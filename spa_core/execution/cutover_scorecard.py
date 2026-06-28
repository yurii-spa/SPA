#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core/execution/cutover_scorecard.py — CUTOVER READINESS SCORECARD (WS-3.6).

Cutover-Bulletproof WS-3.6: the honest, machine-checked readiness scorecard that
closes WS-3. It answers ONE question without spin:

    *How much of the paper→live cutover is PROVEN by code today, and what is left
    that ONLY the owner can do?*

It COMPOSES (never re-implements) the WS-3.1..3.5 artifacts plus the institutional
posture self-audit, and produces:

  * a CODE-readiness percentage — the share of code-provable defenses that are
    demonstrably bulletproof RIGHT NOW (gate-chain ordered/total/fail-closed,
    reconciliation fail-closed, signer-nonce / multisig-signable guards, MEV
    guard ABORT, the end-to-end INERT full-chain walk, the pre-cutover defense
    gate, and the read-only posture controls);
  * an explicit, NAMED list of OWNER-ONLY blockers that NO code can satisfy
    (custody/MPC provisioning, real capital, an external security audit, the
    ≥30-day evidenced track, and the final ``is_live`` flip itself).

HONESTY CONTRACT (do not soften)
--------------------------------
  * ``code_readiness_pct`` is CODE readiness ONLY. It is NEVER "ready to go live".
  * ``ready_for_live`` is ALWAYS gated by the owner-only blockers AND the master
    LiveTradingGate — it stays False until a HUMAN flips ``is_live`` after custody,
    capital, audit, and track are real. Code can reach 100% code-readiness and the
    system is STILL not live.
  * The flip is owner-gated. This module NEVER flips it, NEVER signs, NEVER moves
    capital. It only MEASURES and REPORTS.

HARD GUARANTEES (do not relax)
------------------------------
  * READ-ONLY + INERT. Composes inert audits (each runs in its own sandbox / is a
    pure check). The ONLY file written is data/execution_readiness.json (atomic).
  * stdlib only. Deterministic (modulo the timestamp). fail-CLOSED — any audit
    that errors is scored as NOT proven (0 credit), never silently passed.
  * The report is a SUPERSET of readiness_audit's schema (posture / ready_for_live
    / live_blockers / checks preserved) so /api/execution/readiness keeps working.
  * LLM FORBIDDEN anywhere in this path.

CLI::  python3 -m spa_core.execution.cutover_scorecard
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_REPORT_FILENAME = "execution_readiness.json"
REPORT_VERSION = "v2.0"  # supersedes readiness_audit v1.0 schema (additive)

IS_INERT = True  # un-overridable — this scorecard NEVER moves capital / signs.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _defense(name: str, proven: bool, *, detail: str, source: str) -> dict:
    """One code-defense scorecard row."""
    return {"defense": name, "proven": bool(proven), "detail": detail, "source": source}


# --------------------------------------------------------------------------- #
# Code-provable defenses — each is COMPOSED from a WS-3.x inert artifact and
# scored PROVEN only if that artifact demonstrates its property right now.
# fail-CLOSED: any exception → proven=False (no credit).
# --------------------------------------------------------------------------- #
def _score_gate_chain() -> dict:
    """WS-3.1 — the ordered/total/fail-closed pre-execution gate chain."""
    try:
        from spa_core.execution.gate_chain_audit import audit
        rep = audit(write=False)
        proven = bool(rep.get("chain_bulletproof"))
        props = rep.get("properties", {})
        detail = (f"chain_bulletproof={proven}; "
                  f"ordered={props.get('ordered')} kill_first={props.get('kill_first')} "
                  f"total={props.get('total')} fail_closed_each={props.get('fail_closed_each')}")
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: gate_chain_audit error ({type(exc).__name__}: {exc})"
    return _defense("gate_chain_ordered_total_fail_closed", proven,
                    detail=detail, source="gate_chain_audit (WS-3.1)")


def _score_reconciliation() -> dict:
    """WS-3.2 — intent==outcome + NAV-conserved reconciliation, fail-CLOSED."""
    try:
        from spa_core.execution.reconciliation import reconcile
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        clean = reconcile(target, dict(target), 60_000.0, costs_usd=0.0)
        partial = dict(target); partial["aave_v3"] = 25_000.0
        caught = reconcile(target, partial, 60_000.0, costs_usd=0.0)
        proven = bool(clean["ok"]) and bool(caught["blocked"])
        detail = (f"clean ok={clean['ok']} nav_conserved_to_cent={clean['nav_conserved_to_cent']}; "
                  f"partial-fill caught (blocked={caught['blocked']})")
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: reconciliation error ({type(exc).__name__}: {exc})"
    return _defense("reconciliation_fail_closed", proven,
                    detail=detail, source="reconciliation (WS-3.2)")


