#!/usr/bin/env python3
"""
Validate reconciliation golden fixtures.

Checks:
1. Every data row in input CSVs appears exactly once in expected_import_rows.csv
2. Every VALID row has exactly one terminal state per its role in pairings
3. No external_id is matched twice in the same role (left/right per pairing)
4. Every error code from data-model.md appears at least once
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict, Counter

FIXTURE_DIR = Path(__file__).parent

INPUT_FILES = [
    "orders.csv",
    "payments.csv",
    "refunds.csv",
    "settlements.csv",
    "fees.csv",
]

EXPECTED_IMPORT = "expected_import_rows.csv"
EXPECTED_MATCHES = "expected_matches.csv"
EXPECTED_EXCEPTIONS = "expected_exceptions.csv"

# Error codes from data-model.md §4
ERROR_CODES = {
    "MISSING_REQUIRED",
    "BAD_AMOUNT",
    "BAD_CURRENCY",
    "BAD_TIMESTAMP",
    "DUPLICATE_IN_FILE",
    "UNKNOWN_TYPE",
    "VALID",
}

# Pairings from data-model.md §5.1: (left_source, right_source)
PAIRINGS = [
    ("orders", "payments"),
    ("payments", "settlements"),
    ("refunds", "payments"),
]

# Left sources (get exceptions when unmatched)
LEFT_SOURCES = {"orders", "payments", "refunds"}

# Right sources (no exceptions when unmatched)
RIGHT_SOURCES = {"payments", "settlements"}

# Sources not matched in MVP (fees)
UNMATCHED_SOURCES = {"fees"}

# All sources
ALL_SOURCES = {"orders", "payments", "refunds", "settlements", "fees"}


def read_csv_rows(path):
    """Read CSV as list of rows, preserving all rows including invalid ones."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    return header, rows


def get_input_rows():
    """Return dict: (source_file, row_number) -> {source, external_id, row_data}"""
    result = {}
    for fname in INPUT_FILES:
        source = fname.replace(".csv", "")
        path = FIXTURE_DIR / fname
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)  # line 1
            for i, row in enumerate(reader, start=2):  # line numbers 1-based including header
                if not any(field.strip() for field in row):
                    # Blank line - skipped silently per data-model.md §3.5
                    continue
                external_id = row[0].strip() if row else ""
                result[(fname, i)] = {
                    "source": source,
                    "external_id": external_id,
                    "row_data": row,
                }
    return result


def load_expected_import_rows():
    """Return dict: (source_file, row_number) -> {validation_status, error_code}"""
    path = FIXTURE_DIR / EXPECTED_IMPORT
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["source_file"], int(row["row_number"]))
            result[key] = {
                "validation_status": row["validation_status"],
                "error_code": row["error_code"] if row["error_code"] else None,
            }
    return result


def load_expected_matches():
    """Return list of match dicts."""
    path = FIXTURE_DIR / EXPECTED_MATCHES
    matches = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            matches.append({
                "rule": row["rule"],
                "left_source": row["left_source"],
                "left_external_id": row["left_external_id"],
                "left_row_number": int(row["left_row_number"]),
                "right_source": row["right_source"],
                "right_external_id": row["right_external_id"],
                "right_row_number": int(row["right_row_number"]),
            })
    return matches


def load_expected_exceptions():
    """Return list of exception dicts."""
    path = FIXTURE_DIR / EXPECTED_EXCEPTIONS
    exceptions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exceptions.append({
                "category": row["category"],
                "source": row["source"],
                "external_id": row["external_id"],
                "row_number": int(row["row_number"]),
            })
    return exceptions


def check_import_rows_coverage(input_rows, expected_import):
    """Check 1: Every data row appears exactly once in expected_import_rows.csv"""
    errors = []
    input_keys = set(input_rows.keys())
    expected_keys = set(expected_import.keys())

    missing_in_expected = input_keys - expected_keys
    extra_in_expected = expected_keys - input_keys

    for key in sorted(missing_in_expected):
        errors.append(f"Row {key} in input but missing from {EXPECTED_IMPORT}")

    for key in sorted(extra_in_expected):
        errors.append(f"Row {key} in {EXPECTED_IMPORT} but not in any input file")

    return errors


