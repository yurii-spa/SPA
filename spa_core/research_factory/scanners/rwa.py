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

from datetime import datetime
from pathlib import Path

from spa_core.research_factory import contract, counterparty_registry, onchain
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


def scan(data_dir, now: datetime, *, rpc_client=None) -> dict:
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

    candidates, observations, counterparty, unresolved = [], {}, {}, []
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

        rate, floor_pool_id = floor_rates.get(symbol.upper(), (None, None))
        cells = {}
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
        # redemption fee/delay are the ISSUER'S OWN published terms (collateral_registry.py's own
        # docstring: "we encode the issuer's PUBLISHED terms") — ISSUER_CLAIM (review H6b), and
        # only emitted when the board itself carries a genuine upstream time for them (review H1).
        if isinstance(asset.get("redemption_fee_bps"), (int, float)) and board_has_as_of:
            cells["fees"] = contract.cell(contract.DOCUMENTED, float(asset["redemption_fee_bps"]) / 10_000.0,
                                          unit="fraction", source_ref="rwa_safety_board.json",
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

    status = "OK" if board_err is None else "PARTIAL"
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status,
        "reason": board_err,
        "denominators": {"scanned": len(board["assets"]), "discovered": len(candidates), "truncated": None},
        "candidates": candidates, "unresolved": unresolved, "observations": observations,
        "counterparty": counterparty, "existing_book_roots": [],
    }
