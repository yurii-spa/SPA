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


def _registry_as_of(*adrs: str) -> tuple:
    """Реестр таким, каким он БЫЛ в день проверяемой аварии.

    Зачем (цикл #623). Контроль исторической аварии не имеет права зависеть от
    записей, которых в тот день ещё не существовало. До ADR-407 это сходило с
    рук: у последнего мандата преемника не было, и разницы между «реестр
    тогдашний» и «реестр сегодняшний» не возникало. С появлением преемника
    разница появилась — и утверждение «16.08 вопрос о продлении обязан
    подниматься сам» стало бы ложным по причине, не имеющей к августу никакого
    отношения. Записи берутся ИЗ настоящего реестра, а не переписываются здесь:
    иначе тест сторожил бы свою копию (`.claude/rules/deployment.md`, «вторая
    копия у читателя»).
    """
    sel = tuple(m for m in MANDATES if m.adr in adrs)
    if len(sel) != len(adrs):
        raise AssertionError(
            f"в реестре нет записей {set(adrs) - {m.adr for m in sel}} — "
            f"тест сторожит не тот реестр")
    return sel


#: Реестр на 16.08.2026 — один мандат ADR-078, преемника ещё нет.
REG_078 = _registry_as_of("ADR-078")
#: Реестр на 16.09.2026 — ADR-078 + ADR-101, ответа о продлении ещё нет.
REG_101 = _registry_as_of("ADR-078", "ADR-101")


class TestRealIncidentADR078(unittest.TestCase):
    """Авария №1: у мандата ADR-078 не было срока годности.

    Мандат шёл с 09.08 по 19.08. Вопрос о продлении задали РУКАМИ 19.08 (цикл
    #302) — в последний день. За три дня до конца (16.08) не спросил никто,
    потому что спрашивать было нечему.
    """

    def test_three_days_before_end_asks_for_renewal(self):
        # 16.08 — ровно RENEWAL_LEAD_DAYS до конца ADR-078. Реестр — ТОГДАШНИЙ
        # (см. `_registry_as_of`): преемника 16.08 не существовало, и вопрос
        # обязан был подниматься.
        st = mandate_status(now=D("2026-08-16"), mandates=REG_078)
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
        st = mandate_status(now=D("2026-08-15"), mandates=REG_078)
        self.assertEqual(st["days_left"], 4)
        self.assertFalse(st["ask_renewal"])
        self.assertEqual(st["state"], STATE_ACTIVE)

    def test_last_day_is_still_inside_the_mandate(self):
        """`end` включительно: 19.08 мандат ещё действовал, и это не мелочь —
        именно 19.08 владелец отвечал на вопрос о продлении."""
        st = mandate_status(now=D("2026-08-19"), mandates=REG_078)
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
        # Реестр ТОГДАШНИЙ: 16.09 ответа владельца ещё не было, и карточку
        # обязан был завести сам сторож. Он её и завёл — карточка
        # `owner-decision-mandat-samostoyatelnoi-raboty-konchaetsy-2`.
        st = mandate_status(now=D("2026-09-16"), mandates=REG_101)
        self.assertEqual(st["adr"], "ADR-101")
        self.assertTrue(st["ask_renewal"])
        self.assertEqual(st["days_left"], RENEWAL_LEAD_DAYS)

    def test_expires_on_20_september(self):
        """Без преемника 20.09 — базовый протокол. Это по-прежнему верно, и
        именно поэтому решение владельца 17.09 пришлось ЗАПИСАТЬ кодом."""
        st = mandate_status(now=D("2026-09-20"), mandates=REG_101)
        self.assertEqual(st["state"], STATE_EXPIRED)
        self.assertEqual(st["adr"], "ADR-101")
        self.assertEqual(st["tasks_per_cycle"], "one")

    def test_window_of_adr_101_is_not_rewritten_by_the_renewal(self):
        """Реестр — СЛЕД решений владельца, а не настройка.

        Соблазн при продлении — растянуть `end` действующей записи. Тогда
        история перестала бы быть историей: из реестра было бы не прочесть, что
        мандат №2 был тридцатидневным и что владелец отвечал 17.09.
        """
        m = [x for x in MANDATES if x.adr == "ADR-101"][0]
        self.assertEqual(m.end, D("2026-09-19"))
        self.assertIsNotNone(m.end, "продление не имеет права снимать срок с ЧУЖОЙ записи")


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
        lines = "\n".join(summary_lines(now=D("2026-09-25"), mandates=REG_101))
        self.assertIn("ОДНА безопасная задача за цикл", lines)

    def test_ask_renewal_names_the_owner_decision_point(self):
        lines = "\n".join(summary_lines(now=D("2026-09-17"), mandates=REG_101))
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
                if m.end is None:
                    continue  # мандат без срока — проверяется ниже, отдельно
                self.assertLessEqual(m.start, m.end)

    def test_no_two_mandates_overlap(self):
        ordered = sorted(MANDATES, key=lambda m: m.start)
        for prev, nxt in zip(ordered, ordered[1:]):
            with self.subTest(pair=(prev.adr, nxt.adr)):
                self.assertIsNotNone(
                    prev.end,
                    f"{prev.adr} без срока, а после него начинается {nxt.adr}: "
                    f"пересечение вечное, и весь остаток времени реестр "
                    f"противоречив ⇒ базовый протокол навсегда")
                self.assertLess(prev.end, nxt.start,
                                "пересекающиеся мандаты дают fail-CLOSED на всём "
                                "пересечении — реестр обязан быть однозначным")

    def test_an_open_ended_mandate_is_the_last_one(self):
        """Обратная сторона предыдущего: запись без срока обязана быть хвостом.

        Не оговорка ради красоты — иначе `covering` вернул бы две записи и
        модуль честно ушёл бы в базовый протокол НАВСЕГДА, а выглядело бы это
        как «мандат почему-то не действует».
        """
        open_ended = [m for m in MANDATES if m.end is None]
        self.assertLessEqual(len(open_ended), 1,
                             "двух бессрочных мандатов быть не может")
        if open_ended:
            last = max(MANDATES, key=lambda m: m.start)
            self.assertEqual(open_ended[0].adr, last.adr)

    def test_adr_101_window_is_exactly_thirty_days(self):
        m = [x for x in MANDATES if x.adr == "ADR-101"][0]
        self.assertEqual((m.end - m.start).days, 30,
                         "решение владельца: 30 дней с 2026-08-20 по 2026-09-19")


