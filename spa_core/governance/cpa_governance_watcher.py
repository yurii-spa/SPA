"""
spa_core/governance/cpa_governance_watcher.py

CPA-specific governance events for on-chain/off-chain tracking.
Extends existing governance_watcher.py with CPA gate events.

Events tracked:
  CPA_GATE_CHANGE: gate status changed (FAIL → PASS or PASS → FAIL)
  SOURCE_PROMOTED: source moved to CLEAN_INCLUDED
  OWNER_ACCEPTANCE: owner signed paper trading acceptance
  RESEARCH_SUSPENDED: research strategy suspended due to regime
  PAPER_STARTED: paper trading period officially began
  PAPER_EVIDENCE_MILESTONE: evidence_points crossed threshold (10, 20, 30)

Conventions:
  - stdlib only, no external dependencies
  - Atomic writes: mkstemp + os.replace
  - Ring-buffer cap=1000 events (oldest dropped when exceeded)
  - LLM FORBIDDEN in this module
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Constants ────────────────────────────────────────────────────────────────

CPA_EVENT_TYPES: List[str] = [
    "CPA_GATE_CHANGE",
    "SOURCE_PROMOTED",
    "OWNER_ACCEPTANCE",
    "RESEARCH_SUSPENDED",
    "PAPER_STARTED",
    "PAPER_EVIDENCE_MILESTONE",
]

RING_BUFFER_CAP = 1000
SCHEMA_VERSION = "1.0"

# Evidence milestones (points thresholds)
EVIDENCE_MILESTONES = [10, 20, 30]


# ─── Atomic IO helpers ────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Writes JSON atomically: tmpfile + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _read_json(path: Path, default: Any = None) -> Any:
    """Reads JSON safely; returns default on any error."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _utcnow() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ─── CPAEvent ─────────────────────────────────────────────────────────────────


class CPAEvent:
    """
    A single CPA governance event.

    Attributes:
        event_type  One of CPA_EVENT_TYPES
        details     Arbitrary metadata dict for the event
        timestamp   ISO-8601 UTC timestamp (auto-set if not provided)
    """

    def __init__(
        self,
        event_type: str,
        details: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> None:
        if event_type not in CPA_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type {event_type!r}. "
                f"Must be one of: {CPA_EVENT_TYPES}"
            )
        self.event_type = event_type
        self.details = dict(details)
        self.timestamp = timestamp if timestamp is not None else _utcnow()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CPAEvent":
        """Deserialise from a plain dict produced by to_dict()."""
        return cls(
            event_type=d["event_type"],
            details=dict(d.get("details", {})),
            timestamp=d.get("timestamp"),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CPAEvent):
            return NotImplemented
        return (
            self.event_type == other.event_type
            and self.details == other.details
            and self.timestamp == other.timestamp
        )

    def __repr__(self) -> str:
        return (
            f"CPAEvent(event_type={self.event_type!r}, "
            f"timestamp={self.timestamp!r}, details={self.details!r})"
        )


# ─── CPAGovernanceWatcher ─────────────────────────────────────────────────────


