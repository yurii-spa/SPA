#!/usr/bin/env python3
"""Перепись ПИСАТЕЛЕЙ второго артефакта `data/adapter_status.json` (ADR-707).

Предмет — пункт 1 карточки `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym`
(29.08, САМЫЙ СТАРЫЙ открытый остаток стоячего приказа «Portfolio CIO»; п. 2 той
же карточки закрыт ADR-706):

    «Выяснить, откуда `adapter_status.json` получает запись `aave_arbitrum` — кто
     и когда её пишет (константа в коде производителя или ручная правка).»

Вопрос «кто пишет» у артефакта ЕСТЬ КОМУ задать: документ несёт `generated_by`.
Но это САМО-ОБЪЯВЛЕНИЕ одного писателя, а не замер их множества — ровно та форма,
которую ADR-706 разобрал на оси APY у читателя. Прибор мерит ДВЕ разные вещи:

  **ось W (писатели).** Кто в дереве способен записать ЭТОТ путь, в каком домене
  живёт, какой ФОРМОЙ пишет (атомарной или нет) и объявляет ли себя в
  `generated_by`. Находки: писатель, который пишет и НЕ объявляется (тогда
  `generated_by` врёт о его выходе) · писатель НЕ атомарной формой (инв. #5) ·
  писатель в домене `spa_core/adapters/` (`.claude/rules/adapters.md` запрещает
  дословно: «Адаптеры НИКОГДА не пишут в data/adapter_status.json»).

  **ось L (литерал в опубликованном числе).** Внутри писателя — словарь, который
  уезжает в документ и несёт ключ-число, чьё значение приходит из
  `<что-то>.get(<ключ>, <литерал>)`. Это прямой ответ заказа: «константа
  в коде производителя», с файлом, строкой и самим числом. Рядом мерится,
  объявлен ли род ЭТОГО числа: число без рода читатель не отличит от замера.

  **Ось L смотрит ДВА числа, а не одно (ADR-708).** `apy` РАНЖИРУЕТ, `tvl_usd`
  ДОПУСКАЕТ — порог RiskPolicy $5 млн/пул, и ADR-053 разрешает мерить его только
  живым TVL. ADR-707 мерил одну ось, и три вещи делали прибор зелёным и неправым
  ровно о второй:
    1. `PUBLISHED_NUMBER_KEYS` был кортежем из одного элемента — `tvl_usd` лежал
       вне предмета по КОРТЕЖУ, а не по природе;
    2. умолчание `.get` требовалось `ast.Constant`, а литерал приезжал через
       МОДУЛЬНЫЙ словарь (`_TVL_ESTIMATES.get(key, 0.0)`): `ast.Call` числился
       «разобранным значением» и пропускался МОЛЧА — ни находки, ни третьего
       исхода;
    3. род спрашивался У СЛОВАРЯ («есть ли хоть один ключ на `_source`»), а не у
       ЧИСЛА, поэтому `apy_source`, добавленный ADR-707, начал ручаться за
       соседний `tvl_usd`, у которого рода не было. Починка одной оси ОСЛЕПИЛА
       сторожа на другой.
  Замер на чистой копии origin/main 00b0d461d после починки прибора:
  подстановок литерала **2** ($800 000 000 и $1 200 000 000 — то самое число
  карточки 29.08), чисел без рода **4**. Прежняя редакция прибора показывала
  на том же дереве **0** и **1**.

**Писатель опознаётся по ЦЕЛИ записи, а не по соседству слов.** Первая редакция
прибора считала писателем любой модуль, который где-то УПОМИНАЕТ имя артефакта и
где-то что-то пишет, — и выдала 58 писателей вместо 3: `card_acceptance`,
`kill_switch`, `golive_checker` артефакт только ЧИТАЮТ, а пишут свои. Это ровно
тот дефект, против которого написано правило «токен в файле не делает читателем»,
только с обратной стороны. Мера идёт по ПОТОКУ ЗНАЧЕНИЯ цели: выражение цели
раскрывается через собственные привязки модуля до неподвижной точки, и путь
обязан КОНЧАТЬСЯ именем артефакта.

Третий исход СВОЙ на каждой оси (инв. #17): цель, которую раскрыть не удалось, в
модуле, который артефакт НАЗЫВАЕТ, — это «не измерено» с причиной, под потолком
и с ненулевым кодом возврата, а не «чисто».

ГРАНИЦЫ, названные с величиной (прибор не притворяется полным):
  * цель раскрывается привязками СВОЕГО модуля. Имя, приехавшее из чужого модуля
    (`from X import ADAPTER_STATUS_FILENAME`), мерой не раскрывается — таких в
    дереве ИЗМЕРЕНО отдельной графой `name_from_elsewhere`;
  * ось L идёт по словарям-литералам. Словарь, собранный вызовом или `update`,
    даёт третий исход, а не молчание;
  * «объявляет `generated_by`» есть присутствие ключа в модуле, а не правда его
    значения;
  * тесты исключены намеренно: тест пишет артефакт в свою песочницу — это его
    работа, а не второй писатель прода.

Прибор только ЧИТАЕТ исходники: ни адаптеров, ни сети, ни живого `data/`.

Запуск:
    python3 scripts/adapter_status_writer_census.py
    python3 scripts/adapter_status_writer_census.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from typing import Any, Optional

#: Имя артефакта, писателей которого мы ищем. Одна копия.
ARTIFACT_NAME = "adapter_status.json"

#: Корень дерева (прибор лежит в `scripts/`).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Где искать писателей — ровно то, что синхронизируется в прод
#: (`.claude/rules/deployment.md` п. 2).
SEARCH_ROOTS = ("spa_core", "scripts")

#: Ключи документа, несущие ОПУБЛИКОВАННОЕ ЧИСЛО, по которому РАНЖИРУЮТ или
#: ДОПУСКАЮТ. Осей две, и обе гейтят: `apy` ранжирует (ADR-706), `tvl_usd`
#: ДОПУСКАЕТ — порог RiskPolicy $5 млн/пул, и ADR-053 разрешает мерить его
#: только живым TVL.
#:
#: ADR-707 мерил ОДНУ ось, и кортеж был односоставным. Это и есть дефект,
#: найденный ADR-708: `tvl_usd` лежал вне предмета прибора по кортежу, а не по
#: природе, и ось, которая ДОПУСКАЕТ, не мерилась вовсе.
PUBLISHED_NUMBER_KEYS = ("apy", "tvl_usd")

#: Род числа объявляется ПОИМЁННО, а не суффиксом. ADR-053 назвал поле оси TVL
#: `tvl_source` — НЕ `tvl_usd_source`, — поэтому правило «имя числа + суффикс»
#: на этой оси не работает вовсе, а правило «в словаре есть ХОТЬ ОДИН ключ на
#: `_source`» отвечает на другой вопрос.
#:
#: Именно это и был дефект (ADR-708): проверка стояла НА СЛОВАРЕ, а не на
#: ЧИСЛЕ, поэтому `apy_source`, добавленный ADR-707, начал ручаться ЗА ОБА
#: числа теневого блока — и `tvl_usd` без рода стал невидим для сторожа. Замер:
#: у блоков `morpho_steakhouse` и `aave_arbitrum` рода у TVL не было, а
#: `_dict_declares_provenance` отвечал `True`. Починка чужой оси ОСЛЕПИЛА
#: сторожа на соседней — ровно та форма, против которой весь прибор и написан.
#: ЗНАЧЕНИЕ — МНОЖЕСТВО форм, любая из которых объявляет род ЭТОГО числа.
#: Форм у оси APY действительно две, и это ФАКТ системы, а не послабление:
#: `apy_source` ввёл ADR-706, а `live_apy` — контракт ADR-063, и ровно его
#: читает `status_reader.observed_apy_pct_from_block` («live_apy is the only
#: field that proves observation»). Вложенная запись генератора объявляет род
#: именно так. Первая редакция этой проверки знала одну форму и ОБВИНИЛА
#: вложенную запись ложно (замер: `adapter_status_generator.py:1242`) — та же
#: ошибка, что три ошибки прибора ADR-707, и найдена тем же способом: глазами
#: по каждой строке вывода, а не доверием к числу.
#: У оси TVL форма ОДНА — `tvl_source` (ADR-053). Второй ей не изобретать.
PROVENANCE_KEY: dict[str, frozenset[str]] = {
    "apy": frozenset({"apy_source", "live_apy"}),
    "tvl_usd": frozenset({"tvl_source"}),
}

#: Прежнее имя. Оставлено ТОЛЬКО как якорь: суффикс остаётся верным способом
#: спросить «а вообще род в словаре упомянут», и этот вопрос прибор больше не
#: задаёт — он спрашивает про КАЖДОЕ число.
PROVENANCE_SUFFIX = "_source"

#: Домен, которому писать этот артефакт запрещено ПРАВИЛОМ, а не вкусом.
FORBIDDEN_WRITER_DOMAIN = os.path.join("spa_core", "adapters")

#: Сколько раз распространять привязки при раскрытии цели. Предел объявлен ВХОДОМ
#: (урок ADR-703): достигнутый предел обязан быть отличим от «не нашёл».
DERIVE_ROUNDS = 8

#: ── ПОТОЛКИ. База может только УБЫВАТЬ — тот же порядок, что у
#: `frozen_date_baseline.json` / `site_numbers_baseline.json` / `design_status_baseline.json`.
#: Дописывать сюда, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16).
#: Все числа — ЗАМЕР 2026-10-12 (ADR-707) ПОСЛЕ починки писателя этим же циклом.

#: Третий исход «цель записи не раскрыта» у модуля, который артефакт НАЗЫВАЕТ.
#: Замер: 1 — `scripts/run_tournament_30d.py:598` (одноразовый турнирный скрипт).
#: Ноль здесь недостижим не «по природе», а потому что путь собирается в рантайме;
#: это НЕ «чисто», и ненулевой код возврата про него говорит вслух.
WRITER_UNMEASURED_MAX = 1

#: Третий исход оси L: значение ключа-числа не разобрано. Замер: 0.
LITERAL_UNMEASURED_MAX = 0

#: Цель, приходящая от вызывающего (параметр без умолчания): модуль сам НЕ
#: объявляет, какой артефакт пишет. Это ГРАНИЦА меры, а не находка и не
#: «не измерено» — поэтому у неё свой потолок, равный замеру (26). Рост числа
#: означает новую запись с необъявленной целью и обязан быть замечен.
CALLER_SUPPLIED_MAX = 26

#: Писатель, который пишет артефакт и НЕ ставит `generated_by`: для его выхода
#: само-объявление документа врёт. Замер 4 из 5: `execution/adapter_status.py`
#: (пишет СВОЙ документ целиком и затёр бы поле), `adapters/adapter_registry.py`
#: и `adapters/fluid_fusdc_adapter.py` (дописывают в чужой документ, поле не
#: трогают), `scripts/measure_pin_placement_effect.py` (одноразовый замерщик).
#: Объявляется ОДИН — `monitoring/adapter_status_generator.py`, и он же
#: единственный, кого зовёт дневной цикл.
UNDECLARED_WRITER_MAX = 4

#: Писатель НЕ атомарной формой (инв. #5). Замер 1 из 5 — одноразовый замерщик
#: `scripts/measure_pin_placement_effect.py`; `execution/adapter_status.py`
#: переведён на `atomic_save` ЭТИМ циклом (был 2).
NON_ATOMIC_WRITER_MAX = 1

#: Писатель в домене `spa_core/adapters/` — `.claude/rules/adapters.md` запрещает
#: дословно. Замер 2: `adapter_registry.py` (вызывающих в проде 0, только тесты)
#: и `fluid_fusdc_adapter.py`. Радиус правки больше этого заказа (у первого 20+
#: тестов), поэтому класс ИЗМЕРЕН и НАЗВАН карточкой, а не правлен молча.
FORBIDDEN_DOMAIN_WRITER_MAX = 2

#: ЛИТЕРАЛ в опубликованном числе — предмет заказа. Замер 0.
#: Ось APY: было 3 (`6.5`/`4.1`/`8.0`), снято ADR-707.
#: Ось TVL: было 2 — `_TVL_ESTIMATES[morpho_steakhouse]` = $800 000 000 и
#: `_TVL_ESTIMATES[aave_arbitrum]` = $1 200 000 000 (то самое число карточки
#: 29.08), снято ADR-708. Потолок НОЛЬ: подстановка постоянной под видом
#: наблюдения — ровно то, что решением владельца 2026-08-08 запрещено.
LITERAL_SUBSTITUTION_MAX = 0

#: Опубликованное число БЕЗ СВОЕГО рода. Замер **2**.
#:
#: ⚠️ ЧИСЛО ВЫРОСЛО С 1 ДО 2, И ЭТО НЕ ПОСЛАБЛЕНИЕ — СМЕНИЛАСЬ МЕРА (инв. #16,
#: обоснование обязано стоять здесь и в журнале, и стои́т).
#: Прежняя мера (ADR-707) отвечала на вопрос «есть ли в СЛОВАРЕ хоть один ключ
#: на `_source`» и смотрела ОДНУ ось (`PUBLISHED_NUMBER_KEYS = ("apy",)`).
#: Новая (ADR-708) отвечает на вопрос «объявлен ли род У ЭТОГО ЧИСЛА» и смотрит
#: ОБЕ оси. Новое население — НАДМНОЖЕСТВО прежнего: тот же замер на чистой
#: копии origin/main 00b0d461d даёт **4**, а не 1, и двух из них прежняя мера
#: не видела ПО ПОСТРОЕНИЮ (`adapter_status_generator.py:1286` и `:1295` —
#: `tvl_usd` без `tvl_source`, прикрытые `apy_source`, который там появился
#: ADR-707: починка одной оси ОСЛЕПИЛА сторожа на соседней).
#:
#: Оба остатка — ПОИМЁННО, и оба в домене, которому писать этот артефакт
#: запрещено правилом (карточка `inbox-vtoroi-artefakt-pisateli-iz-zapreschenno`):
#:   * `spa_core/adapters/adapter_registry.py:261`      — ось APY (был и прежде);
#:   * `spa_core/adapters/fluid_fusdc_adapter.py:445`   — ось TVL, НОВАЯ находка:
#:     прежняя мера не могла её увидеть, потому что не смотрела эту ось вовсе.
#: Любая ТРЕТЬЯ запись краснит прибор. Дописывать сюда ЗАПРЕЩЕНО.
PROVENANCE_ABSENT_MAX = 2


# ───────────────────────────── обход дерева ─────────────────────────────────


def _iter_python_files(root_dir: Optional[str] = None) -> list[str]:
    """Файлы дерева. ``root_dir`` объявлен ВХОДОМ: на крафтовом стенде контроль
    должен уметь показать прибору ДРУГОЕ дерево, иначе положительный контроль
    пришлось бы ставить в живой код."""
    base = root_dir or REPO_ROOT
    out: list[str] = []
    for root_name in SEARCH_ROOTS:
        root = os.path.join(base, root_name)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ("tests", "__pycache__", ".git")]
            for fn in filenames:
                if fn.endswith(".py"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _rel(path: str, root_dir: Optional[str] = None) -> str:
    return os.path.relpath(path, root_dir or REPO_ROOT)


# ─────────────────────── раскрытие ЦЕЛИ записи ──────────────────────────────


def _literal_parts(node: ast.AST) -> set[str]:
    """ВСЕ строковые литералы выражения цели.

    Брать «последний» литерал нельзя: ``ast.walk`` обходит в ШИРИНУ, и для
    ``_REPO_ROOT / "data" / "adapter_status.json"`` последним приходит ``"data"``.
    Эта ошибка прятала главного писателя (`adapter_status_generator`) — то есть
    прибор молчал ровно о том модуле, за которым пришёл заказ. Поэтому собираем
    множество и спрашиваем «есть ли СРЕДИ них наше имя»; цена — путь, который
    упоминает имя артефакта в несвязанном литерале, будет назван писателем, и
    эта односторонность промахивается в сторону НАХОДКИ (её видно глазами в
    отчёте), а не в сторону молчания.
    """
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value)
    return out


def _targets_artifact(tails: set[str]) -> bool:
    """Кончается ли раскрытый путь именем нашего артефакта."""
    return any(t.endswith(ARTIFACT_NAME) for t in tails)


def _scope_bindings(tree: ast.Module) -> dict[int, dict[str, list[ast.AST]]]:
    """Привязки имён, СКОУПИРОВАННЫЕ по функции: id(функции) → {имя: [выражения]}.

    Плоский набор привязок на модуль был ПЕРВОЙ ошибкой этого прибора: имя `path`
    связывают по-своему шесть разных функций `card_acceptance.py`, и слитый набор
    читал привязку одной функции как привязку другой — ровно тот класс, что у
    «имитатор обязан носить имя подменяемого». Поэтому ключ — функция, а модульный
    уровень лежит под ключом 0 и служит ТОЛЬКО источником констант.

    Список, а не одно значение, — ВТОРАЯ исправленная ошибка: `output_path`
    у `adapter_status_generator.write()` есть И параметр с умолчанием
    `_STATUS_FILE`, И присваивание `output_path = Path(output_path)`. Взяв
    «первое найденное», мера теряла умолчание — то есть ровно тот путь, который
    функция пишет, когда её зовут без аргумента (а зовут её так из цикла).
    """
    out: dict[int, dict[str, list[ast.AST]]] = {0: {}}

    def _add(bucket: dict[str, list[ast.AST]], name: str, expr: ast.AST) -> None:
        bucket.setdefault(name, []).append(expr)

    def _collect(scope_key: int, body: list[ast.stmt]) -> None:
        bucket = out.setdefault(scope_key, {})
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node is not stmt:
                    continue
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (node.targets if isinstance(node, ast.Assign)
                               else [node.target])
                    if len(targets) == 1 and isinstance(targets[0], ast.Name) \
                            and node.value is not None:
                        _add(bucket, targets[0].id, node.value)
                elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                    if isinstance(node.optional_vars, ast.Name):
                        _add(bucket, node.optional_vars.id, node.context_expr)

    _collect(0, tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect(id(node), node.body)
            bucket = out.setdefault(id(node), {})
            args = node.args
            pos = list(args.posonlyargs) + list(args.args)
            if args.defaults:
                for a, d in zip(pos[len(pos) - len(args.defaults):], args.defaults):
                    _add(bucket, a.arg, d)
            for a, d in zip(args.kwonlyargs, args.kw_defaults):
                if d is not None:
                    _add(bucket, a.arg, d)
            # Параметр, у которого умолчания НЕТ: цель приходит от вызывающего.
            # Это ГРАНИЦА меры, и она обязана быть названа, а не выдана за «нашёл».
            named = {a.arg for a in pos} | {a.arg for a in args.kwonlyargs}
            for a in sorted(named):
                if a not in bucket:
                    _add(bucket, a, _CALLER_SUPPLIED)
    return out


#: Заглушка «значение приходит от вызывающего». Отдельный объект, чтобы
#: раскрытие могло назвать эту границу ИМЕНЕМ, а не выдать её за «не нашёл».
_CALLER_SUPPLIED = ast.Constant(value="<caller-supplied>")

#: Признаки одноразового стенда в цепочке раскрытия цели. Запись в стенд — не
#: писатель прод-артефакта; она обязана быть НАЗВАНА отдельно, а не обвинена.
_STAND_MARKERS = ("mkdtemp", "TemporaryDirectory", "mkstemp", "tmp_path",
                  "tmpdir", "tmp_dir", "sandbox", "gettempdir")


def _enclosing_funcs(tree: ast.Module) -> dict[int, int]:
    """id(узла) → id(ближайшей объемлющей функции) (0 — модульный уровень)."""
    out: dict[int, int] = {}

    def walk(node: ast.AST, scope: int) -> None:
        for child in ast.iter_child_nodes(node):
            nxt = id(child) if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            out[id(child)] = nxt
            walk(child, nxt)

    out[id(tree)] = 0
    walk(tree, 0)
    return out


def _resolve_tails(node: ast.AST, binds: dict[str, list[ast.AST]],
                   mod_binds: dict[str, list[ast.AST]],
                   rounds: int = DERIVE_ROUNDS) -> tuple[set[str], str]:
    """Хвосты пути цели + ИСХОД раскрытия.

    Исход: "resolved" (наш артефакт) · "stand" (наш, но в одноразовом стенде) ·
    "not_ours" (раскрыт КОНКРЕТНЫЙ путь, и он чужой) · "caller_supplied"
    (ничего не раскрылось, и в цепочке параметр без умолчания) · "unresolved".

    Порядок исходов существен: раскрытый конкретный хвост, который нашим именем
    не кончается, есть ОПРЕДЕЛЁННОЕ «не наш писатель», а не граница меры. Первая
    редакция судила наоборот и объявила границей 51 запись, из которых почти все
    пишут заведомо другие файлы.

    Предел ``rounds`` объявлен ВХОДОМ (урок ADR-703): достигнутый предел обязан
    быть отличим от «не нашёл».
    """
    seen: set[str] = set()
    tails: set[str] = set()
    frontier: list[ast.AST] = [node]
    saw_caller = False
    saw_stand = False
    expanded = False

    for _ in range(rounds):
        if not frontier:
            break
        nxt: list[ast.AST] = []
        for expr in frontier:
            if expr is _CALLER_SUPPLIED:
                saw_caller = True
                continue
            tails |= _literal_parts(expr)
            for sub in ast.walk(expr):
                if isinstance(sub, ast.Name):
                    if sub.id in _STAND_MARKERS:
                        saw_stand = True
                    if sub.id in seen:
                        continue
                    seen.add(sub.id)
                    for cand in (binds.get(sub.id) or mod_binds.get(sub.id) or []):
                        nxt.append(cand)
                        expanded = True
                elif isinstance(sub, ast.Attribute) and sub.attr in _STAND_MARKERS:
                    saw_stand = True
                elif isinstance(sub, ast.Call):
                    fn = _callee_name(sub.func)
                    if any(m in fn for m in _STAND_MARKERS):
                        saw_stand = True
        frontier = nxt

    if _targets_artifact(tails):
        return tails, ("stand" if saw_stand else "resolved")
    if tails:
        return tails, "not_ours"
    if saw_caller:
        return tails, "caller_supplied"
    return tails, ("unresolved_named" if expanded else "unresolved")


# ───────────────────────── вызовы записи и их цели ──────────────────────────


class _WriteSite:
    def __init__(self, kind: str, line: int, target: Optional[ast.AST]) -> None:
        self.kind = kind          # "atomic" | "plain_open"
        self.line = line
        self.target = target      # выражение ЦЕЛИ записи


def _callee_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _callee_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _open_mode(call: ast.Call, *, arg_index: int) -> Optional[str]:
    """Режим открытия файла. Неизвестен ⇒ None.

    ``arg_index`` существен: у встроенного ``open(path, mode)`` режим ВТОРОЙ, а у
    метода ``path.open(mode)`` — ПЕРВЫЙ. Одна мерка на две формы читала у метода
    режим там, где его нет, возвращала None и молча пропускала запись: так
    `execution/adapter_status.py` не попадал в писатели вовсе, хотя пишет
    артефакт сырым ``open(..., "w")`` — нарушение инв. #5, за которым и пришёл
    этот прибор.
    """
    if len(call.args) > arg_index:
        a = call.args[arg_index]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) \
                and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _write_sites(tree: ast.Module) -> list[_WriteSite]:
    """Вызовы записи с их ЦЕЛЬЮ.

    `atomic_save(data, path)` — цель ВТОРОЙ аргумент (urok: порядок аргументов
    здесь именно такой). `open(path, "w")` / `<путь>.open("w")` /
    `<путь>.write_text(...)` — не атомарные формы.
    """
    sites: list[_WriteSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = _callee_name(node.func)
        if fname in ("atomic_save", "atomic_save_text"):
            tgt = node.args[1] if len(node.args) > 1 else None
            sites.append(_WriteSite("atomic", node.lineno, tgt))
        elif fname == "open" or (isinstance(node.func, ast.Attribute)
                                 and node.func.attr == "open"):
            is_method = isinstance(node.func, ast.Attribute)
            mode = _open_mode(node, arg_index=0 if is_method else 1)
            if not (mode and ("w" in mode or "a" in mode)):
                continue
            tgt = node.func.value if is_method else (
                node.args[0] if node.args else None)
            sites.append(_WriteSite("plain_open", node.lineno, tgt))
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "write_text":
            sites.append(_WriteSite("plain_open", node.lineno, node.func.value))
        elif fname in ("os.replace", "os.rename", "shutil.move"):
            # ПОСАДКА атомарной записи: `tmp + os.replace(tmp, dst)` — дословно
            # рецепт инв. #5, и цель здесь ВТОРОЙ аргумент. Без этой формы прибор
            # обвинил бы `adapter_status_generator.write()` в неатомарности, хотя
            # тот пишет ровно по рецепту (своими руками, не через atomic_save).
            tgt = node.args[1] if len(node.args) > 1 else None
            sites.append(_WriteSite("atomic", node.lineno, tgt))
    return sites


def _declares_generated_by(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "generated_by":
            return True
    return False


def _names_artifact_anywhere(tree: ast.Module) -> bool:
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                and sub.value.endswith(ARTIFACT_NAME):
            return True
    return False


# ─────────────────────────── ось L: литерал в числе ─────────────────────────


def _get_literal_default(node: ast.AST) -> Optional[tuple[str, float]]:
    """`X.get("ключ", <число>)` ⇒ ("ключ", число). Иначе None.

    `bool` исключён: `True` не доходность.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "get" or len(node.args) != 2:
        return None
    key, default = node.args
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return None
    if not (isinstance(default, ast.Constant)
            and isinstance(default.value, (int, float))
            and not isinstance(default.value, bool)):
        return None
    return key.value, float(default.value)


