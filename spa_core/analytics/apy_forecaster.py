"""
APY Forecaster (MP-580)
=======================

Forecasts per-adapter APY using historical data stored in
``data/apy_history.json`` (the ``APYTracker`` schema).

Three statistical signals are combined to produce a forward estimate:

* **EMA** — exponential moving average of the APY series.  Weights recent
  observations more heavily (default α=0.30).
* **Trend** — linear slope (pp/day) estimated via ordinary least-squares
  on the last ``window`` data points.  Pure stdlib ``math``; no numpy.
* **Forecast** — EMA + trend × days_ahead, clamped to [0, 200] pp.

Confidence levels (driven by available history length):

=======  ====================
Level    Data points required
=======  ====================
"high"   ≥ 14
"medium" 7 – 13
"low"    1 – 6
"none"   0 (fallback only)
=======  ====================

Fallback (confidence="none"): ``forecast_apy`` equals ``default_apy``
supplied by the caller, or 0.0 if not provided.

Design constraints
------------------
* Pure stdlib + ``math`` — no numpy/scipy/requests/web3.
* Read-only over ``data/apy_history.json``; only write target is
  ``data/apy_forecasts.json`` (atomic: tmp + os.replace).
* Never raises on the happy path; missing / malformed history degrades
  gracefully.
* Deterministic: identical input → identical output.

Public API
----------
``ApyForecaster(data_dir: str = "data")``

Methods:
    - ``load_history(adapter_id) -> list[dict]``
    - ``compute_ema(values, alpha=0.3) -> float``
    - ``compute_trend(values, window=7) -> float``
    - ``forecast(adapter_id, days_ahead=7, default_apy=0.0) -> dict``
    - ``forecast_all(adapters) -> dict``
    - ``save_forecast(forecasts) -> None``

CLI
---
``python3 -m spa_core.analytics.apy_forecaster --check``   (default, no write)
``python3 -m spa_core.analytics.apy_forecaster --run``     (+ atomic save)
``python3 -m spa_core.analytics.apy_forecaster --data-dir PATH``
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APY_HISTORY_FILE = "apy_history.json"
APY_FORECASTS_FILE = "apy_forecasts.json"

_CONFIDENCE_HIGH = 14     # ≥ 14 data points
_CONFIDENCE_MEDIUM = 7    # 7–13 data points
# < 7 → "low"; 0 → "none"

_FORECAST_MIN_APY = 0.0   # floor for clamping
_FORECAST_MAX_APY = 200.0 # ceiling for clamping


# ---------------------------------------------------------------------------
# ApyForecaster
# ---------------------------------------------------------------------------

class ApyForecaster:
    """Forecast per-adapter APY from historical data using EMA + linear trend.

    Parameters
    ----------
    data_dir:
        Path to the ``data/`` directory (contains ``apy_history.json`` and
        receives ``apy_forecasts.json``).  Defaults to ``"data"``.
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self._history_file = self.data_dir / APY_HISTORY_FILE
        self._forecasts_file = self.data_dir / APY_FORECASTS_FILE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_history_store(self) -> dict:
        """Load the full apy_history.json store; return empty dict on error."""
        if not self._history_file.exists():
            return {}
        try:
            raw = self._history_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_history(self, adapter_id: str) -> list[dict]:
        """Return chronological APY history for *adapter_id*.

        Each entry is a dict with at least ``"apy"`` (float, %).
        Returns ``[]`` when adapter_id is unknown or file is absent.

        The method tolerates both schema variants found in the store:

        * ``apy_history.json`` written by ``APYTracker``:
          ``protocol_history[adapter_id]`` → list of
          ``{"ts": ..., "apy": ..., "tvl": ...}``

        * Older / alternative schemas where the top-level key is already
          the adapter_id (dict of lists).
        """
        store = self._load_history_store()
        if not store:
            return []

        # Primary schema: protocol_history wrapper
        if "protocol_history" in store:
            entries = store["protocol_history"].get(adapter_id, [])
        else:
            # Fallback: adapter_id is a top-level key
            entries = store.get(adapter_id, [])

        if not isinstance(entries, list):
            return []

        # Keep only entries that have a numeric 'apy' field
        valid = []
        for e in entries:
            if isinstance(e, dict):
                apy = e.get("apy")
                if isinstance(apy, (int, float)) and not math.isnan(apy):
                    valid.append(e)
        return valid

    def compute_ema(self, values: list[float], alpha: float = 0.3) -> float:
        """Exponential moving average over *values* with smoothing factor *alpha*.

        Uses the standard online formula::

            ema_t = alpha * x_t + (1 - alpha) * ema_{t-1}

        The series is processed in chronological order (index 0 = oldest).
        Returns 0.0 for an empty series.

        Parameters
        ----------
        values:
            Chronological list of floats (e.g. APY percentages).
        alpha:
            Smoothing factor in (0, 1].  Default 0.3.

        Returns
        -------
        float
            EMA of the last value in the series (i.e. the "current" EMA).
        """
        if not values:
            return 0.0
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")

        ema = float(values[0])
        for v in values[1:]:
            ema = alpha * float(v) + (1.0 - alpha) * ema
        return ema

    def compute_trend(self, values: list[float], window: int = 7) -> float:
        """Estimate linear trend (slope, pp/day) over the last *window* values.

        Uses ordinary least-squares (closed-form) with integer x-axis
        (x_i = i, i = 0..n-1).  Implemented with only ``math`` — no numpy.

        Returns 0.0 when fewer than 2 data points are available.

        Parameters
        ----------
        values:
            Chronological list of floats.
        window:
            Number of most-recent data points to use.  If ``len(values) <
            window``, all available values are used.

        Returns
        -------
        float
            Slope in units of (pp / day).  Positive → rising APY.
        """
        if not values:
            return 0.0

        n = min(window, len(values))
        if n < 2:
            return 0.0

        xs = values[-n:]  # most-recent n values, chronological
        # OLS: y = a + b*x, where x = 0,1,...,n-1
        n_pts = len(xs)
        sum_x = n_pts * (n_pts - 1) / 2.0          # sum(0..n-1)
        sum_x2 = n_pts * (n_pts - 1) * (2 * n_pts - 1) / 6.0  # sum(i^2)
        sum_y = sum(xs)
        sum_xy = sum(i * v for i, v in enumerate(xs))

        denom = n_pts * sum_x2 - sum_x * sum_x
        if denom == 0.0:
            return 0.0

        slope = (n_pts * sum_xy - sum_x * sum_y) / denom
        return slope

    def _confidence(self, n_points: int) -> str:
        """Map data-point count to confidence string."""
        if n_points == 0:
            return "none"
        if n_points < _CONFIDENCE_MEDIUM:
            return "low"
        if n_points < _CONFIDENCE_HIGH:
            return "medium"
        return "high"

    def forecast(
        self,
        adapter_id: str,
        days_ahead: int = 7,
        default_apy: float = 0.0,
    ) -> dict:
        """Produce an APY forecast for *adapter_id*.

        Parameters
        ----------
        adapter_id:
            Key used in ``apy_history.json`` (e.g. ``"aave-v3-usdc-ethereum"``).
        days_ahead:
            Number of days to project forward.  Default 7.
        default_apy:
            Fallback APY (%) used when history is empty (confidence="none").

        Returns
        -------
        dict with keys:
            ``adapter_id``, ``current_apy``, ``ema_apy``, ``trend_per_day``,
            ``forecast_apy``, ``confidence``, ``method``.
        """
        history = self.load_history(adapter_id)
        n = len(history)
        confidence = self._confidence(n)

        if n == 0:
            return {
                "adapter_id": adapter_id,
                "current_apy": default_apy,
                "ema_apy": default_apy,
                "trend_per_day": 0.0,
                "forecast_apy": default_apy,
                "confidence": "none",
                "method": "fallback",
            }

        apys = [e["apy"] for e in history]
        current_apy = apys[-1]
        ema_apy = self.compute_ema(apys)
        trend = self.compute_trend(apys)

        raw_forecast = ema_apy + trend * days_ahead
        # Clamp to valid APY range
        forecast_apy = max(_FORECAST_MIN_APY, min(_FORECAST_MAX_APY, raw_forecast))

        return {
            "adapter_id": adapter_id,
            "current_apy": round(current_apy, 6),
            "ema_apy": round(ema_apy, 6),
            "trend_per_day": round(trend, 8),
            "forecast_apy": round(forecast_apy, 6),
            "confidence": confidence,
            "method": "ema_trend",
        }

    def forecast_all(self, adapters: list[Any]) -> dict:
        """Run :meth:`forecast` for every adapter in *adapters*.

        *adapters* can be:

        * A list of strings (adapter IDs).
        * A list of dicts with at least ``"id"`` key (and optionally
          ``"default_apy"``).
        * A list of tuples ``(adapter_id, ...)`` where the first element
          is the adapter ID.

        Returns
        -------
        dict
            ``{adapter_id: forecast_dict, ...}``
        """
        result: dict[str, dict] = {}
        for item in adapters:
            if isinstance(item, str):
                adapter_id = item
                default_apy = 0.0
            elif isinstance(item, dict):
                adapter_id = item.get("id") or item.get("adapter_id") or str(item)
                default_apy = float(item.get("default_apy", 0.0))
            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                adapter_id = str(item[0])
                default_apy = float(item[1]) if len(item) > 1 else 0.0
            else:
                adapter_id = str(item)
                default_apy = 0.0

            result[adapter_id] = self.forecast(
                adapter_id, default_apy=default_apy
            )
        return result

    def save_forecast(self, forecasts: dict) -> None:
        """Atomically save *forecasts* to ``data/apy_forecasts.json``.

        The file structure is::

            {
              "generated_at": "<iso-utc>",
              "adapter_count": N,
              "forecasts": { adapter_id: forecast_dict, ... }
            }

        Uses ``tmp + os.replace`` (atomic on POSIX).

        Parameters
        ----------
        forecasts:
            Dict as returned by :meth:`forecast_all`.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "adapter_count": len(forecasts),
            "forecasts": forecasts,
        }
        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(self._forecasts_file))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: list[str] | None = None) -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="APY Forecaster (MP-580) — forecast adapter APY from history"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print forecasts (no write). Default mode.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute forecasts and atomically save data/apy_forecasts.json.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="PATH",
        help="Path to the data/ directory (default: data).",
    )
    args = parser.parse_args(argv)

    forecaster = ApyForecaster(data_dir=args.data_dir)

    # Load all known adapters from apy_history.json
    store = forecaster._load_history_store()
    ph = store.get("protocol_history", store)
    adapter_ids = list(ph.keys()) if isinstance(ph, dict) else []

    if not adapter_ids:
        print("WARNING: No adapters found in apy_history.json — nothing to forecast.")
        sys.exit(0)

    forecasts = forecaster.forecast_all(adapter_ids)

    # Pretty-print
    print(f"=== APY Forecaster (MP-580) — {len(forecasts)} adapters ===")
    for aid, fc in sorted(forecasts.items()):
        print(
            f"  {aid:<40s}  "
            f"current={fc['current_apy']:6.2f}%  "
            f"ema={fc['ema_apy']:6.2f}%  "
            f"trend={fc['trend_per_day']:+.4f} pp/d  "
            f"forecast={fc['forecast_apy']:6.2f}%  "
            f"[{fc['confidence']}]"
        )

    if args.run:
        forecaster.save_forecast(forecasts)
        print(f"\nSaved → {forecaster._forecasts_file}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _run_cli()
