"""
Тесты для spa_core/risk/risk_axes.py (MP-208).
Без сети, без внешних зависимостей.
"""
import unittest

from spa_core.risk.risk_axes import (
    check_credit_axis,
    check_peg_axis,
    check_duration_axis,
    check_bridge_axis,
    check_all_axes,
    _matches,
    CREDIT_PROTOCOLS,
    PEG_PROTOCOLS,
    BRIDGE_PROTOCOLS,
)


class TestCreditAxis(unittest.TestCase):
    """Тесты CREDIT_AXIS (лимит ≤ 15%)."""

    def test_empty_allocation_ok(self):
        result = check_credit_axis({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["credit_weight"], 0.0)
        self.assertEqual(result["protocols"], [])

    def test_no_credit_protocols_ok(self):
        allocation = {"aave_v3": 0.40, "compound_v3": 0.30}
        result = check_credit_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertEqual(result["credit_weight"], 0.0)

    def test_credit_exactly_at_limit_ok(self):
        # 15% exactly — boundary should pass (≤)
        allocation = {"maple_usdc": 0.15, "aave_v3": 0.40}
        result = check_credit_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["credit_weight"], 0.15, places=6)

    def test_credit_over_limit_blocked(self):
        allocation = {"maple_usdc": 0.16, "aave_v3": 0.40}
        result = check_credit_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["credit_weight"], 0.16, places=6)

    def test_multiple_credit_protocols_aggregated(self):
        allocation = {
            "maple_usdc": 0.08,
            "clearpool_usdc": 0.08,
            "aave_v3": 0.40,
        }
        result = check_credit_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["credit_weight"], 0.16, places=6)
        self.assertIn("maple_usdc", result["protocols"])
        self.assertIn("clearpool_usdc", result["protocols"])

    def test_custom_limit(self):
        allocation = {"maple": 0.20}
        result = check_credit_axis(allocation, limit=0.25)
        self.assertTrue(result["ok"])

    def test_substring_matching_case_insensitive(self):
        # "MAPLE_V3_USDC" should match credit protocol "maple"
        allocation = {"MAPLE_V3_USDC": 0.20}
        result = check_credit_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertIn("MAPLE_V3_USDC", result["protocols"])

    def test_ipor_protocol_matched(self):
        allocation = {"ipor_usdc_pool": 0.10}
        result = check_credit_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertIn("ipor_usdc_pool", result["protocols"])


class TestPegAxis(unittest.TestCase):
    """Тесты PEG_AXIS (лимит ≤ 10%)."""

    def test_empty_allocation_ok(self):
        result = check_peg_axis({})
        self.assertTrue(result["ok"])

    def test_no_peg_protocols_ok(self):
        allocation = {"aave_v3": 0.40, "compound_v3": 0.35, "morpho_blue": 0.15}
        result = check_peg_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertEqual(result["peg_weight"], 0.0)

    def test_peg_at_limit_ok(self):
        allocation = {"ethena_usdc": 0.10, "aave_v3": 0.50}
        result = check_peg_axis(allocation)
        self.assertTrue(result["ok"])

    def test_peg_over_limit_blocked(self):
        allocation = {"frax_lending": 0.11, "aave_v3": 0.50}
        result = check_peg_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["peg_weight"], 0.11, places=6)

    def test_susde_matched(self):
        allocation = {"susde_vault": 0.05}
        result = check_peg_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertIn("susde_vault", result["protocols"])

    def test_crvusd_matched(self):
        allocation = {"crvusd_lending_pool": 0.05}
        result = check_peg_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertIn("crvusd_lending_pool", result["protocols"])

    def test_multiple_peg_over_limit(self):
        allocation = {
            "frax_usdc": 0.06,
            "ethena_usdc": 0.06,
            "aave_v3": 0.40,
        }
        result = check_peg_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["peg_weight"], 0.12, places=6)

    def test_limit_field_returned(self):
        result = check_peg_axis({})
        self.assertEqual(result["limit"], 0.10)


