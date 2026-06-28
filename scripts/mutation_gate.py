#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/mutation_gate.py — a small, fast, deterministic MUTATION-TESTING gate
over SPA's CRITICAL money-path modules (Cutover-Bulletproof WS-6.3).

THE META-CHECK
==============
Property / fuzz / chaos suites prove the code does the right thing on the inputs
they try. But how do we know those tests would CATCH a real regression? A
mutation tester answers that empirically: it deliberately BREAKS the code (flips
an operator, nudges a constant), re-runs the tests, and checks a test FAILS. A
mutant the tests still PASS through is a SURVIVOR — a hole where a real bug of
that exact shape would slip past CI undetected.

This gate runs a CURATED, hand-picked set of high-value mutations against the four
most safety-critical modules and asserts the surviving-mutant count stays under a
documented threshold (0 — every curated mutant must be killed). The mutations are
chosen on the EXACT fail-closed boundaries that matter (the kill-switch threshold
comparison, the RiskPolicy cap/TVL/APY bounds, the reconcile NAV/dust tolerances,
the gate-chain ordering) — so a survivor is a directly meaningful coverage gap.

WHY CURATED (not blind AST-wide)
--------------------------------
A blind "mutate every operator" run produces thousands of equivalent / dead-code
mutants and takes minutes — too slow + noisy for a CI gate. We instead pin the
handful of mutations on the load-bearing safety boundaries, each with the FAST
subset of tests that should kill it. Deterministic, < ~60s, stdlib + pytest only.

CONTRACT
--------
  * INERT to source: each mutation is applied to a COPY of the file's text, the
    file is rewritten, the test subset is run, then the ORIGINAL text is restored
    in a finally (even on crash / Ctrl-C). The repo is byte-identical afterwards.
  * NEVER touches live data/ (the targeted tests are all hermetic / sandboxed).
  * Deterministic: same code → same survivor set. Exit 0 iff survivors ≤ threshold.

CLI::
    python3 scripts/mutation_gate.py            # run the gate, print the scorecard
    python3 scripts/mutation_gate.py --json     # machine-readable verdict
    python3 scripts/mutation_gate.py --threshold 0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = sys.executable


@dataclass
class Mutation:
    """One curated source mutation on a critical module.

    file:    path relative to repo root.
    old/new: an EXACT, UNIQUE substring swap (must appear exactly once in the
             file so the mutation is unambiguous — verified before applying).
    tests:   the fast test files that SHOULD catch this mutant.
    why:     the safety boundary this mutation attacks (for the scorecard).
    """
    file: str
    old: str
    new: str
    tests: list[str]
    why: str
    name: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# THE CURATED MUTANTS — each attacks a load-bearing fail-closed boundary.
# ──────────────────────────────────────────────────────────────────────────────
_RISK_TESTS = [
    "spa_core/tests/test_risk_policy.py",
    "spa_core/tests/test_risk_policy_properties.py",
    "spa_core/tests/test_risk_policy_gate.py",
]
_KILL_TESTS = [
    "spa_core/tests/test_kill_switch.py",
    "spa_core/tests/test_gate_mutations.py",
    "spa_core/tests/test_chaos_resilience.py",
    # WS-6.3 coverage fix: the TWO-TIER drawdown classifier boundaries
    # (classify_drawdown_pct / drawdown_tier) are pinned HERE — without these
    # two files the classifier-comparison mutants (kill_drawdown_comparison_flip
    # / kill_soft_threshold_comparison_flip) SURVIVED, because check_drawdown_
    # trigger has an independent comparison that masks the classifier on the
    # happy path. These files exercise the classifier directly at the 5%/10%
    # boundaries so a flip there is caught.
    "spa_core/tests/test_cycle_derisk_e2e.py",
    "spa_core/tests/test_pre_execution_safety.py",
]
_RECON_TESTS = [
    "spa_core/tests/test_execution_reconciliation.py",
    "spa_core/tests/test_reconcile_hardening.py",
    "spa_core/tests/test_money_path_failure_modes.py",
]
_GATE_TESTS = ["spa_core/tests/test_gate_chain_audit.py"]


