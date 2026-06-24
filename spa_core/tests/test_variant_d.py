"""
spa_core/tests/test_variant_d.py — tests for Variant D (directional restaking).

Directional, beta ≈ 1 to ETH: pure long LRT, unhedged. We verify:
  - ETH +20% → equity up ~20% (+ a touch of restaking yield) — beta ≈ 1 upside,
  - ETH -30% → drawdown kill fires once past Z (drawdown_kill_pct),
  - restaking yield accrues daily,
  - points accrue only when configured,
  - FAIL-CLOSED on an invalid/missing required datapoint,
  - peak/high-water-mark + drawdown tracking are correct,
  - determinism (same inputs → same state).

All MarketSnapshots are built directly — NO network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.strategies.variant_d import VariantD

SYM = "eeth"
CAP = 100_000.0


def cfg(drawdown_kill_pct=25.0, points=None, entry_price=None):
    c = {"lrt_symbol": SYM, "drawdown_kill_pct": drawdown_kill_pct}
    if points is not None:
        c["points_apy_assumption"] = points
    if entry_price is not None:
        c["entry_price"] = entry_price
    return c


def snap(date, price, restaking=0.03):
    """A complete, valid snapshot for one day."""
    return MarketSnapshot(
        date=date,
        lrt_price_usd={SYM: price},
        restaking_apy={SYM: restaking},
    )


def make(drawdown_kill_pct=25.0, points=None, entry_price=3000.0):
    s = VariantD()
    s.init(CAP, cfg(drawdown_kill_pct=drawdown_kill_pct, points=points, entry_price=entry_price))
    return s


# ── basic identity / init ────────────────────────────────────────────────────────────────────
def test_identity():
    s = make()
    assert s.id == "variant_d"
    assert s.mandate == "directional"
    assert s.is_advisory is True


def test_init_opens_single_lrt_leg():
    s = make(entry_price=3000.0)
    pos = s.positions()
    assert len(pos) == 1
    leg = pos[0]
    assert leg.kind == "lrt"
    assert leg.asset == SYM
    # qty = capital / entry_price
    assert math.isclose(leg.qty, CAP / 3000.0, rel_tol=1e-12)
    assert math.isclose(s.equity(), CAP, rel_tol=1e-9)


def test_init_fail_closed_on_missing_keys():
    with pytest.raises(InvalidDataError):
        VariantD().init(CAP, {"lrt_symbol": SYM})  # no drawdown_kill_pct
    with pytest.raises(InvalidDataError):
        VariantD().init(CAP, {"drawdown_kill_pct": 25.0})  # no symbol
    with pytest.raises(InvalidDataError):
        VariantD().init(0.0, cfg(entry_price=3000.0))  # non-positive capital


# ── beta ≈ 1 directional behaviour ─────────────────────────────────────────────────────────────
def test_eth_up_20pct_equity_up_about_20pct():
    # zero restaking to isolate the price beta exactly.
    s = make(entry_price=3000.0)
    # ETH (and thus the LRT) +20% → price 3600, restaking 0 for a clean beta read.
    s.step(snap("2026-06-11", 3600.0, restaking=0.0))
    # equity should be ~ +20%
    assert math.isclose(s.equity(), CAP * 1.20, rel_tol=1e-9)
    assert s.metrics().beta_to_eth == 1.0


def test_eth_up_20pct_plus_restaking_yield():
    s = make(entry_price=3000.0)
    s.step(snap("2026-06-11", 3600.0, restaking=0.0365))  # 0.01%/day
    # price gives 120k; one day of restaking adds 0.0365/365 = 0.0001 on the marked notional.
    expected = CAP * 1.20 * (1 + 0.0365 / 365.0)
    assert math.isclose(s.equity(), round(expected, 2), abs_tol=0.02)
    # strictly above the pure-price equity (yield accrued).
    assert s.equity() > CAP * 1.20


def test_eth_down_does_full_downside():
    s = make(drawdown_kill_pct=99.0, entry_price=3000.0)  # high kill so it doesn't trip
    s.step(snap("2026-06-11", 2700.0, restaking=0.0))  # -10%
    assert math.isclose(s.equity(), CAP * 0.90, rel_tol=1e-6)


# ── restaking + points accrual ────────────────────────────────────────────────────────────────
def test_restaking_accrues_flat_price():
    s = make(entry_price=3000.0)
    # flat price, only restaking accrues over 10 days.
    apy = 0.0365  # → 0.0001/day
    for i in range(10):
        s.step(snap(f"2026-06-{11+i:02d}", 3000.0, restaking=apy))
    # ~10 days of 0.0001 compounding ≈ 0.10006%
    growth = (1 + apy / 365.0) ** 10
    assert math.isclose(s.equity(), round(CAP * growth, 2), abs_tol=0.5)
    assert s.equity() > CAP
    assert s.metrics().extra["cum_restaking_usd"] > 0


def test_points_only_when_configured():
    base = make(points=None, entry_price=3000.0)
    base.step(snap("2026-06-11", 3000.0, restaking=0.0365))
    assert base.metrics().extra["cum_points_usd"] == 0.0

    pts = make(points=0.03, entry_price=3000.0)
    pts.step(snap("2026-06-11", 3000.0, restaking=0.0365))
    assert pts.metrics().extra["cum_points_usd"] > 0.0
    # points add extra equity vs the no-points book at flat price.
    assert pts.equity() > base.equity()


# ── drawdown kill ───────────────────────────────────────────────────────────────────────────────
def test_eth_down_30pct_kill_fires():
    s = make(drawdown_kill_pct=25.0, entry_price=3000.0)
    # -30% from peak (init peak = 100k) → drawdown 30% > 25% kill.
    s.step(snap("2026-06-11", 2100.0, restaking=0.0))  # 3000 → 2100 = -30%
    res = s.kill_check(snap("2026-06-11", 2100.0, restaking=0.0))
    assert res.triggered is True
    assert "drawdown" in res.reason


def test_drawdown_just_under_threshold_no_kill():
    s = make(drawdown_kill_pct=25.0, entry_price=3000.0)
    # -24% drawdown → under 25%, no kill.
    s.step(snap("2026-06-11", 3000.0 * 0.76, restaking=0.0))
    res = s.kill_check(snap("2026-06-11", 3000.0 * 0.76, restaking=0.0))
    assert res.triggered is False


def test_kill_latches_once():
    s = make(drawdown_kill_pct=25.0, entry_price=3000.0)
    s.step(snap("2026-06-11", 2100.0, restaking=0.0))
    first = s.kill_check(snap("2026-06-11", 2100.0, restaking=0.0))
    assert first.triggered is True
    # even if price recovers, the kill stays latched.
    s.step(snap("2026-06-12", 3000.0, restaking=0.0))  # step is a no-op once killed
    second = s.kill_check(snap("2026-06-12", 3000.0, restaking=0.0))
    assert second.triggered is True


def test_drawdown_measured_from_peak_not_entry():
    # Price runs up first (new peak), then falls. Drawdown must be from the HIGH-WATER mark.
    s = make(drawdown_kill_pct=25.0, entry_price=3000.0)
    s.step(snap("2026-06-11", 4000.0, restaking=0.0))  # +33% → new peak ~133k
    peak = s.metrics().extra["peak_equity"]
    assert math.isclose(peak, CAP * (4000.0 / 3000.0), rel_tol=1e-6)
    # Fall to 3200: vs entry that's +6.7% (no DD vs entry), but vs peak 4000 it's -20% → no kill yet.
    s.step(snap("2026-06-12", 3200.0, restaking=0.0))
    assert s.kill_check(snap("2026-06-12", 3200.0, restaking=0.0)).triggered is False
    # Fall to 2900: vs peak 4000 that's -27.5% > 25% → kill.
    s.step(snap("2026-06-13", 2900.0, restaking=0.0))
    res = s.kill_check(snap("2026-06-13", 2900.0, restaking=0.0))
    assert res.triggered is True


def test_peak_tracks_high_water_mark():
    s = make(drawdown_kill_pct=99.0, entry_price=3000.0)
    prices = [3000.0, 3300.0, 3100.0, 3600.0, 3500.0]
    for i, p in enumerate(prices):
        s.step(snap(f"2026-06-{11+i:02d}", p, restaking=0.0))
    # peak corresponds to the highest price seen (3600) → equity = CAP * 3600/3000.
    assert math.isclose(s.metrics().extra["peak_equity"], CAP * 3600.0 / 3000.0, rel_tol=1e-6)


# ── fail-closed on invalid data ──────────────────────────────────────────────────────────────────
def test_fail_closed_step_missing_price():
    s = make(entry_price=3000.0)
    bad = MarketSnapshot(date="2026-06-11", restaking_apy={SYM: 0.03})  # no lrt price
    with pytest.raises(InvalidDataError):
        s.step(bad)


def test_fail_closed_step_missing_restaking():
    s = make(entry_price=3000.0)
    bad = MarketSnapshot(date="2026-06-11", lrt_price_usd={SYM: 3000.0})  # no restaking
    with pytest.raises(InvalidDataError):
        s.step(bad)


def test_fail_closed_kill_check_on_invalid():
    s = make(entry_price=3000.0)
    bad = MarketSnapshot(date="2026-06-11")  # nothing valid
    res = s.kill_check(bad)
    assert res.triggered is True
    assert "fail-closed" in res.reason


# ── determinism ────────────────────────────────────────────────────────────────────────────────
def test_deterministic():
    prices = [3000.0, 3200.0, 2900.0, 3100.0, 3050.0]

    def run():
        s = make(points=0.03, entry_price=3000.0)
        for i, p in enumerate(prices):
            d = f"2026-06-{11+i:02d}"
            s.step(snap(d, p, restaking=0.04))
            s.kill_check(snap(d, p, restaking=0.04))
        return s.equity(), s.metrics().extra["peak_equity"], s.metrics().extra["cum_restaking_usd"]

    assert run() == run()


# ── deferred-entry path (init without entry_price, leg opens on first step) ────────────────────────
def test_deferred_entry_opens_on_first_step():
    s = VariantD()
    s.init(CAP, cfg(entry_price=None))  # no entry price → deferred
    assert s.positions() == []
    s.step(snap("2026-06-11", 3000.0, restaking=0.0))
    assert math.isclose(s.equity(), CAP, abs_tol=0.01)
    assert len(s.positions()) == 1
