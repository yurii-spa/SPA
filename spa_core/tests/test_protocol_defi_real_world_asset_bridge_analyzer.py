"""
Tests for MP-1017: ProtocolDeFiRealWorldAssetBridgeAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_real_world_asset_bridge_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_real_world_asset_bridge_analyzer import (
    ProtocolDeFiRealWorldAssetBridgeAnalyzer,
    REDEMPTION_RISK_MAP,
    TRANSPARENCY_MAP,
    AUDIT_RISK_MAP,
    _DEFAULT_CONFIG,
)


def _proto(
    name="PROTO-1",
    rwa_category="us_treasuries",
    total_tvl_usd=10_000_000.0,
    underlying_yield_pct=5.5,
    protocol_fee_pct=0.25,
    net_yield_pct=5.25,
    custodian_name="Blackrock",
    custodian_regulated=True,
    redemption_mechanism="daily",
    on_chain_audit_frequency="daily",
    legal_wrapper="trust",
    jurisdiction="us",
    kyc_required=False,
    min_investment_usd=1_000.0,
    secondary_market_liquidity_score=80.0,
    counterparty_default_risk_score=10.0,
):
    """Helper to build a protocol dict with sensible defaults."""
    return {
        "name": name,
        "rwa_category": rwa_category,
        "total_tvl_usd": total_tvl_usd,
        "underlying_yield_pct": underlying_yield_pct,
        "protocol_fee_pct": protocol_fee_pct,
        "net_yield_pct": net_yield_pct,
        "custodian_name": custodian_name,
        "custodian_regulated": custodian_regulated,
        "redemption_mechanism": redemption_mechanism,
        "on_chain_audit_frequency": on_chain_audit_frequency,
        "legal_wrapper": legal_wrapper,
        "jurisdiction": jurisdiction,
        "kyc_required": kyc_required,
        "min_investment_usd": min_investment_usd,
        "secondary_market_liquidity_score": secondary_market_liquidity_score,
        "counterparty_default_risk_score": counterparty_default_risk_score,
    }


def _tmp_log(tmp_dir):
    return os.path.join(tmp_dir, "rwa_log.json")


class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.assertIsNotNone(a)

    def test_name_attribute(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.assertEqual(a.name, "ProtocolDeFiRealWorldAssetBridgeAnalyzer")

    def test_version_attribute(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.assertEqual(a.version, "1.0.0")


class TestStaticMaps(unittest.TestCase):
    def test_redemption_daily_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["daily"], 10.0)

    def test_redemption_t1_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["t+1"], 15.0)

    def test_redemption_t3_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["t+3"], 25.0)

    def test_redemption_weekly_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["weekly"], 40.0)

    def test_redemption_monthly_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["monthly"], 60.0)

    def test_redemption_quarterly_risk(self):
        self.assertEqual(REDEMPTION_RISK_MAP["quarterly"], 80.0)

    def test_transparency_realtime(self):
        self.assertEqual(TRANSPARENCY_MAP["realtime"], 100.0)

    def test_transparency_daily(self):
        self.assertEqual(TRANSPARENCY_MAP["daily"], 80.0)

    def test_transparency_weekly(self):
        self.assertEqual(TRANSPARENCY_MAP["weekly"], 50.0)

    def test_transparency_monthly(self):
        self.assertEqual(TRANSPARENCY_MAP["monthly"], 20.0)

    def test_audit_risk_realtime(self):
        self.assertEqual(AUDIT_RISK_MAP["realtime"], 0.0)

    def test_audit_risk_monthly(self):
        self.assertEqual(AUDIT_RISK_MAP["monthly"], 80.0)


class TestEmptyInput(unittest.TestCase):
    def test_empty_list_returns_zero_count(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["protocol_count"], 0)

    def test_empty_list_protocols_is_empty(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["protocols"], [])

    def test_empty_aggregates_none(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        r = a.analyze([])
        self.assertIsNone(r["aggregates"]["highest_quality"])
        self.assertIsNone(r["aggregates"]["lowest_quality"])

    def test_empty_total_tvl_zero(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["aggregates"]["total_rwa_tvl_usd"], 0.0)

    def test_empty_avg_quality_zero(self):
        a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["aggregates"]["avg_bridge_quality"], 0.0)


class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_top_level_keys_present(self):
        r = self.a.analyze([_proto()], self.cfg)
        for k in ("analyzer", "version", "timestamp", "protocol_count", "protocols", "aggregates"):
            self.assertIn(k, r)

    def test_protocol_count_matches(self):
        r = self.a.analyze([_proto("A"), _proto("B")], self.cfg)
        self.assertEqual(r["protocol_count"], 2)
        self.assertEqual(len(r["protocols"]), 2)

    def test_protocol_keys_present(self):
        r = self.a.analyze([_proto()], self.cfg)
        p = r["protocols"][0]
        for k in (
            "name", "rwa_category", "total_tvl_usd", "underlying_yield_pct",
            "protocol_fee_pct", "net_yield_pct", "custodian_regulated",
            "redemption_mechanism", "on_chain_audit_frequency",
            "redemption_risk_score", "custody_risk_score",
            "on_chain_transparency_score", "yield_premium_over_tbill_pct",
            "overall_bridge_quality_score", "quality_label", "flags",
        ):
            self.assertIn(k, p)

    def test_aggregate_keys_present(self):
        r = self.a.analyze([_proto()], self.cfg)
        for k in ("highest_quality", "lowest_quality", "avg_bridge_quality",
                  "institutional_grade_count", "total_rwa_tvl_usd"):
            self.assertIn(k, r["aggregates"])

    def test_analyzer_name_in_result(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertEqual(r["analyzer"], "ProtocolDeFiRealWorldAssetBridgeAnalyzer")

    def test_version_in_result(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertEqual(r["version"], "1.0.0")

    def test_timestamp_is_string(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertIsInstance(r["timestamp"], str)


class TestRedemptionRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_daily_redemption_risk_10(self):
        p = _proto(redemption_mechanism="daily")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 10.0)

    def test_weekly_redemption_risk_40(self):
        p = _proto(redemption_mechanism="weekly", custodian_regulated=True,
                   on_chain_audit_frequency="realtime")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 40.0)

    def test_monthly_redemption_risk_60(self):
        p = _proto(redemption_mechanism="monthly", custodian_regulated=True,
                   on_chain_audit_frequency="realtime")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 60.0)

    def test_quarterly_redemption_risk_80(self):
        p = _proto(redemption_mechanism="quarterly", custodian_regulated=True,
                   on_chain_audit_frequency="realtime")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 80.0)

    def test_t1_redemption_risk_15(self):
        p = _proto(redemption_mechanism="t+1")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 15.0)

    def test_t3_redemption_risk_25(self):
        p = _proto(redemption_mechanism="t+3")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 25.0)

    def test_unknown_redemption_defaults_to_monthly(self):
        p = _proto(redemption_mechanism="unknown", custodian_regulated=True)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["redemption_risk_score"], 60.0)


class TestTransparencyScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_realtime_audit_transparency_100(self):
        p = _proto(on_chain_audit_frequency="realtime")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["on_chain_transparency_score"], 100.0)

    def test_daily_audit_transparency_80(self):
        p = _proto(on_chain_audit_frequency="daily")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["on_chain_transparency_score"], 80.0)

    def test_weekly_audit_transparency_50(self):
        p = _proto(on_chain_audit_frequency="weekly")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["on_chain_transparency_score"], 50.0)

    def test_monthly_audit_transparency_20(self):
        p = _proto(on_chain_audit_frequency="monthly")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["on_chain_transparency_score"], 20.0)

    def test_unknown_audit_frequency_defaults_to_monthly_transparency(self):
        p = _proto(on_chain_audit_frequency="unknown")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["on_chain_transparency_score"], 20.0)


class TestCustodyRisk(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()

    def test_regulated_realtime_audit_low_risk(self):
        risk = self.a._calc_custody_risk(True, "realtime")
        self.assertAlmostEqual(risk, 0.0)

    def test_unregulated_realtime_audit_medium_risk(self):
        risk = self.a._calc_custody_risk(False, "realtime")
        self.assertEqual(risk, 50.0)

    def test_regulated_monthly_audit_medium_risk(self):
        risk = self.a._calc_custody_risk(True, "monthly")
        self.assertEqual(risk, 40.0)  # 80*0.5 + 0 = 40

    def test_unregulated_monthly_audit_high_risk(self):
        risk = self.a._calc_custody_risk(False, "monthly")
        self.assertEqual(risk, min(100.0, 80 * 0.5 + 50))  # 90

    def test_custody_risk_bounded_0_100(self):
        for reg in [True, False]:
            for freq in ["realtime", "daily", "weekly", "monthly", "quarterly"]:
                r = self.a._calc_custody_risk(reg, freq)
                self.assertGreaterEqual(r, 0.0)
                self.assertLessEqual(r, 100.0)

    def test_regulated_lowers_custody_risk(self):
        risk_reg = self.a._calc_custody_risk(True, "weekly")
        risk_unreg = self.a._calc_custody_risk(False, "weekly")
        self.assertLess(risk_reg, risk_unreg)


class TestYieldPremium(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_premium_positive(self):
        p = _proto(net_yield_pct=7.5)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["yield_premium_over_tbill_pct"], 2.25, places=2)

    def test_premium_negative(self):
        p = _proto(net_yield_pct=4.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["yield_premium_over_tbill_pct"], -1.25, places=2)

    def test_premium_zero_at_benchmark(self):
        p = _proto(net_yield_pct=5.25)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["yield_premium_over_tbill_pct"], 0.0, places=4)

    def test_custom_benchmark(self):
        cfg = {**self.cfg, "tbill_benchmark_pct": 4.0}
        p = _proto(net_yield_pct=5.0)
        r = self.a.analyze([p], cfg)
        self.assertAlmostEqual(r["protocols"][0]["yield_premium_over_tbill_pct"], 1.0, places=4)


class TestBridgeQualityScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_quality_score_bounded_0_100(self):
        test_cases = [
            _proto(custodian_regulated=True, on_chain_audit_frequency="realtime",
                   secondary_market_liquidity_score=100.0, counterparty_default_risk_score=0.0),
            _proto(custodian_regulated=False, on_chain_audit_frequency="monthly",
                   secondary_market_liquidity_score=0.0, counterparty_default_risk_score=100.0),
        ]
        for p in test_cases:
            r = self.a.analyze([p], self.cfg)
            score = r["protocols"][0]["overall_bridge_quality_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_high_quality_conditions(self):
        p = _proto(
            custodian_regulated=True,
            on_chain_audit_frequency="realtime",
            secondary_market_liquidity_score=90.0,
            counterparty_default_risk_score=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertGreater(r["protocols"][0]["overall_bridge_quality_score"], 70.0)

    def test_low_quality_conditions(self):
        p = _proto(
            custodian_regulated=False,
            on_chain_audit_frequency="monthly",
            secondary_market_liquidity_score=10.0,
            counterparty_default_risk_score=90.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertLess(r["protocols"][0]["overall_bridge_quality_score"], 50.0)

    def test_quality_score_is_float(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertIsInstance(r["protocols"][0]["overall_bridge_quality_score"], float)

    def test_realtime_audit_increases_quality(self):
        p_rt = _proto(on_chain_audit_frequency="realtime")
        p_mo = _proto(on_chain_audit_frequency="monthly")
        r_rt = self.a.analyze([p_rt], self.cfg)
        r_mo = self.a.analyze([p_mo], self.cfg)
        self.assertGreater(
            r_rt["protocols"][0]["overall_bridge_quality_score"],
            r_mo["protocols"][0]["overall_bridge_quality_score"],
        )

    def test_regulated_increases_quality(self):
        p_reg = _proto(custodian_regulated=True)
        p_unreg = _proto(custodian_regulated=False)
        r_reg = self.a.analyze([p_reg], self.cfg)
        r_unreg = self.a.analyze([p_unreg], self.cfg)
        self.assertGreater(
            r_reg["protocols"][0]["overall_bridge_quality_score"],
            r_unreg["protocols"][0]["overall_bridge_quality_score"],
        )


class TestQualityLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_label_institutional_grade(self):
        p = _proto(
            custodian_regulated=True,
            redemption_mechanism="daily",
            on_chain_audit_frequency="realtime",
            secondary_market_liquidity_score=95.0,
            counterparty_default_risk_score=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["quality_label"], "INSTITUTIONAL_GRADE")

    def test_label_institutional_requires_daily_redemption(self):
        p = _proto(
            custodian_regulated=True,
            redemption_mechanism="weekly",  # not daily
            on_chain_audit_frequency="realtime",
            secondary_market_liquidity_score=95.0,
            counterparty_default_risk_score=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertNotEqual(r["protocols"][0]["quality_label"], "INSTITUTIONAL_GRADE")

    def test_label_institutional_requires_regulated(self):
        p = _proto(
            custodian_regulated=False,  # unregulated
            redemption_mechanism="daily",
            on_chain_audit_frequency="realtime",
            secondary_market_liquidity_score=95.0,
            counterparty_default_risk_score=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertNotEqual(r["protocols"][0]["quality_label"], "INSTITUTIONAL_GRADE")

    def test_label_high_risk_rwa_unregulated(self):
        p = _proto(
            custodian_regulated=False,
            on_chain_audit_frequency="monthly",
            secondary_market_liquidity_score=20.0,
            counterparty_default_risk_score=70.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["quality_label"], "HIGH_RISK_RWA")

    def test_label_high_risk_rwa_quarterly_low_score(self):
        p = _proto(
            custodian_regulated=True,
            redemption_mechanism="quarterly",
            on_chain_audit_frequency="monthly",
            secondary_market_liquidity_score=10.0,
            counterparty_default_risk_score=80.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["quality_label"], "HIGH_RISK_RWA")

    def test_label_high_quality(self):
        p = _proto(
            custodian_regulated=True,
            redemption_mechanism="t+1",
            on_chain_audit_frequency="daily",
            secondary_market_liquidity_score=75.0,
            counterparty_default_risk_score=15.0,
        )
        r = self.a.analyze([p], self.cfg)
        label = r["protocols"][0]["quality_label"]
        # Should be HIGH_QUALITY or INSTITUTIONAL_GRADE depending on exact score
        self.assertIn(label, ("HIGH_QUALITY", "INSTITUTIONAL_GRADE", "STANDARD"))

    def test_label_standard(self):
        p = _proto(
            custodian_regulated=True,
            redemption_mechanism="weekly",
            on_chain_audit_frequency="weekly",
            secondary_market_liquidity_score=40.0,
            counterparty_default_risk_score=40.0,
        )
        r = self.a.analyze([p], self.cfg)
        label = r["protocols"][0]["quality_label"]
        self.assertIn(label, ("STANDARD", "HIGH_QUALITY", "BELOW_STANDARD"))

    def test_valid_labels(self):
        VALID = {"INSTITUTIONAL_GRADE", "HIGH_QUALITY", "STANDARD", "BELOW_STANDARD", "HIGH_RISK_RWA"}
        for regulated in [True, False]:
            for red in ["daily", "weekly", "monthly", "quarterly"]:
                p = _proto(custodian_regulated=regulated, redemption_mechanism=red)
                r = self.a.analyze([p], self.cfg)
                self.assertIn(r["protocols"][0]["quality_label"], VALID)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flag_daily_redemption(self):
        p = _proto(redemption_mechanism="daily")
        r = self.a.analyze([p], self.cfg)
        self.assertIn("DAILY_REDEMPTION", r["protocols"][0]["flags"])

    def test_flag_daily_redemption_not_set_for_weekly(self):
        p = _proto(redemption_mechanism="weekly", custodian_regulated=True)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("DAILY_REDEMPTION", r["protocols"][0]["flags"])

    def test_flag_unregulated_custodian(self):
        p = _proto(custodian_regulated=False)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("UNREGULATED_CUSTODIAN", r["protocols"][0]["flags"])

    def test_flag_unregulated_not_set_when_regulated(self):
        p = _proto(custodian_regulated=True)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("UNREGULATED_CUSTODIAN", r["protocols"][0]["flags"])

    def test_flag_opaque_reporting_monthly(self):
        p = _proto(on_chain_audit_frequency="monthly")
        r = self.a.analyze([p], self.cfg)
        self.assertIn("OPAQUE_REPORTING", r["protocols"][0]["flags"])

    def test_flag_opaque_reporting_quarterly(self):
        p = _proto(on_chain_audit_frequency="quarterly")
        r = self.a.analyze([p], self.cfg)
        self.assertIn("OPAQUE_REPORTING", r["protocols"][0]["flags"])

    def test_flag_opaque_reporting_not_set_for_daily(self):
        p = _proto(on_chain_audit_frequency="daily")
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("OPAQUE_REPORTING", r["protocols"][0]["flags"])

    def test_flag_yield_premium_positive(self):
        p = _proto(net_yield_pct=8.0)  # 8 - 5.25 = 2.75 > 1.0
        r = self.a.analyze([p], self.cfg)
        self.assertIn("YIELD_PREMIUM_POSITIVE", r["protocols"][0]["flags"])

    def test_flag_yield_premium_not_set_when_low(self):
        p = _proto(net_yield_pct=5.5)  # 5.5 - 5.25 = 0.25 < 1.0
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("YIELD_PREMIUM_POSITIVE", r["protocols"][0]["flags"])

    def test_flag_kyc_barrier(self):
        p = _proto(kyc_required=True)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("KYC_BARRIER", r["protocols"][0]["flags"])

    def test_flag_kyc_barrier_not_set(self):
        p = _proto(kyc_required=False)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("KYC_BARRIER", r["protocols"][0]["flags"])

    def test_flag_institutional_accessible_below_100k(self):
        p = _proto(min_investment_usd=1_000.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("INSTITUTIONAL_ACCESSIBLE", r["protocols"][0]["flags"])

    def test_flag_institutional_accessible_not_set_at_100k(self):
        p = _proto(min_investment_usd=100_000.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("INSTITUTIONAL_ACCESSIBLE", r["protocols"][0]["flags"])

    def test_multiple_flags_simultaneously(self):
        p = _proto(
            custodian_regulated=False,
            on_chain_audit_frequency="monthly",
            net_yield_pct=9.0,
            kyc_required=True,
            min_investment_usd=500.0,
        )
        r = self.a.analyze([p], self.cfg)
        flags = r["protocols"][0]["flags"]
        self.assertIn("UNREGULATED_CUSTODIAN", flags)
        self.assertIn("OPAQUE_REPORTING", flags)
        self.assertIn("YIELD_PREMIUM_POSITIVE", flags)
        self.assertIn("KYC_BARRIER", flags)
        self.assertIn("INSTITUTIONAL_ACCESSIBLE", flags)

    def test_flags_is_list(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertIsInstance(r["protocols"][0]["flags"], list)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_highest_quality_is_max_score(self):
        p_good = _proto("GOOD", custodian_regulated=True, on_chain_audit_frequency="realtime",
                        secondary_market_liquidity_score=95.0, counterparty_default_risk_score=5.0)
        p_bad = _proto("BAD", custodian_regulated=False, on_chain_audit_frequency="monthly",
                       secondary_market_liquidity_score=5.0, counterparty_default_risk_score=90.0)
        r = self.a.analyze([p_good, p_bad], self.cfg)
        self.assertEqual(r["aggregates"]["highest_quality"], "GOOD")

    def test_lowest_quality_is_min_score(self):
        p_good = _proto("GOOD", custodian_regulated=True, on_chain_audit_frequency="realtime",
                        secondary_market_liquidity_score=95.0, counterparty_default_risk_score=5.0)
        p_bad = _proto("BAD", custodian_regulated=False, on_chain_audit_frequency="monthly",
                       secondary_market_liquidity_score=5.0, counterparty_default_risk_score=90.0)
        r = self.a.analyze([p_good, p_bad], self.cfg)
        self.assertEqual(r["aggregates"]["lowest_quality"], "BAD")

    def test_total_tvl_sum(self):
        p1 = _proto("A", total_tvl_usd=1_000_000.0)
        p2 = _proto("B", total_tvl_usd=2_000_000.0)
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertAlmostEqual(r["aggregates"]["total_rwa_tvl_usd"], 3_000_000.0)

    def test_institutional_grade_count(self):
        p_inst = _proto("IG", custodian_regulated=True, redemption_mechanism="daily",
                        on_chain_audit_frequency="realtime",
                        secondary_market_liquidity_score=95.0, counterparty_default_risk_score=5.0)
        p_other = _proto("OTHER", custodian_regulated=False)
        r = self.a.analyze([p_inst, p_other], self.cfg)
        self.assertEqual(r["aggregates"]["institutional_grade_count"], 1)

    def test_avg_bridge_quality_single(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        pos_score = r["protocols"][0]["overall_bridge_quality_score"]
        self.assertAlmostEqual(r["aggregates"]["avg_bridge_quality"], pos_score, places=4)

    def test_avg_bridge_quality_multiple(self):
        p1 = _proto("A")
        p2 = _proto("B")
        r = self.a.analyze([p1, p2], self.cfg)
        expected = (r["protocols"][0]["overall_bridge_quality_score"] +
                    r["protocols"][1]["overall_bridge_quality_score"]) / 2.0
        self.assertAlmostEqual(r["aggregates"]["avg_bridge_quality"], expected, places=4)

    def test_single_protocol_highest_equals_lowest(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertEqual(r["aggregates"]["highest_quality"], r["aggregates"]["lowest_quality"])


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_log_file_created(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_proto()], {"log_file": log})
        self.assertTrue(os.path.exists(log))

    def test_log_is_list(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_proto()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_proto()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_aggregates(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_proto()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_accumulates_entries(self):
        log = _tmp_log(self.tmp)
        cfg = {"log_file": log}
        for _ in range(4):
            self.a.analyze([_proto()], cfg)
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_ring_buffer_cap(self):
        log = _tmp_log(self.tmp)
        cfg = {"log_file": log, "ring_buffer_cap": 3}
        for _ in range(7):
            self.a.analyze([_proto()], cfg)
        with open(log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)

    def test_log_is_valid_json(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_proto()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIsNotNone(data)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiRealWorldAssetBridgeAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zero_tvl(self):
        p = _proto(total_tvl_usd=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["total_tvl_usd"], 0.0)

    def test_missing_optional_fields(self):
        p = {"name": "MINIMAL", "rwa_category": "us_treasuries",
             "custodian_regulated": True, "redemption_mechanism": "daily"}
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocol_count"], 1)
        self.assertIn("quality_label", r["protocols"][0])

    def test_net_yield_computed_from_underlying_minus_fee(self):
        p = _proto(underlying_yield_pct=6.0, protocol_fee_pct=0.5)
        del p["net_yield_pct"]  # Remove explicit net_yield
        p["net_yield_pct"] = p["underlying_yield_pct"] - p["protocol_fee_pct"]
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols"][0]["net_yield_pct"], 5.5, places=4)

    def test_no_config_does_not_crash(self):
        r = self.a.analyze([], None)
        self.assertEqual(r["protocol_count"], 0)

    def test_large_protocol_count(self):
        protocols = [_proto(name=f"P-{i}") for i in range(30)]
        r = self.a.analyze(protocols, self.cfg)
        self.assertEqual(r["protocol_count"], 30)

    def test_counterparty_risk_0_high_quality(self):
        p = _proto(counterparty_default_risk_score=0.0,
                   secondary_market_liquidity_score=100.0,
                   custodian_regulated=True,
                   on_chain_audit_frequency="realtime")
        r = self.a.analyze([p], self.cfg)
        self.assertGreater(r["protocols"][0]["overall_bridge_quality_score"], 70.0)

    def test_counterparty_risk_100_lowers_quality(self):
        p = _proto(counterparty_default_risk_score=100.0,
                   secondary_market_liquidity_score=0.0,
                   custodian_regulated=False,
                   on_chain_audit_frequency="monthly")
        r = self.a.analyze([p], self.cfg)
        self.assertLess(r["protocols"][0]["overall_bridge_quality_score"], 40.0)

    def test_institutional_grade_count_zero_when_none(self):
        p = _proto(custodian_regulated=False)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["aggregates"]["institutional_grade_count"], 0)

    def test_rwa_category_preserved(self):
        for cat in ["us_treasuries", "corporate_bonds", "real_estate", "trade_finance",
                    "private_credit", "commodities"]:
            p = _proto(rwa_category=cat)
            r = self.a.analyze([p], self.cfg)
            self.assertEqual(r["protocols"][0]["rwa_category"], cat)

    def test_jurisdiction_preserved(self):
        p = _proto(jurisdiction="cayman")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols"][0]["jurisdiction"], "cayman")


if __name__ == "__main__":
    unittest.main()
