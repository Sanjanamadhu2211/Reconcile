import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ImportRow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_rows"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("import_batches.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(sa.Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(sa.Text)
    error_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'BAD_AMOUNT', 'BAD_CURRENCY', 'BAD_TIMESTAMP', "
            "'MISSING_REQUIRED', 'DUPLICATE_IN_FILE', 'UNKNOWN_TYPE')",
            name="validation_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('BAD_AMOUNT', 'BAD_CURRENCY', "
            "'BAD_TIMESTAMP', 'MISSING_REQUIRED', 'DUPLICATE_IN_FILE', 'UNKNOWN_TYPE')",
            name="error_code",
        ),
        sa.UniqueConstraint(
            "import_batch_id", "row_number", name="uq_import_rows_import_batch_id_row_number"
        ),
    )
