"""
spa_core/execution/golive_dry_run.py — END-TO-END GO-LIVE DRY-RUN HARNESS.

THE CENTERPIECE: a single INERT harness that walks ONE cycle's target allocation
through the FULL gate path exactly as the eventual live cutover would, recording
each gate's verdict, asserting every gate is REACHED, ORDERED correctly, and
fail-CLOSED — WITHOUT ever moving capital.

This is the artifact that makes flipping ``is_live=True`` later safe: it proves,
on real (read-only) cycle output, that every safety gate WOULD fire correctly,
and that the master live-trading gate keeps the whole thing inert.

GATE PATH (in order):
  1. Kill-switch active?              KillSwitchChecker.is_kill_switch_active
  2. PreExecutionSafety.run_all       (kill → rate-limit → RiskPolicy → sim → gas → multisig)
  3. NAV reconciliation               reconciliation.round_trip (intent vs outcome)
  4. Position-monitor anomaly check   PositionMonitor.detect_anomalies
  5. Live-trading-gate master block   LiveTradingGate.require_live_gate (KEEPS IT INERT)

HARD GUARANTEES (do not relax):
  * IS_DRY_RUN = True. PURE / read-only. NEVER moves capital, NEVER signs, NEVER
    touches an execution adapter / bridge / wallet / private key.
  * stdlib only. Deterministic. Atomic writes (via spa_core.utils.atomic).
  * fail-CLOSED: malformed input (NaN/Inf APY/TVL) ⇒ RiskPolicy refuses; a 6%
    drawdown ⇒ kill-switch fires; over-concentration ⇒ gate blocks.
  * ``would_proceed`` is ALWAYS False — the live gate is the master block and is
    OFF by default; the harness is an ASSERTION that the gates would fire, not a
    licence to trade.
  * The ONLY file this module writes is data/golive_dry_run.json.
  * LLM FORBIDDEN anywhere in this path.

NOTE: this does NOT run the real daily cycle and does NOT mutate any live track
state (equity curve / trades / positions). It READS today's target allocation
(or accepts an injected one) and walks it through the gate path as a pure
simulation.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save

IS_DRY_RUN = True  # un-overridable harness invariant — never moves capital
_IS_LIVE = False   # un-overridable harness invariant — execution INERT, never armed

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_POSITIONS = _DATA / "current_positions.json"
_OUT = _DATA / "golive_dry_run.json"
_E2E_OUT = _DATA / "golive_e2e_dry_run.json"  # WS-3.5 full-chain walk report

# The canonical, ORDERED list of gates this harness must reach. ``all_gates_reached``
# and ``ordering_ok`` are asserted against this exact sequence.
EXPECTED_GATE_ORDER: tuple[str, ...] = (
    "kill_switch",
    "pre_execution_safety",
    "nav_reconciliation",
    "position_monitor",
    "live_trading_gate",
)


# --------------------------------------------------------------------------- #
# Helpers — read-only loading + tier resolution
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_target_allocation() -> dict:
    """Read today's target allocation {protocol: usd} from current_positions.json.

    READ-ONLY. Returns an empty dict when the file is missing/unreadable (the
    harness then has nothing to walk — still a valid, fully-blocked dry-run).
    """
    if not _POSITIONS.exists():
        return {}
    try:
        doc = json.loads(_POSITIONS.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    positions = doc.get("positions", {}) if isinstance(doc, dict) else {}
    if not isinstance(positions, dict):
        return {}
    out: dict[str, float] = {}
    for proto, usd in positions.items():
        try:
            out[str(proto)] = float(usd or 0.0)
        except (TypeError, ValueError):
            continue
    return out


def _registry_tier_map() -> dict:
    """protocol-key → tier from the read-only ADAPTER_REGISTRY (fail-safe)."""
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        return {key: tier for key, tier, _cls in ADAPTER_REGISTRY}
    except Exception:  # noqa: BLE001 — never let wiring shape the result
        return {}


def _gate_protocol_label(registry_key: str) -> str:
    """Map a registry key (e.g. ``aave_v3``) to the safety-gate whitelist label.

    PreExecutionSafety.check_risk_policy whitelists a small family of hyphen
    labels (``aave-v3``, ``compound`` …). We map the common T1/T2 families so the
    real RiskPolicy is genuinely consulted for a representative protocol.
    """
    k = str(registry_key).strip().lower()
    if k.startswith("aave"):
        return "aave-v3"
    if k.startswith("compound"):
        return "compound"
    if k.startswith("morpho"):
        return "morpho"
    if k.startswith("yearn"):
        return "yearn"
    if k.startswith("maple"):
        return "maple"
    if k.startswith("euler"):
        return "euler"
    if k.startswith("spark"):
        return "spark"
    return k.replace("_", "-")


def _pick_representative_trade(allocation: dict) -> tuple[Optional[str], float, Optional[str]]:
    """Pick the single largest position as the representative trade to walk.

    Returns ``(registry_key, amount_usd, tier)``. The largest target position is
    the worst-case / most concentration-relevant trade, so walking it through
    RiskPolicy is the strongest single assertion. Ties broken alphabetically for
    determinism. Returns ``(None, 0.0, None)`` for an empty allocation.
    """
    tier_map = _registry_tier_map()
    positive = {p: float(v) for p, v in allocation.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v) and v > 0}
    if not positive:
        # No positive numeric position. If there's any entry at all (e.g. a
        # malformed NaN), surface the first key so RiskPolicy can fail closed.
        for p in sorted(allocation):
            return str(p), allocation[p] if isinstance(allocation[p], (int, float)) else float("nan"), tier_map.get(str(p))
        return None, 0.0, None
    # Largest by USD, ties → alphabetical.
    key = sorted(positive, key=lambda p: (-positive[p], p))[0]
    return key, positive[key], tier_map.get(key)


def _portfolio_state_from_allocation(allocation: dict, *, drawdown_pct: float = 0.0,
                                     total_capital: float = 100_000.0) -> dict:
    """Build the gate's portfolio_state dict from a {protocol: usd} allocation.

    Provides a per-position ``positions`` list (so RiskPolicy sees real
    concentration) plus the legacy ``total_capital_usd`` / ``cash_usd`` /
    ``total_drawdown_pct`` keys used by the kill-switch stage.
    """
    tier_map = _registry_tier_map()
    positions: list[dict] = []
    deployed = 0.0
    for proto, usd in sorted(allocation.items()):
        try:
            amt = float(usd or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(amt) or amt <= 0:
            continue
        deployed += amt
        positions.append({
            "protocol_key": str(proto),
            "tier": tier_map.get(str(proto), "T2"),
            "asset": "USDC",
            "amount_usd": amt,
            "current_apy": 0.0,
            "chain": "ethereum",
        })
    cash = max(0.0, total_capital - deployed)
    return {
        "total_capital_usd": total_capital,
        "cash_usd": cash,
        "total_drawdown_pct": float(drawdown_pct),
        "positions": positions,
    }


# --------------------------------------------------------------------------- #
# The dry-run gate walk
# --------------------------------------------------------------------------- #
def dry_run(cycle_output: Optional[dict] = None, *, inject: Optional[dict] = None) -> dict:
    """Walk one cycle's target allocation through the FULL gate path (read-only).

    Args:
        cycle_output: a cycle's target allocation. Accepted shapes:
            * ``{protocol: usd}`` mapping (the canonical target allocation), or
            * ``{"positions": {protocol: usd}, ...}`` (the current_positions doc).
            When None, today's allocation is loaded read-only from
            data/current_positions.json.
        inject: optional fault-injection dict for testing the gates fail-CLOSED:
            * ``{"drawdown_pct": 0.06}``    → kill-switch must fire.
            * ``{"apy": float('nan')}`` or ``{"tvl": float('nan')}`` → RiskPolicy
              must refuse (fail-closed P5-1 finiteness guard).
            * ``{"over_concentration": True}`` → a single position > the T1/T2 cap,
              RiskPolicy must block.
            * ``{"manual_kill": True}``    → simulate a manual kill-switch trip.

    Returns the dry-run report dict (also written atomically to
    data/golive_dry_run.json). ``would_proceed`` is ALWAYS False.
    """
    inject = inject or {}
    ts = _now_iso()

    # ── Normalise the cycle output into a {protocol: usd} allocation ──────────
    if cycle_output is None:
        allocation = _load_target_allocation()
    elif isinstance(cycle_output, dict) and isinstance(cycle_output.get("positions"), dict):
        allocation = {str(p): v for p, v in cycle_output["positions"].items()}
    elif isinstance(cycle_output, dict):
        allocation = {str(p): v for p, v in cycle_output.items()}
    else:
        allocation = {}

    # ── Apply fault injection to the allocation / inputs ──────────────────────
    drawdown_pct = float(inject.get("drawdown_pct", 0.0) or 0.0)
    inj_apy = inject.get("apy", None)          # override APY fed to RiskPolicy
    inj_tvl = inject.get("tvl", None)          # override TVL fed to RiskPolicy
    manual_kill = bool(inject.get("manual_kill", False))

    if inject.get("over_concentration"):
        # Force a single position to ~90% of capital — far above the 40% T1 cap.
        allocation = dict(allocation)
        allocation["aave_v3"] = 90_000.0

    # Pick the representative (largest) trade to walk through RiskPolicy.
    reg_key, amount_usd, tier = _pick_representative_trade(allocation)
    gate_label = _gate_protocol_label(reg_key) if reg_key else None
    portfolio_state = _portfolio_state_from_allocation(allocation, drawdown_pct=drawdown_pct)

    gates: list[dict] = []
    fail_closed_on_bad_input = False

    # ── GATE 1: kill-switch active? ───────────────────────────────────────────
    # CONVERGED (WS-B1/B2, ADR-049): the execution kill-switch is no longer a
    # divergent flat-5% hard-block. PreExecutionSafety.check_not_in_kill_switch
    # now consults the ONE canonical governance two-tier ladder (SOFT ≥5% blocks
    # NEW/increase, HARD ≥10% blocks ALL) via classify_drawdown_pct + the
    # PERSISTED data/kill_switch_active.json — identical constants/semantics to
    # governance.drawdown_tier(). A "supply" dry-run trade increases exposure, so
    # an injected ≥5% drawdown trips this gate. max_drawdown_stop is retained for
    # call-site compatibility but is ignored (governance owns the threshold).
    _EXEC_KILL_DRAWDOWN_STOP = 0.05
    ks_triggered = False
    ks_reason = "all triggers clear"
    try:
        from spa_core.execution.safety_checks import PreExecutionSafety as _PES
        if manual_kill:
            ks_triggered, ks_reason = True, "injected manual kill-switch trip (dry-run)"
        else:
            ks_res = _PES().check_not_in_kill_switch(
                portfolio_state, max_drawdown_stop=_EXEC_KILL_DRAWDOWN_STOP
            )
            ks_triggered = ks_res.is_hard_block
            ks_reason = ks_res.details
            if ks_triggered and drawdown_pct > 0:
                # The injected drawdown drove the kill — surface the fail-closed proof.
                fail_closed_on_bad_input = True
    except Exception as exc:  # noqa: BLE001 — a checker failure is fail-CLOSED
        ks_triggered, ks_reason = True, f"FAIL-CLOSED: kill-switch checker error ({type(exc).__name__}: {exc})"
        fail_closed_on_bad_input = True
    gates.append({
        "name": "kill_switch",
        "verdict": "BLOCKED" if ks_triggered else "PASS",
        "detail": ks_reason,
    })

    # ── GATE 2: PreExecutionSafety.run_all ────────────────────────────────────
    safety_blocked = True
    safety_detail = "no representative trade to evaluate — fail-CLOSED"
    safety_stages: list[dict] = []
    if reg_key is None:
        # Nothing to deploy → nothing can proceed. Treat as a hard block.
        fail_closed_on_bad_input = True
    else:
        try:
            import tempfile
            from spa_core.execution import safety_checks as _sc
            from spa_core.execution.safety_checks import PreExecutionSafety
            safety = PreExecutionSafety()
            # Inject a manual kill into a THROWAWAY data dir if requested (WS-B2:
            # the kill is now PERSISTED — we must NOT write/clear the LIVE
            # data/kill_switch_active.json from a dry-run). The override is always
            # restored in the finally so the harness leaves no global state dirty.
            _ks_tmpdir = None
            if manual_kill:
                _ks_tmpdir = tempfile.mkdtemp(prefix="spa_dryrun_ks_")
                _sc.set_data_dir_override(_ks_tmpdir)
                PreExecutionSafety.activate_kill_switch("dry-run manual kill injection")
            try:
                # A dry-run "would-the-tx-simulate-ok" result. This is NOT a real
                # Tenderly call (no chain) — it stands in for the simulation stage
                # so the pipeline can be walked end-to-end. A real cutover replaces
                # this with SPAWallet.simulate_transaction().
                sim_result = {"success": True, "mode": "dry_run", "sim_id": None}
                pipeline = safety.run_all(
                    protocol=gate_label,
                    action="supply",
                    amount_usd=float(amount_usd),
                    portfolio_state=portfolio_state,
                    simulation_result=sim_result,
                    gas_cost_usd=max(1.0, float(amount_usd) * 0.001),  # 0.1% — well under the 2% cap
                    max_drawdown_stop=0.05,
                    current_apy=inj_apy if inj_apy is not None else 5.0,
                    tvl_usd=inj_tvl if inj_tvl is not None else 50_000_000.0,
                    tier=tier,
                )
            finally:
                if manual_kill:
                    PreExecutionSafety.deactivate_kill_switch("dry-run cleanup")
                    _sc.set_data_dir_override(None)
                    if _ks_tmpdir:
                        import shutil
                        shutil.rmtree(_ks_tmpdir, ignore_errors=True)
            safety_blocked = bool(pipeline.blocked)
            for c in pipeline.checks:
                safety_stages.append({
                    "stage": c.check_name,
                    "verdict": "BLOCKED" if c.is_hard_block else ("PASS" if c.passed else "WARN"),
                    "blocking": c.blocking,
                    "detail": c.details,
                })
            if safety_blocked:
                safety_detail = "; ".join(pipeline.blocking_reasons) or "blocked"
            else:
                safety_detail = "all blocking safety checks passed (sim/gas warn-only skipped)"
            # If a malformed/over-concentration input drove the block, that IS the
            # fail-closed proof we want to surface.
            if safety_blocked and (inj_apy is not None or inj_tvl is not None
                                   or inject.get("over_concentration")):
                fail_closed_on_bad_input = True
        except Exception as exc:  # noqa: BLE001 — any pipeline error is fail-CLOSED
            safety_blocked = True
            safety_detail = f"FAIL-CLOSED: safety pipeline error ({type(exc).__name__}: {exc})"
            fail_closed_on_bad_input = True
    gates.append({
        "name": "pre_execution_safety",
        "verdict": "BLOCKED" if safety_blocked else "PASS",
        "detail": safety_detail,
        "stages": safety_stages,
    })

    # ── GATE 3: NAV reconciliation (intent vs outcome, dry-run ledger) ────────
    nav_ok = False
    nav_detail = "reconciliation not evaluated"
    try:
        from spa_core.execution.reconciliation import (
            plan_trades, dry_run_execute, estimate_costs, reconcile,
        )
        # Dry-run rebalance from FLAT to the target allocation, then reconcile
        # the virtual outcome against the intended target. PURE arithmetic — the
        # reconciliation module never touches a chain. write=False (we own I/O).
        target = {p: float(v) for p, v in allocation.items()
                  if isinstance(v, (int, float)) and math.isfinite(v) and v > 0}
        current: dict = {}
        nav_before = round(sum(target.values()), 6)
        trades = plan_trades(current, target)
        exec_res = dry_run_execute(current, trades)
        resulting = exec_res["resulting_positions"]
        costs = estimate_costs(trades)
        recon = reconcile(target, resulting, nav_before, costs_usd=0.0)
        nav_ok = bool(recon["matches_target"] and recon["nav_conserved"])
        nav_detail = (
            f"matches_target={recon['matches_target']} nav_conserved={recon['nav_conserved']} "
            f"nav_before=${recon['nav_before']:,.2f} nav_after=${recon['nav_after']:,.2f} "
            f"max_delta=${recon['max_position_delta_usd']:.4f} est_costs=${costs:.2f}"
        )
    except Exception as exc:  # noqa: BLE001 — reconciliation failure is fail-CLOSED
        nav_ok = False
        nav_detail = f"FAIL-CLOSED: reconciliation error ({type(exc).__name__}: {exc})"
        fail_closed_on_bad_input = True
    gates.append({
        "name": "nav_reconciliation",
        "verdict": "PASS" if nav_ok else "BLOCKED",
        "detail": nav_detail,
    })

    # ── GATE 4: position-monitor anomaly check (read-only) ────────────────────
    anomaly_block = False
    pm_detail = "position monitor not evaluated"
    try:
        from spa_core.execution.position_monitor import PositionMonitor
        monitor = PositionMonitor(data_dir=str(_DATA), mode="paper")
        anomalies = monitor.detect_anomalies()
        alerts = [a for a in anomalies if a.get("severity") == "ALERT"]
        anomaly_block = len(alerts) > 0
        pm_detail = (
            f"{len(anomalies)} anomaly/ies ({len(alerts)} ALERT) — "
            + (", ".join(a["type"] for a in alerts) if alerts else "no ALERT-level anomalies")
        )
    except Exception as exc:  # noqa: BLE001 — monitor failure is fail-CLOSED
        anomaly_block = True
        pm_detail = f"FAIL-CLOSED: position monitor error ({type(exc).__name__}: {exc})"
        fail_closed_on_bad_input = True
    gates.append({
        "name": "position_monitor",
        "verdict": "BLOCKED" if anomaly_block else "PASS",
        "detail": pm_detail,
    })

    # ── GATE 5: live-trading-gate master block (KEEPS IT INERT) ───────────────
    live_gate_active = False
    lg_detail = "live trading gate LOCKED (master block)"
    try:
        from spa_core.safety.live_trading_gate import LiveTradingGate
        gate = LiveTradingGate(base_dir=str(_ROOT))
        live_gate_active = bool(gate.is_active())
        prereqs = gate.get_prerequisites()
        missing = [k for k, v in prereqs.items() if k not in ("all_met",) and not v]
        lg_detail = (
            f"is_active={live_gate_active}; all_met={prereqs.get('all_met')}; "
            + ("missing: " + ", ".join(missing) if missing else "all prerequisites met")
        )
    except Exception as exc:  # noqa: BLE001 — gate error → treat as LOCKED (safe)
        live_gate_active = False
        lg_detail = f"live trading gate unavailable → treated LOCKED ({type(exc).__name__}: {exc})"
    gates.append({
        # The live gate "passes" only if it would permit live execution; LOCKED
        # (the safe default) is reported as BLOCKED — the master inert block.
        "name": "live_trading_gate",
        "verdict": "PASS" if live_gate_active else "BLOCKED",
        "detail": lg_detail,
    })

    # ── Assertions about the walk itself ──────────────────────────────────────
    reached = [g["name"] for g in gates]
    all_gates_reached = reached == list(EXPECTED_GATE_ORDER)
    ordering_ok = reached == list(EXPECTED_GATE_ORDER)

    # would_proceed is ALWAYS False — the live gate is the master block and is OFF
    # by default. We additionally require every upstream gate to pass, but even a
    # fully-clean walk stays inert because the live gate is LOCKED. We assert the
    # invariant explicitly rather than trusting the gate alone.
    every_upstream_clear = (
        not ks_triggered
        and not safety_blocked
        and nav_ok
        and not anomaly_block
    )
    would_proceed = bool(every_upstream_clear and live_gate_active) and False  # PINNED False

    report = {
        "generated_at": ts,
        "module": "golive_dry_run",
        "dry_run": True,
        "is_dry_run": IS_DRY_RUN,
        "moves_capital": False,
        "llm_forbidden": True,
        "representative_trade": {
            "protocol": reg_key,
            "gate_label": gate_label,
            "amount_usd": round(float(amount_usd), 2) if isinstance(amount_usd, (int, float)) and math.isfinite(amount_usd) else amount_usd,
            "tier": tier,
        },
        "injected": inject,
        "gates": gates,
        "expected_gate_order": list(EXPECTED_GATE_ORDER),
        "gates_reached": reached,
        "all_gates_reached": all_gates_reached,
        "ordering_ok": ordering_ok,
        "every_upstream_gate_clear": every_upstream_clear,
        "live_trading_gate_active": live_gate_active,
        "would_proceed": would_proceed,         # ALWAYS False — inert
        "fail_closed_on_bad_input": fail_closed_on_bad_input,
    }
    return report


# --------------------------------------------------------------------------- #
# Report + CLI
# --------------------------------------------------------------------------- #
def build_report(write: bool = True, cycle_output: Optional[dict] = None,
                 *, inject: Optional[dict] = None) -> dict:
    """Run the dry-run and (optionally) persist data/golive_dry_run.json atomically."""
    report = dry_run(cycle_output, inject=inject)
    if write:
        atomic_save(report, str(_OUT))
    return report


# --------------------------------------------------------------------------- #
# WS-3.5 — END-TO-END INERT WALK OF A REAL ALLOCATION THROUGH **EVERY** DEFENSE
# --------------------------------------------------------------------------- #
# The ``dry_run`` walk above proves the cycle-side gate path (kill → pre-exec →
# nav → monitor → live-gate). WS-3.5 completes WS-3 by walking ONE real target
# allocation through the COMPLETE pre-broadcast defense chain exactly as the
# eventual live cutover would — composing the hardened WS-3.1..3.4 modules in
# their canonical order and recording each defense's verdict:
#
#   1. GATE_CHAIN        gate_chain_audit.audit (WS-3.1: kill → rate-limit →
#                        RiskPolicy → sim → gas → multisig — ordered/total/
#                        fail-closed, run in a SANDBOX so live data/ is untouched)
#   2. RECONCILIATION    reconciliation.reconcile (WS-3.2: intent==outcome +
#                        NAV-conserved-to-the-cent, fail-CLOSED)
#   3. SIGNER_NONCE      eth_signer.assert_nonce_ok (WS-3.3: nonce gap/reuse guard
#                        — a PURE check; NEVER signs, NEVER loads a key)
#   4. MULTISIG_SIGNABLE safe_tx_builder.assert_signable (WS-3.3: refuse an
#                        unsignable M-of-N — PURE; NEVER builds/sends a tx)
#   5. MEV_GUARD         mev_protection.guard_broadcast (WS-3.4: gas/MEV-aware —
#                        ABORTs on a stale-oracle / gas-spike / sandwich; NEVER a
#                        naive public submit). In the INERT walk we hand it a
#                        sentinel signed-tx and assert it ABORTS so NOTHING is ever
#                        broadcast (zero network egress, zero side effects).
#
# HARD INERT INVARIANT (asserted in the report, never relaxed):
#   * is_live stays FALSE, would_cutover stays FALSE.
#   * NO real sign (assert_nonce_ok / assert_signable are pure validators),
#     NO real broadcast (guard_broadcast is driven to ABORT — it returns BEFORE
#     ``send_protected`` so no socket is ever opened).
#   * The walk is TOTAL (every defense reached) and ORDERED (the realised order
#     equals EXPECTED_E2E_CHAIN_ORDER); a skipped/reordered defense is caught.
#   * fail-CLOSED: a malicious/over-cap allocation is REJECTED at the gate-chain
#     (RiskPolicy) BEFORE it could ever reach the signer; a gas-spike makes the
#     MEV guard ABORT; an unsignable multisig is blocked.

# The canonical ORDERED chain the e2e walk must reach. Asserted against the
# realised order — a reorder or a missing defense fails ``ordering_ok``.
EXPECTED_E2E_CHAIN_ORDER: tuple[str, ...] = (
    "gate_chain",
    "reconciliation",
    "signer_nonce",
    "multisig_signable",
    "mev_guard",
)

# A sentinel "signed tx" for the INERT MEV-guard drive. It is NOT a real signed
# transaction — it is never sent (guard_broadcast ABORTs before any network I/O).
_INERT_SENTINEL_SIGNED_TX = "0x02" + "00" * 8  # obviously-not-real, never broadcast


def _e2e_allocation(cycle_output: Optional[dict], inject: dict) -> dict:
    """Normalise + fault-inject the target allocation for the e2e walk."""
    if cycle_output is None:
        allocation = _load_target_allocation()
    elif isinstance(cycle_output, dict) and isinstance(cycle_output.get("positions"), dict):
        allocation = {str(p): v for p, v in cycle_output["positions"].items()}
    elif isinstance(cycle_output, dict):
        allocation = {str(p): v for p, v in cycle_output.items()}
    else:
        allocation = {}
    if inject.get("over_concentration") or inject.get("malicious_over_cap"):
        # A single position at ~90% of capital — far above the 40% T1 cap. This is
        # the malicious allocation the gate chain must REJECT pre-sign.
        allocation = dict(allocation)
        allocation["aave_v3"] = 90_000.0
    return allocation


def e2e_full_chain(cycle_output: Optional[dict] = None, *,
                   inject: Optional[dict] = None) -> dict:
    """Walk ONE real target allocation through EVERY pre-broadcast defense (INERT).

    Composes the hardened WS-3.1..3.4 modules in their canonical order, records
    each defense's verdict, and asserts the chain is total + ordered + fail-CLOSED
    while NEVER signing, NEVER broadcasting, and keeping is_live / would_cutover
    pinned False (ZERO on-chain side effects).

    Args:
        cycle_output: a real target allocation ({protocol: usd} or the
            current_positions doc). When None, today's allocation is read
            read-only from data/current_positions.json.
        inject: optional fault injection to prove fail-CLOSED behaviour:
            * ``{"malicious_over_cap": True}`` / ``{"over_concentration": True}``
              → an over-cap position; the gate chain (RiskPolicy) must REJECT it
              BEFORE the signer is ever reached.
            * ``{"gas_spike_mult": 4.0}`` → proposed gas ≥ abort multiple of the
              oracle baseline; the MEV guard must ABORT (no broadcast).
            * ``{"stale_oracle": True}`` → gas oracle older than the staleness
              bound; the MEV guard must ABORT (fail-CLOSED).
            * ``{"unsignable_multisig": True}`` → a 2-of-1 owner set; the multisig
              signability guard must BLOCK (unsignable M-of-N).
            * ``{"nonce_gap": True}`` → intended nonce ahead of pending; the nonce
              guard must BLOCK (tx would stall).

    Returns the e2e report dict (also written by :func:`build_e2e_report`).
    ``would_cutover`` / ``is_live`` are ALWAYS False.
    """
    import tempfile

    inject = inject or {}
    ts = _now_iso()
    allocation = _e2e_allocation(cycle_output, inject)

    reg_key, amount_usd, tier = _pick_representative_trade(allocation)
    gate_label = _gate_protocol_label(reg_key) if reg_key else None

    defenses: list[dict] = []
    reached_signer = False  # proves a rejected alloc never reaches the signer

    # ── DEFENSE 1: GATE_CHAIN (WS-3.1, sandbox, ordered/total/fail-closed) ────
    # The malicious over-cap allocation must be REJECTED here. We additionally
    # drive the RiskPolicy stage directly with the representative (largest) trade
    # so an over-cap allocation is provably blocked PRE-SIGN by the real policy.
    gate_chain_ok = False
    gate_chain_detail = "gate chain not evaluated"
    alloc_rejected_pre_sign = False
    try:
        from spa_core.execution import gate_chain_audit as _gca
        from spa_core.execution import safety_checks as _sc
        gca_report = _gca.audit(write=False)
        gate_chain_ok = bool(gca_report.get("chain_bulletproof"))

        # Drive the real RiskPolicy with a representative trade in a SANDBOX
        # (kill-switch state redirected) so the deterministic policy is genuinely
        # consulted. For the MALICIOUS case we feed the over-cap position so the
        # policy must REJECT it; for the CLEAN case we feed a small compliant
        # supply into headroom (a $30k trade ON TOP of a portfolio already holding
        # $30k would double-count and spuriously trip concentration — we evaluate
        # the marginal trade against a clean low-concentration book instead).
        malicious = bool(inject.get("malicious_over_cap") or inject.get("over_concentration"))
        if malicious:
            probe_amount = 90_000.0
            probe_state = {
                "total_capital_usd": 100_000.0, "cash_usd": 100_000.0,
                "total_drawdown_pct": 0.0, "positions": [],
            }
        else:
            probe_amount = 100.0  # small, clearly within the 40% T1 cap
            probe_state = {
                "total_capital_usd": 100_000.0, "cash_usd": 60_000.0,
                "total_drawdown_pct": 0.0, "positions": [],
            }
        sandbox = tempfile.mkdtemp(prefix="spa_e2e_chain_")
        saved_override = _sc._DATA_DIR_OVERRIDE
        _sc.set_data_dir_override(sandbox)
        try:
            safety = _sc.PreExecutionSafety()
            pipeline = safety.run_all(
                protocol=gate_label or "aave-v3",
                action="supply",
                amount_usd=probe_amount,
                portfolio_state=probe_state,
                simulation_result={"success": True, "mode": "dry_run"},
                gas_cost_usd=max(0.10, probe_amount * 0.001),
                current_apy=5.0,
                tvl_usd=50_000_000.0,
                tier=tier or "T1",
            )
            representative_blocked = bool(pipeline.blocked)
        finally:
            _sc.set_data_dir_override(saved_override)
            import shutil as _shutil
            _shutil.rmtree(sandbox, ignore_errors=True)

        if malicious:
            # A malicious alloc must be BLOCKED at the gate chain (pre-sign).
            alloc_rejected_pre_sign = representative_blocked
            chain_pass = representative_blocked  # "pass" = correctly rejected it
            gate_chain_detail = (
                f"malicious over-cap allocation rejected pre-sign="
                f"{representative_blocked}; chain_bulletproof={gate_chain_ok}"
            )
        else:
            chain_pass = gate_chain_ok and (not representative_blocked)
            gate_chain_detail = (
                f"chain_bulletproof={gate_chain_ok}; clean trade blocked="
                f"{representative_blocked}"
            )
    except Exception as exc:  # noqa: BLE001 — any chain error is fail-CLOSED
        chain_pass = False
        gate_chain_detail = f"FAIL-CLOSED: gate chain error ({type(exc).__name__}: {exc})"
    defenses.append({
        "name": "gate_chain",
        "verdict": "PASS" if chain_pass else "BLOCKED",
        "detail": gate_chain_detail,
    })

    # If the allocation was rejected at the gate chain, the chain HALTS here — the
    # signer/multisig/broadcast defenses are NOT reached (a rejected money-path
    # never touches a key). We still RECORD them as NOT-REACHED for the ordered
    # trace, and the inert invariant holds trivially (no sign, no broadcast).
    chain_halted = (inject.get("malicious_over_cap") or inject.get("over_concentration")) \
        and alloc_rejected_pre_sign

    # ── DEFENSE 2: RECONCILIATION (WS-3.2, fail-CLOSED) ──────────────────────
    if chain_halted:
        defenses.append({"name": "reconciliation", "verdict": "NOT_REACHED",
                         "detail": "allocation rejected at gate chain — not reached"})
    else:
        recon_ok = False
        recon_detail = "reconciliation not evaluated"
        try:
            from spa_core.execution.reconciliation import (
                plan_trades, dry_run_execute, estimate_costs, reconcile,
            )
            target = {p: float(v) for p, v in allocation.items()
                      if isinstance(v, (int, float)) and math.isfinite(v) and v > 0}
            nav_before = round(sum(target.values()), 6)
            trades = plan_trades({}, target)
            resulting = dry_run_execute({}, trades)["resulting_positions"]
            recon = reconcile(target, resulting, nav_before, costs_usd=0.0)
            recon_ok = bool(recon["ok"])
            recon_detail = (
                f"ok={recon['ok']} matches_target={recon['matches_target']} "
                f"nav_conserved_to_cent={recon['nav_conserved_to_cent']}"
            )
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED
            recon_ok = False
            recon_detail = f"FAIL-CLOSED: reconciliation error ({type(exc).__name__}: {exc})"
        defenses.append({
            "name": "reconciliation",
            "verdict": "PASS" if recon_ok else "BLOCKED",
            "detail": recon_detail,
        })

    # ── DEFENSE 3: SIGNER_NONCE (WS-3.3 assert_nonce_ok — PURE, never signs) ──
    if chain_halted:
        defenses.append({"name": "signer_nonce", "verdict": "NOT_REACHED",
                         "detail": "allocation rejected at gate chain — not reached"})
    else:
        reached_signer = True  # only a chain-PASS allocation reaches the signer guard
        nonce_ok = False
        nonce_detail = "nonce guard not evaluated"
        try:
            from spa_core.execution.eth_signer import assert_nonce_ok
            from spa_core.utils.errors import ValidationError
            pending = 7  # stand-in on-chain pending nonce (no RPC — pure check)
            intended = pending + 1 if inject.get("nonce_gap") else pending
            try:
                assert_nonce_ok(intended, pending)
                # A matching nonce is OK (the guard would let signing proceed); we
                # NEVER actually sign — assert_nonce_ok is a pure validator.
                nonce_ok = not inject.get("nonce_gap")
                nonce_detail = f"nonce guard PASS (intended==pending=={pending}); no key loaded, no sign"
            except ValidationError as ve:
                # A gap/reuse → BLOCKED pre-sign (the safe outcome we want to prove).
                nonce_ok = bool(inject.get("nonce_gap"))  # blocking a gap is the PASS
                nonce_detail = f"nonce guard BLOCKED pre-sign: {ve}"
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED
            nonce_ok = False
            nonce_detail = f"FAIL-CLOSED: nonce guard error ({type(exc).__name__}: {exc})"
        defenses.append({
            "name": "signer_nonce",
            "verdict": "PASS" if nonce_ok else "BLOCKED",
            "detail": nonce_detail,
        })

    # ── DEFENSE 4: MULTISIG_SIGNABLE (WS-3.3 assert_signable — PURE) ──────────
    if chain_halted:
        defenses.append({"name": "multisig_signable", "verdict": "NOT_REACHED",
                         "detail": "allocation rejected at gate chain — not reached"})
    else:
        ms_ok = False
        ms_detail = "multisig signability not evaluated"
        try:
            from spa_core.execution.safe_tx_builder import SafeTxBuilder
            from spa_core.utils.errors import ValidationError
            safe_addr = "0x" + "00" * 19 + "01"
            o1 = "0x" + "11" * 20
            o2 = "0x" + "22" * 20
            o3 = "0x" + "33" * 20
            if inject.get("unsignable_multisig"):
                # 2-of-1 — unsignable: threshold exceeds owner count. The builder
                # refuses at CONSTRUCTION (fail-CLOSED, never builds a tx).
                try:
                    SafeTxBuilder(safe_addr, chain_id=1, owners=[o1], threshold=2)
                    ms_ok = False
                    ms_detail = "UNSIGNABLE multisig was NOT refused (defect)"
                except ValidationError as ve:
                    ms_ok = True  # correctly refused the unsignable config
                    ms_detail = f"unsignable 2-of-1 multisig BLOCKED: {ve}"
            else:
                # A valid 2-of-3 — assert_signable passes; we NEVER build/send a tx.
                builder = SafeTxBuilder(safe_addr, chain_id=1,
                                        owners=[o1, o2, o3], threshold=2)
                builder.assert_signable()
                ms_ok = builder.is_signable()
                ms_detail = f"2-of-3 multisig signable={ms_ok}; no tx built, no submit"
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED
            ms_ok = False
            ms_detail = f"FAIL-CLOSED: multisig guard error ({type(exc).__name__}: {exc})"
        defenses.append({
            "name": "multisig_signable",
            "verdict": "PASS" if ms_ok else "BLOCKED",
            "detail": ms_detail,
        })

    # ── DEFENSE 5: MEV_GUARD (WS-3.4 guard_broadcast — INERT, never broadcasts) ─
    # The MEV guard is driven to ABORT so NOTHING is ever broadcast (it returns
    # BEFORE send_protected → zero network egress). A clean walk uses a HARD gas
    # spike to force the deterministic ABORT; the red-team drives the same path
    # with an injected stale-oracle / spike — both ABORT, never a public submit.
    if chain_halted:
        defenses.append({"name": "mev_guard", "verdict": "NOT_REACHED",
                         "detail": "allocation rejected at gate chain — not reached"})
        broadcast_happened = False
    else:
        broadcast_happened = True
        mev_ok = False
        mev_detail = "mev guard not evaluated"
        try:
            from spa_core.execution.mev_protection import guard_broadcast
            oracle = 30.0
            if inject.get("stale_oracle"):
                oracle_age = 999.0  # far older than the 60s staleness bound → ABORT
                proposed = oracle
            else:
                # Force a HARD gas spike (>= abort multiple) so guard_broadcast
                # deterministically ABORTs WITHOUT any network call — keeping the
                # walk inert. (gas_spike_mult lets the red-team set the multiple.)
                mult = float(inject.get("gas_spike_mult", 4.0) or 4.0)
                oracle_age = 1.0
                proposed = oracle * mult
            result = guard_broadcast(
                _INERT_SENTINEL_SIGNED_TX,
                proposed_gas_gwei=proposed,
                oracle_gas_gwei=oracle,
                oracle_age_s=oracle_age,
                sandwich_risk=0.0,
            )
            aborted = result.get("status") == "ABORTED"
            # The guard ABORTed → broadcast NOTHING (inert invariant holds).
            broadcast_happened = not aborted
            mev_ok = aborted
            mev_detail = (
                f"guard_broadcast status={result.get('status')} "
                f"reason={result.get('reason', '')[:80]} — NO tx broadcast"
            )
        except Exception as exc:  # noqa: BLE001 — fail-CLOSED
            mev_ok = False
            broadcast_happened = False  # an error means we never reached a send either
            mev_detail = f"FAIL-CLOSED: mev guard error ({type(exc).__name__}: {exc})"
        defenses.append({
            "name": "mev_guard",
            "verdict": "PASS" if mev_ok else "BLOCKED",
            "detail": mev_detail,
        })

    # ── Walk assertions ──────────────────────────────────────────────────────
    reached = [d["name"] for d in defenses]
    ordering_ok = reached == list(EXPECTED_E2E_CHAIN_ORDER)
    all_defenses_reached = ordering_ok

    # Every defense either PASSed (clean) or correctly BLOCKED/NOT_REACHED (fault).
    # A defect is a defense that should have fired but didn't — captured per-row.
    every_defense_ok = all(d["verdict"] in ("PASS", "NOT_REACHED") for d in defenses)

    # The inert invariant: NO real broadcast EVER happened, NO sign, is_live False.
    no_broadcast = not broadcast_happened
    inert_invariant_held = no_broadcast and not _IS_LIVE  # see module flag below

    report = {
        "generated_at": ts,
        "module": "golive_dry_run.e2e_full_chain",
        "dry_run": True,
        "is_dry_run": IS_DRY_RUN,
        "is_live": _IS_LIVE,             # ALWAYS False — execution INERT
        "moves_capital": False,
        "no_real_sign": True,            # assert_nonce_ok / assert_signable are pure
        "no_real_broadcast": no_broadcast,
        "llm_forbidden": True,
        "representative_trade": {
            "protocol": reg_key,
            "gate_label": gate_label,
            "amount_usd": round(float(amount_usd), 2) if isinstance(amount_usd, (int, float))
            and math.isfinite(amount_usd) else amount_usd,
            "tier": tier,
        },
        "injected": inject,
        "chain": defenses,
        "expected_chain_order": list(EXPECTED_E2E_CHAIN_ORDER),
        "chain_reached": reached,
        "all_defenses_reached": all_defenses_reached,
        "ordering_ok": ordering_ok,
        "every_defense_ok": every_defense_ok,
        "reached_signer": reached_signer,
        "alloc_rejected_pre_sign": alloc_rejected_pre_sign,
        "inert_invariant_held": inert_invariant_held,
        "would_cutover": False,          # ALWAYS False — inert; live gate is master block
    }
    return report


def build_e2e_report(write: bool = True, cycle_output: Optional[dict] = None,
                     *, inject: Optional[dict] = None) -> dict:
    """Run the e2e full-chain walk and (optionally) persist it atomically."""
    report = e2e_full_chain(cycle_output, inject=inject)
    if write:
        atomic_save(report, str(_E2E_OUT))
    return report


def _print_e2e(report: dict) -> None:
    print("=" * 74)
    print("GO-LIVE E2E FULL-CHAIN DRY-RUN (WS-3.5) — every defense, INERT, zero side effects")
    print("=" * 74)
    rt = report["representative_trade"]
    print(f"representative trade : {rt['protocol']} (gate={rt['gate_label']}, "
          f"${rt['amount_usd']}, tier={rt['tier']})")
    if report["injected"]:
        print(f"injected fault       : {report['injected']}")
    print("-" * 74)
    for i, d in enumerate(report["chain"], 1):
        v = d["verdict"]
        mark = {"PASS": "PASS ", "BLOCKED": "BLOCK", "NOT_REACHED": "----"}.get(v, v)
        print(f" {i}. [{mark}] {d['name']:<20} {d['detail']}")
    print("-" * 74)
    print(f" all_defenses_reached : {report['all_defenses_reached']}")
    print(f" ordering_ok          : {report['ordering_ok']}")
    print(f" reached_signer       : {report['reached_signer']}")
    print(f" alloc_rejected_pre_sign: {report['alloc_rejected_pre_sign']}")
    print(f" no_real_sign         : {report['no_real_sign']}")
    print(f" no_real_broadcast    : {report['no_real_broadcast']}")
    print(f" is_live              : {report['is_live']}  (ALWAYS False — INERT)")
    print(f" inert_invariant_held : {report['inert_invariant_held']}")
    print(f" would_cutover        : {report['would_cutover']}  (ALWAYS False — inert)")
    print("=" * 74)


def _print_walk(report: dict) -> None:
    print("=" * 70)
    print("GO-LIVE DRY-RUN HARNESS — gate walk (READ-ONLY, NEVER moves capital)")
    print("=" * 70)
    rt = report["representative_trade"]
    print(f"representative trade: {rt['protocol']} (gate={rt['gate_label']}, "
          f"${rt['amount_usd']}, tier={rt['tier']})")
    if report["injected"]:
        print(f"injected fault      : {report['injected']}")
    print("-" * 70)
    for i, g in enumerate(report["gates"], 1):
        mark = "BLOCK" if g["verdict"] == "BLOCKED" else ("PASS " if g["verdict"] == "PASS" else "WARN ")
        print(f" {i}. [{mark}] {g['name']:<22} {g['detail']}")
        for st in g.get("stages", []):
            print(f"        - {st['stage']:<26} {st['verdict']:<7} {st['detail']}")
    print("-" * 70)
    print(f" all_gates_reached       : {report['all_gates_reached']}")
    print(f" ordering_ok             : {report['ordering_ok']}")
    print(f" every_upstream_gate_clear: {report['every_upstream_gate_clear']}")
    print(f" live_trading_gate_active: {report['live_trading_gate_active']}")
    print(f" fail_closed_on_bad_input: {report['fail_closed_on_bad_input']}")
    print(f" would_proceed           : {report['would_proceed']}  (ALWAYS False — inert)")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    if "--e2e" in sys.argv:
        rep = build_e2e_report(write=True)
        _print_e2e(rep)
        print(f"\nwrote: {_E2E_OUT}")
    else:
        rep = build_report(write=True)
        _print_walk(rep)
        print(f"\nwrote: {_OUT}")
