#!/usr/bin/env python3
"""Гейт против КЛАССА «молча выключенный файл тестов с шаблонной отпиской».

Зачем этот файл существует
==========================
Три автономных цикла подряд (#37, #38, #39) находили один и тот же приём: тест-файл
целиком гасился **file-level** ``pytestmark = pytest.mark.skip(...)`` в
``except ImportError``, а причиной стояла шаблонная фраза «API refactored — tests
need rewrite». Каждый раз фраза оказывалась НЕВЕРНОЙ, и каждый раз вместе с
тестами мёртвого кода гасились тесты ЖИВОГО:

* #37 ``test_cycle_health_monitor.py``  — 88 скипнутых → 64 passed;
* #38 ``test_adapter_watchdog.py``     — 136 скипнутых → 4 passed (+57 новых);
* #39 ``test_pendle_pt_adapter{,_v2}.py`` (190) + ``test_walk_forward_validator.py``
  (78) → оживлён ``TestASTLint``, пиннящий инвариант #4 у живого MP-1495.

Скип с неверной причиной ХУЖЕ красного теста: он не виден в CI, не попадает в
счётчик падений и создаёт впечатление покрытия там, где его нет (инвариант #16 —
молча ослаблять/выключать тесты запрещено).

Что проверяется (детерминированно, без сети, только чтение файлов репозитория)
=============================================================================
1. **Ни одна** причина skip/skipif во всём ``spa_core/tests`` не содержит
   шаблонных фраз, которые трижды соврали (``_BANNED_PHRASES``).
2. Любой **безусловный file-level** ``pytest.mark.skip`` — только из явного
   реестра ``_ALLOWED_FILE_LEVEL_SKIPS`` с обязательной подстрокой-причиной.
   Новый файл в этом виде ⇒ тест краснеет: сузь скип до классов (если хоть один
   тест в файле импортируется) либо внеси файл в реестр с ПРАВДИВОЙ причиной.
3. У каждой причины есть непустой текст.

Гейт НЕ запрещает скипы как таковые: условные (``skipif`` по зависимости, по
артефакту, по возможности API) — законная форма и здесь не ограничиваются.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, NamedTuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_DIR = _REPO_ROOT / "spa_core" / "tests"
_SELF_NAME = Path(__file__).name

# Фразы, которые в #37/#38/#39 оказались ложными описаниями реальной причины.
# Настоящая причина всегда конкретна: модуль ретирован / зависимость не стоит /
# нужен git-ignored артефакт / нужен ретированный API.
_BANNED_PHRASES = (
    "api refactored",
    "tests need rewrite for new interface",
)

# Безусловный file-level скип допустим ТОЛЬКО когда ни один тест файла не может
# импортироваться. Значение — обязательная подстрока причины (нижний регистр).
_ALLOWED_FILE_LEVEL_SKIPS: dict[str, str] = {
    # MP-354: целевой модуль ретирован (raise ImportError первым оператором);
    # его API не существует ни в одном живом модуле — проверено импортом символов
    # в цикле #39. Ни один из 95 тестов файла импортироваться не может.
    "test_pendle_pt_adapter.py": "retired",
    # Побайтовый дубль предыдущего файла (diff = одна лишняя строка импорта).
    "test_pendle_pt_adapter_v2.py": "retired",
}


class _Mark(NamedTuple):
    file: str
    kind: str          # "skip" (безусловный) | "skipif" (условный)
    reason: str        # статически читаемый текст причины ("" если не литерал)
    has_reason: bool   # причина ВООБЩЕ передана (в т.ч. f-string / переменной)


def _mark_kind(call: ast.Call) -> str | None:
    """Вернуть 'skip'/'skipif', если это pytest.mark.skip(if)(...), иначе None."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("skip", "skipif"):
        return None
    # ожидаем цепочку …mark.skip / …mark.skipif
    owner = func.value
    if isinstance(owner, ast.Attribute) and owner.attr == "mark":
        return func.attr
    return None


def _literal_text(node: ast.AST) -> str:
    """Статически читаемый текст узла-строки.

    Причина часто собирается f-string'ом (``reason=f"gate reads {path}"``) — в AST
    это ``JoinedStr``. Берём его литеральные части: подставляемые значения нам не
    нужны, проверяется формулировка, а не подставленный путь.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_text(node.left) + _literal_text(node.right)
    return ""


def _reason_of(call: ast.Call) -> tuple[str, bool]:
    """(статически читаемый текст, передана ли причина вообще)."""
    for kw in call.keywords:
        if kw.arg == "reason":
            return _literal_text(kw.value), True
    # skip("причина") позиционно: у skip это первый аргумент, у skipif — второй
    positional = call.args[1:] if _mark_kind(call) == "skipif" else call.args
    for arg in positional:
        text = _literal_text(arg)
        if text:
            return text, True
    return "", False


def _iter_pytestmark_assignments(tree: ast.Module) -> Iterator[ast.Call]:
    """Присваивания module-level имени ``pytestmark`` (в т.ч. внутри try/if)."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            continue
        value = node.value
        if isinstance(value, ast.Call):
            yield value
        elif isinstance(value, (ast.List, ast.Tuple)):
            for elt in value.elts:
                if isinstance(elt, ast.Call):
                    yield elt


