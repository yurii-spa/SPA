#!/usr/bin/env python3
"""Кто читает ТРЁХИСХОДНУЮ дверь ДВУМЯ исходами — перепись класса ADR-869 (заказ G869 п. 10).

**Зачем (цикл #987, 2026-10-30).** ADR-869 нашёл и закрыл РОВНО ОДИН экземпляр:
`scripts/verify_publication.py` объявляет три исхода (`PASS, FAIL, NOT_MEASURED = 0, 1, 2`),
а его читатель `scripts/safe_site_push.main` сводил оба ненулевых в один ответ — и на
«ворота не ответили» звал ВЛАДЕЛЬЦА подписать витрину, которой никто не мерил. Сам ADR
запретил объявлять класс закрытым по этой находке:

> «Перепись „кто ещё читает трёхисходную дверь двумя исходами“ НЕ СДЕЛАНА и уходит
> заказом G869 п. 1: называть её закрытой по одному найденному экземпляру было бы тем же
> выводом по населению из одного.»

Этот прибор и есть та перепись. Он НИЧЕГО не чинит — он только ЧИТАЕТ дерево и называет
поимённо каждое место, где исход «НЕ ИЗМЕРЕНО» неотличим от исхода «отказано».

## Две оси, и ни одна не заменяет другую

| ось | вопрос | чего НЕ знает |
|---|---|---|
| `census` (статическая) | где в дереве стоит читатель, сводящий исходы? | исполняется ли он |
| `drive_exemplar` (живая) | различает ли НАСТОЯЩИЙ читатель два исхода двери? | есть ли у него население |

Статическая ось даёт ВЕРХНИЙ край (место есть — исполнение не измерено; урок ADR-674:
дорога есть достижимость, а не исполнение). Живая ось отвечает на другой вопрос: что
различение в этом дереве ДОСТИЖИМО, то есть находка статической оси — дефект читателя, а
не свойство языка. Склеивать их в одно число запрещено.

## Что здесь считается ДВЕРЬЮ (мера тугая намеренно)

Дверь — модуль, который ОБЪЯВИЛ СВОЙ СЛОВАРЬ В КОДЕ: группа целочисленных
модульных констант (совместное присваивание `A, B, C = 0, 1, 2` либо общий префикс
`EXIT_` / `RC_` / `CODE_` / `STATUS_`), в которой **≥3 различных значения** и хотя бы одно
имя говорит «не измерено» (`UNMEASURED` / `NOT_MEASURED`).

**Словарь, объявленный только ПРОЗОЙ, дверью здесь не считается — и это НАЗВАНО,
а не умолчано** (`doors_declared_in_prose_only`). Первая редакция прибора ловила
словарь регуляркой по docstring и дала 20 дверей, из которых у `import_time_anchor_bombs.py`
«не измерено» вышло кодом **0**, а у `apy_provenance_census.py` — кодом **1**: обе цифры
прибор выдумал из прозы, стоявшей рядом. Шумная перепись хуже пустой — по ней нельзя
ни чинить, ни считать. Поэтому мера тугая, а цена туготы (пропущенные двери) печатается
числом, а не прячется.

## Что здесь считается ЧИТАТЕЛЕМ

Вызов двери ПОДПРОЦЕССОМ (`subprocess.run/call/check_call/check_output/Popen`), у которого
среди аргументов стоит строка, кончающаяся на имя файла двери. Читатель судится по
**РАЗБИЕНИЮ**, которое он наводит на словарь двери, а не по словам и не по наличию
`if`: внутри объемлющей функции собираются все сторожа над кодом возврата
(`== k`, `!= k`, `in (…)`, `if rc:`, `check=True`) и считается, в какой КЛАСС разбиения
попадает каждое значение словаря.

| вердикт | условие | почему это дефект |
|---|---|---|
| `fail_open` | «не измерено» лежит в одном классе с **нулём** | гейт не ответил, а читатель пошёл дальше (инв. #2) |
| `collapsed` | «не измерено» лежит в одном классе с ненулевым НЕ-«не измерено» | «отказано» и «не ответило» — один ответ (инв. #17, ADR-869) |
| `ignored` | код возврата не читается вовсе | то же, что `fail_open`, но без единого сторожа |
| `distinguishes` | «не измерено» в своём классе | эталон |
| `unmeasured` | разобрать не удалось | третий исход у самого прибора |

**`check=True` разбиением НЕ является**: исключение `CalledProcessError` одно на все
ненулевые коды, и `returncode` внутри него читает уже обработчик — если он читает.
Поэтому такой вызов классифицируется по сторожам, найденным у обработчика, а при их
отсутствии — `collapsed`, и причина печатается.

## Чего перепись НЕ знает (названо, а не умолчано)

* **Оболочка и воркфлоу.** `*.sh` и `.github/workflows/*.yml` зовут те же двери; их
  разбор здесь НЕ сделан, и число таких мест печатается отдельно со вердиктом
  `unmeasured` — не нулём и не «чисто».
* **Дверь-функция.** Читатель, вызывающий дверь не подпроцессом, а ИМПОРТОМ, судится
  по возвращаемому значению, а не по коду возврата; этой оси здесь нет, и число
  импортирующих мест тоже печатается как `unmeasured`.
* **Исполнение.** Статическая ось говорит «место есть», а не «через него ходят».

Код возврата CLI: ``0`` — ни одного `fail_open`/`collapsed`/`ignored` ·
``1`` — находки НАЗВАНЫ · ``2`` — НЕ ИЗМЕРЕНО с названной причиной.

> Прибор сам является такой дверью (словарь ниже объявлен в коде), поэтому он попадает
> в собственную перепись — и его читатели обязаны различать `RC_UNMEASURED`. Это не
> курьёз: дверь, не выдерживающая своей же меры, меру и опровергает.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: Словарь исходов CLI. Объявлен ОДНОЙ группой — ровно та форма, которую прибор ищет.
RC_CLEAN, RC_FINDING, RC_UNMEASURED = 0, 1, 2

#: Вердикты читателя (закрытый перечень).
FAIL_OPEN = "fail_open"
COLLAPSED = "collapsed"
IGNORED = "ignored"
DISTINGUISHES = "distinguishes"
RESIDUAL_SHARED = "residual_shared"
OTHER_CHANNEL = "other_channel"
UNMEASURED = "unmeasured"

#: Вердикты, которые и есть находка переписи.
FINDING_VERDICTS = (FAIL_OPEN, COLLAPSED, IGNORED)

#: Имя константы, означающей «наблюдения нет» (инв. #17).
_UNMEASURED_NAME = re.compile(r"(UNMEASURED|UN_MEASURED|NOT_MEASURED|NOTMEASURED)")

#: Префиксы, под которыми в этом дереве живут словари кодов возврата.
_CODE_PREFIX = re.compile(r"^_?(EXIT|RC|CODE|EXITCODE|STATUS)_")

#: Запуск подпроцесса.
_SUBPROCESS_CALLS = {"run", "call", "check_call", "check_output", "Popen"}

#: Каталоги, которые перепись не разбирает: тесты говорят о СЦЕНЕ, а не о проводке.
_SKIP_DIR_PARTS = ("/tests/", "/node_modules/", "/.git/", "/site-packages/")


def _is_int_const(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool))


# ── ось 1: двери ─────────────────────────────────────────────────────────────


def declared_groups(tree: ast.Module) -> list[dict]:
    """Группы модульных целочисленных констант — КАК ОБЪЯВЛЕНО В КОДЕ.

    Две формы, и обе суть одно утверждение «вот мой словарь»: совместное
    присваивание кортежем и общий префикс имени.
    """
    out: list[dict] = []
    by_prefix: dict[str, dict[str, int]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        for target in node.targets:
            if (isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple)
                    and len(target.elts) == len(value.elts)):
                group = {t.id: v.value for t, v in zip(target.elts, value.elts)
                         if isinstance(t, ast.Name) and _is_int_const(v)}
                if group and len(group) == len(target.elts):
                    out.append({"form": "tuple", "names": group})
            elif isinstance(target, ast.Name) and _is_int_const(value):
                match = _CODE_PREFIX.match(target.id)
                if match:
                    by_prefix.setdefault(match.group(0), {})[target.id] = value.value
    out += [{"form": f"prefix:{p}", "names": g} for p, g in sorted(by_prefix.items())]
    return out


def door_of(path: Path, source: str) -> "dict | None":
    """Дверь или ``None``. Дверь = объявленный в коде словарь ≥3 исходов с «не измерено»."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    best: "dict | None" = None
    for group in declared_groups(tree):
        names = group["names"]
        unmeasured = {v for k, v in names.items() if _UNMEASURED_NAME.search(k)}
        if not unmeasured or len(set(names.values())) < 3:
            continue
        candidate = {"form": group["form"], "alphabet": dict(sorted(names.items())),
                     "codes": sorted(set(names.values())),
                     "unmeasured": sorted(unmeasured)}
        # Самая широкая группа и есть словарь двери: узкая — её подмножество.
        if best is None or len(candidate["codes"]) > len(best["codes"]):
            best = candidate
    return best


