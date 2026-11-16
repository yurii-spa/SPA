#!/usr/bin/env python3
"""РЫЧАГ варианта (а) заказа G1013 п. 1: ЗОВЁТ ли производитель общую дверь чтения.

## Откуда вопрос

ADR-1024 (цикл #1162) измерил ЦЕНУ варианта (а) — «производители пишут рядом с
артефактом дайджест своих входов» — и нашёл ПОЛ: входы у себя не называют не
меньше 14 производителей офиса из 16. Там же назван РЫЧАГ, из-за которого
вариант (а) не обязан стоить «по разу на производителя»:

    «Площадки чтения сходятся в общих помощников: шесть файлов несут двери у
    двух и более производителей, и у ``spa_core/utils/atomic.py`` таких
    производителей **16 из 16**. То есть запись читателя ставится у немногих
    общих дверей.»

Заказ **G1013 п. 1** потребовал измерить это число ДО правки — «сколько членов
закрывается одной дверью ``atomic_load``», — и потребовал верно: рычаг ADR-1024
посчитан не тем вопросом, и ошибка идёт в САМУЮ опасную сторону (рычаг выглядит
существующим).

## Что именно посчитал рычаг ADR-1024 — и почему это не он

Ось слепого места (``producer_input_awareness.helper_doors``) перечисляет
помощников, которых производитель назвал САМ (глубина 1), и ``_shared_doors``
группирует их по ФАЙЛУ: «файл H несёт дверь, и его назвали N производителей».
Оба утверждения верны. Но между ними и рычагом лежит вопрос, которого не задал
никто:

* ADR-1024 спросил: **ДОСТИЖИМ** ли файл с дверью из модуля производителя (есть
  ли `import`);
* запись читателя требует: **ЗОВЁТ** ли производитель саму ДВЕРЬ.

Замер этого цикла: все 16 производителей импортируют ``spa_core.utils.atomic``
ради ``atomic_save`` — двери ЗАПИСИ, — а единственную дверь ЧТЕНИЯ того файла
(``atomic_load``, ``open(path, "r")`` в строке 108) не зовёт НИ ОДИН. Ровно тот
же дефект, который ADR-1024 нашёл и починил У СЕБЯ ВНУТРИ (его дефект №1:
«``open`` в режиме ЗАПИСИ числился дверью ЧТЕНИЯ»), остался нетронутым на
уровень выше — у РЫЧАГА, а не у вердикта.

## Ловушка, на которой греп соврал бы, а AST не врёт

Первый, дешёвый замер этого цикла был грепом, и он дал **1** зов ``atomic_load``
— в ``cio_target_producers.py``. Зова там нет: это СТРОКОВЫЙ ЛИТЕРАЛ в кортеже
имён загрузчиков (``_LOADERS = ("_load_portfolio_state", "atomic_load", …)``),
то есть данные, а не вызов. Поэтому дверь спрашивается у AST и только у
ВЫЗОВА, чья цель разрешилась в объявленный `import`; строка, равная имени
двери, зовом не является. Положительный контроль на эту ловушку — проба
:func:`test_a_string_literal_equal_to_a_door_name_is_not_a_call`.

## Четыре рода ДВЕРИ помощника — и под запись годится один

Запись читателя ставится там, где её можно ПОЗВАТЬ по имени:

* :data:`D_FUNCTION` — площадка чтения внутри функции УРОВНЯ МОДУЛЯ: дверь
  годится под запись, её зовут по имени;
* :data:`D_METHOD` — площадка внутри метода класса: дверь НАЗВАНА, но позвать её
  по имени нельзя (нужен экземпляр), и вопрос «зовёт ли» к ней не задаётся;
* :data:`D_IMPORT_TIME` — площадка на уровне модуля: исполняется ИМПОРТОМ, а не
  зовом, и к рычагу отношения не имеет;
* :data:`D_FOREIGN` — чужой процесс: не чтение файла вовсе. Помощник, у которого
  других дверей нет, общим читателем быть не может — так устроен
  ``spa_core/monitoring/call_provenance.py`` (единственная площадка —
  ``subprocess.run``), и ADR-1024 числит его одним из шести «общих помощников с
  дверями».

Склеить эти роды значило бы объявить рычагом то, чего позвать нельзя.

## Три рода СВЯЗИ производителя с помощником (инв. #17)

* :data:`C_CALLS` — зовёт дверь (число зовов названо);
* :data:`C_IMPORTS_ONLY` — ИМПОРТИРУЕТ помощника, но ни одной его двери чтения
  не зовёт. Это и есть ровно тот род, который ADR-1024 посчитал рычагом;
* :data:`C_NO_LINK` — помощник в модуле не назван вовсе;
* :data:`C_UNMEASURED` — модуль не разобран, с названной причиной.

## Чего модуль НЕ делает

Не пишет НИ ОДНОГО файла (чистый читатель, ``--json`` в stdout) — ни дайджестов,
ни правок производителей. Не держит СВОЕГО перечня членов класса: поверхность
приходит из :func:`producer_input_awareness.measure`, а та берёт её у закрытой
таблицы ``edition_remeasure.ENTRY`` (ADR-1022). Разойдись они — рычаг считался
бы для одного набора производителей, а решение принималось бы о другом
(`.claude/rules/adapters.md` § «Одно имя — один объект»).

Не утверждает, что найденный зов ИСПОЛНЯЕТСЯ: достижимость зова есть не
исполнение (та же граница, что у ``helper_execution_census`` и у соседа
ADR-1024). И не отвечает на вопрос «надо ли ставить дайджест»: он отвечает
только «есть ли ОДНА дверь, которая закрывает многих».
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from spa_core.monitoring import producer_input_awareness as pia
from spa_core.monitoring.producer_input_awareness import Unmeasured

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Роды ДВЕРИ помощника. Под запись читателя годится РОВНО :data:`D_FUNCTION`.
D_FUNCTION = "module_level_function"
D_METHOD = "method_of_a_class"
D_IMPORT_TIME = "import_time_site"
D_FOREIGN = "foreign_process"

#: Роды СВЯЗИ производителя с помощником.
C_CALLS = "calls_the_door"
C_IMPORTS_ONLY = "imports_the_helper_but_calls_no_read_door"
C_NO_LINK = "helper_not_named_in_the_module"
C_UNMEASURED = "unmeasured"

#: Площадки, которые считаются ЧТЕНИЕМ ФАЙЛА (перебор каталога тоже: запись
#: читателя у него возможна). Чужой процесс сюда НЕ входит — его не ухватит
#: никакая запись читателя, и это сказано ADR-1024 дословно.
_READING_KINDS = frozenset({
    pia.S_NAMED, pia.S_ENUM, pia.S_CONDUIT, pia.S_COMPUTED,
})


@dataclass(frozen=True)
class Door:
    """Одна дверь помощника: имя, которым её можно позвать (или нельзя)."""

    rel: str
    name: Optional[str]
    line: int
    kind: str
    site_door: str


@dataclass
class Link:
    """Связь ОДНОГО производителя с ОДНИМ помощником."""

    artifact: str
    helper: str
    kind: str
    calls: tuple[tuple[str, int], ...] = ()
    reason: Optional[str] = None


@dataclass
class Helper:
    """Общий помощник: его двери и связи с ним."""

    rel: str
    named_by: tuple[str, ...]
    doors: tuple[Door, ...] = ()
    links: list[Link] = field(default_factory=list)
    reason: Optional[str] = None

    @property
    def callable_doors(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            d.name for d in self.doors if d.kind == D_FUNCTION and d.name))

    @property
    def callers(self) -> tuple[str, ...]:
        return tuple(l.artifact for l in self.links if l.kind == C_CALLS)


def _toplevel_owner(tree: ast.Module) -> dict[int, tuple[str, Optional[str]]]:
    """``номер строки → (род площадки, имя двери)`` по ВЕРХНЕМУ объемлющему узлу.

    Род спрашивается у ВЕРХНЕГО уровня, а не у ближайшей функции: вложенная
    функция внутри ``def f`` зовётся через ``f``, а метод класса по имени не
    зовётся вовсе, сколько бы функций внутри него ни лежало.
    """
    out: dict[int, tuple[str, Optional[str]]] = {}

    def mark(node: ast.AST, kind: str, name: Optional[str]) -> None:
        for child in ast.walk(node):
            line = getattr(child, "lineno", None)
            if line is not None:
                out.setdefault(line, (kind, name))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(node, D_FUNCTION, node.name)
        elif isinstance(node, ast.ClassDef):
            mark(node, D_METHOD, node.name)
    return out


def doors_of(root: pathlib.Path, rel: str) -> tuple[Door, ...]:
    """Двери ОДНОГО помощника.

    Площадки берутся у соседа (:func:`producer_input_awareness.sites_of`) — свой
    разборщик дверей означал бы, что рычаг считается по одному определению
    двери, а цена по другому.
    """
    tree = pia._parse(root, rel)
    owner = _toplevel_owner(tree)
    out: list[Door] = []
    for site in pia.sites_of(tree, rel):
        if site.kind == pia.S_FOREIGN:
            out.append(Door(rel, None, site.line, D_FOREIGN, site.door))
            continue
        if site.kind not in _READING_KINDS:
            continue
        kind, name = owner.get(site.line, (D_IMPORT_TIME, None))
        out.append(Door(rel, name if kind == D_FUNCTION else None,
                        site.line, kind, site.door))
    return tuple(out)


def _import_map(tree: ast.Module, root: pathlib.Path) -> tuple[
        dict[str, tuple[str, str]], dict[str, str]]:
    """Что модуль ВВЁЗ: ``имя → (файл помощника, имя двери)`` и ``алиас → файл``.

    Короткое имя засчитывается зовом ТОЛЬКО если оно пришло объявленным
    `import`-ом: иначе одноимённая своя функция числилась бы зовом чужой двери.
    """
    names: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                rel = pia._module_rel(alias.name, root)
                if rel:
                    modules[alias.asname or alias.name.split(".")[0]] = rel
                    modules[alias.name] = rel
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            mod_rel = pia._module_rel(node.module, root)
            for alias in node.names:
                sub_rel = pia._module_rel(f"{node.module}.{alias.name}", root)
                if sub_rel:
                    # ``from spa_core.utils import atomic`` — ввезён МОДУЛЬ.
                    modules[alias.asname or alias.name] = sub_rel
                elif mod_rel:
                    # ``from spa_core.utils.atomic import atomic_load`` — ИМЯ.
                    names[alias.asname or alias.name] = (mod_rel, alias.name)
    return names, modules


def _calls_to(tree: ast.Module, root: pathlib.Path, helper_rel: str,
              doors: Sequence[str]) -> tuple[tuple[str, int], ...]:
    """Зовы дверей ``doors`` помощника ``helper_rel`` в этом модуле.

    Считается только ``ast.Call``: строка, равная имени двери, зовом не
    является (замер этого цикла — ``_LOADERS`` в ``cio_target_producers.py``).
    """
    wanted = frozenset(doors)
    if not wanted:
        return ()
    names, modules = _import_map(tree, root)
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            target = names.get(func.id)
            if target and target[0] == helper_rel and target[1] in wanted:
                out.append((target[1], node.lineno))
        elif isinstance(func, ast.Attribute):
            owner = pia._dotted(func.value) if not isinstance(
                func.value, ast.Name) else func.value.id
            if owner and modules.get(owner) == helper_rel and func.attr in wanted:
                out.append((func.attr, node.lineno))
    return tuple(out)


def _links(root: pathlib.Path, helper: Helper,
           producer_rel: Mapping[str, str]) -> list[Link]:
    doors = helper.callable_doors
    out: list[Link] = []
    for artifact in helper.named_by:
        rel = producer_rel.get(artifact)
        if not rel:
            out.append(Link(artifact, helper.rel, C_UNMEASURED,
                            reason="производитель не разрешился в файл дерева"))
            continue
        try:
            tree = pia._parse(root, rel)
        except Unmeasured as exc:
            out.append(Link(artifact, helper.rel, C_UNMEASURED, reason=str(exc)))
            continue
        calls = _calls_to(tree, root, helper.rel, doors)
        if calls:
            out.append(Link(artifact, helper.rel, C_CALLS, calls))
            continue
        _, modules = _import_map(tree, root)
        imported = helper.rel in set(modules.values()) or helper.rel in {
            v[0] for v in _import_map(tree, root)[0].values()}
        out.append(Link(artifact, helper.rel,
                        C_IMPORTS_ONLY if imported else C_NO_LINK))
    return out


def measure(root: pathlib.Path | str = _REPO_ROOT, *,
            doc: Optional[Mapping] = None) -> dict:
    """ЗАМЕР рычага: какую дверь зовут МНОГИЕ, и зовут ли хоть одну.

    ``doc=None`` ⇒ поверхность берётся у соседа В МОМЕНТ ЗОВА
    (:func:`producer_input_awareness.measure`), а не связывается при определении
    функции: умолчание-ссылка на изменяемый объявленный дом — бомба, измеренная
    ADR-1023 § 5.
    """
    root = pathlib.Path(root)
    if not root.is_dir():
        raise Unmeasured(f"дерева нет по пути {root}")
    base = pia.measure(root) if doc is None else doc
    shared = base.get("shared_doors") or []
    if not shared:
        raise Unmeasured(
            "общих помощников у соседа НЕ НАЗВАНО — рычаг считался бы ни о чём")
    producer_rel = {p["artifact"]: p["rel"] for p in base.get("producers") or ()
                    if p.get("rel")}

    helpers: list[Helper] = []
    for row in shared:
        rel = str(row["rel"])
        h = Helper(rel, tuple(row.get("producers") or ()))
        try:
            h.doors = doors_of(root, rel)
        except Unmeasured as exc:
            h.reason = str(exc)
            helpers.append(h)
            continue
        h.links = _links(root, h, producer_rel)
        helpers.append(h)

    return {
        "schema": "shared-read-door-leverage/1",
        "root": str(root),
        "producers_measurable": len(producer_rel),
        "helpers": [_helper_doc(h) for h in helpers],
        "best": _best(helpers),
        "counts": _counts(helpers),
    }


def _helper_doc(h: Helper) -> dict:
    return {
        "rel": h.rel,
        "named_by": list(h.named_by),
        "named_by_n": len(h.named_by),
        "reason": h.reason,
        "doors": [{"name": d.name, "line": d.line, "kind": d.kind,
                   "site_door": d.site_door} for d in h.doors],
        "callable_doors": list(h.callable_doors),
        "callers": list(h.callers),
        "callers_n": len(h.callers),
        "links": [{"artifact": l.artifact, "kind": l.kind,
                   "calls": [{"door": d, "line": n} for d, n in l.calls],
                   "reason": l.reason} for l in h.links],
    }


def _best(helpers: Sequence[Helper]) -> Optional[dict]:
    """Помощник, чью дверь ЗОВЁТ больше всех производителей.

    Пусто — честный исход: «ни одной двери не зовёт никто» это НЕ «помощников
    нет».
    """
    ranked = sorted(helpers, key=lambda h: (-len(h.callers), h.rel))
    if not ranked or not ranked[0].callers:
        return None
    top = ranked[0]
    return {"rel": top.rel, "callers": list(top.callers),
            "callers_n": len(top.callers), "doors": list(top.callable_doors)}


def _counts(helpers: Sequence[Helper]) -> dict[str, int]:
    out = {C_CALLS: 0, C_IMPORTS_ONLY: 0, C_NO_LINK: 0, C_UNMEASURED: 0}
    for h in helpers:
        for l in h.links:
            out[l.kind] = out.get(l.kind, 0) + 1
    out["helpers"] = len(helpers)
    out["helpers_without_a_callable_read_door"] = len(
        [h for h in helpers if not h.callable_doors])
    return out


def verdict(doc: Mapping) -> str:
    """``lever_found`` · ``lever_empty`` · ``unmeasured``."""
    counts = doc.get("counts") or {}
    if counts.get(C_UNMEASURED):
        return "unmeasured"
    best = doc.get("best")
    if best and int(best.get("callers_n") or 0) > 1:
        return "lever_found"
    return "lever_empty"


EXIT_CODES = {"lever_found": 0, "lever_empty": 1, "unmeasured": 2}

_D_RU = {
    D_FUNCTION: "функция уровня модуля (ЗОВЁТСЯ по имени — годится под запись)",
    D_METHOD: "метод класса (по имени не зовётся — нужен экземпляр)",
    D_IMPORT_TIME: "площадка уровня модуля (исполняется ИМПОРТОМ, не зовом)",
    D_FOREIGN: "чужой процесс (не чтение файла вовсе)",
}
_C_RU = {
    C_CALLS: "ЗОВЁТ дверь",
    C_IMPORTS_ONLY: "импортирует помощника, но ни одной двери чтения НЕ ЗОВЁТ",
    C_NO_LINK: "помощник в модуле не назван",
    C_UNMEASURED: "НЕ ИЗМЕРЕНО",
}


def format_report(doc: Mapping, *, verbose: bool = False) -> str:
    counts = doc.get("counts") or {}
    v = verdict(doc)
    lines = [
        f"рычаг варианта (а) заказа G1013 п. 1 — ЗОВЁТ ли производитель общую "
        f"дверь чтения (дерево {doc.get('root')})",
        f"  производителей измеримых: {doc.get('producers_measurable')} · "
        f"общих помощников у соседа: {counts.get('helpers')} "
        f"(поверхность — ADR-1024, своей копии нет)",
        f"  из них БЕЗ зовомой двери чтения: "
        f"{counts.get('helpers_without_a_callable_read_door')}",
    ]
    for kind in (C_CALLS, C_IMPORTS_ONLY, C_NO_LINK, C_UNMEASURED):
        lines.append(f"  {counts.get(kind, 0):>3}  связ(ь/и): {_C_RU[kind]}")
    best = doc.get("best")
    if best:
        lines.append(f"  ЛУЧШАЯ дверь: {best['rel']} — её зовут "
                     f"{best['callers_n']}: {', '.join(best['callers'][:6])}")
    else:
        lines.append("  ЛУЧШЕЙ двери НЕТ: ни одну зовомую дверь чтения общих "
                     "помощников не зовёт НИ ОДИН производитель")
    for h in doc.get("helpers") or ():
        lines.append(f"  • {h['rel']} — назвали {h['named_by_n']}, ЗОВУТ "
                     f"{h['callers_n']}"
                     + (f" — {h['reason']}" if h.get("reason") else ""))
        for d in h["doors"][:4] if verbose else h["doors"][:2]:
            lines.append(f"      дверь {d['name'] or '—'}:{d['line']} "
                         f"{d['site_door']} — {_D_RU[d['kind']]}")
        if not h["callable_doors"]:
            lines.append("      зовомой двери чтения нет вовсе ⇒ общим "
                         "читателем этот помощник быть не может")
        if verbose:
            for l in h["links"]:
                lines.append(f"      {l['artifact']}: {_C_RU[l['kind']]}"
                             + (f" ({len(l['calls'])})" if l["calls"] else ""))
    lines.append(f"  вердикт: {v} (код {EXIT_CODES[v]})")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ — ни дайджестов, ни правок "
                 "производителей; достижимость зова есть НЕ исполнение")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="рычаг варианта (а): зовёт ли производитель офиса общую "
                    "дверь чтения, или только импортирует помощника")
    ap.add_argument("--root", default=str(_REPO_ROOT),
                    help="дерево, в котором меряем (умолчание — своё)")
    ap.add_argument("--all", action="store_true",
                    help="печатать КАЖДУЮ дверь и КАЖДУЮ связь")
    ap.add_argument("--json", action="store_true", help="документ замера в stdout")
    args = ap.parse_args(argv)
    try:
        doc = measure(args.root)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(format_report(doc, verbose=args.all))
    return EXIT_CODES[verdict(doc)]


if __name__ == "__main__":
    raise SystemExit(main())
