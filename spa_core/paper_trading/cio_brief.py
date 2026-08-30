"""CIO Brief — human-readable WHERE/HOW MUCH/WHY/WHY NOW per book (ADR-060 phase 0).

SPA CIO oversight, phase C (docs/ideas/2026-08-29-cio-oversight-layer.md). Reads the
append-only verdict history phase F already writes (``allocation_rationale_history.jsonl``,
via :func:`spa_core.paper_trading.shadow_trigger_eval.load_history`) and turns the LATEST
record into short RU prose. Computes nothing new: every number/flag used here already
exists in the ledger (phase E's ``policy_version``/``mode``, phase F's ``legs``/``gates``).

Scoping fact this module must respect: ``write_shadow_rationale``/``build_history_record``
is called ONLY from the Conservative book's cycle (``cycle_runner.py``). Balanced
(``hy_cycle.py``) and Aggressive (``lp_cycle.py``) never produce a decision record — this
module reports that plainly (:func:`no_record_brief`) rather than inventing one.

Pure display layer: never mutates a position, never gates a trade. Read-only, fail-open —
a bug here must degrade to a safe dict, never raise into the caller (matches
``spa_core.alerts.daily_report``'s contract).

LLM forbidden. Pure stdlib. Deterministic template strings only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.paper_trading.shadow_trigger_eval import load_history

log = logging.getLogger("spa.paper_trading.cio_brief")

#: Compact RU label per gate key (spa_core.allocator.rebalance_economics.evaluate()'s
#: Decision.gates). Order matters for the WHY sentence — most decisive first.
GATE_LABELS: Dict[str, str] = {
    "gain_above_band": "выгода выше порога",
    "payback_within_horizon": "окупаемость в срок",
    "cooldown_ok": "не в кулдауне",
    "min_hold_ok": "мин. срок удержания пройден",
    "move_turnover_ok": "оборот хода в бюджете",
    "week_turnover_ok": "недельный оборот в бюджете",
    "target_fully_evidenced": "цель полностью доказана",
}

_NO_RECORD_REASON = "no_decision_record_for_book"


def no_record_brief(label: str) -> dict:
    """Explicit "not wired for this book" state — Balanced/Aggressive today.

    A fixed function rather than calling :func:`brief_from_history` with an empty
    list: the reason must read as "this book has no producer at all", not
    "coincidentally no history yet" — those are different facts for a reader to act on.
    """
    return {"available": False, "reason": _NO_RECORD_REASON, "label": label}


def _top_positions(positions: Optional[Dict[str, float]], n: int = 3) -> List[dict]:
    items = sorted(((p, float(v or 0.0)) for p, v in (positions or {}).items()),
                    key=lambda kv: -kv[1])
    return [{"protocol": p, "usd": round(v, 2)} for p, v in items[:n] if v > 0]


def _where_text(rec: dict) -> str:
    top = _top_positions(rec.get("current_positions"))
    legs = rec.get("legs") or []
    held = ", ".join(f"{p['protocol']} (${p['usd']:,.0f})" for p in top) or "капитал не развёрнут"
    if not legs:
        return f"Держит: {held}."
    moves = ", ".join(
        f"{'+' if leg.get('direction') == 'increase' else '−'}{leg.get('protocol')} "
        f"(${abs(float(leg.get('delta_usd') or 0.0)):,.0f})" for leg in legs)
    return f"Держит: {held}. Предложенный ход: {moves}."


def _how_much_text(rec: dict) -> str:
    legs = rec.get("legs") or []
    turnover = rec.get("turnover_usd")
    cost = rec.get("cost_usd")
    if not legs or turnover is None:
        return "Ход этим циклом не размерялся — материальных ног нет."
    return f"Оборот ${float(turnover):,.0f} ({float(rec.get('turnover_frac') or 0.0):.1%} капитала), стоимость ${float(cost or 0.0):,.2f}."


def _why_text(rec: dict) -> dict:
    """Returns {"text": str, "gates_evidenced": bool} — never invents a gate verdict
    for a pre-phase-F (``shadow-hist-v1``) record that carries no ``gates``."""
    reasons = list(rec.get("reasons") or [])
    gates = rec.get("gates")
    reasons_text = "; ".join(reasons) if reasons else "без явных причин (в пределах полос)"
    if not isinstance(gates, dict) or not gates:
        return {"text": reasons_text, "gates_evidenced": False}
    failed = [GATE_LABELS.get(str(k), str(k)) for k, ok in gates.items() if not ok]
    gate_text = ("все критерии пройдены" if not failed
                 else "не пройдено: " + ", ".join(failed))
    return {"text": f"{reasons_text}. Критерии: {gate_text}.", "gates_evidenced": True}


def _why_now_text(records: List[dict]) -> str:
    """Diffs the latest record against the previous one. Grounded only in what the
    ledger already has — no new state, no fabricated "unchanged"."""
    if len(records) < 2:
        return "первый записанный цикл, сравнивать не с чем."
    latest, prev = records[-1], records[-2]
    lv, pv = latest.get("verdict"), prev.get("verdict")
    if lv != pv:
        return f"вердикт изменился: {pv} → {lv}."
    lg, pg = latest.get("gates"), prev.get("gates")
    if isinstance(lg, dict) and isinstance(pg, dict) and lg and pg:
        flipped = [GATE_LABELS.get(str(k), str(k)) for k in lg
                   if k in pg and lg[k] != pg[k]]
        if flipped:
            return "изменился критерий: " + ", ".join(flipped) + "."
    # Streak: walk backward while verdict+reasons stay identical. Bounded by the
    # ledger's own cap (HISTORY_MAX_LINES=1000), no separate bound needed.
    streak = 1
    baseline_reasons = latest.get("reasons")
    for rec in reversed(records[:-1]):
        if rec.get("verdict") == lv and rec.get("reasons") == baseline_reasons:
            streak += 1
        else:
            break
    if streak <= 1:
        return "рутинно — без заметных изменений."
    return f"рутинно — {streak}-й день подряд без изменений."


def brief_from_history(records: List[dict]) -> dict:
    """Pure — no I/O. ``records`` must already be date-sorted (as returned by
    :func:`load_history`). Empty history → explicit fail-closed state."""
    if not records:
        return {"available": False, "reason": _NO_RECORD_REASON}
    latest = records[-1]
    why = _why_text(latest)
    return {
        "available": True,
        "decision_id": latest.get("decision_id"),
        "cycle_date": latest.get("cycle_date"),
        "policy_version": latest.get("policy_version"),
        "mode": latest.get("mode"),
        "verdict": latest.get("verdict"),
        "where": _where_text(latest),
        "how_much": _how_much_text(latest),
        "why": why["text"],
        "gates_evidenced": why["gates_evidenced"],
        "why_now": _why_now_text(records),
    }


def build_books_brief(data_dir: Path) -> dict:
    """The one public entrypoint: {conservative, balanced, aggressive} → brief dict.

    Never raises — a brief-generation bug must not break the caller (matches
    ``spa_core.alerts.daily_report``'s fail-open-for-reporting contract).
    """
    try:
        records, _ = load_history(data_dir)
        return {
            "conservative": brief_from_history(records),
            "balanced": no_record_brief("Balanced"),
            "aggressive": no_record_brief("Aggressive"),
        }
    except Exception as exc:  # noqa: BLE001 — reporting layer never breaks the caller
        log.warning("cio_brief: build_books_brief failed (%s) — degraded response", exc)
        return {
            "conservative": {"available": False, "reason": "brief_generation_failed"},
            "balanced": no_record_brief("Balanced"),
            "aggressive": no_record_brief("Aggressive"),
        }
