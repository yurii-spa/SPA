#!/usr/bin/env python3
"""Второй вход к вариантам ответа: те же кнопки из меню бота (задание владельца).

Задание 2026-08-07 звучало «либо кнопки под алертом, **либо** это всё интегрировать
в меню». Первая половина доставлена циклом #148 (ADR-069), здесь — вторая.

Что именно пиннится и почему:

* **Критерий готовности карточки — совпадение вариантов из ОБОИХ входов.** Два
  экрана, показывающие «варианты ответа на проблему», обязаны показывать ОДНО И ТО
  ЖЕ; разъехавшись, они разъедутся молча. Поэтому сравнение побайтовое, по всем
  родам сразу, а не «на глазок по одному роду».
* **Проводка, а не только детали** (урок #144: снятая точка вызова оставила 22 своих
  и 1342 смежных теста зелёными, пока фича была мертва в проде). Отсюда сквозной
  прогон через РОУТЕР: `nav:` из списка → лист-вид → `act:aa:` → карточка, и она
  та же, что дал бы вход из-под алерта. Плюс отдельные тесты на достижимость
  экрана из меню «Предупреждения» и на реестр вьюх — без них экран есть, но к нему
  нельзя дойти.
* **Fail-CLOSED до нажатия, а не после.** Вытесненный из кольцевого журнала алерт
  цитировать нечем; кнопки вариантов на таком экране не показываются вовсе, а не
  отвечают отказом после нажатия.
* **Тесты не пишут в живое состояние алертов.** Инцидент «прогон тестов может
  заглушить настоящую тревогу»: фикстура сама ПРОВЕРЯЕТ, что резолв пути увёл
  журнал во временный файл, — иначе изоляция ломается молча.

Время — вход, а не окружение (`.claude/rules/deployment.md`, преференция №1):
отметки строятся от одного `FIXED_NOW`, литеральных дат здесь нет.
"""
from __future__ import annotations

import json

import pytest

from spa_core.telegram import alert_actions as aa
from spa_core.telegram import i18n, menus
from spa_core.telegram import prefs as prefs_store
from spa_core.telegram.router import CALLBACK_MAX_BYTES, Router
from spa_core.telegram.views import VIEW_REGISTRY, get_builder, home
from spa_core.telegram.views import warnings as W
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()

OWNER = "424242"
PROBLEM = "🚨 SPA — агент com.spa.daily_cycle не работает (exit 78)\nвторая строка тела"
RISK = "🚨 SPA — HARD_KILL: drawdown 10.4% превысил порог"

ITEM_PATH = "warnings.problems.item"
LIST_PATH = "warnings.problems"


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
def journal(tmp_path, monkeypatch):
    """Журнал алертов уезжает во временный файл — и это ПРОВЕРЯЕТСЯ, а не постулируется.

    Вьюхи зовут `get_alert`/`recent_alerts` без `state_path` (у билдера фиксированная
    сигнатура), поэтому изоляция обязана держаться на резолве пути внутри модуля.
    Если механизм резолва однажды поменяется, ассерт ниже покраснеет здесь, а не
    молча запишет тестовый алерт в живой `data/telegram_alert_actions.json`.
    """
    path = tmp_path / "telegram_alert_actions.json"
    monkeypatch.setattr(aa, "STATE_PATH", path, raising=True)
    monkeypatch.setenv("SPA_ALERT_ACTIONS_TEST", "1")
    assert aa._state_path() == path, "изоляция журнала не сработала — тест писал бы в живое состояние"
    return path


@pytest.fixture()
def beacon(tmp_path, monkeypatch):
    """Маячок живого обработчика — нужен ТОЛЬКО входу из-под алерта (register_alert)."""
    path = tmp_path / "telegram_bot_capabilities.json"
    path.write_text(json.dumps({
        "schema_version": 1, "capabilities": [aa.CAPABILITY],
        "updated_at": FIXED_NOW.isoformat(),
    }))
    monkeypatch.setattr(aa, "BEACON_PATH", path, raising=True)
    return path


