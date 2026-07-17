#!/usr/bin/env python3
"""Regression tests for :mod:`spa_core.reporting._perf_common`.

This is the shared, pure-stdlib, read-only math FOUNDATION of the enhanced
reporting suite (MP-1236): the same helpers power ``performance_attributor``,
``tear_sheet_hf`` and ``benchmark_comparator`` — three public advisory reports.
A silent bug in any of these primitives (return-percent convention, warm-up
segment isolation, drawdown-vs-segment-peak, annualisation) would propagate
identically into all of them, so the invariants are pinned here directly.

Hermetic: every filesystem test writes under ``tmp_path``; no ``data/`` file
(including the live go-live track) is read or touched. Tests only — the module
under test is NOT modified (invariant #16).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spa_core.reporting import _perf_common as P


# --------------------------------------------------------------------------- #
# now_iso                                                                      #
# --------------------------------------------------------------------------- #
def test_now_iso_is_utc_isoformat():
    ts = P.now_iso()
    assert isinstance(ts, str) and "T" in ts
    # UTC offset present (either +00:00 or a Z-equivalent offset) — never naive.
    assert ("+00:00" in ts) or ts.endswith("Z") or "+" in ts[-6:]


# --------------------------------------------------------------------------- #
# read_json — defensive, never raises                                          #
# --------------------------------------------------------------------------- #
def test_read_json_missing_returns_default(tmp_path):
    missing = tmp_path / "nope.json"
    sentinel = {"x": 1}
    assert P.read_json(missing, default=sentinel) is sentinel


def test_read_json_corrupt_returns_default(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not: valid json,,", encoding="utf-8")
    assert P.read_json(bad, default=None) is None


def test_read_json_valid_roundtrip(tmp_path):
    good = tmp_path / "good.json"
    payload = {"a": [1, 2, 3], "b": "т"}  # non-ASCII survives
    good.write_text(json.dumps(payload), encoding="utf-8")
    assert P.read_json(good) == payload


def test_read_json_default_is_none_when_unspecified(tmp_path):
    assert P.read_json(tmp_path / "absent.json") is None


# --------------------------------------------------------------------------- #
# atomic_write_json — round-trips through the atomic helper                     #
# --------------------------------------------------------------------------- #
def test_atomic_write_json_roundtrip(tmp_path):
    out = tmp_path / "out.json"
    doc = {"meta": {"k": 1}, "list": [1, 2]}
    P.atomic_write_json(out, doc)
    assert out.exists()
    assert P.read_json(out) == doc


# --------------------------------------------------------------------------- #
# load_equity_curve — shape guards                                             #
# --------------------------------------------------------------------------- #
def _write_curve(data_dir: Path, doc) -> None:
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def test_load_equity_curve_missing_file_returns_empty(tmp_path):
    # No equity_curve_daily.json present at all.
    assert P.load_equity_curve(tmp_path) == []


def test_load_equity_curve_doc_not_dict_returns_empty(tmp_path):
    _write_curve(tmp_path, ["not", "a", "dict"])
    assert P.load_equity_curve(tmp_path) == []


def test_load_equity_curve_daily_not_list_returns_empty(tmp_path):
    _write_curve(tmp_path, {"daily": {"nope": True}})
    assert P.load_equity_curve(tmp_path) == []


def test_load_equity_curve_filters_non_dict_bars(tmp_path):
    _write_curve(
        tmp_path,
        {"daily": [{"date": "d0", "close_equity": 100.0}, "junk", 42, None]},
    )
    bars = P.load_equity_curve(tmp_path)
    assert bars == [{"date": "d0", "close_equity": 100.0}]


# --------------------------------------------------------------------------- #
# real_track_bars — warm-up filter with all-warmup fallback                     #
# --------------------------------------------------------------------------- #
def test_real_track_bars_drops_warmup():
    daily = [
        {"is_warmup": True, "date": "w0"},
        {"is_warmup": False, "date": "r0"},
        {"date": "r1"},  # missing key == falsy == real
    ]
    assert P.real_track_bars(daily) == [
        {"is_warmup": False, "date": "r0"},
        {"date": "r1"},
    ]


def test_real_track_bars_all_warmup_falls_back_to_all():
    daily = [{"is_warmup": True, "date": "w0"}, {"is_warmup": True, "date": "w1"}]
    # Fallback returns every bar (never an empty track).
    assert P.real_track_bars(daily) == daily


def test_real_track_bars_empty_input():
    assert P.real_track_bars([]) == []


# --------------------------------------------------------------------------- #
# _close — key precedence + numeric guard                                      #
# --------------------------------------------------------------------------- #
def test_close_precedence_and_missing():
    assert P._close({"close_equity": 100.0, "equity": 5, "nav": 1}) == 100.0
    assert P._close({"equity": 55}) == 55.0
    assert P._close({"nav": 7.5}) == 7.5
    assert P._close({"date": "d0"}) is None
    assert P._close({"close_equity": "100"}) is None  # non-numeric ignored


# --------------------------------------------------------------------------- #
# rebuild_curve — the segment-isolation core                                   #
# --------------------------------------------------------------------------- #
def test_rebuild_curve_empty_when_no_usable_close():
    assert P.rebuild_curve([]) == []
    assert P.rebuild_curve([{"date": "d0"}]) == []  # no close/equity/nav


def test_rebuild_curve_seed_bar_zero_return_without_open():
    bars = [
        {"date": "d0", "close_equity": 100000.0},
        {"date": "d1", "close_equity": 101000.0},
    ]
    curve = P.rebuild_curve(bars)
    assert [b["daily_return_pct"] for b in curve] == [0.0, 1.0]
    assert [b["cumulative_return_pct"] for b in curve] == [0.0, 1.0]
    # No drawdown on a strictly rising curve.
    assert [b["drawdown_pct"] for b in curve] == [0.0, 0.0]


def test_rebuild_curve_open_equity_counts_day1_yield():
    # With open_equity as the seed base, the FIRST bar's yield is not thrown away.
    bars = [{"date": "d0", "close_equity": 100500.0, "open_equity": 100000.0}]
    curve = P.rebuild_curve(bars)
    assert len(curve) == 1
    assert curve[0]["daily_return_pct"] == pytest.approx(0.5)
    assert curve[0]["cumulative_return_pct"] == pytest.approx(0.5)


def test_rebuild_curve_drawdown_is_vs_running_peak():
    bars = [
        {"date": "d0", "close_equity": 100.0},
        {"date": "d1", "close_equity": 110.0},  # new peak
        {"date": "d2", "close_equity": 99.0},   # drawdown off the 110 peak
    ]
    curve = P.rebuild_curve(bars)
    assert curve[1]["drawdown_pct"] == pytest.approx(0.0)
    # 99/110 - 1 = -10 %  (drawdown measured from the peak, not the start)
    assert curve[2]["drawdown_pct"] == pytest.approx(-10.0)
    # cumulative is vs the start (100): 99/100 - 1 = -1 %
    assert curve[2]["cumulative_return_pct"] == pytest.approx(-1.0)
    assert curve[2]["daily_return_pct"] == pytest.approx((99.0 / 110.0 - 1) * 100)


def test_rebuild_curve_no_warmup_leak_between_segments():
    # A warm-up reset (capital drop) must NOT show as a real-track drawdown once
    # the caller isolates the post-warm-up segment. rebuild_curve computes peak
    # WITHIN the supplied bars only, so a real segment that only rises has dd 0.
    real_segment = [
        {"date": "r0", "close_equity": 100000.0, "is_warmup": False},
        {"date": "r1", "close_equity": 100200.0, "is_warmup": False},
        {"date": "r2", "close_equity": 100450.0, "is_warmup": False},
    ]
    curve = P.rebuild_curve(P.real_track_bars(real_segment))
    assert all(b["drawdown_pct"] == pytest.approx(0.0) for b in curve)
    assert curve[-1]["cumulative_return_pct"] == pytest.approx(
        (100450.0 / 100000.0 - 1) * 100
    )


def test_rebuild_curve_skips_bars_without_close():
    bars = [
        {"date": "d0", "close_equity": 100.0},
        {"date": "gap"},  # no usable close → skipped entirely
        {"date": "d1", "close_equity": 102.0},
    ]
    curve = P.rebuild_curve(bars)
    assert [b["date"] for b in curve] == ["d0", "d1"]
    assert curve[1]["daily_return_pct"] == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# daily_returns_pct — seed exclusion                                           #
# --------------------------------------------------------------------------- #
def test_daily_returns_pct_excludes_seed():
    curve = [
        {"daily_return_pct": 0.0},   # seed — excluded
        {"daily_return_pct": 1.5},
        {"daily_return_pct": -0.5},
    ]
    assert P.daily_returns_pct(curve) == [1.5, -0.5]


def test_daily_returns_pct_single_bar_is_empty():
    assert P.daily_returns_pct([{"daily_return_pct": 0.0}]) == []
    assert P.daily_returns_pct([]) == []


# --------------------------------------------------------------------------- #
# annualize_return_pct / compound_return_pct                                    #
# --------------------------------------------------------------------------- #
def test_annualize_empty_is_none():
    assert P.annualize_return_pct([]) is None


def test_annualize_all_zero_is_zero():
    assert P.annualize_return_pct([0.0] * 10) == pytest.approx(0.0)


def test_annualize_total_loss_floors_at_minus_100():
    # A -100 % day wipes the book → growth <= 0 → clamped to -100 (never NaN/complex).
    assert P.annualize_return_pct([-100.0]) == -100.0
    assert P.annualize_return_pct([5.0, -100.0, 5.0]) == -100.0


def test_annualize_equals_compound_over_a_full_year():
    # With exactly ANNUALIZATION_DAYS observations the geometric annualisation
    # exponent is 1, so annualised return must equal the compounded total.
    n = P.ANNUALIZATION_DAYS
    returns = [0.02] * n
    assert P.annualize_return_pct(returns) == pytest.approx(
        P.compound_return_pct(returns)
    )


def test_annualize_positive_track_is_positive():
    assert P.annualize_return_pct([0.01] * 30) > 0


def test_compound_return_pct_basic():
    # (1.01)(1.01) - 1 = 2.01 %
    assert P.compound_return_pct([1.0, 1.0]) == pytest.approx(2.01)
    assert P.compound_return_pct([]) == pytest.approx(0.0)


def test_compound_return_pct_offsetting_moves():
    # +10 % then -10 % is a net loss (1.1 * 0.9 = 0.99 → -1 %).
    assert P.compound_return_pct([10.0, -10.0]) == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
# rnd — None propagation                                                        #
# --------------------------------------------------------------------------- #
def test_rnd_propagates_none():
    assert P.rnd(None) is None
    assert P.rnd(None, 2) is None


def test_rnd_rounds_to_places():
    assert P.rnd(1.23456) == 1.2346          # default 4 places
    assert P.rnd(1.23456, 2) == 1.23
    assert P.rnd(2, 2) == 2.0                 # int coerced to float


# --------------------------------------------------------------------------- #
# module-level constants — single source of truth guard                         #
# --------------------------------------------------------------------------- #
def test_benchmark_constants_are_finite_positive():
    for c in (
        P.TBILL_APY_PCT,
        P.STETH_APY_PCT,
        P.AAVE_CONSERVATIVE_APY_PCT,
        P.RISK_FREE_ANNUAL_PCT,
    ):
        assert isinstance(c, float) and math.isfinite(c) and c > 0
