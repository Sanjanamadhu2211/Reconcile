import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import backup_db  # noqa: E402
import benchmark  # noqa: E402
import pg_tools  # noqa: E402
import restore_db  # noqa: E402

URL = "postgresql+psycopg://backup_user:test-only-placeholder@db.example.com:5432/reconcile?sslmode=require"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _completed(returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stderr=stderr)


def test_find_pg_tool_reports_a_missing_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("PG_BIN_DIR", str(tmp_path))
    monkeypatch.setattr(pg_tools.shutil, "which", lambda name, path=None: None)

    with pytest.raises(pg_tools.PgToolError, match="PG_BIN_DIR"):
        pg_tools.find_pg_tool("pg_dump")


def test_find_pg_tool_searches_pg_bin_dir(monkeypatch, tmp_path):
    seen = {}

    def fake_which(name, path=None):
        seen.update(name=name, path=path)
        return str(tmp_path / name)

    monkeypatch.setenv("PG_BIN_DIR", str(tmp_path))
    monkeypatch.setattr(pg_tools.shutil, "which", fake_which)

    assert pg_tools.find_pg_tool("pg_restore") == str(tmp_path / "pg_restore")
    assert seen == {"name": "pg_restore", "path": str(tmp_path)}


def test_run_pg_tool_keeps_the_password_out_of_argv(monkeypatch):
    calls = {}

    def fake_run(command, **kwargs):
        calls.update(command=command, env=kwargs["env"])
        return _completed()

    monkeypatch.setattr(pg_tools, "find_pg_tool", lambda name: f"/bin/{name}")
    monkeypatch.setattr(pg_tools.subprocess, "run", fake_run)

    pg_tools.run_pg_tool("pg_dump", URL, ["--format=custom"])

    argv = " ".join(calls["command"])
    assert "test-only-placeholder" not in argv
    assert calls["command"][0] == "/bin/pg_dump"
    assert calls["command"][1] == (
        "--dbname=postgresql://backup_user@db.example.com:5432/reconcile?sslmode=require"
    )
    assert calls["env"]["PGPASSWORD"] == "test-only-placeholder"


def test_backup_writes_a_custom_format_dump_with_a_timestamped_name(monkeypatch, tmp_path):
    seen = {}

    def fake_run_pg_tool(name, url, args):
        seen.update(name=name, url=url, args=args)
        return _completed()

    monkeypatch.setattr(backup_db, "run_pg_tool", fake_run_pg_tool)

    target = backup_db.backup(URL, tmp_path, NOW)

    assert target == tmp_path / "reconcile-20260102T030405Z.dump"
    assert seen["name"] == "pg_dump"
    assert seen["url"] == URL
    assert "--format=custom" in seen["args"]
    assert f"--file={target}" in seen["args"]


def test_backup_refuses_to_overwrite_an_existing_dump(monkeypatch, tmp_path):
    (tmp_path / "reconcile-20260102T030405Z.dump").write_bytes(b"keep me")
    monkeypatch.setattr(backup_db, "run_pg_tool", lambda *args: pytest.fail("pg_dump must not run"))

    with pytest.raises(FileExistsError):
        backup_db.backup(URL, tmp_path, NOW)

    assert (tmp_path / "reconcile-20260102T030405Z.dump").read_bytes() == b"keep me"


def test_backup_removes_the_partial_file_when_pg_dump_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backup_db, "run_pg_tool", lambda *args: _completed(1, stderr="connection refused")
    )

    with pytest.raises(backup_db.BackupError, match="connection refused"):
        backup_db.backup(URL, tmp_path, NOW)

    assert list(tmp_path.iterdir()) == []


def test_backup_fails_clearly_when_pg_dump_is_missing(monkeypatch, tmp_path):
    def missing(*args):
        raise pg_tools.PgToolError("pg_dump was not found")

    monkeypatch.setattr(backup_db, "run_pg_tool", missing)

    with pytest.raises(pg_tools.PgToolError):
        backup_db.backup(URL, tmp_path, NOW)

    assert list(tmp_path.iterdir()) == []


