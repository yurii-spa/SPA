"""Точный повтор вопроса владельцу ловится ДЕТЕРМИНИРОВАННО (цикл #446).

Каждый положительный контроль здесь — авария 31.08.2026, а не выдуманный вход:
интейк за вечер выпустил три карточки-уточнения, и ДВЕ из них несли байт-в-байт
тексты, уже ставшие вопросами 12.08. По одной владелец нажал «Принято — беру в
работу» — на работе, доставленной 07.08 (ADR-070 п.11, циклы #153/#156).

Тексты ниже — дословно из тех карточек (`owner-decision-utochnenie-po-zametke-
adr-070-11-chestny` / `-13-trevogu` и их близнецов `-2`). Дата в них ЧАСТЬ ПРЕДМЕТА
(исторический инцидент), календарь на вердикт не влияет.
"""
# FROZEN-DATE-OK: тексты и даты — предмет инцидента 2026-08-31, не окружение теста

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.owner_queue import queue as _queue
from spa_core.owner_queue.history_check import (
    SOURCE_TEXT_CLOSE,
    SOURCE_TEXT_OPEN,
    exact_prior_ask,
    history_check,
    recorded_source_text,
)
from spa_core.owner_queue.queue import OWNER_ONLY_STATUSES, create_card, set_status

#: Дословный текст из аварии 31.08 (карточка `…adr-070-13-trevogu`).
REAL_TEXT_13 = "По двум чистым снимкам подряд (решение владельца 2026-08-07, ADR-070 п.13)"
#: Дословный текст из аварии 31.08 (карточка `…adr-070-11-chestny`).
REAL_TEXT_11 = "Не ушло — ошибка; agent_health видит (решение владельца 2026-08-07, ADR-070 п.11)"


def _clarification_body(source_text: str, partial_note: str = "") -> str:
    """Тело карточки-уточнения РОВНО той формы, которую строит интейк."""
    partial_body = (f"\n\n> ⚠️ Проверка истории: похоже на уже существующее — {partial_note}\n"
                    f"> Проверь: это то же самое или новое?\n" if partial_note else "")
    return (f"## Что случилось и почему это важно\n"
            f"Пришло сообщение, непонятно — вопрос это или задача.\n\n"
            f"{SOURCE_TEXT_OPEN}{source_text}{SOURCE_TEXT_CLOSE}{partial_body}\n\n"
            f"## Что от тебя нужно\nУточни.\n\n"
            f"## Как понять, что готово\nТы уточнил.\n\n"
            f"## Что будет после\nОбработаю по твоему ответу.")


