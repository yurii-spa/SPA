#!/usr/bin/env python3
"""Решение, уехавшее БЕЗ кнопок, чинится само, когда бот оживает.

Каждый тест здесь — положительный контроль реальной аварии 10.08.2026, а не украшение.

**Что случилось.** Владелец написал в Телеграм: *«присылать не просто "нужно твоё
решение", а и кнопки с вариантами, чтобы я нажал, ты забрал и взял в работу. Сейчас
приходит вот так и это не удобно»* — и приложил сообщение с припиской «⚠️ Кнопки сейчас
недоступны — бот не подтвердил, что готов их обработать».

**Почему так вышло.** Интерлок ADR-069 честен, но односторонен: маячок бота протух ⇒
кнопок нет. Замер: четыре открытых решения (в т.ч. «прод остановлен») ушли владельцу в
04:13:56Z, а бот поднялся в 04:22:19Z — на восемь минут позже. Сообщения уже в чате,
второго шанса им никто не давал: кнопок у этих четырёх не будет НИКОГДА.

**И вторая половина той же аварии.** Пока разбирали первую, измерили вторую: все четыре
карточки существуют на ``origin/main`` и в чужих ``/tmp``-worktree — и НИ ОДНОЙ нет в
прод-дереве, из которого запущен бот (автосинк возит только ``spa_core/``·``scripts/``·
``tests/``). Журнал хранил путь как есть, поэтому нажатие по такой кнопке вернуло бы
«Карточка исчезла из трекера — ничего не записал». То есть добрать кнопки было мало: они
приехали бы декоративными.

**Что чиним, и чем это проверяется.**

* пуш ЗАПОМИНАЕТ, уехали ли кнопки (``buttons``) — иначе вопрос «получил ли владелец
  кнопки?» неотвечаем задним числом, и авария невидима ровно так же, как 10.08;
* бот, оживая, добирает кнопки к решениям, уехавшим без них — недостающим условием был
  он сам, значит и чинит он;
* fail-CLOSED обе стороны: не измерено / ответ дан / вопрос снят / уже чинили / карточка
  больше не на владельце / обработчика всё ещё нет ⇒ МОЛЧИМ (дубль хуже молчания);
* отметка «починено» — только после успешной отправки: сорвавшаяся посылка не имеет
  права сжечь единственный шанс;
* карточка переносится в ЖИВОЕ дерево, и в журнал уходит именно этот путь — иначе
  нажатие не находит, что закрывать; существующая живая копия НЕ затирается (в ней может
  лежать ответ владельца, #178);
* проводка (урок #144): починку зовёт сам цикл бота, а не только её собственный тест.

Время — вход, а не окружение: маячок ставится относительно ``FIXED_NOW``, литеральных
дат в фикстурах нет.
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
trackerStatus:
  type: owner-decision
title: "Система остановлена аварийным выключателем"
status: needs-owner
created: 2026-08-10
---

## Что случилось и почему это важно

Аварийный тормоз стоит с ночи, книга записана пустой. Причина уже ушла, остановка
держится сама собой.

## Что от тебя нужно

* **Вариант 1 (рекомендую) — снять стоп-кран и продолжить цикл.** Текст.
* **Вариант 2 — держать остановку.** Текст.
"""


# ── фикстуры окружения ───────────────────────────────────────────────────────


def _beacon(tmp_path, *, age_s: float):
    """Маячок бота указанного ВОЗРАСТА. ``age_s`` > 300 ⇒ бот считается лежащим."""
    p = tmp_path / "beacon.json"
    stamped = FIXED_NOW - timedelta(seconds=age_s)
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": stamped.isoformat(), "pid": 1,
        "capabilities": [aa.CAPABILITY],
    }), encoding="utf-8")
    return p


DEAD = aa.BEACON_MAX_AGE_S + 60   # бот лежит (пуш 04:13, старт 04:22)
ALIVE = 10.0                      # бот жив и стучит


@pytest.fixture()
def env(tmp_path):
    """Карточка на диске + пустой журнал + два маячка (лежащий и живой)."""
    card = tmp_path / "owner-decision-sistema-ostanovlena.md"
    card.write_text(CARD, encoding="utf-8")
    dead_dir = tmp_path / "beacon-dead"
    alive_dir = tmp_path / "beacon-alive"
    dead_dir.mkdir()
    alive_dir.mkdir()
    return {
        "card": card,
        "state": tmp_path / "telegram_owner_decisions.json",
        "dead": _beacon(dead_dir, age_s=DEAD),
        "alive": _beacon(alive_dir, age_s=ALIVE),
    }


