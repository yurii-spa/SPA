"""
MP-648: VolatilityRegimeDetector
Classify current market regime based on rolling APY volatility.

Advisory / read-only analytics module.
Pure stdlib. Atomic writes. Ring-buffer 100 entries.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict
import json
import time
import os
import math
from pathlib import Path

DATA_FILE = Path("data/volatility_regime_log.json")
MAX_ENTRIES = 100

# Regimes are checked in descending threshold order.
# vol >= threshold → that regime.
REGIMES: Dict[str, Dict] = {
    "CRISIS":   {"vol_threshold": 0.040, "label": "Crisis — extreme APY swings"},
    "STRESSED": {"vol_threshold": 0.025, "label": "Stressed — elevated volatility"},
    "NORMAL":   {"vol_threshold": 0.010, "label": "Normal — typical market conditions"},
    "CALM":     {"vol_threshold": 0.000, "label": "Calm — very stable yields"},
}

_ADVISORIES = {
    "CRISIS":   "⛔ Suspend new allocations. Review all positions. Activate kill-switch check.",
    "STRESSED": "⚠️ Reduce T2/T3 exposure. Prefer T1 only. Monitor hourly.",
    "NORMAL":   "✅ Normal operations. Standard rebalance schedule.",
    "CALM":     "💤 Low volatility. Good time for entries. Watch for regime change.",
}


@dataclass
class RegimeSnapshot:
    timestamp: float
    strategy_id: str
    current_vol: float       # 14-day rolling stdev of APY
    regime: str              # CRISIS / STRESSED / NORMAL / CALM
    regime_label: str
    days_in_regime: int      # consecutive days in current regime (including today)
    regime_changed: bool     # True if regime changed vs previous snapshot
    prev_regime: Optional[str]
    advisory: str            # actionable guidance


class VolatilityRegimeDetector:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file
        self._vol_window = 14

    def _stdev(self, values: List[float]) -> float:
        """Sample standard deviation. Returns 0.0 for < 2 values."""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        return math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))

    def _classify_regime(self, vol: float) -> str:
        """Map volatility scalar to regime string."""
        if vol >= REGIMES["CRISIS"]["vol_threshold"]:
            return "CRISIS"
        if vol >= REGIMES["STRESSED"]["vol_threshold"]:
            return "STRESSED"
        if vol >= REGIMES["NORMAL"]["vol_threshold"]:
            return "NORMAL"
        return "CALM"

    def _advisory(self, regime: str) -> str:
        """Return actionable guidance for a regime."""
        return _ADVISORIES[regime]

    def _days_in_regime(self, history: List[dict], regime: str) -> int:
        """Count consecutive trailing entries that share the given regime, +1 for today."""
        count = 0
        for entry in reversed(history):
            if entry.get("regime") == regime:
                count += 1
            else:
                break
        return count + 1  # include current day

    def detect(
        self,
        strategy_id: str,
        apy_series: List[float],
        history: Optional[List[dict]] = None,
    ) -> RegimeSnapshot:
        """Detect current regime from the last `_vol_window` APY readings."""
        window = apy_series[-self._vol_window:] if len(apy_series) >= 2 else apy_series
        current_vol = self._stdev(window)
        regime = self._classify_regime(current_vol)

        history = history or []
        prev_regime = history[-1].get("regime") if history else None
        regime_changed = prev_regime is not None and prev_regime != regime
        days_in = self._days_in_regime(history, regime)

        return RegimeSnapshot(
            timestamp=time.time(),
            strategy_id=strategy_id,
            current_vol=round(current_vol, 6),
            regime=regime,
            regime_label=REGIMES[regime]["label"],
            days_in_regime=days_in,
            regime_changed=regime_changed,
            prev_regime=prev_regime,
            advisory=self._advisory(regime),
        )

    def save_snapshot(self, snapshot: RegimeSnapshot) -> None:
        """Append snapshot to ring-buffer JSON (max MAX_ENTRIES), atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        existing.append(
            {
                "timestamp": snapshot.timestamp,
                "strategy_id": snapshot.strategy_id,
                "current_vol": snapshot.current_vol,
                "regime": snapshot.regime,
                "regime_label": snapshot.regime_label,
                "days_in_regime": snapshot.days_in_regime,
                "regime_changed": snapshot.regime_changed,
                "prev_regime": snapshot.prev_regime,
                "advisory": snapshot.advisory,
            }
        )
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load persisted snapshots. Returns [] if file missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []

    def get_regime_transitions(self, history: List[dict]) -> List[dict]:
        """Return only entries where the regime changed."""
        return [h for h in history if h.get("regime_changed", False)]


# ---------------------------------------------------------------------------
# CLI entry point (advisory, read-only)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="MP-648 VolatilityRegimeDetector")
    parser.add_argument("--check", action="store_true", default=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "volatility_regime_log.json"

    detector = VolatilityRegimeDetector(data_file=data_file)
    history = detector.load_history()
    print(f"MP-648 VolatilityRegimeDetector — {len(history)} snapshots persisted")
    sys.exit(0)
