"""
Tests for MP-956: DeFiInsuranceCoverageAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_insurance_coverage_analyzer -v
"""

import json
import os
import sys
import unittest
import tempfile

# Ensure project root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_insurance_coverage_analyzer import DeFiInsuranceCoverageAnalyzer


def _make_coverage(**kwargs):
    """Build a minimal valid coverage dict."""
    base = {
        "protocol_covered": "Aave V3",
        "coverage_amount_usd": 50000.0,
        "premium_annual_pct": 2.5,
        "coverage_type": "smart_contract",
        "provider": "Nexus Mutual",
        "tvl_covered_ratio": 0.8,
        "claim_history_count": 0,
        "coverage_capacity_ratio": 0.5,
        "days_remaining": 180,
        "excluded_risks": [],
    }
    base.update(kwargs)
    return base


class TestDeFiInsuranceCoverageAnalyzerInit(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiInsuranceCoverageAnalyzer()
        self.assertIsInstance(a, DeFiInsuranceCoverageAnalyzer)

    def test_analyze_method_exists(self):
        a = DeFiInsuranceCoverageAnalyzer()
        self.assertTrue(callable(a.analyze))


class TestAnalyzeReturnStructure(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()
        self.cov = _make_coverage()

    def test_returns_dict(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertIsInstance(result, dict)

    def test_has_timestamp(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertIn("timestamp", result)

    def test_has_coverages_analyzed(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertIn("coverages_analyzed", result)

    def test_has_aggregates(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertIn("aggregates", result)

    def test_has_total_count(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertIn("total_count", result)

    def test_total_count_matches_input(self):
        result = self.analyzer.analyze([self.cov], {})
        self.assertEqual(result["total_count"], 1)

    def test_multiple_coverages(self):
        result = self.analyzer.analyze([self.cov, self.cov], {})
        self.assertEqual(result["total_count"], 2)

    def test_empty_coverages(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["total_count"], 0)


class TestCoverageItemStructure(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()
        self.result = self.analyzer.analyze([_make_coverage()], {})
        self.item = self.result["coverages_analyzed"][0]

    def test_has_protocol_covered(self):
        self.assertIn("protocol_covered", self.item)

    def test_has_coverage_amount_usd(self):
        self.assertIn("coverage_amount_usd", self.item)

    def test_has_premium_annual_pct(self):
        self.assertIn("premium_annual_pct", self.item)

    def test_has_coverage_type(self):
        self.assertIn("coverage_type", self.item)

    def test_has_provider(self):
        self.assertIn("provider", self.item)

    def test_has_tvl_covered_ratio(self):
        self.assertIn("tvl_covered_ratio", self.item)

    def test_has_claim_history_count(self):
        self.assertIn("claim_history_count", self.item)

    def test_has_coverage_capacity_ratio(self):
        self.assertIn("coverage_capacity_ratio", self.item)

    def test_has_days_remaining(self):
        self.assertIn("days_remaining", self.item)

    def test_has_excluded_risks(self):
        self.assertIn("excluded_risks", self.item)

    def test_has_derived(self):
        self.assertIn("derived", self.item)

    def test_has_label(self):
        self.assertIn("label", self.item)

    def test_has_flags(self):
        self.assertIn("flags", self.item)

    def test_flags_is_list(self):
        self.assertIsInstance(self.item["flags"], list)

    def test_excluded_risks_is_list(self):
        self.assertIsInstance(self.item["excluded_risks"], list)


class TestDerivedMetrics(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_cost_per_1000_positive(self):
        item = self.analyzer.analyze([_make_coverage(coverage_amount_usd=10000, premium_annual_pct=2.0)], {})
        d = item["coverages_analyzed"][0]["derived"]
        self.assertGreater(d["cost_per_1000_coverage_usd"], 0)

    def test_cost_per_1000_zero_coverage(self):
        item = self.analyzer.analyze([_make_coverage(coverage_amount_usd=0)], {})
        d = item["coverages_analyzed"][0]["derived"]
        self.assertEqual(d["cost_per_1000_coverage_usd"], 0.0)

    def test_efficiency_score_range(self):
        item = self.analyzer.analyze([_make_coverage()], {})
        score = item["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_break_even_prob_equals_premium(self):
        cov = _make_coverage(premium_annual_pct=3.0)
        item = self.analyzer.analyze([cov], {})
        d = item["coverages_analyzed"][0]["derived"]
        self.assertAlmostEqual(d["break_even_loss_probability_pct"], 3.0, places=3)

    def test_implied_risk_less_than_premium(self):
        # Provider has margin, so implied < premium
        cov = _make_coverage(premium_annual_pct=4.0, provider="Nexus Mutual")
        item = self.analyzer.analyze([cov], {})
        d = item["coverages_analyzed"][0]["derived"]
        self.assertLess(d["implied_annual_risk_pct"], 4.0)

    def test_implied_risk_self_insured_zero(self):
        cov = _make_coverage(premium_annual_pct=0.0, provider="self_insured")
        item = self.analyzer.analyze([cov], {})
        d = item["coverages_analyzed"][0]["derived"]
        self.assertEqual(d["implied_annual_risk_pct"], 0.0)

    def test_efficiency_score_high_for_good_coverage(self):
        cov = _make_coverage(
            tvl_covered_ratio=1.0,
            premium_annual_pct=1.0,
            provider="Nexus Mutual",
            claim_history_count=0,
            coverage_capacity_ratio=0.2,
        )
        item = self.analyzer.analyze([cov], {})
        score = item["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"]
        self.assertGreater(score, 60)

    def test_efficiency_score_low_for_self_insured(self):
        cov = _make_coverage(provider="self_insured", premium_annual_pct=0.0)
        item = self.analyzer.analyze([cov], {})
        score = item["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"]
        self.assertLess(score, 60)


class TestCoverageLabels(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_uninsured_self_insured(self):
        cov = _make_coverage(provider="self_insured")
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(result["coverages_analyzed"][0]["label"], "UNINSURED")

    def test_uninsured_zero_coverage(self):
        cov = _make_coverage(coverage_amount_usd=0, provider="Nexus Mutual")
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(result["coverages_analyzed"][0]["label"], "UNINSURED")

    def test_excellent_label(self):
        cov = _make_coverage(
            tvl_covered_ratio=1.0,
            premium_annual_pct=1.0,
            provider="Nexus Mutual",
            claim_history_count=0,
            coverage_capacity_ratio=0.2,
            coverage_amount_usd=100000,
        )
        result = self.analyzer.analyze([cov], {})
        label = result["coverages_analyzed"][0]["label"]
        self.assertIn(label, ("EXCELLENT", "ADEQUATE"))  # high efficiency expected

    def test_minimal_label_low_ratio(self):
        cov = _make_coverage(tvl_covered_ratio=0.05, coverage_amount_usd=1000)
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(result["coverages_analyzed"][0]["label"], "MINIMAL")

    def test_partial_label(self):
        cov = _make_coverage(
            tvl_covered_ratio=0.35,
            premium_annual_pct=4.0,
            provider="InsurAce",
            claim_history_count=3,
            coverage_capacity_ratio=0.6,
        )
        result = self.analyzer.analyze([cov], {})
        self.assertIn(
            result["coverages_analyzed"][0]["label"],
            ("PARTIAL", "MINIMAL", "ADEQUATE")
        )

    def test_labels_are_valid_strings(self):
        valid = {"EXCELLENT", "ADEQUATE", "PARTIAL", "MINIMAL", "UNINSURED"}
        cov = _make_coverage()
        result = self.analyzer.analyze([cov], {})
        label = result["coverages_analyzed"][0]["label"]
        self.assertIn(label, valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_over_insured_flag(self):
        cov = _make_coverage(tvl_covered_ratio=2.0)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("OVER_INSURED", result["coverages_analyzed"][0]["flags"])

    def test_under_insured_flag(self):
        cov = _make_coverage(tvl_covered_ratio=0.3)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("UNDER_INSURED", result["coverages_analyzed"][0]["flags"])

    def test_premium_high_flag(self):
        cov = _make_coverage(premium_annual_pct=6.0)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("PREMIUM_HIGH", result["coverages_analyzed"][0]["flags"])

    def test_pool_near_capacity_flag(self):
        cov = _make_coverage(coverage_capacity_ratio=0.95)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("POOL_NEAR_CAPACITY", result["coverages_analyzed"][0]["flags"])

    def test_expired_soon_flag(self):
        cov = _make_coverage(days_remaining=15)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("EXPIRED_SOON", result["coverages_analyzed"][0]["flags"])

    def test_known_claim_risk_flag(self):
        cov = _make_coverage(claim_history_count=8)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("KNOWN_CLAIM_RISK", result["coverages_analyzed"][0]["flags"])

    def test_no_flags_for_clean_coverage(self):
        cov = _make_coverage(
            tvl_covered_ratio=0.8,
            premium_annual_pct=2.0,
            coverage_capacity_ratio=0.5,
            days_remaining=200,
            claim_history_count=0,
        )
        result = self.analyzer.analyze([cov], {})
        flags = result["coverages_analyzed"][0]["flags"]
        self.assertNotIn("OVER_INSURED", flags)
        self.assertNotIn("UNDER_INSURED", flags)
        self.assertNotIn("PREMIUM_HIGH", flags)
        self.assertNotIn("POOL_NEAR_CAPACITY", flags)
        self.assertNotIn("EXPIRED_SOON", flags)
        self.assertNotIn("KNOWN_CLAIM_RISK", flags)

    def test_expired_soon_not_triggered_at_zero_days(self):
        # 0 days = expired, not "soon"
        cov = _make_coverage(days_remaining=0)
        result = self.analyzer.analyze([cov], {})
        self.assertNotIn("EXPIRED_SOON", result["coverages_analyzed"][0]["flags"])

    def test_expired_soon_at_29_days(self):
        cov = _make_coverage(days_remaining=29)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("EXPIRED_SOON", result["coverages_analyzed"][0]["flags"])

    def test_premium_high_exactly_5(self):
        cov = _make_coverage(premium_annual_pct=5.1)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("PREMIUM_HIGH", result["coverages_analyzed"][0]["flags"])

    def test_claim_risk_exactly_5_no_flag(self):
        cov = _make_coverage(claim_history_count=5)
        result = self.analyzer.analyze([cov], {})
        # >5 triggers; exactly 5 doesn't
        self.assertNotIn("KNOWN_CLAIM_RISK", result["coverages_analyzed"][0]["flags"])

    def test_claim_risk_exactly_6_triggers(self):
        cov = _make_coverage(claim_history_count=6)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("KNOWN_CLAIM_RISK", result["coverages_analyzed"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_empty_aggregates(self):
        result = self.analyzer.analyze([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["best_value_coverage"])
        self.assertIsNone(agg["most_expensive"])
        self.assertEqual(agg["total_coverage_usd"], 0.0)
        self.assertEqual(agg["average_efficiency_score"], 0.0)
        self.assertEqual(agg["uninsured_count"], 0)

    def test_total_coverage_sum(self):
        covs = [
            _make_coverage(coverage_amount_usd=30000),
            _make_coverage(protocol_covered="Compound", coverage_amount_usd=20000),
        ]
        result = self.analyzer.analyze(covs, {})
        self.assertAlmostEqual(result["aggregates"]["total_coverage_usd"], 50000.0)

    def test_uninsured_count(self):
        covs = [
            _make_coverage(provider="self_insured"),
            _make_coverage(provider="Nexus Mutual"),
            _make_coverage(provider="self_insured"),
        ]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["aggregates"]["uninsured_count"], 2)

    def test_best_value_coverage_protocol(self):
        covs = [
            _make_coverage(protocol_covered="ProtA", tvl_covered_ratio=1.0, premium_annual_pct=1.0, provider="Nexus Mutual"),
            _make_coverage(protocol_covered="ProtB", tvl_covered_ratio=0.1, premium_annual_pct=4.9, provider="self_insured"),
        ]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["aggregates"]["best_value_coverage"], "ProtA")

    def test_most_expensive_coverage(self):
        covs = [
            _make_coverage(protocol_covered="CheapProt", premium_annual_pct=1.0),
            _make_coverage(protocol_covered="ExpProt", premium_annual_pct=4.5),
        ]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["aggregates"]["most_expensive"], "ExpProt")

    def test_average_efficiency_score_is_float(self):
        result = self.analyzer.analyze([_make_coverage()], {})
        self.assertIsInstance(result["aggregates"]["average_efficiency_score"], float)

    def test_single_item_aggregates(self):
        cov = _make_coverage(coverage_amount_usd=75000)
        result = self.analyzer.analyze([cov], {})
        agg = result["aggregates"]
        self.assertEqual(agg["total_coverage_usd"], 75000.0)
        self.assertIsNotNone(agg["best_value_coverage"])
        self.assertIsNotNone(agg["most_expensive"])


class TestInputValidation(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_non_list_coverages_raises(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not a list", {})

    def test_non_dict_config_raises(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([], "not a dict")

    def test_none_coverages_raises(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze(None, {})

    def test_none_config_raises(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([], None)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_coverage_with_all_defaults(self):
        result = self.analyzer.analyze([{}], {})
        self.assertEqual(result["total_count"], 1)

    def test_very_high_premium(self):
        cov = _make_coverage(premium_annual_pct=50.0)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("PREMIUM_HIGH", result["coverages_analyzed"][0]["flags"])
        score = result["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"]
        self.assertGreaterEqual(score, 0)

    def test_zero_tvl_ratio(self):
        cov = _make_coverage(tvl_covered_ratio=0.0)
        result = self.analyzer.analyze([cov], {})
        label = result["coverages_analyzed"][0]["label"]
        self.assertIn(label, ("MINIMAL", "UNINSURED"))

    def test_full_capacity_pool(self):
        cov = _make_coverage(coverage_capacity_ratio=1.0)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("POOL_NEAR_CAPACITY", result["coverages_analyzed"][0]["flags"])

    def test_negative_days_remaining(self):
        cov = _make_coverage(days_remaining=-5)
        result = self.analyzer.analyze([cov], {})
        # Should not crash, no EXPIRED_SOON (negative isn't 1-29)
        self.assertIsNotNone(result)

    def test_unknown_provider_handled(self):
        cov = _make_coverage(provider="UnknownProvider")
        result = self.analyzer.analyze([cov], {})
        self.assertIn("derived", result["coverages_analyzed"][0])

    def test_excluded_risks_preserved(self):
        cov = _make_coverage(excluded_risks=["rug_pull", "admin_key"])
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(
            result["coverages_analyzed"][0]["excluded_risks"],
            ["rug_pull", "admin_key"]
        )

    def test_large_number_of_coverages(self):
        covs = [_make_coverage(protocol_covered=f"P{i}", coverage_amount_usd=float(i*1000)) for i in range(50)]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["total_count"], 50)

    def test_all_providers(self):
        providers = ["Nexus Mutual", "InsurAce", "Uno Re", "Unslashed", "self_insured"]
        covs = [_make_coverage(protocol_covered=p, provider=p) for p in providers]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["total_count"], 5)

    def test_all_coverage_types(self):
        types = ["smart_contract", "depeg", "oracle", "liquidation", "hack"]
        covs = [_make_coverage(coverage_type=t) for t in types]
        result = self.analyzer.analyze(covs, {})
        self.assertEqual(result["total_count"], 5)

    def test_string_numeric_fields_coerced(self):
        # float() coercion
        cov = _make_coverage(coverage_amount_usd="50000", premium_annual_pct="2.5")
        result = self.analyzer.analyze([cov], {})
        self.assertIsNotNone(result)

    def test_config_ignored_gracefully(self):
        cov = _make_coverage()
        result = self.analyzer.analyze([cov], {"unknown_key": 999})
        self.assertIsNotNone(result)


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_log_file_created(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                self.assertTrue(os.path.exists(mod.LOG_PATH))
            finally:
                mod.LOG_PATH = orig

    def test_log_is_valid_json_list(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIsInstance(data, list)
            finally:
                mod.LOG_PATH = orig

    def test_log_entries_accumulate(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 2)
            finally:
                mod.LOG_PATH = orig

    def test_log_ring_buffer_cap(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = mod.LOG_PATH
            orig_cap = mod.LOG_CAP
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            mod.LOG_CAP = 5
            try:
                for _ in range(8):
                    self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertLessEqual(len(data), 5)
            finally:
                mod.LOG_PATH = orig_path
                mod.LOG_CAP = orig_cap

    def test_log_entry_has_ts(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIn("ts", data[0])
            finally:
                mod.LOG_PATH = orig

    def test_log_entry_has_aggregates(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertIn("aggregates", data[0])
            finally:
                mod.LOG_PATH = orig

    def test_no_tmp_file_left_behind(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                self.analyzer.analyze([_make_coverage()], {})
                tmp_path = mod.LOG_PATH + ".tmp"
                self.assertFalse(os.path.exists(tmp_path))
            finally:
                mod.LOG_PATH = orig

    def test_log_recovers_from_corrupt_file(self):
        import spa_core.analytics.defi_insurance_coverage_analyzer as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(tmpdir, "test_insurance_log.json")
            try:
                # Write corrupt JSON
                with open(mod.LOG_PATH, "w") as f:
                    f.write("NOT JSON {{{")
                # Should not raise
                self.analyzer.analyze([_make_coverage()], {})
                with open(mod.LOG_PATH) as f:
                    data = json.load(f)
                self.assertEqual(len(data), 1)
            finally:
                mod.LOG_PATH = orig


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_same_input_same_flags(self):
        cov = _make_coverage()
        r1 = self.analyzer.analyze([cov], {})
        r2 = self.analyzer.analyze([cov], {})
        self.assertEqual(
            r1["coverages_analyzed"][0]["flags"],
            r2["coverages_analyzed"][0]["flags"],
        )

    def test_same_input_same_label(self):
        cov = _make_coverage()
        r1 = self.analyzer.analyze([cov], {})
        r2 = self.analyzer.analyze([cov], {})
        self.assertEqual(
            r1["coverages_analyzed"][0]["label"],
            r2["coverages_analyzed"][0]["label"],
        )

    def test_same_input_same_efficiency_score(self):
        cov = _make_coverage()
        r1 = self.analyzer.analyze([cov], {})
        r2 = self.analyzer.analyze([cov], {})
        self.assertEqual(
            r1["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"],
            r2["coverages_analyzed"][0]["derived"]["coverage_efficiency_score"],
        )


class TestBoundaryValues(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_tvl_ratio_exactly_150_percent(self):
        cov = _make_coverage(tvl_covered_ratio=1.5)
        result = self.analyzer.analyze([cov], {})
        # exactly 1.5 is not >1.5
        self.assertNotIn("OVER_INSURED", result["coverages_analyzed"][0]["flags"])

    def test_tvl_ratio_just_above_150_percent(self):
        cov = _make_coverage(tvl_covered_ratio=1.51)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("OVER_INSURED", result["coverages_analyzed"][0]["flags"])

    def test_premium_exactly_5_no_flag(self):
        cov = _make_coverage(premium_annual_pct=5.0)
        result = self.analyzer.analyze([cov], {})
        self.assertNotIn("PREMIUM_HIGH", result["coverages_analyzed"][0]["flags"])

    def test_capacity_exactly_09_no_flag(self):
        cov = _make_coverage(coverage_capacity_ratio=0.9)
        result = self.analyzer.analyze([cov], {})
        self.assertNotIn("POOL_NEAR_CAPACITY", result["coverages_analyzed"][0]["flags"])

    def test_capacity_above_09_flag(self):
        cov = _make_coverage(coverage_capacity_ratio=0.91)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("POOL_NEAR_CAPACITY", result["coverages_analyzed"][0]["flags"])

    def test_tvl_ratio_exactly_50_pct_boundary(self):
        # <0.5 → UNDER_INSURED; exactly 0.5 → no flag
        cov = _make_coverage(tvl_covered_ratio=0.5)
        result = self.analyzer.analyze([cov], {})
        self.assertNotIn("UNDER_INSURED", result["coverages_analyzed"][0]["flags"])

    def test_tvl_ratio_just_below_50_pct(self):
        cov = _make_coverage(tvl_covered_ratio=0.49)
        result = self.analyzer.analyze([cov], {})
        self.assertIn("UNDER_INSURED", result["coverages_analyzed"][0]["flags"])


class TestProtocolPassthrough(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiInsuranceCoverageAnalyzer()

    def test_protocol_name_preserved(self):
        cov = _make_coverage(protocol_covered="MorphoBlue")
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(result["coverages_analyzed"][0]["protocol_covered"], "MorphoBlue")

    def test_coverage_amount_preserved(self):
        cov = _make_coverage(coverage_amount_usd=123456.78)
        result = self.analyzer.analyze([cov], {})
        self.assertAlmostEqual(result["coverages_analyzed"][0]["coverage_amount_usd"], 123456.78)

    def test_premium_pct_preserved(self):
        cov = _make_coverage(premium_annual_pct=3.75)
        result = self.analyzer.analyze([cov], {})
        self.assertAlmostEqual(result["coverages_analyzed"][0]["premium_annual_pct"], 3.75)

    def test_days_remaining_preserved(self):
        cov = _make_coverage(days_remaining=90)
        result = self.analyzer.analyze([cov], {})
        self.assertEqual(result["coverages_analyzed"][0]["days_remaining"], 90)


if __name__ == "__main__":
    unittest.main(verbosity=2)
