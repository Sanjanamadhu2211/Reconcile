from __future__ import annotations

import pytest

from app.imports.mapping import (
    SOURCE_LAYOUTS,
    VALID_SOURCE_NAMES,
    HeaderError,
    get_layout,
    validate_headers,
)


class TestValidateHeaders:
    def test_orders_valid_headers(self):
        headers = ["order_id", "amount", "currency", "order_date", "customer_id"]
        layout = validate_headers(headers, "orders")
        assert layout.source_name == "orders"
        assert layout.transaction_type == "order"

    def test_orders_minimal_required_headers(self):
        headers = ["order_id", "amount", "currency", "order_date"]
        layout = validate_headers(headers, "orders")
        assert layout.source_name == "orders"

    def test_orders_missing_required(self):
        headers = ["order_id", "amount", "currency"]  # missing order_date
        with pytest.raises(HeaderError) as exc:
            validate_headers(headers, "orders")
        assert "order_date" in exc.value.missing

    def test_payments_valid_headers(self):
        headers = ["payment_id", "amount", "currency", "paid_at", "order_id"]
        layout = validate_headers(headers, "payments")
        assert layout.source_name == "payments"
        assert layout.transaction_type == "payment"

    def test_refunds_valid_headers(self):
        headers = ["refund_id", "amount", "currency", "refunded_at", "original_payment_id"]
        layout = validate_headers(headers, "refunds")
        assert layout.source_name == "refunds"
        assert layout.transaction_type == "refund"

    def test_settlements_valid_headers(self):
        headers = ["settlement_id", "amount", "currency", "settled_at", "batch_reference"]
        layout = validate_headers(headers, "settlements")
        assert layout.source_name == "settlements"
        assert layout.transaction_type == "settlement"

    def test_fees_valid_headers(self):
        headers = ["fee_id", "amount", "currency", "charged_at", "related_payment_id"]
        layout = validate_headers(headers, "fees")
        assert layout.source_name == "fees"
        assert layout.transaction_type == "fee"

    def test_unknown_source_raises_header_error(self):
        headers = ["order_id", "amount", "currency", "order_date"]
        with pytest.raises(HeaderError) as exc:
            validate_headers(headers, "unknown")
        assert any("UNKNOWN_TYPE" in m for m in exc.value.missing)

    def test_case_insensitive_header_matching(self):
        # Headers are stripped but case-sensitive per CSV
        headers = ["ORDER_ID", "AMOUNT", "CURRENCY", "ORDER_DATE"]
        with pytest.raises(HeaderError) as exc:
            validate_headers(headers, "orders")
        # The required headers are lowercase, so uppercase won't match
        assert "order_id" in exc.value.missing


class TestGetLayout:
    def test_all_valid_sources(self):
        for name in VALID_SOURCE_NAMES:
            layout = get_layout(name)
            assert layout.source_name == name

    def test_invalid_source_raises(self):
        with pytest.raises(HeaderError) as exc:
            get_layout("invalid")
        assert any("UNKNOWN_TYPE" in m for m in exc.value.missing)


class TestSourceLayouts:
    def test_orders_layout(self):
        layout = SOURCE_LAYOUTS["orders"]
        assert layout.external_id_column == "order_id"
        assert layout.amount_column == "amount"
        assert layout.currency_column == "currency"
        assert layout.timestamp_column == "order_date"
        assert layout.reference_column == "customer_id"
        assert layout.required_headers == frozenset(
            {"order_id", "amount", "currency", "order_date"}
        )

    def test_payments_layout(self):
        layout = SOURCE_LAYOUTS["payments"]
        assert layout.external_id_column == "payment_id"
        assert layout.required_headers == frozenset({"payment_id", "amount", "currency", "paid_at"})

    def test_refunds_layout(self):
        layout = SOURCE_LAYOUTS["refunds"]
        assert layout.external_id_column == "refund_id"
        assert layout.required_headers == frozenset(
            {"refund_id", "amount", "currency", "refunded_at"}
        )

    def test_settlements_layout(self):
        layout = SOURCE_LAYOUTS["settlements"]
        assert layout.external_id_column == "settlement_id"
        assert layout.required_headers == frozenset(
            {"settlement_id", "amount", "currency", "settled_at"}
        )

    def test_fees_layout(self):
        layout = SOURCE_LAYOUTS["fees"]
        assert layout.external_id_column == "fee_id"
        assert layout.required_headers == frozenset({"fee_id", "amount", "currency", "charged_at"})

    def test_transaction_types(self):
        assert SOURCE_LAYOUTS["orders"].transaction_type == "order"
        assert SOURCE_LAYOUTS["payments"].transaction_type == "payment"
        assert SOURCE_LAYOUTS["refunds"].transaction_type == "refund"
        assert SOURCE_LAYOUTS["settlements"].transaction_type == "settlement"
        assert SOURCE_LAYOUTS["fees"].transaction_type == "fee"
