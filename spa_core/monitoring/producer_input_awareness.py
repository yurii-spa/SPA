#!/usr/bin/env python3
"""Цена варианта (а) заказа G1012: ЗНАЕТ ли производитель офиса, что он читает.

## Откуда вопрос

ADR-1023 измерил ось ПРИЧИНЫ у класса «вывод прежней редакции» и нашёл, что у
**шести членов из восьми** набор находок двигают ОБЕ оси сразу — и редакция
производителя, и данные под ним. Развести такой член может только ЧЕТВЁРТЫЙ
прогон: СЕГОДНЯШНЯЯ редакция на ПРЕЖНИХ данных. Прежних данных нет ни у кого —
производство перезаписывает их на месте (``atomic_save`` + ``os.replace``), и
снимка входов на момент производства не держит НИКТО.

Заказ G1012 п. 1 назвал два выхода и потребовал измерить цену первого ДО выбора:

* **(а)** производители пишут рядом с артефактом ДАЙДЖЕСТ своих входов — тогда
  «данные те же» станет проверяемым утверждением, а не предположением;
* **(б)** класс остаётся с родом ОБЕ как с честным исходом, и «починка приехала»
  у шести членов не утверждается НИКОГДА.

Цена (а) не в строках кода дайджеста. Она в одном: **может ли производитель
вообще НАЗВАТЬ множество своих входов.** Кто выписал входы именами файлов,
платит несколько строк; кто перебирает каталог, узнаёт свой набор только в
прогоне; кто читает чужим процессом, не знает его и тогда. Модуль меряет РОД, а
не количество строк.

## Что уже объявлено про входы, и почему этого не хватило

Ничего. ``architecture/manifest.json`` объявляет у артефакта ``producer``,
``consumers``, ``slo_hours`` — ключа ``inputs`` там нет НИ У ОДНОГО из 167
артефактов (замер цикла #1162). Объявленного дома у входов офиса не существует,
и спросить «что читает производитель» сегодня можно только у его КОДА. Ближайший
прецедент такого замера — ``architecture/director_runtime_dependencies.json``
(«замер по КОДУ: строковые пути извлечены AST из модулей кокпита»).

## Поверхность — ЗАКРЫТАЯ таблица соседа, а не свой перечень

Члены класса объявлены ОДИН раз — :data:`spa_core.monitoring.edition_remeasure.ENTRY`
(ADR-1022). Этот модуль её ИМПОРТИРУЕТ и своей копии не держит: разойдись они,
цена считалась бы для одного набора производителей, а решение принималось бы о
другом (`.claude/rules/adapters.md` § «Одно имя — один объект»). Член с непустым
``refusal`` уходит в :data:`REFUSED` с ЕГО причиной: у него и перемера нет, и
цена дайджеста к нему не относится.

## Почему судит СВОЙ модуль производителя, а не его замыкание

Первая редакция судила по полному первопартийному замыканию — и ПЕРВЫЙ ЖЕ
прогон показал, что так вопрос не задаётся. Замер (цикл #1162, предел снят до
фиксированной точки):

===================================  ============  =====================
производитель                        файлов        глубина до замыкания
===================================  ============  =====================
``cio_architecture_constraints``     **795**       21
``ledger_parse_census``              **795**       13
``slo_keepability``                  11            3
===================================  ============  =====================

795 файлов — это практически весь ``spa_core``. «Производитель читает X» при
такой привязке означает «что-то в репозитории читает X», то есть НИЧЕГО о
производителе. Поэтому вердикт выносится по ЕГО СОБСТВЕННОМУ модулю, а
замыкание остаётся ОТДЕЛЬНОЙ осью (:func:`helper_doors`) с объявленным пределом
— она называет СЛЕПОЕ МЕСТО вердикта, а не участвует в нём.

Обратную ошибку (разбор ОДНОГО файла) правило называет тоже
(`.claude/rules/deployment.md` § ИНЪЕКЦИЯ ЧАСОВ, ADR-1023 § «Чего это НЕ
закрывает»), и именно поэтому слепое место ПЕЧАТАЕТСЯ, а не замалчивается:
чтение, живущее в помощнике, вердикту о производителе не видно.

## Пять исходов, и почему не три (инв. #17)

Три из них — ответ про ЦЕНУ, два — честные «не про цену».

* :data:`NAMES` — производитель выписал имена входов у себя (строковые литералы
  с именем файла, в том числе через свои же строковые константы), перебора
  каталога нет, вычисленного пути нет, чужого процесса нет. Дайджест стои́т
  несколько строк: список уже у него.
* :data:`RUNTIME_ONLY` — набор входов существует только в прогоне: перебор
  каталога (``glob``/``rglob``/``iterdir``/``os.walk``/``os.listdir``/
  ``os.scandir``) либо путь, собранный из переменных без единого имени.
  Дайджест возможен, но его надо СОБИРАТЬ по ходу чтения. Два механизма
  объединены намеренно: цена у них одна, а различие печатается площадками.
* :data:`FOREIGN` — читает ЧУЖИМ ПРОЦЕССОМ (``subprocess``). Часть входов
  вообще не файлы — это состояние чужой службы, и никакая запись читателя её
  не ухватит.
* :data:`UNMEASURED` — замера НЕ БЫЛО, с названной причиной: модуль не
  разрешился · файл не разобрался · ни одной двери чтения И ни одного имени
  файла в своём модуле (читает целиком через помощников — вердикт о НЁМ
  вынести нечем). Последнее — «не измерено», а НЕ «входов нет».

Склеить :data:`UNMEASURED` с :data:`NAMES` значило бы объявить неизмеренное
дешёвым — ровно та подмена, из-за которой CRITICAL об инварианте #3 печатался
двенадцать циклов (ADR-1020).

## Направление ошибки названо, и оно РАЗНОЕ у двух чисел

* :data:`NAMES` — **ПОТОЛОК** дешёвых: дверь, живущая в помощнике, своему
  модулю не видна, и производитель выглядит дешевле, чем он есть.
* ``RUNTIME_ONLY + FOREIGN`` — **ПОЛ** цены: перебор каталога, путь без имени и чужой процесс —
  признаки устойчивые, и меньше их не станет.

Цена (а) поэтому объявляется как «не меньше, чем», и это не оговорка: выбор
между (а) и (б) делается по полу, а не по потолку.

## Запись «open» бывает ЗАПИСЬЮ, и это не придирка

``spa_core/utils/atomic.py`` — общий дом записи пяти производителей, и первая
редакция числила его ``open`` дверью ЧТЕНИЯ у каждого. Режим спрашивается у
аргумента (:func:`_is_write`): ``"w"``/``"a"``/``"x"``/``"+"`` ⇒ площадка не
читающая. Рядом в том же файле живёт ``atomic_load`` с ``open(path, "r")`` —
настоящая дверь чтения, но путь у неё ПАРАМЕТР: имя входа лежит у ЗВАВШЕГО, и
такая площадка есть :data:`S_CONDUIT`, а не слепое чтение. Считать её непрозрачной
значило бы объявить непрозрачным каждого, кто пользуется общим читателем.

## Ловушка, на которой первая редакция едва не соврала

Калибровка по 16 производителям дала ``walk`` **48 раз** — и почти всё это
``ast.walk``, обход синтаксического дерева, к файлам отношения не имеющий. Дверь
поэтому спрашивается ПОЛНЫМ точечным именем там, где оно есть (``os.walk``,
``os.listdir``, ``subprocess.run``), и коротким — только у методов ``pathlib``,
у которых получатель по имени не разрешается (``read_text``/``glob``). Считать
дверью короткое ``walk`` значило бы объявить каждого разборщика AST читателем
каталогов.

## Чего модуль НЕ делает

Не пишет НИ ОДНОГО файла (чистый читатель: ``--json`` идёт в stdout) — поэтому
двери ``refuse_if_sandbox_leaks`` (ADR-999/1000) ему не требуется, и перепись
песочных входов относит его к роду ``READER``, а не ``DOOR``. Не чинит ни одного
производителя и не пишет дайджестов: выбор между (а) и (б) — предмет следующего
решения, а не этого замера. Не утверждает, что названный вход ИСПОЛЬЗУЕТСЯ:
достижимость чтения есть не исполнение (та же граница, что у
``helper_execution_census``). Не говорит, что ОДИН дайджест закроет род ``ОБЕ``:
он закроет лишь утверждение «данные те же».
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from spa_core.monitoring import edition_remeasure as er

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Роды ПРОИЗВОДИТЕЛЯ — это ответ про ЦЕНУ дайджеста, и их три плюс два исхода
#: «не про цену». Разделять :data:`RUNTIME_ONLY` на «перебор» и «вычисленный
#: путь» вердиктом НЕЛЬЗЯ: цена у них ОДНА (собирать по ходу чтения), а
#: различие печатается площадками. Первая редакция их развела — и объявила
#: «читает чужим процессом» производителя, у которого ни одного ``subprocess``
#: не было вовсе: ярлык назвал не тот механизм.
NAMES = "names_its_inputs"
RUNTIME_ONLY = "input_set_exists_only_at_runtime"
FOREIGN = "reads_through_a_foreign_process"
REFUSED = "not_a_reading_remeasure"
UNMEASURED = "unmeasured"

#: Роды ПЛОЩАДКИ — другой вопрос, и словарь у него свой. ``S_CONDUIT`` — чтение,
#: чей путь пришёл ПАРАМЕТРОМ: имя входа лежит у звавшего, и слепым такое чтение
#: не является.
S_NAMED = "named_path"
S_ENUM = "enumerated_dir"
S_CONDUIT = "conduit_path_comes_from_the_caller"
S_COMPUTED = "computed_path"
S_FOREIGN = "foreign_process"

#: Предел глубины ОСИ СЛЕПОГО МЕСТА (помощники, названные самим производителем).
#: ВХОД, а не константа у вызова. Полное замыкание вердикту не годится по
#: замеру из докстринга: 795 файлов у двух производителей из трёх.
HELPER_DEPTH = 1

BARE_READ_DOORS = frozenset({"open"})
DOTTED_READ_DOORS = frozenset({"io.open", "codecs.open", "os.open"})
#: Методы ``pathlib``: получатель по имени не разрешается, а короткого имени
#: достаточно — ``read_text``/``read_bytes`` в дереве ничего другого не значат.
METHOD_READ_DOORS = frozenset({"read_text", "read_bytes"})

ENUM_METHOD_DOORS = frozenset({"glob", "rglob", "iterdir"})
ENUM_DOTTED_DOORS = frozenset({"os.walk", "os.listdir", "os.scandir"})

FOREIGN_DOORS = frozenset({
    "subprocess.run", "subprocess.Popen", "subprocess.check_output",
    "subprocess.check_call", "subprocess.call",
})

#: Расширения, по которым строковый литерал признаётся ИМЕНЕМ ФАЙЛА. Перечень
#: закрыт намеренно: «литерал похож на путь» без расширения объявило бы именем
#: каждую строку формата.
#: Предел длины строки, которую можно счесть ИМЕНЕМ файла. Замер #1162: самый
#: длинный настоящий путь в поверхности — 58 символов, самый короткий ложный
#: (докстринг) — 1 574. Порог выбран между ними с запасом в оба конца.
_NAME_MAX = 200

NAME_SUFFIXES = (
    ".json", ".jsonl", ".md", ".py", ".txt", ".yaml", ".yml", ".plist",
    ".sh", ".csv", ".log", ".db", ".astro", ".js", ".html", ".toml",
)


class Unmeasured(Exception):
    """Замер не состоялся, и причина названа. Никогда не ноль и не успех."""


@dataclass(frozen=True)
class Site:
    """Одна площадка: чтение, перебор каталога либо чужой процесс."""

    rel: str
    line: int
    door: str
    kind: str
    named: tuple[str, ...] = ()


@dataclass
class Producer:
    """Исход по ОДНОМУ производителю класса."""

    artifact: str
    module: Optional[str]
    kind: str
    rel: Optional[str] = None
    sites: tuple[Site, ...] = ()
    file_names: tuple[str, ...] = ()
    reason: Optional[str] = None


def _dotted(node: ast.AST) -> Optional[str]:
    """Точечное имя выражения (``os.path.join``) либо ``None``."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _looks_like_a_file_name(value: str) -> bool:
    """Строка НАЗЫВАЕТ файл: есть объявленное расширение либо путь с каталогом.

    ОТКАЗ по форме строки стои́т здесь не из аккуратности. Первый прогон по
    живому дереву засчитал ИМЕНЕМ ФАЙЛА весь докстринг модуля — в нём есть
    ``spa_core/utils/atomic.py`` внутри прозы, и признак «содержит слэш»
    срабатывал на абзац в полторы тысячи символов. Поэтому имя обязано быть
    ОДНОЙ строкой без пробелов и короче :data:`_NAME_MAX`: путь в этом дереве
    пробелов не содержит, а проза без них не бывает.
    """
    if not value or len(value) > _NAME_MAX:
        return False
    if any(ch.isspace() for ch in value):
        return False
    return value.endswith(NAME_SUFFIXES) or "/" in value.strip("/")


