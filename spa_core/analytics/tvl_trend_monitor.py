"""
TVLTrendMonitor (MP-663)
========================
Per-adapter TVL (Total Value Locked) trend monitor. Advisory / read-only.

Tracks each adapter's TVL over time and flags liquidity-exodus risk based on
the percent change of the latest TVL value relative to the oldest value in the
supplied history window. This module answers "is liquidity flowing INTO or OUT
of this adapter?" — it does NOT forecast TVL, move capital, or alter risk
thresholds. Advisory flags are purely informational.

For each adapter with >= 2 history points the percent change is computed and
classified into a trend:
    GROWING     change_pct >  +5.0
    STABLE      -5.0 <= change_pct <= +5.0
    DECLINING   -25.0 <= change_pct < -5.0
    COLLAPSING  change_pct < -25.0
Adapters with < 2 history points → trend UNKNOWN.

risk_flag is derived from the trend:
    HIGH    when COLLAPSING
    MEDIUM  when DECLINING
    LOW     otherwise (GROWING / STABLE / UNKNOWN)

Output ring-buffer (30 entries): data/tvl_trend_report.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never modifies risk/, execution/, monitoring/, allocator/,
  cycle_runner. Advisory flags are informational, never move capital.
* Atomic writes: tmp + os.replace.
* Never raises on the happy path; load failures degrade gracefully.

CLI
---
``python3 -m spa_core.analytics.tvl_trend_monitor --check``
``python3 -m spa_core.analytics.tvl_trend_monitor --run``
``python3 -m spa_core.analytics.tvl_trend_monitor --data-dir PATH``

MP-663.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_FILENAME = "tvl_trend_report.json"
_RING_BUFFER_MAX = 30

_MIN_HISTORY_POINTS = 2

# Trend thresholds (percent change of latest vs oldest)
_GROWING_THRESHOLD = 5.0       # change_pct > +5.0 → GROWING
_STABLE_LOWER = -5.0           # -5.0 <= change_pct <= +5.0 → STABLE
_DECLINING_LOWER = -25.0       # -25.0 <= change_pct < -5.0 → DECLINING
#                                change_pct < -25.0 → COLLAPSING

# Trend labels
_TREND_GROWING = "GROWING"
_TREND_STABLE = "STABLE"
_TREND_DECLINING = "DECLINING"
_TREND_COLLAPSING = "COLLAPSING"
_TREND_UNKNOWN = "UNKNOWN"

_ALL_TRENDS = [
    _TREND_GROWING,
    _TREND_STABLE,
    _TREND_DECLINING,
    _TREND_COLLAPSING,
    _TREND_UNKNOWN,
]

# Risk-flag labels
_RISK_HIGH = "HIGH"
_RISK_MEDIUM = "MEDIUM"
_RISK_LOW = "LOW"

_ADVISORY_CLEAN = (
    "TVL trends are descriptive only. No adapters show DECLINING or COLLAPSING "
    "liquidity. Advisory only — not financial advice."
)
_ADVISORY_PREFIX = (
    "TVL trends are descriptive only. Liquidity-exodus risk flagged for: "
)
_ADVISORY_SUFFIX = " Advisory only — not financial advice."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: object) -> Optional[float]:
    """Coerce to float; return None on failure or bool."""
    if isinstance(val, bool):
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pct_change(old: float, new: float) -> Optional[float]:
    """
    Percent change of ``new`` relative to ``old``: (new - old) / |old| * 100.

    Returns None when ``old`` is zero (undefined percent change).
    """
    if old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _classify_trend(history: List[float]) -> str:
    """
    Classify a TVL trend from a history series (oldest first, newest last).

    Returns one of GROWING / STABLE / DECLINING / COLLAPSING / UNKNOWN.
    UNKNOWN when fewer than _MIN_HISTORY_POINTS usable points, or when the
    oldest value is zero (percent change undefined).
    """
    clean = [v for v in (_safe_float(h) for h in history) if v is not None]
    if len(clean) < _MIN_HISTORY_POINTS:
        return _TREND_UNKNOWN

    change = _pct_change(clean[0], clean[-1])
    if change is None:
        return _TREND_UNKNOWN

    if change > _GROWING_THRESHOLD:
        return _TREND_GROWING
    if change >= _STABLE_LOWER:
        return _TREND_STABLE
    if change >= _DECLINING_LOWER:
        return _TREND_DECLINING
    return _TREND_COLLAPSING


def _risk_flag_for_trend(trend: str) -> str:
    """Map a trend label to a risk flag (HIGH / MEDIUM / LOW)."""
    if trend == _TREND_COLLAPSING:
        return _RISK_HIGH
    if trend == _TREND_DECLINING:
        return _RISK_MEDIUM
    return _RISK_LOW


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TVLPoint:
    """A single TVL observation for one adapter."""
    timestamp: str
    adapter_id: str
    tvl_usd: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "adapter_id": self.adapter_id,
            "tvl_usd": round(self.tvl_usd, 6),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TVLPoint":
        return cls(
            timestamp=str(d.get("timestamp", "")),
            adapter_id=str(d.get("adapter_id", "")),
            tvl_usd=float(_safe_float(d.get("tvl_usd", 0.0)) or 0.0),
        )


@dataclass
class TVLTrendResult:
    """Trend / risk classification for one adapter's TVL series."""
    adapter_id: str
    current_tvl: float
    change_pct_7d: Optional[float]
    change_pct_30d: Optional[float]
    trend: str
    risk_flag: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "current_tvl": round(self.current_tvl, 6),
            "change_pct_7d": (
                round(self.change_pct_7d, 4)
                if self.change_pct_7d is not None
                else None
            ),
            "change_pct_30d": (
                round(self.change_pct_30d, 4)
                if self.change_pct_30d is not None
                else None
            ),
            "trend": self.trend,
            "risk_flag": self.risk_flag,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TVLTrendResult":
        c7 = d.get("change_pct_7d", None)
        c30 = d.get("change_pct_30d", None)
        return cls(
            adapter_id=str(d.get("adapter_id", "")),
            current_tvl=float(_safe_float(d.get("current_tvl", 0.0)) or 0.0),
            change_pct_7d=(None if c7 is None else float(_safe_float(c7) or 0.0)),
            change_pct_30d=(None if c30 is None else float(_safe_float(c30) or 0.0)),
            trend=str(d.get("trend", _TREND_UNKNOWN)),
            risk_flag=str(d.get("risk_flag", _RISK_LOW)),
            timestamp=str(d.get("timestamp", "")),
        )


