"""
MP-639: PortfolioVolatilityTracker
Track rolling volatility of portfolio APY over time.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

from dataclasses import dataclass
from typing import List
import math, json, time, os
from pathlib import Path

DATA_FILE = Path("data/portfolio_volatility.json")
MAX_ENTRIES = 100
RING_BUFFER_SIZE = 90  # days of APY history to keep


@dataclass
class VolatilitySnapshot:
    timestamp: float
    apy_values: List[float]       # recent APY readings
    vol_7d: float                 # stdev of last 7 readings
    vol_30d: float                # stdev of last 30 readings
    vol_90d: float                # stdev of all readings (up to 90)
    regime: str                   # STABLE / MODERATE / HIGH / EXTREME
    trend: str                    # IMPROVING / STABLE / WORSENING (7d vs 30d vol)
    mean_apy: float
    cv: float                     # coefficient of variation = stdev/mean


class PortfolioVolatilityTracker:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file
        self._history: List[float] = []  # ring buffer of APY readings

    # ------------------------------------------------------------------
    # Internal math helpers
    # ------------------------------------------------------------------

    def _stdev(self, values: List[float]) -> float:
        """Sample standard deviation; returns 0.0 if fewer than 2 values."""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        return math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))

    def _classify_regime(self, vol_7d: float) -> str:
        """Classify volatility regime based on 7d stdev (APY decimal)."""
        if vol_7d < 0.005:
            return "STABLE"
        if vol_7d < 0.015:
            return "MODERATE"
        if vol_7d < 0.030:
            return "HIGH"
        return "EXTREME"

    def _classify_trend(self, vol_7d: float, vol_30d: float) -> str:
        """Compare recent (7d) vs medium-term (30d) vol to determine trend."""
        if vol_30d == 0:
            return "STABLE"
        ratio = vol_7d / vol_30d
        if ratio < 0.8:
            return "IMPROVING"
        if ratio > 1.25:
            return "WORSENING"
        return "STABLE"

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def add_reading(self, apy: float) -> None:
        """Add a new APY reading to the history buffer."""
        self._history.append(apy)
        if len(self._history) > RING_BUFFER_SIZE:
            self._history = self._history[-RING_BUFFER_SIZE:]

    def clear_history(self) -> None:
        """Reset the in-memory history buffer."""
        self._history = []

    def history_length(self) -> int:
        """Return current number of readings in memory."""
        return len(self._history)

    # ------------------------------------------------------------------
    # Snapshot computation
    # ------------------------------------------------------------------

    def compute_snapshot(self) -> VolatilitySnapshot:
        """Compute current volatility snapshot from in-memory history."""
        vals = self._history
        n = len(vals)

        v7  = self._stdev(vals[-7:])  if n >= 2 else 0.0
        v30 = self._stdev(vals[-30:]) if n >= 2 else 0.0
        v90 = self._stdev(vals)       if n >= 2 else 0.0

        mean = sum(vals) / n if n > 0 else 0.0
        cv   = v7 / mean if mean > 0.001 else 0.0

        return VolatilitySnapshot(
            timestamp=time.time(),
            apy_values=list(vals),
            vol_7d=round(v7, 6),
            vol_30d=round(v30, 6),
            vol_90d=round(v90, 6),
            regime=self._classify_regime(v7),
            trend=self._classify_trend(v7, v30),
            mean_apy=round(mean, 6),
            cv=round(cv, 4),
        )

    def get_current_regime(self) -> str:
        """Convenience: return regime string without saving."""
        return self.compute_snapshot().regime

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: VolatilitySnapshot) -> None:
        """Append snapshot to ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        existing.append({
            "timestamp": snapshot.timestamp,
            "apy_values_count": len(snapshot.apy_values),
            "vol_7d": snapshot.vol_7d,
            "vol_30d": snapshot.vol_30d,
            "vol_90d": snapshot.vol_90d,
            "regime": snapshot.regime,
            "trend": snapshot.trend,
            "mean_apy": snapshot.mean_apy,
            "cv": snapshot.cv,
        })
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load persisted snapshots from disk. Returns [] if file missing/invalid."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="MP-639 PortfolioVolatilityTracker")
    parser.add_argument("--check", action="store_true",
                        help="Load history and print latest snapshot (no write)")
    parser.add_argument("--run",   action="store_true",
                        help="Compute snapshot from history and save to disk")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory")
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "portfolio_volatility.json"

    tracker = PortfolioVolatilityTracker(data_file=data_file)

    # Seed from persisted snapshots so history is meaningful
    history = tracker.load_history()
    if history:
        for entry in history[-RING_BUFFER_SIZE:]:
            apy = entry.get("mean_apy", 0.0)
            if apy:
                tracker.add_reading(apy)

    snap = tracker.compute_snapshot()
    print(f"vol_7d={snap.vol_7d:.4%}  vol_30d={snap.vol_30d:.4%}  "
          f"vol_90d={snap.vol_90d:.4%}  regime={snap.regime}  "
          f"trend={snap.trend}  mean_apy={snap.mean_apy:.4%}  cv={snap.cv:.4f}")

    if args.run:
        tracker.save_snapshot(snap)
        print(f"Saved → {data_file}")


if __name__ == "__main__":
    _main()
