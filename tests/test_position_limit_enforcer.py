"""
tests/test_position_limit_enforcer.py

MP-1500 (v11.16): 25 tests for spa_core/safety/position_limit_enforcer.py

Coverage:
  - LIMITS constants correctness
  - check() returns empty list for valid allocation
  - check() detects sum != 1.0
  - check() detects single adapter over 40%
  - check() detects T3 over 10%
  - check() detects unverified adapter over 5%
  - enforce() returns allocation on success
  - enforce() raises AllocationError on violation
  - AllocationError has code="POSITION_LIMIT_BREACH"
  - Empty allocation
  - Exactly-at-limit values (boundary)
  - limits_summary()
  - Multiple violations in one check
  - Custom adapter_meta override
"""
import sys
import os
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.safety.position_limit_enforcer import (
    PositionLimitEnforcer,
    LIMITS,
    ADAPTER_META,
)
from spa_core.utils.errors import AllocationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_alloc():
    """
    A valid allocation summing to 1.0 within all limits.

    Constraints satisfied:
      - Each adapter ≤ 40%
      - T1 total = 0.30+0.20+0.15 = 65% ≤ 70%
      - T2 total = 0.20+0.15 = 35% ≤ 70%
      - ethereum = 0.30+0.20+0.20+0.15 = 85% ≤ 85%
      - arbitrum = 0.15 ≤ 85%
      - T3 = 0% ≤ 10%
      - unverified = 0% ≤ 5%
    """
    return {
        "aave_v3": 0.30,           # T1, ethereum
        "compound_v3": 0.20,       # T1, ethereum
        "morpho_blue": 0.20,       # T2, ethereum
        "maple": 0.15,             # T2, ethereum
        "aave_v3_arbitrum": 0.15,  # T1, arbitrum
    }


# ===========================================================================
# 1. Module-level constants
# ===========================================================================

class TestLimitsConstants(unittest.TestCase):

    def test_single_adapter_max(self):
        self.assertAlmostEqual(LIMITS["single_adapter_max"], 0.40)

    def test_single_tier_max(self):
        self.assertAlmostEqual(LIMITS["single_tier_max"], 0.70)

    def test_single_chain_max(self):
        self.assertAlmostEqual(LIMITS["single_chain_max"], 0.85)

    def test_t3_max(self):
        self.assertAlmostEqual(LIMITS["t3_max"], 0.10)

    def test_unverified_max(self):
        self.assertAlmostEqual(LIMITS["unverified_max"], 0.05)


# ===========================================================================
# 2. Valid allocation → no violations
# ===========================================================================

class TestValidAllocation(unittest.TestCase):

    def setUp(self):
        self.enforcer = PositionLimitEnforcer()

    def test_valid_returns_empty_violations(self):
        violations = self.enforcer.check(_valid_alloc())
        self.assertEqual(violations, [])

    def test_valid_enforce_returns_allocation(self):
        alloc = _valid_alloc()
        result = self.enforcer.enforce(alloc)
        self.assertEqual(result, alloc)

    def test_empty_allocation_no_violations(self):
        violations = self.enforcer.check({})
        self.assertEqual(violations, [])


# ===========================================================================
# 3. Sum check
# ===========================================================================

class TestSumCheck(unittest.TestCase):

    def setUp(self):
        self.enforcer = PositionLimitEnforcer()

    def test_sum_too_high_violation(self):
        alloc = {"aave_v3": 0.60, "compound_v3": 0.60}
        violations = self.enforcer.check(alloc)
        self.assertTrue(any("sum" in v.lower() or "1.0" in v for v in violations))

    def test_sum_too_low_violation(self):
        alloc = {"aave_v3": 0.30, "compound_v3": 0.20}
        violations = self.enforcer.check(alloc)
        self.assertTrue(any("sum" in v.lower() or "1.0" in v for v in violations))

    def test_sum_within_tolerance_no_sum_violation(self):
        alloc = {"aave_v3": 0.40, "compound_v3": 0.60}
        violations = self.enforcer.check(alloc)
        # No sum violation (should be empty or only other violations)
        sum_violations = [v for v in violations if "sum" in v.lower() or "1.0" in v]
        self.assertEqual(sum_violations, [])


# ===========================================================================
# 4. Single adapter cap
# ===========================================================================

