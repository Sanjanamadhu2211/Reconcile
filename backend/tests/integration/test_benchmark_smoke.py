import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import benchmark  # noqa: E402

pytestmark = pytest.mark.integration


def test_benchmark_smoke_run_reports_full_accuracy(capsys):
    assert benchmark.main(["--rows", "600"]) == 0

    out = capsys.readouterr().out
    for field in (
        "Dataset",
        "orders",
        "payments",
        "settlements",
        "PostgreSQL",
        "Import",
        "total",
        "rows/s",
        "Reconciliation",
        "duration",
        "records/s",
        "matches",
        "ambiguous",
        "amount_mismatch",
        "unmatched",
        "Match accuracy    100.00%",
        "Result            PASS",
    ):
        assert field in out
