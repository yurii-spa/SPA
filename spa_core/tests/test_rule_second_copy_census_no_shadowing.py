"""Глобальное имя модуля переписи присваивается РОВНО ОДИН раз (CI #6, 17.10).

`rule_second_copy_census.py` (~25 тыс. строк) дважды определял `_REACH_OUTCOMES` и `WITNESS_SUBJECT`: второе
определение молча затирало первое, и подсчёт многозначности шёл по чужому перечню исходов (14 падений
`test_tail_value_divergence` в полном вердикте CI #6), а двуязычный свидетель писался под ключом W2.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "monitoring" / "rule_second_copy_census.py"


def module_level_rebinds(source: str) -> list:
    counts: collections.Counter = collections.Counter()
    for node in ast.parse(source).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
        for t in targets:
            if isinstance(t, ast.Name):
                counts[t.id] += 1
    return sorted(k for k, v in counts.items() if v > 1)


def test_no_module_level_name_is_bound_twice():
    assert module_level_rebinds(MODULE.read_text(encoding="utf-8")) == []


def test_the_guard_sees_a_rebind():
    assert module_level_rebinds("A = 1\nB = 2\nA = (3,)\n") == ["A"]
