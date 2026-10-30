"""Контроль пробы `inbox_record_kind_has_a_writer` в ОБЕ стороны (.claude/rules/acceptance.md п. 3).

Проба зелена на целом контуре и красна на КАЖДОМ порванном звене — с названным звеном.
Звено рвётся у НАСТОЯЩИХ дверей (читатель `triage`, писатель `queue`, меню писателей),
а не подменой самой пробы: контроль, собранный руками, мерил бы свой словарь, а не проводку
(урок циклов #944/#945).

Подстрокой проба НЕ проходит (ADR-333): вердикт сверяется с полями отчёта, и тест это
проверяет отдельно — сцена, где СЛОВА в сводке остались, а ПОЛЕ пропало, обязана краснеть.

Литеральных дат в файле нет вовсе: ось рода времени не спрашивает, и освобождать здесь
нечего — пометки `FROZEN-DATE-OK` поэтому тоже нет (пометка без якоря есть ЛОЖНОЕ
притязание, и сторож `test_injected_clock_claim` ловит ровно его).
"""
from __future__ import annotations

import unittest
from unittest import mock

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED, run_probe)
from spa_core.owner_queue import queue as Q
from spa_core.owner_queue import triage as T

NAME = "inbox_record_kind_has_a_writer"


class TheProbeIsRegisteredAndGreenOnTheWholeCircuit(unittest.TestCase):
    def test_registered_in_the_one_registry(self):
        self.assertIn(NAME, PROBES)

    def test_green_on_the_whole_circuit(self):
        verdict, detail = run_probe(NAME)
        self.assertEqual(verdict, SATISFIED, detail)


class EachBrokenLinkTurnsItRed(unittest.TestCase):
    """Каждое звено рвётся отдельно, и проба обязана НАЗВАТЬ именно его номер."""

    def _red(self, link: str):
        verdict, detail = run_probe(NAME)
        self.assertEqual(verdict, NOT_SATISFIED, f"звено {link}: проба осталась {verdict} — {detail}")
        self.assertIn(f"звено {link}", detail)
        return detail

    def test_link1_undeclared_kind_substituted(self):
        with mock.patch.object(T, "declared_kind", lambda fm: (fm.get("intake_kind") or "task")):
            self._red("1")

    def test_link2_writer_writes_but_reader_does_not_see_it(self):
        real = T.declared_kind
        with mock.patch.object(T, "declared_kind",
                               lambda fm: T.KIND_UNDECLARED if real(fm) == "task" else real(fm)):
            self._red("2")

    def test_link3_unclear_folded_into_absence(self):
        real = T.declared_kind
        with mock.patch.object(T, "declared_kind",
                               lambda fm: T.KIND_UNDECLARED if real(fm) == "unclear" else real(fm)):
            self._red("3")

    def test_link4_tracker_type_becomes_a_kind(self):
        real = T.declared_kind
        with mock.patch.object(
                T, "declared_kind",
                lambda fm: real(fm) if fm.get("intake_kind") else (fm.get("type") or T.KIND_UNDECLARED)):
            self._red("4")

    def test_link5_writer_accepts_anything(self):
        """Писатель без словаря: пишет что дали и не отказывает — звено 5 обязано покраснеть."""
        def permissive(path, kind):
            from pathlib import Path as _P
            p = _P(path)
            lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
            ends = [i for i, ln in enumerate(lines) if ln.strip() == "---"][:2]
            lines.insert(ends[1], f"intake_kind: {kind}\n")
            p.write_text("".join(lines), encoding="utf-8")
            return None

        with mock.patch.object(Q, "set_intake_kind", permissive):
            self._red("5")

    def test_link5_out_of_dictionary_value_loses_its_own_outcome(self):
        real = T.declared_kind
        with mock.patch.object(T, "declared_kind",
                               lambda fm: T.KIND_UNDECLARED if real(fm) == T.KIND_INVALID else real(fm)):
            self._red("5")

    def test_link6_writer_menu_grows_beyond_the_readers_dictionary(self):
        from spa_core.telegram import inbox_intake as II
        wider = dict(II.INTAKE_KIND_RU, срочно="срочно")
        with mock.patch.object(II, "INTAKE_KIND_RU", wider):
            self._red("6")

    def test_link6_the_SECOND_writer_menu_is_watched_too(self):
        """Меню пульта (`mission_intake.KINDS`) — ВТОРОЙ писатель, и он под той же проверкой.

        Контроль добавлен по ВЫЖИВШЕМУ мутанту #991 («звено 6 снято»): первая проверка
        звена (`extra`) ловила обоих писателей, вторая (`disagree`) — только `inbox_intake`,
        и вся защита меню пульта держалась на одной строке, которую ни один тест не трогал.
        """
        from spa_core.studio_os import mission_intake as MI
        wider = dict(MI.KINDS, срочно="Срочно")
        with mock.patch.object(MI, "KINDS", wider):
            detail = self._red("6")
        self.assertIn("срочно", detail)

    def test_link6_writer_and_reader_disagree_on_the_label(self):
        from spa_core.telegram import inbox_intake as II
        other = dict(II.INTAKE_KIND_RU, note="пометка")
        with mock.patch.object(II, "INTAKE_KIND_RU", other):
            self._red("6")


