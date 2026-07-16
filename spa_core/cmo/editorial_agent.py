"""spa_core/cmo/editorial_agent.py — CMO editorial DRAFT runner (the live agent).

The prior CMO layer (docs/CMO_EDITORIAL_LAYER.md) built the *library*: template_rewriter → honesty_gate
→ draft_store, wired end-to-end by `pipeline.run_pipeline`. What was missing was a LIVE runner + launchd
wiring. THIS module is that runner: it reads the real track facts (data/track_ledger.json + the
hash-chained refusal log), calls `pipeline.run_pipeline`, and lets the prior pipeline do the honest work
(rewrite → gate → draft store). It does NOT reimplement the rewrite or the gate.

It NEVER publishes — flow B (owner approves a draft via /api/cmo/drafts/{id}/approve → publish) is the
owner's step. Deterministic · stdlib · fail-CLOSED (no source data → no draft, never fabricated).

CLI::
    python3 -m spa_core.cmo.editorial_agent            # build today's draft (if source data present)
    python3 -m spa_core.cmo.editorial_agent --check    # build via pipeline, print result, do NOT store
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.cmo.pipeline import run_pipeline
from spa_core.cmo.draft_store import DraftStore

log = logging.getLogger("spa.cmo.editorial_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEDGER = _REPO_ROOT / "data" / "track_ledger.json"
_DECISIONS = _REPO_ROOT / "data" / "rates_desk" / "decision_log.jsonl"


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _load_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _count_refusals(p: Path) -> tuple[Optional[int], Optional[int]]:
    """(decision_count, refusal_count) from the hash-chained decision log, or (None, None)."""
    entries = refusals = 0
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            entries += 1
            if d.get("approved") is False:
                refusals += 1
    except OSError:
        return (None, None)
    return (entries, refusals)


def load_source_facts(*, ledger_path: Optional[Path] = None,
                      decisions_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Build the honest source-facts dict the pipeline consumes, from the live track + refusal log.
    Returns None (fail-CLOSED) when neither the ledger nor the refusal log yields real data."""
    ledger = _load_json(ledger_path or _LEDGER)
    entries, refusals = _count_refusals(decisions_path or _DECISIONS)
    n_days = ledger.get("n_evidenced_days")
    if n_days is None and refusals is None:
        return None  # no real data → no draft (never fabricate)
    facts: dict[str, Any] = {}
    if n_days is not None:
        facts["n_evidenced_days"] = n_days
        facts["days_needed"] = ledger.get("days_needed", 30)
        if ledger.get("cumulative_return_pct") is not None:
            facts["cumulative_return_pct"] = ledger.get("cumulative_return_pct")
        if ledger.get("max_drawdown_from_peak_pct") is not None:
            facts["max_drawdown_from_peak_pct"] = ledger.get("max_drawdown_from_peak_pct")
    if refusals is not None:
        facts["refusal_count"] = refusals
        facts["decision_count"] = entries
    return facts


def run(*, now: Optional[datetime] = None, write: bool = True,
        drafts_dir: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
        decisions_path: Optional[Path] = None) -> dict:
    """Build today's draft through the prior CMO pipeline and (if new) store it. Never raises;
    fail-CLOSED (no data → created:False). The pipeline handles rewrite → honesty_gate → draft_store."""
    facts = load_source_facts(ledger_path=ledger_path, decisions_path=decisions_path)
    if facts is None:
        return {"created": False, "reason": "no source data (fail-closed)"}
    date_str = _now(now).strftime("%Y-%m-%d")
    store = DraftStore(drafts_dir) if drafts_dir is not None else None
    if not write:
        # dry-run: run the rewrite+gate without persisting a draft
        from spa_core.cmo.template_rewriter import rewrite as _rewrite
        rw = _rewrite(facts, date_str)
        return {"created": False, "gate_passed": rw["gate_passed"],
                "violations": rw["gate_result"].violations, "text_used":
                (rw["draft_text"] if rw["gate_passed"] else rw["fallback_text"])}
    try:
        result = run_pipeline(facts, date_str, store=store)
    except Exception as exc:  # noqa: BLE001 — a draft failure must never crash the agent
        log.warning("cmo editorial run_pipeline failed: %s", exc)
        return {"created": False, "reason": f"pipeline error: {exc}"}
    return {"created": True, "draft_id": result.get("draft_id"),
            "gate_passed": result.get("gate_passed"), "status": result.get("status")}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.cmo.editorial_agent",
                                 description="CMO editorial DRAFT runner (delegates to pipeline; never publishes)")
    ap.add_argument("--check", action="store_true", help="build via pipeline + print, do NOT store")
    args = ap.parse_args(argv)
    res = run(write=not args.check)
    print(json.dumps(res, ensure_ascii=False, indent=2 if args.check else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
