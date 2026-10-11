"""Отображение СЛАБОЙ оси: ВХОД или СВОИ ЧАСЫ — заказ **G113 п. 3** (ADR-539).

Дословно заказ:

    **Слабая ось не разобрана до конца.** Измерено 29 имён, у которых значение
    есть чтение имени из ``CLOCK_FIELDS``, и у ОДНОГО проверено поимённо, что
    отображение — ВХОД. Остальные 28 не проверял никто, и доля «вход против
    часов» среди них неизвестна. Пока она неизвестна, слабая ось не вправе ни
    поддерживать, ни опровергать ни одно решение об имени.

Слабая ось соседа (``identity_field_kind.clock_named_read``) утверждает ровно
одно: значение поля есть чтение имени из :data:`CLOCK_FIELDS` у какого-то
ОТОБРАЖЕНИЯ. Чьё это отображение, она не спрашивает, и в этом вся её слабость:
``record.get("generated_at")`` у производителя, который запись ПЕРЕПИСЫВАЕТ, и
``receipt["generated_at"]`` у производителя, который сам её ПОСТАВИЛ, — для оси
одно и то же, а для решения об имени противоположное.

Этот прибор задаёт отображению один вопрос — **откуда оно взялось** — и
отвечает тремя исходами, а не двумя.

Посылка заказа ПЕРЕМЕРЕНА, и она верна
------------------------------------------------------------------------------
«29» — это число РАЗНЫХ ИМЁН поля в населении слабой оси по всему дереву на
день ADR-539. Проверено прогоном кода ADR-539 на дереве ADR-539 (коммит
``099e9d551``): **197 площадок, 29 имён**. На 11.10 то же измерение даёт
**207 площадок, 33 имени** — дерево выросло, класс никуда не делся. Число в
заказе есть замер с датой, а не константа, и перепечатывать его вместо прибора
запрещено (``.claude/rules/site-numbers.md``, тот же урок).

Три исхода, и третий — самостоятельный (инв. #17)
------------------------------------------------------------------------------
:data:`INPUT_MAPPING`
    Отображение пришло В этот производитель ИЗВНЕ, и это утверждение о КОДЕ:
    параметр объемлющей функции · элемент обхода такого параметра · результат
    ``json.load``/``json.loads`` · ЧАСТЬ любого из них.
:data:`OWN_CLOCK_MAPPING`
    Отображение собрано ЗДЕСЬ литералом словаря, и искомое имя в нём поставлено
    СТЕННОЙ ДВЕРЬЮ самого модуля. Правило «что есть стенная дверь» не
    переписывается — оно берётся у соседа (``identity_field_kind.derivation``).
:data:`UNMEASURED`
    Всё остальное, и **с названной причиной**. «Не разобрали происхождение» и
    «происхождение — вход» суть разные ответы; склеить их значило бы повторить
    урок ``pyflakes`` (fail-OPEN тише красного и потому опаснее).

Что ответ ``input_mapping`` НЕ утверждает
------------------------------------------------------------------------------
Он утверждает «ЭТОТ модуль отметку не ставил», а НЕ «значение не есть часы».
Зовущий вполне мог поставить её своими часами строкой выше — и тогда момент
всё равно момент производства, только чужого. Через границу вызова
ВВЕЗЁННОЙ функции мера не ходит ВООБЩЕ, и это названная односторонность, а не
оговорка: она смещает ответ в сторону «вход», и поэтому доля
:data:`OWN_CLOCK_MAPPING` есть **нижняя граница**, а доля
:data:`INPUT_MAPPING` — верхняя.

``own_clock_mapping`` НЕ транзитивен через чтение ЧАСТИ
------------------------------------------------------------------------------
Часть входа есть вход — это следует из «целое пришло извне». Обратное неверно:
``receipt["meta"]["generated_at"]`` читает имя у ВЛОЖЕННОГО отображения, а
литерал, который мера открыла, — внешний. Объявить такое «своими часами»
значило бы повторить «контейнер не есть привязка»
(``.claude/rules/deployment.md``), и поэтому чтение части от собранного здесь
документа даёт :data:`UNMEASURED` с названной причиной, а не вердикт.

Население берётся У СОСЕДА, а не вторым поиском
------------------------------------------------------------------------------
Площадки перечисляет ``identity_field_kind.field_assignments`` + новая
``clock_named_read_site`` — то же правило, что у самой оси, в единственном
экземпляре. Второй поиск того же предмета расходится с первым молча (урок
ADR-682/#820), а расхождение здесь означало бы, что прибор мерит НЕ ту ось,
про которую докладывает.

Коды возврата: **0** — находки нет · **1** — находка (ось чаще читает чужое
отображение, чем своё) · **2** — НЕ ИЗМЕРЕНО с названной причиной.

ADVISORY: прибор только ЧИТАЕТ исходники. ``_IDENTITY_FIELDS``, координаты
находок, RiskPolicy v1.0, стоп-кран, аллокатор, живой трек, ``landing/`` и флот
не трогаются. LLM здесь запрещён — это измерение, а не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import collections
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple, Union

from spa_core.monitoring import identity_field_kind as ifk
from spa_core.utils.atomic import atomic_save

SCHEMA = "weak_axis_mapping_origin.v1"
ORDER = "G113 п. 3 (ADR-539)"

#: Имя артефакта — читает шаг 0-офис поимённой ветвью.
ARTIFACT = "weak_axis_mapping_origin.json"

#: Три исхода. Четвёртого нет, и «не измерено» нулём не подменяется.
INPUT_MAPPING = "input_mapping"
OWN_CLOCK_MAPPING = "own_clock_mapping"
UNMEASURED = "unmeasured"
VERDICTS = (INPUT_MAPPING, OWN_CLOCK_MAPPING, UNMEASURED)

#: Предел спуска. Не «на всякий случай»: цикл привязок (``doc = doc or {}``)
#: ловится множеством ``seen``, а предел держит глубину РАЗНЫХ имён.
MAX_DEPTH = 10

#: Случаи, которые ADR-539 проверил ПОИМЁННО — и которые этот прибор обязан
#: перемерять КАЖДЫЙ прогон, а не пересказывать. Исчезни площадка из дерева —
#: сцена скажет это вслух третьим исходом, а не промолчит.
NAMED_CASES = (
    {"module": "spa_core/export_data.py",
     "field": "date",
     "claim": "ADR-539: `rec` — точка СИНТЕТИЧЕСКОЙ ИСТОРИИ, то есть "
              "календарная дата наблюдения, а не момент производства"},
    {"module": "spa_core/monitoring/decision_record_run_identity.py",
     "field": "record_generated_at",
     "claim": "ADR-503 отверг это имя как «производитель копирует свой "
              "generated_at»; ADR-539 прочёл код и сказал: производитель "
              "отметку ПЕРЕПИСЫВАЕТ, она пришла со ВХОДНОЙ записью"},
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── привязки области: имя → чем оно связано ──────────────────────────────────

#: Как имя связано. ``opaque`` — связано, но происхождение значения в этой форме
#: не читается (распаковка непрозрачной целью, обработчик исключения): это
#: ТРЕТИЙ исход, а не «не связано», и путать их нельзя — «имени не связал никто»
#: лечится взглядом на модуль, а «связано непрозрачно» не лечится вовсе.
BIND_ASSIGN = "assign"
BIND_ELEMENT = "element"
BIND_UNPACK = "unpack"
BIND_OPAQUE = "opaque"


def bindings(scope_node: ast.AST) -> Dict[str, List[Tuple[str, Optional[ast.AST], int]]]:
    """``имя → [(как связано, выражение, место в кортеже)]`` для ОДНОЙ области.

    Спуска во вложенные функции нет — у них своя область
    (``identity_field_kind._own_body``, одна копия правила на обе меры).
    Привязок у имени бывает несколько, и это НЕ сворачивается в одну: «какая
    из двух дошла» мера решить не может и обязана сказать это третьим исходом.
    """
    out: Dict[str, List[Tuple[str, Optional[ast.AST], int]]] = collections.defaultdict(list)

    def opaque(target: ast.AST) -> None:
        for name in ifk._targets(target):
            out[name].append((BIND_OPAQUE, None, 0))

    def bind_target(target: ast.AST, value: Optional[ast.AST], kind: str) -> None:
        """Цель привязки: имя — прозрачно, кортеж — по месту, прочее — непрозрачно."""
        if isinstance(target, ast.Name):
            out[target.id].append((kind, value, 0))
        elif isinstance(target, (ast.Tuple, ast.List)) and value is not None:
            for index, element in enumerate(target.elts):
                if isinstance(element, ast.Name):
                    out[element.id].append((BIND_UNPACK, value, index))
                else:
                    opaque(element)
        else:
            opaque(target)

    for node in ifk._own_body(scope_node):
        if isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                bind_target(target, node.value, BIND_ASSIGN)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind_target(node.target, node.value, BIND_ASSIGN)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind_target(node.target, node.iter, BIND_ELEMENT)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bind_target(item.optional_vars, item.context_expr, BIND_ASSIGN)
        elif isinstance(node, ifk.comprehension_types()):
            for gen in node.generators:
                bind_target(gen.target, gen.iter, BIND_ELEMENT)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out[node.name].append((BIND_OPAQUE, None, 0))
    return dict(out)


def parameters(scope_node: ast.AST) -> FrozenSet[str]:
    """Параметры области. Модуль параметров не имеет — пустое множество."""
    args = getattr(scope_node, "args", None)
    if not isinstance(args, ast.arguments):
        return frozenset()
    names: Set[str] = set()
    for group in (args.posonlyargs, args.args, args.kwonlyargs):
        names.update(a.arg for a in group)
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            names.add(extra.arg)
    return frozenset(names)


def outside_parse(node: ast.AST) -> Optional[str]:
    """Это РАЗБОР текста извне (``json.load``/``json.loads``)? Запись или ``None``.

    Названо поимённо по той же причине, что ``_DOOR_ATTRS`` у соседа: признак
    «похоже на чтение» утащил бы и конвертеры, которые ничего извне не берут.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    root = node.func.value
    if isinstance(root, ast.Name) and root.id == "json" and node.func.attr in ("load", "loads"):
        return f"json.{node.func.attr}()"
    return None


