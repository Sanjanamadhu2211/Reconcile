import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Transaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "transactions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("workspaces.id"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    source_name: Mapped[str] = mapped_column(sa.Text)
    external_id: Mapped[str] = mapped_column(sa.Text)
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(19, 4))
    currency: Mapped[str] = mapped_column(sa.CHAR(3))
    transaction_type: Mapped[str] = mapped_column(sa.Text)
    reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.CheckConstraint(
            "source_name IN ('orders', 'payments', 'refunds', 'settlements', 'fees')",
            name="source_name",
        ),
        sa.CheckConstraint(
            "transaction_type IN ('order', 'payment', 'refund', 'fee', 'settlement')",
            name="transaction_type",
        ),
        sa.CheckConstraint("currency = upper(currency)", name="currency_upper"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_name",
            "external_id",
            name="uq_transactions_workspace_id_source_name_external_id",
        ),
    )