def _prose_only_door(source: str) -> bool:
    """Словарь объявлен ПРОЗОЙ: docstring называет «не измерено» рядом с цифрой."""
    try:
        doc = ast.get_docstring(ast.parse(source)) or ""
    except SyntaxError:
        return False
    if not doc:
        return False
    pat = re.compile(r"(?:код\w*\s*)?(\d)\s*[ \-—·:=>]+\s*[^\n]{0,40}?"
                     r"(НЕ ИЗМЕРЕНО|НЕ ИЗМЕРЕН|не измерено|NOT MEASURED|NOT_MEASURED)",
                     re.IGNORECASE)
    pat_rev = re.compile(r"(НЕ ИЗМЕРЕНО|не измерено|NOT MEASURED)[^\n]{0,30}?код\w*[^\n]{0,10}?(\d)",
                         re.IGNORECASE)
    return bool(pat.search(doc) or pat_rev.search(doc))


# ── ось 1b: читатели ─────────────────────────────────────────────────────────


class _Partition:
    """Разбиение целых, наведённое сторожами читателя над кодом возврата.

    Класс значения — множество сторожей, которые на нём срабатывают, плюс признак
    «ни один» (остаточный `else`). Два значения в ОДНОМ классе читатель различить не
    может — ровно это и есть предмет переписи.
    """

    def __init__(self) -> None:
        self.eq: set[int] = set()      # сторожа `== k` / `in (k, …)`
        self.zero_split = False        # сторожа `!= 0` / `if rc:` / `not rc`
        self.has_guard = False

    def note_eq(self, value: int) -> None:
        self.eq.add(value)
        self.has_guard = True

    def note_zero_split(self) -> None:
        self.zero_split = True
        self.has_guard = True

    def class_of(self, value: int) -> str:
        if value in self.eq:
            return f"=={value}"
        if self.zero_split:
            return "==0" if value == 0 else "!=0"
        return "else"

    def classes(self, codes: "list[int]") -> int:
        return len({self.class_of(c) for c in codes})