class TestDurationAxis(unittest.TestCase):
    """Тесты DURATION_AXIS (лимит ≤ 30%, maturity ladder ≤ 15%)."""

    def test_empty_allocation_ok(self):
        result = check_duration_axis({}, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["duration_weight"], 0.0)

    def test_instant_exit_not_counted(self):
        # aave: exit_latency = 0h → should not be duration
        allocation = {"aave_v3": 0.40}
        latency = {"aave_v3": 0.0}
        result = check_duration_axis(allocation, latency)
        self.assertTrue(result["ok"])
        self.assertEqual(result["duration_protocols"], [])

    def test_exactly_24h_not_counted(self):
        # Boundary: exactly 24h should NOT count (> 24, not >=)
        allocation = {"some_protocol": 0.30}
        latency = {"some_protocol": 24.0}
        result = check_duration_axis(allocation, latency)
        self.assertTrue(result["ok"])
        self.assertEqual(result["duration_protocols"], [])

    def test_over_24h_counted(self):
        allocation = {"pendle_pt_eth": 0.25}
        latency = {"pendle_pt_eth": 48.0}
        result = check_duration_axis(allocation, latency)
        self.assertIn("pendle_pt_eth", result["duration_protocols"])
        self.assertAlmostEqual(result["duration_weight"], 0.25, places=6)

    def test_duration_at_limit_ok(self):
        allocation = {"pendle_pt": 0.30, "aave_v3": 0.40}
        latency = {"pendle_pt": 168.0}
        result = check_duration_axis(allocation, latency)
        self.assertTrue(result["ok"])

    def test_duration_over_limit_blocked(self):
        allocation = {"pendle_pt": 0.31, "aave_v3": 0.40}
        latency = {"pendle_pt": 168.0}
        result = check_duration_axis(allocation, latency)
        self.assertFalse(result["ok"])
        self.assertTrue(any("duration_weight" in v for v in result["violations"]))

    def test_default_duration_protocols_fallback(self):
        # "pendle" in DURATION_DEFAULT_PROTOCOLS → should get default latency
        allocation = {"pendle_usdc_pool": 0.35}
        result = check_duration_axis(allocation, {})  # empty map → use defaults
        self.assertFalse(result["ok"])  # 35% > 30% limit
        self.assertIn("pendle_usdc_pool", result["duration_protocols"])

    def test_maple_default_duration(self):
        # "maple" in DURATION_DEFAULT_PROTOCOLS
        allocation = {"maple_senior_pool": 0.35}
        result = check_duration_axis(allocation, {})
        self.assertFalse(result["ok"])

    def test_maturity_ladder_ok(self):
        allocation = {"pendle_pt_long": 0.20, "aave_v3": 0.40}
        latency = {"pendle_pt_long": 168.0, "_maturity_days": {"pendle_pt_long": 90}}
        result = check_duration_axis(allocation, latency)
        self.assertTrue(result["ok"])  # 20% dur, maturity 90d > 30d threshold → ok

    def test_maturity_ladder_short_blocked(self):
        allocation = {"pendle_pt_short": 0.20, "aave_v3": 0.40}
        latency = {"pendle_pt_short": 168.0, "_maturity_days": {"pendle_pt_short": 15}}
        result = check_duration_axis(allocation, latency)
        # short maturity: 20% > maturity_limit 15% → violated
        self.assertFalse(result["ok"])
        self.assertIn("pendle_pt_short", result["short_maturity_protocols"])

    def test_result_fields_present(self):
        result = check_duration_axis({}, {})
        for key in ["ok", "duration_weight", "short_maturity_weight",
                    "duration_limit", "maturity_limit",
                    "duration_protocols", "short_maturity_protocols", "violations"]:
            self.assertIn(key, result)