class TestMandateThreeIsOpenEnded(unittest.TestCase):
    """Решение владельца 2026-09-17 20:10:45Z (вариант 1): продлить БЕЗ СРОКА.

    Каждый тест — положительный контроль на то, что записано кодом, а не
    прозой: до этой правки «без срока» было бы невыразимо — поле `end`
    требовало даты, и любая запись создавала бы новый будильник.
    """

    def test_open_ended_mandate_is_active_and_wide(self):
        for now in ("2026-09-20", "2026-12-31", "2030-01-01"):
            with self.subTest(now=now):
                st = mandate_status(now=D(now))
                self.assertEqual(st["adr"], "ADR-407")
                self.assertEqual(st["state"], STATE_ACTIVE)
                self.assertEqual(st["tasks_per_cycle"], "many")

    def test_open_ended_never_asks_for_renewal_again(self):
        """Будильник снят — и снят САМИМ решением, а не потерян."""
        for now in ("2026-09-20", "2027-06-01"):
            with self.subTest(now=now):
                self.assertFalse(mandate_status(now=D(now))["ask_renewal"])

    def test_absent_deadline_is_its_own_value_not_a_silent_none(self):
        """Инвариант #17: `days_left is None` значит РАЗНОЕ, и различает ключ.

        В состоянии `ACTIVE` без срока и в базовом протоколе `days_left`
        одинаково `None`. Если бы различать их было нечем, читатель имел бы два
        разных мира под одним значением — ровно та подмена, которую инвариант
        запрещает.
        """
        wide = mandate_status(now=D("2026-09-20"))
        self.assertIsNone(wide["days_left"])
        self.assertTrue(wide["open_ended"])

        narrow = mandate_status(now=D("2026-09-20"), mandates=())
        self.assertIsNone(narrow["days_left"])
        self.assertFalse(narrow["open_ended"],
                         "«мандата нет» и «у мандата нет срока» обязаны быть "
                         "различимы у читателя, а не на глаз")
        self.assertEqual(narrow["tasks_per_cycle"], "one")

    def test_open_ended_is_still_revocable_by_the_owner(self):
        """Единственный выход из бессрочного мандата обязан работать.

        Без этого «без срока» означало бы «навсегда», а владелец выбирал
        вариант, в котором отзыв — одна кнопка.
        """
        m = Mandate(adr="ADR-Q", start=D("2026-01-01"), end=None, title="q",
                    revoked_on=D("2026-05-05"))
        self.assertEqual(mandate_status(now=D("2026-05-04"), mandates=(m,))["state"],
                         STATE_ACTIVE)
        st = mandate_status(now=D("2026-05-05"), mandates=(m,))
        self.assertEqual(st["state"], STATE_REVOKED)
        self.assertEqual(st["tasks_per_cycle"], "one")
        self.assertIn("ОТОЗВАН", st["reason"])

    def test_no_deadline_must_be_declared_not_omitted(self):
        """«Без срока» — объявление, а не забытый аргумент.

        У `end` нет умолчания намеренно: умолчание `None` означало бы, что
        опечатка в новой записи молча делает мандат вечным. Полномочия агента
        расширяются только тем, что владелец сказал вслух.
        """
        with self.assertRaises(TypeError):
            Mandate(adr="ADR-NOPE", start=D("2026-01-01"), title="no end given")

    def test_widest_state_is_never_silent_about_being_widest(self):
        lines = "\n".join(summary_lines(now=D("2026-09-20")))
        self.assertIn("СРОКА НЕТ", lines)
        self.assertIn("отзыв", lines)
        self.assertIn("несколько задач за цикл", lines)

    def test_there_is_no_gap_between_mandate_two_and_three(self):
        """19.09 действует №2, 20.09 — №3, и базового протокола между ними нет."""
        self.assertEqual(mandate_status(now=D("2026-09-19"))["adr"], "ADR-101")
        self.assertEqual(mandate_status(now=D("2026-09-20"))["adr"], "ADR-407")
        for now in ("2026-09-19", "2026-09-20"):
            with self.subTest(now=now):
                self.assertEqual(mandate_status(now=D(now))["tasks_per_cycle"],
                                 "many")


