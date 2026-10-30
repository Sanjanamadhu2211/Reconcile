import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.logging import JsonFormatter
from app.main import app

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
EXPORT = "/api/v1/workspaces/{}/exports/matches.csv"
PASSWORD = "correct horse battery"
WEB_ORIGIN = {"Origin": "http://localhost:3000"}


def _email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _register(client: TestClient, email: str | None = None):
    return client.post(REGISTER, json={"email": email or _email(), "password": PASSWORD})


def test_unsafe_request_from_the_web_origin_is_allowed():
    client = TestClient(app)

    response = client.post(
        REGISTER, json={"email": _email(), "password": PASSWORD}, headers=WEB_ORIGIN
    )

    assert response.status_code == 201


def test_unsafe_request_from_another_origin_is_rejected():
    client = TestClient(app)

    response = client.post(
        REGISTER,
        json={"email": _email(), "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}


def test_unsafe_request_without_an_origin_header_is_left_to_the_csrf_check():
    client = TestClient(app)
    _register(client)

    response = client.post(LOGOUT)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}


def test_safe_request_from_another_origin_is_not_origin_checked():
    client = TestClient(app)

    response = client.get(ME, headers={"Origin": "https://evil.example"})

    assert response.status_code == 401


def test_every_response_carries_the_security_headers():
    response = TestClient(app).get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Cache-Control" not in response.headers


def test_auth_responses_are_not_cached():
    client = TestClient(app)
    _register(client)

    response = client.get(ME)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_register_is_limited_per_address_and_the_429_leaks_nothing():
    client = TestClient(app)
    statuses = [_register(client).status_code for _ in range(11)]

    assert statuses == [201] * 10 + [429]
    blocked = _register(client)
    assert blocked.json() == {"detail": "Too many requests, try again later"}
    assert int(blocked.headers["Retry-After"]) > 0


def test_export_limit_is_per_user_and_resets_for_another_user():
    first = TestClient(app)
    _register(first)
    workspace_url = EXPORT.format(uuid.uuid4())
    statuses = [first.get(workspace_url).status_code for _ in range(31)]

    assert statuses == [404] * 30 + [429]
    second = TestClient(app)
    _register(second)
    assert second.get(workspace_url).status_code == 404


def test_request_and_exception_logs_never_contain_credentials(caplog):
    caplog.set_level(logging.INFO)
    client = TestClient(app)
    email = _email()
    _register(client, email)
    session_cookie = client.cookies["session"]
    csrf_token = client.cookies["csrf_token"]
    assert client.post(LOGIN, json={"email": email, "password": PASSWORD}).status_code == 200
    assert (
        client.post(LOGIN, json={"email": email, "password": "wrong password"}).status_code == 401
    )
    try:
        raise RuntimeError("upstream failed")
    except RuntimeError:
        logging.getLogger("app.test").exception(
            "exchange failed", extra={"password": PASSWORD, "csrf_token": csrf_token}
        )

    logged = "\n".join(JsonFormatter().format(record) for record in caplog.records)

    assert any(record.getMessage() == "request" for record in caplog.records)
    assert PASSWORD not in logged
    assert "wrong password" not in logged
    assert session_cookie not in logged
    assert csrf_token not in logged
    assert "[redacted]" in logged


def test_uvicorn_access_log_is_off_so_callback_query_strings_are_not_printed():
    assert logging.getLogger("uvicorn.access").disabled
