import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.permissions import Role, load_membership, require_role
from app.db import get_db
from app.models import OrganizationMembership, User, Workspace
from app.pagination import Limit, Offset
from app.schemas.workspaces import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate

router = APIRouter(
    prefix="/api/v1/workspaces",
    tags=["workspaces"],
    dependencies=[Depends(get_current_user)],
)


def _member_workspace(
    db: Session, user: User, workspace_id: uuid.UUID
) -> tuple[Workspace, OrganizationMembership]:
    # Workspaces outside the caller's organizations match nothing, like missing ones
    row = db.execute(
        select(Workspace, OrganizationMembership)
        .join(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Workspace.organization_id,
                OrganizationMembership.user_id == user.id,
            ),
        )
        .where(Workspace.id == workspace_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return tuple(row)


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A workspace with that name already exists"
        ) from None


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    organization_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    query = (
        select(Workspace)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Workspace.organization_id,
        )
        .where(OrganizationMembership.user_id == user.id)
    )
    if organization_id is not None:
        query = query.where(Workspace.organization_id == organization_id)
    return db.scalars(
        query.order_by(Workspace.created_at, Workspace.id).limit(limit).offset(offset)
    ).all()


@router.post(
    "",
    status_code=201,
    response_model=WorkspaceOut,
    dependencies=[Depends(require_csrf)],
)
def create_workspace(
    body: WorkspaceCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_role(load_membership(db, user, body.organization_id), Role.reviewer)
    workspace = Workspace(
        organization_id=body.organization_id,
        name=body.name,
        timestamp_tolerance_hours=body.timestamp_tolerance_hours,
        created_by=user.id,
    )
    db.add(workspace)
    _commit_or_conflict(db)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    workspace, _ = _member_workspace(db, user, workspace_id)
    return workspace


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceOut,
    dependencies=[Depends(require_csrf)],
)
def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    workspace, membership = _member_workspace(db, user, workspace_id)
    require_role(membership, Role.reviewer)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(workspace, field, value)
    _commit_or_conflict(db)
    return workspace


@router.delete(
    "/{workspace_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def delete_workspace(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    workspace, membership = _member_workspace(db, user, workspace_id)
    require_role(membership, Role.reviewer)
    db.delete(workspace)
    db.commit()
