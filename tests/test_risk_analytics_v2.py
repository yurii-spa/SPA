"""
tests/test_risk_analytics_v2.py

50 tests for the advanced risk-analytics v2 modules:
  * spa_core/risk/var_calculator.py      (Historical / Parametric / CVaR / Monte-Carlo VaR)
  * spa_core/risk/stress_tester.py       (5 stress scenarios)
  * spa_core/risk/correlation_tracker.py (protocol / benchmark / market correlations)

Math is hand-verified where practical; stress scenarios are checked against
closed-form expectations; all correlations are asserted to lie in [-1, 1].

Run:
    python3 -m pytest tests/test_risk_analytics_v2.py -v
"""
import os
import sys
import math
import json
import tempfile
import statistics
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.risk.var_calculator import (
    VaRCalculator, percentile, _inv_norm_cdf, load_daily_returns,
    load_capital, Z_SCORE, DEFAULT_CAPITAL,
)
from spa_core.risk.stress_tester import (
    StressTester, SCENARIO_NAMES, USDC_DEPEG_PRICE, YIELD_COLLAPSE_APY,
    LIQUIDITY_SLIPPAGE_PCT, LIQUIDITY_FREEZE_DAYS,
)
from spa_core.risk.correlation_tracker import (
    CorrelationTracker, pearson, BENCHMARK_APY, TRADING_DAYS_YEAR,
)

DATA_DIR = os.path.join(_REPO, "data")

# A symmetric 10-point return series with known quantiles.
KNOWN_RETURNS = [-0.05, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05]


