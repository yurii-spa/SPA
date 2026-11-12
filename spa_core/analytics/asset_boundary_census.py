#!/usr/bin/env python3
"""Граница актива §18 приказа владельца: есть ли у системы понятие «разрешённая exposure».

Критерий §18 `Asset allocation boundary` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G949 п. 1, цикл #1079.

Дословно §18: «Portfolio CIO не должен самостоятельно менять strategic
underlying exposure. Пример: нельзя продавать BTC/ETH и переходить в USDC
только потому, что USDC yield выше. Нужно разделить: Strategic Asset Allocation
и Yield Optimization inside approved asset allocation. В рамках этой задачи
работать внутри уже разрешенной asset exposure.»

Прибор НИЧЕГО НЕ ПРАВИТ: ни порога, ни политики, ни гейта, ни аллокатора, ни
тюнера. §18 просит РАЗДЕЛЕНИЯ двух решений, а разделение на risk-слое — предмет
№1 ADR-285 и уходит карточкой владельцу.

Три вопроса, и ни один не выводится из другого
------------------------------------------------------------------------------
Заказ G949 п. 1 ставит их дословно:

1. **(а) есть ли у системы понятие «разрешённая asset exposure» вообще**
   (:data:`EXPRESS_KINDS`, ввезено из §17). Спрашивается у живых контрактов —
   подписи ``RiskPolicy.check_new_position`` и ``check_portfolio_health``, поля
   ``Position``, запись, которую строит аллокатор, подпись
   ``rebalance_economics.evaluate``, — а не у памяти автора.
2. **(б) кто вправе её менять** (:data:`AUTHORITY_KINDS`). Объявленная ручка
   меряется ``dataclasses.fields`` обоих контрактов политики; владельческий
   гейт — текстом ``scripts/check_owner_gate.py``; природа карты актива —
   литерал в репозитории против наблюдения (ADR-053: «never stamp `live` on a
   constant»).
3. **(в) отличает ли хоть одна дверь «перекладку внутри актива» от «смены
   актива»** (:data:`DISTINCTION_KINDS`). Мерится ДИФФЕРЕНЦИАЛЬНО: сцена
   прогоняется дважды, и возмущается РОВНО актив пункта назначения. Род
   присваивается по СМЕНЕ вердикта, а не по чтению кода глазами.

Почему оси три, а не одна
------------------------------------------------------------------------------
Урок ADR-943, повторённый §16 и §17: замкнув их в один перечень, две оси
понесли бы ОДИН бит. Состояние «актив у двери выразим, карта актива есть, а
смену актива дверь всё равно не отличает» по шкале выразимости выглядит как
лучший исход — и именно оно найдено у двери КНИГИ.

🪤 ЛОВУШКА ПЕРВАЯ: пример владельца сегодня НЕДОСТИЖИМ, и это не ответ «всё хорошо»
------------------------------------------------------------------------------
Соблазн — построить сцену дословно по примеру владельца: «продать BTC, купить
USDC». Такая сцена ответила бы НЕ НА ТОТ вопрос: в каноническом реестре BTC-ключи
есть (``cbbtc_lending``, ``tbtc_lending``), но оба несут ``IS_ADVISORY=True`` и
``RESEARCH_ONLY=True`` и в живом реестре финансирования
(``data/adapter_registry.json``) отсутствуют ВОВСЕ. То есть сцену закрыл бы
советательный флаг, а не граница актива, и «отказ» был бы верен СЛУЧАЙНО —
ровно та ошибка, которую §16 и §17 исправляли своим же замером.

Поэтому достижимость меряется ОТДЕЛЬНО (:func:`reachability`) и печатается
рядом: среди ФОНДИРУЕМЫХ ключей живого реестра различных активов больше одного ⇒
смена exposure достижима, и дальше вопрос §18 имеет смысл задавать. Сцена
строится на двух фондируемых ключах ОДНОГО тира и ОДНОЙ сети — иначе вердикт
решали бы потолок тира или сетевой потолок, а не актив.

🪤 ЛОВУШКА ВТОРАЯ: актив ключа прибор НЕ РАЗРЕШАЕТ САМ
------------------------------------------------------------------------------
Карту активов даёт канонический сосед
``spa_core.monitoring.swap_existence_price.asset_map`` — две независимые дороги
(совпадение ``(module, class)`` с ``ADAPTER_METADATA`` и атрибут класса
``ASSET``), ``disputed`` при расхождении, ``unknown`` при молчании обеих. Второй
реализации здесь нет НАМЕРЕННО: наивная «asset из ADAPTER_METADATA по ключу»
ответила бы, что актива нет у 23 ключей из 36, тогда как канонический ответ —
14 (цена ошибки — ×1.6 и три ключа живой книги, объявленные безымянными зря).
Два ответа об одном активе, расходящиеся молча, были бы дефектом, который
прибор же и создал бы (урок ``house_view_gap``, цикл #274).

🪤 ЛОВУШКА ТРЕТЬЯ: «вердикт не изменился» без контроля — это о приборе, а не о мире
------------------------------------------------------------------------------
У КАЖДОЙ поверхности свой положительный контроль, и он возмущает ту величину,
которую эта поверхность СВЯЗЫВАЕТ ЗАВЕДОМО (§16/§41): у гейта — сумму против
потолка на протокол, у книги — долю против потолка тира, у цены хода — выгоду.
Контроль не сменил вердикт ⇒ ответ прибора об активе НЕ ВЫДАЁТСЯ (``unmeasured``
с названной причиной), а не печатается как находка. Контроль — не украшение:
«не изменился» и «прибор не работает» выглядят одинаково.

Чего прибор НЕ меряет
------------------------------------------------------------------------------
«Правильный» состав разрешённой exposure. Это предмет №1 ADR-285: какие активы
вообще разрешены — решение владельца, а не замер. Прибор отвечает лишь на
вопрос, ЕСТЬ ли в системе место, где такое решение могло бы быть записано, и
спрашивает ли это место хоть одна дверь.

Словари ВВЕЗЕНЫ, а не перепечатаны
------------------------------------------------------------------------------
``EXPRESS_KINDS``/``OBSERVE_KINDS`` — из §17 (``correlated_dependency_census``),
``UNMEASURED`` — из §13 (``transaction_economics``), ``SURFACES`` и пробы
поверхностей — из §41 (``cio_auto_execution_limits``), ``money_path_axis_call_forms``
— из §17, карта активов — из ``swap_existence_price``. Вторая копия словаря
означала бы две шкалы, расходящиеся молча.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей. Своих копий здесь нет намеренно.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .correlated_dependency_census import (  # noqa: F401
        EXPRESS_KINDS,
        OBSERVE_KINDS,
        money_path_axis_call_forms,
    )
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    EXPRESS_KINDS = ()  # type: ignore[assignment]
    OBSERVE_KINDS = ()  # type: ignore[assignment]
    money_path_axis_call_forms = None  # type: ignore[assignment]
    _VOCAB_ERRORS.append(f"§17 EXPRESS_KINDS: {type(_exc).__name__}: {_exc}")

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append(f"§13 UNMEASURED: {type(_exc).__name__}: {_exc}")

try:
    from spa_core.monitoring.cio_auto_execution_limits import SURFACES
except Exception as _exc:  # pragma: no cover
    SURFACES = ("allocator", "economics", "gate")  # type: ignore[assignment]
    _VOCAB_ERRORS.append(f"§41 SURFACES: {type(_exc).__name__}: {_exc}")


#: Поверхности §18. ``SURFACES`` §41 — поверхности, через которые проходит
#: решение о движении денег. Четвёртая добавлена ЗДЕСЬ и с причиной: §18
#: спрашивает про СОСТАВ КНИГИ («strategic underlying exposure»), а состав книги
#: судит вторая дверь политики (``check_portfolio_health``), которой у §41 в
#: перечне поверхностей нет. Своего словаря поверхностей прибор не заводит —
#: он РАСШИРЯЕТ ввезённый, и расширение названо.
SURFACES_18: Tuple[str, ...] = tuple(SURFACES) + ("book",)

#: КТО вправе менять разрешённую exposure. Порядок — от сильного к слабому.
AUTHORITY_KINDS: Tuple[str, ...] = (
    "owner_only",            # смена требует решения владельца/ADR измеренным механизмом
    "policy_configurable",   # объявленное поле RiskConfig/TriggerParams — ручка владельца
    "code_literal_ungated",  # меняется обычной правкой кода, ни один гейт её не называет
    "no_subject",            # в системе нет объекта, который §18 просит не менять
)

#: ОТЛИЧАЕТ ли дверь «перекладку внутри актива» от «смены актива». Главная ось §18.
DISTINCTION_KINDS: Tuple[str, ...] = (
    "switch_refused",    # дверь отказала смене актива — то, что §18 просит
    "switch_charged",    # дверь пропустила, но вердикт изменился (счёт/предупреждение)
    "switch_invisible",  # вердикт ТОТ ЖЕ — то, что §18 запрещает
    "no_input_door",     # актив не является входом двери: возмутить его нечем
)

#: Сцена ОБЪЯВЛЕНА здесь, а не взята из живого трека: предмет — ПОВЕДЕНИЕ
#: ДВЕРЕЙ, оно обязано быть воспроизводимым на любой машине в любой день. Живой
#: трек (`data/equity_curve_daily.json`) не входит сюда ни одним числом —
#: запрет `CLAUDE.md`.
SCENE_CAPITAL_USD = 100_000.0

#: Живой реестр финансирования: по нему меряется ДОСТИЖИМОСТЬ смены exposure.
#: Файл git-tracked, поэтому ответ воспроизводим; нет файла ⇒ третий исход.
LIVE_REGISTRY_REL = "data/adapter_registry.json"

#: Производитель записи, которую дверь гейта получает на денежном пути. Претензия
#: «актив до гейта не доезжает» СВЕРЯЕТСЯ с этим файлом, а не утверждается.
GATE_RECORD_PRODUCER_REL = "spa_core/orchestrator/adapter_orchestrator.py"


# ---------------------------------------------------------------------------
# Ввоз дверей. Дверь не ввезена ⇒ третий исход, а не подставленная заглушка.
# ---------------------------------------------------------------------------

def load_policy() -> Tuple[Any, Optional[str]]:
    try:
        from spa_core.risk.policy import Position, PortfolioState, RiskConfig, RiskPolicy
    except Exception as exc:  # noqa: BLE001
        return None, f"политика не ввезена: {type(exc).__name__}: {exc}"
    return {"Position": Position, "PortfolioState": PortfolioState,
            "RiskConfig": RiskConfig, "RiskPolicy": RiskPolicy}, None


def load_asset_map() -> Tuple[Dict[str, dict], Dict[str, Any], Optional[str]]:
    """Канонический актив КАЖДОГО ключа реестра — соседом, не своей копией."""
    try:
        from spa_core.monitoring.swap_existence_price import asset_map
    except Exception as exc:  # noqa: BLE001
        return {}, {}, f"карта активов не ввезена: {type(exc).__name__}: {exc}"
    try:
        amap, ctx = asset_map()
    except Exception as exc:  # noqa: BLE001
        return {}, {}, f"карта активов не построена: {type(exc).__name__}: {exc}"
    if not ctx.get("measured"):
        return {}, ctx, f"карта активов НЕ ИЗМЕРЕНА: {ctx.get('reason')}"
    return amap, ctx, None


def load_surface_probes() -> Tuple[Dict[str, Callable], Optional[str]]:
    """Пробы поверхностей §41 — ввезены, чтобы не было ВТОРОГО ответа о них."""
    try:
        from spa_core.monitoring.cio_auto_execution_limits import (
            _econ_scene, _econ_verdict, _gate_verdict, _trim_fingerprint, _trim_record,
        )
    except Exception as exc:  # noqa: BLE001
        return {}, f"пробы §41 не ввезены: {type(exc).__name__}: {exc}"
    return {"gate_verdict": _gate_verdict,
            "econ_scene": _econ_scene,
            "econ_verdict": _econ_verdict,
            # четвёртая поверхность §41 (ADR-987): урезание хода ADR-850
            "trim_record": _trim_record,
            "trim_fingerprint": _trim_fingerprint}, None


# ---------------------------------------------------------------------------
# (а) ВЫРАЗИМОСТЬ: где актив вообще может быть назван
# ---------------------------------------------------------------------------

def _producer_builds_asset(root: Path) -> Tuple[Optional[bool], Optional[str]]:
    """Несёт ли запись, которую строит производитель снимка, ключ ``asset``.

    Меряется AST'ом: подстрока ``asset`` в файле сказала бы лишь, что слово
    где-то есть. Файла нет ⇒ третий исход с названной причиной, а не «не несёт».
    """
    path = root / GATE_RECORD_PRODUCER_REL
    if not path.exists():
        return None, f"{GATE_RECORD_PRODUCER_REL}: файла нет"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"{GATE_RECORD_PRODUCER_REL}: не разобран: {type(exc).__name__}: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "asset":
                    return True, None
    return False, None


def _allocator_record_fields(root: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    """Поля записи, которую аллокатор строит для КАЖДОГО кандидата."""
    path = root / "spa_core/allocator/allocator.py"
    if not path.exists():
        return None, "spa_core/allocator/allocator.py: файла нет"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"аллокатор не разобран: {type(exc).__name__}: {exc}"
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


def expressibility(root: Path, pol: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Род выразимости актива у каждой из поверхностей §18 (пять с #1104: + `trim`)."""
    out: List[Dict[str, Any]] = []

    # ── поверхность gate: дверь допуска + запись, которую она получает ──────
    sig = sorted(inspect.signature(pol["RiskPolicy"].check_new_position).parameters)
    builds, why = _producer_builds_asset(root)
    if builds is None:
        kind, detail = UNMEASURED, f"производитель записи не прочитан: {why}"
    elif "asset" in sig:
        kind, detail = "door_input", "актив — параметр двери допуска"
    elif builds:
        kind = "registry_only"
        detail = ("актив не параметр двери допуска, но производитель снимка его "
                  "в запись кладёт — до двери он доезжает данными")
    else:
        kind = "absent"
        detail = (f"актив не параметр двери допуска (параметры: {sig}) И "
                  f"производитель снимка ключ `asset` в запись НЕ кладёт "
                  f"({GATE_RECORD_PRODUCER_REL}) — до двери он не доезжает вовсе")
    out.append({"surface": "gate", "kind": kind, "detail": detail,
                "door_params": sig})

    # ── поверхность book: вторая дверь политики ─────────────────────────────
    pos_fields = [f.name for f in dataclasses.fields(pol["Position"])]
    book_sig = sorted(inspect.signature(pol["RiskPolicy"].check_portfolio_health).parameters)
    if "asset" in book_sig:
        kind, detail = "door_input", "актив — параметр двери книги"
    elif "asset" in pos_fields:
        kind = "state_field"
        detail = (f"актив — поле строки книги (`Position.asset`), но НЕ параметр "
                  f"двери книги (параметры: {book_sig}); дверь получает его "
                  f"через `state.positions`")
    else:
        kind, detail = "absent", f"актива нет ни в параметрах, ни в полях книги: {pos_fields}"
    out.append({"surface": "book", "kind": kind, "detail": detail,
                "position_fields": pos_fields, "door_params": book_sig})

    # ── поверхность economics: стои́т ли ход своих издержек ──────────────────
    try:
        from spa_core.allocator.rebalance_economics import evaluate
        econ_sig = sorted(inspect.signature(evaluate).parameters)
        if "asset" in econ_sig or "assets" in econ_sig:
            kind, detail = "door_input", "актив — параметр двери цены хода"
        else:
            kind = "absent"
            detail = (f"у двери цены хода входа об активе нет ВОВСЕ "
                      f"(есть `chains`, нет `assets`): {econ_sig}")
    except Exception as exc:  # noqa: BLE001
        kind, detail, econ_sig = UNMEASURED, f"дверь цены хода не ввезена: {exc}", []
    out.append({"surface": "economics", "kind": kind, "detail": detail,
                "door_params": econ_sig})

    # ── поверхность allocator: что вообще предлагается ──────────────────────
    fields, why = _allocator_record_fields(root)
    enforcers, caps = _allocator_dimensions()
    if fields is None:
        kind, detail = UNMEASURED, f"поверхность предложения не прочитана: {why}"
    elif "asset" in fields:
        kind, detail = "door_input", "актив — поле записи кандидата у аллокатора"
    else:
        kind = "absent"
        detail = (f"запись кандидата у аллокатора актива не несёт ({fields}); "
                  f"потолков-измерений у него {len(enforcers)} и ни один не про актив "
                  f"({enforcers}); объявленных потолков про актив нет "
                  f"(объявлено: {caps})")
    out.append({"surface": "allocator", "kind": kind, "detail": detail,
                "record_fields": fields, "enforcers": enforcers, "caps": caps})

    # ── поверхность trim: урезание хода (ADR-850; четвёртая поверхность §41, ADR-987)
    try:
        from spa_core.paper_trading.admissible_trim import apply_admissible_trim
        trim_sig = sorted(inspect.signature(apply_admissible_trim).parameters)
        if "asset" in trim_sig or "assets" in trim_sig:
            kind, detail = "door_input", "актив — параметр урезания хода"
        elif "adapters" in trim_sig:
            kind = "registry_only"
            detail = (f"актив не параметр урезания (параметры: {trim_sig}); до "
                      f"переспрошенного гейта он доезжает ДАННЫМИ — в снимке `adapters`, "
                      f"который трим не читает, а передаёт")
        else:
            kind = "absent"
            detail = (f"у урезания нет ни входа об активе, ни снимка, в котором он "
                      f"мог бы ехать: {trim_sig}")
    except Exception as exc:  # noqa: BLE001
        kind, detail, trim_sig = UNMEASURED, f"шаг урезания не ввезён: {exc}", []
    out.append({"surface": "trim", "kind": kind, "detail": detail,
                "door_params": trim_sig})

    return out


