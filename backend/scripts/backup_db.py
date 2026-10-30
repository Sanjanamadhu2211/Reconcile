"""Write a custom-format pg_dump of the database to a timestamped file.

Run from backend/:

    python scripts/backup_db.py --out backups

Uses DATABASE_DIRECT_URL when it is set, otherwise DATABASE_URL. Set PG_BIN_DIR when the
PostgreSQL client tools are not on PATH. The dump is restored with scripts/restore_db.py.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pg_tools import PgToolError, run_pg_tool

from app.config import get_settings


class BackupError(Exception):
    """The dump could not be written."""


def backup(url: str, out_dir: Path, now: datetime) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"reconcile-{now:%Y%m%dT%H%M%SZ}.dump"
    with target.open("x"):  # refuses to overwrite an existing dump
        pass
    try:
        result = run_pg_tool("pg_dump", url, ["--format=custom", f"--file={target}"])
    except PgToolError:
        target.unlink()
        raise
    if result.returncode != 0:
        target.unlink()
        raise BackupError(f"pg_dump failed: {result.stderr.strip()}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the database with pg_dump.")
    parser.add_argument("--out", type=Path, default=Path("backups"), help="directory for the dump")
    args = parser.parse_args(argv)

    settings = get_settings()
    url = settings.database_direct_url or settings.database_url
    try:
        target = backup(url, args.out, datetime.now(UTC))
    except (PgToolError, BackupError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
