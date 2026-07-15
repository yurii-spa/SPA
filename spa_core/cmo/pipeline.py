"""spa_core/cmo/pipeline.py — CMO editorial pipeline (end-to-end, flow B).

Glues the three layers:
  1. Source facts  (supplied by caller from the raw journal / track ledger)
  2. Template rewrite  →  honesty gate
  3. Draft store  (status: draft)

The LLM rewrite layer (Layer 2b) drops in by replacing the `rewrite` call in `run_pipeline`
with an LLM call that still feeds through the same `check_draft` gate.

Usage::
    from spa_core.cmo.pipeline import run_pipeline
    result = run_pipeline(source_facts, date_str)
    print(result["draft_id"], result["status"])
"""
from __future__ import annotations

from typing import Any

from spa_core.cmo.template_rewriter import rewrite
from spa_core.cmo.draft_store import DraftStore


def run_pipeline(
    source_facts: dict[str, Any],
    date_str: str,
    *,
    store: DraftStore | None = None,
    extra_allowed_numbers: list[float] | None = None,
) -> dict[str, Any]:
    """Run the CMO editorial pipeline for a single daily digest entry.

    Args:
        source_facts: Dict of real facts (no fabricated numbers allowed).
        date_str: ISO date string (e.g. "2026-07-15").
        store: Inject a DraftStore for testing; defaults to the production store.
        extra_allowed_numbers: Additional whitelisted numbers for the honesty gate.

    Returns a dict::
        {
            "draft_id": str,
            "status": "draft",
            "gate_passed": bool,
            "text_used": str,    # draft_text if gate passed, else fallback_text
            "violations": list[str],
        }
    """
    if store is None:
        store = DraftStore()

    rw = rewrite(source_facts, date_str, extra_allowed_numbers=extra_allowed_numbers)

    # If the template draft fails the gate, fall back to the dry version.
    # The fallback is always gate-passing (pure templates with no numbers beyond source).
    text_used = rw["draft_text"] if rw["gate_passed"] else rw["fallback_text"]

    draft_id = store.save_draft(
        source_facts=source_facts,
        draft_text=rw["draft_text"],
        fallback_text=rw["fallback_text"],
        gate_result=rw["gate_result"],
        rewrite_method=rw["rewrite_method"],
        date_str=date_str,
    )

    return {
        "draft_id": draft_id,
        "status": "draft",
        "gate_passed": rw["gate_passed"],
        "text_used": text_used,
        "violations": rw["gate_result"].violations,
    }
