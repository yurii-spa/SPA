"""
Tests for the portfolio concentration-analytics module (SPA-V398).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_advanced_ratios.py).

Run::
    python spa_core/tests/test_concentration_analytics.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.concentration_analytics import (
    DEFAULT_PORTFOLIO_STATE_PATH,
    DEFAULT_TARGET_ALLOCATION_PATH,
    build_concentration_report,
    compute_concentration_metrics,
    generate_concentration_report,
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


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _state(weights_by_protocol, *, usd_only=False, total_usd=100000.0):
    """Build a portfolio_state-shaped dict from {protocol: weight}.

    If usd_only, omit actual_weight and supply only actual_usd (= weight*total)
    so the module must derive weights from USD exposure.
    """
    positions = []
    for protocol, w in weights_by_protocol.items():
        pos = {"protocol": protocol, "actual_usd": round(w * total_usd, 6)}
        if not usd_only:
            pos["actual_weight"] = w
        positions.append(pos)
    return {
        "total_actual_usd": total_usd,
        "num_positions": len(positions),
        "positions": positions,
    }


_SCHEMA_KEYS = {
    "num_positions", "weights", "herfindahl_index", "hhi_normalized",
    "effective_num_positions", "max_weight", "max_weight_protocol",
    "min_weight", "min_weight_protocol", "top1_concentration_pct",
    "top3_concentration_pct", "shannon_entropy", "entropy_normalized",
    "gini_coefficient", "diversification_grade",
}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_none_stable_schema():
    m = compute_concentration_metrics(None)
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_positions"] == 0, m
    assert m["herfindahl_index"] is None, m
    assert m["weights"] == {}, m


def test_empty_positions_stable_schema():
    m = compute_concentration_metrics({"positions": []})
    assert m["num_positions"] == 0, m
    assert m["diversification_grade"] is None, m


def test_malformed_inputs_no_exception():
    for bad in ([], 42, "garbage", {"positions": "nope"}, {"positions": [1, 2, 3]}):
        m = compute_concentration_metrics(bad)
        assert set(m.keys()) == _SCHEMA_KEYS, (bad, m.keys())
        assert m["num_positions"] == 0, (bad, m)


def test_malformed_json_file_stable():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "portfolio_state.json"
        bad.write_text("{ this is not valid json ", encoding="utf-8")
        report = build_concentration_report(bad, target_allocation_path=None)
        assert report["metrics"]["num_positions"] == 0, report
        assert "generated_at" in report and "metrics" in report, report


def test_missing_file_stable():
    report = build_concentration_report(
        "/no/such/portfolio_state.json", target_allocation_path=None
    )
    assert report["metrics"]["num_positions"] == 0, report
    assert report["execution_mode"] == "read_only_simulation", report


def test_equal_weight_four_positions():
    m = compute_concentration_metrics(
        _state({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    )
    assert m["num_positions"] == 4, m
    assert approx(m["herfindahl_index"], 0.25), m
    assert approx(m["effective_num_positions"], 4.0, tol=1e-4), m
    assert approx(m["hhi_normalized"], 0.0, tol=1e-9), m
    assert approx(m["gini_coefficient"], 0.0, tol=1e-9), m
    assert approx(m["entropy_normalized"], 1.0, tol=1e-9), m
    assert m["diversification_grade"] == "A", m


def test_single_position():
    m = compute_concentration_metrics(_state({"solo": 1.0}))
    assert m["num_positions"] == 1, m
    assert approx(m["herfindahl_index"], 1.0), m
    assert approx(m["effective_num_positions"], 1.0), m
    assert m["hhi_normalized"] is None, m
    assert m["entropy_normalized"] is None, m
    assert approx(m["gini_coefficient"], 0.0), m
    assert approx(m["top1_concentration_pct"], 100.0), m
    assert m["max_weight_protocol"] == "solo", m
    assert m["diversification_grade"] is None, m


def test_skewed_weights_hand_computed():
    # 0.7 / 0.1 / 0.1 / 0.1 -> HHI = 0.49 + 3*0.01 = 0.52
    m = compute_concentration_metrics(
        _state({"big": 0.7, "x": 0.1, "y": 0.1, "z": 0.1})
    )
    assert approx(m["herfindahl_index"], 0.52, tol=1e-9), m
    assert approx(m["max_weight"], 0.7), m
    assert m["max_weight_protocol"] == "big", m
    assert approx(m["top1_concentration_pct"], 70.0), m
    # eff_N = 1/0.52 ~ 1.923
    assert approx(m["effective_num_positions"], 1.0 / 0.52, tol=1e-3), m
    # hhi_normalized = (0.52 - 0.25)/(0.75) = 0.36 -> grade C (>0.35, <=0.60)
    assert approx(m["hhi_normalized"], (0.52 - 0.25) / 0.75, tol=1e-9), m
    assert m["diversification_grade"] == "C", m


def test_weights_derived_from_usd_when_weight_missing():
    m = compute_concentration_metrics(
        _state({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}, usd_only=True)
    )
    assert m["num_positions"] == 4, m
    assert approx(m["herfindahl_index"], 0.25, tol=1e-6), m
    assert approx(m["max_weight"], 0.25, tol=1e-6), m


def test_weights_normalize_to_one():
    # Supply non-normalised weights; module should renormalise to sum 1.
    m = compute_concentration_metrics(
        _state({"a": 2.0, "b": 1.0, "c": 1.0})
    )
    total = sum(m["weights"].values())
    assert approx(total, 1.0, tol=1e-6), m["weights"]
    assert approx(m["max_weight"], 0.5, tol=1e-6), m


def test_monotonicity_more_concentrated():
    even = compute_concentration_metrics(_state({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}))
    skew = compute_concentration_metrics(_state({"a": 0.7, "b": 0.1, "c": 0.1, "d": 0.1}))
    assert skew["herfindahl_index"] > even["herfindahl_index"], (even, skew)
    assert skew["effective_num_positions"] < even["effective_num_positions"], (even, skew)
    assert skew["entropy_normalized"] < even["entropy_normalized"], (even, skew)
    assert skew["gini_coefficient"] > even["gini_coefficient"], (even, skew)


def test_effective_num_is_inverse_hhi():
    for w in ({"a": 0.5, "b": 0.3, "c": 0.2}, {"a": 0.4, "b": 0.4, "c": 0.2}):
        m = compute_concentration_metrics(_state(w))
        assert approx(m["effective_num_positions"], 1.0 / m["herfindahl_index"], tol=1e-3), m


def test_top3_geq_top1_and_bounded():
    m = compute_concentration_metrics(_state({"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1}))
    assert m["top3_concentration_pct"] >= m["top1_concentration_pct"], m
    assert m["top3_concentration_pct"] <= 100.0 + 1e-9, m
    assert m["top1_concentration_pct"] <= 100.0 + 1e-9, m


def test_metric_ranges_bounded():
    m = compute_concentration_metrics(_state({"a": 0.5, "b": 0.3, "c": 0.15, "d": 0.05}))
    assert 0.0 <= m["gini_coefficient"] <= 1.0, m
    assert 0.0 <= m["entropy_normalized"] <= 1.0, m
    assert 0.0 <= m["hhi_normalized"] <= 1.0, m


def test_active_share_zero_when_equal():
    state = _state({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    target = {"target_weights": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}}
    with tempfile.TemporaryDirectory() as d:
        ps = Path(d) / "portfolio_state.json"
        ta = Path(d) / "target_allocation.json"
        ps.write_text(json.dumps(state), encoding="utf-8")
        ta.write_text(json.dumps(target), encoding="utf-8")
        report = build_concentration_report(ps, ta)
        cvt = report["concentration_vs_target"]
        assert approx(cvt["active_share"], 0.0, tol=1e-9), cvt


def test_active_share_positive_and_bounded_when_differ():
    state = _state({"a": 0.7, "b": 0.1, "c": 0.1, "d": 0.1})
    target = {"target_weights": {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}}
    with tempfile.TemporaryDirectory() as d:
        ps = Path(d) / "portfolio_state.json"
        ta = Path(d) / "target_allocation.json"
        ps.write_text(json.dumps(state), encoding="utf-8")
        ta.write_text(json.dumps(target), encoding="utf-8")
        report = build_concentration_report(ps, ta)
        cvt = report["concentration_vs_target"]
        assert cvt["active_share"] > 0.0, cvt
        assert 0.0 <= cvt["active_share"] <= 1.0, cvt
        # 0.5 * (0.45 + 0.15 + 0.15 + 0.15) = 0.45
        assert approx(cvt["active_share"], 0.45, tol=1e-6), cvt


def test_cash_buffer_from_target():
    state = _state({"a": 0.5, "b": 0.5})
    target = {"target_weights": {"a": 0.5, "b": 0.5}, "unallocated_pct": 0.2}
    with tempfile.TemporaryDirectory() as d:
        ps = Path(d) / "portfolio_state.json"
        ta = Path(d) / "target_allocation.json"
        ps.write_text(json.dumps(state), encoding="utf-8")
        ta.write_text(json.dumps(target), encoding="utf-8")
        report = build_concentration_report(ps, ta)
        assert approx(report["cash_buffer_pct"], 20.0), report.get("cash_buffer_pct")


def test_atomic_write_and_no_tmp_left():
    state = _state({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    with tempfile.TemporaryDirectory() as d:
        ps = Path(d) / "portfolio_state.json"
        out = Path(d) / "concentration_analytics.json"
        ps.write_text(json.dumps(state), encoding="utf-8")
        generate_concentration_report(ps, target_allocation_path=None, output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [
            p for p in Path(d).iterdir()
            if p.name.startswith(".concentration_analytics_")
        ]
        assert not leftovers, f"temp files left behind: {leftovers}"


def test_smoke_real_data():
    report = build_concentration_report(
        DEFAULT_PORTFOLIO_STATE_PATH, DEFAULT_TARGET_ALLOCATION_PATH
    )
    assert set(report["metrics"].keys()) == _SCHEMA_KEYS, report["metrics"].keys()
    assert report["metrics"]["num_positions"] >= 0, report
    assert report["execution_mode"] == "read_only_simulation", report


def test_all_finite_outputs():
    m = compute_concentration_metrics(_state({"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1}))
    for k, v in m.items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)
    for p, w in m["weights"].items():
        assert math.isfinite(w), (p, w)


def test_weights_sorted_descending():
    m = compute_concentration_metrics(_state({"a": 0.1, "b": 0.6, "c": 0.3}))
    vals = list(m["weights"].values())
    assert vals == sorted(vals, reverse=True), m["weights"]
    assert m["max_weight_protocol"] == "b", m
    assert m["min_weight_protocol"] == "a", m


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_concentration_analytics (SPA-V398)")
    run("None input → stable schema", test_empty_none_stable_schema)
    run("empty positions → stable schema", test_empty_positions_stable_schema)
    run("malformed inputs → no exception", test_malformed_inputs_no_exception)
    run("malformed JSON file → stable", test_malformed_json_file_stable)
    run("missing file → stable", test_missing_file_stable)
    run("equal-weight 4 positions", test_equal_weight_four_positions)
    run("single position", test_single_position)
    run("skewed weights hand-computed", test_skewed_weights_hand_computed)
    run("weights derived from USD", test_weights_derived_from_usd_when_weight_missing)
    run("weights normalize to 1.0", test_weights_normalize_to_one)
    run("monotonicity: more concentrated", test_monotonicity_more_concentrated)
    run("effective_num == 1/HHI", test_effective_num_is_inverse_hhi)
    run("top3 >= top1, bounded", test_top3_geq_top1_and_bounded)
    run("gini/entropy/hhi_norm in [0,1]", test_metric_ranges_bounded)
    run("active_share == 0 when equal", test_active_share_zero_when_equal)
    run("active_share > 0 when differ", test_active_share_positive_and_bounded_when_differ)
    run("cash buffer from target", test_cash_buffer_from_target)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    run("smoke real data", test_smoke_real_data)
    run("all outputs finite", test_all_finite_outputs)
    run("weights sorted descending", test_weights_sorted_descending)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
