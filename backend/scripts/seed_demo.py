"""Create a demo organization, workspace and transactions for trying the app.

Run from backend/ after migrations:

    DEMO_EMAIL=demo@example.com DEMO_PASSWORD=... python scripts/seed_demo.py

Running it again changes nothing that already exists. The user is only created when the
email is new, so an existing account keeps its password.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.db import get_session_factory
from app.models import (
    ImportBatch,
    Organization,
    OrganizationMembership,
    Transaction,
    User,
    Workspace,
)

ORG_NAME = "Demo Organization"
WORKSPACE_NAME = "Demo Workspace"
START = datetime(2026, 1, 1, 9, tzinfo=UTC)

# source, transaction type, external id, amount, hours after START
DEMO_ROWS = (
    ("orders", "order", "ORD-1001", "120.00", 0),
    ("orders", "order", "ORD-1002", "75.50", 3),
    ("payments", "payment", "PAY-5001", "120.00", 1),
    ("payments", "payment", "PAY-5002", "75.50", 4),
    ("settlements", "settlement", "PAY-5001", "120.00", 2),
    ("fees", "fee", "FEE-7001", "2.50", 5),
)


def _demo_batch(db, workspace: Workspace, user: User, source: str) -> ImportBatch:
    checksum = hashlib.sha256(f"demo-seed:{source}".encode()).hexdigest()
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.workspace_id == workspace.id, ImportBatch.file_checksum == checksum
        )
    )
    if batch is None:
        count = sum(1 for row in DEMO_ROWS if row[0] == source)
        batch = ImportBatch(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            source_name=source,
            file_size_bytes=0,
            file_checksum=checksum,
            status="completed",
            rows_total=count,
            rows_processed=count,
            created_by=user.id,
            started_at=START,
        )
        db.add(batch)
        db.flush()
    return batch


def seed(session_factory: sessionmaker, email: str, password: str) -> None:
    with session_factory() as db, db.begin():
        org = db.scalar(select(Organization).where(Organization.name == ORG_NAME))
        if org is None:
            org = Organization(name=ORG_NAME)
            db.add(org)
            db.flush()

        user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            db.flush()

        db.execute(
            insert(OrganizationMembership)
            .values(user_id=user.id, organization_id=org.id, role="reviewer")
            .on_conflict_do_nothing(index_elements=["user_id", "organization_id"])
        )

        workspace = db.scalar(
            select(Workspace).where(
                Workspace.organization_id == org.id, Workspace.name == WORKSPACE_NAME
            )
        )
        if workspace is None:
            workspace = Workspace(organization_id=org.id, name=WORKSPACE_NAME, created_by=user.id)
            db.add(workspace)
            db.flush()

        batches = {
            source: _demo_batch(db, workspace, user, source)
            for source in sorted({row[0] for row in DEMO_ROWS})
        }
        transactions = [
            {
                "organization_id": org.id,
                "workspace_id": workspace.id,
                "import_batch_id": batches[source].id,
                "source_name": source,
                "external_id": external_id,
                "amount": Decimal(amount),
                "currency": "USD",
                "transaction_type": kind,
                "reference": None,
                "occurred_at": START + timedelta(hours=hours),
            }
            for source, kind, external_id, amount, hours in DEMO_ROWS
        ]
        db.execute(
            insert(Transaction).on_conflict_do_nothing(
                index_elements=["workspace_id", "source_name", "external_id"]
            ),
            transactions,
        )


def main() -> int:
    email = os.environ.get("DEMO_EMAIL")
    password = os.environ.get("DEMO_PASSWORD")
    if not email or not password:
        print("Error: DEMO_EMAIL and DEMO_PASSWORD must both be set.", file=sys.stderr)
        return 1
    try:
        seed(get_session_factory(), email, password)
    except SQLAlchemyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Seeded {WORKSPACE_NAME} for {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
