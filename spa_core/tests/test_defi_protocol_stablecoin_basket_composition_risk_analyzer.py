"""
Tests for MP-1078 DeFiProtocolStablecoinBasketCompositionRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_stablecoin_basket_composition_risk_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_stablecoin_basket_composition_risk_analyzer import (
    DeFiProtocolStablecoinBasketCompositionRiskAnalyzer,
    _validate_component,
    _validate_basket,
    _concentration_score,
    _algo_exposure_pct,
    _avg_peg_deviation_pct,
    _component_risk_score,
    _basket_risk_score,
    _basket_label,
    _iso_now,
    _atomic_write,
    _init_log,
    _append_log,
    analyze,
    ALGO_AVOID_THRESHOLD,
    VALID_BACKING_TYPES,
    VALID_REDEMPTION_MECHANISMS,
    BACKING_TYPE_RISK,
    REDEMPTION_RISK,
    INSURANCE_DISCOUNT,
    LOG_MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _comp(symbol="USDC", weight=100.0, bt="fiat_backed", depeg=0, deviation=0.0):
    return {
        "symbol": symbol,
        "weight_pct": weight,
        "backing_type": bt,
        "depeg_history_count": depeg,
        "current_peg_deviation_pct": deviation,
    }


def _basket(name="TestBasket", components=None, tvl=0.0, rm="direct", insurance=False):
    if components is None:
        components = [_comp()]
    return {
        "basket_name": name,
        "components": components,
        "total_basket_tvl_usd": tvl,
        "redemption_mechanism": rm,
        "has_insurance": insurance,
    }


def _two_equal(bt1="fiat_backed", bt2="fiat_backed", depeg=0, dev=0.0):
    return [_comp("A", 50.0, bt1, depeg, dev), _comp("B", 50.0, bt2, depeg, dev)]


def _fake_log_result():
    return {
        "basket_name": "TestLog",
        "basket_risk_score": 10.0,
        "basket_label": "FORTRESS_BASKET",
        "algo_exposure_pct": 0.0,
        "concentration_score": 0.0,
        "component_count": 1,
        "analyzed_at": _iso_now(),
    }


# ---------------------------------------------------------------------------
# TestValidateComponent
# ---------------------------------------------------------------------------

class TestValidateComponent(unittest.TestCase):

    def test_valid_component_passes(self):
        _validate_component(_comp(), 0)  # must not raise

    def test_missing_symbol_raises(self):
        c = _comp(); del c["symbol"]
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_missing_weight_pct_raises(self):
        c = _comp(); del c["weight_pct"]
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_missing_backing_type_raises(self):
        c = _comp(); del c["backing_type"]
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_missing_depeg_history_count_raises(self):
        c = _comp(); del c["depeg_history_count"]
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_missing_current_peg_deviation_pct_raises(self):
        c = _comp(); del c["current_peg_deviation_pct"]
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_negative_weight_raises(self):
        with self.assertRaises(ValueError):
            _validate_component(_comp(weight=-0.01), 0)

    def test_bool_weight_raises(self):
        with self.assertRaises(ValueError):
            _validate_component(_comp(weight=True), 0)

    def test_invalid_backing_type_raises(self):
        with self.assertRaises(ValueError):
            _validate_component(_comp(bt="synthetic"), 0)

    def test_float_depeg_history_raises(self):
        c = _comp(); c["depeg_history_count"] = 1.5
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_negative_depeg_history_raises(self):
        with self.assertRaises(ValueError):
            _validate_component(_comp(depeg=-1), 0)

    def test_bool_depeg_history_raises(self):
        c = _comp(); c["depeg_history_count"] = True
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_string_deviation_raises(self):
        c = _comp(); c["current_peg_deviation_pct"] = "0.5"
        with self.assertRaises(ValueError):
            _validate_component(c, 0)

    def test_bool_deviation_raises(self):
        c = _comp(); c["current_peg_deviation_pct"] = False
        with self.assertRaises(ValueError):
            _validate_component(c, 0)


# ---------------------------------------------------------------------------
# TestValidateBasket
# ---------------------------------------------------------------------------

class TestValidateBasket(unittest.TestCase):

    def test_valid_basket_single_component_passes(self):
        _validate_basket(_basket())

    def test_valid_basket_two_components_passes(self):
        _validate_basket(_basket(components=_two_equal()))

    def test_missing_basket_name_raises(self):
        b = _basket(); del b["basket_name"]
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_missing_components_raises(self):
        b = _basket(); del b["components"]
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_missing_total_basket_tvl_usd_raises(self):
        b = _basket(); del b["total_basket_tvl_usd"]
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_missing_redemption_mechanism_raises(self):
        b = _basket(); del b["redemption_mechanism"]
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_missing_has_insurance_raises(self):
        b = _basket(); del b["has_insurance"]
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_empty_components_raises(self):
        with self.assertRaises(ValueError):
            _validate_basket(_basket(components=[]))

    def test_components_not_list_raises(self):
        b = _basket(); b["components"] = "not_a_list"
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_weights_not_summing_to_100_raises(self):
        comps = [_comp(weight=70.0)]
        with self.assertRaises(ValueError):
            _validate_basket(_basket(components=comps))

    def test_weights_summing_exactly_100_passes(self):
        comps = [_comp("A", 60.0), _comp("B", 40.0)]
        _validate_basket(_basket(components=comps))

    def test_weights_within_tolerance_passes(self):
        comps = [_comp("A", 99.6)]  # within ±0.5 of 100
        _validate_basket(_basket(components=comps))

    def test_weights_barely_out_of_tolerance_raises(self):
        comps = [_comp("A", 99.4)]  # 0.6 outside tolerance
        with self.assertRaises(ValueError):
            _validate_basket(_basket(components=comps))

    def test_negative_tvl_raises(self):
        b = _basket(); b["total_basket_tvl_usd"] = -1.0
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_bool_tvl_raises(self):
        b = _basket(); b["total_basket_tvl_usd"] = True
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_zero_tvl_passes(self):
        _validate_basket(_basket(tvl=0.0))

    def test_invalid_redemption_mechanism_raises(self):
        with self.assertRaises(ValueError):
            _validate_basket(_basket(rm="instant"))

    def test_direct_redemption_passes(self):
        _validate_basket(_basket(rm="direct"))

    def test_amm_only_redemption_passes(self):
        _validate_basket(_basket(rm="amm_only"))

    def test_delayed_redemption_passes(self):
        _validate_basket(_basket(rm="delayed"))

    def test_has_insurance_int_raises(self):
        b = _basket(); b["has_insurance"] = 1
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_has_insurance_string_raises(self):
        b = _basket(); b["has_insurance"] = "yes"
        with self.assertRaises(ValueError):
            _validate_basket(b)

    def test_empty_basket_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_basket(_basket(name=""))

    def test_basket_not_dict_raises(self):
        with self.assertRaises(ValueError):
            _validate_basket("not_a_dict")

    def test_invalid_component_inside_raises(self):
        comps = [_comp(bt="bad_type")]
        with self.assertRaises(ValueError):
            _validate_basket(_basket(components=comps))


# ---------------------------------------------------------------------------
# TestConcentrationScore
# ---------------------------------------------------------------------------

class TestConcentrationScore(unittest.TestCase):

    def test_single_component_is_100(self):
        self.assertEqual(_concentration_score([_comp()]), 100.0)

    def test_equal_weights_two_components_is_0(self):
        comps = [_comp("A", 50.0), _comp("B", 50.0)]
        self.assertAlmostEqual(_concentration_score(comps), 0.0, places=2)

    def test_equal_weights_three_components_near_0(self):
        comps = [_comp("A", 33.33), _comp("B", 33.33), _comp("C", 33.34)]
        score = _concentration_score(comps)
        self.assertLess(score, 3.0)

    def test_equal_weights_four_components_is_0(self):
        comps = [_comp(f"T{i}", 25.0) for i in range(4)]
        self.assertAlmostEqual(_concentration_score(comps), 0.0, places=2)

    def test_dominated_basket_higher_than_equal(self):
        equal = [_comp("A", 50.0), _comp("B", 50.0)]
        dominated = [_comp("A", 80.0), _comp("B", 20.0)]
        self.assertGreater(_concentration_score(dominated), _concentration_score(equal))

    def test_result_always_between_0_and_100(self):
        for weights in ([50, 50], [70, 30], [90, 10], [33, 33, 34]):
            comps = [_comp(f"T{i}", w) for i, w in enumerate(weights)]
            s = _concentration_score(comps)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_more_equal_components_lower_or_equal_score(self):
        two = [_comp(f"T{i}", 50.0) for i in range(2)]
        four = [_comp(f"T{i}", 25.0) for i in range(4)]
        self.assertLessEqual(_concentration_score(four), _concentration_score(two))

    def test_near_monopoly_near_100(self):
        comps = [_comp("A", 99.0), _comp("B", 1.0)]
        score = _concentration_score(comps)
        self.assertGreater(score, 90.0)


# ---------------------------------------------------------------------------
# TestAlgoExposurePct
# ---------------------------------------------------------------------------

class TestAlgoExposurePct(unittest.TestCase):

    def test_no_algo_components_is_0(self):
        comps = [_comp("USDC", 100.0, "fiat_backed")]
        self.assertEqual(_algo_exposure_pct(comps), 0.0)

    def test_all_algo_is_100(self):
        comps = [_comp("UST", 100.0, "algorithmic")]
        self.assertEqual(_algo_exposure_pct(comps), 100.0)

    def test_mixed_half_algo(self):
        comps = [_comp("A", 50.0, "algorithmic"), _comp("B", 50.0, "fiat_backed")]
        self.assertAlmostEqual(_algo_exposure_pct(comps), 50.0)

    def test_partial_algo_weight(self):
        comps = [_comp("A", 30.0, "algorithmic"), _comp("B", 70.0, "fiat_backed")]
        self.assertAlmostEqual(_algo_exposure_pct(comps), 30.0)

    def test_fiat_backed_not_counted(self):
        self.assertEqual(_algo_exposure_pct([_comp("A", 100.0, "fiat_backed")]), 0.0)

    def test_crypto_overcollateral_not_counted(self):
        comps = [_comp("A", 50.0, "crypto_overcollateral"), _comp("B", 50.0, "rwa_backed")]
        self.assertEqual(_algo_exposure_pct(comps), 0.0)

    def test_two_algo_components_summed(self):
        comps = [
            _comp("A", 20.0, "algorithmic"),
            _comp("B", 15.0, "algorithmic"),
            _comp("C", 65.0, "fiat_backed"),
        ]
        self.assertAlmostEqual(_algo_exposure_pct(comps), 35.0)


# ---------------------------------------------------------------------------
# TestAvgPegDeviation
# ---------------------------------------------------------------------------

class TestAvgPegDeviation(unittest.TestCase):

    def test_all_zero_deviation(self):
        comps = [_comp("A", 50.0, deviation=0.0), _comp("B", 50.0, deviation=0.0)]
        self.assertEqual(_avg_peg_deviation_pct(comps), 0.0)

    def test_uniform_positive_deviation(self):
        comps = [_comp("A", 50.0, deviation=1.0), _comp("B", 50.0, deviation=1.0)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 1.0, places=4)

    def test_negative_deviation_treated_absolute(self):
        comps = [_comp("A", 100.0, deviation=-2.0)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 2.0, places=4)

    def test_weighted_average_two_components(self):
        # 80% at 0% + 20% at 5% = 1.0%
        comps = [_comp("A", 80.0, deviation=0.0), _comp("B", 20.0, deviation=5.0)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 1.0, places=4)

    def test_single_component_deviation(self):
        comps = [_comp("A", 100.0, deviation=3.5)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 3.5, places=4)

    def test_mixed_positive_negative_averages_absolute(self):
        comps = [_comp("A", 50.0, deviation=-1.0), _comp("B", 50.0, deviation=1.0)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 1.0, places=4)

    def test_large_deviation(self):
        comps = [_comp("A", 100.0, deviation=10.0)]
        self.assertAlmostEqual(_avg_peg_deviation_pct(comps), 10.0, places=4)


# ---------------------------------------------------------------------------
# TestComponentRiskScore
# ---------------------------------------------------------------------------

class TestComponentRiskScore(unittest.TestCase):

    def test_fiat_backed_clean_base(self):
        score = _component_risk_score(_comp(bt="fiat_backed", depeg=0, deviation=0.0))
        self.assertAlmostEqual(score, 5.0)

    def test_algorithmic_clean_base(self):
        score = _component_risk_score(_comp(bt="algorithmic", depeg=0, deviation=0.0))
        self.assertAlmostEqual(score, 45.0)

    def test_algorithmic_highest_backing_risk(self):
        fiat = _component_risk_score(_comp(bt="fiat_backed", depeg=0, deviation=0.0))
        algo = _component_risk_score(_comp(bt="algorithmic", depeg=0, deviation=0.0))
        self.assertGreater(algo, fiat)

    def test_rwa_backed_between_fiat_and_crypto(self):
        fiat = _component_risk_score(_comp(bt="fiat_backed", depeg=0))
        rwa = _component_risk_score(_comp(bt="rwa_backed", depeg=0))
        crypto = _component_risk_score(_comp(bt="crypto_overcollateral", depeg=0))
        self.assertLess(fiat, rwa)
        self.assertLess(rwa, crypto)

    def test_depeg_history_adds_5_per_event(self):
        base = _component_risk_score(_comp(bt="fiat_backed", depeg=0))
        one = _component_risk_score(_comp(bt="fiat_backed", depeg=1))
        self.assertAlmostEqual(one - base, 5.0)

    def test_depeg_history_capped_at_30(self):
        # 6 events → 30 points (cap). 7 events should equal 6 events
        score_6 = _component_risk_score(_comp(bt="fiat_backed", depeg=6))
        score_7 = _component_risk_score(_comp(bt="fiat_backed", depeg=7))
        self.assertEqual(score_6, score_7)

    def test_depeg_history_capped_large(self):
        score_6 = _component_risk_score(_comp(bt="fiat_backed", depeg=6))
        score_100 = _component_risk_score(_comp(bt="fiat_backed", depeg=100))
        self.assertEqual(score_6, score_100)

    def test_peg_deviation_adds_10_per_percent(self):
        base = _component_risk_score(_comp(bt="fiat_backed", deviation=0.0))
        one = _component_risk_score(_comp(bt="fiat_backed", deviation=1.0))
        self.assertAlmostEqual(one - base, 10.0)

    def test_peg_deviation_capped_at_25(self):
        # 2.5% → 25 points (cap). 5% should equal 2.5%
        score_2_5 = _component_risk_score(_comp(bt="fiat_backed", deviation=2.5))
        score_5 = _component_risk_score(_comp(bt="fiat_backed", deviation=5.0))
        self.assertEqual(score_2_5, score_5)

    def test_negative_deviation_same_as_positive(self):
        pos = _component_risk_score(_comp(bt="fiat_backed", deviation=2.0))
        neg = _component_risk_score(_comp(bt="fiat_backed", deviation=-2.0))
        self.assertEqual(pos, neg)

    def test_all_max_factors_capped_at_100(self):
        # algo(45) + 6 depegs(30) + 2.5% dev(25) = 100
        score = _component_risk_score(_comp(bt="algorithmic", depeg=6, deviation=2.5))
        self.assertLessEqual(score, 100.0)

    def test_zero_risk_clean_fiat(self):
        score = _component_risk_score(_comp(bt="fiat_backed", depeg=0, deviation=0.0))
        self.assertEqual(score, 5.0)


# ---------------------------------------------------------------------------
# TestBasketRiskScore
# ---------------------------------------------------------------------------

class TestBasketRiskScore(unittest.TestCase):

    def _score(self, components, rm="direct", insurance=False, tvl=0.0):
        conc = _concentration_score(components)
        return _basket_risk_score(components, rm, insurance, conc, tvl)

    def test_clean_fiat_direct_insured_clamps_to_zero(self):
        comps = _two_equal("fiat_backed", "fiat_backed")
        # base 5 − insurance 8 = −3 → clamped to 0
        score = self._score(comps, rm="direct", insurance=True, tvl=0.0)
        self.assertEqual(score, 0.0)

    def test_algo_amm_no_insurance_high(self):
        comps = [_comp("A", 100.0, "algorithmic")]
        score = self._score(comps, rm="amm_only", insurance=False, tvl=0.0)
        self.assertGreater(score, 60.0)

    def test_insurance_reduces_risk(self):
        comps = _two_equal("crypto_overcollateral", "crypto_overcollateral")
        no_ins = self._score(comps, insurance=False, tvl=0.0)
        with_ins = self._score(comps, insurance=True, tvl=0.0)
        self.assertGreater(no_ins, with_ins)

    def test_insurance_discount_amount(self):
        comps = [_comp("A", 100.0, "fiat_backed", depeg=2, deviation=1.0)]
        no_ins = self._score(comps, rm="direct", insurance=False, tvl=0.0)
        with_ins = self._score(comps, rm="direct", insurance=True, tvl=0.0)
        self.assertAlmostEqual(no_ins - with_ins, INSURANCE_DISCOUNT, places=1)

    def test_amm_only_higher_than_direct(self):
        comps = _two_equal("fiat_backed", "fiat_backed")
        direct = self._score(comps, rm="direct", tvl=0.0)
        amm = self._score(comps, rm="amm_only", tvl=0.0)
        self.assertGreater(amm, direct)

    def test_delayed_between_direct_and_amm(self):
        comps = _two_equal("fiat_backed", "fiat_backed")
        direct = self._score(comps, rm="direct", tvl=0.0)
        delayed = self._score(comps, rm="delayed", tvl=0.0)
        amm = self._score(comps, rm="amm_only", tvl=0.0)
        self.assertLessEqual(direct, delayed)
        self.assertLessEqual(delayed, amm)

    def test_large_tvl_reduces_risk(self):
        comps = _two_equal("fiat_backed", "fiat_backed")
        no_tvl = self._score(comps, tvl=0.0)
        big_tvl = self._score(comps, tvl=1e9)
        self.assertGreaterEqual(no_tvl, big_tvl)

    def test_zero_tvl_no_bonus_applied(self):
        # Two equal-weight components → concentration_score=0 → no penalty
        comps = _two_equal("fiat_backed", "fiat_backed")
        score = self._score(comps, tvl=0.0)
        self.assertAlmostEqual(score, 5.0)  # just base fiat risk, no concentration penalty

    def test_concentration_increases_risk(self):
        equal = [_comp(f"T{i}", 25.0) for i in range(4)]
        concentrated = [_comp("A", 97.0), _comp("B", 3.0)]
        self.assertGreater(
            self._score(concentrated, tvl=0.0),
            self._score(equal, tvl=0.0),
        )

    def test_result_bounded_0_100(self):
        comps = [_comp("A", 100.0, "algorithmic", depeg=20, deviation=10.0)]
        score = self._score(comps, rm="amm_only", insurance=False, tvl=0.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_result_always_non_negative(self):
        # Even with insurance and large TVL, never negative
        comps = _two_equal("fiat_backed", "fiat_backed")
        score = self._score(comps, rm="direct", insurance=True, tvl=1e12)
        self.assertGreaterEqual(score, 0.0)


# ---------------------------------------------------------------------------
# TestBasketLabel
# ---------------------------------------------------------------------------

class TestBasketLabel(unittest.TestCase):

    def test_fortress_label_zero_risk(self):
        self.assertEqual(_basket_label(0.0, 0.0), "FORTRESS_BASKET")

    def test_fortress_label_just_below_20(self):
        self.assertEqual(_basket_label(19.99, 0.0), "FORTRESS_BASKET")

    def test_conservative_label_at_20(self):
        self.assertEqual(_basket_label(20.0, 0.0), "CONSERVATIVE")

    def test_conservative_label_midrange(self):
        self.assertEqual(_basket_label(30.0, 0.0), "CONSERVATIVE")

    def test_conservative_label_just_below_40(self):
        self.assertEqual(_basket_label(39.99, 0.0), "CONSERVATIVE")

    def test_balanced_label_at_40(self):
        self.assertEqual(_basket_label(40.0, 0.0), "BALANCED")

    def test_balanced_label_midrange(self):
        self.assertEqual(_basket_label(50.0, 0.0), "BALANCED")

    def test_balanced_label_just_below_60(self):
        self.assertEqual(_basket_label(59.99, 0.0), "BALANCED")

    def test_risky_composition_at_60(self):
        self.assertEqual(_basket_label(60.0, 0.0), "RISKY_COMPOSITION")

    def test_risky_composition_midrange(self):
        self.assertEqual(_basket_label(70.0, 0.0), "RISKY_COMPOSITION")

    def test_avoid_basket_at_80(self):
        self.assertEqual(_basket_label(80.0, 0.0), "AVOID_BASKET")

    def test_avoid_basket_max_risk(self):
        self.assertEqual(_basket_label(100.0, 0.0), "AVOID_BASKET")

    def test_avoid_basket_forced_by_algo_threshold(self):
        self.assertEqual(_basket_label(5.0, ALGO_AVOID_THRESHOLD), "AVOID_BASKET")

    def test_avoid_basket_forced_algo_above_threshold(self):
        self.assertEqual(_basket_label(5.0, ALGO_AVOID_THRESHOLD + 20.0), "AVOID_BASKET")

    def test_algo_just_below_threshold_uses_risk_score(self):
        label = _basket_label(5.0, ALGO_AVOID_THRESHOLD - 0.01)
        self.assertEqual(label, "FORTRESS_BASKET")

    def test_algo_zero_uses_risk_score(self):
        self.assertEqual(_basket_label(25.0, 0.0), "CONSERVATIVE")

    def test_algo_threshold_with_zero_risk_still_avoid(self):
        self.assertEqual(_basket_label(0.0, 50.0), "AVOID_BASKET")


# ---------------------------------------------------------------------------
# TestAnalyze  (integration)
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):

    def _run(self, basket):
        return DeFiProtocolStablecoinBasketCompositionRiskAnalyzer().analyze(basket)

    def test_returns_required_keys(self):
        r = self._run(_basket())
        for k in ("basket_name", "basket_risk_score", "concentration_score",
                  "algo_exposure_pct", "avg_peg_deviation_pct",
                  "basket_label", "component_count", "analyzed_at"):
            self.assertIn(k, r)

    def test_basket_name_in_result(self):
        r = self._run(_basket(name="MyBasket"))
        self.assertEqual(r["basket_name"], "MyBasket")

    def test_component_count_in_result(self):
        comps = [_comp(f"T{i}", 33.33) for i in range(2)] + [_comp("T2", 33.34)]
        r = self._run(_basket(components=comps))
        self.assertEqual(r["component_count"], 3)

    def test_analyzed_at_format(self):
        r = self._run(_basket())
        import re
        self.assertRegex(r["analyzed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_fortress_basket_end_to_end(self):
        comps = _two_equal("fiat_backed", "fiat_backed", depeg=0, dev=0.0)
        r = self._run(_basket(components=comps, rm="direct", insurance=True, tvl=0.0))
        self.assertEqual(r["basket_label"], "FORTRESS_BASKET")

    def test_avoid_basket_via_algo_end_to_end(self):
        comps = [_comp("A", 35.0, "algorithmic"), _comp("B", 65.0, "fiat_backed")]
        r = self._run(_basket(components=comps))
        self.assertEqual(r["basket_label"], "AVOID_BASKET")
        self.assertGreaterEqual(r["algo_exposure_pct"], 30.0)

    def test_conservative_basket_end_to_end(self):
        # fiat_backed × 2, 50/50, 2 depeg, 1% deviation, direct, no insurance, TVL=0
        # component_risk = 5+10+10=25 → weighted_risk=25 → raw=25 → CONSERVATIVE
        comps = _two_equal("fiat_backed", "fiat_backed", depeg=2, dev=1.0)
        r = self._run(_basket(components=comps, rm="direct", insurance=False, tvl=0.0))
        self.assertEqual(r["basket_label"], "CONSERVATIVE")

    def test_config_none_accepted(self):
        r = DeFiProtocolStablecoinBasketCompositionRiskAnalyzer().analyze(_basket(), None)
        self.assertIn("basket_label", r)

    def test_config_empty_dict_accepted(self):
        r = DeFiProtocolStablecoinBasketCompositionRiskAnalyzer().analyze(_basket(), {})
        self.assertIn("basket_label", r)

    def test_module_level_analyze_alias(self):
        r = analyze(_basket())
        self.assertIn("basket_label", r)

    def test_risk_score_bounded_0_100(self):
        comps = [_comp("A", 100.0, "algorithmic", depeg=20, deviation=10.0)]
        r = self._run(_basket(components=comps, rm="amm_only", insurance=False, tvl=0.0))
        self.assertGreaterEqual(r["basket_risk_score"], 0.0)
        self.assertLessEqual(r["basket_risk_score"], 100.0)

    def test_algo_exposure_zero_for_no_algo(self):
        r = self._run(_basket())
        self.assertEqual(r["algo_exposure_pct"], 0.0)

    def test_algo_exposure_correct(self):
        comps = [_comp("A", 40.0, "algorithmic"), _comp("B", 60.0, "fiat_backed")]
        r = self._run(_basket(components=comps))
        self.assertAlmostEqual(r["algo_exposure_pct"], 40.0)

    def test_concentration_score_single_component_is_100(self):
        r = self._run(_basket())
        self.assertAlmostEqual(r["concentration_score"], 100.0)

    def test_concentration_score_two_equal_near_zero(self):
        r = self._run(_basket(components=_two_equal()))
        self.assertAlmostEqual(r["concentration_score"], 0.0, places=2)

    def test_avg_peg_deviation_returned(self):
        comps = [_comp("A", 100.0, deviation=2.5)]
        r = self._run(_basket(components=comps))
        self.assertAlmostEqual(r["avg_peg_deviation_pct"], 2.5, places=4)

    def test_invalid_basket_raises(self):
        with self.assertRaises(ValueError):
            self._run({})


# ---------------------------------------------------------------------------
# TestLogHelpers
# ---------------------------------------------------------------------------

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmpdir, "test_log.json")

    def test_iso_now_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_iso_now_format(self):
        import re
        self.assertRegex(_iso_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_atomic_write_creates_file(self):
        _atomic_write(self._log_path, [{"x": 1}])
        self.assertTrue(os.path.exists(self._log_path))

    def test_atomic_write_content_correct(self):
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(self._log_path, data)
        with open(self._log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_atomic_write_overwrites_existing(self):
        _atomic_write(self._log_path, [1])
        _atomic_write(self._log_path, [2, 3])
        with open(self._log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, [2, 3])

    def test_init_log_empty_if_not_exists(self):
        result = _init_log(os.path.join(self._tmpdir, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_init_log_loads_existing(self):
        _atomic_write(self._log_path, [{"ts": "x"}])
        result = _init_log(self._log_path)
        self.assertEqual(len(result), 1)

    def test_init_log_returns_empty_on_corrupt_json(self):
        with open(self._log_path, "w") as f:
            f.write("not valid json {{{")
        result = _init_log(self._log_path)
        self.assertEqual(result, [])

    def test_append_log_creates_entry(self):
        _append_log(_fake_log_result(), log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["basket_name"], "TestLog")

    def test_append_log_ring_buffer_capped(self):
        fake = _fake_log_result()
        for _ in range(LOG_MAX_ENTRIES + 15):
            _append_log(fake, log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(len(entries), LOG_MAX_ENTRIES)

    def test_append_log_keeps_latest_entries(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            result = dict(_fake_log_result(), basket_name=f"B{i}")
            _append_log(result, log_path=self._log_path)
        entries = _init_log(self._log_path)
        # Last entry should be the latest
        self.assertEqual(entries[-1]["basket_name"], f"B{LOG_MAX_ENTRIES + 4}")

    def test_append_log_bad_path_no_crash(self):
        # Use a file as a parent dir to force OSError
        blocker = os.path.join(self._tmpdir, "blocker.txt")
        with open(blocker, "w") as f:
            f.write("x")
        bad_path = os.path.join(blocker, "nested", "log.json")
        _append_log(_fake_log_result(), log_path=bad_path)  # must not raise


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def _run(self, basket):
        return DeFiProtocolStablecoinBasketCompositionRiskAnalyzer().analyze(basket)

    def test_zero_weight_algo_not_counted_in_exposure(self):
        comps = [_comp("A", 100.0, "fiat_backed"), _comp("B", 0.0, "algorithmic")]
        r = self._run(_basket(components=comps))
        self.assertEqual(r["algo_exposure_pct"], 0.0)

    def test_very_large_tvl_bounded(self):
        comps = _two_equal("fiat_backed", "fiat_backed")
        r = self._run(_basket(components=comps, tvl=1e12))
        self.assertGreaterEqual(r["basket_risk_score"], 0.0)
        self.assertLessEqual(r["basket_risk_score"], 100.0)

    def test_100_pct_algo_forced_avoid(self):
        comps = [_comp("LUNA", 100.0, "algorithmic")]
        r = self._run(_basket(components=comps))
        self.assertEqual(r["basket_label"], "AVOID_BASKET")
        self.assertEqual(r["algo_exposure_pct"], 100.0)

    def test_multiple_backing_types_no_crash(self):
        comps = [
            _comp("A", 20.0, "fiat_backed"),
            _comp("B", 20.0, "crypto_overcollateral"),
            _comp("C", 20.0, "rwa_backed"),
            _comp("D", 20.0, "hybrid"),
            _comp("E", 20.0, "fiat_backed"),
        ]
        r = self._run(_basket(components=comps))
        self.assertIn("basket_label", r)

    def test_large_depeg_count_score_bounded(self):
        comps = [_comp("A", 100.0, "fiat_backed", depeg=1000, deviation=0.0)]
        r = self._run(_basket(components=comps))
        self.assertLessEqual(r["basket_risk_score"], 100.0)

    def test_high_peg_deviation_score_bounded(self):
        comps = [_comp("A", 100.0, "fiat_backed", depeg=0, deviation=999.0)]
        r = self._run(_basket(components=comps))
        self.assertLessEqual(r["basket_risk_score"], 100.0)

    def test_five_equal_weight_components_near_zero_concentration(self):
        comps = [_comp(f"S{i}", 20.0, "fiat_backed") for i in range(5)]
        r = self._run(_basket(components=comps))
        self.assertAlmostEqual(r["concentration_score"], 0.0, places=1)

    def test_analysis_does_not_modify_input(self):
        import copy
        b = _basket(components=[_comp("A", 60.0), _comp("B", 40.0)])
        original = copy.deepcopy(b)
        self._run(b)
        self.assertEqual(b, original)


if __name__ == "__main__":
    unittest.main()