def _module_level_strings(tree: ast.Module) -> dict[str, str]:
    """Строковые константы модуля — ``REPORT_REL = "data/x.json"``.

    Без них путь ``root / REPORT_REL`` читался бы как вычисленный, хотя имя
    файла выписано в том же файле двадцатью строками выше.
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for tgt in targets:
                    if isinstance(tgt, ast.Name):
                        out[tgt.id] = node.value.value
    return out


def file_names_of(tree: ast.Module) -> tuple[str, ...]:
    """Имена файлов, ВЫПИСАННЫЕ в модуле: литералы и свои строковые константы."""
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and _looks_like_a_file_name(n.value)]
    return tuple(dict.fromkeys(found))


def _is_write(call: ast.Call) -> bool:
    """Режим площадки — ЗАПИСЬ. Спрашивается у аргумента, а не угадывается."""
    modes: list[str] = []
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        if isinstance(call.args[1].value, str):
            modes.append(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                modes.append(kw.value.value)
    return any(ch in m for m in modes for ch in "wax+")


def _path_arg(call: ast.Call) -> Optional[ast.AST]:
    """Выражение ПУТИ у двери.

    У ``open(p, "r")`` это первый позиционный аргумент; у метода
    ``p.read_text()`` — сам получатель, аргументов у него нет вовсе.
    """
    name = call.func.attr if isinstance(call.func, ast.Attribute) else None
    if name in METHOD_READ_DOORS or name in ENUM_METHOD_DOORS:
        return call.func.value  # type: ignore[union-attr]
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg in {"file", "path", "filename"}:
            return kw.value
    return None


def _param_names(tree: ast.Module) -> dict[int, frozenset[str]]:
    """``id(функции) → имена её параметров`` — чтобы отличить проводник от слепого
    чтения: путь-параметр означает, что имя входа названо у ЗВАВШЕГО."""
    out: dict[int, frozenset[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            names = {p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
            out[id(node)] = frozenset(names)
    return out


def _enclosing(tree: ast.Module) -> dict[int, ast.AST]:
    """``id(узла) → ближайшая объемлющая функция`` (или модуль)."""
    out: dict[int, ast.AST] = {}

    def walk(node: ast.AST, owner: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            nxt = child if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            out[id(child)] = nxt
            walk(child, nxt)

    out[id(tree)] = tree
    walk(tree, tree)
    return out


def sites_of(tree: ast.Module, rel: str) -> tuple[Site, ...]:
    """Площадки ОДНОГО файла.

    Дверь спрашивается полным точечным именем там, где оно есть, и коротким —
    только у методов ``pathlib``. Калибровка #1162: короткое ``walk`` дало бы 48
    ложных площадок (``ast.walk``) на 16 производителях.
    """
    consts = _module_level_strings(tree)
    params = _param_names(tree)
    owner = _enclosing(tree)
    out: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        short = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else None)

        if dotted in FOREIGN_DOORS:
            out.append(Site(rel, node.lineno, dotted, S_FOREIGN))
            continue

        is_enum = (dotted in ENUM_DOTTED_DOORS
                   or (short in ENUM_METHOD_DOORS and dotted not in ENUM_DOTTED_DOORS))
        is_read = (dotted in DOTTED_READ_DOORS
                   or (isinstance(node.func, ast.Name) and short in BARE_READ_DOORS)
                   or (isinstance(node.func, ast.Attribute) and short in METHOD_READ_DOORS))
        if not (is_enum or is_read):
            continue
        if is_read and _is_write(node):
            continue

        door = dotted or short or "?"
        if is_enum:
            out.append(Site(rel, node.lineno, door, S_ENUM))
            continue

        expr = _path_arg(node)
        if expr is None:
            out.append(Site(rel, node.lineno, door, S_COMPUTED))
            continue
        named = tuple(dict.fromkeys(
            [n.value for n in ast.walk(expr)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and _looks_like_a_file_name(n.value)]
            + [consts[n.id] for n in ast.walk(expr)
               if isinstance(n, ast.Name) and n.id in consts
               and _looks_like_a_file_name(consts[n.id])]))
        if named:
            out.append(Site(rel, node.lineno, door, S_NAMED, named))
            continue
        host = owner.get(id(node))
        host_params = params.get(id(host), frozenset())
        from_param = any(isinstance(n, ast.Name) and n.id in host_params
                         for n in ast.walk(expr))
        out.append(Site(rel, node.lineno, door,
                        S_CONDUIT if from_param else S_COMPUTED))
    return tuple(out)


def _module_rel(dotted: str, root: pathlib.Path) -> Optional[str]:
    """``spa_core.monitoring.x`` → ``spa_core/monitoring/x.py``, если он ЕСТЬ."""
    base = dotted.replace(".", "/")
    for cand in (f"{base}.py", f"{base}/__init__.py"):
        if (root / cand).is_file():
            return cand
    return None


def _parse(root: pathlib.Path, rel: str) -> ast.Module:
    try:
        return ast.parse((root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise Unmeasured(f"{rel}: файл не разобран ({type(exc).__name__}: {exc})")


def first_party_imports(tree: ast.Module, root: pathlib.Path) -> tuple[str, ...]:
    """Первопартийные модули файла, разрешившиеся в путь ВНУТРИ дерева.

    Имя, не разрешившееся в файл дерева (сторонняя библиотека, рантаймовое
    имя), дугой не становится — это названная граница замера, а не пропуск.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        dotted_list: list[str] = []
        if isinstance(node, ast.Import):
            dotted_list = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            dotted_list = [node.module] + [f"{node.module}.{a.name}"
                                           for a in node.names]
        for dotted in dotted_list:
            rel = _module_rel(dotted, root)
            if rel:
                out.append(rel)
    return tuple(dict.fromkeys(out))


