#!/usr/bin/env python3
"""Модульная числовая постоянная как ОПЕРАНД — третья односторонность оси, замером.

Заказ **G115 п. 2** приказа владельца «Portfolio CIO» (поставлен ADR-541).
Дословно: «Модульная числовая постоянная — третья односторонность оси. Замерить
население класса: сколько мест вида ``КОНСТАНТА - значение`` ось сегодня не
видит, и есть ли среди них хоть одно поле-кандидат. Если населения нет —
записать это и закрыть, а не расширять ось на всякий случай.»

Что именно ось не видит
------------------------------------------------------------------------------
Ось ``arithmetic_derived`` (:mod:`spa_core.monitoring.identity_field_kind`)
называет родом не оператор, а ОПЕРАНД: числом выражение делает операнд,
числовой ПО ПОСТРОЕНИЮ — числовой литерал либо счёт/сумма/округление
(``_numeric_operand``). Модульная постоянная ``BEACON_MAX_AGE_S = 21600``
числовая по построению ровно так же — но она ИМЯ, а не литерал, и в
``scope.derived`` не попадает: туда входят имена, связанные с ПОСЧИТАННЫМ
значением, а ``= 21600`` ничего не считает. Поэтому ``BEACON_MAX_AGE_S - age``
ось молчит, а ``21600 - age`` называет находкой — одно и то же вычисление под
двумя написаниями.

Односторонность в сторону «чисто», как и две названные до неё (замыкание над
объемлющей функцией — задел G113 п. 3; порядок привязок — ADR-503).

Как мерено: ПОДСТАНОВКА ОПЕРАНДА, а не вторая копия правила
------------------------------------------------------------------------------
Второй разбор «что здесь арифметика» расходился бы с осью молча (урок #820:
второй поиск предмета, уже раскрытого соседом, РАСХОДИТСЯ). Поэтому правило
оси не копируется и не подменяется: прибор прогоняет НАСТОЯЩУЮ ось ДВАЖДЫ по
одному модулю —

1. как есть (ответ «что ось видит сегодня»);
2. по дереву, где каждое ЧТЕНИЕ модульной числовой постоянной заменено её
   литералом (ответ «что ось увидела бы, будь постоянная литералом»).

**Разница ответов и ЕСТЬ население класса.** Подстановка не выдумывает правило,
а исполняет само определение «числовой по построению»: если имя связано только
с числовым литералом, то его чтение и этот литерал — одно и то же значение.
Метод тот же, которым мерены классы #453 (pid) и #700 (git-окружение):
прогнать дважды, подменив одну дверь, и считать предметом класса то, у чего
сменился вердикт.

Что прибор НЕ доказывает
------------------------------------------------------------------------------
* **Годность рода в личность.** Правило «род ⇒ годность» отвергнуто замером
  (ADR-539/503), и этот прибор его не возвращает: он печатает НАСЕЛЕНИЕ, а не
  вердикт о поле. Ось не расширена ни на одно имя — заказ требовал замера.
* **Затенённое имя не подставляется ВОВСЕ.** Если имя постоянной где-нибудь в
  модуле затенено параметром, циклом или ``with``, подстановка его пропускает
  целиком — во всех областях, включая модульную. Односторонность названа:
  промах в сторону «чисто» (ЗАНИЖАЕТ население), и выбор сделан по той же
  причине, что у самой оси, — население не есть гейт, поэтому цена промаха
  есть недостающая строка отчёта, а не отвергнутое имя.
* **Постоянная вне модульной области не считается постоянной.**
  ``def f(): LIMIT = 5`` — привязка функции, а не модуля; заказ назвал класс
  МОДУЛЬНЫМ, и расширять его здесь значило бы мерить не тот класс.
* **Имя, пере-связанное в модуле хоть раз с не-числом, постоянной не является.**
  ``X = 300`` … ``X = load()`` — по построению уже не число.
* **Транзитивный случай назван ОТДЕЛЬНЫМ числом.** ``HALF = LIMIT / 2`` на
  модульном уровне делает ``HALF`` посчитанным, и поле, читающее ``HALF``,
  ось тоже не видит. Это тот же класс (значение происходит от постоянной), но
  в САМОМ выражении поля постоянной нет — поэтому ``direct`` и ``transitive``
  печатаются раздельно и не складываются в одно число.

Три исхода различимы на каждом уровне (инв. #17)
------------------------------------------------------------------------------
======================= ============================================
уровень                 третий исход
======================= ============================================
свод                    каталога нет в дереве ⇒ причина поимённо
свод                    ни один файл не разобран ⇒ ``UNMEASURED``
модуль                  файл не разобран ⇒ причина, не «постоянных нет»
модуль                  состав площадок разошёлся между двумя
                        прогонами ⇒ ``UNMEASURED`` с причиной, а не
                        молчаливое спаривание не тех мест
население кандидатов    перечень кандидатов не дан ⇒ ``None``, а не
                        «ни одного кандидата не задето»
======================= ============================================

ADVISORY: прибор только ЧИТАЕТ исходники. ``_IDENTITY_FIELDS``, координаты,
RiskPolicy v1.0, стоп-кран и живой трек он не трогает.
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # pragma: no cover - путь для прямого запуска
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import identity_field_kind as field_kind  # noqa: E402

SCHEMA = "modular_constant_operand.v1"

PRODUCER = "spa_core/monitoring/modular_constant_operand.py"

#: Населения у класса нет вовсе — ось расширять не на чем.
EMPTY = "EMPTY"

#: Население есть, но ни одно место не пишет поле-кандидат: заказ велел
#: «записать это и закрыть», а не расширять ось на всякий случай.
POPULATED_NO_CANDIDATE = "POPULATED_NO_CANDIDATE"

#: Население есть И хотя бы одно место пишет поле, о котором перепись спрашивает.
POPULATED_CANDIDATE_TOUCHED = "POPULATED_CANDIDATE_TOUCHED"

#: Не измерено. Никогда не выдаётся за «чисто» (инв. #17).
UNMEASURED = "UNMEASURED"

#: Каталоги дерева — ТЕ ЖЕ, что у оси. Своего списка здесь быть не может:
#: население класса обязано совпадать с населением, которое судит ось.
DEFAULT_ROOTS = field_kind.DEFAULT_ROOTS


@dataclasses.dataclass(frozen=True)
class Site:
    """Место, которое ось не видит сегодня и увидела бы при литерале."""

    module: str
    line: int
    field: str
    how: str
    consts: Tuple[str, ...]

    @property
    def transitive(self) -> bool:
        """В САМОМ выражении поля постоянной нет — значение пришло через имя."""
        return not self.consts

    def __str__(self) -> str:
        where = ",".join(self.consts) if self.consts else "через имя"
        return f"{self.module}:{self.line} {self.field} ← {self.how} [{where}]"


def _numeric_literal(node: Optional[ast.AST]) -> Optional[str]:
    """Литерал-число — или ``None``.

    ``bool`` исключён ТИПОМ, а не вычитанием из списка: ``True`` есть ``int``
    по наследству, и ``isinstance`` пропустил бы флаг в арифметику. Правило
    дословно то же, что у ``identity_field_kind._numeric_operand``, и это не
    дублирование: здесь оно отвечает на другой вопрос — «постоянная ли это
    привязка», а не «числовой ли это операнд».
    """
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return repr(node.value)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in (int, float)):
        sign = "-" if isinstance(node.op, ast.USub) else ""
        return f"{sign}{node.operand.value!r}"
    return None


def _module_bindings(tree: ast.Module) -> Dict[str, List[Optional[ast.AST]]]:
    """Все привязки МОДУЛЬНОЙ области: имя → список привязанных выражений.

    ``None`` в списке означает привязку, выражения у которой нет или она не
    присваивание (``for``, ``with``, ``+=``, ``import``): такое имя постоянной
    быть не может, и отличить его от «связано числом» обязано ЗНАЧЕНИЕ, а не
    отсутствие строки.
    """
    out: Dict[str, List[Optional[ast.AST]]] = {}

    def add(names: Iterable[str], value: Optional[ast.AST]) -> None:
        for name in names:
            out.setdefault(name, []).append(value)

    for node in field_kind._own_body(tree):
        if isinstance(node, ast.Assign):
            names: Set[str] = set()
            for target in node.targets:
                names |= field_kind._targets(target)
            add(names, node.value)
        elif isinstance(node, ast.AnnAssign):
            add(field_kind._targets(node.target), node.value)
        elif isinstance(node, ast.AugAssign):
            add(field_kind._targets(node.target), None)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            add(field_kind._targets(node.target), None)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    add(field_kind._targets(item.optional_vars), None)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            add({node.name}, None)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            add({(a.asname or a.name).split(".")[0] for a in node.names}, None)
    return out


def module_constants(tree: ast.Module) -> Dict[str, str]:
    """Имя → литерал: модульные имена, связанные ТОЛЬКО числовыми литералами.

    «Только» — обязательное слово. Имя, пере-связанное хоть раз чем-то иным,
    числом по построению не является, и считать его таким значило бы мерить
    догадку. Затенение проверяется ОТДЕЛЬНО (:func:`shadowed_anywhere`): оно
    свойство других областей, а не этой привязки.
    """
    out: Dict[str, str] = {}
    for name, values in _module_bindings(tree).items():
        literals = [_numeric_literal(v) for v in values]
        if literals and all(lit is not None for lit in literals):
            out[name] = str(literals[0])
    return out


def shadowed_anywhere(tree: ast.Module) -> Set[str]:
    """Имена, затенённые НЕ присваиванием хоть в одной области модуля.

    Такое имя подстановка пропускает целиком — не потому, что это точно не
    постоянная, а потому, что РАЗЛИЧИТЬ области здесь нельзя без второй копии
    правила видимости оси. Односторонность названа в модульной справке:
    население ЗАНИЖАЕТСЯ.
    """
    out: Set[str] = set()
    for scope_node in field_kind._scopes(tree):
        if scope_node is tree:
            continue
        out |= field_kind._shadowed(scope_node)
    return out


class _Substitute(ast.NodeTransformer):
    """Чтение постоянной → её литерал. Ничего, кроме чтений, не меняется."""

    def __init__(self, consts: Dict[str, str]) -> None:
        self.consts = consts
        self.done = 0

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        if not isinstance(node.ctx, ast.Load) or node.id not in self.consts:
            return node
        try:
            value = ast.literal_eval(self.consts[node.id])
        except (ValueError, SyntaxError):  # pragma: no cover - литерал наш
            return node
        self.done += 1
        return ast.copy_location(ast.Constant(value=value), node)


def substituted(tree: ast.Module, consts: Dict[str, str]
                ) -> Tuple[ast.Module, int]:
    """Копия дерева, где чтения постоянных стали литералами. Вторым — сколько.

    Отметки положения КОПИРУЮТСЯ у исходного узла (``copy_location``): номера
    строк в отчёте обязаны указывать на НАСТОЯЩИЙ файл, а не на разобранную
    копию (урок: «регион по номерам строк пуст на разобранной базе»).
    """
    clone = copy.deepcopy(tree)
    sub = _Substitute(consts)
    clone = sub.visit(clone)
    ast.fix_missing_locations(clone)
    return clone, sub.done


def _axis_answers(tree: ast.Module) -> List[Tuple[str, int, str]]:
    """``(поле, строка, что ось сказала)`` для каждой площадки — НАСТОЯЩЕЙ осью.

    Прогон повторяет ровно то, что делает ``identity_field_kind.module_kinds``
    на своей третьей оси, и зовёт ЕГО функции: таблицу областей, обёртки,
    сильное и слабое прочтения. Правило здесь не живёт ни одной строкой —
    иначе прибор и ось разошлись бы молча. Верность повторения проверяется
    контролем (``test_the_today_answer_equals_the_axis_itself``).
    """
    scopes = field_kind._scope_table(tree, field_kind.arith_derivation,
                                     field_kind.arith_wrappers(tree))
    out: List[Tuple[str, int, str]] = []
    for name, value, line, scope_node in field_kind.field_assignments(tree):
        scope = scopes.get(id(scope_node), scopes[id(tree)])
        how = field_kind.arith_derivation(value, scope)
        if not how:
            how = field_kind.arith_formatted(value, scope) or ""
        out.append((name, line, how))
    return out


def _consts_in(value: ast.AST, consts: Dict[str, str]) -> Tuple[str, ...]:
    """Постоянные, прочитанные В САМОМ выражении площадки (без спуска в чужое)."""
    found: Set[str] = set()
    for node in ast.walk(value):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id in consts):
            found.add(node.id)
    return tuple(sorted(found))


def module_sites(source: str) -> Tuple[Optional[List[Site]], Dict[str, str], str]:
    """Площадки класса в ОДНОМ модуле. Вторым — постоянные, третьим — причина.

    ``(None, {}, причина)`` — третий исход: файл не разобран либо два прогона
    дали РАЗНЫЙ состав площадок. Второе означает, что подстановка задела
    структуру, а не только операнд; спарить тогда «что было» и «что стало»
    нельзя, и молчаливое спаривание не тех мест было бы хуже отказа.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return None, {}, f"не разобрано: {type(exc).__name__}"
    consts = module_constants(tree)
    for name in shadowed_anywhere(tree):
        consts.pop(name, None)
    if not consts:
        return [], {}, ""
    clone, _ = substituted(tree, consts)
    before = _axis_answers(tree)
    after = _axis_answers(clone)
    if len(before) != len(after) or [(n, l) for n, l, _ in before] != [
            (n, l) for n, l, _ in after]:
        return None, consts, ("состав площадок разошёлся между прогонами: "
                              f"{len(before)} против {len(after)}")
    by_line: Dict[Tuple[str, int], ast.AST] = {}
    for name, value, line, _scope in field_kind.field_assignments(tree):
        by_line.setdefault((name, line), value)
    sites: List[Site] = []
    for (name, line, was), (_n, _l, now) in zip(before, after):
        if was or not now:
            continue
        value = by_line.get((name, line))
        sites.append(Site(module="", line=line, field=name, how=now,
                          consts=_consts_in(value, consts) if value is not None
                          else ()))
    return sites, consts, ""


