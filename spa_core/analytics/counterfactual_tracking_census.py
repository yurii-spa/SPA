"""counterfactual_tracking_census.py — §31 ТЗ «Portfolio CIO»: Counterfactual tracking.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §31 «Counterfactual tracking»::

    Для каждой неисполненной shadow recommendation отслеживать:
    Что было бы, если бы мы ее выполнили?
    Например:
    T0: Move $15k Aave → Morpho · Expected break-even: 1.8 days · Expected holding: 14 days
    После: 1h · 6h · 24h · 3d · 7d
    пересчитывать: actual opportunity APY · actual theoretical gain · actual costs ·
                   whether recommendation was good

Требований здесь ЧЕТЫРЕ, и ответить «судья тени есть» — ответить не на то:

* **(A) предмет** — «каждая НЕИСПОЛНЕННАЯ shadow recommendation». Население меряется ПАРАМИ
  «ответ системы ↔ ответ CIO» по дням (прибор §30, ADR-974): рекомендация ACT, которую
  система не исполнила (`held&ACT`), и рекомендация HOLD, которой система не последовала
  (`moved&HOLD`). После взвода 11.09 (ADR-324/328) пары совпадают ПО ПОСТРОЕНИЮ — предмета
  у §31 с того дня быть не может, и это печатается, а не подразумевается;
* **(B) пять горизонтов** — у КАЖДОГО объявленного горизонта есть носитель, считающий
  именно на нём. Горизонт короче шага наблюдения входов (трек и ставки — раз в сутки)
  недостижим ПО ПОСТРОЕНИЮ, и это ОТДЕЛЬНЫЙ род, а не «пока не посчитали»;
* **(C) четыре величины** — у каждой есть носитель НА РЕКОМЕНДАЦИЮ, а не агрегат за окно; и
  «actual costs» означает стоимость, ПЕРЕСЧИТАННУЮ после, а не оценку T0, переписанную
  в строку судьи под другим именем (`cost_source = recorded`);
* **(D) связь** — строка судьи привязана к записи решения её личностью (`decision_id`), а не
  датой: в 26 днях окна записей по нескольку, и дата не называет, о какой из них речь.

🪤 ЛОВУШКА, ради которой прибор мерит ШАГ НАБЛЮДЕНИЯ, а не только наличие судьи
==============================================================================
Судья тени (`shadow_trigger_eval`, Step 2g) и реплей §38 (`cio_shadow_replay`) честно
считают исход рекомендации — но ОДИН горизонт (7 дней) на ДНЕВНОЙ сетке. Замер по
наличию сказал бы «counterfactual есть»; замер по горизонтам говорит, что из пяти
объявленных считается один, два недостижимы при суточном шаге входов, а два достижимы и
не считаются никем. И стоимость судья не пересчитывает — он переносит записанную оценку.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): судью, реплей, запись решения и живой трек не правит ни
байтом. Карточку владельцу не заводит: шаг наблюдения — свойство дневного цикла (решение
владельца о такте, ADR-055), а не вопрос. Контрапункты ВВЕЗЕНЫ, не перемерены: §30 пары
(ADR-974), судья (`DEFAULT_HORIZON_DAYS`), §38 реплей (ADR-220), §25 носители (ADR-968).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/counterfactual_tracking_census.json"
CARD_REL = smc.CARD_REL

# ───────────────────────────── дословное требование ───────────────────────────
SECTION_HEAD = "31. Counterfactual tracking"
NEXT_SECTION_HEAD = "32. Ошибки, которые необходимо измерять"
OWNER_SUBJECT_LINE = "Для каждой неисполненной shadow recommendation отслеживать:"
OWNER_QUESTION_LINE = "Что было бы, если бы мы ее выполнили?"
OWNER_AFTER_LEAD = "После:"
OWNER_RECOMPUTE_LEAD = "пересчитывать:"
OWNER_HORIZONS: Tuple[str, ...] = ("1h", "6h", "24h", "3d", "7d")
HORIZON_HOURS: Dict[str, int] = {"1h": 1, "6h": 6, "24h": 24, "3d": 72, "7d": 168}
OWNER_QUANTITIES: Tuple[str, ...] = (
    "actual opportunity APY",
    "actual theoretical gain",
    "actual costs",
    "whether recommendation was good",
)
#: Числа ОБЪЯВЛЕНЫ и краснеют тестом (урок §22/§23/§30: заказ назвал меньше, чем владелец).
OWNER_HORIZONS_DECLARED = 5
OWNER_QUANTITIES_DECLARED = 4
#: Заказ G964 п. 1 назвал горизонты и величины ПОЛНОСТЬЮ (хвост прочитан) — сдвиг 0 печатается.
ORDER_G964_NAMED: Dict[str, Any] = {"horizons": 5, "quantities": 4, "tail_read": True}
OWNER_EXAMPLE: Dict[str, str] = {"move": "Move $15k Aave → Morpho",
                                 "break_even": "1.8 days", "holding": "14 days"}

# ───────────────────────────── словари родов ───────────────────────────────────
#: (A) род неисполненной рекомендации.
SUBJECT_KINDS: Tuple[str, ...] = ("unexecuted_act", "unfollowed_hold")
#: (B) род горизонта.
HORIZON_KINDS: Tuple[str, ...] = ("tracked", "reachable_untracked", "unreachable_by_cadence",
                                  UNMEASURED)
#: (C) род носителя величины.
QUANTITY_KINDS: Tuple[str, ...] = ("per_recommendation", "aggregate_only", "estimate_reused",
                                   "absent", UNMEASURED)
#: (D) род связи строки судьи с записью.
LINK_KINDS: Tuple[str, ...] = ("by_decision_id", "by_date", "by_date_ambiguous", UNMEASURED)

#: Носители: судья тени (строки `per_verdict`), реплей §38, запись решения и её книги-соседи.
EVAL_REL = smc.EVAL_REL
REPLAY_REL = "cio_shadow_replay.json"
RECORD_REL = smc.RECORD_REL
RECORD_BOOKS: Dict[str, str] = {
    "conservative": RECORD_REL,
    "balanced": "allocation_rationale_history_balanced.jsonl",
    "aggressive": "allocation_rationale_history_aggressive.jsonl",
}
#: Стоимость считается ФАКТИЧЕСКОЙ только из этих источников судьи; `recorded` — оценка T0.
ACTUAL_COST_SOURCES: Tuple[str, ...] = ("observed", "measured", "realised", "realized")
GOOD_VALUES: Tuple[str, ...] = ("hit", "miss")

#: Величина владельца → где у носителей её искать (ключи строки судьи · пути реплея).
QUANTITY_CARRIERS: Dict[str, Dict[str, Any]] = {
    "actual opportunity APY": {
        "judge_row_keys": ("opportunity_apy_pct", "realised_target_apy_pct",
                           "actual_opportunity_apy_pct", "target_apy_realised_pct"),
        "replay_paths": ("comparison.observed.net_apy_pct", "comparison.observed.gross_apy_pct"),
    },
    "actual theoretical gain": {
        "judge_row_keys": ("benefit_usd_over_checked_days",),
        "replay_paths": ("comparison.observed.opt_minus_current_pp",),
    },
    "actual costs": {
        "judge_row_keys": ("cost_usd_used",),
        "judge_source_key": "cost_source",
        "replay_paths": ("columns.observed.arms",),
    },
    "whether recommendation was good": {
        "judge_row_keys": ("outcome",),
        "judge_values": GOOD_VALUES,
        "replay_paths": ("false_rebalances", "missed_opportunities"),
    },
}


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по нему "
                      f"был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _items_between(body: List[str], lead: str, stops: Tuple[str, ...]) -> Optional[List[str]]:
    """Пункты после строки ``lead`` до любой из ``stops`` или до «⸻». HTML-комментарии
    карточки (`<!-- источник … -->`) — не пункты владельца."""
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if s in stops or s == "⸻":
            break
        if not s or s.startswith("<!--"):
            continue
        out.append(s)
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
        "horizons": _items_between(body, OWNER_AFTER_LEAD, (OWNER_RECOMPUTE_LEAD,)),
        "quantities": _items_between(body, OWNER_RECOMPUTE_LEAD, ()),
        "subject_line_present": OWNER_SUBJECT_LINE in stripped,
        "question_line_present": OWNER_QUESTION_LINE in stripped,
        "example_present": all(v in stripped for v in OWNER_EXAMPLE.values()),
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None, "order_tail_read": ORDER_G964_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    hz, qt = parsed["horizons"], parsed["quantities"]
    if hz is None:
        mism.append(f"в разделе нет строки {OWNER_AFTER_LEAD!r}")
    elif list(hz) != list(OWNER_HORIZONS):
        mism.append(f"горизонты карточки {hz} ≠ константам {list(OWNER_HORIZONS)}")
    if qt is None:
        mism.append(f"в разделе нет строки {OWNER_RECOMPUTE_LEAD!r}")
    elif list(qt) != list(OWNER_QUANTITIES):
        mism.append(f"величины карточки {qt} ≠ константам {list(OWNER_QUANTITIES)}")
    if not parsed["subject_line_present"]:
        mism.append("строка «для каждой неисполненной shadow recommendation» не найдена")
    if not parsed["question_line_present"]:
        mism.append("строка «что было бы, если бы мы её выполнили» не найдена")
    if not parsed["example_present"]:
        mism.append("пример владельца (Move $15k Aave → Morpho · 1.8 days · 14 days) не найден")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if hz is not None and qt is not None:
        out["order_undercount"] = {
            "horizons": len(hz) - int(ORDER_G964_NAMED["horizons"]),
            "quantities": len(qt) - int(ORDER_G964_NAMED["quantities"]),
        }
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str) -> Dict[str, Any]:
    """Запись/трек/сделки/судья — дверью §30; реплей и книги-соседи — своими."""
    out = smc.load_carriers(data_dir)
    replay, why = smc._read_json(Path(data_dir) / REPLAY_REL)
    out["replay"] = replay if isinstance(replay, dict) else None
    out["replay_reason"] = why if replay is None else (
        None if isinstance(replay, dict) else "реплей не словарь")
    books: Dict[str, Any] = {}
    for book, rel in RECORD_BOOKS.items():
        rows, why_b, corrupt = smc._read_jsonl(Path(data_dir) / rel)
        books[book] = {"rows": rows, "reason": why_b, "corrupt": corrupt}
    out["books"] = books
    return out


def _judge_rows(carriers: Dict[str, Any]) -> Tuple[Optional[List[dict]], Optional[str]]:
    ev = carriers.get("eval")
    if ev is None:
        return None, f"судья {EVAL_REL} не прочитан: {carriers.get('eval_reason')}"
    rows = ev.get("per_verdict") if isinstance(ev, dict) else None
    if not isinstance(rows, list):
        return None, f"у судьи {EVAL_REL} нет списка per_verdict"
    return [r for r in rows if isinstance(r, dict)], None


# ───────────────────────────── (A) предмет ───────────────────────────────────

def measure_subject(carriers: Dict[str, Any], armed_at: Optional[str]) -> Dict[str, Any]:
    """Население «неисполненных рекомендаций» по парам §30 + ACT во всех книгах."""
    pairs = smc.measure_pairs(carriers, armed_at)
    if not pairs.get("measured"):
        return {"measured": False, "reason": f"пары §30 не измерены: {pairs.get('reason')}"}
    rows, why = _judge_rows(carriers)
    judged_by_date: Dict[str, List[dict]] = {}
    for r in rows or []:
        d = r.get("cycle_date")
        if d:
            judged_by_date.setdefault(str(d), []).append(r)
    subjects: List[Dict[str, Any]] = []
    for dv in pairs.get("divergent_days") or []:
        kind = ("unexecuted_act" if dv.get("cio") == "ACT" else
                "unfollowed_hold" if dv.get("cio") == "HOLD" else UNMEASURED)
        jr = judged_by_date.get(str(dv.get("date")), [])
        outcomes = sorted({str(r.get("outcome")) for r in jr}) if jr else []
        subjects.append({"date": dv.get("date"), "kind": kind, "system": dv.get("system"),
                         "turnover_usd": dv.get("turnover_usd"),
                         "judge_rows": len(jr), "judge_outcomes": outcomes,
                         "judge": "tracked" if jr else (UNMEASURED if rows is None else "untracked")})
    acts_by_book: Dict[str, Any] = {}
    for book, b in (carriers.get("books") or {}).items():
        rows_b = b.get("rows")
        acts_by_book[book] = (None if rows_b is None else
                              sum(1 for r in rows_b if r.get("verdict") == "ACT"))
    tally = {k: sum(1 for s in subjects if s["kind"] == k) for k in SUBJECT_KINDS}
    after = pairs.get("after_arming") or {}
    return {
        "measured": True, "subjects": subjects, "tally": tally,
        "acts_by_book": acts_by_book,
        "acts_unmeasured_books": sorted(k for k, v in acts_by_book.items() if v is None),
        "after_arming": after, "armed_at": armed_at,
        "window": pairs.get("window"), "track_days": pairs.get("track_days"),
        "matrix": pairs.get("matrix"), "judge_reason": why,
        "subject_exists": bool(subjects),
        "subject_impossible_after_arming": bool(armed_at) and (after.get("days") or 0) > 0
        and after.get("divergent") == 0,
    }


# ───────────────────────────── (B) горизонты ─────────────────────────────────

def _cadence_hours(daily: Optional[List[dict]]) -> Tuple[Optional[float], Optional[str]]:
    """Шаг наблюдения входов — минимальный зазор между датами трека (часы)."""
    if daily is None:
        return None, "трек не прочитан"
    dates = sorted({str(x.get("date")) for x in daily
                    if isinstance(x, dict) and smc._date_of(x.get("date"))})
    if len(dates) < 2:
        return None, f"в треке {len(dates)} дат(ы) — шаг наблюдения не вычислим"
    gaps: List[float] = []
    for a, b in zip(dates, dates[1:]):
        try:
            da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        except ValueError:
            continue
        gaps.append((db - da).days * 24.0)
    if not gaps:
        return None, "даты трека не разбираются"
    return min(gaps), None


def measure_horizons(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Каждому объявленному горизонту — род: tracked · reachable_untracked ·
    unreachable_by_cadence · не измерено."""
    carrier_h: Dict[str, Any] = {}
    ev = carriers.get("eval")
    if isinstance(ev, dict):
        hd = (ev.get("params") or {}).get("horizon_days") if isinstance(ev.get("params"), dict) else None
        if hd is None:
            try:
                from spa_core.paper_trading import shadow_trigger_eval as ste
                hd = ste.DEFAULT_HORIZON_DAYS
            except Exception as exc:  # noqa: BLE001
                carrier_h["judge"] = {"hours": None, "reason": f"горизонт судьи не прочитан: {exc}"}
        if hd is not None:
            carrier_h["judge"] = {"hours": float(hd) * 24.0, "source": "params.horizon_days"}
    else:
        carrier_h["judge"] = {"hours": None, "reason": f"судья не прочитан: {carriers.get('eval_reason')}"}
    rp = carriers.get("replay")
    if isinstance(rp, dict):
        hd = (rp.get("population") or {}).get("horizon_days") if isinstance(rp.get("population"), dict) else None
        carrier_h["replay"] = ({"hours": float(hd) * 24.0, "source": "population.horizon_days"}
                               if hd is not None else
                               {"hours": None, "reason": "у реплея нет population.horizon_days"})
    else:
        carrier_h["replay"] = {"hours": None, "reason": f"реплей не прочитан: {carriers.get('replay_reason')}"}
    cadence, why = _cadence_hours(carriers.get("daily"))
    tracked_hours = {c["hours"] for c in carrier_h.values() if c.get("hours") is not None}
    rows: Dict[str, Dict[str, Any]] = {}
    for h in OWNER_HORIZONS:
        hh = HORIZON_HOURS[h]
        if hh in tracked_hours:
            rows[h] = {"kind": "tracked", "hours": hh,
                       "carriers": sorted(k for k, c in carrier_h.items() if c.get("hours") == hh)}
        elif cadence is None:
            rows[h] = {"kind": UNMEASURED, "hours": hh, "reason": f"шаг наблюдения не измерен: {why}"}
        elif hh < cadence:
            rows[h] = {"kind": "unreachable_by_cadence", "hours": hh, "cadence_hours": cadence,
                       "reason": f"горизонт {h} короче шага наблюдения входов ({cadence:g} ч)"}
        else:
            rows[h] = {"kind": "reachable_untracked", "hours": hh, "cadence_hours": cadence}
    tally = {k: sum(1 for r in rows.values() if r["kind"] == k) for k in HORIZON_KINDS}
    return {"measured": True, "declared": OWNER_HORIZONS_DECLARED, "horizons": rows,
            "tally": tally, "carriers": carrier_h, "cadence_hours": cadence,
            "cadence_reason": why}


