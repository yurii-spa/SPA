"""
MP-832: YieldBenchmarkComparator
Compares protocol yields against standard benchmarks (risk-free rate, ETH staking,
BTC HODLing) to determine if DeFi strategies genuinely outperform simpler alternatives
on a risk-adjusted basis.
Advisory/read-only, stdlib only.
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/yield_benchmark_log.json")
MAX_ENTRIES = 100

# Verdict labels
VERDICT_EXCELLENT = "EXCELLENT"
VERDICT_GOOD = "GOOD"
VERDICT_FAIR = "FAIR"
VERDICT_POOR = "POOR"
VERDICT_AVOID = "AVOID"


def _compute_verdict(apy: float, risk_score: int, risk_adjusted_apy: float,
                     risk_free_rate: float) -> str:
    """
    Determine verdict for a strategy.

    AVOID:     apy <= 0 OR risk_score >= 90
    EXCELLENT: risk_adjusted_apy >= rfr * 2 AND risk_score < 50
    GOOD:      risk_adjusted_apy > rfr AND risk_score < 70
    FAIR:      apy > rfr AND risk_adjusted_apy <= rfr
    POOR:      apy <= rfr AND apy > 0
    """
    # AVOID takes highest priority
    if apy <= 0 or risk_score >= 90:
        return VERDICT_AVOID

    # EXCELLENT: risk_adjusted_apy >= rfr * 2 AND risk_score < 50
    # When rfr=0, rfr*2=0 → EXCELLENT requires risk_adjusted_apy >= 0 AND risk_score < 50
    if risk_adjusted_apy >= risk_free_rate * 2 and risk_score < 50:
        return VERDICT_EXCELLENT

    # GOOD: risk_adjusted_apy > rfr AND risk_score < 70
    if risk_adjusted_apy > risk_free_rate and risk_score < 70:
        return VERDICT_GOOD

    # FAIR: apy > rfr AND risk_adjusted_apy <= rfr
    if apy > risk_free_rate and risk_adjusted_apy <= risk_free_rate:
        return VERDICT_FAIR

    # POOR: apy <= rfr AND apy > 0
    if apy <= risk_free_rate and apy > 0:
        return VERDICT_POOR

    # Fallback (covers apy > rfr but risk_adjusted_apy <= rfr with other edge cases)
    return VERDICT_POOR


def analyze(strategies: list, benchmarks: dict, config: dict = None) -> dict:
    """
    Compare strategy yields against standard benchmarks.

    strategies: list of {
        "name": str,
        "apy": float,
        "risk_score": int,  # 0-100
        "liquidity": "HIGH" | "MEDIUM" | "LOW"
    }
    benchmarks: {
        "risk_free_rate": float,
        "eth_staking_apy": float,
        "btc_holding_apy": float
    }
    config: {
        "risk_free_label": str  # default "T-Bill"
    }

    Returns: {
        "strategies": [...],
        "best_risk_adjusted": str | None,
        "best_raw_yield": str | None,
        "benchmark_summary": {...},
        "timestamp": float
    }
    """
    if config is None:
        config = {}

    risk_free_rate = float(benchmarks.get("risk_free_rate", 0.0))
    eth_staking_apy = float(benchmarks.get("eth_staking_apy", 0.0))
    btc_holding_apy = float(benchmarks.get("btc_holding_apy", 0.0))

    results = []
    strategies_beating_rfr = 0
    strategies_beating_eth = 0

    best_risk_adjusted_name = None
    best_risk_adjusted_val = None
    best_raw_yield_name = None
    best_raw_yield_val = None

    for strat in strategies:
        name = strat.get("name", "")
        apy = float(strat.get("apy", 0.0))
        risk_score = int(strat.get("risk_score", 0))
        liquidity = strat.get("liquidity", "MEDIUM")

        # Clamp risk_score to [0, 100]
        risk_score = max(0, min(100, risk_score))

        # Risk-adjusted APY: apy * (1 - risk_score/100)
        risk_adjusted_apy = apy * (1.0 - risk_score / 100.0)

        # Excess returns
        excess_over_rfr = apy - risk_free_rate
        excess_over_eth_staking = apy - eth_staking_apy

        # Risk premium = risk_adjusted_apy - risk_free_rate
        risk_premium = risk_adjusted_apy - risk_free_rate

        # Verdict
        verdict = _compute_verdict(apy, risk_score, risk_adjusted_apy, risk_free_rate)

        # Comparisons
        better_than_rfr = apy > risk_free_rate
        better_than_eth = apy > eth_staking_apy

        if better_than_rfr:
            strategies_beating_rfr += 1
        if better_than_eth:
            strategies_beating_eth += 1

        # Track bests
        if best_risk_adjusted_val is None or risk_adjusted_apy > best_risk_adjusted_val:
            best_risk_adjusted_val = risk_adjusted_apy
            best_risk_adjusted_name = name

        if best_raw_yield_val is None or apy > best_raw_yield_val:
            best_raw_yield_val = apy
            best_raw_yield_name = name

        results.append({
            "name": name,
            "apy": apy,
            "risk_score": risk_score,
            "risk_adjusted_apy": risk_adjusted_apy,
            "excess_over_rfr": excess_over_rfr,
            "excess_over_eth_staking": excess_over_eth_staking,
            "risk_premium": risk_premium,
            "verdict": verdict,
            "better_than_rfr": better_than_rfr,
            "better_than_eth": better_than_eth,
            "liquidity_tier": liquidity,
        })

    return {
        "strategies": results,
        "best_risk_adjusted": best_risk_adjusted_name,
        "best_raw_yield": best_raw_yield_name,
        "benchmark_summary": {
            "risk_free_rate": risk_free_rate,
            "eth_staking_apy": eth_staking_apy,
            "btc_holding_apy": btc_holding_apy,
            "strategies_beating_rfr": strategies_beating_rfr,
            "strategies_beating_eth": strategies_beating_eth,
        },
        "timestamp": time.time(),
    }


def save_log(result: dict, data_file: Path = DATA_FILE) -> None:
    """Atomically append result to ring-buffer JSON (max MAX_ENTRIES)."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(data_file.read_text())
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    existing.append(result)
    existing = existing[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    os.replace(tmp, data_file)


def load_log(data_file: Path = DATA_FILE) -> list:
    """Return saved log; [] on any read/parse error."""
    try:
        return json.loads(data_file.read_text())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-832 YieldBenchmarkComparator")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print; no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically write to data file")
    parser.add_argument("--data-dir", default="data", help="data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_file = data_dir / "yield_benchmark_log.json"

    # Load current tournament results as strategies
    tournament_file = data_dir / "tournament_results.json"
    strategies = []
    try:
        raw = json.loads(tournament_file.read_text())
        if isinstance(raw, list):
            strategies = raw
        elif isinstance(raw, dict):
            strategies = raw.get("strategies", [])
    except Exception:
        pass

    # Default benchmarks (2026 approximate)
    benchmarks = {
        "risk_free_rate": 4.5,
        "eth_staking_apy": 3.8,
        "btc_holding_apy": 0.0,
    }

    result = analyze(strategies, benchmarks)

    print("[MP-832] YieldBenchmarkComparator")
    print(f"  strategies analyzed   : {len(result['strategies'])}")
    print(f"  best_risk_adjusted    : {result['best_risk_adjusted']}")
    print(f"  best_raw_yield        : {result['best_raw_yield']}")
    bs = result["benchmark_summary"]
    print(f"  strategies_beating_rfr: {bs['strategies_beating_rfr']}")
    print(f"  strategies_beating_eth: {bs['strategies_beating_eth']}")
    print()
    for s in result["strategies"]:
        print(f"  [{s['verdict']:<9}] {s['name']:<25} "
              f"APY={s['apy']:+.2f}%  risk_adj={s['risk_adjusted_apy']:.2f}%  "
              f"vs_rfr={s['excess_over_rfr']:+.2f}%")

    if args.run:
        save_log(result, data_file)
        print(f"\n  [written] → {data_file}")


if __name__ == "__main__":
    _main()
