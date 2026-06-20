"""
Yield Forecast Engine (MP-615)
==============================
Advisory-only linear APY extrapolation for 1-day, 7-day, and 30-day horizons.

Uses OLS (Ordinary Least Squares) slope over historical APY series to project
future APY for each adapter, and aggregates into a portfolio-level forecast.

⚠️  ADVISORY ONLY — This module produces estimates based on past APY trends.
    Past performance does NOT guarantee future returns.
    NOT financial advice.

Data source (read-only):
    data/watchdog_history.json  — ring-buffer of WatchdogReport snapshots

Output (ring-buffer 48 entries):
    data/yield_forecast.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Read-only over source files; atomic write to data/yield_forecast.json only.
* Atomic writes: tmp + os.replace (POSIX-safe, cleanup on failure).
* Never raises on the happy path; missing / malformed data degrades gracefully.
* NOT imported from risk/, execution/, monitoring/, allocator/, cycle_runner.
* Deterministic: identical input → identical output.

Trend classification (OLS slope %/day):
    |slope| < 0.01 → STABLE
    slope  >  0    → RISING
    else           → FALLING

Confidence classification (data points):
    ≥ 10 → HIGH
    5–9  → MEDIUM
    < 5  → LOW

Forecast caps:
    MIN_APY = 0.0%
    MAX_APY = 25.0%

CLI
---
``python3 -m spa_core.analytics.yield_forecast --check``    (compute + print, no write)
``python3 -m spa_core.analytics.yield_forecast --run``      (+ atomic save)
``python3 -m spa_core.analytics.yield_forecast --data-dir PATH``

MP-615.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_WATCHDOG_HISTORY_FILE = "watchdog_history.json"
_OUTPUT_FILE = "yield_forecast.json"
_RING_BUFFER_MAX = 48

_ADVISORY_NOTE = (
    "Advisory only. Past APY trends do not guarantee future returns."
)
_DISCLAIMER = "ADVISORY ONLY: This is not financial advice."
_TELEGRAM_MAX_CHARS = 1500

# Trend thresholds
_STABLE_THRESHOLD: float = 0.01   # %/day — |slope| below this → STABLE

# Confidence thresholds
_HIGH_CONFIDENCE_MIN: int = 10
_MEDIUM_CONFIDENCE_MIN: int = 5


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdapterForecast:
    """Linear APY forecast for a single adapter."""
    adapter_key: str
    current_apy_pct: float
    data_points: int
    slope_pct_per_day: float      # OLS slope in APY%/day
    forecast_1d: float            # current_apy + slope * 1  (clamped)
    forecast_7d: float            # current_apy + slope * 7  (clamped)
    forecast_30d: float           # current_apy + slope * 30 (clamped)
    trend: str                    # "RISING" / "FALLING" / "STABLE"
    confidence: str               # "HIGH" / "MEDIUM" / "LOW"
    advisory_note: str = field(
        default=_ADVISORY_NOTE
    )


@dataclass
class PortfolioForecast:
    """Aggregated portfolio-level forecast across all adapters."""
    generated_at: str
    adapters: List[AdapterForecast] = field(default_factory=list)
    portfolio_current_apy: float = 0.0
    portfolio_forecast_1d: float = 0.0
    portfolio_forecast_7d: float = 0.0
    portfolio_forecast_30d: float = 0.0
    portfolio_trend: str = "STABLE"   # majority vote
    high_confidence_count: int = 0
    low_data_warning: bool = False
    disclaimer: str = _DISCLAIMER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
def _safe_float(val: object) -> Optional[float]:
    """Return float if val is a non-bool numeric, else None."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    return None


# ---------------------------------------------------------------------------
# YieldForecastEngine
# ---------------------------------------------------------------------------

