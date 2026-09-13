"""Какая доля ПРЕДЛОЖЕННОГО ОБОРОТА зависела от ненаблюдённой ноги (заказ #587/G6).

Заказ, стоящий в хвосте карточки приказа владельца «Portfolio CIO» после цикла #588:

> Режим деградации назван, но не измерен — на трёх деградировавших днях и на любом
> будущем надо померить, **какая доля предложенного оборота вообще зависела от
> ненаблюдённой ноги**. Ход, где такая нога несёт $40 000 из $40 000 оборота, и ход,
> где она несёт $200, — разные отказы, и сегодня они неотличимы.

ADR-366 закрыл G5: знаменатель ``hit_rate`` стои́т на 100 % наблюдённого капитала ПО
ПОСТРОЕНИЮ, потому что день с ненаблюдённой двигаемой ногой судья честно помечает
``UNCHECKED`` и такой день из знаменателя выпадает. Это сказало, ЧТО дни выпали, и не
сказало НИЧЕГО о том, насколько отказ был заслужен. Отказ, где ненаблюдённая нога несёт
весь ход, и отказ, где она несёт округление, — разные события, и принимать их за одно
значит не знать, дорого ли стои́т слепота входов.

## Предмет ровно один

**Доля оборота дня, приходящаяся на ноги, из-за которых день и был отвергнут.**
Не причина, по которой нога осталась без ставки (предмет ``unevidenced_leg_causes``,
заказ #543). Не граница критерия взвода (предмет ``hit_rate_selection_bias``, ось C,
заказ #541). Не пересчёт ``hit_rate`` и не суждение о том, был ли HOLD прав.

## Отвергающие ноги спрашиваются У СУДЬИ, а не выводятся своей копией правила

Соблазн был назвать ненаблюдённой ногой ту, которой нет в ``apy_evidenced_pct`` записи
ТОГО ЖЕ дня. Замер показал, что это было бы верным ответом на не тот вопрос: судья
(`shadow_trigger_eval._day_gain_usd`) спрашивает ставки не у дня решения, а у ДНЕЙ
ВПЕРЁД — ход дня D оценивается ставками D+1…D+h, и отвергается день тогда, когда
двигаемая нога осталась без ставки НА КАЖДОМ форвардном дне (``checked == 0``). Поэтому
множество отвергающих ног берётся готовым из канонического отчёта — ключ
``unpriced_protocols`` строки ``per_verdict`` — и второй копии правила здесь не
появляется. Две копии спорили бы о том же дне молча: обе печатают число, ни одна —
правило.

Следствие, которое надо знать читателю: **ось этого прибора НЕ совпадает с осью
ADR-366.** Тот мерил наблюдённость капитала САМОГО дня и назвал три деградировавших дня;
судья отвергает по форвардным ставкам и отвергает восемь. Пересечение неполно, и это
замер, а не расхождение: вопросы разные. Прибор докладывает оба числа рядом, чтобы
«три» и «восемь» не читались как ошибка одного из них.

## Знаменатель — канонический, и его основание НАЗЫВАЕТСЯ

Оборот берётся из той же строки ``per_verdict``, то есть ровно тот, которым судья мерил
существенность хода (``MATERIAL_TURNOVER_USD``). Своего оборота прибор не считает — иначе
один порог получил бы два знаменателя, и спор был бы молчаливым.

Основание всё же проверяется и печатается, потому что оснований в дереве больше одного:
``_turnover_usd`` предпочитает записанное ``turnover_usd``, а при его отсутствии берёт
``sum|Δ|/2``. Замер 13.09 на живом журнале: эти два числа расходятся на **14 днях из 39**,
и на 2026-09-10 — 46 842.10 против 35 000.00. Прибор, поделивший ход ненаблюдённой ноги
($40 000) на резервное основание, напечатал бы **114.3 %** — долю больше единицы, то есть
заведомую бессмыслицу. Поэтому основание объявлено ключом ``denominator_basis``, а
невоспроизводимое основание — ТРЕТИЙ исход, а не молчаливый выбор одного из кандидатов.

## Доля даётся ГРАНИЦАМИ, когда точки не существует

Оборот считает доллар ОДИН раз, а у переезда доллара две ноги — источник и назначение.
Поэтому «доля оборота, приходящаяся на ноги U» не есть ``Σ|Δ_p| / T``: сумма всех
``|Δ_p|`` равна ``2T``, и такое деление даёт до 200 %. Матрицы переводов «откуда куда»
журнал не несёт, значит точной атрибуции доллара не существует — и выдумывать её нельзя.

Существуют ГРАНИЦЫ, и они обе честны:

* ``lower = max(U_out, U_in) / T`` — столько долларов имеют в U хотя бы один конец при
  любой матрице переводов;
* ``upper = min(U_out + U_in, T) / T`` — больше не выйдет даже если U стои́т на обоих
  концах разных долларов.

Когда U лежит только на одной стороне, границы СОВПАДАЮТ и доля точна. Замер 13.09: так
на 4 днях из 8; на остальных интервал назван, а не сплющен в точку.

## Соразмерность отказа мерится порогом СУДЬИ, а не выдуманным процентом

Отказ назван **несоразмерным**, если ход ненаблюдённых ног (``max(U_out, U_in)``) ниже
``MATERIAL_TURNOVER_USD`` — того самого порога, ниже которого судья сам считает движение
шумом, — при существенном обороте дня. Свой процент («ниже 10 % = мало») был бы числом из
головы: порог берётся у судьи по ссылке на модуль, и сдвинется вместе с ним.

## Третий производитель того же хода — и он теряет ноги

Ход ноги описывают в записи ДВА поля: разность книг (``current_positions`` против
``target_positions``) и готовый список ``legs``. Замер 13.09: на 2026-09-06 ``legs``
не несёт ногу ``aave_v3`` (−$263.16), которую разность книг несёт, — и записанное
``turnover_usd`` совпадает с исходящей стороной ИМЕННО по ``legs`` на всех 12 днях, где
``legs`` есть. То есть записанный знаменатель считан по населению, из которого ноги
выпадают, а судья отвергает день по населению разности книг.

Потерянная нога была наблюдённой, и вреда в тот день не случилось. Но это и есть в точности
тот «$200-случай», о котором спрашивает заказ: окажись выпавшая нога НЕНАБЛЮДЁННОЙ, прибор,
читающий ``legs``, доложил бы «ненаблюдённых ног не двигали» при дне, отвергнутом целиком.
Поэтому такая нога — ``CRITICAL``, а не сноска.

ADVISORY. Только stdlib. Прибор ЧИТАЕТ: ни ``hit_rate``, ни ``MIN_HIT_RATE``, ни
``MATERIAL_TURNOVER_USD``, ни писателя журнала, ни ``POLLED_ADAPTERS``, ни пороги
RiskPolicy v1.0, ни стоп-кран, ни живой трек он не трогает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Судья зовётся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное имя
# есть СНИМОК функции на момент импорта, и подмена канонического правила отбора или
# порога прошла бы мимо нас молча. Так же поступает сосед по заказу (ADR-366).
from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.unobserved_turnover_dependence")

OUTPUT_FILENAME = "unobserved_turnover_dependence.json"
VERSION = "unobs-turnover-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Причина отказа, которая ОДНА и составляет население этого прибора. Прочие
#: ``UNCHECKED`` (нет форвардных дней, нет записанной цели) к ненаблюдённости входов
#: отношения не имеют, и смешивать их значило бы разбавить предмет.
REFUSAL_REASON = "no_evidenced_apy_for_moved_legs"

#: Доллар, ниже которого разность книг движением не считается — константа судьи
#: (`_deltas`). Повторена здесь ТОЛЬКО как документация порога сравнения долей.
_EPS_USD = 0.005

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `MATERIAL_TURNOVER_USD`, "
             "`shadow_trigger_eval`, писатель журнала, `POLLED_ADAPTERS`, пороги "
             "RiskPolicy v1.0, стоп-кран и живой трек НЕ трогаются — прибор только "
             "делит ход ненаблюдённых ног на оборот того же дня")

#: Границы утверждения — В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта шапку
#: не открывает, а именно он переносит число в решение о взводе.
WHAT_IT_DOES_NOT_PROVE = [
    "не утверждает, что HOLD на отвергнутых днях был НЕПРАВ, и исход дня не "
    "пересчитывает: высокая доля означает, что отказ СОРАЗМЕРЕН, а не что он верен",
    "не двигает и не оценивает `hit_rate` и его границу: это предмет "
    "`hit_rate_selection_bias` (ось C, заказ #541)",
    "не объясняет, ПОЧЕМУ нога осталась без живой ставки: это предмет "
    "`unevidenced_leg_causes` (заказ #543)",
    "не измеряет наблюдённость капитала САМОГО дня: это предмет "
    "`capital_observability_history` (ADR-366), и ось у него ДРУГАЯ — прибор "
    "докладывает оба счёта рядом, но одно за другое не выдаёт",
    "точной доли не утверждает вовсе, когда ненаблюдённые ноги стоят на обеих "
    "сторонах хода: матрицы переводов «откуда куда» журнал не несёт, поэтому "
    "публикуются ГРАНИЦЫ, а совпадение границ — замер, а не удача",
    "доля считается от ОБОРОТА, а не от книги: сколько денег в тот день стояло на "
    "ненаблюдённых ставках ВООБЩЕ — вопрос соседа, а не этот",
]

# ──────────────────────────────────────────────────────────────────────────
# исходы дня, который НЕ измеряется
# ──────────────────────────────────────────────────────────────────────────
DAY_NO_RECORD = ("отвергнутый день назван судьёй, но записи с такой датой в журнале нет "
                 "— ход ног не из чего вывести")
DAY_NO_TURNOVER = ("оборот дня не назван судьёй числом — знаменателя нет, и доли у "
                   "него не существует: это НЕ 0 % и НЕ 100 %")
DAY_ZERO_TURNOVER = ("оборот дня равен нулю при непустом списке отвергающих ног — "
                     "доли у нуля не существует, и согласием этот случай не читается")
DAY_NO_DELTAS = ("разность книг дня пуста: ни одна нога не двигалась, а судья назвал "
                 "отвергающие — два чтения одной записи спорят")
DAY_NO_UNPRICED = ("судья отверг день по ненаблюдённым ногам, но списка `unpriced_protocols` "
                   "в строке нет — предмет замера не назван")


def _numeric(value) -> Optional[float]:
    """Число или ``None``. ``bool`` числом не считается: «да» не есть величина."""
    if value is None or isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _legs_map(record: dict) -> Optional[Dict[str, float]]:
    """Ход ног по полю ``legs`` — ТРЕТИЙ производитель той же величины.

    ``None`` = поля нет вовсе (до 2026-08-30 записи его не несут) — это «не с чем
    сверять», а не «сверка сошлась». Пустой список остаётся ЗНАЧЕНИЕМ: он говорит
    «ног не двигали», и на дне с нулевым оборотом это правда.
    """
    legs = observed(record, "legs", kind=list)
    if legs is None:
        return None
    out: Dict[str, float] = {}
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        name = leg.get("protocol")
        delta = _numeric(leg.get("delta_usd"))
        if isinstance(name, str) and delta is not None:
            out[name] = delta
    return out


def _basis(record: dict, deltas: Dict[str, float], turnover: float,
           legs: Optional[Dict[str, float]]) -> dict:
    """ЧЕМ является знаменатель: какое правило воспроизводит записанный оборот.

    Кандидаты перечислены явно, и «ни один не подошёл» — самостоятельный исход. Молча
    выбрать ближайшего значило бы выдать догадку о правиле писателя за замер.
    """
    out_usd = sum(-v for v in deltas.values() if v < 0)
    in_usd = sum(v for v in deltas.values() if v > 0)
    candidates: Dict[str, float] = {
        "half_gross_of_book_delta": sum(abs(v) for v in deltas.values()) / 2.0,
        "outflow_of_book_delta": out_usd,
        "inflow_of_book_delta": in_usd,
        "max_side_of_book_delta": max(out_usd, in_usd),
    }
    if legs is not None:
        l_out = sum(-v for v in legs.values() if v < 0)
        l_in = sum(v for v in legs.values() if v > 0)
        candidates.update({
            "outflow_of_legs": l_out,
            "inflow_of_legs": l_in,
            "max_side_of_legs": max(l_out, l_in),
        })
    matches = sorted(k for k, v in candidates.items() if abs(v - turnover) <= 0.01)
    recorded = _numeric(record.get("turnover_usd"))
    return {
        "reproduced_by": matches,
        "recorded_turnover_usd": recorded,
        "candidates_usd": {k: round(v, 2) for k, v in candidates.items()},
        "book_delta_outflow_usd": round(out_usd, 2),
        "book_delta_inflow_usd": round(in_usd, 2),
        # Книга, у которой стороны не равны, — не ошибка: остаток уехал в кэш или
        # пришёл из него. Но НАЗВАН он обязан быть, иначе разница сторон читается
        # как потеря денег.
        "sides_balance": abs(out_usd - in_usd) <= 0.01,
        "cash_residual_usd": round(in_usd - out_usd, 2),
        "reproducible": bool(matches),
        "reason": None if matches else (
            "записанный оборот не воспроизводится из записи НИ ОДНИМ из перечисленных "
            "правил — основание знаменателя НЕ ИЗМЕРЕНО, и ближайший кандидат за него "
            "не подставляется"),
    }


def _producer_divergence(deltas: Dict[str, float],
                         legs: Optional[Dict[str, float]],
                         unpriced: List[str]) -> dict:
    """Спорят ли разность книг и ``legs`` о том, какие ноги двигались.

    Нога, которую ``legs`` потерял, ОПАСНА ровно тогда, когда она ненаблюдённая:
    читатель ``legs`` доложил бы «ненаблюдённых ног не двигали» о дне, отвергнутом
    целиком. Поэтому исход различает потерю наблюдённой ноги и потерю отвергающей.
    """
    if legs is None:
        return {"measured": False,
                "reason": "в записи дня нет поля `legs` — сверка не состоялась, и "
                          "согласием она не читается"}
    unpriced_set = set(unpriced)
    missing_from_legs = sorted(p for p in deltas if p not in legs)
    extra_in_legs = sorted(p for p in legs if p not in deltas)
    disagreeing = sorted(p for p in set(deltas) & set(legs)
                         if abs(deltas[p] - legs[p]) > _EPS_USD)
    return {
        "measured": True,
        "agrees": not (missing_from_legs or extra_in_legs or disagreeing),
        "missing_from_legs": missing_from_legs,
        "missing_from_legs_usd": {p: round(deltas[p], 2) for p in missing_from_legs},
        # Потеря ОТВЕРГАЮЩЕЙ ноги — слепое пятно, а не расхождение округлений.
        "unpriced_missing_from_legs": sorted(set(missing_from_legs) & unpriced_set),
        "extra_in_legs": extra_in_legs,
        "amount_disagreements": disagreeing,
        "reason": None,
    }


def _day(record: Optional[dict], row: dict) -> dict:
    """Один отвергнутый день: доля оборота, зависевшая от отвергающих ног."""
    date = str(row.get("cycle_date"))
    out: dict = {"cycle_date": date}

    unpriced_raw = observed(row, "unpriced_protocols", kind=list)
    if unpriced_raw is None:
        out["unmeasured_reason"] = DAY_NO_UNPRICED
        return out
    unpriced = sorted(str(p) for p in unpriced_raw)
    out["unpriced_protocols"] = unpriced

    if record is None:
        out["unmeasured_reason"] = DAY_NO_RECORD
        return out

    turnover = _numeric(row.get("turnover_usd"))
    if turnover is None:
        out["unmeasured_reason"] = DAY_NO_TURNOVER
        return out
    out["turnover_usd"] = round(turnover, 2)

    deltas = _ste._deltas(record)
    if not deltas:
        out["unmeasured_reason"] = DAY_NO_DELTAS
        return out
    if turnover <= 0.0:
        out["unmeasured_reason"] = DAY_ZERO_TURNOVER
        return out

    legs = _legs_map(record)
    out["denominator_basis"] = _basis(record, deltas, turnover, legs)
    out["producer_divergence"] = _producer_divergence(deltas, legs, unpriced)

    u_out = sum(-deltas[p] for p in unpriced if deltas.get(p, 0.0) < 0)
    u_in = sum(deltas[p] for p in unpriced if deltas.get(p, 0.0) > 0)
    gross = max(u_out, u_in)
    out.update({
        "moved_legs": {p: round(v, 2) for p, v in sorted(deltas.items())},
        # Нога, названная судьёй отвергающей, но не двигавшаяся по разности книг, —
        # находка, а не ноль: молча она понизила бы долю.
        "unpriced_not_in_book_delta": sorted(p for p in unpriced if p not in deltas),
        "unpriced_outflow_usd": round(u_out, 2),
        "unpriced_inflow_usd": round(u_in, 2),
        "unpriced_gross_usd": round(gross, 2),
        "share_lower_pct": round(gross / turnover * 100.0, 4),
        "share_upper_pct": round(min(u_out + u_in, turnover) / turnover * 100.0, 4),
        # Границы совпали ⇒ доля ТОЧНА, и это свойство хода (ноги на одной стороне),
        # а не приближение. Различать обязан читатель, поэтому признак назван.
        "exact": abs(min(u_out + u_in, turnover) - gross) <= 0.01,
        "unpriced_side": ("exit_only" if u_in <= 0.0 < u_out else
                          "entry_only" if u_out <= 0.0 < u_in else
                          "both_sides" if u_out > 0.0 and u_in > 0.0 else "neither"),
        # Соразмерность — порогом СУДЬИ, не своим процентом.
        "material_turnover_usd": _ste.MATERIAL_TURNOVER_USD,
        "disproportionate": (gross < _ste.MATERIAL_TURNOVER_USD
                            <= turnover),
    })
    return out


def _denominator(data_dir: Path) -> dict:
    """Дни знаменателя ``hit_rate`` — у канонического производителя, не своей копией."""
    try:
        days = _ste.scored_days(data_dir)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        days = None
    if days is None:
        return {"measured": False, "days": None,
                "reason": ("знаменатель hit_rate не получен от "
                           "shadow_trigger_eval.scored_days — пустым множеством он НЕ "
                           "подменяется: пустое читалось бы как «оценённых дней нет»")}
    return {"measured": True, "days": sorted(days), "reason": None}


def _judge(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Строки ``per_verdict`` канонического судьи — или названная причина отказа."""
    try:
        report = _ste.evaluate_window(Path(data_dir), write=False)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return None, f"канонический судья отказал: {type(exc).__name__}: {exc}"
    rows = observed(report, "per_verdict", kind=list)
    if rows is None:
        return None, ("канонический отчёт не несёт `per_verdict` — пустым списком он НЕ "
                      "подменяется: пустое читалось бы как «отвергнутых дней нет»")
    return [r for r in rows if isinstance(r, dict)], ""


