#!/usr/bin/env python3
"""Перепись класса «песочница без названного каталога данных» (ADR-996 § 6б, ADR-998).

Класс найден 12.11 (цикл #1115, ADR-996): куча из **11 файлов** в прод-`data/` 03.11
01:05–01:07Z написана сэмплером мандата ARB 02, который шёл под ``SPA_SANDBOX=1`` и
считал себя в песочнице. Маркер защищал ТРЕКЕР (карточки, уведомления), а каталог
артефактов писатели переписей берут от ``--root`` / ``SPA_DATA_DIR`` / места модуля —
без них это прод. «Песочница» была правдой для трекера и ложью для ``data/``.

**Почему это дефект приёмника, а не только вызывающего.** Защита на приёмнике уже есть —
``spa_core.utils.live_paths`` (C8(a) ADR-580): если маркер стоит, а путь разрешился бы в
прод, функция ОТКАЗЫВАЕТ (``SandboxLeakError``). Но её видит только тот, кто через неё
разрешает путь. Точка входа, берущая корень аргументом ``--root`` с умолчанием «дерево
модуля» и дальше пишущая в ``<root>/data`` (или в процессе раздающая ``root=`` ступеням),
маркера не спрашивает вовсе — и ``SPA_SANDBOX=1`` для неё пустой звук. Так устроен
``findings_bridge --run`` — ровно дверь, через которую легли 11 файлов.

**Что меряет перепись.** По КАЖДОЙ точке входа поверхности — один вопрос: *пишет ли она
под каталог данных, который берёт из аргумента с умолчанием, и спрашивает ли при этом
маркер песочницы.* Поверхность — ОБЪЯВЛЕННАЯ, а не вкусовая: все ``*.py`` в
:data:`SURFACE_DIRS`, у которых argparse объявляет флаг из :data:`ROOT_FLAGS`.

**Вердикты (инв. #17 — различимы и печатаются):**

* ``MARKER_BLIND``  — пишет (или раздаёт ``root=`` ступеням) под каталог из флага с
                      умолчанием, двери к маркеру не зовёт — ПРЕДМЕТ КЛАССА;
* ``DOOR``          — зовёт дверь (``live_root``/``live_data_dir``/
                      ``assert_not_prod_realpath``/читает ``SPA_SANDBOX``);
* ``EXPLICIT_ONLY`` — умолчания у флага нет (``required`` либо ``None`` без запасного
                      выражения): вызывающий обязан назвать каталог сам;
* ``READER``        — записи под каталог данных не найдено: вне предмета;
* ``UNMEASURED``    — файл не разобран / не прочитан (причина названа).

**Дверь судится ДОСТИЖИМОСТЬЮ от точки входа, а не наличием в файле** (урок ADR-932 о
половине инъекции): обход идёт от ``def main`` и блока ``if __name__ == "__main__"`` по
вызовам функций того же файла до неподвижной точки. Функция двери, оставшаяся в файле
после снятия одной строки проводки, входом не достигается — и файл читается
``MARKER_BLIND`` с пометкой ``door_unreached``; мера «дверь где-то есть» объявила бы
аварию закрытой. Входа в файле нет ⇒ берётся весь файл (сказано флагом).

**Чего перепись НЕ закрывает (вслух, чтобы не читалось шире).** Дверь ищется ВЫЗОВОМ в
том же файле: модуль, зовущий дверь только через импортированного помощника, прочитается
``MARKER_BLIND`` с пометкой ``door_imported`` — это ОШИБКА В БЕЗОПАСНУЮ СТОРОНУ (лишняя
находка), а не пропуск. «Дверь позвана» ≠ «дверь спрошена о ТОМ ЖЕ пути, что пишется»
(урок ADR-932 о половине инъекции): смешанный модуль, разрешающий одни пути дверью и
другие — аргументом, прочитается ``DOOR``, и это сказано здесь. Запись ищется по
известным формам (:data:`WRITE_CALLS`, ``open(..., "w")``, ``.write_text``,
``json.dump``); запись чужой формой — ``READER`` в опасную сторону, и поэтому список
форм измерен на члене класса, а не выбран (контроль — тест).

Запуск::

    python3 scripts/sandbox_data_dir_census.py [--repo-root <дерево>] [--subtree <каталог>] [--json]

Коды возврата: 0 — предмет класса ПУСТ (и измерен) · 1 — предмет НАЗВАН · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

#: Каталоги поверхности. Это ЗАМЕР, а не вкус: 03.11 писали ступени
#: `spa_core/monitoring` (мост раздаёт им `root=`), переписи аналитики (`spa_core/analytics`)
#: пишут свои артефакты тем же порядком, `scripts/` — обязательные шаги цикла.
SURFACE_DIRS: Tuple[str, ...] = ("scripts", "spa_core/monitoring", "spa_core/analytics")

#: Флаги, которыми точка входа принимает каталог данных или корень дерева, под который
#: пишет. `--repo-root` здесь ЕСТЬ (в отличие от переписи дерева прогона): корень
#: дерева — это и есть то, к чему писатель дописывает `data/`.
ROOT_FLAGS: Tuple[str, ...] = ("--root", "--data-dir", "--data_dir", "--repo-root",
                               "--live-root", "--out-dir", "--output-dir")

#: Двери к маркеру песочницы. Вызов ЛЮБОЙ из них в файле = `DOOR`.
DOOR_CALLS: Tuple[str, ...] = ("live_root", "live_data_dir", "assert_not_prod_realpath",
                               "_sandbox_marker_active", "sandbox_leak_reason",
                               "refuse_if_sandbox_leaks")

#: Имена переменных окружения, чтение которых тоже считается дверью.
DOOR_ENV_NAMES: Tuple[str, ...] = ("SPA_SANDBOX", "SANDBOX_ENV", "SPA_STAMP_TREE")

#: Формы записи под каталог данных.
WRITE_CALLS: Tuple[str, ...] = ("atomic_save", "atomic_write", "atomic_write_json",
                                "atomic_json_save", "save_json", "write_json")
WRITE_ATTRS: Tuple[str, ...] = ("write_text", "write_bytes", "dump")

#: Сколько кругов разрешения имени умолчания делать (один хоп через импорт).
RESOLVE_HOPS = 2


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


@dataclass
class Entry:
    path: str
    verdict: str
    flag: Optional[str] = None
    default: Optional[str] = None
    default_kind: Optional[str] = None      # constant · none · required · fallback
    default_origin: Optional[str] = None    # module_tree · literal · cwd · other · unresolved
    writes: List[str] = field(default_factory=list)
    delegates_root: bool = False
    doors: List[str] = field(default_factory=list)
    door_imported: bool = False
    door_unreached: bool = False          # дверь есть в файле, но от точки входа не достигается
    reason: Optional[str] = None


@dataclass
class Census:
    root: str
    surface_dirs: List[str]
    entries: List[Entry]
    counts: Dict[str, int]
    code: int
    unmeasured_reason: Optional[str] = None

    @property
    def blind(self) -> List[Entry]:
        return [e for e in self.entries if e.verdict == "MARKER_BLIND"]

    @property
    def unmeasured(self) -> List[Entry]:
        return [e for e in self.entries if e.verdict == "UNMEASURED"]


# ─────────────────────────── разбор одного файла ───────────────────────────

def _name_of(func: ast.AST) -> Optional[str]:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _const_str(node: ast.AST) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _find_root_flag(tree: ast.AST) -> Optional[Tuple[str, ast.Call]]:
    """Первый `add_argument(<флаг из ROOT_FLAGS>, …)` в файле."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name_of(node.func) != "add_argument":
            continue
        for arg in node.args:
            s = _const_str(arg)
            if s in ROOT_FLAGS:
                return s, node
    return None


