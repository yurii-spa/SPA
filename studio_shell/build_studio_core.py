#!/usr/bin/env python3
"""Emit Studio OS Core read models for the desktop Command Center — thin wrappers over the SHARED
projectors spa_core.studio_os.* (same canon the Telegram gateway + continuity test read)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
_now = datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    # lazy import — studio_shell/ is outside the autosync dirs (test_unsynced_hard_imports)
    sys.path.insert(0, str(REPO))
    from spa_core.studio_os.context import build_context_pack, stamp
    from spa_core.studio_os.registry import load_registry
    from spa_core.studio_os import search as S
    from spa_core.studio_os.research import build_research_model
    from spa_core.studio_os.repo_status import status as repo_status
    ctx = stamp(build_context_pack("earn-defi-product"), _now)
    (HERE / "project_context.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "projects.json").write_text(json.dumps(load_registry(), ensure_ascii=False, indent=1), encoding="utf-8")
    # client search index — cap text so the file stays small, plus a keyword field (distinctive tokens
    # from the FULL text) so multi-word concepts like "Position Passport" stay findable cheaply.
    # Reports carry real concept prose (find "Position Passport"); decisions a short snippet; tasks are
    # numerous so title-only + capped. Keeps the client file ~a few hundred KB.
    CAP = {"report": 7000, "decision": 220, "research": 300}
    task_seen = 0
    idx = []
    for it in S.build_index():
        t = it["type"]
        if t == "task":
            task_seen += 1
            if task_seen > 300:
                continue
            txt = ""
        else:
            txt = (it.get("text") or "")[:CAP.get(t, 120)]
        idx.append({"type": t, "id": it["id"][:60], "title": it["title"][:90], "ref": it["ref"], "kw": txt})
    # authority class per index item (a report must never look equal to an accepted ADR)
    AUTHORITY = {"project": "CANONICAL", "decision": "ACCEPTED_DECISION", "decision-draft": "PROPOSED_DECISION",
                 "task": "CANONICAL_WORK", "research": "CANONICAL_RESEARCH", "release": "CANONICAL",
                 "report": "DERIVED_REPORT", "handoff": "HANDOFF"}
    for it in idx:
        it["authority"] = AUTHORITY.get(it["type"], "DERIVED_REPORT")
    (HERE / "search_index.json").write_text(json.dumps({"generated_at": _now, "items": idx},
                                                       ensure_ascii=False), encoding="utf-8")
    (HERE / "research.json").write_text(json.dumps(build_research_model(), ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "repo_status.json").write_text(json.dumps(repo_status(), ensure_ascii=False, indent=1), encoding="utf-8")
    # Task-link overlay: persisted (new work) merged with PROVABLE derivations from mission-work text
    # (project_id by keyword, decision_refs = ADR ids literally named). Never a guessed relationship.
    import re as _re2
    from spa_core.studio_os.links import all_links
    rm2 = json.loads((HERE / "read_model.json").read_text(encoding="utf-8")) if (HERE / "read_model.json").exists() else {}
    persisted = all_links()   # per-task records (EXPLICIT) + legacy backread
    derived = {}
    for w in (rm2.get("work") or []):
        wid = w.get("id") or ""
        blob = " ".join(str(w.get(k, "")) for k in ("title", "request_summary", "reason_code"))
        adrs = sorted(set(_re2.findall(r"ADR[-_]\d+", blob)))
        low = blob.lower()
        proj = ("investment-engine" if _re2.search(r"риск|riskpolicy|adapter|kill|allocat|tvl|apy|адаптер", low)
                else "earn-defi-product" if _re2.search(r"сайт|landing|честн|доходност", low) else "studio-os")
        # per-field origin (ADR-497): project_id from keywords is HEURISTIC; decision_refs literally named = DERIVED
        entry = {"project_id": proj, "_origins": {"project_id": "HEURISTIC"},
                 "provenance": "derived from read_model.work text"}
        if adrs:
            entry["decision_refs"] = adrs
            entry["_origins"]["decision_refs"] = "DERIVED"
        # persisted (EXPLICIT) wins over derived; merge per-field origins so EXPLICIT overrides HEURISTIC
        p = persisted.get(wid, {})
        merged = {**entry, **p}
        merged["_origins"] = {**entry.get("_origins", {}), **p.get("_origins", {})}
        derived[wid] = merged
    (HERE / "task_links.json").write_text(json.dumps(
        {"generated_at": _now, "origin_legend": "EXPLICIT · DERIVED (verified ref) · HEURISTIC · UNKNOWN — "
         "only EXPLICIT/DERIVED feed canonical WHY (ADR-497)", "links": {**derived, **persisted}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"projects": len(load_registry().get("projects", [])),
                      "index_items": len(idx),
                      "next": ctx["next_recommended_work"]["value"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
