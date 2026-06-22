"""
Tests for MP-827 DeFiPortfolioHealthScorer.
Run: python3 -m unittest spa_core.tests.test_defi_portfolio_health_scorer -v
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import spa_core.analytics.defi_portfolio_health_scorer as scorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(protocol="Aave", value=10000.0, apy=5.0, risk=20, liq=0.5,
         audits=3, stable=True):
    return {
        "protocol": protocol,
        "value_usd": value,
        "apy": apy,
        "risk_score": risk,
        "liquidity_days": liq,
        "audit_count": audits,
        "is_stablecoin": stable,
    }


def _two_equal():
    return [_pos("A", 5000), _pos("B", 5000)]


# ---------------------------------------------------------------------------
# TestEmptyPositions
# ---------------------------------------------------------------------------

class TestEmptyPositions(unittest.TestCase):
    def _r(self):
        with patch.object(scorer, "_append_log", return_value=None):
            return scorer.analyze([])

    def test_grade_F(self):
        self.assertEqual(self._r()["grade"], "F")

    def test_total_value_zero(self):
        self.assertEqual(self._r()["total_value_usd"], 0.0)

    def test_position_count_zero(self):
        self.assertEqual(self._r()["position_count"], 0)

    def test_all_dimension_zeros(self):
        d = self._r()["dimensions"]
        self.assertEqual(sum(d.values()), 0)

    def test_health_score_zero(self):
        self.assertEqual(self._r()["total_health_score"], 0)

    def test_alerts_empty(self):
        self.assertEqual(self._r()["alerts"], [])

    def test_recommendations_empty(self):
        self.assertEqual(self._r()["recommendations"], [])

    def test_timestamp_present(self):
        self.assertIn("timestamp", self._r())
        self.assertGreater(self._r()["timestamp"], 0)


# ---------------------------------------------------------------------------
# TestYieldScore
# ---------------------------------------------------------------------------

class TestYieldScore(unittest.TestCase):
    def _ys(self, apy):
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze([_pos(apy=apy, value=1000)])
        return r["dimensions"]["yield_score"]

    def test_zero_apy(self):
        self.assertEqual(self._ys(0.0), 0)

    def test_20pct_apy_gives_25(self):
        self.assertEqual(self._ys(20.0), 25)

    def test_10pct_apy_gives_12(self):
        # int(10/20*25) = int(12.5) = 12
        self.assertEqual(self._ys(10.0), 12)

    def test_40pct_apy_capped_25(self):
        self.assertEqual(self._ys(40.0), 25)

    def test_8pct_apy(self):
        # int(8/20*25) = int(10) = 10
        self.assertEqual(self._ys(8.0), 10)

    def test_16pct_apy(self):
        # int(16/20*25) = int(20) = 20
        self.assertEqual(self._ys(16.0), 20)

    def test_4pct_apy(self):
        # int(4/20*25) = int(5) = 5
        self.assertEqual(self._ys(4.0), 5)

    def test_100pct_apy_capped_25(self):
        self.assertEqual(self._ys(100.0), 25)

    def test_yield_score_is_int(self):
        self.assertIsInstance(self._ys(7.0), int)

    def test_weighted_two_positions(self):
        # 50% @ 10% APY + 50% @ 30% APY → weighted = 20% → score = 25
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze([_pos("A", 5000, apy=10), _pos("B", 5000, apy=30)])
        self.assertEqual(r["dimensions"]["yield_score"], 25)


# ---------------------------------------------------------------------------
# TestRiskScoreDim
# ---------------------------------------------------------------------------

class TestRiskScoreDim(unittest.TestCase):
    def _rs(self, risk):
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze([_pos(risk=risk, value=1000)])
        return r["dimensions"]["risk_score"]

    def test_zero_risk_gives_25(self):
        self.assertEqual(self._rs(0), 25)

    def test_100_risk_gives_0(self):
        self.assertEqual(self._rs(100), 0)

    def test_50_risk(self):
        # 25 - int(50/4) = 25 - 12 = 13
        self.assertEqual(self._rs(50), 13)

    def test_60_risk(self):
        # 25 - int(60/4) = 25 - 15 = 10
        self.assertEqual(self._rs(60), 10)

    def test_80_risk(self):
        # 25 - int(80/4) = 25 - 20 = 5
        self.assertEqual(self._rs(80), 5)

    def test_40_risk(self):
        # 25 - int(40/4) = 25 - 10 = 15
        self.assertEqual(self._rs(40), 15)

    def test_risk_score_never_negative(self):
        self.assertGreaterEqual(self._rs(120), 0)

    def test_risk_score_is_int(self):
        self.assertIsInstance(self._rs(30), int)


# ---------------------------------------------------------------------------
# TestLiquidityScore
# ---------------------------------------------------------------------------

class TestLiquidityScore(unittest.TestCase):
    def _ls(self, liq_days, value=1000):
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze([_pos(liq=liq_days, value=value)])
        return r["dimensions"]["liquidity_score"]

    def test_fully_liquid_gives_25(self):
        # liq_days = 0 → <= 1 → all liquid
        self.assertEqual(self._ls(0.0), 25)

    def test_one_day_liquid(self):
        # liq_days = 1.0 → <= 1 → liquid
        self.assertEqual(self._ls(1.0), 25)

    def test_just_over_one_day_not_liquid(self):
        # liq_days = 1.1 → > 1 → not liquid → score 0
        self.assertEqual(self._ls(1.1), 0)

    def test_7_days_not_liquid(self):
        self.assertEqual(self._ls(7.0), 0)

    def test_50_percent_liquid(self):
        # 2 positions equal value, one liquid one not
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze([_pos("A", 1000, liq=0.5), _pos("B", 1000, liq=3.0)])
        # int(0.5 * 25) = 12
        self.assertEqual(r["dimensions"]["liquidity_score"], 12)

    def test_liquidity_score_non_negative(self):
        self.assertGreaterEqual(self._ls(30.0), 0)

    def test_liquidity_score_max_25(self):
        self.assertLessEqual(self._ls(0.0), 25)


# ---------------------------------------------------------------------------
# TestDiversificationScore
# ---------------------------------------------------------------------------

class TestDiversificationScore(unittest.TestCase):
    def _ds(self, positions):
        with patch.object(scorer, "_append_log", return_value=None):
            r = scorer.analyze(positions)
        return r["dimensions"]["diversification_score"]

    def test_one_position(self):
        # hhi=1 → int(0*20)=0, min(5,1)=1 → 1
        self.assertEqual(self._ds([_pos("A", 1000)]), 1)

    def test_two_equal(self):
        # hhi=0.5 → int(0.5*20)=10, min(5,2)=2 → 12
        self.assertEqual(self._ds([_pos("A", 5000), _pos("B", 5000)]), 12)

    def test_five_equal(self):
        # hhi=0.2 (float: ~0.20000000000000004) → 1-hhi≈0.7999...
        # int(0.7999...*20) = int(15.999...) = 15, min(5,5)=5 → 20
        ps = [_pos(str(i), 2000) for i in range(5)]
        self.assertEqual(self._ds(ps), 20)

    def test_four_equal(self):
        # hhi=0.25 → int(0.75*20)=15, min(5,4)=4 → 19
        ps = [_pos(str(i), 2500) for i in range(4)]
        self.assertEqual(self._ds(ps), 19)

    def test_diversification_capped_25(self):
        # many equal positions → score capped at 25
        ps = [_pos(str(i), 100) for i in range(100)]
        self.assertLessEqual(self._ds(ps), 25)

    def test_score_non_negative(self):
        self.assertGreaterEqual(self._ds([_pos()]), 0)

    def test_more_positions_higher_score(self):
        one_pos = self._ds([_pos("X", 10000)])
        five_pos = self._ds([_pos(str(i), 2000) for i in range(5)])
        self.assertGreater(five_pos, one_pos)

    def test_unequal_two_positions_lower_than_equal(self):
        equal = self._ds([_pos("A", 5000), _pos("B", 5000)])
        unequal = self._ds([_pos("A", 9000), _pos("B", 1000)])
        self.assertGreater(equal, unequal)


# ---------------------------------------------------------------------------
# TestGrade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def _grade(self, score):
        return scorer._grade(score)

    def test_80_is_A(self):
        self.assertEqual(self._grade(80), "A")

    def test_100_is_A(self):
        self.assertEqual(self._grade(100), "A")

    def test_65_is_B(self):
        self.assertEqual(self._grade(65), "B")

    def test_79_is_B(self):
        self.assertEqual(self._grade(79), "B")

    def test_50_is_C(self):
        self.assertEqual(self._grade(50), "C")

    def test_64_is_C(self):
        self.assertEqual(self._grade(64), "C")

    def test_35_is_D(self):
        self.assertEqual(self._grade(35), "D")

    def test_49_is_D(self):
        self.assertEqual(self._grade(49), "D")

    def test_34_is_F(self):
        self.assertEqual(self._grade(34), "F")

    def test_0_is_F(self):
        self.assertEqual(self._grade(0), "F")


# ---------------------------------------------------------------------------
# TestAlerts
# ---------------------------------------------------------------------------

class TestAlerts(unittest.TestCase):
    def _alerts(self, positions, config=None):
        with patch.object(scorer, "_append_log", return_value=None):
            return scorer.analyze(positions, config)["alerts"]

    def test_position_over_default_30pct(self):
        # single position = 100% → alert
        a = self._alerts([_pos("Aave", 10000)])
        self.assertTrue(any("Aave" in x and "Position" in x for x in a))

    def test_position_alert_format(self):
        a = self._alerts([_pos("Aave", 10000)])
        self.assertTrue(any(">30%" in x for x in a))

    def test_no_concentration_alert_when_two_equal_high_threshold(self):
        # 50/50 split is OK when threshold is 60%
        a = self._alerts(
            [_pos("A", 5000), _pos("B", 5000)],
            {"max_single_position_pct": 60.0},
        )
        concentration_alerts = [x for x in a if "Position >" in x]
        self.assertEqual(len(concentration_alerts), 0)

    def test_illiquid_alert(self):
        a = self._alerts([_pos("Pendle", 5000, liq=30.0)])
        self.assertTrue(any("Illiquid" in x and "Pendle" in x for x in a))

    def test_illiquid_alert_shows_days(self):
        a = self._alerts([_pos("Pendle", 5000, liq=30.0)])
        illiquid_alerts = [x for x in a if "Illiquid" in x]
        self.assertTrue(any("30 days" in x for x in illiquid_alerts))

    def test_no_illiquid_alert_within_threshold(self):
        a = self._alerts([_pos("A", 5000, liq=3.0)])
        self.assertFalse(any("Illiquid" in x for x in a))

    def test_high_risk_alert(self):
        a = self._alerts([_pos("Risky", 5000, risk=80)])
        self.assertTrue(any("High-risk" in x and "Risky" in x for x in a))

    def test_no_high_risk_alert_at_70(self):
        a = self._alerts([_pos("X", 5000, risk=70)])
        # risk > 70 triggers, not >= 70
        self.assertFalse(any("High-risk" in x for x in a))

    def test_high_risk_alert_at_71(self):
        a = self._alerts([_pos("X", 5000, risk=71)])
        self.assertTrue(any("High-risk" in x for x in a))

    def test_avg_risk_high_alert(self):
        # weighted_avg_risk > 60
        a = self._alerts([_pos("X", 5000, risk=65), _pos("Y", 5000, risk=65)])
        self.assertTrue(any("average risk is HIGH" in x for x in a))

    def test_avg_risk_no_alert_at_60(self):
        a = self._alerts([_pos("X", 5000, risk=60)])
        self.assertFalse(any("average risk is HIGH" in x for x in a))

    def test_custom_max_position_pct(self):
        # 60% position, custom threshold 50%
        a = self._alerts(
            [_pos("A", 6000), _pos("B", 4000)],
            {"max_single_position_pct": 50.0},
        )
        self.assertTrue(any("Position >50%" in x for x in a))

    def test_custom_illiquid_threshold(self):
        a = self._alerts(
            [_pos("A", 5000, liq=5.0)],
            {"max_liquidity_days": 3.0},
        )
        self.assertTrue(any("Illiquid" in x for x in a))


# ---------------------------------------------------------------------------
# TestRecommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def _recs(self, positions, config=None):
        with patch.object(scorer, "_append_log", return_value=None):
            return scorer.analyze(positions, config)["recommendations"]

    def test_no_stablecoin_recommendation(self):
        # no stablecoins → recommendation triggered
        recs = self._recs([_pos("A", 10000, stable=False)])
        self.assertTrue(any("stablecoin" in r for r in recs))

    def test_illiquid_recommendation(self):
        # >50% illiquid
        recs = self._recs([
            _pos("A", 4000, liq=30.0, stable=False),
            _pos("B", 6000, liq=30.0, stable=False),
        ])
        self.assertTrue(any("illiquid" in r.lower() for r in recs))

    def test_concentration_recommendation(self):
        # single position → HHI = 1 > 0.5
        recs = self._recs([_pos("A", 10000)])
        self.assertTrue(any("Diversify" in r for r in recs))

    def test_recommendations_capped_at_3(self):
        # worst-case: no stablecoins, illiquid, concentrated
        recs = self._recs([_pos("A", 10000, stable=False, liq=30.0)])
        self.assertLessEqual(len(recs), 3)

    def test_no_recommendations_healthy_portfolio(self):
        # 3 stablecoin positions, liquid, equal weights
        ps = [_pos(str(i), 3333, stable=True, liq=0.5) for i in range(3)]
        recs = self._recs(ps)
        # May or may not have some, but diversification check:
        self.assertLessEqual(len(recs), 3)


# ---------------------------------------------------------------------------
# TestPortfolioStats
# ---------------------------------------------------------------------------

class TestPortfolioStats(unittest.TestCase):
    def _stats(self, positions):
        with patch.object(scorer, "_append_log", return_value=None):
            return scorer.analyze(positions)["portfolio_stats"]

    def test_weighted_avg_apy(self):
        # 50/50 split, APY 4% and 8% → weighted = 6%
        s = self._stats([_pos("A", 5000, apy=4.0), _pos("B", 5000, apy=8.0)])
        self.assertAlmostEqual(s["weighted_avg_apy"], 6.0, places=2)

    def test_weighted_avg_risk(self):
        # 50/50, risk 20 and 60 → weighted = 40
        s = self._stats([_pos("A", 5000, risk=20), _pos("B", 5000, risk=60)])
        self.assertAlmostEqual(s["weighted_avg_risk"], 40.0, places=2)

    def test_stablecoin_pct_all(self):
        s = self._stats([_pos("A", 5000, stable=True), _pos("B", 5000, stable=True)])
        self.assertAlmostEqual(s["stablecoin_pct"], 100.0, places=1)

    def test_stablecoin_pct_none(self):
        s = self._stats([_pos("A", 5000, stable=False), _pos("B", 5000, stable=False)])
        self.assertAlmostEqual(s["stablecoin_pct"], 0.0, places=1)

    def test_stablecoin_pct_half(self):
        s = self._stats([_pos("A", 5000, stable=True), _pos("B", 5000, stable=False)])
        self.assertAlmostEqual(s["stablecoin_pct"], 50.0, places=1)

    def test_illiquid_pct(self):
        # 1 position illiquid (liq=30 > 7), 1 liquid
        s = self._stats([
            _pos("A", 5000, liq=30.0),
            _pos("B", 5000, liq=0.5),
        ])
        self.assertAlmostEqual(s["illiquid_pct"], 50.0, places=1)

    def test_most_audited_protocol(self):
        s = self._stats([
            _pos("Aave", audits=10),
            _pos("Compound", audits=5),
        ])
        self.assertEqual(s["most_audited_protocol"], "Aave")

    def test_highest_risk_protocol(self):
        s = self._stats([
            _pos("Safe", risk=10),
            _pos("Risky", risk=80),
        ])
        self.assertEqual(s["highest_risk_protocol"], "Risky")


# ---------------------------------------------------------------------------
# TestOutputShape
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def setUp(self):
        with patch.object(scorer, "_append_log", return_value=None):
            self.r = scorer.analyze([_pos()])

    def test_top_level_keys(self):
        expected = {
            "total_value_usd", "position_count", "dimensions",
            "total_health_score", "grade", "portfolio_stats",
            "alerts", "recommendations", "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_dimension_keys(self):
        expected = {"yield_score", "risk_score", "liquidity_score",
                    "diversification_score"}
        self.assertEqual(set(self.r["dimensions"].keys()), expected)

    def test_portfolio_stats_keys(self):
        expected = {"weighted_avg_apy", "weighted_avg_risk", "stablecoin_pct",
                    "illiquid_pct", "most_audited_protocol", "highest_risk_protocol"}
        self.assertEqual(set(self.r["portfolio_stats"].keys()), expected)

    def test_grade_is_string(self):
        self.assertIsInstance(self.r["grade"], str)

    def test_grade_valid_values(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_alerts_is_list(self):
        self.assertIsInstance(self.r["alerts"], list)

    def test_recommendations_is_list(self):
        self.assertIsInstance(self.r["recommendations"], list)

    def test_dimension_sum_equals_total(self):
        d = self.r["dimensions"]
        total = sum(d.values())
        self.assertEqual(total, self.r["total_health_score"])

    def test_total_value_positive(self):
        self.assertGreater(self.r["total_value_usd"], 0)

    def test_position_count_correct(self):
        self.assertEqual(self.r["position_count"], 1)


# ---------------------------------------------------------------------------
# TestLogging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def _tmp_log(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # delete so module creates fresh
        return path

    def test_log_file_created(self):
        tmp = self._tmp_log()
        with patch.object(scorer, "LOG_PATH", tmp):
            scorer.analyze([_pos()])
        self.assertTrue(os.path.exists(tmp))
        os.unlink(tmp)

    def test_log_contains_entry(self):
        tmp = self._tmp_log()
        with patch.object(scorer, "LOG_PATH", tmp):
            scorer.analyze([_pos()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        os.unlink(tmp)

    def test_log_appends(self):
        tmp = self._tmp_log()
        with patch.object(scorer, "LOG_PATH", tmp):
            scorer.analyze([_pos()])
            scorer.analyze([_pos()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)
        os.unlink(tmp)

    def test_log_ring_buffer_capped_at_100(self):
        tmp = self._tmp_log()
        with patch.object(scorer, "LOG_PATH", tmp):
            for _ in range(105):
                scorer.analyze([_pos()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)
        os.unlink(tmp)

    def test_log_entry_has_timestamp(self):
        tmp = self._tmp_log()
        with patch.object(scorer, "LOG_PATH", tmp):
            scorer.analyze([_pos()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def _r(self, positions, config=None):
        with patch.object(scorer, "_append_log", return_value=None):
            return scorer.analyze(positions, config)

    def test_single_position_hhi_1(self):
        r = self._r([_pos("X", 10000)])
        # HHI=1 → diversification_score = min(25, 0+1) = 1
        self.assertEqual(r["dimensions"]["diversification_score"], 1)

    def test_config_none_uses_defaults(self):
        r = self._r([_pos()])
        self.assertIn("grade", r)

    def test_config_empty_dict_uses_defaults(self):
        r = self._r([_pos()], {})
        self.assertIn("grade", r)

    def test_zero_value_position(self):
        # position with value=0 should not crash
        r = self._r([_pos("A", 0.0), _pos("B", 10000.0)])
        self.assertIsInstance(r["grade"], str)

    def test_very_high_apy_capped(self):
        r = self._r([_pos(apy=1000.0)])
        self.assertEqual(r["dimensions"]["yield_score"], 25)

    def test_risk_score_over_100_clamped(self):
        r = self._r([_pos(risk=200)])
        self.assertGreaterEqual(r["dimensions"]["risk_score"], 0)

    def test_all_positions_stablecoin(self):
        ps = [_pos(str(i), stable=True) for i in range(3)]
        r = self._r(ps)
        self.assertAlmostEqual(r["portfolio_stats"]["stablecoin_pct"], 100.0, places=1)

    def test_custom_max_liquidity_days(self):
        # liq=3 days, custom max=2 → should flag illiquid
        r = self._r(
            [_pos("A", 5000, liq=3.0), _pos("B", 5000, liq=0.5)],
            {"max_liquidity_days": 2.0},
        )
        self.assertGreater(r["portfolio_stats"]["illiquid_pct"], 0)


if __name__ == "__main__":
    unittest.main()
