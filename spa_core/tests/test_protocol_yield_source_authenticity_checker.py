"""
Tests for MP-957: ProtocolYieldSourceAuthenticityChecker
Run: python3 -m unittest spa_core.tests.test_protocol_yield_source_authenticity_checker -v
"""

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_yield_source_authenticity_checker import (
    ProtocolYieldSourceAuthenticityChecker,
)


def _make_protocol(**kwargs):
    """Build a minimal valid protocol dict."""
    base = {
        "name": "TestProtocol",
        "reported_apy_pct": 8.0,
        "fee_revenue_apy_pct": 5.0,
        "token_emission_apy_pct": 2.0,
        "external_incentive_apy_pct": 1.0,
        "points_apy_pct": 0.0,
        "total_tvl_usd": 100_000_000.0,
        "token_fully_diluted_valuation_usd": 500_000_000.0,
        "emission_rate_pct_fdv_annual": 10.0,
        "has_revenue_sharing": True,
        "days_since_launch": 365,
        "audit_count": 2,
    }
    base.update(kwargs)
    return base


class TestProtocolYieldAuthenticityCheckerInit(unittest.TestCase):
    def test_instantiation(self):
        c = ProtocolYieldSourceAuthenticityChecker()
        self.assertIsInstance(c, ProtocolYieldSourceAuthenticityChecker)

    def test_check_method_exists(self):
        c = ProtocolYieldSourceAuthenticityChecker()
        self.assertTrue(callable(c.check))


