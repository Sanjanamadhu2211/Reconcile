import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.auth.permissions import Role, require_role
from app.models import Exception as ExceptionModel
from app.models import OrganizationMembership, Resolution, User

# decision: (from status, to status, role required, audit action)
TRANSITIONS = {
    "propose": ("open", "proposed", Role.analyst, "exception.proposed"),
    "approve": ("proposed", "resolved", Role.reviewer, "exception.approved"),
    "reject": ("proposed", "open", Role.reviewer, "exception.rejected"),
    "reopen": ("resolved", "open", Role.reviewer, "exception.reopened"),
}


def transition(
    db: Session,
    *,
    decision: str,
    exception: ExceptionModel,
    membership: OrganizationMembership,
    user: User,
    version: int,
    note: str | None,
) -> None:
    from_status, to_status, required_role, action = TRANSITIONS[decision]
    require_role(membership, required_role)
    if exception.status != from_status:
        raise HTTPException(
            status_code=409, detail=f"Cannot {decision} an exception that is {exception.status}"
        )
    if decision == "approve" and _proposer_id(db, exception.id) == user.id:
        raise HTTPException(status_code=403, detail="You cannot approve your own proposal")

    updated = db.execute(
        update(ExceptionModel)
        .where(
            ExceptionModel.id == exception.id,
            ExceptionModel.version == version,
            ExceptionModel.status == from_status,
        )
        .values(status=to_status, version=version + 1, updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated == 0:
        raise HTTPException(
            status_code=409, detail="The exception is stale or was already changed, reload it"
        )

    db.add(
        Resolution(
            organization_id=exception.organization_id,
            exception_id=exception.id,
            actor_user_id=user.id,
            decision=decision,
            note=note,
            exception_version=version + 1,
        )
    )
    audit.record(
        db,
        organization_id=exception.organization_id,
        actor=user,
        action=action,
        target_type="exception",
        target_id=exception.id,
        metadata={"from": from_status, "to": to_status, "version": version + 1},
    )
    db.commit()


def _proposer_id(db: Session, exception_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(Resolution.actor_user_id)
        .where(Resolution.exception_id == exception_id, Resolution.decision == "propose")
        .order_by(Resolution.created_at.desc())
        .limit(1)
    )
