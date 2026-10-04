"""spa_core/research_factory/paper.py — ADR-564 (RM-EVIDENCE-01) Package E2: the paper ledger +
paper accounting (binding #9, with #5/#6/#7/#10 touching this file too).

Every call opens/marks/moves/closes a SIMULATED position of exactly ``evidence_contract.
PAPER_NOTIONAL_USD`` — never real capital, never a live order, never a signature. All rows land
on the SAME factory hash-chained ledger as Package A/E1 (``_common.ledger_for``), under one of
``evidence_contract.PAPER_KINDS`` = ``paper_open`` / ``paper_mark`` / ``paper_cashflow`` /
``paper_unit_change`` / ``paper_close``, each keyed for idempotency exactly as
``spa_core.research_factory.forward`` already keys its own rows.

Design convention this package OWNS (not frozen by the ADR beyond the top-level field names in
``evidence_contract.PAPER_FIELDS`` / ``EVIDENCE_SECTIONS``) — E1/E3 authors producing a bundle
for :func:`open_position` must shape it this way:

    bundle["paper_accounting_evidence"] = {
        "entry_price": contract.cell(...),                 # required, VALUED_STATES only
        "entry_fee_components": [fee_component, ...],       # required, non-empty
        "exit_fee_components": [fee_component, ...],        # required non-empty iff HOLDABLE
        "redemption_delay_days": contract.cell(...),        # required iff HOLDABLE
        "price_is_net_of_performance_fee": contract.cell(NOT_APPLICABLE, reason=...) | None,
        "performance_fee_rate": contract.cell(...) | None,
        "leverage": contract.cell(...) | None, "maintenance_margin_rate": contract.cell(...) | None,
        "collateral_yield_rate": contract.cell(...) | None,
        "fee_source": str | None, "holding_period_days_declared": float | None,
        "return_origin_group": str | None,                  # the RETURN claim's affiliation group,
                                                              # for mark_circular at mark() time
        # two-leg (funding-pair) candidates replace the block above with:
        "legs": {"perp": {<same shape>}, "spot": {<same shape>}},
    }
    fee_component = {"kind": "entry"|"exit"|"management"|"performance"|"spread", "cell": contract.cell(...),
                     "unit": "usd"|"bps"|"bps_one_off"|"fraction"|"fraction_one_off"|"fraction_apy"|"fraction_of_yield", "effective_from": "...", "subject_to_change": bool,
                     "one_off": bool}

A fee/cost cell MUST be a VALUED state (MEASURED/DOCUMENTED/ESTIMATED_WITH_METHOD) or explicitly
``NOT_APPLICABLE`` with a reason — never simply absent. "No missing-as-zero": an empty or missing
fee-component list, or any component graded NOT_MEASURED/STALE/CONFLICTED, refuses the open (and,
symmetrically, refuses close() for the fields obs supplies there) — :class:`PaperRefusal`, never a
silent 0.

Every row is a FULL SNAPSHOT of the position's running state (units, cash, NAV, mark provenance,
…), not a delta — ``nav()``/``positions()`` therefore only ever need the LATEST row per
position_id. A field a given event does not touch is carried forward unchanged from the previous
row. ``position_id`` is a deterministic digest of (candidate_id, decision_id, admission_id,
leg_id), so a retried daily run with the SAME admission never opens a second position.

Forward-period COUNTING (maturity toward CIO eligibility) is owned entirely by
``spa_core.research_factory.forward`` / ``contract.period_countable`` — this module never
re-implements or competes with that rule; a daily run calls both ``forward.record()`` (candidate
maturity) and this module's :func:`mark`/:func:`cashflow` (paper NAV) off the same observation.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import grades as grades_mod
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import DuplicateKey

#: mark() default freshness family when ``obs`` names none — NAV marks may stay flat over
#: weekends/holidays (``grades.freshness_verdict`` / ``evidence_contract.FRESHNESS``).
DEFAULT_MARK_FAMILY = "nav_business_day"


class PaperRefusal(Exception):
    """A deliberate fail-CLOSED refusal to open/mark/move/close a paper position — never an
    accident, always named. Mirrors ``lifecycle.InvalidTransition``'s role for the lifecycle."""


# ── small, strict readers — no ``(x or {}).get()``, no missing-as-zero ─────────────────────────

