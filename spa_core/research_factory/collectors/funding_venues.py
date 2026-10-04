"""spa_core/research_factory/collectors/funding_venues.py — ADR-564 (RM-EVIDENCE-01) package E3.

Persists PER-VENUE funding SETTLEMENT rows for BTC and ETH perps — the Phase-0 defect this module
exists to fix: ``strategy_lab/data/funding_feed.py`` fetches up to five venues and reduces them to
one cross-venue median that gets written to ``market_data/funding.json`` as a single number; a day
with exactly one venue answering still LOOKS like a 5-venue median (the "single-print" defect).
This collector keeps every venue's own row, with the venue's own true settlement timestamp.

Row parsing uses ``research_factory._funding_row_parsers`` — a COPY, with attribution, of
``strategy_lab/data/funding_feed.py``'s five per-venue parsers (post-implementation review M7,
2026-10-04): ``funding_feed.py`` itself transitively imports a SECOND network client
(``strategy_lab.data._http.http_fetch``, raw ``urllib.request``) outside this package's
sanctioned surface (``http_client`` / ``capital_shadow.rpc`` only), and importing the parsers
directly from it pulled that whole import graph into every collector/scanner. ``funding_feed.py``
is NEVER modified — other engines depend on it as-is; this module just no longer imports it.
Those parsers read the SETTLEMENT HISTORY endpoints only (``fundingRate`` / ``funding/history`` /
``funding-rate-history`` / ``funding-rates`` / ``fundingHistory``) — never a "predicted next
funding" field (Binance/Bybit/OKX premium-index tickers) — so a predicted rate can never be
mistaken for a settlement by construction (nothing here even parses that shape).

``FUNDING_NORMALISE`` (``evidence_contract``): ``rate_per_8h = rate × 8 / interval_h``. Binance/
Bybit/OKX/KuCoin settle every 8h (``interval_h=8`` ⇒ the raw rate IS already the 8h rate);
Hyperliquid settles hourly (``interval_h=1`` ⇒ × 8). Sign is NEVER clamped — a negative funding
rate is real information (shorts pay longs) and is carried through unchanged.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from spa_core.research_factory import contract, evidence_contract
from spa_core.research_factory._funding_row_parsers import (rows_binance, rows_bybit, rows_hyperliquid,
                                                             rows_kucoin, rows_okx)

VENUES = ("binance", "bybit", "okx", "kucoin", "hyperliquid")
#: interval_h per venue — Binance/Bybit/OKX/KuCoin settle 8-hourly, Hyperliquid hourly.
INTERVAL_H = {"binance": 8.0, "bybit": 8.0, "okx": 8.0, "kucoin": 8.0, "hyperliquid": 1.0}
EXPECTED_SETTLEMENTS_PER_DAY = evidence_contract.EXPECTED_SETTLEMENTS_PER_DAY
FUNDING_SAME_VENUE_BAND_BPS_8H = evidence_contract.FUNDING_SAME_VENUE_BAND_BPS_8H

_ROW_PARSERS = {"binance": rows_binance, "bybit": rows_bybit, "okx": rows_okx, "kucoin": rows_kucoin,
                "hyperliquid": rows_hyperliquid}

_ENDPOINTS = {
    "binance": ("fapi.binance.com", "/fapi/v1/fundingRate"),
    "bybit": ("api.bybit.com", "/v5/market/funding/history"),
    "okx": ("www.okx.com", "/api/v5/public/funding-rate-history"),
    "kucoin": ("api-futures.kucoin.com", "/api/v1/contract/funding-rates"),
    "hyperliquid": ("api.hyperliquid.xyz", "/info"),
}

_SYMBOL = {"BTC": {"binance": "BTCUSDT", "bybit": "BTCUSDT", "okx": "BTC-USDT-SWAP", "kucoin": "XBTUSDTM",
                   "hyperliquid": "BTC"},
          "ETH": {"binance": "ETHUSDT", "bybit": "ETHUSDT", "okx": "ETH-USDT-SWAP", "kucoin": "ETHUSDTM",
                  "hyperliquid": "ETH"}}


def rate_per_8h(raw_rate: float, interval_h: float) -> float:
    """``evidence_contract.FUNDING_NORMALISE`` — sign preserved, never clamped."""
    return raw_rate * 8.0 / interval_h


def _fetch_payload(client, venue: str, asset: str):
    host, path = _ENDPOINTS[venue]
    symbol = _SYMBOL[asset][venue]
    if venue == "hyperliquid":
        return client.post_info("fundingHistory", {"coin": symbol})
    if venue == "bybit":
        params = {"category": "linear", "symbol": symbol}
    elif venue == "kucoin":
        # live-validation finding (2026-10-04): the endpoint 400s on an unbounded/future `to` —
        # it needs an explicit window not extending past "now".
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        params = {"symbol": symbol, "from": 0, "to": now_ms}
    elif venue == "binance":
        params = {"symbol": symbol}
    else:
        params = {"instId": symbol}
    return client.get(host, path, params)


def _venue_rows(venue: str, asset: str, payload, *, now: datetime, backfill: bool) -> list:
    parser = _ROW_PARSERS[venue]
    try:
        ts_rate = parser(payload)
    except Exception as exc:  # noqa: BLE001 — a bad/empty venue payload contributes nothing (fail-OPEN per
        # venue, same discipline as funding_feed._try_venue) — never a fabricated settlement.
        return [{
            "schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": _pair_candidate_id(asset, venue),
            "claim": f"funding_settlement:{asset}", "value": None, "unit": "rate_per_8h", "window": None,
            "upstream_ts": None, "fetched_at": now.isoformat(), "origin": f"venue:{venue}",
            "channel": evidence_contract.CHANNEL_OFFICIAL_API, "ref": f"{_ENDPOINTS[venue][0]}{_ENDPOINTS[venue][1]}",
            "raw_sha256": None, "backfill": backfill, "revises": None, "state": "NOT_MEASURED",
            "reason": f"{venue} funding: {type(exc).__name__}: {exc}",
        }]
    interval_h = INTERVAL_H[venue]
    rows = []
    for ts_ms, raw_rate in ts_rate:
        upstream_ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()
        rows.append({
            "schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": _pair_candidate_id(asset, venue),
            "claim": f"funding_settlement:{asset}", "value": rate_per_8h(raw_rate, interval_h),
            "unit": "rate_per_8h", "window": None, "upstream_ts": upstream_ts, "fetched_at": now.isoformat(),
            "origin": f"venue:{venue}", "channel": evidence_contract.CHANNEL_OFFICIAL_API,
            "ref": f"{_ENDPOINTS[venue][0]}{_ENDPOINTS[venue][1]}#{ts_ms}", "raw_sha256": None,
            "backfill": backfill, "revises": None, "state": "MEASURED", "reason": None,
        })
    return rows


def _pair_candidate_id(asset: str, venue: str) -> str:
    key = contract.exposure_key("FUNDING_CAPTURE", f"perp:{asset}:{venue}", "cex")
    return contract.candidate_id(key)


def collect(now: datetime, client, *, assets=("BTC", "ETH"), backfill: bool = False,
           payloads: Optional[dict] = None) -> list:
    """``payloads``: inject ``{(venue, asset): parsed_payload}`` directly (tests/offline replay);
    ``None`` fetches each venue via ``client``. Every venue, every asset, kept separately — never
    reduced to a cross-venue median here (that reduction, if wanted for display, belongs to a
    DOWNSTREAM aggregate, not to what gets persisted)."""
    rows = []
    for asset in assets:
        for venue in VENUES:
            if payloads is not None:
                payload = payloads.get((venue, asset))
                if payload is None:
                    continue
            else:
                try:
                    payload = _fetch_payload(client, venue, asset)
                except Exception as exc:  # noqa: BLE001
                    rows.append({
                        "schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": _pair_candidate_id(asset, venue),
                        "claim": f"funding_settlement:{asset}", "value": None, "unit": "rate_per_8h",
                        "window": None, "upstream_ts": None, "fetched_at": now.isoformat(),
                        "origin": f"venue:{venue}", "channel": evidence_contract.CHANNEL_OFFICIAL_API,
                        "ref": f"{_ENDPOINTS[venue][0]}{_ENDPOINTS[venue][1]}", "raw_sha256": None,
                        "backfill": backfill, "revises": None, "state": "NOT_MEASURED",
                        "reason": f"{venue} fetch failed: {type(exc).__name__}: {exc}",
                    })
                    continue
            rows.extend(_venue_rows(venue, asset, payload, now=now, backfill=backfill))
    return rows


def settlement_day_summary(rows: list) -> dict:
    """``{(venue, asset, date): {"count", "expected", "partial"}}`` — the expected-settlement-count
    check (ADR-564 binding #8: "a day counts only with the venue's expected settlement count ...
    partial days are flagged")."""
    counts: dict = {}
    for r in rows:
        if r.get("state") != "MEASURED" or not isinstance(r.get("claim"), str) \
                or not r["claim"].startswith("funding_settlement:"):
            continue
        asset = r["claim"].split(":", 1)[1]
        venue = str(r.get("origin") or "").removeprefix("venue:")
        ts = contract.parse_ts(r.get("upstream_ts"))
        if ts is None or venue not in EXPECTED_SETTLEMENTS_PER_DAY:
            continue
        key = (venue, asset, ts.date().isoformat())
        counts.setdefault(key, 0)
        counts[key] += 1
    return {k: {"count": n, "expected": EXPECTED_SETTLEMENTS_PER_DAY[k[0]],
               "partial": n < EXPECTED_SETTLEMENTS_PER_DAY[k[0]]}
           for k, n in counts.items()}


def same_venue_conflict(rate_a_per_8h: float, rate_b_per_8h: float,
                        band_bps_8h: float = FUNDING_SAME_VENUE_BAND_BPS_8H) -> bool:
    """ADR-564 binding #8: conflicts are measured only BETWEEN CHANNELS of the SAME venue, by an
    ABSOLUTE band in bps/8h (never the 25%-relative tolerance ``contract.CONFLICT_TOLERANCE_REL``
    uses elsewhere — that tolerance does not fit a rate that is itself routinely near zero). True
    when the two channels disagree by more than the band."""
    diff_bps = abs(rate_a_per_8h - rate_b_per_8h) * 10_000.0
    return diff_bps > band_bps_8h
