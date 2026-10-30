import hmac
from typing import Annotated

from fastapi import Cookie, Header, HTTPException

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def require_csrf(
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> None:
    # compare_digest rejects non-ASCII str, so both sides are compared as bytes
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    if not hmac.compare_digest(csrf_cookie.encode(), csrf_header.encode()):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
