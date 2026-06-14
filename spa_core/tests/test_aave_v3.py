#!/usr/bin/env python3
"""Тесты AaveV3Adapter — read-only T1-якорь (SPA-V405).

Сетевых вызовов нет: DeFiLlamaFeed подменяется фейком, который отдаёт заранее
заданные APY/TVL (или None). pytest в репо не установлен — тесты на ``unittest``::

    python3 -m unittest spa_core.tests.test_aave_v3 -v
    python3 spa_core/tests/test_aave_v3.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.aave_v3 import AaveV3Adapter
from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo


class _FakeFeed:
    """Минимальный двойник DeFiLlamaFeed: get_apy/get_tvl без сети."""

    def __init__(self, apy=None, tvl=None, raise_exc=None):
        self._apy = apy
        self._tvl = tvl
        self._raise = raise_exc
        self.calls = []

    def get_apy(self, project, symbol, chain="Ethereum"):
        self.calls.append(("apy", project, symbol, chain))
        if self._raise is not None:
            raise self._raise
        return self._apy

    def get_tvl(self, project, symbol, chain="Ethereum"):
        self.calls.append(("tvl", project, symbol, chain))
        if self._raise is not None:
            raise self._raise
        return self._tvl


def _live(apy=0.052, tvl=900_000_000.0) -> AaveV3Adapter:
    return AaveV3Adapter(feed=_FakeFeed(apy=apy, tvl=tvl))


def _dead() -> AaveV3Adapter:
    return AaveV3Adapter(feed=_FakeFeed(apy=None, tvl=None))


class TestAaveV3Adapter(unittest.TestCase):
    # ── идентичность / тир ──────────────────────────────────────────────
    def test_tier_is_t1(self):
        self.assertEqual(_live().tier, "T1")
        self.assertEqual(AaveV3Adapter.TIER, "T1")

    def test_t1_cap_is_040(self):
        self.assertEqual(AaveV3Adapter.T1_CAP, 0.40)

    def test_pool_id(self):
        self.assertEqual(AaveV3Adapter.pool_id, "aave-v3-usdc-ethereum")

    def test_protocol_key(self):
        self.assertEqual(AaveV3Adapter.PROTOCOL, "aave_v3")

    def test_defillama_selectors(self):
        self.assertEqual(AaveV3Adapter.DEFILLAMA_PROJECT, "aave-v3")
        self.assertEqual(AaveV3Adapter.DEFILLAMA_SYMBOL, "USDC")
        self.assertEqual(AaveV3Adapter.DEFILLAMA_CHAIN, "Ethereum")

    def test_is_base_adapter_subclass(self):
        self.assertIsInstance(_live(), BaseAdapter)

    # ── fetch() ─────────────────────────────────────────────────────────
    def test_fetch_returns_ok_when_live(self):
        rec = _live(apy=0.052, tvl=9e8).fetch()
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["apy"], 0.052)
        self.assertEqual(rec["tvl"], 9e8)
        self.assertTrue(rec["live_data"])
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["tier"], "T1")
        self.assertEqual(rec["pool_id"], "aave-v3-usdc-ethereum")

    def test_fetch_returns_error_when_dead(self):
        rec = _dead().fetch()
        self.assertEqual(rec["status"], "error")
        self.assertIsNone(rec["apy"])
        self.assertFalse(rec["live_data"])

    def test_fetch_returns_ok_or_error(self):
        for rec in (_live().fetch(), _dead().fetch()):
            self.assertIn(rec["status"], ("ok", "error"))

    def test_fetch_never_raises_on_feed_exception(self):
        adapter = AaveV3Adapter(feed=_FakeFeed(raise_exc=RuntimeError("net down")))
        rec = adapter.fetch()  # не должно бросить
        self.assertEqual(rec["status"], "error")
        self.assertIsNone(rec["apy"])
        self.assertIn("RuntimeError", rec["error"])

    def test_fetch_queries_correct_selectors(self):
        feed = _FakeFeed(apy=0.05, tvl=1e8)
        AaveV3Adapter(feed=feed).fetch()
        self.assertIn(("apy", "aave-v3", "USDC", "Ethereum"), feed.calls)

    # ── никаких моков ───────────────────────────────────────────────────
    def test_no_mock_fallback(self):
        # При недоступном фиде APY — строго None, а не подставленное число.
        rec = _dead().fetch()
        self.assertIsNone(rec["apy"])
        self.assertIsNone(_dead().get_apy())

    def test_no_mock_when_apy_non_numeric(self):
        # Фид вернул мусор вместо числа → честный None.
        rec = AaveV3Adapter(feed=_FakeFeed(apy="oops", tvl=1e8)).fetch()
        self.assertEqual(rec["status"], "error")
        self.assertIsNone(rec["apy"])

    # ── get_apy ─────────────────────────────────────────────────────────
    def test_get_apy_decimal_when_live(self):
        self.assertEqual(_live(apy=0.052).get_apy(), 0.052)

    def test_get_apy_none_when_dead(self):
        self.assertIsNone(_dead().get_apy())

    # ── get_yield_info ──────────────────────────────────────────────────
    def test_get_yield_info_structure(self):
        info = _live(apy=0.052, tvl=9e8).get_yield_info()
        self.assertIsInstance(info, YieldInfo)
        self.assertEqual(info.protocol, "aave_v3")
        self.assertEqual(info.asset, "USDC")
        self.assertEqual(info.apy, 0.052)
        self.assertEqual(info.tvl_usd, 9e8)
        self.assertEqual(info.tier, "T1")
        self.assertIsInstance(info.risk_score, float)

    def test_get_yield_info_apy_none_when_dead(self):
        info = _dead().get_yield_info()
        self.assertIsNone(info.apy)
        self.assertEqual(info.tier, "T1")

    def test_registered_in_adapter_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY

        entry = [r for r in ADAPTER_REGISTRY if r[0] == "aave_v3"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0][1], "T1")
        self.assertIs(entry[0][2], AaveV3Adapter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
