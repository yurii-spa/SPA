"""
Pendle Finance PT (Principal Token) Read-Only APY Feed.

Fetches live PT market data directly from the Pendle API v2, filters to
SPA-eligible stablecoin markets, and returns APY/TVL for the allocator.

Tier   : T2 (yield source, no T1 guarantees)
Domain : READ-ONLY — no on-chain execution, no state writes.
Source : https://api-v2.pendle.finance/core/v1/{chainId}/markets
stdlib : urllib.request only — zero external dependencies.

MP-201 — Pendle PT read-only APY feed (phase 2, apy-gap epic).
"""
from __future__ import annotations

import datetime
import json
import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── API constants ─────────────────────────────────────────────────────────────
PENDLE_API_BASE = "https://api-v2.pendle.finance/core/v1"
PENDLE_CHAIN_ID = 1          # Ethereum mainnet
PENDLE_REQUEST_TIMEOUT = 10  # seconds
PENDLE_MAX_RETRIES = 1       # one retry after first failure
PENDLE_RETRY_DELAY = 2.0     # seconds between retries

# ── Filter defaults ───────────────────────────────────────────────────────────
PENDLE_MIN_TVL_USD = 5_000_000.0   # matches RiskPolicy TVL floor
PENDLE_MAX_DAYS_TO_MATURITY = 365  # no long-dated positions
PENDLE_MIN_DAYS_TO_MATURITY = 7    # avoid illiquidity at near-expiry

# Symbols/substrings that identify a stablecoin/USD underlying
_STABLECOIN_KEYWORDS = frozenset(
    ["usd", "usdc", "usde", "usdt", "dai", "gho", "frax", "susd", "crvusd"]
)

