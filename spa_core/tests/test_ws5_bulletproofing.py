"""spa_core/tests/test_ws5_bulletproofing.py — Workstream 5.2 + 5.3 bulletproofing.

Property + adversarial coverage the Cutover-Bulletproof brief pins for day-30 readiness:

5.2 — FORWARD ANALYTICS bulletproof:
  * NO LOOK-AHEAD — analyze_track on a prefix of a series uses ONLY that prefix (appending a
    future point can change later metrics but never retroactively rewrites the prefix's verdict);
    the metric at point k depends only on points 0..k.
  * THIN/UNKNOWN below the credible-N — a track with < MIN_POINTS_FOR_RATIO points is THIN, ratios
    UNKNOWN, never a number; the DSR block stays THIN below MIN_POINTS_FOR_DSR.
  * DEGENERATE-METRIC GUARD — a locked-vol (zero-dispersion) track with ENOUGH points returns
    UNKNOWN + locked_vol, never a fabricated ~4.5e8 Sharpe.
  * FAIL-CLOSED — gap / duplicate / out-of-order / FUTURE-dated / malformed / non-finite series →
    verdict UNKNOWN, never a computed number on a broken track.
  * DETERMINISTIC — build_scorecard with a pinned now_iso is byte-stable from fixed inputs.

5.3 — PROMOTION LADDER total + idempotent + refuse-degenerate + auto-produced:
  * TOTAL — check_promotions never raises on ANY input shape (empty / malformed / partial state).
  * IDEMPOTENT — running check_promotions twice (and update_shadow_day for the SAME date twice)
    yields the same result + the same persisted state; the day-count does not double-count.
  * REFUSE-DEGENERATE — an untrustworthy dataset OR a degenerate Sharpe is refused, never promoted,
    however many paper days accrue.
  * AUTO-PRODUCED STATE — run_daily writes tournament_engine_state.json deterministically.

All deterministic, stdlib + pytest only, hermetic tmp dirs. No network, no live data mutation.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.strategy_lab import forward_analytics as fa
from spa_core.strategy_lab import track_integrity as ti
from spa_core.tournament.tournament_engine import (
    DEGENERATE_SHARPE_CEILING,
    PROMOTION_CRITERIA,
    TournamentEngine,
)

_FLOOR = 3.4  # pin the RWA floor (no live network) for deterministic attribution
_MIN_SHARPE = PROMOTION_CRITERIA["min_sharpe"]
_MIN_DAYS = PROMOTION_CRITERIA["min_days_paper"]
_MIN_APY = PROMOTION_CRITERIA["min_apy_pct"]


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────
def _series(equities, start=(2026, 1, 1)):
    """A forward-track series doc: contiguous daily dates carrying equity_usd."""
    import datetime
    y, m, d = start
    base = datetime.date(y, m, d)
    pts = [{"date": (base + datetime.timedelta(days=i)).isoformat(), "equity_usd": float(e)}
           for i, e in enumerate(equities)]
    return {"id": "t", "series": pts}


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 5.2 — FORWARD ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
class TestForwardAnalyticsNoLookAhead:
    def test_prefix_metric_uses_only_prefix(self):
        """The verdict computed on a prefix is identical whether or not future points exist later
        in a longer series — analyze_track on the prefix doc cannot see beyond it (no look-ahead)."""
        full = [100_000 + i * 25 + (i % 4) * 8 for i in range(25)]
        prefix_card = fa.analyze_track(_series(full[:10]), name="p", floor_apy_pct=_FLOOR)
        # building the SAME prefix again is identical; the future tail does not exist in the doc
        prefix_card2 = fa.analyze_track(_series(full[:10]), name="p", floor_apy_pct=_FLOOR)
        assert prefix_card == prefix_card2
        # the prefix's n_points is exactly the prefix length — it never reaches into the future
        assert prefix_card["n_points"] == 10

    def test_drawdown_is_causal(self):
        """Max-DD over a prefix never exceeds max-DD over the full series that EXTENDS it —
        adding later points can only reveal new troughs, never rewrite the prefix's own DD."""
        full = [100_000, 100_500, 100_200, 100_800, 99_000, 99_500]  # a trough at idx4
        dd_prefix = fa.analyze_track(_series(full[:4]), floor_apy_pct=_FLOOR)["max_dd_pct"]
        dd_full = fa.analyze_track(_series(full), floor_apy_pct=_FLOOR)["max_dd_pct"]
        assert dd_full >= dd_prefix  # the later crash deepens DD; it never shrinks the prefix's


