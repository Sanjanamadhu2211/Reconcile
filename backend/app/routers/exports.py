import csv
import io
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from app.auth.dependencies import get_current_user
from app.auth.permissions import load_member_workspace
from app.auth.rate_limit import rate_limit
from app.db import get_db, get_session_factory
from app.models import Exception as ExceptionModel
from app.models import (
    ImportBatch,
    ImportRow,
    Match,
    ReconciliationRun,
    Transaction,
    User,
    Workspace,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["exports"],
    dependencies=[Depends(get_current_user), Depends(rate_limit("export", 30, 60))],
)

BATCH_SIZE = 1000
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MATCH_HEADER = [
    "run_id",
    "rule",
    "left_source",
    "left_external_id",
    "left_amount",
    "left_currency",
    "left_occurred_at",
    "right_source",
    "right_external_id",
    "right_amount",
    "right_currency",
    "right_occurred_at",
]
EXCEPTION_HEADER = [
    "run_id",
    "exception_id",
    "category",
    "status",
    "source_name",
    "external_id",
    "amount",
    "currency",
    "occurred_at",
    "row_number",
    "version",
]
IMPORT_ERROR_HEADER = [
    "batch_id",
    "filename",
    "source_name",
    "row_number",
    "validation_status",
    "error_code",
    "error_detail",
]


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "'" + value if value.startswith(FORMULA_PREFIXES) else value
    if isinstance(value, Decimal):
        return f"{value:.4f}"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"


def _csv_body(header: list[str], statement: Select | None) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return text

    writer.writerow(header)
    yield flush()
    if statement is None:
        return
    with get_session_factory()() as db:
        for row in db.execute(statement, execution_options={"yield_per": BATCH_SIZE}):
            writer.writerow(_cell(value) for value in row)
            yield flush()


def _csv_response(
    workspace: Workspace, kind: str, header: list[str], statement: Select | None
) -> StreamingResponse:
    filename = f"{_slug(workspace.name)}-{kind}-{datetime.now(UTC):%Y%m%d}.csv"
    return StreamingResponse(
        _csv_body(header, statement),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export_run_id(
    db: Session, workspace_id: uuid.UUID, run_id: uuid.UUID | None
) -> uuid.UUID | None:
    runs = select(ReconciliationRun.id).where(ReconciliationRun.workspace_id == workspace_id)
    if run_id is not None:
        found = db.scalar(runs.where(ReconciliationRun.id == run_id))
        if found is None:
            raise HTTPException(status_code=404, detail="Reconciliation run not found")
        return found
    return db.scalar(
        runs.where(ReconciliationRun.status == "completed")
        .order_by(ReconciliationRun.completed_at.desc().nulls_last(), ReconciliationRun.id.desc())
        .limit(1)
    )


def _matches_statement(run_id: uuid.UUID) -> Select:
    left = aliased(Transaction)
    right = aliased(Transaction)
    return (
        select(
            Match.reconciliation_run_id,
            Match.rule,
            left.source_name,
            left.external_id,
            left.amount,
            left.currency,
            left.occurred_at,
            right.source_name,
            right.external_id,
            right.amount,
            right.currency,
            right.occurred_at,
        )
        .join(left, left.id == Match.left_transaction_id)
        .join(right, right.id == Match.right_transaction_id)
        .where(Match.reconciliation_run_id == run_id)
        .order_by(Match.id)
    )


def _exceptions_statement(run_id: uuid.UUID) -> Select:
    return (
        select(
            ExceptionModel.reconciliation_run_id,
            ExceptionModel.id,
            ExceptionModel.category,
            ExceptionModel.status,
            Transaction.source_name,
            Transaction.external_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.occurred_at,
            ImportRow.row_number,
            ExceptionModel.version,
        )
        .outerjoin(Transaction, Transaction.id == ExceptionModel.transaction_id)
        .outerjoin(ImportRow, ImportRow.id == ExceptionModel.import_row_id)
        .where(ExceptionModel.reconciliation_run_id == run_id)
        .order_by(ExceptionModel.id)
    )


@router.get("/workspaces/{workspace_id}/exports/matches.csv")
def export_matches(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    run_id: uuid.UUID | None = None,
) -> StreamingResponse:
    workspace, _ = load_member_workspace(db, user, workspace_id)
    run = _export_run_id(db, workspace.id, run_id)
    statement = _matches_statement(run) if run else None
    return _csv_response(workspace, "matches", MATCH_HEADER, statement)


@router.get("/workspaces/{workspace_id}/exports/exceptions.csv")
def export_exceptions(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    run_id: uuid.UUID | None = None,
) -> StreamingResponse:
    workspace, _ = load_member_workspace(db, user, workspace_id)
    run = _export_run_id(db, workspace.id, run_id)
    statement = _exceptions_statement(run) if run else None
    return _csv_response(workspace, "exceptions", EXCEPTION_HEADER, statement)


@router.get("/workspaces/{workspace_id}/exports/import-errors.csv")
def export_import_errors(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    import_id: uuid.UUID | None = None,
) -> StreamingResponse:
    workspace, _ = load_member_workspace(db, user, workspace_id)
    statement = (
        select(
            ImportRow.import_batch_id,
            ImportBatch.filename,
            ImportBatch.source_name,
            ImportRow.row_number,
            ImportRow.validation_status,
            ImportRow.error_code,
            ImportRow.error_detail,
        )
        .join(ImportBatch, ImportBatch.id == ImportRow.import_batch_id)
        .where(ImportBatch.workspace_id == workspace.id, ImportRow.validation_status != "VALID")
        .order_by(ImportRow.import_batch_id, ImportRow.row_number)
    )
    if import_id is not None:
        statement = statement.where(ImportRow.import_batch_id == import_id)
    return _csv_response(workspace, "import-errors", IMPORT_ERROR_HEADER, statement)
