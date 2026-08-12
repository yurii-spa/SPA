"""Чистка фантомов упавшего классификатора: закрывать ТОЛЬКО их (авария 11.08.2026).

Опасность инструмента ровно одна и противоположная аварии: закрыть НАСТОЯЩИЙ вопрос
владельца, приняв его за фантом. Поэтому больше половины тестов ниже — про то, чего
скрипт делать НЕ должен. Признак фантома — совокупность (тип + статус + source + префикс
заголовка + ДОСЛОВНЫЙ служебный текст упавшего классификатора); при любом несовпадении
карточка остаётся нетронутой.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "repair_phantom_intake_cards", _ROOT / "scripts" / "repair_phantom_intake_cards.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

_OUTAGE = "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>."


def _phantom(tracker: Path, source_title: str, *, asked: str = _OUTAGE,
             status: str = "needs-owner", source: str = "intake",
             title: str | None = None) -> Path:
    p = tracker / f"owner-decision-{abs(hash(source_title)) % 10**8}.md"
    p.write_text(
        "---\n"
        "trackerStatus:\n  type: owner-decision\n"
        f'title: "{title if title is not None else "Уточнение по заметке: " + source_title}"\n'
        f"status: {status}\n"
        f"source: {source}\n"
        "created: 2026-08-11\n"
        "---\n\n"
        "## Что случилось и почему это важно\nПришло сообщение, непонятно — вопрос это или задача.\n\n"
        f"## Что от тебя нужно\n{asked}\n\n"
        "## Как понять, что готово\nТы уточнил.\n",
        encoding="utf-8")
    return p


def _inbox(tracker: Path, title: str, status: str = "done") -> Path:
    p = tracker / f"inbox-{abs(hash(title)) % 10**8}.md"
    p.write_text(
        "---\n"
        "trackerStatus:\n  type: inbox\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        "created: 2026-08-11\n"
        "---\n\n"
        "## Задание (из Telegram)\n\nсделай штуку\n",
        encoding="utf-8")
    return p


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


def _status(p: Path) -> str:
    return R._field(p.read_text(encoding="utf-8"), "status")


# ── что скрипт ОБЯЗАН сделать ────────────────────────────────────────────────

def test_phantom_closed_and_source_reopened(tracker):
    src = _inbox(tracker, "ADR-070.2: канон трека коммитится циклом", status="done")
    ph = _phantom(tracker, "ADR-070.2: канон трека коммитится циклом")

    res = R.repair(tracker, apply=True)

    assert res["phantoms_closed"] == 1
    assert res["sources_reopened"] == 1
    assert _status(ph) == "done"
    assert _status(src) == "new", "реальное задание должно вернуться в работу"


def test_close_note_explains_it_was_not_the_owner(tracker):
    """Закрытие обязано быть подписано машиной — иначе это подделка решения владельца."""
    _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")

    R.repair(tracker, apply=True)

    body = ph.read_text(encoding="utf-8")
    assert "Закрыто автоматически" in body
    assert "не решением владельца" in body
    assert _status(ph) != "owner-done", "инв. #14: owner-done ставит только владелец"


def test_empty_output_signature_also_recognised(tracker):
    _inbox(tracker, "Другое задание", status="done")
    ph = _phantom(tracker, "Другое задание",
                  asked="Пустой ответ. Переформулируй или пришли как /task <текст>.")

    assert R.repair(tracker, apply=True)["phantoms_closed"] == 1
    assert _status(ph) == "done"


def test_mass_case_all_of_them(tracker):
    """Миниатюра 11.08: пачка фантомов уходит целиком, все источники открываются."""
    srcs = [_inbox(tracker, f"Задание {i}", status="done") for i in range(7)]
    [_phantom(tracker, f"Задание {i}") for i in range(7)]

    res = R.repair(tracker, apply=True)

    assert res["phantoms_closed"] == 7
    assert res["sources_reopened"] == 7
    assert all(_status(s) == "new" for s in srcs)


# ── чего скрипт делать НЕ ДОЛЖЕН (главная опасность инструмента) ─────────────

def test_real_owner_question_is_never_touched(tracker):
    """Настоящий вопрос МОДЕЛИ по существу — не фантом, трогать запрещено."""
    ph = _phantom(tracker, "Что-то важное",
                  asked="Это про сайт или про агентов? Уточни, пожалуйста.")

    res = R.repair(tracker, apply=True)

    assert res["phantoms_closed"] == 0
    assert _status(ph) == "needs-owner"


def test_handwritten_owner_card_is_never_touched(tracker):
    """Карточка владельца не от интейка (source: nimbalyst) — вне зоны действия."""
    ph = _phantom(tracker, "Задание", source="nimbalyst")

    assert R.repair(tracker, apply=True)["phantoms_closed"] == 0
    assert _status(ph) == "needs-owner"


def test_card_without_the_title_prefix_is_never_touched(tracker):
    ph = _phantom(tracker, "Задание", title="Живой вопрос про лимит цепочки")

    assert R.repair(tracker, apply=True)["phantoms_closed"] == 0
    assert _status(ph) == "needs-owner"


def test_already_answered_card_is_never_touched(tracker):
    """Ответил владелец (owner-done) — карточка не наша, даже с подписью аварии."""
    ph = _phantom(tracker, "Задание", status="owner-done")

    assert R.repair(tracker, apply=True)["phantoms_closed"] == 0
    assert _status(ph) == "owner-done"


def test_source_still_open_is_not_disturbed(tracker):
    """Исходник, который НЕ закрывали, менять не за что — он уже в работе."""
    src = _inbox(tracker, "Задание", status="in-progress")
    _phantom(tracker, "Задание")

    res = R.repair(tracker, apply=True)

    assert res["sources_reopened"] == 0
    assert _status(src) == "in-progress"


def test_missing_source_is_reported_not_silently_dropped(tracker):
    """Исходника нет ⇒ это НАХОДКА в отчёте, а не тихий пропуск."""
    _phantom(tracker, "Задание без исходника")

    res = R.repair(tracker, apply=True)

    assert res["sources_not_found"] == 1
    assert "Задание без исходника" in res["orphaned"]


def test_dry_run_writes_nothing(tracker):
    src = _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")

    res = R.repair(tracker, apply=False)

    assert res["phantoms_closed"] == 1          # найдено
    assert _status(ph) == "needs-owner"          # но не тронуто
    assert _status(src) == "done"


def test_rerun_is_idempotent(tracker):
    _inbox(tracker, "Задание", status="done")
    ph = _phantom(tracker, "Задание")

    R.repair(tracker, apply=True)
    body_once = ph.read_text(encoding="utf-8")
    second = R.repair(tracker, apply=True)

    assert second["phantoms_closed"] == 0, "закрытый фантом не должен обрабатываться снова"
    assert ph.read_text(encoding="utf-8") == body_once, "пометка не должна дублироваться"
