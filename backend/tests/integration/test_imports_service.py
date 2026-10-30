import csv
import io
import threading
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from app.db import get_session_factory
from app.imports import (
    BatchBusy,
    IdempotencyConflict,
    ImportFileError,
    create_or_get_batch,
    process_batch,
    service,
)
from app.models import ImportBatch, ImportRow, Organization, Transaction, User, Workspace

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reconciliation"
SOURCES = ["orders", "payments", "refunds", "settlements", "fees"]


def _load(filename):
    return (FIXTURES / filename).read_bytes()


def _expected_rows(filename):
    with (FIXTURES / "expected_import_rows.csv").open(newline="") as f:
        return [row for row in csv.DictReader(f) if row["source_file"] == filename]


def _valid_count(expected):
    return sum(row["validation_status"] == "VALID" for row in expected)


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


def _batch(db, user, workspace, filename, data, key=None):
    return create_or_get_batch(
        db,
        user=user,
        workspace=workspace,
        source_name=filename.removesuffix(".csv"),
        filename=filename,
        stream=io.BytesIO(data),
        idempotency_key=key,
    )


def _process(batch_id, data, chunk_size=1000, max_rows=None):
    return process_batch(
        get_session_factory(),
        batch_id,
        io.BytesIO(data),
        chunk_size=chunk_size,
        max_rows=max_rows,
    )


def _reload(db, batch_id):
    db.expire_all()
    return db.get(ImportBatch, batch_id)


def _stored_rows(db, batch_id):
    db.expire_all()
    rows = db.scalars(
        select(ImportRow)
        .where(ImportRow.import_batch_id == batch_id)
        .order_by(ImportRow.row_number)
    ).all()
    return [(row.row_number, row.validation_status, row.error_code) for row in rows]


def _transactions(db, batch_id):
    db.expire_all()
    return db.scalars(
        select(Transaction)
        .where(Transaction.import_batch_id == batch_id)
        .order_by(Transaction.external_id)
    ).all()


def _set_batch_state(db, batch_id, **values):
    db.execute(update(ImportBatch).where(ImportBatch.id == batch_id).values(**values))
    db.commit()


@pytest.mark.parametrize("source", SOURCES)
def test_golden_fixture_rows_and_transactions(db, tenant, source):
    user, workspace = tenant
    filename = f"{source}.csv"
    data = _load(filename)
    batch, created = _batch(db, user, workspace, filename, data)
    assert created

    _process(batch.id, data)

    expected = _expected_rows(filename)
    assert _stored_rows(db, batch.id) == [
        (int(row["row_number"]), row["validation_status"], row["error_code"] or None)
        for row in expected
    ]
    transactions = _transactions(db, batch.id)
    assert len(transactions) == _valid_count(expected)
    assert all(
        t.organization_id == workspace.organization_id and t.workspace_id == workspace.id
        for t in transactions
    )


