# Reconciliation Fixtures

Golden fixtures for testing the reconciliation engine. All inputs and expected outputs derived strictly from `docs/data-model.md`.

## Input Files

| File | Source | Rows (data) |
|------|--------|-------------|
| `orders.csv` | orders | 20 |
| `payments.csv` | payments | 22 |
| `refunds.csv` | refunds | 6 |
| `settlements.csv` | settlements | 19 |
| `fees.csv` | fees | 4 |

Row numbers in expected outputs are 1-based file line numbers (including header).

## Coverage Map

| Case | Description | Covered By |
|------|-------------|------------|
| Rule 1 exact_id | Exact external_id match | orders:2↔payments:2, payments:2↔settlements:2, refunds:2↔payments:13, refunds:5↔payments:23 |
| Rule 2 within tolerance | Amount+currency+time ≤24h | orders:3↔payments:3 (5h), orders:4↔payments:4 (24h), payments:3↔settlements:3 (10.5h), payments:4↔settlements:4 (24h) |
| Rule 2 at boundary | Exactly 24h = match | orders:4↔payments:4, payments:4↔settlements:4 |
| Rule 2 beyond boundary | 24h+1s = no match | orders:5 vs payments:5, payments:5 vs settlements:5 |
| Unmatched left | Order no payment, payment no settlement, refund no payment | orders:5,6,11,17; payments:5,6,11,13,18,23; refunds:3 |
| Amount mismatch | Same ID, different amount | orders:7 vs payments:7, payments:7 vs settlements:7, refunds:4 vs payments:22 |
| Currency mismatch | Same ID, different currency | orders:9 vs payments:9, payments:9 vs settlements:9 |
| Duplicate in file | First VALID, second DUPLICATE_IN_FILE | orders:11/12, payments:11/12, refunds:5/6, settlements:11/12, orders:7/8, orders:9/10, payments:7/8, payments:9/10, settlements:7/8, settlements:9/10 |
| Refund matched | Refund→payment exact_id | refunds:2↔payments:13, refunds:5↔payments:23 |
| Refund unmatched | Refund no payment | refunds:3 |
| Fee rows | Not matched in MVP | fees:2, fees:3 → unmatched exceptions |
| Ambiguous 1→2 | One left, two right candidates | orders:18 (ORD-AMB1) ↔ payments:19,20; settlements:13 (SETL-AMB1) ↔ payments:19,20 |
| Ambiguous 2→1 | Two left, one right candidate | orders:19,20 ↔ payments:21; settlements:14,15 ↔ payments:21 |
| MISSING_REQUIRED | Empty required field | orders:13, payments:14, settlements:16, fees:5 |
| BAD_AMOUNT | >4 decimals | orders:14, payments:15, settlements:17, fees:4 |
| BAD_CURRENCY | Unknown ISO code | orders:15, payments:16, settlements:18 |
| BAD_TIMESTAMP | Unparseable timestamp | orders:16, payments:17, refunds:7, settlements:19 |
| UNKNOWN_TYPE | Invalid source_name | orders:21 (simulated batch-level error) |
| Thousands separator | `1,234.56` accepted | orders:17, payments:18, settlements:20 |
| Blank line | Skipped silently | (trailing newline in each file) |

## Expected Output Files

| File | Description | Sort Order |
|------|-------------|------------|
| `expected_import_rows.csv` | Every data row: source_file, row_number, validation_status, error_code | source_file, row_number |
| `expected_matches.csv` | Every match: rule, left_source, left_external_id, left_row_number, right_source, right_external_id, right_row_number | left_source, left_row_number, right_source, right_row_number |
| `expected_exceptions.csv` | Every exception: category, source, external_id, row_number | source, row_number |

## Usage

These fixtures are consumed by `check_fixtures.py` to verify that any implementation produces exactly these outcomes. Run:

```bash
python backend/tests/fixtures/reconciliation/check_fixtures.py
```

Output `fixtures ok` with exit code 0 means all assertions pass.