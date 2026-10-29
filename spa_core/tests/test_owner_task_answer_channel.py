"""Канал ОТВЕТА на задание владельца (ADR-863, цикл #980).

Положительный контроль — сама авария 29.10: владелец семь раз сказал «проверь дашборд»,
ответ дважды был записан В ФАЙЛ, и ни одна запись не утверждала, что он до него дошёл.
Каждая сцена ниже — её звено, и к каждой приложена ОБРАТНАЯ, отличающаяся РОВНО одним.

Время здесь ВХОД, а не окружение (`.claude/rules/deployment.md` § «Время в тестах»,
приём №1): и дочистка, и writer принимают `now`, и ни одна проверка не смотрит на
стенные часы. Литеральных дат в фикстурах нет — поэтому и пометки `FROZEN-DATE-OK`
не требуется.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.owner_queue import answer_channel as ac
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import queue as q

#: Часы инъектируются во ВСЕ звенья; значение произвольно и ни на что не влияет.
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

CARD = """---
trackerStatus:
  type: inbox
title: {title}
status: {status}
source: {source}
{extra}---

{body}
"""


def write_card(d: Path, name: str, *, title="проверь дашборд", status="in-progress",
               source="voice", extra='acceptance_probe: "problem_absent:x"\n', body="## ОТВЕТ\n\nдашборд проверен, числа сошлись"):
    p = d / f"inbox-{name}.md"
    p.write_text(CARD.format(title=title, status=status, source=source, extra=extra,
                             body=body), encoding="utf-8")
    return p


def fresh_outbox(d: Path) -> Path:
    ob = d / "outbox.json"
    ob.write_text(json.dumps({"schema": 1, "pending": []}), encoding="utf-8")
    return ob


def outbox_items(ob: Path) -> list[dict]:
    return json.loads(ob.read_text(encoding="utf-8"))["pending"]


class TheDoorDistinguishesThreeOutcomes(unittest.TestCase):
    """Инв. #17 у самой двери: «дошло» · «ещё нет» · «НЕ ИЗМЕРЕНО» — три разных ответа."""

    def test_exemplar_distinguishes_on_scenes_differing_only_by_the_mark(self):
        drive = ac.drive_exemplar()
        self.assertEqual(ac.DRIVE_DISTINGUISHES, drive["kind"],
                         f"эталон не различает исходы: {drive.get('verdicts')}")
        self.assertEqual((None, False, True), drive["verdicts"])

    def test_silence_is_never_read_as_delivered(self):
        """ОБРАТНАЯ сцена к главной: метки нет ⇒ None, и НИКОГДА True."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "hist", status="done")       # историческая форма: метки нет
            ok, why = ac.delivery_verdict(p, outbox_path=fresh_outbox(d))
            self.assertIsNone(ok, f"молчание выдано за ответ: {why}")
            self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_queued_but_not_accepted_is_false_not_true(self):
        """Запись ВСЁ ЕЩЁ в исходящих ⇒ канал её не принял. «Положили» ≠ «отдали»."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "q", status="done",
                           extra=f'owner_notice: "{ac.ANSWER_SENT}"\n')
            ob = d / "outbox.json"
            ob.write_text(json.dumps({"schema": 1, "pending": [
                {"key": f"{p.name}#{ac.EVENT_ANSWER}", "text": "t", "queued_at": "x"}]}),
                encoding="utf-8")
            ok, why = ac.delivery_verdict(p, outbox_path=ob)
            self.assertIs(False, ok, why)

    def test_unreadable_outbox_is_unmeasured_not_delivered(self):
        """Нечитаемые исходящие — третий исход. Пустота означала бы «всё отдано»."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "u", status="done",
                           extra=f'owner_notice: "{ac.ANSWER_SENT}"\n')
            bad = d / "outbox.json"
            bad.write_text("{ не json", encoding="utf-8")
            ok, why = ac.delivery_verdict(p, outbox_path=bad)
            self.assertIsNone(ok, f"битые исходящие выданы за доставку: {why}")


class TheChainFromClosureToTheOwnersChannel(unittest.TestCase):
    """Сквозное звено: закрыли задание → метка → исходящие → вердикт «отдано»."""

    def test_closing_a_voice_task_with_an_answer_reaches_the_channel(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "dash")
            ob = fresh_outbox(d)

            q.set_status(p, "done", closed_by="test", evidence="ответ в теле карточки")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(ac.ANSWER_PENDING, fm.get("owner_notice"),
                             "закрытие не оставило следа для канала")
            self.assertIs(False, ac.delivery_verdict(p, outbox_path=ob)[0])

            queued = cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW)
            self.assertEqual([p.name], queued)
            items = outbox_items(ob)
            self.assertEqual([f"{p.name}#{ac.EVENT_ANSWER}"], [i["key"] for i in items])

            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(ac.ANSWER_SENT, fm.get("owner_notice"))
            # Отдано каналу — только когда исходящие запись ПРИНЯЛИ (flush вычеркнул).
            ob.write_text(json.dumps({"schema": 1, "pending": []}), encoding="utf-8")
            ok, why = ac.delivery_verdict(p, outbox_path=ob)
            self.assertIs(True, ok, why)

    def test_the_notice_is_queued_once_not_on_every_sweep(self):
        """Решение «слать ли» живёт в поле: второй прогон дочистки дубля не делает."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "once")
            ob = fresh_outbox(d)
            q.set_status(p, "done", closed_by="test", evidence="e")
            self.assertEqual([p.name], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertEqual([], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))


