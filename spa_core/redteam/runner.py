"""
spa_core/redteam/runner.py — execute scenarios against FRESH sandboxes → a JSON verdict.

The runner is the single entry point that turns the scenario registry into a fail-CLOSED verdict:

  * each scenario gets its OWN fresh tmp sandbox dir (never live data/),
  * ``attack`` is wrapped so a RAISE becomes a fail-CLOSED Finding (an exception is a FAIL, never a
    silently-passed scenario),
  * the live data/ surface files are hash-snapshotted BEFORE and AFTER the whole run and the run
    FAILS CLOSED if a single byte changed (the read-only-against-live guardrail, enforced — not just
    promised),
  * the verdict is {ok, n, n_caught, n_failed, findings[...], live_data_untouched, ts}. ok is True
    iff EVERY scenario fired, controlled, and CAUGHT its forgery AND the live data was untouched.

A scenario that finds an UNCAUGHT flaw → ok=False (the desk has a real hole).

stdlib-only · deterministic · fail-CLOSED · LLM-FORBIDDEN.

CLI:
    python3 -m spa_core.redteam.runner            # run all, human summary, exit 0/1
    python3 -m spa_core.redteam.runner --json     # machine verdict
    python3 -m spa_core.redteam.runner --surface proof   # only one surface
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Iterator, Optional

from spa_core.redteam.base import Finding, RedTeamScenario
from spa_core.redteam.registry import REGISTRY, scenarios_for_surface

_ROOT = Path(__file__).resolve().parents[2]
_LIVE_DATA = _ROOT / "data"

# The live surface files the guardrail watches — a scenario must NEVER mutate any of these.
_WATCHED_LIVE_FILES = (
    "data/rates_desk/decision_log.jsonl",
    "data/rates_desk/exit_nav.json",
    "data/rates_desk/anchors.jsonl",
    "data/rates_desk/equity_track.jsonl",
    "data/tournament/decision_log.jsonl",
    "data/rwa_backstop/nav_proof.jsonl",
    "data/equity_curve_daily.json",
    "data/golive_status.json",
)


def _snapshot_live(root: Path = _ROOT) -> Dict[str, str]:
    """SHA-256 every watched live file (MISSING sentinel for absent). The read-only-against-live
    guard compares this before/after a run."""
    out: Dict[str, str] = {}
    for rel in _WATCHED_LIVE_FILES:
        p = root / rel
        if p.exists():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[rel] = "MISSING"
    return out


@contextmanager
def _quiet_expected_rejections() -> Iterator[None]:
    """Silence the spa loggers DURING the attacks. Every scenario deliberately triggers a REJECTED /
    non-finite verdict from a real defense — those log.error lines are the EXPECTED success signal of
    the attack, not failures, and must not pollute the one-screen red-team summary. Restored after."""
    target = logging.getLogger("spa")
    prev_level = target.level
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(prev_disable)
        target.setLevel(prev_level)


def run_scenario(scenario: RedTeamScenario) -> Finding:
    """Run ONE scenario in a fresh sandbox; a raise becomes a fail-CLOSED Finding (never a crash)."""
    with tempfile.TemporaryDirectory(prefix="spa_redteam_") as td:
        sandbox = Path(td)
        try:
            finding = scenario.attack(sandbox)
        except Exception as exc:  # noqa: BLE001 — a scenario raise is a FAIL, fail-CLOSED
            return Finding(scenario.name, scenario.surface, attempted=False, caught=False,
                           control_ok=False, evidence=f"scenario raised: {exc!r}", error=repr(exc))
        # Defensive: a scenario must return a Finding for its own name/surface.
        if not isinstance(finding, Finding):
            return Finding(scenario.name, scenario.surface, attempted=False, caught=False,
                           control_ok=False, evidence="scenario did not return a Finding",
                           error="bad_return")
        return finding


def run_all(scenarios: Optional[List[RedTeamScenario]] = None,
            *, check_live_untouched: bool = True) -> dict:
    """Run every scenario (or the supplied subset) against fresh sandboxes and return the verdict.

    fail-CLOSED: ok is True iff every scenario ok AND (when check_live_untouched) the live data/
    surface files are byte-identical before and after."""
    scens = list(scenarios if scenarios is not None else REGISTRY)
    before = _snapshot_live() if check_live_untouched else {}

    with _quiet_expected_rejections():
        findings: List[Finding] = [run_scenario(s) for s in scens]

    after = _snapshot_live() if check_live_untouched else {}
    mutated = [rel for rel in before if before.get(rel) != after.get(rel)]
    live_untouched = (not mutated)

    n_caught = sum(1 for f in findings if f.ok)
    n_failed = sum(1 for f in findings if not f.ok)
    ok = (n_failed == 0) and (live_untouched or not check_live_untouched) and bool(findings)

    return {
        "ok": ok,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "n": len(findings),
        "n_caught": n_caught,
        "n_failed": n_failed,
        "live_data_untouched": live_untouched,
        "live_data_mutated_files": mutated,
        "findings": [f.as_dict() for f in findings],
    }


# ── human summary ──
def _print_human(verdict: dict) -> None:
    print("=" * 84)
    print("SPA RED-TEAM HARNESS — every surface red-teams itself (fail-CLOSED)")
    print("=" * 84)
    print(f"ts: {verdict['ts']}")
    print(f"scenarios: {verdict['n']}  caught: {verdict['n_caught']}  failed: {verdict['n_failed']}")
    print(f"live data/ untouched: {verdict['live_data_untouched']}"
          + ("" if verdict["live_data_untouched"]
             else f"  ⚠ MUTATED: {verdict['live_data_mutated_files']}"))
    print("-" * 84)
    for f in verdict["findings"]:
        mark = "✓" if f["ok"] else "✗"
        print(f"  {mark} [{f['surface']:12s}] {f['scenario']}")
        if not f["ok"]:
            if f["error"]:
                print(f"      ERROR: {f['error']}")
            elif not f["control_ok"]:
                print(f"      CONTROL FAILED (false alarm): {f['evidence']}")
            else:
                print(f"      UNCAUGHT FLAW — real hole: {f['evidence']}")
        else:
            print(f"      {f['evidence']}")
    print("-" * 84)
    print(f"VERDICT: {'PASS — every forgery caught, live data untouched' if verdict['ok'] else 'FAIL'}")
    print("=" * 84)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run SPA's standing red-team scenarios (fail-CLOSED).")
    ap.add_argument("--surface", default=None, help="only run scenarios for this surface")
    ap.add_argument("--json", action="store_true", help="emit the machine verdict as JSON")
    ap.add_argument("--no-live-guard", action="store_true",
                    help="skip the live-data untouched snapshot (tests use a sandbox-only run)")
    args = ap.parse_args(argv)

    scens = scenarios_for_surface(args.surface) if args.surface else None
    if args.surface and not scens:
        print(f"no scenarios registered for surface {args.surface!r}", file=sys.stderr)
        return 1
    verdict = run_all(scens, check_live_untouched=not args.no_live_guard)
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        _print_human(verdict)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