def _valued_or_refuse(cell: Any, what: str) -> float:
    """The finite numeric value of a VALUED cell (MEASURED/DOCUMENTED/ESTIMATED_WITH_METHOD) —
    or :class:`PaperRefusal`. NOT_APPLICABLE is deliberately NOT accepted here: a price/an exit
    price/a declared delay is never "not applicable", only known or unknown."""
    state = cell.get("state") if isinstance(cell, dict) else None
    if state not in c1.VALUED_STATES:
        raise PaperRefusal(f"{what} is {state!r}, not a valued cell — never treated as 0")
    value = cell.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PaperRefusal(f"{what} cell carries no finite value")
    return float(value)


def _fee_component_usd(comp: Any, notional_usd: float, what: str) -> float:
    """One fee component's USD amount against ``notional_usd`` — or :class:`PaperRefusal`.
    NOT_APPLICABLE is accepted HERE (a component can legitimately not exist for a mechanism,
    e.g. "no performance fee on this product") and contributes 0.0 — that is a MEASURED zero by
    mechanism, not a missing one."""
    if not isinstance(comp, dict):
        raise PaperRefusal(f"{what}: fee component malformed (not a dict)")
    cell = comp.get("cell")
    state = cell.get("state") if isinstance(cell, dict) else None
    if state == c1.NOT_APPLICABLE:
        return 0.0
    if state not in c1.VALUED_STATES:
        raise PaperRefusal(f"{what}: component {comp.get('kind')!r} is {state!r} — "
                           f"NOT_MEASURED never counts as 0")
    value = cell.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PaperRefusal(f"{what}: component {comp.get('kind')!r} carries no finite value")
    unit = comp.get("unit")
    if unit is None:
        unit = "usd"
    if unit == "usd":
        return float(value)
    if unit in ("bps", "bps_one_off"):
        return float(value) / 10_000.0 * notional_usd
    if unit in ("fraction", "fraction_one_off"):
        return float(value) * notional_usd
    # integration finding: E3's honest fee units. An ANNUAL fee is never a one-off charge: it is either embedded
    # in the NAV price the position is marked at (fund-level fees reduce NAV) or zero; anything else needs an
    # accrual this module does not model ⇒ refused, never silently netted. A performance fee is handled by the
    # performance-fee accrual (performance_fee_rate), never as an entry/exit charge.
    if unit == "fraction_apy":
        if cell.get("embedded_in_return") is True or float(value) == 0.0:
            return 0.0
        raise PaperRefusal(f"{what}: annual component {comp.get('kind')!r} is not embedded in the NAV price and "
                           f"non-zero — needs an accrual model, never netted as a one-off")
    if unit == "fraction_of_yield":
        return 0.0
    raise PaperRefusal(f"{what}: component {comp.get('kind')!r} has unknown unit {unit!r}")


def _amortised_daily_usd(one_off_usd: float, holding_period_days: Optional[float]) -> Optional[float]:
    """One-off bps amortised ONLY by a declared holding period (binding #9's last clause) —
    ``None`` (never 0) when no holding period was declared; a display aid, not an accounting row
    field."""
    if not isinstance(holding_period_days, (int, float)) or isinstance(holding_period_days, bool) \
            or holding_period_days <= 0:
        return None
    return one_off_usd / holding_period_days


# ── gate (binding #9 line 1): ADMIT is the only door, decision/admission/bundle must agree ─────

def _validate_gate(decision: Any, admission: Any, bundle: Any) -> None:
    if not isinstance(decision, dict) or decision.get("decision") != ec.ADMIT_TO_PAPER:
        raise PaperRefusal(f"decision is not {ec.ADMIT_TO_PAPER!r} — open refused")
    if not isinstance(admission, dict) or admission.get("schema") != ec.SCHEMA_ADMISSION_V2:
        raise PaperRefusal(f"admission schema is not {ec.SCHEMA_ADMISSION_V2!r} — open refused")
    decision_id = decision.get("decision_id")
    bundle_digest = decision.get("bundle_digest")
    candidate_id = decision.get("candidate_id")
    if not decision_id or not bundle_digest or not candidate_id:
        raise PaperRefusal("decision is missing decision_id / bundle_digest / candidate_id")
    if admission.get("decision_id") != decision_id:
        raise PaperRefusal("admission.decision_id does not match the decision — open refused")
    if admission.get("bundle_digest") != bundle_digest:
        raise PaperRefusal("admission.bundle_digest does not match the decision — open refused")
    if admission.get("candidate_id") != candidate_id:
        raise PaperRefusal("admission.candidate_id does not match the decision — open refused")
    if not isinstance(bundle, dict) or bundle.get("schema_version") != ec.SCHEMA_BUNDLE:
        raise PaperRefusal(f"bundle schema is not {ec.SCHEMA_BUNDLE!r} — open refused")
    if bundle.get("candidate_id") != candidate_id:
        raise PaperRefusal("bundle.candidate_id does not match the decision — open refused")
    if bundle.get("evidence_digest") != bundle_digest:
        raise PaperRefusal("bundle.evidence_digest does not match decision.bundle_digest — "
                           "stale or wrong bundle, open refused")
    paper_mode = decision.get("paper_mode")
    if paper_mode not in ec.PAPER_MODES:
        raise PaperRefusal(f"decision.paper_mode {paper_mode!r} is not one of {ec.PAPER_MODES}")
    if admission.get("paper_mode") != paper_mode:
        raise PaperRefusal("admission.paper_mode does not match the decision — open refused")