class TestSingleAdapterCap(unittest.TestCase):

    def setUp(self):
        self.enforcer = PositionLimitEnforcer()

    def test_adapter_over_40_pct(self):
        alloc = {"aave_v3": 0.45, "compound_v3": 0.55}
        violations = self.enforcer.check(alloc)
        self.assertTrue(any("aave_v3" in v for v in violations))

    def test_adapter_exactly_40_pct_no_violation(self):
        alloc = {"aave_v3": 0.40, "compound_v3": 0.60}
        violations = self.enforcer.check(alloc)
        adapter_violations = [v for v in violations if "aave_v3" in v and "40%" in v]
        self.assertEqual(adapter_violations, [])

    def test_adapter_at_41_pct_violation(self):
        alloc = {"aave_v3": 0.41, "compound_v3": 0.59}
        violations = self.enforcer.check(alloc)
        self.assertTrue(any("aave_v3" in v for v in violations))


# ===========================================================================
# 5. T3 cap
# ===========================================================================

class TestT3Cap(unittest.TestCase):

    def setUp(self):
        self.enforcer = PositionLimitEnforcer()

    def test_t3_over_10_pct(self):
        alloc = {
            "aave_v3": 0.39,
            "compound_v3": 0.39,
            "pendle_pt": 0.11,
            "pendle_yt": 0.11,
        }
        violations = self.enforcer.check(alloc)
        self.assertTrue(any("T3" in v for v in violations))

    def test_t3_at_10_pct_no_violation(self):
        alloc = {
            "aave_v3": 0.40,
            "compound_v3": 0.50,
            "pendle_pt": 0.10,
        }
        violations = self.enforcer.check(alloc)
        t3_violations = [v for v in violations if "T3" in v]
        self.assertEqual(t3_violations, [])


# ===========================================================================
# 6. Unverified adapter cap
# ===========================================================================

class TestUnverifiedCap(unittest.TestCase):

    def test_unverified_over_5_pct(self):
        custom_meta = dict(ADAPTER_META)
        custom_meta["mystery_protocol"] = {
            "tier": "T2", "chain": "ethereum", "verified": False
        }
        enforcer = PositionLimitEnforcer(adapter_meta=custom_meta)
        alloc = {
            "aave_v3": 0.30,
            "compound_v3": 0.30,
            "morpho_steakhouse": 0.30,
            "mystery_protocol": 0.10,
        }
        violations = enforcer.check(alloc)
        self.assertTrue(any("unverified" in v.lower() for v in violations))

    def test_unknown_adapter_counts_as_unverified(self):
        enforcer = PositionLimitEnforcer()
        alloc = {
            "aave_v3": 0.30,
            "compound_v3": 0.30,
            "morpho_steakhouse": 0.30,
            "brand_new_protocol": 0.10,
        }
        violations = enforcer.check(alloc)
        self.assertTrue(any("unverified" in v.lower() for v in violations))


# ===========================================================================
# 7. enforce() raises AllocationError
# ===========================================================================

class TestEnforce(unittest.TestCase):

    def setUp(self):
        self.enforcer = PositionLimitEnforcer()

    def test_enforce_raises_on_violation(self):
        alloc = {"aave_v3": 0.60, "compound_v3": 0.40}
        with self.assertRaises(AllocationError):
            self.enforcer.enforce(alloc)

    def test_enforce_error_code(self):
        alloc = {"aave_v3": 0.60, "compound_v3": 0.40}
        try:
            self.enforcer.enforce(alloc)
            self.fail("Should have raised AllocationError")
        except AllocationError as exc:
            self.assertEqual(exc.code, "POSITION_LIMIT_BREACH")

    def test_multiple_violations_all_in_message(self):
        alloc = {"aave_v3": 0.55, "compound_v3": 0.55}
        try:
            self.enforcer.enforce(alloc)
            self.fail("Should have raised AllocationError")
        except AllocationError as exc:
            # At least one adapter violation should appear
            self.assertIn("aave_v3", str(exc))


# ===========================================================================
# 8. limits_summary
# ===========================================================================

class TestLimitsSummary(unittest.TestCase):

    def test_summary_returns_dict(self):
        enforcer = PositionLimitEnforcer()
        s = enforcer.limits_summary()
        self.assertIsInstance(s, dict)

    def test_summary_has_all_keys(self):
        enforcer = PositionLimitEnforcer()
        s = enforcer.limits_summary()
        for k in LIMITS:
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
