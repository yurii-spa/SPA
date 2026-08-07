"""Поведенческие тесты `scripts/audit_state_journal_coverage.py`.

Инструмент отвечает на один вопрос: **можно ли удалить эту запись из `docs/STATE.md`, не
потеряв её** — то есть есть ли у названного в ней цикла СВОЯ запись в `docs/journal/`. Цена
ошибки несимметрична: ложное «покрыто» — безвозвратно стёртая запись, ложное «не покрыто» —
лишняя минута ручного разбора. Поэтому все проверки ниже давят на ложное «покрыто».

Каждый тест — реальная ловушка, в которую инструмент попадал при разработке (цикл #142):
голая решётка `#N` теряла однозначные циклы и ловила чужие (`инв. #16`, `PR #2`); жирная
строка внутри записи резала одну запись на куски без номера; упоминание цикла в ТЕЛЕ чужой
записи засчитывалось за покрытие.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "audit_state_journal_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_state_journal_coverage", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit_mod():
    assert _SCRIPT.exists(), f"нет {_SCRIPT}"
    return _load()


# ── номер цикла: контекст, а не любая решётка ────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("> **2026-08-06 (цикл #131) — Tier-C аналитики**", ["131"]),
    ("Циклом #124 доставлено", ["124"]),
    ("- **Hardening (автономный цикл, 2026-07-16, #9):** очередь пуста", ["9"]),
    ("- **Автономный цикл оркестратора (2026-07-30, #48): очередь ПУСТА", ["48"]),
    ("поднята работа циклов #49–#50", ["49"]),
])
def test_cycle_ids_found_where_a_cycle_is_named(audit_mod, text, expected):
    """Все формы, которыми в репозитории называют цикл, распознаются."""
    assert audit_mod.cycle_ids(text) == expected


@pytest.mark.parametrize("text", [
    "ни один существующий тест не изменён (инв. #16)",
    "PR #2–#5, #7 закрыты",
    "класс fail-OPEN #29/#31/#35-#40",
    "карточка own-28 и ключ #212059",
])
def test_bare_hash_is_not_a_cycle(audit_mod, text):
    """Чужая решётка циклом НЕ считается.

    Это и есть опасная сторона: если `инв. #16` прочитать как «цикл 16», запись STATE
    объявится покрытой циклом, о котором в ней не было ни слова, и будет удалена.
    """
    assert audit_mod.cycle_ids(text) == []


def test_single_digit_cycles_are_not_lost(audit_mod):
    """Однозначные циклы (#2…#9) — настоящие записи от 2026-07-16, их терять нельзя.

    Первая версия инструмента требовала двух-трёх цифр и молча отправляла семь записей
    в класс «номера цикла нет» — то есть на ручной разбор, которого никто бы не сделал.
    """
    assert audit_mod.cycle_ids("- **Hardening (автономный цикл, 2026-07-16, #2):**") == ["2"]


# ── нарезка на записи: жирная строка внутри записи — не новая запись ──────────────────────

def _state(lines):
    return "\n".join(lines)


def test_bold_line_inside_an_entry_does_not_start_a_new_one(audit_mod):
    """`> **Границы измерены:**` — подзаголовок тела, а не запись.

    Дробление такой записи давало кусок без номера цикла ⇒ `NO_CYCLE_ID` там, где цикл
    назван абзацем выше. Разделитель записей в блок-цитате — пустая строка цитаты (`>`).
    """
    lines = _state([
        "> **2026-08-06 (цикл #139) — журнал терял записи.**",
        "> тело записи продолжается",
        "> **Границы измерены:** уровень ЗАПИСИ, а не строки",
        "> хвост тела",
        ">",
        "> **2026-08-06 (цикл #138) — разметка была слепа.**",
        "> тело второй записи",
    ]).split("\n")
    entries = audit_mod.split_entries(lines, 0, len(lines), audit_mod.BQ_ENTRY_RE)
    assert len(entries) == 2, [e[1].split("\n")[0] for e in entries]
    assert "цикл #139" in entries[0][1] and "Границы измерены" in entries[0][1]
    assert "цикл #138" in entries[1][1]


# ── вердикты ─────────────────────────────────────────────────────────────────────────────

def _write(tmp_path, state_lines, journal_files):
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    jdir = tmp_path / "docs" / "journal"
    jdir.mkdir(parents=True, exist_ok=True)
    state = tmp_path / "docs" / "STATE.md"
    state.write_text(_state(state_lines), encoding="utf-8")
    for name, body in journal_files.items():
        (jdir / name).write_text(body, encoding="utf-8")
    return state, jdir


def test_entry_with_its_own_journal_header_is_covered(audit_mod, tmp_path):
    """Цикл, у которого в журнале СВОЙ заголовок, помечается COVERED — его можно удалять."""
    state, jdir = _write(
        tmp_path,
        ["# STATE", "", "> **2026-08-06 (цикл #131) — Tier-C.**", "> тело"],
        {"2026-W32.md": "## Цикл #131 (2026-08-06, автономный) — Tier-C\n\nтело записи\n"},
    )
    rep = audit_mod.audit(state, jdir)
    assert rep["counts"] == {"COVERED": 1}, rep["entries"]


def test_entry_whose_cycle_is_absent_from_journal_is_missing(audit_mod, tmp_path):
    """Нет заголовка в журнале ⇒ MISSING: переносить, а не удалять.

    Это ровно тот случай, который опроверг посылку карточки («хроника и так уже есть
    в журнале»): у 18 записей номера циклов, стёртых из журнала перезаписями.
    """
    state, jdir = _write(
        tmp_path,
        ["# STATE", "", "> **2026-07-30 (цикл #48) — очередь пуста.**", "> тело"],
        {"2026-W31.md": "## Цикл #131 — совсем другой цикл\n\nтело\n"},
    )
    rep = audit_mod.audit(state, jdir)
    assert rep["counts"] == {"MISSING": 1}, rep["entries"]
    assert rep["entries"][0]["missing_cycles"] == ["48"]


def test_mention_in_a_body_is_not_coverage(audit_mod, tmp_path):
    """Упоминание цикла в ТЕЛЕ чужой записи покрытием НЕ считается.

    Самая тонкая из ловушек: «поднята осиротевшая работа цикла #137» доказывает, что номер
    где-то встречался, но не что запись цикла #137 сохранена. Засчитать это за покрытие —
    разрешить удаление того, чего в журнале нет. Подсказка ручному разбору выдаётся
    отдельным полем, вердикт от неё не меняется.
    """
    state, jdir = _write(
        tmp_path,
        ["# STATE", "", "> **2026-08-06 (цикл #137) — работа осиротела.**", "> тело"],
        {"2026-W32.md": "## Цикл #138 — свой заголовок\n\nподнята работа цикла #137\n"},
    )
    rep = audit_mod.audit(state, jdir)
    assert rep["counts"] == {"MISSING": 1}, rep["entries"]
    assert rep["entries"][0]["body_only_hint"] == ["137"], "подсказка ручному разбору потеряна"


def test_entry_without_a_cycle_number_is_not_called_covered(audit_mod, tmp_path):
    """Записи без номера цикла — отдельный класс, а не «покрыто» (fail-CLOSED).

    Интерактивные сессии, блоки ADR-066, автопилот. Их нельзя подтвердить механически,
    поэтому они требуют ручного взгляда — и молча удалёнными быть не могут.
    """
    state, jdir = _write(
        tmp_path,
        ["# STATE", "", "> **СЕССИЯ 2026-08-05 (интерактивная, владелец).**", "> тело"],
        {"2026-W32.md": "## Что-то\n\nтело\n"},
    )
    rep = audit_mod.audit(state, jdir)
    assert rep["counts"] == {"NO_CYCLE_ID": 1}, rep["entries"]


def test_exit_code_is_zero_only_when_nothing_needs_hands(audit_mod, tmp_path):
    """Код возврата 0 ⇔ всё COVERED. Любой MISSING/NO_CYCLE_ID ⇒ 1 (нужен ручной шаг)."""
    state, jdir = _write(
        tmp_path,
        ["# STATE", "", "> **2026-08-06 (цикл #131) — Tier-C.**", "> тело"],
        {"2026-W32.md": "## Цикл #131 — заголовок\n\nтело\n"},
    )
    assert audit_mod.main(["--state", str(state), "--journal-dir", str(jdir)]) == 0

    state2, jdir2 = _write(
        tmp_path / "b",
        ["# STATE", "", "> **2026-07-30 (цикл #48) — очередь пуста.**", "> тело"],
        {"2026-W31.md": "## Другое\n\nтело\n"},
    )
    assert audit_mod.main(["--state", str(state2), "--journal-dir", str(jdir2)]) == 1


# ── приёмка доставки: живой репозиторий ───────────────────────────────────────────────────

def test_live_state_no_longer_carries_uncovered_chronicle(audit_mod):
    """На доставленном `docs/STATE.md` не осталось записей цикла, которых нет в журнале.

    Прямая приёмка карточки: MISSING обязан быть нулём — иначе в файле состояния снова
    лежит единственная копия чего-то.
    """
    rep = audit_mod.audit(_REPO_ROOT / "docs" / "STATE.md", _REPO_ROOT / "docs" / "journal")
    assert rep["counts"].get("MISSING", 0) == 0, [
        e for e in rep["entries"] if e["verdict"] == "MISSING"
    ]
