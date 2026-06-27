"""
Agent Stability Tracker — SPA-F001

Tracks consecutive days of stable agent operation for the go-live criterion 12.
"Stable" means: status.json was updated recently (< 6 h ago) on every check.
If status.json becomes stale (> 6 h) or is missing, the stability clock resets.

State is persisted in  data/agent_stability.json  relative to the repo root.

Typical usage (called once per export run):
    tracker = AgentStabilityTracker()
    tracker.update(data_dir="/path/to/data")   # idempotent if called twice in same hour
    result  = tracker.check_criterion()
    # result = {"status": "PASS"|"WARN"|"FAIL", "days": float, ...}

Clock logic:
    • First call → writes stable_since = now, is_active = True
    • Subsequent calls where status.json is fresh (< 6 h) → extends the clock
    • Call where status.json is stale/missing → resets stable_since, records failure
    • 28+ stable days → PASS
    • 14–28 days    → WARN
    • < 14 days     → FAIL
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Go-live threshold (days of consecutive stable operation)
MIN_STABLE_DAYS: int = 28

# status.json is considered "fresh" if updated within this many hours
FRESHNESS_THRESHOLD_H: float = 6.0

# Default paths
_REPO_ROOT         = Path(__file__).parent.parent.parent
_DEFAULT_DATA_DIR  = _REPO_ROOT / "data"
_DEFAULT_STATE_FILE = _DEFAULT_DATA_DIR / "agent_stability.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _elapsed_days(since_iso: str) -> float:
    """Return fractional days elapsed since *since_iso*. Returns 0.0 on error."""
    try:
        return (_now() - _parse_iso(since_iso)).total_seconds() / 86_400
    except Exception:
        return 0.0


# ── AgentStabilityTracker ─────────────────────────────────────────────────────

class AgentStabilityTracker:
    """Persistent stability clock driven by status.json freshness.

    State schema (data/agent_stability.json):
    {
        "stable_since":            "<ISO-8601 | null>",
        "last_check":              "<ISO-8601 | null>",
        "consecutive_stable_days": 0.0,
        "total_failures":          0,
        "failure_history": [
            {"time": "<ISO>", "reason": "<str>"}
        ],
        "is_active": false
    }
    """

    def __init__(
        self,
        state_file: Path | str | None = None,
        data_dir:   Path | str | None = None,
    ) -> None:
        if state_file:
            self._file = Path(state_file)
        elif data_dir:
            self._file = Path(data_dir) / "agent_stability.json"
        else:
            self._file = _DEFAULT_STATE_FILE

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "stable_since":            None,
                "last_check":              None,
                "consecutive_stable_days": 0.0,
                "total_failures":          0,
                "failure_history":         [],
                "is_active":               False,
            }

    def _save(self, state: dict[str, Any]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _status_json_age_hours(self, data_dir: Path | str | None = None) -> float | None:
        """Return age of status.json in hours, or None if file is missing/unreadable."""
        if data_dir is None:
            data_dir = self._file.parent  # assume data/ dir
        status_path = Path(data_dir) / "status.json"
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            # status.json has a "timestamp" or "generated_at" field
            ts = raw.get("timestamp") or raw.get("generated_at")
            if not ts:
                return None
            age = (_now() - _parse_iso(str(ts))).total_seconds() / 3600
            return round(age, 3)
        except Exception:
            return None

    def _reset_clock(self, state: dict, reason: str) -> None:
        """Reset stability clock and record failure in state (mutates state)."""
        now = _now_iso()
        state["stable_since"]            = now
        state["consecutive_stable_days"] = 0.0
        state["is_active"]               = True
        state["total_failures"]          = state.get("total_failures", 0) + 1
        if "failure_history" not in state:
            state["failure_history"] = []
        state["failure_history"].append({"time": now, "reason": reason})
        # Keep only the last 50 failure records
        state["failure_history"] = state["failure_history"][-50:]

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, data_dir: Path | str | None = None) -> dict[str, Any]:
        """Check status.json freshness and update the stability state.

        Should be called once per export cycle (e.g. every 4 hours).
        Idempotent within the same hour — calling twice won't double-count.

        Args:
            data_dir: Directory containing status.json.  Defaults to the same
                      directory as agent_stability.json.

        Returns:
            The current state dict after the update.
        """
        if data_dir is None:
            data_dir = self._file.parent

        state     = self._load()
        now_iso   = _now_iso()
        age_hours = self._status_json_age_hours(data_dir)

        if not state.get("is_active") or not state.get("stable_since"):
            # First ever call — start the clock
            state["stable_since"]            = now_iso
            state["consecutive_stable_days"] = 0.0
            state["is_active"]               = True
            if "failure_history" not in state:
                state["failure_history"] = []
            if "total_failures" not in state:
                state["total_failures"] = 0

        if age_hours is None:
            # status.json is missing or unreadable → reset
            self._reset_clock(state, "status.json missing or unreadable")
        elif age_hours > FRESHNESS_THRESHOLD_H:
            # status.json is stale → reset
            self._reset_clock(
                state,
                f"status.json stale: {age_hours:.1f}h > {FRESHNESS_THRESHOLD_H}h threshold",
            )
        else:
            # Healthy: update consecutive_stable_days from stable_since
            days = _elapsed_days(state["stable_since"])
            state["consecutive_stable_days"] = round(days, 4)

        state["last_check"] = now_iso
        self._save(state)
        return state

    def record_failure(self, reason: str, data_dir: Path | str | None = None) -> None:
        """Explicitly record a critical failure and reset the clock.

        Use this when an agent crashes or the pipeline detects an anomaly.
        """
        state = self._load()
        self._reset_clock(state, reason)
        state["last_check"] = _now_iso()
        self._save(state)

    def get_stable_days(self) -> float:
        """Return consecutive stable days from state (no freshness check)."""
        state = self._load()
        if not state.get("is_active") or not state.get("stable_since"):
            return 0.0
        return round(_elapsed_days(state["stable_since"]), 4)

    def check_criterion(self) -> dict[str, Any]:
        """Evaluate the go-live agent-stability criterion from persisted state.

        Returns:
            {
                "status":   "PASS" | "WARN" | "FAIL",
                "days":     <float>,
                "target":   28,
                "message":  "<human text>",
                "failures": <int>,
                "is_active": <bool>,
            }
        """
        state    = self._load()
        days     = self.get_stable_days()
        n_fails  = state.get("total_failures", 0)
        active   = bool(state.get("is_active", False))
        failures_suffix = f" ({n_fails} prior failure(s))" if n_fails else ""

        if not active:
            return {
                "status":    "FAIL",
                "days":      0.0,
                "target":    MIN_STABLE_DAYS,
                "message":   "Stability tracking not yet started — run export pipeline once",
                "failures":  n_fails,
                "is_active": False,
            }

        if days >= MIN_STABLE_DAYS:
            status  = "PASS"
            message = (
                f"{days:.1f} days of stable operation ≥ {MIN_STABLE_DAYS}-day minimum"
                + failures_suffix
            )
        elif days >= 14:
            status  = "WARN"
            message = (
                f"{days:.1f}/{MIN_STABLE_DAYS} days stable — "
                f"{MIN_STABLE_DAYS - days:.1f} days remaining"
                + failures_suffix
            )
        else:
            status  = "FAIL"
            message = (
                f"{days:.1f}/{MIN_STABLE_DAYS} days stable — "
                f"need {MIN_STABLE_DAYS - days:.1f} more days"
                + failures_suffix
            )

        return {
            "status":    status,
            "days":      round(days, 2),
            "target":    MIN_STABLE_DAYS,
            "message":   message,
            "failures":  n_fails,
            "is_active": active,
        }


# ── Standalone update entry point ─────────────────────────────────────────────

def update_agent_stability(data_dir: str | None = None) -> dict[str, Any]:
    """
    Convenience function: create tracker, run update, return state.
    Called from export_data.py on every export cycle.
    """
    dir_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    tracker  = AgentStabilityTracker(data_dir=dir_path)
    return tracker.update(data_dir=dir_path)
