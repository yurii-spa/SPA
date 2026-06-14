"""spa_core/price_feeds/protocol_direct_feed.py — Tier 1 Oracle (ADR-028 Phase 2).

Fetches APY directly from protocol-native APIs (Aave V3, Compound V3, Morpho Blue)
without relying on any aggregator. This is the highest-trust data source in the
3-tier oracle hierarchy defined by ADR-028.

Design principles
-----------------
* **stdlib only** — urllib.request, json, time, math, logging. Zero external deps.
* **Never raises** — all exceptions are caught; functions always return a value.
* **Read-only / advisory** — never modifies allocator, risk, or execution state.
* **LLM FORBIDDEN** in this module (CLAUDE.md: LLM_FORBIDDEN_AGENTS).
* **Timeout per request** — each adapter fetch is independently time-bounded.

Tier 1 adapters covered
-----------------------
  aave_v3      — Aave V3 Ethereum USDC reserve via The Graph subgraph.
  compound_v3  — Compound V3 USDC comet via v3-api.compound.finance.
  morpho_blue  — Morpho Blue USDC markets via blue-api.morpho.org/graphql.

APY units
---------
All public-facing APY values are expressed as **percent per year** (e.g. 4.8 = 4.8%/yr).
Internally:
  - Aave   liquidityRate is in RAY units (1e27, per second) → converted via compound formula.
  - Compound net_supply_apy is a decimal fraction (0.048) → multiplied by 100.
  - Morpho  state.supplyApy is a decimal fraction (0.048) → multiplied by 100.

Divergence alarm (ADR-028 §Consensus)
--------------------------------------
When Tier 1 (direct) and Tier 2 (DeFiLlama) readings for the same adapter differ by
> 150 bps, a WARNING is emitted. Tier 1 value is still used (it is authoritative by
definition), but the position is flagged so downstream consumers can note data_quality.

Public API
----------
fetch_apy_direct(adapter_id, timeout_seconds=8) -> float
    APY% for one T1 adapter; returns fallback_apy on any error.

fetch_all_direct(timeout_seconds=8) -> dict[str, float]
    APY% for all Tier-1 adapters. Returns {adapter_id: apy_float}.

merge_with_defi_llama(direct, llama) -> dict[str, float]
    Consensus merge: prefer direct (Tier 1) if available; else use DeFiLlama (Tier 2).
    Logs WARNING if divergence > DIVERGENCE_ALARM_BPS for any shared key.
"""
from __future__ import annotations

import json
import logging
import math
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Seconds in a year (365 days) — used for Aave RAY rate → APY conversion.
SECONDS_PER_YEAR: int = 365 * 24 * 3600  # 31_536_000

#: Aave liquidityRate unit divisor (RAY = 1e27).
RAY: float = 1e27

#: APY sanity bounds (% per year). Values outside this range are discarded → fallback.
APY_MIN_PCT: float = 0.01
APY_MAX_PCT: float = 100.0

#: Divergence alarm threshold: if |Tier1 − Tier2| > 150 bps, emit WARNING.
DIVERGENCE_ALARM_BPS: int = 150

_USER_AGENT: str = "SPA-PriceFeed/1.0 (protocol-direct-feed; contact=spa@localhost)"

# ── GraphQL query bodies (JSON-encoded) ───────────────────────────────────────
# Pre-built at module load so there is no runtime json.dumps overhead.

# USDC on Ethereum mainnet: 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
_AAVE_QUERY: str = json.dumps({
    "query": (
        "{ reserves("
        'where: {underlyingAsset: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"}'
        ") { liquidityRate symbol } }"
    )
})

# Morpho Blue: top-5 USDC loan-asset markets by TVL, ordered descending.
_MORPHO_QUERY: str = json.dumps({
    "query": (
        "{ markets("
        "  first: 5,"
        '  orderBy: "totalValueLockedUSD",'
        '  orderDirection: "desc"'
        ") { state { supplyApy } inputToken { symbol } } }"
    )
})

# ── Endpoint registry ─────────────────────────────────────────────────────────

#: Tier 1 adapter endpoints.
#:
#: Schema per entry::
#:
#:     url         — HTTPS endpoint (no API key required).
#:     method      — "get" | "graphql"  (graphql → POST with JSON body).
#:     query       — JSON-encoded GraphQL body string (method="graphql" only).
#:     parser      — key into _PARSERS dict.
#:     fallback_apy — % APY returned when endpoint is unavailable.
#:
DIRECT_ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "aave_v3": {
        "url": "https://api.thegraph.com/subgraphs/name/aave/protocol-v3",
        "method": "graphql",
        "query": _AAVE_QUERY,
        "parser": "aave",
        "fallback_apy": 3.5,
    },
    "compound_v3": {
        "url": (
            "https://v3-api.compound.finance/market/"
            "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        ),
        "method": "get",
        "parser": "compound",
        "fallback_apy": 4.0,
    },
    "morpho_blue": {
        "url": "https://blue-api.morpho.org/graphql",
        "method": "graphql",
        "query": _MORPHO_QUERY,
        "parser": "morpho",
        "fallback_apy": 4.8,
    },
}

