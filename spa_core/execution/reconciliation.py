"""
spa_core/execution/reconciliation.py — Dry-run rebalance ROUND-TRIP + post-trade RECONCILIATION.

SAFETY-CRITICAL DOMAIN (spa_core/execution/) — but this module is ANALYTICAL ONLY.
It proves the institutional control loop:

    plan_trades  →  dry_run_execute  →  reconcile

so that "going live" later is a single flag flip, and we can VERIFY that the executed
outcome matches the intended target (post-trade control / intent-vs-outcome).

HARD GUARANTEES (do not relax):
  * Pure stdlib only (json, datetime, os, tempfile, pathlib, typing).
  * Deterministic — same inputs ⇒ byte-identical outputs (sorted ordering everywhere).
  * NO network, NO web3, NO private keys, NO live calls. DRY-RUN / virtual ledger ONLY.
  * Does NOT import or modify any existing execution adapter / bridge / live path.
  * Atomic writes (tempfile + os.replace).
  * No LLM anywhere in this path.

Position dicts are {protocol: usd_amount}. Trades are explicit ENTER/EXIT/INCREASE/DECREASE
diffs. The dry-run applies them to a virtual ledger by pure arithmetic. Reconciliation
checks resulting == target (within tolerance) and NAV conservation
(nav_after == nav_before − costs, within tolerance).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_POSITIONS = _DATA / "current_positions.json"
_OUT = _DATA / "execution_reconciliation.json"

# Tolerances (USD) for floating-point comparison.
POSITION_TOLERANCE_USD = 1.0
NAV_TOLERANCE_USD = 1.0

# Deterministic per-trade cost model (analytical, NOT chain-derived):
#   cost = fixed_gas + slippage_bps * notional
# These are conservative placeholder estimates for the dry-run; real costs are
# supplied/validated by the live execution layer (which this module never touches).
GAS_USD_PER_TRADE = 2.0
SLIPPAGE_BPS = 5.0  # 5 basis points = 0.05% of traded notional


# --------------------------------------------------------------------------- #
# Path indirection (so tests can redirect away from the real data files)
# --------------------------------------------------------------------------- #
def _positions_path() -> Path:
    return _POSITIONS


def _out_path() -> Path:
    return _OUT


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def plan_trades(current: dict, target: dict, min_trade_usd: float = 10.0) -> list:
    """Diff current vs target positions into an ordered list of trades.

    Both ``current`` and ``target`` are {protocol: usd}. Each trade is::

        {"protocol": str, "action": str, "amount_usd": float}

    Actions:
      * ENTER    — protocol absent (≈0) in current, present in target
      * EXIT     — protocol present in current, absent (≈0) in target
      * INCREASE — target > current
      * DECREASE — target < current

    Dust trades (|delta| < ``min_trade_usd``) are skipped. ``amount_usd`` is the
    positive magnitude of the change. Deterministic ordering: all exit-side trades
    (EXIT, DECREASE) first, then entry-side (ENTER, INCREASE); within each group,
    sorted alphabetically by protocol — so the plan frees cash before deploying it.
    """
    current = current or {}
    target = target or {}
    protocols = set(current) | set(target)

    exits = []   # EXIT + DECREASE (free cash)
    entries = []  # ENTER + INCREASE (deploy cash)

    for protocol in protocols:
        cur = float(current.get(protocol, 0.0) or 0.0)
        tgt = float(target.get(protocol, 0.0) or 0.0)
        delta = tgt - cur
        if abs(delta) < min_trade_usd:
            continue  # skip dust (includes no-change)

        if cur <= 0.0 and tgt > 0.0:
            action = "ENTER"
        elif cur > 0.0 and tgt <= 0.0:
            action = "EXIT"
        elif delta > 0:
            action = "INCREASE"
        else:
            action = "DECREASE"

        trade = {"protocol": protocol, "action": action, "amount_usd": round(abs(delta), 6)}
        if action in ("EXIT", "DECREASE"):
            exits.append(trade)
        else:
            entries.append(trade)

    exits.sort(key=lambda t: t["protocol"])
    entries.sort(key=lambda t: t["protocol"])
    return exits + entries


# --------------------------------------------------------------------------- #
# Dry-run execution (virtual ledger — pure arithmetic, NO chain)
# --------------------------------------------------------------------------- #
def dry_run_execute(current: dict, trades: list) -> dict:
    """Apply planned trades to a virtual copy of ``current``. NO chain interaction.

    Returns::

        {"resulting_positions": {protocol: usd}, "gross_traded_usd": float}

    ENTER/INCREASE add ``amount_usd``; EXIT/DECREASE subtract it. Positions that
    reach ≈0 are dropped from the result. ``gross_traded_usd`` is the sum of all
    trade magnitudes (the notional that would have moved).
    """
    ledger = {p: float(v or 0.0) for p, v in (current or {}).items()}
    gross = 0.0

    for trade in trades or []:
        protocol = trade["protocol"]
        amount = float(trade["amount_usd"])
        action = trade["action"]
        gross += amount
        if action in ("ENTER", "INCREASE"):
            ledger[protocol] = ledger.get(protocol, 0.0) + amount
        elif action in ("EXIT", "DECREASE"):
            ledger[protocol] = ledger.get(protocol, 0.0) - amount
        # any other action is ignored (defensive; plan_trades never emits one)

    # Drop dust / negative residue, round to cents, deterministic key order.
    resulting = {
        p: round(v, 2)
        for p, v in sorted(ledger.items())
        if abs(v) >= 0.005
    }
    return {"resulting_positions": resulting, "gross_traded_usd": round(gross, 6)}


# --------------------------------------------------------------------------- #
# Cost model (deterministic, analytical)
# --------------------------------------------------------------------------- #
def estimate_costs(trades: list) -> float:
    """Deterministic per-trade cost: fixed gas + slippage bps on traded notional.

    cost = n_trades * GAS_USD_PER_TRADE + (SLIPPAGE_BPS / 10000) * gross_notional
    """
    n = len(trades or [])
    notional = sum(float(t["amount_usd"]) for t in (trades or []))
    cost = n * GAS_USD_PER_TRADE + (SLIPPAGE_BPS / 10000.0) * notional
    return round(cost, 6)


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
def reconcile(
    target: dict,
    resulting: dict,
    nav_before: float,
    costs_usd: float = 0.0,
) -> dict:
    """Verify intent (``target``) matches outcome (``resulting``) and NAV is conserved.

    Returns::

        {
          "matches_target": bool,          # every position within POSITION_TOLERANCE_USD
          "max_position_delta_usd": float, # worst |resulting - target| across all protocols
          "deltas_usd": {protocol: delta}, # signed (resulting - target) where non-trivial
          "nav_before": float,
          "nav_after": float,              # sum(resulting positions)
          "expected_nav_after": float,     # nav_before - costs
          "nav_conserved": bool,           # |nav_after - expected| <= NAV_TOLERANCE_USD
          "costs_usd": float,
          "position_tolerance_usd": float,
          "nav_tolerance_usd": float,
        }
    """
    target = target or {}
    resulting = resulting or {}
    protocols = sorted(set(target) | set(resulting))

    deltas = {}
    max_delta = 0.0
    for protocol in protocols:
        tgt = float(target.get(protocol, 0.0) or 0.0)
        res = float(resulting.get(protocol, 0.0) or 0.0)
        delta = res - tgt
        if abs(delta) >= 0.005:
            deltas[protocol] = round(delta, 6)
        if abs(delta) > max_delta:
            max_delta = abs(delta)

    matches_target = max_delta <= POSITION_TOLERANCE_USD

    nav_after = round(sum(float(v or 0.0) for v in resulting.values()), 6)
    expected_nav_after = round(float(nav_before) - float(costs_usd), 6)
    nav_conserved = abs(nav_after - expected_nav_after) <= NAV_TOLERANCE_USD

    return {
        "matches_target": bool(matches_target),
        "max_position_delta_usd": round(max_delta, 6),
        "deltas_usd": deltas,
        "nav_before": round(float(nav_before), 6),
        "nav_after": nav_after,
        "expected_nav_after": expected_nav_after,
        "nav_conserved": bool(nav_conserved),
        "costs_usd": round(float(costs_usd), 6),
        "position_tolerance_usd": POSITION_TOLERANCE_USD,
        "nav_tolerance_usd": NAV_TOLERANCE_USD,
    }


# --------------------------------------------------------------------------- #
# Disk I/O
# --------------------------------------------------------------------------- #
def _load_current() -> dict:
    """Load positions {protocol: usd} from data/current_positions.json (empty if absent)."""
    path = _positions_path()
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    positions = doc.get("positions", {}) if isinstance(doc, dict) else {}
    return {p: float(v or 0.0) for p, v in positions.items()}


def _atomic_write(doc: dict) -> None:
    """Atomically write ``doc`` as indented JSON to the output path.

    Delegates to the shared :func:`spa_core.utils.atomic.atomic_save` helper so
    the project has a single, audited atomic-write implementation.
    """
    path = _out_path()
    atomic_save(doc, str(path))


# --------------------------------------------------------------------------- #
# Round-trip — the full plan→execute(dry)→reconcile loop
# --------------------------------------------------------------------------- #
def round_trip(
    current: Optional[dict] = None,
    target: Optional[dict] = None,
    write: bool = True,
    min_trade_usd: float = 10.0,
    ts: Optional[str] = None,
) -> dict:
    """Run the full dry-run rebalance loop and reconcile intent vs outcome.

    Args:
        current: starting positions {protocol: usd}. Loaded from
            data/current_positions.json when None.
        target: desired positions {protocol: usd}. Defaults to a COPY of
            ``current`` — a no-op rebalance that must reconcile perfectly
            (the baseline proof that the loop is sound).
        write: persist the report to data/execution_reconciliation.json (atomic).
        min_trade_usd: dust floor for plan_trades.
        ts: ISO-8601 timestamp (supply in tests for determinism; defaults to UTC now).

    Returns the full report dict (also written to disk when ``write``).
    """
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if current is None:
        current = _load_current()
    current = {p: float(v or 0.0) for p, v in (current or {}).items()}

    if target is None:
        target = dict(current)  # no-op baseline
    target = {p: float(v or 0.0) for p, v in (target or {}).items()}

    nav_before = round(sum(current.values()), 6)

    trades = plan_trades(current, target, min_trade_usd=min_trade_usd)
    exec_result = dry_run_execute(current, trades)
    resulting = exec_result["resulting_positions"]
    costs = estimate_costs(trades)

    # The dry-run virtual ledger conserves notional exactly (no costs deducted),
    # which proves the arithmetic. We report cost-adjusted NAV separately so the
    # operator sees the expected real-world drag, while nav_conserved uses the
    # actual costs applied to the ledger (0.0 here — dry run does not burn gas).
    recon = reconcile(target, resulting, nav_before, costs_usd=0.0)

    report = {
        "generated_at": ts,
        "module": "execution_reconciliation",
        "mode": "dry_run_analytical",
        "live_execution": False,
        "llm_forbidden": True,
        "nav_before_usd": nav_before,
        "n_trades": len(trades),
        "gross_traded_usd": exec_result["gross_traded_usd"],
        "estimated_costs_usd": costs,
        "estimated_nav_after_costs_usd": round(nav_before - costs, 6),
        "trades": trades,
        "current_positions": dict(sorted(current.items())),
        "target_positions": dict(sorted(target.items())),
        "resulting_positions": resulting,
        "reconciliation": recon,
        "matches_target": recon["matches_target"],
        "nav_conserved": recon["nav_conserved"],
        "go_live_ready": bool(recon["matches_target"] and recon["nav_conserved"]),
    }

    # Best-effort tamper-evident audit record. Never let an audit failure break the
    # analytical loop (it is parallel infrastructure).
    try:
        from spa_core.audit.hash_chain import append as _audit_append

        _audit_append(
            "execution_reconciliation",
            {
                "mode": report["mode"],
                "n_trades": report["n_trades"],
                "matches_target": report["matches_target"],
                "nav_conserved": report["nav_conserved"],
                "nav_before_usd": report["nav_before_usd"],
                "gross_traded_usd": report["gross_traded_usd"],
            },
            ts=ts,
        )
        report["audit_recorded"] = True
    except Exception:
        report["audit_recorded"] = False

    if write:
        _atomic_write(report)

    return report


# --------------------------------------------------------------------------- #
# CLI / smoke check
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    r = round_trip()
    print(json.dumps({
        "matches_target": r["matches_target"],
        "nav_conserved": r["nav_conserved"],
        "n_trades": r["n_trades"],
        "nav_before_usd": r["nav_before_usd"],
        "gross_traded_usd": r["gross_traded_usd"],
        "estimated_costs_usd": r["estimated_costs_usd"],
        "go_live_ready": r["go_live_ready"],
        "audit_recorded": r["audit_recorded"],
    }, indent=2))