def _assigned_literal_gets(tree: ast.Module) -> dict[str, tuple[str, float, int]]:
    out: dict[str, tuple[str, float, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        got = _get_literal_default(node.value)
        if got is not None:
            out[tgt.id] = (got[0], got[1], node.lineno)
        elif isinstance(node.value, ast.Tuple):
            # `a, b = X.get("k", 1.0), src` — разворачивать не требуется: ось L
            # ищет значение КЛЮЧА словаря, а не кортежи. Отмечено, чтобы форма
            # не выглядела пропущенной молча.
            continue
    return out


def _published_dicts(tree: ast.Module) -> list[ast.Dict]:
    out: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if any(k in PUBLISHED_NUMBER_KEYS for k in keys):
            out.append(node)
    return out


def _dict_string_keys(d: ast.Dict) -> set[str]:
    return {k.value for k in d.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _number_declares_provenance(d: ast.Dict, number_key: str) -> bool:
    """Объявлен ли род У ЭТОГО ЧИСЛА (а не «упомянут ли род в словаре»).

    ADR-708: прежняя редакция спрашивала про СЛОВАРЬ («есть ключ на
    ``_source``?») и потому считала объявленным ЛЮБОЕ число в словаре, где род
    объявлен хотя бы у одного. После ADR-707, добавившего теневым блокам
    ``apy_source``, это ручательство распространилось на ``tvl_usd``, у которого
    рода не было, — и сторож замолчал ровно о том числе, за которым пришёл
    следующий заказ.

    Имя поля рода берётся из объявленного словаря ``PROVENANCE_KEY``, а не
    склеивается суффиксом: ось TVL называет его ``tvl_source``, и склейка
    ``tvl_usd`` + ``_source`` не нашла бы его никогда.
    """
    want = PROVENANCE_KEY.get(number_key)
    if not want:
        return False
    return bool(want & _dict_string_keys(d))


_RESOLVED_VALUE_NODES = (ast.Constant, ast.Name, ast.Attribute, ast.Subscript,
                         ast.IfExp, ast.Call, ast.BinOp, ast.UnaryOp,
                         ast.BoolOp, ast.Compare, ast.Tuple, ast.List, ast.Dict)


def _module_literal_dicts(tree: ast.Module) -> dict[str, dict[str, float]]:
    """Модульные словари вида ``NAME = {"k": <число>, ...}`` → их содержимое.

    ADR-708: литерал доезжал до опубликованного числа НЕ вторым аргументом
    ``.get``, а через такой словарь — ``_TVL_ESTIMATES.get(key, 0.0)``, где
    ``_TVL_ESTIMATES["aave_arbitrum"] == 1_200_000_000.0``. Прежняя редакция
    требовала у умолчания ``ast.Constant``, получала ``ast.Call`` и МОЛЧА шла
    дальше (``ast.Call`` входит в ``_RESOLVED_VALUE_NODES``) — ни находки, ни
    третьего исхода. Прибор был зелёным и неправым ровно о том числе, за которым
    пришёл заказ.

    Раскрываются только словари, у которых КЛЮЧ — строковый литерал, а ЗНАЧЕНИЕ
    — числовой литерал. Словарь, собранный вызовом или ``update``, здесь не
    появляется: это третий исход у вызывающего, а не молчание.
    """
    out: dict[str, dict[str, float]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        table: dict[str, float] = {}
        for k, v in zip(value.keys, value.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) \
                    and not isinstance(v.value, bool):
                table[k.value] = float(v.value)
        if table:
            out[targets[0].id] = table
    return out


def _resolve_literal(node: ast.AST,
                     tables: dict[str, dict[str, float]]) -> Optional[tuple[str, float]]:
    """Числовой литерал, до которого раскрывается ``node`` — или ``None``.

    Три формы, и все три встречаются у писателей артефакта:
      * ``3.2``                        → ("", 3.2)         — просто литерал;
      * ``TABLE.get("k", 0.0)``        → ("TABLE[k]", lit)  — модульный словарь;
      * ``TABLE["k"]``                 → ("TABLE[k]", lit)  — он же индексом.

    Ключ, которого в словаре НЕТ, раскрывается до умолчания самого ``.get``
    (``_TVL_ESTIMATES.get(key, 0.0)`` при неизвестном ключе даёт ``0.0``) — и это
    тоже литерал в опубликованном числе, просто равный нулю. Инвариант #17
    ровно про него: «оценки нет» и «оценка ноль» обязаны быть различимы, а
    ``0.0`` склеивает их.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return "", float(node.value)

    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id in tables \
            and isinstance(node.slice, ast.Constant) \
            and isinstance(node.slice.value, str):
        table = tables[node.value.id]
        key = node.slice.value
        if key in table:
            return f"{node.value.id}[{key}]", table[key]
        return None

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and len(node.args) == 2 \
            and isinstance(node.func.value, ast.Name) \
            and node.func.value.id in tables:
        table = tables[node.func.value.id]
        name = node.func.value.id
        key_node, default = node.args
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str) \
                and key_node.value in table:
            return f"{name}[{key_node.value}]", table[key_node.value]
        # Ключ не литерал (переменная цикла) либо его в словаре нет ⇒ значением
        # станет умолчание `.get`. Оно литерал — значит число всё равно литеральное.
        inner = _resolve_literal(default, tables)
        if inner is not None:
            return f"{name}.get(…, {inner[1]!r})", inner[1]
        return None

    return None


def _get_default_literal(node: ast.AST,
                         tables: dict[str, dict[str, float]]
                         ) -> Optional[tuple[str, float, str]]:
    """``X.get("ключ", <раскрываемое до литерала>)`` ⇒ (ключ, литерал, как).

    Расширение ``_get_literal_default`` (ADR-707) на умолчание, которое само
    является модульным словарём: это и есть дверь ADR-708.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "get" or len(node.args) != 2:
        return None
    key, default = node.args
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return None
    resolved = _resolve_literal(default, tables)
    if resolved is None:
        return None
    via = "inline" if resolved[0] == "" else f"module_dict:{resolved[0]}"
    return key.value, resolved[1], via


def _is_two_arg_get(node: ast.AST) -> bool:
    """Является ли узел формой ``X.get(k, default)`` — у неё умолчание ЕСТЬ."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and len(node.args) == 2)


def _literal_axis(path: str, tree: ast.Module,
                  root_dir: Optional[str] = None) -> dict[str, Any]:
    bound = _assigned_literal_gets(tree)
    tables = _module_literal_dicts(tree)
    findings: list[dict[str, Any]] = []
    unmeasured: list[dict[str, Any]] = []
    no_provenance: list[dict[str, Any]] = []
    dicts = _published_dicts(tree)

    for d in dicts:
        for key, value in zip(d.keys, d.values):
            if not (isinstance(key, ast.Constant)
                    and key.value in PUBLISHED_NUMBER_KEYS):
                continue

            # Род спрашивается У ЧИСЛА, а не у словаря (ADR-708).
            if not _number_declares_provenance(d, key.value):
                no_provenance.append({
                    "file": _rel(path, root_dir), "line": d.lineno,
                    "field": key.value,
                    "want": sorted(PROVENANCE_KEY.get(key.value) or ()),
                })

            direct = _get_default_literal(value, tables)
            if direct is not None:
                findings.append({
                    "file": _rel(path, root_dir), "line": value.lineno,
                    "field": key.value, "source_key": direct[0],
                    "literal": direct[1], "via": direct[2],
                })
                continue
            if isinstance(value, ast.Name) and value.id in bound:
                k, lit, ln = bound[value.id]
                findings.append({
                    "file": _rel(path, root_dir), "line": ln,
                    "field": key.value, "source_key": k,
                    "literal": lit, "via": f"name:{value.id}",
                })
                continue
            # Умолчание У ФОРМЫ ЕСТЬ, а до литерала оно не раскрылось ⇒ ТРЕТИЙ
            # ИСХОД. Прежняя редакция здесь молчала, и именно так пропускался
            # `_TVL_ESTIMATES`: `ast.Call` числился «разобранным значением».
            if _is_two_arg_get(value):
                unmeasured.append({
                    "file": _rel(path, root_dir), "line": value.lineno,
                    "field": key.value,
                    "reason": ("умолчание `.get` до литерала не раскрыто: "
                               f"{type(value.args[1]).__name__}"),
                })
                continue
            if isinstance(value, _RESOLVED_VALUE_NODES):
                continue
            unmeasured.append({
                "file": _rel(path, root_dir), "line": value.lineno,
                "field": key.value,
                "reason": f"значение не разобрано: {type(value).__name__}",
            })

    return {
        "published_dicts": len(dicts),
        "substitutions": findings,
        "no_provenance": no_provenance,
        "unmeasured": unmeasured,
        "literal_tables": sorted(tables),
    }


# ───────────────────────────────── замер ────────────────────────────────────


def measure(root_dir: Optional[str] = None) -> dict[str, Any]:
    """Полный замер обеих осей. Только чтение исходников.

    ``root_dir`` — дерево, которое мерим (по умолчанию своё). Дверь объявлена
    входом ради контролей: положительный контроль кладёт крафтовый модуль в
    одноразовый стенд, а не в живой код.
    """
    root = root_dir or REPO_ROOT
    writers: list[dict[str, Any]] = []
    writer_unmeasured: list[dict[str, Any]] = []
    caller_supplied: list[dict[str, Any]] = []
    stands: list[dict[str, Any]] = []
    name_from_elsewhere: list[dict[str, Any]] = []
    files = _iter_python_files(root)

    for path in files:
        rel = _rel(path, root)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (OSError, SyntaxError) as exc:
            writer_unmeasured.append({"file": rel, "reason":
                                      f"{type(exc).__name__}: {exc}"})
            continue

        names_it = _names_artifact_anywhere(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    if "ADAPTER_STATUS" in a.name.upper() \
                            or a.name in ("_DEFAULT_OUTPUT",):
                        name_from_elsewhere.append(
                            {"file": rel, "imports": a.name, "from": node.module})

        sites = _write_sites(tree)
        if not sites:
            continue
        scopes = _scope_bindings(tree)
        encl = _enclosing_funcs(tree)
        mod_binds = scopes.get(0, {})

        hit: list[_WriteSite] = []
        for s in sites:
            if s.target is None:
                if names_it:
                    writer_unmeasured.append({
                        "file": rel,
                        "reason": f"запись без опознанной цели (стр. {s.line})"})
                continue
            scope_key = encl.get(id(s.target), 0)
            binds = scopes.get(scope_key, {})
            _tails, outcome = _resolve_tails(s.target, binds, mod_binds)
            if outcome == "resolved":
                hit.append(s)
            elif outcome == "stand":
                stands.append({"file": rel, "line": s.line, "kind": s.kind})
            elif outcome == "caller_supplied":
                # ГРАНИЦА меры, названная вслух: путь приходит от вызывающего,
                # и модуль сам не объявляет, какой артефакт пишет. Это не находка
                # и не «не измерено» — отдельный исход со своим потолком.
                if names_it:
                    caller_supplied.append({"file": rel, "line": s.line})
            elif outcome == "not_ours":
                continue
            elif names_it and outcome in ("unresolved", "unresolved_named"):
                writer_unmeasured.append({
                    "file": rel,
                    "reason": (f"модуль называет артефакт, цель записи на стр. "
                               f"{s.line} не раскрыта ({outcome})")})

        if not hit:
            continue

        domain = os.path.join(*rel.split(os.sep)[:2]) if os.sep in rel else rel
        non_atomic_lines = sorted(s.line for s in hit if s.kind != "atomic")
        has_atomic = any(s.kind == "atomic" for s in hit)
        # Запись ЧЕРЕЗ временный файл: `open(tmp,"w")` рядом с `os.replace(tmp,dst)`
        # — одна операция, а не две. Неатомарной её делает ОТСУТСТВИЕ посадки.
        if has_atomic:
            non_atomic_lines = []
        writers.append({
            "file": rel,
            "domain": domain,
            "write_kinds": sorted({s.kind for s in hit}),
            "lines": sorted(s.line for s in hit),
            "non_atomic_lines": non_atomic_lines,
            "declares_generated_by": _declares_generated_by(tree),
            "forbidden_domain": rel.startswith(FORBIDDEN_WRITER_DOMAIN + os.sep),
            "literal": _literal_axis(path, tree, root),
        })

    undeclared = [w for w in writers if not w["declares_generated_by"]]
    non_atomic = [w for w in writers if w["non_atomic_lines"]]
    forbidden = [w for w in writers if w["forbidden_domain"]]
    substitutions = [s for w in writers for s in w["literal"]["substitutions"]]
    no_provenance = [s for w in writers for s in w["literal"]["no_provenance"]]
    lit_unmeasured = [s for w in writers for s in w["literal"]["unmeasured"]]

    return {
        "artifact": ARTIFACT_NAME,
        "root": root,
        "files_scanned": len(files),
        "writers": writers,
        "counts": {
            "writers": len(writers),
            "undeclared": len(undeclared),
            "non_atomic": len(non_atomic),
            "forbidden_domain": len(forbidden),
            "literal_substitution": len(substitutions),
            "provenance_absent": len(no_provenance),
            "writer_unmeasured": len(writer_unmeasured),
            "literal_unmeasured": len(lit_unmeasured),
            "caller_supplied": len(caller_supplied),
            "stand": len(stands),
            "name_from_elsewhere": len(name_from_elsewhere),
        },
        "undeclared": undeclared,
        "non_atomic": non_atomic,
        "forbidden": forbidden,
        "substitutions": substitutions,
        "provenance_absent": no_provenance,
        "writer_unmeasured": writer_unmeasured,
        "literal_unmeasured": lit_unmeasured,
        "caller_supplied": caller_supplied,
        "stand": stands,
        "name_from_elsewhere": name_from_elsewhere,
        "ceilings": {
            "undeclared": UNDECLARED_WRITER_MAX,
            "non_atomic": NON_ATOMIC_WRITER_MAX,
            "forbidden_domain": FORBIDDEN_DOMAIN_WRITER_MAX,
            "literal_substitution": LITERAL_SUBSTITUTION_MAX,
            "provenance_absent": PROVENANCE_ABSENT_MAX,
            "writer_unmeasured": WRITER_UNMEASURED_MAX,
            "literal_unmeasured": LITERAL_UNMEASURED_MAX,
            "caller_supplied": CALLER_SUPPLIED_MAX,
        },
    }


def verdict(rep: dict[str, Any]) -> tuple[int, list[str]]:
    """Код возврата и строки вердикта.

    0 — всё в своих потолках · 1 — находка выше потолка · 2 — НЕ ИЗМЕРЕНО.
    «Не измерено» судится ПЕРВЫМ: оно не имеет права выглядеть как «чисто».
    """
    c, cl = rep["counts"], rep["ceilings"]
    lines: list[str] = []

    if c["writers"] == 0:
        return 2, ["НЕ ИЗМЕРЕНО: писателей не найдено ВОВСЕ — у артефакта есть "
                   "`generated_by`, значит писатель существует; ноль здесь есть "
                   "отказ меры, а не чистота"]
    if c["caller_supplied"] > cl["caller_supplied"]:
        lines.append(f"НЕ ИЗМЕРЕНО (цель приходит от вызывающего) "
                     f"{c['caller_supplied']} > потолок {cl['caller_supplied']}")
        for r in rep["caller_supplied"][:6]:
            lines.append(f"  [от вызывающего] {r['file']}:{r['line']}")
        return 2, lines
    if c["writer_unmeasured"] > cl["writer_unmeasured"]:
        lines.append(f"НЕ ИЗМЕРЕНО (цель записи не раскрыта) "
                     f"{c['writer_unmeasured']} > потолок {cl['writer_unmeasured']}")
        for r in rep["writer_unmeasured"][:6]:
            lines.append(f"  [не раскрыто] {r['file']}: {r['reason']}")
        return 2, lines
    if c["literal_unmeasured"] > cl["literal_unmeasured"]:
        lines.append(f"НЕ ИЗМЕРЕНО (значение числа не разобрано) "
                     f"{c['literal_unmeasured']} > потолок "
                     f"{cl['literal_unmeasured']}")
        for r in rep["literal_unmeasured"][:6]:
            lines.append(f"  [не разобрано] {r['file']}:{r['line']} {r['field']} "
                         f"— {r['reason']}")
        return 2, lines

    code = 0
    for key, label in (("literal_substitution", "ЛИТЕРАЛ в опубликованном числе"),
                       ("provenance_absent", "опубликованное число БЕЗ рода"),
                       ("undeclared", "писатель НЕ объявляет себя в generated_by"),
                       ("non_atomic", "писатель НЕ атомарной формой (инв. #5)"),
                       ("forbidden_domain",
                        "писатель в домене adapters (правило запрещает)")):
        if c[key] > cl[key]:
            code = 1
            lines.append(f"НАХОДКА · {label}: {c[key]} > потолок {cl[key]}")
    return code, lines


def report(rep: dict[str, Any]) -> str:
    c = rep["counts"]
    out = [
        f"Писатели второго артефакта `{rep['artifact']}` "
        f"(прочитано файлов {rep['files_scanned']}):",
        f"  писателей {c['writers']} · не объявляются {c['undeclared']} "
        f"(потолок {rep['ceilings']['undeclared']}) "
        f"· не атомарны {c['non_atomic']} "
        f"· запрещённый домен {c['forbidden_domain']}",
        f"  ось L: подстановок литерала {c['literal_substitution']} "
        f"· чисел без рода {c['provenance_absent']}",
        f"  НЕ ИЗМЕРЕНО: целей {c['writer_unmeasured']} "
        f"· значений {c['literal_unmeasured']}",
        f"  ГРАНИЦЫ (не находки): цель от вызывающего {c['caller_supplied']} "
        f"(потолок {rep['ceilings']['caller_supplied']}) "
        f"· запись в одноразовый стенд {c['stand']} "
        f"· имя из чужого модуля {c['name_from_elsewhere']}",
        "",
    ]
    for w in rep["writers"]:
        mark = []
        if not w["declares_generated_by"]:
            mark.append("НЕ ОБЪЯВЛЯЕТСЯ")
        if w["non_atomic_lines"]:
            mark.append(f"НЕ АТОМАРНО (стр. {w['non_atomic_lines']})")
        if w["forbidden_domain"]:
            mark.append("ЗАПРЕЩЁННЫЙ ДОМЕН")
        suffix = ("  ← " + " · ".join(mark)) if mark else ""
        out.append(f"  [{w['domain']}] {w['file']}:{w['lines']} "
                   f"({'/'.join(w['write_kinds'])}){suffix}")
    for s in rep["substitutions"]:
        out.append(f"  [литерал] {s['file']}:{s['line']} → поле {s['field']!r} "
                   f"= .get({s['source_key']!r}, {s['literal']}) [{s['via']}]")
    for s in rep["provenance_absent"]:
        out.append(f"  [без рода] {s['file']}:{s['line']} → поле {s['field']!r} "
                   f"опубликовано, а род не объявлен ни одним из "
                   f"{s.get('want') or []}")
    for r in rep["name_from_elsewhere"]:
        out.append(f"  [имя извне] {r['file']} ← {r['from']}.{r['imports']}")
    code, lines = verdict(rep)
    out.append("")
    out.extend(lines or ["✅ все классы в своих потолках"])
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--root", default=None, help="дерево для замера (по умолчанию своё)")
    args = ap.parse_args(argv)
    rep = measure(args.root)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(report(rep))
    return verdict(rep)[0]


if __name__ == "__main__":
    raise SystemExit(main())
