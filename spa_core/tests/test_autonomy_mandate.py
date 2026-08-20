"""Срок мандата автономии знает код — приёмка (цикл #323, ADR-101).

FROZEN-DATE-OK: injected-clock — часы ИНЪЕКТИРУЮТСЯ (`now=` в каждом
утверждении), а литеральные даты здесь — исторический реестр решений владельца
(ADR-078 09–19.08, ADR-101 20.08–19.09). Обе стороны закреплены: календарь
сдвинется, тесты не покраснеют. `.claude/rules/deployment.md`, предпочтение №1.

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: воспроизводит то, что уже происходило.
На дереве без `autonomy_mandate.py` красным становится весь файл (модуля нет) —
это и есть исходное состояние системы: срока у мандата не знал никто.
"""
# FROZEN-DATE-OK: injected-clock
from __future__ import annotations

import datetime as dt
import os
import unittest

from spa_core.governance.autonomy_mandate import (
    MANDATES,
    RENEWAL_LEAD_DAYS,
    STATE_ACTIVE,
    STATE_ASK_RENEWAL,
    STATE_EXPIRED,
    STATE_NONE,
    STATE_REVOKED,
    Mandate,
    mandate_status,
    summary_lines,
)

D = dt.date.fromisoformat


class TestRealIncidentADR078(unittest.TestCase):
    """Авария №1: у мандата ADR-078 не было срока годности.

    Мандат шёл с 09.08 по 19.08. Вопрос о продлении задали РУКАМИ 19.08 (цикл
    #302) — в последний день. За три дня до конца (16.08) не спросил никто,
    потому что спрашивать было нечему.
    """

    def test_three_days_before_end_asks_for_renewal(self):
        # 16.08 — ровно RENEWAL_LEAD_DAYS до конца ADR-078.
        st = mandate_status(now=D("2026-08-16"))
        self.assertEqual(st["adr"], "ADR-078")
        self.assertEqual(st["days_left"], 3)
        self.assertTrue(st["ask_renewal"],
                        "за 3 дня до конца вопрос о продлении обязан подниматься "
                        "САМ — 16.08.2026 его не задал никто")
        self.assertEqual(st["state"], STATE_ASK_RENEWAL)

    def test_four_days_before_end_does_not_ask_yet(self):
        """Обратный контроль: сторож не должен звонить всё время.

        Тревога, звучащая каждый день, — это не сторож, а фон (ADR-084).
        """
        st = mandate_status(now=D("2026-08-15"))
        self.assertEqual(st["days_left"], 4)
        self.assertFalse(st["ask_renewal"])
        self.assertEqual(st["state"], STATE_ACTIVE)

    def test_last_day_is_still_inside_the_mandate(self):
        """`end` включительно: 19.08 мандат ещё действовал, и это не мелочь —
        именно 19.08 владелец отвечал на вопрос о продлении."""
        st = mandate_status(now=D("2026-08-19"))
        self.assertEqual(st["adr"], "ADR-078")
        self.assertEqual(st["days_left"], 0)
        self.assertEqual(st["tasks_per_cycle"], "many")


class TestNoAutoRenewal(unittest.TestCase):
    """Авария №2: «автопродление запрещено» было обещанием, а не свойством.

    После 19.08 система вернулась к базовому протоколу потому, что кто-то
    написал ADR-088. Здесь истечение срока СУЖАЕТ полномочия само.
    """

    def test_day_after_expiry_reverts_to_base_protocol(self):
        st = mandate_status(now=D("2026-08-20"), mandates=(MANDATES[0],))
        self.assertEqual(st["state"], STATE_EXPIRED)
        self.assertEqual(st["tasks_per_cycle"], "one",
                         "истёкший мандат обязан сузиться САМ, без участия того, "
                         "кто должен был вспомнить")
        self.assertIn("истёк", st["reason"])

    def test_long_after_expiry_never_widens_back(self):
        st = mandate_status(now=D("2026-12-31"), mandates=(MANDATES[0],))
        self.assertEqual(st["state"], STATE_EXPIRED)
        self.assertEqual(st["tasks_per_cycle"], "one")

    def test_gap_between_mandates_is_narrow(self):
        """19.08→20.08 мандат #1 кончился, #2 ещё не начался бы днём раньше."""
        only_second = (MANDATES[1],)
        st = mandate_status(now=D("2026-08-19"), mandates=only_second)
        self.assertEqual(st["state"], STATE_NONE)
        self.assertEqual(st["tasks_per_cycle"], "one")
        self.assertIn("ещё не начался", st["reason"])


class TestMandateTwoIsLive(unittest.TestCase):
    """Решение владельца 2026-08-20: 30 дней, с 20.08 по 19.09 включительно."""

    def test_first_day_active(self):
        st = mandate_status(now=D("2026-08-20"))
        self.assertEqual(st["adr"], "ADR-101")
        self.assertEqual(st["state"], STATE_ACTIVE)
        self.assertEqual(st["tasks_per_cycle"], "many")
        self.assertEqual(st["days_left"], 30)

    def test_renewal_question_fires_on_16_september(self):
        st = mandate_status(now=D("2026-09-16"))
        self.assertEqual(st["adr"], "ADR-101")
        self.assertTrue(st["ask_renewal"])
        self.assertEqual(st["days_left"], RENEWAL_LEAD_DAYS)

    def test_expires_on_20_september(self):
        st = mandate_status(now=D("2026-09-20"))
        self.assertEqual(st["state"], STATE_EXPIRED)
        self.assertEqual(st["adr"], "ADR-101")
        self.assertEqual(st["tasks_per_cycle"], "one")


class TestFailClosed(unittest.TestCase):
    """Неопределённость обязана давать УЗКИЙ протокол, а не широкий.

    Ошибка в сторону «работаем широко» молча расширяет полномочия агента, и
    заметить её будет некому — ровно та авария, от которой заведён модуль.
    """

    def test_empty_registry_is_narrow(self):
        st = mandate_status(now=D("2026-08-20"), mandates=())
        self.assertEqual(st["state"], STATE_NONE)
        self.assertEqual(st["tasks_per_cycle"], "one")

    def test_contradictory_registry_is_narrow_not_widest(self):
        """Две записи на одну дату — состояние НЕ измерено.

        Соблазн «взять ту, что пошире» здесь и есть fail-OPEN.
        """
        a = Mandate(adr="ADR-X", start=D("2026-08-01"), end=D("2026-09-01"),
                    title="x")
        b = Mandate(adr="ADR-Y", start=D("2026-08-10"), end=D("2026-10-01"),
                    title="y")
        st = mandate_status(now=D("2026-08-20"), mandates=(a, b))
        self.assertEqual(st["state"], STATE_NONE)
        self.assertEqual(st["tasks_per_cycle"], "one")
        self.assertIn("противоречив", st["reason"])
        self.assertIn("ADR-X", st["reason"])
        self.assertIn("ADR-Y", st["reason"])

    def test_owner_revocation_takes_effect_same_day(self):
        """Отзыв владельцем — досрочно и сразу, без ожидания конца срока."""
        m = Mandate(adr="ADR-Z", start=D("2026-08-01"), end=D("2026-09-30"),
                    title="z", revoked_on=D("2026-08-15"))
        self.assertEqual(mandate_status(now=D("2026-08-14"), mandates=(m,))["state"],
                         STATE_ACTIVE)
        st = mandate_status(now=D("2026-08-15"), mandates=(m,))
        self.assertEqual(st["state"], STATE_REVOKED)
        self.assertEqual(st["tasks_per_cycle"], "one")
        self.assertIn("ОТОЗВАН", st["reason"])

    def test_reason_is_always_spoken(self):
        """Молчаливого отказа быть не должно ни в одном состоянии."""
        for now in ("2026-08-05", "2026-08-16", "2026-08-20", "2026-09-25"):
            with self.subTest(now=now):
                st = mandate_status(now=D(now))
                self.assertTrue(st["reason"].strip(),
                                "состояние без названной причины — молчаливый отказ")


class TestInvariantsNeverWiden(unittest.TestCase):
    """Самый широкий мандат НЕ разрешает owner-gated мест — ни в одном состоянии."""

    FORBIDDEN = ("RiskPolicy", "kill-switch", "реальный капитал", "legal")

    def test_never_list_present_in_every_state(self):
        for now in ("2026-08-16", "2026-08-20", "2026-09-25"):
            with self.subTest(now=now):
                st = mandate_status(now=D(now))
                for token in self.FORBIDDEN:
                    self.assertIn(token, st["never"])

    def test_summary_prints_the_never_list_even_when_active(self):
        lines = "\n".join(summary_lines(now=D("2026-08-20")))
        for token in self.FORBIDDEN:
            self.assertIn(token, lines)


