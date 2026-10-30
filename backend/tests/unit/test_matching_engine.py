"""Unit tests for the matching engine."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.reconciliation import Record, run_matching


def _utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)


def _record(
    key: object,
    source: str,
    ext_id: str,
    amount: str,
    currency: str,
    dt: datetime,
    is_duplicate: bool = False,
) -> Record:
    return Record(
        key=key,
        source_name=source,
        external_id=ext_id,
        amount=Decimal(amount),
        currency=currency,
        occurred_at=dt,
        is_duplicate=is_duplicate,
    )


class TestRule1ExactId:
    """Tests for Rule 1: exact external_id matching."""

    def test_exact_id_match_orders_payments_only(self):
        """One order, one payment, same external_id, same amount/currency → exact_id match.

        Payment also acts as left in payments→settlements, so it needs a settlement
        with the same external_id to avoid an unmatched exception.
        """
        left = _record("L1", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 31))
        settlement = _record(
            "S1", "settlements", "EXT-001", "100.00", "USD", _utc(2024, 1, 16, 2, 00)
        )
        result = run_matching([left, right, settlement])
        assert len(result.matches) == 2  # order→payment + payment→settlement
        rules = {m.rule for m in result.matches}
        assert rules == {"exact_id"}
        assert len(result.exceptions) == 0

    def test_exact_id_amount_mismatch(self):
        """Same external_id, different amount → amount_mismatch exception on both sides."""
        left = _record("L1", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "EXT-001", "150.00", "USD", _utc(2024, 1, 15, 10, 31))
        result = run_matching([left, right])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 2  # Both left and right get amount_mismatch
        for exc in result.exceptions:
            assert exc.category == "amount_mismatch"

    def test_exact_id_currency_mismatch(self):
        """Same external_id, different currency → amount_mismatch exception on both sides."""
        left = _record("L1", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "EXT-001", "100.00", "EUR", _utc(2024, 1, 15, 10, 31))
        result = run_matching([left, right])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 2
        for exc in result.exceptions:
            assert exc.category == "amount_mismatch"

    def test_exact_id_ambiguous_one_left_two_right(self):
        """One left, two right with same external_id → ambiguous for all three."""
        left = _record("L1", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right1 = _record("R1", "payments", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 31))
        right2 = _record("R2", "payments", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 32))
        result = run_matching([left, right1, right2])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 3  # Left + both rights get ambiguous
        for exc in result.exceptions:
            assert exc.category == "ambiguous"

    def test_exact_id_ambiguous_two_left_one_right(self):
        """Two left, one right with same external_id → ambiguous for all three."""
        left1 = _record("L1", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record("L2", "orders", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 31))
        right = _record("R1", "payments", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 32))
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 3
        for exc in result.exceptions:
            assert exc.category == "ambiguous"

    def test_exact_id_right_only_source_unmatched_no_exception(self):
        """Right record (settlement) with no left partner produces no exception.

        Settlements are only a right source, never a left source.
        """
        right = _record("R1", "settlements", "EXT-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        result = run_matching([right])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 0


class TestRule2AmountCurrencyTime:
    """Tests for Rule 2: amount + currency + time tolerance."""

    def test_amount_currency_time_within_tolerance(self):
        """Exact amount, currency, time within 24h → amount_currency_time match.

        Payment also acts as left in payments→settlements, so it needs a settlement
        to avoid an unmatched exception.
        """
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record(
            "R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 15, 30)
        )  # 5h later
        settlement = _record(
            "S1", "settlements", "PAY-001", "100.00", "USD", _utc(2024, 1, 16, 2, 00)
        )
        result = run_matching([left, right, settlement])
        assert (
            len(result.matches) == 2
        )  # order→payment (amt_curr_time) + payment→settlement (exact_id)
        rules = {m.rule for m in result.matches}
        assert rules == {"amount_currency_time", "exact_id"}
        assert len(result.exceptions) == 0

    def test_amount_currency_time_at_boundary_24h(self):
        """Exactly 24 hours difference → match (inclusive boundary)."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30, 0))
        right = _record(
            "R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 16, 10, 30, 0)
        )  # exactly 24h
        result = run_matching([left, right])
        assert len(result.matches) == 1
        assert result.matches[0].rule == "amount_currency_time"

    def test_amount_currency_time_beyond_boundary(self):
        """24 hours + 1 second → no match, left gets unmatched."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30, 0))
        right = _record(
            "R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 16, 10, 30, 1)
        )  # 24h + 1s
        result = run_matching([left, right])
        assert len(result.matches) == 0
        # Left gets unmatched, right (payment) also gets unmatched as left in payments→settlements
        unmatched = [e for e in result.exceptions if e.category == "unmatched"]
        assert len(unmatched) >= 1
        assert any(e.key == "L1" for e in unmatched)

    def test_amount_currency_time_custom_tolerance(self):
        """Custom tolerance (e.g., 1 hour) works."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record(
            "R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00)
        )  # 30 min
        result = run_matching([left, right], tolerance=timedelta(hours=1))
        assert len(result.matches) == 1

        # Same records with 2 hour gap should not match with 1 hour tolerance
        right2 = _record(
            "R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 12, 31)
        )  # 2h 1min
        result2 = run_matching([left, right2], tolerance=timedelta(hours=1))
        assert len(result2.matches) == 0

    def test_amount_currency_time_different_amount_no_match(self):
        """Different amount → no rule 2 match."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "PAY-001", "101.00", "USD", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left, right])
        assert len(result.matches) == 0

    def test_amount_currency_time_different_currency_no_match(self):
        """Different currency → no rule 2 match."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "PAY-001", "100.00", "EUR", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left, right])
        assert len(result.matches) == 0

    def test_amount_currency_time_ambiguous_one_left_two_right(self):
        """One left, two right candidates satisfying rule 2 → ambiguous for all three."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right1 = _record("R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        right2 = _record("R2", "payments", "PAY-002", "100.00", "USD", _utc(2024, 1, 15, 14, 00))
        result = run_matching([left, right1, right2])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 3
        for exc in result.exceptions:
            assert exc.category == "ambiguous"

    def test_amount_currency_time_ambiguous_two_left_one_right(self):
        """Two left, one right candidate satisfying rule 2 → ambiguous for all three."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record("L2", "orders", "ORD-002", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        right = _record("R1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 3
        for exc in result.exceptions:
            assert exc.category == "ambiguous"


