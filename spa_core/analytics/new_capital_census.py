#!/usr/bin/env python3
"""Новые деньги §20 приказа владельца: отличает ли система ВВОД от ПЕРЕКЛАДКИ.

Критерий §20 `New capital` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G951 п. 1, цикл #1081.

Дословно §20: «Новый incoming capital должен использоваться умнее, чем
существующий капитал. Если поступает новый депозит, сначала направлять его в
underallocated opportunities согласно Target Allocation. Не делать: withdraw A
/ deposit B — если тот же target можно приблизить простым: new money → B без
лишнего turnover.»

Прибор НИЧЕГО НЕ ПРАВИТ: ни порога, ни политики, ни гейта, ни аллокатора, ни
тюнера, ни писателя журнала ходов. §20 просит, чтобы ход «ввод» стоил дешевле
хода «перекладка», а цена хода на денежном пути — предмет №1 ADR-285 и уходит
карточкой владельцу.

Четыре вопроса, и ни один не выводится из другого
------------------------------------------------------------------------------
Заказ G951 п. 1 ставит первые три дословно, четвёртый — условие того же заказа
(«иначе ответ будет верен СЛУЧАЙНО»).

1. **(а) есть ли у системы понятие «новые деньги» ОТДЕЛЬНО от «переложить
   существующие»** (:data:`EXPRESS_KINDS`, ввезено из §17). Спрашивается у
   ЖИВЫХ контрактов — подпись ``rebalance_economics.evaluate``, подписи
   ``RiskPolicy.check_new_position``/``check_portfolio_health``, поля
   ``PortfolioState``/``Position``, запись кандидата аллокатора, ячейка журнала
   ходов, — а не у памяти автора.
2. **(б) различает ли хоть одна дверь ход «ввод» от хода «перекладка»**
   (:data:`SOURCE_KINDS`). Мерится ДИФФЕРЕНЦИАЛЬНО, и возмущается РОВНО
   источник денег: ФОНДИРУЕМАЯ НОГА в обеих сценах ОДНА И ТА ЖЕ (``B``
   +$10 000 до тех же $35 000), меняется лишь, откуда приходит доллар — из
   нераспределённого кэша или из продажи ``A``. Род присваивается по СМЕНЕ
   вердикта, а не по чтению кода глазами.
3. **(в) заряжается ли стоимость ОБОРОТА на ход, который оборота не требует**
   (:data:`CHARGE_KINDS`, ввезено из §13). Оборот — это ровно та величина,
   которую §20 называет «лишним turnover»; у двери цены на ней стоят ЧЕТЫРЕ
   ворот из десяти (``move_turnover_ok``, ``move_amount_ok``,
   ``week_turnover_ok``, ``day_turnover_ok``), и вопрос в том, различают ли они
   источник доллара.
4. **(г) ДОСТИЖИМ ли вопрос вообще** (:func:`reachability`). Две половины:
   приходили ли новые деньги на живом треке (ячейка ``capital`` журнала ходов)
   и какой потолок связывает раньше, если новые деньги направить в
   underallocated T3.

Почему вопросов четыре, а не один
------------------------------------------------------------------------------
Урок ADR-943, повторённый §16…§19: замкнув их в один перечень, две оси понесли
бы ОДИН бит. Состояние «у двери цены источник доллара ВЫРАЗИМ формой ног, цена
хода от него меняется, а ОБОРОТ — величина, про которую §20 и написан, — не
меняется ни на цент» по шкале выразимости выглядит как лучший исход. Оно и
найдено.

🪤 ЛОВУШКА ПЕРВАЯ: §20 про ОБОРОТ, а не про газ, и спутать их значит выдумать находку
------------------------------------------------------------------------------
Цена хода у двери — сумма трёх слагаемых (газ на каждую тронутую позицию,
проскальзывание на оборот, мост при нескольких сетях). Перекладка трогает ДВЕ
позиции, ввод — ОДНУ, поэтому ГАЗ между сценами различается всегда, сам собой,
и первая редакция этого прибора прочла бы это как «дверь различает источник».
Не различает: различается ЧИСЛО НОГ, а не род хода, и величина сдвига есть
ровно один литерал ``GAS_USD_PER_POSITION_CHANGE[chain]``. Поэтому слагаемые
меряются ПООТДЕЛЬНО (:func:`distinction`), и род оси (б) присваивается по
сдвигу ОБОРОТА, а не по сдвигу суммы.

🪤 ЛОВУШКА ВТОРАЯ: ВЫИГРЫШ двух сцен равным быть НЕ МОЖЕТ, и это не дефект
------------------------------------------------------------------------------
Соблазн — потребовать от сцен одинакового выигрыша, чтобы «возмущался ровно
источник». Такое требование невыполнимо по построению: доллар, пришедший из
кэша, зарабатывал 0 % и начинает зарабатывать ставку пула, а доллар из продажи
``A`` зарабатывал ставку ``A``. Разный выигрыш — ВЕРНАЯ экономика, а не
расхождение сцен. Поэтому сцены равны по ЦЕЛЕВОЙ КНИГЕ, по капиталу, по
фондируемой ноге и по сумме развёрнутого после хода, а выигрыш печатается
рядом как измеренная разница, а не выравнивается подгонкой ставок.

🪤 ЛОВУШКА ТРЕТЬЯ: «вердикт не изменился» без контроля — это о приборе, а не о мире
------------------------------------------------------------------------------
У КАЖДОЙ сцены свой положительный контроль, и он возмущает величину, которую
дверь СВЯЗЫВАЕТ ЗАВЕДОМО (§16/§18/§41): у двери цены — выигрыш (ставка пула
назначения) и недельный бюджет оборота. Контроль не сменил вердикт ⇒ ответ
прибора об источнике денег НЕ ВЫДАЁТСЯ (``unmeasured`` с названной причиной), а
не печатается как находка. «Не изменился» и «прибор не работает» выглядят
одинаково.

🪤 ЛОВУШКА ЧЕТВЁРТАЯ: словарь родов хода СУЩЕСТВУЕТ, и спросить надо ЕГО читателей
------------------------------------------------------------------------------
Система уже знает, что ввод дешевле перекладки: ``fee_calculator._GAS_UNITS``
несёт ТРИ операции (``deposit``/``withdraw``/``rebalance``) на пяти сетях, и на
Ethereum это 200 000 против 500 000 единиц газа, то есть ×2.5. Поэтому вопрос
§20 не «умеем ли мы различать», а «кто это различение ЧИТАЕТ» — и читателей
надо мерить AST'ом, а не подстрокой: слово ``deposit`` в докстринге отвечает на
вопрос «есть ли такое слово в файле», а не «передано ли оно ИМЕННО В ЭТОМ
зове» (дословно приём §17 ``money_path_axis_call_forms``).

**И «зов с подходящим литералом» читателем ТОЖЕ не является — это та же
подстрока на уровень выше.** Первая редакция этого прибора насчитала 15
читателей, и среди них были ``add_argument("rebalance")``,
``_execute_single_tx("withdraw")`` и ``enqueue_digest("rebalance")`` — зовы, не
имеющие к словарю газа никакого отношения и совпавшие с ним РОВНО строкой.
Читателем является зов, который ДОХОДИТ до словаря, поэтому перечень имён
ЗАСЕВАЕТСЯ замером (:func:`_operation_taking_callees`): корень — функции
``fee_calculator``, у которых есть параметр с именем ``operation`` (меряется
``ast``, не списком из головы), плюс прямые обращения к самому словарю; затем
добавляются ЧУЖИЕ функции, которые пробрасывают свой параметр в уже известное
имя, — до неподвижной точки (приём ADR-932). Исчерпание круга — третий исход
(``unmeasured``), а не обрезанный ответ.

🪤 ЛОВУШКА ПЯТАЯ: достижимость — отдельный замер, и «не достижимо» ответом НЕ является
------------------------------------------------------------------------------
Готовый контрапункт заказа G951 п. 1: на книге $100 000 суммарный потолок T3
(``max_total_t3_allocation``) связывает раньше любого потолка на протокол, и
поля ``max_concentration_t3`` в ``RiskConfig`` нет вовсе (§19, ADR-962). Значит
сцена «направить новые деньги в underallocated T3» измерила бы СУММАРНЫЙ
потолок, а не правило §20, и отказ был бы верен СЛУЧАЙНО. Поэтому сцена оси (б)
строится на T1 (потолок 40 % на протокол, суммарного потолка у тира нет), а
потолки T3 печатаются рядом ЗАМЕРОМ из живой политики — чтобы следующий цикл
не построил ту же сцену заново.

Чего прибор НЕ меряет
------------------------------------------------------------------------------
КАКОЙ должна быть цена ввода. Это предмет №1 ADR-285: ввести ли в цену хода род
операции, завести ли журналу второй род записи, вычитать ли ввод из бюджета
оборота — решение владельца, а не замер. Прибор отвечает лишь на вопрос, ЕСТЬ
ли в системе место, где это различение уже записано, и спрашивает ли это место
хоть одна дверь денежного пути.

Словари ВВЕЗЕНЫ, а не перепечатаны
------------------------------------------------------------------------------
``UNMEASURED`` и ``CHARGE_KINDS`` — из §13 (``transaction_economics``),
``EXPRESS_KINDS`` и ``MONEY_PATH_FILES`` — из §17
(``correlated_dependency_census``), ``SURFACES`` — из §41
(``cio_auto_execution_limits``). Вторая копия словаря означала бы две шкалы,
расходящиеся молча. Своих здесь два, и каждое РАСШИРЯЕТ ввезённое с названной
причиной (:data:`SURFACES_20`, :data:`MONEY_PATH_20`) либо задаёт ось, которой
до §20 не существовало (:data:`SOURCE_KINDS`).

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей. Своих копий здесь нет намеренно.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import CHARGE_KINDS, UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    CHARGE_KINDS = ("no_input_door", "not_charged", "charged_merged", "charged_named")  # type: ignore[assignment]
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 CHARGE_KINDS/UNMEASURED: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from .correlated_dependency_census import EXPRESS_KINDS, MONEY_PATH_FILES
except Exception as _exc:  # pragma: no cover
    EXPRESS_KINDS = ("door_input", "state_field", "name_substring",
                     "registry_only", "absent")  # type: ignore[assignment]
    MONEY_PATH_FILES = ()  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§17 EXPRESS_KINDS/MONEY_PATH_FILES: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from spa_core.monitoring.cio_auto_execution_limits import SURFACES
except Exception as _exc:  # pragma: no cover
    SURFACES = ("allocator", "economics", "gate")  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§41 SURFACES: {}: {}".format(type(_exc).__name__, _exc))


#: Поверхности §20. ``SURFACES`` §41 — три поверхности, через которые проходит
#: решение о движении денег; ``book`` добавлена §18 (состав книги судит вторая
#: дверь политики). Пятая добавлена ЗДЕСЬ и с причиной: §20 спрашивает про РОД
#: ХОДА, а род хода не записан нигде, кроме ЖУРНАЛА ходов (`data/trades.json`,
#: ячейка `type`) — ни одна из четырёх прежних поверхностей его не несёт.
#: Своего словаря поверхностей прибор не заводит — он РАСШИРЯЕТ ввезённый, и
#: расширение названо.
SURFACES_20: Tuple[str, ...] = tuple(SURFACES) + ("book", "journal")

#: Файлы денежного пути §20. ``MONEY_PATH_FILES`` §17 несёт дверь КНИГИ
#: (`engine.py`); §20 спрашивает цену хода и запись хода, поэтому добавлены
#: дверь ЦЕНЫ и ПИСАТЕЛЬ журнала. Расширение названо, вторая копия перечня не
#: заводится.
MONEY_PATH_20: Tuple[str, ...] = tuple(MONEY_PATH_FILES) + (
    "spa_core/allocator/rebalance_economics.py",
    "spa_core/paper_trading/cycle_runner.py",
)

#: Род ЯЧЕЙКИ журнала, в которой живёт род хода. Словарь СВОЙ, и причина
#: названа: ввезённый ``EXPRESS_KINDS`` (§17) описывает ДВЕРИ и СТРОКИ КНИГИ, а
#: ячейка журнала ходов не является ни тем, ни другим. Согнуть ввезённую шкалу
#: под чужой предмет значило бы развести две шкалы молча — ровно то, против
#: чего написано правило ввоза.
SLOT_KINDS: Tuple[str, ...] = (
    # в ячейку пишется несколько родов — ввод отличим от перекладки В ЗАПИСИ
    "many_kinds_written",
    # ячейка есть, но писатель кладёт в неё ЛИТЕРАЛ: второго рода записать нечем
    "named_but_unreachable",
    # ячейки под род хода нет вовсе
    "absent",
    UNMEASURED,
)

#: РАЗЛИЧАЕТ ли дверь ход «ввод» от хода «перекладка». Главная ось §20.
#: Шкала ОБЪЯВЛЕНА, а не выведена из ветвей: ветка `else` по построению не
#: может сказать, какие роды существуют (урок ADR-357 п. 3 / KNOWN_TIERS).
SOURCE_KINDS: Tuple[str, ...] = (
    # дверь ОТКАЗАЛА перекладке, которую §20 запрещает (ввод достигал той же цели)
    "source_refused",
    # дверь пропустила, но ОБОРОТ — величина §20 — у двух родов хода РАЗНЫЙ
    "source_charged",
    # оборот ТОТ ЖЕ: ход, оборота не требующий, заряжен как перекладка — §20 запрещает
    "source_invisible",
    UNMEASURED,
)
# Рода `no_input_door` в этой шкале НЕТ намеренно, и причина — замер, а не вкус.
# У двери цены источник доллара ВЫРАЗИМ формой книги «до» (кэш против позиции),
# поэтому возмутить его всегда есть чем и сцена строится всегда. Завести здесь
# род, которого не достигает ни одна сцена, значило бы повторить собой находку
# §19 (`named_but_unreachable`, ADR-962). Поверхности, у которых источник НЕ
# является входом вовсе, отвечает ось (а) родом `absent` ввезённой шкалы.

#: Сцена ОБЪЯВЛЕНА здесь, а не взята из живого трека: предмет — ПОВЕДЕНИЕ
#: ДВЕРЕЙ, оно обязано быть воспроизводимым на любой машине в любой день. Живой
#: трек (`data/equity_curve_daily.json`) не входит сюда ни одним числом —
#: запрет `CLAUDE.md`.
SCENE_CAPITAL_USD = 100_000.0
#: Фондируемая нога ОДНА И ТА ЖЕ в обеих сценах: `B` растёт на эту сумму до
#: `SCENE_DEST_AFTER_USD`. Возмущается ровно ИСТОЧНИК доллара.
SCENE_FUND_USD = 10_000.0
SCENE_DEST_AFTER_USD = 35_000.0
SCENE_SRC_AFTER_USD = 35_000.0
#: Ставки сцены. Назначение доходнее источника — иначе у перекладки не было бы
#: выигрыша вовсе и сцена отвечала бы «нет хода», а не «ход такой-то».
SCENE_APY_SRC_PCT = 3.0
SCENE_APY_DEST_PCT = 9.0
#: Одна сеть у обеих ног: две сети подмешали бы к сдвигу мост (`BRIDGE_BPS`) и
#: сдвиг оборота стало бы не отличить от сдвига моста.
SCENE_CHAIN = "ethereum"
#: Ключи сцены — ОБЪЯВЛЕННЫЕ имена, не ключи живого реестра: предмет оси (б) —
#: арифметика двери цены, и она к именам безразлична (дверь цены тир не читает).
SCENE_SRC = "A"
SCENE_DEST = "B"

#: Журнал ходов: по нему меряется ДОСТИЖИМОСТЬ §20 на живом треке.
TRADES_REL = Path("data") / "trades.json"

#: Словарь родов операции, который в системе УЖЕ есть. Претензия «система не
#: умеет различать ввод и перекладку» СВЕРЯЕТСЯ с этим файлом, а не
#: утверждается.
GAS_UNITS_HOME = "spa_core/analytics/fee_calculator.py"

#: Дверь цены денежного пути и модуль, откуда она берёт слагаемые цены.
PRICE_DOOR_REL = "spa_core/allocator/rebalance_economics.py"
PRICE_COST_MODEL_REL = "spa_core/backtesting/tier1/cost_model.py"

#: Писатель журнала ходов — там, где роду хода присваивается значение.
JOURNAL_WRITER_REL = "spa_core/paper_trading/cycle_runner.py"

#: Запись кандидата аллокатора — поверхность ПРЕДЛОЖЕНИЯ.
ALLOCATOR_REL = "spa_core/allocator/allocator.py"


def _repo_root(root: Optional[Path] = None) -> Path:
    return Path(root) if root else Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Ввоз дверей. Дверь не ввезена ⇒ третий исход, а не подставленная заглушка.
# ---------------------------------------------------------------------------

def load_price_door() -> Tuple[Any, Optional[str]]:
    """Модуль двери цены, либо причина — НЕ ИЗМЕРЕНО."""
    try:
        from spa_core.allocator import rebalance_economics
    except Exception as exc:  # noqa: BLE001
        return None, "дверь цены не ввезена: {}: {}".format(type(exc).__name__, exc)
    return rebalance_economics, None


def load_policy() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Оба контракта политики, либо причина — НЕ ИЗМЕРЕНО."""
    try:
        from spa_core.risk.policy import (  # noqa: WPS433
            Position, PortfolioState, RiskConfig, RiskPolicy,
        )
    except Exception as exc:  # noqa: BLE001
        return None, "политика не ввезена: {}: {}".format(type(exc).__name__, exc)
    return {"Position": Position, "PortfolioState": PortfolioState,
            "RiskConfig": RiskConfig, "RiskPolicy": RiskPolicy}, None


