"""
tests/test_adapter_registry.py

35 unit tests for spa_core.adapters.registry.
MP-1380 (v9.96): Unified adapter registry.

Tests cover ADAPTER_REGISTRY structure, list_by_tier(), list_research_only(),
registry_summary(), validate_registry(), and get_adapter() error handling.
No real adapter imports are exercised — get_adapter() failures are simulated
without instantiating live protocol clients.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from spa_core.adapters.registry import (
    ADAPTER_REGISTRY,
    get_adapter,
    list_by_tier,
    list_research_only,
    registry_summary,
    validate_registry,
)


# ---------------------------------------------------------------------------
# 1. ADAPTER_REGISTRY structure
# ---------------------------------------------------------------------------

class TestAdapterRegistryStructure(unittest.TestCase):

    def test_01_registry_is_not_empty(self):
        """ADAPTER_REGISTRY must contain at least one entry."""
        self.assertGreater(len(ADAPTER_REGISTRY), 0)

    def test_02_all_entries_have_tier(self):
        """Every entry must have a 'tier' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("tier", meta, f"{aid} missing 'tier'")

    def test_03_all_entries_have_module(self):
        """Every entry must have a non-empty 'module' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("module", meta)
                self.assertIsInstance(meta["module"], str)
                self.assertTrue(meta["module"].strip())

    def test_04_all_entries_have_class(self):
        """Every entry must have a non-empty 'class' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("class", meta)
                self.assertIsInstance(meta["class"], str)
                self.assertTrue(meta["class"].strip())

    def test_05_all_entries_have_research_only(self):
        """Every entry must have a boolean 'research_only' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("research_only", meta)
                self.assertIsInstance(meta["research_only"], bool)

    def test_06_all_entries_have_chain(self):
        """Every entry must have a 'chain' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("chain", meta)

    def test_07_all_entries_have_asset(self):
        """Every entry must have an 'asset' key."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("asset", meta)

    def test_08_all_entries_have_fallback_apy(self):
        """Every entry must have a numeric 'fallback_apy' >= 0."""
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn("fallback_apy", meta)
                self.assertIsInstance(meta["fallback_apy"], (int, float))
                self.assertGreaterEqual(meta["fallback_apy"], 0)

    def test_09_all_tiers_are_valid(self):
        """Every 'tier' value must be T1, T2, or T3."""
        valid = {"T1", "T2", "T3"}
        for aid, meta in ADAPTER_REGISTRY.items():
            with self.subTest(adapter=aid):
                self.assertIn(meta["tier"], valid)

    def test_10_registry_is_dict(self):
        """ADAPTER_REGISTRY must be a dict (not a list or other type)."""
        self.assertIsInstance(ADAPTER_REGISTRY, dict)

    def test_11_adapter_ids_are_strings(self):
        """All registry keys (adapter IDs) must be non-empty strings."""
        for aid in ADAPTER_REGISTRY:
            self.assertIsInstance(aid, str)
            self.assertTrue(aid.strip())

    def test_12_at_least_one_t1_adapter(self):
        """Registry must contain at least one T1 adapter."""
        t1 = [a for a in ADAPTER_REGISTRY.values() if a["tier"] == "T1"]
        self.assertGreater(len(t1), 0)

    def test_13_at_least_one_t2_adapter(self):
        """Registry must contain at least one T2 adapter."""
        t2 = [a for a in ADAPTER_REGISTRY.values() if a["tier"] == "T2"]
        self.assertGreater(len(t2), 0)


# ---------------------------------------------------------------------------
# 2. list_by_tier
# ---------------------------------------------------------------------------

class TestListByTier(unittest.TestCase):

    def test_14_list_by_tier_t1_returns_only_t1(self):
        """list_by_tier('T1') returns only T1 adapter IDs."""
        ids = list_by_tier("T1")
        for aid in ids:
            self.assertEqual(ADAPTER_REGISTRY[aid]["tier"], "T1")

    def test_15_list_by_tier_t2_returns_only_t2(self):
        """list_by_tier('T2') returns only T2 adapter IDs."""
        ids = list_by_tier("T2")
        for aid in ids:
            self.assertEqual(ADAPTER_REGISTRY[aid]["tier"], "T2")

    def test_16_list_by_tier_returns_list(self):
        """list_by_tier() return type must be a list."""
        self.assertIsInstance(list_by_tier("T1"), list)

    def test_17_list_by_tier_unknown_returns_empty(self):
        """list_by_tier('TX') returns [] for unknown tier."""
        self.assertEqual(list_by_tier("TX"), [])

    def test_18_list_by_tier_t1_not_empty(self):
        """list_by_tier('T1') is non-empty."""
        self.assertGreater(len(list_by_tier("T1")), 0)

    def test_19_list_by_tier_t1_and_t2_disjoint(self):
        """T1 and T2 sets must not overlap."""
        t1_set = set(list_by_tier("T1"))
        t2_set = set(list_by_tier("T2"))
        self.assertEqual(t1_set & t2_set, set())

    def test_20_list_by_tier_covers_all_known(self):
        """Union of T1 + T2 + T3 covers the whole registry."""
        all_ids = set(ADAPTER_REGISTRY.keys())
        t1 = set(list_by_tier("T1"))
        t2 = set(list_by_tier("T2"))
        t3 = set(list_by_tier("T3"))
        self.assertEqual(t1 | t2 | t3, all_ids)


# ---------------------------------------------------------------------------
# 3. list_research_only
# ---------------------------------------------------------------------------

class TestListResearchOnly(unittest.TestCase):

    def test_21_list_research_only_returns_list(self):
        """list_research_only() return type must be a list."""
        self.assertIsInstance(list_research_only(), list)

    def test_22_list_research_only_contains_gmx(self):
        """gmx_btc_perp is a research-only adapter and must appear."""
        self.assertIn("gmx_btc_perp", list_research_only())

    def test_23_list_research_only_contains_gold_proxy(self):
        """gold_proxy is a research-only adapter and must appear."""
        self.assertIn("gold_proxy", list_research_only())

    def test_24_list_research_only_contains_rwa(self):
        """rwa_conc_lp is a research-only adapter and must appear."""
        self.assertIn("rwa_conc_lp", list_research_only())

    def test_25_all_research_only_have_flag_true(self):
        """Every ID returned by list_research_only() must have research_only=True."""
        for aid in list_research_only():
            self.assertTrue(ADAPTER_REGISTRY[aid]["research_only"])

    def test_26_t1_adapters_are_not_research_only(self):
        """All T1 adapters must have research_only=False."""
        for aid in list_by_tier("T1"):
            self.assertFalse(
                ADAPTER_REGISTRY[aid]["research_only"],
                msg=f"T1 adapter '{aid}' must not be research_only",
            )


# ---------------------------------------------------------------------------
# 4. registry_summary
# ---------------------------------------------------------------------------

class TestRegistrySummary(unittest.TestCase):

    def setUp(self):
        self.summary = registry_summary()

    def test_27_summary_returns_dict(self):
        """registry_summary() returns a dict."""
        self.assertIsInstance(self.summary, dict)

    def test_28_summary_has_total(self):
        """summary contains 'total' key equal to len(ADAPTER_REGISTRY)."""
        self.assertIn("total", self.summary)
        self.assertEqual(self.summary["total"], len(ADAPTER_REGISTRY))

    def test_29_summary_has_t1_count(self):
        """summary contains 't1_count' matching list_by_tier('T1')."""
        self.assertIn("t1_count", self.summary)
        self.assertEqual(self.summary["t1_count"], len(list_by_tier("T1")))

    def test_30_summary_has_t2_count(self):
        """summary contains 't2_count' matching list_by_tier('T2')."""
        self.assertIn("t2_count", self.summary)
        self.assertEqual(self.summary["t2_count"], len(list_by_tier("T2")))

    def test_31_summary_has_research_only_count(self):
        """summary contains 'research_only_count' matching list_research_only()."""
        self.assertIn("research_only_count", self.summary)
        self.assertEqual(self.summary["research_only_count"], len(list_research_only()))

    def test_32_summary_counts_add_up(self):
        """t1 + t2 + t3 equals total."""
        t3 = len(list_by_tier("T3"))
        self.assertEqual(
            self.summary["t1_count"] + self.summary["t2_count"] + t3,
            self.summary["total"],
        )


# ---------------------------------------------------------------------------
# 5. validate_registry
# ---------------------------------------------------------------------------

class TestValidateRegistry(unittest.TestCase):

    def test_33_validate_registry_returns_empty_list(self):
        """validate_registry() returns [] when the real registry is clean."""
        errors = validate_registry()
        self.assertIsInstance(errors, list)
        self.assertEqual(errors, [], msg=f"Registry validation errors: {errors}")

    def test_34_validate_registry_catches_missing_key(self):
        """validate_registry() reports error when a required key is missing."""
        # Temporarily inject a bad entry
        bad_entry = {
            "module": "spa_core.adapters.fake",
            "class": "FakeAdapter",
            "tier": "T1",
            # 'research_only' intentionally missing
            "chain": "Ethereum",
            "asset": "USDC",
            "fallback_apy": 5.0,
        }
        ADAPTER_REGISTRY["__test_bad__"] = bad_entry
        try:
            errors = validate_registry()
            found = any("__test_bad__" in e for e in errors)
            self.assertTrue(found, "Expected validation error for missing key not raised")
        finally:
            del ADAPTER_REGISTRY["__test_bad__"]

    def test_35_validate_registry_catches_invalid_tier(self):
        """validate_registry() reports error for an invalid tier string."""
        bad_entry = {
            "module": "spa_core.adapters.fake",
            "class": "FakeAdapter",
            "tier": "T99",          # invalid
            "research_only": False,
            "chain": "Ethereum",
            "asset": "USDC",
            "fallback_apy": 5.0,
        }
        ADAPTER_REGISTRY["__test_tier__"] = bad_entry
        try:
            errors = validate_registry()
            found = any("__test_tier__" in e for e in errors)
            self.assertTrue(found, "Expected tier validation error not raised")
        finally:
            del ADAPTER_REGISTRY["__test_tier__"]


# ---------------------------------------------------------------------------
# 6. get_adapter
# ---------------------------------------------------------------------------

class TestGetAdapter(unittest.TestCase):

    def test_36_get_adapter_raises_key_error_for_unknown(self):
        """get_adapter() raises KeyError for an unknown adapter_id."""
        with self.assertRaises(KeyError):
            get_adapter("nonexistent_adapter_xyz")

    @patch("spa_core.adapters.registry.importlib.import_module")
    def test_37_get_adapter_instantiates_adapter(self, mock_import):
        """get_adapter() calls the right module.class constructor."""
        mock_cls = MagicMock(return_value=MagicMock())
        mock_module = MagicMock()
        # The class name on the module must match what's in the registry
        adapter_id = list(ADAPTER_REGISTRY.keys())[0]
        class_name = ADAPTER_REGISTRY[adapter_id]["class"]
        setattr(mock_module, class_name, mock_cls)
        mock_import.return_value = mock_module

        instance = get_adapter(adapter_id)
        mock_cls.assert_called_once()
        self.assertIsNotNone(instance)


if __name__ == "__main__":
    unittest.main(verbosity=2)
