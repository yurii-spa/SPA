#!/usr/bin/env python3
"""Замер ЧИТАТЕЛЕЙ слепых точек входа класса «песочница без названного каталога данных» (ADR-999).

ADR-998 измерил класс (393 точки входа с флагом каталога, 236 `MARKER_BLIND`) и оставил
решение об ОБЩЕЙ двери открытым с условием: «без замера читателей не выбирать» (§ 6а, урок
ADR-822). Этот прибор и есть тот замер. Вопрос у него один, и он про ВЫЗЫВАЮЩЕГО, а не про
точку входа:

    кто зовёт каждую слепую точку входа — и НАЗЫВАЕТ ли он каталог, под который она пишет?

Слепота точки входа опасна ровно тогда, когда её умолчание ДОСТИЖИМО: вызывающий каталог
не назвал (прибор пишет туда, куда указало умолчание — в прод-дерево) либо вызывающего нет
вовсе (тогда зовут РУКАМИ, и рука под `SPA_SANDBOX=1` получает умолчание — форма аварии
03.11, ADR-996 § 2.1). Точка входа, которую КАЖДЫЙ вызывающий зовёт с названным каталогом,
слепа безвредно: её умолчание не исполняется никогда.

Шесть форм вызывающего (это ЗАМЕР форм репозитория, см. ADR-999 § 2):

| kind            | где                                        | «назвал каталог» значит                                  |
|-----------------|--------------------------------------------|----------------------------------------------------------|
| `launchd_plist` | `launchd/*.plist` → `ProgramArguments`     | флаг точки входа среди аргументов                         |
| `shell`         | `*.sh` (обёртка флота или скрипт руки)     | флаг в той же ЛОГИЧЕСКОЙ строке (`\\`-переносы склеены)   |
| `python_argv`   | argv-список для `subprocess` (с интерпретатором либо `-m`) | флаг константой в том же списке               |
| `inprocess`     | `import` модуля + `.run(...)`/`.main(...)` | именованный аргумент каталога, позиционный аргумент либо флаг в argv-списке |
| `registry`      | реестр модулей (`{"module": "<stem>", …}`) — зовёт бегун по имени, каталога не передаёт | никогда: бегун зовёт класс/функцию, умолчание модуля исполняется |
| `prompt`        | промпт оркестратора (`scripts/agent_orchestrator.sh`, `docs/ORCHESTRATOR_PROTOCOL.md`) | флаг в той же строке; исполняет СЕССИЯ руками |

У каждого вызывающего отдельно измерено: достигается ли он от launchd (plist прямо либо
через обёртку `.sh`, названную в plist; `None` — цепь не прослежена), ставит ли он сам
`SPA_SANDBOX` (прямая форма аварии: маркер есть, каталог не назван; меряется ПРИСВАИВАНИЕМ,
не подстрокой — слово в докстринге маркером не является) и каков вердикт переписи ADR-998 у
самого вызывающего (`DOOR` у моста ⇒ `root=`, который он раздаёт ступеням, уже осуждён его
дверью).

Вердикт точки входа:

* `NAMED_BY_ALL` — вызывающие есть, и каждый назвал каталог: умолчание недостижимо;
* `DEFAULT_RELIED` — хотя бы один вызывающий полагается на умолчание (поимённо);
* `UNCALLED` — вызывающего не найдено ни в одной форме: зовут руками ⇒ умолчание достижимо;
* `UNMEASURED` — файл вызывающего не разобран (причина названа).

Коды: 0 — предмет пуст и измерен (каждая слепая точка входа `NAMED_BY_ALL`) · 1 — предмет
назван (`DEFAULT_RELIED` или `UNCALLED` ≥ 1) · 2 — НЕ ИЗМЕРЕНО (перепись ADR-998 не измерила,
поверхность вызывающих пуста, неразобранный вызывающий при пустом предмете). Как у
переписи: неразобранный файл не прячет названный предмет (код 1 сильнее 2).

Чего прибор НЕ докладывает (ADR-999 § 4): вызов через общего помощника, в котором имя
точки входа собирается из кусков (`f"scripts/{name}.py"`), прочтётся `UNCALLED` — ошибка
в сторону НАХОДКИ, не в сторону «безвредно»; имя функции, ввезённое из НЕСКОЛЬКИХ модулей
под одним локальным именем, никому не приписывается (та же сторона); `names_dir` отвечает
«каталог назван», а не «назван ВЕРНЫЙ каталог» (`--root <прод>` под маркером тоже
«назвал» — это предмет двери на приёмнике, ADR-998 § 3.2, не этого замера); позиционный
аргумент читается как «назван», потому что заменяет умолчание параметра, — какого именно
параметра, прибор не знает (`how=positional`, видно поимённо).

    python3 scripts/sandbox_data_dir_census.py --callers [--repo-root <дерево>] [--json]
    python3 scripts/sandbox_data_dir_callers.py [--repo-root <дерево>] [--json]
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import plistlib
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
CENSUS_FILE = Path(__file__).with_name("sandbox_data_dir_census.py")

#: Где живут вызывающие. Это ЗАМЕР форм репозитория: plist флота, обёртки `scripts/*.sh`,
#: python-код вне тестов (`subprocess`, `import`, реестр), промпт оркестратора.
PLIST_DIR = "launchd"
PY_DIRS: Tuple[str, ...] = ("scripts", "spa_core")
PROMPT_FILES: Tuple[str, ...] = ("scripts/agent_orchestrator.sh", "docs/ORCHESTRATOR_PROTOCOL.md")

#: Функции точки входа, вызов которых через импортированный модуль считается запуском.
ENTRY_FUNCS: Tuple[str, ...] = ("run", "main", "_main", "measure", "build", "refresh", "census")

#: Именованные аргументы, которыми вызывающий НАЗЫВАЕТ каталог при вызове в процессе.
DIR_KWARGS: Tuple[str, ...] = ("root", "data_dir", "repo_root", "live_root", "out_dir",
                               "output_dir", "data_root")

#: Ключ записи реестра модулей, по которому бегун находит модуль по имени.
REGISTRY_KEY = "module"

MARKER_ENV = "SPA_SANDBOX"
_SH_MARKER = re.compile(r"(?:^|[\s;])(?:export\s+)?" + MARKER_ENV + r"=", re.M)


class NotMeasured(RuntimeError):
    """Поверхность не измерена — третий исход, не ноль."""


@dataclass
class Caller:
    file: str
    kind: str                       # launchd_plist · shell · python_argv · inprocess · registry · prompt
    line: int
    names_dir: bool
    how: Optional[str]              # flag · kwarg · positional · None (не назвал)
    launchd: Optional[bool]         # достигается от plist (прямо либо через обёртку); None — не прослежено
    sets_marker: bool               # вызывающий сам ставит SPA_SANDBOX (присваиванием)
    caller_verdict: Optional[str]   # вердикт переписи ADR-998 у вызывающего, если он в её поверхности


@dataclass
class Reader:
    path: str
    flag: str
    default_origin: Optional[str]
    verdict: str                    # NAMED_BY_ALL · DEFAULT_RELIED · UNCALLED · UNMEASURED
    callers: List[Caller] = field(default_factory=list)
    reason: Optional[str] = None

    @property
    def relying(self) -> List[Caller]:
        return [c for c in self.callers if not c.names_dir]


@dataclass
class CallersCensus:
    root: str
    readers: List[Reader]
    counts: Dict[str, int]
    caller_kinds: Dict[str, Dict[str, int]]     # kind → {"named": n, "relying": n}
    exposure: Dict[str, int]                    # формы достижимого умолчания
    unmeasured_files: List[str]
    code: int
    unmeasured_reason: Optional[str] = None


# ─────────────────────────── перепись ADR-998 как вход ───────────────────────────

def load_census_module(path: Path = CENSUS_FILE):
    """Перепись — ВХОД прибора, грузится по файлу рядом (sys.path на неё не ставят)."""
    if not path.is_file():
        raise NotMeasured(f"перепись ADR-998 не найдена: {path}")
    spec = importlib.util.spec_from_file_location("spa_sandbox_data_dir_census", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("spa_sandbox_data_dir_census", mod)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────── имена точки входа ───────────────────────────

def entry_names(rel: str) -> Tuple[str, str, str]:
    """(basename, module, stem) точки входа `scripts/x.py` или `spa_core/a/b.py`."""
    p = Path(rel)
    module = ".".join(p.with_suffix("").parts)
    return p.name, module, p.stem


def _tokens_name_entry(tokens: List[str], basename: str, module: str, rel: str) -> bool:
    for i, t in enumerate(tokens):
        if t == rel or t.endswith("/" + rel) or t.endswith("/" + basename):
            return True
        if t == "-m" and i + 1 < len(tokens) and tokens[i + 1].strip("\"'") == module:
            return True
    return False


def _tokens_name_flag(tokens: Iterable[str], flag: str) -> bool:
    for t in tokens:
        if t == flag or t.startswith(flag + "="):
            return True
    return False


# ─────────────────────────── plist ───────────────────────────

def _plists(repo: Path) -> List[Tuple[Path, List[str], bool]]:
    """(файл, ProgramArguments, ставит ли маркер) по каждому plist флота."""
    out = []
    d = repo / PLIST_DIR
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.plist")):
        try:
            doc = plistlib.loads(p.read_bytes())
        except Exception as exc:  # noqa: BLE001 — неразобранный plist = НЕ ИЗМЕРЕНО поимённо
            raise NotMeasured(f"plist не разобран: {p.relative_to(repo)}: {exc}") from exc
        args = [str(a) for a in doc.get("ProgramArguments", [])]
        env = doc.get("EnvironmentVariables") or {}
        out.append((p, args, MARKER_ENV in env))
    return out


def _wrappers_from_plists(plists) -> Set[str]:
    """Обёртки `.sh`, которые зовёт launchd — по ним ходит цепь plist → обёртка → точка входа."""
    names: Set[str] = set()
    for _path, args, _marker in plists:
        for a in args:
            if a.endswith(".sh"):
                names.add(Path(a).name)
    return names


# ─────────────────────────── shell ───────────────────────────

def _logical_lines(text: str) -> List[Tuple[int, str]]:
    """Строки с `\\`-переносами склеены; номер — первой физической строки."""
    out: List[Tuple[int, str]] = []
    buf, start = "", 0
    for i, raw in enumerate(text.splitlines(), 1):
        if not buf:
            start = i
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1] + " "
            continue
        buf += raw
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def _sh_tokens(line: str) -> List[str]:
    return [t.strip("\"'") for t in re.split(r"[\s;|&()]+", line) if t]


def _sh_sets_marker(text: str) -> bool:
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    return bool(_SH_MARKER.search(code))


def _sh_files(repo: Path) -> List[Path]:
    out = []
    for p in sorted(repo.rglob("*.sh")):
        rel = p.relative_to(repo).as_posix()
        if rel.startswith((".git/", "node_modules/", "landing/")) or "/tests/" in rel:
            continue
        out.append(p)
    return out


# ─────────────────────────── python ───────────────────────────

def _py_files(repo: Path) -> List[Path]:
    out = []
    for d in PY_DIRS:
        base = repo / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "/tests/" in p.as_posix() or p.name.startswith("test_"):
                continue
            out.append(p)
    return out


def _const(node: ast.AST) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _join_path(node: ast.AST) -> Optional[str]:
    """`os.path.join(x, "scripts", "y.py")` / `root / "scripts" / "y.py"` → хвост пути константами."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        tail = [c for c in (_const(a) for a in node.args) if c is not None]
        return "/".join(tail) if tail else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _join_path(node.left) if isinstance(node.left, (ast.BinOp, ast.Call)) else None
        right = _const(node.right)
        if right is None:
            return left
        return f"{left}/{right}" if left else right
    return None