def load_gas_units() -> Tuple[Optional[Dict[tuple, int]], Optional[str]]:
    """Словарь родов операции, который в системе уже есть (ловушка четвёртая)."""
    try:
        from spa_core.analytics.fee_calculator import _GAS_UNITS
    except Exception as exc:  # noqa: BLE001
        return None, "словарь родов операции не ввезён: {}: {}".format(
            type(exc).__name__, exc)
    if not isinstance(_GAS_UNITS, dict) or not _GAS_UNITS:
        return None, "словарь родов операции пуст или не словарь"
    return dict(_GAS_UNITS), None


# ---------------------------------------------------------------------------
# (а) ВЫРАЗИМОСТЬ: есть ли у системы понятие «новые деньги»
# ---------------------------------------------------------------------------

def _door_params(fn: Any) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        return [p for p in inspect.signature(fn).parameters if p != "self"], None
    except Exception as exc:  # noqa: BLE001
        return None, "подпись не прочитана: {}: {}".format(type(exc).__name__, exc)


def _dataclass_fields(cls: Any) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        return [f.name for f in dataclasses.fields(cls)], None
    except Exception as exc:  # noqa: BLE001
        return None, "поля не прочитаны: {}: {}".format(type(exc).__name__, exc)


def _allocator_record_fields(root: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    """Поля записи, которую аллокатор строит для КАЖДОГО кандидата.

    Читается AST'ом у ``_load_adapters`` — тем же приёмом, что §18: подстрока
    сказала бы лишь, что слово где-то есть.
    """
    path = root / ALLOCATOR_REL
    if not path.exists():
        return None, "{}: файла нет".format(ALLOCATOR_REL)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "аллокатор не разобран: {}: {}".format(type(exc).__name__, exc)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_load_adapters":
            keys: set = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for key in sub.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
            return sorted(keys), None
    return None, "в аллокаторе нет `_load_adapters` — поверхность предложения не найдена"


def _allocator_capital_origin(root: Path) -> Tuple[Optional[str], Optional[str]]:
    """Чем является капитал аллокатора: входом или литералом.

    §20 спрашивает про ПРИХОД новых денег. Если капитал поверхности предложения
    — литерал класса, приход невыразим ПО ПОСТРОЕНИЮ, и это сильнее, чем
    «нужного поля нет в записи».
    """
    path = root / ALLOCATOR_REL
    if not path.exists():
        return None, "{}: файла нет".format(ALLOCATOR_REL)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "аллокатор не разобран: {}: {}".format(type(exc).__name__, exc)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for sub in node.body:
            targets = (sub.targets if isinstance(sub, ast.Assign)
                       else [sub.target] if isinstance(sub, ast.AnnAssign) else [])
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CAPITAL":
                    val = getattr(sub, "value", None)
                    if isinstance(val, ast.Constant):
                        return "class_literal:{}={}".format(node.name, val.value), None
                    return "class_expression:{}".format(node.name), None
    return None, "в аллокаторе нет атрибута CAPITAL — происхождение капитала не найдено"


def _journal_kind_slot(root: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """Как писатель журнала присваивает роду хода значение.

    Ячейка `type` есть МЕСТО для рода хода. Вопрос — что в неё кладут: вход,
    выражение или литерал. Литерал означает, что второй род записать НЕЧЕМ.
    """
    path = root / JOURNAL_WRITER_REL
    if not path.exists():
        return {}, "{}: файла нет".format(JOURNAL_WRITER_REL)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, "писатель журнала не разобран: {}: {}".format(
            type(exc).__name__, exc)
    sites: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, val in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "type"):
                continue
            if isinstance(val, ast.Constant):
                shape, literal = "literal", val.value
            elif isinstance(val, ast.Name):
                shape, literal = "name:{}".format(val.id), None
            else:
                shape, literal = type(val).__name__, None
            sites.append({"line": getattr(key, "lineno", None),
                          "shape": shape, "literal": literal})
    # «файл не прочитан» (выше) и «файл прочитан, ячейки в нём нет» — РАЗНЫЕ
    # утверждения. Второе есть ИЗМЕРЕННЫЙ ноль (род `absent`), и выдать его за
    # «не измерено» значило бы сделать род `absent` НЕДОСТИЖИМЫМ, то есть
    # повторить собой находку §19 (инв. #17 и урок «род обязан быть ДОСТИЖИМ до
    # того, как печатать его ноль»).
    if not sites:
        return {"sites": [], "literals": [], "all_literal": None,
                "no_slot": True}, None
    return {"sites": sites,
            "literals": sorted({s["literal"] for s in sites if s["literal"]}),
            "all_literal": all(s["shape"] == "literal" for s in sites)}, None


def expressibility(root: Path) -> List[Dict[str, Any]]:
    """Род выразимости «новых денег» у КАЖДОЙ поверхности §20.

    Ответ про каждую поверхность отдельный и печатается с причиной: шкала
    ``EXPRESS_KINDS`` (§17) не умеет сказать «почему», а без причины род есть
    украшение.
    """
    out: List[Dict[str, Any]] = []
    price, price_err = load_price_door()
    pol, pol_err = load_policy()

    # ── economics: дверь цены ────────────────────────────────────────────────
    if price is None:
        out.append({"surface": "economics", "kind": UNMEASURED, "why": price_err})
    else:
        params, err = _door_params(price.evaluate)
        if params is None:
            out.append({"surface": "economics", "kind": UNMEASURED, "why": err})
        else:
            # Вход про ПРИХОД денег: имя, называющее источник, а не сумму.
            named = sorted(p for p in params
                           if any(tok in p for tok in
                                  ("deposit", "inflow", "new_capital", "new_money",
                                   "contribution", "funding_source", "source")))
            out.append({
                "surface": "economics",
                "kind": "door_input" if named else "absent",
                "params": params,
                "params_naming_source": named,
                "why": ("источник денег назван входом: {}".format(named) if named else
                        "ни один из {} входов двери цены не называет, ОТКУДА доллар: "
                        "книга «до» и книга «после» — всё, что дверь знает"
                        .format(len(params))),
            })

    # ── gate: дверь допуска новой позиции ────────────────────────────────────
    if pol is None:
        out.append({"surface": "gate", "kind": UNMEASURED, "why": pol_err})
    else:
        params, err = _door_params(pol["RiskPolicy"].check_new_position)
        if params is None:
            out.append({"surface": "gate", "kind": UNMEASURED, "why": err})
        else:
            named = sorted(p for p in params
                           if any(tok in p for tok in ("deposit", "inflow", "source",
                                                       "new_capital", "new_money")))
            out.append({
                "surface": "gate", "kind": "door_input" if named else "absent",
                "params": params, "params_naming_source": named,
                "why": ("источник денег назван входом: {}".format(named) if named else
                        "`amount_usd` — единственная денежная величина входа; «новая "
                        "позиция» в имени двери означает НОВУЮ ПОЗИЦИЮ, а не новые деньги"),
            })

    # ── book: состав книги ───────────────────────────────────────────────────
    if pol is None:
        out.append({"surface": "book", "kind": UNMEASURED, "why": pol_err})
    else:
        st_fields, st_err = _dataclass_fields(pol["PortfolioState"])
        pos_fields, pos_err = _dataclass_fields(pol["Position"])
        if st_fields is None or pos_fields is None:
            out.append({"surface": "book", "kind": UNMEASURED,
                        "why": st_err or pos_err})
        else:
            named = sorted(f for f in (st_fields + pos_fields)
                           if any(tok in f for tok in ("deposit", "inflow", "source",
                                                       "new_capital", "contribution")))
            out.append({
                "surface": "book",
                "kind": "state_field" if named else "absent",
                "state_fields": st_fields, "position_fields": pos_fields,
                "params_naming_source": named,
                "why": ("источник назван полем книги: {}".format(named) if named else
                        "`total_capital_usd` растёт и от прихода денег, и от прибыли, и "
                        "РАЗЛИЧИТЬ их книга не может: отдельного поля нет ни у состояния "
                        "({}), ни у строки ({})".format(len(st_fields), len(pos_fields))),
            })

    # ── allocator: поверхность предложения ───────────────────────────────────
    fields, f_err = _allocator_record_fields(root)
    origin, o_err = _allocator_capital_origin(root)
    if fields is None:
        out.append({"surface": "allocator", "kind": UNMEASURED, "why": f_err})
    else:
        named = sorted(f for f in fields
                       if any(tok in f for tok in ("deposit", "inflow", "source",
                                                   "new_capital", "contribution")))
        # `apy_source`/`tvl_source` — источник ЧИСЛА, а не источник ДЕНЕГ.
        named = [f for f in named if not f.endswith("_source")]
        out.append({
            "surface": "allocator",
            "kind": "door_input" if named else "absent",
            "record_fields": fields, "params_naming_source": named,
            "capital_origin": origin, "capital_origin_why": o_err,
            "why": ("источник назван полем записи: {}".format(named) if named else
                    "ни одно из {} полей записи кандидата не про источник денег, а сам "
                    "капитал поверхности — {}: приход новых денег невыразим ПО "
                    "ПОСТРОЕНИЮ, поверхность всегда раскладывает капитал заново"
                    .format(len(fields), origin or "НЕ ИЗМЕРЕН: {}".format(o_err))),
        })

    # ── journal: запись хода ─────────────────────────────────────────────────
    # Род по шкале EXPRESS_KINDS здесь `absent` ВСЕГДА, и это не описка: ячейка
    # `type` — место для РОДА ХОДА, а не для ИСТОЧНИКА ДЕНЕГ, и поля про
    # источник у записи нет. Состояние самой ячейки — отдельная ось со СВОИМ
    # словарём (:data:`SLOT_KINDS`); согнуть ввезённую шкалу под чужой предмет
    # значило бы развести две шкалы молча.
    slot, slot_err = _journal_kind_slot(root)
    row: Dict[str, Any] = {"surface": "journal"}
    if slot_err:
        row.update({"kind": UNMEASURED, "slot_kind": UNMEASURED, "why": slot_err})
    else:
        sites = slot.get("sites") or []
        literals = slot.get("literals") or []
        if slot.get("no_slot"):
            slot_kind = "absent"
        elif slot.get("all_literal"):
            slot_kind = "named_but_unreachable"
        else:
            slot_kind = "many_kinds_written"
        row.update({
            "kind": "absent", "slot_kind": slot_kind,
            "sites": sites, "literals": literals,
            "all_literal": slot.get("all_literal"),
            "why": ("поля про ИСТОЧНИК денег у записи хода нет, и ячейки `type` под "
                    "РОД хода у писателя нет тоже — место, где род мог бы быть "
                    "записан, отсутствует" if slot_kind == "absent" else
                    "поля про ИСТОЧНИК денег у записи хода нет; ячейка `type` — место "
                    "для РОДА хода, и {} писателя кладёт в неё ЛИТЕРАЛ {}: второго "
                    "рода записать НЕЧЕМ"
                    .format("единственная площадка" if len(sites) == 1
                            else "каждая из {} площадок".format(len(sites)), literals)
                    if slot_kind == "named_but_unreachable" else
                    "ячейка `type` получает значение выражением — род хода выразим"),
        })
    out.append(row)

    return out


# ---------------------------------------------------------------------------
# (б) РАЗЛИЧЕНИЕ: дифференциал по ИСТОЧНИКУ денег
# ---------------------------------------------------------------------------

def _scene_books() -> Dict[str, Tuple[Dict[str, float], Dict[str, float]]]:
    """Две сцены с ОДНОЙ И ТОЙ ЖЕ фондируемой ногой.

    ``new`` — доллар приходит из нераспределённого кэша (сумма позиций меньше
    капитала на ``SCENE_FUND_USD``). ``swap`` — тот же доллар приходит из
    продажи источника. Целевая книга, капитал, фондируемая нога и сумма
    развёрнутого ПОСЛЕ хода совпадают бит в бит; различается РОВНО источник.
    """
    dest_before = SCENE_DEST_AFTER_USD - SCENE_FUND_USD
    target = {SCENE_SRC: SCENE_SRC_AFTER_USD, SCENE_DEST: SCENE_DEST_AFTER_USD}
    return {
        "new": ({SCENE_SRC: SCENE_SRC_AFTER_USD, SCENE_DEST: dest_before}, dict(target)),
        "swap": ({SCENE_SRC: SCENE_SRC_AFTER_USD + SCENE_FUND_USD,
                  SCENE_DEST: dest_before}, dict(target)),
    }


def _call_price_door(price: Any, current: Dict[str, float], target: Dict[str, float],
                     **kw: Any) -> Any:
    apy = {SCENE_SRC: SCENE_APY_SRC_PCT, SCENE_DEST: SCENE_APY_DEST_PCT}
    apy.update(kw.pop("apy_override", {}) or {})
    return price.evaluate(
        current_positions=dict(current), target_positions=dict(target),
        apy_pct=apy, evidenced={SCENE_SRC, SCENE_DEST},
        chains={SCENE_SRC: SCENE_CHAIN, SCENE_DEST: SCENE_CHAIN},
        capital_usd=SCENE_CAPITAL_USD,
        turnover_today_usd=kw.pop("turnover_today_usd", 0.0),
        **kw)


def _controls(price: Any) -> Dict[str, Any]:
    """Положительные контроли: дверь СВЯЗЫВАЕТ то, что мы собираемся возмущать.

    Два, и оба на величинах, которые дверь связывает ЗАВЕДОМО: выигрыш (ставка
    назначения) и недельный бюджет оборота.

    **Контроль смотрит на СВОИ ВОРОТА, а не на итоговый вердикт, и это не
    придирка.** Первая редакция сверяла ``decision``, и на ней род
    ``source_refused`` оказался НЕДОСТИЖИМ ПО ПОСТРОЕНИЮ: проба отказа
    перекладке делает базовый вердикт ``HOLD``, после чего контроль, работающий
    переходом ``ACT → HOLD``, сменить ничего не может — прибор отказывался
    отвечать там, где ответ как раз и есть. Это ровно род дефекта
    ``named_but_unreachable``, который §19 нашёл у потолка T3 (ADR-962), и
    завести его в собственной шкале значило бы повторить находку собой.
    Поэтому контроль меряет ВОРОТА (``gain_above_band``, ``week_turnover_ok``) и
    СВОЁ число (``gain_pp``) — они наблюдаемы при любом итоговом вердикте.
    """
    books = _scene_books()
    cur, tgt = books["swap"]
    out: Dict[str, Any] = {}
    try:
        base = _call_price_door(price, cur, tgt)
        # (1) выигрыш: снять премию пула назначения ⇒ выигрыш обязан упасть,
        # а ворота выигрыша — закрыться.
        flat = _call_price_door(price, cur, tgt,
                                apy_override={SCENE_DEST: SCENE_APY_SRC_PCT})
        gain_gate_moved = (base.gates.get("gain_above_band")
                           != flat.gates.get("gain_above_band"))
        gain_number_moved = (flat.gain_pp or 0.0) < (base.gain_pp or 0.0) - 1e-9
        out["gain"] = {
            "base_gain_pp": base.gain_pp, "perturbed_gain_pp": flat.gain_pp,
            "base_gate": base.gates.get("gain_above_band"),
            "perturbed_gate": flat.gates.get("gain_above_band"),
            "changed": bool(gain_gate_moved and gain_number_moved),
            "why": "премия пула назначения снята: выигрыш {} → {}, ворота {} → {}"
                   .format(base.gain_pp, flat.gain_pp,
                           base.gates.get("gain_above_band"),
                           flat.gates.get("gain_above_band")),
        }
        # (2) недельный бюджет оборота: исчерпать ⇒ его ворота обязаны закрыться.
        tight = _call_price_door(price, cur, tgt,
                                 turnover_last_week_usd=SCENE_CAPITAL_USD)
        out["week_budget"] = {
            "base_gate": base.gates.get("week_turnover_ok"),
            "perturbed_gate": tight.gates.get("week_turnover_ok"),
            "changed": bool(base.gates.get("week_turnover_ok") is True
                            and tight.gates.get("week_turnover_ok") is False),
            "why": "недельный бюджет оборота исчерпан: ворота {} → {}".format(
                base.gates.get("week_turnover_ok"),
                tight.gates.get("week_turnover_ok")),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": "контроль не прогнан: {}: {}".format(type(exc).__name__, exc)}
    out["all_changed"] = bool(out["gain"]["changed"] and out["week_budget"]["changed"])
    return out


def distinction(price: Any) -> Dict[str, Any]:
    """Главная ось §20: различает ли дверь цены ВВОД и ПЕРЕКЛАДКУ.

    Род присваивается по сдвигу ОБОРОТА, а не по сдвигу суммы цены: ловушка
    первая — газ между сценами различается всегда, потому что различается ЧИСЛО
    НОГ, и это не род хода.
    """
    if price is None:
        return {"kind": UNMEASURED, "why": "дверь цены не ввезена"}
    controls = _controls(price)
    if "error" in controls:
        return {"kind": UNMEASURED, "why": controls["error"], "controls": controls}
    if not controls.get("all_changed"):
        return {"kind": UNMEASURED, "controls": controls,
                "why": "положительный контроль НЕ сменил вердикт — ответ об источнике "
                       "денег не выдаётся: «не изменился» и «прибор не работает» "
                       "выглядят одинаково"}

    books = _scene_books()
    legs_by_scene: Dict[str, Any] = {}
    try:
        for name, (cur, tgt) in books.items():
            d = _call_price_door(price, cur, tgt)
            legs_by_scene[name] = {
                "decision": d.decision,
                "legs": [{"protocol": lg["protocol"], "delta_usd": lg["delta_usd"],
                          "direction": lg["direction"]} for lg in (d.legs or [])],
                "leg_count": len(d.legs or []),
                "turnover_usd": d.turnover_usd, "turnover_frac": d.turnover_frac,
                "cost_usd": d.cost_usd, "gain_pp": d.gain_pp,
                "payback_days": d.payback_days,
                "turnover_gates": {k: v for k, v in (d.gates or {}).items()
                                   if "turnover" in k or "amount" in k},
            }
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED,
                "why": "сцена не прогнана: {}: {}".format(type(exc).__name__, exc),
                "controls": controls}

    new, swap = legs_by_scene["new"], legs_by_scene["swap"]
    same_turnover = abs(new["turnover_usd"] - swap["turnover_usd"]) < 1e-6
    cost_delta = round(swap["cost_usd"] - new["cost_usd"], 2)

    if swap["decision"] == "HOLD" and new["decision"] != "HOLD":
        kind = "source_refused"
        why = ("дверь отказала перекладке и пропустила ввод — ровно то, что §20 "
               "просит")
    elif not same_turnover:
        kind = "source_charged"
        why = ("оборот у двух родов хода РАЗНЫЙ: ввод ${:,.2f}, перекладка ${:,.2f}"
               .format(new["turnover_usd"], swap["turnover_usd"]))
    else:
        kind = "source_invisible"
        why = ("ОБОРОТ у обоих родов хода ОДИН И ТОТ ЖЕ (${:,.2f}): ход, который "
               "оборота не требует — ни одна позиция не продана, — заряжен как "
               "перекладка. Цена различается на ${:,.2f}, и это РОВНО один литерал "
               "газа за тронутую позицию ({} нога против {}), а не род хода"
               .format(new["turnover_usd"], cost_delta,
                       new["leg_count"], swap["leg_count"]))

    return {
        "kind": kind, "why": why, "controls": controls, "scenes": legs_by_scene,
        "turnover_identical": same_turnover, "cost_delta_usd": cost_delta,
        "gain_delta_pp": round(swap["gain_pp"] - new["gain_pp"], 6),
        "gain_differs_by_construction": (
            "выигрыш двух сцен равным быть НЕ МОЖЕТ (ловушка вторая): доллар из кэша "
            "зарабатывал 0 %, доллар из продажи источника — {} %. Разница "
            "печатается как замер, а не выравнивается подгонкой ставок"
            .format(SCENE_APY_SRC_PCT)),
    }


# ---------------------------------------------------------------------------
# (в) ЗАРЯД: заряжается ли оборот на ход, оборота не требующий
# ---------------------------------------------------------------------------

def turnover_charge(price: Any) -> Dict[str, Any]:
    """Род заряда оборота на ЧИСТЫЙ ВВОД (``CHARGE_KINDS``, ввезено из §13).

    Вопрос заказа дословно: «заряжается ли стоимость оборота на ход, который
    оборота не требует». Мерится ПОВЕДЕНИЕМ ворот, а не чтением формулы: ворота
    на обороте решают вердикт, и если чистый ввод они ОТКАЗЫВАЮТ по бюджету
    оборота, то оборот ему заряжен — чем бы ни называлась переменная.
    """
    if price is None:
        return {"kind": UNMEASURED, "why": "дверь цены не ввезена"}
    books = _scene_books()
    cur, tgt = books["new"]
    swap_cur, swap_tgt = books["swap"]
    try:
        free = _call_price_door(price, cur, tgt)
        params = price.TriggerParams.for_mode()
        # Бюджет недели исчерпан ровно настолько, что ход ВВОДА его переполняет.
        week_used = params.max_turnover_per_week * SCENE_CAPITAL_USD - SCENE_FUND_USD / 2.0
        squeezed = _call_price_door(price, cur, tgt,
                                   turnover_last_week_usd=max(0.0, week_used))
        # День: то же самое через дневной бюджет.
        day_used = params.max_turnover_per_day * SCENE_CAPITAL_USD - SCENE_FUND_USD / 2.0
        day_squeezed = _call_price_door(price, cur, tgt,
                                        turnover_today_usd=max(0.0, day_used))
        # «Заряжено ТЕМ ЖЕ числом» — утверждение о РАВЕНСТВЕ, и оно обязано быть
        # ИЗМЕРЕНО, а не выведено из того, что ворота связали. Поэтому тот же
        # зажим прогоняется на ПЕРЕКЛАДКЕ, и причины отказа сверяются дословно.
        swap_squeezed = _call_price_door(price, swap_cur, swap_tgt,
                                         turnover_last_week_usd=max(0.0, week_used))
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED,
                "why": "сцена заряда не прогнана: {}: {}".format(
                    type(exc).__name__, exc)}

    gates_on_turnover = sorted(k for k in (free.gates or {})
                               if "turnover" in k or "amount" in k)
    refused_week = squeezed.decision == "HOLD" and free.decision != "HOLD"
    refused_day = day_squeezed.decision == "HOLD" and free.decision != "HOLD"
    turnover_reasons = sorted(r for r in (squeezed.reasons or []) if "turnover" in r)
    swap_turnover_reasons = sorted(r for r in (swap_squeezed.reasons or [])
                                   if "turnover" in r)
    same_refusal = turnover_reasons == swap_turnover_reasons
    charged = bool(free.turnover_usd > 0.0)

    if not charged:
        kind, why = "not_charged", "оборот чистого ввода равен нулю — заряда нет"
    elif (refused_week or refused_day) and same_refusal:
        # Заряжено ТЕМ ЖЕ числом, что перекладка: своего сумманда у ввода нет.
        kind = "charged_merged"
        why = ("чистый ввод ${:,.2f} заряжен обороту ПОЛНОСТЬЮ (${:,.2f}) и ОТКАЗАН "
               "бюджетом оборота: неделя — {}, день — {}. Причина отказа у ввода и у "
               "перекладки ОДНА И ТА ЖЕ ({}) — своего слагаемого у ввода нет. Ни одна "
               "позиция при этом не продана: оборота, который бюджет охраняет, ход не "
               "производит"
               .format(SCENE_FUND_USD, free.turnover_usd,
                       "ОТКАЗ" if refused_week else "пропущен",
                       "ОТКАЗ" if refused_day else "пропущен",
                       turnover_reasons or "причина не названа"))
    elif refused_week or refused_day:
        kind = "charged_named"
        why = ("оборот заряжен (${:,.2f}) и ворота ввод отказывают, но причина у ввода "
               "и у перекладки РАЗНАЯ ({} против {}) — у ввода своё слагаемое"
               .format(free.turnover_usd, turnover_reasons, swap_turnover_reasons))
    else:
        kind = "charged_named"
        why = ("оборот заряжен (${:,.2f}), но ни недельный, ни дневной бюджет ввод не "
               "отказывают — у ввода своё слагаемое".format(free.turnover_usd))

    return {
        "kind": kind, "why": why,
        "gates_on_turnover": gates_on_turnover,
        "gates_on_turnover_count": len(gates_on_turnover),
        "gates_total": len(free.gates or {}),
        "free": {"decision": free.decision, "turnover_usd": free.turnover_usd,
                 "cost_usd": free.cost_usd},
        "week_squeezed": {"decision": squeezed.decision,
                          "reasons": list(squeezed.reasons or [])},
        "day_squeezed": {"decision": day_squeezed.decision,
                         "reasons": list(day_squeezed.reasons or [])},
        "swap_squeezed": {"decision": swap_squeezed.decision,
                          "reasons": list(swap_squeezed.reasons or [])},
        "turnover_reasons_new": turnover_reasons,
        "turnover_reasons_swap": swap_turnover_reasons,
        "refusal_identical": same_refusal,
        "refused_by_week_budget": refused_week,
        "refused_by_day_budget": refused_day,
    }


