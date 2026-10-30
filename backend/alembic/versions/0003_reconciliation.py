"""Reconciliation run, match and exception tables

Revision ID: 0003_reconciliation
Revises: 0002_imports_and_transactions
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_reconciliation"
down_revision: str | None = "0002_imports_and_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("tolerance_hours", sa.Integer(), nullable=False),
        sa.Column("matches_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("exceptions_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_reconciliation_runs_status",
        ),
        sa.CheckConstraint("tolerance_hours > 0", name="ck_reconciliation_runs_tolerance_hours"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_reconciliation_runs_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_reconciliation_runs_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_reconciliation_runs_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reconciliation_runs"),
    )
    op.create_index(
        "ix_reconciliation_runs_organization_id", "reconciliation_runs", ["organization_id"]
    )
    op.create_index("ix_reconciliation_runs_workspace_id", "reconciliation_runs", ["workspace_id"])

    op.create_table(
        "matches",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("left_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("right_transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rule IN ('exact_id', 'amount_currency_time')", name="ck_matches_rule"),
        sa.CheckConstraint(
            "left_transaction_id <> right_transaction_id", name="ck_matches_left_ne_right"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_matches_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["reconciliation_runs.id"],
            name="fk_matches_reconciliation_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["left_transaction_id"],
            ["transactions.id"],
            name="fk_matches_left_transaction_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_transaction_id"],
            ["transactions.id"],
            name="fk_matches_right_transaction_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matches"),
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
    op.create_index("ix_matches_organization_id", "matches", ["organization_id"])
    op.create_index("ix_matches_reconciliation_run_id", "matches", ["reconciliation_run_id"])

    op.create_table(
        "exceptions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("import_row_id", sa.Uuid(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("assigned_reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('unmatched', 'ambiguous', 'amount_mismatch', 'duplicate')",
            name="ck_exceptions_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'proposed', 'resolved')", name="ck_exceptions_status"
        ),
        sa.CheckConstraint(
            "transaction_id IS NOT NULL OR import_row_id IS NOT NULL",
            name="ck_exceptions_transaction_or_import_row",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_exceptions_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_exceptions_workspace_id",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["reconciliation_runs.id"],
            name="fk_exceptions_reconciliation_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_exceptions_transaction_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_row_id"],
            ["import_rows.id"],
            name="fk_exceptions_import_row_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_reviewer_id"],
            ["users.id"],
            name="fk_exceptions_assigned_reviewer_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exceptions"),
    )
    op.create_index("ix_exceptions_organization_id", "exceptions", ["organization_id"])
    op.create_index("ix_exceptions_workspace_id", "exceptions", ["workspace_id"])
    op.create_index("ix_exceptions_reconciliation_run_id", "exceptions", ["reconciliation_run_id"])
    op.create_index(
        "ix_exceptions_run_id_transaction_id",
        "exceptions",
        ["reconciliation_run_id", "transaction_id"],
        unique=True,
        postgresql_where=sa.text("transaction_id IS NOT NULL"),
    )
    op.create_index(
        "ix_exceptions_run_id_import_row_id",
        "exceptions",
        ["reconciliation_run_id", "import_row_id"],
        unique=True,
        postgresql_where=sa.text("import_row_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("exceptions")
    op.drop_table("matches")
    op.drop_table("reconciliation_runs")
