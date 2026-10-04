"""spa_core/research_factory/scanners/cash_treasury.py — CASH_TREASURY track (ADR-560 WP-S02).

Two mechanisms, both reusing artifacts a live agent already writes — no new network client:

* STABLECOIN_SAVINGS — sUSDS and sDAI, read from ``data/adapter_status.json`` (the same file the
  money-path cycle reads) and, for sUSDS, the GSM pause-delay reading in ``data/sky_status.json``.
* TOKENISED_TREASURY — the per-pool rows in ``data/market_data/rwa_floor.json`` (the rwa_feed
  cache) for the funds ``rwa.py`` does NOT already cover (post-implementation review M1: one
  track per fund — a tokenised T-bill fund that ``rwa_safety_board.json`` names is owned
  EXCLUSIVELY by ``rwa.py``; this scanner only emits a rwa_floor.json pool whose symbol is outside
  that 11-asset board, e.g. Invesco USTB / Bitwise USCC / OpenEden TBILL). This file has PER-POOL
  rows (label/apy_pct/tvl_usd/pool uuid); the TVL-weighted *aggregate* blended rate at the top of
  that file is never assigned to an instrument — only a per-pool value is (review #15).
  (Deliberately not named here by its literal field key — a static test asserts this module's
  source never reads it at all.)

Post-implementation review H1: no cell's ``as_of`` ever defaults to the scan clock. A missing
upstream timestamp (``generated_at`` absent from either input file) makes the dependent cells
NOT_MEASURED, named as such — never a silent stand-in for "now".

LLM_FORBIDDEN, stdlib only, no network (``rpc_client`` is accepted only to pass through to
``onchain.realised_index`` for the two savings vaults; this module makes no call itself).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract, counterparty_registry, onchain
from spa_core.research_factory.scanners._common import (empty_result, full_candidate, not_applicable,
                                                          not_measured, read_json)

try:
    from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter
    from spa_core.adapters.sdai_adapter import SdaiAdapter
except Exception:  # noqa: BLE001 — the adapter module is pure config/logic; absence is a named outcome
    SparkSusdsAdapter = SdaiAdapter = None

SCANNER_NAME = "cash_treasury"
DOMAIN = "CASH_TREASURY"

#: shared across scanners (cash_treasury / rwa / discovery all import THIS table — one root per
#: fund, keyed by symbol, review M1): no false merges like "fund:ondo-yield-assets" — OUSG and
#: USDY are two DIFFERENT Ondo funds sharing one DeFiLlama *project* slug, never one root.
FUND_ROOTS = {
    "BUIDL": "fund:blackrock-buidl", "sBUIDL": "fund:blackrock-buidl",
    "USYC": "fund:circle-usyc",
    "OUSG": "fund:ondo-ousg",
    "USDY": "fund:ondo-usdy",
    "USDM": "fund:mountain-usdm", "wUSDM": "fund:mountain-usdm",
    "cUSDO": "fund:openeden-usdo",
    "VBILL": "fund:vaneck-vbill",
    "STAC": "fund:arca-stac",
    "BENJI": "fund:franklin-benji",
    # rwa_floor.json pools NOT in the 11-asset safety board (so cash_treasury, not rwa.py, owns
    # them — see SAFETY_BOARD_SYMBOLS below):
    "USTB": "fund:invesco-ustb",
    "USCC": "fund:bitwise-uscc",
    # OpenEden's fund-level TBILL token — NOT merged with cUSDO's root (fund:openeden-usdo):
    # nothing in this repo documents whether TBILL and USDO are the same underlying fund, and
    # review #4/#16 forbid inventing a shared root on a guess.
    "TBILL": "fund:openeden-tbill",
}
#: the 11 symbols rwa_safety_board.json documents — rwa.py owns every one of them exclusively
#: (issuer/redemption/NAV facts included); cash_treasury skips any rwa_floor.json pool whose
#: symbol is in this set (review M1). Kept in sync with the live safety board by
#: ``test_cash_treasury_safety_board_symbols_match_rwa_py`` rather than a shared runtime read —
#: a static cross-check, not a new inter-scanner dependency.
SAFETY_BOARD_SYMBOLS = frozenset({
    "BUIDL", "sBUIDL", "USYC", "OUSG", "USDY", "USDM", "wUSDM", "cUSDO", "VBILL", "STAC", "BENJI",
})

#: review N6: both tables above are keyed by their CANONICAL mixed-case spelling (wUSDM, cUSDO,
#: sBUIDL — matching how collateral_registry.py/rwa_safety_board.json actually write them), so a
#: caller that upper/lower-cases the symbol before lookup (``symbol.upper()`` was exactly this
#: bug) misses them: wUSDM → "WUSDM" ≠ "wUSDM", producing a DIFFERENT, unmerged root
#: ("fund:wusdm" instead of "fund:mountain-usdm") and a membership check that silently says "not
#: on the board". Built ONCE, case-folded, so every caller gets the same answer regardless of how
#: it happened to case the symbol it is holding.
_FUND_ROOTS_CASEFOLD = {k.casefold(): v for k, v in FUND_ROOTS.items()}
_SAFETY_BOARD_SYMBOLS_CASEFOLD = frozenset(s.casefold() for s in SAFETY_BOARD_SYMBOLS)


def fund_root(symbol: str, default: str) -> str:
    """The shared fund root for ``symbol``: the EXACT key first, then a case-folded lookup — so a
    wrapper (wUSDM, cUSDO, sBUIDL) always resolves to the same root as its underlying fund,
    regardless of what case the caller's symbol happens to be in (review N6)."""
    if symbol in FUND_ROOTS:
        return FUND_ROOTS[symbol]
    return _FUND_ROOTS_CASEFOLD.get(str(symbol or "").casefold(), default)


