"""ADR-332: PT Pendle допустим только на основные стейблкоины.

Замер 11.09: фильтр «usd в символе» + выбор «максимальная ставка побеждает» поставили в
консервативную книгу PT-apyUSD-5NOV2026 — 14.05 %, пул $21 млн, 20 % капитала под видом
«pendle 8 %, T2». Высокая фиксированная ставка на малоизвестный стейбл — цена хвоста.
"""
from __future__ import annotations

import datetime
import logging
import unittest

from spa_core.adapters import pendle_adapter as pa
from spa_core.adapters.pendle_pt import PendleMarketData


def _m(name, underlying, apy, tvl=150_000_000.0):
    return PendleMarketData(
        market_address="0x" + name, name=name, underlying_asset=underlying, pt_apy=apy,
        underlying_apy=0.0, maturity_date=(datetime.date.today()
                                           + datetime.timedelta(days=90)).isoformat(),
        days_to_maturity=90, tvl_usd=tvl, liquidity_usd=tvl / 3, implied_apy=apy,
        is_expired=False, chain_id=1)


class _Fake:
    def __init__(self, markets):
        self.markets = markets

    def get_top_markets(self, **kw):
        return list(self.markets)


def _adapter(markets):
    a = pa.PendleAdapter()
    a._pt = _Fake(markets)
    a._cache = []
    # Сверка рынка с пулом DeFiLlama (ADR-239) ходит в сеть — не предмет этого файла.
    # Подменяется на экземпляре: сторож сети остановил первую редакцию теста.
    a._resolve_pool_identity = lambda best: pa.PoolIdentity(
        pool_id=None, reason="сверка с DeFiLlama подменена в тесте", candidates=0)
    return a


REAL_11_09 = [_m("PT-USD3-17DEC2026", "USD3", 14.11, 6_858_733),
              _m("PT-apyUSD-5NOV2026", "apyUSD", 14.05, 21_445_263),
              _m("PT-reUSD-10DEC2026", "reUSD", 10.95, 10_375_368)]


class TheRule(unittest.TestCase):
    def test_the_real_markets_of_11_09_are_all_refused(self):
        """СЦЕНА ЗАМЕРА: три живых рынка, ни одного на основной стейбл."""
        a = _adapter(REAL_11_09)
        self.assertEqual(a._fetch_eligible(), [])
        self.assertIsNone(a.get_yield_info().apy, "книга снова получила хвостовой PT")

    def test_a_mainstream_stable_passes(self):
        a = _adapter([_m("PT-USDC-X", "USDC", 5.1), _m("PT-apyUSD-X", "apyUSD", 14.0)])
        names = [m.name for m in a._fetch_eligible()]
        self.assertEqual(names, ["PT-USDC-X"])
        self.assertAlmostEqual(a.get_yield_info().apy, 0.051, places=6)

    def test_the_higher_rate_on_an_obscure_stable_does_not_win(self):
        """Прежняя логика взяла бы 14 % — теперь выбирается допустимый."""
        a = _adapter([_m("PT-apyUSD-X", "apyUSD", 14.0), _m("PT-sUSDS-X", "sUSDS", 4.6)])
        self.assertAlmostEqual(a.get_yield_info().apy, 0.046, places=6)

    def test_match_is_exact_not_a_substring(self):
        """«usd» в «apyUSD» и было дырой — подстрока запрещена."""
        for bad in ("apyUSD", "USD3", "reUSD", "USDe", "sUSDe", "crvUSD", "USDC-lite"):
            self.assertFalse(pa.is_admissible_underlying(bad), bad)
        for good in ("USDC", "usdc", " USDT ", "DAI", "USDS", "sUSDS", "sDAI"):
            self.assertTrue(pa.is_admissible_underlying(good), good)

    def test_refused_markets_are_named_not_silently_dropped(self):
        """Пусто из-за фильтра и пусто из-за сети — разные исходы; первый назван."""
        a = _adapter(REAL_11_09)
        with self.assertLogs(pa.logger, level=logging.INFO) as cm:
            a._fetch_eligible()
        joined = "\n".join(cm.output)
        self.assertIn("PT-apyUSD-5NOV2026", joined)
        self.assertIn("ADR-332", joined)

    def test_the_list_holds_only_what_the_owner_accepted(self):
        """Решение владельца 11.09 — ровно этот список; расширение — новым решением."""
        self.assertEqual(pa.ADMISSIBLE_UNDERLYINGS,
                         frozenset({"USDC", "USDT", "DAI", "USDS", "SUSDS", "SDAI"}))


if __name__ == "__main__":
    unittest.main()
