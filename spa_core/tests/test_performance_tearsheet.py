"""
Tests for the consolidated performance tearsheet module (SPA-V396).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_return_distribution.py /
test_monte_carlo_projection.py).

Run::
    python spa_core/tests/test_performance_tearsheet.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.performance_tearsheet import (
    SOURCE_FILES,
    build_tearsheet,
    generate_tearsheet_report,
    _age_hours,
    _parse_ts,
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

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago=1.0):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _full_data_dir(tmp: Path, *, ts=None):
    """Write a complete, realistic set of source report JSONs into *tmp*."""
    ts = ts or _ts(2.0)
    reports = {
        "equity_curve_daily.json": {
            "generated_at": ts,
            "summary": {
                "num_days": 8, "start_equity": 100000.0, "end_equity": 98815.79,
                "total_return_pct": -1.1842, "positive_days": 3, "negative_days": 4,
                "first_date": "2026-05-15", "last_date": "2026-05-22",
            },
        },
        "risk_metrics.json": {
            "generated_at": ts,
            "metrics": {
                "sharpe_ratio": -5.38, "sortino_ratio": -4.1, "calmar_ratio": -2.0,
                "profit_factor": 0.7, "win_loss_ratio": 0.9, "daily_volatility_pct": 0.4546,
                "annualized_vol_pct": 8.7, "downside_deviation_pct": 0.5,
                "max_drawdown_pct": -1.5886, "best_day": 0.3473, "worst_day": -1.0533,
                "annualized_return_pct": -46.69, "win_rate_pct": 42.86,
            },
        },
        "rolling_performance.json": {
            "generated_at": ts,
            "windows": [7, 30],
            "by_window": {
                "7": {"return_pct": -1.1, "annualized_return_pct": -40.0, "volatility_pct": 0.45,
                       "sharpe_ratio": -5.0, "max_drawdown_pct": -1.5, "win_rate_pct": 42.0, "num_days": 7},
                "30": {"return_pct": None, "annualized_return_pct": None, "volatility_pct": None,
                        "sharpe_ratio": None, "max_drawdown_pct": None, "win_rate_pct": None, "num_days": 7},
            },
        },
        "drawdown_analysis.json": {
            "generated_at": ts,
            "summary": {
                "max_drawdown_pct": -1.5886, "avg_drawdown_pct": -0.8, "num_episodes": 2,
                "recovered_episodes": 1, "ongoing_episodes": 1, "longest_drawdown_days": 3,
                "longest_recovery_days": 2, "currently_in_drawdown": True,
                "current_drawdown_pct": -1.2, "time_underwater_pct": 60.0,
            },
        },
        "return_distribution.json": {
            "generated_at": ts,
            "distribution": {
                "count": 7, "mean_pct": -0.171, "median_pct": -0.1, "stdev_pct": 0.4546,
                "skewness": -0.3, "excess_kurtosis": 0.5, "min_pct": -1.0533, "max_pct": 0.3473,
                "var": {"95": -1.05, "99": -1.05}, "cvar": {"95": -1.05, "99": -1.05},
                "percentiles": {"p5": -1.05, "p50": -0.1, "p95": 0.34},
            },
        },
        "calendar_returns.json": {
            "generated_at": ts,
            "summary": {
                "num_realised_days": 7, "num_months": 1, "num_weeks": 2,
                "best_month": "2026-05", "worst_month": "2026-05", "positive_months": 0,
                "negative_months": 1, "longest_win_streak": 3, "longest_loss_streak": 3,
                "current_streak_kind": "loss", "current_streak_len": 3,
            },
        },
        "benchmark_comparison.json": {
            "generated_at": ts,
            "comparison": {
                "benchmark_kind": "flat_risk_free", "benchmark_annual_pct": 4.0,
                "portfolio_total_return_pct": -1.1992, "benchmark_total_return_pct": 0.0752,
                "excess_total_return_pct": -1.2744, "tracking_error_pct": 0.4546,
                "information_ratio": -0.4001, "information_ratio_annualized": -7.64,
                "beta": None, "correlation": None, "up_capture": None, "down_capture": None,
                "days_outperformed": 3, "days_underperformed": 4,
            },
        },
        "monte_carlo_projection.json": {
            "generated_at": ts,
            "projection": {
                "inputs": {"horizon": 30, "simulations": 10000, "seed": 42},
                "terminal_equity": {"p5": 89960.01, "p50": 93901.53, "p95": 97664.17},
                "terminal_return_pct": {"p5": -8.96, "p50": -4.97, "p95": -1.17},
                "probability_of_profit": 0.0167, "probability_of_loss": 0.9833,
                "expected_max_drawdown_pct": -5.63,
            },
        },
    }
    for fname, obj in reports.items():
        (tmp / fname).write_text(json.dumps(obj), encoding="utf-8")


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_full_coverage():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        r = build_tearsheet(tmp, now=NOW)
        cov = r["coverage"]
        assert cov["expected"] == len(SOURCE_FILES), cov
        assert cov["available"] == len(SOURCE_FILES), cov
        assert cov["missing"] == 0, cov
        assert cov["complete"] is True, cov
        assert cov["coverage_pct"] == 100.0, cov


def test_stable_schema_when_empty():
    """Empty data dir -> every section present with available=False, no raise."""
    with tempfile.TemporaryDirectory() as d:
        r = build_tearsheet(Path(d), now=NOW)
        assert r["coverage"]["available"] == 0
        assert r["coverage"]["missing"] == len(SOURCE_FILES)
        assert r["coverage"]["complete"] is False
        ts = r["tearsheet"]
        # all expected sections exist
        for sec in ("overview", "risk", "rolling_performance", "drawdown_analysis",
                     "return_distribution", "calendar_returns", "benchmark_comparison",
                     "monte_carlo_projection"):
            assert sec in ts, f"missing section {sec}"
            assert ts[sec]["available"] is False, sec
        # sources all marked unavailable
        for name, meta in r["sources"].items():
            assert meta["available"] is False, name
            assert meta["stale"] is None, name


def test_overview_values_extracted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        ov = build_tearsheet(tmp, now=NOW)["tearsheet"]["overview"]
        assert ov["available"] is True
        assert ov["num_days"] == 8
        assert ov["start_equity"] == 100000.0
        assert ov["end_equity"] == 98815.79
        assert ov["total_return_pct"] == -1.1842
        assert ov["annualized_return_pct"] == -46.69  # pulled from risk_metrics
        assert ov["win_rate_pct"] == 42.86


def test_risk_section_extracted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        risk = build_tearsheet(tmp, now=NOW)["tearsheet"]["risk"]
        assert risk["available"] is True
        assert risk["sharpe_ratio"] == -5.38
        assert risk["sortino_ratio"] == -4.1
        assert risk["max_drawdown_pct"] == -1.5886
        assert risk["worst_day"] == -1.0533


def test_rolling_section_per_window():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        roll = build_tearsheet(tmp, now=NOW)["tearsheet"]["rolling_performance"]
        assert roll["available"] is True
        assert roll["windows"] == [7, 30]
        assert set(roll["by_window"].keys()) == {"7", "30"}
        assert roll["by_window"]["7"]["return_pct"] == -1.1
        assert roll["by_window"]["30"]["return_pct"] is None


def test_distribution_var_cvar_passthrough():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        dist = build_tearsheet(tmp, now=NOW)["tearsheet"]["return_distribution"]
        assert dist["available"] is True
        assert dist["count"] == 7
        assert dist["var"] == {"95": -1.05, "99": -1.05}
        assert dist["cvar"]["95"] == -1.05
        assert dist["percentiles"]["p50"] == -0.1


def test_benchmark_section_extracted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        b = build_tearsheet(tmp, now=NOW)["tearsheet"]["benchmark_comparison"]
        assert b["available"] is True
        assert b["excess_total_return_pct"] == -1.2744
        assert b["information_ratio"] == -0.4001
        assert b["beta"] is None  # flat benchmark
        assert b["days_outperformed"] == 3


def test_projection_section_extracted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        p = build_tearsheet(tmp, now=NOW)["tearsheet"]["monte_carlo_projection"]
        assert p["available"] is True
        assert p["probability_of_profit"] == 0.0167
        assert p["terminal_equity"]["p50"] == 93901.53
        assert p["expected_max_drawdown_pct"] == -5.63


def test_calendar_section_extracted():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        c = build_tearsheet(tmp, now=NOW)["tearsheet"]["calendar_returns"]
        assert c["available"] is True
        assert c["longest_win_streak"] == 3
        assert c["current_streak_kind"] == "loss"


def test_partial_coverage():
    """Only some reports present -> coverage reflects it, present sections valid."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        # remove three reports
        (tmp / "monte_carlo_projection.json").unlink()
        (tmp / "benchmark_comparison.json").unlink()
        (tmp / "rolling_performance.json").unlink()
        r = build_tearsheet(tmp, now=NOW)
        cov = r["coverage"]
        assert cov["available"] == len(SOURCE_FILES) - 3, cov
        assert cov["missing"] == 3, cov
        assert cov["complete"] is False
        assert r["tearsheet"]["monte_carlo_projection"]["available"] is False
        assert r["tearsheet"]["risk"]["available"] is True