def test_restore_refuses_a_target_that_already_has_tables(monkeypatch, tmp_path):
    dump = tmp_path / "reconcile.dump"
    dump.write_bytes(b"dump")

    class FakeEngine:
        def dispose(self):
            pass

    monkeypatch.setattr(restore_db, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(
        restore_db,
        "inspect",
        lambda engine: SimpleNamespace(get_table_names=lambda: ["organizations", "users"]),
    )
    monkeypatch.setattr(
        restore_db, "run_pg_tool", lambda *args: pytest.fail("pg_restore must not run")
    )

    with pytest.raises(restore_db.RestoreError, match="already has 2 tables"):
        restore_db.restore(dump, URL, force=False)


def test_restore_runs_pg_restore_with_no_owner_and_exit_on_error(monkeypatch, tmp_path):
    dump = tmp_path / "reconcile.dump"
    dump.write_bytes(b"dump")
    seen = {}

    class FakeEngine:
        def dispose(self):
            pass

    def fake_run_pg_tool(name, url, args):
        seen.update(name=name, url=url, args=args)
        return _completed()

    monkeypatch.setattr(restore_db, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(
        restore_db, "inspect", lambda engine: SimpleNamespace(get_table_names=lambda: [])
    )
    monkeypatch.setattr(restore_db, "run_pg_tool", fake_run_pg_tool)

    restore_db.restore(dump, URL, force=False)

    assert seen["name"] == "pg_restore"
    assert seen["url"] == URL
    assert seen["args"] == ["--no-owner", "--exit-on-error", str(dump)]


def test_restore_with_force_cleans_existing_objects_first(monkeypatch, tmp_path):
    dump = tmp_path / "reconcile.dump"
    dump.write_bytes(b"dump")
    seen = {}

    class FakeEngine:
        def dispose(self):
            pass

    monkeypatch.setattr(restore_db, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(
        restore_db, "inspect", lambda engine: SimpleNamespace(get_table_names=lambda: ["users"])
    )
    monkeypatch.setattr(
        restore_db, "run_pg_tool", lambda name, url, args: seen.update(args=args) or _completed()
    )

    restore_db.restore(dump, URL, force=True)

    assert "--clean" in seen["args"]
    assert "--if-exists" in seen["args"]


def test_restore_reports_pg_restore_failures(monkeypatch, tmp_path):
    dump = tmp_path / "reconcile.dump"
    dump.write_bytes(b"dump")

    class FakeEngine:
        def dispose(self):
            pass

    monkeypatch.setattr(restore_db, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(
        restore_db, "inspect", lambda engine: SimpleNamespace(get_table_names=lambda: [])
    )
    monkeypatch.setattr(
        restore_db, "run_pg_tool", lambda *args: _completed(1, stderr="role missing")
    )

    with pytest.raises(restore_db.RestoreError, match="role missing"):
        restore_db.restore(dump, URL, force=False)


def test_benchmark_rejects_rows_outside_the_supported_range():
    with pytest.raises(SystemExit):
        benchmark._parse_args(["--rows", "50"])
    with pytest.raises(SystemExit):
        benchmark._parse_args(["--rows", "100001"])


def test_benchmark_rejects_match_ratio_above_the_limit():
    with pytest.raises(SystemExit):
        benchmark._parse_args(["--match-ratio", "0.95"])


def test_benchmark_defaults():
    args = benchmark._parse_args([])

    assert (args.rows, args.match_ratio, args.seed, args.json) == (10_000, 0.8, 1, False)


@pytest.mark.parametrize("rows", [100, 600, 10_000])
def test_benchmark_dataset_has_the_requested_order_count(rows):
    dataset = benchmark.Dataset.build(rows, 0.8, 1)

    assert dataset.orders == rows
    assert dataset.expected_matches == 2 * len(dataset.exact) + 2 * len(dataset.timed)