class YieldForecastEngine:
    """
    Advisory-only yield forecast engine.

    Reads historical APY data from data/watchdog_history.json, computes OLS
    linear slope per adapter, and projects APY forward 1/7/30 days.

    Parameters
    ----------
    data_path : str | None
        Path to the data/ directory. Defaults to the project's data/.
    """

    MAX_APY: float = 25.0
    MIN_APY: float = 0.0

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            p = Path(data_path)
            self._data_dir = p if p.is_dir() else p.parent
        self._watchdog_path = self._data_dir / _WATCHDOG_HISTORY_FILE
        self._output_path = self._data_dir / _OUTPUT_FILE
        self._cached_forecast: Optional[PortfolioForecast] = None

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_apy_history(self) -> Dict[str, List[float]]:
        """
        Read data/watchdog_history.json and extract per-adapter APY series.

        Returns
        -------
        dict[adapter_key, list[apy_pct]]
            Chronological APY% values per adapter (oldest → newest).
            Returns {} on any error or if the file is absent.
        """
        try:
            if not self._watchdog_path.exists():
                return {}
            raw = self._watchdog_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}

            snapshots = data.get("snapshots", [])
            if not isinstance(snapshots, list):
                return {}

            # Collect (adapter_key → list of apy values), snapshot order = chronological
            history: Dict[str, List[float]] = {}

            for snap in snapshots:
                if not isinstance(snap, dict):
                    continue
                statuses = snap.get("adapter_statuses", [])
                if not isinstance(statuses, list):
                    continue
                for entry in statuses:
                    if not isinstance(entry, dict):
                        continue
                    # Adapter key resolution
                    key = (
                        entry.get("adapter_key")
                        or entry.get("protocol_key")
                        or entry.get("adapter_id")
                        or entry.get("id")
                    )
                    if not isinstance(key, str) or not key:
                        continue
                    # APY resolution
                    apy = None
                    for field_name in ("apy_pct", "apy"):
                        v = _safe_float(entry.get(field_name))
                        if v is not None and v >= 0:
                            apy = v
                            break
                    if apy is None:
                        continue
                    if key not in history:
                        history[key] = []
                    history[key].append(apy)

            return history
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Core statistics
    # ------------------------------------------------------------------

    def ols_slope(self, values: List[float]) -> float:
        """
        Compute OLS linear slope for a series of APY values.

        Uses integer x-indices: x = [0, 1, 2, ..., n-1].
        Formula:
            slope = (n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)

        Returns 0.0 when n < 2 or the denominator is 0.

        Parameters
        ----------
        values : list[float]
            Chronological APY% values (oldest first).
        """
        n = len(values)
        if n < 2:
            return 0.0

        sum_x: float = 0.0
        sum_y: float = 0.0
        sum_xy: float = 0.0
        sum_x2: float = 0.0

        for i, y in enumerate(values):
            x = float(i)
            sum_x += x
            sum_y += float(y)
            sum_xy += x * float(y)
            sum_x2 += x * x

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0.0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def clamp(self, value: float) -> float:
        """Clamp *value* to [MIN_APY, MAX_APY]."""
        return max(self.MIN_APY, min(self.MAX_APY, value))

    def classify_trend(self, slope: float) -> str:
        """
        Classify OLS slope into a trend label.

        Rules:
            |slope| < 0.01 → "STABLE"
            slope  > 0     → "RISING"
            slope  < 0     → "FALLING"
        """
        if abs(slope) < _STABLE_THRESHOLD:
            return "STABLE"
        if slope > 0:
            return "RISING"
        return "FALLING"

    def classify_confidence(self, n: int) -> str:
        """
        Classify number of data points into a confidence level.

        Rules:
            n ≥ 10 → "HIGH"
            5 ≤ n < 10 → "MEDIUM"
            n < 5  → "LOW"
        """
        if n >= _HIGH_CONFIDENCE_MIN:
            return "HIGH"
        if n >= _MEDIUM_CONFIDENCE_MIN:
            return "MEDIUM"
        return "LOW"

    # ------------------------------------------------------------------
    # Per-adapter forecast
    # ------------------------------------------------------------------

    def forecast_adapter(
        self, key: str, history: List[float]
    ) -> AdapterForecast:
        """
        Compute a linear APY forecast for a single adapter.

        Parameters
        ----------
        key : str
            Adapter identifier.
        history : list[float]
            Chronological APY% values (oldest first).
        """
        n = len(history)
        current = history[-1] if history else 0.0
        slope = self.ols_slope(history)

        forecast_1d = self.clamp(current + slope * 1)
        forecast_7d = self.clamp(current + slope * 7)
        forecast_30d = self.clamp(current + slope * 30)

        return AdapterForecast(
            adapter_key=key,
            current_apy_pct=round(current, 6),
            data_points=n,
            slope_pct_per_day=round(slope, 8),
            forecast_1d=round(forecast_1d, 6),
            forecast_7d=round(forecast_7d, 6),
            forecast_30d=round(forecast_30d, 6),
            trend=self.classify_trend(slope),
            confidence=self.classify_confidence(n),
            advisory_note=_ADVISORY_NOTE,
        )

    # ------------------------------------------------------------------
    # Portfolio forecast
    # ------------------------------------------------------------------

    def generate_forecast(self) -> PortfolioForecast:
        """
        Generate a portfolio-level APY forecast for all adapters.

        Reads watchdog_history.json, computes per-adapter forecasts, and
        aggregates into a portfolio-level view using equal-weight averaging.

        Returns
        -------
        PortfolioForecast
            Full forecast object. If no history is available, returns an
            empty forecast with low_data_warning=True.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        history_map = self.load_apy_history()

        if not history_map:
            result = PortfolioForecast(
                generated_at=now_iso,
                adapters=[],
                portfolio_current_apy=0.0,
                portfolio_forecast_1d=0.0,
                portfolio_forecast_7d=0.0,
                portfolio_forecast_30d=0.0,
                portfolio_trend="STABLE",
                high_confidence_count=0,
                low_data_warning=True,
                disclaimer=_DISCLAIMER,
            )
            self._cached_forecast = result
            return result

        # Build per-adapter forecasts (sorted by key for determinism)
        adapter_forecasts: List[AdapterForecast] = []
        for key in sorted(history_map.keys()):
            af = self.forecast_adapter(key, history_map[key])
            adapter_forecasts.append(af)

        # Portfolio aggregates (equal-weight average)
        n_adapters = len(adapter_forecasts)
        portfolio_current = sum(a.current_apy_pct for a in adapter_forecasts) / n_adapters
        portfolio_1d = sum(a.forecast_1d for a in adapter_forecasts) / n_adapters
        portfolio_7d = sum(a.forecast_7d for a in adapter_forecasts) / n_adapters
        portfolio_30d = sum(a.forecast_30d for a in adapter_forecasts) / n_adapters

        # Portfolio trend: majority vote
        trend_counts: Dict[str, int] = {"RISING": 0, "FALLING": 0, "STABLE": 0}
        for a in adapter_forecasts:
            trend_counts[a.trend] = trend_counts.get(a.trend, 0) + 1
        portfolio_trend = max(trend_counts, key=lambda t: trend_counts[t])

        # High confidence count
        high_conf = sum(1 for a in adapter_forecasts if a.confidence == "HIGH")

        # Low data warning: avg data_points < 5
        avg_points = sum(a.data_points for a in adapter_forecasts) / n_adapters
        low_data_warning = avg_points < _MEDIUM_CONFIDENCE_MIN

        result = PortfolioForecast(
            generated_at=now_iso,
            adapters=adapter_forecasts,
            portfolio_current_apy=round(portfolio_current, 6),
            portfolio_forecast_1d=round(portfolio_1d, 6),
            portfolio_forecast_7d=round(portfolio_7d, 6),
            portfolio_forecast_30d=round(portfolio_30d, 6),
            portfolio_trend=portfolio_trend,
            high_confidence_count=high_conf,
            low_data_warning=low_data_warning,
            disclaimer=_DISCLAIMER,
        )
        self._cached_forecast = result
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_forecast(
        self, forecast: Optional[PortfolioForecast] = None
    ) -> str:
        """
        Atomically save the forecast to data/yield_forecast.json.

        Maintains a ring-buffer of up to 48 entries.
        Calls generate_forecast() if no forecast is provided.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if forecast is None:
            if self._cached_forecast is None:
                self.generate_forecast()
            forecast = self._cached_forecast
        assert forecast is not None

        dest = self._output_path
        report_dict = self.to_dict(forecast)

        # Load existing ring-buffer
        existing: List[dict] = []
        try:
            if dest.exists():
                raw = dest.read_text(encoding="utf-8")
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    existing = payload.get("history", [])
                    if not isinstance(existing, list):
                        existing = []
        except Exception:
            existing = []

        existing.append(report_dict)
        if len(existing) > _RING_BUFFER_MAX:
            existing = existing[-_RING_BUFFER_MAX:]

        new_payload = {
            "schema_version": 1,
            "source": "yield_forecast_engine",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "snapshot_count": len(existing),
            "updated_at": forecast.generated_at,
            "latest": report_dict,
            "history": existing,
        }
        _atomic_write_json(dest, new_payload)
        return str(dest)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(
        self, forecast: Optional[PortfolioForecast] = None
    ) -> dict:
        """
        Serialise the forecast to a JSON-ready dict.

        Calls generate_forecast() if no forecast is provided or cached.
        """
        if forecast is None:
            if self._cached_forecast is None:
                self.generate_forecast()
            forecast = self._cached_forecast
        assert forecast is not None

        return {
            "generated_at": forecast.generated_at,
            "portfolio_current_apy": forecast.portfolio_current_apy,
            "portfolio_forecast_1d": forecast.portfolio_forecast_1d,
            "portfolio_forecast_7d": forecast.portfolio_forecast_7d,
            "portfolio_forecast_30d": forecast.portfolio_forecast_30d,
            "portfolio_trend": forecast.portfolio_trend,
            "high_confidence_count": forecast.high_confidence_count,
            "low_data_warning": forecast.low_data_warning,
            "disclaimer": forecast.disclaimer,
            "adapters": [
                {
                    "adapter_key": a.adapter_key,
                    "current_apy_pct": a.current_apy_pct,
                    "data_points": a.data_points,
                    "slope_pct_per_day": a.slope_pct_per_day,
                    "forecast_1d": a.forecast_1d,
                    "forecast_7d": a.forecast_7d,
                    "forecast_30d": a.forecast_30d,
                    "trend": a.trend,
                    "confidence": a.confidence,
                    "advisory_note": a.advisory_note,
                }
                for a in forecast.adapters
            ],
        }

    # ------------------------------------------------------------------
    # Telegram formatting
    # ------------------------------------------------------------------

    def format_telegram_message(
        self, forecast: Optional[PortfolioForecast] = None
    ) -> str:
        """
        Format a Telegram-ready advisory message (≤ 1500 characters).

        Format::

            🔮 Yield Forecast (Advisory Only)
            Portfolio now: 5.22% | 1d: 5.25% | 7d: 5.38% | 30d: 5.80%
            Trend: RISING ↗️ | High-conf adapters: 3
            Top adapters:
              morpho_blue: 7.5% → 1d:7.6% 7d:8.0%
            ⚠️ Advisory only. Not financial advice.

        Calls generate_forecast() if no forecast is provided or cached.
        """
        if forecast is None:
            if self._cached_forecast is None:
                self.generate_forecast()
            forecast = self._cached_forecast
        assert forecast is not None

        _TREND_ARROW = {
            "RISING": "↗️",
            "FALLING": "↘️",
            "STABLE": "→",
        }
        arrow = _TREND_ARROW.get(forecast.portfolio_trend, "→")

        lines: List[str] = []
        lines.append("🔮 Yield Forecast (Advisory Only)")
        lines.append(
            f"Portfolio now: {forecast.portfolio_current_apy:.2f}% | "
            f"1d: {forecast.portfolio_forecast_1d:.2f}% | "
            f"7d: {forecast.portfolio_forecast_7d:.2f}% | "
            f"30d: {forecast.portfolio_forecast_30d:.2f}%"
        )
        lines.append(
            f"Trend: {forecast.portfolio_trend} {arrow} | "
            f"High-conf adapters: {forecast.high_confidence_count}"
        )

        if forecast.low_data_warning:
            lines.append("⚠️ Low data: forecast reliability is limited.")

        # Top adapters by absolute slope magnitude (up to 5)
        if forecast.adapters:
            lines.append("Top adapters:")
            ranked = sorted(
                forecast.adapters,
                key=lambda a: abs(a.slope_pct_per_day),
                reverse=True,
            )
            for a in ranked[:5]:
                lines.append(
                    f"  {a.adapter_key}: {a.current_apy_pct:.2f}% "
                    f"→ 1d:{a.forecast_1d:.2f}% "
                    f"7d:{a.forecast_7d:.2f}%"
                )

        lines.append(f"⏱ {forecast.generated_at[:19]}Z")
        lines.append("⚠️ Advisory only. Not financial advice.")

        msg = "\n".join(lines)
        if len(msg) > _TELEGRAM_MAX_CHARS:
            msg = msg[: _TELEGRAM_MAX_CHARS - 1] + "…"
        return msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Yield Forecast Engine (MP-615) — ADVISORY ONLY linear APY extrapolation."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print forecast without saving (default mode).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute forecast and atomically save to data/yield_forecast.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    engine = YieldForecastEngine(data_path=args.data_dir)
    forecast = engine.generate_forecast()

    print("=== Yield Forecast Engine (MP-615) — ADVISORY ONLY ===")
    print(f"Generated at : {forecast.generated_at}")
    print(f"Adapters     : {len(forecast.adapters)}")
    print(f"Portfolio APY: {forecast.portfolio_current_apy:.2f}%")
    print(f"Forecast 1d  : {forecast.portfolio_forecast_1d:.2f}%")
    print(f"Forecast 7d  : {forecast.portfolio_forecast_7d:.2f}%")
    print(f"Forecast 30d : {forecast.portfolio_forecast_30d:.2f}%")
    print(f"Trend        : {forecast.portfolio_trend}")
    print(f"High-conf    : {forecast.high_confidence_count}")
    print(f"Low-data warn: {forecast.low_data_warning}")
    print()

    if forecast.adapters:
        print(f"{'Adapter':<40} {'APY%':>6} {'1d':>6} {'7d':>6} {'30d':>6}  "
              f"{'Trend':<8} {'Conf':<8} {'Pts':>4}")
        print("-" * 90)
        for a in forecast.adapters:
            print(
                f"  {a.adapter_key:<38} {a.current_apy_pct:>6.2f} "
                f"{a.forecast_1d:>6.2f} {a.forecast_7d:>6.2f} {a.forecast_30d:>6.2f}  "
                f"{a.trend:<8} {a.confidence:<8} {a.data_points:>4}"
            )
    else:
        print("  (no adapter history found)")

    print()
    print(engine.format_telegram_message(forecast))
    print()
    print(f"⚠️  {forecast.disclaimer}")

    if args.run:
        path = engine.save_forecast(forecast)
        print(f"\nSaved → {path}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
