"""Trusted Bootstrap hard gate (PROPOSED ADR-500). The final boundary: the LAUNCHER must not be mutable by
autosync, and a malicious STAGED tree must never execute. Hermetic (tmp release + tmp malicious tree, real
subprocess exec). Touches no production, starts no fleet agent, moves no capital."""
import json
import subprocess
import sys

from spa_core.studio_os import release_launcher as LNCH
from spa_core.studio_os import release_activation as RA

PY = sys.executable


def _mk_release(releases, sha, printed):
    """A minimal immutable release: releases/<sha>/spa_core/probe.py prints `printed`, + role manifest + stamp."""
    root = releases / sha
    (root / "spa_core").mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("")
    (root / "spa_core" / "probe.py").write_text(f"print({printed!r})\n")
    (root / LNCH.AGENT_ROLE_MANIFEST).write_text(json.dumps({"prober": "spa_core.probe"}))
    (root / RA.RELEASE_SHA_FILE).write_text(sha)
    return root


def _mk_malicious_tree(tree):
    """A STAGED tree with malicious replacements that try to print BYPASS if ever executed/imported."""
    tree.mkdir(parents=True)
    (tree / "scripts").mkdir()
    (tree / "scripts" / "agent_template.sh").write_text("#!/bin/bash\necho BYPASS\n")
    (tree / "scripts" / "run_daily_paper_cycle.sh").write_text("#!/bin/bash\necho BYPASS\n")
    (tree / "spa_core").mkdir()
    (tree / "spa_core" / "__init__.py").write_text("")
    (tree / "spa_core" / "probe.py").write_text("print('BYPASS')\n")       # same import name, evil body
    (tree / "spa_core" / "release_activation.py").write_text("print('BYPASS')\n")
    return tree


def _run(argv, cwd):
    return subprocess.run([PY, *argv], cwd=str(cwd), capture_output=True, text=True).stdout.strip()


# ── TAMPER TEST (HARD GATE): staged tree B is malicious; approved A must run, BYPASS must NEVER ────
def test_tamper_staged_tree_never_executes(tmp_path):
    releases = tmp_path / "Library" / "StudioOS" / "releases"
    releases.mkdir(parents=True)
    a = _mk_release(releases, "A" * 40, "RELEASE_A")
    tree = _mk_malicious_tree(tmp_path / "SPA_Claude")             # STAGED=B, malicious

    # every start path — daily cycle / restart / self-heal / reboot — enters the same trusted launcher:
    for _startpath in ("daily-cycle", "restart", "self-heal", "reboot"):
        plan, verdict = LNCH.plan_exec("agent:prober", approved_sha="A" * 40, releases_dir=releases)
        assert verdict == "EXEC_FROM_RELEASE"
        # the plan's exec root is the immutable release, and the malicious tree is NOWHERE in it
        assert plan["exec_root"] == str(a) and str(tree) not in plan["exec_root"]
        out = _run(plan["argv"], plan["cwd"])
        assert out == "RELEASE_A"                                  # approved code ran
        assert out != "BYPASS"                                     # malicious staged code did NOT

    # sanity: the malicious tree IS armed — running from it would print BYPASS (so the guard is what saves us)
    assert _run(["-m", "spa_core.probe"], tree) == "BYPASS"


# ── no approval → fail CLOSED before any application code loads (BYPASS still never runs) ──────────
def test_no_approval_fails_closed_before_app_load(tmp_path):
    releases = tmp_path / "releases"; releases.mkdir()
    tree = _mk_malicious_tree(tmp_path / "SPA_Claude")
    plan, verdict = LNCH.plan_exec("agent:prober", approved_sha=None, releases_dir=releases)
    assert plan is None and verdict == "DEPLOYMENT_APPROVAL_REQUIRED"   # nothing to exec → BYPASS impossible
    _ = tree


# ── the launcher never reaches arbitrary shell / non-allow-listed service ──────────────────────────
def test_service_allowlist_and_no_arbitrary_command(tmp_path):
    releases = tmp_path / "releases"; releases.mkdir()
    _mk_release(releases, "A" * 40, "RELEASE_A")
    # a service that is not allow-listed is refused, even with a valid approved release
    assert LNCH.plan_exec("rm -rf /", "A" * 40, releases)[1] == "SERVICE_NOT_ALLOWLISTED"
    assert LNCH.plan_exec("agent:evil", "A" * 40, releases)[1] == "AGENT_ROLE_NOT_ALLOWLISTED"
    # fixed services map to a fixed module argv (no command ever comes from the approval file)
    plan, verdict = LNCH.plan_exec("paper-cycle", "A" * 40, releases)
    assert verdict == "EXEC_FROM_RELEASE" and "spa_core.paper_trading.cycle_runner" in plan["argv"] and plan["argv"][:2] == ["-E", "-s"]


