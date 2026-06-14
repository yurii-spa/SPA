"""
Tests for MP-986: DeFiLiquidityConcentrationRiskScorer
Run with: python3 -m unittest spa_core.tests.test_defi_liquidity_concentration_risk_scorer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_liquidity_concentration_risk_scorer import (
    DeFiLiquidityConcentrationRiskScorer,
    _compute_hhi,
    _score_pool,
    LABEL_WELL_DISTRIBUTED,
    LABEL_LOW_CONCENTRATION,
    LABEL_MODERATE_RISK,
    LABEL_HIGH_CONCENTRATION,
    LABEL_SINGLE_LP_RISK,
    FLAG_SINGLE_LP_DOMINANT,
    FLAG_INCENTIVE_DEPENDENT,
    FLAG_PROTOCOL_OWNED_MAJORITY,
    FLAG_STICKY_MAJORITY,
    FLAG_CL_RANGE_RISK,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(
    protocol="Uniswap",
    pair="ETH/USDC",
    total_tvl_usd=10_000_000,
    lp_positions=None,
    is_cl=False,
    active_range_pct=100.0,
    incentive_dependent_pct=0.0,
    sticky_lp_pct=50.0,
    geographic_concentration="diverse",
    pol_pct=0.0,
):
    if lp_positions is None:
        lp_positions = [
            {"address_alias": "LP1", "tvl_usd": 1_000_000, "days_providing": 200},
            {"address_alias": "LP2", "tvl_usd": 900_000,  "days_providing": 100},
            {"address_alias": "LP3", "tvl_usd": 800_000,  "days_providing": 50},
        ]
    return {
        "protocol": protocol,
        "pair": pair,
        "total_tvl_usd": total_tvl_usd,
        "top_lp_positions": lp_positions,
        "is_concentrated_liquidity": is_cl,
        "active_range_pct": active_range_pct,
        "incentive_dependent_pct": incentive_dependent_pct,
        "sticky_lp_pct": sticky_lp_pct,
        "geographic_concentration": geographic_concentration,
        "protocol_owned_liquidity_pct": pol_pct,
    }


def _make_scorer(tmp_dir):
    log_path = os.path.join(tmp_dir, "liquidity_concentration_log.json")
    return DeFiLiquidityConcentrationRiskScorer(log_path=log_path), log_path


# ---------------------------------------------------------------------------
# 1. HHI utility
# ---------------------------------------------------------------------------

class TestComputeHHI(unittest.TestCase):

    def test_monopoly(self):
        hhi = _compute_hhi([1.0])
        self.assertAlmostEqual(hhi, 10000.0, places=1)

    def test_equal_two(self):
        hhi = _compute_hhi([0.5, 0.5])
        self.assertAlmostEqual(hhi, 5000.0, places=1)

    def test_equal_four(self):
        hhi = _compute_hhi([0.25, 0.25, 0.25, 0.25])
        self.assertAlmostEqual(hhi, 2500.0, places=1)

    def test_equal_ten(self):
        hhi = _compute_hhi([0.1] * 10)
        self.assertAlmostEqual(hhi, 1000.0, places=1)

    def test_empty(self):
        self.assertEqual(_compute_hhi([]), 0.0)

    def test_small_share(self):
        hhi = _compute_hhi([0.01])
        self.assertAlmostEqual(hhi, 1.0, places=2)


# ---------------------------------------------------------------------------
# 2. _score_pool
# ---------------------------------------------------------------------------

class TestScorePool(unittest.TestCase):

    def test_returns_required_keys(self):
        pool = _make_pool()
        r = _score_pool(pool)
        for key in ("protocol", "pair", "total_tvl_usd", "top3_concentration_pct",
                    "lp_hhi", "withdrawal_scenario_10pct_impact",
                    "sticky_ratio_pct", "concentration_risk_score",
                    "risk_label", "flags"):
            self.assertIn(key, r)

    def test_protocol_and_pair_preserved(self):
        pool = _make_pool(protocol="Curve", pair="USDC/USDT")
        r = _score_pool(pool)
        self.assertEqual(r["protocol"], "Curve")
        self.assertEqual(r["pair"], "USDC/USDT")

    def test_single_lp_risk_label(self):
        """When top LP > 60% of TVL → SINGLE_LP_RISK."""
        pool = _make_pool(lp_positions=[
            {"address_alias": "Whale", "tvl_usd": 7_000_000, "days_providing": 10},
            {"address_alias": "LP2",   "tvl_usd": 1_000_000, "days_providing": 50},
            {"address_alias": "LP3",   "tvl_usd": 2_000_000, "days_providing": 30},
        ])
        r = _score_pool(pool)
        self.assertEqual(r["risk_label"], LABEL_SINGLE_LP_RISK)

    def test_single_lp_dominant_flag(self):
        """top1 > 50% → SINGLE_LP_DOMINANT flag."""
        pool = _make_pool(lp_positions=[
            {"address_alias": "BigLP", "tvl_usd": 6_000_000, "days_providing": 10},
            {"address_alias": "LP2",   "tvl_usd": 4_000_000, "days_providing": 50},
        ])
        r = _score_pool(pool)
        self.assertIn(FLAG_SINGLE_LP_DOMINANT, r["flags"])

    def test_incentive_dependent_flag(self):
        pool = _make_pool(incentive_dependent_pct=60.0)
        r = _score_pool(pool)
        self.assertIn(FLAG_INCENTIVE_DEPENDENT, r["flags"])

    def test_no_incentive_dependent_flag_below_threshold(self):
        pool = _make_pool(incentive_dependent_pct=40.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_INCENTIVE_DEPENDENT, r["flags"])

    def test_protocol_owned_majority_flag(self):
        pool = _make_pool(pol_pct=45.0)
        r = _score_pool(pool)
        self.assertIn(FLAG_PROTOCOL_OWNED_MAJORITY, r["flags"])

    def test_no_pol_flag_below_threshold(self):
        pool = _make_pool(pol_pct=30.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_PROTOCOL_OWNED_MAJORITY, r["flags"])

    def test_sticky_majority_flag(self):
        pool = _make_pool(sticky_lp_pct=70.0)
        r = _score_pool(pool)
        self.assertIn(FLAG_STICKY_MAJORITY, r["flags"])

    def test_no_sticky_flag_below_threshold(self):
        pool = _make_pool(sticky_lp_pct=55.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_STICKY_MAJORITY, r["flags"])

    def test_cl_range_risk_flag_triggered(self):
        pool = _make_pool(is_cl=True, active_range_pct=30.0)
        r = _score_pool(pool)
        self.assertIn(FLAG_CL_RANGE_RISK, r["flags"])

    def test_cl_range_risk_flag_not_triggered_above_50(self):
        pool = _make_pool(is_cl=True, active_range_pct=60.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_CL_RANGE_RISK, r["flags"])

    def test_cl_range_risk_flag_not_triggered_non_cl(self):
        pool = _make_pool(is_cl=False, active_range_pct=20.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_CL_RANGE_RISK, r["flags"])

    def test_top3_concentration_pct_range(self):
        pool = _make_pool()
        r = _score_pool(pool)
        self.assertGreaterEqual(r["top3_concentration_pct"], 0.0)
        self.assertLessEqual(r["top3_concentration_pct"], 100.0)

    def test_lp_hhi_range(self):
        pool = _make_pool()
        r = _score_pool(pool)
        self.assertGreaterEqual(r["lp_hhi"], 0.0)
        self.assertLessEqual(r["lp_hhi"], 10000.0)

    def test_risk_score_range(self):
        pool = _make_pool()
        r = _score_pool(pool)
        self.assertGreaterEqual(r["concentration_risk_score"], 0.0)
        self.assertLessEqual(r["concentration_risk_score"], 100.0)

    def test_empty_lp_positions(self):
        pool = _make_pool(lp_positions=[])
        r = _score_pool(pool)
        self.assertEqual(r["top3_concentration_pct"], 0.0)
        self.assertIsInstance(r["risk_label"], str)

    def test_single_lp_position(self):
        pool = _make_pool(lp_positions=[
            {"address_alias": "OnlyLP", "tvl_usd": 5_000_000, "days_providing": 300}
        ])
        r = _score_pool(pool)
        # single LP owns 100% → SINGLE_LP_RISK
        self.assertEqual(r["risk_label"], LABEL_SINGLE_LP_RISK)
        self.assertIn(FLAG_SINGLE_LP_DOMINANT, r["flags"])

    def test_well_distributed_label(self):
        """Many small LPs → low concentration score → WELL_DISTRIBUTED."""
        lp_positions = [
            {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
            for i in range(30)
        ]
        pool = _make_pool(
            total_tvl_usd=3_000_000,
            lp_positions=lp_positions,
            incentive_dependent_pct=0.0,
            geographic_concentration="diverse",
        )
        r = _score_pool(pool)
        self.assertIn(r["risk_label"], (LABEL_WELL_DISTRIBUTED, LABEL_LOW_CONCENTRATION))

    def test_geographic_single_entity_raises_score(self):
        pool_diverse = _make_pool(geographic_concentration="diverse")
        pool_single  = _make_pool(geographic_concentration="single_entity")
        r_diverse = _score_pool(pool_diverse)
        r_single  = _score_pool(pool_single)
        self.assertGreater(r_single["concentration_risk_score"],
                           r_diverse["concentration_risk_score"])

    def test_withdrawal_scenario_equals_top1_share(self):
        pool = _make_pool(lp_positions=[
            {"address_alias": "Big", "tvl_usd": 4_000_000, "days_providing": 10},
            {"address_alias": "Med", "tvl_usd": 2_000_000, "days_providing": 50},
            {"address_alias": "Sml", "tvl_usd": 1_000_000, "days_providing": 30},
        ])
        r = _score_pool(pool)
        expected = 4_000_000 / 7_000_000 * 100.0
        self.assertAlmostEqual(r["withdrawal_scenario_10pct_impact"], expected, places=1)

    def test_sticky_ratio_pct_preserved(self):
        pool = _make_pool(sticky_lp_pct=72.5)
        r = _score_pool(pool)
        self.assertAlmostEqual(r["sticky_ratio_pct"], 72.5, places=1)

    def test_zero_tvl_pool(self):
        pool = _make_pool(total_tvl_usd=0.0, lp_positions=[])
        r = _score_pool(pool)
        self.assertEqual(r["total_tvl_usd"], 0.0)
        self.assertIsInstance(r["risk_label"], str)

    def test_multiple_flags_possible(self):
        pool = _make_pool(
            lp_positions=[
                {"address_alias": "BigWhale", "tvl_usd": 6_000_000, "days_providing": 10}
            ],
            incentive_dependent_pct=70.0,
            pol_pct=50.0,
            sticky_lp_pct=65.0,
            is_cl=True,
            active_range_pct=40.0,
        )
        r = _score_pool(pool)
        self.assertIn(FLAG_SINGLE_LP_DOMINANT, r["flags"])
        self.assertIn(FLAG_INCENTIVE_DEPENDENT, r["flags"])
        self.assertIn(FLAG_PROTOCOL_OWNED_MAJORITY, r["flags"])
        self.assertIn(FLAG_STICKY_MAJORITY, r["flags"])
        self.assertIn(FLAG_CL_RANGE_RISK, r["flags"])

    def test_no_flags_clean_pool(self):
        pool = _make_pool(
            lp_positions=[
                {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
                for i in range(20)
            ],
            incentive_dependent_pct=10.0,
            pol_pct=5.0,
            sticky_lp_pct=30.0,
            is_cl=False,
        )
        r = _score_pool(pool)
        self.assertEqual(r["flags"], [])

    def test_incentive_dependent_boundary_exactly_50(self):
        pool = _make_pool(incentive_dependent_pct=50.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_INCENTIVE_DEPENDENT, r["flags"])

    def test_incentive_dependent_boundary_above_50(self):
        pool = _make_pool(incentive_dependent_pct=50.01)
        r = _score_pool(pool)
        self.assertIn(FLAG_INCENTIVE_DEPENDENT, r["flags"])

    def test_pol_boundary_exactly_40(self):
        pool = _make_pool(pol_pct=40.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_PROTOCOL_OWNED_MAJORITY, r["flags"])

    def test_pol_boundary_above_40(self):
        pool = _make_pool(pol_pct=40.01)
        r = _score_pool(pool)
        self.assertIn(FLAG_PROTOCOL_OWNED_MAJORITY, r["flags"])

    def test_active_range_exactly_50_cl(self):
        pool = _make_pool(is_cl=True, active_range_pct=50.0)
        r = _score_pool(pool)
        self.assertNotIn(FLAG_CL_RANGE_RISK, r["flags"])

    def test_active_range_below_50_cl(self):
        pool = _make_pool(is_cl=True, active_range_pct=49.9)
        r = _score_pool(pool)
        self.assertIn(FLAG_CL_RANGE_RISK, r["flags"])


# ---------------------------------------------------------------------------
# 3. DeFiLiquidityConcentrationRiskScorer.score()
# ---------------------------------------------------------------------------

class TestScorerBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log_path = _make_scorer(self.tmp)

    def test_empty_pools_returns_valid_structure(self):
        result = self.scorer.score([])
        self.assertIn("pools", result)
        self.assertIn("aggregates", result)
        self.assertIn("timestamp", result)
        self.assertEqual(result["pools"], [])

    def test_empty_pools_aggregates(self):
        result = self.scorer.score([])
        agg = result["aggregates"]
        self.assertIsNone(agg["most_concentrated"])
        self.assertIsNone(agg["least_concentrated"])
        self.assertEqual(agg["average_concentration_score"], 0.0)
        self.assertEqual(agg["high_concentration_count"], 0)
        self.assertEqual(agg["total_tvl_analyzed_usd"], 0.0)
        self.assertEqual(agg["total_pools"], 0)

    def test_single_pool_result(self):
        pools = [_make_pool()]
        result = self.scorer.score(pools)
        self.assertEqual(len(result["pools"]), 1)
        agg = result["aggregates"]
        self.assertEqual(agg["total_pools"], 1)
        self.assertIsNotNone(agg["most_concentrated"])
        self.assertIsNotNone(agg["least_concentrated"])

    def test_multiple_pools_all_scored(self):
        pools = [
            _make_pool(protocol="Uniswap", pair="ETH/USDC"),
            _make_pool(protocol="Curve",   pair="3pool"),
            _make_pool(protocol="Aave",    pair="USDC"),
        ]
        result = self.scorer.score(pools)
        self.assertEqual(len(result["pools"]), 3)
        self.assertEqual(result["aggregates"]["total_pools"], 3)

    def test_average_score_is_mean(self):
        pools = [
            _make_pool(protocol="A"),
            _make_pool(protocol="B"),
        ]
        result = self.scorer.score(pools)
        scored = result["pools"]
        expected_avg = round(
            sum(s["concentration_risk_score"] for s in scored) / len(scored), 2
        )
        self.assertAlmostEqual(
            result["aggregates"]["average_concentration_score"], expected_avg, places=1
        )

    def test_most_concentrated_is_highest_score(self):
        pools = [
            _make_pool(protocol="Whale", lp_positions=[
                {"address_alias": "W", "tvl_usd": 9_000_000, "days_providing": 1}
            ]),
            _make_pool(protocol="Diverse", lp_positions=[
                {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
                for i in range(20)
            ]),
        ]
        result = self.scorer.score(pools)
        self.assertEqual(result["aggregates"]["most_concentrated"]["protocol"], "Whale")

    def test_least_concentrated_is_lowest_score(self):
        pools = [
            _make_pool(protocol="Whale", lp_positions=[
                {"address_alias": "W", "tvl_usd": 9_000_000, "days_providing": 1}
            ]),
            _make_pool(protocol="Diverse", lp_positions=[
                {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
                for i in range(20)
            ]),
        ]
        result = self.scorer.score(pools)
        self.assertEqual(result["aggregates"]["least_concentrated"]["protocol"], "Diverse")

    def test_high_concentration_count(self):
        pools = [
            _make_pool(lp_positions=[
                {"address_alias": "Whale", "tvl_usd": 9_500_000, "days_providing": 1}
            ]),
            _make_pool(lp_positions=[
                {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
                for i in range(20)
            ]),
        ]
        result = self.scorer.score(pools)
        # First pool should be HIGH or SINGLE_LP_RISK
        self.assertGreaterEqual(result["aggregates"]["high_concentration_count"], 1)

    def test_total_tvl_sum(self):
        pools = [
            _make_pool(total_tvl_usd=5_000_000),
            _make_pool(total_tvl_usd=3_000_000),
        ]
        result = self.scorer.score(pools)
        self.assertAlmostEqual(
            result["aggregates"]["total_tvl_analyzed_usd"], 8_000_000.0, places=0
        )

    def test_timestamp_present(self):
        result = self.scorer.score([_make_pool()])
        self.assertIn("T", result["timestamp"])

    def test_config_log_path_override(self):
        alt_log = os.path.join(self.tmp, "alt_log.json")
        self.scorer.score([_make_pool()], config={"log_path": alt_log})
        self.assertTrue(os.path.exists(alt_log))

    def test_none_config_uses_default(self):
        result = self.scorer.score([_make_pool()], config=None)
        self.assertIn("aggregates", result)


# ---------------------------------------------------------------------------
# 4. Ring-buffer log
# ---------------------------------------------------------------------------

class TestLogRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log_path = _make_scorer(self.tmp)

    def test_log_created_after_score(self):
        self.scorer.score([_make_pool()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.scorer.score([_make_pool()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        self.scorer.score([_make_pool()])
        self.scorer.score([_make_pool()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_capped_at_100(self):
        for _ in range(110):
            self.scorer.score([_make_pool()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_expected_keys(self):
        self.scorer.score([_make_pool()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        for key in ("timestamp", "total_pools", "average_concentration_score",
                    "high_concentration_count", "total_tvl_analyzed_usd"):
            self.assertIn(key, entry)

    def test_log_empty_score_still_logged(self):
        self.scorer.score([])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["total_pools"], 0)

    def test_log_atomic_write_file_is_valid_json(self):
        """After multiple writes, file must be valid JSON."""
        for i in range(5):
            self.scorer.score([_make_pool(protocol=f"Protocol{i}")])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_ring_drops_oldest(self):
        """After 101 entries the oldest is dropped."""
        for i in range(101):
            self.scorer.score(
                [_make_pool(total_tvl_usd=float(i * 1_000_000))],
                config={"log_path": self.log_path}
            )
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)


# ---------------------------------------------------------------------------
# 5. Aggregates edge cases
# ---------------------------------------------------------------------------

class TestAggregatesEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log_path = _make_scorer(self.tmp)

    def test_most_least_same_pool(self):
        """Single pool → most and least concentrated are same."""
        result = self.scorer.score([_make_pool()])
        agg = result["aggregates"]
        self.assertEqual(agg["most_concentrated"]["protocol"],
                         agg["least_concentrated"]["protocol"])

    def test_aggregates_keys_present(self):
        result = self.scorer.score([_make_pool()])
        keys = ("most_concentrated", "least_concentrated",
                "average_concentration_score", "high_concentration_count",
                "total_tvl_analyzed_usd", "total_pools")
        for k in keys:
            self.assertIn(k, result["aggregates"])

    def test_average_score_single_pool(self):
        pool = _make_pool()
        result = self.scorer.score([pool])
        expected = _score_pool(pool)["concentration_risk_score"]
        self.assertAlmostEqual(
            result["aggregates"]["average_concentration_score"], expected, places=1
        )

    def test_high_concentration_count_zero_for_low_pools(self):
        pools = [
            _make_pool(lp_positions=[
                {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 200}
                for i in range(30)
            ])
            for _ in range(3)
        ]
        result = self.scorer.score(pools)
        # With many diverse LPs score should be low
        self.assertEqual(result["aggregates"]["high_concentration_count"], 0)

    def test_total_tvl_zero_pools(self):
        pools = [_make_pool(total_tvl_usd=0.0), _make_pool(total_tvl_usd=0.0)]
        result = self.scorer.score(pools)
        self.assertEqual(result["aggregates"]["total_tvl_analyzed_usd"], 0.0)

    def test_five_pools_average_correct(self):
        pools = [_make_pool(protocol=f"P{i}") for i in range(5)]
        result = self.scorer.score(pools)
        scores = [s["concentration_risk_score"] for s in result["pools"]]
        expected = round(sum(scores) / len(scores), 2)
        self.assertAlmostEqual(
            result["aggregates"]["average_concentration_score"], expected, places=1
        )


# ---------------------------------------------------------------------------
# 6. Risk labels
# ---------------------------------------------------------------------------

class TestRiskLabels(unittest.TestCase):

    def _score(self, **kwargs):
        return _score_pool(_make_pool(**kwargs))

    def test_label_single_lp_risk_top1_above_60(self):
        r = self._score(lp_positions=[
            {"address_alias": "W", "tvl_usd": 7_000_000, "days_providing": 1},
            {"address_alias": "S", "tvl_usd": 3_000_000, "days_providing": 5},
        ])
        self.assertEqual(r["risk_label"], LABEL_SINGLE_LP_RISK)

    def test_label_all_five_possible(self):
        """Smoke test: all label constants are non-empty strings."""
        for lbl in (LABEL_WELL_DISTRIBUTED, LABEL_LOW_CONCENTRATION,
                    LABEL_MODERATE_RISK, LABEL_HIGH_CONCENTRATION,
                    LABEL_SINGLE_LP_RISK):
            self.assertIsInstance(lbl, str)
            self.assertTrue(lbl)

    def test_label_not_single_lp_risk_at_exactly_60(self):
        r = self._score(lp_positions=[
            {"address_alias": "W", "tvl_usd": 6_000_000, "days_providing": 1},
            {"address_alias": "S", "tvl_usd": 4_000_000, "days_providing": 5},
        ])
        # top1 = 60% exactly — label should NOT be SINGLE_LP_RISK
        self.assertNotEqual(r["risk_label"], LABEL_SINGLE_LP_RISK)

    def test_well_distributed_has_low_score(self):
        pool = _make_pool(lp_positions=[
            {"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 250}
            for i in range(50)
        ], geographic_concentration="diverse", incentive_dependent_pct=0.0)
        r = _score_pool(pool)
        self.assertLessEqual(r["concentration_risk_score"], 30.0)


# ---------------------------------------------------------------------------
# 7. Scorer construction and __init__
# ---------------------------------------------------------------------------

class TestScorerConstruction(unittest.TestCase):

    def test_default_construction(self):
        scorer = DeFiLiquidityConcentrationRiskScorer()
        self.assertIsNotNone(scorer)

    def test_custom_log_path(self):
        scorer = DeFiLiquidityConcentrationRiskScorer(log_path="/tmp/custom_log.json")
        self.assertIsNotNone(scorer)

    def test_score_method_exists(self):
        scorer = DeFiLiquidityConcentrationRiskScorer()
        self.assertTrue(callable(scorer.score))


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):

    def test_same_input_same_output(self):
        tmp = tempfile.mkdtemp()
        scorer = DeFiLiquidityConcentrationRiskScorer(
            log_path=os.path.join(tmp, "log.json")
        )
        pools = [_make_pool(), _make_pool(protocol="Curve")]
        r1 = scorer.score(pools)
        r2 = scorer.score(pools)
        for p1, p2 in zip(r1["pools"], r2["pools"]):
            self.assertEqual(p1["concentration_risk_score"], p2["concentration_risk_score"])
            self.assertEqual(p1["risk_label"], p2["risk_label"])
            self.assertEqual(p1["flags"], p2["flags"])

    def test_score_pool_deterministic(self):
        pool = _make_pool(
            incentive_dependent_pct=55.0,
            pol_pct=45.0,
            sticky_lp_pct=65.0,
            is_cl=True,
            active_range_pct=40.0,
        )
        r1 = _score_pool(pool)
        r2 = _score_pool(pool)
        self.assertEqual(r1["concentration_risk_score"], r2["concentration_risk_score"])


# ---------------------------------------------------------------------------
# 9. Miscellaneous / boundary
# ---------------------------------------------------------------------------

class TestMisc(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer, self.log_path = _make_scorer(self.tmp)

    def test_total_tvl_preserved_in_pool_result(self):
        pool = _make_pool(total_tvl_usd=42_000_000)
        r = _score_pool(pool)
        self.assertAlmostEqual(r["total_tvl_usd"], 42_000_000.0, places=0)

    def test_many_lp_positions(self):
        pool = _make_pool(lp_positions=[
            {"address_alias": f"LP{i}", "tvl_usd": 1_000, "days_providing": 10}
            for i in range(200)
        ])
        r = _score_pool(pool)
        self.assertGreaterEqual(r["top3_concentration_pct"], 0.0)
        self.assertLessEqual(r["top3_concentration_pct"], 100.0)

    def test_score_returns_dict(self):
        result = self.scorer.score([_make_pool()])
        self.assertIsInstance(result, dict)

    def test_pools_list_in_result(self):
        result = self.scorer.score([_make_pool(), _make_pool()])
        self.assertIsInstance(result["pools"], list)

    def test_flags_is_list(self):
        r = _score_pool(_make_pool())
        self.assertIsInstance(r["flags"], list)

    def test_unknown_geo_concentration(self):
        pool = _make_pool(geographic_concentration="unknown")
        r = _score_pool(pool)
        self.assertIsInstance(r["risk_label"], str)

    def test_single_entity_geo_concentration(self):
        pool = _make_pool(geographic_concentration="single_entity")
        r = _score_pool(pool)
        self.assertIsInstance(r["risk_label"], str)

    def test_concentration_score_monotonic_with_dominance(self):
        """Higher top1 share → higher concentration score (other things equal)."""
        pool_low = _make_pool(lp_positions=[
            {"address_alias": f"LP{i}", "tvl_usd": 500_000, "days_providing": 100}
            for i in range(10)
        ])
        pool_high = _make_pool(lp_positions=(
            [{"address_alias": "Whale", "tvl_usd": 4_000_000, "days_providing": 1}]
            + [{"address_alias": f"LP{i}", "tvl_usd": 100_000, "days_providing": 100}
               for i in range(6)]
        ))
        r_low  = _score_pool(pool_low)
        r_high = _score_pool(pool_high)
        self.assertGreater(r_high["concentration_risk_score"],
                           r_low["concentration_risk_score"])

    def test_lp_hhi_monopoly(self):
        pool = _make_pool(lp_positions=[
            {"address_alias": "Only", "tvl_usd": 10_000_000, "days_providing": 1}
        ])
        r = _score_pool(pool)
        self.assertAlmostEqual(r["lp_hhi"], 10000.0, places=0)

    def test_pool_result_risk_label_is_string(self):
        r = _score_pool(_make_pool())
        self.assertIsInstance(r["risk_label"], str)

    def test_scorer_score_with_none_config(self):
        result = self.scorer.score([_make_pool()], config=None)
        self.assertIn("pools", result)

    def test_large_number_of_pools(self):
        pools = [_make_pool(protocol=f"P{i}") for i in range(50)]
        result = self.scorer.score(pools)
        self.assertEqual(len(result["pools"]), 50)
        self.assertEqual(result["aggregates"]["total_pools"], 50)


if __name__ == "__main__":
    unittest.main()
