#!/usr/bin/env python3
"""Маячок бота объявляет способности ПОИМЁННО — по одной на каждый вид кнопок.

Находка цикла #194, закрыта #274. Каждый тест — положительный контроль конкретного способа
сломать владельцу канал, а не украшение.

**Что было.** Способность в маячке (`data/telegram_bot_capabilities.json`) была ОДНА —
``alert_actions``, — а сверялись с ней ДВОЕ: кнопки под тревогой (``act:aa:``) и кнопки под
решением владельца (``act:od:``, ``owner_decisions.prepare``). То есть кнопки решений
гейтились отметкой о способности, к решениям отношения не имеющей.

**Почему это не «мелочь оформления».** Ровно наш родовой класс: сторож честно отвечает на
СВОЙ вопрос, а читают его как ответ на нужный (`.claude/rules/deployment.md` — четыре вопроса,
четыре разных сторожа). Разъедутся обработчики или появится третий вид кнопок — отправитель
этого не заметит, а нажатие уйдёт в неизвестный ``act:``-глагол и ПЕРЕПИШЕТ сообщение панелью
настроек, то есть стерёт сам вопрос владельца.

**Почему починка переходная.** Живой бот в проде — долгожитель (`KeepAlive`) и объявляет только
``alert_actions``: потребуй мы от него сразу ``owner_decisions`` — кнопки решений исчезли бы до
его перезапуска, то есть починка сделала бы хуже прямо сейчас. Поэтому бот объявляет ОБЕ, а
отправитель решений принимает ``owner_decisions`` ИЛИ ``alert_actions``. Обе стороны «или»
закреплены тестами ниже — когда перезапущенный бот начнёт писать обе, снять вторую половину
можно будет, увидев ровно один красный тест, а не угадывая.

Время — ВХОД, а не окружение: все отметки строятся от одного якоря, литеральных дат нет.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

NOW = now_utc()

CARD_WITH_OPTIONS = """---
trackerStatus:
  type: owner-decision
title: "Куда девать освободившийся бюджет"
status: needs-owner
---

## Что от тебя нужно

* **Вариант 1 (рекомендую) — перезаполнять бюджет.** Текст.
* **Вариант 2 — оставить как есть.** Текст.
"""


def _beacon(tmp_path: Path, caps, *, age_s: float = 10.0, name: str = "beacon.json") -> Path:
    """Маячок с ЗАДАННЫМ набором способностей и заданным возрастом."""
    p = tmp_path / name
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": (NOW - timedelta(seconds=age_s)).isoformat(), "pid": 1,
        "capabilities": list(caps),
    }), encoding="utf-8")
    return p


# ── что объявляет сам бот ────────────────────────────────────────────────────


def test_bot_declares_a_capability_for_each_kind_of_button(tmp_path):
    """Положительный контроль находки #194: маячок обязан называть ОБА обработчика.

    Одна отметка за двоих — это утверждение, которого никто не проверял: она правдива про
    кнопки тревог и МОЛЧА распространялась на кнопки решений.
    """
    p = tmp_path / "beacon.json"
    aa.publish_handler_beacon(now=NOW, beacon_path=p)
    caps = json.loads(p.read_text(encoding="utf-8"))["capabilities"]
    assert caps == list(aa.CAPABILITIES)
    assert aa.CAPABILITY in caps and aa.CAPABILITY_OWNER_DECISIONS in caps


# ── каждый сторож отвечает на СВОЙ вопрос ────────────────────────────────────


def test_alert_buttons_do_not_accept_the_decisions_capability(tmp_path):
    """Обратная сторона той же ошибки: чужая отметка не годится и в другую сторону.

    Бот, умеющий только решения, кнопок под ТРЕВОГОЙ обработать не обязан. Принять его
    отметку значило бы повторить дефект зеркально.
    """
    b = _beacon(tmp_path, [aa.CAPABILITY_OWNER_DECISIONS])
    assert aa.handler_available(now=NOW, beacon_path=b) is False


def test_alert_buttons_accept_their_own_capability(tmp_path):
    """Контроль в обратную сторону: своя отметка — годится."""
    b = _beacon(tmp_path, [aa.CAPABILITY])
    assert aa.handler_available(now=NOW, beacon_path=b) is True


def test_decision_buttons_appear_on_the_new_own_capability_alone(tmp_path):
    """Бот объявляет ТОЛЬКО ``owner_decisions`` ⇒ кнопки решений есть.

    Именно этого прежний код не умел: он требовал ``alert_actions`` и отказал бы боту,
    который обработать нажатие по решению как раз способен.
    """
    b = _beacon(tmp_path, [aa.CAPABILITY_OWNER_DECISIONS])
    prep = od.prepare("Бюджет", CARD_WITH_OPTIONS, "own-b", now=NOW, beacon_path=b)
    assert prep.options, "варианты обязаны разобраться — проверяем именно интерлок"
    assert prep.keyboard is not None


def test_decision_buttons_survive_a_bot_that_only_knows_the_old_capability(tmp_path):
    """Переходный порядок: работающий в проде бот пишет только ``alert_actions``.

    Это и есть причина, по которой прямолинейная починка была бы ХУЖЕ: потребуй мы новую
    отметку немедленно — владелец остался бы без кнопок решений до перезапуска долгожителя.
    """
    b = _beacon(tmp_path, [aa.CAPABILITY])
    prep = od.prepare("Бюджет", CARD_WITH_OPTIONS, "own-b", now=NOW, beacon_path=b)
    assert prep.keyboard is not None
    assert aa.CAPABILITY in aa.OWNER_DECISIONS_ACCEPTED, "вторая половина «или» ещё нужна"


# ── fail-CLOSED не ослаблен ни на строку ─────────────────────────────────────


def test_a_stale_beacon_still_removes_every_button(tmp_path):
    """Протухший маячок гасит кнопки ОБОИХ видов: расширили набор отметок, не сроки жизни."""
    b = _beacon(tmp_path, list(aa.CAPABILITIES), age_s=aa.BEACON_MAX_AGE_S + 60)
    assert aa.handler_available(now=NOW, beacon_path=b) is False
    prep = od.prepare("Бюджет", CARD_WITH_OPTIONS, "own-b", now=NOW, beacon_path=b)
    assert prep.keyboard is None
    assert "Кнопки сейчас недоступны" in prep.text  # текст и клавиатура говорят одно


def test_an_unrelated_capability_is_not_enough_for_either_kind(tmp_path):
    """Маячок умеет что-то третье («menus») ⇒ ни тревожных кнопок, ни кнопок решений."""
    b = _beacon(tmp_path, ["menus"])
    assert aa.handler_available(now=NOW, beacon_path=b) is False
    assert aa.handler_available(now=NOW, beacon_path=b,
                                accepted=aa.OWNER_DECISIONS_ACCEPTED) is False
    prep = od.prepare("Бюджет", CARD_WITH_OPTIONS, "own-b", now=NOW, beacon_path=b)
    assert prep.keyboard is None


def test_a_missing_beacon_is_not_a_yes(tmp_path):
    """Измерить не смогли ⇒ кнопок нет. «Не знаю» никогда не значит «можно»."""
    missing = tmp_path / "nope.json"
    assert aa.handler_available(now=NOW, beacon_path=missing) is False
    assert aa.handler_available(now=NOW, beacon_path=missing,
                                accepted=aa.OWNER_DECISIONS_ACCEPTED) is False
