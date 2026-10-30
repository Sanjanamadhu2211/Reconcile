from __future__ import annotations

import csv
from pathlib import Path

from app.imports.reader import read_rows

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "reconciliation"
EXPECTED_FILE = FIXTURES_DIR / "expected_import_rows.csv"
SOURCE_FILES = {
    "orders": "orders.csv",
    "payments": "payments.csv",
    "refunds": "refunds.csv",
    "settlements": "settlements.csv",
    "fees": "fees.csv",
    "unknown": "unknown.csv",
}


def load_expected():
    """Load expected results from golden CSV."""
    expected = []
    with EXPECTED_FILE.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            expected.append(
                (
                    row["source_file"],
                    int(row["row_number"]),
                    row["validation_status"],
                    row["error_code"] if row["error_code"] else None,
                )
            )
    return expected


def test_golden_import_rows():
    """Test that read_rows produces exactly the expected results for all fixture files."""
    expected = load_expected()
    actual = []

    for source_name, filename in SOURCE_FILES.items():
        source_file_key = filename  # expected uses "fees.csv" etc.
        filepath = FIXTURES_DIR / filename
        with filepath.open("rb") as f:
            results = list(read_rows(f, source_name, max_rows=50000))
        for r in results:
            actual.append(
                (
                    source_file_key,
                    r.row_number,
                    r.status,
                    r.error_code,
                )
            )

    # Expected is sorted by source_file, row_number
    actual.sort(key=lambda x: (x[0], x[1]))

    # Compare
    diff_gen = ((a, e) for a, e in zip(actual, expected, strict=False) if a != e)
    first_diff = next(diff_gen, "no diff at same length")
    assert actual == expected, (
        f"Mismatch: got {len(actual)} rows, expected {len(expected)}. First diff: {first_diff}"
    )


def test_golden_row_counts():
    """Quick sanity check on row counts per source."""
    expected = load_expected()
    from collections import Counter

    expected_counts = Counter(e[0] for e in expected)
    actual_counts = Counter()
    for source_name, filename in SOURCE_FILES.items():
        source_file_key = filename
        filepath = FIXTURES_DIR / filename
        with filepath.open("rb") as f:
            results = list(read_rows(f, source_name, max_rows=50000))
        actual_counts[source_file_key] = len(results)

    assert dict(actual_counts) == dict(expected_counts), (
        f"Row count mismatch: {dict(actual_counts)} != {dict(expected_counts)}"
    )
