#!/usr/bin/env python3
"""ЧИТАТЕЛИ ВЫВОДА git, РАЗБИРАЮЩИЕ ЕГО ПО ФИКСИРОВАННОЙ КОЛОНКЕ (заказ G919 п. 5).

Класс НАЗВАН циклом #1044 и до сегодня не был СОСЧИТАН. Авария, его родившая:
общая дверь `spa_core/monitoring/acceptance_tree_lineage._git` отдаёт вывод
`(proc.stdout or "").strip()`-нутым, а читатель в `orphan_sweep` разбирал
`git status --porcelain` срезом `line[3:]`. `.strip()` съедает ведущий пробел
**ПЕРВОЙ** строки и только её (` M data/x.json` → `M data/x.json`), поэтому срез
по колонке у первой строки съедал первый символ пути МОЛЧА: замер 05.11 дал
`ata/adapter_status.json` вместо `data/adapter_status.json`. Код возврата 0,
счётчик строк рядом совпал, ни один сторож не сказал ни слова.

Заказ G919 п. 5 оставил вопрос открытым дословно: «Сколько ещё читателей `_git`
разбирают вывод ПО КОЛОНКЕ — не мерено», и там же названы **девять**
неразобранных читателей `git status --porcelain`. Этот прибор отвечает на
вопрос ШИРЕ и машинно: предмет — не подкоманда `status`, а **встреча двух
половин** на одном потоке данных.

## Две половины, и ни одна из них в одиночку бомбой не является

| половина | что это | без второй половины |
|---|---|---|
| **A — дверь СТРИЖЁТ** | вывод возвращается через `.strip()`/`.lstrip()` | безвредно: никто не читает колонку |
| **B — чтение ПО КОЛОНКЕ** | срез строки литеральным индексом (`line[3:]`, `e[:2]`) | ВЕРНО: это документированная форма вывода git |

Поэтому прибор не ищет «`.strip()` рядом с `[3:]` в одном файле» — он прослеживает
**происхождение** строки: дверь → текстовая привязка → обход строк → срез.

## Третья половина, без которой находка была бы ВЫДУМАНА

Срез, у которого строка отфильтрована литеральным префиксом, НЕ зависит от
ведущего пробела: `?? путь` его не имеет вовсе, значит `.strip()` первой строке
ничего не портит, а строка ` M путь` после стрижки станет `M путь` и фильтр
`startswith("??")` её просто не пустит. Таких читателей в дереве два
(`system_health_monitor`, `reap_stale_worktrees`), и объявить их бомбами
значило бы ИЗГОТОВИТЬ находку, а не измерить её. Прибор называет их
`anchored` — якорь есть, и он напечатан.

## Три исхода, и третий не складывается в первые два (инвариант #17)

| исход | что доказано |
|---|---|
| `COLUMN_BOMB` | дверь стрижёт · колонка читается · якоря нет ⇒ первая строка разбирается НЕВЕРНО |
| `column_safe` | срез есть, но он либо на нестригущей двери, либо под якорем — измерено и названо |
| `unmeasured` | дверь не разрешилась, либо происхождение строки не прослеживается — причина НАЗВАНА |

«Не измерено» НИКОГДА не складывается в `column_safe`: население класса нулём
не считается, пока не измерено (урок `pyflakes`, `.claude/rules/deployment.md`).

## Чего прибор НЕ закрывает (названо заранее, а не после находки)

- **Дверь, добытая через ОБЩЕГО помощника**, прибор числит неразрешённой: он
  разбирает AST по модулю плюс явные `from … import <дверь>`, а дверь, пришедшую
  через `getattr`, словарь или фабрику, он назовёт `unmeasured`, а не «нет».
  Это та же граница, о которую споткнулся сторож претензии `injected-clock`
  (#477) и прибор ADR-897, и она объявлена, а не обнаружена.
- **`.strip()`, применённый не к целому выводу, а к СТРОКЕ перед срезом**
  (`line.strip()[3:]`) прибор ловит — это половина A на месте чтения; но
  стрижка, спрятанная за чужой функцией-однострочником, ему не видна.
- **«Колонка» здесь — литеральный индекс.** Срез по вычисленному смещению
  (`line[len(prefix):]`) к предмету не относится: он следует за содержимым, а не
  за колонкой.
- **Регулярное выражение колонкой не является** даже когда оно описывает те же
  позиции: `_porcelain_path` в `orphan_sweep` берёт буквы состояния ЖАДНО
  (одна или две) и потому переживает стрижку. Это и есть образец починки.
- Прибор только ЧИТАЕТ. Он ничего не правит и ничего не перезапускает.

Коды возврата (ADR-347): **0** — предмет пуст · **3** — предмет непуст ·
**2** — НЕ ИЗМЕРЕНО с названной причиной. 1 оставлен CPython, чтобы падение
прибора никогда не выглядело его находкой.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

#: Корни, в которых живёт рантайм-код. Тесты исключены НАМЕРЕННО и это замер, а
#: не вкус: бомба в тесте краснеет сама, бомба в рантайме молчит.
DEFAULT_SUBTREES = ("spa_core", "scripts")

#: Имена, под которыми stdlib запускает подпроцесс.
_SUBPROCESS_RUNNERS = {"run", "check_output", "Popen", "call", "check_call"}

#: Стригущие методы. `rstrip` в предмет НЕ входит: он трогает хвост, а колонка
#: живёт в голове строки. Назвать его половиной A значило бы изготовить находку.
_STRIPPERS = {"strip", "lstrip"}

#: Сколько кругов засева параметров делать до неподвижной точки. Авария #1044
#: отстоит от двери на ДВА хопа; предел нужен затем, что взаимная рекурсия
#: иначе крутила бы проход вечно. Исчерпание предела — НЕ «чисто»: оно
#: печатается и означает, что засев, возможно, не доехал до конца.
_PROPAGATION_ROUNDS = 6

#: Почему передача не доехала до получателя. Три рода, и они НЕ равнозначны:
#: `OUTSIDE` — почти всегда стандартная библиотека или встроенное (`len`,
#: `json.loads`), то есть шум; `AMBIGUOUS` и `VARIADIC` — пробел охвата В
#: ДЕРЕВЕ, и именно их читает человек. Одно число на три рода выдало бы шум за
#: пробел, а пробел утопило бы в шуме (замер цикла #1047: 63 против 4).
OUTSIDE = "получателя нет в объявленных подкаталогах (stdlib / встроенное)"
AMBIGUOUS = "одноимённых определений в модуле несколько — получатель НЕ УГАДЫВАЕТСЯ"
VARIADIC = "параметр ушёл в `*args`/`**kwargs` — слот не назван"

VERDICT_BOMB = "COLUMN_BOMB"
VERDICT_SAFE = "column_safe"
VERDICT_UNMEASURED = "unmeasured"


# ──────────────────────────────────────────────────────────────────────────────
# разбор
# ──────────────────────────────────────────────────────────────────────────────


def _subtree_has_attr(node: ast.AST, attr: str) -> bool:
    """Встречается ли в поддереве обращение к атрибуту `attr`."""
    return any(isinstance(n, ast.Attribute) and n.attr == attr for n in ast.walk(node))


def _is_git_argv(node: ast.AST) -> bool:
    """Это argv, чей ПЕРВЫЙ элемент — литерал ``git``?

    Спрашивается именно первый элемент: список, где слово `git` стоит в
    середине (`["env", "GIT_DIR=…", "git", …]`), прибор числит git-зовом тоже —
    но только если `git` есть литерал. Имя переменной вместо литерала ⇒ не
    git-зов для прибора, и это названная граница, а не «нет».
    """
    if isinstance(node, ast.List):
        for el in node.elts:
            if isinstance(el, ast.Constant) and el.value == "git":
                return True
            if isinstance(el, ast.Starred):
                continue
        return False
    if isinstance(node, ast.BinOp):            # ["git", …] + extra
        return _is_git_argv(node.left) or _is_git_argv(node.right)
    return False


def _git_call(node: ast.AST) -> bool:
    """Зов, исполняющий git через `subprocess`."""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr in _SUBPROCESS_RUNNERS:
        pass
    elif isinstance(fn, ast.Name) and fn.id in _SUBPROCESS_RUNNERS:
        pass
    else:
        return False
    if not node.args:
        return False
    return _is_git_argv(node.args[0])


def _stripped_expr(node: ast.AST) -> bool:
    """Выражение, прошедшее через `.strip()`/`.lstrip()`."""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _STRIPPERS
            and not node.args)


@dataclass
class Door:
    """Дверь к выводу git: функция, запускающая git и отдающая его текст."""

    module: str
    name: str
    lineno: int
    strips: Optional[bool]
    reason: str

    @property
    def key(self) -> str:
        return f"{self.module}::{self.name}"


def _door_strips(fn: ast.AST) -> Tuple[Optional[bool], str]:
    """Стрижёт ли дверь свой вывод. `None` ⇒ не измерено, причина названа.

    Мера проста и НАМЕРЕННО грубая в сторону находки: если хоть одно
    возвращаемое выражение несёт `.strip()` над чем-то, что произошло от
    `stdout`, дверь объявляется стригущей. Дверь с двумя путями возврата (один
    стрижёт, другой нет) в предмет попадает — и это верно: читателю достаётся
    то, что вернула ветка, а какая ветка отработала, статически не известно.
    """
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if not returns:
        return None, "у двери нет ни одного `return` со значением"

    # имена, чьё значение произошло от `stdout`, и признак стрижки у каждого
    tainted: Dict[str, bool] = {}
    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign):
            continue
        val = n.value
        if not _subtree_has_attr(val, "stdout"):
            continue
        stripped = any(_stripped_expr(x) and _subtree_has_attr(x, "stdout")
                       for x in ast.walk(val))
        for tgt in n.targets:
            for name in ast.walk(tgt):
                if isinstance(name, ast.Name):
                    tainted[name.id] = tainted.get(name.id, False) or stripped

    saw_text = False
    for ret in returns:
        subtree = list(ast.walk(ret.value))
        from_stdout = _subtree_has_attr(ret.value, "stdout")
        via_name = [x.id for x in subtree if isinstance(x, ast.Name) and x.id in tainted]
        if not from_stdout and not via_name:
            continue
        saw_text = True
        if from_stdout and any(_stripped_expr(x) and _subtree_has_attr(x, "stdout")
                               for x in subtree):
            return True, f"возврат на строке {ret.lineno} стрижёт `stdout`"
        if any(tainted[nm] for nm in via_name):
            return True, f"возврат на строке {ret.lineno} отдаёт стриженое имя"
    if not saw_text:
        return None, "ни один `return` двери не произошёл от `stdout`"
    return False, "ни один путь возврата вывод не стрижёт"


def collect_doors(tree: ast.AST, module: str) -> List[Door]:
    """Двери модуля: функции, запускающие git и отдающие его текст."""
    doors: List[Door] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_git_call(n) for n in ast.walk(node)):
            continue
        strips, reason = _door_strips(node)
        doors.append(Door(module=module, name=node.name, lineno=node.lineno,
                          strips=strips, reason=reason))
    return doors


@dataclass
class Finding:
    module: str
    func: str
    lineno: int
    verdict: str
    door: str
    door_strips: Optional[bool]
    anchor: Optional[str]
    column: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "module": self.module, "func": self.func, "line": self.lineno,
            "verdict": self.verdict, "door": self.door,
            "door_strips": self.door_strips, "anchor": self.anchor,
            "column": self.column, "reason": self.reason,
        }


@dataclass
class _Binding:
    """Локальное имя, несущее ТЕКСТ вывода git."""

    door: str
    strips: Optional[bool]
    reason: str


def _literal_column(node: ast.AST) -> Optional[str]:
    """Срез ПО ЛИТЕРАЛЬНОЙ колонке: `x[3:]`, `x[:2]`, `x[0]`. Иначе `None`."""
    if not isinstance(node, ast.Subscript):
        return None
    sl = node.slice
    if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
        return f"[{sl.value}]"
    if isinstance(sl, ast.Slice):
        lo = sl.lower
        hi = sl.upper
        lo_ok = lo is None or (isinstance(lo, ast.Constant) and isinstance(lo.value, int))
        hi_ok = hi is None or (isinstance(hi, ast.Constant) and isinstance(hi.value, int))
        if not (lo_ok and hi_ok):
            return None
        if lo is None and hi is None:
            return None                      # `x[:]` колонкой не является
        lo_s = "" if lo is None else str(lo.value)
        hi_s = "" if hi is None else str(hi.value)
        # Срез, начинающийся с нуля и идущий вправо, колонку головы ЧИТАЕТ
        # (`line[:2]` — буквы состояния), поэтому он тоже предмет.
        return f"[{lo_s}:{hi_s}]"
    return None


def _splitter_source(node: ast.AST) -> Tuple[Optional[ast.AST], bool]:
    """`X.splitlines()` / `X.split(...)` ⇒ (X, стрижётся ли X на месте)."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None, False
    if node.func.attr not in {"splitlines", "split"}:
        return None, False
    src = node.func.value
    local_strip = False
    while _stripped_expr(src):
        local_strip = True
        src = src.func.value                      # type: ignore[union-attr]
    return src, local_strip


