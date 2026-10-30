from __future__ import annotations

import io
import logging
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.config import get_settings
from app.models import ImportBatch, ImportRow, Transaction, User, Workspace

from .checksum import check_size, sha256_hex
from .reader import ImportFileError, RowResult, read_rows

metrics = logging.getLogger("reconcile.metrics")
STALE_AFTER = timedelta(minutes=5)
CLAIMABLE = or_(
    ImportBatch.status.in_(("pending", "failed")),
    and_(
        ImportBatch.status == "processing",
        ImportBatch.updated_at < func.now() - STALE_AFTER,
    ),
)


class IdempotencyConflict(Exception):
    """The Idempotency-Key was already used for a different file."""


class BatchBusy(Exception):
    """Another worker is processing this batch."""


def _find_batch(
    db: Session, workspace_id: UUID, checksum: str, idempotency_key: str | None
) -> ImportBatch | None:
    if idempotency_key is not None:
        keyed = db.scalar(
            select(ImportBatch).where(
                ImportBatch.workspace_id == workspace_id,
                ImportBatch.idempotency_key == idempotency_key,
            )
        )
        if keyed is not None:
            if keyed.file_checksum != checksum:
                raise IdempotencyConflict("Idempotency-Key was used for a different file")
            return keyed
    return db.scalar(
        select(ImportBatch).where(
            ImportBatch.workspace_id == workspace_id,
            ImportBatch.file_checksum == checksum,
        )
    )


def create_or_get_batch(
    db: Session,
    *,
    user: User | None,
    workspace: Workspace,
    source_name: str,
    filename: str | None,
    stream: BinaryIO,
    idempotency_key: str | None = None,
    enforce_size_cap: bool = True,
) -> tuple[ImportBatch, bool]:
    size = stream.seek(0, io.SEEK_END)
    if enforce_size_cap:
        check_size(size, get_settings().max_upload_mb)
    checksum = sha256_hex(stream)

    batch = _find_batch(db, workspace.id, checksum, idempotency_key)
    if batch is not None:
        return batch, False

    batch = ImportBatch(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        source_name=source_name,
        filename=filename,
        file_size_bytes=size,
        file_checksum=checksum,
        idempotency_key=idempotency_key,
        status="pending",
        created_by=user.id if user is not None else None,
    )
    db.add(batch)
    try:
        db.flush()
        audit.record(
            db,
            organization_id=workspace.organization_id,
            actor=user,
            action="import.created",
            target_type="import_batch",
            target_id=batch.id,
            metadata={
                "source_name": source_name,
                "filename": filename,
                "file_size_bytes": size,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_batch(db, workspace.id, checksum, idempotency_key)
        if existing is None:
            raise
        return existing, False
    return batch, True


def _claim(session_factory: sessionmaker[Session], batch_id: UUID) -> Row | None:
    claim = (
        update(ImportBatch)
        .where(ImportBatch.id == batch_id, CLAIMABLE)
        .values(
            status="processing",
            started_at=func.coalesce(ImportBatch.started_at, func.now()),
            updated_at=func.now(),
        )
        .returning(
            ImportBatch.id,
            ImportBatch.organization_id,
            ImportBatch.workspace_id,
            ImportBatch.source_name,
            ImportBatch.rows_processed,
        )
    )
    with session_factory() as session, session.begin():
        return session.execute(claim).first()


def _finish_batch(
    session_factory: sessionmaker[Session], batch: Row, actor: User | None, **values
) -> None:
    status = values["status"]
    with session_factory() as session, session.begin():
        final = session.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch.id)
            .values(updated_at=func.now(), **values)
            .returning(ImportBatch.rows_total, ImportBatch.rows_processed, ImportBatch.rows_failed)
        ).one()
        if status == "completed":
            metadata = {
                "rows_total": final.rows_total,
                "rows_processed": final.rows_processed,
                "rows_failed": final.rows_failed,
            }
        else:
            metadata = {"error_summary": values["error_summary"]}
        audit.record(
            session,
            organization_id=batch.organization_id,
            actor=actor,
            action=f"import.{status}",
            target_type="import_batch",
            target_id=batch.id,
            metadata=metadata,
        )


