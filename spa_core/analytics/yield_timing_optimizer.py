"""
MP-788: YieldTimingOptimizer
Finds optimal entry/exit timing for yield positions based on historical patterns.
Pure stdlib, read-only analytics, atomic write, ring-buffer log (cap 100).
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

RING_BUFFER_CAP = 100
_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_timing_log.json"
)


class YieldTimingOptimizer:
    """
    Computes entry/exit timing signals for yield positions.

    Inputs (yield_data dict):
      - protocol         : str
      - apy_history      : list of (timestamp_ts: float, apy_pct: float)
      - current_apy      : float
      - hold_period_days : int (default 30)

    Outputs (optimize() return dict):
      - apy_percentile      : float  0-100
      - timing_score        : float  0-100
      - expected_apy_next_30d : float
      - entry_signal        : STRONG_BUY | BUY | HOLD | WAIT
      - historical_avg / std / min / max
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or os.path.normpath(_DEFAULT_LOG)
        self._result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, yield_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run timing analysis. Returns result dict and appends to ring-buffer log."""
        protocol: str = yield_data["protocol"]
        apy_history: List[Tuple[float, float]] = yield_data["apy_history"]
        current_apy: float = float(yield_data["current_apy"])
        hold_period_days: int = int(yield_data.get("hold_period_days", 30))

        if not apy_history:
            raise ValueError("apy_history must not be empty")

        apy_values: List[float] = [float(apy) for _, apy in apy_history]
        n = len(apy_values)

        # ── historical statistics ──────────────────────────────────────
        historical_avg: float = sum(apy_values) / n
        historical_min: float = min(apy_values)
        historical_max: float = max(apy_values)

        if n > 1:
            variance = sum((x - historical_avg) ** 2 for x in apy_values) / (n - 1)
            historical_std: float = math.sqrt(variance)
        else:
            historical_std = 0.0

        # ── APY percentile (fraction below current_apy) ────────────────
        below = sum(1 for v in apy_values if v < current_apy)
        apy_percentile: float = (below / n) * 100.0

        # ── timing score = percentile clamped to [0,100] ───────────────
        timing_score: float = min(100.0, max(0.0, apy_percentile))

        # ── EMA projection for next 30 days ────────────────────────────
        window = min(n, max(1, hold_period_days))
        alpha = 2.0 / (window + 1)
        ema: float = apy_values[0]
        for v in apy_values[1:]:
            ema = alpha * v + (1.0 - alpha) * ema
        # blend EMA with latest observed value
        expected_apy_next_30d: float = 0.7 * ema + 0.3 * current_apy

        # ── entry signal ───────────────────────────────────────────────
        entry_signal: str = self._compute_signal(apy_percentile)

        result: Dict[str, Any] = {
            "protocol": protocol,
            "current_apy": current_apy,
            "hold_period_days": hold_period_days,
            "apy_percentile": round(apy_percentile, 4),
            "timing_score": round(timing_score, 4),
            "expected_apy_next_30d": round(expected_apy_next_30d, 6),
            "entry_signal": entry_signal,
            "historical_avg": round(historical_avg, 6),
            "historical_std": round(historical_std, 6),
            "historical_min": round(historical_min, 6),
            "historical_max": round(historical_max, 6),
            "history_count": n,
            "timestamp": int(time.time()),
        }

        self._result = result
        self._append_log(result)
        return result

    def get_entry_signal(self) -> str:
        """Return entry_signal from last optimize() call."""
        if self._result is None:
            raise RuntimeError("Call optimize() before get_entry_signal()")
        return self._result["entry_signal"]

    def get_timing_score(self) -> float:
        """Return timing_score from last optimize() call."""
        if self._result is None:
            raise RuntimeError("Call optimize() before get_timing_score()")
        return self._result["timing_score"]

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the full result dict from the last optimize() call, or None."""
        return self._result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_signal(percentile: float) -> str:
        if percentile > 80:
            return "STRONG_BUY"
        if percentile > 60:
            return "BUY"
        if percentile > 40:
            return "HOLD"
        return "WAIT"

    def _append_log(self, entry: Dict[str, Any]) -> None:
        log = self._read_log()
        log.append(entry)
        if len(log) > RING_BUFFER_CAP:
            log = log[-RING_BUFFER_CAP:]
        self._write_log(log)

    def _read_log(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _write_log(self, log: List[Dict[str, Any]]) -> None:
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        tmp = self.log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, self.log_path)
