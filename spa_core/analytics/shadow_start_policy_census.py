"""shadow_start_policy_census.py — §23 ТЗ «Portfolio CIO»: Starting policy for Shadow Mode.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §23 «Starting policy for Shadow Mode»::

    Для shadow testing можно использовать стартовые значения, но не считать их
    production policy.
    Пример:
    minimum 3 consecutive confirmations
    expected persistence >= 3 × break-even period
    expected net economic benefit >= 3 × switching cost
    target allocation difference >= 3–5 percentage points
    cooldown ~6h
    maximum daily turnover 20–25%
    После simulation/backtest значения должны быть откалиброваны.

🪤 ВЕЛИЧИН ЗДЕСЬ ШЕСТЬ, А ЗАКАЗ НАЗВАЛ ЧЕТЫРЕ
=============================================
Заказ G954 п. 1 перечислил ``minimum 3 consecutive confirmations`` ·
``expected persistence`` · ``expected net economic benefit`` ·
``target allocation difference`` — и потерял ``cooldown ~6h`` и
``maximum daily turnover 20–25%``, которые владелец назвал ТЕМ ЖЕ списком.
Это ровно тот дефект, против которого §22 объявил ``OWNER_PARAMS_DECLARED``
отдельной константой (замер #1082: заказ назвал восемь событий §21 из
одиннадцати). Поэтому число объявлено константой
:data:`OWNER_START_VALUES_DECLARED` и краснеет тестом, а не живёт в чьей-то
памяти; расхождение заказа с ТЗ названо здесь, а не исправлено молча.

Требований в §23 ДВА, и слить их в одно — ответить не на то
===========================================================
* **существование.** Величины может не быть в системе ВООБЩЕ — тогда
  «стартовой её не считают production policy» верно ПУСТО: объявлять стартовым
  нечего. Этот вопрос §22 и §41 уже измерили, и здесь он **ДЕЛЕГИРУЕТСЯ**;
* **род объявления.** Величина, которая есть, обязана быть помечена СТАРТОВОЙ
  (shadow), а не производственной политикой. Это ДРУГОЙ предикат, не шкала
  «связывает ли», и своя шкала у него законна: вторая шкала об ОДНОМ предмете
  запрещена, а это ВТОРОЙ предмет.

Шкала «связывает ли» ВВЕЗЕНА, второй шкалы об одном предмете нет
================================================================
Пять из шести величин §23 владелец назвал и в §22 («Anti-churn / hysteresis»),
а §22 уже измерен (ADR-965) по ввезённой из §41 шкале
``BINDING / LITERAL / DECLARED_INERT / ABSENT / UNCHECKED``. Поэтому:

* шкала, сцены и помощники ВВОЗЯТСЯ из §22 и §41; своих копий здесь нет;
* пять величин по оси СУЩЕСТВОВАНИЯ **ДЕЛЕГИРУЮТСЯ** §22, ключ делегирования —
  СЛОВО ВЛАДЕЛЬЦА (``param``), а не наш слаг: переименуй §22 свою строку —
  делегирование обязано дать ``UNMEASURED``, а не промолчать;
* §22 не смог измерить ⇒ делегированная строка получает ``UNMEASURED`` с
  названной причиной, а не ``ABSENT``.

🪤 ШЕСТАЯ ВЕЛИЧИНА ДЕЛЕГИРОВАНА БЫТЬ НЕ МОЖЕТ, И ЭТО НЕ МЕЛОЧЬ
==============================================================
``target allocation difference >= 3–5 percentage points`` выглядит как §22
``minimum allocation delta``, но это ДРУГАЯ величина, и подмена дала бы верный
ответ на не тот вопрос:

``min_leg_frac`` (§22, BINDING)
    полоса ПЫЛИ **у ОДНОЙ НОГИ**: нога меньше 0.5 % капитала пропускается.
§23 ``target allocation difference``
    разница РАСКЛАДКИ в целом — ``current`` против ``target``, в процентных
    пунктах, независимо от того, на сколько ног она рассыпана.

Различие ИЗМЕРЕНО, а не объявлено: агрегат ~10 пп, рассыпанный на двадцать ног
по 0.499 % капитала, дверь цены отклоняет — но причиной называет
``proposal_has_unexecuted_legs``, то есть ПЫЛЬ у ног, а вовсе не малость
агрегата, которого там 10 пп. Поэтому шестая величина мерится СВОЕЙ пробой, а
отказ от делегирования ПЕЧАТАЕТСЯ (:data:`DELEGATION_REFUSED`).

Что прибор НЕ утверждает
========================
* **Он не судит, достаточен ли порог** и не сравнивает строгость. Живое
  значение, оказавшееся СТРОЖЕ стартового, — не находка и не успех: §23 про
  РОД числа, а не про его величину.
* **Он не мерит КАЛИБРОВКУ.** Последняя строка §23 («после simulation/backtest
  значения должны быть откалиброваны») спрашивает об ИСТОРИИ числа — кто его
  откалибровал и по какому прогону, — а этот прибор читает СЕГОДНЯШНЕЕ дерево.
  Выдать «поле существует» за «число откалибровано» значило бы ответить на свой
  вопрос вместо нужного. Предикат назван и отдан следующему заказу; нулём его
  отсутствие здесь не считается.
* **«Величины нет» ≠ «понятия нет в дереве».** §23 спрашивает о СТАРТОВОМ
  ЗНАЧЕНИИ на пути решения, и мерится оно.

ADVISORY. Живой ``data/`` не читается и не пишется: все сцены — из литералов,
журнал ходов и часы инъектируются. Ни один порог этим модулем не меняется:
развести стартовую политику с production — money-path и решение владельца
(ADR-285, предмет №1), а не строка замера.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей, шкалы и СЦЕН. Своих копий здесь нет намеренно: ввозится РОВНО
# то, что получает читателя ниже, — ввоз без читателя есть ложное усиление.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .anti_churn_census import (
        OWNER_PARAMS, SCENE_NOW, SURFACES_22,
        _books, _control, _damper_move, _econ_move, _scene_capital, _trade,
        census as census_22,
    )
    _DOOR_22 = True
except Exception as _exc:  # pragma: no cover
    _DOOR_22 = False
    OWNER_PARAMS = ()  # type: ignore[assignment]
    SURFACES_22 = ()  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§22 словарь, шкала и сцены: {}: {}".format(
        type(_exc).__name__, _exc))

try:
    from spa_core.monitoring.cio_auto_execution_limits import (
        ABSENT, BINDING, DECLARED_INERT, LITERAL, UNCHECKED,
        _declared_policy_fields, _rec, _trigger_params,
    )
    _SCALE_41 = True
except Exception as _exc:  # pragma: no cover
    ABSENT, BINDING, DECLARED_INERT, LITERAL, UNCHECKED = (
        "ABSENT", "BINDING", "DECLARED_INERT", "LITERAL", "UNCHECKED")
    _SCALE_41 = False
    _VOCAB_ERRORS.append("§41 шкала и объявленные поля политики: {}: {}".format(
        type(_exc).__name__, _exc))


#: ШЕСТЬ стартовых величин §23, дословно и в порядке ТЗ.
SHADOW_START_VALUES: Tuple[str, ...] = (
    "minimum consecutive confirmations",
    "expected persistence",
    "expected net economic benefit",
    "target allocation difference",
    "cooldown",
    "maximum daily turnover",
)

#: Число объявлено ОТДЕЛЬНОЙ константой намеренно — см. ловушку в docstring:
#: заказ G954 п. 1 назвал ЧЕТЫРЕ из этих шести.
OWNER_START_VALUES_DECLARED: int = 6

#: Число величин, названных заказом. Хранится рядом, чтобы расхождение
#: «ТЗ ↔ заказ» было ИЗМЕРЕНО отчётом, а не замечено глазами один раз.
ORDER_G954_NAMED: int = 4

#: Стартовое значение владельца дословно — оно и есть предмет сравнения.
OWNER_START_WORDING: Dict[str, str] = {
    "minimum consecutive confirmations": "minimum 3 consecutive confirmations",
    "expected persistence": "expected persistence >= 3 × break-even period",
    "expected net economic benefit":
        "expected net economic benefit >= 3 × switching cost",
    "target allocation difference":
        "target allocation difference >= 3–5 percentage points",
    "cooldown": "cooldown ~6h",
    "maximum daily turnover": "maximum daily turnover 20–25%",
}

#: Величина §23 → ИМЯ ВЛАДЕЛЬЦА той же величины в §22. Ось СУЩЕСТВОВАНИЯ по
#: этим строкам БЕРЁТСЯ у §22 и здесь не перемеривается.
#:
#: Две строки §23 указывают на ОДНУ строку §22, и это не ошибка карты:
#: «3 подтверждения подряд» и «устойчивость ≥ 3 × срок окупаемости» — два
#: РАЗНЫХ стартовых значения ОДНОЙ величины (устойчивости), и существование
#: ручки у них общее.
DELEGATED_TO_22: Dict[str, str] = {
    "minimum consecutive confirmations": "minimum persistence",
    "expected persistence": "minimum persistence",
    "expected net economic benefit": "minimum net gain",
    "cooldown": "cooldown",
    "maximum daily turnover": "maximum daily turnover",
}

#: Почему шестая величина НЕ делегирована. Печатается в отчёте: отказ от
#: делегирования есть УТВЕРЖДЕНИЕ, и оно обязано быть видно читателю.
DELEGATION_REFUSED: Dict[str, str] = {
    "target allocation difference": (
        "§22 «minimum allocation delta» мерит ПОЛОСУ ПЫЛИ у ОДНОЙ НОГИ "
        "(min_leg_frac, 0.5 % капитала), а §23 — разницу РАСКЛАДКИ в целом в "
        "процентных пунктах. Делегировать значило бы ответить верно на не тот "
        "вопрос: агрегат 10 пп, рассыпанный на ноги ниже пыли, отклоняется "
        "ПО ПРИЧИНЕ ПЫЛИ, а не по малости агрегата"),
}

#: Род ОБЪЯВЛЕНИЯ стартового значения — предикат §23. Шкала ОБЪЯВЛЕНА, а не
#: выведена из сравнений: ветка ``else`` по построению не может сказать, какие
#: роды существуют.
DECLARATION_KINDS: Tuple[str, ...] = (
    # значение есть И помечено СТАРТОВЫМ (shadow/стартовое/неоткалиброванное)
    "shadow_start_declared",
    # значение есть и объявлено ПРОДАКШН-политикой: у несущего контракта стоят
    # признаки производственного решения (версия, дата приёмки владельцем)
    "production_declared",
    # значение есть, но род не объявлен НИКАК: ни стартовым, ни производственным
    "undistinguished",
    # величины нет вовсе ⇒ стартовой её объявить НЕЧЕМ, и это НЕ «не смешиваем»
    "nothing_to_declare",
    UNMEASURED,
)

#: Исход сравнения стартового значения §23 с ЖИВЫМ значением политики.
VALUE_KINDS: Tuple[str, ...] = (
    "matches",            # живое значение попадает в названную владельцем полосу
    "differs",            # живое значение есть и в полосу НЕ попадает
    "no_live_value",      # величины нет ⇒ сравнивать не с чем
    "not_commensurable",  # живое число существует, но ИНОГО рода (срок против кратности)
    UNMEASURED,
)

#: Исход сцены «стартовое значение §23 применено к решению».
REACH_KINDS: Tuple[str, ...] = (
    # применили стартовое значение — и вердикт двери ПЕРЕВЕРНУЛСЯ
    "reachable_verdict_flipped",
    # применить можно, вердикт не двинулся; ЦЕНА смешения этой сценой НЕ
    # измерена, и «значит безопасно» отсюда НЕ следует
    "reachable_no_flip",
    # дверь такого входа не принимает — смешение недостижимо по построению
    "unreachable_by_construction",
    UNMEASURED,
)

#: Токены, по которым поле политики читается как СТАРТОВОЕ (shadow). Перечень
#: объявлен: искать «что-нибудь похожее» значило бы, что отчёт зависит от
#: фантазии читателя, а не от дерева.
SHADOW_MARKER_TOKENS: Tuple[str, ...] = (
    "shadow", "start", "provisional", "uncalibrated", "draft", "seed",
)

#: Токены ПРОДАКШН-признака: версия политики и дата приёмки владельцем — это
#: ровно то, чем «production policy» и объявляется в этом дереве.
PRODUCTION_MARKER_TOKENS: Tuple[str, ...] = ("version", "version_date")

#: Стартовые значения §23 в числах — для сцен и сравнения. Литералы здесь
#: ПРЕДМЕТ (это слова владельца), а не порог системы.
S23_COOLDOWN_HOURS: float = 6.0
S23_DAILY_TURNOVER_BAND: Tuple[float, float] = (0.20, 0.25)
S23_ALLOC_DIFF_BAND_PP: Tuple[float, float] = (3.0, 5.0)
S23_CONFIRMATIONS: int = 3
S23_MULTIPLE: float = 3.0

#: Края сцены шестой величины. Разница НИЖЕ полосы §23 и разница ВНУТРИ неё:
#: прибор смотрит ПЕРЕХОД вердикта, а не числа.
_ALLOC_BELOW_PP: float = 2.0
_ALLOC_WITHIN_PP: float = 10.0
#: Край APY сцены шестой величины. Он СПЕЦИАЛЬНО велик: при узком крае ход на
#: 2 пп не дотягивает до `min_gain_pp` (0.50 пп от ВСЕГО капитала), дверь
#: отказывает ПО ВЫИГРЫШУ, и «величина спрашивается» прочиталось бы на пустом
#: месте. Это первая из моих ошибок замера, названная в ADR-966.
_ALLOC_SCENE_EDGE_PCT: float = 30.0


# ─────────────────────── род объявления (предикат §23) ──────────────────────

def _marker_fields(fields: Dict[str, set], tokens: Sequence[str]) -> Dict[str, List[str]]:
    """Поля объявленных контрактов, чьё ИМЯ несёт любой из ``tokens``.

    Принадлежность МЕРИТСЯ (``dataclasses.fields`` у §41), а не объявляется
    списком: перечислить поля руками значило бы, что отчёт устареет молча при
    первом же новом поле политики.
    """
    out: Dict[str, List[str]] = {}
    for contract, names in (fields or {}).items():
        hit = sorted(n for n in names
                     if any(t in str(n).lower() for t in tokens))
        if hit:
            out[contract] = hit
    return out


def _contract_of(fields: Dict[str, set], names: Sequence[str]) -> Optional[str]:
    """Контракт, в котором объявлено хоть одно из полей ``names``."""
    for contract, declared in (fields or {}).items():
        if any(n in declared for n in names):
            return contract
    return None


def _declaration_kind(exists: bool,
                      contract: Optional[str],
                      shadow: Dict[str, List[str]],
                      production: Dict[str, List[str]]) -> Tuple[str, str]:
    """Род объявления стартового значения. Порядок вопросов объявлен.

    ``exists=False`` ⇒ ``nothing_to_declare``: это НЕ «стартовую политику не
    путают с production», а «путать нечего», и смешивать два этих исхода
    значило бы выдать пустоту за исполнение требования.
    """
    if not exists:
        return "nothing_to_declare", (
            "величины нет ни на одной поверхности решения — объявить её "
            "стартовой НЕЧЕМ, и «не считаем production policy» здесь верно ПУСТО")
    if contract is None:
        return UNMEASURED, ("величина спрашивается, но несущий контракт политики "
                            "не найден среди объявленных — род объявления "
                            "измерить нечем")
    if shadow.get(contract):
        return "shadow_start_declared", (
            "контракт {} несёт признак СТАРТОВОГО значения: {}".format(
                contract, ", ".join(shadow[contract])))
    if production.get(contract):
        return "production_declared", (
            "контракт {} объявлен ПРОДАКШН-политикой ({}) и признака стартового "
            "значения не несёт ни одного — то есть §23 здесь нарушен по "
            "объявлению, а не по величине".format(
                contract, ", ".join(production[contract])))
    return "undistinguished", (
        "контракт {} не несёт ни признака стартового значения, ни признака "
        "производственного решения — род числа не объявлен никак".format(contract))


# ───────── сравнение стартового значения §23 с ЖИВЫМ значением ──────────────

def _live_params() -> Any:
    """Живая колонка порогов. ``paper`` — умолчание боевого пути (ADR-060 §3)."""
    from spa_core.allocator.rebalance_economics import TriggerParams
    return TriggerParams.for_mode("paper")


def _value_comparison(name: str, exists: bool) -> Dict[str, Any]:
    """Попадает ли ЖИВОЕ значение в полосу, названную владельцем.

    Строгость НЕ оценивается: §23 про РОД числа. Исход ``differs`` печатает
    обе стороны и направление, но находкой сам по себе не является.
    """
    if not exists:
        return {"kind": "no_live_value",
                "why": "величины нет — сравнивать стартовое значение не с чем"}
    try:
        p = _live_params()
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED,
                "why": "живая колонка порогов не прочитана: {}: {}".format(
                    type(exc).__name__, exc)}

    if name == "cooldown":
        live_h = float(p.min_hold_days) * 24.0
        return {
            "kind": "matches" if abs(live_h - S23_COOLDOWN_HOURS) < 1e-6 else "differs",
            "owner": "~{:.0f} ч".format(S23_COOLDOWN_HOURS),
            "live": "{:.0f} ч (min_hold_days={})".format(live_h, p.min_hold_days),
            "why": ("живой срок удержания {:.0f} ч против стартовых {:.0f} ч — "
                    "в {:.1f} раза СТРОЖЕ; строгость §23 не оценивает, он про "
                    "РОД числа".format(live_h, S23_COOLDOWN_HOURS,
                                       live_h / S23_COOLDOWN_HOURS)),
        }
    if name == "maximum daily turnover":
        live = float(p.max_turnover_per_day)
        lo, hi = S23_DAILY_TURNOVER_BAND
        return {
            "kind": "matches" if lo - 1e-9 <= live <= hi + 1e-9 else "differs",
            "owner": "{:.0%}…{:.0%}".format(lo, hi),
            "live": "{:.0%} (max_turnover_per_day)".format(live),
            "why": ("живой дневной потолок {:.0%} ниже названной владельцем "
                    "полосы {:.0%}…{:.0%}".format(live, lo, hi)),
        }
    if name == "expected net economic benefit":
        return {
            "kind": "not_commensurable",
            "owner": "≥ {:.0f} × switching cost".format(S23_MULTIPLE),
            "live": "max_payback_days={:.0f} дн., min_gain_pp={:.2f} пп".format(
                float(p.max_payback_days), float(p.min_gain_pp)),
            "why": ("живое число — СРОК окупаемости издержек, стартовое — "
                    "КРАТНОСТЬ выгоды к издержкам. Это величины разного рода, и "
                    "назвать одну другой значило бы объявить сравнение там, где "
                    "его нет"),
        }
    return {"kind": UNMEASURED,
            "why": "правило сравнения для «{}» не объявлено".format(name)}


# ──────────── своя проба ШЕСТОЙ величины (делегировать нельзя) ──────────────

def _alloc_target(pp: float, cap: float) -> Dict[str, float]:
    """Цель, отличающаяся от книги ``A`` ровно на ``pp`` процентных пунктов."""
    return {"aave_v3": (0.40 - pp / 100.0) * cap,
            "pendle": (0.10 + pp / 100.0) * cap}


def _alloc_edge() -> Dict[str, float]:
    """Ставки сцены шестой величины: край СПЕЦИАЛЬНО широк (см. константу)."""
    return {"aave_v3": 2.0, "pendle": _ALLOC_SCENE_EDGE_PCT,
            "morpho_blue_base": 2.0}


def _probe_target_allocation_difference(fields: Dict[str, set]) -> List[dict]:
    """Спрашивает ли хоть одна дверь РАЗНИЦУ РАСКЛАДКИ в процентных пунктах."""
    cap = _scene_capital()
    books = _books(cap)
    out: List[dict] = []
    edge = _alloc_edge()

    below = _econ_move(books["A"], _alloc_target(_ALLOC_BELOW_PP, cap), "pendle",
                       apy_pct=edge)
    within = _econ_move(books["A"], _alloc_target(_ALLOC_WITHIN_PP, cap), "pendle",
                        apy_pct=edge)
    out.append(_rec(
        "economics", "quantity",
        str(below.decision) != str(within.decision),
        "разница раскладки {:.0f} пп → {:.0f} пп при крае {:.0f} пп: {} → {}"
        .format(_ALLOC_WITHIN_PP, _ALLOC_BELOW_PP, _ALLOC_SCENE_EDGE_PCT,
                within.decision, below.decision),
        gap=("дверь цены спрашивает ВЫИГРЫШ и ПЫЛЬ У НОГИ, но разницу РАСКЛАДКИ "
             "как величину не спрашивает: {:.0f} пп проходят ровно как {:.0f} пп"
             .format(_ALLOC_BELOW_PP, _ALLOC_WITHIN_PP)
             if str(below.decision) == str(within.decision) else None)))

    # Тот же вопрос у двери ЖИВОГО пути. Её вход — доллары оборота, а не пункты.
    d_below = _damper_move(books["A"], _alloc_target(_ALLOC_BELOW_PP, cap),
                           [_trade(10.0, 1_000.0, SCENE_NOW)])
    d_within = _damper_move(books["A"], _alloc_target(_ALLOC_WITHIN_PP, cap),
                            [_trade(10.0, 1_000.0, SCENE_NOW)])
    out.append(_rec(
        "damper", "quantity",
        bool(d_below.allowed) != bool(d_within.allowed),
        "та же пара разниц у ограничителя: {}/{} → {}/{}".format(
            d_within.decision, d_within.reason, d_below.decision, d_below.reason),
        gap=("ограничитель мерит оборот В ДОЛЛАРАХ и о процентных пунктах "
             "разницы раскладки не спрашивает вовсе"
             if bool(d_below.allowed) == bool(d_within.allowed) else None)))

    # Ось ручки: поле политики для ЭТОЙ величины не объявлено. `min_leg_frac`
    # ручкой ЗДЕСЬ не считается — это полоса пыли у НОГИ (DELEGATION_REFUSED), и
    # признать её ручкой агрегата значило бы закрыть §23 чужим полем.
    dust = _contract_of(fields, ["min_leg_frac"])
    out.append(_rec(
        "economics", "threshold", False,
        "поля политики для РАЗНИЦЫ РАСКЛАДКИ не объявлено; ближайшее "
        "{} — полоса пыли У НОГИ, а не агрегат".format(
            "{}.min_leg_frac".format(dust) if dust else "min_leg_frac"),
        gap=DELEGATION_REFUSED["target allocation difference"]))

    # Контрапункт, измеренный, а не предположенный: агрегат ВНУТРИ полосы §23,
    # рассыпанный на ноги НИЖЕ пыли, отклоняется ПО ПРИЧИНЕ ПЫЛИ.
    spread_target: Dict[str, float] = {"aave_v3": 0.30 * cap}
    spread_apy: Dict[str, float] = dict(edge)
    for i in range(20):
        spread_target["p{:02d}".format(i)] = 0.005 * cap - 1.0
        spread_apy["p{:02d}".format(i)] = _ALLOC_SCENE_EDGE_PCT
    spread = _econ_move(books["A"], spread_target, "pendle", apy_pct=spread_apy)
    out.append(_rec(
        "economics", "quantity", False,
        "агрегат ~{:.0f} пп на двадцати ногах по 0.499 % капитала: {} ({})"
        .format(_ALLOC_WITHIN_PP, spread.decision,
                "; ".join(list(spread.reasons)[:1])),
        gap=("отказ есть, но причиной названа ПЫЛЬ У НОГ, а не малость "
             "агрегата — которого здесь {:.0f} пп. Это и есть доказательство, "
             "что величины §23 в дереве нет: существующая ручка мерит НОГУ"
             .format(_ALLOC_WITHIN_PP)))) 
    return out


# ───────────────── достижимость: стартовое значение В ДЕЛЕ ──────────────────

def _reach_cooldown_on_live_door() -> Dict[str, Any]:
    """§23 ``cooldown ~6h``, поданный двери ЖИВОГО пути.

    Сцена ПОСТРОЕНА, а не предположена: без неё «мы их не путаем» было бы верно
    СЛУЧАЙНО — из того, что слова «shadow» нет в политике, не следует, что
    стартовое число не двинет живое решение.
    """
    cap = _scene_capital()
    books = _books(cap)
    trades = [_trade(0.5, 1_000.0, SCENE_NOW)]      # последний ход 12 ч назад
    try:
        base = _damper_move(books["A"], books["B"], trades)
        start = _damper_move(books["A"], books["B"], trades,
                             params=_trigger_params(
                                 min_hold_days=S23_COOLDOWN_HOURS / 24.0))
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "why": "{}: {}".format(
            type(exc).__name__, exc)}
    flipped = bool(base.allowed) != bool(start.allowed)
    return {
        "kind": "reachable_verdict_flipped" if flipped else "reachable_no_flip",
        "surface": "damper",
        "baseline": "{}/{} — {}".format(base.decision, base.reason, base.detail),
        "with_start_value": "{}/{} — {}".format(
            start.decision, start.reason, start.detail),
        "why": ("стартовое значение §23 ({:.0f} ч), поданное двери ЖИВОГО пути, "
                "переворачивает её вердикт {} → {}: ничто в дереве не мешает "
                "стартовому числу стать производственным, потому что рода "
                "«стартовое» в политике нет вовсе"
                .format(S23_COOLDOWN_HOURS, base.decision, start.decision)
                if flipped else
                "стартовое значение применилось, но вердикт не двинулся — цена "
                "смешения ЭТОЙ сценой не измерена, и «безопасно» отсюда не следует"),
    }


def _reach_turnover_on_price_door() -> Dict[str, Any]:
    """§23 ``maximum daily turnover 20–25%``, поданный двери ЦЕНЫ.

    🪤 Сцена ИЗОЛИРУЕТ дневной потолок намеренно. Первая редакция брала ход
    сразу на 22 пп — и он отклонялся ПОТОЛКОМ ОДНОГО ХОДА (15 %) и абсолютной
    суммой ($15 000), то есть СОСЕДНИМИ ограничениями; возмущение дневного
    потолка вердикт не двигало, и прибор сказал бы «ручка инертна», споря с
    §22, где та же величина измерена BINDING. Вторая из моих ошибок замера
    (ADR-966). Изоляция: ход ПОД потолком одного хода, а дневной бюджет уже
    почти израсходован — тогда связывает ровно дневная ручка.
    """
    cap = _scene_capital()
    books = _books(cap)
    spent_today = 8_000.0
    lo, hi = S23_DAILY_TURNOVER_BAND
    start_value = (lo + hi) / 2.0
    try:
        base = _econ_move(books["A"], books["B"], "pendle",
                          turnover_today_usd=spent_today)
        start = _econ_move(books["A"], books["B"], "pendle",
                           turnover_today_usd=spent_today,
                           params=_trigger_params(
                               max_turnover_per_day=start_value))
    except Exception as exc:  # noqa: BLE001
        return {"kind": UNMEASURED, "why": "{}: {}".format(
            type(exc).__name__, exc)}
    flipped = str(base.decision) != str(start.decision)
    return {
        "kind": "reachable_verdict_flipped" if flipped else "reachable_no_flip",
        "surface": "economics",
        "isolation": ("ход 10 пп под потолком одного хода 15 %, за сегодня уже "
                      "${:,.0f} — связывает ровно дневная ручка".format(spent_today)),
        "baseline": "{} ({})".format(base.decision, "; ".join(list(base.reasons)[:1])),
        "with_start_value": "{} ({})".format(
            start.decision, "; ".join(list(start.reasons)[:1])),
        "why": ("стартовое значение §23 ({:.1%}), поданное двери цены, "
                "переворачивает её вердикт {} → {}"
                .format(start_value, base.decision, start.decision)
                if flipped else
                "стартовое значение применилось, но вердикт не двинулся — "
                "проверь изоляцию сцены: соседний потолок мог связать первым"),
    }


#: Поля политики, несущие величину. Объявлено картой, а не угадано по имени:
#: «похоже по названию» признаком принадлежности не является, а карта краснеет
#: тестом, если поле переименуют.
_POLICY_FIELDS_OF: Dict[str, Tuple[str, ...]] = {
    "cooldown": ("min_hold_days", "act_cooldown_days"),
    "maximum daily turnover": ("max_turnover_per_day",),
    "expected net economic benefit": ("max_payback_days", "min_gain_pp"),
    "minimum consecutive confirmations": (),
    "expected persistence": (),
    "target allocation difference": (),
}


# ───────────────────────────── сборка отчёта ────────────────────────────────

def _delegated_22() -> Tuple[Dict[str, dict], str]:
    """Вердикты §22 по пяти величинам — БЕЗ перемера."""
    if not _DOOR_22:
        return {}, "прибор §22 не ввезён"
    try:
        doc = census_22()
    except Exception as exc:  # noqa: BLE001
        return {}, "§22 не измерен: {}: {}".format(type(exc).__name__, exc)
    # Ключ делегирования — СЛОВО ВЛАДЕЛЬЦА (`param`), а не наш слаг:
    # переименуй §22 свою строку — делегирование обязано сказать «НЕ ИЗМЕРЕНО».
    by_name = {str(p.get("param")): p for p in (doc.get("params") or [])}
    if not doc.get("control", {}).get("passed"):
        return by_name, "положительный контроль §22 не прошёл: {}".format(
            doc.get("control", {}).get("reason") or "причина не названа")
    return by_name, ""


def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Замер §23. Живой ``data/`` не читается и не пишется."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    fields = _declared_policy_fields() if _SCALE_41 else {}
    shadow = _marker_fields(fields, SHADOW_MARKER_TOKENS)
    production = _marker_fields(fields, PRODUCTION_MARKER_TOKENS)

    if _DOOR_22 and not _VOCAB_ERRORS:
        control_ok, control_why, baseline = _control()
    else:
        control_ok, control_why, baseline = False, (
            "словари/сцены НЕ ВВЕЗЕНЫ: {}".format("; ".join(_VOCAB_ERRORS))), {}

    delegated, delegation_why = _delegated_22()

    rows: List[Dict[str, Any]] = []
    for name in SHADOW_START_VALUES:
        entry: Dict[str, Any] = {
            "value": name,
            "owner_wording": OWNER_START_WORDING[name],
            "records": [],
        }
        # ── ось СУЩЕСТВОВАНИЯ ────────────────────────────────────────────────
        if name in DELEGATED_TO_22:
            src = DELEGATED_TO_22[name]
            row = delegated.get(src)
            entry["delegated_to"] = "§22 «{}»".format(src)
            if row is None or delegation_why:
                entry["existence"] = UNMEASURED
                entry["existence_detail"] = (
                    delegation_why or "§22 не содержит строки «{}»".format(src))
            else:
                entry["existence"] = row.get("outcome")
                entry["existence_detail"] = row.get("detail") or ""
                entry["delegated_surfaces"] = row.get("surfaces_binding") or []
        else:
            entry["delegation_refused"] = DELEGATION_REFUSED.get(name, "")
            if not control_ok:
                entry["existence"] = UNMEASURED
                entry["existence_detail"] = control_why
            else:
                try:
                    recs = _probe_target_allocation_difference(fields)
                except Exception as exc:  # noqa: BLE001 — упавшая проба = НЕ ИЗМЕРЕНО
                    entry["existence"] = UNMEASURED
                    entry["existence_detail"] = "{}: {}".format(
                        type(exc).__name__, exc)
                    recs = []
                if recs:
                    asked = any(r["axis"] == "quantity" and r["changed"] for r in recs)
                    dials = any(r["axis"] == "threshold" and r["changed"]
                                and r.get("policy_field") for r in recs)
                    entry["existence"] = (
                        BINDING if asked and dials else
                        LITERAL if asked else ABSENT)
                    entry["existence_detail"] = (
                        "ни одна дверь решения не реагирует на разницу раскладки "
                        "как на величину, и поля политики для неё не объявлено"
                        if entry["existence"] == ABSENT else
                        "величина спрашивается, см. записи пробы")
                    entry["records"] = recs
                    entry["gaps"] = [{"surface": r["surface"], "gap": r["gap"]}
                                     for r in recs if r.get("gap")]

        exists = entry.get("existence") not in (ABSENT, UNMEASURED, None)
        unmeasured_existence = entry.get("existence") in (UNMEASURED, None)

        # ── ось РОДА ОБЪЯВЛЕНИЯ (предикат §23) ───────────────────────────────
        if unmeasured_existence:
            entry["declaration"] = UNMEASURED
            entry["declaration_detail"] = (
                "существование не измерено ⇒ род объявления измерить нечем: "
                "{}".format(entry.get("existence_detail") or "причина не названа"))
        else:
            contract = None
            if exists:
                contract = _contract_of(
                    fields, _POLICY_FIELDS_OF.get(name, ()))
            kind, why = _declaration_kind(exists, contract, shadow, production)
            entry["declaration"] = kind
            entry["declaration_detail"] = why
            entry["carrying_contract"] = contract

        # ── ось ЗНАЧЕНИЯ ─────────────────────────────────────────────────────
        entry["value_check"] = (
            {"kind": UNMEASURED,
             "why": "существование не измерено ⇒ сравнивать нечего"}
            if unmeasured_existence else _value_comparison(name, exists))
        rows.append(entry)

    reach: Dict[str, Any] = {}
    if control_ok:
        reach["cooldown_on_live_door"] = _reach_cooldown_on_live_door()
        reach["turnover_on_price_door"] = _reach_turnover_on_price_door()
    else:
        reach["cooldown_on_live_door"] = {"kind": UNMEASURED, "why": control_why}
        reach["turnover_on_price_door"] = {"kind": UNMEASURED, "why": control_why}

    tally = {k: sum(1 for r in rows if r.get("declaration") == k)
             for k in DECLARATION_KINDS}
    return {
        "section": "§23 Starting policy for Shadow Mode",
        "owner_criterion": (
            "§23 ТЗ «Portfolio CIO»: для shadow testing можно использовать "
            "стартовые значения, но НЕ считать их production policy; шесть "
            "величин (minimum 3 consecutive confirmations · expected "
            "persistence ≥ 3 × break-even · expected net economic benefit "
            "≥ 3 × switching cost · target allocation difference ≥ 3–5 пп · "
            "cooldown ~6h · maximum daily turnover 20–25 %)"),
        "values_declared": OWNER_START_VALUES_DECLARED,
        "order_g954_named": ORDER_G954_NAMED,
        "order_undercount": OWNER_START_VALUES_DECLARED - ORDER_G954_NAMED,
        "surfaces": list(SURFACES_22),
        "scale_imported_from": (
            "spa_core/analytics/anti_churn_census.py (§22) → "
            "spa_core/monitoring/cio_auto_execution_limits.py (§41)"),
        "control": {"passed": control_ok, "reason": control_why,
                    "healthy_baseline": baseline},
        "delegation": {"rows": sorted(DELEGATED_TO_22),
                       "refused": dict(DELEGATION_REFUSED),
                       "unmeasured_reason": delegation_why},
        "markers": {"shadow_start": shadow, "production": production},
        "tally": tally,
        "values": rows,
        "reachability": reach,
        "vocab_errors": list(_VOCAB_ERRORS),
        "not_claimed": [
            "КАЛИБРОВКА не измерена: последняя строка §23 спрашивает об ИСТОРИИ "
            "числа (кто откалибровал и по какому прогону), а прибор читает "
            "сегодняшнее дерево. Предикат назван и отдан следующему заказу; "
            "нулём его отсутствие не считается",
            "СТРОГОСТЬ не оценивается: живое значение, оказавшееся строже "
            "стартового, не находка и не успех — §23 про РОД числа",
        ],
        "advisory": ("прибор только ЧИТАЕТ: ни один порог не изменён, ни одна "
                     "недостающая величина не построена — развести стартовую "
                     "политику с production это money-path и решение владельца "
                     "(ADR-285, предмет №1)"),
    }


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §23 исполняется · 1 — находка названа · 2 — НЕ ИЗМЕРЕНО."""
    if report.get("vocab_errors") or not report.get("control", {}).get("passed"):
        return 2
    tally = report.get("tally") or {}
    if tally.get(UNMEASURED):
        return 2
    reach = report.get("reachability") or {}
    if any((v or {}).get("kind") == UNMEASURED for v in reach.values()):
        return 2
    # Находка: хоть одна величина объявлена ПРОДАКШН-политикой или не объявлена
    # никак, либо стартовое значение доказанно переворачивает вердикт двери.
    if tally.get("production_declared") or tally.get("undistinguished"):
        return 1
    if any((v or {}).get("kind") == "reachable_verdict_flipped"
           for v in reach.values()):
        return 1
    # «Объявить нечем» — тоже находка: требование §23 исполнено ПУСТО.
    if tally.get("nothing_to_declare"):
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    L: List[str] = ["§23 ТЗ «Portfolio CIO»: Starting policy for Shadow Mode",
                    "=" * 72]
    ctl = report["control"]
    L.append("контроль: {} {}".format(
        "ПРОШЁЛ" if ctl["passed"] else "НЕ ПРОШЁЛ", ctl["reason"]))
    L.append("  здоровая сцена: {}".format(json.dumps(
        ctl["healthy_baseline"], ensure_ascii=False)))
    L.append("шкала ввезена из: {}".format(report["scale_imported_from"]))
    L.append("величин в ТЗ: {} · заказ G954 назвал: {} · ПОТЕРЯНО заказом: {}"
             .format(report["values_declared"], report["order_g954_named"],
                     report["order_undercount"]))
    mk = report["markers"]
    L.append("признак СТАРТОВОГО значения в объявленных контрактах политики: {}"
             .format(json.dumps(mk["shadow_start"], ensure_ascii=False)
                     if mk["shadow_start"] else "НЕ НАЙДЕН НИ ОДИН"))
    L.append("признак ПРОДАКШН-решения: {}".format(
        json.dumps(mk["production"], ensure_ascii=False)
        if mk["production"] else "не найден"))
    L.append("")
    L.append("ШЕСТЬ СТАРТОВЫХ ВЕЛИЧИН — есть ли она, и каким РОДОМ объявлена:")
    for r in report["values"]:
        L.append("  {:<22} «{}»".format(r.get("declaration"), r["owner_wording"]))
        L.append("      существование: {} — {}".format(
            r.get("existence"), r.get("existence_detail") or ""))
        if r.get("delegated_to"):
            L.append("      ← ДЕЛЕГИРОВАНО {} (не перемеряется: одна шкала, "
                     "одно измерение)".format(r["delegated_to"]))
        if r.get("delegation_refused"):
            L.append("      ⊘ ДЕЛЕГИРОВАНИЕ ОТКЛОНЕНО: {}".format(
                r["delegation_refused"]))
        L.append("      род: {}".format(r.get("declaration_detail") or ""))
        v = r.get("value_check") or {}
        L.append("      значение: {} — владелец {} · живое {}".format(
            v.get("kind"), v.get("owner", "—"), v.get("live", "—")))
        if v.get("why"):
            L.append("        {}".format(v["why"]))
        for g in r.get("gaps") or []:
            L.append("      ⚠ [{}] {}".format(g["surface"], g["gap"]))
    t = report["tally"]
    L.append("")
    L.append("  ИТОГ по шести: объявлено СТАРТОВЫМ {} · объявлено PRODUCTION {} · "
             "род не объявлен {} · объявлять НЕЧЕМ {} · НЕ ИЗМЕРЕНО {}".format(
                 t.get("shadow_start_declared", 0), t.get("production_declared", 0),
                 t.get("undistinguished", 0), t.get("nothing_to_declare", 0),
                 t.get(UNMEASURED, 0)))
    L.append("")
    L.append("ДОСТИЖИМОСТЬ — сцена «стартовое значение применено к решению» ПОСТРОЕНА:")
    for key, label in (("cooldown_on_live_door", "cooldown ~6ч → дверь ЖИВОГО пути"),
                       ("turnover_on_price_door", "дневной оборот 22.5 % → дверь ЦЕНЫ")):
        s = report["reachability"].get(key) or {}
        L.append("  {}: {}".format(label, s.get("kind")))
        if s.get("isolation"):
            L.append("      изоляция: {}".format(s["isolation"]))
        if s.get("baseline"):
            L.append("      как есть:   {}".format(s["baseline"]))
            L.append("      со стартовым: {}".format(s.get("with_start_value")))
        L.append("      {}".format(s.get("why") or ""))
    L.append("")
    for line in report.get("not_claimed") or []:
        L.append("ℹ ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ: {}".format(line))
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for x in report["vocab_errors"]:
            L.append("    {}".format(x))
    code = verdict_code(report)
    L.append({0: "✅ §23 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§23 Starting policy").splitlines()[0])
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