MUTATIONS: list[Mutation] = [
    # ── RiskPolicy gate (spa_core/risk/policy.py) ────────────────────────────
    Mutation(
        name="risk_tvl_floor_comparison_flip",
        file="spa_core/risk/policy.py",
        old="if tvl_usd < self.config.min_tvl_usd:",
        new="if tvl_usd < self.config.min_tvl_usd and False:",
        tests=_RISK_TESTS,
        why="TVL-floor check disabled → a sub-$5M pool would pass",
    ),
    Mutation(
        name="risk_apy_max_bound_flip",
        file="spa_core/risk/policy.py",
        old="if current_apy > self.config.max_apy_for_new_position:",
        new="if current_apy > self.config.max_apy_for_new_position and False:",
        tests=_RISK_TESTS,
        why="APY upper-bound check disabled → a >30% APY would pass",
    ),
    Mutation(
        name="risk_concentration_cap_flip",
        file="spa_core/risk/policy.py",
        old="if new_conc > max_conc:",
        new="if new_conc > max_conc and False:",
        tests=_RISK_TESTS,
        why="per-protocol concentration cap disabled → over-cap would pass",
    ),
    Mutation(
        name="risk_drawdown_kill_threshold_inflate",
        file="spa_core/risk/policy.py",
        old="max_drawdown_stop: float = 0.05",
        new="max_drawdown_stop: float = 0.95",
        tests=_RISK_TESTS,
        why="kill-switch drawdown threshold inflated 5%→95% → never fires",
    ),
    Mutation(
        name="risk_finiteness_guard_removed",
        file="spa_core/risk/policy.py",
        old="if finite_violations:",
        new="if finite_violations and False:",
        tests=_RISK_TESTS,
        why="non-finite-input fail-closed guard removed → NaN inputs bypass",
    ),

    # ── Kill switch (spa_core/governance/kill_switch.py) ─────────────────────
    Mutation(
        name="kill_hard_threshold_inflate",
        file="spa_core/governance/kill_switch.py",
        old="DRAWDOWN_THRESHOLD_PCT = 10.0",
        new="DRAWDOWN_THRESHOLD_PCT = 99.0",
        tests=_KILL_TESTS,
        why="hard-kill drawdown threshold inflated 10%→99% → never fires",
    ),
    Mutation(
        name="kill_drawdown_comparison_flip",
        file="spa_core/governance/kill_switch.py",
        old="if dd >= DRAWDOWN_THRESHOLD_PCT:",
        new="if dd >= DRAWDOWN_THRESHOLD_PCT and False:",
        tests=_KILL_TESTS,
        why="hard-kill tier classifier disabled → a 50% drawdown is TIER_NONE",
    ),
    Mutation(
        name="kill_soft_threshold_comparison_flip",
        file="spa_core/governance/kill_switch.py",
        old="if dd >= SOFT_DERISK_THRESHOLD_PCT:",
        new="if dd >= SOFT_DERISK_THRESHOLD_PCT and False:",
        tests=_KILL_TESTS,
        why="soft de-risk tier disabled → a 7% drawdown classifies as NONE",
    ),

    # ── Reconciliation (spa_core/execution/reconciliation.py) ────────────────
    Mutation(
        name="recon_matches_target_force_true",
        file="spa_core/execution/reconciliation.py",
        old="matches_target = bool(finite) and (max_delta < DUST_TOLERANCE_USD)",
        new="matches_target = True",
        tests=_RECON_TESTS,
        why="intent-vs-outcome check forced True → any mismatch reconciles",
    ),
    Mutation(
        name="recon_nav_conserved_force_true",
        file="spa_core/execution/reconciliation.py",
        old="nav_conserved = bool(finite) and (abs(nav_after - expected_nav_after) <= NAV_TOLERANCE_USD)",
        new="nav_conserved = True",
        tests=_RECON_TESTS,
        why="NAV-conservation check forced True → capital creation reconciles",
    ),
    Mutation(
        name="recon_finite_guard_force_true",
        file="spa_core/execution/reconciliation.py",
        old="finite = _all_positions_finite(target, resulting)",
        new="finite = True",
        tests=_RECON_TESTS,
        why="non-finite valuation guard bypassed → NaN positions pass",
    ),
    Mutation(
        name="recon_dust_tolerance_inflate",
        file="spa_core/execution/reconciliation.py",
        old="POSITION_TOLERANCE_USD = 1.0",
        new="POSITION_TOLERANCE_USD = 1.0e12",
        tests=_RECON_TESTS,
        why="dust tolerance inflated to $1T → huge position mismatch passes",
    ),

    # ── Gate-chain audit (spa_core/execution/gate_chain_audit.py) ────────────
    Mutation(
        name="gatechain_kill_not_first",
        file="spa_core/execution/gate_chain_audit.py",
        old='KILL_SWITCH_FIRST = "Kill Switch"',
        new='KILL_SWITCH_FIRST = "Rate Limit"',
        tests=_GATE_TESTS,
        why="kill-switch-first invariant broken → kill not consulted first",
    ),
    Mutation(
        name="gatechain_simulation_nonblocking",
        file="spa_core/execution/gate_chain_audit.py",
        old='("Transaction Simulation", True),',
        new='("Transaction Simulation", False),',
        tests=_GATE_TESTS,
        why="simulation gate demoted to non-blocking → a failed sim won't block",
    ),
]


