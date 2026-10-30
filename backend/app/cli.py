#!/usr/bin/env python3
"""
Command-line interface for the Reconcile import functionality.

This module provides the `python -m app.cli import` command for importing CSV files
with no size or row limits, unlike the web API which has a 10 MB / 50,000-row cap.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.imports import (
    BatchBusy,
    IdempotencyConflict,
    ImportFileError,
    process_batch,
)
from app.models import ImportBatch, User, Workspace


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Import CSV files for reconciliation",
        prog="python -m app.cli",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import a CSV file for reconciliation")
    import_parser.add_argument("file", type=Path, help="Path to the CSV file to import")
    import_parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace UUID to import the file into",
    )
    import_parser.add_argument(
        "--source",
        required=True,
        choices=["orders", "payments", "refunds", "settlements", "fees"],
        help="Source type for the imported data",
    )
    import_parser.add_argument(
        "--user-email", help="Email of the user creating the import (optional)"
    )

    return parser.parse_args()


def _find_user_by_email(db: Session, email: str) -> User | None:
    """Find a user by email (case-insensitive)."""
    return db.scalar(select(User).where(User.email.ilike(email.strip())))


def _find_workspace_by_id(db: Session, workspace_id) -> Workspace | None:
    """Find a workspace by its ID."""
    return db.get(Workspace, workspace_id)


def _write_error_exit(message: str, exit_code: int, to_stderr: bool = True) -> None:
    """Write error message and exit with given code."""
    if to_stderr:
        print(message, file=sys.stderr)
    else:
        print(message, file=sys.stdout)
    sys.exit(exit_code)


def _main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    args = _parse_args()

    # Validate file exists
    if not args.file.exists():
        _write_error_exit(
            f"Error: File not found: {args.file}",
            exit_code=2,
        )

    # Create session factory
    session_factory = get_session_factory()

    with session_factory() as db, session_factory() as db_for_user:
        # Look up workspace
        workspace = _find_workspace_by_id(db, args.workspace)
        if not workspace:
            _write_error_exit(
                f"Error: Workspace not found: {args.workspace}",
                exit_code=2,
            )

        # Resolve user email if provided
        user = None
        if args.user_email:
            user = _find_user_by_email(db_for_user, args.user_email)
            if not user:
                _write_error_exit(
                    f"Error: User not found: {args.user_email}",
                    exit_code=2,
                )
        else:
            # For CLI, we need a user - in a real scenario this might come from config
            # or environment. For now, we'll require it.
            _write_error_exit(
                "Error: --user-email is required for CLI import",
                exit_code=2,
            )

        # Open file in binary mode
        try:
            with open(args.file, "rb") as stream:
                # Calculate checksum by reading stream
                # Note: This bypasses the size check in create_or_get_batch
                # as required for CLI operation with files larger than web cap
                current_pos = stream.tell()
                hasher = hashlib.sha256()
                chunk_size = 8192
                while chunk := stream.read(chunk_size):
                    hasher.update(chunk)
                checksum = hasher.hexdigest()
                stream.seek(current_pos)

                # Find existing batch by checksum
                existing = db.scalar(
                    select(ImportBatch).where(
                        ImportBatch.workspace_id == workspace.id,
                        ImportBatch.file_checksum == checksum,
                    )
                )

                if existing:
                    if existing.status == "completed":
                        print(
                            f"Import already completed: batch_id={existing.id}, "
                            f"status={existing.status}, "
                            f"rows_total={existing.rows_total}, "
                            f"rows_processed={existing.rows_processed}, "
                            f"rows_failed={existing.rows_failed}"
                        )
                        return 0
                    else:
                        # Batch in progress or failed - try to claim it
                        # This is a simplified version of the claiming logic
                        from app.imports.service import CLAIMABLE

                        claim = (
                            db.execute(
                                select(ImportBatch)
                                .where(ImportBatch.id == existing.id, CLAIMABLE)
                                .with_for_update()
                            )
                            .scalars()
                            .first()
                        )

                        if claim is None:
                            if existing.status == "processing":
                                _write_error_exit(
                                    f"Error: Batch is being processed: {existing.id}",
                                    exit_code=3,
                                )
                            else:
                                # Failed batch, we can resume
                                batch = existing
                        else:
                            batch = claim
                else:
                    # Create new batch with bypass size check
                    # We need to manually create the batch without calling create_or_get_batch
                    # to avoid the size check
                    batch = ImportBatch(
                        organization_id=workspace.organization_id,
                        workspace_id=workspace.id,
                        source_name=args.source,
                        filename=args.file.name,
                        file_size_bytes=args.file.stat().st_size,
                        file_checksum=checksum,
                        status="pending",
                        created_by=user.id,
                    )
                    db.add(batch)
                    try:
                        db.commit()
                        db.refresh(batch)
                    except Exception:
                        db.rollback()
                        # Retry finding existing
                        existing = db.scalar(
                            select(ImportBatch).where(
                                ImportBatch.workspace_id == workspace.id,
                                ImportBatch.file_checksum == checksum,
                            )
                        )
                        if existing and existing.status == "completed":
                            print(
                                f"Import already completed: batch_id={existing.id}, "
                                f"status={existing.status}, "
                                f"rows_total={existing.rows_total}, "
                                f"rows_processed={existing.rows_processed}, "
                                f"rows_failed={existing.rows_failed}"
                            )
                            return 0
                        elif existing and existing.status == "processing":
                            _write_error_exit(
                                f"Error: Batch is being processed: {existing.id}",
                                exit_code=3,
                            )
                        else:
                            raise

                # Process the batch with no row cap
                try:
                    processed_batch = process_batch(
                        session_factory, batch.id, stream, max_rows=None
                    )

                    print(
                        f"Import completed: batch_id={processed_batch.id}, "
                        f"status={processed_batch.status}, "
                        f"rows_total={processed_batch.rows_total}, "
                        f"rows_processed={processed_batch.rows_processed}, "
                        f"rows_failed={processed_batch.rows_failed}"
                    )
                    return 0

                except BatchBusy as e:
                    _write_error_exit(
                        f"Error: {e}",
                        exit_code=3,
                    )
                except IdempotencyConflict as e:
                    _write_error_exit(
                        f"Error: {e}",
                        exit_code=4,
                    )
                except ImportFileError as e:
                    _write_error_exit(
                        f"Error: {e}",
                        exit_code=1,
                    )
                except Exception:
                    _write_error_exit(
                        "Error: Unexpected error while importing the file",
                        exit_code=1,
                    )

        except Exception as e:
            _write_error_exit(
                f"Error: Failed to process file: {e}",
                exit_code=1,
            )


if __name__ == "__main__":
    raise SystemExit(_main())
