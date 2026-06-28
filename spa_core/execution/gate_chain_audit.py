#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core/execution/gate_chain_audit.py — PRE-EXECUTION GATE-CHAIN AUDIT (WS-3.1).

Cutover-Bulletproof WS-3.1: a machine-checked, deterministic audit of the ORDERED
pre-execution defense chain in ``PreExecutionSafety.run_all`` — the chain a money
transaction must traverse BEFORE it could ever be signed. This module BUILDS
READINESS; it does NOT flip ``is_live`` and never moves capital.

THE DOCUMENTED ORDERED DEFENSE CHAIN (fail-CLOSED, total, kill-switch FIRST)
---------------------------------------------------------------------------
``PreExecutionSafety.run_all`` appends checks in THIS canonical order. The audit
pins the order and proves the fail-closed-on-ANY-gate property:

    1. Kill Switch            (governance-converged: persisted manual kill +
                               two-tier drawdown ladder — consulted FIRST)
    2. Rate Limit             (≤ N tx / rolling hour)
    3. RiskPolicy             (deterministic v1.0: TVL floor / APY bounds /
                               concentration caps / cash buffer)
    4. Transaction Simulation (must succeed; absent → fail-closed block)
    5. Gas Reasonableness     (gas < 2% of trade)
    6. Multisig Routing       (INFORMATIONAL — routes large tx; not a block)

PROPERTIES ASSERTED (each is a deterministic, machine-checked claim)
--------------------------------------------------------------------
  * ORDERED        — the realised check sequence equals the documented order.
  * KILL-FIRST     — the governance-converged kill switch is position 1.
  * TOTAL          — every required defense is present (no input bypasses a gate);
                     the BLOCKING set is exactly the documented blocking gates.
  * FAIL-CLOSED    — if ANY blocking gate fails, the pipeline is ``blocked`` and
                     no LATER gate can un-block it (a later pass never overrides
                     an earlier hard block).

It produces a GATE-CHAIN SCORECARD (per-gate present / ordered / blocking /
fail-closed) and an aggregate verdict ``chain_bulletproof``.

HARD GUARANTEES (do not relax)
------------------------------
  * INERT. NEVER signs, NEVER moves capital, NEVER touches a wallet/bridge/chain.
    Every drive is a SANDBOX call into the pure ``PreExecutionSafety`` checks with
    deterministic inputs; the persisted kill-switch state is redirected to a
    sandbox dir via ``set_data_dir_override`` so the live ``data/`` is untouched.
  * stdlib only. Deterministic. fail-CLOSED. Atomic writes.
  * LLM FORBIDDEN anywhere in this path.

