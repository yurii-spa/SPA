"""Смещён ли `hit_rate` систематически (заказ #541, ADR-295).

Заказ цикла #541 поставил вопрос ровно так. ADR-295 закрыл предыдущую ветку
отрицательным ответом («расширение записи решения НЕ двигает вердикт») и назвал
следствие, которое важнее самого ответа:

> **сегодняшний ``hit_rate`` = 1.0 — ПРОХОДЯЩИЙ критерий взвода — посчитан на том
> подмножестве дней, которое потолок дал оценить.** Дни без вердикта — это «не
> измерено», а не «HOLD был прав».

``hit_rate`` — не приборная величина. Это **критерий взвода** (``MIN_HIT_RATE``
= 0.60, мандат владельца ADR-067): по нему решается, можно ли переводить тень в
исполнение. Поэтому вопрос «смещён ли он» — вопрос о money-path, и отвечать на
него надо замером, а не рассуждением.

## Механизм, а не подозрение

``shadow_trigger_eval._evaluate_verdict`` судит день так:

* выгода ``benefit`` копится **только по тем forward-дням, которые удалось
  оценить** (``forward_days_checked``); день без живой ставки хотя бы у одной
  двигаемой ноги не оценивается — fail-CLOSED, и это верно;
* издержка ``cost_used`` списывается **целиком**, независимо от того, сколько
  дней удалось оценить;
* для ``HOLD`` исход = ``hit``, если ``net = benefit - cost <= 0``.

Отсюда арифметика, а не гипотеза: **всякое усечение forward-окна уменьшает
benefit, оставляя cost на месте, то есть двигает HOLD в сторону ``hit``.**

## Почему «систематически», а не «шумно»

Направление одинаково у ВСЕХ искажений ровно потому, что окно **сплошь
``HOLD``** (замер: 35 из 35). При ``HOLD`` исход ``hit`` получается из
*занижения* net, и все три оси занижают net. Появись в окне хоть один ``ACT``,
направление у него было бы ОБРАТНЫМ (``hit`` при ``net > 0``) и ошибки начали бы
частично гасить друг друга. Поэтому условие «окно сплошь HOLD» прибор **меряет и
печатает**, а не предполагает: это область действия утверждения, и она может
кончиться.

## Три оси, и ни одна поодиночке не ломает критерий

1. **A — усечение горизонта.** Экстраполяция benefit на полный горизонт по той
   же наблюдённой дневной ставке.
2. **B — база стоимости.** В том же репозитории лежит ИЗМЕРЕННАЯ поправка:
   ``data/rebalance_cost_evidence.json`` сверяет заряженный газ с наблюдённым.
   Берётся **только газовая подстановка** — она наблюдение; модель слиппеджа из
   того же артефакта НЕ берётся, потому что сам артефакт держит её не выше WARN
   («сверка слиппеджа — МОДЕЛЬ над наблюдённым TVL против литерала»). Числа
   прибор не выдумывает: нет артефакта или газ не измерен ⇒ ось ``UNMEASURED``.
3. **C — сама выборка.** ``hit_rate`` считается по ``scored``-дням; ``trivial`` и
   ``UNCHECKED`` в знаменатель не входят. Ось даёт **ГРАНИЦУ, а не оценку**:
   каждый ``UNCHECKED``-день засчитывается промахом. Это худший случай, и он
   назван худшим случаем — выдавать его за оценку значило бы изготовить находку
   из неизмеренного.

**Ответ заказу — в конъюнкции.** Каждая ось поодиночке оставляет критерий
проходящим; вместе они его роняют. Значит ``hit_rate`` не «немного неточен» — он
**не решается на имеющемся эвиденсе**: порог 0.60 лежит ВНУТРИ интервала,
который дают одинаково защитимые поправки. Прибор так и говорит, и это
CRITICAL — не потому, что HOLD был неправ (этого замер не утверждает), а потому
что критерий взвода предъявлен как ``PASS`` там, где честный ответ —
«не измерено».

## Отрицательный результат без положительного контроля не принимается

Правило ADR-295, и здесь оно нужно вдвойне: ось A даёт ЧЕСТНЫЙ НОЛЬ (0 из 15
дней), и без доказанной способности перевернуть день этот ноль был бы вакуумом.
Поэтому у каждой оси свой ОБЯЗАТЕЛЬНЫЙ контроль, и есть общий контроль на
ПАРИТЕТ: при нулевом возмущении пересчёт обязан воспроизвести исходы настоящего
``_evaluate_verdict`` бит в бит. Не сошлось ⇒ мерился не тот путь, и все числа
ниже недействительны. Любой контроль не сработал ⇒ прибор ОТКАЗЫВАЕТ статусом
``UNMEASURED``, а не докладывает «смещения нет».

**ADVISORY.** Прибор ничего не чинит и не предлагает чинить молча: ни
``_move_cost_usd``, ни ``TriggerParams``, ни ``MIN_HIT_RATE``, ни пороги
RiskPolicy v1.0, ни потолки концентрации, ни kill-switch, ни живой трек не
трогаются, капитал не двигается. Живое ``data/`` открывается на запись ровно
один раз — для собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.observation import observed as observed_field

log = logging.getLogger("spa.monitoring.hit_rate_selection_bias")

VERSION = "hit-rate-selection-bias-v1"
OUTPUT_FILENAME = "hit_rate_selection_bias.json"

COST_EVIDENCE_FILENAME = "rebalance_cost_evidence.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

AXIS_SHIFTS = "SHIFTS"
AXIS_NO_SHIFT = "NO_SHIFT"
AXIS_UNMEASURED = "UNMEASURED"

#: Множитель выгоды в контроле СПОСОБНОСТИ оси A. Число ПРИБОРА: оно ничего не
#: гейтит и в решение не попадает — им только доказывается, что положительный
#: результат на этой оси в принципе достижим (иначе ноль оси A вакуумен).
_CAPABILITY_BENEFIT_MULTIPLIER = 1000.0

#: Доля стоимости в контроле СПОСОБНОСТИ оси B: стоимость, обнулённая почти
#: полностью, ОБЯЗАНА перевернуть хотя бы один день. Тоже число прибора.
_CAPABILITY_COST_RATIO = 1e-9


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Пересчёт исхода под возмущением ───────────────────────────────────────────
# Правило исхода здесь ПОВТОРЕНО, и это осознанный риск: повтор может разойтись
# с оригиналом молча. Поэтому он закрыт контролем на ПАРИТЕТ (`_parity_control`),
# который при нулевом возмущении требует совпадения с настоящим
# `_evaluate_verdict` бит в бит по КАЖДОМУ дню. Звать оригинал напрямую нельзя:
# возмущение живёт внутри него (benefit копится в замкнутом цикле по forward-дням),
# и подменять его аргументы значило бы подменять историю, то есть отвечать на
# вопрос о ДРУГИХ данных вместо вопроса о ТЕХ ЖЕ данных под другой поправкой.
def _outcome_for(verdict: str, net: float) -> str:
    """Тот же приговор, что у `shadow_trigger_eval._evaluate_verdict`."""
    if verdict == "ACT":
        return "hit" if net > 0 else "miss"
    if verdict == "HOLD":
        return "miss" if net > 0 else "hit"
    return "UNCHECKED"


def _recount(scored: List[dict], *, horizon_days: int,
             extrapolate: bool, cost_ratio: float,
             benefit_multiplier: float = 1.0) -> List[dict]:
    """Исходы `scored`-дней под поправкой. Не трогает исходные строки."""
    out: List[dict] = []
    for r in scored:
        chk = r.get("forward_days_checked") or 0
        benefit_raw = observed_field(r, "benefit_usd_over_checked_days", kind=(int, float))
        cost_raw = observed_field(r, "cost_usd_used", kind=(int, float))
        if benefit_raw is None or cost_raw is None:
            # Ноль вместо ненаписанной выгоды занижает исход, ноль вместо
            # ненаписанных издержек — завышает: у подстановок РАЗНЫЙ знак, и обе
            # выглядели бы посчитанными. День без этих полей не оценивается вовсе
            # (инвариант #17); его уход виден по длине выдачи.
            continue
        benefit = float(benefit_raw)
        if extrapolate and chk:
            benefit = benefit * horizon_days / chk
        benefit *= benefit_multiplier
        cost = float(cost_raw) * cost_ratio
        net = benefit - cost
        out.append({
            "cycle_date": r.get("cycle_date"),
            "verdict": r.get("verdict"),
            "forward_days_checked": chk,
            "benefit_usd": round(benefit, 4),
            "cost_usd": round(cost, 4),
            "net_usd": round(net, 4),
            "outcome": _outcome_for(str(r.get("verdict")), net),
        })
    return out


def _hit_rate(rows: List[dict], extra_misses: int = 0) -> Optional[float]:
    denom = len(rows) + extra_misses
    if not denom:
        return None
    hits = sum(1 for r in rows if r["outcome"] == "hit")
    return round(hits / denom, 4)


def _flipped(base: List[dict], perturbed: List[dict]) -> List[str]:
    by_date = {r["cycle_date"]: r["outcome"] for r in base}
    return [r["cycle_date"] for r in perturbed
            if by_date.get(r["cycle_date"]) != r["outcome"]]


# ── Ось B: поправка стоимости берётся ИЗМЕРЕННОЙ, а не выдуманной ────────────
def _cost_ratio_from_evidence(data_dir: Path) -> Tuple[Optional[float], dict]:
    """Доля наблюдённой стоимости от заряженной — из `rebalance_cost_evidence`.

    Только ГАЗОВАЯ подстановка: она наблюдение (`observed_gas.measured`).
    Модель слиппеджа из того же артефакта НЕ берётся — сам артефакт держит её не
    выше WARN, и втащить её сюда значило бы поднять чужое допущение до
    наблюдения.
    """
    path = data_dir / COST_EVIDENCE_FILENAME
    prov: dict = {"source": f"data/{COST_EVIDENCE_FILENAME}", "basis": "gas_only"}
    if not path.exists():
        prov["reason"] = "артефакт стоимости отсутствует"
        return None, prov
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:  # noqa: BLE001
        prov["reason"] = f"артефакт стоимости нечитаем: {e}"
        return None, prov
    observed = observed_field(doc, "observed_gas", kind=dict)
    if observed is None:
        prov["reason"] = "в артефакте стоимости нет блока observed_gas"
        return None, prov
    if not observed.get("measured"):
        prov["reason"] = ("газ не измерен производителем: "
                          f"{observed.get('reason') or 'причина не названа'}")
        return None, prov
    sub = (doc.get("substitution") or {})
    ratio = sub.get("cost_ratio_observed_over_charged")
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        prov["reason"] = "в артефакте нет доли cost_ratio_observed_over_charged"
        return None, prov
    if not (0.0 < ratio <= 1.0):
        prov["reason"] = f"доля вне (0, 1]: {ratio}"
        return None, prov
    prov.update({
        "cost_ratio": ratio,
        "gas_usd_charged": sub.get("gas_usd_charged"),
        "gas_usd_observed": sub.get("gas_usd_observed"),
        "gas_ratio_charged_over_observed": sub.get("gas_ratio_charged_over_observed"),
        "generated_at": doc.get("generated_at"),
    })
    return ratio, prov


# ── Главный замер ─────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            cost_ratio: Optional[float] = None) -> dict:
    """Смещён ли `hit_rate` систематически. Детерминирован при данных файлах."""
    from spa_core.paper_trading import shadow_trigger_eval as ste

    data_dir = Path(data_dir)
    now = now or _utcnow()
    horizon = ste.DEFAULT_HORIZON_DAYS
    min_hit_rate = ste.MIN_HIT_RATE

    doc: dict = {
        "generated_at": now.isoformat(),
        "version": VERSION,
        "mode": "ADVISORY",
        "status": STATUS_UNMEASURED,
        "order": "заказ #541 (ADR-295): смещён ли hit_rate систематически",
        "findings": [],
        "advisory": (
            "пороги RiskPolicy v1.0, потолки концентрации, TriggerParams, "
            "MIN_HIT_RATE, _move_cost_usd и kill-switch НЕ трогаются — "
            "подстановка наблюдённой стоимости в решение и пересмотр критерия "
            "взвода это money-path и решение владельца"),
    }

    history, bad_lines = ste.load_history(data_dir)
    if not history:
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] журнал решений пуст — смещать нечего")
        doc["journal_rows"] = 0
        return doc

    rows = [ste._evaluate_verdict(rec, history[i + 1:], horizon)
            for i, rec in enumerate(history)]
    scored = [r for r in rows
              if (not r.get("trivial")) and r["outcome"] in ("hit", "miss")]
    unchecked = [r for r in rows if r["outcome"] == "UNCHECKED"]
    trivial = [r for r in rows if r.get("trivial")]

    verdict_mix: Dict[str, int] = {}
    for r in rows:
        verdict_mix[str(r.get("verdict"))] = verdict_mix.get(str(r.get("verdict")), 0) + 1
    all_hold = set(verdict_mix) == {"HOLD"}

    doc.update({
        "journal_rows": len(history),
        "corrupt_history_lines": bad_lines,
        "population": {
            "days_total": len(rows),
            "scored": len(scored),
            "trivial": len(trivial),
            "unchecked": len(unchecked),
            "scored_share_of_window": (round(len(scored) / len(rows), 4)
                                       if rows else None),
            "partial_among_scored": sum(
                1 for r in scored if r.get("counterfactual") == "PARTIAL"),
            "fully_checked_among_scored": sum(
                1 for r in scored if r.get("counterfactual") == "CHECKED"),
        },
        "verdict_mix": verdict_mix,
        "direction_is_uniform": all_hold,
        "params": {"horizon_days": horizon, "min_hit_rate": min_hit_rate},
    })

    if not scored:
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] ни одного оценённого дня — hit_rate не определён")
        return doc

    # ── Контроль на ПАРИТЕТ: нулевое возмущение обязано воспроизвести оригинал ──
    base = _recount(scored, horizon_days=horizon, extrapolate=False, cost_ratio=1.0)
    mismatched = [r["cycle_date"] for r, orig in zip(base, scored)
                  if r["outcome"] != orig["outcome"]]
    parity = {"passed": not mismatched, "days": len(base),
              "mismatched": mismatched}
    doc["parity_control"] = parity
    if not parity["passed"]:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] пересчёт разошёлся с настоящим _evaluate_verdict на "
            f"{len(mismatched)} дн. — мерился не тот путь, числам верить нельзя")
        return doc

    hit_rate_base = _hit_rate(base)
    doc["hit_rate_as_is"] = hit_rate_base

    # ── Ось A — усечение горизонта ───────────────────────────────────────────
    a_rows = _recount(scored, horizon_days=horizon, extrapolate=True, cost_ratio=1.0)
    a_flips = _flipped(base, a_rows)
    # контроль СПОСОБНОСТИ: выгода, при которой день обязан окупиться
    a_cap_rows = _recount(scored, horizon_days=horizon, extrapolate=True,
                          cost_ratio=1.0,
                          benefit_multiplier=_CAPABILITY_BENEFIT_MULTIPLIER)
    a_cap_flips = _flipped(base, a_cap_rows)
    axis_a = {
        "name": "усечение горизонта",
        "question": ("benefit копится по оценённым forward-дням, cost "
                     "списывается целиком — двигает ли это исход"),
        "hit_rate": _hit_rate(a_rows),
        "flipped_days": a_flips,
        "status": AXIS_SHIFTS if a_flips else AXIS_NO_SHIFT,
        "capability_control": {
            "passed": bool(a_cap_flips),
            "benefit_multiplier": _CAPABILITY_BENEFIT_MULTIPLIER,
            "flipped_days": a_cap_flips,
        },
        "median_forward_days_checked": sorted(
            r["forward_days_checked"] for r in base)[len(base) // 2],
    }
    if not axis_a["capability_control"]["passed"]:
        axis_a["status"] = AXIS_UNMEASURED
    doc["axis_a_horizon"] = axis_a

    # ── Ось B — база стоимости ───────────────────────────────────────────────
    ratio, cost_prov = ((cost_ratio, {"source": "аргумент вызова",
                                      "basis": "gas_only",
                                      "cost_ratio": cost_ratio})
                        if cost_ratio is not None
                        else _cost_ratio_from_evidence(data_dir))
    axis_b: dict = {
        "name": "база стоимости",
        "question": ("cost заряжен по литеральному газу; наблюдённый газ "
                     "измерен тем же репозиторием — двигает ли подстановка исход"),
        "provenance": cost_prov,
    }
    b_rows: Optional[List[dict]] = None
    if ratio is None:
        axis_b.update({"status": AXIS_UNMEASURED, "hit_rate": None,
                       "flipped_days": []})
    else:
        b_rows = _recount(scored, horizon_days=horizon, extrapolate=False,
                          cost_ratio=ratio)
        b_flips = _flipped(base, b_rows)
        b_cap_rows = _recount(scored, horizon_days=horizon, extrapolate=False,
                              cost_ratio=_CAPABILITY_COST_RATIO)
        b_cap_flips = _flipped(base, b_cap_rows)
        axis_b.update({
            "hit_rate": _hit_rate(b_rows),
            "flipped_days": b_flips,
            "status": AXIS_SHIFTS if b_flips else AXIS_NO_SHIFT,
            "capability_control": {
                "passed": bool(b_cap_flips),
                "cost_ratio": _CAPABILITY_COST_RATIO,
                "flipped_days": b_cap_flips,
            },
        })
        if not axis_b["capability_control"]["passed"]:
            axis_b["status"] = AXIS_UNMEASURED
    doc["axis_b_cost"] = axis_b

    # ── Ось C — сама выборка (ГРАНИЦА, не оценка) ────────────────────────────
    c_hit_rate = _hit_rate(base, extra_misses=len(unchecked))
    c_cap = (_hit_rate(base, extra_misses=len(unchecked) + 1) or 1.0) < (
        _hit_rate(base, extra_misses=len(unchecked)) or 0.0) if unchecked else (
        (_hit_rate(base, extra_misses=1) or 1.0) < (hit_rate_base or 0.0))
    axis_c = {
        "name": "выборка",
        "question": ("hit_rate считается по scored-дням; trivial и UNCHECKED в "
                     "знаменатель не входят — что даёт худший случай"),
        "kind": "BOUND",
        "note": ("ГРАНИЦА, а не оценка: каждый UNCHECKED-день засчитан промахом. "
                 "Замер не утверждает, что эти дни были промахами — он "
                 "утверждает, что они НЕ ИЗМЕРЕНЫ"),
        "excluded_unchecked": len(unchecked),
        "excluded_trivial": len(trivial),
        "hit_rate": c_hit_rate,
        "status": (AXIS_SHIFTS if (c_hit_rate is not None
                                   and hit_rate_base is not None
                                   and c_hit_rate < hit_rate_base)
                   else AXIS_NO_SHIFT),
        "capability_control": {"passed": bool(c_cap)},
    }
    if not c_cap:
        axis_c["status"] = AXIS_UNMEASURED
    doc["axis_c_selection"] = axis_c

    # ── Конъюнкция: все защитимые поправки разом ─────────────────────────────
    combined: dict = {"applied": ["A"], "kind": "BOUND"}
    if ratio is not None:
        ab_rows = _recount(scored, horizon_days=horizon, extrapolate=True,
                           cost_ratio=ratio)
        combined["applied"].append("B")
    else:
        ab_rows = a_rows
    combined["hit_rate_scored_only"] = _hit_rate(ab_rows)
    combined["hit_rate_with_unchecked_as_miss"] = _hit_rate(
        ab_rows, extra_misses=len(unchecked))
    combined["applied"].append("C")
    combined["flipped_days"] = _flipped(base, ab_rows)
    doc["combined"] = combined

    # ── Интервал и вердикт критерия ──────────────────────────────────────────
    candidates = [v for v in (
        hit_rate_base, axis_a["hit_rate"], axis_b.get("hit_rate"),
        axis_c["hit_rate"], combined["hit_rate_scored_only"],
        combined["hit_rate_with_unchecked_as_miss"]) if v is not None]
    lo, hi = min(candidates), max(candidates)
    threshold_inside = lo < min_hit_rate <= hi
    doc["hit_rate_interval"] = {
        "low": lo, "high": hi, "threshold": min_hit_rate,
        "threshold_inside_interval": threshold_inside,
        "note": ("интервал по одинаково защитимым поправкам; НЕ доверительный "
                 "интервал и не распределение"),
    }

    controls_ok = (parity["passed"]
                   and axis_a["status"] != AXIS_UNMEASURED
                   and axis_c["status"] != AXIS_UNMEASURED)
    if not controls_ok:
        doc["status"] = STATUS_UNMEASURED
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] обязательный контроль не сработал — "
            "отрицательный результат здесь вакуумен")
        return doc

    f = doc["findings"]
    f.append(
        f"[ОТВЕТ ЗАКАЗУ #541] hit_rate = {hit_rate_base} посчитан на "
        f"{len(scored)} дн. из {len(rows)} ({doc['population']['scored_share_of_window']:.1%} окна); "
        f"из них с усечённым forward-окном {doc['population']['partial_among_scored']}, "
        f"полностью оценённых {doc['population']['fully_checked_among_scored']}. "
        f"Медиана оценённых forward-дней {axis_a['median_forward_days_checked']} из {horizon}")

    if all_hold:
        f.append(
            f"[МЕХАНИЗМ] окно сплошь HOLD ({verdict_mix.get('HOLD')} из {len(rows)}), "
            f"а HOLD=hit при net<=0 ⇒ ВСЯКОЕ занижение net двигает исход в 'hit'. "
            f"Ошибки не гасят друг друга — это и значит «систематически». "
            f"Появление хоть одного ACT сузило бы область этого утверждения")
    else:
        f.append(
            f"[ЦЕНА] окно НЕ сплошь HOLD ({verdict_mix}) — направление искажений "
            f"перестало быть единым, утверждение о систематичности сужается")

    if threshold_inside:
        doc["status"] = STATUS_CRITICAL
        f.append(
            f"[CRITICAL] порог взвода {min_hit_rate} лежит ВНУТРИ интервала "
            f"[{lo}, {hi}], который дают одинаково защитимые поправки: "
            f"как есть {hit_rate_base} · ось A {axis_a['hit_rate']} · "
            f"ось B {axis_b.get('hit_rate')} · ось C(граница) {axis_c['hit_rate']} · "
            f"A+B {combined['hit_rate_scored_only']} · "
            f"A+B+C(граница) {combined['hit_rate_with_unchecked_as_miss']}. "
            f"Критерий предъявлен как PASS там, где честный ответ — «не измерено»: "
            f"замер НЕ утверждает, что HOLD был неправ, он утверждает, что "
            f"эвиденса не хватает, чтобы решить")
    else:
        doc["status"] = STATUS_WARNING
        f.append(
            f"[ЦЕНА] порог {min_hit_rate} вне интервала [{lo}, {hi}] — вердикт "
            f"критерия устойчив к названным поправкам, но сам hit_rate смещён")

    for axis, key in ((axis_a, "A"), (axis_b, "B"), (axis_c, "C")):
        if axis.get("status") == AXIS_UNMEASURED:
            f.append(f"[НЕ ИЗМЕРЕНО] ось {key} ({axis['name']}): "
                     f"{axis.get('provenance', {}).get('reason') or 'контроль не сработал'}")
        elif axis.get("status") == AXIS_NO_SHIFT:
            f.append(f"[КОНТРОЛЬ] ось {key} ({axis['name']}) НЕ двигает ни одного "
                     f"исхода — и это честный ноль: контроль способности "
                     f"сработал, положительный результат был достижим")

    return doc


# ── Отрисовка для шага 0-офис ─────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → оси → контроли → находки."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(f"   смещение hit_rate (заказ #541): {doc.get('status')} · "
               f"дней журнала {doc.get('journal_rows')} · "
               f"оценено {pop.get('scored')} из {pop.get('days_total')} "
               f"(trivial {pop.get('trivial')}, без вердикта {pop.get('unchecked')})")
    par = doc.get("parity_control") or {}
    if par and not par.get("passed"):
        out.append("   [НЕ ИЗМЕРЕНО] контроль паритета не прошёл — "
                   "числам ниже верить нельзя")
    iv = observed_field(doc, "hit_rate_interval", kind=dict)
    if iv:
        out.append(f"   hit_rate: как есть {doc.get('hit_rate_as_is')} · "
                   f"интервал по защитимым поправкам [{iv.get('low')}, {iv.get('high')}] · "
                   f"порог взвода {iv.get('threshold')} "
                   f"{'ВНУТРИ интервала' if iv.get('threshold_inside_interval') else 'вне интервала'}")
    for key, label in (("axis_a_horizon", "A"), ("axis_b_cost", "B"),
                       ("axis_c_selection", "C")):
        ax = doc.get(key) or {}
        if not ax:
            continue
        cap = ax.get("capability_control") or {}
        out.append(f"   ось {label} ({ax.get('name')}): {ax.get('status')} · "
                   f"hit_rate {ax.get('hit_rate')} · "
                   f"перевернулось {len(ax.get('flipped_days') or [])} дн."
                   f"{' · контроль способности сработал' if cap.get('passed') else ' · КОНТРОЛЬ НЕ СРАБОТАЛ'}"
                   f"{' · ГРАНИЦА, не оценка' if ax.get('kind') == 'BOUND' else ''}")
    comb = doc.get("combined") or {}
    if comb:
        out.append(f"   конъюнкция {'+'.join(comb.get('applied') or [])}: "
                   f"по оценённым {comb.get('hit_rate_scored_only')} · "
                   f"с UNCHECKED как промахами (ГРАНИЦА) "
                   f"{comb.get('hit_rate_with_unchecked_as_miss')}")
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
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
        "warn": sum(1 for x in findings if x.startswith("[ЦЕНА")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[КОНТРОЛЬ]") or x.startswith("[МЕХАНИЗМ]")),
        # «не измерено» считается ОТДЕЛЬНО: растворив его в нулях, мы сделали бы
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
        description="смещён ли hit_rate систематически (заказ #541)")
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
