"""Контроль пробы `journal_reader_census_verdict_under_injected_clock` — в обе стороны.

Правило `.claude/rules/acceptance.md` §3: новая проба регистрируется только с
тестом, где она ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене — с
названным звеном, — и где она не проходит подстрокой (ADR-333).

Контур настоящий: проба строит стенды и гонит по ним настоящую проводку
переписи (`module_driver` → `classify_reader`). Живой `data/` не открывается
ни одним звеном — журнал стенда синтетический, обе строки пишет сама проба.

Четыре звена, и каждое ломается ОТДЕЛЬНО:

1. часы прогона доходят до читателя (сверяется ЗНАЧЕНИЕ, а не параметр);
2. БЕЗ часов вердикта у того же читателя нет;
3. С часами вердикт есть, и строка это признаёт;
4. инъекция не красит схлопывающего читателя в «нечувствителен».
"""
# FROZEN-DATE-OK: дата в стенде пробы — её собственный синтетический журнал,
# а не отметка свежести; ни одна проверка здесь не смотрит на стенные часы.
from __future__ import annotations

import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import run_identity_key_price as census

_NAME = "journal_reader_census_verdict_under_injected_clock"


class ProbeIsRegistered(unittest.TestCase):

    def test_the_probe_answers_under_its_registered_name(self):
        self.assertIn(_NAME, ca.PROBES)
        self.assertIsNone(ca.validate_spec(_NAME))

    def test_an_argument_is_refused_out_loud(self):
        """Пофайловой формы у критерия нет: «мой читатель измерен» при слепом
        соседе — зелёный ответ на свой вопрос, выданный за нужный."""
        verdict, detail = ca.run_probe(f"{_NAME}:spa_core.monitoring.house_view_gap")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не принимает аргумента", detail)


class GreenOnTheWholeContour(unittest.TestCase):

    def test_the_shipped_contour_satisfies_the_criterion(self):
        verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("с часами вердикт есть", detail)

    def test_the_population_tail_never_decides_the_verdict(self):
        """Счётчик в артефакте — РИДЕР, а не гейт, и это обязано быть видно:
        артефакт пишет дневной цикл, а не проба. Нечитаемый артефакт даёт
        «НЕ ИЗМЕРЕНО» в хвосте и НЕ роняет вердикт звеньев 1–4."""
        with mock.patch.object(census, "ARTIFACT", "g28_no_such_artifact.json"):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("население НЕ ИЗМЕРЕНО", detail)
        # обратный контроль: при читаемом артефакте хвост говорит ЧИСЛОМ, а не
        # молчит — иначе «не измерено» было бы единственным ответом всегда.
        _v, plain = ca.run_probe(_NAME)
        self.assertEqual(_v, ca.SATISFIED, plain)
        self.assertIn("население", plain)


class RedOnEachBrokenLink(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и проба называет ИМЕННО его."""

    def test_link_1_the_wiring_drops_the_clock(self):
        """Состояние ДО заказа G28: параметр `now` у читателя как стоял, так и
        стоит, а проводка его не проводит. Мутируется именно ПРОВОДКА."""
        real = census.clock_kwarg
        with mock.patch.object(census, "clock_kwarg", lambda fn, now: {}):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 1", detail)
        self.assertIs(census.clock_kwarg, real, "подмена не снята")

    def test_link_2_without_the_clock_the_reader_already_has_a_verdict(self):
        """Если БЕЗ часов вердикт и так получается, зелёное звено 3 ничего про
        инъекцию не доказывает — контроль, истинный по построению."""
        real = census.classify_reader

        def always_judged(name, stands, *, now=None):
            row = real(name, stands, now=now)
            if row.get("cause") == census.CAUSE_RESTS_ON_UNSTABLE:
                row.update(outcome=census.READER_INSENSITIVE, cause=None)
            return row

        with mock.patch.object(census, "classify_reader", always_judged):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 2", detail)

    def test_link_3_the_row_does_not_admit_the_clock_was_injected(self):
        """Строка без `clock_injected` делает улучшение счётчика неотличимым
        от везения: «стало лучше» нечем поверить."""
        real = census.classify_reader

        def forgetful(name, stands, *, now=None):
            row = real(name, stands, now=now)
            row.pop("clock_injected", None)
            return row

        with mock.patch.object(census, "classify_reader", forgetful):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 3", detail)

    def test_link_4_injection_paints_a_collapsing_reader_insensitive(self):
        """Самый дешёвый способ погасить класс — сделать так, чтобы проведённые
        часы гасили РАЗНИЦУ между стендами, а не шум. Тогда счётчик «убыл» бы
        враньём, и звено 4 обязано это поймать."""
        real = census.classify_reader

        def flattening(name, stands, *, now=None):
            row = real(name, stands, now=now)
            if now is not None and row.get("outcome") in (census.READER_LAST,
                                                          census.READER_FIRST):
                row.update(outcome=census.READER_INSENSITIVE)
            return row

        with mock.patch.object(census, "classify_reader", flattening):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 4", detail)

    def test_a_crash_inside_the_contour_is_unmeasured_never_a_verdict(self):
        """«Не измерено» обязано быть отличимо и от `satisfied`, и от
        `not_satisfied` (инв. #17): упавший контур ничего не доказал."""
        def boom(*a, **k):
            raise RuntimeError("проводка не отработала")

        with mock.patch.object(census, "module_driver", boom):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("RuntimeError", detail)


class VerdictDoesNotRideOnASubstring(unittest.TestCase):
    """ADR-333: вердикт обязан стоять на ИСХОДЕ, а не на совпадении текста."""

    def test_a_reader_that_merely_ECHOES_a_timestamp_does_not_pass(self):
        """Читатель, чей ответ СОДЕРЖИТ переданное время, но который всё равно
        остаётся несудимым, зелёным быть не может: звено 1 про значение, а
        звенья 2–4 — про ИСХОД, и одно другого не заменяет."""
        real = census.classify_reader

        def never_judged(name, stands, *, now=None):
            row = real(name, stands, now=now)
            row.update(outcome=census.READER_UNMEASURED,
                       cause=census.CAUSE_RESTS_ON_UNSTABLE,
                       reason="время в ответе есть, вердикта нет")
            return row

        with mock.patch.object(census, "classify_reader", never_judged):
            verdict, detail = ca.run_probe(_NAME)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("звено 3", detail)
