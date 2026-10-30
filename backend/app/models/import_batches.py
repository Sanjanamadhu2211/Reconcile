import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ImportBatch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "import_batches"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("workspaces.id"), index=True
    )
    source_name: Mapped[str] = mapped_column(sa.Text)
    filename: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    file_checksum: Mapped[str] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, server_default="pending")
    rows_total: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    rows_processed: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    rows_failed: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()")
    )

    __table_args__ = (
        sa.CheckConstraint(
            "source_name IN ('orders', 'payments', 'refunds', 'settlements', 'fees')",
            name="source_name",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="status",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "file_checksum",
            name="uq_import_batches_workspace_id_file_checksum",
        ),
        sa.Index(
            "ix_import_batches_workspace_id_idempotency_key",
            "workspace_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        ),
    )
