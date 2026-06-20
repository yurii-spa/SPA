# DEPRECATED — orphaned module. Canonical: spa_core.monitoring.cycle_health_monitor
# No active imports point here. TODO: remove in next cleanup.
# This file is kept for git history only.
raise ImportError(
    "DEPRECATED: use spa_core.monitoring.cycle_health_monitor instead"
)

"""
Cycle Runner Health Monitor (MP-631).
======================================

Monitors the health of the main trading cycle (cycle_runner.py execution).
Records per-cycle metrics, computes health scores, and generates advisory reports.

Data output: data/cycle_health_log.json  (ring-buffer 100 entries)

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic, fail-safe cleanup).
* Never raises on the happy path; missing / malformed data degrades gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).
* Deterministic: identical input → identical output.

Status rules
------------
  OK       — no errors AND duration_seconds < 120
  DEGRADED — errors present OR 120 ≤ duration_seconds < 300
  FAILED   — duration_seconds ≥ 300 OR len(errors) ≥ 5

Health score (0–100) across last N cycles:
  start 100, -10 per DEGRADED, -30 per FAILED, floor 0

CLI
---
  python3 -m spa_core.analytics.cycle_health_monitor --check   (compute + print, no write)
  python3 -m spa_core.analytics.cycle_health_monitor --run     (+ atomic save)
  python3 -m spa_core.analytics.cycle_health_monitor --run --data-dir PATH
"""
# from __future__ import annotations  # MP-1233: neutralized — unreachable below DEPRECATED raise, broke py_compile

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_HEALTH_LOG_FILE = "cycle_health_log.json"
_RING_BUFFER_MAX = 100

# Status thresholds
_DURATION_DEGRADED = 120.0   # seconds
_DURATION_FAILED   = 300.0   # seconds
_ERROR_COUNT_FAILED = 5      # errors → FAILED

# Health score
_HEALTH_SCORE_DEGRADED_PENALTY = 10
_HEALTH_SCORE_FAILED_PENALTY   = 30
_HEALTH_SCORE_MIN              = 0
_HEALTH_SCORE_MAX              = 100.0
_HEALTH_THRESHOLD              = 70.0  # is_system_healthy cutoff