# ---------------------------------------------------------------------------
# Словарь родов операции, который в системе УЖЕ есть, и его читатели
# ---------------------------------------------------------------------------

#: Предел кругов засева имён. Исчерпание — третий исход, а не обрезанный
#: ответ (приём ADR-932: засев до неподвижной точки, исчерпание = код 2).
_SEED_ROUNDS_MAX = 6


def _operation_slots(node: Any) -> set:
    """Позиции и ключевые имена, в которых функция принимает РОД ОПЕРАЦИИ.

    Возвращается множество: номер позиции (``int``, с поправкой на ``self``) и
    имя ключа (``str``). Параметр узнаётся по имени ``operation`` в СВОЕЙ
    подписи — это объявление автора функции, а не догадка прибора.
    """
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    slots: set = set()
    for i, a in enumerate(positional):
        if a.arg == "operation":
            # `self` аргументом зова не передаётся — позиция сдвигается.
            offset = 1 if positional and positional[0].arg in ("self", "cls") else 0
            slots.add(i - offset)
            slots.add("operation")
    for a in args.kwonlyargs:
        if a.arg == "operation":
            slots.add("operation")
    return slots


def _forwards_into_slot(call: ast.Call, own: set, slots: set) -> Optional[str]:
    """Имя СВОЕГО параметра, который зов кладёт ИМЕННО в позицию операции.

    ``None`` — зов в эту позицию своего параметра не кладёт. Проверять «кладёт
    ли хоть куда-нибудь» НЕДОСТАТОЧНО: функция, пробрасывающая в соседнюю
    позицию посторонний параметр (например объект калькулятора), обёрткой рода
    операции НЕ является, а засев от этого растёт — то есть читателей стало бы
    больше, чем их есть. Это ровно та инфляция, которую цикл #1081 уже
    исправлял на уровень ниже (мутант M3).
    """
    for i, a in enumerate(call.args):
        if i in slots and isinstance(a, ast.Name) and a.id in own:
            return a.id
    for k in call.keywords:
        if k.arg in slots and isinstance(k.value, ast.Name) and k.value.id in own:
            return k.value.id
    return None


