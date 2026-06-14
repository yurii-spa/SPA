"""
Tests for MP-1103: ProtocolDeFiAPYDecompositionAnalyzer
Run with: python3 -m unittest spa_core/tests/test_protocol_defi_apy_decomposition_analyzer.py
Target: ≥ 110 tests, all green.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_apy_decomposition_analyzer import (
    ProtocolDeFiAPYDecompositionAnalyzer,
    _clamp,
    _apy_label,
    _apy_quality_score,
    _incentive_decay_risk_pct,
    _atomic_write,
    _append_log,
    LOG_CAP,
)


def _make_analyzer():
    return ProtocolDeFiAPYDecompositionAnalyzer()


def _base_data(**overrides):
    d = {
        "base_interest_apy_pct": 3.0,
        "token_incentive_apy_pct": 2.0,
        "liquidity_mining_apy_pct": 1.0,
        "boost_apy_pct": 0.5,
        "compounding_apy_pct": 0.5,
        "token_incentive_price_usd": 1.50,
        "token_incentive_30d_change_pct": -10.0,
        "protocol_name": "Aave",
    }
    d.update(overrides)
    return d


class TestConstants(unittest.TestCase):
    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


class TestClamp(unittest.TestCase):
    def test_within_bounds(self):
        self.assertEqual(_clamp(0.5), 0.5)

    def test_at_zero(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_one(self):
        self.assertEqual(_clamp(1.0), 1.0)

    def test_below_zero(self):
        self.assertEqual(_clamp(-0.5), 0.0)

    def test_above_one(self):
        self.assertEqual(_clamp(1.5), 1.0)

    def test_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_custom_bounds_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_custom_bounds_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)


class TestAPYLabel(unittest.TestCase):
    def test_pure_incentive_farm_zero(self):
        self.assertEqual(_apy_label(0.0), "PURE_INCENTIVE_FARM")

    def test_pure_incentive_farm_below_02(self):
        self.assertEqual(_apy_label(0.1), "PURE_INCENTIVE_FARM")

    def test_pure_incentive_farm_exactly_02(self):
        # Not > 0.2, so still PURE_INCENTIVE_FARM
        self.assertEqual(_apy_label(0.2), "PURE_INCENTIVE_FARM")

    def test_incentive_dependent_above_02(self):
        self.assertEqual(_apy_label(0.21), "INCENTIVE_DEPENDENT")

    def test_incentive_dependent_middle(self):
        self.assertEqual(_apy_label(0.3), "INCENTIVE_DEPENDENT")

    def test_incentive_dependent_below_04(self):
        self.assertEqual(_apy_label(0.399), "INCENTIVE_DEPENDENT")

    def test_mixed_yield_at_04(self):
        # Not > 0.4, stays INCENTIVE_DEPENDENT... wait: threshold is > 0.2 for ID
        # and > 0.4 for MIXED. So 0.4 is INCENTIVE_DEPENDENT (not > 0.4)
        self.assertEqual(_apy_label(0.4), "INCENTIVE_DEPENDENT")

    def test_mixed_yield_above_04(self):
        self.assertEqual(_apy_label(0.41), "MIXED_YIELD")

    def test_mixed_yield_middle(self):
        self.assertEqual(_apy_label(0.5), "MIXED_YIELD")

    def test_mixed_yield_below_06(self):
        self.assertEqual(_apy_label(0.599), "MIXED_YIELD")

    def test_mostly_sustainable_above_06(self):
        self.assertEqual(_apy_label(0.61), "MOSTLY_SUSTAINABLE")

    def test_mostly_sustainable_middle(self):
        self.assertEqual(_apy_label(0.7), "MOSTLY_SUSTAINABLE")

    def test_mostly_sustainable_below_08(self):
        self.assertEqual(_apy_label(0.799), "MOSTLY_SUSTAINABLE")

    def test_sustainable_yield_above_08(self):
        self.assertEqual(_apy_label(0.81), "SUSTAINABLE_YIELD")

    def test_sustainable_yield_at_09(self):
        self.assertEqual(_apy_label(0.9), "SUSTAINABLE_YIELD")

    def test_sustainable_yield_at_one(self):
        self.assertEqual(_apy_label(1.0), "SUSTAINABLE_YIELD")

    def test_all_labels_are_strings(self):
        for ratio in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            self.assertIsInstance(_apy_label(ratio), str)


class TestIncentiveDecayRisk(unittest.TestCase):
    def test_zero_incentive_apy(self):
        self.assertEqual(_incentive_decay_risk_pct(0.0, -20.0), 0.0)

    def test_zero_price_change(self):
        self.assertEqual(_incentive_decay_risk_pct(10.0, 0.0), 0.0)

    def test_basic_calculation(self):
        # 10 * abs(-20) / 100 = 2.0
        self.assertAlmostEqual(_incentive_decay_risk_pct(10.0, -20.0), 2.0, places=5)

    def test_positive_change_also_uses_abs(self):
        # Positive 30d change is still risk (could reverse): |+20| = same
        self.assertAlmostEqual(
            _incentive_decay_risk_pct(10.0, 20.0),
            _incentive_decay_risk_pct(10.0, -20.0),
            places=5,
        )

    def test_100pct_price_crash(self):
        # 5 * 100 / 100 = 5.0
        self.assertAlmostEqual(_incentive_decay_risk_pct(5.0, -100.0), 5.0, places=5)

    def test_proportional_to_incentive_apy(self):
        r1 = _incentive_decay_risk_pct(5.0, -20.0)
        r2 = _incentive_decay_risk_pct(10.0, -20.0)
        self.assertAlmostEqual(r2, 2 * r1, places=5)

    def test_proportional_to_change(self):
        r1 = _incentive_decay_risk_pct(10.0, -10.0)
        r2 = _incentive_decay_risk_pct(10.0, -20.0)
        self.assertAlmostEqual(r2, 2 * r1, places=5)


class TestAPYQualityScore(unittest.TestCase):
    def test_fully_sustainable_no_decay(self):
        # ratio=1.0, decay=0, total=10 → base=100, pen=0 → score=100
        score = _apy_quality_score(1.0, 0.0, 10.0)
        self.assertEqual(score, 100)

    def test_pure_incentive_no_decay(self):
        # ratio=0, decay=0 → base=0 → score=0
        score = _apy_quality_score(0.0, 0.0, 10.0)
        self.assertEqual(score, 0)

    def test_score_returns_int(self):
        self.assertIsInstance(_apy_quality_score(0.5, 1.0, 10.0), int)

    def test_score_in_range(self):
        for ratio in [0.0, 0.2, 0.5, 0.8, 1.0]:
            for decay in [0.0, 1.0, 5.0]:
                score = _apy_quality_score(ratio, decay, 10.0)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_higher_sustainability_higher_score(self):
        s1 = _apy_quality_score(0.3, 0.0, 10.0)
        s2 = _apy_quality_score(0.7, 0.0, 10.0)
        self.assertGreater(s2, s1)

    def test_higher_decay_lowers_score(self):
        s_no_decay = _apy_quality_score(0.5, 0.0, 10.0)
        s_high_decay = _apy_quality_score(0.5, 5.0, 10.0)
        self.assertGreaterEqual(s_no_decay, s_high_decay)

    def test_zero_total_apy_no_division_error(self):
        score = _apy_quality_score(1.0, 0.0, 0.0)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_high_ratio_high_score(self):
        score = _apy_quality_score(0.9, 0.0, 10.0)
        self.assertGreater(score, 80)


class TestAnalyzerReturnShape(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_returns_dict(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        expected = {
            "ts", "protocol_name",
            "total_advertised_apy_pct", "sustainable_apy_pct", "incentive_apy_pct",
            "sustainability_ratio", "incentive_decay_risk_pct",
            "apy_quality_score", "apy_label", "components",
        }
        self.assertEqual(set(result.keys()), expected)

    def test_components_sub_dict(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        comp = result["components"]
        self.assertIn("base_interest_apy_pct", comp)
        self.assertIn("token_incentive_apy_pct", comp)
        self.assertIn("liquidity_mining_apy_pct", comp)
        self.assertIn("boost_apy_pct", comp)
        self.assertIn("compounding_apy_pct", comp)
        self.assertIn("token_incentive_price_usd", comp)
        self.assertIn("token_incentive_30d_change_pct", comp)

    def test_protocol_name_preserved(self):
        result = self.analyzer.analyze(_base_data(protocol_name="Compound"), self.cfg)
        self.assertEqual(result["protocol_name"], "Compound")

    def test_ts_is_string(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["ts"], str)
        self.assertGreater(len(result["ts"]), 0)

    def test_type_error_on_non_dict(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([1, 2], self.cfg)

    def test_type_error_on_string(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("bad", self.cfg)

    def test_apy_quality_score_is_int(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["apy_quality_score"], int)

    def test_apy_label_is_string(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["apy_label"], str)

    def test_sustainability_ratio_float(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["sustainability_ratio"], float)


class TestTotalAPYCalculation(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_total_is_sum_of_components(self):
        data = _base_data(
            base_interest_apy_pct=3.0,
            token_incentive_apy_pct=2.0,
            liquidity_mining_apy_pct=1.0,
            boost_apy_pct=0.5,
            compounding_apy_pct=0.5,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["total_advertised_apy_pct"], 7.0, places=5)

    def test_all_zero_components(self):
        data = _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["total_advertised_apy_pct"], 0.0)

    def test_only_base_interest(self):
        data = _base_data(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["total_advertised_apy_pct"], 5.0, places=5)

    def test_only_incentive_components(self):
        data = _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=10.0,
            liquidity_mining_apy_pct=5.0,
            boost_apy_pct=2.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["total_advertised_apy_pct"], 17.0, places=5)


class TestSustainableAPY(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_sustainable_is_base_plus_compounding(self):
        data = _base_data(
            base_interest_apy_pct=4.0, compounding_apy_pct=1.5
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["sustainable_apy_pct"], 5.5, places=5)

    def test_sustainable_zero_when_no_base_or_compounding(self):
        data = _base_data(
            base_interest_apy_pct=0.0, compounding_apy_pct=0.0
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["sustainable_apy_pct"], 0.0)

    def test_incentive_apy_is_incentive_plus_lm_plus_boost(self):
        data = _base_data(
            token_incentive_apy_pct=3.0,
            liquidity_mining_apy_pct=2.0,
            boost_apy_pct=1.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["incentive_apy_pct"], 6.0, places=5)

    def test_incentive_zero_when_no_incentives(self):
        data = _base_data(
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["incentive_apy_pct"], 0.0)

    def test_sustainable_plus_incentive_equals_total(self):
        data = _base_data()
        result = self.analyzer.analyze(data, self.cfg)
        expected = result["sustainable_apy_pct"] + result["incentive_apy_pct"]
        self.assertAlmostEqual(result["total_advertised_apy_pct"], expected, places=4)


class TestSustainabilityRatio(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_fully_sustainable(self):
        data = _base_data(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["sustainability_ratio"], 1.0, places=5)

    def test_zero_sustainability(self):
        data = _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=10.0,
            liquidity_mining_apy_pct=5.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["sustainability_ratio"], 0.0, places=5)

    def test_half_sustainable(self):
        data = _base_data(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=5.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertAlmostEqual(result["sustainability_ratio"], 0.5, places=5)

    def test_ratio_in_range(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertGreaterEqual(result["sustainability_ratio"], 0.0)
        self.assertLessEqual(result["sustainability_ratio"], 1.0)

    def test_all_zero_ratio_is_one(self):
        # Edge case: zero total → sustainability_ratio = 1.0
        data = _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["sustainability_ratio"], 1.0)


class TestAPYLabelAssignment(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def _pure_incentive_data(self):
        return _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=20.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )

    def _incentive_dependent_data(self):
        return _base_data(
            base_interest_apy_pct=1.0,
            token_incentive_apy_pct=4.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )  # ratio = 1/5 = 0.2 → INCENTIVE_DEPENDENT when > 0.2 → actually 0.2 is boundary

    def test_pure_incentive_farm_label(self):
        result = self.analyzer.analyze(self._pure_incentive_data(), self.cfg)
        self.assertEqual(result["apy_label"], "PURE_INCENTIVE_FARM")

    def test_sustainable_label(self):
        data = _base_data(
            base_interest_apy_pct=9.0,
            token_incentive_apy_pct=1.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )  # ratio = 9/10 = 0.9
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["apy_label"], "SUSTAINABLE_YIELD")

    def test_mostly_sustainable_label(self):
        data = _base_data(
            base_interest_apy_pct=7.0,
            token_incentive_apy_pct=3.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )  # ratio = 0.7 → MOSTLY_SUSTAINABLE
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["apy_label"], "MOSTLY_SUSTAINABLE")

    def test_mixed_yield_label(self):
        data = _base_data(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=5.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )  # ratio = 0.5 → MIXED_YIELD
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["apy_label"], "MIXED_YIELD")

    def test_label_valid_values(self):
        valid = {
            "SUSTAINABLE_YIELD", "MOSTLY_SUSTAINABLE", "MIXED_YIELD",
            "INCENTIVE_DEPENDENT", "PURE_INCENTIVE_FARM",
        }
        for base in [0.0, 2.0, 5.0, 8.0, 10.0]:
            for inc in [0.0, 2.0, 5.0, 8.0, 10.0]:
                data = _base_data(
                    base_interest_apy_pct=base,
                    token_incentive_apy_pct=inc,
                    liquidity_mining_apy_pct=0.0,
                    boost_apy_pct=0.0,
                    compounding_apy_pct=0.0,
                )
                result = self.analyzer.analyze(data, self.cfg)
                self.assertIn(result["apy_label"], valid)

    def test_label_consistent_with_ratio(self):
        # When ratio > 0.8, label must be SUSTAINABLE_YIELD
        data = _base_data(
            base_interest_apy_pct=9.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=1.0,
        )  # ratio = 10/10 = 1.0
        result = self.analyzer.analyze(data, self.cfg)
        self.assertGreater(result["sustainability_ratio"], 0.8)
        self.assertEqual(result["apy_label"], "SUSTAINABLE_YIELD")


class TestQualityScoreBounds(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_score_min_zero(self):
        data = _base_data(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=10.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
            token_incentive_30d_change_pct=-100.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertGreaterEqual(result["apy_quality_score"], 0)

    def test_score_max_100(self):
        data = _base_data(
            base_interest_apy_pct=10.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
            token_incentive_30d_change_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertLessEqual(result["apy_quality_score"], 100)

    def test_high_sustainability_high_score(self):
        data = _base_data(
            base_interest_apy_pct=9.0,
            token_incentive_apy_pct=1.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
            token_incentive_30d_change_pct=0.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertGreater(result["apy_quality_score"], 70)

    def test_quality_score_is_int(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["apy_quality_score"], int)


class TestDecayRiskCalculation(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_no_incentives_zero_decay(self):
        data = _base_data(
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            token_incentive_30d_change_pct=-50.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["incentive_decay_risk_pct"], 0.0)

    def test_no_price_change_zero_decay(self):
        data = _base_data(token_incentive_30d_change_pct=0.0)
        result = self.analyzer.analyze(data, self.cfg)
        self.assertEqual(result["incentive_decay_risk_pct"], 0.0)

    def test_decay_uses_absolute_change(self):
        r_neg = self.analyzer.analyze(
            _base_data(token_incentive_30d_change_pct=-20.0), self.cfg
        )["incentive_decay_risk_pct"]
        r_pos = self.analyzer.analyze(
            _base_data(token_incentive_30d_change_pct=20.0), self.cfg
        )["incentive_decay_risk_pct"]
        self.assertAlmostEqual(r_neg, r_pos, places=5)

    def test_larger_incentive_apy_larger_decay(self):
        r_small = self.analyzer.analyze(
            _base_data(
                token_incentive_apy_pct=1.0,
                liquidity_mining_apy_pct=0.0,
                boost_apy_pct=0.0,
                token_incentive_30d_change_pct=-20.0,
            ),
            self.cfg,
        )["incentive_decay_risk_pct"]
        r_large = self.analyzer.analyze(
            _base_data(
                token_incentive_apy_pct=5.0,
                liquidity_mining_apy_pct=0.0,
                boost_apy_pct=0.0,
                token_incentive_30d_change_pct=-20.0,
            ),
            self.cfg,
        )["incentive_decay_risk_pct"]
        self.assertGreater(r_large, r_small)

    def test_decay_is_nonnegative(self):
        for change in [-100.0, -50.0, 0.0, 20.0, 100.0]:
            result = self.analyzer.analyze(
                _base_data(token_incentive_30d_change_pct=change), self.cfg
            )
            self.assertGreaterEqual(result["incentive_decay_risk_pct"], 0.0)


class TestComponentsPreservation(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_all_components_preserved(self):
        data = _base_data(
            base_interest_apy_pct=3.5,
            token_incentive_apy_pct=2.5,
            liquidity_mining_apy_pct=1.5,
            boost_apy_pct=0.7,
            compounding_apy_pct=0.3,
            token_incentive_price_usd=2.25,
            token_incentive_30d_change_pct=-15.0,
        )
        result = self.analyzer.analyze(data, self.cfg)
        comp = result["components"]
        self.assertAlmostEqual(comp["base_interest_apy_pct"], 3.5, places=5)
        self.assertAlmostEqual(comp["token_incentive_apy_pct"], 2.5, places=5)
        self.assertAlmostEqual(comp["liquidity_mining_apy_pct"], 1.5, places=5)
        self.assertAlmostEqual(comp["boost_apy_pct"], 0.7, places=5)
        self.assertAlmostEqual(comp["compounding_apy_pct"], 0.3, places=5)
        self.assertAlmostEqual(comp["token_incentive_price_usd"], 2.25, places=5)
        self.assertAlmostEqual(comp["token_incentive_30d_change_pct"], -15.0, places=5)

    def test_token_price_in_components(self):
        result = self.analyzer.analyze(
            _base_data(token_incentive_price_usd=5.0), self.cfg
        )
        self.assertAlmostEqual(result["components"]["token_incentive_price_usd"], 5.0)

    def test_change_pct_in_components_preserves_sign(self):
        result = self.analyzer.analyze(
            _base_data(token_incentive_30d_change_pct=-30.0), self.cfg
        )
        self.assertAlmostEqual(
            result["components"]["token_incentive_30d_change_pct"], -30.0, places=5
        )


class TestDefaultInputHandling(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_empty_dict_uses_defaults(self):
        result = self.analyzer.analyze({}, self.cfg)
        self.assertEqual(result["total_advertised_apy_pct"], 0.0)
        self.assertEqual(result["protocol_name"], "unknown")

    def test_partial_data_uses_defaults(self):
        result = self.analyzer.analyze({"base_interest_apy_pct": 4.0}, self.cfg)
        self.assertAlmostEqual(result["total_advertised_apy_pct"], 4.0, places=5)

    def test_protocol_name_defaults_to_unknown(self):
        result = self.analyzer.analyze({}, self.cfg)
        self.assertEqual(result["protocol_name"], "unknown")


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_apy_log.json")

    def test_log_created_on_write(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_json_list(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_required_fields(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        for field in [
            "ts", "protocol_name", "total_advertised_apy_pct",
            "sustainable_apy_pct", "sustainability_ratio",
            "apy_label", "apy_quality_score", "incentive_decay_risk_pct",
        ]:
            self.assertIn(field, entry)

    def test_log_appends_multiple_entries(self):
        for _ in range(5):
            self.analyzer.analyze(
                _base_data(), {"write_log": True, "log_path": self.log_path}
            )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 25):
            self.analyzer.analyze(
                _base_data(), {"write_log": True, "log_path": self.log_path}
            )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)

    def test_no_log_when_write_log_false(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": False, "log_path": self.log_path}
        )
        self.assertFalse(os.path.exists(self.log_path))

    def test_corrupt_log_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("not valid json{{")
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_protocol_name_correct(self):
        self.analyzer.analyze(
            _base_data(protocol_name="Morpho"),
            {"write_log": True, "log_path": self.log_path},
        )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "Morpho")


class TestAtomicWrite(unittest.TestCase):
    def test_writes_file(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "out.json")
        _atomic_write(path, [{"x": 1}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"x": 1}])

    def test_overwrites(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "out.json")
        _atomic_write(path, [1])
        _atomic_write(path, [2, 3])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [2, 3])

    def test_creates_parent_dir(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "sub", "out.json")
        _atomic_write(path, {"ok": True})
        self.assertTrue(os.path.exists(path))


class TestAppendLog(unittest.TestCase):
    def test_basic_append(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "log.json")
        entry = {
            "ts": "2026-01-01T00:00:00+00:00",
            "protocol_name": "Yearn",
            "total_advertised_apy_pct": 8.0,
            "sustainable_apy_pct": 3.0,
            "sustainability_ratio": 0.375,
            "apy_label": "INCENTIVE_DEPENDENT",
            "apy_quality_score": 35,
            "incentive_decay_risk_pct": 1.0,
        }
        _append_log(entry, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["protocol_name"], "Yearn")

    def test_ring_buffer_enforced(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "log.json")
        entry = {
            "ts": "2026-01-01T00:00:00+00:00",
            "protocol_name": "T",
            "total_advertised_apy_pct": 5.0,
            "sustainable_apy_pct": 3.0,
            "sustainability_ratio": 0.6,
            "apy_label": "MOSTLY_SUSTAINABLE",
            "apy_quality_score": 60,
            "incentive_decay_risk_pct": 0.5,
        }
        for _ in range(LOG_CAP + 10):
            _append_log(entry, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)


class TestAnalyzerIntegration(unittest.TestCase):
    """End-to-end integration with named protocol scenarios."""

    def setUp(self):
        self.analyzer = _make_analyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "int_log.json")

    def _run(self, **overrides):
        return self.analyzer.analyze(
            _base_data(**overrides),
            {"write_log": True, "log_path": self.log_path},
        )

    def test_pure_organic_yield(self):
        r = self._run(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
            token_incentive_30d_change_pct=0.0,
        )
        self.assertEqual(r["apy_label"], "SUSTAINABLE_YIELD")
        self.assertAlmostEqual(r["sustainability_ratio"], 1.0, places=5)
        self.assertEqual(r["incentive_decay_risk_pct"], 0.0)

    def test_incentive_farm(self):
        r = self._run(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=30.0,
            liquidity_mining_apy_pct=10.0,
            boost_apy_pct=5.0,
            compounding_apy_pct=0.0,
            token_incentive_30d_change_pct=-40.0,
        )
        self.assertEqual(r["apy_label"], "PURE_INCENTIVE_FARM")
        self.assertAlmostEqual(r["sustainability_ratio"], 0.0, places=5)
        self.assertGreater(r["incentive_decay_risk_pct"], 0.0)

    def test_mixed_yield_scenario(self):
        r = self._run(
            base_interest_apy_pct=5.0,
            token_incentive_apy_pct=5.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        self.assertEqual(r["apy_label"], "MIXED_YIELD")

    def test_log_entries_accumulate(self):
        for _ in range(4):
            self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_incentive_dependent_label(self):
        r = self._run(
            base_interest_apy_pct=1.0,
            token_incentive_apy_pct=3.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        # ratio = 1/4 = 0.25 → INCENTIVE_DEPENDENT
        self.assertEqual(r["apy_label"], "INCENTIVE_DEPENDENT")

    def test_mostly_sustainable_label(self):
        r = self._run(
            base_interest_apy_pct=7.0,
            token_incentive_apy_pct=3.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=0.0,
        )
        # ratio = 0.7 → MOSTLY_SUSTAINABLE
        self.assertEqual(r["apy_label"], "MOSTLY_SUSTAINABLE")

    def test_multiple_protocols_log(self):
        for name in ["Aave", "Compound", "Morpho"]:
            self._run(protocol_name=name)
        with open(self.log_path) as f:
            data = json.load(f)
        names = [e["protocol_name"] for e in data]
        self.assertIn("Aave", names)
        self.assertIn("Compound", names)
        self.assertIn("Morpho", names)

    def test_high_decay_lowers_quality(self):
        r_low_decay = self._run(token_incentive_30d_change_pct=0.0)
        r_high_decay = self._run(token_incentive_30d_change_pct=-80.0)
        self.assertGreaterEqual(
            r_low_decay["apy_quality_score"],
            r_high_decay["apy_quality_score"],
        )

    def test_boost_contributes_to_incentive(self):
        r = self._run(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=5.0,
            compounding_apy_pct=0.0,
        )
        self.assertAlmostEqual(r["incentive_apy_pct"], 5.0, places=5)
        self.assertEqual(r["apy_label"], "PURE_INCENTIVE_FARM")

    def test_compounding_contributes_to_sustainable(self):
        r = self._run(
            base_interest_apy_pct=0.0,
            token_incentive_apy_pct=0.0,
            liquidity_mining_apy_pct=0.0,
            boost_apy_pct=0.0,
            compounding_apy_pct=3.0,
        )
        self.assertAlmostEqual(r["sustainable_apy_pct"], 3.0, places=5)
        self.assertEqual(r["apy_label"], "SUSTAINABLE_YIELD")


class TestAnalyzerEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_very_large_apy_values(self):
        result = self.analyzer.analyze(
            _base_data(
                base_interest_apy_pct=100.0,
                token_incentive_apy_pct=200.0,
                token_incentive_30d_change_pct=-50.0,
            ),
            self.cfg,
        )
        self.assertAlmostEqual(
            result["total_advertised_apy_pct"],
            result["sustainable_apy_pct"] + result["incentive_apy_pct"],
            places=4,
        )

    def test_zero_incentive_price_handled(self):
        result = self.analyzer.analyze(
            _base_data(token_incentive_price_usd=0.0), self.cfg
        )
        self.assertIn("apy_label", result)

    def test_extreme_negative_30d_change(self):
        result = self.analyzer.analyze(
            _base_data(token_incentive_30d_change_pct=-100.0), self.cfg
        )
        self.assertGreater(result["incentive_decay_risk_pct"], 0.0)

    def test_extreme_positive_30d_change(self):
        result = self.analyzer.analyze(
            _base_data(token_incentive_30d_change_pct=100.0), self.cfg
        )
        # Absolute value used, so still generates decay risk
        self.assertGreater(result["incentive_decay_risk_pct"], 0.0)

    def test_numeric_precision(self):
        result = self.analyzer.analyze(
            _base_data(
                base_interest_apy_pct=1.23456789,
                compounding_apy_pct=0.98765432,
            ),
            self.cfg,
        )
        self.assertAlmostEqual(
            result["sustainable_apy_pct"],
            1.23456789 + 0.98765432,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