# ===========================================================================
# VaR — math helpers & calculator  (tests 1–25)
# ===========================================================================
class TestVaRMath(unittest.TestCase):

    def test_01_percentile_midpoint(self):
        self.assertAlmostEqual(percentile([0, 10], 0.5), 5.0)

    def test_02_percentile_interpolation(self):
        self.assertAlmostEqual(percentile([0, 10, 20, 30], 0.5), 15.0)

    def test_03_percentile_single_value(self):
        self.assertEqual(percentile([7.5], 0.9), 7.5)

    def test_04_percentile_clamps_p(self):
        vals = [1, 2, 3, 4]
        self.assertEqual(percentile(vals, -1.0), 1)
        self.assertEqual(percentile(vals, 2.0), 4)

    def test_05_percentile_empty_raises(self):
        with self.assertRaises(ValueError):
            percentile([], 0.5)

    def test_06_historical_var95_known(self):
        # percentile@0.05 of KNOWN_RETURNS = -0.041 → VaR = 0.041
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertAlmostEqual(calc.historical_var(0.95), 0.041, places=6)

    def test_07_historical_var99_known(self):
        # percentile@0.01 = -0.0482 → VaR = 0.0482
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertAlmostEqual(calc.historical_var(0.99), 0.0482, places=6)

    def test_08_historical_var_floored_nonneg(self):
        calc = VaRCalculator([0.01, 0.02, 0.03, 0.04, 0.05])  # all gains
        self.assertEqual(calc.historical_var(0.95), 0.0)

    def test_09_historical_var_raw_can_be_negative(self):
        calc = VaRCalculator([0.01, 0.02, 0.03, 0.04, 0.05])
        self.assertLess(calc.historical_var_raw(0.95), 0.0)

    def test_10_parametric_matches_formula(self):
        calc = VaRCalculator(KNOWN_RETURNS)
        mu = statistics.fmean(KNOWN_RETURNS)
        sigma = statistics.pstdev(KNOWN_RETURNS)
        expected = max(0.0, Z_SCORE[0.95] * sigma - mu)
        self.assertAlmostEqual(calc.parametric_var(0.95), expected, places=9)

    def test_11_parametric_var99_ge_var95(self):
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertGreaterEqual(calc.parametric_var(0.99), calc.parametric_var(0.95))

    def test_12_expected_shortfall_ge_var(self):
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertGreaterEqual(calc.expected_shortfall(0.95), calc.historical_var(0.95))

    def test_13_expected_shortfall_known(self):
        # tail at 5% = worst day only = -0.05 → CVaR = 0.05
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertAlmostEqual(calc.expected_shortfall(0.95), 0.05, places=6)

    def test_14_monte_carlo_positive(self):
        calc = VaRCalculator(KNOWN_RETURNS)
        self.assertGreater(calc.monte_carlo_var(0.95), 0.0)

    def test_15_monte_carlo_deterministic(self):
        a = VaRCalculator(KNOWN_RETURNS).monte_carlo_var(0.95)
        b = VaRCalculator(KNOWN_RETURNS).monte_carlo_var(0.95)
        self.assertEqual(a, b)

    def test_16_monte_carlo_sims_count(self):
        # fewer sims still runs and yields a finite non-negative number
        calc = VaRCalculator(KNOWN_RETURNS)
        v = calc.monte_carlo_var(0.95, horizon_days=30, sims=100)
        self.assertGreaterEqual(v, 0.0)
        self.assertTrue(math.isfinite(v))

    def test_17_analyze_required_keys(self):
        result = VaRCalculator(KNOWN_RETURNS).analyze()
        for key in ("VaR95", "VaR99", "CVaR95", "monte_carlo_var30d"):
            self.assertIn(key, result)

    def test_18_analyze_values_are_percent(self):
        # headline VaR95 == historical fraction * 100
        calc = VaRCalculator(KNOWN_RETURNS)
        result = calc.analyze()
        self.assertAlmostEqual(result["VaR95"], calc.historical_var(0.95) * 100, places=4)

    def test_19_usd_scales_with_capital(self):
        r = VaRCalculator(KNOWN_RETURNS, capital=200_000).analyze()
        frac = VaRCalculator(KNOWN_RETURNS).historical_var(0.99)
        self.assertAlmostEqual(r["historical"]["var99_usd"], round(frac * 200_000, 2), places=2)

    def test_20_empty_returns_zero(self):
        r = VaRCalculator([]).analyze()
        self.assertEqual(r["VaR95"], 0.0)
        self.assertEqual(r["monte_carlo_var30d"], 0.0)
        self.assertEqual(r["n_returns"], 0)

    def test_21_single_return_zero(self):
        calc = VaRCalculator([0.01])
        self.assertEqual(calc.historical_var(0.95), 0.0)
        self.assertEqual(calc.parametric_var(0.95), 0.0)

    def test_22_inv_norm_cdf_known(self):
        self.assertAlmostEqual(_inv_norm_cdf(0.95), Z_SCORE[0.95], places=3)
        self.assertAlmostEqual(_inv_norm_cdf(0.99), Z_SCORE[0.99], places=3)

    def test_23_cvar_ge_var_random_series(self):
        series = [(-1) ** i * (i % 7) * 0.003 for i in range(40)]
        calc = VaRCalculator(series)
        self.assertGreaterEqual(calc.expected_shortfall(0.95), calc.historical_var(0.95))

    def test_24_default_capital(self):
        self.assertEqual(VaRCalculator(KNOWN_RETURNS).capital, DEFAULT_CAPITAL)

    def test_25_monte_carlo_horizon_grows_with_days(self):
        calc = VaRCalculator(KNOWN_RETURNS)
        short = calc.monte_carlo_var(0.95, horizon_days=1, sims=500)
        long = calc.monte_carlo_var(0.95, horizon_days=30, sims=500)
        self.assertGreater(long, short)


