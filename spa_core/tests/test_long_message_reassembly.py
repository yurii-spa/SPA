"""Длинный документ владельца обязан приезжать ОДНОЙ карточкой, а не N сиротами.

Авария, которую здесь воспроизводит каждый положительный контроль, — **13.08.2026**:
владелец прислал в Телеграм спецификацию «TASK — Portfolio CIO: Dynamic Capital Allocation
& Rebalancing», и интейк завёл **семь** карточек за 21 секунду. Шесть из семи — не задания,
а куски: заголовки разделов («WHY IT EXISTS», «actual costs») и обрывки предложений
(«если тот же target можно приблизить простым:»).

Замер длин тел этих семи карточек (цикл #306):

    4088 · 4085 · 4086 · 4087 · 4080 · 4062 · 3346

Шесть из семи стоят вплотную к пределу Bot API в 4096 символов ⇒ резал НЕ наш код: клиент
Телеграма разбил ОДИН документ на семь сообщений. Отсюда признак — позиционный, не смысловой:
сообщение у предела означает «дальше есть ещё».

Проверяется ЭФФЕКТ (сколько карточек родилось и что увидел владелец), а не возвращаемые
значения. Сети здесь нет. Время — вход: всё, что судит о свежести буфера, принимает ``now``.
"""

from __future__ import annotations

import types

import pytest

from spa_core.telegram import bot as B
from spa_core.telegram import long_message as lm

#: Первые строки СЕМИ настоящих кусков 13.08 — в том порядке, в каком они приехали.
#: Ровно они стали заголовками семи карточек-сирот.
REAL_FIRST_LINES = [
    "TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing",
    "actual costs",
    "APY Persistence / Confidence",
    "100 запусков на одном snapshot.",
    "Для каждого этапа показать:",
    "если тот же target можно приблизить простым:",
    "WHY IT EXISTS",
]
#: Длины тех же семи кусков, замер по карточкам.
REAL_PART_LENGTHS = [4088, 4085, 4086, 4087, 4080, 4062, 3346]


def _part(first_line: str, total_len: int) -> str:
    """Кусок документа: своя первая строка + добивка до измеренной длины по границам строк."""
    filler_line = "строка тела документа, разбираемая оркестратором позже"
    out = [first_line]
    while len("\n".join(out)) + 1 + len(filler_line) <= total_len:
        out.append(filler_line)
    text = "\n".join(out)
    return text + "." * (total_len - len(text))


