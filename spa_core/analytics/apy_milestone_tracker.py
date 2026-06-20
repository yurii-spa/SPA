"""
APY Milestone Tracker — MP-383

Daily log of portfolio APY against fixed milestone thresholds.
Tracks which milestones have been reached and provides rolling stats.

Storage: data/apy_milestone_log.json
  - Atomic writes (mkstemp + os.replace)
  - Pure stdlib, no external dependencies
  - Read-only/advisory — never touches allocator/risk/execution

MP-1406: Migrated to BaseAnalytics (Phase 1 — inheritance + to_dict only).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Milestone definitions
# ---------------------------------------------------------------------------
APY_MILESTONES = [
    {"level": 1, "name": "Baseline beat",  "target_pct": 5.0,  "description": "Превышает Aave 3.2%"},
    {"level": 2, "name": "Target entry",   "target_pct": 7.0,  "description": "Минимальный целевой APY"},
    {"level": 3, "name": "Target mid",     "target_pct": 10.0, "description": "Уверенное превышение цели"},
    {"level": 4, "name": "Target high",    "target_pct": 12.0, "description": "S11 territory"},
    {"level": 5, "name": "Spec target",    "target_pct": 15.0, "description": "Спекулятивный максимум"},
]

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_LOG_FILENAME = "apy_milestone_log.json"


# ---------------------------------------------------------------------------
# Tracker class
# ---------------------------------------------------------------------------

class ApyMilestoneTracker(BaseAnalytics):
    """
    Tracks daily APY against milestone thresholds and persists the log.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory for the log file. Defaults to <repo-root>/data/.
    """

    OUTPUT_PATH = "data/apy_milestone_log.json"

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        super().__init__()  # sets self.base_dir = "."
        if data_dir is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_dir)
        self._log_path = self._data_dir / _LOG_FILENAME
        self._data: dict = self._load()

    def to_dict(self) -> dict:
        """Returns current in-memory milestone log state."""
        return self._data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, *args: Any, **kwargs: Any) -> dict:
        """BaseAnalytics contract: return the current milestone report.

        Delegates to :meth:`get_milestone_report`. Without this method the
        class is abstract and cannot be instantiated (BaseAnalytics.analyze
        is ``@abstractmethod``).
        """
        return self.get_milestone_report()

    def record_day(
        self,
        date_iso: str,
        apy_pct: float,
        strategy_id: str = "tournament_winner",
    ) -> dict:
        """
        Record the APY for a given date.

        Deduplicates by date — if the date already exists the entry is
        overwritten with the new values.

        Returns a dict with the current milestone statuses.
        """
        entry = {
            "date": date_iso,
            "apy_pct": round(float(apy_pct), 6),
            "strategy_id": strategy_id,
        }

        # Deduplicate: replace existing entry for this date
        log = self._data["daily_log"]
        existing_idx = next(
            (i for i, e in enumerate(log) if e["date"] == date_iso), None
        )
        if existing_idx is not None:
            log[existing_idx] = entry
        else:
            log.append(entry)

        # Update metadata
        self._data["days_recorded"] = len(log)
        self._data["last_updated"] = datetime.now(timezone.utc).date().isoformat()

        # Compute which milestones have ever been reached
        self._refresh_milestones_reached()

        self._save()

        return self.get_milestone_report()

    def get_current_milestones(self) -> list:
        """
        Return all milestones with their current reached/not-reached status.

        Each item:
        {
            "level": int,
            "name": str,
            "target_pct": float,
            "description": str,
            "reached": bool,
            "first_reached_date": str | None,
            "days_above": int,
        }
        """
        reached_map = {
            r["level"]: r for r in self._data.get("milestones_reached", [])
        }
        result = []
        for m in APY_MILESTONES:
            days_above = self.get_days_above(m["target_pct"])
            r = reached_map.get(m["level"])
            result.append({
                "level": m["level"],
                "name": m["name"],
                "target_pct": m["target_pct"],
                "description": m["description"],
                "reached": r is not None,
                "first_reached_date": r["first_reached_date"] if r else None,
                "days_above": days_above,
            })
        return result

    def get_days_above(self, target_pct: float) -> int:
        """Return number of recorded days where APY >= target_pct."""
        return sum(
            1 for e in self._data["daily_log"] if e["apy_pct"] >= target_pct
        )

    def get_avg_apy(self, days: int = 7) -> float:
        """
        Rolling average APY over the last *days* recorded entries.

        Returns 0.0 if there are no entries.
        """
        log = self._data["daily_log"]
        if not log:
            return 0.0
        window = log[-days:]
        return round(sum(e["apy_pct"] for e in window) / len(window), 6)

    def get_best_day(self) -> dict:
        """
        Return the entry with the highest APY.

        Returns an empty dict if no days have been recorded.
        """
        log = self._data["daily_log"]
        if not log:
            return {}
        return max(log, key=lambda e: e["apy_pct"])

    def get_milestone_report(self) -> dict:
        """
        Full report suitable for dashboards or JSON serialisation.

        Structure:
        {
            "start_date": str,
            "last_updated": str,
            "days_recorded": int,
            "avg_apy_7d": float,
            "best_day": dict,
            "milestones": list[dict],
            "milestones_reached_count": int,
            "milestones_total": int,
        }
        """
        milestones = self.get_current_milestones()
        return {
            "start_date": self._data.get("start_date", ""),
            "last_updated": self._data.get("last_updated", ""),
            "days_recorded": self._data.get("days_recorded", 0),
            "avg_apy_7d": self.get_avg_apy(7),
            "best_day": self.get_best_day(),
            "milestones": milestones,
            "milestones_reached_count": sum(1 for m in milestones if m["reached"]),
            "milestones_total": len(APY_MILESTONES),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_milestones_reached(self) -> None:
        """Rebuild milestones_reached list from daily_log."""
        # Build per-level: first date each level was reached
        reached: dict[int, str] = {}
        for entry in sorted(self._data["daily_log"], key=lambda e: e["date"]):
            for m in APY_MILESTONES:
                lvl = m["level"]
                if lvl not in reached and entry["apy_pct"] >= m["target_pct"]:
                    reached[lvl] = entry["date"]

        self._data["milestones_reached"] = [
            {
                "level": lvl,
                "name": next(
                    m["name"] for m in APY_MILESTONES if m["level"] == lvl
                ),
                "target_pct": next(
                    m["target_pct"] for m in APY_MILESTONES if m["level"] == lvl
                ),
                "first_reached_date": date,
            }
            for lvl, date in sorted(reached.items())
        ]

    def _load(self) -> dict:
        """Load existing log or create a fresh skeleton."""
        if self._log_path.exists():
            try:
                data = json.loads(self._log_path.read_text(encoding="utf-8"))
                # Ensure required keys exist (forward-compat)
                data.setdefault("daily_log", [])
                data.setdefault("milestones_reached", [])
                data.setdefault("days_recorded", len(data["daily_log"]))
                return data
            except (json.JSONDecodeError, OSError):
                pass

        # Fresh skeleton
        today = datetime.now(timezone.utc).date().isoformat()
        return {
            "start_date": today,
            "last_updated": today,
            "days_recorded": 0,
            "daily_log": [],
            "milestones_reached": [],
        }

    def _save(self) -> None:
        """Atomically write the log to disk (mkstemp + os.replace)."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        from spa_core.utils.atomic import atomic_save
        atomic_save(self._data, str(self._log_path))


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli() -> None:
    import sys

    tracker = ApyMilestoneTracker()
    report = tracker.get_milestone_report()

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"=== APY Milestone Tracker ===")
    print(f"Start date   : {report['start_date']}")
    print(f"Last updated : {report['last_updated']}")
    print(f"Days recorded: {report['days_recorded']}")
    print(f"7-day avg APY: {report['avg_apy_7d']:.3f}%")
    best = report["best_day"]
    if best:
        print(f"Best day     : {best['date']} — {best['apy_pct']:.3f}% ({best['strategy_id']})")
    print()
    reached = report["milestones_reached_count"]
    total = report["milestones_total"]
    print(f"Milestones: {reached}/{total} reached")
    for m in report["milestones"]:
        status = "✅" if m["reached"] else "  "
        first = f"  (first: {m['first_reached_date']})" if m["first_reached_date"] else ""
        above = f"  [{m['days_above']}d above]"
        print(f"  {status} L{m['level']} {m['name']:<15} ≥{m['target_pct']:>5.1f}%{first}{above}")


if __name__ == "__main__":
    _cli()
