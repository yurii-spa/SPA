"""
spa_core/tests/test_btc_lending_sleeve.py — tests for the directional BTC + lending-floor sleeve.

BtcLendingSleeve = HOLD a SAFE wrapped-BTC token (tBTC/cbBTC), earn the small lending floor
(~0–1.2%, honest) ON TOP OF full BTC price exposure (beta ≈ 1 to BTC). The directional BTC
counterpart to btc_neutral. Kill = drawdown stop. Mirrors variant_d's mark-to-market mechanics.

All hermetic: MarketSnapshots are constructed directly (no network). Covers:
  - directional: BTC ±20% → equity moves ~±20% (beta ≈ 1);
  - the lending floor accrues a small positive carry on a flat-price window;
  - drawdown stop fires when the BTC drawdown exceeds the configured kill, and latches;
  - fail-CLOSED on missing/invalid BTC data (step raises / kill_check latches);
  - 0% lending is a legitimate, expected reading (no accrual that day);
  - determinism: two identical runs are bit-for-bit identical.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.strategies.btc_lending_sleeve import BtcLendingSleeve


def _config(wrapper_symbol: str = "tbtc", drawdown_kill_pct: float = 25.0) -> dict:
    return {"wrapper_symbol": wrapper_symbol, "drawdown_kill_pct": drawdown_kill_pct}


def _mk(date, btc_price, ratio=1.0, lending=0.004, symbol="tbtc"):
    return MarketSnapshot(
        date=date,
        btc_price_usd=btc_price,
        btc_wrapper_price_usd={symbol: btc_price * ratio},
        btc_wrapper_ratio={symbol: ratio},
        btc_lending_apy={symbol: lending},
    )


def _date(i: int) -> str:
    return f"2026-06-{10 + i:02d}"


CAP = 100_000.0


# ── directional: beta ≈ 1 to BTC ──────────────────────────────────────────────────────────────
def test_directional_btc_up_20pct():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, lending=0.0))   # entry, no carry to isolate price
    s.step(_mk(_date(1), 72000.0, lending=0.0))   # BTC +20%
    assert s.equity() == pytest.approx(CAP * 1.2, rel=0.01)  # full upside
    assert s.metrics().extra["beta_to_btc"] == 1.0


def test_directional_btc_down_10pct():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, lending=0.0))
    s.step(_mk(_date(1), 54000.0, lending=0.0))   # BTC -10%
    assert s.equity() == pytest.approx(CAP * 0.9, rel=0.01)  # full downside


# ── lending floor accrues (flat price) ──────────────────────────────────────────────────────
def test_lending_floor_accrues_positive_carry():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, lending=0.012))  # ~1.2% floor (top of the honest band)
    for i in range(1, 60):
        s.step(_mk(_date(i), 60000.0, lending=0.012))
    assert s.equity() > CAP  # small but positive carry on a flat-price window
    assert s.metrics().extra["cum_lending_usd"] > 0


def test_zero_lending_is_legitimate_no_accrual():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, lending=0.0))
    s.step(_mk(_date(1), 60000.0, lending=0.0))
    assert s.equity() == pytest.approx(CAP, rel=1e-6)  # flat price + 0% floor → flat
    assert s.metrics().extra["cum_lending_usd"] == pytest.approx(0.0, abs=1e-9)


# ── drawdown kill ─────────────────────────────────────────────────────────────────────────────
def test_drawdown_stop_trips_when_breached():
    s = BtcLendingSleeve()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 60000.0, lending=0.0))   # peak at 60k
    kr = None
    for i, px in enumerate((54000.0, 48000.0, 42000.0), start=1):  # falls to -30%
        s.step(_mk(_date(i), px, lending=0.0))
        kr = s.kill_check(_mk(_date(i), px, lending=0.0))
        if kr.triggered:
            break
    assert kr.triggered
    assert "drawdown" in kr.reason.lower()


def test_shallow_drawdown_survives():
    s = BtcLendingSleeve()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 60000.0, lending=0.0))
    s.step(_mk(_date(1), 54000.0, lending=0.0))   # -10% < 25% kill
    assert not s.kill_check(_mk(_date(1), 54000.0, lending=0.0)).triggered


def test_kill_latches():
    s = BtcLendingSleeve()
    s.init(CAP, _config(drawdown_kill_pct=25.0))
    s.step(_mk(_date(0), 60000.0, lending=0.0))
    s.step(_mk(_date(1), 40000.0, lending=0.0))   # -33%
    assert s.kill_check(_mk(_date(1), 40000.0, lending=0.0)).triggered
    # subsequent checks stay triggered (latched) even on a recovery
    assert s.kill_check(_mk(_date(2), 60000.0, lending=0.0)).triggered


# ── fail-CLOSED on bad data ───────────────────────────────────────────────────────────────────
def test_fail_closed_missing_ratio_in_kill_check():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    s.step(_mk(_date(0), 60000.0, lending=0.004))
    bad = MarketSnapshot(date=_date(1), btc_price_usd=60000.0, btc_wrapper_ratio={})
    kr = s.kill_check(bad)
    assert kr.triggered
    assert "fail-closed" in kr.reason.lower()


def test_fail_closed_step_raises_on_missing_price():
    s = BtcLendingSleeve()
    s.init(CAP, _config())
    bad = MarketSnapshot(date=_date(0), btc_price_usd=None, btc_wrapper_ratio={"tbtc": 1.0})
    with pytest.raises(InvalidDataError):
        s.step(bad)


def test_init_rejects_nonpositive_capital():
    s = BtcLendingSleeve()
    with pytest.raises(InvalidDataError):
        s.init(0.0, _config())


def test_init_rejects_missing_wrapper_symbol():
    s = BtcLendingSleeve()
    with pytest.raises(InvalidDataError):
        s.init(CAP, {"drawdown_kill_pct": 25.0})


# ── determinism ───────────────────────────────────────────────────────────────────────────────
def test_deterministic_two_runs_identical():
    snaps = [_mk(_date(i), 60000.0 * (1.0 + 0.01 * (i % 5 - 2)), lending=0.004) for i in range(20)]

    def run():
        s = BtcLendingSleeve()
        s.init(CAP, _config())
        eq = []
        for snap in snaps:
            s.step(snap)
            s.kill_check(snap)
            eq.append(s.equity())
        return eq

    assert run() == run()