# ───────────────────────────── (C) величины ──────────────────────────────────

def _path(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def measure_quantities(carriers: Dict[str, Any]) -> Dict[str, Any]:
    """Каждой величине — род носителя. Судья — на рекомендацию; реплей — агрегат."""
    rows, why = _judge_rows(carriers)
    rp = carriers.get("replay")
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in QUANTITY_CARRIERS.items():
        r: Dict[str, Any] = {"judge_keys": list(spec["judge_row_keys"]),
                             "replay_paths": list(spec["replay_paths"])}
        replay_hit = [p for p in spec["replay_paths"] if isinstance(rp, dict) and _path(rp, p) is not None]
        r["replay_present"] = replay_hit
        if rows is None:
            r["kind"] = UNMEASURED
            r["reason"] = why
            out[name] = r
            continue
        present = [row for row in rows
                   if any(row.get(k) is not None for k in spec["judge_row_keys"])]
        r["judge_rows"] = len(rows)
        r["judge_rows_with_value"] = len(present)
        if "judge_source_key" in spec:
            sources: Dict[str, int] = {}
            for row in present:
                s = str(row.get(spec["judge_source_key"]))
                sources[s] = sources.get(s, 0) + 1
            r["judge_sources"] = sources
            actual = sum(v for k, v in sources.items() if k in ACTUAL_COST_SOURCES)
            if present and actual == len(present):
                r["kind"] = "per_recommendation"
            elif present:
                r["kind"] = "estimate_reused"
                r["reason"] = (f"источник стоимости у судьи {sources} — оценка T0 из записи, "
                               f"пересчёта после горизонта нет")
            else:
                r["kind"] = "aggregate_only" if replay_hit else "absent"
        elif "judge_values" in spec:
            scored = [row for row in present
                      if any(row.get(k) in spec["judge_values"] for k in spec["judge_row_keys"])]
            r["judge_rows_scored"] = len(scored)
            r["kind"] = ("per_recommendation" if scored else
                         "aggregate_only" if replay_hit else "absent")
        else:
            r["kind"] = ("per_recommendation" if present else
                         "aggregate_only" if replay_hit else "absent")
        out[name] = r
    tally = {k: sum(1 for r in out.values() if r["kind"] == k) for k in QUANTITY_KINDS}
    return {"measured": rows is not None or isinstance(rp, dict), "declared": OWNER_QUANTITIES_DECLARED,
            "quantities": out, "tally": tally, "judge_reason": why}


# ───────────────────────────── (D) связь ─────────────────────────────────────

def measure_linkage(carriers: Dict[str, Any]) -> Dict[str, Any]:
    rows, why = _judge_rows(carriers)
    recs = carriers.get("records")
    if rows is None:
        return {"measured": False, "kind": UNMEASURED, "reason": why}
    if recs is None:
        return {"measured": False, "kind": UNMEASURED,
                "reason": f"запись решения не прочитана: {carriers.get('records_reason')}"}
    if not rows:
        return {"measured": True, "kind": UNMEASURED, "reason": "у судьи нет строк — связь не наблюдена"}
    with_id = sum(1 for r in rows if r.get("decision_id"))
    recs_with_id = sum(1 for r in recs if r.get("decision_id"))
    per_date: Dict[str, int] = {}
    for r in recs:
        d = r.get("cycle_date")
        if d:
            per_date[str(d)] = per_date.get(str(d), 0) + 1
    ambiguous = sorted(d for d, n in per_date.items() if n > 1)
    if with_id == len(rows):
        kind = "by_decision_id"
    elif ambiguous:
        kind = "by_date_ambiguous"
    else:
        kind = "by_date"
    return {"measured": True, "kind": kind, "judge_rows": len(rows), "judge_rows_with_decision_id": with_id,
            "records": len(recs), "records_with_decision_id": recs_with_id,
            "ambiguous_dates": ambiguous, "ambiguous_dates_count": len(ambiguous)}


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], subject: Dict[str, Any], horizons: Dict[str, Any],
              quantities: Dict[str, Any], linkage: Dict[str, Any]
              ) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    # (A)
    if not subject.get("measured"):
        unmeasured.append(f"ось A: {subject.get('reason')}")
    else:
        t = subject["tally"]
        acts = subject["acts_by_book"]
        for b in subject["acts_unmeasured_books"]:
            unmeasured.append(f"ось A: книга {b} не прочитана — ACT в ней не измерен")
        if not subject["subject_exists"]:
            add("WARN", "no_unexecuted_recommendation",
                f"неисполненных рекомендаций в окне {subject.get('window')} нет: ACT по книгам {acts}, "
                f"расхождений «система ↔ CIO» 0 — предмета у §31 нет")
        else:
            untracked = [s for s in subject["subjects"] if s["judge"] != "tracked"]
            add("INFO", "unexecuted_recommendations_counted",
                f"неисполненных рекомендаций {len(subject['subjects'])} ({t}); у судьи есть строка у "
                f"{len(subject['subjects']) - len(untracked)}, нет у {len(untracked)}")
            if untracked:
                add("WARN", "unexecuted_recommendation_without_judge_row",
                    "дни без строки судьи: " + ", ".join(str(s["date"]) for s in untracked))
        if subject["subject_impossible_after_arming"]:
            a = subject["after_arming"]
            add("WARN", "no_subject_after_arming",
                f"после взвода {subject['armed_at']}: дней {a.get('days')}, расхождений 0 — "
                f"рекомендация и ответ системы совпадают ПО ПОСТРОЕНИЮ (ADR-974), §31 нечего отслеживать")

    # (B)
    hz = horizons.get("horizons") or {}
    for h, r in hz.items():
        if r["kind"] == UNMEASURED:
            unmeasured.append(f"ось B: горизонт {h}: {r.get('reason')}")
    tracked = [h for h, r in hz.items() if r["kind"] == "tracked"]
    unreach = [h for h, r in hz.items() if r["kind"] == "unreachable_by_cadence"]
    reach_un = [h for h, r in hz.items() if r["kind"] == "reachable_untracked"]
    if hz and len(tracked) < horizons["declared"]:
        add("CRITICAL", "horizons_declared_vs_tracked",
            f"объявлено {horizons['declared']} горизонтов, считается {len(tracked)} {tracked}; "
            f"недостижимы при шаге наблюдения {horizons.get('cadence_hours')} ч: {unreach}; "
            f"достижимы и не считаются никем: {reach_un}")
    if unreach:
        add("INFO", "horizons_unreachable_by_cadence",
            f"{unreach}: трек и ставки наблюдаются раз в {horizons.get('cadence_hours')} ч — "
            f"горизонт короче шага нельзя посчитать, можно только объявить недостижимым")

    # (C)
    qs = quantities.get("quantities") or {}
    for name, r in qs.items():
        k = r.get("kind")
        if k == UNMEASURED:
            unmeasured.append(f"ось C: «{name}»: {r.get('reason')}")
        elif k == "estimate_reused":
            add("CRITICAL", f"quantity_not_recomputed:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "absent":
            add("CRITICAL", f"quantity_absent:{name}",
                f"«{name}» не несёт ни судья (ключи {r['judge_keys']}), ни реплей ({r['replay_paths']})")
        elif k == "aggregate_only":
            add("WARN", f"quantity_aggregate_only:{name}",
                f"«{name}» есть только агрегатом за окно у реплея {r['replay_present']}; "
                f"на рекомендацию судья не несёт (ключи {r['judge_keys']})")

    # (D)
    if linkage.get("kind") == UNMEASURED:
        unmeasured.append(f"ось D: {linkage.get('reason')}")
    elif linkage.get("kind") == "by_date_ambiguous":
        add("WARN", "linkage_by_date_ambiguous",
            f"строка судьи привязана к записи ДАТОЙ (decision_id у {linkage['judge_rows_with_decision_id']} "
            f"из {linkage['judge_rows']} строк), а в {linkage['ambiguous_dates_count']} днях записей по "
            f"нескольку — дата не называет, о какой рекомендации речь")
    elif linkage.get("kind") == "by_date":
        add("INFO", "linkage_by_date", "строка судьи привязана датой; дней с несколькими записями нет")
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §31. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir)
    order = smc.measure_cycle_order(root)
    execution = smc.measure_execution(data_dir, order)
    armed_at = ((execution.get("armed_books") or {}).get(smc.SCENE_BOOK_ARMED) or {}).get("armed_at") \
        if execution.get("measured") else None
    subject = measure_subject(carriers, armed_at)
    horizons = measure_horizons(carriers)
    quantities = measure_quantities(carriers)
    linkage = measure_linkage(carriers)

    findings, unmeasured = _findings(parity_r, subject, horizons, quantities, linkage)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "counterfactual_tracking_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §31 ТЗ «Portfolio CIO» (Counterfactual tracking). Судью "
                     "тени, реплей, запись решения и живой трек НЕ трогает; карточку владельцу не "
                     "заводит — шаг наблюдения есть свойство дневного цикла"),
        "overall": overall,
        "counts": counts,
        "declared": {"horizons": list(OWNER_HORIZONS), "horizons_declared": OWNER_HORIZONS_DECLARED,
                     "horizon_hours": dict(HORIZON_HOURS),
                     "quantities": list(OWNER_QUANTITIES), "quantities_declared": OWNER_QUANTITIES_DECLARED,
                     "order_g964_named": dict(ORDER_G964_NAMED), "example": dict(OWNER_EXAMPLE),
                     "subject_kinds": list(SUBJECT_KINDS), "horizon_kinds": list(HORIZON_KINDS),
                     "quantity_kinds": list(QUANTITY_KINDS), "link_kinds": list(LINK_KINDS),
                     "actual_cost_sources": list(ACTUAL_COST_SOURCES)},
        "parity": parity_r,
        "axis_a_subject": subject,
        "axis_b_horizons": horizons,
        "axis_c_quantities": quantities,
        "axis_d_linkage": linkage,
        "carriers_read": {k: (carriers.get(k) is not None)
                          for k in ("records", "daily", "trades", "eval", "replay")},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path): перестановка у §26 оставляла прибор без артефакта.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§31 ТЗ «Portfolio CIO» (Counterfactual tracking): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (горизонтов {OWNER_HORIZONS_DECLARED}, величин "
              f"{OWNER_QUANTITIES_DECLARED}; заказ G964 назвал {ORDER_G964_NAMED['horizons']}/"
              f"{ORDER_G964_NAMED['quantities']}, сдвиг {p.get('order_undercount')})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    a = doc["axis_a_subject"]
    if a.get("measured"):
        print(f"   [ось A] предмет: окно {a.get('window')} · неисполненных {len(a['subjects'])} {a['tally']} · "
              f"ACT по книгам {a['acts_by_book']} · после взвода {a.get('after_arming')}")
    else:
        print(f"   [ось A] НЕ ИЗМЕРЕНО: {a.get('reason')}")
    b = doc["axis_b_horizons"]
    print(f"   [ось B] горизонты (шаг наблюдения {b.get('cadence_hours')} ч): " + ", ".join(
        f"{h}→{r['kind']}" for h, r in (b.get("horizons") or {}).items()))
    q = doc["axis_c_quantities"]
    print(f"   [ось C] величины: {q.get('tally')}")
    for name, r in (q.get("quantities") or {}).items():
        print(f"      «{name}»: {r.get('kind')} (судья {r.get('judge_rows_with_value')}/{r.get('judge_rows')}, "
              f"реплей {r.get('replay_present')})")
    d = doc["axis_d_linkage"]
    print(f"   [ось D] связь судья↔запись: {d.get('kind')} — дней с несколькими записями "
          f"{d.get('ambiguous_dates_count')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§31 ТЗ «Portfolio CIO»: Counterfactual tracking — есть ли пять горизонтов и "
                    "четыре величины на КАЖДУЮ неисполненную рекомендацию")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(ns.data_dir if ns.data_dir else ns.root, who="counterfactual_tracking_census")
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
