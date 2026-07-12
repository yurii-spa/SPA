#!/usr/bin/env python3
"""Go-live freshness cycle — the body of com.spa.golive_freshness (Q1-11).

Keeps the go-live readiness verdict + the money-path pre-cutover proof FRESH and
DATED, decoupled from the daily cycle, so a diligence reviewer never meets a stale
readiness artifact:

  golive_checker    -> data/golive_status.json   (29-criteria gate; exit 1 == NOT READY
                                                   is a VERDICT, not a crash)
  pre_cutover_gate  -> its INERT readiness proof  (money-path defenses; never moves capital)

Reporter, NOT a gate (mirrors resilience_cycle.py): each step is best-effort and its
exit code is RECORDED, never propagated — golive_checker exits 1 while the track is
<30 evidenced days, which is the honest verdict, not a failure. Writes a small dated
freshness stamp (atomic) so agent_health / the briefing can confirm THIS agent ran.
Touches no live-track state beyond what golive_checker already writes; stdlib only. Exit 0.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Make spa_core importable regardless of the launchd cwd (the script's own dir is
# sys.path[0], not the repo root) so the atomic freshness-stamp writer resolves.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STEPS: list[tuple[str, list[str]]] = [
    ("golive_checker", [PY, "-m", "spa_core.paper_trading.golive_checker"]),
    ("pre_cutover_gate", [PY, str(ROOT / "scripts" / "pre_cutover_gate.py")]),
    # Q1-9: refresh the owner-only procurement tracker AFTER golive_checker rewrites
    # golive_status.json, so track_days is derived from the just-updated count. Advisory;
    # never marks audit/legal satisfied on its own (owner-asserted evidence only).
    ("owner_blockers", [PY, "-m", "spa_core.execution.owner_blockers"]),
    # Q1-13 (owner-flagged): refresh the capital-efficiency guard — flags LAZY idle cash (deployable
    # T1/T2 headroom left at 0%). Read-only/advisory: writes data/capital_efficiency.json which
    # agent_health escalates. Non-zero exit here just means WARNING/UNKNOWN — best-effort, never gates.
    ("capital_efficiency", [PY, "-m", "spa_core.monitoring.capital_efficiency"]),
]


def main() -> int:
    results: dict[str, int | None] = {}
    for name, cmd in STEPS:
        try:
            r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
            results[name] = r.returncode
            out = (r.stdout or r.stderr or "").strip().splitlines()
            last = out[-1] if out else ""
            print(f"[golive_freshness] {name}: exit {r.returncode}  {last}")
        except Exception as exc:  # noqa: BLE001 — best-effort; never abort the cycle
            results[name] = None
            print(f"[golive_freshness] {name}: ERROR {exc}")

    # Dated freshness stamp so agent_health / the briefing can confirm THIS agent ran.
    # golive_checker's exit 1 (NOT READY) is RECORDED, never treated as a failure.
    try:
        from spa_core.utils.atomic import atomic_save

        atomic_save(
            {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "steps": results,
                "note": (
                    "reporter — golive_checker exit 1 means NOT READY (a verdict), not a crash; "
                    "pre_cutover_gate is INERT (never moves capital). Freshness only."
                ),
                "is_advisory": True,
            },
            str(ROOT / "data" / "golive_freshness.json"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[golive_freshness] stamp ERROR {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
