"""
Tests for APYTracker — 6 tests covering snapshot recording,
trend calculation, pruning, and weighted portfolio APY.
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import sys
import os

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.apy_tracker import APYTracker


def _make_tracker(tmp_path: Path) -> APYTracker:
    """Create a tracker using a temp file."""
    history_file = str(tmp_path / "apy_history.json")
    return APYTracker(history_file=history_file)


def _pool(project: str, symbol: str, apy: float, tvl: float = 1_000_000) -> dict:
    return {"project": project, "symbol": symbol, "apy": apy, "tvlUsd": tvl}


def _ts(days_ago: float = 0) -> str:
    """Return an ISO timestamp N days in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ──────────────────────────────────────────────────────────────────────────────


def test_record_snapshot_creates_file(tmp_path):
    """record_snapshot with 3 pools should create apy_history.json."""
    tracker = _make_tracker(tmp_path)
    pools = [
        _pool("aave", "USDC", 5.0),
        _pool("compound", "USDC", 4.5),
        _pool("morpho", "USDC", 5.8),
    ]
    tracker.record_snapshot(pools)

    history_file = tmp_path / "apy_history.json"
    assert history_file.exists(), "apy_history.json should be created"

    data = json.loads(history_file.read_text())
    assert "protocol_history" in data
    assert len(data["protocol_history"]) == 3
    assert "aave:USDC" in data["protocol_history"]
    assert "compound:USDC" in data["protocol_history"]
    assert "morpho:USDC" in data["protocol_history"]


def test_trend_stable_when_no_change(tmp_path):
    """Recording the same APY 5 times should produce trend=STABLE."""
    tracker = _make_tracker(tmp_path)
    pool = _pool("aave", "USDC", 5.0)
    for i in range(5):
        tracker.record_snapshot([pool])

    trend = tracker.get_trend("aave:USDC", days=7)
    assert trend["trend"] == "STABLE", f"Expected STABLE, got {trend['trend']}"
    assert trend["data_points"] == 5


def test_trend_up_when_rising(tmp_path):
    """Recording APY rising from 4.0 → 5.0 should produce trend=UP and change_7d_bps=100."""
    tracker = _make_tracker(tmp_path)
    # Record 4.0% first
    tracker.record_snapshot([_pool("aave", "USDC", 4.0)], timestamp=_ts(days_ago=1))
    # Record 5.0% now
    tracker.record_snapshot([_pool("aave", "USDC", 5.0)], timestamp=_ts(days_ago=0))

    trend = tracker.get_trend("aave:USDC", days=7)
    assert trend["trend"] == "UP", f"Expected UP, got {trend['trend']}"
    assert trend["change_7d_bps"] == 100.0, f"Expected 100 bps, got {trend['change_7d_bps']}"


def test_trend_down_when_falling(tmp_path):
    """Recording APY falling from 6.0 → 4.5 should produce trend=DOWN."""
    tracker = _make_tracker(tmp_path)
    tracker.record_snapshot([_pool("compound", "USDC", 6.0)], timestamp=_ts(days_ago=2))
    tracker.record_snapshot([_pool("compound", "USDC", 4.5)], timestamp=_ts(days_ago=0))

    trend = tracker.get_trend("compound:USDC", days=7)
    assert trend["trend"] == "DOWN", f"Expected DOWN, got {trend['trend']}"
    assert trend["change_7d_bps"] < -10, f"Expected negative change, got {trend['change_7d_bps']}"


def test_prune_old_entries(tmp_path):
    """Entries older than MAX_HISTORY_DAYS should be pruned after save."""
    tracker = _make_tracker(tmp_path)
    # Record an entry 100 days ago (beyond the 90-day window)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    tracker.record_snapshot([_pool("yearn", "USDC", 8.0)], timestamp=old_ts)

    # Record a fresh entry to trigger pruning
    tracker.record_snapshot([_pool("yearn", "USDC", 8.1)], timestamp=_ts(days_ago=0))

    # Reload to confirm pruning was persisted
    reloaded = APYTracker(history_file=str(tmp_path / "apy_history.json"))
    entries = reloaded._data["protocol_history"].get("yearn:USDC", [])
    # Only the fresh entry (within 90 days) should survive
    assert len(entries) == 1, f"Expected 1 entry after prune, got {len(entries)}"
    assert entries[0]["ts"] != old_ts, "Old entry should have been pruned"


def test_weighted_portfolio_apy(tmp_path):
    """Weighted APY: Aave 5.2% @ 60% + Compound 4.8% @ 40% → 5.04%."""
    tracker = _make_tracker(tmp_path)

    # Record within 1-day window so get_trend(days=1) picks them up
    tracker.record_snapshot(
        [
            _pool("aave", "USDC", 5.2),
            _pool("compound", "USDC", 4.8),
        ],
        timestamp=_ts(days_ago=0),
    )

    positions = [
        {"protocol": "aave", "symbol": "USDC", "allocation_pct": 60},
        {"protocol": "compound", "symbol": "USDC", "allocation_pct": 40},
    ]
    weighted = tracker.weighted_portfolio_apy(positions)
    # 5.2 * 60 + 4.8 * 40 = 312 + 192 = 504 / 100 = 5.04
    assert abs(weighted - 5.04) < 0.001, f"Expected 5.04, got {weighted}"
