"""Тождество актива USD0++ — точное, а не «содержит USD0» (замер 29.08).

Адаптер `usual_usd0pp` называется по активу **USD0++**, а живой пул искал так:

    DEFILLAMA_SYMBOL = "USD0"
    if self.DEFILLAMA_SYMBOL not in (r.get("symbol") or "").upper():

Подстрокой, без цепочки, с выбором крупнейшего из подошедших. Под условие в тот
день подходили `BUSD0`, `USD0A`, `SUSD0`, и отбор брал **`BUSD0` — $505.7 млн,
3.41 %**. Это число адаптер и отдавал как «доходность USD0++». Больше того:
кредитного пула USD0++ в фиде нет вовсе — актив встречается только LP-парой
`USD0++-USD0` (другой класс риска).

Поэтому главный тест здесь — не «живое число подставилось», а **«чужой пул НЕ
выбран»**, и «отсутствие названо отсутствием». Каждый тест ниже — положительный
контроль: он краснеет на коде, каким тот был до 01.09.

Второй разбираемый здесь литерал — TVL. Решение владельца 2026-08-08 («делать все
15») сняло подстановку ДОХОДНОСТИ, но в той же `fetch()` осталась подстановка
ГЛУБИНЫ (`FALLBACK_TVL_USD = 350_000_000`), причём она уезжала с `live_data=True`
в самом частом после этой починки случае: доходность из rates-API есть, пула в
фиде нет. Порог TVL RiskPolicy ($5 млн) такое число проходит, не наблюдав ничего.
"""
from __future__ import annotations

import unittest

from spa_core.adapters.usual_usd0pp_adapter import UsualUSD0PPAdapter

_DL = "https://yields.llama.fi/pools"

# Строки фида в том виде, в каком они наблюдались 29.08.
BUSD0 = {"project": "usual-usd0", "chain": "Ethereum", "symbol": "BUSD0",
         "pool": "busd0-pool-id", "tvlUsd": 505_700_000.0, "apy": 3.41}
USD0A = {"project": "usual-usd0", "chain": "Ethereum", "symbol": "USD0A",
         "pool": "usd0a-pool-id", "tvlUsd": 90_000_000.0, "apy": 7.2}
SUSD0 = {"project": "usual-usd0", "chain": "Ethereum", "symbol": "SUSD0",
         "pool": "susd0-pool-id", "tvlUsd": 120_000_000.0, "apy": 6.1}
LP_PAIR = {"project": "uniswap-v3", "chain": "Ethereum", "symbol": "USD0++-USD0",
           "pool": "lp-pool-id", "tvlUsd": 40_000_000.0, "apy": 11.0}
# Тот же LP-символ, но проект и цепочка удержаны нашими: остаётся ровно ОДНА
# различающая ось — символ. Без этого тест краснел бы из-за фильтра проекта и
# ничего не говорил бы о подстроке (сторож, никогда не видевший поломки, —
# украшение).
LP_PAIR_SAME_PROJECT = {"project": "usual-usd0", "chain": "Ethereum",
                        "symbol": "USD0++-USD0", "pool": "lp-usual-pool-id",
                        "tvlUsd": 40_000_000.0, "apy": 11.0}
OURS = {"project": "usual-usd0", "chain": "Ethereum", "symbol": "USD0++",
        "pool": "usd0pp-pool-id", "tvlUsd": 350_000_000.0, "apy": 5.0}
OURS_OTHER_CHAIN = {"project": "usual-usd0", "chain": "Arbitrum", "symbol": "USD0++",
                    "pool": "usd0pp-arb-pool-id", "tvlUsd": 900_000_000.0, "apy": 19.0}

FOREIGNERS = [BUSD0, USD0A, SUSD0, LP_PAIR]


def _feed(pools, rates=None):
    """http_get, отдающий заданный набор пулов; rates-API молчит, если не задан."""
    def _get(url, timeout):
        if _DL in url:
            return {"data": list(pools)}
        if rates is None:
            raise RuntimeError("rates API down")
        return rates
    return _get


class ForeignPoolIsNotOurs(unittest.TestCase):
    """Чужой символ не должен приниматься за свой — ни при каких TVL."""

    def test_busd0_is_not_taken(self):
        rec = UsualUSD0PPAdapter(http_get=_feed([BUSD0])).fetch()
        self.assertIsNone(rec["apy"], "BUSD0 — не USD0++; 3.41 % принадлежит ему")
        self.assertIsNone(rec["tvl"], "$505.7 млн — глубина ЧУЖОГО рынка")

    def test_no_foreigner_is_taken(self):
        rec = UsualUSD0PPAdapter(http_get=_feed(FOREIGNERS)).fetch()
        self.assertIsNone(rec["apy"])
        self.assertIsNone(rec["tvl"])
        self.assertEqual(rec["source"], "none")
        self.assertTrue(rec["stale"])
        self.assertFalse(rec["live_data"])

    def test_lp_pair_is_a_different_risk_class(self):
        """`USD0++-USD0` содержит наш символ, но это LP-пара, а не наш пул.

        Проект и цепочка held constant — красит ИМЕННО подстроку.
        """
        rec = UsualUSD0PPAdapter(http_get=_feed([LP_PAIR_SAME_PROJECT])).fetch()
        self.assertIsNone(rec["apy"])
        self.assertIsNone(rec["tvl"])

    def test_largest_foreigner_does_not_win_over_absence(self):
        """Отбор «крупнейший из подошедших» — ровно тот механизм, что промахнулся."""
        rec = UsualUSD0PPAdapter(http_get=_feed(FOREIGNERS)).fetch()
        self.assertNotEqual(rec["apy"], 0.0341)

    def test_our_symbol_on_another_chain_is_not_taken(self):
        rec = UsualUSD0PPAdapter(http_get=_feed([OURS_OTHER_CHAIN])).fetch()
        self.assertIsNone(rec["apy"], "тот же символ на другой цепочке — другой пул")


