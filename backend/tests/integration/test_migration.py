import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db import get_engine
from app.models import Base

pytestmark = pytest.mark.integration

TABLES = {"users", "organizations", "organization_memberships", "workspaces", "sessions"}


def _table_names() -> set[str]:
    return set(inspect(get_engine()).get_table_names())


def _new_email() -> str:
    return f"{uuid.uuid4()}@example.com"


def test_migration_round_trip_and_constraints():
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert not TABLES & _table_names()

    command.upgrade(config, "head")
    assert TABLES <= _table_names()

    email = _new_email()
    with get_engine().begin() as conn:
        user_id = conn.execute(
            text("INSERT INTO users (email, password_hash) VALUES (:email, 'hash') RETURNING id"),
            {"email": email},
        ).scalar_one()
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Test org') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO organization_memberships (user_id, organization_id, role) "
                "VALUES (:user_id, :org_id, 'analyst')"
            ),
            {"user_id": user_id, "org_id": org_id},
        )
        conn.execute(
            text("INSERT INTO workspaces (organization_id, name) VALUES (:org_id, 'Main')"),
            {"org_id": org_id},
        )

    rejected = [
        ("INSERT INTO users (email) VALUES (:email)", {"email": _new_email()}),
        (
            "INSERT INTO users (email, password_hash) VALUES (:email, 'hash')",
            {"email": email.upper()},
        ),
        (
            "INSERT INTO organization_memberships (user_id, organization_id, role) "
            "VALUES (:user_id, :org_id, 'admin')",
            {"user_id": user_id, "org_id": org_id},
        ),
        (
            "INSERT INTO organization_memberships (user_id, organization_id, role) "
            "VALUES (:user_id, :org_id, 'reviewer')",
            {"user_id": user_id, "org_id": org_id},
        ),
        (
            "INSERT INTO workspaces (organization_id, name) VALUES (:org_id, 'Main')",
            {"org_id": org_id},
        ),
        (
            "INSERT INTO workspaces (organization_id, name, timestamp_tolerance_hours) "
            "VALUES (:org_id, 'Other', 0)",
            {"org_id": org_id},
        ),
    ]
    for statement, params in rejected:
        params = {"user_id": user_id, "org_id": org_id, **params}
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(text(statement), params)


def test_models_match_the_migrated_schema():
    command.upgrade(Config("alembic.ini"), "head")

    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == []
