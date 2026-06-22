"""
MP-762: ProtocolRevenueTracker
Tracks and analyzes DeFi protocol revenue trends over time — fee income,
volume, revenue per TVL. Detects revenue growth/decline trends and predicts
sustainability of current APY levels.

Advisory/read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer cap: 100 entries.

CLI
---
  python3 -m spa_core.analytics.protocol_revenue_tracker --check   (default)
  python3 -m spa_core.analytics.protocol_revenue_tracker --run
  python3 -m spa_core.analytics.protocol_revenue_tracker --run --data-dir PATH
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "protocol_revenue_log.json"
_RING_BUFFER_MAX = 100


# ---------------------------------------------------------------------------
# Core computation functions (module-level so tests can import them directly)
# ---------------------------------------------------------------------------

def compute_daily_fee(daily_volume_usd: float, fee_rate_bps: float) -> float:
    """daily_volume * fee_rate_bps / 10000"""
    return daily_volume_usd * fee_rate_bps / 10_000.0


def compute_revenue_to_tvl(annualized_revenue_usd: float, tvl_usd: float) -> float:
    """annualized / tvl * 100 if tvl > 0 else 0"""
    if tvl_usd > 0:
        return annualized_revenue_usd / tvl_usd * 100.0
    return 0.0


def compute_growth(first: float, latest: float) -> float:
    """(latest - first) / first * 100 if first > 0 else 0"""
    if first > 0:
        return (latest - first) / first * 100.0
    return 0.0


def sustainability_score(revenue_to_tvl_pct: float) -> float:
    """min(100, revenue_to_tvl_pct * 10)  — 10% revenue/TVL → score 100"""
    return min(100.0, revenue_to_tvl_pct * 10.0)


def get_trend_label(growth_pct: float) -> str:
    """GROWING (>10%) | STABLE (-10 to 10%) | DECLINING (<-10%)"""
    if growth_pct > 10.0:
        return "GROWING"
    elif growth_pct < -10.0:
        return "DECLINING"
    else:
        return "STABLE"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RevenueDataPoint:
    protocol: str
    date_iso: str
    daily_volume_usd: float
    fee_rate_bps: float       # e.g. 30 bps = 0.30%
    tvl_usd: float

    # Computed in __post_init__
    daily_fee_revenue_usd: float = field(init=False)
    annualized_revenue_usd: float = field(init=False)
    revenue_to_tvl_pct: float = field(init=False)

    def __post_init__(self) -> None:
        self.daily_fee_revenue_usd = compute_daily_fee(
            self.daily_volume_usd, self.fee_rate_bps
        )
        self.annualized_revenue_usd = self.daily_fee_revenue_usd * 365.0
        self.revenue_to_tvl_pct = compute_revenue_to_tvl(
            self.annualized_revenue_usd, self.tvl_usd
        )


@dataclass
class RevenueTrend:
    protocol: str
    data_points: List[RevenueDataPoint]

    # Revenue metrics
    total_cumulative_revenue_usd: float  # sum of daily_fee_revenue_usd
    avg_daily_revenue_usd: float
    peak_daily_revenue_usd: float
    latest_daily_revenue_usd: float      # most recent

    # Growth
    revenue_growth_pct: float  # (latest - first) / first * 100 if first > 0 else 0

    # Trend direction
    trend_label: str  # "GROWING" | "STABLE" | "DECLINING"

    # Revenue sustainability score 0-100
    sustainability_score: float  # min(100, revenue_to_tvl_pct_latest * 10)

    # APY implied by revenue
    implied_sustainable_apy_pct: float  # = latest revenue_to_tvl_pct

    recommendation: str


@dataclass
class RevenueResult:
    trends: List[RevenueTrend]

    highest_revenue_protocol: str    # max avg_daily_revenue_usd
    fastest_growing_protocol: str    # max revenue_growth_pct
    most_sustainable_protocol: str   # max sustainability_score

    avg_sustainability_score: float

    market_revenue_label: str  # "BULL_REVENUE" | "STABLE_REVENUE" | "BEAR_REVENUE"

    recommendation_summary: str
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_protocol(
    protocol: str,
    data_points_list: List[Dict[str, Any]],
) -> RevenueTrend:
    """
    Build a RevenueTrend for a single protocol.

    data_points_list: List[dict] with keys
        {date_iso, daily_volume_usd, fee_rate_bps, tvl_usd}
    """
    # Sort by date_iso ascending
    sorted_data = sorted(data_points_list, key=lambda d: d["date_iso"])

    points: List[RevenueDataPoint] = [
        RevenueDataPoint(
            protocol=protocol,
            date_iso=dp["date_iso"],
            daily_volume_usd=float(dp["daily_volume_usd"]),
            fee_rate_bps=float(dp["fee_rate_bps"]),
            tvl_usd=float(dp["tvl_usd"]),
        )
        for dp in sorted_data
    ]

    if not points:
        raise ValueError(f"No data points provided for protocol '{protocol}'")

    daily_fees = [p.daily_fee_revenue_usd for p in points]

    total_cumulative = sum(daily_fees)
    n = len(daily_fees)
    avg_daily = total_cumulative / n
    peak_daily = max(daily_fees)
    latest_daily = daily_fees[-1]
    first_daily = daily_fees[0]

    growth = compute_growth(first_daily, latest_daily)
    label = get_trend_label(growth)

    latest_r2tvl = points[-1].revenue_to_tvl_pct
    sus_score = sustainability_score(latest_r2tvl)
    implied_apy = latest_r2tvl

    if label == "DECLINING":
        rec = "Revenue declining. Yield sustainability at risk."
    elif label == "GROWING":
        rec = "Revenue growing. Protocol gaining traction."
    else:
        rec = "Stable revenue. Sustainable yield profile."

    return RevenueTrend(
        protocol=protocol,
        data_points=points,
        total_cumulative_revenue_usd=total_cumulative,
        avg_daily_revenue_usd=avg_daily,
        peak_daily_revenue_usd=peak_daily,
        latest_daily_revenue_usd=latest_daily,
        revenue_growth_pct=growth,
        trend_label=label,
        sustainability_score=sus_score,
        implied_sustainable_apy_pct=implied_apy,
        recommendation=rec,
    )


def analyze_market(
    protocols_data: List[Dict[str, Any]],
) -> RevenueResult:
    """
    Analyze revenue trends across multiple protocols.

    protocols_data: List[dict] with keys
        {protocol, data_points: List[...]}
    """
    trends: List[RevenueTrend] = [
        analyze_protocol(pd["protocol"], pd["data_points"])
        for pd in protocols_data
    ]

    if not trends:
        raise ValueError("No protocol data provided")

    highest = max(trends, key=lambda t: t.avg_daily_revenue_usd)
    fastest = max(trends, key=lambda t: t.revenue_growth_pct)
    most_sus = max(trends, key=lambda t: t.sustainability_score)

    avg_sus = sum(t.sustainability_score for t in trends) / len(trends)
    avg_growth = sum(t.revenue_growth_pct for t in trends) / len(trends)

    if avg_growth > 10.0:
        market_label = "BULL_REVENUE"
    elif avg_growth < -10.0:
        market_label = "BEAR_REVENUE"
    else:
        market_label = "STABLE_REVENUE"

    rec_summary = (
        f"Market revenue is {market_label}. "
        f"Highest revenue: {highest.protocol} "
        f"(avg ${highest.avg_daily_revenue_usd:,.0f}/day). "
        f"Most sustainable: {most_sus.protocol} "
        f"(score {most_sus.sustainability_score:.1f}/100)."
    )

    return RevenueResult(
        trends=trends,
        highest_revenue_protocol=highest.protocol,
        fastest_growing_protocol=fastest.protocol,
        most_sustainable_protocol=most_sus.protocol,
        avg_sustainability_score=avg_sus,
        market_revenue_label=market_label,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _dp_to_dict(dp: RevenueDataPoint) -> Dict[str, Any]:
    return {
        "protocol": dp.protocol,
        "date_iso": dp.date_iso,
        "daily_volume_usd": dp.daily_volume_usd,
        "fee_rate_bps": dp.fee_rate_bps,
        "tvl_usd": dp.tvl_usd,
        "daily_fee_revenue_usd": dp.daily_fee_revenue_usd,
        "annualized_revenue_usd": dp.annualized_revenue_usd,
        "revenue_to_tvl_pct": dp.revenue_to_tvl_pct,
    }


def _trend_to_dict(t: RevenueTrend) -> Dict[str, Any]:
    return {
        "protocol": t.protocol,
        "data_points": [_dp_to_dict(dp) for dp in t.data_points],
        "total_cumulative_revenue_usd": t.total_cumulative_revenue_usd,
        "avg_daily_revenue_usd": t.avg_daily_revenue_usd,
        "peak_daily_revenue_usd": t.peak_daily_revenue_usd,
        "latest_daily_revenue_usd": t.latest_daily_revenue_usd,
        "revenue_growth_pct": t.revenue_growth_pct,
        "trend_label": t.trend_label,
        "sustainability_score": t.sustainability_score,
        "implied_sustainable_apy_pct": t.implied_sustainable_apy_pct,
        "recommendation": t.recommendation,
    }


def _result_to_dict(result: RevenueResult) -> Dict[str, Any]:
    return {
        "trends": [_trend_to_dict(t) for t in result.trends],
        "highest_revenue_protocol": result.highest_revenue_protocol,
        "fastest_growing_protocol": result.fastest_growing_protocol,
        "most_sustainable_protocol": result.most_sustainable_protocol,
        "avg_sustainability_score": result.avg_sustainability_score,
        "market_revenue_label": result.market_revenue_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(
    result: RevenueResult,
    data_dir: Optional[Path] = None,
) -> RevenueResult:
    """Append result to ring-buffer JSON (max _RING_BUFFER_MAX entries)."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = data_dir / _LOG_FILENAME

    history = load_history(data_dir)
    entry = _result_to_dict(result)
    entry["saved_at"] = datetime.now(timezone.utc).isoformat()
    history.append(entry)

    # Ring-buffer trim
    if len(history) > _RING_BUFFER_MAX:
        history = history[-_RING_BUFFER_MAX:]

    # Atomic write via tmp + os.replace
    atomic_save(history, str(log_file))
    result.saved_to = str(log_file)
    return result


