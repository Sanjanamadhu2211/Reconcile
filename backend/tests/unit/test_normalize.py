from __future__ import annotations

from decimal import Decimal

import pytest

from app.imports.normalize import (
    ISO_4217_ALLOWLIST,
    RowError,
    normalize_external_id,
    parse_currency,
    parse_money,
    parse_timestamp,
)


class TestParseMoney:
    def test_valid_simple_decimal(self):
        assert parse_money("149.99") == Decimal("149.9900")

    def test_valid_with_comma_thousands(self):
        assert parse_money("1,234.56") == Decimal("1234.5600")

    def test_valid_with_underscore_thousands(self):
        assert parse_money("1_234.56") == Decimal("1234.5600")

    def test_valid_with_space_thousands(self):
        assert parse_money("1 234.56") == Decimal("1234.5600")

    def test_valid_negative_sign_ignored(self):
        assert parse_money("-149.99") == Decimal("149.9900")

    def test_valid_whitespace_trimmed(self):
        assert parse_money("  149.99  ") == Decimal("149.9900")

    def test_valid_four_decimal_places(self):
        assert parse_money("0.0001") == Decimal("0.0001")

    def test_valid_zero(self):
        assert parse_money("0") == Decimal("0.0000")

    def test_valid_integer(self):
        assert parse_money("100") == Decimal("100.0000")

    def test_reject_five_decimal_places(self):
        with pytest.raises(RowError) as exc:
            parse_money("0.00001")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_scientific_notation(self):
        with pytest.raises(RowError) as exc:
            parse_money("1e3")
        assert exc.value.code == "BAD_AMOUNT"

        with pytest.raises(RowError) as exc:
            parse_money("1E3")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_empty(self):
        with pytest.raises(RowError) as exc:
            parse_money("")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_whitespace_only(self):
        with pytest.raises(RowError) as exc:
            parse_money("   ")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_none(self):
        with pytest.raises(RowError) as exc:
            parse_money(None)  # type: ignore
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_multiple_decimal_points(self):
        with pytest.raises(RowError) as exc:
            parse_money("1.2.3")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_nan(self):
        with pytest.raises(RowError) as exc:
            parse_money("NaN")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_infinity(self):
        with pytest.raises(RowError) as exc:
            parse_money("Infinity")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_negative_infinity(self):
        with pytest.raises(RowError) as exc:
            parse_money("-Infinity")
        assert exc.value.code == "BAD_AMOUNT"

    def test_reject_garbage(self):
        with pytest.raises(RowError) as exc:
            parse_money("abc")
        assert exc.value.code == "BAD_AMOUNT"

    def test_large_number_accepted(self):
        # 19 digits max for NUMERIC(19,4)
        assert parse_money("999999999999999.9999") == Decimal("999999999999999.9999")


class TestParseCurrency:
    def test_valid_uppercase(self):
        assert parse_currency("USD") == "USD"

    def test_valid_lowercase_converted(self):
        assert parse_currency("usd") == "USD"

    def test_valid_mixed_case(self):
        assert parse_currency("UsD") == "USD"

    def test_valid_whitespace_trimmed(self):
        assert parse_currency("  EUR  ") == "EUR"

    def test_reject_unknown_code(self):
        with pytest.raises(RowError) as exc:
            parse_currency("XYZ")
        assert exc.value.code == "BAD_CURRENCY"

    def test_reject_empty(self):
        with pytest.raises(RowError) as exc:
            parse_currency("")
        assert exc.value.code == "BAD_CURRENCY"

    def test_reject_whitespace_only(self):
        with pytest.raises(RowError) as exc:
            parse_currency("   ")
        assert exc.value.code == "BAD_CURRENCY"

    def test_reject_none(self):
        with pytest.raises(RowError) as exc:
            parse_currency(None)  # type: ignore
        assert exc.value.code == "BAD_CURRENCY"

    def test_all_allowlist_codes_accepted(self):
        for code in ISO_4217_ALLOWLIST:
            assert parse_currency(code) == code
            assert parse_currency(code.lower()) == code


class TestParseTimestamp:
    def test_iso_with_z_suffix(self):
        dt = parse_timestamp("2024-01-15T10:30:00Z")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_iso_with_positive_offset(self):
        dt = parse_timestamp("2024-01-15T10:30:00+00:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0

    def test_iso_with_negative_offset(self):
        dt = parse_timestamp("2024-01-15T10:30:00-05:00")
        assert dt.tzinfo is not None
        # Should be converted to UTC
        assert dt.hour == 15  # 10:30 -05:00 = 15:30 UTC

    def test_iso_with_microseconds_and_z(self):
        dt = parse_timestamp("2024-01-15T10:30:00.123456Z")
        assert dt.tzinfo is not None
        assert dt.microsecond == 123456

    def test_naive_iso_treated_as_utc(self):
        dt = parse_timestamp("2024-01-15T10:30:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert dt.hour == 10

    def test_naive_space_separator_treated_as_utc(self):
        dt = parse_timestamp("2024-01-15 10:30:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert dt.hour == 10

    def test_naive_with_microseconds(self):
        dt = parse_timestamp("2024-01-15T10:30:00.123456")
        assert dt.tzinfo is not None
        assert dt.microsecond == 123456

    def test_date_only_treated_as_midnight_utc(self):
        dt = parse_timestamp("2024-01-15")
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0

    def test_reject_garbage(self):
        with pytest.raises(RowError) as exc:
            parse_timestamp("not-a-timestamp")
        assert exc.value.code == "BAD_TIMESTAMP"

    def test_reject_empty(self):
        with pytest.raises(RowError) as exc:
            parse_timestamp("")
        assert exc.value.code == "BAD_TIMESTAMP"

    def test_reject_whitespace_only(self):
        with pytest.raises(RowError) as exc:
            parse_timestamp("   ")
        assert exc.value.code == "BAD_TIMESTAMP"

    def test_reject_none(self):
        with pytest.raises(RowError) as exc:
            parse_timestamp(None)  # type: ignore
        assert exc.value.code == "BAD_TIMESTAMP"


class TestNormalizeExternalId:
    def test_trim_whitespace(self):
        assert normalize_external_id("  PAY-123  ") == "PAY-123"

    def test_case_sensitive_preserved(self):
        assert normalize_external_id("PAY-123") == "PAY-123"
        assert normalize_external_id("pay-123") == "pay-123"
        assert normalize_external_id("Pay-123") == "Pay-123"

    def test_reject_empty_after_trim(self):
        with pytest.raises(RowError) as exc:
            normalize_external_id("")
        assert exc.value.code == "MISSING_REQUIRED"

    def test_reject_whitespace_only(self):
        with pytest.raises(RowError) as exc:
            normalize_external_id("   ")
        assert exc.value.code == "MISSING_REQUIRED"

    def test_reject_none(self):
        with pytest.raises(RowError) as exc:
            normalize_external_id(None)  # type: ignore
        assert exc.value.code == "MISSING_REQUIRED"