class Sender:
    """Отправитель вызывающего: копит (text, keyboard). ``ok`` — успех отправки."""

    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def __call__(self, text, keyboard):
        self.sent.append((text, keyboard))
        return {"ok": True} if self.ok else None


def _rec(env, pid=None):
    doc = json.loads(env["state"].read_text(encoding="utf-8"))
    for r in doc["pushes"]:
        if pid is None or r.get("pid") == pid:
            return r
    return None


def _push(env, *, beacon):
    return od.register_push(env["card"], "Система остановлена", CARD,
                            now=FIXED_NOW, state_path=env["state"],
                            beacon_path=beacon)


# ── 1. авария видима: пуш ЗАПОМИНАЕТ, были ли кнопки ─────────────────────────


def test_push_records_that_buttons_did_not_go(env):
    """Бот лежит ⇒ кнопок нет, и это ЗАПИСАНО. Без записи авария невидима."""
    prep = _push(env, beacon=env["dead"])
    assert prep.keyboard is None
    assert "Кнопки сейчас недоступны" in prep.text  # ровно то, что видел владелец
    assert _rec(env)["buttons"] is False


def test_push_records_that_buttons_did_go(env):
    """Бот жив ⇒ кнопки уехали, и это тоже записано — отметка честна в обе стороны."""
    prep = _push(env, beacon=env["alive"])
    assert prep.keyboard is not None
    assert _rec(env)["buttons"] is True


# ── 2. сама авария 10.08: пуш при лежащем боте → бот встал → кнопки доехали ───


def test_dead_bot_push_is_healed_when_bot_comes_up(env):
    """ПОЛНЫЙ повтор 10.08: решение ушло текстом в 04:13, бот встал в 04:22.

    До починки этот сценарий заканчивался ничем: кнопок у сообщения не будет никогда.
    """
    prep = _push(env, beacon=env["dead"])
    send = Sender()

    fixed = od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                               beacon_path=env["alive"])

    assert fixed == [prep.pid]
    assert len(send.sent) == 1
    text, keyboard = send.sent[0]
    # Кнопки — по одной на вариант карточки, плюс «Подробнее».
    labels = [row[0]["text"] for row in keyboard["inline_keyboard"]]
    assert any(lbl.startswith("⭐ 1.") for lbl in labels)
    assert any(lbl.startswith("2.") for lbl in labels)
    # callback ведёт к ТОЙ ЖЕ карточке — иначе нажатие получит «не нашёл карточку».
    assert all(prep.pid in row[0]["callback_data"] for row in keyboard["inline_keyboard"])
    # Владелец должен понимать, почему решение пришло второй раз.
    assert "Кнопки подъехали" in text
    assert "Кнопки сейчас недоступны" not in text
    assert _rec(env, prep.pid)["buttons"] is True
    assert _rec(env, prep.pid)["buttons_fixed_at"]


def test_healed_message_keeps_the_same_options(env):
    """Починка ПОВТОРЯЕТ то же решение, а не сочиняет новое."""
    _push(env, beacon=env["dead"])
    send = Sender()
    od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                       beacon_path=env["alive"])
    text = send.sent[0][0]
    assert "снять стоп-кран" in text.lower()
    assert "держать остановку" in text.lower()


# ── 3. fail-CLOSED: когда чинить НЕЛЬЗЯ ──────────────────────────────────────


