"""
Pendle PT Fetcher — fixed-rate yield positions for SPA.
Only fetches PT (Principal Tokens) — NOT YT (too risky for SPA's mandate).

PT characteristics:
- Fixed APY locked at entry price
- Redeems at $1.00 on maturity date
- Liquidity risk: less liquid than lending pools, but acceptable for 60-90 day holds
- Platforms: Arbitrum (main), Ethereum

SPA inclusion criteria for Pendle PT:
- Underlying asset: USDC, USDT, or sUSDE (stable only)
- Min APY: 6% (must justify T2 risk premium over T1 baseline)
- Min TVL: $5M
- Max maturity: 180 days (no long-dated positions)
- Min maturity remaining: 14 days (avoid illiquidity at expiry)

Whitelist reference: T2-02, Pendle, Ethereum/Arbitrum, PT-stablecoin
ADR: ADR_002_pendle_pt_integration.md (PROPOSED — paper test only until approved)
"""

import json
import datetime
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

DEFILLAMA_YIELDS_URL = "https://yields.llama.fi/pools"

# Stable underlying tokens SPA accepts for Pendle PT
PENDLE_STABLE_UNDERLYING = ["usdc", "usdt", "susde", "usde", "dai", "frax"]

# SPA inclusion criteria
PENDLE_MIN_APY = 6.0          # % — must justify T2 risk over T1 baseline (~4%)
PENDLE_MIN_TVL = 5_000_000    # $5M minimum liquidity
PENDLE_MAX_DAYS_TO_MATURITY = 180   # no long-dated positions
PENDLE_MIN_DAYS_TO_MATURITY = 14    # avoid illiquidity near expiry
PENDLE_TOP_N = 5              # max pools returned (ranked by APY)

# Month abbreviation map for symbol date parsing (e.g. "26DEC2026", "MAR2026")
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_maturity_from_symbol(symbol: str) -> Optional[datetime.date]:
    """
    Attempt to parse a maturity date from a Pendle PT symbol string.

    DeFiLlama symbol formats seen in the wild:
      PT-USDC-26DEC2026      → 2026-12-26
      PT-sUSDe-27MAR2025     → 2025-03-27
      PT-weETH-27JUN2024     → 2024-06-27
      PT-USDC-30NOV2026      → 2026-11-30

    Returns None if no date can be parsed (caller will use default).
    """
    # Strip "PT-" prefix, uppercase, then scan the tail for a date token
    cleaned = symbol.upper()
    # Pattern: optional 2-digit day + 3-letter month + 4-digit year
    # e.g. "26DEC2026" or "DEC2026"
    pattern = re.compile(r'(\d{1,2})?([A-Z]{3})(\d{4})')
    matches = pattern.findall(cleaned)
    if not matches:
        return None

    # Use the last match (most specific)
    day_str, mon_str, year_str = matches[-1]
    month = _MONTH_MAP.get(mon_str.lower())
    if not month:
        return None
    try:
        year = int(year_str)
        day = int(day_str) if day_str else 1
        return datetime.date(year, month, day)
    except (ValueError, TypeError):
        return None


def _days_to_maturity(maturity: Optional[datetime.date]) -> Optional[int]:
    """Return days remaining until maturity, or None if unknown."""
    if maturity is None:
        return None
    return (maturity - datetime.date.today()).days