def _enclosing(tree: ast.Module, node: ast.AST) -> ast.AST:
    """Объемлющая функция вызова (или модуль, если вызов на верхнем уровне)."""
    best: ast.AST = tree
    best_span = -1
    for cand in ast.walk(tree):
        if not isinstance(cand, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = getattr(cand, "lineno", None)
        end = getattr(cand, "end_lineno", None)
        if start is None or end is None:
            continue
        if start <= node.lineno <= end:
            span = end - start
            if best_span < 0 or span < best_span:
                best, best_span = cand, span
    return best


def _literal_strings(node: ast.AST) -> list[str]:
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _assignments(scope: ast.AST) -> "list[tuple[list[str], ast.expr]]":
    """Присваивания области ОДНИМ обходом: (имена-цели, правая часть)."""
    out: list[tuple[list[str], ast.expr]] = []
    for node in ast.walk(scope):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                out.append((names, value))
    return out


def _name_literals(scope: ast.AST,
                   assignments: "list[tuple[list[str], ast.expr]] | None" = None,
                   seed: "dict[str, list[str]] | None" = None
                   ) -> "dict[str, list[str]]":
    """Имя → строковые литералы, из которых его значение собрано В ЭТОЙ области.

    Путь к двери почти никогда не стоит в самом вызове: его собирают строкой выше
    (`_vp = os.path.join(base, "scripts", "verify_publication.py")`) или модульной
    константой (`_VERIFY = _REPO_ROOT / "scripts" / "verify_publication.py"`). Искать
    литерал ТОЛЬКО внутри вызова значило бы объявить класс пустым: первая редакция этого
    прибора так и ответила — «читателей 0» при трёх живых читателях в одном файле.
    """
    assigns = _assignments(scope) if assignments is None else assignments
    # Семя — таблица МОДУЛЬНОГО уровня: путь к двери чаще всего лежит в модульной
    # константе (`_VERIFY = ROOT / "scripts" / "verify_publication.py"`), а команда
    # собирается внутри функции (`cmd = [sys.executable, str(_VERIFY), …]`). Без семени
    # цепочка рвётся на границе области, и читатель, который исходы РАЗЛИЧАЕТ, в
    # перепись не попадает вовсе — именно так первая редакция дала «различают: 0».
    out: dict[str, list[str]] = {k: list(v) for k, v in (seed or {}).items()}
    borrows: list[tuple[list[str], list[str]]] = []
    for names, value in assigns:
        lits = _literal_strings(value)
        refs = [sub.id for sub in ast.walk(value) if isinstance(sub, ast.Name)]
        for name in names:
            if lits:
                out.setdefault(name, []).extend(lits)
        borrows.append((names, refs))
    _propagate(borrows, out)
    return out


def _propagate(borrows: "list[tuple[list[str], list[str]]]",
               table: "dict[str, list[str]]") -> None:
    """Протащить литералы по цепочке присваиваний ДО НЕПОДВИЖНОЙ ТОЧКИ.

    `guard = probe` литерала не несёт, а дверь зовут именно через `guard` — так первая
    редакция прибора не увидела ЕДИНСТВЕННОГО читателя, который исходы РАЗЛИЧАЕТ, и
    перепись сказала «различают: 0». Та же неподвижная точка, что у разбора якоря
    времени (`spa_core/tests/_injected_clock.py`): происхождение значения, а не форма
    правой части. Предел витков — против цикла `a = b; b = a`, а не экономия: цепочек
    длиннее восьми в этом дереве нет (замер 30.10).
    """
    for _ in range(8):
        changed = False
        for names, refs in borrows:
            borrowed: list[str] = []
            for ref in refs:
                if ref not in names:
                    borrowed.extend(table.get(ref, ()))
            if not borrowed:
                continue
            for name in names:
                have = table.setdefault(name, [])
                fresh = [lit for lit in borrowed if lit not in have]
                if fresh:
                    have.extend(fresh)
                    changed = True
        if not changed:
            return


def _name_literals_module(tree: ast.Module) -> "dict[str, list[str]]":
    """То же, но только для ВЕРХНЕГО уровня модуля (`_VERIFY = ROOT / "scripts" / …`)."""
    assigns: list[tuple[list[str], ast.expr]] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                assigns.append((names, value))
    return _name_literals(tree, assignments=assigns)


def _door_hits(call: ast.Call, by_basename: "dict[str, str]",
               *scopes: "dict[str, list[str]]") -> "set[str]":
    """Какие двери зовёт этот вызов: по литералам самого вызова и по именам, что он берёт."""
    hits = {by_basename[Path(s).name] for s in _literal_strings(call)
            if Path(s).name in by_basename}
    for sub in ast.walk(call):
        if not isinstance(sub, ast.Name):
            continue
        for table in scopes:
            for lit in table.get(sub.id, ()):
                name = Path(lit).name
                if name in by_basename:
                    hits.add(by_basename[name])
    return hits


def _subprocess_calls(tree: ast.Module) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SUBPROCESS_CALLS):
            out.append(node)
    return out


