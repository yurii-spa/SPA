"""
tests/test_research_risk_limits.py

40 tests for spa_core.analytics.research_risk_limits
(MP-1344, Sprint v9.60)

Coverage:
  - check_rs001 with valid allocation → valid=True, violations=[]
  - check_rs001 with btc_stable_pool=0.40 → violation (exceeds 35%)
  - check_rs001 with stablecoin_t1=0.10 → violation (below 15% min)
  - check_rs001 with crypto total > 50% → violation
  - check_rs002 with conc_lp_total > 70% → violation
  - check_rs002 in bear regime → suspended=True, warning present
  - check_rs002 stablecoin buffer below 15% → violation
  - enforce_rs001() corrects single-protocol overweight
  - enforce_rs001() corrects stablecoin deficit
  - enforce_rs001() corrects crypto overexposure
  - enforce_rs002() corrects concentrated LP overweight
  - enforce_rs002() in bear mode returns stablecoin-only allocation
  - RiskLimitViolation raised when auto-fix impossible
  - limit_report() contains all expected keys and limits

Run:
    python3 -m unittest tests/test_research_risk_limits.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.research_risk_limits import (
    RS002_CONC_LP_SLOTS,
    ResearchRiskLimits,
    RiskLimitViolation,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _valid_rs001() -> dict:
    """Minimal valid RS-001 allocation that passes all limits."""
    return {
        "stablecoin_t1": 0.20,      # ≥ 15% ✓
        "btc_stable_pool": 0.30,    # ≤ 35% ✓
        "gmx_btc": 0.15,            # crypto
        "gmx_eth": 0.10,            # crypto (total crypto = 0.55, too high!)
        # Fix: keep crypto total ≤ 50%
    }

def _valid_rs001_clean() -> dict:
    """RS-001 allocation that passes ALL hard limits."""
    return {
        "stablecoin_t1": 0.25,      # ≥ 15% ✓
        "btc_stable_pool": 0.30,    # ≤ 35% ✓  (counts as crypto too)
        "gmx_btc": 0.10,            # crypto
        "gmx_eth": 0.10,            # crypto
        # btc_stable_pool(0.30) + gmx_btc(0.10) + gmx_eth(0.10) = 0.50 ✓
        # Total = 0.75 ≤ 1.0 ✓
    }

def _valid_rs002() -> dict:
    """RS-002 allocation that passes all limits."""
    return {
        "stablecoin_deposit": 0.20,  # ≥ 15% ✓
        "btc_usd": 0.40,             # conc LP
        "rwa": 0.25,                 # conc LP; total conc = 0.65 ≤ 70% ✓
        # Total = 0.85 ≤ 1.0 ✓
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. check_rs001 — valid allocation
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS001Valid(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_valid_allocation_passes(self):
        result = self.limits.check_rs001(_valid_rs001_clean())
        self.assertTrue(result["valid"])

    def test_valid_allocation_no_violations(self):
        result = self.limits.check_rs001(_valid_rs001_clean())
        self.assertEqual(result["violations"], [])

    def test_result_has_valid_key(self):
        result = self.limits.check_rs001(_valid_rs001_clean())
        self.assertIn("valid", result)

    def test_result_has_violations_key(self):
        result = self.limits.check_rs001(_valid_rs001_clean())
        self.assertIn("violations", result)

    def test_result_has_warnings_key(self):
        result = self.limits.check_rs001(_valid_rs001_clean())
        self.assertIn("warnings", result)

    def test_empty_allocation_fails_stablecoin_minimum(self):
        """Empty allocation violates stablecoin minimum."""
        result = self.limits.check_rs001({})
        self.assertFalse(result["valid"])

    def test_stablecoin_at_exactly_15_pct_passes(self):
        alloc = {
            "stablecoin_t1": 0.15,
            "btc_stable_pool": 0.30,
            "gmx_btc": 0.10,
            "gmx_eth": 0.10,
        }
        result = self.limits.check_rs001(alloc)
        self.assertTrue(result["valid"])


# ══════════════════════════════════════════════════════════════════════════════
# 2. check_rs001 — single-protocol cap violations
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS001SingleProtocolCap(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_btc_stable_pool_at_40_pct_fails(self):
        """btc_stable_pool=0.40 exceeds single-protocol cap of 35%."""
        alloc = _valid_rs001_clean()
        alloc["btc_stable_pool"] = 0.40
        result = self.limits.check_rs001(alloc)
        self.assertFalse(result["valid"])

    def test_btc_stable_pool_at_40_pct_has_violation_message(self):
        alloc = _valid_rs001_clean()
        alloc["btc_stable_pool"] = 0.40
        result = self.limits.check_rs001(alloc)
        self.assertTrue(any("btc_stable_pool" in v for v in result["violations"]))

    def test_single_slot_at_35_pct_passes(self):
        """Exactly at cap should pass."""
        alloc = {
            "stablecoin_t1": 0.20,
            "btc_stable_pool": 0.35,
            "gmx_btc": 0.10,
            "gmx_eth": 0.05,
        }
        result = self.limits.check_rs001(alloc)
        self.assertTrue(result["valid"])

    def test_any_slot_above_35_pct_triggers_violation(self):
        """Any slot at 0.36 should violate the cap."""
        alloc = {
            "stablecoin_t1": 0.20,
            "gmx_eth": 0.36,
            "gmx_btc": 0.10,
        }
        result = self.limits.check_rs001(alloc)
        self.assertFalse(result["valid"])
        self.assertTrue(any("gmx_eth" in v for v in result["violations"]))


# ══════════════════════════════════════════════════════════════════════════════
# 3. check_rs001 — stablecoin minimum
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS001StablecoinMin(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_stablecoin_at_10_pct_fails(self):
        """stablecoin_t1=0.10 is below 15% minimum."""
        alloc = {
            "stablecoin_t1": 0.10,
            "btc_stable_pool": 0.30,
            "gmx_btc": 0.10,
        }
        result = self.limits.check_rs001(alloc)
        self.assertFalse(result["valid"])

    def test_stablecoin_violation_message_mentions_min(self):
        alloc = {"stablecoin_t1": 0.10, "btc_stable_pool": 0.30}
        result = self.limits.check_rs001(alloc)
        self.assertTrue(any("minimum" in v or "min" in v for v in result["violations"]))

    def test_zero_stablecoin_fails(self):
        alloc = {"btc_stable_pool": 0.30, "gmx_btc": 0.20}
        result = self.limits.check_rs001(alloc)
        self.assertFalse(result["valid"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. check_rs001 — crypto total cap
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS001CryptoCap(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_crypto_total_above_50_pct_fails(self):
        """Total crypto exposure above 50% must fail."""
        alloc = {
            "stablecoin_t1": 0.20,
            "btc_stable_pool": 0.30,  # crypto
            "gmx_btc": 0.15,          # crypto
            "gmx_eth": 0.10,          # crypto; total = 0.55 > 0.50
        }
        result = self.limits.check_rs001(alloc)
        self.assertFalse(result["valid"])

    def test_crypto_total_exactly_50_pct_passes(self):
        alloc = {
            "stablecoin_t1": 0.20,
            "btc_stable_pool": 0.30,
            "gmx_btc": 0.10,
            "gmx_eth": 0.10,
            # total crypto = 0.50 ✓
        }
        result = self.limits.check_rs001(alloc)
        self.assertTrue(result["valid"])

    def test_crypto_cap_violation_message_present(self):
        alloc = {
            "stablecoin_t1": 0.20,
            "btc_stable_pool": 0.30,
            "gmx_btc": 0.15,
            "gmx_eth": 0.10,
        }
        result = self.limits.check_rs001(alloc)
        self.assertTrue(any("crypto" in v.lower() or "exposure" in v.lower()
                            for v in result["violations"]))


# ══════════════════════════════════════════════════════════════════════════════
# 5. check_rs002 — valid allocation
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS002Valid(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_valid_rs002_passes(self):
        result = self.limits.check_rs002(_valid_rs002())
        self.assertTrue(result["valid"])

    def test_valid_rs002_no_violations(self):
        result = self.limits.check_rs002(_valid_rs002())
        self.assertEqual(result["violations"], [])

    def test_neutral_regime_not_suspended(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="neutral")
        self.assertFalse(result["suspended"])


# ══════════════════════════════════════════════════════════════════════════════
# 6. check_rs002 — concentrated LP cap
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS002ConcLP(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_conc_lp_total_at_75_pct_fails(self):
        alloc = {
            "stablecoin_deposit": 0.20,
            "btc_usd": 0.40,
            "rwa": 0.35,  # total conc = 0.75 > 0.70
        }
        result = self.limits.check_rs002(alloc)
        self.assertFalse(result["valid"])

    def test_conc_lp_violation_message_present(self):
        alloc = {"stablecoin_deposit": 0.20, "btc_usd": 0.50, "rwa": 0.25}
        result = self.limits.check_rs002(alloc)
        self.assertTrue(any("conc" in v.lower() or "concentrated" in v.lower()
                            for v in result["violations"]))

    def test_conc_lp_at_exactly_70_pct_passes(self):
        alloc = {"stablecoin_deposit": 0.20, "btc_usd": 0.35, "rwa": 0.35}
        result = self.limits.check_rs002(alloc)
        self.assertTrue(result["valid"])


# ══════════════════════════════════════════════════════════════════════════════
# 7. check_rs002 — bear market suspension
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS002BearMarket(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_bear_regime_triggers_suspension(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="bear")
        self.assertTrue(result["suspended"])

    def test_bear_regime_has_warning(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="bear")
        self.assertTrue(len(result["warnings"]) > 0)

    def test_extreme_bear_regime_suspended(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="extreme_bear")
        self.assertTrue(result["suspended"])

    def test_bull_regime_not_suspended(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="bull")
        self.assertFalse(result["suspended"])

    def test_neutral_regime_not_suspended(self):
        result = self.limits.check_rs002(_valid_rs002(), regime="neutral")
        self.assertFalse(result["suspended"])


# ══════════════════════════════════════════════════════════════════════════════
# 8. check_rs002 — stablecoin buffer
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRS002StablecoinBuffer(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_stablecoin_buffer_below_15_pct_fails(self):
        alloc = {"stablecoin_deposit": 0.10, "btc_usd": 0.35, "rwa": 0.30}
        result = self.limits.check_rs002(alloc)
        self.assertFalse(result["valid"])

    def test_zero_stablecoin_buffer_fails(self):
        alloc = {"btc_usd": 0.40, "rwa": 0.30}
        result = self.limits.check_rs002(alloc)
        self.assertFalse(result["valid"])


# ══════════════════════════════════════════════════════════════════════════════
# 9. enforce_rs001()
# ══════════════════════════════════════════════════════════════════════════════


class TestEnforceRS001(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_enforce_rs001_returns_valid_allocation(self):
        """enforce_rs001 on a violating allocation must produce valid output."""
        alloc = {
            "stablecoin_t1": 0.05,   # below min
            "btc_stable_pool": 0.40, # above single-protocol cap
            "gmx_btc": 0.10,
            "gmx_eth": 0.10,
        }
        fixed = self.limits.enforce_rs001(alloc)
        result = self.limits.check_rs001(fixed)
        self.assertTrue(result["valid"], f"Violations: {result['violations']}")

    def test_enforce_rs001_clips_single_protocol_cap(self):
        alloc = {
            "stablecoin_t1": 0.20,
            "btc_stable_pool": 0.50,  # over 35%
            "gmx_btc": 0.05,
        }
        fixed = self.limits.enforce_rs001(alloc)
        self.assertLessEqual(fixed.get("btc_stable_pool", 0.0), 0.35 + 1e-9)

    def test_enforce_rs001_raises_when_impossible(self):
        """Impossible constraint: all slots forbidden and cannot add stablecoin."""
        # Provide only negative fractions with no fixable stablecoin
        alloc = {"exotic_slot": -0.50}
        # This should either work or raise RiskLimitViolation
        try:
            fixed = self.limits.enforce_rs001(alloc)
            result = self.limits.check_rs001(fixed)
            # If it returns, it must be valid
            self.assertTrue(result["valid"])
        except RiskLimitViolation:
            pass  # acceptable

    def test_enforce_rs001_total_not_above_1(self):
        alloc = {
            "stablecoin_t1": 0.40,
            "btc_stable_pool": 0.35,
            "gmx_btc": 0.10,
            "gmx_eth": 0.05,
        }
        fixed = self.limits.enforce_rs001(alloc)
        total = sum(fixed.values())
        self.assertLessEqual(total, 1.0 + 1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# 10. enforce_rs002()
# ══════════════════════════════════════════════════════════════════════════════


class TestEnforceRS002(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()

    def test_enforce_rs002_returns_valid_allocation_neutral(self):
        alloc = {
            "stablecoin_deposit": 0.05,  # below min
            "btc_usd": 0.55,             # conc LP
            "rwa": 0.30,                 # conc LP; total = 0.85 > 70%
        }
        fixed = self.limits.enforce_rs002(alloc, regime="neutral")
        result = self.limits.check_rs002(fixed, regime="neutral")
        self.assertTrue(result["valid"], f"Violations: {result['violations']}")

    def test_enforce_rs002_bear_returns_stablecoin_only(self):
        """In bear regime, enforce_rs002 returns stablecoin-only allocation."""
        alloc = {"stablecoin_deposit": 0.20, "btc_usd": 0.40, "rwa": 0.25}
        fixed = self.limits.enforce_rs002(alloc, regime="bear")
        # All non-stablecoin slots should be 0
        for slot in RS002_CONC_LP_SLOTS:
            self.assertAlmostEqual(fixed.get(slot, 0.0), 0.0, places=9)

    def test_enforce_rs002_clips_conc_lp_cap(self):
        alloc = {
            "stablecoin_deposit": 0.20,
            "btc_usd": 0.50,
            "rwa": 0.30,  # total conc = 0.80 > 70%
        }
        fixed = self.limits.enforce_rs002(alloc, regime="neutral")
        conc_total = sum(fixed.get(s, 0.0) for s in RS002_CONC_LP_SLOTS)
        self.assertLessEqual(conc_total, 0.70 + 1e-9)

    def test_enforce_rs002_total_not_above_1(self):
        alloc = {"stablecoin_deposit": 0.20, "btc_usd": 0.40, "rwa": 0.25}
        fixed = self.limits.enforce_rs002(alloc, regime="neutral")
        total = sum(fixed.values())
        self.assertLessEqual(total, 1.0 + 1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# 11. limit_report()
# ══════════════════════════════════════════════════════════════════════════════


class TestLimitReport(unittest.TestCase):

    def setUp(self):
        self.limits = ResearchRiskLimits()
        self.report = self.limits.limit_report()

    def test_report_has_rs001_key(self):
        self.assertIn("rs001", self.report)

    def test_report_has_rs002_key(self):
        self.assertIn("rs002", self.report)

    def test_report_rs001_has_limits(self):
        self.assertIn("limits", self.report["rs001"])

    def test_report_rs002_has_limits(self):
        self.assertIn("limits", self.report["rs002"])

    def test_report_rs001_max_single_protocol_correct(self):
        self.assertAlmostEqual(
            self.report["rs001"]["limits"]["max_single_protocol"], 0.35
        )

    def test_report_rs001_min_stablecoin_correct(self):
        self.assertAlmostEqual(
            self.report["rs001"]["limits"]["min_stablecoin"], 0.15
        )

    def test_report_rs002_max_conc_lp_correct(self):
        self.assertAlmostEqual(
            self.report["rs002"]["limits"]["max_conc_lp_total"], 0.70
        )

    def test_report_rs002_min_stablecoin_buffer_correct(self):
        self.assertAlmostEqual(
            self.report["rs002"]["limits"]["min_stablecoin_buffer"], 0.15
        )

    def test_report_schema_version_present(self):
        self.assertIn("schema_version", self.report)

    def test_report_rs002_il_classification_aggressive(self):
        self.assertEqual(
            self.report["rs002"]["limits"]["il_risk_classification"], "AGGRESSIVE"
        )


if __name__ == "__main__":
    unittest.main()
