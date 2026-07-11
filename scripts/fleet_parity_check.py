#!/usr/bin/env python3
"""Q3-2 — Fleet-parity self-check (deterministic, advisory).

A drift guard for the LaunchAgent fleet, in the same spirit as the doc-drift guard: it asserts the
three declarations of "the fleet" agree with each other, so a plist that no installer installs (a
loaded-not-installed orphan) or an installer line pointing at a missing plist can never silently rot.

Three sources of truth:
  • DECLARED  — labels the installer (`scripts/install_all_agents.sh`) actually installs.
  • PLIST     — `com.spa.*.plist` files present on disk (scripts/ + launchd/).
  • RETIRED   — `agent_health_monitor.RETIRED_LABELS` (deliberately not-installed; must not revive).

Parity classes (any non-empty problem class → status DRIFT):
  • broken_declared_no_plist   — installer installs a label whose plist file is missing → install fails.
  • orphan_plist_not_declared  — a plist exists that is NEITHER installed NOR retired → dead/confusing.
  • retired_but_installed      — a RETIRED label the installer still installs → revival hazard (409/flood).

The LIVE running fleet (`launchctl list | grep com.spa`) is compared too WHEN available (prod host);
in a sandbox/CI checkout launchctl is absent, so that comparison is reported as `unavailable`, never
failed. Deterministic, stdlib-only, LLM-forbidden, fail-CLOSED. Advisory — writes a status file, never
loads/unloads anything.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402

_INSTALLER = ROOT / "scripts" / "install_all_agents.sh"
_PLIST_DIRS = (ROOT / "scripts", ROOT / "launchd")
_OUT = ROOT / "data" / "fleet_parity.json"

# a quoted "com.spa.<label>" token that is NOT a path and NOT a .plist filename = an install label
_LABEL_RE = re.compile(r'"(com\.spa\.[a-z0-9_-]+)"')


def declared_labels() -> set:
    """Labels the installer installs — the quoted install_agent label arg (not the plist path)."""
    try:
        text = _INSTALLER.read_text()
    except OSError as e:
        raise RuntimeError(f"fleet_parity: installer unreadable ({e})") from e
    out = set()
    for line in text.splitlines():
        # strip shell comments FIRST — a commented-out install_agent block is NOT a declared install
        # (matching it produced a false httpserver positive). The label arg is a bare quoted token; the
        # plist PATH arg is quoted too but the regex already only accepts label-shaped tokens (no '/').
        code = line.split("#", 1)[0]
        for m in _LABEL_RE.finditer(code):
            out.add(m.group(1))
    return out


def plist_labels() -> set:
    out = set()
    for d in _PLIST_DIRS:
        if d.is_dir():
            for p in d.glob("com.spa.*.plist"):
                out.add(p.name[:-len(".plist")])
    return out


def retired_labels() -> set:
    from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
    return set(RETIRED_LABELS)


def _live_labels():
    """Running com.spa.* labels via launchctl, or None when launchctl is unavailable (sandbox/CI)."""
    if not shutil.which("launchctl"):
        return None
    try:
        res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    labels = set()
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[-1].startswith("com.spa."):
            labels.add(parts[-1].strip())
    return labels


def build_report(write: bool = True) -> dict:
    declared = declared_labels()
    plist = plist_labels()
    retired = retired_labels()

    broken = sorted(declared - plist)                      # installed but no plist file
    orphan = sorted(plist - declared - retired)            # plist exists, not installed, not retired
    retired_installed = sorted(declared & retired)         # retired yet still installed → hazard

    live = _live_labels()
    live_block = {"available": live is not None}
    if live is not None:
        # a declared+has-plist label that is NOT running (excluding retired) — a possibly-down agent
        expected_running = (declared & plist) - retired
        live_block["running_count"] = len(live)
        live_block["declared_not_running"] = sorted(expected_running - live)
        live_block["running_not_declared"] = sorted(live - declared - retired)

    problems = bool(broken or orphan or retired_installed)
    report = {
        "model": "fleet_parity_check",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "status": "DRIFT" if problems else "OK",
        "n_declared": len(declared),
        "n_plist": len(plist),
        "n_retired": len(retired),
        "broken_declared_no_plist": broken,
        "orphan_plist_not_declared": orphan,
        "retired_but_installed": retired_installed,
        "live": live_block,
        "note": (
            "Deterministic fleet-drift guard: the installer's declared fleet, the on-disk plists, and "
            "RETIRED_LABELS must agree. broken = installer references a missing plist; orphan = a plist "
            "nobody installs and isn't retired (loaded-not-installed hazard); retired_but_installed = a "
            "retired label the installer still installs (revival/flood hazard). launchctl comparison runs "
            "only on the prod host; absent in sandbox/CI (reported unavailable, never failed). Advisory."
        ),
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


def main() -> int:
    rep = build_report(write=True)
    print(f"fleet parity: {rep['status']}  "
          f"(declared {rep['n_declared']} / plist {rep['n_plist']} / retired {rep['n_retired']})")
    for k in ("broken_declared_no_plist", "orphan_plist_not_declared", "retired_but_installed"):
        if rep[k]:
            print(f"  {k}: {rep[k]}")
    lv = rep["live"]
    if lv.get("available"):
        if lv.get("declared_not_running"):
            print(f"  declared_not_running (host): {lv['declared_not_running']}")
    else:
        print("  live launchctl comparison: unavailable (not on prod host)")
    print(f"  → wrote {_OUT}")
    return 1 if rep["status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
