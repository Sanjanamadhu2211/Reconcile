import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.main import app

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
PASSWORD = "correct horse battery"


def _email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _register(client: TestClient, email: str):
    return client.post(REGISTER, json={"email": email, "password": PASSWORD})


def test_register_then_me():
    client = TestClient(app)
    email = _email()

    registered = _register(client, email)
    me = client.get(ME)

    assert registered.status_code == 201
    assert me.status_code == 200
    assert me.json() == {"id": registered.json()["id"], "email": email}


def test_duplicate_email_in_another_case_is_rejected():
    email = _email()
    assert _register(TestClient(app), email).status_code == 201

    response = _register(TestClient(app), email.upper())

    assert response.status_code == 409


def test_login_sets_session_and_csrf_cookies():
    client = TestClient(app)
    email = _email()
    _register(client, email)
    client.cookies.clear()

    response = client.post(LOGIN, json={"email": email, "password": PASSWORD})

    assert response.status_code == 200
    set_cookies = " ".join(response.headers.get_list("set-cookie"))
    assert "session=" in set_cookies
    assert "csrf_token=" in set_cookies
    assert client.cookies.get("session")


def test_wrong_password_and_unknown_email_return_the_same_401():
    email = _email()
    _register(TestClient(app), email)

    wrong_password = TestClient(app).post(
        LOGIN, json={"email": email, "password": "wrong horse battery"}
    )
    unknown_email = TestClient(app).post(LOGIN, json={"email": _email(), "password": PASSWORD})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_logout_needs_csrf_header_and_deletes_the_session():
    client = TestClient(app)
    _register(client, _email())
    token = client.cookies["session"]

    without_header = client.post(LOGOUT)
    with_header = client.post(LOGOUT, headers={"X-CSRF-Token": client.cookies["csrf_token"]})

    assert without_header.status_code == 403
    assert with_header.status_code == 200
    with get_engine().connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM sessions WHERE token_hash = :hash"),
            {"hash": _digest(token)},
        ).scalar_one()
    assert remaining == 0
    assert client.get(ME).status_code == 401


def test_expired_session_is_rejected():
    client = TestClient(app)
    _register(client, _email())
    token = client.cookies["session"]
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET expires_at = now() - interval '1 second' "
                "WHERE token_hash = :hash"
            ),
            {"hash": _digest(token)},
        )

    response = client.get(ME)

    assert response.status_code == 401


def test_raw_token_is_never_stored():
    client = TestClient(app)
    _register(client, _email())
    token = client.cookies["session"]

    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM sessions")).scalars().all()

    assert token not in stored
    assert _digest(token) in stored


def test_sixth_failed_login_is_rate_limited():
    client = TestClient(app)
    email = _email()
    _register(client, email)
    client.cookies.clear()
    attempts = [
        client.post(LOGIN, json={"email": email, "password": "wrong horse battery"})
        for _ in range(6)
    ]

    assert [attempt.status_code for attempt in attempts] == [401] * 5 + [429]
