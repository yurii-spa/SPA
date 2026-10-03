"""spa_core/studio_os/provenance.py — «why does this exist, who made it, who owns it, may it go?» (ADR-551).

Resolves ARTIFACT → PURPOSE → SOURCE TASK → SOURCE DECISION → PRODUCER ROLE → PRODUCER RUN →
REVIEWER → RELEASE → CURRENT OWNER → CURRENT STATUS from three canonical sources and nothing else:

1. ``architecture/provenance.json`` — the human/decision facts of significant artifacts;
2. ``architecture/manifest.json`` — producer agent, consumers and passport goal of fleet data artifacts;
3. git history (the origin-synced mirror) — first/last commit, model co-authors, session links,
   ADR and cycle references, and whether the last change is released (ancestor of the deployed
   origin commit recorded by code-sync).

A link that cannot be proven is ``UNKNOWN``. ``UNKNOWN_PURPOSE`` is NEVER «safe to remove»: the
removal verdict is never a plain yes — at best «only with a Change-Record» (ADR-537), and for
anything public also the owner (ADR-285 subject 2).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "architecture" / "provenance.json"
MANIFEST = REPO / "architecture" / "manifest.json"
STATUSES = ("ACTIVE", "EXPERIMENTAL", "SUPERSEDED", "DEPRECATED", "UNKNOWN_PURPOSE")
UNKNOWN = "UNKNOWN"


def git_root() -> Path:
    """Git facts come from the origin-synced mirror when present (the production checkout's own git
    is weeks behind by design, ADR-152); tests and CI fall back to this repository."""
    env = os.environ.get("SPA_PROVENANCE_GIT_ROOT")
    if env:
        return Path(env)
    mirror = Path.home() / "Documents" / "SPA_mirror"
    return mirror if (mirror / ".git").exists() else REPO


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _git(args: list[str], root: Path) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def find_record(query: str, reg: Optional[dict] = None) -> Optional[dict]:
    reg = reg or load_registry()
    q = query.strip().lstrip("./")
    for a in reg["artifacts"]:
        if a["id"] == q:
            return a
    for a in reg["artifacts"]:
        for anc in a["anchors"]:
            path, _, mark = anc.partition("#")
            if q == anc or q == path or (path.endswith("/") and q.startswith(path)):
                return a
            if mark and q == mark:
                return a
    return None


def manifest_artifact(path: str, manifest_path: Path = MANIFEST) -> Optional[dict]:
    try:
        m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    q = path.strip().lstrip("./")
    for art in m.get("artifacts", []):
        if art.get("path") in (q, q.replace("data/", ""), "data/" + q):
            producer = art.get("producer")
            agent = next((a for a in m.get("agents", []) if a.get("label") == producer), None)
            return {"artifact": art, "agent": agent}
    return None


_ADR = re.compile(r"\bADR-\d{3}\b")
_CYCLE = re.compile(r"(?:цикл|cycle)\s*#(\d+)", re.I)
_SESSION = re.compile(r"claude\.ai/code/session_\w+")
_COAUTH = re.compile(r"^Co-Authored-By:\s*(.+?)\s*<", re.M)


def _log(root: Path, args: list[str]) -> list[dict]:
    fmt = "%H%x1f%cI%x1f%an%x1f%s%x1f%b%x1e"
    out = _git(["log", "--format=" + fmt, *args], root)
    commits = []
    for rec in (out or "").strip("\x1e\n").split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) >= 5:
            sha, when, author, subj, body = parts[:5]
            msg = subj + "\n" + body
            commits.append({"sha": sha[:9], "date": when, "author": author, "subject": subj[:160],
                            "adrs": sorted(set(_ADR.findall(msg))), "cycles": _CYCLE.findall(msg),
                            "sessions": _SESSION.findall(msg), "co_authors": _COAUTH.findall(msg)})
    return commits


def git_facts(path: str, *, root: Optional[Path] = None, marker: str = "") -> dict:
    """First commit of the component (by ``marker`` content search when given, else of the file),
    last commit and references from the file's own history. Absent history ⇒ UNKNOWN."""
    root = root or git_root()
    if not (root / path).exists():
        return {"state": UNKNOWN, "reason": f"{path} not in {root}"}
    file_log = _log(root, ["--follow", "--", path])
    if not file_log:
        return {"state": UNKNOWN, "reason": "no git history found"}
    # The component's origin is searched across ALL refs (ADR-537 memory-before-change: the first
    # appearance on main can be a bulk re-add, and a shallow clone hides older main history — measured
    # 2026-10-03 on the production clone: main alone gave a 10-02 commit, --all gave e3263507b).
    comp = _log(root, ["--all", "-S", marker, "--", path]) if marker else []
    shallow = (_git(["rev-parse", "--is-shallow-repository"], root) or "").strip() == "true"
    first = comp[-1] if comp else file_log[-1]
    basis = f"content «{marker}», all refs" if comp else "file"
    if shallow:
        # A shallow boundary commit «adds» everything below it: if that is what we found, it is the
        # earliest VISIBLE commit, not the origin — say so instead of inventing an origin.
        sp = (_git(["rev-parse", "--git-path", "shallow"], root) or "").strip()
        try:
            boundary = {ln.strip()[:9] for ln in (Path(sp) if os.path.isabs(sp) else root / sp).read_text().splitlines()}
        except OSError:
            boundary = set()
        if first["sha"] in boundary or not comp:
            basis += " — SHALLOW clone: earliest VISIBLE commit, the true first is UNKNOWN here"
    last = file_log[0]
    return {"state": "MEASURED", "first": first, "first_basis": basis, "shallow_clone": shallow,
            "last": last, "n_commits": len(file_log),
            "adrs": sorted({a for c in file_log for a in c["adrs"]}),
            "models": sorted({m for c in file_log for m in c["co_authors"]}),
            "sessions": sorted({s for c in file_log for s in c["sessions"]}),
            "cycles": sorted({x for c in file_log for x in c["cycles"]}, key=int)}


