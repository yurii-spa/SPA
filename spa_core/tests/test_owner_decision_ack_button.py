#!/usr/bin/env python3
"""На карточку-ПОРУЧЕНИЕ владелец может ответить с телефона. Чем именно — здесь и пиннится.

Замер цикла #197 (журнал отправок `data/telegram_owner_decisions.json`): пять карточек,
уехавших владельцу 08.08, за двое суток не получили НИ ОДНОГО ответа. У всех пяти секция
«Что от тебя нужно» вариантов не предлагает — это поручения («сделай то-то») или сообщения
о находке. Разбор вёл себя правильно: кнопок нет, текст честно говорил «вариантов в карточке
не нашёл». Но ответить на такую карточку было можно ТОЛЬКО словами в чат — и молчание стало
неотличимо от «не увидел».

Отсюда две кнопки, которых в карточке нет и быть не может:

* **«✅ Принято»** — подтверждение «прочитал и согласен». Это решение ВЛАДЕЛЬЦА, поэтому идёт
  тем же узким owner-путём (`owner_answer.record_owner_answer`, сверка личности ВНУТРИ
  писателя) и так же закрывает карточку.
* **«⏳ Позже»** — НЕ решение. Карточка не меняется ни на байт, статус остаётся `needs-owner`,
  вопрос остаётся открытым; в журнал ложится только факт, что владелец его видел.

Что каждый тест здесь охраняет (все — положительные контроли, а не украшения):

* инвариант #14 не ослаблен: чужое нажатие «Принято» карточку не закрывает и не трогает;
* ADR-075 не ослаблен: подтверждение появляется ТОЛЬКО там, где карточка выбора не
  предлагает вовсе — не рядом с вариантами, не вместо непрочитанных вариантов, не на
  карточке с двумя независимыми вопросами и не на многовыборной;
* «Позже» не притворяется решением — иначе владелец счёл бы вопрос закрытым;
* оба входа (пуш и экран «Мои решения») дают ОДНУ И ТУ ЖЕ клавиатуру;
* кнопки подтверждения доезжают и до карточки, уехавшей, пока бот лежал.

Время — ВХОД, а не окружение: все отметки от одного якоря, литеральных дат нет.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.telegram import prefs as prefs_store
from spa_core.telegram.router import Router
from spa_core.telegram.views import decisions as V
from spa_core.tests._freshness import now_utc

NOW = now_utc()
OWNER = "424242"
STRANGER = "999999"

# Живая форма поручения: §2.4, четыре секции, НИ ОДНОГО варианта — «сделай то-то».
CARD_ERRAND = """---
trackerStatus:
  type: owner-decision
title: "Добавить ключ Etherscan на сервер"
status: needs-owner
created: 2026-08-08
---

## Что случилось и почему это важно

Без ключа Etherscan не работает проверка кошельков — раздел показывает пустоту.

## Что от тебя нужно

Зайди в настройки сервера и добавь ключ. Это займёт минуту, дальше всё поедет само.

## Как понять, что готово

В разделе появились адреса кошельков.

## Что будет после

Проверю, что ключ подхватился, и закрою карточку.
"""

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

# Живая карточка own-31: ДВА независимых вопроса, а не выбор одного варианта.
CARD_TWO_QUESTIONS = """---
trackerStatus:
  type: owner-decision
title: "Десять агентов в реестре без флота"
status: needs-owner
---

## Что от тебя нужно

Два решения:

1. **Ставить ли четыре готовых?** Рекомендую да.
2. **Выводить ли шесть из реестра?** Рекомендую да.
"""

CARD_MULTISELECT = """---
trackerStatus:
  type: owner-decision
title: "Табличка честности"
status: needs-owner
---

## Что от тебя нужно

Выбери, как поступаем — можно взять несколько.

