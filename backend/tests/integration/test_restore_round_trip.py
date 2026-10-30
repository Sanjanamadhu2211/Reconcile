import io
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import backup_db  # noqa: E402
import pg_tools  # noqa: E402
import restore_db  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_session_factory  # noqa: E402
from app.imports import create_or_get_batch, process_batch  # noqa: E402
from app.models import Organization, User, Workspace  # noqa: E402
from app.reconciliation.runner import run_reconciliation  # noqa: E402

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reconciliation"
SOURCES = ["orders", "payments", "refunds", "settlements", "fees"]
TRIGGERS = {"audit_events_append_only", "audit_events_no_truncate"}


def _pg_tools_found() -> bool:
    try:
        pg_tools.find_pg_tool("pg_dump")
        pg_tools.find_pg_tool("pg_restore")
    except pg_tools.PgToolError:
        return False
    return True


requires_pg_tools = pytest.mark.skipif(
    not _pg_tools_found(),
    reason="pg_dump and pg_restore were not found; put them on PATH or set PG_BIN_DIR",
)


@pytest.fixture
def workspace_with_run(db):
    org = Organization(name=f"Org {uuid.uuid4()}")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="unused")
    db.add_all([org, user])
    db.flush()
    workspace = Workspace(organization_id=org.id, name=f"Ledger {uuid.uuid4()}", created_by=user.id)
    db.add(workspace)
    db.commit()
    for source in SOURCES:
        data = (FIXTURES / f"{source}.csv").read_bytes()
        batch, _ = create_or_get_batch(
            db,
            user=user,
            workspace=workspace,
            source_name=source,
            filename=f"{source}.csv",
            stream=io.BytesIO(data),
        )
        process_batch(get_session_factory(), batch.id, io.BytesIO(data), max_rows=None)
    run_reconciliation(get_session_factory(), workspace_id=workspace.id, user_id=user.id)


@pytest.fixture
def empty_database():
    source = make_url(get_settings().database_url)
    name = f"reconcile_restore_{uuid.uuid4().hex[:12]}"
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield source.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _unique_constraints(url: str) -> set[tuple[str, str, tuple[str, ...]]]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            insp = inspect(conn)
            return {
                (table, uq["name"], tuple(uq["column_names"]))
                for table in insp.get_table_names()
                for uq in insp.get_unique_constraints(table)
            }
    finally:
        engine.dispose()


def _trigger_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return set(
                conn.execute(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid = 'audit_events'::regclass AND NOT tgisinternal"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()


@requires_pg_tools
def test_restore_round_trip_reproduces_the_database(workspace_with_run, tmp_path, empty_database):
    source_url = get_settings().database_url
    dump = backup_db.backup(source_url, tmp_path, datetime.now(UTC))

    restore_db.restore(dump, empty_database, force=False)

    source_counts = restore_db.row_counts(source_url)
    target_counts = restore_db.row_counts(empty_database)
    assert target_counts == source_counts
    assert target_counts["matches"] > 0
    assert target_counts["exceptions"] > 0

    assert TRIGGERS <= _trigger_names(empty_database)
    source_unique = _unique_constraints(source_url)
    assert source_unique
    assert _unique_constraints(empty_database) == source_unique

    engine = create_engine(empty_database)
    try:
        with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("UPDATE audit_events SET actor_user_id = NULL"))
    finally:
        engine.dispose()


@requires_pg_tools
def test_restore_refuses_a_target_that_is_not_empty(workspace_with_run, tmp_path, empty_database):
    dump = backup_db.backup(get_settings().database_url, tmp_path, datetime.now(UTC))
    restore_db.restore(dump, empty_database, force=False)

    with pytest.raises(restore_db.RestoreError, match="already has"):
        restore_db.restore(dump, empty_database, force=False)