# ---------------------------------------------------------------------------
# TVLTrendMonitor
# ---------------------------------------------------------------------------

class TVLTrendMonitor:
    """Per-adapter TVL trend monitor (advisory only)."""

    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX
    MIN_HISTORY_POINTS: int = _MIN_HISTORY_POINTS

    def __init__(
        self,
        data_dir: Optional[str] = None,
        growing_threshold: float = _GROWING_THRESHOLD,
        stable_lower: float = _STABLE_LOWER,
        declining_lower: float = _DECLINING_LOWER,
    ) -> None:
        if data_dir is None:
            data_dir = str(_DEFAULT_DATA_DIR)
        self._data_dir = Path(data_dir)
        self.growing_threshold = growing_threshold
        self.stable_lower = stable_lower
        self.declining_lower = declining_lower
        self._ensure_stub()

    # ------------------------------------------------------------------
    # Stub
    # ------------------------------------------------------------------

    def _ensure_stub(self) -> None:
        """Create an empty data/tvl_trend_report.json stub ([]) if absent."""
        try:
            out_path = self._data_dir / self.OUTPUT_FILE
            if not out_path.exists():
                self._data_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write(out_path, [])
        except Exception:
            # Never raise on construction; degrade gracefully.
            pass

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_trend(self, history: List[float]) -> str:
        """
        Pure helper: classify a TVL history series into a trend label.

        Honours the monitor's configurable thresholds. Returns one of
        GROWING / STABLE / DECLINING / COLLAPSING / UNKNOWN.
        """
        clean = [v for v in (_safe_float(h) for h in history) if v is not None]
        if len(clean) < self.MIN_HISTORY_POINTS:
            return _TREND_UNKNOWN

        change = _pct_change(clean[0], clean[-1])
        if change is None:
            return _TREND_UNKNOWN

        if change > self.growing_threshold:
            return _TREND_GROWING
        if change >= self.stable_lower:
            return _TREND_STABLE
        if change >= self.declining_lower:
            return _TREND_DECLINING
        return _TREND_COLLAPSING

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record_tvl(
        self,
        adapter_id: str,
        tvl_usd: float,
        history: List[float],
    ) -> TVLTrendResult:
        """
        Build a TVLTrendResult for one adapter.

        Parameters
        ----------
        adapter_id : adapter identifier
        tvl_usd    : the adapter's current TVL in USD
        history    : trailing TVL series (oldest first, newest last). The
                     final value is treated as the current observation; when
                     ``tvl_usd`` differs it is appended as the newest point.
        """
        current = _safe_float(tvl_usd)
        if current is None:
            current = 0.0

        clean = [v for v in (_safe_float(h) for h in history) if v is not None]
        # Ensure the current observation is the newest point in the series.
        if not clean or clean[-1] != current:
            series = clean + [current]
        else:
            series = clean

        trend = self.classify_trend(series)
        risk_flag = _risk_flag_for_trend(trend)

        # 7d window: last up-to-7 points. 30d window: full series (up-to-30).
        if len(series) >= self.MIN_HISTORY_POINTS:
            window_7d = series[-7:]
            change_7d = _pct_change(window_7d[0], window_7d[-1])
            window_30d = series[-30:]
            change_30d = _pct_change(window_30d[0], window_30d[-1])
        else:
            change_7d = None
            change_30d = None

        return TVLTrendResult(
            adapter_id=adapter_id,
            current_tvl=current,
            change_pct_7d=change_7d,
            change_pct_30d=change_30d,
            trend=trend,
            risk_flag=risk_flag,
            timestamp=_now_iso(),
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        tvl_map: Dict[str, float],
        history_map: Dict[str, List[float]],
    ) -> dict:
        """
        Generate a full TVL trend report for all adapters.

        Parameters
        ----------
        tvl_map      : current TVL per adapter
        history_map  : trailing TVL series per adapter
        """
        results: List[TVLTrendResult] = []
        trend_counts: Dict[str, int] = {t: 0 for t in _ALL_TRENDS}
        flagged: List[str] = []

        if isinstance(tvl_map, dict):
            for adapter_id in sorted(tvl_map.keys()):
                raw_current = tvl_map.get(adapter_id, 0.0)
                current = _safe_float(raw_current)
                if current is None:
                    current = 0.0
                hist_raw = []
                if isinstance(history_map, dict):
                    hist_raw = history_map.get(adapter_id, []) or []
                if not isinstance(hist_raw, list):
                    hist_raw = []
                res = self.record_tvl(str(adapter_id), current, hist_raw)
                results.append(res)
                trend_counts[res.trend] = trend_counts.get(res.trend, 0) + 1
                if res.risk_flag in (_RISK_HIGH, _RISK_MEDIUM):
                    flagged.append(f"{res.adapter_id} ({res.risk_flag})")

        if flagged:
            advisory = _ADVISORY_PREFIX + ", ".join(flagged) + "." + _ADVISORY_SUFFIX
        else:
            advisory = _ADVISORY_CLEAN

        return {
            "generated_at": _now_iso(),
            "adapter_count": len(results),
            "results": [r.to_dict() for r in results],
            "trend_counts": trend_counts,
            "flagged_count": len(flagged),
            "advisory": advisory,
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: dict) -> str:
        """Atomic ring-buffer write to data/tvl_trend_report.json."""
        out_path = self._data_dir / self.OUTPUT_FILE
        self._data_dir.mkdir(parents=True, exist_ok=True)

        existing: List[dict] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError, ValueError):
                existing = []

        existing.append(report)
        if len(existing) > self.RING_BUFFER_SIZE:
            existing = existing[-self.RING_BUFFER_SIZE:]

        _atomic_write(out_path, existing)
        return str(out_path)