def _leg_accounting(bundle_acc: Any, leg_id: Optional[str]) -> dict:
    legs = bundle_acc.get("legs") if isinstance(bundle_acc, dict) else None
    if isinstance(legs, dict):
        if leg_id is None:
            raise PaperRefusal("bundle declares multiple legs but no leg_id was selected")
        block = legs.get(leg_id)
        if not isinstance(block, dict):
            raise PaperRefusal(f"no paper_accounting_evidence for leg {leg_id!r}")
        return block
    if leg_id is not None:
        raise PaperRefusal(f"leg_id {leg_id!r} given but bundle declares no 'legs'")
    if not isinstance(bundle_acc, dict):
        raise PaperRefusal("bundle has no paper_accounting_evidence")
    return bundle_acc


# ── open ─────────────────────────────────────────────────────────────────────────────────────

def open_position(data_dir: Path, decision: dict, admission: dict, bundle: dict, now: datetime) -> dict:
    """ADMIT_TO_PAPER + a matching paper-admission/2 snapshot -> one (or, for a two-leg
    funding-pair mechanism, one PER LEG) ``paper_open`` row. Returns the single row, or
    ``{"legs": {leg_id: row, ...}}`` for a multi-leg candidate."""
    _validate_gate(decision, admission, bundle)
    candidate_id = decision["candidate_id"]
    decision_id = decision["decision_id"]
    admission_id = admission["admission_id"]
    paper_mode = decision["paper_mode"]
    acc = bundle.get("paper_accounting_evidence")
    legs = acc.get("legs") if isinstance(acc, dict) else None
    leg_ids = sorted(legs.keys()) if isinstance(legs, dict) else [None]
    rows = {}
    for leg_id in leg_ids:
        block = _leg_accounting(acc, leg_id)
        rows[leg_id] = _open_one_leg(data_dir, candidate_id, decision_id, admission_id, paper_mode,
                                     block, leg_id, now)
    if leg_ids == [None]:
        return rows[None]
    return {"legs": rows}


