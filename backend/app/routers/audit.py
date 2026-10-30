import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.permissions import load_membership
from app.db import get_db
from app.models import AuditEvent, OrganizationMembership, User
from app.pagination import Limit, Offset
from app.schemas.audit import AuditEventOut

router = APIRouter(
    prefix="/api/v1/audit-events",
    tags=["audit"],
    dependencies=[Depends(get_current_user)],
)


def _only_organization(db: Session, user: User) -> uuid.UUID:
    organization_ids = db.scalars(
        select(OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user.id)
        .limit(2)
    ).all()
    if len(organization_ids) != 1:
        raise HTTPException(status_code=422, detail="organization_id is required")
    return organization_ids[0]


@router.get("", response_model=list[AuditEventOut])
def list_audit_events(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    organization_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=64),
    target_type: str | None = Query(default=None, max_length=64),
    target_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    if organization_id is None:
        organization_id = _only_organization(db, user)
    load_membership(db, user, organization_id)

    query = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
    if action is not None:
        query = query.where(AuditEvent.action == action)
    if target_type is not None:
        query = query.where(AuditEvent.target_type == target_type)
    if target_id is not None:
        query = query.where(AuditEvent.target_id == target_id)
    return db.scalars(
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
