"""
Tracks continuous agent stability for go-live criteria.

Go-live requires MIN_STABLE_DAYS=28 of uninterrupted stable operation.
Clock starts when start_tracking() is called for the first time (idempotent).
Resets if a critical failure is recorded.

State is persisted in data/stability_tracking.json relative to the repo root.

Usage:
    from spa_core.paper_trading.stability_tracker import StabilityTracker

    tracker = StabilityTracker()
    tracker.start_tracking()           # idempotent — call on every export run
    result = tracker.check_criterion() # {'status': 'FAIL'|'WARN'|'PASS', 'days': ..., ...}
    tracker.record_failure("reason")   # resets clock, appends to critical_failures
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Minimum consecutive stable days required for go-live
MIN_STABLE_DAYS: int = 28

# Default path for state file — data/ at repo root
_DEFAULT_STATE_FILE = Path(__file__).parent.parent.parent / "data" / "stability_tracking.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    """Parse ISO-8601 string to timezone-aware datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class StabilityTracker:
    """Persistent stability clock for the go-live agent-stability criterion.

    State schema (data/stability_tracking.json):
    {
        "start_time":        "<ISO-8601>",     # when clock started / last reset
        "last_check":        "<ISO-8601>",     # last time start_tracking() was called
        "critical_failures": [                 # list of recorded failures
            {"time": "<ISO-8601>", "reason": "<str>"}
        ],
        "is_active":         true              # false → not yet started
    }
    """

    def __init__(self, state_file: Path | str | None = None) -> None:
        self._file: Path = (
            Path(state_file) if state_file else _DEFAULT_STATE_FILE
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        """Load state from JSON file; return empty default if missing."""
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "start_time":        None,
                "last_check":        None,
                "critical_failures": [],
                "is_active":         False,
            }

    def _save(self, state: dict[str, Any]) -> None:
        """Persist state to JSON file; creates parent dirs as needed."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Public API ₔ�───────────────────────────────────────────────────────────

    def start_tracking(self) -> bool:
        """Start the stability clock if not already started.

        Idempotent: calling multiple times has no effect once the clock is
        running. Updates last_check on every call to confirm liveness.

        Returns:
            True  — clock was just started for the first time.
            False — clock was already running (nuo`change to start_time).
        """
        state = self._load()
        now   = _now_iso()
        just_started = False

        if not state.get("is_active") or not state.get("start_time"):
            state["start_time"] = now
            state["is_active"]  = True
            just_started        = True

        state["last_check"] = now
        self._save(state)
        return just_started

    def record_failure(self, reason: str, reset_clock: bool = True) -> None:
        """Record a critical failure event.

        Appends to critical_failures list. If reset_clock=True (default),
        resets start_time to now so the 28-day counter restarts.

        Args:
            reason:      Human-readable description of the failure.
            reset_clock: Whether to restart the stability clock (default: True).
        """
        state = self._load()
        now   = _now_iso()

        failure = {"time": now, "reason": reason}
        if "critical_failures" not in state:
            state["critical_failures"] = []
        state["critical_failures"].append(failure)

        if reset_clock:
            state["start_time"] = now
            state["is_active"]  = True

        state["last_check"] = now
        self._save(state)

    def get_stable_days(self) -> float:
        """Return elapsed stable days since start_time (or last reset).

        Returns 0.0 if tracking has not been started yet.
        """
        state = self._load()
        if not state.get("is_active") or not state.get("start_time"):
            return 0.0

        try:
            start  = _parse_iso(state["start_time"])
            elapsed = datetime.now(timezone.utc) - start
            return elapsed.total_seconds() / 86_400
        except Exception:
            return 0.0

    def check_criterion(self) -> dict[str, Any]:
        """Evaluate the agent-stability go-live criterion.

        Returns:
            {
                "status":  "PASS" | "WARN" | "FAIL",
                "days":    <float>,          # days of continuous stable operation
                "target":  28,               # MIN_STABLE_DAYS
                "message": "<human text>",
                "failures": <int>,           # total critical failures recorded
                "is_active": <bool>,
            }

        Thresholds:
            PASS  — days >= 28
            WARN  — 14 <= days < 28
            FAIL  — days < 14
        """
        days    = self.get_stable_days()
        state   = self._load()
        n_fails = len(state.get("critical_failures", []))
        active  = bool(state.get("is_active", False))

        if days >= MIN_STABLE_DAYS:
            status  = "PASS"
            message = (
                f"{days:.1f} days of stable operation ≥ {MIN_STABLE_DAYS}-day minimum"
                + (f" ({n_fails} failure(s) before current run)" if n_fails else "")
            )
        elif days >= 14:
            status  = "WARN"
            message = (
                f"{days:.1f}/{MIN_STABLE_DAYS} days stable — "
                f"{MIN_STABLE_DAYS - days:.1f} days remaining"
            )
        else:
            if not active:
                status  = "FAIL"
                message = "Stability tracking not yet started — call start_tracking()"
            else:
                status  = "FAIL"
                message = (
                    f"{days:.1f}/{MIN_STABLE_DAYS} days stable — "
                    f"need {MIN_STABLE_DAYS - days:.1f} more days"
                )

        return {
            "status":   status,
            "days":     round(days, 2),
            "target":   MIN_STABLE_DAYS,
            "message":  message,
            "failures": n_fails,
            "is_active": active,
        }