def _is_guard_tail(node: ast.AST) -> bool:
    """``{}`` в ``x or {}`` — защитный хвост, а не отображение-кандидат."""
    return isinstance(node, (ast.Dict, ast.List)) and not getattr(node, "keys", getattr(node, "elts", None))


class ModuleOrigins:
    """Происхождение отображений ОДНОГО модуля.

    Состояние модуля (функции по именам, что ввезено, таблица стенных привязок
    соседа) собирается один раз: иначе каждая площадка пересобирала бы его, и
    замер на дереве в 2449 файлов стал бы неподъёмным.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.funcs: Dict[str, List[ast.AST]] = collections.defaultdict(list)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name].append(node)
        self.imported: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    self.imported.add((alias.asname or alias.name).split(".")[0])
        # Правило «что есть стенная дверь» — соседское, в единственном экземпляре.
        self.clock_scopes = ifk._scope_table(tree, ifk.derivation, ifk.clock_wrappers(tree))
        self._scope_cache: Dict[int, Tuple[FrozenSet[str], Dict[str, List[Tuple[str, Optional[ast.AST], int]]]]] = {}

    def _scope(self, scope_node: ast.AST):
        got = self._scope_cache.get(id(scope_node))
        if got is None:
            got = (parameters(scope_node), bindings(scope_node))
            self._scope_cache[id(scope_node)] = got
        return got

    def _clock_scope(self, scope_node: ast.AST) -> "ifk._Scope":
        return self.clock_scopes.get(id(scope_node), self.clock_scopes[id(self.tree)])

    # ── сам вопрос ───────────────────────────────────────────────────────────

    def origin(self, expr: Optional[ast.AST], key: str, scope_node: ast.AST, *,
               seen: FrozenSet[str] = frozenset(), depth: int = 0,
               index: Optional[int] = None) -> Tuple[str, str]:
        """``(вердикт, причина)`` для ОТОБРАЖЕНИЯ ``expr``, у которого читают ``key``.

        ``index`` — место распаковки: ``history, why = read()`` спрашивает у
        возврата не значение, а его НУЛЕВОЙ элемент. Без этого параметра
        распаковка была бы непрозрачна целиком, а это самая частая форма
        чтения файла в этом дереве.
        """
        if expr is None:
            return UNMEASURED, "отображения нет"
        if depth > MAX_DEPTH:
            return UNMEASURED, f"спуск глубже {MAX_DEPTH} шагов"

        parsed = outside_parse(expr)
        if parsed:
            return INPUT_MAPPING, f"разобрано из текста извне: {parsed}"

        if isinstance(expr, ast.Dict):
            if index is not None:
                return UNMEASURED, "на месте распаковки стои́т словарь, а не кортеж"
            return self._own_literal(expr, key, scope_node)

        if isinstance(expr, (ast.Tuple, ast.List)):
            if index is None:
                return UNMEASURED, f"отображением оказался {type(expr).__name__.lower()}"
            if index < len(expr.elts):
                return self.origin(expr.elts[index], key, scope_node,
                                   seen=seen, depth=depth + 1)
            return UNMEASURED, "кортеж короче места распаковки"

        if isinstance(expr, (ast.BoolOp, ast.IfExp)):
            return self._fork(expr, key, scope_node, seen=seen, depth=depth, index=index)

        if isinstance(expr, ast.Call):
            return self._call(expr, key, scope_node, seen=seen, depth=depth, index=index)

        if isinstance(expr, ast.Subscript):
            return self._part(expr.value, key, scope_node, "[…]", seen=seen, depth=depth)

        if isinstance(expr, ast.Attribute):
            return self._part(expr.value, key, scope_node, ".атрибут",
                              seen=seen, depth=depth)

        if isinstance(expr, ast.Name):
            return self._name(expr.id, key, scope_node, seen=seen, depth=depth)

        if isinstance(expr, ast.Await):
            return UNMEASURED, "значение дожидается сопрограммы"
        return UNMEASURED, f"не разобрано ({type(expr).__name__})"

    def _own_literal(self, expr: ast.Dict, key: str,
                     scope_node: ast.AST) -> Tuple[str, str]:
        """Литерал словаря НА МЕСТЕ: искомое имя в нём — и чем оно поставлено."""
        for node_key, value in zip(expr.keys, expr.values):
            if isinstance(node_key, ast.Constant) and node_key.value == key:
                how = ifk.derivation(value, self._clock_scope(scope_node))
                if how:
                    return OWN_CLOCK_MAPPING, (
                        f"отображение собрано ЗДЕСЬ, и `{key}` поставлено своей "
                        f"стенной дверью ({how})")
                return UNMEASURED, (
                    f"отображение собрано здесь, но происхождение самого `{key}` "
                    f"не разобрано")
        return UNMEASURED, f"отображение собрано здесь, имени `{key}` в нём нет"

    def _fork(self, expr: Union[ast.BoolOp, ast.IfExp], key: str,
              scope_node: ast.AST, *, seen: FrozenSet[str], depth: int,
              index: Optional[int]) -> Tuple[str, str]:
        """Развилка (``a or b``, ``a if t else b``): значением станет ОДИН операнд.

        Защитный хвост ``or {}`` операндом-отображением не является: он несёт
        не значение, а отказ от падения. Операнды дали РАЗНЫЕ ответы ⇒ третий
        исход: выбрать «тот, который удобнее» значило бы выдумать поток
        управления, за которым мера не следит.
        """
        kids = (list(expr.values) if isinstance(expr, ast.BoolOp)
                else [expr.body, expr.orelse])
        answers: Dict[str, str] = {}
        for kid in kids:
            if _is_guard_tail(kid):
                continue
            verdict, why = self.origin(kid, key, scope_node, seen=seen,
                                       depth=depth + 1, index=index)
            answers.setdefault(verdict, why)
        if len(answers) == 1:
            verdict = next(iter(answers))
            return verdict, answers[verdict]
        if not answers:
            return UNMEASURED, "у развилки не осталось ни одного операнда-отображения"
        return UNMEASURED, ("операнды развилки дают РАЗНЫЕ ответы: "
                            + "/".join(sorted(answers)))

    def _call(self, expr: ast.Call, key: str, scope_node: ast.AST, *,
              seen: FrozenSet[str], depth: int,
              index: Optional[int]) -> Tuple[str, str]:
        """Вызов: чтение ЧАСТИ · возврат функции ЭТОГО модуля · граница."""
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr in ("get", "pop") and expr.args:
            return self._part(func.value, key, scope_node, f".{func.attr}()",
                              seen=seen, depth=depth)
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name is None:
            return UNMEASURED, "вызов без разрешимого имени"
        if isinstance(func, ast.Name) and name in self.imported:
            return UNMEASURED, (f"`{name}()` ввезён из другого модуля — "
                                f"через импорт мера не ходит")
        defs = self.funcs.get(name) or []
        if len(defs) > 1:
            return UNMEASURED, (f"`{name}` определено {len(defs)} раз в модуле — "
                                f"какое из определений позвано, мера не знает")
        if not defs:
            return UNMEASURED, f"`{name}()` — за границей модуля"
        if name in seen:
            return UNMEASURED, f"`{name}()` разрешается через себя"
        returns = ifk._returns(defs[0])
        if not returns:
            return UNMEASURED, f"`{name}()` не возвращает значения"
        answers: Dict[str, str] = {}
        for ret in returns:
            verdict, why = self.origin(ret, key, defs[0], seen=seen | {name},
                                       depth=depth + 1, index=index)
            answers.setdefault(verdict, why)
        if len(answers) == 1:
            verdict = next(iter(answers))
            return verdict, f"`{name}()` → {answers[verdict]}"
        return UNMEASURED, (f"возвраты `{name}()` дают РАЗНЫЕ ответы: "
                            + "/".join(sorted(answers)))

    def _part(self, container: ast.AST, key: str, scope_node: ast.AST, how: str, *,
              seen: FrozenSet[str], depth: int) -> Tuple[str, str]:
        """Чтение ЧАСТИ отображения. ``input`` транзитивен, ``own_clock`` — НЕТ.

        Часть входа есть вход: целое пришло извне, значит и всё в нём. Обратное
        ложно — литерал, который мера открыла, лежит СНАРУЖИ прочитанной части,
        и искомое имя в нём не то же самое имя. Объявить это «своими часами»
        значило бы повторить «контейнер не есть привязка».
        """
        verdict, why = self.origin(container, key, scope_node,
                                   seen=seen, depth=depth + 1)
        if verdict == INPUT_MAPPING:
            return INPUT_MAPPING, f"ЧАСТЬ {how} от: {why}"
        if verdict == OWN_CLOCK_MAPPING:
            return UNMEASURED, (
                f"ЧАСТЬ {how} собранного ЗДЕСЬ документа — искомое имя лежит во "
                f"ВЛОЖЕННОМ отображении, а его мера не открывала")
        return UNMEASURED, f"ЧАСТЬ {how} от: {why}"

    def _name(self, name: str, key: str, scope_node: ast.AST, *,
              seen: FrozenSet[str], depth: int) -> Tuple[str, str]:
        """Имя: параметр ⇒ вход; одна привязка ⇒ спуск; иначе третий исход."""
        if name in seen:
            return UNMEASURED, f"`{name}` разрешается через себя"
        params, binds = self._scope(scope_node)
        own = binds.get(name) or []
        if name in params:
            if own:
                return UNMEASURED, (f"`{name}` и параметр, и переприсвоено в теле "
                                    f"({len(own)} привязк(а/и)) — какая дошла, "
                                    f"мера не знает")
            return INPUT_MAPPING, f"`{name}` — параметр объемлющей функции"
        if not own:
            return UNMEASURED, (f"`{name}` в этой области не связано — глобальное, "
                                f"ввезённое или замыкание объемлющей функции")
        if len(own) > 1:
            return UNMEASURED, (f"`{name}` связано {len(own)} раз — какая привязка "
                                f"дошла до чтения, мера не знает")
        kind, rhs, index = own[0]
        if kind == BIND_OPAQUE or rhs is None:
            return UNMEASURED, f"`{name}` связано непрозрачно ({kind})"
        verdict, why = self.origin(rhs, key, scope_node, seen=seen | {name},
                                   depth=depth + 1,
                                   index=index if kind == BIND_UNPACK else None)
        tag = {BIND_ELEMENT: "элемент обхода ", BIND_UNPACK: "место распаковки "}.get(kind, "")
        return verdict, f"{tag}`{name}` ← {why}"


# ── перепись населения ───────────────────────────────────────────────────────

def module_sites(source: str, module: str) -> Tuple[List[dict], str]:
    """Площадки слабой оси ОДНОГО модуля с вердиктом происхождения.

    Вторым — причина, если модуль не разобран: «не прочитан» и «часов нет» суть
    разные ответы, и прибор их не склеивает.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return [], f"не разобрано: {type(exc).__name__}"
    origins = ModuleOrigins(tree)
    out: List[dict] = []
    for field, value, line, scope_node in ifk.field_assignments(tree):
        site = ifk.clock_named_read_site(value)
        if site is None:
            continue
        mapping, key, written = site
        # Сильная ось соседа перебивает слабую у него же, и здесь перебивает
        # так же: площадка, где значение производится своими часами НАПРЯМУЮ,
        # населением СЛАБОЙ оси не является — иначе прибор мерил бы не ту ось,
        # про которую докладывает.
        if ifk.derivation(value, origins._clock_scope(scope_node)):
            continue
        verdict, why = origins.origin(mapping, key, scope_node)
        out.append({"module": module, "line": line, "field": field,
                    "clock_name": key, "written_as": written,
                    "verdict": verdict, "why": why,
                    "scope": getattr(scope_node, "name", "<модуль>")})
    return out, ""


