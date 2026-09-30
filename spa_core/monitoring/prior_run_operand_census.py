"""Перепись: операнд «предыдущий прогон», взятый из git-tracked артефакта.

Заказ владельца **G86 п. 3** (хвост ADR-475, стои́т остатком с 25.09):

> Сколько ещё сторожей читают «предыдущий прогон» из git-tracked артефакта. Класс шире
> одного файла: любой `prev_*` операнд, который в CI берётся из репозитория, есть
> константа, а не наблюдение. Мерить у ПИСАТЕЛЯ (кто коммитит артефакт обратно), а не
> по имени поля; три исхода обязательны.

Авария, из которой заказ вырос (ADR-475, замер 25.09). Половина стоп-крана кустодиана
читала `prev_report.stale_48h` из `data/site_freshness_report.json`. Файл git-tracked, у
джобы `permissions: contents: read`, обратно его не коммитит НИКТО — значит в CI на месте
«предыдущего прогона» лежал отчёт от 2026-07-04 со `stale_48h: false`, возраст 2000 ч.
Второй операнд «двух прогонов подряд» был КОНСТАНТОЙ из 4 июля, и ветка не срабатывала
ни разу за 83 дня. Тихий fail-OPEN: красного теста нет, красной джобы нет, ноль в отчёте
неотличим от «на прошлом прогоне было чисто».

## Почему перепись мерит у ПИСАТЕЛЯ, а не по имени поля

Имя `prev_*` — привычка автора, а не свойство кода: тот же вред носит `last_report`,
`baseline`, `earlier` и безымянный элемент списка. И наоборот: `prev_apy`, посчитанный
в ЭТОМ прогоне из ряда, никакого вреда не несёт. Вопрос, отвечающий на вред, ровно один:
**кто кладёт этот файл в то дерево, которое сторож прочтёт.** Если файл git-tracked и
обратно его не коммитит никакая ОБЪЯВЛЕННАЯ автоматика, то в CI сторож читает не прошлый
прогон, а последний коммит — то есть константу.

## Что признаётся «предыдущим прогоном» (структурно, без имён)

Модуль ПИШЕТ и ЧИТАЕТ ОДИН И ТОТ ЖЕ путь под `data/`. Чтение своего же вывода и есть
структурная форма «предыдущего прогона»: другого способа получить прошлый прогон у
процесса без памяти нет. Форма не зависит ни от имени переменной, ни от имени поля.

## Исходы (форма ЗАКРЫТА, сумма равна населению, инв. #17)

Ноги спрашиваются в ЭТОМ порядке, и порядок — часть утверждения:

1. ``reader_not_reachable_from_ci`` — ни один воркфлоу не зовёт читателя. На хосте файл
   на диске ЕСТЬ результат прошлого прогона, поэтому операнд там — наблюдение, и вреда
   заказа тут нет. Спрашивать это первым обязательно: иначе перепись объявила бы
   дефектом каждый агентский журнал флота.
2. ``absent_in_ci`` — артефакт НЕ git-tracked. В CI прошлого прогона нет ВОВСЕ, то есть
   операнд ОТСУТСТВУЕТ, а не врёт. Это другая беда и чинится другим (назвать отсутствие
   третьим исходом), поэтому в находку не сливается.
3. ``prior_run_committed_back`` — артефакт git-tracked И объявленная автоматика коммитит
   его обратно. Тогда в CI операнд есть наблюдение (пусть и на шаг старое).
4. ``constant_in_ci_named`` — git-tracked, автоматики нет, но читатель СПРАШИВАЕТ
   ВОЗРАСТ прошлого артефакта (значение из него уходит в разбор времени, а результат
   разбора — в сравнение). Фоссил назван; это состояние кустодиана ПОСЛЕ ADR-475 и
   положительный контроль исхода.
5. ``constant_in_ci_trusted`` — git-tracked, автоматики нет, возраст не спрашивается.
   **Это и есть находка заказа**: операнд — константа, и молчание выдаётся за согласие.
6. ``unmeasured:<причина>`` — громкий третий исход с НАЗВАННОЙ причиной. Недоступный git,
   нечитаемое дерево воркфлоу, неразбираемый файл. Никогда не ноль и никогда не «чисто».

## Односторонность — НАЗВАНА ЗАРАНЕЕ, и каждая клауза есть нижняя граница

- **Читатель чужого вывода в население НЕ входит.** Сторож, читающий прошлый прогон
  ДРУГОГО производителя, несёт тот же вред, и здесь он не измерен ВОВСЕ. Это следующий
  вопрос, а не молчаливое «чисто».
- **Запись видна на один уровень.** Кроме примитивов (`atomic_save`, `open(...,'w')`,
  `.write_text`, `os.replace`) разбирается ОДИН уровень локального помощника: функция
  этого же модуля, у которой параметр уходит в примитив на месте пути. Авария ADR-475
  имеет ровно эту форму (`_atomic_write(_REPORT, report)`), и без уровня помощника
  положительный контроль не нашёлся бы — первый черновик этой переписи дал на нём
  НОЛЬ. Цепочка глубже двух звеньев в население не попадает: население — нижняя граница.
- **Достижимость из CI — по УПОМИНАНИЮ** читателя в `.github/workflows/*.yml`. Читатель,
  позванный окольно (модуль, импортированный скриптом, которого зовёт джоба), считается
  недостижимым. Опять нижняя граница, и опять сказано вслух.
- **Писатель ищется в ОБЪЯВЛЕННОМ радиусе** — воркфлоу и plist'ы флота, — а НЕ в истории
  git. История в CI отсутствует по построению (`fetch-depth: 1`, ADR-479), и прибор,
  спросивший `git log`, отвечал бы на разных машинах разное. Коммит, сделанный руками
  цикла, писателем НЕ считается: у ADR-475 файл был закоммичен именно так, и это его
  фоссилом не сделало менее фоссилом.
- **«Возраст спрашивается» — признак, а не доказательство.** Прибор видит, что читатель
  СПРАШИВАЕТ, когда был прошлый прогон; верен ли порог и верно ли ветвление — вопрос не
  его. Сказано числом, а не словами: исход зовётся ``named``, не ``safe``.

ADVISORY: прибор только ЧИТАЕТ (`applied=False`). Ни строки risk-логики, стоп-крана
просадки, аллокатора, гейта исполнения, живого трека, `landing/**` или флота он не
меняет и менять не может.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib
import re
import subprocess
import sys

APPLIED = False

#: Каталоги, в которых ищутся читатели. Тесты сюда не входят: тест, читающий свой же
#: артефакт, есть фикстура, а не сторож дерева.
SOURCE_ROOTS = ("spa_core", "scripts")

#: Литерал признаётся путём артефакта данных по РАСШИРЕНИЮ. Путь собирается из кусков
#: (`_ROOT / "data" / "x.json"`), поэтому якорем берётся последний кусок — имя файла.
ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:json|jsonl)$")

#: Примитивы записи. `os.replace` входит: атомарная запись кончается именно им, и без
#: него локальный помощник вида `tmp.write_text(...); os.replace(tmp, path)` не виден.
WRITE_PRIMITIVES = ("atomic_save", "write_text", "replace", "open", "dump")

#: Вызовы, превращающие значение в ВРЕМЯ. Читатель, приведший операнд к времени,
#: спрашивает «когда был прошлый прогон» — это и есть признак названного фоссила.
TIME_CALL_NAMES = (
    "fromisoformat", "strptime", "utcfromtimestamp", "fromtimestamp",
    "parse_ts", "_parse_ts", "hours_since", "_hours_since", "age_hours",
    "_age_hours", "_hours_since_ts", "hours_since_ts", "total_seconds",
)

#: Вызовы, добывающие наблюдение ЭТОГО прогона извне модуля: сеть, процесс, часы.
#: Операнд «предыдущий прогон» опасен ровно тогда, когда встречается в решении с таким
#: наблюдением: тогда «прошлый раз было чисто» подставляется вместо факта. Сравнение
#: прошлого содержимого с ЛИТЕРАЛОМ — это проверка самого документа, а не решение о мире.
#: Голого `get` здесь НЕТ, и это замер, а не недосмотр: `dict.get` — самая частая форма
#: в этом дереве, и её включение делало `observed` почти всеми именами модуля, то есть
#: гасило ногу «нет решения против наблюдения» целиком. Сетевой случай через `get` при
#: этом ничего не терял: живой запрос кустодиана идёт своим помощником `_get`, а не
#: `requests.get`. Канал наблюдения, на котором нога держится, — чтение ДРУГОГО артефакта,
#: и он проверяется отдельным звеном, а не именем вызова.
OBSERVATION_CALL_NAMES = (
    "urlopen", "request", "urlretrieve", "run", "check_output", "Popen",
    "now", "utcnow", "time", "monotonic", "stat", "st_mtime", "getmtime",
)

OUT_NOT_IN_CI = "reader_not_reachable_from_ci"
OUT_ABSENT_IN_CI = "absent_in_ci"
OUT_COMMITTED_BACK = "prior_run_committed_back"
OUT_PARITY = "parity_with_own_regeneration"
OUT_NO_DECISION = "no_decision_against_a_current_observation"
OUT_CONST_NAMED = "constant_in_ci_named"
OUT_CONST_TRUSTED = "constant_in_ci_trusted"
OUT_UNMEASURED = "unmeasured"

#: Форма исхода ЗАКРЫТА. Сумма по этому перечню обязана равняться населению, и каждый
#: ноль объявляется явно (инв. #17) — «нет такого исхода» и «исход не считался» разные.
OUTCOMES = (
    OUT_NOT_IN_CI,
    OUT_ABSENT_IN_CI,
    OUT_COMMITTED_BACK,
    OUT_PARITY,
    OUT_NO_DECISION,
    OUT_CONST_NAMED,
    OUT_CONST_TRUSTED,
    OUT_UNMEASURED,
)

#: Формы, которыми объявленная автоматика кладёт артефакт обратно в дерево (YAML/plist).
COMMIT_FORMS = ("git commit", "git-auto-commit", "add-and-commit", "stefanzweifel")

#: Доставщики дерева этого репозитория. Писателем признаётся вызов, ПОЛУЧИВШИЙ путь
#: артефакта аргументом, а не сосед по файлу: третий дефект черновика был ровно здесь —
#: радиус писателя ограничивался воркфлоу и plist'ами, и `landing/src/data/track_snapshot.json`,
#: который кустодиан публикует САМ (`publish_from_fresh_checkout(_SNAP, …)`), получил вердикт
#: «автоматики нет». Со-присутствие в одном файле писателем НЕ является: тот же кустодиан
#: называет и `site_freshness_report.json`, которого не коммитит никто, и «писатель в том же
#: модуле» оправдал бы аварию ADR-475 её же собственным доставщиком.
COMMIT_CALL_NAMES = (
    "publish_from_fresh_checkout", "safe_site_push", "push_to_github",
    "batch_push", "push_files", "commit_and_push", "git_commit",
)

RC_MEASURED = 0
RC_FINDING = 1
RC_UNMEASURED = 2


# ─────────────────────────────────────────────────────────────────────────────────────
# Разрешение имён: какие литералы-артефакты стои́т за выражением
# ─────────────────────────────────────────────────────────────────────────────────────

def _artifact_literals(node):
    """Имена файлов-артефактов, встречающиеся литералами внутри выражения."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            tail = sub.value.rsplit("/", 1)[-1]
            if ARTIFACT_NAME_RE.match(tail):
                out.add(tail)
    return out


