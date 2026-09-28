"""Trusted release LAUNCHER (ACCEPTED ADR-500, Trusted-Bootstrap) — SELF-CONTAINED reference logic that, in
production, is INSTALLED into the root-owned trusted plane so the autosync cannot replace it.

TRUST CLOSURE (ARB Phase 2): this file has **NO import from `~/Documents/SPA_Claude`** — only stdlib. It must
not depend on any mutable project module to select the approved release, or a malicious staged tree could
subvert the selector before the release is chosen. (The earlier draft imported `spa_core.studio_os.
release_activation`; that was a mutable pre-exec dependency and is inlined here.) The installed copy execs the
approved release with an ISOLATED interpreter (`python -E -s`: ignore PYTHONPATH + user-site, keep the release dir on the path) and cwd set to the
immutable release dir, so imports resolve ONLY from the approved release + stdlib — never the mutable tree.

The final boundary: every launchd entrypoint today is `/bin/bash ~/Documents/SPA_Claude/scripts/*.sh` (inside
autosync). The fix reuses the existing root-owned trusted plane `/Library/Application Support/StudioOS/`
(user-write-DENIED — proven live; same pattern as `worker_runner-<sha>.py` at root:wheel 0444). Installed as
`/Library/Application Support/StudioOS/bin/release_launcher-<sha256>.py`; launchd ProgramArguments repoint to
it. It reads APPROVED from a root-owned control file the user cannot write, maps a FIXED service id to an
ALLOW-LISTED argv (never arbitrary shell from the approval file), and execs ONLY from `releases/<APPROVED>/`.
FAIL CLOSED before any application code loads on: approval missing · sha invalid · release missing/corrupt ·
service/role not allow-listed."""
from __future__ import annotations

import json
from pathlib import Path

RELEASE_SHA_FILE = ".release_sha"    # each materialised release self-identifies with its own sha

# FIXED service → allow-listed argv. Lives in the launcher (immutable, root plane), NOT in the approval file,
# so an approval can only ever name a SHA — never a command. `-E -s` = ignore PYTHONPATH + user site (proven: blocks an injected PYTHONPATH) while cwd=<release>
# keeps the module path = the approved release only. `-I` was rejected: it drops cwd, so `-m` cannot find the release.
SERVICE_ALLOWLIST = {
    "paper-cycle":  ["-E", "-s", "-m", "spa_core.paper_trading.cycle_runner", "--verbose", "--live"],
    "orchestrator": ["-E", "-s", "-m", "spa_core.orchestrator.adapter_orchestrator"],
    "telegram":     ["-E", "-s", "-m", "spa_core.telegram.bot"],
    "canary": ["-E", "-s", "-m", "spa_core.monitoring.deployment_acceptance"],  # benign, non-money, exits — the CANARY service
}
AGENT_ROLE_MANIFEST = "studio_release_agents.json"   # {role: "spa_core.module.path"} committed in the release


def exec_root(approved_sha, releases_dir):
    """PURE, stdlib-only: the immutable dir a process MUST exec from. Never the mutable tree. Returns
    (root|None, verdict): ACTIVATE_OK · DEPLOYMENT_APPROVAL_REQUIRED · APPROVED_RELEASE_MISSING · APPROVED_RELEASE_CORRUPT."""
    if not approved_sha:
        return None, "DEPLOYMENT_APPROVAL_REQUIRED"
    root = Path(releases_dir) / approved_sha
    if not root.is_dir():
        return None, "APPROVED_RELEASE_MISSING"
    stamp = root / RELEASE_SHA_FILE
    if not stamp.exists() or stamp.read_text().strip() != approved_sha:
        return None, "APPROVED_RELEASE_CORRUPT"
    return root, "ACTIVATE_OK"


def _agent_argv(release_root: Path, role: str):
    try:
        m = json.loads((Path(release_root) / AGENT_ROLE_MANIFEST).read_text())
        mod = m.get(role)
        return ["-E", "-s", "-m", mod] if isinstance(mod, str) and mod.startswith("spa_core.") else None
    except Exception:
        return None


