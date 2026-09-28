"""Project Context Pack — a generated, disposable projection so a fresh AI session bootstraps from canon
without the Owner re-explaining (ADR-495). Each section carries provenance. NOT a maintained truth source.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os.registry import get_project

REPO = Path(__file__).resolve().parents[2]


def _read(rel):
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def _json(rel):
    t = _read(rel)
    try:
        return json.loads(t) if t else None
    except ValueError:
        return None


def _sec(value, provenance, note=None):
    return {"value": value, "provenance": provenance, **({"note": note} if note else {})}


def _recent_decisions(n=6):
    idx = _read("docs/decisions/INDEX.md") or ""
    rows = re.findall(r"\|\s*(ADR-[\w-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", idx)
    out = [{"id": r[0], "summary": r[1].strip()[:140], "status": r[2].strip()} for r in rows[:n]]
    return out


def _drafts():
    d = REPO / "docs" / "decisions" / "drafts"
    if not d.exists():
        return []
    return [{"id": p.stem, "status": "PROPOSED"} for p in sorted(d.glob("*.md"))]


def _roadmap_snip():
    for f in ("docs/STATE.md", "MASTER_PLAN_v1.md"):
        t = _read(f)
        if t:
            lines = [ln.strip() for ln in t.splitlines() if ln.strip()][:6]
            return _sec("\n".join(lines), f)
    return _sec(None, "docs/STATE.md|MASTER_PLAN_v1.md", "roadmap source not found")


def _last_handoff():
    # per-session records (ADR-497) via the handoff reader, with legacy jsonl backread
    try:
        from spa_core.studio_os.handoff import last_handoff
        h = last_handoff()
        if h:
            return _sec(h, "data/handoffs/ (per-session) + legacy data/studio_handoffs.jsonl")
    except Exception:
        pass
    # fall back to the newest weekly journal filename
    jd = REPO / "docs" / "journal"
    files = sorted(jd.glob("2026-W*.md")) if jd.exists() else []
    return _sec({"journal": files[-1].name} if files else None,
                "docs/journal/", "no structured handoff yet; newest journal named")


def build_context_pack(project_id: str = "earn-defi-product") -> dict:
    proj = get_project(project_id) or {}
    rm = _json("studio_shell/read_model.json") or {}
    counts = (rm.get("overview") or {}).get("counts") or {}
    dec_items = ((rm.get("decisions") or {}).get("items")) or []
    sysd = rm.get("system") or {}
    health = sysd.get("health") or {}
    gl = _json("data/golive_status.json") or {}
    ra = (health.get("risk_alerts") or {}).get("count")

    owner_wait = (counts.get("owner_wait") or 0) + len(dec_items)
    blocked = counts.get("blocked") or 0
    failed = counts.get("failed") or 0

    # next recommended work — deterministic: owner-waiting first, then blocked, then failed
    if owner_wait:
        nxt = f"Resolve {owner_wait} owner-waiting decision(s) — see DECISIONS."
    elif blocked:
        nxt = f"Unblock {blocked} blocked task(s) — see WORK/blocked."
    elif failed:
        nxt = f"Investigate {failed} failed task(s) — see WORK/failed."
    else:
        nxt = "No owner-blocking work; continue the top roadmap item."

    return {
        "schema": "studio-os/context-pack/1",
        "generated_note": "Generated projection from canon (ADR-495). Disposable. Re-run any time.",
        "project": _sec({"id": project_id, "name": proj.get("name"), "status": proj.get("status")},
                        "data/studio_projects.json"),
        "purpose": _sec(proj.get("purpose"), "data/studio_projects.json"),
        "boundaries": _sec(proj.get("boundary") or
                           "Studio OS manages WORK ON the Investment Engine; the Investment Engine owns "
                           "financial truth. Read-only cockpit; no money path; RiskPolicy untouched.",
                           "data/studio_projects.json / ADR-495 / CLAUDE.md invariants"),
        "accepted_decisions": _sec(_recent_decisions(), "docs/decisions/INDEX.md"),
        "proposed_decisions": _sec(_drafts(), "docs/decisions/drafts/"),
        "roadmap": _roadmap_snip(),
        "work": _sec({"active": counts.get("running", 0), "owner_wait": owner_wait,
                      "blocked": blocked, "review": counts.get("review", 0),
                      "failed": failed, "done_recent": counts.get("done", 0)},
                     "studio_shell/read_model.json ← mission-state/v04/ledger.json"),
        "owner_decisions_waiting": _sec([{"title": d.get("title", "")[:120]} for d in dec_items[:5]],
                                        "studio_shell/read_model.json#decisions"),
        "recent_activity": _sec([a.get("text", "")[:100] for a in (rm.get("activity") or [])[:6]],
                                "studio_shell/read_model.json#activity"),
        "releases": _sec({"golive": f"{gl.get('passed', '?')}/{gl.get('total', '?')}"} if gl else None,
                         "data/golive_status.json"),
        "research": _sec({"maturity_register": (REPO / "docs" / "MATURITY_REGISTER.md").exists()},
                         "docs/MATURITY_REGISTER.md / research/"),
        "risks": _sec({"risk_alerts": ra if ra is not None else "unmeasured"},
                      "studio_shell/read_model.json#system.health.risk_alerts"),
        "runtime_health": _sec({"dispatch": "open" if (sysd.get("dispatch") or {}).get("open") else "closed"},
                               "studio_shell/read_model.json#system.dispatch"),
        "last_handoff": _last_handoff(),
        "next_recommended_work": _sec(nxt, "derived from work counts + owner queue"),
        "do_not_redesign": _sec(["FounderOS/JARVIS shell", "RiskPolicy v1.0", "the mission ledger",
                                 "the ADR decision authority", "the Telegram production bot (one bot)"],
                                "ADR-495 / CLAUDE.md invariants"),
    }


def stamp(pack: dict, now_iso: str) -> dict:
    pack["generated_at"] = now_iso
    return pack


if __name__ == "__main__":
    import sys
    pid = sys.argv[1] if len(sys.argv) > 1 else "earn-defi-product"
    p = stamp(build_context_pack(pid), datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print(json.dumps(p, ensure_ascii=False, indent=1))
