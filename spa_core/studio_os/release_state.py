"""Release-state model (PROPOSED ADR-500) — the deterministic separation the autosync boundary needs:

    CANONICAL  — code accepted on origin/main (the truth).
    STAGED     — code the autosync has placed on the production FILESYSTEM (what a restart WOULD load).
    ACTIVE     — code the currently-running processes were STARTED from (what is executing right now).
    APPROVED   — the release the Owner has explicitly approved for activation (owner-gated).

Why this file exists (P0, 2026-09-28): a push to origin/main is automatically staged into the active
runtime tree by `scripts/code_sync_from_origin.sh` (run from `agent_template.sh` before every agent, and
from `run_daily_paper_cycle.sh`). That checkout writes DIRECTLY into `~/Documents/SPA_Claude` — no staging
dir, no approval gate, and it never touches git HEAD. So `repo_status.production.sha` (git HEAD) is a FALSE
proxy for what is running: the filesystem can be at a new release while the processes still execute the old
in-memory code, and the next restart of ANY agent silently activates the staged code.

This module MEASURES the three SHAs honestly (ACTIVE = UNKNOWN when it cannot be proven, never faked from a
repo HEAD) and provides the pure restart-guard DECISION. It performs NO side effects on production, starts
nothing, and is imported by no money-path code. Only stdlib; all paths injectable for hermetic tests."""
from __future__ import annotations

import json
from pathlib import Path

PROD = Path.home() / "Documents" / "SPA_Claude"

# markers (read-only here). STAGED already exists (the autosync writes it). ACTIVE + APPROVED are introduced
# by the proposed fix — until agents write ACTIVE at startup and the Owner writes APPROVED, both read absent,
# and this module says so rather than guessing.
STAGED_MARKER = "data/code_sync_status.json"        # written by code_sync_from_origin.sh (existing)
ACTIVE_MARKER = "data/active_release.json"          # PROPOSED: an agent records the SHA it loaded, at startup
APPROVED_MARKER = "data/approved_active_release.json"  # PROPOSED: owner-gated approved activation SHA

UNKNOWN = "UNKNOWN"
RELEASE_SHA_FILE = ".release_sha"   # each materialised release self-identifies (matches release_activation/launcher)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def staged_sha(prod: Path = PROD):
    """The SHA the filesystem was last synced to — what a restart would load. None if unmeasurable."""
    d = _read_json(prod / STAGED_MARKER)
    if not d:
        return None
    # only trust it as STAGED when the sync actually converged (IN_SYNC / SYNCED), else it's mid-flight
    if d.get("result") in ("IN_SYNC", "SYNCED"):
        return d.get("origin_main")
    return d.get("origin_main")  # still report it, caller can see result via raw()


def active_sha(prod: Path = PROD):
    """DEPRECATED as authority: the user-writable marker is only an OBSERVATION/hint. Security must never
    depend on it — use `active_from_process()` for measured, verified ACTIVE. Kept for backward reads."""
    d = _read_json(prod / ACTIVE_MARKER)
    return (d or {}).get("active_sha")


def _default_release_procs(_run=None):
    """(label|pid, cwd) for candidate long-running processes, measured from the live OS. macOS: `lsof` cwd."""
    import subprocess
    run = _run or (lambda a: subprocess.run(a, capture_output=True, text=True, timeout=10).stdout)
    out = []
    try:
        # python processes are the ones a trusted launcher would exec from a release dir
        pids = [l.split()[0] for l in run(["pgrep", "-fl", "python"]).splitlines() if l.strip()]
        for pid in pids:
            # lsof cwd of the pid → the directory it was started in (the release dir under a trusted launcher)
            cwd = ""
            for line in run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"]).splitlines():
                if line.startswith("n"):
                    cwd = line[1:]
            if cwd:
                out.append((pid, cwd))
    except Exception:
        pass
    return out


