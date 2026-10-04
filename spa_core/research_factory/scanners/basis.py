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

from spa_core.research_factory import contract, counterparty_registry, onchain
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


def scan(data_dir, now: datetime, *, rpc_client=None) -> dict:
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

    eth_cand = _funding_capture_candidate("ETH", eth_doc or {}, now)
    candidates.append(eth_cand)
    counterparty[eth_cand["candidate_id"]] = counterparty_registry.funding_capture()
    if eth_cand["funding"]["state"] == contract.MEASURED:
        observations[eth_cand["candidate_id"]] = {"observed_return": eth_cand["funding"], "realised_index": None,
                                                   "period": now.date().isoformat()}

    btc_cand = _funding_capture_candidate("BTC", btc_doc or {}, now)
    candidates.append(btc_cand)
    counterparty[btc_cand["candidate_id"]] = counterparty_registry.funding_capture()
    if btc_cand["funding"]["state"] == contract.MEASURED:
        observations[btc_cand["candidate_id"]] = {"observed_return": btc_cand["funding"], "realised_index": None,
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