def _cross_axis(data_dir: Path) -> dict:
    """Сколько дней назвал деградировавшими СОСЕД (ADR-366) — и совпадают ли оси.

    Заказ говорил «на трёх деградировавших днях», и три — это счёт соседа: он мерил
    наблюдённость капитала САМОГО дня. Судья отвергает по форвардным ставкам, и таких
    дней восемь. Ни одно из чисел не ошибка; печатать одно за другое — ошибка. Поэтому
    оба счёта и их пересечение называются прямо, а отказ соседа — третий исход.
    """
    try:
        from spa_core.monitoring import capital_observability_history as _coh
        doc = _coh.measure(Path(data_dir))
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return {"measured": False,
                "reason": f"сосед `capital_observability_history` не ответил: "
                          f"{type(exc).__name__}: {exc}"}
    raw = observed(doc, "degraded_days", kind=list)
    if raw is None:
        return {"measured": False,
                "reason": "сосед не несёт `degraded_days` — пустым списком он НЕ "
                          "подменяется: пустое читалось бы как «деградации не было»"}
    days = sorted({str(d.get("cycle_date")) if isinstance(d, dict) else str(d)
                   for d in raw})
    return {"measured": True, "own_capital_degraded_days": days, "reason": None}


def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    data_dir = Path(data_dir)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    doc: dict = {
        "version": VERSION,
        "generated_at": stamp,
        "mode": "ADVISORY",
        "axis": ("доля ПРЕДЛОЖЕННОГО ОБОРОТА дня, приходящаяся на ноги, из-за которых "
                 "судья и отверг день (`unpriced_protocols`); знаменатель — оборот той "
                 "же строки `per_verdict`, своего оборота прибор не считает"),
        "refusal_reason_measured": REFUSAL_REASON,
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }

    rows, why = _judge(data_dir)
    if rows is None:
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None, "per_day": [], "findings": [f"[НЕ ИЗМЕРЕНО] {why}"]})
        return doc

    history, bad_lines = _ste.load_history(data_dir)
    by_date = {str(r.get("cycle_date")): r for r in history}
    doc["journal_rows"] = len(history)
    doc["corrupt_history_lines"] = bad_lines
    doc["denominator"] = _denominator(data_dir)
    doc["cross_axis"] = _cross_axis(data_dir)

    refusals = [r for r in rows if str(r.get("unchecked_reason") or "") == REFUSAL_REASON]
    # Прочие UNCHECKED называются ОТДЕЛЬНО, а не растворяются: «нет форвардных дней» —
    # не слепота входов, и складывать их значило бы разбавить предмет.
    other_unchecked = sorted(str(r.get("cycle_date")) for r in rows
                             if str(r.get("outcome") or "").upper() == "UNCHECKED"
                             and str(r.get("unchecked_reason") or "") != REFUSAL_REASON)

    per_day: List[dict] = []
    unmeasured: List[dict] = []
    for row in refusals:
        day = _day(by_date.get(str(row.get("cycle_date"))), row)
        if day.get("unmeasured_reason"):
            unmeasured.append({"cycle_date": day["cycle_date"],
                               "reason": day["unmeasured_reason"]})
        else:
            per_day.append(day)

    doc["per_day"] = per_day
    doc["population"] = {
        "verdict_rows": len(rows),
        "refusals_on_unpriced_legs": len(refusals),
        "measured_days": len(per_day),
        "unmeasured_days": unmeasured,
        "other_unchecked_days": other_unchecked,
        # Тождество истинно ПО ПОСТРОЕНИЮ (каждый отказ попадает ровно в один список) и
        # само по себе не доказывает ничего; ценно оно тем, что уронить день МОЛЧА
        # нельзя — падение тождества обязано быть громким.
        "accounting_identity_holds": len(per_day) + len(unmeasured) == len(refusals),
    }

    if not refusals:
        doc.update({
            "status": STATUS_OK,
            "answer": {"measured": True, "refusals": 0,
                       "note": ("судья не отверг ни одного дня по ненаблюдённым "
                                "двигаемым ногам — это измеренный НОЛЬ отказов, а не "
                                "отсутствие замера")},
        })
        doc["findings"] = _findings(doc)
        return doc

    if not per_day:
        doc.update({
            "status": STATUS_UNMEASURED,
            "unmeasured_reason": (f"отказов {len(refusals)}, и ни один не измерен — "
                                  f"причины названы поимённо в population.unmeasured_days"),
            "answer": None,
        })
        doc["findings"] = _findings(doc)
        return doc

    total_turnover = sum(d["turnover_usd"] for d in per_day)
    total_gross = sum(d["unpriced_gross_usd"] for d in per_day)
    doc["answer"] = {
        "measured": True,
        "refusals_measured": len(per_day),
        "proposed_turnover_usd": round(total_turnover, 2),
        "unobserved_dependent_usd": round(total_gross, 2),
        "share_lower_pct": round(total_gross / total_turnover * 100.0, 4),
        "min_day_share_lower_pct": round(min(d["share_lower_pct"] for d in per_day), 4),
        "max_day_share_lower_pct": round(max(d["share_lower_pct"] for d in per_day), 4),
        "days_exact": sum(1 for d in per_day if d["exact"]),
        "disproportionate_days": sorted(d["cycle_date"] for d in per_day
                                        if d["disproportionate"]),
    }
    doc["status"] = _status(doc)
    doc["findings"] = _findings(doc)
    return doc


