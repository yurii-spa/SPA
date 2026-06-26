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