def _open_one_leg(data_dir: Path, candidate_id: str, decision_id: str, admission_id: str,
                  paper_mode: str, block: dict, leg_id: Optional[str], now: datetime) -> dict:
    notional = ec.PAPER_NOTIONAL_USD
    entry_price = _valued_or_refuse(block.get("entry_price"), "entry_price")
    if entry_price <= 0:
        raise PaperRefusal("entry_price must be positive")

    entry_components = block.get("entry_fee_components")
    if not entry_components:
        raise PaperRefusal("entry_fee_components missing or empty — state NOT_APPLICABLE "
                           "explicitly, never omit the fee entirely")
    entry_fees_usd = sum(_fee_component_usd(c, notional, "entry_fee") for c in entry_components)

    if paper_mode == ec.PAPER_MODE_HOLDABLE:
        exit_components = block.get("exit_fee_components")
        if not exit_components:
            raise PaperRefusal("exit_fee_components missing or empty for a HOLDABLE position — "
                               "state NOT_APPLICABLE explicitly")
        for c in exit_components:
            _fee_component_usd(c, notional, "exit_fee")  # validated now; applied at close()
        delay_cell = block.get("redemption_delay_days")
        if isinstance(delay_cell, dict) and delay_cell.get("state") == c1.NOT_APPLICABLE:
            redemption_delay_days = 0.0
        else:
            redemption_delay_days = _valued_or_refuse(delay_cell, "redemption_delay_days")
    else:
        exit_components = []
        redemption_delay_days = 0.0  # REFERENCE_TRACK: no exit-liquidity claim, NOT_APPLICABLE by mode

    units = notional / entry_price
    position_id = c1.digest({"candidate_id": candidate_id, "decision_id": decision_id,
                            "admission_id": admission_id, "leg_id": leg_id})[:24]
    price_is_net_cell = block.get("price_is_net_of_performance_fee")
    # H4 fix (post-implementation review): the OLD code recognised ONLY a NOT_APPLICABLE cell
    # ("no performance fee exists on this product at all") as skipping the accrual — missing the
    # OTHER legitimate way a product tells us not to double-count it: a VALUED fact of EXACTLY
    # 1.0 ("the price is already net of the performance fee", e.g. USYC's cited DOCUMENTED 1.0).
    # Both skip the fee, for different reasons, so this is an OR, never a replacement of one by
    # the other — "NOT_APPLICABLE stays 'no performance fee'" is a requirement on the OUTCOME,
    # not something left to coincide via an absent performance_fee_rate.
    price_is_net = isinstance(price_is_net_cell, dict) and (
        price_is_net_cell.get("state") == c1.NOT_APPLICABLE
        or (price_is_net_cell.get("state") in c1.VALUED_STATES and price_is_net_cell.get("value") == 1.0))
    holding_period_days = block.get("holding_period_days_declared")
    if isinstance(holding_period_days, bool) or not isinstance(holding_period_days, (int, float)):
        holding_period_days = None
    entry_fee_amortised = _amortised_daily_usd(entry_fees_usd, holding_period_days)

    at = iso(now)
    nav0 = units * entry_price - entry_fees_usd
    row = {f: None for f in ec.PAPER_FIELDS}
    row.update({
        "position_id": position_id, "candidate_id": candidate_id, "decision_id": decision_id,
        "admission_id": admission_id, "paper_mode": paper_mode, "leg_id": leg_id, "opened_at": at,
        "initial_notional_usd": notional, "units": units, "entry_price": entry_price,
        "entry_value_usd": units * entry_price, "entry_fees_usd": entry_fees_usd,
        "cash_usd": -entry_fees_usd, "position_value_usd": units * entry_price, "nav_usd": nav0,
        "realised_return": None, "unrealised_return": nav0 / notional - 1.0,
        "performance_fee_accrual_usd": 0.0, "fee_source": block.get("fee_source"),
        "holding_period_days_declared": holding_period_days,
    })
    row.update({
        "schema": ec.SCHEMA_PAPER, "status": "OPEN", "mark_state": "NEVER_MARKED", "last_mark_at": None,
        "return_origin_group": block.get("return_origin_group"),
        "entry_fee_components": entry_components, "exit_fee_components": exit_components,
        "redemption_delay_days": redemption_delay_days, "price_is_net": price_is_net,
        "performance_fee_rate": block.get("performance_fee_rate"), "leverage": block.get("leverage"),
        "maintenance_margin_rate": block.get("maintenance_margin_rate"),
        "collateral_yield_rate": block.get("collateral_yield_rate"),
        "entry_fee_amortised_usd_per_day": entry_fee_amortised,
        "_high_water_mark": notional, "closed_at": None, "close_reason": None,
    })
    ledger = ledger_for(data_dir)
    key = ["paper_open", candidate_id, admission_id, leg_id if leg_id is not None else "_single"]
    try:
        return ledger.append("paper_open", key, row, at)
    except DuplicateKey as dup:
        return dup.existing


# ── read helpers ─────────────────────────────────────────────────────────────────────────────

def _latest_row(ledger, position_id: str) -> Optional[dict]:
    best = None
    for e in ledger.read_all():
        if e.get("kind") not in ec.PAPER_KINDS:
            continue
        if (e.get("payload") or {}).get("position_id") != position_id:
            continue
        if best is None or e["seq"] > best["seq"]:
            best = e
    return best


def _require_open(ledger, position_id: str, action: str) -> dict:
    prev = _latest_row(ledger, position_id)
    if prev is None:
        raise PaperRefusal(f"no position {position_id!r} — cannot {action}")
    if prev["payload"].get("status") == "CLOSED":
        raise PaperRefusal(f"position {position_id!r} is closed — cannot {action}")
    return prev