def load_history(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load persisted history list from ring-buffer JSON."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_file = Path(data_dir) / _LOG_FILENAME
    if not log_file.exists():
        return []
    try:
        with open(log_file) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, ValueError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_protocols_data() -> List[Dict[str, Any]]:
    return [
        {
            "protocol": "Aave V3",
            "data_points": [
                {"date_iso": "2026-06-01", "daily_volume_usd": 50_000_000,
                 "fee_rate_bps": 10, "tvl_usd": 5_000_000_000},
                {"date_iso": "2026-06-07", "daily_volume_usd": 55_000_000,
                 "fee_rate_bps": 10, "tvl_usd": 5_100_000_000},
                {"date_iso": "2026-06-13", "daily_volume_usd": 60_000_000,
                 "fee_rate_bps": 10, "tvl_usd": 5_200_000_000},
            ],
        },
        {
            "protocol": "Compound V3",
            "data_points": [
                {"date_iso": "2026-06-01", "daily_volume_usd": 20_000_000,
                 "fee_rate_bps": 15, "tvl_usd": 1_000_000_000},
                {"date_iso": "2026-06-07", "daily_volume_usd": 18_000_000,
                 "fee_rate_bps": 15, "tvl_usd": 950_000_000},
                {"date_iso": "2026-06-13", "daily_volume_usd": 17_000_000,
                 "fee_rate_bps": 15, "tvl_usd": 920_000_000},
            ],
        },
        {
            "protocol": "Morpho Steakhouse",
            "data_points": [
                {"date_iso": "2026-06-01", "daily_volume_usd": 10_000_000,
                 "fee_rate_bps": 20, "tvl_usd": 300_000_000},
                {"date_iso": "2026-06-07", "daily_volume_usd": 12_000_000,
                 "fee_rate_bps": 20, "tvl_usd": 320_000_000},
                {"date_iso": "2026-06-13", "daily_volume_usd": 15_000_000,
                 "fee_rate_bps": 20, "tvl_usd": 350_000_000},
            ],
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="MP-762 ProtocolRevenueTracker")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print (no write). Default mode.")
    parser.add_argument("--run", action="store_true",
                        help="Compute and save to data/")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory path")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else None
    result = analyze_market(_sample_protocols_data())

    print(f"Market revenue label : {result.market_revenue_label}")
    print(f"Highest revenue      : {result.highest_revenue_protocol}")
    print(f"Fastest growing      : {result.fastest_growing_protocol}")
    print(f"Most sustainable     : {result.most_sustainable_protocol}")
    print(f"Avg sustainability   : {result.avg_sustainability_score:.1f}/100")
    print(f"Summary: {result.recommendation_summary}")
    print()
    for t in result.trends:
        print(
            f"  {t.protocol:25s}  {t.trend_label:9s}  "
            f"growth={t.revenue_growth_pct:+7.1f}%  "
            f"sustain={t.sustainability_score:5.1f}  "
            f"implied_apy={t.implied_sustainable_apy_pct:.3f}%"
        )

    if args.run:
        save_results(result, data_dir)
        print(f"\nSaved to: {result.saved_to}")
    else:
        print("\n[--check mode] No data written. Use --run to persist.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