def _operation_taking_callees(root: Path) -> Tuple[Optional[set], Optional[str]]:
    """Имена, зов которых ДОХОДИТ до словаря родов операции.

    Корень меряется, а не перечисляется: функции ``fee_calculator``, у которых
    есть параметр с именем ``operation``. Затем — чужие функции, пробрасывающие
    свой параметр ИМЕННО В ПОЗИЦИЮ ОПЕРАЦИИ уже известного имени, до неподвижной
    точки (приём ADR-932).

    Два условия, и ни одно не выводится из другого: имя, совпавшее с операцией
    лишь СТРОКОЙ аргумента, читателем не является (ловушка четвёртая), и
    функция, пробросившая в соседнюю позицию ПОСТОРОННИЙ параметр, обёрткой не
    является (мутант M3 того же цикла).
    """
    home = root / GAS_UNITS_HOME
    if not home.exists():
        return None, "{}: файла нет".format(GAS_UNITS_HOME)
    try:
        tree = ast.parse(home.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, "{} не разобран: {}: {}".format(
            GAS_UNITS_HOME, type(exc).__name__, exc)
    # имя → позиции/ключи, в которых оно принимает род операции
    slots_of: Dict[str, set] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            slots = _operation_slots(node)
            if slots:
                slots_of[node.name] = slots
    seed: set = set(slots_of)
    if not seed:
        return None, ("в {} нет ни одной функции с параметром `operation` — корень "
                      "засева пуст, и нулём это не считается".format(GAS_UNITS_HOME))

    files: List[Tuple[str, ast.AST]] = []
    for path in sorted((root / "spa_core").rglob("*.py")) + \
            sorted((root / "scripts").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in rel or Path(rel).name.startswith("test_"):
            continue
        try:
            files.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001 — нечитаемый файл назовёт вызывающий
            continue

    for _round in range(_SEED_ROUNDS_MAX):
        grew = False
        for _rel, ftree in files:
            for node in ast.walk(ftree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name in seed:
                    continue
                own_list = list(node.args.posonlyargs) + list(node.args.args)
                own = {a.arg for a in own_list + list(node.args.kwonlyargs)}
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    fn = sub.func
                    callee = (fn.attr if isinstance(fn, ast.Attribute)
                              else fn.id if isinstance(fn, ast.Name) else None)
                    if callee not in seed:
                        continue
                    param = _forwards_into_slot(sub, own, slots_of.get(callee, set()))
                    if param is None:
                        continue
                    # Обёртка наследует позиции операции — СВОИ, по своей подписи.
                    offset = 1 if own_list and own_list[0].arg in ("self", "cls") else 0
                    inherited = {param}
                    for i, a in enumerate(own_list):
                        if a.arg == param:
                            inherited.add(i - offset)
                    slots_of[node.name] = slots_of.get(node.name, set()) | inherited
                    seed.add(node.name)
                    grew = True
                    break
        if not grew:
            return seed, None
    return None, ("засев имён не сошёлся за {} кругов — третий исход, а не обрезанный "
                  "перечень читателей".format(_SEED_ROUNDS_MAX))


def operation_kind_readers(root: Path) -> Dict[str, Any]:
    """Кто ЧИТАЕТ различение «ввод ≠ перекладка», которое в системе уже есть.

    Меряется AST'ом по ЗАСЕЯННОМУ перечню имён (:func:`_operation_taking_callees`):
    подстрока ``deposit`` в файле ответила бы на вопрос «есть ли такое слово», а
    зов с подходящим литералом — на вопрос «совпала ли строка». Денежный путь
    объявлен :data:`MONEY_PATH_20`; файл вне перечня — советательный, и его
    чтение решения не двигает.
    """
    units, err = load_gas_units()
    if units is None:
        return {"kind": UNMEASURED, "why": err}
    ops = sorted({str(k[0]) for k in units if isinstance(k, tuple) and k})
    pairs = {"{}:{}".format(k[0], k[1]): v for k, v in units.items()
             if isinstance(k, tuple) and len(k) == 2}

    callees, seed_err = _operation_taking_callees(root)
    if callees is None:
        return {"kind": UNMEASURED, "why": seed_err,
                "operations_declared": ops, "pairs": pairs}

    readers: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    for path in sorted((root / "spa_core").rglob("*.py")) + \
            sorted((root / "scripts").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in rel or Path(rel).name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            unreadable.append("{}: {}".format(rel, type(exc).__name__))
            continue
        if not any(name in text for name in callees):
            continue   # дешёвое отсечение; вердикт выносит AST ниже
        try:
            tree = ast.parse(text)
        except Exception as exc:  # noqa: BLE001
            unreadable.append("{}: не разобран: {}".format(rel, type(exc).__name__))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            callee = (fn.attr if isinstance(fn, ast.Attribute)
                      else fn.id if isinstance(fn, ast.Name) else None)
            if callee not in callees:
                continue   # зов НЕ доходит до словаря — литерал ничего не значит
            literals = [a.value for a in node.args
                        if isinstance(a, ast.Constant) and a.value in ops]
            literals += [k.value.value for k in node.keywords
                         if isinstance(k.value, ast.Constant) and k.value.value in ops]
            readers.append({"file": rel, "line": node.lineno, "callee": callee,
                            "operations": sorted(set(literals)),
                            "operation_literal_named": bool(literals),
                            "money_path": rel in MONEY_PATH_20})

    on_money_path = [r for r in readers if r["money_path"]]
    ops_read = sorted({op for r in readers for op in r["operations"]})
    ops_read_on_money_path = sorted({op for r in on_money_path
                                     for op in r["operations"]})
    return {
        "home": GAS_UNITS_HOME,
        "operations_declared": ops, "pairs": pairs,
        "operations_read_anywhere": ops_read,
        "operations_declared_with_no_reader": sorted(set(ops) - set(ops_read)),
        "readers_count": len(readers), "readers": readers,
        "readers_on_money_path": on_money_path,
        "operations_read_on_money_path": ops_read_on_money_path,
        "money_path_declared": list(MONEY_PATH_20),
        "seeded_callees": sorted(callees),
        "unreadable": unreadable,
        "price_door_cost_model": PRICE_COST_MODEL_REL,
        "why": ("различение объявлено {} операциями на {} парах (на {} — {} против {} "
                "единиц газа, ×{:.1f}), читателей всего {}, НА ДЕНЕЖНОМ ПУТИ — {}"
                .format(len(ops), len(pairs), SCENE_CHAIN,
                        pairs.get("deposit:{}".format(SCENE_CHAIN), "?"),
                        pairs.get("rebalance:{}".format(SCENE_CHAIN), "?"),
                        (pairs.get("rebalance:{}".format(SCENE_CHAIN), 0) /
                         pairs["deposit:{}".format(SCENE_CHAIN)])
                        if pairs.get("deposit:{}".format(SCENE_CHAIN)) else float("nan"),
                        len(readers), len(on_money_path))),
    }


# ---------------------------------------------------------------------------
# (г) ДОСТИЖИМОСТЬ: приходили ли новые деньги и какой потолок связывает раньше
# ---------------------------------------------------------------------------

def reachability(data_dir: Optional[Path], root: Path) -> Dict[str, Any]:
    """Две половины достижимости §20, и ни одна не выводится из другой.

    ``journal`` — приходили ли новые деньги на треке ВООБЩЕ (ячейка ``capital``
    журнала ходов). Каталог данных — ВХОД: из worktree живого ``data/`` нет по
    построению, и без входа прибор мерил бы git-замороженный канон вместо
    живого трека (дословно урок шагов 1д/1е).

    ``ceiling`` — какой потолок связывает раньше, если новые деньги направить в
    underallocated T3 (контрапункт заказа G951 п. 1 / §19).
    """
    out: Dict[str, Any] = {}

    path = (Path(data_dir) / "trades.json") if data_dir else (root / TRADES_REL)
    out["journal_path"] = str(path)
    out["journal_dir_named"] = data_dir is not None
    if not data_dir:
        out["journal_default_printed"] = (
            "каталог данных НЕ НАЗВАН — мерен git-замороженный канон дерева, не живой "
            "трек; назвать входом --data-dir")
    if not path.exists():
        out["journal"] = {"kind": UNMEASURED,
                          "why": "{}: файла нет".format(path)}
    else:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            out["journal"] = {"kind": UNMEASURED,
                              "why": "журнал не разобран: {}: {}".format(
                                  type(exc).__name__, exc)}
        else:
            if not isinstance(rows, list):
                out["journal"] = {"kind": UNMEASURED,
                                  "why": "журнал не список, а {}".format(type(rows).__name__)}
            else:
                caps = [r.get("capital") for r in rows if isinstance(r, dict)]
                kinds = sorted({str(r.get("type")) for r in rows
                                if isinstance(r, dict) and r.get("type") is not None})
                distinct_caps = sorted({c for c in caps if c is not None})
                out["journal"] = {
                    "kind": ("many_capitals" if len(distinct_caps) > 1
                             else "single_capital" if distinct_caps else UNMEASURED),
                    "moves": len(rows),
                    "kinds_written": kinds,
                    "kinds_written_count": len(kinds),
                    "distinct_capitals": distinct_caps,
                    "why": ("за {} ходов род записан {} значением(ями) {}, а капитал — "
                            "{} значением(ями) {}: {}"
                            .format(len(rows), len(kinds), kinds,
                                    len(distinct_caps), distinct_caps,
                                    "приход новых денег журналом НЕ НАБЛЮДЁН"
                                    if len(distinct_caps) <= 1 else
                                    "капитал менялся — приход наблюдаем")),
                }

    pol, pol_err = load_policy()
    if pol is None:
        out["ceiling"] = {"kind": UNMEASURED, "why": pol_err}
    else:
        cfg = pol["RiskConfig"]()
        t3_total = getattr(cfg, "max_total_t3_allocation", None)
        t3_each = getattr(cfg, "max_concentration_t3", None)
        t1_each = getattr(cfg, "max_concentration_t1", None)
        out["ceiling"] = {
            "kind": "measured",
            "max_total_t3_allocation": t3_total,
            "max_concentration_t3": t3_each,
            "max_concentration_t3_field_exists": hasattr(cfg, "max_concentration_t3"),
            "max_concentration_t1": t1_each,
            "scene_tier": "T1",
            "why": ("на книге ${:,.0f} суммарный потолок T3 = {} связывает раньше любого "
                    "потолка на протокол (поля `max_concentration_t3` в политике {}), "
                    "поэтому сцена оси (б) построена на T1 (потолок на протокол {}): "
                    "иначе замер поймал бы СУММАРНЫЙ потолок, а не правило §20, и отказ "
                    "был бы верен СЛУЧАЙНО"
                    .format(SCENE_CAPITAL_USD, t3_total,
                            "НЕТ ВОВСЕ" if not hasattr(cfg, "max_concentration_t3")
                            else "= {}".format(t3_each), t1_each)),
        }
    return out


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def census(root: Optional[Path] = None,
           data_dir: Optional[Path] = None) -> Dict[str, Any]:
    base = _repo_root(root)
    price, price_err = load_price_door()

    report: Dict[str, Any] = {
        "paragraph": 20,
        "subject": "New capital — ввод ОТДЕЛЬНО от перекладки",
        "order": "G951 п. 1",
        "root": str(base),
        "vocab_errors": list(_VOCAB_ERRORS),
        "surfaces_declared": list(SURFACES_20),
        "source_kinds": list(SOURCE_KINDS),
        "slot_kinds": list(SLOT_KINDS),
        "charge_kinds": list(CHARGE_KINDS),
        "express_kinds": list(EXPRESS_KINDS),
        "unmeasured": [],
        "advisory": "прибор только ЧИТАЕТ: ни политика, ни пороги, ни гейт, ни "
                    "аллокатор, ни писатель журнала не изменены",
    }
    if price_err:
        report["unmeasured"].append(price_err)

    report["expressibility"] = expressibility(base)
    report["distinction"] = distinction(price)
    report["turnover_charge"] = turnover_charge(price)
    report["operation_kinds"] = operation_kind_readers(base)
    report["reachability"] = reachability(data_dir, base)

    # Роды СВЕРЯЮТСЯ со словарями: род вне словаря есть дефект прибора, а не
    # находка о мире (урок §19).
    for row in report["expressibility"]:
        if row["kind"] not in tuple(EXPRESS_KINDS) + (UNMEASURED,):
            report["unmeasured"].append(
                "род выразимости поверхности {} вне словаря EXPRESS_KINDS: {}".format(
                    row["surface"], row["kind"]))
        if "slot_kind" in row and row["slot_kind"] not in SLOT_KINDS:
            report["unmeasured"].append(
                "род ячейки журнала вне словаря SLOT_KINDS: {}".format(row["slot_kind"]))
    if report["distinction"]["kind"] not in SOURCE_KINDS:
        report["unmeasured"].append("род оси (б) вне словаря SOURCE_KINDS: {}".format(
            report["distinction"]["kind"]))
    if report["turnover_charge"]["kind"] not in tuple(CHARGE_KINDS) + (UNMEASURED,):
        report["unmeasured"].append("род оси (в) вне словаря CHARGE_KINDS: {}".format(
            report["turnover_charge"]["kind"]))

    # Поверхности объявлены ВСЕ: поверхность без ответа — не пустота, а
    # НЕ ИЗМЕРЕНО с названной причиной (инв. #17).
    answered = {row["surface"] for row in report["expressibility"]}
    for surface in SURFACES_20:
        if surface not in answered:
            report["unmeasured"].append(
                "поверхность {} объявлена и НЕ измерена".format(surface))

    for key in ("distinction", "turnover_charge", "operation_kinds"):
        if report[key].get("kind") == UNMEASURED:
            report["unmeasured"].append("{}: {}".format(key, report[key].get("why")))
    if report["reachability"].get("journal", {}).get("kind") == UNMEASURED:
        report["unmeasured"].append(
            "достижимость/журнал: {}".format(report["reachability"]["journal"]["why"]))

    report["verdict"] = {
        "express_absent": sorted(row["surface"] for row in report["expressibility"]
                                 if row["kind"] == "absent"),
        "express_slot_only": sorted(row["surface"] for row in report["expressibility"]
                                    if row["kind"] == "state_field"),
        "source_kind": report["distinction"]["kind"],
        "charge_kind": report["turnover_charge"]["kind"],
        "operations_without_a_money_path_reader": sorted(
            set(report["operation_kinds"].get("operations_declared", []))
            - set(report["operation_kinds"].get("operations_read_on_money_path", []))),
    }
    return report


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §20 исполняется · 1 — находка НАЗВАНА · 2 — НЕ ИЗМЕРЕНО.

    Порядок проверок значим: «не измерено» НЕ ХУЖЕ и НЕ ЛУЧШЕ находки, это
    отдельный исход (инв. #17), и он решается ПЕРВЫМ — иначе ненадёжный замер
    печатался бы как вердикт о мире.
    """
    if report.get("vocab_errors") or report.get("unmeasured"):
        return 2
    v = report["verdict"]
    if v["source_kind"] == "source_refused" and v["charge_kind"] == "charged_named" \
            and not v["express_absent"]:
        return 0
    return 1


def render(report: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append("§20 «New capital» — ввод ОТДЕЛЬНО от перекладки (заказ {})".format(
        report["order"]))
    L.append("  дерево: {}".format(report["root"]))

    L.append("")
    L.append("(а) ВЫРАЗИМОСТЬ «новых денег» по {} поверхностям:".format(
        len(report["surfaces_declared"])))
    for row in report["expressibility"]:
        L.append("  {:10s} {:14s} {}".format(row["surface"], row["kind"], row["why"]))

    d = report["distinction"]
    L.append("")
    L.append("(б) РАЗЛИЧАЕТ ли дверь источник денег: {}".format(d["kind"]))
    L.append("    {}".format(d.get("why")))
    for name, sc in sorted((d.get("scenes") or {}).items()):
        L.append("    сцена {:4s}: ног {} · оборот ${:,.2f} · цена ${:,.2f} · "
                 "выигрыш {:.3f}pp · вердикт {}".format(
                     name, sc["leg_count"], sc["turnover_usd"], sc["cost_usd"],
                     sc["gain_pp"], sc["decision"]))
    if d.get("controls", {}).get("all_changed"):
        L.append("    ✅ контроль: оба положительных контроля сменили вердикт")
    elif d.get("controls"):
        L.append("    ⚠️ контроль НЕ сменил вердикт — ответ не выдан")
    if d.get("gain_differs_by_construction"):
        L.append("    · {}".format(d["gain_differs_by_construction"]))

    c = report["turnover_charge"]
    L.append("")
    L.append("(в) ЗАРЯД оборота на ход, оборота не требующий: {}".format(c["kind"]))
    L.append("    {}".format(c.get("why")))
    if c.get("gates_on_turnover"):
        L.append("    ворот на обороте: {} из {} — {}".format(
            c["gates_on_turnover_count"], c["gates_total"],
            ", ".join(c["gates_on_turnover"])))

    o = report["operation_kinds"]
    L.append("")
    L.append("СЛОВАРЬ РОДОВ ОПЕРАЦИИ, который в системе УЖЕ есть ({}):".format(
        o.get("home")))
    L.append("    {}".format(o.get("why")))
    if o.get("operations_read_on_money_path") is not None:
        L.append("    на денежном пути читается: {} из объявленных {}".format(
            o.get("operations_read_on_money_path") or "НИ ОДНОЙ",
            o.get("operations_declared")))
    for r in (o.get("readers") or []):
        L.append("      {} {}:{} {}({}) — {}".format(
            "money-path" if r["money_path"] else "advisory ",
            r["file"], r["line"], r["callee"], ", ".join(r["operations"]),
            "решение двигает" if r["money_path"] else "решения не двигает"))
    L.append("    дверь цены берёт слагаемые из {} — рода операции там нет вовсе".format(
        o.get("price_door_cost_model")))

    rr = report["reachability"]
    L.append("")
    L.append("(г) ДОСТИЖИМОСТЬ:")
    if rr.get("journal_default_printed"):
        L.append("    ⚠️ {}".format(rr["journal_default_printed"]))
    L.append("    журнал ({}): {}".format(rr.get("journal_path"),
                                          rr.get("journal", {}).get("why")))
    L.append("    потолки: {}".format(rr.get("ceiling", {}).get("why")))

    L.append("")
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for e in report["vocab_errors"]:
            L.append("    {}".format(e))
    if report.get("unmeasured"):
        L.append("⚠️ НЕ ИЗМЕРЕНО ({}):".format(len(report["unmeasured"])))
        for u in report["unmeasured"]:
            L.append("    {}".format(u))
    code = verdict_code(report)
    L.append({0: "✅ §20 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§20 New capital").splitlines()[0])
    ap.add_argument("--root", type=Path, default=None,
                    help="корень дерева (умолчание — дерево этого файла)")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="каталог живого data/ (из worktree его нет по построению; "
                         "без флага мерен git-замороженный канон, и это ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = census(args.root, args.data_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
