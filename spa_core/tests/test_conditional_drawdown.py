"""
Tests for the paper-trading Conditional Drawdown-at-Risk module (SPA-V401).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_regime_segmentation.py /
test_advanced_ratios.py).

Run::
    python spa_core/tests/test_conditional_drawdown.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.conditional_drawdown import (
    DEFAULT_CONFIDENCES,
    compute_conditional_drawdown,
    generate_conditional_drawdown_report,
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

    The module reconstructs the underwater series off ``close_equity`` directly,
    and annualized return off ``daily_return_pct``; both are filled so the test
    curves behave like real equity_curve output.
    """
    bars = []
    first = closes[0] if closes else None
    prev = None
    for i, c in enumerate(closes):
        cum = 0.0 if not first else (c / first - 1.0) * 100.0
        dr = 0.0 if prev in (None, 0) else (c / prev - 1.0) * 100.0
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(c, 4),
            "close_equity": round(c, 4),
            "high_equity": round(c, 4),
            "low_equity": round(c, 4),
            "snapshots": 1,
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": round(cum, 6),
            "drawdown_pct": 0.0,  # intentionally zeroed: module must not rely on it
        })
        prev = c
    return bars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


_SCHEMA_KEYS = {
    "execution_mode", "annualization_days", "num_days", "first_date",
    "last_date", "max_drawdown_pct", "average_drawdown_pct",
    "pct_time_underwater", "annualized_return_pct", "drawdown_quantiles",
    "confidences", "levels",
}

_LEVEL_KEYS = {"confidence", "dar_pct", "cdar_pct", "tail_days", "rocdar"}


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_conditional_drawdown([])
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_days"] == 0, m
    assert m["max_drawdown_pct"] == 0.0, m
    assert m["pct_time_underwater"] == 0.0, m
    assert m["annualized_return_pct"] is None, m
    assert len(m["levels"]) == len(DEFAULT_CONFIDENCES), m
    assert m["execution_mode"] == "read_only_simulation", m


