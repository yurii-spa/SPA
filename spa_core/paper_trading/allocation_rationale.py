"""SHADOW writer for the yield-improvement trigger (ADR-060, phase 0).

Runs the trigger's economics every cycle and records what it WOULD have done in
``data/allocation_rationale.json``. It never returns a target, never mutates a
position, and never influences the trade decision — arming it is a separate,
owner-gated step. The point of the shadow phase is that the owner can read a
fortnight of real verdicts before any capital depends on them.

Also discharges the ADR-055 obligation that idle capital be explained every cycle:
whatever the named binders do not cover is published as ``UNEXPLAINED_CASH``.

Fail-open by construction: any error here is logged and swallowed. A reporting
layer must never be able to break the cycle that feeds the track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.allocator.rebalance_economics import (
    TriggerParams,
    below_median_cap_violations,
    evaluate,
    explain_cash,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.allocation_rationale")

RATIONALE_FILENAME = "allocation_rationale.json"
SHADOW_VERSION = "shadow-v1"


def _resolve_tier_caps(protocols) -> Dict[str, float]:
    """Per-protocol concentration cap from RiskConfig via the canonical tier map.

    Without these the below-median rule is INERT — it can only flag "funded above
    half its cap" if it knows the cap. Values are read from RiskConfig (T1 40 % /
    T2+T3 20 %), never hardcoded here, so this can never drift from policy.
    """
    caps: Dict[str, float] = {}
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
    except Exception as exc:  # noqa: BLE001
        log.warning("ADR-060 shadow: RiskConfig unavailable (%s) — below-median rule inert", exc)
        return caps
    try:
        from spa_core.adapters.tier_map import tier_of
    except Exception as exc:  # noqa: BLE001
        log.warning("ADR-060 shadow: tier_map unavailable (%s)", exc)
        return caps
    for proto in protocols or []:
        try:
            tier = str(tier_of(proto) or "T2").upper()
        except Exception:  # noqa: BLE001 — one bad lookup never breaks the report
            tier = "T2"
        caps[proto] = float(
            cfg.max_concentration_t1 if tier == "T1" else cfg.max_concentration_t2
        )
    return caps


def _parse_ts(value: object) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _history_from_trades(trades: List[dict], now: datetime) -> dict:
    """Derive the anti-churn history the trigger needs from ``trades.json``.

    Returns ``days_since_last_act`` / ``last_move_legs`` / ``turnover_last_week_usd``.
    Unknown values stay ``None`` — the trigger then treats that gate as unconstrained,
    which is the honest reading in SHADOW (we are measuring, not restraining).
    """
    out: dict = {"days_since_last_act": None, "days_since_last_move": None,
                 "last_move_legs": None, "turnover_last_week_usd": 0.0}
    rebalances = [t for t in (trades or []) if isinstance(t, dict)
                  and t.get("type") == "rebalance"]
    if not rebalances:
        return out

    week_ago = now - timedelta(days=7)
    turnover = 0.0
    for t in rebalances:
        ts = _parse_ts(t.get("ts"))
        if ts is not None and ts >= week_ago:
            turnover += float(t.get("delta_abs") or 0.0)
    out["turnover_last_week_usd"] = round(turnover, 2)

    last = rebalances[-1]
    ts = _parse_ts(last.get("ts"))
    if ts is not None:
        age_days = (now - ts).total_seconds() / 86400.0
        out["days_since_last_act"] = round(age_days, 4)
        out["days_since_last_move"] = round(age_days, 4)
    frm = last.get("from_allocation") or {}
    to = last.get("to_allocation") or {}
    if isinstance(frm, dict) and isinstance(to, dict):
        out["last_move_legs"] = {
            p: round(float(to.get(p, 0.0) or 0.0) - float(frm.get(p, 0.0) or 0.0), 2)
            for p in set(frm) | set(to)
        }
    return out


def _position_ages(trades: List[dict], positions: Dict[str, float],
                   now: datetime) -> Dict[str, float]:
    """Days since each held protocol was last INCREASED (its entry, for min-hold)."""
    ages: Dict[str, float] = {}
    for t in reversed([t for t in (trades or []) if isinstance(t, dict)
                       and t.get("type") == "rebalance"]):
        ts = _parse_ts(t.get("ts"))
        if ts is None:
            continue
        frm, to = t.get("from_allocation") or {}, t.get("to_allocation") or {}
        if not isinstance(frm, dict) or not isinstance(to, dict):
            continue
        for proto in positions:
            if proto in ages:
                continue
            if float(to.get(proto, 0.0) or 0.0) > float(frm.get(proto, 0.0) or 0.0):
                ages[proto] = round((now - ts).total_seconds() / 86400.0, 4)
    return ages


def write_shadow_rationale(
    *,
    data_dir: Path,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    apy_pct: Dict[str, float],
    apy_sources: Dict[str, str],
    tvl_sources: Optional[Dict[str, str]] = None,
    capital_usd: float,
    cycle_date: str,
    run_ts: str,
    tier_caps: Optional[Dict[str, float]] = None,
    cash_binders: Optional[List[dict]] = None,
    min_cash_frac: float = 0.05,
    trades: Optional[List[dict]] = None,
    now: Optional[datetime] = None,
    write: bool = True,
    params: Optional[TriggerParams] = None,
) -> dict:
    """Compute the shadow verdict and (optionally) persist it. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        p = params or TriggerParams()

        # Evidence comes from the allocator's own provenance, which ADR-061/063 made
        # truthful: "live" now means observed, not "a literal we dressed up".
        evidenced = {proto for proto, src in (apy_sources or {}).items() if src == "live"}

        chains: Dict[str, str] = {}
        try:
            reg = json.loads(
                (Path(data_dir) / "adapter_registry.json").read_text(encoding="utf-8"))
            for name, entry in (reg.get("adapters", {}) or {}).items():
                if isinstance(entry, dict) and entry.get("chain"):
                    chains[str(name)] = str(entry["chain"]).strip().lower()
        except Exception as exc:  # noqa: BLE001 — cost model degrades, never breaks
            log.warning("ADR-060 shadow: chain map unavailable (%s)", exc)

        # TVL provenance: a target pool that cleared the floor on a literal makes the
        # recommendation unsound.
        #
        # Source of truth is the ALLOCATOR's own ``tvl_sources`` (ADR-053 allocator
        # side): "live" only when the orchestrator record declares the TVL
        # feed-observed; registry $50M / fallback_tvl_usd literals are "static".
        # Deriving it here from the raw snapshot instead would create a second,
        # competing definition of the same thing — the drift this project keeps
        # paying for. The snapshot is used only as a fallback when the allocator
        # did not supply the map.
        tvl_evidenced = set()
        if tvl_sources:
            tvl_evidenced = {p_ for p_, src in tvl_sources.items() if src == "live"}
        else:
            try:
                orch = json.loads((Path(data_dir) / "adapter_orchestrator_status.json")
                                  .read_text(encoding="utf-8"))
                for a in orch.get("adapters", []) or []:
                    if isinstance(a, dict) and a.get("protocol") and a.get("tvl_usd") is not None:
                        tvl_evidenced.add(str(a["protocol"]))
            except Exception as exc:  # noqa: BLE001
                log.warning("ADR-060 shadow: TVL provenance unavailable (%s)", exc)

        hist = _history_from_trades(trades or [], now)
        ages = _position_ages(trades or [], current_positions or {}, now)

        decision = evaluate(
            current_positions=current_positions or {},
            target_positions=target_positions or {},
            apy_pct=apy_pct or {},
            evidenced=evidenced,
            chains=chains,
            capital_usd=capital_usd,
            params=p,
            days_since_last_act=hist["days_since_last_act"],
            position_age_days=ages,
            turnover_last_week_usd=hist["turnover_last_week_usd"],
            last_move_legs=hist["last_move_legs"],
            days_since_last_move=hist["days_since_last_move"],
            tvl_evidenced=tvl_evidenced or None,
        )

        cash = explain_cash(positions=current_positions or {}, capital_usd=capital_usd,
                            min_cash_frac=min_cash_frac, binders=cash_binders)
        # Caps resolved here when the caller did not supply them — otherwise the
        # below-median rule silently reports nothing and looks compliant.
        _caps = tier_caps or _resolve_tier_caps(list((current_positions or {}).keys()))
        below_median = below_median_cap_violations(
            positions=current_positions or {}, apy_pct=apy_pct or {},
            tier_caps=_caps, capital_usd=capital_usd,
            evidenced=evidenced, factor=p.below_median_cap_factor)

        doc = {
            "generated_at": run_ts,
            "cycle_date": cycle_date,
            "mode": "SHADOW",
            "version": SHADOW_VERSION,
            "note": (
                "ADR-060 phase 0. Verdict is ADVISORY: no position was changed by it. "
                "Arming is a separate owner-gated step."
            ),
            "capital_usd": capital_usd,
            "decision_shadow": decision.to_dict(),
            "cash": cash,
            "below_median_cap": below_median,
            "history": {**hist, "position_age_days": ages},
            "params": {
                "min_gain_pp": p.min_gain_pp,
                "max_payback_days": p.max_payback_days,
                "min_hold_days": p.min_hold_days,
                "act_cooldown_days": p.act_cooldown_days,
                "max_turnover_per_move": p.max_turnover_per_move,
                "max_turnover_per_week": p.max_turnover_per_week,
                "min_leg_frac": p.min_leg_frac,
                "reversal_window_days": p.reversal_window_days,
                "reversal_escalation": p.reversal_escalation,
                "below_median_cap_factor": p.below_median_cap_factor,
            },
        }

        if write:
            atomic_save(doc, str(Path(data_dir) / RATIONALE_FILENAME))
        log.info(
            "ADR-060 SHADOW: %s | gain %.3fpp (need %.3f) | cost $%.2f | payback %s | cash %s",
            decision.decision, decision.gain_pp, decision.required_gain_pp,
            decision.cost_usd, decision.payback_days, cash.get("status"),
        )
        return doc
    except Exception as exc:  # noqa: BLE001 — a reporting layer never breaks the cycle
        log.warning("ADR-060 shadow rationale failed (%s) — cycle continues", exc)
        return {"error": type(exc).__name__, "mode": "SHADOW"}