@pytest.fixture()
def router(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_store, "PREFS_FILE", tmp_path / "user_prefs.json",
                        raising=True)
    return Router(MockTransport(), OWNER)


def _register(text, journal_path, beacon_path, *, lang="ru"):
    out = aa.register_alert(text, lang=lang, now=FIXED_NOW,
                            state_path=journal_path, beacon_path=beacon_path)
    assert out is not None, "алерт обязан был зарегистрироваться"
    return out  # (alert_id, keyboard)


def _seed(journal_path, kind, *, alert_id="deadbeef", text=PROBLEM, choices=None):
    """Положить в журнал запись ЗАДАННОГО рода.

    Классификатор родов пиннится своими тестами (`test_alert_actions.py`); здесь
    предмет проверки другой — что лист-вид показывает варианты ИМЕННО того рода,
    который записан у алерта. Поэтому род задаётся прямо, а не подбором текста.
    """
    journal_path.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_alert_actions",
        "alerts": [{"id": alert_id, "ts": FIXED_NOW.isoformat(), "kind": kind,
                    "text": text, "choices": choices or {}}],
    }))
    return alert_id


def _option_rows(keyboard):
    """Ряды кнопок ВАРИАНТОВ (навигационные — те, что ведут в `nav:`, — отбрасываем)."""
    return [row for row in keyboard["inline_keyboard"]
            if all(str(b.get("callback_data", "")).startswith(aa.CALLBACK_PREFIX)
                   for b in row)]


# ── критерий готовности карточки: варианты совпадают у обоих входов ──────────


@pytest.mark.parametrize("kind", sorted(aa.KIND_TITLE_RU))
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_menu_shows_byte_identical_options_for_every_kind(journal, kind, lang):
    """По КАЖДОМУ роду проблемы меню показывает ровно те же варианты, что алерт."""
    alert_id = _seed(journal, kind)
    from_alert = aa.build_keyboard(alert_id, kind, lang)["inline_keyboard"]
    _text, from_menu = W.render_item(arg=alert_id, lang=lang)
    # лист-вид собирается вокруг build_keyboard — сравниваем ряды вариантов побайтово
    assert _option_rows(from_menu) == from_alert, (
        "варианты из меню разошлись с вариантами под алертом (род {})".format(kind))


def test_risk_kind_recommends_owner_decision_from_the_menu_too(journal):
    """Инвариант #1 держится на ОБОИХ входах: у риска рекомендация — решение владельца.

    Кнопка «агент починит просадку» из меню обучала бы владельца одним нажатием
    заказывать то, что агенту запрещено, — ровно как и под алертом.
    """
    alert_id = _seed(journal, "risk", text=RISK)
    _text, kb = W.render_item(arg=alert_id, lang="ru")
    starred = [b for row in _option_rows(kb) for b in row if "⭐" in b["text"]]
    assert len(starred) == 1
    assert starred[0]["callback_data"].endswith(":own")


def test_option_callbacks_do_not_depend_on_language(journal):
    """Язык меняет ПОДПИСИ, но не сами варианты: иначе EN-владелец получит другой набор."""
    alert_id = _seed(journal, "problem")
    ru = _option_rows(W.render_item(arg=alert_id, lang="ru")[1])
    en = _option_rows(W.render_item(arg=alert_id, lang="en")[1])
    assert [b["callback_data"] for row in ru for b in row] == \
           [b["callback_data"] for row in en for b in row]
    assert [b["text"] for row in ru for b in row] != \
           [b["text"] for row in en for b in row], "подписи обязаны локализоваться"


def test_recommended_option_is_marked_in_menu_too(journal):
    """⭐ рекомендация — часть реестра; вход из меню обязан её показывать."""
    alert_id = _seed(journal, "problem")
    _text, kb = W.render_item(arg=alert_id, lang="ru")
    labels = [b["text"] for row in _option_rows(kb) for b in row]
    assert sum("⭐" in l for l in labels) == 1


