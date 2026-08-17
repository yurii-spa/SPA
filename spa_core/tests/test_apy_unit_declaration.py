"""Единица APY ОБЪЯВЛЕНА источником; необъявленная — отказ, а не догадка.

Карточка: ``agent-s76-apy-unit-guess.md`` (находка цикла #121).

Авария настоящая и уже случалась: единицу определяли по ВЕЛИЧИНЕ числа
(``v < 1.0 → ×100``), поэтому честные 0.5 % годовых читались как 50 %, а
смешанная доходность S76 выходила ~30.9 % вместо ~1.2 %. Числа 0.8 («0.8 %») и
0.8 («80 %») неразличимы, значит без объявления единицы честного ответа не
существует — только отказ (инвариант 2, fail-CLOSED).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ этого файла — ``test_same_number_two_units_two_answers``
и ``test_true_sub_one_percent_decimal_is_not_scaled``: НИ ОДНА функция,
угадывающая единицу по величине, их не проходит (одно и то же число 0.5 обязано
дать 0.005 при объявленном percent и 0.5 при объявленном decimal). Остальное —
проверки отказа (undeclared / опечатка / нечисло) и стражи существующего
канонического аксессора.

``.claude/rules/adapters.md``: единицы в репозитории действительно
непоследовательны (percent у новых, decimal у aave/yearn/euler/maple), поэтому
``adapters_missing_apy_unit`` НАЗЫВАЕТ ещё не миграированные источники —
измеряемый остаток вместо предположения.

stdlib, без сети, без диска.
"""
from __future__ import annotations

import unittest

from spa_core.adapters.apy_contract import (
    APY_UNIT_ATTR,
    APY_UNIT_DECIMAL,
    APY_UNIT_PERCENT,
    adapters_missing_apy_unit,
    apy_decimal_from_declared,
    declared_apy_unit,
    raw_apy_decimal,
)


class _DeclaredPercentSource:
    PROTOCOL = "declared_percent"
    APY_UNIT = APY_UNIT_PERCENT

    def get_apy(self):
        return 0.5          # 0.5 % годовых — честные sub-1%


class _DeclaredDecimalSource:
    PROTOCOL = "declared_decimal"
    APY_UNIT = APY_UNIT_DECIMAL

    def get_apy(self):
        return 0.5          # 50 % годовых


class _UndeclaredSource:
    PROTOCOL = "undeclared"

    def get_apy(self):
        return 0.5          # 0.5 % или 50 %? — неизвестно


class _TypoUnitSource:
    PROTOCOL = "typo_unit"
    APY_UNIT = "percents"   # опечатка — НЕ единица


class _RaisingSource:
    PROTOCOL = "raising"
    APY_UNIT = APY_UNIT_PERCENT

    def get_apy(self):
        raise RuntimeError("feed down")


