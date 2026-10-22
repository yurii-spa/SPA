"""Население ступени переписей моста — ОДНА копия правила (храповик и его потребитель).

Зов ступени — любой `X.run(...)` с `root=args.root` в `findings_bridge.py`; `X` — ИМЯ
ПЕРЕМЕННОЙ, разрешаемое по импортам самого моста (`... import acceptance_tree_capability
as _atc`). Прежде храповик `test_census_stage_root_contract` держал правило у себя, а
потребитель `census_consumer_census` искал в нём регулярку `X.findall` — после перевода
храповика на AST (22.10) потребитель честно отвечал «население НЕ выведено» (CI 39825423993).
Одна копия правила — два читателя, ни одной второй копии.

stdlib, без побочных эффектов.
"""
from __future__ import annotations

import ast
from pathlib import Path

#: Нет литерального значения у аргумента зова — воспроизвести зов потребителя нельзя.
NOT_LITERAL = object()


def bridge_import_names(src: str) -> dict:
    """Локальное имя в мосте → имя модуля `spa_core.monitoring.*` (по всему файлу, вкл. тела)."""
    names: dict = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "spa_core.monitoring":
            for a in node.names:
                names[a.asname or a.name] = a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and a.name.startswith("spa_core.monitoring."):
                    names[a.asname] = a.name.rsplit(".", 1)[1]
    return names


def stage_calls(bridge: Path) -> dict:
    """Зовы ступени по AST: модуль → список наборов дополнительных аргументов."""
    src = Path(bridge).read_text(encoding="utf-8")
    imported = bridge_import_names(src)
    out: dict = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run" and isinstance(node.func.value, ast.Name)):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        if "root" not in kws or ast.unparse(kws["root"]) != "args.root" or node.args:
            continue
        extra = {}
        for k, v in kws.items():
            if k == "root":
                continue
            try:
                extra[k] = ast.literal_eval(v)
            except ValueError:
                extra[k] = NOT_LITERAL
        name = imported.get(node.func.value.id, node.func.value.id)
        if extra not in out.setdefault(name, []):
            out[name].append(extra)
    return out


def stage_censuses(bridge: Path) -> list:
    """Население ступени = все, кого она зовёт `….run(root=args.root[, …])` — по AST."""
    return sorted(stage_calls(bridge))
