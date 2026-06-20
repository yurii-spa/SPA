"""
tests/test_fluid_notional_adapters.py

MP-1547 (v11.63) — 25 tests for FluidUSDCAdapter, FluidUSDTAdapter,
NotionalV3Adapter, and their registry entries.

All tests use offline stubs (no live network calls).
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.adapters.fluid_adapter import FluidUSDCAdapter, FluidUSDTAdapter
from spa_core.adapters.notional_v3_adapter import NotionalV3Adapter
from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.registry import ADAPTER_REGISTRY, registry_summary


# ---------------------------------------------------------------------------
# Helper — mock feed returning a fixed APY pool dict
# ---------------------------------------------------------------------------

def _make_feed(apy_pct: float = 5.5):
    """Return a mock DeFiLlamaFeed that yields a pool with given APY %."""
    feed = MagicMock()
    if apy_pct is None:
        feed.get_pool.return_value = None
    else:
        feed.get_pool.return_value = {"apy": apy_pct, "tvlUsd": 2_000_000_000}
    return feed


# ===========================================================================
# 1. FluidUSDCAdapter — class attributes
# ===========================================================================

class TestFluidUSDCAttributes(unittest.TestCase):

    def setUp(self):
        self.adapter = FluidUSDCAdapter(feed=_make_feed())

    def test_protocol(self):
        self.assertEqual(self.adapter.PROTOCOL, "fluid_usdc")

    def test_asset(self):
        self.assertEqual(self.adapter.ASSET, "USDC")

    def test_chain(self):
        self.assertEqual(self.adapter.CHAIN, "ethereum")

    def test_tier(self):
        self.assertEqual(self.adapter.TIER, "T2")
        self.assertEqual(self.adapter.tier, "T2")

    def test_research_only_true(self):
        self.assertTrue(self.adapter.RESEARCH_ONLY)

    def test_fallback_apy_decimal(self):
        """FALLBACK_APY must be a decimal in [0, 1]."""
        self.assertIsInstance(self.adapter.FALLBACK_APY, float)
        self.assertGreater(self.adapter.FALLBACK_APY, 0.0)
        self.assertLess(self.adapter.FALLBACK_APY, 1.0)

    def test_inherits_base_adapter(self):
        self.assertIsInstance(self.adapter, BaseAdapter)


# ===========================================================================
# 2. FluidUSDCAdapter — APY methods
# ===========================================================================

class TestFluidUSDCApyMethods(unittest.TestCase):

    def test_fetch_apy_from_feed(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(apy_pct=6.0))
        # DeFiLlama returns pct → adapter converts to decimal
        self.assertAlmostEqual(adapter.fetch_apy(), 0.060, places=4)

    def test_fetch_apy_fallback_on_no_pool(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(apy_pct=None))
        self.assertEqual(adapter.fetch_apy(), FluidUSDCAdapter.FALLBACK_APY)

    def test_safe_apy_clamped_to_max(self):
        feed = _make_feed(apy_pct=50.0)  # 50% → 0.50 decimal
        adapter = FluidUSDCAdapter(feed=feed)
        self.assertLessEqual(adapter.safe_apy(), adapter.MAX_APY)

    def test_safe_apy_clamped_to_min(self):
        feed = _make_feed(apy_pct=0.001)  # 0.001% → tiny decimal
        adapter = FluidUSDCAdapter(feed=feed)
        self.assertGreaterEqual(adapter.safe_apy(), adapter.MIN_APY)

    def test_get_apy_returns_float(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(6.0))
        result = adapter.get_apy()
        self.assertIsInstance(result, float)

    def test_get_apy_matches_safe_apy(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(5.5))
        self.assertEqual(adapter.get_apy(), adapter.safe_apy())

    def test_get_yield_info_returns_yield_info(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(5.5))
        yi = adapter.get_yield_info()
        self.assertIsInstance(yi, YieldInfo)

    def test_get_yield_info_fields(self):
        adapter = FluidUSDCAdapter(feed=_make_feed(5.0))
        yi = adapter.get_yield_info()
        self.assertEqual(yi.protocol, "fluid_usdc")
        self.assertEqual(yi.tier, "T2")
        self.assertIsNotNone(yi.apy)
        self.assertIsNotNone(yi.tvl_usd)
        self.assertIsNotNone(yi.exit_latency_hours)


# ===========================================================================
# 3. FluidUSDTAdapter
# ===========================================================================

class TestFluidUSDTAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = FluidUSDTAdapter(feed=_make_feed(apy_pct=5.4))

    def test_protocol(self):
        self.assertEqual(self.adapter.PROTOCOL, "fluid_usdt")

    def test_asset(self):
        self.assertEqual(self.adapter.ASSET, "USDT")

    def test_tier(self):
        self.assertEqual(self.adapter.TIER, "T2")

    def test_research_only(self):
        self.assertTrue(self.adapter.RESEARCH_ONLY)

    def test_fallback_apy_decimal(self):
        self.assertLess(self.adapter.FALLBACK_APY, 1.0)

    def test_inherits_fluid_usdc(self):
        self.assertIsInstance(self.adapter, FluidUSDCAdapter)

    def test_get_yield_info_asset(self):
        # asset passed to constructor should appear in YieldInfo
        adapter = FluidUSDTAdapter(asset="USDT", feed=_make_feed(5.4))
        yi = adapter.get_yield_info()
        self.assertEqual(yi.protocol, "fluid_usdt")


# ===========================================================================
# 4. NotionalV3Adapter
# ===========================================================================

class TestNotionalV3Adapter(unittest.TestCase):

    def setUp(self):
        self.adapter = NotionalV3Adapter(feed=_make_feed(apy_pct=5.0))

    def test_protocol(self):
        self.assertEqual(self.adapter.PROTOCOL, "notional_v3")

    def test_asset(self):
        self.assertEqual(self.adapter.ASSET, "USDC")

    def test_chain(self):
        self.assertEqual(self.adapter.CHAIN, "ethereum")

    def test_tier(self):
        self.assertEqual(self.adapter.TIER, "T2")

    def test_research_only_true(self):
        self.assertTrue(self.adapter.RESEARCH_ONLY)

    def test_fallback_apy_decimal(self):
        self.assertGreater(self.adapter.FALLBACK_APY, 0.0)
        self.assertLess(self.adapter.FALLBACK_APY, 1.0)

    def test_exit_latency_positive(self):
        """Notional has non-zero exit latency (fixed-rate maturity)."""
        self.assertGreater(self.adapter.EXIT_LATENCY_HOURS, 0.0)

    def test_fetch_apy_from_feed(self):
        adapter = NotionalV3Adapter(feed=_make_feed(apy_pct=6.5))
        self.assertAlmostEqual(adapter.fetch_apy(), 0.065, places=4)

    def test_fetch_apy_fallback(self):
        adapter = NotionalV3Adapter(feed=_make_feed(apy_pct=None))
        self.assertEqual(adapter.fetch_apy(), NotionalV3Adapter.FALLBACK_APY)

    def test_safe_apy_in_range(self):
        adapter = NotionalV3Adapter(feed=_make_feed(5.0))
        apy = adapter.safe_apy()
        self.assertGreaterEqual(apy, adapter.MIN_APY)
        self.assertLessEqual(apy, adapter.MAX_APY)

    def test_get_yield_info(self):
        adapter = NotionalV3Adapter(feed=_make_feed(5.0))
        yi = adapter.get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertEqual(yi.tier, "T2")


# ===========================================================================
# 5. Registry entries for new adapters (22 total)
# ===========================================================================

class TestRegistryNewEntries(unittest.TestCase):

    def test_fluid_usdc_in_registry(self):
        self.assertIn("fluid_usdc", ADAPTER_REGISTRY)

    def test_fluid_usdt_in_registry(self):
        self.assertIn("fluid_usdt", ADAPTER_REGISTRY)

    def test_notional_v3_in_registry(self):
        self.assertIn("notional_v3", ADAPTER_REGISTRY)

    def test_registry_has_22_entries(self):
        self.assertEqual(len(ADAPTER_REGISTRY), 22)

    def test_new_adapters_are_research_only(self):
        for key in ("fluid_usdc", "fluid_usdt", "notional_v3"):
            with self.subTest(adapter=key):
                self.assertTrue(ADAPTER_REGISTRY[key]["research_only"])

    def test_new_adapters_tier_t2(self):
        for key in ("fluid_usdc", "fluid_usdt", "notional_v3"):
            with self.subTest(adapter=key):
                self.assertEqual(ADAPTER_REGISTRY[key]["tier"], "T2")

    def test_registry_summary_total(self):
        s = registry_summary()
        self.assertEqual(s["total"], 22)


if __name__ == "__main__":
    unittest.main(verbosity=2)