def census(tree_root: Path,
           roots: Sequence[str] = DEFAULT_ROOTS) -> dict:
    """Население класса по всему дереву. Тесты исключены — как у оси."""
    sites: List[Site] = []
    unmeasured: Dict[str, str] = {}
    modules_with_consts = 0
    constants_seen = 0
    files_parsed = 0
    for root in roots:
        base = Path(tree_root) / root
        if not base.is_dir():
            unmeasured[root] = "каталога нет в дереве"
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(tree_root))
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured[rel] = f"не прочитано: {type(exc).__name__}"
                continue
            found, consts, why = module_sites(source)
            if found is None:
                unmeasured[rel] = why
                continue
            files_parsed += 1
            if consts:
                modules_with_consts += 1
                constants_seen += len(consts)
            sites.extend(dataclasses.replace(s, module=rel) for s in found)
    doc = {
        "schema": SCHEMA,
        "files_parsed": files_parsed,
        "files_unmeasured": unmeasured,
        "modules_with_constants": modules_with_consts,
        "constants_seen": constants_seen,
        "sites": [dataclasses.asdict(s) for s in sites],
        "population": len(sites),
        "direct": sum(1 for s in sites if not s.transitive),
        "transitive": sum(1 for s in sites if s.transitive),
    }
    if not files_parsed:
        doc["status"] = UNMEASURED
        doc["reason"] = ("ни один файл дерева не разобран — ноль мест читался "
                         "бы как ответ")
    return doc


