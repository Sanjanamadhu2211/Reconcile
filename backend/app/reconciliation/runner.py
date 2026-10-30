from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import Exception as ExceptionRow
from app.models import ImportBatch, ImportRow, ReconciliationRun, Transaction, Workspace
from app.models import Match as MatchRow
from app.reconciliation.engine import MatchingResult, Record, run_matching

logger = logging.getLogger(__name__)

RULE_VERSION = "1"
RUN_STALE_AFTER = timedelta(minutes=10)


class RunInProgress(Exception):
    """Another reconciliation run for the workspace is still running."""


def _start_run(
    session_factory: sessionmaker[Session], workspace_id: uuid.UUID, user_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID, int]:
    with session_factory() as session, session.begin():
        session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(workspace_id), 0)))
        )
        busy = session.scalar(
            select(ReconciliationRun.id).where(
                ReconciliationRun.workspace_id == workspace_id,
                ReconciliationRun.status == "running",
                ReconciliationRun.started_at > func.now() - RUN_STALE_AFTER,
            )
        )
        if busy is not None:
            raise RunInProgress("A reconciliation run is already in progress")

        workspace = session.get(Workspace, workspace_id)
        run = ReconciliationRun(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            rule_version=RULE_VERSION,
            status="running",
            tolerance_hours=workspace.timestamp_tolerance_hours,
            created_by=user_id,
            started_at=func.now(),
        )
        session.add(run)
        session.flush()
        return run.id, run.organization_id, run.tolerance_hours


def _duplicate_record(row_id: uuid.UUID, payload: dict) -> Record | None:
    # In-file duplicates are stored without values, so they can be skipped without a Record
    try:
        return Record(
            key=("row", row_id),
            source_name=payload["source_name"],
            external_id=payload["external_id"],
            amount=Decimal(payload["amount"]),
            currency=payload["currency"],
            occurred_at=datetime.fromisoformat(payload["occurred_at"]),
            is_duplicate=True,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def _load_records(
    session: Session, organization_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[Record]:
    # shortcut: in-memory matching, batch or SQL matching past a few hundred thousand rows
    transactions = session.execute(
        select(
            Transaction.id,
            Transaction.source_name,
            Transaction.external_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.occurred_at,
        ).where(
            Transaction.organization_id == organization_id,
            Transaction.workspace_id == workspace_id,
        )
    )
    records = [
        Record(
            key=row.id,
            source_name=row.source_name,
            external_id=row.external_id,
            amount=row.amount,
            currency=row.currency,
            occurred_at=row.occurred_at,
        )
        for row in transactions
    ]

    duplicates = session.execute(
        select(ImportRow.id, ImportRow.payload)
        .join(ImportBatch, ImportRow.import_batch_id == ImportBatch.id)
        .where(
            ImportRow.organization_id == organization_id,
            ImportBatch.workspace_id == workspace_id,
            ImportRow.validation_status == "DUPLICATE_IN_FILE",
        )
    )
    records.extend(
        record
        for record in (_duplicate_record(row.id, row.payload) for row in duplicates)
        if record is not None
    )
    return records


def _insert_matches(
    session: Session, run_id: uuid.UUID, organization_id: uuid.UUID, matches
) -> None:
    if not matches:
        return
    session.execute(
        insert(MatchRow),
        [
            {
                "organization_id": organization_id,
                "reconciliation_run_id": run_id,
                "rule": match.rule,
                "left_transaction_id": match.left_key,
                "right_transaction_id": match.right_key,
            }
            for match in matches
        ],
    )


def _insert_exceptions(
    session: Session,
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    exceptions,
) -> None:
    if not exceptions:
        return
    session.execute(
        insert(ExceptionRow),
        [
            {
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "reconciliation_run_id": run_id,
                "category": item.category,
                "transaction_id": None if isinstance(item.key, tuple) else item.key,
                "import_row_id": item.key[1] if isinstance(item.key, tuple) else None,
                "details": (
                    {"candidates": [str(key) for key in item.candidate_keys]}
                    if item.category == "ambiguous"
                    else None
                ),
            }
            for item in exceptions
        ],
    )


def _persist(
    session_factory: sessionmaker[Session],
    run_id: uuid.UUID,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    result: MatchingResult,
) -> None:
    with session_factory() as session, session.begin():
        _insert_matches(session, run_id, organization_id, result.matches)
        _insert_exceptions(session, run_id, organization_id, workspace_id, result.exceptions)
        session.execute(
            update(ReconciliationRun)
            .where(ReconciliationRun.id == run_id)
            .values(
                status="completed",
                matches_count=len(result.matches),
                exceptions_count=len(result.exceptions),
                completed_at=func.now(),
            )
        )


def _fail_run(session_factory: sessionmaker[Session], run_id: uuid.UUID) -> None:
    with session_factory() as session, session.begin():
        session.execute(
            update(ReconciliationRun)
            .where(ReconciliationRun.id == run_id)
            .values(
                status="failed",
                error_summary="Unexpected error while reconciling the workspace",
                completed_at=func.now(),
            )
        )


def run_reconciliation(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> ReconciliationRun:
    run_id, organization_id, tolerance_hours = _start_run(session_factory, workspace_id, user_id)
    try:
        with session_factory() as session:
            records = _load_records(session, organization_id, workspace_id)
        result = run_matching(records, timedelta(hours=tolerance_hours))
        _persist(session_factory, run_id, organization_id, workspace_id, result)
    except Exception:
        logger.exception("Reconciliation run %s failed", run_id)
        _fail_run(session_factory, run_id)
        raise

    with session_factory() as session:
        return session.get(ReconciliationRun, run_id)
