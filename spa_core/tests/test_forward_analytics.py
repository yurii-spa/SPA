"""
Tests for spa_core/strategy_lab/forward_analytics.py — risk-adjusted analytics on the LIVE
forward series (rates-desk FixedCarry + Strategy-Lab sleeves).

These pin the HONESTY contract that makes the forward tracks fundable evidence at day 30:
  T4
    - a synthetic series with KNOWN stats → correct ann return / max-DD / vol / Sharpe / Sortino,
    - attribution vs the RWA floor: a series beating the floor → positive excess + beats_floor,
      a series below the floor → negative excess + below verdict,
    - INSUFFICIENT history (< MIN_POINTS_FOR_RATIO) → Sharpe/Sortino = "UNKNOWN" (NEVER a
      fabricated/degenerate number), but the well-defined return/DD/vol are still reported,
    - a LOCKED-VOL (fixed-rate accrual) track with enough points → Sharpe = "UNKNOWN" + locked_vol
      flag (the documented degenerate-Sharpe hazard, never a ~4.5e8 artifact),
    - fail-CLOSED: a GAPPED / DUPLICATE / malformed series → integrity not-ok → verdict UNKNOWN,
      with NO computed metrics.
  T5
    - the stress overlay applies each canonical scenario to a held PT book → per-scenario DD,
    - a small held book survives within the band; a large held book breaches it → survives False,
    - a cash-only book (no held notional) → $0 shock → 0% stress DD (honest, not fabricated loss).
  aggregate
    - build_scorecard over fixtures aggregates + writes the scorecard file (to the scanned tmp dir).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math

import pytest

from spa_core.strategy_lab import forward_analytics as fa


_FLOOR = 3.4  # pin the RWA floor for deterministic attribution tests (no live network dependency)


def _day(offset: int) -> str:
    base = datetime.date(2026, 6, 1)
    return (base + datetime.timedelta(days=offset)).isoformat()


def _series(equities, *, id_="t"):
    """Build a clean continuous on-disk series doc from a list of equity values."""
    return {
        "id": id_,
        "series": [
            {"date": _day(i), "ts": f"{_day(i)}T00:00:00+00:00", "equity_usd": float(e)}
            for i, e in enumerate(equities)
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# T4 — known-stats correctness
# ──────────────────────────────────────────────────────────────────────────────
def test_known_stats_growing_series():
    """A monotonic compounding series (8 points) → positive ann return, ~0 DD, finite Sharpe."""
    eq = [100000.0]
    for _ in range(7):
        eq.append(eq[-1] * 1.0003)  # ~0.03%/day, mild jitter-free compounding
    # add a touch of real dispersion so vol/Sharpe are finite & honest (not locked-vol)
    eq = [100000.0, 100040.0, 100020.0, 100075.0, 100060.0, 100120.0, 100100.0, 100170.0]
    card = fa.analyze_track(_series(eq), name="grow", floor_apy_pct=_FLOOR)

    assert card["integrity_ok"] is True
    assert card["integrity_reason"] == "ok"
    assert card["n_points"] == 8
    # ann return well-defined and positive (monotone-ish up)
    assert card["ann_return_pct"] is not None and card["ann_return_pct"] > 0
    # enough points → Sharpe should be a real finite number (genuine dispersion present)
    assert isinstance(card["sharpe"], (int, float))
    assert math.isfinite(card["sharpe"])
    assert isinstance(card["sortino"], (int, float)) or card["sortino"] == "UNKNOWN"
    # max-dd matches the metrics primitive
    from spa_core.strategy_lab import metrics
    assert card["max_dd_pct"] == metrics.max_drawdown_pct(eq)
    assert card["ann_return_pct"] == metrics.net_apy_from_equity(eq)


def test_max_drawdown_known_value():
    """A series with a clean 5% peak-to-trough → max_dd_pct == 5.0."""
    eq = [100.0, 105.0, 99.75, 102.0, 108.0, 110.0, 109.0, 111.0]  # trough 99.75 vs peak 105 = 5%
    card = fa.analyze_track(_series(eq), name="dd", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is True
    assert card["max_dd_pct"] == pytest.approx(5.0, abs=1e-6)


# ──────────────────────────────────────────────────────────────────────────────
# T4 — attribution vs the RWA floor
# ──────────────────────────────────────────────────────────────────────────────
def test_beats_floor_positive_excess():
    """A series whose annualized return clears the floor → positive excess + BEATS_FLOOR."""
    # ~0.05%/day with jitter → ~20% annualized, comfortably above a 3.4% floor.
    eq = [100000.0, 100060.0, 100040.0, 100110.0, 100150.0, 100210.0, 100200.0, 100280.0]
    card = fa.analyze_track(_series(eq), name="beat", floor_apy_pct=_FLOOR)
    assert card["ann_return_pct"] > _FLOOR
    assert card["excess_vs_floor_pct"] > 0
    assert card["attribution"]["beats_floor"] is True
    assert card["attribution"]["floor_leg_pct"] == pytest.approx(_FLOOR)
    assert card["attribution"]["excess_carry_pct"] == card["excess_vs_floor_pct"]
    # excess = realized - floor exactly
    assert card["excess_vs_floor_pct"] == pytest.approx(
        round(card["ann_return_pct"] - _FLOOR, 4)
    )
    assert card["verdict"] == "BEATS_FLOOR"


def test_below_floor_negative_excess():
    """A flat-to-declining series → return below the floor → negative excess + BELOW_FLOOR."""
    eq = [100000.0, 99990.0, 99995.0, 99980.0, 99985.0, 99970.0, 99975.0, 99960.0]
    card = fa.analyze_track(_series(eq), name="below", floor_apy_pct=_FLOOR)
    assert card["ann_return_pct"] < _FLOOR
    assert card["excess_vs_floor_pct"] < 0
    assert card["attribution"]["beats_floor"] is False
    assert card["verdict"] == "BELOW_FLOOR"


# ──────────────────────────────────────────────────────────────────────────────
# T4 — honest insufficient-history handling
# ──────────────────────────────────────────────────────────────────────────────
def test_thin_track_sharpe_unknown_not_fabricated():
    """Fewer than MIN_POINTS_FOR_RATIO points → Sharpe/Sortino = UNKNOWN, NEVER a number."""
    eq = [100000.0, 100020.0, 100010.0]  # 3 points < 7
    card = fa.analyze_track(_series(eq), name="thin", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is True
    assert card["sharpe"] == "UNKNOWN"
    assert card["sortino"] == "UNKNOWN"
    assert card["verdict"] == "THIN_TRACK"
    # but the well-defined stats ARE reported (return/DD/vol are honest from ≥2 points)
    assert card["ann_return_pct"] is not None
    assert card["max_dd_pct"] is not None
    assert card["excess_vs_floor_pct"] is not None
    # Q2-17 countdown: 3 points → 4 more to the first (7) verdict, 17 more to the robust (20) one
    assert card["days_to_first_verdict"] == fa.MIN_POINTS_FOR_RATIO - 3
    assert card["days_to_robust_verdict"] == fa.MIN_POINTS_FOR_DSR - 3
    assert card["verdict_depth_thresholds"] == {
        "first": fa.MIN_POINTS_FOR_RATIO, "robust": fa.MIN_POINTS_FOR_DSR}


def test_days_to_verdict_zero_once_depth_reached():
    """Q2-17: once the track has ≥ MIN_POINTS_FOR_RATIO points the first-verdict countdown is 0
    (a verdict is now computable); the robust countdown keeps ticking down to 0 at MIN_POINTS_FOR_DSR."""
    eq = [100000.0 * (1.001 ** i) for i in range(fa.MIN_POINTS_FOR_RATIO + 1)]
    card = fa.analyze_track(_series(eq), name="mid", floor_apy_pct=_FLOOR)
    assert card["days_to_first_verdict"] == 0
    assert card["days_to_robust_verdict"] == max(0, fa.MIN_POINTS_FOR_DSR - len(eq))
    # deep enough for the robust block too → both zero
    eq2 = [100000.0 * (1.001 ** i) for i in range(fa.MIN_POINTS_FOR_DSR + 2)]
    card2 = fa.analyze_track(_series(eq2), name="deep", floor_apy_pct=_FLOOR)
    assert card2["days_to_first_verdict"] == 0
    assert card2["days_to_robust_verdict"] == 0


def test_thin_track_never_emits_degenerate_sharpe():
    """Even a thin series with tiny dispersion must NOT surface a giant finite Sharpe."""
    eq = [100000.0, 100001.0, 100002.0]  # locked-ish + thin
    card = fa.analyze_track(_series(eq), name="thin2", floor_apy_pct=_FLOOR)
    assert card["sharpe"] == "UNKNOWN"  # never 4.5e8


def test_locked_vol_flagged_unknown():
    """A fixed-rate accrual with ENOUGH points → locked_vol flag + Sharpe UNKNOWN (degenerate
    hazard), never a fabricated ~4.5e8 Sharpe."""
    # exact constant daily growth factor → variance is float-noise only → metrics.sharpe()=None
    eq = [100000.0]
    for _ in range(9):
        eq.append(eq[-1] * 1.0001)  # 10 points, ≥ MIN_POINTS_FOR_RATIO
    card = fa.analyze_track(_series(eq), name="locked", floor_apy_pct=_FLOOR)
    assert card["n_points"] >= fa.MIN_POINTS_FOR_RATIO
    assert card["sharpe"] == "UNKNOWN"
    assert card["locked_vol"] is True
    # return is still honest & positive (a fixed accrual earns), attribution still computed
    assert card["ann_return_pct"] is not None and card["ann_return_pct"] > 0


# ──────────────────────────────────────────────────────────────────────────────
# T4 — fail-CLOSED on broken series
# ──────────────────────────────────────────────────────────────────────────────
def test_gapped_series_fails_closed_unknown():
    doc = _series([100000.0, 100010.0, 100020.0, 100030.0, 100040.0, 100050.0, 100060.0])
    # punch a gap: drop the 3rd point's date forward by 3 days (missing days)
    doc["series"][3]["date"] = _day(6)  # creates a gap between idx2 (_day2) and idx3 (_day6)
    # keep the rest in order to isolate the gap
    for i in range(4, len(doc["series"])):
        doc["series"][i]["date"] = _day(6 + (i - 3))
    card = fa.analyze_track(doc, name="gap", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is False
    assert card["integrity_reason"] == "gaps"
    assert card["verdict"] == "UNKNOWN"
    # NO fabricated metrics on a broken track
    assert card["ann_return_pct"] is None
    assert card["sharpe"] == "UNKNOWN"


def test_duplicate_date_fails_closed():
    doc = _series([100000.0, 100010.0, 100020.0])
    doc["series"][2]["date"] = doc["series"][1]["date"]  # duplicate
    card = fa.analyze_track(doc, name="dup", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is False
    assert card["integrity_reason"] == "duplicates"
    assert card["verdict"] == "UNKNOWN"


def test_malformed_series_fails_closed():
    card = fa.analyze_track({"id": "x", "series": "not-a-list"}, name="bad", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is False
    assert card["verdict"] == "UNKNOWN"


def test_missing_equity_fails_closed():
    """A point with no numeric equity_usd → malformed → UNKNOWN, never equity=0 fabricated."""
    doc = _series([100000.0, 100010.0, 100020.0])
    del doc["series"][1]["equity_usd"]
    card = fa.analyze_track(doc, name="noeq", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is False
    assert "malformed" in card["integrity_reason"]
    assert card["verdict"] == "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────────────
# T5 — stress overlay on the realized forward record
# ──────────────────────────────────────────────────────────────────────────────
def test_stress_overlay_per_scenario_dd():
    """Each canonical scenario produces a stress DD = held_notional × markdown / equity (peak)."""
    realized = [100000.0, 100002.0, 100004.0]  # mild realized track
    held = 15000.0   # ~$15k PT held
    cur = 100004.0
    ov = fa.stress_overlay(realized, held, cur)
    assert len(ov["scenarios"]) == len(fa.STRESS_SCENARIOS)
    for sc in ov["scenarios"]:
        # shock = held * markdown; the shocked point drops below the realized peak
        expected_shock = held * sc["pt_markdown_pct"] / 100.0
        assert sc["shock_usd"] == pytest.approx(round(expected_shock, 2))
        # DD = (peak - trough)/peak where trough = cur - shock; peak = max(realized, cur)
        peak = max(realized)
        trough = cur - expected_shock
        expected_dd = round((peak - trough) / peak * 100.0, 4)
        assert sc["stress_dd_pct"] == pytest.approx(expected_dd, abs=1e-3)
    assert ov["held_pt_notional_usd"] == pytest.approx(held)


def test_stress_overlay_small_book_survives():
    """A small held book → DD within the 15% band → survives."""
    ov = fa.stress_overlay([100000.0, 100005.0], 14546.0, 100005.0)
    assert ov["survives_all"] is True
    assert all(s["survives"] for s in ov["scenarios"])
    assert ov["worst_stress_dd_pct"] <= fa.MAX_DD_BAND_PCT


def test_stress_overlay_large_book_breaches_band():
    """A very large held PT book under the worst markdown → DD exceeds the band → survives False."""
    # held big enough that 6% markdown blows past 15% of equity
    ov = fa.stress_overlay([100000.0], 300000.0, 100000.0)
    assert ov["survives_all"] is False
    worst = [s for s in ov["scenarios"] if s["pt_markdown_pct"] == 6.0][0]
    assert worst["survives"] is False
    assert worst["stress_dd_pct"] > fa.MAX_DD_BAND_PCT


def test_stress_overlay_cash_only_no_loss():
    """No held PT notional → $0 shock → 0% stress DD (honest cash book, not a fabricated loss)."""
    ov = fa.stress_overlay([100000.0, 100003.0], 0.0, 100003.0)
    for s in ov["scenarios"]:
        assert s["shock_usd"] == 0.0
        assert s["stress_dd_pct"] == 0.0
        assert s["survives"] is True
    assert ov["survives_all"] is True


def test_held_pt_notional_extraction():
    """The held-notional extractor sums open-book sizes + computes book equity from the state."""
    state = {
        "state": {
            "capital": "100000.0",
            "cash": "85000.0",
            "accrued": "5.0",
            "books": {
                "a": {"size": "7000.0"},
                "b": {"size": "8000.0"},
                "c": {"size": "0"},  # closed → not counted
            },
        }
    }
    held, equity, n_open = fa._held_pt_notional(state)
    assert held == pytest.approx(15000.0)
    assert n_open == 2
    assert equity == pytest.approx(85000.0 + 15000.0 + 5.0)


def test_held_pt_notional_failclosed_on_bad_shape():
    assert fa._held_pt_notional("nope") == (0.0, 0.0, 0)
    assert fa._held_pt_notional({"state": "bad"}) == (0.0, 0.0, 0)


# ──────────────────────────────────────────────────────────────────────────────
# aggregate — build_scorecard over fixtures + atomic write
# ──────────────────────────────────────────────────────────────────────────────
def _write_series(dir_, name, equities):
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{name}_series.json").write_text(json.dumps(_series(equities, id_=name)))


def test_build_scorecard_aggregates_and_writes(tmp_path, monkeypatch):
    # pin the floor (avoid live network) for deterministic attribution
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)

    rates_dir = tmp_path / "rates_desk" / "paper"
    lab_dir = tmp_path / "strategy_lab_paper"
    # a thin carry track + a clean lab track
    _write_series(rates_dir, "rates_desk_fixed_carry",
                  [100000.0, 100001.85, 100003.69])  # thin (3 pts) → THIN_TRACK
    _write_series(lab_dir, "engine_a",
                  [100000.0, 100012.0, 100024.0, 100033.0, 100043.0, 100050.0, 100060.0, 100070.0])

    # a carry STATE so the stress overlay has a held book
    (rates_dir / "rates_desk_fixed_carry_state.json").write_text(json.dumps({
        "state": {"capital": "100000.0", "cash": "85454.0", "accrued": "3.69",
                  "books": {"x": {"size": "7634.0"}, "y": {"size": "6911.0"}}}
    }))

    rep = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=True)

    assert rep["n_tracks"] == 2
    assert rep["rwa_floor_apy_pct"] == pytest.approx(_FLOOR)
    names = {t["name"] for t in rep["tracks"]}
    assert "paper/rates_desk_fixed_carry" in names
    assert "strategy_lab_paper/engine_a" in names

    # the carry track is thin → THIN_TRACK, Sharpe UNKNOWN
    carry = [t for t in rep["tracks"] if t["name"].endswith("rates_desk_fixed_carry")][0]
    assert carry["verdict"] == "THIN_TRACK"
    assert carry["sharpe"] == "UNKNOWN"

    # the stress overlay is attached + reflects the held book (~$14545 notional)
    ov = rep["carry_book_stress_overlay"]
    assert ov["held_pt_notional_usd"] == pytest.approx(7634.0 + 6911.0)
    assert ov["n_open_books"] == 2
    assert len(ov["scenarios"]) == len(fa.STRESS_SCENARIOS)

    # the scorecard file was written atomically into the SCANNED dir (not the live data/)
    written = tmp_path / "forward_analytics.json"
    assert written.exists()
    on_disk = json.loads(written.read_text())
    assert on_disk["n_tracks"] == 2


def test_build_scorecard_unreadable_file_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)
    rates_dir = tmp_path / "rates_desk" / "paper"
    rates_dir.mkdir(parents=True, exist_ok=True)
    (rates_dir / "broken_series.json").write_text("{ not json ")
    rep = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=False)
    broken = [t for t in rep["tracks"] if t["name"].endswith("broken")][0]
    assert broken["integrity_ok"] is False
    assert broken["verdict"] == "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────────────
# D3-T2 — non-finite safety on the forward analytics (NaN / inf / zero-var / single)
# ──────────────────────────────────────────────────────────────────────────────
_INF = float("inf")
_NAN = float("nan")


def _card_has_no_nonfinite(card: dict) -> bool:
    """No numeric field in a per-track scorecard may be a leaked NaN/inf."""
    for v in card.values():
        if isinstance(v, float) and not math.isfinite(v):
            return False
        if isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, float) and not math.isfinite(vv):
                    return False
    return True


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF])
def test_nonfinite_equity_point_fails_closed(bad):
    """A NaN/inf equity_usd is a CORRUPT point → integrity not-ok → verdict UNKNOWN, never a
    leaked NaN/inf metric (isinstance(nan, float) is True, so it must be explicitly rejected)."""
    doc = _series([100000.0, 100010.0, 100020.0, 100030.0, 100040.0, 100050.0, 100060.0])
    doc["series"][3]["equity_usd"] = bad
    card = fa.analyze_track(doc, name="badeq", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is False
    assert "malformed" in card["integrity_reason"]
    assert card["verdict"] == "UNKNOWN"
    assert card["ann_return_pct"] is None
    assert card["sharpe"] == "UNKNOWN"
    assert _card_has_no_nonfinite(card)


def test_all_nonfinite_series_never_leaks_nan():
    """Even an all-NaN / all-inf series must fail closed to UNKNOWN, never serialize NaN."""
    for bad in (_NAN, _INF):
        doc = _series([bad] * 8)
        card = fa.analyze_track(doc, name="allbad", floor_apy_pct=_FLOOR)
        assert card["verdict"] == "UNKNOWN"
        assert _card_has_no_nonfinite(card)


def test_zero_variance_track_no_nan_and_unknown_sharpe():
    """A perfectly flat track (zero variance) → finite return/DD/vol, Sharpe UNKNOWN, no NaN."""
    doc = _series([100000.0] * 8)  # exactly flat → zero variance
    card = fa.analyze_track(doc, name="flat", floor_apy_pct=_FLOOR)
    assert card["integrity_ok"] is True
    assert card["sharpe"] == "UNKNOWN"        # locked/zero-vol → undefined, never a number
    assert _card_has_no_nonfinite(card)
    # the well-defined stats are finite numbers
    assert isinstance(card["ann_return_pct"], (int, float)) and math.isfinite(card["ann_return_pct"])
    assert isinstance(card["max_dd_pct"], (int, float)) and math.isfinite(card["max_dd_pct"])
    assert isinstance(card["rolling_vol_pct"], (int, float)) and math.isfinite(card["rolling_vol_pct"])


def test_single_point_track_unknown_never_nan():
    """A single-point track has no return → THIN/UNKNOWN, never a NaN metric."""
    doc = _series([100000.0])
    card = fa.analyze_track(doc, name="one", floor_apy_pct=_FLOOR)
    assert card["sharpe"] == "UNKNOWN"
    assert card["sortino"] == "UNKNOWN"
    assert _card_has_no_nonfinite(card)


def test_stress_overlay_nonfinite_state_fails_closed():
    """A NaN/inf in the carry STATE must not poison the stress overlay into NaN shocks."""
    for bad in ("nan", "inf", "-inf"):
        held, equity, n_open = fa._held_pt_notional(
            {"state": {"capital": "100000.0", "cash": "85000.0", "accrued": "5.0",
                       "books": {"a": {"size": bad}, "b": {"size": "8000.0"}}}}
        )
        # the corrupt book is skipped, the good one still counted; nothing non-finite
        assert math.isfinite(held) and math.isfinite(equity)
        assert held == pytest.approx(8000.0)
        assert n_open == 1
    # a non-finite top-level capital/cash fails the whole extraction closed
    held, equity, n_open = fa._held_pt_notional(
        {"state": {"capital": "inf", "cash": "1.0", "accrued": "0.0", "books": {}}}
    )
    assert (held, equity, n_open) == (0.0, 0.0, 0)


def test_stress_overlay_output_always_finite():
    """The stress overlay never emits a NaN/inf stress DD even from a degenerate equity base."""
    ov = fa.stress_overlay([100000.0, 100005.0], 14546.0, 100005.0)
    assert math.isfinite(ov["worst_stress_dd_pct"])
    for sc in ov["scenarios"]:
        assert math.isfinite(sc["stress_dd_pct"])
        assert math.isfinite(sc["shock_usd"])


# ──────────────────────────────────────────────────────────────────────────────
# D3-T2 — determinism: byte-stable scorecard regen from FIXED inputs
# ──────────────────────────────────────────────────────────────────────────────
def _seed_forward_fixture(tmp_path):
    rates_dir = tmp_path / "rates_desk" / "paper"
    lab_dir = tmp_path / "strategy_lab_paper"
    _write_series(rates_dir, "rates_desk_fixed_carry",
                  [100000.0, 100001.85, 100003.69])
    _write_series(lab_dir, "engine_a",
                  [100000.0, 100012.0, 100024.0, 100033.0, 100043.0, 100050.0, 100060.0, 100070.0])
    (rates_dir / "rates_desk_fixed_carry_state.json").write_text(json.dumps({
        "state": {"capital": "100000.0", "cash": "85454.0", "accrued": "3.69",
                  "books": {"x": {"size": "7634.0"}, "y": {"size": "6911.0"}}}
    }))


def test_scorecard_byte_stable_from_fixed_inputs(tmp_path, monkeypatch):
    """Regenerating the scorecard from FIXED inputs (with an injected timestamp) is byte-stable
    across repeated runs — no dict-ordering / float-format / wall-clock drift."""
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)
    _seed_forward_fixture(tmp_path)
    fixed_ts = "2026-06-27T00:00:00+00:00"
    runs = []
    for _ in range(3):
        fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=True, now_iso=fixed_ts)
        runs.append((tmp_path / "forward_analytics.json").read_bytes())
    assert runs[0] == runs[1] == runs[2]


def test_scorecard_only_timestamp_varies(tmp_path, monkeypatch):
    """The ONLY field that may differ between two live regenerations is generated_at; injecting
    the same timestamp makes the dicts equal (proves no other hidden non-determinism)."""
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)
    _seed_forward_fixture(tmp_path)
    a = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=False, now_iso="A")
    b = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=False, now_iso="B")
    a.pop("generated_at"); b.pop("generated_at")
    assert a == b
    # with the SAME injected stamp the full docs are identical
    c = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=False, now_iso="A")
    d = fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=False, now_iso="A")
    assert c == d
