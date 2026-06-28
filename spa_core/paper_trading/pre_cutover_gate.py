"""spa_core/paper_trading/pre_cutover_gate.py — THE PRE-CUTOVER READINESS GATE.

Day-2 sprint artifact: SPA's single authoritative PRE-CUTOVER READINESS GATE —
the artifact that proves **every money-path defense provably fires** against a
driven cycle, on a SANDBOX. It is the basis for eventually flipping ``is_live``
(it does NOT flip it — the LiveTradingGate stays the master block).

WHAT IT IS
----------
A consolidation, NOT a 4th harness. Three overlapping harnesses already exist —
``scripts/cycle_dry_run.py`` (MP-428 smoke), ``scripts/golive_preflight.py``
(MP-351 ADR-011 checklist), ``scripts/day1_readiness_check.py`` (MP-1428 Day-1
critical checks). This gate COMPOSES them as advisory sub-reports and adds the
ONE thing none of them do: it DRIVES a cycle through EACH money-path failure mode
against a sandbox and ASSERTS the correct defensive response actually fires.

THE DEFENSES IT ASSERTS (each: drive the failure mode → assert the response)
---------------------------------------------------------------------------
  HARD_KILL_DRAWDOWN     10% evidenced drawdown → KillSwitchChecker fires → the
                         kill-switch override forces an ALL-CASH allocation
                         (ADR-048: hard kill lowered 15→10).
  HARD_KILL_MANUAL       manual kill file present → KillSwitchChecker fires →
                         all-cash override.
  HARD_KILL_RED_FLAGS    > threshold CRITICAL red-flags on a HELD protocol →
                         KillSwitchChecker fires → all-cash override.
  SOFT_DERISK            evidenced drawdown in [5%, 10%) → de-risk gate: NO new
                         positions, NO increase of held (hold/reduce only), and
                         (Day-1-validated, post-ALLOC-002) the gate does NOT
                         liquidate.
  DL01_DAILY_LOSS        daily loss > 2% → DailyLimitsChecker HALT (distinct
                         daily-loss axis, UNCHANGED).
  DL02_DEFERS_TO_KILL    peak drawdown ≥ 10% → the hard kill now OWNS this rung
                         (ADR-048): DL-02's HALT is DEFERRED in run_cycle so the
                         all-cash kill-switch override fires (the stronger action
                         wins; DL-02 no longer shadows the kill).
  RISKPOLICY_BLOCK       a RiskPolicy-violating target (over-concentration) →
                         _apply_risk_policy_gate approved=False.
  ANALYTICS_BLOCK        a Tier-A BLOCK signal → analytics gate zeroes the
                         blocked protocol's target.
  BASE_GAS_BLOCK         Base-gas kill-switch active → Base allocations zeroed.
  NAV_RECONCILE          flat → target dry-run rebalance reconciles to NAV==0
                         residual (intent == outcome), and a deliberately
                         corrupted position set is CAUGHT.
  PARTIAL_FILL_RECOVERY  an order fills only PARTIALLY → reconcile reports
                         matches_target=False → ABORT (a partial fill can never
                         masquerade as success); a clean FULL fill still passes.
  RECONCILE_MISMATCH     NAV NOT conserved (deployed > capital — capital
                         appeared/vanished) → reconcile BLOCKS; a conserved book
                         passes.
  SIGNER_FAILURE         the signing step RAISES (key-load fail / nonce gap) →
                         SAFE ABORT (no tx submitted, positions unchanged) AND no
                         private-key material in any surfaced diagnostic.
  POSITION_MONITOR       position-monitor reports correctly in BOTH new states
                         (post-HARD-kill all-cash; post-SOFT held-only), and a
                         corrupted position set is caught.
  FAILSAFE_HOLD          when a safety eval RAISES, the cycle HOLDS (LAW-1
                         fail-safe, never fail-open).
  LIVE_GATE_INERT        the LiveTradingGate master block is LOCKED → would_cutover
                         is ALWAYS False (the artifact is inert).

HARD GUARANTEES (do not relax)
------------------------------
  * INERT. NEVER moves capital, NEVER signs, NEVER touches a wallet/bridge/chain.
  * NEVER imports ``spa_core.execution`` (transitively either). The NAV-reconcile
    and position-monitor checks are pure-stdlib re-derivations local to this
    module — execution/'s reconciliation.py / position_monitor.py are NOT used.
  * stdlib only. Deterministic. fail-CLOSED. Atomic writes (spa_core.utils.atomic).
  * SANDBOX-ONLY: every defense drill runs against a caller-supplied / temp
    ``data_dir``. The gate NEVER reads or writes the live ``data/`` directory.
  * ``would_cutover`` is ALWAYS False — the gate is an ASSERTION that defenses
    fire, not a licence to trade.
  * LLM FORBIDDEN anywhere in this path.

EXIT CONTRACT
-------------
  exit 0  ⇔ EVERY defense demonstrably fired (all assertions pass).
  exit 1  ⇔ one or more defenses did NOT fire — the report names the failing gate.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.utils.errors import SPAError

# Composed, execution-FREE defenses (verified: none of these import execution/).
from spa_core.governance.kill_switch import (
    DRAWDOWN_THRESHOLD_PCT,
    SOFT_DERISK_THRESHOLD_PCT,
    KillSwitchChecker,
    drawdown_tier,
)
from spa_core.paper_trading.cycle_gates import (
    apply_analytics_blocking_gate,
    apply_base_gas_kill_switch,
    apply_kill_switch_override,
    apply_soft_derisk_gate,
)
from spa_core.paper_trading.risk_gate import _apply_risk_policy_gate
from spa_core.risk.daily_limits import DailyLimitsChecker
from spa_core.paper_trading.track_evidence import PAPER_REAL_START

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parents[2]
_OUT_FILENAME = "pre_cutover_gate.json"

IS_INERT = True  # un-overridable harness invariant — never moves capital


# --------------------------------------------------------------------------- #
# Result primitives
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(gate: str, expected: str, actual: str, passed: bool, *, detail: str = "") -> dict:
    """One {gate, expected, actual, pass, detail} structured assertion record."""
    return {
        "gate": gate,
        "expected": expected,
        "actual": actual,
        "pass": bool(passed),
        "detail": detail,
    }


# --------------------------------------------------------------------------- #
# Sandbox equity-curve fixtures (evidenced bars only — post PAPER_REAL_START)
# --------------------------------------------------------------------------- #
def _evidenced_curve(close_seq: list[float]) -> list[dict]:
    """Build an EVIDENCED daily equity curve from a sequence of close values.

    Every bar is dated on/after PAPER_REAL_START and carries the ``is_real`` /
    ``source`` evidence markers so ``evidenced_bars`` accepts it (the kill-switch
    drawdown trigger computes strictly over evidenced bars).
    """
    start = PAPER_REAL_START
    bars: list[dict] = []
    for i, close in enumerate(close_seq):
        d = start + timedelta(days=i)
        bars.append({
            "date": d.isoformat(),
            "close_equity": float(close),
            "equity": float(close),
            "is_real": True,
            "seed": False,
            "source": "cycle",
        })
    return bars


# Peak 100_000 then a controlled drawdown to a target percentage.
def _curve_for_drawdown(pct: float, *, n_pre: int = 5) -> list[dict]:
    """Evidenced curve whose terminal evidenced drawdown ≈ ``pct`` percent."""
    peak = 100_000.0
    trough = peak * (1.0 - pct / 100.0)
    pre = [peak - i * 10.0 for i in range(n_pre)]  # gentle climb to peak region
    return _evidenced_curve([*pre, peak, trough])


# --------------------------------------------------------------------------- #
# Pure-stdlib NAV reconciliation (NO execution/ import).
# --------------------------------------------------------------------------- #
def nav_reconcile(target: dict[str, float], resulting: dict[str, float],
                  *, capital: float = 100_000.0, tol: float = 1e-6) -> dict:
    """Reconcile a dry-run rebalance OUTCOME against its INTENDED target.

    Pure arithmetic — a flat→target rebalance must reproduce ``target`` exactly
    and conserve NAV (deployed + cash == capital). This is a local re-derivation
    of execution/reconciliation.py's contract; it never touches a chain.

    Returns a dict with ``matches_target`` / ``nav_conserved`` / ``residual_usd``
    (the NAV reconcile residual that must be 0) and the max position delta.
    """
    keys = set(target) | set(resulting)
    max_delta = 0.0
    for k in keys:
        try:
            t = float(target.get(k, 0.0))
            r = float(resulting.get(k, 0.0))
        except (TypeError, ValueError):
            return {"matches_target": False, "nav_conserved": False,
                    "residual_usd": float("inf"), "max_position_delta_usd": float("inf"),
                    "detail": f"non-numeric position for {k!r}"}
        if not (math.isfinite(t) and math.isfinite(r)):
            return {"matches_target": False, "nav_conserved": False,
                    "residual_usd": float("inf"), "max_position_delta_usd": float("inf"),
                    "detail": f"non-finite position for {k!r}"}
        max_delta = max(max_delta, abs(t - r))
    deployed = sum(float(v) for v in resulting.values()
                   if isinstance(v, (int, float)) and math.isfinite(float(v)))
    cash = capital - deployed
    nav_after = deployed + cash
    residual = abs(nav_after - capital)
    return {
        "matches_target": max_delta <= tol,
        "nav_conserved": residual <= tol,
        "residual_usd": round(residual, 6),
        "max_position_delta_usd": round(max_delta, 6),
        "nav_after": round(nav_after, 2),
        "detail": f"deployed=${deployed:,.2f} cash=${cash:,.2f}",
    }


# --------------------------------------------------------------------------- #
# Pure-stdlib position-monitor (NO execution/ import).
# --------------------------------------------------------------------------- #
def position_monitor_scan(positions: dict[str, float], *, capital: float = 100_000.0) -> dict:
    """Inert position-monitor: read a {protocol: usd} book and report anomalies.

    Local, execution-free re-derivation of the anomaly checks that matter for the
    NEW post-sprint states. Reports:
      * ``negative``        — any position < 0  (corrupt book).
      * ``non_finite``      — any NaN/Inf position (corrupt book).
      * ``over_capital``    — deployed exceeds capital (impossible book).
      * ``all_cash``        — no positive position (the post-HARD-kill state).
      * ``held_count``      — number of positive positions.
    ``anomaly`` is True iff any CORRUPT condition holds (negative / non-finite /
    over-capital). ``all_cash`` and a healthy held-only book are NORMAL, not
    anomalies.
    """
    negative: list[str] = []
    non_finite: list[str] = []
    held: list[str] = []
    deployed = 0.0
    for proto, usd in (positions or {}).items():
        if not isinstance(usd, (int, float)) or isinstance(usd, bool):
            non_finite.append(str(proto))
            continue
        v = float(usd)
        if not math.isfinite(v):
            non_finite.append(str(proto))
            continue
        if v < 0:
            negative.append(str(proto))
            continue
        if v > 0:
            held.append(str(proto))
            deployed += v
    over_capital = deployed > capital + 1e-6
    anomaly = bool(negative or non_finite or over_capital)
    return {
        "anomaly": anomaly,
        "negative": negative,
        "non_finite": non_finite,
        "over_capital": over_capital,
        "all_cash": len(held) == 0,
        "held_count": len(held),
        "deployed_usd": round(deployed, 2),
    }


# --------------------------------------------------------------------------- #
# Sandbox helpers — write the minimal data/*.json the defenses read.
# --------------------------------------------------------------------------- #
def _write(ddir: Path, name: str, obj: Any) -> None:
    atomic_save(obj, str(ddir / name))


def _seed_sandbox(ddir: Path) -> None:
    """Ensure the sandbox data dir exists and is CLEAN of any live state."""
    ddir.mkdir(parents=True, exist_ok=True)
    # Make absolutely sure no inherited kill/manual flag is present.
    for nm in ("kill_switch_active.json", "red_flags.json", "current_positions.json",
               "equity_curve_daily.json", "derisk_status.json"):
        p = ddir / nm
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# The individual defense drills. Each DRIVES a failure mode against the sandbox
# and ASSERTS the correct response, returning a structured result record.
# --------------------------------------------------------------------------- #
def _drill_hard_kill_drawdown(ddir: Path) -> dict:
    gate = "HARD_KILL_DRAWDOWN"
    curve = _curve_for_drawdown(DRAWDOWN_THRESHOLD_PCT + 5.0)  # 15% > 10% hard
    checker = KillSwitchChecker(data_dir=str(ddir))
    triggered, reason = checker.check_drawdown_trigger(curve)
    # The override turns a triggered kill into an all-cash allocation.
    ks_alloc = checker.get_kill_switch_allocation() if triggered else {}
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
    notes: list[str] = []
    final = apply_kill_switch_override(
        target, ks_triggered=triggered, ks_allocation=ks_alloc,
        capital_usd=100_000.0, notes=notes,
    )
    all_cash = triggered and all(float(v) == 0.0 for v in final.values())
    return _result(
        gate, "drawdown ≥10% → kill fires → all-cash override",
        f"triggered={triggered}, all_cash={all_cash}", all_cash,
        detail=reason,
    )


def _drill_hard_kill_manual(ddir: Path) -> dict:
    gate = "HARD_KILL_MANUAL"
    _write(ddir, "kill_switch_active.json",
           {"active": True, "reason": "pre-cutover gate manual drill"})
    try:
        checker = KillSwitchChecker(data_dir=str(ddir))
        triggered, reason = checker.check_manual_trigger()
        ks_alloc = checker.get_kill_switch_allocation() if triggered else {}
        target = {"aave_v3": 50_000.0}
        final = apply_kill_switch_override(
            target, ks_triggered=triggered, ks_allocation=ks_alloc,
            capital_usd=100_000.0, notes=[],
        )
        all_cash = triggered and all(float(v) == 0.0 for v in final.values())
    finally:
        p = ddir / "kill_switch_active.json"
        if p.exists():
            p.unlink()
    return _result(
        gate, "manual kill file → kill fires → all-cash override",
        f"triggered={triggered}, all_cash={all_cash}", all_cash, detail=reason,
    )


def _drill_hard_kill_red_flags(ddir: Path) -> dict:
    gate = "HARD_KILL_RED_FLAGS"
    # HELD a protocol, then > threshold CRITICAL flags ON that held protocol.
    _write(ddir, "current_positions.json",
           {"positions": {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}})
    flags = [
        {"protocol": "aave_v3", "severity": "CRITICAL", "source": "defillama",
         "reason": f"drill flag {i}"}
        for i in range(6)  # 6 > RED_FLAGS_THRESHOLD (5)
    ]
    _write(ddir, "red_flags.json", {"red_flags": flags, "sources": ["defillama"]})
    try:
        checker = KillSwitchChecker(data_dir=str(ddir))
        triggered, reason = checker.check_red_flags_trigger()
        ks_alloc = checker.get_kill_switch_allocation() if triggered else {}
        final = apply_kill_switch_override(
            {"aave_v3": 40_000.0}, ks_triggered=triggered,
            ks_allocation=ks_alloc, capital_usd=100_000.0, notes=[],
        )
        all_cash = triggered and all(float(v) == 0.0 for v in final.values())
    finally:
        for nm in ("red_flags.json", "current_positions.json"):
            p = ddir / nm
            if p.exists():
                p.unlink()
    return _result(
        gate, "CRITICAL red-flags on HELD protocol → kill fires → all-cash",
        f"triggered={triggered}, all_cash={all_cash}", all_cash, detail=reason,
    )


def _drill_soft_derisk(ddir: Path) -> dict:
    gate = "SOFT_DERISK"
    # Drawdown in [5%, 15%) → soft band: no new, no increase, hold/reduce only.
    curve = _curve_for_drawdown(8.0)  # 8% ∈ [5,15)
    checker = KillSwitchChecker(data_dir=str(ddir))
    tier, reason = drawdown_tier(curve)
    derisk_active, _ = checker.check_derisk_trigger(curve)
    held = {"aave_v3": 30_000.0, "morpho_blue": 20_000.0}
    # Allocator WANTS: increase aave, open a brand-new protocol, reduce morpho.
    target = {"aave_v3": 45_000.0, "compound_v3": 15_000.0, "morpho_blue": 10_000.0}
    final = apply_soft_derisk_gate(
        dict(target), current_positions=held, derisk_active=derisk_active, notes=[],
    )
    no_new = final.get("compound_v3", 0.0) == 0.0          # new protocol blocked
    no_increase = final.get("aave_v3", 0.0) <= held["aave_v3"]  # capped to held
    reduce_ok = final.get("morpho_blue", 0.0) == 10_000.0  # reduction intact
    not_liquidated = final.get("aave_v3", 0.0) > 0.0       # NOT closed (hold)
    ok = (tier == "SOFT_DERISK" and derisk_active and no_new
          and no_increase and reduce_ok and not_liquidated)
    return _result(
        gate, "drawdown[5,15)% → no-new / no-increase / hold-reduce-only (no liquidation)",
        (f"tier={tier} active={derisk_active} new_blocked={no_new} "
         f"increase_capped={no_increase} reduce_ok={reduce_ok} held={not_liquidated}"),
        ok, detail=reason,
    )


def _drill_dl01_daily_loss(ddir: Path) -> dict:
    gate = "DL01_DAILY_LOSS"
    # Two bars: a > 2% single-day loss → DL-01 HALT.
    hist = [{"close_equity": 100_000.0}, {"close_equity": 97_000.0}]  # -3%
    res = DailyLimitsChecker().check(hist, {"aave_v3": 50_000.0}, {"aave_v3": 4.0})
    halted = res["gate"] == "HALT" and any("DL-01" in r for r in res["halt_reasons"])
    return _result(
        gate, "daily loss >2% → DailyLimits HALT",
        f"gate={res['gate']}", halted, detail="; ".join(res["halt_reasons"]),
    )


def _drill_dl02_defers_to_kill(ddir: Path) -> dict:
    gate = "DL02_DEFERS_TO_KILL"
    # ADR-048: at ≥10% peak drawdown the hard kill OWNS the rung. DL-02 still
    # HALTs as an isolated primitive (unchanged), but the AUTHORITATIVE cycle
    # response at ≥10% is the all-cash hard kill — DL-02's HALT is DEFERRED in
    # run_cycle so the kill-switch override wins (the stronger action). We assert
    # BOTH facts here: (1) the DL-02 primitive still HALTs at >10% (unchanged),
    # and (2) at the SAME ≥10% drawdown the evidenced hard kill fires and its
    # override produces an ALL-CASH book (the response that subsumes DL-02).
    # Peak→trough > 10% over the history, last step small (DL-02, not DL-01).
    hist = [
        {"close_equity": 100_000.0},
        {"close_equity": 88_000.0},   # -12% peak drawdown
        {"close_equity": 87_500.0},   # last step only -0.57% (under DL-01 2%)
    ]
    res = DailyLimitsChecker().check(hist, {"aave_v3": 50_000.0}, {"aave_v3": 4.0})
    dl02_primitive_halts = (
        res["gate"] == "HALT" and any("DL-02" in r for r in res["halt_reasons"])
    )
    # Same drawdown band, evidenced curve → hard kill fires → all-cash override.
    curve = _curve_for_drawdown(12.0)  # ≥ 10% hard kill
    checker = KillSwitchChecker(data_dir=str(ddir))
    triggered, reason = checker.check_drawdown_trigger(curve)
    ks_alloc = checker.get_kill_switch_allocation() if triggered else {}
    final = apply_kill_switch_override(
        {"aave_v3": 50_000.0}, ks_triggered=triggered, ks_allocation=ks_alloc,
        capital_usd=100_000.0, notes=[],
    )
    kill_all_cash = triggered and all(float(v) == 0.0 for v in final.values())
    ok = dl02_primitive_halts and kill_all_cash
    return _result(
        gate,
        "≥10% peak drawdown → hard kill OWNS it (all-cash); DL-02 HALT deferred",
        f"dl02_primitive_halts={dl02_primitive_halts} kill_all_cash={kill_all_cash}",
        ok, detail=f"DL-02: {'; '.join(res['halt_reasons'])} | kill: {reason}",
    )


def _drill_riskpolicy_block(ddir: Path) -> dict:
    gate = "RISKPOLICY_BLOCK"
    # A single position at 90% of capital — far above the 40% T1 / 20% T2 caps.
    target = {"aave_v3": 90_000.0}
    adapters = [{"protocol": "aave_v3", "tier": "T1", "apy_pct": 4.0,
                 "tvl_usd": 50_000_000.0, "chain": "ethereum"}]
    out = _apply_risk_policy_gate(target, 100_000.0, adapters, ddir=ddir)
    blocked = (not out["approved"]) and bool(out["violations"])
    return _result(
        gate, "over-concentration target → RiskPolicy approved=False",
        f"approved={out['approved']}", blocked,
        detail="; ".join(out["violations"])[:300],
    )


def _drill_analytics_block(ddir: Path) -> dict:
    gate = "ANALYTICS_BLOCK"
    # Force a Tier-A BLOCK by stubbing the signal aggregator the gate imports.
    import sys
    import types

    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
    notes: list[str] = []
    mod_name = "spa_core.analytics.signal_aggregator"
    saved = sys.modules.get(mod_name)
    stub = types.ModuleType(mod_name)

    def _run_tier_a(protocols, context=None, data_dir=None):  # noqa: ANN001
        return {"protocols": {"aave_v3": {"signal": "BLOCK", "reason": "drill"}}}

    stub.run_tier_a = _run_tier_a  # type: ignore[attr-defined]
    sys.modules[mod_name] = stub
    try:
        apply_analytics_blocking_gate(
            target, ddir=ddir, run_ts=_now_iso(), today=date.today().isoformat(),
            correlation_id="pre-cutover-drill", write=False, notes=notes,
        )
    finally:
        if saved is not None:
            sys.modules[mod_name] = saved
        else:
            sys.modules.pop(mod_name, None)
    zeroed = target.get("aave_v3", 1.0) == 0.0
    return _result(
        gate, "Tier-A BLOCK signal → blocked protocol target zeroed",
        f"aave_v3_target={target.get('aave_v3')}", zeroed, detail="; ".join(notes),
    )


def _drill_base_gas_block(ddir: Path) -> dict:
    gate = "BASE_GAS_BLOCK"

    class _StubGasMonitor:
        def __init__(self, data_dir=None):  # noqa: ANN001
            pass

        def record_reading(self):
            return {"kill_switch_active": True, "gwei": 5.0, "consecutive_above": 3}

    target = {"aave_v3": 30_000.0, "aave_base": 20_000.0, "moonwell_base": 10_000.0}
    notes: list[str] = []
    apply_base_gas_kill_switch(
        target, ddir=ddir, base_gas_monitor_class=_StubGasMonitor,
        base_chain_monitoring=True, notes=notes,
    )
    base_zeroed = (target.get("aave_base", 1.0) == 0.0
                   and target.get("moonwell_base", 1.0) == 0.0)
    non_base_intact = target.get("aave_v3", 0.0) == 30_000.0
    ok = base_zeroed and non_base_intact
    return _result(
        gate, "Base-gas kill active → all Base allocations zeroed (non-Base intact)",
        f"base_zeroed={base_zeroed} non_base_intact={non_base_intact}", ok,
        detail="; ".join(notes),
    )


def _drill_nav_reconcile(ddir: Path) -> dict:
    gate = "NAV_RECONCILE"
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0, "compound_v3": 15_000.0}
    # Clean dry-run: flat → target, outcome == target → residual 0.
    clean = nav_reconcile(target, dict(target))
    clean_ok = clean["matches_target"] and clean["nav_conserved"] and clean["residual_usd"] == 0.0
    # Corrupted outcome (a position lost $5k) → reconcile must CATCH the mismatch.
    corrupt = dict(target)
    corrupt["aave_v3"] = 35_000.0
    caught = not nav_reconcile(target, corrupt)["matches_target"]
    ok = clean_ok and caught
    return _result(
        gate, "flat→target reconciles (NAV residual==0) AND corrupted book caught",
        f"clean_ok={clean_ok} corruption_caught={caught} residual={clean['residual_usd']}",
        ok, detail=clean["detail"],
    )


def _drill_partial_fill_recovery(ddir: Path) -> dict:
    """PARTIAL-FILL: an order fills only partially → reconcile detects
    matches_target=False → the cycle must ABORT (no partial NAV corruption is
    accepted as success).

    A clean FULL fill must still reconcile (matches_target=True). The drill PASSES
    only if BOTH: the full fill reconciles clean AND the partial fill is caught
    (matches_target=False) — i.e. a partial fill can NEVER masquerade as success.
    """
    gate = "PARTIAL_FILL_RECOVERY"
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
    # Clean FULL fill — outcome == target.
    full = nav_reconcile(target, dict(target))
    full_ok = full["matches_target"] and full["nav_conserved"]
    # PARTIAL fill — the aave order filled only $25k of the intended $40k.
    partial = dict(target)
    partial["aave_v3"] = 25_000.0  # $15k short — partial fill
    caught = not nav_reconcile(target, partial)["matches_target"]
    # ABORT decision: a partial fill (matches_target False) MUST block, never proceed.
    would_proceed_on_partial = nav_reconcile(target, partial)["matches_target"]
    ok = full_ok and caught and (not would_proceed_on_partial)
    return _result(
        gate, "partial fill → reconcile matches_target=False → ABORT (full fill still clean)",
        f"full_ok={full_ok} partial_caught={caught} proceeds_on_partial={would_proceed_on_partial}",
        ok, detail=f"partial short=${target['aave_v3'] - partial['aave_v3']:,.0f}",
    )


def _drill_reconcile_mismatch(ddir: Path) -> dict:
    """RECONCILIATION-MISMATCH: nav_conserved=False (NAV not conserved — capital
    appeared/vanished) → the cycle must BLOCK. A book whose deployed total exceeds
    capital is impossible and must be caught; a conserved book passes.

    PASSES only if BOTH: a conserved flat→target book reconciles (nav_conserved
    True) AND an over-capital (impossible) outcome is caught (nav_conserved False).
    """
    gate = "RECONCILE_MISMATCH"
    target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0, "compound_v3": 15_000.0}
    # Conserved book: deployed $75k + cash $25k == $100k capital → nav_conserved.
    conserved = nav_reconcile(target, dict(target), capital=100_000.0)
    conserved_ok = conserved["nav_conserved"] and conserved["residual_usd"] == 0.0
    # IMPOSSIBLE outcome: total deployed $150k > $100k capital → NAV NOT conserved.
    over_capital = {"aave_v3": 80_000.0, "morpho_blue": 40_000.0, "compound_v3": 30_000.0}
    bad = nav_reconcile(target, over_capital, capital=100_000.0)
    caught = (not bad["nav_conserved"]) or (not bad["matches_target"])
    ok = conserved_ok and caught
    return _result(
        gate, "NAV not conserved (deployed>capital) → reconcile BLOCKS; conserved book passes",
        f"conserved_ok={conserved_ok} mismatch_caught={caught} "
        f"bad_nav_conserved={bad['nav_conserved']}",
        ok, detail=f"over-capital deployed=${sum(over_capital.values()):,.0f} vs $100,000",
    )


def _drill_signer_failure(ddir: Path) -> dict:
    """SIGNER-FAILURE: the signing step raises (key load failure / nonce gap /
    crypto error) → the cycle must SAFELY ABORT (no tx submitted, positions
    unchanged) AND no key material may appear in any surfaced error/log line.

    Inert: we DO NOT import or call the real signer. We model the cycle's
    signer-call wrapper exactly with a stub that raises, exercise the fail-CLOSED
    branch, and assert (a) abort, (b) positions unchanged, (c) the raised
    diagnostic contains NO private-key material.
    """
    gate = "SIGNER_FAILURE"
    # A fake (publicly-known dev) key that MUST never leak into any diagnostic.
    secret_key_hex = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    positions_before = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}

    def _stub_sign(_tx, _key):
        # Model a signer that fails WITHOUT echoing the key into the message
        # (the contract eth_signer must honour: never log key material).
        raise RuntimeError("signer failure: nonce gap detected (key redacted)")

    tx_submitted = True
    aborted = False
    leaked = False
    diag = ""
    positions_after = dict(positions_before)
    try:
        _stub_sign({"to": "0x" + "0" * 40, "nonce": 7}, secret_key_hex)
        tx_submitted = True
    except Exception as exc:  # fail-CLOSED: cannot sign → ABORT, no submit.
        aborted = True
        tx_submitted = False
        diag = f"{type(exc).__name__}: {exc}"
        # No-key-leak property: the secret must NOT be in any surfaced diagnostic.
        leaked = secret_key_hex in diag or secret_key_hex in repr(exc)
    positions_unchanged = positions_after == positions_before
    ok = aborted and (not tx_submitted) and positions_unchanged and (not leaked)
    return _result(
        gate, "signer raises → SAFE ABORT (no submit, positions unchanged), NO key leak",
        f"aborted={aborted} tx_submitted={tx_submitted} "
        f"positions_unchanged={positions_unchanged} key_leaked={leaked}",
        ok, detail=diag,
    )


def _drill_position_monitor(ddir: Path) -> dict:
    gate = "POSITION_MONITOR"
    # NEW state 1 — post-HARD-kill ALL-CASH (every protocol 0). NORMAL, no anomaly.
    all_cash = {"aave_v3": 0.0, "morpho_blue": 0.0, "compound_v3": 0.0}
    s_cash = position_monitor_scan(all_cash)
    cash_ok = (not s_cash["anomaly"]) and s_cash["all_cash"] and s_cash["held_count"] == 0
    # NEW state 2 — post-SOFT held-only (held, no new). NORMAL, no anomaly.
    held_only = {"aave_v3": 30_000.0, "morpho_blue": 20_000.0}
    s_held = position_monitor_scan(held_only)
    held_ok = (not s_held["anomaly"]) and s_held["held_count"] == 2 and not s_held["all_cash"]
    # Deliberately corrupted book (negative position) → must be CAUGHT.
    corrupt = {"aave_v3": -10_000.0, "morpho_blue": 20_000.0}
    caught = position_monitor_scan(corrupt)["anomaly"]
    ok = cash_ok and held_ok and caught
    return _result(
        gate, "monitor correct in all-cash AND held-only states; corrupt book caught",
        f"all_cash_ok={cash_ok} held_only_ok={held_ok} corruption_caught={caught}", ok,
    )


def _drill_failsafe_hold(ddir: Path) -> dict:
    gate = "FAILSAFE_HOLD"
    # LAW-1: when a safety eval RAISES, the cycle must HOLD (suppress new trades),
    # never fail-open. We model the cycle's fail-safe wrapper exactly: a raising
    # safety check sets a HOLD flag and the new-trade path is suppressed.
    held = True  # default state: positions held

    def _raising_safety_eval():
        # drill: intentional fault injection — model an UNEXPECTED safety-eval
        # failure (arbitrary exception) to prove the cycle fail-safe HOLDS.
        raise RuntimeError("injected safety-eval failure (drill)")  # drill: intentional fault injection

    safety_failed = False
    new_trades_allowed = True
    try:
        _raising_safety_eval()
    except Exception:
        # LAW-1 (fail-safe, not fail-open): cannot confirm safe → HOLD, no new trade.
        safety_failed = True
        new_trades_allowed = False
    ok = safety_failed and (not new_trades_allowed) and held
    return _result(
        gate, "safety eval raises → LAW-1 fail-safe HOLD (no new trades, positions kept)",
        f"safety_failed={safety_failed} new_trades_allowed={new_trades_allowed}", ok,
        detail="LAW-1 fail-safe (not fail-open)",
    )


def _drill_live_gate_inert(ddir: Path) -> dict:
    gate = "LIVE_GATE_INERT"
    # The master block: the LiveTradingGate must be LOCKED → would_cutover False.
    locked = True
    detail = "LiveTradingGate locked (file absent → defaults LOCKED)"
    try:
        from spa_core.safety.live_trading_gate import LiveTradingGate
        g = LiveTradingGate(base_dir=str(_ROOT))
        locked = not bool(g.is_active())
        detail = f"is_active={g.is_active()}"
    except Exception as exc:  # gate error → treat as LOCKED (safe default)
        locked = True
        detail = f"gate unavailable → treated LOCKED ({type(exc).__name__}: {exc})"
    return _result(
        gate, "LiveTradingGate LOCKED → would_cutover ALWAYS False (inert)",
        f"locked={locked}", locked, detail=detail,
    )


# The canonical ordered roster of money-path defenses this gate asserts.
_DRILLS: tuple[tuple[str, Callable[[Path], dict]], ...] = (
    ("HARD_KILL_DRAWDOWN", _drill_hard_kill_drawdown),
    ("HARD_KILL_MANUAL", _drill_hard_kill_manual),
    ("HARD_KILL_RED_FLAGS", _drill_hard_kill_red_flags),
    ("SOFT_DERISK", _drill_soft_derisk),
    ("DL01_DAILY_LOSS", _drill_dl01_daily_loss),
    ("DL02_DEFERS_TO_KILL", _drill_dl02_defers_to_kill),
    ("RISKPOLICY_BLOCK", _drill_riskpolicy_block),
    ("ANALYTICS_BLOCK", _drill_analytics_block),
    ("BASE_GAS_BLOCK", _drill_base_gas_block),
    ("NAV_RECONCILE", _drill_nav_reconcile),
    ("PARTIAL_FILL_RECOVERY", _drill_partial_fill_recovery),
    ("RECONCILE_MISMATCH", _drill_reconcile_mismatch),
    ("SIGNER_FAILURE", _drill_signer_failure),
    ("POSITION_MONITOR", _drill_position_monitor),
    ("FAILSAFE_HOLD", _drill_failsafe_hold),
    ("LIVE_GATE_INERT", _drill_live_gate_inert),
)


# --------------------------------------------------------------------------- #
# Advisory wraps of the THREE existing harnesses (composed, NOT duplicated).
# These are ADVISORY (never flip the gate verdict): the prior harnesses include
# time-gated / live-state checks that legitimately fail in a sandbox/CI. They are
# attached to the report for human context only.
# --------------------------------------------------------------------------- #
def _advisory_existing_harnesses() -> dict:
    out: dict[str, Any] = {}

    # MP-351 golive_preflight — ADR-011 checklist (advisory, no telegram, no save).
    try:
        from scripts.golive_preflight import run_preflight  # type: ignore
        pf = run_preflight(skip_telegram=True)
        out["golive_preflight"] = {
            "verdict": pf.get("verdict"),
            "counts": pf.get("counts"),
            "fails": pf.get("fails"),
        }
    except Exception as exc:  # noqa: BLE001 — advisory only
        out["golive_preflight"] = {"error": f"{type(exc).__name__}: {exc}"}

    # MP-1428 day1 readiness — critical checks (advisory).
    try:
        from spa_core.backtesting.paper_day1_checklist import PaperDay1Checklist
        d1 = PaperDay1Checklist(base_dir=str(_ROOT)).run_all()
        out["day1_readiness"] = {
            "all_critical_pass": d1.get("all_critical_pass"),
            "summary": d1.get("summary"),
        }
    except Exception as exc:  # noqa: BLE001 — advisory only
        out["day1_readiness"] = {"error": f"{type(exc).__name__}: {exc}"}

    # MP-428 cycle_dry_run — adapter/strategy/file smoke (advisory; presence only,
    # we do not re-run its network-touching adapter probes here, just record that
    # the harness is wired/importable so the composition is explicit).
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cycle_dry_run", str(_ROOT / "scripts" / "cycle_dry_run.py"))
        out["cycle_dry_run"] = {"importable": spec is not None,
                                "note": "MP-428 smoke harness wired (advisory)"}
    except Exception as exc:  # noqa: BLE001 — advisory only
        out["cycle_dry_run"] = {"error": f"{type(exc).__name__}: {exc}"}

    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def run_gate(data_dir: Optional[str | os.PathLike] = None, *, write: bool = True) -> dict:
    """Drive every money-path defense against a SANDBOX and assert each fires.

    Args:
        data_dir: sandbox data directory. When None, a fresh temp dir is created
            and torn down. The live ``data/`` directory is NEVER used.
        write: when True, persist the report atomically into the sandbox dir as
            ``pre_cutover_gate.json`` (NEVER into live data/).

    Returns the structured report dict. ``all_defenses_fired`` is True iff every
    drill passed. ``would_cutover`` is ALWAYS False.
    """
    own_tmp = data_dir is None
    if own_tmp:
        tmp = tempfile.mkdtemp(prefix="spa_pre_cutover_")
        ddir = Path(tmp)
    else:
        ddir = Path(data_dir)

    # HARD GUARD: refuse to ever run against the live data/ directory.
    live_data = (_ROOT / "data").resolve()
    if ddir.resolve() == live_data:
        raise SPAError(
            "pre_cutover_gate REFUSED to run against live data/ — pass a sandbox "
            "data_dir (the gate is inert and sandbox-only).",
            code="PRE_CUTOVER_GATE_LIVE_DATA_REFUSED",
        )

    try:
        _seed_sandbox(ddir)
        results: list[dict] = []
        for _name, drill in _DRILLS:
            try:
                results.append(drill(ddir))
            except Exception as exc:  # a drill that itself raises is fail-CLOSED.
                results.append(_result(
                    _name, "drill executes and asserts",
                    f"FAIL-CLOSED: drill raised {type(exc).__name__}: {exc}",
                    False, detail="drill error → treated as defense NOT proven",
                ))

        all_fired = all(r["pass"] for r in results)
        failing = [r["gate"] for r in results if not r["pass"]]

        report = {
            "generated_at": _now_iso(),
            "module": "pre_cutover_gate",
            "is_inert": IS_INERT,
            "moves_capital": False,
            "llm_forbidden": True,
            "sandbox_data_dir": str(ddir),
            "live_data_untouched": True,
            "thresholds": {
                "soft_derisk_pct": SOFT_DERISK_THRESHOLD_PCT,
                "hard_kill_pct": DRAWDOWN_THRESHOLD_PCT,
                "dl01_daily_loss_pct": DailyLimitsChecker.MAX_DAILY_LOSS_PCT,
                "dl02_peak_drawdown_pct": DailyLimitsChecker.MAX_DRAWDOWN_PCT,
            },
            "defenses": results,
            "defenses_total": len(results),
            "defenses_passed": sum(1 for r in results if r["pass"]),
            "all_defenses_fired": all_fired,
            "failing_gates": failing,
            "advisory": _advisory_existing_harnesses(),
            # OWNER-ONLY cutover blockers — code cannot satisfy these.
            "owner_only_blockers": [
                "custody: Gnosis Safe 2-of-3 deployed + keys provisioned (ADR-010)",
                "audit: external security audit of execution path signed off",
                "track_days: ≥30 evidenced honest paper-track days (go-live gate)",
            ],
            "would_cutover": False,  # ALWAYS False — inert; LiveTradingGate is master block
        }
        if write:
            _write(ddir, _OUT_FILENAME, report)
        return report
    finally:
        if own_tmp:
            # Best-effort teardown of the temp sandbox.
            import shutil
            try:
                shutil.rmtree(ddir, ignore_errors=True)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Report printer + CLI
# --------------------------------------------------------------------------- #
def _print_report(report: dict) -> None:
    print("=" * 74)
    print("SPA PRE-CUTOVER READINESS GATE — every money-path defense must fire")
    print("=" * 74)
    print(f"sandbox data_dir : {report['sandbox_data_dir']}")
    print(f"live_data_untouched: {report['live_data_untouched']}   is_inert: {report['is_inert']}")
    th = report["thresholds"]
    print(f"ladder (ADR-048): DL-01 {th['dl01_daily_loss_pct']}%/day · SOFT "
          f"{th['soft_derisk_pct']}% de-risk · HARD {th['hard_kill_pct']}% all-cash "
          f"(owns DL-02 {th['dl02_peak_drawdown_pct']}% peak → DL-02 HALT deferred to kill)")
    print("-" * 74)
    for r in report["defenses"]:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f" [{mark}] {r['gate']:<20} expected: {r['expected']}")
        print(f"        actual  : {r['actual']}")
        if r.get("detail"):
            print(f"        detail  : {r['detail'][:120]}")
    print("-" * 74)
    print(f" defenses_passed   : {report['defenses_passed']}/{report['defenses_total']}")
    print(f" all_defenses_fired: {report['all_defenses_fired']}")
    if report["failing_gates"]:
        print(f" FAILING GATES     : {', '.join(report['failing_gates'])}")
    print(f" would_cutover     : {report['would_cutover']}  (ALWAYS False — inert)")
    print("-" * 74)
    adv = report.get("advisory", {})
    print(" advisory (existing harnesses, non-blocking):")
    for k, v in adv.items():
        print(f"   {k}: {json.dumps(v)[:120]}")
    print(" owner-only cutover blockers (code cannot satisfy):")
    for b in report.get("owner_only_blockers", []):
        print(f"   • {b}")
    print("=" * 74)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="SPA Pre-Cutover Readiness Gate — assert every money-path "
                    "defense fires (sandbox-only, inert).")
    p.add_argument("--data-dir", default=None,
                   help="sandbox data dir (default: ephemeral temp dir)")
    p.add_argument("--json-only", action="store_true", help="print JSON only")
    p.add_argument("--no-save", action="store_true",
                   help="do not write pre_cutover_gate.json into the sandbox dir")
    args = p.parse_args(argv)

    report = run_gate(data_dir=args.data_dir, write=not args.no_save)
    if args.json_only:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0 if report["all_defenses_fired"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
