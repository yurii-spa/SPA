"""
spa_core/tests/test_eth_lst_staking.py — tests for the directional ETH-staking sleeve.

EthLstStaking = HOLD a plain-staking LST (stETH/rETH), earn the staking APY (~2.5%) ON TOP OF
full ETH price exposure (beta ≈ 1 to ETH). The directional counterpart to eth_lst_neutral. Kill =
drawdown stop. Mirrors variant_d's mark-to-market mechanics, on the SAFE LST asset.

All hermetic: MarketSnapshots are constructed directly (no network). Covers:
  - directional: ETH ±20% → equity moves ~±20% (beta ≈ 1);
  - staking yield accrues a positive carry on a flat-price window;
  - drawdown stop fires when the ETH drawdown exceeds the configured kill, and latches;
  - fail-CLOSED on missing/invalid data (step raises / kill_check latches);
  - determinism: two identical runs are bit-for-bit identical.

The LST flows through the SAME snapshot maps the LRT variants use (lrt_price/lrt_ratio/restaking).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.strategies.eth_lst_staking import EthLstStaking


def _config(lst_symbol: str = "steth", drawdown_kill_pct: float = 25.0) -> dict:
    return {"lst_symbol": lst_symbol, "drawdown_kill_pct": drawdown_kill_pct}


def _mk(date, eth_price, ratio=1.0, staking=0.026, symbol="steth"):
    return MarketSnapshot(
        date=date,
        eth_price_usd=eth_price,
        lrt_price_usd={symbol: eth_price * ratio},
        lrt_eth_ratio={symbol: ratio},
        restaking_apy={symbol: staking},
    )


def _date(i: int) -> str:
    return f"2026-06-{10 + i:02d}"


CAP = 100_000.0


# ── directional: beta ≈ 1 to ETH ──────────────────────────────────────────────────────────────
def test_directional_eth_up_20pct():
    s = EthLstStaking()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, staking=0.0))   # entry, no carry to isolate price
    s.step(_mk(_date(1), 3600.0, staking=0.0))   # ETH +20%
    assert s.equity() == pytest.approx(CAP * 1.2, rel=0.01)
    assert s.metrics().beta_to_eth == 1.0


def test_directional_eth_down_10pct():
    s = EthLstStaking()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, staking=0.0))
    s.step(_mk(_date(1), 2700.0, staking=0.0))   # ETH -10%
    assert s.equity() == pytest.approx(CAP * 0.9, rel=0.01)


# ── staking yield accrues (flat price) ──────────────────────────────────────────────────────
def test_staking_accrues_positive_carry():
    s = EthLstStaking()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, staking=0.026))   # ~2.6% Lido stETH
    for i in range(1, 60):
        s.step(_mk(_date(i), 3000.0, staking=0.026))
    assert s.equity() > CAP
    assert s.metrics().extra["cum_staking_usd"] > 0


# ── drawdown kill ─────────────────────────────────────────────────────────────────────────────
def test_drawdown_stop_trips_when_breached():
    s = EthLstStaking()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 3000.0, staking=0.0))    # peak at 3000
    kr = None
    for i, px in enumerate((2700.0, 2400.0, 2100.0), start=1):  # falls to -30%
        s.step(_mk(_date(i), px, staking=0.0))
        kr = s.kill_check(_mk(_date(i), px, staking=0.0))
        if kr.triggered:
            break
    assert kr.triggered
    assert "drawdown" in kr.reason.lower()


def test_shallow_drawdown_survives():
    s = EthLstStaking()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 3000.0, staking=0.0))
    s.step(_mk(_date(1), 2700.0, staking=0.0))    # -10% < 25% kill
    assert not s.kill_check(_mk(_date(1), 2700.0, staking=0.0)).triggered


def test_kill_latches():
    s = EthLstStaking()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 3000.0, staking=0.0))
    s.step(_mk(_date(1), 2000.0, staking=0.0))    # -33%
    assert s.kill_check(_mk(_date(1), 2000.0, staking=0.0)).triggered
    assert s.kill_check(_mk(_date(2), 3000.0, staking=0.0)).triggered  # latched


# ── fail-CLOSED on bad data ───────────────────────────────────────────────────────────────────
def test_fail_closed_missing_ratio_in_kill_check():
    s = EthLstStaking()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 3000.0, staking=0.026))
    bad = MarketSnapshot(date=_date(1), eth_price_usd=3000.0, lrt_eth_ratio={},
                         restaking_apy={"steth": 0.026})
    kr = s.kill_check(bad)
    assert kr.triggered
    assert "fail-closed" in kr.reason.lower()


def test_fail_closed_step_raises_on_missing_price():
    s = EthLstStaking()
    s.init(CAP, _config())
    bad = MarketSnapshot(date=_date(0), eth_price_usd=None, lrt_eth_ratio={"steth": 1.0},
                         restaking_apy={"steth": 0.026})
    with pytest.raises(InvalidDataError):
        s.step(bad)


def test_init_rejects_nonpositive_capital():
    s = EthLstStaking()
    with pytest.raises(InvalidDataError):
        s.init(0.0, _config())


def test_init_rejects_missing_lst_symbol():
    s = EthLstStaking()
    with pytest.raises(InvalidDataError):
        s.init(CAP, {"drawdown_kill_pct": 25.0})


# ── determinism ───────────────────────────────────────────────────────────────────────────────
def test_deterministic_two_runs_identical():
    snaps = [_mk(_date(i), 3000.0 * (1.0 + 0.01 * (i % 5 - 2)), staking=0.026) for i in range(20)]

    def run():
        s = EthLstStaking()
        s.init(CAP, _config())
        eq = []
        for snap in snaps:
            s.step(snap)
            s.kill_check(snap)
            eq.append(s.equity())
        return eq

    assert run() == run()