def helper_doors(root: pathlib.Path, seed_rel: str,
                 depth: int = HELPER_DEPTH) -> dict:
    """ОСЬ СЛЕПОГО МЕСТА: двери чтения у помощников, названных САМИМ модулем.

    Вердикта не выносит. Отвечает на один вопрос — «сколько чтений вердикт о
    производителе НЕ ВИДИТ», и предел глубины объявляет.
    """
    seen = {seed_rel}
    frontier = [seed_rel]
    used = 0
    while frontier and used < depth:
        nxt: list[str] = []
        for rel in frontier:
            for dep in first_party_imports(_parse(root, rel), root):
                if dep not in seen:
                    seen.add(dep)
                    nxt.append(dep)
        frontier = nxt
        used += 1
    helpers = sorted(seen - {seed_rel})
    rows: list[Site] = []
    unparsed: list[str] = []
    for rel in helpers:
        try:
            rows.extend(sites_of(_parse(root, rel), rel))
        except Unmeasured as exc:
            unparsed.append(str(exc))
    return {
        "depth": depth,
        "depth_used": used,
        "truncated": bool(frontier),
        "helpers": len(helpers),
        "sites": rows,
        "unparsed": unparsed,
    }


def _module_of_entry(entry: "er.Entry") -> Optional[str]:
    """Точечное имя производителя из шаблона запуска (``-m <модуль>``)."""
    argv = list(entry.argv)
    if "-m" in argv:
        idx = argv.index("-m")
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def measure(root: pathlib.Path | str = _REPO_ROOT, *,
            entries: Optional[Mapping[str, "er.Entry"]] = None,
            helper_depth: int = HELPER_DEPTH) -> dict:
    """ЗАМЕР цены (а) по всем членам класса.

    ``entries=None`` ⇒ таблица читается у соседа В МОМЕНТ ЗОВА, а не связывается
    при определении функции: умолчание-ссылка на изменяемый объявленный дом —
    бомба, измеренная ADR-1023 § 5 (десять проб соседней батареи ушли в красное,
    ничего не измерив).
    """
    root = pathlib.Path(root)
    table = er.ENTRY if entries is None else entries
    if not root.is_dir():
        raise Unmeasured(f"дерева нет по пути {root}")
    if not table:
        raise Unmeasured("таблица членов класса ПУСТА — цена считалась бы ни о ком")

    producers: list[Producer] = []
    blind: list[dict] = []
    for artifact in sorted(table):
        entry = table[artifact]
        if entry.refusal:
            producers.append(Producer(artifact, None, REFUSED, reason=entry.refusal))
            continue
        dotted = _module_of_entry(entry)
        rel = _module_rel(dotted, root) if dotted else None
        if not rel:
            producers.append(Producer(
                artifact, dotted, UNMEASURED,
                reason=(f"производитель не разрешился в файл дерева: "
                        f"{dotted or 'имени нет в шаблоне запуска'}")))
            continue
        try:
            tree = _parse(root, rel)
        except Unmeasured as exc:
            producers.append(Producer(artifact, dotted, UNMEASURED, rel,
                                      reason=str(exc)))
            continue
        sites = sites_of(tree, rel)
        names = file_names_of(tree)
        own_kinds = {s.kind for s in sites}
        reason: Optional[str] = None
        if S_FOREIGN in own_kinds:
            # Хуже всех: часть входов — не файлы, и дайджест их не ухватит
            # НИКАКОЙ записью читателя.
            kind: str = FOREIGN
        elif own_kinds & {S_ENUM, S_COMPUTED}:
            kind = RUNTIME_ONLY
        elif names:
            # Остались только названные пути и проводники, а имена выписаны —
            # список входов у производителя уже есть.
            kind = NAMES
        else:
            kind = UNMEASURED
            reason = ("ни одного имени файла в своём модуле и ни одной "
                      "непроводниковой двери — вердикт о НЁМ вынести нечем "
                      "(читает целиком через помощников)")
        producers.append(Producer(artifact, dotted, kind, rel, sites, names, reason))
        try:
            blind.append({"artifact": artifact,
                          **_blind_doc(helper_doors(root, rel, helper_depth))})
        except Unmeasured as exc:
            blind.append({"artifact": artifact, "unmeasured": str(exc)})

    return {
        "schema": "producer-input-awareness/2",
        "root": str(root),
        "helper_depth": helper_depth,
        "members": len(table),
        "producers": [_as_doc(p) for p in producers],
        "counts": _counts(producers),
        "blind_spot": blind,
        "shared_doors": _shared_doors(blind),
    }


