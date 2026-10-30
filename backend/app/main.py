from fastapi import FastAPI

from app.logging import add_request_logging, configure_logging
from app.routers import (
    auth,
    google_auth,
    health,
    imports,
    organizations,
    reconciliation_results,
    reconciliation_runs,
    workspaces,
)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Reconcile")
    add_request_logging(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(google_auth.router)
    app.include_router(organizations.router)
    app.include_router(workspaces.router)
    app.include_router(imports.router)
    app.include_router(reconciliation_results.router)
    app.include_router(reconciliation_runs.router)
    return app


app = create_app()
