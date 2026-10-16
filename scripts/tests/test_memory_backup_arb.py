"""Memory backup — ARB follow-up 2026-10-16 (stash reflog, uncommitted code, bundle retention linkage).

Each test replays one gap of scripts/memory_backup.py as delivered in 2e173313 and fails on that version:
  * only refs/stash (the NEWEST entry) was bundled — older stash entries lived only in the reflog;
  * modified/untracked code outside docs/ and nimbalyst-local/ (prod tree and its worktrees) was carried by nothing;
  * bundles were pruned to the last 3 per name while day snapshots live 14 days, so a retained MANIFEST could
    name a bundle that no longer existed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


def _load(monkeypatch, home: Path, spa: Path):
    spec = importlib.util.spec_from_file_location("memory_backup_arb", ROOT / "scripts" / "memory_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HOME", home)
    monkeypatch.setattr(mod, "SPA", spa)
    monkeypatch.setattr(mod, "REPOS", {})
    # only the sets this file is about; the others are covered by test_memory_backup_coverage.py
    monkeypatch.setattr(mod, "STATE_SETS", {k: v for k, v in mod.STATE_SETS.items() if k == "spa_uncommitted"})
    return mod


@pytest.fixture()
def scene(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    home = tmp_path / "home"
    spa = home / "Documents" / "SPA_Claude"
    spa.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(spa)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _git(spa, "config", k, v)
    (spa / "a.txt").write_text("a\n")
    _git(spa, "add", "a.txt")
    _git(spa, "commit", "-qm", "base")
    _git(spa, "remote", "add", "origin", str(origin))
    _git(spa, "push", "-q", "origin", "main")
    _git(spa, "checkout", "-qb", "p1/local-only")
    (spa / "b.txt").write_text("b\n")
    _git(spa, "add", "b.txt")
    _git(spa, "commit", "-qm", "local only")
    _git(spa, "checkout", "-q", "main")
    return tmp_path, origin, home, spa


def _stash(spa: Path, text: str) -> None:
    (spa / "a.txt").write_text(text)
    _git(spa, "stash", "push", "-q", "-m", text.strip())


def test_every_stash_entry_and_local_branch_restore_into_a_fresh_clone(scene, monkeypatch):
    tmp, origin, home, spa = scene
    _stash(spa, "older stash\n")
    _stash(spa, "newer stash\n")
    src_stash = _git(spa, "stash", "list", "--format=%H").split()
    assert len(src_stash) == 2
    refs_before = _git(spa, "for-each-ref")
    mod = _load(monkeypatch, home, spa)
    res = mod.run(tmp / "dest", today="2026-10-16")
    b = next(x for x in res["bundles"] if x["name"] == "spa_local_branches")
    assert b["ok"] and not b.get("empty"), b
    assert _git(spa, "for-each-ref") == refs_before            # the source repo was not written

    # restore by BEHAVIOUR first: whatever the bundle carries, a fresh clone must end with every stash entry
    fresh = tmp / "fresh"
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(origin), str(fresh)], check=True)
    bundle = tmp / "dest" / "bundles" / Path(b["bundle"]).name
    _git(fresh, "fetch", "-q", str(bundle), "refs/*:refs/restored/*")
    assert _git(fresh, "rev-parse", "refs/restored/heads/p1/local-only") == _git(spa, "rev-parse", "p1/local-only")
    restored = [_git(fresh, "rev-parse", f"refs/restored/stash-backup/{i}")
                for i in range(len(_git(fresh, "for-each-ref", "refs/restored/stash-backup").splitlines()))]
    for i in reversed(range(len(restored))):                   # oldest first ⇒ newest ends on top
        _git(fresh, "stash", "store", "-m", f"restored {i}", restored[i])
    assert _git(fresh, "stash", "list", "--format=%H").split() == src_stash
    # and the manifest describes it: entries, prerequisites, all of them on origin
    assert b["stash_entries"] == src_stash
    assert b["prerequisites"] and b["prerequisites_not_on_origin"] == []
    subprocess.run(["git", "-C", str(fresh), "fsck", "--connectivity-only", "--no-progress"], check=True,
                   capture_output=True)


def test_uncommitted_code_of_prod_tree_and_worktrees_is_archived_big_and_secret_named(scene, monkeypatch):
    tmp, origin, home, spa = scene
    (spa / "a.txt").write_text("modified\n")                    # modified tracked
    (spa / "spa_core").mkdir()
    (spa / "spa_core" / "new_mod.py").write_text("X = 1\n")       # untracked code
    (spa / "data").mkdir()
    (spa / "data" / "state.json").write_text("{}")               # data/ — the daily FULL archive's
    (spa / "docs").mkdir()
    (spa / "docs" / "n.md").write_text("doc")                    # docs/ — spa_owner_files'
    (spa / "big.bin").write_bytes(b"x" * 5000)                   # over the cap ⇒ named, not covered
    (spa / "leak.py").write_text("T = 'ghp_" + "A" * 36 + "'\n")   # credential-shaped ⇒ named, not copied
    wt = tmp / "wt1"
    _git(spa, "worktree", "add", "-q", "--detach", str(wt), "main")
    (wt / "wip.py").write_text("WIP = True\n")
    mod = _load(monkeypatch, home, spa)
    monkeypatch.setattr(mod, "UNCOMMITTED_MAX_BYTES", 1000, raising=False)
    res = mod.run(tmp / "dest", today="2026-10-16")
    st = next(x for x in res["states"] if x["name"] == "spa_uncommitted")
    assert st["ok"], st
    with tarfile.open(tmp / "dest" / "2026-10-16" / "state-spa_uncommitted.tar.gz") as t:
        members = {m.name: t.extractfile(m).read() for m in t.getmembers()}
    wlabel = next(r["label"] for r in st["trees"] if r["path"].endswith("wt1"))
    assert members["prod/a.txt"] == b"modified\n"
    assert members["prod/spa_core/new_mod.py"] == b"X = 1\n"
    assert members[f"{wlabel}/wip.py"] == b"WIP = True\n"
    assert not any("/data/" in m or "/docs/" in m or m.endswith(("big.bin", "leak.py")) for m in members)
    skipped = {(s["tree"], s["path"]) for s in st["skipped"]}
    assert {("prod", "big.bin"), ("prod", "leak.py")} <= skipped
    for row in st["manifest"]:
        assert hashlib.sha256(members[f"{row['tree']}/{row['path']}"]).hexdigest() == row["sha256"]


def test_retained_snapshot_never_loses_its_bundle(scene, monkeypatch):
    """15 days, retention 14: day 1 names state S0, days 2..15 name five distinct states S1..S5."""
    tmp, origin, home, spa = scene
    mod = _load(monkeypatch, home, spa)
    dest = tmp / "dest"
    plan = {1: 0, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 2, 8: 3, 9: 3, 10: 3, 11: 4, 12: 4, 13: 4, 14: 5, 15: 5}
    state = 0
    names = {}
    for day, want in plan.items():
        while state < want:
            _git(spa, "checkout", "-q", "p1/local-only")
            (spa / f"s{state}.txt").write_text(str(state))
            _git(spa, "add", f"s{state}.txt")
            _git(spa, "commit", "-qm", f"s{state + 1}")
            _git(spa, "checkout", "-q", "main")
            state += 1
        res = mod.run(dest, today=f"2026-10-{day:02d}", retention=14)
        b = next(x for x in res["bundles"] if x["name"] == "spa_local_branches")
        names[state] = Path(b["bundle"]).name
    assert len(set(names.values())) == 6
    left = {p.name for p in (dest / "bundles").glob("*.bundle")}
    assert {names[i] for i in range(1, 6)} <= left              # every retained MANIFEST still restorable
    assert names[0] not in left                                 # referenced only by the pruned day
    for day in sorted(p for p in dest.iterdir() if p.name.startswith("2026-")):
        for bb in json.loads((day / "MANIFEST.json").read_text())["bundles"]:
            if bb.get("bundle"):
                assert (day / bb["bundle"]).exists(), (day.name, bb["bundle"])


def test_unreadable_retained_manifest_deletes_no_bundle(tmp_path):
    spec = importlib.util.spec_from_file_location("memory_backup_arb2", ROOT / "scripts" / "memory_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store = tmp_path / "bundles"
    store.mkdir()
    for i in range(6):
        (store / f"x-{i:012d}.bundle").write_text(str(i))
    (tmp_path / "2026-10-16").mkdir()
    (tmp_path / "2026-10-16" / "MANIFEST.json").write_text("{not json")
    r = mod.prune_bundles(tmp_path, keep=1)
    assert r["deleted"] == [] and "refused" in r
    assert len(list(store.glob("*.bundle"))) == 6
