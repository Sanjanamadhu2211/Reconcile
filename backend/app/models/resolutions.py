import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Resolution(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "resolutions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    exception_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("exceptions.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(sa.Text)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    exception_version: Mapped[int] = mapped_column(sa.Integer)

    __table_args__ = (
        sa.CheckConstraint(
            "decision IN ('propose', 'approve', 'reject', 'reopen')", name="decision"
        ),
    )