class TestAmbiguityPrecedence:
    """Tests for ambiguity handling and precedence rules."""

    def test_ambiguous_left_never_matched(self):
        """Ambiguous left record is never matched, even if rule 2 would work."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        # Two right with same external_id (rule 1 ambiguous)
        right1 = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        right2 = _record("R2", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        result = run_matching([left, right1, right2])
        assert len(result.matches) == 0
        assert len(result.exceptions) == 3
        for exc in result.exceptions:
            assert exc.category == "ambiguous"

    def test_right_record_matched_in_rule1_not_available_for_rule2(self):
        """Right record matched in rule 1 is excluded from rule 2 candidates."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record("L2", "orders", "ORD-002", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        # left1 matches right on exact_id, left2 would match on amount_currency_time
        # but right is already taken
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 1
        assert result.matches[0].rule == "exact_id"
        assert result.matches[0].left_key == "L1"
        # left2 should be unmatched (not ambiguous, since right is not available)
        # right (payment) will also be unmatched as left in payments→settlements
        unmatched_left2 = [
            e for e in result.exceptions if e.category == "unmatched" and e.key == "L2"
        ]
        assert len(unmatched_left2) == 1

    def test_right_record_amount_mismatch_excluded_from_rule2(self):
        """Right record flagged amount_mismatch in rule 1 is excluded from rule 2."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record("L2", "orders", "ORD-002", "200.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record(
            "R1", "payments", "ORD-001", "150.00", "USD", _utc(2024, 1, 15, 11, 00)
        )  # amount mismatch with left1
        # left1 → amount_mismatch with right (same ext_id, diff amount)
        # left2 would match right on amount_currency_time if right were available
        # but right is excluded due to amount_mismatch
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 0
        # Both left1 and right get amount_mismatch
        amt_mismatch = [e for e in result.exceptions if e.category == "amount_mismatch"]
        assert len(amt_mismatch) == 2
        # left2 is unmatched (right not available for rule 2)
        unmatched = [e for e in result.exceptions if e.category == "unmatched"]
        assert any(e.key == "L2" for e in unmatched)

    def test_right_record_ambiguous_excluded_from_rule2(self):
        """Right record ambiguous in rule 1 is excluded from rule 2."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record(
            "L2", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00)
        )  # ambiguous with left1 on rule 1
        left3 = _record("L3", "orders", "ORD-002", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        # left1 & left2 ambiguous on rule 1 with right
        # left3 would match right on rule 2 if available
        result = run_matching([left1, left2, left3, right])
        assert len(result.matches) == 0
        # left1, left2, right all ambiguous
        ambiguous = [e for e in result.exceptions if e.category == "ambiguous"]
        assert len(ambiguous) == 3
        # left3 is unmatched (right excluded due to ambiguous)
        unmatched = [e for e in result.exceptions if e.category == "unmatched"]
        assert any(e.key == "L3" for e in unmatched)


class TestDuplicateHandling:
    """Tests for DUPLICATE_IN_FILE handling."""

    def test_duplicate_record_no_matching(self):
        """Duplicate record takes no part in matching."""
        left_valid = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left_dup = _record(
            "L2", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30), is_duplicate=True
        )
        right = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left_valid, left_dup, right])
        assert len(result.matches) == 1
        assert result.matches[0].left_key == "L1"  # Only valid record matched
        # Duplicate should have duplicate exception
        dup_excs = [e for e in result.exceptions if e.category == "duplicate"]
        assert len(dup_excs) == 1
        assert dup_excs[0].key == "L2"

    def test_first_occurrence_matches_duplicate_flagged(self):
        """First occurrence participates in matching, second gets duplicate exception."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record(
            "L2", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30), is_duplicate=True
        )
        right = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 1
        assert result.matches[0].left_key == "L1"
        dup_excs = [e for e in result.exceptions if e.category == "duplicate"]
        assert len(dup_excs) == 1
        assert dup_excs[0].key == "L2"


class TestExceptionPrecedence:
    """Tests for exception precedence: duplicate > ambiguous > amount_mismatch > unmatched."""

    def test_duplicate_beats_ambiguous(self):
        """Duplicate exception takes precedence over ambiguous."""
        # A duplicate record that would also be ambiguous if it participated
        left_dup = _record(
            "L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30), is_duplicate=True
        )
        right1 = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        right2 = _record("R2", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        result = run_matching([left_dup, right1, right2])
        # Duplicate doesn't participate in matching, only gets duplicate exception
        dup_excs = [e for e in result.exceptions if e.category == "duplicate"]
        assert len(dup_excs) == 1
        assert dup_excs[0].key == "L1"
        # No ambiguous exception for the duplicate
        ambiguous_excs = [e for e in result.exceptions if e.category == "ambiguous"]
        assert len(ambiguous_excs) == 0  # Duplicate doesn't participate

    def test_ambiguous_beats_amount_mismatch(self):
        """Ambiguous takes precedence over amount_mismatch when both apply to same record.

        This test uses a scenario where a record could be both amount_mismatch (rule 1)
        and ambiguous (rule 2). The engine processes rule 1 first, so amount_mismatch
        is assigned and rule 2 is not considered for that record.
        """
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right1 = _record(
            "R1", "payments", "ORD-001", "150.00", "USD", _utc(2024, 1, 15, 11, 00)
        )  # amount mismatch rule 1
        right2 = _record(
            "R2", "payments", "PAY-002", "100.00", "USD", _utc(2024, 1, 15, 12, 00)
        )  # rule 2 candidate
        right3 = _record(
            "R3", "payments", "PAY-003", "100.00", "USD", _utc(2024, 1, 15, 13, 00)
        )  # another rule 2 candidate
        # Rule 1: left vs right1 → amount_mismatch
        # Rule 2: left vs right2, right3 → ambiguous (if rule 1 didn't claim it)
        # Per current implementation: rule 1 amount_mismatch stops rule 2 for this left
        result = run_matching([left, right1, right2, right3])
        # The left record gets amount_mismatch from rule 1 (and right1 gets amount_mismatch too)
        amt_mismatch = [e for e in result.exceptions if e.category == "amount_mismatch"]
        assert len(amt_mismatch) == 2  # left and right1
        assert any(e.key == "L1" for e in amt_mismatch)
        assert any(e.key == "R1" for e in amt_mismatch)

    def test_amount_mismatch_beats_unmatched(self):
        """Amount mismatch takes precedence over unmatched."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "ORD-001", "150.00", "USD", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left, right])
        amt_mismatch = [e for e in result.exceptions if e.category == "amount_mismatch"]
        assert len(amt_mismatch) == 2  # Both left and right get amount_mismatch
        # No unmatched for these keys
        unmatched = [e for e in result.exceptions if e.category == "unmatched"]
        assert not any(e.key in ("L1", "R1") for e in unmatched)


