from __future__ import annotations

import io

import pytest

from app.imports.reader import ImportFileError, RowResult, read_rows


class TestReadRows:
    def test_orders_valid_rows(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,2024-01-15T10:30:00Z,CUST-001
ORD-002,200.50,EUR,2024-01-15T10:30:00Z,CUST-002
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 2
        assert all(r.status == "VALID" for r in results)
        assert results[0].row_number == 2
        assert results[1].row_number == 3
        assert results[0].values["external_id"] == "ORD-001"
        assert results[0].values["amount"] == "100.0000"
        assert results[0].values["currency"] == "USD"

    def test_blank_lines_skipped_not_counted(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,2024-01-15T10:30:00Z,CUST-001

ORD-002,200.00,USD,2024-01-15T10:30:00Z,CUST-002
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 2
        # Row numbers should be 2 and 4 (blank line at line 3 is skipped)
        assert results[0].row_number == 2
        assert results[1].row_number == 4

    def test_bom_handled(self):
        csv_content = (
            b"\xef\xbb\xbforder_id,amount,currency,order_date,customer_id\n"
            b"ORD-001,100.00,USD,2024-01-15T10:30:00Z,CUST-001\n"
        )
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"

    def test_bad_encoding_raises(self):
        # Invalid UTF-8 sequence
        csv_content = (
            b"order_id,amount,currency,order_date,customer_id\n"
            b"ORD-001,100.00,USD,2024-01-15T10:30:00Z,CUST-001\n"
        )
        # Corrupt it
        csv_content = csv_content[:-1] + b"\xff"
        stream = io.BytesIO(csv_content)
        with pytest.raises(ImportFileError) as exc:
            list(read_rows(stream, "orders", max_rows=1000))
        assert "ENCODING_ERROR" in str(exc.value)

    def test_missing_required_field(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,,USD,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "MISSING_REQUIRED"
        assert results[0].error_code == "MISSING_REQUIRED"

    def test_bad_amount_too_many_decimals(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,999.99999,USD,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "BAD_AMOUNT"
        assert results[0].error_code == "BAD_AMOUNT"

    def test_bad_currency_unknown(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,XYZ,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "BAD_CURRENCY"
        assert results[0].error_code == "BAD_CURRENCY"

    def test_bad_timestamp(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,not-a-timestamp,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "BAD_TIMESTAMP"
        assert results[0].error_code == "BAD_TIMESTAMP"

    def test_duplicate_in_file(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,2024-01-15T10:30:00Z,CUST-001
ORD-001,200.00,USD,2024-01-15T10:30:00Z,CUST-002
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 2
        assert results[0].status == "VALID"
        assert results[1].status == "DUPLICATE_IN_FILE"
        assert results[1].error_code == "DUPLICATE_IN_FILE"

    def test_too_many_rows(self):
        csv_content = b"order_id,amount,currency,order_date,customer_id\n"
        for i in range(5):
            csv_content += f"ORD-{i:03d},100.00,USD,2024-01-15T10:30:00Z,CUST-{i:03d}\n".encode()
        stream = io.BytesIO(csv_content)
        with pytest.raises(ImportFileError) as exc:
            list(read_rows(stream, "orders", max_rows=3))
        assert "too many rows" in str(exc.value)

    def test_unknown_source_type(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-UNK,100.00,USD,2024-01-15T10:30:00Z,CUST-UNK
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "unknown", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "UNKNOWN_TYPE"
        assert results[0].error_code == "UNKNOWN_TYPE"

    def test_thousands_separator_comma(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,"1,234.56",USD,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"
        assert results[0].values["amount"] == "1234.5600"

    def test_negative_amount_absolute_value(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,-149.99,USD,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"
        assert results[0].values["amount"] == "149.9900"

    def test_currency_lowercase_accepted(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,usd,2024-01-15T10:30:00Z,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"
        assert results[0].values["currency"] == "USD"

    def test_naive_timestamp_treated_as_utc(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,2024-01-15T10:30:00,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"
        assert results[0].values["occurred_at"].endswith("Z")

    def test_date_only_timestamp(self):
        csv_content = b"""order_id,amount,currency,order_date,customer_id
ORD-001,100.00,USD,2024-01-15,CUST-001
"""
        stream = io.BytesIO(csv_content)
        results = list(read_rows(stream, "orders", max_rows=1000))
        assert len(results) == 1
        assert results[0].status == "VALID"
        assert "T00:00:00" in results[0].values["occurred_at"]

    def test_all_source_types(self):
        # Test each source type has correct transaction_type in output
        sources_and_headers = [
            ("orders", "order_id,amount,currency,order_date,customer_id\n"),
            ("payments", "payment_id,amount,currency,paid_at,order_id\n"),
            ("refunds", "refund_id,amount,currency,refunded_at,original_payment_id\n"),
            ("settlements", "settlement_id,amount,currency,settled_at,batch_reference\n"),
            ("fees", "fee_id,amount,currency,charged_at,related_payment_id\n"),
        ]
        for source, header in sources_and_headers:
            csv_content = header.encode() + b"ID-001,100.00,USD,2024-01-15T10:30:00Z,REF-001\n"
            stream = io.BytesIO(csv_content)
            results = list(read_rows(stream, source, max_rows=1000))
            assert len(results) == 1
            assert results[0].status == "VALID"
            expected_type = {
                "orders": "order",
                "payments": "payment",
                "refunds": "refund",
                "settlements": "settlement",
                "fees": "fee",
            }[source]
            assert results[0].values["transaction_type"] == expected_type


class TestRowResult:
    def test_row_result_is_frozen(self):
        result = RowResult(1, "VALID", None, None, {"a": "b"})
        with pytest.raises(AttributeError):
            result.row_number = 2

    def test_row_result_slots(self):
        result = RowResult(1, "VALID", None, None, {"a": "b"})
        # Should not have __dict__
        assert not hasattr(result, "__dict__")
