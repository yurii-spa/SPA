"""
spa_core/analytics/decision_audit_trail.py
Append-only JSONL decision audit trail for SPA.

Each system decision (APY fetch, allocation, gate check, alert) is logged as a
JSON line with a correlation_id that ties the full decision chain for one cycle.

Storage: data/decision_audit.jsonl (append-only, 10 MB rotation).
"""
import json
import os
import uuid
import datetime
from typing import List, Optional

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


class DecisionAuditTrail:
    """Append-only audit trail for all SPA decisions (JSONL)."""

    ENTRY_TYPES = frozenset({
        "gate_check",
        "adapter_fetch",
        "allocation",
        "alert",
        "evidence_record",
    })

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self._path = os.path.join(base_dir, "data", "decision_audit.jsonl")

    # ── write ────────────────────────────────────────────────────────────────

    def log(
        self,
        entry_type: str,
        description: str,
        correlation_id: Optional[str] = None,
        outcome: str = "OK",
        **details,
    ) -> str:
        """
        Appends a decision entry to the JSONL file.

        Returns the correlation_id (auto-generated if not supplied).
        """
        if entry_type not in self.ENTRY_TYPES:
            entry_type = "unknown"

        cid = correlation_id or str(uuid.uuid4())[:8]
        entry = {
            "id": str(uuid.uuid4()),
            "correlation_id": cid,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": entry_type,
            "description": description,
            "outcome": outcome,
        }
        if details:
            entry.update(details)

        self._ensure_dir()
        self._rotate_if_needed()

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return cid

    # ── read ─────────────────────────────────────────────────────────────────

    def read_entries(self, limit: int = 100) -> List[dict]:
        """Returns up to `limit` most-recent entries (newest last)."""
        if not os.path.exists(self._path):
            return []
        entries = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]

    def get_by_correlation_id(self, cid: str) -> List[dict]:
        """Returns all entries matching a given correlation_id."""
        return [e for e in self.read_entries(limit=10_000) if e.get("correlation_id") == cid]

    def count(self) -> int:
        """Returns total number of entries in the current file."""
        if not os.path.exists(self._path):
            return 0
        n = 0
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n

    # ── internal ─────────────────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Rotates the JSONL file if it exceeds MAX_FILE_BYTES."""
        if not os.path.exists(self._path):
            return
        if os.path.getsize(self._path) < MAX_FILE_BYTES:
            return
        # Rotate: rename current → .1 (keep one backup)
        backup = self._path + ".1"
        if os.path.exists(backup):
            os.unlink(backup)
        os.rename(self._path, backup)
