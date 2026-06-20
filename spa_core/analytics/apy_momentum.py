"""
APY Momentum Detector (MP-598)
==============================

Detects APY trends for each adapter: RISING / FALLING / STABLE / UNKNOWN.
Uses EMA (Exponential Moving Average) and OLS linear regression (pure stdlib).

Data sources:
  - data/watchdog_history.json   (ring-buffer snapshots from AdapterWatchdog)
  - data/apy_history.json        (APYTracker rich time-series, supplementary)
  - data/adapter_status.json     (current APY values per adapter)

Output: data/momentum_report.json (ring-buffer 30 reports)

Design constraints
------------------
* Pure stdlib + ``math`` only — no numpy/scipy/requests/web3/pandas.
* Read-only over history/status files; writes only ``data/momentum_report.json``.
* Atomic writes: tmp + os.replace (POSIX-atomic, fail-safe cleanup).
* Never raises on the happy path; missing / malformed data degrades gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).
* Deterministic: identical input → identical output.

Confidence levels (driven by available history points):

========  ==================
Level     Data points needed
========  ==================
HIGH      ≥ 7  (MIN_POINTS_HIGH)
MEDIUM    3–6  (MIN_POINTS_MEDIUM)
LOW       1–2  (only strong signals emitted as RISING/FALLING)
UNKNOWN   0 data points
========  ==================

Trend detection:
  MEDIUM/HIGH confidence:
    |slope| < STABLE_THRESHOLD (0.1 %/day)  → STABLE
    slope  ≥ STABLE_THRESHOLD               → RISING
    slope  ≤ -STABLE_THRESHOLD              → FALLING
  LOW confidence (1–2 points):
    slope  > RISING_THRESHOLD  (0.05 %/day) → RISING, LOW
    slope  < -RISING_THRESHOLD              → FALLING, LOW
    else                                    → UNKNOWN, LOW
  0 points → UNKNOWN, LOW

CLI
---
``python3 -m spa_core.analytics.apy_momentum --check``    (default, no write)
``python3 -m spa_core.analytics.apy_momentum --run``      (+ atomic save)
``python3 -m spa_core.analytics.apy_momentum --data-dir PATH``
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_WATCHDOG_HISTORY_FILE = "watchdog_history.json"
_APY_HISTORY_FILE = "apy_history.json"
_ADAPTER_STATUS_FILE = "adapter_status.json"
_MOMENTUM_REPORT_FILE = "momentum_report.json"
_RING_BUFFER_MAX = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts_unix(ts_str: str) -> float:
    """Parse ISO-8601 UTC string → unix timestamp float. Returns 0.0 on error."""
    if not isinstance(ts_str, str):
        return 0.0
    try:
        # Handle both "+00:00" and "Z" suffix
        s = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return 0.0


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
class MomentumSignal:
    """Momentum signal for one adapter at one point in time."""
    adapter_id: str
    trend: str               # "RISING" / "FALLING" / "STABLE" / "UNKNOWN"
    confidence: str          # "HIGH" / "MEDIUM" / "LOW"
    current_apy: float
    ema_apy: float           # EMA(alpha=EMA_ALPHA) over historical series
    apy_change_24h: float    # diff vs ~24 h ago snapshot (0.0 if unavailable)
    apy_change_7d: float     # diff vs ~7 days ago snapshot (0.0 if unavailable)
    slope_per_day: float     # OLS linear slope: APY% / day (positive → rising)
    data_points: int         # number of historical time-points used
    signal_strength: float   # |slope_per_day| * confidence_factor, clamped [0, 1]

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "trend": self.trend,
            "confidence": self.confidence,
            "current_apy": round(self.current_apy, 6),
            "ema_apy": round(self.ema_apy, 6),
            "apy_change_24h": round(self.apy_change_24h, 6),
            "apy_change_7d": round(self.apy_change_7d, 6),
            "slope_per_day": round(self.slope_per_day, 8),
            "data_points": self.data_points,
            "signal_strength": round(self.signal_strength, 6),
        }


@dataclass
class MomentumReport:
    """Aggregated momentum report for all adapters."""
    generated_at: str
    total_adapters: int
    rising: int
    falling: int
    stable: int
    unknown: int
    top_rising: list   # top-3 adapters with highest slope (list of signal dicts)
    top_falling: list  # top-3 adapters with most negative slope
    signals: List[MomentumSignal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_adapters": self.total_adapters,
            "rising": self.rising,
            "falling": self.falling,
            "stable": self.stable,
            "unknown": self.unknown,
            "top_rising": self.top_rising,
            "top_falling": self.top_falling,
            "signals": [s.to_dict() for s in self.signals],
        }


# ---------------------------------------------------------------------------
# APYMomentumDetector
# ---------------------------------------------------------------------------

class APYMomentumDetector:
    """
    Detect APY momentum (RISING / FALLING / STABLE / UNKNOWN) for each adapter.

    Parameters
    ----------
    history_path : str | None
        Path to the ``data/`` directory.  Defaults to the project's ``data/``.
    """

    EMA_ALPHA: float = 0.3
    MIN_POINTS_MEDIUM: int = 3
    MIN_POINTS_HIGH: int = 7
    STABLE_THRESHOLD: float = 0.1   # %/day — below this magnitude → STABLE
    RISING_THRESHOLD: float = 0.05  # %/day — threshold for RISING/FALLING at LOW conf

    # Confidence → weight used to scale signal_strength
    _CONFIDENCE_FACTOR: Dict[str, float] = {
        "HIGH": 1.0,
        "MEDIUM": 0.5,
        "LOW": 0.25,
        "UNKNOWN": 0.0,
    }

    def __init__(self, history_path: Optional[str] = None) -> None:
        if history_path is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            p = Path(history_path)
            # Accept either the data dir itself or a file inside it
            self._data_dir = p if p.is_dir() else p.parent
        self._watchdog_path = self._data_dir / _WATCHDOG_HISTORY_FILE
        self._apy_history_path = self._data_dir / _APY_HISTORY_FILE
        self._adapter_status_path = self._data_dir / _ADAPTER_STATUS_FILE
        self._report_path = self._data_dir / _MOMENTUM_REPORT_FILE

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_history(self) -> List[dict]:
        """
        Read historical APY data from watchdog_history.json and apy_history.json.

        Returns a list of unified reading dicts (one per adapter-snapshot),
        sorted ascending by timestamp:

            [{"ts_unix": float, "generated_at": str,
              "adapter_id": str, "apy_pct": float, "source": str}, ...]

        Returns ``[]`` on any error or when both files are absent.
        """
        readings: List[dict] = []

        # Source 1: watchdog_history.json (ring-buffer of WatchdogReport snapshots)
        try:
            if self._watchdog_path.exists():
                raw = self._watchdog_path.read_text(encoding="utf-8")
                wh = json.loads(raw)
                if isinstance(wh, dict):
                    snapshots = wh.get("snapshots", [])
                    if isinstance(snapshots, list):
                        for snap in snapshots:
                            if not isinstance(snap, dict):
                                continue
                            ts_str = snap.get("generated_at", "")
                            ts_unix = _parse_ts_unix(ts_str)
                            if ts_unix <= 0:
                                continue
                            statuses = snap.get("adapter_statuses", [])
                            if not isinstance(statuses, list):
                                continue
                            for entry in statuses:
                                if not isinstance(entry, dict):
                                    continue
                                aid = entry.get("adapter_id")
                                apy = entry.get("apy_pct")
                                if (
                                    isinstance(aid, str) and aid
                                    and isinstance(apy, (int, float))
                                    and not isinstance(apy, bool)
                                    and not math.isnan(float(apy))
                                ):
                                    readings.append({
                                        "ts_unix": float(ts_unix),
                                        "generated_at": ts_str,
                                        "adapter_id": str(aid),
                                        "apy_pct": float(apy),
                                        "source": "watchdog",
                                    })
        except Exception:
            pass  # fail-safe

        # Source 2: apy_history.json (APYTracker rich per-adapter series)
        try:
            if self._apy_history_path.exists():
                raw = self._apy_history_path.read_text(encoding="utf-8")
                ah = json.loads(raw)
                if isinstance(ah, dict):
                    ph = ah.get("protocol_history", {})
                    if not isinstance(ph, dict):
                        ph = {}
                    for aid, entries in ph.items():
                        if not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            ts_str = entry.get("ts", "")
                            ts_unix = _parse_ts_unix(ts_str)
                            apy = entry.get("apy")
                            if (
                                ts_unix > 0
                                and isinstance(apy, (int, float))
                                and not isinstance(apy, bool)
                                and not math.isnan(float(apy))
                            ):
                                readings.append({
                                    "ts_unix": float(ts_unix),
                                    "generated_at": ts_str,
                                    "adapter_id": str(aid),
                                    "apy_pct": float(apy),
                                    "source": "apy_history",
                                })
        except Exception:
            pass  # fail-safe

        # Sort chronologically
        readings.sort(key=lambda r: r["ts_unix"])
        return readings

    # ------------------------------------------------------------------
    # APY series extraction
    # ------------------------------------------------------------------

    def extract_apy_series(
        self,
        adapter_id: str,
        history: List[dict],
    ) -> List[Tuple[float, float]]:
        """
        Extract ``[(timestamp_days, apy_pct)]`` for *adapter_id* from *history*.

        ``timestamp_days = ts_unix / 86400`` (suitable for OLS x-axis).

        Matching strategy (in order):
        1. Exact match on ``adapter_id`` field.
        2. Prefix match: history entry's adapter_id starts with *adapter_id*
           (e.g. "aave-v3" matches "aave-v3-usdc-ethereum").

        Returns ``[]`` when no matching entries are found.
        """
        if not history or not adapter_id:
            return []

        result: List[Tuple[float, float]] = []
        for r in history:
            rid = r.get("adapter_id", "")
            apy = r.get("apy_pct")
            ts_unix = r.get("ts_unix", 0.0)
            if not isinstance(apy, (int, float)) or isinstance(apy, bool):
                continue
            if not (rid == adapter_id or rid.startswith(adapter_id)):
                continue
            result.append((float(ts_unix) / 86400.0, float(apy)))

        # Already sorted (history is pre-sorted), but deduplicate ts ties by last value
        return result

    # ------------------------------------------------------------------
    # Core statistics
    # ------------------------------------------------------------------

    def compute_ema(
        self,
        series: List[float],
        alpha: float = EMA_ALPHA,
    ) -> float:
        """
        Exponential Moving Average over *series* with smoothing factor *alpha*.

        Formula: ``ema_t = alpha * x_t + (1 - alpha) * ema_{t-1}``.
        Index 0 is the oldest observation (chronological order).

        Returns 0.0 for an empty series.

        Parameters
        ----------
        series : list[float]
            Chronological APY values.
        alpha : float
            Smoothing factor in (0, 1].  Values outside this range are clamped.

        Raises
        ------
        ValueError
            If *alpha* is not in (0, 1].
        """
        if not series:
            return 0.0
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0, 1], got {alpha!r}")
        ema = float(series[0])
        for v in series[1:]:
            ema = alpha * float(v) + (1.0 - alpha) * ema
        return ema

    def compute_ols_slope(
        self,
        xy_pairs: List[Tuple[float, float]],
    ) -> float:
        """
        Ordinary Least Squares slope for ``y = a + b*x``.

        Formula::

            slope = (n*Σxy − Σx*Σy) / (n*Σx² − (Σx)²)

        Pure stdlib — no numpy.

        Returns 0.0 when fewer than 2 pairs are provided or denominator is 0.

        Parameters
        ----------
        xy_pairs : list[tuple[float, float]]
            List of ``(x, y)`` pairs (e.g. ``(timestamp_days, apy_pct)``).
        """
        n = len(xy_pairs)
        if n < 2:
            return 0.0

        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_x2 = 0.0
        for x, y in xy_pairs:
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_x2 += x * x

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0.0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    # ------------------------------------------------------------------
    # Trend classification
    # ------------------------------------------------------------------

    def classify_trend(
        self,
        slope: float,
        data_points: int,
    ) -> Tuple[str, str]:
        """
        Map ``(slope, data_points)`` → ``(trend, confidence)``.

        Trend values:  ``"RISING"`` / ``"FALLING"`` / ``"STABLE"`` / ``"UNKNOWN"``
        Confidence:    ``"HIGH"`` / ``"MEDIUM"`` / ``"LOW"``

        Rules
        -----
        * 0 points:               ``("UNKNOWN", "LOW")``
        * 1–2 points (LOW conf):
            slope > RISING_THRESHOLD  → ``("RISING",  "LOW")``
            slope < -RISING_THRESHOLD → ``("FALLING", "LOW")``
            else                      → ``("UNKNOWN", "LOW")``
        * ≥ 3 points → confidence = "MEDIUM" (3–6) or "HIGH" (≥ 7):
            |slope| < STABLE_THRESHOLD → ``("STABLE",  confidence)``
            slope   ≥ 0               → ``("RISING",  confidence)``
            else                      → ``("FALLING", confidence)``
        """
        if data_points < 1:
            return ("UNKNOWN", "LOW")

        if data_points < self.MIN_POINTS_MEDIUM:
            # 1 or 2 points: emit only strong signals
            if slope > self.RISING_THRESHOLD:
                return ("RISING", "LOW")
            if slope < -self.RISING_THRESHOLD:
                return ("FALLING", "LOW")
            return ("UNKNOWN", "LOW")

        # 3+ points
        confidence = "HIGH" if data_points >= self.MIN_POINTS_HIGH else "MEDIUM"

        if abs(slope) < self.STABLE_THRESHOLD:
            return ("STABLE", confidence)
        if slope > 0:
            return ("RISING", confidence)
        return ("FALLING", confidence)

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def _find_apy_near_ts(
        self,
        series: List[Tuple[float, float]],
        target_ts_days: float,
        tolerance_days: float = 3.0,
    ) -> float:
        """Return APY from the point in *series* closest to *target_ts_days*.

        Returns 0.0 if no point is within *tolerance_days* of the target.
        """
        if not series:
            return 0.0
        best_apy = 0.0
        best_diff = float("inf")
        for ts, apy in series:
            diff = abs(ts - target_ts_days)
            if diff < best_diff:
                best_diff = diff
                best_apy = apy
        return best_apy if best_diff <= tolerance_days else 0.0

    def get_signal(
        self,
        adapter_id: str,
        current_apy: float,
        history: List[dict],
    ) -> MomentumSignal:
        """
        Compute a full ``MomentumSignal`` for one adapter.

        Parameters
        ----------
        adapter_id : str
            Adapter identifier (e.g. ``"aave-v3"``).
        current_apy : float
            Most-recent APY (%) from ``adapter_status.json``.
        history : list[dict]
            Unified history as returned by :meth:`load_history`.
        """
        series = self.extract_apy_series(adapter_id, history)
        n = len(series)

        # APY values only (sorted chronologically via extract_apy_series)
        apy_values = [apy for _, apy in series]

        # EMA over historical values (include current as last point if no history)
        if apy_values:
            ema_apy = self.compute_ema(apy_values, alpha=self.EMA_ALPHA)
        else:
            ema_apy = current_apy

        # OLS slope
        slope = self.compute_ols_slope(series)

        # Classify
        trend, confidence = self.classify_trend(slope, n)

        # Changes vs 24 h / 7 d
        apy_change_24h = 0.0
        apy_change_7d = 0.0
        if series:
            latest_ts_days = series[-1][0]
            apy_24h_ago = self._find_apy_near_ts(
                series, latest_ts_days - 1.0, tolerance_days=2.0
            )
            apy_7d_ago = self._find_apy_near_ts(
                series, latest_ts_days - 7.0, tolerance_days=3.0
            )
            if apy_24h_ago != 0.0:
                apy_change_24h = round(current_apy - apy_24h_ago, 6)
            if apy_7d_ago != 0.0:
                apy_change_7d = round(current_apy - apy_7d_ago, 6)

        # Signal strength: |slope| × confidence_factor, clamped to [0, 1]
        cf = self._CONFIDENCE_FACTOR.get(confidence, 0.0)
        signal_strength = min(1.0, abs(slope) * cf)

        return MomentumSignal(
            adapter_id=adapter_id,
            trend=trend,
            confidence=confidence,
            current_apy=round(current_apy, 6),
            ema_apy=round(ema_apy, 6),
            apy_change_24h=apy_change_24h,
            apy_change_7d=apy_change_7d,
            slope_per_day=round(slope, 8),
            data_points=n,
            signal_strength=round(signal_strength, 6),
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _read_adapter_status(self) -> List[Tuple[str, float]]:
        """
        Read ``adapter_status.json`` → list of ``(protocol_key, apy_pct)``.

        APY resolution order: ``apy_pct`` → ``apy`` → ``mock_apy.ethereum.USDC``
        → first available mock value.  Returns ``[]`` on error.
        """
        try:
            if not self._adapter_status_path.exists():
                return []
            raw = self._adapter_status_path.read_text(encoding="utf-8")
            status = json.loads(raw)
            if not isinstance(status, dict):
                return []
            adapters_list = status.get("adapters", [])
            if not isinstance(adapters_list, list):
                return []
            result: List[Tuple[str, float]] = []
            for entry in adapters_list:
                if not isinstance(entry, dict):
                    continue
                key = entry.get("protocol_key") or entry.get("id") or entry.get("adapter_id")
                if not isinstance(key, str) or not key:
                    continue
                apy = _extract_current_apy(entry)
                result.append((key, apy))
            return result
        except Exception:
            return []

    def get_report(self) -> MomentumReport:
        """
        Generate a :class:`MomentumReport` for all adapters.

        Reads ``data/adapter_status.json`` (current APY) and the history
        files.  Signals are sorted alphabetically by adapter_id.

        Counters: rising + falling + stable + unknown == total_adapters.
        ``top_rising`` / ``top_falling`` each contain ≤ 3 entries (signal dicts)
        sorted by descending / ascending slope respectively.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        adapters = self._read_adapter_status()
        history = self.load_history()

        signals: List[MomentumSignal] = []
        for adapter_id, current_apy in adapters:
            sig = self.get_signal(adapter_id, current_apy, history)
            signals.append(sig)

        # Sort alphabetically for determinism
        signals.sort(key=lambda s: s.adapter_id)

        # Count trends
        rising = sum(1 for s in signals if s.trend == "RISING")
        falling = sum(1 for s in signals if s.trend == "FALLING")
        stable = sum(1 for s in signals if s.trend == "STABLE")
        unknown = sum(1 for s in signals if s.trend == "UNKNOWN")

        # Top rising: highest slope (only RISING signals)
        rising_sigs = sorted(
            [s for s in signals if s.trend == "RISING"],
            key=lambda s: s.slope_per_day,
            reverse=True,
        )
        top_rising = [s.to_dict() for s in rising_sigs[:3]]

        # Top falling: most negative slope (only FALLING signals)
        falling_sigs = sorted(
            [s for s in signals if s.trend == "FALLING"],
            key=lambda s: s.slope_per_day,
        )
        top_falling = [s.to_dict() for s in falling_sigs[:3]]

        return MomentumReport(
            generated_at=now_iso,
            total_adapters=len(signals),
            rising=rising,
            falling=falling,
            stable=stable,
            unknown=unknown,
            top_rising=top_rising,
            top_falling=top_falling,
            signals=signals,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, output_path: Optional[str] = None) -> str:
        """
        Atomically save the current ``MomentumReport`` to
        ``data/momentum_report.json`` (ring-buffer ≤ 30 entries).

        Returns the absolute path of the saved file.
        """
        dest = Path(output_path) if output_path else self._report_path

        report = self.get_report()
        report_dict = report.to_dict()

        # Load existing ring-buffer (if any)
        existing: List[dict] = []
        try:
            if dest.exists():
                raw = dest.read_text(encoding="utf-8")
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    existing = payload.get("reports", [])
                    if not isinstance(existing, list):
                        existing = []
        except Exception:
            existing = []

        # Append and trim to ring-buffer size
        existing.append(report_dict)
        if len(existing) > _RING_BUFFER_MAX:
            existing = existing[-_RING_BUFFER_MAX:]

        new_payload = {
            "schema_version": 1,
            "ring_buffer_max": _RING_BUFFER_MAX,
            "snapshot_count": len(existing),
            "updated_at": report.generated_at,
            "latest": report_dict,
            "reports": existing,
        }
        _atomic_write_json(dest, new_payload)
        return str(dest)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return the current report as a JSON-serialisable dict."""
        return self.get_report().to_dict()

    # ------------------------------------------------------------------
    # Telegram formatting
    # ------------------------------------------------------------------

    def format_telegram_message(self) -> str:
        """
        Build a Telegram-ready momentum summary (≤ 1500 characters).

        Format::

            📊 APY Momentum Report
            Total: N adapters | ↑ R rising | ↓ F falling | → S stable | ? U unknown

            🟢 TOP RISING:
            • adapter — +X.XXXX %/day (conf, strength=Y.YY)

            🔴 TOP FALLING:
            • adapter — -X.XXXX %/day (conf, strength=Y.YY)
        """
        report = self.get_report()
        lines: List[str] = []
        lines.append("📊 *APY Momentum Report*")
        lines.append(
            f"Total: {report.total_adapters} adapters | "
            f"↑ {report.rising} rising | "
            f"↓ {report.falling} falling | "
            f"→ {report.stable} stable | "
            f"? {report.unknown} unknown"
        )

        if report.top_rising:
            lines.append("\n🟢 *TOP RISING:*")
            for s in report.top_rising:
                lines.append(
                    f"• {s['adapter_id']} — "
                    f"+{s['slope_per_day']:.4f} %/day "
                    f"({s['confidence']}, "
                    f"str={s['signal_strength']:.2f})"
                )

        if report.top_falling:
            lines.append("\n🔴 *TOP FALLING:*")
            for s in report.top_falling:
                lines.append(
                    f"• {s['adapter_id']} — "
                    f"{s['slope_per_day']:.4f} %/day "
                    f"({s['confidence']}, "
                    f"str={s['signal_strength']:.2f})"
                )

        msg = "\n".join(lines)
        # Hard-cap at 1500 characters (Telegram limit safety margin)
        if len(msg) > 1500:
            msg = msg[:1497] + "…"
        return msg


# ---------------------------------------------------------------------------
# APY extraction helper (used by _read_adapter_status)
# ---------------------------------------------------------------------------

def _extract_current_apy(entry: dict) -> float:
    """Extract current APY from an adapter entry in adapter_status.json."""
    for key in ("apy_pct", "apy"):
        val = entry.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            return float(val)
    mock = entry.get("mock_apy")
    if isinstance(mock, dict):
        for chain_key in ("ethereum", *mock.keys()):
            chain_data = mock.get(chain_key)
            if isinstance(chain_data, dict):
                for asset_key in ("USDC", "USDT", *chain_data.keys()):
                    val = chain_data.get(asset_key)
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
                        return float(val)
    return 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="APY Momentum Detector (MP-598) — EMA/OLS trend detection"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print report (no write). Default mode.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute report and atomically save data/momentum_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Path to the data/ directory (default: project data/).",
    )
    args = parser.parse_args(argv)

    detector = APYMomentumDetector(history_path=args.data_dir)
    report = detector.get_report()

    print(f"=== APY Momentum Detector (MP-598) — {report.total_adapters} adapters ===")
    print(
        f"  Rising: {report.rising}  Falling: {report.falling}  "
        f"Stable: {report.stable}  Unknown: {report.unknown}"
    )
    print()

    for sig in report.signals:
        arrow = {"RISING": "↑", "FALLING": "↓", "STABLE": "→", "UNKNOWN": "?"}.get(
            sig.trend, "?"
        )
        print(
            f"  {arrow} {sig.adapter_id:<40s}  "
            f"apy={sig.current_apy:6.2f}%  "
            f"ema={sig.ema_apy:6.2f}%  "
            f"slope={sig.slope_per_day:+.4f} %/d  "
            f"Δ24h={sig.apy_change_24h:+.2f}%  "
            f"[{sig.trend}/{sig.confidence}]  "
            f"pts={sig.data_points}"
        )

    if report.top_rising:
        print("\n  Top RISING:  " + ", ".join(s["adapter_id"] for s in report.top_rising))
    if report.top_falling:
        print("  Top FALLING: " + ", ".join(s["adapter_id"] for s in report.top_falling))

    if args.run:
        path = detector.save_report()
        print(f"\nSaved → {path}")
    else:
        print("\n(--check mode: not saved. Use --run to persist.)")

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _run_cli()
