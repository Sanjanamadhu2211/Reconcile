import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class OrganizationMembership(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "organization_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(sa.Text)

    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "organization_id", name="uq_organization_memberships_user_org"
        ),
        sa.CheckConstraint("role IN ('analyst', 'reviewer')", name="role"),
    )