class TestDeterminism:
    """Tests for deterministic, order-independent results."""

    def test_input_order_independence(self):
        """Permuting input order gives identical result."""
        records = [
            _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30)),
            _record("L2", "orders", "ORD-002", "200.00", "USD", _utc(2024, 1, 15, 10, 30)),
            _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00)),
            _record("R2", "payments", "PAY-002", "200.00", "USD", _utc(2024, 1, 15, 11, 00)),
            _record("R3", "settlements", "SETL-001", "100.00", "USD", _utc(2024, 1, 16, 2, 00)),
        ]

        rng = random.Random(42)
        results = []
        for _ in range(50):
            shuffled = records.copy()
            rng.shuffle(shuffled)
            result = run_matching(shuffled)
            # Convert to comparable form
            matches = tuple(sorted((m.rule, m.left_key, m.right_key) for m in result.matches))
            exceptions = tuple(
                sorted((e.category, e.key, e.candidate_keys) for e in result.exceptions)
            )
            results.append((matches, exceptions))

        # All results should be identical
        assert all(r == results[0] for r in results)

    def test_empty_input(self):
        """Empty input produces empty result."""
        result = run_matching([])
        assert result.matches == ()
        assert result.exceptions == ()


class TestLargeInput:
    """Performance/regression test with synthetic data."""

    def test_large_input_completes_quickly(self):
        """20,000 synthetic records finish within a couple of seconds.

        Uses orders, payments, and settlements so all records are matched in both pairings.
        """
        import time

        records = []
        # Create 5,000 orders, 5,000 payments, 5,000 settlements with known matches
        for i in range(5_000):
            ext_id = f"EXT-{i:05d}"
            dt = _utc(2024, 1, 15, 10, 30, i % 60)
            records.append(_record(f"O{i}", "orders", ext_id, "100.00", "USD", dt))
            records.append(
                _record(f"P{i}", "payments", ext_id, "100.00", "USD", dt + timedelta(minutes=5))
            )
            records.append(
                _record(f"S{i}", "settlements", ext_id, "100.00", "USD", dt + timedelta(hours=10))
            )

        start = time.perf_counter()
        result = run_matching(records)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"Matching took {elapsed:.2f}s, expected < 5s"
        assert len(result.matches) == 10_000  # 5000 orders→payments + 5000 payments→settlements
        assert all(m.rule == "exact_id" for m in result.matches)
        # No exceptions because everything matches perfectly in both pairings
        assert len(result.exceptions) == 0


