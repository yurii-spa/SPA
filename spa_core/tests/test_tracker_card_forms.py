"""Обе формы frontmatter карточки — один читатель на всю очередь (карточка
``inbox-ochered-teryaet-kartochki-chitat-obe-for``, priority high, решение владельца 09.08).

Карточки в трекере объявляют себя ДВУМЯ формами, и обе легитимны:

* **вложенная** — ``trackerStatus: {type: …}`` + ``title:`` (её пишет ``create_card``);
* **плоская** — ``type:`` верхним уровнем, а название — ``#``-заголовком тела
  (так пишут R&D-сессии и авторы находок руками).

Замер цикла #183 на живом трекере: 381 карточка, из них **9 плоских**. ТИП у них читается
верно (починено #145, ниже — сторож в обе стороны, чтобы не разошлось снова), а вот
**НАЗВАНИЕ не доезжало до владельца ни в одном читателе**: на доске и в Telegram вместо
русского предложения стоял слаг файла. Среди этих девяти — ``own-32-evidence-vs-curve-diverge``,
живой вопрос владельцу о расхождении двух записей о деньгах, заведённый в тот же день.

Каждый тест здесь — положительный контроль: снятие починки (``resolve_card_title`` → чтение
одного лишь поля ``title``) красит его на реальном классе карточек, а не на выдуманном.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from spa_core.owner_queue.queue import (
    TRACKER_DIR,
    list_cards,
    load_card,
    resolve_card_title,
    set_status,
)
from spa_core.owner_queue.notify import build_message

REPO_ROOT = Path(__file__).resolve().parents[2]

FLAT_CARD = """---
type: owner-decision
status: needs-owner
priority: medium
created: 2026-08-09
---

# Две записи о деньгах расходятся каждый день

## Что от тебя нужно

Выбрать вариант.
"""

NESTED_CARD = """---
trackerStatus:
  type: owner-decision
title: "Вложенная форма — вопрос владельцу"
status: needs-owner
created: 2026-08-09
---

## Что от тебя нужно

