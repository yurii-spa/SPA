"""
Tests for MP-877: DeFiVaultStrategyComparator
python3 -m unittest spa_core/tests/test_defi_vault_strategy_comparator.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import spa_core.analytics.defi_vault_strategy_comparator as mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_strategy(**kwargs):
    base = {
        "name": "TestStrat",
        "strategy_type": "SINGLE_ASSET",
        "net_apy_pct": 5.0,
        "risk_multiplier": 1.0,
        "min_capital_usd": 0.0,
        "max_capital_usd": 0.0,
        "rebalance_frequency_days": 30,
        "gas_cost_per_month_usd": 0.0,
        "requires_active_management": False,
    }
    base.update(kwargs)
    return base


def make_config(**kwargs):
    base = {
        "user_capital_usd": 10_000.0,
        "max_acceptable_risk": 3.0,
        "management_preference": "ANY",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):

    def test_empty_strategies_returns_dict(self):
        r = mod.analyze([], {})
        self.assertIsInstance(r, dict)

    def test_empty_strategies_list(self):
        r = mod.analyze([], {})
        self.assertEqual(r["strategies"], [])

    def test_empty_best_strategy_none(self):
        r = mod.analyze([], {})
        self.assertIsNone(r["best_strategy"])

    def test_empty_best_by_type(self):
        r = mod.analyze([], {})
        self.assertEqual(r["best_by_type"], {})

    def test_empty_suitable_count(self):
        r = mod.analyze([], {})
        self.assertEqual(r["suitable_count"], 0)

    def test_empty_comparison_summary(self):
        r = mod.analyze([], {})
        self.assertEqual(r["comparison_summary"], "")

    def test_empty_timestamp_present(self):
        r = mod.analyze([], {})
        self.assertIn("timestamp", r)

    def test_none_config_defaults(self):
        r = mod.analyze([], None)
        self.assertEqual(r["suitable_count"], 0)


# ---------------------------------------------------------------------------
# 2. Derived metric calculations
# ---------------------------------------------------------------------------

class TestDerivedMetrics(unittest.TestCase):

    def _analyze_one(self, **kwargs):
        s = make_strategy(**kwargs)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        return r["strategies"][0]

    def test_risk_adjusted_apy_basic(self):
        e = self._analyze_one(net_apy_pct=10.0, risk_multiplier=2.0)
        self.assertAlmostEqual(e["risk_adjusted_apy_pct"], 5.0, places=4)

    def test_risk_adjusted_apy_risk_one(self):
        e = self._analyze_one(net_apy_pct=8.0, risk_multiplier=1.0)
        self.assertAlmostEqual(e["risk_adjusted_apy_pct"], 8.0, places=4)

    def test_annualized_gas_drag(self):
        # gas=100/month, capital=10000 → 100*12/10000*100 = 12%
        e = self._analyze_one(gas_cost_per_month_usd=100.0)
        self.assertAlmostEqual(e["annualized_gas_drag_pct"], 12.0, places=4)

    def test_monthly_gas_drag(self):
        # gas=100/month, capital=10000 → 100/10000*100 = 1%
        e = self._analyze_one(gas_cost_per_month_usd=100.0)
        self.assertAlmostEqual(e["monthly_gas_drag_pct"], 1.0, places=4)

    def test_net_net_apy_with_gas(self):
        # risk_adj=5.0, annualized gas=12% → net_net = 5-12 = -7
        e = self._analyze_one(
            net_apy_pct=10.0, risk_multiplier=2.0,
            gas_cost_per_month_usd=100.0
        )
        self.assertAlmostEqual(e["net_net_apy_pct"], 5.0 - 12.0, places=3)

    def test_zero_capital_gas_drag_zero(self):
        s = make_strategy(gas_cost_per_month_usd=500.0)
        r = mod.analyze([s], make_config(user_capital_usd=0))
        e = r["strategies"][0]
        self.assertEqual(e["annualized_gas_drag_pct"], 0.0)
        self.assertEqual(e["monthly_gas_drag_pct"], 0.0)

    def test_zero_risk_multiplier_risk_adj_zero(self):
        e = self._analyze_one(net_apy_pct=10.0, risk_multiplier=0.0)
        self.assertEqual(e["risk_adjusted_apy_pct"], 0.0)

    def test_net_net_no_gas(self):
        e = self._analyze_one(net_apy_pct=6.0, risk_multiplier=1.0, gas_cost_per_month_usd=0.0)
        self.assertAlmostEqual(e["net_net_apy_pct"], 6.0, places=4)


# ---------------------------------------------------------------------------
# 3. Yield score
# ---------------------------------------------------------------------------

class TestYieldScore(unittest.TestCase):

    def _score_for_net_net(self, net_net):
        return mod._yield_score(net_net)

    def test_yield_score_ge30(self):
        self.assertEqual(self._score_for_net_net(30.0), 40)
        self.assertEqual(self._score_for_net_net(50.0), 40)

    def test_yield_score_ge20(self):
        self.assertEqual(self._score_for_net_net(20.0), 35)
        self.assertEqual(self._score_for_net_net(29.9), 35)

    def test_yield_score_ge15(self):
        self.assertEqual(self._score_for_net_net(15.0), 30)

    def test_yield_score_ge10(self):
        self.assertEqual(self._score_for_net_net(10.0), 25)

    def test_yield_score_ge5(self):
        self.assertEqual(self._score_for_net_net(5.0), 18)

    def test_yield_score_ge2(self):
        self.assertEqual(self._score_for_net_net(2.0), 10)

    def test_yield_score_ge0(self):
        self.assertEqual(self._score_for_net_net(0.0), 5)
        self.assertEqual(self._score_for_net_net(1.9), 5)  # 1.9 < 2.0 → >=0 bucket

    def test_yield_score_negative(self):
        self.assertEqual(self._score_for_net_net(-1.0), 0)
        self.assertEqual(self._score_for_net_net(-100.0), 0)


# ---------------------------------------------------------------------------
# 4. Risk bonus
# ---------------------------------------------------------------------------

class TestRiskBonus(unittest.TestCase):

    def test_risk_bonus_le1(self):
        self.assertEqual(mod._risk_bonus(1.0), 30)
        self.assertEqual(mod._risk_bonus(0.5), 30)

    def test_risk_bonus_le1_5(self):
        self.assertEqual(mod._risk_bonus(1.5), 25)
        self.assertEqual(mod._risk_bonus(1.2), 25)

    def test_risk_bonus_le2(self):
        self.assertEqual(mod._risk_bonus(2.0), 18)

    def test_risk_bonus_le2_5(self):
        self.assertEqual(mod._risk_bonus(2.5), 12)

    def test_risk_bonus_le3(self):
        self.assertEqual(mod._risk_bonus(3.0), 6)

    def test_risk_bonus_gt3(self):
        self.assertEqual(mod._risk_bonus(3.1), 0)
        self.assertEqual(mod._risk_bonus(10.0), 0)


# ---------------------------------------------------------------------------
# 5. Rebalance score
# ---------------------------------------------------------------------------

class TestRebalanceScore(unittest.TestCase):

    def test_rebalance_ge30(self):
        self.assertEqual(mod._rebalance_score(30), 30)
        self.assertEqual(mod._rebalance_score(90), 30)

    def test_rebalance_ge14(self):
        self.assertEqual(mod._rebalance_score(14), 22)

    def test_rebalance_ge7(self):
        self.assertEqual(mod._rebalance_score(7), 15)

    def test_rebalance_ge3(self):
        self.assertEqual(mod._rebalance_score(3), 8)

    def test_rebalance_lt3(self):
        self.assertEqual(mod._rebalance_score(2), 0)
        self.assertEqual(mod._rebalance_score(1), 0)
        self.assertEqual(mod._rebalance_score(0), 0)


# ---------------------------------------------------------------------------
# 6. Strategy score composite & capped at 100
# ---------------------------------------------------------------------------

class TestStrategyScore(unittest.TestCase):

    def test_max_score_capped_100(self):
        # Perfect: net_net>=30, risk=1.0, rebalance=30
        score = mod._strategy_score(30.0, 1.0, 30)
        self.assertEqual(score, min(100, 40 + 30 + 30))

    def test_zero_score_all_bad(self):
        score = mod._strategy_score(-10.0, 5.0, 1)
        self.assertEqual(score, 0)

    def test_moderate_score(self):
        # net_net=10 → 25, risk=2.0 → 18, rebalance=14 → 22
        score = mod._strategy_score(10.0, 2.0, 14)
        self.assertEqual(score, 25 + 18 + 22)


# ---------------------------------------------------------------------------
# 7. Strategy grade
# ---------------------------------------------------------------------------

class TestStrategyGrade(unittest.TestCase):

    def test_grade_S(self):
        self.assertEqual(mod._strategy_grade(90), "S")
        self.assertEqual(mod._strategy_grade(100), "S")

    def test_grade_A(self):
        self.assertEqual(mod._strategy_grade(75), "A")
        self.assertEqual(mod._strategy_grade(89), "A")

    def test_grade_B(self):
        self.assertEqual(mod._strategy_grade(60), "B")
        self.assertEqual(mod._strategy_grade(74), "B")

    def test_grade_C(self):
        self.assertEqual(mod._strategy_grade(45), "C")
        self.assertEqual(mod._strategy_grade(59), "C")

    def test_grade_D(self):
        self.assertEqual(mod._strategy_grade(30), "D")
        self.assertEqual(mod._strategy_grade(44), "D")

    def test_grade_F(self):
        self.assertEqual(mod._strategy_grade(0), "F")
        self.assertEqual(mod._strategy_grade(29), "F")


# ---------------------------------------------------------------------------
# 8. Rebalance burden
# ---------------------------------------------------------------------------

class TestRebalanceBurden(unittest.TestCase):

    def test_burden_HIGH(self):
        self.assertEqual(mod._rebalance_burden(1), "HIGH")
        self.assertEqual(mod._rebalance_burden(6), "HIGH")

    def test_burden_MEDIUM(self):
        self.assertEqual(mod._rebalance_burden(7), "MEDIUM")
        self.assertEqual(mod._rebalance_burden(14), "MEDIUM")

    def test_burden_LOW(self):
        self.assertEqual(mod._rebalance_burden(15), "LOW")
        self.assertEqual(mod._rebalance_burden(30), "LOW")
        self.assertEqual(mod._rebalance_burden(365), "LOW")


# ---------------------------------------------------------------------------
# 9. Suitability — capital filters
# ---------------------------------------------------------------------------

class TestSuitabilityCapital(unittest.TestCase):

    def test_below_min_capital(self):
        s = make_strategy(min_capital_usd=50_000)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])
        self.assertIn("50000", e["suitability_reason"])
        self.assertIn("10000", e["suitability_reason"])

    def test_above_max_capital(self):
        s = make_strategy(min_capital_usd=0, max_capital_usd=5_000)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])
        self.assertIn("5000", e["suitability_reason"])

    def test_max_capital_zero_means_unlimited(self):
        s = make_strategy(min_capital_usd=0, max_capital_usd=0)
        r = mod.analyze([s], make_config(user_capital_usd=1_000_000))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])

    def test_exactly_at_min_capital(self):
        s = make_strategy(min_capital_usd=10_000)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])

    def test_exactly_at_max_capital(self):
        s = make_strategy(min_capital_usd=0, max_capital_usd=10_000)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])


# ---------------------------------------------------------------------------
# 10. Suitability — risk filter
# ---------------------------------------------------------------------------

class TestSuitabilityRisk(unittest.TestCase):

    def test_risk_above_max(self):
        s = make_strategy(risk_multiplier=4.0)
        r = mod.analyze([s], make_config(max_acceptable_risk=3.0))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])
        self.assertIn("4.0x", e["suitability_reason"])
        self.assertIn("3.0x", e["suitability_reason"])

    def test_risk_exactly_at_max(self):
        s = make_strategy(risk_multiplier=3.0)
        r = mod.analyze([s], make_config(max_acceptable_risk=3.0))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])

    def test_risk_below_max(self):
        s = make_strategy(risk_multiplier=1.5)
        r = mod.analyze([s], make_config(max_acceptable_risk=3.0))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])


# ---------------------------------------------------------------------------
# 11. Suitability — management preference
# ---------------------------------------------------------------------------

class TestSuitabilityManagement(unittest.TestCase):

    def test_passive_rejects_active(self):
        s = make_strategy(requires_active_management=True)
        r = mod.analyze([s], make_config(management_preference="PASSIVE"))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])
        self.assertIn("active", e["suitability_reason"].lower())

    def test_passive_accepts_passive(self):
        s = make_strategy(requires_active_management=False)
        r = mod.analyze([s], make_config(management_preference="PASSIVE"))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])

    def test_active_rejects_passive(self):
        s = make_strategy(requires_active_management=False)
        r = mod.analyze([s], make_config(management_preference="ACTIVE"))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])
        self.assertIn("passive", e["suitability_reason"].lower())

    def test_active_accepts_active(self):
        s = make_strategy(requires_active_management=True)
        r = mod.analyze([s], make_config(management_preference="ACTIVE"))
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])

    def test_any_accepts_both(self):
        s1 = make_strategy(name="A", requires_active_management=True)
        s2 = make_strategy(name="B", requires_active_management=False)
        r = mod.analyze([s1, s2], make_config(management_preference="ANY"))
        names_suitable = {e["name"] for e in r["strategies"] if e["is_suitable"]}
        self.assertIn("A", names_suitable)
        self.assertIn("B", names_suitable)


# ---------------------------------------------------------------------------
# 12. Suitable reason is None when suitable
# ---------------------------------------------------------------------------

class TestSuitabilityReason(unittest.TestCase):

    def test_reason_none_when_suitable(self):
        s = make_strategy()
        r = mod.analyze([s], make_config())
        e = r["strategies"][0]
        self.assertTrue(e["is_suitable"])
        self.assertIsNone(e["suitability_reason"])


# ---------------------------------------------------------------------------
# 13. best_strategy selection
# ---------------------------------------------------------------------------

class TestBestStrategy(unittest.TestCase):

    def test_best_strategy_highest_score_among_suitable(self):
        s1 = make_strategy(name="LowScore", net_apy_pct=1.0)
        s2 = make_strategy(name="HighScore", net_apy_pct=30.0)
        r = mod.analyze([s1, s2], make_config())
        self.assertEqual(r["best_strategy"], "HighScore")

    def test_best_strategy_none_when_no_suitable(self):
        s = make_strategy(risk_multiplier=10.0)
        r = mod.analyze([s], make_config(max_acceptable_risk=1.0))
        self.assertIsNone(r["best_strategy"])

    def test_best_strategy_single_suitable(self):
        s = make_strategy(name="Only", net_apy_pct=5.0)
        r = mod.analyze([s], make_config())
        self.assertEqual(r["best_strategy"], "Only")

    def test_best_strategy_excludes_unsuitable(self):
        # s1 is high score but unsuitable (risk too high)
        s1 = make_strategy(name="Risky", net_apy_pct=100.0, risk_multiplier=10.0)
        s2 = make_strategy(name="Safe", net_apy_pct=5.0, risk_multiplier=1.0)
        r = mod.analyze([s1, s2], make_config(max_acceptable_risk=3.0))
        self.assertEqual(r["best_strategy"], "Safe")


# ---------------------------------------------------------------------------
# 14. best_by_type
# ---------------------------------------------------------------------------

class TestBestByType(unittest.TestCase):

    def test_best_by_type_keys(self):
        s1 = make_strategy(name="A", strategy_type="SINGLE_ASSET", net_apy_pct=5.0)
        s2 = make_strategy(name="B", strategy_type="LP_PROVISION", net_apy_pct=10.0)
        r = mod.analyze([s1, s2], make_config())
        self.assertIn("SINGLE_ASSET", r["best_by_type"])
        self.assertIn("LP_PROVISION", r["best_by_type"])

    def test_best_by_type_includes_unsuitable(self):
        # Unsuitable strategy is still best of its type
        s = make_strategy(name="Risky", strategy_type="LEVERAGED",
                          risk_multiplier=10.0, net_apy_pct=50.0)
        r = mod.analyze([s], make_config(max_acceptable_risk=3.0))
        self.assertEqual(r["best_by_type"].get("LEVERAGED"), "Risky")

    def test_best_by_type_selects_highest_score(self):
        s1 = make_strategy(name="Low", strategy_type="DELTA_NEUTRAL", net_apy_pct=2.0)
        s2 = make_strategy(name="High", strategy_type="DELTA_NEUTRAL", net_apy_pct=20.0)
        r = mod.analyze([s1, s2], make_config())
        self.assertEqual(r["best_by_type"]["DELTA_NEUTRAL"], "High")

    def test_best_by_type_values_are_strings(self):
        s = make_strategy(name="X", strategy_type="RESTAKING")
        r = mod.analyze([s], make_config())
        self.assertIsInstance(r["best_by_type"]["RESTAKING"], str)


# ---------------------------------------------------------------------------
# 15. suitable_count
# ---------------------------------------------------------------------------

class TestSuitableCount(unittest.TestCase):

    def test_suitable_count_all_suitable(self):
        strats = [make_strategy(name=str(i)) for i in range(5)]
        r = mod.analyze(strats, make_config())
        self.assertEqual(r["suitable_count"], 5)

    def test_suitable_count_none_suitable(self):
        strats = [make_strategy(risk_multiplier=10.0) for _ in range(3)]
        r = mod.analyze(strats, make_config(max_acceptable_risk=1.0))
        self.assertEqual(r["suitable_count"], 0)

    def test_suitable_count_partial(self):
        s1 = make_strategy(name="ok", risk_multiplier=1.0)
        s2 = make_strategy(name="bad", risk_multiplier=10.0)
        r = mod.analyze([s1, s2], make_config(max_acceptable_risk=3.0))
        self.assertEqual(r["suitable_count"], 1)


# ---------------------------------------------------------------------------
# 16. comparison_summary
# ---------------------------------------------------------------------------

class TestComparisonSummary(unittest.TestCase):

    def test_summary_contains_count(self):
        strats = [make_strategy(name=str(i)) for i in range(3)]
        r = mod.analyze(strats, make_config())
        self.assertIn("3", r["comparison_summary"])

    def test_summary_contains_best(self):
        s = make_strategy(name="BestStrat")
        r = mod.analyze([s], make_config())
        self.assertIn("BestStrat", r["comparison_summary"])

    def test_summary_contains_none_when_no_suitable(self):
        s = make_strategy(risk_multiplier=10.0)
        r = mod.analyze([s], make_config(max_acceptable_risk=1.0))
        self.assertIn("none", r["comparison_summary"])

    def test_summary_contains_net_net_apy(self):
        s = make_strategy(net_apy_pct=10.0, risk_multiplier=1.0, gas_cost_per_month_usd=0.0)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        self.assertIn("10.00", r["comparison_summary"])


# ---------------------------------------------------------------------------
# 17. Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def test_all_top_level_keys(self):
        r = mod.analyze([make_strategy()], make_config())
        for key in ("strategies", "best_strategy", "best_by_type",
                    "suitable_count", "comparison_summary", "timestamp"):
            self.assertIn(key, r)

    def test_strategy_entry_keys(self):
        r = mod.analyze([make_strategy()], make_config())
        e = r["strategies"][0]
        for key in ("name", "strategy_type", "net_apy_pct",
                    "risk_adjusted_apy_pct", "monthly_gas_drag_pct",
                    "net_net_apy_pct", "annualized_gas_drag_pct",
                    "strategy_score", "strategy_grade",
                    "is_suitable", "suitability_reason", "rebalance_burden"):
            self.assertIn(key, e, msg=f"Missing key: {key}")

    def test_timestamp_is_float(self):
        r = mod.analyze([make_strategy()], make_config())
        self.assertIsInstance(r["timestamp"], float)

    def test_strategy_score_int(self):
        r = mod.analyze([make_strategy()], make_config())
        self.assertIsInstance(r["strategies"][0]["strategy_score"], int)

    def test_strategy_grade_valid(self):
        r = mod.analyze([make_strategy()], make_config())
        self.assertIn(r["strategies"][0]["strategy_grade"],
                      ("S", "A", "B", "C", "D", "F"))


# ---------------------------------------------------------------------------
# 18. Data file logging
# ---------------------------------------------------------------------------

class TestDataFileLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self.tmp) / "vault_strategy_log.json"

    def tearDown(self):
        mod.DATA_FILE = self.orig

    def test_log_file_created(self):
        mod.analyze([make_strategy()], make_config())
        self.assertTrue(mod.DATA_FILE.exists())

    def test_log_file_is_list(self):
        mod.analyze([make_strategy()], make_config())
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        mod.analyze([make_strategy()], make_config())
        mod.analyze([make_strategy()], make_config())
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_max(self):
        for _ in range(mod.MAX_ENTRIES + 5):
            mod.analyze([make_strategy()], make_config())
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), mod.MAX_ENTRIES)

    def test_log_atomic_write(self):
        # tmp file should not linger after write
        mod.analyze([make_strategy()], make_config())
        tmp_path = str(mod.DATA_FILE) + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))


# ---------------------------------------------------------------------------
# 19. Strategy types
# ---------------------------------------------------------------------------

class TestStrategyTypes(unittest.TestCase):

    def test_all_strategy_types_recognized(self):
        types = ["SINGLE_ASSET", "LP_PROVISION", "LEVERAGED",
                 "DELTA_NEUTRAL", "RESTAKING"]
        strats = [make_strategy(name=t, strategy_type=t) for t in types]
        r = mod.analyze(strats, make_config())
        returned_types = {e["strategy_type"] for e in r["strategies"]}
        for t in types:
            self.assertIn(t, returned_types)

    def test_unknown_strategy_type_passthrough(self):
        s = make_strategy(strategy_type="UNKNOWN_TYPE")
        r = mod.analyze([s], make_config())
        self.assertEqual(r["strategies"][0]["strategy_type"], "UNKNOWN_TYPE")


# ---------------------------------------------------------------------------
# 20. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_negative_net_apy(self):
        s = make_strategy(net_apy_pct=-5.0)
        r = mod.analyze([s], make_config())
        e = r["strategies"][0]
        self.assertLess(e["net_net_apy_pct"], 0)

    def test_very_high_net_apy(self):
        s = make_strategy(net_apy_pct=100.0)
        r = mod.analyze([s], make_config())
        e = r["strategies"][0]
        self.assertEqual(e["strategy_score"], 100)

    def test_score_never_exceeds_100(self):
        s = make_strategy(net_apy_pct=1000.0, risk_multiplier=0.1, rebalance_frequency_days=365)
        r = mod.analyze([s], make_config())
        self.assertLessEqual(r["strategies"][0]["strategy_score"], 100)

    def test_multiple_strategies_all_returned(self):
        strats = [make_strategy(name=f"S{i}") for i in range(10)]
        r = mod.analyze(strats, make_config())
        self.assertEqual(len(r["strategies"]), 10)

    def test_no_gas_no_drag(self):
        s = make_strategy(gas_cost_per_month_usd=0.0)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertEqual(e["annualized_gas_drag_pct"], 0.0)

    def test_rebalance_frequency_zero_is_high_burden(self):
        e = mod._rebalance_burden(0)
        self.assertEqual(e, "HIGH")

    def test_name_passthrough(self):
        s = make_strategy(name="MyUniqueStrat")
        r = mod.analyze([s], make_config())
        self.assertEqual(r["strategies"][0]["name"], "MyUniqueStrat")

    def test_default_config_applied(self):
        # Should not crash and should set defaults
        s = make_strategy()
        r = mod.analyze([s])
        self.assertIn("strategies", r)

    def test_max_capital_exactly_exceeded(self):
        s = make_strategy(max_capital_usd=9999)
        r = mod.analyze([s], make_config(user_capital_usd=10_000))
        e = r["strategies"][0]
        self.assertFalse(e["is_suitable"])

    def test_suitable_count_matches_is_suitable(self):
        strats = [make_strategy(name=f"S{i}") for i in range(5)]
        strats[0]["risk_multiplier"] = 10.0  # make first unsuitable
        r = mod.analyze(strats, make_config(max_acceptable_risk=3.0))
        count = sum(1 for e in r["strategies"] if e["is_suitable"])
        self.assertEqual(r["suitable_count"], count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