def census(tree_root: Path,
           roots: Sequence[str] = ifk.DEFAULT_ROOTS) -> Tuple[List[dict], Dict[str, str], int]:
    """``(площадки, файлы НЕ измерены, файлов разобрано)`` по дереву.

    Каталоги — те же, что у соседа (``identity_field_kind.DEFAULT_ROOTS``), и
    тесты исключены по той же причине: фикстура пишет часы в поля сознательно,
    и считать её производителем значило бы мерить население СЦЕН.
    """
    sites: List[dict] = []
    unmeasured_files: Dict[str, str] = {}
    files_parsed = 0
    for root in roots:
        base = Path(tree_root) / root
        if not base.is_dir():
            unmeasured_files[root] = "каталога нет в дереве"
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(tree_root))
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured_files[rel] = f"не прочитано: {type(exc).__name__}"
                continue
            rows, why = module_sites(source, rel)
            if why:
                unmeasured_files[rel] = why
                continue
            files_parsed += 1
            sites.extend(rows)
    return sites, unmeasured_files, files_parsed


def _named_cases(sites: Sequence[dict]) -> List[dict]:
    """Случаи ADR-539 — перемерены, а не пересказаны. Нет площадки ⇒ сказать вслух."""
    by_key = {(s["module"], s["field"]): s for s in sites}
    out: List[dict] = []
    for case in NAMED_CASES:
        row = by_key.get((case["module"], case["field"]))
        out.append({
            **case,
            "verdict": row["verdict"] if row else UNMEASURED,
            "why": row["why"] if row else ("площадки нет в населении — имя, "
                                           "модуль или сама ось изменились"),
            "line": row["line"] if row else None,
            "present": bool(row),
        })
    return out


