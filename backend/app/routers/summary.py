import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.permissions import load_member_workspace
from app.db import get_db
from app.models import Exception as ExceptionModel
from app.models import ImportBatch, ReconciliationRun, User
from app.schemas.summary import (
    BatchCounts,
    ExceptionCategoryCounts,
    ExceptionsSummary,
    ExceptionStatusCounts,
    ImportsSummary,
    LatestRunSummary,
    WorkspaceSummary,
)

router = APIRouter(
    prefix="/api/v1/workspaces",
    tags=["summary"],
    dependencies=[Depends(get_current_user)],
)


def _match_rate(matches: int, categories: ExceptionCategoryCounts) -> str | None:
    unresolved = categories.unmatched + categories.ambiguous + categories.amount_mismatch
    denominator = matches + unresolved
    if denominator == 0:
        return None
    rate = Decimal(matches) / Decimal(denominator)
    return str(rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


@router.get("/{workspace_id}/summary", response_model=WorkspaceSummary)
def get_workspace_summary(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    load_member_workspace(db, user, workspace_id)

    batch_counts = db.execute(
        select(ImportBatch.status, func.count())
        .where(ImportBatch.workspace_id == workspace_id)
        .group_by(ImportBatch.status)
    ).all()
    rows_imported, rows_invalid = db.execute(
        select(
            func.coalesce(func.sum(ImportBatch.rows_total), 0),
            func.coalesce(func.sum(ImportBatch.rows_failed), 0),
        ).where(ImportBatch.workspace_id == workspace_id, ImportBatch.status == "completed")
    ).one()
    recent_batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.workspace_id == workspace_id)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(5)
    ).all()
    imports = ImportsSummary(
        batches_by_status=BatchCounts(**dict(batch_counts)),
        rows_imported=rows_imported,
        rows_invalid=rows_invalid,
        recent_batches=recent_batches,
    )

    run = db.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.workspace_id == workspace_id,
            ReconciliationRun.status == "completed",
        )
        .order_by(ReconciliationRun.completed_at.desc(), ReconciliationRun.id.desc())
        .limit(1)
    )
    latest_run = None
    status_counts = ExceptionStatusCounts()
    category_counts = ExceptionCategoryCounts()
    if run is not None:
        run_exceptions = ExceptionModel.reconciliation_run_id == run.id
        status_counts = ExceptionStatusCounts(
            **dict(
                db.execute(
                    select(ExceptionModel.status, func.count())
                    .where(run_exceptions)
                    .group_by(ExceptionModel.status)
                ).all()
            )
        )
        category_counts = ExceptionCategoryCounts(
            **dict(
                db.execute(
                    select(ExceptionModel.category, func.count())
                    .where(run_exceptions)
                    .group_by(ExceptionModel.category)
                ).all()
            )
        )
        latest_run = LatestRunSummary(
            id=run.id,
            completed_at=run.completed_at,
            matches_count=run.matches_count,
            exceptions_count=run.exceptions_count,
            match_rate=_match_rate(run.matches_count, category_counts),
        )

    return WorkspaceSummary(
        imports=imports,
        latest_run=latest_run,
        exceptions=ExceptionsSummary(by_status=status_counts, by_category=category_counts),
    )