def _is_ancestor(sha: str, of: str, root: Path) -> Optional[bool]:
    """git merge-base --is-ancestor: 0 ⇒ True, 1 ⇒ False, anything else (unknown sha, missing ref,
    timeout) ⇒ None — NOT MEASURED, never read as «not released» (review 2026-10-03)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, of],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return True if r.returncode == 0 else False if r.returncode == 1 else None


def release_of(sha: Optional[str], *, root: Optional[Path] = None, data_dir: Optional[Path] = None) -> dict:
    """RELEASED needs BOTH proofs: the commit is on origin/main (the site builds every push to main) AND
    it is contained in the origin commit code-sync last delivered to production. A proof that cannot be
    read makes the answer UNKNOWN-flavoured, never RELEASED (inv. #17)."""
    if not sha:
        return {"state": UNKNOWN, "reason": "no commit"}
    root = root or git_root()
    on_main = _is_ancestor(sha, "origin/main", root)
    deployed = None
    try:
        if data_dir is None:
            from spa_core.utils.live_paths import live_data_dir
            data_dir = live_data_dir()
        cs = json.loads((Path(data_dir) / "code_sync_status.json").read_text(encoding="utf-8"))
        dsha = cs.get("origin_main")
        # code-sync writes origin_main for EVERY outcome, failures included — only a converged sync is
        # evidence that production runs it (second review 2026-10-03).
        if dsha and str(cs.get("result", "")).upper() not in ("IN_SYNC", "SYNCED"):
            dsha = None
        if dsha:
            deployed = {"origin_commit": dsha[:12], "checked_at": cs.get("timestamp"),
                        "contains": _is_ancestor(sha, dsha, root)}
    except (OSError, ValueError, ImportError):
        deployed = None
    if on_main is None:
        state = "UNKNOWN"
    elif not on_main:
        state = "NOT_ON_MAIN"
    elif deployed is None or deployed["contains"] is None:
        state = "ON_MAIN_PRODUCTION_UNKNOWN"
    else:
        state = "RELEASED" if deployed["contains"] else "ON_MAIN_NOT_SYNCED"
    return {"state": state, "on_origin_main": on_main, "production": deployed or UNKNOWN}


def removal_verdict(rec: dict) -> dict:
    st = rec.get("status", "UNKNOWN_PURPOSE")
    cons = rec.get("consumers") or []
    public = str(rec.get("kind", "")).startswith("site") or rec.get("owner_role") == "owner"
    if st == "UNKNOWN_PURPOSE":
        v, why = "NO", "purpose unknown — UNKNOWN is not OBSOLETE; restore its origin first (ADR-537)"
    elif st in ("ACTIVE", "EXPERIMENTAL"):
        v, why = "NO", f"{st.lower()} and in use ({len(cons)} known consumer(s))"
    elif cons:
        v, why = "NO", f"{st.lower()} but still consumed by: {', '.join(cons[:4])}"
    else:
        v, why = "ONLY_WITH_CHANGE_RECORD", f"{st.lower()}, no known consumer"
    if v != "NO" and public:
        v, why = "ONLY_WITH_CHANGE_RECORD_AND_OWNER", why + "; public or owner-owned (ADR-285 subject 2)"
    return {"may_remove": v, "why": why}


def explain(query: str, *, reg: Optional[dict] = None, root: Optional[Path] = None,
            data_dir: Optional[Path] = None) -> dict:
    reg = reg or load_registry()
    rec = find_record(query, reg)
    out: dict = {"query": query}
    if rec:
        out["record"] = {k: v for k, v in rec.items()}
        out["source"] = "architecture/provenance.json"
        anchor = rec["anchors"][0]
        path, _, mark = anchor.partition("#")
    else:
        path, _, mark = query.partition("#")
        man = manifest_artifact(path)
        if man:
            ag = man["agent"] or {}
            pp = ag.get("passport") or {}
            rec = {"id": path, "kind": "agent-data", "anchors": [path],
                   "purpose": pp.get("goal") or ag.get("intent") or UNKNOWN,
                   "purpose_source": "architecture/manifest.json (agent passport)",
                   "source_task": UNKNOWN, "source_decision": ", ".join(ag.get("governed_by") or []) or UNKNOWN,
                   "producer_role": ag.get("role") or UNKNOWN, "producer_run": man["artifact"].get("producer") or UNKNOWN,
                   "reviewer": UNKNOWN, "owner_role": UNKNOWN,
                   "status": "ACTIVE" if str(man["artifact"].get("status", "")).lower() in ("active", "live", "") else
                   str(man["artifact"].get("status")).upper(),
                   "consumers": man["artifact"].get("consumers") or []}
            out["record"], out["source"] = rec, "architecture/manifest.json"
        else:
            rec = {"id": query, "anchors": [query], "purpose": UNKNOWN, "purpose_source": UNKNOWN,
                   "source_task": UNKNOWN, "source_decision": UNKNOWN, "producer_role": UNKNOWN,
                   "producer_run": UNKNOWN, "reviewer": UNKNOWN, "owner_role": UNKNOWN,
                   "status": "UNKNOWN_PURPOSE", "consumers": []}
            out["record"], out["source"] = rec, "none — not in provenance.json nor manifest.json"
    if not path.startswith("data/"):
        # A distinctive anchor (calc-slider, stop_reference) is searched by content (-S), so the FIRST
        # commit is the one that introduced the component, not the file; a short one (#sub) would
        # match everywhere, so the file's own history is used instead.
        gf = git_facts(path, root=root, marker=mark if len(mark) >= 6 else "")
        if mark and gf.get("state") != "MEASURED":
            gf = git_facts(path, root=root)
        out["git"] = gf
        out["release"] = release_of((gf.get("last") or {}).get("sha"), root=root, data_dir=data_dir)
    out["removal"] = removal_verdict(out["record"])
    return out


def render(x: dict) -> str:
    r = x["record"]
    lines = [f"# {r['id']}  [{r.get('status')}]  (source: {x['source']})",
             f"purpose:          {r.get('purpose')}",
             f"purpose source:   {r.get('purpose_source')}",
             f"source task:      {r.get('source_task')}",
             f"source decision:  {r.get('source_decision')}",
             f"producer role:    {r.get('producer_role')}",
             f"producer run:     {r.get('producer_run')}",
             f"reviewer:         {r.get('reviewer')}",
             f"owner:            {r.get('owner_role')}"]
    if r.get("supersedes"):
        lines.append(f"supersedes:       {r['supersedes']}")
    g = x.get("git")
    if g and g.get("state") == "MEASURED":
        f, l = g["first"], g["last"]
        lines += [f"first commit:     {f['sha']} {f['date'][:10]} «{f['subject'][:90]}» (by {g.get('first_basis')})",
                  f"last commit:      {l['sha']} {l['date'][:10]} «{l['subject'][:90]}»",
                  f"ADRs in history:  {', '.join(g['adrs']) or '—'}",
                  f"models (trailer): {', '.join(g['models']) or 'none recorded'}",
                  f"sessions:         {', '.join(g['sessions']) or 'none recorded'}"]
    elif g:
        lines.append(f"git:              {g.get('state')} — {g.get('reason')}")
    rel = x.get("release")
    if rel:
        prod = rel.get("production")
        lines.append(f"release:          {rel['state']}"
                     + (f" (production {prod['origin_commit']} @ {prod['checked_at']})" if isinstance(prod, dict) else ""))
    lines.append(f"may remove:       {x['removal']['may_remove']} — {x['removal']['why']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="artifact provenance (ADR-551)")
    ap.add_argument("cmd", choices=("explain", "list"))
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        reg = load_registry()
        for r in reg["artifacts"]:
            print(f"{r['id']:<32} {r['status']:<16} owner={r['owner_role']:<10} {r['anchors'][0]}")
        return 0
    x = explain(a.query)
    print(json.dumps(x, ensure_ascii=False, indent=1) if a.json else render(x))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
