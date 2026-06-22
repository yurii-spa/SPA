"""
Tests for spa_core.tools.seed_demo_data

Run with:
    python -m pytest tests/test_seed_demo.py -v
"""

import json

import pytest

from tools.seed_demo_data import seed_demo_data


EXPECTED_FILES = [
    "status.json",
    "pnl_history.json",
    "protocols.json",
    "risk_alerts.json",
    "golive_readiness.json",
    "pipeline_health.json",
    "meta.json",
]


def test_seed_creates_all_files(tmp_path):
    """Seeder must produce all 7 required JSON files in the output directory."""
    seed_demo_data(days=7, capital=100_000, output_dir=str(tmp_path))

    for filename in EXPECTED_FILES:
        fpath = tmp_path / filename
        assert fpath.exists(), f"Missing expected file: {filename}"
        assert fpath.stat().st_size > 0, f"Empty file: {filename}"


def test_pnl_history_has_correct_length(tmp_path):
    """7 days × 6 runs/day = 42 PnL history entries."""
    days = 7
    runs_per_day = 6
    seed_demo_data(days=days, capital=100_000, output_dir=str(tmp_path))

    data = json.loads((tmp_path / "pnl_history.json").read_text())
    assert isinstance(data, list), "pnl_history.json must be a JSON array"
    assert len(data) == days * runs_per_day, (
        f"Expected {days * runs_per_day} entries, got {len(data)}"
    )
    # Spot-check that each entry has required keys
    required_keys = {"timestamp", "total_capital_usd", "total_pnl_usd", "is_demo"}
    for entry in data:
        missing = required_keys - entry.keys()
        assert not missing, f"PnL entry missing keys: {missing}"


def test_all_files_valid_json(tmp_path):
    """Every generated file must parse as valid JSON without errors."""
    seed_demo_data(days=7, capital=100_000, output_dir=str(tmp_path))

    for filename in EXPECTED_FILES:
        fpath = tmp_path / filename
        try:
            data = json.loads(fpath.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"{filename} is not valid JSON: {exc}")

        # All dict-type files must carry the is_demo flag
        if isinstance(data, dict):
            assert data.get("is_demo") is True, (
                f"{filename} is missing 'is_demo: true' marker"
            )
        elif isinstance(data, list) and data:
            # List files (e.g. pnl_history, protocols) should mark entries
            assert data[0].get("is_demo") is True, (
                f"{filename}[0] is missing 'is_demo: true' marker"
            )