class TestCheckReturnStructure(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()
        self.proto = _make_protocol()

    def test_returns_dict(self):
        result = self.checker.check([self.proto], {})
        self.assertIsInstance(result, dict)

    def test_has_timestamp(self):
        result = self.checker.check([self.proto], {})
        self.assertIn("timestamp", result)

    def test_has_protocols_checked(self):
        result = self.checker.check([self.proto], {})
        self.assertIn("protocols_checked", result)

    def test_has_aggregates(self):
        result = self.checker.check([self.proto], {})
        self.assertIn("aggregates", result)

    def test_has_total_count(self):
        result = self.checker.check([self.proto], {})
        self.assertIn("total_count", result)

    def test_total_count_single(self):
        result = self.checker.check([self.proto], {})
        self.assertEqual(result["total_count"], 1)

    def test_total_count_multiple(self):
        result = self.checker.check([self.proto, self.proto], {})
        self.assertEqual(result["total_count"], 2)

    def test_empty_protocols(self):
        result = self.checker.check([], {})
        self.assertEqual(result["total_count"], 0)


class TestProtocolItemStructure(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()
        self.result = self.checker.check([_make_protocol()], {})
        self.item = self.result["protocols_checked"][0]

    def test_has_name(self):
        self.assertIn("name", self.item)

    def test_has_reported_apy_pct(self):
        self.assertIn("reported_apy_pct", self.item)

    def test_has_fee_revenue_apy_pct(self):
        self.assertIn("fee_revenue_apy_pct", self.item)

    def test_has_token_emission_apy_pct(self):
        self.assertIn("token_emission_apy_pct", self.item)

    def test_has_external_incentive_apy_pct(self):
        self.assertIn("external_incentive_apy_pct", self.item)

    def test_has_points_apy_pct(self):
        self.assertIn("points_apy_pct", self.item)

    def test_has_total_tvl_usd(self):
        self.assertIn("total_tvl_usd", self.item)

    def test_has_fdv(self):
        self.assertIn("token_fully_diluted_valuation_usd", self.item)

    def test_has_emission_rate(self):
        self.assertIn("emission_rate_pct_fdv_annual", self.item)

    def test_has_has_revenue_sharing(self):
        self.assertIn("has_revenue_sharing", self.item)

    def test_has_days_since_launch(self):
        self.assertIn("days_since_launch", self.item)

    def test_has_audit_count(self):
        self.assertIn("audit_count", self.item)

    def test_has_derived(self):
        self.assertIn("derived", self.item)

    def test_has_label(self):
        self.assertIn("label", self.item)

    def test_has_flags(self):
        self.assertIn("flags", self.item)

    def test_flags_is_list(self):
        self.assertIsInstance(self.item["flags"], list)


class TestDerivedMetrics(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_real_yield_equals_fee_revenue(self):
        proto = _make_protocol(fee_revenue_apy_pct=4.5)
        result = self.checker.check([proto], {})
        self.assertAlmostEqual(
            result["protocols_checked"][0]["derived"]["real_yield_pct"], 4.5
        )

    def test_inflation_yield_is_emission_plus_incentive(self):
        proto = _make_protocol(token_emission_apy_pct=3.0, external_incentive_apy_pct=2.0)
        result = self.checker.check([proto], {})
        self.assertAlmostEqual(
            result["protocols_checked"][0]["derived"]["inflation_yield_pct"], 5.0
        )

    def test_sustainability_ratio_range(self):
        proto = _make_protocol()
        result = self.checker.check([proto], {})
        ratio = result["protocols_checked"][0]["derived"]["sustainability_ratio"]
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_sustainability_ratio_pure_real(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=5.0,
            token_emission_apy_pct=0.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        ratio = result["protocols_checked"][0]["derived"]["sustainability_ratio"]
        self.assertAlmostEqual(ratio, 1.0, places=3)

    def test_sustainability_ratio_pure_emission(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=0.0,
            token_emission_apy_pct=5.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        ratio = result["protocols_checked"][0]["derived"]["sustainability_ratio"]
        self.assertAlmostEqual(ratio, 0.0, places=3)

    def test_fdv_to_tvl_ratio(self):
        proto = _make_protocol(
            total_tvl_usd=100_000_000.0,
            token_fully_diluted_valuation_usd=500_000_000.0,
        )
        result = self.checker.check([proto], {})
        self.assertAlmostEqual(
            result["protocols_checked"][0]["derived"]["fdv_to_tvl_ratio"], 5.0
        )

    def test_fdv_to_tvl_zero_tvl(self):
        proto = _make_protocol(total_tvl_usd=0.0)
        result = self.checker.check([proto], {})
        self.assertEqual(
            result["protocols_checked"][0]["derived"]["fdv_to_tvl_ratio"], 0.0
        )

    def test_yield_inflation_pressure_positive(self):
        proto = _make_protocol(
            total_tvl_usd=100_000_000.0,
            token_fully_diluted_valuation_usd=1_000_000_000.0,
            emission_rate_pct_fdv_annual=20.0,
        )
        result = self.checker.check([proto], {})
        pressure = result["protocols_checked"][0]["derived"]["yield_inflation_pressure"]
        self.assertGreater(pressure, 0)

    def test_yield_inflation_pressure_zero_fdv(self):
        proto = _make_protocol(token_fully_diluted_valuation_usd=0.0)
        result = self.checker.check([proto], {})
        pressure = result["protocols_checked"][0]["derived"]["yield_inflation_pressure"]
        self.assertEqual(pressure, 0.0)

    def test_derived_keys_present(self):
        result = self.checker.check([_make_protocol()], {})
        derived = result["protocols_checked"][0]["derived"]
        for key in [
            "real_yield_pct",
            "inflation_yield_pct",
            "sustainability_ratio",
            "fdv_to_tvl_ratio",
            "yield_inflation_pressure",
        ]:
            self.assertIn(key, derived)


class TestAuthenticityLabels(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_real_yield_label(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=8.0,
            token_emission_apy_pct=0.5,
            external_incentive_apy_pct=0.5,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertEqual(result["protocols_checked"][0]["label"], "REAL_YIELD")

    def test_pure_emission_label(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=0.0,
            token_emission_apy_pct=10.0,
            external_incentive_apy_pct=2.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertEqual(result["protocols_checked"][0]["label"], "PURE_EMISSION")

    def test_points_based_label(self):
        proto = _make_protocol(
            reported_apy_pct=10.0,
            fee_revenue_apy_pct=1.0,
            token_emission_apy_pct=1.0,
            external_incentive_apy_pct=1.0,
            points_apy_pct=7.0,
        )
        result = self.checker.check([proto], {})
        self.assertEqual(result["protocols_checked"][0]["label"], "POINTS_BASED")

    def test_mostly_real_label(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=6.0,
            token_emission_apy_pct=2.0,
            external_incentive_apy_pct=0.5,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertIn(
            result["protocols_checked"][0]["label"],
            ("REAL_YIELD", "MOSTLY_REAL")
        )

    def test_mixed_label(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=4.0,
            token_emission_apy_pct=4.0,
            external_incentive_apy_pct=2.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertIn(
            result["protocols_checked"][0]["label"],
            ("MIXED", "MOSTLY_REAL", "MOSTLY_INCENTIVIZED")
        )

    def test_mostly_incentivized_label(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=1.0,
            token_emission_apy_pct=6.0,
            external_incentive_apy_pct=3.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertIn(
            result["protocols_checked"][0]["label"],
            ("MOSTLY_INCENTIVIZED", "PURE_EMISSION")
        )

    def test_label_is_valid_string(self):
        valid = {
            "REAL_YIELD", "MOSTLY_REAL", "MIXED",
            "MOSTLY_INCENTIVIZED", "PURE_EMISSION", "POINTS_BASED"
        }
        result = self.checker.check([_make_protocol()], {})
        label = result["protocols_checked"][0]["label"]
        self.assertIn(label, valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_unsustainable_flag(self):
        proto = _make_protocol(emission_rate_pct_fdv_annual=60.0)
        result = self.checker.check([proto], {})
        self.assertIn("UNSUSTAINABLE", result["protocols_checked"][0]["flags"])

    def test_ponzi_pattern_flag(self):
        proto = _make_protocol(
            total_tvl_usd=10_000_000.0,
            token_fully_diluted_valuation_usd=10_000_000_000.0,
            emission_rate_pct_fdv_annual=200.0,
        )
        result = self.checker.check([proto], {})
        self.assertIn("PONZI_PATTERN", result["protocols_checked"][0]["flags"])

    def test_new_protocol_flag(self):
        proto = _make_protocol(days_since_launch=30)
        result = self.checker.check([proto], {})
        self.assertIn("NEW_PROTOCOL", result["protocols_checked"][0]["flags"])

    def test_revenue_sharing_flag(self):
        proto = _make_protocol(has_revenue_sharing=True)
        result = self.checker.check([proto], {})
        self.assertIn("REVENUE_SHARING", result["protocols_checked"][0]["flags"])

    def test_audited_flag(self):
        proto = _make_protocol(audit_count=1)
        result = self.checker.check([proto], {})
        self.assertIn("AUDITED", result["protocols_checked"][0]["flags"])

    def test_high_fdv_tvl_flag(self):
        proto = _make_protocol(
            total_tvl_usd=10_000_000.0,
            token_fully_diluted_valuation_usd=200_000_000.0,
        )
        result = self.checker.check([proto], {})
        self.assertIn("HIGH_FDV_TVL", result["protocols_checked"][0]["flags"])

    def test_no_new_protocol_flag_old(self):
        proto = _make_protocol(days_since_launch=365)
        result = self.checker.check([proto], {})
        self.assertNotIn("NEW_PROTOCOL", result["protocols_checked"][0]["flags"])

    def test_no_revenue_sharing_flag(self):
        proto = _make_protocol(has_revenue_sharing=False)
        result = self.checker.check([proto], {})
        self.assertNotIn("REVENUE_SHARING", result["protocols_checked"][0]["flags"])

    def test_no_audited_flag_zero_audits(self):
        proto = _make_protocol(audit_count=0)
        result = self.checker.check([proto], {})
        self.assertNotIn("AUDITED", result["protocols_checked"][0]["flags"])

    def test_no_high_fdv_tvl_flag(self):
        proto = _make_protocol(
            total_tvl_usd=100_000_000.0,
            token_fully_diluted_valuation_usd=500_000_000.0,
        )
        result = self.checker.check([proto], {})
        self.assertNotIn("HIGH_FDV_TVL", result["protocols_checked"][0]["flags"])

    def test_unsustainable_boundary(self):
        # exactly 50% — not >50
        proto = _make_protocol(emission_rate_pct_fdv_annual=50.0)
        result = self.checker.check([proto], {})
        self.assertNotIn("UNSUSTAINABLE", result["protocols_checked"][0]["flags"])

    def test_new_protocol_boundary_exactly_90(self):
        # exactly 90 — not <90
        proto = _make_protocol(days_since_launch=90)
        result = self.checker.check([proto], {})
        self.assertNotIn("NEW_PROTOCOL", result["protocols_checked"][0]["flags"])

    def test_new_protocol_boundary_89(self):
        proto = _make_protocol(days_since_launch=89)
        result = self.checker.check([proto], {})
        self.assertIn("NEW_PROTOCOL", result["protocols_checked"][0]["flags"])

    def test_high_fdv_tvl_boundary_exactly_10(self):
        proto = _make_protocol(
            total_tvl_usd=100_000_000.0,
            token_fully_diluted_valuation_usd=1_000_000_000.0,
        )
        result = self.checker.check([proto], {})
        self.assertNotIn("HIGH_FDV_TVL", result["protocols_checked"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_empty_aggregates(self):
        result = self.checker.check([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["most_authentic"])
        self.assertIsNone(agg["least_authentic"])
        self.assertEqual(agg["average_real_yield_pct"], 0.0)
        self.assertEqual(agg["real_yield_protocols_count"], 0)
        self.assertEqual(agg["ponzi_pattern_count"], 0)

    def test_most_authentic_highest_ratio(self):
        p1 = _make_protocol(
            name="RealProt",
            fee_revenue_apy_pct=9.0,
            token_emission_apy_pct=1.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        p2 = _make_protocol(
            name="EmissionProt",
            fee_revenue_apy_pct=0.0,
            token_emission_apy_pct=10.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([p1, p2], {})
        self.assertEqual(result["aggregates"]["most_authentic"], "RealProt")

    def test_least_authentic_lowest_ratio(self):
        p1 = _make_protocol(
            name="RealProt",
            fee_revenue_apy_pct=9.0,
            token_emission_apy_pct=1.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        p2 = _make_protocol(
            name="PonziProt",
            fee_revenue_apy_pct=0.0,
            token_emission_apy_pct=10.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
        )
        result = self.checker.check([p1, p2], {})
        self.assertEqual(result["aggregates"]["least_authentic"], "PonziProt")

    def test_average_real_yield(self):
        p1 = _make_protocol(name="A", fee_revenue_apy_pct=4.0,
                            token_emission_apy_pct=0, external_incentive_apy_pct=0, points_apy_pct=0)
        p2 = _make_protocol(name="B", fee_revenue_apy_pct=6.0,
                            token_emission_apy_pct=0, external_incentive_apy_pct=0, points_apy_pct=0)
        result = self.checker.check([p1, p2], {})
        self.assertAlmostEqual(result["aggregates"]["average_real_yield_pct"], 5.0, places=2)

    def test_real_yield_protocols_count(self):
        p1 = _make_protocol(name="A", fee_revenue_apy_pct=8.0,
                            token_emission_apy_pct=1.0, external_incentive_apy_pct=0.5, points_apy_pct=0.0)
        p2 = _make_protocol(name="B", fee_revenue_apy_pct=0.0,
                            token_emission_apy_pct=10.0, external_incentive_apy_pct=0.0, points_apy_pct=0.0)
        result = self.checker.check([p1, p2], {})
        self.assertEqual(result["aggregates"]["real_yield_protocols_count"], 1)

    def test_ponzi_pattern_count(self):
        p1 = _make_protocol(
            name="PonziA",
            total_tvl_usd=5_000_000.0,
            token_fully_diluted_valuation_usd=10_000_000_000.0,
            emission_rate_pct_fdv_annual=200.0,
        )
        p2 = _make_protocol(name="Normal")
        result = self.checker.check([p1, p2], {})
        self.assertGreaterEqual(result["aggregates"]["ponzi_pattern_count"], 1)

    def test_aggregates_keys(self):
        result = self.checker.check([_make_protocol()], {})
        agg = result["aggregates"]
        for key in [
            "most_authentic", "least_authentic", "average_real_yield_pct",
            "real_yield_protocols_count", "ponzi_pattern_count"
        ]:
            self.assertIn(key, agg)


class TestInputValidation(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_non_list_raises(self):
        with self.assertRaises(TypeError):
            self.checker.check("not a list", {})

    def test_non_dict_config_raises(self):
        with self.assertRaises(TypeError):
            self.checker.check([], "not a dict")

    def test_none_protocols_raises(self):
        with self.assertRaises(TypeError):
            self.checker.check(None, {})

    def test_none_config_raises(self):
        with self.assertRaises(TypeError):
            self.checker.check([], None)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_all_zeros(self):
        proto = _make_protocol(
            fee_revenue_apy_pct=0.0,
            token_emission_apy_pct=0.0,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
            reported_apy_pct=0.0,
            total_tvl_usd=0.0,
            token_fully_diluted_valuation_usd=0.0,
            emission_rate_pct_fdv_annual=0.0,
        )
        result = self.checker.check([proto], {})
        self.assertIsNotNone(result)

    def test_empty_protocol_dict(self):
        result = self.checker.check([{}], {})
        self.assertEqual(result["total_count"], 1)

    def test_large_list(self):
        protos = [_make_protocol(name=f"P{i}") for i in range(50)]
        result = self.checker.check(protos, {})
        self.assertEqual(result["total_count"], 50)

    def test_name_preserved(self):
        proto = _make_protocol(name="UniqueProtocolName")
        result = self.checker.check([proto], {})
        self.assertEqual(result["protocols_checked"][0]["name"], "UniqueProtocolName")

    def test_has_revenue_sharing_preserved(self):
        proto = _make_protocol(has_revenue_sharing=True)
        result = self.checker.check([proto], {})
        self.assertTrue(result["protocols_checked"][0]["has_revenue_sharing"])

    def test_string_numeric_coercion(self):
        proto = _make_protocol(fee_revenue_apy_pct="4.5", token_emission_apy_pct="2.0")
        result = self.checker.check([proto], {})
        self.assertAlmostEqual(result["protocols_checked"][0]["derived"]["real_yield_pct"], 4.5)

    def test_config_extra_keys_ignored(self):
        result = self.checker.check([_make_protocol()], {"random_key": 123})
        self.assertIsNotNone(result)

    def test_very_high_fdv_no_crash(self):
        proto = _make_protocol(
            total_tvl_usd=1.0,
            token_fully_diluted_valuation_usd=1e15,
            emission_rate_pct_fdv_annual=100.0,
        )
        result = self.checker.check([proto], {})
        self.assertIsNotNone(result)

    def test_zero_emission_no_unsustainable(self):
        proto = _make_protocol(emission_rate_pct_fdv_annual=0.0)
        result = self.checker.check([proto], {})
        self.assertNotIn("UNSUSTAINABLE", result["protocols_checked"][0]["flags"])


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_log_file_created(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                self.assertTrue(os.path.exists(mod.LOG_PATH))
            finally:
                mod.LOG_PATH = orig

    def test_log_is_valid_json_list(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIsInstance(data, list)
            finally:
                mod.LOG_PATH = orig

    def test_log_entries_accumulate(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 2)
            finally:
                mod.LOG_PATH = orig

    def test_log_ring_buffer_cap(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = mod.LOG_PATH
            orig_cap = mod.LOG_CAP
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            mod.LOG_CAP = 5
            try:
                for _ in range(8):
                    self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertLessEqual(len(data), 5)
            finally:
                mod.LOG_PATH = orig_path
                mod.LOG_CAP = orig_cap

    def test_log_entry_has_ts(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIn("ts", data[0])
            finally:
                mod.LOG_PATH = orig

    def test_log_entry_has_aggregates(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIn("aggregates", data[0])
            finally:
                mod.LOG_PATH = orig

    def test_no_tmp_file_left_behind(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                self.checker.check([_make_protocol()], {})
                self.assertFalse(os.path.exists(mod.LOG_PATH + ".tmp"))
            finally:
                mod.LOG_PATH = orig

    def test_log_recovers_from_corrupt_file(self):
        import spa_core.analytics.protocol_yield_source_authenticity_checker as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_yield_auth_log.json")
            try:
                with open(mod.LOG_PATH, "w") as f:
                    f.write("NOT JSON {{{")
                self.checker.check([_make_protocol()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 1)
            finally:
                mod.LOG_PATH = orig


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_same_input_same_label(self):
        proto = _make_protocol()
        r1 = self.checker.check([proto], {})
        r2 = self.checker.check([proto], {})
        self.assertEqual(
            r1["protocols_checked"][0]["label"],
            r2["protocols_checked"][0]["label"],
        )

    def test_same_input_same_flags(self):
        proto = _make_protocol()
        r1 = self.checker.check([proto], {})
        r2 = self.checker.check([proto], {})
        self.assertEqual(
            r1["protocols_checked"][0]["flags"],
            r2["protocols_checked"][0]["flags"],
        )

    def test_same_input_same_sustainability(self):
        proto = _make_protocol()
        r1 = self.checker.check([proto], {})
        r2 = self.checker.check([proto], {})
        self.assertEqual(
            r1["protocols_checked"][0]["derived"]["sustainability_ratio"],
            r2["protocols_checked"][0]["derived"]["sustainability_ratio"],
        )


class TestRealWorldScenarios(unittest.TestCase):
    def setUp(self):
        self.checker = ProtocolYieldSourceAuthenticityChecker()

    def test_aave_like_protocol(self):
        # Aave: mostly real yield from fees
        proto = _make_protocol(
            name="Aave V3",
            reported_apy_pct=4.5,
            fee_revenue_apy_pct=4.2,
            token_emission_apy_pct=0.2,
            external_incentive_apy_pct=0.1,
            points_apy_pct=0.0,
            total_tvl_usd=10_000_000_000.0,
            token_fully_diluted_valuation_usd=2_000_000_000.0,
            emission_rate_pct_fdv_annual=3.0,
            has_revenue_sharing=False,
            days_since_launch=1500,
            audit_count=10,
        )
        result = self.checker.check([proto], {})
        item = result["protocols_checked"][0]
        self.assertIn(item["label"], ("REAL_YIELD", "MOSTLY_REAL"))
        self.assertIn("AUDITED", item["flags"])
        self.assertNotIn("NEW_PROTOCOL", item["flags"])

    def test_new_defi_farm_ponzi_like(self):
        # New protocol, high emissions relative to TVL/FDV
        proto = _make_protocol(
            name="NewFarm",
            reported_apy_pct=500.0,
            fee_revenue_apy_pct=0.5,
            token_emission_apy_pct=499.5,
            external_incentive_apy_pct=0.0,
            points_apy_pct=0.0,
            total_tvl_usd=1_000_000.0,
            token_fully_diluted_valuation_usd=100_000_000.0,
            emission_rate_pct_fdv_annual=200.0,
            has_revenue_sharing=False,
            days_since_launch=10,
            audit_count=0,
        )
        result = self.checker.check([proto], {})
        item = result["protocols_checked"][0]
        self.assertIn("PONZI_PATTERN", item["flags"])
        self.assertIn("NEW_PROTOCOL", item["flags"])
        self.assertIn("UNSUSTAINABLE", item["flags"])
        self.assertNotIn("AUDITED", item["flags"])

    def test_points_program_protocol(self):
        proto = _make_protocol(
            name="PointsProtocol",
            reported_apy_pct=20.0,
            fee_revenue_apy_pct=1.0,
            token_emission_apy_pct=2.0,
            external_incentive_apy_pct=1.0,
            points_apy_pct=16.0,
        )
        result = self.checker.check([proto], {})
        self.assertEqual(result["protocols_checked"][0]["label"], "POINTS_BASED")

    def test_multiple_protocols_aggregation(self):
        protos = [
            _make_protocol(name="RealA", fee_revenue_apy_pct=5.0, token_emission_apy_pct=0.5,
                           external_incentive_apy_pct=0.0, points_apy_pct=0.0),
            _make_protocol(name="RealB", fee_revenue_apy_pct=6.0, token_emission_apy_pct=0.3,
                           external_incentive_apy_pct=0.0, points_apy_pct=0.0),
            _make_protocol(name="PureEmit", fee_revenue_apy_pct=0.0, token_emission_apy_pct=8.0,
                           external_incentive_apy_pct=0.0, points_apy_pct=0.0),
        ]
        result = self.checker.check(protos, {})
        self.assertEqual(result["total_count"], 3)
        agg = result["aggregates"]
        self.assertEqual(agg["real_yield_protocols_count"], 2)
        self.assertAlmostEqual(agg["average_real_yield_pct"], (5.0 + 6.0 + 0.0) / 3, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
