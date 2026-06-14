"""
tests/test_conftest_fixtures.py — validates that conftest.py fixtures produce
correct, well-typed synthetic data. These are smoke tests for the shared fixture
layer itself, not for production logic.

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_conftest_fixtures.py -v
"""

from __future__ import annotations


# ── Pool fixtures ─────────────────────────────────────────────────────────

def test_mock_pool_t1_aave_valid(mock_pool_t1_aave):
    """T1 Aave pool fixture has positive APY/TVL and is a stablecoin."""
    assert mock_pool_t1_aave["apy"] > 0, "APY must be positive"
    assert mock_pool_t1_aave["tvlUsd"] > 0, "TVL must be positive"
    assert mock_pool_t1_aave["stablecoin"] is True, "Aave USDC pool should be a stablecoin"
    assert mock_pool_t1_aave["project"] == "aave-v3"
    assert mock_pool_t1_aave["chain"] == "Ethereum"


def test_mock_pool_list_has_four_pools(mock_pool_list):
    """Standard pool list fixture must contain exactly 4 pools."""
    assert len(mock_pool_list) == 4, f"Expected 4 pools, got {len(mock_pool_list)}"
    # Verify all required keys present in each pool
    required_keys = {"pool", "project", "symbol", "chain", "apy", "tvlUsd"}
    for pool in mock_pool_list:
        missing = required_keys - pool.keys()
        assert not missing, f"Pool {pool.get('pool')} missing keys: {missing}"


# ── RiskConfig fixtures ───────────────────────────────────────────────────

def test_default_risk_config_valid(default_risk_config):
    """Default RiskConfig must have max_single_protocol < 1.0 (a valid fraction)."""
    assert default_risk_config.max_single_protocol < 1.0, (
        f"max_single_protocol {default_risk_config.max_single_protocol} must be < 1.0"
    )
    assert default_risk_config.max_single_protocol > 0.0
    assert default_risk_config.max_total_t2_allocation < 1.0


# ── Portfolio / position fixtures ─────────────────────────────────────────

def test_mock_positions_sum_to_85pct(mock_positions):
    """Sum of allocation_pct across all positions must equal 85.0%."""
    total = sum(p["allocation_pct"] for p in mock_positions)
    assert abs(total - 85.0) < 1e-6, (
        f"Expected allocation_pct sum == 85.0, got {total}"
    )


# ── PnL history fixture ───────────────────────────────────────────────────

def test_mock_pnl_history_has_84_entries(mock_pnl_history):
    """14 days × 6 runs/day = 84 PnL history entries."""
    assert len(mock_pnl_history) == 84, (
        f"Expected 84 PnL history entries (14d × 6), got {len(mock_pnl_history)}"
    )
    # Verify entry shape
    required_keys = {"timestamp", "portfolio_value", "pnl_usd", "daily_return_pct"}
    for entry in mock_pnl_history[:3]:
        missing = required_keys - entry.keys()
        assert not missing, f"PnL entry missing keys: {missing}"


# ── Temp data dir fixture ─────────────────────────────────────────────────

def test_populated_data_dir_has_files(populated_data_dir):
    """populated_data_dir must contain status.json and pnl_history.json."""
    assert (populated_data_dir / "status.json").exists(), "status.json not found"
    assert (populated_data_dir / "pnl_history.json").exists(), "pnl_history.json not found"
    assert (populated_data_dir / "risk_alerts.json").exists(), "risk_alerts.json not found"

    # Files must be valid JSON and non-empty
    import json

    status = json.loads((populated_data_dir / "status.json").read_text())
    assert "positions" in status

    history = json.loads((populated_data_dir / "pnl_history.json").read_text())
    assert isinstance(history, list)
    assert len(history) == 84
