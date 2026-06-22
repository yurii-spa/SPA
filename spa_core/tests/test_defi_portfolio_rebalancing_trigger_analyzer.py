"""
Tests for MP-950 DeFiPortfolioRebalancingTriggerAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_portfolio_rebalancing_trigger_analyzer -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from spa_core.analytics.defi_portfolio_rebalancing_trigger_analyzer import (
    DeFiPortfolioRebalancingTriggerAnalyzer,
    LABEL_IMMEDIATE,
    LABEL_RECOMMENDED,
    LABEL_OPTIONAL,
    LABEL_HOLD,
    LABEL_JUST_REBALANCED,
    FLAG_DRIFT_EXCEEDED,
    FLAG_HIGH_VOLATILITY,
    FLAG_TAX_HARVEST,
    FLAG_COST_PROHIBITIVE,
    FLAG_OVERDUE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio(**kwargs) -> dict:
    """Return a minimal valid portfolio dict, overriding with kwargs."""
    base = {
        "name": "TestPortfolio",
        "target_allocations": {"A": 50.0, "B": 50.0},
        "current_allocations": {"A": 50.0, "B": 50.0},
        "total_value_usd": 100_000.0,
        "last_rebalance_days_ago": 30.0,
        "tx_cost_estimate_usd": 50.0,
        "drift_threshold_pct": 5.0,
        "volatility_regime": "normal",
        "tax_harvesting_opportunity": False,
    }
    base.update(kwargs)
    return base


def _analyzer(data_dir=None) -> DeFiPortfolioRebalancingTriggerAnalyzer:
    return DeFiPortfolioRebalancingTriggerAnalyzer(data_dir=data_dir)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestAnalyzeReturnsStructure(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_returns_dict(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIsInstance(result, dict)

    def test_has_portfolios_key(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIn("portfolios", result)

    def test_has_aggregates_key(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIn("aggregates", result)

    def test_has_analyzed_at_key(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIn("analyzed_at", result)

    def test_portfolios_is_list(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIsInstance(result["portfolios"], list)

    def test_portfolios_length_matches_input(self):
        result = self.az.analyze([_make_portfolio(), _make_portfolio(name="B")])
        self.assertEqual(len(result["portfolios"]), 2)

    def test_empty_portfolios(self):
        result = self.az.analyze([])
        self.assertEqual(result["portfolios"], [])

    def test_empty_aggregates_total_zero(self):
        result = self.az.analyze([])
        self.assertEqual(result["aggregates"]["total_portfolios_needing_rebalance"], 0)

    def test_analyzed_at_is_string(self):
        result = self.az.analyze([_make_portfolio()])
        self.assertIsInstance(result["analyzed_at"], str)


class TestPerPortfolioFields(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()
        self.p = _make_portfolio()
        self.result = self.az.analyze([self.p])["portfolios"][0]

    def test_name_field(self):
        self.assertEqual(self.result["name"], "TestPortfolio")

    def test_max_drift_pct_present(self):
        self.assertIn("max_drift_pct", self.result)

    def test_weighted_drift_score_present(self):
        self.assertIn("weighted_drift_score", self.result)

    def test_rebalance_cost_as_pct_value_present(self):
        self.assertIn("rebalance_cost_as_pct_value", self.result)

    def test_urgency_score_present(self):
        self.assertIn("urgency_score", self.result)

    def test_label_present(self):
        self.assertIn("label", self.result)

    def test_flags_present(self):
        self.assertIn("flags", self.result)

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["flags"], list)

    def test_max_drift_pct_non_negative(self):
        self.assertGreaterEqual(self.result["max_drift_pct"], 0.0)

    def test_urgency_score_in_range(self):
        self.assertGreaterEqual(self.result["urgency_score"], 0.0)
        self.assertLessEqual(self.result["urgency_score"], 100.0)

    def test_weighted_drift_score_in_range(self):
        self.assertGreaterEqual(self.result["weighted_drift_score"], 0.0)
        self.assertLessEqual(self.result["weighted_drift_score"], 100.0)


class TestMaxDriftComputation(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_zero_drift_when_equal(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 50, "B": 50},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 0.0)

    def test_ten_pct_drift(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 60, "B": 40},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 10.0, places=2)

    def test_drift_is_absolute(self):
        p = _make_portfolio(
            target_allocations={"A": 70, "B": 30},
            current_allocations={"A": 50, "B": 50},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 20.0, places=2)

    def test_single_asset_drift(self):
        p = _make_portfolio(
            target_allocations={"A": 100},
            current_allocations={"A": 85},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 15.0, places=2)

    def test_asset_missing_from_current_counts_as_full_target(self):
        p = _make_portfolio(
            target_allocations={"A": 60, "B": 40},
            current_allocations={"A": 100},  # B missing from current
        )
        r = self.az.analyze([p])["portfolios"][0]
        # B target=40 current=0 → drift=40; A target=60 current=100 → drift=40
        self.assertAlmostEqual(r["max_drift_pct"], 40.0, places=2)


class TestCostCalculation(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_cost_pct_calculation(self):
        p = _make_portfolio(total_value_usd=10_000, tx_cost_estimate_usd=100)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["rebalance_cost_as_pct_value"], 1.0, places=4)

    def test_zero_value_no_crash(self):
        p = _make_portfolio(total_value_usd=0, tx_cost_estimate_usd=50)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["rebalance_cost_as_pct_value"], 0.0)

    def test_zero_cost(self):
        p = _make_portfolio(total_value_usd=100_000, tx_cost_estimate_usd=0)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["rebalance_cost_as_pct_value"], 0.0)

    def test_cost_pct_half_percent(self):
        p = _make_portfolio(total_value_usd=200_000, tx_cost_estimate_usd=1_000)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["rebalance_cost_as_pct_value"], 0.5, places=4)


class TestLabelAssignment(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_just_rebalanced_label(self):
        p = _make_portfolio(last_rebalance_days_ago=1)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["label"], LABEL_JUST_REBALANCED)

    def test_immediate_label_high_drift_high_time(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 80, "B": 20},  # 30% drift
            last_rebalance_days_ago=80,
            volatility_regime="high",
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["label"], LABEL_IMMEDIATE)

    def test_hold_label_no_drift_short_time(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 50, "B": 50},
            last_rebalance_days_ago=5,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(r["label"], (LABEL_HOLD, LABEL_JUST_REBALANCED))

    def test_cost_prohibitive_suppresses_immediate(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 80, "B": 20},
            total_value_usd=1_000,
            tx_cost_estimate_usd=50,   # 5% → cost prohibitive
            last_rebalance_days_ago=80,
            volatility_regime="high",
        )
        r = self.az.analyze([p])["portfolios"][0]
        # Cost prohibitive → at most RECOMMENDED
        self.assertNotEqual(r["label"], LABEL_IMMEDIATE)

    def test_recommended_label_medium_urgency(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 65, "B": 35},  # 15% drift
            last_rebalance_days_ago=45,
            volatility_regime="normal",
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(r["label"], (LABEL_IMMEDIATE, LABEL_RECOMMENDED))

    def test_label_is_valid_string(self):
        valid_labels = {LABEL_IMMEDIATE, LABEL_RECOMMENDED, LABEL_OPTIONAL,
                        LABEL_HOLD, LABEL_JUST_REBALANCED}
        p = _make_portfolio()
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(r["label"], valid_labels)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_drift_exceeded_flag(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 62, "B": 38},
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_DRIFT_EXCEEDED, r["flags"])

    def test_no_drift_exceeded_flag_within_threshold(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 52, "B": 48},
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_DRIFT_EXCEEDED, r["flags"])

    def test_high_volatility_flag(self):
        p = _make_portfolio(volatility_regime="high")
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_HIGH_VOLATILITY, r["flags"])

    def test_no_high_volatility_flag_normal(self):
        p = _make_portfolio(volatility_regime="normal")
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_HIGH_VOLATILITY, r["flags"])

    def test_no_high_volatility_flag_low(self):
        p = _make_portfolio(volatility_regime="low")
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_HIGH_VOLATILITY, r["flags"])

    def test_tax_harvest_flag(self):
        p = _make_portfolio(tax_harvesting_opportunity=True)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_TAX_HARVEST, r["flags"])

    def test_no_tax_harvest_flag_false(self):
        p = _make_portfolio(tax_harvesting_opportunity=False)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_TAX_HARVEST, r["flags"])

    def test_cost_prohibitive_flag(self):
        p = _make_portfolio(total_value_usd=1_000, tx_cost_estimate_usd=15)  # 1.5%
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_COST_PROHIBITIVE, r["flags"])

    def test_no_cost_prohibitive_flag_cheap(self):
        p = _make_portfolio(total_value_usd=100_000, tx_cost_estimate_usd=50)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_COST_PROHIBITIVE, r["flags"])

    def test_overdue_flag(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 60, "B": 40},  # 10% drift > 5%
            last_rebalance_days_ago=95,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_OVERDUE, r["flags"])

    def test_no_overdue_flag_recent(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 60, "B": 40},
            last_rebalance_days_ago=30,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_OVERDUE, r["flags"])

    def test_no_overdue_flag_low_drift(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 52, "B": 48},  # drift < 5%
            last_rebalance_days_ago=95,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertNotIn(FLAG_OVERDUE, r["flags"])

    def test_multiple_flags_simultaneously(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 65, "B": 35},
            last_rebalance_days_ago=100,
            volatility_regime="high",
            tax_harvesting_opportunity=True,
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertIn(FLAG_DRIFT_EXCEEDED, r["flags"])
        self.assertIn(FLAG_HIGH_VOLATILITY, r["flags"])
        self.assertIn(FLAG_TAX_HARVEST, r["flags"])
        self.assertIn(FLAG_OVERDUE, r["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_most_urgent_portfolio_name(self):
        p1 = _make_portfolio(name="Urgent",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 80, "B": 20},
                              last_rebalance_days_ago=80,
                              volatility_regime="high")
        p2 = _make_portfolio(name="Stable",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 51, "B": 49},
                              last_rebalance_days_ago=5)
        r = self.az.analyze([p1, p2])["aggregates"]
        self.assertEqual(r["most_urgent_portfolio"], "Urgent")

    def test_least_urgent_portfolio_name(self):
        p1 = _make_portfolio(name="Urgent",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 80, "B": 20},
                              last_rebalance_days_ago=80,
                              volatility_regime="high")
        p2 = _make_portfolio(name="Stable",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 50, "B": 50},
                              last_rebalance_days_ago=5)
        r = self.az.analyze([p1, p2])["aggregates"]
        self.assertEqual(r["least_urgent_portfolio"], "Stable")

    def test_average_drift_single(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 60, "B": 40},
        )
        r = self.az.analyze([p])["aggregates"]
        self.assertAlmostEqual(r["average_drift"], 10.0, places=2)

    def test_average_drift_two_portfolios(self):
        p1 = _make_portfolio(target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 60, "B": 40})
        p2 = _make_portfolio(target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 70, "B": 30})
        r = self.az.analyze([p1, p2])["aggregates"]
        self.assertAlmostEqual(r["average_drift"], 15.0, places=2)

    def test_immediate_count(self):
        p1 = _make_portfolio(name="P1",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 85, "B": 15},
                              last_rebalance_days_ago=80, volatility_regime="high")
        p2 = _make_portfolio(name="P2",
                              target_allocations={"A": 50, "B": 50},
                              current_allocations={"A": 50, "B": 50},
                              last_rebalance_days_ago=5)
        r = self.az.analyze([p1, p2])["aggregates"]
        self.assertGreaterEqual(r["immediate_count"], 0)

    def test_total_portfolios_count(self):
        portfolios = [_make_portfolio(name=f"P{i}") for i in range(5)]
        r = self.az.analyze(portfolios)["aggregates"]
        self.assertEqual(r["total_portfolios"], 5)

    def test_total_portfolios_needing_rebalance_max_bound(self):
        portfolios = [_make_portfolio(name=f"P{i}") for i in range(3)]
        r = self.az.analyze(portfolios)["aggregates"]
        self.assertLessEqual(
            r["total_portfolios_needing_rebalance"],
            r["total_portfolios"]
        )

    def test_empty_most_urgent_is_none(self):
        r = self.az.analyze([])["aggregates"]
        self.assertIsNone(r["most_urgent_portfolio"])

    def test_empty_least_urgent_is_none(self):
        r = self.az.analyze([])["aggregates"]
        self.assertIsNone(r["least_urgent_portfolio"])


class TestConfigOverride(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_custom_drift_threshold_from_config(self):
        """Global config drift_threshold_pct overridden by portfolio level."""
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 57, "B": 43},
        )
        # With threshold=10 (from config), 7% drift should NOT trigger flag
        p_no_per = dict(p)
        del p_no_per["drift_threshold_pct"]
        r = self.az.analyze([p_no_per], config={"drift_threshold_pct": 10.0})["portfolios"][0]
        self.assertNotIn(FLAG_DRIFT_EXCEEDED, r["flags"])

    def test_just_rebalanced_days_config(self):
        p = _make_portfolio(last_rebalance_days_ago=3)
        r = self.az.analyze([p], config={"just_rebalanced_days": 5})["portfolios"][0]
        self.assertEqual(r["label"], LABEL_JUST_REBALANCED)

    def test_just_rebalanced_days_not_triggered(self):
        p = _make_portfolio(last_rebalance_days_ago=6)
        r = self.az.analyze([p], config={"just_rebalanced_days": 5})["portfolios"][0]
        self.assertNotEqual(r["label"], LABEL_JUST_REBALANCED)

    def test_per_portfolio_threshold_overrides_global(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 58, "B": 42},
            drift_threshold_pct=5.0,
        )
        r = self.az.analyze([p], config={"drift_threshold_pct": 20.0})["portfolios"][0]
        # Portfolio-level threshold 5 → drift 8% should trigger flag
        self.assertIn(FLAG_DRIFT_EXCEEDED, r["flags"])


class TestVolatilityRegimeEffect(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def _get_urgency(self, regime: str) -> float:
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 65, "B": 35},
            last_rebalance_days_ago=30,
            volatility_regime=regime,
        )
        return self.az.analyze([p])["portfolios"][0]["urgency_score"]

    def test_high_volatility_higher_urgency_than_normal(self):
        self.assertGreater(self._get_urgency("high"), self._get_urgency("normal"))

    def test_normal_higher_urgency_than_low(self):
        self.assertGreater(self._get_urgency("normal"), self._get_urgency("low"))

    def test_unknown_regime_treated_as_normal(self):
        p_unknown = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 65, "B": 35},
            volatility_regime="extreme",
        )
        p_normal = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 65, "B": 35},
            volatility_regime="normal",
        )
        r_unknown = self.az.analyze([p_unknown])["portfolios"][0]["urgency_score"]
        r_normal = self.az.analyze([p_normal])["portfolios"][0]["urgency_score"]
        self.assertAlmostEqual(r_unknown, r_normal, places=2)


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.az = _analyzer(data_dir=self.tmpdir)

    def test_log_file_created(self):
        result = self.az.analyze([_make_portfolio()])
        self.az.write_log(result)
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        self.assertTrue(log_path.exists())

    def test_log_is_valid_json(self):
        result = self.az.analyze([_make_portfolio()])
        self.az.write_log(result)
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_write(self):
        result = self.az.analyze([_make_portfolio()])
        self.az.write_log(result)
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(3):
            result = self.az.analyze([_make_portfolio()])
            self.az.write_log(result)
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(105):
            result = self.az.analyze([_make_portfolio()])
            self.az.write_log(result)
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_path_returned(self):
        result = self.az.analyze([_make_portfolio()])
        path = self.az.write_log(result)
        self.assertIsInstance(path, Path)

    def test_log_corrupted_file_handled(self):
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path, "w") as f:
            f.write("NOT JSON {{{{")
        result = self.az.analyze([_make_portfolio()])
        self.az.write_log(result)  # should not raise
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_non_list_file_handled(self):
        log_path = Path(self.tmpdir) / "rebalancing_trigger_log.json"
        with open(log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        result = self.az.analyze([_make_portfolio()])
        self.az.write_log(result)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_no_allocations(self):
        p = _make_portfolio(target_allocations={}, current_allocations={})
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 0.0)

    def test_single_asset_portfolio(self):
        p = _make_portfolio(
            target_allocations={"BTC": 100},
            current_allocations={"BTC": 85},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["max_drift_pct"], 15.0, places=2)

    def test_three_asset_portfolio(self):
        p = _make_portfolio(
            target_allocations={"A": 33, "B": 33, "C": 34},
            current_allocations={"A": 40, "B": 30, "C": 30},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertGreater(r["max_drift_pct"], 0.0)

    def test_large_number_of_portfolios(self):
        portfolios = [_make_portfolio(name=f"P{i}") for i in range(50)]
        result = self.az.analyze(portfolios)
        self.assertEqual(len(result["portfolios"]), 50)

    def test_zero_total_value(self):
        p = _make_portfolio(total_value_usd=0.0, tx_cost_estimate_usd=100.0)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["rebalance_cost_as_pct_value"], 0.0)

    def test_negative_tx_cost_treated_as_zero(self):
        p = _make_portfolio(tx_cost_estimate_usd=-100)
        r = self.az.analyze([p])["portfolios"][0]
        # Should not crash; cost ≤ 0 → no COST_PROHIBITIVE
        self.assertNotIn(FLAG_COST_PROHIBITIVE, r["flags"])

    def test_very_high_drift_capped_urgency_at_100(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 100, "B": 0},
            last_rebalance_days_ago=365,
            volatility_regime="high",
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertLessEqual(r["urgency_score"], 100.0)

    def test_config_none_uses_defaults(self):
        p = _make_portfolio()
        r1 = self.az.analyze([p], config=None)
        r2 = self.az.analyze([p], config={})
        self.assertEqual(r1["portfolios"][0]["label"], r2["portfolios"][0]["label"])

    def test_name_default_unknown(self):
        p = _make_portfolio()
        del p["name"]
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["name"], "unknown")

    def test_volatility_regime_passthrough(self):
        p = _make_portfolio(volatility_regime="low")
        r = self.az.analyze([p])["portfolios"][0]
        self.assertEqual(r["volatility_regime"], "low")

    def test_tax_harvest_passthrough(self):
        p = _make_portfolio(tax_harvesting_opportunity=True)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertTrue(r["tax_harvesting_opportunity"])

    def test_last_rebalance_days_passthrough(self):
        p = _make_portfolio(last_rebalance_days_ago=42.0)
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["last_rebalance_days_ago"], 42.0)


class TestWeightedDriftScore(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_perfect_match_zero_score(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 50, "B": 50},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertAlmostEqual(r["weighted_drift_score"], 0.0)

    def test_score_positive_on_drift(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 70, "B": 30},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertGreater(r["weighted_drift_score"], 0.0)

    def test_score_bounded_at_100(self):
        p = _make_portfolio(
            target_allocations={"A": 50, "B": 50},
            current_allocations={"A": 100, "B": 0},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertLessEqual(r["weighted_drift_score"], 100.0)

    def test_score_non_negative(self):
        p = _make_portfolio(
            target_allocations={"A": 30, "B": 70},
            current_allocations={"A": 70, "B": 30},
        )
        r = self.az.analyze([p])["portfolios"][0]
        self.assertGreaterEqual(r["weighted_drift_score"], 0.0)


class TestJsonSerializable(unittest.TestCase):
    def setUp(self):
        self.az = _analyzer()

    def test_output_json_serializable(self):
        p = _make_portfolio()
        result = self.az.analyze([p])
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"Output is not JSON-serializable: {e}")

    def test_multiple_portfolios_serializable(self):
        portfolios = [
            _make_portfolio(name="A", volatility_regime="high", tax_harvesting_opportunity=True),
            _make_portfolio(name="B", volatility_regime="low"),
        ]
        result = self.az.analyze(portfolios)
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"Output is not JSON-serializable: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
