from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def allowed_origin() -> str:
    parts = urlsplit(get_settings().web_origin)
    return f"{parts.scheme}://{parts.netloc}"


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def origin_check_and_headers(request: Request, call_next) -> Response:
        # Defence in depth: browsers send Origin on unsafe requests; CSRF stays the real check
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin is not None and origin != allowed_origin():
            response = JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response