# ──────────────────────────────────────────────────────────────────────────
# вердикт
# ──────────────────────────────────────────────────────────────────────────
def _blind_spots(doc: dict) -> List[dict]:
    """Дни, где ``legs`` потерял ОТВЕРГАЮЩУЮ ногу — читатель `legs` ослеп бы."""
    out = []
    for day in doc.get("per_day") or []:
        div = day.get("producer_divergence") or {}
        if div.get("measured") and div.get("unpriced_missing_from_legs"):
            out.append(day)
    return out


def _writer_divergence(doc: dict) -> List[dict]:
    """Дни, где производители хода спорят ИЛИ основание знаменателя невоспроизводимо."""
    out = []
    for day in doc.get("per_day") or []:
        div = day.get("producer_divergence") or {}
        basis = day.get("denominator_basis") or {}
        if (div.get("measured") and not div.get("agrees")) or not basis.get("reproducible"):
            out.append(day)
    return out


def _status(doc: dict) -> str:
    if not (doc.get("population") or {}).get("accounting_identity_holds", True):
        return STATUS_UNMEASURED
    answer = doc.get("answer") or {}
    if answer.get("disproportionate_days"):
        return STATUS_CRITICAL
    if _blind_spots(doc):
        return STATUS_CRITICAL
    if _writer_divergence(doc):
        return STATUS_WARNING
    if (doc.get("population") or {}).get("unmeasured_days"):
        return STATUS_WARNING
    return STATUS_OK


