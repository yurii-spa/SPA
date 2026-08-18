"""Tests for edge R&D idea #56 — MHE: Multi-Horizon Ensemble Scoring.

Tests are written on hand-crafted minimal series (NOT the real panel) so they
are deterministic, fast, and do not depend on any file or network access.

All checks operate on the ADVISORY module only — no execution code imported,
RiskPolicy v1.0 untouched, capital does not move.
"""
# LLM_FORBIDDEN
# IS_ADVISORY = True
# OUTSIDE_RISKPOLICY = True
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# import only the advisory edge module
from scripts.edge_multi_horizon_ensemble import (
    mhe_scores,
    xsd_scores,
    rank_demotion_flags,
    alloc_recycle,
    portfolio_metrics,
    raw_metrics,
    build_panel,
    L_FAST,
    L_MID,
    L_SLOW,
    _MHE_CONFIGS,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _const_rets(n: int, drift: float) -> list:
    return [drift] * n


def _make_books(n: int, drifts: dict) -> dict:
    return {b: _const_rets(n, d) for b, d in drifts.items()}


# ─── 1. Warm-up contract ─────────────────────────────────────────────────────

def test_mhe_none_before_L_slow():
    """MHE requires L_SLOW days of history; scores are None before that."""
    rets = _make_books(L_SLOW + 10, {"a": 0.001, "b": 0.002})
    sc = mhe_scores(rets, 1/3, 1/3, 1/3)
    for b in ("a", "b"):
        assert all(v is None for v in sc[b][:L_SLOW]), (
            f"Expected None for first {L_SLOW} days"
        )
        assert all(v is not None for v in sc[b][L_SLOW:]), (
            "Expected numeric scores after warm-up"
        )


def test_xsd_none_before_L():
    """XSD requires L days; scores are None before that."""
    rets = _make_books(L_MID + 5, {"a": 0.001, "b": 0.002})
    sc = xsd_scores(rets, L=L_MID)
    for b in ("a", "b"):
        assert all(v is None for v in sc[b][:L_MID])
        assert all(v is not None for v in sc[b][L_MID:])


# ─── 2. Constant drift → MHE matches XSD60 in relative order ────────────────

def test_mhe_preserves_rank_on_constant_drift():
    """With constant drift, all horizons agree → MHE ranking equals XSD(L=60) ranking."""
    n = L_SLOW + 50
    rets = _make_books(n, {"high": 0.002, "low": 0.001})
    sc_mhe = mhe_scores(rets, 1/3, 1/3, 1/3)
    sc_xsd = xsd_scores(rets, L=L_MID)
    # After warm-up both should rank "high" > "low"
    for i in range(L_SLOW, n):
        mhe_high = sc_mhe["high"][i]
        mhe_low = sc_mhe["low"][i]
        xsd_high = sc_xsd["high"][i]
        xsd_low = sc_xsd["low"][i]
        assert mhe_high is not None and mhe_low is not None
        assert xsd_high is not None and xsd_low is not None
        assert mhe_high > mhe_low, "MHE should rank high > low on constant drift"
        assert xsd_high > xsd_low, "XSD should rank high > low on constant drift"


# ─── 3. MHE is a convex combination ─────────────────────────────────────────

def test_mhe_equal_weight_is_average_of_three():
    """MHE(1/3,1/3,1/3) score == arithmetic mean of XSD(L20), XSD(L60), XSD(L180) scores."""
    n = L_SLOW + 30
    rets = _make_books(n, {"a": 0.003, "b": 0.001})
    sc_mhe = mhe_scores(rets, 1/3, 1/3, 1/3)
    sc20 = xsd_scores(rets, L=L_FAST)
    sc60 = xsd_scores(rets, L=L_MID)
    sc180 = xsd_scores(rets, L=L_SLOW)
    for b in ("a", "b"):
        for i in range(L_SLOW, n):
            expected = (sc20[b][i] + sc60[b][i] + sc180[b][i]) / 3
            actual = sc_mhe[b][i]
            assert actual is not None
            assert abs(actual - expected) < 1e-12, (
                f"MHE score {actual} != average of three {expected}"
            )


def test_mhe_weights_sum_to_one_property():
    """MHE fast-heavy (0.5, 0.35, 0.15) correctly assigns higher weight to L_FAST signal."""
    n = L_SLOW + 20
    # Create a situation where L=20 mean ≠ L=60 mean ≠ L=180 mean
    # by using a single-day shock followed by constant drift
    rets = {"a": [0.001] * n, "b": [0.001] * n}
    # add a shock 25 days before end: still in L20 window, outside would be inside L60 but...
    shock_idx = n - 25
    rets["a"][shock_idx] = 0.05  # positive spike
    sc_mhe = mhe_scores(rets, 0.5, 0.35, 0.15)
    sc20 = xsd_scores(rets, L=L_FAST)
    sc60 = xsd_scores(rets, L=L_MID)
    sc180 = xsd_scores(rets, L=L_SLOW)
    for i in range(L_SLOW, n):
        if sc20["a"][i] is None or sc60["a"][i] is None or sc180["a"][i] is None:
            continue
        expected = 0.5 * sc20["a"][i] + 0.35 * sc60["a"][i] + 0.15 * sc180["a"][i]
        actual = sc_mhe["a"][i]
        assert actual is not None
        assert abs(actual - expected) < 1e-12


# ─── 4. Demotion logic: fail-CLOSED when too few rankable books ──────────────

def test_rank_demotion_failclosed_insufficient_rankable():
    """If fewer than k+1 books are rankable, no state changes (fail-CLOSED)."""
    # Only one book has a valid score (the other is None throughout)
    sc = {
        "a": [0.001] * 10,
        "b": [None] * 10,  # type: ignore[list-item]
    }
    flags = rank_demotion_flags(sc, k=1, readmit_days=1)
    # No book should be demoted (fail-CLOSED: only 1 rankable < k+1 = 2)
    for b in ("a", "b"):
        assert not any(flags[b]), f"Book {b} should not be demoted (fail-CLOSED)"


# ─── 5. Allocator recycling ───────────────────────────────────────────────────

def test_alloc_recycle_weights_sum_to_one():
    """At each timestep, allocated weights sum to 1.0."""
    books = ["a", "b", "c"]
    flags = {
        "a": [False, True, False, True],
        "b": [False, False, True, True],
        "c": [False, False, False, False],
    }
    n = 4
    w = alloc_recycle(books, flags, n)
    for i in range(n):
        total = sum(w[b][i] for b in books)
        assert abs(total - 1.0) < 1e-10, f"Weights sum {total} != 1.0 at day {i}"


# ─── 6. FLIP control: demoting BEST books must lose to normal demotion ────────

def test_flip_control_worse_than_normal():
    """Demoting the BEST books (flip) should give lower net APY than normal demotion.

    Note: we compare netAPY rather than Calmar because on a pure constant-drift
    panel without any crisis drawdown, both strategies have Calmar = inf (no drawdown).
    netAPY is the right metric here: normal demotion concentrates capital in high-drift
    books → higher netAPY; flip demotion concentrates in low-drift books → lower netAPY.
    """
    n = L_SLOW + 100
    # high drift books vs low drift: clear ranking
    rets = _make_books(n, {"high_a": 0.004, "high_b": 0.003, "low_c": 0.0005, "low_d": 0.0001})
    books = sorted(rets)
    sc = mhe_scores(rets, 1/3, 1/3, 1/3)

    fl_normal = rank_demotion_flags(sc, k=2, readmit_days=1, worst_first=True)
    fl_flip = rank_demotion_flags(sc, k=2, readmit_days=1, worst_first=False)

    w_normal = alloc_recycle(books, fl_normal, n)
    w_flip = alloc_recycle(books, fl_flip, n)

    m_normal = portfolio_metrics(books, rets, w_normal, n)
    m_flip = portfolio_metrics(books, rets, w_flip, n)

    assert m_normal["net_apy"] > m_flip["net_apy"], (
        f"Normal netAPY {m_normal['net_apy']:.4f} should exceed flip {m_flip['net_apy']:.4f}"
    )


# ─── 7. Crisis memory: MHE with slow component remembers past crises ─────────

def test_slow_component_extends_crisis_memory():
    """After a crisis, XSD(L=20) re-admits a book faster than a slow-heavy MHE."""
    n = L_SLOW + 120
    # One book has a large negative hit near the start
    crash_idx = L_SLOW + 5
    rets_a = [0.002] * n
    rets_b = [0.002] * n
    # Book 'b' takes a −20% hit concentrated in 3 days
    for j in range(crash_idx, crash_idx + 3):
        rets_b[j] = -0.07  # large daily loss
    rets = {"a": rets_a, "b": rets_b}
    books = ["a", "b"]

    sc_fast = xsd_scores(rets, L=L_FAST)
    sc_slow_mhe = mhe_scores(rets, 0.15, 0.35, 0.50)  # slow-heavy

    # Find the first day after the crash where 'b' is BACK IN TOP score for the fast signal
    fast_readmit = None
    for i in range(crash_idx + 5, n):
        if sc_fast["b"][i] is not None and sc_fast["a"][i] is not None:
            if sc_fast["b"][i] >= sc_fast["a"][i]:
                fast_readmit = i
                break

    # For slow-heavy MHE, find the same re-admission
    slow_readmit = None
    for i in range(crash_idx + 5, n):
        if sc_slow_mhe["b"][i] is not None and sc_slow_mhe["a"][i] is not None:
            if sc_slow_mhe["b"][i] >= sc_slow_mhe["a"][i]:
                slow_readmit = i
                break

    # Slow-heavy MHE should take LONGER to re-admit the crashed book
    if fast_readmit is not None and slow_readmit is not None:
        assert slow_readmit >= fast_readmit, (
            f"Slow-heavy MHE re-admits at {slow_readmit} BEFORE fast {fast_readmit} — "
            "expected slow MHE to have longer crisis memory"
        )


# ─── 8. fixture panel builds without errors ──────────────────────────────────

def test_build_panel_shape():
    """Fixture panel builds correctly: 5 books, expected number of days."""
    axis, rets = build_panel()
    assert len(rets) == 5, f"Expected 5 books, got {len(rets)}"
    n = len(axis)
    assert n > 600, f"Expected >600 days, got {n}"
    for b, r in rets.items():
        assert len(r) == n, f"Book {b} has {len(r)} days, expected {n}"


# ─── 9. MHE-equal OOS does not regress vs XSD(L=60) ─────────────────────────

def test_mhe_equal_oos_calmar_competitive_vs_xsd60():
    """MHE-equal (k=2, M=20) Calmar on full panel is >= XSD(L=60) Calmar."""
    axis, rets = build_panel()
    books = sorted(rets)
    n = len(axis)

    sc_xsd = xsd_scores(rets, L=L_MID)
    sc_mhe = mhe_scores(rets, 1/3, 1/3, 1/3)

    k, m_days = 2, 20
    fl_xsd = rank_demotion_flags(sc_xsd, k, m_days)
    fl_mhe = rank_demotion_flags(sc_mhe, k, m_days)

    w_xsd = alloc_recycle(books, fl_xsd, n)
    w_mhe = alloc_recycle(books, fl_mhe, n)

    m_xsd = portfolio_metrics(books, rets, w_xsd, n)
    m_mhe = portfolio_metrics(books, rets, w_mhe, n)

    assert m_mhe["calmar"] >= m_xsd["calmar"] - 0.05, (
        f"MHE-equal Calmar {m_mhe['calmar']:.3f} unexpectedly << "
        f"XSD(L=60) Calmar {m_xsd['calmar']:.3f} — registry result changed?"
    )


# ─── 10. Raw baseline: equal-weight has negative APY on fixture ──────────────

def test_raw_negative_apy_on_fixture():
    """Raw equal-weight portfolio should have negative APY on this fixture (fixture sanity)."""
    axis, rets = build_panel()
    books = sorted(rets)
    n = len(axis)
    m = raw_metrics(books, rets, n)
    assert m["apy"] < 0, (
        f"Expected negative raw APY on crisis-heavy fixture, got {m['apy']:.3f}"
    )


# ─── 11. MHE config weights sum to 1 ─────────────────────────────────────────

def test_mhe_config_weights_sum_to_one():
    """All predefined MHE weight sets sum to approximately 1.0."""
    for name, (a, b, g) in _MHE_CONFIGS.items():
        total = a + b + g
        assert abs(total - 1.0) < 1e-10, (
            f"Config {name} weights {a}+{b}+{g} = {total} != 1.0"
        )


# ─── 12. MHE fast-heavy exits crisis faster than slow-heavy ──────────────────

def test_fast_heavy_exits_crisis_sooner_than_slow_heavy():
    """Fast-heavy MHE turns negative score sooner after a crisis starts than slow-heavy."""
    n = L_SLOW + 50
    # Two books: 'safe' earns steady drift; 'risky' suffers a crash near the warmup end
    crash_start = L_SLOW + 2
    rets_safe = [0.001] * n
    rets_risky = [0.003] * n
    for j in range(crash_start, crash_start + 20):
        rets_risky[j] = -0.015  # crash

    rets = {"risky": rets_risky, "safe": rets_safe}
    books = sorted(rets)

    sc_fast = mhe_scores(rets, 0.5, 0.35, 0.15)
    sc_slow = mhe_scores(rets, 0.15, 0.35, 0.5)

    # Find first day after crash where 'risky' goes negative under fast vs slow
    fast_neg = None
    slow_neg = None
    for i in range(crash_start, n):
        if sc_fast["risky"][i] is not None and fast_neg is None:
            if sc_fast["risky"][i] < 0:
                fast_neg = i
        if sc_slow["risky"][i] is not None and slow_neg is None:
            if sc_slow["risky"][i] < 0:
                slow_neg = i

    # Fast-heavy should detect negative score earlier (or same time) as slow-heavy
    if fast_neg is not None and slow_neg is not None:
        assert fast_neg <= slow_neg, (
            f"Fast-heavy first negative at {fast_neg}, slow-heavy at {slow_neg} — "
            "expected fast to go negative first"
        )
