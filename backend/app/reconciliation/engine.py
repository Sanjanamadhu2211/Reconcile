from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Record:
    """A normalized transaction record ready for matching."""

    key: object
    source_name: str
    external_id: str
    amount: Decimal
    currency: str
    occurred_at: datetime
    is_duplicate: bool = False


@dataclass(frozen=True, slots=True)
class Match:
    """A confirmed match between two records."""

    rule: str
    left_key: object
    right_key: object


@dataclass(frozen=True, slots=True)
class ExceptionItem:
    """A record that could not be cleanly matched."""

    category: str
    key: object
    candidate_keys: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchingResult:
    """Complete outcome of a matching run."""

    matches: tuple[Match, ...]
    exceptions: tuple[ExceptionItem, ...]


_PAIRINGS = (
    ("orders", "payments"),
    ("payments", "settlements"),
    ("refunds", "payments"),
)

_UNMATCHED_SOURCES = {"fees"}

# Precedence for exception categories (highest first)
_EXCEPTION_PRECEDENCE = {
    "duplicate": 4,
    "ambiguous": 3,
    "amount_mismatch": 2,
    "unmatched": 1,
}


def _stable_key(record: Record) -> tuple:
    """Sort key that makes results independent of input order."""
    return (
        record.source_name,
        record.external_id,
        record.amount,
        record.currency,
        record.occurred_at.isoformat(),
        str(record.key),
    )


def _within_tolerance(left: datetime, right: datetime, tolerance: timedelta) -> bool:
    """Check if two timestamps are within tolerance (inclusive boundary)."""
    return abs(left - right) <= tolerance


def _group_by_external_id(records: list[Record]) -> dict[str, list[Record]]:
    """Group records by external_id."""
    groups = defaultdict(list)
    for r in records:
        groups[r.external_id].append(r)
    return groups


def _group_by_amount_currency(records: list[Record]) -> dict[tuple[Decimal, str], list[Record]]:
    """Group records by (amount, currency) for rule 2."""
    groups = defaultdict(list)
    for r in records:
        groups[(r.amount, r.currency)].append(r)
    return groups


def _match_pairing(
    left_records: list[Record],
    right_records: list[Record],
    tolerance: timedelta,
) -> tuple[list[Match], dict[object, list[ExceptionItem]], dict[object, list[ExceptionItem]]]:
    """
    Match one left/right source pairing.

    Returns:
        - list of Match objects
        - dict mapping left record key -> list of ExceptionItem
        - dict mapping right record key -> list of ExceptionItem
    """
    matches: list[Match] = []
    left_exceptions: dict[object, list[ExceptionItem]] = defaultdict(list)
    right_exceptions: dict[object, list[ExceptionItem]] = defaultdict(list)

    # Track right-side state
    right_matched = set()
    right_ambiguous = set()
    right_amount_mismatch = set()

    # Skip duplicate records entirely
    left_nondup = [r for r in left_records if not r.is_duplicate]
    right_nondup = [r for r in right_records if not r.is_duplicate]

    # rule 1: exact external_id
    left_by_ext_id = _group_by_external_id(left_nondup)
    right_by_ext_id = _group_by_external_id(right_nondup)

    all_ext_ids = set(left_by_ext_id.keys()) | set(right_by_ext_id.keys())

    for ext_id in sorted(all_ext_ids):
        left_group = left_by_ext_id.get(ext_id, [])
        right_group = right_by_ext_id.get(ext_id, [])

        if not left_group or not right_group:
            # No candidates on one side - these will be handled by rule 2 or unmatched
            continue

        # Check for ambiguity: multiple on either side
        if len(left_group) > 1 or len(right_group) > 1:
            # Ambiguous for all involved
            left_candidate_keys = tuple(r.key for r in right_group)
            right_candidate_keys = tuple(r.key for r in left_group)
            for left in left_group:
                left_exceptions[left.key].append(
                    ExceptionItem("ambiguous", left.key, left_candidate_keys)
                )
            for right in right_group:
                right_exceptions[right.key].append(
                    ExceptionItem("ambiguous", right.key, right_candidate_keys)
                )
                right_ambiguous.add(right.key)
            continue

        # Exactly one left, one right
        left = left_group[0]
        right = right_group[0]

        # Check amount and currency
        if right.amount == left.amount and right.currency == left.currency:
            # Exact match
            matches.append(Match("exact_id", left.key, right.key))
            right_matched.add(right.key)
        else:
            # Same external_id but different amount/currency → amount_mismatch
            left_exceptions[left.key].append(
                ExceptionItem("amount_mismatch", left.key, (right.key,))
            )
            right_exceptions[right.key].append(
                ExceptionItem("amount_mismatch", right.key, (left.key,))
            )
            right_amount_mismatch.add(right.key)

    # rule 2: amount, currency and time tolerance
    # Consider only left records not yet matched/ambiguous/amount_mismatch
    # and right records not yet matched/ambiguous/amount_mismatch
    rule1_matched = {m.left_key for m in matches}
    left_unmatched = [
        r for r in left_nondup if r.key not in rule1_matched and r.key not in left_exceptions
    ]
    right_available = {
        r.key: r
        for r in right_nondup
        if r.key not in right_matched
        and r.key not in right_ambiguous
        and r.key not in right_amount_mismatch
    }

    if not left_unmatched or not right_available:
        # No candidates for rule 2
        for left in left_unmatched:
            left_exceptions[left.key].append(ExceptionItem("unmatched", left.key))
        return matches, left_exceptions, right_exceptions

    # Group by (amount, currency)
    left_by_amt_cur = _group_by_amount_currency(left_unmatched)
    right_by_amt_cur = _group_by_amount_currency(list(right_available.values()))

    all_amt_cur = set(left_by_amt_cur.keys()) | set(right_by_amt_cur.keys())

    for amt_cur in sorted(all_amt_cur):
        left_group = left_by_amt_cur.get(amt_cur, [])
        right_group = right_by_amt_cur.get(amt_cur, [])

        if not left_group or not right_group:
            continue

        # Build bipartite graph: left -> list of right within tolerance
        left_to_right: dict[object, list[object]] = defaultdict(list)
        right_to_left: dict[object, list[object]] = defaultdict(list)

        for left in left_group:
            for right in right_group:
                if _within_tolerance(left.occurred_at, right.occurred_at, tolerance):
                    left_to_right[left.key].append(right.key)
                    right_to_left[right.key].append(left.key)

        if not left_to_right:
            # No pairs within tolerance
            for left in left_group:
                left_exceptions[left.key].append(ExceptionItem("unmatched", left.key))
            continue

        # Find connected components in the bipartite graph
        # A component is ambiguous if any node has degree > 1
        visited_left = set()
        visited_right = set()

        for left in left_group:
            if left.key in visited_left:
                continue
            if left.key not in left_to_right:
                # No edges for this left
                left_exceptions[left.key].append(ExceptionItem("unmatched", left.key))
                visited_left.add(left.key)
                continue

            # BFS to find component
            component_left = set()
            component_right = set()
            queue = [("left", left.key)]

            while queue:
                side, key = queue.pop(0)
                if side == "left":
                    if key in visited_left:
                        continue
                    visited_left.add(key)
                    component_left.add(key)
                    for rkey in left_to_right.get(key, []):
                        if rkey not in visited_right:
                            queue.append(("right", rkey))
                else:
                    if key in visited_right:
                        continue
                    visited_right.add(key)
                    component_right.add(key)
                    for lkey in right_to_left.get(key, []):
                        if lkey not in visited_left:
                            queue.append(("left", lkey))

            # Check if component is ambiguous
            is_ambiguous = any(len(left_to_right.get(lk, [])) > 1 for lk in component_left)
            is_ambiguous = is_ambiguous or any(
                len(right_to_left.get(rk, [])) > 1 for rk in component_right
            )

            if is_ambiguous:
                # All records in component are ambiguous
                left_candidate_keys = tuple(sorted(component_right))
                right_candidate_keys = tuple(sorted(component_left))
                for lkey in component_left:
                    left_exceptions[lkey].append(
                        ExceptionItem("ambiguous", lkey, left_candidate_keys)
                    )
                for rkey in component_right:
                    right_exceptions[rkey].append(
                        ExceptionItem("ambiguous", rkey, right_candidate_keys)
                    )
                    right_ambiguous.add(rkey)
            else:
                # Each left has exactly one right and vice versa - perfect matching
                for lkey in component_left:
                    rkey = left_to_right[lkey][0]
                    matches.append(Match("amount_currency_time", lkey, rkey))
                    right_matched.add(rkey)

    # Any left records not processed (no right candidates at all for their amt_cur)
    matched_left = {m.left_key for m in matches}
    for left in left_unmatched:
        if left.key not in matched_left and left.key not in left_exceptions:
            left_exceptions[left.key].append(ExceptionItem("unmatched", left.key))

    return matches, left_exceptions, right_exceptions