class OurPoolIsTaken(unittest.TestCase):
    """Обратная сторона: доказанно наш пул берётся, и берётся именно он."""

    def test_our_pool_is_taken_among_foreigners(self):
        rec = UsualUSD0PPAdapter(http_get=_feed(FOREIGNERS + [OURS])).fetch()
        self.assertAlmostEqual(rec["apy"], 0.05, places=6)
        self.assertAlmostEqual(rec["tvl"], 350_000_000.0, places=2)
        self.assertEqual(rec["source"], "defillama")
        self.assertTrue(rec["live_data"])

    def test_declared_pool_id_beats_every_name(self):
        """Объявлен адрес ⇒ он и решает, даже если имя/проект переименуют."""
        renamed = dict(OURS, symbol="USD0PP-V2", project="usual-v2")

        class Pinned(UsualUSD0PPAdapter):
            DEFILLAMA_POOL_ID = "usd0pp-pool-id"

        rec = Pinned(http_get=_feed(FOREIGNERS + [renamed])).fetch()
        self.assertAlmostEqual(rec["apy"], 0.05, places=6)

    def test_pool_id_absent_by_design_today(self):
        """Сегодня адрес не объявлен — и это ЗАЯВЛЕННОЕ состояние, не забывчивость.

        Кредитного пула USD0++ в фиде 29.08 не было. Пока его нет, адаптер
        отказывает; появится — сюда впишется id, и тест выше уже проверяет, что
        адрес бьёт имя.
        """
        self.assertIsNone(UsualUSD0PPAdapter.DEFILLAMA_POOL_ID)
        self.assertEqual(UsualUSD0PPAdapter.DEFILLAMA_SYMBOL, "USD0++")


class RatesApiIdentity(unittest.TestCase):
    """Тот же вопрос к rates-API эмитента: чьё это число?"""

    def test_named_key_is_accepted(self):
        """ОБРАТНЫЙ контроль: зелёный и до, и после починки — тождество в имени
        ключа было верным и остаётся; починка не должна была его сломать."""
        rec = UsualUSD0PPAdapter(
            http_get=_feed([], rates={"usd0pp_apy": 5.5})).fetch()
        self.assertAlmostEqual(rec["apy"], 0.055, places=6)
        self.assertEqual(rec["source"], "usual_api")

    def test_unnamed_top_level_apy_is_refused(self):
        """У эмитента несколько активов: безымянный `apy` не говорит, чей он."""
        rec = UsualUSD0PPAdapter(
            http_get=_feed([], rates={"apy": 12.0})).fetch()
        self.assertIsNone(rec["apy"], "12 % может быть чем угодно из линейки Usual")

    def test_foreign_row_symbol_is_refused(self):
        rec = UsualUSD0PPAdapter(http_get=_feed([], rates={
            "rates": [{"symbol": "BUSD0", "apy": 3.41},
                      {"symbol": "SUSD0", "apy": 6.1}]})).fetch()
        self.assertIsNone(rec["apy"])

    def test_our_row_symbol_is_accepted(self):
        rec = UsualUSD0PPAdapter(http_get=_feed([], rates={
            "rates": [{"symbol": "BUSD0", "apy": 3.41},
                      {"symbol": "USD0++", "apy": 5.2}]})).fetch()
        self.assertAlmostEqual(rec["apy"], 0.052, places=6)

    def test_bare_list_payload_no_longer_takes_the_max(self):
        """Раньше здесь брался `max()` по ВСЕМ строкам — без тождества вовсе."""
        rec = UsualUSD0PPAdapter(
            http_get=_feed([], rates=[{"symbol": "BUSD0", "apy": 3.41},
                                      {"symbol": "USD0A", "apy": 9.9}])).fetch()
        self.assertIsNone(rec["apy"])


class DepthIsObservedOrAbsent(unittest.TestCase):
    """TVL — второй литерал той же записи (снят 01.09)."""

    def test_no_literal_depth_when_yield_came_but_pool_did_not(self):
        """Самый частый случай после починки тождества: ставка есть, пула нет.

        До 01.09 запись уезжала с `apy` из rates-API, `live_data=True` и
        `tvl = 350_000_000` — числом, которого никто не наблюдал, и которое
        порог TVL RiskPolicy ($5 млн) пропускает.
        """
        rec = UsualUSD0PPAdapter(
            http_get=_feed(FOREIGNERS, rates={"usd0pp_apy": 5.5})).fetch()
        self.assertAlmostEqual(rec["apy"], 0.055, places=6)
        self.assertIsNone(rec["tvl"])
        self.assertTrue(rec["live_data"], "доходность наблюдали — это правда")

    def test_class_carries_no_tvl_literal_anymore(self):
        self.assertFalse(hasattr(UsualUSD0PPAdapter, "FALLBACK_TVL_USD"))
        self.assertFalse(hasattr(UsualUSD0PPAdapter, "FALLBACK_APY"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