def _blind_doc(doc: Mapping) -> dict:
    sites: Sequence[Site] = doc["sites"]  # type: ignore[assignment]
    return {
        "helpers": doc["helpers"],
        "depth": doc["depth"],
        "truncated": doc["truncated"],
        "read_sites": len([s for s in sites if s.kind != S_FOREIGN]),
        "foreign_sites": len([s for s in sites if s.kind == S_FOREIGN]),
        "files": sorted({s.rel for s in sites}),
        "unparsed": list(doc["unparsed"]),
    }


def _as_doc(p: Producer) -> dict:
    return {
        "artifact": p.artifact,
        "module": p.module,
        "rel": p.rel,
        "kind": p.kind,
        "file_names": list(p.file_names[:12]),
        "file_names_total": len(p.file_names),
        "reason": p.reason,
        "sites": [{"rel": s.rel, "line": s.line, "door": s.door,
                   "kind": s.kind, "named": list(s.named)} for s in p.sites],
    }


def _counts(producers: Sequence[Producer]) -> dict[str, int]:
    out = {k: 0 for k in (NAMES, RUNTIME_ONLY, FOREIGN, REFUSED, UNMEASURED)}
    for p in producers:
        out[p.kind] = out.get(p.kind, 0) + 1
    return out


def _shared_doors(blind: Sequence[Mapping]) -> list[dict]:
    """Файлы-помощники с дверями, общие для ДВУХ и более производителей.

    Это и есть рычаг цены (а): если чтения сходятся в несколько общих
    помощников, дайджест ставится у них ОДИН раз, а не у каждого производителя.
    """
    owners: dict[str, set[str]] = {}
    for row in blind:
        for rel in row.get("files") or ():
            owners.setdefault(rel, set()).add(str(row.get("artifact")))
    rows = [{"rel": rel, "producers": sorted(arts), "n": len(arts)}
            for rel, arts in owners.items() if len(arts) > 1]
    return sorted(rows, key=lambda r: (-r["n"], r["rel"]))


