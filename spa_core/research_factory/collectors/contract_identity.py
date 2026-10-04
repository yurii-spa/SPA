"""spa_core/research_factory/collectors/contract_identity.py — ADR-564 (RM-EVIDENCE-01) package
E3, coordinator live-validation finding #3 (2026-10-04).

Every live run of the funding-pair candidates graded ``identity_verified`` FAIL / PRIMARY_IDENTITY
WEAK: `evidence_contract.GRADING_RULES["PRIMARY_IDENTITY"]` is explicit that a perp's identity
grades ADEQUATE from "venue contract spec from the venue API" — but nothing collected one. This
module does, for every venue + asset the funding/basis tracks cover, via the SAME allow-listed
client every other collector uses (every endpoint below is already inside
``evidence_contract.HTTP_ALLOW`` by host+method+path-prefix — no new grant needed):

* Binance perp (``fapi.binance.com/fapi/v1/exchangeInfo``) AND spot
  (``api.binance.com/api/v3/exchangeInfo``) — two different hosts, so both are fetched;
* Bybit (``api.bybit.com/v5/market/instruments-info``), perp (``category=linear``) and spot
  (``category=spot``) from the SAME endpoint;
* OKX (``www.okx.com/api/v5/public/instruments``), perp (``instType=SWAP``) and spot
  (``instType=SPOT``) from the SAME endpoint;
* KuCoin perp (``api-futures.kucoin.com/api/v1/contracts/{symbol}``) — no public spot-market
  identity call is made (out of this module's asked scope; the spot LEG's identity for KuCoin
  stays WEAK/cited-only until asked for);
* Hyperliquid (perp only, no native spot) — reuses the ALREADY-allow-listed
  ``metaAndAssetCtxs`` info type (its first element's ``universe`` IS what a bare ``meta`` call
  would return) rather than requesting a new Hyperliquid info-type grant.

Emits one ``OBS_ROW_FIELDS`` row per (venue, asset, leg) under
``claim = "{perp|spot}_contract_identity:{ASSET}"``, ``origin = "venue:<venue>"``,
``channel = official_api`` — the shape E1's grades.py reads to grade PRIMARY_IDENTITY for a
funding-pair candidate's perp (and, where collected, spot) leg.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from typing import Optional

from spa_core.research_factory import contract, evidence_contract
from spa_core.research_factory.collectors.books import PERP_VENUES, SPOT_VENUES, _PERP_SYMBOL, _SYMBOL

PERP_IDENTITY_CLAIM = "perp_contract_identity"
SPOT_IDENTITY_CLAIM = "spot_contract_identity"

_PERP_ENDPOINTS = {
    "binance": ("fapi.binance.com", "/fapi/v1/exchangeInfo"),
    "bybit": ("api.bybit.com", "/v5/market/instruments-info"),
    "okx": ("www.okx.com", "/api/v5/public/instruments"),
    "kucoin": ("api-futures.kucoin.com", "/api/v1/contracts/{symbol}"),
    "hyperliquid": ("api.hyperliquid.xyz", "/info"),
}
_SPOT_ENDPOINTS = {
    "binance": ("api.binance.com", "/api/v3/exchangeInfo"),
    "bybit": ("api.bybit.com", "/v5/market/instruments-info"),
    "okx": ("www.okx.com", "/api/v5/public/instruments"),
}


def _row(*, candidate_id: str, claim: str, state: str, value, origin: str, ref: str, now: datetime,
        reason: Optional[str] = None) -> dict:
    return {"schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": candidate_id, "claim": claim,
           "value": value, "unit": "contract_spec", "window": None, "upstream_ts": None,
           "fetched_at": now.isoformat(), "origin": origin, "channel": evidence_contract.CHANNEL_OFFICIAL_API,
           "ref": ref, "raw_sha256": None, "backfill": False, "revises": None, "state": state, "reason": reason}


def _candidate_id(asset: str, venue: str) -> str:
    return contract.candidate_id(contract.exposure_key("FUNDING_CAPTURE", f"perp:{asset}:{venue}", "cex"))


def _perp_identity(venue: str, asset: str, client) -> "tuple[Optional[dict], Optional[str]]":
    host, path = _PERP_ENDPOINTS[venue]
    symbol = _PERP_SYMBOL[asset][venue]
    try:
        if venue == "binance":
            doc = client.get(host, path, {})
            row = next((s for s in (doc or {}).get("symbols", []) if s.get("symbol") == symbol), None)
            if row is None:
                return None, f"{symbol} not found in fapi exchangeInfo"
            return {"symbol": row.get("symbol"), "contract_type": row.get("contractType"),
                    "settle_asset": row.get("marginAsset"), "base_asset": row.get("baseAsset"),
                    "quote_asset": row.get("quoteAsset")}, None
        if venue == "bybit":
            doc = client.get(host, path, {"category": "linear", "symbol": symbol})
            rows = ((doc or {}).get("result") or {}).get("list") or []
            row = next((r for r in rows if r.get("symbol") == symbol), None)
            if row is None:
                return None, f"{symbol} not found in bybit instruments-info (linear)"
            return {"symbol": row.get("symbol"), "contract_type": row.get("contractType"),
                    "settle_asset": row.get("settleCoin"), "base_asset": row.get("baseCoin"),
                    "quote_asset": row.get("quoteCoin")}, None
        if venue == "okx":
            doc = client.get(host, path, {"instType": "SWAP", "instId": symbol})
            rows = (doc or {}).get("data") or []
            row = rows[0] if rows else None
            if row is None:
                return None, f"{symbol} not found in okx instruments (SWAP)"
            return {"symbol": row.get("instId"), "contract_type": row.get("ctType"),
                    "settle_asset": row.get("settleCcy"), "base_asset": row.get("ctValCcy"),
                    "quote_asset": None, "ct_val": row.get("ctVal")}, None
        if venue == "kucoin":
            doc = client.get(host, path.format(symbol=symbol), {})
            row = (doc or {}).get("data")
            if not isinstance(row, dict):
                return None, f"{symbol} not found in kucoin contracts"
            return {"symbol": row.get("symbol"), "contract_type": row.get("type"),
                    "settle_asset": row.get("settleCurrency"), "base_asset": row.get("baseCurrency"),
                    "quote_asset": row.get("quoteCurrency"), "multiplier": row.get("multiplier")}, None
        if venue == "hyperliquid":
            # reuse the already-allow-listed metaAndAssetCtxs — its first element's "universe"
            # IS a bare `meta` call's response; no new Hyperliquid info-type grant needed.
            doc = client.post_info("metaAndAssetCtxs", {})
            universe = doc[0].get("universe", []) if isinstance(doc, list) and doc else []
            row = next((u for u in universe if u.get("name") == symbol), None)
            if row is None:
                return None, f"{symbol} not found in hyperliquid metaAndAssetCtxs universe"
            return {"symbol": row.get("name"), "contract_type": "PERPETUAL", "settle_asset": "USDC",
                    "base_asset": row.get("name"), "quote_asset": "USDC",
                    "sz_decimals": row.get("szDecimals"), "max_leverage": row.get("maxLeverage")}, None
    except Exception as exc:  # noqa: BLE001 — a venue-specific failure never crashes the collector
        return None, f"{type(exc).__name__}: {exc}"
    return None, f"unhandled venue {venue!r}"


def _spot_identity(venue: str, asset: str, client) -> "tuple[Optional[dict], Optional[str]]":
    host, path = _SPOT_ENDPOINTS[venue]
    symbol = _SYMBOL[asset][venue]
    try:
        if venue == "binance":
            doc = client.get(host, path, {"symbol": symbol})
            rows = (doc or {}).get("symbols") or []
            row = rows[0] if rows else None
            if row is None:
                return None, f"{symbol} not found in binance spot exchangeInfo"
            return {"symbol": row.get("symbol"), "contract_type": "SPOT", "settle_asset": None,
                    "base_asset": row.get("baseAsset"), "quote_asset": row.get("quoteAsset"),
                    "status": row.get("status")}, None
        if venue == "bybit":
            doc = client.get(host, path, {"category": "spot", "symbol": symbol})
            rows = ((doc or {}).get("result") or {}).get("list") or []
            row = next((r for r in rows if r.get("symbol") == symbol), None)
            if row is None:
                return None, f"{symbol} not found in bybit instruments-info (spot)"
            return {"symbol": row.get("symbol"), "contract_type": "SPOT", "settle_asset": None,
                    "base_asset": row.get("baseCoin"), "quote_asset": row.get("quoteCoin")}, None
        if venue == "okx":
            doc = client.get(host, path, {"instType": "SPOT", "instId": symbol})
            rows = (doc or {}).get("data") or []
            row = rows[0] if rows else None
            if row is None:
                return None, f"{symbol} not found in okx instruments (SPOT)"
            return {"symbol": row.get("instId"), "contract_type": "SPOT", "settle_asset": None,
                    "base_asset": row.get("baseCcy"), "quote_asset": row.get("quoteCcy")}, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    return None, f"unhandled venue {venue!r}"


def collect(now: datetime, client, *, assets=("BTC", "ETH")) -> list:
    rows = []
    for asset in assets:
        for venue in PERP_VENUES:
            value, reason = _perp_identity(venue, asset, client) if client is not None else (None, "no client")
            ref = f"{_PERP_ENDPOINTS[venue][0]}{_PERP_ENDPOINTS[venue][1]}"
            rows.append(_row(candidate_id=_candidate_id(asset, venue),
                             claim=f"{PERP_IDENTITY_CLAIM}:{asset}", state="MEASURED" if value else "NOT_MEASURED",
                             value=value, origin=f"venue:{venue}", ref=ref, now=now, reason=reason))
        for venue in SPOT_VENUES:
            if venue not in _SPOT_ENDPOINTS:
                continue
            value, reason = _spot_identity(venue, asset, client) if client is not None else (None, "no client")
            ref = f"{_SPOT_ENDPOINTS[venue][0]}{_SPOT_ENDPOINTS[venue][1]}"
            rows.append(_row(candidate_id=_candidate_id(asset, venue),
                             claim=f"{SPOT_IDENTITY_CLAIM}:{asset}", state="MEASURED" if value else "NOT_MEASURED",
                             value=value, origin=f"venue:{venue}", ref=ref, now=now, reason=reason))
    return rows
