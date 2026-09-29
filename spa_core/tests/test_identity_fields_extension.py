"""Приёмка заказа **G35 п. 4** — расширение `_IDENTITY_FIELDS` ЗАМЕРОМ (ADR-503).

Заказ: «Расширение `_IDENTITY_FIELDS` теперь стои́т на замере, а не на глаз.
Начинать с полей, подпёртых длинными списками, и каждое — с контролем, что
координаты соседей от него не поехали.»

Здесь живёт этот контроль, и он двусторонний: мало показать, что соседи не
поехали, — надо показать, что контроль УВИДЕЛ БЫ, если бы поехали. Поэтому у
каждого утверждения есть отрицательная половина: вставка тех же имён В НАЧАЛО
кортежа обязана покраснить ровно то, что дописывание в конец оставляет на месте.

Единственный литерал даты здесь — якорь `_ANCHOR`, и он ЯВЛЯЕТСЯ предметом:
даты стенда строятся от него счётом, а не берутся у календаря машины. Ни один
вердикт не зависит от того, какое сегодня число, и ни одна проверка не
спрашивает стенные часы.
"""
# FROZEN-DATE-OK: единственный литерал — якорь _ANCHOR, от которого даты
# строятся счётом; ни один вердикт не зависит от календаря машины, стенные часы
# не спрашиваются ни одной проверкой.
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from spa_core.monitoring import run_identity_key_price as g16

#: Якорь дат стенда. Календарь машины на вердикты не влияет.
_ANCHOR = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)


def _day(offset: int = 0) -> str:
    return (_ANCHOR + timedelta(days=offset)).date().isoformat()


#: Корпус. Каждая строка — ФОРМА, наблюдённая переписью `list_identity_census`
#: (замер 25.09, `finding_rows`), а не выдуманная: имя модуля названо, чтобы
#: форму можно было перепроверить у источника, а не поверить на слово.
_CORPUS = {
    # называют себя СТАРЫМ именем — их координаты и есть «соседи» заказа
    "adapter_feed_divergence.legs": [
        {"protocol": "aave_v3", "apy": 2.7}, {"protocol": "pendle", "apy": 8.0}],
    "decision_audit_trail.rows": [
        {"cycle_date": _day(0), "verdict": "HOLD"},
        {"cycle_date": _day(1), "verdict": "ACT"}],
    "criterion_population_floor.criteria": [
        {"criterion": "g1", "share_pct": 100.0},
        {"criterion": "g2", "share_pct": 40.0}],
    # обе половины сразу: старое имя ОБЯЗАНО победить дописанное
    "both_names_present": [
        {"protocol": "aave_v3", "source": "live"},
        {"protocol": "morpho_blue", "source": "defillama"}],
    # не назывались ничем — это и есть находка заказа
    "criterion_value_interval.granted_rates": [
        {"source": "adapter", "rate_pct": 2.7},
        {"source": "defillama", "rate_pct": 2.9}],
    "asset_registry_gap_price.zero_vs_absent.rows": [
        {"coordinate": ".legs[0].tvl_usd", "zero": True},
        {"coordinate": ".legs[1].tvl_usd", "zero": False}],
    "rate_observation_census.run_axis": [
        {"day": _day(0), "runs": 1}, {"day": _day(1), "runs": 2}],
    "criterion_sign_price.differential.rows": [
        {"variant": "as_is", "net_usd": 10.0},
        {"variant": "collapsing", "net_usd": 4.0}],
}

#: Имена, дописанные замером. Берутся у модуля, а не перечисляются заново:
#: вторая копия списка и есть тот класс, который эта семья ловит у читателей.
_MEASURED = g16._MEASURED_IDENTITY_FIELDS
_HAND = g16._HAND_PICKED_IDENTITY_FIELDS


def _identity_under(fields, items):
    """Личность по ОБЪЯВЛЕННОМУ кортежу — тем же кодом, что и в проде.

    Кортеж здесь ВХОД, а не окружение: правило не переписывается, подменяется
    только его объявление. Вторая копия `element_identity` в тесте означала бы,
    что контроль судит не о том коде, который поедет.
    """
    with mock.patch.object(g16, "_IDENTITY_FIELDS", tuple(fields)):
        return g16.element_identity(items)


class ExtensionIsAnAppendNotAnInsertion(unittest.TestCase):
    """Форма расширения — машинная, а не обещание в комментарии."""

    def test_full_tuple_is_exactly_hand_picked_then_measured(self):
        self.assertEqual(g16._IDENTITY_FIELDS, _HAND + _MEASURED)

    def test_the_hand_picked_prefix_is_untouched(self):
        self.assertEqual(g16._IDENTITY_FIELDS[:len(_HAND)], _HAND)

    def test_no_name_is_declared_twice(self):
        self.assertEqual(len(set(g16._IDENTITY_FIELDS)), len(g16._IDENTITY_FIELDS))

    def test_a_wall_clock_field_is_never_an_identity(self):
        """Поле, объявленное СТЕННЫМ этим же модулем, личностью быть не вправе.

        Население дефекта СЕГОДНЯ — ноль, и это сказано вслух: утверждение про
        правило, а не про найденное неверное имя. Цена нарушения — координата,
        которая ездит каждый прогон производителя.
        """
        self.assertEqual(set(g16._IDENTITY_FIELDS) & set(g16.CLOCK_FIELDS), set())


