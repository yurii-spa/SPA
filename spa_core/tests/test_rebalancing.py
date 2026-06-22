"""
tests/test_rebalancing.py — portfolio drift-based rebalancing tests.

Covers:
  - test_no_drift_when_at_target
  - test_trim_when_overweight
  - test_add_when_underweight
  - test_should_rebalance_true_on_large_drift
  - test_should_rebalance_false_when_balanced
  - test_rebalance_actions_produced
  - test_cash_outside_bounds_triggers_rebalance

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_rebalancing.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Make spa_core importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helper: build a PaperTrader instance without touching the real DB
# ---------------------------------------------------------------------------

def _make_trader():
    """Instantiate PaperTrader with all DB calls stubbed out."""
    with patch("paper_trading.engine.get_connection"), \
         patch("paper_trading.engine.get_db_path", return_value=":memory:"), \
         patch("paper_trading.engine.PaperTrader._ensure_strategy_state"):
        from paper_trading.engine import PaperTrader
        trader = PaperTrader.__new__(PaperTrader)
        # Minimal attribute setup — methods under test don't need real DB
        from risk.policy import RiskPolicy
        trader.policy = RiskPolicy()
        trader.strategy_id = "paper-v1"
        trader.db_path = ":memory:"
        trader._dlog = None
        return trader


# ---------------------------------------------------------------------------
# 1. No drift when positions are exactly at target
# ---------------------------------------------------------------------------

def test_no_drift_when_at_target():
    """Positions at exactly their target pct → all drift = 0, action = OK."""
    trader = _make_trader()

    total = 100_000.0
    positions = [
        {"protocol": "aave-v3-usdc", "amount_usd": 30_000.0, "target_pct": 30.0},
        {"protocol": "compound-usdc", "amount_usd": 20_000.0, "target_pct": 20.0},
    ]

    drift = trader.calculate_drift(positions, total)

    assert len(drift) == 2
    for rec in drift:
        assert rec["drift_pct"] == 0.0, f"Expected zero drift for {rec['protocol']}"
        assert rec["action"] == "OK"
        assert rec["urgency"] == "LOW"


# ---------------------------------------------------------------------------
# 2. TRIM when a position is overweight by >5%
# ---------------------------------------------------------------------------

def test_trim_when_overweight():
    """Position at 42% vs 30% target → drift = +12%, action = TRIM, urgency = HIGH."""
    trader = _make_trader()

    total = 100_000.0
    positions = [
        {"protocol": "aave-v3-usdc", "amount_usd": 42_000.0, "target_pct": 30.0},
    ]

    drift = trader.calculate_drift(positions, total)

    assert len(drift) == 1
    rec = drift[0]
    assert rec["protocol"] == "aave-v3-usdc"
    assert abs(rec["current_pct"] - 42.0) < 1e-6
    assert abs(rec["target_pct"] - 30.0) < 1e-6
    assert abs(rec["drift_pct"] - 12.0) < 1e-6
    assert rec["action"] == "TRIM"
    assert rec["urgency"] == "HIGH"
    assert rec["drift_usd"] > 0


# ---------------------------------------------------------------------------
# 3. ADD when a position is underweight by >5%
# ---------------------------------------------------------------------------

def test_add_when_underweight():
    """Position at 18% vs 30% target → drift = -12%, action = ADD, urgency = HIGH."""
    trader = _make_trader()

    total = 100_000.0
    positions = [
        {"protocol": "compound-usdc", "amount_usd": 18_000.0, "target_pct": 30.0},
    ]

    drift = trader.calculate_drift(positions, total)

    assert len(drift) == 1
    rec = drift[0]
    assert abs(rec["drift_pct"] - (-12.0)) < 1e-6
    assert rec["action"] == "ADD"
    assert rec["urgency"] == "HIGH"
    assert rec["drift_usd"] < 0


# ---------------------------------------------------------------------------
# 4. should_rebalance → True when any drift > 5%
# ---------------------------------------------------------------------------

def test_should_rebalance_true_on_large_drift():
    """should_rebalance() returns True when a position drifted >5% from target."""
    trader = _make_trader()

    total = 100_000.0
    # cash = 100k - 40k = 60k → 60% — outside [3%, 20%] by itself, but let's
    # use a well-funded scenario so we test the drift path, not cash path.
    # Deployed = 92k → cash = 8% (within bounds).  One position drifted +6%.
    positions = [
        {"protocol": "aave-v3-usdc",  "amount_usd": 36_000.0, "target_pct": 30.0},  # +6%
        {"protocol": "compound-usdc", "amount_usd": 30_000.0, "target_pct": 30.0},
        {"protocol": "morpho-usdc",   "amount_usd": 26_000.0, "target_pct": 26.0},
    ]

    assert trader.should_rebalance(positions, total) is True


# ---------------------------------------------------------------------------
# 5. should_rebalance → False when all within 5%
# ---------------------------------------------------------------------------

def test_should_rebalance_false_when_balanced():
    """should_rebalance() returns False when no drift exceeds 5% and cash is normal."""
    trader = _make_trader()

    total = 100_000.0
    # Deployed = 80k → cash = 20% (just on the boundary → still within [3%, 20%])
    positions = [
        {"protocol": "aave-v3-usdc",  "amount_usd": 30_000.0, "target_pct": 30.0},
        {"protocol": "compound-usdc", "amount_usd": 25_000.0, "target_pct": 25.0},
        {"protocol": "morpho-usdc",   "amount_usd": 25_000.0, "target_pct": 25.0},
    ]

    assert trader.should_rebalance(positions, total) is False


# ---------------------------------------------------------------------------
# 6. rebalance_actions() produces non-empty list when drift exists
# ---------------------------------------------------------------------------

def test_rebalance_actions_produced():
    """rebalance_actions() returns at least one action when a position has drift >5%."""
    trader = _make_trader()

    total = 100_000.0
    positions = [
        {"protocol": "aave-v3-usdc",  "amount_usd": 38_000.0, "target_pct": 30.0},  # +8% → TRIM
        {"protocol": "compound-usdc", "amount_usd": 30_000.0, "target_pct": 30.0},
        {"protocol": "morpho-usdc",   "amount_usd": 24_000.0, "target_pct": 24.0},
    ]

    ops = trader.rebalance_actions(positions, total)

    assert len(ops) > 0
    trim_ops = [o for o in ops if o["action"] == "REBALANCE_TRIM"]
    assert len(trim_ops) == 1
    assert trim_ops[0]["protocol"] == "aave-v3-usdc"
    assert trim_ops[0]["amount_usd"] > 0
    assert "Drift" in trim_ops[0]["reason"]


# ---------------------------------------------------------------------------
# 7. Cash outside bounds triggers rebalance
# ---------------------------------------------------------------------------

def test_cash_outside_bounds_triggers_rebalance():
    """Cash < 3% of portfolio triggers should_rebalance() = True."""
    trader = _make_trader()

    total = 100_000.0
    # Deploy 98k → cash = 2% (below 3% minimum)
    positions = [
        {"protocol": "aave-v3-usdc",  "amount_usd": 50_000.0, "target_pct": 50.0},
        {"protocol": "compound-usdc", "amount_usd": 48_000.0, "target_pct": 48.0},
    ]

    # cash = 100k - 98k = 2k → 2% < 3% threshold
    assert trader.should_rebalance(positions, total) is True