def _mark_at_or_before(ledger, position_id: str, settlement_ts: str) -> Optional[float]:
    """The per-unit price of the latest VALUED mark at-or-before ``settlement_ts`` — never a
    forward-filled guess, ``None`` if no such mark exists."""
    target = c1.parse_ts(settlement_ts)
    if target is None:
        return None
    best_price, best_at = None, None
    for e in ledger.read_all():
        if e.get("kind") != "paper_mark":
            continue
        p = e.get("payload") or {}
        if p.get("position_id") != position_id:
            continue
        value = p.get("position_value_usd")
        units = p.get("units")
        if not isinstance(value, (int, float)) or not isinstance(units, (int, float)) or units == 0:
            continue
        mark_at = c1.parse_ts(p.get("last_mark_at"))
        if mark_at is None or mark_at > target:
            continue
        if best_at is None or mark_at > best_at:
            best_at, best_price = mark_at, value / units
    return best_price


# ── mark ─────────────────────────────────────────────────────────────────────────────────────

def _apply_performance_fee(row: dict, position_value: float) -> float:
    """Accrue the performance fee only where the price is not net (binding #9): a cited
    "price is net" fact makes it NOT_APPLICABLE forever (``row['price_is_net']``). Otherwise a
    standard high-water-mark accrual on the rate cell — carried forward unchanged (never reset
    to 0) whenever the rate itself is not currently valued."""
    if row.get("price_is_net"):
        return 0.0
    existing = row.get("performance_fee_accrual_usd")
    existing = existing if isinstance(existing, (int, float)) else 0.0
    rate_cell = row.get("performance_fee_rate")
    state = rate_cell.get("state") if isinstance(rate_cell, dict) else None
    if state not in c1.VALUED_STATES:
        return existing
    prior_hwm = row.get("_high_water_mark")
    if not isinstance(prior_hwm, (int, float)):
        prior_hwm = row.get("initial_notional_usd")
    new_hwm = max(prior_hwm, position_value)
    row["_high_water_mark"] = new_hwm
    gain = new_hwm - prior_hwm
    if gain <= 0:
        return existing
    return existing + float(rate_cell["value"]) * gain


def _leverage_fields(payload: dict) -> tuple:
    lev_cell = payload.get("leverage")
    mmr_cell = payload.get("maintenance_margin_rate")
    lev_state = lev_cell.get("state") if isinstance(lev_cell, dict) else None
    mmr_state = mmr_cell.get("state") if isinstance(mmr_cell, dict) else None
    if lev_state not in c1.VALUED_STATES or mmr_state not in c1.VALUED_STATES:
        return None, None
    leverage = float(lev_cell["value"])
    mmr = float(mmr_cell["value"])
    if leverage <= 0:
        return None, None
    notional = payload.get("initial_notional_usd")
    margin_usd = notional / leverage if isinstance(notional, (int, float)) else None
    # Liquidation distance is ESTIMATED_WITH_METHOD from the cited maintenance-margin tiers —
    # NEVER MEASURED (binding #9): re-estimated at the CURRENT mark, not frozen at entry.
    distance_fraction = max(0.0, 1.0 / leverage - mmr)
    liquidation_distance = c1.cell(
        c1.ESTIMATED_WITH_METHOD, round(distance_fraction, 10), unit="fraction",
        method="1/leverage - maintenance_margin_rate, from cited maintenance-margin tiers")
    return margin_usd, liquidation_distance


def _collateral_yield_usd(payload: dict, position_value: float) -> Optional[float]:
    rate_cell = payload.get("collateral_yield_rate")
    state = rate_cell.get("state") if isinstance(rate_cell, dict) else None
    if state not in c1.VALUED_STATES:
        return None
    return float(rate_cell["value"]) * position_value


