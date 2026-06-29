"""
spa_core/tests/test_aggressive_lab_mark_to_market.py — the MARK-TO-MARKET realism contract.

The owner's purpose: a year-long paper-test of the 15% strategies whose realized equity curve ACTUALLY
DIPS −X% on the REAL event dates (the Oct-2025 USDe unwind, the LRT depegs) — not a smooth accrual with
a modeled overlay bolted on. This file is the red-team + smoke for exactly that:

  RED-TEAM
  • the dips come from REAL historical price/funding moves on the REAL dates — feed two DIFFERENT
    real paths and the realized trough MOVES with the data (a hardcoded −12% stamped on a date would
    not), and the trough lands ON the real event day, not an arbitrary one;
  • a book whose risk shape has NO real per-day price path for the event (points_farm: incentive_decay)
    shows NO fabricated realized dip — its tail stays in the labelled modeled overlay;
  • the stable ~5% book inherits NO dip (its real path had no such event) — max-DD stays ~0.

  SMOKE
  • re-run the backtest through a stress window → the aggressive equity curves visibly dip on the real
    event date, realized_drawdowns is POPULATED with dated episodes (date + depth + recovery), and the
    mark provenance is honestly stamped (mtm_source == "realized_backtest_series" on a real-mark day).

stdlib + pytest only; everything injected (no network); deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

import pytest

from spa_core.strategy_lab.aggressive_lab import _io
from spa_core.strategy_lab.aggressive_lab import annual_contrast as ac
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.harness import run_backtest

_EVENT = datetime.date(2025, 10, 1)   # the canonical USDe-unwind window start
_FLIP_DAY = 8                          # the regime flips mid-window at i == _FLIP_DAY


def _stress_feeds(n: int = 25, *, eth_low: float = 2400.0, ratio_low: float = 0.90):
    """A real-SHAPED injected history with a mid-window stress at i==_FLIP_DAY: funding inverts, the
    PT implied yield spikes (PT marks down), ETH crashes, the LRT/LST ratios depeg. The magnitudes are
    parameterized so a test can feed TWO different real paths and prove the dip tracks the data."""
    dates = [(_EVENT + datetime.timedelta(days=i)).isoformat() for i in range(n)]
    susde, pt, funding, eth = {}, {}, {}, {}
    rest = {"steth": {}, "eeth": {}}
    ratio = {"eeth": {}, "steth": {}}
    for i, d in enumerate(dates):
        stressed = i >= _FLIP_DAY
        susde[d] = 0.11
        pt[d] = 0.45 if stressed else 0.12                 # implied yield spikes → PT marks down
        funding[d] = -0.0006 if stressed else 0.0001       # funding inverts (carry → bleed)
        eth[d] = eth_low if stressed else 3000.0           # ETH crash
        rest["steth"][d] = 0.03
        rest["eeth"][d] = 0.032
        ratio["eeth"][d] = ratio_low if stressed else 1.03  # LRT depeg
        ratio["steth"][d] = 0.97 if stressed else 1.0       # LST wobble (for the leverage loop)
    feeds = AggressiveFeeds(
        susde_apy_series=susde, pt_susde_series=pt, funding_series=funding,
        eth_price_series=eth, restaking_series=rest, lrt_ratio_series=ratio,
    )
    return feeds, dates


def _series(tmp_path, sid):
    return _io.read_jsonl(tmp_path / sid / "realized_series.jsonl")


def _max_dd_and_trough(series):
    peak = series[0]["equity_usd"]
    worst = 0.0
    trough_date = None
    for p in series:
        peak = max(peak, p["equity_usd"])
        dd = (peak - p["equity_usd"]) / peak if peak else 0.0
        if dd > worst:
            worst = dd
            trough_date = p["date"]
    return worst * 100.0, trough_date


# ════════════════════════════════════════════════════════════════════════════════════════════════
# SMOKE — the realized curve dips on the real date; realized_drawdowns populated; provenance stamped
# ════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", ["susde_spot", "lrt_neutral", "eth_directional",
                                 "pendle_pt_levered", "pendle_yt_susde", "leverage_loop"])
def test_aggressive_books_dip_on_the_real_event_date(tmp_path, sid):
    """Each price/funding-exposed aggressive book's realized equity MUST dip materially through the
    stress window, with the trough ON or after the real flip day (not before it)."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    series = _series(tmp_path, sid)
    mdd, trough = _max_dd_and_trough(series)
    assert mdd > 2.0, f"{sid} realized curve did not dip (maxDD={mdd:.2f}%) — still smooth"
    # the dip arrives WITH the stress, never before it (the mark is driven by the real regime flip)
    assert trough is not None
    assert trough >= dates[_FLIP_DAY - 1], f"{sid} trough {trough} predates the real event flip"


