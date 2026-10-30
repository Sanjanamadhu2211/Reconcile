import secrets

from fastapi import Response

from app.auth.csrf import CSRF_COOKIE
from app.auth.sessions import SESSION_LIFETIME
from app.config import get_settings

SESSION_COOKIE = "session"
OAUTH_TX_COOKIE = "oauth_tx"
OAUTH_TX_PATH = "/api/v1/auth/google"
OAUTH_TX_MAX_AGE = 10 * 60
MAX_AGE = int(SESSION_LIFETIME.total_seconds())


def secure_cookies() -> bool:
    return get_settings().env != "development"


def set_auth_cookies(response: Response, session_token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=MAX_AGE,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=MAX_AGE,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


def set_oauth_tx_cookie(response: Response, value: str, *, secure: bool) -> None:
    response.set_cookie(
        OAUTH_TX_COOKIE,
        value,
        max_age=OAUTH_TX_MAX_AGE,
        path=OAUTH_TX_PATH,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def clear_oauth_tx_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        OAUTH_TX_COOKIE, path=OAUTH_TX_PATH, secure=secure, httponly=True, samesite="lax"
    )
