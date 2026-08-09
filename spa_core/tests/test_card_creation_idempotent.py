#!/usr/bin/env python3
"""Тот же вопрос, заданный второй раз, — НЕ вторая карточка.

Замер 08–09.08: автоматические авторы (owner-gate сайта и другие) при каждом повторе своей
проверки заводили новую карточку `-2`, `-3`… и КАЖДАЯ слала владельцу отдельное уведомление.
Владелец получал одно и то же «нужно решение» каждые несколько минут — «с этим невозможно
работать».

Чинить это у каждого автора по очереди бессмысленно: авторов много, и завтра появится новый.
Поэтому защита стоит в ЕДИНСТВЕННОЙ точке, через которую карточки рождаются — `create_card`.

Условие узкое и проверяемое, чтобы защита не стала глухотой:
тот же заголовок + то же тело + карточка ВСЁ ЕЩЁ ОТКРЫТА.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spa_core.owner_queue.queue import create_card, load_card, set_status

TITLE = "Сайт: автономная правка задела owner-gated область"
BODY = "## Что от тебя нужно\n\n1. **Одобрить** — текст.\n2. **Отклонить** — текст.\n"


def test_the_same_question_twice_is_one_card(tmp_path):
    """Положительный контроль потока: повтор той же проверки не плодит карточку."""
    first = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    for _ in range(5):
        again = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
        assert again == first
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_a_changed_body_is_a_new_question(tmp_path):
    """Защита не имеет права стать глухотой: изменилось содержание — новая карточка."""
    create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    create_card("owner-decision", TITLE, BODY + "\nещё одно нарушение\n", tracker_dir=tmp_path)
    assert len(list(tmp_path.glob("*.md"))) == 2


def test_a_closed_question_that_returns_gets_a_new_card(tmp_path):
    """Вопрос вернулся ПОСЛЕ закрытия — это новый вопрос, и о нём надо сказать.

    Иначе закрытая вчера карточка навсегда глушила бы ту же проблему сегодня.
    """
    first = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    set_status(first, "ingested")
    second = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert second != first
    assert len(list(tmp_path.glob("*.md"))) == 2


@pytest.mark.parametrize("status", ["needs-owner", "new", "in-progress", "blocked"])
def test_every_open_status_suppresses_the_duplicate(tmp_path, status):
    """Открыт — значит ещё ждёт ответа, в любом из открытых состояний."""
    first = create_card("owner-decision", TITLE, BODY, status=status, tracker_dir=tmp_path)
    assert create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path) == first


def test_whitespace_only_difference_is_still_the_same_question(tmp_path):
    """Лишний перевод строки в конце — не новый вопрос владельцу."""
    first = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert create_card("owner-decision", TITLE, BODY + "\n\n", tracker_dir=tmp_path) == first


def test_a_different_tracker_type_can_never_collide(tmp_path):
    """Задача и решение не пересекаются, потому что ТИП входит в имя файла.

    Это не «ещё одна проверка», а свойство именования: `inbox-…` против `owner-decision-…`.
    Тест пиннит именно его — сверять тип внутри поиска близнеца было бы защитой, которой
    нечего защищать (первая версия так и делала, и мутация её не заметила).
    """
    a = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    b = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path)
    assert a != b
    assert a.name.startswith("owner-decision-") and b.name.startswith("inbox-")


def test_a_broken_card_on_disk_never_blocks_a_new_one(tmp_path):
    """Fail-CLOSED в сторону ВЛАДЕЛЬЦА: битый файл не имеет права проглотить вопрос."""
    broken = tmp_path / "owner-decision-sait-avtonomnaya-pravka-zadela-owner-gated-oblast.md"
    broken.write_text("не карточка вовсе", encoding="utf-8")
    created = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert created.exists()
    assert load_card(created).title == TITLE


def test_a_failing_lookup_still_creates_the_card(tmp_path, monkeypatch):
    """Fail-CLOSED в сторону ВЛАДЕЛЬЦА, теперь на ВНЕШНЕМ предохранителе.

    Первая версия этого контроля проверяла только битый файл — а он обрабатывается
    внутренним `except` и до внешнего не доходит, поэтому мутация «внешний except
    возвращает путь» оставалась НЕ ЗАМЕЧЕННОЙ. Здесь ломается сам обход каталога:
    если поиск близнеца рухнул, карточка обязана создаться, а не исчезнуть.
    """
    from spa_core.owner_queue import queue as q

    def boom(*a, **k):
        raise OSError("каталог недоступен")

    monkeypatch.setattr(q.Path, "glob", boom)
    created = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert created.exists()
    assert load_card(created).title == TITLE