class TestVaRRealData(unittest.TestCase):

    def test_26_load_daily_returns_real(self):
        rets = load_daily_returns(DATA_DIR)
        self.assertGreaterEqual(len(rets), 10)
        self.assertTrue(all(isinstance(x, float) for x in rets))

    def test_27_load_capital_real(self):
        cap = load_capital(DATA_DIR)
        self.assertGreater(cap, 0)

    def test_28_from_equity_curve_analyze(self):
        result = VaRCalculator.from_equity_curve(DATA_DIR).analyze()
        self.assertFalse(result["is_demo"])
        for key in ("VaR95", "VaR99", "CVaR95", "monte_carlo_var30d"):
            self.assertGreaterEqual(result[key], 0.0)

    def test_29_missing_dir_returns_empty(self):
        self.assertEqual(load_daily_returns("/no/such/dir/xyz"), [])
        self.assertEqual(load_capital("/no/such/dir/xyz"), DEFAULT_CAPITAL)

    def test_30_run_writes_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            # seed a minimal equity curve
            curve = {"daily": [{"close_equity": 100000 + i * 10,
                                "apy_today": 4.0} for i in range(15)]}
            with open(os.path.join(d, "equity_curve_daily.json"), "w") as fh:
                json.dump(curve, fh)
            from spa_core.risk.var_calculator import main
            rc = main(["--run", "--data-dir", d])
            self.assertEqual(rc, 0)
            out = os.path.join(d, "var_analytics_v2.json")
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                saved = json.load(fh)
            self.assertIn("VaR95", saved)


# ===========================================================================
# Stress tester  (tests 31–42)
# ===========================================================================
class TestStressTester(unittest.TestCase):

    def setUp(self):
        self.positions = {
            "aave_v3": 10000.0, "compound_v3": 5000.0,
            "morpho_blue": 8000.0, "yearn_v3": 2000.0, "pendle": 1000.0,
        }
        self.tester = StressTester(self.positions, capital=100_000.0, blended_apy=0.05)

    def test_31_usdc_depeg_math(self):
        sc = self.tester.scenario_usdc_depeg()
        expected = (10000 + 5000) * (1 - USDC_DEPEG_PRICE)
        self.assertAlmostEqual(sc["impact_usd"], round(expected, 2), places=2)

    def test_32_usdc_depeg_affected_protocols(self):
        sc = self.tester.scenario_usdc_depeg()
        affected = sc["assumptions"]["affected_protocols"]
        self.assertIn("aave_v3", affected)
        self.assertIn("compound_v3", affected)
        self.assertNotIn("pendle", affected)

    def test_33_contagion_zeroes_largest_t2(self):
        sc = self.tester.scenario_defi_contagion()
        self.assertEqual(sc["assumptions"]["wiped_protocol"], "morpho_blue")
        self.assertAlmostEqual(sc["impact_usd"], 8000.0, places=2)

    def test_34_yield_collapse_math(self):
        sc = self.tester.scenario_yield_collapse()
        deployed = sum(self.positions.values())
        expected = deployed * (0.05 - YIELD_COLLAPSE_APY) * (30 / 365.0)
        self.assertAlmostEqual(sc["impact_usd"], round(expected, 2), places=2)

    def test_35_yield_collapse_nonneg(self):
        cheap = StressTester(self.positions, capital=100_000, blended_apy=0.002)
        self.assertGreaterEqual(cheap.scenario_yield_collapse()["impact_usd"], 0.0)

    def test_36_smart_contract_hack_largest(self):
        sc = self.tester.scenario_smart_contract_hack()
        self.assertEqual(sc["assumptions"]["hacked_protocol"], "aave_v3")
        self.assertAlmostEqual(sc["impact_usd"], 10000.0, places=2)

    def test_37_liquidity_crisis_components(self):
        sc = self.tester.scenario_liquidity_crisis()
        deployed = sum(self.positions.values())
        slip = deployed * LIQUIDITY_SLIPPAGE_PCT
        opp = deployed * 0.05 * (LIQUIDITY_FREEZE_DAYS / 365.0)
        self.assertAlmostEqual(sc["impact_usd"], round(slip + opp, 2), places=2)

    def test_38_analyze_five_scenarios(self):
        result = self.tester.analyze()
        self.assertEqual(len(result["scenarios"]), 5)
        names = [s["scenario"] for s in result["scenarios"]]
        self.assertEqual(names, SCENARIO_NAMES)

    def test_39_each_scenario_has_impact_keys(self):
        for sc in self.tester.analyze()["scenarios"]:
            self.assertIn("impact_usd", sc)
            self.assertIn("impact_pct", sc)
            self.assertIn("description", sc)

    def test_40_impact_pct_consistent(self):
        for sc in self.tester.analyze()["scenarios"]:
            expected_pct = round(sc["impact_usd"] / 100_000 * 100, 4)
            self.assertAlmostEqual(sc["impact_pct"], expected_pct, places=3)

    def test_41_worst_case_identified(self):
        result = self.tester.analyze()
        worst = max(result["scenarios"], key=lambda s: s["impact_usd"])
        self.assertEqual(result["worst_case_scenario"], worst["scenario"])
        self.assertGreaterEqual(result["worst_case_impact_usd"], 0.0)

    def test_42_empty_positions_zero_impact(self):
        result = StressTester({}, capital=100_000).analyze()
        for sc in result["scenarios"]:
            self.assertEqual(sc["impact_usd"], 0.0)
            self.assertGreaterEqual(sc["impact_pct"], 0.0)


