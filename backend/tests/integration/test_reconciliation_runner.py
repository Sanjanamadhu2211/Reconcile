import csv
import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db import get_session_factory
from app.imports import create_or_get_batch, process_batch
from app.models import Exception as ExceptionRow
from app.models import (
    ImportBatch,
    ImportRow,
    Match,
    Organization,
    ReconciliationRun,
    Transaction,
    User,
    Workspace,
)
from app.reconciliation import runner
from app.reconciliation.runner import RunInProgress, run_reconciliation

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reconciliation"
SOURCES = ["orders", "payments", "refunds", "settlements", "fees"]
MATCH_COLUMNS = [
    "rule",
    "left_source",
    "left_external_id",
    "left_row_number",
    "right_source",
    "right_external_id",
    "right_row_number",
]
EXCEPTION_COLUMNS = ["category", "source", "external_id", "row_number"]


@pytest.fixture
def tenant(db):
    org = Organization(name=f"Org {uuid.uuid4()}")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="unused")
    db.add_all([org, user])
    db.flush()
    workspace = Workspace(organization_id=org.id, name=f"Ledger {uuid.uuid4()}", created_by=user.id)
    db.add(workspace)
    db.commit()
    return SimpleNamespace(
        organization_id=org.id, user_id=user.id, workspace_id=workspace.id, user=user
    )


@pytest.fixture
def golden_workspace(db, tenant):
    workspace = db.get(Workspace, tenant.workspace_id)
    for source in SOURCES:
        data = (FIXTURES / f"{source}.csv").read_bytes()
        batch, _ = create_or_get_batch(
            db,
            user=tenant.user,
            workspace=workspace,
            source_name=source,
            filename=f"{source}.csv",
            stream=io.BytesIO(data),
        )
        process_batch(get_session_factory(), batch.id, io.BytesIO(data), max_rows=None)
    return tenant


def _run(tenant):
    return run_reconciliation(
        get_session_factory(), workspace_id=tenant.workspace_id, user_id=tenant.user_id
    )


def _persisted_outcome(run_id, workspace_id):
    """Map persisted matches and exceptions onto the golden files' columns."""
    with get_session_factory()() as db:
        row_numbers = {
            (row.import_batch_id, row.payload["external_id"]): row.row_number
            for row in db.execute(
                select(ImportRow.import_batch_id, ImportRow.payload, ImportRow.row_number)
                .join(ImportBatch, ImportRow.import_batch_id == ImportBatch.id)
                .where(
                    ImportBatch.workspace_id == workspace_id,
                    ImportRow.validation_status == "VALID",
                )
            )
        }
        transactions = {
            t.id: (t.source_name, t.external_id, row_numbers[(t.import_batch_id, t.external_id)])
            for t in db.scalars(select(Transaction).where(Transaction.workspace_id == workspace_id))
        }
        matches = {
            (m.rule, *transactions[m.left_transaction_id], *transactions[m.right_transaction_id])
            for m in db.scalars(select(Match).where(Match.reconciliation_run_id == run_id))
        }
        exceptions = set()
        for item in db.scalars(
            select(ExceptionRow).where(ExceptionRow.reconciliation_run_id == run_id)
        ):
            if item.transaction_id is not None:
                source, external_id, row_number = transactions[item.transaction_id]
            else:
                import_row = db.get(ImportRow, item.import_row_id)
                source = db.get(ImportBatch, import_row.import_batch_id).source_name
                external_id = import_row.payload.get("external_id")
                row_number = import_row.row_number
            exceptions.add((item.category, source, external_id, row_number))
    return matches, exceptions


def _golden(filename, columns, int_columns):
    with (FIXTURES / filename).open(newline="", encoding="utf-8") as f:
        return {
            tuple(int(row[column]) if column in int_columns else row[column] for column in columns)
            for row in csv.DictReader(f)
        }


