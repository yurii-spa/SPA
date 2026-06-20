"""
spa_core/monitor/data_freshness_monitor.py

Sprint v11.21 — MP-1505: Stale data detector + freshness alerts.

Checks all known data files for staleness against configurable thresholds.
Reports FRESH / STALE / MISSING per data type.  Writes results to
data/data_freshness_monitor.json atomically.

Architecture
------------
- Strictly read-only / advisory — never modifies any state file.
- Pure stdlib; inherits BaseAnalytics for atomic save/load.
- CLI:  python3 -m spa_core.monitor.data_freshness_monitor --check | --run

Freshness thresholds (seconds):
  apy_data         1 h   (3 600 s)
  portfolio_nav    1 day (86 400 s)
  gate_status      7 d   (604 800 s)
  backtest_results 30 d  (2 592 000 s)
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Optional

from spa_core.base import BaseAnalytics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Freshness thresholds (seconds)
# ---------------------------------------------------------------------------

FRESHNESS_THRESHOLDS: dict[str, int] = {
    "apy_data":          3_600,            # 1 hour
    "portfolio_nav":     86_400,           # 1 day
    "gate_status":       86_400 * 7,       # 1 week
    "backtest_results":  86_400 * 30,      # 30 days
}

# Canonical file paths relative to base_dir
_FILE_MAP: dict[str, str] = {
    "apy_data":          "data/apy_data.json",
    "portfolio_nav":     "data/portfolio_nav.json",
    "gate_status":       "data/gate_status.json",
    "backtest_results":  "data/backtest_results.json",
}

# Human-readable threshold labels
_THRESHOLD_LABELS: dict[str, str] = {
    "apy_data":          "1 hour",
    "portfolio_nav":     "1 day",
    "gate_status":       "7 days",
    "backtest_results":  "30 days",
}


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_FRESH   = "FRESH"
STATUS_STALE   = "STALE"
STATUS_MISSING = "MISSING"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DataFreshnessMonitor(BaseAnalytics):
    """Checks all known data files for staleness.

    Parameters
    ----------
    base_dir:
        Project root directory (default ".").
    thresholds:
        Optional override for FRESHNESS_THRESHOLDS dict (useful in tests).
    file_map:
        Optional override for _FILE_MAP dict (useful in tests).
    clock:
        Optional callable returning current UTC timestamp as float
        (default: time.time()).  Injected for deterministic testing.
    """

    OUTPUT_PATH = "data/data_freshness_monitor.json"

    def __init__(
        self,
        base_dir: str = ".",
        thresholds: Optional[dict[str, int]] = None,
        file_map: Optional[dict[str, str]] = None,
        clock=None,
    ) -> None:
        super().__init__(base_dir)
        self._thresholds = thresholds if thresholds is not None else FRESHNESS_THRESHOLDS
        self._file_map = file_map if file_map is not None else _FILE_MAP
        self._clock = clock if clock is not None else __import__("time").time
        self._data: dict = {
            "checks": {},
            "stale_files": [],
            "missing_files": [],
            "fresh_files": [],
            "last_run": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> dict:
        """Check all registered data files for freshness.

        Returns
        -------
        dict with keys:
            checks       – {data_type: {status, age_sec, threshold, path}}
            stale_files  – list of data_type strings with STALE status
            missing_files– list of data_type strings with MISSING status
            fresh_files  – list of data_type strings with FRESH status
            last_run     – ISO UTC timestamp
        """
        now = self._clock()
        stale: list[str] = []
        missing: list[str] = []
        fresh: list[str] = []
        checks: dict = {}

        for data_type, max_age_sec in self._thresholds.items():
            file_path = self._resolve_path(data_type)
            check = self._check_file(data_type, file_path, max_age_sec, now)
            checks[data_type] = check

            if check["status"] == STATUS_STALE:
                stale.append(data_type)
            elif check["status"] == STATUS_MISSING:
                missing.append(data_type)
            else:
                fresh.append(data_type)

        self._data = {
            "checks": checks,
            "stale_files": stale,
            "missing_files": missing,
            "fresh_files": fresh,
            "last_run": datetime.datetime.utcnow().isoformat(),
            "summary": {
                "total": len(checks),
                "fresh": len(fresh),
                "stale": len(stale),
                "missing": len(missing),
            },
        }

        if stale:
            logger.warning(
                "DataFreshnessMonitor: %d stale file(s): %s",
                len(stale), ", ".join(stale),
            )
        if missing:
            logger.info(
                "DataFreshnessMonitor: %d missing file(s): %s",
                len(missing), ", ".join(missing),
            )

        return self._data

    def is_fresh(self, data_type: str) -> Optional[bool]:
        """Return True if *data_type* is FRESH, False if STALE/MISSING, None if unknown."""
        checks = self._data.get("checks", {})
        if data_type not in checks:
            return None
        return checks[data_type]["status"] == STATUS_FRESH

    def stale_count(self) -> int:
        """Return number of STALE files from the last check_all() run."""
        return len(self._data.get("stale_files", []))

    def missing_count(self) -> int:
        """Return number of MISSING files from the last check_all() run."""
        return len(self._data.get("missing_files", []))

    def to_dict(self) -> dict:
        return self._data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, data_type: str) -> Optional[str]:
        """Resolve the full path for *data_type* relative to base_dir."""
        rel = self._file_map.get(data_type)
        if rel is None:
            return None
        return os.path.join(self.base_dir, rel)

    def _check_file(
        self,
        data_type: str,
        file_path: Optional[str],
        max_age_sec: int,
        now: float,
    ) -> dict:
        """Return a freshness check result dict for one data file."""
        label = _THRESHOLD_LABELS.get(data_type, f"{max_age_sec}s")

        if file_path is None or not os.path.exists(file_path):
            return {
                "status": STATUS_MISSING,
                "age_sec": None,
                "threshold_sec": max_age_sec,
                "threshold_label": label,
                "path": file_path,
            }

        mtime = os.path.getmtime(file_path)
        age_sec = now - mtime

        if age_sec > max_age_sec:
            logger.debug(
                "DataFreshnessMonitor: %s is STALE (age=%.0fs, threshold=%ds)",
                data_type, age_sec, max_age_sec,
            )
            return {
                "status": STATUS_STALE,
                "age_sec": age_sec,
                "threshold_sec": max_age_sec,
                "threshold_label": label,
                "path": file_path,
            }

        return {
            "status": STATUS_FRESH,
            "age_sec": age_sec,
            "threshold_sec": max_age_sec,
            "threshold_label": label,
            "path": file_path,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Data Freshness Monitor — stale data detector"
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without saving (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically save to data/")
    parser.add_argument("--data-dir", default=".",
                        help="Project root directory")
    args = parser.parse_args(argv)

    monitor = DataFreshnessMonitor(base_dir=args.data_dir)
    result = monitor.check_all()

    print(json.dumps(result, indent=2, default=str))

    if args.run:
        path = monitor.save()
        print(f"\n[data_freshness_monitor] Saved → {path}")


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
