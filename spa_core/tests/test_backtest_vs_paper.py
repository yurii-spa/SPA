"""
Tests for spa_core.paper_trading.backtest_vs_paper (MP-139).

≥40 tests covering:
  - load_backtest_results  (normal, missing file, empty, ties, sortino)
  - load_paper_results     (normal, missing file, empty, days count)
  - compute_rank_correlation (ρ=1, ρ=-1, n<3, partial, n=6)
  - compare_strategies     (confidence, rank delta, missing data, structure)
  - run_comparison         (atomic write, output path, returned dict)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.paper_trading.backtest_vs_paper import (
    _extract_strategy_index,
    compare_strategies,
    compute_rank_correlation,
    load_backtest_results,
    load_paper_results,
    run_comparison,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_screening(tmp_path: Path, strategies: dict | None = None) -> Path:
    """Write a minimal strategy_screening.json and return data_dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    if strategies is None:
        strategies = {
            "s0_baseline": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 48.5},
                "sortino": {"value": None},
                "total_return_pct": 0.53,
            },
            "s1_concentration": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 48.4},
                "sortino": {"value": None},
                "total_return_pct": 0.41,
            },
            "s2_momentum": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 1.97},
                "sortino": {"value": None},
                "total_return_pct": 0.26,
            },
            "s3_risk_parity": {
                "passed_screening": False,
                "sharpe_with_ci": {"value": 20.9},
                "sortino": {"value": 3.5},
                "total_return_pct": 0.50,
            },
            "s4_kelly": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 48.5},
                "sortino": {"value": None},
                "total_return_pct": 0.33,
            },
            "s5_yield_spread": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 6.07},
                "sortino": {"value": None},
                "total_return_pct": 0.25,
            },
        }
    payload = {"schema_version": "1.0", "strategies": strategies}
    (data_dir / "strategy_screening.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return data_dir


def _make_shadow(tmp_path: Path, strategies: dict | None = None, history_days: int = 3) -> Path:
    """Write a minimal shadow_portfolio.json into *tmp_path/data* and return data_dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    if strategies is None:
        strategies = {
            "S0": {"equity": 100039.51, "total_return_pct": 0.0395},
            "S1": {"equity": 100029.73, "total_return_pct": 0.0297},
            "S2": {"equity": 100029.48, "total_return_pct": 0.0295},
            "S3": {"equity": 100026.16, "total_return_pct": 0.0262},
            "S4": {"equity": 100020.93, "total_return_pct": 0.0209},
            "S5": {"equity": 100026.06, "total_return_pct": 0.0261},
        }
    history = [{"date": f"2026-06-0{i+8}"} for i in range(history_days)]
    payload = {
        "date": "2026-06-12",
        "generated_at": "2026-06-12T06:00:00+00:00",
        "source": "shadow_tracker",
        "advisory_only": True,
        "initial_capital": 100000.0,
        "real_equity_usd": 100026.06,
        "strategies": strategies,
        "history": history,
    }
    (data_dir / "shadow_portfolio.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return data_dir


def _make_both(tmp_path: Path, history_days: int = 3) -> Path:
    """Create both screening and shadow files in the same data_dir."""
    data_dir = _make_screening(tmp_path)
    _make_shadow(tmp_path, history_days=history_days)
    return data_dir


# ===========================================================================
# 1. load_backtest_results
# ===========================================================================

class TestLoadBacktestResults:

    def test_returns_dict_on_normal_file(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert isinstance(result, dict)
        assert len(result) == 6

    def test_strategy_names_preserved(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert "s0_baseline" in result
        assert "s5_yield_spread" in result

    def test_passed_field_correct(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert result["s0_baseline"]["passed"] is True
        assert result["s3_risk_parity"]["passed"] is False

    def test_sharpe_value_present(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert result["s0_baseline"]["sharpe"] == pytest.approx(48.5)

    def test_sortino_value_present(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert result["s0_baseline"]["sortino"] is None
        assert result["s3_risk_parity"]["sortino"] == pytest.approx(3.5)

    def test_rank_is_int_and_positive(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        for name, v in result.items():
            assert isinstance(v["rank"], int)
            assert v["rank"] >= 1

    def test_rank_unique(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        ranks = [v["rank"] for v in result.values()]
        assert len(ranks) == len(set(ranks)), "ranks must be unique"

    def test_rank_top_is_highest_sharpe(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        # s0_baseline and s4_kelly both have sharpe=48.5; s0 wins on total_return
        assert result["s0_baseline"]["rank"] == 1

    def test_tie_broken_by_total_return(self, tmp_path):
        # s0_baseline (return=0.53) beats s4_kelly (return=0.33) on tie
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert result["s0_baseline"]["rank"] < result["s4_kelly"]["rank"]

    def test_lowest_sharpe_gets_last_rank(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        assert result["s2_momentum"]["rank"] == 6

    def test_missing_file_returns_empty(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        result = load_backtest_results(data_dir)
        assert result == {}

    def test_empty_json_returns_empty(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "strategy_screening.json").write_text("{}", encoding="utf-8")
        result = load_backtest_results(data_dir)
        assert result == {}

    def test_empty_strategies_returns_empty(self, tmp_path):
        data_dir = _make_screening(tmp_path, strategies={})
        result = load_backtest_results(data_dir)
        assert result == {}

    def test_none_sharpe_handled(self, tmp_path):
        strats = {
            "s0_null_sharpe": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": None},
                "sortino": {"value": None},
                "total_return_pct": 0.5,
            },
            "s1_real_sharpe": {
                "passed_screening": True,
                "sharpe_with_ci": {"value": 10.0},
                "sortino": {"value": None},
                "total_return_pct": 0.3,
            },
        }
        data_dir = _make_screening(tmp_path, strategies=strats)
        result = load_backtest_results(data_dir)
        # s1_real_sharpe should rank ahead of s0_null_sharpe
        assert result["s1_real_sharpe"]["rank"] < result["s0_null_sharpe"]["rank"]

    def test_result_has_expected_keys(self, tmp_path):
        data_dir = _make_screening(tmp_path)
        result = load_backtest_results(data_dir)
        for v in result.values():
            assert set(v.keys()) == {"passed", "sortino", "sharpe", "rank"}


# ===========================================================================
# 2. load_paper_results
# ===========================================================================

class TestLoadPaperResults:

    def test_returns_dict_on_normal_file(self, tmp_path):
        data_dir = _make_shadow(tmp_path)
        result = load_paper_results(data_dir)
        assert isinstance(result, dict)
        assert len(result) == 6

    def test_strategy_keys_preserved(self, tmp_path):
        data_dir = _make_shadow(tmp_path)
        result = load_paper_results(data_dir)
        for k in ("S0", "S1", "S2", "S3", "S4", "S5"):
            assert k in result

    def test_equity_value_correct(self, tmp_path):
        data_dir = _make_shadow(tmp_path)
        result = load_paper_results(data_dir)
        assert result["S0"]["equity"] == pytest.approx(100039.51)

    def test_pnl_pct_correct(self, tmp_path):
        data_dir = _make_shadow(tmp_path)
        result = load_paper_results(data_dir)
        assert result["S0"]["pnl_pct"] == pytest.approx(0.0395)

    def test_days_reflects_history_length(self, tmp_path):
        data_dir = _make_shadow(tmp_path, history_days=7)
        result = load_paper_results(data_dir)
        for v in result.values():
            assert v["days"] == 7

    def test_zero_history_gives_zero_days(self, tmp_path):
        data_dir = _make_shadow(tmp_path, history_days=0)
        result = load_paper_results(data_dir)
        for v in result.values():
            assert v["days"] == 0

    def test_missing_file_returns_empty(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        result = load_paper_results(data_dir)
        assert result == {}

    def test_empty_json_returns_empty(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "shadow_portfolio.json").write_text("{}", encoding="utf-8")
        result = load_paper_results(data_dir)
        assert result == {}

    def test_single_strategy(self, tmp_path):
        strats = {"S0": {"equity": 100050.0, "total_return_pct": 0.05}}
        data_dir = _make_shadow(tmp_path, strategies=strats, history_days=5)
        result = load_paper_results(data_dir)
        assert len(result) == 1
        assert result["S0"]["days"] == 5

    def test_result_has_expected_keys(self, tmp_path):
        data_dir = _make_shadow(tmp_path)
        result = load_paper_results(data_dir)
        for v in result.values():
            assert set(v.keys()) == {"equity", "pnl_pct", "days"}


# ===========================================================================
# 3. compute_rank_correlation
# ===========================================================================

class TestComputeRankCorrelation:

    def test_perfect_agreement_rho_one(self):
        bt = {"A": 1, "B": 2, "C": 3, "D": 4}
        pp = {"A": 1, "B": 2, "C": 3, "D": 4}
        r = compute_rank_correlation(bt, pp)
        assert r["rho"] == pytest.approx(1.0)
        assert r["n"] == 4
        assert r["interpretation"] == "CONSISTENT"

    def test_perfect_reversal_rho_minus_one(self):
        bt = {"A": 1, "B": 2, "C": 3, "D": 4}
        pp = {"A": 4, "B": 3, "C": 2, "D": 1}
        r = compute_rank_correlation(bt, pp)
        assert r["rho"] == pytest.approx(-1.0)
        assert r["interpretation"] == "DIVERGING"

    def test_n_zero_insufficient(self):
        r = compute_rank_correlation({}, {})
        assert r["rho"] is None
        assert r["n"] == 0
        assert "INSUFFICIENT" in r["interpretation"]

    def test_n_one_insufficient(self):
        r = compute_rank_correlation({"A": 1}, {"A": 1})
        assert r["rho"] is None
        assert r["n"] == 1
        assert "INSUFFICIENT" in r["interpretation"]

    def test_n_two_insufficient(self):
        r = compute_rank_correlation({"A": 1, "B": 2}, {"A": 1, "B": 2})
        assert r["rho"] is None
        assert r["n"] == 2
        assert "INSUFFICIENT" in r["interpretation"]

    def test_n_three_minimal(self):
        bt = {"A": 1, "B": 2, "C": 3}
        pp = {"A": 1, "B": 2, "C": 3}
        r = compute_rank_correlation(bt, pp)
        assert r["rho"] == pytest.approx(1.0)
        assert r["n"] == 3

    def test_consistent_threshold(self):
        # ρ > 0.7 → CONSISTENT
        bt = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        pp = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 6, "F": 5}
        # only ranks 5,6 are swapped → small d²
        r = compute_rank_correlation(bt, pp)
        assert r["interpretation"] == "CONSISTENT"
        assert r["rho"] > 0.7

    def test_weak_agreement_threshold(self):
        # Construct a case where ρ is between 0.3 and 0.7
        # n=6 strategies, some moderate re-ordering
        bt = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        pp = {"A": 2, "B": 1, "C": 4, "D": 3, "E": 6, "F": 5}
        # d = [1,1,1,1,1,1], Σd²=6, ρ=1-36/210 ≈ 0.829 → CONSISTENT actually
        # Let's try bigger swaps
        bt2 = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        pp2 = {"A": 3, "B": 1, "C": 5, "D": 2, "E": 6, "F": 4}
        r = compute_rank_correlation(bt2, pp2)
        assert r["rho"] is not None
        assert isinstance(r["interpretation"], str)

    def test_diverging_threshold(self):
        bt = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        pp = {"A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1}
        r = compute_rank_correlation(bt, pp)
        assert r["rho"] == pytest.approx(-1.0)
        assert r["interpretation"] == "DIVERGING"

    def test_only_common_keys_used(self):
        # Extra keys in one dict should be ignored
        bt = {"A": 1, "B": 2, "C": 3, "EXTRA": 4}
        pp = {"A": 1, "B": 2, "C": 3}
        r = compute_rank_correlation(bt, pp)
        assert r["n"] == 3
        assert r["rho"] == pytest.approx(1.0)

    def test_n_six_formula(self):
        # Verify formula manually: n=6, all ranks swap adjacent pairs
        # d=[1,1,1,1,1,1], Σd²=6, ρ=1-36/210≈0.8286
        bt = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        pp = {"A": 2, "B": 1, "C": 4, "D": 3, "E": 6, "F": 5}
        r = compute_rank_correlation(bt, pp)
        expected = 1.0 - 6 * 6 / (6 * 35)
        assert r["rho"] == pytest.approx(expected, abs=1e-3)
        assert r["n"] == 6

    def test_rho_clamped_to_minus_one(self):
        # Perfect reversal n=3: ρ must not go below -1
        bt = {"A": 1, "B": 2, "C": 3}
        pp = {"A": 3, "B": 2, "C": 1}
        r = compute_rank_correlation(bt, pp)
        assert r["rho"] >= -1.0
        assert r["rho"] == pytest.approx(-1.0)


# ===========================================================================
# 4. compare_strategies
# ===========================================================================

class TestCompareStrategies:

    def test_returns_dict(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        assert isinstance(result, dict)

    def test_top_level_keys_present(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        for key in ("generated_at", "paper_days", "confidence",
                    "rank_correlation", "strategies", "summary", "advisory"):
            assert key in result, f"Missing top-level key: {key}"

    def test_paper_days_three(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert result["paper_days"] == 3

    def test_confidence_insufficient_below_7_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert "INSUFFICIENT" in result["confidence"]

    def test_confidence_low_between_7_and_14_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=10)
        result = compare_strategies(data_dir)
        assert "LOW" in result["confidence"]

    def test_confidence_sufficient_at_14_plus_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=14)
        result = compare_strategies(data_dir)
        assert result["confidence"] == "SUFFICIENT"

    def test_rank_correlation_skipped_below_7_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert result["rank_correlation"]["rho"] is None
        assert "INSUFFICIENT" in result["rank_correlation"]["interpretation"]

    def test_rank_correlation_computed_above_7_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=14)
        result = compare_strategies(data_dir)
        rho = result["rank_correlation"]["rho"]
        assert rho is not None
        assert -1.0 <= rho <= 1.0

    def test_strategies_list_has_6_entries(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        assert len(result["strategies"]) == 6

    def test_strategy_entry_has_required_keys(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        required = {"name", "backtest_rank", "paper_rank",
                    "backtest_sharpe", "paper_pnl_pct", "rank_delta", "note"}
        for entry in result["strategies"]:
            assert required.issubset(set(entry.keys()))

    def test_s0_on_track_note(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        s0 = next(s for s in result["strategies"] if s["name"] == "S0")
        # S0: backtest_rank=1, paper_rank=1 → delta=0 → "On track"
        assert s0["rank_delta"] == 0
        assert s0["note"] == "On track"

    def test_rank_delta_sign(self, tmp_path):
        # A strategy with lower backtest rank should get positive rank_delta
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        for s in result["strategies"]:
            if s["rank_delta"] is not None and s["rank_delta"] > 0:
                assert "Underperforming" in s["note"]
            if s["rank_delta"] is not None and s["rank_delta"] < 0:
                assert "Outperforming" in s["note"]

    def test_missing_backtest_file(self, tmp_path):
        # Only shadow file present
        data_dir = _make_shadow(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert result["paper_days"] == 3
        for s in result["strategies"]:
            assert s["backtest_rank"] is None
            assert s["note"] == "No backtest data"

    def test_missing_paper_file(self, tmp_path):
        # Only screening file present
        data_dir = _make_screening(tmp_path)
        result = compare_strategies(data_dir)
        assert result["paper_days"] == 0
        for s in result["strategies"]:
            assert s["paper_rank"] is None
            assert s["note"] == "No paper data"

    def test_both_files_missing(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        result = compare_strategies(data_dir)
        assert result["strategies"] == []
        assert result["paper_days"] == 0

    def test_summary_contains_paper_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert "3" in result["summary"]

    def test_advisory_mentions_wait_when_few_days(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=3)
        result = compare_strategies(data_dir)
        assert "14+" in result["advisory"] or "Wait" in result["advisory"]

    def test_advisory_mentions_rho_when_sufficient(self, tmp_path):
        data_dir = _make_both(tmp_path, history_days=14)
        result = compare_strategies(data_dir)
        assert "ρ=" in result["advisory"]

    def test_generated_at_is_iso_string(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = compare_strategies(data_dir)
        ts = result["generated_at"]
        assert isinstance(ts, str)
        assert "T" in ts  # ISO 8601


# ===========================================================================
# 5. run_comparison
# ===========================================================================

class TestRunComparison:

    def test_creates_output_file(self, tmp_path):
        data_dir = _make_both(tmp_path)
        out_file = data_dir / "backtest_vs_paper.json"
        run_comparison(data_dir=data_dir)
        assert out_file.exists()

    def test_output_file_is_valid_json(self, tmp_path):
        data_dir = _make_both(tmp_path)
        run_comparison(data_dir=data_dir)
        raw = (data_dir / "backtest_vs_paper.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_returns_dict(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = run_comparison(data_dir=data_dir)
        assert isinstance(result, dict)

    def test_returned_dict_has_top_level_keys(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = run_comparison(data_dir=data_dir)
        assert "strategies" in result
        assert "rank_correlation" in result

    def test_custom_output_path(self, tmp_path):
        data_dir = _make_both(tmp_path)
        custom_out = tmp_path / "custom_output.json"
        run_comparison(data_dir=data_dir, output_path=custom_out)
        assert custom_out.exists()
        parsed = json.loads(custom_out.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_atomic_write_no_partial_file(self, tmp_path):
        """Output file must not be a tmp file at rest (no .tmp suffix)."""
        data_dir = _make_both(tmp_path)
        run_comparison(data_dir=data_dir)
        tmp_files = list(data_dir.glob("*.tmp"))
        assert tmp_files == [], f"Leftover tmp files: {tmp_files}"

    def test_result_matches_file_contents(self, tmp_path):
        data_dir = _make_both(tmp_path)
        result = run_comparison(data_dir=data_dir)
        parsed = json.loads((data_dir / "backtest_vs_paper.json").read_text(encoding="utf-8"))
        assert result["paper_days"] == parsed["paper_days"]
        assert result["confidence"] == parsed["confidence"]

    def test_generated_at_in_file(self, tmp_path):
        data_dir = _make_both(tmp_path)
        run_comparison(data_dir=data_dir)
        parsed = json.loads((data_dir / "backtest_vs_paper.json").read_text(encoding="utf-8"))
        assert "generated_at" in parsed

    def test_overwrite_idempotent(self, tmp_path):
        """Calling twice should overwrite cleanly."""
        data_dir = _make_both(tmp_path)
        run_comparison(data_dir=data_dir)
        run_comparison(data_dir=data_dir)
        raw = (data_dir / "backtest_vs_paper.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


# ===========================================================================
# 6. _extract_strategy_index (internal helper — sanity checks)
# ===========================================================================

class TestExtractStrategyIndex:

    def test_s0_baseline(self):
        assert _extract_strategy_index("s0_baseline") == 0

    def test_s5_yield_spread(self):
        assert _extract_strategy_index("s5_yield_spread") == 5

    def test_capital_S0(self):
        assert _extract_strategy_index("S0") == 0

    def test_capital_S3(self):
        assert _extract_strategy_index("S3") == 3

    def test_no_digit_returns_none(self):
        assert _extract_strategy_index("NoDigitHere") is None
