from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from .mapping import HeaderError, validate_headers
from .normalize import (
    RowError,
    normalize_external_id,
    parse_currency,
    parse_money,
    parse_timestamp,
)


@dataclass(frozen=True, slots=True)
class RowResult:
    """Result of processing a single CSV row."""

    row_number: int
    status: str
    error_code: str | None
    error_detail: str | None
    values: dict[str, str] | None


class ImportFileError(Exception):
    """File-level error during import (encoding, size, row cap)."""

    pass


def _is_blank_row(row: list[str]) -> bool:
    """Check if a CSV row is completely empty/whitespace."""
    return all(not cell.strip() for cell in row)


def read_rows(
    stream: BinaryIO,
    source_name: str,
    *,
    max_rows: int,
) -> Iterator[RowResult]:
    """Stream rows from a binary CSV file, yielding RowResult for each data row.

    - Decodes UTF-8 with optional BOM
    - Skips blank lines without consuming a row number
    - Row numbers are 1-based file line numbers (including header)
    - Validates every row against the source layout
    - Detects DUPLICATE_IN_FILE (same external_id in same file)
    - Stops with ImportFileError if row count would exceed max_rows
    """
    # Decode with UTF-8, handling BOM
    try:
        # Read first chunk to check for BOM
        stream.seek(0)
        first_bytes = stream.read(3)
        stream.seek(0)
        has_bom = first_bytes.startswith(b"\xef\xbb\xbf")

        text_stream = io.TextIOWrapper(
            stream,
            encoding="utf-8-sig" if has_bom else "utf-8",
            newline="",
        )
    except UnicodeDecodeError as e:
        raise ImportFileError("ENCODING_ERROR") from e

    reader = csv.reader(text_stream)

    # Read header row (first non-empty row)
    header_row = None
    header_line_number = 0
    try:
        for line_number, row in enumerate(reader, start=1):
            if _is_blank_row(row):
                continue
            header_row = [cell.strip() for cell in row]
            header_line_number = line_number
            break
    except UnicodeDecodeError as e:
        raise ImportFileError("ENCODING_ERROR") from e

    if header_row is None:
        raise ImportFileError("Empty file: no header row found")

    # Validate headers
    try:
        layout = validate_headers(header_row, source_name)
    except HeaderError as e:
        if "UNKNOWN_TYPE" in str(e):
            # For unknown source type, we still need to process rows with
            # UNKNOWN_TYPE status. The first data row will be line
            # header_line_number + 1. But we need to know the layout to
            # parse... for UNKNOWN_TYPE we can't parse properly. Per the spec
            # and fixtures, unknown.csv has the same headers as orders but
            # source is unknown. We'll treat it as having no valid layout
            # and mark all rows as UNKNOWN_TYPE.
            layout = None
        else:
            raise ImportFileError(f"Header validation failed: {e}") from e

    # Build column index mapping for the layout
    col_indices: dict[str, int] = {}
    if layout:
        for i, header in enumerate(header_row):
            for col_map in layout.columns:
                if col_map.csv_header == header:
                    col_indices[col_map.canonical_field] = i
                    break

    seen_external_ids: set[str] = set()
    data_row_count = 0

    # Process data rows
    try:
        for line_number, row in enumerate(reader, start=header_line_number + 1):
            if _is_blank_row(row):
                continue

            data_row_count += 1
            if data_row_count > max_rows:
                raise ImportFileError("too many rows")

            if layout is None:
                # UNKNOWN_TYPE source
                yield RowResult(
                    row_number=line_number,
                    status="UNKNOWN_TYPE",
                    error_code="UNKNOWN_TYPE",
                    error_detail="Source type not recognized",
                    values=None,
                )
                continue

            # Extract raw values
            raw_values = {}
            for canonical_field, idx in col_indices.items():
                if idx < len(row):
                    raw_values[canonical_field] = row[idx]
                else:
                    raw_values[canonical_field] = ""

            # Validate required fields present
            missing_required = []
            for col_map in layout.columns:
                if col_map.required and col_map.canonical_field:
                    value = raw_values.get(col_map.canonical_field, "").strip()
                    if not value:
                        missing_required.append(col_map.csv_header)

            if missing_required:
                yield RowResult(
                    row_number=line_number,
                    status="MISSING_REQUIRED",
                    error_code="MISSING_REQUIRED",
                    error_detail=f"Missing required field(s): {', '.join(missing_required)}",
                    values=None,
                )
                continue

            # Parse and normalize each field
            try:
                external_id = normalize_external_id(raw_values.get("external_id", ""))
            except RowError as e:
                yield RowResult(
                    row_number=line_number,
                    status=e.code,
                    error_code=e.code,
                    error_detail="External ID is required",
                    values=None,
                )
                continue

            # Check for duplicate
            if external_id in seen_external_ids:
                yield RowResult(
                    row_number=line_number,
                    status="DUPLICATE_IN_FILE",
                    error_code="DUPLICATE_IN_FILE",
                    error_detail=f"Duplicate external_id in file: {external_id}",
                    values=None,
                )
                continue
            seen_external_ids.add(external_id)

            # Parse amount
            try:
                amount_decimal = parse_money(raw_values.get("amount", ""))
                amount_str = f"{amount_decimal:.4f}"
            except RowError as e:
                yield RowResult(
                    row_number=line_number,
                    status=e.code,
                    error_code=e.code,
                    error_detail="Invalid amount format or precision",
                    values=None,
                )
                continue

            # Parse currency
            try:
                currency = parse_currency(raw_values.get("currency", ""))
            except RowError as e:
                yield RowResult(
                    row_number=line_number,
                    status=e.code,
                    error_code=e.code,
                    error_detail="Invalid or unsupported currency code",
                    values=None,
                )
                continue

            # Parse timestamp
            try:
                occurred_at = parse_timestamp(raw_values.get("occurred_at", ""))
                occurred_at_str = occurred_at.isoformat().replace("+00:00", "Z")
            except RowError as e:
                yield RowResult(
                    row_number=line_number,
                    status=e.code,
                    error_code=e.code,
                    error_detail="Invalid timestamp format",
                    values=None,
                )
                continue

            # Reference (optional)
            reference = raw_values.get("reference", "").strip() or None

            # All validations passed
            yield RowResult(
                row_number=line_number,
                status="VALID",
                error_code=None,
                error_detail=None,
                values={
                    "source_name": layout.source_name,
                    "external_id": external_id,
                    "amount": amount_str,
                    "currency": currency,
                    "transaction_type": layout.transaction_type,
                    "reference": reference or "",
                    "occurred_at": occurred_at_str,
                },
            )
    except UnicodeDecodeError as e:
        raise ImportFileError("ENCODING_ERROR") from e