def plan_exec(service, approved_sha, releases_dir):
    """PURE: how the trusted launcher must exec `service`, or why it fails CLOSED. Returns (plan|None, verdict).
    plan = {argv, cwd, exec_root, sha} — exec `python <argv>` with cwd=exec_root so imports come from the
    APPROVED release only. The mutable tree is never read here."""
    if service not in SERVICE_ALLOWLIST and not service.startswith("agent:"):
        return None, "SERVICE_NOT_ALLOWLISTED"
    root, verdict = exec_root(approved_sha, releases_dir)
    if verdict != "ACTIVATE_OK":
        return None, verdict
    argv = SERVICE_ALLOWLIST.get(service)
    if argv is None:
        argv = _agent_argv(root, service.split(":", 1)[1])
        if argv is None:
            return None, "AGENT_ROLE_NOT_ALLOWLISTED"
    return {"argv": argv, "cwd": str(root), "exec_root": str(root), "sha": approved_sha}, "EXEC_FROM_RELEASE"


# ── installed entrypoint (root plane). launchd runs: <trusted python> <this file> <service-id> ──────────
# Trusted-plane fixed locations (all root-owned, user-write-denied). Overridable ONLY for hermetic tests.
TRUSTED_ROOT = "/Library/Application Support/StudioOS"
# INTERPRETER: the launcher re-execs the approved release with the SAME interpreter it is already running under
# (`sys.executable`) — i.e. the one launchd invoked it with, named in the ROOT-OWNED plist ProgramArguments.
# The interpreter-trust decision therefore lives in the root-owned plist (the Owner names a non-user-writable
# python there), not in a hardcoded path here — which also avoids a wrong/absent path. (ARB Checkpoint-A fix:
# the earlier hardcoded `…/toolchains/base/bin/python3` did not exist.)
# ACTIVE is an observation marker (what actually started), not authority; written user-side, never read as a gate.
ACTIVE_MARKER_PATH = str(Path.home() / "Documents" / "SPA_Claude" / "data" / "active_release.json")


def _read_approved(approved_file):
    try:
        return json.loads(Path(approved_file).read_text()).get("approved_sha")
    except Exception:
        return None


def main(service_id, *, root=None, python=None, active_path=None):
    """The installed launcher's exec: resolve the approved release, record ACTIVE, exec from the release with a
    deterministic isolated interpreter. FAIL CLOSED (exit 3) before any application code loads. Never touches
    the mutable tree. Returns a verdict string in test mode (when python is a list sink) or execs for real."""
    import os
    import sys
    root = Path(root or TRUSTED_ROOT)
    approved = _read_approved(root / "approved_release.json")
    plan, verdict = plan_exec(service_id, approved, root / "releases")
    if verdict != "EXEC_FROM_RELEASE":
        return ("FAIL_CLOSED", verdict)
    # record ACTIVE = the sha we are about to exec (observation only)
    try:
        ap = Path(active_path or ACTIVE_MARKER_PATH)
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_text(json.dumps({"active_sha": plan["sha"], "service": service_id}))
    except Exception:
        pass
    # re-exec the release with the SAME (trusted, launchd-named) interpreter; no hardcoded path
    py = sys.executable if python is None else python
    if isinstance(py, list):                     # test hook: capture instead of exec
        py.append((py_exec := [sys.executable, *plan["argv"]], plan["cwd"]))
        return ("EXEC_FROM_RELEASE", py_exec, plan["cwd"])
    os.chdir(plan["cwd"])
    os.execv(py, [py, *plan["argv"]])            # replaces the process; imports come from the release only


if __name__ == "__main__":                       # pragma: no cover — exercised in production, not CI
    import sys
    if len(sys.argv) < 2:
        sys.stderr.write("usage: release_launcher.py <service-id>\n"); sys.exit(2)
    r = main(sys.argv[1])
    if r and r[0] == "FAIL_CLOSED":
        sys.stderr.write(f"trusted-launcher FAIL_CLOSED: {r[1]}\n"); sys.exit(3)
