"""
MP-812: ProtocolVolumeAnalyzer
Analyzes daily transaction volume trends as a leading indicator of protocol
health and TVL momentum.
Advisory/read-only. Pure Python stdlib only.

CLI:
    python3 -m spa_core.analytics.protocol_volume_analyzer --check
    python3 -m spa_core.analytics.protocol_volume_analyzer --run [--data-dir data]
"""

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

DATA_FILE = Path("data/protocol_volume_log.json")
MAX_ENTRIES = 100

DEFAULT_CONFIG: dict = {
    "ma_window": 7,
}

# Volume score: $1 billion = 60 base points
_LOG10_1B_PLUS_1 = math.log10(1e9 + 1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str):
    """Parse 'YYYY-MM-DD' → datetime.date. Raises ValueError on bad input."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _sma(values: list) -> float:
    """Simple moving average over the provided list. Returns 0.0 for empty."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _volume_trend(change_pct) -> str:
    """
    Map volume_change_7d_pct → trend label.

    > 50%   → SURGING
    > 10%   → GROWING
    >= -10% → STABLE
    >= -50% → DECLINING
    < -50%  → COLLAPSING
    If change_pct is None → STABLE
    """
    if change_pct is None:
        return "STABLE"
    if change_pct > 50.0:
        return "SURGING"
    if change_pct > 10.0:
        return "GROWING"
    if change_pct >= -10.0:
        return "STABLE"
    if change_pct >= -50.0:
        return "DECLINING"
    return "COLLAPSING"