def _list_strings(node: ast.AST) -> List[str]:
    """Строковые элементы списка argv; `join`/`/`-формы дают хвост пути."""
    out: List[str] = []
    for el in node.elts:  # type: ignore[attr-defined]
        c = _const(el)
        if c is not None:
            out.append(c)
            continue
        j = _join_path(el)
        if j:
            out.append(j)
    return out


def _looks_like_argv(node: ast.AST, strs: List[str]) -> bool:
    """Список — это КОМАНДА, а не перечень путей: первым идёт интерпретатор либо внутри есть `-m`.

    `MEASURE_CARRIERS = ("scripts/x.py", …)` — перечень, не вызов; без этого отличия прибор
    приписывал бы точке входа вызывающего, который её только УПОМИНАЕТ.
    """
    if "-m" in strs:
        return True
    if not getattr(node, "elts", None):
        return False
    first = node.elts[0]  # type: ignore[attr-defined]
    if isinstance(first, ast.Attribute) and first.attr == "executable":
        return True
    if isinstance(first, ast.Name) and "py" in first.id.lower():
        return True
    c = _const(first)
    return bool(c and "python" in c)


def _py_sets_marker(tree: ast.Module) -> bool:
    """`env["SPA_SANDBOX"] = …`, `{"SPA_SANDBOX": …}`, `.setdefault("SPA_SANDBOX", …)` — ПРИСВАИВАНИЕ, не слово."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and _const(t.slice) == MARKER_ENV:
                    return True
        elif isinstance(node, ast.Dict):
            if any(_const(k) == MARKER_ENV for k in node.keys if k is not None):
                return True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("setdefault", "update") and node.args and _const(node.args[0]) == MARKER_ENV:
                return True
    return False


def _scopes(tree: ast.Module) -> Dict[int, Optional[int]]:
    """id(узла) → id ближайшей охватывающей функции (None — уровень модуля)."""
    scope: Dict[int, Optional[int]] = {}

    def walk(node: ast.AST, current: Optional[int]) -> None:
        for child in ast.iter_child_nodes(node):
            scope[id(child)] = current
            nxt = id(child) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            walk(child, nxt)

    walk(tree, None)
    return scope


def _enclosing_chain(node_id: int, scope: Dict[int, Optional[int]]) -> Set[Optional[int]]:
    chain: Set[Optional[int]] = {None}
    cur: Optional[int] = node_id
    while cur is not None:
        cur = scope.get(cur)
        chain.add(cur)
    return chain


def _import_bindings(tree: ast.Module, module: str, stem: str, caller_in_scripts: bool,
                     scope: Dict[int, Optional[int]]) -> List[Tuple[str, Optional[int], bool]]:
    """(локальное имя, область видимости импорта, это имя ФУНКЦИИ) для модуля точки входа.

    Импорт внутри функции виден только в ней: `from … import X as census` в десяти разных
    пробах `card_acceptance.py` связывает одно и то же имя с десятью модулями, и считать
    любой `census.measure()` вызовом каждого из них значило бы приписать точке входа девять
    чужих вызывающих.
    """
    out: List[Tuple[str, Optional[int], bool]] = []
    parent = module.rsplit(".", 1)[0] if "." in module else None
    for node in ast.walk(tree):
        sc = scope.get(id(node))
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == module:
                    out.append((a.asname or module, sc, False))
                elif caller_in_scripts and a.name == stem and not module.startswith("spa_core"):
                    out.append((a.asname or stem, sc, False))
        elif isinstance(node, ast.ImportFrom):
            if node.module == parent:
                for a in node.names:
                    if a.name == stem:
                        out.append((a.asname or stem, sc, False))
            elif node.module == module or (caller_in_scripts and node.module == stem
                                           and not module.startswith("spa_core")):
                for a in node.names:
                    if a.name in ENTRY_FUNCS:
                        out.append((a.asname or a.name, sc, True))
    return out


def _call_names_dir(call: ast.Call, flag: str) -> Optional[str]:
    for kw in call.keywords:
        if kw.arg in DIR_KWARGS:
            return "kwarg"
    for a in call.args:
        if isinstance(a, (ast.List, ast.Tuple)):
            if _tokens_name_flag(_list_strings(a), flag):
                return "flag"
            continue
        return "positional"
    return None


def _dotted(node: ast.AST) -> Optional[str]:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _py_callers(rel: str, tree: ast.Module, text: str, scope: Dict[int, Optional[int]],
                sets_marker: bool, caller_verdict: Optional[str],
                fn_name_owners: Dict[str, Set[str]], reader: Reader) -> List[Caller]:
    basename, module, stem = entry_names(reader.path)
    if stem not in text:
        return []
    found: List[Caller] = []
    # argv-списки
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            strs = _list_strings(node)
            if strs and _tokens_name_entry(strs, basename, module, reader.path) and _looks_like_argv(node, strs):
                named = _tokens_name_flag(strs, reader.flag)
                found.append(Caller(rel, "python_argv", node.lineno, named, "flag" if named else None,
                                    False, sets_marker, caller_verdict))
    # реестр модулей: {"module": "<stem>", …}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is not None and _const(k) == REGISTRY_KEY and _const(v) == stem:
                    found.append(Caller(rel, "registry", node.lineno, False, None, None, sets_marker,
                                        caller_verdict))
    # вызов в процессе через импорт
    bindings = _import_bindings(tree, module, stem, rel.startswith("scripts/"), scope)
    if not bindings:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        visible = _enclosing_chain(id(node), scope)
        f = node.func
        hit = False
        if isinstance(f, ast.Attribute) and f.attr in ENTRY_FUNCS:
            name = _dotted(f.value)
            hit = name == module or any(n == name and sc in visible and not is_fn
                                        for n, sc, is_fn in bindings)
        elif isinstance(f, ast.Name):
            # имя функции, ввезённое из нескольких модулей под одним именем, — ничьё
            hit = (any(n == f.id and sc in visible and is_fn for n, sc, is_fn in bindings)
                   and len(fn_name_owners.get(f.id, set())) == 1)
        if hit:
            how = _call_names_dir(node, reader.flag)
            found.append(Caller(rel, "inprocess", node.lineno, how is not None, how, False,
                                sets_marker, caller_verdict))
    return found


# ─────────────────────────── измерение ───────────────────────────

def measure(repo: Path, census=None) -> CallersCensus:
    repo = Path(repo).resolve()
    if census is None:
        mod = load_census_module()
        census = mod.measure(repo)
    if census.code == 2 and not census.entries:
        raise NotMeasured(f"перепись ADR-998 не измерила дерево: {census.unmeasured_reason}")
    entries = {e.path: asdict(e) for e in census.entries}
    readers = [Reader(e.path, e.flag or "", e.default_origin, "UNCALLED") for e in census.blind]
    if not readers:
        return CallersCensus(str(repo), [], {}, {}, {}, [], 0, "у переписи нет ни одной слепой точки входа")

    plists = _plists(repo)
    wrappers = _wrappers_from_plists(plists)
    sh_files = _sh_files(repo)
    py_files = _py_files(repo)
    prompt_rel = set(PROMPT_FILES)
    if not plists and not sh_files and not py_files:
        raise NotMeasured("поверхность вызывающих пуста: ни plist, ни *.sh, ни *.py")

    unmeasured_files: List[str] = []

    # plist
    for p, args, marker in plists:
        rel = p.relative_to(repo).as_posix()
        for r in readers:
            basename, module, _ = entry_names(r.path)
            if _tokens_name_entry(args, basename, module, r.path):
                named = _tokens_name_flag(args, r.flag)
                r.callers.append(Caller(rel, "launchd_plist", 0, named, "flag" if named else None,
                                        True, marker, None))

    # shell (в т.ч. промпт оркестратора — он лежит в .sh)
    for p in sh_files:
        rel = p.relative_to(repo).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured_files.append(f"{rel}: {exc}")
            continue
        kind = "prompt" if rel in prompt_rel else "shell"
        launchd = p.name in wrappers
        marker = _sh_sets_marker(text)
        present = [r for r in readers if entry_names(r.path)[2] in text]
        if not present:
            continue
        for lineno, line in _logical_lines(text):
            if line.lstrip().startswith("#"):
                continue
            toks = _sh_tokens(line)
            for r in present:
                basename, module, _ = entry_names(r.path)
                if _tokens_name_entry(toks, basename, module, r.path):
                    named = _tokens_name_flag(toks, r.flag)
                    r.callers.append(Caller(rel, kind, lineno, named, "flag" if named else None,
                                            launchd, marker, entries.get(rel, {}).get("verdict")))

    # промпт в markdown
    for rel in PROMPT_FILES:
        p = repo / rel
        if not p.is_file() or p.suffix != ".md":
            continue
        text = p.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "python3" not in line:
                continue
            toks = _sh_tokens(line)
            for r in readers:
                basename, module, _ = entry_names(r.path)
                if _tokens_name_entry(toks, basename, module, r.path):
                    named = _tokens_name_flag(toks, r.flag)
                    r.callers.append(Caller(rel, "prompt", lineno, named, "flag" if named else None,
                                            False, False, None))

    # python
    stems = {entry_names(r.path)[2] for r in readers}
    for p in py_files:
        rel = p.relative_to(repo).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unmeasured_files.append(f"{rel}: {exc}")
            continue
        if not any(s in text for s in stems):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            unmeasured_files.append(f"{rel}: {exc.msg} (строка {exc.lineno})")
            continue
        scope = _scopes(tree)
        sets_marker = _py_sets_marker(tree)
        cv = entries.get(rel, {}).get("verdict")
        # одно локальное имя функции — от скольких модулей точек входа оно ввезено
        owners: Dict[str, Set[str]] = {}
        for r in readers:
            _b, module, stem = entry_names(r.path)
            if stem not in text:
                continue
            for n, _sc, is_fn in _import_bindings(tree, module, stem, rel.startswith("scripts/"), scope):
                if is_fn:
                    owners.setdefault(n, set()).add(r.path)
        for r in readers:
            if r.path == rel:
                continue                      # сам себя не зовёт
            r.callers.extend(_py_callers(rel, tree, text, scope, sets_marker, cv, owners, r))

    # вердикты
    for r in readers:
        if not r.callers:
            r.verdict = "UNCALLED"
            r.reason = "вызывающего не найдено ни в одной форме — зовут руками, умолчание достижимо"
        elif r.relying:
            r.verdict = "DEFAULT_RELIED"
            r.reason = "; ".join(f"{c.file}:{c.line} [{c.kind}]" for c in r.relying[:6])
        else:
            r.verdict = "NAMED_BY_ALL"
    if unmeasured_files:
        for r in readers:
            if r.verdict == "NAMED_BY_ALL":
                r.verdict, r.reason = "UNMEASURED", ("часть вызывающих не разобрана — «назвали все» "
                                                     "утверждать нельзя")

    counts: Dict[str, int] = {}
    kinds: Dict[str, Dict[str, int]] = {}
    exposure = {"relied_from_launchd_no_marker": 0, "relied_by_marker_setter": 0,
                "relied_by_prompt_or_hand": 0, "relied_via_registry": 0, "relied_other": 0,
                "uncalled": 0}
    for r in readers:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
        if r.verdict == "UNCALLED":
            exposure["uncalled"] += 1
        for c in r.callers:
            k = kinds.setdefault(c.kind, {"named": 0, "relying": 0})
            k["named" if c.names_dir else "relying"] += 1
            if c.names_dir:
                continue
            if c.sets_marker:
                exposure["relied_by_marker_setter"] += 1
            elif c.kind == "prompt":
                exposure["relied_by_prompt_or_hand"] += 1
            elif c.kind == "registry":
                exposure["relied_via_registry"] += 1
            elif c.launchd:
                exposure["relied_from_launchd_no_marker"] += 1
            else:
                exposure["relied_other"] += 1
    subject = counts.get("DEFAULT_RELIED", 0) + counts.get("UNCALLED", 0)
    if subject:
        code = 1
    elif unmeasured_files:
        code = 2
    else:
        code = 0
    reason = None
    if code == 2:
        reason = "часть вызывающих не разобрана: " + "; ".join(unmeasured_files[:5])
    return CallersCensus(str(repo), readers, counts, kinds, exposure, unmeasured_files, code, reason)


# ─────────────────────────── вывод ───────────────────────────

def render(c: CallersCensus) -> str:
    out = [f"ЧИТАТЕЛИ слепых точек входа (ADR-999) · дерево {c.root}",
           f"  слепых точек входа: {len(c.readers)}"]
    for k in ("NAMED_BY_ALL", "DEFAULT_RELIED", "UNCALLED", "UNMEASURED"):
        out.append(f"  {k:<15} {c.counts.get(k, 0)}")
    out.append("  вызывающие по форме (назвал каталог / полагается на умолчание):")
    for kind, n in sorted(c.caller_kinds.items()):
        out.append(f"    {kind:<14} {n['named']} / {n['relying']}")
    out.append("  достижимое умолчание (это и есть предмет):")
    for k, v in c.exposure.items():
        out.append(f"    {k:<32} {v}")
    relied = [r for r in c.readers if r.verdict == "DEFAULT_RELIED"]
    if relied:
        out.append("  полагаются на умолчание (поимённо, первые 40):")
        for r in relied[:40]:
            out.append(f"    {r.path} ({r.flag}, {r.default_origin}) ← {r.reason}")
    if c.unmeasured_files:
        out.append("  НЕ ИЗМЕРЕНО (файлы вызывающих):")
        for u in c.unmeasured_files[:10]:
            out.append(f"    {u}")
    verdict = {0: "✅ предмет пуст: каждую слепую точку входа каждый вызывающий зовёт с названным каталогом",
               1: "❗ предмет НАЗВАН: умолчание слепой точки входа достижимо",
               2: f"⚠️ НЕ ИЗМЕРЕНО: {c.unmeasured_reason}"}[c.code]
    out.append(verdict)
    return "\n".join(out)


def to_doc(c: CallersCensus) -> dict:
    return {"root": c.root, "counts": c.counts, "caller_kinds": c.caller_kinds,
            "exposure": c.exposure, "code": c.code, "unmeasured_reason": c.unmeasured_reason,
            "unmeasured_files": c.unmeasured_files,
            "readers": [asdict(r) for r in c.readers]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, которое переписывается (умолчание — своё; ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo_root).resolve() if args.repo_root else ROOT
    if args.repo_root is None:
        print(f"[читатели] дерево не названо — беру своё: {repo}", file=sys.stderr)
    try:
        c = measure(repo)
    except NotMeasured as exc:
        if args.json:
            print(json.dumps({"code": 2, "unmeasured_reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
        return 2
    print(json.dumps(to_doc(c), ensure_ascii=False, indent=2) if args.json else render(c))
    return c.code


if __name__ == "__main__":
    sys.exit(main())
