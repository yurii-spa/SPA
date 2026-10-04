"""spa_core/research_factory/scanners/basis.py — MARKET_NEUTRAL / basis track (ADR-560 WP-S03).

Three sources, zero new engines (the ADR is explicit: "No new engine"):

* FUNDING_CAPTURE (ETH, BTC) — ``data/market_data/funding.json`` / ``btc_funding.json``, the ONE
  canonical 5-venue median funding feed (``strategy_lab/data/funding_feed.py``). Per-venue values
  are never persisted, so the honest ``source_root`` is ``venue:median5`` — a median of whichever
  venues answered that day, NOT a cross-venue quorum/agreement check (stated in the cell's own
  ``reason``, never silently implied). A negative funding value is real and is never clamped.
* DELTA_NEUTRAL_CARRY (sUSDe) — the live DeFiLlama-relayed sUSDe rate in ``adapter_status.json``
  (the ``"susde"`` block — NOT the stale, static ``"ethena_susde"`` legacy block). Funding is
  ``embedded_in_return=True`` (Ethena's own yield already blends funding + staking — adding it
  again would double-count, review #6). The pre-existing ``aggressive_lab/susde_dn`` forward
  series is carried as a named, NON-forward fact: its rows from 2026-07-05 onward are frozen
  replays (Phase 0 audit), so this scanner marks the value ``ESTIMATED_WITH_METHOD`` /
  ``source_class=MODELLED`` and says so in the method string — it is never offered as MEASURED
  forward evidence, the exact failure mode review #5 names by this series.
``variant_n`` (LRT + short-ETH-perp paper) is deliberately NOT emitted here (post-implementation
review, LOW item): it is an engine-owned strategy_lab paper strategy, not a capital-opportunity
candidate for this factory's own lifecycle to admit.

LLM_FORBIDDEN, stdlib only, no network of its own.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from spa_core.research_factory import contract, counterparty_registry, evidence_contract, onchain
from spa_core.research_factory.scanners._common import (empty_result, full_candidate, not_applicable,
                                                          not_measured, read_json)

SCANNER_NAME = "basis"
DOMAIN = "MARKET_NEUTRAL_BASIS"

SETTLEMENTS_PER_DAY = 3.0
DAYS_PER_YEAR = 365.0
ANNUALISE_METHOD = (f"median 8h funding rate (strategy_lab/data/funding_feed.py, up to 5 venues) "
                    f"× {SETTLEMENTS_PER_DAY:.0f} settlements/day × {DAYS_PER_YEAR:.0f} days; annualised; "
                    "sign preserved, never clamped")
QUORUM_CAVEAT = ("value is the median of however many of the 5 venues answered that day — this is "
                 "NOT a cross-venue quorum/agreement check; a day with one venue reporting still "
                 "produces a median of one")


def _funding_as_of(latest_date: str, generated_at: "str | None", now: datetime) -> str:
    """review N5: the latest series DATE is the true upstream settlement day, but stamping it at
    ``T00:00:00`` undercounts freshness within that same day — the feed writes around 09:10 UTC,
    and against the 12h funding freshness window a plain midnight anchor is "fresh" only from
    00:00 to 12:00 UTC, even though the settlements it reports run all the way through the day.

    ``as_of`` is therefore ``min(generated_at, end of latest_date 23:59:59Z, now)``:

    * capped at ``generated_at`` — we can never honestly claim to know more than we have actually
      fetched (this is what keeps a FROZEN upstream day from borrowing today's fetch time, the
      exact ``susde_dn`` failure mode review #5 names: review H1's reason this scanner does not
      simply trust ``generated_at`` on its own);
    * capped at the end of the settlement day itself — a date's data is never "complete" before
      its own day ends, so we never claim a time later than that EITHER;
    * capped at ``now`` defensively, so a bogus future ``generated_at`` can never make
      ``contract.cell()`` raise on "as_of is in the future" (H0's discipline, applied here).

    In the ordinary case (fetched the same day the series last reports, which is every normal
    day) this simply resolves to ``generated_at`` itself — honestly fresher than midnight,
    never later than the fetch that produced it.
    """
    day_end = contract.parse_ts(f"{latest_date}T23:59:59+00:00")
    candidates = [now]
    if day_end is not None:
        candidates.append(day_end)
    gen_dt = contract.parse_ts(generated_at) if isinstance(generated_at, str) else None
    if gen_dt is not None:
        candidates.append(gen_dt)
    return min(candidates).isoformat()


def _funding_cell(doc: dict, asset: str, now: datetime) -> dict:
    """``as_of`` is capped at the latest SERIES DATE's own day (never later, review N5) and never
    later than the file's ``generated_at`` or the scan clock — see :func:`_funding_as_of`. This is
    never a silent stand-in for "now": a frozen upstream day still caps at that day's end even
    when ``generated_at`` keeps advancing (review H1), and a fresh same-day fetch is credited up
    to its own fetch time rather than an artificial midnight floor (review N5). ``period_countable()``
    needs exactly this upstream time to ever let a funding observation count as forward evidence
    (its ``source_class`` is PRIMARY_VENUE, in ``PRIMARY_CLASSES``)."""
    series = (doc or {}).get("series")
    if not isinstance(series, dict) or not series:
        return not_measured(f"market_data funding series empty/missing for {asset}")
    latest_date = max(series.keys())
    rate_8h = series[latest_date]
    if not isinstance(rate_8h, (int, float)):
        return not_measured(f"latest {asset} funding value is not numeric")
    annual_pct = float(rate_8h) * SETTLEMENTS_PER_DAY * DAYS_PER_YEAR * 100.0
    as_of = _funding_as_of(latest_date, (doc or {}).get("generated_at"), now)
    return contract.cell(contract.MEASURED, round(annual_pct, 10), unit="pct_apy_annualised",
                         source_ref=f"data/market_data/{'funding' if asset == 'ETH' else 'btc_funding'}.json"
                                    f"#{latest_date}",
                         source_class=contract.PRIMARY_VENUE, source_root="venue:median5", as_of=as_of,
                         recorded_at=now.isoformat(), now=now, method=ANNUALISE_METHOD, reason=QUORUM_CAVEAT,
                         window="since_admission")


#: ADR-564 binding #8: official fee sources only (KuCoin's contracts API, Hyperliquid's own fee
#: docs); every other venue has no verified fee source in this repo's citation seed and stays
#: NOT_MEASURED — never a guessed/typical figure.
#: H2 (post-implementation review, 2026-10-04): a ONE-OFF cost (a per-trade taker fee) declares
#: this unit explicitly — never the bare, ambiguous "fraction" `contract.ANNUAL_RATE_UNITS` would
#: treat as a recurring annual rate (the exact shape of a separate, already-fixed live defect in
#: scanners/rwa.py — ``rwa.UNIT_ONE_OFF``, redeclared here rather than imported so this module
#: does not depend on rwa.py for a plain string constant).
UNIT_ONE_OFF = "fraction_one_off"
PERP_TAKER_FEE = {"kucoin": 0.0006, "hyperliquid": 0.00045}
#: (origin, source_class, ref, effective_from) — effective_from is the citation's OWN retrieval
#: date (registry/facts.jsonl's retrieved_at, 2026-10-04), never the scan clock (review H1's
#: discipline, applied to a curated fact instead of a live cache).
PERP_TAKER_FEE_SOURCE = {
    "kucoin": ("venue:kucoin", contract.OFFICIAL_API, "api-futures.kucoin.com/api/v1/contracts/<symbol> "
              "takerFeeRate", "2026-10-04"),
    "hyperliquid": ("venue:hyperliquid", contract.OFFICIAL_API,
                    "hyperliquid.gitbook.io/hyperliquid-docs/trading/fees (venue-published fee schedule)",
                    "2026-10-04"),
}
#: ADR-564 decision #6: funding capture is one candidate PER (perp venue, spot venue) pair; all
#: pairs of one asset share this family tag (recorded on ``underlying_root`` — contract.py v1 has
#: no dedicated ``exposure_family`` field; that lives on the v2 evidence bundle, package E1).
FUNDING_FAMILY_ROOT = "perp:{asset}:family"
SPOT_LEG_VENUES = ("binance", "bybit", "okx", "kucoin")      # Hyperliquid has no native spot market
PERP_LEG_VENUES = ("binance", "bybit", "okx", "kucoin", "hyperliquid")


def _settlement_rows(funding_rows: list, asset: str, venue: str) -> list:
    claim = f"funding_settlement:{asset}"
    return [r for r in (funding_rows or []) if r.get("claim") == claim and r.get("origin") == f"venue:{venue}"
           and r.get("state") == contract.MEASURED]


def _latest_settlement_cell(rows: list, now: datetime) -> dict:
    if not rows:
        return not_measured("no persisted settlement rows for this venue (never a fabricated median)")
    latest = max(rows, key=lambda r: r.get("upstream_ts") or "")
    as_of = latest.get("upstream_ts")
    if not isinstance(as_of, str) or contract.parse_ts(as_of) is None:
        return not_measured("latest settlement row has no parseable upstream_ts")
    annual_pct = float(latest["value"]) * 3.0 * 365.0 * 100.0   # review N5 style annualisation; sign preserved
    return contract.cell(contract.MEASURED, round(annual_pct, 10), unit="pct_apy_annualised",
                         source_ref=latest.get("ref"), source_class=contract.PRIMARY_VENUE,
                         source_root=f"venue:{latest.get('origin', '').removeprefix('venue:')}", as_of=as_of,
                         recorded_at=now.isoformat(), now=now, window="since_admission", n=len(rows),
                         method="per-venue settlement rate × 3 settlements/day × 365, annualised; sign preserved, "
                                "never clamped (ADR-564 binding #8 — never the 5-venue median)")


def _book_entry_cell(book_rows: list, asset: str, venue: str, claim_prefix: str, now: datetime) -> dict:
    row = next((r for r in (book_rows or []) if r.get("claim") == f"{claim_prefix}:{asset}"
               and r.get("origin") == f"venue:{venue}"), None)
    if row is None or row.get("state") != contract.MEASURED:
        return not_measured(f"no {claim_prefix} book-walk evidence for {venue}/{asset} — "
                            "a delta-neutral pair needs entry evidence for BOTH legs (ADR-564 decision #6)")
    return contract.cell(contract.MEASURED, row.get("value"), unit=row.get("unit"), source_ref=row.get("ref"),
                         source_class=contract.PRIMARY_VENUE, source_root=f"venue:{venue}",
                         as_of=row.get("upstream_ts") or now.isoformat(), recorded_at=now.isoformat(), now=now,
                         reason=row.get("reason"))


def _slippage_cost_cell(book_rows: list, asset: str, spot_venue: str, now: datetime) -> dict:
    """H2 (post-implementation review, 2026-10-04): the hedge leg's COST is the SLIPPAGE of the
    spot book-walk fill away from the top-of-book mid, in bps (``collectors.books``'
    ``spot_slippage_bps:{asset}`` claim) — never the fill PRICE itself (the live defect: a MEASURED
    ``2701.78`` priced cell, unit ``avg_price_usd_for_10000_usd_notional``, sitting in a COST
    field)."""
    row = next((r for r in (book_rows or []) if r.get("claim") == f"spot_slippage_bps:{asset}"
               and r.get("origin") == f"venue:{spot_venue}"), None)
    if row is None or row.get("state") != contract.MEASURED:
        return not_measured(f"no spot_slippage_bps evidence for {spot_venue}/{asset} — a delta-neutral "
                            "pair needs entry evidence for BOTH legs (ADR-564 decision #6)")
    return contract.cell(contract.MEASURED, row.get("value"), unit="bps", source_ref=row.get("ref"),
                         source_class=contract.PRIMARY_VENUE, source_root=f"venue:{spot_venue}",
                         as_of=now.isoformat(), recorded_at=now.isoformat(), now=now, reason=row.get("reason"))


def _taker_fee_component(kind: str, venue: str, now: datetime, *, is_spot: bool) -> dict:
    """H2: every fee component carries an EXPLICIT one-off unit — never the bare, ambiguous
    "fraction" that let a one-off cost be mistaken for an annual rate elsewhere in this package.
    Perp taker fees are cited for KuCoin/Hyperliquid only (``PERP_TAKER_FEE``); no spot taker fee
    is cited for ANY venue in this repo's citation seed — a leg with no official fee source gets
    an explicit NOT_MEASURED component, never a guessed/typical figure, so COST can never grade
    ADEQUATE for that leg."""
    if is_spot:
        cell = not_measured(f"{venue}: no official spot taker-fee source cited in this repo's citation "
                            "seed — COST UNKNOWN for the spot leg, never a guessed figure")
        effective_from = None
    else:
        fee_val = PERP_TAKER_FEE.get(venue)
        if fee_val is None:
            cell = not_measured(f"{venue}: no official taker-fee source in this repo's citation seed — "
                                "COST UNKNOWN, never a guessed figure (ADR-564 binding #8)")
            effective_from = None
        else:
            origin, source_class, ref, effective_from = PERP_TAKER_FEE_SOURCE[venue]
            cell = contract.cell(contract.DOCUMENTED, fee_val, unit=UNIT_ONE_OFF, source_ref=ref,
                                 source_class=source_class, source_root=f"venue:{venue}", as_of=effective_from,
                                 recorded_at=now.isoformat(), now=now,
                                 method=f"{venue} taker fee — ONE-OFF per trade, never an annual rate")
    return {"kind": kind, "cell": cell, "unit": UNIT_ONE_OFF, "effective_from": effective_from,
           "subject_to_change": is_spot, "one_off": True}


def funding_pair_paper_accounting_hints(perp_venue: str, spot_venue: str, now: datetime) -> dict:
    """``evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS`` shape, PER LEG (paper.py's own
    docstring: "two-leg (funding-pair) candidates replace the block above with:
    `legs`: {`perp`: {...}, `spot`: {...}}") — H2's frozen shape for E1's ``grade_cost``, which
    needs BOTH legs' fee components (a leg with no cited fee source has NOT_MEASURED components,
    so COST cannot grade ADEQUATE on that leg alone)."""
    perp_leg = {
        "entry_price": None,
        "entry_fee_components": [_taker_fee_component("entry", perp_venue, now, is_spot=False)],
        "exit_fee_components": [_taker_fee_component("exit", perp_venue, now, is_spot=False)],
        "redemption_delay_days": not_applicable("CEX perp leg; no redemption concept"),
        "price_is_net_of_performance_fee": None, "performance_fee_rate": None,
        "leverage": not_measured(f"{perp_venue}: margin requirement not measured — no venue "
                                 "margin-schedule client"),
        "maintenance_margin_rate": not_measured(f"{perp_venue}: maintenance margin not measured"),
        "collateral_yield_rate": None,
        "fee_source": (PERP_TAKER_FEE_SOURCE[perp_venue][2] if perp_venue in PERP_TAKER_FEE_SOURCE
                      else f"no official taker-fee source cited for {perp_venue}"),
        "holding_period_days_declared": None, "return_origin_group": f"venue:{perp_venue}",
    }
    spot_leg = {
        "entry_price": None,
        "entry_fee_components": [_taker_fee_component("entry", spot_venue, now, is_spot=True)],
        "exit_fee_components": [_taker_fee_component("exit", spot_venue, now, is_spot=True)],
        "redemption_delay_days": not_applicable("CEX spot leg; no redemption concept"),
        "price_is_net_of_performance_fee": None, "performance_fee_rate": None,
        "leverage": not_applicable("spot leg; unlevered hedge"),
        "maintenance_margin_rate": not_applicable("spot leg; unlevered hedge"),
        "collateral_yield_rate": None,
        "fee_source": f"no official spot taker-fee source cited for {spot_venue} in this repo's citation seed",
        "holding_period_days_declared": None, "return_origin_group": f"venue:{spot_venue}",
    }
    return {"legs": {"perp": perp_leg, "spot": spot_leg}}


def funding_pair_candidates(asset: str, funding_rows: list, book_rows: list, now: datetime) -> list:
    """One candidate per (perp venue × spot venue) PAIR for ``asset`` (ADR-564 decision #6) — the
    fix for the single cross-venue ``median5`` candidate: every venue's own persisted settlement
    rows stand on their own, dispersion stays visible, and a pair is never admitted on
    manufactured hedge-leg evidence."""
    out = []
    family_root = FUNDING_FAMILY_ROOT.format(asset=asset)
    for perp_venue in PERP_LEG_VENUES:
        settlement_rows = _settlement_rows(funding_rows, asset, perp_venue)
        for spot_venue in SPOT_LEG_VENUES:
            # evidence_contract.FUNDING_PAIR_ID ("perp:{asset}:{perp_venue}+spot:{spot_venue}") is
            # the DISPLAY label (and the v2 bundle's id, once E1's bundle.py exists) — it does not
            # fit contract.py v1's frozen INSTRUMENT_ID_RE (no "+", single venue token), so the v1
            # instrument_id used for exposure_key()/candidate_id is a concatenated form instead.
            pair_label = evidence_contract.FUNDING_PAIR_ID.format(asset=asset, perp_venue=perp_venue,
                                                                   spot_venue=spot_venue)
            instrument_id = f"perp:{asset}:{perp_venue}{spot_venue}"
            cells = {
                "base_return": not_applicable("FUNDING_CAPTURE has no base/deposit-yield leg"),
                "funding": _latest_settlement_cell(settlement_rows, now),
                "incentive_return": not_applicable("no incentive/reward component for a perp funding leg"),
                "quoted_return": not_applicable("no issuer-advertised rate for a perp funding leg"),
                # H2: no leg has a recurring ANNUAL fee — entry/exit taker fees are ONE-OFF (see
                # paper_accounting_hints.legs); the v1 single cell is never fed a one-off cost again.
                "fees": not_applicable("FUNDING_CAPTURE's taker fees are ONE-OFF per leg, never an annual "
                                       "rate — see paper_accounting_hints.legs.{perp,spot}.*_fee_components"),
                "gas": not_applicable("CEX perp leg; no on-chain gas"),
                # H2: a COST in bps (slippage), never the fill PRICE a prior version stored here.
                "hedging_cost": _slippage_cost_cell(book_rows, asset, spot_venue, now),
                "duration": not_applicable("perpetual position; no fixed maturity"),
                "liquidity": _book_entry_cell(book_rows, asset, perp_venue, "perp_mark", now),
                "time_to_exit": not_measured("time to flatten a perp position not measured"),
                "capacity": not_measured("venue capacity not measured"),
                "measured_return": not_applicable("pre-admission scan; no running paper account yet"),
                "realised_return": not_applicable("pre-admission scan; no running paper account yet"),
                "leverage": not_measured("margin requirement not measured — no venue margin-schedule client"),
                "liquidation_distance": not_measured("no margin/liquidation-price client for this leg"),
            }
            cells["net_expected_return"] = contract.net_expected_return(cells)
            cand = full_candidate(
                scanner=SCANNER_NAME, mechanism_id="FUNDING_CAPTURE", domain=DOMAIN, network="cex",
                instrument=f"{asset} perp funding: {perp_venue} perp / {spot_venue} spot ({pair_label})",
                instrument_id=instrument_id, venue_or_protocol=f"{perp_venue}+{spot_venue}",
                underlying_root=family_root, economic_driver_key=f"{asset}_PERP_FUNDING",
                yield_source="delta_neutral", strategy_family="basis", return_window="since_admission",
                cells=cells, now=now,
            )
            cand["paper_accounting_hints"] = funding_pair_paper_accounting_hints(perp_venue, spot_venue, now)
            out.append(cand)
    return out


def _funding_capture_candidate(asset: str, doc: dict, now: datetime) -> dict:
    cells = {
        "base_return": not_applicable("FUNDING_CAPTURE has no base/deposit-yield leg"),
        "funding": _funding_cell(doc, asset, now),
        "incentive_return": not_applicable("no incentive/reward component for a perp funding leg"),
        "quoted_return": not_applicable("no issuer-advertised rate for a perp funding leg"),
        "fees": not_measured("perp execution/taker fee not measured — no per-venue fee client"),
        "gas": not_applicable("CEX perp leg; no on-chain gas"),
        "hedging_cost": not_measured("spot-perp basis leg / hedging cost not measured — no paired spot price feed"),
        "duration": not_applicable("perpetual position; no fixed maturity"),
        "liquidity": not_measured("venue order-book depth not measured"),
        "time_to_exit": not_measured("time to flatten a perp position not measured"),
        "capacity": not_measured("venue capacity not measured"),
        "measured_return": not_applicable("pre-admission scan; no running paper account yet"),
        "realised_return": not_applicable("pre-admission scan; no running paper account yet"),
        "leverage": not_measured("margin requirement not measured — no venue margin-schedule client"),
        "liquidation_distance": not_measured("no margin/liquidation-price client for this leg"),
    }
    cells["net_expected_return"] = contract.net_expected_return(cells)
    instrument_id = f"perp:{asset}:median5"
    cand = full_candidate(
        scanner=SCANNER_NAME, mechanism_id="FUNDING_CAPTURE", domain=DOMAIN, network="cex",
        instrument=f"{asset} perp funding (5-venue median)", instrument_id=instrument_id,
        venue_or_protocol="Binance/Bybit/OKX/KuCoin/Hyperliquid (median)", underlying_root=instrument_id,
        economic_driver_key=f"{asset}_PERP_FUNDING", yield_source="delta_neutral",
        strategy_family="basis", return_window="since_admission", cells=cells, now=now,
    )
    return cand


def _susde_candidate(adapter_status: dict, susde_dn_last: "dict | None", now: datetime) -> "tuple[dict, dict] | None":
    adapters = (adapter_status or {}).get("adapters")
    block = adapters.get("susde") if isinstance(adapters, dict) else None
    if not isinstance(block, dict):
        return None
    cells = {}
    rate, as_of, fresh = block.get("live_apy"), block.get("live_apy_as_of"), block.get("live_apy_fresh")
    if isinstance(rate, (int, float)) and isinstance(as_of, str) and fresh:
        cells["base_return"] = contract.cell(contract.MEASURED, float(rate), unit="pct_apy",
                                             source_ref="data/adapter_status.json#adapters.susde",
                                             source_class=contract.REPUTABLE_AGGREGATOR,
                                             source_root="defillama:yields", as_of=as_of,
                                             recorded_at=now.isoformat(), now=now, window="spot")
    else:
        cells["base_return"] = not_measured("adapter_status.json 'susde' block has no fresh live_apy")
    # review M3 (invariant #17): funding is NOT split out of sUSDe's blended DeFiLlama rate
    # anywhere in this repo — that is an ABSENT observation, not an observed zero, and must say so
    # as NOT_MEASURED rather than a fabricated MEASURED 0.0. embedded_in_return=True still matters
    # on a NOT_MEASURED cell: contract.net_expected_return()'s cost/funding loop skips a field the
    # moment embedded_in_return is True, regardless of its state, so this unsplit funding leg never
    # blocks the net-return computation as a "missing cost" (review #6).
    cells["funding"] = contract.cell(
        contract.NOT_MEASURED, embedded_in_return=True,
        reason="funding is already blended into the DeFiLlama-relayed sUSDe rate (Ethena's own design) "
               "and this repo has no separately split funding component for sUSDe — NOT_MEASURED, never "
               "a fabricated 0.0 (invariant #17); embedded_in_return=True so net_expected_return() does "
               "not treat the unsplit leg as a missing cost (review #6)")
    cells["incentive_return"] = (contract.cell(contract.MEASURED, float(block["apy_reward"]), unit="pct_apy",
                                               source_ref="data/adapter_status.json#adapters.susde",
                                               source_class=contract.REPUTABLE_AGGREGATOR,
                                               source_root="defillama:yields", as_of=as_of, recorded_at=now.isoformat(), now=now)
                                 if isinstance(block.get("apy_reward"), (int, float)) else
                                 not_measured("apy_reward not published for susde"))
    cells["quoted_return"] = not_measured("no issuer-advertised rate distinct from the DeFiLlama-relayed reading")
    cells["fees"] = not_applicable("no explicit fee leg beyond the embedded funding blend")
    cells["gas"] = not_measured("mint/redeem gas cost not measured")
    cells["hedging_cost"] = not_applicable("hedge is internal to Ethena's design; not a separate paper cost here")
    cells["duration"] = not_applicable("floating rate; no fixed maturity")
    cells["liquidity"] = not_measured("exit liquidity not separately measured")
    cells["time_to_exit"] = not_measured("redemption/cooldown timeline not read from this repo's adapter data")
    cells["capacity"] = (contract.cell(contract.MEASURED, float(block["tvl_usd"]), unit="usd",
                                       source_ref="data/adapter_status.json#adapters.susde",
                                       source_class=contract.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                       as_of=as_of, recorded_at=now.isoformat(), now=now)
                        if isinstance(block.get("tvl_usd"), (int, float)) and block.get("tvl_source") == "live"
                        else not_measured("tvl_usd not live-sourced for susde"))
    if susde_dn_last is not None and isinstance(susde_dn_last.get("net_apy_pct"), (int, float)):
        cells["realised_return"] = contract.cell(
            contract.ESTIMATED_WITH_METHOD, float(susde_dn_last["net_apy_pct"]), unit="pct_apy",
            source_ref="data/aggressive_lab/susde_dn/realized_series.jsonl",
            source_class=contract.MODELLED, as_of=susde_dn_last.get("as_of"), recorded_at=now.isoformat(), now=now,
            method="aggressive_lab/susde_dn realized_series.jsonl net_apy_pct — KNOWN DEFECT (ADR-560 Phase 0 "
                   "audit): forward rows from 2026-07-05 onward are FROZEN REPLAYS (60/61 identical), funding "
                   "is counted twice and there is no ETH-leg P&L in this series; recorded for continuity ONLY "
                   "and NEVER counted as forward evidence")
    else:
        cells["realised_return"] = not_applicable("aggressive_lab/susde_dn/realized_series.jsonl unavailable")
    cells["measured_return"] = not_applicable("pre-admission scan; no running paper account yet")
    cells["net_expected_return"] = contract.net_expected_return(cells)

    address = onchain.SUSDE_ADDRESS
    cand = full_candidate(
        scanner=SCANNER_NAME, mechanism_id="DELTA_NEUTRAL_CARRY", domain=DOMAIN, network="ethereum",
        instrument="sUSDe", instrument_id=f"1:{address.lower()}", venue_or_protocol="Ethena Labs",
        underlying_root="fund:ethena-susde", economic_driver_key="ETHENA_FUNDING_STAKING",
        yield_source="staked_synthetic", strategy_family="basis", return_window="spot", cells=cells, now=now,
    )
    return cand, cells


#: post-implementation review, LOW item: variant_n is an engine-owned strategy (strategy_lab's own
#: paper book), not a capital-opportunity candidate this factory should admit through its own
#: lifecycle — it is intentionally NOT projected as a candidate here (it was, before this review;
#: dropped rather than fixed, since nothing downstream reads it — see the ADR's "OBSERVE-level
#: fact for the CIO relabel" framing, which belongs to the CIO's own relabelling work, not to a
#: Package-B scanner inventing a basis-track candidate for an engine it does not own).


def scan(data_dir, now: datetime, *, rpc_client=None, funding_rows=None, book_rows=None) -> dict:
    """``funding_rows``/``book_rows``: pre-collected ``collectors.funding_venues``/``collectors.books``
    observation rows (ADR-564 decision #6) — when given, this scan also emits one PAIR candidate
    per (perp venue × spot venue) per asset (``funding_pair_candidates``) and marks the legacy
    5-venue-median candidate ``superseded_by`` the pair family; a caller that does not have
    collected rows yet still gets the (now-superseded) median candidate unchanged, never a crash."""
    data_dir = Path(data_dir)
    as_of = now.isoformat()

    eth_doc, eth_err = read_json(data_dir / "market_data" / "funding.json")
    btc_doc, btc_err = read_json(data_dir / "market_data" / "btc_funding.json")
    adapter_status, status_err = read_json(data_dir / "adapter_status.json")
    susde_dn_last = None
    susde_dn_path = data_dir / "aggressive_lab" / "susde_dn" / "realized_series.jsonl"
    try:
        with open(susde_dn_path, encoding="utf-8") as fh:
            last_line = None
            for line in fh:
                line = line.strip()
                if line:
                    last_line = line
            if last_line:
                susde_dn_last = json.loads(last_line)
    except FileNotFoundError:
        susde_dn_last = None
    except Exception:  # noqa: BLE001 — a malformed tail line is simply "no reading"
        susde_dn_last = None

    if eth_doc is None and btc_doc is None and adapter_status is None:
        reason = f"funding.json: {eth_err}; btc_funding.json: {btc_err}; adapter_status.json: {status_err}"
        return empty_result(SCANNER_NAME, DOMAIN, as_of, "UNAVAILABLE", reason)

    candidates, observations, counterparty = [], {}, {}

    for asset, doc in (("ETH", eth_doc or {}), ("BTC", btc_doc or {})):
        legacy_cand = _funding_capture_candidate(asset, doc, now)
        if funding_rows is not None or book_rows is not None:
            # ADR-564 decision #6: the 5-venue median is a display aggregate only, superseded by
            # the per-venue-pair family; it is never removed outright (continuity for anything
            # still reading the old instrument id), only labelled.
            legacy_cand["superseded_by"] = FUNDING_FAMILY_ROOT.format(asset=asset)
        candidates.append(legacy_cand)
        counterparty[legacy_cand["candidate_id"]] = counterparty_registry.funding_capture()
        if legacy_cand["funding"]["state"] == contract.MEASURED:
            observations[legacy_cand["candidate_id"]] = {"observed_return": legacy_cand["funding"],
                                                          "realised_index": None, "period": now.date().isoformat()}
        if funding_rows is not None or book_rows is not None:
            for pair_cand in funding_pair_candidates(asset, funding_rows or [], book_rows or [], now):
                candidates.append(pair_cand)
                counterparty[pair_cand["candidate_id"]] = counterparty_registry.funding_capture()
                if pair_cand["funding"]["state"] == contract.MEASURED:
                    observations[pair_cand["candidate_id"]] = {"observed_return": pair_cand["funding"],
                                                               "realised_index": None,
                                                               "period": now.date().isoformat()}

    susde_result = _susde_candidate(adapter_status or {}, susde_dn_last, now)
    if susde_result is not None:
        susde_cand, susde_cells = susde_result
        candidates.append(susde_cand)
        counterparty[susde_cand["candidate_id"]] = counterparty_registry.delta_neutral_carry_susde()
        idx = onchain.realised_index("sUSDe", onchain.SUSDE_ADDRESS, rpc_client=rpc_client, now=now)
        if susde_cells["base_return"]["state"] == contract.MEASURED or idx.get("state") == contract.MEASURED:
            observations[susde_cand["candidate_id"]] = {
                "observed_return": susde_cells["base_return"],
                "realised_index": idx if idx.get("state") == contract.MEASURED else None,
                "period": now.date().isoformat(),
            }

    ok = eth_doc is not None and btc_doc is not None and adapter_status is not None
    status = "OK" if ok else "PARTIAL"
    reason = None if ok else "one or more inputs unavailable (see denominators/candidates for what was read)"
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status, "reason": reason,
        "denominators": {"scanned": None, "discovered": len(candidates), "truncated": None},
        "candidates": candidates, "unresolved": [], "observations": observations,
        "counterparty": counterparty, "existing_book_roots": [],
    }
