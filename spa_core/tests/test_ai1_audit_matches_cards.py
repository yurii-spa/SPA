"""`AI1_AUDIT.md` — окно в карточки, а не второй учёт. Тест держит это правдой.

# LLM_FORBIDDEN

Документ сам объявляет: «Единственное место, где статус задачи меняется, — её
карточка. Эта таблица — окно в них, а не второй учёт: разошлись ⇒ верна карточка».

Заявление продержалось несколько часов. Замер 2026-08-29 вечером: таблица
утверждала про задачу 1.1 `blocked`, тогда как карточка уже была `done` —
второй учёт завёлся ровно там, где документ обещал его не заводить.

Логика сверки работает на фикстуре ВСЕГДА; живые файлы — вторым слоем.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_AUDIT = _ROOT / "docs" / "AI1_AUDIT.md"
_TRACKER = _ROOT / "nimbalyst-local" / "tracker"

#: строка таблицы: | **1.1** Название | `card-name` | ✅ `done` | ... |
_ROW = re.compile(r"^\|\s*\*\*(?P<task>[\d.]+)\*\*[^|]*\|\s*`(?P<card>[^`]+)`\s*\|"
                  r"[^|]*?`(?P<status>done|blocked|backlog|needs-owner|ingested)`")


def audit_rows(text: str) -> dict:
    """{карточка: статус, заявленный таблицей}."""
    out = {}
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if m:
            out[m.group("card")] = m.group("status")
    return out


def card_status(path: Path) -> str | None:
    """Статус из frontmatter карточки — источник правды."""
    for line in path.read_text(encoding="utf-8").splitlines()[:20]:
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip()
    return None


# ── логика: работает без живых файлов ────────────────────────────────────
def test_parser_reads_a_table_row():
    text = "| **1.1** Имя | `agent-ai1-11-x` | ✅ `done` | комментарий |"
    assert audit_rows(text) == {"agent-ai1-11-x": "done"}


def test_parser_ignores_prose_and_other_tables():
    text = "\n".join([
        "Обычный текст про `done` и карточки.",
        "| Компонент | Статус | Где |",
        "| **2.1** Имя | `agent-ai1-21-y` | ⛔ `blocked` | почему |",
    ])
    assert audit_rows(text) == {"agent-ai1-21-y": "blocked"}


def test_parser_finds_nothing_when_there_is_no_table():
    assert audit_rows("просто текст без таблицы") == {}


def test_a_planted_drift_is_caught():
    """Положительный контроль ровно той формы, что случилась 29.08."""
    table = {"agent-ai1-11-allocation-auditor": "blocked"}
    cards = {"agent-ai1-11-allocation-auditor": "done"}
    drift = {c: (table[c], cards[c]) for c in table if table[c] != cards[c]}
    assert drift, "расхождение таблицы с карточкой обязано быть видимым"


# ── живой слой ───────────────────────────────────────────────────────────
def test_audit_table_matches_every_card():
    if not _AUDIT.exists() or not _TRACKER.exists():
        pytest.skip("документ или трекер недоступны в этом дереве")
    rows = audit_rows(_AUDIT.read_text(encoding="utf-8"))
    assert len(rows) >= 7, f"в таблице задач всего {len(rows)} строк — сверка ослабла"

    missing, drift = [], {}
    for card, claimed in sorted(rows.items()):
        f = _TRACKER / f"{card}.md"
        if not f.exists():
            missing.append(card)
            continue
        actual = card_status(f)
        if actual and actual != claimed:
            drift[card] = (claimed, actual)

    assert not missing, f"таблица ссылается на несуществующие карточки: {missing}"
    assert not drift, (
        "таблица разошлась с карточками (заявлено → на самом деле): "
        f"{drift}. Документ объявляет себя ОКНОМ в карточки; расхождение "
        "означает, что завёлся второй учёт — правь таблицу, не карточку.")
