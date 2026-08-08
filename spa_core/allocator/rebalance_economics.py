"""Yield-improvement rebalance trigger — economics + anti-churn (ADR-060).

Answers ONE question, deterministically: *is moving capital from the current book
to the proposed one worth what the move costs?*

It grants no new permission. RiskPolicy, the kill-switch, the SOFT de-risk gate and
the enforcer decide what is ALLOWED; this module only decides whether an allowed
move is WORTH making. It can say HOLD, never "override".

Phase 0 (this file's only live use): SHADOW. ``evaluate()`` is pure — it reads
nothing and writes nothing — and the cycle records its verdict in
``data/allocation_rationale.json`` without touching a single position. Arming it
is a separate, owner-gated step (ADR-060 §4).

LLM forbidden. Pure stdlib. Deterministic: same inputs → same verdict.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from spa_core.risk.tvl_floor import floor_is_resolved, floor_reason

# Per-move cost inputs are REUSED from the existing Tier-1 cost model rather than
# re-invented, so a gas/slippage assumption exists in exactly one place.
try:
    from spa_core.backtesting.tier1.cost_model import (
        GAS_USD_PER_POSITION_CHANGE,
        SLIPPAGE_BPS_STABLE,
        BRIDGE_BPS,
    )
except Exception:  # pragma: no cover — import guard keeps the cycle safe
    GAS_USD_PER_POSITION_CHANGE = {
        "ethereum": 12.0, "mainnet": 12.0, "arbitrum": 0.25, "optimism": 0.25,
        "base": 0.15, "polygon": 0.05, "blended": 1.5,
    }
    SLIPPAGE_BPS_STABLE = 8.0
    BRIDGE_BPS = 5.0

_EPS = 1e-9
_DAYS_YEAR = 365.0


@dataclass(frozen=True)
class TriggerParams:
    """Owner-gated dials (ADR-060 §3). NOT RiskPolicy thresholds.

    These decide whether a PERMITTED move is worth making; they can never widen a
    cap. Paper defaults below; the real-capital column of ADR-060 §3 is applied by
    passing an explicit instance.
    """
    min_gain_pp: float = 0.50            # min blended-APY gain, pp of TOTAL capital
    max_payback_days: float = 30.0       # cost must repay within this horizon
    min_hold_days: int = 3               # a fresh position is not churned out
    act_cooldown_days: int = 3           # at most one yield-driven move per window
    max_turnover_per_move: float = 0.15  # ≤15 % of capital in one move
    max_turnover_per_week: float = 0.25  # ≤25 % of capital per rolling week
    min_leg_frac: float = 0.005          # dust legs (<0.5 % of capital) are skipped
    reversal_window_days: int = 14       # window in which a reversal is penalised
    reversal_escalation: float = 1.5     # gain threshold ×N when reversing
    below_median_cap_factor: float = 0.5  # below-median yield ⇒ ≤ half the tier cap


@dataclass
class Decision:
    """Verdict + every number behind it. Serialised verbatim into the artifact."""
    decision: str                        # "ACT" | "HOLD"
    reasons: List[str] = field(default_factory=list)
    apy_now_pp: float = 0.0
    apy_opt_pp: float = 0.0
    gain_pp: float = 0.0
    required_gain_pp: float = 0.0
    cost_usd: float = 0.0
    cost_pp: float = 0.0
    payback_days: Optional[float] = None
    turnover_usd: float = 0.0
    turnover_frac: float = 0.0
    legs: List[dict] = field(default_factory=list)
    gates: Dict[str, bool] = field(default_factory=dict)
    evidence: Dict[str, list] = field(default_factory=dict)
    cash: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _blended_apy_pp(
    positions: Dict[str, float],
    apy_pct: Dict[str, float],
    capital_usd: float,
    evidenced: set,
) -> Tuple[float, List[str]]:
    """Blended APY over TOTAL capital; unevidenced positions contribute ZERO.

    Two deliberate choices:

    * **Total capital, not deployed capital.** On a deployed-only base, moving idle
      cash into a pool shows up as no improvement at all, so the trigger would never
      fire on the one change that matters most.
    * **Unevidenced ⇒ 0.** "What we cannot evidence, we did not earn." Crediting a
      position its literal APY would let an unobservable pool defend itself against
      a move into an observable one — exactly backwards. This makes opacity
      expensive instead of free.
    """
    if capital_usd <= 0:
        return 0.0, ["capital_usd<=0"]
    total = 0.0
    unevidenced: List[str] = []
    for proto, usd in (positions or {}).items():
        amount = float(usd or 0.0)
        if amount <= 0:
            continue
        if proto not in evidenced:
            unevidenced.append(proto)
            continue
        total += (amount / capital_usd) * float(apy_pct.get(proto, 0.0) or 0.0)
    return total, sorted(unevidenced)


def _legs(
    current: Dict[str, float],
    target: Dict[str, float],
    capital_usd: float,
    min_leg_frac: float,
) -> Tuple[List[dict], float]:
    """Per-protocol deltas above the dust band, plus one-sided turnover in USD."""
    min_leg_usd = max(0.0, min_leg_frac) * capital_usd
    legs: List[dict] = []
    increases = 0.0
    decreases = 0.0
    for proto in sorted(set(current) | set(target)):
        delta = float(target.get(proto, 0.0) or 0.0) - float(current.get(proto, 0.0) or 0.0)
        if abs(delta) <= min_leg_usd + _EPS:
            continue   # dust: pays full gas, moves nothing worth moving
        legs.append({"protocol": proto, "delta_usd": round(delta, 2),
                     "direction": "increase" if delta > 0 else "decrease"})
        if delta > 0:
            increases += delta
        else:
            decreases += -delta
    # One-sided turnover = capital ACTUALLY relocated, i.e. max(bought, sold).
    #
    # A plain gross/2 is only right when every buy is funded by a matching sell.
    # Deploying idle cash has no sell leg, so gross/2 would halve the real turnover
    # — understating both the slippage cost and the turnover budget on exactly the
    # move the trigger most wants to make. max() is correct in both shapes: for a
    # matched swap it equals gross/2, for a pure deployment it equals the amount
    # deployed. (Caught by test_a_large_clear_gain_acts.)
    return legs, max(increases, decreases)


def _move_cost_usd(legs: List[dict], turnover_usd: float, chains: Dict[str, str]) -> float:
    """USD cost of executing ``legs``: gas per touched position + slippage + bridge.

    Per-MOVE, not annualised — the benefit is a rate, the cost is paid once, and
    ``payback_days`` is what makes them comparable.
    """
    gas = 0.0
    touched_chains = set()
    for leg in legs:
        chain = str(chains.get(leg["protocol"], "blended")).lower()
        gas += float(GAS_USD_PER_POSITION_CHANGE.get(
            chain, GAS_USD_PER_POSITION_CHANGE.get("blended", 1.5)))
        touched_chains.add(chain)
    slippage = turnover_usd * (SLIPPAGE_BPS_STABLE / 10_000.0)
    bridge = (turnover_usd * (BRIDGE_BPS / 10_000.0)) if len(touched_chains) > 1 else 0.0
    return gas + slippage + bridge


def evaluate(
    *,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    apy_pct: Dict[str, float],
    evidenced: set,
    chains: Dict[str, str],
    capital_usd: float,
    params: Optional[TriggerParams] = None,
    days_since_last_act: Optional[float] = None,
    position_age_days: Optional[Dict[str, float]] = None,
    turnover_last_week_usd: float = 0.0,
    last_move_legs: Optional[Dict[str, float]] = None,
    days_since_last_move: Optional[float] = None,
    tvl_evidenced: Optional[set] = None,
) -> Decision:
    """Decide whether moving ``current`` → ``target`` is worth its cost.

    Fail-CLOSED throughout: anything that cannot be computed yields HOLD with a
    named reason, never an optimistic guess. ``ACT`` means only "the economics
    justify this move"; admissibility was already decided upstream.
    """
    p = params or TriggerParams()
    d = Decision(decision="HOLD")

    if capital_usd <= 0:
        d.reasons.append("invalid_capital")
        return d

    current_positions = {k: float(v or 0.0) for k, v in (current_positions or {}).items()}
    target_positions = {k: float(v or 0.0) for k, v in (target_positions or {}).items()}

    # ── L1: the two comparable numbers ─────────────────────────────────────
    d.apy_now_pp, unev_now = _blended_apy_pp(current_positions, apy_pct, capital_usd, evidenced)
    d.apy_opt_pp, unev_opt = _blended_apy_pp(target_positions, apy_pct, capital_usd, evidenced)
    d.gain_pp = round(d.apy_opt_pp - d.apy_now_pp, 6)
    d.apy_now_pp = round(d.apy_now_pp, 6)
    d.apy_opt_pp = round(d.apy_opt_pp, 6)
    d.evidence = {
        "unevidenced_held": unev_now,
        "unevidenced_in_target": unev_opt,
        "tvl_unevidenced_in_target": sorted(
            proto for proto in target_positions
            if tvl_evidenced is not None
            and target_positions[proto] > 0
            and proto not in tvl_evidenced
        ),
    }
    if unev_opt:
        # Funding something we cannot observe is not an improvement, whatever the
        # arithmetic says. Upstream gates should already prevent it; if one slips
        # through, the trigger refuses rather than endorses.
        d.reasons.append("target_contains_unevidenced:{}".format(unev_opt))
    if d.evidence["tvl_unevidenced_in_target"]:
        # Not a veto here (the TVL floor is RiskPolicy's job) but the recommendation
        # is unsound while a target pool clears the floor on a literal — say so.
        d.warnings.append(
            "tvl_not_evidenced_for:{} — floor cleared on a literal, recommendation "
            "is not sound until the TVL source is live".format(
                d.evidence["tvl_unevidenced_in_target"]))

    # ── L1: cost of the move ───────────────────────────────────────────────
    d.legs, d.turnover_usd = _legs(current_positions, target_positions, capital_usd, p.min_leg_frac)
    d.turnover_usd = round(d.turnover_usd, 2)
    d.turnover_frac = round(d.turnover_usd / capital_usd, 6)
    if not d.legs:
        d.reasons.append("no_material_legs")
        d.gates = {"has_legs": False}
        return d

    d.cost_usd = round(_move_cost_usd(d.legs, d.turnover_usd, chains), 2)
    d.cost_pp = round(100.0 * d.cost_usd / capital_usd, 6)
    d.payback_days = (
        round(_DAYS_YEAR * d.cost_pp / d.gain_pp, 2)
        if d.gain_pp > _EPS else None
    )

    # ── L2: hysteresis — a reversal must clear a HIGHER bar ────────────────
    required = p.min_gain_pp
    reversing: List[str] = []
    if last_move_legs and days_since_last_move is not None \
            and days_since_last_move <= p.reversal_window_days:
        for leg in d.legs:
            prior = float(last_move_legs.get(leg["protocol"], 0.0) or 0.0)
            if prior * leg["delta_usd"] < 0:   # opposite sign ⇒ undoing the last move
                reversing.append(leg["protocol"])
    if reversing:
        required *= p.reversal_escalation
        d.reasons.append("reversal_of_recent_move:{}".format(sorted(reversing)))
    d.required_gain_pp = round(required, 6)

    # ── L2: anti-churn gates ───────────────────────────────────────────────
    cooldown_ok = days_since_last_act is None or days_since_last_act >= p.act_cooldown_days
    min_hold_ok = True
    too_fresh: List[str] = []
    for leg in d.legs:
        if leg["delta_usd"] >= 0:
            continue   # min-hold restrains SELLING a fresh position, not buying
        age = (position_age_days or {}).get(leg["protocol"])
        if age is not None and age < p.min_hold_days:
            too_fresh.append(leg["protocol"])
    if too_fresh:
        min_hold_ok = False
        d.reasons.append("positions_below_min_hold:{}".format(sorted(too_fresh)))

    move_budget_ok = d.turnover_frac <= p.max_turnover_per_move + _EPS
    week_budget_ok = (
        (turnover_last_week_usd + d.turnover_usd) / capital_usd
        <= p.max_turnover_per_week + _EPS
    )
    gain_ok = d.gain_pp >= required - _EPS
    payback_ok = d.payback_days is not None and d.payback_days <= p.max_payback_days + _EPS

    d.gates = {
        "has_legs": True,
        "gain_above_band": bool(gain_ok),
        "payback_within_horizon": bool(payback_ok),
        "cooldown_ok": bool(cooldown_ok),
        "min_hold_ok": bool(min_hold_ok),
        "move_turnover_ok": bool(move_budget_ok),
        "week_turnover_ok": bool(week_budget_ok),
        "target_fully_evidenced": not unev_opt,
    }

    if not gain_ok:
        d.reasons.append("gain_below_band:{:.3f}pp<{:.3f}pp".format(d.gain_pp, required))
    if not payback_ok:
        d.reasons.append(
            "payback_too_long:{}".format(
                "undefined" if d.payback_days is None else "{:.1f}d".format(d.payback_days)))
    if not cooldown_ok:
        d.reasons.append("cooldown_active:{:.1f}d<{}d".format(
            days_since_last_act or 0.0, p.act_cooldown_days))
    if not move_budget_ok:
        d.reasons.append("move_turnover_over_budget:{:.1%}>{:.0%}".format(
            d.turnover_frac, p.max_turnover_per_move))
    if not week_budget_ok:
        d.reasons.append("week_turnover_over_budget")

    d.decision = "ACT" if all(d.gates.values()) else "HOLD"
    if d.decision == "ACT":
        d.reasons.append("gain {:.3f}pp ≥ {:.3f}pp, cost ${:.2f} repays in {:.1f}d".format(
            d.gain_pp, required, d.cost_usd, d.payback_days or 0.0))
    return d


def explain_cash(
    *,
    positions: Dict[str, float],
    capital_usd: float,
    min_cash_frac: float,
    binders: Optional[List[dict]] = None,
) -> Dict[str, object]:
    """Attribute every idle dollar above the buffer (ADR-055 invariant).

    Idle capital must be a logged decision, never a default. Whatever the named
    binders do not explain is published as ``unexplained_pct`` — a number a monitor
    can act on — instead of quietly rounding to "fine".
    """
    if capital_usd <= 0:
        return {"error": "invalid_capital"}
    deployed = sum(float(v or 0.0) for v in (positions or {}).values())
    cash_pct = 100.0 * (capital_usd - deployed) / capital_usd
    buffer_pct = 100.0 * min_cash_frac
    excess_pct = max(0.0, cash_pct - buffer_pct)
    attributed = sum(float(b.get("pct", 0.0) or 0.0) for b in (binders or []))
    unexplained = round(max(0.0, excess_pct - attributed), 4)

    # Three states, not two. The invariant (ADR-055) is that idle capital must be a
    # LOGGED DECISION rather than a default — it is not that every dollar must be
    # split numerically. A first version had only explained/UNEXPLAINED, so a cycle
    # that named eleven blocked protocols — a complete and sufficient reason for the
    # idle cash — still reported UNEXPLAINED_CASH. Naming the cause and then calling
    # it unexplained is the same cry-wolf failure this project keeps paying for: the
    # alarm stops meaning anything and the real case (no reason at all) hides in it.
    if excess_pct <= 1e-6:
        status = "explained"                 # nothing above the buffer to explain
    elif unexplained <= 1e-6:
        status = "explained"                 # binders cover it quantitatively
    elif binders:
        status = "named_not_quantified"      # cause is on record, split is not
    else:
        status = "UNEXPLAINED_CASH"          # genuinely silent idle capital
    return {
        "cash_pct": round(cash_pct, 4),
        "buffer_pct": round(buffer_pct, 4),
        "excess_pct": round(excess_pct, 4),
        "attribution": list(binders or []),
        "attributed_pct": round(attributed, 4),
        "unexplained_pct": unexplained,
        "status": status,
    }


def attribute_cash(
    *,
    positions: Dict[str, float],
    capital_usd: float,
    min_cash_frac: float,
    apy_pct: Dict[str, float],
    apy_sources: Optional[Dict[str, str]],
    tvl_live: Optional[set],
    tier_caps: Optional[Dict[str, float]],
    tiers: Optional[Dict[str, Optional[str]]],
    t2_total_cap: Optional[float],
    t3_total_cap: Optional[float],
    min_apy_pct: Optional[float],
    tvl_usd: Optional[Dict[str, float]] = None,
    min_tvl_usd: Optional[float] = None,
    blocked: Optional[Dict[str, str]] = None,
    external_binders: Optional[List[dict]] = None,
    policy_refusals: Optional[List[dict]] = None,
) -> Dict[str, object]:
    """Deterministic attribution of every idle dollar (ADR-055 invariant, task Y2).

    Decomposes the book's cash into named components, each with USD and an
    estimate of forgone yield (bps/yr over TOTAL capital, from live APYs):

      (а) ``min_cash_buffer``            — the policy floor (never "forgone");
      (д) ``unexplained_deployable``     — room fundable RIGHT NOW under every cap
          with live APY+TVL evidence, left unfilled. THIS and only this is the
          honest LAZY signal (status ``UNEXPLAINED_CASH``);
      (в) ``aggregate_cap``              — per-protocol headroom throttled by the
          T2-total / T3-total caps;
      (г) ``insufficient_eligible_live`` — room that exists only in protocols we
          may not fund: blocked (advisory/GSM), stale APY feed, no live TVL
          (ADR-053 freeze), TVL below the RiskPolicy floor / unmeasured
          (``min_tvl_usd``, MP-011 — the SAME rule the allocator applies, see
          :mod:`spa_core.risk.tvl_floor`), or APY below the entry floor;
      (б) ``per_protocol_cap``           — what remains when every fundable
          protocol is (or in the counterfactual max-fill becomes) pinned at its
          40 %/20 % tier cap.

    Waterfall order is FIXED and part of the contract (like tax brackets):
    buffer → (д) → (в) → (г) → (б). It is deliberate: room we could legally use
    today is charged to the allocator BEFORE any cap is blamed, so a cap can
    never launder laziness.

    Fail-CLOSED (task step 3): a component whose inputs are missing (no cap
    config, no APY provenance, no TVL provenance) is reported as ``UNCHECKED``
    with the whole attribution stamped ``attribution_incomplete`` — never as a
    silent zero that would make the cash look explained.

    ``policy_refusals`` — what the RiskPolicy gate REMOVED from this cycle's
    target AFTER the allocator built it (ADR-053 TVL-evidence freeze: a pool
    without an observed live TVL gets no fresh capital). Each entry:
    ``{"protocol", "reason", "usd_removed_from_target"}``. It is PROVENANCE,
    not a binder: it does **not** move a single dollar between components and
    does not shrink ``unexplained_deployable``. Deliberately so — the refusal
    explains where the cash CAME FROM, but the room it left is still fundable
    elsewhere today (measured 2026-08-06: the freeze zeroed 10 % of the target
    and nothing re-filled it, while morpho_steakhouse/compound_v3 headroom
    stood open). Charging it as a binder would let a fail-closed refusal
    launder a missing re-fill — the same laundering the waterfall order exists
    to prevent. So the number stays honest and the CAUSE stops being anonymous:
    ``unexplained_deployable`` carries ``caused_by`` and the artifact carries
    ``policy_refusals``.

    ``tvl_usd`` / ``min_tvl_usd`` — the pool's observed TVL and the RiskPolicy
    floor (both INPUTS, resolved by the caller from the allocator's own feed map
    and ``RiskConfig``). Until 08.08 the eligibility check knew only the
    PROVENANCE of TVL (``proto in tvl_live``) and nothing about its SIZE, while
    the allocator applies the floor (``_filter_by_tvl``, MP-011) — so a pool the
    allocator had filtered out (measured: ``moonwell_base``, TVL $1.41M vs the
    $5M floor) still stood in "fundable headroom" and its room was charged to the
    allocator as laziness. Two definitions of one thing; the fail-CLOSED one wins.
    Missing floor / missing TVL map ⇒ ``tvl_floor_unresolved`` in ``unchecked``
    (attribution_incomplete) — never a silent pass, and never a silent *fail*
    either: a per-protocol-only rule would let a missing map empty the fundable
    set and mute the LAZY alarm, which is the failure this project keeps paying for.

    Pure and deterministic: reads nothing, writes nothing, changes no cap.
    RiskPolicy values are INPUTS here, resolved by the caller from RiskConfig.
    """
    refusals: List[dict] = []
    for r in policy_refusals or []:
        if not isinstance(r, dict) or not r.get("protocol"):
            continue
        try:
            usd = float(r.get("usd_removed_from_target") or 0.0)
        except (TypeError, ValueError):
            usd = 0.0
        refusals.append({
            "protocol": str(r["protocol"]),
            "reason": str(r.get("reason") or "unnamed_refusal"),
            "usd_removed_from_target": round(usd, 2),
            "pct_of_capital": (round(100.0 * usd / capital_usd, 4)
                               if capital_usd > 0 else None),
        })
    if capital_usd <= 0:
        return {"status": "error", "error": "invalid_capital"}

    positions = {k: float(v or 0.0) for k, v in (positions or {}).items()}
    deployed = sum(v for v in positions.values() if v > 0)
    cash_usd = capital_usd - deployed
    cash_pct = 100.0 * cash_usd / capital_usd
    buffer_frac = max(0.0, float(min_cash_frac))
    buffer_usd = min(max(cash_usd, 0.0), buffer_frac * capital_usd)
    excess_usd = max(0.0, cash_usd - buffer_frac * capital_usd)

    def _comp(kind: str, usd: float, *, forgone_bps: Optional[float] = None,
              detail: str = "", protocols: Optional[list] = None,
              status: str = "OK") -> dict:
        c: dict = {"kind": kind, "usd": round(usd, 2),
                   "pct": round(100.0 * usd / capital_usd, 4), "status": status}
        if forgone_bps is not None:
            c["forgone_bps_yr"] = round(forgone_bps, 1)
        if detail:
            c["detail"] = detail
        if protocols is not None:
            c["protocols"] = protocols
        return c

    components: List[dict] = [
        _comp("min_cash_buffer", buffer_usd, forgone_bps=0.0,
              detail="policy min-cash floor {:.0f}% — mandated, not forgone".format(
                  buffer_frac * 100.0)),
    ]
    out_base = {
        "capital_usd": capital_usd,
        "cash_pct": round(cash_pct, 4),
        "buffer_pct": round(buffer_frac * 100.0, 4),
        "excess_pct": round(100.0 * excess_usd / capital_usd, 4),
    }

    # External, caller-supplied binders (legacy path): named causes with their own
    # pct. They shrink the pool the waterfall must attribute — a cause already on
    # record is not re-attributed — but can never push it below zero.
    remaining = excess_usd
    for b in external_binders or []:
        pct = float(b.get("pct", 0.0) or 0.0)
        usd = pct / 100.0 * capital_usd
        components.append(_comp("external_binder", min(usd, remaining),
                                detail=str(b.get("reason", ""))))
        remaining = max(0.0, remaining - usd)

    if excess_usd <= 1e-6:
        return {**out_base, "components": components,
                "explained_pct": out_base["cash_pct"], "unexplained_pct": 0.0,
                "unchecked": [], "status": "explained",
                "policy_refusals": refusals}

    # ── fail-CLOSED gate: every dimension the split depends on must be present ──
    unchecked: List[str] = []
    if tier_caps is None or tiers is None or min_apy_pct is None:
        unchecked.append("risk_caps_unresolved")
    if t2_total_cap is None or t3_total_cap is None:
        unchecked.append("aggregate_caps_unresolved")
    if apy_sources is None:
        unchecked.append("apy_provenance_unavailable")
    if tvl_live is None:
        unchecked.append("tvl_provenance_unavailable")
    # The floor is a dimension of eligibility like any other: unresolvable ⇒ the
    # split is UNCHECKED, not "everything qualifies" (old behaviour) and not
    # "nothing qualifies" (which would silence the alarm by losing an input).
    # An EMPTY map over a non-empty universe is the same "could not look": left
    # alone it would make every pool ineligible, the cash "explained", and the
    # LAZY alarm quiet — silence bought by losing an input, not by a better book.
    _tvl_map = tvl_usd if tvl_usd is not None else {}
    _candidates = set(apy_sources or {}) | set(positions) | set(blocked or {})
    if tvl_usd is None or (not _tvl_map and _candidates) or not floor_is_resolved(min_tvl_usd):
        unchecked.append("tvl_floor_unresolved")
    if unchecked:
        components.append(_comp(
            "unattributed", remaining, status="UNCHECKED",
            detail="cannot split (б)/(в)/(г)/(д): missing " + ", ".join(unchecked)))
        return {**out_base, "components": components,
                "explained_pct": round(100.0 * (cash_usd - remaining) / capital_usd, 4),
                "unexplained_pct": None,   # honestly unknown — NOT zero
                "unchecked": unchecked, "status": "attribution_incomplete",
                "policy_refusals": refusals}

    # ── classify every candidate protocol's headroom ────────────────────────
    universe = set(apy_sources) | set(positions) | set(blocked or {})
    fundable: Dict[str, float] = {}          # proto → room USD (all gates pass)
    non_eligible: Dict[str, Tuple[float, List[str]]] = {}   # proto → (room, why)
    at_cap: List[str] = []
    tier_unknown: List[str] = []
    held_by_tier = {"T1": 0.0, "T2": 0.0, "T3": 0.0}
    fundable_by_tier = {"T1": 0.0, "T2": 0.0, "T3": 0.0}

    for proto in sorted(universe):
        held = max(0.0, positions.get(proto, 0.0))
        tier = tiers.get(proto)
        tier = str(tier).upper() if tier else None
        cap_frac = tier_caps.get(proto)
        if held > 0 and tier in held_by_tier:
            held_by_tier[tier] += held
        if tier not in ("T1", "T2", "T3") or cap_frac is None:
            tier_unknown.append(proto)
            continue
        room = max(0.0, float(cap_frac) * capital_usd - held)
        if room <= 1e-6:
            if held > 0:
                at_cap.append("{}@{:.0f}%".format(proto, float(cap_frac) * 100.0))
            continue
        why: List[str] = []
        if blocked and proto in blocked:
            why.append("blocked:{}".format(blocked[proto]))
        src = apy_sources.get(proto)
        if src != "live":
            why.append("apy_not_live" if src else "apy_source_missing")
        elif float(apy_pct.get(proto, 0.0) or 0.0) < float(min_apy_pct):
            why.append("apy_below_min:{:.2f}%<{:.2f}%".format(
                float(apy_pct.get(proto, 0.0) or 0.0), float(min_apy_pct)))
        if proto not in tvl_live:
            why.append("tvl_not_live")
        # MP-011 floor — the allocator's rule, not a second copy of it.
        _floor_ok, _floor_why = floor_reason(_tvl_map.get(proto), min_tvl_usd)
        if not _floor_ok:
            why.append(_floor_why)
        if why:
            non_eligible[proto] = (room, why)
        else:
            fundable[proto] = room
            fundable_by_tier[tier] += room

    # ── aggregate caps throttle the fundable T2/T3 rooms ────────────────────
    t2_agg_room = max(0.0, float(t2_total_cap) * capital_usd - held_by_tier["T2"])
    t3_agg_room = max(0.0, float(t3_total_cap) * capital_usd - held_by_tier["T3"])
    eff_t2 = min(fundable_by_tier["T2"], t2_agg_room)
    eff_t3 = min(fundable_by_tier["T3"], t3_agg_room)
    throttled = (fundable_by_tier["T2"] - eff_t2) + (fundable_by_tier["T3"] - eff_t3)
    fundable_total = fundable_by_tier["T1"] + eff_t2 + eff_t3

    def _best_apy(protos) -> float:
        vals = [float(apy_pct.get(p, 0.0) or 0.0) for p in protos]
        return max(vals) if vals else 0.0

    # (д) deployable-but-idle — charged FIRST, so caps can't launder laziness.
    deployable = min(remaining, fundable_total)
    unexplained_usd = 0.0
    if deployable > 1e-6:
        best = _best_apy(fundable)
        # ADR-055: "idle without a recorded reason" was a LIE whenever the
        # policy gate had already named one. The dollars stay unexplained (they
        # remain placeable), but the cause is no longer anonymous.
        _detail = ("fundable headroom under every cap with live APY+TVL — "
                   "idle without a recorded reason")
        if refusals:
            _detail = (
                "fundable headroom under every cap with live APY+TVL — still "
                "placeable today, but ${:,.0f} of this cycle's target was "
                "removed after the allocator by: {} (see policy_refusals); "
                "nothing re-filled the freed budget".format(
                    sum(r["usd_removed_from_target"] for r in refusals),
                    ", ".join("{}:{}".format(r["protocol"], r["reason"])
                              for r in refusals)))
        _c = _comp(
            "unexplained_deployable", deployable,
            forgone_bps=(deployable / capital_usd) * best * 100.0,
            detail=_detail,
            protocols=["{}(+${:,.0f} @ {:.2f}%)".format(p, fundable[p],
                       float(apy_pct.get(p, 0.0) or 0.0))
                       for p in sorted(fundable, key=lambda x: -fundable[x])[:6]])
        if refusals:
            _c["caused_by"] = list(refusals)
        components.append(_c)
        unexplained_usd = deployable
        remaining -= deployable

    # (в) aggregate caps (T2-total / T3-total).
    if remaining > 1e-6 and throttled > 1e-6:
        take = min(remaining, throttled)
        throttled_protos = [p for p in fundable
                            if tiers.get(p) and str(tiers[p]).upper() in ("T2", "T3")]
        components.append(_comp(
            "aggregate_cap", take,
            forgone_bps=(take / capital_usd) * _best_apy(throttled_protos) * 100.0,
            detail="per-protocol T2/T3 headroom throttled by t2_total {:.0f}% / "
                   "t3_total {:.0f}%".format(float(t2_total_cap) * 100.0,
                                             float(t3_total_cap) * 100.0),
            protocols=sorted(throttled_protos)))
        remaining -= take

    # (г) room that exists only behind missing evidence / blocks.
    if remaining > 1e-6 and non_eligible:
        room_total = sum(r for r, _ in non_eligible.values())
        take = min(remaining, room_total)
        components.append(_comp(
            "insufficient_eligible_live", take,
            forgone_bps=(take / capital_usd) * _best_apy(non_eligible) * 100.0,
            detail="headroom only in protocols without live evidence "
                   "(stale feed / no live TVL / blocked / below APY floor) — "
                   "fail-closed keeps them unfunded",
            protocols=["{}(${:,.0f}: {})".format(p, non_eligible[p][0],
                       ",".join(non_eligible[p][1])) for p in sorted(non_eligible)]))
        remaining -= take

    # (б) per-protocol caps — the terminal bucket when the fundable universe is
    # pinned at 40 %/20 % (held at cap, or filled to cap in the counterfactual).
    if remaining > 1e-6:
        if at_cap or fundable:
            filled_to_cap = at_cap + ["{}@cap(counterfactual)".format(p)
                                      for p in sorted(fundable)]
            components.append(_comp(
                "per_protocol_cap", remaining,
                forgone_bps=(remaining / capital_usd)
                * _best_apy([c.split("@")[0] for c in at_cap] + list(fundable)) * 100.0,
                detail="every fundable protocol capped at its tier limit "
                       "(T1 40% / T2 20%)",
                protocols=filled_to_cap))
            remaining = 0.0
        elif tier_unknown:
            components.append(_comp(
                "unattributed", remaining, status="UNCHECKED",
                detail="tier unknown for {} — rooms uncomputable".format(
                    sorted(tier_unknown))))
            unchecked.append("tier_unknown:{}".format(sorted(tier_unknown)))
            remaining = 0.0
        else:
            components.append(_comp(
                "insufficient_eligible_live", remaining,
                forgone_bps=0.0,
                detail="no eligible protocol exists at all — universe empty",
                protocols=[]))
            remaining = 0.0

    # ПРОВЕНАНС непригодности (карточка 07.08). Водопад распределяет ДОЛЛАРЫ, и
    # бакет (г) появляется только если до него дошли деньги: при достаточной
    # пригодной комнате пул ниже порога исчезал из отчёта МОЛЧА. Ретайр молчанием —
    # ровно то, что карточка запрещает. Поэтому причина публикуется всегда,
    # отдельно от долларов: ни один компонент от этого не меняется на цент.
    ineligible_rooms = [
        {"protocol": p_, "room_usd": round(room, 2),
         "pct_of_capital": round(100.0 * room / capital_usd, 4), "why": list(why_)}
        for p_, (room, why_) in sorted(non_eligible.items())
    ]

    explained_usd = cash_usd - unexplained_usd
    if unchecked:
        status = "attribution_incomplete"
    elif unexplained_usd > 1e-6:
        status = "UNEXPLAINED_CASH"
    else:
        status = "explained"
    return {
        **out_base,
        "components": components,
        "explained_pct": round(100.0 * explained_usd / capital_usd, 4),
        "unexplained_pct": (round(100.0 * unexplained_usd / capital_usd, 4)
                            if not unchecked else None),
        "unchecked": unchecked,
        "status": status,
        "policy_refusals": refusals,
        "ineligible_rooms": ineligible_rooms,
    }


def below_median_cap_violations(
    *,
    positions: Dict[str, float],
    apy_pct: Dict[str, float],
    tier_caps: Dict[str, float],
    capital_usd: float,
    evidenced: set,
    factor: float = 0.5,
) -> List[dict]:
    """Protocols funded above ``factor × tier_cap`` while yielding below the median.

    Encodes the risk-engine rule "concentration follows yield/risk, not the inertia
    of an old target". Advisory here: it reports, it does not clamp.
    """
    ranked = sorted(
        apy_pct[p] for p in positions
        if p in evidenced and float(positions.get(p, 0.0) or 0.0) > 0 and p in apy_pct
    )
    if len(ranked) < 3 or capital_usd <= 0:
        return []   # a median over fewer than three pools is noise, not a signal
    mid = len(ranked) // 2
    median = ranked[mid] if len(ranked) % 2 else (ranked[mid - 1] + ranked[mid]) / 2.0
    out: List[dict] = []
    for proto, usd in (positions or {}).items():
        amount = float(usd or 0.0)
        if amount <= 0 or proto not in evidenced:
            continue
        apy = float(apy_pct.get(proto, 0.0) or 0.0)
        cap = float(tier_caps.get(proto, 0.0) or 0.0)
        if cap <= 0 or apy >= median:
            continue
        share = amount / capital_usd
        if share > cap * factor + _EPS:
            out.append({
                "protocol": proto, "apy_pct": round(apy, 4),
                "median_apy_pct": round(median, 4),
                "share": round(share, 6), "tier_cap": round(cap, 6),
                "allowed_share": round(cap * factor, 6),
            })
    return sorted(out, key=lambda r: r["protocol"])