# ---------------------------------------------------------------------------
# Helpers (I/O)
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_synthetic_inputs() -> tuple:
    """Return minimal synthetic TVL / history for CLI demo."""
    import random
    rng = random.Random(11)

    # Base TVL and a per-adapter directional drift to exercise each trend.
    adapters = {
        "aave_v3": (1_000_000.0, 0.012),           # GROWING
        "compound_v3": (800_000.0, 0.001),         # STABLE
        "morpho_steakhouse": (600_000.0, -0.012),  # DECLINING
        "exodus_vault": (400_000.0, -0.05),        # COLLAPSING
        "new_adapter": (250_000.0, 0.0),           # < 2 points → UNKNOWN
    }
    tvl_map: Dict[str, float] = {}
    history_map: Dict[str, List[float]] = {}
    for aid, (base, drift) in adapters.items():
        if aid == "new_adapter":
            history_map[aid] = [base]  # single point → UNKNOWN
            tvl_map[aid] = base
            continue
        series: List[float] = []
        val = base
        for _ in range(20):
            val = max(0.0, val * (1.0 + drift) + rng.gauss(0, base * 0.001))
            series.append(round(val, 2))
        history_map[aid] = series
        tvl_map[aid] = series[-1]
    return tvl_map, history_map


def _load_live_data(data_dir: Path) -> tuple:
    """Attempt to load TVL data from existing data files; fall back to synthetic."""
    tvl_map: Dict[str, float] = {}
    history_map: Dict[str, List[float]] = {}

    # Best-effort: pull current TVL from adapter_status.json if present.
    status_path = data_dir / "adapter_status.json"
    if status_path.exists():
        try:
            with open(status_path, "r", encoding="utf-8") as fh:
                status = json.load(fh)
            adapters = status.get("adapters", status) if isinstance(status, dict) else {}
            if isinstance(adapters, dict):
                for adapter_id, info in adapters.items():
                    if isinstance(info, dict):
                        tvl = info.get("tvl_usd", info.get("tvl"))
                        if isinstance(tvl, (int, float)):
                            tvl_map[adapter_id] = float(tvl)
                            history_map[adapter_id] = [float(tvl)]
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            pass

    if not tvl_map:
        tvl_map, history_map = _build_synthetic_inputs()

    return tvl_map, history_map


def main(argv: Optional[List[str]] = None) -> None:
    args = sys.argv[1:] if argv is None else argv

    data_dir: Optional[str] = None
    do_run = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--run":
            do_run = True
        elif arg == "--check":
            do_run = False
        elif arg == "--data-dir" and i + 1 < len(args):
            i += 1
            data_dir = args[i]
        i += 1

    monitor = TVLTrendMonitor(data_dir=data_dir)
    tvl_map, history_map = _load_live_data(monitor._data_dir)
    report = monitor.generate_report(tvl_map, history_map)

    print(json.dumps(report, indent=2))

    if do_run:
        path = monitor.save_report(report)
        print(f"\n[tvl_trend_monitor] Saved -> {path}", file=sys.stderr)
    else:
        print("\n[tvl_trend_monitor] --check mode: no file written.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