@dataclass
class MutantResult:
    name: str
    file: str
    why: str
    killed: bool
    killer_tests: list[str] = field(default_factory=list)
    note: str = ""


def _run_tests(test_files: list[str]) -> tuple[bool, str]:
    """Run pytest over the given files; return (all_passed, short_tail).

    all_passed True iff the subset is GREEN. We deselect the randomizer for
    determinism and stop at the first failure (``-x``) so a killed mutant returns
    fast. A pytest internal error (exit >= 2 other than 1) is treated as NOT
    passing (the mutant broke import/collection — that still counts as caught).
    """
    cmd = [
        _PYTHON, "-m", "pytest", *test_files,
        "-p", "no:randomly", "-x", "-q", "--no-header",
        "-o", "addopts=",  # ignore repo addopts (coverage etc.) for speed
    ]
    proc = subprocess.run(
        cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=300
    )
    tail = (proc.stdout or "")[-400:] + (proc.stderr or "")[-200:]
    return proc.returncode == 0, tail


def _apply_mutant(m: Mutation) -> MutantResult:
    """Apply ONE mutant, run its tests, restore the source. killed iff tests fail.

    A mutant is KILLED when the targeted test subset goes RED (returncode != 0)
    after the mutation. It SURVIVES when the tests still pass — a coverage hole.
    The original file text is ALWAYS restored in the finally.
    """
    path = _REPO_ROOT / m.file
    original = path.read_text(encoding="utf-8")

    # The swap target must appear EXACTLY ONCE (unambiguous mutation).
    count = original.count(m.old)
    if count != 1:
        return MutantResult(
            m.name, m.file, m.why, killed=False,
            note=(f"SKIP/ERROR: mutation anchor found {count}x (expected 1) — "
                  f"the source moved; update mutation_gate.py"),
        )

    mutated = original.replace(m.old, m.new, 1)
    try:
        path.write_text(mutated, encoding="utf-8")
        passed, tail = _run_tests(m.tests)
        killed = not passed  # tests RED on the mutant ⇒ caught
        return MutantResult(
            m.name, m.file, m.why, killed=killed,
            killer_tests=m.tests if killed else [],
            note="" if killed else f"SURVIVED — tests stayed green:\n{tail}",
        )
    finally:
        # ALWAYS restore — the repo must be byte-identical afterwards.
        path.write_text(original, encoding="utf-8")


def run_gate(threshold: int = 0) -> dict:
    """Run every curated mutant and assemble the scorecard.

    A baseline is NOT re-run per-mutant for speed; instead each anchor is verified
    unique (a moved anchor is reported as an ERROR survivor so the gate fails
    loudly rather than silently skipping a critical mutation).
    """
    t0 = time.time()
    results: list[MutantResult] = []
    for m in MUTATIONS:
        results.append(_apply_mutant(m))

    survivors = [r for r in results if not r.killed]
    errors = [r for r in results if r.note.startswith("SKIP/ERROR")]
    return {
        "module": "mutation_gate",
        "version": "v1.0",
        "threshold": threshold,
        "n_mutants": len(results),
        "n_killed": sum(1 for r in results if r.killed),
        "n_survivors": len(survivors),
        "n_anchor_errors": len(errors),
        "survivors": [r.name for r in survivors],
        "pass": len(survivors) <= threshold,
        "elapsed_s": round(time.time() - t0, 1),
        "results": [
            {"name": r.name, "file": r.file, "why": r.why, "killed": r.killed,
             "note": r.note}
            for r in results
        ],
    }


def _print(report: dict) -> None:
    print("=" * 74)
    print("SPA MUTATION-TESTING GATE (WS-6.3) — do our tests actually catch bugs?")
    print("=" * 74)
    for r in report["results"]:
        mark = "KILLED " if r["killed"] else "SURVIVE"
        print(f" [{mark}] {r['name']:<38} {r['file'].split('/')[-1]}")
        print(f"           {r['why']}")
        if not r["killed"] and r["note"]:
            first = r["note"].splitlines()[0]
            print(f"           ↳ {first}")
    print("-" * 74)
    print(f" mutants: {report['n_mutants']}   killed: {report['n_killed']}   "
          f"survivors: {report['n_survivors']}   (threshold ≤ {report['threshold']})")
    if report["survivors"]:
        print(f" SURVIVING MUTANTS (coverage holes): {', '.join(report['survivors'])}")
    print(f" elapsed: {report['elapsed_s']}s")
    print(f" GATE: {'PASS' if report['pass'] else 'FAIL'}")
    print("=" * 74)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="SPA mutation-testing gate (WS-6.3) — assert the test suite "
                    "catches deliberate bugs on the critical money-path modules.")
    p.add_argument("--threshold", type=int, default=0,
                   help="max surviving mutants allowed (default 0)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    report = run_gate(threshold=args.threshold)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
