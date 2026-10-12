"""Род числа на оси APY у отчёта владельцу ``/protocols`` — ADR-709, заказ G708 п. 4.

ADR-708 закрыл ось TVL у ЭТОГО ЖЕ читателя и назвал ось APY остатком вслух:
``_get_best_apy`` читает ``apy_pct`` / ``apy`` / ``mock_apy`` и ``apy_source`` не
смотрит вовсе. Батарея держит ДВА утверждения:

1. род числа печатается рядом с числом, и три исхода РАЗЛИЧИМЫ (инв. #17);
2. правило «что есть наблюдение» взято ОДНОЙ копией из ``status_reader``
   (контракт ADR-063), а не выведено здесь заново.

У каждого звена есть обратная сторона с НАЗВАННЫМ звеном: тест, который краснеет
ровно от того, что это звено порвано. Проверка, никогда не видевшая настоящей
поломки, — украшение (``.claude/rules/deployment.md``).

Пометки ``FROZEN-DATE-OK`` здесь НЕТ намеренно, и это измерено, а не выбрано:
литеральные даты ниже стоят только в ПРОЗЕ (дата замера), ни одно утверждение
батареи не читает ни стенные часы, ни отметку времени, и храповик замороженных
дат этот файл в население не берёт (проверено ``claiming_files`` + зелёный
``test_frozen_date_ratchet``). Объявить `injected-clock` значило бы заявить
инъекцию, которой тут нет, — записка не есть инъекция (цикл #477).
"""
from __future__ import annotations

import unittest

from spa_core.adapters.status_reader import observed_apy_pct_from_block
from spa_core.telegram_protocols_reporter import (
    _get_apy_str,
    _get_best_apy,
    format_protocols_message,
    unparsed_adapter_entries,
)

# ── замер живого дерева 2026-10-12, воспроизведённый фикстурами ──────────────
#
# Из 34 современных записей ``adapters`` с напечатанным числом: 23 несут
# ``live_apy`` (наблюдение), 11 его не несут И печатают ровно свой
# ``fallback_apy`` (литерал). Владелец читал «APY: 14.0%» у ``pendle_yt_susde``
# неотличимо от замера.

OBSERVED = {"apy": 4.3725, "live_apy": 4.3725}          # nested:aave_v3, дословно
LITERAL = {"apy": 14.0, "fallback_apy": 14.0}           # nested:pendle_yt_susde
SHADOW = {"apy": 3.1293}                                # теневой блок aave_arbitrum


class TestThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Исходов три, и различает их РОД, а не величина (инв. #17)."""

    def test_observation_prints_the_number_alone(self):
        self.assertEqual(_get_apy_str(OBSERVED), "4.4%")

    def test_declared_literal_is_marked_an_estimate(self):
        self.assertEqual(_get_apy_str(LITERAL), "14.0% (оценка)")

    def test_no_provenance_at_all_is_its_OWN_third_outcome(self):
        # «род не объявлен» ≠ «объявлен литералом»: разные факты о числе.
        self.assertEqual(_get_apy_str(SHADOW), "3.1% (род не объявлен)")

    def test_the_three_outcomes_are_pairwise_DIFFERENT_strings(self):
        # Обратная сторона предыдущих трёх: склей любые два — и этот тест
        # краснеет. Именно склейка и была дефектом ADR-708.
        got = {_get_apy_str(OBSERVED), _get_apy_str(LITERAL), _get_apy_str(SHADOW)}
        self.assertEqual(len(got), 3, f"исходы склеились: {got}")

    def test_apy_source_declared_and_not_live_is_an_estimate(self):
        # Форма рода, объявленная ADR-707. В живом артефакте её ещё нет —
        # читатель обязан быть готов к ней ДО того, как производитель поедет.
        self.assertEqual(
            _get_apy_str({"apy": 8.0, "apy_source": "fallback_stale"}),
            "8.0% (оценка)",
        )

    def test_apy_source_live_without_live_apy_is_NOT_taken_as_observation(self):
        # Ровно дефект ADR-063: провайдер WS1.1 штамповал apy_source="live" на
        # литерал. Доказывает наблюдение ТОЛЬКО live_apy; штамп — не доказательство.
        got = _get_apy_str({"apy": 5.5, "apy_source": "live"})
        self.assertEqual(got, "5.5% (оценка)")
        self.assertNotEqual(got, "5.5%")


class TestNumberIsNeverSilenced(unittest.TestCase):
    """Отчёт — сводка, а не гейт: число не гасится, гасится неизвестность рода."""

    def test_no_numeric_apy_at_all_returns_None(self):
        self.assertIsNone(_get_apy_str({}))
        self.assertIsNone(_get_apy_str({"apy": "наверное 5"}))

    def test_non_dict_returns_None_and_does_not_raise(self):
        self.assertIsNone(_get_apy_str(None))  # type: ignore[arg-type]
        self.assertIsNone(_get_apy_str("bad"))  # type: ignore[arg-type]

    def test_the_VALUE_is_unchanged_by_this_change(self):
        # Обратная сторона: правка добавляет РОД и не двигает величину.
        for block in (OBSERVED, LITERAL, SHADOW):
            apy = _get_best_apy(block)
            self.assertIsNotNone(apy)
            self.assertTrue(
                _get_apy_str(block).startswith(f"{apy:.1f}%"),
                f"величина сдвинулась у {block}",
            )


class TestTheObservationRuleHasONECopy(unittest.TestCase):
    """Правило взято из ``status_reader``, а не выведено здесь заново (ADR-063)."""

    def test_verdict_agrees_with_the_canonical_reader_on_every_shape(self):
        # Если кто-то заведёт здесь ВТОРУЮ копию правила, она разойдётся с
        # канонической на одной из этих форм — и тест назовёт форму.
        shapes = [
            OBSERVED,
            LITERAL,
            SHADOW,
            {"apy": 5.0, "live_apy": None},
            {"apy": 5.0, "live_apy": 5.0, "apy_source": "fallback_stale"},
            {"apy": 1.0, "live_apy": 999.0},   # вне полосы санитарности
        ]
        for block in shapes:
            canonical_says_observed = observed_apy_pct_from_block(block) is not None
            printed = _get_apy_str(block)
            self.assertIsNotNone(printed, f"нет числа у {block}")
            reader_says_observed = "(" not in printed
            self.assertEqual(
                canonical_says_observed,
                reader_says_observed,
                f"читатель разошёлся с каноном на {block}: {printed!r}",
            )

    def test_insane_live_apy_is_not_an_observation(self):
        # Полоса санитарности — свойство КАНОНА (_MAX_APY_PCT=200), и читатель
        # наследует её, а не переобъявляет. 999 % — сломанный фид, не щедрый.
        self.assertEqual(_get_apy_str({"apy": 1.0, "live_apy": 999.0}),
                         "1.0% (род не объявлен)")


class TestUnparsedPopulationIsNamedNotSilent(unittest.TestCase):
    """Третий исход у ПОПУЛЯЦИИ отчёта (инв. #17).

    ЗАМЕР 2026-10-12: ``_get_all_adapters`` обходит ``data["adapters"]`` как
    СПИСОК, а живой артефакт несёт его СЛОВАРЁМ — обход словаря отдаёт ключи,
    ``isinstance(str, dict)`` ложен, и 34 из 36 записей падали МОЛЧА. Владелец
    читал «Total adapters: 2» и не имел ни одного признака, что остальные
    существуют.
    """

    def _doc(self):
        return {
            "adapters": {
                "aave_v3": dict(OBSERVED, tier="T1", name="aave-v3"),
                "pendle_yt_susde": dict(LITERAL, tier="T3", name="pendle-yt"),
            },
            "aave_arbitrum": dict(SHADOW, tier="T1", name="aave-arb"),
        }

    def test_dict_section_counts_its_unparsed_entries(self):
        self.assertEqual(unparsed_adapter_entries(self._doc()), 2)

    def test_list_section_is_NOT_MEASURED_rather_than_zero(self):
        # Список — форма, которую читатель разбирает; ронять нечего. Третий
        # исход (None) отличим от измеренного нуля.
        self.assertIsNone(unparsed_adapter_entries({"adapters": [OBSERVED]}))

    def test_missing_section_is_NOT_MEASURED(self):
        self.assertIsNone(unparsed_adapter_entries({}))
        self.assertIsNone(unparsed_adapter_entries(None))  # type: ignore[arg-type]

    def test_measured_zero_is_distinguishable_from_not_measured(self):
        # Обратная сторона: пустой СЛОВАРЬ есть измеренный ноль, а не «не измерено».
        self.assertEqual(unparsed_adapter_entries({"adapters": {}}), 0)
        self.assertIsNone(unparsed_adapter_entries({"adapters": None}))

    def test_the_owner_MESSAGE_names_the_drop(self):
        msg = format_protocols_message(self._doc())
        self.assertIn("НЕ РАЗОБРАНО", msg)
        self.assertIn("2", msg)

    def test_the_message_stays_SILENT_when_nothing_was_dropped(self):
        # Обратная сторона предыдущего: вечно печатаемая строка есть шум, а не
        # наблюдение. Нулевой потери ⇒ нет строки.
        msg = format_protocols_message({"adapters": [], "aave_arbitrum": dict(SHADOW, tier="T1")})
        self.assertNotIn("НЕ РАЗОБРАНО", msg)

    def test_the_drop_line_does_NOT_publish_the_numbers(self):
        # Поднять 34 записи значило бы напечатать владельцу 34 НОВЫХ числа —
        # публикация, а не представление (та же граница, что у ADR-708/pendle_pt).
        msg = format_protocols_message(self._doc())
        self.assertNotIn("14.0%", msg, "число непрочитанной записи утекло в отчёт")
        self.assertNotIn("4.4%", msg, "число непрочитанной записи утекло в отчёт")


class TestTheOwnerFacingLineCarriesTheRod(unittest.TestCase):
    """Поле, которого не видит читатель, есть мёртвый свидетель (ADR-704)."""

    def test_estimate_reaches_the_rendered_line(self):
        msg = format_protocols_message(
            {"pendle_yt_susde": dict(LITERAL, tier="T3", name="pendle-yt")}
        )
        self.assertIn("APY: 14.0% (оценка)", msg)

    def test_observation_reaches_the_line_WITHOUT_a_qualifier(self):
        # Обратная сторона: пометь наблюдение — и тест краснеет. Иначе «оценка»
        # стала бы украшением, которое ничего не различает.
        msg = format_protocols_message(
            {"aave_v3": dict(OBSERVED, tier="T1", name="aave-v3")}
        )
        self.assertIn("APY: 4.4%", msg)
        self.assertNotIn("4.4% (", msg)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