class PendleFetcher:
    """
    Fetches Pendle V2 PT pools from DeFiLlama and filters to SPA-eligible ones.

    Usage:
        f = PendleFetcher()
        pools = f.fetch_pt_pools()   # list of dicts, ranked by APY desc
        best  = f.get_best_pt()      # top pool or None
    """

    def fetch_pt_pools(self) -> list[dict]:
        """
        Fetch all Pendle PT pools from DeFiLlama.

        Returns list of SPA-eligible pools with metadata.
        Never raises — returns [] on any network or parse error.

        Each returned pool dict contains:
            pool_id, protocol, symbol, chain, tier, apy, tvl_usd,
            asset, special, underlying_symbol, project,
            maturity_date (str YYYY-MM-DD or None),
            days_to_maturity (int or None)
        """
        try:
            from data_pipeline.defillama_fetcher import retry_request
            data_bytes, err = retry_request(DEFILLAMA_YIELDS_URL, timeout=15, max_attempts=3, backoff=2.0)
            if err is not None:
                log.warning(f"PendleFetcher.fetch_pt_pools: all retries failed — {err}")
                return []
            data = json.loads(data_bytes)
            pools = data.get("data", [])
            log.info(f"PendleFetcher: fetched {len(pools)} total pools from DeFiLlama")
            return self._filter_pt_pools(pools)
        except Exception as e:
            log.warning(f"PendleFetcher.fetch_pt_pools error: {e}")
            return []

    def _filter_pt_pools(self, pools: list[dict]) -> list[dict]:
        """
        Filter the raw DeFiLlama pool list to SPA-eligible Pendle PT pools.

        Criteria applied (all must pass):
          1. project == "pendle-v2"
          2. symbol starts with "PT-" (case-insensitive)
          3. stable underlying: symbol contains one of PENDLE_STABLE_UNDERLYING
          4. apy >= PENDLE_MIN_APY (6%)
          5. tvlUsd >= PENDLE_MIN_TVL ($5M)
          6. chain in (arbitrum, ethereum)
          7. maturity: if parseable, must be 14–180 days from today
        """
        today = datetime.date.today()
        eligible = []

        for p in pools:
            # --- Gate 1: Pendle V2 only ---
            if p.get("project") != "pendle-v2":
                continue

            # --- Gate 2: PT only (not YT, not LP) ---
            symbol_raw = p.get("symbol") or ""
            symbol_lower = symbol_raw.lower()
            if not symbol_lower.startswith("pt-"):
                continue

            # --- Gate 3: Stable underlying ---
            is_stable = any(s in symbol_lower for s in PENDLE_STABLE_UNDERLYING)
            if not is_stable:
                continue

            # --- Gate 4: APY threshold ---
            apy = p.get("apy") or 0.0
            try:
                apy = float(apy)
            except (TypeError, ValueError):
                apy = 0.0
            if apy < PENDLE_MIN_APY:
                continue

            # --- Gate 5: TVL threshold ---
            tvl = p.get("tvlUsd") or 0.0
            try:
                tvl = float(tvl)
            except (TypeError, ValueError):
                tvl = 0.0
            if tvl < PENDLE_MIN_TVL:
                continue

            # --- Gate 6: Chain whitelist ---
            chain = (p.get("chain") or "").lower()
            if chain not in ("arbitrum", "ethereum"):
                continue

            # --- Gate 7: Maturity window (best-effort) ---
            maturity_date = _parse_maturity_from_symbol(symbol_raw)
            days_left = _days_to_maturity(maturity_date)

            if days_left is not None:
                if days_left < PENDLE_MIN_DAYS_TO_MATURITY:
                    log.debug(
                        f"PendleFetcher: skip {symbol_raw} — "
                        f"only {days_left}d to maturity (min {PENDLE_MIN_DAYS_TO_MATURITY}d)"
                    )
                    continue
                if days_left > PENDLE_MAX_DAYS_TO_MATURITY:
                    log.debug(
                        f"PendleFetcher: skip {symbol_raw} — "
                        f"{days_left}d to maturity exceeds max {PENDLE_MAX_DAYS_TO_MATURITY}d"
                    )
                    continue

            eligible.append({
                "pool_id":          p.get("pool"),
                "protocol":         "Pendle PT",
                "symbol":           symbol_raw,
                "chain":            chain,
                "tier":             "T2",
                "apy":              round(apy, 4),
                "tvl_usd":          round(tvl, 2),
                "asset":            "PT-STABLE",
                "special":          "fixed_rate",
                "underlying_symbol": symbol_lower,
                "project":          "pendle-v2",
                "maturity_date":    maturity_date.isoformat() if maturity_date else None,
                "days_to_maturity": days_left,
            })

        # Sort by APY descending, return top N
        eligible.sort(key=lambda x: x["apy"], reverse=True)
        result = eligible[:PENDLE_TOP_N]

        log.info(
            f"PendleFetcher: {len(eligible)} eligible PT pools found, "
            f"returning top {len(result)}"
        )
        return result

    def filter_pools(self, raw_pools: list[dict]) -> list[dict]:
        """
        Public wrapper for _filter_pt_pools — filters a raw DeFiLlama pool list
        to SPA-eligible Pendle PT pools.  Useful for unit testing with mock data.

        Args:
            raw_pools: list of pool dicts in DeFiLlama /pools format

        Returns:
            Filtered + sorted list of eligible pools (same shape as fetch_pt_pools)
        """
        return self._filter_pt_pools(raw_pools)

    def get_best_pt(self) -> Optional[dict]:
        """
        Returns the single best eligible PT pool by APY, or None if none qualify.

        This is the primary entry point for the paper trading engine:
            best = PendleFetcher().get_best_pt()
            if best:
                size = pendle_allocation_size(capital, best["apy"])
        """
        pools = self.fetch_pt_pools()
        if pools:
            log.info(
                f"PendleFetcher.get_best_pt: best pool = {pools[0]['symbol']} "
                f"APY={pools[0]['apy']}% TVL=${pools[0]['tvl_usd']:,.0f}"
            )
        return pools[0] if pools else None
