"""Fee Market Analyzer (MP-697).

Analyzes DeFi protocol fee structures and identifies the optimal fee tier
for yield farming and trading activities.

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Ring-buffer capped at :data:`MAX_ENTRIES` entries (100).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Data File
---------
``data/fee_market_log.json``::

    {
      "schema_version": "1.0",
      "generated_at": "<ISO-8601 UTC>",
      "entries": [ <MarketFeeReport dicts>, ... ]   # ring-buffer ≤ 100
    }

Public API
----------
``FeeMarketAnalyzer(data_dir="data")``

    analyze_pool(pool: FeePool) -> FeeAnalysis
    analyze_market(pools: list[FeePool]) -> MarketFeeReport
    save_results(reports: list[MarketFeeReport]) -> None
    load_history() -> list[dict]
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/fee_market_log.json")
MAX_ENTRIES = 100
SCHEMA_VERSION = "1.0"
FEE_APY_CAP = 999.0

# Standard Uniswap V3 fee tiers
UNISWAP_FEE_TIERS: Dict[int, Dict[str, object]] = {
    100:   {"bps": 1,   "typical_use": "Stable pairs (USDC/USDT)"},
    500:   {"bps": 5,   "typical_use": "Correlated pairs (ETH/stETH)"},
    3000:  {"bps": 30,  "typical_use": "Standard pairs (ETH/USDC)"},
    10000: {"bps": 100, "typical_use": "Exotic/volatile pairs"},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FeePool:
    pool_id: str
    protocol: str
    fee_tier_bps: float           # fee in basis points
    volume_24h_usd: float
    tvl_usd: float
    fee_revenue_24h_usd: float    # actual fees collected
    lp_count: int                 # number of liquidity providers


@dataclass
class FeeAnalysis:
    pool_id: str
    protocol: str
    fee_tier_bps: float
    implied_volume_ratio: float   # volume_24h / tvl (daily turnover)
    fee_apy_pct: float            # fee_revenue_24h * 365 / tvl * 100
    revenue_per_lp_daily_usd: float  # fee_revenue / lp_count
    fee_efficiency: float         # actual vs expected fee revenue
    fee_tier_label: str           # ULTRA_LOW / LOW / STANDARD / HIGH
    attractiveness: str           # HIGHLY_ATTRACTIVE / ATTRACTIVE / FAIR / POOR
    recommended_for: str          # LP / TRADER / BOTH / NEITHER
    insights: List[str]


@dataclass
class MarketFeeReport:
    pools: List[FeeAnalysis]
    best_for_lp: str              # pool_id with highest fee_apy
    best_for_trader: str          # pool_id with lowest fee_tier_bps (most liquid)
    avg_fee_apy_pct: float
    market_summary: str


# ---------------------------------------------------------------------------
# Helper functions (pure, no I/O)
# ---------------------------------------------------------------------------


def _implied_volume_ratio(volume_24h: float, tvl: float) -> float:
    if tvl <= 0:
        return 0.0
    return volume_24h / tvl


def _fee_apy_pct(fee_revenue_24h: float, tvl: float) -> float:
    if tvl <= 0:
        return 0.0
    raw = fee_revenue_24h * 365.0 / tvl * 100.0
    return min(raw, FEE_APY_CAP)


def _revenue_per_lp(fee_revenue_24h: float, lp_count: int) -> float:
    if lp_count <= 0:
        return 0.0
    return fee_revenue_24h / lp_count


def _fee_efficiency(
    fee_revenue_24h: float, volume_24h: float, fee_tier_bps: float
) -> float:
    """Ratio of actual fee revenue to theoretically expected revenue.

    expected = volume_24h * fee_tier_bps / 10_000
    Values > 1 imply flash-loan / arbitrage activity boosting fees.
    """
    if volume_24h <= 0 or fee_tier_bps <= 0:
        return 0.0
    expected = volume_24h * fee_tier_bps / 10_000.0
    return fee_revenue_24h / expected


def _fee_tier_label(fee_tier_bps: float) -> str:
    if fee_tier_bps <= 5:
        return "ULTRA_LOW"
    if fee_tier_bps <= 30:
        return "LOW"
    if fee_tier_bps <= 50:
        return "STANDARD"
    return "HIGH"


def _attractiveness(fee_apy: float) -> str:
    if fee_apy > 20.0:
        return "HIGHLY_ATTRACTIVE"
    if fee_apy > 10.0:
        return "ATTRACTIVE"
    if fee_apy > 3.0:
        return "FAIR"
    return "POOR"


def _recommended_for(
    fee_apy: float,
    fee_tier_bps: float,
    volume_ratio: float,
) -> str:
    if fee_apy > 10.0 and fee_tier_bps <= 30:
        return "BOTH"
    if fee_apy > 5.0:
        return "LP"
    if fee_tier_bps <= 10 and volume_ratio > 0.5:
        return "TRADER"
    return "NEITHER"


def _insights(
    fee_efficiency: float,
    implied_volume_ratio: float,
    revenue_per_lp: float,
    fee_apy: float,
    lp_count: int,
) -> List[str]:
    notes: List[str] = []

    if fee_efficiency > 1.5:
        notes.append(
            "💡 Fee revenue above expected — flash loan activity likely"
        )

    if implied_volume_ratio > 5:
        notes.append(
            "🔄 High turnover — pool sees 5x TVL in daily volume"
        )

    if revenue_per_lp > 100:
        notes.append(
            f"💰 Strong LP revenue ${revenue_per_lp:.0f}/day"
        )

    if fee_apy > 50:
        notes.append(
            "⚠️ Very high fee APY — verify volume sustainability"
        )

    if lp_count < 5:
        notes.append(
            "⚠️ Very few LPs — concentrated pool, higher il risk"
        )

    return notes


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class FeeMarketAnalyzer:
    """Advisory analyzer for DeFi protocol fee structures."""

    def __init__(self, data_dir: str = "data") -> None:
        self._data_file = Path(data_dir) / "fee_market_log.json"

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def analyze_pool(self, pool: FeePool) -> FeeAnalysis:
        """Return a FeeAnalysis for a single FeePool."""
        vol_ratio = _implied_volume_ratio(pool.volume_24h_usd, pool.tvl_usd)
        apy = _fee_apy_pct(pool.fee_revenue_24h_usd, pool.tvl_usd)
        rev_per_lp = _revenue_per_lp(pool.fee_revenue_24h_usd, pool.lp_count)
        efficiency = _fee_efficiency(
            pool.fee_revenue_24h_usd, pool.volume_24h_usd, pool.fee_tier_bps
        )
        tier_label = _fee_tier_label(pool.fee_tier_bps)
        attract = _attractiveness(apy)
        rec = _recommended_for(apy, pool.fee_tier_bps, vol_ratio)
        notes = _insights(efficiency, vol_ratio, rev_per_lp, apy, pool.lp_count)

        return FeeAnalysis(
            pool_id=pool.pool_id,
            protocol=pool.protocol,
            fee_tier_bps=pool.fee_tier_bps,
            implied_volume_ratio=vol_ratio,
            fee_apy_pct=apy,
            revenue_per_lp_daily_usd=rev_per_lp,
            fee_efficiency=efficiency,
            fee_tier_label=tier_label,
            attractiveness=attract,
            recommended_for=rec,
            insights=notes,
        )

    def analyze_market(self, pools: List[FeePool]) -> MarketFeeReport:
        """Return a MarketFeeReport summarising all pools.

        Graceful for an empty list.
        """
        analyses = [self.analyze_pool(p) for p in pools]

        if not analyses:
            return MarketFeeReport(
                pools=[],
                best_for_lp="",
                best_for_trader="",
                avg_fee_apy_pct=0.0,
                market_summary="No pools provided.",
            )

        best_lp = max(analyses, key=lambda a: a.fee_apy_pct).pool_id
        best_trader = min(analyses, key=lambda a: a.fee_tier_bps).pool_id
        avg_apy = sum(a.fee_apy_pct for a in analyses) / len(analyses)

        summary = (
            f"Analysed {len(analyses)} pool(s). "
            f"Best LP yield: {best_lp}. "
            f"Lowest fees for traders: {best_trader}. "
            f"Average fee APY: {avg_apy:.2f}%."
        )

        return MarketFeeReport(
            pools=analyses,
            best_for_lp=best_lp,
            best_for_trader=best_trader,
            avg_fee_apy_pct=avg_apy,
            market_summary=summary,
        )

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic)
    # ------------------------------------------------------------------

    def save_results(self, reports: List[MarketFeeReport]) -> None:
        """Append *reports* to the ring-buffer JSON file atomically."""
        history = self.load_history()
        new_entries = [_report_to_dict(r) for r in reports]
        history.extend(new_entries)
        if len(history) > MAX_ENTRIES:
            history = history[-MAX_ENTRIES:]

        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": history,
        }
        _atomic_write(self._data_file, payload)

    def load_history(self) -> List[dict]:
        """Load existing entries from the ring-buffer file.

        Returns an empty list if the file does not exist or is corrupt.
        """
        if not self._data_file.exists():
            return []
        try:
            with open(self._data_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("entries", [])
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _report_to_dict(report: MarketFeeReport) -> dict:
    return {
        "pools": [asdict(a) for a in report.pools],
        "best_for_lp": report.best_for_lp,
        "best_for_trader": report.best_for_trader,
        "avg_fee_apy_pct": report.avg_fee_apy_pct,
        "market_summary": report.market_summary,
    }


def _atomic_write(path: Path, payload: dict) -> None:
    """Write *payload* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MP-697 FeeMarketAnalyzer — advisory CLI"
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Run example analysis and print, without writing (default)",
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="Run example analysis and write to data file",
    )
    p.add_argument(
        "--data-dir",
        default="data",
        help="Directory for data files (default: data)",
    )
    return p