def test_item_quotes_the_alert_verbatim_including_body_lines(journal):
    """Карточка цитирует алерт дословно — экран обязан показывать то же, что уедет в неё."""
    alert_id = _seed(journal, "agent_down")
    text, _kb = W.render_item(arg=alert_id, lang="ru")
    for line in PROBLEM.splitlines():
        assert line in text


# ── сквозная проводка: список → лист-вид → карточка ──────────────────────────


def test_end_to_end_menu_tap_creates_the_same_card_as_the_alert_button(
        journal, beacon, router, tmp_path, monkeypatch):
    """Полный путь через РОУТЕР: `nav:` из списка → лист-вид → `act:aa:` → карточка.

    Это и есть ответ на вопрос владельца «получу ли я ту же карточку»: сравниваем
    карточку, заведённую из меню, с карточкой того же варианта под алертом.
    """
    tracker = tmp_path / "tracker"
    alert_id, _kb = _register(PROBLEM, journal, beacon)

    # 1) лист-вид открывается навигацией с аргументом-идентификатором
    router.handle_callback("nav:{}|{}".format(ITEM_PATH, alert_id), OWNER, 7, "cb1")
    assert len(router.transport.edits) == 1
    item_text, item_kb = router.transport.edits[0][2], router.transport.edits[0][3]
    assert "com.spa.daily_cycle" in item_text  # текст алерта процитирован

    # 2) нажатие варианта из этой же клавиатуры
    option_cb = _option_rows(item_kb)[0][0]["callback_data"]
    real_record = aa.record_choice
    monkeypatch.setattr(aa, "record_choice", lambda a, o, **kw: real_record(
        a, o, state_path=journal, tracker_dir=tracker, now=FIXED_NOW))
    router.handle_callback(option_cb, OWNER, 7, "cb2")

    assert len(router.transport.sends) == 1, "подтверждение уходит НОВЫМ сообщением"
    cards = sorted(p.name for p in tracker.glob("*.md"))
    assert len(cards) == 1, "нажатие из меню обязано завести карточку"

    # 3) тот же вариант под самим алертом даёт карточку того же вида
    option_id = option_cb.rsplit(":", 1)[1]
    other = tmp_path / "tracker2"
    res = real_record(alert_id, option_id, state_path=journal, tracker_dir=other,
                      now=FIXED_NOW)
    assert res.ok and res.already, "идемпотентность по (алерт, вариант) сохраняется"


def test_menu_entrance_needs_no_beacon(journal, monkeypatch, tmp_path):
    """Интерлок маячка — про доставку кода отправителю, а не про меню.

    Экран рисует ТОТ ЖЕ процесс, чей роутер обработает нажатие: бот без обработчика
    не нарисует и экрана. Требовать здесь маячок значило бы гасить рабочие кнопки.
    """
    alert_id = _seed(journal, "problem")
    monkeypatch.setattr(aa, "BEACON_PATH", tmp_path / "missing.json", raising=True)
    assert aa.handler_available() is False
    _text, kb = W.render_item(arg=alert_id, lang="ru")
    assert _option_rows(kb), "варианты в меню обязаны остаться"


# ── список проблем ───────────────────────────────────────────────────────────


def test_list_rows_are_buttons_newest_first(journal, beacon):
    first, _ = _register(PROBLEM, journal, beacon)
    second, _ = _register(RISK, journal, beacon)
    _text, kb = W.render_problems(lang="ru")
    navs = [b["callback_data"] for row in kb["inline_keyboard"] for b in row
            if str(b.get("callback_data", "")).startswith("nav:" + ITEM_PATH)]
    assert navs[0] == "nav:{}|{}".format(ITEM_PATH, second)
    assert navs[1] == "nav:{}|{}".format(ITEM_PATH, first)


def test_list_callback_data_fits_telegram_limit(journal, beacon):
    _register(PROBLEM, journal, beacon)
    _text, kb = W.render_problems(lang="ru")
    for row in kb["inline_keyboard"]:
        for b in row:
            assert len(str(b["callback_data"]).encode("utf-8")) <= CALLBACK_MAX_BYTES


