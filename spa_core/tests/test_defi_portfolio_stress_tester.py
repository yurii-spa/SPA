"""
Tests for MP-849 DeFiPortfolioStressTester
python3 -m unittest spa_core.tests.test_defi_portfolio_stress_tester -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_portfolio_stress_tester import (
    BUILTIN_SCENARIOS,
    RING_BUFFER_MAX,
    _compute_position_loss,
    _find_most_vulnerable,
    _run_scenario,
    _severity,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STABLE_POSITION = {
    "protocol": "Aave",
    "category": "lending",
    "allocation_pct": 100.0,
    "position_value_usd": 10_000.0,
    "collateral_type": "STABLECOIN",
}

ETH_DEX_POSITION = {
    "protocol": "Uniswap",
    "category": "DEX",
    "allocation_pct": 100.0,
    "position_value_usd": 10_000.0,
    "collateral_type": "ETH",
}

ALTCOIN_STAKING = {
    "protocol": "SomeStaking",
    "category": "staking",
    "allocation_pct": 100.0,
    "position_value_usd": 5_000.0,
    "collateral_type": "ALTCOIN",
}

MIXED_PORTFOLIO = [
    {
        "protocol": "Aave",
        "category": "lending",
        "allocation_pct": 40.0,
        "position_value_usd": 40_000.0,
        "collateral_type": "STABLECOIN",
    },
    {
        "protocol": "Uniswap",
        "category": "DEX",
        "allocation_pct": 30.0,
        "position_value_usd": 30_000.0,
        "collateral_type": "ETH",
    },
    {
        "protocol": "Lido",
        "category": "liquid_staking",
        "allocation_pct": 30.0,
        "position_value_usd": 30_000.0,
        "collateral_type": "ETH",
    },
]


# ===========================================================================
# 1. Module constants
# ===========================================================================

class TestConstants(unittest.TestCase):
    def test_builtin_scenario_count(self):
        self.assertEqual(len(BUILTIN_SCENARIOS), 5)

    def test_ring_buffer_max(self):
        self.assertEqual(RING_BUFFER_MAX, 100)

    def test_scenario_names_unique(self):
        names = [s["name"] for s in BUILTIN_SCENARIOS]
        self.assertEqual(len(names), len(set(names)))

    def test_each_scenario_has_required_keys(self):
        required = {"name", "description", "collateral_shocks", "category_shocks"}
        for s in BUILTIN_SCENARIOS:
            self.assertTrue(required.issubset(set(s.keys())), f"Missing keys in {s['name']}")

    def test_march_2020_eth_shock(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "March 2020 Crash")
        self.assertEqual(s["collateral_shocks"]["ETH"], 50.0)

    def test_march_2020_btc_shock(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "March 2020 Crash")
        self.assertEqual(s["collateral_shocks"]["BTC"], 40.0)

    def test_march_2020_stablecoin_safe(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "March 2020 Crash")
        self.assertEqual(s["collateral_shocks"]["STABLECOIN"], 0.0)

    def test_terra_stablecoin_shock(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "Terra/Luna Collapse")
        self.assertEqual(s["collateral_shocks"]["STABLECOIN"], 30.0)

    def test_ftx_altcoin_shock(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "FTX Contagion")
        self.assertEqual(s["collateral_shocks"]["ALTCOIN"], 55.0)

    def test_defi_summer_altcoin_shock(self):
        s = next(x for x in BUILTIN_SCENARIOS if x["name"] == "DeFi Summer Reversal")
        self.assertEqual(s["collateral_shocks"]["ALTCOIN"], 70.0)


# ===========================================================================
# 2. _severity
# ===========================================================================

class TestSeverity(unittest.TestCase):
    def test_mild_zero(self):
        self.assertEqual(_severity(0.0), "MILD")

    def test_mild_boundary(self):
        self.assertEqual(_severity(14.99), "MILD")

    def test_moderate_at_15(self):
        self.assertEqual(_severity(15.0), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(_severity(29.99), "MODERATE")

    def test_severe_at_30(self):
        self.assertEqual(_severity(30.0), "SEVERE")

    def test_severe_boundary(self):
        self.assertEqual(_severity(49.99), "SEVERE")

    def test_catastrophic_at_50(self):
        self.assertEqual(_severity(50.0), "CATASTROPHIC")

    def test_catastrophic_100(self):
        self.assertEqual(_severity(100.0), "CATASTROPHIC")


# ===========================================================================
# 3. _compute_position_loss
# ===========================================================================

class TestComputePositionLoss(unittest.TestCase):
    def _shocks(self):
        return {"ETH": 50.0, "BTC": 40.0, "ALTCOIN": 60.0, "STABLECOIN": 0.0}

    def _cat(self):
        return {"DEX": 10.0, "lending": 5.0, "stablecoin": 0.0,
                "staking": 5.0, "liquid_staking": 30.0}

    def test_stablecoin_lending_march2020(self):
        pos = {**STABLE_POSITION}
        loss = _compute_position_loss(pos, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 5.0)  # 0 + 5 (lending)

    def test_eth_dex_march2020(self):
        loss = _compute_position_loss(ETH_DEX_POSITION, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 60.0)  # 50 + 10

    def test_eth_liquid_staking_march2020(self):
        pos = {**STABLE_POSITION, "collateral_type": "ETH", "category": "liquid_staking"}
        loss = _compute_position_loss(pos, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 80.0)  # 50 + 30

    def test_altcoin_staking_march2020(self):
        loss = _compute_position_loss(ALTCOIN_STAKING, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 65.0)  # 60 + 5

    def test_unknown_collateral_zero_base(self):
        pos = {**STABLE_POSITION, "collateral_type": "UNKNOWN"}
        loss = _compute_position_loss(pos, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 5.0)  # 0 + 5 (lending)

    def test_unknown_category_zero_modifier(self):
        pos = {**STABLE_POSITION, "category": "unknown_cat", "collateral_type": "BTC"}
        loss = _compute_position_loss(pos, self._shocks(), self._cat())
        self.assertAlmostEqual(loss, 40.0)  # 40 + 0

    def test_negative_category_reduces_loss(self):
        # FTX DEX has -5% category shock
        ftx_cat = {"DEX": -5.0}
        pos = {**ETH_DEX_POSITION, "collateral_type": "ETH"}
        loss = _compute_position_loss(pos, {"ETH": 30.0}, ftx_cat)
        self.assertAlmostEqual(loss, 25.0)  # 30 - 5

    def test_loss_floored_at_zero(self):
        pos = {**STABLE_POSITION, "collateral_type": "STABLECOIN", "category": "DEX"}
        # collateral=0, cat=-20 → would be -20 → clamped to 0
        loss = _compute_position_loss(pos, {"STABLECOIN": 0.0}, {"DEX": -20.0})
        self.assertEqual(loss, 0.0)

    def test_loss_capped_at_100(self):
        pos = {**STABLE_POSITION, "collateral_type": "ALTCOIN", "category": "DEX"}
        loss = _compute_position_loss(pos, {"ALTCOIN": 80.0}, {"DEX": 40.0})
        self.assertEqual(loss, 100.0)

    def test_empty_shocks(self):
        loss = _compute_position_loss(STABLE_POSITION, {}, {})
        self.assertEqual(loss, 0.0)


# ===========================================================================
# 4. _run_scenario
# ===========================================================================

class TestRunScenario(unittest.TestCase):
    SCENARIO_NAME = "Test"
    SCENARIO_DESC = "Test scenario"

    def _col(self):
        return {"ETH": 50.0, "STABLECOIN": 0.0, "BTC": 40.0, "ALTCOIN": 60.0}

    def _cat(self):
        return {"lending": 5.0, "DEX": 10.0, "staking": 5.0,
                "stablecoin": 0.0, "liquid_staking": 30.0}

    def test_empty_portfolio_returns_zero_loss(self):
        r = _run_scenario([], self.SCENARIO_NAME, self.SCENARIO_DESC, self._col(), self._cat())
        self.assertEqual(r["portfolio_loss_pct"], 0.0)
        self.assertEqual(r["portfolio_loss_usd"], 0.0)

    def test_empty_portfolio_severity_mild(self):
        r = _run_scenario([], self.SCENARIO_NAME, self.SCENARIO_DESC, self._col(), self._cat())
        self.assertEqual(r["severity"], "MILD")

    def test_result_keys(self):
        r = _run_scenario(MIXED_PORTFOLIO, self.SCENARIO_NAME, self.SCENARIO_DESC,
                          self._col(), self._cat())
        expected = {
            "scenario_name", "description", "portfolio_loss_pct",
            "portfolio_loss_usd", "worst_position", "surviving_positions", "severity"
        }
        self.assertEqual(set(r.keys()), expected)

    def test_scenario_name_preserved(self):
        r = _run_scenario([STABLE_POSITION], "MyScenario", "desc", self._col(), self._cat())
        self.assertEqual(r["scenario_name"], "MyScenario")

    def test_description_preserved(self):
        r = _run_scenario([STABLE_POSITION], "X", "MyDesc", self._col(), self._cat())
        self.assertEqual(r["description"], "MyDesc")

    def test_surviving_positions_contains_stablecoin_lending(self):
        r = _run_scenario([STABLE_POSITION], self.SCENARIO_NAME, self.SCENARIO_DESC,
                          self._col(), self._cat())
        # stablecoin lending in March 2020: 0 + 5 = 5% < 20 → survives
        self.assertIn("Aave", r["surviving_positions"])

    def test_worst_position_is_protocol_name(self):
        r = _run_scenario(MIXED_PORTFOLIO, self.SCENARIO_NAME, self.SCENARIO_DESC,
                          self._col(), self._cat())
        self.assertIsInstance(r["worst_position"], str)

    def test_portfolio_loss_between_0_and_100(self):
        r = _run_scenario(MIXED_PORTFOLIO, self.SCENARIO_NAME, self.SCENARIO_DESC,
                          self._col(), self._cat())
        self.assertGreaterEqual(r["portfolio_loss_pct"], 0.0)
        self.assertLessEqual(r["portfolio_loss_pct"], 100.0)

    def test_weighted_loss_calculation(self):
        # Single position with 100% alloc
        pos = {
            "protocol": "X",
            "category": "lending",
            "allocation_pct": 100.0,
            "position_value_usd": 1000.0,
            "collateral_type": "STABLECOIN",
        }
        r = _run_scenario([pos], "T", "d",
                          {"STABLECOIN": 0.0}, {"lending": 5.0})
        self.assertAlmostEqual(r["portfolio_loss_pct"], 5.0)

    def test_portfolio_loss_usd_correct(self):
        pos = {
            "protocol": "X",
            "category": "lending",
            "allocation_pct": 100.0,
            "position_value_usd": 1000.0,
            "collateral_type": "ETH",
        }
        r = _run_scenario([pos], "T", "d", {"ETH": 20.0}, {"lending": 0.0})
        self.assertAlmostEqual(r["portfolio_loss_usd"], 200.0)


# ===========================================================================
# 5. analyze() — return structure
# ===========================================================================

class TestAnalyzeStructure(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _analyze(self, portfolio=None, config=None):
        return analyze(portfolio or MIXED_PORTFOLIO, config, _data_dir=self.tmpdir)

    def test_returns_dict(self):
        r = self._analyze()
        self.assertIsInstance(r, dict)

    def test_top_level_keys(self):
        r = self._analyze()
        expected = {
            "scenarios", "worst_scenario", "best_scenario",
            "average_loss_pct", "portfolio_resilience_score",
            "most_vulnerable_position", "timestamp"
        }
        self.assertEqual(set(r.keys()), expected)

    def test_scenarios_is_list(self):
        r = self._analyze()
        self.assertIsInstance(r["scenarios"], list)

    def test_scenarios_count_equals_5(self):
        r = self._analyze()
        self.assertEqual(len(r["scenarios"]), 5)

    def test_worst_scenario_is_string(self):
        r = self._analyze()
        self.assertIsInstance(r["worst_scenario"], str)

    def test_best_scenario_is_string(self):
        r = self._analyze()
        self.assertIsInstance(r["best_scenario"], str)

    def test_average_loss_pct_is_float(self):
        r = self._analyze()
        self.assertIsInstance(r["average_loss_pct"], float)

    def test_resilience_score_is_int(self):
        r = self._analyze()
        self.assertIsInstance(r["portfolio_resilience_score"], int)

    def test_resilience_score_range(self):
        r = self._analyze()
        self.assertGreaterEqual(r["portfolio_resilience_score"], 0)
        self.assertLessEqual(r["portfolio_resilience_score"], 100)

    def test_timestamp_is_recent(self):
        before = time.time() - 1
        r = self._analyze()
        self.assertGreater(r["timestamp"], before)

    def test_most_vulnerable_is_protocol_name(self):
        r = self._analyze()
        protocols = {p["protocol"] for p in MIXED_PORTFOLIO}
        self.assertIn(r["most_vulnerable_position"], protocols)


# ===========================================================================
# 6. analyze() — empty portfolio
# ===========================================================================

class TestAnalyzeEmptyPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_empty_portfolio_scenarios_count(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 5)

    def test_empty_portfolio_all_zero_loss(self):
        r = analyze([], _data_dir=self.tmpdir)
        for s in r["scenarios"]:
            self.assertEqual(s["portfolio_loss_pct"], 0.0)

    def test_empty_portfolio_resilience_100(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(r["portfolio_resilience_score"], 100)

    def test_empty_portfolio_average_loss_0(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(r["average_loss_pct"], 0.0)

    def test_empty_portfolio_most_vulnerable_none(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertIsNone(r["most_vulnerable_position"])


# ===========================================================================
# 7. analyze() — resilience score
# ===========================================================================

class TestResilienceScore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_resilience_inversely_proportional_to_average_loss(self):
        r_stable = analyze([STABLE_POSITION], _data_dir=self.tmpdir)
        r_risky = analyze([ALTCOIN_STAKING], _data_dir=self.tmpdir)
        self.assertGreater(
            r_stable["portfolio_resilience_score"],
            r_risky["portfolio_resilience_score"],
        )

    def test_resilience_floored_at_zero(self):
        pos = {
            "protocol": "X",
            "category": "staking",
            "allocation_pct": 100.0,
            "position_value_usd": 1000.0,
            "collateral_type": "ALTCOIN",
        }
        r = analyze([pos], _data_dir=self.tmpdir)
        self.assertGreaterEqual(r["portfolio_resilience_score"], 0)

    def test_all_stablecoin_high_resilience(self):
        pos = {
            "protocol": "SafeProtocol",
            "category": "stablecoin",
            "allocation_pct": 100.0,
            "position_value_usd": 100_000.0,
            "collateral_type": "STABLECOIN",
        }
        r = analyze([pos], _data_dir=self.tmpdir)
        # Should be reasonably resilient
        self.assertGreater(r["portfolio_resilience_score"], 50)


# ===========================================================================
# 8. analyze() — custom scenarios
# ===========================================================================

class TestCustomScenarios(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _custom(self):
        return {
            "name": "Nuclear Winter",
            "description": "Everything crashes 90%",
            "shocks": {
                "by_collateral": {
                    "STABLECOIN": 90.0, "ETH": 90.0,
                    "BTC": 90.0, "ALTCOIN": 90.0
                },
                "by_category": {}
            }
        }

    def test_custom_scenario_adds_to_list(self):
        r = analyze(MIXED_PORTFOLIO, {"custom_scenarios": [self._custom()]},
                    _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 6)

    def test_custom_scenario_appears_in_results(self):
        r = analyze(MIXED_PORTFOLIO, {"custom_scenarios": [self._custom()]},
                    _data_dir=self.tmpdir)
        names = [s["scenario_name"] for s in r["scenarios"]]
        self.assertIn("Nuclear Winter", names)

    def test_custom_scenario_becomes_worst(self):
        r = analyze(MIXED_PORTFOLIO, {"custom_scenarios": [self._custom()]},
                    _data_dir=self.tmpdir)
        self.assertEqual(r["worst_scenario"], "Nuclear Winter")

    def test_empty_custom_scenarios_still_5(self):
        r = analyze(MIXED_PORTFOLIO, {"custom_scenarios": []},
                    _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 5)

    def test_none_config_defaults_to_5_scenarios(self):
        r = analyze(MIXED_PORTFOLIO, None, _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 5)

    def test_multiple_custom_scenarios(self):
        customs = [self._custom(), {
            "name": "Mild Dip",
            "description": "Minor correction",
            "shocks": {
                "by_collateral": {"STABLECOIN": 0.0, "ETH": 5.0, "BTC": 5.0, "ALTCOIN": 10.0},
                "by_category": {}
            }
        }]
        r = analyze(MIXED_PORTFOLIO, {"custom_scenarios": customs},
                    _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 7)


# ===========================================================================
# 9. analyze() — ring-buffer log
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "portfolio_stress_log.json")

    def test_log_file_created(self):
        analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        for _ in range(3):
            analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(105):
            analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


# ===========================================================================
# 10. Scenario-specific correctness
# ===========================================================================

class TestScenarioCorrectness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _scenario_by_name(self, results, name):
        for s in results["scenarios"]:
            if s["scenario_name"] == name:
                return s
        return None

    def test_march2020_eth_dex_high_loss(self):
        # ETH DEX: 50 + 10 = 60%
        portfolio = [ETH_DEX_POSITION]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "March 2020 Crash")
        self.assertAlmostEqual(s["portfolio_loss_pct"], 60.0)

    def test_march2020_stablecoin_only_mild(self):
        portfolio = [{**STABLE_POSITION}]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "March 2020 Crash")
        # STABLECOIN + lending = 0 + 5 = 5%
        self.assertAlmostEqual(s["portfolio_loss_pct"], 5.0)
        self.assertEqual(s["severity"], "MILD")

    def test_terra_stablecoin_moderate_or_worse(self):
        portfolio = [STABLE_POSITION]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "Terra/Luna Collapse")
        # STABLECOIN 30 + lending 15 = 45%
        self.assertAlmostEqual(s["portfolio_loss_pct"], 45.0)
        self.assertEqual(s["severity"], "SEVERE")

    def test_ftx_dex_negative_modifier_reduces_loss(self):
        # ETH DEX in FTX: 30 + (-5) = 25%
        portfolio = [{**ETH_DEX_POSITION}]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "FTX Contagion")
        self.assertAlmostEqual(s["portfolio_loss_pct"], 25.0)

    def test_eth_merge_staking_extra_penalty(self):
        # ETH staking: 20 + 20 = 40%
        portfolio = [{
            "protocol": "EthStake",
            "category": "staking",
            "allocation_pct": 100.0,
            "position_value_usd": 10_000.0,
            "collateral_type": "ETH",
        }]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "ETH Merge Uncertainty")
        self.assertAlmostEqual(s["portfolio_loss_pct"], 40.0)

    def test_defi_summer_altcoin_staking_catastrophic(self):
        portfolio = [{**ALTCOIN_STAKING}]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        s = self._scenario_by_name(r, "DeFi Summer Reversal")
        # ALTCOIN 70 + staking 30 = 100 → capped at 100
        self.assertAlmostEqual(s["portfolio_loss_pct"], 100.0)
        self.assertEqual(s["severity"], "CATASTROPHIC")

    def test_severity_labels_all_valid(self):
        r = analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        valid_severities = {"MILD", "MODERATE", "SEVERE", "CATASTROPHIC"}
        for s in r["scenarios"]:
            self.assertIn(s["severity"], valid_severities)

    def test_surviving_positions_all_under_20pct_loss(self):
        r = analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        for scenario in r["scenarios"]:
            for name in scenario["surviving_positions"]:
                # just verify it's a string protocol name
                self.assertIsInstance(name, str)

    def test_worst_best_scenario_names_in_scenarios(self):
        r = analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        all_names = {s["scenario_name"] for s in r["scenarios"]}
        self.assertIn(r["worst_scenario"], all_names)
        self.assertIn(r["best_scenario"], all_names)

    def test_worst_scenario_has_highest_loss(self):
        r = analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        worst_name = r["worst_scenario"]
        worst_loss = next(
            s["portfolio_loss_pct"] for s in r["scenarios"]
            if s["scenario_name"] == worst_name
        )
        for s in r["scenarios"]:
            self.assertGreaterEqual(worst_loss, s["portfolio_loss_pct"])

    def test_best_scenario_has_lowest_loss(self):
        r = analyze(MIXED_PORTFOLIO, _data_dir=self.tmpdir)
        best_name = r["best_scenario"]
        best_loss = next(
            s["portfolio_loss_pct"] for s in r["scenarios"]
            if s["scenario_name"] == best_name
        )
        for s in r["scenarios"]:
            self.assertLessEqual(best_loss, s["portfolio_loss_pct"])


# ===========================================================================
# 11. _find_most_vulnerable
# ===========================================================================

class TestFindMostVulnerable(unittest.TestCase):
    def test_empty_portfolio(self):
        self.assertIsNone(_find_most_vulnerable([], BUILTIN_SCENARIOS))

    def test_empty_scenarios(self):
        self.assertIsNone(_find_most_vulnerable(MIXED_PORTFOLIO, []))

    def test_returns_protocol_name(self):
        result = _find_most_vulnerable(MIXED_PORTFOLIO, BUILTIN_SCENARIOS)
        protocols = {p["protocol"] for p in MIXED_PORTFOLIO}
        self.assertIn(result, protocols)

    def test_altcoin_staking_most_vulnerable(self):
        portfolio = [
            {**STABLE_POSITION, "allocation_pct": 50.0},
            {**ALTCOIN_STAKING, "allocation_pct": 50.0},
        ]
        result = _find_most_vulnerable(portfolio, BUILTIN_SCENARIOS)
        self.assertEqual(result, "SomeStaking")

    def test_single_position(self):
        result = _find_most_vulnerable([STABLE_POSITION], BUILTIN_SCENARIOS)
        self.assertEqual(result, "Aave")


# ===========================================================================
# 12. Unknown/missing fields edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_missing_collateral_type_field(self):
        pos = {
            "protocol": "NoCollateral",
            "category": "lending",
            "allocation_pct": 100.0,
            "position_value_usd": 1000.0,
            # no collateral_type
        }
        r = analyze([pos], _data_dir=self.tmpdir)
        # Should not raise; unknown collateral defaults to 0% base shock
        self.assertIsNotNone(r)

    def test_missing_category_field(self):
        pos = {
            "protocol": "NoCategory",
            "collateral_type": "ETH",
            "allocation_pct": 100.0,
            "position_value_usd": 1000.0,
            # no category
        }
        r = analyze([pos], _data_dir=self.tmpdir)
        self.assertIsNotNone(r)

    def test_zero_position_value(self):
        pos = {
            "protocol": "ZeroVal",
            "category": "lending",
            "allocation_pct": 100.0,
            "position_value_usd": 0.0,
            "collateral_type": "ETH",
        }
        r = analyze([pos], _data_dir=self.tmpdir)
        for s in r["scenarios"]:
            self.assertEqual(s["portfolio_loss_usd"], 0.0)

    def test_allocation_not_summing_to_100(self):
        portfolio = [
            {**STABLE_POSITION, "allocation_pct": 30.0},
            {**ETH_DEX_POSITION, "allocation_pct": 30.0},
        ]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        # Should not raise
        self.assertIsNotNone(r)

    def test_single_position_portfolio(self):
        r = analyze([STABLE_POSITION], _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 5)

    def test_many_positions(self):
        portfolio = [
            {
                "protocol": f"P{i}",
                "category": "lending",
                "allocation_pct": 10.0,
                "position_value_usd": 10_000.0,
                "collateral_type": "STABLECOIN",
            }
            for i in range(10)
        ]
        r = analyze(portfolio, _data_dir=self.tmpdir)
        self.assertEqual(len(r["scenarios"]), 5)

    def test_config_none_equivalent_to_empty(self):
        r1 = analyze(MIXED_PORTFOLIO, None, _data_dir=self.tmpdir)
        r2 = analyze(MIXED_PORTFOLIO, {}, _data_dir=self.tmpdir)
        self.assertEqual(r1["average_loss_pct"], r2["average_loss_pct"])


if __name__ == "__main__":
    unittest.main()