def _anchor_of(scope_nodes: List[ast.AST], var: str) -> Optional[str]:
    """Литеральный ЯКОРЬ строки: `var.startswith("??")` в той же области.

    Якорь снимает зависимость от ведущего пробела ровно потому, что литерал,
    не начинающийся с пробела, у стриженой первой строки не совпадёт, а у
    нестриженой совпадёт только если пробела там и не было. Якорь, сам
    начинающийся с пробела, якорем НЕ является — он как раз и ломается.
    """
    for n in scope_nodes:
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in {"startswith", "removeprefix"}:
            continue
        base = n.func.value
        while _stripped_expr(base):
            base = base.func.value                # type: ignore[union-attr]
        if not (isinstance(base, ast.Name) and base.id == var):
            continue
        for arg in n.args:
            lits: List[str] = []
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                lits = [arg.value]
            elif isinstance(arg, ast.Tuple):
                lits = [e.value for e in arg.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            good = [s for s in lits if s and not s[0].isspace()]
            if good and len(good) == len(lits):
                return ", ".join(repr(s) for s in good)
    return None


class _FuncScan:
    """Разбор ОДНОЙ функции: привязки текста git и срезы по колонке.

    **Имя двери — не только её собственное.** Дверь приходит к читателю ещё
    двумя путями, и оба живут в дереве: модульный синоним (`git = _git`) и
    ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ у параметра (`def work_paths(wt, base, git=_git)`).
    Первая редакция прибора искала только собственное имя и потому не нашла
    `scripts/reap_stale_worktrees.py`, про который заказ G919 п. 5 знал прямым
    перечислением, — то есть ошибалась в сторону ПУСТОГО предмета. Ошибка
    такого прибора обязана идти в сторону находки.
    """

    def __init__(self, module: str, fn: ast.AST, doors: Dict[str, Door],
                 imported: Dict[str, Door],
                 seed_text: Optional[Dict[str, "_Binding"]] = None,
                 seed_line: Optional[Dict[str, "_Binding"]] = None) -> None:
        self.module = module
        self.fn = fn
        self.doors = dict(doors)
        self.imported = imported
        #: ЗАСЕВ: текст (или одна строка) вывода, доставшийся функции ПАРАМЕТРОМ
        #: от вызывающего. Без него прибор видит только те срезы, что живут в
        #: ОДНОЙ функции с зовом двери, а авария #1044 от двери на ДВА хопа:
        #: `_git` → `status_out=` у `_worktree_axis` → `line` у `_porcelain_path`.
        self.seed_text: Dict[str, "_Binding"] = dict(seed_text or {})
        self.seed_line: Dict[str, "_Binding"] = dict(seed_line or {})
        self.bindings: Dict[str, _Binding] = {}
        self.findings: List[Finding] = []
        self.lines_names: Set[str] = set()      # имена, несущие СПИСОК строк
        self.line_names: Dict[str, List[ast.AST]] = {}   # имя строки → область якоря
        self._lines_origin: Dict[str, Tuple[_Binding, bool]] = {}
        self._line_origin: Dict[str, Tuple[_Binding, bool]] = {}
        #: строки, рождённые ОБХОДОМ (`for ln in text.splitlines()`): их срезы
        #: ищет сам `scan_columns`, а здесь они нужны только чтобы ПЕРЕДАЧУ
        #: такой строки дальше было чем проследить
        self.loop_lines: Dict[str, _Binding] = {}
        args = getattr(fn, "args", None)
        if args is not None:
            slots = list(args.posonlyargs) + list(args.args)
            defaults = list(args.defaults)
            pairs = list(zip(slots[len(slots) - len(defaults):], defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d]
            for arg, default in pairs:
                if not isinstance(default, ast.Name):
                    continue
                door = doors.get(default.id) or imported.get(default.id)
                if door is not None:
                    self.doors[arg.arg] = door

    # — привязки ————————————————————————————————————————————————————
    def _door_of_call(self, call: ast.AST) -> Optional[_Binding]:
        if not isinstance(call, ast.Call):
            return None
        fn = call.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name is None:
            return None
        door = self.doors.get(name) or self.imported.get(name)
        if door is None:
            return None
        return _Binding(door=door.key, strips=door.strips, reason=door.reason)

    def _bind(self, targets: List[ast.AST], binding: _Binding) -> None:
        for tgt in targets:
            for nm in ast.walk(tgt):
                if isinstance(nm, ast.Name):
                    self.bindings[nm.id] = binding

    def scan_bindings(self) -> None:
        # Параметр несёт текст двери ДО первого присваивания в теле; локальное
        # присваивание тому же имени ниже перепишет привязку своей, и это верно.
        self.bindings.update(self.seed_text)
        for n in ast.walk(self.fn):
            if not isinstance(n, (ast.Assign, ast.AnnAssign)):
                continue
            targets = list(n.targets) if isinstance(n, ast.Assign) else [n.target]
            val = n.value
            if val is None:
                continue
            # прямой зов git: `p = subprocess.run([... git ...])`
            if _git_call(val):
                self._bind(targets, _Binding(door="subprocess(git)", strips=False,
                                             reason="вывод берётся у `subprocess` напрямую"))
                continue
            # `out = p.stdout` / `out = p.stdout.strip()` / `out = git(...)`
            if _subtree_has_attr(val, "stdout"):
                stripped = any(_stripped_expr(x) and _subtree_has_attr(x, "stdout")
                               for x in ast.walk(val))
                self._bind(targets, _Binding(
                    door="subprocess(git).stdout", strips=stripped,
                    reason=("вывод стрижётся на месте привязки" if stripped
                            else "вывод берётся у `subprocess` напрямую")))
                continue
            binding = self._door_of_call(val)
            if binding is not None:
                self._bind(targets, binding)

    # — чтение по колонке ————————————————————————————————————————————
    def _text_binding(self, src: ast.AST) -> Optional[_Binding]:
        if isinstance(src, ast.Name):
            return self.bindings.get(src.id)
        if isinstance(src, ast.Attribute) and src.attr == "stdout":
            return _Binding(door="subprocess(git).stdout", strips=False,
                            reason="вывод берётся у `subprocess` напрямую")
        if isinstance(src, ast.Call):
            return self._door_of_call(src)
        return None

    def _record(self, lineno: int, binding: _Binding, column: str,
                anchor: Optional[str], local_strip: bool) -> None:
        strips = True if local_strip else binding.strips
        if strips is None:
            verdict, reason = VERDICT_UNMEASURED, (
                f"стрижёт ли дверь `{binding.door}` — не разрешилось: {binding.reason}")
        elif not strips:
            verdict, reason = VERDICT_SAFE, (
                f"дверь `{binding.door}` вывод НЕ стрижёт: {binding.reason}")
        elif anchor is not None:
            verdict, reason = VERDICT_SAFE, (
                f"дверь стрижёт, но срез под ЯКОРЕМ {anchor} — ведущий пробел ему безразличен")
        else:
            verdict, reason = VERDICT_BOMB, (
                f"дверь `{binding.door}` стрижёт вывод ({binding.reason}), а срез {column} "
                f"читает голову строки без якоря ⇒ ПЕРВАЯ строка разбирается неверно")
        self.findings.append(Finding(
            module=self.module, func=getattr(self.fn, "name", "?"), lineno=lineno,
            verdict=verdict, door=binding.door,
            door_strips=strips, anchor=anchor, column=column, reason=reason))

    def _scan_scope(self, var: str, body: List[ast.AST], binding: _Binding,
                    local_strip: bool, lineno: int,
                    scope: Optional[List[ast.AST]] = None) -> None:
        scope_nodes = scope if scope is not None else [x for node in body for x in ast.walk(node)]
        anchor = _anchor_of(scope_nodes, var)
        seen: Set[str] = set()
        for x in scope_nodes:
            col = _literal_column(x)
            if col is None:
                continue
            base = x.value                                  # type: ignore[union-attr]
            inner_strip = False
            while _stripped_expr(base):
                inner_strip = True
                base = base.func.value                      # type: ignore[union-attr]
            if not (isinstance(base, ast.Name) and base.id == var):
                continue
            key = f"{getattr(x, 'lineno', lineno)}:{col}"
            if key in seen:
                continue
            seen.add(key)
            self._record(getattr(x, "lineno", lineno), binding, col, anchor,
                         local_strip or inner_strip)

    def scan_lines(self) -> None:
        """Имена, несущие ОДНУ строку вывода, и область, где искать её якорь.

        Строка достаётся читателю тремя формами, и все три живут в дереве:
        обходом (`for ln in text.splitlines()`), включением
        (`{ln[3:] for ln in text.splitlines() if …}`) и — что первая редакция
        прибора не видела — ИНДЕКСОМ по заранее разрезанному списку
        (`ents = out.split("\\0")` … `e = ents[i]`), как в
        `scripts/memory_backup.py`. Форма «индекс» встречается у `-z`-разбора,
        то есть ровно там, где колонка и читается.
        """
        fn_scope = [x for st in getattr(self.fn, "body", []) for x in ast.walk(st)]
        # список строк: `lines = TEXT.splitlines()`
        for n in ast.walk(self.fn):
            if not isinstance(n, ast.Assign):
                continue
            src, local_strip = _splitter_source(n.value)
            if src is None:
                continue
            binding = self._text_binding(src)
            if binding is None:
                continue
            for tgt in n.targets:
                names = [x for x in ast.walk(tgt) if isinstance(x, ast.Name)]
                # кортежная цель (`ents, out, i = text.split(...), [], 0`) даёт
                # список строк только ПЕРВОМУ имени; остальные к нему не причастны
                if isinstance(tgt, ast.Tuple) and isinstance(n.value, ast.Tuple):
                    continue
                for nm in names:
                    self.lines_names.add(nm.id)
                    self._lines_origin[nm.id] = (binding, local_strip)
        # кортежная распаковка, где РАЗРЕЗ стоит на своей позиции
        for n in ast.walk(self.fn):
            if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Tuple)
                    and isinstance(n.value, ast.Tuple)):
                continue
            for tgt, val in zip(n.targets[0].elts, n.value.elts):
                src, local_strip = _splitter_source(val)
                if src is None or not isinstance(tgt, ast.Name):
                    continue
                binding = self._text_binding(src)
                if binding is None:
                    continue
                self.lines_names.add(tgt.id)
                self._lines_origin[tgt.id] = (binding, local_strip)
        # имя ОДНОЙ строки: `e = lines[i]`
        for n in ast.walk(self.fn):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Subscript):
                continue
            base = n.value.value
            if not (isinstance(base, ast.Name) and base.id in self.lines_names):
                continue
            if _literal_column(n.value) is not None:
                continue                      # `lines[0]` — выбор строки, не колонка
            for tgt in n.targets:
                if isinstance(tgt, ast.Name):
                    self.line_names[tgt.id] = fn_scope
                    self._line_origin[tgt.id] = self._lines_origin[base.id]
        # имя ОДНОЙ строки: обход готового списка строк
        for n in ast.walk(self.fn):
            if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) \
                    and n.iter.id in self.lines_names and isinstance(n.target, ast.Name):
                self.line_names[n.target.id] = [x for st in n.body for x in ast.walk(st)]
                self._line_origin[n.target.id] = self._lines_origin[n.iter.id]
        # имя ОДНОЙ строки: ПАРАМЕТР, которому строку передал вызывающий
        # (`_porcelain_path(line)` — ровно форма аварии #1044). Якорь ищется по
        # всему телу функции: за её пределами о строке ничего не известно.
        for nm, binding in self.seed_line.items():
            if nm in self.line_names:
                continue
            self.line_names[nm] = fn_scope
            self._line_origin[nm] = (binding, False)

    def scan_columns(self) -> None:
        for n in ast.walk(self.fn):
            # `for v in TEXT.splitlines(): …`
            if isinstance(n, ast.For):
                src, local_strip = _splitter_source(n.iter)
                if src is None or not isinstance(n.target, ast.Name):
                    continue
                binding = self._text_binding(src)
                if binding is None:
                    continue
                self.loop_lines.setdefault(n.target.id, binding)
                self._scan_scope(n.target.id, list(n.body), binding, local_strip, n.lineno)
                continue
            # `[… v … for v in TEXT.splitlines() if …]`
            if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                for gen in n.generators:
                    src, local_strip = _splitter_source(gen.iter)
                    if src is None and isinstance(gen.iter, ast.Name) \
                            and gen.iter.id in self.lines_names:
                        binding, local_strip = self._lines_origin[gen.iter.id]
                    elif src is None:
                        continue
                    else:
                        binding = self._text_binding(src)
                    if binding is None or not isinstance(gen.target, ast.Name):
                        continue
                    parts: List[ast.AST] = list(gen.ifs)
                    if isinstance(n, ast.DictComp):
                        parts += [n.key, n.value]
                    else:
                        parts.append(n.elt)                 # type: ignore[attr-defined]
                    self.loop_lines.setdefault(gen.target.id, binding)
                    self._scan_scope(gen.target.id, parts, binding, local_strip, n.lineno)
        # строки, добытые индексом или обходом готового списка
        for name, scope in self.line_names.items():
            binding, local_strip = self._line_origin[name]
            self._scan_scope(name, [], binding, local_strip,
                             getattr(self.fn, "lineno", 0), scope=scope)

    # — передача дальше ——————————————————————————————————————————————
    def propagations(self) -> List[Tuple[str, bool, Optional[int], Optional[str],
                                         str, "_Binding"]]:
        """Куда эта функция ПЕРЕДАЁТ текст двери (или одну его строку) дальше.

        Отвечает формой «кого зовут · на какой позиции · каким ключевым словом ·
        род · привязка». Имя параметра у принимающей функции здесь НЕ известно —
        его знает только `measure()`, у которого есть указатель определений;
        угадывать его тут значило бы завести вторую копию разрешения имён.

        **Род передачи ровно два, и третий НАЗВАН, а не подставлен.** Текст
        (`out`) и ОДНА строка (`line`) — две разные вещи для принимающего: из
        первого он сам сделает `splitlines()`, вторую прочтёт как есть. Список
        строк (`lines`), переданный целиком, этим прибором НЕ прослеживается —
        формы `for ln in lines` у принимающего он не засеет, и это объявленная
        граница, а не ноль.
        """
        out: List[Tuple[str, bool, Optional[int], Optional[str], str,
                        "_Binding"]] = []
        for n in ast.walk(self.fn):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            if isinstance(fn, ast.Name):
                callee, bound = fn.id, False
            elif isinstance(fn, ast.Attribute):
                # зов «через точку»: позиционные аргументы получателя сдвинуты
                # на `self`/`cls`, и не знать этого значило бы засеять ЧУЖОЙ
                # параметр — хуже, чем не засеять ни один
                callee, bound = fn.attr, True
            else:
                continue
            pairs: List[Tuple[Optional[int], Optional[str], ast.AST]] = [
                (i, None, a) for i, a in enumerate(n.args)
                if not isinstance(a, ast.Starred)]
            pairs += [(None, kw.arg, kw.value) for kw in n.keywords if kw.arg]
            for pos, key, val in pairs:
                if not isinstance(val, ast.Name):
                    continue
                if val.id in self.line_names:
                    out.append((callee, bound, pos, key, "line",
                                self._line_origin[val.id][0]))
                elif val.id in self.loop_lines:
                    out.append((callee, bound, pos, key, "line",
                                self.loop_lines[val.id]))
                elif val.id in self.bindings:
                    out.append((callee, bound, pos, key, "text",
                                self.bindings[val.id]))
        return out