def _check_true(call: ast.Call) -> bool:
    return any(kw.arg == "check" and isinstance(kw.value, ast.Constant)
               and kw.value.value is True for kw in call.keywords)


def _captures_output(call: ast.Call) -> bool:
    """Перехвачен ли вывод двери: тогда её вердикт может ехать полем, а не кодом."""
    if isinstance(call.func, ast.Attribute) and call.func.attr == "check_output":
        return True
    for kw in call.keywords:
        if kw.arg == "capture_output" and isinstance(kw.value, ast.Constant) \
                and kw.value.value is True:
            return True
        if kw.arg in ("stdout", "stderr"):
            return True
    return False


def _names_unmeasured(scope: ast.AST) -> bool:
    """Назвал ли читатель «не измерено» СВОИМ именем (константой/полем)."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and _UNMEASURED_NAME.search(node.id):
            return True
        if isinstance(node, ast.Attribute) and _UNMEASURED_NAME.search(node.attr):
            return True
    return False


def _note(part: "_Partition", value: int) -> None:
    """Сторож `== k` НЕ делит ноль от остатка, если k ≠ 0.

    Читатель, знающий только `if rc == 1: отказ`, на всё прочее идёт ДАЛЬШЕ — и код
    «не измерено» уезжает по дороге УСПЕХА. Первая редакция прибора считала, что
    `== 1` заодно отделяет ноль, и называла такого читателя различающим: сцена
    `READER_FAIL_OPEN` в батарее — тот самый контроль, который это и вскрыл.
    """
    if value == 0:
        part.note_zero_split()
    else:
        part.note_eq(value)


def _collect_partition(scope: ast.AST) -> _Partition:
    """Сторожа над кодом возврата внутри области видимости читателя.

    Мера НАМЕРЕННО грубая в сторону находки: сторож `== k` учитывается независимо от
    того, над какой переменной он стоит. Назвать `collapsed` читателя, который на самом
    деле различает, — ошибка ВИДИМАЯ (её опровергнет взгляд в файл); пропустить
    сводящего читателя — ошибка молчаливая, а молчаливых мы и ищем.
    """
    part = _Partition()
    rc_like = re.compile(r"(returncode|^rc$|_rc$|^rc_|code$|^code_|outcome|status|verdict)",
                         re.IGNORECASE)

    def names_in(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and rc_like.search(sub.id):
                return True
            if isinstance(sub, ast.Attribute) and rc_like.search(sub.attr):
                return True
            if isinstance(sub, ast.Subscript):
                return True
        return False

    for node in ast.walk(scope):
        if isinstance(node, ast.Compare) and names_in(node.left):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and _is_int_const(comp):
                    _note(part, comp.value)
                elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(
                        comp, (ast.Tuple, ast.List, ast.Set)):
                    for elt in comp.elts:
                        if _is_int_const(elt):
                            _note(part, elt.value)
        elif isinstance(node, ast.If) and names_in(node.test) and not isinstance(
                node.test, ast.Compare):
            part.note_zero_split()
    return part


def classify_reader(scope: ast.AST, call: ast.Call, door: dict) -> dict:
    """Вердикт читателя по РАЗБИЕНИЮ словаря двери, а не по словам.

    Сила утверждения РАЗНАЯ, и прибор её не завышает. Читатель, у которого над
    ненулевым кодом нет НИ ОДНОГО сторожа `== k`, умеет ровно два ответа — «ноль» и
    «не ноль», — и тогда «отказано» от «не ответило» он не отличает НИКОГДА: это
    дословный дефект ADR-869, вердикт ``collapsed``. Читатель, который какой-то
    ненулевой код выделил явно и оставил остаточный класс (`else`), построил этот
    класс НАМЕРЕННО — и читает ли он остаток как «не измерено» или как «отказ», эта
    ось НЕ ЗНАЕТ: вердикт ``residual_shared``, и он НЕ находка. Считать его находкой
    значило бы выдать неизмеренное за дефект — ровно то, против чего весь класс.
    """
    part = _collect_partition(scope)
    codes = door["codes"]
    unmeasured = door["unmeasured"]
    others = [c for c in codes if c not in unmeasured]
    if not part.has_guard:
        # Код возврата — не единственный канал вердикта. Дверь, зовомая с `--json` и
        # перехваченным выводом, отвечает ПОЛЕМ, и читатель, который сам назвал у себя
        # «не измерено» (своя константа), три исхода ЗАВЕДОМО моделирует: сказать про
        # него «код не читает» формально верно и по сути ложно. Это ровно читатель,
        # ПОЧИНЕННЫЙ ADR-869, и объявить его дефектным значило бы опровергнуть сам ADR
        # его же мерой. Поэтому — свой исход, НЕ находка, и канал НАЗВАН неизмеренным.
        if _captures_output(call) and _names_unmeasured(scope):
            return {"verdict": OTHER_CHANNEL, "classes": 1, "clash": [],
                    "reason": ("вердикт двери читается не кодом возврата, а полем "
                               "перехваченного вывода; читатель назвал «не измерено» "
                               "своей константой — различает ли он исходы, ЭТОЙ осью "
                               "НЕ ИЗМЕРЕНО")}
        reason = ("код возврата двери не читается ни одним сторожем"
                  + (" (check=True: исключение одно на все ненулевые)" if _check_true(call) else ""))
        return {"verdict": IGNORED, "reason": reason, "classes": 1, "clash": []}
    classes = {c: part.class_of(c) for c in codes}
    for u in unmeasured:
        if 0 in codes and classes.get(0) == classes.get(u):
            return {"verdict": FAIL_OPEN, "classes": part.classes(codes), "clash": [0],
                    "reason": (f"«не измерено» ({u}) и успех (0) попадают в один класс "
                               f"«{classes[u]}» — гейт не ответил, а читатель пошёл дальше")}
    clash: list[int] = []
    for u in unmeasured:
        clash += [c for c in others if c != 0 and classes.get(c) == classes.get(u)]
    clash = sorted(set(clash))
    if not clash:
        return {"verdict": DISTINGUISHES, "classes": part.classes(codes), "clash": [],
                "reason": f"«не измерено» {unmeasured} в своём классе «{classes[unmeasured[0]]}»"}
    if part.eq:
        return {"verdict": RESIDUAL_SHARED, "classes": part.classes(codes), "clash": clash,
                "reason": (f"читатель выделил {sorted(part.eq)} явно, а «не измерено» "
                           f"{unmeasured} и {clash} делят ОСТАТОЧНЫЙ класс "
                           f"«{classes[unmeasured[0]]}»; читает ли он остаток как «не "
                           f"измерено» — этой осью НЕ ИЗМЕРЕНО")}
    return {"verdict": COLLAPSED, "classes": part.classes(codes), "clash": clash,
            "reason": (f"над ненулевым кодом нет ни одного сторожа «== k»: «не измерено» "
                       f"({unmeasured}) неотличимо от {clash} — у читателя ровно два "
                       f"ответа, «ноль» и «не ноль»")}


# ── перепись ─────────────────────────────────────────────────────────────────


def _py_files(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*.py")):
        rel = "/" + path.relative_to(root).as_posix()
        if any(part in rel for part in _SKIP_DIR_PARTS):
            continue
        out.append(path)
    return out


def run_census(root: "Path | str | None" = None) -> dict:
    """Перепись класса. Только ЧИТАЕТ дерево; ничего не правит и в сеть не ходит."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    if not root.is_dir():
        return {"verdict": UNMEASURED, "reason": f"каталога дерева нет: {root}"}

    sources: dict[Path, str] = {}
    unreadable: list[str] = []
    for path in _py_files(root):
        try:
            sources[path] = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{path.relative_to(root).as_posix()}: {type(exc).__name__}")

    doors: dict[str, dict] = {}
    prose_only: list[str] = []
    for path, src in sources.items():
        rel = path.relative_to(root).as_posix()
        door = door_of(path, src)
        if door:
            doors[rel] = door
        elif _prose_only_door(src):
            prose_only.append(rel)

    by_basename = {Path(rel).name: rel for rel in doors}

    readers: list[dict] = []
    unparsed: list[str] = []
    for path, src in sources.items():
        rel = path.relative_to(root).as_posix()
        # Файл, не называющий НИ ОДНОЙ двери, читателем быть не может: дверь зовут по
        # имени файла. Отсев до разбора — вопрос цены, а не меры (замер: 9 817 файлов).
        if not any(name in src for name in by_basename):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            unparsed.append(f"{rel}: SyntaxError line {exc.lineno}")
            continue
        module_names = _name_literals_module(tree)
        scope_tables: dict[int, dict] = {}
        for call in _subprocess_calls(tree):
            scope = _enclosing(tree, call)
            table = scope_tables.get(id(scope))
            if table is None:
                table = scope_tables[id(scope)] = _name_literals(
                    scope, seed=module_names)
            hits = _door_hits(call, by_basename, table, module_names)
            for door_rel in sorted(hits):
                if door_rel == rel:
                    continue  # дверь, зовущая себя, читателем себя не является
                res = classify_reader(scope, call, doors[door_rel])
                readers.append({
                    "reader": rel, "line": call.lineno,
                    "scope": getattr(scope, "name", "<module>"),
                    "door": door_rel, "door_codes": doors[door_rel]["codes"],
                    "door_unmeasured": doors[door_rel]["unmeasured"],
                    **res})

    # Поверхности, которых эта перепись НЕ разбирает — числом, а не нулём.
    shell_sites, workflow_sites, import_sites = 0, 0, 0
    for pattern, bump in (("*.sh", "shell"), ("*.yml", "workflow"), ("*.yaml", "workflow")):
        for path in root.rglob(pattern):
            rel = "/" + path.relative_to(root).as_posix()
            if any(part in rel for part in _SKIP_DIR_PARTS):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hit = sum(1 for name in by_basename if name in text)
            if bump == "shell":
                shell_sites += hit
            else:
                workflow_sites += hit
    door_modules = {Path(rel).stem for rel in doors}
    for path, src in sources.items():
        rel = path.relative_to(root).as_posix()
        if rel in doors:
            continue
        for stem in door_modules:
            if re.search(rf"^\s*(from\s+\S*\b{re.escape(stem)}\b|import\s+\S*\b{re.escape(stem)}\b)",
                         src, re.MULTILINE):
                import_sites += 1

    counts = {v: sum(1 for r in readers if r["verdict"] == v)
              for v in (FAIL_OPEN, COLLAPSED, IGNORED, DISTINGUISHES,
                        RESIDUAL_SHARED, OTHER_CHANNEL, UNMEASURED)}
    findings = [r for r in readers if r["verdict"] in FINDING_VERDICTS]
    return {
        "verdict": UNMEASURED if (unparsed or unreadable) and not readers else (
            FAIL_OPEN if counts[FAIL_OPEN] else (COLLAPSED if findings else DISTINGUISHES)),
        "root": str(root),
        "door_count": len(doors),
        "doors": doors,
        "doors_declared_in_prose_only": sorted(prose_only),
        "reader_count": len(readers),
        "readers": sorted(readers, key=lambda r: (r["reader"], r["line"])),
        "findings": sorted(findings, key=lambda r: (FINDING_VERDICTS.index(r["verdict"]),
                                                    r["reader"], r["line"])),
        "counts": counts,
        "not_measured_surfaces": {
            "shell_sites": shell_sites,
            "workflow_sites": workflow_sites,
            "import_sites": import_sites,
            "unreadable_files": unreadable,
            "unparsed_files": unparsed,
        },
    }


