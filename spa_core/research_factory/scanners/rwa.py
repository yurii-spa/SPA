"""spa_core/research_factory/scanners/rwa.py — RWA / stable-yield track (ADR-560 WP-S04).

The 11 ``rwa_safety_board.json`` assets, cross-referenced against:

* ``spa_core/strategy_lab/rwa_backstop/collateral_registry.py`` for the public mainnet token
  contract (where one exists — a transfer-restricted fund with NO public contract, e.g. sBUIDL,
  VBILL, STAC, BENJI, is ``unresolved``, never a symbol fallback, per review #2);
* ``data/market_data/rwa_floor.json`` per-pool rows, when the SAME issuer/symbol happens to be one
  of the seven live-rated pools there, for a per-instrument rate (never the aggregate floor,
  review #15);
* ``onchain.realised_index`` for cUSDO / wUSDM, the two GENUINE ERC-4626 wrappers in the set
  (``nav_source == "onchain_4626"`` in the safety board itself) — an independent on-chain NAV
  series, not the board's own already-computed value (that value used a *different*, non-quorum
  RPC path; review #5 asks for THIS package's own 2-of-N quorum read). Per post-implementation
  review H6c, this NAV read is recorded ONLY as its own ``observations[cid]["realised_index"]``
  fact — it never upgrades the counterparty ``reserve_transparency`` dimension (a share price is
  not a reserve-composition fact).

rwa.py owns EVERY fund ``rwa_safety_board.json`` names, exclusively (post-implementation review
M1): ``cash_treasury.py`` reads the same ``market_data/rwa_floor.json`` cache but skips any pool
whose symbol is in ``cash_treasury.SAFETY_BOARD_SYMBOLS``, so a fund is never emitted by two
scanners. The shared root table (``cash_treasury.FUND_ROOTS``) is imported, not re-declared, so
"the same fund" always means the same ``underlying_root`` across every scanner.

"Tokenised Treasury" is never treated as risk-free: every liquidity/exit fact below is the
board's own documented-vs-observed split, carried through, never upgraded to MEASURED here.

LLM_FORBIDDEN, stdlib only; no network of its own (only ``onchain.realised_index``, which no-ops
to NOT_MEASURED without an injected ``rpc_client``).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from spa_core.research_factory import contract, counterparty_registry, instruments, onchain, registry_loader
from spa_core.research_factory.scanners._common import (empty_result, full_candidate, not_applicable,
                                                          not_measured, read_json)
from spa_core.research_factory.scanners.cash_treasury import FUND_ROOTS, fund_root

try:
    from spa_core.strategy_lab.rwa_backstop import collateral_registry
except Exception:  # noqa: BLE001 — the registry is pure config; absence is still a named outcome
    collateral_registry = None

SCANNER_NAME = "rwa"
DOMAIN = "RWA_STABLE_YIELD"

#: collateral_registry.asset_class → mechanism (conservative: unknown asset_class ⇒ the stricter,
#: credit-like mechanism rather than the gentler treasury one).
ASSET_CLASS_MECHANISM = {"tokenized_tbill": "TOKENISED_TREASURY", "tokenized_mmf": "TOKENISED_TREASURY",
                         "tokenized_credit": "RWA_CREDIT"}


#: the four instruments the Phase-0 audit (ADR-564) actually traced to a wrong-chain pool join
#: AND a cited, non-zero fee — ``_floor_rate_by_symbol`` below is SYMBOL-keyed (``rwa_floor.json``
#: carries no chain/underlying-contract field at all) and is therefore unsafe for exactly these
#: four; everything else in the 11-asset board is unaffected and keeps the pre-existing behaviour.
CHAIN_JOIN_REQUIRED_SYMBOLS = frozenset(instruments.INSTRUMENTS.keys())

def _fact(symbol: str, claim_type: str, *, now: datetime) -> "dict | None":
    """The newest NON-STALE fact for ``symbol``'s own candidate + ``claim_type``.

    M5 (post-implementation review, 2026-10-04): this used to be a second, private,
    UNVALIDATED loader — it parsed ``facts.jsonl`` by hand, silently skipped malformed lines
    (``except json.JSONDecodeError: continue``) and ignored ``expires_at`` entirely. The ONLY
    door now is ``registry_loader.load_facts()`` and ``registry_loader.facts_for(..., now=now)``
    (which excludes a fact past its own ``expires_at`` — staleness is judged, not ignored).

    ``registry_loader`` refuses a MALFORMED line loudly (``FactRegistryError`` propagates — a
    corrupt git-tracked registry must halt this scan, never degrade silently). It is caught here
    ONLY for the one NAMED, EXPECTED refusal reason the coordinator told this package to keep
    producing: ``evidence_contract.FACT_REQUIRES_INDEPENDENT_REVIEW`` refuses every fact in this
    seed because ``reviewed_by`` is still ``null`` (an independent review session, not this one,
    stamps it) — every call site already has its OWN static NOT_MEASURED fallback for "no fact
    found", so that refusal degrades to exactly that, not a crash. Any OTHER ``FactRegistryError``
    reason (a genuinely malformed line) still propagates uncaught."""
    if symbol not in instruments.INSTRUMENTS:
        return None
    cid = instruments.candidate_id_for(symbol)
    try:
        facts = registry_loader.load_facts()
    except registry_loader.FactRegistryError as exc:
        if "reviewed_by" in exc.reason or "FACT_REQUIRES_INDEPENDENT_REVIEW" in exc.reason:
            return None
        raise
    for f in registry_loader.facts_for(facts, cid, now=now):
        if f.get("claim_type") == claim_type:
            return f
    return None


#: ADR-564 integration finding (2026-10-04, coordinator live run): a live run netted
#: `-2697` because a ONE-OFF cost (USYC's 4+3 bps subscription/redemption) was labelled
#: ``unit="fraction"`` — a unit `contract.ANNUAL_RATE_UNITS` treats as an ANNUAL rate, so
#: `net_expected_return` subtracted a one-off trade cost from an APY as if it recurred every
#: year. Every fee cell/component below now declares its unit HONESTLY, in exactly one of three
#: families, never the ambiguous bare ``"fraction"`` again:
#:   * UNIT_ANNUAL ("fraction_apy") — a recurring annual rate (management fee); IS an
#:     ``ANNUAL_RATE_UNITS`` member, so `net_expected_return` may subtract it directly.
#:   * UNIT_ONE_OFF ("fraction_one_off") — a one-off cost (subscription/redemption/entry/exit);
#:     deliberately NOT in `ANNUAL_RATE_UNITS` — `net_expected_return` refuses to net it until
#:     amortised over a declared holding period (never silently annualised). Carried only in
#:     ``paper_accounting_hints``' fee-component lists, never in the v1 candidate's own cell.
#:   * UNIT_OF_YIELD ("fraction_of_yield") — a performance fee, a fraction OF THE YIELD earned,
#:     not of NAV and not an annual rate on its own; always ``embedded_in_return=True`` here
#:     because the cited price is already net of it.
UNIT_ANNUAL = "fraction_apy"
UNIT_ONE_OFF = "fraction_one_off"
UNIT_OF_YIELD = "fraction_of_yield"

#: M5 (post-implementation review, 2026-10-04): the OUSG management-fee waiver's END DATE
#: ("waived until January 1, 2027") is cited only as free text inside the curated fact's own
#: ``quote`` field — the registry schema carries no structured waiver-end field at all, so this
#: literal is the one honest thing the scanner can act on. Once ``now`` reaches it, continuing to
#: report the fee as a DOCUMENTED 0 would silently extend a waiver past the one date the citation
#: ever named — exactly the missing-as-zero shape invariant #17 forbids. NOT_MEASURED from this
#: date onward, never a guess about what the fee becomes.
OUSG_MGMT_FEE_WAIVER_END = "2027-01-01T00:00:00+00:00"


def _ousg_waiver_expired(now: datetime) -> bool:
    end = contract.parse_ts(OUSG_MGMT_FEE_WAIVER_END)
    if end is None:
        return False
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return now_aware >= end


def _phase0_fee_cell(symbol: str, now: datetime) -> dict:
    """ADR-564 decision #3 + Phase-0 citations: the candidate's SINGLE v1 ``fees`` cell — the
    ANNUAL total ONLY, in ``UNIT_ANNUAL``, never the safety board's uncited
    ``redemption_fee_bps``. One-off components (subscription/redemption bps) are NEVER folded in
    here — they belong exclusively to ``paper_accounting_hints``' fee-component lists, each in a
    one-off unit `net_expected_return` will never mistake for an annual rate."""
    if symbol == "USYC":
        sub, red, perf = _fact("USYC", "fee_subscription", now=now), _fact("USYC", "fee_redemption", now=now), \
            _fact("USYC", "fee_performance", now=now)
        # M5 (post-implementation review, 2026-10-04): the "no recurring ANNUAL fee" conclusion is
        # built FROM all three facts together (subscription/redemption are one-off, performance is
        # embedded) — a figure built from an INCOMPLETE set of the facts it depends on must never
        # quietly stand in for "the missing one is also accounted for". The live defect: a single
        # cited fact (say redemption alone) was enough to print DOCUMENTED 0.0 for the TOTAL, with
        # the other two shown as a literal "?" in the method string — a missing fee silently
        # counted as zero. All three present, or NOT_MEASURED naming exactly which are missing.
        missing = [name for name, fact in (("fee_subscription", sub), ("fee_redemption", red),
                                           ("fee_performance", perf)) if fact is None]
        if not missing:
            fact_as_of = (sub or red or perf).get("effective_from") or (sub or red or perf).get("retrieved_at")
            return contract.cell(contract.DOCUMENTED, 0.0, unit=UNIT_ANNUAL,
                                 source_ref=(sub or red or perf)["ref"], source_class=contract.ISSUER_CLAIM,
                                 source_root="doc:usyc_fees", as_of=fact_as_of, recorded_at=now.isoformat(), now=now,
                                 method=f"no cited recurring ANNUAL fee for USYC; subscription ({sub['value']}) / "
                                        f"redemption ({red['value']}) are ONE-OFF (see paper_accounting_hints); "
                                        "performance fee is embedded in a net price")
        if sub or red or perf:
            return not_measured(f"USYC: missing fee fact(s) {missing} — the 'no recurring annual fee' figure "
                                "needs ALL of fee_subscription/fee_redemption/fee_performance, never a "
                                "partial set standing in for the missing ones")
        return not_measured("USYC: no fee facts found in registry/facts.jsonl")
    if symbol == "OUSG":
        mgmt = _fact("OUSG", "fee_management", now=now)
        expenses = _fact("OUSG", "fee_expenses_cap", now=now)
        if mgmt and expenses:
            # M5 (post-implementation review, 2026-10-04): "expenses capped at 0.15%" is NOT the
            # same claim as "management fee waived to 0" — the management fee IS 0 until
            # 2027-01-01 (cited), but OTHER fund expenses are only capped, never measured at an
            # actual run-rate. Folding the cap into "the annual fee is 0" would be exactly the
            # missing-as-zero invariant #17 forbids. The TOTAL annual cost cell is therefore
            # NOT_MEASURED — which, per paper.py's own stated discipline ("any component graded
            # NOT_MEASURED/STALE/CONFLICTED REFUSES the open"), correctly blocks a HOLDABLE net
            # for OUSG until the real expense run-rate is cited.
            fact_as_of = mgmt.get("effective_from") or mgmt.get("retrieved_at")
            return contract.cell(
                contract.NOT_MEASURED,
                reason=f"OUSG: management fee {mgmt['value']} (ANNUAL, cited {fact_as_of}) is WAIVED until "
                      f"2027-01-01 — currently-charged management fee is 0 — BUT total fund expenses are "
                      f"only capped at <= {expenses['value']} annually with no cited actual run-rate "
                      "(fee_expenses_cap fact); the TOTAL annual cost is NOT_MEASURED, never the "
                      "management-fee-only 0")
        if mgmt:
            # M5 (post-implementation review, 2026-10-04): the live defect — "mgmt fee is 0" was
            # reported as the TOTAL annual fee whenever the expenses-cap fact was simply missing
            # or refused, exactly the same missing-as-zero shape as the `mgmt and expenses` branch
            # above was already fixed for. A missing fact is never a zero fee: NOT_MEASURED,
            # naming fee_expenses_cap as the fact this figure could not be built without.
            return not_measured(
                f"OUSG: management fee {mgmt['value']} (ANNUAL, cited) is waived, but the fee_expenses_cap "
                "fact (other fund expenses) was not found/refused this run — the TOTAL annual cost cannot "
                "be concluded to be 0 from the management fee alone")
        return not_measured("OUSG: management-fee fact not found in registry/facts.jsonl")
    if symbol == "USDY":
        return not_measured("USDY: price is quoted \"minus a small spread\"; spread size undisclosed "
                            "(cited issuer terms) — COST UNKNOWN, never 0")
    if symbol == "BUIDL":
        return not_measured("BUIDL: no official fee figure published in this repo's citation seed — "
                            "COST UNKNOWN, never 0")
    return None


#: symbol -> the RETURN claim's affiliation group (registry/origins.json), for E1's bundle /
#: E2's mark_circular — the fact origin IS the oracle/NAV origin for all four (ADR-564 decision #2:
#: "an issuer-posted on-chain oracle, the issuer's API and an aggregator relaying them are ONE origin").
_RETURN_ORIGIN_GROUP = {"USYC": "circle", "OUSG": "ondo", "USDY": "ondo", "BUIDL": "blackrock"}


def _fee_component(kind: str, cell: dict, *, unit: str, effective_from, subject_to_change: bool,
                   one_off: bool) -> dict:
    return {"kind": kind, "cell": cell, "unit": unit, "effective_from": effective_from,
           "subject_to_change": subject_to_change, "one_off": one_off}


def paper_accounting_hints(symbol: str, now: datetime) -> "dict | None":
    """ADR-564 ``evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS`` / ``FEE_COMPONENT_FIELDS``
    shape (frozen by the paper.py/bundle.py integration, 2026-10-04) — a scanner HINT, copied by
    E1's bundle into ``paper_accounting_evidence``. Every fee cell here is either a cited VALUED
    (DOCUMENTED) cell or an honest NOT_MEASURED — paper.py's own docstring is explicit that a
    NOT_MEASURED/STALE/CONFLICTED component REFUSES the open, which for BUIDL/USDY is exactly the
    Phase-0 verdict ("not feasible with free evidence" / "spread undisclosed"): this hint does not
    soften that, it reports it."""
    if symbol not in instruments.INSTRUMENTS:
        return None
    group = _RETURN_ORIGIN_GROUP.get(symbol)
    if symbol == "USYC":
        sub, red, perf = _fact("USYC", "fee_subscription", now=now), _fact("USYC", "fee_redemption", now=now), \
            _fact("USYC", "fee_performance", now=now)
        net = _fact("USYC", "price_net_of_fees", now=now)
        entry = [_fee_component(
            "entry", contract.cell(contract.DOCUMENTED, float(sub["value"]), unit=UNIT_ONE_OFF,
                                   source_ref=sub["ref"], source_class=contract.ISSUER_CLAIM,
                                   source_root="doc:usyc_fees",
                                   as_of=sub.get("effective_from") or sub.get("retrieved_at"),
                                   recorded_at=now.isoformat(), now=now,
                                   method="subscription fee — ONE-OFF on entry, never an annual rate") if sub else
            not_measured("USYC: subscription-fee fact not found"),
            unit=UNIT_ONE_OFF, effective_from=sub.get("effective_from") if sub else None,
            subject_to_change=False, one_off=True)]
        exit_ = [_fee_component(
            "exit", contract.cell(contract.DOCUMENTED, float(red["value"]), unit=UNIT_ONE_OFF,
                                  source_ref=red["ref"], source_class=contract.ISSUER_CLAIM,
                                  source_root="doc:usyc_fees",
                                  as_of=red.get("effective_from") or red.get("retrieved_at"),
                                  recorded_at=now.isoformat(), now=now,
                                  method="redemption fee — ONE-OFF on exit, never an annual rate") if red else
            not_measured("USYC: redemption-fee fact not found"),
            unit=UNIT_ONE_OFF, effective_from=red.get("effective_from") if red else None,
            subject_to_change=False, one_off=True)]
        perf_note = (f"; price is NET of this fee (price_net_of_fees fact, {net['ref']})" if net else
                    "; whether the price already nets this fee is UNKNOWN (no price_net_of_fees fact)")
        perf_cell = (contract.cell(contract.DOCUMENTED, float(perf["value"]), unit=UNIT_OF_YIELD,
                                   source_ref=perf["ref"], source_class=contract.ISSUER_CLAIM,
                                   source_root="doc:usyc_fees",
                                   as_of=perf.get("effective_from") or perf.get("retrieved_at"),
                                   recorded_at=now.isoformat(), now=now, embedded_in_return=True,
                                   method=f"performance fee, a FRACTION OF THE YIELD earned (not of NAV, "
                                          f"not an annual rate on its own){perf_note}")
                    if perf else None)
        net_cell = (contract.cell(contract.DOCUMENTED, 1.0, unit="boolean", source_ref=net["ref"],
                                  source_class=contract.ISSUER_CLAIM, source_root="doc:usyc_fees",
                                  as_of=net.get("effective_from") or net.get("retrieved_at"),
                                  recorded_at=now.isoformat(), now=now)
                   if net else None)
        delay = contract.cell(contract.DOCUMENTED, 0.0, unit="days", source_ref=_fact("USYC", "redemption_terms", now=now)["ref"],
                              source_class=contract.ISSUER_CLAIM, source_root="doc:usyc_fees",
                              as_of=now.isoformat(), recorded_at=now.isoformat(), now=now,
                              method="Teller contract, 24/7, T+0 settlement (cited)") \
            if _fact("USYC", "redemption_terms", now=now) else not_measured("USYC: redemption-terms fact not found")
        return {"entry_price": None, "entry_fee_components": entry, "exit_fee_components": exit_,
               "redemption_delay_days": delay,
               "price_is_net_of_performance_fee": net_cell, "performance_fee_rate": perf_cell,
               "leverage": None, "maintenance_margin_rate": None, "collateral_yield_rate": None,
               "fee_source": "registry/facts.jsonl (USYC fee_subscription/fee_redemption/fee_performance/"
                             "price_net_of_fees)", "holding_period_days_declared": None,
               "return_origin_group": group}
    if symbol == "OUSG":
        mgmt = _fact("OUSG", "fee_management", now=now)
        expenses = _fact("OUSG", "fee_expenses_cap", now=now)
        # TWO separate ANNUAL components, never conflated (M5): the management fee IS known (0,
        # waived to 2027-01-01) — that component is DOCUMENTED; other fund expenses are only
        # CAPPED, with no cited actual run-rate — that component is honestly NOT_MEASURED (which
        # correctly blocks a HOLDABLE net, per paper.py's own discipline). FEE_COMPONENT_KINDS has
        # no "expenses" kind, so both use "management" — two components under one kind is a valid
        # shape (a list, not a dict keyed by kind).
        # M5 (post-implementation review, 2026-10-04): the waiver END DATE is not machine-readable
        # anywhere in the fact (free text in its quote only, see OUSG_MGMT_FEE_WAIVER_END above) —
        # once `now` reaches it, the cited 0 can no longer be assumed and this component must say
        # NOT_MEASURED instead of silently continuing to report a waiver the citation never
        # actually claimed past that date.
        if mgmt is None:
            mgmt_cell = not_measured("OUSG: management-fee fact not found")
        elif _ousg_waiver_expired(now):
            mgmt_cell = not_measured(
                f"OUSG: management fee waiver end (2027-01-01, cited only in the fact's quote text, never a "
                f"structured field) is not machine-readable — now ({now.isoformat()}) is on/after that date, "
                "so the cited 0 can no longer be assumed")
        else:
            mgmt_cell = contract.cell(contract.DOCUMENTED, 0.0, unit=UNIT_ANNUAL, source_ref=mgmt["ref"],
                                      source_class=contract.ISSUER_CLAIM, source_root="doc:ousg_fees",
                                      as_of=mgmt.get("effective_from") or mgmt.get("retrieved_at"),
                                      recorded_at=now.isoformat(), now=now,
                                      method=f"management fee {mgmt['value']} (ANNUAL) WAIVED until 2027-01-01 "
                                             "(cited) — currently-charged management fee is 0")
        expenses_cell = (not_measured(
            f"OUSG: fund expenses capped at <= {expenses['value']} annually (cited {expenses.get('effective_from')}) "
            "but the actual run-rate is not separately published — COST UNKNOWN, never folded into the "
            "waived management fee's 0")
            if expenses else not_measured("OUSG: expenses-cap fact not found"))
        entry = [
            _fee_component("management", mgmt_cell, unit=UNIT_ANNUAL,
                           effective_from=mgmt.get("effective_from") if mgmt else None,
                           subject_to_change=True, one_off=False),
            _fee_component("management", expenses_cell, unit=UNIT_ANNUAL,
                           effective_from=expenses.get("effective_from") if expenses else None,
                           subject_to_change=True, one_off=False),
        ]
        exit_ = [_fee_component("exit", not_measured("OUSG: no distinct exit fee cited beyond the waived "
                                                     "management fee"), unit=UNIT_ONE_OFF, effective_from=None,
                                subject_to_change=True, one_off=True)]
        delay = not_measured("OUSG: redemption is instant-atomic or next business day depending on size "
                             "(cited) — no single day count to cite")
        return {"entry_price": None, "entry_fee_components": entry, "exit_fee_components": exit_,
               "redemption_delay_days": delay,
               "price_is_net_of_performance_fee": None, "performance_fee_rate": None,
               "leverage": None, "maintenance_margin_rate": None, "collateral_yield_rate": None,
               "fee_source": "registry/facts.jsonl (OUSG fee_management/fee_expenses_cap)",
               "holding_period_days_declared": None, "return_origin_group": group}
    if symbol in ("USDY", "BUIDL"):
        reason = ("USDY: price is quoted \"minus a small spread\"; spread size undisclosed (cited) — "
                 "COST UNKNOWN, never 0" if symbol == "USDY" else
                 "BUIDL: no official fee figure published in this repo's citation seed — COST UNKNOWN, never 0")
        kind = "spread" if symbol == "USDY" else "entry"
        # a spread/undisclosed-entry-fee is charged PER TRANSACTION, not annually — ONE-OFF unit even
        # though the value itself is unknown (never let the UNIT imply "safe to treat as annual").
        entry = [_fee_component(kind, not_measured(reason), unit=UNIT_ONE_OFF, effective_from=None,
                                subject_to_change=True, one_off=True)]
        exit_ = [_fee_component("exit", not_measured(reason), unit=UNIT_ONE_OFF, effective_from=None,
                                subject_to_change=True, one_off=True)]
        return {"entry_price": None, "entry_fee_components": entry, "exit_fee_components": exit_,
               "redemption_delay_days": not_measured(f"{symbol}: no single cited redemption-day figure"),
               "price_is_net_of_performance_fee": None, "performance_fee_rate": None,
               "leverage": None, "maintenance_margin_rate": None, "collateral_yield_rate": None,
               "fee_source": f"registry/facts.jsonl ({symbol}: no fee fact cited)",
               "holding_period_days_declared": None, "return_origin_group": group}
    return None


#: ADR-564 decision #5 (HOLDER_ELIGIBILITY): SPA has no legal entity, KYC or investor
#: classification on record — every KYC-gated / accredited-only instrument is NOT_ELIGIBLE or
#: UNKNOWN for SPA, never assumed eligible. A scanner HINT (consumed by E1's profile.py once it
#: exists) — not yet wired into any candidate field contract.py v1 defines.
def holder_eligibility_hint(symbol: str, *, now: datetime) -> dict:
    elig = _fact("USYC" if symbol == "USYC" else symbol, "holder_eligibility", now=now)
    if symbol == "USYC":
        return {"state": "NOT_ELIGIBLE", "requirements": (elig or {}).get("value"),
               "reason": "USYC requires non-US institutional KYC + $100k minimum (cited issuer terms); "
                        "SPA has no legal entity, KYC or investor classification on record"}
    if symbol == "OUSG":
        return {"state": "NOT_ELIGIBLE",
               "requirements": {"investor_class": "qualified purchaser", "minimum_usd": 5000},
               "reason": "OUSG requires QP status + a minimum ticket (cited issuer terms); SPA has no "
                        "investor classification on record"}
    if symbol == "USDY":
        return {"state": "UNKNOWN", "requirements": {"jurisdiction": "non-US accounts (cited)"},
               "reason": "USDY redemption requires a non-US USD-wire-receiving account; SPA's own "
                        "jurisdiction/entity status for this purpose is not on record — UNKNOWN, not assumed"}
    if symbol == "BUIDL":
        return {"state": "NOT_ELIGIBLE", "requirements": {"minimum_usd": 100000, "whitelist": True},
               "reason": "BUIDL is whitelist-gated with a $100,000 minimum (cited Form D); SPA has no "
                        "whitelist/legal entity on record"}
    return {"state": "UNKNOWN", "requirements": None, "reason": f"{symbol}: no holder-eligibility fact cited"}


def _floor_rate_by_symbol(rwa_floor_doc: dict) -> dict:
    out = {}
    pools = (rwa_floor_doc or {}).get("pools")
    if not isinstance(pools, list):
        return out
    for row in pools:
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        apy = row.get("apy_pct")
        pool_id = row.get("pool")
        if isinstance(label, str) and ":" in label and isinstance(apy, (int, float)):
            sym = label.split(":", 1)[1].strip().upper()
            out[sym] = (float(apy), pool_id if isinstance(pool_id, str) else None)
    return out


def scan(data_dir, now: datetime, *, rpc_client=None, raw_pools=None) -> dict:
    """``raw_pools``: a fresh DeFiLlama pool listing carrying ``chain``/``underlyingTokens`` (e.g.
    from a collector or a live ``yields.llama.fi/pools`` fetch) — when given, it is the ONLY
    source ``CHAIN_JOIN_REQUIRED_SYMBOLS`` (the four Phase-0-audited instruments) may take a rate
    from (``instruments.join_pool_by_chain_and_contract``); ``market_data/rwa_floor.json``'s
    SYMBOL-keyed cache is never trusted for them again (ADR-564 decision #4 — a symbol join is
    forbidden), so without ``raw_pools`` those four are NOT_MEASURED rather than silently falling
    back to the old, now-known-unsafe, join."""
    data_dir = Path(data_dir)
    as_of = now.isoformat()
    board, board_err = read_json(data_dir / "rwa_safety_board.json")
    if not isinstance(board, dict) or not isinstance(board.get("assets"), list):
        return empty_result(SCANNER_NAME, DOMAIN, as_of, "UNAVAILABLE",
                            f"rwa_safety_board.json: {board_err or 'missing assets list'}")
    floor_doc, _ = read_json(data_dir / "market_data" / "rwa_floor.json")
    floor_rates = _floor_rate_by_symbol(floor_doc or {})
    # review H1/M4: floor_as_of is a genuine upstream time ONLY when the cache names one; a
    # MEASURED cell with as_of=None raises inside contract.cell() (that ValueError used to escape
    # uncaught and kill all 11 candidates) — so the rate is NOT_MEASURED, not MEASURED-with-no-time,
    # whenever the cache carries no 'generated_at'.
    floor_as_of = (floor_doc or {}).get("generated_at")
    floor_has_as_of = isinstance(floor_as_of, str)
    # review H1: board_as_of is likewise never defaulted to the scan clock — every DOCUMENTED cell
    # below that would cite it is NOT_MEASURED instead when the board itself has no 'generated_at'.
    board_as_of = board.get("generated_at")
    board_has_as_of = isinstance(board_as_of, str)

    by_symbol = {}
    if collateral_registry is not None:
        try:
            by_symbol = collateral_registry.by_symbol()
        except Exception:  # noqa: BLE001
            by_symbol = {}

    candidates, observations, counterparty, unresolved, holder_eligibility = [], {}, {}, [], {}
    for asset in board["assets"]:
        if not isinstance(asset, dict):
            continue
        symbol = str(asset.get("symbol") or "")
        if not symbol:
            unresolved.append({"name": "(unnamed)", "reason": "rwa_safety_board asset row has no symbol"})
            continue
        reg = by_symbol.get(symbol.upper())
        token_contract = getattr(reg, "token_contract", None) if reg is not None else None
        if not token_contract:
            unresolved.append({"name": symbol,
                               "reason": "no public mainnet token contract in collateral_registry.py "
                                         "(transfer-restricted / registry-only instrument — never a symbol "
                                         "fallback, ADR-560 review #2)"})
            continue

        asset_class = getattr(reg, "asset_class", None)
        mechanism_id = ASSET_CLASS_MECHANISM.get(asset_class, "RWA_CREDIT")
        # review N6: look up the exact symbol, then case-folded (fund_root does both) — a plain
        # symbol.upper()/lower() lookup misses the mixed-case keys this repo actually uses
        # (wUSDM, cUSDO, sBUIDL), silently un-deduping a wrapper from its fund.
        root = fund_root(symbol, f"fund:{symbol.lower()}")

        cells = {}
        if symbol in CHAIN_JOIN_REQUIRED_SYMBOLS:
            # ADR-564 decision #4: BUIDL/OUSG/USYC were each found mis-joined to a same-symbol pool
            # on the WRONG chain (Solana/XRPL/BSC) via exactly the symbol-keyed lookup this branch
            # replaces — rwa_floor.json's cache has no chain/underlying-contract field to join by
            # safely, so these four NEVER read from it again, raw_pools or NOT_MEASURED only.
            if raw_pools is not None:
                pool, join_reason = instruments.join_pool_by_chain_and_contract(symbol, raw_pools)
            else:
                pool, join_reason = None, (f"{symbol}: chain-correct join requires a raw DeFiLlama pool list "
                                           "(chain + underlyingTokens); the symbol-keyed rwa_floor.json cache "
                                           "is not chain-safe for this instrument (ADR-564 decision #4)")
            if pool is not None and isinstance(pool.get("apy"), (int, float)):
                cells["base_return"] = contract.cell(
                    contract.MEASURED, float(pool["apy"]), unit="pct_apy",
                    source_ref=f"yields.llama.fi/pools#{pool.get('pool')}", source_class=contract.REPUTABLE_AGGREGATOR,
                    source_root="defillama:yields", as_of=now.isoformat(), recorded_at=now.isoformat(), now=now,
                    window="spot", method="chain=Ethereum AND underlyingTokens contract match — never by symbol")
            else:
                cells["base_return"] = not_measured(join_reason or f"{symbol}: no chain-correct pool match")
        else:
            rate, floor_pool_id = floor_rates.get(symbol.upper(), (None, None))
            if rate is not None and floor_has_as_of:
                cells["base_return"] = contract.cell(contract.MEASURED, rate, unit="pct_apy",
                                                     source_ref=f"data/market_data/rwa_floor.json#{floor_pool_id}",
                                                     source_class=contract.REPUTABLE_AGGREGATOR,
                                                     source_root="defillama:yields", as_of=floor_as_of,
                                                     recorded_at=now.isoformat(), now=now, window="spot")
            elif rate is not None:
                cells["base_return"] = not_measured(f"{symbol}: rwa_floor.json has a rate but no 'generated_at' "
                                                    "timestamp to pin it to")
            else:
                cells["base_return"] = not_measured(f"no per-pool rate for {symbol} in this repo's data "
                                                    "(not one of the rwa_floor.json live-rated pools)")
        cells["incentive_return"] = not_applicable("tokenised-Treasury/MMF yield has no incentive component")
        cells["quoted_return"] = not_measured("no separately documented issuer-advertised rate beyond the "
                                              "marketing $1.00 NAV assumption")
        phase0_fee = _phase0_fee_cell(symbol, now) if symbol in CHAIN_JOIN_REQUIRED_SYMBOLS else None
        if phase0_fee is not None:
            # ADR-564 decision #3: "the repo's 0 bps figures are superseded by cited terms or by
            # NOT_MEASURED" — the board's own redemption_fee_bps=0.0 for these four is NEVER used.
            cells["fees"] = phase0_fee
        # redemption fee/delay are the ISSUER'S OWN published terms (collateral_registry.py's own
        # docstring: "we encode the issuer's PUBLISHED terms") — ISSUER_CLAIM (review H6b), and
        # only emitted when the board itself carries a genuine upstream time for them (review H1).
        elif isinstance(asset.get("redemption_fee_bps"), (int, float)) and board_has_as_of:
            # a REDEMPTION fee is ONE-OFF (charged on exit), never an annual rate — same unit
            # discipline as the Phase-0 fee cells above (never the bare, ambiguous "fraction").
            cells["fees"] = contract.cell(contract.DOCUMENTED, float(asset["redemption_fee_bps"]) / 10_000.0,
                                          unit=UNIT_ONE_OFF, source_ref="rwa_safety_board.json",
                                          source_class=contract.ISSUER_CLAIM, source_root="doc:rwa_safety_board",
                                          as_of=board_as_of, recorded_at=now.isoformat(), now=now)
        elif isinstance(asset.get("redemption_fee_bps"), (int, float)):
            cells["fees"] = not_measured("redemption_fee_bps is published but rwa_safety_board.json has no "
                                        "'generated_at' timestamp to pin it to")
        else:
            cells["fees"] = not_measured("redemption_fee_bps not published")
        cells["gas"] = not_applicable("off-chain fund; no gas leg")
        cells["hedging_cost"] = not_applicable("no hedge required for a Treasury/MMF holding")
        cells["funding"] = not_applicable("no funding leg for a Treasury/MMF holding")
        cells["duration"] = not_measured("fund duration not published in this repo's data")
        if isinstance(asset.get("redemption_delay_days"), (int, float)) and board_has_as_of:
            cells["time_to_exit"] = contract.cell(
                contract.DOCUMENTED, float(asset["redemption_delay_days"]), unit="days",
                source_ref="rwa_safety_board.json", source_class=contract.ISSUER_CLAIM,
                source_root="doc:rwa_safety_board", as_of=board_as_of, recorded_at=now.isoformat(), now=now)
        elif isinstance(asset.get("redemption_delay_days"), (int, float)):
            cells["time_to_exit"] = not_measured("redemption_delay_days is published but rwa_safety_board.json "
                                                 "has no 'generated_at' timestamp to pin it to")
        else:
            cells["time_to_exit"] = not_measured("redemption_delay_days not published")
        # exit_capacity is the board's OWN computed analysis (on-chain DEX liquidity it measured),
        # not an issuer term — SECONDARY_SOURCE (repo-curated), never ISSUER_CLAIM or AUDITED_DOCUMENT.
        if isinstance(asset.get("exit_capacity_72h_usd"), (int, float)) and board_has_as_of:
            cells["liquidity"] = contract.cell(
                contract.DOCUMENTED, float(asset["exit_capacity_72h_usd"]), unit="usd",
                source_ref="rwa_safety_board.json", source_class=contract.SECONDARY_SOURCE,
                source_root="doc:rwa_safety_board", as_of=board_as_of, recorded_at=now.isoformat(), now=now)
        elif isinstance(asset.get("exit_capacity_72h_usd"), (int, float)):
            cells["liquidity"] = not_measured("exit_capacity_72h_usd is published but rwa_safety_board.json "
                                              "has no 'generated_at' timestamp to pin it to")
        else:
            cells["liquidity"] = not_measured("exit_capacity_72h_usd not published")
        cells["capacity"] = not_measured("fund size / capacity not published per-instrument in this repo")
        cells["measured_return"] = not_applicable("pre-admission scan; no running paper account yet")
        cells["realised_return"] = not_applicable("pre-admission scan; no running paper account yet")
        cells["net_expected_return"] = contract.net_expected_return(cells)

        cand = full_candidate(
            scanner=SCANNER_NAME, mechanism_id=mechanism_id, domain=DOMAIN, network="ethereum",
            instrument=symbol, instrument_id=f"1:{token_contract.lower()}",
            venue_or_protocol=asset.get("issuer") or symbol, underlying_root=root,
            economic_driver_key="UST_BILL", yield_source="rwa_tbill" if mechanism_id == "TOKENISED_TREASURY"
            else "rwa_credit", strategy_family="rwa_stable_yield", return_window="spot", cells=cells, now=now,
        )
        candidates.append(cand)

        # review H6c: a clean on-chain NAV read is recorded ONLY here, as observations["realised_index"]
        # — it never upgrades any counterparty dimension (a share price is not a reserve-transparency
        # fact). nav_source=="onchain_4626" tells us the board considers this a GENUINE 4626 wrapper
        # worth attempting; whether the attempt actually succeeds THIS run is what idx_measured below
        # records — the counterparty call below passes neither flag any further.
        onchain_capable = asset.get("nav_source") == "onchain_4626"
        idx = onchain.realised_index(symbol, token_contract, rpc_client=rpc_client, now=now) \
            if onchain_capable else not_measured(f"{symbol}: nav_source={asset.get('nav_source')!r}, "
                                                  "not a genuine ERC-4626 wrapper per the safety board")
        idx_measured = idx.get("state") == contract.MEASURED
        if cells["base_return"]["state"] == contract.MEASURED or idx_measured:
            observations[cand["candidate_id"]] = {
                "observed_return": cells["base_return"], "realised_index": idx if idx_measured else None,
                "period": now.date().isoformat(),
            }

        counterparty[cand["candidate_id"]] = counterparty_registry.tokenised_treasury(
            symbol, asset.get("issuer"), source_ref="rwa_safety_board.json", mechanism_id=mechanism_id,
            redemption_documented=bool(asset.get("redemption_documented")) and board_has_as_of,
            redemption_delay_days=asset.get("redemption_delay_days"),
            redemption_fee_bps=asset.get("redemption_fee_bps"),
            transfer_restricted=asset.get("transfer_restricted"),
            as_of=board_as_of if board_has_as_of else None,
        )
        if symbol in CHAIN_JOIN_REQUIRED_SYMBOLS:
            holder_eligibility[cand["candidate_id"]] = holder_eligibility_hint(symbol, now=now)
            # ADR-564 integration (2026-10-04): a scanner hint in evidence_contract's frozen
            # PAPER_ACCOUNTING_EVIDENCE_FIELDS/FEE_COMPONENT shape, copied into the bundle by E1.
            cand["paper_accounting_hints"] = paper_accounting_hints(symbol, now)

    status = "OK" if board_err is None else "PARTIAL"
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status,
        "reason": board_err,
        "denominators": {"scanned": len(board["assets"]), "discovered": len(candidates), "truncated": None},
        "candidates": candidates, "unresolved": unresolved, "observations": observations,
        "counterparty": counterparty, "existing_book_roots": [], "holder_eligibility": holder_eligibility,
    }
