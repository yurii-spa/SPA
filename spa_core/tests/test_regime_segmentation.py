"""
Tests for the paper-trading regime-segmentation module (SPA-V400).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_advanced_ratios.py / test_serial_dependence.py).

Run::
    python spa_core/tests/test_regime_segmentation.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics_lab.regime_segmentation import (
    DEFAULT_THRESHOLD_PCT,
    compute_regime_segmentation,
    generate_regime_segmentation_report,
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


def _curve(closes):
    """Build a minimal daily curve from a list of close_equity values.

    Fills date/cumulative_return_pct so the module's path logic works. The
    segmentation operates off ``close_equity`` directly.
    """
    bars = []
    first = closes[0] if closes else None
    for i, c in enumerate(closes):
        cum = 0.0 if not first else (c / first - 1.0) * 100.0
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(c, 4),
            "close_equity": round(c, 4),
            "high_equity": round(c, 4),
            "low_equity": round(c, 4),
            "snapshots": 1,
            "daily_return_pct": 0.0,
            "cumulative_return_pct": round(cum, 6),
            "drawdown_pct": 0.0,
        })
    return bars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


_SCHEMA_KEYS = {
    "execution_mode", "threshold_pct", "num_days", "first_date", "last_date",
    "num_segments", "segments", "advance", "decline", "flat",
    "current_regime", "largest_advance", "largest_decline", "trend_summary",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_regime_segmentation([])
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_segments"] == 0, m
    assert m["segments"] == [], m
    assert m["current_regime"] is None, m
    assert m["largest_advance"] is None and m["largest_decline"] is None, m
    assert m["trend_summary"] == "insufficient_data", m
    assert m["execution_mode"] == "read_only_simulation", m


def test_single_day_stable_schema():
    m = compute_regime_segmentation(_curve([100.0]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_segments"] == 0, m
    assert m["num_days"] == 1, m
    assert m["current_regime"] is None, m
    assert m["trend_summary"] == "insufficient_data", m


def test_schema_keys_on_real_shape():
    m = compute_regime_segmentation(_curve([100.0, 102.0, 99.0, 105.0]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["execution_mode"] == "read_only_simulation", m


def test_monotonic_up_is_advance_uptrending():
    m = compute_regime_segmentation(_curve([100, 102, 104, 107, 110]))
    assert m["num_segments"] >= 1, m
    assert m["current_regime"]["direction"] == "advance", m
    assert m["advance"]["count"] >= 1, m
    assert m["trend_summary"] == "uptrending", m
    # No reversal big enough → a single advance leg spanning the whole series.
    assert m["num_segments"] == 1, m


def test_monotonic_down_is_decline_downtrending():
    m = compute_regime_segmentation(_curve([110, 107, 104, 101, 98]))
    assert m["current_regime"]["direction"] == "decline", m
    assert m["decline"]["count"] >= 1, m
    assert m["trend_summary"] == "downtrending", m
    assert m["num_segments"] == 1, m


def test_zigzag_above_threshold_segment_count():
    # Clear up-down-up zig-zag, each leg ~5% >> 1% threshold.
    # 100 -> 105 (up) -> 100 (down, -4.76%) -> 106 (up, +6%).
    closes = [100, 102, 105, 103, 100, 102, 106]
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    dirs = [s["direction"] for s in m["segments"]]
    # Expect three confirmed legs: advance, decline, advance.
    assert m["num_segments"] == 3, (m["num_segments"], dirs)
    assert dirs == ["advance", "decline", "advance"], dirs
    assert m["current_regime"]["direction"] == "advance", m


def test_small_wiggles_below_threshold_no_extra_segments():
    # Up-drift with tiny <1% wiggles → one advance leg, no spurious reversals.
    closes = [100.0, 100.3, 100.1, 100.5, 100.2, 100.8, 101.5]
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    assert m["num_segments"] == 1, m["segments"]
    assert m["segments"][0]["direction"] == "advance", m


def test_threshold_monotonicity():
    closes = [100, 103, 101, 104, 102, 105, 101, 106]
    low = compute_regime_segmentation(_curve(closes), threshold_pct=0.5)
    high = compute_regime_segmentation(_curve(closes), threshold_pct=5.0)
    # A higher reversal threshold can only merge legs, never create more.
    assert high["num_segments"] <= low["num_segments"], (
        low["num_segments"], high["num_segments"])


def test_return_pct_formula():
    # Single advance leg 100 -> 110 → return_pct = 10.0.
    m = compute_regime_segmentation(_curve([100.0, 110.0]))
    seg = m["segments"][0]
    expected = (110.0 / 100.0 - 1.0) * 100.0
    assert approx(seg["return_pct"], expected, tol=1e-6), seg
    assert approx(seg["return_pct"], 10.0, tol=1e-6), seg


def test_magnitude_is_abs_return_and_nonneg():
    m = compute_regime_segmentation(_curve([110, 107, 104, 101, 98]))
    for s in m["segments"]:
        assert s["magnitude_pct"] >= 0.0, s
        assert approx(s["magnitude_pct"], abs(s["return_pct"]), tol=1e-9), s


def test_length_days_at_least_one():
    m = compute_regime_segmentation(_curve([100, 102, 105, 103, 100, 102, 106]))
    for s in m["segments"]:
        assert s["length_days"] >= 1, s
    # Length days across all legs sum to total steps (n-1) for a zig-zag chain.
    total = sum(s["length_days"] for s in m["segments"])
    assert total == m["num_days"] - 1, (total, m["num_days"])


def test_largest_advance_consistent_with_segments():
    closes = [100, 102, 105, 103, 100, 102, 112]  # last advance is biggest
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    advs = [s for s in m["segments"] if s["direction"] == "advance"]
    assert advs, m
    biggest = max(advs, key=lambda s: s["magnitude_pct"])
    assert m["largest_advance"] is not None, m
    assert approx(m["largest_advance"]["magnitude_pct"], biggest["magnitude_pct"]), m
    assert m["largest_advance"]["start_date"] == biggest["start_date"], m


def test_largest_decline_consistent_with_segments():
    closes = [100, 105, 90, 95, 80]  # declines present
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    decs = [s for s in m["segments"] if s["direction"] == "decline"]
    if decs:
        biggest = max(decs, key=lambda s: s["magnitude_pct"])
        assert m["largest_decline"] is not None, m
        assert approx(m["largest_decline"]["magnitude_pct"], biggest["magnitude_pct"]), m
    else:
        assert m["largest_decline"] is None, m


def test_current_regime_matches_last_segment():
    closes = [100, 102, 105, 103, 100, 102, 106]
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    last = m["segments"][-1]
    cr = m["current_regime"]
    assert cr["direction"] == last["direction"], (cr, last)
    assert cr["start_date"] == last["start_date"], (cr, last)
    assert cr["end_date"] == last["end_date"], (cr, last)
    assert approx(cr["return_pct"], last["return_pct"]), (cr, last)


def test_flat_series_trailing_flat_leg():
    # Perfectly flat → one trailing leg labelled flat, no advance/decline.
    m = compute_regime_segmentation(_curve([100.0, 100.0, 100.0, 100.0]))
    assert m["num_segments"] == 1, m
    assert m["segments"][0]["direction"] == "flat", m
    assert m["advance"]["count"] == 0 and m["decline"]["count"] == 0, m
    assert m["current_regime"]["direction"] == "flat", m


def test_sub_threshold_drift_labelled_flat():
    # Drifts up only 0.4% total, below a 1% threshold → trailing flat leg.
    m = compute_regime_segmentation(_curve([100.0, 100.2, 100.1, 100.4]),
                                    threshold_pct=1.0)
    assert m["num_segments"] == 1, m
    assert m["segments"][0]["direction"] == "flat", m


def test_all_finite_outputs():
    m = compute_regime_segmentation(_curve([100, 103, 99, 107, 101, 110, 95]))

    def _walk(obj):
        if isinstance(obj, float):
            assert math.isfinite(obj), obj
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(m)


def test_phase_summary_totals_consistent():
    closes = [100, 105, 100, 106, 101, 108]
    m = compute_regime_segmentation(_curve(closes), threshold_pct=1.0)
    advs = [s for s in m["segments"] if s["direction"] == "advance"]
    if advs:
        assert m["advance"]["count"] == len(advs), m
        total = round(sum(s["return_pct"] for s in advs), 6)
        assert approx(m["advance"]["total_return_pct"], total, tol=1e-4), m
        assert m["advance"]["max_length_days"] == max(s["length_days"] for s in advs), m


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "regime_segmentation.json"
        generate_regime_segmentation_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir()
                     if p.name.startswith(".regime_segmentation_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


def test_report_no_write_smoke_real_data():
    report = generate_regime_segmentation_report(output_path=None)
    assert "generated_at" in report and "segmentation" in report, report
    assert set(report["segmentation"].keys()) == _SCHEMA_KEYS, report["segmentation"].keys()
    assert report["segmentation"]["execution_mode"] == "read_only_simulation", report
    assert report["segmentation"]["threshold_pct"] == DEFAULT_THRESHOLD_PCT, report


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_regime_segmentation (SPA-V400)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single day → stable schema", test_single_day_stable_schema)
    run("schema keys on real shape", test_schema_keys_on_real_shape)
    run("monotonic up → advance / uptrending", test_monotonic_up_is_advance_uptrending)
    run("monotonic down → decline / downtrending", test_monotonic_down_is_decline_downtrending)
    run("zig-zag above threshold → exact segment count", test_zigzag_above_threshold_segment_count)
    run("small wiggles below threshold → no extra segments", test_small_wiggles_below_threshold_no_extra_segments)
    run("threshold monotonicity (higher → not more)", test_threshold_monotonicity)
    run("return_pct == (end/start-1)*100", test_return_pct_formula)
    run("magnitude == abs(return) and >= 0", test_magnitude_is_abs_return_and_nonneg)
    run("length_days >= 1 and sums to steps", test_length_days_at_least_one)
    run("largest_advance consistent with segments", test_largest_advance_consistent_with_segments)
    run("largest_decline consistent with segments", test_largest_decline_consistent_with_segments)
    run("current_regime matches last segment", test_current_regime_matches_last_segment)
    run("flat series → trailing flat leg", test_flat_series_trailing_flat_leg)
    run("sub-threshold drift → labelled flat", test_sub_threshold_drift_labelled_flat)
    run("all outputs finite", test_all_finite_outputs)
    run("phase-summary totals consistent", test_phase_summary_totals_consistent)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
