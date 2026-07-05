#!/usr/bin/env python3
"""Cleanly-liftable allocation-mutating gate stages (N12 / P4-5 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.run_cycle``: the three gate stages that
transform the ``target_usd`` allocation in place *without* participating in
``run_cycle``'s early-return control flow or its ``_mark_safety_failure``
``nonlocal`` closure. Each is a self-contained ``(target_usd, …) -> None`` (or
small return) helper whose body is byte-identical to the original inline block —
no behaviour change. ``cycle_runner`` calls these in the same order, between the
same surrounding stages, so the observable cycle output is unchanged.

The entangled stages — DailyLimits HALT, Emergency Breakers, the kill-switch
*check*, and the RiskPolicy-gate-error fail-safe — are LEFT inline in
``run_cycle`` because they early-return a ``CycleResult`` and/or mutate the
``_safety_failed`` closure; lifting them would require restructuring the HALT /
breaker / kill-switch ordering, which is out of scope for a behaviour-preserving
move (correctness >> LOC).

LLM FORBIDDEN — deterministic. stdlib only. Each block is independently
fail-safe (fail-open / WARNING) exactly as before.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spa_core.paper_trading._cycle_io import _atomic_write_json, _read_json

log = logging.getLogger("spa.cycle_runner")


def apply_analytics_blocking_gate(
    target_usd: dict[str, float],
    *,
    ddir: Path,
    run_ts: str,
    today: str,
    correlation_id: str,
    write: bool,
    notes: list[str],
) -> None:
    """Step 2c-pre (ADR-031 / MP-1146): Analytics Blocking Gate.

    Runs AFTER the allocator and BEFORE the RiskPolicy gate. Reads the Tier-A
    blocking signals; any protocol flagged BLOCK has its target_usd zeroed and
    the freed capital redistributed proportionally to the remaining (allowed)
    protocols. Fail-open: any exception → WARNING + note, no blocking applied.

    Mutates ``target_usd`` and ``notes`` in place (byte-identical to the original
    inline block in ``run_cycle``).
    """
    try:
        from spa_core.analytics.signal_aggregator import run_tier_a as _analytics_tier_a
        _blk = _analytics_tier_a(
            list(target_usd.keys()),
            context={"cycle_ts": run_ts},
            data_dir=ddir,
        )
        _blk_protos = [
            p for p, s in (_blk.get("protocols") or {}).items()
            if isinstance(s, dict) and s.get("signal") == "BLOCK"
        ]
        if _blk_protos:
            _freed = sum(float(target_usd.get(p, 0.0)) for p in _blk_protos)
            for _p in _blk_protos:
                target_usd[_p] = 0.0
            # redistribute freed capital proportionally onto allowed protocols
            _allowed = {k: v for k, v in target_usd.items()
                        if k not in _blk_protos and v > 0.0}
            _allowed_total = sum(_allowed.values())
            if _freed > 0.0 and _allowed_total > 0.0:
                for _k, _v in _allowed.items():
                    target_usd[_k] = _v + _freed * (_v / _allowed_total)
            # else: freed capital implicitly stays in cash (residual)
            log.warning("Analytics blocked protocols: %s (freed $%.0f)",
                        _blk_protos, _freed)
            notes.append(
                "analytics_blocking: blocked=" + ",".join(_blk_protos)
                + f" freed=${_freed:,.0f}"
            )
            # ring-buffer audit (data/analytics_blocks.json, max 100)
            if write:
                try:
                    _ab_path = ddir / "analytics_blocks.json"
                    _ab_hist = _read_json(_ab_path, [])
                    if not isinstance(_ab_hist, list):
                        _ab_hist = []
                    _ab_hist.append({
                        "ts": run_ts, "date": today,
                        "blocked": _blk_protos, "freed_usd": round(_freed, 2),
                        "correlation_id": correlation_id,
                        "signals": {p: _blk["protocols"][p] for p in _blk_protos},
                    })
                    _atomic_write_json(_ab_path, _ab_hist[-100:])
                except Exception as _abw_exc:
                    log.warning("analytics_blocks write failed (%s)", _abw_exc)
    except Exception as _ag_exc:  # gate must never crash the cycle
        log.warning(
            "Analytics Blocking Gate failed (%s) — fail-open, cycle continues",
            _ag_exc,
        )
        notes.append(f"analytics_blocking_error: {type(_ag_exc).__name__}")


def apply_kill_switch_override(
    target_usd: dict[str, float],
    *,
    ks_triggered: bool,
    ks_allocation: dict[str, float],
    capital_usd: float,
    notes: list[str],
) -> dict[str, float]:
    """Step 2c (MP-108): kill-switch override — force all-cash allocation.

    Kill-switch overrides both the allocator and the risk policy gate. All
    capital moves to cash; all protocol allocations set to 0. Returns the
    (possibly rewritten) ``target_usd`` — byte-identical to the original inline
    block (which reassigned ``target_usd``).
    """
    if ks_triggered and ks_allocation:
        # Kill-switch overrides both the allocator and the risk policy gate.
        # All capital moves to cash; all protocol allocations set to 0.
        target_usd = {
            k: float(v) * capital_usd if k == "cash" else 0.0
            for k, v in ks_allocation.items()
        }
        # Remove "cash" as a protocol entry — cash is the residual.
        target_usd = {k: v for k, v in target_usd.items() if k != "cash"}
        notes.append(
            "kill_switch_override: all protocol allocations set to 0 (all-cash)."
        )
    return target_usd


def apply_soft_derisk_gate(
    target_usd: dict[str, float],
    *,
    current_positions: dict[str, float],
    derisk_active: bool,
    notes: list[str],
) -> dict[str, float]:
    """SOFT tier (ADR-034): de-risk → halt new allocations / no INCREASES.

    When the evidenced drawdown is in the soft band ``[5%, 10%)`` the cycle must
    NOT open any new position nor INCREASE an existing one — it may only HOLD or
    REDUCE. This is enforced deterministically by capping every protocol's target
    to its currently-held USD:

        * a brand-new protocol (not currently held) is forced to 0.0  (no NEW);
        * an existing protocol's target is clamped to ``min(target, held)``
          (no INCREASE — a reduction below ``held`` is left intact).

    The freed capital implicitly stays in cash (residual). Does NOT liquidate:
    held positions are preserved at their current size when the allocator wanted
    to keep or grow them. Mutates ``target_usd`` and ``notes`` in place and
    returns ``target_usd`` (for symmetry with ``apply_kill_switch_override``).

    Deterministic, fail-safe: when not active it is a no-op.
    """
    if not derisk_active:
        return target_usd

    held = {
        str(p): float(v)
        for p, v in (current_positions or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0
    }
    blocked_new: list[str] = []
    capped: list[str] = []
    for proto in list(target_usd.keys()):
        try:
            want = float(target_usd[proto])
        except (TypeError, ValueError):
            want = 0.0
        held_usd = held.get(proto, 0.0)
        if held_usd <= 0.0:
            # Not currently held → no NEW position allowed under de-risk.
            if want > 0.0:
                blocked_new.append(proto)
            target_usd[proto] = 0.0
        elif want > held_usd:
            # Currently held → no INCREASE; clamp to the held size (hold).
            target_usd[proto] = held_usd
            capped.append(proto)
        # want <= held_usd (a reduction or unchanged hold) → left intact.

    log.warning(
        "SOFT DE-RISK gate ACTIVE (ADR-034): blocked %d new, capped %d increase "
        "(hold/reduce only)",
        len(blocked_new),
        len(capped),
    )
    notes.append(
        "soft_derisk_gate: drawdown in [5%,10%) — halted new allocations / "
        f"increases (blocked_new={blocked_new}, capped_increase={capped}); "
        "hold/reduce only, NOT liquidated."
    )
    return target_usd


def apply_rtmr_posture_gate(
    target_usd: dict[str, float],
    *,
    capital_usd: float,
    now_ts: int,
    notes: list[str],
    posture: dict | None = None,
) -> dict[str, float]:
    """RTMR (ADR-053) posture-honor gate: clamp targets to the emergency-path's active posture.

    The RTMR sense/emergency service writes ``data/monitoring/risk_posture.json`` on a de-risk;
    the cycle must honor it (§2, §7). **De-risk-only:** EXITED scope → 0, CAPPED → ``min(target,
    cap×capital)``, portfolio DEFENSIVE → all-cash. Only ever REDUCES; freed capital stays in cash.

    Protocol-scoped postures (from the tvl / liquidity sensors — scopes ARE protocol names) match
    ``target_usd`` keys directly. Asset-scoped postures (peg / oracle — scopes are "USDC" etc.) need
    an asset→protocol map (follow-up) and are dormant here. Deterministic; a NORMAL / unreadable
    posture is a no-op (fail-safe: never over-constrain the cycle on a read error).

    NOTE: additive — ``cycle_runner`` does not call this yet. Wiring it (one call beside
    ``apply_soft_derisk_gate``) is the owner-gated money-path activation (S10.5b).
    """
    try:
        from spa_core.monitoring import posture as P
        posture = posture if posture is not None else P.load_posture()
    except Exception:  # noqa: BLE001 — no posture module/file → no-op (fail-safe)
        return target_usd

    if P.portfolio_defensive(posture):
        for proto in list(target_usd.keys()):
            target_usd[proto] = 0.0
        notes.append("rtmr_posture_gate: portfolio DEFENSIVE → all-cash (RTMR emergency).")
        return target_usd

    try:
        from spa_core.monitoring.asset_map import asset_of
    except Exception:  # noqa: BLE001
        asset_of = lambda _p: None  # noqa: E731

    clamped: list[str] = []
    for proto in list(target_usd.keys()):
        # honor BOTH the protocol-scoped posture (tvl/liquidity) AND the asset-scoped posture
        # (peg/oracle → the stablecoin this protocol is denominated in). Take the tighter (min) cap.
        caps = [c for c in (P.cap_for(posture, proto, now_ts=now_ts),
                            P.cap_for(posture, asset_of(proto) or "", now_ts=now_ts)) if c is not None]
        if not caps:
            continue
        cap = min(caps)
        cap_usd = max(0.0, float(cap) * float(capital_usd))
        try:
            want = float(target_usd[proto])
        except (TypeError, ValueError):
            want = 0.0
        if want > cap_usd:
            target_usd[proto] = cap_usd
            clamped.append(f"{proto}->${cap_usd:,.0f}")
    if clamped:
        log.warning("RTMR posture gate ACTIVE: clamped %d protocol(s) to posture", len(clamped))
        notes.append(f"rtmr_posture_gate: honored RTMR posture (de-risk only): {clamped}")
    return target_usd


def apply_base_gas_kill_switch(
    target_usd: dict[str, float],
    *,
    ddir: Path,
    base_gas_monitor_class: type[Any] | None,
    base_chain_monitoring: bool,
    notes: list[str],
) -> None:
    """Step 2d (ADR-025): Base chain gas kill-switch — zero Base allocations.

    Fail-safe: any exception → WARNING log, cycle continues unaffected.
    LLM_FORBIDDEN in this block (deterministic gas monitor only).

    Mutates ``target_usd`` and ``notes`` in place (byte-identical to the original
    inline block in ``run_cycle``).
    """
    if base_chain_monitoring and base_gas_monitor_class is not None:
        try:
            _base_gas_mon = base_gas_monitor_class(data_dir=ddir)
            _gas_status = _base_gas_mon.record_reading()
            if _gas_status.get("kill_switch_active"):
                _base_adapters = [k for k in target_usd if "base" in k.lower()]
                _zeroed = []
                for _aid in _base_adapters:
                    if target_usd.get(_aid, 0.0) > 0.0:
                        target_usd[_aid] = 0.0
                        _zeroed.append(_aid)
                _gas_gwei = _gas_status.get("gwei")
                _gas_days = _gas_status.get("consecutive_above")
                log.warning(
                    "ADR-025 Base gas kill-switch ACTIVE: %.4f Gwei, %d consecutive days "
                    "above threshold. Zeroed Base allocations: %s",
                    _gas_gwei,
                    _gas_days,
                    _zeroed or "none",
                )
                notes.append(
                    f"adr025_base_gas_kill_switch: gwei={_gas_gwei}, "
                    f"consecutive_above={_gas_days}, zeroed={_zeroed}"
                )
            elif _gas_status.get("action") == "WARN":
                log.info(
                    "ADR-025 Base gas WARN: %.4f Gwei, %d consecutive days above threshold",
                    _gas_status.get("gwei"),
                    _gas_status.get("consecutive_above"),
                )
        except Exception as _bge:  # never break the main cycle
            log.warning("ADR-025 base_gas_monitor check failed (%s) — cycle continues", _bge)
