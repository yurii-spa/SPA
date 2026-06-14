"""
Tests for MP-862 ProtocolTreasuryRunwayAnalyzer
≥ 65 unittest cases covering calculations, labels, edge cases, ring-buffer log,
runway labels, governance labels, and all recommendation strings.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root on path
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_treasury_runway_analyzer import (
    analyze,
    _runway_label,
    _governance_safety_label,
    _recommendation,
    _LOG_CAP,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

def _proto(
    name="TestProto",
    treasury_usd=10_000_000.0,
    monthly_burn=500_000.0,
    monthly_revenue=0.0,
    token_price=1.0,
    token_amount=0.0,
    vesting_unlock=0.0,
    has_dao=True,
):
    return {
        "name": name,
        "treasury_usd": treasury_usd,
        "monthly_burn_usd": monthly_burn,
        "monthly_revenue_usd": monthly_revenue,
        "token_price_usd": token_price,
        "token_treasury_amount": token_amount,
        "vesting_unlock_usd_per_month": vesting_unlock,
        "has_dao_vote_for_spending": has_dao,
    }


class TestEmptyInput(unittest.TestCase):
    def test_empty_returns_dict(self):
        r = analyze([])
        self.assertIsInstance(r, dict)

    def test_empty_most_solvent_none(self):
        r = analyze([])
        self.assertIsNone(r["most_solvent"])

    def test_empty_most_at_risk_none(self):
        r = analyze([])
        self.assertIsNone(r["most_at_risk"])

    def test_empty_profitable_protocols_empty(self):
        r = analyze([])
        self.assertEqual(r["profitable_protocols"], [])

    def test_empty_average_runway_none(self):
        r = analyze([])
        self.assertIsNone(r["average_runway_months"])

    def test_empty_protocols_list(self):
        r = analyze([])
        self.assertEqual(r["protocols"], [])

    def test_empty_has_timestamp(self):
        before = time.time()
        r = analyze([])
        self.assertGreaterEqual(r["timestamp"], before)


class TestNetBurnCalculation(unittest.TestCase):
    def test_net_burn_positive(self):
        r = analyze([_proto(monthly_burn=500_000, monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["net_burn_per_month"], 300_000.0, places=2)

    def test_net_burn_negative_profitable(self):
        r = analyze([_proto(monthly_burn=200_000, monthly_revenue=500_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["net_burn_per_month"], -300_000.0, places=2)

    def test_net_burn_zero(self):
        r = analyze([_proto(monthly_burn=300_000, monthly_revenue=300_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["net_burn_per_month"], 0.0, places=2)

    def test_is_profitable_true(self):
        r = analyze([_proto(monthly_burn=100_000, monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertTrue(p["is_profitable"])

    def test_is_profitable_false(self):
        r = analyze([_proto(monthly_burn=500_000, monthly_revenue=100_000)])
        p = r["protocols"][0]
        self.assertFalse(p["is_profitable"])

    def test_is_profitable_breakeven(self):
        r = analyze([_proto(monthly_burn=300_000, monthly_revenue=300_000)])
        p = r["protocols"][0]
        self.assertTrue(p["is_profitable"])  # net_burn = 0 → profitable


class TestStablecoinRunway(unittest.TestCase):
    def test_stablecoin_runway_basic(self):
        # 10M / 500k = 20 months
        r = analyze([_proto(treasury_usd=10_000_000, monthly_burn=500_000,
                            monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["stablecoin_runway_months"], 20.0, places=4)

    def test_stablecoin_runway_with_revenue(self):
        # net_burn = 500k - 200k = 300k; runway = 10M/300k = 33.33
        r = analyze([_proto(treasury_usd=10_000_000, monthly_burn=500_000,
                            monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["stablecoin_runway_months"], 10_000_000 / 300_000, places=4)

    def test_stablecoin_runway_profitable_is_9999(self):
        r = analyze([_proto(monthly_burn=100_000, monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertEqual(p["stablecoin_runway_months"], 9999.0)

    def test_stablecoin_runway_zero_burn_zero_revenue_is_9999(self):
        r = analyze([_proto(monthly_burn=0, monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["stablecoin_runway_months"], 9999.0)


class TestAdjustedRunway(unittest.TestCase):
    def test_adjusted_runway_with_tokens(self):
        # treasury = 1M, token = 1000 tokens * 10 USD * (1-0.5) = 5000 haircut
        # adjusted = 1M + 5000 = 1_005_000
        # net_burn = 100k; runway = 1_005_000 / 100_000 = 10.05
        r = analyze([_proto(treasury_usd=1_000_000, monthly_burn=100_000,
                            monthly_revenue=0, token_price=10.0, token_amount=1000)])
        p = r["protocols"][0]
        expected = (1_000_000 + 1000 * 10.0 * 0.5) / 100_000
        self.assertAlmostEqual(p["adjusted_runway_months"], expected, places=4)

    def test_adjusted_runway_profitable_is_9999(self):
        r = analyze([_proto(monthly_burn=100_000, monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertEqual(p["adjusted_runway_months"], 9999.0)

    def test_adjusted_runway_custom_haircut(self):
        # haircut = 0.3 → token_value = tokens * price * 0.7
        r = analyze([_proto(treasury_usd=500_000, monthly_burn=100_000,
                            monthly_revenue=0, token_price=5.0, token_amount=10_000)],
                    config={"pessimistic_token_haircut": 0.3})
        p = r["protocols"][0]
        token_val = 10_000 * 5.0 * 0.7
        expected = (500_000 + token_val) / 100_000
        self.assertAlmostEqual(p["adjusted_runway_months"], expected, places=4)

    def test_adjusted_runway_zero_tokens(self):
        r = analyze([_proto(treasury_usd=2_000_000, monthly_burn=200_000,
                            token_amount=0, token_price=100)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["adjusted_runway_months"], 10.0, places=4)


class TestCoverageRatio(unittest.TestCase):
    def test_coverage_ratio_below_one(self):
        r = analyze([_proto(monthly_burn=500_000, monthly_revenue=200_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["coverage_ratio"], 0.4, places=4)

    def test_coverage_ratio_above_one(self):
        r = analyze([_proto(monthly_burn=200_000, monthly_revenue=500_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["coverage_ratio"], 2.5, places=4)

    def test_coverage_ratio_zero_burn(self):
        r = analyze([_proto(monthly_burn=0, monthly_revenue=100_000)])
        p = r["protocols"][0]
        self.assertEqual(p["coverage_ratio"], 9999.0)

    def test_coverage_ratio_zero_both(self):
        r = analyze([_proto(monthly_burn=0, monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["coverage_ratio"], 9999.0)


class TestVestingPressure(unittest.TestCase):
    def test_vesting_pressure_basic(self):
        # 100_000 / 1_000_000 * 100 = 10%
        r = analyze([_proto(treasury_usd=1_000_000, vesting_unlock=100_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["vesting_pressure_pct"], 10.0, places=4)

    def test_vesting_pressure_zero_treasury(self):
        r = analyze([_proto(treasury_usd=0, vesting_unlock=100_000,
                            monthly_burn=0, monthly_revenue=100_000)])
        p = r["protocols"][0]
        self.assertEqual(p["vesting_pressure_pct"], 0.0)

    def test_vesting_pressure_zero_vesting(self):
        r = analyze([_proto(treasury_usd=1_000_000, vesting_unlock=0)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["vesting_pressure_pct"], 0.0, places=4)

    def test_vesting_pressure_high(self):
        r = analyze([_proto(treasury_usd=100_000, vesting_unlock=50_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["vesting_pressure_pct"], 50.0, places=4)


class TestBreakEvenRevenue(unittest.TestCase):
    def test_break_even_equals_monthly_burn(self):
        r = analyze([_proto(monthly_burn=500_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["break_even_revenue"], 500_000.0, places=2)

    def test_break_even_zero_burn(self):
        r = analyze([_proto(monthly_burn=0)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["break_even_revenue"], 0.0, places=2)


class TestRunwayLabel(unittest.TestCase):
    def test_self_sustaining_profitable(self):
        self.assertEqual(_runway_label(9999.0, -100_000, 1_000_000), "SELF_SUSTAINING")

    def test_self_sustaining_breakeven(self):
        self.assertEqual(_runway_label(9999.0, 0.0, 1_000_000), "SELF_SUSTAINING")

    def test_healthy_36_months(self):
        self.assertEqual(_runway_label(36.0, 100_000, 3_600_000), "HEALTHY")

    def test_healthy_above_36(self):
        self.assertEqual(_runway_label(48.0, 100_000, 4_800_000), "HEALTHY")

    def test_adequate_18_months(self):
        self.assertEqual(_runway_label(18.0, 100_000, 1_800_000), "ADEQUATE")

    def test_adequate_24_months(self):
        self.assertEqual(_runway_label(24.0, 100_000, 2_400_000), "ADEQUATE")

    def test_tight_6_months(self):
        self.assertEqual(_runway_label(6.0, 100_000, 600_000), "TIGHT")

    def test_tight_12_months(self):
        self.assertEqual(_runway_label(12.0, 100_000, 1_200_000), "TIGHT")

    def test_critical_1_month(self):
        self.assertEqual(_runway_label(1.0, 100_000, 100_000), "CRITICAL")

    def test_critical_3_months(self):
        self.assertEqual(_runway_label(3.0, 100_000, 300_000), "CRITICAL")

    def test_insolvent_below_1_month(self):
        self.assertEqual(_runway_label(0.5, 100_000, 50_000), "INSOLVENT")

    def test_insolvent_zero_runway(self):
        self.assertEqual(_runway_label(0.0, 100_000, 0), "INSOLVENT")

    def test_insolvent_zero_treasury_positive_burn(self):
        self.assertEqual(_runway_label(0.0, 100_000, 0), "INSOLVENT")


class TestGovernanceSafetyLabel(unittest.TestCase):
    def test_dao_governed_true(self):
        label = _governance_safety_label(True)
        self.assertIn("DAO-governed", label)
        self.assertIn("governance", label)

    def test_centralized_false(self):
        label = _governance_safety_label(False)
        self.assertIn("Centralized", label)
        self.assertIn("DAO", label)

    def test_dao_label_in_result(self):
        r = analyze([_proto(has_dao=True)])
        p = r["protocols"][0]
        self.assertIn("DAO-governed", p["governance_safety_label"])

    def test_centralized_label_in_result(self):
        r = analyze([_proto(has_dao=False)])
        p = r["protocols"][0]
        self.assertIn("Centralized", p["governance_safety_label"])


class TestRecommendationStrings(unittest.TestCase):
    def test_self_sustaining_recommendation(self):
        rec = _recommendation("SELF_SUSTAINING", 9999.0, -300_000, 5.0)
        self.assertIn("profitable", rec)
        self.assertIn("300000", rec)

    def test_healthy_recommendation(self):
        rec = _recommendation("HEALTHY", 48.0, 100_000, 8.5)
        self.assertIn("48", rec)
        self.assertIn("8.5%", rec)

    def test_adequate_recommendation(self):
        rec = _recommendation("ADEQUATE", 24.0, 200_000, 3.0)
        self.assertIn("24", rec)
        self.assertIn("revenue growth", rec)

    def test_tight_recommendation(self):
        rec = _recommendation("TIGHT", 8.5, 150_000, 12.0)
        self.assertIn("8.5", rec)
        self.assertIn("Urgent", rec)

    def test_critical_recommendation(self):
        rec = _recommendation("CRITICAL", 2.3, 500_000, 20.0)
        self.assertIn("CRITICAL", rec)
        self.assertIn("2.3", rec)

    def test_insolvent_recommendation(self):
        rec = _recommendation("INSOLVENT", 0.0, 100_000, 0.0)
        self.assertIn("INSOLVENT", rec)
        self.assertIn("collapse", rec)


class TestRunwayLabelInResult(unittest.TestCase):
    def test_self_sustaining_label(self):
        r = analyze([_proto(monthly_burn=100_000, monthly_revenue=500_000)])
        p = r["protocols"][0]
        self.assertEqual(p["runway_label"], "SELF_SUSTAINING")

    def test_healthy_label(self):
        # 36M treasury, 1M burn, 0 revenue → 36 months
        r = analyze([_proto(treasury_usd=36_000_000, monthly_burn=1_000_000,
                            monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["runway_label"], "HEALTHY")

    def test_insolvent_zero_treasury(self):
        r = analyze([_proto(treasury_usd=0, monthly_burn=100_000, monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["runway_label"], "INSOLVENT")

    def test_tight_label(self):
        # 1.2M / 200k = 6 months
        r = analyze([_proto(treasury_usd=1_200_000, monthly_burn=200_000,
                            monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["runway_label"], "TIGHT")


class TestMostSolventAndAtRisk(unittest.TestCase):
    def test_most_solvent_highest_runway(self):
        protos = [
            _proto("A", treasury_usd=36_000_000, monthly_burn=1_000_000),
            _proto("B", treasury_usd=6_000_000, monthly_burn=1_000_000),
        ]
        r = analyze(protos)
        self.assertEqual(r["most_solvent"], "A")

    def test_most_at_risk_lowest_runway(self):
        protos = [
            _proto("A", treasury_usd=36_000_000, monthly_burn=1_000_000),
            _proto("B", treasury_usd=600_000, monthly_burn=1_000_000),
        ]
        r = analyze(protos)
        self.assertEqual(r["most_at_risk"], "B")

    def test_all_profitable_most_at_risk_highest_vesting(self):
        # All profitable → most_at_risk = highest vesting_pressure_pct
        protos = [
            _proto("A", monthly_burn=100_000, monthly_revenue=200_000,
                   treasury_usd=1_000_000, vesting_unlock=100_000),  # 10%
            _proto("B", monthly_burn=100_000, monthly_revenue=200_000,
                   treasury_usd=1_000_000, vesting_unlock=500_000),  # 50%
        ]
        r = analyze(protos)
        self.assertEqual(r["most_at_risk"], "B")

    def test_single_protocol_most_solvent(self):
        r = analyze([_proto("Solo", treasury_usd=5_000_000, monthly_burn=500_000)])
        self.assertEqual(r["most_solvent"], "Solo")

    def test_single_protocol_most_at_risk(self):
        r = analyze([_proto("Solo", treasury_usd=500_000, monthly_burn=200_000)])
        self.assertEqual(r["most_at_risk"], "Solo")


class TestProfitableProtocols(unittest.TestCase):
    def test_profitable_list(self):
        protos = [
            _proto("A", monthly_burn=100_000, monthly_revenue=200_000),
            _proto("B", monthly_burn=500_000, monthly_revenue=100_000),
        ]
        r = analyze(protos)
        self.assertIn("A", r["profitable_protocols"])
        self.assertNotIn("B", r["profitable_protocols"])

    def test_all_profitable(self):
        protos = [
            _proto("A", monthly_burn=100_000, monthly_revenue=200_000),
            _proto("B", monthly_burn=50_000, monthly_revenue=300_000),
        ]
        r = analyze(protos)
        self.assertEqual(len(r["profitable_protocols"]), 2)

    def test_none_profitable(self):
        protos = [
            _proto("A", monthly_burn=500_000, monthly_revenue=100_000),
            _proto("B", monthly_burn=200_000, monthly_revenue=50_000),
        ]
        r = analyze(protos)
        self.assertEqual(r["profitable_protocols"], [])


class TestAverageRunwayMonths(unittest.TestCase):
    def test_average_runway_basic(self):
        protos = [
            _proto("A", treasury_usd=12_000_000, monthly_burn=1_000_000),  # 12 months
            _proto("B", treasury_usd=24_000_000, monthly_burn=1_000_000),  # 24 months
        ]
        r = analyze(protos)
        self.assertAlmostEqual(r["average_runway_months"], 18.0, places=4)

    def test_average_runway_all_profitable_none(self):
        protos = [
            _proto("A", monthly_burn=100_000, monthly_revenue=200_000),
            _proto("B", monthly_burn=50_000, monthly_revenue=100_000),
        ]
        r = analyze(protos)
        self.assertIsNone(r["average_runway_months"])

    def test_average_runway_mixed(self):
        protos = [
            _proto("A", treasury_usd=10_000_000, monthly_burn=500_000),  # 20 months
            _proto("B", monthly_burn=100_000, monthly_revenue=200_000),  # profitable → 9999
        ]
        r = analyze(protos)
        # Only finite runway counts: [20]
        self.assertAlmostEqual(r["average_runway_months"], 20.0, places=4)


class TestOutputStructure(unittest.TestCase):
    def test_all_top_level_keys(self):
        r = analyze([_proto()])
        for k in ("protocols", "most_solvent", "most_at_risk",
                   "profitable_protocols", "average_runway_months", "timestamp"):
            self.assertIn(k, r)

    def test_protocol_entry_keys(self):
        r = analyze([_proto()])
        p = r["protocols"][0]
        for k in ("name", "stablecoin_runway_months", "adjusted_runway_months",
                   "net_burn_per_month", "is_profitable", "break_even_revenue",
                   "coverage_ratio", "vesting_pressure_pct", "runway_label",
                   "governance_safety_label", "recommendation"):
            self.assertIn(k, p)

    def test_timestamp_is_float(self):
        r = analyze([_proto()])
        self.assertIsInstance(r["timestamp"], float)

    def test_name_preserved(self):
        r = analyze([_proto(name="Morpho")])
        self.assertEqual(r["protocols"][0]["name"], "Morpho")


class TestPersistLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_persist_creates_file(self):
        analyze([_proto()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        self.assertTrue(os.path.exists(path))

    def test_persist_appends_entries(self):
        for _ in range(3):
            analyze([_proto()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap(self):
        for _ in range(_LOG_CAP + 5):
            analyze([_proto()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_no_persist_no_file(self):
        analyze([_proto()], persist=False, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        self.assertFalse(os.path.exists(path))

    def test_log_entry_has_timestamp(self):
        analyze([_proto()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_is_valid_json(self):
        analyze([_proto()], persist=True, data_dir=self.tmpdir)
        path = os.path.join(self.tmpdir, "treasury_runway_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestEdgeCases(unittest.TestCase):
    def test_zero_everything(self):
        r = analyze([_proto(treasury_usd=0, monthly_burn=0, monthly_revenue=0,
                            token_price=0, token_amount=0, vesting_unlock=0)])
        p = r["protocols"][0]
        self.assertTrue(p["is_profitable"])  # net_burn = 0
        self.assertEqual(p["stablecoin_runway_months"], 9999.0)

    def test_zero_treasury_positive_burn_insolvent(self):
        r = analyze([_proto(treasury_usd=0, monthly_burn=100_000, monthly_revenue=0)])
        p = r["protocols"][0]
        self.assertEqual(p["runway_label"], "INSOLVENT")
        self.assertEqual(p["stablecoin_runway_months"], 0.0)
        self.assertEqual(p["adjusted_runway_months"], 0.0)

    def test_token_haircut_zero(self):
        # haircut=0 means tokens at full value
        r = analyze([_proto(treasury_usd=1_000_000, monthly_burn=200_000,
                            token_price=10.0, token_amount=100_000)],
                    config={"pessimistic_token_haircut": 0.0})
        p = r["protocols"][0]
        token_val = 100_000 * 10.0 * 1.0  # full value
        expected = (1_000_000 + token_val) / 200_000
        self.assertAlmostEqual(p["adjusted_runway_months"], expected, places=4)

    def test_token_haircut_one(self):
        # haircut=1.0 means tokens worth 0
        r = analyze([_proto(treasury_usd=1_000_000, monthly_burn=200_000,
                            token_price=10.0, token_amount=100_000)],
                    config={"pessimistic_token_haircut": 1.0})
        p = r["protocols"][0]
        expected = 1_000_000 / 200_000
        self.assertAlmostEqual(p["adjusted_runway_months"], expected, places=4)

    def test_very_large_treasury(self):
        r = analyze([_proto(treasury_usd=1_000_000_000, monthly_burn=1_000_000)])
        p = r["protocols"][0]
        self.assertAlmostEqual(p["stablecoin_runway_months"], 1000.0, places=2)

    def test_multiple_protocols_count(self):
        protos = [
            _proto("A"), _proto("B"), _proto("C"), _proto("D"),
        ]
        r = analyze(protos)
        self.assertEqual(len(r["protocols"]), 4)

    def test_none_config_uses_defaults(self):
        r = analyze([_proto()], config=None)
        p = r["protocols"][0]
        self.assertIn("runway_label", p)

    def test_empty_config_uses_defaults(self):
        r = analyze([_proto()], config={})
        p = r["protocols"][0]
        self.assertIn("runway_label", p)

    def test_high_revenue_low_burn_profitable(self):
        r = analyze([_proto(monthly_burn=10_000, monthly_revenue=1_000_000)])
        p = r["protocols"][0]
        self.assertTrue(p["is_profitable"])
        self.assertEqual(p["runway_label"], "SELF_SUSTAINING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