class CPAGovernanceWatcher:
    """
    Append-only log of CPA governance events with ring-buffer cap.

    Log file format (data/governance/cpa_events.json):
    {
      "schema_version": "1.0",
      "events": [ { event dicts... }, ... ]   ← newest last, cap=1000
    }
    """

    LOG_PATH = "data/governance/cpa_events.json"

    def __init__(self, base_dir: str = ".") -> None:
        self._base_dir = Path(base_dir)
        self._log_path = self._base_dir / self.LOG_PATH

    # ── Internal IO ───────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        """Load the event log; returns empty structure if missing/corrupt."""
        data = _read_json(self._log_path, default=None)
        if not isinstance(data, dict) or "events" not in data:
            return {"schema_version": SCHEMA_VERSION, "events": []}
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        """Atomically save the event log."""
        _atomic_write_json(self._log_path, data)

    # ── Core API ──────────────────────────────────────────────────────────────

    def emit(self, event: CPAEvent) -> None:
        """
        Appends event to log atomically.
        Ring-buffer: if len(events) > RING_BUFFER_CAP, oldest are dropped.
        """
        data = self._load()
        events: List[Dict[str, Any]] = data.get("events", [])
        events.append(event.to_dict())
        # Apply ring-buffer cap
        if len(events) > RING_BUFFER_CAP:
            events = events[-RING_BUFFER_CAP:]
        data["events"] = events
        data["schema_version"] = SCHEMA_VERSION
        self._save(data)

    def recent_events(self, n: int = 20) -> List[Dict[str, Any]]:
        """Returns last N events from log (newest last)."""
        data = self._load()
        events = data.get("events", [])
        return events[-n:] if n < len(events) else list(events)

    def events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """Filter events by type; returns list in chronological order."""
        data = self._load()
        return [e for e in data.get("events", []) if e.get("event_type") == event_type]

    def all_events(self) -> List[Dict[str, Any]]:
        """Returns all events in chronological order."""
        data = self._load()
        return list(data.get("events", []))

    def summary(self) -> Dict[str, Any]:
        """
        Returns event summary:
        {
          "total_events": int,
          "by_type": {event_type: count},
          "latest": dict | None,
          "owner_has_signed": bool,
          "paper_has_started": bool,
          "sources_promoted_count": int
        }
        """
        data = self._load()
        events = data.get("events", [])

        by_type: Dict[str, int] = {et: 0 for et in CPA_EVENT_TYPES}
        owner_has_signed = False
        paper_has_started = False
        sources_promoted_count = 0

        for e in events:
            et = e.get("event_type", "")
            if et in by_type:
                by_type[et] += 1
            if et == "OWNER_ACCEPTANCE":
                owner_has_signed = True
            if et == "PAPER_STARTED":
                paper_has_started = True
            if et == "SOURCE_PROMOTED":
                sources_promoted_count += 1

        return {
            "total_events": len(events),
            "by_type": by_type,
            "latest": events[-1] if events else None,
            "owner_has_signed": owner_has_signed,
            "paper_has_started": paper_has_started,
            "sources_promoted_count": sources_promoted_count,
        }

    # ── Factory methods ───────────────────────────────────────────────────────

    def gate_change_event(
        self,
        gate_name: str,
        old_status: str,
        new_status: str,
    ) -> CPAEvent:
        """Factory for CPA_GATE_CHANGE events."""
        return CPAEvent(
            event_type="CPA_GATE_CHANGE",
            details={
                "gate_name": gate_name,
                "old_status": old_status,
                "new_status": new_status,
            },
        )

    def source_promoted_event(
        self,
        source_id: str,
        to_state: str,
    ) -> CPAEvent:
        """Factory for SOURCE_PROMOTED events."""
        return CPAEvent(
            event_type="SOURCE_PROMOTED",
            details={
                "source_id": source_id,
                "to_state": to_state,
            },
        )

    def owner_acceptance_event(self, owner: str) -> CPAEvent:
        """Factory for OWNER_ACCEPTANCE events."""
        return CPAEvent(
            event_type="OWNER_ACCEPTANCE",
            details={
                "owner": owner,
            },
        )

    def research_suspended_event(
        self,
        strategy_id: str,
        reason: str,
        regime: str = "unknown",
    ) -> CPAEvent:
        """Factory for RESEARCH_SUSPENDED events."""
        return CPAEvent(
            event_type="RESEARCH_SUSPENDED",
            details={
                "strategy_id": strategy_id,
                "reason": reason,
                "regime": regime,
            },
        )

    def paper_started_event(self, start_date: str, owner: str = "") -> CPAEvent:
        """Factory for PAPER_STARTED events."""
        return CPAEvent(
            event_type="PAPER_STARTED",
            details={
                "start_date": start_date,
                "owner": owner,
            },
        )

    def evidence_milestone_event(
        self,
        points: float,
        milestone: int,
    ) -> CPAEvent:
        """Factory for PAPER_EVIDENCE_MILESTONE events."""
        return CPAEvent(
            event_type="PAPER_EVIDENCE_MILESTONE",
            details={
                "evidence_points": points,
                "milestone": milestone,
            },
        )


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    watcher = CPAGovernanceWatcher()
    summary = watcher.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
