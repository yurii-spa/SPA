#!/usr/bin/env python3
"""Перепись класса «названный каталог данных до читателя НЕ дошёл» у НЕ-проб.

Класс найден 25.11 (цикл #1252, ADR-1107) и закрыт там у ОДНОЙ двери — у реестра
проб приёмки: названный ``--data-dir`` доходил до 34 проб из 158, а четыре читали
``REPO_ROOT/data`` и отвечали о дереве МОДУЛЯ под заголовком про дерево, которое
назвал читатель. Цена этого ИЗМЕРЕНА: критерий §5 голодающего приказа
«Portfolio CIO» двенадцать циклов отвечал «НЕ ИЗМЕРЕНО: артефакт протух 3787,8 ч»
при живом прод-артефакте **14,2 ч** в НАЗВАННОМ каталоге.

Карточка ``inbox-klass-nazvannyi-katalog-do-pribora-ne-do`` (п. 2) назвала
оставшееся НЕ ИЗМЕРЕННЫМ вслух: ``probe_numbers_tree`` спрашивает ТОЛЬКО пробы
приёмки, а сколько приборов ``scripts/*`` и ``spa_core/monitoring/*`` принимают
``--data-dir`` на CLI и всё равно читают своё дерево внутри — не мерил никто.
Нулём это не считается (инв. #17). Эта перепись отвечает на тот вопрос.

**Вопрос КАЖДОМУ прибору поверхности один:** *когда вызывающий НАЗВАЛ каталог
данных, доходит ли это имя до КАЖДОГО чтения дерева данных внутри.*

**Поверхность ОБЪЯВЛЕННАЯ, а не вкусовая:** все ``*.py`` в :data:`SURFACE_DIRS`,
у которых argparse объявляет флаг из :data:`DATA_FLAGS`. Обходить каталоги целиком
значило бы мерить сотни файлов, у которых каталог данных не входит вовсе, и
утопить предмет в шуме; а брать список «из головы» — потерять ровно того члена,
по которому класс найден (урок ADR-1074: форма, теряющая известного члена, класс
не сужает, а ПОДМЕНЯЕТ).

**Умолчание-запаска НЕ является дефектом, и это несущее различие.** Зрелый прибор
пишет ``if data_dir is not None: return Path(data_dir)`` и лишь ПОТОМ падает на
``_REPO_ROOT / "data"``: названный каталог до читателя доходит, а дерево модуля
берётся, только когда никто ничего не назвал. Мера, не отличающая запаску от
безусловного чтения, покрасила бы `deployment_acceptance`, `book_second_record` и
всю зрелую половину дерева — и научила бы дописывать в базу. Поэтому чтение дерева
модуля судится ПО ОХРАНЕ: стои́т ли оно под проверкой засева (``if``, ``or``,
тернарник) или читается ВСЕГДА.

**Вердикты (инв. #17 — различимы и печатаются порознь):**

* ``REACHES``    — каждое чтение дерева данных происходит от названного входа
                   (чтение дерева модуля либо отсутствует, либо стои́т запаской);
* ``PARTIAL``    — ПРЕДМЕТ КЛАССА (нижняя граница вилки): вход объявлен, но ≥1
                   чтение дерева данных БЕЗУСЛОВНО берёт дерево модуля, и засев в
                   объемлющей функции не спрашивается НИГДЕ — названное имя до него
                   не дойдёт ни при каком вызове;
* ``PARTIAL_WEAK``— ВЕРХНЯЯ граница вилки: чтение дерева модуля стои́т вне охраны,
                   но объемлющая функция засев СПРАШИВАЕТ (форма «ранний возврат»).
                   Это и запаска, и возможный член — одним числом их склеивать
                   нельзя, поэтому население есть ВИЛКА;
* ``NO_DATA_READ``— чтения под каталогом данных не найдено: вне предмета;
* ``UNMEASURED`` — файл не прочитан · не разобрался · все найденные чтения
                   неразрешимы · засев исчерпал предел кругов. Причина названа.

**«✅ ПУСТ» без доказательства, что ось РАЗЛИЧАЕТ, мерой не является** (урок
ADR-932 и § «ось отвечает О СЕБЕ, пока дорога закрыта»). Поэтому перед любым
ответом о населении прибор гоняет САМОКОНТРОЛЬ на двух синтетических сценах,
отличающихся РОВНО охраной чтения, и при неразличении ОТКАЗЫВАЕТ кодом 2:
«предмет пуст» и «мера до предмета не добралась» обязаны быть разными ответами.

**Чего перепись НЕ закрывает (вслух, чтобы не читалось шире).**

1. Засев идёт ВНУТРИ одного файла: прибор, берущий каталог у ИМПОРТИРОВАННОГО
   помощника, числится по своим чтениям, а чтения помощника не судятся — та же
   граница одного хопа, о которую спотыкается сторож притязания ``injected-clock``
   (``.claude/rules/deployment.md``, § девятая дверь). Население за этой границей
   НЕ ИЗМЕРЕНО и нулём не считается.
2. Вопрос задаётся ЧТЕНИЮ пути, а не тому, ТОТ ЛИ это артефакт: прибор, честно
   читающий названный каталог и берущий оттуда не тот файл, прочтётся
   ``REACHES``.
3. Формы чтения — перечислены (:data:`_JOIN_CALLS`, деление ``Path`` на ``"data"``,
   относительный литерал ``data/...``). Чтение чужой формой уйдёт в
   ``NO_DATA_READ``, то есть ошибка в ОПАСНУЮ сторону, и поэтому список форм
   измерен на членах класса (контроль — тест), а не выбран по вкусу.
4. Дифференциальный прогон (два РАЗЛИЧИМЫХ каталога, предмет — тот, у кого
   вердикт НЕ меняется) здесь не делается: он требует запускать 125 приборов,
   часть из которых пишет артефакты. Статическая ось отвечает на тот же вопрос
   БЕЗ побочных действий, а её способность различать доказана самоконтролем.

Запуск::

    python3 scripts/named_data_dir_census.py [--repo-root <дерево>] [--json]
                                             [--subtree <каталог>] [--self-check]

Коды возврата: ``0`` — предмет пуст (при зелёном самоконтроле) · ``1`` — предмет
НЕ пуст (находки названы) · ``2`` — НЕ ИЗМЕРЕНО (самоконтроль не различает ·
каталог поверхности не прочитан · названное дерево нечитаемо).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

#: Каталоги поверхности. Пробы приёмки живут в `card_acceptance.py` и уже
#: измерены своей дверью (`probe_numbers_tree`, ADR-1107) — здесь он участвует
#: как обычный прибор с CLI.
SURFACE_DIRS: Tuple[str, ...] = ("scripts", "spa_core/monitoring")

#: Флаги, которыми вызывающий НАЗЫВАЕТ каталог данных.
DATA_FLAGS: Tuple[str, ...] = ("--data-dir", "--data-root", "--datadir")

#: Зовы, собирающие путь из частей.
_JOIN_CALLS = {"join", "joinpath"}

#: Зовы, ОТКРЫВАЮЩИЕ путь. Относительный литерал считается чтением только здесь:
#: `"data/x.json"` в словаре или в константе модуля — ИМЯ артефакта, которое зрелый
#: прибор потом разрешает против названного каталога (`slo_keepability.artifact_file`).
#: Первая редакция этой переписи считала такие литералы чтениями и объявила предметом
#: `data_freshness_monitor._FILE_MAP` и `card_acceptance._LPC_ARTIFACT` — то есть
#: ОШИБЛАСЬ в сторону находки на ровном месте. Мера, у которой ложных срабатываний
#: больше, чем предмета, учит дописывать в базу (урок ADR-1074).
_OPENERS = {"open", "Path", "read_text", "read_bytes"}

#: Хвосты имён флагов, которыми НАЗЫВАЮТ путь.
_PATH_FLAG_SUFFIXES = ("-dir", "-root", "-path", "-tree", "-file", "-dirs")

#: Предел кругов засева. Исчерпан ⇒ UNMEASURED, а не «чисто».
_SEED_ROUNDS = 12

#: Форма функции (обычной или асинхронной) — одна на обе.
_Func = Union[ast.FunctionDef, ast.AsyncFunctionDef]

REACHES = "REACHES"
PARTIAL = "PARTIAL"
PARTIAL_WEAK = "PARTIAL_WEAK"
NO_DATA_READ = "NO_DATA_READ"
UNMEASURED = "UNMEASURED"

FLAG_DEFAULT = "flag_default"
MODULE_DEFINITION = "module_definition"
OFF_CLI_PATH = "off_cli_path"
SEEDED = "seeded"
MODULE_GUARDED = "module_guarded"
MODULE_LIKELY_FALLBACK = "module_likely_fallback"
MODULE_ALWAYS = "module_always"
UNRESOLVED = "unresolved"


# --------------------------------------------------------------------------- #
# разбор: мелкие помощники
# --------------------------------------------------------------------------- #

def _name_of(node: ast.AST) -> str:
    """Имя зова/атрибута последним звеном (`os.path.join` -> `join`)."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _root_name(node: ast.AST) -> str:
    """Самое левое имя выражения (`a.b.c / "data"` -> `a`)."""
    while True:
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.BinOp):
            node = node.left
        else:
            break
    return node.id if isinstance(node, ast.Name) else ""