def real_document_parts() -> list[str]:
    """Семь сообщений 13.08 в их измеренных длинах."""
    return [_part(line, n) for line, n in zip(REAL_FIRST_LINES, REAL_PART_LENGTHS)]


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    """Буфер сборщика — ТОЛЬКО в песочнице: прогон теста не смеет писать в живой data/."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert lm.store_path().parent == tmp_path, "буфер уехал бы в живое дерево"
    return tmp_path


@pytest.fixture()
def wired(monkeypatch, sandbox):
    """Бот без Keychain/сети: перехват карточек (обоих видов) и сообщений владельцу."""
    cards: list[tuple[str, str]] = []   # (вид, текст) — вид: task | document
    sent: list[str] = []

    monkeypatch.setattr(B, "get_token", lambda: "T", raising=False)
    monkeypatch.setattr(B, "get_chat_id", lambda: "42", raising=False)
    bot = B.TelegramBot(token="T", chat_id="42")
    monkeypatch.setattr(bot, "send_message", lambda text, *a, **k: sent.append(text))
    monkeypatch.setattr(bot, "_get_router",
                        lambda: types.SimpleNamespace(is_owner=lambda cid: True))

    from spa_core.telegram import inbox_intake as II

    monkeypatch.setattr(II, "save_inbox_task",
                        lambda text, source="telegram", transcript=None:
                        (cards.append(("task", text)), (sandbox / "c.md", "Заголовок"))[1])
    # raising=False: на НЕИСПРАВЛЕННОМ origin такой функции нет вовсе — и тест обязан
    # краснеть на ЧИСЛЕ карточек (7 против 1), а не на отсутствии атрибута.
    monkeypatch.setattr(II, "save_inbox_document",
                        lambda text, provenance, source="telegram":
                        (cards.append(("document", text)), (sandbox / "d.md", "Заголовок"))[1],
                        raising=False)

    # Классификатор: свободный текст = задача. Сети и `claude` здесь нет.
    from spa_core.telegram import ask_router
    monkeypatch.setattr(ask_router, "classify_and_answer", lambda text: ("task", ""))
    # Разбор ответа владельца по умолчанию говорит «это не ответ».
    from spa_core.telegram import owner_decisions as od
    monkeypatch.setattr(od, "resolve_text_answer", lambda text, chat_id: None)

    return types.SimpleNamespace(bot=bot, cards=cards, sent=sent)


def _deliver(wired, parts: list[str]) -> None:
    """Прогнать сообщения через ЖИВОЙ интейк бота, как их отдаёт getUpdates."""
    for text in parts:
        wired.bot._handle_inbox_intake({"text": text}, text, "42")


# ── Положительный контроль: сама авария 13.08 ────────────────────────────────

def test_the_real_document_of_13_08_becomes_one_card_not_seven(wired):
    """АНКЕР. Семь сообщений владельца → ОДНА карточка.

    На неисправленном дереве здесь ровно семь карточек — это и есть авария 13.08.
    """
    _deliver(wired, real_document_parts())

    assert len(wired.cards) == 1, (
        f"документ владельца распался на {len(wired.cards)} карточек с заголовками "
        f"{[t.splitlines()[0] for _k, t in wired.cards]}"
    )
    kind, text = wired.cards[0]
    assert kind == "document", "документ обязан ехать своим путём, с происхождением в теле"
    for line in REAL_FIRST_LINES:
        assert line in text, f"кусок {line!r} потерян при сборке"


def test_the_parts_are_joined_in_arrival_order(wired):
    """Порядок частей сохранён: документ читается сверху вниз, а не вперемешку."""
    _deliver(wired, real_document_parts())

    text = wired.cards[0][1]
    positions = [text.index(line) for line in REAL_FIRST_LINES]
    assert positions == sorted(positions), (
        "части склеены не в порядке прихода — документ восстановлен неверно")


def test_no_card_title_is_a_fragment_of_a_sentence(wired):
    """Ни одна карточка не имеет заголовком обрывок предложения.

    Критерий приёмки исходной карточки дословно: прогон интейка на этом самом документе
    не порождает карточек с заголовком-обрывком.
    """
    _deliver(wired, real_document_parts())

    titles = [t.splitlines()[0].strip() for _k, t in wired.cards]
    assert titles == [REAL_FIRST_LINES[0]], (
        f"в очередь уехали заголовки-обрывки: {titles}")


def test_the_owner_is_told_once_at_the_start_and_once_at_the_end(wired):
    """Владелец слышит ДВА сообщения на документ, а не по одному на каждую часть.

    Ответить на длинный документ семью «📥 добавил в inbox» — это ровно тот поток
    одинаковых сообщений, на который он жаловался (#215/#217/#228).
    """
    _deliver(wired, real_document_parts())

    assert len(wired.sent) == 2, f"владелец получил {len(wired.sent)} сообщений: {wired.sent}"
    assert "жду продолжение" in wired.sent[0]
    assert "7" in wired.sent[1], f"итог обязан назвать число собранных частей: {wired.sent[1]}"


def test_the_card_body_carries_how_it_arrived(wired):
    """Происхождение записано машиной: из скольких частей и почему сборка закрыта.

    Без этой строки связь частей восстановима только памятью человека — исходная
    жалоба карточки («порядок и связь потеряны безвозвратно»).
    """
    captured: list[str] = []
    from spa_core.telegram import inbox_intake as II
    orig = II.save_inbox_document

    def _spy(text, provenance, source="telegram"):
        captured.append(provenance)
        return orig(text, provenance, source)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(II, "save_inbox_document", _spy)
        _deliver(wired, real_document_parts())

    assert len(captured) == 1
    assert "7" in captured[0], captured[0]
    assert str(lm.TELEGRAM_MAX_CHARS) in captured[0], captured[0]


# ── Обратные контроли: обычная переписка не тронута ──────────────────────────

def test_a_short_message_takes_the_ordinary_path_untouched(wired):
    """Короткое сообщение сборщик не трогает вовсе — обычная задача, как и раньше."""
    _deliver(wired, ["почини график на дашборде"])

    assert wired.cards == [("task", "почини график на дашборде")], wired.cards
    assert len(wired.sent) == 1 and "inbox" in wired.sent[0].lower()


def test_an_owner_answer_is_not_swallowed_by_an_open_buffer(wired, monkeypatch):
    """«Ответ 1» доходит до разбора решений, даже когда буфер документа открыт.

    Инвариант #14 держится на том, что слово владельца доходит; открытый буфер не имеет
    права его съесть. Документ при этом закрывается тем, что уже собрано.
    """
    seen: list[str] = []
    from spa_core.telegram import owner_decisions as od
    monkeypatch.setattr(od, "resolve_text_answer",
                        lambda text, chat_id: (seen.append(text), None)[1])

    _deliver(wired, [real_document_parts()[0], "Ответ 1"])

    assert seen == ["Ответ 1"], f"ответ владельца до разбора решений не дошёл: {seen}"
    docs = [t for kind, t in wired.cards if kind == "document"]
    assert len(docs) == 1, "документ обязан закрыться тем, что уже собрано"
    assert "Ответ 1" not in docs[0], "решение владельца приклеилось к телу документа"


@pytest.mark.parametrize("text,expected", [
    ("1", True), ("Ответ 1", True), ("ответ 2.", True), ("вариант 3", True),
    ("Option 1", True), ("11", True),
    ("1. Реализовать deterministic portfolio optimization", False),
    ("почини сайт", False), ("", False),
])
def test_owner_answer_shape_is_narrow(text, expected):
    """Форма ответа владельца узкая: пункт списка «1. Реализовать…» ответом НЕ считается."""
    assert lm.looks_like_owner_answer(text) is expected


# ── Проводка: сборщик обязан быть ПОДКЛЮЧЁН, а не просто написан ─────────────

def test_the_poll_loop_flushes_pending_documents(wired, monkeypatch):
    """Такт опроса обязан звать выдачу протухших буферов.

    Проверяется ПРОВОДКА, а не деталь: удалённый вызов оставил бы все остальные тесты
    зелёными (они зовут `flush_expired` напрямую), а придержанный кусок владельца ждал бы
    следующего его сообщения — то есть, возможно, вечно. Ровно этот класс уже стоил нам
    цикла: «одна удалённая точка вызова оставила 1364 теста зелёными».
    """
    calls: list[int] = []
    monkeypatch.setattr(wired.bot, "_flush_pending_documents", lambda: calls.append(1))
    monkeypatch.setattr(wired.bot, "_api_call",
                        lambda method, params=None: {"ok": True, "result": []})

    wired.bot.get_updates()

    assert calls == [1], "успешный такт опроса не зовёт выдачу придержанных документов"


def test_a_restart_does_not_need_a_new_message_to_release_the_document(wired, monkeypatch):
    """Придержанный кусок уезжает карточкой САМ, без нового сообщения владельца.

    Сквозной контроль поверх предыдущего: буфер открыт, владелец молчит, приходит только
    пустой такт опроса — и документ обязан уехать.
    """
    head = real_document_parts()[0]
    lm.offer("42", head, now=1000.0)
    monkeypatch.setattr(lm, "WINDOW_S", -1.0)  # окно уже истекло
    monkeypatch.setattr(wired.bot, "_api_call",
                        lambda method, params=None: {"ok": True, "result": []})

    wired.bot.get_updates()

    assert [k for k, _t in wired.cards] == ["document"], (
        f"молчание владельца оставило его документ в буфере: {wired.cards}")


# ── Свойства сборщика: время — вход, потери нет ──────────────────────────────

def test_a_message_at_the_limit_is_held_and_a_short_one_is_not(sandbox):
    """Признак продолжения — длина, и он стоит ниже самого короткого замера (4062)."""
    assert lm.looks_truncated("x" * lm.CONTINUATION_MIN_CHARS)
    assert lm.looks_truncated("x" * min(REAL_PART_LENGTHS[:-1]))
    assert not lm.looks_truncated("x" * (lm.CONTINUATION_MIN_CHARS - 1))
    assert lm.CONTINUATION_MIN_CHARS < min(REAL_PART_LENGTHS[:-1]), (
        "порог обязан лежать НИЖЕ измеренного минимума, иначе настоящий кусок не опознан")


def test_a_held_part_is_emitted_when_the_continuation_never_comes(sandbox):
    """Продолжение не пришло ⇒ собранное уезжает САМО. Задержка, но не потеря."""
    head = real_document_parts()[0]
    emits, hold, passthrough = lm.offer("42", head, now=1000.0)
    assert emits == [] and hold is not None and passthrough is False

    assert lm.flush_expired(now=1000.0 + lm.WINDOW_S - 1) == [], "окно ещё не истекло"
    late = lm.flush_expired(now=1000.0 + lm.WINDOW_S + 1)
    assert [e.parts for e in late] == [1]
    assert late[0].reason == "expired"
    assert head in late[0].text
    assert lm.flush_expired(now=1e9) == [], "второй раз тот же документ ехать не должен"


def test_a_held_part_survives_a_process_restart(sandbox):
    """Буфер лежит на ДИСКЕ: перезапуск бота придержанный кусок не теряет.

    Куски в памяти процесса означали бы, что документ владельца исчезает при штатной
    самопочинке бота (14 перезапусков за день — измеренная норма, ADR-084).
    """
    head = real_document_parts()[0]
    lm.offer("42", head, now=1000.0)

    assert lm.store_path().exists(), "придержанный кусок нигде не сохранён"
    recovered = lm.flush_expired(now=1000.0 + lm.WINDOW_S + 1)  # «новый процесс»
    assert len(recovered) == 1 and head in recovered[0].text


def test_a_stale_buffer_does_not_glue_itself_to_the_next_message(sandbox):
    """Протухший буфер уезжает сам, а новое сообщение разбирается с чистого листа."""
    head = real_document_parts()[0]
    lm.offer("42", head, now=1000.0)

    emits, hold, passthrough = lm.offer("42", "почини график", now=1000.0 + lm.WINDOW_S + 1)
    assert [e.reason for e in emits] == ["expired"]
    assert head in emits[0].text and "почини график" not in emits[0].text
    assert hold is None and passthrough is True, "новое сообщение обязано идти обычным путём"


def test_two_chats_do_not_mix(sandbox):
    """Буферы разных чатов независимы."""
    a, b = real_document_parts()[0], real_document_parts()[1]
    lm.offer("42", a, now=1000.0)
    lm.offer("77", b, now=1000.0)
    emits, _hold, _pt = lm.offer("42", "хвост первого", now=1001.0)
    assert len(emits) == 1 and a in emits[0].text and b not in emits[0].text


def test_an_endless_stream_is_capped_instead_of_buffering_forever(sandbox):
    """Поток кусков упирается в потолок и уезжает, а не растёт без конца."""
    part = "x" * lm.CONTINUATION_MIN_CHARS
    emitted = []
    for i in range(lm.MAX_PARTS + 1):
        emits, _hold, _pt = lm.offer("42", part, now=1000.0 + i)
        emitted += emits
    assert [e.reason for e in emitted] == ["capped"]
    assert emitted[0].parts == lm.MAX_PARTS


def test_joining_never_welds_two_lines_into_one():
    """Склейка не теряет границу строки — в структурированном документе это дороже лишней."""
    assert lm.join_parts(["a", "b"]) == "a\nb"
    assert lm.join_parts(["a\n", "b"]) == "a\nb", "перевод строки не удваивается"
    assert lm.join_parts(["a", "\nb"]) == "a\nb"
    assert lm.join_parts(["один"]) == "один"