class NotMeasuredIsItsOwnVerdict(unittest.TestCase):
    """«Нечем измерить» ≠ «не выполнено»: третий исход у пробы есть и он отличим."""

    def test_missing_reader_is_unmeasured_BY_THE_PROBES_OWN_BRANCH(self):
        """Третий исход обязан прийти от САМОЙ пробы, а не от общего ловца `run_probe`.

        Первая редакция этого контроля рвала имя `spa_core.owner_queue.triage`, и оно
        поднималось НЕ в блоке пробы, а позже — внутри писателя; вердикт `unmeasured`
        приходил от `run_probe` («проба упала»), и мутант «UNMEASURED → NOT_SATISFIED» в
        собственной ветке пробы ПЕРЕЖИЛ прогон. Теперь сцена рвёт ровно тот импорт, который
        делает проба (`from spa_core.owner_queue import triage`), и вердикт сверяется с
        ТЕКСТОМ её собственной причины.
        """
        import builtins
        real_import = builtins.__import__

        def boom(name, *a, **kw):
            if name == "spa_core.owner_queue" and "triage" in (kw.get("fromlist") or a[2] or ()):
                raise ImportError("сцена: читателя оси нет")
            return real_import(name, *a, **kw)

        with mock.patch.object(builtins, "__import__", boom):
            verdict, detail = run_probe(NAME)
        self.assertEqual(verdict, UNMEASURED, detail)
        self.assertIn("ось рода записи не поднимается", detail)

    def test_missing_writer_menu_is_unmeasured_not_red(self):
        import builtins
        real_import = builtins.__import__

        def boom(name, *a, **kw):
            if name == "spa_core.telegram.inbox_intake":
                raise ImportError("сцена: меню писателя нет")
            return real_import(name, *a, **kw)

        with mock.patch.object(builtins, "__import__", boom):
            verdict, detail = run_probe(NAME)
        self.assertEqual(verdict, UNMEASURED, detail)
        self.assertIn("меню писателей не поднимается", detail)


class TheProbeJudgesFIELDSNotWORDS(unittest.TestCase):
    """ADR-333: вердикт обязан держаться на ПОЛЕ отчёта, а не на словах сводки.

    Сцена: слова в `summary_line` остались прежними, а ПОЛЕ `kind_invalid` исчезло из
    отчёта. Проба, судившая бы подстрокой, этого не заметит.
    """

    def test_losing_a_field_while_keeping_the_words_turns_it_red(self):
        real_triage = T.triage

        def without_field(d, **kw):
            rep = real_triage(d, **kw)
            rep.pop("kind_invalid", None)
            return rep

        with mock.patch.object(T, "triage", without_field):
            verdict, detail = run_probe(NAME)
        self.assertEqual(verdict, NOT_SATISFIED, detail)
        self.assertIn("звено 5", detail)


if __name__ == "__main__":
    unittest.main()
