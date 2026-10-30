import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models import ImportRow, Transaction


class Exception(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exceptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("workspaces.id"), index=True
    )
    reconciliation_run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(sa.Text)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True
    )
    import_row_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("import_rows.id", ondelete="CASCADE"), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, server_default="open")
    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(sa.Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()")
    )

    transaction: Mapped["Transaction | None"] = relationship("Transaction", lazy="selectin")
    import_row: Mapped["ImportRow | None"] = relationship("ImportRow", lazy="selectin")

    __table_args__ = (
        sa.CheckConstraint(
            "category IN ('unmatched', 'ambiguous', 'amount_mismatch', 'duplicate')",
            name="category",
        ),
        sa.CheckConstraint("status IN ('open', 'proposed', 'resolved')", name="status"),
        sa.CheckConstraint(
            "transaction_id IS NOT NULL OR import_row_id IS NOT NULL",
            name="transaction_or_import_row",
        ),
        sa.Index(
            "ix_exceptions_run_id_transaction_id",
            "reconciliation_run_id",
            "transaction_id",
            unique=True,
            postgresql_where=sa.text("transaction_id IS NOT NULL"),
        ),
        sa.Index(
            "ix_exceptions_run_id_import_row_id",
            "reconciliation_run_id",
            "import_row_id",
            unique=True,
            postgresql_where=sa.text("import_row_id IS NOT NULL"),
        ),
    )
