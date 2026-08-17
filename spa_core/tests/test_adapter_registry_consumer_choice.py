"""Потребитель обязан ВЫБИРАТЬ набор адаптеров осознанно, а не по длине имени.

Цикл #274 развёл ИМЕНА трёх наборов (`ADAPTER_REGISTRY` / `ADAPTER_METADATA` /
`POLLED_ADAPTERS`), и храповик `test_adapter_registry_single_name.py` не даёт
завести четвёртое определение. Но развод имён — это половина дефекта: он делает
`grep` чистым, НЕ пересматривая, какой набор читает каждый потребитель.

Замер 2026-08-17 показал, что осталось ровно это. `PaperDay1Checklist.
check_adapter_registry` — CRITICAL-чек дня-1, который называется «adapter registry
is populated» и число которого читают как размер ВСЕЛЕННОЙ ВЫБОРА аллокатора, —
считал `len(ADAPTER_METADATA)` и докладывал **22** при канонических **36**. Молча:
22 ≥ порога 15, поэтому чек был ЗЕЛЁНЫЙ и выглядел правдой. Ровно та же ошибка,
что три месяца врала в `house_view_gap` (#206), только в отчёте дня-1.

Эти тесты — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на коде до правки `test_day1_reports_canonical_universe`
краснеет («22 adapters registered» вместо 36).

Состав наборов здесь НЕ проверяется и НЕ фиксируется числом — состав это money-path
(вселенная выбора аллокатора) и меняется owner-gated решением. Проверяется только то,
КАКОЙ набор читает потребитель.
"""

import builtins
import contextlib
import unittest
from unittest import mock

from spa_core.adapters import ADAPTER_REGISTRY as CANON
from spa_core.adapters.registry import ADAPTER_METADATA as META
from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS as POLLED
from spa_core.backtesting.paper_day1_checklist import PaperDay1Checklist


def _canon_keys() -> set:
    return {e[0] for e in CANON}


@contextlib.contextmanager
def canon_unimportable(module: str = "spa_core.adapters"):
    """Сделать `from <module> import ...` неудачным, НЕ трогая `sys.modules`.

    Наивный приём — `mock.patch.dict(sys.modules, {module: None})` — заставляет
    интерпретатор ПЕРЕИМПОРТИРОВАТЬ пакет на следующем обращении, а переимпорт
    заново присваивает `urllib.request.urlopen` и тем самым выбивает сетевой
    сторож тестового набора из цепочки (набор это замечает и чинит сам, но чинить
    за собой должен тест). Здесь вместо этого перехватывается сам `__import__`:
    целевой модуль поднимает ImportError, все остальные импорты идут как обычно,
    и ни один модуль не перезагружается.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module or name.startswith(module + "."):
            raise ImportError(f"simulated: {name} unreadable")
        return real_import(name, *args, **kwargs)

    with mock.patch.object(builtins, "__import__", fake_import):
        yield


class TestSetsStayDistinct(unittest.TestCase):
    """Страховка осмысленности: если наборы схлопнутся, тесты ниже станут пустыми.

    Это НЕ фиксация состава (числа не зашиты) — фиксируется лишь то, что три набора
    остаются РАЗНЫМИ ответами, ради чего вся эта работа и делалась.
    """

    def test_canon_is_a_strict_superset_question_from_metadata(self):
        self.assertNotEqual(
            len(CANON), len(META),
            "CANON и META совпали по размеру — тесты выбора набора обессмыслились",
        )

    def test_largest_book_position_is_canon_only(self):
        """`aave_v3` (крупнейшая позиция книги) есть в каноне и ОТСУТСТВУЕТ в метаданных."""
        self.assertIn("aave_v3", _canon_keys())
        self.assertNotIn("aave_v3", META)

    def test_polled_is_subset_of_canon(self):
        """Цикл не смеет опрашивать то, чего нет во вселенной выбора."""
        polled = {e[0] for e in POLLED}
        self.assertTrue(
            polled <= _canon_keys(),
            f"опрашивается вне канона: {sorted(polled - _canon_keys())}",
        )


class TestDay1ChecklistReadsCanon(unittest.TestCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до правки здесь стояло 22 вместо 36."""

    def test_day1_reports_canonical_universe(self):
        detail = PaperDay1Checklist().check_adapter_registry()["detail"]
        self.assertIn(
            f"{len(CANON)} adapters registered", detail,
            "день-1 докладывает размер НЕ канонического набора: " + detail,
        )

    def test_day1_does_not_headline_metadata_count(self):
        """Число метаданных допустимо как ОПИСАНИЕ, но не как размер вселенной."""
        detail = PaperDay1Checklist().check_adapter_registry()["detail"]
        self.assertNotIn(
            f"{len(META)} adapters registered", detail,
            "размер ADAPTER_METADATA подан как число зарегистрированных адаптеров: " + detail,
        )

    def test_day1_names_the_set_it_used(self):
        """Выбор набора обязан быть НАЗВАН в отчёте, а не подразумеваться."""
        detail = PaperDay1Checklist().check_adapter_registry()["detail"]
        self.assertIn("ADAPTER_REGISTRY", detail)

    def test_day1_fails_closed_when_canon_unreadable(self):
        """Канон не читается ⇒ ОТКАЗ, а не тихий пересчёт по метаданным (инвариант #2)."""
        with canon_unimportable():
            result = PaperDay1Checklist().check_adapter_registry()
        self.assertFalse(
            result["pass"],
            "канон недоступен, а чек всё равно зелёный — fail-OPEN: " + str(result),
        )


class TestWhitelistReadsCanon(unittest.TestCase):
    """`governance_watcher` отвечает на вопрос «во что вообще можно вкладывать»."""

    def test_whitelist_is_canon_not_polled_or_metadata(self):
        from spa_core.alerts.governance_watcher import whitelisted_protocol_keys

        keys = whitelisted_protocol_keys()
        self.assertIsNotNone(keys, "whitelist не измерен — fail-CLOSED сорвался")
        self.assertEqual(set(keys), _canon_keys())

    def test_whitelist_fails_closed_when_registry_unreadable(self):
        from spa_core.alerts.governance_watcher import whitelisted_protocol_keys

        with canon_unimportable():
            self.assertIsNone(
                whitelisted_protocol_keys(),
                "нечитаемый реестр обязан дать None = НЕ ИЗМЕРЕНО, а не пустой список",
            )


class TestHouseViewGapReadsCanon(unittest.TestCase):
    """Авария #206 жила ровно здесь — закрепляем набор и fail-CLOSED."""

    def test_registry_keys_match_canon(self):
        from spa_core.monitoring.house_view_gap import registry_protocol_keys

        keys = registry_protocol_keys()
        self.assertIsNotNone(keys)
        self.assertIn("aave_v3", keys)
        self.assertEqual(len(keys), len(_canon_keys()))

    def test_returns_none_not_empty_when_unreadable(self):
        from spa_core.monitoring.house_view_gap import registry_protocol_keys

        with canon_unimportable():
            self.assertIsNone(registry_protocol_keys())


if __name__ == "__main__":
    unittest.main()