def measure(tree_root: Path, *, now: Optional[datetime] = None,
            roots: Sequence[str] = ifk.DEFAULT_ROOTS) -> Dict[str, Any]:
    """Доля «вход против своих часов» в населении слабой оси — ответ заказа."""
    moment = now or _utcnow()
    sites, unmeasured_files, files_parsed = census(Path(tree_root), roots)
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "order": ORDER,
        "generated_at": _iso(moment),
        "advisory": True,
        "files_parsed": files_parsed,
        "files_unmeasured": unmeasured_files,
    }
    if not files_parsed:
        doc.update({"measured": False, "status": "НЕ ИЗМЕРЕНО",
                    "reason": "ни один файл дерева не разобран — "
                              + (", ".join(sorted(unmeasured_files)) or "каталогов нет")})
        return doc
    if not sites:
        # Пустое население НЕ выдаётся за «доля ноль»: доли без населения нет.
        doc.update({"measured": False, "status": "НЕ ИЗМЕРЕНО",
                    "reason": f"население слабой оси пусто при {files_parsed} "
                              f"разобранных файлах — мерить долю не на чем"})
        return doc

    tally = collections.Counter(s["verdict"] for s in sites)
    total = len(sites)
    resolved = tally[INPUT_MAPPING] + tally[OWN_CLOCK_MAPPING]
    identity_sites = [s for s in sites if s["field"] in set(ifk._IDENTITY_FIELDS)]
    identity_tally = collections.Counter(s["verdict"] for s in identity_sites)
    causes = collections.Counter(
        s["why"].split("←")[-1].split("→")[-1].strip()[:90]
        for s in sites if s["verdict"] == UNMEASURED)

    doc.update({
        "measured": True,
        "population": {
            "sites": total,
            "field_names": len(sorted({s["field"] for s in sites})),
            "modules": len(sorted({s["module"] for s in sites})),
        },
        "tally": {v: tally[v] for v in VERDICTS},
        "share_pct": {v: round(100.0 * tally[v] / total, 1) for v in VERDICTS},
        # Доля СРЕДИ РАЗРЕШЁННЫХ печатается отдельно и не подменяет долю среди
        # всех: «не измерено» из знаменателя не вычёркивается молча.
        "share_of_resolved_pct": (
            {v: round(100.0 * tally[v] / resolved, 1)
             for v in (INPUT_MAPPING, OWN_CLOCK_MAPPING)} if resolved else None),
        "resolved": resolved,
        "admitted_names": {
            "sites": len(identity_sites),
            "tally": {v: identity_tally[v] for v in VERDICTS},
            "rows": [{k: s[k] for k in ("module", "line", "field", "verdict", "why")}
                     for s in identity_sites],
        },
        "named_cases": _named_cases(sites),
        "unmeasured_causes": [{"cause": c, "sites": n}
                              for c, n in causes.most_common(20)],
        "own_clock_sites": [{k: s[k] for k in ("module", "line", "field",
                                               "clock_name", "why")}
                            for s in sites if s["verdict"] == OWN_CLOCK_MAPPING],
        "input_sites_sample": [{k: s[k] for k in ("module", "line", "field", "why")}
                               for s in sites
                               if s["verdict"] == INPUT_MAPPING][:12],
        "one_sidedness": [
            "`input_mapping` утверждает «ЭТОТ модуль отметку не ставил», а не "
            "«значение не есть часы»: зовущий мог поставить её своими часами",
            "через импорт мера не ходит ВООБЩЕ ⇒ доля own_clock_mapping есть "
            "НИЖНЯЯ граница, доля input_mapping — верхняя",
            "`own_clock_mapping` не транзитивен через чтение ЧАСТИ: имя "
            "вложенного отображения мера не открывала",
        ],
    })
    doc["verdict"] = _verdict(doc)
    doc["status"] = "НАХОДКА" if doc["verdict"]["finding"] else "чисто"
    return doc