def active_from_process(releases_root, *, procs=None):
    """MEASURED ACTIVE (ARB §6): trust the actual process, not a user-writable marker. For each running
    process whose cwd is `releases_root/<sha>/`, verify the dir self-identifies (`.release_sha` == <sha>).
    Returns {active_sha, active_evidence, active_verified}. No verified process → active_sha UNKNOWN.
    Never trusts `active_release.json` as authority."""
    releases_root = Path(releases_root)
    procs = procs if procs is not None else _default_release_procs()
    for who, cwd in procs:
        p = Path(cwd)
        stamp_file = p / RELEASE_SHA_FILE
        # cwd must be an immediate child of releases_root AND self-identify by its stamp
        if p.parent == releases_root and stamp_file.exists() and stamp_file.read_text().strip() == p.name:
            return {"active_sha": p.name, "active_verified": True,
                    "active_evidence": f"pid/label {who} cwd={cwd} .release_sha✓"}
    return {"active_sha": UNKNOWN, "active_verified": False,
            "active_evidence": "no running process has cwd in a verified releases/<sha> (launcher not wired or nothing running)"}


def approved_sha(prod: Path = PROD):
    """The Owner-approved activation SHA. None => no approved release recorded (fail-CLOSED on restart)."""
    d = _read_json(prod / APPROVED_MARKER)
    return (d or {}).get("approved_sha")


def restart_decision(staged, approved):
    """PURE guard: what an agent restart must do, given the staged (on-disk) and approved (owner) SHAs.

    Never silently activates staged canonical code. Returns one of:
      ACTIVATE_OK                 — staged == approved: loading the on-disk code is exactly what the Owner approved.
      LOAD_APPROVED_NOT_STAGED    — staged != approved: restart must load the APPROVED release, not the newer staged one.
      DEPLOYMENT_APPROVAL_REQUIRED — no approved release recorded: fail-CLOSED, do not activate anything new.
    """
    if not approved:
        return "DEPLOYMENT_APPROVAL_REQUIRED"
    if staged and staged == approved:
        return "ACTIVATE_OK"
    return "LOAD_APPROVED_NOT_STAGED"


TRUSTED_RELEASES_ROOT = "/Library/Application Support/StudioOS/releases"


def release_state(canonical, prod: Path = PROD, *, releases_root=TRUSTED_RELEASES_ROOT, procs=None) -> dict:
    """The three-state truth for Studio OS. ACTIVE is MEASURED from process evidence (ARB §6), never trusted
    from the user-writable marker; the marker is exposed only as a non-authoritative hint."""
    staged = staged_sha(prod)
    approved = approved_sha(prod)
    decision = restart_decision(staged, approved)

    meas = active_from_process(releases_root, procs=procs)   # verified process evidence
    active = meas["active_sha"] if meas["active_verified"] else None
    hint = active_sha(prod)                                   # user-writable marker — OBSERVATION only

    if active is None:                                       # cannot PROVE what executes → unverified boundary
        status_label = "ACTIVE_UNKNOWN · DEPLOYMENT_APPROVAL_REQUIRED" if decision == "DEPLOYMENT_APPROVAL_REQUIRED" \
            else "ACTIVE_UNKNOWN"
    elif staged and staged != active:
        status_label = "DEPLOYMENT_APPROVAL_REQUIRED"
    elif staged and staged == active:
        status_label = "IN_SYNC"
    else:
        status_label = "UNKNOWN"

    return {
        "schema": "studio-os/release-state/2",
        "policy": "ADR-500",
        "canonical_sha": canonical,
        "canonical_sha_short": (canonical or "")[:12],
        "staged_sha": staged,
        "staged_sha_short": (staged or "")[:12] if staged else None,
        "active_sha": active if active else UNKNOWN,
        "active_sha_short": (active or "")[:12] if active else UNKNOWN,
        "active_verified": meas["active_verified"],
        "active_evidence": meas["active_evidence"],
        "active_marker_hint": (hint or None),                # non-authoritative; never overrides measurement
        "approved_sha": approved,
        "approved_sha_short": (approved or "")[:12] if approved else None,
        "restart_decision": decision,
        "status": status_label,
        "restart_would_activate": bool(staged and staged != active and decision != "ACTIVATE_OK"),
        "note": "ACTIVE is MEASURED from process cwd → root-owned releases/<sha> → .release_sha; the "
                "user-writable active_release.json is a hint, never authority. UNKNOWN when unproven.",
    }
