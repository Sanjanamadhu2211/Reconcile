import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

AUDIT_ACTIONS = (
    "import.created",
    "import.completed",
    "import.failed",
    "exception.proposed",
    "exception.approved",
    "exception.rejected",
    "exception.reopened",
)
AUDIT_TARGET_TYPES = ("import_batch", "exception")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(sa.Text)
    action: Mapped[str] = mapped_column(sa.Text)
    target_type: Mapped[str] = mapped_column(sa.Text)
    target_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=sa.text("'{}'::jsonb")
    )

    __table_args__ = (
        sa.CheckConstraint(f"action IN ({_sql_list(AUDIT_ACTIONS)})", name="action"),
        sa.CheckConstraint(f"target_type IN ({_sql_list(AUDIT_TARGET_TYPES)})", name="target_type"),
        sa.Index(
            "ix_audit_events_organization_id_created_at",
            "organization_id",
            sa.desc("created_at"),
        ),
        sa.Index("ix_audit_events_target_type_target_id", "target_type", "target_id"),
    )