def _allocator_dimensions() -> Tuple[List[str], List[str]]:
    """Измерения, по которым аллокатор ВООБЩЕ ставит потолки — найденные, не вшитые."""
    try:
        from spa_core.allocator.allocator import StrategyAllocator
    except Exception:  # noqa: BLE001
        return [], []
    enforcers = sorted(n for n in dir(StrategyAllocator) if n.startswith("_enforce"))
    caps = sorted(n for n in dir(StrategyAllocator) if n.isupper())
    return enforcers, caps


# ---------------------------------------------------------------------------
# (б) ВЛАСТЬ: кто вправе менять разрешённую exposure
# ---------------------------------------------------------------------------

def _policy_asset_dials() -> Tuple[List[str], Optional[str]]:
    """Объявленные поля политики, которыми можно было бы задать границу актива."""
    names: List[str] = []
    try:
        from spa_core.allocator.rebalance_economics import TriggerParams
        from spa_core.risk.policy import RiskConfig
    except Exception as exc:  # noqa: BLE001
        return [], f"контракты политики не ввезены: {type(exc).__name__}: {exc}"
    for contract in (RiskConfig, TriggerParams):
        for field in dataclasses.fields(contract):
            low = field.name.lower()
            if "asset" in low or "underlying" in low or "collateral" in low:
                names.append(f"{contract.__name__}.{field.name}")
    return sorted(names), None


