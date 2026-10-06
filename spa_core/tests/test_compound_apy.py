"""spa_core/tests/test_compound_apy.py — the ONE compound-annualisation formula
(RM-TRUTH-01 W5, ADR-580 C2). Pins ``spa_core.reporting.compound_apy`` against the
canonical arithmetic already shipped in ``scripts/generate_track_snapshot.py`` and
``landing/src/lib/site_numbers.js::floorTo`` — this module exists so those stop
being three independent copies of the same three formulas.
"""
from __future__ import annotations

from spa_core.reporting.compound_apy import (
    compound_annualized_pct,
    evidenced_bars,
    floor_pct,
    max_drawdown_pct,
)


def test_compound_annualized_pct_matches_hand_computed_value():
    # $100,000 -> $100,490.32 over 10 days, compound-annualised.
    v = compound_annualized_pct(100000.0, 100490.32, 10)
    assert v is not None
    assert round(v, 2) == 19.55


def test_compound_annualized_pct_refuses_below_two_days():
    assert compound_annualized_pct(100000.0, 100100.0, 1) is None
    assert compound_annualized_pct(100000.0, 100100.0, 0) is None


def test_compound_annualized_pct_refuses_non_positive_equity():
    assert compound_annualized_pct(0.0, 100100.0, 10) is None
    assert compound_annualized_pct(100000.0, -5.0, 10) is None
    assert compound_annualized_pct(None, 100100.0, 10) is None


def test_evidenced_bars_filters_to_evidenced_true_only():
    doc = {"daily": [
        {"date": "2026-06-01", "equity": 100000.0, "evidenced": False},
        {"date": "2026-06-22", "equity": 100000.0, "evidenced": True},
        {"date": "2026-06-23", "equity": 100050.0, "evidenced": True},
    ]}
    ev = evidenced_bars(doc)
    assert len(ev) == 2
    assert all(b["evidenced"] is True for b in ev)


def test_evidenced_bars_missing_or_malformed_is_empty_not_a_guess():
    assert evidenced_bars({}) == []
    assert evidenced_bars(None) == []
    assert evidenced_bars({"daily": "not-a-list"}) == []


def test_max_drawdown_pct_prefers_per_bar_field():
    bars = [{"drawdown_pct": 0.0}, {"drawdown_pct": -0.026}, {"drawdown_pct": -0.01}]
    assert max_drawdown_pct(bars) == -0.026


def test_max_drawdown_pct_falls_back_to_equity_peak_to_trough():
    bars = [{"equity": 100.0}, {"equity": 90.0}, {"equity": 95.0}]
    assert max_drawdown_pct(bars) == -10.0


def test_floor_pct_rounds_down_never_up():
    """ADR-563 (owner decision 2026-10-04): the published rate never exceeds the
    measured one. 4.9637 must floor to 4.9, not round to 5.0."""
    assert floor_pct(4.9637, 1) == 4.9
    assert floor_pct(5.0, 1) == 5.0  # exact values are not shaved down


def test_floor_pct_epsilon_guard_does_not_shave_an_exact_value():
    """2.9 is stored in binary as 2.8999999999999996 — a naive floor would read it
    as 2.8. The 1e-9 epsilon guard (same trick as the JS floorTo) must not do that."""
    assert floor_pct(2.9, 1) == 2.9


def test_floor_pct_non_numeric_is_none():
    assert floor_pct(None, 1) is None
    assert floor_pct("4.9", 1) is None
