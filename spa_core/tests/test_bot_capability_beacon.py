#!/usr/bin/env python3
"""Маячок бота объявляет ровно то, что умеет — и каждый отправитель спрашивает СВОЁ.

Находка цикла #194, карточка `inbox-mayachok-obyavlyaet-odnu-sposobnost-gejtit-dve`:
интерлок ADR-069 объявлял ОДНУ способность (`alert_actions`), а гейтил ДВЕ — кнопки
под тревогой (`act:aa:`) и кнопки под решением владельца (`act:od:`, ADR-075). Пока
оба обработчика живут в одном роутере и приезжают одним коммитом, вреда нет; разъедься
они (или появись третий вид кнопок) — отправитель бы этого не заметил, а нажатие ушло
бы в неизвестный `act:`-глагол, который ПЕРЕПИСЫВАЕТ сообщение панелью настроек, то
есть стирает сам вопрос владельцу.

Что здесь пиннится:

* **Маячок — ЗАМЕР, а не литерал.** Умение засчитывается по живому роутеру; исчез
  обработчик — умение исчезло из маячка (положительные контроли `Mutation*`).
* **Каждый спрашивает своё.** Тревога гейтится `alert_actions`, решение —
  `owner_decisions`. Проверка в ОБЕ стороны: чужой отметкой кнопку не открыть.
* **Третий вид кнопок не получает бесплатного пропуска** — это и есть суть находки.
* **Переходное послабление названо и ограничено:** решения принимают `alert_actions`
  как доказательство `owner_decisions` ТОЛЬКО потому, что работающий в проде
  долгожитель объявляет старый набор, а `act:od:` при этом обрабатывает. Послабление
  задаётся вызывающим поимённо, по умолчанию его нет (fail-CLOSED).

Время — ВХОД, а не окружение (правило `.claude/rules/deployment.md`, преференция №1):
маячок и проверка получают один и тот же момент, литеральных дат здесь нет.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.telegram.router import Router
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()

PROBLEM = "🚨 SPA — агент com.spa.daily_cycle не работает (exit 78)"

CARD = """---
title: Тестовое решение
status: needs-owner
---

## Что случилось и почему это важно

Кэш лежит без дела.

## Что от тебя нужно

* **Вариант 1 (рекомендую) — разместить освободившийся бюджет.** Текст.
* **Вариант 2 — оставить как есть.** Текст.

## Как понять, что готово

Кэш размещён.

## Что будет после

