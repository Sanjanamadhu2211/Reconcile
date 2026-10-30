from fastapi import Response

from app.auth.cookies import clear_auth_cookies, set_auth_cookies


def _attributes(set_cookie: str) -> set[str]:
    return {part.strip().lower() for part in set_cookie.split(";")}


def test_session_cookie_is_httponly_lax_and_host_only():
    response = Response()

    set_auth_cookies(response, "token", secure=True)

    session_cookie, csrf_cookie = response.headers.getlist("set-cookie")
    assert session_cookie.startswith("session=token;")
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= _attributes(session_cookie)
    assert not any(attr.startswith("domain=") for attr in _attributes(session_cookie))
    assert "httponly" not in _attributes(csrf_cookie)
    assert "samesite=lax" in _attributes(csrf_cookie)


def test_cookies_are_not_secure_in_development():
    response = Response()

    set_auth_cookies(response, "token", secure=False)
    clear_auth_cookies(response, secure=False)

    assert all(
        "secure" not in _attributes(cookie) for cookie in response.headers.getlist("set-cookie")
    )
