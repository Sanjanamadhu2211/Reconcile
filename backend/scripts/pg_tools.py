"""Run the PostgreSQL client tools without putting the password on the command line."""

from __future__ import annotations

import os
import shutil
import subprocess

from sqlalchemy.engine import URL, make_url


class PgToolError(Exception):
    """A PostgreSQL client tool is missing or exited with an error."""


def find_pg_tool(name: str) -> str:
    bin_dir = os.environ.get("PG_BIN_DIR")
    path = shutil.which(name, path=bin_dir) if bin_dir else shutil.which(name)
    if path is None:
        raise PgToolError(
            f"{name} was not found; install the PostgreSQL client tools or set PG_BIN_DIR"
        )
    return path


def run_pg_tool(name: str, url: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run a client tool against url. The password goes in PGPASSWORD, never in argv."""
    parsed = make_url(url)
    uri = URL.create(
        "postgresql",
        username=parsed.username,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        query=parsed.query,
    ).render_as_string()
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    command = [find_pg_tool(name), f"--dbname={uri}", *args]
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False)