STATUS_OK       = "OK"
STATUS_DEGRADED = "DEGRADED"
STATUS_FAILED   = "FAILED"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write: tmp-file + os.replace. Creates parent dirs."""
    from spa_core.utils.atomic import atomic_save
    atomic_save(payload, str(path))


def _load_log(path: Path) -> list:
    """Load ring-buffer JSON list from disk. Returns [] on any error."""
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CycleHealthEntry:
    """Snapshot of one cycle_runner execution."""
    timestamp: str               # ISO-8601 UTC
    cycle_id: str                # e.g. "2026-06-13T08:00:01"
    strategies_run: int          # number of strategies executed
    adapters_polled: int         # number of adapters queried
    errors: List[str]            # list of error strings encountered
    duration_seconds: float      # wall-clock time for the cycle
    status: str                  # "OK" / "DEGRADED" / "FAILED"
    apy_snapshot: Dict[str, float]  # adapter_id → APY at cycle time

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cycle_id": self.cycle_id,
            "strategies_run": self.strategies_run,
            "adapters_polled": self.adapters_polled,
            "errors": list(self.errors),
            "duration_seconds": round(self.duration_seconds, 3),
            "status": self.status,
            "apy_snapshot": {k: round(v, 6) for k, v in self.apy_snapshot.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "CycleHealthEntry":
        return CycleHealthEntry(
            timestamp=d.get("timestamp", ""),
            cycle_id=d.get("cycle_id", ""),
            strategies_run=int(d.get("strategies_run", 0)),
            adapters_polled=int(d.get("adapters_polled", 0)),
            errors=list(d.get("errors", [])),
            duration_seconds=float(d.get("duration_seconds", 0.0)),
            status=d.get("status", STATUS_OK),
            apy_snapshot={
                str(k): float(v)
                for k, v in d.get("apy_snapshot", {}).items()
            },
        )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CycleHealthMonitor:
    """
    Advisory monitor for cycle_runner.py execution health.

    Persists a ring-buffer (max 100) of CycleHealthEntry records to
    data/cycle_health_log.json. All methods are read-only advisory;
    no writes happen unless record_cycle() or log_* is called explicitly.
    """

    def __init__(self, data_dir: str | Path = _DEFAULT_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)
        self._log_path = self._data_dir / _HEALTH_LOG_FILE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_status(
        self,
        errors: List[str],
        duration_seconds: float,
    ) -> str:
        """Determine cycle status from errors and duration."""
        if duration_seconds >= _DURATION_FAILED or len(errors) >= _ERROR_COUNT_FAILED:
            return STATUS_FAILED
        if errors or duration_seconds >= _DURATION_DEGRADED:
            return STATUS_DEGRADED
        return STATUS_OK

    def _load_entries(self) -> List[CycleHealthEntry]:
        """Load all persisted entries from disk."""
        raw = _load_log(self._log_path)
        entries: List[CycleHealthEntry] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    entries.append(CycleHealthEntry.from_dict(item))
                except Exception:
                    pass
        return entries

    def _save_entries(self, entries: List[CycleHealthEntry]) -> None:
        """Atomically persist entries (ring-buffer trimmed to 100)."""
        trimmed = entries[-_RING_BUFFER_MAX:]
        _atomic_write_json(self._log_path, [e.to_dict() for e in trimmed])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_cycle(
        self,
        cycle_id: str,
        strategies_run: int,
        adapters_polled: int,
        errors: List[str],
        duration_seconds: float,
        apy_snapshot: Dict[str, float],
    ) -> CycleHealthEntry:
        """
        Record one completed cycle and persist to ring-buffer.

        Returns the created CycleHealthEntry.
        """
        errors = list(errors) if errors else []
        apy_snapshot = dict(apy_snapshot) if apy_snapshot else {}

        status = self._compute_status(errors, duration_seconds)

        entry = CycleHealthEntry(
            timestamp=_now_iso(),
            cycle_id=str(cycle_id),
            strategies_run=max(0, int(strategies_run)),
            adapters_polled=max(0, int(adapters_polled)),
            errors=errors,
            duration_seconds=float(duration_seconds),
            status=status,
            apy_snapshot={str(k): float(v) for k, v in apy_snapshot.items()},
        )

        entries = self._load_entries()
        entries.append(entry)
        self._save_entries(entries)
        return entry

    def get_recent_cycles(self, n: int = 10) -> List[CycleHealthEntry]:
        """Return the last N cycle entries (most-recent last)."""
        n = max(1, int(n))
        entries = self._load_entries()
        return entries[-n:]

    def compute_health_score(self, n: int = 10) -> float:
        """
        Compute a 0–100 health score over the last N cycles.

        100 if all OK; -10 per DEGRADED, -30 per FAILED, floor 0.
        Returns 100.0 if there are no entries.
        """
        n = max(1, int(n))
        entries = self._load_entries()
        recent = entries[-n:]
        if not recent:
            return _HEALTH_SCORE_MAX

        score = _HEALTH_SCORE_MAX
        for e in recent:
            if e.status == STATUS_DEGRADED:
                score -= _HEALTH_SCORE_DEGRADED_PENALTY
            elif e.status == STATUS_FAILED:
                score -= _HEALTH_SCORE_FAILED_PENALTY

        return max(float(_HEALTH_SCORE_MIN), score)

    def get_error_frequency(self, n: int = 20) -> Dict[str, int]:
        """
        Count occurrences of each unique error string across last N cycles.

        Returns dict mapping error string → count, sorted by count descending.
        """
        n = max(1, int(n))
        entries = self._load_entries()
        recent = entries[-n:]

        freq: Dict[str, int] = {}
        for e in recent:
            for err in e.errors:
                freq[err] = freq.get(err, 0) + 1

        # Sort by count descending
        return dict(sorted(freq.items(), key=lambda x: x[1], reverse=True))

    def is_system_healthy(self, n: int = 5) -> bool:
        """
        Returns True if health_score >= 70 across last N cycles.

        True when no entries exist (system never failed).
        """
        return self.compute_health_score(n) >= _HEALTH_THRESHOLD

    def generate_report(self) -> dict:
        """
        Generate a full advisory health report.

        Returns a dict with:
          health_score       — float 0–100
          is_healthy         — bool
          recent_summary     — {OK: int, DEGRADED: int, FAILED: int}
          error_frequency    — dict[error_str, count] (last 20 cycles)
          last_cycle         — dict or None
          advisory           — human-readable summary string
        """
        entries = self._load_entries()
        recent_10 = entries[-10:]

        health_score = self.compute_health_score(10)
        is_healthy = health_score >= _HEALTH_THRESHOLD

        status_counts: Dict[str, int] = {
            STATUS_OK: 0,
            STATUS_DEGRADED: 0,
            STATUS_FAILED: 0,
        }
        for e in recent_10:
            if e.status in status_counts:
                status_counts[e.status] += 1

        error_freq = self.get_error_frequency(20)

        last_cycle = entries[-1].to_dict() if entries else None

        # Advisory text
        if not entries:
            advisory = "No cycles recorded yet. System awaiting first cycle run."
        elif is_healthy:
            advisory = (
                f"System healthy. Score {health_score:.0f}/100 over last "
                f"{len(recent_10)} cycles. "
                f"OK={status_counts[STATUS_OK]}, "
                f"DEGRADED={status_counts[STATUS_DEGRADED]}, "
                f"FAILED={status_counts[STATUS_FAILED]}."
            )
        else:
            top_errors = list(error_freq.keys())[:3]
            advisory = (
                f"System DEGRADED. Score {health_score:.0f}/100 over last "
                f"{len(recent_10)} cycles. "
                f"DEGRADED={status_counts[STATUS_DEGRADED]}, "
                f"FAILED={status_counts[STATUS_FAILED]}. "
                f"Top errors: {top_errors}. Investigate cycle_runner logs."
            )

        return {
            "generated_at": _now_iso(),
            "health_score": health_score,
            "is_healthy": is_healthy,
            "recent_summary": status_counts,
            "error_frequency": error_freq,
            "last_cycle": last_cycle,
            "advisory": advisory,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-631 Cycle Runner Health Monitor"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Generate report and write to data/cycle_health_log.json"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Compute and print report (no write, default mode)"
    )
    parser.add_argument(
        "--data-dir", default=str(_DEFAULT_DATA_DIR),
        help="Path to data directory"
    )
    args = parser.parse_args(argv)

    monitor = CycleHealthMonitor(data_dir=args.data_dir)
    report = monitor.generate_report()

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.run:
        # Record a synthetic check-only cycle (advisory, no side-effects on real data)
        # In production, cycle_runner.py calls record_cycle() directly.
        out_path = Path(args.data_dir) / _HEALTH_LOG_FILE
        print(f"\n[CycleHealthMonitor] Report generated. Log: {out_path}", file=sys.stderr)
    else:
        print(
            "\n[CycleHealthMonitor] --check mode: no data written.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    _main()
