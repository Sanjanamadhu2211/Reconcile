"""Imports and transactions tables

Revision ID: 0002_imports_and_transactions
Revises: 0001_identity_and_tenancy
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_imports_and_transactions"
down_revision: str | None = "0001_identity_and_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_checksum", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("rows_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_name IN ('orders', 'payments', 'refunds', 'settlements', 'fees')",
            name="ck_import_batches_source_name",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_import_batches_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_import_batches_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_import_batches_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.UniqueConstraint(
            "workspace_id",
            "file_checksum",
            name="uq_import_batches_workspace_id_file_checksum",
        ),
    )
    op.create_index("ix_import_batches_organization_id", "import_batches", ["organization_id"])
    op.create_index("ix_import_batches_workspace_id", "import_batches", ["workspace_id"])
    op.create_index(
        "ix_import_batches_workspace_id_idempotency_key",
        "import_batches",
        ["workspace_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "import_rows",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("validation_status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'BAD_AMOUNT', 'BAD_CURRENCY', 'BAD_TIMESTAMP', "
            "'MISSING_REQUIRED', 'DUPLICATE_IN_FILE', 'UNKNOWN_TYPE')",
            name="ck_import_rows_validation_status",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('BAD_AMOUNT', 'BAD_CURRENCY', "
            "'BAD_TIMESTAMP', 'MISSING_REQUIRED', 'DUPLICATE_IN_FILE', 'UNKNOWN_TYPE')",
            name="ck_import_rows_error_code",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_import_rows_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_import_rows_import_batch_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_rows"),
        sa.UniqueConstraint(
            "import_batch_id",
            "row_number",
            name="uq_import_rows_import_batch_id_row_number",
        ),
    )
    op.create_index("ix_import_rows_organization_id", "import_rows", ["organization_id"])
    op.create_index("ix_import_rows_import_batch_id", "import_rows", ["import_batch_id"])

    op.create_table(
        "transactions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_name IN ('orders', 'payments', 'refunds', 'settlements', 'fees')",
            name="ck_transactions_source_name",
        ),
        sa.CheckConstraint(
            "transaction_type IN ('order', 'payment', 'refund', 'fee', 'settlement')",
            name="ck_transactions_transaction_type",
        ),
        sa.CheckConstraint("currency = upper(currency)", name="ck_transactions_currency_upper"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_transactions_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_transactions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_transactions_import_batch_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_name",
            "external_id",
            name="uq_transactions_workspace_id_source_name_external_id",
        ),
    )
    op.create_index("ix_transactions_organization_id", "transactions", ["organization_id"])
    op.create_index("ix_transactions_workspace_id", "transactions", ["workspace_id"])
    op.create_index("ix_transactions_import_batch_id", "transactions", ["import_batch_id"])


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("import_rows")
    op.drop_table("import_batches")
