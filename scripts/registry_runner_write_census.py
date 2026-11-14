#!/usr/bin/env python3
"""Замер «реестр → бегун»: куда пишут аналитики реестра, когда их зовёт бегун из песочницы (ADR-999 § 6в).

ADR-999 измерил читателей слепых точек входа класса «песочница без названного каталога данных» и назвал
76 из них `registry`: их зовёт не рука и не plist, а бегун `signal_aggregator` — по имени из
`_module_registry`, классом либо функцией модуля, — и КАТАЛОГА НЕ ПЕРЕДАЁТ. Дверь в `main()` (ADR-1000,
транш 1) для них инертна: бегун `main()` не зовёт никогда. Вопрос этого прибора — про сам бегун и про
тот путь, которым он входит в модуль:

    бегун построен с каталогом песочницы (`SignalAggregator(data_dir=<песочница>)`, так его зовут
    `cycle_runner` и `cycle_gates`); доходит ли этот каталог до модуля реестра — и если нет,
    достигает ли вход бегуна ЗАПИСИ на диск?

Две статические стороны (AST) и одно наблюдение (`--observe`):

1. **Бегун.** `_ENTRY_METHODS` читается из `signal_aggregator.py` ТОГО ЖЕ дерева (не копия правила);
   меряется, кладёт ли бегун ключ `"data_dir"` в контекст модуля (присваивание `ctx["data_dir"]` /
   словарь контекста с таким ключом внутри `_ModuleAdapter`/`SignalAggregator`).
2. **Модуль реестра** — каждая запись `_module_registry`. Вход бегуна выбирается ТЕМ ЖЕ правилом, что
   `_ModuleAdapter._import_callable` + `_invoke`: класс записи, если он есть в файле и строится без
   аргументов, иначе сам модуль; первый метод из `_ENTRY_METHODS`, принимающий контекст (параметр
   `context`, либо один позиционный, либо `*args`/`**kwargs`). От входа — достижимость записи по графу
   вызовов ВНУТРИ модуля (функции модуля, методы `self`, конструкторы и методы классов модуля — по
   имени, с избытком: ошибка в сторону НАХОДКИ). Записью считаются `atomic_save` · `write_text/bytes` ·
   `open(…, "w"/"a"/"x"/"+")` · `json.dump` · `mkdir`/`os.makedirs` · `shutil.copy*/move` ·
   `os.replace/rename`. Отдельно: читает ли модуль `data_dir` из контекста (дверь у МОДУЛЯ есть, бегун
   её не открывает) и спрашивает ли он `SPA_DATA_DIR`.

Вердикт модуля:

* `NO_ENTRY` — у бегуна нет входа, принимающего контекст (у бегуна это `unchecked`): записи по этому
  пути нет;
* `WRITE_REACHABLE` — вход достигает ≥1 записи; под песочницей она ляжет в УМОЛЧАНИЕ модуля (дерево
  модуля либо `data` от cwd) — каталог бегуна до неё не доходит, если бегун его не передаёт;
* `DELEGATES_OUT` — своей записи вход не достигает, но зовёт ЧУЖИЕ модули аналитики: запись там прибор
  НЕ следит — третий исход, не «чисто»;
* `NO_WRITE_REACHED` — вход есть, ни записи, ни делегирования;
* `UNMEASURED` — файл не найден или не разобран (причина названа).

Две формы, где статика честно уступает бегуну и говорит об этом: класс записи, ВВЕЗЁННЫЙ в модуль из
другого файла (бегун возьмёт его `getattr`, а его методы здесь не разобрать) — `DELEGATES_OUT` с именем
класса; `@dataclass` без своего `__init__` строится без аргументов только если у всех полей есть
значения. Вход с доменной аннотацией (`analyze(positions: list)`) бегун зовёт и, если тот упал,
отвечает `unchecked` ПОСЛЕ вызова — статика это не предсказывает, а лишь считает (`entry_non_mapping_annotation`).

`--observe <дерево>` — наблюдение: НАСТОЯЩИЙ бегун названного дерева зовёт каждый модуль одним
протоколом, с каталогом-песочницей и cwd в ОТДЕЛЬНОМ пустом каталоге; записи наблюдаются корзинами
(каталог бегуна · `data/` дерева · `data/` от cwd · прочее в дереве) и сверяются со статикой поимённо
(парность входа: статический `NO_ENTRY` против `unchecked` бегуна). Отказывает (код 2), если дерево —
прод-дерево или git-дерево: писать туда значило бы воспроизвести предмет замера. Записи по абсолютным
путям ВНЕ дерева, cwd и песочницы наблюдение не видит — это сказано в итоге, не замалчивается.

Коды: 0 — предмет пуст и измерен (ни одного `WRITE_REACHABLE`, умолчание которого достижимо у бегуна) ·
1 — предмет назван · 2 — НЕ ИЗМЕРЕНО (реестр/бегун не прочитаны, `_ENTRY_METHODS` не найден, пустая
поверхность). Как у соседних переписей: `UNMEASURED` у отдельных модулей не прячет названный предмет.

    python3 scripts/registry_runner_write_census.py [--repo-root <дерево>] [--readers-json <callers.json>] [--json]
    python3 scripts/registry_runner_write_census.py --observe <одноразовое дерево> [--timeout 3] [--protocol aave_v3]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

REGISTRY_REL = "spa_core/analytics/_module_registry.py"
RUNNER_REL = "spa_core/analytics/signal_aggregator.py"
ANALYTICS_PKG = "spa_core/analytics"
ANALYTICS_DOTTED = "spa_core.analytics"

#: Ключ контекста, которым модуль мог бы получить каталог от бегуна.
DATA_DIR_KEY = "data_dir"
#: Переменная окружения песочницы данных.
ENV_KEY = "SPA_DATA_DIR"
#: Имя параметра, которым `_invoke` передаёт контекст именованно.
CONTEXT_PARAM = "context"

VERDICTS = ("NO_ENTRY", "WRITE_REACHABLE", "DELEGATES_OUT", "NO_WRITE_REACHED", "UNMEASURED")

#: Ось «у какого ПАРАМЕТРА дверь» (ADR-1004 § 6а; до неё прибор судил по КЛЮЧУ: `ctx["data_dir"]` где
#: угодно в файле читалось как «модуль читает каталог бегуна», и у `protocol_defi_yield_duration_mismatch_analyzer`
#: до ADR-1004 это было ложно — ключ читался у `config`, а бегун биндит контекст в `protocols`).
#:   CONTEXT_PARAM  — ≥1 чтение ключа у имени, которому бегун отдаёт контекст (само имя, его псевдоним,
#:                    параметр помощника, которому оно передано, атрибут `self`, в который оно положено);
#:   FOREIGN_PARAM  — ключ читается, но НИ ОДНО чтение не достигает связанного имени: все — у чужого
#:                    параметра/атрибута (`config`, `self.config`, …) либо в функции, куда контекст не доходит;
#:   NONE           — ключ не читается вовсе;
#:   UNRESOLVED     — ключ читается, а связанное имя назвать нельзя (входа у бегуна нет; контекст идёт в
#:                    `*args`/`**kwargs` без имени) — третий исход, не «читает» и не «не читает».
#: Распространение СТРОГОЕ: контейнер (`[ctx]`, `{"k": ctx}`) и результат чужого вызова (`f(ctx)`) связью
#: НЕ являются — ошибка идёт в сторону FOREIGN_PARAM, то есть находки, а не её отсутствия.
DOOR_OUTCOMES = ("CONTEXT_PARAM", "FOREIGN_PARAM", "NONE", "UNRESOLVED")

#: Формы записи. `os.replace`/`os.rename`/`os.makedirs`/`shutil.*`/`json.dump` — только у СВОЕГО модуля
#: (`str.replace` записью не является); `write_text`/`write_bytes`/`mkdir` — у любого объекта;
#: `atomic_save` — именем либо атрибутом; `open` — с режимом записи.
_OS_WRITES = {"replace", "rename", "makedirs"}
_SHUTIL_WRITES = {"copy", "copy2", "copyfile", "copytree", "move"}
_ANY_ATTR_WRITES = {"write_text", "write_bytes", "mkdir"}
_WRITE_MODES = set("wax+")


class NotMeasured(RuntimeError):
    """Прибор не смог ответить: причина — в тексте."""


@dataclass
class WriteSite:
    func: str            # где лежит запись (функция / Класс.метод)
    line: int
    form: str            # atomic_save · write_text · open:w · json.dump · mkdir · shutil.copy · os.replace


@dataclass
class ReadSite:
    func: str            # где лежит чтение ключа (функция / Класс.метод / «<модуль>»)
    line: int
    base: str            # у кого читается: текст базы (`config`, `context`, `self._ctx`, …)
    bound: bool          # достигает ли база имени, которому бегун отдал контекст


@dataclass
class ModuleVerdict:
    module: str                       # имя записи реестра (stem, может быть dotted)
    tier: str
    path: str                         # относительный путь файла
    registry_class: Optional[str]
    runner_target: str                # class · module · module (класс не найден) · module (класс требует аргументов)
    entry: Optional[str]              # выбранный вход бегуна (имя метода/функции) либо None
    verdict: str
    writes: List[WriteSite] = field(default_factory=list)
    delegates: List[str] = field(default_factory=list)
    reads_context_data_dir: bool = False   # по КЛЮЧУ: `"data_dir"` читается где-то в файле (ось ADR-1002)
    data_dir_door: str = "NONE"            # по ПАРАМЕТРУ: один из DOOR_OUTCOMES (ось ADR-1004 § 6а)
    data_dir_door_reason: Optional[str] = None   # у UNRESOLVED — почему связанное имя не названо
    data_dir_reads: List[ReadSite] = field(default_factory=list)
    reads_env_data_dir: bool = False
    init_unknown: bool = False        # конструктор класса не разобран (база вне модуля) — принят строящимся
    entry_annotation: Optional[str] = None  # аннотация входа контекста: не-Mapping ⇒ бегун может ответить unchecked ПОСЛЕ вызова
    blind_cli: Optional[str] = None   # default_origin из callers.json, если модуль в 76 (literal/module_tree/other)
    reason: Optional[str] = None


@dataclass
class RunnerSide:
    entry_methods: Tuple[str, ...]
    passes_data_dir: bool
    runner_path: str


@dataclass
class Census:
    root: str
    runner: RunnerSide
    modules: List[ModuleVerdict]
    counts: Dict[str, int]
    exposure: Dict[str, int]
    blind_subset: Optional[Dict[str, int]]   # счёт вердиктов среди 76 (если callers.json дан)
    code: int
    unmeasured_reason: Optional[str] = None


# ─────────────────────────── чтение бегуна ───────────────────────────

def _read_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def read_runner(repo: Path) -> RunnerSide:
    """`_ENTRY_METHODS` и «кладёт ли бегун data_dir в контекст» — из AST бегуна этого дерева."""
    runner = repo / RUNNER_REL
    if not runner.is_file():
        raise NotMeasured(f"бегуна нет: {runner}")
    try:
        tree = _read_tree(runner)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        raise NotMeasured(f"бегун не разобран: {type(exc).__name__}: {exc}")
    methods: Optional[Tuple[str, ...]] = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_ENTRY_METHODS" for t in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                vals = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
                if vals and all(isinstance(v, str) for v in vals):
                    methods = tuple(str(v) for v in vals)
    if not methods:
        raise NotMeasured("в бегуне не найдено объявление `_ENTRY_METHODS` (кортеж строк)")
    passes = False
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for node in ast.walk(cls):
            # ctx["data_dir"] = … / context["data_dir"] = …
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Subscript) and _const(t.slice) == DATA_DIR_KEY:
                        passes = True
            # {"data_dir": …} внутри бегуна · ctx.setdefault("data_dir", …) · ctx.update(data_dir=…)
            if isinstance(node, ast.Dict) and any(_const(k) == DATA_DIR_KEY for k in node.keys if k is not None):
                passes = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("setdefault", "update"):
                if node.args and _const(node.args[0]) == DATA_DIR_KEY:
                    passes = True
                if any(kw.arg == DATA_DIR_KEY for kw in node.keywords):
                    passes = True
    return RunnerSide(entry_methods=methods, passes_data_dir=passes, runner_path=RUNNER_REL)


# ─────────────────────────── чтение реестра ───────────────────────────

def read_registry(repo: Path) -> List[Dict[str, object]]:
    """Записи `_module_registry` — литералами из AST (без импорта чужого дерева)."""
    reg = repo / REGISTRY_REL
    if not reg.is_file():
        raise NotMeasured(f"реестра нет: {reg}")
    try:
        tree = _read_tree(reg)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        raise NotMeasured(f"реестр не разобран: {type(exc).__name__}: {exc}")
    entries: List[Dict[str, object]] = []
    for node in tree.body:
        # TIER_A_MODULES: List[...] = [...] — это AnnAssign; без аннотации — Assign. Обе формы — реестр.
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.List):
            continue
        for elt in node.value.elts:
            if not isinstance(elt, ast.Dict):
                continue
            try:
                d = ast.literal_eval(elt)
            except (ValueError, SyntaxError):
                continue
            if isinstance(d, dict) and isinstance(d.get("module"), str):
                entries.append(d)
    if not entries:
        raise NotMeasured("в реестре не найдено ни одной записи `{\"module\": …}`")
    return entries


# ─────────────────────────── AST-помощники ───────────────────────────

def _const(node: Optional[ast.AST]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _decorators(fn: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for d in getattr(fn, "decorator_list", []):
        if isinstance(d, ast.Name):
            out.add(d.id)
        elif isinstance(d, ast.Attribute):
            out.add(d.attr)
    return out


def _accepts_context(fn: Any, *, is_method: bool) -> bool:
    """Повтор правила `_invoke`: сначала `fn(context=ctx)`, затем `fn(ctx)`; первое удачное — вход."""
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    decos = _decorators(fn)
    if is_method and "staticmethod" not in decos and pos:
        pos = pos[1:]                       # self / cls скрыты связыванием
    n_pos = len(pos)
    n_def = len(a.defaults)
    required_pos = pos[: max(0, n_pos - n_def)]
    kwonly_required = [k for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    pos_names = [p.arg for p in pos]
    kw_names = [k.arg for k in a.kwonlyargs]
    # форма 1: context=ctx
    if CONTEXT_PARAM in pos_names or CONTEXT_PARAM in kw_names or a.kwarg is not None:
        required = [p.arg for p in required_pos] + [k.arg for k in kwonly_required]
        if all(r == CONTEXT_PARAM for r in required):
            return True
    # форма 2: (ctx)
    if n_pos >= 1:
        if not required_pos[1:] and not kwonly_required:
            return True
    elif a.vararg is not None and not kwonly_required:
        return True
    return False


def _constructible(cls: ast.ClassDef, classes: Dict[str, ast.ClassDef]) -> Tuple[bool, bool]:
    """(строится без аргументов?, разобрано ли). База вне модуля без своего `__init__` — не разобрано."""
    seen: Set[str] = set()
    cur: Optional[ast.ClassDef] = cls
    while cur is not None and cur.name not in seen:
        seen.add(cur.name)
        init = next((n for n in cur.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "__init__"), None)
        if init is None and "dataclass" in _decorators(cur):
            # @dataclass порождает __init__ из полей: поле без значения и без field(default…) — обязательное
            required_fields = [n for n in cur.body if isinstance(n, ast.AnnAssign) and n.simple
                               and not _field_has_default(n.value)]
            return (not required_fields), True
        if init is not None:
            a = init.args
            pos = (list(a.posonlyargs) + list(a.args))[1:]
            required = pos[: max(0, len(pos) - len(a.defaults))]
            kwonly_required = [k for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
            return (not required and not kwonly_required), True
        bases = [b.id for b in cur.bases if isinstance(b, ast.Name)]
        in_module = [classes[b] for b in bases if b in classes]
        if not bases:
            return True, True                 # нет базы и нет __init__ → object()
        if in_module:
            cur = in_module[0]
            continue
        return True, False                    # база вне модуля: конструктор не разобран
    return True, False


def _field_has_default(value: Optional[ast.AST]) -> bool:
    if value is None:
        return False
    if isinstance(value, ast.Call):
        fname = value.func.id if isinstance(value.func, ast.Name) else getattr(value.func, "attr", None)
        if fname == "field":
            return any(kw.arg in ("default", "default_factory") for kw in value.keywords)
    return True


def _imported_names(tree: ast.Module) -> Set[str]:
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                out.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.asname or a.name.split(".")[0])
    return out


def _module_level_assigned(tree: ast.Module, name: str) -> Optional[str]:
    """`name = <выражение>` на уровне модуля → текст правой части (первые 60 символов), иначе None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == name for x in node.targets):
            return ast.unparse(node.value)[:60]
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.unparse(node.value)[:60] if node.value is not None else "<аннотация>"
    return None


