"""
MP-785: ProtocolLiquidityDepthAnalyzer
Analyzes available liquidity depth for position entry/exit.

CLI:
    python3 -m spa_core.analytics.protocol_liquidity_depth_analyzer --check
    python3 -m spa_core.analytics.protocol_liquidity_depth_analyzer --run
    python3 -m spa_core.analytics.protocol_liquidity_depth_analyzer --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save
from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FILE_NAME = "liquidity_depth_log.json"
LOG_CAP = 100

DEPTH_DEEP = "DEEP"
DEPTH_ADEQUATE = "ADEQUATE"
DEPTH_THIN = "THIN"
DEPTH_INSUFFICIENT = "INSUFFICIENT"

# Depth-within band tolerance
BAND_PCT = 0.01  # 1% of mid price


# ---------------------------------------------------------------------------
# ProtocolLiquidityDepthAnalyzer
# ---------------------------------------------------------------------------


class ProtocolLiquidityDepthAnalyzer(BaseAnalytics):
    OUTPUT_PATH = "data/protocol_liquidity_depth.json"
    """Analyzes available liquidity depth for position entry/exit.

    Parameters
    ----------
    data_dir : str
        Directory where ``liquidity_depth_log.json`` is written.
    """

    def __init__(self, data_dir: str = "") -> None:
        self._data_dir = data_dir
        self._last_result: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, orderbook_data: dict[str, Any]) -> dict[str, Any]:
        """Analyze orderbook depth for a single protocol.

        Parameters
        ----------
        orderbook_data : dict
            Required keys:
                protocol        str              – protocol name
                bids            list[(price, size_usd)] – bid levels
                asks            list[(price, size_usd)] – ask levels
                mid_price       float            – reference mid price
                position_size_usd float          – intended position size in USD
        """
        protocol = str(orderbook_data.get("protocol", "unknown"))
        bids: list[tuple[float, float]] = [
            (float(b[0]), float(b[1])) for b in orderbook_data.get("bids", [])
        ]
        asks: list[tuple[float, float]] = [
            (float(a[0]), float(a[1])) for a in orderbook_data.get("asks", [])
        ]
        mid_price = float(orderbook_data.get("mid_price", 0.0))
        position_size_usd = float(orderbook_data.get("position_size_usd", 0.0))

        # ---- Bid/Ask depth within 1% of mid ----
        lower_bid = mid_price * (1.0 - BAND_PCT) if mid_price > 0 else 0.0
        upper_ask = mid_price * (1.0 + BAND_PCT) if mid_price > 0 else float("inf")

        bid_depth_usd = sum(size for price, size in bids if price >= lower_bid)
        ask_depth_usd = sum(size for price, size in asks if price <= upper_ask)

        # ---- Spread ----
        best_bid = max((price for price, _ in bids), default=0.0)
        best_ask = min((price for price, _ in asks), default=0.0)

        if mid_price > 0 and best_bid > 0 and best_ask > 0:
            spread_bps = (best_ask - best_bid) / mid_price * 10_000.0
        else:
            spread_bps = 0.0

        # ---- Market impact ----
        market_impact_bps = self._calc_market_impact(
            bids, position_size_usd, mid_price, side="exit"
        )

        # ---- Can exit in 1% ----
        can_exit_in_1pct = bid_depth_usd >= position_size_usd if position_size_usd > 0 else True

        # ---- Depth rating ----
        depth_rating = self._rate_depth(bid_depth_usd, position_size_usd)

        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol": protocol,
            "mid_price": mid_price,
            "position_size_usd": position_size_usd,
            "bid_depth_usd": round(bid_depth_usd, 2),
            "ask_depth_usd": round(ask_depth_usd, 2),
            "spread_bps": round(spread_bps, 4),
            "market_impact_bps": round(market_impact_bps, 4),
            "can_exit_in_1pct": can_exit_in_1pct,
            "depth_rating": depth_rating,
            "ratio_bid_to_position": round(bid_depth_usd / position_size_usd, 3)
            if position_size_usd > 0
            else None,
        }
        self._last_result = result
        return result

    def get_depth_rating(self) -> str:
        """Return the depth rating from the last ``analyze()`` call."""
        if self._last_result is None:
            return DEPTH_INSUFFICIENT
        return self._last_result["depth_rating"]

    def get_market_impact(self) -> float:
        """Return market impact in bps from the last ``analyze()`` call."""
        if self._last_result is None:
            return 0.0
        return self._last_result["market_impact_bps"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, data_dir: str = "") -> str:
        """Append the last result to the ring-buffer log (cap 100).

        Returns the path written.
        """
        if self._last_result is None:
            raise RuntimeError("No result to save – call analyze() first.")

        base = data_dir or self._data_dir or ""
        if base:
            path = os.path.join(base, LOG_FILE_NAME)
        else:
            path = os.path.join("data", LOG_FILE_NAME)

        _atomic_append(path, self._last_result, cap=LOG_CAP)
        return path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_market_impact(
        bids: list[tuple[float, float]],
        position_size_usd: float,
        mid_price: float,
        side: str = "exit",
    ) -> float:
        """Walk the book to estimate average execution price, return impact in bps."""
        if not bids or position_size_usd <= 0 or mid_price <= 0:
            return 0.0

        # Sort bids descending (best bid first)
        sorted_bids = sorted(bids, key=lambda x: x[0], reverse=True)

        remaining = position_size_usd
        total_cost = 0.0
        total_filled = 0.0

        for price, size_usd in sorted_bids:
            if remaining <= 0:
                break
            fill = min(remaining, size_usd)
            # price here is per unit; size_usd is already in USD
            # We compute value-weighted avg price
            # size_usd represents USD liquidity at this price level
            total_cost += fill  # USD value at level price
            total_filled += fill
            remaining -= fill

        if total_filled <= 0 or mid_price <= 0:
            return 0.0

        # If we couldn't fill entirely → full impact signal
        if remaining > 0:
            # Couldn't fill — return large impact
            return 500.0  # 500 bps flag for insufficient depth

        # avg_exec vs mid — approximate: walk gives average px weighted by size
        # Since size_usd already represents the USD value, impact = fraction unfilled ×
        # We need weighted price. Recalculate:
        remaining2 = position_size_usd
        weighted_price_num = 0.0
        weighted_price_den = 0.0
        for price, size_usd in sorted_bids:
            if remaining2 <= 0:
                break
            fill = min(remaining2, size_usd)
            # proportion of position filled at this price
            weighted_price_num += price * fill
            weighted_price_den += fill
            remaining2 -= fill

        if weighted_price_den <= 0:
            return 0.0

        avg_exec_price = weighted_price_num / weighted_price_den
        impact_bps = abs(mid_price - avg_exec_price) / mid_price * 10_000.0
        return impact_bps

    @staticmethod
    def _rate_depth(bid_depth_usd: float, position_size_usd: float) -> str:
        """Rate depth relative to position size."""
        if position_size_usd <= 0:
            return DEPTH_DEEP
        ratio = bid_depth_usd / position_size_usd
        if ratio >= 10.0:
            return DEPTH_DEEP
        if ratio >= 5.0:
            return DEPTH_ADEQUATE
        if ratio >= 2.0:
            return DEPTH_THIN
        return DEPTH_INSUFFICIENT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



    def to_dict(self) -> dict:
        """Return internal state as a plain dict. LLM FORBIDDEN."""
        return getattr(self, '_data', {})

def _atomic_append(path: str, entry: dict[str, Any], cap: int = 100) -> None:
    """Read existing log, append entry, cap to ``cap``, atomic write."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    existing: list[dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    existing = existing[-cap:]

    dir_ = os.path.dirname(os.path.abspath(path))
    atomic_save(existing, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _sample_orderbook() -> dict[str, Any]:
    mid = 1.0
    bids = [(round(mid - i * 0.001, 4), 500_000.0) for i in range(20)]
    asks = [(round(mid + i * 0.001, 4), 500_000.0) for i in range(1, 21)]
    return {
        "protocol": "Aave V3",
        "bids": bids,
        "asks": asks,
        "mid_price": mid,
        "position_size_usd": 1_000_000.0,
    }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-785 ProtocolLiquidityDepthAnalyzer")
    parser.add_argument("--check", action="store_true", help="Analyze + print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Analyze + atomic write to log")
    parser.add_argument("--data-dir", default="", help="Override data directory")
    args = parser.parse_args()

    analyzer = ProtocolLiquidityDepthAnalyzer(data_dir=args.data_dir)
    ob = _sample_orderbook()
    result = analyzer.analyze(ob)

    print(json.dumps(result, indent=2))
    print(f"\nDepth rating : {analyzer.get_depth_rating()}")
    print(f"Market impact: {analyzer.get_market_impact():.4f} bps")

    if args.run:
        path = analyzer.save(data_dir=args.data_dir)
        print(f"\nSaved → {path}")


if __name__ == "__main__":
    _main()
