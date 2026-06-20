"""
MP-798: YieldDecayTracker
Tracks APY decay over time for liquidity-mining / incentive programs that emit
tokens at diminishing rates.  Projects future yield via linear regression.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer write (100 entries) → data/yield_decay_log.json
"""
from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DECAY_WINDOW_DAYS = 30
DEFAULT_PROJECTION_DAYS = 90
SECONDS_PER_DAY = 86_400.0
LOG_FILE = "data/yield_decay_log.json"
LOG_MAX = 100

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_config(config: dict | None) -> dict:
    cfg = config or {}
    return {
        "decay_window_days": int(cfg.get("decay_window_days", DEFAULT_DECAY_WINDOW_DAYS)),
        "projection_days": int(cfg.get("projection_days", DEFAULT_PROJECTION_DAYS)),
    }


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """
    Simple OLS linear regression: y = slope * x + intercept.
    Returns (slope, intercept). Requires len(xs) == len(ys) >= 2.
    """
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0.0:
        return 0.0, sum_y / n

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def _find_apy_at_offset(
    history: list[dict], now_ts: float, offset_seconds: float
) -> float | None:
    """
    Return the APY value closest to (now_ts - offset_seconds), or None if
    no entry exists within that window.
    """
    target_ts = now_ts - offset_seconds
    best = None
    best_delta = float("inf")
    for entry in history:
        delta = abs(entry["timestamp"] - target_ts)
        if delta < best_delta:
            best_delta = delta
            best = entry["apy"]
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocol: str, apy_history: list[dict], config: dict | None = None) -> dict:
    """
    Analyze APY decay for a single protocol.

    Parameters
    ----------
    protocol : str
    apy_history : list of {"timestamp": float, "apy": float}, ascending by timestamp.
        Minimum 2 entries required for regression; 1 entry → decay_rate = 0, STABLE.
    config : optional dict
        decay_window_days (default 30) — regression window
        projection_days   (default 90) — how far to project

    Returns
    -------
    dict with keys:
        protocol, current_apy, apy_7d_ago, apy_30d_ago,
        decay_rate_daily_pct, half_life_days, projected_apy_30d,
        projected_apy_90d, trend, sustainability_score,
        recommendation, timestamp
    """
    cfg = _resolve_config(config)
    decay_window = cfg["decay_window_days"]
    projection_days = cfg["projection_days"]

    history = sorted(apy_history or [], key=lambda e: e["timestamp"])

    # --- current APY ---
    current_apy: float = history[-1]["apy"] if history else 0.0
    now_ts: float = history[-1]["timestamp"] if history else time.time()

    # --- historical snapshots ---
    apy_7d_ago: float | None = None
    apy_30d_ago: float | None = None
    if len(history) >= 2:
        apy_7d_ago = _find_apy_at_offset(history[:-1], now_ts, 7 * SECONDS_PER_DAY)
        candidate_30 = _find_apy_at_offset(history[:-1], now_ts, 30 * SECONDS_PER_DAY)
        # Only report 30d if we actually have data that old
        earliest_ts = history[0]["timestamp"]
        if now_ts - earliest_ts >= 25 * SECONDS_PER_DAY:
            apy_30d_ago = candidate_30

    # --- linear regression over decay window ---
    cutoff_ts = now_ts - decay_window * SECONDS_PER_DAY
    window = [e for e in history if e["timestamp"] >= cutoff_ts]
    if len(window) < 2:
        window = history  # fall back to full history

    decay_rate_daily_pct = 0.0
    if len(window) >= 2:
        # Convert timestamps to days relative to first entry in window
        t0 = window[0]["timestamp"]
        xs = [(e["timestamp"] - t0) / SECONDS_PER_DAY for e in window]
        ys = [e["apy"] for e in window]
        slope, _ = _linear_regression(xs, ys)
        # slope positive → APY increasing (recovering)
        # slope negative → APY decreasing (decaying)
        # decay_rate_daily_pct = -slope (positive = decaying)
        decay_rate_daily_pct = -slope

    # --- trend ---
    if current_apy < 1.0:
        trend = "COLLAPSED"
    elif decay_rate_daily_pct > 0.5:
        trend = "DECAYING"
    elif decay_rate_daily_pct < -0.5:
        trend = "RECOVERING"
    else:
        trend = "STABLE"

    # --- projections (linear, floor 0) ---
    projected_apy_30d = max(0.0, current_apy - decay_rate_daily_pct * 30)
    projected_apy_90d = max(0.0, current_apy - decay_rate_daily_pct * projection_days)

    # --- half-life ---
    half_life_days: float | None = None
    if decay_rate_daily_pct > 0.0:
        half_life_days = (current_apy / 2.0) / decay_rate_daily_pct

    # --- sustainability score (0–100) ---
    score = 50
    if current_apy > 10:
        score += 30
    if trend in ("STABLE", "RECOVERING"):
        score += 20
    elif trend == "DECAYING":
        score -= 20
    elif trend == "COLLAPSED":
        score -= 50
    score = max(0, min(100, score))

    # --- recommendation ---
    if trend == "COLLAPSED" or (trend == "DECAYING" and projected_apy_30d < 3.0):
        recommendation = "EXIT"
    elif trend == "DECAYING" and projected_apy_30d >= 3.0:
        recommendation = "REDUCE"
    elif trend == "RECOVERING" and current_apy > 5.0:
        recommendation = "ENTER"
    else:
        recommendation = "HOLD"

    return {
        "protocol": protocol,
        "current_apy": round(current_apy, 6),
        "apy_7d_ago": round(apy_7d_ago, 6) if apy_7d_ago is not None else None,
        "apy_30d_ago": round(apy_30d_ago, 6) if apy_30d_ago is not None else None,
        "decay_rate_daily_pct": round(decay_rate_daily_pct, 6),
        "half_life_days": round(half_life_days, 4) if half_life_days is not None else None,
        "projected_apy_30d": round(projected_apy_30d, 6),
        "projected_apy_90d": round(projected_apy_90d, 6),
        "trend": trend,
        "sustainability_score": score,
        "recommendation": recommendation,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic write)
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(path))
def append_log(result: dict, log_path: str = LOG_FILE) -> None:
    """Append an analysis result to the ring-buffer log (capped at LOG_MAX)."""
    try:
        with open(log_path, "r") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > LOG_MAX:
        log = log[-LOG_MAX:]

    _atomic_write(log_path, log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_history() -> list[dict]:
    """Generate a sample 60-day decaying APY history."""
    base_ts = time.time() - 60 * SECONDS_PER_DAY
    return [
        {"timestamp": base_ts + i * SECONDS_PER_DAY, "apy": max(0.5, 20.0 - i * 0.25)}
        for i in range(61)
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-798 YieldDecayTracker")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--check", action="store_true", help="Compute and print (default)")
    parser.add_argument("--log", default=LOG_FILE, help="Path to log file")
    args = parser.parse_args()

    result = analyze("SampleProtocol", _sample_history())
    print(f"Protocol          : {result['protocol']}")
    print(f"Current APY       : {result['current_apy']:.2f}%")
    print(f"APY 7d ago        : {result['apy_7d_ago']}")
    print(f"APY 30d ago       : {result['apy_30d_ago']}")
    print(f"Decay rate/day    : {result['decay_rate_daily_pct']:.4f}%")
    print(f"Half-life         : {result['half_life_days']} days")
    print(f"Projected 30d     : {result['projected_apy_30d']:.2f}%")
    print(f"Projected 90d     : {result['projected_apy_90d']:.2f}%")
    print(f"Trend             : {result['trend']}")
    print(f"Sustainability    : {result['sustainability_score']}/100")
    print(f"Recommendation    : {result['recommendation']}")

    if args.run:
        append_log(result, args.log)
        print(f"\n✅ Written to {args.log}")
