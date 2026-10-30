from fastapi import FastAPI

from app.logging import add_request_logging, configure_logging
from app.routers import health


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Reconcile")
    add_request_logging(app)
    app.include_router(health.router)
    return app


app = create_app()
