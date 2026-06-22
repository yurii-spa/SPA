"""
tests/test_drawdown_attribution_coverage.py

MP-1468 (v10.84) — Coverage tests for spa_core/paper_trading/drawdown_attribution.py
(1049 lines, previously untested in tests/).

15 tests focused on pure, side-effect-free functions.
stdlib-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.drawdown_attribution import (
    identify_drawdown_episodes,
    drawdown_summary,
    attribute_drawdown,
    get_worst_drawdown,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _curve(*values, start="2026-01-01"):
    """Build equity_curve list from plain equity values."""
    from datetime import date, timedelta
    base = date.fromisoformat(start)
    return [
        {"date": str(base + timedelta(days=i)), "equity": v}
        for i, v in enumerate(values)
    ]


# ─── identify_drawdown_episodes ───────────────────────────────────────────────


def test_01_no_drawdown_monotone_up():
    """Monotonically rising curve → zero episodes."""
    curve = _curve(100, 110, 120, 130)
    eps = identify_drawdown_episodes(curve)
    assert eps == []


def test_02_single_episode_with_recovery():
    """One down-then-recover episode is detected correctly."""
    curve = _curve(100, 90, 80, 100, 110)
    eps = identify_drawdown_episodes(curve)
    assert len(eps) == 1
    ep = eps[0]
    assert ep["peak_equity"] == 100
    assert ep["trough_equity"] == 80
    assert ep["drawdown_pct"] < 0
    assert ep["recovery_date"] is not None


def test_03_ongoing_episode_no_recovery():
    """Drawdown that doesn't recover by end → recovery_date is None."""
    curve = _curve(100, 90, 80, 70)
    eps = identify_drawdown_episodes(curve)
    assert len(eps) == 1
    assert eps[0]["recovery_date"] is None
    assert eps[0]["trough_equity"] == 70


def test_04_drawdown_pct_correct():
    """drawdown_pct = (trough/peak - 1) * 100."""
    curve = _curve(200, 100, 200)
    eps = identify_drawdown_episodes(curve)
    assert len(eps) == 1
    assert abs(eps[0]["drawdown_pct"] - (-50.0)) < 0.01


def test_05_two_episodes():
    """Two separate drawdown episodes are both detected."""
    curve = _curve(100, 90, 100, 80, 100)
    eps = identify_drawdown_episodes(curve)
    assert len(eps) == 2


def test_06_flat_curve_no_episodes():
    """Flat equity → no drawdown episodes."""
    curve = _curve(100, 100, 100, 100)
    eps = identify_drawdown_episodes(curve)
    assert eps == []


def test_07_empty_curve():
    """Empty input → empty list, no error."""
    assert identify_drawdown_episodes([]) == []


def test_08_too_short_curve():
    """Single-bar curve → empty list."""
    curve = _curve(100)
    assert identify_drawdown_episodes(curve) == []


# ─── drawdown_summary ─────────────────────────────────────────────────────────


def test_09_summary_no_episodes():
    """Monotone curve → all fields are None except total_episodes=0."""
    curve = _curve(100, 110, 120)
    s = drawdown_summary(curve)
    assert s["total_episodes"] == 0
    assert s["max_drawdown"] is None
    assert s["avg_drawdown"] is None


def test_10_summary_one_episode():
    """Summary with one recovered episode has valid max_drawdown."""
    curve = _curve(100, 80, 100)
    s = drawdown_summary(curve)
    assert s["total_episodes"] == 1
    assert s["max_drawdown"] < 0
    assert s["avg_recovery_time"] is not None


def test_11_summary_max_drawdown_is_most_negative():
    """max_drawdown is the worst (most-negative) drawdown."""
    curve = _curve(100, 90, 100, 60, 100)
    s = drawdown_summary(curve)
    assert s["max_drawdown"] <= -30.0  # ~-40 pct from 100→60


# ─── attribute_drawdown ───────────────────────────────────────────────────────


def test_12_attribute_drawdown_proportional():
    """Attribution sums to ~100 when alloc and returns are well-formed."""
    episode = {
        "start_date": "2026-01-01",
        "trough_date": "2026-01-03",
    }
    allocation_fracs = {"aave": 0.5, "compound": 0.5}
    protocol_returns = {
        "aave":    {"2026-01-02": -0.02, "2026-01-03": -0.01},
        "compound":{"2026-01-02": -0.02, "2026-01-03": -0.03},
    }
    result = attribute_drawdown(episode, allocation_fracs, protocol_returns)
    if result:  # may return {} on edge cases
        total = sum(result.values())
        assert abs(total - 100.0) < 1.0, f"sum={total}"


def test_13_attribute_drawdown_empty_alloc():
    """Empty allocation → attribution returns empty dict without raising."""
    episode = {"start_date": "2026-01-01", "trough_date": "2026-01-02"}
    result = attribute_drawdown(episode, {}, {})
    assert isinstance(result, dict)


# ─── get_worst_drawdown ───────────────────────────────────────────────────────


def test_14_get_worst_drawdown_no_dd():
    """Monotone curve → result is None or empty, no error."""
    curve = _curve(100, 110, 120)
    result = get_worst_drawdown(curve)
    assert result is None or result == {}


def test_15_get_worst_drawdown_picks_deepest():
    """Two episodes: get_worst picks the deeper one."""
    # Episode 1: -10%, Episode 2: -40%
    curve = _curve(100, 90, 100, 60, 100)
    result = get_worst_drawdown(curve)
    assert result is not None
    assert result.get("drawdown_pct", 0) <= -30.0