#: Tuple of all Tier-1 adapter IDs (guaranteed stable order).
T1_ADAPTERS: tuple = tuple(DIRECT_ENDPOINTS.keys())  # ("aave_v3", "compound_v3", "morpho_blue")


# ── APY conversion helpers ────────────────────────────────────────────────────

def _ray_to_apy_pct(ray_rate_raw: Any) -> Optional[float]:
    """Convert Aave RAY-unit per-second rate to APY percent.

    Aave V3 ``liquidityRate`` is a per-second accumulation rate in RAY (1e27)::

        APY = (1 + rate/RAY)^SECONDS_PER_YEAR − 1

    Uses ``math.log1p`` + ``math.exp`` for numerical stability at tiny rates.

    Args:
        ray_rate_raw: Raw value from the API — int, float, or string representation
                      of the RAY-scaled integer (e.g. ``"31709791983764585603"``).

    Returns:
        APY as float percent (e.g. 3.5 for 3.5%/yr), or None if conversion fails.
    """
    try:
        ray_rate = float(ray_rate_raw)
        if ray_rate < 0:
            return None
        per_second = ray_rate / RAY
        # log1p is numerically stable for per_second ≈ 1e-9
        apy_pct = (math.exp(math.log1p(per_second) * SECONDS_PER_YEAR) - 1.0) * 100.0
        return apy_pct
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


# ── APY Parsers ───────────────────────────────────────────────────────────────

def _parse_aave(payload: dict) -> Optional[float]:
    """Parse Aave V3 GraphQL response → APY percent.

    Expected shape::

        {
          "data": {
            "reserves": [
              {"liquidityRate": "31709791983764585603", "symbol": "USDC"}
            ]
          }
        }

    ``liquidityRate`` is a RAY-scaled (1e27) per-second rate string.

    Returns:
        APY% float, or None if parsing fails or value is out of bounds.
    """
    try:
        reserves = payload.get("data", {}).get("reserves", [])
        if not isinstance(reserves, list) or not reserves:
            logger.debug("protocol_direct_feed: aave_parser — empty reserves list")
            return None
        rate_raw = reserves[0].get("liquidityRate")
        if rate_raw is None:
            logger.debug("protocol_direct_feed: aave_parser — liquidityRate missing")
            return None
        apy = _ray_to_apy_pct(rate_raw)
        if apy is None or apy < APY_MIN_PCT or apy > APY_MAX_PCT:
            logger.debug(
                "protocol_direct_feed: aave_parser — APY out of bounds: %s", apy
            )
            return None
        return apy
    except Exception as exc:  # noqa: BLE001
        logger.debug("protocol_direct_feed: aave_parser error: %s", exc)
        return None


def _parse_compound(payload: dict) -> Optional[float]:
    """Parse Compound V3 REST response → APY percent.

    Supported shapes::

        {"market": {"net_supply_apy": "0.0481", ...}}  # wrapped
        {"net_supply_apy": "0.0481", ...}              # flat
        {"net_supply_apy": 4.81, ...}                  # already in percent

    ``net_supply_apy`` is either a decimal fraction (0.048 → 4.8%) or a
    percent (4.8). Values < 1.0 are treated as fractions and multiplied by 100.

    Returns:
        APY% float, or None if parsing fails or value is out of bounds.
    """
    try:
        # Support both wrapped {"market": {...}} and flat response shapes
        market = payload.get("market", payload)
        if not isinstance(market, dict):
            market = payload

        apy_raw = (
            market.get("net_supply_apy")
            or market.get("supply_apy")
            or market.get("supplyApy")
        )
        if apy_raw is None:
            logger.debug(
                "protocol_direct_feed: compound_parser — net_supply_apy not found"
            )
            return None

        apy_f = float(apy_raw)
        # Decimal fraction → percent
        if abs(apy_f) < 1.0:
            apy_f *= 100.0

        if apy_f < APY_MIN_PCT or apy_f > APY_MAX_PCT:
            logger.debug(
                "protocol_direct_feed: compound_parser — APY out of bounds: %s", apy_f
            )
            return None
        return apy_f
    except (ValueError, TypeError) as exc:
        logger.debug("protocol_direct_feed: compound_parser error: %s", exc)
        return None


