import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "reconciliation" / "check_fixtures.py"


def test_reconciliation_fixtures_are_consistent():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "fixtures ok" in result.stdout
