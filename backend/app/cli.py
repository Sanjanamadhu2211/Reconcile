#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db import get_session_factory
from app.imports import (
    BatchBusy,
    IdempotencyConflict,
    ImportFileError,
    create_or_get_batch,
    process_batch,
)
from app.models import User, Workspace


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="Import a CSV file for reconciliation")
    imp.add_argument("file", type=Path, help="Path to the CSV file to import")
    imp.add_argument("--workspace", required=True, help="Workspace UUID")
    imp.add_argument(
        "--source",
        required=True,
        choices=["orders", "payments", "refunds", "settlements", "fees"],
        help="Source type for the imported data",
    )
    imp.add_argument("--user-email", help="Email of the user creating the import (optional)")
    return parser.parse_args(argv)


def _find_user(db, email: str) -> User | None:
    return db.scalar(select(User).where(User.email.ilike(email.strip())))


def _find_workspace(db, workspace_id: UUID) -> Workspace | None:
    return db.get(Workspace, workspace_id)


def _err(msg: str, code: int) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.file.exists():
        return _err(f"Error: File not found: {args.file}", 2)

    try:
        workspace_id = UUID(args.workspace)
    except ValueError:
        return _err("Error: Invalid workspace UUID", 2)

    session_factory = get_session_factory()

    with session_factory() as db:
        workspace = _find_workspace(db, workspace_id)
        if not workspace:
            return _err(f"Error: Workspace not found: {workspace_id}", 2)

        user = None
        if args.user_email:
            user = _find_user(db, args.user_email)
            if not user:
                return _err(f"Error: User not found: {args.user_email}", 2)

        try:
            with open(args.file, "rb") as stream:
                batch, created = create_or_get_batch(
                    db,
                    user=user,
                    workspace=workspace,
                    source_name=args.source,
                    filename=args.file.name,
                    stream=stream,
                    enforce_size_cap=False,
                )

                if batch.status == "completed":
                    print(
                        f"Import already completed: batch_id={batch.id}, "
                        f"status={batch.status}, "
                        f"rows_total={batch.rows_total}, "
                        f"rows_processed={batch.rows_processed}, "
                        f"rows_failed={batch.rows_failed}"
                    )
                    return 0

                stream.seek(0)
                processed = process_batch(
                    session_factory, batch.id, stream, max_rows=None, actor=user
                )

                print(
                    f"Import completed: batch_id={processed.id}, "
                    f"status={processed.status}, "
                    f"rows_total={processed.rows_total}, "
                    f"rows_processed={processed.rows_processed}, "
                    f"rows_failed={processed.rows_failed}"
                )
                return 0

        except BatchBusy as e:
            return _err(f"Error: {e}", 3)
        except IdempotencyConflict as e:
            return _err(f"Error: {e}", 4)
        except ImportFileError as e:
            return _err(f"Error: {e}", 1)
        except Exception:
            return _err("Error: Unexpected error while importing the file", 1)


if __name__ == "__main__":
    raise SystemExit(main())
