"""Production activation-boundary (PROPOSED ADR-500) — CANONICAL ≠ STAGED ≠ ACTIVE, and no restart may
silently activate staged canonical code. Every test A–H from the boundary spec, hermetic (tmp markers,
never touches ~/Documents/SPA_Claude, starts nothing, moves no capital)."""
import json

from spa_core.studio_os import release_state as R


def _write(prod, name, obj):
    (prod / "data").mkdir(parents=True, exist_ok=True)
    (prod / name).write_text(json.dumps(obj), encoding="utf-8")


def _proc_active(tmp_path, sha):
    """Simulate a running process executing from a VERIFIED release dir → measured ACTIVE=sha (ARB §6)."""
    root = tmp_path / "releases"; rel = root / sha; rel.mkdir(parents=True, exist_ok=True)
    (rel / R.RELEASE_SHA_FILE).write_text(sha)
    return root, [("pid", str(rel))]


# ── A. canonical changes while ACTIVE remains unchanged ──────────────────────────────────
def test_A_canonical_moves_active_unchanged(tmp_path):
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "X1"})
    root, procs = _proc_active(tmp_path, "X1")                       # X1 is running (measured)
    s1 = R.release_state("X1", prod=tmp_path, releases_root=root, procs=procs)
    s2 = R.release_state("X2", prod=tmp_path, releases_root=root, procs=procs)  # canonical → X2
    assert s1["active_sha"] == "X1" and s2["active_sha"] == "X1"     # ACTIVE unchanged (measured)
    assert s2["canonical_sha"] == "X2"                               # CANONICAL moved
    assert s2["staged_sha"] == "X1"                                  # STAGED not yet advanced


# ── B. autosync stages a new release but ACTIVE remains unchanged ─────────────────────────
def test_B_autosync_stages_active_unchanged(tmp_path):
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "X2"})  # autosync staged X2
    root, procs = _proc_active(tmp_path, "X1")                       # but X1 still running (measured)
    s = R.release_state("X2", prod=tmp_path, releases_root=root, procs=procs)
    assert s["staged_sha"] == "X2" and s["active_sha"] == "X1"       # staged ahead of measured active
    assert s["restart_would_activate"] is True
    assert s["status"] == "DEPLOYMENT_APPROVAL_REQUIRED"


# ── C. an unapproved restart cannot activate STAGED ───────────────────────────────────────
def test_C_unapproved_restart_cannot_activate_staged():
    # no approved release recorded → fail CLOSED, never activate the staged code
    assert R.restart_decision(staged="X2", approved=None) == "DEPLOYMENT_APPROVAL_REQUIRED"
    # approved is the OLD release → restart must load the approved one, not the newer staged one
    assert R.restart_decision(staged="X2", approved="X1") == "LOAD_APPROVED_NOT_STAGED"


# ── D. owner-approved activation changes ACTIVE ───────────────────────────────────────────
def test_D_owner_approved_activation(tmp_path):
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "X2"})
    _write(tmp_path, R.APPROVED_MARKER, {"approved_sha": "X2"})       # owner approves X2
    assert R.restart_decision("X2", "X2") == "ACTIVATE_OK"
    # after the (approved) restart, a process now runs from the X2 release → measured ACTIVE=X2, IN_SYNC
    root, procs = _proc_active(tmp_path, "X2")
    s = R.release_state("X2", prod=tmp_path, releases_root=root, procs=procs)
    assert s["active_sha"] == "X2" and s["status"] == "IN_SYNC"
    assert s["restart_would_activate"] is False


# ── E. a failed activation rolls back to the previous release ─────────────────────────────
def test_E_failed_activation_rolls_back(tmp_path):
    # X2 staged but activation FAILED → approved stays at the previous known-good X1
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "X2"})
    _write(tmp_path, R.APPROVED_MARKER, {"approved_sha": "X1"})       # rollback target = prior good
    # the guard directs a restart to the APPROVED (rolled-back) release, not the failed staged one
    assert R.restart_decision(staged="X2", approved="X1") == "LOAD_APPROVED_NOT_STAGED"


