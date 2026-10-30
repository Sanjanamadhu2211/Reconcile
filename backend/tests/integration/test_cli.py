#!/usr/bin/env python3
"""Integration tests for the CLI module."""

import csv
import io
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.cli import main
from app.config import get_settings
from app.db import get_session_factory
from app.imports import create_or_get_batch
from app.models import ImportBatch, ImportRow, Organization, Transaction, User, Workspace

pytestmark = pytest.mark.integration
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "reconciliation"


def load_fixture(filename: str) -> bytes:
    return (FIXTURES_DIR / filename).read_bytes()


def expected_rows_for_file(filename: str) -> list:
    with (FIXTURES_DIR / "expected_import_rows.csv").open(newline="") as f:
        return [row for row in csv.DictReader(f) if row["source_file"] == filename]


def generate_large_csv(rows: int = 40, source: str = "orders") -> bytes:
    """Generate a CSV with more rows than the web cap, using correct headers for the source."""
    output = io.StringIO()
    writer = csv.writer(output)

    if source == "orders":
        writer.writerow(["order_id", "amount", "currency", "order_date", "customer_id"])
        for i in range(1, rows + 1):
            writer.writerow(
                [f"TEST-{i:04d}", "100.00", "USD", f"2024-01-{i:02d}T12:00:00Z", f"CUST-{i}"]
            )
    elif source == "payments":
        writer.writerow(["payment_id", "amount", "currency", "paid_at", "order_id"])
        for i in range(1, rows + 1):
            writer.writerow(
                [f"TEST-{i:04d}", "100.00", "USD", f"2024-01-{i:02d}T12:00:00Z", f"ORD-{i}"]
            )
    elif source == "refunds":
        writer.writerow(["refund_id", "amount", "currency", "refunded_at", "original_payment_id"])
        for i in range(1, rows + 1):
            writer.writerow(
                [f"TEST-{i:04d}", "100.00", "USD", f"2024-01-{i:02d}T12:00:00Z", f"PAY-{i}"]
            )
    elif source == "settlements":
        writer.writerow(["settlement_id", "amount", "currency", "settled_at", "batch_reference"])
        for i in range(1, rows + 1):
            writer.writerow(
                [f"TEST-{i:04d}", "100.00", "USD", f"2024-01-{i:02d}T12:00:00Z", f"BATCH-{i}"]
            )
    elif source == "fees":
        writer.writerow(["fee_id", "amount", "currency", "charged_at", "related_payment_id"])
        for i in range(1, rows + 1):
            writer.writerow(
                [f"TEST-{i:04d}", "100.00", "USD", f"2024-01-{i:02d}T12:00:00Z", f"PAY-{i}"]
            )
    else:
        raise ValueError(f"Unknown source: {source}")

    return output.getvalue().encode("utf-8")


def generate_oversized_csv(source: str = "orders", target_mb: float = 2.0) -> bytes:
    """Generate a CSV file larger than target_mb MB."""
    output = io.StringIO()
    writer = csv.writer(output)

    if source == "orders":
        writer.writerow(["order_id", "amount", "currency", "order_date", "customer_id"])
    else:
        raise ValueError(f"Unsupported source for oversized: {source}")

    # Generate enough rows to exceed target_mb
    # Each row is roughly 60-70 bytes, so we need ~15000 rows per MB
    rows_needed = int(target_mb * 15000)
    for i in range(1, rows_needed + 1):
        writer.writerow(
            [f"TEST-{i:06d}", "123456.78", "USD", "2024-06-15T12:00:00Z", f"CUST-{i:06d}"]
        )

    data = output.getvalue().encode("utf-8")
    # Ensure it's actually over the target size
    if len(data) < target_mb * 1024 * 1024:
        # Add more rows
        extra_rows = int((target_mb * 1024 * 1024 - len(data)) / 70) + 100
        for i in range(rows_needed + 1, rows_needed + extra_rows + 1):
            writer.writerow(
                [f"TEST-{i:06d}", "123456.78", "USD", "2024-06-15T12:00:00Z", f"CUST-{i:06d}"]
            )
        data = output.getvalue().encode("utf-8")

    return data


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