Выбрать вариант.
"""


@pytest.fixture()
def tracker(tmp_path: Path) -> Path:
    d = tmp_path / "tracker"
    d.mkdir()
    (d / "own-flat.md").write_text(FLAT_CARD, encoding="utf-8")
    (d / "own-nested.md").write_text(NESTED_CARD, encoding="utf-8")
    return d


# --------------------------------------------------------------------------- тип


def test_flat_form_card_is_listed_under_its_declared_type(tracker: Path) -> None:
    """Плоская карточка ОБЯЗАНА находиться `list --type owner-decision`."""
    names = {c.path.name for c in list_cards(tracker_type="owner-decision", tracker_dir=tracker)}
    assert names == {"own-flat.md", "own-nested.md"}


def test_flat_form_card_is_not_listed_under_a_foreign_type(tracker: Path) -> None:
    """Обратная сторона: карточка НЕ имеет права протечь в чужой тип."""
    for foreign in ("inbox", "agent-task"):
        names = {c.path.name for c in list_cards(tracker_type=foreign, tracker_dir=tracker)}
        assert names == set(), f"плоская owner-decision протекла в тип {foreign}: {names}"


def test_live_tracker_positive_control_flat_owner_decision_is_visible() -> None:
    """Положительный контроль на ЖИВОЙ карточке (её называет сама карточка-задание).

    ``own-rnd-xsd-rank-demotion-allocator`` — реальная плоская карточка решения владельца.
    Она была одной из трёх, которых CLI не показывал вовсе (#143–#145).
    """
    card_path = TRACKER_DIR / "own-rnd-xsd-rank-demotion-allocator.md"
    if not card_path.exists():
        pytest.skip("живая карточка положительного контроля отсутствует в этом дереве")
    ids = {c.id for c in list_cards(tracker_type="owner-decision", tracker_dir=TRACKER_DIR)}
    assert "own-rnd-xsd-rank-demotion-allocator" in ids


# ------------------------------------------------------------------------ название


def test_flat_form_title_comes_from_the_body_heading(tracker: Path) -> None:
    card = load_card(tracker / "own-flat.md")
    assert card.title == "Две записи о деньгах расходятся каждый день"
    assert card.title != card.id, "владельцу уехал слаг файла вместо названия"


def test_declared_title_wins_over_a_body_heading() -> None:
    """Объявление раньше догадки: явный ``title:`` не перебивается заголовком тела."""
    fm = {"title": "Объявленное название"}
    assert resolve_card_title(fm, "# Заголовок тела\n") == "Объявленное название"


def test_heading_below_body_text_is_not_taken_as_a_title() -> None:
    """Заголовок РАЗДЕЛА (после текста) названием не является — иначе владелец получит
    случайную секцию вместо имени карточки."""
    body = "Тело начинается прозой.\n\n# Это раздел, а не название\n"
    assert resolve_card_title({}, body) == ""


def test_no_title_and_no_heading_resolves_to_empty_not_to_a_guess() -> None:
    """Нечего прочитать — пусто; подстановку id делает читатель, а не резолвер."""
    assert resolve_card_title({}, "просто текст\n") == ""
    assert resolve_card_title({}, "") == ""


def test_owner_notification_carries_the_human_title_not_the_slug(tracker: Path) -> None:
    """Худшая часть дефекта — то, что видит владелец в телефоне."""
    msg = build_message(load_card(tracker / "own-flat.md"))
    assert "Две записи о деньгах расходятся каждый день" in msg
    assert "own-flat" not in msg.split("📄")[0], "в заголовке сообщения стоит слаг файла"


def test_board_prints_the_human_title_for_a_flat_card(tracker: Path) -> None:
    """Доска — второй читатель; своей копии правила «где лежит название» у неё быть не должно."""
    spec = importlib.util.spec_from_file_location(
        "_board_under_test", REPO_ROOT / "scripts" / "build_tracker_board.py")
    assert spec and spec.loader
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)
    board.TRACKER = tracker
    board.OUT = tracker / "_BOARD.md"
    assert board.main() == 0
    rendered = (tracker / "_BOARD.md").read_text(encoding="utf-8")
    assert "Две записи о деньгах расходятся каждый день" in rendered
    assert "Вложенная форма — вопрос владельцу" in rendered


def test_every_live_needs_owner_card_shows_the_owner_a_human_name() -> None:
    """Храповик на инвариант #15 (название карточки — по-русски, а не слаг).

    Ждущая ответа карточка без читаемого названия — это вопрос, который владелец не
    узнаёт в списке; ровно так девять плоских карточек выглядели до #183.
    """
    if not TRACKER_DIR.exists():
        pytest.skip("трекера нет в этом дереве")
    faceless = [c.id for c in list_cards(status="needs-owner", tracker_dir=TRACKER_DIR)
                if not c.title or c.title == c.id]
    assert faceless == [], f"карточки ждут владельца без названия: {faceless}"


# ------------------------------------------------------- мутации карточки (обе формы)


def test_set_status_rewrites_status_on_both_forms(tracker: Path) -> None:
    """Инжест ответа владельца обязан работать на обеих формах — без этого решение
    по плоской карточке невозможно закрыть (та самая «худшая часть» из задания)."""
    for name in ("own-flat.md", "own-nested.md"):
        set_status(tracker / name, "ingested")
        card = load_card(tracker / name)
        assert card.status == "ingested"
        assert card.tracker_type == "owner-decision", "тип потерян при правке статуса"
        assert card.title, "название потеряно при правке статуса"


def test_set_status_touches_only_the_status_line_of_a_flat_card(tracker: Path) -> None:
    before = (tracker / "own-flat.md").read_text(encoding="utf-8").splitlines()
    set_status(tracker / "own-flat.md", "ingested")
    after = (tracker / "own-flat.md").read_text(encoding="utf-8").splitlines()
    diff = [(a, b) for a, b in zip(before, after) if a != b]
    assert diff == [("status: needs-owner", "status: ingested")]
    assert len(before) == len(after)