# ── ось 2: живой эталон ──────────────────────────────────────────────────────

DRIVE_DISTINGUISHES = "distinguishes"
DRIVE_CONFLATES = "conflates"
DRIVE_UNMEASURED = "unmeasured"

_STUB_DOOR = '''#!/usr/bin/env python3
"""Заглушка ДВЕРИ: отвечает объявленным кодом. Читатель — настоящий."""
import json, sys
CODE = {code}
print(json.dumps({{"state": "stub", "detail": "сцена эталона", "touching": []}}))
sys.exit(CODE)
'''


def exemplar_verdict(refused: dict, silent: dict) -> dict:
    """Вердикт о двух сценах эталона — ОТДЕЛЬНО от их подъёма, чтобы его можно было
    проверить контролем, а не только живым деревом.

    Замер мутациями 30.10: подмена всей этой проверки на `ok = True` ВЫЖИЛА. Сцены в
    живом дереве отвечают верно, поэтому утверждения о ЧИСЛАХ держались, а утверждение о
    РОДЕ исхода не держало ничего — и проба приёмки, которая решает по `kind`, прошла бы
    на СВОДЯЩЕМ читателе. Это fail-OPEN у пробы, и закрыть его можно только швом: сцену
    с неверным читателем в живом дереве взять негде.

    Три исхода, и они взаимно исключающие: «различает» (находка у отказа, неизмеренное у
    молчания) · «сводит» (оба рода совпали) · «не измерено» (различны, но не в ту сторону).
    """
    distinguishes = (refused["findings"] >= 1 and refused["unmeasured"] == 0
                     and silent["unmeasured"] >= 1 and silent["findings"] == 0)
    if distinguishes:
        return {"kind": DRIVE_DISTINGUISHES}
    if (refused["findings"], refused["unmeasured"]) == (silent["findings"], silent["unmeasured"]):
        return {"kind": DRIVE_CONFLATES, "reason": "обе сцены дали один и тот же род исхода"}
    return {"kind": DRIVE_UNMEASURED, "reason": "исходы различны, но НЕ в объявленную сторону"}


