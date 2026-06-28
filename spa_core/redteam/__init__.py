"""
spa_core/redteam/ — the STANDING adversarial red-team + smoke INFRASTRUCTURE.

WHY THIS PACKAGE EXISTS
-----------------------
For every sprint the ad-hoc red-team caught a real, serious flaw (a forged proof head that
self-verified, a structural-veto size-down exploit, a track-corrupting cycle run, …). That value
came from a HABIT, not a SYSTEM — a single throwaway file per sprint. This package turns the habit
into infrastructure: every attack surface red-teams ITSELF, continuously, deterministically.

THE CONTRACT (a scenario)
-------------------------
A red-team scenario is a small, pure adversary against ONE surface:

    surface  — which defense it attacks (money-path / proof / optimizer / sleeves /
               kill-switch / feeds / dashboard-contract)
    attack(sandbox) -> Finding — it mutates ONLY a SANDBOX copy (never live data/), feeds the
               tampered artifact through the REAL defense, and reports whether the defense CAUGHT it.
    expected — caught must be True. A scenario that finds an UNCAUGHT flaw means the desk has a
               real hole → the runner verdict is FAIL (fail-CLOSED).

GUARDRAILS (repo rules — enforced here)
---------------------------------------
* READ-ONLY against live data/: scenarios receive a per-run SANDBOX path (a tmp dir) and MUST
  confine every mutation to it. The runner snapshots the live data/ dir's surface files BEFORE and
  AFTER a full run and FAILS CLOSED if a single byte of the live track changed.
* stdlib-only, deterministic (fixed timestamps / seeds — same run → same verdict), fail-CLOSED
  (an uncaught flaw, OR a scenario that raises, is a FAIL, never a silent pass), LLM-FORBIDDEN.
* atomic: the status writer is tmp + os.replace.

PUBLIC SURFACE
--------------
    RedTeamScenario  — the pluggable ABC (subclass + register).
    Finding          — {attempted, caught, evidence} the verdict of one attack.
    REGISTRY         — the seeded scenarios (one per surface, the proven attacks).
    runner.run_all() — execute every (or a chosen) scenario against fresh sandboxes → a JSON verdict.
    rotation.run()   — deterministic per-UTC-day surface rotation → data/redteam_status.json (atomic).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.redteam.base import Finding, RedTeamScenario, Surface
from spa_core.redteam.registry import REGISTRY, scenarios_for_surface

__all__ = ["Finding", "RedTeamScenario", "Surface", "REGISTRY", "scenarios_for_surface"]
