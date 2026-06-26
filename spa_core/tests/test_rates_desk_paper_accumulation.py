"""
spa_core/tests/test_rates_desk_paper_accumulation.py — KEYSTONE accumulation contract for BOTH
forward paper services (rates_desk FixedCarry + the Strategy Lab).

WHY THIS FILE EXISTS (the architect's keystone bug): the forward paper-tracks must ACCUMULATE one
honest point per UTC day — that growing forward-carry series is what makes the validated rates-desk
GO thesis fundable. The hazard is a tick that OVERWRITES rather than APPENDs (e.g. a same-day re-tick
double-accruing / duplicating, a dropped idempotency pretick that breaks replay, or a ring-buffer that
fails to drop-oldest). These tests PIN the contract by DRIVING the tick with injected/parameterized
as_of dates (NO network, NO waiting for real hourly ticks):

  • day N → series len k; day N+1 → len k+1                 (append-one-per-day)
  • re-tick day N+1 → len unchanged, no dup, no double-accrue (idempotent per UTC day)
  • restart (reload from disk) → series + book intact         (restart-survival)
  • ring-buffer cap honored by DROPPING OLDEST, never by failing to append

stdlib only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab.paper import PaperService
from spa_core.strategy_lab.rates_desk.contracts import (
    RateQuote,
    RateVenue,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.paper_rates import RatesDeskPaperService


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# rates_desk FixedCarry paper service
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _rd_quote(u: str, as_of: str, rate: str = "0.12") -> RateQuote:
    """A PT quote whose as_of == the tick day (so the per-day series key advances with as_of)."""
    return RateQuote(
        underlying=u, kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id=f"pt-{u}", tenor_seconds=86400 * 60, as_of=as_of,
        quoted_rate=D(rate), tvl_usd=D("5e7"), exit_liquidity_usd=D("5e6"),
        hedge_available=False, utilization=D("0.5"), ltv=D("0.8"), cap_headroom_usd=D("1e7"),
    )


def _rd_risk(u: str, as_of: str) -> UnderlyingRisk:
    return UnderlyingRisk(
        underlying=u, as_of=as_of, nav_redemption_value=D("1"), market_price=D("1.0003"),
        peg_distance=D("0.0003"), peg_vol_30d=D("0.001"), redemption_sla_seconds=86400,
        reserve_fund_ratio=D("0.05"), funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink",
        oracle_staleness_seconds=300, nested_protocol_count=1, top_borrower_share=D("0.1"),
    )


def _rd_provider():
    """surface_provider(as_of) -> (quotes, risks). Rich enough (>=3 PT markets) to clear the
    THIN-surface guard, with each quote's as_of stamped to the requested day so the per-day key moves."""
    underlyings = ("susde", "usde", "susds", "wsteth")

    def provider(as_of):
        day = as_of  # the test always passes an explicit as_of
        quotes = [_rd_quote(u, day) for u in underlyings]
        risks = {u: _rd_risk(u, day) for u in underlyings}
        return quotes, risks

    return provider


def _rd_service(tmp_path: Path):
    return RatesDeskPaperService(
        surface_provider=_rd_provider(),
        state_dir=tmp_path,
        record_proof=False,          # no proof-chain side effects in the unit test
        telegram_send=lambda _t: True,
        alert_on_gap=False,
    )


def _rd_series(tmp_path: Path):
    p = tmp_path / "rates_desk_fixed_carry_series.json"
    return json.loads(p.read_text())["series"] if p.exists() else []


def test_rates_desk_appends_one_point_per_utc_day(tmp_path):
    svc = _rd_service(tmp_path)
    days = ("2026-06-10", "2026-06-11", "2026-06-12")
    for n, d in enumerate(days, start=1):
        svc.tick(as_of=d)
        series = _rd_series(tmp_path)
        assert len(series) == n, (d, n)
        assert [p["date"] for p in series] == list(days[:n])


def test_rates_desk_same_day_retick_is_idempotent(tmp_path):
    svc = _rd_service(tmp_path)
    svc.tick(as_of="2026-06-10")
    svc.tick(as_of="2026-06-11")
    eq_after = svc._sleeve.equity()
    series_len = len(_rd_series(tmp_path))

    # Re-tick the SAME day repeatedly → no duplicate point, no double-accrue.
    for _ in range(3):
        svc.tick(as_of="2026-06-11")
        series = _rd_series(tmp_path)
        assert len(series) == series_len, "same-day re-tick must not append a duplicate"
        assert series[-1]["date"] == "2026-06-11"
        assert svc._sleeve.equity() == pytest.approx(eq_after, rel=1e-12), "no double-accrue"

    # A NEW day still advances after the re-ticks (idempotency didn't wedge the clock).
    svc.tick(as_of="2026-06-12")
    series = _rd_series(tmp_path)
    assert len(series) == series_len + 1
    assert series[-1]["date"] == "2026-06-12"


