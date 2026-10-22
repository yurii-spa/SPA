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
    # Audit 2026-10-16 (ADR-763 package 3): owner cards / decisions and local docs existed only in the weekly
    # whole-tree archive (same Mac, 2 of the last 4 archives truncated); ~47 cards were not on origin at all.
    "spa_owner_files": (SPA, None),               # only nimbalyst-local/ and docs/ — see _files
    # launchd definitions (5 of 92 differ from launchd/ on origin, 1 exists only here) and the cockpit's
    # serve-root settings (current bundle pointer, access config). Credential-shaped content is screened as usual.
    "host_settings": (HOME, None),                # only the paths named in _files
    # ARB 2026-10-16: modified/untracked CODE (outside data/, docs/, nimbalyst-local/) in the prod tree and in
    # every existing worktree of the prod repo — measured 1782 files in prod + ~1.1k across 37 worktrees, carried
    # by nothing but the weekly whole-tree archive. See archive_uncommitted.
    "spa_uncommitted": (SPA, None),
}
# spa_uncommitted: what git status reports that the other sets / the daily FULL archive already own, or that is
# rebuildable noise. Files larger than the cap are NAMED as skipped in the manifest (inv. #17), never «covered».
UNCOMMITTED_EXCLUDED_TOP = ("data/", "docs/", "nimbalyst-local/", ".claude/worktrees/")
UNCOMMITTED_EXCLUDED_PARTS = ("node_modules", "__pycache__", ".git")
UNCOMMITTED_SECRET_NAMES = (".github_pat", ".env", "id_rsa", "id_ed25519")
UNCOMMITTED_MAX_BYTES = 5 * 1024 * 1024
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


def bundle_repo(name: str, repo: Path, store: Path, *, refs=("--all",), extra=(), git_dir_ok: bool = False) -> dict:
    """One bundle per distinct state of the repo: <store>/<name>-<tip12>.bundle. Unchanged repos are not
    re-uploaded every night; every day's MANIFEST names the bundle to restore. Retention is decided by
    prune_bundles AFTER the day snapshots are pruned (a bundle a retained MANIFEST names is never deleted)."""
    if not git_dir_ok and not (repo / ".git").exists():
        return {"name": name, "ok": False, "error": "not a git repository"}
    # The tip hash covers exactly the ref selection the bundle uses (rev-parse understands --all/--branches/
    # --not/--remotes): before 2026-10-16 option-style refs were dropped here, so a bundle of «--branches»
    # would have been keyed by nothing and REUSED although the branches had moved.
    tips = _git(repo, "rev-parse", *refs, *extra)
    tip = hashlib.sha256((tips.stdout if tips.returncode == 0 else time.time().hex()).encode()).hexdigest()[:12]
    dst = store / f"{name}-{tip}.bundle"
    reused = dst.exists() and _git(repo, "bundle", "verify", str(dst)).returncode == 0
    if not reused:
        tmp = dst.with_suffix(".tmp")
        p = _git(repo, "bundle", "create", str(tmp), *refs, *extra)
        if p.returncode != 0 and "empty bundle" in (p.stderr or ""):
            tmp.unlink(missing_ok=True)       # measured: nothing local-only to carry — a value, not a failure
            return {"name": name, "ok": True, "empty": True, "bytes": 0}
        if p.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            return {"name": name, "ok": False, "error": (p.stderr or "").strip()[-300:]}
        tmp.replace(dst)
    v = _git(repo, "bundle", "verify", str(dst))
    return {"name": name, "ok": v.returncode == 0, "verify": "ok" if v.returncode == 0 else v.stderr[-300:],
            "bundle": f"../bundles/{dst.name}", "reused": reused,
            "head": _git(repo, "rev-parse", "HEAD").stdout.strip()[:12], "bytes": dst.stat().st_size,
            "sha256": _sha(dst)}


def _known_on_origin(repo: Path):
    """What THIS clone knows as origin/main — read EXPLICITLY as a snapshot of its last fetch, never as the
    server's answer (server_ref.cached_ref: source="cache", the ref's own reflog time as its age).

    Why a snapshot and not a server pin (ARB 22.10): the backup is read-only towards every source and must
    work offline — a pin may fetch INTO the production .git and waits on the network. A stale snapshot is
    safe here by construction: it excludes LESS, so the bundle only grows (commits already on the server
    ride along); it never drops a local-only commit. The snapshot and its age go into the MANIFEST."""
    try:
        if str(Path(__file__).resolve().parents[1]) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from spa_core.utils.server_ref import cached_ref
    except Exception as exc:  # noqa: BLE001 — without the reader there is no named exclusion base
        return None, f"server_ref not loaded: {type(exc).__name__}: {exc}"
    snap = cached_ref(str(repo), "origin/main")
    return snap, snap.describe()