def _names_in(node):
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


class _PathResolver:
    """Имя → множество имён артефактов, до неподвижной точки.

    Область НАМЕРЕННО плоская: путь к артефакту в этом коде почти всегда константа
    модуля, а разбор по областям видимости добавил бы вторую копию правила связывания
    ради случая, которого в дереве нет. Цена названа: одноимённые локальные пути в
    разных функциях слились бы — и это подняло бы население (ошибка в сторону находки),
    а не понизило.
    """

    def __init__(self, tree):
        self._direct = collections.defaultdict(set)
        self._via = collections.defaultdict(set)
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets = [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    self._direct[tgt.id] |= _artifact_literals(node.value)
                    self._via[tgt.id] |= _names_in(node.value)

    def resolve(self, node):
        out = _artifact_literals(node)
        for name in _names_in(node):
            out |= self._name(name, set())
        return out

    def _name(self, name, seen):
        if name in seen:
            return set()
        seen.add(name)
        out = set(self._direct.get(name, ()))
        for nxt in self._via.get(name, ()):
            out |= self._name(nxt, seen)
        return out


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _mode_of(call):
    mode = ""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            mode = arg.value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = str(kw.value.value)
    return mode


def _primitive_path_slots(call):
    """Выражения этого вызова, стоя́щие на месте ПУТИ у примитива записи/чтения.

    Возвращает ``(write_slots, read_slots)``. Один вызов может не быть ни тем, ни
    другим — тогда оба пусты.
    """
    name = _call_name(call)
    func = call.func
    writes, reads = [], []
    if name == "atomic_save" and len(call.args) >= 2:
        # ADR-порядок: atomic_save(data, path) — данные ПЕРВЫМ аргументом.
        writes.append(call.args[1])
    elif name == "write_text" and isinstance(func, ast.Attribute):
        writes.append(func.value)
    elif name == "replace" and isinstance(func, ast.Attribute) and call.args:
        # os.replace(tmp, path) — целью является ВТОРОЙ аргумент; tmp нас не интересует.
        if len(call.args) >= 2:
            writes.append(call.args[1])
    elif name == "dump" and len(call.args) >= 2:
        writes.append(call.args[1])
    elif name == "open" and call.args:
        mode = _mode_of(call)
        if "w" in mode or "a" in mode or "x" in mode:
            writes.append(call.args[0])
        else:
            reads.append(call.args[0])
    elif name == "read_text" and isinstance(func, ast.Attribute):
        reads.append(func.value)
    elif name == "load" and call.args:
        reads.append(call.args[0])
    elif name == "loads" and call.args:
        reads.append(call.args[0])
    return writes, reads


# ─────────────────────────────────────────────────────────────────────────────────────
# Один уровень локального помощника
# ─────────────────────────────────────────────────────────────────────────────────────

def _parameters(fdef):
    """Параметры функции: позиционные и ТОЛЬКО-ИМЕННЫЕ, одним правилом.

    Возвращает ``(positional, all_names)``. Отдельная функция, а не два обхода на
    месте: пропуск ``kwonlyargs`` был НАСТОЯЩИМ дефектом первого черновика — на
    положительном контроле ADR-475 (`def evaluate(*, …, prev_report=None)`) метка не
    доходила до параметра, и перепись объявляла названный фоссил молчаливой
    константой, то есть выдумывала находку на исправленном коде.
    """
    positional = [a.arg for a in list(fdef.args.posonlyargs) + list(fdef.args.args)]
    names = positional + [a.arg for a in fdef.args.kwonlyargs]
    return positional, names


def _local_functions(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _helper_path_slots(tree):
    """Локальные помощники, чей параметр уходит в примитив на месте пути.

    ``{имя функции: {"write": {индексы}, "read": {индексы}}}``. Без этого уровня
    авария ADR-475 не находится: кустодиан пишет отчёт не примитивом, а своим
    ``_atomic_write(_REPORT, report)``. Первый черновик переписи дал на положительном
    контроле НОЛЬ именно поэтому.
    """
    out = {}
    for fname, fdef in _local_functions(tree).items():
        positional, params = _parameters(fdef)
        if not params:
            continue
        index = {p: i for i, p in enumerate(positional)}
        slots = {"write": set(), "read": set(), "write_kw": set(), "read_kw": set()}
        for node in ast.walk(fdef):
            if not isinstance(node, ast.Call):
                continue
            writes, reads = _primitive_path_slots(node)
            for kind, exprs in (("write", writes), ("read", reads)):
                for expr in exprs:
                    for nm in _names_in(expr):
                        if nm in index:
                            slots[kind].add(index[nm])
                        elif nm in params:
                            slots[kind + "_kw"].add(nm)
        if any(slots.values()):
            out[fname] = slots
    return out


def _sites(tree, resolver):
    """Места записи и чтения артефактов: примитивы + ОДИН уровень помощника."""
    helpers = _helper_path_slots(tree)
    writes = collections.defaultdict(set)
    reads = collections.defaultdict(set)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        w_exprs, r_exprs = _primitive_path_slots(node)
        for artifact in {a for e in w_exprs for a in resolver.resolve(e)}:
            writes[artifact].add(node.lineno)
        for artifact in {a for e in r_exprs for a in resolver.resolve(e)}:
            reads[artifact].add(node.lineno)
        name = _call_name(node)
        slots = helpers.get(name)
        if slots:
            for kind, bucket in (("write", writes), ("read", reads)):
                for idx in slots[kind]:
                    if idx < len(node.args):
                        for artifact in resolver.resolve(node.args[idx]):
                            bucket[artifact].add(node.lineno)
                for kwname in slots[kind + "_kw"]:
                    for kw in node.keywords:
                        if kw.arg == kwname:
                            for artifact in resolver.resolve(kw.value):
                                bucket[artifact].add(node.lineno)
    return writes, reads


# ─────────────────────────────────────────────────────────────────────────────────────
# Спрашивает ли читатель ВОЗРАСТ прошлого артефакта
# ─────────────────────────────────────────────────────────────────────────────────────

def _read_bindings(tree, artifact, resolver):
    """Имена, связанные со значением, прочитанным из этого артефакта."""
    tainted = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(getattr(node, "target", None), ast.Name):
            targets = [node.target]
        if not targets:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Call):
                _, r_exprs = _primitive_path_slots(sub)
                if any(artifact in resolver.resolve(e) for e in r_exprs):
                    tainted |= {t.id for t in targets}
    return tainted


def _spread(tree, tainted):
    """Разнести метку по связываниям и по ОДНОМУ уровню локального вызова."""
    funcs = _local_functions(tree)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = _names_in(node.value)
                if names & tainted:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id not in tainted:
                            tainted.add(tgt.id)
                            changed = True
            elif isinstance(node, ast.Call):
                fdef = funcs.get(_call_name(node))
                if fdef is None:
                    continue
                positional, params = _parameters(fdef)
                for idx, arg in enumerate(node.args):
                    if idx < len(positional) and (_names_in(arg) & tainted) and positional[idx] not in tainted:
                        tainted.add(positional[idx])
                        changed = True
                for kw in node.keywords:
                    if kw.arg in params and (_names_in(kw.value) & tainted) and kw.arg not in tainted:
                        tainted.add(kw.arg)
                        changed = True
    return tainted


def _write_data_names(tree):
    """Имена, чьё значение уходит в ДАННЫЕ записи (а не в путь).

    Радиус НАМЕРЕННО грубый — все примитивы записи модуля, без разделения по артефакту:
    модуль, пишущий два артефакта, слил бы их. Цена названа, и она в сторону
    ИСКЛЮЧЕНИЯ из находки, поэтому население остаётся нижней границей, а не раздувается.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "atomic_save" and node.args:
            out |= _names_in(node.args[0]) | _callees_in(node.args[0])
        elif name in ("dump", "write_text", "write") and node.args:
            out |= _names_in(node.args[0]) | _callees_in(node.args[0])
    return out


def _callees_in(node):
    """Имена вызываемых функций внутри выражения — «чьим производством это значение»."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _call_name(sub)
            if name:
                out.add("()" + name)
    return out


def _producer_chain(tree, names):
    """Имена и производители, из которых происходят эти имена (до неподвижной точки)."""
    out = set(names)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & out:
                add = (_names_in(node.value) | _callees_in(node.value)) - out
                if add:
                    out |= add
                    changed = True
    return out


def _parity_with_own_regeneration(tree, artifact, resolver):
    """Читанное сравнивается с ПЕРЕСБОРКОЙ того же артефакта в этом же прогоне.

    Идиома `scripts/build_protection_lab_site_data.py --check`: закоммиченный файл
    читается как ПРЕДМЕТ проверки, рядом строится свежий той же функцией, и расхождение
    и есть вердикт. Закоммиченная копия здесь — не «прошлый прогон», а ожидаемое
    значение, ради которого её и коммитят. Объявить это находкой значило бы потребовать
    убрать проверку паритета — обратное тому, ради чего заказ написан.
    """
    prior = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not prior:
        return False
    written = _producer_chain(tree, _write_data_names(tree))
    local = set(_local_functions(tree))
    # Производителем пересборки признаётся ТОЛЬКО функция этого модуля. Без этого
    # условия за пересборку сошёл бы `json.dumps` у любого писателя, и идиома паритета
    # проглотила бы настоящую находку: авария ADR-475 пишет отчёт именно так.
    written_callees = {n for n in written if n.startswith("()") and n[2:] in local}
    if not written_callees:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        if not any(_names_in(o) & prior for o in operands):
            continue
        # Требовать «другой операнд НЕ из прошлого» здесь нельзя: у идиомы паритета
        # пересборка берёт из закоммиченной копии одно поле (`generated`), и метка
        # прошлого честно доходит до ОБОИХ операндов. Спрашивается поэтому не
        # непричастность, а ПРОИСХОЖДЕНИЕ от собственной пересборки.
        for operand in operands:
            chain = _producer_chain(tree, _names_in(operand)) | _callees_in(operand)
            if chain & written_callees:
                return True
    return False


def _meets_a_current_observation(tree, artifact, resolver):
    """Встречается ли прошлый операнд в РЕШЕНИИ с наблюдением этого прогона.

    Наблюдение — чтение ДРУГОГО артефакта, сеть, процесс или часы. Авария ADR-475
    имеет ровно эту форму: ``stale_48 and prev_stale_48``, где `stale_48` посчитан из
    снимка, а `prev_stale_48` взят из фоссила. Сравнение прошлого содержимого с
    литералом или с собственным полем — проверка документа, а не решение о мире, и в
    находку не идёт: иначе переписью стал бы каждый валидатор git-tracked документа
    (`scripts/kanban_health.py` — положительный контроль этого исключения).
    """
    prior = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not prior:
        return False
    seeds = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if not targets:
            continue
        for sub in ast.walk(node.value):
            if not isinstance(sub, ast.Call):
                continue
            _, r_exprs = _primitive_path_slots(sub)
            other_read = any(
                a != artifact for e in r_exprs for a in resolver.resolve(e)
            )
            if other_read or _call_name(sub) in OBSERVATION_CALL_NAMES:
                seeds |= targets
    observed = _spread(tree, seeds) - prior
    if not observed:
        return False
    for node in ast.walk(tree):
        operands = None
        if isinstance(node, ast.Compare):
            operands = [node.left] + list(node.comparators)
        elif isinstance(node, ast.BoolOp):
            operands = list(node.values)
        if not operands:
            continue
        reached_prior = any(_names_in(o) & prior for o in operands)
        reached_obs = any(_names_in(o) & observed for o in operands)
        if reached_prior and reached_obs:
            return True
    return False


def _asks_the_age(tree, artifact, resolver):
    """Уходит ли значение из артефакта в разбор ВРЕМЕНИ, а результат — в сравнение.

    Две клаузы, и обе обязательны. Только разбор времени — это «прочитали отметку»;
    только сравнение — это любая проверка поля. Фоссил НАЗВАН, когда читатель спросил,
    КОГДА был прошлый прогон, и СРАВНИЛ ответ с чем-то.
    """
    tainted = _spread(tree, _read_bindings(tree, artifact, resolver))
    if not tainted:
        return False
    aged = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in TIME_CALL_NAMES:
            continue
        reached = _names_in(node.func if isinstance(node.func, ast.Attribute) else node)
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            reached |= _names_in(arg)
        if reached & tainted:
            aged.add(node)
    if not aged:
        return False
    aged_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(a in ast.walk(node.value) for a in aged):
            aged_names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    aged_names = _spread(tree, aged_names)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        for operand in operands:
            if _names_in(operand) & aged_names:
                return True
            if any(a in ast.walk(operand) for a in aged):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────────────
# Достижимость читателя из CI и объявленный писатель
# ─────────────────────────────────────────────────────────────────────────────────────

def _workflow_texts(root):
    """Тексты воркфлоу. Третий исход: каталога нет / файл нечитаем ⇒ причина НАЗВАНА."""
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return None, "workflows_dir_missing"
    out = {}
    for path in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"workflow_unreadable:{path.name}:{type(exc).__name__}"
    if not out:
        return None, "workflows_dir_empty"
    return out, None


def _plist_texts(root):
    """plist'ы флота — вторая половина объявленного радиуса писателя."""
    out = {}
    for base in ("launchd", "launchd_plists"):
        d = root / base
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.plist")):
            try:
                out[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
            except OSError:
                continue
    return out


def _reader_in_ci(rel_path, workflows):
    """Воркфлоу, упоминающие этого читателя: по пути, по модульному имени, по файлу."""
    stem = pathlib.PurePosixPath(rel_path).stem
    module = rel_path[:-3].replace("/", ".")
    file_re = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(stem) + r"\.py(?![A-Za-z0-9_])")
    hits = []
    for name, text in sorted(workflows.items()):
        if rel_path in text or module in text or file_re.search(text):
            hits.append(name)
    return hits


def _commit_calls(tree, resolver, rel):
    """Вызовы доставщика, получившие путь артефакта аргументом."""
    out = collections.defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in COMMIT_CALL_NAMES:
            continue
        for expr in list(node.args) + [kw.value for kw in node.keywords]:
            for artifact in resolver.resolve(expr):
                out[artifact].append(f"{rel}:{node.lineno}:{name}")
    return out


def _committed_back(artifact, tracked_path, workflows, plists, commit_calls=()):
    """Объявленная автоматика, кладущая артефакт обратно в дерево.

    Ищется КОММИТ, а не упоминание: воркфлоу, печатающий путь в лог, писателем не
    является. Коммит руками цикла писателем тоже не является — у ADR-475 файл был
    закоммичен именно так и от этого фоссилом быть не перестал.
    """
    found = []
    for name, text in sorted(workflows.items()):
        if not any(form in text for form in COMMIT_FORMS):
            continue
        if artifact in text or (tracked_path and tracked_path in text):
            found.append(f"workflow:{name}")
    for name, text in sorted(plists.items()):
        if any(form in text for form in COMMIT_FORMS) and artifact in text:
            found.append(f"plist:{name}")
    found.extend(f"call:{c}" for c in commit_calls)
    # Дедуп обязателен: один вызов может получить путь ДВАЖДЫ (аргументом и через
    # `rel=`), и тогда перечень читался бы как два независимых писателя.
    return sorted(set(found))


def _tracked_data_files(root):
    """`git ls-files` по ВСЕМУ дереву — что именно лежит в репозитории.

    История НЕ спрашивается намеренно: в CI её нет по построению (`fetch-depth: 1`,
    ADR-479), и прибор, опирающийся на `git log`, отвечал бы на разных машинах разное.

    Радиус ВСЁ дерево, а не `data/`: первый черновик спрашивал только про `data/`, и
    `KANBAN.json` — файл В КОРНЕ репозитория, который читает `scripts/kanban_health.py`
    из двух джоб, — получил вердикт «в CI отсутствует» при том, что он git-tracked.
    Знаменатель переписи собирается по ИМЕНИ файла где угодно, значит и вопрос о
    отслеживании обязан идти по всему дереву: иначе вредная клетка гасится молча.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root), capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git_unavailable:{type(exc).__name__}"
    if proc.returncode != 0:
        return None, f"git_ls_files_failed:rc={proc.returncode}"
    paths = [
        line.strip() for line in proc.stdout.splitlines()
        if line.strip() and ARTIFACT_NAME_RE.match(line.strip().rsplit("/", 1)[-1])
    ]
    return paths, None


# ─────────────────────────────────────────────────────────────────────────────────────
# Замер
# ─────────────────────────────────────────────────────────────────────────────────────

def _population(root):
    """Пары (читатель, артефакт), где модуль ПИШЕТ и ЧИТАЕТ один и тот же путь."""
    pairs = []
    unparsed = []
    commit_calls = collections.defaultdict(list)
    for base in SOURCE_ROOTS:
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = str(path.relative_to(root))
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as exc:
                unparsed.append({"reader": rel, "reason": f"unparsed:{type(exc).__name__}"})
                continue
            resolver = _PathResolver(tree)
            for artifact, calls in _commit_calls(tree, resolver, rel).items():
                commit_calls[artifact].extend(calls)
            writes, reads = _sites(tree, resolver)
            for artifact in sorted(set(writes) & set(reads)):
                pairs.append({
                    "reader": rel,
                    "artifact": artifact,
                    "write_lines": sorted(writes[artifact]),
                    "read_lines": sorted(reads[artifact]),
                    "_tree": tree,
                    "_resolver": resolver,
                })
    return pairs, unparsed, commit_calls


def measure(root, tracked=None, workflows=None, plists=None):
    """Замер. Внешние двери приходят ВХОДОМ — иначе тест судил бы о живой машине."""
    root = pathlib.Path(root)
    notes = []

    if tracked is None:
        tracked, why = _tracked_data_files(root)
        if tracked is None:
            return {
                "applied": APPLIED,
                "order": "G86.3",
                "population": 0,
                "outcomes": {name: 0 for name in OUTCOMES},
                "unmeasured_reasons": {why: 1},
                "findings": [],
                "named_sample": [],
                "measured": False,
                "why_unmeasured": why,
                "notes": notes,
            }
    # Все пути с этим именем, а НЕ первый попавшийся: `track_snapshot.json` лежит в
    # репозитории дважды (`data/` и `landing/src/data/`), и выбор одного из двух был бы
    # догадкой о том, какой файл имел в виду читатель. Догадка здесь запрещена: имя не
    # есть адрес (ADR-465), поэтому двусмысленность уходит в третий исход ГРОМКО.
    tracked_by_name = collections.defaultdict(list)
    for rel in tracked:
        tracked_by_name[pathlib.PurePosixPath(rel).name].append(rel)

    if workflows is None:
        workflows, why = _workflow_texts(root)
        if workflows is None:
            return {
                "applied": APPLIED,
                "order": "G86.3",
                "population": 0,
                "outcomes": {name: 0 for name in OUTCOMES},
                "unmeasured_reasons": {why: 1},
                "findings": [],
                "named_sample": [],
                "measured": False,
                "why_unmeasured": why,
                "notes": notes,
            }
    if plists is None:
        plists = _plist_texts(root)

    pairs, unparsed, commit_calls = _population(root)
    outcomes = {name: 0 for name in OUTCOMES}
    reasons = collections.Counter()
    findings, named_sample, committed_sample, excluded_sample = [], [], [], []

    for item in unparsed:
        outcomes[OUT_UNMEASURED] += 1
        reasons[item["reason"]] += 1

    for pair in pairs:
        reader, artifact = pair["reader"], pair["artifact"]
        in_ci = _reader_in_ci(reader, workflows)
        if not in_ci:
            outcomes[OUT_NOT_IN_CI] += 1
            continue
        candidates = sorted(tracked_by_name.get(artifact, ()))
        if not candidates:
            outcomes[OUT_ABSENT_IN_CI] += 1
            continue
        if len(candidates) > 1:
            outcomes[OUT_UNMEASURED] += 1
            reasons[f"artifact_name_ambiguous_in_repo:{artifact}:{len(candidates)}"] += 1
            continue
        tracked_path = candidates[0]
        writers = _committed_back(
            artifact, tracked_path, workflows, plists, commit_calls.get(artifact, ()),
        )
        if writers:
            outcomes[OUT_COMMITTED_BACK] += 1
            committed_sample.append({
                "reader": reader, "artifact": tracked_path, "writers": writers,
            })
            continue
        row = {
            "reader": reader,
            "artifact": tracked_path,
            "workflows": in_ci,
            "read_lines": pair["read_lines"],
            "write_lines": pair["write_lines"],
        }
        tree, resolver = pair["_tree"], pair["_resolver"]
        if _parity_with_own_regeneration(tree, artifact, resolver):
            outcomes[OUT_PARITY] += 1
            excluded_sample.append(dict(row, why=OUT_PARITY))
            continue
        if not _meets_a_current_observation(tree, artifact, resolver):
            outcomes[OUT_NO_DECISION] += 1
            excluded_sample.append(dict(row, why=OUT_NO_DECISION))
            continue
        if _asks_the_age(tree, artifact, resolver):
            outcomes[OUT_CONST_NAMED] += 1
            named_sample.append(row)
        else:
            outcomes[OUT_CONST_TRUSTED] += 1
            findings.append(row)

    # ИЗМЕРЕННОЕ число рядом, а не исход: на хосте файл на диске ЕСТЬ прошлый прогон,
    # поэтому вреда заказа здесь нет. Но это ровно то население, которое `git checkout
    # -- data/` молча подменяет закоммиченным каноном (авария цикла #361: одна команда
    # откатила 116 файлов на три недели). Форма исходов остаётся ЗАКРЫТОЙ: цифра
    # докладывается, в сумму не входит и находкой не объявляется.
    host_only_but_tracked = sum(
        1 for p in pairs
        if not _reader_in_ci(p["reader"], workflows)
        and p["artifact"] in tracked_by_name
    )

    population = len(pairs) + len(unparsed)
    total = sum(outcomes.values())
    if total != population:
        notes.append(f"сумма исходов {total} != населению {population} — ОТКАЗ формы")

    return {
        "applied": APPLIED,
        "order": "G86.3",
        "population": population,
        "readers": len({p["reader"] for p in pairs}),
        "host_only_but_git_tracked": host_only_but_tracked,
        "outcomes": outcomes,
        "unmeasured_reasons": dict(reasons),
        "findings": sorted(findings, key=lambda r: (r["reader"], r["artifact"])),
        "named_sample": sorted(named_sample, key=lambda r: (r["reader"], r["artifact"])),
        "committed_sample": sorted(committed_sample, key=lambda r: (r["reader"], r["artifact"])),
        "excluded_sample": sorted(excluded_sample, key=lambda r: (r["reader"], r["artifact"])),
        "measured": True,
        "why_unmeasured": None,
        "notes": notes,
        "not_reported": [
            "читатель ЧУЖОГО прошлого прогона — не измерен вовсе, это следующий вопрос",
            "верность порога и ветвления у названного фоссила",
            "запись глубже одного локального помощника — население нижняя граница",
            "читатель, позванный окольно из джобы — считается недостижимым",
            "верность самой проверки паритета и самого валидатора документа",
        ],
    }


def verdict(doc):
    """Код возврата: три РАЗЛИЧИМЫХ исхода, и «не измерено» никогда не 0."""
    if not doc.get("measured"):
        return RC_UNMEASURED
    if doc["outcomes"][OUT_UNMEASURED]:
        return RC_UNMEASURED
    if doc["notes"]:
        return RC_UNMEASURED
    return RC_FINDING if doc["outcomes"][OUT_CONST_TRUSTED] else RC_MEASURED


def format_report(doc):
    lines = []
    if not doc.get("measured"):
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('why_unmeasured')}")
        return "\n".join(lines)
    out = doc["outcomes"]
    lines.append(
        f"операнд «предыдущий прогон» из git-tracked артефакта (заказ G86 п. 3): "
        f"население {doc['population']} пар(ы) у {doc.get('readers', 0)} читател(ей)"
    )
    lines.append(
        "  " + " · ".join(f"{name} {out[name]}" for name in OUTCOMES)
    )
    for row in doc["findings"]:
        lines.append(
            f"  [КОНСТАНТА, молчаливо принятая за прошлый прогон] {row['reader']}"
            f" читает {row['artifact']} (строки {row['read_lines']}), джобы "
            f"{row['workflows']}: файл git-tracked, обратно его не коммитит никакая "
            f"объявленная автоматика, возраст прошлого артефакта не спрашивается"
        )
    for row in doc["named_sample"]:
        lines.append(
            f"  [константа, но ФОССИЛ НАЗВАН] {row['reader']} читает {row['artifact']}"
            f" — возраст прошлого артефакта спрашивается"
        )
    lines.append(
        f"  [рядом, ИЗМЕРЕНО и не находка] хостовых читателей git-tracked артефакта "
        f"{doc.get('host_only_but_git_tracked', 0)}: на хосте это прошлый прогон, но именно "
        f"их подменяет каноном `git checkout -- data/` (авария цикла #361)"
    )
    for row in doc.get("excluded_sample", ()):
        lines.append(
            f"  [ИСКЛЮЧЁН со причиной] {row['reader']} :: {row['artifact']} — {row['why']}"
        )
    for row in doc["committed_sample"]:
        lines.append(
            f"  [операнд есть наблюдение] {row['reader']} :: {row['artifact']}"
            f" — коммитит обратно {row['writers']}"
        )
    for reason, count in sorted(doc["unmeasured_reasons"].items()):
        lines.append(f"  [НЕ ИЗМЕРЕНО] {reason}: {count}")
    for note in doc["notes"]:
        lines.append(f"  [ОТКАЗ] {note}")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc["not_reported"]))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="корень дерева репозитория")
    parser.add_argument("--json", action="store_true", help="печатать документ замера")
    args = parser.parse_args(argv)
    doc = measure(pathlib.Path(args.root))
    printable = {k: v for k, v in doc.items() if not k.startswith("_")}
    print(json.dumps(printable, ensure_ascii=False, indent=2) if args.json
          else format_report(doc))
    return verdict(doc)


if __name__ == "__main__":
    sys.exit(main())
