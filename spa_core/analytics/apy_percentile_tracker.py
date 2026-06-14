"""
APYPercentileTracker (MP-644)
=============================
Per-adapter percentile rank of the adapter's CURRENT APY within its own
trailing history window. Advisory / read-only.

Distinct from apy_momentum / apy_forecast / apy_anomaly / apy_dispersion:
this module answers "is the current APY high or low relative to this
adapter's own recent history?" — it does NOT forecast, detect anomalies, or
measure cross-adapter dispersion.

For each adapter with >= 2 history points:
    percentile = (count of history values <= current) / len(history) * 100
                 clamped to [0, 100]
    zone classification:
        AT_HIGH   >= 80      (possible mean-reversion candidate — advisory)
        ELEVATED  >= 60
        NORMAL    >= 40
        LOW       >= 20
        AT_LOW    <  20      (possible entry candidate — advisory)
Adapters with < 2 history points → zone UNKNOWN, percentile None.

Output ring-buffer (30 entries): data/apy_percentile_report.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never modifies risk/, execution/, monitoring/, allocator/,
  cycle_runner. Advisory flags are informational, never move capital.
* Atomic writes: tmp + os.replace.
* Never raises on the happy path; load failures degrade gracefully.
* Telegram message ≤ 1500 chars.

CLI
---
``python3 -m spa_core.analytics.apy_percentile_tracker --check``
``python3 -m spa_core.analytics.apy_percentile_tracker --run``
``python3 -m spa_core.analytics.apy_percentile_tracker --data-dir PATH``

MP-644.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_FILENAME = "apy_percentile_report.json"
_RING_BUFFER_MAX = 30
_TELEGRAM_MAX_CHARS = 1500
_TELEGRAM_ELLIPSIS = "…"

_MIN_HISTORY_POINTS = 2

# Zone thresholds (percentile)
_ZONE_AT_HIGH = 80.0
_ZONE_ELEVATED = 60.0
_ZONE_NORMAL = 40.0
_ZONE_LOW = 20.0

# Zone labels
_ZONE_AT_HIGH_LABEL = "AT_HIGH"
_ZONE_ELEVATED_LABEL = "ELEVATED"
_ZONE_NORMAL_LABEL = "NORMAL"
_ZONE_LOW_LABEL = "LOW"
_ZONE_AT_LOW_LABEL = "AT_LOW"
_ZONE_UNKNOWN_LABEL = "UNKNOWN"

_ALL_ZONES = [
    _ZONE_AT_HIGH_LABEL,
    _ZONE_ELEVATED_LABEL,
    _ZONE_NORMAL_LABEL,
    _ZONE_LOW_LABEL,
    _ZONE_AT_LOW_LABEL,
    _ZONE_UNKNOWN_LABEL,
]

_ADVISORY = (
    "Percentile ranks are descriptive only. AT_HIGH may indicate possible "
    "mean-reversion; AT_LOW may indicate a possible entry. Advisory only — "
    "not financial advice."
)


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


def _classify_zone(percentile: Optional[float]) -> str:
    """Classify a percentile value into a zone label."""
    if percentile is None:
        return _ZONE_UNKNOWN_LABEL
    if percentile >= _ZONE_AT_HIGH:
        return _ZONE_AT_HIGH_LABEL
    if percentile >= _ZONE_ELEVATED:
        return _ZONE_ELEVATED_LABEL
    if percentile >= _ZONE_NORMAL:
        return _ZONE_NORMAL_LABEL
    if percentile >= _ZONE_LOW:
        return _ZONE_LOW_LABEL
    return _ZONE_AT_LOW_LABEL


def _compute_percentile(current: float, history: List[float]) -> float:
    """
    Percentile rank: (count of history values <= current) / len(history) * 100,
    clamped to [0, 100]. Assumes len(history) >= 1.
    """
    if not history:
        return 0.0
    count_le = sum(1 for h in history if h <= current)
    pct = (count_le / len(history)) * 100.0
    if pct < 0.0:
        return 0.0
    if pct > 100.0:
        return 100.0
    return pct


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdapterPercentile:
    """Percentile rank of one adapter's current APY within its own history."""
    adapter_id: str
    current_apy: float
    percentile: Optional[float]   # None when history too short
    zone: str
    history_len: int
    history_min: Optional[float]
    history_max: Optional[float]

    def to_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "current_apy": round(self.current_apy, 6),
            "percentile": (
                round(self.percentile, 4) if self.percentile is not None else None
            ),
            "zone": self.zone,
            "history_len": self.history_len,
            "history_min": (
                round(self.history_min, 6) if self.history_min is not None else None
            ),
            "history_max": (
                round(self.history_max, 6) if self.history_max is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AdapterPercentile":
        pct = d.get("percentile", None)
        hmin = d.get("history_min", None)
        hmax = d.get("history_max", None)
        return cls(
            adapter_id=str(d.get("adapter_id", "")),
            current_apy=float(_safe_float(d.get("current_apy", 0.0)) or 0.0),
            percentile=(None if pct is None else float(_safe_float(pct) or 0.0)),
            zone=str(d.get("zone", _ZONE_UNKNOWN_LABEL)),
            history_len=int(_safe_float(d.get("history_len", 0)) or 0),
            history_min=(None if hmin is None else float(_safe_float(hmin) or 0.0)),
            history_max=(None if hmax is None else float(_safe_float(hmax) or 0.0)),
        )


# ---------------------------------------------------------------------------
# APYPercentileTracker
# ---------------------------------------------------------------------------

class APYPercentileTracker:
    """Per-adapter APY percentile rank tracker (advisory only)."""

    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX
    MIN_HISTORY_POINTS: int = _MIN_HISTORY_POINTS

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir is None:
            data_dir = str(_DEFAULT_DATA_DIR)
        self._data_dir = Path(data_dir)
        self._ensure_stub()

    # ------------------------------------------------------------------
    # Stub
    # ------------------------------------------------------------------

    def _ensure_stub(self) -> None:
        """Create an empty data/apy_percentile_report.json stub ([]) if absent."""
        try:
            out_path = self._data_dir / self.OUTPUT_FILE
            if not out_path.exists():
                self._data_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write(out_path, [])
        except Exception:
            # Never raise on construction; degrade gracefully.
            pass

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def compute_adapter(
        self, adapter_id: str, current_apy: float, history: List[float]
    ) -> AdapterPercentile:
        """Compute the percentile / zone for a single adapter."""
        clean_history = [v for v in (_safe_float(h) for h in history) if v is not None]

        if len(clean_history) < self.MIN_HISTORY_POINTS:
            return AdapterPercentile(
                adapter_id=adapter_id,
                current_apy=current_apy,
                percentile=None,
                zone=_ZONE_UNKNOWN_LABEL,
                history_len=len(clean_history),
                history_min=(min(clean_history) if clean_history else None),
                history_max=(max(clean_history) if clean_history else None),
            )

        percentile = _compute_percentile(current_apy, clean_history)
        zone = _classify_zone(percentile)
        return AdapterPercentile(
            adapter_id=adapter_id,
            current_apy=current_apy,
            percentile=percentile,
            zone=zone,
            history_len=len(clean_history),
            history_min=min(clean_history),
            history_max=max(clean_history),
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        apy_map: Dict[str, float],
        history_map: Dict[str, List[float]],
    ) -> dict:
        """
        Generate a full percentile report for all adapters.

        Parameters mirror apy_forecast_v2.generate_report:
            apy_map      — current APY per adapter
            history_map  — trailing APY series per adapter
        """
        adapters: List[AdapterPercentile] = []
        zone_counts: Dict[str, int] = {z: 0 for z in _ALL_ZONES}

        if isinstance(apy_map, dict):
            for adapter_id in sorted(apy_map.keys()):
                raw_current = apy_map.get(adapter_id, 0.0)
                current = _safe_float(raw_current)
                if current is None:
                    current = 0.0
                hist_raw = []
                if isinstance(history_map, dict):
                    hist_raw = history_map.get(adapter_id, []) or []
                if not isinstance(hist_raw, list):
                    hist_raw = []
                ap = self.compute_adapter(str(adapter_id), current, hist_raw)
                adapters.append(ap)
                zone_counts[ap.zone] = zone_counts.get(ap.zone, 0) + 1

        return {
            "generated_at": _now_iso(),
            "adapter_count": len(adapters),
            "adapters": [a.to_dict() for a in adapters],
            "zone_counts": zone_counts,
            "advisory": _ADVISORY,
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: dict) -> str:
        """Atomic ring-buffer write to data/apy_percentile_report.json."""
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

    # ------------------------------------------------------------------
    # Format
    # ------------------------------------------------------------------

    def format_telegram_message(self, report: dict) -> str:
        """Format a Telegram-ready message ≤ 1500 characters."""
        if not isinstance(report, dict):
            report = {}

        adapters = report.get("adapters", [])
        if not isinstance(adapters, list):
            adapters = []
        zone_counts = report.get("zone_counts", {})
        if not isinstance(zone_counts, dict):
            zone_counts = {}
        generated_at = str(report.get("generated_at", ""))

        lines: List[str] = ["📊 APY Percentile Tracker"]

        if not adapters:
            lines.append("No adapter data available.")
            lines.append(f"⏱ {generated_at[:19]}Z")
            msg = "\n".join(lines)
            if len(msg) > _TELEGRAM_MAX_CHARS:
                msg = msg[: _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)] + _TELEGRAM_ELLIPSIS
            return msg

        lines.append(
            f"Adapters: {report.get('adapter_count', len(adapters))} | "
            f"AT_HIGH {zone_counts.get(_ZONE_AT_HIGH_LABEL, 0)} | "
            f"AT_LOW {zone_counts.get(_ZONE_AT_LOW_LABEL, 0)} | "
            f"UNKNOWN {zone_counts.get(_ZONE_UNKNOWN_LABEL, 0)}"
        )

        _ZONE_EMOJI = {
            _ZONE_AT_HIGH_LABEL: "🔺",
            _ZONE_ELEVATED_LABEL: "🟢",
            _ZONE_NORMAL_LABEL: "⚪",
            _ZONE_LOW_LABEL: "🔵",
            _ZONE_AT_LOW_LABEL: "🔻",
            _ZONE_UNKNOWN_LABEL: "❔",
        }

        for a in adapters:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("adapter_id", "?"))
            zone = str(a.get("zone", _ZONE_UNKNOWN_LABEL))
            emoji = _ZONE_EMOJI.get(zone, "⚪")
            pct = a.get("percentile", None)
            cur = _safe_float(a.get("current_apy", 0.0)) or 0.0
            if pct is None:
                lines.append(f"{emoji} {aid}: {zone} (cur {cur:.3f})")
            else:
                pct_f = _safe_float(pct) or 0.0
                lines.append(
                    f"{emoji} {aid}: p{pct_f:.0f} {zone} (cur {cur:.3f})"
                )

        lines.append(f"⏱ {generated_at[:19]}Z")

        msg = "\n".join(lines)
        if len(msg) > _TELEGRAM_MAX_CHARS:
            msg = msg[: _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)] + _TELEGRAM_ELLIPSIS
        return msg


