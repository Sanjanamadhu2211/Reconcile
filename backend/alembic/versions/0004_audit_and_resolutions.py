"""Audit events, resolutions and the append-only audit trigger

Revision ID: 0004_audit_and_resolutions
Revises: 0003_reconciliation
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_audit_and_resolutions"
down_revision: str | None = "0003_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "reconcile_app"
APP_TABLES = (
    "users",
    "organizations",
    "organization_memberships",
    "workspaces",
    "sessions",
    "import_batches",
    "import_rows",
    "transactions",
    "reconciliation_runs",
    "matches",
    "exceptions",
    "resolutions",
)

CREATE_APP_ROLE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE EXCEPTION 'cannot create role {APP_ROLE}: create it as a superuser or grant CREATEROLE';
END
$$
"""

# Blocks UPDATE, DELETE and TRUNCATE. The one exception is the actor_user_id
# SET NULL that the users foreign key runs while a user is deleted (nested trigger).
CREATE_APPEND_ONLY_FUNCTION = """
CREATE FUNCTION reject_audit_event_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND pg_trigger_depth() > 1 AND OLD.actor_user_id IS NOT NULL
       AND NEW.actor_user_id IS NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "resolutions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("exception_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("exception_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('propose', 'approve', 'reject', 'reopen')",
            name="ck_resolutions_decision",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_resolutions_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["exception_id"],
            ["exceptions.id"],
            name="fk_resolutions_exception_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_resolutions_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resolutions"),
    )
    op.create_index("ix_resolutions_organization_id", "resolutions", ["organization_id"])
    op.create_index("ix_resolutions_exception_id", "resolutions", ["exception_id"])

    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('import.created', 'import.completed', 'import.failed', "
            "'exception.proposed', 'exception.approved', 'exception.rejected', "
            "'exception.reopened')",
            name="ck_audit_events_action",
        ),
        sa.CheckConstraint(
            "target_type IN ('import_batch', 'exception')",
            name="ck_audit_events_target_type",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_events_organization_id",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index(
        "ix_audit_events_organization_id_created_at",
        "audit_events",
        ["organization_id", sa.desc("created_at")],
    )
    op.create_index(
        "ix_audit_events_target_type_target_id", "audit_events", ["target_type", "target_id"]
    )

    op.execute(CREATE_APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_change()"
    )

    op.execute(CREATE_APP_ROLE)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(APP_TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {', '.join(APP_TABLES)} FROM {APP_ROLE}")
    op.drop_table("audit_events")
    op.drop_table("resolutions")
    op.execute("DROP FUNCTION reject_audit_event_change()")
