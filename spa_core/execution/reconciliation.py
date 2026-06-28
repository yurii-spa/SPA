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
import math
from decimal import Decimal, InvalidOperation
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

# ── WS-3.2 hardening constants ──────────────────────────────────────────────
# NAV conservation is checked TO THE CENT with Decimal (no float fuzz): the
# deployed/expected NAVs must agree within one cent. This is INDEPENDENT of the
# coarser ``NAV_TOLERANCE_USD`` operator-facing band above (which still drives
# the ``nav_conserved`` boolean for the existing cost-drag semantics). The cent
# axis is reported as ``nav_conserved_to_cent`` and is the stricter gate.
NAV_CENT = Decimal("0.01")

# Dust floor: a sub-threshold position delta (|delta| < this) is treated as
# clean (rounding/dust); at or above it the delta is a real mismatch. This is
# the SAME magnitude as POSITION_TOLERANCE_USD, named explicitly so the
# dust-vs-mismatch boundary is a first-class, tested contract.
DUST_TOLERANCE_USD = POSITION_TOLERANCE_USD

# Stale-price guard: a reconciliation that is fed a price/quote snapshot must
# carry an ``as_of`` no older than this many seconds, else we cannot trust the
# valuation and MUST fail-CLOSED (block). 0/None ``as_of`` is unknown → block
# only when a ``price_as_of`` was supplied at all (callers that pass none keep
# the legacy behaviour — the gate is opt-in but, once a price age is supplied,
# strictly enforced).
MAX_PRICE_AGE_SECONDS = 120.0


