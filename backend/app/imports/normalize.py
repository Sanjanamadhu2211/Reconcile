from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class RowError(Exception):
    code: str


ISO_4217_ALLOWLIST = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CAD",
        "AUD",
        "CHF",
        "CNY",
        "INR",
        "SGD",
        "HKD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "ILS",
        "MXN",
        "BRL",
        "ZAR",
        "KRW",
        "TRY",
        "THB",
        "MYR",
        "IDR",
        "PHP",
        "VND",
        "TWD",
        "AED",
        "SAR",
        "QAR",
        "KWD",
        "BHD",
        "OMR",
        "JOD",
        "EGP",
        "MAD",
        "KES",
        "NGN",
        "GHS",
        "TZS",
        "UGX",
        "XOF",
        "XAF",
        "XPF",
    }
)


def parse_money(text: str) -> Decimal:
    """Parse a monetary amount string into a Decimal.

    Accepted: optional leading sign (ignored), thousands separators (, _ space),
    decimal point only. Rejected: >4 decimal places, scientific notation,
    multiple decimal points, empty/whitespace, NaN, Infinity.
    """
    if text is None:
        raise RowError("BAD_AMOUNT")
    s = text.strip()
    if not s:
        raise RowError("BAD_AMOUNT")

    # Reject exponent forms early
    if any(c in s for c in "eE"):
        raise RowError("BAD_AMOUNT")

    # Remove thousands separators
    for sep in (",", "_", " "):
        s = s.replace(sep, "")

    # At this point we should have only digits, optional leading sign, optional single decimal point
    if s.count(".") > 1:
        raise RowError("BAD_AMOUNT")

    try:
        value = Decimal(s)
    except InvalidOperation as err:
        raise RowError("BAD_AMOUNT") from err

    # Reject NaN and Infinity
    if value.is_nan() or value.is_infinite():
        raise RowError("BAD_AMOUNT")

    # Take absolute value (sign is ignored per spec)
    value = value.copy_abs()

    # Check decimal places
    if value.as_tuple().exponent < -4:
        raise RowError("BAD_AMOUNT")

    # Quantize to 4 decimal places for storage consistency
    return value.quantize(Decimal("0.0001"))


def parse_currency(text: str) -> str:
    """Parse and validate a currency code."""
    if text is None:
        raise RowError("BAD_CURRENCY")
    code = text.strip().upper()
    if not code:
        raise RowError("BAD_CURRENCY")
    if code not in ISO_4217_ALLOWLIST:
        raise RowError("BAD_CURRENCY")
    return code


def parse_timestamp(text: str) -> datetime:
    """Parse a timestamp string into an aware UTC datetime.

    Accepted formats (in order):
    1. ISO 8601 with timezone: 2024-01-15T10:30:00Z, 2024-01-15T10:30:00+00:00,
       2024-01-15T10:30:00-05:00
    2. ISO 8601 naive (no timezone): 2024-01-15T10:30:00,
       2024-01-15 10:30:00 — treated as UTC
    3. Date only: 2024-01-15 — treated as 2024-01-15T00:00:00Z
    """
    if text is None:
        raise RowError("BAD_TIMESTAMP")
    s = text.strip()
    if not s:
        raise RowError("BAD_TIMESTAMP")

    # Try formats in order
    formats_with_tz = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
    ]
    for fmt in formats_with_tz:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.astimezone(UTC)
        except ValueError:
            pass

    # Naive formats (treated as UTC)
    formats_naive = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in formats_naive:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            pass

    # Date only
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.replace(tzinfo=UTC)
    except ValueError:
        pass

    raise RowError("BAD_TIMESTAMP")


def normalize_external_id(text: str) -> str:
    """Normalize an external ID: trim whitespace, case-sensitive."""
    if text is None:
        raise RowError("MISSING_REQUIRED")
    value = text.strip()
    if not value:
        raise RowError("MISSING_REQUIRED")
    return value
