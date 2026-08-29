"""Адаптер обязан выполнять контракт базового класса, иначе он неопрашиваем.

Перепись всех 36 адаптеров 29.08 нашла: `extra_finance_base` — ЕДИНСТВЕННЫЙ из 36,
кто возвращал из `get_yield_info()` словарь вместо `YieldInfo`. Любая попытка его
опросить падала:

    adapter extra_finance_base failed: 'dict' object has no attribute 'tvl_usd'

Дефект спящий: адаптер T3 и в `POLLED_ADAPTERS` не входит. Но он означал, что
кандидатом в опрос адаптер быть НЕ МОГ, и причина нигде не значилась — «его просто
не берут» и «его физически нельзя взять» выглядели одинаково.

Второй предмет здесь важнее первого: чиня контракт, легко протащить литерал.
В словаре при мёртвом фиде APY подменяется константой `APY_FALLBACK = 8.0`. Если бы
эта подстановка уехала в канонический аксессор, она стала бы «наблюдённой доходностью»
для всей системы — ровно то, что снято решением владельца 2026-08-08 («делать все 15»).
Поэтому `apy is None` при мёртвом фиде проверяется отдельно и в обе стороны.
"""
from __future__ import annotations

import unittest

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.extra_finance_base_adapter import (
    APY_FALLBACK, ExtraFinanceBaseAdapter)


def _adapter(pool):
    a = ExtraFinanceBaseAdapter()
    a._fetch_live_pool = lambda: pool          # шов: живой сети в тестах нет
    return a


class ContractOfTheBaseClass(unittest.TestCase):
    def test_returns_yield_info_not_a_dict(self):
        """Положительный контроль: именно на dict падал опрос."""
        info = _adapter({"apy": 6.9, "tvlUsd": 3_000_000.0}).get_yield_info()
        self.assertIsInstance(info, YieldInfo)
        self.assertTrue(hasattr(info, "tvl_usd"), "падало на отсутствии .tvl_usd")

    def test_apy_is_a_decimal_fraction(self):
        """Канон: apy — десятичная дробь, а фид отдаёт проценты."""
        self.assertAlmostEqual(
            _adapter({"apy": 6.9, "tvlUsd": 3_000_000.0}).get_yield_info().apy, 0.069)

    def test_orchestrator_can_actually_poll_it(self):
        """Проводка, а не деталь: контракт проверяется НАСТОЯЩИМ опросом."""
        import json
        import os
        import tempfile
        from spa_core.orchestrator.adapter_orchestrator import (
            STATUS_FILENAME, run_orchestrator)

        class _Fake(ExtraFinanceBaseAdapter):
            def _fetch_live_pool(self):
                return {"apy": 6.9, "tvlUsd": 3_000_000.0}

        d = tempfile.mkdtemp()
        run_orchestrator(registry=[("extra_finance_base", "T3", _Fake)],
                         write=True, data_dir=d)
        row = json.load(open(os.path.join(d, STATUS_FILENAME)))["adapters"][0]
        self.assertIsNone(row["error"], row)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["tvl_source"], "live")


class FallbackIsNotLaunderedIntoTheCanonicalAccessor(unittest.TestCase):
    """Обратная сторона: чиня контракт, нельзя протащить литерал как наблюдение."""

    def test_dead_feed_gives_none_not_the_literal(self):
        info = _adapter(None).get_yield_info()
        self.assertIsNone(info.apy, "мёртвый фид ⇒ наблюдения нет; 8.0 % это не наблюдение")
        self.assertEqual(info.tvl_source, "static")

    def test_the_literal_still_exists_and_is_what_we_refuse_to_return(self):
        """Контроль самого контроля: константа на месте, значит проверка не вхолостую."""
        self.assertEqual(APY_FALLBACK, 8.0)
        self.assertNotEqual(_adapter(None).get_yield_info().apy, APY_FALLBACK / 100.0)

    def test_legacy_research_dict_is_preserved_under_its_own_name(self):
        """Поведение исследовательской поверхности НЕ менялось — она лишь переименована."""
        d = _adapter(None).yield_details()
        self.assertEqual(d["apy_pct"], APY_FALLBACK)
        self.assertEqual(d["tvl_source"], "static")


if __name__ == "__main__":
    unittest.main()
