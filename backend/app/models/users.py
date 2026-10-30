import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.Text)
    password_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(sa.Text, nullable=True, unique=True)

    __table_args__ = (
        sa.Index("ix_users_email_lower", sa.text("lower(email)"), unique=True),
        sa.CheckConstraint(
            "password_hash IS NOT NULL OR google_sub IS NOT NULL",
            name="password_or_google_sub",
        ),
    )