def test_persisted_matches_match_golden_fixtures(golden_workspace):
    run = _run(golden_workspace)

    matches, _ = _persisted_outcome(run.id, golden_workspace.workspace_id)
    expected = _golden(
        "expected_matches.csv", MATCH_COLUMNS, {"left_row_number", "right_row_number"}
    )
    assert matches == expected


def test_persisted_exceptions_match_golden_fixtures(golden_workspace):
    run = _run(golden_workspace)

    _, exceptions = _persisted_outcome(run.id, golden_workspace.workspace_id)
    expected = _golden("expected_exceptions.csv", EXCEPTION_COLUMNS, {"row_number"})
    expected_non_duplicate = {row for row in expected if row[0] != "duplicate"}
    assert {row for row in exceptions if row[0] != "duplicate"} == expected_non_duplicate


def test_persisted_duplicate_exceptions_match_golden_fixtures(golden_workspace):
    run = _run(golden_workspace)

    _, exceptions = _persisted_outcome(run.id, golden_workspace.workspace_id)
    expected = _golden("expected_exceptions.csv", EXCEPTION_COLUMNS, {"row_number"})
    assert {row for row in exceptions if row[0] == "duplicate"} == {
        row for row in expected if row[0] == "duplicate"
    }


def test_rerun_gives_identical_results_and_keeps_transactions(golden_workspace):
    first = _run(golden_workspace)
    with get_session_factory()() as db:
        transactions_before = db.execute(
            select(Transaction.id, Transaction.amount, Transaction.occurred_at)
            .where(Transaction.workspace_id == golden_workspace.workspace_id)
            .order_by(Transaction.id)
        ).all()

    second = _run(golden_workspace)

    assert first.id != second.id
    assert _persisted_outcome(first.id, golden_workspace.workspace_id) == _persisted_outcome(
        second.id, golden_workspace.workspace_id
    )
    with get_session_factory()() as db:
        transactions_after = db.execute(
            select(Transaction.id, Transaction.amount, Transaction.occurred_at)
            .where(Transaction.workspace_id == golden_workspace.workspace_id)
            .order_by(Transaction.id)
        ).all()
        runs = db.scalar(
            select(func.count())
            .select_from(ReconciliationRun)
            .where(ReconciliationRun.workspace_id == golden_workspace.workspace_id)
        )
    assert transactions_after == transactions_before
    assert runs == 2


def test_failed_persistence_leaves_no_matches_or_exceptions(golden_workspace, monkeypatch):
    def fail_after_matches(session, run_id, organization_id, workspace_id, exceptions):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(runner, "_insert_exceptions", fail_after_matches)

    with pytest.raises(RuntimeError):
        _run(golden_workspace)

    with get_session_factory()() as db:
        run = db.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.workspace_id == golden_workspace.workspace_id
            )
        )
        assert run.status == "failed"
        assert run.error_summary == "Unexpected error while reconciling the workspace"
        assert "disk on fire" not in run.error_summary
        assert (
            db.scalar(
                select(func.count()).select_from(Match).where(Match.reconciliation_run_id == run.id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExceptionRow)
                .where(ExceptionRow.reconciliation_run_id == run.id)
            )
            == 0
        )


def test_second_start_is_refused_while_a_run_is_in_progress(golden_workspace, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    real_run_matching = runner.run_matching

    def slow_run_matching(records, tolerance):
        started.set()
        release.wait(10)
        return real_run_matching(records, tolerance)

    monkeypatch.setattr(runner, "run_matching", slow_run_matching)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_run, golden_workspace)
        assert started.wait(10)
        second = pool.submit(_run, golden_workspace)
        with pytest.raises(RunInProgress):
            second.result(timeout=10)
        release.set()
        assert first.result(timeout=10).status == "completed"

    with get_session_factory()() as db:
        statuses = db.scalars(
            select(ReconciliationRun.status).where(
                ReconciliationRun.workspace_id == golden_workspace.workspace_id
            )
        ).all()
    assert sorted(statuses) == ["completed"]
