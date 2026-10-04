"""spa_core/research_factory/instruments.py — the instrument registry (ADR-564 / RM-EVIDENCE-01,
Appendix I, package E3).

Covers the four Phase-0 tokenised-Treasury instruments (BUIDL, USYC, OUSG, USDY): chain, mainnet
address, expected on-chain identity (name/symbol/decimals), the oracle reader kind + address to
use (``onchain.chainlink_round`` / ``onchain.ondo_price_data`` / ``onchain.ondo_asset_price`` /
none), the fund root wrappers/share-classes resolve to, and — the Phase-0 defect this module
exists to fix — a DeFiLlama pool JOIN that matches by CHAIN **and** CONTRACT, never by symbol.

The Phase-0 audit (ADR-564) found all three real contracts mis-joined to a same-symbol pool on
the WRONG chain: BUIDL -> Solana, OUSG -> XRPL, USYC -> BSC. A symbol-only join cannot tell "the
Ethereum BUIDL pool" from "a Solana pool that also happens to be labelled BUIDL" — this module
makes that distinction structural, not a lookup convention a caller can get wrong: the matcher
takes the pool's own ``chain`` and ``underlyingTokens`` fields and refuses anything without an
address match.

Addresses are the SAME literals already live in
``spa_core/strategy_lab/rwa_backstop/collateral_registry.py`` (imported, never retyped) — the
addresses are not in question; the WRONG CHAIN JOIN against the right address is.

LLM_FORBIDDEN, stdlib only, no network of its own (identity verification delegates to
``onchain.verify_erc20_identity``, which is the only place that touches the chain).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from spa_core.research_factory import contract, onchain

try:
    from spa_core.strategy_lab.rwa_backstop import collateral_registry
except Exception:  # noqa: BLE001 — pure config; absence is still a named outcome
    collateral_registry = None


def _addr(symbol: str, fallback: str) -> str:
    """The mainnet address for ``symbol`` — read from ``collateral_registry.by_symbol()`` when
    importable (the single existing source of these literals), else the ``fallback`` literal
    cited directly in the Phase-0 audit (used only if the registry module cannot be imported,
    e.g. in an isolated test run)."""
    if collateral_registry is not None:
        try:
            reg = collateral_registry.by_symbol().get(symbol)
            if reg is not None and getattr(reg, "token_contract", None):
                return reg.token_contract
        except Exception:  # noqa: BLE001
            pass
    return fallback


ETHEREUM_CHAIN_ID = 1

#: canonical mainnet address per instrument — see collateral_registry.py for the primary source;
#: these literals are the Phase-0 citation fallback only.
BUIDL_ADDRESS = _addr("BUIDL", "0x7712c34205737192402172409a8F7ccef8aA2AEc")
USYC_ADDRESS = _addr("USYC", "0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b")
OUSG_ADDRESS = _addr("OUSG", "0x1B19C19393e2d034D8Ff31ff34c81252FcBbee92")
USDY_ADDRESS = _addr("USDY", "0x96F6eF951840721AdBF46Ac996b59E0235CB985C")

#: oracle reader kinds this module knows how to dispatch to ``onchain.py`` — see Appendix I.
ORACLE_CHAINLINK_ROUND = "chainlink_round"
ORACLE_ONDO_PRICE_DATA = "ondo_price_data"
ORACLE_ONDO_ASSET_PRICE = "ondo_asset_price"
ORACLE_NONE = None

#: the four Phase-0 instruments — chain, address, decimals, expected on-chain identity, oracle
#: reader + address, fund root. Everything here is cited in
#: scratchpad/ev/phase0_citations.md (2026-10-04) — nothing invented.
INSTRUMENTS: dict = {
    "BUIDL": {
        "chain_id": ETHEREUM_CHAIN_ID, "address": BUIDL_ADDRESS, "decimals": 6,
        "expected_name": "BlackRock USD Institutional Digital Liquidity Fund", "expected_symbol": "BUIDL", "expected_pool_project": "blackrock-buidl",
        "mechanism_id": "TOKENISED_TREASURY", "fund_root": "fund:blackrock-buidl",
        "oracle": {"kind": ORACLE_NONE, "address": None,
                  "reason": "no on-chain NAV documented on Ethereum (Phase-0 audit); RedStone's "
                            "off-chain gateway (BUIDL_DAILY_INTEREST_ACCRUAL) is not an eth_call "
                            "source — its forward series is NOT_MEASURED by design"},
        "oracle_origin": None,
    },
    "USYC": {
        "chain_id": ETHEREUM_CHAIN_ID, "address": USYC_ADDRESS, "decimals": 6,
        "expected_name": "US Yield Coin", "expected_symbol": "USYC", "expected_pool_project": "circle-usyc",
        "mechanism_id": "TOKENISED_TREASURY", "fund_root": "fund:circle-usyc",
        "oracle": {"kind": ORACLE_CHAINLINK_ROUND,
                  "address": "0x74f2199AEb743f68f05943e5715A33EaF2b61f53", "answer_decimals": 18},
        "oracle_origin": "issuer:hashnote",
    },
    "OUSG": {
        "chain_id": ETHEREUM_CHAIN_ID, "address": OUSG_ADDRESS, "decimals": 18,
        "expected_name": "Ondo Short-Term U.S. Government Bond Fund", "expected_symbol": "OUSG", "expected_pool_project": "ondo-yield-assets",
        "mechanism_id": "TOKENISED_TREASURY", "fund_root": "fund:ondo-ousg",
        "oracle": {"kind": ORACLE_ONDO_ASSET_PRICE,
                  "address": "0x9Cad45a8BF0Ed41Ff33074449B357C7a1fAb4094", "price_decimals": 18},
        "oracle_origin": "issuer:ondo",
    },
    "USDY": {
        "chain_id": ETHEREUM_CHAIN_ID, "address": USDY_ADDRESS, "decimals": 18,
        "expected_name": "Ondo U.S. Dollar Yield", "expected_symbol": "USDY", "expected_pool_project": "ondo-yield-assets",
        "mechanism_id": "TOKENISED_TREASURY", "fund_root": "fund:ondo-usdy",
        "oracle": {"kind": ORACLE_ONDO_PRICE_DATA,
                  "address": "0x87b126e5518b6a1Bb8465779b4607C45C643DF90", "price_decimals": 18},
        "oracle_origin": "issuer:ondo",
    },
}

#: wrapper / share-class → its fund root, chain, and WHY it is never the join target (Phase-0
#: audit, review of BUIDL/USYC): a mis-join picked exactly one of these, on the WRONG chain, by
#: symbol alone.
WRAPPERS: dict = {
    "sBUIDL": {"wraps": "BUIDL", "chain_id": ETHEREUM_CHAIN_ID, "address": None,
              "note": "composable wrapper; no canonical public mainnet contract (collateral_registry.py)"},
    "USYC_BSC": {"wraps": "USYC", "chain_id": 56, "address": None,
                "note": "most USYC supply is bridged to BSC (0x8D0f…) — the Phase-0 wrong-join target; "
                        "never the Ethereum instrument's pool join"},
}


def instrument_id(symbol: str) -> str:
    meta = INSTRUMENTS[symbol]
    return f"{meta['chain_id']}:{meta['address'].lower()}"


def candidate_id_for(symbol: str) -> str:
    meta = INSTRUMENTS[symbol]
    key = contract.exposure_key(meta["mechanism_id"], instrument_id(symbol), "ethereum")
    return contract.candidate_id(key)


def verify_identity(symbol: str, *, rpc_client, now: datetime) -> dict:
    """On-chain identity verification (``contract.cell``) for ``symbol`` — delegates to
    ``onchain.verify_erc20_identity``, the only module allowed to touch the network."""
    meta = INSTRUMENTS[symbol]
    return onchain.verify_erc20_identity(
        meta["address"], expected_name=meta["expected_name"], expected_symbol=meta["expected_symbol"],
        expected_decimals=meta["decimals"], rpc_client=rpc_client, now=now,
    )


def _pool_chain(pool: dict) -> str:
    return str(pool.get("chain") or "").strip().casefold()


def _pool_underlying(pool: dict) -> list:
    toks = pool.get("underlyingTokens")
    return [str(t).lower() for t in toks] if isinstance(toks, list) else []


def join_pool_by_chain_and_contract(symbol: str, pools: list) -> "tuple[Optional[dict], Optional[str]]":
    """The DeFiLlama pool for ``symbol`` — matched by chain **AND** underlying contract address,
    never by symbol/project label (the exact Phase-0 defect: BUIDL->Solana, OUSG->XRPL,
    USYC->BSC, each a same-symbol pool on the wrong chain).

    ``pools`` is a list of DeFiLlama-shaped pool rows (``chain``, ``underlyingTokens``, …, as
    returned by ``yields.llama.fi/pools``). Returns ``(pool, None)`` on exactly one match,
    ``(None, reason)`` on zero or on an AMBIGUOUS match (more than one Ethereum pool naming this
    contract) — ambiguity is never resolved by picking the first one."""
    meta = INSTRUMENTS.get(symbol)
    if meta is None:
        return None, f"{symbol!r} is not a known instrument"
    chain_name = "ethereum"  # canonical_network("1") has no reverse map; DeFiLlama spells it "Ethereum"
    address = meta["address"].lower()
    matches = [p for p in pools if isinstance(p, dict) and _pool_chain(p) == chain_name
              and address in _pool_underlying(p)]
    if not matches:
        return None, (f"no Ethereum pool names underlying contract {address} for {symbol} "
                      "(a same-symbol pool on another chain is never substituted)")
    if len(matches) > 1:
        # Deterministic disambiguation ONLY among already chain+contract-matched pools: the issuer's own
        # DeFiLlama adapter slug is DECLARED per instrument (Phase-0 audit: the yield-server adapters
        # blackrock-buidl / circle-usyc / ondo-yield-assets). A third-party market listing the same contract
        # (e.g. flux-finance for OUSG) is not the instrument's yield. Never a fallback for zero matches.
        proj = meta.get("expected_pool_project")
        own = [p for p in matches if proj and str(p.get("project") or "").lower() == proj]
        if len(own) == 1:
            return own[0], None
        ids = sorted(str(p.get("pool")) for p in matches)
        return None, f"ambiguous: {len(matches)} Ethereum pools name {address} for {symbol}: {ids}"
    return matches[0], None


def symbol_join_is_forbidden(symbol: str, pools: list) -> bool:
    """True when at least one pool in ``pools`` shares ``symbol`` (any chain) that is NOT the
    chain-correct match — the defect surface a naive ``label.split(':')[1] == symbol`` join would
    have picked. Used only by tests to prove the fixture actually exercises the ambiguity."""
    meta = INSTRUMENTS.get(symbol)
    if meta is None:
        return False
    correct, _ = join_pool_by_chain_and_contract(symbol, pools)
    correct_id = correct.get("pool") if isinstance(correct, dict) else None
    for p in pools:
        if not isinstance(p, dict):
            continue
        label = str(p.get("symbol") or "")
        if label.upper() == symbol.upper() and p.get("pool") != correct_id:
            return True
    return False
