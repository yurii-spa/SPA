"""Положительный контроль: длинный документ владельца — ОДНА карточка, а не семь сирот.

Авария (замер #215, 13.08.2026 13:10Z). Владелец прислал в Телеграм спецификацию
«TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing». Telegram НЕ УМЕЕТ
доставить сообщение длиннее ~4096 символов — клиент сам рубит текст на куски и шлёт
их подряд. Бот получил семь независимых сообщений за 21 секунду и завёл СЕМЬ карточек;
шесть из них — обрывки на полуслове («если тот же target можно приблизить простым:»,
«Для каждого этапа показать:»), то есть задания, которых владелец не давал. Протокол
велит брать по одной карточке за цикл — следующая сессия исполняла бы половину
предложения без документа, из которого её вырвали.

Длины живых семи кусков (замерены по карточкам на диске): 4088, 3346, 4085, 4062,
4086, 4080, 4087 символов при лимите Telegram 4096 — фикстура ниже воспроизводит
ровно эту форму.

Время — ВХОД (`now=`), а не окружение: и отметки частей, и «сейчас» задаёт тест,
поэтому он не зависит от календаря (`.claude/rules/deployment.md`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from spa_core.owner_queue.queue import list_cards, load_card
from spa_core.telegram import inbox_intake

# Начало документа и первые строки шести последующих кусков — дословно те, что стали
# заголовками шести карточек-сирот 13.08.
_FIRST_LINE = "TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing"
_FRAGMENT_HEADS = [
    "WHY IT EXISTS",
    "actual costs",
    "APY Persistence / Confidence",
    "100 запусков на одном snapshot.",
    "Для каждого этапа показать:",
    "если тот же target можно приблизить простым:",
]
_FILLER = ("Ребалансировка выполняется только в рамках потолков RiskPolicy v1.0, "
           "с учётом стоимости переключения и гистерезиса. ")


def _part(head: str, target_len: int) -> str:
    """Кусок документа: первая строка + наполнитель до длины, на которой рубит транспорт."""
    body = head + "\n"
    while len(body) < target_len:
        body += _FILLER
    return body[:target_len]


def _document_parts() -> list[str]:
    lengths = [4088, 3346, 4085, 4062, 4086, 4080, 4087]
    heads = [_FIRST_LINE] + _FRAGMENT_HEADS
    return [_part(h, n) for h, n in zip(heads, lengths)]


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    """Изолированный каталог карточек — на живой трекер тест не смотрит и в него не пишет."""
    from spa_core.owner_queue import queue as q

    monkeypatch.setattr(q, "TRACKER_DIR", tmp_path)
    return tmp_path


def test_owner_long_document_becomes_one_card(tracker):
    """Семь кусков ОДНОГО сообщения = одна карточка; обрывков-заголовков нет."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    parts = _document_parts()
    for i, part in enumerate(parts):
        inbox_intake.save_inbox_task(part, source="telegram",
                                     now=t0 + timedelta(seconds=3 * i), tracker_dir=tracker)

    cards = list_cards(tracker_type="inbox", tracker_dir=tracker)
    titles = [c.title for c in cards]
    assert len(cards) == 1, f"документ разрезан на {len(cards)} карточек: {titles}"

    card = cards[0]
    assert card.title.startswith("TASK — Portfolio CIO")
    for head in _FRAGMENT_HEADS:
        assert head not in titles, f"обрывок «{head}» стал отдельным заданием"
        assert head in card.body, f"часть «{head}» потеряна при склейке"
    assert card.fields.get("intake_parts") == "7"


def test_two_separate_short_tasks_stay_two_cards(tracker):
    """Обратная сторона: два коротких поручения подряд НЕ склеиваются в одно."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    inbox_intake.save_inbox_task("проверь дашборд", source="telegram",
                                 now=t0, tracker_dir=tracker)
    inbox_intake.save_inbox_task("купить зонт в пятницу", source="telegram",
                                 now=t0 + timedelta(seconds=10), tracker_dir=tracker)
    assert len(list_cards(tracker_type="inbox", tracker_dir=tracker)) == 2


def test_late_message_after_long_one_is_a_new_card(tracker):
    """Пришло ПОЗЖЕ окна — это уже другой разговор, а не хвост документа."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    inbox_intake.save_inbox_task(_part(_FIRST_LINE, 4088), source="telegram",
                                 now=t0, tracker_dir=tracker)
    inbox_intake.save_inbox_task("проверь дашборд", source="telegram",
                                 now=t0 + timedelta(seconds=inbox_intake._CONTINUATION_WINDOW_SEC + 1),
                                 tracker_dir=tracker)
    assert len(list_cards(tracker_type="inbox", tracker_dir=tracker)) == 2


def test_explicit_new_task_marker_breaks_the_glue(tracker):
    """Явный маркер новой задачи разрывает склейку даже внутри окна."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    inbox_intake.save_inbox_task(_part(_FIRST_LINE, 4088), source="telegram",
                                 now=t0, tracker_dir=tracker)
    inbox_intake.save_inbox_task("Новая задача: проверить kill-switch", source="telegram",
                                 now=t0 + timedelta(seconds=5), tracker_dir=tracker)
    assert len(list_cards(tracker_type="inbox", tracker_dir=tracker)) == 2


def test_continuation_keeps_card_readable_and_open(tracker):
    """Склеенная карточка остаётся валидной: статус new, служебный хвост — один и в конце."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    p1, _ = inbox_intake.save_inbox_task(_part(_FIRST_LINE, 4088), source="telegram",
                                         now=t0, tracker_dir=tracker)
    inbox_intake.save_inbox_task(_part("WHY IT EXISTS", 3346), source="telegram",
                                 now=t0 + timedelta(seconds=3), tracker_dir=tracker)
    card = load_card(p1)
    assert card.status == "new"
    assert card.fields.get("source") == "telegram"
    assert card.body.count(inbox_intake._FOOTER) == 1
    assert card.body.rstrip().endswith(inbox_intake._FOOTER)
    assert "## Продолжение — часть 2" in card.body


def test_voice_transcript_is_never_glued(tracker):
    """Голосовое приходит целиком — его карточка не должна утекать в чужую склейку."""
    t0 = datetime(2026, 8, 13, 13, 10, 14, tzinfo=timezone.utc)
    inbox_intake.save_inbox_task(_part(_FIRST_LINE, 4088), source="voice",
                                 now=t0, tracker_dir=tracker)
    inbox_intake.save_inbox_task("проверь дашборд", source="voice",
                                 transcript="проверь дашборд на телефоне",
                                 now=t0 + timedelta(seconds=5), tracker_dir=tracker)
    assert len(list_cards(tracker_type="inbox", tracker_dir=tracker)) == 2
