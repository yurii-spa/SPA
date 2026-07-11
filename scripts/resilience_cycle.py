#!/usr/bin/env python3
"""Resilience cycle — the body of com.spa.resilience.

Exercises the DR machinery so the posture is *provably re-proven*, not dormant,
then rolls it up:

  R6 offsite-copy      -> data/dr_offsite_status.json
  R7 restore drill     -> data/restore_drill_status.json
  R4 fleet-down drill  -> data/fleet_drill_status.json
  R8 resilience rollup -> data/resilience_status.json   (reads the three above)

Each step is isolated (best-effort): one failing step never stops the rest, and
the rollup surfaces any failure honestly (fail-CLOSED -> WARNING). None of these
touch the live track — the drills are sandboxed / pure and all writes are atomic.
stdlib only. Exit 0 (a reporter, not a gate).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Order matters: exercise the three drills first, then roll their fresh statuses
# up. Each runs with a hard timeout so a wedged drill can't hang the agent.
STEPS: list[tuple[str, list[str]]] = [
    ("R6 offsite-copy", [PY, "-m", "spa_core.dr.offsite_copy"]),
    ("R7 restore-drill", [PY, str(ROOT / "scripts" / "drill_restore.py")]),
    ("R4 fleet-down-drill", [PY, str(ROOT / "scripts" / "drill_fleet_down.py")]),
    # Q3-6: fold the money-path brake (sandboxed, de-risk-only kill-switch drill) into the
    # provably-exercised list — it now writes a dated latency/verdict artifact each cycle.
    ("Q3-5 kill-switch-drill", [PY, str(ROOT / "scripts" / "kill_switch_drill.py")]),
    ("R8 resilience-rollup", [PY, "-m", "spa_core.monitoring.resilience_status"]),
]


def main() -> int:
    for name, cmd in STEPS:
        try:
            r = subprocess.run(
                cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300
            )
            out = (r.stdout or r.stderr or "").strip().splitlines()
            last = out[-1] if out else ""
            print(f"[resilience_cycle] {name}: exit {r.returncode}  {last}")
        except Exception as exc:  # noqa: BLE001 — best-effort; never abort the cycle
            print(f"[resilience_cycle] {name}: ERROR {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
