"""S2 — исправления по самопроверке diff (31.10): байткод и ссылка ``__pycache__`` в релизе — лишний состав;
материализация не принимает ``git replace``; один перепроверенный читатель объектов; self-test установщика не
доверяет лежащей копии лаунчера; ``propose`` после захвата перечитывает полное состояние шага."""
import hashlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from spa_core.studio_os import executor as ex
from spa_core.studio_os import goal_graph as gg
from spa_core.studio_os import release_activation as RA
from spa_core.studio_os import release_launcher as LNCH
from spa_core.studio_os.model_roles import adapters as ad

REPO = Path(__file__).resolve().parents[2]


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "pkg").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], r)
    _git(["config", "user.email", "t@t"], r)
    _git(["config", "user.name", "t"], r)
    (r / "pkg" / "__init__.py").write_text("")
    (r / "pkg" / "mod.py").write_text("print('A')\n")
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "A"], r)
    return r, _git(["rev-parse", "HEAD"], r), tmp_path / "releases"


def _both(sha, rel, r):
    return RA.exec_root(sha, rel, r)[1], LNCH.exec_root(sha, rel, str(r))[1]


def test_planted_bytecode_is_refused_by_both_resolvers(repo):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    (path / "pkg" / "__pycache__").mkdir()
    (path / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"\x00planted")
    assert _both(sha, rel, r) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")


def test_pycache_symlink_out_of_the_release_is_refused(repo, tmp_path):
    r, sha, rel = repo
    path, _ = RA.materialise_release(sha, rel, r)
    outside = tmp_path / "attacker_cache"
    outside.mkdir()
    os.symlink(outside, path / "pkg" / "__pycache__")
    assert _both(sha, rel, r) == ("APPROVED_RELEASE_CORRUPT", "APPROVED_RELEASE_CORRUPT")


def test_launcher_runs_every_service_without_writing_bytecode():
    assert all(argv[0] == "-B" for argv in LNCH.SERVICE_ALLOWLIST.values())
    assert LNCH._agent_argv.__code__.co_consts and "-B" in LNCH._agent_argv.__code__.co_consts


def _forge_replace(r, sha):
    real_tree = _git(["rev-parse", f"{sha}^{{tree}}"], r)
    (r / "pkg" / "evil.py").write_text("print('EVIL')\n")
    _git(["add", "-A"], r)
    forged = _git(["write-tree"], r)
    _git(["replace", real_tree, forged], r)
    assert "pkg/evil.py" in _git(["ls-tree", "-r", "--name-only", sha], r)      # наивный git видит подмену
    return real_tree


def test_materialise_ignores_replace_refs_and_extracts_the_real_tree(repo):
    r, sha, rel = repo
    _forge_replace(r, sha)
    path, verdict = RA.materialise_release(sha, rel, r)
    assert verdict == "OK" and not (path / "pkg" / "evil.py").exists()
    assert _both(sha, rel, r) == ("ACTIVATE_OK", "ACTIVATE_OK")


def test_activation_reference_rechecks_objects_like_the_launcher(repo):
    """Подменённый файл объекта дерева в хранилище: оба резолвера — «проверить нечем», а не «доказано»."""
    r, sha, rel = repo
    RA.materialise_release(sha, rel, r)
    real_tree = _git(["rev-parse", f"{sha}^{{tree}}"], r)
    (r / "pkg" / "mod.py").write_text("print('EVIL')\n")
    _git(["add", "-A"], r)
    forged = subprocess.run(["git", "cat-file", "tree", _git(["write-tree"], r)], cwd=str(r), capture_output=True).stdout
    loose = r / ".git" / "objects" / real_tree[:2] / real_tree[2:]
    os.chmod(loose, 0o644)
    loose.write_bytes(zlib.compress(b"tree %d\0" % len(forged) + forged))
    assert RA.trusted_tree(sha, r) is None
    assert _both(sha, rel, r) == ("APPROVED_RELEASE_UNVERIFIABLE", "APPROVED_RELEASE_UNVERIFIABLE")


