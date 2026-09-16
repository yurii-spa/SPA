#!/usr/bin/env python3
"""Вопрос владельцу, отправленный пока бот перезапускается, уезжает С КНОПКАМИ (ADR-400).

Жалоба владельца 16.09 — четвёртая на один и тот же текст («⚠️ Кнопки сейчас
недоступны — бот не подтвердил, что готов их обработать»; до этого 10.08, 14.08,
22.08). Под ним стояли три безупречно разобранных варианта: разбор был ни при чём,
кнопки снимал интерлок ADR-069 — маячок бота старше 300 с. Бот перезапускается ~2 раза
в сутки (сентинел ADR-117 после каждой доставки кода, кикстарты `telegram_health` и
`self_heal`), и каждое окно длиннее пяти минут снимало кнопки с любого вопроса,
отправленного в это окно. Нажатие же, сделанное пока бот лежит, Telegram держит до
24 ч и отдаёт первому `getUpdates` — то есть кнопка обрабатывается ПОСЛЕ подъёма.

Здесь закреплён ИСХОД, а не константа: тот же путь, которым уезжает решение
(`owner_decisions.prepare` → `alert_actions.handler_available`), при маячке возрастом
в час даёт клавиатуру и текст «Нажми кнопку», а при маячке возрастом в сутки —
честный текст без кнопок, как и прежде. Обе стороны, чтобы порог нельзя было
молча сдвинуть ни в ноль, ни в бесконечность.

Время — вход, а не окружение: возраст маячка задаётся относительно ``FIXED_NOW``.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()

CARD = """---
title: "Сайт: правка — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
---

## Что случилось и почему это важно

Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated
область. Такое не уезжает в live само — только с твоего одобрения.

## Что от тебя нужно

Посмотри изменение и выбери:

1. **Одобрить** — правка уезжает в live как есть.
2. **Отклонить (рекомендую)** — оркестратор не трогает эту область.
3. **Отложить** — оставить карточку открытой и вернуться к ней позже.

## Как понять, что готово

Ты нажал кнопку в Телеграме.

## Что будет после

Одобришь → изменение уезжает в live.
"""

PROBLEM = "🚨 SPA — агент com.spa.daily_cycle не работает (exit 78)"


def _beacon(tmp_path, *, age):
    p = tmp_path / "telegram_bot_capabilities.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": (FIXED_NOW - age).isoformat(),
        "capabilities": [aa.CAPABILITY, aa.CAPABILITY_OWNER_DECISIONS],
    }), encoding="utf-8")
    return p


@pytest.mark.parametrize("age", [timedelta(minutes=6), timedelta(hours=1),
                                 timedelta(hours=5)])
def test_owner_question_sent_during_a_restart_window_carries_buttons(tmp_path, age):
    """Сам вопрос владельца от 16.09, при маячке старше прежних 300 с."""
    b = _beacon(tmp_path, age=age)
    prep = od.prepare("Сайт: правка — нужно решение", CARD, "owner-decision-sait-pravka",
                      now=FIXED_NOW, beacon_path=b)
    assert len(prep.options) == 3, "разбор вариантов здесь ни при чём"
    assert prep.keyboard is not None, "маячок возрастом {} снял кнопки".format(age)
    assert "Нажми кнопку" in prep.text
    assert "Кнопки сейчас недоступны" not in prep.text


def test_a_bot_that_has_been_silent_for_a_day_still_gets_the_honest_text(tmp_path):
    """Обратный контроль: порог не бесконечность. Сутки без маячка — бота нет."""
    b = _beacon(tmp_path, age=timedelta(hours=24))
    prep = od.prepare("Сайт: правка — нужно решение", CARD, "owner-decision-sait-pravka",
                      now=FIXED_NOW, beacon_path=b)
    assert len(prep.options) == 3
    assert prep.keyboard is None
    assert "Кнопки сейчас недоступны" in prep.text
    assert "РЕПЛАЕМ" in prep.text, "путь ответа без кнопок обязан быть назван"


def test_the_push_journal_records_buttons_true_for_a_restart_window(tmp_path):
    """Журнал отправок — то, по чему судят сторожа: `buttons: true`, чинить нечего."""
    b = _beacon(tmp_path, age=timedelta(hours=1))
    card = tmp_path / "owner-decision-sait-pravka.md"
    card.write_text(CARD, encoding="utf-8")
    state = tmp_path / "telegram_owner_decisions.json"
    prep = od.register_push(card, "Сайт: правка — нужно решение", CARD, now=FIXED_NOW,
                            state_path=state, beacon_path=b)
    rec = json.loads(state.read_text(encoding="utf-8"))["pushes"][-1]
    assert rec["pid"] == prep.pid
    assert rec["buttons"] is True


def test_alert_buttons_share_the_same_rule(tmp_path):
    """Кнопки под тревогой идут тем же гейтом — окно перезапуска и их не снимает."""
    b = _beacon(tmp_path, age=timedelta(hours=1))
    got = aa.register_alert(PROBLEM, now=FIXED_NOW, state_path=tmp_path / "alerts.json",
                            beacon_path=b)
    assert got is not None
    _alert_id, keyboard = got
    assert keyboard.get("inline_keyboard")