# ──────────────────────────────────────────────────────────────────────────────
# замер
# ──────────────────────────────────────────────────────────────────────────────


def _py_files(root: Path, subtrees: Tuple[str, ...]) -> List[Path]:
    """Рантайм-модули под объявленными корнями. Тесты исключены по ИМЕНИ."""
    out: List[Path] = []
    for sub in subtrees:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or p.name.startswith("test_"):
                continue
            out.append(p)
    return out


@dataclass
class Census:
    findings: List[Finding] = field(default_factory=list)
    doors: List[Door] = field(default_factory=list)
    unparsed: List[Tuple[str, str]] = field(default_factory=list)
    #: кругов засева параметров ушло · исчерпан ли предел · получатели передач,
    #: которых не нашли. Третий исход обязан ДОЕЗЖАТЬ до читателя, иначе он не
    #: третий исход, а поле в отчёте (ровно замечание шага 0-офис про ADR-851)
    propagation_rounds: int = 0
    propagation_exhausted: bool = False
    propagation_unresolved: List[str] = field(default_factory=list)

    @property
    def bombs(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == VERDICT_BOMB]

    @property
    def safe(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == VERDICT_SAFE]

    @property
    def unmeasured(self) -> List[Finding]:
        return [f for f in self.findings if f.verdict == VERDICT_UNMEASURED]

    def as_dict(self, root: Path) -> dict:
        return {
            "root": str(root),
            "doors": len(self.doors),
            "doors_stripping": sum(1 for d in self.doors if d.strips is True),
            "doors_unmeasured": sum(1 for d in self.doors if d.strips is None),
            "surface": len(self.findings),
            "bomb": len(self.bombs),
            "column_safe": len(self.safe),
            "unmeasured": len(self.unmeasured),
            "unparsed_modules": [{"module": m, "reason": r} for m, r in self.unparsed],
            "propagation_rounds": self.propagation_rounds,
            "propagation_exhausted": self.propagation_exhausted,
            "propagation_unresolved": self.propagation_unresolved,
            "findings": [f.as_dict() for f in self.findings],
        }


