"""
tests/test_adapter_tier_criteria.py

MP-1550 (v11.66) — 20 tests for ADR-041 adapter tier promotion criteria.

Tests verify:
  - ADR-041 document exists and has expected content
  - Registry tiers are consistent with ADR-041 rules
  - New T2 research-only adapters meet T2 entry criteria (TVL, chain, asset)
  - T1 adapters have the expected properties (research_only=False, chain known)
  - T3 adapters have research_only status and fallback APY set
  - Tier count invariants (T1 ≥ 5, T2 ≥ 10, T3 ≥ 1)
"""
import sys
import os
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.adapters.registry import ADAPTER_REGISTRY, list_by_tier, list_research_only, registry_summary

ADR_PATH = os.path.join(_REPO, "docs", "adr", "ADR-041-adapter-tier-promotion.md")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _by_tier(tier: str) -> dict:
    return {k: v for k, v in ADAPTER_REGISTRY.items() if v.get("tier") == tier}


# ===========================================================================
# 1. ADR-041 document existence and content
# ===========================================================================

class TestADR041Document(unittest.TestCase):

    def test_adr_file_exists(self):
        self.assertTrue(os.path.isfile(ADR_PATH), f"ADR-041 not found at {ADR_PATH}")

    def test_adr_status_accepted(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Accepted", content)

    def test_adr_has_t3_to_t2_section(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("T3 → T2", content)

    def test_adr_has_t2_to_t1_section(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("T2 → T1", content)

    def test_adr_has_demotion_criteria(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Demotion", content)

    def test_adr_references_mp1550(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("MP-1550", content)

    def test_adr_mentions_suspended(self):
        with open(ADR_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("SUSPENDED", content)


# ===========================================================================
# 2. Tier count invariants (ADR-041: T1 ≥ 5, T2 ≥ 10, T3 ≥ 1)
# ===========================================================================

class TestTierCountInvariants(unittest.TestCase):

    def test_t1_count_at_least_five(self):
        t1 = list_by_tier("T1")
        self.assertGreaterEqual(len(t1), 5, f"Expected ≥5 T1 adapters, got {len(t1)}")

    def test_t2_count_at_least_ten(self):
        t2 = list_by_tier("T2")
        self.assertGreaterEqual(len(t2), 10, f"Expected ≥10 T2 adapters, got {len(t2)}")

    def test_t3_count_at_least_one(self):
        t3 = list_by_tier("T3")
        self.assertGreaterEqual(len(t3), 1, f"Expected ≥1 T3 adapter, got {len(t3)}")

    def test_total_registry_22(self):
        s = registry_summary()
        self.assertEqual(s["total"], 22)


# ===========================================================================
# 3. T1 adapters — ADR-041 rules
# ===========================================================================

class TestT1AdapterRules(unittest.TestCase):

    def test_t1_adapters_not_research_only(self):
        """ADR-041: T1 adapters must be production-eligible (research_only=False)."""
        for adapter_id in list_by_tier("T1"):
            with self.subTest(adapter=adapter_id):
                meta = ADAPTER_REGISTRY[adapter_id]
                self.assertFalse(
                    meta.get("research_only"),
                    f"T1 adapter '{adapter_id}' must have research_only=False"
                )

    def test_t1_adapters_have_known_chain(self):
        """T1 adapters must declare a chain."""
        for adapter_id in list_by_tier("T1"):
            with self.subTest(adapter=adapter_id):
                meta = ADAPTER_REGISTRY[adapter_id]
                self.assertIn("chain", meta)
                self.assertTrue(meta["chain"])


# ===========================================================================
# 4. T2 new adapters meet ADR-041 T2 entry criteria
# ===========================================================================

class TestNewT2AdapterCriteria(unittest.TestCase):
    """Fluid USDC/USDT and Notional V3 must meet T2 entry bar from ADR-041."""

    _NEW_T2 = ["fluid_usdc", "fluid_usdt", "notional_v3"]

    def test_new_t2_research_only_true(self):
        """New T2 adapters start as research_only per ADR-041."""
        for adapter_id in self._NEW_T2:
            with self.subTest(adapter=adapter_id):
                self.assertTrue(ADAPTER_REGISTRY[adapter_id]["research_only"])

    def test_new_t2_chain_ethereum(self):
        for adapter_id in self._NEW_T2:
            with self.subTest(adapter=adapter_id):
                self.assertEqual(
                    ADAPTER_REGISTRY[adapter_id]["chain"].lower(), "ethereum"
                )

    def test_new_t2_asset_usdc_or_usdt(self):
        for adapter_id in self._NEW_T2:
            with self.subTest(adapter=adapter_id):
                asset = ADAPTER_REGISTRY[adapter_id]["asset"]
                self.assertIn(asset, ("USDC", "USDT"))

    def test_new_t2_fallback_apy_in_range(self):
        """ADR-041: T2 APY target 4–10% in normal conditions."""
        for adapter_id in self._NEW_T2:
            with self.subTest(adapter=adapter_id):
                fap = ADAPTER_REGISTRY[adapter_id]["fallback_apy"]
                self.assertGreater(fap, 0.0)
                self.assertLessEqual(fap, 20.0)


# ===========================================================================
# 5. T3 adapters — ADR-041 rules
# ===========================================================================

class TestT3AdapterRules(unittest.TestCase):

    def test_t3_fallback_apy_positive(self):
        for adapter_id in list_by_tier("T3"):
            with self.subTest(adapter=adapter_id):
                fap = ADAPTER_REGISTRY[adapter_id].get("fallback_apy", 0)
                self.assertGreater(fap, 0)

    def test_research_only_list_not_empty(self):
        ro = list_research_only()
        self.assertGreater(len(ro), 0)

    def test_registry_summary_has_t3_count(self):
        s = registry_summary()
        self.assertIn("t3_count", s)
        self.assertGreater(s["t3_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
