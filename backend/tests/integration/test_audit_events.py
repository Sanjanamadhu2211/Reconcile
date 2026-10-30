import uuid

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from alembic import command
from app.audit import record
from app.config import get_settings
from app.db import get_engine, get_session_factory
from app.models import User

pytestmark = pytest.mark.integration

AUDIT_INSERT = text(
    """
    INSERT INTO audit_events (
        organization_id, actor_email, action, target_type, target_id
    )
    VALUES (:org_id, 'system', :action, :target_type, :target_id)
    RETURNING id
    """
)
RESOLUTION_INSERT = text(
    """
    INSERT INTO resolutions (
        organization_id, exception_id, decision, exception_version
    )
    VALUES (:org_id, :exception_id, :decision, 1)
    """
)


def _organization_id() -> uuid.UUID:
    with get_engine().begin() as conn:
        return conn.execute(
            text("INSERT INTO organizations (name) VALUES ('Audit org') RETURNING id")
        ).scalar_one()


def _exception_id(org_id: uuid.UUID) -> uuid.UUID:
    with get_engine().begin() as conn:
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) "
                "VALUES (:org_id, 'Audit') RETURNING id"
            ),
            {"org_id": org_id},
        ).scalar_one()
        run_id = conn.execute(
            text(
                "INSERT INTO reconciliation_runs (organization_id, workspace_id, rule_version, "
                "tolerance_hours) VALUES (:org_id, :workspace_id, 'v1', 24) RETURNING id"
            ),
            {"org_id": org_id, "workspace_id": workspace_id},
        ).scalar_one()
        batch_id = conn.execute(
            text(
                "INSERT INTO import_batches (organization_id, workspace_id, source_name, "
                "file_size_bytes, file_checksum) "
                "VALUES (:org_id, :workspace_id, 'orders', 10, :checksum) RETURNING id"
            ),
            {"org_id": org_id, "workspace_id": workspace_id, "checksum": uuid.uuid4().hex},
        ).scalar_one()
        row_id = conn.execute(
            text(
                "INSERT INTO import_rows (organization_id, import_batch_id, row_number, payload, "
                "validation_status) VALUES (:org_id, :batch_id, 1, '{}', 'VALID') RETURNING id"
            ),
            {"org_id": org_id, "batch_id": batch_id},
        ).scalar_one()
        return conn.execute(
            text(
                "INSERT INTO exceptions (organization_id, workspace_id, reconciliation_run_id, "
                "category, import_row_id) "
                "VALUES (:org_id, :workspace_id, :run_id, 'unmatched', :row_id) RETURNING id"
            ),
            {"org_id": org_id, "workspace_id": workspace_id, "run_id": run_id, "row_id": row_id},
        ).scalar_one()


def _insert_event(org_id: uuid.UUID) -> uuid.UUID:
    with get_engine().begin() as conn:
        return conn.execute(
            AUDIT_INSERT,
            {
                "org_id": org_id,
                "action": "import.created",
                "target_type": "import_batch",
                "target_id": uuid.uuid4(),
            },
        ).scalar_one()


def _event_count(target_id: uuid.UUID) -> int:
    with get_engine().begin() as conn:
        return conn.execute(
            text("SELECT count(*) FROM audit_events WHERE target_id = :target_id"),
            {"target_id": target_id},
        ).scalar_one()