def test_heal_is_once_only(env):
    """Второй заход молчит: подъём бота не превращается в очередь дублей."""
    _push(env, beacon=env["dead"])
    first = Sender()
    od.heal_buttonless(first, now=FIXED_NOW, state_path=env["state"],
                       beacon_path=env["alive"])
    second = Sender()
    assert od.heal_buttonless(second, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert second.sent == []


def test_failed_send_does_not_burn_the_one_chance(env):
    """Отправка не удалась ⇒ отметки нет, и следующий заход пробует снова."""
    _push(env, beacon=env["dead"])
    failing = Sender(ok=False)
    assert od.heal_buttonless(failing, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert len(failing.sent) == 1
    assert "buttons_fixed_at" not in _rec(env)

    retry = Sender()
    assert od.heal_buttonless(retry, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"])
    assert len(retry.sent) == 1


def test_answered_decision_is_not_healed(env):
    """Владелец уже ответил ⇒ нажимать нечего, второе сообщение — шум."""
    prep = _push(env, beacon=env["dead"])
    doc = json.loads(env["state"].read_text(encoding="utf-8"))
    doc["pushes"][0]["choice"] = "1"
    env["state"].write_text(json.dumps(doc), encoding="utf-8")
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert send.sent == []
    assert prep.pid  # запись на месте, просто не тронута


def test_withdrawn_decision_is_not_healed(env):
    """Вопрос снят (находка оказалась ложной) ⇒ кнопок не досылаем (цикл #172)."""
    _push(env, beacon=env["dead"])
    od.mark_withdrawn(env["card"], now=FIXED_NOW, state_path=env["state"])
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert send.sent == []


def test_card_no_longer_on_the_owner_is_not_healed(env):
    """Карточка ушла из needs-owner ⇒ решение больше не требуется."""
    _push(env, beacon=env["dead"])
    env["card"].write_text(CARD.replace("status: needs-owner", "status: ingested"),
                           encoding="utf-8")
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert send.sent == []


def test_missing_card_is_not_healed(env):
    """Карточку удалили ⇒ молчим, а не падаем."""
    _push(env, beacon=env["dead"])
    env["card"].unlink()
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert send.sent == []


def test_unmeasured_legacy_record_is_not_healed(env):
    """Запись СТАРЕЕ починки (поля ``buttons`` нет) — «не измерено», а не «без кнопок».

    Fail-CLOSED против дубля: разослать по такой записи значит прислать владельцу
    второй экземпляр решения, которое, может быть, и так пришло с кнопками.
    """
    _push(env, beacon=env["dead"])
    doc = json.loads(env["state"].read_text(encoding="utf-8"))
    doc["pushes"][0].pop("buttons")
    env["state"].write_text(json.dumps(doc), encoding="utf-8")
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == []
    assert send.sent == []


def test_silent_while_the_bot_still_cannot_handle_taps(env):
    """Обработчика по-прежнему нет ⇒ чинить нечем; кнопку без обработчика не вешаем."""
    _push(env, beacon=env["dead"])
    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["dead"]) == []
    assert send.sent == []
    assert _rec(env)["buttons"] is False  # запись ждёт своего часа


def test_heal_is_bounded_per_run(env, tmp_path):
    """Подъём бота не выливается в залп: за раз чинится не больше ``limit``."""
    for i in range(4):
        card = tmp_path / f"owner-decision-{i}.md"
        card.write_text(CARD, encoding="utf-8")
        od.register_push(card, f"Решение {i}", CARD, now=FIXED_NOW,
                         state_path=env["state"], beacon_path=env["dead"])
    send = Sender()
    fixed = od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                               beacon_path=env["alive"], limit=2)
    assert len(fixed) == 2
    assert len(send.sent) == 2


# ── 4. кнопка ведёт к карточке, которую нажатию есть где найти ───────────────


OWNER_CHAT = "424242"


@pytest.fixture()
def split_trees(tmp_path):
    """Два дерева: ``wt`` — worktree сессии (карточка здесь), ``live`` — прод (пусто)."""
    wt = tmp_path / "wt" / "nimbalyst-local" / "tracker"
    wt.mkdir(parents=True)
    live = tmp_path / "live"
    (live / "nimbalyst-local" / "tracker").mkdir(parents=True)
    card = wt / "owner-decision-sistema-ostanovlena.md"
    card.write_text(CARD, encoding="utf-8")
    return {"card": card, "live": live,
            "live_card": live / "nimbalyst-local" / "tracker" / card.name,
            "state": tmp_path / "journal.json",
            "beacon": _beacon(tmp_path, age_s=ALIVE)}


def test_press_on_a_card_absent_from_the_live_tree_finds_nothing(split_trees):
    """Положительный контроль аварии: путь из чужого дерева ⇒ «карточка исчезла».

    Так и вело себя нажатие до переноса — журнал хранил путь worktree, а бот запущен
    в прод-дереве, где этого файла нет.
    """
    prep = od.register_push(split_trees["card"], "Система остановлена", CARD,
                            now=FIXED_NOW, state_path=split_trees["state"],
                            beacon_path=split_trees["beacon"])  # переноса нет (pytest)
    split_trees["card"].unlink()  # worktree сессии снят — ровно то, что происходит всегда
    res = od.record_choice(prep.pid, "1", OWNER_CHAT, owner_chat_id=OWNER_CHAT,
                           now=FIXED_NOW, state_path=split_trees["state"])
    assert res["ok"] is False and res["reason"] == "card_gone"


def test_card_is_carried_into_the_live_tree_and_the_press_lands(split_trees):
    """С переносом карточка есть там, где нажатие её ищет, и решение записывается."""
    prep = od.register_push(split_trees["card"], "Система остановлена", CARD,
                            now=FIXED_NOW, state_path=split_trees["state"],
                            beacon_path=split_trees["beacon"],
                            live_root=split_trees["live"])
    assert split_trees["live_card"].is_file(), "карточка не доехала до живого дерева"
    doc = json.loads(split_trees["state"].read_text(encoding="utf-8"))
    assert doc["pushes"][0]["card"] == str(split_trees["live_card"])

    split_trees["card"].unlink()  # worktree сессии снят
    res = od.record_choice(prep.pid, "1", OWNER_CHAT, owner_chat_id=OWNER_CHAT,
                           now=FIXED_NOW, state_path=split_trees["state"])
    assert res["ok"] is True, res
    written = split_trees["live_card"].read_text(encoding="utf-8")
    assert "owner_choice: 1" in written
    assert "owner-done" in written  # закрыл ВЛАДЕЛЕЦ, инвариант #14 не тронут


def test_existing_live_copy_is_never_overwritten(split_trees):
    """В живой копии может лежать ответ владельца — затирать её запрещено (#178)."""
    answered = CARD.replace("status: needs-owner",
                            "status: needs-owner\nowner_choice: 2")
    split_trees["live_card"].write_text(answered, encoding="utf-8")
    od.register_push(split_trees["card"], "Система остановлена", CARD,
                     now=FIXED_NOW, state_path=split_trees["state"],
                     beacon_path=split_trees["beacon"],
                     live_root=split_trees["live"])
    assert "owner_choice: 2" in split_trees["live_card"].read_text(encoding="utf-8")


def test_materialize_never_raises_on_a_missing_card(tmp_path):
    """Карточки нет — возвращаем что дали, а не падаем внутри уведомления."""
    ghost = tmp_path / "нет-такой.md"
    assert od.materialize_card(ghost, live_root=tmp_path / "live") == ghost


# ── 5. проводка: починку зовёт САМ бот (урок #144) ───────────────────────────


class _StubBot:
    """Достаточно бота, чтобы проверить порядок вызовов в его собственном цикле."""

    def __init__(self):
        self.calls = []

    def refresh_capability_beacon(self):
        self.calls.append("beacon")

    def heal_buttonless_decisions(self):
        self.calls.append("heal")
        return 0

    def get_updates(self):
        self.calls.append("updates")
        return []

    def handle_update(self, upd):  # pragma: no cover — обновлений нет
        raise AssertionError("не должно вызываться")


def test_run_once_heals_after_stamping_the_beacon():
    """``run_once`` штампует маячок, потом чинит, потом читает обновления.

    Порядок — не косметика: отправитель кнопок проверяет ИМЕННО маячок, и без свежей
    отметки бот не признал бы способным даже сам себя.
    """
    from spa_core.telegram.bot import TelegramBot

    stub = _StubBot()
    assert TelegramBot.run_once(stub) == 0
    assert stub.calls == ["beacon", "heal", "updates"]


def test_polling_loop_heals_before_the_first_poll():
    """Тот же вызов есть и в вечном цикле — иначе починка мертва в проде.

    Реальный запуск идёт через ``run_polling``; ``run_once`` живёт только под ``--once``.
    Ловим цикл на первом же опросе (``KeyboardInterrupt`` минует ``except Exception``).
    """
    from spa_core.telegram.bot import TelegramBot

    calls = []

    class _Poller(_StubBot):
        _offset = 0
        _last_beat = 0.0

        def acquire_single_instance_lock(self):
            return True

        def release_single_instance_lock(self):
            calls.append("unlock")

        def settle_startup(self):
            calls.append("settle")

        def register_commands(self):
            calls.append("commands")

        def _start_liveness_watchdog(self):
            calls.append("watchdog")

        def refresh_capability_beacon(self):
            calls.append("beacon")

        def heal_buttonless_decisions(self):
            calls.append("heal")
            return 0

        def get_updates(self):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        TelegramBot.run_polling(_Poller())

    assert "heal" in calls, "вечный цикл бота починку не зовёт — фича мертва в проде"
    assert calls.index("heal") < calls.index("unlock")
    assert calls.index("beacon") < calls.index("heal")