def verdict(doc: Mapping) -> str:
    """``measured_zero`` · ``price_named`` · ``unmeasured``."""
    counts = doc.get("counts") or {}
    if counts.get(UNMEASURED):
        return "unmeasured"
    if counts.get(RUNTIME_ONLY) or counts.get(FOREIGN):
        return "price_named"
    return "measured_zero"


EXIT_CODES = {"measured_zero": 0, "price_named": 1, "unmeasured": 2}

_KIND_RU = {
    NAMES: "НАЗЫВАЕТ входы у себя (дайджест ≈ несколько строк)",
    RUNTIME_ONLY: "набор входов существует ТОЛЬКО В ПРОГОНЕ — перебор "
                  "каталога либо вычисленный путь (дайджест надо СОБИРАТЬ)",
    FOREIGN: "читает ЧУЖИМ ПРОЦЕССОМ (часть входов — не файлы вовсе)",
    REFUSED: "перемер НЕ ЧИТАЮЩИЙ (причина у таблицы соседа)",
    UNMEASURED: "НЕ ИЗМЕРЕНО",
}


def format_report(doc: Mapping, *, verbose: bool = False) -> str:
    counts = doc.get("counts") or {}
    v = verdict(doc)
    lines = [
        f"цена варианта (а) заказа G1012 — знает ли производитель, что читает "
        f"(дерево {doc.get('root')})",
        f"  членов класса: {doc.get('members')} · вердикт выносится по СВОЕМУ "
        f"модулю производителя (замыкание 795 файлов вердикту не годится)",
    ]
    for kind in (NAMES, RUNTIME_ONLY, FOREIGN, REFUSED, UNMEASURED):
        lines.append(f"  {counts.get(kind, 0):>3}  {_KIND_RU[kind]}")
    floor = counts.get(RUNTIME_ONLY, 0) + counts.get(FOREIGN, 0)
    lines.append(
        f"  ПОЛ цены: НЕ МЕНЬШЕ {floor} производител(ь/я/ей) не называют входы "
        f"у себя · ПОТОЛОК дешёвых: НЕ БОЛЬШЕ {counts.get(NAMES, 0)} "
        f"(дверь в помощнике своему модулю не видна)")

    blind = doc.get("blind_spot") or []
    hidden = sum((row.get("read_sites") or 0) for row in blind)
    foreign = sum((row.get("foreign_sites") or 0) for row in blind)
    trunc = [row["artifact"] for row in blind if row.get("truncated")]
    lines.append(
        f"  СЛЕПОЕ МЕСТО (помощники глубины {doc.get('helper_depth')}): "
        f"площадок чтения {hidden}, чужих процессов {foreign}; обрезано у "
        f"{len(trunc)} из {len(blind)} — вердикт их НЕ учитывает намеренно")
    shared = doc.get("shared_doors") or []
    lines.append(f"  РЫЧАГ: общих помощников с дверями (≥2 производителей): "
                 f"{len(shared)}")
    for row in shared[:8]:
        lines.append(f"      • {row['rel']} — у {row['n']}: "
                     f"{', '.join(row['producers'][:4])}"
                     + (" …" if len(row['producers']) > 4 else ""))

    for p in doc.get("producers") or []:
        if p["kind"] == NAMES and not verbose:
            continue
        lines.append(f"  [{p['kind']}] {p['artifact']}"
                     + (f" — {p['reason']}" if p.get("reason") else ""))
        shown = [s for s in p["sites"]
                 if verbose or s["kind"] in (S_ENUM, S_FOREIGN, S_COMPUTED)]
        for s in shown[:4]:
            named = (" ← " + ", ".join(s["named"][:3])) if s["named"] else ""
            lines.append(f"      {s['rel']}:{s['line']} {s['door']} "
                         f"({s['kind']}){named}")
        if len(shown) > 4:
            lines.append(f"      … и ещё {len(shown) - 4} площадок(а)")
        if p["kind"] == NAMES and p["file_names_total"]:
            lines.append(f"      имён файлов выписано: {p['file_names_total']} "
                         f"(напр. {', '.join(p['file_names'][:3])})")
    lines.append(f"  вердикт: {v} (код {EXIT_CODES[v]})")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ — ни дайджестов, ни правок "
                 "производителей (выбор между (а) и (б) — отдельное решение)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="цена варианта (а) заказа G1012: знает ли производитель "
                    "офиса, что он читает")
    ap.add_argument("--root", default=str(_REPO_ROOT),
                    help="дерево, в котором меряем (умолчание — своё)")
    ap.add_argument("--helper-depth", type=int, default=HELPER_DEPTH,
                    help="предел глубины ОСИ СЛЕПОГО МЕСТА (ВХОД)")
    ap.add_argument("--all", action="store_true",
                    help="печатать КАЖДОГО производителя и КАЖДУЮ площадку")
    ap.add_argument("--json", action="store_true", help="документ замера в stdout")
    args = ap.parse_args(argv)
    try:
        doc = measure(args.root, helper_depth=args.helper_depth)
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