# Fallback values when the live API is unavailable
_FALLBACK_APY = 7.0
_FALLBACK_DICT: dict = {
    "id": "pendle_pt",
    "name": "Pendle PT",
    "tier": "T2",
    "apy": _FALLBACK_APY,
    "tvl_usd": 0.0,
    "is_available": False,
    "source": "fallback",
    "details": {"reason": "api_unavailable"},
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PendleMarketData:
    """Normalised snapshot of one Pendle PT market."""

    market_address: str
    name: str                   # e.g. "PT-sUSDe-27MAR2025"
    underlying_asset: str       # e.g. "sUSDe"
    pt_apy: float               # fixed APY of holding PT to maturity (%)
    underlying_apy: float       # current yield of underlying (%)
    maturity_date: str          # ISO date string, e.g. "2025-03-27"
    days_to_maturity: int
    tvl_usd: float
    is_expired: bool
    liquidity_usd: float        # liquidity in the AMM pool
    implied_apy: float          # market-implied APY from AMM price (%)
    # optional extra metadata
    chain_id: int = PENDLE_CHAIN_ID
    extra: dict = field(default_factory=dict)


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = PENDLE_REQUEST_TIMEOUT) -> dict:
    """
    Perform a GET request and return parsed JSON.

    Raises urllib.error.URLError / urllib.error.HTTPError / ValueError on failure.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SPA-Read-Adapter/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw)


def _http_get_with_retry(
    url: str,
    timeout: int = PENDLE_REQUEST_TIMEOUT,
    max_retries: int = PENDLE_MAX_RETRIES,
    retry_delay: float = PENDLE_RETRY_DELAY,
) -> dict:
    """Wrapper that retries once on network/HTTP errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return _http_get(url, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.debug(
                    "pendle_pt: attempt %d failed (%s), retrying in %.1fs",
                    attempt + 1, exc, retry_delay,
                )
                time.sleep(retry_delay)
    raise last_exc  # type: ignore[misc]


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _safe_float(value: object, fallback: float = 0.0) -> float:
    """Coerce a value (str/int/float/None) to a FINITE float without raising.

    ``float("NaN")`` / ``float("inf")`` and ``1e400`` do not raise — they yield
    non-finite floats. Returning those would propagate a fabricated/unbounded
    value (e.g. NaN tvl) into allocation. Fail-CLOSED: non-finite → ``fallback``.
    """
    if value is None:
        return fallback
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(result):
        return fallback
    return result


def _parse_maturity(expiry_str: str) -> Optional[datetime.date]:
    """
    Parse an ISO-8601 expiry string from the Pendle API.

    Accepts both full datetime strings ("2025-03-27T00:00:00.000Z") and
    plain date strings ("2025-03-27").
    """
    if not expiry_str:
        return None
    try:
        # Strip time component if present
        date_part = expiry_str[:10]
        return datetime.date.fromisoformat(date_part)
    except (ValueError, TypeError):
        return None


def _days_to_maturity(maturity: Optional[datetime.date]) -> int:
    """Days from today until maturity; 0 if maturity is in the past."""
    if maturity is None:
        return 0
    delta = (maturity - datetime.date.today()).days
    return max(delta, 0)


def _is_stablecoin(symbol: str) -> bool:
    """Return True if the asset symbol suggests a stablecoin/USD peg."""
    sym_lower = symbol.lower()
    return any(kw in sym_lower for kw in _STABLECOIN_KEYWORDS)


def _parse_market(raw: dict) -> Optional[PendleMarketData]:
    """
    Parse a single market dict from the Pendle API /markets response.

    Returns None if any required field is missing or unparseable.
    """
    try:
        address: str = raw.get("address", "")
        if not address:
            return None

        # PT info
        pt_info: dict = raw.get("pt") or {}
        name: str = pt_info.get("symbol") or raw.get("name") or address

        # Underlying asset
        underlying_info: dict = raw.get("underlyingAsset") or {}
        underlying_asset: str = underlying_info.get("symbol") or ""

        # Expiry / maturity
        expiry_str: str = raw.get("expiry") or ""
        maturity = _parse_maturity(expiry_str)
        maturity_date_str = maturity.isoformat() if maturity else ""
        days_left = _days_to_maturity(maturity)

        # Liquidity — Pendle API returns nested {"usd": ...} or plain float.
        # USD pool size can never be negative; floor at 0 (fail-closed) so a
        # malformed negative value never leaks downstream as a bound.
        liq_raw = raw.get("liquidity") or {}
        if isinstance(liq_raw, dict):
            liquidity_usd = max(0.0, _safe_float(liq_raw.get("usd")))
        else:
            liquidity_usd = max(0.0, _safe_float(liq_raw))

        # TVL — the v2 /markets endpoint returns ``tvl: null``; the pool's USD
        # value lives in ``liquidity.usd`` (these are AMM pools, so AMM liquidity
        # is the pool TVL). Use ``tvl`` when present, else fall back to liquidity.
        tvl_raw = raw.get("tvl") or {}
        if isinstance(tvl_raw, dict):
            tvl_usd = max(0.0, _safe_float(tvl_raw.get("usd")))
        else:
            tvl_usd = max(0.0, _safe_float(tvl_raw))
        if tvl_usd <= 0.0:
            tvl_usd = liquidity_usd

        # APY values — Pendle returns decimals (0.089 = 8.9%); we store %.
        # ``_pct`` re-checks finiteness after the *100 scale: a huge-but-finite
        # input (e.g. 1e308) overflows to inf when multiplied, which would leak
        # a non-finite "APY". Fail-closed → 0.0 on any non-finite product.
        def _pct(dec: float) -> float:
            scaled = dec * 100
            return round(scaled, 4) if math.isfinite(scaled) else 0.0

        implied_apy_dec = _safe_float(raw.get("impliedApy"))
        underlying_apy_dec = _safe_float(raw.get("underlyingInterestApy"))

        pt_apy = _pct(implied_apy_dec)
        underlying_apy = _pct(underlying_apy_dec)
        implied_apy = _pct(implied_apy_dec)

        is_expired: bool = bool(raw.get("isExpired", False))

        return PendleMarketData(
            market_address=address,
            name=name,
            underlying_asset=underlying_asset,
            pt_apy=pt_apy,
            underlying_apy=underlying_apy,
            maturity_date=maturity_date_str,
            days_to_maturity=days_left,
            tvl_usd=tvl_usd,
            is_expired=is_expired,
            liquidity_usd=liquidity_usd,
            implied_apy=implied_apy,
            chain_id=raw.get("chainId", PENDLE_CHAIN_ID),
            extra={},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("pendle_pt: failed to parse market %s — %s", raw.get("address"), exc)
        return None


# ── Adapter ───────────────────────────────────────────────────────────────────

class PendlePTAdapter:
    """
    Read-only adapter for Pendle Finance PT yields.

    Queries the Pendle API v2, filters to SPA-eligible stablecoin markets,
    and returns structured APY/TVL data for the SPA allocator.

    This class is strictly read-only: it never touches capital and must
    NOT be imported from execution/, feed_health/, or risk agents.
    """

    def __init__(
        self,
        chain_id: int = PENDLE_CHAIN_ID,
        timeout: int = PENDLE_REQUEST_TIMEOUT,
        max_retries: int = PENDLE_MAX_RETRIES,
    ) -> None:
        self.chain_id = chain_id
        self.timeout = timeout
        self.max_retries = max_retries

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_markets_url(self) -> str:
        return f"{PENDLE_API_BASE}/{self.chain_id}/markets"

    def _fetch_markets_raw(self) -> list[dict]:
        """
        GET /markets and return the raw results list.

        Handles pagination via 'total'/'limit' if needed; for SPA we only
        need enough markets to find the best stablecoin PT, so the first
        page (default limit from API, typically 20–50) is sufficient.
        Returns [] on any network or parse failure.
        """
        url = self._build_markets_url()
        try:
            data = _http_get_with_retry(url, timeout=self.timeout, max_retries=self.max_retries)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pendle_pt: failed to fetch markets — %s", exc)
            return []

        # Pendle API wraps results in {"results": [...]} or {"data": [...]}
        if isinstance(data, dict):
            results = data.get("results") or data.get("data") or []
        elif isinstance(data, list):
            results = data
        else:
            results = []

        if not isinstance(results, list):
            logger.warning("pendle_pt: unexpected markets response type %s", type(results))
            return []

        logger.debug("pendle_pt: fetched %d raw markets from API", len(results))
        return results

    # ── Public interface ──────────────────────────────────────────────────────

    def get_top_markets(
        self,
        min_tvl_usd: float = PENDLE_MIN_TVL_USD,
        max_days_to_maturity: int = PENDLE_MAX_DAYS_TO_MATURITY,
        min_days_to_maturity: int = PENDLE_MIN_DAYS_TO_MATURITY,
        stablecoin_only: bool = True,
    ) -> list[PendleMarketData]:
        """
        Return SPA-eligible Pendle PT markets sorted by pt_apy descending.

        Filters applied:
          - not expired
          - TVL >= min_tvl_usd
          - days_to_maturity in [min_days_to_maturity, max_days_to_maturity]
          - stablecoin underlying (if stablecoin_only=True)
          - pt_apy > 0

        Returns [] if no eligible markets or if the API is unavailable.
        """
        raw_list = self._fetch_markets_raw()
        eligible: list[PendleMarketData] = []

        for raw in raw_list:
            market = _parse_market(raw)
            if market is None:
                continue

            # Gate 1: not expired
            if market.is_expired:
                continue

            # Gate 2: TVL floor
            if market.tvl_usd < min_tvl_usd:
                continue

            # Gate 3: maturity window
            if market.days_to_maturity < min_days_to_maturity:
                continue
            if market.days_to_maturity > max_days_to_maturity:
                continue

            # Gate 4: stablecoin filter
            if stablecoin_only and not _is_stablecoin(market.underlying_asset):
                continue

            # Gate 5: positive APY (sanity)
            if market.pt_apy <= 0:
                continue

            eligible.append(market)

        eligible.sort(key=lambda m: m.pt_apy, reverse=True)
        logger.info(
            "pendle_pt: %d eligible stablecoin PT markets (TVL≥$%.0fM, "
            "maturity %d–%dd)",
            len(eligible),
            min_tvl_usd / 1_000_000,
            min_days_to_maturity,
            max_days_to_maturity,
        )
        return eligible

    def get_best_market(self, **kwargs) -> Optional[PendleMarketData]:
        """Return the single best PT market by pt_apy, or None if none qualify."""
        markets = self.get_top_markets(**kwargs)
        return markets[0] if markets else None

    @staticmethod
    def to_adapter_format(market: PendleMarketData) -> dict:
        """
        Convert a PendleMarketData into the SPA standard adapter dict:

        {
            "id":           "pendle_pt",
            "name":         "Pendle PT",
            "tier":         "T2",
            "apy":          <pt_apy as %>,
            "tvl_usd":      <float>,
            "is_available": <not expired>,
            "source":       "pendle_api",
            "details": {
                "market_address":  "0x...",
                "underlying":      "sUSDe",
                "maturity_date":   "2025-03-27",
                "days_to_maturity": 90,
                "liquidity_usd":   1234567.0,
                "implied_apy":     8.9,
                "underlying_apy":  14.5,
            }
        }
        """
        return {
            "id": "pendle_pt",
            "name": "Pendle PT",
            "tier": "T2",
            "apy": market.pt_apy,
            "tvl_usd": market.tvl_usd,
            "is_available": not market.is_expired,
            "source": "pendle_api",
            "details": {
                "market_address": market.market_address,
                "underlying": market.underlying_asset,
                "maturity_date": market.maturity_date,
                "days_to_maturity": market.days_to_maturity,
                "liquidity_usd": market.liquidity_usd,
                "implied_apy": market.implied_apy,
                "underlying_apy": market.underlying_apy,
                "pt_name": market.name,
            },
        }


# ── Module-level entry point ──────────────────────────────────────────────────

def get_pendle_apy(fallback_apy: float = _FALLBACK_APY) -> dict:
    """
    Main entry point for the SPA orchestrator.

    Returns the SPA adapter-format dict for the best eligible Pendle PT
    stablecoin market.  Falls back gracefully if the API is unavailable
    or no eligible market is found.

    Return shape:
        {
            "id":           "pendle_pt",
            "name":         "Pendle PT",
            "tier":         "T2",
            "apy":          <float, %>    ← from live API or fallback_apy
            "tvl_usd":      <float>,
            "is_available": <bool>,
            "source":       "pendle_api" | "fallback",
            "details":      {...},
        }
    """
    try:
        adapter = PendlePTAdapter()
        best = adapter.get_best_market()
        if best is None:
            logger.info("pendle_pt: no eligible markets found; using fallback APY=%.2f%%", fallback_apy)
            return dict(_FALLBACK_DICT, apy=fallback_apy)

        result = PendlePTAdapter.to_adapter_format(best)
        logger.info(
            "pendle_pt: best market=%s APY=%.2f%% TVL=$%.1fM maturity=%s",
            best.name,
            best.pt_apy,
            best.tvl_usd / 1_000_000,
            best.maturity_date,
        )
        return result

    except Exception as exc:  # noqa: BLE001
        logger.warning("pendle_pt: get_pendle_apy failed (%s); using fallback", exc)
        return dict(_FALLBACK_DICT, apy=fallback_apy)
