#!/usr/bin/env python3
"""Tests for spa_core.adapters.btc_lending (tBTC + cbBTC lending, T2, advisory).

No network: :class:`DeFiLlamaFeed` is replaced by a FakeFeed returning canned
pool dicts (or None). Mirrors the FakeFeed pattern in ``test_aave_v3.py`` /
``test_pendle_pt_adapter.py``. Run::

    python3 -m unittest spa_core.tests.test_btc_lending_adapter -v
    python3 -m pytest spa_core/tests/test_btc_lending_adapter.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters import ADAPTER_REGISTRY
from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.btc_lending import (
    BtcLendingAdapter,
    CbbtcLendingAdapter,
    TbtcLendingAdapter,
)


class _FakeFeed:
    """Minimal DeFiLlamaFeed double: get_pool() returns a canned dict or None.

    ``pools`` maps ``(project_lower, symbol_upper, chain_lower)`` -> pool dict so
    the adapter's multi-venue probe can be exercised. Any unconfigured key
    returns None (pool miss). ``raise_exc`` forces every call to raise.
    """

    def __init__(self, pools=None, raise_exc=None):
        self.pools = pools or {}
        self._raise = raise_exc
        self.calls = []

    def get_pool(self, project, symbol, chain="Ethereum"):
        self.calls.append((project, symbol, chain))
        if self._raise is not None:
            raise self._raise
        return self.pools.get((project.lower(), symbol.upper(), chain.lower()))


def _pool(apy_pct, tvl):
    return {"apy": apy_pct, "tvlUsd": tvl, "pool": "uuid-x"}


# DeFiLlama serves APY as a PERCENTAGE. tBTC Aave ETH is ~0.0006%; cbBTC ~0.0013%.
def _tbtc_feed(apy_pct=0.0006, tvl=113_000_000.0):
    return _FakeFeed({("aave-v3", "TBTC", "ethereum"): _pool(apy_pct, tvl)})


def _cbbtc_feed(apy_pct=0.0013, tvl=964_000_000.0):
    return _FakeFeed({("aave-v3", "CBBTC", "ethereum"): _pool(apy_pct, tvl)})


class TestIdentityAndTier(unittest.TestCase):
    def test_tbtc_tier_t2(self):
        a = TbtcLendingAdapter(feed=_tbtc_feed())
        self.assertEqual(a.tier, "T2")
        self.assertEqual(a.TIER, "T2")

    def test_cbbtc_tier_t2(self):
        self.assertEqual(CbbtcLendingAdapter(feed=_cbbtc_feed()).TIER, "T2")

    def test_protocol_keys(self):
        self.assertEqual(TbtcLendingAdapter(feed=_tbtc_feed()).PROTOCOL, "tbtc_lending")
        self.assertEqual(CbbtcLendingAdapter(feed=_cbbtc_feed()).PROTOCOL, "cbbtc_lending")

    def test_symbols(self):
        self.assertEqual(TbtcLendingAdapter(feed=_tbtc_feed()).SYMBOL, "TBTC")
        self.assertEqual(CbbtcLendingAdapter(feed=_cbbtc_feed()).SYMBOL, "CBBTC")

    def test_is_advisory_true(self):
        # Core deliverable contract: advisory / read-only until canary.
        self.assertTrue(TbtcLendingAdapter(feed=_tbtc_feed()).IS_ADVISORY)
        self.assertTrue(CbbtcLendingAdapter(feed=_cbbtc_feed()).IS_ADVISORY)
        self.assertTrue(BtcLendingAdapter.IS_ADVISORY)

    def test_research_only_alias_true(self):
        self.assertTrue(TbtcLendingAdapter(feed=_tbtc_feed()).RESEARCH_ONLY)

    def test_wrapper_flags(self):
        # tBTC = decentralized; cbBTC = regulated single entity.
        self.assertTrue(TbtcLendingAdapter(feed=_tbtc_feed()).decentralized)
        self.assertFalse(TbtcLendingAdapter(feed=_tbtc_feed()).regulated)
        self.assertTrue(CbbtcLendingAdapter(feed=_cbbtc_feed()).regulated)
        self.assertFalse(CbbtcLendingAdapter(feed=_cbbtc_feed()).decentralized)

    def test_no_execution_surface(self):
        # READ-ONLY domain: must NOT expose allocate/withdraw.
        a = TbtcLendingAdapter(feed=_tbtc_feed())
        self.assertFalse(hasattr(a, "allocate"))
        self.assertFalse(hasattr(a, "withdraw"))


class TestApyUnits(unittest.TestCase):
    def test_apy_is_decimal_not_percent(self):
        # Feed gives 0.0006 (percent) -> adapter must return 0.000006 (decimal).
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=0.0006))
        apy = a.get_apy()
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 0.0006 / 100.0, places=12)

    def test_low_apy_is_honest_not_inflated(self):
        # ~1% supply APY -> 0.01 decimal. We do not inflate.
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=1.0))
        self.assertAlmostEqual(a.get_apy(), 0.01, places=10)

    def test_zero_apy_is_valid(self):
        # 0% is a legitimate, expected BTC-lending reading (utilization ~0).
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=0.0))
        self.assertEqual(a.get_apy(), 0.0)

    def test_anomalous_high_apy_rejected(self):
        # >5% on "safe" BTC lending is an anomaly -> None (yield/risk mismatch).
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=9.0))
        self.assertIsNone(a.get_apy())

    def test_tvl_passthrough(self):
        a = CbbtcLendingAdapter(feed=_cbbtc_feed(tvl=964_000_000.0))
        self.assertEqual(a.get_tvl(), 964_000_000.0)


class TestGracefulNoData(unittest.TestCase):
    def test_no_pool_returns_none_apy(self):
        a = TbtcLendingAdapter(feed=_FakeFeed({}))  # no BTC pool anywhere
        self.assertIsNone(a.get_apy())

    def test_no_pool_returns_none_tvl(self):
        self.assertIsNone(TbtcLendingAdapter(feed=_FakeFeed({})).get_tvl())

    def test_feed_exception_does_not_raise(self):
        a = TbtcLendingAdapter(feed=_FakeFeed(raise_exc=RuntimeError("boom")))
        self.assertIsNone(a.get_apy())   # degrades to None, never raises
        self.assertIsNone(a.get_tvl())

    def test_non_numeric_apy_returns_none(self):
        feed = _FakeFeed({("aave-v3", "TBTC", "ethereum"): {"apy": None, "tvlUsd": 1e8}})
        self.assertIsNone(TbtcLendingAdapter(feed=feed).get_apy())

    def test_yield_info_none_when_no_data(self):
        yi = TbtcLendingAdapter(feed=_FakeFeed({})).get_yield_info()
        self.assertIsInstance(yi, YieldInfo)
        self.assertIsNone(yi.apy)
        self.assertEqual(yi.tier, "T2")


class TestEligibility(unittest.TestCase):
    def test_eligible_when_tvl_clears_floor(self):
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=0.5, tvl=113_000_000.0))
        self.assertTrue(a.tvl_ok())
        self.assertTrue(a.is_eligible())

    def test_not_eligible_below_tvl_floor(self):
        a = TbtcLendingAdapter(feed=_tbtc_feed(apy_pct=0.5, tvl=1_000_000.0))
        self.assertFalse(a.tvl_ok())
        self.assertFalse(a.is_eligible())

    def test_not_eligible_when_no_data(self):
        self.assertFalse(TbtcLendingAdapter(feed=_FakeFeed({})).is_eligible())

    def test_multi_venue_picks_highest_tvl(self):
        feed = _FakeFeed({
            ("aave-v3", "CBBTC", "ethereum"): _pool(0.0013, 964_000_000.0),
            ("aave-v3", "CBBTC", "base"): _pool(0.0177, 129_000_000.0),
        })
        a = CbbtcLendingAdapter(feed=feed)
        # ETH pool has the larger TVL -> its APY (0.0013%) is reported.
        self.assertAlmostEqual(a.get_apy(), 0.0013 / 100.0, places=12)
        self.assertEqual(a.get_tvl(), 964_000_000.0)


class TestRegistry(unittest.TestCase):
    def test_keys_present(self):
        keys = [k for (k, _t, _c) in ADAPTER_REGISTRY]
        self.assertIn("tbtc_lending", keys)
        self.assertIn("cbbtc_lending", keys)

    def test_registered_as_t2(self):
        by_key = {k: (t, c) for (k, t, c) in ADAPTER_REGISTRY}
        self.assertEqual(by_key["tbtc_lending"][0], "T2")
        self.assertEqual(by_key["cbbtc_lending"][0], "T2")

    def test_registered_classes(self):
        by_key = {k: c for (k, _t, c) in ADAPTER_REGISTRY}
        self.assertIs(by_key["tbtc_lending"], TbtcLendingAdapter)
        self.assertIs(by_key["cbbtc_lending"], CbbtcLendingAdapter)

    def test_btc_keys_filter(self):
        btc = [k for (k, _t, _c) in ADAPTER_REGISTRY if "btc" in k.lower()]
        self.assertEqual(sorted(btc), ["cbbtc_lending", "tbtc_lending"])


class TestToDict(unittest.TestCase):
    def test_to_dict_shape(self):
        d = TbtcLendingAdapter(feed=_tbtc_feed()).to_dict()
        for key in ("protocol", "tier", "is_advisory", "apy_decimal",
                    "apy_pct", "tvl_usd", "decentralized", "eligible"):
            self.assertIn(key, d)
        self.assertEqual(d["tier"], "T2")
        self.assertTrue(d["is_advisory"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
