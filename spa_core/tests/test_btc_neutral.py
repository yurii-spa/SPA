"""
spa_core/tests/test_btc_neutral.py — tests for the market-neutral BTC funding-carry sleeve.

BtcNeutral = long SAFE wrapped-BTC spot (tBTC/cbBTC) + short BTC perp → beta ≈ 0 to BTC. Income
= BTC perp funding + a small honest lending floor. Mirrors EthLstNeutral with a wrapper-depeg kill
that REUSES the depeg-median-smoothing (artifact-vs-sustained).

All hermetic: MarketSnapshots are constructed directly (no network). Covers:
  - delta-neutral: BTC ±20% → equity stays ~flat (the short perp cancels the price move);
  - funding carry + lending floor accrue (positive net carry on a flat-ratio window);
  - funding-kill fires after N hours of sub-threshold BTC funding (fail-closed safe-hold);
  - wrapper-depeg kill fires on a SUSTAINED depeg but NOT on a 1-day artifact (smoothed signal);
  - fail-CLOSED on missing/invalid BTC data (step + kill_check both latch a kill);
  - determinism: two identical runs are bit-for-bit identical.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.strategies.btc_neutral import BtcNeutral


def _config(
    wrapper_symbol: str = "tbtc",
    hedge_ratio: float = 1.0,
    funding_kill_threshold: float = -0.0003,
    funding_kill_hours: float = 24,
    wrapper_depeg_kill_pct: float = 2.0,
) -> dict:
    return {
        # global cost/funding params
        "gas_usd_per_rebalance": 8.0,
        "slippage_bps": 5.0,
        "rebalance_bps": 2.0,
        "funding_settles_per_day": 3,
        # strategy block
        "wrapper_symbol": wrapper_symbol,
        "hedge_ratio": hedge_ratio,
        "funding_kill_threshold": funding_kill_threshold,
        "funding_kill_hours": funding_kill_hours,
        "wrapper_depeg_kill_pct": wrapper_depeg_kill_pct,
    }


def _mk(date, btc_price, funding, ratio, lending=0.0, symbol="tbtc"):
    return MarketSnapshot(
        date=date,
        btc_price_usd=btc_price,
        btc_funding_rate_8h=funding,
        btc_wrapper_price_usd={symbol: btc_price * ratio},
        btc_wrapper_ratio={symbol: ratio},
        btc_lending_apy={symbol: lending},
    )


def _date(i: int) -> str:
    return f"2026-06-{10 + i:02d}"


CAP = 100_000.0


# ── neutrality: BTC ±20% → equity stays ~flat ────────────────────────────────────────────────
def test_neutral_btc_up_20pct_equity_flat():
    s = BtcNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, 0.0, 1.0, 0.0))
    s.step(_mk(_date(1), 72000.0, 0.0, 1.0, 0.0))  # BTC +20%
    assert s.equity() == pytest.approx(CAP, rel=0.01)
    assert s.metrics().beta_to_eth == 0.0
    assert s.metrics().extra["beta_to_btc"] == 0.0


def test_neutral_btc_down_20pct_equity_flat():
    s = BtcNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, 0.0, 1.0, 0.0))
    s.step(_mk(_date(1), 48000.0, 0.0, 1.0, 0.0))  # BTC -20%
    assert s.equity() == pytest.approx(CAP, rel=0.01)


# ── income: funding carry + lending floor ─────────────────────────────────────────────────────
def test_funding_and_lending_accrue_positive_carry():
    s = BtcNeutral()
    s.init(CAP, _config())
    # flat price + flat ratio + positive funding + small lending floor → positive carry.
    s.step(_mk(_date(0), 60000.0, 0.0002, 1.0, 0.004))
    for i in range(1, 30):
        s.step(_mk(_date(i), 60000.0, 0.0002, 1.0, 0.004))
    assert s.equity() > CAP
    extra = s.metrics().extra
    assert extra["cum_funding_usd"] > 0   # short receives positive funding
    assert extra["cum_lending_usd"] > 0   # the small honest floor accrues


def test_negative_funding_costs_a_short():
    s = BtcNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, -0.0001, 1.0, 0.0))
    s.step(_mk(_date(1), 60000.0, -0.0001, 1.0, 0.0))
    assert s.metrics().extra["cum_funding_usd"] < 0  # a short PAYS negative funding


# ── funding kill after N hours ────────────────────────────────────────────────────────────────
def test_funding_kill_after_n_hours():
    s = BtcNeutral()
    s.init(CAP, _config(funding_kill_threshold=-0.0003, funding_kill_hours=24))
    snap = _mk(_date(0), 60000.0, -0.0005, 1.0, 0.004)
    s.step(snap)
    kr = s.kill_check(snap)
    assert kr.triggered
    assert "funding" in kr.reason.lower()


def test_funding_recovers_resets_streak():
    s = BtcNeutral()
    s.init(CAP, _config(funding_kill_threshold=-0.0003, funding_kill_hours=48))
    for f in (-0.0005, 0.0002, -0.0005):
        snap = _mk(_date(0), 60000.0, f, 1.0, 0.004)
        s.step(snap)
        kr = s.kill_check(snap)
    assert not kr.triggered


# ── wrapper-depeg kill: artifact-vs-sustained (the smoothed signal) ──────────────────────────
def test_sustained_wrapper_depeg_kills():
    s = BtcNeutral()
    s.init(CAP, _config(wrapper_depeg_kill_pct=2.0))
    s.step(_mk(_date(0), 60000.0, 0.0001, 1.0, 0.004))  # entry ratio 1.0
    triggered = False
    for i, r in enumerate((0.99, 0.96, 0.95, 0.94, 0.93), start=1):  # drops AND STAYS down
        bad = _mk(_date(i), 60000.0, 0.0001, r, 0.004)
        s.step(bad)
        if s.kill_check(bad).triggered:
            triggered = True
            break
    assert triggered
    assert "depeg" in s.metrics().extra["kill_reason"].lower()


def test_one_day_wrapper_depeg_artifact_does_not_kill():
    # A lone 1-day ratio spike (a DeFiLlama daily-granularity timestamp-misalignment artifact)
    # must NOT trip the kill — the peg recovers the next tick → no sustained depeg.
    s = BtcNeutral()
    s.init(CAP, _config(wrapper_depeg_kill_pct=2.0))
    s.step(_mk(_date(0), 60000.0, 0.0001, 1.0, 0.004))
    triggered = False
    for i, r in enumerate((1.012, 0.95, 1.03, 0.97, 1.005, 1.0), start=1):
        bad = _mk(_date(i), 60000.0, 0.0001, r, 0.004)
        s.step(bad)
        if s.kill_check(bad).triggered:
            triggered = True
            break
    assert triggered is False


def test_small_depeg_below_threshold_survives():
    s = BtcNeutral()
    s.init(CAP, _config(wrapper_depeg_kill_pct=2.0))
    s.step(_mk(_date(0), 60000.0, 0.0001, 1.0, 0.004))
    ok = _mk(_date(1), 60000.0, 0.0001, 0.99, 0.004)  # -1% < 2% kill → survives
    s.step(ok)
    assert not s.kill_check(ok).triggered


# ── fail-CLOSED on bad data ───────────────────────────────────────────────────────────────────
def test_fail_closed_missing_btc_price():
    s = BtcNeutral()
    s.init(CAP, _config())
    bad = MarketSnapshot(
        date=_date(0),
        btc_price_usd=None,  # missing
        btc_funding_rate_8h=0.0001,
        btc_wrapper_ratio={"tbtc": 1.0},
        btc_lending_apy={"tbtc": 0.004},
    )
    s.step(bad)  # safe-hold (no raise out of step)
    assert s.metrics().extra["killed"] is True


def test_fail_closed_missing_funding_in_kill_check():
    s = BtcNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, 0.0001, 1.0, 0.004))
    bad = MarketSnapshot(
        date=_date(1),
        btc_price_usd=60000.0,
        btc_funding_rate_8h=None,  # missing
        btc_wrapper_ratio={"tbtc": 1.0},
        btc_lending_apy={"tbtc": 0.004},
    )
    kr = s.kill_check(bad)
    assert kr.triggered
    assert "fail-closed" in kr.reason.lower()


def test_lending_floor_optional_zero_is_legitimate():
    # 0% lending is a legitimate, expected BTC reading — the sleeve still runs on funding alone.
    s = BtcNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, 0.0002, 1.0, 0.0))
    s.step(_mk(_date(1), 60000.0, 0.0002, 1.0, 0.0))
    assert s.metrics().extra["cum_lending_usd"] == pytest.approx(0.0, abs=1e-9)
    assert s.metrics().extra["cum_funding_usd"] > 0


def test_step_before_init_raises():
    s = BtcNeutral()
    with pytest.raises(InvalidDataError):
        s.step(_mk(_date(0), 60000.0, 0.0001, 1.0, 0.004))


def test_init_rejects_nonpositive_capital():
    s = BtcNeutral()
    with pytest.raises(InvalidDataError):
        s.init(0.0, _config())


# ── determinism ───────────────────────────────────────────────────────────────────────────────
def test_deterministic_two_runs_identical():
    snaps = [
        _mk(_date(i), 60000.0 * (1.0 + 0.01 * (i % 5 - 2)), 0.0001 * (i % 3 - 1), 1.0, 0.004)
        for i in range(20)
    ]

    def run():
        s = BtcNeutral()
        s.init(CAP, _config())
        eq = []
        for snap in snaps:
            s.step(snap)
            s.kill_check(snap)
            eq.append(s.equity())
        return eq

    assert run() == run()
