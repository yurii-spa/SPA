"""Карточку моста закрыли РУКАМИ — запись состояния обязана перестать врать.

Авария, воспроизведённая здесь дословно (карточка
`inbox-kartochku-mosta-zakryli-rukami-zhivaya-n`, замер 17.08). Мост закрывает
карточку только сам (`close_card`), и из этого молча следовало, что иначе она
закрыться не может. Может: 16.08 три находки петли схлопнули в корневые карточки
РУКАМИ. После этого запись состояния остаётся `carded` НАВСЕГДА —
`_reconcile_with_tracker` умеет только ВОССТАНАВЛИВАТЬ запись по открытой карточке,
а `needs_card` требует `observed`. Итог: находка живёт в отчёте источника каждый
такт, карточки под неё нет, новая не родится НИКОГДА, а `open_cards` докладывает
работу, которой не существует. Направление ошибки — в сторону ТИШИНЫ (класс
fail-OPEN #29), и это худший из возможных: отчёт выглядит рабочим.

**Что здесь закреплено и что НАМЕРЕННО не закреплено.** Правильное поведение после
ручного закрытия — ПОЛИТИКА (принять «человек взял на себя» / сбросить гистерезис /
гибрид со сроком), и выбор за владельцем. Поэтому тесты держат только ту половину,
которая верна при ЛЮБОМ прочтении: механизм обязан НАЗЫВАТЬ такую запись и не
считать её открытой карточкой. Отсутствие воскрешения тоже закреплено — но как
СЕГОДНЯШНЕЕ поведение, названное именем (`test_bridge_does_not_decide_the_policy`),
чтобы будущий выбор варианта 2 или 3 покрасил тест и был осознанным, а не тихим.

Обратная сторона проверяется наравне с прямой: открытая карточка по-прежнему
считается открытой (иначе «починка» просто обнулила бы счётчик), а карточка, чью
судьбу измерить НЕЛЬЗЯ, продолжает считаться открытой по fail-CLOSED.

Время — вход: `now` инъектируется во все прогоны, отметки источников считаются от
той же константы. Карточные операции инъектируются (`FakeQueue`) — тест НИКОГДА не
трогает живой tracker.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import findings_bridge as fb
from spa_core.tests.test_findings_bridge import FakeQueue

NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются


class _BridgeCase(unittest.TestCase):
    """Общая песочница: три свежих источника, поддельная очередь, инъекция часов."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        os.makedirs(os.path.join(self.root, "data"))
        self.tracker = os.path.join(self.root, "tracker")
        os.makedirs(self.tracker)
        self.q = FakeQueue(self.tracker)

    def tearDown(self):
        self.td.cleanup()

    # -- фикстуры ------------------------------------------------------------

    def sources(self, findings, *, at: dt.datetime | None = None) -> None:
        """Все три источника СВЕЖИ; находки кладём в сторожа архитектуры."""
        stamp = (at or NOW).isoformat()
        self._write("architecture_conformance",
                    {"generated_at": stamp, "findings": list(findings), "unchecked": []})
        self._write("house_view_gap", {"generated_at": stamp, "gaps": [], "unchecked": []})
        self._write("loop_retro", {"generated_at": stamp, "findings": [], "unchecked": []})

    def _write(self, name: str, payload: dict) -> None:
        with open(os.path.join(self.root, fb.SOURCES[name]), "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def run_bridge(self, *, at: dt.datetime) -> dict:
        return fb.run_bridge(
            self.root, now=at, create=self.q.create, close=self.q._close,
            notify=self.q.notify, retract=self.q.retract,
            deliver=lambda *a, **k: {"status": "SKIP"},
            deliver_answers=lambda **k: {"status": "SKIP"})

    def state(self) -> dict:
        with open(os.path.join(self.root, fb.STATE_REL), encoding="utf-8") as f:
            return json.load(f)["findings"]

    def critical(self, key: str = "gap:opportunity_unnamed:fluid_fusdc") -> dict:
        return {"key": key, "severity": "CRITICAL", "message": "атрибуция кэша молчит"}

    def born_card(self, finding: dict) -> str:
        """Прогнать мост до рождения карточки и вернуть путь к ней."""
        self.sources([finding])
        report = self.run_bridge(at=NOW)
        self.assertEqual(len(report["created"]), 1, "карточка обязана родиться")
        return report["created"][0]["card"]

    @staticmethod
    def close_by_hand(card: str) -> None:
        """Ровно то, что делает человек: правит статус карточки мимо моста."""
        with open(card, encoding="utf-8") as f:
            text = f.read()
        for old in ("status: needs-owner", "status: new"):
            text = text.replace(old, "status: done")
        with open(card, "w", encoding="utf-8") as f:
            f.write(text)


# ── воспроизведение аварии ───────────────────────────────────────────────────

class ManuallyClosedCardIsNamed(_BridgeCase):
    """Прогон из карточки, строка в строку: раньше `open_cards: 1` и ни слова в отчёте."""

    def test_reproduces_the_measurement_from_the_card(self):
        f = self.critical()
        card = self.born_card(f)
        self.close_by_hand(card)
        self.assertEqual(fb.card_status(card), "done")

        for i in (1, 2, 3):
            r = self.run_bridge(at=NOW + dt.timedelta(hours=6 * i))
            self.assertEqual(r["created"], [], f"прогон {i}: новых карточек быть не должно")
            # ГЛАВНОЕ: счётчик больше не докладывает работу, которой нет.
            self.assertEqual(r["open_cards"], 0,
                             f"прогон {i}: открытой карточки не существует")
            named = r["cards_closed_outside_bridge"]
            self.assertEqual([x["key"] for x in named], [f["key"]],
                             f"прогон {i}: запись обязана быть НАЗВАНА, а не растворена")
            self.assertTrue(named[0]["finding_still_reported"],
                            "находка всё ещё в отчёте источника — это и есть суть аварии")
            self.assertIn("мимо моста", named[0]["reason"])

    def test_deleted_card_file_counts_as_closed_by_hand(self):
        """Схлопнуть можно и удалением файла — отсутствие файла тоже измеримо."""
        f = self.critical()
        card = self.born_card(f)
        os.remove(card)
        r = self.run_bridge(at=NOW + dt.timedelta(hours=6))
        self.assertEqual(r["open_cards"], 0)
        self.assertEqual([x["key"] for x in r["cards_closed_outside_bridge"]], [f["key"]])
        self.assertIn("нет на диске", r["cards_closed_outside_bridge"][0]["reason"])

    def test_state_entry_carries_the_reason_not_only_the_report(self):
        """Причина живёт и в состоянии — как `closing_held_reason` у гарантии 1."""
        f = self.critical()
        self.close_by_hand(self.born_card(f))
        self.run_bridge(at=NOW + dt.timedelta(hours=6))
        entry = self.state()[f["key"]]
        self.assertIn("card_gone_at", entry)
        self.assertIn("мимо моста", entry["card_gone_reason"])

    def test_card_gone_at_marks_the_FIRST_sighting_not_the_latest_run(self):
        """Отметка не переписывается каждым прогоном: иначе «сколько уже висит» не узнать."""
        f = self.critical()
        self.close_by_hand(self.born_card(f))
        first = NOW + dt.timedelta(hours=6)
        self.run_bridge(at=first)
        self.run_bridge(at=NOW + dt.timedelta(hours=48))
        self.assertEqual(self.state()[f["key"]]["card_gone_at"], first.isoformat())


# ── обратная сторона: «починка» не имеет права обнулять счётчик ──────────────

class OpenCardStaysOpen(_BridgeCase):
    """Без этих тестов ту же зелень дал бы `open_cards = 0` всегда."""

    def test_untouched_card_is_still_counted_and_not_named(self):
        f = self.critical()
        self.born_card(f)
        r = self.run_bridge(at=NOW + dt.timedelta(hours=6))
        self.assertEqual(r["open_cards"], 1)
        self.assertEqual(r["cards_closed_outside_bridge"], [])

    def test_card_taken_into_work_is_still_open(self):
        """`in-progress` — открытый статус: работа идёт, карточка жива."""
        f = self.critical()
        card = self.born_card(f)
        with open(card, encoding="utf-8") as fh:
            text = fh.read().replace("status: needs-owner", "status: in-progress")
        with open(card, "w", encoding="utf-8") as fh:
            fh.write(text)
        r = self.run_bridge(at=NOW + dt.timedelta(hours=6))
        self.assertEqual(r["open_cards"], 1)
        self.assertEqual(r["cards_closed_outside_bridge"], [])

    def test_card_closed_BY_THE_BRIDGE_is_not_named_twice(self):
        """Штатное закрытие — не авария: запись уходит в `closed`, раздел пуст."""
        f = self.critical()
        self.born_card(f)
        self.sources([])                      # находка ПОЧИНЕНА, источник свеж
        r = self.run_bridge(at=NOW + dt.timedelta(hours=6))
        self.assertEqual(len(r["closed"]), 1, "мост обязан закрыть её сам")
        self.assertEqual(r["cards_closed_outside_bridge"], [])
        self.assertEqual(r["open_cards"], 0)
        self.assertEqual(self.state()[f["key"]]["status"], "closed")


# ── fail-CLOSED: «не измерено» ≠ «закрыта» ───────────────────────────────────

class UnmeasurableCardStaysCounted(_BridgeCase):
    def test_unparsable_frontmatter_is_named_separately_and_still_counted(self):
        """Нечитаемая карточка не смеет ТИХО занизить счётчик — это вторая тихая неправда."""
        f = self.critical()
        card = self.born_card(f)
        with open(card, "w", encoding="utf-8") as fh:
            fh.write("совсем не карточка, ограды нет\n")
        r = self.run_bridge(at=NOW + dt.timedelta(hours=6))
        self.assertEqual(r["cards_closed_outside_bridge"], [],
                         "нечитаемое не объявляется закрытым")
        self.assertEqual([x["key"] for x in r["cards_liveness_unmeasured"]], [f["key"]])
        self.assertEqual(r["open_cards"], 1, "по fail-CLOSED считаем открытой")
        self.assertNotIn("card_gone_at", self.state()[f["key"]])


# ── граница: что мост НЕ решает ──────────────────────────────────────────────

class PolicyIsNotDecidedHere(_BridgeCase):
    def test_bridge_does_not_decide_the_policy(self):
        """Сегодняшнее поведение названо ИМЕНЕМ, чтобы его смена была осознанной.

        Варианты 2 («сброс гистерезиса») и 3 («гибрид со сроком») из карточки
        воскрешают карточку — и покрасят ИМЕННО этот тест. Так и задумано: выбор
        владельца обязан быть виден как изменение теста, а не проехать молча.
        """
        f = self.critical()
        self.close_by_hand(self.born_card(f))
        for i in range(1, 6):                 # заведомо больше REQUIRED_SIGHTINGS
            r = self.run_bridge(at=NOW + dt.timedelta(hours=6 * i))
            self.assertEqual(r["created"], [], "мост не воскрешает схлопнутую человеком карточку")
        self.assertEqual(self.state()[f["key"]]["status"], "carded",
                         "статус записи не двигается: это решение владельца, не моста")


# ── сам вердикт, поштучно ────────────────────────────────────────────────────

class CardLivenessVerdicts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.td.cleanup()

    def _card(self, status_line: str) -> str:
        path = os.path.join(self.td.name, "c.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"---\ntrackerStatus:\n  type: inbox\n{status_line}\n---\nтело\n")
        return path

    def test_open_statuses(self):
        for st in fb.OPEN_CARD_STATUSES:
            self.assertEqual(fb.card_liveness(self._card(f"status: {st}"))[0], "open", st)

    def test_closed_statuses(self):
        for st in ("done", "ingested", "owner-done"):
            self.assertEqual(fb.card_liveness(self._card(f"status: {st}"))[0], "gone", st)

    def test_missing_file(self):
        verdict, reason = fb.card_liveness(os.path.join(self.td.name, "нет-такой.md"))
        self.assertEqual(verdict, "gone")
        self.assertIn("нет на диске", reason)

    def test_no_path_at_all_is_unmeasured(self):
        self.assertEqual(fb.card_liveness(None)[0], "unmeasured")

    def test_status_absent_is_unmeasured_not_gone(self):
        self.assertEqual(fb.card_liveness(self._card("source: nimbalyst"))[0], "unmeasured")


if __name__ == "__main__":
    unittest.main()