def is_safety_board_symbol(symbol: str) -> bool:
    """Case-insensitive membership in ``SAFETY_BOARD_SYMBOLS`` (review N6's root cause, applied to
    the only OTHER place this repo compares a symbol against that mixed-case table)."""
    return str(symbol or "").casefold() in _SAFETY_BOARD_SYMBOLS_CASEFOLD


#: shared across scanners (duplicated — see discovery.py/basis.py/rwa.py for the same table):
#: a live-adapter / paper-book protocol key → the underlying_root it economically IS, so a
#: freshly discovered or re-proxied instrument collides with what the live books already hold.
PROTOCOL_ROOT_MAP = {
    "spark_susds": "fund:sky-savings", "sky_susds": "fund:sky-savings",
    "sdai": "fund:sky-savings",
    "susde": "fund:ethena-susde", "ethena_susde": "fund:ethena-susde",
    "wusdm": "fund:mountain-usdm",
}

#: sUSDS/sDAI "resolve to the Sky savings root" (ADR-560 binding revision, review #3, verbatim).
ROOT_SKY_SAVINGS = "fund:sky-savings"

_SAVINGS = (
    # (adapter_status protocol key, display symbol, driver key, on-chain address, adapter class)
    ("spark_susds", "sUSDS", "SKY_SSR", onchain.SUSDS_ADDRESS, SparkSusdsAdapter),
    ("sdai", "sDAI", "MAKER_DSR", onchain.SDAI_ADDRESS, SdaiAdapter),
)


def _existing_book_roots(data_dir: Path) -> list:
    roots = set()
    cur, _ = read_json(data_dir / "current_positions.json")
    if isinstance(cur, dict):
        for p in (cur.get("feed_coverage") or {}).get("live_adapters") or []:
            r = PROTOCOL_ROOT_MAP.get(str(p))
            if r:
                roots.add(r)
        for p in (cur.get("positions") or {}):
            r = PROTOCOL_ROOT_MAP.get(str(p))
            if r:
                roots.add(r)
    for fname in ("hy_paper_trading.json", "lp_paper_trading.json"):
        doc, _ = read_json(data_dir / fname)
        if isinstance(doc, dict):
            for pos in doc.get("positions") or []:
                if isinstance(pos, dict):
                    r = PROTOCOL_ROOT_MAP.get(str(pos.get("protocol")))
                    if r:
                        roots.add(r)
    return sorted(roots)