class _ClarificationCase(unittest.TestCase):
    """Общая песочница трекера. Имя не по маске `*Test` — pytest её не собирает,
    и набор не удваивается наследованием."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tracker = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _ask(self, source_text, *, title, status, partial_note=""):
        """Завести карточку-уточнение и привести её в нужный статус."""
        p = create_card("owner-decision", title,
                        _clarification_body(source_text, partial_note),
                        status="needs-owner", source="intake", tracker_dir=self.tracker)
        if status in OWNER_ONLY_STATUSES:
            # `owner-accepted` — слова ВЛАДЕЛЬЦА: `set_status` верно отказывает агенту
            # (инв. #14, ADR-146). Фикстура играет владельца и пишет строку сама —
            # ослаблять отказ ради теста нельзя, он и есть проверяемое свойство.
            txt = p.read_text(encoding="utf-8")
            p.write_text(txt.replace("status: needs-owner", f"status: {status}", 1),
                         encoding="utf-8")
        elif status != "needs-owner":
            set_status(p, status, closed_by="test", evidence="положительный контроль #446")
        return p


class ExactPriorAskTest(_ClarificationCase):
    # ── положительные контроли: ровно авария 31.08 ───────────────────────────

    def test_closed_prior_ask_is_found_verbatim(self):
        """13.п: текст 12.08 закрыт `done` — 31.08 он пришёл снова и НИКТО не сказал."""
        self._ask(REAL_TEXT_13, title="ADR-070.13: тревогу core-agent-down гасит agent_health",
                  status="done")
        hit = exact_prior_ask(REAL_TEXT_13, tracker_dir=self.tracker)
        self.assertIsNotNone(hit, "точный повтор закрытого вопроса обязан быть НАЙДЕН")
        self.assertEqual(hit["status"], "done")
        self.assertIn("trevogu", hit["card_id"])

    def test_the_ask_that_cost_an_owner_decision(self):
        """11.п: по этому повтору владелец нажал «Принято» на работе от 07.08."""
        self._ask(REAL_TEXT_11, title="ADR-070.11: честный exit digest-обёртки", status="done")
        hit = exact_prior_ask(REAL_TEXT_11, tracker_dir=self.tracker)
        self.assertIsNotNone(hit, "повтор, потративший решение владельца, обязан быть найден")
        self.assertIn("chestny", hit["card_id"])

    def test_prior_ask_found_even_when_the_judge_is_unreachable(self):
        """Судья лежит ⇒ fail-safe даёт NEW; детерминированная сверка обязана работать
        и в этом состоянии — иначе повтор уезжает владельцу при ЛЮБОМ исходе."""
        self._ask(REAL_TEXT_13, title="ADR-070.13", status="done")
        # exact_prior_ask не зовёт claude вовсе — доказываем это отсутствием сети/бинаря:
        # функция не принимает и не читает _CLAUDE, поэтому вердикт от него не зависит.
        self.assertIsNotNone(exact_prior_ask(REAL_TEXT_13, tracker_dir=self.tracker))

    def test_prior_ask_survives_a_partial_note_in_the_older_card(self):
        """У реального близнеца `-11-chestny-2` в теле СТОИТ пометка истории — граница
        исходного текста обязана проходить по разделу, а не по первой кавычке."""
        self._ask(REAL_TEXT_11, title="ADR-070.11", status="done",
                  partial_note="Похоже на закрытую карточку agent-morning-digest-... (done)")
        self.assertIsNotNone(exact_prior_ask(REAL_TEXT_11, tracker_dir=self.tracker))

    def test_multiline_telegram_task_text_round_trips(self):
        """Реальные тексты интейка многострочные («## Задание (из Telegram)» …)."""
        text = ("## Задание (из Telegram)\n\nТак почини\n\n---\n"
                "_Оркестратор: классифицируй (задача/идея/непонятно)._")
        self._ask(text, title="Так почини", status="done")
        hit = exact_prior_ask(text, tracker_dir=self.tracker)
        self.assertIsNotNone(hit, "многострочный текст обязан сверяться целиком")

    # ── обратные контроли: проверка не имеет права звонить на верном ─────────

    def test_open_prior_ask_is_deliberately_silent(self):
        """Живой вопрос — НЕ наш случай: его держит идемпотентность `create_card`, а
        пометка изменила бы тело и сломала бы сверку тел, на которой та стоит."""
        self._ask(REAL_TEXT_13, title="ADR-070.13", status="needs-owner")
        self.assertIsNone(exact_prior_ask(REAL_TEXT_13, tracker_dir=self.tracker))

    def test_owner_accepted_counts_as_open(self):
        """`owner-accepted` открыт (#350): владелец согласился, сделано ещё ничего."""
        self._ask(REAL_TEXT_11, title="ADR-070.11", status="owner-accepted")
        self.assertIsNone(exact_prior_ask(REAL_TEXT_11, tracker_dir=self.tracker))

    def test_different_text_is_not_a_repeat(self):
        self._ask(REAL_TEXT_13, title="ADR-070.13", status="done")
        self.assertIsNone(exact_prior_ask(REAL_TEXT_11, tracker_dir=self.tracker))

    def test_near_miss_is_not_a_repeat(self):
        """Сверка ТОЧНАЯ: «почти тот же» текст — это суждение, и оно не здесь."""
        self._ask(REAL_TEXT_13, title="ADR-070.13", status="done")
        self.assertIsNone(exact_prior_ask(REAL_TEXT_13 + " и ещё вот это",
                                          tracker_dir=self.tracker))

    def test_non_intake_card_is_not_a_prior_ask(self):
        """Обычная карточка, процитировавшая текст, вопросом владельцу не была."""
        create_card("owner-decision", "Обычный вопрос", _clarification_body(REAL_TEXT_13),
                    status="needs-owner", source="findings-bridge", tracker_dir=self.tracker)
        set_status(self.tracker / "owner-decision-obychnyi-vopros.md", "done",
                   closed_by="test", evidence="обратный контроль")
        self.assertIsNone(exact_prior_ask(REAL_TEXT_13, tracker_dir=self.tracker))

    def test_empty_text_never_matches(self):
        self._ask(REAL_TEXT_13, title="ADR-070.13", status="done")
        self.assertIsNone(exact_prior_ask("", tracker_dir=self.tracker))
        self.assertIsNone(exact_prior_ask("   ", tracker_dir=self.tracker))

    def test_missing_tracker_dir_is_not_a_match(self):
        """Сбой чтения не имеет права ПОДАВИТЬ карточку — в сомнении повтора нет."""
        self.assertIsNone(exact_prior_ask(REAL_TEXT_13,
                                          tracker_dir=self.tracker / "нет-такого"))


class RecordedSourceTextTest(unittest.TestCase):
    def test_reads_back_what_intake_wrote(self):
        self.assertEqual(recorded_source_text(_clarification_body(REAL_TEXT_11)), REAL_TEXT_11)

    def test_text_containing_the_closing_quote_is_not_truncated(self):
        """Граница — раздел, а не первая «»: иначе цитата внутри текста резала бы его."""
        tricky = "владелец написал «сделай» и добавил ещё строку"
        self.assertEqual(recorded_source_text(_clarification_body(tricky)), tricky)

    def test_foreign_body_has_no_recorded_text(self):
        self.assertIsNone(recorded_source_text("## Что случилось\nпросто текст без маркера"))

    def test_empty_body(self):
        self.assertIsNone(recorded_source_text(""))
        self.assertIsNone(recorded_source_text(None))


if __name__ == "__main__":
    unittest.main()


class HistoryCheckWiringTest(_ClarificationCase):
    """У проверки должен быть ВЫЗЫВАЮЩИЙ. Сама функция может быть безупречна и при
    этом не звучать нигде — один снятый вызов оставил бы весь набор выше ЗЕЛЁНЫМ.

    Судья здесь заведомо недостижим (`SPA_CLAUDE_BIN` в никуда), поэтому вердикт
    `PARTIAL` может прийти ТОЛЬКО от детерминированной ветки: без неё fail-safe
    даёт `NEW` — ровно то состояние, в котором повтор и уезжал владельцу.
    """

    def _run_history_check(self, text):
        env = dict(os.environ, SPA_CLAUDE_BIN=str(self.tracker / "нет-такого-claude"))
        with mock.patch.object(_queue, "TRACKER_DIR", self.tracker), \
                mock.patch.dict(os.environ, env, clear=False):
            return history_check(text, timeout=5)

    def test_history_check_calls_the_deterministic_repeat_check(self):
        self._ask(REAL_TEXT_13, status="done",
                  title="ADR-070.13: тревогу core-agent-down гасит agent_health")
        res = self._run_history_check(REAL_TEXT_13)
        self.assertEqual(res["verdict"], "PARTIAL")
        self.assertIn("trevogu", res.get("prior_ask", {}).get("card_id", ""))
        self.assertIn("уже становился вопросом", res["response"])

    def test_without_a_prior_ask_the_unreachable_judge_still_fails_safe(self):
        """Обратный контроль: без повтора остаётся прежнее поведение (NEW)."""
        res = self._run_history_check(REAL_TEXT_13)
        self.assertEqual(res["verdict"], "NEW")
        self.assertNotIn("prior_ask", res)

    def test_partial_from_a_repeat_does_not_suppress_the_card(self):
        """PARTIAL — это «создать и пометить». Подавляют только DONE/IN_PROGRESS/REJECTED:
        повтор не имеет права ГЛОТАТЬ задание владельца."""
        from spa_core.owner_queue.history_check import is_duplicate

        self._ask(REAL_TEXT_11, title="ADR-070.11", status="done")
        res = self._run_history_check(REAL_TEXT_11)
        self.assertFalse(is_duplicate(res["verdict"]))
