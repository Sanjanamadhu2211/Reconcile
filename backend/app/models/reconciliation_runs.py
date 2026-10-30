import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ReconciliationRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reconciliation_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("workspaces.id"), index=True
    )
    rule_version: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text, server_default="pending")
    tolerance_hours: Mapped[int] = mapped_column(sa.Integer)
    matches_count: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    exceptions_count: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')", name="status"
        ),
        sa.CheckConstraint("tolerance_hours > 0", name="tolerance_hours"),
    )
