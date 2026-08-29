"""Тождество резерва — по АДРЕСУ, и это не педантизм (замер 29.08).

`aave_arbitrum` объявляет константу `TVL_USD = 1_200_000_000`. Отслеживает он при этом
**USDC.e** (мостовой, `0xff970a61…`). У `aave-v3` на Arbitrum ДВА пула с символом `USDC`,
и это РАЗНЫЕ резервы:

    0xaf88d065…  нативный USDC : $43.1 млн, 2.29 %
    0xff970a61…  USDC.e (мост) : $252 тыс., 3.47 %   ← наш

То есть литерал завышал глубину НАШЕГО рынка примерно в 4800 раз. Сопоставление по
символу выбрало бы пул покрупнее и «подтвердило» бы константу — ровно так в этой сессии
родились четыре ложных отождествления подряд (stusd→STUSDS, pendle→USDAI,
euler→AUSD на Monad, usual_usd0pp→BUSD0).

Поэтому главный тест здесь — не «живое число подставилось», а «чужой пул НЕ выбран».
"""
from __future__ import annotations

import unittest

from spa_core.adapters.aave_arbitrum_adapter import AaveArbitrumAdapter

NATIVE = {"project": "aave-v3", "chain": "Arbitrum", "symbol": "USDC",
          "tvlUsd": 43_117_610.0, "apy": 2.28554,
          "underlyingTokens": ["0xaf88d065e77c8cc2239327c5edb3a432268e5831"]}
BRIDGED = {"project": "aave-v3", "chain": "Arbitrum", "symbol": "USDC",
           "tvlUsd": 251_894.0, "apy": 3.47252,
           "underlyingTokens": ["0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"]}
OTHER_CHAIN = {"project": "aave-v3", "chain": "Ethereum", "symbol": "USDC",
               "tvlUsd": 900_000_000.0, "apy": 9.0,
               "underlyingTokens": ["0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"]}


def _with_pools(pools):
    from spa_core.feeds import defi_llama_feed as feed
    real = feed.DefiLlamaFeed._load_pools
    feed.DefiLlamaFeed._load_pools = lambda self: pools
    return real


def _restore(real):
    from spa_core.feeds import defi_llama_feed as feed
    feed.DefiLlamaFeed._load_pools = real


class IdentityIsAnAddressNotAName(unittest.TestCase):
    def setUp(self):
        self._real = None

    def tearDown(self):
        if self._real is not None:
            _restore(self._real)

    def _info(self, pools):
        self._real = _with_pools(pools)
        a = AaveArbitrumAdapter()
        a._load_apy_from_status = lambda: None      # статуса нет — смотрим на пул
        return a.get_yield_info()

    def test_the_bigger_same_named_pool_is_NOT_taken(self):
        """Положительный контроль: оба пула зовутся USDC, наш — меньший."""
        info = self._info([NATIVE, BRIDGED])
        self.assertEqual(info.tvl_usd, 251_894.0,
                         "выбран нативный USDC — это ЧУЖОЙ резерв, отождествление по имени")
        self.assertEqual(info.tvl_source, "live")

    def test_same_address_on_another_chain_is_not_ours(self):
        info = self._info([OTHER_CHAIN, BRIDGED])
        self.assertEqual(info.tvl_usd, 251_894.0)

    def test_live_tvl_replaces_the_literal(self):
        """Константа $1.2 млрд завышала НАШ рынок примерно в 4800 раз."""
        info = self._info([BRIDGED])
        self.assertLess(info.tvl_usd, AaveArbitrumAdapter.TVL_USD / 1000)

    def test_apy_falls_back_to_the_pool_when_status_is_silent(self):
        self.assertAlmostEqual(self._info([BRIDGED]).apy, 0.0347252)


class LiteralIsNeverCalledLive(unittest.TestCase):
    """Обратная сторона: нет пула ⇒ константа, и она честно помечена static."""

    def tearDown(self):
        _restore(self._real)

    def test_no_matching_pool_keeps_the_literal_but_labels_it_static(self):
        self._real = _with_pools([NATIVE])          # только чужой пул
        a = AaveArbitrumAdapter()
        a._load_apy_from_status = lambda: 4.1
        info = a.get_yield_info()
        self.assertEqual(info.tvl_usd, float(AaveArbitrumAdapter.TVL_USD))
        self.assertEqual(info.tvl_source, "static")

    def test_feed_failure_does_not_break_the_adapter(self):
        from spa_core.feeds import defi_llama_feed as feed
        self._real = feed.DefiLlamaFeed._load_pools

        def boom(self):
            raise OSError("сеть недоступна")

        feed.DefiLlamaFeed._load_pools = boom
        a = AaveArbitrumAdapter()
        a._load_apy_from_status = lambda: 4.1
        info = a.get_yield_info()
        self.assertEqual(info.tvl_source, "static")
        self.assertAlmostEqual(info.apy, 0.041)


if __name__ == "__main__":
    unittest.main()
