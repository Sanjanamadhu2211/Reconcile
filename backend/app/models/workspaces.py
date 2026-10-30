import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "workspaces"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(sa.Text)
    timestamp_tolerance_hours: Mapped[int] = mapped_column(sa.Integer, server_default="24")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        sa.UniqueConstraint("organization_id", "name", name="uq_workspaces_organization_id_name"),
        sa.CheckConstraint("timestamp_tolerance_hours > 0", name="timestamp_tolerance"),
    )
