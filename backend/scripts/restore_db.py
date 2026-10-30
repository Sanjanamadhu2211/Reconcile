"""Restore a pg_dump custom-format file into an empty database and print the row counts.

Run from backend/:

    python scripts/restore_db.py --dump backups/reconcile-20260101T000000Z.dump --target-url URL

The target must be empty. Pass --force to restore over existing tables; that drops and
recreates the objects in the dump. The target cluster needs the reconcile_app role first,
because the dump grants privileges to it. Set PG_BIN_DIR when the PostgreSQL client tools
are not on PATH.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pg_tools import PgToolError, run_pg_tool
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.sql import table


class RestoreError(Exception):
    """The dump could not be restored into the target."""


def restore(dump: Path, target_url: str, *, force: bool) -> None:
    if not dump.is_file():
        raise RestoreError(f"{dump} does not exist")
    engine = create_engine(target_url)
    try:
        existing = inspect(engine).get_table_names()
    finally:
        engine.dispose()
    if existing and not force:
        raise RestoreError(
            f"the target already has {len(existing)} tables; restore into an empty database "
            "or pass --force"
        )

    args = ["--no-owner", "--exit-on-error"]
    if force:
        args += ["--clean", "--if-exists"]
    result = run_pg_tool("pg_restore", target_url, [*args, str(dump)])
    if result.returncode != 0:
        raise RestoreError(f"pg_restore failed: {result.stderr.strip()}")


def row_counts(target_url: str) -> dict[str, int]:
    engine = create_engine(target_url)
    try:
        with engine.connect() as conn:
            names = inspect(conn).get_table_names()
            return {
                name: conn.execute(select(func.count()).select_from(table(name))).scalar_one()
                for name in names
            }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a pg_dump file into an empty database.")
    parser.add_argument("--dump", type=Path, required=True, help="custom-format dump file")
    parser.add_argument("--target-url", required=True, help="database URL to restore into")
    parser.add_argument("--force", action="store_true", help="restore over existing tables")
    args = parser.parse_args(argv)

    try:
        restore(args.dump, args.target_url, force=args.force)
        counts = row_counts(args.target_url)
    except (PgToolError, RestoreError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Restored {args.dump}")
    for name, count in sorted(counts.items()):
        print(f"  {name:<30} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
