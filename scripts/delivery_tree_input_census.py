#!/usr/bin/env python3
"""Сколько обязательных шагов цикла поднимают долгий прогон, НЕ умея назвать дерево.

Класс найден 05.11 (цикл #1039, карточка
``inbox-obyazatelnyi-shag-1g-podnimaet-dolgii-py``, ADR-926) и закрыт у ОДНОЙ двери —
шага 1г. Там он выглядел так: обязательный шаг ``scripts/import_time_anchor_bombs.py``
поднимает дочерний ``pytest`` по десяткам тест-модулей (прогон на минуты), а входа
«в каком дереве» у него не было вовсе — значит прогон идёт в том дереве, из которого
скрипт запущен, а цикл, правивший тесты, запускает его из своего ДЕРЕВА ДОСТАВКИ по
построению.

**Почему это дефект, а не неудобство.** ``.claude/rules/deployment.md``
§ «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ КОДОМ» п. 1: «долгий прогон НЕ ЖИВЁТ в дереве доставки»,
и цена запрета ИЗМЕРЕНА аварией цикла #1000 — часть предписанного набора
инструментирует исходники НА МЕСТЕ (``_GBC_REC``, перепись ADR-543), снятый прогон
оставил синтаксически битый ``card_acceptance.py``, и ``f4612d8e9`` увёз его на ``main``;
три сторожа доставки ответили верно и мимо. То есть обязательный шаг протокола
приглашал ровно то состояние, которое правило запрещает.

**«Измерил и обошлось» мерой класса не является** — поэтому эта перепись. Она отвечает
на один вопрос по КАЖДОМУ объявленному шагу: *поднимает ли шаг долгий дочерний прогон,
и может ли вызывающий НАЗВАТЬ дерево, в котором тот пойдёт.*

**Объявление, а не вкус: поверхность берётся из объявления, а не из головы.** Шаги —
это пути ``scripts/*.py``, названные там, где шаг объявляется обязательным; собирать
поверхность обходом каталога ``scripts/`` значило бы мерить триста скриптов, из которых
шагом цикла не является почти ни один, и утопить предмет в шуме.

**Мест объявления ДВА, и это замер, а не удобство.** Первая редакция этого прибора
брала поверхность только из ``docs/ORCHESTRATOR_PROTOCOL.md`` и ответила
«✅ предмет класса ПУСТ» при пятнадцати шагах — потому что ``import_time_anchor_bombs.py``,
то есть РОВНО та дверь, по которой класс и найден, в документе не названа НИ РАЗУ.
Обязательные шаги 1 · 1в · 1г · 1д · 1е цикл читает из промпта, собираемого
``scripts/agent_orchestrator.sh``; документ описывает протокол, а исполняется ТЕКСТ
ПРОМПТА. Поэтому поверхность — ОБЪЕДИНЕНИЕ двух мест, у каждого шага печатается, откуда
он взят, и **недоступность ЛЮБОГО из двух мест есть `NotMeasured`**, а не поверхность
поменьше: урезанная поверхность отвечает «чисто» ровно про то, чего не видела. Это тот
же урок, что у положительного контроля ADR-932: «✅ ПУСТ» при зелёных сценах означает
не пустой класс, а меру, не добравшуюся до предмета.

**Объявить вход — НЕ то же, что провести его до прогона (урок ADR-932).** Параметр,
который объявлен у функции и которому никто не передаёт значение из CLI, — это
«половина инъекции», и она ничем не лучше отсутствия входа: дерево по-прежнему
неназываемо. Поэтому вердикт даёт не наличие флага, а ДОСТИЖИМОСТЬ: засев от
``args.<флаг>`` распространяется по присваиваниям и В ПАРАМЕТРЫ вызываемых функций до
неподвижной точки, и спрашивается, доехал ли он до ``cwd=`` дочернего прогона. Шаг 1г
до починки отстоял от ``cwd=`` на ДВА хопа через параметры (``main`` → ``bombs(root)``
→ ``outcomes(..., root)`` → ``subprocess.run(cwd=root)``), то есть мера, разбирающая
одну функцию, назвала бы класс пустым.

**Три исхода различимы у каждого шага (инв. #17):**

* ``NAMEABLE``   — поднимает долгий прогон, и вход достаёт до его ``cwd=``;
* ``HALF``       — вход ОБЪЯВЛЕН, но до ``cwd=`` не доехал (форма ADR-932);
* ``UNNAMEABLE`` — поднимает долгий прогон, назвать дерево нечем (предмет класса);
* ``NO_LONG_RUN``— долгого дочернего прогона не поднимает, вне предмета;
* ``UNMEASURED`` — файла нет · не разобрался · засев исчерпал предел кругов.

«НЕ ИЗМЕРЕНО» никогда не выдаётся за «чисто»: шаг, названный в протоколе и
отсутствующий в дереве, — это отказ с причиной, а не вычитание из населения.

**Что перепись НЕ закрывает (названо вслух, чтобы не читалось шире).** Долгим прогоном
считается дочерний ``pytest``: это ФОРМА измеренной аварии (инструментирующий тест),
и она разрешима статически. Мутационный прибор, инструментирующая перепись или
``git``-обход, которые тоже пишут в дерево, этой мерой не судятся — у них свой
объявленный шов (``.mutation_window``, ADR-772), и выдумывать им общий предикат
значило бы завести меру, отвечающую «я не умею» под видом «чисто». Засев идёт ВНУТРИ
одного файла: шаг, делегирующий прогон модулю из ``spa_core``, получает
``UNRESOLVED``-пометку с названным получателем, а не молчаливое «чисто».

Запуск::

    python3 scripts/delivery_tree_input_census.py [--repo-root <дерево>] [--json]

Коды возврата: 0 — предмет класса пуст · 1 — предмет НАЗВАН · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

#: Места, где шаг цикла объявляется обязательным. ДВА, и оба обязательны к прочтению:
#: промпт — то, что сессия исполняет; документ — то, что описывает протокол. Замер
#: 06.11: из 16 шагов 15 названы только в документе, а `import_time_anchor_bombs.py` —
#: только в промпте, и это ровно дверь, по которой класс найден.
DECLARATION_PLACES = ("scripts/agent_orchestrator.sh", "docs/ORCHESTRATOR_PROTOCOL.md")

#: Как в документе выглядит ссылка на шаг.
_STEP_RE = re.compile(r"\bscripts/([A-Za-z0-9_]+)\.py\b")

#: Имена, под которыми stdlib поднимает дочерний процесс.
_SPAWNERS = {"run", "Popen", "check_output", "call", "check_call"}

#: Слово, по которому дочерний процесс опознаётся как ДОЛГИЙ прогон по дереву.
#: Это форма измеренной аварии (#1000), а не весь мыслимый долгий прогон — граница
#: названа в докстринге модуля.
_LONG_RUN_TOKEN = "pytest"

#: Флаги, которыми вызывающий называет дерево прогона. `--data-dir` сюда НЕ входит и
#: это замер, а не вкус: он называет каталог ДАННЫХ (куда читать/писать артефакты), а
#: не дерево, в котором исполняется дочерний прогон, — приравнять их значило бы
#: объявить названным дерево, о котором никто не спрашивал.
TREE_FLAGS = ("--repo-root", "--root", "--tree", "--repo", "--worktree", "--repo-dir")

#: Сколько кругов засева параметров делать до неподвижной точки. Шаг 1г до починки
#: отстоял от двери на ДВА хопа; предел нужен затем, что взаимная рекурсия иначе
#: крутила бы проход вечно. Исчерпание предела — НЕ «чисто»: это `UNMEASURED`.
TAINT_ROUNDS = 6


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


# ─────────────────────────── поверхность ───────────────────────────

def declared_steps(root: Path) -> Dict[str, List[str]]:
    """Шаги, ОБЪЯВЛЕННЫЕ обязательными: путь `scripts/*.py` → места объявления.

    Поверхность — ОБЪЕДИНЕНИЕ двух мест (:data:`DECLARATION_PLACES`). Любое из двух
    не прочитано ⇒ третий исход: поверхность поменьше ответила бы «чисто» про то,
    чего не видела, и ровно так первая редакция прибора объявила класс пустым.
    """
    by_step: Dict[str, List[str]] = {}
    for place in DECLARATION_PLACES:
        f = root / place
        if not f.is_file():
            raise NotMeasured(f"место объявления шагов {place} не найдено в {root} — "
                              "поверхность НЕПОЛНА, и это отказ, а не меньший класс")
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            raise NotMeasured(f"место объявления шагов {place} не читается: {exc}") from exc
        hits = {f"scripts/{m.group(1)}.py" for m in _STEP_RE.finditer(text)}
        if not hits:
            raise NotMeasured(
                f"в {place} не названо НИ ОДНОГО шага формы scripts/<имя>.py — либо форма "
                "ссылки изменилась, либо файл не тот; пустая поверхность это отказ прибора, "
                "а не пустой класс")
        for h in hits:
            by_step.setdefault(h, []).append(place)
    return {k: by_step[k] for k in sorted(by_step)}


# ─────────────────────────── разбор файла ───────────────────────────

def _names_in(node: ast.AST) -> Set[str]:
    """Все простые имена, встречающиеся в поддереве выражения."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _attrs_in(node: ast.AST) -> Set[str]:
    """Все имена атрибутов в поддереве (`args.repo_root` → `repo_root`)."""
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def declared_tree_dests(tree: ast.AST) -> Set[str]:
    """`dest` тех `add_argument`, чей флаг называет ДЕРЕВО прогона.

    `dest` вычисляется так же, как argparse: первый длинный флаг без `--`, дефисы
    в подчёркивания, либо явный `dest=`.
    """
    dests: Set[str] = set()
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        fn = call.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "add_argument"):
            continue
        flags = [a.value for a in call.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not any(f in TREE_FLAGS for f in flags):
            continue
        explicit = next((kw.value.value for kw in call.keywords
                         if kw.arg == "dest" and isinstance(kw.value, ast.Constant)), None)
        if isinstance(explicit, str):
            dests.add(explicit)
            continue
        long = next((f for f in flags if f.startswith("--")), None)
        if long:
            dests.add(long[2:].replace("-", "_"))
    return dests


@dataclass
class LongRun:
    """Дочерний долгий прогон: где он поднят и чем назван его `cwd=`."""

    func: str                      #: функция, в которой стои́т вызов
    lineno: int
    cwd_expr: Optional[ast.AST]    #: выражение `cwd=`; `None` — ключа нет вовсе


#: Насколько глубоко раскручивать argv, собранный переменными. Два хопа измерены
#: достаточными на живом дереве (`cmd = [...]; subprocess.run(cmd, ...)`); исчерпание
#: глубины печатается в `unresolved`, а не выдаётся за «не долгий прогон».
_ARGV_DEPTH = 3


def _mentions_long_run(node: ast.AST) -> bool:
    """Есть ли в поддереве литерал, называющий долгий прогон."""
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and _LONG_RUN_TOKEN in n.value for n in ast.walk(node))


