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

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_POSITIONS = _DATA / "current_positions.json"
_OUT = _DATA / "golive_dry_run.json"

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
    # Uses the EXECUTION kill-switch semantics (the 5% max_drawdown_stop that
    # gates real capital), so an injected 6% drawdown trips it. This mirrors
    # PreExecutionSafety.check_not_in_kill_switch — the threshold that actually
    # blocks a live trade. (The governance KillSwitchChecker's 15% drawdown
    # trigger is a separate, slower book-closing signal.)
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
            from spa_core.execution.safety_checks import PreExecutionSafety, _kill_switch_active  # noqa: F401
            safety = PreExecutionSafety()
            # Inject a manual kill into the safety module state if requested, then
            # always restore it (the harness must not leave global state dirty).
            if manual_kill:
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
    rep = build_report(write=True)
    _print_walk(rep)
    print(f"\nwrote: {_OUT}")