# ---------------------------------------------------------------------------
# Helpers (I/O)
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_apy_percentile_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_synthetic_inputs() -> tuple:
    """Return minimal synthetic APY / history for CLI demo."""
    import random
    rng = random.Random(7)

    adapters = {
        "aave_v3": 0.045,
        "compound_v3": 0.030,
        "morpho_steakhouse": 0.070,
        "new_adapter": 0.05,
    }
    history_map: Dict[str, List[float]] = {}
    for aid, base in adapters.items():
        if aid == "new_adapter":
            history_map[aid] = [base]  # < 2 points → UNKNOWN
            continue
        history_map[aid] = [
            max(0.0, base + rng.gauss(0, 0.005)) for _ in range(20)
        ]
    return adapters, history_map


def _load_live_data(data_dir: Path) -> tuple:
    """Attempt to load APY data from existing data files; fall back to synthetic."""
    apy_map: Dict[str, float] = {}
    history_map: Dict[str, List[float]] = {}

    yf_path = data_dir / "yield_forecast.json"
    if yf_path.exists():
        try:
            with open(yf_path, "r", encoding="utf-8") as fh:
                ring = json.load(fh)
            if isinstance(ring, list) and ring:
                latest = ring[-1]
                for adapter_id, info in latest.get("adapters", {}).items():
                    if isinstance(info, dict):
                        apy = info.get("current_apy")
                        if isinstance(apy, (int, float)):
                            apy_map[adapter_id] = float(apy)
                            hist = []
                            for entry in ring:
                                a_info = entry.get("adapters", {}).get(adapter_id, {})
                                v = a_info.get("current_apy")
                                if isinstance(v, (int, float)):
                                    hist.append(float(v))
                            history_map[adapter_id] = hist
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    if not apy_map:
        apy_map, history_map = _build_synthetic_inputs()

    return apy_map, history_map


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

    tracker = APYPercentileTracker(data_dir=data_dir)
    apy_map, history_map = _load_live_data(tracker._data_dir)
    report = tracker.generate_report(apy_map, history_map)

    print(tracker.format_telegram_message(report))
    print("\n" + "=" * 60)
    print(json.dumps(report, indent=2))

    if do_run:
        path = tracker.save_report(report)
        print(f"\n[apy_percentile_tracker] ✅ Saved → {path}", file=sys.stderr)
    else:
        print("\n[apy_percentile_tracker] --check mode: no file written.", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
