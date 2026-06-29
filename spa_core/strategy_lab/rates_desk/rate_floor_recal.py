"""
spa_core/strategy_lab/rates_desk/rate_floor_recal.py — ROUND-2 WS-3.1: EVIDENCE-BASED size-floor
recalibration (behind the OWNER-TUNABLE flag SPA_RATE_FLOOR_RECAL, DEFAULT OFF).

THE PROBLEM (WS-1's honest finding)
════════════════════════════════════
The gate's SIZE step (rate_policy step 7) refuses a book whose exit-capacity-bound size collapses below
a FIXED `min_tradeable_size_usd = $1,000`. WS-1.2 (refusal_cost) found this auto-refuses a GENUINELY-
FUNDABLE carry book: the live USDe PT book (net edge ~661 bps, structurally CLEAN — it passed every
tail/economic veto) has a §9 one-tick capacity cap of only $541.87 (= 25% × $2,167 realized exit
liquidity), so it hits the $1,000 floor and is refused as `size_floor`. That is NOT a risk refusal —
it forgoes real carry purely because a FIXED dollar floor is mis-scaled to a THIN-but-real pool.

THE FIX (evidence-based, behind a flag)
═════════════════════════════════════════
Re-derive `min_tradeable_size_usd` from the REALIZED Pendle PT exit depth on the live surface (the
actual liquidity), instead of a fixed $1,000 guess. The recalibrated floor is a small, depth-anchored
number: the smallest ticket that is still operationally worth trading, scaled to what the THINNEST
fundable pool can actually absorb in one tick. With the recalibrated floor, the USDe 661 bps book (and
any other historically-refused-but-SAFE book whose §9 cap sits between the recalibrated floor and the
old $1,000) now PASSES the SIZE gate at its capacity-bounded size.

THE HARD GUARDRAIL (the red-team's predicted catch)
═════════════════════════════════════════════════════
Recalibrating the SIZE floor touches ONLY gate step 7. It does NOT touch — and CANNOT touch — the
structural TAIL_VETO (step 1), which fires on the SIZE-INDEPENDENT `structural_haircut` BEFORE sizing
is ever consulted. A toxic LRT (ezETH/rsETH/over-levered USDe) is refused at step 1 at ANY size; it
never reaches the SIZE step, so NO recalibration of `min_tradeable_size_usd` can re-admit it. This
module ASSERTS that invariant: it only ever overrides `min_tradeable_size_usd` (and never lowers it
BELOW a documented hard floor), leaving `max_structural_haircut` / `max_total_haircut` / every k_* /
cap_* BYTE-IDENTICAL. An adversary who feeds a recalibrated floor that tried to re-admit a toxic book
would be feeding a `max_structural_haircut` change — which this module refuses to produce.

FLAG SEMANTICS (owner-tunable)
════════════════════════════════
`SPA_RATE_FLOOR_RECAL` (env): unset / "0" → recalibration OFF (the committed $1,000 floor is used
verbatim — no behavior change, fully back-compatible). "1" → ON (the depth-anchored floor is applied).
`flag_enabled()` reads it once per call (no cached global). The default OFF means the live paper desk
is UNCHANGED until the owner flips the flag — this is research, surfaced for a decision, not a silent
policy change.

stdlib only, Decimal-exact, deterministic, PURE where possible, fail-CLOSED, LLM-FORBIDDEN. Advisory:
this shapes ONLY the size floor of an already-structurally-approved book; it never approves a refused
book, never moves live capital, never touches the go-live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import dataclasses
import os
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from spa_core.strategy_lab.rates_desk.contracts import D0, RatePolicyParams
from spa_core.strategy_lab.rates_desk.fair_value_engine import _safe_decimal

_ROOT = Path(__file__).resolve().parents[3]
_SURFACE = _ROOT / "data" / "rates_desk" / "rate_surface.json"

# The OWNER-TUNABLE flag. DEFAULT OFF — unset or "0" leaves the committed $1,000 floor untouched.
FLAG_ENV = "SPA_RATE_FLOOR_RECAL"

# ── HARD bounds on the recalibrated floor (the floor can MOVE within these, never outside them) ──────
# A ticket below this is genuinely not worth the round-trip cost regardless of depth (operational floor).
# The recalibrated floor is NEVER lowered below this — depth recalibration cannot drive the floor to dust.
HARD_MIN_FLOOR_USD = Decimal("250")
# The recalibrated floor is NEVER raised ABOVE the committed default (recalibration only ever LOOSENS a
# mis-scaled fixed floor toward realized depth; it never makes the desk MORE restrictive than committed —
# that would be a tightening, which is a separate research decision).
COMMITTED_DEFAULT_FLOOR_USD = Decimal("1000")

# The recalibrated floor is a fraction of the THINNEST fundable pool's one-tick capacity cap: the
# smallest ticket the thinnest pool we would still trade can absorb. Anchored to realized depth, pinned.
FLOOR_FRAC_OF_THIN_CAPACITY = Decimal("0.5")

# A pool below this realized exit liquidity is too thin to be a fundable carry venue at all (not used to
# anchor the floor — anchoring on dust would drive the floor to HARD_MIN). Mirrors the repo $5M TVL
# floor's spirit at the EXIT-liquidity layer: a one-tick exit pool under this is not a real venue.
MIN_FUNDABLE_EXIT_LIQUIDITY_USD = Decimal("1000")


def flag_enabled() -> bool:
    """True iff SPA_RATE_FLOOR_RECAL is set to an ON value. DEFAULT OFF (unset / '0' / '' → False).
    Read per-call (no cached global) so an owner toggling the env takes effect without a reimport."""
    return os.environ.get(FLAG_ENV, "0") not in ("0", "", "false", "False", "off", "OFF")


def _surface_exit_liquidities(surface: dict) -> List[Decimal]:
    """Every positive realized one-tick exit liquidity on the surface (Decimal, fail-CLOSED skips
    malformed/non-positive). PURE."""
    out: List[Decimal] = []
    quotes = surface.get("quotes") if isinstance(surface, dict) else None
    if not isinstance(quotes, list):
        return out
    for q in quotes:
        if not isinstance(q, dict):
            continue
        el = _safe_decimal(q.get("exit_liquidity_usd"))
        if el is not None and el > D0:
            out.append(el)
    return out


def recalibrated_floor_usd(
    surface: dict,
    params: Optional[RatePolicyParams] = None,
) -> Decimal:
    """Derive the depth-anchored `min_tradeable_size_usd` from the REALIZED exit liquidities on the
    surface. PURE / deterministic / fail-CLOSED.

    floor = clamp( FLOOR_FRAC_OF_THIN_CAPACITY × (max_size_frac_of_exit × thinnest_fundable_depth),
                   HARD_MIN_FLOOR_USD, COMMITTED_DEFAULT_FLOOR_USD )

    where `thinnest_fundable_depth` = the MIN exit liquidity among pools at/above
    MIN_FUNDABLE_EXIT_LIQUIDITY_USD (anchoring on the thinnest pool we would still trade — conservative:
    it sets the floor to what the SMALLEST fundable venue can absorb, so the floor never excludes a real
    thin-but-fundable book). fail-CLOSED: NO fundable pool on the surface → keep the committed default
    (we do not loosen a floor we cannot evidence)."""
    p = params or RatePolicyParams()
    fundable = [el for el in _surface_exit_liquidities(surface)
                if el >= MIN_FUNDABLE_EXIT_LIQUIDITY_USD]
    if not fundable:
        return COMMITTED_DEFAULT_FLOOR_USD  # fail-CLOSED: no evidence → no loosening
    thinnest = min(fundable)
    frac = _safe_decimal(p.max_size_frac_of_exit) or D0
    thin_capacity_cap = frac * thinnest
    floor = FLOOR_FRAC_OF_THIN_CAPACITY * thin_capacity_cap
    # clamp into [HARD_MIN, COMMITTED_DEFAULT] — never below dust, never tighter than committed.
    if floor < HARD_MIN_FLOOR_USD:
        floor = HARD_MIN_FLOOR_USD
    if floor > COMMITTED_DEFAULT_FLOOR_USD:
        floor = COMMITTED_DEFAULT_FLOOR_USD
    return floor


def recalibrated_params(
    base: Optional[RatePolicyParams] = None,
    surface: Optional[dict] = None,
) -> RatePolicyParams:
    """Return a RatePolicyParams with ONLY `min_tradeable_size_usd` recalibrated from realized depth —
    when the flag is ON. When the flag is OFF, returns `base` UNCHANGED (the committed floor verbatim).

    HARD GUARDRAIL (asserted): the returned params differ from `base` in `min_tradeable_size_usd` AND
    NOTHING ELSE. Every toxicity veto field (`max_structural_haircut`, `max_total_haircut`, every k_* /
    cap_*) is byte-identical to `base`. Recalibrating the SIZE floor can NEVER touch the structural
    TAIL_VETO that refuses toxic books at step 1 — so no recalibration can re-admit a toxic book.

    fail-CLOSED: a missing/unreadable surface → the committed default floor (no loosening without
    evidence). PURE w.r.t. (base, surface) except for the one env read in flag_enabled()."""
    base = base or RatePolicyParams()
    if not flag_enabled():
        return base
    surf = surface if surface is not None else _read_surface()
    new_floor = recalibrated_floor_usd(surf, base)
    recal = dataclasses.replace(base, min_tradeable_size_usd=new_floor)
    # ── HARD GUARDRAIL: assert ONLY the size floor moved; every toxicity veto is untouched ──
    _assert_only_size_floor_changed(base, recal)
    return recal


def _assert_only_size_floor_changed(base: RatePolicyParams, recal: RatePolicyParams) -> None:
    """Assert recalibration touched ONLY `min_tradeable_size_usd`. ANY change to a toxicity-veto field
    (max_structural_haircut / max_total_haircut / k_* / cap_*) is a contract violation → raise. This is
    the code-level proof that a recalibrated floor can never be a vehicle for re-admitting a toxic book."""
    protected = (
        "max_structural_haircut", "max_total_haircut", "max_peg_distance",
        "max_oracle_staleness_s", "max_stable_depeg", "funding_flip_streak_kill",
        "k_peg", "cap_peg", "k_funding", "cap_funding", "k_oracle", "cap_oracle",
        "k_liquidity", "cap_liquidity", "k_protocol", "cap_protocol",
        "cost_buffer", "edge_hurdle", "max_size_frac_of_exit",
    )
    for f in protected:
        bv = getattr(base, f)
        rv = getattr(recal, f)
        if bv != rv:
            raise AssertionError(
                f"rate_floor_recal INVARIANT VIOLATED: recalibration changed protected veto field "
                f"{f!r} ({bv} -> {rv}). The floor recalibration may ONLY move min_tradeable_size_usd; "
                "a toxicity-veto change can never be smuggled through the size-floor recalibration.")
    # the floor itself must stay within the documented hard band
    if not (HARD_MIN_FLOOR_USD <= recal.min_tradeable_size_usd <= COMMITTED_DEFAULT_FLOOR_USD):
        raise AssertionError(
            f"rate_floor_recal INVARIANT VIOLATED: recalibrated floor "
            f"{recal.min_tradeable_size_usd} outside the hard band "
            f"[{HARD_MIN_FLOOR_USD}, {COMMITTED_DEFAULT_FLOOR_USD}]")


def _read_surface() -> dict:
    """Read the live rate surface (fail-CLOSED: missing/unreadable → empty dict → committed floor)."""
    import json
    try:
        return json.loads(_SURFACE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def recal_report(base: Optional[RatePolicyParams] = None, surface: Optional[dict] = None) -> dict:
    """A small honest report of the recalibration decision (for audit / the proof chain / a CLI). PURE."""
    base = base or RatePolicyParams()
    surf = surface if surface is not None else _read_surface()
    fundable = [el for el in _surface_exit_liquidities(surf)
                if el >= MIN_FUNDABLE_EXIT_LIQUIDITY_USD]
    floor = recalibrated_floor_usd(surf, base)
    return {
        "flag": FLAG_ENV,
        "flag_enabled": flag_enabled(),
        "committed_floor_usd": str(COMMITTED_DEFAULT_FLOOR_USD),
        "hard_min_floor_usd": str(HARD_MIN_FLOOR_USD),
        "n_fundable_pools": len(fundable),
        "thinnest_fundable_exit_liquidity_usd": str(min(fundable)) if fundable else None,
        "recalibrated_floor_usd": str(floor),
        "effective_floor_usd": str(floor if flag_enabled() else COMMITTED_DEFAULT_FLOOR_USD),
        "max_size_frac_of_exit": str(base.max_size_frac_of_exit),
        "note": ("EVIDENCE-BASED size-floor recalibration. ONLY min_tradeable_size_usd moves; every "
                 "structural/economic veto (incl. the toxicity TAIL_VETO at step 1) is byte-identical "
                 "→ a recalibrated floor can never re-admit a toxic book. Owner-tunable, default OFF."),
    }


def main() -> int:
    import json
    print(json.dumps(recal_report(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