def bundle_shadow_branch(repo: Path, store: Path, *, name: str = "spa_shadow_branch") -> dict:
    """Commits of the shadow branch that are not in this clone's snapshot of origin/main — bundled with
    `--not <snapshot sha>`, the snapshot named in the result (`exclusion_base`)."""
    snap, note = _known_on_origin(repo)
    if snap is None or not snap.ok:
        return {"name": name, "ok": False, "exclusion_base": note,
                "error": f"exclusion base (this clone's origin/main snapshot) not resolved: {note}"}
    res = bundle_repo(name, repo, store, refs=(SHADOW_BRANCH,), extra=("--not", snap.sha))
    res["exclusion_base"] = note
    return res


def _bundle_header(path: Path) -> tuple[list, list]:
    """(prerequisites, heads) read from the bundle's own header — the bundle describes itself."""
    pre, heads = [], []
    with open(path, "rb") as f:
        f.readline()                                   # signature line
        for raw in f:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line:
                break
            if line.startswith("@"):                   # v3 capabilities
                continue
            if line.startswith("-"):
                pre.append(line[1:].split(" ", 1)[0])
            else:
                sha, _, ref = line.partition(" ")
                heads.append({"ref": ref, "sha": sha})
    return pre, heads


def _worktrees(repo: Path) -> list:
    """[{path, head, label, exists}] from `git worktree list --porcelain`; the main tree is labelled «prod»."""
    p = _git(repo, "worktree", "list", "--porcelain")
    out, cur = [], {}
    for line in (p.stdout or "").splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line[9:]}
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif not line and cur:
            out.append(cur)
            cur = {}
    for i, w in enumerate(out):
        wp = w["path"]
        w["label"] = "prod" if i == 0 else \
            f"wt-{re.sub(r'[^A-Za-z0-9._-]', '_', Path(wp).name)}-{hashlib.sha256(wp.encode()).hexdigest()[:8]}"
        w["exists"] = Path(wp).is_dir()
    return out


