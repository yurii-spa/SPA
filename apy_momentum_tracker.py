"""
MP-811: APYMomentumTracker
Tracks APY momentum across protocols using short/long EMA crossover signals.
Identifies protocols with accelerating or decelerating yield.
Advisory/read-only. Pure Python stdlib only.

CLI:
    python3 -m spa_core.analytics.apy_momentum_tracker --check
    python3 -m spa_core.analytics.apy_momentum_tracker --run [--data-dir data]
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/apy_momentum_log.json")
MAX_ENTRIES = 100

DEFAULT_CONFIG: dict = {
    "short_window": 7,
    "long_window": 21,
}


# ---------------------------------------------------------------------------
# Internal helpers (module-level, importable for unit testing)
# ---------------------------------------------------------------------------

def _compute_ema(values: list, window: int) -> float:
    """
    Compute Exponential Moving Average over all values using α = 2/(window+1).

    Formula:
        ema[0] = values[0]
        ema[i] = α * values[i] + (1 - α) * ema[i-1]

    All available values are used; ``window`` controls α only (not slice length).
    Returns 0.0 for an empty list.
    """
    if not values:
        return 0.0
    alpha = 2.0 / (window + 1)
    ema = float(values[0])
    for v in values[1:]:
        ema = alpha * float(v) + (1.0 - alpha) * ema
    return ema


def _classify_signal(momentum_pct: float) -> str:
    """
    Map momentum_pct → signal label.

    > 10%  → STRONG_BUY
    > 2%   → BUY
    >= -2% → NEUTRAL
    >= -10%→ SELL
    < -10% → STRONG_SELL
    """
    if momentum_pct > 10.0:
        return "STRONG_BUY"
    if momentum_pct > 2.0:
        return "BUY"
    if momentum_pct >= -2.0:
        return "NEUTRAL"
    if momentum_pct >= -10.0:
        return "SELL"
    return "STRONG_SELL"


def _classify_trend(current_apy: float, ema_short: float) -> str:
    """
    Classify yield trend by comparing current_apy vs short EMA.

    ACCELERATING : current_apy > ema_short * 1.02
    DECELERATING : current_apy < ema_short * 0.98
    STABLE       : otherwise (or if ema_short == 0)
    """
    if ema_short == 0.0:
        return "STABLE"
    if current_apy > ema_short * 1.02:
        return "ACCELERATING"
    if current_apy < ema_short * 0.98:
        return "DECELERATING"
    return "STABLE"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze APY momentum for a list of protocols via short/long EMA crossover.

    Args:
        protocols: list of dicts:
            {
                "name":        str          — protocol identifier
                "apy_history": list[float]  — APY values oldest-first; ≥1 for output
            }
            Protocols with empty apy_history are silently skipped.

        config: optional dict:
            {
                "short_window": int  (default 7)  — period for short EMA alpha
                "long_window":  int  (default 21) — period for long EMA alpha
            }

    Returns:
        {
            "protocols":        list[dict],   — per-protocol analysis
            "top_momentum":     str,          — name with highest momentum_pct
            "bottom_momentum":  str,          — name with most negative momentum_pct
            "bullish_count":    int,          — STRONG_BUY + BUY count
            "bearish_count":    int,          — STRONG_SELL + SELL count
            "market_sentiment": str,          — BULLISH | NEUTRAL | BEARISH
            "timestamp":        float,        — epoch seconds
        }

        Per-protocol dict:
            "name", "current_apy", "ema_short", "ema_long",
            "momentum", "momentum_pct", "signal", "trend"
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    short_w = int(cfg.get("short_window", DEFAULT_CONFIG["short_window"]))
    long_w = int(cfg.get("long_window", DEFAULT_CONFIG["long_window"]))

    protocol_results: list = []

    for proto in protocols:
        name = proto.get("name", "unknown")
        history = proto.get("apy_history", [])

        if not history:
            continue  # skip protocols with no data

        current_apy = float(history[-1])

        if len(history) == 1:
            # Single data point — both EMAs equal the sole value
            ema_short = current_apy
            ema_long = current_apy
            momentum = 0.0
            momentum_pct = 0.0
            signal = "NEUTRAL"
            trend = "STABLE"
        else:
            ema_short = _compute_ema(history, short_w)
            ema_long = _compute_ema(history, long_w)
            momentum = ema_short - ema_long
            momentum_pct = (momentum / ema_long * 100.0) if ema_long != 0.0 else 0.0
            signal = _classify_signal(momentum_pct)
            trend = _classify_trend(current_apy, ema_short)

        protocol_results.append({
            "name": name,
            "current_apy": current_apy,
            "ema_short": ema_short,
            "ema_long": ema_long,
            "momentum": momentum,
            "momentum_pct": momentum_pct,
            "signal": signal,
            "trend": trend,
        })

    bullish_signals = {"STRONG_BUY", "BUY"}
    bearish_signals = {"STRONG_SELL", "SELL"}
    bullish_count = sum(1 for r in protocol_results if r["signal"] in bullish_signals)
    bearish_count = sum(1 for r in protocol_results if r["signal"] in bearish_signals)

    if protocol_results:
        top_momentum = max(protocol_results, key=lambda r: r["momentum_pct"])["name"]
        bottom_momentum = min(protocol_results, key=lambda r: r["momentum_pct"])["name"]
    else:
        top_momentum = ""
        bottom_momentum = ""

    if bullish_count > bearish_count:
        market_sentiment = "BULLISH"
    elif bearish_count > bullish_count:
        market_sentiment = "BEARISH"
    else:
        market_sentiment = "NEUTRAL"

    return {
        "protocols": protocol_results,
        "top_momentum": top_momentum,
        "bottom_momentum": bottom_momentum,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "market_sentiment": market_sentiment,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_result(result: dict, data_file: Path = DATA_FILE) -> None:
    """
    Atomically append *result* to a ring-buffer JSON log capped at MAX_ENTRIES.
    Uses tmp-file + os.replace for crash-safe writes.
    """
    data_file = Path(data_file)
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
    """Return saved log entries; returns [] on any read / parse error."""
    try:
        data = json.loads(Path(data_file).read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-811 APYMomentumTracker")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without writing (default behaviour)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically write result to data file")
    parser.add_argument("--data-dir", default="data", help="Data directory path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    protocols: list = []
    equity_file = data_dir / "equity_curve_daily.json"
    try:
        records = json.loads(equity_file.read_text())
        if isinstance(records, list) and records:
            series = [
                float(r.get("apy", r.get("daily_return", 0.0)))
                for r in records if isinstance(r, dict)
            ]
            if series:
                protocols.append({"name": "portfolio", "apy_history": series})
    except Exception:
        pass

    if not protocols:
        print("[MP-811] No equity curve data — using synthetic demo")
        protocols = [
            {
                "name": "aave_v3",
                "apy_history": [0.030, 0.031, 0.032, 0.033, 0.035, 0.037, 0.040,
                                 0.042, 0.044, 0.046, 0.048, 0.050],
            },
            {
                "name": "compound_v3",
                "apy_history": [0.048, 0.047, 0.046, 0.045, 0.044, 0.043, 0.042,
                                 0.041, 0.040, 0.039, 0.038, 0.037],
            },
        ]

    result = analyze(protocols)

    print("[MP-811] APYMomentumTracker")
    print(f"  market_sentiment : {result['market_sentiment']}")
    print(f"  bullish_count    : {result['bullish_count']}")
    print(f"  bearish_count    : {result['bearish_count']}")
    print(f"  top_momentum     : {result['top_momentum']}")
    print(f"  bottom_momentum  : {result['bottom_momentum']}")
    for p in result["protocols"]:
        print(
            f"  [{p['name']}] "
            f"apy={p['current_apy']:.4f} "
            f"ema_s={p['ema_short']:.6f} "
            f"ema_l={p['ema_long']:.6f} "
            f"mom_pct={p['momentum_pct']:.2f}% "
            f"signal={p['signal']} "
            f"trend={p['trend']}"
        )

    if args.run:
        data_file = data_dir / "apy_momentum_log.json"
        save_result(result, data_file=data_file)
        print(f"  [written] → {data_file}")


if __name__ == "__main__":
    _main()