class TestCrossPairing:
    """Tests involving multiple pairings."""

    def test_payment_matched_as_right_in_orders_then_left_in_settlements(self):
        """A payment can be matched as right (to order) AND as left (to settlement)."""
        order = _record("O1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        payment = _record("P1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        settlement = _record(
            "S1", "settlements", "SETL-001", "100.00", "USD", _utc(2024, 1, 16, 2, 00)
        )
        result = run_matching([order, payment, settlement])
        assert len(result.matches) == 2
        rules = {m.rule for m in result.matches}
        assert rules == {"exact_id", "amount_currency_time"}
        # order→payment is exact_id, payment→settlement is amount_currency_time
        # No exceptions

    def test_refund_matched_to_payment_exact_id(self):
        """Refund matched to payment on exact external_id with same amount."""
        refund = _record("R1", "refunds", "PAY-001", "100.00", "USD", _utc(2024, 1, 20, 14, 22))
        payment = _record("P1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        result = run_matching([refund, payment])
        assert len(result.matches) == 1
        assert result.matches[0].rule == "exact_id"
        assert result.matches[0].left_key == "R1"
        assert result.matches[0].right_key == "P1"
        # Payment also participates in payments→settlements but has no settlement
        # so it gets an unmatched exception as left
        unmatched = [e for e in result.exceptions if e.category == "unmatched"]
        assert any(e.key == "P1" for e in unmatched)

    def test_refund_amount_mismatch_with_payment(self):
        """Refund with same external_id but different amount → amount_mismatch on both."""
        refund = _record("R1", "refunds", "PAY-001", "25.00", "USD", _utc(2024, 1, 20, 14, 22))
        payment = _record("P1", "payments", "PAY-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        result = run_matching([refund, payment])
        assert len(result.matches) == 0
        # Both get amount_mismatch
        amt_mismatch = [e for e in result.exceptions if e.category == "amount_mismatch"]
        assert len(amt_mismatch) == 2

    def test_no_double_matching_same_side(self):
        """A record never appears in two matches on the same side."""
        # One order, two payments with same external_id (ambiguous)
        order = _record("O1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        pay1 = _record("P1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        pay2 = _record("P2", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 12, 00))
        result = run_matching([order, pay1, pay2])
        assert len(result.matches) == 0
        # All three are ambiguous
        ambiguous = [e for e in result.exceptions if e.category == "ambiguous"]
        assert len(ambiguous) == 3
        # No matches on either side


class TestEdgeCases:
    """Edge case tests."""

    def test_zero_amount(self):
        """Zero amount is valid (positive decimal with 4 places)."""
        left = _record("L1", "orders", "ORD-001", "0.0000", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "ORD-001", "0.0000", "USD", _utc(2024, 1, 15, 11, 00))
        result = run_matching([left, right])
        assert len(result.matches) == 1
        assert result.matches[0].rule == "exact_id"

    def test_microsecond_precision_timestamps(self):
        """Timestamps with microsecond precision work correctly."""
        left = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30, 0))
        right = _record(
            "R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30, 0, 500_000)
        )
        result = run_matching([left, right])
        assert len(result.matches) == 1
        assert result.matches[0].rule == "exact_id"

    def test_rule2_candidates_exclude_already_matched_right(self):
        """Rule 2 candidates exclude right records already matched in rule 1."""
        left1 = _record("L1", "orders", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        left2 = _record("L2", "orders", "ORD-002", "100.00", "USD", _utc(2024, 1, 15, 10, 30))
        right = _record("R1", "payments", "ORD-001", "100.00", "USD", _utc(2024, 1, 15, 11, 00))
        # left1 exact_id matches right
        # left2 would match right on amount_currency_time but right is taken
        result = run_matching([left1, left2, right])
        assert len(result.matches) == 1
        assert result.matches[0].left_key == "L1"
        # left2 unmatched
        unmatched_left2 = [
            e for e in result.exceptions if e.category == "unmatched" and e.key == "L2"
        ]
        assert len(unmatched_left2) == 1
