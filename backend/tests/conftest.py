import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_session_factory
from app.main import app

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/reconcile_test"
)


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
