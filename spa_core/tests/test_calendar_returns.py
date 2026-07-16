"""
Tests for the paper-trading calendar-returns module (SPA-V384).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_return_distribution.py).

Run::
    python spa_core/tests/test_calendar_returns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics_lab.calendar_returns import (
    _compound_pct,
    compute_day_of_week,
    compute_monthly_returns,
    compute_streaks,
    compute_summary,
    compute_weekly_returns,
    generate_calendar_returns_report,
)


# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0


def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except AssertionError as exc:
        FAIL += 1
        print(f"  ✗ {name}: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors as fails
        FAIL += 1
        print(f"  ✗ {name}: UNEXPECTED {type(exc).__name__}: {exc}")


def _curve(dated_returns):
    """Build a minimal daily curve from (date_str, daily_return_pct) pairs.

    The first element is the seed day (daily_return_pct forced to 0.0); all
    subsequent values are realised returns. Mirrors the sibling test helpers
    but lets each test pin explicit calendar dates.
    """
    bars = []
    equity = 100.0
    for i, (d, r) in enumerate(dated_returns):
        dr = 0.0 if i == 0 else r
        equity *= (1.0 + dr / 100.0)
        bars.append({
            "date": d,
            "open_equity": round(equity, 4),
            "close_equity": round(equity, 4),
            "high_equity": round(equity, 4),
            "low_equity": round(equity, 4),
            "snapshots": 1,
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": 0.0,
            "drawdown_pct": 0.0,
        })
    return bars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_compound_pct_helper():
    assert approx(_compound_pct([]), 0.0)
    assert approx(_compound_pct([1.0, -2.0]), (1.01 * 0.98 - 1.0) * 100.0)
    # two +1% days compound to slightly more than +2%
    assert _compound_pct([1.0, 1.0]) > 2.0


def test_empty_curve_stable_schema():
    assert compute_monthly_returns([]) == []
    assert compute_weekly_returns([]) == []
    dow = compute_day_of_week([])
    assert len(dow) == 7, dow
    assert all(d["num_days"] == 0 for d in dow), dow
    st = compute_streaks([])
    assert st["runs"] == [] and st["current_streak"] is None, st
    s = compute_summary([], [], st)
    assert s["num_realised_days"] == 0 and s["best_month"] is None, s


def test_single_seed_day_no_realised():
    curve = _curve([("2026-05-15", 0.0)])
    assert compute_monthly_returns(curve) == []
    st = compute_streaks(curve)
    assert st["runs"] == [], st


def test_monthly_grouping_and_compounding():
    curve = _curve([
        ("2026-05-15", 0.0),   # seed (dropped)
        ("2026-05-16", 1.0),
        ("2026-05-17", -0.5),
        ("2026-06-01", 2.0),
        ("2026-06-02", -1.0),
    ])
    m = compute_monthly_returns(curve)
    assert [x["month"] for x in m] == ["2026-05", "2026-06"], m
    may = m[0]
    assert may["num_days"] == 2 and may["positive_days"] == 1 and may["negative_days"] == 1, may
    assert approx(may["return_pct"], round((1.01 * 0.995 - 1.0) * 100.0, 4), tol=1e-4), may
    jun = m[1]
    assert approx(jun["return_pct"], round((1.02 * 0.99 - 1.0) * 100.0, 4), tol=1e-4), jun
    assert jun["best_day"]["date"] == "2026-06-01", jun
    assert jun["worst_day"]["date"] == "2026-06-02", jun


def test_weekly_iso_grouping():
    # 2026-05-15 is Fri (W20); 2026-05-18 is Mon (W21).
    curve = _curve([
        ("2026-05-15", 0.0),   # seed
        ("2026-05-16", 0.5),   # W20 (Sat)
        ("2026-05-18", -0.3),  # W21 (Mon)
        ("2026-05-19", 0.4),   # W21 (Tue)
    ])
    w = compute_weekly_returns(curve)
    weeks = [x["week"] for x in w]
    assert weeks == ["2026-W20", "2026-W21"], weeks
    assert w[1]["num_days"] == 2, w[1]


def test_day_of_week_seasonality():
    # 2026-05-18 Mon, 19 Tue, 20 Wed, 25 Mon.
    curve = _curve([
        ("2026-05-15", 0.0),   # seed
        ("2026-05-18", 1.0),   # Mon
        ("2026-05-19", -0.5),  # Tue
        ("2026-05-20", 0.2),   # Wed
        ("2026-05-25", 0.6),   # Mon
    ])
    dow = compute_day_of_week(curve)
    mon = next(d for d in dow if d["weekday"] == "Mon")
    assert mon["num_days"] == 2, mon
    assert approx(mon["mean_return_pct"], 0.8, tol=1e-4), mon
    assert approx(mon["win_rate_pct"], 100.0), mon
    sun = next(d for d in dow if d["weekday"] == "Sun")
    assert sun["num_days"] == 0 and sun["mean_return_pct"] is None, sun


def test_streaks_basic_runs():
    curve = _curve([
        ("2026-05-15", 0.0),   # seed
        ("2026-05-16", 1.0),   # win
        ("2026-05-17", 0.5),   # win
        ("2026-05-18", -0.3),  # loss
        ("2026-05-19", -0.2),  # loss
        ("2026-05-20", -0.1),  # loss
        ("2026-05-21", 0.4),   # win
    ])
    st = compute_streaks(curve)
    assert [r["kind"] for r in st["runs"]] == ["win", "loss", "win"], st["runs"]
    assert st["runs"][0]["length"] == 2, st["runs"][0]
    assert st["longest_loss_streak"]["length"] == 3, st["longest_loss_streak"]
    assert st["longest_win_streak"]["length"] == 2, st["longest_win_streak"]
    assert st["current_streak"]["kind"] == "win" and st["current_streak"]["length"] == 1, st


def test_streaks_flat_breaks_run():
    curve = _curve([
        ("2026-05-15", 0.0),   # seed
        ("2026-05-16", 1.0),   # win
        ("2026-05-17", 0.0),   # flat (breaks)
        ("2026-05-18", 0.5),   # win
    ])
    st = compute_streaks(curve)
    kinds = [r["kind"] for r in st["runs"]]
    assert kinds == ["win", "flat", "win"], kinds
    assert st["longest_win_streak"]["length"] == 1, st["longest_win_streak"]


def test_summary_rollup():
    curve = _curve([
        ("2026-05-15", 0.0),
        ("2026-05-16", 1.0),
        ("2026-05-17", -0.5),
        ("2026-06-01", 2.0),
    ])
    monthly = compute_monthly_returns(curve)
    st = compute_streaks(curve)
    s = compute_summary(curve, monthly, st)
    assert s["num_realised_days"] == 3, s
    assert s["num_months"] == 2, s
    assert s["best_month"]["month"] == "2026-06", s
    assert s["positive_months"] >= 1, s
    assert s["first_date"] == "2026-05-16" and s["last_date"] == "2026-06-01", s


def test_report_no_write_smoke():
    rep = generate_calendar_returns_report(output_path=None)
    for key in ("generated_at", "summary", "monthly", "weekly", "day_of_week", "streaks"):
        assert key in rep, (key, list(rep))
    assert isinstance(rep["summary"]["num_months"], int), rep["summary"]
    assert len(rep["day_of_week"]) == 7, rep["day_of_week"]
    # monthly compounded returns must be finite floats
    for m in rep["monthly"]:
        assert isinstance(m["return_pct"], float), m


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_calendar_returns (SPA-V384)")
    run("compound_pct helper", test_compound_pct_helper)
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no realised", test_single_seed_day_no_realised)
    run("monthly grouping + compounding", test_monthly_grouping_and_compounding)
    run("weekly ISO grouping", test_weekly_iso_grouping)
    run("day-of-week seasonality", test_day_of_week_seasonality)
    run("streaks basic runs", test_streaks_basic_runs)
    run("flat day breaks streak", test_streaks_flat_breaks_run)
    run("summary rollup", test_summary_rollup)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
