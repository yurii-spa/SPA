"""
MP-744: ProtocolTVLMomentumTracker

Advisory/read-only module. Tracks TVL (Total Value Locked) changes over time
for DeFi protocols and detects inflow/outflow momentum signals. High TVL
inflows indicate growing confidence; outflows indicate capital flight risk.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from typing import List


# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "tvl_momentum_log.json"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TVLSnapshot:
    protocol: str
    tvl_usd: float
    timestamp_iso: str


@dataclass
class TVLMomentum:
    protocol: str
    current_tvl_usd: float

    # Change metrics
    tvl_change_1d_pct: float   # % change from 1 period ago
    tvl_change_7d_pct: float   # % change from 7 periods ago (or first if <7)
    tvl_change_30d_pct: float  # % change from 30 periods ago (or first if <30)

    # Momentum
    momentum_score: float  # weighted: 0.5*change_1d + 0.3*change_7d + 0.2*change_30d

    # Direction
    momentum_label: str  # STRONG_INFLOW/INFLOW/NEUTRAL/OUTFLOW/STRONG_OUTFLOW

    # Peak/trough
    all_time_high_tvl_usd: float
    drawdown_from_ath_pct: float   # (ATH - current) / ATH * 100

    # Trend
    is_trending_up: bool   # True if current > 7d SMA of TVL
    sma_7_tvl_usd: float   # simple moving avg of last 7 snapshots TVL

    alert: str   # OUTFLOW_ALERT / INFLOW_SIGNAL / NONE
    recommendation: str


@dataclass
class TVLMomentumResult:
    protocols: List[TVLMomentum]

    top_inflow_protocols: List[str]   # top 3 by momentum_score
    top_outflow_protocols: List[str]  # bottom 3 by momentum_score

    avg_momentum_score: float

    market_momentum_label: str  # BULL (avg>3) | NEUTRAL (-3 to 3) | BEAR (<-3)

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def compute_pct_change(current: float, previous: float) -> float:
    """Percentage change from previous to current. Returns 0 if previous <= 0."""
    if previous <= 0:
        return 0.0
    return (current - previous) / previous * 100.0


def compute_momentum_score(c1d: float, c7d: float, c30d: float) -> float:
    """Weighted momentum: 0.5*1d + 0.3*7d + 0.2*30d."""
    return 0.5 * c1d + 0.3 * c7d + 0.2 * c30d


def momentum_label(score: float) -> str:
    """Classify momentum score into directional label."""
    if score > 10:
        return "STRONG_INFLOW"
    elif score > 2:
        return "INFLOW"
    elif score >= -2:
        return "NEUTRAL"
    elif score >= -10:
        return "OUTFLOW"
    else:
        return "STRONG_OUTFLOW"


def compute_sma_tvl(snapshots: List[TVLSnapshot], window: int = 7) -> float:
    """Simple moving average of last `window` snapshot TVL values."""
    if not snapshots:
        return 0.0
    values = [s.tvl_usd for s in snapshots[-window:]]
    return sum(values) / len(values)


def analyze_protocol(protocol: str, snapshots: List[TVLSnapshot]) -> TVLMomentum:
    """
    Analyze a single protocol's TVL history.
    snapshots: List[TVLSnapshot] sorted by timestamp ascending.
    """
    n = len(snapshots)
    current_tvl = snapshots[-1].tvl_usd if n > 0 else 0.0

    # 1d change: snapshots[-2] → snapshots[-1]  (0 if <2 snapshots)
    if n >= 2:
        tvl_change_1d_pct = compute_pct_change(snapshots[-1].tvl_usd, snapshots[-2].tvl_usd)
    else:
        tvl_change_1d_pct = 0.0

    # 7d change: snapshots[-8] (or [0] if <8) → snapshots[-1]
    ref_7d = snapshots[-8] if n >= 8 else snapshots[0]
    tvl_change_7d_pct = compute_pct_change(snapshots[-1].tvl_usd, ref_7d.tvl_usd) if n >= 2 else 0.0

    # 30d change: snapshots[-31] (or [0] if <31) → snapshots[-1]
    ref_30d = snapshots[-31] if n >= 31 else snapshots[0]
    tvl_change_30d_pct = compute_pct_change(snapshots[-1].tvl_usd, ref_30d.tvl_usd) if n >= 2 else 0.0

    # Momentum score and label
    score = compute_momentum_score(tvl_change_1d_pct, tvl_change_7d_pct, tvl_change_30d_pct)
    label = momentum_label(score)

    # All-time high
    ath = max(s.tvl_usd for s in snapshots) if n > 0 else 0.0

    # Drawdown from ATH
    drawdown = (ath - current_tvl) / ath * 100.0 if ath > 0 else 0.0

    # 7-period SMA and trend
    sma_7 = compute_sma_tvl(snapshots, 7)
    is_trending_up = current_tvl > sma_7

    # Alert
    if score < -5:
        alert = "OUTFLOW_ALERT"
    elif score > 5:
        alert = "INFLOW_SIGNAL"
    else:
        alert = "NONE"

    # Recommendation
    if alert == "OUTFLOW_ALERT":
        recommendation = "Significant TVL outflow detected. Review protocol health."
    elif alert == "INFLOW_SIGNAL":
        recommendation = "Strong TVL inflows. Protocol gaining traction."
    else:
        recommendation = "TVL momentum within normal range."

    return TVLMomentum(
        protocol=protocol,
        current_tvl_usd=current_tvl,
        tvl_change_1d_pct=tvl_change_1d_pct,
        tvl_change_7d_pct=tvl_change_7d_pct,
        tvl_change_30d_pct=tvl_change_30d_pct,
        momentum_score=score,
        momentum_label=label,
        all_time_high_tvl_usd=ath,
        drawdown_from_ath_pct=drawdown,
        is_trending_up=is_trending_up,
        sma_7_tvl_usd=sma_7,
        alert=alert,
        recommendation=recommendation,
    )


def analyze_market(protocols_data: List[dict]) -> TVLMomentumResult:
    """
    Analyze TVL momentum across all protocols.
    protocols_data: List[dict] with keys: protocol, snapshots (list of {tvl_usd, timestamp_iso})
    """
    momentums: List[TVLMomentum] = []
    for pd_item in protocols_data:
        protocol = pd_item["protocol"]
        raw_snaps = pd_item.get("snapshots", [])
        snapshots = [
            TVLSnapshot(protocol=protocol, tvl_usd=s["tvl_usd"], timestamp_iso=s["timestamp_iso"])
            for s in raw_snaps
        ]
        m = analyze_protocol(protocol, snapshots)
        momentums.append(m)

    # Top 3 inflow: highest momentum_score
    sorted_desc = sorted(momentums, key=lambda x: x.momentum_score, reverse=True)
    top_inflow = [m.protocol for m in sorted_desc[:3]]

    # Bottom 3 outflow: lowest momentum_score
    sorted_asc = sorted(momentums, key=lambda x: x.momentum_score)
    top_outflow = [m.protocol for m in sorted_asc[:3]]

    # Aggregate
    avg_score = sum(m.momentum_score for m in momentums) / len(momentums) if momentums else 0.0

    # Market label
    if avg_score > 3:
        market_label = "BULL"
        rec_summary = "Market showing strong inflows. Favorable for yield deployment."
    elif avg_score >= -3:
        market_label = "NEUTRAL"
        rec_summary = "Market momentum is neutral. Continue monitoring."
    else:
        market_label = "BEAR"
        rec_summary = "Market experiencing outflows. Exercise caution with new positions."

    return TVLMomentumResult(
        protocols=momentums,
        top_inflow_protocols=top_inflow,
        top_outflow_protocols=top_outflow,
        avg_momentum_score=avg_score,
        market_momentum_label=market_label,
        recommendation_summary=rec_summary,
        saved_to="",
    )


def save_results(result: TVLMomentumResult, data_file: str = _DEFAULT_DATA_FILE) -> str:
    """Save result to ring-buffer JSON (max 100 entries). Returns saved_to path."""
    os.makedirs(os.path.dirname(data_file), exist_ok=True)

    history = load_history(data_file)
    entry = asdict(result)
    history.append(entry)

    # Ring-buffer cap 100
    if len(history) > 100:
        history = history[-100:]

    # Atomic write
    dir_ = os.path.dirname(data_file)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tf:
        json.dump(history, tf, indent=2)
        tmp_path = tf.name
    os.replace(tmp_path, data_file)

    return data_file


def load_history(data_file: str = _DEFAULT_DATA_FILE) -> list:
    """Load history from JSON file. Returns empty list on missing/corrupt file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import datetime

    parser = argparse.ArgumentParser(description="MP-744 ProtocolTVLMomentumTracker")
    parser.add_argument("--run", action="store_true", help="Run and save results")
    parser.add_argument("--check", action="store_true", help="Run without saving (default)")
    parser.add_argument("--data-dir", help="Override data directory")
    args = parser.parse_args()

    data_file = _DEFAULT_DATA_FILE
    if args.data_dir:
        data_file = os.path.join(args.data_dir, "tvl_momentum_log.json")

    protocols = ["Aave V3", "Compound V3", "Morpho Steakhouse"]
    base_tvl = {"Aave V3": 5_000_000, "Compound V3": 3_000_000, "Morpho Steakhouse": 2_000_000}
    sample = []
    for p in protocols:
        tvl = base_tvl[p]
        snaps = []
        for i in range(35):
            ts = (datetime.datetime.now() - datetime.timedelta(days=34 - i)).isoformat()
            snaps.append({"tvl_usd": tvl, "timestamp_iso": ts})
            tvl *= 1.005
        sample.append({"protocol": p, "snapshots": snaps})

    result = analyze_market(sample)
    print(f"Market Momentum: {result.market_momentum_label}")
    print(f"Avg Score:       {result.avg_momentum_score:.4f}")
    print(f"Top Inflows:     {result.top_inflow_protocols}")
    print(f"Top Outflows:    {result.top_outflow_protocols}")
    for m in result.protocols:
        print(f"  {m.protocol}: score={m.momentum_score:.2f} label={m.momentum_label} alert={m.alert}")

    if args.run:
        result.saved_to = save_results(result, data_file)
        print(f"Saved to: {result.saved_to}")