def mark(data_dir: Path, position_id: str, obs: dict, now: datetime) -> dict:
    """One ``paper_mark`` row. ``obs = {"price": cell, "mark_origin": str,
    "origin_group": str|None, "leg_id": str|None, "family": str|None}``.

    H3 fix (post-implementation review): a VALUED price cell is FRESH only when its OWN
    ``as_of`` judges fresh via ``grades.freshness_verdict(family, as_of, now)`` —
    ``family`` defaults to :data:`DEFAULT_MARK_FAMILY` ("nav_business_day": NAVs may stay flat
    over weekends/holidays). A cell that is not VALUED at all, OR is VALUED but STALE/UNKNOWN
    (no judgeable ``as_of``), is recorded STALE with NO price — the previous price is never
    forward-filled either way.

    Keyed by ``(position_id, price_cell["as_of"])`` — not the wall clock — so the SAME upstream
    reading looked at by any number of runs is ONE row. A cell with no judgeable ``as_of`` at all
    is keyed by ``(position_id, "stale", today's date)``: one "nothing new today" row per day,
    never one per call."""
    if not isinstance(obs, dict):
        raise PaperRefusal("mark needs an obs dict")
    ledger = ledger_for(data_dir)
    prev = _require_open(ledger, position_id, "mark")
    payload = prev["payload"]
    leg_id = obs.get("leg_id")
    if leg_id != payload.get("leg_id"):
        raise PaperRefusal(f"obs leg_id {leg_id!r} does not match position leg {payload.get('leg_id')!r}")
    mark_origin = obs.get("mark_origin")
    if not mark_origin:
        raise PaperRefusal("mark needs mark_origin — the row never records a price without one")
    price_cell = obs.get("price")
    origin_group = obs.get("origin_group")
    return_group = payload.get("return_origin_group")
    mark_circular = None
    if origin_group is not None and return_group is not None:
        mark_circular = (origin_group == return_group)

    at = iso(now)
    row = dict(payload)
    row["mark_origin"] = mark_origin
    row["mark_circular"] = mark_circular
    row["price_source"] = price_cell.get("source_root") if isinstance(price_cell, dict) else None

    state = price_cell.get("state") if isinstance(price_cell, dict) else None
    as_of_raw = price_cell.get("as_of") if isinstance(price_cell, dict) else None
    as_of_dt = c1.parse_ts(as_of_raw)
    family = obs.get("family")
    if not family:
        family = DEFAULT_MARK_FAMILY
    freshness = grades_mod.freshness_verdict(family, as_of_dt, now)

    if state in c1.VALUED_STATES and freshness == ec.ADEQUATE:
        value = price_cell.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PaperRefusal("price cell carries no finite value")
        price = float(value)
        units = payload["units"]
        position_value = units * price
        perf_accrual = _apply_performance_fee(row, position_value)
        nav_usd = position_value + payload["cash_usd"] - perf_accrual
        margin_usd, liquidation_distance = _leverage_fields(payload)
        row.update({
            "position_value_usd": position_value, "nav_usd": nav_usd,
            "unrealised_return": nav_usd / payload["initial_notional_usd"] - 1.0,
            "performance_fee_accrual_usd": perf_accrual, "margin_usd": margin_usd,
            "liquidation_distance": liquidation_distance,
            "collateral_yield_usd": _collateral_yield_usd(payload, position_value),
            "mark_state": "FRESH", "last_mark_at": at, "funding_usd": None,
        })
    else:
        # STALE mark: NO price, nothing else recomputed off a price we do not have — the
        # position's last known NAV/value is NOT carried into this row as if fresh. Covers BOTH
        # an unvalued price cell AND a valued-but-stale/unjudgeable one (H3) — same treatment.
        row.update({"position_value_usd": None, "nav_usd": None, "unrealised_return": None,
                   "mark_state": "STALE", "funding_usd": None})

    if as_of_dt is not None:
        key = ["paper_mark", position_id, as_of_raw]
    else:
        key = ["paper_mark", position_id, "stale", now.date().isoformat()]
    try:
        return ledger.append("paper_mark", key, row, at)
    except DuplicateKey as dup:
        return dup.existing


# ── cashflow (funding) ───────────────────────────────────────────────────────────────────────

def cashflow(data_dir: Path, position_id: str, settlement: dict, now: datetime) -> dict:
    """Funding at ONE settlement timestamp, on the notional valued at THAT settlement's mark
    (binding #9) — never the entry notional, never the current one. ``settlement =
    {"settlement_ts": iso str, "funding_rate": cell, "unit": "fraction"|"bps"}``."""
    if not isinstance(settlement, dict):
        raise PaperRefusal("cashflow needs a settlement dict")
    ledger = ledger_for(data_dir)
    prev = _require_open(ledger, position_id, "apply a cashflow")
    payload = prev["payload"]
    settlement_ts = settlement.get("settlement_ts")
    if not isinstance(settlement_ts, str) or c1.parse_ts(settlement_ts) is None:
        raise PaperRefusal("cashflow needs a parseable settlement_ts")
    rate_cell = settlement.get("funding_rate")
    rate_value = _valued_or_refuse(rate_cell, "funding_rate")
    unit = settlement.get("unit")
    if unit is None:
        unit = "fraction"
    if unit == "bps":
        rate_value = rate_value / 10_000.0
    elif unit != "fraction":
        raise PaperRefusal(f"funding_rate unit {unit!r} not understood")

    price_at_settlement = _mark_at_or_before(ledger, position_id, settlement_ts)
    if price_at_settlement is None:
        raise PaperRefusal("no valued mark at or before this settlement — cannot value the "
                           "notional at settlement time, never assumed")
    notional_at_settlement = payload["units"] * price_at_settlement
    funding_usd = notional_at_settlement * rate_value

    row = dict(payload)
    row["cash_usd"] = payload["cash_usd"] + funding_usd
    row["funding_usd"] = funding_usd
    position_value = payload.get("position_value_usd")
    if isinstance(position_value, (int, float)):
        perf = payload.get("performance_fee_accrual_usd")
        perf = perf if isinstance(perf, (int, float)) else 0.0
        row["nav_usd"] = position_value + row["cash_usd"] - perf
        row["unrealised_return"] = row["nav_usd"] / payload["initial_notional_usd"] - 1.0

    at = iso(now)
    key = ["paper_cashflow", position_id, settlement_ts]
    try:
        return ledger.append("paper_cashflow", key, row, at)
    except DuplicateKey as dup:
        return dup.existing


