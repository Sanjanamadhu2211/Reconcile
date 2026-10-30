import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User
from app.models.audit_events import AUDIT_ACTIONS, AUDIT_TARGET_TYPES


def record(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add the event to the caller's transaction without committing.

    Metadata never holds raw CSV row values or credentials.
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action: {action}")
    if target_type not in AUDIT_TARGET_TYPES:
        raise ValueError(f"unknown audit target type: {target_type}")

    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else "system",
        action=action,
        target_type=target_type,
        target_id=target_id,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.flush()
    return event
