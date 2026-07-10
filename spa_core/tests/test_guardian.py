"""Tests for the Dynamic Leverage Guardian overlay (spa_core/strategy_lab/aggressive_lab/guardian.py).

Verifies the proven properties: the guardian REDUCES drawdown on a series that draws down, leaves a
clean (monotone-up) series essentially untouched (no whipsaw), and is fail-closed on short input.
Deterministic; no network.
"""
from spa_core.strategy_lab import metrics
from spa_core.strategy_lab.aggressive_lab.guardian import (
    apply_guardian_drawdown,
    apply_guardian_vol,
    stdev,
)


def _drawdown_series():
    """Ramp up, then a sustained multi-day drawdown (the kind a guardian can cut), then recover."""
    eq = [100000.0]
    for _ in range(20):
        eq.append(eq[-1] * 1.004)          # calm rise
    for _ in range(15):
        eq.append(eq[-1] * 0.97)           # sustained ~3%/day drawdown
    for _ in range(20):
        eq.append(eq[-1] * 1.01)           # recovery
    return eq


def _clean_series():
    eq = [100000.0]
    for _ in range(60):
        eq.append(eq[-1] * 1.003)          # monotone up, no drawdown
    return eq


def test_reactive_guardian_reduces_drawdown():
    eq = _drawdown_series()
    raw_dd = metrics.max_drawdown_pct(eq)
    g_dd = metrics.max_drawdown_pct(apply_guardian_drawdown(eq, derisk_dd=0.04, derisk_frac=0.0))
    assert g_dd < raw_dd, f"guardian should cut drawdown: raw={raw_dd} guarded={g_dd}"


def test_preemptive_guardian_reduces_drawdown():
    eq = _drawdown_series()
    raw_dd = metrics.max_drawdown_pct(eq)
    g_dd = metrics.max_drawdown_pct(apply_guardian_vol(eq, vol_mult=2.0, derisk_frac=0.0))
    assert g_dd < raw_dd


def test_guardian_leaves_clean_series_essentially_untouched():
    # A monotone-up series has no drawdown to protect against → the guardian must NOT whipsaw it.
    eq = _clean_series()
    raw_apy = metrics.net_apy_from_equity(eq)
    for fn in (apply_guardian_drawdown, apply_guardian_vol):
        g = fn(eq)
        g_apy = metrics.net_apy_from_equity(g)
        assert metrics.max_drawdown_pct(g) <= 0.01          # essentially no drawdown introduced
        assert g_apy >= raw_apy * 0.98                       # yield not materially eroded


def test_fail_closed_on_short_series():
    assert apply_guardian_drawdown([100000.0]) == [100000.0]
    assert apply_guardian_vol([100000.0, 100100.0]) == [100000.0, 100100.0]  # < lookback+2


def test_roundtrip_cost_only_reduces_or_equals():
    eq = _drawdown_series()
    no_cost = apply_guardian_vol(eq, vol_mult=2.0, derisk_frac=0.0, roundtrip_cost=0.0)
    with_cost = apply_guardian_vol(eq, vol_mult=2.0, derisk_frac=0.0, roundtrip_cost=0.003)
    # a positive churn cost can only lower (or equal) the final equity, never raise it
    assert with_cost[-1] <= no_cost[-1] + 1e-6


def test_deterministic():
    eq = _drawdown_series()
    assert apply_guardian_vol(eq) == apply_guardian_vol(eq)
    assert stdev([1.0, 2.0, 3.0]) == stdev([1.0, 2.0, 3.0])