def _is_long_run(call: ast.Call, argv_sources: Dict[str, List[ast.AST]]) -> bool:
    """Поднимает ли вызов дочерний ДОЛГИЙ прогон по дереву.

    Опознаётся по двум признакам сразу: имя пускателя из stdlib И слово ``pytest``
    в argv. Одного имени пускателя мало — тогда предметом стал бы любой
    ``subprocess.run(["git", ...])``, то есть шум.

    **argv почти никогда не стои́т в самом вызове, и первая редакция этого не видела.**
    Живая форма — ``cmd = [sys.executable, "-m", "pytest", *files, …]`` строкой выше и
    ``subprocess.run(cmd, cwd=root, …)``; литерала ``pytest`` в поддереве вызова при
    этом НЕТ ВОВСЕ, и прибор отвечал ``NO_LONG_RUN`` про ту самую дверь, по которой
    класс найден (второй вакуум подряд, см. докстринг модуля). Поэтому имя argv
    раскручивается по присваиваниям файла на :data:`_ARGV_DEPTH` хопов.
    """
    fn = call.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
    if name not in _SPAWNERS:
        return False
    if _mentions_long_run(call):
        return True
    seen: Set[str] = set()
    frontier = [a for a in call.args[:1]] + [kw.value for kw in call.keywords if kw.arg == "args"]
    for _ in range(_ARGV_DEPTH):
        nxt: List[ast.AST] = []
        for expr in frontier:
            for nm in (n.id for n in ast.walk(expr) if isinstance(n, ast.Name)):
                if nm in seen:
                    continue
                seen.add(nm)
                for src in argv_sources.get(nm, ()):
                    if _mentions_long_run(src):
                        return True
                    nxt.append(src)
        if not nxt:
            break
        frontier = nxt
    return False