class TestStressRealData(unittest.TestCase):

    def test_43_from_data_real(self):
        result = StressTester.from_data(DATA_DIR).analyze()
        self.assertEqual(len(result["scenarios"]), 5)
        self.assertFalse(result["is_demo"])
        for sc in result["scenarios"]:
            self.assertGreaterEqual(sc["impact_usd"], 0.0)


# ===========================================================================
# Correlation tracker  (tests 44–50)
# ===========================================================================
class TestCorrelationTracker(unittest.TestCase):

    def test_44_pearson_perfect_positive(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0, places=9)

    def test_45_pearson_perfect_negative(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0, places=9)

    def test_46_pearson_zero_variance_none(self):
        self.assertIsNone(pearson([5, 5, 5, 5], [1, 2, 3, 4]))

    def test_47_pearson_insufficient_none(self):
        self.assertIsNone(pearson([1], [2]))

    def test_48_all_correlations_in_range(self):
        series = {
            "a": [100, 101, 102, 103, 104],
            "b": [200, 198, 199, 201, 203],
            "c": [50, 55, 53, 52, 58],
        }
        tracker = CorrelationTracker(series, [0.01, -0.02, 0.03, 0.0], [4.0, 4.1, 4.2, 4.0, 4.3])
        matrix = tracker.protocol_matrix()["matrix"]
        for row in matrix.values():
            for r in row.values():
                if r is not None:
                    self.assertGreaterEqual(r, -1.0)
                    self.assertLessEqual(r, 1.0)

    def test_49_matrix_diagonal_one_and_symmetric(self):
        series = {"a": [1, 2, 3, 4, 5], "b": [2, 1, 4, 3, 6]}
        m = CorrelationTracker(series, [], []).protocol_matrix()["matrix"]
        self.assertEqual(m["a"]["a"], 1.0)
        self.assertEqual(m["b"]["b"], 1.0)
        self.assertEqual(m["a"]["b"], m["b"]["a"])

    def test_50_analyze_real_data_structure(self):
        result = CorrelationTracker.from_data(DATA_DIR).analyze()
        self.assertFalse(result["is_demo"])
        self.assertIn("protocol_correlations", result)
        svb = result["strategy_vs_benchmark"]
        self.assertEqual(svb["benchmark"], "ETH staking ~3.5% APY")
        # benchmark daily return is the flat 3.5% APY / 365
        self.assertAlmostEqual(svb["benchmark_daily_return"],
                               BENCHMARK_APY / TRADING_DAYS_YEAR, places=8)
        # every reported protocol correlation in range
        for row in result["protocol_correlations"]["matrix"].values():
            for r in row.values():
                if r is not None:
                    self.assertTrue(-1.0 <= r <= 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
