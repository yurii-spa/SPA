"""
Tests for MP-931 ProtocolRealYieldVsPaperYieldAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_real_yield_vs_paper_yield_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_real_yield_vs_paper_yield_analyzer import (
    ProtocolRealYieldVsPaperYieldAnalyzer,
    _clamp_ratio,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="TestProtocol",
    advertised_apy_pct=10.0,
    fee_revenue_apy_pct=5.0,
    token_emission_apy_pct=5.0,
    token_price_change_30d_pct=0.0,
    inflation_rate_pct=2.0,
    tvl_usd=100_000_000.0,
    protocol_revenue_monthly_usd=500_000.0,
) -> dict:
    return {
        "name": name,
        "advertised_apy_pct": advertised_apy_pct,
        "fee_revenue_apy_pct": fee_revenue_apy_pct,
        "token_emission_apy_pct": token_emission_apy_pct,
        "token_price_change_30d_pct": token_price_change_30d_pct,
        "inflation_rate_pct": inflation_rate_pct,
        "tvl_usd": tvl_usd,
        "protocol_revenue_monthly_usd": protocol_revenue_monthly_usd,
    }


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and basic structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolRealYieldVsPaperYieldAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_method_exists(self):
        a = ProtocolRealYieldVsPaperYieldAnalyzer()
        self.assertTrue(callable(a.analyze))

    def test_analyze_returns_dict(self):
        a = ProtocolRealYieldVsPaperYieldAnalyzer()
        result = a.analyze([], NO_LOG)
        self.assertIsInstance(result, dict)

    def test_result_has_required_keys(self):
        a = ProtocolRealYieldVsPaperYieldAnalyzer()
        result = a.analyze([], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, result)

    def test_raises_typeerror_non_list(self):
        a = ProtocolRealYieldVsPaperYieldAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze("not a list", NO_LOG)


# ===========================================================================
# 2. Empty protocols
# ===========================================================================

class TestEmptyProtocols(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_empty_results_list(self):
        r = self.a.analyze([], NO_LOG)
        self.assertEqual(r["results"], [])

    def test_empty_aggregates_defaults(self):
        r = self.a.analyze([], NO_LOG)
        agg = r["aggregates"]
        self.assertIsNone(agg["best_real_yield"])
        self.assertIsNone(agg["worst_real_yield"])
        self.assertEqual(agg["average_yield_quality_ratio"], 0.0)
        self.assertEqual(agg["average_true_apy"], 0.0)
        self.assertEqual(agg["genuine_yield_count"], 0)

    def test_timestamp_is_float(self):
        r = self.a.analyze([], NO_LOG)
        self.assertIsInstance(r["timestamp"], float)


# ===========================================================================
# 3. Per-protocol result structure
# ===========================================================================

class TestProtocolResultStructure(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()
        self.r = self.a.analyze([_proto()], NO_LOG)["results"][0]

    def test_has_name(self):
        self.assertIn("name", self.r)

    def test_has_advertised_apy(self):
        self.assertIn("advertised_apy_pct", self.r)

    def test_has_real_apy(self):
        self.assertIn("real_apy_pct", self.r)

    def test_has_paper_yield(self):
        self.assertIn("paper_yield_pct", self.r)

    def test_has_true_total_apy(self):
        self.assertIn("true_total_apy_pct", self.r)

    def test_has_yield_quality_ratio(self):
        self.assertIn("yield_quality_ratio", self.r)

    def test_has_token_dilution_cost(self):
        self.assertIn("token_dilution_cost_pct", self.r)

    def test_has_yield_label(self):
        self.assertIn("yield_label", self.r)

    def test_has_flags(self):
        self.assertIn("flags", self.r)

    def test_name_preserved(self):
        self.assertEqual(self.r["name"], "TestProtocol")


# ===========================================================================
# 4. real_apy_pct calculation
# ===========================================================================

class TestRealAPY(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _real(self, fee, inflation) -> float:
        p = _proto(fee_revenue_apy_pct=fee, inflation_rate_pct=inflation)
        return self.a.analyze([p], NO_LOG)["results"][0]["real_apy_pct"]

    def test_real_apy_basic(self):
        self.assertAlmostEqual(self._real(5.0, 2.0), 3.0, places=4)

    def test_real_apy_zero_inflation(self):
        self.assertAlmostEqual(self._real(8.0, 0.0), 8.0, places=4)

    def test_real_apy_negative_when_inflation_exceeds_fee(self):
        self.assertLess(self._real(2.0, 5.0), 0.0)

    def test_real_apy_zero_when_equal(self):
        self.assertAlmostEqual(self._real(4.0, 4.0), 0.0, places=4)

    def test_real_apy_high_fee(self):
        self.assertAlmostEqual(self._real(20.0, 3.0), 17.0, places=4)

    def test_real_apy_is_float(self):
        r = self._real(5.0, 2.0)
        self.assertIsInstance(r, float)

    def test_real_apy_zero_fee(self):
        self.assertAlmostEqual(self._real(0.0, 2.0), -2.0, places=4)

    def test_real_apy_both_zero(self):
        self.assertAlmostEqual(self._real(0.0, 0.0), 0.0, places=4)


# ===========================================================================
# 5. paper_yield_pct calculation
# ===========================================================================

class TestPaperYield(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _paper(self, emission, price_change) -> float:
        p = _proto(
            token_emission_apy_pct=emission,
            token_price_change_30d_pct=price_change,
        )
        return self.a.analyze([p], NO_LOG)["results"][0]["paper_yield_pct"]

    def test_paper_yield_flat_price(self):
        # emission 10%, price +0% → factor=1.0 → paper=10%
        self.assertAlmostEqual(self._paper(10.0, 0.0), 10.0, places=4)

    def test_paper_yield_price_up(self):
        # emission 10%, price +10% → factor=1.1 → paper=11%
        self.assertAlmostEqual(self._paper(10.0, 10.0), 11.0, places=4)

    def test_paper_yield_price_down(self):
        # emission 10%, price -50% → factor=0.5 → paper=5%
        self.assertAlmostEqual(self._paper(10.0, -50.0), 5.0, places=4)

    def test_paper_yield_token_collapsed_floor_zero(self):
        # emission 10%, price -100% → factor=0 → paper=0
        result = self._paper(10.0, -100.0)
        self.assertGreaterEqual(result, 0.0)

    def test_paper_yield_zero_emission(self):
        self.assertAlmostEqual(self._paper(0.0, 50.0), 0.0, places=4)

    def test_paper_yield_non_negative(self):
        # Even with severe price drop, should not be negative
        result = self._paper(5.0, -200.0)
        self.assertGreaterEqual(result, 0.0)

    def test_paper_yield_is_float(self):
        result = self._paper(5.0, 10.0)
        self.assertIsInstance(result, float)

    def test_paper_yield_price_doubled(self):
        # emission 10%, price +100% → factor=2.0 → paper=20%
        self.assertAlmostEqual(self._paper(10.0, 100.0), 20.0, places=4)


# ===========================================================================
# 6. true_total_apy_pct
# ===========================================================================

class TestTrueTotalAPY(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_true_total_is_sum_of_real_and_paper(self):
        p = _proto(fee_revenue_apy_pct=5.0, inflation_rate_pct=2.0,
                   token_emission_apy_pct=8.0, token_price_change_30d_pct=0.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        expected = r["real_apy_pct"] + r["paper_yield_pct"]
        self.assertAlmostEqual(r["true_total_apy_pct"], expected, places=4)

    def test_true_total_can_be_negative(self):
        # real_apy very negative, paper_yield zero
        p = _proto(fee_revenue_apy_pct=0.0, inflation_rate_pct=20.0,
                   token_emission_apy_pct=0.0, token_price_change_30d_pct=0.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertLess(r["true_total_apy_pct"], 0.0)

    def test_true_total_is_float(self):
        r = self.a.analyze([_proto()], NO_LOG)["results"][0]
        self.assertIsInstance(r["true_total_apy_pct"], float)

    def test_pure_fee_protocol_true_total_equals_real(self):
        p = _proto(token_emission_apy_pct=0.0, inflation_rate_pct=0.0,
                   fee_revenue_apy_pct=7.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["true_total_apy_pct"], r["real_apy_pct"], places=4)


# ===========================================================================
# 7. yield_quality_ratio
# ===========================================================================

class TestYieldQualityRatio(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _ratio(self, fee, inflation, emission, price_change) -> float:
        p = _proto(fee_revenue_apy_pct=fee, inflation_rate_pct=inflation,
                   token_emission_apy_pct=emission,
                   token_price_change_30d_pct=price_change)
        return self.a.analyze([p], NO_LOG)["results"][0]["yield_quality_ratio"]

    def test_ratio_in_0_1(self):
        r = self._ratio(5.0, 2.0, 5.0, 0.0)
        self.assertGreaterEqual(r, 0.0)
        self.assertLessEqual(r, 1.0)

    def test_pure_fee_ratio_high(self):
        # Only fee revenue, no emissions, no inflation → ratio should be 1.0
        r = self._ratio(10.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_pure_emissions_ratio_low(self):
        # Only emissions, no fees, but some inflation
        r = self._ratio(0.0, 5.0, 20.0, 0.0)
        # real_apy = -5, paper = 20, true = 15, quality = 0
        self.assertAlmostEqual(r, 0.0, places=4)

    def test_zero_total_yields_zero_ratio(self):
        # Zero everything
        r = self._ratio(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(r, 0.0)

    def test_negative_total_yields_zero_ratio(self):
        r = self._ratio(0.0, 20.0, 0.0, 0.0)
        self.assertEqual(r, 0.0)

    def test_mixed_yields_partial_ratio(self):
        # real = 3, paper = 7, true = 10, ratio = 0.3
        r = self._ratio(5.0, 2.0, 7.0, 0.0)
        self.assertAlmostEqual(r, 0.3, places=3)

    def test_ratio_is_float(self):
        r = self._ratio(5.0, 2.0, 5.0, 0.0)
        self.assertIsInstance(r, float)


# ===========================================================================
# 8. token_dilution_cost_pct
# ===========================================================================

class TestTokenDilutionCost(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _dilution(self, inflation) -> float:
        p = _proto(inflation_rate_pct=inflation)
        return self.a.analyze([p], NO_LOG)["results"][0]["token_dilution_cost_pct"]

    def test_dilution_equals_inflation(self):
        self.assertAlmostEqual(self._dilution(5.0), 5.0, places=4)

    def test_dilution_zero(self):
        self.assertAlmostEqual(self._dilution(0.0), 0.0, places=4)

    def test_dilution_high(self):
        self.assertAlmostEqual(self._dilution(50.0), 50.0, places=4)


# ===========================================================================
# 9. Yield labels
# ===========================================================================

class TestYieldLabel(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _label(self, fee, inflation, emission, price_change) -> str:
        p = _proto(fee_revenue_apy_pct=fee, inflation_rate_pct=inflation,
                   token_emission_apy_pct=emission,
                   token_price_change_30d_pct=price_change)
        return self.a.analyze([p], NO_LOG)["results"][0]["yield_label"]

    def test_genuine_yield_label(self):
        # High real yield, minimal emissions → ratio ≥ 0.8
        label = self._label(fee=10.0, inflation=0.0, emission=1.0, price_change=0.0)
        self.assertEqual(label, "GENUINE_YIELD")

    def test_illusory_label(self):
        # Mostly emissions with negative real yield
        label = self._label(fee=0.0, inflation=10.0, emission=30.0, price_change=0.0)
        self.assertEqual(label, "ILLUSORY")

    def test_label_is_string(self):
        label = self._label(5.0, 2.0, 5.0, 0.0)
        self.assertIsInstance(label, str)

    def test_label_in_valid_set(self):
        label = self._label(5.0, 2.0, 5.0, 0.0)
        valid = {"GENUINE_YIELD", "MOSTLY_REAL", "MIXED", "MOSTLY_EMISSIONS", "ILLUSORY"}
        self.assertIn(label, valid)

    def test_mostly_emissions_label(self):
        # Very small real portion
        label = self._label(fee=1.0, inflation=0.0, emission=20.0, price_change=0.0)
        self.assertIn(label, {"MOSTLY_EMISSIONS", "ILLUSORY"})


# ===========================================================================
# 10. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def _flags(self, **kwargs) -> list:
        p = _proto(**kwargs)
        return self.a.analyze([p], NO_LOG)["results"][0]["flags"]

    # NEGATIVE_REAL_YIELD
    def test_negative_real_yield_flag(self):
        flags = self._flags(fee_revenue_apy_pct=1.0, inflation_rate_pct=5.0)
        self.assertIn("NEGATIVE_REAL_YIELD", flags)

    def test_no_negative_real_yield_when_positive(self):
        flags = self._flags(fee_revenue_apy_pct=8.0, inflation_rate_pct=2.0)
        self.assertNotIn("NEGATIVE_REAL_YIELD", flags)

    def test_negative_real_yield_boundary(self):
        # Exactly zero → should NOT flag
        flags = self._flags(fee_revenue_apy_pct=3.0, inflation_rate_pct=3.0)
        self.assertNotIn("NEGATIVE_REAL_YIELD", flags)

    # TOKEN_COLLAPSE
    def test_token_collapse_flag(self):
        flags = self._flags(token_price_change_30d_pct=-50.0)
        self.assertIn("TOKEN_COLLAPSE", flags)

    def test_no_token_collapse_moderate_drop(self):
        flags = self._flags(token_price_change_30d_pct=-30.0)
        self.assertNotIn("TOKEN_COLLAPSE", flags)

    def test_no_token_collapse_flat(self):
        flags = self._flags(token_price_change_30d_pct=0.0)
        self.assertNotIn("TOKEN_COLLAPSE", flags)

    def test_token_collapse_boundary(self):
        flags = self._flags(token_price_change_30d_pct=-40.1)
        self.assertIn("TOKEN_COLLAPSE", flags)

    # EMISSION_DOMINANT
    def test_emission_dominant_flag(self):
        # emission 90%, fee 10% of gross → dominant
        flags = self._flags(fee_revenue_apy_pct=1.0, token_emission_apy_pct=9.0)
        self.assertIn("EMISSION_DOMINANT", flags)

    def test_no_emission_dominant_balanced(self):
        flags = self._flags(fee_revenue_apy_pct=5.0, token_emission_apy_pct=5.0)
        self.assertNotIn("EMISSION_DOMINANT", flags)

    def test_no_emission_dominant_fee_heavy(self):
        flags = self._flags(fee_revenue_apy_pct=8.0, token_emission_apy_pct=1.0)
        self.assertNotIn("EMISSION_DOMINANT", flags)

    # GENUINE_REVENUE
    def test_genuine_revenue_flag(self):
        flags = self._flags(fee_revenue_apy_pct=7.0)
        self.assertIn("GENUINE_REVENUE", flags)

    def test_no_genuine_revenue_low_fee(self):
        flags = self._flags(fee_revenue_apy_pct=3.0)
        self.assertNotIn("GENUINE_REVENUE", flags)

    def test_genuine_revenue_exactly_at_threshold(self):
        flags = self._flags(fee_revenue_apy_pct=5.1)
        self.assertIn("GENUINE_REVENUE", flags)

    # MISLEADING_APY
    def test_misleading_apy_flag(self):
        # advertised=20, true≈3 → diff=17, ratio=0.85 > 0.5 → misleading
        flags = self._flags(
            advertised_apy_pct=20.0,
            fee_revenue_apy_pct=3.0,
            token_emission_apy_pct=0.0,
            inflation_rate_pct=0.0,
        )
        self.assertIn("MISLEADING_APY", flags)

    def test_no_misleading_apy_when_accurate(self):
        flags = self._flags(
            advertised_apy_pct=7.0,
            fee_revenue_apy_pct=5.0,
            token_emission_apy_pct=2.0,
            inflation_rate_pct=0.0,
            token_price_change_30d_pct=0.0,
        )
        self.assertNotIn("MISLEADING_APY", flags)

    def test_flags_is_list(self):
        flags = self._flags()
        self.assertIsInstance(flags, list)

    def test_multiple_flags_possible(self):
        flags = self._flags(
            fee_revenue_apy_pct=0.5,
            inflation_rate_pct=10.0,
            token_emission_apy_pct=20.0,
            token_price_change_30d_pct=-60.0,
            advertised_apy_pct=40.0,
        )
        self.assertIn("NEGATIVE_REAL_YIELD", flags)
        self.assertIn("TOKEN_COLLAPSE", flags)


# ===========================================================================
# 11. Aggregate calculations
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_best_real_yield_protocol(self):
        protocols = [
            _proto(name="High", fee_revenue_apy_pct=10.0, inflation_rate_pct=0.0),
            _proto(name="Low", fee_revenue_apy_pct=1.0, inflation_rate_pct=0.0),
        ]
        agg = self.a.analyze(protocols, NO_LOG)["aggregates"]
        self.assertEqual(agg["best_real_yield"], "High")

    def test_worst_real_yield_protocol(self):
        protocols = [
            _proto(name="High", fee_revenue_apy_pct=10.0, inflation_rate_pct=0.0),
            _proto(name="Low", fee_revenue_apy_pct=1.0, inflation_rate_pct=0.0),
        ]
        agg = self.a.analyze(protocols, NO_LOG)["aggregates"]
        self.assertEqual(agg["worst_real_yield"], "Low")

    def test_average_yield_quality_ratio(self):
        protocols = [
            _proto(name="A", fee_revenue_apy_pct=10.0, inflation_rate_pct=0.0,
                   token_emission_apy_pct=0.0),
            _proto(name="B", fee_revenue_apy_pct=0.0, inflation_rate_pct=5.0,
                   token_emission_apy_pct=0.0),
        ]
        r = self.a.analyze(protocols, NO_LOG)
        ratios = [res["yield_quality_ratio"] for res in r["results"]]
        expected_avg = sum(ratios) / len(ratios)
        self.assertAlmostEqual(r["aggregates"]["average_yield_quality_ratio"], expected_avg, places=4)

    def test_average_true_apy(self):
        protocols = [
            _proto(name="A", fee_revenue_apy_pct=5.0, inflation_rate_pct=0.0,
                   token_emission_apy_pct=5.0, token_price_change_30d_pct=0.0),
            _proto(name="B", fee_revenue_apy_pct=3.0, inflation_rate_pct=1.0,
                   token_emission_apy_pct=2.0, token_price_change_30d_pct=0.0),
        ]
        r = self.a.analyze(protocols, NO_LOG)
        apys = [res["true_total_apy_pct"] for res in r["results"]]
        expected_avg = sum(apys) / len(apys)
        self.assertAlmostEqual(r["aggregates"]["average_true_apy"], expected_avg, places=4)

    def test_genuine_yield_count(self):
        protocols = [
            _proto(name="Genuine", fee_revenue_apy_pct=10.0, inflation_rate_pct=0.0,
                   token_emission_apy_pct=0.5),
            _proto(name="Emissions", fee_revenue_apy_pct=0.0, inflation_rate_pct=5.0,
                   token_emission_apy_pct=20.0),
        ]
        r = self.a.analyze(protocols, NO_LOG)
        genuine_count = sum(
            1 for res in r["results"] if res["yield_label"] == "GENUINE_YIELD"
        )
        self.assertEqual(r["aggregates"]["genuine_yield_count"], genuine_count)

    def test_single_protocol_best_equals_worst(self):
        r = self.a.analyze([_proto(name="Solo")], NO_LOG)
        agg = r["aggregates"]
        self.assertEqual(agg["best_real_yield"], "Solo")
        self.assertEqual(agg["worst_real_yield"], "Solo")


# ===========================================================================
# 12. Ring-buffer log
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_yield_log.json")

    def test_log_created(self):
        self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_protocol_count(self):
        self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIn("protocol_count", data[0])

    def test_ring_buffer_cap(self):
        for _ in range(105):
            self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_no_log_when_write_log_false(self):
        self.a.analyze([_proto()], {"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_multiple_entries_accumulate(self):
        for _ in range(3):
            self.a.analyze([_proto()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)


# ===========================================================================
# 13. Helper functions
# ===========================================================================

class TestHelpers(unittest.TestCase):
    def test_clamp_ratio_within(self):
        self.assertEqual(_clamp_ratio(0.5), 0.5)

    def test_clamp_ratio_below_zero(self):
        self.assertEqual(_clamp_ratio(-0.1), 0.0)

    def test_clamp_ratio_above_one(self):
        self.assertEqual(_clamp_ratio(1.5), 1.0)

    def test_atomic_log_creates_file(self):
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "test.json")
        _atomic_log(log_path, {"x": 1})
        self.assertTrue(os.path.exists(log_path))

    def test_atomic_log_appends_entries(self):
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "test.json")
        _atomic_log(log_path, {"a": 1})
        _atomic_log(log_path, {"b": 2})
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_atomic_log_ring_buffer(self):
        from spa_core.analytics.protocol_real_yield_vs_paper_yield_analyzer import _LOG_CAP
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "test.json")
        for i in range(_LOG_CAP + 15):
            _atomic_log(log_path, {"i": i})
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)


# ===========================================================================
# 14. Edge cases and missing fields
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_missing_name_defaults_unknown(self):
        p = {k: v for k, v in _proto().items() if k != "name"}
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertEqual(r["name"], "unknown")

    def test_missing_inflation_defaults_zero(self):
        p = {k: v for k, v in _proto().items() if k != "inflation_rate_pct"}
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertIsNotNone(r["real_apy_pct"])

    def test_zero_advertised_apy_no_crash(self):
        p = _proto(advertised_apy_pct=0.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertIsNotNone(r["yield_label"])

    def test_extreme_high_emission_no_crash(self):
        p = _proto(token_emission_apy_pct=1000.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertIsNotNone(r["paper_yield_pct"])

    def test_negative_inflation_increases_real_apy(self):
        p = _proto(fee_revenue_apy_pct=5.0, inflation_rate_pct=-2.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        # real = 5 - (-2) = 7
        self.assertAlmostEqual(r["real_apy_pct"], 7.0, places=4)

    def test_multiple_protocols_all_analyzed(self):
        protocols = [_proto(name=f"P{i}") for i in range(8)]
        r = self.a.analyze(protocols, NO_LOG)
        self.assertEqual(len(r["results"]), 8)

    def test_large_batch_no_crash(self):
        protocols = [_proto() for _ in range(50)]
        r = self.a.analyze(protocols, NO_LOG)
        self.assertEqual(len(r["results"]), 50)

    def test_zero_tvl_no_crash(self):
        p = _proto(tvl_usd=0.0)
        r = self.a.analyze([p], NO_LOG)
        self.assertEqual(len(r["results"]), 1)

    def test_very_high_price_change_positive(self):
        p = _proto(token_price_change_30d_pct=500.0, token_emission_apy_pct=10.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        # paper yield should be significantly amplified
        self.assertGreater(r["paper_yield_pct"], 10.0)

    def test_config_none_defaults(self):
        r = self.a.analyze([], None)
        self.assertIsInstance(r, dict)


# ===========================================================================
# 15. Timestamp
# ===========================================================================

class TestTimestamp(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_timestamp_is_positive(self):
        r = self.a.analyze([], NO_LOG)
        self.assertGreater(r["timestamp"], 0.0)

    def test_timestamp_is_float(self):
        r = self.a.analyze([], NO_LOG)
        self.assertIsInstance(r["timestamp"], float)

    def test_timestamp_monotone(self):
        import time
        r1 = self.a.analyze([], NO_LOG)
        time.sleep(0.01)
        r2 = self.a.analyze([], NO_LOG)
        self.assertGreaterEqual(r2["timestamp"], r1["timestamp"])


# ===========================================================================
# 16. Protocol name preservation
# ===========================================================================

class TestNamePreservation(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_name_preserved_in_result(self):
        p = _proto(name="Aave")
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertEqual(r["name"], "Aave")

    def test_name_preserved_in_aggregates_best(self):
        protocols = [
            _proto(name="Alpha", fee_revenue_apy_pct=15.0, inflation_rate_pct=0.0),
            _proto(name="Beta", fee_revenue_apy_pct=2.0, inflation_rate_pct=0.0),
        ]
        agg = self.a.analyze(protocols, NO_LOG)["aggregates"]
        self.assertEqual(agg["best_real_yield"], "Alpha")
        self.assertEqual(agg["worst_real_yield"], "Beta")


# ===========================================================================
# 17. Advertised APY field
# ===========================================================================

class TestAdvertisedAPY(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolRealYieldVsPaperYieldAnalyzer()

    def test_advertised_preserved(self):
        p = _proto(advertised_apy_pct=25.0)
        r = self.a.analyze([p], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["advertised_apy_pct"], 25.0, places=4)

    def test_advertised_zero_no_misleading_flag(self):
        p = _proto(advertised_apy_pct=0.0)
        flags = self.a.analyze([p], NO_LOG)["results"][0]["flags"]
        # Zero advertised → no MISLEADING_APY (guarded by advertised > 0 check)
        self.assertNotIn("MISLEADING_APY", flags)


if __name__ == "__main__":
    unittest.main()
