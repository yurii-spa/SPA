"""observation_period_census.py — §39 ТЗ «Portfolio CIO»: «Observation period».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §39::

    Observation period
    Перед реальным capital execution Portfolio CIO должен пройти shadow observation.
    Duration определить на основании доступности данных и existing release process.
    Не использовать только количество дней как критерий.
    Нужен минимальный набор рыночных событий:
    APY spike; stable opportunity; high gas; low gas; opportunity disappearing;
    incoming capital; risk block; no-action period.

Событий **ВОСЕМЬ**, условий ТРИ (до денег — тень · срок по доступности данных и
релизному процессу · не только дни). Прибор сверяет перечень и обе границы раздела с
карточкой (`parity`).

Что УЖЕ есть и что измеряется
=============================
Период наблюдения у системы ЕСТЬ — это журнал тени ADR-060
(`data/allocation_rationale_history.jsonl`, с 06.08) и критерий взвода ADR-067
(`shadow_trigger_eval.evaluate_window`: ≥30 дней · hit-rate ≥ 0,6 · net benefit > 0,
артефакт `data/shadow_trigger_evaluation.json`). ADR-228 измерил, что третий критерий
НЕДОСТИЖИМ ожиданием (ACT не было ни разу). Прибор НЕ строит второй период и НЕ
назначает своих порогов: он спрашивает у ЖИВОГО периода, какие из восьми событий
владельца в нём уже случились — и считает ли их критерий взвода хоть одним полем.

Пять осей замера
================
* **A — паритет.** Перечень событий, три условия и обе границы раздела — с карточки.
* **B — событие → наблюдение.** У КАЖДОГО события объявлена ДВЕРЬ (`EVENT_DOORS`): в
  каком входе оно видно и чьим порогом судится. Пороги — СИСТЕМЫ, не прибора:
  всплеск и «стоячая возможность» — полосой `required_gain_pp` самой записи
  (ADR-060, гейт `gain_above_band`); дорогой/дешёвый газ — режимом
  `gas_price_agent.regime_for` (≤p25 · ≥p75 собственной истории, причинно: только
  ПРЕДШЕСТВУЮЩИЕ чтения); длина «периода» — горизонтом судьи
  `shadow_trigger_eval.DEFAULT_HORIZON_DAYS`; risk block — гейтом
  `target_fully_evidenced`, списком `apy_unevidenced` и ответом RiskPolicy в записи.
  Род: `observed` (≥1 день с названным доказательством) · `never_observed` (дверь
  есть, вход есть, события не было) · `unmeasured` (входа нет либо детектор не
  различает — см. контроль).
* **C — контроль детекторов.** Каждый детектор гоняется на ДВУХ синтетических сценах —
  с событием и без; детектор, срабатывающий одинаково на обеих, ничего не различает,
  и его событие получает род `unmeasured`, а не `observed`. Урок #1101: контроль — о
  ЧУВСТВИТЕЛЬНОСТИ предиката, не о «ответы различаются».
* **D — критерий срока.** Владелец: «не только количество дней». Прибор читает ИМЕНА
  критериев живого артефакта взвода и спрашивает, есть ли среди них покрытие событий:
  `events_in_criterion` · `days_and_outcomes_only` (дни + исходы, событий нет — так
  сегодня) · `days_only` · `absent` · `unmeasured`. Вердикт ADR-228 (`arming_blockade`)
  переносится INFO, не пересчитывается.
* **E — доступность данных и рост.** Окно каждого входа (первая/последняя дата, дней)
  печатается — владелец велел определять срок «на основании доступности данных».
  У события, которого не было, спрашивается, МОЖЕТ ЛИ оно ещё случиться: вход живой
  (последняя дата не старше горизонта от `now`) ⇒ `can_grow`, вход остановился ⇒
  `cannot_grow`; у `incoming capital` отдельно печатается число различных значений
  капитала за весь период (одно — значит взносов в бумажной книге не было ни разу).

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): журнал, историю газа и артефакт взвода — как есть,
ни одно число не вычисляется заново (третье место для чисел запрещено —
`.claude/rules/site-numbers.md`). Срок наблюдения НЕ назначает и «достаточно/нет» НЕ
говорит — это решение владельца по предмету №1 (движение денег), прибор лишь
показывает, какие события период уже содержит. Карточку владельцу не заводит.
Релизный процесс (§40) — следующий раздел ТЗ и здесь не измеряется.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import gas_price_agent as gpa
from spa_core.paper_trading import shadow_trigger_eval as ste
from spa_core.utils.observation import observed as observed_field
from spa_core.utils.observation import observed_number

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/observation_period_census.json"
CARD_REL = smc.CARD_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "39. Observation period"
NEXT_SECTION_HEAD = "40. Release stages"
OWNER_LINE_BEFORE = "Перед реальным capital execution Portfolio CIO должен пройти shadow observation."
OWNER_LINE_DURATION = "Duration определить на основании доступности данных и existing release process."
OWNER_LINE_NOT_DAYS_ONLY = "Не использовать только количество дней как критерий."
OWNER_EVENTS_LEAD = "Нужен минимальный набор рыночных событий:"
OWNER_EVENTS: Tuple[str, ...] = (
    "APY spike",
    "stable opportunity",
    "high gas",
    "low gas",
    "opportunity disappearing",
    "incoming capital",
    "risk block",
    "no-action period",
)
OWNER_EVENTS_DECLARED = 8

#: Заказ G972 п. 1 назвал предмет и границы (`sed -n '1247,1300p'`, вторая граница —
#: §40) и велел пересчитать входы своим глазом; числа событий он не называл — сдвиг не
#: применим, и это печатается отдельно от «назвал верно».
ORDER_G972_NAMED: Dict[str, Any] = {"events": None, "tail_read": True}

EVENT_KINDS: Tuple[str, ...] = ("observed", "never_observed", UNMEASURED)
CONTROL_KINDS: Tuple[str, ...] = ("discriminates", "indiscriminate", UNMEASURED)
CRITERION_KINDS: Tuple[str, ...] = ("events_in_criterion", "days_and_outcomes_only", "days_only",
                                    "absent", UNMEASURED)
GROWTH_KINDS: Tuple[str, ...] = ("can_grow", "cannot_grow", UNMEASURED)

HISTORY_FILE = ste.HISTORY_FILENAME
GAS_FILE = "gas_price_history.json"
BASE_GAS_FILE = "base_gas_history.json"
EVAL_FILE = ste.EVAL_FILENAME
INPUT_FILES: Tuple[str, ...] = (HISTORY_FILE, GAS_FILE, BASE_GAS_FILE, EVAL_FILE)

#: Длина «периода» (стоячая возможность · период без действий) — горизонт судьи тени:
#: возможность, пережившая окно, за которое судится вердикт, и есть стоячая. Порог
#: СИСТЕМЫ, импортирован, не назначен.
RUN_DAYS: int = int(ste.DEFAULT_HORIZON_DAYS)
#: Сеть, по которой судится газ: книга Conservative стоит на Ethereum-протоколах.
GAS_CHAIN = "ethereum"

#: Ось B — объявление дверей: где событие видно и чьим порогом судится.
EVENT_DOORS: Dict[str, Dict[str, str]] = {
    "APY spike": {"input": HISTORY_FILE, "field": "apy_evidenced_pct",
                  "threshold": "подъём ставки протокола за сутки ≥ required_gain_pp записи (полоса ADR-060)",
                  "door": "spa_core.paper_trading.allocation_rationale · гейт gain_above_band"},
    "stable opportunity": {"input": HISTORY_FILE, "field": "gain_pp / required_gain_pp",
                           "threshold": f"gain_pp ≥ required_gain_pp {RUN_DAYS} календарных дней подряд "
                                        f"(горизонт судьи shadow_trigger_eval.DEFAULT_HORIZON_DAYS)",
                           "door": "spa_core.paper_trading.shadow_trigger_eval"},
    "high gas": {"input": GAS_FILE, "field": f"history.{GAS_CHAIN}[].gwei",
                 "threshold": f"медиана live-чтений дня в режиме `expensive` (≥p{gpa.EXPENSIVE_PCTL:g} "
                              f"ПРЕДШЕСТВУЮЩЕЙ истории, ≥{gpa.MIN_HISTORY_FOR_REGIME} чтений)",
                 "door": "spa_core.monitoring.gas_price_agent.regime_for"},
    "low gas": {"input": GAS_FILE, "field": f"history.{GAS_CHAIN}[].gwei",
                "threshold": f"медиана live-чтений дня в режиме `cheap` (≤p{gpa.CHEAP_PCTL:g} "
                             f"ПРЕДШЕСТВУЮЩЕЙ истории, ≥{gpa.MIN_HISTORY_FOR_REGIME} чтений)",
                "door": "spa_core.monitoring.gas_price_agent.regime_for"},
    "opportunity disappearing": {"input": HISTORY_FILE, "field": "target_positions ∩ apy_evidenced_pct",
                                 "threshold": "протокол в цели дня i с живой ставкой — без ставки на день i+1",
                                 "door": "spa_core.paper_trading.allocation_rationale (apy_unevidenced)"},
    "incoming capital": {"input": HISTORY_FILE, "field": "capital_usd",
                         "threshold": "capital_usd дня i+1 > capital_usd дня i",
                         "door": "spa_core.paper_trading.allocation_rationale"},
    "risk block": {"input": HISTORY_FILE, "field": "gates.target_fully_evidenced · apy_unevidenced · "
                                                   "admissible_trim.policy.approved",
                   "threshold": "гейт отказал, либо список непустой, либо RiskPolicy ответила approved=False",
                   "door": "spa_core.paper_trading.shadow_trigger_eval.gate_state · RiskPolicy v1.0"},
    "no-action period": {"input": HISTORY_FILE, "field": "verdict · gain_pp / required_gain_pp",
                         "threshold": f"HOLD при gain_pp < required_gain_pp {RUN_DAYS} календарных дней подряд",
                         "door": "spa_core.paper_trading.shadow_trigger_eval"},
}

#: Ось D — какие имена критерия читались бы как «покрытие событий». Ни одного нет —
#: это и есть замер; появится — род станет `events_in_criterion`.
EVENT_CRITERION_MARKERS: Tuple[str, ...] = ("event", "scenario", "scene", "coverage", "regime")
DAYS_CRITERION_NAMES: Tuple[str, ...] = ("observation_days",)

#: Входы риска записи, которые читаются как «risk block» (ось B). Перечень ЗАМКНУТ.
RISK_GATES: Tuple[str, ...] = ("target_fully_evidenced",)

# Сцены контроля — литералы сцены, не пороги системы.
_A, _B = "proto_a", "proto_b"
SCENE_CAPITAL = 100_000.0
SCENE_REQUIRED_PP = 0.5
SCENE_DAYS = RUN_DAYS + 2


# ───────────────────────────── чтение карточки / паритет ──────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница {NEXT_SECTION_HEAD!r} — "
                      f"перечень не ограничен, и счёт по нему был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _events_after(body: List[str], lead: str) -> Optional[List[str]]:
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if not s:
            continue
        if s == "⸻":
            break
        out.append(s.rstrip(";.").strip())
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = smc._read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {
        "measured": True,
        "events": _events_after(body, OWNER_EVENTS_LEAD),
        "before_line_present": OWNER_LINE_BEFORE in stripped,
        "duration_line_present": OWNER_LINE_DURATION in stripped,
        "not_days_only_line_present": OWNER_LINE_NOT_DAYS_ONLY in stripped,
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    if not parsed.get("measured"):
        return {"agrees": None, "parsed": parsed, "mismatches": []}
    mism: List[str] = []
    if parsed["events"] is None:
        mism.append(f"в разделе нет строки {OWNER_EVENTS_LEAD!r}")
    elif list(parsed["events"]) != list(OWNER_EVENTS):
        mism.append(f"события в карточке {parsed['events']} ≠ объявленным {list(OWNER_EVENTS)}")
    if not parsed["before_line_present"]:
        mism.append("в разделе нет строки «до денег — тень»")
    if not parsed["duration_line_present"]:
        mism.append("в разделе нет строки о сроке (доступность данных · релизный процесс)")
    if not parsed["not_days_only_line_present"]:
        mism.append("в разделе нет строки «не только количество дней»")
    return {"agrees": not mism, "parsed": parsed, "mismatches": mism}


# ───────────────────────────── входы ──────────────────────────────────────────

def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def load_days(data_dir: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], int]:
    """Журнал ADR-060 → ОДНА строка на дату (последний прогон дня — как у критерия взвода).

    Порядок — у ``shadow_trigger_eval.load_history`` (та же дверь, что у взвода).
    Возврат ``(дни, причина, битых строк)``; журнала нет ⇒ ``(None, причина, 0)``.
    """
    path = Path(data_dir) / HISTORY_FILE
    if not path.exists():
        return None, f"журнала {HISTORY_FILE} в {data_dir} нет — наблюдать нечего", 0
    try:
        records, bad = ste.load_history(Path(data_dir))
    except Exception as exc:  # noqa: BLE001 — отказ читателя есть исход, не молчание
        return None, f"журнал не прочитан: {type(exc).__name__}: {exc}", 0
    if not records:
        return None, f"журнал {HISTORY_FILE} пуст (битых строк {bad})", bad
    by_date: Dict[str, dict] = {}
    for rec in records:
        day = smc._date_of(rec.get("cycle_date"))
        if day is None:
            continue
        by_date[day] = rec
    days: List[Dict[str, Any]] = []
    for day in sorted(by_date):
        rec = by_date[day]
        trim = observed_field(rec, "admissible_trim", kind=dict)
        policy = observed_field(trim, "policy", kind=dict) if trim is not None else None
        days.append({
            "date": day,
            "apy": observed_field(rec, "apy_evidenced_pct", kind=dict),
            "unevidenced": observed_field(rec, "apy_unevidenced", kind=list),
            "gain_pp": observed_number(rec, "gain_pp"),
            "required_gain_pp": observed_number(rec, "required_gain_pp"),
            "capital_usd": observed_number(rec, "capital_usd"),
            "target": observed_field(rec, "target_positions", kind=dict),
            "current": observed_field(rec, "current_positions", kind=dict),
            "verdict": rec.get("verdict"),
            "gates": ste.gate_state(rec)[0],
            "policy_approved": (policy.get("approved") if isinstance(policy, dict) else None),
        })
    if not days:
        return None, "ни одна строка журнала не несёт cycle_date", bad
    return days, None, bad


def load_gas_days(data_dir: str, chain: str = GAS_CHAIN) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """История газа → по дням: live-чтения (gwei) и число чтений без числа (`unchecked`)."""
    doc, why = smc._read_json(Path(data_dir) / GAS_FILE)
    if doc is None:
        return None, f"история газа не прочитана: {why}"
    history = observed_field(doc, "history", kind=dict)
    if history is None:
        return None, f"в {GAS_FILE} нет раздела history"
    readings = observed_field(history, chain, kind=list)
    if readings is None:
        return None, f"в истории газа нет сети {chain!r} (есть: {sorted(history)})"
    by_day: Dict[str, Dict[str, Any]] = {}
    for r in readings:
        day = smc._date_of(r.get("ts"))
        if day is None:
            continue
        row = by_day.setdefault(day, {"date": day, "live_gwei": [], "unchecked": 0})
        gwei = observed_number(r, "gwei")
        if r.get("source") == gpa.LIVE and gwei is not None:
            row["live_gwei"].append(gwei)
        else:
            row["unchecked"] += 1
    if not by_day:
        return None, f"история газа сети {chain!r} пуста"
    return [by_day[d] for d in sorted(by_day)], None


def load_base_gas(data_dir: str) -> Dict[str, Any]:
    doc, why = smc._read_json(Path(data_dir) / BASE_GAS_FILE)
    if doc is None:
        return {"measured": False, "reason": f"{BASE_GAS_FILE} не прочитан: {why}"}
    rows = observed_field(doc, "recent_readings", kind=list)
    if rows is None:
        return {"measured": False, "reason": f"в {BASE_GAS_FILE} нет recent_readings"}
    dates = sorted(d for d in (smc._date_of(r.get("date")) for r in rows) if d)
    above = sum(1 for r in rows if r.get("above_threshold") is True)
    return {"measured": True, "days": len(dates), "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None, "above_threshold_days": above}


# ───────────────────────────── ось B: детекторы ───────────────────────────────

def _consecutive(a: str, b: str) -> bool:
    da, db = _parse_date(a), _parse_date(b)
    return da is not None and db is not None and (db - da).days == 1


def detect_apy_spike(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Подъём ставки протокола за сутки ≥ полосы записи (`required_gain_pp` дня i+1)."""
    hits: List[Dict[str, Any]] = []
    for i in range(1, len(days)):
        d0, d1 = days[i - 1], days[i]
        if d0["apy"] is None or d1["apy"] is None or d1["required_gain_pp"] is None:
            continue
        band = d1["required_gain_pp"]
        for p in sorted(set(d0["apy"]) & set(d1["apy"])):
            a0, a1 = d0["apy"][p], d1["apy"][p]
            if not (isinstance(a0, (int, float)) and isinstance(a1, (int, float))):
                continue
            if a1 - a0 >= band:
                reverted = None
                if i + 1 < len(days) and days[i + 1]["apy"] is not None and p in days[i + 1]["apy"]:
                    a2 = days[i + 1]["apy"][p]
                    reverted = isinstance(a2, (int, float)) and (a1 - a2) >= band
                hits.append({"date": d1["date"], "protocol": p, "from_pct": round(a0, 4), "to_pct": round(a1, 4),
                             "band_pp": band, "reverted_next_day": reverted})
    return {"days": sorted({h["date"] for h in hits}), "evidence": hits}