def _insert_chunk(session: Session, batch: Row, rows: list[RowResult], seen: int) -> None:
    transactions = [
        {
            "organization_id": batch.organization_id,
            "workspace_id": batch.workspace_id,
            "import_batch_id": batch.id,
            "source_name": row.values["source_name"],
            "external_id": row.values["external_id"],
            "amount": Decimal(row.values["amount"]),
            "currency": row.values["currency"],
            "transaction_type": row.values["transaction_type"],
            "reference": row.values["reference"] or None,
            "occurred_at": datetime.fromisoformat(row.values["occurred_at"]),
        }
        for row in rows
        if row.status == "VALID"
    ]
    inserted = set()
    if transactions:
        inserted = set(
            session.scalars(
                insert(Transaction)
                .on_conflict_do_nothing(
                    index_elements=["workspace_id", "source_name", "external_id"]
                )
                .returning(Transaction.external_id),
                transactions,
            )
        )

    import_rows = []
    failed = 0
    for row in rows:
        status, error_code, error_detail = row.status, row.error_code, row.error_detail
        if status == "VALID" and row.values["external_id"] not in inserted:
            status = error_code = "DUPLICATE_IN_FILE"
            error_detail = "External ID was already imported in an earlier batch"
        if status != "VALID":
            failed += 1
        import_rows.append(
            {
                "organization_id": batch.organization_id,
                "import_batch_id": batch.id,
                "row_number": row.row_number,
                "payload": row.values if row.values is not None else {},
                "validation_status": status,
                "error_code": error_code,
                "error_detail": error_detail,
            }
        )
    session.execute(insert(ImportRow), import_rows)
    session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch.id)
        .values(
            rows_processed=rows[-1].row_number,
            rows_failed=ImportBatch.rows_failed + failed,
            rows_total=seen,
            updated_at=func.now(),
        )
    )


def _write_chunk(
    session_factory: sessionmaker[Session], batch: Row, rows: list[RowResult], seen: int
) -> None:
    with session_factory() as session, session.begin():
        _insert_chunk(session, batch, rows, seen)


def _summary(exc: Exception) -> str:
    if isinstance(exc, ImportFileError):
        return str(exc)
    return "Unexpected error while importing the file"


def _log_import_finished(
    session_factory: sessionmaker[Session], batch_id: UUID, started: float
) -> None:
    with session_factory() as session:
        batch = session.get(ImportBatch, batch_id)
    duration = time.perf_counter() - started
    metrics.info(
        "import finished",
        extra={
            "event": "import_finished",
            "batch_id": str(batch.id),
            "status": batch.status,
            "duration_ms": round(duration * 1000, 2),
            "rows_total": batch.rows_total,
            "rows_failed": batch.rows_failed,
            "rows_per_second": round(batch.rows_total / duration, 2) if duration > 0 else None,
        },
    )


def process_batch(
    session_factory: sessionmaker[Session],
    batch_id: UUID,
    stream: BinaryIO,
    *,
    chunk_size: int = 1000,
    max_rows: int | None,
    actor: User | None = None,
) -> ImportBatch:
    batch = _claim(session_factory, batch_id)
    if batch is None:
        with session_factory() as session:
            current = session.get(ImportBatch, batch_id)
        if current.status == "completed":
            return current
        raise BatchBusy("Batch is being processed by another worker")

    started = time.perf_counter()
    read_cap = sys.maxsize if max_rows is None else max_rows
    pending: list[RowResult] = []
    seen = 0
    try:
        for result in read_rows(stream, batch.source_name, max_rows=read_cap):
            seen += 1
            if result.row_number <= batch.rows_processed:
                continue
            pending.append(result)
            if len(pending) == chunk_size:
                _write_chunk(session_factory, batch, pending, seen)
                pending = []
        if pending:
            _write_chunk(session_factory, batch, pending, seen)
        _finish_batch(
            session_factory, batch, actor, status="completed", rows_total=seen, error_summary=None
        )
    except Exception as exc:
        _finish_batch(session_factory, batch, actor, status="failed", error_summary=_summary(exc))
        raise
    finally:
        _log_import_finished(session_factory, batch_id, started)

    with session_factory() as session:
        return session.get(ImportBatch, batch_id)