def run_matching(
    records: Iterable[Record],
    tolerance: timedelta = timedelta(hours=24),
) -> MatchingResult:
    """
    Run the deterministic matching engine.

    Args:
        records: All records from all sources (orders, payments, refunds, settlements, fees).
        tolerance: Timestamp tolerance for rule 2 (default 24 hours, inclusive boundary).

    Returns:
        MatchingResult with matches and exceptions.
    """
    # Materialize and sort for determinism
    all_records = sorted(records, key=_stable_key)

    # Partition by source
    by_source: dict[str, list[Record]] = defaultdict(list)
    for r in all_records:
        by_source[r.source_name].append(r)

    all_matches: list[Match] = []
    all_exceptions: dict[object, list[ExceptionItem]] = defaultdict(list)

    # Process each pairing in order
    for left_src, right_src in _PAIRINGS:
        left_records = by_source.get(left_src, [])
        right_records = by_source.get(right_src, [])

        matches, left_excs, right_excs = _match_pairing(left_records, right_records, tolerance)
        all_matches.extend(matches)

        # Merge exceptions for left records
        for key, excs in left_excs.items():
            all_exceptions[key].extend(excs)
        # Merge exceptions for right records (ambiguous, amount_mismatch only - not unmatched)
        for key, excs in right_excs.items():
            all_exceptions[key].extend(excs)

    # Add exceptions for unmatched sources (fees) - these only get unmatched
    for src in _UNMATCHED_SOURCES:
        for record in by_source.get(src, []):
            if record.is_duplicate:
                continue
            all_exceptions[record.key].append(ExceptionItem("unmatched", record.key))

    # Add duplicate exceptions for all sources
    for record in all_records:
        if record.is_duplicate:
            all_exceptions[record.key].append(ExceptionItem("duplicate", record.key))

    # Resolve precedence: each record keeps only its highest-precedence exception
    final_exceptions: list[ExceptionItem] = []
    for _key, excs in all_exceptions.items():
        if not excs:
            continue
        best = max(excs, key=lambda e: _EXCEPTION_PRECEDENCE.get(e.category, 0))
        final_exceptions.append(best)

    # Sort results for determinism
    all_matches.sort(key=lambda m: (m.rule, str(m.left_key), str(m.right_key)))
    final_exceptions.sort(key=lambda e: (e.category, str(e.key)))

    return MatchingResult(tuple(all_matches), tuple(final_exceptions))


__all__ = [
    "Record",
    "Match",
    "ExceptionItem",
    "MatchingResult",
    "run_matching",
]
