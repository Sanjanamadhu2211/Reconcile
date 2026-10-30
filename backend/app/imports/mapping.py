from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Mapping from CSV header to canonical field."""

    csv_header: str
    canonical_field: str
    required: bool


@dataclass(frozen=True, slots=True)
class SourceLayout:
    """Layout definition for a source CSV."""

    source_name: str
    transaction_type: str
    external_id_column: str
    amount_column: str
    currency_column: str
    timestamp_column: str
    reference_column: str | None
    columns: tuple[ColumnMapping, ...]
    required_headers: frozenset[str]


class HeaderError(Exception):
    """Raised when CSV headers don't match expected layout."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required headers: {', '.join(missing)}")


SOURCE_LAYOUTS: dict[str, SourceLayout] = {
    "orders": SourceLayout(
        source_name="orders",
        transaction_type="order",
        external_id_column="order_id",
        amount_column="amount",
        currency_column="currency",
        timestamp_column="order_date",
        reference_column="customer_id",
        columns=(
            ColumnMapping("order_id", "external_id", True),
            ColumnMapping("amount", "amount", True),
            ColumnMapping("currency", "currency", True),
            ColumnMapping("order_date", "occurred_at", True),
            ColumnMapping("customer_id", "reference", False),
            ColumnMapping("order_type", None, False),  # ignored
        ),
        required_headers=frozenset({"order_id", "amount", "currency", "order_date"}),
    ),
    "payments": SourceLayout(
        source_name="payments",
        transaction_type="payment",
        external_id_column="payment_id",
        amount_column="amount",
        currency_column="currency",
        timestamp_column="paid_at",
        reference_column="order_id",
        columns=(
            ColumnMapping("payment_id", "external_id", True),
            ColumnMapping("amount", "amount", True),
            ColumnMapping("currency", "currency", True),
            ColumnMapping("paid_at", "occurred_at", True),
            ColumnMapping("order_id", "reference", False),
            ColumnMapping("payment_method", None, False),  # ignored
        ),
        required_headers=frozenset({"payment_id", "amount", "currency", "paid_at"}),
    ),
    "refunds": SourceLayout(
        source_name="refunds",
        transaction_type="refund",
        external_id_column="refund_id",
        amount_column="amount",
        currency_column="currency",
        timestamp_column="refunded_at",
        reference_column="original_payment_id",
        columns=(
            ColumnMapping("refund_id", "external_id", True),
            ColumnMapping("amount", "amount", True),
            ColumnMapping("currency", "currency", True),
            ColumnMapping("refunded_at", "occurred_at", True),
            ColumnMapping("original_payment_id", "reference", False),
            ColumnMapping("reason", None, False),  # ignored
        ),
        required_headers=frozenset({"refund_id", "amount", "currency", "refunded_at"}),
    ),
    "settlements": SourceLayout(
        source_name="settlements",
        transaction_type="settlement",
        external_id_column="settlement_id",
        amount_column="amount",
        currency_column="currency",
        timestamp_column="settled_at",
        reference_column="batch_reference",
        columns=(
            ColumnMapping("settlement_id", "external_id", True),
            ColumnMapping("amount", "amount", True),
            ColumnMapping("currency", "currency", True),
            ColumnMapping("settled_at", "occurred_at", True),
            ColumnMapping("batch_reference", "reference", False),
            ColumnMapping("fee_amount", None, False),  # ignored
        ),
        required_headers=frozenset({"settlement_id", "amount", "currency", "settled_at"}),
    ),
    "fees": SourceLayout(
        source_name="fees",
        transaction_type="fee",
        external_id_column="fee_id",
        amount_column="amount",
        currency_column="currency",
        timestamp_column="charged_at",
        reference_column="related_payment_id",
        columns=(
            ColumnMapping("fee_id", "external_id", True),
            ColumnMapping("amount", "amount", True),
            ColumnMapping("currency", "currency", True),
            ColumnMapping("charged_at", "occurred_at", True),
            ColumnMapping("related_payment_id", "reference", False),
        ),
        required_headers=frozenset({"fee_id", "amount", "currency", "charged_at"}),
    ),
}

VALID_SOURCE_NAMES = frozenset(SOURCE_LAYOUTS.keys())


def get_layout(source_name: str) -> SourceLayout:
    """Get the source layout for a given source name.

    Raises HeaderError if source_name is not one of the known sources.
    """
    if source_name not in SOURCE_LAYOUTS:
        raise HeaderError([f"UNKNOWN_TYPE: {source_name}"])
    return SOURCE_LAYOUTS[source_name]


def validate_headers(headers: list[str], source_name: str) -> SourceLayout:
    """Validate CSV headers against the expected layout for a source.

    Returns the SourceLayout if valid, raises HeaderError listing missing required headers.
    """
    layout = get_layout(source_name)
    header_set = {h.strip() for h in headers}
    missing = [h for h in layout.required_headers if h not in header_set]
    if missing:
        raise HeaderError(missing)
    return layout