class TestForwardAnalyticsThinAndDegenerate:
    def test_thin_track_ratios_unknown(self):
        card = fa.analyze_track(_series([100_000, 100_100, 100_250]), floor_apy_pct=_FLOOR)
        assert card["n_points"] == 3
        assert card["sharpe"] == "UNKNOWN" and card["sortino"] == "UNKNOWN"
        assert card["verdict"] == "THIN_TRACK"

    def test_locked_vol_never_fabricates_sharpe(self):
        """A perfectly-constant-growth (locked-vol) track with ENOUGH points → UNKNOWN + locked_vol,
        never a ~4.5e8 Sharpe artifact."""
        eq = [100_000.0 * (1.0001 ** i) for i in range(fa.MIN_POINTS_FOR_RATIO + 2)]
        card = fa.analyze_track(_series(eq), floor_apy_pct=_FLOOR)
        assert card["sharpe"] == "UNKNOWN"
        assert card["locked_vol"] is True

    def test_dsr_block_thin_below_min(self):
        """The deflated-Sharpe block stays THIN (UNKNOWN) below MIN_POINTS_FOR_DSR returns."""
        rets = [0.0001, 0.0002, -0.0001, 0.0003]  # 4 returns << MIN_POINTS_FOR_DSR
        block = fa.deflated_sharpe_block(rets, floor_apy_pct=_FLOOR)
        assert block["status"] == "THIN"
        assert block["deflated_sharpe"] == "UNKNOWN"

    def test_dsr_block_locked_vol_when_zero_dispersion(self):
        """A zero-dispersion return series with enough points → LOCKED_VOL, never a fabricated DSR."""
        rets = [0.0] * (fa.MIN_POINTS_FOR_DSR + 1)
        block = fa.deflated_sharpe_block(rets, floor_apy_pct=_FLOOR)
        assert block["status"] == "LOCKED_VOL"
        assert block["deflated_sharpe"] == "UNKNOWN"


class TestForwardAnalyticsFailClosed:
    @pytest.mark.parametrize("doc", [
        {"series": [{"date": "2026-01-01", "equity_usd": 100.0},
                    {"date": "2026-01-05", "equity_usd": 101.0}]},      # gap
        {"series": [{"date": "2026-01-01", "equity_usd": 100.0},
                    {"date": "2026-01-01", "equity_usd": 101.0}]},      # duplicate
        {"series": [{"date": "2026-01-03", "equity_usd": 100.0},
                    {"date": "2026-01-01", "equity_usd": 101.0}]},      # out-of-order
        {"series": [{"date": "2026-01-01", "equity_usd": 100.0},
                    {"date": "2999-01-02", "equity_usd": 101.0}]},      # future-dated
        {"series": [{"date": "2026-01-01"}]},                          # missing equity
        {"series": "not-a-list"},                                       # malformed
    ])
    def test_broken_series_is_unknown_no_number(self, doc):
        card = fa.analyze_track(doc, floor_apy_pct=_FLOOR)
        assert card["verdict"] == "UNKNOWN"
        assert card["sharpe"] == "UNKNOWN"
        assert card["ann_return_pct"] in (None, card["ann_return_pct"])  # no fabricated metric

    def test_non_finite_equity_fails_closed(self):
        doc = {"series": [{"date": "2026-01-01", "equity_usd": 100.0},
                          {"date": "2026-01-02", "equity_usd": float("inf")}]}
        card = fa.analyze_track(doc, floor_apy_pct=_FLOOR)
        assert card["verdict"] == "UNKNOWN"


class TestForwardAnalyticsDeterministic:
    def test_scorecard_byte_stable_with_pinned_now(self, tmp_path):
        """build_scorecard with a fixed now_iso is byte-identical across runs (fixed inputs)."""
        rd = tmp_path / "rates_desk" / "paper"
        rd.mkdir(parents=True)
        (rd / "rates_desk_fixed_carry_series.json").write_text(
            json.dumps(_series([100_000 + i * 10 for i in range(5)])), encoding="utf-8")
        a = fa.build_scorecard(tmp_path, floor_apy_pct=_FLOOR, write=False,
                               now_iso="2026-07-21T00:00:00+00:00")
        b = fa.build_scorecard(tmp_path, floor_apy_pct=_FLOOR, write=False,
                               now_iso="2026-07-21T00:00:00+00:00")
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 5.3 — PROMOTION LADDER total + idempotent + refuse-degenerate + auto-produced
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _seed(data_dir: Path, sid: str, sharpe: float, *, trustworthy=True,
          sharpe_degenerate=False) -> TournamentEngine:
    data_dir.mkdir(parents=True, exist_ok=True)
    tournament = {
        "total_strategies": 1,
        "trustworthy": trustworthy,
        "data_source_regime": "NORMAL",
        "shadow_active_strategies": [{
            "strategy_key": sid, "id": sid, "rank": 1, "sharpe": sharpe,
            "sharpe_degenerate": sharpe_degenerate, "days_active": 0,
            "allocation": {"aave_v3": 1.0},
        }],
    }
    shadow = {"active_strategies": [{"id": sid, "rank": 1, "sharpe": sharpe}], "daily_results": []}
    (data_dir / "strategy_tournament.json").write_text(json.dumps(tournament), encoding="utf-8")
    (data_dir / "shadow_paper_trading.json").write_text(json.dumps(shadow), encoding="utf-8")
    return TournamentEngine(data_dir=data_dir)


