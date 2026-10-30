import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.google import AUTHORIZATION_URL, GoogleLoginError, GoogleProvider
from app.config import Settings, get_settings
from app.main import app
from app.models import User
from app.routers.google_auth import get_google_provider

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/google/login"
CALLBACK = "/api/v1/auth/google/callback"
PROVIDERS = "/api/v1/auth/providers"
REGISTER = "/api/v1/auth/register"
PASSWORD = "correct horse battery"
CLIENT_ID = "test-client.apps.googleusercontent.com"


class FakeGoogleProvider(GoogleProvider):
    def __init__(self):
        super().__init__(
            Settings(
                google_client_id=CLIENT_ID,
                google_client_secret="secret",
                google_redirect_uri="http://testserver/api/v1/auth/google/callback",
            )
        )
        self.claims = {}

    async def fetch_claims(self, code, code_verifier):
        if code != "good-code":
            raise GoogleLoginError("provider_error")
        return self.claims


@pytest.fixture
def google():
    provider = FakeGoogleProvider()
    app.dependency_overrides[get_google_provider] = lambda: provider
    yield provider
    app.dependency_overrides.clear()


def _email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _claims(nonce, **overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": 4_102_444_800,
        "nonce": nonce,
        "sub": str(uuid.uuid4()),
        "email": _email(),
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def _start_login(client: TestClient) -> tuple[str, str]:
    response = client.get(LOGIN, follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], query["nonce"][0]


def _callback(client: TestClient, state: str, code: str = "good-code"):
    return client.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)


def _cookie_names(response) -> set[str]:
    return {header.split("=", 1)[0] for header in response.headers.get_list("set-cookie")}


def _error(response) -> str:
    return parse_qs(urlparse(response.headers["location"]).query)["error"][0]


def _user_by_sub(db, sub: str) -> User | None:
    return db.scalar(select(User).where(User.google_sub == sub))


def test_login_redirects_to_google_with_pkce(google):
    response = TestClient(app).get(LOGIN, follow_redirects=False)

    query = parse_qs(urlparse(response.headers["location"]).query)
    assert response.status_code == 302
    assert response.headers["location"].startswith(AUTHORIZATION_URL)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0] and query["nonce"][0] and query["code_challenge"][0]
    assert "oauth_tx" in _cookie_names(response)


def test_new_google_user_is_created_and_signed_in(google, db):
    client = TestClient(app)
    state, nonce = _start_login(client)
    sub = str(uuid.uuid4())
    google.claims = _claims(nonce, sub=sub)

    response = _callback(client, state)

    user = _user_by_sub(db, sub)
    assert response.status_code == 302
    assert response.headers["location"] == f"{get_settings().web_origin}/"
    assert {"session", "csrf_token"} <= _cookie_names(response)
    assert user is not None and user.password_hash is None


def test_second_login_returns_the_same_user(google, db):
    sub = str(uuid.uuid4())
    for _ in range(2):
        client = TestClient(app)
        state, nonce = _start_login(client)
        google.claims = _claims(nonce, sub=sub)
        _callback(client, state)

    rows = db.scalars(select(User).where(User.google_sub == sub)).all()
    assert len(rows) == 1


def test_verified_email_links_existing_password_user(google, db):
    email = _email()
    registered = TestClient(app).post(REGISTER, json={"email": email, "password": PASSWORD})
    client = TestClient(app)
    state, nonce = _start_login(client)
    sub = str(uuid.uuid4())
    google.claims = _claims(nonce, sub=sub, email=email.upper())

    response = _callback(client, state)

    user = _user_by_sub(db, sub)
    assert response.status_code == 302
    assert str(user.id) == registered.json()["id"]
    assert user.password_hash is not None


def test_unverified_email_never_links_and_creates_no_session(google, db):
    email = _email()
    TestClient(app).post(REGISTER, json={"email": email, "password": PASSWORD})
    client = TestClient(app)
    state, nonce = _start_login(client)
    sub = str(uuid.uuid4())
    google.claims = _claims(nonce, sub=sub, email=email, email_verified=False)

    response = _callback(client, state)

    linked = db.scalar(select(User).where(User.email == email))
    assert _error(response) == "google_unverified_email"
    assert "session" not in _cookie_names(response)
    assert linked.google_sub is None
    assert _user_by_sub(db, sub) is None


@pytest.mark.parametrize(
    "overrides, expected_error",
    [
        ({"aud": "someone-else"}, "google_invalid_token"),
        ({"nonce": "not-the-nonce"}, "google_invalid_token"),
    ],
)
def test_invalid_id_token_is_rejected(google, overrides, expected_error):
    client = TestClient(app)
    state, nonce = _start_login(client)
    google.claims = {**_claims(nonce), **overrides}

    response = _callback(client, state)

    assert _error(response) == expected_error
    assert "session" not in _cookie_names(response)


def test_forged_state_is_rejected(google):
    client = TestClient(app)
    _start_login(client)
    google.claims = _claims("unused")

    response = _callback(client, "forged-state")

    assert _error(response) == "google_invalid_state"
    assert "session" not in _cookie_names(response)


def test_missing_transaction_cookie_is_rejected(google):
    client = TestClient(app)
    state, nonce = _start_login(client)
    client.cookies.clear()
    google.claims = _claims(nonce)

    response = _callback(client, state)

    assert _error(response) == "google_invalid_state"
    assert "session" not in _cookie_names(response)


def test_same_email_with_different_google_sub_is_a_conflict(google, db):
    email = _email()
    db.add(User(email=email, google_sub=str(uuid.uuid4())))
    db.commit()
    client = TestClient(app)
    state, nonce = _start_login(client)
    google.claims = _claims(nonce, email=email)

    response = _callback(client, state)

    assert _error(response) == "google_account_conflict"
    assert "session" not in _cookie_names(response)


def test_google_sign_in_is_off_without_settings():
    app.dependency_overrides[get_google_provider] = lambda: GoogleProvider(Settings())
    try:
        client = TestClient(app)

        assert client.get(PROVIDERS).json() == {"google": False}
        assert client.get(LOGIN, follow_redirects=False).status_code == 503
        assert client.get(CALLBACK, follow_redirects=False).status_code == 503
    finally:
        app.dependency_overrides.clear()
