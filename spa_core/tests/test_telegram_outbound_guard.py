#!/usr/bin/env python3
"""Заслон перед отправкой владельцу — ОДИН на обе двери в Телеграм.

Замер 13.08 (цикл #215). Владелец голосом: «мне это сообщение в цикле приходит, где-то
за день раз 40-50, каждые примерно 1-10 минут… я хочу, чтобы система перед тем, как мне
отправлять сообщение, проверяла, не было ли оно только что уже отправлено».

Дедуп в проекте на тот момент ЖИЛ УЖЕ ЧЕТЫРЕ ДНЯ — его поставили 09.08 по РОВНО ТАКОЙ ЖЕ
жалобе («поток одинаковых сообщений всё утро, с этим невозможно работать»). Поставили в
``telegram_client._post_message``. А владелец получает через ВТОРУЮ дверь —
``TelegramBot.send_message``: ею шлёт ``notify_needs_owner`` (вопрос о решении) и все пуши
бота. Эта дверь взяла у заслона ровно половину:

* лимит потока  — есть (17.07);
* дедуп         — НЕТ;
* запись в историю — НЕТ ВОВСЕ.

Третий пункт и есть то, почему дефект прожил четыре дня незамеченным: в
``data/alert_history.json`` за 13.08 стояло **3 записи** против десятков реально
полученных. Вопрос «кто это шлёт владельцу» был неотвечаем ПО ПОСТРОЕНИЮ — тот же класс,
что `.claude/rules/deployment.md` разбирает на трёх вопросах доставки: сторож честно
отвечает на свой вопрос, а нужный не задаёт никто.

Каждый тест ниже — положительный контроль: он краснеет на коде ДО починки.

Отдельно проверяется обратная сторона. Дедуп не имеет права стать глухотой: почти все
вызовы ``TelegramBot.send_message`` — это ОТВЕТЫ на команду, кнопку или голосовое.
Владелец нажал `/status` дважды — обязан получить ответ дважды, иначе он справедливо
прочтёт молчание как поломку бота. Поэтому солиситированные ответы (а) не глушатся и
(б) записываются в историю помеченными, чтобы не глушить ЧУЖИЕ сообщения.

Сети здесь нет: транспорт (``_api_call``) подменён, наружу не уходит ничего.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from spa_core.alerts import telegram_client as tc
from spa_core.telegram import bot as B
from spa_core.tests._freshness import now_utc

NOW = now_utc()

# Тот самый вопрос, который владелец получал десятками раз (карточка сайта owner-gated).
OWNER_QUESTION = (
    "🧑‍⚖️ Нужно твоё решение: сайт /packages — автономная правка задела owner-gated область\n"
    "Варианты: 1 — одобрить · 2 — отклонить ⭐ · 3 — отложить"
)


@pytest.fixture(autouse=True)
def _guard_env(tmp_path, monkeypatch):
    """История и лимит — во временном дереве; дедуп и запись включены явно.

    Оба модуля глушат себя под pytest (``PYTEST_CURRENT_TEST``), чтобы прогон не писал в
    ЖИВОЕ состояние бота — на этом уже горели (карточка «прогон тестов писал в живые
    настройки Телеграм-бота»). Здесь мы снимаем глушилку адресно, на временных файлах.
    """
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setenv("SPA_ALERT_HISTORY_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE", tmp_path / "alert_history.json")
    monkeypatch.setattr(tc, "_RATE_STATE", tmp_path / ".telegram_rate.json")
    return tmp_path


def _history(path):
    try:
        return json.loads((path / "alert_history.json").read_text()).get("entries") or []
    except Exception:
        return []


def _seed(path, text, *, seconds_ago=0, ok=True, solicited=False):
    """Положить в историю одну отправку — как будто она была ``seconds_ago`` секунд назад."""
    entry = {"ts": (NOW - timedelta(seconds=seconds_ago)).isoformat(),
             "preview": text[:tc._PREVIEW_LEN], "ok": ok}
    if solicited:
        entry["solicited"] = True
    (path / "alert_history.json").write_text(json.dumps({"entries": [entry]}),
                                             encoding="utf-8")


class _Bot(B.TelegramBot):
    """Бот без сети и без Keychain: считает вызовы транспорта."""

    def __init__(self):  # noqa: D107 — namesake ctor ходит в Keychain
        self.token = "t"
        self.chat_id = "42"
        self.api_base = "https://example.invalid/bot"
        self._router = None
        self._last_status = None
        self.calls = []

    def _api_call(self, method, params=None, timeout=None):
        self.calls.append((method, params))
        return {"ok": True, "result": {"message_id": 100 + len(self.calls)}}


# ── ЖАЛОБА ВЛАДЕЛЬЦА: один и тот же вопрос десятками раз ────────────────────────────

def test_the_same_owner_question_within_the_window_is_not_sent_twice(_guard_env):
    """Ядро жалобы 13.08. До починки эта дверь дедупа не знала — уходили обе отправки."""
    bot = _Bot()
    assert bot.send_message(OWNER_QUESTION, dedup=True) is not None
    assert bot.send_message(OWNER_QUESTION, dedup=True) is None
    assert len(bot.calls) == 1, "второй одинаковый вопрос обязан быть погашен ДО транспорта"


def test_the_suppressed_repeat_is_named_in_the_history(_guard_env):
    """Молчаливое подавление неотличимо от поломки канала — причина обязана быть записана."""
    bot = _Bot()
    bot.send_message(OWNER_QUESTION, dedup=True)
    bot.send_message(OWNER_QUESTION, dedup=True)
    dropped = [e for e in _history(_guard_env) if e.get("error") == "duplicate_dropped"]
    assert len(dropped) == 1
    assert dropped[0]["ok"] is False


def test_notify_needs_owner_asks_for_dedup():
    """Проводка, а не деталь: заслон бесполезен, если зовущий его не включил.

    Урок «правь проводку, а не части»: один невызванный вызов оставил 1364 теста
    зелёными, пока фича была мертва в проде.
    """
    import inspect

    from spa_core.owner_queue import notify

    # Считаем по КОДУ, а не по тексту функции: комментарий, объясняющий dedup, тоже
    # содержит эти буквы, и тест, считающий их, мерил бы прозу.
    code = [ln.split("#", 1)[0] for ln in
            inspect.getsource(notify.notify_needs_owner).splitlines()]
    rungs = [ln for ln in code if "_send(" in ln and "def _send" not in ln]
    assert len(rungs) == 4, ("лестница деградации: кнопки+дедуп, дедуп, дедуп после "
                             f"отказа от кнопок, голая отправка — найдено {len(rungs)}")
    # ИЗМЕНЕНО ОСОЗНАННО (цикл #318, ADR-096; инв. #16 — обоснование здесь + журнал W34).
    # Было: `sum("dedup=True" in ln ...) == 3` — счёт ЛИТЕРАЛА в исходнике. С приходом
    # `owner_requested` (решение владельца 20.08: «пришлите вопросы заново») литерал стал
    # переменной `dedup = not owner_requested`, и тест покраснел на ВЕРНОМ коде: проводка
    # на месте, поведение по умолчанию прежнее, изменилась запись.
    #
    # Проверка не ослаблена, а РАСШИРЕНА, и намеренно в обе стороны:
    #   1) структурно — дедуп по-прежнему передаётся на всех ступенях, кроме нижней;
    #   2) ПОВЕДЕНЧЕСКИ (ниже) — по умолчанию до отправителя доезжает именно `True`.
    # Старая форма второго не проверяла вовсе: литерал `dedup=True` в мёртвой ветке
    # удовлетворил бы её полностью. Мутация `dedup = True → False` убивает новый тест и
    # НЕ убивала старый.
    assert sum("dedup=" in ln for ln in rungs) == 3, \
        f"дедуп обязан стоять на всех ступенях, кроме нижней: {rungs}"


def test_default_notification_really_arrives_with_dedup_on(tmp_path, monkeypatch):
    """Вторая половина проверки выше: ЧТО ДОЕХАЛО до отправителя, а не что написано.

    Заведена вместе с `owner_requested` (#318). Структурный счёт мерит запись в
    исходнике; этот тест мерит эффект — по умолчанию (владелец НИЧЕГО не просил) до
    двери приезжает `dedup=True`, то есть петля спама 09.08/13.08 закрыта по-прежнему.

    Анти-шторм здесь подменён СОЗНАТЕЛЬНО: он читает песочницу, общую на весь хост
    (`inbox-pesochnitsa-testov-obschaya-na-ves-host`), и без подмены тест краснел бы от
    чужого прогона за последние 6 часов, а не от проверяемого поведения.
    """
    from spa_core.owner_queue import notify as N

    card = tmp_path / "own-default.md"
    card.write_text(
        "---\ntrackerStatus:\n  type: owner-decision\n"
        "title: Тестовый вопрос\nstatus: needs-owner\n---\n\n"
        "## Что случилось и почему это важно\n\nНечто.\n\n"
        "## Что от тебя нужно\n\n* **Вариант 1 — да.**\n* **Вариант 2 — нет.**\n",
        encoding="utf-8")

    seen = {}

    class Sender:
        def send_message(self, text, parse_mode="HTML", **extra):
            seen.update(extra)
            seen["text"] = text
            return {"result": {"message_id": 1}}

    monkeypatch.setattr("spa_core.telegram.owner_decisions.throttle_state",
                        lambda *a, **k: (True, ""))
    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", Sender, raising=True)
    N.notify_needs_owner(card)
    assert seen.get("text"), "уведомление обязано дойти"
    assert seen.get("dedup") is True, \
        "без просьбы владельца дедуп обязан доехать до двери включённым"


def test_a_sender_without_buttons_still_gets_the_dedup(tmp_path, monkeypatch):
    """Средняя ступень лестницы: кнопок не знает, дедуп знает — дедуп терять НЕ обязаны.

    Нижнюю ступень (не знает ничего, но доставляет) держит
    ``test_owner_decisions_wiring.py::test_notification_reaches_a_sender_that_knows_
    nothing_about_buttons`` — тот самый тест, на котором цикл #215 справедливо покраснел,
    когда добавил ``dedup`` в нижнюю ступень. Здесь проверяется РОВНО то, чего он не
    проверяет: что откат по кнопкам не выплёскивает вместе с ними дедуп.
    """
    from spa_core.owner_queue import notify as N

    card = tmp_path / "own-test.md"
    card.write_text(
        "---\ntrackerStatus:\n  type: owner-decision\n"
        "title: Тестовый вопрос\nstatus: needs-owner\n---\n\n"
        "## Что случилось и почему это важно\n\nНечто.\n\n"
        "## Что от тебя нужно\n\n* **Вариант 1 — да.**\n* **Вариант 2 — нет.**\n",
        encoding="utf-8")

    seen = {}

    class MidSender:
        """Знает dedup, не знает reply_markup."""

        def send_message(self, text, parse_mode="HTML", dedup=False):
            seen["dedup"] = dedup
            seen["text"] = text
            return {"ok": True}

    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", MidSender, raising=True)
    N.notify_needs_owner(card)
    assert seen.get("text"), "уведомление обязано дойти"
    assert seen.get("dedup") is True, "откат по кнопкам не имеет права уронить дедуп"


# ── ОБРАТНАЯ СТОРОНА: дедуп не имеет права стать глухотой ───────────────────────────

def test_a_reply_to_the_owner_is_never_suppressed(_guard_env):
    """Владелец нажал `/status` дважды — ответ обязан прийти дважды.

    Это и есть причина, по которой ``dedup`` здесь по умолчанию ВЫКЛЮЧЕН: почти все
    вызовы этой двери — ответы на действие владельца.
    """
    bot = _Bot()
    assert bot.send_message("📊 Portfolio: $100 865") is not None
    assert bot.send_message("📊 Portfolio: $100 865") is not None
    assert len(bot.calls) == 2


def test_a_solicited_reply_does_not_mute_a_real_alert(_guard_env):
    """Ответ на команду не должен глушить ТРЕВОГУ с тем же текстом.

    Поэтому солиситированные записи в историю попадают (иначе «кто шлёт» опять слепнет),
    но повтором не считаются.
    """
    _seed(_guard_env, OWNER_QUESTION, seconds_ago=60, solicited=True)
    assert tc._duplicate_recently(OWNER_QUESTION) is False


def test_bot_chatter_cannot_wash_a_push_out_of_the_dedup_window(_guard_env):
    """Риск, который создаёт САМА эта починка, — и он закрыт здесь.

    С #215 в историю пишет и бот, включая ответы на команды. Бот разговорчив: если бы
    окно дедупа считалось «последние 60 записей подряд», полсотни нажатий владельца
    вытолкнули бы настоящий пуш из поля зрения за минуты — и наблюдение, добавленное
    ради дедупа, ослабило бы дедуп.
    """
    entries = [{"ts": (NOW - timedelta(seconds=120)).isoformat(),
                "preview": OWNER_QUESTION[:tc._PREVIEW_LEN], "ok": True}]
    entries += [{"ts": (NOW - timedelta(seconds=60)).isoformat(),
                 "preview": f"📊 ответ на команду {i}", "ok": True, "solicited": True}
                for i in range(200)]
    (_guard_env / "alert_history.json").write_text(json.dumps({"entries": entries}),
                                                   encoding="utf-8")
    assert tc._duplicate_recently(OWNER_QUESTION) is True, \
        "болтовня бота не имеет права вымыть пуш из окна дедупа"


def test_a_different_question_always_passes(_guard_env):
    """Изменился текст — изменился факт. Гасится только побуквенный повтор."""
    bot = _Bot()
    bot.send_message(OWNER_QUESTION, dedup=True)
    assert bot.send_message(OWNER_QUESTION.replace("/packages", "/dashboard"),
                            dedup=True) is not None
    assert len(bot.calls) == 2


def test_the_same_question_after_the_window_passes_again(_guard_env):
    """Окно, а не вечный запрет: вопрос, оставшийся без ответа полчаса, снова уместен."""
    _seed(_guard_env, OWNER_QUESTION, seconds_ago=tc.DUPLICATE_WINDOW_S + 60)
    bot = _Bot()
    assert bot.send_message(OWNER_QUESTION, dedup=True) is not None


# ── НЕВИДИМОСТЬ: почему дефект прожил четыре дня ────────────────────────────────────

def test_every_bot_send_is_written_to_the_history(_guard_env):
    """До починки эта дверь не писала НИЧЕГО — и «кто это шлёт» было не спросить.

    Замер 13.08: 3 записи за день против десятков полученных владельцем.
    """
    bot = _Bot()
    bot.send_message("🎤 Слушаю…")
    bot.send_message(OWNER_QUESTION, dedup=True)
    entries = _history(_guard_env)
    assert len(entries) == 2, "в историю обязана попасть КАЖДАЯ отправка, а не только пуши"
    assert [e.get("solicited") for e in entries] == [True, None], \
        "ответ владельцу помечается солиситированным, пуш — нет"


def test_a_failed_send_is_recorded_as_failed(_guard_env):
    """Неудачную отправку нельзя записывать успехом — иначе она погасит повтор."""
    bot = _Bot()
    bot._api_call = lambda *a, **k: None  # транспорт лёг
    bot.send_message(OWNER_QUESTION, dedup=True)
    entries = _history(_guard_env)
    assert len(entries) == 1 and entries[0]["ok"] is False
    # и повтор обязан пройти: молчание канала — не повод молчать дальше
    assert tc._duplicate_recently(OWNER_QUESTION) is False


# ── ОДИН ЗАСЛОН НА ОБЕ ДВЕРИ ────────────────────────────────────────────────────────

def test_both_doors_call_one_and_the_same_guard():
    """Половину защиты взять нельзя — иначе мы чиним дверь, в которую владелец не ходит.

    Ровно это и произошло 09.08 → 13.08: дедуп поставили в ``_post_message``, а жалоба
    пришла снова, теми же словами, потому что вторая дверь его не знала.
    """
    import inspect

    assert "guard_outbound" in inspect.getsource(tc._post_message)
    assert "guard_outbound" in inspect.getsource(B.TelegramBot.send_message)


def test_the_guard_reports_the_reason_it_refused(_guard_env):
    """``guard_outbound`` возвращает ПРИЧИНУ, а не булево: отказ обязан быть назван."""
    assert tc.guard_outbound(OWNER_QUESTION) is None
    _seed(_guard_env, OWNER_QUESTION, seconds_ago=60)
    assert tc.guard_outbound(OWNER_QUESTION) == "duplicate_dropped"
    assert tc.guard_outbound(OWNER_QUESTION, dedup=False) is None


def test_an_unreadable_history_never_suppresses(_guard_env):
    """Сомнение → отправляем. «Проверить не смогли» не имеет права стать молчанием."""
    (_guard_env / "alert_history.json").write_text("{не json", encoding="utf-8")
    assert tc.guard_outbound(OWNER_QUESTION) is None
