#!/usr/bin/env python3
"""Memory backup (ADR-527) — the company-memory sources that git/origin does NOT already protect.

Audit 2026-10-01: SPA's canon is on origin, but these existed only on this Mac with no backup:
  * local-only git repositories — Studio Bridge, Studio OS, Company Memory, earn-defi (full history);
  * the SPA feature branch of the shadow worktree (studio-os-scratch/v03) — commits not on origin;
  * Studio Bridge runtime state (bridge.db, the 65k-entry decision journal, mandate, notifications);
  * the Mission Fabric ledger (~/studio-os-scratch/mission-state);
  * SPA lineage/handoff records (data/task_links, data/handoffs) and Claude auto-memory.

What it writes — to iCloud Drive (leaves the machine; same convention as spa_core/persistence/backup.py
and earn-defi's backup), else ~/SPA_backups/memory:
  <dest>/bundles/<repo>-<tip>.bundle (one per distinct repo state) · <dest>/<YYYY-MM-DD>/{state-*.tar.gz, MANIFEST.json}
Git bundles are restore-checked (`git bundle verify`); every archived text file is screened for
credential shapes and EXCLUDED on a hit (named in the manifest, never copied). Secret material is
excluded by path: the Bridge signer key directory and one-time owner action tokens.
Read-only towards every source. Stdlib only. Exit 0 ok · 1 something failed (named) · 2 nothing done.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HOME = Path.home()
ICLOUD = HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "SPA_backups" / "memory"
FALLBACK = HOME / "SPA_backups" / "memory"
REPOS = {
    "studio_bridge": HOME / "Documents" / "studio_bridge",
    "studio_os": HOME / "Documents" / "studio_os",
    "company_memory": HOME / "Documents" / "earn-defi-studio-memory",
    "earn_defi": HOME / "Documents" / "earn-defi",
}
SPA = HOME / "Documents" / "SPA_Claude"
SHADOW_BRANCH = "feature/mobile-owner-remote"
STATE_SETS = {
    "bridge_state": (HOME / "Documents" / "studio_bridge" / "state",
                     ("activation_ipc/signer", "action_tokens.json", "coordinator.lock", ".db-shm", ".db-wal")),
    "mission_state": (HOME / "studio-os-scratch" / "mission-state", ()),
    "spa_lineage": (SPA / "data", None),          # only task_links/ and handoffs/ — see _spa_lineage_files
    "claude_memory": (HOME / ".claude" / "projects", None),
}
SECRET = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|(?<![A-Za-z0-9])sk-(ant-)?[A-Za-z0-9_-]{20,}|"
                    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _git(repo: Path, *a: str, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=timeout)


def bundle_repo(name: str, repo: Path, store: Path, *, refs=("--all",), extra=(), keep: int = 3) -> dict:
    """One bundle per distinct state of the repo: <store>/<name>-<tip12>.bundle, the last `keep` kept.
    Unchanged repos are not re-uploaded every night; every day's MANIFEST names the bundle to restore."""
    if not (repo / ".git").exists():
        return {"name": name, "ok": False, "error": "not a git repository"}
    tips = _git(repo, "rev-parse", *[r for r in refs if not r.startswith("--")] or ["--all"])
    tip = hashlib.sha256((tips.stdout if tips.returncode == 0 else time.time().hex()).encode()).hexdigest()[:12]
    dst = store / f"{name}-{tip}.bundle"
    reused = dst.exists() and _git(repo, "bundle", "verify", str(dst)).returncode == 0
    if not reused:
        tmp = dst.with_suffix(".tmp")
        p = _git(repo, "bundle", "create", str(tmp), *refs, *extra)
        if p.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            return {"name": name, "ok": False, "error": (p.stderr or "").strip()[-300:]}
        tmp.replace(dst)
    v = _git(repo, "bundle", "verify", str(dst))
    for old in sorted(store.glob(f"{name}-*.bundle"), key=lambda x: x.stat().st_mtime)[:-keep]:
        old.unlink(missing_ok=True)
    return {"name": name, "ok": v.returncode == 0, "verify": "ok" if v.returncode == 0 else v.stderr[-300:],
            "bundle": f"../bundles/{dst.name}", "reused": reused,
            "head": _git(repo, "rev-parse", "HEAD").stdout.strip()[:12], "bytes": dst.stat().st_size,
            "sha256": _sha(dst)}


