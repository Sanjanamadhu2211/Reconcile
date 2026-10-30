import io
import json
import logging
import uuid
from pathlib import Path

import pytest

from app.db import get_session_factory
from app.imports import ImportFileError, create_or_get_batch, process_batch
from app.logging import JsonFormatter
from app.models import Organization, User, Workspace
from app.reconciliation.runner import run_reconciliation

pytestmark = pytest.mark.integration

ORDERS = (Path(__file__).parents[1] / "fixtures" / "reconciliation" / "orders.csv").read_bytes()


@pytest.fixture
def metric_lines():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    metrics = logging.getLogger("reconcile.metrics")
    metrics.addHandler(handler)
    yield stream
    metrics.removeHandler(handler)


@pytest.fixture
def tenant(db):
    org = Organization(name=f"Org {uuid.uuid4()}")
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="unused")
    db.add_all([org, user])
    db.flush()
    workspace = Workspace(organization_id=org.id, name=f"Ledger {uuid.uuid4()}", created_by=user.id)
    db.add(workspace)
    db.commit()
    return user, workspace


def _events(stream, name: str) -> list[dict]:
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [line for line in lines if line.get("event") == name]


def _import(db, user, workspace, max_rows=None):
    batch, _ = create_or_get_batch(
        db,
        user=user,
        workspace=workspace,
        source_name="orders",
        filename="orders.csv",
        stream=io.BytesIO(ORDERS),
        idempotency_key=None,
    )
    return process_batch(
        get_session_factory(), batch.id, io.BytesIO(ORDERS), max_rows=max_rows, actor=user
    )


def test_completed_import_logs_one_event_without_sensitive_values(db, tenant, metric_lines):
    user, workspace = tenant

    batch = _import(db, user, workspace)

    [event] = _events(metric_lines, "import_finished")
    assert event["logger"] == "reconcile.metrics"
    assert event["batch_id"] == str(batch.id)
    assert event["status"] == "completed"
    assert event["rows_total"] == batch.rows_total
    assert event["rows_failed"] == batch.rows_failed
    assert event["duration_ms"] >= 0
    assert event["rows_per_second"] is None or event["rows_per_second"] > 0
    raw = metric_lines.getvalue()
    assert "orders.csv" not in raw
    assert user.email not in raw


def test_failed_import_logs_one_event(db, tenant, metric_lines):
    user, workspace = tenant

    with pytest.raises(ImportFileError):
        _import(db, user, workspace, max_rows=1)

    [event] = _events(metric_lines, "import_finished")
    assert event["status"] == "failed"


def test_each_reconciliation_run_logs_one_event(db, tenant, metric_lines):
    user, workspace = tenant
    _import(db, user, workspace)
    metric_lines.truncate(0)
    metric_lines.seek(0)

    run = run_reconciliation(get_session_factory(), workspace_id=workspace.id, user_id=user.id)

    [event] = _events(metric_lines, "reconciliation_finished")
    matches, exceptions = run.matches_count, run.exceptions_count
    assert event["run_id"] == str(run.id)
    assert event["status"] == "completed"
    assert event["matches"] == matches
    assert event["exceptions"] == exceptions
    assert event["duration_ms"] >= 0
    total = matches + exceptions
    assert event["match_rate"] == f"{matches / total:.4f}"
    assert event["exception_rate"] == f"{exceptions / total:.4f}"
    assert user.email not in metric_lines.getvalue()