class TestSummaryLinesAreAJudgement(unittest.TestCase):
    """Читателю нужен ответ «как работать», а не две даты для устного вычитания."""

    def test_active_says_many_tasks(self):
        lines = "\n".join(summary_lines(now=D("2026-08-20")))
        self.assertIn("ACTIVE", lines)
        self.assertIn("несколько задач за цикл", lines)

    def test_expired_says_one_task(self):
        lines = "\n".join(summary_lines(now=D("2026-09-25")))
        self.assertIn("ОДНА безопасная задача за цикл", lines)

    def test_ask_renewal_names_the_owner_decision_point(self):
        lines = "\n".join(summary_lines(now=D("2026-09-17")))
        self.assertIn("автопродление запрещено", lines)
        self.assertIn("карточку-вопрос", lines)


class TestWiredIntoTheMandatoryStep(unittest.TestCase):
    """Сторож без ЧИТАТЕЛЯ — украшение (правило класса, #197).

    Мутировать проводку, а не только части: одного удалённого места вызова
    хватало, чтобы 1364 теста остались зелёными. Здесь проверяется ЭФФЕКТ —
    что обязательный шаг 0-офис действительно печатает суждение о мандате, —
    и в ДОЧЕРНЕМ процессе: перехват stdout внутри pytest уже раз ослеплял
    проверки прод-эффекта.
    """

    def _run_step(self, root: str) -> str:
        import subprocess
        import sys
        # Артефактов офиса в worktree нет (они в .gitignore) — шаг вернёт 3
        # «офис НЕ ИЗМЕРЕН». Это ровно тот случай, ради которого строка о
        # мандате печатается ДО манифеста: ответ «как работать» не зависит от
        # того, читается ли офис.
        p = subprocess.run(
            [sys.executable, os.path.join(root, "scripts", "consume_office_reports.py"),
             "--no-receipts"],
            capture_output=True, text=True, cwd=root, timeout=180)
        return p.stdout

    def test_office_step_prints_the_mandate_judgement(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        out = self._run_step(root)
        self.assertIn("мандат автономии:", out,
                      "обязательный шаг цикла обязан произносить ширину "
                      "полномочий — иначе о сроке снова не узнает никто")
        self.assertIn("режим цикла:", out)

    def test_mandate_line_survives_an_unmeasurable_office(self):
        """Даже когда офис не измерить, ответ о мандате уже произнесён."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        out = self._run_step(root)
        head = out.strip().splitlines()[0] if out.strip() else ""
        self.assertIn("мандат автономии:", head,
                      "строка о мандате обязана быть ПЕРВОЙ, до манифеста и "
                      "до любых ранних return")

    def test_fail_closed_when_the_module_cannot_be_read(self):
        """Импорт не удался ⇒ УЗКИЙ протокол, а не молчаливое «работаем как шли»."""
        import importlib
        import sys as _sys
        mod = importlib.import_module("scripts.consume_office_reports") \
            if "scripts.consume_office_reports" in _sys.modules else None
        if mod is None:  # загрузка по пути к файлу — sys.path репо не гарантирован
            import importlib.util
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            spec = importlib.util.spec_from_file_location(
                "_cor_probe", os.path.join(root, "scripts",
                                           "consume_office_reports.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        real = _sys.modules.get("spa_core.governance.autonomy_mandate")
        _sys.modules["spa_core.governance.autonomy_mandate"] = None  # ломаем импорт
        try:
            lines = "\n".join(mod._mandate_lines(dt.datetime(2026, 8, 20)))
        finally:
            if real is not None:
                _sys.modules["spa_core.governance.autonomy_mandate"] = real
            else:
                _sys.modules.pop("spa_core.governance.autonomy_mandate", None)
        self.assertIn("НЕ ИЗМЕРЕН", lines)
        self.assertIn("ОДНА безопасная задача", lines)


class TestRegistryIsSane(unittest.TestCase):
    """Реестр — след решений владельца; порядок и непротиворечивость проверяем."""

    def test_every_mandate_has_start_before_end(self):
        for m in MANDATES:
            with self.subTest(adr=m.adr):
                self.assertLessEqual(m.start, m.end)

    def test_no_two_mandates_overlap(self):
        ordered = sorted(MANDATES, key=lambda m: m.start)
        for prev, nxt in zip(ordered, ordered[1:]):
            with self.subTest(pair=(prev.adr, nxt.adr)):
                self.assertLess(prev.end, nxt.start,
                                "пересекающиеся мандаты дают fail-CLOSED на всём "
                                "пересечении — реестр обязан быть однозначным")

    def test_adr_101_window_is_exactly_thirty_days(self):
        m = [x for x in MANDATES if x.adr == "ADR-101"][0]
        self.assertEqual((m.end - m.start).days, 30,
                         "решение владельца: 30 дней с 2026-08-20 по 2026-09-19")


if __name__ == "__main__":
    unittest.main()
