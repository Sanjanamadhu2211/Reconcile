import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

import seed_demo  # noqa: E402


@pytest.mark.parametrize(
    "set_vars",
    [
        {"DEMO_PASSWORD": "test-only-placeholder"},
        {"DEMO_EMAIL": "demo@example.com"},
    ],
)
def test_main_refuses_to_seed_without_both_demo_variables(monkeypatch, capsys, set_vars):
    monkeypatch.delenv("DEMO_EMAIL", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    for name, value in set_vars.items():
        monkeypatch.setenv(name, value)

    assert seed_demo.main() == 1
    assert "DEMO_EMAIL and DEMO_PASSWORD must both be set" in capsys.readouterr().err
