"""anti_churn_census.py — §22 ТЗ «Portfolio CIO»: Anti-churn / hysteresis.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §22 «Anti-churn / hysteresis»::

    Обязательно реализовать защиту от:
    A → B → A → B
    из-за небольших колебаний APY.
    Использовать policy-configurable параметры:
    minimum yield edge · minimum net gain · minimum allocation delta ·
    minimum persistence · minimum confidence · cooldown ·
    maximum daily turnover · rebalance cost budget · decision expiry
    Все значения должны быть config/policy.
    Не hardcode.

Требований здесь ТРИ, и слить их в одно — ответить не на то:

* **(а) параметр существует** — он вообще спрашивается на пути решения;
* **(б) параметр policy-configurable** — повернуть его можно решением
  владельца, а не коммитом. Поле, лежащее в конфиге и ничего не двигающее,
  «настраиваемым» не является, поэтому ось мерится ДИФФЕРЕНЦИАЛЬНО: возмущается
  РОВНО одно значение, и смотрится, двинулся ли вердикт двери;
* **(в) защита достигает цели** — сцена качелей ``A → B → A`` ПОСТРОЕНА, и у
  неё спрошен вердикт. Без сцены «защита работает» было бы верно СЛУЧАЙНО: из
  того, что девять ручек объявлены, не следует, что книга не вернётся туда,
  откуда ушла.

Шкала ВВЕЗЕНА, второй шкалы об одном предмете нет
=================================================
Четыре из девяти величин §22 владелец назвал и в §41 («Auto-execution limits»),
а §41 уже измерен прибором :mod:`spa_core.monitoring.cio_auto_execution_limits`
по шкале ``BINDING / LITERAL / DECLARED_INERT / ABSENT / UNCHECKED``. Перемерить
их здесь своей шкалой значило бы завести ВТОРУЮ шкалу об одном предмете — две
шкалы расходятся молча, и расходящийся дубль хуже пустоты (урок ADR-952/G953
п. 3). Поэтому:

* шкала, классификатор (``_classify``) и сцена цены ВВОЗЯТСЯ из §41;
* четыре пересекающиеся величины **ДЕЛЕГИРУЮТСЯ**: их вердикт БЕРЁТСЯ у §41, а
  не измеряется заново, и факт делегирования ПЕЧАТАЕТСЯ у каждой строки;
* §41 не смог измерить (его положительный контроль не прошёл) ⇒ делегированная
  строка получает ``UNMEASURED`` с названной причиной, а не ``ABSENT``.

🪤 ЛОВУШКА, ради которой прибор мерит ДВЕ поверхности, а не одну
================================================================
**Защита от качелей живёт на ДВУХ дверях, и они отвечают РАЗНОЕ.**

``economics``
    :func:`spa_core.allocator.rebalance_economics.evaluate` — ТЕНЕВАЯ дверь
    цены (ADR-060, Phase 0 SHADOW): «стои́т ли разрешённый ход своих издержек».
    Гистерезис здесь — множитель ``reversal_escalation`` на полосу выигрыша.
``damper``
    :func:`spa_core.governance.churn_damper.decide` — дверь ЖИВОГО пути
    (ADR-168, решение владельца 29.08): цикл считает цель и перекладывает книгу
    под неё. Здесь гистерезис — минимальный срок удержания и недельный бюджет
    оборота.

Замер по ОДНОЙ из них даёт верный ответ на НЕ ТОТ вопрос — ровно та ловушка, из
которой устроен §41 (там потолок T3 связывал у аллокатора и не связывал у
гейта). Поэтому ``SURFACES_22`` РАСШИРЯЕТ ввезённый ``SURFACES_20`` шестой
поверхностью ``damper``; своего словаря поверхностей прибор не заводит.

Что прибор НЕ утверждает
========================
* «Параметра нет» ≠ «понятия нет в дереве». Рядом живут
  :mod:`spa_core.analytics.apy_persistence_scorer` и перепись
  :mod:`spa_core.monitoring.gain_persistence_census`; §22 спрашивает не о
  существовании понятия, а о ручке НА ПУТИ РЕШЕНИЯ, и мерится второе.
* Сцена качелей отвечает о ДВЕРЯХ, а не о живой книге. Исход «книга 12 раз
  вернулась туда, откуда ушла» измерен по журналу ходов (ADR-480), и повторно
  здесь не находится.
* Прибор не судит, достаточен ли порог. Он судит, ЕСТЬ ли порог, ПОВОРАЧИВАЕТСЯ
  ли он владельцем и ОТКАЗЫВАЕТ ли дверь на построенной сцене качелей.

ADVISORY. Живой ``data/`` не читается и не пишется: все сцены — из литералов,
журнал ходов и часы инъектируются. Ни один порог этим модулем не меняется:
изменить защиту от качелей — money-path и решение владельца (ADR-285, предмет
№1), а не строка замера.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей и шкалы. Своих копий здесь нет намеренно: ввозится РОВНО то,
# что получает читателя ниже, — ввоз без читателя есть ложное усиление.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .new_capital_census import SURFACES_20
except Exception as _exc:  # pragma: no cover
    SURFACES_20 = ("allocator", "economics", "gate", "book", "journal")  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§20 SURFACES_20: {}: {}".format(type(_exc).__name__, _exc))

try:
    from spa_core.monitoring.cio_auto_execution_limits import (
        ABSENT, BINDING, DECLARED_INERT, LITERAL, UNCHECKED,
        _classify, _declared_policy_fields, _econ_scene, _econ_verdict,
        _rec, _trigger_params, _SCENE_CAPITAL_USD,
    )
    _SCALE_41 = True
except Exception as _exc:  # pragma: no cover
    ABSENT, BINDING, DECLARED_INERT, LITERAL, UNCHECKED = (
        "ABSENT", "BINDING", "DECLARED_INERT", "LITERAL", "UNCHECKED")
    _SCALE_41 = False
    _VOCAB_ERRORS.append("§41 шкала и сцена цены: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from .cadence_census import load_manifest, recalculation_tact
    _TACT_DOOR = True
except Exception as _exc:  # pragma: no cover
    _TACT_DOOR = False
    _VOCAB_ERRORS.append("§21 такт пересчёта: {}: {}".format(
        type(_exc).__name__, _exc))


#: Поверхности §22. ``SURFACES_20`` несёт пять поверхностей РЕШЕНИЯ; §22
#: спрашивает о защите от качелей, и шестая дверь — ограничитель частоты на
#: ЖИВОМ пути (ADR-168), которого ни §20, ни §41 среди своих поверхностей не
#: называют. Расширение названо, вторая копия перечня не заводится.
SURFACES_22: Tuple[str, ...] = tuple(SURFACES_20) + ("damper",)

#: ДЕВЯТЬ величин §22, дословно и в порядке ТЗ. Число объявлено отдельной
#: константой намеренно: пересказ теряет пункты (замер #1082 — заказ назвал
#: восемь событий §21 из одиннадцати), и расхождение обязано краснеть тестом,
#: а не жить в чьей-то памяти.
OWNER_PARAMS: Tuple[str, ...] = (
    "minimum yield edge",
    "minimum net gain",
    "minimum allocation delta",
    "minimum persistence",
    "minimum confidence",
    "cooldown",
    "maximum daily turnover",
    "rebalance cost budget",
    "decision expiry",
)
OWNER_PARAMS_DECLARED: int = 9

#: Величина §22 → имя той же величины в §41. Вердикт по этим строкам БЕРЁТСЯ у
#: §41 и здесь не перемеривается: одна шкала, одно измерение на предмет.
DELEGATED_TO_41: Dict[str, str] = {
    "minimum net gain": "minimum expected net gain",
    "minimum persistence": "minimum persistence",
    "minimum confidence": "minimum confidence",
    "maximum daily turnover": "max daily turnover",
}

#: Исход сцены качелей. Шкала ОБЪЯВЛЕНА, а не выведена из сравнений: ветка
#: ``else`` по построению не может сказать, какие роды существуют.
SWING_KINDS: Tuple[str, ...] = (
    # дверь ОТКАЗАЛА, и назвала причиной именно защиту от качелей (разворот,
    # срок удержания, бюджет оборота)
    "refused_by_anti_churn",
    # дверь ОТКАЗАЛА, но по причине, к качелям не относящейся (полоса выигрыша,
    # окупаемость, пыль): качели тут остановлены ЭКОНОМИКОЙ, а не защитой
    "refused_by_economics",
    # дверь РАЗРЕШИЛА: книга возвращается в состояние, которое сама покинула
    "permitted",
    # сцена на этой двери НЕДОСТИЖИМА по построению, и причина названа
    "unreachable_by_construction",
    UNMEASURED,
)

#: Во сколько раз возмущается значение в дифференциальном замере. Объявлено
#: числом: возмущение обязано быть заведомо больше любого округления, иначе
#: «не сдвинулось» было бы свойством арифметики, а не ответом о ручке.
PERTURB_FACTOR: float = 10.0

#: Якорь сцены. Литерал — ПРЕДМЕТ (сцена обязана быть воспроизводима на любом
#: хосте), и часы обеих дверей инъектируются от него.
# FROZEN-DATE-OK: injected-clock — момент передаётся входом `now` в
# churn_damper.decide и в отметки журнала сцены; стенных часов сцена не знает.
SCENE_NOW: datetime = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


# ───────────────────────────── сцена качелей ────────────────────────────────

def _books(capital: float) -> Dict[str, Dict[str, float]]:
    """Три книги сцены. ``A`` — исходная, ``B`` и ``C`` — промежуточные.

    Доли ничего не решают: прибор смотрит на ПЕРЕХОД вердикта, а не на числа.
    Третья книга нужна для качелей ЧЕРЕЗ промежуточный шаг (``A → B → C → A``):
    именно их не видит защита, сравнивающая ход с ходом непосредственно
    предыдущим (ADR-480: семь случаев из двенадцати — именно такие).
    """
    return {
        "A": {"aave_v3": 0.40 * capital, "pendle": 0.10 * capital},
        "B": {"aave_v3": 0.30 * capital, "pendle": 0.20 * capital},
        "C": {"aave_v3": 0.30 * capital, "pendle": 0.10 * capital,
              "morpho_blue_base": 0.10 * capital},
    }


def _apy_favouring(winner: str) -> Dict[str, float]:
    """Ставки, при которых выгоден ход ИМЕННО в ``winner``.

    Качели §22 — это колебание ставок туда и обратно, поэтому у каждого шага
    сцены свой победитель. Числа — литералы сцены, не пороги системы.
    """
    base = {"aave_v3": 2.0, "pendle": 2.0, "morpho_blue_base": 2.0}
    base[winner] = 12.0
    return base


def _econ_move(current: Dict[str, float], target: Dict[str, float],
               winner: str, **over: Any) -> Any:
    """Вердикт двери ЦЕНЫ на одном шаге сцены (полный объект решения)."""
    from spa_core.allocator import rebalance_economics as economics
    protos = sorted(set(current) | set(target) | {"morpho_blue_base"})
    scene = dict(
        current_positions=dict(current), target_positions=dict(target),
        apy_pct=_apy_favouring(winner),
        evidenced=set(protos),
        chains={p: "ethereum" for p in protos},
        capital_usd=_scene_capital(),
        days_since_last_act=99.0,
        position_age_days={p: 99.0 for p in protos},
        turnover_last_week_usd=0.0,
        turnover_today_usd=0.0,
        tvl_evidenced=set(protos),
    )
    scene.update(over)
    return economics.evaluate(**scene)


def _scene_capital() -> float:
    return float(_SCENE_CAPITAL_USD) if _SCALE_41 else 100_000.0


def _legs_of(decision: Any) -> Dict[str, float]:
    return {str(l["protocol"]): float(l["delta_usd"]) for l in (decision.legs or [])}


def _trade(days_ago: float, usd: float, now: datetime) -> dict:
    """Запись журнала ходов для сцены ограничителя.

    Ключ отметки — ``ts``: ``churn_damper._recent`` читает его первым, и замер
    29.08 показал, что поиск по ``timestamp`` давал «ноль перекладок за неделю»
    при 22 фактических. Сцена обязана говорить на языке читателя.
    """
    return {"ts": (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta_abs": float(usd)}


def _damper_move(current: Dict[str, float], target: Dict[str, float],
                 trades: List[dict], *, now: Optional[datetime] = None,
                 params: Any = None) -> Any:
    """Вердикт двери ЖИВОГО пути на одном шаге сцены."""
    from spa_core.governance import churn_damper as damper
    return damper.decide(dict(current), dict(target), list(trades),
                         _scene_capital(), now=now or SCENE_NOW, params=params)


# ───────────────────────────── контроль ─────────────────────────────────────

def _control() -> Tuple[bool, str, Dict[str, str]]:
    """Разрешает ли ЗДОРОВАЯ сцена ход на ОБЕИХ поверхностях.

    Без этого условия счёт читать нельзя: «дверь отказала» и «проба сломана»
    выглядят одинаково, а «параметр не спрашивается» произносилось бы и в мире,
    где не работает сама сцена. Это не украшение, а условие ВСЕГО отчёта.
    """
    if _VOCAB_ERRORS:
        return False, "словари/шкала НЕ ВВЕЗЕНЫ: {}".format("; ".join(_VOCAB_ERRORS)), {}
    books = _books(_scene_capital())
    try:
        econ = _econ_move(books["A"], books["B"], "pendle")
        damp = _damper_move(books["A"], books["B"],
                            [_trade(10.0, 1_000.0, SCENE_NOW)])
    except Exception as exc:  # noqa: BLE001
        return False, "здоровая сцена не построена: {}: {}".format(
            type(exc).__name__, exc), {}
    base = {"economics": str(econ.decision), "damper": str(damp.decision)}
    if econ.decision != "ACT":
        return False, ("здоровая сцена не даёт ACT у двери цены ({}: {}) — "
                       "перехода «разрешено → запрещено» показать нечем"
                       .format(econ.decision, "; ".join(econ.reasons))), base
    if not damp.allowed:
        return False, ("здоровая сцена не пропускается ограничителем ({}/{}) — "
                       "перехода показать нечем".format(damp.decision, damp.reason)), base
    return True, "", base


# ───────────────────────── пробы пяти величин §22 ───────────────────────────
#
# Запись пробы — ввезённая форма §41::
#
#     {"surface", "axis", "changed", "detail", ["policy_field", "declared_in"]}
#
# ``axis="quantity"`` — варьировали ВЕЛИЧИНУ ВЛАДЕЛЬЦА;
# ``axis="threshold"`` — варьировали ОБЪЯВЛЕННОЕ ПОЛЕ ПОЛИТИКИ.

def _policy_field(fields: Dict[str, set], name: str) -> Optional[str]:
    """Контракт, в котором объявлено поле ``name``, либо ``None``.

    Принадлежность к политике МЕРИТСЯ (``dataclasses.fields``), а не
    объявляется списком: перечислить поля руками значило бы, что отчёт
    устареет молча при первом же новом поле.
    """
    for contract, names in (fields or {}).items():
        if name in names:
            return contract
    return None


def _probe_minimum_yield_edge(fields: Dict[str, set]) -> List[dict]:
    """Минимальная ПОЛОСА выигрыша: величина — сам выигрыш хода."""
    books = _books(_scene_capital())
    out: List[dict] = []

    # (а) величина: тот же ход при выигрыше, сжатом до пыли.
    tiny = dict(_apy_favouring("pendle"))
    tiny["pendle"] = 2.03           # выигрыш ≈0.003 пп вместо 1.0 пп
    from spa_core.allocator import rebalance_economics as economics
    protos = sorted(set(books["A"]) | set(books["B"]) | {"morpho_blue_base"})
    shrunk = economics.evaluate(
        current_positions=books["A"], target_positions=books["B"], apy_pct=tiny,
        evidenced=set(protos), chains={p: "ethereum" for p in protos},
        capital_usd=_scene_capital(), days_since_last_act=99.0,
        position_age_days={p: 99.0 for p in protos}, turnover_last_week_usd=0.0,
        turnover_today_usd=0.0, tvl_evidenced=set(protos))
    out.append(_rec("economics", "quantity", shrunk.decision != "ACT",
                    "выигрыш хода 1.000 пп → 0.003 пп: {}".format(shrunk.decision)))

    # Та же величина у двери живого пути: у ограничителя ставки нет ВХОДОМ.
    sig = inspect.signature(_damper_decide())
    out.append(_rec("damper", "quantity", False,
                    "ограничитель о ставке не спрашивает: его вход — {}"
                    .format(", ".join(sorted(sig.parameters))),
                    gap="дверь ЖИВОГО пути пропускает ход, не зная выигрыша "
                        "вовсе: полоса выигрыша существует только в ТЕНЕВОЙ "
                        "двери цены (ADR-060 Phase 0 SHADOW)"))

    # (б) ручка: возмущаем РОВНО min_gain_pp.
    contract = _policy_field(fields, "min_gain_pp")
    turned = _econ_move(books["A"], books["B"], "pendle",
                        params=_trigger_params(min_gain_pp=0.50 * PERTURB_FACTOR))
    out.append(_rec("economics", "threshold", turned.decision != "ACT",
                    "min_gain_pp 0.50 → {:.2f} пп: {}".format(
                        0.50 * PERTURB_FACTOR, turned.decision),
                    policy_field="min_gain_pp" if contract else None,
                    declared_in=contract))
    return out


def _damper_decide() -> Any:
    from spa_core.governance.churn_damper import decide
    return decide


def _probe_minimum_allocation_delta(fields: Dict[str, set]) -> List[dict]:
    """Минимальная ДЕЛЬТА раскладки: величина — размер самого хода."""
    cap = _scene_capital()
    books = _books(cap)
    out: List[dict] = []

    dust_target = {"aave_v3": 0.3999 * cap, "pendle": 0.1001 * cap}
    dust = _econ_move(books["A"], dust_target, "pendle")
    out.append(_rec("economics", "quantity", dust.decision != "ACT",
                    "ход 10.0 % капитала → 0.01 %: {} ({})".format(
                        dust.decision, "; ".join(dust.reasons[:1]))))

    dust_damp = _damper_move(books["A"], dust_target,
                             [_trade(10.0, 1_000.0, SCENE_NOW)])
    out.append(_rec("damper", "quantity", not dust_damp.allowed,
                    "тот же пыльный ход у ограничителя: {}/{}".format(
                        dust_damp.decision, dust_damp.reason),
                    gap="ограничитель не знает ПОЛОСЫ ПЫЛИ: ход в 0.01 % "
                        "капитала проходит у него ровно как ход в 10 %, и "
                        "платит полный газ"))

    contract = _policy_field(fields, "min_leg_frac")
    turned = _econ_move(books["A"], books["B"], "pendle",
                        params=_trigger_params(min_leg_frac=0.005 * PERTURB_FACTOR * 4))
    out.append(_rec("economics", "threshold", turned.decision != "ACT",
                    "min_leg_frac 0.005 → {:.3f}: {} ({})".format(
                        0.005 * PERTURB_FACTOR * 4, turned.decision,
                        "; ".join(turned.reasons[:1])),
                    policy_field="min_leg_frac" if contract else None,
                    declared_in=contract))
    return out


def _probe_cooldown(fields: Dict[str, set]) -> List[dict]:
    """Пауза между ходами — единственная величина §22 на ОБЕИХ дверях."""
    cap = _scene_capital()
    books = _books(cap)
    out: List[dict] = []

    hot = _econ_move(books["A"], books["B"], "pendle", days_since_last_act=1.0)
    out.append(_rec("economics", "quantity", hot.decision != "ACT",
                    "давность последнего хода 99 дн. → 1 дн.: {} ({})".format(
                        hot.decision, "; ".join(hot.reasons[:1]))))

    hot_damp = _damper_move(books["A"], books["B"],
                            [_trade(1.0, 1_000.0, SCENE_NOW)])
    out.append(_rec("damper", "quantity", not hot_damp.allowed,
                    "последняя перекладка 10 дн. → 1 дн.: {}/{} ({})".format(
                        hot_damp.decision, hot_damp.reason, hot_damp.detail)))

    econ_contract = _policy_field(fields, "act_cooldown_days")
    econ_turned = _econ_move(books["A"], books["B"], "pendle",
                             days_since_last_act=1.0,
                             params=_trigger_params(act_cooldown_days=1))
    out.append(_rec("economics", "threshold", econ_turned.decision == "ACT",
                    "act_cooldown_days 3 → 1 при давности 1 дн.: {}".format(
                        econ_turned.decision),
                    policy_field="act_cooldown_days" if econ_contract else None,
                    declared_in=econ_contract))

    damp_contract = _policy_field(fields, "min_hold_days")
    damp_turned = _damper_move(books["A"], books["B"],
                               [_trade(1.0, 1_000.0, SCENE_NOW)],
                               params=_trigger_params(min_hold_days=0))
    out.append(_rec("damper", "threshold", damp_turned.allowed,
                    "min_hold_days 3 → 0 при давности 1 дн.: {}/{}".format(
                        damp_turned.decision, damp_turned.reason),
                    policy_field="min_hold_days" if damp_contract else None,
                    declared_in=damp_contract))
    return out


def _probe_rebalance_cost_budget(fields: Dict[str, set]) -> List[dict]:
    """Бюджет ИЗДЕРЖЕК перекладки — и чем он у нас НЕ является.

    Величина владельца здесь КУМУЛЯТИВНА: «сколько издержек уже потрачено за
    период». Рядом есть бюджет ОБОРОТА (``max_turnover_per_week``), и принять
    его за ответ — та же подмена, что считать оборот издержками: издержки
    оборачиваемой сумме НЕ пропорциональны (газ начисляется на НОГУ, мост — на
    смену сети), поэтому один и тот же оборот стои́т разных денег.
    """
    cap = _scene_capital()
    books = _books(cap)
    out: List[dict] = []

    # Величина измеряется ВХОДОМ: кумулятивных издержек нет ни у одной двери.
    from spa_core.allocator import rebalance_economics as economics
    econ_inputs = sorted(inspect.signature(economics.evaluate).parameters)
    damp_inputs = sorted(inspect.signature(_damper_decide()).parameters)
    cost_inputs = [n for n in econ_inputs + damp_inputs if "cost" in n or "budget" in n]
    out.append(_rec("economics", "quantity", False,
                    "входов про уже потраченные издержки у двери цены нет: {}"
                    .format(", ".join(econ_inputs)),
                    gap="ЦЕНА ОДНОГО хода у двери цены спрашивается и связывает "
                        "(через max_payback_days), но «сколько уже потрачено за "
                        "период» не спрашивается ничем: бюджета как НАКОПЛЕНИЯ "
                        "нет"))
    out.append(_rec("damper", "quantity", False,
                    "входов про издержки у ограничителя нет: {}".format(
                        ", ".join(damp_inputs)),
                    gap="недельный бюджет ограничителя — про ОБОРОТ, а не про "
                        "издержки: газ начисляется на ногу, мост — на смену "
                        "сети, и один и тот же оборот стои́т разных денег"))

    # Та же сцена ТРЕМЯ ногами вместо двух: оборот тот же, газ выше. Это
    # наблюдение о ЦЕНЕ ОДНОГО хода, и счётной записью оно быть НЕ ВПРАВЕ:
    # величина владельца здесь — НАКОПЛЕНИЕ за период, и зачесть за неё цену
    # одного хода значило бы объявить бюджет существующим. Поэтому наблюдение
    # уходит в `gap` — туда, где его нельзя прочесть как ответ.
    spread_target = {"aave_v3": 0.30 * cap, "pendle": 0.15 * cap,
                     "morpho_blue_base": 0.05 * cap}
    plain = _econ_move(books["A"], books["B"], "pendle")
    spread = _econ_move(books["A"], spread_target, "pendle")
    out.append(_rec("economics", "quantity", False,
                    "накопленных издержек за период не спрашивает ни одна "
                    "дверь — величина §22 здесь КУМУЛЯТИВНА",
                    gap="цена ОДНОГО хода дверью цены считается: тот же оборот "
                        "тремя ногами вместо двух даёт издержки ${:.2f} → "
                        "${:.2f} при вердикте {} → {} — то есть меняется "
                        "ОКУПАЕМОСТЬ, а бюджета издержек как накопления нет"
                        .format(plain.cost_usd, spread.cost_usd,
                                plain.decision, spread.decision)))

    out.append(_rec("economics", "threshold", False,
                    "поля политики, чьё имя называет издержки или бюджет "
                    "издержек: {}".format(cost_inputs or "нет ни одного")))
    return out


def _probe_decision_expiry(fields: Dict[str, set]) -> List[dict]:
    """Срок годности РЕШЕНИЯ: величина — возраст самого вердикта.

    Три состояния здесь легко слить в одно, и слить нельзя: «решение просрочено
    и отвергнуто» · «решение просрочено и исполнено» · «решение не доживает до
    просрочки, потому что пересчитывается каждый такт». Третье — свойство
    ТАКТА (§21), а не объявленный срок годности, и прибор говорит это вслух,
    спрашивая такт у ЕДИНСТВЕННОЙ двери §21, а не перепечатывая число.
    """
    cap = _scene_capital()
    books = _books(cap)
    out: List[dict] = []

    from spa_core.allocator import rebalance_economics as economics
    econ_inputs = sorted(inspect.signature(economics.evaluate).parameters)
    clock_inputs = [n for n in econ_inputs if "now" in n or "age" in n or "at" == n]
    out.append(_rec("economics", "quantity", False,
                    "часов у двери цены нет ВХОДОМ (входы: {}) ⇒ вердикт не "
                    "может зависеть от возраста решения по построению; про "
                    "время она принимает {}".format(
                        ", ".join(econ_inputs), clock_inputs or "ничего")))

    # У ограничителя часы ЕСТЬ — но они мерят возраст ХОДА, не решения.
    shifted_now = SCENE_NOW + timedelta(days=365)
    same_interval = _damper_move(books["A"], books["B"],
                                 [_trade(10.0, 1_000.0, shifted_now)],
                                 now=shifted_now)
    at_anchor = _damper_move(books["A"], books["B"],
                             [_trade(10.0, 1_000.0, SCENE_NOW)])
    out.append(_rec("damper", "quantity",
                    same_interval.decision != at_anchor.decision,
                    "сцена сдвинута на год ВМЕСТЕ с журналом: {}/{} против "
                    "{}/{} — часы мерят ИНТЕРВАЛ между ходами, а не возраст "
                    "решения".format(same_interval.decision, same_interval.reason,
                                     at_anchor.decision, at_anchor.reason)))

    expiry_fields = sorted(n for names in (fields or {}).values() for n in names
                           if "expiry" in n or "expire" in n or "ttl" in n)
    out.append(_rec("economics", "threshold", False,
                    "поля политики, чьё имя называет срок годности решения: {}"
                    .format(expiry_fields or "нет ни одного")))
    return out


#: Пять величин §22, которые §41 не измеряет, → их проба.
OWN_PROBES: Dict[str, Any] = {
    "minimum yield edge": _probe_minimum_yield_edge,
    "minimum allocation delta": _probe_minimum_allocation_delta,
    "cooldown": _probe_cooldown,
    "rebalance cost budget": _probe_rebalance_cost_budget,
    "decision expiry": _probe_decision_expiry,
}


# ─────────────────────── ось (в): достижимость качелей ──────────────────────

def _anti_churn_reason(reasons: Sequence[str], damper_reason: str = "") -> bool:
    """Отказ назван ЗАЩИТОЙ ОТ КАЧЕЛЕЙ, а не экономикой хода.

    Разделение существенно: «ход не окупается» и «ход разворачивает недавний
    ход» — разные утверждения, и зачесть первое за защиту от качелей значило бы
    объявить защиту работающей в мире, где её нет вовсе.
    """
    churn_marks = ("reversal_of_recent_move", "cooldown_active",
                   "positions_below_min_hold", "week_turnover_over_budget",
                   "day_turnover_over_budget", "move_turnover_over_budget")
    if damper_reason in ("min_hold", "weekly_turnover_budget"):
        return True
    return any(any(m in str(r) for m in churn_marks) for r in (reasons or []))


def _swing_on_economics() -> Dict[str, Any]:
    """Качели ``A → B → A`` и ``A → B → C → A`` у двери ЦЕНЫ.

    Каждый шаг получает ставки, при которых он выгоден: качели §22 — это
    колебание ставок туда и обратно, и сцена обязана его воспроизводить, иначе
    отказ на третьем шаге был бы отказом «выигрыша нет», то есть верным
    СЛУЧАЙНО.
    """
    books = _books(_scene_capital())
    A, B, C = books["A"], books["B"], books["C"]

    step1 = _econ_move(A, B, "pendle")
    legs1 = _legs_of(step1)
    prev_gain = 0.0

    direct = _econ_move(B, A, "aave_v3", last_move_legs=legs1,
                        days_since_last_move=1.0)
    step2 = _econ_move(B, C, "morpho_blue_base", last_move_legs=legs1,
                       days_since_last_move=1.0)
    legs2 = _legs_of(step2)
    via_c = _econ_move(C, A, "aave_v3", last_move_legs=legs2,
                       days_since_last_move=1.0)

    def kind(dec: Any) -> str:
        if dec.decision == "ACT":
            return "permitted"
        return ("refused_by_anti_churn" if _anti_churn_reason(dec.reasons)
                else "refused_by_economics")

    # КРАЙ полосы: ставка победителя снижается, пока прямой разворот не
    # перевернётся в отказ. Без этого числа «permitted» читалось бы как «защиты
    # нет вовсе» — а защита ЕСТЬ, она ПОЛОСА, и ровно это надо сказать: ниже
    # края качели отказываются, выше — проходят, и вопрос о книге не задаётся
    # ни там, ни там. Шаг перебора объявлен, и исход «край не найден» — третий
    # (`None`), а не молчаливое число.
    edge: Optional[Dict[str, float]] = None
    probe_rate = 12.0
    while probe_rate > 2.0 + 1e-9:
        trial = _econ_move(B, A, "aave_v3", last_move_legs=legs1,
                           days_since_last_move=1.0,
                           apy_pct={**_apy_favouring("aave_v3"),
                                    "aave_v3": probe_rate})
        if trial.decision != "ACT":
            edge = {"last_permitted_gain_pp": round(prev_gain, 6),
                    "first_refused_gain_pp": trial.gain_pp,
                    "required_gain_pp": trial.required_gain_pp}
            break
        prev_gain = trial.gain_pp
        probe_rate -= 0.5

    return {
        "surface": "economics",
        "step1_reaches_B": step1.decision,
        "two_step": {
            "kind": kind(direct), "decision": direct.decision,
            "required_gain_pp": direct.required_gain_pp,
            "gain_pp": direct.gain_pp, "reasons": list(direct.reasons),
        },
        "three_step": {
            "kind": kind(via_c), "decision": via_c.decision,
            "required_gain_pp": via_c.required_gain_pp,
            "gain_pp": via_c.gain_pp, "reasons": list(via_c.reasons),
            "intermediate_step": step2.decision,
        },
        "band_edge": edge,
        "asks_about_the_book": False,
        "why": ("дверь цены сравнивает ноги нового хода с ногами хода "
                "НЕПОСРЕДСТВЕННО ПРЕДЫДУЩЕГО (last_move_legs) и повышает "
                "полосу в reversal_escalation раз; вопроса «не возвращаемся ли "
                "мы в книгу, которую сами покинули» у неё нет ни одного — "
                "владелец выбрал ровно его (вариант 1, ADR-836, 27.10)"),
    }


def _swing_on_damper() -> Dict[str, Any]:
    """Те же качели у двери ЖИВОГО пути — и за сколько дней они достижимы.

    Срок НЕ объявляется, а ИЩЕТСЯ: сцена спрашивается при давности 1, 2, 3 …
    дней, и берётся первый день, на котором ограничитель пропускает ход. Тот
    же вопрос про бюджет оборота: полный цикл ``A → B → A → B`` — это четыре
    ноги, и бюджет недели может кончиться раньше, чем срок удержания.
    """
    books = _books(_scene_capital())
    A, B = books["A"], books["B"]
    per_move = abs(B["aave_v3"] - A["aave_v3"])

    first_allowed: Optional[float] = None
    probed: List[dict] = []
    for days in (0.5, 1.0, 2.0, 3.0, 4.0, 7.0, 14.0):
        v = _damper_move(B, A, [_trade(days, per_move, SCENE_NOW)])
        probed.append({"days_since_last_move": days, "decision": v.decision,
                       "reason": v.reason})
        if v.allowed and first_allowed is None:
            first_allowed = days

    # Четыре ноги подряд внутри одной недели: бюджет оборота против срока.
    four = _damper_move(B, A, [_trade(3.0, per_move, SCENE_NOW),
                               _trade(5.0, per_move, SCENE_NOW),
                               _trade(6.5, per_move, SCENE_NOW)])
    return {
        "surface": "damper",
        "first_day_a_return_is_allowed": first_allowed,
        "probed": probed,
        "full_cycle_within_a_week": {
            "kind": ("refused_by_anti_churn" if _anti_churn_reason(
                        [], four.reason) else
                     "permitted" if four.allowed else "refused_by_economics"),
            "decision": four.decision, "reason": four.reason,
            "detail": four.detail,
            "week_turnover_usd": four.week_turnover_usd,
            "week_budget_usd": four.week_budget_usd,
        },
        "asks_about_the_book": False,
        "why": ("ограничитель спрашивает ВРЕМЯ и ОБОРОТ, а не состав книги: "
                "возврат в покинутую книгу и ход в новую книгу он не "
                "различает вовсе"),
    }


def _tact_counterpoint(root: Path) -> Dict[str, Any]:
    """Достижима ли сцена качелей внутри суток — спрошено у двери §21.

    Такт пересчёта МЕРИТСЯ (``cadence_census.recalculation_tact``), а не
    перепечатывается: число в тексте правила вместо прибора — ровно тот дефект,
    против которого написан §22-замер. Не измерен ⇒ третий исход, а не «сутки».
    """
    if not _TACT_DOOR:
        return {"kind": UNMEASURED, "why": "дверь §21 не ввезена", "tact_s": None}
    manifest, err = load_manifest(root)
    if manifest is None:
        return {"kind": UNMEASURED,
                "why": "объявление не прочитано: {}".format(err), "tact_s": None}
    tact = recalculation_tact(manifest)
    tact_s = tact.get("tact_s")
    if tact_s is None:
        return {"kind": UNMEASURED, "why": tact.get("why") or "такт не измерен",
                "tact_s": None, "recalc_label": tact.get("label")}
    moves_per_day = 86_400.0 / float(tact_s)
    return {
        "kind": ("unreachable_by_construction" if moves_per_day < 2.0
                 else "permitted"),
        "tact_s": float(tact_s),
        "recalc_label": tact.get("label"),
        "moves_per_day": round(moves_per_day, 4),
        "why": ("пересчёт целевой раскладки идёт раз в {:.0f} с ({}), то есть "
                "решений в сутки {:.2f} — качели A → B → A → B ВНУТРИ суток "
                "недостижимы по построению, и защита тут не при чём; за пределы "
                "суток их выпускает срок удержания, а не вопрос о книге"
                .format(float(tact_s), tact.get("label"), moves_per_day)),
    }


# ───────────────────────────── сборка отчёта ────────────────────────────────

def _delegated_verdicts() -> Tuple[Dict[str, dict], str]:
    """Вердикты §41 по четырём пересекающимся величинам — БЕЗ перемера."""
    if not _SCALE_41:
        return {}, "шкала §41 не ввезена"
    try:
        from spa_core.monitoring import cio_auto_execution_limits as limits
        doc = limits.run(write=False)
    except Exception as exc:  # noqa: BLE001
        return {}, "§41 не измерен: {}: {}".format(type(exc).__name__, exc)
    # Ключом делегирования взято СЛОВО ВЛАДЕЛЬЦА (`owner_wording`), а не наш
    # внутренний слаг: тождество величины §22 с величиной §41 есть тождество
    # ИМЕНИ, которое дал владелец, и переименуй §41 свой слаг — делегирование
    # обязано сказать «НЕ ИЗМЕРЕНО», а не промолчать на совпавшей строке.
    by_name = {str(r.get("owner_wording")): r for r in (doc.get("limits") or [])}
    if not doc.get("control", {}).get("passed"):
        return by_name, "положительный контроль §41 не прошёл: {}".format(
            doc.get("control", {}).get("reason") or "причина не названа")
    return by_name, ""


def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Замер §22. Живой ``data/`` не читается и не пишется."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    fields = _declared_policy_fields() if _SCALE_41 else {}
    control_ok, control_why, baseline = _control()
    delegated, delegation_why = _delegated_verdicts()

    params: List[dict] = []
    for name in OWNER_PARAMS:
        entry: Dict[str, Any] = {"param": name, "records": []}
        if name in DELEGATED_TO_41:
            src = DELEGATED_TO_41[name]
            row = delegated.get(src)
            entry["delegated_to"] = "§41 «{}»".format(src)
            if row is None or delegation_why:
                entry.update({
                    "outcome": UNMEASURED,
                    "detail": delegation_why or
                              "§41 не содержит строки «{}»".format(src),
                })
            else:
                entry.update({"outcome": row.get("outcome"),
                              "detail": row.get("detail") or "",
                              "delegated_key": row.get("limit"),
                              "surfaces_binding": row.get("surfaces_binding") or []})
            params.append(entry)
            continue
        if not control_ok:
            entry.update({"outcome": UNMEASURED, "detail": control_why})
            params.append(entry)
            continue
        try:
            records = OWN_PROBES[name](fields)
        except Exception as exc:  # noqa: BLE001 — упавшая проба это НЕ ИЗМЕРЕНО
            entry.update({"outcome": UNMEASURED,
                          "detail": "{}: {}".format(type(exc).__name__, exc)})
            params.append(entry)
            continue
        outcome, detail = _classify(records)
        entry.update({
            "outcome": outcome, "detail": detail, "records": records,
            "surfaces_binding": sorted({r["surface"] for r in records
                                        if r["axis"] == "quantity" and r["changed"]}),
            "gaps": [{"surface": r["surface"], "gap": r["gap"]}
                     for r in records if r.get("gap")],
        })
        params.append(entry)

    reach: Dict[str, Any] = {"tact": _tact_counterpoint(root)}
    if control_ok:
        try:
            reach["economics"] = _swing_on_economics()
            reach["damper"] = _swing_on_damper()
        except Exception as exc:  # noqa: BLE001
            reach["economics"] = {"kind": UNMEASURED,
                                  "why": "{}: {}".format(type(exc).__name__, exc)}
    else:
        reach["economics"] = {"kind": UNMEASURED, "why": control_why}
        reach["damper"] = {"kind": UNMEASURED, "why": control_why}

    tally = {o: sum(1 for p in params if p["outcome"] == o)
             for o in (BINDING, LITERAL, DECLARED_INERT, ABSENT, UNMEASURED)}
    return {
        "section": "§22 Anti-churn / hysteresis",
        "owner_criterion": (
            "§22 ТЗ «Portfolio CIO»: защита от A → B → A → B из-за небольших "
            "колебаний APY; девять величин (minimum yield edge · minimum net "
            "gain · minimum allocation delta · minimum persistence · minimum "
            "confidence · cooldown · maximum daily turnover · rebalance cost "
            "budget · decision expiry) ОБЯЗАНЫ быть config/policy, не hardcode"),
        "params_declared": OWNER_PARAMS_DECLARED,
        "surfaces": list(SURFACES_22),
        "scale_imported_from": "spa_core/monitoring/cio_auto_execution_limits.py (§41)",
        "control": {"passed": control_ok, "reason": control_why,
                    "healthy_baseline": baseline},
        "delegation": {"rows": sorted(DELEGATED_TO_41),
                       "unmeasured_reason": delegation_why},
        "declared_policy_fields": {k: sorted(v) for k, v in (fields or {}).items()},
        "tally": tally,
        "params": params,
        "reachability": reach,
        "vocab_errors": list(_VOCAB_ERRORS),
        "advisory": ("прибор только ЧИТАЕТ: ни один порог не изменён, ни одна "
                     "недостающая величина не построена — защита от качелей "
                     "это money-path и решение владельца (ADR-285, предмет №1)"),
    }


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §22 исполняется · 1 — находка названа · 2 — НЕ ИЗМЕРЕНО."""
    if report.get("vocab_errors") or not report.get("control", {}).get("passed"):
        return 2
    tally = report.get("tally") or {}
    if tally.get(UNMEASURED):
        return 2
    reach = report.get("reachability") or {}
    if any((reach.get(k) or {}).get("kind") == UNMEASURED
           for k in ("economics", "damper", "tact")):
        return 2
    if tally.get(ABSENT) or tally.get(LITERAL) or tally.get(DECLARED_INERT):
        return 1
    if (reach.get("economics") or {}).get("two_step", {}).get("kind") == "permitted":
        return 1
    if (reach.get("economics") or {}).get("three_step", {}).get("kind") == "permitted":
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    L: List[str] = ["§22 ТЗ «Portfolio CIO»: Anti-churn / hysteresis",
                    "=" * 72]
    ctl = report["control"]
    L.append("контроль: {} {}".format(
        "ПРОШЁЛ" if ctl["passed"] else "НЕ ПРОШЁЛ", ctl["reason"]))
    L.append("  здоровая сцена: {}".format(json.dumps(
        ctl["healthy_baseline"], ensure_ascii=False)))
    L.append("шкала ввезена из: {}".format(report["scale_imported_from"]))
    L.append("поверхности ({}): {}".format(len(report["surfaces"]),
                                           ", ".join(report["surfaces"])))
    L.append("")
    L.append("(а)+(б) ДЕВЯТЬ ВЕЛИЧИН ВЛАДЕЛЬЦА — где живёт порог и поворачивается ли он:")
    for p in report["params"]:
        tag = p["outcome"]
        where = ", ".join(p.get("surfaces_binding") or []) or "—"
        L.append("  {:<16} «{}» [{}]".format(tag, p["param"], where))
        if p.get("delegated_to"):
            L.append("      ← ДЕЛЕГИРОВАНО {} (не перемеряется: одна шкала, "
                     "одно измерение)".format(p["delegated_to"]))
        if p.get("detail"):
            L.append("      {}".format(p["detail"]))
        for g in p.get("gaps") or []:
            L.append("      ⚠ [{}] {}".format(g["surface"], g["gap"]))
    t = report["tally"]
    L.append("")
    L.append("  ИТОГ по девяти: policy-configurable и связывает {} · порог в коде "
             "{} · объявлено и не спрашивается {} · отсутствует {} · НЕ ИЗМЕРЕНО {}"
             .format(t.get(BINDING, 0), t.get(LITERAL, 0),
                     t.get(DECLARED_INERT, 0), t.get(ABSENT, 0),
                     t.get(UNMEASURED, 0)))
    L.append("")
    L.append("(в) ДОСТИЖИМОСТЬ КАЧЕЛЕЙ — сцена ПОСТРОЕНА, не предположена:")
    e = report["reachability"].get("economics") or {}
    if e.get("kind") == UNMEASURED:
        L.append("  economics: НЕ ИЗМЕРЕНО — {}".format(e.get("why")))
    else:
        two, three = e["two_step"], e["three_step"]
        L.append("  economics · A → B → A (прямой разворот): {} ({}; полоса "
                 "{:.3f} пп против выигрыша {:.3f} пп)".format(
                     two["kind"], two["decision"], two["required_gain_pp"],
                     two["gain_pp"]))
        L.append("  economics · A → B → C → A (качели ЧЕРЕЗ шаг): {} ({}; полоса "
                 "{:.3f} пп против выигрыша {:.3f} пп)".format(
                     three["kind"], three["decision"], three["required_gain_pp"],
                     three["gain_pp"]))
        be = e.get("band_edge")
        L.append("  economics · КРАЙ полосы (защита ЕСТЬ, и она полоса): {}"
                 .format("последний пропущенный выигрыш {:.3f} пп, первый "
                         "отказанный {:.3f} пп при полосе {:.3f} пп".format(
                             be["last_permitted_gain_pp"],
                             be["first_refused_gain_pp"],
                             be["required_gain_pp"])
                         if be else "НЕ НАЙДЕН перебором — третий исход, не число"))
        L.append("      {}".format(e["why"]))
    d = report["reachability"].get("damper") or {}
    if d.get("kind") == UNMEASURED:
        L.append("  damper: НЕ ИЗМЕРЕНО — {}".format(d.get("why")))
    else:
        L.append("  damper · первый день, когда возврат пропускают: {} дн.".format(
            d["first_day_a_return_is_allowed"]))
        fc = d["full_cycle_within_a_week"]
        L.append("  damper · полный цикл A → B → A → B внутри недели: {} ({}/{}; "
                 "оборот ${:,.0f} при бюджете ${:,.0f})".format(
                     fc["kind"], fc["decision"], fc["reason"],
                     fc["week_turnover_usd"], fc["week_budget_usd"] or 0.0))
        L.append("      {}".format(d["why"]))
    tc = report["reachability"].get("tact") or {}
    L.append("  такт пересчёта (спрошен у §21): {} — {}".format(
        tc.get("kind"), tc.get("why")))
    L.append("")
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for x in report["vocab_errors"]:
            L.append("    {}".format(x))
    code = verdict_code(report)
    L.append({0: "✅ §22 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§22 Anti-churn").splitlines()[0])
    ap.add_argument("--root", type=Path, default=None,
                    help="корень дерева (умолчание — дерево этого файла)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = census(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
