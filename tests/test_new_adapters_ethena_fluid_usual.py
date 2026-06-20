"""tests/test_new_adapters_ethena_fluid_usual.py

MP-1227 — 45 tests (15 per adapter) for three new read-only T2 adapters:
  * EthenaSusdeAdapter   (spa_core/adapters/ethena_susde_adapter.py)
  * FluidUSDCAdapter     (spa_core/adapters/fluid_usdc_adapter.py)
  * UsualUSD0PPAdapter   (spa_core/adapters/usual_usd0pp_adapter.py)

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
from spa_core.adapters.ethena_susde_adapter import EthenaSusdeAdapter
from spa_core.adapters.fluid_usdc_adapter import FluidUSDCAdapter
from spa_core.adapters.usual_usd0pp_adapter import UsualUSD0PPAdapter
from spa_core.adapters import ADAPTER_REGISTRY


# ---------------------------------------------------------------------------
# Fake HTTP openers (url, timeout) -> parsed JSON. ``_fail`` simulates outage.
# ---------------------------------------------------------------------------

def _fail(url, timeout):
    raise RuntimeError(f"simulated outage for {url}")


def _ethena_live(url, timeout):
    if "protocol-and-staking-yield" in url:
        return {"stakingYield": {"value": 9.0}}  # 9% (percent form)
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "project": "ethena-usde", "symbol": "SUSDE", "chain": "Ethereum",
            "apy": 9.2, "tvlUsd": 1_700_000_000,
        }]}
    raise RuntimeError("not mocked")


def _ethena_low_yield(url, timeout):
    if "protocol-and-staking-yield" in url:
        return {"stakingYield": {"value": 2.0}}  # 2% → below anomaly floor
    if "yields.llama.fi/pools" in url:
        return {"data": []}
    raise RuntimeError("not mocked")


def _ethena_clamp(url, timeout):
    if "protocol-and-staking-yield" in url:
        return {"stakingYield": {"value": 80.0}}  # 80% → must clamp to MAX_APY
    return {"data": []}


def _fluid_live(url, timeout):
    if "fluid.instadapp.io" in url:
        return {"data": [{"symbol": "USDC", "supplyApy": 6.5, "utilization": 85.0}]}
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "project": "fluid-lending", "symbol": "USDC", "chain": "Ethereum",
            "apy": 6.22, "tvlUsd": 116_000_000,
        }]}
    raise RuntimeError("not mocked")


def _fluid_dl_only(url, timeout):
    if "fluid.instadapp.io" in url:
        raise RuntimeError("404")
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "project": "fluid-lending", "symbol": "USDC", "chain": "Ethereum",
            "apy": 6.22, "tvlUsd": 116_000_000,
        }]}
    raise RuntimeError("not mocked")


def _fluid_clamp(url, timeout):
    if "fluid.instadapp.io" in url:
        return {"data": [{"symbol": "USDC", "supplyApy": 99.0}]}
    return {"data": []}


def _usual_live(url, timeout):
    if "usual.money" in url:
        return {"usd0pp_apy": 5.5}
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "project": "usual-usd0", "symbol": "USD0++", "chain": "Ethereum",
            "apy": 5.5, "tvlUsd": 350_000_000,
        }]}
    raise RuntimeError("not mocked")


def _usual_dl_only(url, timeout):
    if "usual.money" in url:
        raise RuntimeError("000")
    if "yields.llama.fi/pools" in url:
        return {"data": [{
            "project": "usual-usd0", "symbol": "USD0++", "chain": "Ethereum",
            "apy": 4.8, "tvlUsd": 350_000_000,
        }]}
    raise RuntimeError("not mocked")


def _usual_clamp(url, timeout):
    if "usual.money" in url:
        return {"usd0pp_apy": 75.0}
    return {"data": []}


# ===========================================================================
# 1. EthenaSusdeAdapter — 15 tests
# ===========================================================================

class TestEthenaSusdeAdapter(unittest.TestCase):

    def test_inherits_base(self):
        self.assertIsInstance(EthenaSusdeAdapter(), BaseAdapter)

    def test_tier(self):
        a = EthenaSusdeAdapter()
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")

    def test_protocol(self):
        self.assertEqual(EthenaSusdeAdapter().PROTOCOL, "ethena_susde")

    def test_asset(self):
        self.assertEqual(EthenaSusdeAdapter().asset, "sUSDe")

    def test_get_apy_live_in_range(self):
        a = EthenaSusdeAdapter(http_get=_ethena_live)
        apy = a.get_apy()
        self.assertIsInstance(apy, float)
        self.assertGreaterEqual(apy, 0.0)
        self.assertLessEqual(apy, 0.50)
        self.assertAlmostEqual(apy, 0.09, places=4)

    def test_get_apy_fallback_on_failure(self):
        a = EthenaSusdeAdapter(http_get=_fail)
        self.assertEqual(a.get_apy(), EthenaSusdeAdapter.FALLBACK_APY)

    def test_get_tvl_live_positive(self):
        a = EthenaSusdeAdapter(http_get=_ethena_live)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_tvl_fallback_positive(self):
        a = EthenaSusdeAdapter(http_get=_fail)
        self.assertEqual(a.get_tvl(), EthenaSusdeAdapter.FALLBACK_TVL_USD)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_yield_info(self):
        yi = EthenaSusdeAdapter(http_get=_ethena_live).get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertEqual(yi.protocol, "ethena_susde")
        self.assertEqual(yi.tier, "T2")
        self.assertIsNotNone(yi.apy)
        self.assertIsNotNone(yi.tvl_usd)
        self.assertEqual(yi.exit_latency_hours, 168.0)

    def test_fetch_stale_on_failure(self):
        rec = EthenaSusdeAdapter(http_get=_fail).fetch()
        self.assertTrue(rec["stale"])
        self.assertFalse(rec["live_data"])
        self.assertEqual(rec["source"], "cached")

    def test_fetch_live_flag(self):
        rec = EthenaSusdeAdapter(http_get=_ethena_live).fetch()
        self.assertTrue(rec["live_data"])
        self.assertFalse(rec["stale"])
        self.assertEqual(rec["source"], "ethena_api")

    def test_norm_apy_percent(self):
        self.assertAlmostEqual(EthenaSusdeAdapter._norm_apy(9.0), 0.09, places=6)
        self.assertAlmostEqual(EthenaSusdeAdapter._norm_apy(0.09), 0.09, places=6)
        self.assertIsNone(EthenaSusdeAdapter._norm_apy("bad"))

    def test_get_utilization_none(self):
        # staking vault has no borrow utilization
        self.assertIsNone(EthenaSusdeAdapter(http_get=_ethena_live).get_utilization())

    def test_apy_clamped_to_max(self):
        a = EthenaSusdeAdapter(http_get=_ethena_clamp)
        self.assertLessEqual(a.get_apy(), EthenaSusdeAdapter.MAX_APY)

    def test_anomaly_flag(self):
        # Low live yield trips the advisory anomaly flag; normal yield does not.
        self.assertTrue(EthenaSusdeAdapter(http_get=_ethena_low_yield).is_anomaly())
        self.assertFalse(EthenaSusdeAdapter(http_get=_ethena_live).is_anomaly())


# ===========================================================================
# 2. FluidUSDCAdapter — 15 tests
# ===========================================================================

class TestFluidUSDCAdapter(unittest.TestCase):

    def test_inherits_base(self):
        self.assertIsInstance(FluidUSDCAdapter(), BaseAdapter)

    def test_tier(self):
        a = FluidUSDCAdapter()
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")

    def test_protocol(self):
        self.assertEqual(FluidUSDCAdapter().PROTOCOL, "fluid_usdc")

    def test_asset(self):
        self.assertEqual(FluidUSDCAdapter().asset, "USDC")

    def test_get_apy_live_in_range(self):
        a = FluidUSDCAdapter(http_get=_fluid_live)
        apy = a.get_apy()
        self.assertIsInstance(apy, float)
        self.assertGreaterEqual(apy, 0.0)
        self.assertLessEqual(apy, 0.50)
        self.assertAlmostEqual(apy, 0.065, places=4)

    def test_get_apy_fallback_on_failure(self):
        a = FluidUSDCAdapter(http_get=_fail)
        self.assertEqual(a.get_apy(), FluidUSDCAdapter.FALLBACK_APY)

    def test_get_tvl_live_positive(self):
        a = FluidUSDCAdapter(http_get=_fluid_live)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_tvl_fallback_positive(self):
        a = FluidUSDCAdapter(http_get=_fail)
        self.assertEqual(a.get_tvl(), FluidUSDCAdapter.FALLBACK_TVL_USD)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_yield_info(self):
        yi = FluidUSDCAdapter(http_get=_fluid_live).get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertEqual(yi.protocol, "fluid_usdc")
        self.assertEqual(yi.tier, "T2")
        self.assertIsNotNone(yi.apy)
        self.assertIsNotNone(yi.tvl_usd)
        self.assertEqual(yi.exit_latency_hours, 0.0)

    def test_fetch_stale_on_failure(self):
        rec = FluidUSDCAdapter(http_get=_fail).fetch()
        self.assertTrue(rec["stale"])
        self.assertFalse(rec["live_data"])
        self.assertEqual(rec["source"], "cached")

    def test_fetch_live_flag(self):
        rec = FluidUSDCAdapter(http_get=_fluid_live).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "fluid_api")

    def test_norm_apy_percent(self):
        self.assertAlmostEqual(FluidUSDCAdapter._norm_apy(6.5), 0.065, places=6)
        self.assertAlmostEqual(FluidUSDCAdapter._norm_apy(0.065), 0.065, places=6)

    def test_get_utilization_live(self):
        # Fluid lending exposes a borrow utilization (85% → 0.85 decimal)
        util = FluidUSDCAdapter(http_get=_fluid_live).get_utilization()
        self.assertAlmostEqual(util, 0.85, places=4)

    def test_apy_clamped_to_max(self):
        a = FluidUSDCAdapter(http_get=_fluid_clamp)
        self.assertLessEqual(a.get_apy(), FluidUSDCAdapter.MAX_APY)

    def test_defillama_fallback(self):
        # Fluid's own API down → DeFiLlama supplies the live APY.
        rec = FluidUSDCAdapter(http_get=_fluid_dl_only).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "defillama")
        self.assertAlmostEqual(rec["apy"], 0.0622, places=4)


# ===========================================================================
# 3. UsualUSD0PPAdapter — 15 tests
# ===========================================================================

class TestUsualUSD0PPAdapter(unittest.TestCase):

    def test_inherits_base(self):
        self.assertIsInstance(UsualUSD0PPAdapter(), BaseAdapter)

    def test_tier(self):
        a = UsualUSD0PPAdapter()
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")

    def test_protocol(self):
        self.assertEqual(UsualUSD0PPAdapter().PROTOCOL, "usual_usd0pp")

    def test_asset(self):
        self.assertEqual(UsualUSD0PPAdapter().asset, "USD0++")

    def test_get_apy_live_in_range(self):
        a = UsualUSD0PPAdapter(http_get=_usual_live)
        apy = a.get_apy()
        self.assertIsInstance(apy, float)
        self.assertGreaterEqual(apy, 0.0)
        self.assertLessEqual(apy, 0.50)
        self.assertAlmostEqual(apy, 0.055, places=4)

    def test_get_apy_fallback_on_failure(self):
        a = UsualUSD0PPAdapter(http_get=_fail)
        self.assertEqual(a.get_apy(), UsualUSD0PPAdapter.FALLBACK_APY)

    def test_get_tvl_live_positive(self):
        a = UsualUSD0PPAdapter(http_get=_usual_live)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_tvl_fallback_positive(self):
        a = UsualUSD0PPAdapter(http_get=_fail)
        self.assertEqual(a.get_tvl(), UsualUSD0PPAdapter.FALLBACK_TVL_USD)
        self.assertGreater(a.get_tvl(), 0.0)

    def test_get_yield_info(self):
        yi = UsualUSD0PPAdapter(http_get=_usual_live).get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertEqual(yi.protocol, "usual_usd0pp")
        self.assertEqual(yi.tier, "T2")
        self.assertIsNotNone(yi.apy)
        self.assertIsNotNone(yi.tvl_usd)
        self.assertGreater(yi.exit_latency_hours, 0.0)

    def test_fetch_stale_on_failure(self):
        rec = UsualUSD0PPAdapter(http_get=_fail).fetch()
        self.assertTrue(rec["stale"])
        self.assertFalse(rec["live_data"])
        self.assertEqual(rec["source"], "cached")

    def test_fetch_live_flag(self):
        rec = UsualUSD0PPAdapter(http_get=_usual_live).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "usual_api")

    def test_norm_apy_percent(self):
        self.assertAlmostEqual(UsualUSD0PPAdapter._norm_apy(5.0), 0.05, places=6)
        self.assertAlmostEqual(UsualUSD0PPAdapter._norm_apy(0.05), 0.05, places=6)

    def test_get_utilization_none(self):
        self.assertIsNone(UsualUSD0PPAdapter(http_get=_usual_live).get_utilization())

    def test_apy_clamped_to_max(self):
        a = UsualUSD0PPAdapter(http_get=_usual_clamp)
        self.assertLessEqual(a.get_apy(), UsualUSD0PPAdapter.MAX_APY)

    def test_defillama_fallback(self):
        rec = UsualUSD0PPAdapter(http_get=_usual_dl_only).fetch()
        self.assertTrue(rec["live_data"])
        self.assertEqual(rec["source"], "defillama")
        self.assertAlmostEqual(rec["apy"], 0.048, places=4)


# ===========================================================================
# 4. Registry wiring (bonus — confirms STEP 6 registration)
# ===========================================================================

class TestRegistryWiring(unittest.TestCase):

    def _entry(self, key):
        return next((e for e in ADAPTER_REGISTRY if e[0] == key), None)

    def test_ethena_registered(self):
        e = self._entry("ethena_susde")
        self.assertIsNotNone(e)
        self.assertEqual(e[1], "T2")
        self.assertIs(e[2], EthenaSusdeAdapter)

    def test_fluid_registered(self):
        e = self._entry("fluid_usdc")
        self.assertIsNotNone(e)
        self.assertEqual(e[1], "T2")
        self.assertIs(e[2], FluidUSDCAdapter)

    def test_usual_registered(self):
        e = self._entry("usual_usd0pp")
        self.assertIsNotNone(e)
        self.assertEqual(e[1], "T2")
        self.assertIs(e[2], UsualUSD0PPAdapter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
