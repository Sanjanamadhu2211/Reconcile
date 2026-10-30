import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models import Transaction


class Match(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "matches"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    reconciliation_run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True
    )
    rule: Mapped[str] = mapped_column(sa.Text)
    left_transaction_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("transactions.id", ondelete="CASCADE")
    )
    right_transaction_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("transactions.id", ondelete="CASCADE")
    )

    left_transaction: Mapped["Transaction"] = relationship(
        "Transaction", foreign_keys=[left_transaction_id], lazy="selectin"
    )
    right_transaction: Mapped["Transaction"] = relationship(
        "Transaction", foreign_keys=[right_transaction_id], lazy="selectin"
    )

    __table_args__ = (
        sa.CheckConstraint("rule IN ('exact_id', 'amount_currency_time')", name="rule"),
        sa.CheckConstraint("left_transaction_id <> right_transaction_id", name="left_ne_right"),
        sa.UniqueConstraint(
            "reconciliation_run_id",
            "left_transaction_id",
            name="uq_matches_run_id_left_transaction_id",
        ),
        sa.UniqueConstraint(
            "reconciliation_run_id",
            "right_transaction_id",
            name="uq_matches_run_id_right_transaction_id",
        ),
    )
