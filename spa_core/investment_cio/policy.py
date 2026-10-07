"""Investment CIO — allocation policy (ADR-554 WP-A03, revised-after-review rules 1-10).

``recommend(sleeves_doc, previous, now)`` is a PURE function: same input -> byte-identical JSON
output (including ``recommendation_id``). It never touches the filesystem, the clock (besides the
``now`` it is handed) or any RNG. Ledger / lineage / snapshotting live in ``ledger.py``; this module
only computes the recommendation object defined by ``contract.REC_FIELDS``.

# LLM_FORBIDDEN — deterministic, reproducible from the same inputs (ADR-554 boundary).

Design notes for the next reader (also reported to the caller, since ``contract.py`` is frozen and
these are judgement calls made where the contract is silent):

* **Mechanism cap** (WP-A03 rule 2, "Engine mechanic caps ... apply on top, regardless of maturity").
  ``contract.SLEEVE_FIELDS`` has no dedicated field for this. We look, in order: (a) a numeric
  ``mechanism_cap_pct`` key inside the sleeve's ``risk`` structured field (a cell-less dict), (b) the
  static fallback table ``MECHANISM_CAPS`` below (currently only ``leveraged_loop: 0.10``, the ADR's
  own example). A future contract revision could promote this to a first-class cell.
* **Return gate hurdle** (rule 3) is read from ``sleeves_doc["hurdle"]`` (a contract cell, if the
  caller supplies it). Cost-amortisation is NOT implemented (no switching-cost evidence exists yet
  per WP-S04) — the gate compares the sleeve's raw ``realized_return`` against the hurdle and this
  limitation is named in the rationale.
* **"Remainder to cash"** (rule 5) is read literally: sleeve weights are capped independently (no
  redistribution of a capped sleeve's excess to its peers) and whatever is left of the 1.0 risk
  budget is cash, before the look-through cash-floor pass.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.investment_cio import contract
from spa_core.investment_cio import exposure as _exposure

_PACKAGE_DIR = Path(__file__).resolve().parent


def code_identity(package_dir: Optional[Path] = None) -> str:
    """sha256 over the sorted source bytes of ``spa_core/investment_cio/*.py``.

    Identifies the CODE version, not the data — it depends on the package's own source tree, not on
    any argument to :func:`recommend`, so calling it twice in the same process (same code on disk)
    yields the same value and does not break the "same input -> byte-identical JSON" guarantee.
    """
    d = package_dir or _PACKAGE_DIR
    h = hashlib.sha256()
    for p in sorted(Path(d).glob("*.py")):
        h.update(p.name.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
    return h.hexdigest()

# ── local, judgement-call constants (documented above; not in the frozen contract) ──────────────────
#: static fallback mechanism caps, used only when a sleeve does not itself carry a ``risk.
#: mechanism_cap_pct`` cell. ADR-554 WP-A03 rule 2 names exactly this example.
MECHANISM_CAPS: Dict[str, float] = {
    "leveraged_loop": 0.10,
}
#: RiskPolicy v1.0 published per-protocol caps — a SINGLE copy, read from ``exposure.py`` (finding
#: #10: this module used to carry its own literal ``0.40``/``0.20`` alongside exposure's, and the
#: two could drift silently). Still never an import of ``spa_core.risk`` itself (the AST guard
#: forbids that from this package; ``.claude/rules/risk-engine.md``) — exposure's own copy is
#: itself a documented literal, not a live read. Tries exposure's named constants first (the shape
#: the concurrent work-package may land); falls back to its reference dict otherwise, so this does
#: not depend on which shape ``exposure.py`` ends up with. ``test_investment_cio_parity.py`` pins
#: both to RiskPolicy's own defaults so an ADR change to the real policy reddens this test instead
#: of drifting out of step.


def _protocol_caps_from_exposure() -> Tuple[float, float]:
    t1 = getattr(_exposure, "RISK_POLICY_CAP_T1", None)
    t2 = getattr(_exposure, "RISK_POLICY_CAP_T2", None)
    if t1 is None or t2 is None:
        ref = getattr(_exposure, "RISK_POLICY_CAPS_REFERENCE", {}) or {}
        t1 = t1 if t1 is not None else ref.get("T1")
        t2 = t2 if t2 is not None else ref.get("T2")
    return t1, t2


PROTOCOL_CAP_T1, PROTOCOL_CAP_T2 = _protocol_caps_from_exposure()

_RISK_LEVEL_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_of(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _utc(now: datetime) -> datetime:
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc)
    return now.replace(tzinfo=timezone.utc)


# ── sleeve-level reads (never a bare number; invariant #17) ─────────────────────────────────────────

def _cell(sleeve: dict, name: str) -> Any:
    return sleeve.get(name)


def _num(sleeve: dict, name: str) -> Optional[float]:
    return contract.value_of(_cell(sleeve, name))


def _is_allocatable(sleeve: dict) -> bool:
    return bool(sleeve.get("allocatable"))


def _maturity(sleeve: dict) -> Optional[str]:
    return contract.value_of(_cell(sleeve, "maturity"))


def _maturity_cap(maturity: str) -> Optional[float]:
    if maturity == contract.MATURITY_DEVELOPING:
        return contract.POLICY["cap_developing"]
    if maturity == contract.MATURITY_MATURE:
        return contract.POLICY["cap_mature"]
    return None  # IMMATURE never reaches here (excluded earlier)


def _mechanism_cap(sleeve: dict) -> Optional[float]:
    risk = sleeve.get("risk")
    if isinstance(risk, dict):
        v = risk.get("mechanism_cap_pct")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return MECHANISM_CAPS.get(sleeve.get("mechanism_class"))


def _gate_reason(gates: Any) -> Optional[str]:
    """First non-PASS gate reason, or None if every gate (or there are none) PASS."""
    if not isinstance(gates, list):
        return None
    for g in gates:
        if not isinstance(g, dict):
            continue
        state = g.get("state")
        if state != "PASS":
            return f"{g.get('gate', 'gate')}: {state} — {g.get('reason', 'no reason given')}"
    return None


def _return_gate(sleeve: dict, hurdle_cell: Any) -> Tuple[bool, str]:
    """(eligible_on_this_gate, rationale_line). Only binds on MATURE sleeves (rule 3)."""
    sid = sleeve.get("sleeve_id")
    if _maturity(sleeve) != contract.MATURITY_MATURE:
        return True, f"{sid}: return gate not applicable (not MATURE)"
    hurdle = contract.value_of(hurdle_cell) if hurdle_cell is not None else None
    if hurdle is None:
        return True, f"{sid}: return gate SKIPPED — hurdle unreadable (no sleeves_doc['hurdle'] cell)"
    realized = _num(sleeve, "realized_return")
    if realized is None:
        return False, f"{sid}: return gate FAIL — realized_return UNKNOWN, cannot compare to hurdle {hurdle}"
    if realized < hurdle:
        return False, f"{sid}: return gate FAIL — realized_return {realized} < hurdle {hurdle} (no cost amortisation applied; no switching-cost evidence exists yet)"
    return True, f"{sid}: return gate PASS — realized_return {realized} >= hurdle {hurdle}"


def _eligibility(sleeves: Dict[str, dict], hurdle_cell: Any) -> Tuple[Dict[str, dict], Dict[str, str], List[str]]:
    """Returns (eligible_risk_sleeves, abstentions, rationale_lines). 'cash' is never in either dict —
    it is handled separately by the cash-floor pass."""
    eligible: Dict[str, dict] = {}
    abstentions: Dict[str, str] = {}
    rationale: List[str] = []
    for sid in sorted(sleeves.keys()):
        if sid == "cash":
            continue
        sleeve = sleeves[sid]
        if not _is_allocatable(sleeve):
            abstentions[sid] = "observe-only: no mandate (allocatable=False)"
            rationale.append(f"rule 1: {sid} excluded — observe-only, no mandate")
            continue
        maturity = _maturity(sleeve)
        if maturity == contract.MATURITY_IMMATURE or maturity is None:
            vp = _num(sleeve, "valid_periods")
            start = sleeve.get("experiment_start")
            need = contract.POLICY["maturity_developing_min"]
            abstentions[sid] = (
                f"IMMATURE: re-versioned {start}, {int(vp) if vp is not None else '?'}/{need} valid periods"
                if maturity == contract.MATURITY_IMMATURE
                else "maturity UNKNOWN — not measured"
            )
            rationale.append(f"rule 2: {sid} excluded — {abstentions[sid]}")
            continue
        gate_reason = _gate_reason(sleeve.get("gates"))
        if gate_reason:
            abstentions[sid] = gate_reason
            rationale.append(f"rule 3: {sid} excluded — exclusion gate: {gate_reason}")
            continue
        s_loss = _num(sleeve, "worst_case_loss")
        if s_loss is None:
            abstentions[sid] = "worst_case_loss UNKNOWN — ineligible (fail-closed)"
            rationale.append(f"rule 4: {sid} excluded — worst_case_loss UNKNOWN")
            continue
        if s_loss <= 0:
            abstentions[sid] = f"worst_case_loss invalid ({s_loss}) — ineligible (fail-closed)"
            rationale.append(f"rule 4: {sid} excluded — worst_case_loss <= 0")
            continue
        ok, line = _return_gate(sleeve, hurdle_cell)
        rationale.append(f"rule 3: {line}")
        if not ok:
            abstentions[sid] = line
            continue
        eligible[sid] = sleeve
        rationale.append(f"rule 2: {sid} eligible, maturity={maturity}, worst_case_loss={s_loss}")
    return eligible, abstentions, rationale


# ── weight construction (rule 5) ──────────────────────────────────────────────────────────────────

def _raw_inverse_loss(eligible: Dict[str, dict]) -> Dict[str, float]:
    raws = {sid: 1.0 / _num(s, "worst_case_loss") for sid, s in eligible.items()}
    total = sum(raws.values())
    if total <= 0:
        return {sid: 0.0 for sid in eligible}
    return {sid: v / total for sid, v in raws.items()}


def _raw_equal(eligible: Dict[str, dict]) -> Dict[str, float]:
    n = len(eligible)
    if n == 0:
        return {}
    return {sid: 1.0 / n for sid in eligible}


def _caps_for(eligible: Dict[str, dict]) -> Dict[str, float]:
    caps = {}
    for sid, s in eligible.items():
        mcap = _maturity_cap(_maturity(s))
        xcap = _mechanism_cap(s)
        cap = mcap if mcap is not None else 1.0
        if xcap is not None:
            cap = min(cap, xcap)
        caps[sid] = cap
    return caps


def _apply_caps_independent(raw: Dict[str, float], caps: Dict[str, float]) -> Dict[str, float]:
    """Each sleeve's weight is capped on its own; no redistribution to peers — the excess becomes
    'remainder to cash' (ADR-554 WP-A03 rule 5), applied by the caller."""
    return {sid: min(w, caps.get(sid, 1.0)) for sid, w in raw.items()}


def _apply_cash_floor(risk_weights: Dict[str, float], eligible: Dict[str, dict],
                       cash_floor: float) -> Tuple[Dict[str, float], float, Optional[float], str]:
    """Returns (final_risk_weights, explicit_cash, look_through_cash_or_None, note)."""
    R = sum(risk_weights.values())
    explicit0 = 1.0 - R
    cash_shares: Dict[str, Optional[float]] = {sid: _num(eligible[sid], "cash_share") for sid in risk_weights
                                               if risk_weights[sid] > 0}
    any_unmeasured = any(v is None for v in cash_shares.values())
    if any_unmeasured:
        if explicit0 >= cash_floor:
            return risk_weights, explicit0, None, (
                "look-through cash UNDEFINED (a weighted sleeve's cash_share is NOT_MEASURED); "
                f"explicit cash alone ({explicit0:.4f}) already satisfies the {cash_floor:.0%} floor"
            )
        if R <= 0:
            return risk_weights, 1.0, None, "no risk weight to shrink; all cash"
        x = (1.0 - cash_floor) / R
        shrunk = {sid: w * x for sid, w in risk_weights.items()}
        return shrunk, cash_floor, None, (
            "look-through cash UNDEFINED; risk weights shrunk so the EXPLICIT cash sleeve alone "
            f"meets the {cash_floor:.0%} floor"
        )
    C = sum(risk_weights[sid] * cash_shares[sid] for sid in cash_shares)
    lt0 = explicit0 + C
    if lt0 >= cash_floor:
        return risk_weights, explicit0, lt0, f"look-through cash {lt0:.4f} already meets the {cash_floor:.0%} floor"
    denom = R - C
    if denom <= 0:
        if R <= 0:
            return risk_weights, 1.0, lt0, "no risk weight to shrink; all cash"
        x = (1.0 - cash_floor) / R
    else:
        x = (1.0 - cash_floor) / denom
    x = max(0.0, min(1.0, x))
    shrunk = {sid: w * x for sid, w in risk_weights.items()}
    return shrunk, 1.0 - sum(shrunk.values()), cash_floor, (
        f"look-through cash {lt0:.4f} was below the {cash_floor:.0%} floor; risk weights shrunk to meet it"
    )


def _round_pp(weights: Dict[str, float], increment_pp: float,
              ceilings: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Largest-remainder rounding to ``increment_pp`` percentage points, summing to exactly 1.0.
    Ties broken deterministically by ascending sleeve_id (ADR-554 WP-A03 rule 9). A sleeve with a
    ceiling (its cap) is never rounded ABOVE it — a step it cannot take goes to cash (final-check N1
    residual: a 16.5 % cap must not become 17 %)."""
    if not weights:
        return {}
    steps_total = round(1.0 / (increment_pp / 100.0))
    ceilings = ceilings or {}
    cap_steps = {sid: int(c * steps_total + 1e-9) for sid, c in ceilings.items() if c is not None}
    scaled = {sid: w * steps_total for sid, w in weights.items()}
    floors = {sid: min(int(v + 1e-9), cap_steps.get(sid, int(v + 1e-9))) for sid, v in scaled.items()}
    remainders = {sid: v - floors[sid] for sid, v in scaled.items()}
    deficit = steps_total - sum(floors.values())
    order = sorted(weights.keys(), key=lambda sid: (-remainders[sid], sid))
    final_steps = dict(floors)
    for sid in order:
        if deficit <= 0:
            break
        if sid in cap_steps and final_steps[sid] + 1 > cap_steps[sid]:
            continue
        final_steps[sid] += 1
        deficit -= 1
    if deficit > 0 and "cash" in final_steps:
        final_steps["cash"] += deficit
    return {sid: final_steps[sid] * (increment_pp / 100.0) for sid in weights}


def _build_portfolio(eligible: Dict[str, dict], raw_fn, cash_floor: float) -> Tuple[Dict[str, float], dict]:
    """Full rule-5 pipeline for a given eligible set + weighting function. Returns
    (rounded_weights_incl_cash, detail)."""
    if not eligible:
        return {"cash": 1.0}, {"risk_raw": {}, "risk_capped": {}, "explicit_cash": 1.0,
                               "look_through_cash": None, "note": "no eligible risk sleeves"}
    raw = raw_fn(eligible)
    caps = _caps_for(eligible)
    capped = _apply_caps_independent(raw, caps)
    final_risk, explicit_cash, lt_cash, note = _apply_cash_floor(capped, eligible, cash_floor)
    combined = dict(final_risk)
    combined["cash"] = explicit_cash
    rounded = _round_pp(combined, contract.POLICY["weight_rounding_pp"], ceilings=caps)
    detail = {"risk_raw": raw, "risk_capped": capped, "caps": caps, "explicit_cash": explicit_cash,
              "look_through_cash": lt_cash, "note": note}
    return rounded, detail


# ── derived summaries ────────────────────────────────────────────────────────────────────────────

def _weighted_avg_cell(sleeves: Dict[str, dict], weights: Dict[str, float], field: str, *, note: str) -> dict:
    contributors = [(sid, w) for sid, w in weights.items() if w > 0 and sid != "cash"]
    if not contributors:
        return contract.absent(contract.NOT_MEASURED, reason=f"no non-cash weight to average {field} over")
    values = {}
    ns = []
    for sid, _ in contributors:
        v = _num(sleeves.get(sid, {}), field)
        if v is None:
            return contract.absent(contract.NOT_MEASURED,
                                   reason=f"{sid} has no measured {field}; portfolio-level {field} withheld")
        values[sid] = v
        n = sleeves[sid].get(field, {}).get("n") if isinstance(sleeves[sid].get(field), dict) else None
        if isinstance(n, (int, float)):
            ns.append(n)
    total_w = sum(w for _, w in contributors)
    avg = sum(values[sid] * w for sid, w in contributors) / total_w if total_w > 0 else 0.0
    return contract.measured(round(avg, 6), unit="pct_annualized", source="investment_cio.policy",
                             as_of=None, n=min(ns) if ns else None, note=note)


def _max_level_detail(sleeve_axis_levels: List[str]) -> dict:
    """Finding #13: UNKNOWN must DOMINATE a combination, not rank below LOW — a portfolio with one
    UNKNOWN contributor and the rest LOW is not safely LOW (invariant #17: absence of knowledge is
    its own value, never silently rounded down to the friendliest known level). Returns the
    dominant ``level`` (``UNKNOWN`` whenever any contributor is UNKNOWN or there are no
    contributors at all) alongside ``any_unknown`` and the ``max_known`` level among the rest, so
    a reader can still see "the known part tops out at LOW" even while the honest combined level
    is UNKNOWN."""
    if not sleeve_axis_levels:
        return {"level": "UNKNOWN", "any_unknown": True, "max_known": None}
    any_unknown = "UNKNOWN" in sleeve_axis_levels
    known = [lv for lv in sleeve_axis_levels if lv in _RISK_LEVEL_RANK]
    max_known = max(known, key=lambda lv: _RISK_LEVEL_RANK[lv]) if known else None
    level = "UNKNOWN" if any_unknown else (max_known or "UNKNOWN")
    return {"level": level, "any_unknown": any_unknown, "max_known": max_known}


def _max_level(sleeve_axis_levels: List[str]) -> str:
    return _max_level_detail(sleeve_axis_levels)["level"]


def _portfolio_risk_summary(sleeves: Dict[str, dict], weights: Dict[str, float]) -> dict:
    out = {}
    contributors = [sid for sid, w in weights.items() if w > 0 and sid != "cash"]
    for axis in contract.RISK_AXES:
        levels = []
        for sid in contributors:
            risk = sleeves.get(sid, {}).get("risk")
            level = None
            if isinstance(risk, dict) and axis in risk:
                entry = risk[axis]
                level = entry.get("level") if isinstance(entry, dict) else entry
            if level not in contract.RISK_LEVELS:
                # finding N7: a weighted contributor that does not report this axis at all is
                # UNKNOWN on it, never silently dropped from the combination — dropping it let a
                # peer's reported LOW stand in for a HIGH-risk sleeve's unassessed COUNTERPARTY.
                level = "UNKNOWN"
            levels.append(level)
        detail = _max_level_detail(levels)
        out[axis] = {"level": detail["level"], "any_unknown": detail["any_unknown"],
                    "max_known": detail["max_known"], "contributors": list(contributors)}
    return out


def _major_risks(sleeves: Dict[str, dict], weights: Dict[str, float]) -> dict:
    """Per-factor concentration of a shared failure mode: which sleeves share it and the weight
    exposed to it. Finding #13: the combined ``level`` is computed ONCE over the full list of
    reported levels for the factor (never folded incrementally against an "UNKNOWN" starting
    sentinel, which would poison every bucket to UNKNOWN forever the moment any contributor used
    the sentinel). Finding #14: the per-sleeve contribution is named ``sleeve_weight_touching`` —
    it is the sleeve weight that touches the factor, not a portfolio-level weighted risk score."""
    buckets: Dict[str, dict] = {}
    for sid, w in weights.items():
        if w <= 0 or sid == "cash":
            continue
        factors = sleeves.get(sid, {}).get("factors")
        # sleeves publish factor ids (a list); a level per factor is not measured, so the fact reported is the
        # concentration of the common failure mode: which sleeves share it and the weight exposed to it
        if isinstance(factors, list):
            factors = {f: "UNKNOWN" for f in factors if isinstance(f, str)}
        if not isinstance(factors, dict):
            continue
        for factor, entry in factors.items():
            level = entry.get("level") if isinstance(entry, dict) else entry
            if level not in contract.RISK_LEVELS:
                continue
            bucket = buckets.setdefault(factor, {"levels": [], "contributors": [], "weight_sum": 0.0})
            bucket["contributors"].append(sid)
            bucket["weight_sum"] = round(bucket["weight_sum"] + w, 6)
            bucket["levels"].append(level)
    out: Dict[str, dict] = {}
    for factor, bucket in buckets.items():
        detail = _max_level_detail(bucket["levels"])
        out[factor] = {"level": detail["level"], "any_unknown": detail["any_unknown"],
                       "max_known": detail["max_known"], "contributors": bucket["contributors"],
                       "sleeve_weight_touching": bucket["weight_sum"]}
    return out


def _diversification_summary(sleeves_doc: dict, weights: Dict[str, float]) -> dict:
    # the weighted look-through overlap needs THESE weights — the sleeves document can only carry the
    # unweighted facts (it is built before any weight exists)
    sleeves_map = sleeves_doc.get("sleeves") or {}
    exposure = _exposure.build(sleeves_map, weights=weights) if weights else (sleeves_doc.get("exposure") or {})
    correlation = sleeves_doc.get("correlation") or {}
    overlap = exposure.get("protocol_overlap") if isinstance(exposure, dict) else None
    # finding #8: the old version silently DROPPED any protocol whose weighted_share could not be
    # computed and then reported the cap check as fully "MEASURED" — a holder with no measured
    # share made the check look complete when it was only partial. Every protocol in the overlap
    # is now carried (absent weight counted as 0 — it can only UNDERSTATE a breach, never hide
    # one) and the ones that could not actually be checked are named, driving the state to
    # PARTIAL. If the concurrent exposure.py work-package lands its own ``unchecked_protocols`` /
    # ``protocol_cap_state`` fields, those are honoured as the authoritative answer; otherwise
    # this derives the same fact from ``protocol_overlap`` itself.
    explicit_unchecked = exposure.get("unchecked_protocols") if isinstance(exposure, dict) else None
    explicit_state = exposure.get("protocol_cap_state") if isinstance(exposure, dict) else None
    if overlap is None:
        protocol_cap_check = {"state": "NOT_MEASURED",
                              "reason": "exposure document carries no protocol_overlap breakdown yet"}
    else:
        per_protocol: Dict[str, dict] = {}
        derived_unchecked: List[dict] = []
        for row in overlap:
            protocol = row.get("protocol")
            tier = row.get("tier")
            ws = row.get("weighted_share")
            if isinstance(ws, dict) and ws.get("state") == "MEASURED":
                per_protocol[protocol] = {"share": ws.get("value") or 0.0, "tier": tier}
            else:
                per_protocol[protocol] = {"share": 0.0, "tier": tier}  # absent weight = 0 (never a hidden breach)
                reason = ws.get("reason") if isinstance(ws, dict) else "weighted_share not measured"
                derived_unchecked.append({"protocol": protocol, "reason": reason})
        unchecked_protocols = explicit_unchecked if explicit_unchecked is not None else derived_unchecked
        breaches = []
        for protocol, info in per_protocol.items():
            share = info.get("share")
            tier = info.get("tier")
            cap = PROTOCOL_CAP_T1 if tier == "T1" else PROTOCOL_CAP_T2 if tier == "T2" else None
            if isinstance(share, (int, float)) and cap is not None and share > cap:
                breaches.append({"protocol": protocol, "tier": tier, "share": share, "cap": cap})
        state = explicit_state if explicit_state in ("MEASURED", "PARTIAL") else (
            "PARTIAL" if unchecked_protocols else "MEASURED")
        protocol_cap_check = {"state": state, "breaches": breaches}
        if unchecked_protocols:
            protocol_cap_check["unchecked_protocols"] = unchecked_protocols
    return {"exposure": exposure, "correlation": correlation, "protocol_cap_check": protocol_cap_check}


def _liquidity_summary(sleeves: Dict[str, dict], weights: Dict[str, float]) -> dict:
    by_sleeve = {}
    for sid, w in weights.items():
        if w <= 0 or sid == "cash":
            continue
        s = sleeves.get(sid, {})
        by_sleeve[sid] = {"liquidity": _num(s, "liquidity"), "time_to_exit": _num(s, "time_to_exit"),
                          "weight": w}
    return {"by_sleeve": by_sleeve}


def _explanation_facts(sleeves: Dict[str, dict], previous: Optional[dict], seed_split: dict,
                       recommended: Dict[str, float], stance: str, binding: List[dict]) -> List[dict]:
    def fact(name: str, state: str, text: str) -> dict:
        return {"fact": name, "state": state, "text": text}

    prev_weights = (previous or {}).get("recommended_weights") or seed_split or {}
    cur_yield = _weighted_avg_cell(sleeves, prev_weights, "realized_return", note="current portfolio, realised")
    tgt_yield = _weighted_avg_cell(sleeves, recommended, "expected_return", note="target portfolio, expected")
    proj_yield = _weighted_avg_cell(sleeves, recommended, "realized_return",
                                    note="realised, not a forecast")
    facts = [
        fact("current_yield_of_source",
            "SPOKEN" if contract.value_of(cur_yield) is not None else "UNKNOWN",
            f"current (previous/seed) weighted realised yield: {cur_yield}"),
        fact("expected_yield_of_target",
            "SPOKEN" if contract.value_of(tgt_yield) is not None else "UNKNOWN",
            f"candidate weighted expected yield: {tgt_yield}"),
        fact("projected_yield_after_move",
            "SPOKEN" if contract.value_of(proj_yield) is not None else "UNKNOWN",
            f"candidate weighted realised yield (label: realised, not a forecast): {proj_yield}"),
        fact("switching_cost", "UNKNOWN",
            "NOT_MEASURED — no rebalance-cost evidence file exists yet (WP-S04)"),
        fact("break_even", "UNKNOWN", "depends on switching_cost, which is UNKNOWN"),
        fact("persistence",
            "SPOKEN",
            f"stance={stance}; hysteresis threshold {contract.POLICY['hysteresis_pp']}pp vs previous recommendation"),
        fact("risk_inside_limits",
            "SPOKEN" if binding is not None else "UNKNOWN",
            f"binding_constraints: {binding}"),
        fact("recommendation",
            "SPOKEN",
            f"stance={stance}, recommended_weights={recommended}"),
    ]
    return facts


def _alternatives(sleeves: Dict[str, dict], eligible: Dict[str, dict], seed_split: dict,
                  cash_floor: float) -> dict:
    equal_weight, _ = _build_portfolio(eligible, _raw_equal, cash_floor)
    mature_only = {sid: s for sid, s in eligible.items() if _maturity(s) == contract.MATURITY_MATURE}
    evidence_only, _ = _build_portfolio(mature_only, _raw_inverse_loss, cash_floor)
    return {
        "SEED_SPLIT": {"weights": dict(seed_split), "note": "the experiments' own equal seeding — nobody's decision"},
        "EQUAL_WEIGHT": {"weights": equal_weight, "note": "equal-weight of eligible risk sleeves"},
        "EVIDENCE_ONLY": {"weights": evidence_only,
                          "note": "evidence-only portfolio (not a recommendation) — MATURE eligible sleeves only"},
        "ALL_CASH": {"weights": {"cash": 1.0}, "note": "100% cash"},
    }


def _portfolio_check(sleeves: Dict[str, dict], weights: Dict[str, float]) -> List[dict]:
    """rule 6: report-only Sigma w*S vs Sigma w*loss_budget."""
    out = []
    s_sum = 0.0
    b_sum = 0.0
    unknown = []
    if not any(w > 0 and sid != "cash" for sid, w in weights.items()):
        out.append({"constraint": "portfolio_loss_budget", "state": "NOT_APPLICABLE",
                    "reason": "no recommended risk weights — nothing to check"})
        return out
    for sid, w in weights.items():
        if w <= 0 or sid == "cash":
            continue
        s = _num(sleeves.get(sid, {}), "worst_case_loss")
        b = _num(sleeves.get(sid, {}), "loss_budget")
        if s is None or b is None:
            unknown.append(sid)
            continue
        s_sum += w * s
        b_sum += w * b
    if unknown:
        out.append({"constraint": "portfolio_loss_budget", "state": "UNKNOWN",
                    "reason": f"loss_budget or worst_case_loss not measured for: {unknown}"})
    else:
        breach = s_sum > b_sum
        out.append({"constraint": "portfolio_loss_budget", "state": "BREACH" if breach else "OK",
                    "detail": f"sum(w*worst_case_loss)={round(s_sum, 6)} vs sum(w*loss_budget)={round(b_sum, 6)}"})
    return out


def _binding_caps(eligible: Dict[str, dict], caps: Dict[str, float], raw: Dict[str, float]) -> List[dict]:
    out = []
    for sid, cap in caps.items():
        if raw.get(sid, 0.0) > cap + 1e-12:
            out.append({"constraint": f"{sid}_cap", "state": "BINDING",
                       "detail": f"raw weight {raw[sid]:.4f} capped to {cap:.4f}"})
    return out


# ── main entry ───────────────────────────────────────────────────────────────────────────────────

def recommend(sleeves_doc: dict, previous: Optional[dict], now: datetime) -> dict:
    """ADR-554 WP-A03 rules 1-10. Pure: same (sleeves_doc, previous, now) -> byte-identical JSON."""
    now_utc = _utc(now)
    generated_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    date = now_utc.strftime("%Y-%m-%d")

    sleeves: Dict[str, dict] = sleeves_doc.get("sleeves") or {}
    seed_split = dict(sleeves_doc.get("seed_split_weights") or {})
    hurdle_cell = sleeves_doc.get("hurdle")
    cash_floor = contract.POLICY["cash_floor"]

    eligible, abstentions, rationale = _eligibility(sleeves, hurdle_cell)
    n_eligible = len(eligible)
    n_mature = sum(1 for s in eligible.values() if _maturity(s) == contract.MATURITY_MATURE)

    unknowns: List[str] = []
    if hurdle_cell is None or contract.value_of(hurdle_cell) is None:
        unknowns.append("hurdle unreadable — return gate SKIPPED wherever it would have applied")

    if n_eligible == 0:
        stance = contract.STANCE_NONE
        recommended_weights: Dict[str, float] = {}
        rationale.append("rule 7: stance=NO_RECOMMENDATION — 0 eligible risk sleeves")
        raw_for_check, caps_for_check = {}, {}
    elif n_eligible == 1:
        stance = contract.STANCE_INSUFFICIENT
        recommended_weights = {}
        rationale.append("rule 7: stance=INSUFFICIENT_EVIDENCE — exactly 1 eligible risk sleeve "
                         "(F2: one mature sleeve is not an allocation)")
        raw_for_check = _raw_inverse_loss(eligible)
        caps_for_check = _caps_for(eligible)
    else:
        candidate_weights, detail = _build_portfolio(eligible, _raw_inverse_loss, cash_floor)
        raw_for_check, caps_for_check = detail["risk_raw"], detail["caps"]
        prev_weights = (previous or {}).get("recommended_weights") or {}
        # finding #4: HOLD must never copy a previous weight for a sleeve that is now ineligible —
        # the raw |delta| check alone can stay small even when the eligible SET changed (a dropped
        # sleeve's slack can land almost entirely on a newly-eligible sleeve of similar size).
        # HOLD is only safe when (a) the eligible set is unchanged vs the previous recommendation
        # AND (b) no sleeve the previous recommendation actually weighted is now an abstention.
        prev_abstentions = set((previous or {}).get("abstentions") or {})
        universe_non_cash = set(sleeves.keys()) - {"cash"}
        prev_eligible_sids = universe_non_cash - prev_abstentions
        eligible_set_unchanged = bool(previous) and prev_eligible_sids == set(eligible.keys())
        prev_weighted_sids = {sid for sid, w in prev_weights.items() if w > 0 and sid != "cash"}
        now_ineligible_weighted = prev_weighted_sids & set(abstentions.keys())
        all_sids = set(candidate_weights) | set(prev_weights)
        max_delta = max((abs(candidate_weights.get(sid, 0.0) - prev_weights.get(sid, 0.0))
                        for sid in all_sids), default=0.0)
        # finding N1: HOLD must also never freeze a previous weight that now BREACHES a tightened
        # cap (e.g. a mechanism cap lowered by its own ADR from 0.20 to 0.16) — a small |delta|
        # alone says nothing about whether the frozen number still respects today's caps. Checked
        # against caps_for_check, which is computed from the CURRENT sleeves/eligibility, not the
        # previous ones. The explicit cash weight held over by a HOLD must also still clear
        # today's cash floor.
        caps_exceeded = {sid for sid in prev_weighted_sids
                        if prev_weights.get(sid, 0.0) > caps_for_check.get(sid, 1.0) + 1e-9}
        prev_cash = prev_weights.get("cash", 0.0)
        cash_floor_breached = bool(prev_weights) and prev_cash < cash_floor - 1e-9
        can_hold = bool(prev_weights) and eligible_set_unchanged and not now_ineligible_weighted and \
            not caps_exceeded and not cash_floor_breached and \
            max_delta < (contract.POLICY["hysteresis_pp"] / 100.0)
        if can_hold:
            stance = contract.STANCE_HOLD
            recommended_weights = dict(prev_weights)
            rationale.append(f"rule 7: stance=HOLD — max |delta| vs previous {max_delta:.4f} < "
                             f"{contract.POLICY['hysteresis_pp']}pp, eligible set unchanged")
        else:
            stance = contract.STANCE_RECOMMEND
            recommended_weights = candidate_weights
            reasons = []
            if prev_weights and not eligible_set_unchanged:
                reasons.append("eligible set changed vs the previous recommendation")
            if now_ineligible_weighted:
                reasons.append(f"previously-weighted sleeve(s) now ineligible: {sorted(now_ineligible_weighted)}")
            if caps_exceeded:
                reasons.append(f"previous weight now exceeds its current cap: {sorted(caps_exceeded)}")
            if cash_floor_breached:
                reasons.append(f"previous explicit cash {prev_cash:.4f} is below the current "
                               f"{cash_floor:.0%} floor")
            if not reasons:
                reasons.append(f"{n_eligible} eligible risk sleeves, weights ∝ 1/worst_case_loss, capped")
            rationale.append("rule 7: stance=RECOMMEND — " + "; ".join(reasons))

    confidence = "MEDIUM" if n_mature >= 2 else "LOW"
    confidence_reasons = [
        f"{n_mature} eligible MATURE sleeve(s) — MEDIUM needs >= 2" if confidence == "MEDIUM"
        else f"only {n_mature} eligible MATURE sleeve(s) — MEDIUM needs >= 2, staying LOW",
        "HIGH is unreachable in v1 (no mark-to-market coverage, no measured price-risk correlation) — WP-A03 rule 8",
    ]

    binding_constraints = _portfolio_check(sleeves, recommended_weights) + \
        _binding_caps(eligible, caps_for_check, raw_for_check)

    # finding #14: major_risks was silently computed on the SEED_SPLIT whenever there was no
    # recommendation (stance HOLD/INSUFFICIENT_EVIDENCE/NO_RECOMMENDATION weren't distinguishable
    # from "the recommended portfolio has this risk") — the basis is now a named field, and the
    # per-factor weight is "sleeve_weight_touching" (see _major_risks), not a portfolio score.
    major_risks_basis = "recommended" if recommended_weights else "seed_split"
    major_risks = {"basis": major_risks_basis,
                   "factors": _major_risks(sleeves, recommended_weights if recommended_weights else seed_split)}
    portfolio_risk_summary = _portfolio_risk_summary(sleeves, recommended_weights if recommended_weights else seed_split)
    liquidity_summary = _liquidity_summary(sleeves, recommended_weights)
    diversification_summary = _diversification_summary(sleeves_doc, recommended_weights)
    regime = sleeves_doc.get("regime", contract.absent(contract.NOT_MEASURED,
                                                       reason="sleeves_doc carries no regime cell"))

    # finding #19: portfolio_expected_return keeps its contract field name, but its value must be
    # unmistakably a trailing REALISED figure, never read as a forecast of what is to come.
    portfolio_expected_return = dict(_weighted_avg_cell(sleeves, recommended_weights, "realized_return",
                                                        note="realised, not a forecast"))
    portfolio_expected_return["kind"] = "realised_trailing"
    worst_case_to_stops = 0.0
    any_unknown_s = False
    for sid, w in recommended_weights.items():
        if w <= 0 or sid == "cash":
            continue
        s = _num(sleeves.get(sid, {}), "worst_case_loss")
        if s is None:
            any_unknown_s = True
            continue
        worst_case_to_stops += w * s
    realised_dd = _weighted_avg_cell(sleeves, recommended_weights, "max_drawdown", note="realised max drawdown")
    portfolio_drawdown_estimate = {
        "worst_case_to_stops": (contract.absent(contract.NOT_MEASURED,
                                                reason="a weighted sleeve has no measured worst_case_loss")
                               if any_unknown_s else
                               contract.measured(round(worst_case_to_stops, 6), unit="pct",
                                                 source="investment_cio.policy", as_of=None,
                                                 note="sum(w*worst_case_loss), worst-case-to-stops")),
        "realised_max_drawdown": realised_dd,
    }

    abstentions_out = dict(abstentions)

    explanation_facts = _explanation_facts(sleeves, previous, seed_split, recommended_weights, stance,
                                           binding_constraints)
    alternatives_considered = _alternatives(sleeves, eligible, seed_split, cash_floor)

    inputs = sleeves_doc.get("inputs") or []
    as_ofs = [i.get("as_of") for i in inputs if isinstance(i, dict) and i.get("as_of")]
    evidence_cutoff = min(as_ofs) if as_ofs else None
    input_ages = {i.get("name"): i.get("age_hours") for i in inputs if isinstance(i, dict)}
    evidence_refs = [{"name": i.get("name"), "path": i.get("path"), "digest": i.get("digest")}
                     for i in inputs if isinstance(i, dict)]
    # finding #19: evidence_cutoff is a timestamp, not a completeness claim — a STALE/NOT_MEASURED
    # input still contributes its (old or absent) as_of to the min(), so the cutoff alone cannot
    # tell a reader "every input the policy used was itself fresh and measured". Named separately.
    incomplete_inputs = [i.get("name") for i in inputs
                         if isinstance(i, dict) and i.get("state") in (contract.NOT_MEASURED, contract.STALE)]
    evidence_cutoff_complete = not incomplete_inputs
    if incomplete_inputs:
        unknowns.append(f"evidence_cutoff incomplete — input(s) not fully measured/fresh: {incomplete_inputs}")

    prev_weights_for_change = (previous or {}).get("recommended_weights") or {}
    all_sids_prev = set(recommended_weights) | set(prev_weights_for_change)
    change_vs_previous = {sid: round(recommended_weights.get(sid, 0.0) - prev_weights_for_change.get(sid, 0.0), 6)
                          for sid in sorted(all_sids_prev)}
    all_sids_seed = set(recommended_weights) | set(seed_split)
    change_vs_seed_split = {sid: round(recommended_weights.get(sid, 0.0) - seed_split.get(sid, 0.0), 6)
                            for sid in sorted(all_sids_seed)}

    if any(contract.value_of(sleeves.get(sid, {}).get("cash_share")) is None
          for sid, w in recommended_weights.items() if w > 0 and sid != "cash"):
        unknowns.append("look-through cash is UNDEFINED for at least one weighted sleeve "
                        "(a weighted sleeve's cash_share is NOT_MEASURED)")
    if contract.value_of(portfolio_expected_return) is None:
        unknowns.append("portfolio_expected_return NOT_MEASURED — not every weighted sleeve has a "
                        "measured realized_return")

    # finding N6: real_capital_usd is owner subject #1 (money-path boundary) — a bare passthrough
    # of whatever sleeves_doc carries let a non-zero figure (e.g. a stray $5,000) ride straight
    # into the ledger as though it were real. Only 0 or None are ever accepted; anything else is
    # refused to None and named, never silently clamped without a trace.
    raw_real_capital_usd = sleeves_doc.get("real_capital_usd", None)
    real_capital_is_bool = isinstance(raw_real_capital_usd, bool)
    real_capital_ok = raw_real_capital_usd is None or (
        not real_capital_is_bool and isinstance(raw_real_capital_usd, (int, float)) and raw_real_capital_usd == 0)
    if real_capital_ok:
        real_capital_usd = raw_real_capital_usd
    else:
        unknowns.append(f"real capital value outside the paper boundary refused: {raw_real_capital_usd!r} "
                        "is not 0 or None")
        real_capital_usd = None

    rec: Dict[str, Any] = {
        "schema": contract.SCHEMA_REC,
        "recommendation_id": None,  # filled below
        "generated_at": generated_at,
        "date": date,
        "evidence_cutoff": evidence_cutoff,
        "evidence_cutoff_complete": evidence_cutoff_complete,
        "evidence_cutoff_incomplete_inputs": incomplete_inputs,
        "input_ages": input_ages,
        "mode": contract.MODE,
        "role_id": contract.ROLE_ID,
        "stance": stance,
        "recommended_weights": recommended_weights,
        "seed_split_weights": seed_split,
        "previous_recommendation_id": (previous or {}).get("recommendation_id"),
        "change_vs_previous": change_vs_previous,
        "change_vs_seed_split": change_vs_seed_split,
        "portfolio_expected_return": portfolio_expected_return,
        "portfolio_risk_summary": portfolio_risk_summary,
        "portfolio_drawdown_estimate": portfolio_drawdown_estimate,
        "liquidity_summary": liquidity_summary,
        "diversification_summary": diversification_summary,
        "regime": regime,
        "confidence": confidence,
        "confidence_reasons": confidence_reasons,
        "binding_constraints": binding_constraints,
        "major_risks": major_risks,
        "unknowns": unknowns,
        "abstentions": abstentions_out,
        "rationale": rationale,
        "explanation_facts": explanation_facts,
        "alternatives_considered": alternatives_considered,
        "evidence_refs": evidence_refs,
        "policy_version": contract.POLICY_VERSION,
        "policy": contract.POLICY,
        "code_identity": code_identity(),
        "lineage": {"policy_version": contract.POLICY_VERSION,
                   "previous_recommendation_id": (previous or {}).get("recommendation_id"),
                   "snapshot_digest": None},  # filled by ledger.append
        "executes": False,
        "real_capital_usd": real_capital_usd,
    }
    # ADR-641: the multi-source view (capital sources, Trading Alpha eligibility, paper portfolio, frontier) —
    # present only when the sleeves document carries the snapshotted capital-sources inputs. Additive field;
    # it is inside the recommendation hash, it never changes `recommended_weights`, it never executes.
    cs_inputs = sleeves_doc.get("capital_sources")
    if isinstance(cs_inputs, dict):
        if cs_inputs.get("state") == "REFUSED":
            rec["capital_sources_view"] = {"state": "REFUSED", "reason": cs_inputs.get("reason"),
                                           "executes": False, "real_capital_usd": 0}
        else:
            try:
                from spa_core.investment_cio import sources_portfolio
                # as_of = the recommendation DATE, not the clock: the view enters the recommendation hash and the
                # same evidence must give the same recommendation_id whatever hour the run happened (review P1-2)
                rec["capital_sources_view"] = sources_portfolio.view(cs_inputs, recommended_weights, stance,
                                                                     alternatives_considered, as_of=date)
            except Exception as exc:  # noqa: BLE001 — named in the record, never a failed recommendation
                rec["capital_sources_view"] = {"state": "REFUSED", "reason": f"{type(exc).__name__}: {exc}",
                                               "executes": False, "real_capital_usd": 0}
    missing = [f for f in contract.REC_FIELDS if f not in rec]
    assert not missing, f"recommend() missing contract.REC_FIELDS: {missing}"

    hash_basis = {k: v for k, v in rec.items() if k not in ("recommendation_id", "generated_at", "lineage")}
    rec["recommendation_id"] = _sha256_of(hash_basis)
    return rec