def _example_pools() -> List[FeePool]:
    return [
        FeePool("usdc_usdt_stable", "Uniswap V3", 1,    50_000_000,  20_000_000, 5_000,    120),
        FeePool("eth_usdc_std",     "Uniswap V3", 30,   200_000_000, 40_000_000, 600_000,  80),
        FeePool("eth_steth_corr",   "Uniswap V3", 5,    80_000_000,  25_000_000, 40_000,   45),
        FeePool("exotic_pair",      "Uniswap V3", 100,  5_000_000,   2_000_000,  500_000,  3),
    ]


def main() -> None:
    args = _build_cli().parse_args()
    analyzer = FeeMarketAnalyzer(data_dir=args.data_dir)
    pools = _example_pools()
    report = analyzer.analyze_market(pools)

    for a in report.pools:
        print(
            f"[{a.pool_id:<22}] fee={a.fee_tier_bps:>5.1f}bps "
            f"| APY={a.fee_apy_pct:>7.2f}% "
            f"| {a.attractiveness:<18} "
            f"| rec={a.recommended_for}"
        )
        for note in a.insights:
            print(f"                           {note}")

    print(f"\n{report.market_summary}")
    print(f"Best LP:     {report.best_for_lp}")
    print(f"Best Trader: {report.best_for_trader}")

    if args.run:
        analyzer.save_results([report])
        print(f"\n📄 Results saved → {analyzer._data_file}")


if __name__ == "__main__":
    main()