def _exit_latency_cell(adapter_cls, source_ref: str, now: datetime) -> dict:
    """``EXIT_LATENCY_HOURS`` is a genuine class attribute the adapter module itself declares
    (not a DeFiLlama field, and not this scanner's invention, review M3) — DOCUMENTED,
    SECONDARY_SOURCE (a repo-curated code constant, not an issuer term and not an audit). A
    static design constant carries no meaningful observation time, so ``as_of`` is left unset
    (``None`` — allowed for DOCUMENTED; never backfilled with the scan clock, review H1)."""
    if adapter_cls is None or not hasattr(adapter_cls, "EXIT_LATENCY_HOURS"):
        return not_measured("adapter module unavailable or has no EXIT_LATENCY_HOURS constant")
    hours = getattr(adapter_cls, "EXIT_LATENCY_HOURS")
    if not isinstance(hours, (int, float)) or isinstance(hours, bool):
        return not_measured("EXIT_LATENCY_HOURS is not a usable number")
    return contract.cell(contract.DOCUMENTED, float(hours), unit="hours", source_ref=source_ref,
                         source_class=contract.SECONDARY_SOURCE, source_root="doc:adapter_module",
                         recorded_at=now.isoformat(), now=now)


def _savings_candidate(protocol: str, symbol: str, driver: str, address: str, adapter_cls, block: dict,
                        gsm: Optional[dict], now: datetime, rpc_client) -> "tuple[dict, dict, dict]":
    as_of = block.get("live_apy_as_of")
    base_apy = block.get("apy_base")
    if base_apy is None and block.get("live_apy") is not None:
        base_apy = block.get("live_apy")  # no reward split published for this protocol — the whole thing is base
    source_ref = f"data/adapter_status.json#adapters.{protocol}"

    cells: dict = {}
    if isinstance(base_apy, (int, float)) and isinstance(as_of, str) and block.get("live_apy_fresh"):
        cells["base_return"] = contract.cell(contract.MEASURED, float(base_apy), unit="pct_apy",
                                              source_ref=source_ref, source_class=contract.REPUTABLE_AGGREGATOR,
                                              source_root="defillama:yields", as_of=as_of,
                                              recorded_at=now.isoformat(), now=now, window="spot")
    else:
        cells["base_return"] = not_measured(f"{protocol}: no fresh live_apy in adapter_status.json")

    reward = block.get("apy_reward")
    if isinstance(reward, (int, float)) and isinstance(as_of, str):
        cells["incentive_return"] = contract.cell(contract.MEASURED, float(reward), unit="pct_apy",
                                                   source_ref=source_ref, source_class=contract.REPUTABLE_AGGREGATOR,
                                                   source_root="defillama:yields", as_of=as_of,
                                                   recorded_at=now.isoformat(), now=now, window="spot")
    else:
        cells["incentive_return"] = not_measured(f"{protocol}: apy_reward not published, or no as_of to pin it to")

    cells["quoted_return"] = not_measured(
        f"{protocol}: no issuer-advertised rate distinct from the DeFiLlama-relayed reading is carried "
        "in this repo (fallback_apy is our own offline assumption, not an issuer claim)")
    cells["fees"] = not_applicable("no deposit/withdrawal fee documented for this savings vault")
    cells["gas"] = not_measured("gas cost of mint/redeem not measured")
    cells["hedging_cost"] = not_applicable("no hedge required for a cash/treasury position")
    cells["funding"] = not_applicable("no funding leg for a savings vault")
    cells["duration"] = not_applicable("floating daily savings rate; no fixed maturity")
    cells["time_to_exit"] = _exit_latency_cell(adapter_cls, f"spa_core/adapters/{protocol}_adapter.py", now)
    tvl = block.get("tvl_usd")
    if isinstance(tvl, (int, float)) and block.get("tvl_source") == "live" and isinstance(as_of, str):
        cells["capacity"] = contract.cell(contract.MEASURED, float(tvl), unit="usd", source_ref=source_ref,
                                          source_class=contract.REPUTABLE_AGGREGATOR,
                                          source_root="defillama:yields", as_of=as_of,
                                          recorded_at=now.isoformat(), now=now)
    else:
        cells["capacity"] = not_measured(f"{protocol}: tvl_usd not live-sourced, or no as_of to pin it to")
    cells["liquidity"] = not_measured(f"{protocol}: no separate exit-liquidity depth measurement beyond TVL")
    cells["measured_return"] = not_applicable("pre-admission scan; no running paper account yet")
    cells["realised_return"] = not_applicable("pre-admission scan; no running paper account yet")
    cells["net_expected_return"] = contract.net_expected_return(cells)

    gsm_hours = gsm_as_of = None
    if gsm and gsm.get("source") == "onchain" and isinstance(gsm.get("gsm_hours"), (int, float)):
        gsm_hours, gsm_as_of = gsm.get("gsm_hours"), gsm.get("last_checked")
    cp = counterparty_registry.stablecoin_savings(symbol, gsm_hours=gsm_hours, gsm_as_of=gsm_as_of)

    obs = {}
    idx = onchain.realised_index(symbol, address, rpc_client=rpc_client, now=now)
    period = now.date().isoformat()
    observed = cells["base_return"] if cells["base_return"]["state"] == contract.MEASURED else None
    if observed is not None or idx.get("state") == contract.MEASURED:
        obs = {"observed_return": observed or not_measured("no fresh base_return this period"),
               "realised_index": idx if idx.get("state") == contract.MEASURED else None,
               "period": period}

    cand = full_candidate(
        scanner=SCANNER_NAME, mechanism_id="STABLECOIN_SAVINGS", domain=DOMAIN, network="ethereum",
        instrument=symbol, instrument_id=f"1:{address.lower()}", venue_or_protocol=protocol,
        underlying_root=ROOT_SKY_SAVINGS, economic_driver_key=driver, yield_source="savings_rate",
        strategy_family="cash_treasury", return_window="spot", cells=cells, now=now,
    )
    return cand, obs, cp


