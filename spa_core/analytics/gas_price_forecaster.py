"""
MP-790: GasPriceForecaster
Forecasts near-term gas prices and optimal transaction timing.

CLI:
    python3 -m spa_core.analytics.gas_price_forecaster --check
    python3 -m spa_core.analytics.gas_price_forecaster --run
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional, Tuple

from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "gas_price_forecast_log.json"
)
LOG_CAP = 100
EMA_ALPHA = 0.3
EMA_LOOKBACK = 6
GAS_LIMIT_SIMPLE_TRANSFER = 21_000


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TxUrgency(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    FLEXIBLE = "FLEXIBLE"
    PATIENT = "PATIENT"


class GasRegime(str, Enum):
    CHEAP = "CHEAP"
    NORMAL = "NORMAL"
    EXPENSIVE = "EXPENSIVE"
    VERY_EXPENSIVE = "VERY_EXPENSIVE"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GasForecastResult:
    timestamp: float
    current_gwei: float
    rolling_avg_1h: Optional[float]
    rolling_avg_24h: Optional[float]
    percentile_current: float          # 0–100
    forecast_1h: float
    optimal_window: str
    gas_regime: str
    estimated_tx_cost_usd: float
    eth_price_usd: float
    urgency: str
    data_points_used: int

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core forecaster
# ---------------------------------------------------------------------------

class GasPriceForecaster:
    """
    Forecasts gas prices and classifies gas regime.
    All computation is pure-stdlib, offline.
    """

    def __init__(self, log_path: str = LOG_PATH_DEFAULT):
        self._log_path = log_path
        self._last_result: Optional[GasForecastResult] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        gas_data: dict,
        eth_price_usd: float = 3000.0,
    ) -> GasForecastResult:
        """
        gas_data keys:
            gas_history: List[Tuple[float, float]]  — (timestamp_ts, gwei_price)
            current_gwei: float
            tx_urgency: "IMMEDIATE" | "FLEXIBLE" | "PATIENT"
        """
        history: List[Tuple[float, float]] = [
            (float(ts), float(gwei))
            for ts, gwei in gas_data.get("gas_history", [])
        ]
        current_gwei: float = float(gas_data.get("current_gwei", 0.0))
        urgency_raw: str = str(gas_data.get("tx_urgency", "FLEXIBLE")).upper()
        try:
            urgency = TxUrgency(urgency_raw)
        except ValueError:
            urgency = TxUrgency.FLEXIBLE

        now = time.time()

        # Sort history ascending
        history_sorted = sorted(history, key=lambda x: x[0])

        # Rolling averages
        rolling_avg_1h = self._rolling_avg(history_sorted, now, window_seconds=3600)
        rolling_avg_24h = self._rolling_avg(history_sorted, now, window_seconds=86400)

        # Percentile of current within 24h distribution
        prices_24h = self._prices_in_window(history_sorted, now, 86400)
        percentile_current = self._percentile(current_gwei, prices_24h)

        # 1h EMA forecast using last EMA_LOOKBACK data points
        forecast_1h = self._ema_forecast(history_sorted, current_gwei)

        # Gas regime
        regime = self._classify_regime(percentile_current)

        # Optimal tx window
        optimal_window = self._optimal_window(urgency, history_sorted, now)

        # Estimated tx cost
        estimated_tx_cost_usd = self._tx_cost_usd(current_gwei, eth_price_usd)

        result = GasForecastResult(
            timestamp=now,
            current_gwei=current_gwei,
            rolling_avg_1h=rolling_avg_1h,
            rolling_avg_24h=rolling_avg_24h,
            percentile_current=round(percentile_current, 2),
            forecast_1h=round(forecast_1h, 4),
            optimal_window=optimal_window,
            gas_regime=regime.value,
            estimated_tx_cost_usd=round(estimated_tx_cost_usd, 6),
            eth_price_usd=eth_price_usd,
            urgency=urgency.value,
            data_points_used=len(history_sorted),
        )
        self._last_result = result
        return result

    def get_gas_regime(self) -> Optional[str]:
        """Return gas regime from most recent forecast, or None."""
        if self._last_result is None:
            return None
        return self._last_result.gas_regime

    def get_optimal_tx_window(self) -> Optional[str]:
        """Return optimal tx window from most recent forecast, or None."""
        if self._last_result is None:
            return None
        return self._last_result.optimal_window

    # ------------------------------------------------------------------
    # Log persistence
    # ------------------------------------------------------------------

    def append_log(self, result: GasForecastResult, log_path: Optional[str] = None) -> None:
        """Atomically append result to ring-buffer log (max LOG_CAP entries)."""
        path = log_path or self._log_path
        self._ensure_dir(path)
        entries = self._read_log(path)
        entries.append(result.to_dict())
        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]
        self._write_log(path, entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rolling_avg(
        history: List[Tuple[float, float]],
        now: float,
        window_seconds: float,
    ) -> Optional[float]:
        cutoff = now - window_seconds
        prices = [gwei for ts, gwei in history if ts >= cutoff]
        if not prices:
            return None
        return round(sum(prices) / len(prices), 4)

    @staticmethod
    def _prices_in_window(
        history: List[Tuple[float, float]],
        now: float,
        window_seconds: float,
    ) -> List[float]:
        cutoff = now - window_seconds
        return [gwei for ts, gwei in history if ts >= cutoff]

    @staticmethod
    def _percentile(value: float, data: List[float]) -> float:
        """Return what percentile `value` sits at in `data` (0–100)."""
        if not data:
            return 50.0
        below = sum(1 for x in data if x < value)
        return round(below / len(data) * 100, 2)

    @staticmethod
    def _ema_forecast(
        history: List[Tuple[float, float]],
        current_gwei: float,
    ) -> float:
        """
        EMA with alpha=0.3 applied to last EMA_LOOKBACK data points
        (plus current as the final observation).
        """
        recent = [gwei for _, gwei in history[-EMA_LOOKBACK:]]
        recent.append(current_gwei)

        if not recent:
            return current_gwei

        ema = recent[0]
        for price in recent[1:]:
            ema = EMA_ALPHA * price + (1 - EMA_ALPHA) * ema
        return round(ema, 4)

    @staticmethod
    def _classify_regime(percentile: float) -> GasRegime:
        if percentile < 20:
            return GasRegime.CHEAP
        elif percentile < 70:
            return GasRegime.NORMAL
        elif percentile < 90:
            return GasRegime.EXPENSIVE
        else:
            return GasRegime.VERY_EXPENSIVE

    @staticmethod
    def _optimal_window(
        urgency: TxUrgency,
        history: List[Tuple[float, float]],
        now: float,
    ) -> str:
        if urgency == TxUrgency.IMMEDIATE:
            return "now"

        if urgency == TxUrgency.FLEXIBLE:
            # Find lowest-average 4-hour block in available history
            window_sec = 4 * 3600
            if not history:
                return "next 4h"
            # Slide a 4h window across the 24h history
            cutoff_24h = now - 86400
            hist_24h = [(ts, g) for ts, g in history if ts >= cutoff_24h]
            if not hist_24h:
                return "next 4h"
            best_avg = math.inf
            best_label = "next 4h"
            # Build candidate windows (step 1h)
            min_ts = hist_24h[0][0]
            max_ts = hist_24h[-1][0]
            step = 3600
            t = min_ts
            while t + window_sec <= max_ts + step:
                block = [g for ts, g in hist_24h if t <= ts < t + window_sec]
                if block:
                    avg = sum(block) / len(block)
                    if avg < best_avg:
                        best_avg = avg
                        # Express as time offset from now
                        offset_h = (t - now) / 3600
                        if offset_h < 0:
                            best_label = "next 4h"
                        else:
                            best_label = f"in ~{max(1, round(offset_h))}h"
                t += step
            return best_label

        # PATIENT: scan full 24h history for lowest individual hour
        if urgency == TxUrgency.PATIENT:
            if not history:
                return "next 24h"
            cutoff_24h = now - 86400
            hist_24h = [(ts, g) for ts, g in history if ts >= cutoff_24h]
            if not hist_24h:
                return "next 24h"
            # Find hour bucket with lowest average
            best_avg = math.inf
            best_label = "next 24h"
            for h in range(24):
                t_start = now - 86400 + h * 3600
                block = [g for ts, g in hist_24h if t_start <= ts < t_start + 3600]
                if block:
                    avg = sum(block) / len(block)
                    if avg < best_avg:
                        best_avg = avg
                        offset_h = (t_start - now) / 3600
                        if offset_h < 0:
                            best_label = "next 24h"
                        else:
                            best_label = f"in ~{max(1, round(offset_h))}h"
            return best_label

        return "next 24h"

    @staticmethod
    def _tx_cost_usd(gwei: float, eth_price_usd: float) -> float:
        """Cost = gwei * 21000 / 1e9 * eth_price_usd"""
        return gwei * GAS_LIMIT_SIMPLE_TRANSFER / 1e9 * eth_price_usd

    @staticmethod
    def _read_log(path: str) -> list:
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    @staticmethod
    def _write_log(path: str, entries: list) -> None:
        dir_ = os.path.dirname(path) or "."
        os.makedirs(dir_, exist_ok=True)
        atomic_save(entries, str(path))

    @staticmethod
    def _ensure_dir(path: str) -> None:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _make_demo_data() -> dict:
    """Generate a sample 24h gas history for demo/check mode."""
    now = time.time()
    history = []
    import random
    random.seed(42)
    base_gwei = 25.0
    for i in range(288):  # 5-min intervals over 24h
        ts = now - 86400 + i * 300
        gwei = max(1.0, base_gwei + random.gauss(0, 5))
        history.append((ts, round(gwei, 2)))
    return {
        "gas_history": history,
        "current_gwei": 22.5,
        "tx_urgency": "FLEXIBLE",
    }


def main(args=None):
    import argparse
    parser = argparse.ArgumentParser(description="MP-790 GasPriceForecaster")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument("--eth-price", type=float, default=3000.0, help="ETH price in USD")
    parsed = parser.parse_args(args)

    log_path = LOG_PATH_DEFAULT
    if parsed.data_dir:
        log_path = os.path.join(parsed.data_dir, "gas_price_forecast_log.json")

    forecaster = GasPriceForecaster(log_path=log_path)
    demo_data = _make_demo_data()
    result = forecaster.forecast(demo_data, eth_price_usd=parsed.eth_price)

    print("=== GasPriceForecaster (MP-790) ===")
    print(f"  current_gwei       : {result.current_gwei}")
    print(f"  rolling_avg_1h     : {result.rolling_avg_1h}")
    print(f"  rolling_avg_24h    : {result.rolling_avg_24h}")
    print(f"  percentile_current : {result.percentile_current:.1f}%")
    print(f"  forecast_1h        : {result.forecast_1h} gwei")
    print(f"  gas_regime         : {result.gas_regime}")
    print(f"  optimal_window     : {result.optimal_window}")
    print(f"  est_tx_cost_usd    : ${result.estimated_tx_cost_usd:.4f}")
    print(f"  urgency            : {result.urgency}")
    print(f"  data_points_used   : {result.data_points_used}")

    if parsed.run:
        forecaster.append_log(result, log_path)
        print(f"\n✅ Appended to {log_path}")
    else:
        print("\n(dry-run — use --run to persist)")


if __name__ == "__main__":
    main()
