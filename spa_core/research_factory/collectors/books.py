"""spa_core/research_factory/collectors/books.py — ADR-564 (RM-EVIDENCE-01) package E3.

Spot and perp order-book walks for a declared notional, plus mark/index/premium per venue
(Binance, Bybit, OKX, KuCoin spot+perp; Hyperliquid PERP ONLY — it has no native BTC/ETH spot
market, per the Phase-0 citation seed). This is the hedge-leg evidence ADR-564 decision #6 needs
before a delta-neutral funding-capture PAIR may be admitted: "a delta-neutral paper position is
opened only when entry evidence for BOTH legs exists — never manufactured".

Most of these venues' book/ticker endpoints carry NO timestamp of their own (the seed is explicit:
"spot bookTicker/depth have no timestamps"); where that is true, ``upstream_ts`` stays ``None``
and ``fetched_at`` (our own clock) is the only time recorded — and the row SAYS so (``reason``
names it), never silently standing in as if it were an upstream time.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime
from typing import Optional

from spa_core.research_factory import contract, evidence_contract

DEFAULT_NOTIONAL_USD = 10_000.0

SPOT_VENUES = ("binance", "bybit", "okx", "kucoin")
PERP_VENUES = ("binance", "bybit", "okx", "kucoin", "hyperliquid")

_SPOT_ENDPOINTS = {
    "binance": ("api.binance.com", "/api/v3/depth"),
    "bybit": ("api.bybit.com", "/v5/market/orderbook"),
    "okx": ("www.okx.com", "/api/v5/market/books"),
    "kucoin": ("api.kucoin.com", "/api/v1/market/orderbook/level2_20"),
}
_PERP_MARK_ENDPOINTS = {
    "binance": ("fapi.binance.com", "/fapi/v1/premiumIndex"),
    "bybit": ("api.bybit.com", "/v5/market/tickers"),
    "okx": ("www.okx.com", "/api/v5/public/mark-price"),
    "kucoin": ("api-futures.kucoin.com", "/api/v1/contracts/{symbol}"),
    "hyperliquid": ("api.hyperliquid.xyz", "/info"),
}

_SYMBOL = {"BTC": {"binance": "BTCUSDT", "bybit": "BTCUSDT", "okx": "BTC-USDT", "kucoin": "BTC-USDT"},
          "ETH": {"binance": "ETHUSDT", "bybit": "ETHUSDT", "okx": "ETH-USDT", "kucoin": "ETH-USDT"}}
_PERP_SYMBOL = {"BTC": {"binance": "BTCUSDT", "bybit": "BTCUSDT", "okx": "BTC-USDT-SWAP", "kucoin": "XBTUSDTM",
                       "hyperliquid": "BTC"},
               "ETH": {"binance": "ETHUSDT", "bybit": "ETHUSDT", "okx": "ETH-USDT-SWAP", "kucoin": "ETHUSDTM",
                       "hyperliquid": "ETH"}}


def walk_book(levels: list, notional_usd: float) -> "tuple[Optional[float], Optional[float]]":
    """Classic VWAP book walk: ``levels`` = ``[[price, qty], ...]`` on ONE side, best price first.
    Returns ``(avg_price, filled_notional_usd)`` — ``filled_notional_usd`` is LESS than
    ``notional_usd`` (never silently padded) when the visible book is too thin; ``(None, None)``
    on an empty/malformed book, never a guessed price."""
    remaining = float(notional_usd)
    usd_spent = 0.0
    base_qty_filled = 0.0
    if not isinstance(levels, list) or not levels:
        return None, None
    for level in levels:
        if remaining <= 0:
            break
        try:
            price, qty = float(level[0]), float(level[1])
        except (TypeError, ValueError, IndexError):
            continue
        if price <= 0 or qty <= 0:
            continue
        level_usd = price * qty
        take_usd = min(level_usd, remaining)
        usd_spent += take_usd
        base_qty_filled += take_usd / price
        remaining -= take_usd
    if usd_spent <= 0 or base_qty_filled <= 0:
        return None, None
    return usd_spent / base_qty_filled, usd_spent


def _row(*, candidate_id: str, claim: str, state: str, value=None, unit=None, upstream_ts=None,
        fetched_at: str, origin: str, channel: str, ref: str, reason: Optional[str] = None) -> dict:
    return {
        "schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": candidate_id, "claim": claim, "value": value,
        "unit": unit, "window": None, "upstream_ts": upstream_ts, "fetched_at": fetched_at, "origin": origin,
        "channel": channel, "ref": ref, "raw_sha256": None, "backfill": False, "revises": None, "state": state,
        "reason": reason,
    }


def _candidate_id(asset: str, venue: str) -> str:
    return contract.candidate_id(contract.exposure_key("FUNDING_CAPTURE", f"perp:{asset}:{venue}", "cex"))


def _mid_price(doc: dict) -> Optional[float]:
    """Top-of-book mid = (best bid + best ask) / 2, from the SAME depth snapshot a book walk
    reads. ``None`` on anything malformed/missing — never a guessed mid."""
    bids = (doc or {}).get("bids") or (doc or {}).get("bids1") or []
    asks = (doc or {}).get("asks") or (doc or {}).get("asks1") or []
    try:
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
    except (IndexError, TypeError, ValueError, KeyError):
        return None
    if best_bid <= 0 or best_ask <= 0:
        return None
    return (best_bid + best_ask) / 2.0


def _spot_rows(asset: str, venue: str, client, now: datetime, notional_usd: float) -> list:
    """``[book_row, slippage_row]`` — H2 (post-implementation review, 2026-10-04): a book-walk
    FILL PRICE is a price, not a cost; the COST is the SLIPPAGE of that fill away from the SAME
    snapshot's top-of-book mid, in bps. Both rows come from ONE fetch (no doubled network calls)."""
    host, path = _SPOT_ENDPOINTS[venue]
    symbol = _SYMBOL[asset][venue]
    try:
        doc = client.get(host, path, {"symbol": symbol}) if client is not None else None
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"
        return [
            _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_book:{asset}", state="NOT_MEASURED",
                fetched_at=now.isoformat(), origin=f"venue:{venue}", channel=evidence_contract.CHANNEL_OFFICIAL_API,
                ref=f"{host}{path}", reason=reason),
            _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_slippage_bps:{asset}", state="NOT_MEASURED",
                fetched_at=now.isoformat(), origin=f"venue:{venue}", channel=evidence_contract.CHANNEL_OFFICIAL_API,
                ref=f"{host}{path}", reason=reason),
        ]
    asks = (doc or {}).get("asks") or (doc or {}).get("asks1") or []
    avg_price, filled_usd = walk_book(asks, notional_usd)
    mid = _mid_price(doc)
    if avg_price is None:
        book_row = _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_book:{asset}", state="NOT_MEASURED",
                       fetched_at=now.isoformat(), origin=f"venue:{venue}",
                       channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{host}{path}",
                       reason="book empty/malformed or too thin to fill any notional")
    else:
        # review (seed): "spot bookTicker/depth have no timestamps" -- fetch time is used and LABELLED.
        book_row = _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_book:{asset}", state="MEASURED",
                       value=round(avg_price, 8), unit=f"avg_price_usd_for_{filled_usd:.0f}_usd_notional",
                       upstream_ts=None, fetched_at=now.isoformat(), origin=f"venue:{venue}",
                       channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{host}{path}",
                       reason="venue gives no book timestamp; value is dated by OUR fetch time (fetched_at), "
                              "never treated as an upstream time")
    if avg_price is None or mid is None:
        slip_row = _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_slippage_bps:{asset}",
                       state="NOT_MEASURED", fetched_at=now.isoformat(), origin=f"venue:{venue}",
                       channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{host}{path}",
                       reason="book walk fill price or top-of-book mid not available this snapshot")
    else:
        slippage_bps = round((avg_price / mid - 1.0) * 10_000.0, 6)      # sign preserved, never clamped
        slip_row = _row(candidate_id=_candidate_id(asset, venue), claim=f"spot_slippage_bps:{asset}",
                       state="MEASURED", value=slippage_bps, unit="bps", upstream_ts=None,
                       fetched_at=now.isoformat(), origin=f"venue:{venue}",
                       channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{host}{path}",
                       reason="slippage = (book-walk fill price / top-of-book mid - 1) x 10000 bps; "
                              "venue gives no book timestamp, dated by OUR fetch time")
    return [book_row, slip_row]