def _dest_of(flag: str, call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "dest":
            d = _const_str(kw.value)
            if d:
                return d
    return flag.lstrip("-").replace("-", "_")


def _module_assign(tree: ast.Module, name: str) -> Optional[ast.AST]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name and node.value is not None:
            return node.value
    return None


def _import_source(tree: ast.Module, name: str) -> Optional[str]:
    """`from X import name` ⇒ X (модульный путь), иначе None."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return node.module
    return None


def _classify_expr(expr: ast.AST, src: str) -> Optional[str]:
    seg = ast.get_source_segment(src, expr) or ""
    if "__file__" in seg:
        return "module_tree"
    if "getcwd" in seg or "Path.cwd" in seg or "os.curdir" in seg:
        return "cwd"
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return "literal"
    return None


def _unwrap(expr: ast.AST) -> ast.AST:
    """`str(X)` · `Path(X)` · `X / "data"` · `X.parent` ⇒ X — обёртки не меняют происхождения."""
    seen = 0
    while seen < 8:
        seen += 1
        if isinstance(expr, ast.Call) and _name_of(expr.func) in ("str", "Path", "os.fspath",
                                                                   "fspath", "abspath",
                                                                   "realpath", "resolve") \
                and len(expr.args) == 1:
            expr = expr.args[0]
            continue
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) \
                and expr.func.attr in ("resolve", "absolute", "expanduser") and not expr.args:
            expr = expr.func.value
            continue
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            expr = expr.left
            continue
        if isinstance(expr, ast.Attribute) and expr.attr in ("parent", "parents"):
            expr = expr.value
            continue
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute) \
                and expr.value.attr == "parents":
            expr = expr.value.value
            continue
        break
    return expr


def _default_origin(expr: ast.AST, tree: ast.Module, src: str, repo: Path,
                    hops: int = RESOLVE_HOPS) -> str:
    """Откуда берётся умолчание: дерево модуля · литерал · cwd · другое · не разрешено."""
    direct = _classify_expr(expr, src)
    if direct:
        return direct
    expr = _unwrap(expr)
    direct = _classify_expr(expr, src)
    if direct:
        return direct
    if isinstance(expr, ast.Name) and hops > 0:
        local = _module_assign(tree, expr.id)
        if local is not None:
            return _default_origin(local, tree, src, repo, hops - 1)
        mod = _import_source(tree, expr.id)
        if mod:
            cand = repo / (mod.replace(".", "/") + ".py")
            if cand.is_file():
                try:
                    osrc = cand.read_text(encoding="utf-8")
                    otree = ast.parse(osrc)
                except (OSError, SyntaxError, ValueError):
                    return "unresolved"
                oassign = _module_assign(otree, expr.id)
                if oassign is not None:
                    return _default_origin(oassign, otree, osrc, repo, hops - 1)
            return "unresolved"
        return "unresolved"
    if isinstance(expr, ast.Attribute) and hops > 0:
        # `Path(__file__).resolve().parent` и родня уже пойманы сегментом; остальное — other
        return "other"
    return "other"


def _mentions_dest(node: ast.AST, dest: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == dest \
                and isinstance(sub.value, ast.Name) and sub.value.id == "args":
            return True
    return False


def _fallback_for(tree: ast.AST, dest: str) -> Optional[ast.AST]:
    """Запасное умолчание для флага без `default`: выражение, которое берётся, когда
    `args.<dest>` пуст. Три формы: `args.x or X` · `X if not args.x else …` (IfExp) ·
    `if args.x is None: x = X` (If с присваиванием, не упоминающим `args.x`)."""
    def _is_none(n: ast.AST) -> bool:
        return isinstance(n, ast.Constant) and n.value is None

    def _usable(n: ast.AST) -> bool:
        return not _mentions_dest(n, dest) and not _is_none(n)

    def _empty_test(test: ast.AST) -> Optional[bool]:
        """`args.x is None` / `not args.x` ⇒ True (пусто в body) · `args.x` /
        `args.x is not None` ⇒ False (пусто в orelse) · иначе None (не о пустоте)."""
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1 \
                and _mentions_dest(test.left, dest) and _is_none(test.comparators[0]):
            return isinstance(test.ops[0], ast.Is)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) \
                and _mentions_dest(test.operand, dest):
            return True
        if isinstance(test, ast.Attribute) and _mentions_dest(test, dest):
            return False
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) > 1:
            if _mentions_dest(node.values[0], dest) and _usable(node.values[1]):
                return node.values[1]
        if isinstance(node, ast.IfExp):
            empty = _empty_test(node.test)
            if empty is not None:
                branch = node.body if empty else node.orelse
                if _usable(branch):
                    return branch
        if isinstance(node, ast.If):
            empty = _empty_test(node.test)
            if empty is not None:
                for stmt in (node.body if empty else node.orelse):
                    if isinstance(stmt, ast.Assign) and _usable(stmt.value):
                        return stmt.value
    return None


def _doors_in(node: ast.AST) -> List[str]:
    """Двери к маркеру, ПОЗВАННЫЕ внутри `node` (вызовы и чтения окружения)."""
    doors: List[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _name_of(sub.func)
            if name in DOOR_CALLS:
                doors.append(name)
            if name in ("get", "getenv") and sub.args:
                if _const_str(sub.args[0]) in DOOR_ENV_NAMES:
                    doors.append(f"env:{_const_str(sub.args[0])}")
        if isinstance(sub, ast.Subscript):
            s = _const_str(sub.slice)
            if s in DOOR_ENV_NAMES:
                doors.append(f"env:{s}")
        if isinstance(sub, ast.Name) and sub.id == "SANDBOX_ENV":
            doors.append("env:SANDBOX_ENV")
    return doors


def _is_main_block(node: ast.AST) -> bool:
    """`if __name__ == "__main__":`"""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    t = node.test
    return (isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and _const_str(t.comparators[0]) == "__main__")


def reachable_doors(tree: ast.Module) -> Tuple[List[str], Optional[bool]]:
    """Двери, ДОСТИЖИМЫЕ от точки входа файла, и флаг «вход найден».

    Точка входа — `def main` и/или блок `if __name__ == "__main__"`; от неё обход идёт
    по вызовам функций ТОГО ЖЕ файла до неподвижной точки. Дверь, определённая в файле,
    но не позванная ни с одного пути от входа, — ПОЛОВИНА ИНЪЕКЦИИ (урок ADR-932):
    снятая одной строкой проводка оставляет функцию двери в файле, и мера «дверь есть
    где-то в файле» объявила бы аварию закрытой. Входа нет (`None`) ⇒ вызывающий
    решает сам, чем судить; эта перепись тогда берёт весь файл.
    """
    funcs: Dict[str, ast.AST] = {
        n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    roots: List[ast.AST] = []
    if "main" in funcs:
        roots.append(funcs["main"])
    roots.extend(n for n in tree.body if _is_main_block(n))
    if not roots:
        return _doors_in(tree), None
    seen: set = set()
    queue: List[ast.AST] = list(roots)
    doors: List[str] = []
    while queue:
        node = queue.pop()
        doors.extend(_doors_in(node))
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = _name_of(sub.func)
                if name in funcs and name not in seen:
                    seen.add(name)
                    queue.append(funcs[name])
    return doors, True


def _writes_and_doors(tree: ast.Module) -> Tuple[List[str], bool, List[str], bool, bool]:
    """(формы записи, раздаёт ли `root=`, достижимые двери, дверь импортирована,
    дверь есть в файле, но от входа не достигается)."""
    writes: List[str] = []
    delegates = False
    door_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in DOOR_CALLS or alias.name in DOOR_ENV_NAMES:
                    door_imported = True
        if isinstance(node, ast.Call):
            name = _name_of(node.func)
            if name in WRITE_CALLS:
                writes.append(name)
            elif name in WRITE_ATTRS and isinstance(node.func, ast.Attribute):
                writes.append(name)
            elif name == "open":
                mode = None
                if len(node.args) >= 2:
                    mode = _const_str(node.args[1])
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode = _const_str(kw.value)
                if mode and any(ch in mode for ch in "wax"):
                    writes.append(f"open:{mode}")
            elif name == "run" and isinstance(node.func, ast.Attribute):
                if any(kw.arg == "root" for kw in node.keywords):
                    delegates = True
    doors, _entry_found = reachable_doors(tree)
    anywhere = _doors_in(tree)
    door_unreached = bool(anywhere) and not doors
    # уникально, порядок сохранён
    writes = list(dict.fromkeys(writes))
    doors = list(dict.fromkeys(doors))
    return writes, delegates, doors, door_imported, door_unreached


def judge_file(path: Path, repo: Path) -> Optional[Entry]:
    """Вердикт по одному файлу; None — файл вне поверхности (флага нет)."""
    rel = path.relative_to(repo).as_posix()
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Entry(path=rel, verdict="UNMEASURED", reason=f"не прочитан: {exc}")
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as exc:
        return Entry(path=rel, verdict="UNMEASURED", reason=f"не разобран: {exc}")
    found = _find_root_flag(tree)
    if found is None:
        return None
    flag, call = found
    dest = _dest_of(flag, call)
    default_expr: Optional[ast.AST] = None
    required = False
    for kw in call.keywords:
        if kw.arg == "default":
            default_expr = kw.value
        if kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            required = True
    writes, delegates, doors, door_imported, door_unreached = _writes_and_doors(tree)
    entry = Entry(path=rel, verdict="", flag=flag, writes=writes, delegates_root=delegates,
                  doors=doors, door_imported=door_imported, door_unreached=door_unreached)
    if required:
        entry.default_kind = "required"
    elif default_expr is None or (isinstance(default_expr, ast.Constant)
                                  and default_expr.value is None):
        fb = _fallback_for(tree, dest)
        if fb is not None:
            entry.default_kind = "fallback"
            entry.default = ast.get_source_segment(src, fb)
            entry.default_origin = _default_origin(fb, tree, src, repo)
        else:
            entry.default_kind = "none"
    else:
        entry.default_kind = "constant"
        entry.default = ast.get_source_segment(src, default_expr)
        entry.default_origin = _default_origin(default_expr, tree, src, repo)
    if doors:
        entry.verdict = "DOOR"
    elif not writes and not delegates:
        entry.verdict = "READER"
    elif entry.default_kind in ("required", "none"):
        entry.verdict = "EXPLICIT_ONLY"
    else:
        entry.verdict = "MARKER_BLIND"
    return entry


# ─────────────────────────── перепись ───────────────────────────

def surface_files(repo: Path, dirs: Tuple[str, ...]) -> List[Path]:
    out: List[Path] = []
    for d in dirs:
        base = repo / d
        if not base.is_dir():
            raise NotMeasured(f"каталог поверхности отсутствует: {base}")
        for p in sorted(base.glob("*.py")):
            if "/tests/" in p.as_posix() or p.name.startswith("test_"):
                continue
            out.append(p)
    return out


def measure(repo: Path, dirs: Tuple[str, ...] = SURFACE_DIRS) -> Census:
    repo = Path(repo).resolve()
    files = surface_files(repo, dirs)
    entries: List[Entry] = []
    for p in files:
        e = judge_file(p, repo)
        if e is not None:
            entries.append(e)
    counts: Dict[str, int] = {}
    for e in entries:
        counts[e.verdict] = counts.get(e.verdict, 0) + 1
    if not entries:
        return Census(str(repo), list(dirs), entries, counts, 2,
                      "поверхность ПУСТА: ни одной точки входа с флагом каталога — "
                      "«класс пуст» был бы вакуумом")
    blind = counts.get("MARKER_BLIND", 0)
    unm = counts.get("UNMEASURED", 0)
    if blind:
        code = 1
    elif unm:
        code = 2
    else:
        code = 0
    reason = None
    if code == 2:
        reason = f"{unm} файл(ов) не измерено — утверждать «предмет пуст» нельзя"
    return Census(str(repo), list(dirs), entries, counts, code, reason)


def render(c: Census) -> str:
    lines = [f"Перепись «песочница без названного каталога данных» · дерево {c.root} · "
             f"поверхность {', '.join(c.surface_dirs)}"]
    order = ("MARKER_BLIND", "DOOR", "EXPLICIT_ONLY", "READER", "UNMEASURED")
    lines.append("  точек входа с флагом каталога: " + str(len(c.entries)) + " · " +
                 " · ".join(f"{k} {c.counts.get(k, 0)}" for k in order))
    blind = c.blind
    if blind:
        lines.append(f"  🔴 ПРЕДМЕТ КЛАССА НАЗВАН ({len(blind)}): пишут под каталог из флага с "
                     "умолчанием и маркер песочницы не спрашивают")
        for e in blind:
            forms = ", ".join(e.writes) + (" + run(root=…)" if e.delegates_root else "")
            imp = " · дверь ИМПОРТИРОВАНА, но не позвана" if e.door_imported else ""
            if e.door_unreached:
                imp += " · дверь ЕСТЬ в файле, но от точки входа не достигается (половина инъекции)"
            lines.append(f"    - {e.path}: {e.flag} default={e.default!r} "
                         f"[{e.default_kind}/{e.default_origin}] пишет: {forms}{imp}")
    for e in c.unmeasured:
        lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО {e.path}: {e.reason}")
    if c.code == 0:
        lines.append("  ✅ предмет класса ПУСТ и измерен")
    elif c.code == 2:
        lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО: {c.unmeasured_reason}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, которое переписывается (умолчание — своё; ПЕЧАТАЕТСЯ)")
    ap.add_argument("--subtree", action="append", default=None,
                    help="ограничить поверхность одним каталогом (можно несколько раз)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo_root).resolve() if args.repo_root else ROOT
    if args.repo_root is None:
        print(f"[перепись] дерево не названо — беру своё: {repo}", file=sys.stderr)
    dirs = tuple(args.subtree) if args.subtree else SURFACE_DIRS
    try:
        census = measure(repo, dirs)
    except NotMeasured as exc:
        if args.json:
            print(json.dumps({"code": 2, "unmeasured_reason": str(exc)}, ensure_ascii=False))
        else:
            print(f"⚠️ НЕ ИЗМЕРЕНО: {exc}")
        return 2
    if args.json:
        doc = {"root": census.root, "surface_dirs": census.surface_dirs,
               "counts": census.counts, "code": census.code,
               "unmeasured_reason": census.unmeasured_reason,
               "entries": [asdict(e) for e in census.entries]}
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(render(census))
    return census.code


if __name__ == "__main__":
    sys.exit(main())
