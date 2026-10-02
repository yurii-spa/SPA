"""Controls for scripts/edge_cads_real.py (#120 CADS-REAL). Synthetic panels only — no live data.

Each test names the link it guards; the two causality/cost tests are the ones that make the
registry numbers mean anything (ADR-212: a guard that decides knowing the day's outcome).
"""
# FROZEN-DATE-OK: literal ISO dates are synthetic panel axis labels, compared to each other only
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edge_cads_real as C  # noqa: E402


def _axis(n: int):
    # 2025-01-01 + i days, as ISO strings, without datetime arithmetic in the assertions
    import datetime as _dt
    d0 = _dt.date(2025, 1, 1)
    return [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(n)]


def _panel(n=60, crash_day=10, crash=-0.20):
    dates = _axis(n)
    rets = {
        "a": {d: 0.001 for d in dates},
        "b": {d: 0.0005 for d in dates},
        "x": {d: (crash if i == crash_day else 0.0) for i, d in enumerate(dates)},
    }
    return dates, ["a", "b", "x"], rets


def test_stop_cannot_dodge_the_day_that_triggers_it():
    """Causality: the crash on day t must be eaten by the stop arm too (1/3 of −20 %); only
    the days AFTER can be avoided. A simulator that decides on day t's own return dodges it."""
    dates, books, rets = _panel()
    ew = C.simulate(dates, books, rets, None, 0.0, "ew")
    st = C.simulate(dates, books, rets, 0.05, 0.01, "cash")
    i = 10
    day_ret_ew = ew.equity[i + 1] / ew.equity[i] - 1.0
    day_ret_st = st.equity[i + 1] / st.equity[i] - 1.0
    assert day_ret_st == pytest.approx(day_ret_ew, abs=1e-12)
    assert day_ret_st < -0.06
    # and the stop is recorded on the NEXT day, with the dd it saw through t
    assert st.stops[0][0] == dates[i + 1] and st.stops[0][1] == "x"
    assert st.stops[0][2] == pytest.approx(0.20, abs=1e-9)


def test_moving_a_slice_is_charged_roundtrip_on_one_nth():
    dates, books, rets = _panel()
    st = C.simulate(dates, books, rets, 0.05, 0.01, "cash", roundtrip=0.0096)
    eq_before = st.equity[11]
    assert st.cost == pytest.approx(eq_before * 0.0096 / 3, rel=1e-9)
    assert st.turnover == pytest.approx(1 / 3, rel=1e-12)
    # and the charge actually leaves the equity (a counter that is not deducted is decoration)
    free = C.simulate(dates, books, rets, 0.05, 0.01, "cash", roundtrip=0.0)
    assert st.equity[-1] / free.equity[-1] == pytest.approx(1.0 - 0.0096 / 3, rel=1e-9)


def test_ew_never_stops_and_pays_nothing():
    dates, books, rets = _panel()
    ew = C.simulate(dates, books, rets, None, 0.0, "ew")
    assert ew.stops == [] and ew.cost == 0.0


def test_reentry_outside_the_stop_band_is_refused():
    dates, books, rets = _panel()
    with pytest.raises(C.Refusal):
        C.simulate(dates, books, rets, 0.05, 0.05, "cash")
    with pytest.raises(C.Refusal):
        C.simulate(dates, books, rets, 0.05, 0.01, "nonsense")


def test_calmar_mode_sends_the_slice_to_the_best_survivor():
    dates, books, rets = _panel()
    r = C.simulate(dates, books, rets, 0.05, 0.01, "calmar")
    # after the stop, "a" (higher return, no drawdown) carries x's slice: 2/3 of capital
    assert r.avg_w["a"] > r.avg_w["b"] + 0.2
    assert r.avg_w[C.CASH] == 0.0


def test_spread_mode_splits_equally():
    dates, books, rets = _panel()
    r = C.simulate(dates, books, rets, 0.05, 0.01, "spread")
    assert r.avg_w["a"] == pytest.approx(r.avg_w["b"], abs=1e-12)


def test_static_mix_with_equal_weights_reproduces_ew():
    dates, books, rets = _panel()
    ew = C.simulate(dates, books, rets, None, 0.0, "ew")
    st = C.static_mix(dates, books, rets, {b: 1 / 3 for b in books})
    assert st.equity[-1] == pytest.approx(ew.equity[-1], rel=1e-12)


def test_out_through_replays_stops_and_reentries():
    run = C.Run([], [1.0], 0.0, 0.0,
                stops=[("2025-01-05", "x", 0.1), ("2025-02-01", "y", 0.1), ("2025-03-01", "z", 0.1)],
                reentries=[("2025-01-20", "x", 0.0), ("2025-03-05", "z", 0.0)], avg_w={})
    # y stopped before start and never back; z stopped before start but re-entered later; x back
    assert C.out_through(run, "2025-02-15") == ["y"]


def test_segment_refuses_a_short_window():
    dates, books, rets = _panel(n=60)
    ew = C.simulate(dates, books, rets, None, 0.0, "ew")
    with pytest.raises(C.Refusal):
        C.segment(ew, dates[-10], None)


def test_absent_panel_is_not_measured(tmp_path):
    with pytest.raises(C.Refusal):
        C.load_real_panel(tmp_path / "nope")


def test_pick_on_train_never_reads_test_rows():
    """Two arms identical through TRAIN_END, divergent after: the pick must not change when only
    the test rows change (it ties → deterministic key order)."""
    dates = _axis(800)
    books = ["a", "b"]
    base = {b: {d: 0.0003 for d in dates} for b in books}
    runs1 = C.run_all(dates, books, base)
    alt = {b: dict(v) for b, v in base.items()}
    for d in dates:
        if d > C.TRAIN_END:
            alt["a"][d] = -0.01
    runs2 = C.run_all(dates, books, alt)
    assert C.pick_on_train(runs1) == C.pick_on_train(runs2)


def test_wired_through_the_119_command(tmp_path):
    """`python scripts/edge_cads.py --real` is the named command that reproduces #120; with no
    panel it must say НЕ ИЗМЕРЕНО and exit 2 — never fall through to the fixture run of #119."""
    import os
    import subprocess
    env = dict(os.environ, SPA_PANEL_DIR=str(tmp_path / "absent"))
    p = subprocess.run([sys.executable, str(Path(C.__file__).with_name("edge_cads.py")), "--real"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 2 and "НЕ ИЗМЕРЕНО" in p.stdout and "CADS #119" not in p.stdout
