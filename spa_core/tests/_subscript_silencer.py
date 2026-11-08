#!/usr/bin/env python3
"""ГРОМКОСТЬ индексирующего чтения — величина ИЗМЕРИМАЯ, а не выводимая из формы.

# LLM_FORBIDDEN

**Что это закрывает.** ADR-947 назвал индексацию производного имени (`x[k]`)
крупнейшей оставшейся формой чтения у оси направления вреда — **78 чтений, 42 %** —
и отнёс её к ГРОМКОЙ половине класса (ADR-945) со словами «над ПУСТЫМ поднимает
`KeyError`/`IndexError` ⇒ пустота замечена ГРОМКО; предмета здесь нет вовсе».

Это утверждение было ОБЪЯВЛЕНО ПО ФОРМЕ, а не измерено, и сам ADR-947 назвал его
кандидатом на замер: `x[k]` внутри `try/except KeyError` **МОЛЧИТ**, и тогда это
тишина — опасная половина класса, — а не шум. Разница не косметическая: «предмета
здесь нет вовсе» снимает с приоритета 42 % остатка, и если хоть одно из 78 чтений
стоит под глушителем, снято оно НЕВЕРНО.

Прибор отвечает на ОДИН вопрос: **замечена ли пустота этим чтением громко?**

| исход | что значит |
|---|---|
| `loud` | глушителя в области связывания нет — над пустым поднимется `LookupError` |
| `silenced` | глушитель НАЗВАН: чтение под `try` с ловящим обработчиком либо под охраной |
| `unmeasured` | форма не разобрана (род ловимого исключения, подъём за предел) |

**Ошибаться обязано в сторону `unmeasured`, а НЕ в сторону `loud`** (требование
заказа G937 п. 2). Поэтому глушителем считаются ДВА рода, а не один:

1. **`try`-обработчик** — чтение лежит в ТЕЛЕ `try`, и хотя бы один обработчик ловит
   род из `SILENCING_EXCEPTIONS` (или это `except:` без рода). `orelse` и `finally`
   телом НЕ считаются: исключение из них наружу уходит, обработчики их не кроют.
2. **ОХРАНА** — чтение лежит в теле `if`, чьё условие над ПУСТЫМ перечнем ложно по
   построению: `if NAME:` либо `if … in NAME:`. Ветка не срабатывает вовсе, и
   `KeyError` не поднимается — то есть пустота замечена ТИХО. Не спросить про охрану
   значило бы назвать такое чтение `loud`, то есть ошибиться в ОПАСНУЮ сторону.

**Объявленная граница: ВЫЗЫВАЮЩИХ прибор НЕ СПРАШИВАЕТ.** Подъём кончается на
границе области связывания (`FunctionDef`/`Lambda`/`Module`), и `x[k]`, громкий
внутри своей функции, может быть заглушён `try` у вызывающего. Население ЭТОЙ формы
прибором НЕ ИЗМЕРЕНО, и исход `loud` несёт границу в своей причине дословно — чтобы
«громко здесь» нельзя было прочитать как «громко вообще».

**Чего прибор НЕ считает глушителем и почему.** Сосед `.get()` — другое ЧТЕНИЕ, а не
глушитель этого: `x.get(k)` рядом с `x[k]` не мешает второму поднять `KeyError`.
Обработчик чужого рода (`except ValueError`) глушителем не является, и подъём после
него ПРОДОЛЖАЕТСЯ: `try` бывает вложен в `try`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.monitoring import declared_collection_census as census_mod
from spa_core.tests import _empty_collection_harm as harm

#: Роды исключений, ловля которых ГЛУШИТ пустоту индексирующего чтения. `Exception`
#: и `BaseException` входят, потому что `LookupError` — их потомок; `except:` без
#: рода ловит всё и представлен отдельным значением `BARE`.
SILENCING_EXCEPTIONS = frozenset({
    "KeyError", "IndexError", "LookupError", "Exception", "BaseException",
})

#: Обработчик без объявленного рода (`except:`).
BARE = "<bare>"

#: Предел подъёма по разбору. Исчерпание — ТРЕТИЙ исход, а не `loud`.
CLIMB_DEPTH = 40

#: Исходы вопроса о громкости. «Не измерено» ни за один из двух не выдаётся (инв. #17).
OUTCOMES: Tuple[str, ...] = ("loud", "silenced", "unmeasured")

#: Роды глушителя. Считаются ОТДЕЛЬНО и в одно число не складываются.
SILENCER_KINDS: Tuple[str, ...] = ("try", "guard")


def handler_catches(handler: ast.ExceptHandler) -> Optional[List[str]]:
    """Имена родов, которые ловит обработчик, либо ``None`` = НЕ РАЗОБРАНО.

    ``None`` обязано доехать до вердикта как `unmeasured`: обработчик, чей род
    собирается выражением (`except (E[0]):`, `except pick():`), может ловить
    `KeyError`, а может не ловить, и угадать это нечем.
    """
    node = handler.type
    if node is None:
        return [BARE]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        out: List[str] = []
        for item in node.elts:
            if isinstance(item, ast.Name):
                out.append(item.id)
            elif isinstance(item, ast.Attribute):
                out.append(item.attr)
            else:
                return None
        return out
    return None


def _guard_silences(test: ast.expr, name: str) -> Optional[str]:
    """Причина, по которой условие ЛОЖНО над пустым ``name``, либо ``None``."""
    if isinstance(test, ast.Name) and test.id == name:
        return f"`if {name}:` — над пустым ветка НЕ срабатывает"
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and isinstance(test.ops[0], ast.In) \
            and isinstance(test.comparators[0], ast.Name) \
            and test.comparators[0].id == name:
        return f"`… in {name}:` — над пустым ветка НЕ срабатывает"
    return None


def silencer_of_one_subscript(
    sub: ast.Subscript, name: str, parents: Dict[int, ast.AST]
) -> Tuple[str, Optional[str], str]:
    """Громкость ОДНОГО чтения ``name[…]``: ``(исход, род глушителя, причина)``.

    Исход — член :data:`OUTCOMES`. Подъём идёт от самого чтения вверх и кончается на
    границе области связывания; род глушителя назван только у `silenced`.
    """
    child: ast.AST = sub
    current: Optional[ast.AST] = parents.get(id(sub))
    for _hop in range(CLIMB_DEPTH):
        if current is None:
            return "unmeasured", None, "подъём вышел за разбор — область не найдена"
        if isinstance(current, ast.Try) \
                and any(harm._contains(stmt, child) for stmt in current.body):
            for handler in current.handlers:
                caught = handler_catches(handler)
                if caught is None:
                    return ("unmeasured", None,
                            "род ловимого исключения НЕ РАЗОБРАН — заглушает или нет, "
                            "из формы не следует")
                if BARE in caught or (set(caught) & SILENCING_EXCEPTIONS):
                    return ("silenced", "try",
                            f"чтение в теле `try`, обработчик ловит {sorted(caught)}")
            # Обработчики чужого рода пустоту не глушат — подъём ПРОДОЛЖАЕТСЯ:
            # `try` бывает вложен в `try`, и внешний может ловить `KeyError`.
        if isinstance(current, ast.If) \
                and any(harm._contains(stmt, child) for stmt in current.body):
            why = _guard_silences(current.test, name)
            if why is not None:
                return "silenced", "guard", why
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.Lambda, ast.Module)):
            return ("loud", None,
                    "глушителя в области связывания нет ⇒ над пустым поднимется "
                    "LookupError (ВЫЗЫВАЮЩИХ прибор НЕ СПРАШИВАЛ — граница объявлена)")
        child, current = current, parents.get(id(current))
    return "unmeasured", None, f"подъём длиннее предела ({CLIMB_DEPTH})"


def _load(root: Path, rel: str, cache: Dict[str, Any]) -> Tuple[Any, Any]:
    if rel not in cache:
        try:
            tree = ast.parse((root / rel).read_text(errors="replace"))
        except (OSError, SyntaxError, ValueError) as exc:
            cache[rel] = (None, f"{type(exc).__name__}: {exc}")
        else:
            cache[rel] = (tree, harm._parents(tree))
    return cache[rel]


def seeds_of(rows: Sequence[Dict[str, Any]], root: Path,
             cache: Dict[str, Any]) -> List[Tuple[str, str, ast.AST, ast.AST, Any]]:
    """Засевы производного имени у входных объявлений — ТЕМИ ЖЕ дверями, что ось.

    Второй копии прослеживания здесь нет: все решения («цикл над именем»,
    «имя дано», «область связывания», «второе связывание») принимают функции
    `_empty_collection_harm`. Паритет с осью держит проба.
    """
    seen, out = set(), []
    for row in rows:
        for place in row.get("reads", {}).get("loop", []):
            rel, _, lineno = place.rpartition(":")
            tree, index = _load(root, rel, cache)
            if tree is None:
                continue
            hits = [
                node for node in ast.walk(tree)
                if getattr(node, "lineno", None) == int(lineno)
                and ((isinstance(node, ast.Name) and node.id == row["name"])
                     or (isinstance(node, ast.Attribute)
                         and node.attr == row["name"]))
            ]
            for hit in hits:
                kind, loop = harm._enclosing_loop(hit, index)
                if loop is None or kind != "comprehension":
                    continue
                owner = index.get(id(loop))
                if not isinstance(owner, (ast.ListComp, ast.SetComp, ast.DictComp)):
                    continue
                host = index.get(id(owner))
                derived = harm.bound_name(host)
                if derived is None:
                    continue
                scope, _why = harm._enclosing_scope(host, index)
                if scope is None or harm.rebinding_of(scope, derived) is not None:
                    continue
                token = (rel, derived, id(host))
                if token in seen:
                    continue
                seen.add(token)
                out.append((rel, derived, host, scope, index))
    return out


def subscript_reads(root: Optional[Path] = None) -> Dict[str, Any]:
    """Громкость КАЖДОГО индексирующего чтения производного имени.

    **Область ОБЪЯВЛЕНА, а не подразумевается:** спрашивается у засевов тех
    объявлений, чей род ось направления ВСЁ ЕЩЁ не назвала (`direction ==
    "unmeasured"`). Это ровно та область, в которой ответ способен изменить вердикт,
    и ровно она воспроизводит число ADR-947 (замер 08.11 на `e904991fe`: **78**).
    Засевы объявлений с уже названным родом в область не входят: их вердикт
    индексацией не изменится (замер того же дня — 116 чтений на всех кандидатах).
    """
    root = root or harm.REPO_ROOT
    result = census_mod.census()
    subjects = [row for row in result["rows"] if row["subject"]]
    signal = harm.production(subjects)
    by_key = {harm.key(r["module"], r["name"]): r for r in subjects}
    candidates = [by_key[harm.key(r["module"], r["name"])]
                  for r in signal["rows"] if r["production"] == "produces"]
    axis = harm.direction(candidates)
    still = {harm.key(r["module"], r["name"]) for r in axis["rows"]
             if r["direction"] == "unmeasured"}
    scoped = [row for row in candidates
              if harm.key(row["module"], row["name"]) in still]

    cache: Dict[str, Any] = {}
    tally = {outcome: 0 for outcome in OUTCOMES}
    kinds = {kind: 0 for kind in SILENCER_KINDS}
    rows: List[Dict[str, Any]] = []
    for rel, name, host, scope, index in seeds_of(scoped, root, cache):
        outcome, why = harm._direction_through_name(
            name, host, index, harm.SEED_HOPS - 1)
        if outcome != "unmeasured" or "рода не дало ни одно чтение" not in why:
            continue
        asked = {id(node)
                 for node in harm._direction_reads_of(scope, name, host, index)}
        for node in ast.walk(scope):
            if not (isinstance(node, ast.Name) and node.id == name
                    and isinstance(node.ctx, ast.Load)):
                continue
            if harm._contains(host, node) or id(node) in asked:
                continue
            parent = index.get(id(node))
            if not (isinstance(parent, ast.Subscript) and parent.value is node):
                continue
            verdict, kind, reason = silencer_of_one_subscript(parent, name, index)
            tally[verdict] += 1
            if kind is not None:
                kinds[kind] += 1
            rows.append({"module": rel, "name": name, "lineno": node.lineno,
                         "loudness": verdict, "silencer": kind, "why": reason})
    return {"tally": tally, "silencer_kinds": kinds, "rows": rows,
            "scope": {"declarations_still_unmeasured": len(still),
                      "candidates": len(candidates),
                      "subjects": len(subjects)},
            "axis_tally": axis["tally"],
            "unparsable_readers": {rel: val for rel, (tree, val) in cache.items()
                                   if tree is None}}