def check_terminal_states(input_rows, expected_import, matches, exceptions):
    """Check 2: Every VALID row has correct terminal states per pairing role."""
    errors = []

    # Build match lookups per pairing role
    matched_as_left = defaultdict(set)   # (source, ext_id, row_num) -> set of pairings where matched as left
    matched_as_right = defaultdict(set)  # (source, ext_id, row_num) -> set of pairings where matched as right

    for m in matches:
        pairing = (m["left_source"], m["right_source"])
        left_key = (m["left_source"], m["left_external_id"], m["left_row_number"])
        right_key = (m["right_source"], m["right_external_id"], m["right_row_number"])
        matched_as_left[left_key].add(pairing)
        matched_as_right[right_key].add(pairing)

    # Build exception lookup
    excepted = set()  # (source, ext_id, row_num)
    for e in exceptions:
        excepted.add((e["source"], e["external_id"], e["row_number"]))

    # Check each VALID input row
    for (fname, row_num), info in input_rows.items():
        exp = expected_import.get((fname, row_num))
        if not exp:
            continue  # Already reported in check 1

        if exp["validation_status"] != "VALID":
            continue  # Invalid rows are terminal in import_rows with their error code

        source = info["source"]
        ext_id = info["external_id"]
        key = (source, ext_id, row_num)

        if source in LEFT_SOURCES:
            # Left source: must have exactly one terminal state in its pairing
            # Terminal state = matched as left in its pairing OR exception
            left_pairings = [p for p in PAIRINGS if p[0] == source]
            assert len(left_pairings) == 1, f"Source {source} should be left in exactly one pairing"
            pairing = left_pairings[0]

            matched_left = key in matched_as_left and pairing in matched_as_left[key]
            has_exception = key in excepted

            if matched_left and has_exception:
                errors.append(f"VALID row {fname}:{row_num} ({source}/{ext_id}) both matched as left and has exception")
            elif not matched_left and not has_exception:
                errors.append(f"VALID row {fname}:{row_num} ({source}/{ext_id}) has no terminal state (not matched as left, no exception)")

        elif source in UNMATCHED_SOURCES:
            # Fees: must have unmatched exception
            if key not in excepted:
                errors.append(f"VALID fee row {fname}:{row_num} ({source}/{ext_id}) missing unmatched exception")

        elif source in RIGHT_SOURCES:
            # Right source: can be matched as right (0 or 1 per pairing), no exceptions
            # No requirement for terminal state - unmatched right-side is OK
            # But verify not matched as right more than once per pairing
            for pairing in PAIRINGS:
                if pairing[1] == source:
                    if key in matched_as_right and pairing in matched_as_right[key]:
                        # Could check count but matches list already has unique entries
                        pass

    return errors


def check_no_double_matching(matches, exceptions):
    """Check 3: No row matched twice in same role per pairing."""
    errors = []

    # Check left side: each (source, ext_id, row_num) matched as left at most once per pairing
    left_counts = Counter()
    right_counts = Counter()

    for m in matches:
        pairing = (m["left_source"], m["right_source"])
        left_key = (m["left_source"], m["left_external_id"], m["left_row_number"], pairing)
        right_key = (m["right_source"], m["right_external_id"], m["right_row_number"], pairing)
        left_counts[left_key] += 1
        right_counts[right_key] += 1

    for key, count in left_counts.items():
        if count > 1:
            errors.append(f"Left side matched multiple times in same pairing: {key} (count={count})")

    for key, count in right_counts.items():
        if count > 1:
            errors.append(f"Right side matched multiple times in same pairing: {key} (count={count})")

    # Check: no row both matched as left and has exception
    matched_left_keys = set((m["left_source"], m["left_external_id"], m["left_row_number"]) for m in matches)
    for e in exceptions:
        exc_key = (e["source"], e["external_id"], e["row_number"])
        if exc_key in matched_left_keys:
            errors.append(f"Row {exc_key} both matched as left and has exception")

    return errors


