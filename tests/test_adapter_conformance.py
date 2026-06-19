"""
tests/test_adapter_conformance.py

MP-1393 (v10.9): 30 tests for spa_core/adapters/base_migration.py

Tests cover:
  - check_adapter_interface() for each T1 adapter → conforming=True
  - check_adapter_interface() for research_only adapters → conforming=True
  - check_adapter_interface() for unknown adapter → conforming=False
  - check_all() returns full dict covering all registry adapters
  - Research adapters with research_only=True have module-level RESEARCH_ONLY=True
  - T1 adapters have research_only=False in registry
  - report() returns human-readable string
"""
import sys
import os
import importlib
import unittest

# Make repo root importable
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.adapters.base_migration import (
    check_adapter_interface,
    check_all,
    report,
)
from spa_core.adapters.registry import ADAPTER_REGISTRY, list_by_tier, list_research_only


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _conforming(adapter_id: str) -> bool:
    return check_adapter_interface(adapter_id).get("conforming", False)


# ===========================================================================
# 1. Structure of check_adapter_interface return value
# ===========================================================================

class TestCheckAdapterInterfaceStructure(unittest.TestCase):

    def test_returns_dict(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIsInstance(result, dict)

    def test_has_adapter_id_key(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIn("adapter_id", result)

    def test_has_conforming_key(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIn("conforming", result)

    def test_conforming_is_bool(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIsInstance(result["conforming"], bool)

    def test_has_missing_key(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIn("missing", result)

    def test_missing_is_list(self):
        result = check_adapter_interface("aave_usdc")
        self.assertIsInstance(result["missing"], list)

    def test_adapter_id_echoed(self):
        result = check_adapter_interface("aave_usdc")
        self.assertEqual(result["adapter_id"], "aave_usdc")


# ===========================================================================
# 2. T1 adapters — conforming=True
# ===========================================================================

class TestT1AdaptersConforming(unittest.TestCase):

    def test_aave_usdc_conforming(self):
        self.assertTrue(_conforming("aave_usdc"))

    def test_compound_usdc_conforming(self):
        self.assertTrue(_conforming("compound_usdc"))

    def test_morpho_steakhouse_conforming(self):
        self.assertTrue(_conforming("morpho_steakhouse"))

    def test_aave_arbitrum_conforming(self):
        self.assertTrue(_conforming("aave_arbitrum"))

    def test_spark_susds_conforming(self):
        self.assertTrue(_conforming("spark_susds"))

    def test_aave_optimism_conforming(self):
        self.assertTrue(_conforming("aave_optimism"))

    def test_aave_polygon_conforming(self):
        self.assertTrue(_conforming("aave_polygon"))

    def test_all_t1_adapters_conforming(self):
        """Every adapter in the T1 tier must be conforming."""
        t1_ids = list_by_tier("T1")
        self.assertTrue(len(t1_ids) > 0, "Registry must contain T1 adapters")
        for aid in t1_ids:
            with self.subTest(adapter=aid):
                self.assertTrue(_conforming(aid), f"{aid} is not conforming")


# ===========================================================================
# 3. Research-only adapters — conforming=True
# ===========================================================================

class TestResearchAdaptersConforming(unittest.TestCase):

    def test_gmx_btc_perp_conforming(self):
        self.assertTrue(_conforming("gmx_btc_perp"))

    def test_gold_proxy_conforming(self):
        self.assertTrue(_conforming("gold_proxy"))

    def test_rwa_conc_lp_conforming(self):
        self.assertTrue(_conforming("rwa_conc_lp"))

    def test_all_research_adapters_conforming(self):
        research_ids = list_research_only()
        self.assertTrue(len(research_ids) > 0, "Registry must contain research-only adapters")
        for aid in research_ids:
            with self.subTest(adapter=aid):
                self.assertTrue(_conforming(aid), f"{aid} is not conforming")


# ===========================================================================
# 4. Unknown adapter — conforming=False
# ===========================================================================

class TestUnknownAdapter(unittest.TestCase):

    def test_nonexistent_not_conforming(self):
        result = check_adapter_interface("nonexistent_xyz_999")
        self.assertFalse(result["conforming"])

    def test_nonexistent_missing_contains_registry(self):
        result = check_adapter_interface("nonexistent_xyz_999")
        self.assertIn("registry", result["missing"])

    def test_empty_string_not_conforming(self):
        result = check_adapter_interface("")
        self.assertFalse(result["conforming"])


# ===========================================================================
# 5. check_all()
# ===========================================================================

class TestCheckAll(unittest.TestCase):

    def test_check_all_returns_dict(self):
        self.assertIsInstance(check_all(), dict)

    def test_check_all_has_all_registry_adapters(self):
        results = check_all()
        for aid in ADAPTER_REGISTRY:
            self.assertIn(aid, results, f"{aid} missing from check_all() output")

    def test_check_all_each_value_has_conforming(self):
        for aid, result in check_all().items():
            with self.subTest(adapter=aid):
                self.assertIn("conforming", result)

    def test_check_all_each_value_has_missing(self):
        for aid, result in check_all().items():
            with self.subTest(adapter=aid):
                self.assertIn("missing", result)

    def test_check_all_aave_usdc_conforming(self):
        self.assertTrue(check_all()["aave_usdc"]["conforming"])

    def test_check_all_gmx_conforming(self):
        self.assertTrue(check_all()["gmx_btc_perp"]["conforming"])

    def test_check_all_total_count_matches_registry(self):
        results = check_all()
        self.assertEqual(len(results), len(ADAPTER_REGISTRY))


# ===========================================================================
# 6. research_only=True → module-level RESEARCH_ONLY=True
# ===========================================================================

class TestResearchOnlyFlag(unittest.TestCase):

    def _module_research_only(self, adapter_id: str) -> bool:
        meta = ADAPTER_REGISTRY[adapter_id]
        mod = importlib.import_module(meta["module"])
        return getattr(mod, "RESEARCH_ONLY", False) is True

    def test_gmx_module_has_research_only_true(self):
        self.assertTrue(self._module_research_only("gmx_btc_perp"))

    def test_gold_proxy_module_has_research_only_true(self):
        self.assertTrue(self._module_research_only("gold_proxy"))

    def test_rwa_conc_lp_module_has_research_only_true(self):
        self.assertTrue(self._module_research_only("rwa_conc_lp"))

    def test_t1_adapters_are_not_research_only_in_registry(self):
        for aid in list_by_tier("T1"):
            with self.subTest(adapter=aid):
                self.assertFalse(
                    ADAPTER_REGISTRY[aid].get("research_only"),
                    f"{aid} should not be research_only in registry",
                )


# ===========================================================================
# 7. report()
# ===========================================================================

class TestReport(unittest.TestCase):

    def test_report_returns_string(self):
        self.assertIsInstance(report(), str)

    def test_report_contains_aave_usdc(self):
        self.assertIn("aave_usdc", report())

    def test_report_contains_pass(self):
        self.assertIn("PASS", report())

    def test_report_contains_summary_line(self):
        r = report()
        self.assertTrue("Total:" in r and "PASS:" in r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
