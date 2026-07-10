"""6mo-M1 #1 — enforced per-tier POLICY profiles (the owner's headline ask).

The owner's #1 product requirement: three customer-selectable tiers, each with its OWN enforced rules,
so the customer picks risk/return knowingly. This module is that rulebook — a deterministic, stdlib-only,
self-contained data structure with a pure validator. It lives ENTIRELY OUTSIDE RiskPolicy v1.0 (the
deterministic live execution gate is untouched); it governs only the advisory aggressive_lab / tier
composition. LLM-forbidden, fail-CLOSED (an unknown tier or a missing descriptor field → a violation,
never a silent pass).

The three tiers and their enforced bands:
  • CONSERVATIVE — delegates to RiskPolicy v1.0 unchanged. A Conservative book IS a RiskPolicy-governed
    book (risk_class A, no leverage, no aggressive tail shape). This tier adds NOTHING to RiskPolicy; it
    just records that the hard deterministic gate is the rule, and refuses any aggressive attribute.
  • BALANCED     — risk_class B/C; leverage ≤ 2x; a hedge OR an explicit depeg-guard REQUIRED; tighter
    drawdown-kill (≤ 10%); the tail MUST be shown. (sUSDe delta-neutral, PT-carry, LST-hedged.)
  • AGGRESSIVE   — risk_class C/D; PT/YT loops + LRT + points ALLOWED, but a non-empty tail overlay is
    MANDATORY (the tail is always shown), and the book is stamped C/D. Refused-for-live regardless.

`validate_book(tier, descriptor)` returns {ok, tier, violations:[...]}. It never raises on bad input —
a malformed descriptor is reported as violations (fail-CLOSED), so a caller (e.g. build_roster, #2) can
reject/park a book that violates its assigned tier band.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# RiskPolicy version this rulebook composes UNDER (Conservative delegates to it). Imported lazily in the
# validator so this module stays import-light and NEVER pulls execution/ into the advisory path.
RISKPOLICY_VERSION = "v1.0"

__all__ = ["TierProfile", "TIER_PROFILES", "validate_book", "tier_of_risk_class"]


@dataclass(frozen=True)
class TierProfile:
    """One tier's enforced band. Frozen + pure data — no behaviour, no I/O."""
    name: str
    allowed_risk_classes: Tuple[str, ...]
    max_leverage: float
    hedge_or_depeg_guard_required: bool
    tail_required: bool
    max_dd_kill_pct: float                 # the tier's drawdown-kill ceiling (advisory de-risk band)
    delegates_to_riskpolicy: bool = False  # Conservative → RiskPolicy v1.0 is the hard gate
    allows_points_lrt_loops: bool = False  # Aggressive-only: PT/YT loops + LRT + points permitted


TIER_PROFILES: Dict[str, TierProfile] = {
    "conservative": TierProfile(
        name="conservative",
        allowed_risk_classes=("A",),
        max_leverage=1.0,
        hedge_or_depeg_guard_required=False,
        tail_required=False,
        max_dd_kill_pct=10.0,              # inherits the two-tier kill via RiskPolicy governance
        delegates_to_riskpolicy=True,
        allows_points_lrt_loops=False,
    ),
    "balanced": TierProfile(
        name="balanced",
        allowed_risk_classes=("B", "C"),
        max_leverage=2.0,
        hedge_or_depeg_guard_required=True,
        tail_required=True,
        max_dd_kill_pct=10.0,
        delegates_to_riskpolicy=False,
        allows_points_lrt_loops=False,
    ),
    "aggressive": TierProfile(
        name="aggressive",
        allowed_risk_classes=("C", "D"),
        max_leverage=10.0,                 # loops permitted; the tail (mandatory) is the honesty gate
        hedge_or_depeg_guard_required=False,
        tail_required=True,
        max_dd_kill_pct=50.0,
        delegates_to_riskpolicy=False,
        allows_points_lrt_loops=True,
    ),
}


def tier_of_risk_class(risk_class: str) -> Optional[str]:
    """The DEFAULT tier a given risk_class maps to (A→conservative, B→balanced, C→balanced/aggressive,
    D→aggressive). C is dual-eligible (Balanced hedged, or Aggressive) — returns 'balanced' as the safer
    default; the caller may assign Aggressive explicitly. None for an unknown class (fail-CLOSED)."""
    return {"A": "conservative", "B": "balanced", "C": "balanced", "D": "aggressive"}.get(
        (risk_class or "").strip().upper())


def _num(v: Any, default: float) -> float:
    try:
        f = float(v)
        return f if f == f else default   # NaN-guard
    except (TypeError, ValueError):
        return default


def validate_book(tier: str, descriptor: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a book DESCRIPTOR against its assigned tier's enforced band. Pure + fail-CLOSED.

    descriptor keys (missing → treated conservatively as a violation where the band requires proof):
      risk_class:str, leverage:float=1.0, hedged:bool=False, depeg_guard:bool=False,
      tail_overlay_present:bool=False, uses_points_lrt_loops:bool=False.
    """
    prof = TIER_PROFILES.get((tier or "").strip().lower())
    if prof is None:
        return {"ok": False, "tier": tier, "violations": [f"unknown tier {tier!r}"],
                "riskpolicy_version": RISKPOLICY_VERSION}

    v: List[str] = []
    rc = str(descriptor.get("risk_class", "")).strip().upper()
    lev = _num(descriptor.get("leverage", 1.0), 1.0)
    hedged = bool(descriptor.get("hedged", False))
    depeg_guard = bool(descriptor.get("depeg_guard", False))
    tail_present = bool(descriptor.get("tail_overlay_present", False))
    uses_loops = bool(descriptor.get("uses_points_lrt_loops", False))

    if rc not in prof.allowed_risk_classes:
        v.append(f"risk_class {rc or '∅'} not in tier band {prof.allowed_risk_classes}")
    if lev > prof.max_leverage + 1e-9:
        v.append(f"leverage {lev:g}x exceeds tier max {prof.max_leverage:g}x")
    if prof.hedge_or_depeg_guard_required and not (hedged or depeg_guard):
        v.append("tier requires a hedge OR an explicit depeg-guard; neither declared")
    if prof.tail_required and not tail_present:
        v.append("tier requires the tail overlay to be shown (tail_overlay_present=False)")
    if uses_loops and not prof.allows_points_lrt_loops:
        v.append("PT/YT loops + LRT + points are not permitted in this tier")

    # Conservative delegates the HARD gate to RiskPolicy v1.0 — record it, and forbid aggressive attrs.
    if prof.delegates_to_riskpolicy:
        if lev > 1.0 + 1e-9:
            v.append("conservative delegates to RiskPolicy v1.0 — no leverage permitted")
        try:
            from spa_core.risk.policy import RiskConfig  # noqa: F401 — presence + version assertion only
            cfg_version = getattr(RiskConfig(), "version", None)
            if cfg_version and cfg_version != RISKPOLICY_VERSION:
                v.append(f"RiskPolicy version drift: {cfg_version} != {RISKPOLICY_VERSION}")
        except Exception as exc:  # fail-CLOSED: cannot confirm the hard gate → a violation
            v.append(f"could not confirm RiskPolicy v1.0 hard gate ({exc})")

    return {"ok": not v, "tier": prof.name, "violations": v,
            "riskpolicy_version": RISKPOLICY_VERSION,
            "delegates_to_riskpolicy": prof.delegates_to_riskpolicy}
