"""
spa_core/tests/test_eth_lst_neutral.py — tests for the SAFE hedged ETH-yield sleeve.

EthLstNeutral = plain-staking LST (stETH/rETH, NOT LRTs) + short ETH perp → beta ≈ 0. Mirrors
the Variant-N neutral structure with a TIGHTER depeg kill (LSTs barely depeg vs LRTs).

All hermetic: MarketSnapshots are constructed directly (no network). Covers:
  - delta-neutral: ETH ±20% → equity stays ~flat (the hedge cancels the price move);
  - staking yield accrues (positive net carry on a flat-ratio window);
  - funding-kill fires after N hours of sub-threshold funding (fail-closed safe-hold);
  - depeg-kill fires at the (tighter) Y% LST depeg;
  - fail-CLOSED on missing/invalid data (step + kill_check both latch a kill);
  - determinism: two identical runs are bit-for-bit identical.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.strategies.eth_lst_neutral import EthLstNeutral


# ── config + snapshot helpers ──────────────────────────────────────────────────────────────────
def _config(
    lst_symbol: str = "steth",
    hedge_ratio: float = 1.0,
    funding_kill_threshold: float = -0.0003,
    funding_kill_hours: float = 24,
    lst_depeg_kill_pct: float = 1.0,
) -> dict:
    """Merged config dict (global cost/funding params + the strategy block), as the backtest
    harness passes via _merged_strategy_config."""
    return {
        # global cost/funding params
        "gas_usd_per_rebalance": 8.0,
        "slippage_bps": 5.0,
        "rebalance_bps": 2.0,
        "funding_settles_per_day": 3,
        # strategy block
        "lst_symbol": lst_symbol,
        "hedge_ratio": hedge_ratio,
        "funding_kill_threshold": funding_kill_threshold,
        "funding_kill_hours": funding_kill_hours,
        "lst_depeg_kill_pct": lst_depeg_kill_pct,
    }


def _mk(date, eth_price, funding, ratio, staking, symbol="steth"):
    """A MarketSnapshot carrying the LST in the same maps the LRT variants use."""
    return MarketSnapshot(
        date=date,
        eth_price_usd=eth_price,
        funding_rate_8h=funding,
        lrt_price_usd={symbol: eth_price * ratio},
        lrt_eth_ratio={symbol: ratio},
        restaking_apy={symbol: staking},
    )


def _date(i: int) -> str:
    return f"2026-06-{10 + i:02d}"


CAP = 100_000.0


# ── neutrality: ETH ±20% → equity stays ~flat ────────────────────────────────────────────────
def test_neutral_eth_up_20pct_equity_flat():
    s = EthLstNeutral()
    s.init(CAP, _config())
    ratio = 1.0  # tight peg, no depeg
    staking = 0.0  # isolate the price/hedge effect (no carry)
    # open at 3000, then ETH +20% to 3600 with ZERO funding so only the hedge effect shows.
    s.step(_mk(_date(0), 3000.0, 0.0, ratio, staking))
    s.step(_mk(_date(1), 3600.0, 0.0, ratio, staking))
    # delta-neutral: the +20% ETH move is cancelled by the short perp → equity ≈ start capital.
    assert s.equity() == pytest.approx(CAP, rel=0.01)
    assert s.metrics().beta_to_eth == 0.0


def test_neutral_eth_down_20pct_equity_flat():
    s = EthLstNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, 0.0, 1.0, 0.0))
    s.step(_mk(_date(1), 2400.0, 0.0, 1.0, 0.0))  # ETH -20%
    # the short perp gains ~ what the LST spot loses → equity ≈ flat.
    assert s.equity() == pytest.approx(CAP, rel=0.01)


# ── staking yield accrues ─────────────────────────────────────────────────────────────────────
def test_staking_accrues_positive_carry():
    s = EthLstNeutral()
    s.init(CAP, _config())
    staking = 0.026  # ~2.6% Lido stETH
    # flat ETH price + flat ratio + ZERO funding → equity grows only by staking carry.
    s.step(_mk(_date(0), 3000.0, 0.0, 1.0, staking))
    for i in range(1, 30):
        s.step(_mk(_date(i), 3000.0, 0.0, 1.0, staking))
    # 30 days of ~2.6%/365 daily accrual on ~$100k ≈ +$210; strictly positive carry.
    assert s.equity() > CAP
    extra = s.metrics().extra
    assert extra["cum_staking_usd"] > 0
    assert extra["cum_funding_usd"] == pytest.approx(0.0, abs=1e-6)


def test_positive_funding_adds_to_a_short():
    s = EthLstNeutral()
    s.init(CAP, _config())
    # positive funding → a SHORT receives it → cum_funding > 0.
    s.step(_mk(_date(0), 3000.0, 0.0002, 1.0, 0.0))
    s.step(_mk(_date(1), 3000.0, 0.0002, 1.0, 0.0))
    assert s.metrics().extra["cum_funding_usd"] > 0


# ── funding kill after N hours ────────────────────────────────────────────────────────────────
def test_funding_kill_after_n_hours():
    # funding_kill_hours=24 → ONE sub-threshold day (24h) trips the kill.
    s = EthLstNeutral()
    s.init(CAP, _config(funding_kill_threshold=-0.0003, funding_kill_hours=24))
    snap = _mk(_date(0), 3000.0, -0.0005, 1.0, 0.026)  # below threshold
    s.step(snap)
    kr = s.kill_check(snap)
    assert kr.triggered
    assert "funding" in kr.reason.lower()


def test_funding_recovers_resets_streak():
    s = EthLstNeutral()
    s.init(CAP, _config(funding_kill_threshold=-0.0003, funding_kill_hours=48))
    # one bad day (24h), then a good day resets, then one bad day again → never 48h consecutive.
    for f in (-0.0005, 0.0002, -0.0005):
        snap = _mk(_date(0), 3000.0, f, 1.0, 0.026)
        s.step(snap)
        kr = s.kill_check(snap)
    assert not kr.triggered


# ── depeg kill at Y% (tighter than the LRT variant) ──────────────────────────────────────────
def test_depeg_kill_at_threshold():
    # A SUSTAINED depeg below the (tight) Y% kill fires — once it persists past the smoothing
    # window/persistence guard (which exists to reject 1-day DeFiLlama misalignment artifacts).
    s = EthLstNeutral()
    s.init(CAP, _config(lst_depeg_kill_pct=1.0))
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))          # entry ratio 1.0
    kr = None
    for i in range(1, 6):                                      # ratio stays -1.5% (sustained)
        bad = _mk(_date(i), 3000.0, 0.0001, 0.985, 0.026)     # -1.5% > 1.0% kill
        s.step(bad)
        kr = s.kill_check(bad)
        if kr.triggered:
            break
    assert kr.triggered
    assert "depeg" in kr.reason.lower()


def test_small_depeg_below_threshold_survives():
    s = EthLstNeutral()
    s.init(CAP, _config(lst_depeg_kill_pct=1.0))
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))
    ok = _mk(_date(1), 3000.0, 0.0001, 0.995, 0.026)  # -0.5% < 1.0% kill → survives
    s.step(ok)
    kr = s.kill_check(ok)
    assert not kr.triggered


def test_one_day_depeg_artifact_does_not_kill():
    # The FALSE-depeg fix: a lone 1-day ratio spike (a DeFiLlama daily-granularity timestamp-
    # misalignment artifact — e.g. stETH showed 0.95/1.14 in Aug-2024 while the peg held ~1.0)
    # must NOT trip the tight kill. The peg recovers the next tick → no sustained depeg.
    s = EthLstNeutral()
    s.init(CAP, _config(lst_depeg_kill_pct=1.0))
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))         # entry ratio 1.0
    # Reproduce the Aug-2024 stETH artifact sequence around a held peg.
    triggered = False
    for i, r in enumerate((1.0156, 0.9479, 1.1399, 0.9705, 1.0093, 1.0), start=1):
        bad = _mk(_date(i), 3000.0, 0.0001, r, 0.026)
        s.step(bad)
        if s.kill_check(bad).triggered:
            triggered = True
            break
    assert triggered is False  # no single-day artifact may kill the safe hedged sleeve


def test_sustained_depeg_still_kills():
    # A REAL multi-day depeg (like ezETH's Apr-2024 event) MUST still trigger the kill — the
    # smoothing/persistence guard rejects 1-day artifacts, not sustained depegs.
    s = EthLstNeutral()
    s.init(CAP, _config(lst_depeg_kill_pct=1.0))
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))         # entry ratio 1.0
    triggered = False
    for i, r in enumerate((0.99, 0.95, 0.90, 0.88, 0.87), start=1):  # drops AND STAYS down
        bad = _mk(_date(i), 3000.0, 0.0001, r, 0.026)
        s.step(bad)
        if s.kill_check(bad).triggered:
            triggered = True
            break
    assert triggered is True


def test_tighter_than_lrt_variant():
    # A SUSTAINED 1.5% depeg KILLS the LST sleeve (1.0% kill) but would NOT kill variant_n
    # (2.0% kill): proves the LST kill is tighter, reflecting LSTs' smaller depeg tail.
    s = EthLstNeutral()
    s.init(CAP, _config(lst_depeg_kill_pct=1.0))
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))
    triggered = False
    for i in range(1, 6):
        bad = _mk(_date(i), 3000.0, 0.0001, 0.985, 0.026)  # -1.5% sustained
        s.step(bad)
        if s.kill_check(bad).triggered:
            triggered = True
            break
    assert triggered  # killed at 1.0% once sustained
    # (variant_n's 2.0% threshold would NOT have fired at 1.5% — the tighter sleeve is safer.)


# ── fail-CLOSED on bad data ───────────────────────────────────────────────────────────────────
def test_fail_closed_missing_eth_price():
    s = EthLstNeutral()
    s.init(CAP, _config())
    bad = MarketSnapshot(
        date=_date(0),
        eth_price_usd=None,  # missing
        funding_rate_8h=0.0001,
        lrt_eth_ratio={"steth": 1.0},
        restaking_apy={"steth": 0.026},
    )
    s.step(bad)  # safe-hold (no raise out of step)
    assert s.metrics().extra["killed"] is True


def test_fail_closed_missing_ratio_in_kill_check():
    s = EthLstNeutral()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))
    bad = MarketSnapshot(
        date=_date(1),
        eth_price_usd=3000.0,
        funding_rate_8h=0.0001,
        lrt_eth_ratio={},  # ratio missing for steth
        restaking_apy={"steth": 0.026},
    )
    kr = s.kill_check(bad)
    assert kr.triggered
    assert "fail-closed" in kr.reason.lower()


def test_step_before_init_raises():
    s = EthLstNeutral()
    with pytest.raises(InvalidDataError):
        s.step(_mk(_date(0), 3000.0, 0.0001, 1.0, 0.026))


def test_init_rejects_nonpositive_capital():
    s = EthLstNeutral()
    with pytest.raises(InvalidDataError):
        s.init(0.0, _config())


# ── determinism ───────────────────────────────────────────────────────────────────────────────
def test_deterministic_two_runs_identical():
    snaps = [
        _mk(_date(i), 3000.0 * (1.0 + 0.01 * (i % 5 - 2)), 0.0001 * (i % 3 - 1), 1.0, 0.026)
        for i in range(20)
    ]

    def run():
        s = EthLstNeutral()
        s.init(CAP, _config())
        eq = []
        for snap in snaps:
            s.step(snap)
            s.kill_check(snap)
            eq.append(s.equity())
        return eq

    assert run() == run()