def test_single_day_stable_schema():
    m = compute_conditional_drawdown(_curve([100.0]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    assert m["num_days"] == 1, m
    assert m["max_drawdown_pct"] == 0.0, m  # no prior peak to be below
    assert m["pct_time_underwater"] == 0.0, m


def test_schema_keys_on_real_shape():
    m = compute_conditional_drawdown(_curve([100.0, 102.0, 99.0, 105.0]))
    assert set(m.keys()) == _SCHEMA_KEYS, m.keys()
    for lv in m["levels"]:
        assert set(lv.keys()) == _LEVEL_KEYS, lv.keys()
    assert set(m["drawdown_quantiles"].keys()) == {"p50", "p90", "p95", "p99"}, m


def test_monotonic_up_no_drawdown():
    m = compute_conditional_drawdown(_curve([100, 102, 104, 107, 110]))
    assert m["max_drawdown_pct"] == 0.0, m
    assert m["average_drawdown_pct"] == 0.0, m
    assert m["pct_time_underwater"] == 0.0, m
    for lv in m["levels"]:
        assert lv["dar_pct"] == 0.0, lv
        assert lv["cdar_pct"] == 0.0, lv
        assert lv["rocdar"] is None, lv  # CDaR == 0 → RoCDaR undefined


def test_max_drawdown_magnitude_formula():
    # 100 -> 110 (peak) -> 88 → deepest depth = (110-88)/110*100 = 20.0
    m = compute_conditional_drawdown(_curve([100, 110, 88, 99]))
    assert approx(m["max_drawdown_pct"], 20.0, tol=1e-6), m


def test_cdar_geq_dar_and_max_geq_cdar():
    m = compute_conditional_drawdown(_curve([100, 110, 90, 105, 80, 95, 70]))
    mdd = m["max_drawdown_pct"]
    for lv in m["levels"]:
        assert lv["cdar_pct"] >= lv["dar_pct"] - 1e-9, lv  # tail mean >= threshold
        assert mdd >= lv["cdar_pct"] - 1e-9, (mdd, lv)     # worst day bounds tail mean


def test_dar_monotonic_in_confidence():
    m = compute_conditional_drawdown(
        _curve([100, 110, 90, 105, 80, 95, 70, 102]),
        confidences=[0.80, 0.90, 0.95, 0.99],
    )
    dars = [lv["dar_pct"] for lv in m["levels"]]
    # Higher confidence selects a deeper quantile → DaR is non-decreasing.
    for a, b in zip(dars, dars[1:]):
        assert b >= a - 1e-9, dars


def test_cdar_monotonic_in_confidence():
    m = compute_conditional_drawdown(
        _curve([100, 110, 90, 105, 80, 95, 70, 102]),
        confidences=[0.80, 0.90, 0.95, 0.99],
    )
    cdars = [lv["cdar_pct"] for lv in m["levels"]]
    # A narrower (worse) tail can only raise the conditional mean depth.
    for a, b in zip(cdars, cdars[1:]):
        assert b >= a - 1e-9, cdars


def test_tail_days_positive_when_underwater():
    m = compute_conditional_drawdown(_curve([100, 110, 90, 105, 80]))
    for lv in m["levels"]:
        assert lv["tail_days"] >= 1, lv


def test_pct_time_underwater_bounds_and_value():
    # depths>0 on days 3,4,5 of 5 (after the 100->110 peak): 60% underwater.
    m = compute_conditional_drawdown(_curve([100, 110, 105, 100, 108]))
    assert 0.0 <= m["pct_time_underwater"] <= 100.0, m
    assert approx(m["pct_time_underwater"], 60.0, tol=1e-6), m


def test_average_le_max_drawdown():
    m = compute_conditional_drawdown(_curve([100, 110, 90, 105, 80, 95, 70]))
    assert m["average_drawdown_pct"] <= m["max_drawdown_pct"] + 1e-9, m


def test_drawdown_quantiles_ordered():
    m = compute_conditional_drawdown(_curve([100, 110, 90, 105, 80, 95, 70, 102]))
    q = m["drawdown_quantiles"]
    assert q["p50"] <= q["p90"] + 1e-9 <= q["p95"] + 1e-9, q
    assert q["p95"] <= q["p99"] + 1e-9, q


def test_flat_series_no_drawdown():
    m = compute_conditional_drawdown(_curve([100.0, 100.0, 100.0, 100.0]))
    assert m["max_drawdown_pct"] == 0.0, m
    assert m["average_drawdown_pct"] == 0.0, m
    assert m["pct_time_underwater"] == 0.0, m
    for lv in m["levels"]:
        assert lv["cdar_pct"] == 0.0 and lv["rocdar"] is None, lv


def test_rocdar_sign_follows_return():
    # Net-positive path with a drawdown → positive annualized return → RoCDaR > 0.
    m = compute_conditional_drawdown(_curve([100, 90, 130]))
    assert m["annualized_return_pct"] is not None and m["annualized_return_pct"] > 0, m
    found = [lv for lv in m["levels"] if lv["cdar_pct"] > 0]
    assert found, m
    for lv in found:
        assert lv["rocdar"] is not None and lv["rocdar"] > 0, lv


def test_invalid_confidences_fall_back_to_defaults():
    m = compute_conditional_drawdown(_curve([100, 110, 90]), confidences=[0, 1, 2, -5, "x"])
    assert m["confidences"] == [round(c, 6) for c in DEFAULT_CONFIDENCES], m
    assert len(m["levels"]) == len(DEFAULT_CONFIDENCES), m


def test_confidences_deduped_and_sorted():
    m = compute_conditional_drawdown(_curve([100, 110, 90]), confidences=[0.95, 0.90, 0.95])
    assert m["confidences"] == [0.9, 0.95], m


def test_does_not_rely_on_drawdown_pct_field():
    # _curve() zeroes drawdown_pct; the module must still detect the real DD.
    m = compute_conditional_drawdown(_curve([100, 120, 84]))
    assert m["max_drawdown_pct"] > 0, m  # (120-84)/120*100 = 30
    assert approx(m["max_drawdown_pct"], 30.0, tol=1e-6), m


def test_all_finite_outputs():
    m = compute_conditional_drawdown(_curve([100, 103, 99, 107, 101, 110, 95, 120, 80]))

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


def test_atomic_write_and_no_tmp_left():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "conditional_drawdown.json"
        generate_conditional_drawdown_report(output_path=out)
        assert out.exists(), "report file not written"
        leftovers = [p for p in Path(d).iterdir()
                     if p.name.startswith(".conditional_drawdown_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


def test_report_no_write_smoke_real_data():
    report = generate_conditional_drawdown_report(output_path=None)
    assert "generated_at" in report and "conditional_drawdown" in report, report
    cd = report["conditional_drawdown"]
    assert set(cd.keys()) == _SCHEMA_KEYS, cd.keys()
    assert cd["execution_mode"] == "read_only_simulation", report
    assert cd["confidences"] == [round(c, 6) for c in DEFAULT_CONFIDENCES], report


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_conditional_drawdown (SPA-V401)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single day → stable schema", test_single_day_stable_schema)
    run("schema keys on real shape", test_schema_keys_on_real_shape)
    run("monotonic up → no drawdown / RoCDaR None", test_monotonic_up_no_drawdown)
    run("max drawdown magnitude formula", test_max_drawdown_magnitude_formula)
    run("CDaR >= DaR and maxDD >= CDaR", test_cdar_geq_dar_and_max_geq_cdar)
    run("DaR monotonic in confidence", test_dar_monotonic_in_confidence)
    run("CDaR monotonic in confidence", test_cdar_monotonic_in_confidence)
    run("tail_days >= 1 when underwater", test_tail_days_positive_when_underwater)
    run("pct_time_underwater bounds + value", test_pct_time_underwater_bounds_and_value)
    run("average <= max drawdown", test_average_le_max_drawdown)
    run("drawdown quantiles ordered", test_drawdown_quantiles_ordered)
    run("flat series → no drawdown", test_flat_series_no_drawdown)
    run("RoCDaR sign follows return", test_rocdar_sign_follows_return)
    run("invalid confidences → defaults", test_invalid_confidences_fall_back_to_defaults)
    run("confidences deduped + sorted", test_confidences_deduped_and_sorted)
    run("does not rely on drawdown_pct field", test_does_not_rely_on_drawdown_pct_field)
    run("all outputs finite", test_all_finite_outputs)
    run("atomic write + no tmp left", test_atomic_write_and_no_tmp_left)
    run("report no-write smoke (real data)", test_report_no_write_smoke_real_data)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
