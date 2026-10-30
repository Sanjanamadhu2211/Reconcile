import contextvars
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import Response

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

logger = logging.getLogger(__name__)

STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|authorization|cookie|csrf|session|api_key", re.IGNORECASE
)


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in STANDARD_RECORD_FIELDS and key not in payload:
                payload[key] = "[redacted]" if SENSITIVE_KEY.search(key) else redact(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn's access line prints the query string, which holds the Google callback code and state
    logging.getLogger("uvicorn.access").disabled = True


def add_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_and_log(request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 128 else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)