def _parse_morpho(payload: dict) -> Optional[float]:
    """Parse Morpho Blue GraphQL response → APY percent.

    Expected shape::

        {
          "data": {
            "markets": [
              {"state": {"supplyApy": 0.048}, "inputToken": {"symbol": "USDC"}}
            ]
          }
        }

    ``supplyApy`` is a decimal fraction (0.048 → 4.8%).

    Uses the first market in the list (caller orders by TVL descending).

    Returns:
        APY% float, or None if parsing fails or value is out of bounds.
    """
    try:
        markets = payload.get("data", {}).get("markets", [])
        if not isinstance(markets, list) or not markets:
            logger.debug("protocol_direct_feed: morpho_parser — empty markets list")
            return None
        state = markets[0].get("state") or {}
        apy_raw = state.get("supplyApy")
        if apy_raw is None:
            logger.debug("protocol_direct_feed: morpho_parser — supplyApy missing")
            return None

        apy_f = float(apy_raw)
        # Decimal fraction → percent
        if abs(apy_f) < 1.0:
            apy_f *= 100.0

        if apy_f < APY_MIN_PCT or apy_f > APY_MAX_PCT:
            logger.debug(
                "protocol_direct_feed: morpho_parser — APY out of bounds: %s", apy_f
            )
            return None
        return apy_f
    except (ValueError, TypeError) as exc:
        logger.debug("protocol_direct_feed: morpho_parser error: %s", exc)
        return None


#: Dispatch table mapping parser name → parser function.
_PARSERS: Dict[str, Any] = {
    "aave": _parse_aave,
    "compound": _parse_compound,
    "morpho": _parse_morpho,
}


# ── Internal HTTP helpers ─────────────────────────────────────────────────────

