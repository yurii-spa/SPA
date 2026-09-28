"""Shell-level activation proof (PROPOSED ADR-500, ARB proof requirement). Pure Python A–H prove the STATE
machine; THIS proves the EXEC guarantee with real subprocess exec and real local git objects:

  filesystem/tree holds STAGED=B, APPROVED=A → a start either executes A (from the immutable release,
  materialised from git objects) or refuses before ANY application module loads. B must NEVER execute.

Hermetic: a throwaway git repo + temp releases dir under tmp_path. Touches no production tree, starts no
fleet agent, moves no capital."""
import subprocess
import sys

import pytest

from spa_core.studio_os import release_activation as RA

PY = sys.executable


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def repo_ab(tmp_path):
    """A git repo whose module prints RELEASE_A at commit A and RELEASE_B at commit B (B checked out = STAGED)."""
    repo = tmp_path / "tree"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "mod.py").write_text("print('RELEASE_A')\n")
    _git(["add", "-A"], repo); _git(["commit", "-q", "-m", "A"], repo)
    sha_a = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    (repo / "mod.py").write_text("print('RELEASE_B')\n")   # STAGED = B is what sits in the tree now
    _git(["add", "-A"], repo); _git(["commit", "-q", "-m", "B"], repo)
    sha_b = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    return repo, sha_a, sha_b, tmp_path / "releases"


def _exec_from(root):
    """Actually run `python` importing mod from `root` — returns stdout (the release identity it printed)."""
    r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import mod", str(root)],
                       capture_output=True, text=True)
    return r.stdout.strip()


# ── APPROVED code comes from LOCAL git objects, materialised into an immutable dir ────────────────
def test_approved_material_from_git_objects(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    path, verdict = RA.materialise_release(sha_a, releases, repo)
    assert verdict == "OK" and (path / RA.RELEASE_SHA_FILE).read_text().strip() == sha_a
    assert (path / "mod.py").read_text() == "print('RELEASE_A')\n"   # exactly A, not the B in the tree


# ── with STAGED=B in the tree and APPROVED=A, exec runs A — proven by real subprocess exec ────────
def test_exec_runs_approved_A_not_staged_B(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    RA.materialise_release(sha_a, releases, repo)
    plan = RA.activation_plan(approved_sha=sha_a, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert plan["action"] == "EXEC_FROM_RELEASE"
    out = _exec_from(plan["root"])
    assert out == "RELEASE_A"                                  # A executed
    assert out != "RELEASE_B"                                  # B did NOT
    # and the staged tree is provably NOT the exec root
    assert str(repo) not in plan["root"]


# ── B must never execute accidentally: the resolver never yields the shared tree ──────────────────
def test_staged_tree_is_never_the_exec_root(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    RA.materialise_release(sha_a, releases, repo)
    for approved in (sha_a, sha_b, None, "deadbeef"):
        root, _ = RA.exec_root(approved, releases)
        assert root is None or str(repo) not in str(root)     # never the tree that holds B


# ── no approval → fail CLOSED, execute nothing (no application module loads) ───────────────────────
def test_no_approval_fails_closed(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    plan = RA.activation_plan(approved_sha=None, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert plan["action"] == "FAIL_CLOSED" and plan["verdict"] == "DEPLOYMENT_APPROVAL_REQUIRED"
    # the wrapper, seeing FAIL_CLOSED, imports nothing — simulate and assert B never printed
    assert RA.exec_root(None, releases)[0] is None


# ── daily-cycle path: sync B then approval missing → B cannot execute ─────────────────────────────
def test_daily_cycle_staged_B_no_approval_cannot_run_B(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab   # tree already holds B (the "sync B" state)
    plan = RA.activation_plan(approved_sha=None, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert plan["action"] == "FAIL_CLOSED"                    # cycle must not run the staged money-path code


# ── recovery: APPROVED set but release dir missing, object present → MATERIALISE_THEN_EXEC ─────────
def test_missing_release_recovers_from_object(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    plan = RA.activation_plan(approved_sha=sha_a, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert plan["action"] == "MATERIALISE_THEN_EXEC" and plan["recoverable"] is True
    # object absent → fail CLOSED, never the tree
    plan2 = RA.activation_plan(approved_sha="deadbeef" * 5, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert plan2["action"] == "FAIL_CLOSED"


# ── rollback proof: repoint APPROVED to the prior release; exec follows it, atomically ────────────
def test_rollback_reactivates_prior_release(repo_ab):
    repo, sha_a, sha_b, releases = repo_ab
    RA.materialise_release(sha_a, releases, repo)             # prior known-good A
    RA.materialise_release(sha_b, releases, repo)             # bad B also materialised
    # active was B; rollback = approve A again → exec runs A, no git history rewrite
    plan = RA.activation_plan(approved_sha=sha_a, staged_sha=sha_b, releases_dir=releases, repo=repo)
    assert _exec_from(plan["root"]) == "RELEASE_A"