# ── unit change (dividend mints, rebases) ───────────────────────────────────────────────────

def unit_change(data_dir: Path, position_id: str, event: dict, now: datetime) -> dict:
    """A dividend mint (``units_delta``) or a rebase (``new_units`` absolute balance). Keyed by
    ``event["event_id"]`` — a declared economic-event id (e.g. a mint id or tx hash), not the
    wall clock, so the SAME event replayed twice is a no-op, never a double mint."""
    if not isinstance(event, dict):
        raise PaperRefusal("unit_change needs an event dict")
    event_id = event.get("event_id")
    if not event_id:
        raise PaperRefusal("unit_change needs an event_id for idempotency")
    ledger = ledger_for(data_dir)
    prev = _require_open(ledger, position_id, "apply a unit change")
    payload = prev["payload"]

    delta_cell = event.get("units_delta")
    new_units_cell = event.get("new_units")
    if isinstance(delta_cell, dict) and delta_cell.get("state") in c1.VALUED_STATES:
        units = payload["units"] + float(delta_cell["value"])
    elif isinstance(new_units_cell, dict) and new_units_cell.get("state") in c1.VALUED_STATES:
        units = float(new_units_cell["value"])
    else:
        raise PaperRefusal("unit_change needs a valued units_delta or new_units — units are "
                           "never assumed unchanged by default")

    row = dict(payload)
    row["units"] = units
    prior_value = payload.get("position_value_usd")
    prior_units = payload.get("units")
    if isinstance(prior_value, (int, float)) and isinstance(prior_units, (int, float)) and prior_units:
        last_price = prior_value / prior_units
        position_value = units * last_price
        perf = payload.get("performance_fee_accrual_usd")
        perf = perf if isinstance(perf, (int, float)) else 0.0
        row["position_value_usd"] = position_value
        row["nav_usd"] = position_value + payload["cash_usd"] - perf
        row["unrealised_return"] = row["nav_usd"] / payload["initial_notional_usd"] - 1.0
    row["funding_usd"] = None

    at = iso(now)
    key = ["paper_unit_change", position_id, event_id]
    try:
        return ledger.append("paper_unit_change", key, row, at)
    except DuplicateKey as dup:
        return dup.existing


# ── close ────────────────────────────────────────────────────────────────────────────────────