* **Вариант 1 — переписать.** Текст.
* **Вариант 2 — удалить.** Текст.
"""


class MockTransport:
    def __init__(self):
        self.edits, self.sends, self.answers = [], [], []

    def edit_message_text(self, chat_id, message_id, text, reply_markup):
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True}

    def send_message(self, chat_id, text, reply_markup):
        self.sends.append((chat_id, text, reply_markup))
        return {"ok": True}

    def answer_callback(self, callback_id):
        self.answers.append(callback_id)


@pytest.fixture()
def beacon(tmp_path, monkeypatch):
    """Живой маячок бота, умеющего обрабатывать нажатия под решениями."""
    p = tmp_path / "telegram_bot_capabilities.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot", "pid": 1,
        "updated_at": NOW.isoformat(), "capabilities": list(aa.CAPABILITIES),
    }), encoding="utf-8")
    monkeypatch.setattr(aa, "BEACON_PATH", p, raising=True)
    return p


@pytest.fixture()
def dead_beacon(tmp_path):
    """Маячок протухшего бота: кнопок в момент отправки не будет."""
    p = tmp_path / "beacon-dead.json"
    stamped = NOW - timedelta(seconds=aa.BEACON_MAX_AGE_S + 60)
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot", "pid": 1,
        "updated_at": stamped.isoformat(), "capabilities": list(aa.CAPABILITIES),
    }), encoding="utf-8")
    return p


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """Журнал отправок во временном файле — включая вызовы БЕЗ ``state_path`` (вьюхи)."""
    path = tmp_path / "telegram_owner_decisions.json"
    monkeypatch.setattr(od, "STATE_PATH", path, raising=True)
    monkeypatch.setenv("SPA_OWNER_DECISIONS_TEST", "1")
    assert od._state_path() == path, "изоляция журнала не сработала"
    return path


@pytest.fixture()
def card(tmp_path):
    p = tmp_path / "owner-decision-klyuch-etherscan.md"
    p.write_text(CARD_ERRAND, encoding="utf-8")
    return p


@pytest.fixture()
def owner_known(monkeypatch):
    """chat_id владельца известен: иначе писатель отказывает всем (fail-CLOSED)."""
    monkeypatch.setattr("spa_core.owner_queue.owner_answer._owner_chat_id",
                        lambda explicit=None: OWNER)


def _push(card_path, journal_path, beacon_path, *, body: str = CARD_ERRAND):
    return od.register_push(card_path, "Добавить ключ Etherscan на сервер", body,
                            now=NOW, state_path=journal_path, beacon_path=beacon_path)


def _rec(journal_path, pid):
    doc = json.loads(journal_path.read_text(encoding="utf-8"))
    return next(r for r in doc["pushes"] if r["pid"] == pid)


def _choices(keyboard):
    return [od.parse_callback(b[0]["callback_data"])[1]
            for b in keyboard["inline_keyboard"]]


# ── 1. поручение перестало быть безответным ──────────────────────────────────


def test_an_errand_card_gets_something_to_answer_with(beacon, card):
    """Положительный контроль замера #197: пять поручений, ноль способов ответить.

    Раньше клавиатуры не было вовсе, и владелец мог ответить только словами в чат — по факту
    не ответил ни на одну за двое суток.
    """
    prep = od.prepare("Ключ Etherscan", CARD_ERRAND, card.stem, now=NOW, beacon_path=beacon)
    assert prep.options == []
    assert prep.ack is True
    assert _choices(prep.keyboard) == [od.ACK_CHOICE, od.LATER_CHOICE, od.MORE_CHOICE]
    # Текст и клавиатура обязаны говорить ОДНО (урок «Нажми кнопку» без кнопок).
    assert od.ACK_BUTTON_RU in prep.text and od.LATER_BUTTON_RU in prep.text


def test_the_confirmation_is_never_offered_instead_of_real_options(beacon):
    """ADR-075: там, где карточка предлагает выбор, подтверждения быть не должно.

    Иначе «Принято» стало бы способом закрыть вопрос, не ответив на него.
    """
    prep = od.prepare("Бюджет", CARD_WITH_OPTIONS, "own-b", now=NOW, beacon_path=beacon)
    assert prep.ack is False
    assert od.ACK_CHOICE not in _choices(prep.keyboard)


@pytest.mark.parametrize("body,why", [
    (CARD_TWO_QUESTIONS, "два независимых вопроса — подтверждение не ответит ни на один"),
    (CARD_MULTISELECT, "многовыборная карточка — подтверждение съело бы выбор"),
])
def test_cards_whose_choice_we_refused_to_show_get_no_confirmation(beacon, body, why):
    """Кнопок нет по РАЗНЫМ причинам, и подтверждением закрывается только ОДНА из них.

    Живая карточка own-31 («Ставить ли четыре готовых? Выводить ли шесть?») — тот случай,
    где «Принято» закрыло бы карточку, не ответив ни на один вопрос владельца.
    """
    assert od.offers_no_choice(body) is False, why
    prep = od.prepare("Карточка", body, "own-x", now=NOW, beacon_path=beacon)
    assert prep.ack is False
    assert prep.keyboard is None


def test_a_card_with_unreadable_options_is_not_closed_by_a_confirmation(beacon):
    """Варианты НАПИСАНЫ, а собрать кнопки не смогли мы — это наша неполадка.

    Подтверждение здесь закрыло бы карточку, похоронив выбор, который автор написал.
    """
    body = ("## Что от тебя нужно\n\n"
            "- **Вариант А1 (рекомендую).** Первое решение.\n"
            "- **Вариант Б1.** Второе решение.\n")
    assert od.has_unparsed_options(body) is True
    assert od.offers_no_choice(body) is False
    prep = od.prepare("Аварийный тормоз", body, "own-rearm", now=NOW, beacon_path=beacon)
    assert prep.ack is False and prep.keyboard is None


def test_reserved_tokens_cannot_collide_with_a_card_option_number(beacon):
    """Служебные токены не имеют права совпасть с номером варианта из карточки.

    Столкнись они — нажатие «Принято» записалось бы как выбор варианта, и наоборот.
    Утверждение проверяется, а не остаётся комментарием.
    """
    # По одной карточке на форму метки: смешанные семьи («1» и «А1» рядом) разбор отвергает
    # целиком, и такой замер не проверял бы ничего.
    nums = set()
    for n in ("1", "12", "А", "А1", "B2"):
        body = f"## Что от тебя нужно\n\n* **Вариант {n} — текст {n}.** Хвост.\n"
        parsed = od.parse_options(body)
        assert parsed, f"метка «{n}» обязана разобраться — иначе тест ничего не проверяет"
        nums |= {o.num.lower() for o in parsed}
    assert nums.isdisjoint(od.RESERVED_CHOICES)


# ── 2. нажатие «Принято» = решение владельца (инвариант #14) ──────────────────


def test_owner_tap_on_accepted_closes_the_card_through_the_owner_path(journal, beacon,
                                                                     card, owner_known):
    """Подтверждение записывается тем же owner-путём и закрывает карточку."""
    prep = _push(card, journal, beacon)
    assert prep.ack is True and _rec(journal, prep.pid)["ack"] is True

    res = od.record_choice(prep.pid, od.ACK_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=journal)

    assert res["ok"] is True and res.get("ack") is True
    text = card.read_text(encoding="utf-8")
    assert "status: owner-done" in text
    assert f"owner_choice: {od.ACK_CHOICE}" in text
    # В карточке — подтверждение, а НЕ «Вариант ack»: выбора автор не писал.
    assert "**Принято**" in text
    assert "Вариант ack" not in text
    assert _rec(journal, prep.pid)["choice"] == od.ACK_CHOICE
    assert "принято" in od.confirmation_text(res).lower()


def test_a_stranger_cannot_accept_the_owners_card(journal, beacon, card, owner_known):
    """Инвариант #14 не ослаблен: чужое «Принято» не меняет карточку ни на байт."""
    prep = _push(card, journal, beacon)
    before = card.read_text(encoding="utf-8")

    res = od.record_choice(prep.pid, od.ACK_CHOICE, STRANGER, owner_chat_id=OWNER, now=NOW,
                           state_path=journal)

    assert res["ok"] is False and res["reason"] == "not_owner"
    assert card.read_text(encoding="utf-8") == before
    assert _rec(journal, prep.pid)["choice"] is None


