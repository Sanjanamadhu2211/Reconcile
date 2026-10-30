import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.permissions import Role, load_member_workspace, require_role
from app.db import get_db, get_session_factory
from app.models import OrganizationMembership, ReconciliationRun, User
from app.reconciliation.runner import RunInProgress, run_reconciliation
from app.schemas.reconciliation import ReconciliationRunOut

router = APIRouter(
    prefix="/api/v1",
    tags=["reconciliation"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/workspaces/{workspace_id}/reconciliation-runs",
    status_code=201,
    response_model=ReconciliationRunOut,
    dependencies=[Depends(require_csrf)],
)
def create_reconciliation_run(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    workspace, membership = load_member_workspace(db, user, workspace_id)
    require_role(membership, Role.analyst)
    try:
        return run_reconciliation(get_session_factory(), workspace_id=workspace.id, user_id=user.id)
    except RunInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reconciliation-runs/{run_id}", response_model=ReconciliationRunOut)
def get_reconciliation_run(
    run_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    # Runs of organizations the caller does not belong to match nothing, like missing ones
    run = db.scalar(
        select(ReconciliationRun)
        .join(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == ReconciliationRun.organization_id,
                OrganizationMembership.user_id == user.id,
            ),
        )
        .where(ReconciliationRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return run
