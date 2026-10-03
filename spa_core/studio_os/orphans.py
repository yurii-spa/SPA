"""spa_core/studio_os/orphans.py — orphaned artifacts and unsupervised agent output (ADR-551).

A deterministic REPORT. It never deletes, disables or edits anything: every finding carries a
recommended action for a human or a later, reviewed change.

Finding classes:
  page_without_lineage     a site page with no provenance record, no ADR in its git history and no
                           mention in the redesign specs
  undeclared_agent_output  a data/*.json written in the last 7 days that no manifest artifact declares
  artifact_without_reader  a manifest artifact with no declared consumer
  worker_not_in_manifest   a loaded launchd job the fleet manifest does not know
  manifest_worker_not_loaded  a manifest agent marked active that launchd does not run
  duplicate_canonical_doc  a *ROADMAP*.md other than docs/ROADMAP.md with no SUPERSEDED marker in itself
  stale_in_progress        a card in-progress / blocked with no transition for 14+ days
  abandoned_worktree       a registered git worktree idle 3+ days (removal only via the reaper)
  stray_temp_tree          an unregistered /private/tmp/spa_* directory (not disposable by rule ⇒ report)
  approved_never_published an agent output approved by the owner that no publisher ever took

Supervision: ``supervise()`` gives every autonomous output a disposition — ACCEPTED_INTO_BACKLOG,
MERGED, REVIEWED_AND_RELEASED, REJECTED, ARCHIVED_AS_RESEARCH or NEEDS_REVIEW (the default: an
output nobody looked at is never silently «fine»).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.studio_os import build_loop, provenance as prov

REPO = Path(__file__).resolve().parents[2]
DAY = 86400.0


def _f(artifact, reason, *, last_activity=None, owner="UNKNOWN", purpose="UNKNOWN", risk="MEDIUM",
       action="review", cls="") -> dict:
    return {"class": cls, "artifact": artifact, "reason": reason, "last_activity": last_activity,
            "known_owner": owner, "known_purpose": purpose, "removal_risk": risk,
            "recommended_action": action}


def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def pages_without_lineage(root: Path, reg: dict) -> list[dict]:
    specs = " ".join(Path(p).read_text(encoding="utf-8", errors="ignore")
                     for p in glob.glob(str(root / "docs" / "redesign" / "*.md")) +
                     [str(root / "docs" / "SITE_REDESIGN_MASTER_BRIEF.md")] if os.path.exists(p))
    anchored = {a.split("#")[0] for r in reg["artifacts"] for a in r["anchors"]}
    out = []
    for p in sorted((root / "landing" / "src" / "pages").rglob("*.astro")):
        rel = str(p.relative_to(root))
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if rel in anchored or 'http-equiv="refresh"' in txt or "Astro.redirect" in txt:
            continue
        route = "/" + str(p.relative_to(root / "landing" / "src" / "pages")).replace(".astro", "").replace("index", "").rstrip("/")
        # Route matched as a whole path token (review 2026-10-03: a bare substring «/a» matched anything).
        if route != "/" and re.search(r"(?<![\w/-])" + re.escape(route) + r"(?![\w-])", specs):
            continue
        log = prov._git(["log", "--format=%ct%x1f%s%x1f%b%x1e", "--", rel], root) or ""
        # A decision or a spec named in the page's history — anchored markers only (review 2026-10-03:
        # the bare word «owner» appears in nearly every commit body and hid every orphan).
        if re.search(r"\bADR-\d{3}\b|Owner-Approved:|owner-decision-|docs/redesign/|\bSELL SPRINT\b|"
                     r"\bredesign [A-Z]\d|\bM\d{1,2}\b", log):
            continue
        last = log.split("\x1f", 1)[0].strip() if log else None
        out.append(_f(rel, "no provenance record, no ADR/spec/owner reference in its history, not in the redesign specs",
                      last_activity=_iso(float(last)) if last and last.isdigit() else None,
                      risk="HIGH (public page; UNKNOWN purpose is not OBSOLETE)",
                      action="restore origin (git log --all -S, journals) and add a provenance record; do not remove",
                      cls="page_without_lineage"))
    return out


def manifest_checks(root: Path, data_dir: Path, *, launchctl_text: Optional[str] = None,
                    now: Optional[float] = None) -> list[dict]:
    now = now or time.time()
    try:
        man = json.loads((root / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [_f("architecture/manifest.json", f"NOT MEASURED: {exc}", cls="manifest_unreadable")]
    out = []
    declared = {a.get("path") for a in man.get("artifacts", [])}
    for a in man.get("artifacts", []):
        if not a.get("consumers"):
            out.append(_f(a["path"], "declared artifact with no declared consumer",
                          owner=a.get("producer", "UNKNOWN"), risk="LOW",
                          action="name its reader or retire the producer by decision", cls="artifact_without_reader"))
    for p in sorted(Path(data_dir).glob("*.json")):
        rel = f"data/{p.name}"
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if rel not in declared and now - mt < 7 * DAY:
            out.append(_f(rel, "written in the last 7 days but declared by no manifest artifact (producer/consumers unknown)",
                          last_activity=_iso(mt), risk="MEDIUM",
                          action="declare it in architecture/manifest.json (producer, consumers, slo) or stop producing it",
                          cls="undeclared_agent_output"))
    if launchctl_text is None:
        try:
            r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
            launchctl_text = r.stdout if r.returncode == 0 and r.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            launchctl_text = None
        if launchctl_text is None:
            out.append(_f("launchctl list", "NOT MEASURED: launchctl gave no answer — worker/manifest "
                          "parity not judged", risk="—", action="re-run", cls="worker_parity_unmeasured"))
    if launchctl_text is not None:
        loaded = {ln.split()[-1] for ln in launchctl_text.splitlines()[1:]
                  if ln.split() and re.match(r"com\.(spa|earn-defi|studiobridge)\.", ln.split()[-1])}
        known = {a.get("label") for a in man.get("agents", [])}
        for lab in sorted(loaded - known):
            out.append(_f(lab, "loaded launchd job not represented in architecture/manifest.json",
                          risk="MEDIUM", action="add an agent entry with passport (owner, purpose) or unload by decision",
                          cls="worker_not_in_manifest"))
        for a in man.get("agents", []):
            if a.get("label") not in loaded and str(a.get("status", "active")).lower() == "active":
                out.append(_f(a.get("label"), "manifest says active, launchd does not run it",
                              purpose=(a.get("passport") or {}).get("goal", "UNKNOWN"), risk="LOW",
                              action="mark retired/designed in the manifest or load it by decision",
                              cls="manifest_worker_not_loaded"))
    return out


def duplicate_docs(root: Path) -> list[dict]:
    out = []
    for p in sorted((root / "docs").glob("*ROADMAP*.md")):
        if p.name == "ROADMAP.md":
            continue
        head = "\n".join(p.read_text(encoding="utf-8", errors="ignore").splitlines()[:12])
        if not re.search(r"SUPERSEDED|УСТАРЕЛ|заменён", head, re.I):
            out.append(_f(f"docs/{p.name}", "roadmap-looking document without a SUPERSEDED marker in its own head "
                          "(ADR-527 marks it only in architecture/memory_truth.json)",
                          last_activity=_iso(p.stat().st_mtime), risk="LOW",
                          action="add a one-line SUPERSEDED header pointing at docs/ROADMAP.md",
                          cls="duplicate_canonical_doc"))
    return out


def stale_cards(tdir: Path, *, now: Optional[float] = None, days: int = 14) -> list[dict]:
    now = now or time.time()
    out = []
    for p in sorted(tdir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        fm, trail, _ = build_loop._frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        if fm.get("status") not in ("in-progress", "blocked"):
            continue
        ts = None
        if trail:
            m = re.match(r"(\d{4}-\d{2}-\d{2}T[\d:.]+)", trail[-1])
            if m:
                try:
                    ts = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    ts = None
        ts = ts or p.stat().st_mtime
        if now - ts > days * DAY:
            out.append(_f(p.name, f"{fm.get('status')} with no transition for {int((now - ts) / DAY)} days",
                          last_activity=_iso(ts), owner=fm.get("claimed_by", "UNKNOWN"),
                          purpose=fm.get("title", "UNKNOWN")[:120], risk="LOW",
                          action="resume, block with a reason, or close with evidence (set-status … --evidence)",
                          cls="stale_in_progress"))
    return out


def worktrees(repos: list[Path], *, now: Optional[float] = None, idle_days: float = 3.0) -> list[dict]:
    now = now or time.time()
    out, registered = [], set()
    for repo in repos:
        txt = prov._git(["worktree", "list", "--porcelain"], repo) or ""
        blocks = [b for b in txt.split("\n\n") if b.strip()]
        for i, b in enumerate(blocks):
            path = b.splitlines()[0].replace("worktree ", "").strip()
            registered.add(os.path.realpath(path))
            if i == 0:
                continue                                  # the main tree is never a candidate
            gitf = Path(path) / ".git"
            try:
                idx_dir = Path(gitf.read_text().split("gitdir:", 1)[1].strip()) if gitf.is_file() else None
                mt = (idx_dir / "index").stat().st_mtime if idx_dir and (idx_dir / "index").exists() else Path(path).stat().st_mtime
            except (OSError, IndexError):
                out.append(_f(path, "registered worktree whose path is gone or unreadable", risk="LOW",
                              action="git worktree prune (metadata only)", cls="abandoned_worktree"))
                continue
            if now - mt > idle_days * DAY:
                out.append(_f(path, f"registered worktree of {repo.name} idle {int((now - mt) / DAY)} days",
                              last_activity=_iso(mt), risk="LOW (only the reaper removes, after proving delivery)",
                              action="resource_guard --cleanup --apply (runs scripts/reap_stale_worktrees.py)",
                              cls="abandoned_worktree"))
    for p in sorted(glob.glob("/private/tmp/spa_*")):
        if os.path.isdir(p) and not os.path.islink(p) and os.path.realpath(p) not in registered:
            try:
                mt = os.stat(p).st_mtime
            except OSError:
                continue
            if now - mt > idle_days * DAY and not re.match(r".*/spa_test_backups_", p):
                out.append(_f(p, "unregistered /private/tmp/spa_* tree (not a worktree, not on the disposable allow-list)",
                              last_activity=_iso(mt), risk="MEDIUM (may hold undelivered work)",
                              action="inspect; if delivered, remove by hand or add its prefix to the allow-list by ADR",
                              cls="stray_temp_tree"))
    return out


def supervise(data_dir: Path, *, drafts_dir: Optional[Path] = None) -> dict:
    """Disposition of autonomous output. Each output ends in one of the six states; NEEDS_REVIEW is
    the default for anything nobody looked at."""
    out: dict = {"roles": {}}
    dd = Path(drafts_dir) if drafts_dir else Path(data_dir) / "cmo_drafts"
    items = []
    for p in sorted(dd.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        st = d.get("status")
        disp = {"draft": "NEEDS_REVIEW", "rejected": "REJECTED", "published": "REVIEWED_AND_RELEASED",
                "approved": "ACCEPTED_NOT_RELEASED"}.get(st, "NEEDS_REVIEW")
        items.append({"output": f"{dd.name}/{p.name}", "producer_role": "marketing",
                      "producer": "com.spa.cmo_editorial", "created_at": d.get("created_at"),
                      "review": {"honesty_gate": "passed" if d.get("gate_passed") else "failed → fallback text",
                                 "owner": st}, "disposition": disp,
                      "provenance": "architecture/provenance.json#marketing.cmo_drafts"})
    counts: dict = {}
    for it in items:
        counts[it["disposition"]] = counts.get(it["disposition"], 0) + 1
    out["roles"]["marketing"] = {"agent": "com.spa.cmo_editorial", "outputs": len(items), "dispositions": counts,
                                 "finding": ("approved drafts have no publisher — they end nowhere"
                                             if counts.get("ACCEPTED_NOT_RELEASED") else None),
                                 "items": items[-20:]}
    # R&D: every idea in the registry carries its own verdict ⇒ archived as research; no verdict ⇒ needs review
    reg = prov.git_root() / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md"
    ideas = []
    if reg.exists():
        _txt = reg.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"^(?:- \*\*#|### Идея #)(\d+)(.*)$", _txt, re.M):
            line = _txt[m.start(): m.start() + 700]          # the status often wraps to the next lines
            # The registry writes a verdict as «статус: **ПРОТЕСТИРОВАНА → ПОЗИТИВНО**» / «ИЗМЕРЕНА → ❌ …»:
            # a status with an arrow is a recorded outcome (positive or negative); without one the idea
            # is still open and nobody has judged it.
            verdict = re.search(r"статус:\s*\**[^→\n]*→", line, re.I)
            ideas.append({"idea": int(m.group(1)), "disposition": "ARCHIVED_AS_RESEARCH" if verdict else "NEEDS_REVIEW"})
    rc: dict = {}
    for i in ideas:
        rc[i["disposition"]] = rc.get(i["disposition"], 0) + 1
    out["roles"]["rnd"] = {"agent": "com.spa.novel_edge_rnd", "outputs": len(ideas), "dispositions": rc,
                           "governance": "SPA_AUTONOMOUS=1 + run id + 4 h term since ADR-551"}
    out["roles"]["build_loop"] = {"agent": "com.spa.orchestrator",
                                  "dispositions_source": "tracker cards (spa_core/studio_os/build_loop.py lineage)",
                                  "site_changes": "owner-gated classes only via safe_site_push + owner-done card"}
    return out


def report(*, root: Optional[Path] = None, data_dir: Optional[Path] = None, tdir: Optional[Path] = None,
           launchctl_text: Optional[str] = None, pages: bool = True) -> dict:
    root = root or prov.git_root()
    if data_dir is None:
        from spa_core.utils.live_paths import live_data_dir
        data_dir = Path(live_data_dir())
    tdir = tdir or build_loop.tracker_dir()
    reg = prov.load_registry()
    findings = []
    if pages:
        findings += pages_without_lineage(root, reg)
    findings += manifest_checks(root, data_dir, launchctl_text=launchctl_text)
    findings += duplicate_docs(root)
    findings += stale_cards(tdir)
    repos = [Path(p) for p in {str(REPO), str(root)} if (Path(p) / ".git").exists()]
    findings += worktrees(repos)
    by: dict = {}
    for f in findings:
        by[f["class"]] = by.get(f["class"], 0) + 1
    return {"schema": "orphan-report/1",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy": "report only — nothing is deleted or disabled (ADR-551)",
            "counts": by, "total": len(findings), "findings": findings,
            "supervision": supervise(data_dir)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="orphan & supervision report (ADR-551)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="write data/orphan_report.json (read model)")
    ap.add_argument("--no-pages", action="store_true")
    a = ap.parse_args(argv)
    rep = report(pages=not a.no_pages)
    if a.write:
        from spa_core.utils.atomic import atomic_save
        from spa_core.utils.live_paths import live_data_dir
        atomic_save(rep, str(Path(live_data_dir()) / "orphan_report.json"))
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"orphan report: {rep['total']} findings · {rep['counts']}")
        for cls in sorted(rep["counts"]):
            ex = [f for f in rep["findings"] if f["class"] == cls][:4]
            print(f"\n[{cls}] {rep['counts'][cls]}")
            for f in ex:
                print(f"  - {f['artifact']} — {f['reason'][:110]} → {f['recommended_action'][:80]}")
        sv = rep["supervision"]["roles"]
        print("\nsupervision:", {k: v.get("dispositions") for k, v in sv.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