def test_accepting_twice_is_not_two_different_answers(journal, beacon, card, owner_known):
    """Владелец может нажать дважды из двух чатов — это ОДНО решение."""
    prep = _push(card, journal, beacon)
    od.record_choice(prep.pid, od.ACK_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                     state_path=journal)
    first = card.read_text(encoding="utf-8")

    again = od.record_choice(prep.pid, od.ACK_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                            state_path=journal)

    assert again["ok"] is True and again["already"] is True
    assert card.read_text(encoding="utf-8") == first
    assert first.count(od.ACK_ANSWER_LINE.splitlines()[0]) == 1


def test_a_confirmation_tap_on_a_card_that_offers_a_choice_is_refused(journal, beacon,
                                                                     card, owner_known):
    """Старое сообщение / ручной callback: «Принято» по карточке С вариантами — отказ.

    Fail-CLOSED и вслух: подтверждением нельзя подменить ответ на вопрос.
    """
    card.write_text(CARD_WITH_OPTIONS, encoding="utf-8")
    prep = _push(card, journal, beacon, body=CARD_WITH_OPTIONS)
    assert prep.options, "проверяем именно карточку С выбором"
    before = card.read_text(encoding="utf-8")

    res = od.record_choice(prep.pid, od.ACK_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=journal)

    assert res["ok"] is False and res["reason"] == "ack_not_allowed"
    assert card.read_text(encoding="utf-8") == before
    assert "номером варианта" in od.confirmation_text(res)


# ── 3. «Позже» НЕ решение ────────────────────────────────────────────────────