def _entry_annotation(fn: Any, *, is_method: bool) -> Optional[str]:
    """Аннотация параметра, которому бегун отдаст контекст (первый позиционный после self), текстом."""
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if is_method and "staticmethod" not in _decorators(fn) and pos:
        pos = pos[1:]
    for p in pos:
        if p.arg == CONTEXT_PARAM or p is pos[0]:
            return ast.unparse(p.annotation) if p.annotation is not None else None
    return None


def _methods(cls: ast.ClassDef, classes: Dict[str, ast.ClassDef]) -> Dict[str, Tuple[str, ast.AST]]:
    """Методы класса с учётом баз ВНУТРИ модуля: имя → (класс-владелец, узел)."""
    out: Dict[str, Tuple[str, ast.AST]] = {}
    order: List[ast.ClassDef] = []
    seen: Set[str] = set()
    stack = [cls]
    while stack:
        c = stack.pop(0)
        if c.name in seen:
            continue
        seen.add(c.name)
        order.append(c)
        for b in c.bases:
            if isinstance(b, ast.Name) and b.id in classes:
                stack.append(classes[b.id])
    for c in order:
        for n in c.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in out:
                out[n.name] = (c.name, n)
    return out


def _analytics_imports(tree: ast.Module, own_stem: str) -> Set[str]:
    """Имена, ввезённые из ДРУГИХ модулей аналитики (где угодно в файле) — делегирование наружу."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:
                # from . import x  /  from ._apy_series import get_series
                if mod == "" :
                    for a in node.names:
                        if a.name != own_stem:
                            names.add(a.asname or a.name)
                else:
                    for a in node.names:
                        names.add(a.asname or a.name)
            elif mod == ANALYTICS_DOTTED:
                for a in node.names:
                    if a.name != own_stem:
                        names.add(a.asname or a.name)
            elif mod.startswith(ANALYTICS_DOTTED + ".") and mod.split(".")[-1] != own_stem:
                for a in node.names:
                    names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(ANALYTICS_DOTTED + ".") and a.name.split(".")[-1] != own_stem:
                    names.add(a.asname or a.name.split(".")[-1])
    return names


def _write_form(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Name):
        if f.id == "atomic_save":
            return "atomic_save"
        if f.id == "open":
            return "open:w" if _open_writes(call) else None
        if f.id == "dump":
            return "json.dump"
        if f.id in _OS_WRITES or f.id in _SHUTIL_WRITES:
            return f"os/shutil.{f.id}"
        return None
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else None
        if f.attr == "atomic_save":
            return "atomic_save"
        if f.attr in _ANY_ATTR_WRITES:
            return f.attr
        if f.attr == "open" and _open_writes(call):
            return "open:w"
        if base == "json" and f.attr == "dump":
            return "json.dump"
        if base == "os" and f.attr in _OS_WRITES:
            return f"os.{f.attr}"
        if base == "shutil" and f.attr in _SHUTIL_WRITES:
            return f"shutil.{f.attr}"
    return None


def _open_writes(call: ast.Call) -> bool:
    mode: Optional[str] = None
    if len(call.args) >= 2:
        mode = _const(call.args[1])
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = _const(kw.value)
    # Path.open("w") — режим первым позиционным
    if isinstance(call.func, ast.Attribute) and call.args and mode is None:
        mode = _const(call.args[0])
    return bool(mode) and any(ch in _WRITE_MODES for ch in mode)


def _reads_context_data_dir(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _const(node.slice) == DATA_DIR_KEY:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "pop") and node.args and _const(node.args[0]) == DATA_DIR_KEY:
            return True
    return False


def _reads_env(tree: ast.Module) -> bool:
    return any(_const(n) == ENV_KEY for n in ast.walk(tree))


# ─────────────── ось «у какого параметра дверь» (ADR-1004 § 6а) ───────────────

def _read_base(node: ast.AST) -> Optional[ast.AST]:
    """База чтения ключа `data_dir`: `X["data_dir"]` → X; `X.get("data_dir")`/`X.pop(...)` → X; иначе None."""
    if isinstance(node, ast.Subscript) and _const(node.slice) == DATA_DIR_KEY:
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("get", "pop") and node.args and _const(node.args[0]) == DATA_DIR_KEY:
        return node.func.value
    return None


def _bound_context_name(fn: Any, *, is_method: bool) -> Tuple[Optional[str], Optional[str]]:
    """Имя параметра, в который `_invoke` биндит контекст, — тем же правилом, что `_accepts_context`.

    Возвращает (имя, None) либо (None, причина): форма 1 (`context=ctx`) — параметр `context`, если он есть
    по имени; если форма 1 проходит только через `**kwargs` — имени нет (контекст лежит в `kwargs["context"]`);
    форма 2 (`fn(ctx)`) — первый позиционный после `self`; только `*args` — имени нет.
    """
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if is_method and "staticmethod" not in _decorators(fn) and pos:
        pos = pos[1:]
    n_def = len(a.defaults)
    required_pos = pos[: max(0, len(pos) - n_def)]
    kwonly_required = [k for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    pos_names = [p.arg for p in pos]
    kw_names = [k.arg for k in a.kwonlyargs]
    if CONTEXT_PARAM in pos_names or CONTEXT_PARAM in kw_names or a.kwarg is not None:
        required = [p.arg for p in required_pos] + [k.arg for k in kwonly_required]
        if all(r == CONTEXT_PARAM for r in required):
            if CONTEXT_PARAM in pos_names or CONTEXT_PARAM in kw_names:
                return CONTEXT_PARAM, None
            return None, f"контекст уходит в **{a.kwarg.arg} под ключом `{CONTEXT_PARAM}` — имени параметра нет"
    if pos:
        if not required_pos[1:] and not kwonly_required:
            return pos[0].arg, None
    elif a.vararg is not None and not kwonly_required:
        return None, f"контекст уходит в *{a.vararg.arg} — имени параметра нет"
    return None, "вход бегуна не принимает контекст"


def _carrying_names(expr: ast.AST, names: Set[str], self_attrs: Set[str]) -> bool:
    """Несёт ли выражение связанный контекст. СТРОГО: имя · `self.attr` из набора · `a or b`/`a if c else b`
    из несущих · `dict(x)`/`x.copy()` несущего. Контейнер и чужой вызов — НЕ связь (ошибка в сторону находки)."""
    if isinstance(expr, ast.Name):
        return expr.id in names
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == "self":
        return expr.attr in self_attrs
    if isinstance(expr, ast.BoolOp):
        return any(_carrying_names(v, names, self_attrs) for v in expr.values)
    if isinstance(expr, ast.IfExp):
        return _carrying_names(expr.body, names, self_attrs) or _carrying_names(expr.orelse, names, self_attrs)
    if isinstance(expr, ast.Call):
        f = expr.func
        if isinstance(f, ast.Name) and f.id == "dict" and len(expr.args) == 1 and not expr.keywords:
            return _carrying_names(expr.args[0], names, self_attrs)
        if isinstance(f, ast.Attribute) and f.attr == "copy" and not expr.args:
            return _carrying_names(f.value, names, self_attrs)
    return False


def _params_of(fn: Any, *, is_method: bool) -> Tuple[List[str], Set[str]]:
    """(позиционные имена без self, все имена параметров) — для сопоставления аргументов вызова."""
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if is_method and "staticmethod" not in _decorators(fn) and pos:
        pos = pos[1:]
    names = {p.arg for p in pos} | {k.arg for k in a.kwonlyargs}
    return [p.arg for p in pos], names


def _data_dir_door(tree: ast.Module, funcs: Dict[str, ast.AST], classes: Dict[str, ast.ClassDef],
                   all_methods: Dict[str, List[Tuple[str, ast.AST]]], node_of, entry_key: Tuple[str, ...],
                   bound: Optional[str]) -> Tuple[str, Optional[str], List[ReadSite]]:
    """Распространить связанное имя по графу вызовов модуля и судить КАЖДОЕ чтение ключа `data_dir`.

    Возвращает (исход из DOOR_OUTCOMES, причина для UNRESOLVED, чтения поимённо).
    """
    # функция-владелец каждого узла (первый уровень вложенности: методы классов и функции модуля)
    owner: Dict[int, Tuple[str, ...]] = {}
    for name, fn in funcs.items():
        for n in ast.walk(fn):
            owner[id(n)] = ("f", name)
    for cname, c in classes.items():
        for n in c.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(n):
                    owner[id(sub)] = ("m", cname, n.name)
    reads: List[Tuple[ast.AST, ast.AST, Optional[Tuple[str, ...]]]] = []
    for node in ast.walk(tree):
        base = _read_base(node)
        if base is not None:
            reads.append((node, base, owner.get(id(node))))
    if not reads:
        return "NONE", None, []
    if bound is None:
        return "UNRESOLVED", None, [ReadSite(func=(k[1] if k and k[0] == "f" else f"{k[1]}.{k[2]}" if k else "<модуль>"),
                                             line=n.lineno, base=ast.unparse(b), bound=False) for n, b, k in reads]

    carry: Dict[Tuple[str, ...], Set[str]] = {entry_key: {bound}}
    self_attrs: Dict[str, Set[str]] = {}          # класс → атрибуты self, несущие контекст
    changed = True
    rounds = 0
    while changed and rounds < 50:
        changed = False
        rounds += 1
        for key in list(carry):
            fn = node_of(key)
            if fn is None:
                continue
            names = carry[key]
            attrs = self_attrs.setdefault(key[1], set()) if key[0] == "m" else set()
            for node in ast.walk(fn):
                # псевдонимы: x = ctx · x = ctx or {} · self.a = ctx
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    if value is None or not _carrying_names(value, names, attrs):
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Name) and t.id not in names:
                            names.add(t.id); changed = True
                        elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self" \
                                and key[0] == "m" and t.attr not in attrs:
                            attrs.add(t.attr); changed = True
                    continue
                if not isinstance(node, ast.Call):
                    continue
                # вызовы: куда уходит несущее имя аргументом
                callees: List[Tuple[Tuple[str, ...], ast.AST, bool]] = []
                f = node.func
                if isinstance(f, ast.Name):
                    if f.id in funcs:
                        callees.append((("f", f.id), funcs[f.id], False))
                    elif f.id in classes:
                        for cname, n in all_methods.get("__init__", []):
                            if cname == f.id:
                                callees.append((("m", cname, "__init__"), n, True))
                elif isinstance(f, ast.Attribute):
                    for cname, n in all_methods.get(f.attr, []):
                        callees.append((("m", cname, f.attr), n, True))       # по имени, с избытком
                for ckey, cfn, is_m in callees:
                    pos_names, all_names = _params_of(cfn, is_method=is_m)
                    got: Set[str] = set()
                    for i, arg in enumerate(node.args):
                        if isinstance(arg, ast.Starred):
                            continue
                        if i < len(pos_names) and _carrying_names(arg, names, attrs):
                            got.add(pos_names[i])
                    for kw in node.keywords:
                        if kw.arg in all_names and _carrying_names(kw.value, names, attrs):
                            got.add(kw.arg)
                    if got:
                        cur = carry.setdefault(ckey, set())
                        if not got <= cur:
                            cur |= got; changed = True
                    elif ckey not in carry and is_m and ckey[1] in self_attrs and self_attrs[ckey[1]]:
                        carry[ckey] = set(); changed = True      # метод того же класса видит self.attr
    sites: List[ReadSite] = []
    any_bound = False
    for node, base, key in reads:
        label = "<модуль>" if key is None else (key[1] if key[0] == "f" else f"{key[1]}.{key[2]}")
        names = carry.get(key, set()) if key is not None else set()
        attrs = self_attrs.get(key[1], set()) if key is not None and key[0] == "m" else set()
        is_bound = _carrying_names(base, names, attrs)
        any_bound = any_bound or is_bound
        sites.append(ReadSite(func=label, line=node.lineno, base=ast.unparse(base), bound=is_bound))
    return ("CONTEXT_PARAM" if any_bound else "FOREIGN_PARAM"), None, sites


# ─────────────────────────── один модуль ───────────────────────────

def measure_module(repo: Path, entry: Dict[str, object], methods_order: Iterable[str]) -> ModuleVerdict:
    stem = str(entry["module"])
    tier = str(entry.get("tier") or "?")
    rel = f"{ANALYTICS_PKG}/{stem.replace('.', '/')}.py"
    raw_cls = entry.get("class")
    cls_name: Optional[str] = raw_cls if isinstance(raw_cls, str) else None
    path = repo / rel
    mv = ModuleVerdict(module=stem, tier=tier, path=rel, registry_class=cls_name,
                       runner_target="module", entry=None, verdict="UNMEASURED")
    if not path.is_file():
        mv.reason = "файла нет в дереве"
        return mv
    try:
        tree = _read_tree(path)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        mv.reason = f"не разобран: {type(exc).__name__}: {exc}"
        return mv

    funcs: Dict[str, ast.AST] = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes: Dict[str, ast.ClassDef] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    mv.reads_context_data_dir = _reads_context_data_dir(tree)
    mv.reads_env_data_dir = _reads_env(tree)
    delegate_names = _analytics_imports(tree, stem.split(".")[-1])

    # ── вход бегуна (правило _import_callable + _invoke) ──
    target_cls: Optional[str] = None
    if cls_name and cls_name not in classes:
        assigned = _module_level_assigned(tree, cls_name)
        if cls_name in _imported_names(tree) or assigned is not None:
            # бегун возьмёт имя через getattr(mod, cls): оно ВВЕЗЕНО из другого модуля либо СОБРАНО присваиванием
            # (`Cls = make_analyzer(...)`) — тела его методов в этом файле нет, разобрать нечего
            mv.runner_target = ("class (ввезён из другого модуля)" if assigned is None
                                else "class (собран присваиванием)")
            mv.entry = f"{cls_name}.<вне модуля>"
            mv.delegates = [cls_name if assigned is None else f"{cls_name} = {assigned}"]
            mv.verdict = "DELEGATES_OUT"
            return mv
    if cls_name:
        if cls_name in classes:
            ok, measured = _constructible(classes[cls_name], classes)
            mv.init_unknown = not measured
            if ok:
                target_cls = cls_name
                mv.runner_target = "class"
            else:
                mv.runner_target = "module (класс требует аргументов)"
        else:
            mv.runner_target = "module (класс не найден)"
    all_methods: Dict[str, List[Tuple[str, ast.AST]]] = {}
    for cname, c in classes.items():
        for n in c.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_methods.setdefault(n.name, []).append((cname, n))

    def node_of(key: Tuple[str, ...]) -> Optional[ast.AST]:
        if key[0] == "f":
            return funcs.get(key[1])
        for cname, n in all_methods.get(key[2], []):
            if cname == key[1]:
                return n
        return None

    entry_key: Optional[Tuple[str, ...]] = None
    entry_fn: Optional[ast.AST] = None
    entry_is_method = False
    if target_cls:
        meths = _methods(classes[target_cls], classes)
        for m in methods_order:
            if m in meths and _accepts_context(meths[m][1], is_method=True):
                entry_key = ("m", meths[m][0], m)
                entry_fn, entry_is_method = meths[m][1], True
                mv.entry = f"{target_cls}.{m}"
                mv.entry_annotation = _entry_annotation(meths[m][1], is_method=True)
                break
    else:
        for m in methods_order:
            if m in funcs and _accepts_context(funcs[m], is_method=False):
                entry_key = ("f", m)
                entry_fn, entry_is_method = funcs[m], False
                mv.entry = m
                mv.entry_annotation = _entry_annotation(funcs[m], is_method=False)
                break
    if entry_key is None:
        mv.verdict = "NO_ENTRY"
        if mv.reads_context_data_dir:
            # ключ читается, а связывать нечего: бегун в этот модуль с контекстом не входит
            mv.data_dir_door, _, mv.data_dir_reads = _data_dir_door(
                tree, funcs, classes, all_methods, node_of, ("f", "<нет входа>"), None)
            mv.data_dir_door_reason = "входа у бегуна нет — контекст в модуль не приходит, связанного имени нет"
        return mv

    # ── ось «у какого параметра дверь» (ADR-1004 § 6а) ──
    bound, why = _bound_context_name(entry_fn, is_method=entry_is_method)
    mv.data_dir_door, _, mv.data_dir_reads = _data_dir_door(
        tree, funcs, classes, all_methods, node_of, entry_key, bound)
    if mv.data_dir_door == "UNRESOLVED":
        mv.data_dir_door_reason = why

    # ── достижимость записи ──
    reached: Set[Tuple[str, ...]] = set()
    stack: List[Tuple[str, ...]] = [entry_key]
    writes: List[WriteSite] = []
    delegates: Set[str] = set()

    while stack:
        key = stack.pop()
        if key in reached:
            continue
        reached.add(key)
        fn = node_of(key)
        if fn is None:
            continue
        label = key[1] if key[0] == "f" else f"{key[1]}.{key[2]}"
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            form = _write_form(node)
            if form:
                writes.append(WriteSite(func=label, line=node.lineno, form=form))
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in funcs:
                    stack.append(("f", f.id))
                elif f.id in classes:
                    for cname, n in all_methods.get("__init__", []):
                        if cname == f.id:
                            stack.append(("m", cname, "__init__"))
                elif f.id in delegate_names:
                    delegates.add(f.id)
            elif isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else None
                if base in delegate_names:
                    delegates.add(f"{base}.{f.attr}")
                for cname, _n in all_methods.get(f.attr, []):
                    stack.append(("m", cname, f.attr))      # по имени, с избытком
    mv.writes = writes
    mv.delegates = sorted(delegates)
    if writes:
        mv.verdict = "WRITE_REACHABLE"
    elif delegates:
        mv.verdict = "DELEGATES_OUT"
    else:
        mv.verdict = "NO_WRITE_REACHED"
    return mv


# ─────────────────────────── перепись ───────────────────────────

_MAPPING_HEADS = {"dict", "Dict", "Mapping", "MutableMapping", "Any", "object", "None"}
_WRAPPER_HEADS = {"Optional", "Union"}


def _annotation_is_foreign(ann: Optional[str]) -> bool:
    """Аннотация входа — доменный тип (`list`, `List[Dict…]`, свой класс), а не Mapping: бегун после
    падения ответит `unchecked` (ADR #136). Судится ГОЛОВА аннотации (`List[Dict[str, Any]]` — это список);
    `Optional[...]`/`Union[...]` раскрываются на один уровень. Статика этого исхода НЕ предсказывает —
    она его только называет."""
    if not ann:
        return False
    head = ann.strip().strip('"\'').split("[", 1)[0].split(".")[-1]
    if head in _WRAPPER_HEADS and "[" in ann:
        inner = ann.split("[", 1)[1].rstrip("]")
        return _annotation_is_foreign(inner.split(",", 1)[0])
    if ann.strip().endswith("| None"):
        return _annotation_is_foreign(ann.strip()[: -len("| None")])
    return head not in _MAPPING_HEADS


def load_readers_json(path: Path) -> Dict[str, str]:
    """`callers.json` (ADR-999) → {rel: default_origin} по читателям `DEFAULT_RELIED` формы registry."""
    return readers_from_doc(json.loads(path.read_text(encoding="utf-8")))


def readers_from_doc(doc: Dict[str, Any]) -> Dict[str, str]:
    """Тот же разбор для документа, отданного прибором читателей в процессе (`--callers --runner`)."""
    readers = doc.get("callers", doc).get("readers") or []
    out: Dict[str, str] = {}
    for r in readers:
        if r.get("verdict") != "DEFAULT_RELIED":
            continue
        if any(c.get("kind") == "registry" for c in r.get("callers") or []):
            out[str(r["path"])] = str(r.get("default_origin") or "?")
    return out


def measure(repo: Path, readers_json: Optional[Path] = None,
            readers_doc: Optional[Dict[str, Any]] = None) -> Census:
    repo = repo.resolve()
    runner = read_runner(repo)
    entries = read_registry(repo)
    blind: Optional[Dict[str, str]] = None
    if readers_json is not None or readers_doc is not None:
        try:
            blind = load_readers_json(readers_json) if readers_json is not None else readers_from_doc(readers_doc or {})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise NotMeasured(f"callers.json не прочитан: {type(exc).__name__}: {exc}")
    modules: List[ModuleVerdict] = []
    for e in entries:
        mv = measure_module(repo, e, runner.entry_methods)
        if blind is not None and mv.path in blind:
            mv.blind_cli = blind[mv.path]
        modules.append(mv)
    counts = {v: 0 for v in VERDICTS}
    for m in modules:
        counts[m.verdict] += 1
    # Дверь бегуна закрывает умолчание только у того, кто читает ключ У СВЯЗАННОГО ИМЕНИ (ADR-1004 § 6а):
    # читатель ключа у чужого параметра (`FOREIGN_PARAM`) под песочницей пишет в умолчание, как и не-читатель.
    exposed = [m for m in modules if m.verdict == "WRITE_REACHABLE"
               and not (runner.passes_data_dir and m.data_dir_door == "CONTEXT_PARAM")]
    door_counts = {d: sum(1 for m in modules if m.data_dir_door == d) for d in DOOR_OUTCOMES}
    exposure = {
        "write_reachable": counts["WRITE_REACHABLE"],
        "runner_passes_data_dir": int(runner.passes_data_dir),
        "module_reads_context_data_dir": sum(1 for m in modules if m.reads_context_data_dir),
        "door_context_param": door_counts["CONTEXT_PARAM"],
        "door_foreign_param": door_counts["FOREIGN_PARAM"],
        "door_unresolved": door_counts["UNRESOLVED"],
        "module_reads_env_data_dir": sum(1 for m in modules if m.reads_env_data_dir),
        "default_reached_under_sandbox": len(exposed),
        "init_unknown": sum(1 for m in modules if m.init_unknown),
        "delegates_out": counts["DELEGATES_OUT"],
        "entry_non_mapping_annotation": sum(1 for m in modules if _annotation_is_foreign(m.entry_annotation)),
    }
    blind_subset: Optional[Dict[str, int]] = None
    if blind is not None:
        blind_subset = {v: 0 for v in VERDICTS}
        blind_subset["named"] = len(blind)
        blind_subset["found"] = 0
        for m in modules:
            if m.blind_cli is not None:
                blind_subset[m.verdict] += 1
                blind_subset["found"] += 1
    measured = [m for m in modules if m.verdict != "UNMEASURED"]
    if not measured:
        return Census(str(repo), runner, modules, counts, exposure, blind_subset, 2,
                      "ни один модуль реестра не измерен")
    code = 1 if exposed else 0
    return Census(str(repo), runner, modules, counts, exposure, blind_subset, code)


# ─────────────────────────── наблюдение ───────────────────────────

_OBSERVER = r'''
import json, os, sys, time
repo, sandbox, protocol, timeout, modules_path, out_path = sys.argv[1:7]
sys.path.insert(0, repo)
from spa_core.analytics import signal_aggregator as sa
agg = sa.SignalAggregator(data_dir=sandbox, module_timeout=float(timeout))
cwd = os.getcwd()
watch = {"runner_dir": sandbox, "tree_data": os.path.join(repo, "data"), "cwd_data": os.path.join(cwd, "data")}

def snap(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[p] = (st.st_mtime_ns, st.st_size)
    return out

def diff(a, b):
    return sorted(p for p in b if a.get(p) != b[p])

modules = json.load(open(modules_path, encoding="utf-8"))
results = []
for info in modules:
    before = {k: snap(v) for k, v in watch.items()}
    t0 = time.time()
    try:
        agg._run_module(info, protocol, {"cycle_ts": "observe", "source": "registry_runner_write_census"})
        status = agg._log[-1]["status"] if agg._log else "?"
        detail = agg._log[-1].get("detail", "") if agg._log else ""
    except BaseException as exc:
        status, detail = "observer_error", f"{type(exc).__name__}: {exc}"
    after = {k: snap(v) for k, v in watch.items()}
    results.append({"module": info["module"], "status": status, "detail": detail[:200],
                    "seconds": round(time.time() - t0, 3),
                    "written": {k: [os.path.relpath(p, watch[k]) for p in diff(before[k], after[k])] for k in watch}})
json.dump({"results": results}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
'''


def _tree_snapshot(root: Path) -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git", "data")]
        for f in fn:
            p = Path(dp) / f
            try:
                st = p.stat()
            except OSError:
                continue
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def _live_paths():
    """ЕДИНСТВЕННАЯ дверь прод-пути проекта (`spa_core.utils.live_paths`); не ввезлась ⇒ НЕ ИЗМЕРЕНО, не «не прод»."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from spa_core.utils import live_paths  # type: ignore
    except ImportError as exc:  # pragma: no cover — дерево без двери
        raise NotMeasured(f"дверь прод-пути не ввезена: {exc}")
    return live_paths


def _is_prod_tree(repo: Path) -> bool:
    prod = Path(_live_paths().DEFAULT_LIVE_ROOT).resolve()
    r = repo.resolve()
    return r == prod or prod in r.parents


def observe(repo: Path, census: Census, *, protocol: str, timeout: float,
            python: str = sys.executable) -> Dict[str, Any]:
    """Настоящий бегун названного дерева зовёт каждый модуль; записи ловятся корзинами."""
    repo = repo.resolve()
    # каноническая дверь: под маркером песочницы прод-realpath — отказ (SandboxLeakError); и БЕЗ маркера — ниже
    _live_paths().assert_not_prod_realpath(repo, who="registry_runner_write_census --observe")
    if _is_prod_tree(repo):
        raise NotMeasured(f"наблюдение в ПРОД-дереве запрещено: {repo}")
    if (repo / ".git").exists():
        raise NotMeasured(f"наблюдение в git-дереве запрещено (git-tracked data/ был бы записан): {repo}")
    entries = read_registry(repo)
    with tempfile.TemporaryDirectory(prefix="rrwc_sandbox_") as sb, \
            tempfile.TemporaryDirectory(prefix="rrwc_cwd_") as cwd, \
            tempfile.TemporaryDirectory(prefix="rrwc_io_") as io_dir:
        mods_path = Path(io_dir) / "modules.json"
        out_path = Path(io_dir) / "out.json"
        mods_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        before_tree = _tree_snapshot(repo)
        env = dict(os.environ)
        env.pop("SPA_ENV", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [python, "-c", _OBSERVER, str(repo), sb, protocol, str(timeout), str(mods_path), str(out_path)],
            cwd=cwd, env=env, capture_output=True, text=True)
        after_tree = _tree_snapshot(repo)
        if not out_path.is_file():
            raise NotMeasured(f"наблюдатель не отдал результата (код {proc.returncode}): "
                              f"{(proc.stderr or '')[-800:]}")
        doc = json.loads(out_path.read_text(encoding="utf-8"))
        elsewhere = sorted(p for p in after_tree if before_tree.get(p) != after_tree[p])
    results = doc["results"]
    by_name = {m.module: m for m in census.modules}
    statuses: Dict[str, int] = {}
    baskets = {"runner_dir": 0, "tree_data": 0, "cwd_data": 0}
    writers: List[Dict[str, Any]] = []
    parity = {"static_no_entry_and_unchecked": 0, "static_no_entry_but_invoked": 0,
              "static_entry_but_unchecked": 0, "static_entry_and_invoked": 0,
              "static_write_reachable_observed": 0, "static_write_reachable_silent": 0,
              "observed_write_static_missed": 0}
    for r in results:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        wrote = {k: v for k, v in r["written"].items() if v}
        for k in wrote:
            baskets[k] = baskets.get(k, 0) + 1
        if wrote:
            writers.append({"module": r["module"], "status": r["status"], "written": wrote})
        mv = by_name.get(r["module"])
        if mv is None:
            continue
        unchecked = r["status"] == "unchecked"
        if mv.verdict == "NO_ENTRY":
            parity["static_no_entry_and_unchecked" if unchecked else "static_no_entry_but_invoked"] += 1
        elif mv.verdict != "UNMEASURED":
            parity["static_entry_but_unchecked" if unchecked else "static_entry_and_invoked"] += 1
        if mv.verdict == "WRITE_REACHABLE":
            parity["static_write_reachable_observed" if wrote else "static_write_reachable_silent"] += 1
        elif wrote:
            parity["observed_write_static_missed"] += 1
    return {"repo": str(repo), "protocol": protocol, "timeout": timeout, "modules": len(results),
            "statuses": statuses, "baskets": baskets, "writers": writers, "per_module": results,
            "elsewhere_in_tree": [str(Path(p).relative_to(repo)) for p in elsewhere],
            "parity": parity, "observer_returncode": proc.returncode,
            "observer_stderr_tail": (proc.stderr or "")[-600:]}


# ─────────────────────────── вывод ───────────────────────────

def to_doc(c: Census) -> dict:
    return {"root": c.root, "runner": asdict(c.runner), "counts": c.counts, "exposure": c.exposure,
            "blind_subset": c.blind_subset, "code": c.code, "unmeasured_reason": c.unmeasured_reason,
            "modules": [asdict(m) for m in c.modules]}


def render(c: Census, obs: Optional[Dict[str, Any]] = None) -> str:
    out = [f"РЕЕСТР → БЕГУН: куда пишут аналитики под песочницей (ADR-999 § 6в) · дерево {c.root}",
           f"  бегун {c.runner.runner_path}: входы {list(c.runner.entry_methods)}; кладёт data_dir в контекст "
           f"модуля — {'ДА' if c.runner.passes_data_dir else 'НЕТ'}",
           f"  записей реестра: {len(c.modules)}"]
    for v in VERDICTS:
        out.append(f"  {v:<17} {c.counts.get(v, 0)}")
    out.append("  предмет (достижимое умолчание у бегуна):")
    for k, v in c.exposure.items():
        out.append(f"    {k:<32} {v}")
    if c.blind_subset is not None:
        out.append("  подмножество «76 реестра» (callers.json): "
                   + " · ".join(f"{k} {v}" for k, v in c.blind_subset.items() if v))
    writers = [m for m in c.modules if m.verdict == "WRITE_REACHABLE"]
    if writers:
        out.append("  достигают записи от входа бегуна (поимённо, первые 40):")
        for m in writers[:40]:
            forms = sorted({w.form for w in m.writes})
            door = f" · дверь контекста: {m.data_dir_door}" if m.reads_context_data_dir else ""
            env = " · SPA_DATA_DIR" if m.reads_env_data_dir else ""
            cli = f" · CLI-умолчание {m.blind_cli}" if m.blind_cli else ""
            out.append(f"    {m.module} [{m.tier}] {m.entry} → {', '.join(forms)} "
                       f"({len(m.writes)} мест){door}{env}{cli}")
    foreign = [m for m in c.modules if m.data_dir_door in ("FOREIGN_PARAM", "UNRESOLVED")]
    if foreign:
        out.append("  читают ключ data_dir НЕ у связанного имени (ось ADR-1004 § 6а, поимённо):")
        for m in foreign[:40]:
            bases = sorted({f"{r.func}:{r.line} у `{r.base}`" for r in m.data_dir_reads})
            why = f" — {m.data_dir_door_reason}" if m.data_dir_door_reason else ""
            out.append(f"    {m.module} [{m.verdict}] {m.data_dir_door}{why}: " + "; ".join(bases[:4]))
    unm = [m for m in c.modules if m.verdict == "UNMEASURED"]
    if unm:
        out.append("  НЕ ИЗМЕРЕНО (модули):")
        for m in unm[:10]:
            out.append(f"    {m.module}: {m.reason}")
    if obs is not None:
        out.append(f"  НАБЛЮДЕНИЕ в {obs['repo']} (протокол {obs['protocol']}, таймаут {obs['timeout']} с): "
                   f"модулей {obs['modules']}, статусы бегуна {obs['statuses']}")
        out.append(f"    корзины записи (модулей): {obs['baskets']} · прочее в дереве: {len(obs['elsewhere_in_tree'])}")
        out.append(f"    парность со статикой: {obs['parity']}")
        for w in obs["writers"][:40]:
            out.append(f"    ✍ {w['module']} ({w['status']}): " + "; ".join(
                f"{k}: {', '.join(v[:4])}{' …' if len(v) > 4 else ''}" for k, v in w["written"].items()))
        if obs["elsewhere_in_tree"]:
            out.append("    прочее в дереве: " + ", ".join(obs["elsewhere_in_tree"][:10]))
        out.append("    записи по абсолютным путям вне дерева/cwd/песочницы наблюдение НЕ видит")
    verdict = {0: "✅ предмет пуст: ни одна запись реестра не доводит вход бегуна до записи в своё умолчание",
               1: "❗ предмет НАЗВАН: бегун каталога не передаёт, а вход достигает записи — она ляжет в умолчание модуля",
               2: f"⚠️ НЕ ИЗМЕРЕНО: {c.unmeasured_reason}"}[c.code]
    out.append(verdict)
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="дерево, которое переписывается (умолчание — своё; ПЕЧАТАЕТСЯ)")
    ap.add_argument("--readers-json", default=None, help="callers.json ADR-999 — пометить подмножество «76 реестра»")
    ap.add_argument("--observe", default=None, metavar="TREE",
                    help="одноразовое НЕ-git дерево: настоящий бегун зовёт каждый модуль, записи наблюдаются")
    ap.add_argument("--protocol", default="aave_v3")
    ap.add_argument("--timeout", type=float, default=3.0, help="таймаут модуля у бегуна, с")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo_root).resolve() if args.repo_root else ROOT
    if args.repo_root is None:
        print(f"[реестр→бегун] дерево не названо — беру своё: {repo}", file=sys.stderr)
    try:
        c = measure(repo, Path(args.readers_json) if args.readers_json else None)
        obs = None
        if args.observe:
            obs = observe(Path(args.observe), c, protocol=args.protocol, timeout=args.timeout)
    except NotMeasured as exc:
        if args.json:
            print(json.dumps({"code": 2, "unmeasured_reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
        return 2
    if args.json:
        doc = to_doc(c)
        if obs is not None:
            doc["observation"] = obs
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(render(c, obs))
    return c.code


if __name__ == "__main__":
    sys.exit(main())
