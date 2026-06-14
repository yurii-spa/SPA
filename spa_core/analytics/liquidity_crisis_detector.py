"""
MP-748: LiquidityCrisisDetector
Advisory/read-only analytics module.
Detects early signs of DeFi liquidity crises by monitoring utilization spikes,
borrow rate jumps, liquidity depth drops, and withdrawal queues.
Fires WATCH/WARNING/CRISIS alerts with time-to-crisis estimates.

CLI:
    python3 -m spa_core.analytics.liquidity_crisis_detector --check
    python3 -m spa_core.analytics.liquidity_crisis_detector --run
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, asdict
from typing import List


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "liquidity_crisis_log.json")
RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LiquiditySignal:
    protocol: str
    asset: str

    # Current state
    utilization_pct: float           # % of pool currently lent out
    available_liquidity_usd: float   # cash available for withdrawals
    total_deposits_usd: float

    # Rate context
    borrow_rate_pct: float           # current variable borrow rate
    borrow_rate_7d_avg_pct: float    # 7-day average borrow rate

    # Computed
    utilization_spike: float         # borrow_rate - borrow_rate_7d_avg (positive = spike)
    liquidity_ratio_pct: float       # available_liquidity / total_deposits * 100

    # Crisis indicators
    is_utilization_critical: bool    # utilization >= 95%
    is_rate_spiking: bool            # utilization_spike >= 2.0 percentage points
    is_liquidity_thin: bool          # liquidity_ratio < 10%

    crisis_score: float              # 0-100: weighted sum of indicators
    alert_level: str                 # "NORMAL" | "WATCH" | "WARNING" | "CRISIS"

    # Estimated hours until illiquidity at current utilization rate
    hours_to_illiquidity: float

    recommendation: str


@dataclass
class LiquidityCrisisResult:
    signals: List[LiquiditySignal]

    crisis_protocols: List[str]    # alert_level == "CRISIS"
    warning_protocols: List[str]   # alert_level == "WARNING"

    most_at_risk_protocol: str     # highest crisis_score

    system_alert_level: str        # worst alert_level across all

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Alert level ordering for comparison
# ---------------------------------------------------------------------------

_ALERT_ORDER = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRISIS": 3}


def _worst_alert(levels: List[str]) -> str:
    if not levels:
        return "NORMAL"
    return max(levels, key=lambda l: _ALERT_ORDER.get(l, 0))


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def compute_liquidity_ratio(available_liquidity_usd: float, total_deposits_usd: float) -> float:
    """Return available / total * 100. Returns 0 if total is 0."""
    if total_deposits_usd <= 0:
        return 0.0
    return available_liquidity_usd / total_deposits_usd * 100.0


def compute_crisis_score(
    util_pct: float,
    spike: float,
    is_thin: bool,
    is_critical: bool,
) -> float:
    """
    Weighted crisis score 0-100.
    score = util_pct * 0.4 + min(spike * 5, 30) + (10 if thin else 0) + (20 if critical else 0)
    Clamped to [0, 100].
    """
    score = (
        util_pct * 0.4
        + min(spike * 5.0, 30.0)
        + (10.0 if is_thin else 0.0)
        + (20.0 if is_critical else 0.0)
    )
    return min(100.0, max(0.0, score))


def alert_level(score: float) -> str:
    """Map crisis score to alert level."""
    if score >= 80.0:
        return "CRISIS"
    if score >= 60.0:
        return "WARNING"
    if score >= 30.0:
        return "WATCH"
    return "NORMAL"


def compute_hours_to_illiquidity(
    available_liquidity_usd: float,
    total_deposits_usd: float,
    util_pct: float,
) -> float:
    """
    Estimate hours until pool is illiquid.
    If util_pct >= 95: return 0 (already critical).
    hours = (available / total / 0.01) capped at 720.
    """
    if util_pct >= 95.0:
        return 0.0
    if total_deposits_usd <= 0:
        return 720.0
    hours = available_liquidity_usd / total_deposits_usd / 0.01
    return min(720.0, hours)


def _make_recommendation(level: str) -> str:
    if level == "CRISIS":
        return "CRISIS: Withdraw immediately. Liquidity near zero."
    if level == "WARNING":
        return "WARNING: High crisis risk. Monitor closely and prepare exit."
    if level == "WATCH":
        return "WATCH: Elevated risk signals. Track utilization."
    return "Liquidity appears healthy."


def analyze_signal(
    protocol: str,
    asset: str,
    utilization_pct: float,
    available_liquidity_usd: float,
    total_deposits_usd: float,
    borrow_rate_pct: float,
    borrow_rate_7d_avg_pct: float,
) -> LiquiditySignal:
    """Build a LiquiditySignal from raw inputs."""
    spike = borrow_rate_pct - borrow_rate_7d_avg_pct
    liq_ratio = compute_liquidity_ratio(available_liquidity_usd, total_deposits_usd)

    is_critical = utilization_pct >= 95.0
    is_spiking = spike >= 2.0
    is_thin = liq_ratio < 10.0

    score = compute_crisis_score(utilization_pct, spike, is_thin, is_critical)
    level = alert_level(score)
    hours = compute_hours_to_illiquidity(available_liquidity_usd, total_deposits_usd, utilization_pct)
    rec = _make_recommendation(level)

    return LiquiditySignal(
        protocol=protocol,
        asset=asset,
        utilization_pct=utilization_pct,
        available_liquidity_usd=available_liquidity_usd,
        total_deposits_usd=total_deposits_usd,
        borrow_rate_pct=borrow_rate_pct,
        borrow_rate_7d_avg_pct=borrow_rate_7d_avg_pct,
        utilization_spike=spike,
        liquidity_ratio_pct=liq_ratio,
        is_utilization_critical=is_critical,
        is_rate_spiking=is_spiking,
        is_liquidity_thin=is_thin,
        crisis_score=score,
        alert_level=level,
        hours_to_illiquidity=hours,
        recommendation=rec,
    )


def detect_crises(
    signals_data: List[dict],
    data_file: str = DEFAULT_DATA_FILE,
) -> LiquidityCrisisResult:
    """
    Build LiquidityCrisisResult from a list of signal dicts.
    Each dict must contain the fields expected by analyze_signal.
    """
    signals: List[LiquiditySignal] = []
    for d in signals_data:
        sig = analyze_signal(
            protocol=d["protocol"],
            asset=d["asset"],
            utilization_pct=d["utilization_pct"],
            available_liquidity_usd=d["available_liquidity_usd"],
            total_deposits_usd=d["total_deposits_usd"],
            borrow_rate_pct=d["borrow_rate_pct"],
            borrow_rate_7d_avg_pct=d["borrow_rate_7d_avg_pct"],
        )
        signals.append(sig)

    crisis_protocols = [s.protocol for s in signals if s.alert_level == "CRISIS"]
    warning_protocols = [s.protocol for s in signals if s.alert_level == "WARNING"]

    if signals:
        most_at_risk = max(signals, key=lambda s: s.crisis_score).protocol
        sys_level = _worst_alert([s.alert_level for s in signals])
    else:
        most_at_risk = ""
        sys_level = "NORMAL"

    # Build recommendation summary
    if crisis_protocols:
        rec_summary = f"CRISIS detected in: {', '.join(crisis_protocols)}. Immediate action required."
    elif warning_protocols:
        rec_summary = f"WARNING in: {', '.join(warning_protocols)}. Monitor and prepare exit strategy."
    else:
        rec_summary = "No crisis signals detected. Liquidity conditions appear normal."

    return LiquidityCrisisResult(
        signals=signals,
        crisis_protocols=crisis_protocols,
        warning_protocols=warning_protocols,
        most_at_risk_protocol=most_at_risk,
        system_alert_level=sys_level,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_history(data_file: str = DEFAULT_DATA_FILE) -> list:
    """Load history from JSON ring-buffer file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _result_to_dict(result: LiquidityCrisisResult) -> dict:
    return {
        "signals": [asdict(s) for s in result.signals],
        "crisis_protocols": result.crisis_protocols,
        "warning_protocols": result.warning_protocols,
        "most_at_risk_protocol": result.most_at_risk_protocol,
        "system_alert_level": result.system_alert_level,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(
    result: LiquidityCrisisResult,
    data_file: str = DEFAULT_DATA_FILE,
) -> str:
    """Atomically append result to ring-buffer JSON file (cap 100)."""
    history = load_history(data_file)
    history.append(_result_to_dict(result))
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(data_file), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(history, f, indent=2)
        os.replace(tmp_path, data_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    result.saved_to = data_file
    return data_file


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_SIGNALS = [
    {
        "protocol": "Aave V3",
        "asset": "USDC",
        "utilization_pct": 82.0,
        "available_liquidity_usd": 18_000_000.0,
        "total_deposits_usd": 100_000_000.0,
        "borrow_rate_pct": 5.2,
        "borrow_rate_7d_avg_pct": 4.8,
    },
    {
        "protocol": "Compound V3",
        "asset": "USDC",
        "utilization_pct": 96.5,
        "available_liquidity_usd": 1_750_000.0,
        "total_deposits_usd": 50_000_000.0,
        "borrow_rate_pct": 12.0,
        "borrow_rate_7d_avg_pct": 5.5,
    },
    {
        "protocol": "Morpho Steakhouse",
        "asset": "USDC",
        "utilization_pct": 65.0,
        "available_liquidity_usd": 7_000_000.0,
        "total_deposits_usd": 20_000_000.0,
        "borrow_rate_pct": 6.8,
        "borrow_rate_7d_avg_pct": 6.5,
    },
]


def main() -> None:
    mode = "--check"
    data_file = DEFAULT_DATA_FILE
    args = sys.argv[1:]
    if "--run" in args:
        mode = "--run"
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_file = os.path.join(args[idx + 1], "liquidity_crisis_log.json")

    result = detect_crises(_SAMPLE_SIGNALS, data_file=data_file)

    print("=== MP-748 LiquidityCrisisDetector ===")
    print(f"System alert level: {result.system_alert_level}")
    print(f"Crisis protocols:   {result.crisis_protocols}")
    print(f"Warning protocols:  {result.warning_protocols}")
    print(f"Most at risk:       {result.most_at_risk_protocol}")
    print(f"Summary: {result.recommendation_summary}")
    print()
    for s in result.signals:
        print(
            f"  [{s.alert_level:7s}] {s.protocol}/{s.asset} "
            f"util={s.utilization_pct:.1f}% "
            f"score={s.crisis_score:.1f} "
            f"h_to_illiq={s.hours_to_illiquidity:.1f}h"
        )
        print(f"           → {s.recommendation}")

    if mode == "--run":
        save_results(result, data_file)
        print(f"\nSaved → {result.saved_to}")


if __name__ == "__main__":
    main()