def test_later_leaves_the_question_open_and_the_card_untouched(journal, beacon, card,
                                                              owner_known):
    """«Позже» не закрывает карточку — иначе владелец счёл бы вопрос решённым.

    Записывается только факт, что он его ВИДЕЛ: без этого «отложил» и «не заметил»
    неотличимы — та самая неразличимость, из-за которой пять карточек висели двое суток.
    """
    prep = _push(card, journal, beacon)
    before = card.read_text(encoding="utf-8")

    res = od.record_choice(prep.pid, od.LATER_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=journal)

    assert res["ok"] is True and res["deferred"] is True
    assert card.read_text(encoding="utf-8") == before
    assert "status: needs-owner" in before
    rec = _rec(journal, prep.pid)
    assert rec["choice"] is None and rec["deferred_count"] == 1
    reply = od.confirmation_text(res)
    assert "не закрывал" in reply and "Записал" not in reply


def test_a_deferred_question_is_still_an_open_one(journal, beacon, card, owner_known):
    """Отложенное решение остаётся в очереди открытых — иначе оно потерялось бы молча."""
    prep = _push(card, journal, beacon)
    od.record_choice(prep.pid, od.LATER_CHOICE, OWNER, owner_chat_id=OWNER, now=NOW,
                     state_path=journal)
    assert [r["pid"] for r in od.open_pushes(state_path=journal)] == [prep.pid]


# ── 4. проводка: роутер и экран «Мои решения» ────────────────────────────────


def test_tap_through_the_router_records_the_confirmation(journal, beacon, card,
                                                         owner_known, tmp_path,
                                                         monkeypatch):
    """Полная проводка (урок #144): кнопка из пуша → роутер → карточка закрыта.

    Снятая точка вызова оставляет тесты зелёными, пока фича мертва в проде.
    """
    monkeypatch.setattr(prefs_store, "PREFS_FILE", tmp_path / "user_prefs.json",
                        raising=True)
    router = Router(MockTransport(), OWNER)
    prep = _push(card, journal, beacon)
    data = prep.keyboard["inline_keyboard"][0][0]["callback_data"]

    router.handle_callback(data, OWNER, message_id=7, callback_id="cb1")

    assert "status: owner-done" in card.read_text(encoding="utf-8")
    assert router.transport.sends and not router.transport.edits
    assert "принято" in router.transport.sends[0][1].lower()


def test_the_menu_offers_exactly_the_same_buttons_as_the_push(journal, beacon, card):
    """Два входа — одна клавиатура. Разъедутся — разъедутся молча."""
    prep = _push(card, journal, beacon)
    _text, kb = V.render_item(prep.pid, "ru")
    from_menu = [b[0]["callback_data"] for b in kb["inline_keyboard"]
                 if b[0]["callback_data"].startswith(od.CALLBACK_PREFIX)]
    assert from_menu == [b[0]["callback_data"] for b in prep.keyboard["inline_keyboard"]]


def test_the_menu_does_not_invent_a_confirmation_for_an_unreadable_card(journal, beacon,
                                                                       card):
    """Экран берёт признак из ЖУРНАЛА (измерен при отправке), а не пересчитывает его.

    Карточка, чей выбор мы не прочитали, подтверждения не получает и здесь.
    """
    card.write_text(CARD_MULTISELECT, encoding="utf-8")
    prep = _push(card, journal, beacon, body=CARD_MULTISELECT)
    assert _rec(journal, prep.pid)["ack"] is False
    _text, kb = V.render_item(prep.pid, "ru")
    assert not [b for b in kb["inline_keyboard"]
                if b[0]["callback_data"].startswith(od.CALLBACK_PREFIX)]


# ── 5. кнопки доезжают и к поручению, уехавшему без них ──────────────────────


def test_confirmation_buttons_are_healed_after_the_bot_wakes_up(journal, card,
                                                                dead_beacon, beacon):
    """Поручение уехало, пока бот лежал ⇒ кнопки добираются, когда он встал.

    Отбор «есть варианты» этого не пропускал: у поручения их нет по построению, и
    единственный шанс на кнопки сгорал молча.
    """
    prep = _push(card, journal, dead_beacon)
    assert prep.keyboard is None and _rec(journal, prep.pid)["buttons"] is False

    heals = od.buttonless_pushes(now=NOW, state_path=journal, beacon_path=beacon)

    assert [h.pid for h in heals] == [prep.pid]
    assert _choices(heals[0].keyboard) == [od.ACK_CHOICE, od.LATER_CHOICE, od.MORE_CHOICE]
    assert "Кнопки подъехали" in heals[0].text