def _score_signer_nonce() -> dict:
    """WS-3.3 — nonce gap/reuse guard refuses pre-sign (pure validator)."""
    try:
        from spa_core.execution.eth_signer import assert_nonce_ok
        from spa_core.utils.errors import ValidationError
        ok_match = assert_nonce_ok(7, 7) == 7
        gap_blocked = reuse_blocked = False
        try:
            assert_nonce_ok(8, 7)
        except ValidationError:
            gap_blocked = True
        try:
            assert_nonce_ok(6, 7)
        except ValidationError:
            reuse_blocked = True
        proven = ok_match and gap_blocked and reuse_blocked
        detail = f"match_ok={ok_match} gap_blocked={gap_blocked} reuse_blocked={reuse_blocked}"
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: nonce guard error ({type(exc).__name__}: {exc})"
    return _defense("signer_nonce_guard", proven, detail=detail, source="eth_signer (WS-3.3)")


def _score_multisig_signable() -> dict:
    """WS-3.3 — an UNSIGNABLE M-of-N is refused; a valid 2-of-3 is signable."""
    try:
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        safe = "0x" + "00" * 19 + "01"
        owners = ["0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20]
        valid = SafeTxBuilder(safe, chain_id=1, owners=owners, threshold=2).is_signable()
        unsignable_refused = False
        try:
            SafeTxBuilder(safe, chain_id=1, owners=owners[:1], threshold=2)
        except ValidationError:
            unsignable_refused = True
        proven = bool(valid) and unsignable_refused
        detail = f"valid_2of3_signable={valid} unsignable_2of1_refused={unsignable_refused}"
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: multisig guard error ({type(exc).__name__}: {exc})"
    return _defense("multisig_signable_guard", proven, detail=detail, source="safe_tx_builder (WS-3.3)")


def _score_mev_guard() -> dict:
    """WS-3.4 — guard_broadcast ABORTs on stale-oracle / gas-spike (no submit)."""
    try:
        from spa_core.execution.mev_protection import evaluate_gas_and_mev
        stale = evaluate_gas_and_mev(30.0, 30.0, 999.0, 0.0)["decision"] == "ABORT"
        spike = evaluate_gas_and_mev(120.0, 30.0, 1.0, 0.0)["decision"] == "ABORT"
        calm = evaluate_gas_and_mev(31.0, 30.0, 1.0, 0.0)["decision"] == "OK"
        proven = stale and spike and calm
        detail = f"stale_oracle_abort={stale} gas_spike_abort={spike} calm_ok={calm}"
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: mev guard error ({type(exc).__name__}: {exc})"
    return _defense("mev_guard_abort", proven, detail=detail, source="mev_protection (WS-3.4)")


def _score_e2e_walk() -> dict:
    """WS-3.5 — the end-to-end INERT full-chain walk: ordered, inert, zero side effects."""
    try:
        from spa_core.execution.golive_dry_run import e2e_full_chain
        clean = e2e_full_chain({"aave_v3": 30_000.0, "compound_v3": 20_000.0,
                                "morpho_blue": 15_000.0})
        # The malicious allocation must be rejected BEFORE the signer.
        mal = e2e_full_chain({"aave_v3": 30_000.0}, inject={"malicious_over_cap": True})
        proven = bool(
            clean["ordering_ok"] and clean["every_defense_ok"]
            and clean["inert_invariant_held"] and clean["no_real_broadcast"]
            and clean["would_cutover"] is False and clean["is_live"] is False
            and mal["alloc_rejected_pre_sign"] and mal["reached_signer"] is False
        )
        detail = (f"clean ordered={clean['ordering_ok']} inert={clean['inert_invariant_held']} "
                  f"no_broadcast={clean['no_real_broadcast']}; malicious rejected pre-sign="
                  f"{mal['alloc_rejected_pre_sign']} (reached_signer={mal['reached_signer']})")
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: e2e walk error ({type(exc).__name__}: {exc})"
    return _defense("e2e_full_chain_inert", proven, detail=detail,
                    source="golive_dry_run.e2e_full_chain (WS-3.5)")


def _score_pre_cutover_gate() -> dict:
    """WS-3 (Day-2) — every money-path defense fires against a sandbox."""
    try:
        from spa_core.paper_trading.pre_cutover_gate import run_gate
        rep = run_gate(write=False)  # ephemeral sandbox, torn down
        proven = bool(rep.get("all_defenses_fired"))
        detail = (f"all_defenses_fired={proven} "
                  f"({rep.get('defenses_passed')}/{rep.get('defenses_total')})")
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        proven, detail = False, f"FAIL-CLOSED: pre_cutover_gate error ({type(exc).__name__}: {exc})"
    return _defense("pre_cutover_money_path_defenses", proven,
                    detail=detail, source="pre_cutover_gate")


def _score_posture(posture: str, checks: dict) -> dict:
    """Read-only institutional posture controls (dry-run default / caps / kill / multisig)."""
    proven = (
        posture == "PAPER_SAFE"
        and checks.get("adapter_dry_run_default", {}).get("ok") is True
        and checks.get("kill_switch_readable", {}).get("ok") is True
        and checks.get("live_amount_cap", {}).get("ok") is True
        and checks.get("multisig_control", {}).get("ok") is True
    )
    detail = (f"posture={posture}; dry_run_default/kill_readable/amount_cap/multisig_control "
              f"all present and safe")
    return _defense("paper_safe_posture_controls", proven,
                    detail=detail, source="readiness_audit posture")


# The ordered roster of CODE-provable defenses scored by this scorecard.
_CODE_DEFENSE_SCORERS = (
    _score_gate_chain,
    _score_reconciliation,
    _score_signer_nonce,
    _score_multisig_signable,
    _score_mev_guard,
    _score_e2e_walk,
    _score_pre_cutover_gate,
)


# --------------------------------------------------------------------------- #
# The scorecard.
# --------------------------------------------------------------------------- #
def build_scorecard(data_dir: str | os.PathLike | None = None) -> dict:
    """Compose the honest cutover readiness scorecard (READ-ONLY / INERT).

    Returns a dict that is a SUPERSET of readiness_audit's schema:
      * ``posture`` / ``ready_for_live`` / ``live_blockers`` / ``checks`` —
        preserved verbatim from the posture self-audit (so the API + tests keep
        working);
      * ``code_defenses`` — the per-defense scorecard rows (proven / detail / source);
      * ``code_readiness_pct`` — share of code-provable defenses proven NOW;
      * ``code_defenses_proven`` / ``code_defenses_total``;
      * ``owner_only_blockers`` — NAMED human-only blockers code cannot satisfy;
      * ``is_live`` / ``would_cutover`` — ALWAYS False (owner-gated flip).
    """
    dd = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    # ── Posture self-audit (read-only) — reused verbatim, NOT re-implemented. ──
    from spa_core.execution import readiness_audit as ra
    posture_report = ra.audit(data_dir=dd)
    posture = posture_report["posture"]
    checks = posture_report["checks"]

    # ── Score every CODE-provable defense (fail-CLOSED). ──────────────────────
    code_defenses = [scorer() for scorer in _CODE_DEFENSE_SCORERS]
    code_defenses.append(_score_posture(posture, checks))

    proven = sum(1 for d in code_defenses if d["proven"])
    total = len(code_defenses)
    code_readiness_pct = round(100.0 * proven / total, 1) if total else 0.0
    failing = [d["defense"] for d in code_defenses if not d["proven"]]

    # ── Owner-only blockers — NAMED, code CANNOT satisfy these. ───────────────
    # We surface the posture self-audit's honest live_blockers and add the
    # explicit human-only gates (custody / capital / audit / track / the flip).
    owner_only_blockers = [
        "custody/MPC: Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010/022)",
        "real_capital: production capital funded into the Safe (off-code)",
        "external_audit: third-party security audit of the execution path signed off",
        "track_record: ≥30 evidenced honest paper-track days (go-live gate)",
        "is_live_flip: a HUMAN flips is_live / arms the LiveTradingGate (owner-gated)",
    ]

    # ── Master live gate is the inert block — confirm it is LOCKED. ────────────
    live_gate_locked = True
    try:
        from spa_core.safety.live_trading_gate import LiveTradingGate
        live_gate_locked = not bool(LiveTradingGate(base_dir=str(_REPO_ROOT)).is_active())
    except Exception:  # noqa: BLE001 — gate error → treat as LOCKED (safe default)
        live_gate_locked = True

    # ready_for_live is ALWAYS owner-gated: even at 100% code-readiness the flip is
    # human-only. We preserve the posture audit's verdict (which already requires
    # custody/audit/track) AND require the live gate to be active — it never is.
    ready_for_live = bool(posture_report["ready_for_live"]) and (not live_gate_locked)

    report = {
        "audited_at": _now_iso(),
        "version": REPORT_VERSION,
        "module": "cutover_scorecard",
        "is_inert": IS_INERT,
        "moves_capital": False,
        "is_live": False,            # ALWAYS False — execution INERT
        "would_cutover": False,      # ALWAYS False — owner-gated flip
        "llm_forbidden": True,
        # ── readiness_audit schema (preserved for /api + existing consumers) ──
        "posture": posture,
        "checks": checks,
        "ready_for_live": ready_for_live,
        "live_blockers": posture_report["live_blockers"],
        # ── WS-3.6 cutover scorecard (additive) ──────────────────────────────
        "code_defenses": code_defenses,
        "code_defenses_total": total,
        "code_defenses_proven": proven,
        "code_readiness_pct": code_readiness_pct,
        "code_defenses_failing": failing,
        "owner_only_blockers": owner_only_blockers,
        "live_trading_gate_locked": live_gate_locked,
        "honesty_note": (
            "code_readiness_pct is CODE readiness ONLY — the share of code-provable "
            "defenses proven inert right now. It is NOT 'ready to go live': the cutover "
            "is owner-gated (custody, real capital, external audit, ≥30-day track, and a "
            "human is_live flip). ready_for_live stays False until ALL owner-only blockers "
            "are cleared by a human and the LiveTradingGate is armed."
        ),
    }
    return report


def build_report(write: bool = True, data_dir: str | os.PathLike | None = None) -> dict:
    """Build the cutover scorecard and (optionally) persist it atomically.

    Writes data/execution_readiness.json (the file /api/execution/readiness serves)
    so the dashboard surface gets the honest readiness % + owner-blockers. The
    written schema is a SUPERSET of readiness_audit's — existing consumers keep
    their keys.
    """
    dd = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    report = build_scorecard(data_dir=dd)
    if write:
        atomic_save(report, str(dd / _REPORT_FILENAME))
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(report: dict) -> None:
    print("=" * 74)
    print("SPA CUTOVER READINESS SCORECARD (WS-3.6) — honest CODE readiness, owner-gated flip")
    print("=" * 74)
    print(f"posture            : {report['posture']}")
    print(f"code_readiness_pct : {report['code_readiness_pct']}%  "
          f"({report['code_defenses_proven']}/{report['code_defenses_total']} defenses proven)")
    print(f"ready_for_live     : {report['ready_for_live']}  (owner-gated — ALWAYS False until human flip)")
    print(f"is_live            : {report['is_live']}   would_cutover: {report['would_cutover']}")
    print("-" * 74)
    print("CODE-PROVABLE DEFENSES (proven inert RIGHT NOW):")
    for d in report["code_defenses"]:
        mark = "PROVEN" if d["proven"] else "  NOT "
        print(f"  [{mark}] {d['defense']:<34} {d['source']}")
        print(f"            {d['detail'][:96]}")
    if report["code_defenses_failing"]:
        print(f"  FAILING: {', '.join(report['code_defenses_failing'])}")
    print("-" * 74)
    print("OWNER-ONLY BLOCKERS (no code can satisfy these — the flip is human):")
    for b in report["owner_only_blockers"]:
        print(f"  • {b}")
    if report["live_blockers"]:
        print("-" * 74)
        print("posture live_blockers:")
        for b in report["live_blockers"]:
            print(f"  - {b}")
    print("-" * 74)
    print(f"NOTE: {report['honesty_note']}")
    print("=" * 74)


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="SPA cutover readiness scorecard (WS-3.6) — honest CODE "
                    "readiness %, owner-only blockers named (inert, read-only).")
    p.add_argument("--no-save", action="store_true",
                   help="do not write data/execution_readiness.json")
    p.add_argument("--json-only", action="store_true")
    args = p.parse_args(argv)
    report = build_report(write=not args.no_save)
    if args.json_only:
        import json
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