def _runs(days: List[Dict[str, Any]], pred: Callable[[Dict[str, Any]], Optional[bool]],
          min_len: int) -> Dict[str, Any]:
    """Календарно-непрерывные серии дней, на которых ``pred`` истинен; ``None`` рвёт серию."""
    all_runs: List[Dict[str, Any]] = []
    cur: List[str] = []

    def _flush() -> None:
        if cur:
            all_runs.append({"start": cur[0], "end": cur[-1], "days": len(cur)})

    for d in days:
        ok = pred(d)
        joined = bool(cur) and _consecutive(cur[-1], d["date"])
        if ok is True and (not cur or joined):
            cur.append(d["date"])
        else:
            _flush()
            cur = [d["date"]] if ok is True else []
    _flush()
    runs = [r for r in all_runs if r["days"] >= min_len]
    # Самая долгая серия считается по ВСЕМ сериям, включая короче порога: «0» при
    # наличии шестидневной серии читалось бы как «предложения над полосой не было вовсе».
    longest = max((r["days"] for r in all_runs), default=0)
    return {"days": sorted({day for r in runs for day in _span(r["start"], r["end"])}),
            "evidence": runs, "longest_run_days": longest, "min_run_days": min_len,
            "runs_total": len(all_runs)}


def _span(start: str, end: str) -> List[str]:
    a, b = _parse_date(start), _parse_date(end)
    if a is None or b is None:
        return [start]
    return [(a + dt.timedelta(days=k)).isoformat() for k in range((b - a).days + 1)]