def _findings(doc: dict) -> List[str]:
    out: List[str] = []
    pop = doc.get("population") or {}
    answer = doc.get("answer") or {}

    if answer.get("measured") and answer.get("refusals") == 0:
        out.append("[ОТВЕТ] судья не отверг ни одного дня по ненаблюдённым двигаемым "
                   "ногам: измеренный НОЛЬ отказов")
    elif answer.get("measured"):
        out.append(
            f"[ОТВЕТ] на {answer['refusals_measured']} отвергнутых днях от "
            f"ненаблюдённой ноги зависело ${answer['unobserved_dependent_usd']:,.2f} "
            f"из ${answer['proposed_turnover_usd']:,.2f} предложенного оборота = "
            f"{answer['share_lower_pct']:.2f} % (нижняя граница); по дням от "
            f"{answer['min_day_share_lower_pct']:.2f} % до "
            f"{answer['max_day_share_lower_pct']:.2f} %, точных долей "
            f"{answer['days_exact']} из {answer['refusals_measured']}")
        for day in doc.get("per_day") or []:
            span = (f"{day['share_lower_pct']:.2f} %" if day["exact"]
                    else f"{day['share_lower_pct']:.2f}–{day['share_upper_pct']:.2f} %")
            out.append(
                f"[ПО ДНЯМ] {day['cycle_date']}: ноги {', '.join(day['unpriced_protocols'])} "
                f"несли ${day['unpriced_gross_usd']:,.2f} из ${day['turnover_usd']:,.2f} "
                f"оборота = {span} · сторона {day['unpriced_side']}")

    if answer.get("disproportionate_days"):
        out.append(
            f"[CRITICAL] отказ НЕСОРАЗМЕРЕН на днях "
            f"{', '.join(answer['disproportionate_days'])}: ход отвергающих ног ниже "
            f"${_ste.MATERIAL_TURNOVER_USD:,.2f} — порога, ниже которого судья сам "
            f"считает движение шумом, — а день при этом отвергнут целиком и выпал из "
            f"знаменателя hit_rate")
    elif answer.get("measured") and answer.get("refusals_measured"):
        out.append(
            f"[ОПОРА] несоразмерных отказов НЕТ: на каждом из "
            f"{answer['refusals_measured']} дней ход отвергающих ног выше порога "
            f"существенности судьи (${_ste.MATERIAL_TURNOVER_USD:,.2f}) — «$200-случай» "
            f"заказа на наблюдённой истории не встретился ни разу, и отказы "
            f"СОРАЗМЕРНЫ. Это не значит, что они верны: верность исхода прибор не "
            f"пересчитывает")

    for day in _blind_spots(doc):
        div = day["producer_divergence"]
        out.append(
            f"[CRITICAL] {day['cycle_date']}: поле `legs` НЕ несёт отвергающую ногу "
            f"{', '.join(div['unpriced_missing_from_legs'])}, которую несёт разность "
            f"книг — читатель `legs` доложил бы «ненаблюдённых ног не двигали» о дне, "
            f"отвергнутом целиком")

    for day in _writer_divergence(doc):
        if day in _blind_spots(doc):
            continue
        div = day.get("producer_divergence") or {}
        basis = day.get("denominator_basis") or {}
        if div.get("measured") and not div.get("agrees"):
            # Отсутствие суммы НАЗЫВАЕТСЯ: пустой словарь сказал бы «ничего не
            # потеряно» о дне, который в эту ветку попал ровно потому, что потеряно.
            _lost = observed(div, "missing_from_legs_usd", kind=dict)
            lost = "СУММА НЕ ИЗМЕРЕНА" if _lost is None else _lost
            out.append(
                f"[WARNING] {day['cycle_date']}: два производителя хода спорят — `legs` "
                f"теряет {lost or div.get('amount_disagreements')}, а записанный оборот "
                f"считан ИМЕННО по `legs` ({', '.join(basis.get('reproduced_by') or []) or '—'}); "
                f"нога наблюдена, вреда сегодня нет, но знаменатель считан по населению, "
                f"из которого ноги выпадают")
        if not basis.get("reproducible"):
            out.append(f"[НЕ ИЗМЕРЕНО] {day['cycle_date']}: {basis.get('reason')}")

    misses = observed(pop, "unmeasured_days", kind=list)
    if misses is None:
        # `… or []` склеил бы отчёт старого образца со здоровым: оба молчали бы, и
        # молчание читалось бы согласием (инв. #17).
        out.append("[НЕ ИЗМЕРЕНО] перечень неизмеренных дней: население не несёт ключа "
                   "`unmeasured_days` — пустым списком он НЕ подменяется")
    else:
        for miss in misses:
            out.append(f"[НЕ ИЗМЕРЕНО] {miss['cycle_date']}: {miss['reason']}")

    if pop.get("other_unchecked_days"):
        out.append(
            f"[ОПОРА] ещё {len(pop['other_unchecked_days'])} дн. "
            f"({', '.join(pop['other_unchecked_days'])}) судья пометил UNCHECKED по "
            f"ДРУГОЙ причине (нет форвардных дней / нет записанной цели) — к слепоте "
            f"входов они не относятся и в население этого прибора не входят")

    cross = doc.get("cross_axis") or {}
    own = observed(cross, "own_capital_degraded_days", kind=list)
    if not cross.get("measured"):
        out.append(f"[НЕ ИЗМЕРЕНО] сверка осей: {cross.get('reason')}")
    elif own is None:
        # `measured: True` без перечня — сверка НЕСОСТОЯВШАЯСЯ, а не «ноль дней».
        # Опереться на то, что ключ есть «по построению», значило бы поверить
        # построению вместо замера.
        out.append("[НЕ ИЗМЕРЕНО] сверка осей: сосед доложил `measured`, но перечня "
                   "деградировавших дней не несёт — пересечение не считается")
    else:
        mine = [d["cycle_date"] for d in (observed(doc, "per_day", kind=list) or [])]
        overlap = sorted(set(own) & set(mine))
        out.append(
            f"[ОСИ] сосед ADR-366 назвал деградировавшими {len(own)} дн. по "
            f"наблюдённости капитала САМОГО дня, судья отверг "
            f"{pop.get('refusals_on_unpriced_legs')} дн. по форвардным ставкам; "
            f"пересечение {len(overlap)} ({', '.join(overlap) or '—'}). Числа разные "
            f"потому, что вопросы разные, и ни одно не является поправкой к другому")

    den = doc.get("denominator") or {}
    if not den.get("measured"):
        out.append(f"[НЕ ИЗМЕРЕНО] знаменатель hit_rate: {den.get('reason')}")

    if not pop.get("accounting_identity_holds", True):
        out.append("[НЕ ИЗМЕРЕНО] тождество «измерено + не измерено == отказов на "
                   "входе» НЕ держится — день исчез молча, и числу верить нельзя")
    return out


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Порядок — порядок вопроса: население, ответ, дни."""
    out: List[str] = []
    pop = observed(doc, "population", kind=dict)
    # Ни одно число не подставляется: пропавший ключ обязан читаться как «не измерено»,
    # а не как ноль. `… or 0` здесь и был бы тем дефектом — отчёт старого образца молчал
    # бы ровно так же, как здоровый.
    refusals = None if pop is None else pop.get("refusals_on_unpriced_legs")
    measured = None if pop is None else pop.get("measured_days")
    out.append(f"   доля оборота, зависевшая от ненаблюдённой ноги (заказ #587/G6): "
               f"{doc.get('status')} · отказов "
               f"{'НЕ ИЗМЕРЕНО' if refusals is None else refusals} · измерено "
               f"{'НЕ ИЗМЕРЕНО' if measured is None else measured}")
    for line in (observed(doc, "findings", kind=list) or []):
        out.append(f"   {line}")
    if doc.get("advisory"):
        out.append(f"   {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[WARNING]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[ПО ДНЯМ]") or x.startswith("[ОПОРА]")
                    or x.startswith("[ОСИ]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=("доля предложенного оборота, зависевшая от ненаблюдённой ноги "
                     "(заказ #587/G6 приказа «Portfolio CIO»)"))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
