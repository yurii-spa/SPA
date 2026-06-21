"""tests/test_fluid_arbitrum.py

v1.276 — 15 offline tests for the new read-only T2 adapter
``FluidArbitrumUsdcAdapter`` (spa_core/adapters/fluid_arbitrum_usdc_adapter.py),
Fluid USDC lending on Arbitrum (DeFiLlama: project ``fluid-lending``, chain
``Arbitrum``, pool ``4c45cc9e-e1a4-43c9-8a3d-687d96abb07c`` ≈ $36.6M TVL /
4.96% APY).

All tests are fully offline: HTTP is injected via the ``http_get`` constructor
seam (a callable ``(url, timeout) -> parsed_json`` that may raise to simulate an
outage). No live network calls are made.
"""
import os
import sys
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.fluid_arbitrum_usdc_adapter import FluidArbitrumUsdcAdapter
from spa_core.adapters import ADAPTER_REGISTRY


# ---------------------------------------------------------------------------
# Fake HTTP openers (url, timeout) -> parsed JSON. ``_fail`` simulates outage.
# ---------------------------------------------------------------------------

def _fail(url, timeout):
    raise RuntimeError(f"simulated outage for {url}")


def _live(url, timeout):
    if "fluid.instadapp.io" in url:
        return {"data": [{"symbol": "USDC", "supplyApy": 4.96, "utilization": 82.0}]}
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "pool": "4c45cc9e-e1a4-43c9-8a3d-687d96abb07c",
            "project": "fluid-lending", "symbol": "USDC", "chain": "Arbitrum",
            "apy": 4.96, "tvlUsd": 36_642_247,
        }]}
    raise RuntimeError("not mocked")


def _dl_only(url, timeout):
    if "fluid.instadapp.io" in url:
        raise RuntimeError("404")
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "pool": "4c45cc9e-e1a4-43c9-8a3d-687d96abb07c",
            "project": "fluid-lending", "symbol": "USDC", "chain": "Arbitrum",
            "apy": 4.96, "tvlUsd": 36_642_247,
        }]}
    raise RuntimeError("not mocked")


def _clamp(url, timeout):
    if "fluid.instadapp.io" in url:
        return {"data": [{"symbol": "USDC", "supplyApy": 99.0}]}
    return {"data": []}


class TestFluidArbitrumUsdcAdapter(unittest.TestCase):

    def test_inherits_base(self):
        self.assertIsInstance(FluidArbitrumUsdcAdapter(), BaseAdapter)

    def test_tier(self):
        a = FluidArbitrumUsdcAdapter()
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")

    def test_protocol(self):
        self.assertEqual(FluidArbitrumUsdcAdapter().PROTOCOL, "fluid_arbitrum")

    def test_chain_is_arbitrum(self):
        # Capital "A" Arbitrum, matching the DeFiLlama chain param.
        self.assertEqual(FluidArbitrumUsdcAdapter().CHAIN, "Arbitrum")
        self.assertEqual(FluidArbitrumUsdcAdapter.DEFILLAMA_CHAIN, "Arbitrum")

    def test_get_apy_live_in_range(self):
        a = FluidArbitrumUsdcAdapter(http_get=_live)
        apy = a.get_apy()
        self.assertIsInstance(apy, float)
        self.assertGreaterEqual(apy, 0.0)
        self.assertLessEqual(apy, 0.50)
        self.assertAlmostEqual(apy, 0.0496, places=4)

    def test_get_apy_fallback_on_failure(self):
        a = FluidArbitrumUsdcAdapter(http_get=_fail)
        self.assertEqual(a.get_apy(), FluidArbitrumUsdcAdapter.FALLBACK_APY)
        self.assertAlmostEqual(a.get_apy(), 0.045, places=6)

    def test_get_tvl_live_positive(self):
        a = FluidArbitrumUsdcAdapter(http_get=_live)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_tvl_above_floor(self):
        # Live TVL must clear the RiskPolicy $5M floor.
        a = FluidArbitrumUsdcAdapter(http_get=_live)
        self.assertGreaterEqual(a.get_tvl(), 5_000_000.0)
        self.assertGreaterEqual(FluidArbitrumUsdcAdapter.FALLBACK_TVL_USD, 5_000_000.0)

    def test_get_tvl_fallback_positive(self):
        a = FluidArbitrumUsdcAdapter(http_get=_fail)
        self.assertEqual(a.get_tvl(), FluidArbitrumUsdcAdapter.FALLBACK_TVL_USD)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_yield_info(self):
        yi = FluidArbitrumUsdcAdapter(http_get=_live).get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertEqual(yi.protocol, "fluid_arbitrum")
        self.assertEqual(yi.tier, "T2")
        self.assertAlmostEqual(yi.risk_score, 0.38, places=6)
        self.assertIsNotNone(yi.apy)
        self.assertIsNotNone(yi.tvl_usd)
        self.assertEqual(yi.exit_latency_hours, 0.0)

    def test_fetch_stale_on_failure(self):
        rec = FluidArbitrumUsdcAdapter(http_get=_fail).fetch()
        self.assertTrue(rec["stale"])
        self.assertFalse(rec["live_data"])
        self.assertEqual(rec["source"], "cached")

    def test_fetch_live_flag(self):
        rec = FluidArbitrumUsdcAdapter(http_get=_live).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "fluid_api")
        self.assertEqual(rec["chain"], "Arbitrum")

    def test_norm_apy_percent(self):
        self.assertAlmostEqual(FluidArbitrumUsdcAdapter._norm_apy(4.96), 0.0496, places=6)
        self.assertAlmostEqual(FluidArbitrumUsdcAdapter._norm_apy(0.0496), 0.0496, places=6)

    def test_apy_clamped_to_max(self):
        a = FluidArbitrumUsdcAdapter(http_get=_clamp)
        self.assertLessEqual(a.get_apy(), FluidArbitrumUsdcAdapter.MAX_APY)

    def test_defillama_fallback_by_pool_id(self):
        # Fluid's own API down → DeFiLlama supplies the live APY, matched by
        # the exact Arbitrum pool id.
        rec = FluidArbitrumUsdcAdapter(http_get=_dl_only).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "defillama")
        self.assertAlmostEqual(rec["apy"], 0.0496, places=4)
        self.assertAlmostEqual(rec["tvl"], 36_642_247, places=0)

    def test_registered_in_registry(self):
        entry = [e for e in ADAPTER_REGISTRY if e[0] == "fluid_arbitrum"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0][1], "T2")
        self.assertIs(entry[0][2], FluidArbitrumUsdcAdapter)


if __name__ == "__main__":
    unittest.main()
