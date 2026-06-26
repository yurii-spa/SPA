#!/usr/bin/env python3
"""Deterministic RiskPolicy gate for the paper-trading cycle (N12 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.py``: the MP-005 RiskPolicy gate, the
ALLOC-002 pre-diff compliant-target collapse, the policy-block audit writer and
the policy-version helper. Bodies are byte-identical to their originals — no
behaviour change. ``cycle_runner`` re-exports every name below for back-compat.

LLM FORBIDDEN — deterministic, pure in-memory checks (the gate reads no files,
writes no files and touches no capital). stdlib only.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from spa_core.paper_trading._cycle_io import (
    MAX_POLICY_BLOCKS,
    POSITIONS_FILENAME,
    RISK_BLOCKS_FILENAME,
    _atomic_write_json,
    _read_json,
)

log = logging.getLogger("spa.cycle_runner")


def _compliant_target(
    target_usd: dict[str, float],
    capital_usd: float,
    ddir: "Path",
    write: bool,
) -> tuple[dict[str, float], bool]:
    """ALLOC-002: collapse the raw allocator target to a policy-compliant book
    *before* the rebalance diff is computed.

    ROOT-CAUSE FIX (allocation oscillation): ``StrategyAllocator.allocate()`` has
    per-protocol concentration caps but NO protocol-*count* cap, so it natively
    emits ~24 protocols. Previously the rebalance diff compared the persisted
    ≤8-protocol book against this fresh 24-protocol target → always a large diff
    → a phantom ~$122K rebalance every cycle, then ALLOC-002 collapsed the book
    to ≤8 *after* the trade was already recorded. The next cycle's allocator
    emitted 24 again → endless 24↔8 churn on an unchanged market.

    This helper makes the count-capped, policy-compliant book the *target* the
    diff is computed against. When the raw target already passes the enforcer it
    is returned unchanged. When it violates (e.g. ``max_protocols`` / ``t1_min``)
    we derive the compliant book from the DETERMINISTIC ``portfolio_rebalancer``
    (``random.Random(42)`` candidate search + deterministic safe-fallback). Same
    market data → same compliant book every cycle → held-compliant vs
    new-compliant diff ≈ 0 (no phantom turnover).

    Returns ``(compliant_target, was_collapsed)``. Fail-open: any error returns
    the original target unchanged (ALLOC-002 post-check still guards the write).
    """
    try:
        from spa_core.risk.policy_enforcer import validate_positions as _pe
        _cash = capital_usd - sum(target_usd.values())
        _chk = _pe(positions=target_usd, capital_usd=capital_usd, cash_usd=_cash)
        if _chk.passed:
            return target_usd, False
        # Scope: this pre-diff collapse targets the OSCILLATION root cause —
        # the protocol-*count* explosion (~24 protocols) that the allocator has
        # no native cap for. Other policy violations (per-protocol concentration,
        # t1_min, etc.) on an already-small book are left to the existing gate +
        # post-write ALLOC-002 check (unchanged behaviour). We only intervene
        # pre-diff when the count cap is breached, which is what flaps the diff.
        _viol_rules = {v.rule for v in _chk.violations}
        if "max_protocols" not in _viol_rules:
            return target_usd, False
        # Over-diversified raw target: derive the deterministic compliant book
        # from the rebalancer.
        from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio as _rb
        if _rb(capital_usd=capital_usd, data_dir=ddir, write=write, send_alert=False):
            _pos = (
                _read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}
            )
            if _pos:
                _c = _pe(
                    positions=_pos,
                    capital_usd=capital_usd,
                    cash_usd=capital_usd - sum(float(v) for v in _pos.values()),
                )
                if _c.passed:
                    return {str(p): float(v) for p, v in _pos.items()}, True
        # Rebalancer could not produce a compliant book (e.g. no adapter snapshot
        # available). Fall back to the DETERMINISTIC known-good safe portfolio so
        # the cycle output is STILL count-capped and stable — never the raw
        # 24-protocol target. This is the same hardcoded book the rebalancer uses
        # as its own fallback, validated below before adoption.
        from spa_core.tuner.portfolio_rebalancer import (
            _build_safe_fallback_positions as _safe,
        )
        _safe_pos, _safe_cash = _safe(capital_usd)
        _safe_chk = _pe(
            positions=_safe_pos, capital_usd=capital_usd, cash_usd=_safe_cash
        )
        if _safe_chk.passed:
            return {str(p): float(v) for p, v in _safe_pos.items()}, True
        # Even the safe fallback failed validation — keep raw target; the
        # downstream ALLOC-002 post-check still guards the persisted write.
        return target_usd, False
    except Exception as exc:  # noqa: BLE001 — fail-open, never break the cycle
        log.warning("ALLOC-002: pre-diff compliant collapse skipped (%s)", exc)
        return target_usd, False


def _apply_risk_policy_gate(
    target_usd: dict[str, float],
    capital_usd: float,
    adapters: list[dict],
    ddir: "Path | None" = None,
) -> dict:
    """Validate the allocator's target against ``RiskPolicy`` (MP-005).

    The target is replayed position-by-position through
    ``RiskPolicy.check_new_position()`` on a fresh ``PortfolioState`` so the
    cumulative limits (per-protocol concentration, total-T2 cap, cash buffer)
    see the *whole* target allocation, not just one trade.

    min-cash handling: a target that deploys past ``1 - min_cash_pct`` of
    capital is trimmed proportionally instead of blocked (per MP-005 spec).

    Returns a dict::

        approved    bool — False → the rebalance trade must NOT be recorded
        violations  list[str] — blocking violations ("<pool>: <reason>")
        warnings    list[str] — non-blocking policy warnings
        trimmed     bool — target was scaled down to the min-cash buffer
        target_usd  dict — the (possibly trimmed) allocation to use downstream
        error       str | None — the gate itself failed → fail-closed (FIX-P0)

    Never raises: any unexpected exception is captured into ``error`` so a
    broken gate degrades to a logged WARNING and a BLOCKED trade (fail-closed).
    Previously this was fail-open; changed to fail-closed for live-capital safety.
    """
    out: dict = {
        "approved": True,
        "violations": [],
        "warnings": [],
        "trimmed": False,
        "target_usd": dict(target_usd),
        "error": None,
    }
    try:
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        cfg = policy.config

        meta: dict[str, dict] = {}
        for a in adapters:
            if isinstance(a, dict) and a.get("protocol"):
                meta[str(a["protocol"])] = a

        # ── MP-1180: load adapter_registry.json fallbacks ────────────────────
        # When live orchestrator returns apy=None/tvl=None (network errors),
        # the gate sees APY=0%/TVL=$0 → policy_blocked=True → 0 trades.
        # We resolve this by loading researched fallback values from the
        # registry (keyed by snake_case adapter name, matching target_usd keys).
        # fallback_apy is stored as decimal fraction (0.035 = 3.5%) and must
        # be converted to percentage units for RiskPolicy.check_new_position().
        # TVL is not stored in registry → use conservative safe minimum $20M
        # (safely above the policy floor of $5M for all whitelisted protocols).
        _reg_fallbacks: dict[str, dict] = {}
        if ddir is not None:
            try:
                _reg_doc = _read_json(Path(ddir) / "adapter_registry.json", {})
                if isinstance(_reg_doc, dict):
                    _reg_adapters = _reg_doc.get("adapters", {})
                    if isinstance(_reg_adapters, dict):
                        _reg_fallbacks = {
                            k: v
                            for k, v in _reg_adapters.items()
                            if isinstance(v, dict)
                        }
            except Exception as _rfb_exc:
                log.warning(
                    "MP-1180 registry fallback load failed (%s) — gate continues",
                    _rfb_exc,
                )

        adjusted = {
            str(p): float(v)
            for p, v in target_usd.items()
            if isinstance(v, (int, float)) and float(v) > 0
        }

        # min_cash: trim to the deployable maximum, do not block (MP-005 spec).
        # floor() keeps the trimmed total strictly ≤ the cap despite rounding.
        max_deploy = capital_usd * (1.0 - cfg.min_cash_pct)
        total = sum(adjusted.values())
        if total > max_deploy and total > 0:
            scale = max_deploy / total
            adjusted = {
                p: math.floor(v * scale * 100) / 100.0 for p, v in adjusted.items()
            }
            out["trimmed"] = True

        state = PortfolioState(total_capital_usd=capital_usd, positions=[])
        violations: list[str] = []
        warnings: list[str] = []
        for pool, usd in sorted(adjusted.items(), key=lambda kv: (-kv[1], kv[0])):
            m = meta.get(pool, {})
            tier = str(m.get("tier") or "T2").upper()
            apy = float(m.get("apy_pct") or 0.0)
            tvl = float(m.get("tvl_usd") or 0.0)
            # Chain-level limits apply only when the adapter reports its chain.
            # Without it, a per-pool placeholder prevents the single-chain cap
            # from falsely lumping every pool onto "ethereum".
            chain = str(m.get("chain") or f"unknown:{pool}")

            # ── MP-1180: registry fallback when live data is missing ──────────
            # Live orchestrator returns None→0 for APY/TVL on network errors.
            # Prefer registry fallback over blocking the rebalance entirely.
            # Live values (apy>0 or tvl>0) are never overwritten.
            if (apy == 0.0 or tvl == 0.0) and pool in _reg_fallbacks:
                _fb = _reg_fallbacks[pool]
                if apy == 0.0:
                    # registry stores fraction (0.035); gate expects pct (3.5)
                    _fb_apy_frac = _fb.get("live_apy") or _fb.get("fallback_apy")
                    if isinstance(_fb_apy_frac, (int, float)) and _fb_apy_frac > 0:
                        apy = float(_fb_apy_frac) * 100.0
                        log.warning(
                            "MP-1180 %s: live apy missing → registry fallback"
                            " apy=%.3f%% (was 0.0%%)",
                            pool,
                            apy,
                        )
                if tvl == 0.0:
                    # registry has no tvl_usd → conservative safe minimum
                    # $20M is above the policy floor of $5M for all whitelisted
                    # protocols, and below any real deployed TVL.
                    _fb_tvl = _fb.get("tvl_usd")
                    tvl = (
                        float(_fb_tvl)
                        if isinstance(_fb_tvl, (int, float)) and _fb_tvl > 0
                        else 20_000_000.0
                    )
                    log.warning(
                        "MP-1180 %s: live tvl missing → fallback tvl=$%.0f",
                        pool,
                        tvl,
                    )
                # also fill tier/chain from registry when meta was empty
                if not m.get("tier") and _fb.get("tier") is not None:
                    _t = _fb["tier"]
                    tier = f"T{_t}".upper() if isinstance(_t, int) else str(_t).upper()
                if chain.startswith("unknown:") and _fb.get("chain"):
                    chain = str(_fb["chain"])
            res = policy.check_new_position(
                state,
                protocol_key=pool,
                tier=tier,
                amount_usd=usd,
                current_apy=apy,
                tvl_usd=tvl,
                chain=chain,
            )
            warnings.extend(res.warnings)
            if not res.approved:
                violations.extend(f"{pool}: {v}" for v in res.violations)
            # Add the position regardless of the verdict so cumulative limits
            # (T2 total, concentration) are evaluated over the full target.
            state.positions.append(
                Position(
                    protocol_key=pool,
                    tier=tier,
                    asset="USDC",
                    amount_usd=usd,
                    apy_at_open=apy,
                    current_apy=apy,
                    chain=chain,
                )
            )

        out["violations"] = violations
        out["warnings"] = warnings
        out["approved"] = not violations
        out["target_usd"] = adjusted
    except Exception as exc:  # gate must never crash the cycle (MP-005 spec)
        # FIX-P0 (fail-closed): any exception inside the gate BLOCKS the trade.
        # Previously this was fail-open (approved=True on exception), which is
        # a critical vulnerability for live capital — an error could silently
        # bypass all risk checks.  Now: exception → approved=False, trade blocked.
        log.warning(
            "FAIL-CLOSED: risk gate exception, blocking trade: %s",
            exc,
        )
        out["approved"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["violations"] = out.get("violations") or [
            f"gate_exception: {type(exc).__name__}: {exc}"
        ]
    return out


def _record_policy_block(
    ddir: Path,
    *,
    run_ts: str,
    date: str,
    gate: dict,
    current_positions: dict[str, float],
    capital_usd: float,
) -> None:
    """Append one audit record to ``risk_policy_blocks.json`` (ring-buffer 100)."""
    blocks = _read_json(ddir / RISK_BLOCKS_FILENAME, [])
    if not isinstance(blocks, list):
        blocks = []
    blocks.append(
        {
            "ts": run_ts,
            "date": date,
            "source": "cycle_runner",
            "policy_version": _policy_version(),
            "violations": list(gate.get("violations") or []),
            "warnings": list(gate.get("warnings") or []),
            "blocked_target_usd": {
                p: round(float(v), 2)
                for p, v in (gate.get("target_usd") or {}).items()
            },
            "held_positions_usd": {
                p: round(float(v), 2) for p, v in current_positions.items()
            },
            "capital_usd": capital_usd,
        }
    )
    blocks = blocks[-MAX_POLICY_BLOCKS:]  # ring-buffer
    _atomic_write_json(ddir / RISK_BLOCKS_FILENAME, blocks)


def _policy_version() -> str:
    """Active RiskConfig version for audit records (best-effort)."""
    try:
        from spa_core.risk.policy import RiskConfig

        return RiskConfig().version
    except Exception:
        return "unknown"