def _treasury_candidates(pools: list, now: datetime, generated_at: Optional[str]) -> "tuple[list, dict, dict]":
    """``generated_at`` is ``market_data/rwa_floor.json``'s OWN top-level timestamp (the one true
    upstream time this cache carries) — ``None`` when the file does not have one, in which case
    every MEASURED cell below becomes NOT_MEASURED instead (review H1/M4: never fall back to the
    scan clock, and never raise building a cell with ``as_of=None``)."""
    candidates, observations, counterparty = [], {}, {}
    source_ref = "data/market_data/rwa_floor.json"
    has_as_of = isinstance(generated_at, str)
    for row in pools:
        if not isinstance(row, dict):
            continue
        label, apy_pct, tvl_usd, pool_id = row.get("label"), row.get("apy_pct"), row.get("tvl_usd"), row.get("pool")
        if not (isinstance(label, str) and ":" in label and isinstance(apy_pct, (int, float))
                and isinstance(pool_id, str) and pool_id):
            continue
        project, symbol = label.split(":", 1)
        symbol = symbol.strip()
        if is_safety_board_symbol(symbol):
            # review M1: rwa.py owns every safety-board fund exclusively — never emit it twice.
            continue
        instrument_id = f"llama:{pool_id.lower()}"
        if has_as_of:
            base_return = contract.cell(contract.MEASURED, float(apy_pct), unit="pct_apy", source_ref=source_ref,
                                        source_class=contract.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                        as_of=generated_at, recorded_at=now.isoformat(), now=now, window="spot")
        else:
            base_return = not_measured("market_data/rwa_floor.json has no 'generated_at' timestamp "
                                        "— no genuine upstream time to pin this rate to")
        cells = {
            "base_return": base_return,
            "incentive_return": not_applicable("tokenised-Treasury yield has no incentive/reward component"),
            "quoted_return": not_measured("no separately documented issuer-advertised rate in this repo"),
            "fees": not_measured("redemption/management fee not separately measured per pool"),
            "gas": not_applicable("off-chain fund; no gas leg"),
            "hedging_cost": not_applicable("no hedge required for a Treasury holding"),
            "funding": not_applicable("no funding leg for a Treasury holding"),
            "duration": not_measured("fund duration not published in this repo's data"),
            "liquidity": not_measured("exit liquidity not separately measured for this pool"),
            "time_to_exit": not_measured("redemption timeline not in market_data/rwa_floor.json"),
            "capacity": (contract.cell(contract.MEASURED, float(tvl_usd), unit="usd", source_ref=source_ref,
                                       source_class=contract.REPUTABLE_AGGREGATOR, source_root="defillama:yields",
                                       as_of=generated_at, recorded_at=now.isoformat(), now=now)
                        if isinstance(tvl_usd, (int, float)) and has_as_of else
                        not_measured("tvl_usd missing for this pool, or no as_of to pin it to")),
            "measured_return": not_applicable("pre-admission scan; no running paper account yet"),
            "realised_return": not_applicable("pre-admission scan; no running paper account yet"),
        }
        cells["net_expected_return"] = contract.net_expected_return(cells)
        root = fund_root(symbol, f"fund:{project.strip().lower()}-{symbol.lower()}")
        cand = full_candidate(
            scanner=SCANNER_NAME, mechanism_id="TOKENISED_TREASURY", domain=DOMAIN, network="offchain",
            instrument=symbol, instrument_id=instrument_id, venue_or_protocol=project,
            underlying_root=root, economic_driver_key="UST_BILL", yield_source="rwa_tbill",
            strategy_family="cash_treasury", return_window="spot", cells=cells, now=now,
        )
        candidates.append(cand)
        if cells["base_return"]["state"] == contract.MEASURED:
            observations[cand["candidate_id"]] = {"observed_return": cells["base_return"], "realised_index": None,
                                                   "period": now.date().isoformat()}
        counterparty[cand["candidate_id"]] = counterparty_registry.tokenised_treasury(
            symbol, None, source_ref=source_ref, redemption_documented=False)
    return candidates, observations, counterparty


