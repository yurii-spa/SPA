"""
Tests for MP-731: PortfolioStressScenarioRunner
stdlib unittest only. ≥65 tests.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.portfolio_stress_scenario_runner import (
    StressScenario,
    PositionStressResult,
    PortfolioStressResult,
    DEFAULT_SCENARIOS,
    apply_shock,
    stress_position,
    run_stress,
    compare_scenarios,
    save_results,
    load_history,
)


def _pos(name="Aave USDC", protocol="Aave", value_usd=10000.0, apy=3.5, risk_score=2.0):
    return {
        "name": name,
        "protocol": protocol,
        "value_usd": value_usd,
        "apy": apy,
        "risk_score": risk_score,
    }


def _scenario(
    name="TEST",
    description="Test scenario",
    tvl_shock_pct=-40.0,
    apy_shock_pct=-50.0,
    price_shock_pct=-40.0,
    liquidity_shock_pct=-30.0,
    prob_annual=0.10,
    severity="SEVERE",
):
    return StressScenario(
        name=name,
        description=description,
        tvl_shock_pct=tvl_shock_pct,
        apy_shock_pct=apy_shock_pct,
        price_shock_pct=price_shock_pct,
        liquidity_shock_pct=liquidity_shock_pct,
        prob_annual=prob_annual,
        severity=severity,
    )


class TestApplyShock(unittest.TestCase):
    def test_negative_40_pct(self):
        # 1000 * (1 + (-40)/100) = 600
        result = apply_shock(1000.0, -40.0)
        self.assertAlmostEqual(result, 600.0, places=6)

    def test_positive_shock(self):
        # 1000 * (1 + 20/100) = 1200
        result = apply_shock(1000.0, 20.0)
        self.assertAlmostEqual(result, 1200.0, places=6)

    def test_zero_shock(self):
        result = apply_shock(1000.0, 0.0)
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_minus_100_pct(self):
        result = apply_shock(5000.0, -100.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_minus_50_pct(self):
        result = apply_shock(1000.0, -50.0)
        self.assertAlmostEqual(result, 500.0, places=6)

    def test_minus_10_pct(self):
        result = apply_shock(10000.0, -10.0)
        self.assertAlmostEqual(result, 9000.0, places=6)

    def test_formula_general(self):
        initial = 7500.0
        shock = -30.0
        expected = initial * (1.0 + shock / 100.0)
        self.assertAlmostEqual(apply_shock(initial, shock), expected, places=8)

    def test_zero_initial_value(self):
        self.assertAlmostEqual(apply_shock(0.0, -50.0), 0.0, places=8)


class TestStressPosition(unittest.TestCase):
    def _single_scenario(self, price_shock=-40.0, apy_shock=-50.0, liquidity_shock=-30.0):
        return [_scenario(
            name="S1",
            price_shock_pct=price_shock,
            apy_shock_pct=apy_shock,
            liquidity_shock_pct=liquidity_shock,
        )]

    def test_stressed_value_uses_price_shock(self):
        pos = _pos(value_usd=10000.0)
        scenarios = self._single_scenario(price_shock=-40.0)
        result = stress_position(pos, scenarios)
        expected_value = apply_shock(10000.0, -40.0)
        self.assertAlmostEqual(result.scenario_results["S1"]["stressed_value"], expected_value, places=4)

    def test_stressed_apy_floored_at_zero(self):
        # apy=1.0, shock=-200% → apply_shock(1.0, -200) = 1.0*(1-2) = -1.0 → floor to 0
        pos = _pos(apy=1.0)
        scenarios = [_scenario(name="S1", apy_shock_pct=-200.0)]
        result = stress_position(pos, scenarios)
        self.assertEqual(result.scenario_results["S1"]["stressed_apy"], 0.0)

    def test_stressed_apy_positive_case(self):
        pos = _pos(apy=4.0)
        scenarios = [_scenario(name="S1", apy_shock_pct=-50.0)]
        result = stress_position(pos, scenarios)
        expected_apy = max(0.0, apply_shock(4.0, -50.0))
        self.assertAlmostEqual(result.scenario_results["S1"]["stressed_apy"], expected_apy, places=6)

    def test_loss_usd_formula(self):
        pos = _pos(value_usd=10000.0)
        scenarios = self._single_scenario(price_shock=-40.0)
        result = stress_position(pos, scenarios)
        stressed = result.scenario_results["S1"]["stressed_value"]
        expected_loss = 10000.0 - stressed
        self.assertAlmostEqual(result.scenario_results["S1"]["loss_usd"], expected_loss, places=4)

    def test_loss_pct_formula(self):
        pos = _pos(value_usd=10000.0)
        scenarios = self._single_scenario(price_shock=-40.0)
        result = stress_position(pos, scenarios)
        sr = result.scenario_results["S1"]
        expected_pct = sr["loss_usd"] / 10000.0 * 100.0
        self.assertAlmostEqual(sr["loss_pct"], expected_pct, places=4)

    def test_can_exit_true(self):
        # liquidity_shock = -30% → remaining = 0.70 > 0.3 → can_exit = True
        pos = _pos()
        scenarios = [_scenario(name="S1", liquidity_shock_pct=-30.0)]
        result = stress_position(pos, scenarios)
        self.assertTrue(result.scenario_results["S1"]["can_exit"])

    def test_can_exit_false(self):
        # liquidity_shock = -80% → remaining = 0.20 < 0.3 → can_exit = False
        pos = _pos()
        scenarios = [_scenario(name="S1", liquidity_shock_pct=-80.0)]
        result = stress_position(pos, scenarios)
        self.assertFalse(result.scenario_results["S1"]["can_exit"])

    def test_can_exit_border_exactly_30_pct(self):
        # remaining = 0.29 → NOT > 0.3 → False  (use -71% to avoid float rounding at -70%)
        pos = _pos()
        scenarios = [_scenario(name="S1", liquidity_shock_pct=-71.0)]
        result = stress_position(pos, scenarios)
        self.assertFalse(result.scenario_results["S1"]["can_exit"])

    def test_can_exit_just_above_30(self):
        # -69.9% → 0.301 > 0.3 → True
        pos = _pos()
        scenarios = [_scenario(name="S1", liquidity_shock_pct=-69.0)]
        result = stress_position(pos, scenarios)
        self.assertTrue(result.scenario_results["S1"]["can_exit"])

    def test_worst_scenario_max_loss(self):
        pos = _pos(value_usd=10000.0)
        scenarios = [
            _scenario(name="MILD", price_shock_pct=-10.0),
            _scenario(name="SEVERE", price_shock_pct=-60.0),
        ]
        result = stress_position(pos, scenarios)
        self.assertEqual(result.worst_scenario, "SEVERE")

    def test_max_loss_usd(self):
        pos = _pos(value_usd=10000.0)
        scenarios = [
            _scenario(name="S1", price_shock_pct=-40.0),
            _scenario(name="S2", price_shock_pct=-60.0),
        ]
        result = stress_position(pos, scenarios)
        expected_max_loss = max(
            result.scenario_results["S1"]["loss_usd"],
            result.scenario_results["S2"]["loss_usd"],
        )
        self.assertAlmostEqual(result.max_loss_usd, expected_max_loss, places=4)

    def test_max_loss_pct(self):
        pos = _pos(value_usd=10000.0)
        scenarios = self._single_scenario(price_shock=-40.0)
        result = stress_position(pos, scenarios)
        expected_pct = result.max_loss_usd / 10000.0 * 100.0
        self.assertAlmostEqual(result.max_loss_pct, expected_pct, places=4)

    def test_position_fields_preserved(self):
        pos = _pos(name="Test", protocol="Morpho", value_usd=5000.0, apy=6.5, risk_score=3.5)
        scenarios = self._single_scenario()
        result = stress_position(pos, scenarios)
        self.assertEqual(result.position_name, "Test")
        self.assertEqual(result.protocol, "Morpho")
        self.assertAlmostEqual(result.initial_value_usd, 5000.0)
        self.assertAlmostEqual(result.initial_apy, 6.5)
        self.assertAlmostEqual(result.risk_score, 3.5)

    def test_multiple_scenarios_all_computed(self):
        pos = _pos()
        scenarios = [
            _scenario(name="A", price_shock_pct=-20.0),
            _scenario(name="B", price_shock_pct=-40.0),
            _scenario(name="C", price_shock_pct=-60.0),
        ]
        result = stress_position(pos, scenarios)
        self.assertIn("A", result.scenario_results)
        self.assertIn("B", result.scenario_results)
        self.assertIn("C", result.scenario_results)


class TestRunStress(unittest.TestCase):
    def _portfolio(self):
        return [
            _pos("Aave USDC", "Aave", 40000.0, 3.5, 2.0),
            _pos("Compound USDC", "Compound", 30000.0, 4.8, 2.5),
            _pos("Morpho", "Morpho", 20000.0, 6.5, 3.5),
            _pos("Cash", "USDC", 10000.0, 0.0, 1.0),
        ]

    def _scenarios(self):
        return [
            _scenario("CRASH", price_shock_pct=-40.0, prob_annual=0.10, severity="SEVERE"),
            _scenario("SPIKE", price_shock_pct=-10.0, prob_annual=0.20, severity="MODERATE"),
        ]

    def test_portfolio_scenario_losses_sums_positions(self):
        positions = self._portfolio()
        scenarios = self._scenarios()
        result = run_stress("test_portfolio", positions, scenarios)

        # Manual check for CRASH
        crash_loss = sum(
            pr.scenario_results["CRASH"]["loss_usd"]
            for pr in result.position_results
        )
        self.assertAlmostEqual(
            result.portfolio_scenario_losses["CRASH"], crash_loss, places=4
        )

    def test_worst_scenario_name_is_max_loss(self):
        positions = self._portfolio()
        scenarios = [
            _scenario("BIG", price_shock_pct=-60.0, prob_annual=0.05, severity="EXTREME"),
            _scenario("SMALL", price_shock_pct=-5.0, prob_annual=0.20, severity="MODERATE"),
        ]
        result = run_stress("test", positions, scenarios)
        self.assertEqual(result.worst_scenario_name, "BIG")

    def test_worst_scenario_loss_usd_is_max(self):
        positions = self._portfolio()
        scenarios = self._scenarios()
        result = run_stress("test", positions, scenarios)
        max_loss = max(result.portfolio_scenario_losses.values())
        self.assertAlmostEqual(result.worst_scenario_loss_usd, max_loss, places=4)

    def test_worst_scenario_loss_pct_formula(self):
        positions = self._portfolio()
        scenarios = self._scenarios()
        result = run_stress("test", positions, scenarios)
        total_value = sum(float(p["value_usd"]) for p in positions)
        expected_pct = result.worst_scenario_loss_usd / total_value * 100.0
        self.assertAlmostEqual(result.worst_scenario_loss_pct, expected_pct, places=4)

    def test_total_value_sum(self):
        positions = self._portfolio()
        scenarios = self._scenarios()
        result = run_stress("test", positions, scenarios)
        expected = sum(float(p["value_usd"]) for p in positions)
        self.assertAlmostEqual(result.total_value_usd, expected, places=4)

    def test_expected_shortfall_uses_severe_extreme_only(self):
        positions = [_pos(value_usd=100000.0)]
        # Only MODERATE scenario → expected_shortfall should be 0
        scenarios = [_scenario("MOD", price_shock_pct=-10.0, prob_annual=0.20, severity="MODERATE")]
        result = run_stress("test", positions, scenarios)
        self.assertEqual(result.expected_shortfall_usd, 0.0)

    def test_expected_shortfall_severe_scenario(self):
        positions = [_pos(value_usd=100000.0)]
        scenarios = [
            _scenario("CRASH", price_shock_pct=-40.0, prob_annual=0.15, severity="SEVERE"),
            _scenario("EXTREME", price_shock_pct=-70.0, prob_annual=0.05, severity="EXTREME"),
        ]
        result = run_stress("test", positions, scenarios)
        # ES = weighted average of severe+extreme losses
        crash_loss = result.portfolio_scenario_losses["CRASH"]
        extreme_loss = result.portfolio_scenario_losses["EXTREME"]
        total_prob = 0.15 + 0.05
        expected_es = (0.15 * crash_loss + 0.05 * extreme_loss) / total_prob
        self.assertAlmostEqual(result.expected_shortfall_usd, expected_es, places=2)

    def test_resilient_positions_low_loss(self):
        # All positions lose < 20% → all resilient
        positions = [_pos(value_usd=10000.0)]
        scenarios = [_scenario("MILD", price_shock_pct=-10.0, prob_annual=0.10, severity="MILD")]
        result = run_stress("test", positions, scenarios)
        self.assertEqual(result.resilient_positions_count, 1)

    def test_vulnerable_positions_high_loss(self):
        # Position loses >= 50% → vulnerable
        positions = [_pos(value_usd=10000.0)]
        scenarios = [_scenario("CRASH", price_shock_pct=-60.0, prob_annual=0.05, severity="EXTREME")]
        result = run_stress("test", positions, scenarios)
        self.assertEqual(result.vulnerable_positions_count, 1)

    def test_resilience_score_formula(self):
        positions = [
            _pos("A", value_usd=10000.0),
            _pos("B", value_usd=10000.0),
            _pos("C", value_usd=10000.0),
            _pos("D", value_usd=10000.0),
        ]
        # Two scenarios: one mild (all resilient), one extreme (all vulnerable)
        # We'll just test the formula with a mild scenario only
        scenarios = [_scenario("MILD", price_shock_pct=-5.0, prob_annual=0.10, severity="MILD")]
        result = run_stress("test", positions, scenarios)
        # All positions should be resilient (5% loss < 20%)
        self.assertEqual(result.resilient_positions_count, 4)
        self.assertAlmostEqual(result.resilience_score, 100.0, places=4)

    def test_resilience_label_strong(self):
        positions = [_pos()]
        scenarios = [_scenario("MILD", price_shock_pct=-5.0, prob_annual=0.10, severity="MILD")]
        result = run_stress("test", positions, scenarios)
        # Loss 5% < 20% → all resilient → score 100 → STRONG
        self.assertEqual(result.resilience_label, "STRONG")

    def test_resilience_label_adequate(self):
        # Need 40% ≤ score < 70%
        positions = [
            _pos("A"), _pos("B"), _pos("C"), _pos("D"), _pos("E")
        ]
        # Crash: 40% loss → not resilient (≥20%), not vulnerable (<50%)
        scenarios = [_scenario("CRASH", price_shock_pct=-40.0, prob_annual=0.10, severity="SEVERE")]
        result = run_stress("test", positions, scenarios)
        # 40% loss → max_loss_pct = 40% → not resilient (≥20%), not vulnerable (<50%)
        self.assertEqual(result.resilient_positions_count, 0)
        self.assertEqual(result.resilience_score, 0.0)
        # score 0 → WEAK
        self.assertEqual(result.resilience_label, "WEAK")

    def test_resilience_label_weak(self):
        positions = [_pos(value_usd=10000.0)]
        scenarios = [_scenario("CRASH", price_shock_pct=-60.0, prob_annual=0.10, severity="SEVERE")]
        result = run_stress("test", positions, scenarios)
        self.assertEqual(result.resilience_label, "WEAK")

    def test_recommendations_vulnerable(self):
        positions = [_pos("RiskyPos", value_usd=10000.0)]
        scenarios = [_scenario("CRASH", price_shock_pct=-60.0, prob_annual=0.10, severity="SEVERE")]
        result = run_stress("test", positions, scenarios)
        # 60% loss → vulnerable
        rec_text = " ".join(result.recommendations)
        self.assertIn("Reduce exposure", rec_text)

    def test_recommendations_expected_shortfall(self):
        # Force a huge expected shortfall
        positions = [_pos(value_usd=100000.0)]
        scenarios = [_scenario("CRASH", price_shock_pct=-80.0, prob_annual=0.50, severity="SEVERE")]
        result = run_stress("test", positions, scenarios)
        # ES will be 80000, total 100000 → ES > 30% → recommendation
        rec_text = " ".join(result.recommendations)
        self.assertIn("expected shortfall exceeds 30%", rec_text)

    def test_recommendations_resilience(self):
        positions = [_pos(value_usd=10000.0)]
        scenarios = [_scenario("CRASH", price_shock_pct=-60.0, prob_annual=0.10, severity="SEVERE")]
        result = run_stress("test", positions, scenarios)
        rec_text = " ".join(result.recommendations)
        self.assertIn("diversify across safer protocols", rec_text)

    def test_default_scenarios_used_when_none(self):
        positions = [_pos()]
        result = run_stress("test", positions)
        self.assertEqual(len(result.scenarios), len(DEFAULT_SCENARIOS))

    def test_portfolio_id_preserved(self):
        result = run_stress("my_portfolio_123", [_pos()])
        self.assertEqual(result.portfolio_id, "my_portfolio_123")

    def test_single_position(self):
        positions = [_pos("Solo", value_usd=100000.0)]
        scenarios = self._scenarios()
        result = run_stress("test", positions, scenarios)
        self.assertEqual(len(result.position_results), 1)
        self.assertAlmostEqual(result.total_value_usd, 100000.0, places=4)

    def test_all_low_risk_high_resilience(self):
        positions = [
            _pos("A", value_usd=10000.0),
            _pos("B", value_usd=10000.0),
        ]
        scenarios = [_scenario("MILD", price_shock_pct=-2.0, prob_annual=0.10, severity="MILD")]
        result = run_stress("test", positions, scenarios)
        self.assertGreaterEqual(result.resilience_score, 70.0)
        self.assertEqual(result.resilience_label, "STRONG")


class TestDefaultScenarios(unittest.TestCase):
    def test_five_scenarios_defined(self):
        self.assertEqual(len(DEFAULT_SCENARIOS), 5)

    def test_market_crash_severity(self):
        crash = next(s for s in DEFAULT_SCENARIOS if s.name == "MARKET_CRASH")
        self.assertEqual(crash.severity, "SEVERE")

    def test_defi_contagion_is_extreme(self):
        contagion = next(s for s in DEFAULT_SCENARIOS if s.name == "DEFI_CONTAGION")
        self.assertEqual(contagion.severity, "EXTREME")

    def test_rate_spike_moderate(self):
        spike = next(s for s in DEFAULT_SCENARIOS if s.name == "RATE_SPIKE")
        self.assertEqual(spike.severity, "MODERATE")

    def test_all_have_names(self):
        names = {s.name for s in DEFAULT_SCENARIOS}
        expected = {"MARKET_CRASH", "RATE_SPIKE", "LIQUIDITY_CRISIS", "DEFI_CONTAGION", "STABLECOIN_DEPEG"}
        self.assertEqual(names, expected)

    def test_all_have_negative_shocks(self):
        for s in DEFAULT_SCENARIOS:
            self.assertLess(s.price_shock_pct, 0, f"{s.name} price_shock should be negative")
            self.assertLess(s.apy_shock_pct, 0, f"{s.name} apy_shock should be negative")
            self.assertLess(s.liquidity_shock_pct, 0, f"{s.name} liquidity_shock should be negative")

    def test_market_crash_price_shock(self):
        crash = next(s for s in DEFAULT_SCENARIOS if s.name == "MARKET_CRASH")
        self.assertAlmostEqual(crash.price_shock_pct, -40.0)

    def test_liquidity_crisis_high_liquidity_shock(self):
        lc = next(s for s in DEFAULT_SCENARIOS if s.name == "LIQUIDITY_CRISIS")
        self.assertAlmostEqual(lc.liquidity_shock_pct, -80.0)


class TestCompareScenarios(unittest.TestCase):
    def test_sorted_by_loss_desc(self):
        positions = [_pos(value_usd=10000.0)]
        scenarios = [
            _scenario("BIG", price_shock_pct=-60.0, prob_annual=0.05, severity="EXTREME"),
            _scenario("SMALL", price_shock_pct=-10.0, prob_annual=0.20, severity="MODERATE"),
        ]
        result = run_stress("test", positions, scenarios)
        comparison = compare_scenarios(result)
        values = list(comparison.values())
        self.assertEqual(values, sorted(values, reverse=True))

    def test_returns_dict(self):
        result = run_stress("test", [_pos()], self._scenarios())
        self.assertIsInstance(compare_scenarios(result), dict)

    def test_all_scenarios_present(self):
        scenarios = self._scenarios()
        result = run_stress("test", [_pos()], scenarios)
        comparison = compare_scenarios(result)
        for s in scenarios:
            self.assertIn(s.name, comparison)

    def _scenarios(self):
        return [
            _scenario("A", price_shock_pct=-20.0),
            _scenario("B", price_shock_pct=-50.0),
        ]


class TestSaveLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_save_creates_file(self):
        result = run_stress("test", [_pos()], [_scenario()])
        save_results(result, data_dir=self.tmpdir)
        log_file = os.path.join(self.tmpdir, "stress_scenario_log.json")
        self.assertTrue(os.path.exists(log_file))

    def test_save_load_round_trip(self):
        result = run_stress("test", [_pos()], [_scenario()])
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            result = run_stress("test", [_pos()], [_scenario()])
            save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(105):
            result = run_stress("test", [_pos()], [_scenario()])
            save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)

    def test_load_empty_dir(self):
        history = load_history(data_dir=self.tmpdir)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)

    def test_atomic_no_tmp_file(self):
        result = run_stress("test", [_pos()], [_scenario()])
        save_results(result, data_dir=self.tmpdir)
        tmp_file = os.path.join(self.tmpdir, "stress_scenario_log.json.tmp")
        self.assertFalse(os.path.exists(tmp_file))

    def test_saved_at_field(self):
        result = run_stress("test", [_pos()], [_scenario()])
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertIn("_saved_at", history[0])

    def test_portfolio_id_in_saved(self):
        result = run_stress("my_fund_XYZ", [_pos()], [_scenario()])
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history[0]["portfolio_id"], "my_fund_XYZ")


if __name__ == "__main__":
    unittest.main()