def drive_exemplar(root: "Path | str | None" = None) -> dict:
    """Различает ли НАСТОЯЩИЙ читатель «отказано» от «не ответило»?

    Эталон — `push_to_github.mutation_window_verdict`: живой читатель живой двери
    `scripts/delta_mutation_run.py --window-check` (`.claude/rules/deployment.md`,
    § «ОКНО МУТАЦИОННОГО ПРИБОРА»: 0 — окна нет · 1 — находка · 2 — НЕ ИЗМЕРЕНО).

    Подменяется РОВНО ОДНО — сама дверь: две сцены отличаются только кодом, которым она
    отвечает (1 против 2). Читатель, его разбор и его проводка берутся из дерева как есть.
    Собрать из тех же слов печать, подтверждающую саму себя, здесь нечем: спрашивается
    ПРИСУТСТВИЕ находки в своём поле вердикта, а не текст сообщения (ADR-333).
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    runner = root / "push_to_github.py"
    if not runner.is_file():
        return {"kind": DRIVE_UNMEASURED, "reason": f"эталонного читателя нет: {runner}"}
    sys_path_added = False
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
            sys_path_added = True
        import importlib.util as _u
        spec = _u.spec_from_file_location("_p2g_exemplar", runner)
        module = _u.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — эталон, который не ввозится, есть третий исход
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"эталонный читатель не ввозится: {type(exc).__name__}: {exc}"}
    finally:
        if sys_path_added:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    verdict_fn = getattr(module, "mutation_window_verdict", None)
    if verdict_fn is None:
        return {"kind": DRIVE_UNMEASURED,
                "reason": "у эталонного читателя нет mutation_window_verdict"}

    scenes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="three_outcome_exemplar_") as tmp:
        for label, code in (("door_refused", 1), ("door_did_not_answer", 2)):
            scene = Path(tmp) / label
            (scene / "scripts").mkdir(parents=True)
            # Сцена ОБЯЗАНА быть рабочим деревом: читатель спрашивает у git, какому
            # дереву принадлежит файл, и на каталоге без репозитория отвечает «дерево
            # файла не определяется» — то есть СВОИМ третьим исходом, а не вердиктом о
            # двери (ADR-789, память «сцена доставки обязана быть рабочим деревом»).
            # Имя ветки объявлено явно: `init.defaultBranch` хоста иначе решал бы за нас
            # (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»).
            init = subprocess.run(["git", "init", "-b", "main", str(scene)],
                                  capture_output=True, text=True)
            if init.returncode != 0:
                return {"kind": DRIVE_UNMEASURED,
                        "reason": (f"сцену {label} не удалось сделать рабочим деревом: "
                                   f"git init вернул {init.returncode} — "
                                   f"{(init.stderr or '').strip()[:200]}")}
            (scene / "scripts" / "delta_mutation_run.py").write_text(
                _STUB_DOOR.format(code=code), encoding="utf-8")
            payload = scene / "delivered.py"
            payload.write_text("# набор доставки сцены эталона\n", encoding="utf-8")
            fake_runner = scene / "push_to_github.py"
            fake_runner.write_text("# только адрес дерева, код берётся из живого модуля\n",
                                   encoding="utf-8")
            try:
                out = verdict_fn([str(payload)], runner_file=str(fake_runner))
            except Exception as exc:  # noqa: BLE001
                return {"kind": DRIVE_UNMEASURED,
                        "reason": f"сцена {label} не собралась: {type(exc).__name__}: {exc}"}
            scenes[label] = {
                "findings": len(out.get("findings") or []),
                "unmeasured": len(out.get("unmeasured") or []),
                "trees": out.get("trees") or {},
            }

    verdict = exemplar_verdict(scenes["door_refused"], scenes["door_did_not_answer"])
    verdict.update({"reader": "push_to_github.mutation_window_verdict", "scenes": scenes})
    if verdict["kind"] == DRIVE_DISTINGUISHES:
        verdict["door"] = "scripts/delta_mutation_run.py --window-check"
    return verdict


def publication_scenes_verdict(refused: dict, silent: dict) -> dict:
    """Вердикт о двух сценах ПОЧИНЕННОГО читателя — ОТДЕЛЬНО от их подъёма (ADR-871).

    Шов здесь по тому же уроку, что у :func:`exemplar_verdict`: подмена живой проверки
    на «ok = True» выживает мутацию, если утверждение о РОДЕ исхода не проверено
    напрямую — живые сцены отвечают верно, и проба прошла бы на сводящем читателе.
    Сцену со СВОДЯЩИМ читателем в живом дереве взять негде (его только что починили),
    поэтому вердикт обязан быть проверяем без дерева.

    Три исхода взаимно исключающие: «различает» (дверь отказала ⇒ ``refused``, дверь не
    ответила ⇒ ``unmeasured``) · «сводит» (род исхода совпал) · «не измерено» (роды
    различны, но НЕ в объявленную сторону).
    """
    kinds = (refused.get("kind"), silent.get("kind"))
    if kinds == ("refused", "unmeasured"):
        return {"kind": DRIVE_DISTINGUISHES}
    if refused.get("kind") == silent.get("kind"):
        return {"kind": DRIVE_CONFLATES,
                "reason": (f"обе сцены дали один род исхода «{refused.get('kind')}»: "
                           f"«ворота отказали» и «ворота не ответили» неотличимы")}
    return {"kind": DRIVE_UNMEASURED,
            "reason": (f"роды исходов различны, но НЕ в объявленную сторону: "
                       f"отказ ⇒ «{kinds[0]}», молчание ⇒ «{kinds[1]}»")}


def drive_publication_gate(root: "Path | str | None" = None) -> dict:
    """Различает ли ПОЧИНЕННЫЙ читатель ворот публикации «отказано» от «не ответило»?

    Предмет — находки 1–2 переписи ADR-870, закрытые ADR-871. Эталон тут не сосед, а
    сам починенный читатель: `push_to_github.publication_gate_verdict`, живая дверь —
    `scripts/verify_publication.py` (`PASS, FAIL, NOT_MEASURED = 0, 1, 2`).

    Подменяется РОВНО ОДНО — код, которым отвечает дверь (1 против 2). Читатель, его
    поиск двери и его классификация берутся из дерева как есть. Статическая ось говорит
    «место есть»; эта отвечает на другой вопрос — что различение ДОСТИЖИМО (урок
    ADR-674).
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    runner = root / "push_to_github.py"
    if not runner.is_file():
        return {"kind": DRIVE_UNMEASURED, "reason": f"починенного читателя нет: {runner}"}
    sys_path_added = False
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
            sys_path_added = True
        import importlib.util as _u
        spec = _u.spec_from_file_location("_p2g_pubgate", runner)
        module = _u.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — читатель, который не ввозится, есть 3-й исход
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"читатель не ввозится: {type(exc).__name__}: {exc}"}
    finally:
        if sys_path_added:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass

    verdict_fn = getattr(module, "publication_gate_verdict", None)
    if verdict_fn is None:
        return {"kind": DRIVE_UNMEASURED,
                "reason": "у читателя нет publication_gate_verdict — ворота публикации "
                          "читает кто-то другой, и кто именно, ЭТОЙ осью НЕ ИЗМЕРЕНО"}

    scenes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="three_outcome_pubgate_") as tmp:
        for label, code in (("door_refused", 1), ("door_did_not_answer", 2)):
            scene = Path(tmp) / label
            (scene / "scripts").mkdir(parents=True)
            (scene / "landing" / "src" / "data").mkdir(parents=True)
            (scene / "scripts" / "verify_publication.py").write_text(
                _STUB_DOOR.format(code=code), encoding="utf-8")
            shelf = scene / "landing" / "src" / "data" / "site_numbers.json"
            shelf.write_text('{"_scene": "витрина сцены"}\n', encoding="utf-8")
            fake_runner = scene / "push_to_github.py"
            fake_runner.write_text("# только адрес дерева, код берётся из живого модуля\n",
                                   encoding="utf-8")
            try:
                out = verdict_fn([str(shelf)], runner_file=str(fake_runner))
            except Exception as exc:  # noqa: BLE001
                return {"kind": DRIVE_UNMEASURED,
                        "reason": f"сцена {label} не собралась: {type(exc).__name__}: {exc}"}
            scenes[label] = {"kind": out.get("kind"), "rc": out.get("rc"),
                             "detail": out.get("detail")}

    verdict = publication_scenes_verdict(scenes["door_refused"],
                                         scenes["door_did_not_answer"])
    verdict.update({"reader": "push_to_github.publication_gate_verdict", "scenes": scenes})
    if verdict["kind"] == DRIVE_DISTINGUISHES:
        verdict["door"] = "scripts/verify_publication.py --find-approval"
    return verdict


