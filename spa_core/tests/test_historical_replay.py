"""
Tests for the paper-trading historical-replay module (SPA-V385).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_calendar_returns.py).

Run::
    python spa_core/tests/test_historical_replay.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.historical_replay import (
    _aligned_dates,
    _daily_factor,
    compute_protocol_summary,
    compute_strategy_summary,
    generate_historical_replay_report,
    load_historical_apy,
    replay_best_apy,
    replay_buy_and_hold_best,
    replay_equal_weight,
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


def _write_history(tmpdir, protocols, data_source="synthetic"):
    """Write a tiny historical_apy.json fixture and return its path.

    ``protocols`` is ``{proto_id: [(date, apy), ...]}``.
    """
    payload = {
        "generated_at": "2026-01-01T00:00:00Z",
        "data_source": data_source,
        "days": 0,
        "protocols": {
            pid: [{"date": d, "apy": a, "tvl_usd": 1.0} for d, a in series]
            for pid, series in protocols.items()
        },
    }
    p = Path(tmpdir) / "historical_apy.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_daily_factor_zero():
    assert approx(_daily_factor(0.0), 1.0), _daily_factor(0.0)


def test_daily_factor_positive():
    assert _daily_factor(6.05) > 1.0
    # compounding the daily factor 365 times reconstructs the annual APY.
    f = _daily_factor(10.0)
    annual = f ** 365
    assert approx(annual, 1.10, tol=1e-9), annual


def test_daily_factor_known_value():
    # (1 + 7.3/100) ** (1/365)
    expected = (1.0 + 7.3 / 100.0) ** (1.0 / 365.0)
    assert approx(_daily_factor(7.3), expected, tol=1e-12), _daily_factor(7.3)


def test_load_missing_returns_empty():
    loaded = load_historical_apy("/no/such/file/historical_apy.json")
    assert loaded["protocols"] == {}, loaded
    assert loaded["data_source"] is None, loaded


def test_empty_report_valid_schema():
    rep = generate_historical_replay_report(
        path="/no/such/file/historical_apy.json", output_path=None,
    )
    for key in ("generated_at", "source", "num_days", "num_protocols",
                "strategies", "best_strategy", "per_protocol"):
        assert key in rep, (key, list(rep))
    assert rep["num_days"] == 0, rep
    assert rep["strategies"] == {} and rep["per_protocol"] == {}, rep
    assert rep["best_strategy"] is None, rep


def test_aligned_dates_intersection():
    protos = {
        "a": {"2026-01-01": 5.0, "2026-01-02": 5.0, "2026-01-03": 5.0},
        "b": {"2026-01-02": 4.0, "2026-01-03": 4.0, "2026-01-04": 4.0},
    }
    assert _aligned_dates(protos) == ["2026-01-02", "2026-01-03"], _aligned_dates(protos)


def test_equal_weight_curve_length():
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 5.0), ("2026-01-02", 5.0), ("2026-01-03", 5.0)],
            "b": [("2026-01-01", 7.0), ("2026-01-02", 7.0), ("2026-01-03", 7.0)],
        })
        loaded = load_historical_apy(p)
        dates = _aligned_dates(loaded["protocols"])
        curve = replay_equal_weight(loaded["protocols"], dates, 10_000.0)
        assert len(curve) == len(dates) == 3, (len(curve), len(dates))
        # cumulative return must be monotonically increasing for positive APYs.
        cums = [b["cumulative_return_pct"] for b in curve]
        assert cums == sorted(cums) and cums[0] > 0, cums


def test_equal_weight_compounding_correctness():
    # Single protocol, flat 10% APY for 2 days, $100 start.
    f = _daily_factor(10.0)
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {"a": [("2026-01-01", 10.0), ("2026-01-02", 10.0)]})
        loaded = load_historical_apy(p)
        dates = _aligned_dates(loaded["protocols"])
        curve = replay_equal_weight(loaded["protocols"], dates, 100.0)
        # curve equity is rounded to 4 decimals -> compare within rounding tol.
        assert approx(curve[0]["equity"], 100.0 * f, tol=1e-4), curve[0]
        assert approx(curve[1]["equity"], 100.0 * f * f, tol=1e-4), curve[1]


def test_best_apy_picks_highest_each_day():
    # Day 1: a (8) wins; day 2: b (9) wins.
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 8.0), ("2026-01-02", 3.0)],
            "b": [("2026-01-01", 2.0), ("2026-01-02", 9.0)],
        })
        loaded = load_historical_apy(p)
        dates = _aligned_dates(loaded["protocols"])
        curve = replay_best_apy(loaded["protocols"], dates, 100.0)
        f_day1 = _daily_factor(8.0)
        f_day2 = _daily_factor(9.0)
        assert approx(curve[0]["equity"], 100.0 * f_day1, tol=1e-4), curve[0]
        assert approx(curve[1]["equity"], 100.0 * f_day1 * f_day2, tol=1e-4), curve[1]


def test_buy_and_hold_selects_highest_mean():
    # b has higher mean apy (mean 6.0) than a (mean 5.0).
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 4.0), ("2026-01-02", 6.0)],
            "b": [("2026-01-01", 7.0), ("2026-01-02", 5.0)],
        })
        loaded = load_historical_apy(p)
        dates = _aligned_dates(loaded["protocols"])
        curve, selected = replay_buy_and_hold_best(loaded["protocols"], dates, 100.0)
        assert selected == "b", selected
        f = _daily_factor(7.0) * _daily_factor(5.0)
        assert approx(curve[-1]["equity"], 100.0 * f, tol=1e-4), curve[-1]


def test_strategy_summary_fields_and_drawdown():
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 5.0), ("2026-01-02", -90.0), ("2026-01-03", 5.0)],
        })
        loaded = load_historical_apy(p)
        dates = _aligned_dates(loaded["protocols"])
        curve = replay_equal_weight(loaded["protocols"], dates, 1000.0)
        s = compute_strategy_summary(curve)
        for key in ("start_equity", "end_equity", "total_return_pct",
                    "annualized_apy_pct", "num_days", "mean_daily_return_pct",
                    "daily_volatility_pct", "best_day", "worst_day",
                    "max_drawdown_pct"):
            assert key in s, key
        assert s["num_days"] == 3, s
        assert s["max_drawdown_pct"] <= 0.0, s
        # the -90% APY day must be the worst day.
        assert s["worst_day"]["date"] == "2026-01-02", s


def test_empty_curve_summary_stable():
    s = compute_strategy_summary([])
    assert s["num_days"] == 0 and s["start_equity"] is None, s
    assert s["max_drawdown_pct"] == 0.0 and s["total_return_pct"] == 0.0, s


def test_per_protocol_block_correctness():
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 4.0), ("2026-01-02", 6.0)],
            "b": [("2026-01-01", 10.0), ("2026-01-02", 10.0)],
        })
        loaded = load_historical_apy(p)
        per = compute_protocol_summary(loaded["protocols"])
        assert set(per) == {"a", "b"}, per
        assert approx(per["a"]["mean_apy"], 5.0, tol=1e-6), per["a"]
        assert per["a"]["min_apy"] == 4.0 and per["a"]["max_apy"] == 6.0, per["a"]
        assert per["a"]["num_points"] == 2, per["a"]
        # b: flat 10% APY 2 days -> period return = factor^2 - 1.
        f = _daily_factor(10.0)
        assert approx(per["b"]["period_return_pct"], (f * f - 1.0) * 100.0, tol=1e-4), per["b"]


def test_best_strategy_selection():
    # b dominates (constant 12% vs a constant 3%) -> all strategies favor b;
    # best_apy and buy_and_hold_best should win equal_weight; best_strategy set.
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 3.0), ("2026-01-02", 3.0), ("2026-01-03", 3.0)],
            "b": [("2026-01-01", 12.0), ("2026-01-02", 12.0), ("2026-01-03", 12.0)],
        })
        rep = generate_historical_replay_report(path=p, starting_capital=10_000.0,
                                                output_path=None)
        assert rep["best_strategy"] is not None, rep
        name = rep["best_strategy"]["name"]
        strat_returns = {n: s["total_return_pct"] for n, s in rep["strategies"].items()}
        assert strat_returns[name] == max(strat_returns.values()), strat_returns
        # buy_and_hold_best must pick b.
        assert rep["strategies"]["buy_and_hold_best"]["selected_protocol"] == "b", rep


def test_malformed_records_skipped():
    with tempfile.TemporaryDirectory() as td:
        payload = {
            "data_source": "synthetic",
            "protocols": {
                "a": [
                    {"date": "2026-01-01", "apy": 5.0, "tvl_usd": 1.0},
                    {"date": "2026-01-02", "apy": "bad", "tvl_usd": 1.0},  # bad apy
                    {"date": None, "apy": 5.0},                            # bad date
                    "not-a-dict",                                          # junk
                    {"date": "2026-01-03", "apy": 5.0},
                ],
            },
        }
        p = Path(td) / "historical_apy.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_historical_apy(p)
        # only the two well-formed records survive.
        assert set(loaded["protocols"]["a"]) == {"2026-01-01", "2026-01-03"}, \
            loaded["protocols"]["a"]


def test_total_return_sign_consistency():
    # all positive APYs -> all strategies must have positive total_return.
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 5.0), ("2026-01-02", 6.0), ("2026-01-03", 4.0)],
            "b": [("2026-01-01", 7.0), ("2026-01-02", 5.0), ("2026-01-03", 8.0)],
        })
        rep = generate_historical_replay_report(path=p, starting_capital=10_000.0,
                                                output_path=None)
        for name, strat in rep["strategies"].items():
            assert strat["total_return_pct"] > 0, (name, strat["total_return_pct"])
            assert strat["annualized_apy_pct"] > 0, (name, strat["annualized_apy_pct"])


def test_report_writes_file():
    with tempfile.TemporaryDirectory() as td:
        p = _write_history(td, {
            "a": [("2026-01-01", 5.0), ("2026-01-02", 6.0)],
            "b": [("2026-01-01", 7.0), ("2026-01-02", 5.0)],
        })
        out = Path(td) / "out" / "historical_replay.json"
        rep = generate_historical_replay_report(path=p, output_path=out)
        assert out.exists(), out
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["num_protocols"] == 2 == rep["num_protocols"], on_disk
        assert on_disk["data_source"] == "synthetic", on_disk


def test_report_real_data_smoke():
    rep = generate_historical_replay_report(output_path=None)
    for key in ("generated_at", "strategies", "per_protocol", "num_days"):
        assert key in rep, key
    assert isinstance(rep["num_days"], int), rep
    # if real data present, all three strategies must be there.
    if rep["num_days"] > 0:
        assert set(rep["strategies"]) == {
            "equal_weight", "best_apy", "buy_and_hold_best"}, list(rep["strategies"])
        for strat in rep["strategies"].values():
            assert len(strat["curve"]) == rep["num_days"], len(strat["curve"])


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_historical_replay (SPA-V385)")
    run("daily_factor apy=0 -> 1.0", test_daily_factor_zero)
    run("daily_factor positive -> >1 / annual roundtrip", test_daily_factor_positive)
    run("daily_factor known value", test_daily_factor_known_value)
    run("load missing -> empty", test_load_missing_returns_empty)
    run("empty input -> valid empty report", test_empty_report_valid_schema)
    run("aligned dates = intersection", test_aligned_dates_intersection)
    run("equal_weight curve length == aligned dates", test_equal_weight_curve_length)
    run("equal_weight compounding correctness", test_equal_weight_compounding_correctness)
    run("best_apy picks highest apy per day", test_best_apy_picks_highest_each_day)
    run("buy_and_hold selects highest mean", test_buy_and_hold_selects_highest_mean)
    run("strategy summary fields + max_dd<=0", test_strategy_summary_fields_and_drawdown)
    run("empty curve summary stable", test_empty_curve_summary_stable)
    run("per_protocol block correctness", test_per_protocol_block_correctness)
    run("best_strategy selection", test_best_strategy_selection)
    run("malformed records skipped", test_malformed_records_skipped)
    run("total_return sign consistency", test_total_return_sign_consistency)
    run("report writes file", test_report_writes_file)
    run("report real-data smoke", test_report_real_data_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
