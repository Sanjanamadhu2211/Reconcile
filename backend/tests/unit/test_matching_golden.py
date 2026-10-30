"""Golden fixture tests for the matching engine.

Reads the fixture CSVs using the real import reader, builds Records,
runs run_matching, and asserts exact equality with expected_matches.csv
and expected_exceptions.csv.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.imports.reader import read_rows
from app.reconciliation import Record, run_matching

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "reconciliation"

SOURCE_FILES = [
    ("orders", "orders.csv"),
    ("payments", "payments.csv"),
    ("refunds", "refunds.csv"),
    ("settlements", "settlements.csv"),
    ("fees", "fees.csv"),
    ("unknown", "unknown.csv"),
]

MAX_ROWS = 100_000


def _parse_datetime(s: str) -> datetime:
    """Parse ISO datetime string (with Z or +00:00) to aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(UTC)


def _load_expected_matches() -> set[tuple]:
    """Load expected_matches.csv as a set of tuples for comparison."""
    path = FIXTURE_DIR / "expected_matches.csv"
    result = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result.add(
                (
                    row["rule"],
                    row["left_source"],
                    row["left_external_id"],
                    int(row["left_row_number"]),
                    row["right_source"],
                    row["right_external_id"],
                    int(row["right_row_number"]),
                )
            )
    return result


def _load_expected_exceptions() -> set[tuple]:
    """Load expected_exceptions.csv as a set of tuples for comparison."""
    path = FIXTURE_DIR / "expected_exceptions.csv"
    result = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result.add(
                (
                    row["category"],
                    row["source"],
                    row["external_id"],
                    int(row["row_number"]),
                )
            )
    return result


def _iter_valid_records() -> Iterator[Record]:
    """Yield Record objects for all VALID rows across all source files."""
    for source_name, filename in SOURCE_FILES:
        path = FIXTURE_DIR / filename
        with open(path, "rb") as f:
            for row_result in read_rows(f, source_name, max_rows=MAX_ROWS):
                if row_result.status == "VALID":
                    v = row_result.values
                    yield Record(
                        key=(source_name, row_result.row_number),
                        source_name=v["source_name"],
                        external_id=v["external_id"],
                        amount=Decimal(v["amount"]),
                        currency=v["currency"],
                        occurred_at=_parse_datetime(v["occurred_at"]),
                        is_duplicate=False,
                    )
                elif row_result.status == "DUPLICATE_IN_FILE":
                    # For duplicates, we still need the external_id to create the record
                    # Parse the raw row to get the external_id
                    # The reader doesn't give us values for duplicates, so we read the CSV directly
                    pass


def _iter_duplicate_records() -> Iterator[Record]:
    """Yield Record objects for all DUPLICATE_IN_FILE rows."""
    for source_name, filename in SOURCE_FILES:
        path = FIXTURE_DIR / filename
        with open(path, "rb") as f:
            for row_result in read_rows(f, source_name, max_rows=MAX_ROWS):
                if row_result.status == "DUPLICATE_IN_FILE":
                    # Re-read the CSV to get the raw values for this row
                    # We know the row_number (1-based including header)
                    with open(path, newline="", encoding="utf-8") as f2:
                        reader = csv.reader(f2)
                        next(reader)
                        # row_result.row_number is 1-based file line number
                        # header is line 1, so data row N is at line N
                        for i, row in enumerate(reader, start=2):
                            if i == row_result.row_number:
                                # Extract external_id from first column
                                external_id = row[0].strip() if row else ""
                                # We still need amount, currency, occurred_at for the Record
                                # But the doc says DUPLICATE_IN_FILE rows take no part in matching
                                # They only produce a duplicate exception
                                # So we can use dummy values for the other fields
                                yield Record(
                                    key=(source_name, row_result.row_number),
                                    source_name=source_name,
                                    external_id=external_id,
                                    amount=Decimal("0"),
                                    currency="USD",
                                    occurred_at=datetime.now(UTC),
                                    is_duplicate=True,
                                )
                                break


def _build_all_records() -> list[Record]:
    """Build complete list of records including VALID and DUPLICATE_IN_FILE."""
    records = list(_iter_valid_records())
    records.extend(_iter_duplicate_records())
    return records


class TestGoldenFixtures:
    """Golden fixture tests - must match expected output exactly."""

    def test_matches_match_golden(self):
        """Matches produced by engine equal expected_matches.csv exactly."""
        records = _build_all_records()
        result = run_matching(records)

        # Build comparable tuples from result
        actual_matches = set()
        for m in result.matches:
            # We need to map keys back to source and row_number
            left_src, left_row = m.left_key
            right_src, right_row = m.right_key
            # Get external_ids by finding the record
            left_ext_id = next(r.external_id for r in records if r.key == m.left_key)
            right_ext_id = next(r.external_id for r in records if r.key == m.right_key)
            actual_matches.add(
                (
                    m.rule,
                    left_src,
                    left_ext_id,
                    left_row,
                    right_src,
                    right_ext_id,
                    right_row,
                )
            )

        expected_matches = _load_expected_matches()
        assert actual_matches == expected_matches, (
            f"Matches differ.\n"
            f"Expected only: {sorted(expected_matches - actual_matches)}\n"
            f"Actual only: {sorted(actual_matches - expected_matches)}"
        )

    def test_exceptions_match_golden(self):
        """Exceptions produced by engine equal expected_exceptions.csv exactly."""
        records = _build_all_records()
        result = run_matching(records)

        # Build comparable tuples from result
        actual_exceptions = set()
        for e in result.exceptions:
            src, row = e.key
            ext_id = next(r.external_id for r in records if r.key == e.key)
            actual_exceptions.add(
                (
                    e.category,
                    src,
                    ext_id,
                    row,
                )
            )

        expected_exceptions = _load_expected_exceptions()
        assert actual_exceptions == expected_exceptions, (
            f"Exceptions differ.\n"
            f"Expected only: {sorted(expected_exceptions - actual_exceptions)}\n"
            f"Actual only: {sorted(actual_exceptions - expected_exceptions)}"
        )