def test_realized_drawdowns_populated_and_provenance_stamped(tmp_path):
    """The realized_drawdowns timeline is POPULATED with a dated episode, and the marked days carry
    the honest provenance stamp (realized_backtest_series), never a fabricated source."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    # a real per-day mark is stamped on the moved days (not on the anchor / safe-hold days)
    series = _series(tmp_path, "eth_directional")
    sources = {p.get("mtm_source") for p in series}
    assert "realized_backtest_series" in sources
    assert sources <= {"realized_backtest_series", None}  # only the honest stamp or "no mark"
    # the annual-contrast realized episodes are real, dated, signed-negative, with a recovery field
    doc = ac.build_annual_contrast(data_dir=tmp_path, stable_apy_pct=5.0, write=False,
                                   use_fixture_if_empty=False, now_iso="2026-06-30T00:00:00+00:00")
    direc = next(s for s in doc["strategies"] if s["strategy_id"] == "eth_directional")
    realized = direc["dated_drawdown_timeline"]["realized_drawdowns"]
    assert realized, "eth_directional must show a REAL dated realized drawdown"
    for e in realized:
        assert e["source"] == "realized_backtest_series"
        assert e["depth_pct"] < 0.0
        assert e["peak_date"] <= e["trough_date"]
        assert "time_to_recover_days" in e


# ════════════════════════════════════════════════════════════════════════════════════════════════
# RED-TEAM — the dip is the REAL data, not a stamped number; absent path → no fake; stable stays flat
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_dip_tracks_the_real_path_not_a_hardcoded_number(tmp_path):
    """RED-TEAM: feed TWO different real ETH-crash magnitudes; the realized trough depth MUST differ
    (a hardcoded −X% stamped on the date would be identical regardless of the data)."""
    mild, dates = _stress_feeds(eth_low=2700.0)     # a −10% ETH move
    severe, _ = _stress_feeds(eth_low=2100.0)       # a −30% ETH move
    a = tmp_path / "mild"
    b = tmp_path / "severe"
    run_backtest(mild, dates[0], dates[-1], state_dir=a, verify_isolation=False)
    run_backtest(severe, dates[0], dates[-1], state_dir=b, verify_isolation=False)
    dd_mild, _ = _max_dd_and_trough(_series(a, "eth_directional"))
    dd_severe, _ = _max_dd_and_trough(_series(b, "eth_directional"))
    # the bigger REAL crash → the bigger realized dip (the dip is the data, not a constant)
    assert dd_severe > dd_mild + 5.0, (
        f"realized dip did not track the real path (mild={dd_mild:.2f}% severe={dd_severe:.2f}%)")


def test_no_real_path_means_no_fabricated_realized_dip(tmp_path):
    """RED-TEAM: points_farm (incentive_decay) has NO real per-day price path — its realized equity
    must NOT show a fabricated dip; the tail belongs in the labelled modeled overlay instead."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    series = _series(tmp_path, "points_farm")
    mdd, _ = _max_dd_and_trough(series)
    assert mdd < 0.5, f"points_farm fabricated a realized dip (maxDD={mdd:.2f}%) — must stay smooth"
    # every point is a pure-accrual day (no real mark path) — provenance honestly None
    assert all(p.get("mtm_source") is None for p in series)
    doc = ac.build_annual_contrast(data_dir=tmp_path, stable_apy_pct=5.0, write=False,
                                   use_fixture_if_empty=False, now_iso="2026-06-30T00:00:00+00:00")
    pf = next(s for s in doc["strategies"] if s["strategy_id"] == "points_farm")
    ddt = pf["dated_drawdown_timeline"]
    assert ddt["realized_drawdowns"] == []                 # NO fabricated real dip
    assert ddt["dated_stress_overlay"], "the tail must still surface via the labelled MODELED overlay"
    for o in ddt["dated_stress_overlay"]:
        assert o["source"] == "modeled_stress_overlay"


def test_stable_book_stays_flat_no_inherited_dip(tmp_path):
    """RED-TEAM: the steady ~5% book's real path had no such event — its max-DD must stay ~0 in every
    window (it must NEVER inherit the aggressive side's dip)."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    doc = ac.build_annual_contrast(data_dir=tmp_path, stable_apy_pct=5.0, write=False,
                                   use_fixture_if_empty=False, now_iso="2026-06-30T00:00:00+00:00")
    for st in doc["strategies"]:
        for w in st["windows"]:
            assert w["stable"]["max_drawdown_pct"] == 0.0, (
                f"stable book inherited a dip in {st['strategy_id']}/{w['window']}")
            assert w["stable"]["days_underwater"] == 0


def test_missing_mark_feed_is_honest_gap_no_fabricated_advance(tmp_path):
    """fail-CLOSED: a depeg book whose required LRT-ratio mark feed is ABSENT must NOT advance the
    equity that tick (no fabricated accrual, no smooth-fake, no fake dip) — an honest GAP. The book
    holds at its starting notional and resumes when the real path returns (not a permanent death)."""
    from spa_core.strategy_lab.aggressive_lab import DEFAULT_NOTIONAL_USD, roster
    # lrt_neutral needs lrt_ratio[eeth]; omit the ratio series entirely (present restaking, no ratio)
    d0 = _EVENT.isoformat()
    feeds = AggressiveFeeds(
        susde_apy_series={d0: 0.11}, pt_susde_series={d0: 0.12}, funding_series={d0: 0.0001},
        restaking_series={"eeth": {d0: 0.032}},   # has restaking but NO lrt_ratio (mark feed absent)
    )
    snap = feeds.build_live_snapshot(d0)
    s = roster.build_roster()["lrt_neutral"]
    s.step(snap)
    # honest GAP: equity UNCHANGED (no fabricated accrual/dip), no mark stamped this tick
    assert s.equity() == pytest.approx(DEFAULT_NOTIONAL_USD)
    assert s.metrics().extra["mtm_source"] is None
    # and a missing ACCRUAL feed (the yield source itself) for a strict book still KILLS (susde_spot)
    empty = AggressiveFeeds(eth_price_series={d0: 3000.0}, enable_points=False)
    ss = roster.build_roster()["susde_spot"]
    ss.step(empty.build_live_snapshot(d0))
    assert ss.metrics().extra["killed"] is True
    assert "fail-closed" in ss.metrics().extra["kill_reason"]
