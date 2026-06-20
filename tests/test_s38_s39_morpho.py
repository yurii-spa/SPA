#!/usr/bin/env python3
"""tests/test_s38_s39_morpho.py — S38 Morpho Max / S39 Morpho Max+ (MP-1247).

Covers the two Morpho-max-allocation strategies that capture Morpho Blue USDC
(highest-APY venue, 365-day mean ≈ 6.87%) by pushing its weight to / above the
T2 single-protocol cap.

S38 Morpho Max  — 20% Morpho (at cap), policy-COMPLIANT, blended ~3.95%.
S39 Morpho Max+ — 25% Morpho (above cap), RESEARCH-only, NON-compliant AS-IS.

Coverage (20 tests):
  S38 structure / weights / caps      T01–T05
  S38 allocation + APY math           T06–T09
  S38 compliance (adr_compliant=True) T10–T11
  S38 simulate + health               T12–T13
  S39 weights / above-cap             T14–T16
  S39 NON-compliance (research-only)  T17–T18
  Registry registration of S38, S39   T19–T20
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategies.s38_morpho_max import MorphoMaxStrategy, SLOTS as S38_SLOTS
from spa_core.strategies.s39_morpho_max_plus import (
    MorphoMaxPlusStrategy,
    SLOTS as S39_SLOTS,
)

CAPITAL = 100_000.0


class TestS38Structure(unittest.TestCase):
    """S38 weight structure and cap discipline."""

    def setUp(self) -> None:
        self.s = MorphoMaxStrategy()

    def test_T01_identity(self) -> None:
        self.assertEqual(self.s.STRATEGY_ID, "S38")
        self.assertEqual(self.s.TIER, "T2")

    def test_T02_weights_sum_to_one(self) -> None:
        total = sum(slot["weight"] for slot in S38_SLOTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_T03_morpho_at_t2_cap(self) -> None:
        # Morpho Blue is allocated exactly to the 20% T2 single-protocol cap.
        self.assertAlmostEqual(S38_SLOTS["morpho_blue"]["weight"], 0.20, places=9)
        self.assertLessEqual(
            S38_SLOTS["morpho_blue"]["weight"],
            self.s.T2_PER_PROTOCOL_CAP + 1e-9,
        )

    def test_T04_t2_total_within_cap(self) -> None:
        t2 = sum(s["weight"] for s in S38_SLOTS.values() if s["tier"] == "T2")
        self.assertAlmostEqual(t2, 0.40, places=9)
        self.assertLessEqual(t2, self.s.T2_TOTAL_CAP + 1e-9)

    def test_T05_cash_buffer_at_least_min(self) -> None:
        cash = sum(s["weight"] for s in S38_SLOTS.values() if s["tier"] == "CASH")
        self.assertGreaterEqual(cash, self.s.MIN_CASH_BUFFER - 1e-9)


class TestS38Allocation(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MorphoMaxStrategy()

    def test_T06_allocation_deploys_95pct(self) -> None:
        alloc = self.s.get_allocation(CAPITAL)
        deployed = sum(alloc.values())
        # 95% deployed, 5% cash held implicitly
        self.assertAlmostEqual(deployed, 95_000.0, places=2)

    def test_T07_morpho_dollar_allocation(self) -> None:
        alloc = self.s.get_allocation(CAPITAL)
        self.assertAlmostEqual(alloc["morpho_blue"], 20_000.0, places=2)

    def test_T08_zero_capital_safe(self) -> None:
        alloc = self.s.get_allocation(0.0)
        self.assertTrue(all(v == 0.0 for v in alloc.values()))

    def test_T09_expected_apy_in_range(self) -> None:
        apy = self.s.get_expected_apy()
        # Blended APY (incl. 5% cash drag) lands in the target band ~3.5–4.6%.
        self.assertGreater(apy, 3.0)
        self.assertLess(apy, 5.0)

    def test_T09b_expected_apy_beats_pure_t1(self) -> None:
        # Adding Morpho/Euler must beat a pure-T1 ~3.2% book.
        self.assertGreater(self.s.get_expected_apy(), 3.2)


class TestS38Compliance(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MorphoMaxStrategy()

    def test_T10_adr_compliant_true(self) -> None:
        rs = self.s.get_risk_summary()
        self.assertTrue(rs["adr_compliant"])
        self.assertTrue(rs["t2_per_protocol_ok"])
        self.assertTrue(rs["cash_buffer_ok"])

    def test_T11_tier_weights(self) -> None:
        rs = self.s.get_risk_summary()
        self.assertAlmostEqual(rs["t1_weight_pct"], 55.0, places=2)
        self.assertAlmostEqual(rs["t2_weight_pct"], 40.0, places=2)
        self.assertAlmostEqual(rs["cash_weight_pct"], 5.0, places=2)


class TestS38SimulateHealth(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MorphoMaxStrategy()

    def test_T12_simulate_yield_positive(self) -> None:
        res = self.s.simulate(CAPITAL)
        self.assertEqual(res["status"], "ok")
        self.assertGreater(res["expected_annual_yield_usd"], 0.0)
        self.assertAlmostEqual(res["deployed_usd"], 95_000.0, places=2)
        self.assertAlmostEqual(res["cash_usd"], 5_000.0, places=2)

    def test_T13_health_keys(self) -> None:
        h = self.s.get_health()
        self.assertEqual(h["strategy_id"], "S38")
        self.assertIn(h["overall_status"], {"ok", "degraded", "critical"})
        self.assertEqual(h["total_slots"], 4)  # 4 yield slots (cash excluded)


class TestS39Structure(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MorphoMaxPlusStrategy()

    def test_T14_weights_sum_to_one(self) -> None:
        total = sum(slot["weight"] for slot in S39_SLOTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_T15_morpho_above_current_cap(self) -> None:
        # S39 deliberately exceeds the current 20% T2 per-protocol cap.
        self.assertAlmostEqual(S39_SLOTS["morpho_blue"]["weight"], 0.25, places=9)
        self.assertGreater(
            S39_SLOTS["morpho_blue"]["weight"],
            self.s.T2_PER_PROTOCOL_CAP,
        )

    def test_T16_t2_total_still_within_cap(self) -> None:
        t2 = sum(s["weight"] for s in S39_SLOTS.values() if s["tier"] == "T2")
        self.assertAlmostEqual(t2, 0.45, places=9)
        self.assertLessEqual(t2, self.s.T2_TOTAL_CAP + 1e-9)


class TestS39NonCompliance(unittest.TestCase):
    def setUp(self) -> None:
        self.s = MorphoMaxPlusStrategy()

    def test_T17_research_only_and_non_compliant(self) -> None:
        rs = self.s.get_risk_summary()
        self.assertFalse(rs["adr_compliant"])          # blocked AS-IS
        self.assertFalse(rs["t2_per_protocol_ok"])
        self.assertTrue(rs["is_research_only"])
        self.assertTrue(self.s.IS_RESEARCH_ONLY)

    def test_T18_compliant_only_if_cap_raised(self) -> None:
        rs = self.s.get_risk_summary()
        # Would pass under the proposed 25% cap.
        self.assertTrue(rs["adr_compliant_if_cap_raised"])
        self.assertGreater(
            self.s.get_expected_apy(),
            MorphoMaxStrategy().get_expected_apy(),
        )


class TestRegistration(unittest.TestCase):
    def test_T19_s38_registered(self) -> None:
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S38")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "MorphoMaxStrategy")
        self.assertEqual(meta.risk_tier, "T2")

    def test_T20_s39_registered(self) -> None:
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S39")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "MorphoMaxPlusStrategy")
        self.assertIn("research_only", meta.tags)


if __name__ == "__main__":
    unittest.main(verbosity=2)
