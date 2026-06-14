"""
Tests for MP-1029: ProtocolDeFiPositionSizeOptimizer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_position_size_optimizer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_position_size_optimizer import (
    ProtocolDeFiPositionSizeOptimizer,
    LOG_CAP,
    VALID_FLAGS,
    VALID_LABELS,
    _LOG_FILENAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_opp(**overrides) -> dict:
    """Return a minimal valid opportunity dict with optional overrides."""
    base = {
        "name": "TestOpp",
        "protocol": "TestProtocol",
        "expected_apy_pct": 10.0,
        "apy_confidence_pct": 70.0,
        "max_loss_scenario_pct": 10.0,
        "protocol_risk_score": 30.0,
        "tvl_usd": 500_000_000,
        "our_position_impact_pct": 1.0,
        "max_single_position_pct": 25.0,
        "portfolio_total_usd": 100_000.0,
        "min_viable_size_usd": 1_000.0,
        "liquidity_exit_days": 1.0,
    }
    base.update(overrides)
    return base


def make_optimizer(tmp_dir: str) -> ProtocolDeFiPositionSizeOptimizer:
    return ProtocolDeFiPositionSizeOptimizer(data_dir=tmp_dir)


# ---------------------------------------------------------------------------
# 1. Kelly Fraction Computation
# ---------------------------------------------------------------------------

class TestComputeKelly(unittest.TestCase):

    def setUp(self):
        self.opt = ProtocolDeFiPositionSizeOptimizer()

    def test_zero_max_loss_returns_zero(self):
        self.assertEqual(self.opt._compute_kelly(10.0, 80.0, 0.0), 0.0)

    def test_negative_max_loss_returns_zero(self):
        self.assertEqual(self.opt._compute_kelly(10.0, 80.0, -5.0), 0.0)

    def test_zero_expected_apy_returns_negative(self):
        # b=0/10=0 → b<=0 → -1.0
        self.assertEqual(self.opt._compute_kelly(0.0, 80.0, 10.0), -1.0)

    def test_negative_expected_apy_returns_negative(self):
        # b<0 → -1.0
        self.assertEqual(self.opt._compute_kelly(-5.0, 80.0, 10.0), -1.0)

    def test_basic_kelly_calculation(self):
        # apy=10, confidence=80, max_loss=5
        # p=0.8, q=0.2, b=10/5=2
        # kelly = (0.8*2 - 0.2)/2 = 1.4/2 = 0.7
        k = self.opt._compute_kelly(10.0, 80.0, 5.0)
        self.assertAlmostEqual(k, 0.7, places=6)

    def test_negative_kelly_when_expected_value_negative(self):
        # apy=5, confidence=40, max_loss=20
        # p=0.4, q=0.6, b=5/20=0.25
        # kelly = (0.4*0.25 - 0.6)/0.25 = (0.1-0.6)/0.25 = -0.5/0.25 = -2.0
        k = self.opt._compute_kelly(5.0, 40.0, 20.0)
        self.assertAlmostEqual(k, -2.0, places=6)

    def test_kelly_equals_zero_at_break_even(self):
        # p*b = q → p*apy/loss = (1-p)
        # apy=5, max_loss=5, confidence=50 → b=1
        # kelly = (0.5*1 - 0.5)/1 = 0.0
        k = self.opt._compute_kelly(5.0, 50.0, 5.0)
        self.assertAlmostEqual(k, 0.0, places=6)

    def test_high_confidence_gives_high_kelly(self):
        # p=0.95, q=0.05, b=15/10=1.5
        # kelly = (0.95*1.5 - 0.05)/1.5 = (1.425-0.05)/1.5 = 1.375/1.5 ≈ 0.9167
        k = self.opt._compute_kelly(15.0, 95.0, 10.0)
        self.assertAlmostEqual(k, 1.375 / 1.5, places=6)

    def test_low_apy_to_loss_ratio(self):
        # apy=2, max_loss=10, confidence=70 → b=0.2
        # kelly = (0.7*0.2 - 0.3)/0.2 = (0.14-0.3)/0.2 = -0.16/0.2 = -0.8
        k = self.opt._compute_kelly(2.0, 70.0, 10.0)
        self.assertAlmostEqual(k, -0.8, places=6)

    def test_kelly_pct_for_minimal_position(self):
        # apy=10, confidence=50.5, max_loss=10 → b=1
        # kelly = (0.505 - 0.495) = 0.01 → kelly_pct = 1% < 2 → MINIMAL
        k = self.opt._compute_kelly(10.0, 50.5, 10.0)
        self.assertAlmostEqual(k, 0.01, places=6)


# ---------------------------------------------------------------------------
# 2. Impact Adjustment
# ---------------------------------------------------------------------------

class TestApplyImpactAdjustment(unittest.TestCase):

    def setUp(self):
        self.opt = ProtocolDeFiPositionSizeOptimizer()

    def test_no_adjustment_when_impact_below_5(self):
        self.assertEqual(self.opt._apply_impact_adjustment(30.0, 3.0), 30.0)

    def test_no_adjustment_when_impact_exactly_5(self):
        self.assertEqual(self.opt._apply_impact_adjustment(30.0, 5.0), 30.0)

    def test_halves_position_when_impact_is_10(self):
        # 30 * (5/10) = 15
        self.assertAlmostEqual(self.opt._apply_impact_adjustment(30.0, 10.0), 15.0, places=6)

    def test_reduces_when_impact_is_25(self):
        # 40 * (5/25) = 8
        self.assertAlmostEqual(self.opt._apply_impact_adjustment(40.0, 25.0), 8.0, places=6)

    def test_zero_impact_no_change(self):
        self.assertEqual(self.opt._apply_impact_adjustment(20.0, 0.0), 20.0)

    def test_large_impact_drastically_reduces(self):
        # 100 * (5/100) = 5
        self.assertAlmostEqual(self.opt._apply_impact_adjustment(100.0, 100.0), 5.0, places=6)


# ---------------------------------------------------------------------------
# 3. Label Determination
# ---------------------------------------------------------------------------

class TestDetermineLabel(unittest.TestCase):

    def setUp(self):
        self.opt = ProtocolDeFiPositionSizeOptimizer()

    def test_negative_kelly_is_dne(self):
        self.assertEqual(self.opt._determine_label(-0.5, 80.0, 10.0), "DO_NOT_ENTER")

    def test_low_confidence_is_dne(self):
        self.assertEqual(self.opt._determine_label(0.5, 19.9, 10.0), "DO_NOT_ENTER")

    def test_exactly_20_confidence_not_dne(self):
        # confidence=20 is NOT < 20
        label = self.opt._determine_label(0.5, 20.0, 10.0)
        self.assertNotEqual(label, "DO_NOT_ENTER")

    def test_high_max_loss_is_dne(self):
        self.assertEqual(self.opt._determine_label(0.5, 80.0, 55.0), "DO_NOT_ENTER")

    def test_exactly_50_max_loss_not_dne(self):
        # max_loss=50 is NOT > 50
        label = self.opt._determine_label(0.5, 80.0, 50.0)
        self.assertNotEqual(label, "DO_NOT_ENTER")

    def test_full_kelly_requires_confidence_above_80(self):
        # kelly_pct=50 > 10, confidence=80 NOT > 80 → HALF_KELLY
        self.assertEqual(self.opt._determine_label(0.5, 80.0, 10.0), "HALF_KELLY")

    def test_full_kelly_with_high_confidence(self):
        # kelly_pct=50 > 10, confidence=85 > 80 → FULL_KELLY
        self.assertEqual(self.opt._determine_label(0.5, 85.0, 10.0), "FULL_KELLY")

    def test_kelly_exactly_10pct_not_full(self):
        # kelly=0.1 → kelly_pct=10, NOT > 10 → HALF_KELLY if >=5
        self.assertEqual(self.opt._determine_label(0.1, 90.0, 10.0), "HALF_KELLY")

    def test_half_kelly_range(self):
        # kelly=0.07 → kelly_pct=7 >=5, not FULL → HALF_KELLY
        self.assertEqual(self.opt._determine_label(0.07, 70.0, 10.0), "HALF_KELLY")

    def test_quarter_kelly_range(self):
        # kelly=0.04 → kelly_pct=4 >=2 → QUARTER_KELLY
        self.assertEqual(self.opt._determine_label(0.04, 70.0, 10.0), "QUARTER_KELLY")

    def test_minimal_position(self):
        # kelly=0.01 → kelly_pct=1 < 2 → MINIMAL_POSITION
        self.assertEqual(self.opt._determine_label(0.01, 70.0, 10.0), "MINIMAL_POSITION")

    def test_zero_kelly_is_minimal(self):
        self.assertEqual(self.opt._determine_label(0.0, 70.0, 10.0), "MINIMAL_POSITION")


# ---------------------------------------------------------------------------
# 4. Position Score
# ---------------------------------------------------------------------------

class TestComputePositionScore(unittest.TestCase):

    def setUp(self):
        self.opt = ProtocolDeFiPositionSizeOptimizer()

    def test_dne_gives_zero_score(self):
        self.assertEqual(self.opt._compute_position_score("DO_NOT_ENTER", 50.0, 80.0, 1.0), 0.0)

    def test_basic_score_calculation(self):
        # apy=10, confidence=80, exit_days=1
        # ev=10*0.8=8, lf=min(1,7/1)=1, score=min(100,8*2*1)=16
        s = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 1.0)
        self.assertAlmostEqual(s, 16.0, places=4)

    def test_illiquid_reduces_score(self):
        # apy=10, confidence=80, exit_days=14
        # lf=min(1,7/14)=0.5, score=min(100,8*2*0.5)=8
        s = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 14.0)
        self.assertAlmostEqual(s, 8.0, places=4)

    def test_score_capped_at_100(self):
        # apy=60, confidence=90 → ev=54 → score=min(100,108)=100
        s = self.opt._compute_position_score("FULL_KELLY", 60.0, 90.0, 1.0)
        self.assertAlmostEqual(s, 100.0, places=4)

    def test_score_non_negative(self):
        s = self.opt._compute_position_score("MINIMAL_POSITION", 0.1, 21.0, 1.0)
        self.assertGreaterEqual(s, 0.0)

    def test_liquidity_factor_capped_at_1(self):
        # exit_days=0.5 → min(1,7/0.5)=min(1,14)=1
        s1 = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 0.5)
        s2 = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 1.0)
        # Both should give same score since lf is capped
        self.assertAlmostEqual(s1, s2, places=4)

    def test_7_day_exit_gives_full_liquidity_factor(self):
        # exit_days=7 → min(1,7/7)=1.0
        s_7 = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 7.0)
        s_1 = self.opt._compute_position_score("HALF_KELLY", 10.0, 80.0, 1.0)
        self.assertAlmostEqual(s_7, s_1, places=4)

    def test_full_kelly_label_also_scores(self):
        s = self.opt._compute_position_score("FULL_KELLY", 20.0, 90.0, 2.0)
        self.assertGreater(s, 0.0)


# ---------------------------------------------------------------------------
# 5. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = make_optimizer(self.tmp)

    def _flags(self, **overrides) -> list:
        opp = make_opp(**overrides)
        result = self.opt._analyze_opportunity(opp)
        return result["flags"]

    def test_high_confidence_flag(self):
        self.assertIn("HIGH_CONFIDENCE_OPPORTUNITY", self._flags(apy_confidence_pct=85.0))

    def test_no_high_confidence_at_80(self):
        # 80 is NOT > 80
        self.assertNotIn("HIGH_CONFIDENCE_OPPORTUNITY", self._flags(apy_confidence_pct=80.0))

    def test_no_high_confidence_below_80(self):
        self.assertNotIn("HIGH_CONFIDENCE_OPPORTUNITY", self._flags(apy_confidence_pct=75.0))

    def test_kelly_positive_flag(self):
        # kelly=0.7 (positive) → KELLY_POSITIVE
        self.assertIn("KELLY_POSITIVE", self._flags(
            expected_apy_pct=10.0, apy_confidence_pct=80.0, max_loss_scenario_pct=5.0
        ))

    def test_no_kelly_positive_when_negative(self):
        # Low confidence, low apy → negative kelly
        self.assertNotIn("KELLY_POSITIVE", self._flags(
            expected_apy_pct=1.0, apy_confidence_pct=30.0, max_loss_scenario_pct=50.0
        ))

    def test_large_pool_impact_flag(self):
        self.assertIn("LARGE_POOL_IMPACT", self._flags(our_position_impact_pct=5.0))

    def test_no_large_pool_impact_at_3(self):
        # 3.0 is NOT > 3.0
        self.assertNotIn("LARGE_POOL_IMPACT", self._flags(our_position_impact_pct=3.0))

    def test_illiquid_exit_flag(self):
        self.assertIn("ILLIQUID_EXIT", self._flags(liquidity_exit_days=8.0))

    def test_no_illiquid_exit_at_7(self):
        self.assertNotIn("ILLIQUID_EXIT", self._flags(liquidity_exit_days=7.0))

    def test_concentrated_risk_flag(self):
        # Need optimal_pct > 20: use high kelly + high max_single
        self.assertIn("CONCENTRATED_RISK", self._flags(
            expected_apy_pct=20.0,
            apy_confidence_pct=90.0,
            max_loss_scenario_pct=5.0,
            max_single_position_pct=50.0,
            our_position_impact_pct=0.0,
        ))

    def test_diversification_required_flag(self):
        # half_kelly_pct > max_single → DIVERSIFICATION_REQUIRED
        # High kelly: apy=20, confidence=90, max_loss=5 → b=4
        # kelly=(0.9*4-0.1)/4=(3.6-0.1)/4=0.875 → half_kelly=43.75%
        # max_single=20 → 43.75 > 20 → DIVERSIFICATION_REQUIRED
        self.assertIn("DIVERSIFICATION_REQUIRED", self._flags(
            expected_apy_pct=20.0,
            apy_confidence_pct=90.0,
            max_loss_scenario_pct=5.0,
            max_single_position_pct=20.0,
            our_position_impact_pct=0.0,
        ))

    def test_all_flags_in_valid_set(self):
        flags = self._flags(
            apy_confidence_pct=90.0,
            expected_apy_pct=10.0,
            max_loss_scenario_pct=5.0,
            our_position_impact_pct=5.0,
            liquidity_exit_days=10.0,
            max_single_position_pct=5.0,
        )
        for f in flags:
            self.assertIn(f, VALID_FLAGS)


# ---------------------------------------------------------------------------
# 6. Analyze Opportunity (integration)
# ---------------------------------------------------------------------------

class TestAnalyzeOpportunity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = make_optimizer(self.tmp)

    def test_output_has_required_keys(self):
        result = self.opt._analyze_opportunity(make_opp())
        expected_keys = {
            "name", "protocol", "expected_apy_pct", "kelly_fraction",
            "half_kelly_pct", "position_impact_adjusted_pct",
            "optimal_position_pct", "optimal_position_usd",
            "position_score", "label", "flags",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_name_preserved(self):
        result = self.opt._analyze_opportunity(make_opp(name="AaveUSDC"))
        self.assertEqual(result["name"], "AaveUSDC")

    def test_protocol_preserved(self):
        result = self.opt._analyze_opportunity(make_opp(protocol="Aave V3"))
        self.assertEqual(result["protocol"], "Aave V3")

    def test_expected_apy_preserved(self):
        result = self.opt._analyze_opportunity(make_opp(expected_apy_pct=12.5))
        self.assertEqual(result["expected_apy_pct"], 12.5)

    def test_label_is_valid(self):
        result = self.opt._analyze_opportunity(make_opp())
        self.assertIn(result["label"], VALID_LABELS)

    def test_optimal_usd_matches_pct(self):
        result = self.opt._analyze_opportunity(make_opp(
            portfolio_total_usd=100_000.0,
        ))
        expected_usd = result["optimal_position_pct"] / 100.0 * 100_000.0
        self.assertAlmostEqual(result["optimal_position_usd"], round(expected_usd, 2), places=2)

    def test_dne_gives_zero_optimal(self):
        result = self.opt._analyze_opportunity(make_opp(
            apy_confidence_pct=10.0,  # < 20 → DO_NOT_ENTER
        ))
        self.assertEqual(result["label"], "DO_NOT_ENTER")
        self.assertEqual(result["optimal_position_pct"], 0.0)
        self.assertEqual(result["optimal_position_usd"], 0.0)

    def test_optimal_pct_capped_by_max_single(self):
        # Very high kelly → optimal should not exceed max_single
        result = self.opt._analyze_opportunity(make_opp(
            expected_apy_pct=50.0,
            apy_confidence_pct=90.0,
            max_loss_scenario_pct=5.0,
            max_single_position_pct=10.0,
            our_position_impact_pct=0.0,
        ))
        self.assertLessEqual(result["optimal_position_pct"], 10.0)

    def test_default_name_when_missing(self):
        result = self.opt._analyze_opportunity({})
        self.assertEqual(result["name"], "unknown")

    def test_scores_non_negative(self):
        result = self.opt._analyze_opportunity(make_opp())
        self.assertGreaterEqual(result["half_kelly_pct"], 0.0)
        self.assertGreaterEqual(result["optimal_position_pct"], 0.0)
        self.assertGreaterEqual(result["position_score"], 0.0)

    def test_optimal_pct_zero_when_dne_despite_high_kelly(self):
        # max_loss > 50 → DO_NOT_ENTER
        result = self.opt._analyze_opportunity(make_opp(
            expected_apy_pct=30.0,
            apy_confidence_pct=90.0,
            max_loss_scenario_pct=60.0,
        ))
        self.assertEqual(result["optimal_position_pct"], 0.0)


# ---------------------------------------------------------------------------
# 7. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.opt = ProtocolDeFiPositionSizeOptimizer()

    def test_empty_returns_defaults(self):
        agg = self.opt._compute_aggregates([])
        self.assertIsNone(agg["best_opportunity"])
        self.assertEqual(agg["avoid_list"], [])
        self.assertEqual(agg["total_optimal_allocation_pct"], 0.0)
        self.assertEqual(agg["do_not_enter_count"], 0)
        self.assertEqual(agg["full_kelly_count"], 0)

    def test_avoid_list_contains_dne_names(self):
        dne_result = {
            "name": "Risky", "label": "DO_NOT_ENTER",
            "optimal_position_pct": 0.0, "position_score": 0.0,
        }
        good_result = {
            "name": "Good", "label": "HALF_KELLY",
            "optimal_position_pct": 10.0, "position_score": 40.0,
        }
        agg = self.opt._compute_aggregates([dne_result, good_result])
        self.assertIn("Risky", agg["avoid_list"])
        self.assertNotIn("Good", agg["avoid_list"])

    def test_best_opportunity_is_highest_score(self):
        r1 = {"name": "A", "label": "HALF_KELLY",
               "optimal_position_pct": 5.0, "position_score": 30.0}
        r2 = {"name": "B", "label": "FULL_KELLY",
               "optimal_position_pct": 15.0, "position_score": 80.0}
        agg = self.opt._compute_aggregates([r1, r2])
        self.assertEqual(agg["best_opportunity"], "B")

    def test_best_opportunity_ignores_dne(self):
        dne = {"name": "X", "label": "DO_NOT_ENTER",
               "optimal_position_pct": 0.0, "position_score": 0.0}
        good = {"name": "Y", "label": "MINIMAL_POSITION",
                "optimal_position_pct": 1.0, "position_score": 5.0}
        agg = self.opt._compute_aggregates([dne, good])
        self.assertEqual(agg["best_opportunity"], "Y")

    def test_best_opportunity_is_none_when_all_dne(self):
        dne1 = {"name": "X", "label": "DO_NOT_ENTER",
                "optimal_position_pct": 0.0, "position_score": 0.0}
        agg = self.opt._compute_aggregates([dne1])
        self.assertIsNone(agg["best_opportunity"])

    def test_total_allocation_pct_sums(self):
        r1 = {"name": "A", "label": "HALF_KELLY",
               "optimal_position_pct": 10.0, "position_score": 20.0}
        r2 = {"name": "B", "label": "QUARTER_KELLY",
               "optimal_position_pct": 5.0, "position_score": 10.0}
        agg = self.opt._compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["total_optimal_allocation_pct"], 15.0, places=4)

    def test_full_kelly_count(self):
        r1 = {"name": "A", "label": "FULL_KELLY",
               "optimal_position_pct": 15.0, "position_score": 80.0}
        r2 = {"name": "B", "label": "FULL_KELLY",
               "optimal_position_pct": 12.0, "position_score": 75.0}
        r3 = {"name": "C", "label": "HALF_KELLY",
               "optimal_position_pct": 8.0, "position_score": 40.0}
        agg = self.opt._compute_aggregates([r1, r2, r3])
        self.assertEqual(agg["full_kelly_count"], 2)

    def test_do_not_enter_count(self):
        results = [
            {"name": "A", "label": "DO_NOT_ENTER", "optimal_position_pct": 0.0, "position_score": 0.0},
            {"name": "B", "label": "DO_NOT_ENTER", "optimal_position_pct": 0.0, "position_score": 0.0},
            {"name": "C", "label": "MINIMAL_POSITION", "optimal_position_pct": 1.0, "position_score": 2.0},
        ]
        agg = self.opt._compute_aggregates(results)
        self.assertEqual(agg["do_not_enter_count"], 2)


# ---------------------------------------------------------------------------
# 8. Ring-Buffer Log
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = make_optimizer(self.tmp)

    def _log_path(self):
        return os.path.join(self.tmp, _LOG_FILENAME)

    def test_log_created(self):
        self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_is_list(self):
        self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_opportunity_count(self):
        self.opt.optimize(
            [make_opp(), make_opp(name="B")],
            config={"log_enabled": True, "data_dir": self.tmp}
        )
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["opportunity_count"], 2)

    def test_log_grows_with_calls(self):
        for _ in range(4):
            self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 4)

    def test_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 10):
            self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_CAP)

    def test_no_log_when_disabled(self):
        self.opt.optimize([make_opp()], config={"log_enabled": False, "data_dir": self.tmp})
        self.assertFalse(os.path.exists(self._log_path()))

    def test_log_recovers_from_corrupt(self):
        with open(self._log_path(), "w") as fh:
            fh.write("{{{INVALID")
        self.opt.optimize([make_opp()], config={"log_enabled": True, "data_dir": self.tmp})
        with open(self._log_path()) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 9. Optimize Output (top-level)
# ---------------------------------------------------------------------------

class TestOptimizeOutput(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = make_optimizer(self.tmp)

    def _run(self, opps=None):
        if opps is None:
            opps = [make_opp()]
        return self.opt.optimize(opps, config={"log_enabled": False})

    def test_required_keys_present(self):
        result = self._run()
        for key in ("timestamp", "module", "mp", "opportunity_count",
                    "opportunities", "aggregates"):
            self.assertIn(key, result)

    def test_module_name(self):
        result = self._run()
        self.assertEqual(result["module"], "ProtocolDeFiPositionSizeOptimizer")

    def test_mp_tag(self):
        result = self._run()
        self.assertEqual(result["mp"], "MP-1029")

    def test_opportunity_count_matches(self):
        result = self._run([make_opp(), make_opp(name="B")])
        self.assertEqual(result["opportunity_count"], 2)

    def test_empty_list(self):
        result = self._run([])
        self.assertEqual(result["opportunity_count"], 0)
        self.assertEqual(result["opportunities"], [])

    def test_timestamp_is_string(self):
        result = self._run()
        self.assertIsInstance(result["timestamp"], str)

    def test_opportunities_list_length(self):
        result = self._run([make_opp(name=f"O{i}") for i in range(5)])
        self.assertEqual(len(result["opportunities"]), 5)

    def test_raises_on_non_list(self):
        with self.assertRaises(TypeError):
            self.opt.optimize("bad", config={})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.opt.optimize([], config="bad")

    def test_aggregates_is_dict(self):
        result = self._run()
        self.assertIsInstance(result["aggregates"], dict)


# ---------------------------------------------------------------------------
# 10. Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = make_optimizer(self.tmp)

    def test_very_high_apy_with_high_confidence(self):
        result = self.opt._analyze_opportunity(make_opp(
            expected_apy_pct=500.0, apy_confidence_pct=95.0, max_loss_scenario_pct=10.0,
        ))
        self.assertIn(result["label"], VALID_LABELS)

    def test_zero_portfolio_total(self):
        result = self.opt._analyze_opportunity(make_opp(portfolio_total_usd=0.0))
        self.assertEqual(result["optimal_position_usd"], 0.0)

    def test_confidence_clamped_above_100(self):
        result = self.opt._analyze_opportunity(make_opp(apy_confidence_pct=120.0))
        self.assertIn(result["label"], VALID_LABELS)

    def test_confidence_clamped_below_zero(self):
        result = self.opt._analyze_opportunity(make_opp(apy_confidence_pct=-10.0))
        self.assertEqual(result["label"], "DO_NOT_ENTER")

    def test_large_opportunity_list(self):
        opps = [make_opp(name=f"Opp{i}") for i in range(50)]
        result = self.opt.optimize(opps, config={"log_enabled": False})
        self.assertEqual(result["opportunity_count"], 50)

    def test_data_dir_override_in_config(self):
        alt = tempfile.mkdtemp()
        self.opt.optimize(
            [make_opp()],
            config={"log_enabled": True, "data_dir": alt},
        )
        self.assertTrue(os.path.exists(os.path.join(alt, _LOG_FILENAME)))

    def test_optimal_always_non_negative(self):
        result = self.opt._analyze_opportunity(make_opp(
            expected_apy_pct=1.0,
            apy_confidence_pct=21.0,
            max_loss_scenario_pct=10.0,
        ))
        self.assertGreaterEqual(result["optimal_position_pct"], 0.0)

    def test_half_kelly_pct_is_half_of_kelly(self):
        result = self.opt._analyze_opportunity(make_opp(
            expected_apy_pct=10.0,
            apy_confidence_pct=80.0,
            max_loss_scenario_pct=5.0,
        ))
        # kelly = 0.7 (computed above), half_kelly = 35%
        expected_half = max(0.0, result["kelly_fraction"] / 2.0 * 100.0)
        self.assertAlmostEqual(result["half_kelly_pct"], round(expected_half, 4), places=4)


if __name__ == "__main__":
    unittest.main()
