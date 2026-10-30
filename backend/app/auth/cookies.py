import secrets

from fastapi import Response

from app.auth.csrf import CSRF_COOKIE
from app.auth.sessions import SESSION_LIFETIME

SESSION_COOKIE = "session"
MAX_AGE = int(SESSION_LIFETIME.total_seconds())


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
