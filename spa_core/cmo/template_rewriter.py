"""spa_core/cmo/template_rewriter.py — deterministic template-based CMO rewrite (Layer 2 placeholder).

Until the owner provides an LLM key, this module produces engaging copy from a set of
source facts using template strings — no hallucinated numbers, no invented claims.
It is intentionally "richer than dry" while staying within the honesty floor.

The LLM rewrite slot REPLACES this function once a key is available;
the honesty-gate check (Layer 3) remains in place regardless.

Usage::
    from spa_core.cmo.template_rewriter import rewrite
    result = rewrite(source_facts, date_str)
    if result["gate_passed"]:
        draft = result["draft_text"]
    else:
        draft = result["fallback_text"]  # dry deterministic summary (always gate-passes)
"""
from __future__ import annotations

import re
from typing import Any

from spa_core.cmo.honesty_gate import check_draft, GateResult


def _fmt_pct(v: Any, *, default: str = "N/A") -> str:
    try:
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return default


def _fmt_usd(v: Any, *, default: str = "N/A") -> str:
    try:
        n = float(v)
        if n >= 1_000_000:
            return f"${n/1_000_000:.2f}M"
        if n >= 1_000:
            return f"${n:,.0f}"
        return f"${n:.2f}"
    except (TypeError, ValueError):
        return default


def _fmt_days(v: Any, *, default: str = "N/A") -> str:
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return default


# ── Template bank (indexed by which facts are available) ───────────────────────

def _build_draft(facts: dict[str, Any], date_str: str) -> str:
    """Compose a draft from the richest applicable template. Returns draft text."""
    n_days = facts.get("n_evidenced_days") or facts.get("track_days")
    needed = facts.get("days_needed", 30)
    cum = facts.get("cumulative_return_pct")
    dd = facts.get("max_drawdown_from_peak_pct")
    apy = facts.get("paper_apy_pct") or facts.get("apy_pct")
    nav = facts.get("nav_usd") or facts.get("end_equity")
    refusals = facts.get("refusal_count")
    entries = facts.get("decision_count")

    # ── richer template (track + performance + refusals available) ────────────
    if n_days is not None and cum is not None and dd is not None and refusals is not None:
        dd_abs = abs(float(dd))
        ref_txt = (
            f"{int(refusals)} of {int(entries)} yield opportunities declined"
            if entries is not None
            else f"{int(refusals)} yield opportunities declined"
        )
        return (
            f"Week {date_str}: Paper track reaches {_fmt_days(n_days)}/{_fmt_days(needed)} "
            f"evidenced days — cumulative return {_fmt_pct(cum)}, "
            f"maximum drawdown {_fmt_pct(dd_abs)} from peak. "
            f"The refusal engine made {ref_txt} on risk grounds "
            f"(high-tail compensation, depeg exposure, or insufficient liquidity). "
            f"Simulated paper results only — not real capital. "
            f"Past performance is no guarantee. "
            f"All yield carries risk: drawdown and loss of principal are possible. "
            f"This is not financial advice."
        )

    # ── medium template (track + APY, no refusal detail) ─────────────────────
    if n_days is not None and apy is not None:
        return (
            f"Paper track update ({date_str}): {_fmt_days(n_days)}/{_fmt_days(needed)} "
            f"evidenced days at a paper APY of {_fmt_pct(apy)}. "
            f"{'NAV is ' + _fmt_usd(nav) + '. ' if nav is not None else ''}"
            f"Simulated results only — not real capital. "
            f"Past performance is no guarantee. "
            f"There is risk of drawdown and loss. "
            f"Not financial advice."
        )

    # ── minimal template (track days only) ───────────────────────────────────
    if n_days is not None:
        return (
            f"Paper track update ({date_str}): {_fmt_days(n_days)}/{_fmt_days(needed)} "
            f"evidenced days. "
            f"Simulated results only — not real capital. "
            f"Past performance is no guarantee. "
            f"Drawdown and loss are possible. "
            f"Not financial advice."
        )

    # ── refusal-only template ─────────────────────────────────────────────────
    if refusals is not None:
        ref_txt = (
            f"{int(refusals)} of {int(entries)}"
            if entries is not None
            else str(int(refusals))
        )
        return (
            f"Refusal engine digest ({date_str}): {ref_txt} "
            f"yield opportunities declined on risk grounds "
            f"(tail compensation, depeg risk, or low liquidity). "
            f"Paper research only — not real capital. "
            f"Not a guarantee of any return. "
            f"Risk of loss is always present. "
            f"Not financial advice."
        )

    # ── ultra-minimal fallback ────────────────────────────────────────────────
    return (
        f"Research digest {date_str}. "
        f"Paper advisory research only — not real capital. "
        f"Past performance is no guarantee. "
        f"Risk of loss is always present. "
        f"Not financial advice."
    )


def _fallback_dry(facts: dict[str, Any], date_str: str) -> str:
    """Produce the minimal dry fallback that always passes the honesty gate."""
    n_days = facts.get("n_evidenced_days") or facts.get("track_days")
    needed = facts.get("days_needed", 30)
    parts = [f"Research digest {date_str}."]
    if n_days is not None:
        parts.append(f"Paper track: {_fmt_days(n_days)}/{_fmt_days(needed)} days.")
    parts.append(
        "Simulated paper results only — not real capital. "
        "Past performance is no guarantee. "
        "Risk of drawdown and loss is always present. "
        "Not financial advice."
    )
    return " ".join(parts)


def rewrite(
    source_facts: dict[str, Any],
    date_str: str,
    *,
    extra_allowed_numbers: list[float] | None = None,
) -> dict[str, Any]:
    """Produce an engaging CMO draft from source_facts and run it through the honesty gate.

    Args:
        source_facts: Dict of known-good facts (track days, APY, NAV, refusals…).
        date_str: ISO date string for the entry (e.g. "2026-07-15").
        extra_allowed_numbers: Additional numbers explicitly allowed (optional).

    Returns a dict::
        {
            "gate_passed": bool,
            "draft_text": str,           # template draft (gate may have rejected it)
            "fallback_text": str,        # always-passing dry fallback
            "gate_result": GateResult,   # from honesty_gate.check_draft
            "rewrite_method": str,       # "template_v1"
        }
    """
    draft = _build_draft(source_facts, date_str)
    fallback = _fallback_dry(source_facts, date_str)

    gate = check_draft(draft, source_facts, extra_allowed_numbers=extra_allowed_numbers)

    return {
        "gate_passed": gate.passed,
        "draft_text": draft,
        "fallback_text": fallback,
        "gate_result": gate,
        "rewrite_method": "template_v1",
    }
