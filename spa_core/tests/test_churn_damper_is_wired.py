"""Ограничитель перекладок действительно спрашивают — и обойти его нельзя.

# LLM_FORBIDDEN

ADR-168. Модуль, который решает и которого никто не спрашивает, — это файл,
а не ограничитель; сегодня в надзорном слое таких нашлось одиннадцать.

Тест читает цикл как ТЕКСТ и не запускает его: дневной цикл против живого
`data/` не запускается никогда.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_CYCLE = Path(__file__).resolve().parents[1] / "paper_trading" / "cycle_runner.py"


def _text() -> str:
    return _CYCLE.read_text(encoding="utf-8")


def test_the_damper_is_imported_by_the_cycle():
    tree = ast.parse(_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "spa_core.governance.churn_damper" in mods, (
        "цикл перестал импортировать ограничитель — перекладки снова без ограничения")


def _trade_decision_source() -> str:
    """Исходник ТОГО САМОГО присваивания `traded`, что решает про перекладку.

    Регулярка здесь не годится: `traded` встречается в файле пять раз, в том
    числе как именованный аргумент `traded=False`. Первая редакция теста
    поймала именно его и покраснела на верной проводке — ложная находка,
    исправленная разбором AST.
    """
    tree = ast.parse(_text())
    src = _text()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "traded" for t in node.targets):
            continue
        chunk = ast.get_source_segment(src, node.value) or ""
        if "_safety_failed" in chunk:
            return chunk
    raise AssertionError("присваивание `traded`, решающее про перекладку, не найдено")


def test_the_verdict_actually_gates_the_trade():
    """Мало позвать — вердикт обязан входить в решение `traded`."""
    expr = _trade_decision_source()
    assert "_churn.allowed" in expr, (
        "вердикт ограничителя не входит в решение о перекладке: его зовут, "
        "но результат никуда не идёт")


def test_the_safety_conditions_are_still_there():
    """Обратный контроль: ограничитель добавлен, а не заменил защиту."""
    expr = _trade_decision_source()
    for guard in ("_safety_failed", "policy_blocked", "diff_usd > threshold_usd"):
        assert guard in expr, f"из решения о перекладке исчезло условие {guard}"


def test_the_block_is_recorded_where_a_human_looks():
    """Отложенная перекладка обязана быть НАЗВАНА, а не тихо не случиться."""
    t = _text()
    assert "churn_damper: перекладка отложена" in t
    assert "ADR-168" in t


def test_derisk_exemption_is_documented_at_the_call_site():
    """Читающий цикл должен видеть, что де-риск не задерживается."""
    t = _text()
    i = t.index("_churn_decide(")
    head = t[max(0, i - 900):i]
    assert "не задерживается никогда" in head or "СОКРАЩАЕТ" in head, (
        "у места вызова пропало объяснение, что де-риск проходит всегда")