class AppendingNeverMovesAnExistingChoice(unittest.TestCase):
    """Контроль, которого требовал заказ, — и его отрицательная половина."""

    def test_every_already_named_list_keeps_its_field(self):
        for label, items in _CORPUS.items():
            before = _identity_under(_HAND, items)
            if before is None:
                continue
            with self.subTest(label=label):
                self.assertEqual(_identity_under(_HAND + _MEASURED, items), before)

    def test_prepending_the_same_names_DOES_move_them(self):
        """Положительный контроль: контроль выше не пуст.

        Те же имена, вставленные В НАЧАЛО, переименовывают координату у списка,
        где годны и старое имя, и дописанное. Не покрасней здесь — контроль выше
        был бы неотличим от своего удаления.
        """
        moved = [label for label, items in _CORPUS.items()
                 if (_identity_under(_HAND, items) is not None
                     and _identity_under(_MEASURED + _HAND, items)
                     != _identity_under(_HAND, items))]
        self.assertIn("both_names_present", moved)

    def test_the_corpus_actually_contains_a_list_with_both_kinds_of_name(self):
        """Сцена контроля выше существует — иначе он был бы верен вхолостую."""
        items = _CORPUS["both_names_present"]
        self.assertEqual(_identity_under(_HAND, items), "protocol")
        self.assertEqual(_identity_under(_MEASURED + _HAND, items), "source")


class TheGainIsRealAndDirected(unittest.TestCase):
    """Каждое дописанное имя ПРИНОСИТ личность там, где её не было."""

    def test_each_measured_name_turns_a_positional_list_into_a_named_one(self):
        for name in _MEASURED:
            items = [{name: "alpha", "payload": 1}, {name: "beta", "payload": 2}]
            with self.subTest(field=name):
                self.assertIsNone(_identity_under(_HAND, items))
                self.assertEqual(_identity_under(_HAND + _MEASURED, items), name)

    def test_the_coordinate_of_a_gained_list_changes_and_that_IS_the_price(self):
        """Односторонность названа, а не спрятана.

        У списка, который личность ПРИОБРЁЛ, координаты потомков переезжают с
        `[0]` на `[day="…"]`. Это и есть цель заказа, но это ПЕРЕЕЗД, и молчать
        о нём значило бы продать половину правды: у соседей, уже названных
        именем, не двигается ничего (контроль выше), у приобретших — двигается
        всё, что под ними.
        """
        items = _CORPUS["rate_observation_census.run_axis"]
        with mock.patch.object(g16, "_IDENTITY_FIELDS", _HAND):
            self.assertEqual([c for c, _ in g16.indexed(items)], ["[0]", "[1]"])
        with mock.patch.object(g16, "_IDENTITY_FIELDS", _HAND + _MEASURED):
            self.assertEqual([c for c, _ in g16.indexed(items)],
                             [f'[day="{_day(0)}"]', f'[day="{_day(1)}"]'])


class TheNewNamesObeyTheSameRule(unittest.TestCase):
    """Дописанное имя не получает поблажек: правило одно на все имена."""

    def test_a_repeated_value_is_refused(self):
        items = [{"source": "live"}, {"source": "live"}]
        self.assertIsNone(_identity_under(_HAND + _MEASURED, items))

    def test_a_missing_field_in_one_element_is_refused(self):
        items = [{"day": _day(0)}, {"runs": 2}]
        self.assertIsNone(_identity_under(_HAND + _MEASURED, items))

    def test_bool_values_are_refused_for_the_new_names_too(self):
        items = [{"variant": True}, {"variant": False}]
        self.assertIsNone(_identity_under(_HAND + _MEASURED, items))

    def test_a_non_scalar_value_is_refused(self):
        items = [{"coordinate": [".a"]}, {"coordinate": [".b"]}]
        self.assertIsNone(_identity_under(_HAND + _MEASURED, items))


class TheRefusedChampionsStayRefused(unittest.TestCase):
    """Чемпионы ПО ДЛИНЕ, которых замер длины взял бы, а род — нет.

    Замер 25.09 на настоящем населении: `value` длиной 93 и
    `record_generated_at` длиной 65 стоя́т ВЫШЕ трёх дописанных имён
    (`coordinate` 43, `day` 27, `variant` 18). Признак «длина списка» —
    необходимый и НЕ достаточный, и это утверждение проверяемо: добавь любое из
    двух — тест покраснеет.
    """

    def test_a_producers_generated_at_is_not_an_identity(self):
        items = [{"record_generated_at": f"{_day(0)}T01:00:00+00:00"},
                 {"record_generated_at": f"{_day(1)}T01:00:00+00:00"}]
        self.assertNotIn("record_generated_at", g16._IDENTITY_FIELDS)
        self.assertIsNone(g16.element_identity(items))

    def test_the_generic_name_value_is_not_an_identity(self):
        items = [{"value": "hit_rate"}, {"value": "turnover"}]
        self.assertNotIn("value", g16._IDENTITY_FIELDS)
        self.assertIsNone(g16.element_identity(items))


class TheCensusProbeSeesTheSameTupleAsTheRule(unittest.TestCase):
    """Перепись судит тем же списком имён, каким судит правило.

    Разойдись они — перепись докладывала бы про «поля вне списка» то, чего в
    списке уже нет, то есть считала бы уже закрытую находку открытой.
    """

    def test_probe_tuple_is_the_rule_tuple(self):
        from spa_core.monitoring import _list_identity_probe as probe
        self.assertEqual(tuple(probe.IDENTITY_FIELDS), tuple(g16._IDENTITY_FIELDS))


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
