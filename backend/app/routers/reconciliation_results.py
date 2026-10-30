import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.models import (
    Exception as ExceptionModel,
)
from app.models import (
    ImportRow,
    Match,
    OrganizationMembership,
    ReconciliationRun,
    Transaction,
    Workspace,
)
from app.pagination import Limit, Offset
from app.schemas.reconciliation_results import (
    ExceptionImportRowSummary,
    ExceptionItem,
    ExceptionTransactionSummary,
    MatchItem,
    ReconciliationRunSummary,
    TransactionSummary,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["reconciliation-results"],
    dependencies=[Depends(get_current_user)],
)


def _verify_workspace_access(db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID) -> uuid.UUID:
    """Verify user has access to workspace and return organization_id."""
    row = db.execute(
        select(Workspace.organization_id, OrganizationMembership)
        .join(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Workspace.organization_id,
                OrganizationMembership.user_id == user_id,
            ),
        )
        .where(Workspace.id == workspace_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row[0]


def _verify_run_access(db: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> ReconciliationRun:
    """Verify user has access to reconciliation run and return it."""
    run = db.execute(
        select(ReconciliationRun)
        .join(
            Workspace,
            Workspace.id == ReconciliationRun.workspace_id,
        )
        .join(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Workspace.organization_id,
                OrganizationMembership.user_id == user_id,
            ),
        )
        .where(ReconciliationRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return run


def _format_amount(amount: Decimal) -> str:
    """Format Decimal amount as string with exactly 4 decimal places."""
    return f"{amount:.4f}"


@router.get(
    "/workspaces/{workspace_id}/reconciliation-runs",
    response_model=list[ReconciliationRunSummary],
)
def list_reconciliation_runs(
    workspace_id: uuid.UUID,
    user: Annotated[uuid.UUID, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
):
    """List reconciliation runs for a workspace, newest first."""
    _verify_workspace_access(db, user.id, workspace_id)

    runs = db.scalars(
        select(ReconciliationRun)
        .where(ReconciliationRun.workspace_id == workspace_id)
        .order_by(ReconciliationRun.created_at.desc(), ReconciliationRun.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return [
        ReconciliationRunSummary(
            id=r.id,
            status=r.status,
            rule_version=r.rule_version,
            tolerance_hours=r.tolerance_hours,
            matches_count=r.matches_count,
            exceptions_count=r.exceptions_count,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]


@router.get(
    "/reconciliation-runs/{run_id}/matches",
    response_model=list[MatchItem],
)
def list_matches(
    run_id: uuid.UUID,
    user: Annotated[uuid.UUID, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
    rule: str | None = Query(default=None, pattern="^(exact_id|amount_currency_time)$"),
):
    """List matches for a reconciliation run with optional rule filter."""
    _verify_run_access(db, user.id, run_id)

    query = (
        select(Match)
        .options(
            joinedload(Match.left_transaction),
            joinedload(Match.right_transaction),
        )
        .where(Match.reconciliation_run_id == run_id)
    )

    if rule is not None:
        query = query.where(Match.rule == rule)

    matches = db.scalars(
        query.order_by(Match.rule, Match.left_transaction_id, Match.right_transaction_id, Match.id)
        .limit(limit)
        .offset(offset)
    ).all()

    result = []
    for m in matches:
        left = m.left_transaction
        right = m.right_transaction
        result.append(
            MatchItem(
                id=m.id,
                rule=m.rule,
                left_transaction=TransactionSummary(
                    source_name=left.source_name,
                    external_id=left.external_id,
                    amount=_format_amount(left.amount),
                    currency=left.currency,
                    occurred_at=left.occurred_at,
                ),
                right_transaction=TransactionSummary(
                    source_name=right.source_name,
                    external_id=right.external_id,
                    amount=_format_amount(right.amount),
                    currency=right.currency,
                    occurred_at=right.occurred_at,
                ),
            )
        )
    return result


@router.get(
    "/reconciliation-runs/{run_id}/exceptions",
    response_model=list[ExceptionItem],
)
def list_exceptions(
    run_id: uuid.UUID,
    user: Annotated[uuid.UUID, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
    category: str | None = Query(
        default=None, pattern="^(unmatched|ambiguous|amount_mismatch|duplicate)$"
    ),
    status: str | None = Query(default=None, pattern="^(open|proposed|resolved)$"),
    source_name: str | None = Query(
        default=None, pattern="^(orders|payments|refunds|settlements|fees)$"
    ),
    q: str | None = Query(default=None, max_length=200),
):
    """List exceptions for a reconciliation run with filters."""
    _verify_run_access(db, user.id, run_id)

    # Build the base query with joins
    query = (
        select(ExceptionModel)
        .outerjoin(Transaction, ExceptionModel.transaction_id == Transaction.id)
        .outerjoin(ImportRow, ExceptionModel.import_row_id == ImportRow.id)
        .where(ExceptionModel.reconciliation_run_id == run_id)
    )

    if category is not None:
        query = query.where(ExceptionModel.category == category)
    if status is not None:
        query = query.where(ExceptionModel.status == status)
    if source_name is not None:
        query = query.where(Transaction.source_name == source_name)
    if q is not None:
        # Escape % and _ for literal search, then do case-insensitive contains
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                Transaction.external_id.ilike(f"%{escaped}%", escape="\\"),
                ImportRow.payload.op("->>")("external_id").ilike(f"%{escaped}%", escape="\\"),
            )
        )

    exceptions = db.scalars(
        query.order_by(
            ExceptionModel.category,
            ExceptionModel.created_at,
            ExceptionModel.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()

    result = []
    for exc in exceptions:
        txn = exc.transaction
        imp_row = exc.import_row

        if txn is not None:
            transaction_summary = ExceptionTransactionSummary(
                source_name=txn.source_name,
                external_id=txn.external_id,
                amount=_format_amount(txn.amount),
                currency=txn.currency,
                occurred_at=txn.occurred_at,
            )
            import_row_summary = None
        else:
            transaction_summary = None
            import_row_summary = ExceptionImportRowSummary(
                row_number=imp_row.row_number,
                batch_id=imp_row.import_batch_id,
            )

        result.append(
            ExceptionItem(
                id=exc.id,
                category=exc.category,
                status=exc.status,
                version=exc.version,
                assigned_reviewer_id=exc.assigned_reviewer_id,
                details=exc.details,
                transaction=transaction_summary,
                import_row=import_row_summary,
                reconciliation_run_id=exc.reconciliation_run_id,
            )
        )
    return result


@router.get(
    "/exceptions/{exception_id}",
    response_model=ExceptionItem,
)
def get_exception(
    exception_id: uuid.UUID,
    user: Annotated[uuid.UUID, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a single exception with its details."""
    exc = (
        db.execute(
            select(ExceptionModel)
            .join(
                ReconciliationRun,
                ReconciliationRun.id == ExceptionModel.reconciliation_run_id,
            )
            .join(
                Workspace,
                Workspace.id == ReconciliationRun.workspace_id,
            )
            .join(
                OrganizationMembership,
                and_(
                    OrganizationMembership.organization_id == Workspace.organization_id,
                    OrganizationMembership.user_id == user.id,
                ),
            )
            .outerjoin(Transaction, ExceptionModel.transaction_id == Transaction.id)
            .outerjoin(ImportRow, ExceptionModel.import_row_id == ImportRow.id)
            .where(ExceptionModel.id == exception_id)
            .options(joinedload(ExceptionModel.transaction), joinedload(ExceptionModel.import_row))
        )
        .unique()
        .scalar_one_or_none()
    )

    if exc is None:
        raise HTTPException(status_code=404, detail="Exception not found")

    txn = exc.transaction
    imp_row = exc.import_row

    if txn is not None:
        transaction_summary = ExceptionTransactionSummary(
            source_name=txn.source_name,
            external_id=txn.external_id,
            amount=_format_amount(txn.amount),
            currency=txn.currency,
            occurred_at=txn.occurred_at,
        )
        import_row_summary = None
    else:
        transaction_summary = None
        import_row_summary = ExceptionImportRowSummary(
            row_number=imp_row.row_number,
            batch_id=imp_row.import_batch_id,
        )

    return ExceptionItem(
        id=exc.id,
        category=exc.category,
        status=exc.status,
        version=exc.version,
        assigned_reviewer_id=exc.assigned_reviewer_id,
        details=exc.details,
        transaction=transaction_summary,
        import_row=import_row_summary,
        reconciliation_run_id=exc.reconciliation_run_id,
    )