def test_cli_import_fixture_file(db, tenant):
    user, workspace = tenant
    filename = "orders.csv"
    data = load_fixture(filename)

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(data)
        temp_path = f.name

    try:
        argv = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "orders",
            "--user-email",
            user.email,
        ]
        exit_code = main(argv)
        assert exit_code == 0

        session_factory = get_session_factory()
        with session_factory() as session:
            batches = session.scalars(
                select(ImportBatch).where(ImportBatch.workspace_id == workspace.id)
            ).all()
            assert len(batches) == 1
            batch = batches[0]
            assert batch.status == "completed"

            expected = expected_rows_for_file(filename)
            # All rows (valid and invalid) should be stored as ImportRow records
            total_expected = len(expected)
            rows = session.scalars(
                select(ImportRow)
                .where(ImportRow.import_batch_id == batch.id)
                .order_by(ImportRow.row_number)
            ).all()
            assert len(rows) == total_expected

            # Verify valid rows match expected VALID count
            valid_count = len([r for r in expected if r["validation_status"] == "VALID"])
            transactions = session.scalars(
                select(Transaction).where(Transaction.import_batch_id == batch.id)
            ).all()
            assert len(transactions) == valid_count
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_cli_import_idempotency(db, tenant):
    user, workspace = tenant
    filename = "payments.csv"
    data = load_fixture(filename)

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(data)
        temp_path = f.name

    try:
        argv1 = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "payments",
            "--user-email",
            user.email,
        ]
        exit_code1 = main(argv1)
        assert exit_code1 == 0

        session_factory = get_session_factory()
        with session_factory() as session:
            batch = session.scalar(
                select(ImportBatch).where(
                    ImportBatch.workspace_id == workspace.id, ImportBatch.source_name == "payments"
                )
            )
            batch_id1 = batch.id

        argv2 = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "payments",
            "--user-email",
            user.email,
        ]
        exit_code2 = main(argv2)
        assert exit_code2 == 0

        with session_factory() as session:
            batch2 = session.get(ImportBatch, batch_id1)
            assert batch2 is not None
            assert batch2.status == "completed"
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_cli_import_bypass_size_and_row_caps(db, tenant, monkeypatch):
    user, workspace = tenant

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("MAX_IMPORT_ROWS", "5")
    get_settings.cache_clear()

    data = generate_large_csv(rows=40, source="orders")

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(data)
        temp_path = f.name

    try:
        argv = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "orders",
            "--user-email",
            user.email,
        ]
        exit_code = main(argv)
        assert exit_code == 0

        session_factory = get_session_factory()
        with session_factory() as session:
            batch = session.scalar(
                select(ImportBatch).where(
                    ImportBatch.workspace_id == workspace.id, ImportBatch.source_name == "orders"
                )
            )
            assert batch is not None
            assert batch.status == "completed"
            assert batch.rows_total >= 40
    finally:
        Path(temp_path).unlink(missing_ok=True)
        get_settings.cache_clear()


def test_web_path_rejects_oversized_file(db, tenant, monkeypatch):
    user, workspace = tenant

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("MAX_IMPORT_ROWS", "5")
    get_settings.cache_clear()

    # Generate a file larger than 1 MB
    data = generate_oversized_csv(source="orders", target_mb=2.0)

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(data)
        temp_path = f.name

    try:
        with get_session_factory()() as session:
            from app.imports.reader import ImportFileError

            with pytest.raises(ImportFileError, match="exceeds limit"):
                create_or_get_batch(
                    session,
                    user=user,
                    workspace=workspace,
                    source_name="orders",
                    filename="large.csv",
                    stream=open(temp_path, "rb"),
                    enforce_size_cap=True,
                )
    finally:
        Path(temp_path).unlink(missing_ok=True)
        get_settings.cache_clear()


def test_cli_import_missing_workspace(db):
    missing_workspace_id = uuid.uuid4()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(
            b"order_id,amount,currency,order_date,customer_id\nTEST-1,100.00,USD,2024-01-01T00:00:00Z,CUST-1"
        )
        temp_path = f.name

    try:
        argv = [
            "import",
            temp_path,
            "--workspace",
            str(missing_workspace_id),
            "--source",
            "orders",
            "--user-email",
            "test@example.com",
        ]
        exit_code = main(argv)
        assert exit_code == 2
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_cli_import_unknown_user_email(db, tenant):
    user, workspace = tenant

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(
            b"order_id,amount,currency,order_date,customer_id\nTEST-1,100.00,USD,2024-01-01T00:00:00Z,CUST-1"
        )
        temp_path = f.name

    try:
        argv = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "orders",
            "--user-email",
            "unknown@example.com",
        ]
        exit_code = main(argv)
        assert exit_code == 2
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_cli_import_garbage_file(db, tenant):
    user, workspace = tenant

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        f.write(b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f")
        temp_path = f.name

    try:
        argv = [
            "import",
            temp_path,
            "--workspace",
            str(workspace.id),
            "--source",
            "orders",
            "--user-email",
            user.email,
        ]
        exit_code = main(argv)
        assert exit_code == 1

        session_factory = get_session_factory()
        with session_factory() as session:
            batches = session.scalars(
                select(ImportBatch).where(
                    ImportBatch.workspace_id == workspace.id, ImportBatch.status == "failed"
                )
            ).all()
            assert len(batches) == 1
            batch = batches[0]
            assert batch.error_summary is not None
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_cli_import_file_not_found():
    non_existent_path = Path("/tmp/this_file_does_not_exist_12345.csv")
    argv = [
        "import",
        str(non_existent_path),
        "--workspace",
        "123e4567-e89b-12d3-a456-426614174000",
        "--source",
        "orders",
        "--user-email",
        "test@example.com",
    ]
    exit_code = main(argv)
    assert exit_code == 2