def measure(root: Path, subtrees: Tuple[str, ...] = DEFAULT_SUBTREES) -> Census:
    """Перепись класса в дереве `root`.

    Двери собираются по ВСЕМУ дереву сперва, потому что дверь и её читатель
    почти никогда не живут в одном модуле: авария #1044 именно такая
    (`acceptance_tree_lineage._git` против `orphan_sweep`).
    """
    root = Path(root).resolve()
    files = _py_files(root, subtrees)
    census = Census()
    trees: Dict[str, Tuple[ast.AST, str]] = {}
    by_module: Dict[str, List[Door]] = {}

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            census.unparsed.append((rel, f"файл не прочитан: {exc}"))
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            census.unparsed.append((rel, f"модуль не разобрался: {exc}"))
            continue
        trees[rel] = (tree, src)
        doors = collect_doors(tree, rel)
        by_module[rel] = doors
        census.doors.extend(doors)

    #: дверь адресуется ИМЕНЕМ МОДУЛЯ, иначе одноимённые `_git` из разных
    #: модулей слились бы в одну и ответ о стрижке достался бы чужой двери
    module_of_dotted = {rel.replace("/", ".")[:-3]: rel for rel in trees}

    #: Второй адрес того же модуля — ГОЛОЕ имя по `sys.path`. Эту форму дерево
    #: использует наравне с точечной (`from check_undelivered_work import …` в
    #: `scripts/reap_stale_worktrees.py`), и не знать её значит числить дверь
    #: неразрешённой там, где она разрешима. Неоднозначный огрызок (один стем у
    #: двух модулей) НЕ разрешается вовсе: угаданная дверь дала бы ответ о
    #: стрижке ЧУЖОЙ двери, а это хуже «не измерено».
    by_stem: Dict[str, List[str]] = {}
    for rel in trees:
        by_stem.setdefault(rel.rsplit("/", 1)[-1][:-3], []).append(rel)
    module_of_stem = {stem: rels[0] for stem, rels in by_stem.items() if len(rels) == 1}

    def _module_of(dotted: str) -> Optional[str]:
        return (module_of_dotted.get(dotted)
                or module_of_stem.get(dotted.rsplit(".", 1)[-1]))

    #: двери, ввезённые в модуль под своим или чужим именем
    imported_doors: Dict[str, Dict[str, Door]] = {}
    #: ФУНКЦИИ, ввезённые в модуль: алиас → (модуль-источник, имя)
    imported_funcs: Dict[str, Dict[str, Tuple[str, str]]] = {}
    #: определения функций модуля; одноимённые внутри модуля НЕ разрешаются
    #: вовсе — засеять угаданного получателя хуже, чем не засеять никого
    funcs_of: Dict[str, Dict[str, ast.AST]] = {}
    #: одноимённые определения модуля: получатель по такому имени НЕ УГАДЫВАЕТСЯ
    ambiguous_of: Dict[str, Set[str]] = {}

    for rel, (tree, _src) in trees.items():
        doors_here: Dict[str, Door] = {}
        funcs_here: Dict[str, ast.AST] = {}
        ambiguous: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in funcs_here:
                    ambiguous.add(node.name)
                funcs_here[node.name] = node
                continue
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            src_rel = _module_of(node.module)
            if src_rel is None:
                continue
            src_doors = {d.name: d for d in by_module.get(src_rel, [])}
            for alias in node.names:
                door = src_doors.get(alias.name)
                if door is not None:
                    doors_here[alias.asname or alias.name] = door
                imported_funcs.setdefault(rel, {})[alias.asname or alias.name] = (
                    src_rel, alias.name)
        for name in ambiguous:
            funcs_here.pop(name, None)
        imported_doors[rel] = doors_here
        funcs_of[rel] = funcs_here
        ambiguous_of[rel] = ambiguous

    def _param_name(callee: ast.AST, bound: bool, pos: Optional[int],
                    key: Optional[str]) -> Optional[str]:
        args = getattr(callee, "args", None)
        if args is None:
            return None
        slots = list(args.posonlyargs) + list(args.args)
        if key is not None:
            for a in slots + list(args.kwonlyargs):
                if a.arg == key:
                    return a.arg
            return None                      # ушло в `**kwargs` ⇒ не разрешено
        if pos is None:
            return None
        idx = pos + (1 if bound and slots and slots[0].arg in ("self", "cls") else 0)
        if idx >= len(slots):
            return None                      # ушло в `*args` ⇒ не разрешено
        return slots[idx].arg

    def _scan_all(seeds: Dict[Tuple[str, str], Dict[str, Dict[str, _Binding]]],
                  only: Optional[Set[Tuple[str, str]]] = None):
        """Проход по дереву с текущим засевом. Возвращает сканы и передачи.

        `only` сужает проход до функций, чей ЗАСЕВ изменился на прошлом круге:
        у остальных ни привязки, ни срезы измениться не могли, и перебирать их
        заново значило бы платить полную цену обхода за каждый круг. Полный
        проход при этом остаётся ДВАЖДЫ — первым кругом и последним (сбор
        находок), — иначе сужение могло бы спрятать площадку.
        """
        scans: List[Tuple[str, ast.AST, _FuncScan]] = []
        for rel, (tree, _src) in trees.items():
            local = {d.name: d for d in by_module.get(rel, [])}
            imported = imported_doors.get(rel, {})
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if only is not None and (rel, node.name) not in only:
                    continue
                seed = seeds.get((rel, node.name), {})
                scan = _FuncScan(rel, node, local, imported,
                                 seed_text=seed.get("text"), seed_line=seed.get("line"))
                scan.scan_bindings()
                scan.scan_lines()
                scan.scan_columns()
                scans.append((rel, node, scan))
        return scans

    #: ЗАСЕВ до неподвижной точки. Авария #1044 отстоит от двери на ДВА хопа
    #: (`out` параметром → строка параметром), поэтому одного прохода мало;
    #: предел кругов объявлен, и его исчерпание НАЗЫВАЕТСЯ, а не глотается.
    seeds: Dict[Tuple[str, str], Dict[str, Dict[str, _Binding]]] = {}
    unresolved: Set[str] = set()
    rounds, exhausted = 0, False
    frontier: Optional[Set[Tuple[str, str]]] = None      # None = полный проход
    for rounds in range(1, _PROPAGATION_ROUNDS + 1):
        scans = _scan_all(seeds, frontier)
        grew = False
        if frontier is None:
            # перечень «не разрешилось» снимается на ПОЛНОМ проходе: на суженном
            # он описывал бы только фронт, то есть отвечал бы о своём охвате —
            # ровно тот дефект, из-за которого эта поправка и понадобилась
            unresolved = set()
        next_frontier: Set[Tuple[str, str]] = set()
        for rel, _node, scan in scans:
            for callee_name, bound, pos, key, kind, binding in scan.propagations():
                target = None
                if callee_name in funcs_of.get(rel, {}):
                    target = (rel, callee_name)
                elif callee_name in imported_funcs.get(rel, {}):
                    src_rel, real = imported_funcs[rel][callee_name]
                    if real in funcs_of.get(src_rel, {}):
                        target = (src_rel, real)
                if target is None:
                    # Род «не разрешилось» ТРИ, и складывать их в одно число
                    # значило бы выдать шум стандартной библиотеки за пробел
                    # охвата: `len(out)` колонку не читает по построению, а
                    # одноимённый получатель В ДЕРЕВЕ — настоящий пробел.
                    why = (AMBIGUOUS if callee_name in ambiguous_of.get(rel, ())
                           else OUTSIDE)
                    unresolved.add(f"{rel}::{callee_name} — {why}")
                    continue
                param = _param_name(funcs_of[target[0]][target[1]], bound, pos, key)
                if param is None:
                    unresolved.add(f"{target[0]}::{target[1]}"
                                   f"({pos if key is None else key}) — {VARIADIC}")
                    continue
                slot = seeds.setdefault(target, {}).setdefault(kind, {})
                if slot.get(param) is None:
                    slot[param] = binding
                    grew = True
                    next_frontier.add(target)
        if not grew:
            break
        frontier = next_frontier
    else:
        exhausted = True

    census.propagation_rounds = rounds
    census.propagation_exhausted = exhausted
    census.propagation_unresolved = sorted(unresolved)
    for _rel, _node, scan in _scan_all(seeds):
        census.findings.extend(scan.findings)
    return census


