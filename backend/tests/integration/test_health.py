from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_db

pytestmark = pytest.mark.integration


def test_health_ok_with_real_database(client, db):
    assert db.execute(text("SELECT 1")).scalar() == 1

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_degraded_when_database_fails(client):
    def unreachable_database():
        session = MagicMock()
        session.execute.side_effect = OperationalError(
            "SELECT 1", {}, Exception("password authentication failed for user postgres")
        )
        yield session

    client.app.dependency_overrides[get_db] = unreachable_database

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "down"}
    assert "password" not in response.text
