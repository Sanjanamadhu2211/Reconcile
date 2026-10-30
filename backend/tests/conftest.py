import os

import pytest
from fastapi.testclient import TestClient

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
        yield session
