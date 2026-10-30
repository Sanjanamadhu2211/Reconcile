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

TABLES = {
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
}


BATCH_INSERT = text(
    """
    INSERT INTO import_batches (
        organization_id, workspace_id, source_name, file_size_bytes, file_checksum, idempotency_key
    )
    VALUES (:org_id, :workspace_id, 'orders', 10, :checksum, :idempotency_key)
    RETURNING id
    """
)
TRANSACTION_INSERT = text(
    """
    INSERT INTO transactions (
        organization_id, workspace_id, import_batch_id, source_name, external_id,
        amount, currency, transaction_type, occurred_at
    )
    VALUES (
        :org_id, :workspace_id, :batch_id, 'orders', :external_id,
        100.00, :currency, 'payment', now()
    )
    RETURNING id
    """
)
RECONCILIATION_RUN_INSERT = text(
    """
    INSERT INTO reconciliation_runs (
        organization_id, workspace_id, rule_version, tolerance_hours
    )
    VALUES (:org_id, :workspace_id, :rule_version, :tolerance_hours)
    RETURNING id
    """
)
MATCH_INSERT = text(
    """
    INSERT INTO matches (
        organization_id, reconciliation_run_id, rule, left_transaction_id, right_transaction_id
    )
    VALUES (:org_id, :run_id, :rule, :left_id, :right_id)
    """
)
EXCEPTION_INSERT = text(
    """
    INSERT INTO exceptions (
        organization_id, workspace_id, reconciliation_run_id, category, transaction_id
    )
    VALUES (:org_id, :workspace_id, :run_id, :category, :transaction_id)
    """
)


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


def test_import_and_transaction_constraints():
    command.upgrade(Config("alembic.ini"), "head")

    with get_engine().begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Imports org') RETURNING id")
        ).scalar_one()
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) "
                "VALUES (:org_id, 'Imports') RETURNING id"
            ),
            {"org_id": org_id},
        ).scalar_one()

        batch = {
            "org_id": org_id,
            "workspace_id": workspace_id,
            "checksum": "abc123",
            "idempotency_key": None,
        }
        conn.execute(BATCH_INSERT, batch)
        conn.execute(BATCH_INSERT, {**batch, "checksum": "def456"})
        batch_id = conn.execute(
            BATCH_INSERT, {**batch, "checksum": "ghi789", "idempotency_key": "key-1"}
        ).scalar_one()

        transaction = {
            "org_id": org_id,
            "workspace_id": workspace_id,
            "batch_id": batch_id,
            "external_id": "PAY-001",
            "currency": "USD",
        }
        conn.execute(TRANSACTION_INSERT, transaction)

    rejected = [
        (BATCH_INSERT, {**batch, "checksum": "abc123"}),
        (BATCH_INSERT, {**batch, "checksum": "jkl012", "idempotency_key": "key-1"}),
        (BATCH_INSERT, {**batch, "checksum": "mno345", "org_id": None}),
        (TRANSACTION_INSERT, transaction),
        (TRANSACTION_INSERT, {**transaction, "external_id": "PAY-002", "currency": "usd"}),
    ]
    for statement, params in rejected:
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(statement, params)


def test_reconciliation_run_constraints():
    command.upgrade(Config("alembic.ini"), "head")

    with get_engine().begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Recon org') RETURNING id")
        ).scalar_one()
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) "
                "VALUES (:org_id, 'Recon') RETURNING id"
            ),
            {"org_id": org_id},
        ).scalar_one()

        run = {
            "org_id": org_id,
            "workspace_id": workspace_id,
            "rule_version": "v1",
            "tolerance_hours": 24,
        }
        conn.execute(RECONCILIATION_RUN_INSERT, run)

    rejected = [
        (RECONCILIATION_RUN_INSERT, {**run, "tolerance_hours": 0}),
        (RECONCILIATION_RUN_INSERT, {**run, "org_id": None}),
    ]
    for statement, params in rejected:
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(statement, params)


