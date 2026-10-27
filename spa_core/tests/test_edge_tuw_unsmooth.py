# FROZEN-DATE-OK: the dates here are axis labels of synthetic panels and the window
# constants of the script under test (split / splice cut). Nothing in the module asks
# what time it is — no freshness window, no TTL — so the calendar moving cannot change
# a single assertion.
"""Controls for ideas #143 TUW / #144 GLM (scripts/edge_tuw_unsmooth.py).

Each test is a positive control for a way the measurement could lie:

* admission could read the day it is meant to predict (look-ahead);
* "days since HWM" could reset on a partial recovery instead of a new high;
* the duration rule could secretly be the depth rule (then #143 = #119 CADS);
* unsmoothing could LOWER measured risk on a mean-reverting series;
* a constant series could be reported as autocorrelation 0 instead of "not measured";
* a panel with mismatched axes, or nothing on disk, could be read as a result;
* the 2026-08-05 splice could leak into the window.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import edge_tuw_unsmooth as m  # noqa: E402


def _dates(n, start=(2024, 3, 5)):
    import datetime as dt
    d0 = dt.date(*start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_panel(tmp_path, books, dates, extra_rows=None):
    for name, eq in books.items():
        d = tmp_path / name
        d.mkdir()
        rows = [{"date": dt, "equity_usd": e} for dt, e in zip(dates, eq)]
        rows += (extra_rows or {}).get(name, [])
        (d / "realized_series.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_days_since_hwm_resets_only_on_a_new_high():
    assert m.days_since_hwm([100, 99, 99.5, 100, 98, 101]) == [0, 1, 2, 0, 1, 0]


def test_admission_is_causal_a_crash_today_does_not_change_todays_weight():
    # book a crashes on day 3; the crash must be paid in full (no same-day exit)
    eq = {"a": [100, 100.1, 100.2, 50, 50, 50], "b": [100, 100, 100, 100, 100, 100]}
    dsh = {k: m.days_since_hwm(v) for k, v in eq.items()}
    admit = {k: [x <= 0 for x in v] for k, v in dsh.items()}
    r = m.run_overlay(eq, admit, redistribute=False, toll=0.0)
    assert r[2] == pytest.approx(0.5 * (50 / 100.2 - 1))   # held through the crash day
    assert r[3] == pytest.approx(0.0)                       # excluded from the next day on


def test_duration_and_depth_rules_disagree_on_a_shallow_long_drawdown():
    # −1 % for 40 days: TUW-20 excludes it, DEPTH-2 % keeps it
    eq = [100.0] + [99.0] * 40
    dsh = m.days_since_hwm(eq)
    ddp = m.drawdown_path(eq)
    assert any(x > 20 for x in dsh)
    assert all(x <= 0.02 for x in ddp)


def test_redistribute_spreads_excluded_weight_and_cash_mode_does_not():
    eq = {"a": [100, 90, 91, 92], "b": [100, 101, 102, 103]}
    admit = {"a": [True, False, False, False], "b": [True] * 4}
    cash = m.run_overlay(eq, admit, redistribute=False, toll=0.0)
    red = m.run_overlay(eq, admit, redistribute=True, toll=0.0)
    assert cash[1] == pytest.approx(0.5 * (102 / 101 - 1))
    assert red[1] == pytest.approx(102 / 101 - 1)


def test_toll_is_charged_on_admission_changes_only():
    eq = {"a": [100, 100, 100, 100], "b": [100, 100, 100, 100]}
    admit = {"a": [True, False, False, False], "b": [True] * 4}
    r = m.run_overlay(eq, admit, redistribute=False, toll=0.01)
    assert r[0] == 0.0                                      # day 1: still EW, no change
    assert r[1] == pytest.approx(-0.5 * 0.01 / 2)           # one-way half of the round trip on 0.5 weight
    assert r[2] == 0.0


def test_unsmoothing_only_raises_risk():
    assert m.unsmooth_factor(0.9) > 4.0
    assert m.unsmooth_factor(-0.5) == 1.0
    assert m.unsmooth_factor(None) == 1.0


def test_constant_series_autocorrelation_is_unmeasured_not_zero():
    assert m.lag1_autocorr([0.001] * 50) is None
    import random
    rng = random.Random(7)                                  # seeded: deterministic AR(1), ρ = 0.9
    ar = [0.0]
    for _ in range(400):
        ar.append(0.9 * ar[-1] + rng.gauss(0, 0.01))
    assert m.lag1_autocorr(ar) > 0.7


def test_calmar_without_drawdown_is_none_not_infinite():
    assert m.metrics([0.001] * 30)["calmar"] is None
    mm = m.metrics([0.01, -0.02, 0.01])
    assert mm["mdd"] == pytest.approx(0.02)


def test_spearman_handles_ties_and_population():
    assert m.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert m.spearman([1, 2], [2, 1]) is None
    assert m.spearman([1, 1, 1], [1, 2, 3]) is None


def test_load_panel_cuts_the_splice_and_refuses_misaligned_axes(tmp_path):
    dates = _dates(5)
    splice = [{"date": "2026-08-05", "equity_usd": 1.0}]
    _write_panel(tmp_path, {"a": [100] * 5, "b": [100] * 5}, dates, {"a": splice, "b": splice})
    axis, eq = m.load_panel(tmp_path)
    assert axis == dates and all(len(v) == 5 for v in eq.values())

    bad = tmp_path / "bad"
    _write_panel(bad.mkdir() or bad, {"a": [100] * 5, "b": [100] * 4}, dates)
    with pytest.raises(m.PanelError):
        m.load_panel(bad)


def test_empty_data_dir_is_not_measured(tmp_path):
    with pytest.raises(m.PanelError):
        m.load_panel(tmp_path)
    assert m.main(["--data-dir", str(tmp_path)]) == 2


def test_run_end_to_end_on_a_synthetic_panel(tmp_path):
    n = 700
    dates = _dates(n)
    carry = [100 * (1 + 0.0003) ** i for i in range(n)]
    bleed = [100 * (1 - 0.0002) ** i for i in range(n)]          # chronically under water
    _write_panel(tmp_path, {"carry": carry, "bleed": bleed}, dates)
    res = m.run(tmp_path)
    s = res["splits"][m.SPLIT_PRIMARY]
    ew = s["tuw_rows"][0]["test"]
    tuw = s["train_picks"]["TUW/cash"]["test"]
    assert tuw["apy"] > ew["apy"]                                # the bleeding book is excluded
    assert set(s["loo"]) == {"carry", "bleed"}
    assert res["is_advisory"] is True and res["outside_riskpolicy"] is True
    assert math.isfinite(s["glm"]["sigma_floor"])
