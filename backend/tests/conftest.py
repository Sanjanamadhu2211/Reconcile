import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.auth.rate_limit import request_limiter
from app.db import get_session_factory
from app.main import app

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/reconcile_test"
)


@pytest.fixture(autouse=True)
def fresh_request_limits():
    # Every TestClient shares one client address, so per-IP buckets would leak between tests
    request_limiter.clear()


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    with get_session_factory()() as session:
        try:
            session.execute(text("SELECT 1"))
        except OperationalError:
            pytest.skip("no PostgreSQL reachable at DATABASE_URL")
        yield session