def render(census: Census, root: Path) -> str:
    """Отчёт человеку. Числа печатаются ВСЕ три, и «не измерено» — отдельным."""
    lines: List[str] = []
    bombs, safe, unm = census.bombs, census.safe, census.unmeasured
    lines.append(f"Читатели вывода git, разбирающие его ПО КОЛОНКЕ (дерево {root}):")
    lines.append(f"   двери к выводу git: {len(census.doors)} · "
                 f"СТРИГУТ {sum(1 for d in census.doors if d.strips is True)} · "
                 f"не стригут {sum(1 for d in census.doors if d.strips is False)} · "
                 f"НЕ ИЗМЕРЕНО {sum(1 for d in census.doors if d.strips is None)}")
    lines.append(f"   поверхность (срезов по колонке): {len(census.findings)} — "
                 f"БОМБА {len(bombs)} · безопасно {len(safe)} · НЕ ИЗМЕРЕНО {len(unm)}")
    # Засев параметров ОБЯЗАН доезжать до читателя числом: без него поверхность
    # есть только то, что живёт в ОДНОЙ функции с зовом двери, и «0» описывал бы
    # охват прибора. Число кругов и перечень неразрешённых получателей — это
    # третий исход, а третий исход, который никто не читает, им не является
    # (замечание шага 0-офис про ADR-851, цикл #1047).
    lines.append(f"   засев параметров: кругов {census.propagation_rounds}"
                 + (" (ПРЕДЕЛ ИСЧЕРПАН — засев мог не доехать)"
                    if census.propagation_exhausted else " (неподвижная точка)")
                 + f" · получателей НЕ РАЗРЕШЕНО {len(census.propagation_unresolved)}"
                 + f" (из них пробел В ДЕРЕВЕ "
                   f"{sum(1 for u in census.propagation_unresolved if OUTSIDE not in u)})")
    for f in bombs:
        lines.append(f"   💣 {f.module}:{f.lineno} {f.func}() срез {f.column} ← {f.door}")
        lines.append(f"      {f.reason}")
    for f in unm:
        lines.append(f"   ⚠️ НЕ ИЗМЕРЕНО {f.module}:{f.lineno} {f.func}() срез {f.column}")
        lines.append(f"      {f.reason}")
    for f in safe:
        anchor = f" под якорем {f.anchor}" if f.anchor else ""
        lines.append(f"   ▫️ безопасно {f.module}:{f.lineno} {f.func}() срез {f.column}{anchor}")
    if census.unparsed:
        lines.append(f"   ⚠️ модулей не разобрано: {len(census.unparsed)}")
        for m, r in census.unparsed[:5]:
            lines.append(f"      {m} — {r}")
    gaps = [u for u in census.propagation_unresolved if OUTSIDE not in u]
    noise = len(census.propagation_unresolved) - len(gaps)
    if gaps:
        lines.append(f"   ⚠️ ПРОБЕЛ ОХВАТА В ДЕРЕВЕ ({len(gaps)}): передача дошла до "
                     "получателя, но слот не назван — срезы у него в поверхность НЕ "
                     "вошли, и нулём это не считается:")
        for u in gaps[:10]:
            lines.append(f"      {u}")
    if noise:
        lines.append(f"   · передач получателям ВНЕ объявленных подкаталогов: {noise} "
                     "(stdlib / встроенное; какие из них читают колонку, прибор не "
                     "угадывает и не выдаёт это за ноль)")
    if bombs:
        lines.append(f"❌ предмет НЕПУСТ: {len(bombs)} срез(ов) по колонке на стригущей двери")
    elif census.propagation_exhausted:
        lines.append("⚠️ НЕ ИЗМЕРЕНО целиком: предел кругов засева исчерпан — "
                     "часть передач могла не доехать, нулём это не считается")
    elif unm or census.unparsed:
        lines.append("⚠️ НЕ ИЗМЕРЕНО целиком: часть поверхности не разрешилась — "
                     "нулём это не считается")
    else:
        lines.append("✅ предмет ПУСТ: ни один срез по колонке не стоит на стригущей двери")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None,
                    help="корень дерева (умолчание — дерево этого файла)")
    ap.add_argument("--subtree", action="append", default=None,
                    help="подкаталог для обхода (можно несколько; умолчание — spa_core, scripts)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    subtrees = tuple(args.subtree) if args.subtree else DEFAULT_SUBTREES
    if not root.is_dir():
        print(f"НЕ ИЗМЕРЕНО: корень {root} не каталог", file=sys.stderr)
        return 2
    if not any((root / s).is_dir() for s in subtrees):
        print(f"НЕ ИЗМЕРЕНО: под {root} нет ни одного из объявленных подкаталогов "
              f"{', '.join(subtrees)}", file=sys.stderr)
        return 2

    census = measure(root, subtrees)
    if args.json:
        print(json.dumps(census.as_dict(root), ensure_ascii=False, indent=2))
    else:
        print(render(census, root))
    if census.bombs:
        return 3
    # Исчерпанный предел кругов засева есть «НЕ ИЗМЕРЕНО», а не «чисто»: часть
    # передач могла не доехать до получателя, и срезы у него в поверхность не
    # вошли. Складывать это в ноль значило бы вернуть ровно тот дефект, из-за
    # которого первая редакция прибора ответила «предмет ПУСТ» над аварией.
    if census.unmeasured or census.unparsed or census.propagation_exhausted:
        return 2
    return 0


if __name__ == "__main__":        # pragma: no cover
    sys.exit(main())