def tally(candidate_fields: Optional[Dict[str, int]],
          identity_fields: Optional[Sequence[str]],
          tree_root: Optional[Path]) -> dict:
    """Свод: население класса и ЗАДЕТО ли им хоть одно поле-кандидат.

    ``tree_root=None`` ⇒ ``UNMEASURED`` с причиной: население есть утверждение
    о КОДЕ, и выдумать его нельзя. ``candidate_fields=None`` ⇒ пересечение
    остаётся ``None``, а не нулём: «перечня не дали» и «ни одного не задето» —
    разные ответы (инв. #17).
    """
    if tree_root is None:
        return {
            "schema": SCHEMA,
            "status": UNMEASURED,
            "reason": "дерева не дали — население класса есть утверждение о КОДЕ",
            "population": None,
            "candidate_hits": None,
            "identity_hits": None,
            "what_it_does_not_prove": _NOT_PROVEN,
        }
    doc = census(Path(tree_root))
    if doc.get("status") == UNMEASURED:
        doc.update({"candidate_hits": None, "identity_hits": None,
                    "what_it_does_not_prove": _NOT_PROVEN})
        return doc
    sites = [Site(**s) for s in doc["sites"]]
    cand = set(candidate_fields or {}) if candidate_fields is not None else None
    ident = set(identity_fields or ()) if identity_fields is not None else None
    cand_rows = (None if cand is None
                 else [str(s) for s in sites if s.field in cand])
    ident_rows = (None if ident is None
                  else [str(s) for s in sites if s.field in ident])
    doc["candidate_hits"] = None if cand_rows is None else len(cand_rows)
    doc["candidate_sites"] = cand_rows
    doc["identity_hits"] = None if ident_rows is None else len(ident_rows)
    doc["identity_sites"] = ident_rows
    doc["candidate_denominator"] = None if cand is None else len(cand)
    if not sites:
        doc["status"] = EMPTY
        doc["reason"] = ("мест вида «постоянная ⊕ значение», которых ось не "
                         "видит, в дереве нет — расширять ось не на чем")
    elif cand_rows or ident_rows:
        doc["status"] = POPULATED_CANDIDATE_TOUCHED
        doc["reason"] = (
            f"население класса {len(sites)}; из них пишут поле-кандидат "
            f"{len(cand_rows or [])}, поле из _IDENTITY_FIELDS "
            f"{len(ident_rows or [])}")
    else:
        doc["status"] = POPULATED_NO_CANDIDATE
        doc["reason"] = (
            f"население класса {len(sites)}, но ни одно место не пишет поле, "
            "о котором перепись спрашивает — заказ велел записать и закрыть")
    doc["what_it_does_not_prove"] = _NOT_PROVEN
    return doc