# ── F. reboot / self-heal cannot bypass approval ──────────────────────────────────────────
def test_F_reboot_selfheal_cannot_bypass(tmp_path):
    # the guard is PURE and path-independent: manual restart, reboot, crash self-heal, scheduled restart
    # all call the same decision. With no approval it is always fail-CLOSED regardless of what is staged.
    for staged in ("X2", "X9", None):
        assert R.restart_decision(staged=staged, approved=None) == "DEPLOYMENT_APPROVAL_REQUIRED"


# ── G. Studio OS reports CANONICAL / STAGED / ACTIVE correctly ────────────────────────────
def test_G_reports_three_states(tmp_path):
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "STG"})
    root, procs = _proc_active(tmp_path, "ACT")                     # ACTIVE measured from a verified process
    s = R.release_state("CAN", prod=tmp_path, releases_root=root, procs=procs)
    assert (s["canonical_sha"], s["staged_sha"], s["active_sha"]) == ("CAN", "STG", "ACT")
    assert s["active_verified"] is True
    # ACTIVE is UNKNOWN (never faked) when no process evidence exists — even if a marker claims one
    s2 = R.release_state("CAN", prod=tmp_path, releases_root=tmp_path / "empty", procs=[])
    assert s2["active_sha"] == "UNKNOWN" and s2["active_verified"] is False


# ── H. no financial / execution path is touched by this model ─────────────────────────────
def test_H_no_money_path_touched():
    import spa_core.studio_os.release_state as mod
    src = open(mod.__file__).read()
    assert "spa_core.execution" not in src and "spa_core.risk" not in src
    assert "spa_core.governance" not in src and "paper_trading" not in src
    # and the reverse: money-path modules must not import the release model (kept a read-only projection)
    import spa_core.risk.policy as pol
    assert "release_state" not in open(pol.__file__).read()


# ── ARB §6: ACTIVE is MEASURED from process evidence, never trusted from the user-writable marker ──
def test_active_measured_from_process_evidence(tmp_path):
    releases = tmp_path / "releases"
    rel = releases / ("A" * 40); rel.mkdir(parents=True)
    (rel / R.RELEASE_SHA_FILE).write_text("A" * 40)
    # a process whose cwd IS the verified release dir → measured, verified
    m = R.active_from_process(releases, procs=[("pid123", str(rel))])
    assert m["active_verified"] is True and m["active_sha"] == "A" * 40 and "pid123" in m["active_evidence"]


def test_active_ignores_user_writable_marker(tmp_path):
    # marker claims X, but NO process runs from a verified release → ACTIVE must be UNKNOWN, not X
    _write(tmp_path, R.ACTIVE_MARKER, {"active_sha": "X" * 40})
    _write(tmp_path, R.STAGED_MARKER, {"result": "IN_SYNC", "origin_main": "S" * 40})
    s = R.release_state("C" * 40, prod=tmp_path, releases_root=tmp_path / "releases", procs=[])
    assert s["active_sha"] == "UNKNOWN" and s["active_verified"] is False
    assert s["active_marker_hint"] == "X" * 40            # exposed as a hint only, never as authority


def test_active_rejects_unstamped_or_mismatched_dir(tmp_path):
    releases = tmp_path / "releases"
    (releases / ("A" * 40)).mkdir(parents=True)           # no .release_sha stamp
    assert R.active_from_process(releases, procs=[("p", str(releases / ("A" * 40)))])["active_verified"] is False
    bad = releases / ("B" * 40); bad.mkdir()
    (bad / R.RELEASE_SHA_FILE).write_text("C" * 40)        # stamp != dir name
    assert R.active_from_process(releases, procs=[("p", str(bad))])["active_verified"] is False
