#!/usr/bin/env python3
"""Храповик строки статуса у нумерованных design-документов (`docs/NN_*.md`).

Правило — `.claude/rules/design-docs.md`. Замер, которым оно вызвано (2026-08-20):
`docs/` — 415 файлов / ~102 000 строк, 47 нумерованных документов, и девять
названных слоёв, под которыми НЕТ НИ ОДНОГО файла кода. Вред не в объёме, а в
том, что описанное неотличимо от работающего.

Устройство — как у ``frozen_date_baseline.json``, и по той же причине: запрет в
лоб покрасил бы все 47 документов разом и научил бы всех отключать проверку.
Поэтому:

* база (`design_status_baseline.json`) перечисляет документы, существовавшие на
  момент введения правила, — они НЕ краснеют;
* **новый** документ без строки статуса краснеет сразу;
* база может только уменьшаться; добавлять в неё файл, чтобы погасить падение,
  запрещено — на этом храповик и держится.

Строка статуса:

    > **Статус:** L2 · владелец: @yurii · приёмка: <как понять, что построено>

Три поля отвечают на три разных вопроса — построено ли (L1–L5), кто вправе
принять результат (AI1 гл. 05 п.3 = наш инвариант #14) и как мы узнаем, что
документ перестал быть текстом. Проверяется наличие ВСЕХ трёх: две трети строки
статуса — это не статус.

Только stdlib, оффлайн.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "docs"
_BASELINE = Path(__file__).resolve().parent / "design_status_baseline.json"

# Нумерованный design-документ: docs/07_..., docs/07a_..., docs/23_...
_NUMBERED = re.compile(r"^\d{2}[a-z]?_.+\.md$")

# Строка статуса. Уровень, владелец и приёмка — все три обязательны.
_STATUS = re.compile(
    r"\*\*Статус:\*\*\s*L(?P<level>[1-5])\b"
    r"(?=.*владелец:\s*\S)"
    r"(?=.*приёмка:\s*\S)",
    re.S,
)
_HEAD_LINES = 40


def _numbered_docs() -> set[str]:
    if not _DOCS.is_dir():
        return set()
    return {p.name for p in _DOCS.iterdir() if p.is_file() and _NUMBERED.match(p.name)}


def _has_status(name: str) -> bool:
    """Строка статуса обязана быть В ШАПКЕ: статус, найденный на 300-й строке,
    читающий не увидит, а значит он не выполняет свою работу."""
    try:
        text = (_DOCS / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    head = "\n".join(text.splitlines()[:_HEAD_LINES])
    return bool(_STATUS.search(head))


def _baseline() -> set[str] | None:
    try:
        return set(json.loads(_BASELINE.read_text(encoding="utf-8"))["files"])
    except Exception:  # noqa: BLE001 — пропавшая база не должна проходить молча
        return None


def test_baseline_exists_and_is_readable() -> None:
    """Нет базы ⇒ храповик ничего не меряет. Fail-CLOSED."""
    assert _baseline() is not None, (
        f"{_BASELINE.name} отсутствует или не читается — храповик не отличит "
        "новый документ от старого и молча пропустит всё")


def test_no_new_doc_lacks_a_status_line() -> None:
    """Главная проверка: новый design-документ обязан назвать свой статус."""
    base = _baseline() or set()
    offenders = sorted(n for n in _numbered_docs() if not _has_status(n) and n not in base)
    assert not offenders, (
        "нумерованный design-документ без строки статуса:\n  "
        + "\n  ".join(offenders)
        + "\n\nДобавьте в первые 40 строк:\n"
        '  > **Статус:** L2 · владелец: @yurii · приёмка: <как понять, что построено>\n'
        "Шкала и смысл полей — .claude/rules/design-docs.md. В базу файл НЕ добавлять: "
        "база только уменьшается.")


def test_baseline_holds_nothing_that_is_no_longer_at_risk() -> None:
    """База обязана сжиматься: починенный документ выпадает из неё."""
    base = _baseline() or set()
    fixed = sorted(n for n in base if n in _numbered_docs() and _has_status(n))
    assert not fixed, (
        "эти документы уже несут строку статуса и обязаны выйти из базы "
        f"(база только уменьшается): {fixed}")


def test_baseline_holds_no_ghosts() -> None:
    """Удалённый документ не должен вечно занимать место в базе."""
    base = _baseline() or set()
    ghosts = sorted(n for n in base if n not in _numbered_docs())
    assert not ghosts, f"в базе документы, которых нет на диске: {ghosts}"


def test_detector_accepts_the_prescribed_line() -> None:
    """Положительный контроль формы: правило и сторож обязаны совпадать дословно."""
    good = ("# 15 — что-то\n\n"
            "> **Статус:** L2 · владелец: @yurii · приёмка: есть модуль и зелёный тест\n")
    assert _STATUS.search(good)


def test_detector_rejects_two_thirds_of_a_status_line() -> None:
    """Две трети строки статуса — не статус. Обратный контроль детектора."""
    assert not _STATUS.search("> **Статус:** L2 · владелец: @yurii\n"), "нет приёмки"
    assert not _STATUS.search("> **Статус:** L2 · приёмка: тест\n"), "нет владельца"
    assert not _STATUS.search("> **Статус:** построено · владелец: @yurii · приёмка: тест\n"), \
        "уровень должен быть L1–L5, а не словом"


def test_status_deep_in_the_body_does_not_count() -> None:
    """Статус, которого не видно в шапке, работы не делает."""
    body = "\n".join(["# 99 — что-то", ""] + ["текст"] * 60
                     + ["> **Статус:** L2 · владелец: @yurii · приёмка: тест"])
    head = "\n".join(body.splitlines()[:_HEAD_LINES])
    assert _STATUS.search(body) and not _STATUS.search(head)