class TestDeclarationIsTheOnlyInput(unittest.TestCase):
    """Единица приходит из объявления, а не из величины числа."""

    def test_same_number_two_units_two_answers(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: 0.5 → 0.005 (percent) и 0.5 (decimal)."""
        self.assertAlmostEqual(
            apy_decimal_from_declared(0.5, APY_UNIT_PERCENT), 0.005, places=9)
        self.assertAlmostEqual(
            apy_decimal_from_declared(0.5, APY_UNIT_DECIMAL), 0.5, places=9)

    def test_true_sub_one_percent_decimal_is_not_scaled(self):
        """Честные 0.5 % в долях (0.005) остаются 0.005, а не 0.5."""
        self.assertAlmostEqual(
            apy_decimal_from_declared(0.005, APY_UNIT_DECIMAL), 0.005, places=9)

    def test_percent_conversion_happens_exactly_once(self):
        self.assertAlmostEqual(
            apy_decimal_from_declared(5.2, APY_UNIT_PERCENT), 0.052, places=9)

    def test_measured_zero_is_kept(self):
        """Ноль — измеренное значение, а не «нет данных»."""
        self.assertEqual(apy_decimal_from_declared(0.0, APY_UNIT_DECIMAL), 0.0)
        self.assertEqual(apy_decimal_from_declared(0.0, APY_UNIT_PERCENT), 0.0)


class TestUndeclaredIsRefusal(unittest.TestCase):
    """Нет объявления — нет ответа. Никакой единицы по умолчанию."""

    def test_none_unit_refused(self):
        self.assertIsNone(apy_decimal_from_declared(0.5, None))

    def test_unknown_unit_refused(self):
        self.assertIsNone(apy_decimal_from_declared(0.5, "bps"))
        self.assertIsNone(apy_decimal_from_declared(0.5, ""))

    def test_non_numeric_refused_even_with_unit(self):
        for bad in ("5.0", None, True, float("nan"), float("inf")):
            with self.subTest(value=bad):
                self.assertIsNone(
                    apy_decimal_from_declared(bad, APY_UNIT_DECIMAL))

    def test_negative_refused(self):
        self.assertIsNone(apy_decimal_from_declared(-0.01, APY_UNIT_DECIMAL))

    def test_out_of_band_after_conversion_still_refused(self):
        """120 % → 1.2 в долях — вне sane-band, отказ (не второе домножение)."""
        self.assertIsNone(apy_decimal_from_declared(120.0, APY_UNIT_PERCENT))
        self.assertIsNone(apy_decimal_from_declared(5000.0, APY_UNIT_PERCENT))


class TestDeclaredApyUnit(unittest.TestCase):
    """Чтение объявления: только точные значения, опечатка = не объявлено."""

    def test_reads_declaration(self):
        self.assertEqual(declared_apy_unit(_DeclaredPercentSource()),
                         APY_UNIT_PERCENT)
        self.assertEqual(declared_apy_unit(_DeclaredDecimalSource()),
                         APY_UNIT_DECIMAL)

    def test_case_and_whitespace_tolerated(self):
        class _Loud:
            APY_UNIT = "  DECIMAL "
        self.assertEqual(declared_apy_unit(_Loud()), APY_UNIT_DECIMAL)

    def test_missing_attribute_is_undeclared(self):
        self.assertIsNone(declared_apy_unit(_UndeclaredSource()))
        self.assertIsNone(declared_apy_unit(None))

    def test_typo_is_undeclared_not_percent(self):
        self.assertIsNone(declared_apy_unit(_TypoUnitSource()))

    def test_non_string_declaration_is_undeclared(self):
        class _Numeric:
            APY_UNIT = 100
        self.assertIsNone(declared_apy_unit(_Numeric()))

    def test_attribute_name_is_the_documented_one(self):
        self.assertEqual(APY_UNIT_ATTR, "APY_UNIT")


class TestRawApyDecimal(unittest.TestCase):
    """Сырой ``get_apy()`` читается только через объявление источника."""

    def test_declared_percent_source(self):
        self.assertAlmostEqual(raw_apy_decimal(_DeclaredPercentSource()),
                               0.005, places=9)

    def test_declared_decimal_source(self):
        self.assertAlmostEqual(raw_apy_decimal(_DeclaredDecimalSource()),
                               0.5, places=9)

    def test_undeclared_source_refused(self):
        self.assertIsNone(raw_apy_decimal(_UndeclaredSource()))

    def test_missing_get_apy_refused(self):
        class _NoAccessor:
            APY_UNIT = APY_UNIT_DECIMAL
        self.assertIsNone(raw_apy_decimal(_NoAccessor()))

    def test_raising_accessor_refused_not_raised(self):
        self.assertIsNone(raw_apy_decimal(_RaisingSource()))

    def test_none_source(self):
        self.assertIsNone(raw_apy_decimal(None))


class TestMigrationRemainderIsMeasurable(unittest.TestCase):
    """Остаток миграции НАЗЫВАЕТСЯ, а не предполагается."""

    def test_injected_registry_split(self):
        registry = [
            ("declared", "T1", _DeclaredPercentSource),
            ("undeclared", "T2", _UndeclaredSource),
            ("typo", "T2", _TypoUnitSource),
        ]
        self.assertEqual(adapters_missing_apy_unit(registry),
                         ["typo", "undeclared"])

    def test_live_registry_is_listable_and_read_only(self):
        """Функция не инстанцирует адаптеры и не ходит в сеть."""
        from spa_core.adapters import ADAPTER_REGISTRY
        missing = adapters_missing_apy_unit()
        self.assertIsInstance(missing, list)
        self.assertLessEqual(len(missing), len(ADAPTER_REGISTRY))
        self.assertEqual(missing, sorted(missing))


class TestCanonicalAccessorStillPreferred(unittest.TestCase):
    """Страж: объявление НЕ отменяет канонический аксессор.

    ``get_yield_info().apy`` остаётся каноническим (всегда decimal); объявление
    нужно только тем, кто вынужден читать сырое число.
    """

    def test_canonical_accessor_unaffected_by_declaration(self):
        from spa_core.adapters.apy_contract import canonical_apy_decimal

        class _Both:
            PROTOCOL = "both"
            APY_UNIT = APY_UNIT_PERCENT

            def get_apy(self):
                return 5.0

            def get_yield_info(self):
                class _Info:
                    apy = 0.05
                return _Info()

        self.assertAlmostEqual(canonical_apy_decimal(_Both()), 0.05, places=9)
        self.assertAlmostEqual(raw_apy_decimal(_Both()), 0.05, places=9)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
