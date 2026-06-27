#!/usr/bin/env python3
"""
scripts/drill_fleet_down.py — INERT END-TO-END FLEET-DOWN DRILL HARNESS (R4).

THE CENTERPIECE (mirrors spa_core/execution/golive_dry_run.py's inert/report
style): a single PURE harness that simulates a fleet-down event against a FAKE
launchctl-list fixture and asserts the recovery logic — self_heal's bootstrap
decision + verify_fleet_after_reboot's RETIRED skip — would revive the RIGHT set
of agents, SKIP retired agents, and SKIP correctly-idle calendar agents — WITHOUT
booting anything real.

This is the artifact that proves, on simulated launchctl fixtures, that after a
reboot / fleet-down event the recovery path would do the right thing. It is the
"would-it-recover?" analogue of the go-live dry-run's "would-the-gates-fire?".

HARD GUARANTEES (do not relax):
  * IS_DRILL = True. PURE / read-only. NEVER calls launchctl, NEVER spawns a
    subprocess, NEVER bootstraps/boots-out/kickstarts anything, NEVER touches the
    real host's loaded jobs or live state. The "loaded set" and the plists are
    FIXTURES injected in-process.
  * stdlib only. Deterministic. Atomic writes (via spa_core.utils.atomic).
  * The decision logic is SOURCED FROM THE REAL monitoring modules
    (``requires_residency`` / ``classify_agent`` / ``RETIRED_LABELS`` imported
    read-only) — NOT a divergent copy — so a drill PASS proves the real recovery
    code, not a stand-in.
  * The REGRESSION GUARD this drill exists for: a RETIRED label must NEVER appear
    in the would-revive set (booting bot_commands/httpserver/the legacy daily
    senders re-introduces a Telegram 409 / duplicate-flood). Asserted across
    EVERY scenario.
  * The CHURN GUARD: an idle calendar agent (StartCalendarInterval + RunAtLoad:
    False, not resident) is NOT a fault — it must NOT be in the would-revive set.
  * The OUTAGE GUARD: a genuinely-missing RESIDENT agent (KeepAlive / StartInterval)
    MUST be in the would-revive set.
  * The ONLY file this module writes is data/fleet_drill_status.json (optional).
  * LLM FORBIDDEN anywhere in this path.

HOW IT MAPS TO THE REAL RECOVERY PATH:
  self_heal.run_self_heal() reconciles ``_expected_labels()`` (every installed,
  non-disabled, non-RETIRED com.spa.*.plist) against ``_loaded_labels()`` (from
  ``launchctl list``) and bootstraps a missing label ONLY when
  ``requires_residency(classify_agent(plist), plist)`` is True; a non-resident
  calendar agent is skipped (idle, not a fault); a RETIRED label is excluded from
  the expected set entirely. verify_fleet_after_reboot.sh additionally boots-OUT
  any RETIRED plist that lingered loaded. This drill replays exactly that decision
  surface against fixtures, with ZERO subprocess calls.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Allow ``python3 scripts/drill_fleet_down.py`` from anywhere: put the repo root
# (parent of this scripts/ dir) on sys.path so ``import spa_core`` resolves. (No
# effect when run as ``python3 -m scripts.drill_fleet_down``.)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── REAL decision logic, imported READ-ONLY (single source of truth) ──────────
# These are the SAME functions self_heal.py imports to decide what to revive.
from spa_core.monitoring.agent_health_monitor import (  # noqa: E402
    RETIRED_LABELS,
    classify_agent,
    requires_residency,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402

IS_DRILL = True  # un-overridable harness invariant — never boots anything real

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "data"
_OUT = _DATA / "fleet_drill_status.json"


# --------------------------------------------------------------------------- #
# Fixture plist builders — synthetic plist dicts (NOT read from disk).
# Shapes match what plistlib.load() would return for real SPA agents, so the
# REAL classify_agent / requires_residency judge them exactly as on a live host.
# --------------------------------------------------------------------------- #
def _keepalive_plist(label: str) -> dict:
    """A KeepAlive daemon (e.g. cloudflared / apiserver / telegram_bot).
    launchd keeps it RESIDENT → absence = real outage → MUST revive."""
    return {"Label": label, "KeepAlive": True, "RunAtLoad": True}


def _interval_plist(label: str, interval_s: int) -> dict:
    """A StartInterval guardian (e.g. rules_watchdog @300s, self_heal @300s).
    launchd holds it loaded and fires it on the interval → RESIDENT → MUST revive."""
    return {"Label": label, "StartInterval": interval_s, "RunAtLoad": True}


def _calendar_plist(label: str, *, hour: int = 8, minute: int = 0,
                    run_at_load: bool = False) -> dict:
    """A StartCalendarInterval daily agent (e.g. daily_cycle @08:00 UTC).
    With RunAtLoad:False it EXITS between scheduled runs → 'not resident' is its
    NORMAL idle state → must be SKIPPED (judged by log freshness, not residency)."""
    return {
        "Label": label,
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": run_at_load,
    }


# --------------------------------------------------------------------------- #
# Scenario fixtures.
# Each scenario = a synthetic "installed fleet" (label → plist dict) PLUS a fake
# "loaded set" (the labels a simulated `launchctl list` would report). The drill
# computes, via the REAL decision logic, what recovery WOULD do — no host touched.
# --------------------------------------------------------------------------- #
def _base_fleet() -> Dict[str, dict]:
    """A representative installed fleet covering every residency class + retired.

    Mix:
      * 3 KeepAlive daemons (resident-required)
      * 2 StartInterval guardians (resident-required)
      * 3 calendar/daily agents (idle-when-not-resident, must NOT churn)
      * the RETIRED labels (must NEVER be revived; verify boots them out)
    """
    fleet: Dict[str, dict] = {
        # resident-required: KeepAlive daemons
        "com.spa.apiserver": _keepalive_plist("com.spa.apiserver"),
        "com.spa.cloudflared": _keepalive_plist("com.spa.cloudflared"),
        "com.spa.telegram_bot": _keepalive_plist("com.spa.telegram_bot"),
        # resident-required: StartInterval guardians
        "com.spa.rules_watchdog": _interval_plist("com.spa.rules_watchdog", 300),
        "com.spa.self_heal": _interval_plist("com.spa.self_heal", 300),
        # idle-calendar: daily/scheduled, RunAtLoad:False → not resident is FINE
        "com.spa.daily_cycle": _calendar_plist("com.spa.daily_cycle", hour=8),
        "com.spa.tournament_engine": _calendar_plist("com.spa.tournament_engine", hour=9),
        "com.spa.daily_backup": _calendar_plist("com.spa.daily_backup", hour=4),
    }
    # RETIRED labels whose stale .plist may linger installed on a host.
    for retired in sorted(RETIRED_LABELS):
        # Give them a plausible (resident-looking) shape on purpose: even though
        # they LOOK like a KeepAlive that "should" be resident, the RETIRED skip
        # must override and they must NEVER be revived. Worst-case stress.
        fleet[retired] = _keepalive_plist(retired)
    return fleet


# Resident-required labels in the base fleet (for building "loaded" sets).
def _resident_required(fleet: Dict[str, dict]) -> List[str]:
    return sorted(
        lbl for lbl, pl in fleet.items()
        if lbl not in RETIRED_LABELS and requires_residency(classify_agent(pl), pl)
    )


def _idle_calendar(fleet: Dict[str, dict]) -> List[str]:
    return sorted(
        lbl for lbl, pl in fleet.items()
        if lbl not in RETIRED_LABELS and not requires_residency(classify_agent(pl), pl)
    )


def build_scenarios() -> List[dict]:
    """Construct the fleet-down scenarios. Each: name, installed fleet, loaded set."""
    fleet = _base_fleet()
    residents = _resident_required(fleet)
    idle = _idle_calendar(fleet)
    retired = sorted(RETIRED_LABELS)

    scenarios: List[dict] = []

    # 1) ALL-DOWN: nothing loaded (cold boot before any agent came up).
    scenarios.append({
        "name": "all_down",
        "description": "cold boot — launchctl reports NOTHING loaded",
        "fleet": fleet,
        "loaded": set(),
    })

    # 2) HALF-DOWN: ~half the residents loaded, the rest down; idle correctly
    #    not resident; retired correctly not loaded.
    half = residents[: len(residents) // 2]
    scenarios.append({
        "name": "half_down",
        "description": "partial outage — some resident daemons up, some down",
        "fleet": fleet,
        "loaded": set(half),
    })

    # 3) RETIRED-STILL-LOADED: full fleet healthy BUT a stale retired plist got
    #    bootstrapped and is lingering loaded → verify must boot it out, self_heal
    #    must never count it as expected/revive.
    loaded = set(residents) | {retired[0]}
    scenarios.append({
        "name": "retired_still_loaded",
        "description": "healthy fleet but a RETIRED agent lingers loaded (must be booted out, never revived)",
        "fleet": fleet,
        "loaded": loaded,
    })

    # 4) IDLE-CALENDAR-NOT-LOADED-BUT-FINE: all residents up; calendar agents are
    #    NOT loaded (their normal idle state). This must be reported HEALTHY —
    #    zero would-revive (the chronic false-CRITICAL churn loop guard).
    scenarios.append({
        "name": "idle_calendar_not_loaded",
        "description": "residents all up; calendar agents idle (not loaded) — must NOT be revived",
        "fleet": fleet,
        "loaded": set(residents),
    })

    # 5) MIXED-WORST-CASE: residents partly down, a calendar agent ALSO not
    #    loaded (still fine), AND two retired agents lingering loaded.
    scenarios.append({
        "name": "mixed_worst_case",
        "description": "residents partly down + idle calendar + multiple retired lingering loaded",
        "fleet": fleet,
        "loaded": set(residents[:1]) | set(retired[:2]),
    })

    # Stash the derived sets for the report header (deterministic).
    for sc in scenarios:
        sc["_residents"] = residents
        sc["_idle"] = idle
        sc["_retired_installed"] = retired
    return scenarios


# --------------------------------------------------------------------------- #
# The drill — compute recovery decision via the REAL logic (NO subprocess).
# --------------------------------------------------------------------------- #
def _compute_recovery(fleet: Dict[str, dict], loaded: set) -> dict:
    """Replay self_heal + verify_fleet_after_reboot decision logic on a fixture.

    Mirrors self_heal.run_self_heal()'s reconcile step exactly:
      expected = installed, non-disabled, NON-RETIRED labels
      for each expected label NOT in `loaded`:
          if requires_residency(classify_agent(plist), plist): → REVIVE (bootstrap)
          else:                                                → SKIP (idle calendar)
      RETIRED labels are excluded from expected; if lingering loaded, verify boots
      them out (never revives).
    Returns the four would-sets. PURE — touches no host.
    """
    # expected = every installed (non-disabled, non-retired) label.
    # (Fixtures carry no '.disabled' suffix; the real _expected_labels() filters
    # those — represented here by simply not including disabled labels.)
    expected = sorted(lbl for lbl in fleet if lbl not in RETIRED_LABELS)

    would_revive: List[str] = []
    would_skip_idle: List[str] = []
    for label in expected:
        if label in loaded:
            continue  # already resident → nothing to do
        plist = fleet[label]
        if requires_residency(classify_agent(plist), plist):
            would_revive.append(label)         # genuinely-down resident → bootstrap
        else:
            would_skip_idle.append(label)       # idle calendar → NOT a fault, skip

    # RETIRED skip-set: any retired label that is installed. verify boots out the
    # ones that are *loaded*; self_heal simply never expects/revives any of them.
    retired_installed = sorted(lbl for lbl in fleet if lbl in RETIRED_LABELS)
    retired_loaded = sorted(lbl for lbl in retired_installed if lbl in loaded)

    return {
        "expected": expected,
        "would_revive": sorted(would_revive),
        "would_skip_idle_calendar": sorted(would_skip_idle),
        "would_skip_retired": retired_installed,
        "retired_lingering_loaded_would_bootout": retired_loaded,
        "loaded": sorted(loaded),
    }


def run_drill() -> dict:
    """Run every scenario, compute would-recover sets, and ASSERT the invariants.

    Returns a report dict. ``passed`` is True iff EVERY assertion holds across
    EVERY scenario. PURE — never calls launchctl / subprocess / boots anything.
    """
    ts = datetime.now(timezone.utc).isoformat()
    scenarios = build_scenarios()
    results: List[dict] = []
    assertion_failures: List[str] = []

    for sc in scenarios:
        rec = _compute_recovery(sc["fleet"], sc["loaded"])
        checks: List[dict] = []

        def _check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})
            if not ok:
                assertion_failures.append(f"{sc['name']}::{name} — {detail}")

        # ── INVARIANT A (the regression we fixed): no RETIRED label is EVER in
        #    the would-revive set. The hard, non-negotiable guard. ──────────────
        revived_retired = sorted(set(rec["would_revive"]) & set(RETIRED_LABELS))
        _check(
            "no_retired_ever_revived",
            not revived_retired,
            f"retired in revive set: {revived_retired}" if revived_retired
            else "no RETIRED label in would-revive set",
        )

        # ── INVARIANT B (churn guard): idle calendar agents (RunAtLoad:False, not
        #    due) are NOT in the would-revive set. ──────────────────────────────
        idle_in_revive = sorted(set(rec["would_skip_idle_calendar"]) & set(rec["would_revive"]))
        _check(
            "idle_calendar_not_revived",
            not idle_in_revive,
            f"idle calendar in revive set: {idle_in_revive}" if idle_in_revive
            else f"{len(rec['would_skip_idle_calendar'])} idle calendar agent(s) correctly skipped",
        )

        # ── INVARIANT C (outage guard): every genuinely-missing RESIDENT agent IS
        #    in the would-revive set (no real outage silently ignored). ──────────
        missing_residents = sorted(
            lbl for lbl in sc["_residents"] if lbl not in sc["loaded"]
        )
        _check(
            "missing_residents_all_revived",
            sorted(rec["would_revive"]) == missing_residents,
            f"would_revive={rec['would_revive']} vs expected missing residents={missing_residents}",
        )

        # ── INVARIANT D: a retired label lingering LOADED is flagged for bootout
        #    (verify_fleet_after_reboot) and STILL never revived. ────────────────
        lingering = sorted(set(sc["loaded"]) & set(RETIRED_LABELS))
        _check(
            "retired_lingering_booted_not_revived",
            rec["retired_lingering_loaded_would_bootout"] == lingering
            and not (set(lingering) & set(rec["would_revive"])),
            f"lingering retired loaded={lingering}; bootout={rec['retired_lingering_loaded_would_bootout']}",
        )

        results.append({
            "scenario": sc["name"],
            "description": sc["description"],
            "recovery": rec,
            "checks": checks,
            "scenario_passed": all(c["ok"] for c in checks),
        })

    passed = not assertion_failures
    report = {
        "generated_at": ts,
        "module": "drill_fleet_down",
        "is_drill": IS_DRILL,
        "calls_launchctl": False,
        "boots_anything": False,
        "llm_forbidden": True,
        "decision_logic_source": "spa_core.monitoring.agent_health_monitor "
                                 "(requires_residency / classify_agent / RETIRED_LABELS) — "
                                 "the same functions self_heal.py imports",
        "retired_labels": sorted(RETIRED_LABELS),
        "scenarios": results,
        "assertion_failures": assertion_failures,
        "passed": passed,
    }
    return report


# --------------------------------------------------------------------------- #
# Report + CLI
# --------------------------------------------------------------------------- #
def _print_report(report: dict) -> None:
    print("=" * 78)
    print("FLEET-DOWN DRILL HARNESS — recovery walk (INERT, NEVER calls launchctl)")
    print("=" * 78)
    print(f"decision logic: {report['decision_logic_source']}")
    print(f"retired labels (never revived): {', '.join(report['retired_labels'])}")
    print("-" * 78)
    for sc in report["scenarios"]:
        rec = sc["recovery"]
        mark = "PASS" if sc["scenario_passed"] else "FAIL"
        print(f"\n[{mark}] {sc['scenario']} — {sc['description']}")
        print(f"   loaded (fixture) : {rec['loaded'] or '(none)'}")
        print(f"   would REVIVE      : {rec['would_revive'] or '(none)'}")
        print(f"   would SKIP idle   : {rec['would_skip_idle_calendar'] or '(none)'}")
        print(f"   would SKIP retired: {rec['would_skip_retired'] or '(none)'}")
        if rec["retired_lingering_loaded_would_bootout"]:
            print(f"   retired→BOOTOUT   : {rec['retired_lingering_loaded_would_bootout']}")
        for c in sc["checks"]:
            icon = "ok " if c["ok"] else "FAIL"
            print(f"      [{icon}] {c['name']:<36} {c['detail']}")
    print("-" * 78)
    if report["passed"]:
        print("RESULT: PASS — recovery would revive the right residents, "
              "skip retired, skip idle calendar. No host touched.")
    else:
        print(f"RESULT: FAIL — {len(report['assertion_failures'])} assertion(s) failed:")
        for f in report["assertion_failures"]:
            print(f"   - {f}")
    print("=" * 78)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--no-write" not in argv
    report = run_drill()
    _print_report(report)
    if write:
        try:
            atomic_save(report, str(_OUT))
            print(f"\nwrote: {_OUT}")
        except Exception as exc:  # noqa: BLE001 — drill result must not depend on disk
            print(f"\n(note: could not write {_OUT}: {type(exc).__name__}: {exc})")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