class TestTheAnsweredQuestionIsNotAskedTwice(unittest.TestCase):
    """Записанный преемник ГАСИТ вопрос о продлении — и только вопрос.

    ADR-285: карточка в очереди `needs-owner`, на которую ответ уже дан, есть
    дефект очереди, а не ожидание. Замер, вызвавший то решение, — 247 карточек
    за 55 дней. Сторож, звонящий после ответа, пополняет ровно этот счёт.
    """

    EARLIER = Mandate(adr="ADR-A", start=D("2026-01-01"), end=D("2026-01-31"),
                      title="a")
    NEXT_DAY = Mandate(adr="ADR-B", start=D("2026-02-01"), end=D("2026-03-31"),
                       title="b")
    AFTER_A_GAP = Mandate(adr="ADR-C", start=D("2026-06-01"), end=D("2026-07-31"),
                          title="c")

    def test_without_a_successor_the_question_is_asked(self):
        """Положительный контроль: без записанного ответа сторож звонит."""
        st = mandate_status(now=D("2026-01-29"), mandates=(self.EARLIER,))
        self.assertTrue(st["ask_renewal"])
        self.assertEqual(st["state"], STATE_ASK_RENEWAL)
        self.assertIn("ЗАВЕСТИ карточку", st["reason"])

    def test_a_recorded_successor_silences_it_and_says_why(self):
        st = mandate_status(now=D("2026-01-29"),
                            mandates=(self.EARLIER, self.NEXT_DAY))
        self.assertFalse(st["ask_renewal"])
        self.assertEqual(st["state"], STATE_ACTIVE)
        self.assertIn("ADR-B", st["reason"],
                      "молчание без названной причины — не ответ, а пропажа")
        self.assertNotIn("ЗАВЕСТИ карточку", st["reason"])

    def test_silencing_the_question_widens_nothing(self):
        """Гасится ВОПРОС, а не срок: та же запись кончается в тот же день."""
        st = mandate_status(now=D("2026-01-29"),
                            mandates=(self.EARLIER, self.NEXT_DAY))
        self.assertEqual(st["adr"], "ADR-A")
        self.assertEqual(st["end"], D("2026-01-31"))
        self.assertEqual(st["days_left"], 2)

    def test_a_successor_after_a_gap_still_leaves_the_gap_narrow(self):
        """Преемник с разрывом гасит вопрос, но НЕ закрывает разрыв.

        Обратная сторона той же правки: если бы гашение вопроса заодно
        расширяло полномочия на пустые дни, это был бы fail-OPEN — молчаливое
        автопродление, прямо запрещённое решением владельца 2026-08-20.
        """
        regs = (self.EARLIER, self.AFTER_A_GAP)
        self.assertFalse(mandate_status(now=D("2026-01-29"), mandates=regs)["ask_renewal"])
        for now in ("2026-02-01", "2026-05-31"):
            with self.subTest(now=now):
                st = mandate_status(now=D(now), mandates=regs)
                self.assertEqual(st["state"], STATE_EXPIRED)
                self.assertEqual(st["tasks_per_cycle"], "one")

    def test_an_open_ended_mandate_has_no_successor_to_look_for(self):
        """У бессрочного вопроса о продлении нет ни по календарю, ни по поиску."""
        never_ends = Mandate(adr="ADR-D", start=D("2026-01-01"), end=None, title="d")
        st = mandate_status(now=D("2026-01-29"), mandates=(never_ends,))
        self.assertFalse(st["ask_renewal"])
        self.assertTrue(st["open_ended"])


if __name__ == "__main__":
    unittest.main()