def _http_get(url: str, timeout: int) -> Optional[dict]:
    """HTTP GET → parsed JSON dict, or None on any error.

    Never raises. All network and JSON errors are caught and logged at DEBUG.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            logger.debug("protocol_direct_feed: GET %s — response is not a dict", url)
            return None
        return payload
    except urllib.error.URLError as exc:
        logger.debug("protocol_direct_feed: GET %s URLError: %s", url, exc)
    except json.JSONDecodeError as exc:
        logger.debug("protocol_direct_feed: GET %s JSONDecodeError: %s", url, exc)
    except OSError as exc:
        logger.debug("protocol_direct_feed: GET %s OSError: %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("protocol_direct_feed: GET %s unexpected error: %s", url, exc)
    return None


def _http_post_graphql(url: str, query_json: str, timeout: int) -> Optional[dict]:
    """HTTP POST with JSON body (GraphQL) → parsed JSON dict, or None on any error.

    Never raises. All network and JSON errors are caught and logged at DEBUG.
    """
    try:
        body = query_json.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            logger.debug("protocol_direct_feed: POST %s — response is not a dict", url)
            return None
        return payload
    except urllib.error.URLError as exc:
        logger.debug("protocol_direct_feed: POST %s URLError: %s", url, exc)
    except json.JSONDecodeError as exc:
        logger.debug("protocol_direct_feed: POST %s JSONDecodeError: %s", url, exc)
    except OSError as exc:
        logger.debug("protocol_direct_feed: POST %s OSError: %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("protocol_direct_feed: POST %s unexpected error: %s", url, exc)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_apy_direct(adapter_id: str, timeout_seconds: int = 8) -> float:
    """Fetch APY% from a protocol direct API. Never raises.

    Implements the Tier 1 fetch for a single adapter. On any failure — network
    error, unexpected response shape, APY out of bounds — returns the configured
    ``fallback_apy`` for that adapter (Tier 3 static value).

    Args:
        adapter_id: Key from DIRECT_ENDPOINTS (``"aave_v3"``, ``"compound_v3"``,
                    or ``"morpho_blue"``).
        timeout_seconds: Per-request HTTP timeout. Independent for each adapter.

    Returns:
        APY as float percent (e.g. 4.8 for 4.8%/yr).
        Returns ``0.0`` if adapter_id is not in DIRECT_ENDPOINTS.
        Never raises.
    """
    entry = DIRECT_ENDPOINTS.get(adapter_id)
    if entry is None:
        logger.warning(
            "protocol_direct_feed: unknown adapter_id=%r, returning 0.0", adapter_id
        )
        return 0.0

    fallback: float = entry["fallback_apy"]
    url: str = entry["url"]
    method: str = entry.get("method", "get")
    parser_name: Optional[str] = entry.get("parser")
    parser_fn = _PARSERS.get(parser_name) if parser_name else None

    try:
        t0 = time.monotonic()

        if method == "graphql":
            query_json: str = entry.get("query", "{}")
            payload = _http_post_graphql(url, query_json, timeout=timeout_seconds)
        else:
            payload = _http_get(url, timeout=timeout_seconds)

        elapsed = time.monotonic() - t0

        if payload is None:
            logger.debug(
                "protocol_direct_feed: %s — endpoint unavailable (%.2fs), "
                "fallback=%.2f%%",
                adapter_id, elapsed, fallback,
            )
            return fallback

        if parser_fn is None:
            logger.warning(
                "protocol_direct_feed: %s — no parser configured, fallback=%.2f%%",
                adapter_id, fallback,
            )
            return fallback

        apy = parser_fn(payload)
        if apy is None:
            logger.debug(
                "protocol_direct_feed: %s — parser returned None (%.2fs), "
                "fallback=%.2f%%",
                adapter_id, elapsed, fallback,
            )
            return fallback

        logger.info(
            "protocol_direct_feed: %s → %.4f%% (direct, %.2fs)",
            adapter_id, apy, elapsed,
        )
        return apy

    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders
        logger.warning(
            "protocol_direct_feed: fetch_apy_direct(%s) unexpected error: %s, "
            "fallback=%.2f%%",
            adapter_id, exc, fallback,
        )
        return fallback


def fetch_all_direct(timeout_seconds: int = 8) -> Dict[str, float]:
    """Fetch APY% for all Tier-1 adapters (aave_v3, compound_v3, morpho_blue).

    Each adapter is fetched independently; a failure for one does not affect
    others. Returns a complete dict even if all adapters fall back to static values.

    Args:
        timeout_seconds: Per-request HTTP timeout, applied to each adapter call.

    Returns:
        ``{adapter_id: apy_float}`` for all entries in DIRECT_ENDPOINTS.
        Guaranteed to contain exactly the keys in T1_ADAPTERS.
        Never raises.
    """
    results: Dict[str, float] = {}
    for adapter_id in DIRECT_ENDPOINTS:
        results[adapter_id] = fetch_apy_direct(adapter_id, timeout_seconds=timeout_seconds)

    logger.info(
        "protocol_direct_feed: fetch_all_direct — %d adapters fetched: %s",
        len(results),
        {k: f"{v:.2f}%" for k, v in results.items()},
    )
    return results


def merge_with_defi_llama(
    direct: Dict[str, float],
    llama: Dict[str, float],
) -> Dict[str, float]:
    """Consensus merge: Tier 1 preferred over Tier 2. Never raises.

    Merge rules (ADR-028 §Consensus):

    1. Start with all keys from ``llama`` (Tier 2 baseline).
    2. For every key in ``direct`` (Tier 1): overwrite with the direct value.
    3. If a key is in **both** sources and ``|direct − llama| > 150 bps``:
       emit a WARNING. The Tier 1 value is still used.
    4. Keys only in ``llama`` (not T1) pass through unchanged.

    Args:
        direct: Output of :func:`fetch_all_direct` — ``{adapter_id: apy%}``.
        llama:  Output of DeFiLlama ``fetch_apy_map`` — ``{adapter_id: apy%}``.

    Returns:
        Merged ``{adapter_id: apy_float}`` dict. Never raises.
    """
    try:
        # Tier 2 baseline
        merged: Dict[str, float] = dict(llama)

        for adapter_id, direct_apy in direct.items():
            llama_apy = llama.get(adapter_id)

            if llama_apy is not None:
                delta_bps = abs(direct_apy - llama_apy) * 100.0  # % → bps
                if delta_bps > DIVERGENCE_ALARM_BPS:
                    logger.warning(
                        "protocol_direct_feed: DIVERGENCE ALARM [%s] — "
                        "direct=%.4f%% llama=%.4f%% delta=%.1f bps "
                        "(threshold=%d bps)",
                        adapter_id,
                        direct_apy,
                        llama_apy,
                        delta_bps,
                        DIVERGENCE_ALARM_BPS,
                    )
                else:
                    logger.debug(
                        "protocol_direct_feed: %s — direct=%.4f%% llama=%.4f%% "
                        "delta=%.1f bps (OK)",
                        adapter_id, direct_apy, llama_apy, delta_bps,
                    )

            # Tier 1 wins regardless of divergence
            merged[adapter_id] = direct_apy

        return merged

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "protocol_direct_feed: merge_with_defi_llama unexpected error: %s", exc
        )
        # Belt-and-suspenders: return best-effort merge
        result = dict(llama)
        result.update(direct)
        return result