def _volume_score(latest_volume_usd: float, trend: str, days_since_peak: int) -> int:
    """
    Composite volume score 0-100:
      base        = min(log10(vol+1) / log10(1e9+1) * 60, 60)  — log scale, $1B → 60
      trend bonus = SURGING+20, GROWING+15, STABLE+10, DECLINING+5, COLLAPSING+0
      peak bonus  = days_since_peak ≤ 7 → +20; ≤ 30 → +10; else → +0
    Clamped to [0, 100].
    """
    base = min(math.log10(latest_volume_usd + 1) / _LOG10_1B_PLUS_1 * 60.0, 60.0)
    trend_bonus = {
        "SURGING": 20,
        "GROWING": 15,
        "STABLE": 10,
        "DECLINING": 5,
        "COLLAPSING": 0,
    }[trend]
    if days_since_peak <= 7:
        peak_bonus = 20
    elif days_since_peak <= 30:
        peak_bonus = 10
    else:
        peak_bonus = 0
    return int(max(0, min(100, base + trend_bonus + peak_bonus)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocol: str, volume_history: list, config: dict = None) -> dict:
    """
    Analyze daily volume trends for a single protocol.

    Args:
        protocol: str — protocol identifier.
        volume_history: list[dict], each entry:
            {
                "date":       str   — "YYYY-MM-DD"
                "volume_usd": float — daily volume in USD
                "tx_count":   int   — number of transactions
            }
            Must be sorted ascending by date; must not be empty.
        config: optional dict:
            {"ma_window": int (default 7)}

    Returns:
        {
            "protocol":             str,
            "latest_volume_usd":    float,
            "latest_tx_count":      int,
            "volume_7d_avg":        float,       — ma_window-day (or available) SMA
            "volume_30d_avg":       float|None,  — None if < 30 entries
            "volume_change_7d_pct": float|None,  — None if < 14 entries or prev_avg==0
            "tx_count_7d_avg":      float,
            "avg_tx_size_usd":      float,
            "volume_trend":         str,
            "volume_score":         int,          — 0-100
            "peak_volume_usd":      float,
            "peak_date":            str,
            "days_since_peak":      int,
            "timestamp":            float,
        }
    """
    if not volume_history:
        raise ValueError("volume_history must not be empty")

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    ma_window = int(cfg.get("ma_window", DEFAULT_CONFIG["ma_window"]))

    n = len(volume_history)
    latest = volume_history[-1]
    latest_volume_usd = float(latest.get("volume_usd", 0.0))
    latest_tx_count = int(latest.get("tx_count", 0))
    latest_date_str = latest.get("date", "")

    # --- ma_window-day (or available) SMA ---
    window = min(ma_window, n)
    last_w = volume_history[-window:]
    vols_w = [float(e.get("volume_usd", 0.0)) for e in last_w]
    tx_w = [float(e.get("tx_count", 0)) for e in last_w]
    volume_7d_avg = _sma(vols_w)
    tx_count_7d_avg = _sma(tx_w)
    avg_tx_size_usd = (volume_7d_avg / tx_count_7d_avg
                       if tx_count_7d_avg > 0.0 else 0.0)

    # --- 30-day SMA ---
    if n >= 30:
        vols_30 = [float(e.get("volume_usd", 0.0)) for e in volume_history[-30:]]
        volume_30d_avg: float | None = _sma(vols_30)
    else:
        volume_30d_avg = None

    # --- 7d change vs prior 7d (needs ≥14 entries) ---
    if n >= 14:
        curr_7 = [float(e.get("volume_usd", 0.0)) for e in volume_history[-7:]]
        prev_7 = [float(e.get("volume_usd", 0.0)) for e in volume_history[-14:-7]]
        curr_avg = sum(curr_7) / 7.0
        prev_avg = sum(prev_7) / 7.0
        if prev_avg != 0.0:
            volume_change_7d_pct: float | None = (curr_avg / prev_avg - 1.0) * 100.0
        else:
            volume_change_7d_pct = None
    else:
        volume_change_7d_pct = None

    # --- Peak ---
    peak_entry = max(volume_history, key=lambda e: float(e.get("volume_usd", 0.0)))
    peak_volume_usd = float(peak_entry.get("volume_usd", 0.0))
    peak_date_str = peak_entry.get("date", "")

    try:
        latest_date = _parse_date(latest_date_str)
        peak_date = _parse_date(peak_date_str)
        days_since_peak = (latest_date - peak_date).days
    except Exception:
        days_since_peak = 0

    # --- Derived ---
    trend = _volume_trend(volume_change_7d_pct)
    score = _volume_score(latest_volume_usd, trend, days_since_peak)

    return {
        "protocol": protocol,
        "latest_volume_usd": latest_volume_usd,
        "latest_tx_count": latest_tx_count,
        "volume_7d_avg": volume_7d_avg,
        "volume_30d_avg": volume_30d_avg,
        "volume_change_7d_pct": volume_change_7d_pct,
        "tx_count_7d_avg": tx_count_7d_avg,
        "avg_tx_size_usd": avg_tx_size_usd,
        "volume_trend": trend,
        "volume_score": score,
        "peak_volume_usd": peak_volume_usd,
        "peak_date": peak_date_str,
        "days_since_peak": days_since_peak,
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
    """Return saved log entries; [] on any read / parse error."""
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

    parser = argparse.ArgumentParser(description="MP-812 ProtocolVolumeAnalyzer")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without writing (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically write result to data file")
    parser.add_argument("--data-dir", default="data", help="Data directory path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    # Synthetic demo history
    base_date = datetime(2026, 1, 1)
    demo_history = []
    import random
    random.seed(42)
    for i in range(30):
        d = (base_date.date().__class__)(2026, 1, 1)
        # advance by i days
        from datetime import timedelta
        entry_date = (datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        vol = 1_000_000 + random.uniform(-200_000, 500_000) * (1 + i * 0.02)
        demo_history.append({
            "date": entry_date,
            "volume_usd": round(vol, 2),
            "tx_count": random.randint(800, 2000),
        })

    result = analyze("demo_protocol", demo_history)

    print("[MP-812] ProtocolVolumeAnalyzer")
    print(f"  protocol             : {result['protocol']}")
    print(f"  latest_volume_usd    : ${result['latest_volume_usd']:,.0f}")
    print(f"  volume_7d_avg        : ${result['volume_7d_avg']:,.0f}")
    print(f"  volume_30d_avg       : "
          f"${result['volume_30d_avg']:,.0f}" if result['volume_30d_avg'] else
          "  volume_30d_avg       : N/A")
    print(f"  volume_change_7d_pct : "
          f"{result['volume_change_7d_pct']:.2f}%" if result['volume_change_7d_pct'] is not None else
          "  volume_change_7d_pct : N/A")
    print(f"  volume_trend         : {result['volume_trend']}")
    print(f"  volume_score         : {result['volume_score']}/100")
    print(f"  peak_volume_usd      : ${result['peak_volume_usd']:,.0f}")
    print(f"  peak_date            : {result['peak_date']}")
    print(f"  days_since_peak      : {result['days_since_peak']}")
    print(f"  avg_tx_size_usd      : ${result['avg_tx_size_usd']:,.2f}")

    if args.run:
        data_file = data_dir / "protocol_volume_log.json"
        save_result(result, data_file=data_file)
        print(f"  [written] → {data_file}")


if __name__ == "__main__":
    _main()