def scan(data_dir, now: datetime, *, rpc_client=None) -> dict:
    data_dir = Path(data_dir)
    as_of = now.isoformat()
    existing_book_roots = _existing_book_roots(data_dir)

    status_doc, status_err = read_json(data_dir / "adapter_status.json")
    rwa_floor_doc, rwa_floor_err = read_json(data_dir / "market_data" / "rwa_floor.json")
    sky_status_doc, _ = read_json(data_dir / "sky_status.json")

    if status_doc is None and rwa_floor_doc is None:
        reason = f"adapter_status.json: {status_err}; market_data/rwa_floor.json: {rwa_floor_err}"
        res = empty_result(SCANNER_NAME, DOMAIN, as_of, "UNAVAILABLE", reason)
        res["existing_book_roots"] = existing_book_roots
        return res

    candidates, observations, counterparty, unresolved = [], {}, {}, []
    adapters = (status_doc or {}).get("adapters") if isinstance(status_doc, dict) else None
    adapters = adapters if isinstance(adapters, dict) else {}
    for protocol, symbol, driver, address, adapter_cls in _SAVINGS:
        block = adapters.get(protocol)
        if not isinstance(block, dict):
            unresolved.append({"name": symbol, "reason": f"adapter_status.json has no '{protocol}' block"})
            continue
        cand, obs, cp = _savings_candidate(protocol, symbol, driver, address, adapter_cls, block,
                                           sky_status_doc if protocol == "spark_susds" else None, now, rpc_client)
        candidates.append(cand)
        if obs:
            observations[cand["candidate_id"]] = obs
        counterparty[cand["candidate_id"]] = cp

    n_treasury_scanned = 0
    if isinstance(rwa_floor_doc, dict):
        pools = rwa_floor_doc.get("pools")
        if isinstance(pools, list):
            n_treasury_scanned = len(pools)
            generated_at = rwa_floor_doc.get("generated_at")
            t_cands, t_obs, t_cp = _treasury_candidates(pools, now,
                                                        generated_at if isinstance(generated_at, str) else None)
            candidates.extend(t_cands)
            observations.update(t_obs)
            counterparty.update(t_cp)

    status = "OK" if (status_doc is not None and rwa_floor_doc is not None) else "PARTIAL"
    reason = None if status == "OK" else (status_err or rwa_floor_err)
    return {
        "scanner": SCANNER_NAME, "domain": DOMAIN, "as_of": as_of, "status": status, "reason": reason,
        "denominators": {"scanned": n_treasury_scanned + len(_SAVINGS), "discovered": len(candidates),
                         "truncated": None},
        "candidates": candidates, "unresolved": unresolved, "observations": observations,
        "counterparty": counterparty, "existing_book_roots": existing_book_roots,
    }
