"""Time the import and reconciliation path on synthetic data and check the matches.

Run from backend/ after the migrations are applied to DATABASE_URL:

    python scripts/benchmark.py --rows 10000

The script creates its own organization, user and workspace, generates orders, payments
and settlements whose outcome is known in advance, imports them through the same service
the API uses and reconciles the workspace. It exits 1 unless every match and exception
count agrees with that known outcome. Afterwards it deletes the workspace data it wrote.
The organization, the user and their audit events stay, because audit_events is
append-only and references the organization.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import accumulate, chain, pairwise

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import aliased

from app.db import get_session_factory
from app.imports import create_or_get_batch, process_batch
from app.models import Exception as ExceptionRow
from app.models import (
    ImportBatch,
    Organization,
    ReconciliationRun,
    Transaction,
    User,
    Workspace,
)
from app.models import Match as MatchRow
from app.reconciliation.runner import run_reconciliation

try:
    import resource
except ImportError:  # Windows has no getrusage
    resource = None

START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_SECONDS = 90 * 24 * 60 * 60
MIN_ROWS = 100
MAX_ROWS = 100_000
MISMATCH_SHARE = 0.01
AMBIGUOUS_SHARE = 0.01
ORPHAN_SHARE = 0.01
MAX_MATCH_RATIO = 0.9

SOURCES = (
    ("orders", ["order_id", "amount", "currency", "order_date", "customer_id"]),
    ("payments", ["payment_id", "amount", "currency", "paid_at", "order_id"]),
    ("settlements", ["settlement_id", "amount", "currency", "settled_at", "batch_reference"]),
)

# (left source, right source, rule) -> (left id prefix, right id prefix, Dataset block)
EXPECTED_PAIRINGS = {
    ("orders", "payments", "exact_id"): ("ORD", "ORD", "exact"),
    ("orders", "payments", "amount_currency_time"): ("ORD", "PAY", "timed"),
    ("payments", "settlements", "exact_id"): ("ORD", "ORD", "exact"),
    ("payments", "settlements", "amount_currency_time"): ("PAY", "SET", "timed"),
}


class BenchmarkFailure(Exception):
    """A run step did not produce the expected result."""


@dataclass(frozen=True)
class Dataset:
    seed: int
    exact: range
    timed: range
    mismatched: range
    groups: range
    unmatched: range
    orphans: range

    @classmethod
    def build(cls, rows: int, match_ratio: float, seed: int) -> Dataset:
        matched = round(rows * match_ratio)
        mismatched = max(1, round(rows * MISMATCH_SHARE))
        group_count = max(1, round(rows * AMBIGUOUS_SHARE) // 2)
        unmatched = rows - matched - mismatched - 2 * group_count
        if unmatched < 0:
            raise ValueError("the match ratio leaves no room for the unmatched orders")
        counts = (
            matched // 2,
            matched - matched // 2,
            mismatched,
            2 * group_count,
            unmatched,
            max(1, round(rows * ORPHAN_SHARE)),
        )
        exact, timed, mismatch, grouped, unmatched_slots, orphans = (
            range(start, stop) for start, stop in pairwise(accumulate(counts, initial=0))
        )
        return cls(
            seed=seed,
            exact=exact,
            timed=timed,
            mismatched=mismatch,
            groups=grouped[::2],
            unmatched=unmatched_slots,
            orphans=orphans,
        )

    @property
    def orders(self) -> int:
        return (
            len(self.exact)
            + len(self.timed)
            + len(self.mismatched)
            + len(self.unmatched)
            + 2 * len(self.groups)
        )

    @property
    def payments(self) -> int:
        return (
            len(self.exact)
            + len(self.timed)
            + len(self.mismatched)
            + len(self.groups)
            + len(self.orphans)
        )

    @property
    def settlements(self) -> int:
        return len(self.exact) + len(self.timed)

    @property
    def expected_matches(self) -> int:
        return 2 * (len(self.exact) + len(self.timed))

    @property
    def expected_exceptions(self) -> dict[str, int]:
        return {
            "ambiguous": 3 * len(self.groups),
            "amount_mismatch": 2 * len(self.mismatched),
            "unmatched": len(self.unmatched) + len(self.orphans),
        }


def _amount(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _currency(slot: int) -> str:
    return "EUR" if slot % 2 else "USD"


def _order_time(seed: int, slot: int) -> datetime:
    return START + timedelta(seconds=(slot * 2654435761 + seed) % WINDOW_SECONDS)


def _timed_shift(slot: int) -> timedelta:
    return timedelta(seconds=(slot * 40009) % 72000 - 36000)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _order_rows(dataset: Dataset):
    def order(number: int, slot: int) -> list[str]:
        return [
            f"ORD-{number}",
            _amount(1000 + slot),
            _currency(slot),
            _iso(_order_time(dataset.seed, slot)),
            f"CUST-{number % 1000}",
        ]

    for slot in chain(dataset.exact, dataset.timed, dataset.mismatched, dataset.unmatched):
        yield order(slot, slot)
    for base in dataset.groups:
        yield order(base, base)
        yield order(base + 1, base)


def _payment_rows(dataset: Dataset):
    def payment(external_id: str, cents: int, slot: int, moment: datetime) -> list[str]:
        return [external_id, _amount(cents), _currency(slot), _iso(moment), ""]

    seed = dataset.seed
    for slot in dataset.exact:
        when = _order_time(seed, slot) + timedelta(minutes=5)
        yield payment(f"ORD-{slot}", 1000 + slot, slot, when)
    for slot in dataset.timed:
        when = _order_time(seed, slot) + _timed_shift(slot)
        yield payment(f"PAY-{slot}", 1000 + slot, slot, when)
    for slot in dataset.mismatched:
        yield payment(f"ORD-{slot}", 100_000_000 + slot, slot, _order_time(seed, slot))
    for base in dataset.groups:
        yield payment(f"PAY-{base}", 1000 + base, base, _order_time(seed, base))
    for slot in dataset.orphans:
        yield payment(f"PAY-{slot}", 1000 + slot, slot, _order_time(seed, slot))


def _settlement_rows(dataset: Dataset):
    def settlement(external_id: str, slot: int, moment: datetime) -> list[str]:
        return [external_id, _amount(1000 + slot), _currency(slot), _iso(moment), ""]

    seed = dataset.seed
    for slot in dataset.exact:
        yield settlement(f"ORD-{slot}", slot, _order_time(seed, slot) + timedelta(hours=1))
    for slot in dataset.timed:
        when = _order_time(seed, slot) + _timed_shift(slot) + timedelta(hours=2)
        yield settlement(f"SET-{slot}", slot, when)


ROW_BUILDERS = {
    "orders": _order_rows,
    "payments": _payment_rows,
    "settlements": _settlement_rows,
}


def _number(external_id: str, prefix: str) -> int | None:
    head, _, digits = external_id.partition("-")
    return int(digits) if head == prefix else None


def _is_expected_match(
    dataset: Dataset,
    rule: str,
    left_source: str,
    left_id: str,
    right_source: str,
    right_id: str,
) -> bool:
    pattern = EXPECTED_PAIRINGS.get((left_source, right_source, rule))
    if pattern is None:
        return False
    left_prefix, right_prefix, block = pattern
    left_number = _number(left_id, left_prefix)
    return (
        left_number is not None
        and _number(right_id, right_prefix) == left_number
        and left_number in getattr(dataset, block)
    )


def _write_csv(stream, header: list[str], rows) -> int:
    text_stream = io.TextIOWrapper(stream, encoding="utf-8", newline="", write_through=True)
    writer = csv.writer(text_stream)
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    text_stream.detach()
    stream.seek(0)
    return count


def _import_source(db, session_factory, user, workspace, dataset: Dataset, source: str, header):
    with tempfile.TemporaryFile() as stream:
        rows = _write_csv(stream, header, ROW_BUILDERS[source](dataset))
        started = time.perf_counter()
        batch, _ = create_or_get_batch(
            db,
            user=user,
            workspace=workspace,
            source_name=source,
            filename=f"{source}.csv",
            stream=stream,
            enforce_size_cap=False,
        )
        batch = process_batch(session_factory, batch.id, stream, max_rows=None, actor=user)
        elapsed = time.perf_counter() - started
    if batch.status != "completed" or batch.rows_failed or batch.rows_total != rows:
        raise BenchmarkFailure(
            f"import of {source} did not finish cleanly: status={batch.status}, "
            f"rows={rows}, rows_total={batch.rows_total}, rows_failed={batch.rows_failed}"
        )
    return {"source": source, "rows": rows, "seconds": elapsed}


def _reconcile(db, session_factory, user_id, workspace_id, dataset: Dataset) -> dict:
    started = time.perf_counter()
    run = run_reconciliation(session_factory, workspace_id=workspace_id, user_id=user_id)
    seconds = time.perf_counter() - started

    left = aliased(Transaction)
    right = aliased(Transaction)
    pairs = (
        select(
            MatchRow.rule,
            left.source_name,
            left.external_id,
            right.source_name,
            right.external_id,
        )
        .select_from(MatchRow)
        .join(left, MatchRow.left_transaction_id == left.id)
        .join(right, MatchRow.right_transaction_id == right.id)
        .where(MatchRow.reconciliation_run_id == run.id)
    )
    found = correct = 0
    for match in db.execute(pairs.execution_options(stream_results=True)):
        found += 1
        correct += _is_expected_match(dataset, *match)

    found_categories = dict(
        db.execute(
            select(ExceptionRow.category, func.count())
            .where(ExceptionRow.reconciliation_run_id == run.id)
            .group_by(ExceptionRow.category)
        ).all()
    )
    expected_categories = dataset.expected_exceptions
    categories = expected_categories.keys() | found_categories.keys()
    return {
        "seconds": seconds,
        "run_status": run.status,
        "matches": {
            "expected": dataset.expected_matches,
            "found": found,
            "correct": correct,
            "false": found - correct,
            "missed": dataset.expected_matches - correct,
        },
        "exceptions": {
            category: {
                "expected": expected_categories.get(category, 0),
                "found": found_categories.get(category, 0),
            }
            for category in sorted(categories)
        },
    }


def _accuracy(reconciliation: dict) -> float:
    matches = reconciliation["matches"]
    denominator = max(matches["expected"], matches["found"])
    if denominator == 0:
        return 100.0
    return 100.0 * matches["correct"] / denominator


def _peak_rss_mb() -> float | None:
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(peak / divisor, 1)


def _create_tenant(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    token = uuid.uuid4().hex
    with session_factory() as db, db.begin():
        org = Organization(name=f"Benchmark {token}")
        user = User(email=f"benchmark-{token}@example.com", password_hash="unused")
        db.add_all([org, user])
        db.flush()
        workspace = Workspace(organization_id=org.id, name=f"Benchmark {token}", created_by=user.id)
        db.add(workspace)
        db.flush()
        return user.id, workspace.id


def _delete_workspace_data(session_factory, workspace_id: uuid.UUID) -> None:
    run_ids = select(ReconciliationRun.id).where(ReconciliationRun.workspace_id == workspace_id)
    with session_factory() as db, db.begin():
        db.execute(delete(ExceptionRow).where(ExceptionRow.workspace_id == workspace_id))
        db.execute(delete(MatchRow).where(MatchRow.reconciliation_run_id.in_(run_ids)))
        db.execute(delete(ReconciliationRun).where(ReconciliationRun.workspace_id == workspace_id))
        db.execute(delete(Transaction).where(Transaction.workspace_id == workspace_id))
        db.execute(delete(ImportBatch).where(ImportBatch.workspace_id == workspace_id))
        db.execute(delete(Workspace).where(Workspace.id == workspace_id))


def _benchmark(session_factory, dataset: Dataset, user_id, workspace_id) -> dict:
    imports = []
    with session_factory() as db:
        user = db.get(User, user_id)
        workspace = db.get(Workspace, workspace_id)
        for source, header in SOURCES:
            imports.append(
                _import_source(db, session_factory, user, workspace, dataset, source, header)
            )
        reconciliation = _reconcile(db, session_factory, user_id, workspace_id, dataset)
        server_version = db.scalar(text("show server_version"))

    total_rows = sum(item["rows"] for item in imports)
    total_seconds = sum(item["seconds"] for item in imports)
    accuracy = _accuracy(reconciliation)
    matches = reconciliation["matches"]
    passed = (
        accuracy == 100.0
        and matches["found"] == matches["expected"]
        and all(item["expected"] == item["found"] for item in reconciliation["exceptions"].values())
    )
    return {
        "dataset": {
            "seed": dataset.seed,
            "orders": dataset.orders,
            "payments": dataset.payments,
            "settlements": dataset.settlements,
            "total_rows": dataset.orders + dataset.payments + dataset.settlements,
        },
        "environment": {
            "python": platform.python_version(),
            "postgresql": server_version,
            "os": platform.platform(),
            "cpus": os.cpu_count(),
        },
        "imports": [
            {**item, "rows_per_second": item["rows"] / item["seconds"]} for item in imports
        ],
        "import_total": {
            "rows": total_rows,
            "seconds": total_seconds,
            "rows_per_second": total_rows / total_seconds,
        },
        "reconciliation": {
            **reconciliation,
            "records_per_second": total_rows / reconciliation["seconds"],
        },
        "accuracy_percent": accuracy,
        "peak_rss_mb": _peak_rss_mb(),
        "passed": passed,
    }


def _format_report(report: dict) -> str:
    dataset = report["dataset"]
    environment = report["environment"]
    reconciliation = report["reconciliation"]
    matches = reconciliation["matches"]
    lines = [
        "Dataset",
        f"  orders          {dataset['orders']} rows",
        f"  payments        {dataset['payments']} rows",
        f"  settlements     {dataset['settlements']} rows",
        "Environment",
        f"  Python          {environment['python']}",
        f"  PostgreSQL      {environment['postgresql']}",
        f"  OS              {environment['os']}",
        f"  CPUs            {environment['cpus']}",
        "Import",
    ]
    for item in report["imports"]:
        lines.append(
            f"  {item['source']:<15} {item['rows']} rows in {item['seconds']:.2f} s, "
            f"{item['rows_per_second']:.0f} rows/s"
        )
    total = report["import_total"]
    lines.append(
        f"  {'total':<15} {total['rows']} rows in {total['seconds']:.2f} s, "
        f"{total['rows_per_second']:.0f} rows/s"
    )
    lines += [
        "Reconciliation",
        f"  duration        {reconciliation['seconds']:.2f} s",
        f"  records/s       {reconciliation['records_per_second']:.0f}",
        f"  matches         found {matches['found']}, expected {matches['expected']}, "
        f"false {matches['false']}, missed {matches['missed']}",
    ]
    for category, counts in reconciliation["exceptions"].items():
        lines.append(f"  {category:<15} found {counts['found']}, expected {counts['expected']}")
    if report["peak_rss_mb"] is not None:
        lines.append(f"Peak RSS          {report['peak_rss_mb']} MB")
    lines += [
        f"Match accuracy    {report['accuracy_percent']:.2f}%",
        f"Result            {'PASS' if report['passed'] else 'FAIL'}",
    ]
    return "\n".join(lines)


def _bounded_int(low: int, high: int):
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low:,} and {high:,}")
        return number

    return parse


def _match_ratio(value: str) -> float:
    ratio = float(value)
    if not 0 <= ratio <= MAX_MATCH_RATIO:
        raise argparse.ArgumentTypeError(f"must be between 0 and {MAX_MATCH_RATIO}")
    return ratio


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the import and reconciliation path against known results.",
        epilog="Run from backend/ with the migrations applied to DATABASE_URL.",
    )
    parser.add_argument(
        "--rows",
        type=_bounded_int(MIN_ROWS, MAX_ROWS),
        default=10_000,
        help="orders to generate; benchmark at 10,000 and 100,000 (default: 10,000)",
    )
    parser.add_argument(
        "--match-ratio",
        type=_match_ratio,
        default=0.8,
        help="share of orders with a matching payment, 0 to 0.9 (default: 0.8)",
    )
    parser.add_argument("--seed", type=int, default=1, help="generator seed (default: 1)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset = Dataset.build(args.rows, args.match_ratio, args.seed)
    session_factory = get_session_factory()
    user_id, workspace_id = _create_tenant(session_factory)
    try:
        report = _benchmark(session_factory, dataset, user_id, workspace_id)
    except BenchmarkFailure as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        _delete_workspace_data(session_factory, workspace_id)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