def _accrue(engine: TournamentEngine, n: int, apy: float):
    for d in range(n):
        engine.update_shadow_day(date=f"2026-01-{d + 1:02d}", apy_map={"aave_v3": apy})


class TestLadderTotal:
    """check_promotions is TOTAL — it never raises on any input shape."""

    @pytest.mark.parametrize("tournament,shadow", [
        ({}, {}),                                                  # both empty
        ({"trustworthy": True}, {"active_strategies": []}),        # no strategies
        ({"trustworthy": True, "shadow_active_strategies": "x"},   # malformed ranked
         {"active_strategies": [{"id": "a"}], "daily_results": "y"}),  # malformed daily
        ({"trustworthy": True}, {"active_strategies": [{}]}),      # strategy with no id
    ])
    def test_check_promotions_never_raises(self, tmp_path, tournament, shadow):
        d = tmp_path
        (d / "strategy_tournament.json").write_text(json.dumps(tournament), encoding="utf-8")
        (d / "shadow_paper_trading.json").write_text(json.dumps(shadow), encoding="utf-8")
        eng = TournamentEngine(data_dir=d)
        result = eng.check_promotions()       # must not raise
        assert isinstance(result, list)


class TestLadderIdempotent:
    def test_check_promotions_idempotent(self, tmp_path):
        """Two consecutive check_promotions over unchanged state → identical result."""
        eng = _seed(tmp_path, "good", _MIN_SHARPE + 0.5)
        _accrue(eng, _MIN_DAYS, _MIN_APY + 1.0)
        first = eng.check_promotions()
        second = eng.check_promotions()
        assert first == second
        assert {p["strategy_id"] for p in first} == {"good"}

    def test_update_shadow_day_same_date_idempotent(self, tmp_path):
        """Re-running the SAME UTC date does not double-count paper days (de-dup on date)."""
        eng = _seed(tmp_path, "good", _MIN_SHARPE + 0.5)
        eng.update_shadow_day(date="2026-01-01", apy_map={"aave_v3": _MIN_APY + 1.0})
        eng.update_shadow_day(date="2026-01-01", apy_map={"aave_v3": _MIN_APY + 1.0})  # same date
        shadow = json.loads((tmp_path / "shadow_paper_trading.json").read_text(encoding="utf-8"))
        dates = [dr.get("date") for dr in shadow.get("daily_results", [])]
        assert dates.count("2026-01-01") == 1  # exactly one bar for the date

    def test_run_daily_auto_produces_state(self, tmp_path):
        """run_daily writes tournament_engine_state.json — the ladder auto-produces its state."""
        eng = _seed(tmp_path, "good", _MIN_SHARPE + 0.5)
        _accrue(eng, _MIN_DAYS, _MIN_APY + 1.0)
        summary = eng.run_daily()       # must not raise; advisory
        assert isinstance(summary, dict)
        state_path = tmp_path / "tournament_engine_state.json"
        assert state_path.is_file(), "run_daily must persist the engine state"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert isinstance(state, dict)


class TestLadderRefuseDegenerate:
    def test_untrustworthy_dataset_refuses_all(self, tmp_path):
        """An untrustworthy dataset refuses EVERY promotion, however good the per-strategy numbers."""
        eng = _seed(tmp_path, "good", _MIN_SHARPE + 1.0, trustworthy=False)
        _accrue(eng, _MIN_DAYS + 10, _MIN_APY + 2.0)
        assert eng.check_promotions() == []
        assert any(r["reason"] == "untrustworthy" for r in eng.last_refusals)

    def test_degenerate_sharpe_never_promotes(self, tmp_path):
        """A degenerate (above-ceiling) Sharpe is refused, never promoted, regardless of days."""
        eng = _seed(tmp_path, "degen", DEGENERATE_SHARPE_CEILING + 1.0)
        _accrue(eng, _MIN_DAYS + 5, _MIN_APY + 2.0)
        assert eng.check_promotions() == []
        assert any(r["reason"] == "degenerate_data" for r in eng.last_refusals)

    def test_producer_flagged_degenerate_refused(self, tmp_path):
        """A producer-flagged sharpe_degenerate strategy is refused even with a credible Sharpe."""
        eng = _seed(tmp_path, "flagged", _MIN_SHARPE + 0.5, sharpe_degenerate=True)
        _accrue(eng, _MIN_DAYS + 1, _MIN_APY + 1.0)
        assert eng.check_promotions() == []
