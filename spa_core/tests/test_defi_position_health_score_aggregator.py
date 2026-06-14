"""
Tests for MP-968: DeFiPositionHealthScoreAggregator
Run: python3 -m unittest spa_core.tests.test_defi_position_health_score_aggregator -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_position_health_score_aggregator import (
    DeFiPositionHealthScoreAggregator,
    _score_health_factor,
    _score_liquidation_distance,
    _score_il,
    _apy_penalty,
    _stale_penalty,
    _score_position,
    _portfolio_label,
    DEFAULT_CONFIG,
)


def _make_lending(
    value_usd=10000, hf=2.0, liq_dist=40.0, apy=3.0,
    days_open=30, cr=None, risk=None, protocol="Aave", pos_id="p1",
):
    p = {
        "id": pos_id, "type": "lending", "protocol": protocol,
        "value_usd": value_usd, "health_factor": hf,
        "liquidation_distance_pct": liq_dist,
        "apy_net_pct": apy, "days_open": days_open,
    }
    if cr is not None:
        p["collateral_ratio_pct"] = cr
    if risk is not None:
        p["risk_score_0_100"] = risk
    return p


def _make_lp(
    value_usd=10000, il=0.0, apy=10.0, days_open=30,
    protocol="Uniswap", pos_id="p2",
):
    return {
        "id": pos_id, "type": "lp", "protocol": protocol,
        "value_usd": value_usd, "il_pct": il,
        "apy_net_pct": apy, "days_open": days_open,
    }


def _make_staking(value_usd=10000, apy=4.0, days_open=30, protocol="Lido", pos_id="p3", risk=None):
    p = {
        "id": pos_id, "type": "staking", "protocol": protocol,
        "value_usd": value_usd, "apy_net_pct": apy, "days_open": days_open,
    }
    if risk is not None:
        p["risk_score_0_100"] = risk
    return p


def _make_vault(value_usd=10000, liq_dist=50.0, apy=5.0, days_open=30, protocol="Yearn", pos_id="p4"):
    return {
        "id": pos_id, "type": "vault", "protocol": protocol,
        "value_usd": value_usd, "liquidation_distance_pct": liq_dist,
        "apy_net_pct": apy, "days_open": days_open,
    }


def _make_perp(value_usd=10000, liq_dist=20.0, apy=0.0, days_open=10, protocol="GMX", pos_id="p5"):
    return {
        "id": pos_id, "type": "perp", "protocol": protocol,
        "value_usd": value_usd, "liquidation_distance_pct": liq_dist,
        "apy_net_pct": apy, "days_open": days_open,
    }


def _no_log_cfg(extra=None):
    cfg = {**DEFAULT_CONFIG, "log_path": "/dev/null"}
    if extra:
        cfg.update(extra)
    return cfg


class TestScoreHealthFactor(unittest.TestCase):
    def test_below_one_is_zero(self):
        self.assertAlmostEqual(_score_health_factor(0.9), 0.0)

    def test_exactly_one_is_zero(self):
        self.assertAlmostEqual(_score_health_factor(1.0), 0.0)

    def test_1_025_low(self):
        score = _score_health_factor(1.025)
        self.assertGreater(score, 0)
        self.assertLess(score, 5)

    def test_1_05_exactly_5(self):
        self.assertAlmostEqual(_score_health_factor(1.05), 5.0)

    def test_1_1_is_15(self):
        self.assertAlmostEqual(_score_health_factor(1.1), 15.0)

    def test_1_2_is_30(self):
        self.assertAlmostEqual(_score_health_factor(1.2), 30.0)

    def test_1_5_is_80(self):
        self.assertAlmostEqual(_score_health_factor(1.5), 80.0)

    def test_2_0_is_95(self):
        self.assertAlmostEqual(_score_health_factor(2.0), 95.0)

    def test_high_hf_approaches_100(self):
        score = _score_health_factor(10.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreater(score, 95.0)

    def test_interpolation_1_1_to_1_2(self):
        mid = _score_health_factor(1.15)
        self.assertGreater(mid, 15.0)
        self.assertLess(mid, 30.0)


class TestScoreLiquidationDistance(unittest.TestCase):
    def test_zero_liq_dist_is_zero(self):
        self.assertAlmostEqual(_score_liquidation_distance(0.0), 0.0)

    def test_50_pct_is_100(self):
        self.assertAlmostEqual(_score_liquidation_distance(50.0), 100.0)

    def test_25_pct_is_50(self):
        self.assertAlmostEqual(_score_liquidation_distance(25.0), 50.0)

    def test_above_50_capped_at_100(self):
        self.assertAlmostEqual(_score_liquidation_distance(80.0), 100.0)

    def test_negative_clamped_zero(self):
        self.assertAlmostEqual(_score_liquidation_distance(-5.0), 0.0)


class TestScoreIL(unittest.TestCase):
    def test_zero_il_perfect(self):
        self.assertAlmostEqual(_score_il(0.0), 100.0)

    def test_20_il_zero(self):
        self.assertAlmostEqual(_score_il(20.0), 0.0)

    def test_10_il_50(self):
        self.assertAlmostEqual(_score_il(10.0), 50.0)

    def test_above_20_clamped_zero(self):
        self.assertAlmostEqual(_score_il(30.0), 0.0)

    def test_5_il_is_75(self):
        self.assertAlmostEqual(_score_il(5.0), 75.0)


class TestApyPenalty(unittest.TestCase):
    def test_positive_apy_no_penalty(self):
        self.assertIsNone(_apy_penalty(5.0))

    def test_zero_apy_no_penalty(self):
        self.assertIsNone(_apy_penalty(0.0))

    def test_negative_apy_penalty(self):
        p = _apy_penalty(-2.0)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 40.0)

    def test_very_negative_apy_zero_floor(self):
        p = _apy_penalty(-20.0)
        self.assertAlmostEqual(p, 0.0)

    def test_minus_10_apy_zero(self):
        self.assertAlmostEqual(_apy_penalty(-10.0), 0.0)


class TestStalePenalty(unittest.TestCase):
    def test_365_days_no_penalty(self):
        self.assertIsNone(_stale_penalty(365, 365))

    def test_366_days_has_penalty(self):
        p = _stale_penalty(366, 365)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 79.9)

    def test_very_old_clamped_zero(self):
        p = _stale_penalty(2000, 365)
        self.assertAlmostEqual(p, 0.0)

    def test_custom_stale_days(self):
        self.assertIsNone(_stale_penalty(90, 180))
        self.assertIsNotNone(_stale_penalty(181, 180))


class TestScorePosition(unittest.TestCase):
    def test_lending_perfect_hf(self):
        pos = _make_lending(hf=3.0, liq_dist=60.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertGreater(result["position_health_score"], 90)

    def test_lending_critical_hf(self):
        pos = _make_lending(hf=1.01, liq_dist=1.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertLess(result["position_health_score"], 10)

    def test_lp_zero_il_perfect(self):
        pos = _make_lp(il=0.0, apy=10.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertGreater(result["position_health_score"], 90)

    def test_lp_high_il(self):
        pos = _make_lp(il=20.0, apy=0.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertAlmostEqual(result["position_health_score"], 0.0)

    def test_negative_apy_reduces_score(self):
        pos = _make_staking(apy=-5.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertLess(result["position_health_score"], 50)

    def test_stale_position_reduces_score(self):
        pos = _make_staking(days_open=500)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertLess(result["position_health_score"], 80)

    def test_score_bounded_0_100(self):
        pos = _make_lending(hf=0.5, liq_dist=0.0, apy=-50.0, days_open=1000)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertGreaterEqual(result["position_health_score"], 0.0)
        self.assertLessEqual(result["position_health_score"], 100.0)

    def test_id_preserved(self):
        pos = _make_lending(pos_id="xyz")
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertEqual(result["id"], "xyz")

    def test_protocol_preserved(self):
        pos = _make_lending(protocol="Morpho")
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertEqual(result["protocol"], "Morpho")

    def test_external_risk_high_reduces_score(self):
        pos_low = _make_staking(risk=10)
        pos_high = _make_staking(risk=90)
        r_low = _score_position(pos_low, DEFAULT_CONFIG)
        r_high = _score_position(pos_high, DEFAULT_CONFIG)
        self.assertGreater(r_low["position_health_score"], r_high["position_health_score"])

    def test_score_components_present(self):
        pos = _make_lending(hf=1.5, liq_dist=30.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertIn("score_components", result)
        self.assertIn("health_factor", result["score_components"])

    def test_lp_il_component_logged(self):
        pos = _make_lp(il=5.0)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertIn("il_score", result["score_components"])

    def test_stale_component_logged(self):
        pos = _make_staking(days_open=400)
        result = _score_position(pos, DEFAULT_CONFIG)
        self.assertIn("stale_penalty", result["score_components"])

    def test_lending_low_cr_penalty(self):
        pos_high = _make_lending(cr=200.0, hf=2.0, liq_dist=60.0)
        pos_low = _make_lending(cr=102.0, hf=2.0, liq_dist=60.0)
        r_high = _score_position(pos_high, DEFAULT_CONFIG)
        r_low = _score_position(pos_low, DEFAULT_CONFIG)
        self.assertGreater(r_high["position_health_score"], r_low["position_health_score"])


class TestPortfolioLabel(unittest.TestCase):
    def setUp(self):
        self.thresholds = DEFAULT_CONFIG["health_thresholds"]

    def test_excellent(self):
        self.assertEqual(_portfolio_label(85.0, self.thresholds), "EXCELLENT")

    def test_healthy(self):
        self.assertEqual(_portfolio_label(70.0, self.thresholds), "HEALTHY")

    def test_moderate(self):
        self.assertEqual(_portfolio_label(50.0, self.thresholds), "MODERATE")

    def test_at_risk(self):
        self.assertEqual(_portfolio_label(30.0, self.thresholds), "AT_RISK")

    def test_critical(self):
        self.assertEqual(_portfolio_label(10.0, self.thresholds), "CRITICAL")

    def test_exactly_80_is_excellent(self):
        # > 80 → EXCELLENT; exactly 80 → HEALTHY
        self.assertEqual(_portfolio_label(80.0, self.thresholds), "HEALTHY")

    def test_exactly_20_is_critical(self):
        self.assertEqual(_portfolio_label(20.0, self.thresholds), "CRITICAL")


class TestAggregatorEmptyInput(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()

    def test_empty_label_critical(self):
        r = self.agg.aggregate([], self.cfg)
        self.assertEqual(r["portfolio_label"], "CRITICAL")

    def test_empty_health_zero(self):
        r = self.agg.aggregate([], self.cfg)
        self.assertEqual(r["weighted_portfolio_health"], 0.0)

    def test_empty_positions_list(self):
        r = self.agg.aggregate([], self.cfg)
        self.assertEqual(r["positions"], [])

    def test_empty_total_value_zero(self):
        r = self.agg.aggregate([], self.cfg)
        self.assertEqual(r["aggregates"]["total_value_usd"], 0.0)

    def test_empty_position_count_zero(self):
        r = self.agg.aggregate([], self.cfg)
        self.assertEqual(r["aggregates"]["position_count"], 0)


class TestAggregatorResultKeys(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()
        self.result = self.agg.aggregate([_make_lending()], self.cfg)

    def test_has_positions(self):
        self.assertIn("positions", self.result)

    def test_has_weighted_health(self):
        self.assertIn("weighted_portfolio_health", self.result)

    def test_has_weakest_link(self):
        self.assertIn("weakest_link_score", self.result)

    def test_has_diversification_score(self):
        self.assertIn("diversification_score", self.result)

    def test_has_total_at_risk(self):
        self.assertIn("total_at_risk_usd", self.result)

    def test_has_portfolio_label(self):
        self.assertIn("portfolio_label", self.result)

    def test_has_flags(self):
        self.assertIn("flags", self.result)

    def test_has_aggregates(self):
        self.assertIn("aggregates", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)


class TestWeightedHealth(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()

    def test_single_position_weighted_equals_score(self):
        pos = _make_lending(hf=2.5, liq_dist=60.0, value_usd=10000)
        r = self.agg.aggregate([pos], self.cfg)
        self.assertAlmostEqual(
            r["weighted_portfolio_health"],
            r["positions"][0]["position_health_score"],
            places=3,
        )

    def test_two_equal_value_positions(self):
        p1 = _make_lending(value_usd=5000, hf=2.5, liq_dist=60.0, protocol="Aave", pos_id="a")
        p2 = _make_lp(value_usd=5000, il=0.0, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        expected = (
            r["positions"][0]["position_health_score"]
            + r["positions"][1]["position_health_score"]
        ) / 2
        self.assertAlmostEqual(r["weighted_portfolio_health"], expected, places=2)

    def test_larger_value_dominates(self):
        p1 = _make_lending(value_usd=90000, hf=2.5, liq_dist=60.0, protocol="Aave", pos_id="a")
        p2 = _make_lp(value_usd=10000, il=19.0, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        score1 = r["positions"][0]["position_health_score"]
        score2 = r["positions"][1]["position_health_score"]
        # Weighted health should be close to score1 (90% weight)
        self.assertGreater(r["weighted_portfolio_health"], score2)
        self.assertLess(
            abs(r["weighted_portfolio_health"] - score1),
            abs(r["weighted_portfolio_health"] - score2),
        )

    def test_weakest_link_is_minimum(self):
        p1 = _make_lending(value_usd=10000, hf=2.5, liq_dist=60.0, protocol="Aave", pos_id="a")
        p2 = _make_lp(value_usd=10000, il=18.0, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        scores = [sp["position_health_score"] for sp in r["positions"]]
        self.assertAlmostEqual(r["weakest_link_score"], min(scores), places=3)

    def test_strongest_position_is_max(self):
        p1 = _make_lending(value_usd=10000, hf=2.5, liq_dist=60.0, protocol="Aave", pos_id="a")
        p2 = _make_lp(value_usd=10000, il=18.0, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        scores = [sp["position_health_score"] for sp in r["positions"]]
        self.assertAlmostEqual(
            r["aggregates"]["strongest_position"]["position_health_score"],
            max(scores),
            places=3,
        )

    def test_average_health_score(self):
        p1 = _make_staking(value_usd=5000, apy=4.0, protocol="Lido", pos_id="a")
        p2 = _make_staking(value_usd=5000, apy=4.0, protocol="Rocket", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        scores = [sp["position_health_score"] for sp in r["positions"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(r["aggregates"]["average_health_score"], expected_avg, places=3)


class TestDiversificationScore(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()

    def test_single_type_zero_diversity(self):
        positions = [_make_staking(value_usd=10000, protocol="Lido", pos_id=f"p{i}")
                     for i in range(3)]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertAlmostEqual(r["diversification_score"], 0.0, places=3)

    def test_two_equal_types(self):
        p1 = _make_lending(value_usd=5000, protocol="Aave", pos_id="a")
        p2 = _make_lp(value_usd=5000, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p1, p2], self.cfg)
        # HHI = 0.5, div = 0.5 * 100 = 50
        self.assertAlmostEqual(r["diversification_score"], 50.0, places=1)

    def test_four_equal_types(self):
        positions = [
            _make_lending(value_usd=2500, protocol="Aave", pos_id="a"),
            _make_lp(value_usd=2500, protocol="Uni", pos_id="b"),
            _make_staking(value_usd=2500, protocol="Lido", pos_id="c"),
            _make_vault(value_usd=2500, protocol="Yearn", pos_id="d"),
        ]
        r = self.agg.aggregate(positions, self.cfg)
        # HHI = 0.25, div = 0.75 * 100 = 75
        self.assertAlmostEqual(r["diversification_score"], 75.0, places=1)

    def test_three_equal_types(self):
        positions = [
            _make_lending(value_usd=3333, protocol="Aave", pos_id="a"),
            _make_lp(value_usd=3333, protocol="Uni", pos_id="b"),
            _make_staking(value_usd=3334, protocol="Lido", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertGreater(r["diversification_score"], 60.0)
        self.assertLess(r["diversification_score"], 70.0)


class TestAtRiskMetrics(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()

    def test_no_positions_at_risk(self):
        positions = [_make_staking(value_usd=10000, apy=4.0)]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertEqual(r["aggregates"]["positions_at_risk_count"], 0)
        self.assertEqual(r["total_at_risk_usd"], 0.0)

    def test_all_positions_at_risk(self):
        # IL 20% → score 0 → at risk (< 30)
        positions = [_make_lp(value_usd=5000, il=20.0, protocol="Uni", pos_id=f"p{i}")
                     for i in range(3)]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertEqual(r["aggregates"]["positions_at_risk_count"], 3)
        self.assertAlmostEqual(r["total_at_risk_usd"], 15000.0, places=0)

    def test_partial_at_risk(self):
        p_safe = _make_staking(value_usd=8000, apy=4.0, protocol="Lido", pos_id="a")
        p_risky = _make_lp(value_usd=2000, il=20.0, protocol="Uni", pos_id="b")
        r = self.agg.aggregate([p_safe, p_risky], self.cfg)
        self.assertEqual(r["aggregates"]["positions_at_risk_count"], 1)
        self.assertAlmostEqual(r["total_at_risk_usd"], 2000.0, places=0)

    def test_position_count(self):
        positions = [_make_staking(pos_id=f"p{i}") for i in range(5)]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertEqual(r["aggregates"]["position_count"], 5)

    def test_total_value_usd(self):
        positions = [
            _make_staking(value_usd=10000, protocol="Lido", pos_id="a"),
            _make_lp(value_usd=20000, protocol="Uni", pos_id="b"),
        ]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertAlmostEqual(r["aggregates"]["total_value_usd"], 30000.0, places=0)


class TestPortfolioLabels(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()

    def test_label_excellent(self):
        # Perfect health factors → EXCELLENT
        positions = [_make_lending(hf=3.0, liq_dist=80.0, apy=4.0)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertEqual(r["portfolio_label"], "EXCELLENT")

    def test_label_critical_from_lp(self):
        # All high IL → CRITICAL
        positions = [_make_lp(il=20.0, value_usd=10000)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertEqual(r["portfolio_label"], "CRITICAL")

    def test_label_at_risk_negative_apy(self):
        positions = [_make_staking(apy=-8.0)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn(r["portfolio_label"], ["AT_RISK", "CRITICAL"])


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()

    def test_single_protocol_concentration_flag(self):
        # 80% in Aave → SINGLE_PROTOCOL_CONCENTRATION
        positions = [
            _make_lending(value_usd=80000, protocol="Aave", pos_id="a"),
            _make_lp(value_usd=20000, protocol="Uniswap", pos_id="b"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("SINGLE_PROTOCOL_CONCENTRATION", r["flags"])

    def test_no_concentration_flag_even_split(self):
        positions = [
            _make_lending(value_usd=40000, protocol="Aave", pos_id="a"),
            _make_lp(value_usd=30000, protocol="Uniswap", pos_id="b"),
            _make_staking(value_usd=30000, protocol="Lido", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("SINGLE_PROTOCOL_CONCENTRATION", r["flags"])

    def test_imminent_liquidation_flag(self):
        # HF 1.01, liq_dist=1 → score < 10 → flag
        positions = [_make_lending(hf=1.01, liq_dist=1.0)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("IMMINENT_LIQUIDATION", r["flags"])

    def test_no_imminent_liquidation_flag_safe(self):
        positions = [_make_lending(hf=2.5, liq_dist=60.0)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("IMMINENT_LIQUIDATION", r["flags"])

    def test_undiversified_one_type(self):
        positions = [
            _make_staking(protocol="Lido", pos_id="a"),
            _make_staking(protocol="Rocket", pos_id="b"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("UNDIVERSIFIED", r["flags"])

    def test_undiversified_two_types(self):
        positions = [
            _make_lending(protocol="Aave", pos_id="a"),
            _make_lp(protocol="Uni", pos_id="b"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("UNDIVERSIFIED", r["flags"])

    def test_no_undiversified_three_types(self):
        positions = [
            _make_lending(protocol="Aave", pos_id="a"),
            _make_lp(protocol="Uni", pos_id="b"),
            _make_staking(protocol="Lido", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("UNDIVERSIFIED", r["flags"])

    def test_high_il_exposure_flag(self):
        # LP > 40% of portfolio
        positions = [
            _make_lp(value_usd=50000, protocol="Uni", pos_id="a"),
            _make_staking(value_usd=40000, protocol="Lido", pos_id="b"),
            _make_lending(value_usd=10000, protocol="Aave", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("HIGH_IL_EXPOSURE", r["flags"])

    def test_no_high_il_exposure_below_threshold(self):
        positions = [
            _make_lp(value_usd=30000, protocol="Uni", pos_id="a"),
            _make_staking(value_usd=50000, protocol="Lido", pos_id="b"),
            _make_lending(value_usd=20000, protocol="Aave", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("HIGH_IL_EXPOSURE", r["flags"])

    def test_stale_position_flag(self):
        positions = [_make_staking(days_open=400)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertIn("STALE_POSITION", r["flags"])

    def test_no_stale_position_flag(self):
        positions = [_make_staking(days_open=100)]
        r = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("STALE_POSITION", r["flags"])

    def test_multiple_flags_simultaneously(self):
        positions = [
            # Same protocol → SINGLE_PROTOCOL_CONCENTRATION
            _make_lending(value_usd=90000, protocol="Aave", hf=1.01, liq_dist=1.0,
                          days_open=400, pos_id="a"),
            _make_lending(value_usd=10000, protocol="Aave", pos_id="b"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg())
        # Single protocol + IMMINENT_LIQUIDATION + UNDIVERSIFIED + STALE
        self.assertGreater(len(r["flags"]), 2)


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()

    def test_custom_concentration_threshold(self):
        # Lower threshold: 30% triggers concentration flag
        positions = [
            _make_lending(value_usd=40000, protocol="Aave", pos_id="a"),
            _make_lp(value_usd=60000, protocol="Uni", pos_id="b"),
        ]
        cfg = _no_log_cfg({"concentration_threshold_pct": 30.0})
        r = self.agg.aggregate(positions, cfg)
        self.assertIn("SINGLE_PROTOCOL_CONCENTRATION", r["flags"])

    def test_custom_lp_exposure_threshold(self):
        positions = [
            _make_lp(value_usd=35000, protocol="Uni", pos_id="a"),
            _make_staking(value_usd=65000, protocol="Lido", pos_id="b"),
        ]
        # Default 40% → no flag; lower to 30% → flag
        r_default = self.agg.aggregate(positions, _no_log_cfg())
        self.assertNotIn("HIGH_IL_EXPOSURE", r_default["flags"])

        r_low = self.agg.aggregate(positions, _no_log_cfg({"lp_exposure_threshold_pct": 30.0}))
        self.assertIn("HIGH_IL_EXPOSURE", r_low["flags"])

    def test_custom_at_risk_threshold(self):
        # Staking with negative APY → score ~25; with high threshold=90 it becomes at_risk
        positions = [_make_staking(value_usd=10000, apy=-5.0)]
        r = self.agg.aggregate(positions, _no_log_cfg({"at_risk_health_threshold": 90.0}))
        self.assertEqual(r["aggregates"]["positions_at_risk_count"], 1)

    def test_custom_stale_days(self):
        positions = [_make_staking(days_open=200)]
        r = self.agg.aggregate(positions, _no_log_cfg({"stale_position_days": 180}))
        self.assertIn("STALE_POSITION", r["flags"])

    def test_custom_min_types(self):
        # Require 5 types → 3 types triggers UNDIVERSIFIED
        positions = [
            _make_lending(protocol="Aave", pos_id="a"),
            _make_lp(protocol="Uni", pos_id="b"),
            _make_staking(protocol="Lido", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, _no_log_cfg({"min_diversification_types": 5}))
        self.assertIn("UNDIVERSIFIED", r["flags"])

    def test_custom_liquidation_threshold(self):
        # HF=1.05 → score ~5 → below threshold 20 → IMMINENT_LIQUIDATION
        positions = [_make_lending(hf=1.05, liq_dist=2.0)]
        r = self.agg.aggregate(positions, _no_log_cfg({"liquidation_imminent_threshold": 20.0}))
        self.assertIn("IMMINENT_LIQUIDATION", r["flags"])


class TestLogFile(unittest.TestCase):
    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "test_health_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            agg = DeFiPositionHealthScoreAggregator()
            agg.aggregate([_make_staking()], cfg)
            self.assertTrue(os.path.exists(log_path))

    def test_log_has_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            agg = DeFiPositionHealthScoreAggregator()
            agg.aggregate([_make_staking()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path, "log_cap": 5}
            agg = DeFiPositionHealthScoreAggregator()
            for _ in range(10):
                agg.aggregate([_make_staking()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_log_entry_has_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            agg = DeFiPositionHealthScoreAggregator()
            agg.aggregate([_make_staking()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])

    def test_log_entry_has_portfolio_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            agg = DeFiPositionHealthScoreAggregator()
            agg.aggregate([_make_staking()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("portfolio_label", data[0])

    def test_log_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            agg = DeFiPositionHealthScoreAggregator()
            agg.aggregate([_make_staking()], cfg)
            agg.aggregate([_make_lending()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.agg = DeFiPositionHealthScoreAggregator()
        self.cfg = _no_log_cfg()

    def test_zero_value_positions(self):
        pos = _make_lending(value_usd=0.0)
        r = self.agg.aggregate([pos], self.cfg)
        self.assertIsNotNone(r["portfolio_label"])

    def test_positions_list_length_matches_input(self):
        positions = [
            _make_lending(protocol="Aave", pos_id="a"),
            _make_lp(protocol="Uni", pos_id="b"),
            _make_staking(protocol="Lido", pos_id="c"),
        ]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertEqual(len(r["positions"]), 3)

    def test_staking_type_accepted(self):
        r = self.agg.aggregate([_make_staking()], self.cfg)
        self.assertEqual(r["positions"][0]["type"], "staking")

    def test_vault_type_accepted(self):
        r = self.agg.aggregate([_make_vault()], self.cfg)
        self.assertEqual(r["positions"][0]["type"], "vault")

    def test_perp_type_accepted(self):
        r = self.agg.aggregate([_make_perp()], self.cfg)
        self.assertEqual(r["positions"][0]["type"], "perp")

    def test_flags_is_list(self):
        r = self.agg.aggregate([_make_staking()], self.cfg)
        self.assertIsInstance(r["flags"], list)

    def test_very_large_portfolio(self):
        positions = [
            _make_lending(value_usd=1_000_000, hf=2.0, protocol="Aave", pos_id=f"p{i}")
            for i in range(5)
        ]
        r = self.agg.aggregate(positions, self.cfg)
        self.assertAlmostEqual(r["aggregates"]["total_value_usd"], 5_000_000.0, delta=1.0)

    def test_lending_no_hf_still_works(self):
        pos = {"id": "x", "type": "lending", "protocol": "Aave",
               "value_usd": 10000, "apy_net_pct": 3.0, "days_open": 10}
        r = self.agg.aggregate([pos], self.cfg)
        self.assertIsNotNone(r["portfolio_label"])

    def test_lp_no_il_uses_zero(self):
        pos = {"id": "x", "type": "lp", "protocol": "Uni",
               "value_usd": 10000, "apy_net_pct": 5.0, "days_open": 10}
        r = self.agg.aggregate([pos], self.cfg)
        self.assertGreater(r["positions"][0]["position_health_score"], 50)


if __name__ == "__main__":
    unittest.main()