def _argv_sources(tree: ast.AST) -> Dict[str, List[ast.AST]]:
    """Имя → выражения, которые ему присваивают (по всему файлу).

    Область намеренно ОДНА на файл, без разделения по функциям: вопрос прибора —
    «что это за argv», и одноимённая переменная в двух функциях даёт ошибку в сторону
    НАХОДКИ (лишний кандидат на долгий прогон), а не в сторону пустого предмета.
    Ошибаться эта мера обязана именно так.
    """
    out: Dict[str, List[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is not None:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                out.setdefault(node.target.id, []).append(node.value)
    return out


def _scope_nodes(scope: ast.AST, tree: ast.AST):
    """Узлы, принадлежащие ИМЕННО этой области, без спуска в вложенные функции.

    Граница существенна, и это измерено контролем B: пока модульная область обходила
    `ast.walk(tree)` целиком, присваивание ВНУТРИ ``main`` пятнало имя в модульной
    области, оттуда пятно уезжало в параметр вызываемой функции, и прибор объявлял
    `NAMEABLE` проводку, которой не было. То есть «половина инъекции» — ровно предмет
    ADR-932 — читалась как целая.
    """
    stack = [scope]
    while stack:
        node = stack.pop()
        for child in ast.iter_child_nodes(node):
            yield child
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            stack.append(child)


def _functions(tree: ast.AST) -> Dict[str, List[ast.AST]]:
    """Функции файла по имени. Одноимённые определения НЕ угадываются.

    Одно имя — список: получатель с двумя определениями есть `AMBIGUOUS`, и засев
    в него не идёт (угадать, какое из двух позовут, нечем).
    """
    out: Dict[str, List[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, []).append(node)
    return out


def _enclosing_func(tree: ast.AST) -> Dict[int, str]:
    """Для каждого узла-вызова — имя объемлющей функции (`<module>` для верхнего уровня)."""
    owner: Dict[int, str] = {}

    def walk(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            nxt = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            owner[id(child)] = nxt if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            walk(child, nxt)

    owner[id(tree)] = "<module>"
    walk(tree, "<module>")
    return owner


@dataclass
class FileVerdict:
    step: str
    verdict: str
    declared_in: List[str] = field(default_factory=list)
    long_runs: List[Tuple[str, int, str]] = field(default_factory=list)
    tree_dests: List[str] = field(default_factory=list)
    reason: str = ""
    unresolved: List[str] = field(default_factory=list)
    rounds: int = 0


def measure_file(path: Path, step: str) -> FileVerdict:
    """Вердикт по ОДНОМУ объявленному шагу."""
    if not path.is_file():
        return FileVerdict(step, "UNMEASURED",
                           reason="шаг назван в объявлении, а файла в дереве нет")
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        return FileVerdict(step, "UNMEASURED", reason=f"файл не читается: {exc}")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return FileVerdict(step, "UNMEASURED", reason=f"файл не разобран: {exc}")

    owner = _enclosing_func(tree)
    argv_sources = _argv_sources(tree)
    runs: List[LongRun] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_long_run(node, argv_sources):
            cwd = next((kw.value for kw in node.keywords if kw.arg == "cwd"), None)
            runs.append(LongRun(owner.get(id(node), "<module>"), node.lineno, cwd))

    dests = declared_tree_dests(tree)
    v = FileVerdict(step, "NO_LONG_RUN", tree_dests=sorted(dests))
    if not runs:
        return v

    funcs = _functions(tree)
    tainted, unresolved, rounds, exhausted = _propagate(tree, funcs, dests, owner)
    v.rounds, v.unresolved = rounds, unresolved
    v.long_runs = [(r.func, r.lineno,
                    "cwd=" + (ast.unparse(r.cwd_expr) if r.cwd_expr is not None else "<НЕТ КЛЮЧА cwd>"))
                   for r in runs]

    reached = False
    for r in runs:
        if r.cwd_expr is None:
            continue
        scope = tainted.get(r.func, set())
        if _names_in(r.cwd_expr) & scope or _attrs_in(r.cwd_expr) & dests:
            reached = True
            break

    if reached:
        v.verdict = "NAMEABLE"
    elif exhausted:
        v.verdict = "UNMEASURED"
        v.reason = (f"засев параметров исчерпал предел {TAINT_ROUNDS} кругов, не достигнув "
                    "неподвижной точки — доехал ли вход до cwd=, НЕ ИЗМЕРЕНО")
    elif dests:
        v.verdict = "HALF"
        v.reason = (f"вход ОБЪЯВЛЕН ({', '.join(sorted(dests))}), но до cwd= дочернего "
                    "прогона не доехал — половина инъекции (форма ADR-932)")
    else:
        v.verdict = "UNNAMEABLE"
        v.reason = ("поднимает дочерний долгий прогон, а входа, называющего дерево, "
                    f"нет вовсе (ни одного из {', '.join(TREE_FLAGS)})")
    return v


def _propagate(tree: ast.AST, funcs: Dict[str, List[ast.AST]], dests: Set[str],
               owner: Dict[int, str]) -> Tuple[Dict[str, Set[str]], List[str], int, bool]:
    """Засев от `args.<флаг>` по присваиваниям и В ПАРАМЕТРЫ — до неподвижной точки.

    Возвращает (запятнанные имена по функциям, непрослеженные передачи, кругов,
    исчерпан ли предел). Исчерпание предела — третий исход, а не «чисто».
    """
    tainted: Dict[str, Set[str]] = {}
    unresolved: List[str] = []
    scopes: List[Tuple[str, ast.AST]] = [("<module>", tree)]
    scopes += [(name, node) for name, nodes in funcs.items() for node in nodes]

    def is_tainted(expr: ast.AST, scope: str) -> bool:
        return bool(_attrs_in(expr) & dests) or bool(_names_in(expr) & tainted.get(scope, set()))

    rounds = 0
    for rounds in range(1, TAINT_ROUNDS + 1):
        changed = False
        for scope, node in scopes:
            for stmt in _scope_nodes(node, tree):
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                    if not is_tainted(stmt.value, scope):
                        continue
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for t in targets:
                        for nm in ast.walk(t):
                            if isinstance(nm, ast.Name):
                                if nm.id not in tainted.setdefault(scope, set()):
                                    tainted[scope].add(nm.id)
                                    changed = True
                elif isinstance(stmt, ast.Call):
                    fname = (stmt.func.attr if isinstance(stmt.func, ast.Attribute)
                             else getattr(stmt.func, "id", None))
                    hot_pos = [i for i, a in enumerate(stmt.args) if is_tainted(a, scope)]
                    hot_kw = [kw.arg for kw in stmt.keywords
                              if kw.arg and is_tainted(kw.value, scope)]
                    if not hot_pos and not hot_kw:
                        continue
                    if fname is None or fname not in funcs:
                        unresolved.append(f"OUTSIDE {fname}@{getattr(stmt, 'lineno', 0)}")
                        continue
                    if len(funcs[fname]) > 1:
                        unresolved.append(f"AMBIGUOUS {fname}@{stmt.lineno}")
                        continue
                    callee = funcs[fname][0]
                    params = [a.arg for a in callee.args.posonlyargs + callee.args.args]
                    # Точечный вызов сдвигает позиционные на self/cls.
                    shift = 1 if (isinstance(stmt.func, ast.Attribute) and params
                                  and params[0] in ("self", "cls")) else 0
                    seeds: Set[str] = set()
                    for i in hot_pos:
                        j = i + shift
                        if j < len(params):
                            seeds.add(params[j])
                        elif callee.args.vararg is not None:
                            unresolved.append(f"VARIADIC {fname}@{stmt.lineno}")
                        else:
                            unresolved.append(f"ARITY {fname}@{stmt.lineno}")
                    for kw in hot_kw:
                        if kw in params or kw in [a.arg for a in callee.args.kwonlyargs]:
                            seeds.add(kw)
                        elif callee.args.kwarg is not None:
                            unresolved.append(f"VARIADIC {fname}@{stmt.lineno}")
                        else:
                            unresolved.append(f"ARITY {fname}@{stmt.lineno}")
                    for s in seeds:
                        if s not in tainted.setdefault(fname, set()):
                            tainted[fname].add(s)
                            changed = True
        if not changed:
            return tainted, sorted(set(unresolved)), rounds, False
    return tainted, sorted(set(unresolved)), rounds, True


# ─────────────────────────── перепись ───────────────────────────

@dataclass
class Census:
    root: str
    steps: List[FileVerdict]

    @property
    def subject(self) -> List[FileVerdict]:
        return [s for s in self.steps if s.verdict in ("UNNAMEABLE", "HALF")]

    @property
    def unmeasured(self) -> List[FileVerdict]:
        return [s for s in self.steps if s.verdict == "UNMEASURED"]

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for s in self.steps:
            out[s.verdict] = out.get(s.verdict, 0) + 1
        return out


def measure(root: Path) -> Census:
    """Перепись по ВСЕМ объявленным шагам дерева `root`."""
    out: List[FileVerdict] = []
    for step, places in declared_steps(root).items():
        v = measure_file(root / step, step)
        v.declared_in = places
        out.append(v)
    return Census(str(root), out)


def render(c: Census) -> str:
    lines = [f"Перепись «обязательный шаг не умеет назвать дерево прогона» — {c.root}",
             f"  объявленных шагов: {len(c.steps)} · {c.counts()}"]
    for s in c.steps:
        if s.verdict == "NO_LONG_RUN":
            continue
        lines.append(f"  [{s.verdict}] {s.step}  (объявлен: {', '.join(s.declared_in)})")
        for func, lineno, cwd in s.long_runs:
            lines.append(f"      прогон в {func}:{lineno} — {cwd}")
        if s.tree_dests:
            lines.append(f"      объявленный вход: {', '.join(s.tree_dests)}")
        if s.reason:
            lines.append(f"      {s.reason}")
        if s.unresolved:
            lines.append(f"      непрослежено: {', '.join(s.unresolved[:6])}")
    if c.unmeasured:
        lines.append(f"  НЕ ИЗМЕРЕНО: {len(c.unmeasured)} шаг(ов) — "
                     + "; ".join(f"{s.step}: {s.reason}" for s in c.unmeasured[:5]))
    if c.subject:
        lines.append(f"  ПРЕДМЕТ КЛАССА: {len(c.subject)} — "
                     + ", ".join(s.step for s in c.subject))
    else:
        lines.append("  ✅ предмет класса ПУСТ: каждый шаг с долгим прогоном умеет "
                     "назвать дерево")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, КОТОРОЕ меряется (не названо — дерево прибора, и оно "
                         "печатается; названное нечитаемое дерево — ОТКАЗ код 2)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.repo_root is None:
        root, named = ROOT, False
    else:
        root = Path(args.repo_root).expanduser()
        if not root.is_dir():
            print(f"НЕ ИЗМЕРЕНО — --repo-root {root} не каталог")
            return 2
        root, named = root.resolve(), True
    try:
        c = measure(root)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    if args.json:
        print(json.dumps({"root": c.root, "counts": c.counts(),
                          "steps": [{"step": s.step, "verdict": s.verdict,
                                     "declared_in": s.declared_in,
                                     "reason": s.reason, "tree_dests": s.tree_dests,
                                     "long_runs": s.long_runs,
                                     "unresolved": s.unresolved, "rounds": s.rounds}
                                    for s in c.steps]}, ensure_ascii=False, indent=1))
    else:
        print(f"дерево переписи: {root} "
              f"({'НАЗВАНО входом --repo-root' if named else 'умолчание — дерево прибора'})")
        print(render(c))
    if c.unmeasured:
        return 2
    return 1 if c.subject else 0


if __name__ == "__main__":
    raise SystemExit(main())
