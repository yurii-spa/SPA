"""Поток одинаковых вопросов владельцу: свойство сообщения старше слов отправителя.

Жалоба владельца 17.08, дословно: «мне в телеграм пишут раз по 200 в день одно и то же
сообщение, и без вариантов кнопок». Это ТРЕТЬЯ жалоба теми же словами (09.08, 13.08,
17.08), и каждый раз чинилась дверь, в которую поток не шёл.

Механика, воспроизведённая замером, — самоподдерживающаяся петля из двух половин:

1. ``TelegramBot.send_message`` принимает ``dedup`` ПАРАМЕТРОМ со значением по
   умолчанию ``False``. Отправитель, который параметра не знает (старая сигнатура ⇒
   ``TypeError`` ⇒ нижняя ступень лестницы деградации в ``notify_needs_owner``),
   отправляет БЕЗ дедупа. Прежний комментарий на этой ступени звучал «лишний повтор
   владелец переживёт» — верно для одного повтора и неверно для потока.
2. Хуже: ``_record_history`` пишет ``solicited = not dedup``, то есть помечает такой
   вопрос как «владелец сам его попросил». А ``_duplicate_recently`` берёт в кандидаты
   ТОЛЬКО не солиситированные записи — поэтому поток помечал сам себя невидимым для
   дедупа, который обязан был его остановить. Шесть побуквенно одинаковых вопросов
   подряд давали шесть отправок и НОЛЬ кандидатов.

Починка не добавляет ещё один флаг, а перестаёт верить вызывающему: сообщение,
ПРЕДЛАГАЮЩЕЕ ВЫБОР, ответом на команду владельца быть не может по построению, и это уже
измеряется в дверях (``offers_choice``, цикл #229).

Почему это не глушит ответы владельцу — отдельный тест ниже: ``solicited`` влияет только
на СОСТАВ кандидатов, а сам дедуп спрашивается лишь при ``dedup=True``; ответ на команду
уходит с ``dedup=False`` и не подавляется ничем.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.alerts import telegram_client as tc

PUSH_TEXT = (
    "🧑‍⚖️ Нужно твоё решение\n\n"
    "Сайт: packages.astro — автономная правка задела owner-gated область, нужно решение\n\n"
    "Варианты:\n1. Одобрить\n2. Отклонить ⭐ рекомендую\n3. Отложить"
)


@pytest.fixture()
def door(tmp_path, monkeypatch):
    """Живые заслон и журнал, уведённые в песочницу; проверки включены явно."""
    monkeypatch.setattr(tc, "_HISTORY_STATE", tmp_path / "alert_history.json")
    monkeypatch.setattr(tc, "_RATE_STATE", tmp_path / "tg_rate.json")
    # Обе проверки под pytest выключены by design — включаем их именно здесь.
    monkeypatch.setenv("SPA_ALERT_HISTORY_TEST", "1")
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.delenv("SPA_TELEGRAM_DUP_WINDOW_S", raising=False)
    return tmp_path


def _entries(door_dir: Path) -> list[dict]:
    p = door_dir / "alert_history.json"
    if not p.exists():
        return []
    doc = json.loads(p.read_text())
    return doc.get("entries") or []


def _send(text: str, *, dedup: bool) -> str:
    """Одна отправка через настоящий заслон; возвращает 'SENT' или причину отказа."""
    reason = tc.guard_outbound(text, dedup=dedup)
    if reason is not None:
        return reason
    tc._record_history(text, ok=True, message_id=1, solicited=not dedup, buttons=False)
    return "SENT"


# ── петля, из-за которой владелец получал 200 сообщений в сутки ───────────────


def test_a_push_never_marks_itself_as_asked_for_by_the_owner(door):
    """Ядро аварии: вопрос с вариантами не имеет права записаться как солиситированный.

    Положительный контроль: снять условие ``not entry.get("offers_choice")`` в
    ``_record_history`` — и этот тест краснеет, потому что запись снова объявляет себя
    просьбой владельца и выпадает из кандидатов дедупа.
    """
    _send(PUSH_TEXT, dedup=False)  # старый отправитель: dedup передать нечем

    recs = _entries(door)
    assert len(recs) == 1
    assert recs[0].get("offers_choice") is True, "измерение выбора обязано попасть в журнал"
    assert "solicited" not in recs[0], (
        "вопрос с вариантами записан как ответ на команду владельца — "
        "именно так поток и прятался от собственного дедупа"
    )


def test_the_flood_becomes_visible_to_the_dedup_that_must_stop_it(door):
    """Шесть одинаковых вопросов от отправителя без дедупа ⇒ шесть КАНДИДАТОВ.

    Тест не про подавление (отправитель дедупа не спрашивает — подавлять некому), а про
    то, что поток перестал быть невидимым: следующий же вызов, который заслон СПРОСИТ,
    найдёт совпадение. До починки кандидатов было ноль при шести записях.
    """
    for _ in range(6):
        assert _send(PUSH_TEXT, dedup=False) == "SENT"

    recs = _entries(door)
    candidates = [r for r in recs if r.get("ok") and not r.get("solicited")]
    assert len(recs) == 6
    assert len(candidates) == 6, f"поток невидим для дедупа: {len(candidates)} из {len(recs)}"

    # И сразу же: первый спросивший заслон получает отказ — петля разорвана.
    assert tc.guard_outbound(PUSH_TEXT, dedup=True) == "duplicate_dropped"


def test_bottom_rung_of_the_ladder_asks_the_guard_itself(door, monkeypatch, tmp_path):
    """Отправитель со СТАРОЙ сигнатурой больше не проносит поток мимо заслона.

    Положительный контроль реальной ступени: до починки нижняя ветка
    ``notify_needs_owner`` звала голую отправку, и второй побуквенно одинаковый вопрос
    уезжал владельцу. Теперь заслон спрашивается на стороне вызывающего — там, где ТОЧНО
    известно, что это пуш.
    """
    from spa_core.owner_queue import notify as N

    card = tmp_path / "owner-decision-sait-packages-astro.md"
    card.write_text(
        "---\ntrackerStatus:\n  type: owner-decision\n"
        "title: \"Сайт: packages.astro — автономная правка задела owner-gated область\"\n"
        "status: needs-owner\n---\n\n"
        "## Что от тебя нужно\n\n1. **Одобрить**\n2. **Отклонить (рекомендую)**\n"
        "3. **Отложить**\n",
        encoding="utf-8",
    )

    sent: list[str] = []

    class OldSender:
        """Ни `reply_markup`, ни `dedup` — ровно то, что стоит в проде долгожителем."""

        def send_message(self, text, parse_mode="HTML"):
            sent.append(text)
            return {"ok": True}

    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", OldSender, raising=True)

    N.notify_needs_owner(card)
    N.notify_needs_owner(card)

    assert len(sent) == 1, (
        f"побуквенно одинаковый вопрос уехал владельцу {len(sent)} раза — "
        "нижняя ступень снова потеряла дедуп"
    )


# ── обратный контроль: ответы владельцу глушить нельзя ────────────────────────


def test_an_answer_to_the_owners_command_is_never_suppressed(door):
    """Владелец спросил дважды — обязан получить ответ дважды.

    Это и есть цена, которую починка не имеет права заплатить: ``solicited`` влияет
    ТОЛЬКО на состав кандидатов, а подавление спрашивается лишь при ``dedup=True``.
    """
    reply = "📊 Портфель: $100 910.66 · deployed 90 % · cash 10 %"
    for _ in range(5):
        assert _send(reply, dedup=False) == "SENT"
    assert len(_entries(door)) == 5


def test_a_choice_free_alert_still_keeps_the_solicited_mark(door):
    """Сужение починки: без вариантов запись помечается как прежде.

    Иначе ответ на `/status` попал бы в кандидаты и заглушил бы НАСТОЯЩУЮ тревогу с тем
    же текстом — ровно тот дефект, ради которого признак ``solicited`` и заведён.
    """
    plain = "✅ Телеграм-бот снова работает"
    _send(plain, dedup=False)

    recs = _entries(door)
    assert recs[0].get("offers_choice") is False
    assert recs[0].get("solicited") is True


def test_a_different_question_passes_immediately(door):
    """Дедуп гасит ПОБУКВЕННО тот же текст и ничего сверх — эскалация проходит сразу."""
    assert _send(PUSH_TEXT, dedup=True) == "SENT"
    assert tc.guard_outbound(PUSH_TEXT, dedup=True) == "duplicate_dropped"

    other = PUSH_TEXT.replace("packages.astro", "index.astro")
    assert tc.guard_outbound(other, dedup=True) is None, (
        "другой вопрос подавлен как повтор — дедуп превратился в глушилку"
    )


# ── вторая половина жалобы: «без вариантов кнопок» ───────────────────────────


def test_buttonless_notice_does_not_promise_what_the_same_bot_cannot_do(tmp_path):
    """Обещание «ответь номером, я разберу» стояло на НЕПОДТВЕРЖДЁННОЙ способности.

    Кнопки снимаются ровно тогда, когда маячок бота не подтверждён (fail-CLOSED, ADR-069).
    Но текстовый ответ разбирает ТОТ ЖЕ бот — значит за него ручаться нечем, и владелец,
    написавший «2», не получал ничего. Fail-CLOSED снимал кнопки и тут же выдавал вместо
    них непроверенную гарантию.

    Положительный контроль: вернуть прежнюю фразу — тест краснеет.
    """
    from spa_core.telegram import owner_decisions as od

    body = ("## Что от тебя нужно\n\n1. **Одобрить**\n"
            "2. **Отклонить (рекомендую)**\n3. **Отложить**\n")
    beacon = tmp_path / "no_such_beacon.json"  # маячка нет ⇒ способность не подтверждена

    prep = od.prepare("Сайт: packages.astro — правка задела owner-gated область",
                      body, "own-packages-astro", card_name="own-packages-astro.md",
                      beacon_path=beacon)

    assert prep.keyboard is None, "маячка нет — кнопок быть не должно"
    text = prep.text
    assert "Кнопки сейчас недоступны" in text
    assert "я разберу" not in text, (
        "текст ручается за разбор ответа тем же ботом, который только что не подтвердил "
        "способность — обещание несуществующего"
    )
    assert "ручаться за это нельзя" in text, "оговорка про того же бота исчезла"
    # И называет путь, который работает БЕЗ бота вообще.
    assert "статус карточки" in text
