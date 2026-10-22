"""Словари, которые функция действительно ОТДАЁТ: `return {...}` или `doc = {...}` … `return doc`.

Проверки проводки переписей («результат шага уехал в документ») искали только форму
`return {...}`. Перепись `rule_second_copy_census.measure` собирает документ в имени и
возвращает имя (`doc = {...}; …; return doc`), и проверки отвергали ВЕРНУЮ проводку
(`tail_value_divergence`, `invisible_consumer_scale`: красные с прогона №6). Строгость та же:
словарь обязан дойти до `return`, ключ — указывать на связанное имя.
"""
from __future__ import annotations

import ast


def returned_dicts(fn: ast.FunctionDef) -> list[ast.Dict]:
    """Литералы-словари, которые доходят до `return` функции `fn` (напрямую или через имя)."""
    returned_names = set()
    out: list[ast.Dict] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Dict):
                out.append(node.value)
            elif isinstance(node.value, ast.Name):
                returned_names.add(node.value.id)
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id in returned_names for t in node.targets)):
            out.append(node.value)
    return out