def _owner_gate_names_asset(root: Path) -> Tuple[Optional[bool], Optional[str]]:
    """Называет ли владельческий гейт актив хоть одним своим классом."""
    path = root / "scripts/check_owner_gate.py"
    if not path.exists():
        return None, "scripts/check_owner_gate.py: файла нет"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, f"владельческий гейт не прочитан: {type(exc).__name__}: {exc}"
    return ("asset" in text.lower()), None


def authority(root: Path, amap_ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Кто вправе менять разрешённую exposure — по измеренным механизмам."""
    dials, dial_why = _policy_asset_dials()
    gated, gate_why = _owner_gate_names_asset(root)

    # Где актив объявлен сегодня и чем он является по природе.
    subjects: List[Dict[str, Any]] = [
        {"where": "spa_core/adapters/registry.py::ADAPTER_METADATA[*]['asset']",
         "nature": "declared_literal",
         "covers": amap_ctx.get("metadata_keys"),
         "why": "захардкоженная карта в коде; наблюдением не является (ADR-053)"},
        {"where": "класс адаптера, атрибут ASSET",
         "nature": "declared_literal",
         "covers": len(amap_ctx.get("resolved_by_class_attribute_only") or []),
         "why": "литерал в классе; вторая дорога канонической карты"},
        {"where": "spa_core/database/schema.sql::protocols.asset "
                  "(сеется INITIAL_PROTOCOLS)",
         "nature": "declared_literal",
         "covers": None,
         "why": "колонка NOT NULL, но ключи там СВОЕГО пространства имён "
                "(слаги через дефис) — с ключами реестра не пересекаются"},
        {"where": LIVE_REGISTRY_REL,
         "nature": "absent",
         "covers": 0,
         "why": "живой реестр финансирования поля `asset` не несёт ВОВСЕ "
                "(есть `chain`, `tier`, `per_protocol_cap`)"},
    ]

    if dial_why:
        kind, detail = UNMEASURED, dial_why
    elif dials:
        kind, detail = "policy_configurable", f"объявленные ручки: {dials}"
    elif gated is None:
        kind, detail = UNMEASURED, f"владельческий гейт не измерен: {gate_why}"
    elif gated:
        kind = "owner_only"
        detail = "актив называет владельческий гейт — смена требует карточки"
    else:
        kind = "no_subject"
        detail = ("объекта «разрешённая asset exposure» в системе НЕТ: ни одного "
                  "поля политики (RiskConfig 22 + TriggerParams 15), ни одного "
                  "класса владельческого гейта, ни одного потолка аллокатора. "
                  "Есть лишь ЯРЛЫК актива у отдельных ключей, и он — литерал в "
                  "коде: меняется обычной правкой, ни один гейт её не называет")
    return {"kind": kind, "detail": detail, "dials": dials,
            "owner_gate_names_asset": gated, "subjects": subjects,
            "label_authority": "code_literal_ungated" if kind == "no_subject" else kind}


# ---------------------------------------------------------------------------
# ДОСТИЖИМОСТЬ: имеет ли вопрос §18 смысл на сегодняшнем реестре
# ---------------------------------------------------------------------------

def reachability(root: Path, amap: Dict[str, dict]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Достижима ли смена exposure среди ФОНДИРУЕМЫХ ключей живого реестра.

    Советательный ключ сценой быть не может: его закрыл бы флаг
    ``research_only``/``advisory_only``, а не граница актива, и «отказ» вышел бы
    верен СЛУЧАЙНО (ошибка, которую §16 и §17 исправляли своим же замером).
    """
    path = root / LIVE_REGISTRY_REL
    if not path.exists():
        return {}, f"{LIVE_REGISTRY_REL}: файла нет — достижимость НЕ ИЗМЕРЕНА"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, f"{LIVE_REGISTRY_REL}: не разобран: {type(exc).__name__}: {exc}"
    entries = doc.get("adapters")
    if not isinstance(entries, dict):
        return {}, f"{LIVE_REGISTRY_REL}: раздела `adapters` в объявленной форме нет"

    fundable: Dict[str, Dict[str, Any]] = {}
    advisory: Dict[str, str] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "active":
            continue
        if entry.get("research_only") or entry.get("advisory_only"):
            advisory[str(key)] = "research_only/advisory_only"
            continue
        info = amap.get(str(key)) or {}
        fundable[str(key)] = {
            "asset": info.get("asset"),
            "asset_state": info.get("state", "НЕ В КАНОНИЧЕСКОМ РЕЕСТРЕ"),
            "tier": entry.get("tier"),
            "chain": entry.get("chain"),
        }

    by_asset: Dict[str, List[str]] = {}
    for key, info in fundable.items():
        by_asset.setdefault(info["asset"] or "UNKNOWN", []).append(key)
    named = {a: sorted(ks) for a, ks in sorted(by_asset.items()) if a != "UNKNOWN"}
    unknown = sorted(by_asset.get("UNKNOWN", []))

    # BTC-ключи примера владельца: есть ли они и почему недостижимы.
    btc = {k: v for k, v in amap.items() if "btc" in k.lower()}
    return {
        "fundable_keys": len(fundable),
        "advisory_keys": len(advisory),
        "assets_named": named,
        "distinct_named_assets": len(named),
        "asset_unknown_keys": unknown,
        "owner_example_keys": sorted(btc),
        "owner_example_reachable": sorted(k for k in btc if k in fundable),
        "fundable": fundable,
    }, None


# ---------------------------------------------------------------------------
# (в) РАЗЛИЧЕНИЕ: отличает ли дверь перекладку внутри актива от смены актива
# ---------------------------------------------------------------------------

def pick_scene(reach: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Три ключа сцены: источник, сосед ТОГО ЖЕ актива, сосед ДРУГОГО актива.

    Все три обязаны делить тир И сеть: иначе вердикт решал бы потолок тира или
    сетевой потолок, а не актив, — и ответ был бы верен не по делу. Не нашлось ⇒
    третий исход с названной причиной, а не сцена на выдуманных ключах.
    """
    fundable = reach.get("fundable") or {}
    groups: Dict[Tuple[Any, Any], Dict[str, List[str]]] = {}
    for key, info in fundable.items():
        if not info.get("asset"):
            continue
        slot = groups.setdefault((info.get("tier"), str(info.get("chain") or "").lower()), {})
        slot.setdefault(info["asset"], []).append(key)
    for (tier, chain), by_asset in sorted(groups.items(), key=lambda kv: str(kv[0])):
        same = [a for a, ks in by_asset.items() if len(ks) >= 2]
        others = sorted(a for a in by_asset if len(by_asset[a]) >= 1)
        for asset in sorted(same):
            for other in others:
                if other == asset:
                    continue
                keys = sorted(by_asset[asset])
                return {
                    "tier": tier, "chain": chain,
                    "source": keys[0], "source_asset": asset,
                    "same_asset": keys[1], "same_asset_asset": asset,
                    "other_asset": sorted(by_asset[other])[0], "other_asset_asset": other,
                }, None
    return None, ("сцены нет: среди фондируемых ключей не нашлось тира+сети, где "
                  "были бы и ДВА ключа одного актива, и ключ другого актива — "
                  "возмутить РОВНО актив, удержав тир и сеть, нечем")


def role_normalised(verdict: str, scene: Dict[str, str]) -> str:
    """Отпечаток вердикта, из которого вынута ЛИЧНОСТЬ ключей сцены.

    🪤 Ошибка первой редакции, найденная своим же замером. Два пункта назначения
    §18 обязаны быть РАЗНЫМИ ключами — иначе у них не было бы разных активов. Но
    отпечаток двери допуска несёт имя ключа (``book={'compound_v3': 15000.0}``
    против ``book={'spark_susds': 15000.0}``), и прямое сравнение объявило
    различение там, где дверь всего лишь назвала, куда ушли деньги. Такой ответ
    был бы «изменился» при ЛЮБОМ возмущении имени — то есть мерил бы не актив.

    Поэтому имена заменяются РОЛЯМИ (``SRC``/``DEST``) до сравнения, и то же
    делается с текстами нарушений/предупреждений, где имена тоже встречаются.
    Положительный контроль самого нормализатора — тест
    ``test_role_normaliser_removes_the_identity_confound``: без него две сцены,
    различающиеся ТОЛЬКО именем пункта назначения, дают разные отпечатки.
    """
    out = str(verdict)
    for role, key in (("DEST", scene.get("same_asset")),
                      ("DEST", scene.get("other_asset")),
                      ("SRC", scene.get("source"))):
        if key:
            out = out.replace(str(key), role)
    # Переименование могло сбить порядок ключей словаря в отпечатке — вернуть его.
    if "book={" in out:
        head, _, tail = out.partition("book={")
        body, close, rest = tail.partition("}")
        try:
            parsed = ast.literal_eval("{" + body + "}")
            body = ", ".join(f"{k!r}: {parsed[k]}" for k in sorted(parsed))
        except Exception:  # noqa: BLE001 — не разобрали ⇒ оставить как есть
            pass
        out = f"{head}book={{{body}{close}{rest}"
    return out


def _gate_specs(scene: Dict[str, str], dest: str, dest_asset: str,
                amount_frac: float) -> Tuple[Dict[str, float], List[dict]]:
    """Цель и снимок для двери допуска: уходим из источника, приходим в ``dest``."""
    tier = str(scene["tier"]).upper()
    tier = tier if tier.startswith("T") else f"T{tier}"
    spec = [
        {"protocol": scene["source"], "tier": tier, "apy_pct": 4.0,
         "chain": scene["chain"], "asset": scene["source_asset"]},
        {"protocol": dest, "tier": tier, "apy_pct": 8.0,
         "chain": scene["chain"], "asset": dest_asset},
    ]
    target = {dest: amount_frac * SCENE_CAPITAL_USD}
    return target, spec


def probe_gate(scene: Dict[str, str], probes: Dict[str, Callable]) -> Dict[str, Any]:
    """Дверь допуска: тот же ход, возмущён РОВНО актив пункта назначения.

    Положительный контроль возмущает СУММУ против потолка на протокол — величину,
    которую эта дверь связывает заведомо (§16, ADR-959). Контроль молчит ⇒ ответ
    об активе не выдаётся.
    """
    verdict = probes["gate_verdict"]
    held = {scene["source"]: 0.15 * SCENE_CAPITAL_USD}

    t_same, s_same = _gate_specs(scene, scene["same_asset"], scene["same_asset_asset"], 0.15)
    t_other, s_other = _gate_specs(scene, scene["other_asset"], scene["other_asset_asset"], 0.15)
    try:
        v_same = role_normalised(verdict(t_same, s_same, held=held), scene)
        v_other = role_normalised(verdict(t_other, s_other, held=held), scene)
        # контроль: та же сцена, но сумма заведомо выше любого потолка на протокол
        t_big, s_big = _gate_specs(scene, scene["same_asset"], scene["same_asset_asset"], 0.95)
        v_big = role_normalised(verdict(t_big, s_big, held=held), scene)
    except Exception as exc:  # noqa: BLE001
        return {"surface": "gate", "kind": UNMEASURED,
                "detail": f"дверь допуска не ответила: {type(exc).__name__}: {exc}"}

    if v_big == v_same:
        return {"surface": "gate", "kind": UNMEASURED,
                "detail": ("положительный контроль МОЛЧИТ: сумма 15 % → 95 % против "
                           "потолка на протокол вердикт не изменила, значит прибор "
                           "не способен увидеть различение и на активе"),
                "control": {"base": v_same, "oversized": v_big}}

    kind = "switch_invisible" if v_other == v_same else "switch_charged"
    return {
        "surface": "gate", "kind": kind,
        "detail": (f"ход 15 % капитала из `{scene['source']}` ({scene['source_asset']}): "
                   f"в `{scene['same_asset']}` ({scene['same_asset_asset']}, ТОТ ЖЕ актив) → "
                   f"{v_same}; в `{scene['other_asset']}` ({scene['other_asset_asset']}, "
                   f"ДРУГОЙ актив) → {v_other}. Тир {scene['tier']} и сеть "
                   f"{scene['chain']} удержаны, личность ключей вынута из отпечатка. "
                   f"ВАЖНО: поле `asset` в этой сцене СИНТЕЗИРОВАНО пробой §41 — живой "
                   f"производитель снимка его в запись не кладёт (см. ось выразимости)"),
        "within_asset": v_same, "across_asset": v_other,
        "control": {"base": v_same, "oversized": v_big},
    }


def probe_book(scene: Dict[str, str], pol: Dict[str, Any]) -> Dict[str, Any]:
    """Дверь книги: та же книга, возмущён РОВНО актив одной строки.

    Здесь актив — настоящий вход (``Position.asset``), поэтому дифференциал не
    вырожден. Положительный контроль возмущает ДОЛЮ строки против потолка тира.
    """
    Position, PortfolioState = pol["Position"], pol["PortfolioState"]
    RiskPolicy = pol["RiskPolicy"]
    tier = str(scene["tier"]).upper()
    tier = tier if tier.startswith("T") else f"T{tier}"

    def _book(asset_of_second: str, second_frac: float = 0.15) -> Any:
        return PortfolioState(
            total_capital_usd=SCENE_CAPITAL_USD,
            positions=[
                Position(protocol_key=scene["source"], tier=tier,
                         asset=scene["source_asset"],
                         amount_usd=0.15 * SCENE_CAPITAL_USD,
                         apy_at_open=4.0, current_apy=4.0, days_held=99.0,
                         chain=scene["chain"]),
                Position(protocol_key=scene["same_asset"], tier=tier,
                         asset=asset_of_second,
                         amount_usd=second_frac * SCENE_CAPITAL_USD,
                         apy_at_open=8.0, current_apy=8.0, days_held=99.0,
                         chain=scene["chain"]),
            ])

    def _ask(state: Any) -> str:
        """Отпечаток двери книги: вердикт + ТЕКСТЫ, а не только их счёт.

        Счёт нарушений спрятал бы смену СОДЕРЖАНИЯ при том же количестве, то
        есть выдал бы «различения нет» за замер. Личность ключей из текстов
        вынута тем же нормализатором, что у двери допуска.
        """
        res = RiskPolicy().check_portfolio_health(state)
        texts = sorted(str(x) for x in (list(getattr(res, "violations", []) or [])
                                        + list(getattr(res, "warnings", []) or [])))
        return role_normalised(
            f"approved={bool(getattr(res, 'approved', None))}"
            f"|violations={len(getattr(res, 'violations', []) or [])}"
            f"|warnings={len(getattr(res, 'warnings', []) or [])}"
            f"|texts={texts}", scene)

    try:
        v_same = _ask(_book(scene["same_asset_asset"]))
        v_other = _ask(_book(scene["other_asset_asset"]))
        v_big = _ask(_book(scene["same_asset_asset"], second_frac=0.95))
    except Exception as exc:  # noqa: BLE001
        return {"surface": "book", "kind": UNMEASURED,
                "detail": f"дверь книги не ответила: {type(exc).__name__}: {exc}"}

    if v_big == v_same:
        return {"surface": "book", "kind": UNMEASURED,
                "detail": ("положительный контроль МОЛЧИТ: доля строки 15 % → 95 % "
                           "вердикт книги не изменила — прибор не способен увидеть "
                           "различение и на активе"),
                "control": {"base": v_same, "oversized": v_big}}

    kind = "switch_invisible" if v_other == v_same else "switch_charged"
    return {
        "surface": "book", "kind": kind,
        "detail": (f"та же книга, у второй строки актив "
                   f"{scene['same_asset_asset']} → {scene['other_asset_asset']}: "
                   f"{v_same} → {v_other}. Актив здесь НАСТОЯЩИЙ вход "
                   f"(`Position.asset`), а не выдуманное поле сцены"),
        "within_asset": v_same, "across_asset": v_other,
        "control": {"base": v_same, "oversized": v_big},
    }


def probe_economics(probes: Dict[str, Callable]) -> Dict[str, Any]:
    """Дверь цены хода: входа об активе нет ВОВСЕ ⇒ возмутить нечем.

    Это не «измерено и равно»: подать актив этой двери НЕЧЕМ, и выдать её
    молчание за «различения нет» значило бы утверждать о замере, которого не было
    (инв. #17). Контроль печатается, чтобы было видно: дверь жива и на СВОЮ
    величину откликается.
    """
    try:
        from spa_core.allocator.rebalance_economics import evaluate
        params = sorted(inspect.signature(evaluate).parameters)
        base = probes["econ_verdict"](probes["econ_scene"]())
        weak = probes["econ_verdict"](probes["econ_scene"](
            apy_pct={"aave_v3": 2.0, "pendle": 2.04}))
    except Exception as exc:  # noqa: BLE001
        return {"surface": "economics", "kind": UNMEASURED,
                "detail": f"дверь цены хода не ответила: {type(exc).__name__}: {exc}"}
    if base == weak:
        return {"surface": "economics", "kind": UNMEASURED,
                "detail": ("положительный контроль МОЛЧИТ: обрушенная выгода вердикт "
                           "не изменила — о живости двери сказать нечего"),
                "control": {"base": base, "weak_gain": weak}}
    return {"surface": "economics", "kind": "no_input_door",
            "detail": (f"входа об активе у двери нет: {params}. Есть `chains` — то есть "
                       f"СЕТЬ дверь спрашивает, а АКТИВ подать нечем"),
            "control": {"base": base, "weak_gain": weak}}


def probe_trim(probes: Dict[str, Callable]) -> Dict[str, Any]:
    """Урезание хода (ADR-850): входа об активе нет ВОВСЕ ⇒ возмутить нечем.

    Четвёртая поверхность §41 (ADR-987). Трим читает доллары ног и потолки
    РАЗМЕРА; актив до него доезжает только внутри снимка ``adapters``, который он
    не читает, а ПЕРЕДАЁТ переспрошенному гейту — ответ гейта про актив уже
    измерен :func:`probe_gate`, и считать его здесь второй раз значило бы завести
    два ответа об одной двери. Контроль печатается: трим жив и на СВОЮ величину
    (размер хода) откликается — иначе его молчание об активе ничего не стоило бы.
    """
    try:
        from spa_core.paper_trading.admissible_trim import apply_admissible_trim
        params = sorted(inspect.signature(apply_admissible_trim).parameters)
        cap = SCENE_CAPITAL_USD
        held = {"aave_v3": 0.40 * cap, "compound_v3": 0.0}
        small = probes["trim_fingerprint"](probes["trim_record"](
            held, {"aave_v3": 0.30 * cap, "compound_v3": 0.10 * cap}))
        big = probes["trim_fingerprint"](probes["trim_record"](
            held, {"aave_v3": 0.10 * cap, "compound_v3": 0.30 * cap}))
    except Exception as exc:  # noqa: BLE001
        return {"surface": "trim", "kind": UNMEASURED,
                "detail": f"шаг урезания не ответил: {type(exc).__name__}: {exc}"}
    if small == big:
        return {"surface": "trim", "kind": UNMEASURED,
                "detail": ("положительный контроль МОЛЧИТ: ход втрое больше потолка "
                           "урезан так же, как ход внутри потолка — о живости трима "
                           "сказать нечего"),
                "control": {"within_caps": small, "over_caps": big}}
    if "asset" in params or "assets" in params:
        return {"surface": "trim", "kind": UNMEASURED,
                "detail": (f"у урезания ПОЯВИЛСЯ вход об активе ({params}) — проба "
                           f"смены актива для него не написана; «не измерено», а не "
                           f"«не различает»"),
                "control": {"within_caps": small, "over_caps": big}}
    return {"surface": "trim", "kind": "no_input_door",
            "detail": (f"входа об активе у урезания нет: {params}. Оно читает доллары "
                       f"ног и потолки РАЗМЕРА (ADR-850); актив едет мимо него в снимке "
                       f"`adapters` к переспрошенному гейту, чей ответ уже измерен"),
            "control": {"within_caps": small, "over_caps": big}}


def probe_allocator(root: Path) -> Dict[str, Any]:
    """Поверхность предложения: актива нет ни во входе, ни в потолках."""
    fields, why = _allocator_record_fields(root)
    enforcers, caps = _allocator_dimensions()
    if fields is None:
        return {"surface": "allocator", "kind": UNMEASURED,
                "detail": f"поверхность предложения не прочитана: {why}"}
    if "asset" in fields:
        return {"surface": "allocator", "kind": "switch_charged",
                "detail": "запись кандидата несёт актив — различение возможно"}
    chain_caps = [c for c in caps if "CHAIN" in c]
    return {"surface": "allocator", "kind": "no_input_door",
            "detail": (f"актив не входит в запись кандидата ({fields}) и ни один "
                       f"потолок не ключуется им: измерений-потолков {len(enforcers)} "
                       f"({enforcers}); у СЕТИ потолки есть ({chain_caps}), у АКТИВА — "
                       f"ни одного. Возмутить нечем: поверхность предложения актива "
                       f"не видит"),
            "record_fields": fields, "enforcers": enforcers}


# ---------------------------------------------------------------------------
# Заказ G949 п. 4: зовётся ли дверь книги со входами peg и срока выхода
# ---------------------------------------------------------------------------

def depeg_inputs_on_money_path(root: Path) -> Dict[str, Any]:
    """Подаёт ли денежный путь двери книги ``stablecoin_prices`` и ``exit_latency_map``.

    Вопрос соседний §18 по ПРЕДМЕТУ (и тот и другой — про актив у двери книги) и
    поставлен заказом G949 п. 4. Форма зова меряется AST'ом ввезённой дверью §17,
    своей копии разбора здесь нет.
    """
    if money_path_axis_call_forms is None:
        return {"kind": UNMEASURED, "detail": "читатель формы зова §17 не ввезён"}
    calls, why = money_path_axis_call_forms(root)
    if why and not calls:
        return {"kind": UNMEASURED, "detail": f"форма зова не измерена: {why}"}
    missing_prices = [c for c in calls if "stablecoin_prices" not in (c.get("keywords") or [])]
    missing_latency = [c for c in calls if "exit_latency_map" not in (c.get("keywords") or [])]
    return {
        "kind": "finding" if (missing_prices or missing_latency) else "ok",
        "calls": calls,
        "detail": (f"зовов двери книги на денежном пути {len(calls)}; без "
                   f"`stablecoin_prices` — {len(missing_prices)}, без "
                   f"`exit_latency_map` — {len(missing_latency)}. Политика запускает "
                   f"детекцию depeg ТОЛЬКО когда цены переданы "
                   f"(`if stablecoin_prices is not None`), поэтому на денежном пути "
                   f"она не запускается НИ РАЗУ"),
        "note": why,
    }


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def census(root: Optional[Path] = None) -> Dict[str, Any]:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    report: Dict[str, Any] = {
        "section": "§18 Asset allocation boundary",
        "order": "G949 п. 1",
        "root": str(base),
        "vocab_errors": list(_VOCAB_ERRORS),
        "express_kinds": list(EXPRESS_KINDS),
        "observe_kinds": list(OBSERVE_KINDS),
        "authority_kinds": list(AUTHORITY_KINDS),
        "distinction_kinds": list(DISTINCTION_KINDS),
        "surfaces": list(SURFACES_18),
    }

    pol, why = load_policy()
    if pol is None:
        report["unmeasured"] = why
        return report
    amap, amap_ctx, why = load_asset_map()
    if why:
        report["unmeasured"] = why
        return report
    probes, why = load_surface_probes()
    if why:
        report["unmeasured"] = why
        return report

    report["asset_map"] = amap_ctx
    report["expressibility"] = expressibility(base, pol)
    report["authority"] = authority(base, amap_ctx)

    reach, why = reachability(base, amap)
    report["reachability"] = reach
    report["reachability_unmeasured"] = why

    if why:
        report["distinction"] = [{"surface": s, "kind": UNMEASURED,
                                  "detail": f"достижимость не измерена: {why}"}
                                 for s in SURFACES_18]
        report["scene"] = None
    else:
        scene, scene_why = pick_scene(reach)
        report["scene"] = scene
        report["scene_unfit_reason"] = scene_why
        if scene is None:
            report["distinction"] = [{"surface": s, "kind": UNMEASURED,
                                      "detail": scene_why} for s in SURFACES_18]
        else:
            report["distinction"] = [
                probe_gate(scene, probes),
                probe_book(scene, pol),
                probe_economics(probes),
                probe_trim(probes),
                probe_allocator(base),
            ]

    report["depeg_inputs"] = depeg_inputs_on_money_path(base)
    return report


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — граница выразима и соблюдается · 1 — находка · 2 — НЕ ИЗМЕРЕНО."""
    if report.get("unmeasured") or report.get("vocab_errors"):
        return 2
    rows = report.get("distinction") or []
    if any(r.get("kind") == UNMEASURED for r in rows):
        return 2
    if any(r.get("kind") in ("switch_invisible", "no_input_door") for r in rows):
        return 1
    if report.get("authority", {}).get("kind") in ("no_subject", UNMEASURED):
        return 1
    if any(r.get("kind") == "absent" for r in report.get("expressibility") or []):
        return 1
    if report.get("depeg_inputs", {}).get("kind") == "finding":
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    out: List[str] = []
    out.append(f"§18 «Asset allocation boundary» — заказ {report['order']} "
               f"(дерево {report['root']})")
    if report.get("vocab_errors"):
        out.append("  ⚠️ НЕ ИЗМЕРЕНО: словари не ввезены — "
                   + "; ".join(report["vocab_errors"]))
    if report.get("unmeasured"):
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО: {report['unmeasured']}")
        return "\n".join(out)

    ctx = report.get("asset_map") or {}
    out.append(f"\n  КАРТА АКТИВА (канонический сосед, две дороги): ключей реестра "
               f"{ctx.get('registry_keys')}, актив назван у {ctx.get('resolved')}, "
               f"НЕ НАЗВАН у {ctx.get('unknown')}, спорных {ctx.get('disputed')}")

    reach = report.get("reachability") or {}
    if report.get("reachability_unmeasured"):
        out.append(f"\n  ДОСТИЖИМОСТЬ: ⚠️ {report['reachability_unmeasured']}")
    else:
        out.append(f"\n  ДОСТИЖИМОСТЬ смены exposure: фондируемых ключей "
                   f"{reach.get('fundable_keys')}, различных НАЗВАННЫХ активов "
                   f"{reach.get('distinct_named_assets')} "
                   f"({', '.join(f'{a}×{len(k)}' for a, k in (reach.get('assets_named') or {}).items())}), "
                   f"актив НЕ НАЗВАН у {len(reach.get('asset_unknown_keys') or [])}")
        ex = reach.get("owner_example_keys") or []
        out.append(f"    пример владельца (BTC): ключей в каноне {len(ex)} "
                   f"({', '.join(ex) or '—'}), фондируемых "
                   f"{len(reach.get('owner_example_reachable') or [])} — сцену на нём "
                   f"строить НЕЛЬЗЯ: её закрыл бы советательный флаг, а не граница актива")

    out.append("\n  (а) ВЫРАЗИМОСТЬ актива по поверхностям:")
    for row in report.get("expressibility") or []:
        out.append(f"    {row['surface']:10s} {row['kind']:14s} {row['detail']}")

    auth = report.get("authority") or {}
    out.append(f"\n  (б) ВЛАСТЬ над разрешённой exposure: {auth.get('kind')}")
    out.append(f"    {auth.get('detail')}")
    for sub in auth.get("subjects") or []:
        out.append(f"      · {sub['where']} — {sub['nature']} ({sub['why']})")

    scene = report.get("scene")
    out.append("\n  (в) РАЗЛИЧЕНИЕ «внутри актива» vs «смена актива»:")
    if scene:
        out.append(f"    сцена: тир {scene['tier']}, сеть {scene['chain']}; "
                   f"из `{scene['source']}` ({scene['source_asset']}) → "
                   f"`{scene['same_asset']}` ({scene['same_asset_asset']}) ИЛИ "
                   f"`{scene['other_asset']}` ({scene['other_asset_asset']})")
    elif report.get("scene_unfit_reason"):
        out.append(f"    ⚠️ {report['scene_unfit_reason']}")
    for row in report.get("distinction") or []:
        out.append(f"    {row['surface']:10s} {row['kind']:16s} {row['detail']}")

    dep = report.get("depeg_inputs") or {}
    out.append(f"\n  заказ G949 п. 4 (входы peg/срока выхода у двери книги): "
               f"{dep.get('kind')}")
    out.append(f"    {dep.get('detail')}")

    code = verdict_code(report)
    out.append(f"\n  вердикт: код {code} "
               f"({'находка' if code == 1 else 'НЕ ИЗМЕРЕНО' if code == 2 else 'чисто'})")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=None,
                        help="дерево, о котором задаётся вопрос (умолчание — своё)")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.repo_root) if args.repo_root else None
    if root is not None and not root.exists():
        print(f"НЕ ИЗМЕРЕНО: названное дерево не существует: {root}")
        return 2
    report = census(root)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)
          if args.json else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