def _perp_mark_row(asset: str, venue: str, client, now: datetime) -> dict:
    host, path = _PERP_MARK_ENDPOINTS[venue]
    symbol = _PERP_SYMBOL[asset][venue]
    try:
        if venue == "hyperliquid":
            doc = client.post_info("metaAndAssetCtxs", {}) if client is not None else None
        elif venue == "kucoin":
            doc = client.get(host, path.format(symbol=symbol), {}) if client is not None else None
        else:
            params = {"symbol": symbol} if venue == "binance" else {"category": "linear", "symbol": symbol} \
                if venue == "bybit" else {"instId": symbol}
            doc = client.get(host, path, params) if client is not None else None
    except Exception as exc:  # noqa: BLE001
        return _row(candidate_id=_candidate_id(asset, venue), claim=f"perp_mark:{asset}", state="NOT_MEASURED",
                   fetched_at=now.isoformat(), origin=f"venue:{venue}", channel=evidence_contract.CHANNEL_OFFICIAL_API,
                   ref=f"{host}{path}", reason=f"{type(exc).__name__}: {exc}")
    mark, index, ts = _extract_mark_index_ts(venue, doc, symbol)
    if mark is None:
        return _row(candidate_id=_candidate_id(asset, venue), claim=f"perp_mark:{asset}", state="NOT_MEASURED",
                   fetched_at=now.isoformat(), origin=f"venue:{venue}", channel=evidence_contract.CHANNEL_OFFICIAL_API,
                   ref=f"{host}{path}", reason=f"{venue}: no mark price in the response")
    premium = (mark - index) / index if (isinstance(index, (int, float)) and index) else None
    value = {"mark": mark, "index": index, "premium": premium}
    return _row(candidate_id=_candidate_id(asset, venue), claim=f"perp_mark:{asset}", state="MEASURED",
               value=value, unit="usd_and_fraction", upstream_ts=ts, fetched_at=now.isoformat(),
               origin=f"venue:{venue}", channel=evidence_contract.CHANNEL_OFFICIAL_API, ref=f"{host}{path}",
               reason=None if ts else "venue gives no mark timestamp; dated by OUR fetch time (fetched_at)")