def _to_decimal_cents(value: float | int | str) -> Optional[Decimal]:
    """Quantise a USD value to cents as Decimal, or None if non-finite/invalid.

    Returns ``None`` (NOT 0) on NaN/Inf/garbage so the caller fails CLOSED — a
    non-finite valuation can NEVER be silently coerced to a number that passes a
    conservation check.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    try:
        return Decimal(str(f)).quantize(NAV_CENT)
    except (InvalidOperation, ValueError):
        return None


def _all_positions_finite(*books: dict) -> bool:
    """True iff every position value across the given books is a finite number.

    Bools are rejected (a ``True`` would coerce to 1.0 and masquerade as $1).
    """
    for book in books:
        for v in (book or {}).values():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return False
            if not math.isfinite(float(v)):
                return False
    return True

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
    *,
    price_as_of: Optional[float] = None,
    now: Optional[float] = None,
    max_price_age_seconds: float = MAX_PRICE_AGE_SECONDS,
) -> dict:
    """Verify intent (``target``) matches outcome (``resulting``) and NAV is conserved.

    FAIL-CLOSED CONTRACT (WS-3.2). The reconcile reconciles correctly OR blocks
    (never a silent proceed) under EVERY failure mode:

      * **partial-fill / reorg / state-change** — any position differs from target
        by ≥ ``DUST_TOLERANCE_USD`` → ``matches_target=False`` → block.
      * **non-finite valuation** — any NaN/Inf/garbage position (a corrupt feed
        read) → ``matches_target=False`` AND ``nav_conserved=False`` →
        ``blocked=True``. A non-finite value is NEVER coerced into a passing
        number.
      * **stale-price** — when a ``price_as_of`` epoch is supplied and it is older
        than ``max_price_age_seconds`` → ``price_stale=True`` → block.
      * **dust-tolerance** — a sub-``DUST_TOLERANCE_USD`` delta passes; at/above it
        blocks. NAV conservation is checked TO THE CENT with Decimal
        (``nav_conserved_to_cent``).

    ``ok`` / ``blocked`` are the single safe verdict: ``ok`` is True ONLY when
    matches_target AND nav_conserved AND nav_conserved_to_cent AND not price_stale
    AND all positions finite. Any mismatch → ``blocked=True``.

    Returns the existing keys plus: ``finite`` (bool), ``nav_conserved_to_cent``
    (bool — Decimal cent axis), ``price_stale`` (bool), ``price_age_seconds``,
    ``ok`` / ``blocked`` (the consolidated safe verdict), ``block_reasons``.
    """
    target = target or {}
    resulting = resulting or {}
    protocols = sorted(set(target) | set(resulting))

    # ── Non-finite guard (fail-CLOSED) ───────────────────────────────────────
    # A NaN position makes ``abs(delta) > max_delta`` False, so without this
    # guard a NaN would leave max_delta at 0 and matches_target True (fail-OPEN).
    finite = _all_positions_finite(target, resulting)

    deltas = {}
    max_delta = 0.0
    for protocol in protocols:
        try:
            tgt = float(target.get(protocol, 0.0) or 0.0)
            res = float(resulting.get(protocol, 0.0) or 0.0)
        except (TypeError, ValueError):
            finite = False
            continue
        if not (math.isfinite(tgt) and math.isfinite(res)):
            # leave finite=False (set above); record an infinite delta marker.
            finite = False
            continue
        delta = res - tgt
        if abs(delta) >= 0.005:
            deltas[protocol] = round(delta, 6)
        if abs(delta) > max_delta:
            max_delta = abs(delta)

    # A non-finite book can NEVER match the target.
    matches_target = bool(finite) and (max_delta < DUST_TOLERANCE_USD)

    # ── NAV: float band (legacy) + Decimal cent axis (strict) ────────────────
    nav_after = round(sum(float(v or 0.0) for v in resulting.values()
                          if isinstance(v, (int, float)) and not isinstance(v, bool)
                          and math.isfinite(float(v))), 6)
    expected_nav_after = round(float(nav_before) - float(costs_usd), 6)
    nav_conserved = bool(finite) and (abs(nav_after - expected_nav_after) <= NAV_TOLERANCE_USD)

    # Decimal conservation to the cent — the stricter, exact axis.
    dec_after = _to_decimal_cents(nav_after) if finite else None
    dec_expected = _to_decimal_cents(expected_nav_after)
    if dec_after is None or dec_expected is None:
        nav_conserved_to_cent = False
        nav_residual_cents = None
    else:
        residual = abs(dec_after - dec_expected)
        nav_residual_cents = str(residual)
        nav_conserved_to_cent = residual <= NAV_CENT

    # ── Stale-price guard (opt-in; strict once a price age is supplied) ───────
    price_age_seconds = None
    price_stale = False
    if price_as_of is not None:
        ref_now = float(now) if now is not None else datetime.datetime.now(
            datetime.timezone.utc).timestamp()
        try:
            age = ref_now - float(price_as_of)
        except (TypeError, ValueError):
            price_stale = True
            age = None
        else:
            price_age_seconds = round(age, 6)
            # A future-dated or NaN price is also untrustworthy → stale/block.
            if not math.isfinite(age) or age < 0 or age > float(max_price_age_seconds):
                price_stale = True

    # ── Consolidated safe verdict ────────────────────────────────────────────
    block_reasons: list[str] = []
    if not finite:
        block_reasons.append("non-finite position (corrupt valuation) — fail-closed")
    if not matches_target:
        block_reasons.append(
            f"intent != outcome (max delta ${max_delta:,.2f} ≥ dust ${DUST_TOLERANCE_USD})"
        )
    if not nav_conserved:
        block_reasons.append("NAV not conserved (band)")
    if not nav_conserved_to_cent:
        block_reasons.append("NAV not conserved to the cent")
    if price_stale:
        block_reasons.append(
            f"stale price (age {price_age_seconds}s > {max_price_age_seconds}s)"
        )
    ok = not block_reasons

    return {
        "matches_target": bool(matches_target),
        "max_position_delta_usd": round(max_delta, 6),
        "deltas_usd": deltas,
        "nav_before": round(float(nav_before), 6),
        "nav_after": nav_after,
        "expected_nav_after": expected_nav_after,
        "nav_conserved": bool(nav_conserved),
        "nav_conserved_to_cent": bool(nav_conserved_to_cent),
        "nav_residual_cents": nav_residual_cents,
        "finite": bool(finite),
        "price_as_of": price_as_of,
        "price_age_seconds": price_age_seconds,
        "price_stale": bool(price_stale),
        "max_price_age_seconds": float(max_price_age_seconds),
        "ok": bool(ok),
        "blocked": not bool(ok),
        "block_reasons": block_reasons,
        "costs_usd": round(float(costs_usd), 6),
        "position_tolerance_usd": POSITION_TOLERANCE_USD,
        "dust_tolerance_usd": DUST_TOLERANCE_USD,
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
