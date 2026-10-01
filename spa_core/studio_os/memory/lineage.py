"""Lineage — IDEA → RFC/research → DECISION → TASK → IMPLEMENTATION → TEST/EVIDENCE → RELEASE → OUTCOME.

Derived on demand from identifiers that ALREADY exist (no mass migration of history):
    decision      the ADR file (docs/decisions/ or the Bridge's docs/adr/)
    idea          docs/ideas notes and the ADR's own «Context» that name an owner directive / idea
    tasks         tracker cards whose text cites the ADR id
    implementation commits on origin/main (full mirror clone) or the Bridge repo whose message cites it
    tests         test files touched by those commits
    release       SPA: on origin/main ⇒ delivered; in the production tree ⇒ the code sync's origin_main
                  contains it. Bridge: release tags containing the commit.
    outcome       later journal entries citing it; SUPERSEDED/REJECTED from the truth layer
Each link carries an origin: EXPLICIT (the id is written in the linked record) or HEURISTIC (a name
match). The older overlay `spa_core.studio_os.links` (ADR-497) is merged in when a record exists.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import sources as src

#: the production code sync's own record of which origin/main the prod tree carries (an environment door —
#: injectable so a test never reads the host's production state)
SYNC_STATUS = Path.home() / "Documents" / "SPA_Claude" / "data" / "code_sync_status.json"


def _sync_status_path() -> Path:
    return Path(os.environ.get("SPA_MEMORY_SYNC_STATUS") or SYNC_STATUS)


def _git(repo: Path, *args: str, timeout: float = 20.0) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _find_decision(adr: str) -> Optional[Dict]:
    rs = src.roots()
    for root, rel in (("spa", "docs/decisions"), ("bridge", "docs/adr")):
        d = rs[root] / rel
        if not d.is_dir():
            continue
        for p in sorted(d.glob(f"{adr}-*.md")) + sorted(d.glob(f"{adr}.md")):
            return {"repo": root, "path": f"{rel}/{p.name}", "file": p}
    return None


def _mentions(root: str, pattern: str, needle: str, limit: int = 12) -> List[Dict]:
    base = src.roots()[root]
    out = []
    if not base.is_dir():
        return out
    rx = re.compile(re.escape(needle) + r"(?![\w.])")
    for p in sorted(base.glob(pattern)):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = rx.search(t)
        if m:
            line = t[max(0, t.rfind("\n", 0, m.start()) + 1): t.find("\n", m.end()) if t.find("\n", m.end()) > 0 else None]
            out.append({"ref": f"{root}:{p.relative_to(base).as_posix()}", "excerpt": line.strip()[:200],
                        "origin": "EXPLICIT"})
            if len(out) >= limit:
                break
    return out


def lineage(adr: str) -> Dict:
    adr = adr.strip().upper()
    rs = src.roots()
    dec = _find_decision(adr)
    if dec is None:
        return {"subject": adr, "found": False, "status": "UNKNOWN",
                "note": "no decision file with this id in docs/decisions/ or the Bridge docs/adr/"}
    text = dec["file"].read_text(encoding="utf-8", errors="replace")
    from .truth import status_of_text
    out: Dict = {"subject": adr, "found": True,
                 "decision": {"ref": f"{dec['repo']}:{dec['path']}", "title": (re.search(r"^#\s*(.+)$", text, re.M) or [None, adr])[1],
                              "status": status_of_text(text) or "UNKNOWN", "origin": "EXPLICIT"}}
    ctx = re.search(r"(?is)##\s*(?:context|контекст)\s*\n(.{0,900})", text)
    directive = re.search(r"(?i)(owner directive[^.\n]{0,160}|решени[ея] владельца[^.\n]{0,160}|приказ[^.\n]{0,120})", text)
    out["idea"] = {"origin_text": directive.group(1).strip() if directive else None,
                   "context_excerpt": ctx.group(1).strip()[:500] if ctx else None,
                   "ideas": _mentions("spa", "docs/ideas/*.md", adr, 5),
                   "origin": "EXPLICIT" if directive else "UNKNOWN"}
    out["tasks"] = _mentions("spa", "nimbalyst-local/tracker/*.md", adr, 10)
    repo = rs[dec["repo"]]
    log = _git(repo, "log", "--all" if dec["repo"] == "bridge" else "origin/main", f"--grep={adr}",
               "--format=%H|%cI|%s", "-n", "30") or ""
    commits = []
    for line in log.splitlines():
        h, d, s = (line.split("|", 2) + ["", ""])[:3]
        files = (_git(repo, "show", "--name-only", "--format=", h) or "").split()
        commits.append({"commit": h[:12], "date": d, "subject": s[:160], "files": len(files),
                        "tests": [f for f in files if "/tests/" in f or f.startswith("tests/")][:8],
                        "origin": "EXPLICIT"})
    out["implementation"] = commits
    out["tests"] = sorted({t for c in commits for t in c["tests"]})
    rel: Dict = {}
    if dec["repo"] == "spa" and commits:
        rel["delivered_to_origin_main"] = True
        try:
            sync = json.loads(_sync_status_path().read_text())
            synced = sync.get("origin_main")
            first = commits[-1]["commit"]
            anc = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", first, synced],
                                 capture_output=True).returncode == 0 if synced else None
            rel["in_production_tree"] = anc
            rel["production_sync"] = (synced or "")[:12]
        except (OSError, ValueError):
            rel["in_production_tree"] = None
    if dec["repo"] == "bridge" and commits:
        tags = _git(repo, "tag", "--contains", commits[-1]["commit"]) or ""
        rel["release_tags"] = [t for t in tags.split() if t.startswith("b")][:6]
    out["release"] = rel or {"note": "no commit cites this decision — release UNKNOWN"}
    outcome = _mentions("spa", "docs/journal/2026-W*.md", adr, 6)
    out["outcome"] = {"journal": outcome, "status": out["decision"]["status"]}
    try:
        from spa_core.studio_os.links import all_links
        overlay = {k: v for k, v in all_links().items() if adr in json.dumps(v)}
        if overlay:
            out["overlay_ADR_497"] = overlay
    except Exception:  # noqa: BLE001 — the overlay is optional evidence
        pass
    return out


def render(l: Dict) -> str:
    if not l.get("found"):
        return f"{l['subject']}: UNKNOWN — {l.get('note')}"
    L = [f"{l['subject']} — {l['decision']['title']} [{l['decision']['status']}] ({l['decision']['ref']})"]
    i = l["idea"]
    L.append("idea/origin: " + (i["origin_text"] or "UNKNOWN") + (f"; ideas: {[x['ref'] for x in i['ideas']]}" if i["ideas"] else ""))
    L.append(f"tasks: {len(l['tasks'])} card(s)" + (": " + ", ".join(t['ref'].split('/')[-1] for t in l['tasks'][:4]) if l["tasks"] else ""))
    L.append(f"implementation: {len(l['implementation'])} commit(s)" +
             (": " + ", ".join(f"{c['commit']} {c['date'][:10]}" for c in l["implementation"][:4]) if l["implementation"] else ""))
    L.append(f"tests: {', '.join(l['tests'][:5]) or 'none found'}")
    L.append(f"release: {l['release']}")
    L.append(f"outcome: {len(l['outcome']['journal'])} journal mention(s); status {l['outcome']['status']}")
    return "\n".join(L)