def test_same_file_returns_the_same_batch(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    batch, _ = _batch(db, user, workspace, "orders.csv", data)
    _process(batch.id, data)

    again, created = _batch(db, user, workspace, "orders.csv", data)

    assert not created
    assert again.id == batch.id
    assert len(_stored_rows(db, batch.id)) == len(_expected_rows("orders.csv"))


def test_idempotency_key_returns_batch_or_conflicts(db, tenant):
    user, workspace = tenant
    orders = _load("orders.csv")
    first, _ = _batch(db, user, workspace, "orders.csv", orders, key="upload-1")

    same, created = _batch(db, user, workspace, "orders.csv", orders, key="upload-1")

    assert not created
    assert same.id == first.id
    with pytest.raises(IdempotencyConflict):
        _batch(db, user, workspace, "fees.csv", _load("fees.csv"), key="upload-1")


def test_concurrent_identical_uploads_share_one_batch(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    user_id, workspace_id = user.id, workspace.id
    factory = get_session_factory()
    barrier = threading.Barrier(2)
    results = []

    def upload():
        with factory() as session:
            barrier.wait()
            batch, created = create_or_get_batch(
                session,
                user=session.get(User, user_id),
                workspace=session.get(Workspace, workspace_id),
                source_name="orders",
                filename="orders.csv",
                stream=io.BytesIO(data),
            )
            results.append((batch.id, created))

    threads = [threading.Thread(target=upload) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert len({batch_id for batch_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_resume_after_a_failed_chunk_matches_a_clean_run(db, tenant, monkeypatch):
    user, workspace = tenant
    data = _load("payments.csv")
    batch, _ = _batch(db, user, workspace, "payments.csv", data)

    real_insert_chunk = service._insert_chunk
    calls = []

    def fail_second_chunk(session, batch_row, rows, seen):
        calls.append(rows)
        if len(calls) == 2:
            raise RuntimeError("simulated crash")
        return real_insert_chunk(session, batch_row, rows, seen)

    monkeypatch.setattr(service, "_insert_chunk", fail_second_chunk)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _process(batch.id, data, chunk_size=3)

    expected = _expected_rows("payments.csv")
    failed = _reload(db, batch.id)
    assert failed.status == "failed"
    assert failed.rows_processed == int(expected[2]["row_number"])
    assert len(_stored_rows(db, batch.id)) == 3

    monkeypatch.undo()
    resumed = _process(batch.id, data, chunk_size=3)

    other_workspace = Workspace(
        organization_id=workspace.organization_id, name=f"Clean {uuid.uuid4()}", created_by=user.id
    )
    db.add(other_workspace)
    db.commit()
    clean, _ = _batch(db, user, other_workspace, "payments.csv", data)
    _process(clean.id, data)

    failed_count = len(expected) - _valid_count(expected)
    assert resumed.status == "completed"
    assert resumed.rows_total == len(expected)
    assert resumed.rows_processed == int(expected[-1]["row_number"])
    assert resumed.rows_failed == failed_count
    assert _stored_rows(db, batch.id) == _stored_rows(db, clean.id)
    assert [
        (t.external_id, t.amount, t.currency, t.occurred_at) for t in _transactions(db, batch.id)
    ] == [(t.external_id, t.amount, t.currency, t.occurred_at) for t in _transactions(db, clean.id)]


def test_row_already_imported_in_an_earlier_batch_is_flagged(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    first, _ = _batch(db, user, workspace, "orders.csv", data)
    _process(first.id, data)

    again = data + b"\n"
    second, created = _batch(db, user, workspace, "orders.csv", again)
    assert created
    _process(second.id, again)

    expected = _expected_rows("orders.csv")
    assert _stored_rows(db, second.id) == [
        (
            int(row["row_number"]),
            "DUPLICATE_IN_FILE"
            if row["validation_status"] == "VALID"
            else row["validation_status"],
            "DUPLICATE_IN_FILE"
            if row["validation_status"] == "VALID"
            else row["error_code"] or None,
        )
        for row in expected
    ]
    assert _transactions(db, second.id) == []
    assert len(_transactions(db, first.id)) == _valid_count(expected)
    assert _reload(db, second.id).rows_failed == len(expected)


def test_concurrent_workers_process_the_batch_once(db, tenant):
    user, workspace = tenant
    data = _load("payments.csv")
    batch, _ = _batch(db, user, workspace, "payments.csv", data)
    batch_id = batch.id
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        barrier.wait()
        try:
            outcomes.append(_process(batch_id, data, chunk_size=2).status)
        except BatchBusy:
            outcomes.append("busy")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    expected = _expected_rows("payments.csv")
    assert sorted(outcomes) in (["busy", "completed"], ["completed", "completed"])
    assert _stored_rows(db, batch.id) == [
        (int(row["row_number"]), row["validation_status"], row["error_code"] or None)
        for row in expected
    ]


def test_fresh_processing_batch_is_busy(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    batch, _ = _batch(db, user, workspace, "orders.csv", data)
    _set_batch_state(db, batch.id, status="processing", updated_at=func.now())

    with pytest.raises(BatchBusy):
        _process(batch.id, data)


def test_stale_processing_batch_is_resumed(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    batch, _ = _batch(db, user, workspace, "orders.csv", data)
    _set_batch_state(
        db,
        batch.id,
        status="processing",
        updated_at=func.now() - timedelta(minutes=10),
    )

    resumed = _process(batch.id, data)

    assert resumed.status == "completed"
    assert len(_stored_rows(db, batch.id)) == len(_expected_rows("orders.csv"))


def test_completed_batch_is_returned_unchanged(db, tenant):
    user, workspace = tenant
    data = _load("fees.csv")
    batch, _ = _batch(db, user, workspace, "fees.csv", data)
    done = _process(batch.id, data)
    updated_at = _reload(db, batch.id).updated_at

    again = _process(batch.id, data)

    assert again.status == "completed"
    assert again.updated_at == updated_at == done.updated_at
    assert len(_stored_rows(db, batch.id)) == len(_expected_rows("fees.csv"))


def test_row_cap_fails_the_batch_and_keeps_only_committed_rows(db, tenant):
    user, workspace = tenant
    data = _load("orders.csv")
    batch, _ = _batch(db, user, workspace, "orders.csv", data)

    with pytest.raises(ImportFileError):
        _process(batch.id, data, chunk_size=2, max_rows=5)

    capped = _reload(db, batch.id)
    stored = _stored_rows(db, batch.id)
    assert capped.status == "failed"
    assert capped.error_summary == "too many rows"
    assert len(stored) == 4
    assert capped.rows_processed == stored[-1][0]

    completed = _process(batch.id, data, chunk_size=2)

    assert completed.status == "completed"
    assert _stored_rows(db, batch.id) == [
        (int(row["row_number"]), row["validation_status"], row["error_code"] or None)
        for row in _expected_rows("orders.csv")
    ]