def test_update_delete_and_truncate_are_rejected_for_the_owner():
    event_id = _insert_event(_organization_id())

    for statement in (
        "UPDATE audit_events SET action = 'import.failed' WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(DBAPIError, match="append-only"), get_engine().begin() as conn:
            conn.execute(text(statement), {"id": event_id})


def test_app_role_can_insert_and_select_but_not_update_or_delete():
    org_id = _organization_id()
    login_role = f"audit_login_{uuid.uuid4().hex}"
    with get_engine().begin() as conn:
        conn.execute(text(f"CREATE ROLE {login_role} LOGIN"))
        conn.execute(text(f"GRANT reconcile_app TO {login_role}"))
    app_engine = create_engine(make_url(get_settings().database_url).set(username=login_role))

    try:
        with app_engine.begin() as conn:
            event_id = conn.execute(
                AUDIT_INSERT,
                {
                    "org_id": org_id,
                    "action": "import.created",
                    "target_type": "import_batch",
                    "target_id": uuid.uuid4(),
                },
            ).scalar_one()
            assert (
                conn.execute(
                    text("SELECT count(*) FROM audit_events WHERE id = :id"), {"id": event_id}
                ).scalar_one()
                == 1
            )

        for statement in (
            "UPDATE audit_events SET action = 'import.failed' WHERE id = :id",
            "DELETE FROM audit_events WHERE id = :id",
        ):
            with (
                pytest.raises(ProgrammingError, match="permission denied"),
                app_engine.begin() as conn,
            ):
                conn.execute(text(statement), {"id": event_id})
    finally:
        app_engine.dispose()
        with get_engine().begin() as conn:
            conn.execute(text(f"DROP ROLE {login_role}"))


def test_record_commits_and_rolls_back_with_the_callers_transaction():
    org_id = _organization_id()
    rolled_back_target = uuid.uuid4()
    committed_target = uuid.uuid4()

    session = get_session_factory()()
    try:
        record(
            session,
            organization_id=org_id,
            actor=None,
            action="import.created",
            target_type="import_batch",
            target_id=rolled_back_target,
        )
        session.rollback()
        assert _event_count(rolled_back_target) == 0

        record(
            session,
            organization_id=org_id,
            actor=None,
            action="import.completed",
            target_type="import_batch",
            target_id=committed_target,
        )
        session.commit()
    finally:
        session.close()
    assert _event_count(committed_target) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"action": "import.deleted"}, {"target_type": "user"}, {"org_id": None}],
)
def test_database_rejects_unknown_actions_and_missing_organization(overrides):
    params = {
        "org_id": _organization_id(),
        "action": "import.created",
        "target_type": "import_batch",
        "target_id": uuid.uuid4(),
        **overrides,
    }

    with pytest.raises(IntegrityError), get_engine().begin() as conn:
        conn.execute(AUDIT_INSERT, params)


def test_resolution_rejects_unknown_decision():
    org_id = _organization_id()
    exception_id = _exception_id(org_id)

    with get_engine().begin() as conn:
        conn.execute(
            RESOLUTION_INSERT,
            {"org_id": org_id, "exception_id": exception_id, "decision": "propose"},
        )
    with pytest.raises(IntegrityError), get_engine().begin() as conn:
        conn.execute(
            RESOLUTION_INSERT,
            {"org_id": org_id, "exception_id": exception_id, "decision": "close"},
        )


def test_deleting_the_actor_keeps_the_audit_row():
    email = f"{uuid.uuid4()}@example.com"
    org_id = _organization_id()
    target_id = uuid.uuid4()

    session = get_session_factory()()
    try:
        user = User(email=email, password_hash="hash")
        session.add(user)
        session.flush()
        user_id = user.id
        record(
            session,
            organization_id=org_id,
            actor=user,
            action="exception.approved",
            target_type="exception",
            target_id=target_id,
        )
        session.commit()
    finally:
        session.close()

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        row = conn.execute(
            text(
                "SELECT actor_user_id, actor_email FROM audit_events WHERE target_id = :target_id"
            ),
            {"target_id": target_id},
        ).one()

    assert row == (None, email)


def test_audit_migration_downgrades_to_0003_and_back():
    config = Config("alembic.ini")

    command.downgrade(config, "0003_reconciliation")
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT to_regclass('audit_events')")).scalar_one() is None
        assert conn.execute(text("SELECT to_regclass('resolutions')")).scalar_one() is None
        assert (
            conn.execute(text("SELECT to_regproc('reject_audit_event_change')")).scalar_one()
            is None
        )

    command.upgrade(config, "head")
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT to_regclass('audit_events')")).scalar_one() is not None
