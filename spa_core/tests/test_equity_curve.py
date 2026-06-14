"""
Tests for the paper-trading daily equity-curve tracker (SPA-V379).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_paper_trading.py).

Run::
    python spa_core/tests/test_equity_curve.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.equity_curve import (
    build_daily_equity_curve,
    compute_summary,
    generate_equity_curve_report,
    load_pnl_history,
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
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  ✗ {name}: UNEXPECTED {type(exc).__name__}: {exc}")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _snap(ts, equity):
    return {"timestamp": ts, "total_capital_usd": equity}


# Two days, multiple intraday snapshots.
TWO_DAY = [
    _snap("2026-05-15T05:00:00Z", 100000.0),
    _snap("2026-05-15T09:00:00Z", 100500.0),
    _snap("2026-05-15T17:00:00Z", 100200.0),   # day1 close 100200, high 100500, low 100000
    _snap("2026-05-16T05:00:00Z", 100300.0),
    _snap("2026-05-16T21:00:00Z", 101200.0),   # day2 close 101200
]


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_history_curve():
    assert build_daily_equity_curve([]) == [], "empty input -> empty curve"
    s = compute_summary([])
    assert s["num_days"] == 0
    assert s["start_equity"] is None
    assert s["total_return_pct"] == 0.0


def test_basic_ohlc():
    curve = build_daily_equity_curve(TWO_DAY)
    assert len(curve) == 2, f"expected 2 daily bars, got {len(curve)}"
    d1 = curve[0]
    assert d1["date"] == "2026-05-15"
    assert d1["open_equity"] == 100000.0
    assert d1["close_equity"] == 100200.0
    assert d1["high_equity"] == 100500.0
    assert d1["low_equity"] == 100000.0
    assert d1["snapshots"] == 3
    assert d1["daily_return_pct"] == 0.0, "day1 daily return is seed 0.0"


def test_daily_and_cumulative_returns():
    curve = build_daily_equity_curve(TWO_DAY)
    d2 = curve[1]
    # day2 close 101200 vs day1 close 100200 -> +0.998%
    assert abs(d2["daily_return_pct"] - 0.998) < 0.01, d2["daily_return_pct"]
    # cumulative vs first open 100000 -> +1.2%
    assert abs(d2["cumulative_return_pct"] - 1.2) < 1e-6, d2["cumulative_return_pct"]


def test_drawdown_non_positive_and_recovers():
    # Peak then dip then new peak.
    data = [
        _snap("2026-05-15T05:00:00Z", 100000.0),
        _snap("2026-05-16T05:00:00Z", 95000.0),   # -5% drawdown vs peak 100000
        _snap("2026-05-17T05:00:00Z", 102000.0),  # new peak -> dd 0
    ]
    curve = build_daily_equity_curve(data)
    assert curve[0]["drawdown_pct"] == 0.0
    assert abs(curve[1]["drawdown_pct"] - (-5.0)) < 1e-6, curve[1]["drawdown_pct"]
    assert curve[2]["drawdown_pct"] == 0.0, "new high -> drawdown resets to 0"
    s = compute_summary(curve)
    assert abs(s["max_drawdown_pct"] - (-5.0)) < 1e-6, s["max_drawdown_pct"]


def test_summary_best_worst_and_counts():
    curve = build_daily_equity_curve(TWO_DAY)
    s = compute_summary(curve)
    assert s["num_days"] == 2
    assert s["num_snapshots"] == 5
    assert s["start_equity"] == 100000.0
    assert s["end_equity"] == 101200.0
    assert abs(s["total_return_pct"] - 1.2) < 1e-6
    assert s["best_day"]["date"] == "2026-05-16"
    assert s["positive_days"] == 1
    assert s["negative_days"] == 0


def test_malformed_snapshots_skipped():
    data = [
        _snap("2026-05-15T05:00:00Z", 100000.0),
        {"timestamp": "not-a-date", "total_capital_usd": 999.0},  # bad ts
        {"timestamp": "2026-05-15T06:00:00Z", "total_capital_usd": "oops"},  # bad equity
        {"timestamp": "2026-05-15T07:00:00Z"},  # missing equity
        "garbage",  # not a dict
        _snap("2026-05-16T05:00:00Z", 100500.0),
    ]
    curve = build_daily_equity_curve(data)
    assert len(curve) == 2, f"only 2 valid snapshots across 2 days, got {curve}"
    assert curve[0]["snapshots"] == 1


def test_out_of_order_snapshots_sorted():
    data = [
        _snap("2026-05-16T05:00:00Z", 100500.0),
        _snap("2026-05-15T05:00:00Z", 100000.0),
    ]
    curve = build_daily_equity_curve(data)
    assert [b["date"] for b in curve] == ["2026-05-15", "2026-05-16"]


def test_report_roundtrip_write_and_load():
    tmp_hist = Path(tempfile.mktemp(suffix=".json"))
    tmp_out = Path(tempfile.mktemp(suffix=".json"))
    tmp_hist.write_text(json.dumps(TWO_DAY), encoding="utf-8")
    try:
        report = generate_equity_curve_report(tmp_hist, tmp_out)
        assert tmp_out.exists(), "report file should be written"
        on_disk = json.loads(tmp_out.read_text(encoding="utf-8"))
        assert on_disk["summary"]["num_days"] == 2
        assert "generated_at" in report and report["daily"][0]["date"] == "2026-05-15"
    finally:
        for p in (tmp_hist, tmp_out):
            if p.exists():
                p.unlink()


def test_load_missing_file_is_empty():
    assert load_pnl_history(Path(tempfile.mktemp(suffix=".json"))) == []


def test_runs_against_real_history_if_present():
    """Smoke test: the real data/pnl_history.json should parse into a report."""
    real = Path(__file__).resolve().parents[2] / "data" / "pnl_history.json"
    if not real.exists():
        return  # skip silently if not present in this checkout
    report = generate_equity_curve_report(real, output_path=None)
    assert report["summary"]["num_days"] >= 1, "real history should yield >=1 day"
    assert isinstance(report["daily"], list)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("test_equity_curve (SPA-V379)")
    run("empty_history_curve", test_empty_history_curve)
    run("basic_ohlc", test_basic_ohlc)
    run("daily_and_cumulative_returns", test_daily_and_cumulative_returns)
    run("drawdown_non_positive_and_recovers", test_drawdown_non_positive_and_recovers)
    run("summary_best_worst_and_counts", test_summary_best_worst_and_counts)
    run("malformed_snapshots_skipped", test_malformed_snapshots_skipped)
    run("out_of_order_snapshots_sorted", test_out_of_order_snapshots_sorted)
    run("report_roundtrip_write_and_load", test_report_roundtrip_write_and_load)
    run("load_missing_file_is_empty", test_load_missing_file_is_empty)
    run("runs_against_real_history_if_present", test_runs_against_real_history_if_present)
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