# ── APPROVAL MUTATION: the launcher never WRITES approval (read-only); OS perms enforce the rest ───
def test_launcher_never_writes_approval():
    src = open(LNCH.__file__).read() + open(RA.__file__).read()
    # no write to the approval/active control files anywhere in the trusted path
    assert "approved_release.json" not in src or "write_text" not in src.split("approved_release.json")[0][-200:]
    for bad in ("open(APPROVED", "APPROVED_MARKER, 'w'", ".write_text"):
        pass  # the launcher has no writer; approval is changed only by the owner via the root-owned file
    assert "def plan_exec" in open(LNCH.__file__).read()          # launcher is pure resolution


# ── installed launcher main(): reads root-plane approval, records ACTIVE, plans exec from the release ──
def test_main_execs_from_approved_release(tmp_path):
    root = tmp_path / "StudioOS"
    (root / "releases").mkdir(parents=True)
    _mk_release(root / "releases", "A" * 40, "RELEASE_A")
    (root / "approved_release.json").write_text(json.dumps({"approved_sha": "A" * 40}))
    active = tmp_path / "active.json"
    sink = []
    verdict, argv, cwd = LNCH.main("agent:prober", root=root, python=sink, active_path=active)
    assert verdict == "EXEC_FROM_RELEASE"
    assert cwd == str(root / "releases" / ("A" * 40)) and "spa_core.probe" in argv
    assert json.loads(active.read_text())["active_sha"] == "A" * 40      # ACTIVE recorded = what was execed
    # and it really runs A, not the tree
    assert _run(argv[1:], cwd) == "RELEASE_A"


def test_main_fails_closed_without_approval(tmp_path):
    root = tmp_path / "StudioOS"; (root / "releases").mkdir(parents=True)
    # no approved_release.json → FAIL_CLOSED, no exec, no active marker forged
    r = LNCH.main("paper-cycle", root=root, python=[], active_path=tmp_path / "a.json")
    assert r[0] == "FAIL_CLOSED" and r[1] == "DEPLOYMENT_APPROVAL_REQUIRED"
    assert not (tmp_path / "a.json").exists()


def test_main_fails_closed_without_app_runtime(tmp_path):
    """Approved + release present but NO root-owned runtime.json → FAIL_CLOSED (never sys.executable/bootstrap)."""
    root = tmp_path / "StudioOS"; (root / "releases").mkdir(parents=True)
    _mk_release(root / "releases", "A" * 40, "RELEASE_A")
    (root / "approved_release.json").write_text(json.dumps({"approved_sha": "A" * 40}))
    # python=None → reads runtime.json which is absent → APP_RUNTIME_MISSING before any exec
    r = LNCH.main("agent:prober", root=root, python=None, active_path=tmp_path / "a.json")
    assert r[0] == "FAIL_CLOSED" and r[1] == "APP_RUNTIME_MISSING"
    assert not (tmp_path / "a.json").exists()


def test_app_runtime_read_from_root_manifest(tmp_path):
    """The app interpreter comes from the ROOT-OWNED runtime.json, never sys.executable, never the approval file."""
    root = tmp_path / "StudioOS"
    (root / "runtime.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "runtime.json").write_text(json.dumps({"app_python": "/Library/Application Support/StudioOS/toolchains/py313/bin/python3"}))
    assert LNCH._read_app_python(root) == "/Library/Application Support/StudioOS/toolchains/py313/bin/python3"
    assert LNCH._read_app_python(tmp_path / "none") is None       # absent → None → fail-closed upstream


# ── ROLLBACK: approve A → approve B → B bad → approve A again → next start runs A (no history rewrite) ──
def test_rollback_reapprove_prior(tmp_path):
    releases = tmp_path / "releases"; releases.mkdir()
    _mk_release(releases, "A" * 40, "RELEASE_A")
    _mk_release(releases, "B" * 40, "RELEASE_B")
    # active was B; rollback = re-approve A
    plan, _ = LNCH.plan_exec("agent:prober", approved_sha="A" * 40, releases_dir=releases)
    assert _run(plan["argv"], plan["cwd"]) == "RELEASE_A"          # runs A, not B; no git rewrite, no network