def _extract_mark_index_ts(venue: str, doc, symbol: str) -> "tuple[Optional[float], Optional[float], Optional[str]]":
    if not isinstance(doc, dict):
        return None, None, None
    if venue == "binance":
        mark, idx, t = doc.get("markPrice"), doc.get("indexPrice"), doc.get("time")
        ts = _ms_to_iso(t)
        return _f(mark), _f(idx), ts
    if venue == "bybit":
        rows = ((doc.get("result") or {}).get("list")) or []
        row = next((r for r in rows if r.get("symbol") == symbol), None) if rows else None
        if row is None:
            return None, None, None
        return _f(row.get("markPrice")), _f(row.get("indexPrice")), _ms_to_iso(doc.get("time"))
    if venue == "okx":
        rows = doc.get("data") or []
        row = rows[0] if rows else None
        if row is None:
            return None, None, None
        return _f(row.get("markPx")), _f(row.get("idxPx")), _ms_to_iso(row.get("ts"))
    if venue == "kucoin":
        row = doc.get("data") or {}
        return _f(row.get("markPrice")), _f(row.get("indexPrice")), None
    if venue == "hyperliquid":
        try:
            universe, ctxs = doc[0].get("universe", []), doc[1]
            i = next(i for i, u in enumerate(universe) if u.get("name") == symbol)
            ctx = ctxs[i]
        except (TypeError, IndexError, StopIteration, AttributeError, KeyError):
            return None, None, None
        return _f(ctx.get("markPx")), _f(ctx.get("oraclePx")), None
    return None, None, None


def _f(v):
    return float(v) if isinstance(v, (int, float, str)) and str(v) not in ("", "None") and _is_num(v) else None


def _is_num(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _ms_to_iso(ms) -> Optional[str]:
    from datetime import timezone
    if not _is_num(ms):
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def collect(now: datetime, client, *, assets=("BTC", "ETH"), notional_usd: float = DEFAULT_NOTIONAL_USD) -> list:
    rows = []
    for asset in assets:
        for venue in SPOT_VENUES:
            rows.extend(_spot_rows(asset, venue, client, now, notional_usd))
        for venue in PERP_VENUES:
            rows.append(_perp_mark_row(asset, venue, client, now))
    return rows