def _names_in(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _flag_dest(tree: ast.AST) -> Optional[Tuple[str, str]]:
    """`(флаг, dest)` первого `add_argument(<флаг данных>, …)`; иначе None."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name_of(node.func) != "add_argument":
            continue
        for arg in node.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            if arg.value not in DATA_FLAGS:
                continue
            dest = arg.value.lstrip("-").replace("-", "_")
            for kw in node.keywords:
                if kw.arg == "dest" and isinstance(kw.value, ast.Constant):
                    dest = str(kw.value.value)
            return arg.value, dest
    return None


def _declared_dests(tree: ast.AST) -> Set[str]:
    """Все `dest` argparse этого файла — то есть всё, что вызывающий МОЖЕТ назвать.

    Охрана спрашивается по ЭТОМУ набору, а не только по каталогу данных: вопрос
    класса — «читает ли прибор своё дерево МОЛЧА», и путь, который вызывающий
    вправе назвать другим объявленным флагом (`--panel-dir`, `--root`), молчаливым
    не является. Замер: `edge_live_marks_gate` держит `ROOT / "data" /
    "aggressive_lab"` запаской флага `--panel-dir`, и мера, спрашивавшая только
    `--data-dir`, объявила его предметом.
    """
    out: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name_of(node.func) != "add_argument":
            continue
        dest = ""
        for kw in node.keywords:
            if kw.arg == "dest" and isinstance(kw.value, ast.Constant):
                dest = str(kw.value.value)
        flag = ""
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value.startswith("--"):
                flag = arg.value
                break
        if not flag:
            continue
        # Только флаги, НАЗЫВАЮЩИЕ путь: охрана по `--json` или `--save` ответила бы
        # «назвать можно» про то, что назвать нельзя. Признак объявленный — хвост
        # имени флага, а не вкус.
        if not any(flag.endswith(suf) for suf in _PATH_FLAG_SUFFIXES):
            continue
        out.add(dest or flag.lstrip("-").replace("-", "_"))
    return out


def _module_tree_names(tree: ast.AST) -> Set[str]:
    """Имена модуля, чьё значение происходит от `__file__` (дерево МОДУЛЯ).

    Привязка прослеживается до неподвижной точки: `ROOT = Path(__file__)…`,
    затем `DATA = ROOT / "data"`. Контейнер привязкой не считается — тот же
    порядок, что у сторожа притязания `injected-clock`.

    **Только УРОВЕНЬ МОДУЛЯ.** Первая редакция собирала присваивания по всему
    файлу, и локальное имя `root` одной функции делало «деревом модуля» одноимённый
    ПАРАМЕТР другой: `decision_journal_coverage._reader_probe(spec, root)` читает
    `root / "data"` одноразовой ПЕСОЧНИЦЫ, которую сам же и создал, а мера объявила
    это чтением дерева модуля. Локальные привязки считаются в своей области —
    :func:`_local_tree_names`.
    """
    names: Set[str] = set()
    body = list(getattr(tree, "body", []))
    for _ in range(_SEED_ROUNDS):
        grew = False
        for node in body:
            if not isinstance(node, ast.Assign):
                continue
            if isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
                continue
            src = _names_in(node.value)
            if "__file__" not in src and not (src & names):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id not in names:
                    names.add(tgt.id)
                    grew = True
        if not grew:
            break
    return names


# --------------------------------------------------------------------------- #
# засев от названного входа
# --------------------------------------------------------------------------- #

def _local_tree_names(scope: Optional[ast.AST], module_names: Set[str]) -> Set[str]:
    """Имена дерева модуля, рождённые ВНУТРИ одной функции (`base = Path(__file__)…`)."""
    if scope is None:
        return set()
    names: Set[str] = set()
    for _ in range(_SEED_ROUNDS):
        grew = False
        for node in ast.walk(scope):
            if not isinstance(node, ast.Assign):
                continue
            if isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
                continue
            src = _names_in(node.value)
            if "__file__" not in src and not (src & (names | module_names)):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id not in names:
                    names.add(tgt.id)
                    grew = True
        if not grew:
            break
    return names


def _functions(tree: ast.AST) -> Dict[str, _Func]:
    out: Dict[str, _Func] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _seed_set(tree: ast.AST, dest: str) -> Tuple[Set[str], bool]:
    """Имена, чьё значение происходит от названного входа. `(имена, доразобрано)`.

    Засев идёт не только по присваиваниям, но и В ПАРАМЕТРЫ зовомых функций того
    же файла: шаг 1г до починки ADR-933 отстоял от своего `cwd=` на ДВА хопа через
    параметры, то есть мера, разбирающая одну функцию, назвала бы класс пустым.
    """
    funcs = _functions(tree)
    seeds: Set[str] = {dest}
    settled = False
    for _ in range(_SEED_ROUNDS):
        grew = False
        # (а) `x = <выражение от засева>`  ·  `args.<dest>` считается засевом
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
                    continue
                if not (_names_in(node.value) & seeds):
                    continue
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id not in seeds:
                        seeds.add(tgt.id)
                        grew = True
            # (б) зов функции того же файла засеянным значением -> её параметр
            elif isinstance(node, ast.Call):
                # ТОЛЬКО прямой зов по имени: `subprocess.run(...)` — чужая функция,
                # и приравнивать её к одноимённой своей значило бы засеять
                # параметры постороннего получателя (замер: так `run` файла
                # `tree_lifetime_census` стал «достижимым» от CLI-входа).
                if not isinstance(node.func, ast.Name):
                    continue
                callee = funcs.get(node.func.id)
                if callee is None:
                    continue
                params = [a.arg for a in callee.args.args] + \
                         [a.arg for a in callee.args.kwonlyargs]
                for i, arg in enumerate(node.args):
                    if i < len(params) and (_names_in(arg) & seeds) \
                            and params[i] not in seeds:
                        seeds.add(params[i])
                        grew = True
                for kw in node.keywords:
                    if kw.arg and kw.arg in params and (_names_in(kw.value) & seeds) \
                            and kw.arg not in seeds:
                        seeds.add(kw.arg)
                        grew = True
        if not grew:
            settled = True
            break
    return seeds, settled


# --------------------------------------------------------------------------- #
# чтения дерева данных
# --------------------------------------------------------------------------- #

def _is_data_component(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.strip("/") == "data")


def _data_reads(tree: ast.AST) -> List[Tuple[ast.AST, Optional[ast.AST], str]]:
    """Все выражения «путь под каталогом данных».

    Возврат — список `(узел, выражение-корень, форма)`. Корень у относительного
    литерала отсутствует (`None`): его дерево — текущий каталог, то есть дерево
    запуска, и названный вход до него не доходит по построению.
    """
    out: List[Tuple[ast.AST, Optional[ast.AST], str]] = []
    for node in ast.walk(tree):
        # `X / "data"` (и дальше)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) \
                and _is_data_component(node.right):
            out.append((node, node.left, "truediv"))
        # `os.path.join(X, "data", …)` / `X.joinpath("data", …)`
        elif isinstance(node, ast.Call) and _name_of(node.func) in _JOIN_CALLS:
            args = list(node.args)
            if _name_of(node.func) == "joinpath" and isinstance(node.func, ast.Attribute):
                root = node.func.value
                if any(_is_data_component(a) for a in args):
                    out.append((node, root, "joinpath"))
            elif len(args) >= 2 and any(_is_data_component(a) for a in args[1:]):
                out.append((node, args[0], "join"))
        # относительный литерал `"data/..."` — ТОЛЬКО как аргумент открывателя
        elif isinstance(node, ast.Call) and _name_of(node.func) in _OPENERS:
            for a in node.args[:1]:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and a.value.startswith("data/") and len(a.value) > 5:
                    out.append((node, None, "relative_literal"))
    return out


def _parents(tree: ast.AST) -> Dict[int, ast.AST]:
    """Карта «узел -> родитель». Считается ОДИН раз на файл.

    Первая редакция искала охрану перебором `ast.walk` на каждый запрос, и на
    `card_acceptance.py` (20 с лишним тысяч строк) перепись перестала укладываться
    в минуты. Подъём по родителям отвечает на тот же вопрос за глубину дерева и
    вдобавок ТОЧНЕЕ: «узел лежит внутри ветки» — это отношение предок/потомок, а
    не совпадение по обходу.
    """
    out: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _guard_names(target: ast.AST, parents: Dict[int, ast.AST],
                 *, stop: Optional[ast.AST] = None) -> Set[str]:
    """Имена, упомянутые в ОХРАНЕ чтения `target` (подъём по родителям).

    Охраной считаются: условие объемлющего `if` (ЛЮБАЯ его ветка — чтение дерева
    модуля в `else` и есть запаска), условие тернарника, и более ранний операнд
    `or`, в котором чтение стои́т запаской. Это и есть различие «запаска» ↔
    «читается всегда»: под охраной названный каталог до читателя ДОХОДИТ, а дерево
    модуля берётся лишь когда никто ничего не назвал.
    """
    out: Set[str] = set()
    cur: Optional[ast.AST] = target
    while cur is not None and cur is not stop:
        parent = parents.get(id(cur))
        if parent is None:
            break
        if isinstance(parent, (ast.If, ast.While)) and cur is not parent.test:
            out |= _names_in(parent.test)
        elif isinstance(parent, ast.IfExp) and cur is not parent.test:
            out |= _names_in(parent.test)
        elif isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
            for i, val in enumerate(parent.values):
                if val is cur:
                    for j, other in enumerate(parent.values):
                        if j < i:
                            out |= _names_in(other)
        cur = parent
    return out


def _cli_reach(tree: ast.AST, nameable: Set[str], parents: Dict[int, ast.AST]
               ) -> Tuple[Optional[Dict[str, Set[str]]], str]:
    """Достижимость от CLI-входа ВМЕСТЕ с состоянием охраны.

    Возврат — `({имя функции: {"guarded"|"plain", …}}, причина-если-входа-нет)`.

    Вопрос переписи — «когда вызывающий назвал каталог НА CLI»; поэтому судятся
    чтения на пути ОТ CLI-входа, а не любые чтения файла. Различие измерено:
    `judge_alone_price.main` и `tree_lifetime_census.main` разрешают каталог честно,
    а дерево модуля безусловно читает их ступень моста `run(root=…)` — ДРУГОЙ вход
    с ДРУГИМ объявленным параметром.

    **Охрана бывает МЕЖПРОЦЕДУРНОЙ, и это тоже замер, а не вкус.** Зрелый прибор
    пишет::

        if args.data_dir:
            doc = measure(Path(args.data_dir))
        else:
            doc = run()                 # внутри — дерево модуля

    Чтение дерева модуля лежит в ДРУГОЙ функции, лексической охраны у него нет
    вовсе, и мера, спрашивающая только текст функции, объявила бы предметом четыре
    прибора (`adapter_repair_price`, `criterion_sign_price`,
    `move_cost_composition_price`, `swap_existence_price`), написанных честно.
    Поэтому состояние охраны едет ПО ЗОВУ: функция, достижимая ТОЛЬКО из ветки,
    проверяющей засев, числится запаской целиком.
    """
    funcs = _functions(tree)
    entries: Set[str] = set()
    if "main" in funcs:
        entries.add("main")
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "__name__" in _names_in(node.test):
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                        and n.func.id in funcs:
                    entries.add(n.func.id)
    if not entries:
        return None, "CLI-входа (`main` / блок `__main__`) не найдено — судится весь файл"

    states: Dict[str, Set[str]] = {e: {"plain"} for e in entries}
    for _ in range(_SEED_ROUNDS):
        grew = False
        for name in list(states):
            fn = funcs.get(name)
            if fn is None:
                continue
            here = states[name]
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                callee = node.func.id
                if callee not in funcs:
                    continue
                guarded_site = bool(_guard_names(node, parents, stop=fn) & nameable)
                inherited = {("guarded" if guarded_site or st == "guarded" else "plain")
                             for st in here}
                before = states.get(callee, set())
                after = before | inherited
                if after != before:
                    states[callee] = after
                    grew = True
        if not grew:
            break
    return states, ""


def _seed_tested_in(scope: Optional[ast.AST], seeds: Set[str]) -> bool:
    """Спрашивает ли ОБЪЕМЛЮЩАЯ функция про засев — где-либо в своих условиях.

    Зрелая запаска часто написана РАННИМ ВОЗВРАТОМ::

        if data_dir is not None:
            return Path(data_dir)
        return _REPO_ROOT / "data"

    Чтение дерева модуля стои́т тогда СНАРУЖИ `if`, и лексическая охрана
    (:func:`_guard_names`) его не видит: первая редакция переписи объявила поэтому
    предметом `deployment_acceptance._data_dir_for` — функцию, написанную ровно
    против этого дефекта. Но «функция где-то спрашивает про засев» слабее, чем
    «чтение стои́т под охраной»: она верна у запаски и верна же у настоящего члена,
    спрашивающего засев в другом месте. Поэтому ответ о населении есть ВИЛКА, а не
    одно число.
    """
    if scope is None:
        return False
    for node in ast.walk(scope):
        test = getattr(node, "test", None)
        if test is not None and (_names_in(test) & seeds):
            return True
    return False


def classify_file(text: str, *, path: str = "<memory>") -> dict:
    """Один вердикт о приборе. Форма возврата — словарь записи переписи."""
    rec = {"path": path, "verdict": UNMEASURED, "flag": None, "dest": None,
           "reads": [], "reason": ""}
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        rec["reason"] = f"не разобрался: {exc.__class__.__name__}: {exc.msg}"
        return rec

    found = _flag_dest(tree)
    if found is None:
        rec["reason"] = "каталог данных входом не объявлен — вне поверхности"
        return rec
    flag, dest = found
    rec["flag"], rec["dest"] = flag, dest

    seeds, settled = _seed_set(tree, dest)
    if not settled:
        rec["reason"] = (f"засев от {flag} не сошёлся за {_SEED_ROUNDS} кругов — "
                         f"какое дерево прочтут читатели, измерить нечем")
        return rec

    module_names = _module_tree_names(tree)
    nameable = seeds | _declared_dests(tree)
    parents = _parents(tree)
    reach, no_entry = _cli_reach(tree, nameable, parents)
    if no_entry:
        rec["entry"] = no_entry
    funcs_by_name = _functions(tree)
    func_of: Dict[int, str] = {}
    for fname, fn in funcs_by_name.items():
        for n in ast.walk(fn):
            func_of.setdefault(id(n), fname)
    in_function: Set[int] = set()
    for fn in _functions(tree).values():
        for n in ast.walk(fn):
            in_function.add(id(n))
    # Чтение внутри `add_argument(...)` — это УМОЛЧАНИЕ самого флага, а не чтение:
    # названное вызывающим значение его перекрывает по построению. Первая редакция
    # переписи считала такое умолчание предметом и объявила членами три прибора,
    # написанных как раз честно (`default=str(_REPO_ROOT / "data")`).
    in_flag_decl: Set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _name_of(n.func) == "add_argument":
            for x in ast.walk(n):
                in_flag_decl.add(id(x))

    reads: List[dict] = []
    for node, root, form in _data_reads(tree):
        if id(node) in in_flag_decl:
            reads.append({"line": getattr(node, "lineno", 0), "form": form,
                          "origin": FLAG_DEFAULT,
                          "detail": "УМОЛЧАНИЕ самого флага — названное значение "
                                    "его перекрывает"})
            continue
        if id(node) not in in_function:
            reads.append({"line": getattr(node, "lineno", 0), "form": form,
                          "origin": MODULE_DEFINITION,
                          "detail": "уровень модуля — ОПРЕДЕЛЕНИЕ пути, а не чтение; "
                                    "его использования судятся по месту"})
            continue
        owner = func_of.get(id(node), "")
        owner_states = reach.get(owner, set()) if reach is not None else {"plain"}
        if reach is not None and not owner_states:
            reads.append({"line": getattr(node, "lineno", 0), "form": form,
                          "origin": OFF_CLI_PATH,
                          "detail": f"функция {owner or '?'} не на пути от CLI-входа — "
                                    f"у того входа свой объявленный параметр, и это "
                                    f"ДРУГОЕ утверждение"})
            continue
        rn = _root_name(root) if root is not None else ""
        root_names = _names_in(root) if root is not None else set()
        owner_scope = funcs_by_name.get(owner)
        scope_mod_names = module_names | _local_tree_names(owner_scope, module_names)
        guarded = bool(_guard_names(node, parents) & nameable) \
            or owner_states == {"guarded"}
        if form == "relative_literal" and not guarded:
            origin, detail = MODULE_ALWAYS, "относительный литерал — дерево запуска"
        elif rn in seeds or (root_names & seeds):
            origin, detail = SEEDED, f"корень {rn or '?'} от названного входа"
        elif guarded:
            # Охрана снимает вопрос о КОРНЕ: названный каталог до читателя доходит,
            # а эта ветка берётся лишь когда никто ничего не назвал. Так написана
            # половина зрелых приборов: `data_dir or os.path.join(root, "data")`,
            # где `root` — ВТОРОЙ названный вход (`--root`), а не дерево модуля.
            origin = MODULE_GUARDED
            detail = (f"корень {rn or '?'} ЗАПАСКОЙ под охраной засева"
                      if owner_states != {"guarded"} else
                      f"корень {rn or '?'} в функции {owner}, достижимой ТОЛЬКО из "
                      f"ветки, проверяющей засев — запаска по зову")
        elif rn in scope_mod_names or "__file__" in root_names:
            if _seed_tested_in(funcs_by_name.get(owner), seeds):
                origin = MODULE_LIKELY_FALLBACK
                detail = (f"дерево модуля ({rn}) вне охраны, но объемлющая функция "
                          f"засев СПРАШИВАЕТ — похоже на ранний возврат")
            else:
                origin = MODULE_ALWAYS
                detail = f"дерево модуля ({rn}) БЕЗУСЛОВНО"
        elif isinstance(root, ast.Constant) and isinstance(root.value, str) \
                and root.value.startswith("/"):
            origin, detail = MODULE_ALWAYS, "абсолютный литерал в коде"
        else:
            origin, detail = UNRESOLVED, f"корень {rn or '?'} не разрешился"
        reads.append({"line": getattr(node, "lineno", 0), "form": form,
                      "origin": origin, "detail": detail})

    rec["reads"] = reads
    if not reads:
        rec["verdict"] = NO_DATA_READ
        rec["reason"] = "чтения под каталогом данных не найдено"
        return rec
    judged = [r for r in reads if r["origin"] not in (MODULE_DEFINITION, OFF_CLI_PATH, FLAG_DEFAULT)]
    if not judged:
        rec["verdict"] = NO_DATA_READ
        rec["reason"] = (f"на пути от CLI-входа чтений под каталогом данных нет "
                         f"({len(reads)} чтен(ий) вне пути либо определения модуля)")
        return rec
    reads = judged
    origins = {r["origin"] for r in reads}
    if MODULE_ALWAYS in origins:
        rec["verdict"] = PARTIAL
        bad = [r for r in reads if r["origin"] == MODULE_ALWAYS]
        rec["reason"] = (f"{len(bad)} чтен(ие/ия) берут дерево модуля БЕЗУСЛОВНО: "
                         + ", ".join(f"стр. {r['line']} ({r['detail']})" for r in bad[:4]))
        return rec
    if MODULE_LIKELY_FALLBACK in origins:
        rec["verdict"] = PARTIAL_WEAK
        weak = [r for r in reads if r["origin"] == MODULE_LIKELY_FALLBACK]
        rec["reason"] = (f"{len(weak)} чтен(ие/ия) берут дерево модуля вне охраны, "
                         f"но засев спрашивается в той же функции — ВЕРХНЯЯ граница вилки: "
                         + ", ".join(f"стр. {r['line']}" for r in weak[:4]))
        return rec
    if origins == {UNRESOLVED}:
        rec["reason"] = (f"все {len(reads)} чтен(ия) неразрешимы — "
                         f"дошёл ли {flag}, измерить нечем")
        return rec
    rec["verdict"] = REACHES
    rec["reason"] = ("названный вход доходит до каждого чтения"
                     + ("; дерево модуля стои́т запаской" if MODULE_GUARDED in origins else ""))
    return rec


# --------------------------------------------------------------------------- #
# самоконтроль: ось обязана РАЗЛИЧАТЬ
# --------------------------------------------------------------------------- #

#: Сцена-ЧЛЕН: вход объявлен, а одно чтение берёт дерево модуля безусловно.
SCENE_MEMBER = '''
import argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def measure(data_dir=None):
    d = Path(data_dir) if data_dir else ROOT / "data"
    return (d / "a.json").exists()

def tail():
    return (ROOT / "data" / "b.json").exists()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if measure(args.data_dir) and tail() else 1
'''

#: Сцена-НЕ-ЧЛЕН: ровно та же форма, но запаска под охраной засева.
SCENE_CLEAN = '''
import argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def measure(data_dir=None):
    d = Path(data_dir) if data_dir else ROOT / "data"
    return (d / "a.json").exists()

def tail(data_dir=None):
    d = Path(data_dir) if data_dir else ROOT / "data"
    return (d / "b.json").exists()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if measure(args.data_dir) and tail(args.data_dir) else 1
'''


#: Сцена-ЗАПАСКА РАННИМ ВОЗВРАТОМ: чтение дерева модуля стои́т СНАРУЖИ `if`.
SCENE_FALLBACK = '''
import argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def resolve(data_dir=None):
    if data_dir is not None:
        return Path(data_dir)
    return ROOT / "data"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    return 0 if (resolve(args.data_dir) / "a.json").exists() else 1
'''


def self_check() -> dict:
    """Различает ли ось член класса от не-члена. `{"ok", "member", "clean"}`.

    Сцены отличаются РОВНО охраной одного чтения. Два одинаковых ответа означают,
    что мера до предмета не добралась, и тогда «предмет пуст» не является ответом
    (урок ADR-932 и мутации M10 цикла #1226).
    """
    m = classify_file(SCENE_MEMBER, path="<scene:member>")
    c = classify_file(SCENE_CLEAN, path="<scene:clean>")
    f = classify_file(SCENE_FALLBACK, path="<scene:fallback>")
    ok = (m["verdict"] == PARTIAL and c["verdict"] == REACHES
          and f["verdict"] == PARTIAL_WEAK)
    return {"ok": ok, "member": m["verdict"], "clean": c["verdict"],
            "fallback": f["verdict"], "member_reason": m["reason"],
            "clean_reason": c["reason"], "fallback_reason": f["reason"]}


# --------------------------------------------------------------------------- #
# обход поверхности
# --------------------------------------------------------------------------- #

def surface(repo_root: Path, subtrees: Optional[List[str]] = None) -> dict:
    """Поверхность и вердикты. Нечитаемый каталог — НЕ ИЗМЕРЕНО с причиной."""
    dirs = list(subtrees or SURFACE_DIRS)
    records: List[dict] = []
    missing: List[str] = []
    for d in dirs:
        base = repo_root / d
        if not base.is_dir():
            missing.append(d)
            continue
        for p in sorted(base.rglob("*.py")):
            rel = str(p.relative_to(repo_root))
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as exc:
                records.append({"path": rel, "verdict": UNMEASURED, "flag": None,
                                "dest": None, "reads": [],
                                "reason": f"не прочитан: {exc.__class__.__name__}"})
                continue
            rec = classify_file(text, path=rel)
            if rec["flag"] is None and rec["verdict"] == UNMEASURED \
                    and rec["reason"].startswith("каталог данных входом не объявлен"):
                continue          # вне поверхности, в население не входит
            records.append(rec)
    counts = {v: sum(1 for r in records if r["verdict"] == v)
              for v in (REACHES, PARTIAL, PARTIAL_WEAK, NO_DATA_READ, UNMEASURED)}
    return {"repo_root": str(repo_root), "dirs": dirs, "missing_dirs": missing,
            "records": records, "counts": counts,
            "surface_total": len(records), "self_check": self_check()}


def format_report(rep: dict) -> str:
    out: List[str] = []
    sc = rep["self_check"]
    out.append("самоконтроль оси: "
               + ("✅ РАЗЛИЧАЕТ все три формы (член -> PARTIAL, "
                  "запаска под охраной -> REACHES, ранний возврат -> PARTIAL_WEAK)"
                  if sc["ok"] else
                  f"⛔ НЕ РАЗЛИЧАЕТ (член -> {sc['member']}, не-член -> {sc['clean']}, "
                  f"ранний возврат -> {sc.get('fallback')})"))
    if rep["missing_dirs"]:
        out.append("⛔ НЕ ИЗМЕРЕНО: каталог(и) поверхности не прочитан(ы): "
                   + ", ".join(rep["missing_dirs"]))
    c = rep["counts"]
    out.append(f"поверхность (каталог данных объявлен входом): {rep['surface_total']} "
               f"в {', '.join(rep['dirs'])}")
    out.append(f"  имя ДОХОДИТ до каждого чтения: {c[REACHES]}")
    out.append(f"  ПРЕДМЕТ, нижняя граница (дерево модуля читается безусловно): {c[PARTIAL]}")
    out.append(f"  вилка, верхняя граница (чтение вне охраны, засев спрашивается рядом): "
               f"+{c[PARTIAL_WEAK]} ⇒ ВИЛКА {c[PARTIAL]} … {c[PARTIAL] + c[PARTIAL_WEAK]}")
    out.append(f"  чтений под каталогом данных нет: {c[NO_DATA_READ]}")
    out.append(f"  НЕ ИЗМЕРЕНО: {c[UNMEASURED]}")
    subj = [r for r in rep["records"] if r["verdict"] == PARTIAL]
    for r in subj:
        out.append(f"  ⚠️ {r['path']} ({r['flag']}) — {r['reason']}")
    for r in [x for x in rep["records"] if x["verdict"] == PARTIAL_WEAK]:
        out.append(f"  ◻️ {r['path']} ({r['flag']}) — {r['reason']}")
    unm = [r for r in rep["records"] if r["verdict"] == UNMEASURED]
    for r in unm:
        out.append(f"  ❔ {r['path']} — НЕ ИЗМЕРЕНО: {r['reason']}")
    if not subj and sc["ok"]:
        out.append("✅ предмет класса ПУСТ по этой форме — и ось доказала, "
                   "что различает (иначе это был бы ответ о себе)")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево, о котором отвечаем (умолчание — дерево прибора, ПЕЧАТАЕТСЯ)")
    ap.add_argument("--subtree", action="append", default=None,
                    help="каталог поверхности (можно несколько); умолчание — SURFACE_DIRS")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--surface", action="store_true",
                    help="то же, что без флага: поверхность, предмет и НЕ ИЗМЕРЕНО порознь")
    ap.add_argument("--self-check", action="store_true",
                    help="только самоконтроль оси")
    args = ap.parse_args(argv)

    if args.self_check:
        sc = self_check()
        print(json.dumps(sc, ensure_ascii=False, indent=1) if args.json
              else ("✅ ось РАЗЛИЧАЕТ" if sc["ok"]
                    else f"⛔ ось НЕ различает: член -> {sc['member']}, не-член -> {sc['clean']}"))
        return 0 if sc["ok"] else 2

    if args.repo_root:
        root = Path(args.repo_root).expanduser()
        if not root.is_dir():
            print(f"⛔ НЕ ИЗМЕРЕНО: названное дерево {root} не читается", file=sys.stderr)
            return 2
        print(f"дерево НАЗВАНО входом: {root}")
    else:
        root = Path(__file__).resolve().parents[1]
        print(f"дерево НЕ НАЗВАНО — отвечаю о дереве ПРИБОРА: {root}")

    rep = surface(root, args.subtree)
    print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json
          else format_report(rep))
    if not rep["self_check"]["ok"] or rep["missing_dirs"]:
        return 2
    return 1 if rep["counts"][PARTIAL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