def _excluded(rel: str, excl) -> bool:
    return any(x in rel for x in excl or ())


def _files(name: str, base: Path, excl):
    if name == "spa_lineage":
        for sub in ("task_links", "handoffs"):
            d = base / sub
            if d.is_dir():
                yield from (p for p in d.rglob("*") if p.is_file())
        return
    if name == "claude_memory":
        for d in base.glob("*/memory"):
            yield from (p for p in d.rglob("*") if p.is_file())
        return
    for p in base.rglob("*"):
        if p.is_file() and not _excluded(p.relative_to(base).as_posix(), excl):
            yield p


def archive_state(name: str, base: Path, excl, out: Path) -> dict:
    if not base.is_dir():
        return {"name": name, "ok": False, "error": f"missing {base}"}
    dst = out / f"state-{name}.tar.gz"
    skipped, n = [], 0
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(dst, "w:gz") as tar:
        for p in _files(name, base, excl):
            rel = p.relative_to(base).as_posix()
            if p.suffix in (".db", ".sqlite"):
                staged = Path(tmp) / (rel.replace("/", "__"))
                src = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                dst_db = sqlite3.connect(str(staged))
                src.backup(dst_db); dst_db.close(); src.close()
                tar.add(staged, arcname=rel)
                n += 1
                continue
            try:
                data = p.read_bytes()
            except OSError as e:
                skipped.append({"file": rel, "why": f"unreadable: {e.__class__.__name__}"})
                continue
            if SECRET.search(data.decode("utf-8", errors="ignore")):
                skipped.append({"file": rel, "why": "credential-shaped content — never archived"})
                continue
            tar.add(p, arcname=rel)
            n += 1
    with tarfile.open(dst, "r:gz") as t:
        listed = len(t.getmembers())
    return {"name": name, "ok": listed == n, "files": n, "listed": listed, "excluded_by_path": list(excl or ()),
            "skipped": skipped[:50], "bytes": dst.stat().st_size, "sha256": _sha(dst)}


def run(dest: Path, *, retention: int = 14, today: str | None = None) -> dict:
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    out = dest / today
    out.mkdir(parents=True, exist_ok=True)
    res = {"schema": "spa-memory-backup/1", "date": today, "dest": str(out),
           "offsite": str(dest).startswith(str(ICLOUD.parent.parent)), "bundles": [], "states": []}
    store = dest / "bundles"
    store.mkdir(exist_ok=True)
    for name, repo in REPOS.items():
        res["bundles"].append(bundle_repo(name, repo, store))
    # commits that live only in the shadow worktree's branch (not on origin)
    if _git(SPA, "rev-parse", "--verify", SHADOW_BRANCH).returncode == 0:
        res["bundles"].append(bundle_repo("spa_shadow_branch", SPA, store, refs=(SHADOW_BRANCH,), extra=("--not", "origin/main")))
    for name, (base, excl) in STATE_SETS.items():
        res["states"].append(archive_state(name, base, excl, out))
    res["ok"] = all(b["ok"] for b in res["bundles"]) and all(s["ok"] for s in res["states"])
    (out / "MANIFEST.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    days = sorted(p for p in dest.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name))
    for old in days[:-retention]:
        shutil.rmtree(old, ignore_errors=True)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest")
    ap.add_argument("--retention", type=int, default=14)
    a = ap.parse_args(argv)
    dest = Path(a.dest) if a.dest else (ICLOUD if ICLOUD.parent.exists() else FALLBACK)
    try:
        r = run(dest, retention=a.retention)
    except Exception as e:  # noqa: BLE001 — named, non-zero, never silent
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 2
    print(json.dumps({k: r[k] for k in ("date", "dest", "offsite", "ok")} |
                     {"bundles": [(b["name"], b["ok"]) for b in r["bundles"]],
                      "states": [(s["name"], s["ok"], s.get("files")) for s in r["states"]]}, ensure_ascii=False))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