def close(data_dir: Path, position_id: str, obs: dict, now: datetime, reason: str) -> dict:
    """Exit at NAV − redemption fee − delay haircut (+ slippage where relevant). A
    REFERENCE_TRACK position is a NAV tracker with no exit-liquidity claim: redemption fee,
    delay haircut and slippage are NOT_APPLICABLE BY MODE, never a missing-as-zero. A HOLDABLE
    position requires every applicable obs field VALUED (or explicitly NOT_APPLICABLE) — close()
    refuses rather than assuming 0, exactly like open()."""
    if not reason:
        raise PaperRefusal("close always names its reason")
    if not isinstance(obs, dict):
        raise PaperRefusal("close needs an obs dict")
    ledger = ledger_for(data_dir)
    prev = _latest_row(ledger, position_id)
    if prev is None:
        raise PaperRefusal(f"no position {position_id!r} — cannot close")
    payload = prev["payload"]
    if payload.get("status") == "CLOSED":
        return prev  # idempotent: already closed, never re-closed with different terms

    exit_price = _valued_or_refuse(obs.get("price"), "exit price")
    units = payload["units"]
    gross_exit_value = units * exit_price
    paper_mode = payload["paper_mode"]

    if paper_mode == ec.PAPER_MODE_HOLDABLE:
        exit_components = payload.get("exit_fee_components")
        exit_components = exit_components if isinstance(exit_components, list) else []
        exit_fees_usd = sum(_fee_component_usd(c, gross_exit_value, "exit_fee") for c in exit_components)

        delay_days = payload.get("redemption_delay_days")
        delay_days = delay_days if isinstance(delay_days, (int, float)) else 0.0
        haircut_rate_cell = obs.get("redemption_delay_haircut_rate")
        if delay_days == 0:
            haircut_usd = 0.0
        elif isinstance(haircut_rate_cell, dict) and haircut_rate_cell.get("state") in c1.VALUED_STATES:
            haircut_usd = gross_exit_value * float(haircut_rate_cell["value"]) * (delay_days / 365.0)
        elif isinstance(haircut_rate_cell, dict) and haircut_rate_cell.get("state") == c1.NOT_APPLICABLE:
            haircut_usd = 0.0
        else:
            raise PaperRefusal("redemption delay > 0 days but no haircut rate — never assumed 0")

        slippage_cell = obs.get("slippage")
        if not isinstance(slippage_cell, dict):
            raise PaperRefusal("close needs a slippage cell (state NOT_APPLICABLE when slippage "
                               "does not apply to this mechanism) — never assumed 0 by omission")
        if slippage_cell.get("state") == c1.NOT_APPLICABLE:
            slippage_usd = 0.0
        elif slippage_cell.get("state") in c1.VALUED_STATES:
            value = slippage_cell.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise PaperRefusal("slippage cell carries no finite value")
            slippage_usd = float(value)
        else:
            raise PaperRefusal(f"slippage is {slippage_cell.get('state')!r} — never 0 by default")
    else:
        # REFERENCE_TRACK: never a position SPA could hold/exit — no redemption, no delay, no
        # market-impact slippage is claimed; these are NOT_APPLICABLE by MODE, not by omission.
        exit_fees_usd = 0.0
        haircut_usd = 0.0
        slippage_usd = 0.0

    exit_value_usd = gross_exit_value - exit_fees_usd - haircut_usd - slippage_usd
    perf = payload.get("performance_fee_accrual_usd")
    perf = perf if isinstance(perf, (int, float)) else 0.0
    nav_usd = exit_value_usd + payload["cash_usd"] - perf

    at = iso(now)
    row = dict(payload)
    row.update({
        "status": "CLOSED", "closed_at": at, "close_reason": reason, "mark_state": "CLOSED",
        "position_value_usd": gross_exit_value, "exit_value_usd": exit_value_usd,
        "exit_fees_usd": exit_fees_usd, "redemption_delay_haircut_usd": haircut_usd,
        "slippage_usd": slippage_usd, "nav_usd": nav_usd,
        "realised_return": nav_usd / payload["initial_notional_usd"] - 1.0,
        "unrealised_return": None, "funding_usd": None,
    })
    key = ["paper_close", position_id]
    try:
        return ledger.append("paper_close", key, row, at)
    except DuplicateKey as dup:
        return dup.existing


# ── views ────────────────────────────────────────────────────────────────────────────────────

_NAV_VIEW_FIELDS = (
    "candidate_id", "leg_id", "paper_mode", "status", "mark_state", "units", "nav_usd",
    "position_value_usd", "cash_usd", "realised_return", "unrealised_return", "last_mark_at",
    "mark_origin", "mark_circular", "performance_fee_accrual_usd", "margin_usd",
    "liquidation_distance", "funding_usd",
)


def nav(data_dir: Path, position_id: str) -> dict:
    """The current (or final, if closed) NAV view of one position — derived from its single
    LATEST ledger row, which is always a full snapshot."""
    ledger = ledger_for(data_dir)
    row = _latest_row(ledger, position_id)
    if row is None:
        raise PaperRefusal(f"no position {position_id!r}")
    p = row["payload"]
    out = {"position_id": position_id}
    out.update({f: p.get(f) for f in _NAV_VIEW_FIELDS})
    return out


def positions(data_dir: Path) -> list:
    """Every position ever opened (open or closed), each as its current :func:`nav` view."""
    ledger = ledger_for(data_dir)
    latest_by_id: dict = {}
    for e in ledger.read_all():
        if e.get("kind") not in ec.PAPER_KINDS:
            continue
        pid = (e.get("payload") or {}).get("position_id")
        if not pid:
            continue
        cur = latest_by_id.get(pid)
        if cur is None or e["seq"] > cur["seq"]:
            latest_by_id[pid] = e
    return [nav(data_dir, pid) for pid in sorted(latest_by_id)]
