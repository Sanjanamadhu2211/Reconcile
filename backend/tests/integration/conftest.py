import pytest
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from alembic import command
from app.db import get_engine


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    try:
        with get_engine().connect():
            pass
    except OperationalError:
        pytest.skip("no PostgreSQL reachable at DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