CLI::  python3 -m spa_core.execution.gate_chain_audit
"""
from __future__ import annotations

import inspect
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[2]
_REPORT_FILENAME = "gate_chain_audit.json"
REPORT_VERSION = "v1.0"

IS_INERT = True  # un-overridable invariant — this audit NEVER moves capital.


# --------------------------------------------------------------------------- #
# The canonical documented chain. The audit asserts the runtime matches THIS.
# Each entry: (check_name as emitted by SafetyCheckResult.check_name, blocking?).
# Order is significant — index 0 is consulted FIRST.
# --------------------------------------------------------------------------- #
CANONICAL_CHAIN: tuple[tuple[str, bool], ...] = (
    ("Kill Switch", True),
    ("Rate Limit", True),
    ("RiskPolicy", True),
    ("Transaction Simulation", True),
    ("Gas Reasonableness", True),
    ("Multisig Routing", False),  # informational routing — NOT a block
)

# The gate that MUST be consulted first (governance-converged kill switch).
KILL_SWITCH_FIRST = "Kill Switch"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(check: str, expected: str, actual: str, passed: bool, *, detail: str = "") -> dict:
    return {"check": check, "expected": expected, "actual": actual,
            "pass": bool(passed), "detail": detail}


# --------------------------------------------------------------------------- #
# Sandbox inputs — a clean, RiskPolicy-passing transaction so we can observe the
# FULL ordered chain (every gate present, all passing) and then drive failures.
# --------------------------------------------------------------------------- #
def _clean_portfolio() -> dict:
    """A portfolio with no drawdown → kill-switch tier NONE (clean baseline)."""
    return {
        "total_capital_usd": 100_000.0,
        "cash_usd": 60_000.0,
        "total_drawdown_pct": 0.0,
        "positions": [],
    }


def _clean_kwargs() -> dict:
    """Inputs that make EVERY blocking gate PASS on a whitelisted protocol.

    current_apy / tvl_usd are supplied so the RiskPolicy stage never reaches the
    live adapter feed (deterministic, offline). A small amount keeps it under the
    multisig threshold so routing reports auto-execute.
    """
    return {
        "protocol": "aave-v3",
        "action": "supply",
        "amount_usd": 100.0,
        "portfolio_state": _clean_portfolio(),
        "gas_cost_usd": 0.10,                  # 0.1% of $100 → gas OK
        "simulation_result": {"success": True, "mode": "local"},
        "current_apy": 4.0,                    # within 1..30% bounds
        "tvl_usd": 500_000_000.0,              # well above $5M floor
        "tier": "T1",
    }


def _run_pipeline(safety: Any, **overrides: Any):
    kw = _clean_kwargs()
    kw.update(overrides)
    return safety.run_all(**kw)


def _realised_order(pipeline: Any) -> list[str]:
    """The check_name sequence the pipeline actually produced, in append order."""
    return [c.check_name for c in pipeline.checks]


# --------------------------------------------------------------------------- #
# Static order proof — the ORDER is a property of run_all's source, not just a
# single run. We assert the documented order matches BOTH a live driven run AND
# the literal append-order in run_all's source (defence against a silent
# reordering/skip that a single happy-path run might not reveal).
# --------------------------------------------------------------------------- #
def _source_append_order(run_all_fn: Callable) -> list[str]:
    """Extract the check_name literals appended (in order) by run_all's source.

    Looks for ``check_name="..."`` and ``check_name=...`` constructions plus the
    helper-method calls (check_not_in_kill_switch / check_rate_limit /
    check_risk_policy / check_simulation_passes / check_gas_reasonable /
    check_amount_requires_multisig) so a reordering of the appends is caught
    statically — independent of runtime inputs.
    """
    src = inspect.getsource(run_all_fn)
    # Map the ordered helper calls to their emitted check_name.
    call_to_name = [
        (r"check_not_in_kill_switch", "Kill Switch"),
        (r"check_rate_limit", "Rate Limit"),
        (r"check_risk_policy", "RiskPolicy"),
        (r"check_simulation_passes|Transaction Simulation", "Transaction Simulation"),
        (r"check_gas_reasonable|Gas Reasonableness", "Gas Reasonableness"),
        (r"check_amount_requires_multisig|Multisig Routing", "Multisig Routing"),
    ]
    # Find the first source offset of each gate's marker; order by offset.
    found: list[tuple[int, str]] = []
    for pattern, name in call_to_name:
        m = re.search(pattern, src)
        if m:
            found.append((m.start(), name))
    found.sort(key=lambda t: t[0])
    # De-dup preserving order (a name may match more than one alias).
    seen: set[str] = set()
    ordered: list[str] = []
    for _off, name in found:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


# --------------------------------------------------------------------------- #
# The audit drills.
# --------------------------------------------------------------------------- #
def _audit_ordered(safety: Any) -> dict:
    """ORDERED — the realised + source append order equals the documented order."""
    documented = [name for name, _ in CANONICAL_CHAIN]
    pipeline = _run_pipeline(safety)
    realised = _realised_order(pipeline)
    source_order = _source_append_order(safety.run_all)
    ok = (realised == documented) and (source_order == documented)
    return _result(
        "ORDERED",
        f"chain order == {documented}",
        f"realised={realised} source={source_order}",
        ok,
        detail="runtime append order and static source order both match the canonical chain",
    )


def _audit_kill_first(safety: Any) -> dict:
    """KILL-FIRST — the governance-converged kill switch is position 1."""
    pipeline = _run_pipeline(safety)
    realised = _realised_order(pipeline)
    first = realised[0] if realised else None
    ok = (first == KILL_SWITCH_FIRST) and (CANONICAL_CHAIN[0][0] == KILL_SWITCH_FIRST)
    return _result(
        "KILL_FIRST",
        f"first gate == {KILL_SWITCH_FIRST!r} (governance-converged)",
        f"first={first!r}",
        ok,
        detail="kill switch consulted before any other defense",
    )


def _audit_total(safety: Any) -> dict:
    """TOTAL — every documented gate is present; the BLOCKING set matches exactly.

    No input may bypass a gate: the realised gate-set must equal the documented
    gate-set, and the set of gates that are ``blocking`` must equal the documented
    blocking set (so e.g. Simulation cannot silently become non-blocking).
    """
    documented = {name for name, _ in CANONICAL_CHAIN}
    documented_blocking = {name for name, blk in CANONICAL_CHAIN if blk}

    pipeline = _run_pipeline(safety)
    realised = {c.check_name for c in pipeline.checks}
    realised_blocking = {c.check_name for c in pipeline.checks if c.blocking}

    present_ok = realised == documented
    blocking_ok = realised_blocking == documented_blocking
    ok = present_ok and blocking_ok
    return _result(
        "TOTAL",
        f"gates=={sorted(documented)}; blocking=={sorted(documented_blocking)}",
        f"gates={sorted(realised)}; blocking={sorted(realised_blocking)}",
        ok,
        detail="no input bypasses a gate; blocking set is exactly the documented set",
    )


def _audit_fail_closed_each(safety: Any) -> dict:
    """FAIL-CLOSED — failing EACH blocking gate (one at a time) blocks the pipeline.

    For every documented blocking gate we inject the minimal failure that trips
    ONLY that gate and assert ``pipeline.blocked`` is True. This proves the chain
    is fail-CLOSED per gate (a single failed defense is sufficient to abort).
    """
    # Each entry drives ONE gate to fail via run_all overrides.
    sandbox_kill_dir = None
    drives: dict[str, dict] = {
        # Kill Switch — a HARD-kill drawdown (>=10%) blocks supply.
        "Kill Switch": {"portfolio_state": {
            "total_capital_usd": 100_000.0, "cash_usd": 60_000.0,
            "total_drawdown_pct": 0.20, "positions": []}},
        # RiskPolicy — an un-whitelisted protocol blocks pre-policy.
        "RiskPolicy": {"protocol": "not_whitelisted_xyz"},
        # Transaction Simulation — a failed sim blocks.
        "Transaction Simulation": {"simulation_result": {"success": False,
                                                          "error": "revert (drill)"}},
        # Gas Reasonableness — gas 10% of trade (> 2%) blocks.
        "Gas Reasonableness": {"gas_cost_usd": 10.0, "amount_usd": 100.0},
    }
    per_gate: dict[str, bool] = {}
    for gate, overrides in drives.items():
        pipeline = _run_pipeline(safety, **overrides)
        # The targeted gate must have failed AND the pipeline must be blocked.
        gate_failed = any(
            c.check_name == gate and c.is_hard_block for c in pipeline.checks
        )
        per_gate[gate] = bool(gate_failed and pipeline.blocked)

    # Rate Limit — fill the rolling window so the NEXT call is rate-limited.
    from spa_core.execution import safety_checks as _sc
    saved = list(_sc._tx_timestamps)
    try:
        import time as _t
        _sc._tx_timestamps[:] = [_t.time()] * _sc._RATE_LIMIT_MAX_TX
        pipeline = _run_pipeline(safety)
        per_gate["Rate Limit"] = bool(
            any(c.check_name == "Rate Limit" and c.is_hard_block for c in pipeline.checks)
            and pipeline.blocked
        )
    finally:
        _sc._tx_timestamps[:] = saved

    ok = all(per_gate.values())
    return _result(
        "FAIL_CLOSED_EACH",
        "failing ANY single blocking gate → pipeline.blocked True",
        str(per_gate),
        ok,
        detail="each blocking defense, driven to fail in isolation, aborts the pipeline",
    )


def _audit_no_later_gate_unblocks(safety: Any) -> dict:
    """FAIL-CLOSED ordering — a LATER gate passing cannot un-block an EARLIER fail.

    Drive the FIRST gate (Kill Switch) to fail while EVERY later gate is set up to
    pass cleanly. The pipeline must STILL be blocked — proving no downstream pass
    overrides an upstream hard block (the property the chain ordering must hold).
    """
    pipeline = _run_pipeline(
        safety,
        portfolio_state={"total_capital_usd": 100_000.0, "cash_usd": 60_000.0,
                         "total_drawdown_pct": 0.20, "positions": []},  # kill fires
        # all later gates pass:
        simulation_result={"success": True, "mode": "local"},
        gas_cost_usd=0.10, amount_usd=100.0,
    )
    by_name = {c.check_name: c for c in pipeline.checks}
    kill_failed = by_name.get("Kill Switch") and by_name["Kill Switch"].is_hard_block
    later_passed = (
        by_name.get("Transaction Simulation") and by_name["Transaction Simulation"].passed
        and by_name.get("Gas Reasonableness") and by_name["Gas Reasonableness"].passed
    )
    still_blocked = pipeline.blocked
    ok = bool(kill_failed and later_passed and still_blocked)
    return _result(
        "NO_LATER_GATE_UNBLOCKS",
        "earliest gate fails + all later gates pass → STILL blocked",
        f"kill_failed={bool(kill_failed)} later_passed={bool(later_passed)} "
        f"still_blocked={still_blocked}",
        ok,
        detail="a downstream pass never overrides an upstream hard block",
    )


def _audit_clean_path_proceeds(safety: Any) -> dict:
    """NON-VACUOUS control — a fully clean transaction passes ALL blocking gates.

    Without this, an always-block chain would trivially satisfy fail-closed. The
    clean path must NOT be blocked (and must NOT spuriously require multisig for a
    sub-threshold amount)."""
    pipeline = _run_pipeline(safety)
    ok = (not pipeline.blocked) and pipeline.all_passed and (not pipeline.requires_multisig)
    return _result(
        "CLEAN_PATH_PROCEEDS",
        "fully clean tx → not blocked (gate not vacuous)",
        f"blocked={pipeline.blocked} all_passed={pipeline.all_passed} "
        f"requires_multisig={pipeline.requires_multisig}",
        ok,
    )


_DRILLS: tuple[tuple[str, Callable[[Any], dict]], ...] = (
    ("ORDERED", _audit_ordered),
    ("KILL_FIRST", _audit_kill_first),
    ("TOTAL", _audit_total),
    ("FAIL_CLOSED_EACH", _audit_fail_closed_each),
    ("NO_LATER_GATE_UNBLOCKS", _audit_no_later_gate_unblocks),
    ("CLEAN_PATH_PROCEEDS", _audit_clean_path_proceeds),
)


# --------------------------------------------------------------------------- #
# Scorecard — per-gate present / ordered / blocking state.
# --------------------------------------------------------------------------- #
def _gate_scorecard(safety: Any) -> list[dict]:
    pipeline = _run_pipeline(safety)
    realised = _realised_order(pipeline)
    by_name = {c.check_name: c for c in pipeline.checks}
    rows: list[dict] = []
    for idx, (name, blocking) in enumerate(CANONICAL_CHAIN):
        present = name in by_name
        actual_idx = realised.index(name) if name in realised else None
        rows.append({
            "position": idx + 1,
            "gate": name,
            "blocking": blocking,
            "present": present,
            "ordered": actual_idx == idx,
            "actual_position": (actual_idx + 1) if actual_idx is not None else None,
            "kill_switch_first": (idx == 0 and name == KILL_SWITCH_FIRST),
        })
    return rows


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #
def audit(data_dir: Optional[str | os.PathLike] = None, *, write: bool = True) -> dict:
    """Run the full gate-chain audit against a SANDBOX and produce the scorecard.

    Args:
        data_dir: sandbox dir for the persisted kill-switch state. When None a
            fresh temp dir is created + torn down. The live ``data/`` is NEVER
            used (we redirect ``safety_checks`` via ``set_data_dir_override``).
        write: when True, persist the report atomically INTO the sandbox dir.

    Returns the report dict. ``chain_bulletproof`` is True iff every audit drill
    passed. ``would_cutover`` is ALWAYS False (this audit is inert).
    """
    from spa_core.execution import safety_checks as sc

    own_tmp = data_dir is None
    ddir = Path(tempfile.mkdtemp(prefix="spa_gate_chain_")) if own_tmp else Path(data_dir)

    # HARD GUARD: never run against live data/.
    live_data = (_ROOT / "data").resolve()
    if ddir.resolve() == live_data:
        from spa_core.utils.errors import SPAError
        raise SPAError(
            "gate_chain_audit REFUSED to run against live data/ — pass a sandbox "
            "data_dir (this audit is inert and sandbox-only).",
            code="GATE_CHAIN_AUDIT_LIVE_DATA_REFUSED",
        )

    saved_override = sc._DATA_DIR_OVERRIDE
    sc.set_data_dir_override(ddir)
    try:
        ddir.mkdir(parents=True, exist_ok=True)
        # Ensure no inherited kill flag in the sandbox.
        kp = ddir / "kill_switch_active.json"
        if kp.exists():
            try:
                kp.unlink()
            except OSError:
                pass

        safety = sc.PreExecutionSafety()
        results: list[dict] = []
        for name, drill in _DRILLS:
            try:
                results.append(drill(safety))
            except Exception as exc:  # a drill that raises is fail-CLOSED.
                results.append(_result(
                    name, "drill executes and asserts",
                    f"FAIL-CLOSED: drill raised {type(exc).__name__}: {exc}",
                    False, detail="drill error → property NOT proven",
                ))

        scorecard = _gate_scorecard(safety)
        all_passed = all(r["pass"] for r in results)
        failing = [r["check"] for r in results if not r["pass"]]

        report = {
            "generated_at": _now_iso(),
            "module": "gate_chain_audit",
            "version": REPORT_VERSION,
            "is_inert": IS_INERT,
            "moves_capital": False,
            "llm_forbidden": True,
            "sandbox_data_dir": str(ddir),
            "live_data_untouched": True,
            "canonical_chain": [
                {"position": i + 1, "gate": n, "blocking": b}
                for i, (n, b) in enumerate(CANONICAL_CHAIN)
            ],
            "kill_switch_first": KILL_SWITCH_FIRST,
            "gate_scorecard": scorecard,
            "audits": results,
            "audits_total": len(results),
            "audits_passed": sum(1 for r in results if r["pass"]),
            "failing_audits": failing,
            "properties": {
                "ordered": next(r["pass"] for r in results if r["check"] == "ORDERED"),
                "kill_first": next(r["pass"] for r in results if r["check"] == "KILL_FIRST"),
                "total": next(r["pass"] for r in results if r["check"] == "TOTAL"),
                "fail_closed_each": next(
                    r["pass"] for r in results if r["check"] == "FAIL_CLOSED_EACH"),
                "no_later_gate_unblocks": next(
                    r["pass"] for r in results if r["check"] == "NO_LATER_GATE_UNBLOCKS"),
            },
            "chain_bulletproof": all_passed,
            "would_cutover": False,  # ALWAYS False — inert; LiveTradingGate is master block
        }
        if write:
            atomic_save(report, str(ddir / _REPORT_FILENAME))
        return report
    finally:
        sc.set_data_dir_override(saved_override)
        if own_tmp:
            import shutil
            shutil.rmtree(ddir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(report: dict) -> None:
    print("=" * 74)
    print("SPA PRE-EXECUTION GATE-CHAIN AUDIT (WS-3.1) — ordered · total · fail-closed")
    print("=" * 74)
    print(f"sandbox data_dir   : {report['sandbox_data_dir']}")
    print(f"live_data_untouched: {report['live_data_untouched']}   is_inert: {report['is_inert']}")
    print("-" * 74)
    print("canonical ordered chain (kill switch FIRST):")
    for row in report["gate_scorecard"]:
        blk = "BLOCK" if row["blocking"] else "info "
        mark = "OK" if (row["present"] and row["ordered"]) else "!!"
        print(f"  [{mark}] {row['position']}. {row['gate']:<24} [{blk}] "
              f"present={row['present']} ordered={row['ordered']}")
    print("-" * 74)
    for r in report["audits"]:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f" [{mark}] {r['check']:<24} expected: {r['expected']}")
        print(f"        actual  : {r['actual']}")
    print("-" * 74)
    print(f" audits_passed    : {report['audits_passed']}/{report['audits_total']}")
    print(f" chain_bulletproof: {report['chain_bulletproof']}")
    if report["failing_audits"]:
        print(f" FAILING          : {', '.join(report['failing_audits'])}")
    print(f" would_cutover    : {report['would_cutover']}  (ALWAYS False — inert)")
    print("=" * 74)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="SPA pre-execution gate-chain audit (WS-3.1) — assert the "
                    "ordered, total, fail-closed defense chain (sandbox, inert).")
    p.add_argument("--data-dir", default=None, help="sandbox dir (default: temp)")
    p.add_argument("--json-only", action="store_true")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args(argv)
    report = audit(data_dir=args.data_dir, write=not args.no_save)
    if args.json_only:
        import json
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print(report)
    return 0 if report["chain_bulletproof"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