def check_error_codes_covered(expected_import):
    """Check 4: Every error code from data-model.md appears at least once."""
    errors = []
    seen_codes = set()
    for exp in expected_import.values():
        if exp["error_code"]:
            seen_codes.add(exp["error_code"])
        if exp["validation_status"] == "VALID":
            seen_codes.add("VALID")

    missing = ERROR_CODES - seen_codes
    for code in sorted(missing):
        errors.append(f"Error code {code} from data-model.md not present in {EXPECTED_IMPORT}")

    return errors


def check_match_consistency(matches, expected_import):
    """Check that matched rows are VALID in expected_import."""
    errors = []
    for m in matches:
        left_key = (m["left_source"] + ".csv", m["left_row_number"])
        right_key = (m["right_source"] + ".csv", m["right_row_number"])

        for key, side in [(left_key, "left"), (right_key, "right")]:
            exp = expected_import.get(key)
            if not exp:
                errors.append(f"Match references missing row in {EXPECTED_IMPORT}: {key} ({side})")
            elif exp["validation_status"] != "VALID":
                errors.append(f"Match references non-VALID row: {key} ({side}) status={exp['validation_status']}")

    return errors


def check_exception_consistency(exceptions, expected_import):
    """Check that excepted rows exist in expected_import."""
    errors = []
    for e in exceptions:
        key = (e["source"] + ".csv", e["row_number"])
        exp = expected_import.get(key)
        if not exp:
            errors.append(f"Exception references missing row in {EXPECTED_IMPORT}: {key}")
        # Exception rows can be VALID (unmatched, ambiguous, amount_mismatch) or DUPLICATE_IN_FILE
        # Both are valid terminal states for left sources

    return errors


def main():
    all_errors = []

    print("Loading fixtures...")
    input_rows = get_input_rows()
    expected_import = load_expected_import_rows()
    matches = load_expected_matches()
    exceptions = load_expected_exceptions()

    print(f"  Input rows: {len(input_rows)}")
    print(f"  Expected import rows: {len(expected_import)}")
    print(f"  Expected matches: {len(matches)}")
    print(f"  Expected exceptions: {len(exceptions)}")

    print("\nRunning checks...")

    all_errors.extend(check_import_rows_coverage(input_rows, expected_import))
    print(f"  Check 1 (coverage): {'OK' if not all_errors else 'FAIL'}")

    all_errors.extend(check_terminal_states(input_rows, expected_import, matches, exceptions))
    print(f"  Check 2 (terminal states): {'OK' if not any(e for e in all_errors if 'terminal state' in e or 'both matched' in e or 'missing unmatched' in e) else 'FAIL'}")

    all_errors.extend(check_no_double_matching(matches, exceptions))
    print(f"  Check 3 (no double matching): {'OK' if not any(e for e in all_errors if 'matched multiple times' in e or 'both matched as left' in e) else 'FAIL'}")

    all_errors.extend(check_error_codes_covered(expected_import))
    print(f"  Check 4 (error codes covered): {'OK' if not any(e for e in all_errors if 'not present' in e) else 'FAIL'}")

    all_errors.extend(check_match_consistency(matches, expected_import))
    print(f"  Check 5 (match consistency): {'OK' if not any(e for e in all_errors if 'Match references' in e) else 'FAIL'}")

    all_errors.extend(check_exception_consistency(exceptions, expected_import))
    print(f"  Check 6 (exception consistency): {'OK' if not any(e for e in all_errors if 'Exception references' in e) else 'FAIL'}")

    if all_errors:
        print("\n=== FIXTURE VALIDATION FAILED ===")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("\n=== fixtures ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())