class TheHistoricalPopulationIsNamedNotMailed(unittest.TestCase):
    """АНТИ-ШТОРМ. Канал появился сегодня; 18 закрытых просьб — не повод для 18 сообщений."""

    def test_a_card_closed_before_the_channel_is_never_queued(self):
        """Историческая форма: закрыта, ответ записан, метки нет ⇒ дочистка молчит."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "old", status="done",
                           extra="carried_to: nimbalyst-local/tracker/inbox-anchor.md\n")
            ob = fresh_outbox(d)
            self.assertEqual([], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertEqual([], outbox_items(ob))
            self.assertIsNone(ac.delivery_verdict(p, outbox_path=ob)[0])

    def test_the_line_is_a_field_not_a_calendar(self):
        """Та же карточка с меткой — уедет; без метки — нет. Различает ПОЛЕ, не дата.

        Обе сцены судятся ОДНИМИ часами `NOW`, поэтому разный исход календарю приписать
        нечему: сдвинь часы куда угодно — ответ не изменится.
        """
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ob = fresh_outbox(d)
            write_card(d, "nomark", status="done")
            write_card(d, "marked", status="done",
                       extra=f'owner_notice: "{ac.ANSWER_PENDING}"\n')
            self.assertEqual(["inbox-marked.md"],
                             cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))


class WhatTheChannelRefusesToClaim(unittest.TestCase):
    """Границы населения и честность основания — обе измеряются поведением."""

    def test_a_closed_task_with_no_recorded_answer_says_nothing(self):
        """«Готово», не умея сказать ЧТО, — обещание, а не ответ."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "empty", body="(ничего не записано)")
            ob = fresh_outbox(d)
            q.set_status(p, "done", closed_by="test", evidence="e")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertIsNone(fm.get("owner_notice"))
            self.assertEqual([], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))

    def test_an_agent_born_card_is_outside_the_population(self):
        """`source: nimbalyst` — находка сторожа, а не просьба владельца. ОБРАТНАЯ сцена
        к главной, отличающаяся РОВНО источником."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "agent", source="nimbalyst")
            ob = fresh_outbox(d)
            q.set_status(p, "done", closed_by="test", evidence="e")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertIsNone(fm.get("owner_notice"),
                             "находка сторожа ушла бы владельцу как его просьба")
            self.assertEqual([], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertIsNone(ac.delivery_verdict(p, outbox_path=ob)[0])

    def test_the_basis_is_named_honestly_and_a_probe_is_never_invented(self):
        """Три рода основания дают ТРИ РАЗНЫХ текста, и там, где пробы нет, её не называют."""
        probe = ac.answer_notice_text("t", ac.EV_PROBE, "some_probe", "inbox-a.md")
        carried = ac.answer_notice_text("t", ac.EV_CARRIED, "docs/x.md", "inbox-a.md")
        section = ac.answer_notice_text("t", ac.EV_SECTION, "", "inbox-a.md")
        self.assertEqual(3, len({probe, carried, section}),
                         "разные основания печатаются одинаково")
        for text in (carried, section):
            self.assertNotIn("пробой", text, "названа проверка, которой не было")

    def test_the_cockpit_path_keeps_its_own_event(self):
        """Путь пульта не задет: своя метка, своё событие, одно сообщение."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "cockpit", status="done", source="cockpit",
                           extra='verified_by_probe: "problem_absent:x"\n')
            ob = fresh_outbox(d)
            self.assertEqual([p.name], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertEqual([f"{p.name}#{cl.EVENT_DONE}"],
                             [i["key"] for i in outbox_items(ob)])
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(cl.EVENT_DONE, fm.get("owner_notice"))
            # По предмету ЭТОГО модуля путь пульта отвечает ДА: та же дверь, тот же Telegram.
            ob.write_text(json.dumps({"schema": 1, "pending": []}), encoding="utf-8")
            self.assertIs(True, ac.delivery_verdict(p, outbox_path=ob)[0])


class ThePopulationIsMeasuredNotAsserted(unittest.TestCase):
    """Перепись публикует число отсутствия ЗНАЧЕНИЕМ и у него есть читатель (ADR-851/856)."""

    def test_census_counts_each_outcome_separately(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ob = fresh_outbox(d)
            write_card(d, "hist", status="done")                      # unmeasured
            write_card(d, "none", status="done", body="пусто")         # no_answer
            write_card(d, "pend", status="done",
                       extra=f'owner_notice: "{ac.ANSWER_PENDING}"\n')  # pending
            write_card(d, "sent", status="done",
                       extra=f'owner_notice: "{ac.ANSWER_SENT}"\n')     # delivered
            write_card(d, "open")                                      # не закрыта
            r = ac.measure(d, outbox_path=ob)
            self.assertEqual(4, r["closed_owner_tasks"])
            self.assertEqual({ac.DELIVERED: 1, ac.PENDING: 1, ac.UNMEASURED: 1,
                              ac.NO_ANSWER: 1}, r["counts"])

    def test_a_missing_tracker_is_unmeasured_with_a_named_reason(self):
        """Каталога нет ⇒ «не измерено» с причиной, а не «закрытых заданий ноль»."""
        r = ac.measure("/nonexistent/tracker/for/the/test")
        self.assertIsNone(r["closed_owner_tasks"])
        self.assertIn("каталога трекера нет", r["unmeasured_reason"])


if __name__ == "__main__":
    unittest.main()


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Контроль пробы в ОБЕ стороны (`.claude/rules/acceptance.md` п. 3).

    Зелёная проба, никогда не видевшая настоящей поломки, — украшение. Здесь каждое
    звено контура рвётся по отдельности, и проба обязана покраснеть С НАЗВАННЫМ звеном.
    Отдельно проверено, что подстрокой она НЕ проходит (ADR-333): текст сообщения можно
    оставить верным и всё равно не доставить его — проба спрашивает КЛЮЧ и ВЕРДИКТ.
    """

    PROBE = "owner_task_answer_reaches_the_channel"

    def run_probe(self):
        from spa_core.monitoring.card_acceptance import run_probe
        return run_probe(self.PROBE)

    def test_green_on_the_whole_circuit(self):
        verdict, detail = self.run_probe()
        self.assertEqual("satisfied", verdict, detail)

    def test_red_when_the_exemplar_conflates_outcomes(self):
        from unittest.mock import patch
        with patch.object(ac, "drive_exemplar",
                          return_value={"kind": ac.DRIVE_CONFLATES,
                                        "verdicts": (None, None, None)}):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("эталон", detail)

    def test_red_when_closing_leaves_no_mark_for_the_channel(self):
        """Рвём ПЕРВОЕ звено: закрытие больше не видит в карточке записанного ответа.

        Рвать здесь `is_owner_task` НЕЛЬЗЯ, и это не придирка: его зовёт и эталон, так
        что проба покраснела бы РАНЬШЕ и на ДРУГОМ звене — контроль подтвердил бы сам
        себя. `answer_evidence` же оставляет эталон различающим (его сцены разделены
        меткой, а не основанием), поэтому красным оказывается именно первое звено.
        """
        from unittest.mock import patch
        with patch.object(ac, "answer_evidence", return_value=None):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("НЕ оставило следа", detail)

    def test_red_when_the_sweep_never_queues_the_answer(self):
        """Рвём ВТОРОЕ звено: метка ставится, но в исходящие ничего не кладётся.

        Это же и проверка «не проходит подстрокой»: тексты уведомлений не тронуты и
        остались верными — проба краснеет, потому что спрашивает КЛЮЧ в очереди.
        """
        from unittest.mock import patch
        with patch.object(cl, "_ensure_answer_notice", return_value=False):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("исходящие", detail)

    def test_red_when_the_anti_storm_is_breached(self):
        """Рвём ТРЕТЬЕ звено: дочистка берёт КАЖДОЕ закрытое задание с ответом.

        Это и есть правка, от которой защищает поле-граница: достаточно уронить
        проверку метки, и канал начнёт рассылать историю. Рвать надо на уровне
        `sweep_notices`, а не `_ensure_answer_notice`, — именно там стоит отсев по
        метке, и первая редакция этого контроля ошиблась, подменив звено ниже отсева
        (поломка не воспроизводилась, и проба честно оставалась зелёной).
        """
        from unittest.mock import patch

        def greedy_sweep(*, tracker_dir=None, outbox_path=None, now=None):
            out = []
            for card in sorted(Path(tracker_dir).glob("inbox-*.md")):
                fm, body = ac.split_frontmatter(card.read_text(encoding="utf-8"))
                if not (ac.is_owner_task(fm) and ac.is_closed(fm)):
                    continue
                if ac.answer_evidence(fm, body) is None:
                    continue
                cl._set_fields(card, {"owner_notice": ac.ANSWER_PENDING})
                if cl._ensure_answer_notice(card, now, outbox_path):
                    out.append(card.name)
            return out

        with patch.object(cl, "sweep_notices", side_effect=greedy_sweep):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("АНТИ-ШТОРМ ПРОБИТ", detail)

    def test_unmeasured_is_its_own_outcome_when_the_scene_cannot_be_built(self):
        """Третий исход у пробы СВОЙ: сцена не собралась ⇒ не «не выполнено»."""
        from unittest.mock import patch
        with patch.object(q, "set_status", side_effect=RuntimeError("дверь недоступна")):
            verdict, detail = self.run_probe()
        self.assertEqual("unmeasured", verdict)
        self.assertIn("НЕ ИЗМЕРИТЬ", detail)


class TheBoundaryWithTheCockpitWriter(unittest.TestCase):
    """Один писатель на карточку: пульт с пробой — свой, остальные — канал ответа.

    Этот класс написан по чужому красному тесту, а не по разбору: первая редакция
    ставила метку и на карточку пульта, закрытую пробой, и положительный контроль
    восстановления пульта после падения (`test_cockpit_loop.py`) покраснел на лишней
    метке. Второй писатель одного понятия (ADR-220) — именно то, от чего он сторожит.
    """

    def test_a_probe_closed_cockpit_card_gets_no_answer_mark(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "cock", source="cockpit",
                           extra=('acceptance_probe: "problem_absent:x"\n'
                                  'verified_by_probe: "problem_absent:x"\n'))
            q.set_status(p, "done", closed_by="test", evidence="e")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertNotIn("owner_notice", fm,
                             "у карточки пульта с пробой появился второй писатель")

    def test_a_cockpit_card_without_a_probe_does_get_the_channel(self):
        """ОБРАТНАЯ сцена, отличающаяся РОВНО пробой: без неё писателя не было ни у кого."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "cockvoice", source="cockpit-voice")
            q.set_status(p, "done", closed_by="test", evidence="e")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(ac.ANSWER_PENDING, fm.get("owner_notice"))


class HolesFoundByTheMutationRun(unittest.TestCase):
    """Сцены, которых не было в первой редакции: их назвал мутационный прибор, не разбор.

    Каждая закрывает ВЫЖИВШЕГО мутанта из `docs/mutations/ADR-863.json`. Отдельно
    записано, что ДВА выживших оказались ЭКВИВАЛЕНТНЫМИ, а не дырами, — см.
    :class:`TheAntiStormIsHeldByTwoIndependentConditions`.
    """

    def test_a_well_formed_but_wrong_shaped_outbox_is_unmeasured(self):
        """Исходящие разбираются, но `pending` не список ⇒ «не измерено», а не «пусто».

        Первая редакция мерила только НЕразбираемый файл, и мутант, снявший проверку
        ФОРМЫ, выжил: `json.loads` на «{ не json» падает и без него. Пустое же
        множество ключей означало бы «канал всё принял» — тот же fail-OPEN, с другой
        стороны.
        """
        for payload in ('{"schema": 1, "pending": "не список"}', '[]', 'null'):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as td:
                    d = Path(td)
                    p = write_card(d, "shape", status="done",
                                   extra=f'owner_notice: "{ac.ANSWER_SENT}"\n')
                    ob = d / "outbox.json"
                    ob.write_text(payload, encoding="utf-8")
                    ok, why = ac.delivery_verdict(p, outbox_path=ob)
                    self.assertIsNone(ok, f"форма исходящих не проверена: {why}")

    def test_closing_never_overwrites_a_notice_already_given(self):
        """Карточка уже несёт чужое событие ⇒ метка ответа её НЕ перебивает.

        Решение «что владельцу сказали последним» живёт в одном поле; перебить его
        значило бы послать второе сообщение об одном событии (ADR-220).
        """
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "already",
                           extra=('acceptance_probe: "problem_absent:x"\n'
                                  'owner_notice: "not-accepted:no_probe"\n'))
            q.set_status(p, "done", closed_by="test", evidence="e")
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual("not-accepted:no_probe", fm.get("owner_notice"))

    def test_a_crash_before_the_outbox_leaves_the_answer_retryable(self):
        """Порядок записей: исходящие ПЕРЕД меткой.

        Упади мы между ними в обратном порядке — метка сказала бы «отдано», а записи
        не было бы НИКОГДА. Здесь падение происходит на самих исходящих, и карточка
        обязана остаться в `answer-pending`, то есть повторяемой.
        """
        from unittest.mock import patch
        from spa_core.owner_queue import intake
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "crash")
            ob = fresh_outbox(d)
            q.set_status(p, "done", closed_by="test", evidence="e")
            with patch.object(intake, "_outbox_put", side_effect=OSError("диск")):
                cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW)
            fm, _ = ac.split_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(ac.ANSWER_PENDING, fm.get("owner_notice"),
                             "метка «отдано» поставлена при пустых исходящих — ответ потерян")
            # Следующий прогон доносит его: доставка не менее одного раза.
            self.assertEqual([p.name], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))

    def test_the_cockpit_event_wins_when_a_card_is_due_for_both(self):
        """Карточка годна ОБОИМ звеньям ⇒ уходит «сделано и проверено», а не «вот ответ».

        Состояние конструируется руками: штатный путь его не рождает (метку не ставят
        при `verified_by_probe`), но порядок звеньев — контракт, и он пришпилен здесь.
        """
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = write_card(d, "both", status="done", source="cockpit",
                           extra=('verified_by_probe: "problem_absent:x"\n'
                                  f'owner_notice: "{ac.ANSWER_PENDING}"\n'))
            ob = fresh_outbox(d)
            self.assertEqual([p.name], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertEqual([f"{p.name}#{cl.EVENT_DONE}"],
                             [i["key"] for i in outbox_items(ob)])


class TheAntiStormIsHeldByTwoIndependentConditions(unittest.TestCase):
    """ВЫЖИВШИЕ МУТАНТЫ, оказавшиеся ЭКВИВАЛЕНТНЫМИ, а не дырами покрытия.

    Прибор назвал «дырой покрытия» снятие отсева по метке в :func:`sweep_notices` и
    снятие той же проверки внутри :func:`_ensure_answer_notice`. Замер сказал другое:
    условия РЕДУНДАНТНЫ. Снятие любого ОДНОГО наблюдаемого выхода не меняет — поэтому
    мутант и выжил, и это не дыра, а защита в два слоя. Снятие ОБОИХ отправляет
    владельцу историческую карточку.

    Дописывать тест под эквивалентного мутанта значило бы закрепить оптимизацию как
    поведение. Закрепляется само свойство: защита НЕСУЩАЯ, и ни одно из двух условий
    не является украшением.
    """

    def test_with_both_guards_gone_the_history_would_be_mailed(self):
        """Вариант БЕЗ обоих отсевов — ровно та правка, от которой защищает поле-граница."""
        from spa_core.owner_queue import intake

        def sweep_without_the_mark_guard(tracker_dir, outbox_path, now):
            """Опасный вариант: годна КАЖДАЯ закрытая просьба с записанным ответом."""
            out = []
            for card in sorted(Path(tracker_dir).glob("inbox-*.md")):
                fm, body = ac.split_frontmatter(card.read_text(encoding="utf-8"))
                if not (ac.is_owner_task(fm) and ac.is_closed(fm)):
                    continue
                if ac.answer_evidence(fm, body) is None:
                    continue
                intake._outbox_put(f"{card.name}#{ac.EVENT_ANSWER}", "x", now, outbox_path)
                out.append(card.name)
            return out

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            write_card(d, "hist", status="done", extra="carried_to: docs/STATE.md\n")
            ob = fresh_outbox(d)

            # как есть: оба отсева на месте — владельцу не уходит ничего
            self.assertEqual([], cl.sweep_notices(tracker_dir=d, outbox_path=ob, now=NOW))
            self.assertEqual([], outbox_items(ob))

            # без обоих: та же карточка уехала бы — значит защита несущая
            self.assertEqual(["inbox-hist.md"],
                             sweep_without_the_mark_guard(d, ob, NOW))


class TheProbeConditionsAreIndependentlyExercised(unittest.TestCase):
    """Две внутренние проверки пробы, которых не трогало ни одно порванное звено.

    Прибор назвал их выжившими, и это была правда: прежние контролы рвали контур так,
    что проба краснела РАНЬШЕ. Здесь каждая проверяется в одиночку.
    """

    PROBE = "owner_task_answer_reaches_the_channel"

    def run_probe(self):
        from spa_core.monitoring.card_acceptance import run_probe
        return run_probe(self.PROBE)

    def test_red_when_the_doors_verdict_does_not_change(self):
        """Ключ в очереди есть, а вердикт двери не сдвинулся ⇒ проводка НЕ измерена."""
        from unittest.mock import patch
        real = ac.delivery_verdict

        def always_true(path, **kw):
            return (True, "подменено") if "inbox-live" in str(path) else real(path, **kw)

        with patch.object(ac, "delivery_verdict", side_effect=always_true):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("не сменился", detail)

    def test_red_when_the_historical_card_is_called_delivered(self):
        """Анти-шторм не пробит, но историческая карточка объявлена доставленной."""
        from unittest.mock import patch
        real = ac.delivery_verdict

        def hist_true(path, **kw):
            return (True, "подменено") if "inbox-hist" in str(path) else real(path, **kw)

        with patch.object(ac, "delivery_verdict", side_effect=hist_true):
            verdict, detail = self.run_probe()
        self.assertEqual("not_satisfied", verdict)
        self.assertIn("молчание выдано за ответ", detail)
