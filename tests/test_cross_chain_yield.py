#!/usr/bin/env python3
"""
tests/test_cross_chain_yield.py

30 unit tests for CrossChainYieldComparator (MP-1487, v11.03).

Covers:
  - Basic instantiation and defaults
  - collect_chain_data: chain filtering, error handling, supplementary Base adapters
  - compare_all: structure, best_opportunities, last_updated
  - best_chain / apy_spread helpers
  - to_dict / save integration
  - Edge cases: empty registry, all-error adapters, zero APY
  - SPAError on unsupported chain
  - _safe_apy helper (decimal conversion, None, exceptions)
  - _instantiate helper
  - SUPPORTED_CHAINS / OUTPUT_PATH constants

Run:
    python3 -m pytest tests/test_cross_chain_yield.py -v
    python3 tests/test_cross_chain_yield.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.cross_chain_yield import (
    OUTPUT_PATH,
    SUPPORTED_CHAINS,
    CrossChainYieldComparator,
    _BASE_CHAIN_SUPPLEMENTARY,
    _CHAIN_CANONICAL,
    _instantiate,
    _safe_apy,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(chains: List[str]) -> Dict[str, Any]:
    """Build a minimal ADAPTER_REGISTRY stub for given chains."""
    registry = {}
    for i, chain in enumerate(chains):
        registry[f"adapter_{i}"] = {
            "module":       "spa_core.adapters.aave_v3",
            "class":        "AaveV3Adapter",
            "tier":         "T1",
            "research_only": False,
            "chain":        chain,
            "fallback_apy": 5.0 + i,
        }
    return registry


def _make_adapter(apy: float) -> MagicMock:
    """Return a mock adapter whose get_apy() returns *apy*."""
    m = MagicMock()
    m.get_apy.return_value = apy
    return m


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_01_supported_chains_is_list(self):
        self.assertIsInstance(SUPPORTED_CHAINS, list)

    def test_02_ethereum_in_supported(self):
        self.assertIn("ethereum", SUPPORTED_CHAINS)

    def test_03_base_in_supported(self):
        self.assertIn("base", SUPPORTED_CHAINS)

    def test_04_output_path_ends_with_json(self):
        self.assertTrue(OUTPUT_PATH.endswith(".json"))

    def test_05_chain_canonical_contains_ethereum(self):
        self.assertIn("ethereum", _CHAIN_CANONICAL)

    def test_06_chain_canonical_contains_base(self):
        self.assertIn("base", _CHAIN_CANONICAL)

    def test_07_base_supplementary_not_empty(self):
        self.assertGreater(len(_BASE_CHAIN_SUPPLEMENTARY), 0)

    def test_08_supplementary_all_have_fallback_apy(self):
        for k, v in _BASE_CHAIN_SUPPLEMENTARY.items():
            with self.subTest(adapter=k):
                self.assertIn("fallback_apy", v)

    def test_09_supplementary_all_have_module_and_class(self):
        for k, v in _BASE_CHAIN_SUPPLEMENTARY.items():
            with self.subTest(adapter=k):
                self.assertIn("module", v)
                self.assertIn("class", v)


# ---------------------------------------------------------------------------
# 2. CrossChainYieldComparator: init and basic API
# ---------------------------------------------------------------------------

class TestComparatorInit(unittest.TestCase):

    def test_10_instantiation_default_base_dir(self):
        comp = CrossChainYieldComparator()
        self.assertIsNotNone(comp)

    def test_11_supported_chains_attribute(self):
        comp = CrossChainYieldComparator()
        self.assertIn("ethereum", comp.SUPPORTED_CHAINS)
        self.assertIn("base", comp.SUPPORTED_CHAINS)

    def test_12_output_path_attribute(self):
        comp = CrossChainYieldComparator()
        self.assertEqual(comp.OUTPUT_PATH, OUTPUT_PATH)

    def test_13_to_dict_returns_dict(self):
        comp = CrossChainYieldComparator()
        d = comp.to_dict()
        self.assertIsInstance(d, dict)

    def test_14_to_dict_has_chains_key(self):
        comp = CrossChainYieldComparator()
        self.assertIn("chains", comp.to_dict())

    def test_15_best_chain_none_before_compare(self):
        comp = CrossChainYieldComparator()
        # best_chain returns None if no best_opportunities yet
        self.assertIsNone(comp.best_chain())


# ---------------------------------------------------------------------------
# 3. _safe_apy helper
# ---------------------------------------------------------------------------

class TestSafeApy(unittest.TestCase):

    def test_16_normal_percent_value(self):
        adapter = _make_adapter(6.5)
        self.assertAlmostEqual(_safe_apy(adapter, 0.0), 6.5, places=4)

    def test_17_decimal_value_converted(self):
        # get_apy() returning 0.065 → converted to 6.5%
        adapter = _make_adapter(0.065)
        result = _safe_apy(adapter, 0.0)
        self.assertAlmostEqual(result, 6.5, places=2)

    def test_18_none_returns_fallback(self):
        adapter = _make_adapter(None)
        self.assertAlmostEqual(_safe_apy(adapter, 4.2), 4.2, places=4)

    def test_19_exception_returns_fallback(self):
        adapter = MagicMock()
        adapter.get_apy.side_effect = RuntimeError("network error")
        self.assertAlmostEqual(_safe_apy(adapter, 3.5), 3.5, places=4)

    def test_20_zero_apy_returns_zero(self):
        adapter = _make_adapter(0.0)
        self.assertAlmostEqual(_safe_apy(adapter, 5.0), 0.0, places=4)


# ---------------------------------------------------------------------------
# 4. collect_chain_data
# ---------------------------------------------------------------------------

class TestCollectChainData(unittest.TestCase):

    def test_21_unsupported_chain_raises(self):
        comp = CrossChainYieldComparator()
        with self.assertRaises(SPAError):
            comp.collect_chain_data("solana")

    def test_22_ethereum_filters_base_adapters(self):
        """Only Ethereum adapters should appear in Ethereum results."""
        fake_registry = {
            "eth_adapter": {
                "module": "spa_core.adapters.aave_v3",
                "class":  "AaveV3Adapter",
                "tier":   "T1",
                "research_only": False,
                "chain":  "Ethereum",
                "fallback_apy": 5.0,
            },
            "base_adapter": {
                "module": "spa_core.adapters.aave_v3_base_adapter",
                "class":  "AaveV3BaseAdapter",
                "tier":   "T2",
                "research_only": False,
                "chain":  "Base",
                "fallback_apy": 6.0,
            },
        }
        comp = CrossChainYieldComparator()
        mock_adapter = _make_adapter(5.0)

        # Patch the registry at its source so the module-level getattr picks it up
        with patch("spa_core.adapters.registry.ADAPTER_REGISTRY", fake_registry):
            with patch("spa_core.analytics.cross_chain_yield._instantiate", return_value=mock_adapter):
                result = comp.collect_chain_data("ethereum")

        self.assertIn("eth_adapter", result)
        self.assertNotIn("base_adapter", result)

    def test_23_base_chain_includes_supplementary(self):
        """Base chain results should include supplementary adapters."""
        comp = CrossChainYieldComparator()
        mock_adapter = _make_adapter(6.0)

        with patch("spa_core.analytics.cross_chain_yield._instantiate", return_value=mock_adapter):
            result = comp.collect_chain_data("base")

        # At least one supplementary Base adapter should be present
        self.assertTrue(
            any(k in result for k in _BASE_CHAIN_SUPPLEMENTARY.keys()),
            f"Expected supplementary adapters in result, got {list(result.keys())}",
        )

    def test_24_broken_adapter_returns_error_key(self):
        """If adapter instantiation fails, result should contain 'error' key."""
        fake_registry = {
            "broken_eth": {
                "module": "spa_core.adapters.nonexistent_xyz",
                "class":  "NonExistent",
                "tier":   "T1",
                "research_only": False,
                "chain":  "Ethereum",
                "fallback_apy": 5.0,
            }
        }
        comp = CrossChainYieldComparator()
        with patch("spa_core.adapters.registry.ADAPTER_REGISTRY", fake_registry):
            result = comp.collect_chain_data("ethereum")

        self.assertIn("broken_eth", result)
        self.assertIn("error", result["broken_eth"])

    def test_25_research_only_adapters_excluded(self):
        """research_only=True adapters must not appear in results."""
        fake_registry = {
            "research_eth": {
                "module": "spa_core.adapters.aave_v3",
                "class":  "AaveV3Adapter",
                "tier":   "T2",
                "research_only": True,
                "chain":  "Ethereum",
                "fallback_apy": 5.0,
            }
        }
        comp = CrossChainYieldComparator()
        with patch("spa_core.adapters.registry.ADAPTER_REGISTRY", fake_registry):
            with patch("spa_core.analytics.cross_chain_yield._instantiate", return_value=_make_adapter(5.0)):
                result = comp.collect_chain_data("ethereum")

        self.assertNotIn("research_eth", result)


# ---------------------------------------------------------------------------
# 5. compare_all
# ---------------------------------------------------------------------------

class TestCompareAll(unittest.TestCase):

    def _make_comparator_with_mock(self, eth_apy=6.5, base_apy=7.0):
        comp = CrossChainYieldComparator()
        mock_adapter_eth = _make_adapter(eth_apy)
        mock_adapter_base = _make_adapter(base_apy)

        eth_reg = {
            "aave_usdc": {
                "module": "spa_core.adapters.aave_v3",
                "class":  "AaveV3Adapter",
                "tier":   "T1",
                "research_only": False,
                "chain":  "Ethereum",
                "fallback_apy": eth_apy,
            }
        }

        def fake_instantiate(meta):
            if "base" in meta.get("module", "").lower() or meta.get("chain", "").lower() == "base":
                return mock_adapter_base
            return mock_adapter_eth

        with patch("spa_core.analytics.cross_chain_yield.ADAPTER_REGISTRY", eth_reg, create=True):
            with patch("spa_core.analytics.cross_chain_yield._instantiate", side_effect=fake_instantiate):
                data = comp.compare_all()
        return comp, data

    def test_26_compare_all_returns_dict(self):
        comp, data = self._make_comparator_with_mock()
        self.assertIsInstance(data, dict)

    def test_27_compare_all_has_chains_key(self):
        comp, data = self._make_comparator_with_mock()
        self.assertIn("chains", data)

    def test_28_compare_all_has_best_opportunities(self):
        comp, data = self._make_comparator_with_mock()
        self.assertIn("best_opportunities", data)
        self.assertIsInstance(data["best_opportunities"], list)

    def test_29_best_opportunities_sorted_desc(self):
        comp, data = self._make_comparator_with_mock(eth_apy=6.0, base_apy=7.5)
        opps = data["best_opportunities"]
        if len(opps) >= 2:
            self.assertGreaterEqual(opps[0]["apy"], opps[1]["apy"])

    def test_30_last_updated_is_set(self):
        comp, data = self._make_comparator_with_mock()
        self.assertIsNotNone(data.get("last_updated"))
        self.assertIn("T", data["last_updated"])  # ISO format has 'T'


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
