"""Y3 (ADR-055/ADR-060 tooling): shadow-verdict vs fact reconciliation.

The yield-trigger SHADOW (``allocation_rationale.py``) says HOLD/ACT every cycle
without moving capital. Before the owner arms it, we need the honest question
answered: **had the verdicts been followed, would the book have earned more,
net of switching cost?** This module reads the append-only verdict history
(``data/allocation_rationale_history.jsonl``), replays every verdict against the
LIVE evidenced APYs of the FOLLOWING days, and writes
``data/shadow_trigger_evaluation.json``.

Method, in one paragraph. For each verdict on day *d* with a material proposed
move (current → target), the counterfactual benefit over the horizon is
``Σ_{f in next H observed days} Σ_p (target_p − current_p) · apy_p(f) / 100 / 365``
where ``apy_p(f)`` comes from the history line of day *f* — evidenced (live)
APYs only, never literals. Cost is the verdict's own recorded ``cost_usd``
(gas + slippage model from ``rebalance_economics``); when a material move has no
recorded cost, a CONSERVATIVE assumption of ``ASSUMED_COST_BPS_OF_TURNOVER`` bps
of turnover is charged and labelled as an assumption. An ACT is a **hit** if
net > 0; a material HOLD is a **hit** if net ≤ 0 (holding was right) and a
**miss** if the gated move would have paid. Trivial HOLDs (no material legs —
nothing to decide) are counted but excluded from the hit-rate denominator, so a
quiet market cannot inflate the score. Any day the counterfactual cannot be
priced (missing forward data, missing evidenced APY for a moved leg) is
UNCHECKED — reported, never guessed (invariant 2).

Deterministic, stdlib-only, read-only over everything except its own output.
Fail-open at the cycle boundary: the cycle hook wraps this in try/except.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.shadow_trigger_eval")

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
EVAL_FILENAME = "shadow_trigger_evaluation.json"
EVAL_VERSION = "shadow-eval-v1"

# ── Evaluation parameters (documented in the output; changing them is visible) ──
DEFAULT_HORIZON_DAYS = 7          # forward window a verdict is judged over
# Arming criteria set BY THE OWNER (ADR-067, 2026-08-06): ≥30 observed days,
# hit-rate ≥60%, net benefit > 0. The previous 7d/70% were the tool author's
# placeholder; the owner's bar is the binding one. The agent brings the table,
# arming stays an owner-gated step regardless of PASS.
MIN_OBSERVATION_DAYS = 30         # arming criterion (ADR-067)
MIN_EVALUATED_FOR_HIT_RATE = 5    # hit-rate is UNCHECKED below this sample size
MIN_HIT_RATE = 0.60               # arming criterion (ADR-067)
ASSUMED_COST_BPS_OF_TURNOVER = 15.0  # conservative gas+slippage assumption (vs ~8bps
#                                      slippage + gas in rebalance_economics) used ONLY
#                                      when a material move carries no recorded cost
MATERIAL_TURNOVER_USD = 100.0     # below this a "move" is noise, the HOLD is trivial


def load_history(data_dir: Path) -> Tuple[List[dict], int]:
    """Parsed history lines sorted by cycle_date (last line wins per date).

    Returns ``(records, unparseable_count)``. Never raises: a missing file is an
    empty history, a corrupt line is counted, not fatal.
    """
    path = Path(data_dir) / HISTORY_FILENAME
    by_date: Dict[str, dict] = {}
    bad = 0
    if not path.exists():
        return [], 0
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("shadow history unreadable (%s)", exc)
        return [], 0
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(obj, dict) or not obj.get("cycle_date"):
            bad += 1
            continue
        by_date[str(obj["cycle_date"])] = obj  # later line wins (same-date re-run)
    return [by_date[d] for d in sorted(by_date)], bad


def _load_equity_daily(data_dir: Path) -> Dict[str, dict]:
    """date → daily row from equity_curve_daily.json (book-APY cross-check)."""
    try:
        doc = json.loads((Path(data_dir) / "equity_curve_daily.json")
                         .read_text(encoding="utf-8"))
        return {str(r.get("date")): r for r in doc.get("daily", [])
                if isinstance(r, dict) and r.get("date")}
    except Exception as exc:  # noqa: BLE001 — cross-check only, never fatal
        log.warning("equity_curve_daily unavailable (%s) — cross-check UNCHECKED", exc)
        return {}


def _deltas(rec: dict) -> Dict[str, float]:
    cur = rec.get("current_positions") or {}
    tgt = rec.get("target_positions") or {}
    out: Dict[str, float] = {}
    for p in set(cur) | set(tgt):
        d = float(tgt.get(p, 0.0) or 0.0) - float(cur.get(p, 0.0) or 0.0)
        if abs(d) > 0.005:
            out[p] = d
    return out


def _turnover_usd(rec: dict, deltas: Dict[str, float]) -> float:
    t = rec.get("turnover_usd")
    if t is not None:
        try:
            return float(t)
        except (TypeError, ValueError):
            pass
    return sum(abs(v) for v in deltas.values()) / 2.0


def _day_gain_usd(deltas: Dict[str, float],
                  apy_map: Dict[str, float]) -> Tuple[Optional[float], List[str]]:
    """One forward day's counterfactual gain; None if any moved leg is unpriced.

    Fail-CLOSED per day: a day where one leg lacks an evidenced APY is UNCHECKED
    for the whole move — partial pricing would silently bias the answer toward
    whichever side happened to have data.
    """
    missing = sorted(p for p in deltas if apy_map.get(p) is None)
    if missing:
        return None, missing
    gain = 0.0
    for p, dv in deltas.items():
        gain += dv * float(apy_map[p]) / 100.0 / 365.0
    return gain, []


def _evaluate_verdict(rec: dict, forward: List[dict],
                      horizon_days: int) -> dict:
    """Judge one verdict against the live evidenced APYs of the following days."""
    verdict = str(rec.get("verdict") or "UNKNOWN").upper()
    deltas = _deltas(rec)
    turnover = _turnover_usd(rec, deltas)
    material = bool(deltas) and turnover >= MATERIAL_TURNOVER_USD

    out: dict = {
        "cycle_date": rec.get("cycle_date"),
        "verdict": verdict,
        "reasons": list(rec.get("reasons") or []),
        "material": material,
        "turnover_usd": round(turnover, 2),
        "gain_pp_claimed": rec.get("gain_pp"),
    }

    # A line with a held book but NO recorded target (e.g. reconstructed from a
    # log that never carried the proposed book) must not be read as "liquidate
    # everything" — that is a data hole, not a proposal. UNCHECKED, not a guess.
    if (rec.get("current_positions") or {}) and not (rec.get("target_positions") or {}):
        out.update({
            "outcome": "UNCHECKED",
            "counterfactual": "UNCHECKED",
            "unchecked_reason": "no_target_recorded",
            "trivial": False,
        })
        return out

    if not material:
        # Nothing was proposed — a HOLD here is trivially consistent, an ACT
        # here would be a contradiction worth surfacing.
        out.update({
            "outcome": "hit" if verdict == "HOLD" else "miss",
            "counterfactual": "TRIVIAL",
            "trivial": True,
            "net_usd": 0.0,
        })
        return out
    out["trivial"] = False

    # Cost: recorded by the trigger's own gas+slippage model; if absent on a
    # material move, charge the conservative assumption — never zero.
    cost_rec = rec.get("cost_usd")
    try:
        cost_rec = float(cost_rec) if cost_rec is not None else None
    except (TypeError, ValueError):
        cost_rec = None
    if cost_rec is not None and cost_rec > 0.0:
        cost_used, cost_source = cost_rec, "recorded"
    else:
        cost_used = turnover * ASSUMED_COST_BPS_OF_TURNOVER / 10_000.0
        cost_source = f"assumption:{ASSUMED_COST_BPS_OF_TURNOVER:g}bps_of_turnover"
    out.update({"cost_usd_recorded": cost_rec, "cost_usd_used": round(cost_used, 2),
                "cost_source": cost_source})

    fw = forward[:horizon_days]
    checked = unchecked = 0
    benefit = 0.0
    missing_all: set = set()
    for frec in fw:
        gain, missing = _day_gain_usd(deltas, frec.get("apy_evidenced_pct") or {})
        if gain is None:
            unchecked += 1
            missing_all.update(missing)
        else:
            checked += 1
            benefit += gain
    out.update({
        "forward_days_available": len(fw),
        "forward_days_checked": checked,
        "forward_days_unchecked": unchecked,
        "unpriced_protocols": sorted(missing_all),
    })

    if checked == 0:
        out.update({
            "counterfactual": "UNCHECKED",
            "unchecked_reason": ("no_forward_data" if not fw
                                 else "no_evidenced_apy_for_moved_legs"),
            "outcome": "UNCHECKED",
        })
        return out

    net = benefit - cost_used
    out.update({
        "counterfactual": "CHECKED" if (unchecked == 0 and len(fw) == horizon_days)
        else "PARTIAL",
        "benefit_usd_over_checked_days": round(benefit, 2),
        "net_usd": round(net, 2),
    })
    if verdict == "ACT":
        out["outcome"] = "hit" if net > 0 else "miss"
    elif verdict == "HOLD":
        # Holding was right unless the gated move would have paid its own cost.
        out["outcome"] = "miss" if net > 0 else "hit"
        out["missed_usd"] = round(net, 2) if net > 0 else 0.0
    else:
        out["outcome"] = "UNCHECKED"
        out["unchecked_reason"] = f"unknown_verdict:{verdict}"
    return out


def _criterion(name: str, threshold, actual, status: str, note: str = "") -> dict:
    c = {"criterion": name, "threshold": threshold, "actual": actual, "status": status}
    if note:
        c["note"] = note
    return c


def evaluate_window(
    data_dir: Path,
    *,
    window_days: Optional[int] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_days: int = MIN_OBSERVATION_DAYS,
    min_hit_rate: float = MIN_HIT_RATE,
    write: bool = True,
) -> dict:
    """Reconcile the shadow's verdict history with what live data then showed.

    Deterministic given the files on disk. Data holes surface as UNCHECKED with
    a reason — never as a made-up number. ``write=False`` computes without
    touching disk (beyond reads).
    """
    data_dir = Path(data_dir)
    history, bad_lines = load_history(data_dir)
    if window_days is not None and window_days > 0:
        history = history[-(window_days + horizon_days):]
    equity = _load_equity_daily(data_dir)

    per_verdict: List[dict] = []
    for i, rec in enumerate(history):
        row = _evaluate_verdict(rec, history[i + 1:], horizon_days)
        # Book-APY cross-check against the equity curve (context, not a gate).
        eq = equity.get(str(rec.get("cycle_date")))
        if eq is not None and eq.get("apy_today") is not None:
            row["book_apy_equity_pct"] = eq.get("apy_today")
        per_verdict.append(row)
    if window_days is not None and window_days > 0:
        per_verdict = per_verdict[-window_days:]

    observed_days = len({r["cycle_date"] for r in per_verdict if r.get("cycle_date")})
    acts = [r for r in per_verdict if r["verdict"] == "ACT"]
    holds = [r for r in per_verdict if r["verdict"] == "HOLD"]
    trivial = [r for r in per_verdict if r.get("trivial")]
    unchecked = [r for r in per_verdict if r["outcome"] == "UNCHECKED"]
    scored = [r for r in per_verdict
              if not r.get("trivial") and r["outcome"] in ("hit", "miss")]
    hits = [r for r in scored if r["outcome"] == "hit"]
    hit_rate = round(len(hits) / len(scored), 4) if scored else None

    acts_scored = [r for r in acts if r["outcome"] in ("hit", "miss")]
    net_usd_if_followed = round(sum(r.get("net_usd", 0.0) for r in acts_scored), 2)
    capital = None
    for rec in reversed(history):
        if rec.get("capital_usd"):
            capital = float(rec["capital_usd"])
            break
    net_bps_if_followed = (round(10_000.0 * net_usd_if_followed / capital, 2)
                           if capital else None)
    hold_missed_usd = round(sum(r.get("missed_usd", 0.0) for r in holds), 2)

    # ── Arming-readiness criteria (each PASS / FAIL / UNCHECKED; fail-closed:
    #    anything not PASS ⇒ NOT_READY). These are the thresholds the owner card
    #    will cite — change them only with the ADR that arms the trigger. ──
    criteria = [
        _criterion("observation_days", f">={min_days}", observed_days,
                   "PASS" if observed_days >= min_days else "FAIL"),
    ]
    if len(scored) < MIN_EVALUATED_FOR_HIT_RATE:
        criteria.append(_criterion(
            "hit_rate", f">={min_hit_rate}", hit_rate, "UNCHECKED",
            f"only {len(scored)} non-trivial verdict(s) scored — "
            f"need >={MIN_EVALUATED_FOR_HIT_RATE} for the rate to mean anything"))
    else:
        criteria.append(_criterion(
            "hit_rate", f">={min_hit_rate}", hit_rate,
            "PASS" if (hit_rate is not None and hit_rate >= min_hit_rate) else "FAIL"))
    if not acts_scored:
        criteria.append(_criterion(
            "net_bps_if_followed", ">0", net_bps_if_followed, "UNCHECKED",
            "no ACT verdict has been scored yet — nothing proves the trigger PAYS; "
            "an all-HOLD window can satisfy hit-rate while leaving this unknown"))
    else:
        criteria.append(_criterion(
            "net_bps_if_followed", ">0", net_bps_if_followed,
            "PASS" if (net_bps_if_followed is not None
                       and net_bps_if_followed > 0) else "FAIL"))

    ready = all(c["status"] == "PASS" for c in criteria)

    doc = {
        "generated_at": None,  # filled below; kept out of the hash-relevant zone
        "version": EVAL_VERSION,
        "mode": "ADVISORY",
        "note": ("Y3 tooling (ADR-055/ADR-060): reconciles shadow verdicts with "
                 "subsequent live data. ADVISORY ONLY — arming the trigger is a "
                 "separate owner-gated step (pre_cutover_gate + ADR)."),
        "status": "READY" if ready else "NOT_READY",
        "ready_to_arm": ready,
        "observation_days": observed_days,
        "counts": {
            "act": len(acts), "hold": len(holds),
            "trivial_hold": len([r for r in trivial if r["verdict"] == "HOLD"]),
            "scored": len(scored), "unchecked": len(unchecked),
            "corrupt_history_lines": bad_lines,
        },
        "hit_rate": hit_rate,
        "net_usd_if_followed": net_usd_if_followed,
        "net_bps_if_followed": net_bps_if_followed,
        "hold_missed_usd_total": hold_missed_usd,
        "criteria": criteria,
        "params": {
            "horizon_days": horizon_days,
            "min_observation_days": min_days,
            "min_hit_rate": min_hit_rate,
            "min_scored_for_hit_rate": MIN_EVALUATED_FOR_HIT_RATE,
            "assumed_cost_bps_of_turnover": ASSUMED_COST_BPS_OF_TURNOVER,
            "material_turnover_usd": MATERIAL_TURNOVER_USD,
        },
        "assumptions": [
            "forward APY per protocol comes from the accumulator's own evidenced "
            "(live-sourced) daily maps; a day with an unpriced moved leg is "
            "UNCHECKED, never interpolated",
            "cost = the verdict's recorded gas+slippage estimate; a material move "
            f"without one is charged {ASSUMED_COST_BPS_OF_TURNOVER:g} bps of "
            "turnover (conservative assumption, labelled per verdict)",
            "trivial HOLDs (no material proposal) are excluded from hit-rate so a "
            "quiet market cannot inflate the score",
        ],
        "per_verdict": per_verdict,
    }
    # Полный ISO с временем: date-only метка читалась сторожем B2 как «полночь»
    # и рождала ложный WARN свежести каждую ночь 02:00–06:00 (2026-08-07).
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    if write:
        atomic_save(doc, str(data_dir / EVAL_FILENAME))
    return doc


def format_summary(doc: dict) -> str:
    """Human-readable stdout summary (RU — owner-facing)."""
    lines = [
        "── Оценка теневого триггера (Y3, ADR-060) ─────────────────────",
        f"Статус: {doc['status']}  (готов к включению: "
        f"{'да' if doc.get('ready_to_arm') else 'нет'})",
        f"Дней наблюдения: {doc.get('observation_days')}",
        "Вердикты: ACT={act}  HOLD={hold} (из них тривиальных: {trivial_hold})  "
        "оценено: {scored}  UNCHECKED: {unchecked}".format(**doc.get("counts", {})),
        f"Hit-rate: {doc.get('hit_rate')}",
        f"Если бы следовали ACT: {doc.get('net_usd_if_followed')} USD "
        f"({doc.get('net_bps_if_followed')} bps капитала), net затрат",
        f"Упущено на HOLD суммарно: {doc.get('hold_missed_usd_total')} USD",
        "Критерии включения:",
    ]
    for c in doc.get("criteria", []):
        note = f" — {c['note']}" if c.get("note") else ""
        lines.append(f"  [{c['status']:>9}] {c['criterion']} {c['threshold']} "
                     f"(факт: {c['actual']}){note}")
    lines.append("Включение — отдельное owner-решение (pre_cutover_gate + ADR); "
                 "этот отчёт капитал не двигает.")
    return "\n".join(lines)