def test_list_marks_problems_that_already_have_a_card(journal, beacon, tmp_path):
    """Без этой пометки владелец жмёт повторно, гадая, сработало ли в прошлый раз."""
    alert_id, _kb = _register(PROBLEM, journal, beacon)
    text_before, _ = W.render_problems(lang="ru")
    assert "карточка заведена" not in text_before

    res = aa.record_choice(alert_id, "fix", state_path=journal,
                           tracker_dir=tmp_path / "tracker", now=FIXED_NOW)
    assert res.ok and res.card_path
    text_after, _ = W.render_problems(lang="ru")
    assert "карточка заведена" in text_after
    assert "✅" in text_after


def test_empty_journal_says_so_without_crashing(journal):
    text, kb = W.render_problems(lang="ru")
    assert "Проблем с вариантами ответа пока не было" in text
    assert kb["inline_keyboard"], "навигационный ряд обязан остаться"


def test_corrupt_journal_does_not_break_the_screen(journal):
    journal.write_text("{ not json at all")
    text, _kb = W.render_problems(lang="ru")
    assert "Проблем с вариантами ответа пока не было" in text


# ── fail-CLOSED: вытесненный алерт ───────────────────────────────────────────


def test_aged_out_alert_shows_no_option_buttons(journal):
    """Цитировать нечего ⇒ вариантов не показываем ВООБЩЕ — честность до нажатия."""
    text, kb = W.render_item(arg="00000000", lang="ru")
    assert "вытеснен из журнала" in text
    assert _option_rows(kb) == []


def test_empty_arg_is_treated_as_missing_alert(journal):
    text, kb = W.render_item(arg="", lang="ru")
    assert "вытеснен из журнала" in text
    assert _option_rows(kb) == []


# ── достижимость: экран, к которому нельзя дойти, не существует ──────────────


def test_warnings_screen_offers_the_problems_button():
    _text, kb = W.render_active(lang="ru")
    targets = [b.get("callback_data") for row in kb["inline_keyboard"] for b in row]
    assert "nav:" + LIST_PATH in targets


def test_both_new_paths_are_registered_and_not_the_home_fallback():
    for path, builder in ((LIST_PATH, W.render_problems), (ITEM_PATH, W.render_item)):
        assert VIEW_REGISTRY.get(path) is builder
        assert get_builder(path) is not home.render


def test_back_from_item_returns_to_the_list_not_home():
    """Иначе владелец после каждой проблемы возвращается в корень и ищет список заново."""
    assert menus.parent_of(ITEM_PATH) == LIST_PATH
    row = menus.nav_row(ITEM_PATH, "ru")
    assert row[0]["callback_data"] == "nav:" + LIST_PATH


def test_item_is_a_dynamic_leaf_not_a_static_child():
    """Лист-вид адресуется только с аргументом: статической кнопкой он был бы пустым."""
    assert ITEM_PATH not in menus.TREE[LIST_PATH]["children"]
    assert ITEM_PATH in menus.TREE


def test_breadcrumb_walks_up_the_new_chain():
    assert menus.breadcrumb(ITEM_PATH, "ru") == "{} › Предупреждения › Проблемы › Проблема".format(
        i18n.t("crumb.home", "ru"))


# ── двуязычность (правило site-copy на копию бота не распространяется, но
#     смешанный алфавит в RU — та же болезнь) ────────────────────────────────


@pytest.mark.parametrize("key", [
    "btn.problems", "crumb.problems", "crumb.problem", "ttl.problems",
    "w.no_problems", "w.problems_shown", "w.card_done", "w.pick_option",
    "w.problem_gone",
])
def test_new_strings_exist_in_both_languages(key):
    assert i18n.t(key, "en") != key and i18n.t(key, "ru") != key
    assert i18n.t(key, "en") != i18n.t(key, "ru")


def test_all_views_still_render_after_the_additions():
    """Смежный контроль: новая ветка дерева не уронила ни один существующий экран."""
    for path in VIEW_REGISTRY:
        text, kb = get_builder(path)(arg="", lang="ru", page=0, prefs={})
        assert isinstance(text, str) and text
        assert isinstance(kb, dict) and "inline_keyboard" in kb
