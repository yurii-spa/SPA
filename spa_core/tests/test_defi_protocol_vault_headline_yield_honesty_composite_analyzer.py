"""
Tests for MP-1206: DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_headline_yield_honesty_composite_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_headline_yield_honesty_composite_analyzer import (  # noqa: E501
    DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer,
    _clamp,
    _mean,
    _coerce_num,
    _coerce_drag,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    DOMINANT_SHARE_THRESHOLD,
    MANY_SOURCES_THRESHOLD,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_apr_pct=None,
    drag_components=None,
    total_drag_apr_pct=None,
):
    pos = {"vault": vault}
    if headline_apr_pct is not None:
        pos["headline_apr_pct"] = headline_apr_pct
    if drag_components is not None:
        pos["drag_components"] = drag_components
    if total_drag_apr_pct is not None:
        pos["total_drag_apr_pct"] = total_drag_apr_pct
    return pos


def comp(source, drag):
    return {"source": source, "drag_apr_pct": drag}


NUMERIC_RESULT_KEYS = [
    "headline_apr_pct",
    "raw_total_drag_apr_pct",
    "net_realized_apr_pct",
    "overstatement_pct",
    "realization_ratio",
    "drag_fraction",
    "dominant_drag_apr_pct",
    "dominant_share",
]


def assert_finite_result(testcase, r):
    for k in NUMERIC_RESULT_KEYS:
        v = r.get(k)
        if v is not None:
            testcase.assertTrue(
                math.isfinite(v), "field %s not finite: %r" % (k, v))
    testcase.assertTrue(math.isfinite(r["score"]))


# ── helper: _clamp / _mean ─────────────────────────────────────────────────────

class TestClamp(unittest.TestCase):
    def test_within(self):
        self.assertEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 1.0), 0.0)

    def test_above(self):
        self.assertEqual(_clamp(2.0, 0.0, 1.0), 1.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0, 0.0, 1.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(1.0, 0.0, 1.0), 1.0)

    def test_negative_range(self):
        self.assertEqual(_clamp(-5.0, -3.0, 3.0), -3.0)


class TestMean(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_mean([4.0]), 4.0)

    def test_multi(self):
        self.assertEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negatives(self):
        self.assertEqual(_mean([-2.0, 2.0]), 0.0)


# ── helper: _coerce_num ─────────────────────────────────────────────────────────

class TestCoerceNum(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_coerce_num(5), 5.0)

    def test_float(self):
        self.assertEqual(_coerce_num(2.5), 2.5)

    def test_numeric_string(self):
        self.assertEqual(_coerce_num("3.5"), 3.5)

    def test_whitespace_string(self):
        self.assertEqual(_coerce_num("  7 "), 7.0)

    def test_empty_string(self):
        self.assertIsNone(_coerce_num(""))

    def test_blank_string(self):
        self.assertIsNone(_coerce_num("   "))

    def test_non_numeric_string(self):
        self.assertIsNone(_coerce_num("abc"))

    def test_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_bool_true(self):
        self.assertIsNone(_coerce_num(True))

    def test_bool_false(self):
        self.assertIsNone(_coerce_num(False))

    def test_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_neg_inf(self):
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_negative(self):
        self.assertEqual(_coerce_num(-4.0), -4.0)

    def test_list(self):
        self.assertIsNone(_coerce_num([1, 2]))

    def test_dict(self):
        self.assertIsNone(_coerce_num({"a": 1}))

    def test_inf_string(self):
        self.assertIsNone(_coerce_num("inf"))

    def test_nan_string(self):
        self.assertIsNone(_coerce_num("nan"))


# ── helper: _coerce_drag ────────────────────────────────────────────────────────

class TestCoerceDrag(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(_coerce_drag(2.0), 2.0)

    def test_zero(self):
        self.assertEqual(_coerce_drag(0.0), 0.0)

    def test_negative_taken_as_magnitude(self):
        self.assertEqual(_coerce_drag(-3.0), 3.0)

    def test_numeric_string(self):
        self.assertEqual(_coerce_drag("1.5"), 1.5)

    def test_negative_string(self):
        self.assertEqual(_coerce_drag("-2.5"), 2.5)

    def test_none(self):
        self.assertIsNone(_coerce_drag(None))

    def test_bool(self):
        self.assertIsNone(_coerce_drag(True))

    def test_nan(self):
        self.assertIsNone(_coerce_drag(float("nan")))

    def test_inf(self):
        self.assertIsNone(_coerce_drag(float("inf")))

    def test_non_numeric_string(self):
        self.assertIsNone(_coerce_drag("xyz"))

    def test_empty_string(self):
        self.assertIsNone(_coerce_drag(""))


# ── helper: _grade_from_score ───────────────────────────────────────────────────

class TestGrade(unittest.TestCase):
    def test_a(self):
        self.assertEqual(_grade_from_score(90.0), "A")

    def test_a_boundary(self):
        self.assertEqual(_grade_from_score(85.0), "A")

    def test_b(self):
        self.assertEqual(_grade_from_score(75.0), "B")

    def test_b_boundary(self):
        self.assertEqual(_grade_from_score(70.0), "B")

    def test_c(self):
        self.assertEqual(_grade_from_score(60.0), "C")

    def test_c_boundary(self):
        self.assertEqual(_grade_from_score(55.0), "C")

    def test_d(self):
        self.assertEqual(_grade_from_score(45.0), "D")

    def test_d_boundary(self):
        self.assertEqual(_grade_from_score(40.0), "D")

    def test_f(self):
        self.assertEqual(_grade_from_score(10.0), "F")

    def test_f_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_just_below_a(self):
        self.assertEqual(_grade_from_score(84.99), "B")


# ── helper: _build_default_cfg ──────────────────────────────────────────────────

class TestBuildCfg(unittest.TestCase):
    def test_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_override_path(self):
        cfg = _build_default_cfg({"log_path": "/tmp/x.json"})
        self.assertEqual(cfg["log_path"], "/tmp/x.json")

    def test_override_cap(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_none_override(self):
        cfg = _build_default_cfg(None)
        self.assertEqual(cfg["log_cap"], LOG_CAP)


# ── insufficient-data path ──────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_no_headline(self):
        r = self.a.analyze(make_pos(drag_components=[comp("fee", 1.0)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_headline(self):
        r = self.a.analyze(
            make_pos(headline_apr_pct=0.0, drag_components=[comp("fee", 1.0)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = self.a.analyze(
            make_pos(headline_apr_pct=-5.0, drag_components=[comp("fee", 1.0)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = self.a.analyze(
            make_pos(headline_apr_pct=float("nan"),
                     drag_components=[comp("fee", 1.0)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = self.a.analyze(
            make_pos(headline_apr_pct=float("inf"),
                     drag_components=[comp("fee", 1.0)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_components_no_override(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_component_list(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0, drag_components=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_invalid_components(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=12.0,
            drag_components=[comp("a", float("nan")), comp("b", None)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["score"], 0.0)

    def test_insufficient_grade_f(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommend(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_flag(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_nulls(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertIsNone(r["raw_total_drag_apr_pct"])
        self.assertIsNone(r["net_realized_apr_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["drag_fraction"])

    def test_insufficient_token_preserved(self):
        r = self.a.analyze(make_pos(vault="WeirdVault"))
        self.assertEqual(r["token"], "WeirdVault")

    def test_insufficient_component_count_zero(self):
        r = self.a.analyze(make_pos(headline_apr_pct=12.0))
        self.assertEqual(r["component_count"], 0)


# ── classification: clean ───────────────────────────────────────────────────────

class TestClassifyClean(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_clean_small_drags(self):
        # total drag 0.5 / 18 = 0.028 <= 0.05
        r = self.a.analyze(make_pos(
            headline_apr_pct=18.0,
            drag_components=[comp("fee", 0.3), comp("mgmt", 0.2)]))
        self.assertEqual(r["classification"], "CLEAN_HEADLINE")

    def test_clean_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=18.0, drag_components=[comp("fee", 0.4)]))
        self.assertIn("CLEAN_HEADLINE_CONFIRMED", r["flags"])

    def test_clean_recommend(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=18.0, drag_components=[comp("fee", 0.4)]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_clean_high_score(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=18.0, drag_components=[comp("fee", 0.4)]))
        self.assertGreaterEqual(r["score"], 85.0)

    def test_clean_grade_a(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=18.0, drag_components=[comp("fee", 0.4)]))
        self.assertEqual(r["grade"], "A")

    def test_clean_at_boundary(self):
        # exactly 5% drag fraction → CLEAN
        r = self.a.analyze(make_pos(
            headline_apr_pct=100.0, drag_components=[comp("fee", 5.0)]))
        self.assertEqual(r["drag_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "CLEAN_HEADLINE")

    def test_zero_drag_components_clean(self):
        # a known mechanism contributing exactly 0 → kept, drag 0 → clean
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("fee", 0.0)]))
        self.assertEqual(r["classification"], "CLEAN_HEADLINE")
        self.assertEqual(r["raw_total_drag_apr_pct"], 0.0)


# ── classification: mild / moderate / severe ───────────────────────────────────

class TestClassifyTiers(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_mild(self):
        # 1.8 / 12 = 0.15 → MILD
        r = self.a.analyze(make_pos(
            headline_apr_pct=12.0,
            drag_components=[comp("mgmt", 1.0), comp("slip", 0.8)]))
        self.assertEqual(r["classification"], "MILD_EROSION")

    def test_mild_at_boundary(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=100.0, drag_components=[comp("x", 20.0)]))
        self.assertEqual(r["drag_fraction"], MILD_FRACTION)
        self.assertEqual(r["classification"], "MILD_EROSION")

    def test_mild_recommend(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=100.0, drag_components=[comp("x", 15.0)]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_moderate(self):
        # 4 / 12 = 0.33 → MODERATE
        r = self.a.analyze(make_pos(
            headline_apr_pct=12.0,
            drag_components=[comp("loss", 2.5), comp("fee", 1.5)]))
        self.assertEqual(r["classification"], "MODERATE_EROSION")

    def test_moderate_at_boundary(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=100.0, drag_components=[comp("x", 50.0)]))
        self.assertEqual(r["drag_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["classification"], "MODERATE_EROSION")

    def test_moderate_recommend(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=100.0, drag_components=[comp("x", 40.0)]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_severe_above_moderate(self):
        # 6 / 10 = 0.6 → SEVERE (net positive but > 0.5 fraction)
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0,
            drag_components=[comp("loss", 4.0), comp("fee", 2.0)]))
        self.assertEqual(r["classification"], "SEVERE_EROSION")
        self.assertFalse(r["net_is_negative"])

    def test_severe_net_negative(self):
        # drags exceed headline → net negative → SEVERE
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0,
            drag_components=[comp("loss", 7.0), comp("fee", 5.0)]))
        self.assertEqual(r["classification"], "SEVERE_EROSION")
        self.assertTrue(r["net_is_negative"])

    def test_severe_recommend(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("x", 9.0)]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_severe_net_negative_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("x", 12.0)]))
        self.assertIn("NET_NEGATIVE_AFTER_DRAGS", r["flags"])

    def test_net_exactly_zero_is_negative(self):
        # net == 0 → net_is_negative True (<=0) → SEVERE
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("x", 10.0)]))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_EROSION")


# ── arithmetic correctness ──────────────────────────────────────────────────────

class TestArithmetic(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_raw_total_sum(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("a", 1.0), comp("b", 2.0), comp("c", 0.5)]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 3.5, places=4)

    def test_net_realized(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("a", 5.0)]))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)

    def test_overstatement_equals_total(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("a", 3.0), comp("b", 1.0)]))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["raw_total_drag_apr_pct"], places=4)

    def test_realization_ratio(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components=[comp("a", 5.0)]))
        self.assertAlmostEqual(r["realization_ratio"], 0.75, places=4)

    def test_drag_fraction(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components=[comp("a", 5.0)]))
        self.assertAlmostEqual(r["drag_fraction"], 0.25, places=4)

    def test_realization_clamped_at_zero(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("a", 25.0)]))
        self.assertEqual(r["realization_ratio"], 0.0)

    def test_drag_fraction_clamped_at_one(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("a", 25.0)]))
        self.assertEqual(r["drag_fraction"], 1.0)

    def test_net_can_be_negative_value(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("a", 25.0)]))
        self.assertLess(r["net_realized_apr_pct"], 0.0)

    def test_negative_drag_taken_as_magnitude(self):
        # a -3 drag contributes +3 to the total
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components=[comp("a", -3.0)]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 3.0, places=4)


# ── dominant culprit ────────────────────────────────────────────────────────────

class TestDominant(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_dominant_source(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("fee", 1.0), comp("loss", 5.0),
                            comp("slip", 2.0)]))
        self.assertEqual(r["dominant_source"], "loss")

    def test_dominant_drag_value(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("fee", 1.0), comp("loss", 5.0)]))
        self.assertAlmostEqual(r["dominant_drag_apr_pct"], 5.0, places=4)

    def test_dominant_share(self):
        # loss 6 of total 10 → 0.6
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("fee", 4.0), comp("loss", 6.0)]))
        self.assertAlmostEqual(r["dominant_share"], 0.6, places=4)

    def test_single_dominant_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("fee", 1.0), comp("loss", 9.0)]))
        self.assertIn("SINGLE_DOMINANT_DRAG", r["flags"])

    def test_no_single_dominant_when_balanced(self):
        # two equal drags → share 0.5 each → exactly at threshold (>=0.5) → flagged
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("a", 2.0), comp("b", 2.0)]))
        self.assertAlmostEqual(r["dominant_share"], 0.5, places=4)
        self.assertIn("SINGLE_DOMINANT_DRAG", r["flags"])

    def test_no_single_dominant_below_threshold(self):
        # three equal drags → share 1/3 < 0.5 → not flagged
        r = self.a.analyze(make_pos(
            headline_apr_pct=30.0,
            drag_components=[comp("a", 1.0), comp("b", 1.0), comp("c", 1.0)]))
        self.assertLess(r["dominant_share"], DOMINANT_SHARE_THRESHOLD)
        self.assertNotIn("SINGLE_DOMINANT_DRAG", r["flags"])

    def test_many_sources_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=40.0,
            drag_components=[comp("a", 1.0), comp("b", 1.0),
                            comp("c", 1.0), comp("d", 1.0)]))
        self.assertIn("MANY_DRAG_SOURCES", r["flags"])

    def test_few_sources_no_many_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=40.0,
            drag_components=[comp("a", 1.0), comp("b", 1.0), comp("c", 1.0)]))
        self.assertNotIn("MANY_DRAG_SOURCES", r["flags"])

    def test_component_count(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=40.0,
            drag_components=[comp("a", 1.0), comp("b", 1.0), comp("c", 1.0)]))
        self.assertEqual(r["component_count"], 3)

    def test_dominant_zero_total_share(self):
        # all components zero → dominant_share 0
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0,
            drag_components=[comp("a", 0.0), comp("b", 0.0)]))
        self.assertEqual(r["dominant_share"], 0.0)


# ── component parsing variants ──────────────────────────────────────────────────

class TestComponentParsing(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_dict_mapping(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components={"fee": 1.0, "loss": 3.0}))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 4.0, places=4)
        self.assertEqual(r["component_count"], 2)

    def test_dict_dominant(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components={"fee": 1.0, "loss": 3.0}))
        self.assertEqual(r["dominant_source"], "loss")

    def test_alt_value_key_drag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"source": "fee", "drag": 2.0}]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 2.0, places=4)

    def test_alt_value_key_value(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"source": "fee", "value": 2.0}]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 2.0, places=4)

    def test_alt_value_key_apr_pct(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"source": "fee", "apr_pct": 2.0}]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 2.0, places=4)

    def test_alt_source_key_name(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"name": "loss", "drag_apr_pct": 3.0}]))
        self.assertEqual(r["dominant_source"], "loss")

    def test_alt_source_key_label(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"label": "loss", "drag_apr_pct": 3.0}]))
        self.assertEqual(r["dominant_source"], "loss")

    def test_missing_source_gets_positional(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"drag_apr_pct": 3.0}]))
        self.assertEqual(r["dominant_source"], "component_0")

    def test_bare_number_list(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components=[1.0, 2.0, 0.5]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 3.5, places=4)

    def test_bare_number_positional_source(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components=[1.0, 5.0]))
        self.assertEqual(r["dominant_source"], "component_1")

    def test_mixed_valid_invalid(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("a", 2.0), comp("b", float("nan")),
                            comp("c", 1.0)]))
        self.assertEqual(r["component_count"], 2)
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 3.0, places=4)

    def test_string_value_in_component(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[{"source": "fee", "drag_apr_pct": "2.5"}]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 2.5, places=4)

    def test_dict_with_invalid_values_skipped(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components={"fee": 1.0, "bad": None, "loss": 2.0}))
        self.assertEqual(r["component_count"], 2)

    def test_unknown_components_type_insufficient(self):
        # a non-list, non-dict drag_components → no components → INSUFFICIENT
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components="not-a-container"))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_kept_in_dict(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, drag_components={"fee": 0.0}))
        self.assertEqual(r["component_count"], 1)
        self.assertEqual(r["classification"], "CLEAN_HEADLINE")


# ── override path ───────────────────────────────────────────────────────────────

class TestOverride(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_override_total(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 9.0, places=4)

    def test_override_net(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)

    def test_override_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertIn("DRAG_FROM_OVERRIDE", r["flags"])

    def test_override_used_flag(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertTrue(r["used_override"])

    def test_override_component_count_zero(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertEqual(r["component_count"], 0)

    def test_override_dominant_none(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertIsNone(r["dominant_source"])
        self.assertIsNone(r["dominant_share"])
        self.assertIsNone(r["dominant_drag_apr_pct"])

    def test_override_no_component_flags(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=9.0))
        self.assertNotIn("SINGLE_DOMINANT_DRAG", r["flags"])
        self.assertNotIn("MANY_DRAG_SOURCES", r["flags"])

    def test_override_takes_priority_over_components(self):
        # override present → components ignored
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=6.0,
            drag_components=[comp("a", 100.0)]))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 6.0, places=4)
        self.assertEqual(r["component_count"], 0)

    def test_override_zero(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=0.0))
        self.assertEqual(r["classification"], "CLEAN_HEADLINE")

    def test_override_negative_taken_as_magnitude(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=-9.0))
        self.assertAlmostEqual(r["raw_total_drag_apr_pct"], 9.0, places=4)

    def test_override_net_negative(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, total_drag_apr_pct=15.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_EROSION")

    def test_override_nan_falls_to_components(self):
        # nan override invalid → falls through to components
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, total_drag_apr_pct=float("nan"),
            drag_components=[comp("a", 2.0)]))
        self.assertFalse(r["used_override"])
        self.assertEqual(r["component_count"], 1)

    def test_override_inf_falls_to_components(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=20.0, total_drag_apr_pct=float("inf"),
            drag_components=[comp("a", 2.0)]))
        self.assertFalse(r["used_override"])

    def test_override_grade_consistent(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=24.0, total_drag_apr_pct=0.5))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── scoring monotonicity ────────────────────────────────────────────────────────

class TestScoringMonotonic(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def _score(self, total):
        return self.a.analyze(make_pos(
            headline_apr_pct=20.0,
            drag_components=[comp("x", total)]))["score"]

    def test_more_drag_lower_score(self):
        self.assertGreater(self._score(1.0), self._score(5.0))

    def test_much_more_drag_lower_score(self):
        self.assertGreater(self._score(5.0), self._score(15.0))

    def test_score_bounds(self):
        for total in [0.0, 1.0, 5.0, 10.0, 19.0, 25.0, 50.0]:
            s = self._score(total)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_zero_drag_max_score(self):
        self.assertEqual(self._score(0.0), 100.0)

    def test_score_never_negative_extreme(self):
        self.assertGreaterEqual(self._score(1000.0), 0.0)


# ── aggregate ───────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_portfolio_keys(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=20.0,
                     drag_components=[comp("x", 0.5)]),
            make_pos(vault="B", headline_apr_pct=10.0,
                     drag_components=[comp("x", 8.0)]),
        ])
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)

    def test_cleanest_and_worst(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="Clean", headline_apr_pct=20.0,
                     drag_components=[comp("x", 0.2)]),
            make_pos(vault="Eroded", headline_apr_pct=10.0,
                     drag_components=[comp("x", 9.0)]),
        ])
        agg = out["aggregate"]
        self.assertEqual(agg["cleanest_headline_vault"], "Clean")
        self.assertEqual(agg["worst_eroded_vault"], "Eroded")

    def test_position_count(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=20.0,
                     drag_components=[comp("x", 1.0)]),
            make_pos(vault="B"),  # insufficient
        ])
        self.assertEqual(out["aggregate"]["position_count"], 2)

    def test_net_negative_count(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=10.0,
                     drag_components=[comp("x", 15.0)]),
            make_pos(vault="B", headline_apr_pct=10.0,
                     drag_components=[comp("x", 12.0)]),
            make_pos(vault="C", headline_apr_pct=10.0,
                     drag_components=[comp("x", 1.0)]),
        ])
        self.assertEqual(out["aggregate"]["net_negative_count"], 2)

    def test_all_insufficient_aggregate(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A"),
            make_pos(vault="B"),
        ])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_headline_vault"])
        self.assertIsNone(agg["worst_eroded_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_empty_portfolio(self):
        out = self.a.analyze_portfolio([])
        self.assertEqual(out["positions"], [])
        self.assertEqual(out["aggregate"]["position_count"], 0)

    def test_avg_score_excludes_insufficient(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=20.0,
                     drag_components=[comp("x", 0.0)]),  # score 100
            make_pos(vault="B"),  # insufficient — excluded
        ])
        self.assertEqual(out["aggregate"]["avg_score"], 100.0)

    def test_avg_score_value(self):
        out = self.a.analyze_portfolio([
            make_pos(vault="A", headline_apr_pct=20.0,
                     drag_components=[comp("x", 0.0)]),  # 100
            make_pos(vault="B", headline_apr_pct=10.0,
                     drag_components=[comp("x", 10.0)]),  # net 0 → low
        ])
        scores = [r["score"] for r in out["positions"]]
        self.assertAlmostEqual(
            out["aggregate"]["avg_score"], round(sum(scores) / 2, 2), places=2)


# ── logging ─────────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "composite_log.json")

    def _cfg(self, cap=LOG_CAP):
        return {"log_path": self.log_path, "log_cap": cap}

    def test_no_log_by_default(self):
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]))
        self.assertFalse(os.path.exists(self.log_path))

    def test_write_log_creates_file(self):
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]),
                       cfg=self._cfg(), write_log=True)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]),
                       cfg=self._cfg(), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_log_entry_fields(self):
        self.a.analyze_portfolio(
            [make_pos(headline_apr_pct=20.0, drag_components=[comp("x", 1.0)])],
            cfg=self._cfg(), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        self.assertIn("ts", entry)
        self.assertIn("aggregate", entry)
        self.assertIn("snapshots", entry)
        self.assertIn("dominant_source", entry["snapshots"][0])

    def test_log_appends(self):
        for _ in range(3):
            self.a.analyze(make_pos(headline_apr_pct=20.0,
                                    drag_components=[comp("x", 1.0)]),
                           cfg=self._cfg(), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        for _ in range(5):
            self.a.analyze(make_pos(headline_apr_pct=20.0,
                                    drag_components=[comp("x", 1.0)]),
                           cfg=self._cfg(cap=2), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_corrupt_recovered(self):
        with open(self.log_path, "w") as fh:
            fh.write("{not valid json")
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]),
                       cfg=self._cfg(), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_non_list_recovered(self):
        with open(self.log_path, "w") as fh:
            json.dump({"a": 1}, fh)
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]),
                       cfg=self._cfg(), write_log=True)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_no_tmp_left(self):
        self.a.analyze(make_pos(headline_apr_pct=20.0,
                                drag_components=[comp("x", 1.0)]),
                       cfg=self._cfg(), write_log=True)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))


# ── finiteness invariants ───────────────────────────────────────────────────────

class TestFiniteness(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_demo_all_finite(self):
        out = self.a.analyze_portfolio(_demo_positions())
        for r in out["positions"]:
            assert_finite_result(self, r)

    def test_extreme_headline_finite(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=1e9, drag_components=[comp("x", 1.0)]))
        assert_finite_result(self, r)

    def test_tiny_headline_finite(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=1e-6, drag_components=[comp("x", 1.0)]))
        assert_finite_result(self, r)

    def test_extreme_drag_finite(self):
        r = self.a.analyze(make_pos(
            headline_apr_pct=10.0, drag_components=[comp("x", 1e9)]))
        assert_finite_result(self, r)

    def test_many_components_finite(self):
        comps = [comp("c%d" % i, float(i) * 0.1) for i in range(50)]
        r = self.a.analyze(make_pos(headline_apr_pct=100.0,
                                    drag_components=comps))
        assert_finite_result(self, r)

    def test_score_in_bounds_random_ish(self):
        for h in [1.0, 5.0, 12.5, 50.0, 200.0]:
            for d in [0.0, 0.5, 3.0, 7.0, 49.0, 500.0]:
                r = self.a.analyze(make_pos(
                    headline_apr_pct=h, drag_components=[comp("x", d)]))
                self.assertGreaterEqual(r["score"], 0.0)
                self.assertLessEqual(r["score"], 100.0)


# ── token / misc ────────────────────────────────────────────────────────────────

class TestTokenAndMisc(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_token_key(self):
        r = self.a.analyze({"token": "TKN", "headline_apr_pct": 20.0,
                            "drag_components": [comp("x", 1.0)]})
        self.assertEqual(r["token"], "TKN")

    def test_vault_preferred_over_token(self):
        r = self.a.analyze({"vault": "V", "token": "T",
                            "headline_apr_pct": 20.0,
                            "drag_components": [comp("x", 1.0)]})
        self.assertEqual(r["token"], "V")

    def test_unknown_token_default(self):
        r = self.a.analyze({"headline_apr_pct": 20.0,
                            "drag_components": [comp("x", 1.0)]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_classification_always_in_flags(self):
        r = self.a.analyze(make_pos(headline_apr_pct=20.0,
                                    drag_components=[comp("x", 1.0)]))
        self.assertIn(r["classification"], r["flags"])

    def test_result_has_all_keys(self):
        r = self.a.analyze(make_pos(headline_apr_pct=20.0,
                                    drag_components=[comp("x", 1.0)]))
        for k in [
            "token", "headline_apr_pct", "raw_total_drag_apr_pct",
            "net_realized_apr_pct", "overstatement_pct", "realization_ratio",
            "drag_fraction", "component_count", "dominant_source",
            "dominant_drag_apr_pct", "dominant_share", "net_is_negative",
            "used_override", "score", "classification", "recommendation",
            "grade", "flags",
        ]:
            self.assertIn(k, r)

    def test_analyze_does_not_mutate_input(self):
        pos = make_pos(headline_apr_pct=20.0, drag_components=[comp("x", 1.0)])
        snapshot = json.dumps(pos, sort_keys=True)
        self.a.analyze(pos)
        self.assertEqual(json.dumps(pos, sort_keys=True), snapshot)


# ── demo / CLI ──────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer()

    def test_demo_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_runs(self):
        out = self.a.analyze_portfolio(_demo_positions())
        self.assertEqual(len(out["positions"]), 5)

    def test_demo_classifications_present(self):
        out = self.a.analyze_portfolio(_demo_positions())
        classes = {r["classification"] for r in out["positions"]}
        self.assertIn("CLEAN_HEADLINE", classes)
        self.assertIn("SEVERE_EROSION", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_severe_dominant_is_loss(self):
        out = self.a.analyze_portfolio(_demo_positions())
        severe = [r for r in out["positions"]
                  if r["token"] == "GOV-Vault-SevereErosion"][0]
        self.assertEqual(severe["dominant_source"], "net_of_loss")

    def test_demo_override_present(self):
        out = self.a.analyze_portfolio(_demo_positions())
        ov = [r for r in out["positions"]
              if r["token"] == "LST-Vault-OverrideTotal"][0]
        self.assertTrue(ov["used_override"])

    def test_demo_json_serializable(self):
        out = self.a.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertIsInstance(s, str)


# ── registry ────────────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        mods = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_headline_yield_honesty_composite_analyzer",
            mods)

    def test_registered_class_and_tier(self):
        from spa_core.analytics import _module_registry as reg
        entry = [m for m in reg.ALL_MODULES
                 if m["module"] ==
                 "defi_protocol_vault_headline_yield_honesty_composite_analyzer"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(
            entry[0]["class"],
            "DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer")
        self.assertEqual(entry[0]["tier"], "B")
        self.assertEqual(entry[0]["category"], "yield_quality")


if __name__ == "__main__":
    unittest.main()