def test_rates_desk_restart_survival(tmp_path):
    svc1 = _rd_service(tmp_path)
    for d in ("2026-06-10", "2026-06-11", "2026-06-12"):
        svc1.tick(as_of=d)
    eq_before = svc1._sleeve.equity()
    len_before = len(_rd_series(tmp_path))

    # Brand-new service reloads from disk — book + series continue, not zeroed.
    svc2 = _rd_service(tmp_path)
    assert svc2._sleeve.equity() == pytest.approx(eq_before, rel=1e-12)
    assert svc2._last_tick == "2026-06-12"
    assert len(_rd_series(tmp_path)) == len_before

    # A re-tick of the last day after restart is still idempotent (no dup).
    svc2.tick(as_of="2026-06-12")
    assert len(_rd_series(tmp_path)) == len_before
    # New day continues from the restored book.
    svc2.tick(as_of="2026-06-13")
    assert len(_rd_series(tmp_path)) == len_before + 1


def test_rates_desk_ring_buffer_drops_oldest(tmp_path, monkeypatch):
    import spa_core.strategy_lab.rates_desk.paper_rates as pr
    monkeypatch.setattr(pr, "SERIES_CAP", 3)
    svc = _rd_service(tmp_path)
    days = [f"2026-06-{d:02d}" for d in range(10, 16)]  # 6 distinct days, cap 3
    for d in days:
        svc.tick(as_of=d)
    series = _rd_series(tmp_path)
    assert len(series) == 3, "cap honored by dropping oldest, not by failing to append"
    assert [p["date"] for p in series] == days[-3:]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Strategy Lab paper service
# ══════════════════════════════════════════════════════════════════════════════════════════════════
class _FakeMD:
    """Injectable MarketData stand-in: latest() returns the canned snapshot (no network)."""

    def __init__(self):
        self._snap = None

    def set(self, snap):
        self._snap = snap

    def latest(self):
        return self._snap


def _snap(date: str, eth=3000.0):
    return MarketSnapshot(
        date=date, eth_price_usd=eth, funding_rate_8h=0.0002,
        lrt_price_usd={"eeth": eth * 1.03}, lrt_eth_ratio={"eeth": 1.03},
        restaking_apy={"eeth": 0.04}, defi_apy={"stable_blend": 0.045},
    )


def _lab_service(tmp_path: Path, md):
    return PaperService(market_data=md, state_dir=tmp_path, telegram_send=lambda _t: True,
                        alert_on_kill=False, alert_on_gap=False)


def _lab_series(tmp_path: Path, sid: str):
    return json.loads((tmp_path / f"{sid}_series.json").read_text())["series"]


def test_lab_pretick_is_preserved_for_idempotent_replay(tmp_path):
    """REGRESSION: _persist_state must NOT drop the `pretick` snapshot _persist_pretick stored.
    The prior bug rebuilt the state doc from scratch → pretick:None → the documented same-day
    replay path was silently dead (it fell through to the bare skip branch). Pin it here."""
    md = _FakeMD()
    md.set(_snap("2026-06-10"))
    svc = _lab_service(tmp_path, md)
    svc.tick()
    for sid in svc._strategies:
        doc = json.loads((tmp_path / f"{sid}_state.json").read_text())
        assert "pretick" in doc and doc["pretick"], f"pretick dropped for {sid}"
        assert doc["pretick"]["date"] == "2026-06-10", sid


def test_lab_appends_one_point_per_day_and_idempotent(tmp_path):
    md = _FakeMD()
    svc = _lab_service(tmp_path, md)
    days = ("2026-06-10", "2026-06-11", "2026-06-12")
    for n, d in enumerate(days, start=1):
        md.set(_snap(d, eth=3000.0 + n * 25))
        svc.tick()
        for sid in svc._strategies:
            assert len(_lab_series(tmp_path, sid)) == n, (sid, d)
        # re-tick same day → no dup, no double-accrue (equity flat, series flat)
        eq = {sid: s.equity() for sid, s in svc._strategies.items()}
        svc.tick()
        for sid, s in svc._strategies.items():
            assert len(_lab_series(tmp_path, sid)) == n, (sid, "re-tick", d)
            assert s.equity() == pytest.approx(eq[sid], rel=1e-9), sid


def test_lab_restart_survival_then_ring_buffer(tmp_path, monkeypatch):
    md = _FakeMD()
    svc1 = _lab_service(tmp_path, md)
    for d in ("2026-06-10", "2026-06-11"):
        md.set(_snap(d))
        svc1.tick()
    eq_before = {sid: s.equity() for sid, s in svc1._strategies.items()}

    # restart: reload from disk continues the book + series.
    svc2 = _lab_service(tmp_path, md)
    for sid in svc2._strategies:
        assert svc2._strategies[sid].equity() == pytest.approx(eq_before[sid], rel=1e-9), sid
        assert svc2._last_tick[sid] == "2026-06-11", sid
        assert len(_lab_series(tmp_path, sid)) == 2, sid

    # ring-buffer drops oldest (cap 3 over 5 distinct days), never fails to append.
    import spa_core.strategy_lab.paper as lp
    monkeypatch.setattr(lp, "SERIES_CAP", 3)
    svc3 = _lab_service(tmp_path, md)
    days = ("2026-06-12", "2026-06-13", "2026-06-14")
    for d in days:
        md.set(_snap(d))
        svc3.tick()
    for sid in svc3._strategies:
        series = _lab_series(tmp_path, sid)
        assert len(series) == 3, sid
        assert [p["date"] for p in series] == ["2026-06-12", "2026-06-13", "2026-06-14"], sid
