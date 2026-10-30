import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import get_engine, get_session_factory
from app.main import app
from app.models import (
    Exception as ExceptionModel,
)
from app.models import (
    ImportBatch,
    ImportRow,
    ReconciliationRun,
)

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
NOW = datetime.now(UTC)
ROW_NUMBERS = itertools.count(1)


def _signed_in_client() -> tuple[TestClient, dict]:
    client = TestClient(app)
    email = f"{uuid.uuid4()}@example.com"
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _create_org(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/organizations", json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()


def _create_workspace(client: TestClient, org_id: str) -> dict:
    response = client.post(
        "/api/v1/workspaces",
        json={"organization_id": org_id, "name": f"Ledger {uuid.uuid4()}"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    return response.json()


def _summary(client: TestClient, workspace_id: str) -> dict:
    response = client.get(f"/api/v1/workspaces/{workspace_id}/summary")
    assert response.status_code == 200
    return response.json()


def _batch(
    db,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    status: str = "completed",
    rows_total: int = 0,
    rows_failed: int = 0,
    created_at: datetime = NOW,
    filename: str | None = None,
) -> ImportBatch:
    batch = ImportBatch(
        organization_id=org_id,
        workspace_id=workspace_id,
        source_name="orders",
        filename=filename,
        file_size_bytes=100,
        file_checksum=f"checksum-{uuid.uuid4()}",
        status=status,
        rows_total=rows_total,
        rows_failed=rows_failed,
        created_at=created_at,
    )
    db.add(batch)
    db.commit()
    return batch


def _run(
    db,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "completed",
    matches: int = 0,
    exceptions: int = 0,
    created_at: datetime = NOW,
    completed_at: datetime | None = NOW,
) -> ReconciliationRun:
    run = ReconciliationRun(
        organization_id=org_id,
        workspace_id=workspace_id,
        rule_version="v1",
        status=status,
        tolerance_hours=24,
        matches_count=matches,
        exceptions_count=exceptions,
        created_by=user_id,
        created_at=created_at,
        completed_at=completed_at,
    )
    db.add(run)
    db.commit()
    return run


def _exceptions(
    db,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID,
    batch: ImportBatch,
    run: ReconciliationRun,
    category: str,
    status: str,
    count: int,
) -> None:
    rows = [
        ImportRow(
            organization_id=org_id,
            import_batch_id=batch.id,
            row_number=next(ROW_NUMBERS),
            payload={},
            validation_status="BAD_AMOUNT",
        )
        for _ in range(count)
    ]
    db.add_all(rows)
    db.flush()
    db.add_all(
        ExceptionModel(
            organization_id=org_id,
            workspace_id=workspace_id,
            reconciliation_run_id=run.id,
            category=category,
            import_row_id=row.id,
            status=status,
        )
        for row in rows
    )
    db.commit()


@pytest.fixture
def workspace():
    owner, owner_user = _signed_in_client()
    org = _create_org(owner)
    ws = _create_workspace(owner, org["id"])
    ids = (uuid.UUID(org["id"]), uuid.UUID(ws["id"]), uuid.UUID(owner_user["id"]))
    return owner, ws["id"], ids


def test_summary_requires_auth():
    response = TestClient(app).get(f"/api/v1/workspaces/{uuid.uuid4()}/summary")

    assert response.status_code == 401


def test_other_tenant_gets_404(workspace):
    _, workspace_id, _ = workspace
    attacker, _ = _signed_in_client()
    _create_org(attacker)

    response = attacker.get(f"/api/v1/workspaces/{workspace_id}/summary")

    assert response.status_code == 404


def test_empty_workspace_is_all_zeros(workspace):
    owner, workspace_id, _ = workspace

    summary = _summary(owner, workspace_id)

    assert summary == {
        "imports": {
            "batches_by_status": {"pending": 0, "processing": 0, "completed": 0, "failed": 0},
            "rows_imported": 0,
            "rows_invalid": 0,
            "recent_batches": [],
        },
        "latest_run": None,
        "exceptions": {
            "by_status": {"open": 0, "proposed": 0, "resolved": 0},
            "by_category": {"unmatched": 0, "ambiguous": 0, "amount_mismatch": 0, "duplicate": 0},
        },
    }


def test_populated_workspace_counts_and_match_rate(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    with get_session_factory()() as db:
        batch = _batch(db, org_id, ws_uuid, rows_total=10, rows_failed=2, filename="a.csv")
        _batch(db, org_id, ws_uuid, rows_total=5, rows_failed=1)
        _batch(db, org_id, ws_uuid, status="failed", rows_total=7, rows_failed=7)
        _batch(db, org_id, ws_uuid, status="pending")
        _batch(db, org_id, ws_uuid, status="processing")
        run = _run(db, org_id, ws_uuid, user_id, matches=3, exceptions=5)
        run_id = run.id
        _exceptions(db, org_id, ws_uuid, batch, run, "unmatched", "open", 1)
        _exceptions(db, org_id, ws_uuid, batch, run, "unmatched", "proposed", 1)
        _exceptions(db, org_id, ws_uuid, batch, run, "ambiguous", "resolved", 1)
        _exceptions(db, org_id, ws_uuid, batch, run, "amount_mismatch", "open", 1)
        _exceptions(db, org_id, ws_uuid, batch, run, "duplicate", "open", 1)

    summary = _summary(owner, workspace_id)

    assert summary["imports"]["batches_by_status"] == {
        "pending": 1,
        "processing": 1,
        "completed": 2,
        "failed": 1,
    }
    assert summary["imports"]["rows_imported"] == 15
    assert summary["imports"]["rows_invalid"] == 3
    assert summary["latest_run"]["id"] == str(run_id)
    assert summary["latest_run"]["matches_count"] == 3
    assert summary["latest_run"]["exceptions_count"] == 5
    # duplicates are not part of the rate: 3 / (3 + 2 + 1 + 1) = 0.428571...
    assert summary["latest_run"]["match_rate"] == "0.4286"
    assert summary["exceptions"] == {
        "by_status": {"open": 3, "proposed": 1, "resolved": 1},
        "by_category": {"unmatched": 2, "ambiguous": 1, "amount_mismatch": 1, "duplicate": 1},
    }


def test_match_rate_rounds_half_up(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    with get_session_factory()() as db:
        batch = _batch(db, org_id, ws_uuid)
        run = _run(db, org_id, ws_uuid, user_id, matches=1, exceptions=31)
        _exceptions(db, org_id, ws_uuid, batch, run, "unmatched", "open", 31)

    summary = _summary(owner, workspace_id)

    # 1 / 32 = 0.03125 rounds up to 0.0313 (banker's rounding would give 0.0312)
    assert summary["latest_run"]["match_rate"] == "0.0313"


def test_match_rate_is_null_without_matches_or_exceptions(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    with get_session_factory()() as db:
        _run(db, org_id, ws_uuid, user_id)

    summary = _summary(owner, workspace_id)

    assert summary["latest_run"]["match_rate"] is None


def test_newer_failed_or_running_run_does_not_replace_latest_completed(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    with get_session_factory()() as db:
        batch = _batch(db, org_id, ws_uuid)
        completed = _run(
            db,
            org_id,
            ws_uuid,
            user_id,
            matches=2,
            exceptions=1,
            created_at=NOW - timedelta(minutes=30),
            completed_at=NOW - timedelta(minutes=20),
        )
        completed_id = completed.id
        _exceptions(db, org_id, ws_uuid, batch, completed, "unmatched", "open", 1)
        failed = _run(
            db,
            org_id,
            ws_uuid,
            user_id,
            status="failed",
            exceptions=4,
            created_at=NOW - timedelta(minutes=10),
            completed_at=None,
        )
        _exceptions(db, org_id, ws_uuid, batch, failed, "unmatched", "open", 4)
        _run(
            db,
            org_id,
            ws_uuid,
            user_id,
            status="running",
            created_at=NOW - timedelta(minutes=1),
            completed_at=None,
        )

    summary = _summary(owner, workspace_id)

    assert summary["latest_run"]["id"] == str(completed_id)
    assert summary["latest_run"]["match_rate"] == "0.6667"
    assert summary["exceptions"]["by_category"]["unmatched"] == 1


def test_exception_counts_come_from_latest_completed_run_only(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    with get_session_factory()() as db:
        batch = _batch(db, org_id, ws_uuid)
        older = _run(
            db,
            org_id,
            ws_uuid,
            user_id,
            exceptions=3,
            created_at=NOW - timedelta(minutes=20),
            completed_at=NOW - timedelta(minutes=15),
        )
        _exceptions(db, org_id, ws_uuid, batch, older, "unmatched", "open", 3)
        newer = _run(
            db,
            org_id,
            ws_uuid,
            user_id,
            exceptions=1,
            created_at=NOW - timedelta(minutes=10),
            completed_at=NOW - timedelta(minutes=5),
        )
        _exceptions(db, org_id, ws_uuid, batch, newer, "duplicate", "resolved", 1)
        newer_id = newer.id

    summary = _summary(owner, workspace_id)

    assert summary["latest_run"]["id"] == str(newer_id)
    assert summary["exceptions"]["by_category"] == {
        "unmatched": 0,
        "ambiguous": 0,
        "amount_mismatch": 0,
        "duplicate": 1,
    }
    assert summary["exceptions"]["by_status"] == {"open": 0, "proposed": 0, "resolved": 1}


def test_recent_batches_are_the_five_newest_first(workspace):
    owner, workspace_id, (org_id, ws_uuid, _) = workspace
    with get_session_factory()() as db:
        batches = [
            _batch(
                db,
                org_id,
                ws_uuid,
                rows_total=index,
                created_at=NOW - timedelta(minutes=index),
            )
            for index in range(7)
        ]
        newest_ids = [str(batch.id) for batch in batches[:5]]

    summary = _summary(owner, workspace_id)

    recent = summary["imports"]["recent_batches"]
    assert [batch["id"] for batch in recent] == newest_ids
    assert recent[0]["rows_total"] == 0
    assert set(recent[0]) == {
        "id",
        "source_name",
        "filename",
        "status",
        "rows_total",
        "rows_failed",
        "created_at",
    }


def _count_statements(client: TestClient, url: str) -> int:
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(url)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200
    return len(statements)


def test_statement_count_does_not_grow_with_data(workspace):
    owner, workspace_id, (org_id, ws_uuid, user_id) = workspace
    url = f"/api/v1/workspaces/{workspace_id}/summary"
    with get_session_factory()() as db:
        batch = _batch(db, org_id, ws_uuid)
        run = _run(db, org_id, ws_uuid, user_id, matches=1, exceptions=1)
        _exceptions(db, org_id, ws_uuid, batch, run, "unmatched", "open", 1)
        _count_statements(owner, url)
        before = _count_statements(owner, url)

        for _ in range(6):
            _batch(db, org_id, ws_uuid, rows_total=1)
        run = _run(db, org_id, ws_uuid, user_id, matches=5, exceptions=4)
        _exceptions(db, org_id, ws_uuid, batch, run, "ambiguous", "proposed", 2)
        _exceptions(db, org_id, ws_uuid, batch, run, "duplicate", "resolved", 2)
        after = _count_statements(owner, url)

    assert before == after
    assert before <= 10
