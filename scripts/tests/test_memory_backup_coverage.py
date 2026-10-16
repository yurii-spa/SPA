"""Memory backup coverage (ADR-763 package 3, audit 2026-10-16).

Before this change owner cards (nimbalyst-local/), local docs, launchd definitions and every SPA branch that
is not on origin were carried ONLY by the weekly whole-tree archive — on the same Mac, 2 of its last 4 archives
truncated. Each test below replays one of those gaps on a scratch tree and fails on the pre-change code.
"""
from __future__ import annotations

import importlib.util
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(monkeypatch, home: Path):
    spec = importlib.util.spec_from_file_location("memory_backup_under_test", ROOT / "scripts" / "memory_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    spa = home / "Documents" / "SPA_Claude"
    monkeypatch.setattr(mod, "HOME", home)
    monkeypatch.setattr(mod, "SPA", spa)
    monkeypatch.setattr(mod, "REPOS", {})
    sets = dict(mod.STATE_SETS)
    sets["spa_owner_files"] = (spa, None)
    sets["host_settings"] = (home, None)
    # spa_uncommitted needs a git tree; its own scenes live in test_memory_backup_arb.py
    for k in ("bridge_state", "mission_state", "spa_lineage", "claude_memory", "spa_uncommitted"):
        sets.pop(k, None)
    monkeypatch.setattr(mod, "STATE_SETS", sets)
    return mod


def _git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


def _scene(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    spa = home / "Documents" / "SPA_Claude"
    (spa / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (spa / "nimbalyst-local" / "tracker" / "own-local-only.md").write_text("---\nstatus: needs-owner\n---\nкарточка\n")
    (spa / "docs").mkdir()
    (spa / "docs" / "RFC_LOCAL.md").write_text("локальный документ\n")
    (spa / "docs" / "leak.md").write_text("token ghp_" + "A" * 36 + "\n")
    (spa / "data").mkdir()
    (spa / "data" / "big.json").write_text("{}")
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True)
    (la / "com.spa.mission_tick.plist").write_text("<plist/>")
    (la / "com.other.app.plist").write_text("<plist/>")
    serve = home / "studio-os-serve" / "mission"
    serve.mkdir(parents=True)
    (serve / "current.json").write_text('{"bundle": "b-1"}')
    (serve / "b-1").mkdir()
    (serve / "b-1" / "app.js").write_text("x")
    (home / "studio-os-serve" / "mission_access.json").write_text("{}")
    return home


def _members(out: Path, name: str) -> set:
    with tarfile.open(out / f"state-{name}.tar.gz") as t:
        return {m.name for m in t.getmembers()}


def test_owner_cards_and_local_docs_are_carried_secrets_are_not(tmp_path, monkeypatch):
    home = _scene(tmp_path)
    mod = _load(monkeypatch, home)
    res = mod.run(tmp_path / "dest", today="2026-10-16")
    assert res["ok"], res
    got = _members(tmp_path / "dest" / "2026-10-16", "spa_owner_files")
    assert "nimbalyst-local/tracker/own-local-only.md" in got
    assert "docs/RFC_LOCAL.md" in got
    assert "docs/leak.md" not in got                       # credential-shaped content never archived
    assert not any(m.startswith("data/") for m in got)     # data/ belongs to the daily FULL archive


def test_host_settings_carry_spa_plists_and_cockpit_pointer_only(tmp_path, monkeypatch):
    home = _scene(tmp_path)
    mod = _load(monkeypatch, home)
    mod.run(tmp_path / "dest", today="2026-10-16")
    got = _members(tmp_path / "dest" / "2026-10-16", "host_settings")
    assert "Library/LaunchAgents/com.spa.mission_tick.plist" in got
    assert "Library/LaunchAgents/com.other.app.plist" not in got
    assert "studio-os-serve/mission/current.json" in got
    assert "studio-os-serve/mission_access.json" in got
    assert "studio-os-serve/mission/b-1/app.js" not in got   # rebuilt bundles are not settings


@pytest.fixture()
def repo_with_origin(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    home = _scene(tmp_path)
    spa = home / "Documents" / "SPA_Claude"
    subprocess.run(["git", "init", "-q", "-b", "main", str(spa)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _git(spa, "config", k, v)
    (spa / "a.txt").write_text("a")
    _git(spa, "add", "a.txt")
    _git(spa, "commit", "-qm", "base")
    _git(spa, "remote", "add", "origin", str(origin))
    _git(spa, "push", "-q", "origin", "main")
    _git(spa, "checkout", "-qb", "p1/local-only")
    (spa / "b.txt").write_text("b")
    _git(spa, "add", "b.txt")
    _git(spa, "commit", "-qm", "local only")
    _git(spa, "checkout", "-q", "main")
    return home, spa


def test_local_only_branches_are_bundled_and_restorable(tmp_path, monkeypatch, repo_with_origin):
    home, spa = repo_with_origin
    mod = _load(monkeypatch, home)
    res = mod.run(tmp_path / "dest", today="2026-10-16")
    b = next(x for x in res["bundles"] if x["name"] == "spa_local_branches")
    assert b["ok"] and not b.get("empty"), b
    bundle = tmp_path / "dest" / "bundles" / Path(b["bundle"]).name
    heads = subprocess.run(["git", "bundle", "list-heads", str(bundle)], capture_output=True, text=True).stdout
    assert "refs/heads/p1/local-only" in heads
    assert _git(spa, "rev-parse", "p1/local-only") in heads


def test_bundle_key_follows_moved_branches_not_reused_stale(tmp_path, monkeypatch, repo_with_origin):
    """Pre-change bug: option-style refs were dropped from the tip key, so «--branches» was keyed by
    nothing and yesterday's bundle was REUSED after a branch moved."""
    home, spa = repo_with_origin
    mod = _load(monkeypatch, home)
    first = next(x for x in mod.run(tmp_path / "dest", today="2026-10-16")["bundles"] if x["name"] == "spa_local_branches")
    _git(spa, "checkout", "-q", "p1/local-only")
    (spa / "c.txt").write_text("c")
    _git(spa, "add", "c.txt")
    _git(spa, "commit", "-qm", "moved")
    _git(spa, "checkout", "-q", "main")
    second = next(x for x in mod.run(tmp_path / "dest", today="2026-10-17")["bundles"] if x["name"] == "spa_local_branches")
    assert second["bundle"] != first["bundle"] and not second["reused"]
    bundle = tmp_path / "dest" / "bundles" / Path(second["bundle"]).name
    heads = subprocess.run(["git", "bundle", "list-heads", str(bundle)], capture_output=True, text=True).stdout
    assert _git(spa, "rev-parse", "p1/local-only") in heads


def test_nothing_local_only_is_a_measured_empty_not_a_failure(tmp_path, monkeypatch, repo_with_origin):
    home, spa = repo_with_origin
    _git(spa, "push", "-q", "origin", "p1/local-only")
    _git(spa, "fetch", "-q", "origin")
    mod = _load(monkeypatch, home)
    res = mod.run(tmp_path / "dest", today="2026-10-16")
    b = next(x for x in res["bundles"] if x["name"] == "spa_local_branches")
    assert b["ok"] and b["empty"] is True and b["bytes"] == 0
    assert res["ok"]


def test_daily_full_archive_declares_spa_db():
    spec = importlib.util.spec_from_file_location("daily_backup_under_test", ROOT / "scripts" / "daily_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "spa.db" in mod._SQLITE_FILES
