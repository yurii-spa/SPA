"""
Tests for MP-656: RateSensitivityAnalyzer
≥65 unittest tests. Pure stdlib (unittest only).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.rate_sensitivity_analyzer import (
    RateSensitivityAnalyzer,
    AdapterRateInput,
    RateShockResult,
    SensitivityReport,
    SHOCKS_BPS,
    MAX_ENTRIES,
)


def _inp(adapter_id="aave", capital=100_000.0, base_apy=0.05,
         rate_beta=0.5, is_variable=True):
    return AdapterRateInput(
        adapter_id=adapter_id,
        capital_usd=capital,
        base_apy=base_apy,
        rate_beta=rate_beta,
        is_variable_rate=is_variable,
    )


class TestShockedApy(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_shocked_apy_plus100bps(self):
        # base=0.10, beta=0.5, shock=+100 → 0.10 + (100/10000)*0.5 = 0.105
        result = self.ana._shocked_apy(0.10, 0.5, 100)
        self.assertAlmostEqual(result, 0.105, places=6)

    def test_shocked_apy_plus200bps(self):
        # base=0.10, beta=0.5, shock=+200 → 0.10 + 0.01 = 0.11
        result = self.ana._shocked_apy(0.10, 0.5, 200)
        self.assertAlmostEqual(result, 0.11, places=6)

    def test_shocked_apy_minus100bps(self):
        # base=0.10, beta=0.5, shock=-100 → 0.10 - 0.005 = 0.095
        result = self.ana._shocked_apy(0.10, 0.5, -100)
        self.assertAlmostEqual(result, 0.095, places=6)

    def test_shocked_apy_zero_shock_unchanged(self):
        result = self.ana._shocked_apy(0.10, 0.5, 0)
        self.assertAlmostEqual(result, 0.10, places=6)

    def test_shocked_apy_clamp_never_negative(self):
        # Very large negative shock
        result = self.ana._shocked_apy(0.05, 0.5, -10000)
        self.assertEqual(result, 0.0)

    def test_shocked_apy_clamp_exactly_zero(self):
        # base=0.005, beta=1.0, shock=-50 → 0.005 - 0.005 = 0.0
        result = self.ana._shocked_apy(0.005, 1.0, -50)
        self.assertEqual(result, 0.0)

    def test_shocked_apy_beta_zero_unchanged(self):
        result = self.ana._shocked_apy(0.08, 0.0, 200)
        self.assertAlmostEqual(result, 0.08, places=6)

    def test_shocked_apy_beta_one_full_pass_through(self):
        # beta=1.0 → 100bps shock → 100bps APY change
        result = self.ana._shocked_apy(0.05, 1.0, 100)
        self.assertAlmostEqual(result, 0.06, places=6)

    def test_shocked_apy_minus200bps_beta05_drops_100bps(self):
        # base=0.10, beta=0.5, shock=-200 → 0.10 + (-200/10000)*0.5 = 0.10 - 0.01 = 0.09
        result = self.ana._shocked_apy(0.10, 0.5, -200)
        self.assertAlmostEqual(result, 0.09, places=6)

    def test_shocked_apy_positive_shock_increases_apy(self):
        base = 0.06
        result = self.ana._shocked_apy(base, 0.5, 50)
        self.assertGreater(result, base)

    def test_shocked_apy_negative_shock_decreases_apy(self):
        base = 0.06
        result = self.ana._shocked_apy(base, 0.5, -50)
        self.assertLess(result, base)


class TestDV01(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_dv01_standard(self):
        # capital=100000, beta=0.5 → 100000*0.5*0.0001 = 5.0
        self.assertAlmostEqual(self.ana._dv01(100_000, 0.5), 5.0, places=4)

    def test_dv01_capital_zero(self):
        self.assertEqual(self.ana._dv01(0.0, 0.5), 0.0)

    def test_dv01_beta_zero(self):
        self.assertEqual(self.ana._dv01(100_000, 0.0), 0.0)

    def test_dv01_large_capital(self):
        # capital=200000, beta=0.25 → 200000*0.25*0.0001 = 5.0
        self.assertAlmostEqual(self.ana._dv01(200_000, 0.25), 5.0, places=4)

    def test_dv01_beta_one(self):
        # capital=50000, beta=1.0 → 50000*1.0*0.0001 = 5.0
        self.assertAlmostEqual(self.ana._dv01(50_000, 1.0), 5.0, places=4)

    def test_dv01_rounded_to_4dp(self):
        result = self.ana._dv01(100_000, 0.5)
        # Should be exactly 5.0 = 5.0000
        self.assertEqual(result, round(result, 4))

    def test_dv01_proportional_to_capital(self):
        dv01_a = self.ana._dv01(100_000, 0.5)
        dv01_b = self.ana._dv01(200_000, 0.5)
        self.assertAlmostEqual(dv01_b, 2 * dv01_a, places=6)


class TestSensitivityGrade(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_grade_capital_zero_is_low(self):
        self.assertEqual(self.ana._sensitivity_grade(0.0, 0.0), "LOW")

    def test_grade_low_below_2bps(self):
        # dv01/capital * 10000 < 2 → LOW
        # dv01=1.0, capital=100000 → 0.01 bps → LOW
        self.assertEqual(self.ana._sensitivity_grade(1.0, 100_000), "LOW")

    def test_grade_medium_between_2_and_5bps(self):
        # dv01=3.0, capital=100000 → 0.3 bps... wait
        # dv01_pct = (dv01/capital)*10000 bps
        # dv01=30, capital=100000 → 3.0 bps → MEDIUM
        self.assertEqual(self.ana._sensitivity_grade(30.0, 100_000), "MEDIUM")

    def test_grade_high_between_5_and_10bps(self):
        # dv01=70, capital=100000 → 7.0 bps → HIGH
        self.assertEqual(self.ana._sensitivity_grade(70.0, 100_000), "HIGH")

    def test_grade_very_high_at_or_above_10bps(self):
        # dv01=100, capital=100000 → 10.0 bps → VERY_HIGH
        self.assertEqual(self.ana._sensitivity_grade(100.0, 100_000), "VERY_HIGH")

    def test_grade_boundary_exactly_2bps_is_medium(self):
        # dv01=20, capital=100000 → 2.0 bps → MEDIUM
        self.assertEqual(self.ana._sensitivity_grade(20.0, 100_000), "MEDIUM")

    def test_grade_boundary_exactly_5bps_is_high(self):
        # dv01=50, capital=100000 → 5.0 bps → HIGH
        self.assertEqual(self.ana._sensitivity_grade(50.0, 100_000), "HIGH")

    def test_grade_boundary_exactly_10bps_is_very_high(self):
        # dv01=100, capital=100000 → 10.0 bps → VERY_HIGH
        self.assertEqual(self.ana._sensitivity_grade(100.0, 100_000), "VERY_HIGH")

    def test_grade_just_below_2bps_is_low(self):
        # dv01=19.9, capital=100000 → 1.99 bps → LOW
        self.assertEqual(self.ana._sensitivity_grade(19.9, 100_000), "LOW")


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_analyze_produces_6_shock_results(self):
        r = self.ana.analyze(_inp())
        self.assertEqual(len(r.shock_results), 6)

    def test_analyze_shock_results_ordered_as_shocks_bps(self):
        r = self.ana.analyze(_inp())
        shocks = [sr.shock_bps for sr in r.shock_results]
        self.assertEqual(shocks, SHOCKS_BPS)

    def test_analyze_minus200bps_beta05_drops_100bps_apy(self):
        # base=0.10, beta=0.5, shock=-200 → APY drops by (200/10000)*0.5 = 0.01 = 100bps
        r = self.ana.analyze(_inp(base_apy=0.10, rate_beta=0.5))
        sr_minus200 = next(sr for sr in r.shock_results if sr.shock_bps == -200)
        self.assertAlmostEqual(sr_minus200.apy_change_bps, -100.0, places=4)

    def test_analyze_positive_shock_positive_pnl(self):
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        positive_shocks = [sr for sr in r.shock_results if sr.shock_bps > 0]
        for sr in positive_shocks:
            self.assertGreater(sr.pnl_impact_usd, 0, f"shock_bps={sr.shock_bps}")

    def test_analyze_negative_shock_negative_pnl(self):
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        negative_shocks = [sr for sr in r.shock_results if sr.shock_bps < 0]
        for sr in negative_shocks:
            self.assertLess(sr.pnl_impact_usd, 0, f"shock_bps={sr.shock_bps}")

    def test_analyze_direction_positive(self):
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        sr = next(sr for sr in r.shock_results if sr.shock_bps == 200)
        self.assertEqual(sr.direction, "POSITIVE")

    def test_analyze_direction_negative(self):
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        sr = next(sr for sr in r.shock_results if sr.shock_bps == -200)
        self.assertEqual(sr.direction, "NEGATIVE")

    def test_analyze_worst_case_is_min_pnl(self):
        r = self.ana.analyze(_inp())
        pnl_impacts = [sr.pnl_impact_usd for sr in r.shock_results]
        self.assertAlmostEqual(r.worst_case_pnl_usd, round(min(pnl_impacts), 4), places=4)

    def test_analyze_best_case_is_max_pnl(self):
        r = self.ana.analyze(_inp())
        pnl_impacts = [sr.pnl_impact_usd for sr in r.shock_results]
        self.assertAlmostEqual(r.best_case_pnl_usd, round(max(pnl_impacts), 4), places=4)

    def test_analyze_apy_change_bps_correct_sign(self):
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        for sr in r.shock_results:
            if sr.shock_bps > 0:
                self.assertGreater(sr.apy_change_bps, 0)
            elif sr.shock_bps < 0:
                self.assertLess(sr.apy_change_bps, 0)

    def test_analyze_apy_change_bps_magnitude(self):
        # beta=0.5: 100bps shock → 50bps APY change
        r = self.ana.analyze(_inp(base_apy=0.05, rate_beta=0.5))
        sr = next(sr for sr in r.shock_results if sr.shock_bps == 100)
        self.assertAlmostEqual(sr.apy_change_bps, 50.0, places=4)

    def test_analyze_capital_rounded_to_2dp(self):
        r = self.ana.analyze(_inp(capital=100_000.999))
        self.assertEqual(r.capital_usd, round(100_000.999, 2))

    def test_analyze_base_apy_rounded_to_6dp(self):
        r = self.ana.analyze(_inp(base_apy=0.123456789))
        self.assertEqual(r.base_apy, round(0.123456789, 6))

    def test_analyze_rate_beta_rounded_to_4dp(self):
        r = self.ana.analyze(_inp(rate_beta=0.12345678))
        self.assertEqual(r.rate_beta, round(0.12345678, 4))

    def test_analyze_dv01_correct(self):
        r = self.ana.analyze(_inp(capital=100_000, rate_beta=0.5))
        self.assertAlmostEqual(r.dv01_usd, 5.0, places=4)

    def test_analyze_adapter_id_preserved(self):
        r = self.ana.analyze(_inp(adapter_id="compound_v3"))
        self.assertEqual(r.adapter_id, "compound_v3")

    def test_analyze_is_variable_rate_preserved(self):
        r = self.ana.analyze(_inp(is_variable=False))
        self.assertFalse(r.is_variable_rate)

    def test_analyze_worst_best_case_ordering(self):
        r = self.ana.analyze(_inp())
        self.assertLessEqual(r.worst_case_pnl_usd, r.best_case_pnl_usd)

    def test_analyze_sensitivity_grade_is_string(self):
        r = self.ana.analyze(_inp())
        self.assertIn(r.sensitivity_grade, ("LOW", "MEDIUM", "HIGH", "VERY_HIGH"))

    def test_analyze_pnl_proportional_to_capital(self):
        r1 = self.ana.analyze(_inp(capital=100_000))
        r2 = self.ana.analyze(_inp(capital=200_000))
        self.assertAlmostEqual(r2.worst_case_pnl_usd,
                               r1.worst_case_pnl_usd * 2, places=2)

    def test_analyze_shocked_apy_non_negative(self):
        r = self.ana.analyze(_inp(base_apy=0.001, rate_beta=1.0))
        for sr in r.shock_results:
            self.assertGreaterEqual(sr.shocked_apy, 0.0)


class TestAnalyzeBatch(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_batch_empty_returns_empty(self):
        self.assertEqual(self.ana.analyze_batch([]), [])

    def test_batch_single(self):
        results = self.ana.analyze_batch([_inp()])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], SensitivityReport)

    def test_batch_multiple(self):
        inputs = [
            _inp(adapter_id="aave", capital=30_000),
            _inp(adapter_id="compound", capital=40_000),
            _inp(adapter_id="morpho", capital=30_000),
        ]
        results = self.ana.analyze_batch(inputs)
        self.assertEqual(len(results), 3)

    def test_batch_order_preserved(self):
        inputs = [
            _inp(adapter_id="first"),
            _inp(adapter_id="second"),
        ]
        results = self.ana.analyze_batch(inputs)
        self.assertEqual(results[0].adapter_id, "first")
        self.assertEqual(results[1].adapter_id, "second")


class TestPortfolioDV01(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_portfolio_dv01_empty_returns_zero(self):
        self.assertEqual(self.ana.portfolio_dv01([]), 0.0)

    def test_portfolio_dv01_single_report(self):
        r = self.ana.analyze(_inp(capital=100_000, rate_beta=0.5))
        total = self.ana.portfolio_dv01([r])
        self.assertAlmostEqual(total, 5.0, places=4)

    def test_portfolio_dv01_sums_correctly(self):
        r1 = self.ana.analyze(_inp(adapter_id="a1", capital=100_000, rate_beta=0.5))
        r2 = self.ana.analyze(_inp(adapter_id="a2", capital=200_000, rate_beta=0.25))
        # dv01_1 = 5.0, dv01_2 = 5.0 → total = 10.0
        total = self.ana.portfolio_dv01([r1, r2])
        self.assertAlmostEqual(total, r1.dv01_usd + r2.dv01_usd, places=4)

    def test_portfolio_dv01_rounded_to_4dp(self):
        reports = self.ana.analyze_batch([_inp(), _inp(adapter_id="b")])
        total = self.ana.portfolio_dv01(reports)
        self.assertEqual(total, round(total, 4))


class TestCustomShocks(unittest.TestCase):
    def test_custom_shocks_bps_used(self):
        custom = [-50, +50]
        ana = RateSensitivityAnalyzer(shocks_bps=custom)
        r = ana.analyze(_inp())
        self.assertEqual(len(r.shock_results), 2)

    def test_custom_shocks_bps_order_preserved(self):
        custom = [+100, -100, +200]
        ana = RateSensitivityAnalyzer(shocks_bps=custom)
        r = ana.analyze(_inp())
        shocks = [sr.shock_bps for sr in r.shock_results]
        self.assertEqual(shocks, custom)

    def test_default_shocks_bps_constant(self):
        self.assertEqual(SHOCKS_BPS, [-200, -100, -50, +50, +100, +200])

    def test_default_analyzer_uses_6_shocks(self):
        ana = RateSensitivityAnalyzer()
        r = ana.analyze(_inp())
        self.assertEqual(len(r.shock_results), 6)


class TestSaveLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "test_rate_sensitivity_log.json"
        self.ana = RateSensitivityAnalyzer(data_file=self.data_file)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.ana.load_history(), [])

    def test_save_creates_file(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        self.assertTrue(self.data_file.exists())

    def test_save_file_is_valid_json(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_contains_timestamp(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertIn("timestamp", data[0])

    def test_save_contains_adapter_id(self):
        r = self.ana.analyze(_inp(adapter_id="euler_v2"))
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertEqual(data[0]["adapter_id"], "euler_v2")

    def test_save_contains_dv01_usd(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertIn("dv01_usd", data[0])

    def test_save_contains_sensitivity_grade(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertIn("sensitivity_grade", data[0])

    def test_save_contains_worst_case_pnl(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        data = json.loads(self.data_file.read_text())
        self.assertIn("worst_case_pnl_usd", data[0])

    def test_save_ring_buffer_capped_at_100(self):
        inputs = [_inp(adapter_id=f"a{i}") for i in range(110)]
        reports = self.ana.analyze_batch(inputs)
        self.ana.save_reports(reports)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_save_atomic_no_tmp_leftover(self):
        r = self.ana.analyze(_inp())
        self.ana.save_reports([r])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_history_returns_saved_data(self):
        r = self.ana.analyze(_inp(adapter_id="aave"))
        self.ana.save_reports([r])
        history = self.ana.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["adapter_id"], "aave")

    def test_load_history_corrupt_file_returns_empty(self):
        self.data_file.write_text("{ corrupt json }")
        self.assertEqual(self.ana.load_history(), [])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.ana = RateSensitivityAnalyzer()

    def test_max_entries_constant(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_report_is_sensitivity_report(self):
        r = self.ana.analyze(_inp())
        self.assertIsInstance(r, SensitivityReport)

    def test_direction_neutral_when_zero_pnl(self):
        # beta=0 → no APY change → PnL=0 → NEUTRAL
        r = self.ana.analyze(_inp(rate_beta=0.0))
        for sr in r.shock_results:
            self.assertEqual(sr.direction, "NEUTRAL")

    def test_shock_result_type(self):
        r = self.ana.analyze(_inp())
        for sr in r.shock_results:
            self.assertIsInstance(sr, RateShockResult)


if __name__ == "__main__":
    unittest.main()
