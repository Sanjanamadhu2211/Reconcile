import uuid
from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrganizationMembership, User


class Role(StrEnum):
    analyst = "analyst"
    reviewer = "reviewer"

    def covers(self, required: "Role") -> bool:
        return self is Role.reviewer or self is required


def load_membership(db: Session, user: User, organization_id: uuid.UUID) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return membership


def require_role(membership: OrganizationMembership, required: Role) -> None:
    if not Role(membership.role).covers(required):
        raise HTTPException(status_code=403, detail="Your role does not allow this")
