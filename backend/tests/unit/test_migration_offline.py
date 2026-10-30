import pytest
from alembic.config import Config

from alembic import command
from app.config import get_settings

DUMMY_URL = "postgresql+psycopg://user:password@localhost/unused"
TABLES = (
    "users",
    "organizations",
    "organization_memberships",
    "workspaces",
    "sessions",
    "import_batches",
    "import_rows",
    "transactions",
    "reconciliation_runs",
    "matches",
    "exceptions",
    "resolutions",
    "audit_events",
)


@pytest.fixture
def offline_config(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DUMMY_URL)
    monkeypatch.delenv("DATABASE_DIRECT_URL", raising=False)
    get_settings.cache_clear()
    yield Config("alembic.ini")
    get_settings.cache_clear()


def test_offline_upgrade_creates_the_thirteen_tables(offline_config, capsys):
    command.upgrade(offline_config, "head", sql=True)

    sql = capsys.readouterr().out
    for table in TABLES:
        assert f"CREATE TABLE {table} (" in sql
    assert "CREATE FUNCTION reject_audit_event_change()" in sql
    assert "CREATE TRIGGER audit_events_append_only" in sql
    assert "CREATE TRIGGER audit_events_no_truncate" in sql


def test_offline_downgrade_drops_the_thirteen_tables(offline_config, capsys):
    command.downgrade(offline_config, "head:base", sql=True)

    sql = capsys.readouterr().out
    for table in TABLES:
        assert f"DROP TABLE {table};" in sql
    assert "DROP FUNCTION reject_audit_event_change()" in sql
