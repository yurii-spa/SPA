"""spa_core/paper_trading/morpho_market.py — one Morpho Blue market observed from primary sources.

Input of the Aggressive loop PAPER model (ADR-533). Every number is tagged with where it came from:

==========================  ===================================================================
quantity                    primary source
==========================  ===================================================================
loan / collateral / oracle  ``Morpho.idToMarketParams(id)`` — on-chain, 2-witness quorum
LLTV                        same call (the market's immutable liquidation LTV)
supply / borrow / shares    ``Morpho.market(id)`` — on-chain, 2-witness quorum (1e-4 tolerance)
collateral price            ``oracle.price()`` — THE price this market liquidates at (on-chain)
sUSDe share price           ``sUSDe.convertToAssets(1e18)`` — ERC-4626, on-chain
borrow APY                  Morpho API ``state.borrowApy`` cross-checked with DeFiLlama
                            ``/lendBorrow`` ``apyBaseBorrow`` (both off-chain; must agree)
liquidation incentive       computed from LLTV with Morpho Blue's own constants:
                            ``LIF = min(1.15, 1 / (1 − 0.3·(1 − LLTV)))``
                            (``ConstantsLib.MAX_LIQUIDATION_INCENTIVE_FACTOR`` /
                            ``LIQUIDATION_CURSOR``, used by ``Morpho._liquidate``)
==========================  ===================================================================

``observe()`` never raises and never fills a gap: any input without its quorum is ``None`` with
a reason, and ``ok`` is ``True`` only when every input the model needs is measured.
Read-only (``eth_call`` / HTTPS GET), stdlib, LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from spa_core.paper_trading import onchain_read as R

MORPHO_BLUE = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
SEL_ID_TO_MARKET_PARAMS = "0x2c3c9157"   # idToMarketParams(bytes32)
SEL_MARKET = "0x5c60e39a"                # market(bytes32)
SEL_PRICE = "0xa035b1fe"                 # IOracle.price()
SEL_CONVERT_TO_ASSETS = "0x07a2d13a"     # ERC4626.convertToAssets(uint256)
SEL_DECIMALS = "0x313ce567"              # ERC20.decimals()

#: Morpho Blue ConstantsLib (WAD-scaled in the contract; plain floats here).
MAX_LIQUIDATION_INCENTIVE_FACTOR = 1.15
LIQUIDATION_CURSOR = 0.3
#: Morpho Blue SharesMathLib virtual offsets.
VIRTUAL_SHARES = 10 ** 6
VIRTUAL_ASSETS = 1

MORPHO_API = "https://blue-api.morpho.org/graphql"
LLAMA_LENDBORROW = "https://yields.llama.fi/lendBorrow"

#: The one market the first loop experiment uses (ADR-533) — identity fixed, not discovered.
SUSDE_PYUSD_915 = {
    "market_id": "0x90ef0c5a0dc7c4de4ad4585002d44e9d411d212d2f6258e94948beecf8b4c0d5",
    "chain": "ethereum",
    "loan_symbol": "PYUSD",
    "collateral_symbol": "sUSDe",
    "llama_pool": "9b0c3b21-d47b-4b0c-855d-d1b78cd35350",
    "expect_loan": "0x6c3ea9036406852006290770bedfcaba0e23a0e8",
    "expect_collateral": "0x9d39a5de30e57443bff2a8307a4256c8797a3497",
}

BORROW_APY_MAX_DISAGREEMENT_PP = 0.5


def liquidation_incentive_factor(lltv: float) -> float:
    return min(MAX_LIQUIDATION_INCENTIVE_FACTOR, 1.0 / (1.0 - LIQUIDATION_CURSOR * (1.0 - lltv)))


def shares_to_assets(shares: float, total_assets: float, total_shares: float) -> float:
    """Morpho Blue ``toAssetsDown`` with virtual shares/assets (paper: float precision)."""
    return shares * (total_assets + VIRTUAL_ASSETS) / (total_shares + VIRTUAL_SHARES)


def assets_to_shares(assets: float, total_assets: float, total_shares: float) -> float:
    return assets * (total_shares + VIRTUAL_SHARES) / (total_assets + VIRTUAL_ASSETS)


def _get_json(url: str, body: Optional[dict] = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"User-Agent": "spa-paper/1.0", "Content-Type": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=20) as r:  # noqa: S310
        return json.loads(r.read())


def _api_borrow_apy(market_id: str, get_json: Callable) -> tuple[Optional[float], Optional[str]]:
    q = '{ marketById(marketId:"%s", chainId:1) { state { borrowApy } } }' % market_id
    try:
        d = get_json(MORPHO_API, {"query": q})
        v = ((((d or {}).get("data") or {}).get("marketById") or {}).get("state") or {}).get("borrowApy")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v) * 100.0, None
        return None, "Morpho API returned no borrowApy"
    except Exception as exc:  # noqa: BLE001
        return None, f"Morpho API unreachable: {type(exc).__name__}"


def _llama_borrow_apy(pool: str, get_json: Callable) -> tuple[Optional[float], Optional[str]]:
    try:
        rows = get_json(LLAMA_LENDBORROW)
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("pool") == pool:
                v = r.get("apyBaseBorrow")
                return (float(v), None) if isinstance(v, (int, float)) else (None, "no apyBaseBorrow")
        return None, "pool absent from /lendBorrow"
    except Exception as exc:  # noqa: BLE001
        return None, f"DeFiLlama unreachable: {type(exc).__name__}"


def observe(market: dict = SUSDE_PYUSD_915, *, post: Optional[R.Post] = None,
            get_json: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    """One observation of ``market``. ``ok`` only when every model input is measured."""
    now = now or datetime.now(timezone.utc)
    get_json = get_json or _get_json
    mid = market["market_id"][2:]
    obs: dict = {"observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "market_id": market["market_id"],
                 "chain": market["chain"], "source_contract": MORPHO_BLUE, "missing": []}

    p = R.eth_call_quorum(MORPHO_BLUE, SEL_ID_TO_MARKET_PARAMS + mid, post=post)
    if p["result"]:
        w = R.words(p["result"])
        loan, coll, oracle = R.address_word(w[0]), R.address_word(w[1]), R.address_word(w[2])
        lltv = w[4] / 1e18
        identity_ok = loan == market["expect_loan"] and coll == market["expect_collateral"]
        obs.update(loan_token=loan, collateral_token=coll, oracle=oracle, irm=R.address_word(w[3]),
                   lltv=lltv, identity_ok=identity_ok,
                   liquidation_incentive_factor=liquidation_incentive_factor(lltv),
                   params_witnesses=p["witnesses"])
        if not identity_ok:
            obs["missing"].append("identity (on-chain loan/collateral differ from the declared market)")
    else:
        obs["missing"].append(f"market params: {p['reason']}")

    m = R.eth_call_quorum(MORPHO_BLUE, SEL_MARKET + mid, post=post, rel_tol=1e-4)
    if m["result"]:
        v = R.words(m["result"])
        obs.update(total_supply_assets_raw=v[0], total_supply_shares_raw=v[1],
                   total_borrow_assets_raw=v[2], total_borrow_shares_raw=v[3],
                   last_update=v[4], market_witnesses=m["witnesses"])
    else:
        obs["missing"].append(f"market state: {m['reason']}")

    if obs.get("oracle") and obs.get("loan_token") and obs.get("collateral_token"):
        dl = R.eth_call_quorum(obs["loan_token"], SEL_DECIMALS, post=post)
        dc = R.eth_call_quorum(obs["collateral_token"], SEL_DECIMALS, post=post)
        pr = R.eth_call_quorum(obs["oracle"], SEL_PRICE, post=post, rel_tol=1e-6)
        sp = R.eth_call_quorum(obs["collateral_token"], SEL_CONVERT_TO_ASSETS + R.uint_arg(10 ** 18),
                               post=post, rel_tol=1e-6)
        if dl["result"] and dc["result"]:
            loan_dec, coll_dec = R.words(dl["result"])[0], R.words(dc["result"])[0]
            obs.update(loan_decimals=loan_dec, collateral_decimals=coll_dec)
            if pr["result"]:
                # Morpho oracle: collateral price in loan units, scaled by 1e36 · 10^(loan−coll).
                raw = R.words(pr["result"])[0]
                obs["collateral_price_in_loan"] = raw / (10 ** (36 + loan_dec - coll_dec))
                obs["oracle_witnesses"] = pr["witnesses"]
            else:
                obs["missing"].append(f"oracle price: {pr['reason']}")
            if sp["result"]:
                obs["collateral_share_price"] = R.words(sp["result"])[0] / 10 ** 18
            else:
                obs["missing"].append(f"collateral share price: {sp['reason']}")
            if "total_borrow_assets_raw" in obs:
                scale = 10 ** loan_dec
                ta = obs["total_supply_assets_raw"] / scale
                ba = obs["total_borrow_assets_raw"] / scale
                # Borrow share price in loan units per RAW share (shares carry Morpho's virtual
                # 1e6 offset, so they are NOT scaled by the token's decimals).
                obs.update(total_supply=ta, total_borrow=ba,
                           borrow_share_price=shares_to_assets(1.0, obs["total_borrow_assets_raw"],
                                                               obs["total_borrow_shares_raw"]) / scale,
                           utilization=(ba / ta if ta > 0 else None),
                           available_liquidity=max(0.0, ta - ba))
        else:
            obs["missing"].append("token decimals")
    if obs.get("collateral_price_in_loan") and obs.get("collateral_share_price"):
        # what the oracle implies for one unit of the collateral's ASSET (USDe) in loan units (PYUSD)
        obs["implied_underlying_price_in_loan"] = (obs["collateral_price_in_loan"]
                                                   / obs["collateral_share_price"])

    api, api_why = _api_borrow_apy(market["market_id"], get_json)
    llama, llama_why = _llama_borrow_apy(market["llama_pool"], get_json)
    obs.update(borrow_apy_morpho_api_pct=api, borrow_apy_defillama_pct=llama)
    if api is not None and llama is not None:
        if abs(api - llama) <= BORROW_APY_MAX_DISAGREEMENT_PP:
            obs["borrow_apy_pct"] = api
        else:
            obs["missing"].append(f"borrow APY sources disagree ({api:.3f} vs {llama:.3f} pp)")
    elif api is not None or llama is not None:
        obs["missing"].append(f"borrow APY single source ({api_why or llama_why})")
    else:
        obs["missing"].append(f"borrow APY: {api_why}; {llama_why}")
    obs["ok"] = not obs["missing"]
    return obs