Агент исполнит выбор.
"""


def _beacon(path: Path, capabilities, now=FIXED_NOW) -> Path:
    path.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": now.isoformat(), "capabilities": list(capabilities),
    }))
    return path


class MeasuresTheLiveProcess(unittest.TestCase):
    """Маячок обязан говорить о РАБОТАЮЩЕМ коде, а не о том, что написано в исходнике."""

    def test_this_build_declares_both_capabilities(self):
        """Проводка: оба обработчика живы ⇒ оба умения объявлены."""
        measured = aa.measure_capabilities()
        self.assertIn(aa.CAPABILITY, measured)
        self.assertIn(aa.CAPABILITY_OWNER_DECISIONS, measured)

    def test_published_beacon_carries_the_measurement_not_a_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp) / "beacon.json"
            aa.publish_handler_beacon(now=FIXED_NOW, beacon_path=b)
            declared = json.loads(b.read_text())["capabilities"]
        self.assertEqual(sorted(declared), sorted(aa.measure_capabilities()))
        self.assertIn(aa.CAPABILITY_OWNER_DECISIONS, declared)

    def test_every_probed_capability_names_a_real_handler(self):
        """Зонд, промахнувшийся мимо имени метода, молча гасил бы умение навсегда."""
        for name, (_mod, _prefix, handler) in aa._CAPABILITY_PROBES.items():
            self.assertTrue(callable(getattr(Router, handler, None)),
                            "умение {}: у роутера нет метода {}".format(name, handler))


class MutationRemovesTheCapability(unittest.TestCase):
    """Положительные контроли: снятая проводка обязана КРАСНИТЬ, а не молчать."""

    def test_router_without_the_owner_decision_handler_stops_declaring_it(self):
        with mock.patch.object(Router, "handle_owner_decision", None, create=True):
            measured = aa.measure_capabilities()
        self.assertNotIn(aa.CAPABILITY_OWNER_DECISIONS, measured)
        self.assertIn(aa.CAPABILITY, measured, "соседнее умение задевать нельзя")

    def test_module_without_a_callback_prefix_stops_declaring_it(self):
        """Префикс без обработчика — нажатие не доедет; умения нет."""
        with mock.patch.object(od, "CALLBACK_PREFIX", ""):
            measured = aa.measure_capabilities()
        self.assertNotIn(aa.CAPABILITY_OWNER_DECISIONS, measured)

    def test_alert_handler_removal_also_shows_up(self):
        with mock.patch.object(Router, "handle_alert_action", None, create=True):
            measured = aa.measure_capabilities()
        self.assertNotIn(aa.CAPABILITY, measured)


class EachSenderAsksItsOwn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_decision_capability_alone_does_not_open_alert_buttons(self):
        """Обратная сторона: чужой отметкой кнопку под ТРЕВОГОЙ не открыть."""
        b = _beacon(self.dir / "od_only.json", [aa.CAPABILITY_OWNER_DECISIONS])
        self.assertFalse(aa.handler_available(now=FIXED_NOW, beacon_path=b))
        self.assertIsNone(aa.register_alert(PROBLEM, now=FIXED_NOW,
                                            state_path=self.dir / "alerts.json",
                                            beacon_path=b))

    def test_a_third_kind_of_button_gets_no_free_pass(self):
        """Суть находки: полный маячок НЕ доказывает умение, которого в нём нет."""
        b = _beacon(self.dir / "full.json",
                    [aa.CAPABILITY, aa.CAPABILITY_OWNER_DECISIONS])
        self.assertFalse(aa.handler_available(now=FIXED_NOW, beacon_path=b,
                                              capability="some_future_buttons"))

    def test_relaxation_is_never_the_default(self):
        b = _beacon(self.dir / "legacy.json", [aa.CAPABILITY])
        self.assertFalse(aa.handler_available(
            now=FIXED_NOW, beacon_path=b,
            capability=aa.CAPABILITY_OWNER_DECISIONS))
        self.assertTrue(aa.handler_available(
            now=FIXED_NOW, beacon_path=b,
            capability=aa.CAPABILITY_OWNER_DECISIONS,
            also_accept=(aa.CAPABILITY,)))

    def test_staleness_still_wins_over_any_capability(self):
        """Послабление не воскрешает мёртвого бота: протухший маячок — отказ."""
        b = _beacon(self.dir / "stale.json",
                    [aa.CAPABILITY, aa.CAPABILITY_OWNER_DECISIONS])
        later = FIXED_NOW + timedelta(hours=1)
        self.assertFalse(aa.handler_available(
            now=later, beacon_path=b,
            capability=aa.CAPABILITY_OWNER_DECISIONS,
            also_accept=(aa.CAPABILITY,)))


class DecisionButtonsSurviveTheTransition(unittest.TestCase):
    """`prepare` — единственная дверь, через которую решение уезжает владельцу."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _prepare(self, capabilities, now=FIXED_NOW):
        b = _beacon(self.dir / "b.json", capabilities)
        return od.prepare("Кэш лежит", CARD, "own-cash", now=now, beacon_path=b)

    def test_legacy_bot_still_gets_decision_buttons(self):
        """Окна без кнопок нет: прод-долгожитель объявляет старый набор и умеет act:od:."""
        self.assertIsNotNone(self._prepare([aa.CAPABILITY]).keyboard)

    def test_restarted_bot_gets_them_by_its_own_capability(self):
        prepared = self._prepare([aa.CAPABILITY_OWNER_DECISIONS])
        self.assertIsNotNone(prepared.keyboard)

    def test_no_relevant_capability_means_text_without_buttons(self):
        prepared = self._prepare(["menus"])
        self.assertIsNone(prepared.keyboard)
        self.assertTrue(prepared.text, "сам вопрос владельцу подавлять нельзя")

    def test_dead_beacon_means_text_without_buttons(self):
        prepared = self._prepare([aa.CAPABILITY, aa.CAPABILITY_OWNER_DECISIONS],
                                 now=FIXED_NOW)
        self.assertIsNotNone(prepared.keyboard)
        b = _beacon(self.dir / "b.json",
                    [aa.CAPABILITY, aa.CAPABILITY_OWNER_DECISIONS])
        late = od.prepare("Кэш лежит", CARD, "own-cash",
                          now=FIXED_NOW + timedelta(hours=1), beacon_path=b)
        self.assertIsNone(late.keyboard)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