def test_malformed_source_degrades():
    """A corrupt JSON file is treated as missing, no raise."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        (tmp / "risk_metrics.json").write_text("{not valid json", encoding="utf-8")
        r = build_tearsheet(tmp, now=NOW)
        assert r["tearsheet"]["risk"]["available"] is False
        assert r["sources"]["risk_metrics"]["available"] is False
        # other sections still fine
        assert r["tearsheet"]["overview"]["available"] is True


def test_staleness_flag():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # all reports generated 48h ago
        _full_data_dir(tmp, ts=_ts(48.0))
        r = build_tearsheet(tmp, stale_hours=24.0, now=NOW)
        assert r["coverage"]["stale"] == len(SOURCE_FILES), r["coverage"]
        for name, meta in r["sources"].items():
            assert meta["stale"] is True, name
            assert meta["age_hours"] is not None and meta["age_hours"] >= 47.9, meta


def test_not_stale_when_fresh():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp, ts=_ts(1.0))
        r = build_tearsheet(tmp, stale_hours=24.0, now=NOW)
        assert r["coverage"]["stale"] == 0, r["coverage"]


def test_age_hours_none_on_missing_ts():
    assert _age_hours(None, NOW) is None
    assert _age_hours("not-a-date", NOW) is None
    assert _age_hours(123, NOW) is None


def test_parse_ts_handles_z_suffix():
    dt = _parse_ts("2026-06-09T12:00:00Z")
    assert dt is not None and dt.tzinfo is not None
    # naive timestamp gets UTC attached
    dt2 = _parse_ts("2026-06-09T12:00:00")
    assert dt2 is not None and dt2.tzinfo is not None


def test_age_hours_positive_for_past():
    age = _age_hours(_ts(5.0), NOW)
    assert age is not None and abs(age - 5.0) < 0.01, age


def test_generate_writes_file_atomically():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        out = tmp / "out" / "performance_tearsheet.json"
        r = generate_tearsheet_report(tmp, out, stale_hours=24.0)
        assert out.exists(), "output file not written"
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["coverage"]["available"] == len(SOURCE_FILES)
        assert on_disk["tearsheet"]["overview"]["num_days"] == 8
        # returned object equals on-disk object
        assert on_disk["coverage"]["complete"] == r["coverage"]["complete"]
        # no leftover temp files
        leftovers = [p.name for p in (tmp / "out").iterdir() if p.name.startswith(".tearsheet_")]
        assert not leftovers, f"temp files left behind: {leftovers}"


def test_sources_record_filenames():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _full_data_dir(tmp)
        r = build_tearsheet(tmp, now=NOW)
        for name, fname in SOURCE_FILES.items():
            assert r["sources"][name]["file"] == fname, name


def test_top_level_schema_keys():
    with tempfile.TemporaryDirectory() as d:
        r = build_tearsheet(Path(d), now=NOW)
        for k in ("generated_at", "data_dir", "stale_hours", "coverage", "sources", "tearsheet"):
            assert k in r, f"missing top-level key {k}"


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("test_performance_tearsheet (SPA-V396)")
    tests = [
        ("full coverage", test_full_coverage),
        ("stable schema when empty", test_stable_schema_when_empty),
        ("overview values extracted", test_overview_values_extracted),
        ("risk section extracted", test_risk_section_extracted),
        ("rolling section per window", test_rolling_section_per_window),
        ("distribution var/cvar passthrough", test_distribution_var_cvar_passthrough),
        ("benchmark section extracted", test_benchmark_section_extracted),
        ("projection section extracted", test_projection_section_extracted),
        ("calendar section extracted", test_calendar_section_extracted),
        ("partial coverage", test_partial_coverage),
        ("malformed source degrades", test_malformed_source_degrades),
        ("staleness flag", test_staleness_flag),
        ("not stale when fresh", test_not_stale_when_fresh),
        ("age_hours none on missing ts", test_age_hours_none_on_missing_ts),
        ("parse_ts handles Z suffix", test_parse_ts_handles_z_suffix),
        ("age_hours positive for past", test_age_hours_positive_for_past),
        ("generate writes file atomically", test_generate_writes_file_atomically),
        ("sources record filenames", test_sources_record_filenames),
        ("top-level schema keys", test_top_level_schema_keys),
    ]
    for name, fn in tests:
        run(name, fn)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