def _collect() -> tuple[list[_Mark], list[_Mark]]:
    """(все марки skip/skipif в файлах, file-level марки) по всему дереву тестов."""
    all_marks: list[_Mark] = []
    file_level: list[_Mark] = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        if path.name == _SELF_NAME:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # синтаксис ловит отдельный гейт CI, не этот
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                kind = _mark_kind(node)
                if kind:
                    reason, has_reason = _reason_of(node)
                    all_marks.append(_Mark(path.name, kind, reason, has_reason))
        for call in _iter_pytestmark_assignments(tree):
            kind = _mark_kind(call)
            if kind:
                reason, has_reason = _reason_of(call)
                file_level.append(_Mark(path.name, kind, reason, has_reason))
    return all_marks, file_level


_ALL_MARKS, _FILE_LEVEL_MARKS = _collect()


def test_test_tree_is_scannable() -> None:
    """Сам гейт должен что-то видеть — иначе он «зелёный» ни о чём (fail-CLOSED)."""
    assert _TESTS_DIR.is_dir(), f"tests dir not found: {_TESTS_DIR}"
    assert len(_ALL_MARKS) > 10, (
        f"scanned only {len(_ALL_MARKS)} skip/skipif marks — сканер, похоже, сломан; "
        "пустой обход не должен читаться как «нарушений нет»"
    )


def test_no_banned_template_skip_reasons() -> None:
    """Шаблонная отписка, трижды соврав­шая, запрещена в любой причине скипа."""
    offenders = [
        f"{m.file} [{m.kind}]: {m.reason!r}"
        for m in _ALL_MARKS
        if any(p in m.reason.lower() for p in _BANNED_PHRASES)
    ]
    assert not offenders, (
        "Найдена шаблонная причина скипа. В #37/#38/#39 ровно эта формулировка "
        "оказывалась НЕВЕРНОЙ (модуль был ретирован, а не «отрефакторен»). "
        "Опиши настоящую причину конкретно: какой модуль/символ/артефакт и почему.\n  "
        + "\n  ".join(offenders)
    )


def test_no_undocumented_file_level_unconditional_skips() -> None:
    """Безусловный file-level скип — только из реестра, с правдивой причиной."""
    unconditional = [m for m in _FILE_LEVEL_MARKS if m.kind == "skip"]
    unexpected = [m.file for m in unconditional if m.file not in _ALLOWED_FILE_LEVEL_SKIPS]
    assert not unexpected, (
        "Новый безусловный file-level skip: "
        f"{sorted(set(unexpected))}. Так гасится ВЕСЬ файл, включая тесты живого "
        "кода (см. #37/#38/#39). Сузь скип до классов, зависящих от мёртвого API, "
        "либо внеси файл в _ALLOWED_FILE_LEVEL_SKIPS с настоящей причиной."
    )
    for m in unconditional:
        required = _ALLOWED_FILE_LEVEL_SKIPS[m.file]
        assert required in m.reason.lower(), (
            f"{m.file}: причина file-level скипа должна содержать {required!r} "
            f"(реестр требует именно это обоснование), получено: {m.reason!r}"
        )


def test_every_skip_has_a_reason() -> None:
    """Скип без текста причины непроверяем — запрещён."""
    silent = [f"{m.file} [{m.kind}]" for m in _ALL_MARKS if not m.has_reason]
    assert not silent, (
        "Скип без причины (нельзя проверить, правда ли это): " + ", ".join(sorted(set(silent)))
    )


def test_allowlist_has_no_stale_entries() -> None:
    """Реестр не должен разрастаться мёртвыми записями (файл починили/удалили)."""
    seen = {m.file for m in _FILE_LEVEL_MARKS if m.kind == "skip"}
    stale = sorted(set(_ALLOWED_FILE_LEVEL_SKIPS) - seen)
    assert not stale, (
        f"Записи реестра больше не соответствуют реальности: {stale}. "
        "Файл починен или удалён — убери запись, чтобы реестр не разрешал лишнего."
    )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