def bundle_local_refs(name: str, repo: Path, store: Path) -> dict:
    """Every local branch, EVERY stash entry (refs/stash is only the newest — the rest live in its reflog) and
    every worktree HEAD, minus what origin already has — WITHOUT writing to `repo`: refs are recreated in a
    throwaway bare repo whose objects/info/alternates points at repo's object store, and bundled from there.
    The bundle needs origin for its prerequisite commits; the manifest lists them and whether each one is
    reachable from origin (per the local remote-tracking refs at backup time)."""
    if not (repo / ".git").exists():
        return {"name": name, "ok": False, "error": "not a git repository"}
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    objects = Path(common) / "objects"
    refs = _git(repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/remotes/origin")
    stash = _git(repo, "log", "-g", "--format=%H", "refs/stash") if \
        _git(repo, "rev-parse", "--verify", "-q", "refs/stash").returncode == 0 else None
    if refs.returncode != 0 or (stash is not None and stash.returncode != 0):
        return {"name": name, "ok": False, "error": "cannot list refs/stash reflog"}
    lines = [ln.split(" ", 1) for ln in refs.stdout.splitlines() if ln.strip()]
    stash_shas = (stash.stdout.split() if stash is not None else [])
    lines += [[sha, f"refs/stash-backup/{i}"] for i, sha in enumerate(stash_shas)]
    wt_heads = []
    for w in _worktrees(repo):
        h = w.get("head")
        if h and _git(repo, "cat-file", "-e", f"{h}^{{commit}}").returncode == 0:
            lines.append([h, f"refs/worktree-head/{w['label']}"])
            wt_heads.append({"label": w["label"], "path": w["path"], "head": h, "exists": w["exists"]})
    with tempfile.TemporaryDirectory(prefix="spa-refs-") as tmp:
        t = Path(tmp) / "r.git"
        subprocess.run(["git", "init", "-q", "--bare", str(t)], check=True, capture_output=True)
        (t / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (t / "objects" / "info" / "alternates").write_text(str(objects) + "\n")
        # measured 2026-10-16: the prod repo is SHALLOW (.git/shallow, 12 grafts) — without the same grafts
        # the throwaway repo cannot traverse history ("Could not read <parent>") and origin looks empty
        if (Path(common) / "shallow").is_file():
            shutil.copyfile(Path(common) / "shallow", t / "shallow")
        upd = subprocess.run(["git", "-C", str(t), "update-ref", "--stdin"], input="".join(
            f"create {ref} {sha}\n" for sha, ref in lines), capture_output=True, text=True)
        if upd.returncode != 0:
            return {"name": name, "ok": False, "error": (upd.stderr or "").strip()[-300:]}
        res = bundle_repo(name, t, store, refs=("--branches", "--glob=refs/stash-backup/*",
                                                  "--glob=refs/worktree-head/*"),
                          extra=("--not", "--remotes=origin"), git_dir_ok=True)
        res["stash_entries"] = stash_shas
        res["branches"] = {ref[len("refs/heads/"):]: sha for sha, ref in lines if ref.startswith("refs/heads/")}
        res["worktree_heads"] = wt_heads
        if res.get("ok") and not res.get("empty"):
            pre, heads = _bundle_header(store / Path(res["bundle"]).name)
            rl = subprocess.run(["git", "-C", str(t), "rev-list", "--remotes=origin"], capture_output=True, text=True)
            if rl.returncode != 0:
                res.update(ok=False, error=f"cannot walk origin history: {(rl.stderr or '').strip()[-200:]}")
                return res
            on_origin = set(rl.stdout.split())
            res["heads_count"] = len(heads)
            res["prerequisites"] = pre
            res["prerequisites_not_on_origin"] = [p for p in pre if p not in on_origin]
            res["restore_needs"] = "origin (github.com/yurii-spa/SPA) for every prerequisite commit"
            in_bundle = {h["sha"] for h in heads}
            # refs whose tip is already on origin are not in the bundle by construction; name them
            res["refs_restored_from_origin"] = sorted(ref for sha, ref in lines
                                                      if not ref.startswith("refs/remotes/") and sha not in in_bundle)
            if res["prerequisites_not_on_origin"]:
                res["ok"] = False
                res["error"] = "bundle prerequisites missing from origin — restore would be incomplete"
        res["head"] = _git(repo, "rev-parse", "HEAD").stdout.strip()[:12]
        res["source_shallow"] = (Path(common) / "shallow").is_file()
    return res


def _uncommitted_paths(tree: Path) -> tuple[list | None, str]:
    env = dict(__import__("os").environ, GIT_OPTIONAL_LOCKS="0")   # status must not refresh the index
    p = subprocess.run(["git", "--no-optional-locks", "-C", str(tree), "status", "--porcelain=v1", "-uall", "-z"],
                       capture_output=True, text=True, timeout=600, env=env)
    if p.returncode != 0:
        return None, (p.stderr or "").strip()[-200:]
    ents, out, i = p.stdout.split("\0"), [], 0
    while i < len(ents):
        e = ents[i]
        i += 1
        if not e:
            continue
        st, path = e[:2], e[3:]
        if st[0] in "RC":
            i += 1                                      # -z rename: the source path follows
        if "D" in st:
            continue                                    # nothing on disk to carry
        out.append(path)
    return out, ""


def archive_uncommitted(name: str, repo: Path, out: Path, *, max_bytes: int | None = None) -> dict:
    """Modified/untracked files of the prod tree and of every EXISTING worktree, arcname <label>/<path>."""
    cap = UNCOMMITTED_MAX_BYTES if max_bytes is None else max_bytes
    if not (repo / ".git").exists():
        return {"name": name, "ok": False, "error": f"not a git repository: {repo}"}
    dst = out / f"state-{name}.tar.gz"
    trees, files, skipped, errors, n = [], [], [], [], 0
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(dst, "w:gz") as tar:
        for w in _worktrees(repo):
            row = {"label": w["label"], "path": w["path"], "exists": w["exists"]}
            trees.append(row)
            if not w["exists"]:
                continue                                # stale registration — its HEAD is bundled, files are gone
            paths, err = _uncommitted_paths(Path(w["path"]))
            if paths is None:
                errors.append({"tree": w["label"], "error": err})
                row["error"] = err
                continue
            row["files"] = 0
            for rel in paths:
                parts = rel.split("/")
                if rel.startswith(UNCOMMITTED_EXCLUDED_TOP) or rel.endswith(".log") or \
                        any(x in parts for x in UNCOMMITTED_EXCLUDED_PARTS):
                    continue
                p = Path(w["path"]) / rel
                if not p.is_file() or p.is_symlink():
                    continue
                item = {"tree": w["label"], "path": rel}
                if parts[-1] in UNCOMMITTED_SECRET_NAMES or p.suffix in (".pem", ".key"):
                    skipped.append(item | {"why": "secret by name — never archived"})
                    continue
                size = p.stat().st_size
                if size > cap:
                    skipped.append(item | {"why": f"over size cap {cap} bytes", "bytes": size})
                    continue
                arc = f"{w['label']}/{rel}"
                if p.suffix in (".db", ".sqlite"):
                    staged = Path(tmp) / arc.replace("/", "__")
                    try:
                        src = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                        dst_db = sqlite3.connect(str(staged))
                        src.backup(dst_db); dst_db.close(); src.close()
                    except sqlite3.Error as e:
                        skipped.append(item | {"why": f"sqlite unreadable: {e}"})
                        continue
                    tar.add(staged, arcname=arc)
                    files.append(item | {"sha256": _sha(staged), "sqlite_backup": True})
                    n += 1; row["files"] += 1
                    continue
                try:
                    data = p.read_bytes()
                except OSError as e:
                    skipped.append(item | {"why": f"unreadable: {e.__class__.__name__}"})
                    continue
                if SECRET.search(data.decode("utf-8", errors="ignore")):
                    skipped.append(item | {"why": "credential-shaped content — never archived"})
                    continue
                info = tar.gettarinfo(str(p), arcname=arc)
                info.size = len(data)
                tar.addfile(info, __import__("io").BytesIO(data))   # archive exactly the bytes screened
                files.append(item | {"sha256": hashlib.sha256(data).hexdigest()})
                n += 1; row["files"] += 1
    with tarfile.open(dst, "r:gz") as t:
        listed = len(t.getmembers())
    return {"name": name, "ok": listed == n and not errors, "files": n, "listed": listed,
            "max_bytes": cap, "trees": trees, "tree_errors": errors, "skipped": skipped,
            "skipped_count": len(skipped), "manifest": files, "bytes": dst.stat().st_size, "sha256": _sha(dst)}


def prune_bundles(dest: Path, *, keep: int = 3) -> dict:
    """Run AFTER the day snapshots are pruned: a bundle named by ANY retained day's MANIFEST is never deleted;
    of the rest only the newest `keep` per name survive. A retained MANIFEST that cannot be read ⇒ delete
    nothing (fail-CLOSED: its references are unknown)."""
    store = dest / "bundles"
    if not store.is_dir():
        return {"deleted": [], "kept": []}
    referenced = set()
    for day in (p for p in dest.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name)):
        m = day / "MANIFEST.json"
        if not m.exists():
            continue
        try:
            doc = json.loads(m.read_text())
        except (OSError, ValueError) as e:
            return {"deleted": [], "refused": f"unreadable {m}: {e.__class__.__name__}"}
        referenced |= {Path(b["bundle"]).name for b in doc.get("bundles", []) if b.get("bundle")}
    groups: dict = {}
    for b in store.glob("*.bundle"):
        groups.setdefault(b.name.rsplit("-", 1)[0], []).append(b)
    deleted, kept = [], []
    for _, items in groups.items():
        items.sort(key=lambda x: x.stat().st_mtime)
        newest = set(items[-keep:]) if keep > 0 else set()
        for b in items:
            if b.name in referenced or b in newest:
                kept.append(b.name)
            else:
                b.unlink(missing_ok=True)
                deleted.append(b.name)
    return {"deleted": sorted(deleted), "kept": sorted(kept), "referenced": len(referenced)}


def _excluded(rel: str, excl) -> bool:
    return any(x in rel for x in excl or ())


def _files(name: str, base: Path, excl):
    if name == "spa_lineage":
        for sub in ("task_links", "handoffs"):
            d = base / sub
            if d.is_dir():
                yield from (p for p in d.rglob("*") if p.is_file())
        return
    if name == "spa_owner_files":
        for sub in ("nimbalyst-local", "docs"):
            d = base / sub
            if d.is_dir():
                yield from (p for p in d.rglob("*") if p.is_file() and p.name != ".DS_Store")
        return
    if name == "host_settings":
        la = base / "Library" / "LaunchAgents"
        if la.is_dir():
            yield from sorted(la.glob("com.spa.*.plist*"))
        serve = base / "studio-os-serve"
        if serve.is_dir():
            yield from sorted(p for p in serve.glob("*.json") if p.is_file())
            for d in ("mission", "director"):
                cur = serve / d / "current.json"
                if cur.is_file():
                    yield cur
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


def run(dest: Path, *, retention: int = 14, today: str | None = None, keep_bundles: int = 3) -> dict:
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
        res["bundles"].append(bundle_shadow_branch(SPA, store))
    # every local SPA branch, EVERY stash entry (not just refs/stash = the newest) and every worktree HEAD whose
    # commits are not on origin (audit 2026-10-16: 64 branch tips and 11 stash entries existed only in this Mac's
    # .git). Built in a throwaway repo over the prod object store — the prod .git is never written.
    if (SPA / ".git").exists():
        res["bundles"].append(bundle_local_refs("spa_local_branches", SPA, store))
    for name, (base, excl) in STATE_SETS.items():
        if name == "spa_uncommitted":
            res["states"].append(archive_uncommitted(name, SPA, out))
            continue
        res["states"].append(archive_state(name, base, excl, out))
    res["ok"] = all(b["ok"] for b in res["bundles"]) and all(s["ok"] for s in res["states"])
    (out / "MANIFEST.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    days = sorted(p for p in dest.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name))
    for old in days[:-retention]:
        shutil.rmtree(old, ignore_errors=True)
    res["bundle_retention"] = prune_bundles(dest, keep=keep_bundles)    # days first, then bundles
    (out / "MANIFEST.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
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