_NOT_PROVEN = [
    "население НЕ есть правило: ось не расширена ни на одно имя, и «род ⇒ "
    "годность» остаётся отвергнутым замером (ADR-539/503)",
    "затенённое хоть в одной области имя не подставляется ВОВСЕ — промах в "
    "сторону «чисто», население ЗАНИЖЕНО",
    "постоянная функции постоянной здесь не считается: заказ назвал класс "
    "МОДУЛЬНЫМ",
    "«поле-кандидат задето» говорит о МЕСТЕ в коде, а не о годности поля в "
    "личность — годность меряет перепись, и правила от этого числа у неё нет",
]


def report(doc: dict, *, max_rows: int = 8) -> List[str]:
    """Строки отчёта. Знаменатель рядом с числителем, третий исход — вслух."""
    status = doc.get("status")
    if status == UNMEASURED:
        return [f"НЕ ИЗМЕРЕНО: {doc.get('reason')}"]
    out = [str(doc.get("reason"))]
    out.append(
        f"  население {doc.get('population')} "
        f"(в самом выражении {doc.get('direct')} · через имя "
        f"{doc.get('transitive')}) · модулей с постоянными "
        f"{doc.get('modules_with_constants')} · постоянных "
        f"{doc.get('constants_seen')} · файлов разобрано "
        f"{doc.get('files_parsed')}")
    hits = doc.get("candidate_hits")
    denom = doc.get("candidate_denominator")
    out.append("  полей-кандидатов задето: "
               + ("НЕ ИЗМЕРЕНО (перечня не дали)" if hits is None
                  else f"{hits} из {denom}"))
    ident = doc.get("identity_hits")
    out.append("  полей _IDENTITY_FIELDS задето: "
               + ("НЕ ИЗМЕРЕНО (перечня не дали)" if ident is None
                  else str(ident)))
    for row in (doc.get("sites") or [])[:max_rows]:
        out.append(f"    · {Site(**row)}")
    extra = len(doc.get("sites") or []) - max_rows
    if extra > 0:
        out.append(f"    … ещё {extra} мест(а)")
    for why in doc.get("files_unmeasured") or {}:
        out.append(f"  [НЕ ИЗМЕРЕНО] {why}: "
                   f"{(doc.get('files_unmeasured') or {})[why]}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """``0`` — населения нет · ``1`` — есть · ``2`` — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree-root", default=str(_ROOT), help="корень дерева")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rows", type=int, default=8)
    args = ap.parse_args(argv)
    from spa_core.monitoring import list_identity_census as census_mod
    identity = list(census_mod.probe.IDENTITY_FIELDS)
    doc = tally(None, identity, Path(args.tree_root))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in report(doc, max_rows=args.max_rows):
            print(f"[ПОСТОЯННАЯ-ОПЕРАНД] {line}")
    if doc.get("status") == UNMEASURED:
        return 2
    return 1 if doc.get("population") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