def _verdict(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Вердикт ВЫЧИСЛЕН из замера, а не объявлен строкой.

    Порога здесь нет намеренно (заказ: «Пороги не назначать: сначала замер,
    потом правило»). Сравниваются два ИЗМЕРЕННЫХ числа одного населения:
    чаще ось читает чужое отображение или своё.
    """
    tally = doc["tally"]
    reads_foreign_more = tally[INPUT_MAPPING] > tally[OWN_CLOCK_MAPPING]
    admitted = doc["admitted_names"]["tally"]
    admitted_resolved = admitted[INPUT_MAPPING] + admitted[OWN_CLOCK_MAPPING]
    named_resolved = [c for c in doc["named_cases"] if c["verdict"] != UNMEASURED]
    why: List[str] = []
    if reads_foreign_more:
        why.append(
            f"ось читает ЧУЖОЕ отображение {tally[INPUT_MAPPING]} раз против "
            f"{tally[OWN_CLOCK_MAPPING]} своих — то, ради чего она названа, "
            f"есть меньшая часть того, о чём она говорит")
    if not admitted_resolved:
        why.append(
            f"про ПРИНЯТЫЕ имена (_IDENTITY_FIELDS) ось не даёт НИ ОДНОГО "
            f"измеренного свидетельства: площадок {doc['admitted_names']['sites']}, "
            f"разрешено 0")
    if not named_resolved:
        why.append(
            "ни один из случаев, проверенных ADR-539 ВРУЧНУЮ, машинным "
            "признаком не достаётся — претензия человека остаётся прозой")
    return {
        "finding": bool(why),
        "why": "; ".join(why),
        "axis_reads_foreign_mapping_more_often": reads_foreign_more,
        "axis_may_support_a_name_decision": False,
        "why_it_may_not": (
            "доля «вход против часов» ИЗМЕРЕНА, и она против оси: решение об "
            "имени требует ответа «чей предмет этот момент», а ось отвечает "
            "«кто-то когда-то положил в отображение имя из CLOCK_FIELDS». "
            "Запрет ADR-539 остаётся в силе — но теперь он стои́т на числе, а "
            "не на одном примере"),
        "admitted_names_resolved": admitted_resolved,
        "named_cases_resolved": len(named_resolved),
    }


# ── отрисовка ────────────────────────────────────────────────────────────────

def render(doc: Dict[str, Any]) -> List[str]:
    lines = [f"[ОТОБРАЖЕНИЕ СЛАБОЙ ОСИ: ВХОД ИЛИ СВОИ ЧАСЫ] заказ {doc.get('order')} · "
             f"{doc.get('generated_at')}"]
    if not doc.get("measured"):
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return lines
    pop = doc["population"]
    lines.append(f"население слабой оси: площадок {pop['sites']} · имён поля "
                 f"{pop['field_names']} · модулей {pop['modules']} · файлов "
                 f"разобрано {doc['files_parsed']} · не измерено файлов "
                 f"{len(doc['files_unmeasured'])}")
    tally, share = doc["tally"], doc["share_pct"]
    lines.append(f"[ДОЛЯ] вход {tally[INPUT_MAPPING]} ({share[INPUT_MAPPING]} %) · "
                 f"свои часы {tally[OWN_CLOCK_MAPPING]} ({share[OWN_CLOCK_MAPPING]} %) · "
                 f"НЕ ИЗМЕРЕНО {tally[UNMEASURED]} ({share[UNMEASURED]} %)")
    resolved = doc.get("share_of_resolved_pct")
    if resolved:
        lines.append(f"[СРЕДИ РАЗРЕШЁННЫХ {doc['resolved']}] вход "
                     f"{resolved[INPUT_MAPPING]} % · свои часы "
                     f"{resolved[OWN_CLOCK_MAPPING]} % — знаменатель НАЗВАН, "
                     f"«не измерено» из него не вычеркнуто молча")
    adm = doc["admitted_names"]
    lines.append(f"[ПРИНЯТЫЕ ИМЕНА] площадок {adm['sites']} · вход "
                 f"{adm['tally'][INPUT_MAPPING]} · свои часы "
                 f"{adm['tally'][OWN_CLOCK_MAPPING]} · НЕ ИЗМЕРЕНО "
                 f"{adm['tally'][UNMEASURED]}")
    for case in doc["named_cases"]:
        lines.append(f"[СЛУЧАЙ ADR-539] {case['module']}:{case['line']} "
                     f"{case['field']} → {case['verdict']} — {case['why']}")
    for row in doc["own_clock_sites"][:8]:
        lines.append(f"  ⏰ {row['module']}:{row['line']} {row['field']} ← "
                     f"{row['clock_name']}: {row['why']}")
    for row in doc["unmeasured_causes"][:8]:
        lines.append(f"  ? {row['sites']:4} — {row['cause']}")
    verdict = doc["verdict"]
    lines.append(f"[ВЕРДИКТ] {'НАХОДКА' if verdict['finding'] else 'чисто'}: "
                 f"{verdict['why'] or 'ось читает своё отображение не реже чужого'}")
    lines.append(f"[ПРАВО ОСИ] поддерживать решение об имени: НЕТ — "
                 f"{verdict['why_it_may_not']}")
    for line in doc["one_sidedness"]:
        lines.append(f"ЦЕНА ОДНОСТОРОННОСТИ: {line}")
    lines.append("НЕ ДОКЛАДЫВАЕТ: поставил ли ЗОВУЩИЙ отметку своими часами "
                 "(через импорт мера не ходит) · какая из нескольких привязок "
                 "имени дошла до чтения · содержимое вложенного отображения")
    lines.append("ADVISORY: прибор только ЧИТАЕТ исходники — _IDENTITY_FIELDS, "
                 "координаты, RiskPolicy v1.0, стоп-кран и живой трек не трогает")
    return lines


def format_report(doc: Dict[str, Any]) -> List[str]:
    """Имя, которое зовёт шаг 0-офис. Правило отрисовки живёт у ПРОИЗВОДИТЕЛЯ."""
    return render(doc)


def save_artifact(doc: Dict[str, Any], data_dir: Path) -> Path:
    path = Path(data_dir) / ARTIFACT
    atomic_save(doc, str(path))
    return path


def run(root: Optional[str] = None, *,
        now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (``findings_bridge``).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис не
    отличит его от «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(repo_root, now=now)
    try:
        save_artifact(doc, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        doc = dict(doc)
        doc["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(doc.get("measured")), "doc": doc}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=None, help="корень дерева (умолчание — своё)")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(list(argv) if argv is not None else None)
    doc = run(root=args.root)["doc"]
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in render(doc):
            print(line)
    if not doc.get("measured"):
        return 2
    return 1 if doc.get("status") == "НАХОДКА" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