class TestBridgeAxis(unittest.TestCase):
    """Тесты BRIDGE_AXIS (per-cap ≤ 5%, суммарно ≤ 10%)."""

    def test_empty_allocation_ok(self):
        result = check_bridge_axis({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["bridge_weight"], 0.0)

    def test_no_bridge_protocols_ok(self):
        allocation = {"aave_v3": 0.40, "compound_v3": 0.35}
        result = check_bridge_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertEqual(result["protocols"], [])

    def test_per_cap_at_limit_ok(self):
        allocation = {"across_usdc": 0.05, "aave_v3": 0.40}
        result = check_bridge_axis(allocation)
        self.assertTrue(result["ok"])

    def test_per_cap_exceeded(self):
        allocation = {"across_usdc": 0.06, "aave_v3": 0.40}
        result = check_bridge_axis(allocation)
        self.assertFalse(result["ok"])
        self.assertEqual(len([v for v in result["violations"] if "across_usdc" in v]), 1)

    def test_total_limit_exceeded(self):
        allocation = {
            "across_usdc": 0.05,
            "stargate_usdc": 0.05,
            "layerzero_bridge": 0.02,
        }
        result = check_bridge_axis(allocation)
        self.assertFalse(result["ok"])
        # total 12% > 10%
        self.assertTrue(any("total bridge weight" in v for v in result["violations"]))

    def test_per_cap_and_total_both_violated(self):
        allocation = {"across_usdc": 0.08, "stargate_usdc": 0.05}
        result = check_bridge_axis(allocation)
        self.assertFalse(result["ok"])
        # violations: across per-cap + total
        self.assertGreaterEqual(len(result["violations"]), 2)

    def test_stargate_matched(self):
        allocation = {"stargate_usdc_pool": 0.04}
        result = check_bridge_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertIn("stargate_usdc_pool", result["protocols"])

    def test_layerzero_matched(self):
        allocation = {"layerzero_bridge_arb": 0.04}
        result = check_bridge_axis(allocation)
        self.assertTrue(result["ok"])
        self.assertIn("layerzero_bridge_arb", result["protocols"])


class TestCheckAllAxes(unittest.TestCase):
    """Тесты check_all_axes — интеграция всех 4 осей."""

    def test_clean_allocation_all_ok(self):
        allocation = {
            "aave_v3": 0.40,
            "compound_v3": 0.35,
            "morpho_blue": 0.15,
        }
        result = check_all_axes(allocation)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(result["violations"], [])

    def test_credit_violation_propagates(self):
        allocation = {"maple_usdc": 0.20, "aave_v3": 0.40}
        result = check_all_axes(allocation)
        self.assertFalse(result["ok"])
        self.assertEqual(result["summary"], "fail")
        self.assertTrue(any("CREDIT" in v for v in result["violations"]))

    def test_peg_violation_propagates(self):
        allocation = {"ethena_usdc": 0.15, "aave_v3": 0.40}
        result = check_all_axes(allocation)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PEG" in v for v in result["violations"]))

    def test_duration_violation_propagates(self):
        allocation = {"pendle_pt": 0.35, "aave_v3": 0.40}
        latency = {"pendle_pt": 168.0}
        result = check_all_axes(allocation, latency)
        self.assertFalse(result["ok"])
        self.assertTrue(any("DURATION" in v for v in result["violations"]))

    def test_bridge_violation_propagates(self):
        allocation = {"across_usdc": 0.08, "aave_v3": 0.40}
        result = check_all_axes(allocation)
        self.assertFalse(result["ok"])
        self.assertTrue(any("BRIDGE" in v for v in result["violations"]))

    def test_multiple_violations_all_reported(self):
        allocation = {
            "maple_usdc": 0.20,       # credit violation
            "ethena_usdc": 0.15,      # peg violation
            "aave_v3": 0.40,
        }
        result = check_all_axes(allocation)
        self.assertFalse(result["ok"])
        # Both credit and peg should be reported
        self.assertTrue(any("CREDIT" in v for v in result["violations"]))
        self.assertTrue(any("PEG" in v for v in result["violations"]))

    def test_result_has_all_four_axis_keys(self):
        result = check_all_axes({})
        for key in ["credit", "peg", "duration", "bridge"]:
            self.assertIn(key, result)

    def test_none_latency_map_ok(self):
        allocation = {"aave_v3": 0.40}
        result = check_all_axes(allocation, None)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])

    def test_substring_matching_works_end_to_end(self):
        allocation = {
            "FRAXLEND_USDC_POOL": 0.15,    # peg axis
            "MAPLE_SENIOR_USDC": 0.20,     # credit axis
        }
        result = check_all_axes(allocation)
        self.assertFalse(result["ok"])
        self.assertTrue(any("CREDIT" in v for v in result["violations"]))
        self.assertTrue(any("PEG" in v for v in result["violations"]))


class TestHelperMatches(unittest.TestCase):
    """Тесты вспомогательной функции _matches."""

    def test_exact_match(self):
        self.assertTrue(_matches("maple", ["maple"]))

    def test_substring_match(self):
        self.assertTrue(_matches("maple_usdc_pool", ["maple"]))

    def test_case_insensitive(self):
        self.assertTrue(_matches("MAPLE_USDC", ["maple"]))

    def test_no_match(self):
        self.assertFalse(_matches("aave_v3", ["maple", "clearpool"]))

    def test_multiple_names_any_match(self):
        self.assertTrue(_matches("clearpool_usdc", CREDIT_PROTOCOLS))

    def test_frax_not_in_credit(self):
        self.assertFalse(_matches("frax_usdc", CREDIT_PROTOCOLS))

    def test_frax_in_peg(self):
        self.assertTrue(_matches("fraxlend_usdc", PEG_PROTOCOLS))


if __name__ == "__main__":
    unittest.main()
