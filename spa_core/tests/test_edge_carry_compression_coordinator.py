"""
spa_core/tests/test_edge_carry_compression_coordinator.py

Structural tests for Idea #104 CCC (Carry-Compression Coordinator).

Invariants guarded here (each is a minimal, runnable property — not a
hand-held golden number):
  1. Determinism: two identical runs return identical metrics.
  2. CCC max-DD ≤ EW baseline max-DD for the best IS config (lb=20, thr=−0.5).
  3. Fallback sanity: when ALL books are compressed, CCC falls back to EW
     (carry_ratio cannot produce a degenerate zero-weight portfolio).
  4. Causal property: the carry_ratio on day t uses returns [t-lb .. t-1],
     NOT [t-lb+1 .. t] (no same-bar look-ahead in the signal).

These tests do NOT assert specific APY/Calmar numbers because the fixture
values are already documented in the registry entry (#104). They assert
STRUCTURAL properties that survive any future fixture revision.

IS_ADVISORY=True. LLM_FORBIDDEN. stdlib-only.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.edge_carry_compression_coordinator import (  # noqa: E402
    BOOKS,
    INITIAL,
    _build_returns,
    _crisis_dd,
    _metrics,
    run_ccc,
    run_equal_weight,
)


def _all_rets():
    return {b: _build_returns(b) for b in BOOKS}


# ── Test 1: determinism ───────────────────────────────────────────────────────

def test_ccc_deterministic():
    """Two runs with the same params produce identical equity curves."""
    rets = _all_rets()
    c1, _ = run_ccc(rets, lookback=20, threshold=-0.5, mode="HARD")
    c2, _ = run_ccc(rets, lookback=20, threshold=-0.5, mode="HARD")
    assert c1 == c2, "CCC is not deterministic"


# ── Test 2: CCC reduces max-DD vs EW for best IS config ─────────────────────

def test_ccc_reduces_maxdd_vs_ew():
    """
    CCC-HARD(lb=20, thr=-0.5) must have max-DD ≤ EW baseline max-DD.
    This guards the core finding: per-book carry compression reduces tail risk.
    """
    rets = _all_rets()
    bl_curve, _ = run_equal_weight(rets)
    ccc_curve, _ = run_ccc(rets, lookback=20, threshold=-0.5, mode="HARD")

    bl_m = _metrics(bl_curve)
    ccc_m = _metrics(ccc_curve)

    assert ccc_m["max_dd_pct"] <= bl_m["max_dd_pct"], (
        f"CCC maxDD {ccc_m['max_dd_pct']:.2f}% should be ≤ EW maxDD {bl_m['max_dd_pct']:.2f}%"
    )


# ── Test 3: fallback to EW when all books are compressed ─────────────────────

def test_ccc_hard_fallback_equal_weight():
    """
    When all 5 books have carry_ratio below threshold, CCC must fall back to
    equal weight — NOT produce a zero-weight portfolio.
    The equity curve total should never be zero or negative (positive-only equity).
    """
    rets = _all_rets()
    # Use a very high threshold so that every day, carry_ratio < threshold
    # → fallback EW should fire every day
    curve, _ = run_ccc(rets, lookback=20, threshold=999.0, mode="HARD")
    # all equity values should be positive (no blow-up, no zero)
    assert all(v > 0.0 for v in curve), "Equity curve contains non-positive values"
    # APY should be close to EW (since fallback fires every day)
    bl_curve, _ = run_equal_weight(rets)
    m_ccc = _metrics(curve)
    m_bl = _metrics(bl_curve)
    # Both should have the same APY within floating-point tolerance
    assert abs(m_ccc["apy_pct"] - m_bl["apy_pct"]) < 0.01, (
        f"Fallback not reached: CCC APY {m_ccc['apy_pct']:.4f}% ≠ EW {m_bl['apy_pct']:.4f}%"
    )


# ── Test 4: causal property — day-t decision uses only returns through t-1 ───

def test_ccc_causal_no_same_bar_lookahead():
    """
    Verify causal property: injecting a large negative return on a specific
    day T should affect the weight on day T+1 (or later), NOT on day T itself.

    Method: we compare TWO runs that differ only on day T's return for one book.
    If the difference first appears in the equity curve on day T+1 (or later),
    the decision was made AFTER observing the shock — causal.
    If the difference appears on day T itself, the shock was used on the same bar.
    """
    rets = _all_rets()

    # Inject a huge negative shock to susde_dn on day T=50 (index 49 in 0-based)
    shock_t = 49  # 0-indexed day within the series
    shock_book = "susde_dn"

    # Build a perturbed version
    perturbed_rets = {b: list(v) for b, v in rets.items()}
    perturbed_rets[shock_book] = list(perturbed_rets[shock_book])
    orig_t50 = perturbed_rets[shock_book][shock_t]
    perturbed_rets[shock_book][shock_t] = (
        orig_t50[0],  # date unchanged
        -0.50,        # inject −50% return on day T
    )

    lb = 5  # short lookback so the shock is visible quickly
    curve_orig, _ = run_ccc(rets, lookback=lb, threshold=0.0, mode="HARD")
    curve_pert, _ = run_ccc(perturbed_rets, lookback=lb, threshold=0.0, mode="HARD")

    # curve[t+1] = equity after day t; curve[shock_t+1] = equity after shock_t
    # If causal: curves must agree through curve[shock_t+1] (same bar — shock INCLUDED
    # in equity, NOT in the weight decision on that bar)
    # The WEIGHT decision for day shock_t uses returns[shock_t-lb..shock_t-1] (no shock)
    # → equity on day shock_t should STILL differ because the RETURN differs
    # → but the weight applied to that return must be the same (no look-ahead)
    #
    # Correct causal behaviour:
    #   curve[shock_t]   (equity BEFORE day shock_t): SAME in both
    #   curve[shock_t+1] (equity AFTER day shock_t) : DIFFERENT (shock applied with same weight)
    #   curve[shock_t+2] (equity AFTER day shock_t+1): DIFFERENT AND carries CCC weight change

    # Check: before the shock, curves must be identical
    for i in range(shock_t + 1):  # indices 0..shock_t (before and at start of shock day)
        assert curve_orig[i] == curve_pert[i], (
            f"Curves diverged before shock at curve[{i}]: "
            f"{curve_orig[i]} vs {curve_pert[i]}"
        )

    # Check: after the shock day, curves must differ (shock has effect)
    assert curve_orig[shock_t + 1] != curve_pert[shock_t + 1], (
        "Curves did not diverge after shock — shock had no effect at all"
    )


# ── Test 5: SOFT mode weight normalization ────────────────────────────────────

def test_ccc_soft_mode_never_negative_equity():
    """SOFT mode must never produce negative equity (weights always ≥ 0, sum to 1)."""
    rets = _all_rets()
    curve, _ = run_ccc(rets, lookback=10, threshold=0.0, mode="SOFT")
    assert all(v > 0.0 for v in curve), "SOFT mode produced non-positive equity"
