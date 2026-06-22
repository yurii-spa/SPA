#!/usr/bin/env python3
"""Unit tests for MP-1076 DeFiProtocolLendingMarketHealthScorer.

Run:
    python3 -m unittest spa_core/tests/test_defi_protocol_lending_market_health_scorer.py -v

Pure stdlib unittest — no pytest, no numpy, no external dependencies.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_protocol_lending_market_health_scorer import (
    DeFiProtocolLendingMarketHealthScorer,
    analyze,
    _score_utilization,
    _score_bad_debt,
    _score_reserve_coverage,
    _score_concentration,
    _score_oracle,
    _score_market_pause,
    _score_incentive,
    _health_label,
    _compute_utilization_rate,
    _compute_bad_debt_ratio,
    _compute_reserve_coverage,
    _load_json_list,
    _atomic_write,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    LABEL_PRISTINE,
    LABEL_HEALTHY,
    LABEL_WATCH,
    LABEL_STRESSED,
    WEIGHTS,
    SOURCE_NAME,
    SCHEMA_VERSION,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _good_data(**overrides) -> dict:
    """Return a valid healthy-protocol snapshot (can be overridden)."""
    base = {
        "protocol_name":                  "TestProtocol",
        "total_supplied_usd":             1_000_000.0,
        "total_borrowed_usd":               650_000.0,
        "bad_debt_usd":                           0.0,
        "reserve_factor_pct":                    10.0,
        "reserve_balance_usd":               50_000.0,
        "top_borrower_concentration_pct":        5.0,
        "liquidation_incentive_pct":            10.0,
        "oracle_type":                    "chainlink",
        "paused_markets":                          0,
        "total_markets":                          10,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _compute_utilization_rate
# ===========================================================================

class TestComputeUtilizationRate(unittest.TestCase):

    def test_normal_case(self):
        rate = _compute_utilization_rate(1_000_000, 650_000)
        self.assertAlmostEqual(rate, 65.0, places=4)

    def test_zero_supply_returns_zero(self):
        self.assertEqual(_compute_utilization_rate(0, 500_000), 0.0)

    def test_negative_supply_returns_zero(self):
        self.assertEqual(_compute_utilization_rate(-100, 50), 0.0)

    def test_zero_borrow(self):
        self.assertEqual(_compute_utilization_rate(1_000_000, 0), 0.0)

    def test_fully_borrowed(self):
        rate = _compute_utilization_rate(1_000_000, 1_000_000)
        self.assertAlmostEqual(rate, 100.0, places=4)

    def test_over_borrowed_clamped_100(self):
        rate = _compute_utilization_rate(1_000_000, 1_100_000)
        self.assertAlmostEqual(rate, 100.0, places=4)

    def test_small_values(self):
        rate = _compute_utilization_rate(100, 50)
        self.assertAlmostEqual(rate, 50.0, places=4)


# ===========================================================================
# 2. _compute_bad_debt_ratio
# ===========================================================================

class TestComputeBadDebtRatio(unittest.TestCase):

    def test_no_bad_debt(self):
        self.assertEqual(_compute_bad_debt_ratio(0, 1_000_000), 0.0)

    def test_some_bad_debt(self):
        ratio = _compute_bad_debt_ratio(10_000, 1_000_000)
        self.assertAlmostEqual(ratio, 1.0, places=4)

    def test_zero_supply(self):
        self.assertEqual(_compute_bad_debt_ratio(50_000, 0), 0.0)

    def test_negative_bad_debt_clamped(self):
        ratio = _compute_bad_debt_ratio(-100, 1_000_000)
        self.assertEqual(ratio, 0.0)

    def test_large_bad_debt(self):
        ratio = _compute_bad_debt_ratio(500_000, 1_000_000)
        self.assertAlmostEqual(ratio, 50.0, places=4)


# ===========================================================================
# 3. _compute_reserve_coverage
# ===========================================================================

class TestComputeReserveCoverage(unittest.TestCase):

    def test_no_bad_debt_no_reserve(self):
        cov = _compute_reserve_coverage(0, 0, 10.0)
        self.assertEqual(cov, 0.0)

    def test_no_bad_debt_with_reserve(self):
        cov = _compute_reserve_coverage(500_000, 0, 10.0)
        self.assertGreater(cov, 0.0)
        self.assertLessEqual(cov, 10.0)

    def test_coverage_ratio_normal(self):
        # reserve=100, bad_debt=50 → ratio=2
        cov = _compute_reserve_coverage(100, 50, 10.0)
        self.assertAlmostEqual(cov, 2.0, places=4)

    def test_coverage_ratio_below_1(self):
        cov = _compute_reserve_coverage(25, 50, 10.0)
        self.assertAlmostEqual(cov, 0.5, places=4)

    def test_coverage_zero_reserve(self):
        cov = _compute_reserve_coverage(0, 100, 10.0)
        self.assertEqual(cov, 0.0)


# ===========================================================================
# 4. _score_utilization
# ===========================================================================

class TestScoreUtilization(unittest.TestCase):

    def test_zero_utilization_low_score(self):
        s = _score_utilization(0.0)
        self.assertAlmostEqual(s, 0.0, places=4)

    def test_ideal_utilization_near_65(self):
        s = _score_utilization(65.0)
        self.assertAlmostEqual(s, 100.0, places=4)

    def test_high_utilization_penalised(self):
        s90 = _score_utilization(90.0)
        s65 = _score_utilization(65.0)
        self.assertLess(s90, s65)

    def test_100_utilization_near_zero(self):
        s = _score_utilization(100.0)
        self.assertAlmostEqual(s, 0.0, places=4)

    def test_below_zero_clamped(self):
        s = _score_utilization(-10.0)
        self.assertAlmostEqual(s, 0.0, places=4)

    def test_above_100_clamped(self):
        s = _score_utilization(110.0)
        self.assertAlmostEqual(s, 0.0, places=4)

    def test_score_in_range(self):
        for u in range(0, 101, 5):
            s = _score_utilization(float(u))
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_20_pct_gives_50(self):
        s = _score_utilization(20.0)
        self.assertAlmostEqual(s, 50.0, places=3)


# ===========================================================================
# 5. _score_bad_debt
# ===========================================================================

class TestScoreBadDebt(unittest.TestCase):

    def test_zero_ratio_gives_100(self):
        self.assertAlmostEqual(_score_bad_debt(0.0), 100.0, places=4)

    def test_5_pct_gives_0(self):
        self.assertAlmostEqual(_score_bad_debt(5.0), 0.0, places=4)

    def test_above_5_gives_0(self):
        self.assertAlmostEqual(_score_bad_debt(10.0), 0.0, places=4)

    def test_2_5_pct_gives_50(self):
        s = _score_bad_debt(2.5)
        self.assertAlmostEqual(s, 50.0, places=4)

    def test_negative_ratio_gives_100(self):
        self.assertAlmostEqual(_score_bad_debt(-1.0), 100.0, places=4)

    def test_score_decreasing(self):
        scores = [_score_bad_debt(float(r)) for r in range(6)]
        for i in range(1, len(scores)):
            self.assertLessEqual(scores[i], scores[i - 1])


# ===========================================================================
# 6. _score_reserve_coverage
# ===========================================================================

class TestScoreReserveCoverage(unittest.TestCase):

    def test_zero_coverage_gives_0(self):
        self.assertAlmostEqual(_score_reserve_coverage(0.0), 0.0, places=4)

    def test_coverage_1_gives_60(self):
        self.assertAlmostEqual(_score_reserve_coverage(1.0), 60.0, places=4)

    def test_coverage_2_gives_80(self):
        self.assertAlmostEqual(_score_reserve_coverage(2.0), 80.0, places=4)

    def test_coverage_5_or_more_gives_100(self):
        self.assertAlmostEqual(_score_reserve_coverage(5.0), 100.0, places=4)
        self.assertAlmostEqual(_score_reserve_coverage(10.0), 100.0, places=4)

    def test_score_monotone(self):
        vals = [0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0]
        scores = [_score_reserve_coverage(v) for v in vals]
        for i in range(1, len(scores)):
            self.assertGreaterEqual(scores[i], scores[i - 1])

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(_score_reserve_coverage(-1.0), 0.0, places=4)


# ===========================================================================
# 7. _score_concentration
# ===========================================================================

class TestScoreConcentration(unittest.TestCase):

    def test_low_concentration_gives_100(self):
        self.assertAlmostEqual(_score_concentration(5.0), 100.0, places=4)
        self.assertAlmostEqual(_score_concentration(10.0), 100.0, places=4)

    def test_high_concentration_gives_0(self):
        self.assertAlmostEqual(_score_concentration(50.0), 0.0, places=4)
        self.assertAlmostEqual(_score_concentration(80.0), 0.0, places=4)

    def test_midpoint(self):
        s = _score_concentration(30.0)
        self.assertAlmostEqual(s, 50.0, places=4)

    def test_score_decreases(self):
        scores = [_score_concentration(float(c)) for c in range(5, 55, 5)]
        for i in range(1, len(scores)):
            self.assertLessEqual(scores[i], scores[i - 1])


# ===========================================================================
# 8. _score_oracle
# ===========================================================================

class TestScoreOracle(unittest.TestCase):

    def test_chainlink_is_100(self):
        self.assertAlmostEqual(_score_oracle("chainlink"), 100.0, places=4)

    def test_twap_is_60(self):
        self.assertAlmostEqual(_score_oracle("twap"), 60.0, places=4)

    def test_internal_is_30(self):
        self.assertAlmostEqual(_score_oracle("internal"), 30.0, places=4)

    def test_unknown_oracle_low(self):
        s = _score_oracle("proprietary")
        self.assertLessEqual(s, 30.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(_score_oracle("ChainLink"), 100.0, places=4)
        self.assertAlmostEqual(_score_oracle("TWAP"), 60.0, places=4)

    def test_empty_string_is_unknown(self):
        s = _score_oracle("")
        self.assertLessEqual(s, 30.0)


# ===========================================================================
# 9. _score_market_pause
# ===========================================================================

class TestScoreMarketPause(unittest.TestCase):

    def test_no_paused_markets_is_100(self):
        self.assertAlmostEqual(_score_market_pause(0, 10), 100.0, places=4)

    def test_all_paused_is_0(self):
        self.assertAlmostEqual(_score_market_pause(10, 10), 0.0, places=4)

    def test_half_paused(self):
        s = _score_market_pause(5, 10)
        self.assertAlmostEqual(s, 50.0, places=4)

    def test_zero_total_markets_returns_100(self):
        self.assertAlmostEqual(_score_market_pause(0, 0), 100.0, places=4)

    def test_paused_more_than_total_clamped(self):
        # Can't pause more than total, but function should not crash
        s = _score_market_pause(15, 10)
        self.assertGreaterEqual(s, 0.0)


# ===========================================================================
# 10. _score_incentive
# ===========================================================================

class TestScoreIncentive(unittest.TestCase):

    def test_zero_incentive(self):
        self.assertAlmostEqual(_score_incentive(0.0), 0.0, places=4)

    def test_ideal_range_is_100(self):
        self.assertAlmostEqual(_score_incentive(8.0), 100.0, places=4)
        self.assertAlmostEqual(_score_incentive(12.0), 100.0, places=4)

    def test_5_pct_scores_80(self):
        self.assertAlmostEqual(_score_incentive(5.0), 80.0, places=4)

    def test_high_incentive_penalised(self):
        s_high = _score_incentive(30.0)
        s_ideal = _score_incentive(10.0)
        self.assertLess(s_high, s_ideal)

    def test_negative_clamped(self):
        self.assertAlmostEqual(_score_incentive(-5.0), 0.0, places=4)

    def test_score_in_range(self):
        for inc in range(0, 51, 5):
            s = _score_incentive(float(inc))
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


# ===========================================================================
# 11. _health_label
# ===========================================================================

class TestHealthLabel(unittest.TestCase):

    def test_pristine(self):
        self.assertEqual(_health_label(90.0), "PRISTINE")
        self.assertEqual(_health_label(85.0), "PRISTINE")

    def test_healthy(self):
        self.assertEqual(_health_label(70.0), "HEALTHY")
        self.assertEqual(_health_label(80.0), "HEALTHY")

    def test_watch(self):
        self.assertEqual(_health_label(50.0), "WATCH")
        self.assertEqual(_health_label(60.0), "WATCH")

    def test_stressed(self):
        self.assertEqual(_health_label(30.0), "STRESSED")
        self.assertEqual(_health_label(40.0), "STRESSED")

    def test_critical(self):
        self.assertEqual(_health_label(0.0), "CRITICAL")
        self.assertEqual(_health_label(29.9), "CRITICAL")

    def test_all_valid_labels(self):
        valid = {"PRISTINE", "HEALTHY", "WATCH", "STRESSED", "CRITICAL"}
        for score in range(0, 101, 5):
            lbl = _health_label(float(score))
            self.assertIn(lbl, valid)


# ===========================================================================
# 12. analyze() — integration
# ===========================================================================

class TestAnalyzeFunction(unittest.TestCase):

    def _run(self, **overrides):
        return analyze(_good_data(**overrides))

    def test_output_keys_present(self):
        result = self._run()
        for key in (
            "protocol_name", "utilization_rate_pct", "bad_debt_ratio_pct",
            "reserve_coverage_ratio", "market_health_score", "health_label",
            "dimension_scores", "mp_tag", "source", "schema_version",
        ):
            self.assertIn(key, result)

    def test_mp_tag_correct(self):
        self.assertEqual(self._run()["mp_tag"], "MP-1076")

    def test_source_correct(self):
        self.assertEqual(self._run()["source"], SOURCE_NAME)

    def test_schema_version(self):
        self.assertEqual(self._run()["schema_version"], SCHEMA_VERSION)

    def test_health_label_is_valid(self):
        result = self._run()
        self.assertIn(result["health_label"],
                      {"PRISTINE", "HEALTHY", "WATCH", "STRESSED", "CRITICAL"})

    def test_score_in_range(self):
        result = self._run()
        self.assertGreaterEqual(result["market_health_score"], 0.0)
        self.assertLessEqual(result["market_health_score"], 100.0)

    def test_healthy_protocol_gets_good_score(self):
        result = self._run()
        self.assertGreaterEqual(result["market_health_score"], 50.0)

    def test_high_bad_debt_lowers_score(self):
        good = analyze(_good_data(bad_debt_usd=0))
        bad = analyze(_good_data(bad_debt_usd=50_000))  # 5% of supply
        self.assertGreater(good["market_health_score"], bad["market_health_score"])

    def test_all_paused_lowers_score(self):
        good = analyze(_good_data(paused_markets=0, total_markets=10))
        bad = analyze(_good_data(paused_markets=10, total_markets=10))
        self.assertGreater(good["market_health_score"], bad["market_health_score"])

    def test_chainlink_better_than_internal(self):
        r_chain = analyze(_good_data(oracle_type="chainlink"))
        r_internal = analyze(_good_data(oracle_type="internal"))
        self.assertGreater(r_chain["market_health_score"],
                           r_internal["market_health_score"])

    def test_utilization_rate_pct_correct(self):
        result = self._run(
            total_supplied_usd=1_000_000,
            total_borrowed_usd=800_000,
        )
        self.assertAlmostEqual(result["utilization_rate_pct"], 80.0, places=2)

    def test_bad_debt_ratio_pct_correct(self):
        result = self._run(
            total_supplied_usd=1_000_000,
            bad_debt_usd=10_000,
        )
        self.assertAlmostEqual(result["bad_debt_ratio_pct"], 1.0, places=2)

    def test_dimension_scores_all_in_range(self):
        result = self._run()
        for key, score in result["dimension_scores"].items():
            self.assertGreaterEqual(score, 0.0, f"{key} score below 0")
            self.assertLessEqual(score, 100.0, f"{key} score above 100")

    def test_all_bad_inputs_gives_low_score(self):
        data = {
            "protocol_name":                  "BadProtocol",
            "total_supplied_usd":             1_000_000.0,
            "total_borrowed_usd":               999_000.0,  # 99.9% util
            "bad_debt_usd":                    100_000.0,   # 10% bad debt
            "reserve_factor_pct":                    0.0,
            "reserve_balance_usd":                   0.0,
            "top_borrower_concentration_pct":       70.0,
            "liquidation_incentive_pct":             0.0,
            "oracle_type":                     "internal",
            "paused_markets":                          5,
            "total_markets":                          10,
        }
        result = analyze(data)
        self.assertLess(result["market_health_score"], 40.0)
        self.assertIn(result["health_label"], {"STRESSED", "CRITICAL"})

    def test_zero_supply_no_crash(self):
        result = analyze(_good_data(total_supplied_usd=0, total_borrowed_usd=0))
        self.assertIn("market_health_score", result)

    def test_protocol_name_preserved(self):
        result = analyze(_good_data(protocol_name="Morpho"))
        self.assertEqual(result["protocol_name"], "Morpho")

    def test_missing_optional_keys_uses_defaults(self):
        minimal = {"protocol_name": "Minimal", "total_supplied_usd": 1_000_000}
        result = analyze(minimal)
        self.assertIn("market_health_score", result)

    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=10)


# ===========================================================================
# 13. DeFiProtocolLendingMarketHealthScorer class
# ===========================================================================

class TestDeFiProtocolLendingMarketHealthScorerClass(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolLendingMarketHealthScorer()

    def test_score_returns_dict(self):
        result = self.scorer.score(_good_data())
        self.assertIsInstance(result, dict)

    def test_score_has_health_label(self):
        result = self.scorer.score(_good_data())
        self.assertIn("health_label", result)

    def test_score_has_market_health_score(self):
        result = self.scorer.score(_good_data())
        self.assertIn("market_health_score", result)

    def test_write_log_false_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.scorer.score(_good_data(), write_log=False, data_dir=data_dir)
            log_path = data_dir / LOG_FILENAME
            self.assertFalse(log_path.exists())

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.scorer.score(_good_data(), write_log=True, data_dir=data_dir)
            log_path = data_dir / LOG_FILENAME
            self.assertTrue(log_path.exists())

    def test_write_log_is_valid_json_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.scorer.score(_good_data(), write_log=True, data_dir=data_dir)
            log_path = data_dir / LOG_FILENAME
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_multiple_scores_accumulate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            for i in range(5):
                self.scorer.score(
                    _good_data(protocol_name=f"Proto{i}"),
                    write_log=True, data_dir=data_dir,
                )
            log_path = data_dir / LOG_FILENAME
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            for i in range(RING_BUFFER_CAP + 5):
                self.scorer.score(
                    _good_data(protocol_name=f"Proto{i}"),
                    write_log=True, data_dir=data_dir,
                )
            log_path = data_dir / LOG_FILENAME
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_log_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.scorer.score(_good_data(), write_log=True, data_dir=data_dir)
            log_path = data_dir / LOG_FILENAME
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_score_multiple_calls_independent(self):
        r1 = self.scorer.score(_good_data(oracle_type="chainlink"))
        r2 = self.scorer.score(_good_data(oracle_type="internal"))
        self.assertGreater(r1["market_health_score"], r2["market_health_score"])


# ===========================================================================
# 14. _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def test_load_missing_file_returns_empty_list(self):
        path = Path("/tmp/nonexistent_spa_test_file_xyz.json")
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_atomic_write_then_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, [{"a": 1}, {"b": 2}])
            result = _load_json_list(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["a"], 1)

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            _atomic_write(path, [1, 2, 3])
            _atomic_write(path, [4, 5])
            result = _load_json_list(path)
            self.assertEqual(result, [4, 5])

    def test_load_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            fname = f.name
        try:
            result = _load_json_list(Path(fname))
            self.assertEqual(result, [])
        finally:
            os.unlink(fname)

    def test_load_json_non_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "obj.json"
            _atomic_write(path, {"not": "a list"})
            result = _load_json_list(path)
            self.assertEqual(result, [])


# ===========================================================================
# 15. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_all_zeros_no_crash(self):
        data = {k: 0 for k in [
            "total_supplied_usd", "total_borrowed_usd", "bad_debt_usd",
            "reserve_factor_pct", "reserve_balance_usd",
            "top_borrower_concentration_pct", "liquidation_incentive_pct",
            "paused_markets", "total_markets",
        ]}
        data["protocol_name"] = "ZeroProto"
        data["oracle_type"] = "chainlink"
        result = analyze(data)
        self.assertIn("market_health_score", result)
        self.assertGreaterEqual(result["market_health_score"], 0.0)

    def test_extreme_values_no_crash(self):
        data = _good_data(
            total_supplied_usd=1e15,
            total_borrowed_usd=1e15,
            bad_debt_usd=1e12,
            reserve_balance_usd=1e14,
            top_borrower_concentration_pct=100.0,
            liquidation_incentive_pct=100.0,
            paused_markets=1000,
            total_markets=1000,
        )
        result = analyze(data)
        self.assertGreaterEqual(result["market_health_score"], 0.0)
        self.assertLessEqual(result["market_health_score"], 100.0)

    def test_string_numbers_handled(self):
        data = _good_data(
            total_supplied_usd="1000000",
            total_borrowed_usd="650000",
        )
        result = analyze(data)
        self.assertAlmostEqual(result["utilization_rate_pct"], 65.0, places=2)

    def test_pristine_protocol_example(self):
        data = {
            "protocol_name":                  "PristineProtocol",
            "total_supplied_usd":             2_000_000_000.0,
            "total_borrowed_usd":             1_300_000_000.0,
            "bad_debt_usd":                           0.0,
            "reserve_factor_pct":                    15.0,
            "reserve_balance_usd":            50_000_000.0,
            "top_borrower_concentration_pct":         3.0,
            "liquidation_incentive_pct":             10.0,
            "oracle_type":                    "chainlink",
            "paused_markets":                          0,
            "total_markets":                          25,
        }
        result = analyze(data)
        self.assertGreaterEqual(result["market_health_score"], 85.0)
        self.assertEqual(result["health_label"], "PRISTINE")

    def test_critical_protocol_example(self):
        data = {
            "protocol_name":                  "CriticalProtocol",
            "total_supplied_usd":             1_000_000.0,
            "total_borrowed_usd":               990_000.0,
            "bad_debt_usd":                    200_000.0,
            "reserve_factor_pct":                    0.0,
            "reserve_balance_usd":                   0.0,
            "top_borrower_concentration_pct":       80.0,
            "liquidation_incentive_pct":             0.0,
            "oracle_type":                     "internal",
            "paused_markets":                          8,
            "total_markets":                          10,
        }
        result = analyze(data)
        self.assertLess(result["market_health_score"], 30.0)
        self.assertEqual(result["health_label"], "CRITICAL")

    def test_oracle_score_all_types(self):
        for oracle in ["chainlink", "twap", "internal"]:
            s = _score_oracle(oracle)
            self.assertGreater(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_label_thresholds_boundary(self):
        self.assertEqual(_health_label(LABEL_PRISTINE), "PRISTINE")
        self.assertEqual(_health_label(LABEL_HEALTHY), "HEALTHY")
        self.assertEqual(_health_label(LABEL_WATCH), "WATCH")
        self.assertEqual(_health_label(LABEL_STRESSED), "STRESSED")
        self.assertEqual(_health_label(LABEL_STRESSED - 0.1), "CRITICAL")

    def test_utilization_80_pct_transition(self):
        s80 = _score_utilization(80.0)
        s85 = _score_utilization(85.0)
        self.assertGreater(s80, s85)

    def test_reserve_coverage_between_1_and_2(self):
        s1 = _score_reserve_coverage(1.0)
        s15 = _score_reserve_coverage(1.5)
        s2 = _score_reserve_coverage(2.0)
        self.assertLess(s1, s15)
        self.assertLess(s15, s2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