# ── CLI ──────────────────────────────────────────────────────────────────────

BASELINE_REL = "scripts/three_outcome_reader_baseline.json"


def load_baseline(root: "Path | str | None" = None) -> dict:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    path = root / BASELINE_REL
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def finding_key(row: dict) -> str:
    """Личность находки — читатель + дверь + область, но НЕ номер строки.

    Номер строки дрейфует от любой правки выше, и храповик на нём краснел бы от
    переноса строк. Область (`scope`) при этом держит место достаточно узко.
    """
    return f"{row['reader']}::{row['scope']}::{row['door']}"


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Перепись: кто читает трёхисходную дверь двумя исходами (ADR-869).")
    ap.add_argument("--root", help="дерево для разбора (умолчание — дерево этого модуля)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--drive-exemplar", action="store_true",
                    help="дополнительно прогнать живой эталон (две сцены)")
    args = ap.parse_args(argv)

    report = run_census(args.root)
    if report.get("verdict") == UNMEASURED and "reason" in report:
        print(f"НЕ ИЗМЕРЕНО: {report['reason']}", file=sys.stderr)
        return RC_UNMEASURED
    if args.drive_exemplar:
        report["exemplar"] = drive_exemplar(args.root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        counts = report["counts"]
        print(f"Перепись «трёхисходная дверь — двухисходный читатель» "
              f"(дерево {report['root']}):")
        print(f"  дверей (словарь объявлен В КОДЕ): {report['door_count']} · "
              f"читателей: {report['reader_count']}")
        print(f"  различают: {counts[DISTINGUISHES]} · сводят: {counts[COLLAPSED]} · "
              f"fail-OPEN: {counts[FAIL_OPEN]} · не читают код: {counts[IGNORED]} · "
              f"делят остаточный класс (НЕ находка): {counts[RESIDUAL_SHARED]} · "
              f"вердикт едет не кодом (НЕ находка): {counts[OTHER_CHANNEL]}")
        for row in report["findings"]:
            print(f"  ⚠️ {row['verdict'].upper()} {row['reader']}:{row['line']} "
                  f"({row['scope']}) ← {row['door']} {row['door_codes']}: {row['reason']}")
        nm = report["not_measured_surfaces"]
        print(f"  НЕ ИЗМЕРЕНО этой переписью: оболочка {nm['shell_sites']} · "
              f"воркфлоу {nm['workflow_sites']} · импорт двери {nm['import_sites']} мест; "
              f"словарь только прозой у {len(report['doors_declared_in_prose_only'])} модулей")
        if args.drive_exemplar:
            ex = report["exemplar"]
            print(f"  живой эталон: {ex['kind']}"
                  + (f" — {ex['reason']}" if ex.get("reason") else ""))
    if report["counts"][FAIL_OPEN] or report["findings"]:
        return RC_FINDING
    return RC_CLEAN


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