def _install(root, r, sha):
    lsha = hashlib.sha256(Path(LNCH.__file__).read_bytes()).hexdigest()
    return subprocess.run(["bash", str(REPO / "scripts" / "install_trusted_bootstrap.sh"), "--self-test-root", str(root),
                           "--launcher", LNCH.__file__, "--launcher-sha256", lsha, "--repo", str(r), "--approved", sha,
                           "--self-test-app-python", sys.executable], capture_output=True, text=True), lsha


def test_installer_extracts_the_real_tree_despite_replace_refs(repo, tmp_path):
    r, sha, _ = repo
    _forge_replace(r, sha)
    root = tmp_path / "root"
    root.mkdir()
    res, _ = _install(root, r, sha)
    assert res.returncode == 0, res.stderr
    assert not (root / "releases" / sha / "pkg" / "evil.py").exists()


def test_installer_self_test_refuses_a_tampered_existing_launcher_copy(repo, tmp_path):
    r, sha, _ = repo
    root = tmp_path / "root"
    root.mkdir()
    lsha = hashlib.sha256(Path(LNCH.__file__).read_bytes()).hexdigest()
    (root / "bin").mkdir()
    (root / "bin" / f"release_launcher-{lsha}.py").write_text("def trusted_tree(*a):\n    return {}\n"
                                                              "def _composition_problem(*a):\n    return ''\n")
    res, _ = _install(root, r, sha)
    assert res.returncode != 0 and "not used as the verifier" in res.stderr, res.stderr
    assert not (root / "releases").exists()


# ── propose: после захвата — полное состояние, а не только счётчик ────────────────────────────────
T0 = "2026-10-31T20:00:00+00:00"          # FROZEN-DATE-OK: injected-clock — every `now` derives from T0
PLAN = json.dumps({"tasks": [{"id": "t1", "outcome": "x", "operations": [{"op": "write_file", "path": "docs/n.md",
                   "content": "ok\n"}], "check": {"kind": "file_contains", "path": "docs/n.md", "text": "ok"}}]})


@pytest.mark.parametrize("first_outcome,expect", [({"status": "quota"}, "paused:quota"),
                                                  ({"status": "ownership_unresolved"}, "blocked"),
                                                  (PLAN, None)])
def test_outcome_written_between_status_read_and_claim_is_honoured(tmp_path, monkeypatch, first_outcome, expect):
    """Гонка ревьюера: w2 прочитал «в работе», w1 успел записать исход, w2 захватил шаг. w2 не зовёт модель."""
    run = tmp_path / "run"
    goal = gg.goal_record("g", source="t", transport_id="m", owner="o", outcome="out", at=T0)
    kw = dict(run_dir=run, scope=["docs/"], context="c", provider_id="fixture_test_adapter", ttl_s=600)
    later = "2026-10-31T20:30:00+00:00"   # FROZEN-DATE-OK: injected-clock — T0 + 30 min, past w1's lease
    if expect == "paused:quota" or expect == "blocked":
        with pytest.raises(ex.Paused):
            ex.propose(goal, adapters={"fixture": ad.fixture({"*": first_outcome})}, worker="w1", now=T0, **kw)
    else:
        ex.propose(goal, adapters={"fixture": ad.fixture({"*": first_outcome})}, worker="w1", now=T0, **kw)
    real = ex.proposal_status
    calls = {"n": 0}

    def stale_first(*a, **k):                     # первое чтение w2 — устаревшее «in_flight»
        calls["n"] += 1
        st = real(*a, **k)
        return {**st, "state": "in_flight"} if calls["n"] == 1 else st

    monkeypatch.setattr(ex, "proposal_status", stale_first)
    hit = {"n": 0}

    def counting(req, *, timeout_s, tools):
        hit["n"] += 1
        return ad.fixture({"*": PLAN})(req, timeout_s=timeout_s, tools=tools)

    if expect:
        with pytest.raises(ex.Paused, match=expect):
            ex.propose(goal, adapters={"fixture": counting}, worker="w2", now=later, **kw)
    else:
        assert ex.propose(goal, adapters={"fixture": counting}, worker="w2", now=later, **kw)["called_model"] is False
    assert hit["n"] == 0