def _material(d: Dict[str, Any]) -> Optional[bool]:
    if d["gain_pp"] is None or d["required_gain_pp"] is None:
        return None
    return d["gain_pp"] >= d["required_gain_pp"]


def detect_stable_opportunity(days: List[Dict[str, Any]], run_days: int = RUN_DAYS) -> Dict[str, Any]:
    """Предложение тюнера над полосой ``run_days`` календарных дней подряд."""
    return _runs(days, _material, run_days)


def detect_no_action_period(days: List[Dict[str, Any]], run_days: int = RUN_DAYS) -> Dict[str, Any]:
    """HOLD без существенного предложения ``run_days`` календарных дней подряд."""
    def quiet(d: Dict[str, Any]) -> Optional[bool]:
        m = _material(d)
        if m is None:
            return None
        return (not m) and d["verdict"] == "HOLD"
    return _runs(days, quiet, run_days)


def detect_opportunity_disappearing(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Протокол в ЦЕЛИ дня i с живой ставкой — без ставки на день i+1."""
    hits: List[Dict[str, Any]] = []
    for i in range(1, len(days)):
        d0, d1 = days[i - 1], days[i]
        if d0["apy"] is None or d1["apy"] is None or d0["target"] is None:
            continue
        for p, amount in sorted(d0["target"].items()):
            if isinstance(amount, (int, float)) and amount > 0 and p in d0["apy"] and p not in d1["apy"]:
                hits.append({"date": d1["date"], "protocol": p, "target_usd": amount,
                             "last_rate_pct": d0["apy"][p]})
    return {"days": sorted({h["date"] for h in hits}), "evidence": hits}


def detect_incoming_capital(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    hits: List[Dict[str, Any]] = []
    for i in range(1, len(days)):
        c0, c1 = days[i - 1]["capital_usd"], days[i]["capital_usd"]
        if c0 is None or c1 is None:
            continue
        if c1 > c0:
            hits.append({"date": days[i]["date"], "from_usd": c0, "to_usd": c1})
    distinct = sorted({d["capital_usd"] for d in days if d["capital_usd"] is not None})
    return {"days": sorted({h["date"] for h in hits}), "evidence": hits, "distinct_capital_values": distinct}


def detect_risk_block(days: List[Dict[str, Any]], risk_gates: Sequence[str] = RISK_GATES) -> Dict[str, Any]:
    hits: List[Dict[str, Any]] = []
    for d in days:
        doors: List[str] = []
        if d["gates"] is not None:
            doors += [f"gate:{g}" for g in risk_gates if d["gates"].get(g) is False]
        if d["unevidenced"]:
            doors.append(f"apy_unevidenced:{sorted(d['unevidenced'])}")
        if d["policy_approved"] is False:
            doors.append("risk_policy:approved=False")
        if doors:
            hits.append({"date": d["date"], "doors": doors})
    return {"days": sorted({h["date"] for h in hits}), "evidence": hits}


def _gas_regimes(gas_days: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Режим КАЖДОГО дня у двери системы, причинно: история — только предшествующие live-чтения."""
    out: List[Dict[str, Any]] = []
    history: List[float] = []
    for g in gas_days:
        live = g["live_gwei"]
        if not live:
            out.append({"date": g["date"], "regime": gpa.REGIME_UNMEASURED, "unchecked": g["unchecked"]})
        else:
            med = statistics.median(live)
            verdict = gpa.regime_for(history, {"source": gpa.LIVE, "gwei": med})
            out.append({"date": g["date"], "regime": verdict["regime"], "gwei": round(med, 6),
                        "percentile": verdict.get("percentile"), "history_n": len(history),
                        "unchecked": g["unchecked"]})
        history.extend(live)
    return out


def detect_gas_regime(gas_days: List[Dict[str, Any]], regime: str) -> Dict[str, Any]:
    rows = _gas_regimes(gas_days)
    hits = [r for r in rows if r["regime"] == regime]
    tally: Dict[str, int] = {}
    for r in rows:
        tally[r["regime"]] = tally.get(r["regime"], 0) + 1
    return {"days": [h["date"] for h in hits], "evidence": hits, "regime_tally": tally}


# ───────────────────────────── ось C: контроль детекторов ─────────────────────

def _scene_day(i: int, *, apy: Dict[str, float], gain_pp: float, capital: float = SCENE_CAPITAL,
               target: Optional[Dict[str, float]] = None, unevidenced: Optional[List[str]] = None,
               gate_ok: bool = True, policy_ok: bool = True) -> Dict[str, Any]:
    day = (dt.date(2000, 1, 1) + dt.timedelta(days=i)).isoformat()   # FROZEN-DATE-OK: literal is the scene's own calendar origin, never compared with wall-clock
    return {"date": day, "apy": dict(apy), "unevidenced": list(unevidenced or []), "gain_pp": gain_pp,
            "required_gain_pp": SCENE_REQUIRED_PP, "capital_usd": capital,
            "target": dict(target if target is not None else {_A: 60_000.0, _B: 40_000.0}),
            "current": {_A: 60_000.0, _B: 40_000.0}, "verdict": "HOLD",
            "gates": {g: gate_ok for g in RISK_GATES}, "policy_approved": policy_ok}


def _flat_scene(n: int = SCENE_DAYS, *, gain_pp: float = 0.1) -> List[Dict[str, Any]]:
    return [_scene_day(i, apy={_A: 4.0, _B: 5.0}, gain_pp=gain_pp) for i in range(n)]


def _control(name: str, with_event: Any, without_event: Any, detector: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        fires_with = bool(detector(with_event)["days"])
        fires_without = bool(detector(without_event)["days"])
    except Exception as exc:  # noqa: BLE001 — упавший детектор ничего не различает
        return {"event": name, "kind": UNMEASURED, "reason": f"детектор упал: {type(exc).__name__}: {exc}"}
    kind = "discriminates" if (fires_with and not fires_without) else "indiscriminate"
    return {"event": name, "kind": kind, "fires_with_event": fires_with, "fires_without_event": fires_without}


def _gas_scene(spike: Optional[str]) -> List[Dict[str, Any]]:
    n_hist = gpa.MIN_HISTORY_FOR_REGIME
    days: List[Dict[str, Any]] = []
    # ровная история: достаточно чтений, чтобы дверь СУДИЛА режим
    for i in range(3):
        days.append({"date": (dt.date(2000, 1, 1) + dt.timedelta(days=i)).isoformat(),   # FROZEN-DATE-OK: scene calendar origin
                     "live_gwei": [1.0 + 0.01 * (k % 5) for k in range(n_hist)], "unchecked": 0})
    last = {"date": (dt.date(2000, 1, 1) + dt.timedelta(days=3)).isoformat(),   # FROZEN-DATE-OK: scene calendar origin
            "live_gwei": [1.02] * 4, "unchecked": 0}
    if spike == "high":
        last["live_gwei"] = [10.0] * 4
    elif spike == "low":
        last["live_gwei"] = [0.1] * 4
    days.append(last)
    return days


def control_detectors() -> Dict[str, Dict[str, Any]]:
    """Каждый детектор — на сцене С событием и БЕЗ. Одинаковый ответ = ничего не различает."""
    flat = _flat_scene()
    spike = _flat_scene()
    spike[3]["apy"][_A] = 4.0 + SCENE_REQUIRED_PP * 2
    stable = [_scene_day(i, apy={_A: 4.0, _B: 5.0}, gain_pp=SCENE_REQUIRED_PP * 2) for i in range(SCENE_DAYS)]
    short_stable = _flat_scene()
    for d in short_stable[:RUN_DAYS - 1]:
        d["gain_pp"] = SCENE_REQUIRED_PP * 2
    vanish = _flat_scene()
    for d in vanish[4:]:
        d["apy"].pop(_B)
    deposit = _flat_scene()
    for d in deposit[4:]:
        d["capital_usd"] = SCENE_CAPITAL + 10_000.0
    blocked = _flat_scene()
    blocked[2]["gates"] = {g: False for g in RISK_GATES}
    quiet = _flat_scene()
    busy = [_scene_day(i, apy={_A: 4.0, _B: 5.0}, gain_pp=SCENE_REQUIRED_PP * 2) for i in range(SCENE_DAYS)]
    return {
        "APY spike": _control("APY spike", spike, flat, detect_apy_spike),
        "stable opportunity": _control("stable opportunity", stable, short_stable, detect_stable_opportunity),
        "high gas": _control("high gas", _gas_scene("high"), _gas_scene(None),
                             lambda g: detect_gas_regime(g, gpa.REGIME_EXPENSIVE)),
        "low gas": _control("low gas", _gas_scene("low"), _gas_scene(None),
                            lambda g: detect_gas_regime(g, gpa.REGIME_CHEAP)),
        "opportunity disappearing": _control("opportunity disappearing", vanish, flat, detect_opportunity_disappearing),
        "incoming capital": _control("incoming capital", deposit, flat, detect_incoming_capital),
        "risk block": _control("risk block", blocked, flat, detect_risk_block),
        "no-action period": _control("no-action period", quiet, busy, detect_no_action_period),
    }


# ───────────────────────────── ось B: замер на живых входах ───────────────────

def measure_events(days: Optional[List[Dict[str, Any]]], days_why: Optional[str],
                   gas_days: Optional[List[Dict[str, Any]]], gas_why: Optional[str],
                   controls: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    detectors: Dict[str, Tuple[str, Callable[[], Dict[str, Any]]]] = {
        "APY spike": ("journal", lambda: detect_apy_spike(days or [])),
        "stable opportunity": ("journal", lambda: detect_stable_opportunity(days or [])),
        "high gas": ("gas", lambda: detect_gas_regime(gas_days or [], gpa.REGIME_EXPENSIVE)),
        "low gas": ("gas", lambda: detect_gas_regime(gas_days or [], gpa.REGIME_CHEAP)),
        "opportunity disappearing": ("journal", lambda: detect_opportunity_disappearing(days or [])),
        "incoming capital": ("journal", lambda: detect_incoming_capital(days or [])),
        "risk block": ("journal", lambda: detect_risk_block(days or [])),
        "no-action period": ("journal", lambda: detect_no_action_period(days or [])),
    }
    out: Dict[str, Dict[str, Any]] = {}
    for event in OWNER_EVENTS:
        source, fn = detectors[event]
        row: Dict[str, Any] = {"door": dict(EVENT_DOORS[event]), "source": source}
        ctl = controls.get(event) or {"kind": UNMEASURED, "reason": "контроля для события нет"}
        row["control"] = ctl["kind"]
        if source == "journal" and days is None:
            row.update(kind=UNMEASURED, reason=days_why or "журнала нет")
        elif source == "gas" and gas_days is None:
            row.update(kind=UNMEASURED, reason=gas_why or "истории газа нет")
        elif ctl["kind"] != "discriminates":
            row.update(kind=UNMEASURED,
                       reason=f"детектор не различает сцену с событием и без ({ctl['kind']}: "
                              f"{ctl.get('reason') or ctl}) — его «наблюдено» ничего бы не значило")
        else:
            got = fn()
            n_input = len(gas_days or []) if source == "gas" else len(days or [])
            row.update(kind="observed" if got["days"] else "never_observed",
                       days_with_event=len(got["days"]), input_days=n_input,
                       first=got["days"][0] if got["days"] else None,
                       last=got["days"][-1] if got["days"] else None,
                       evidence=got["evidence"][:12], evidence_total=len(got["evidence"]))
            for k in ("longest_run_days", "min_run_days", "distinct_capital_values", "regime_tally"):
                if k in got:
                    row[k] = got[k]
            if event == "APY spike" and got["evidence"]:
                row["reverted_next_day"] = sum(1 for e in got["evidence"] if e.get("reverted_next_day") is True)
                row["persisted_or_unjudged"] = len(got["evidence"]) - row["reverted_next_day"]
        out[event] = row
    return out


# ───────────────────────────── ось D: критерий срока ──────────────────────────

def measure_criterion(data_dir: str) -> Dict[str, Any]:
    doc, why = smc._read_json(Path(data_dir) / EVAL_FILE)
    if doc is None:
        return {"kind": UNMEASURED, "reason": f"артефакт взвода не прочитан: {why}"}
    crit = observed_field(doc, "criteria", kind=list)
    if crit is None:
        return {"kind": UNMEASURED, "reason": f"в {EVAL_FILE} нет раздела criteria"}
    names = [str(c.get("criterion") or c.get("name") or "") for c in crit if isinstance(c, dict)]
    names = [n for n in names if n]
    if not names:
        kind = "absent"
    elif any(any(m in n.lower() for m in EVENT_CRITERION_MARKERS) for n in names):
        kind = "events_in_criterion"
    elif set(names) <= set(DAYS_CRITERION_NAMES):
        kind = "days_only"
    else:
        kind = "days_and_outcomes_only"
    blockade = observed_field(doc, "arming_blockade", kind=dict)
    return {"kind": kind, "criteria": names,
            "statuses": {str(c.get("criterion")): c.get("status") for c in crit if isinstance(c, dict)},
            "observation_days": observed_number(doc, "observation_days"),
            "ready_to_arm": doc.get("ready_to_arm"),
            "arming_blockade": (None if blockade is None else {"verdict": blockade.get("verdict"),
                                                              "reason": blockade.get("reason")}),
            "artifact_generated_at": doc.get("generated_at")}


# ───────────────────────────── ось E: доступность и рост ──────────────────────

def measure_availability(days: Optional[List[Dict[str, Any]]], gas_days: Optional[List[Dict[str, Any]]],
                         base_gas: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if days:
        out["journal"] = {"days": len(days), "first": days[0]["date"], "last": days[-1]["date"]}
    else:
        out["journal"] = {"days": None, "reason": "журнала нет"}
    if gas_days:
        live_days = sum(1 for g in gas_days if g["live_gwei"])
        out["gas"] = {"days": len(gas_days), "live_days": live_days, "first": gas_days[0]["date"],
                      "last": gas_days[-1]["date"], "chain": GAS_CHAIN,
                      "unchecked_readings": sum(g["unchecked"] for g in gas_days)}
    else:
        out["gas"] = {"days": None, "reason": "истории газа нет"}
    out["base_gas"] = base_gas
    return out


def measure_growth(events: Dict[str, Dict[str, Any]], availability: Dict[str, Any], *,
                   now: dt.datetime) -> Dict[str, Dict[str, Any]]:
    """У события, которого не было: жив ли его вход (последняя дата не старше горизонта)."""
    today = now.date()
    out: Dict[str, Dict[str, Any]] = {}
    for event, row in events.items():
        if row["kind"] != "never_observed":
            continue
        src = availability.get(row["source"]) or {}
        last = _parse_date(src.get("last"))
        if last is None:
            out[event] = {"kind": UNMEASURED, "reason": "последняя дата входа не прочитана"}
            continue
        age = (today - last).days
        kind = "can_grow" if age <= RUN_DAYS else "cannot_grow"
        g: Dict[str, Any] = {"kind": kind, "input_last": last.isoformat(), "input_age_days": age,
                             "horizon_days": RUN_DAYS}
        if event == "incoming capital":
            vals = row.get("distinct_capital_values")
            if vals is None:
                # детектор не донёс перечень значений — это не «ноль значений» (инв. #17)
                g["distinct_capital_values"] = None
                g["note"] = "число различных значений капитала за период НЕ ИЗМЕРЕНО"
            else:
                g["distinct_capital_values"] = len(vals)
                g["note"] = (f"за {row.get('input_days')} дней капитал принимал {len(vals)} значение(я): "
                             f"взносов в бумажную книгу не было ни разу; вход пишется, но событие родит только "
                             f"взнос — у бумажной книги его дверь не названа")
        out[event] = g
    return out


# ───────────────────────────── находки и сборка ───────────────────────────────

def _findings(parity_r: Dict[str, Any], events: Dict[str, Dict[str, Any]], controls: Dict[str, Dict[str, Any]],
              criterion: Dict[str, Any], growth: Dict[str, Dict[str, Any]],
              availability: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    if parity_r.get("agrees") is False:
        findings.append({"severity": "CRITICAL", "code": "owner_section_drifted",
                         "detail": "; ".join(parity_r["mismatches"])})
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    for event, row in events.items():
        if row["kind"] == "never_observed":
            g = growth.get(event) or {}
            findings.append({"severity": "CRITICAL", "code": "owner_event_never_observed", "event": event,
                             "detail": (f"за {row.get('input_days')} дней входа ({row['source']}) событие не "
                                        f"наблюдалось ни разу; дверь: {row['door']['threshold']}; "
                                        f"рост: {g.get('kind')}"
                                        + (f" — {g['note']}" if g.get("note") else ""))})
        elif row["kind"] == UNMEASURED:
            unmeasured.append(f"событие {event!r}: {row.get('reason')}")
    for event, ctl in controls.items():
        if ctl["kind"] == "indiscriminate":
            findings.append({"severity": "CRITICAL", "code": "detector_indiscriminate", "event": event,
                             "detail": f"детектор срабатывает одинаково с событием и без: {ctl}"})

    ck = criterion.get("kind")
    if ck in ("days_and_outcomes_only", "days_only", "absent"):
        findings.append({"severity": "CRITICAL", "code": "event_coverage_not_a_criterion",
                         "detail": (f"критерий взвода ({criterion.get('criteria')}) считает "
                                    f"{'только дни' if ck == 'days_only' else 'дни и исходы' if ck == 'days_and_outcomes_only' else 'ничего'}; "
                                    f"ни одно его поле не спрашивает, какие из {OWNER_EVENTS_DECLARED} событий "
                                    f"владельца период содержит — «не только количество дней» критерием не стало")})
    elif ck == UNMEASURED:
        unmeasured.append(f"критерий срока: {criterion.get('reason')}")
    blockade = criterion.get("arming_blockade")
    if isinstance(blockade, dict) and blockade.get("verdict"):
        findings.append({"severity": "INFO", "code": "arming_blockade_carried",
                         "detail": f"{blockade['verdict']}: {blockade.get('reason')}",
                         "carried_from": "shadow_trigger_evaluation (ADR-228, не пересчитано)"})

    for event, g in growth.items():
        if g.get("kind") == "cannot_grow":
            findings.append({"severity": "WARN", "code": "event_input_stopped", "event": event,
                             "detail": f"вход события не пишется {g['input_age_days']} дн. (последняя дата "
                                       f"{g['input_last']}) — событие уже не случится в этом периоде"})
        elif g.get("kind") == UNMEASURED:
            unmeasured.append(f"рост {event!r}: {g.get('reason')}")

    gas = availability.get("gas") or {}
    jr = availability.get("journal") or {}
    if gas.get("days") and jr.get("days") and gas["days"] < jr["days"]:
        findings.append({"severity": "WARN", "code": "gas_window_shorter_than_journal",
                         "detail": (f"история газа покрывает {gas['days']} дн. ({gas['first']}…{gas['last']}), "
                                    f"журнал тени — {jr['days']} дн. ({jr['first']}…{jr['last']}): события газа "
                                    f"судятся на более коротком периоде, чем остальные")})
    return findings, unmeasured


def _tally(events: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    return {k: sum(1 for r in events.values() if r["kind"] == k) for k in EVENT_KINDS}


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None, card_path: Optional[str] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §39. Только ЧИТАЕТ журнал, историю газа и артефакт взвода."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    parity_r = parity(card_path)
    days, days_why, corrupt = load_days(data_dir)
    gas_days, gas_why = load_gas_days(data_dir)
    base_gas = load_base_gas(data_dir)
    controls = control_detectors()
    events = measure_events(days, days_why, gas_days, gas_why, controls)
    criterion = measure_criterion(data_dir)
    availability = measure_availability(days, gas_days, base_gas)
    growth = measure_growth(events, availability, now=stamped)
    findings, unmeasured = _findings(parity_r, events, controls, criterion, growth, availability)
    tally = _tally(events)
    counts = {"critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
              "warn": sum(1 for f in findings if f["severity"] == "WARN"),
              "info": sum(1 for f in findings if f["severity"] == "INFO"),
              "unmeasured": len(unmeasured)}
    overall = ("CRITICAL" if counts["critical"] else "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "observation_period_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §39 ТЗ «Portfolio CIO» (Observation period): какие из восьми "
                     "рыночных событий владельца ЖИВОЙ период тени уже содержит (B, у каждого — дверь и "
                     "порог СИСТЕМЫ), различают ли детекторы сцену с событием и без (C), спрашивает ли критерий "
                     "взвода о событиях или только о днях и исходах (D), какое окно есть у каждого входа и "
                     "может ли ненаблюдённое событие ещё случиться (E). Ни одно число не считается заново; "
                     "срок прибор не назначает — это решение владельца. Карточка владельцу не заводится."),
        "overall": overall,
        "counts": counts,
        "declared": {"events": list(OWNER_EVENTS), "events_declared": OWNER_EVENTS_DECLARED,
                     "owner_lines": [OWNER_LINE_BEFORE, OWNER_LINE_DURATION, OWNER_LINE_NOT_DAYS_ONLY],
                     "event_doors": {k: dict(v) for k, v in EVENT_DOORS.items()},
                     "event_kinds": list(EVENT_KINDS), "control_kinds": list(CONTROL_KINDS),
                     "criterion_kinds": list(CRITERION_KINDS), "growth_kinds": list(GROWTH_KINDS),
                     "run_days": RUN_DAYS, "gas_chain": GAS_CHAIN, "risk_gates": list(RISK_GATES),
                     "input_files": list(INPUT_FILES), "order_g972_named": dict(ORDER_G972_NAMED)},
        "parity": parity_r,
        "events": events,
        "events_tally": tally,
        "coverage": {"observed": tally["observed"], "declared": OWNER_EVENTS_DECLARED,
                     "share": (round(tally["observed"] / OWNER_EVENTS_DECLARED, 4)
                               if tally[UNMEASURED] == 0 else None)},
        "controls": controls,
        "criterion": criterion,
        "availability": availability,
        "growth": growth,
        # Население, на котором стоят ответы: дней журнала, доступных детекторам (читатель
        # `apy_evidenced_pct` — `decision_journal_coverage.READERS`, счётчик `population.scoreable`).
        "population": {"scoreable": len(days) if days is not None else None, "corrupt_lines": corrupt},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§39 ТЗ «Portfolio CIO» (Observation period): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (событий {OWNER_EVENTS_DECLARED}, условий 3; заказ G972 чисел не называл)")
    elif p.get("agrees") is False:
        print("   паритет с карточкой: РАСХОЖДЕНИЕ — " + "; ".join(p["mismatches"]))
    else:
        print(f"   паритет с карточкой: НЕ ИЗМЕРЕН — {p['parsed'].get('reason')}")
    cov = doc["coverage"]
    share = cov["share"]
    print(f"   события владельца: {doc['events_tally']} → наблюдено {cov['observed']} из {cov['declared']}"
          f"{f' ({share:.0%})' if share is not None else ' (доля НЕ ИЗМЕРЕНА: есть unmeasured)'}")
    for event, row in doc["events"].items():
        if row["kind"] == UNMEASURED:
            print(f"      {event:<26} {row['kind']:<15} — {row.get('reason')}")
            continue
        extra = ""
        if row.get("longest_run_days") is not None:
            extra = f", самая долгая серия {row['longest_run_days']} дн. (нужно ≥{row['min_run_days']})"
        if row.get("regime_tally"):
            extra = f", режимы {row['regime_tally']}"
        if row.get("reverted_next_day") is not None:
            extra = f", откатились за сутки {row['reverted_next_day']} из {row['evidence_total']}"
        print(f"      {event:<26} {row['kind']:<15} дней {row['days_with_event']}/{row['input_days']} "
              f"[{row.get('first')}…{row.get('last')}]{extra} · контроль {row['control']}")
    cr = doc["criterion"]
    print(f"   критерий срока: {cr['kind']} — критерии {cr.get('criteria')}, дней {cr.get('observation_days')}, "
          f"ready_to_arm={cr.get('ready_to_arm')}" if cr["kind"] != UNMEASURED
          else f"   критерий срока: НЕ ИЗМЕРЕН — {cr.get('reason')}")
    av = doc["availability"]
    print(f"   доступность данных: журнал {av['journal']} · газ {av['gas']} · base {av['base_gas']}")
    for event, g in doc["growth"].items():
        print(f"   рост {event:<26} {g['kind']} (вход {g.get('input_last')}, возраст {g.get('input_age_days')} дн.)")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['code']}: {f.get('detail')}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — момент замера не назван"
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        return None, f"--now не разобран ({exc})"
    return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)), None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§39 ТЗ «Portfolio CIO»: какие из восьми рыночных событий владельца живой период тени "
                    "уже содержит, и спрашивает ли о них критерий взвода")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None, help="каталог данных (журнал ADR-060, история газа, артефакт взвода)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card, write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