def test_match_constraints():
    command.upgrade(Config("alembic.ini"), "head")

    with get_engine().begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Match org') RETURNING id")
        ).scalar_one()
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) "
                "VALUES (:org_id, 'Match') RETURNING id"
            ),
            {"org_id": org_id},
        ).scalar_one()
        run_id = conn.execute(
            RECONCILIATION_RUN_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "rule_version": "v1",
                "tolerance_hours": 24,
            },
        ).scalar_one()

        batch_id = conn.execute(
            BATCH_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "checksum": "abc123",
                "idempotency_key": None,
            },
        ).scalar_one()

        left_id = conn.execute(
            TRANSACTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "external_id": "LEFT-1",
                "currency": "USD",
            },
        ).scalar_one()
        right_id = conn.execute(
            TRANSACTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "external_id": "RIGHT-1",
                "currency": "USD",
            },
        ).scalar_one()
        other_right_id = conn.execute(
            TRANSACTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "external_id": "RIGHT-2",
                "currency": "USD",
            },
        ).scalar_one()

        conn.execute(
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id,
                "rule": "exact_id",
                "left_id": left_id,
                "right_id": right_id,
            },
        )

    rejected = [
        # same left_transaction_id in same run
        (
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id,
                "rule": "amount_currency_time",
                "left_id": left_id,
                "right_id": other_right_id,
            },
        ),
        # same right_transaction_id in same run
        (
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id,
                "rule": "amount_currency_time",
                "left_id": other_right_id,
                "right_id": right_id,
            },
        ),
        # left == right
        (
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id,
                "rule": "exact_id",
                "left_id": left_id,
                "right_id": left_id,
            },
        ),
        # invalid rule
        (
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id,
                "rule": "invalid_rule",
                "left_id": left_id,
                "right_id": right_id,
            },
        ),
        # NULL organization_id
        (
            MATCH_INSERT,
            {
                "org_id": None,
                "run_id": run_id,
                "rule": "exact_id",
                "left_id": left_id,
                "right_id": right_id,
            },
        ),
    ]
    for statement, params in rejected:
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(statement, params)

    # But same transaction CAN be left in one match and right in another
    with get_engine().begin() as conn:
        run_id2 = conn.execute(
            RECONCILIATION_RUN_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "rule_version": "v1",
                "tolerance_hours": 24,
            },
        ).scalar_one()
        conn.execute(
            MATCH_INSERT,
            {
                "org_id": org_id,
                "run_id": run_id2,
                "rule": "exact_id",
                "left_id": right_id,
                "right_id": left_id,
            },
        )


def test_exception_constraints():
    command.upgrade(Config("alembic.ini"), "head")

    with get_engine().begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Exception org') RETURNING id")
        ).scalar_one()
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) "
                "VALUES (:org_id, 'Exception') RETURNING id"
            ),
            {"org_id": org_id},
        ).scalar_one()
        run_id = conn.execute(
            RECONCILIATION_RUN_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "rule_version": "v1",
                "tolerance_hours": 24,
            },
        ).scalar_one()

        batch_id = conn.execute(
            BATCH_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "checksum": "abc123",
                "idempotency_key": None,
            },
        ).scalar_one()

        txn_id = conn.execute(
            TRANSACTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "external_id": "TXN-1",
                "currency": "USD",
            },
        ).scalar_one()

        import_row_id = conn.execute(
            text(
                "INSERT INTO import_rows (organization_id, import_batch_id, "
                "row_number, payload, validation_status) "
                "VALUES (:org_id, :batch_id, 1, '{}', 'VALID') RETURNING id"
            ),
            {"org_id": org_id, "batch_id": batch_id},
        ).scalar_one()

        conn.execute(
            EXCEPTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "unmatched",
                "transaction_id": txn_id,
            },
        )

    rejected = [
        # duplicate (run, transaction_id)
        (
            EXCEPTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "ambiguous",
                "transaction_id": txn_id,
            },
        ),
        # neither transaction_id nor import_row_id
        (
            EXCEPTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "unmatched",
                "transaction_id": None,
            },
        ),
        # invalid category
        (
            EXCEPTION_INSERT,
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "invalid",
                "transaction_id": txn_id,
            },
        ),
        # invalid status (via raw insert bypassing default)
        (
            text(
                "INSERT INTO exceptions (organization_id, workspace_id, "
                "reconciliation_run_id, category, transaction_id, status) "
                "VALUES (:org_id, :workspace_id, :run_id, :category, "
                ":transaction_id, 'invalid')"
            ),
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "unmatched",
                "transaction_id": txn_id,
            },
        ),
        # NULL organization_id
        (
            EXCEPTION_INSERT,
            {
                "org_id": None,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "category": "unmatched",
                "transaction_id": txn_id,
            },
        ),
    ]
    for statement, params in rejected:
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(statement, params)

    # But different import_row_id is allowed
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO exceptions (organization_id, workspace_id, "
                "reconciliation_run_id, category, import_row_id) "
                "VALUES (:org_id, :workspace_id, :run_id, 'duplicate', :import_row_id)"
            ),
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "import_row_id": import_row_id,
            },
        )

    # And duplicate (run, import_row_id) is rejected
    rejected_import = [
        (
            text(
                "INSERT INTO exceptions (organization_id, workspace_id, "
                "reconciliation_run_id, category, import_row_id) "
                "VALUES (:org_id, :workspace_id, :run_id, 'unmatched', :import_row_id)"
            ),
            {
                "org_id": org_id,
                "workspace_id": workspace_id,
                "run_id": run_id,
                "import_row_id": import_row_id,
            },
        ),
    ]
    for statement, params in rejected_import:
        with pytest.raises(IntegrityError), get_engine().begin() as conn:
            conn.execute(statement, params)
