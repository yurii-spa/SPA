"""
spa_core/alerts/alert_aggregator.py — MP-1494 (Sprint v11.10)

Alert aggregator: deduplicates, throttles, and routes alerts by severity.
Prevents alert fatigue by collapsing repeated alerts within throttle windows.

Pure stdlib. Offline-safe. Atomic writes. LLM FORBIDDEN.
"""
from __future__ import annotations

import datetime
import logging
from typing import Dict

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.utils import clock

log = logging.getLogger("spa.alerts.aggregator")

OUTPUT_PATH = "data/alert_aggregator.json"

# Throttle windows per severity (minutes). 0 = always send immediately.
THROTTLE_MINUTES: Dict[str, int] = {
    "CRITICAL": 0,    # Always send immediately
    "HIGH":     60,   # Once per hour
    "MEDIUM":   240,  # Once per 4 hours
    "LOW":      1440, # Once per day
}


class AlertAggregator(BaseAnalytics):
    """Deduplicates and throttles alert delivery.

    Usage::
        agg = AlertAggregator(base_dir="/path/to/repo")
        sent = agg.submit({"type": "apy_drift", "strategy": "S0", "severity": "HIGH"})
        # True on first call, False within 60 min (HIGH throttle)
    """

    OUTPUT_PATH = OUTPUT_PATH

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._base_dir_path = base_dir
        self._data: Dict = {
            "sent":              {},    # dedup_key → ISO timestamp of last send
            "pending":           [],
            "suppressed_count":  0,
            "total_sent":        0,
        }
        # Load persisted state on construction
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, alert: Dict) -> bool:
        """Submit alert for delivery.

        Returns True if the alert was not throttled (caller should send it).
        Returns False if the alert was suppressed by throttle/dedup logic.
        Saves state atomically on every call.
        """
        key = self._dedup_key(alert)
        severity = alert.get("severity", "MEDIUM")

        if self._is_throttled(key, severity):
            self._data["suppressed_count"] = self._data.get("suppressed_count", 0) + 1
            log.debug("Alert suppressed (throttled): %s [%s]", key, severity)
            self._save_state()
            return False

        # Not throttled — record and approve
        self._record_sent(key)
        self._data["total_sent"] = self._data.get("total_sent", 0) + 1
        self._save_state()
        log.info("Alert approved: %s [%s]", key, severity)
        return True

    def get_stats(self) -> Dict:
        """Return aggregator statistics."""
        return {
            "suppressed_count": self._data.get("suppressed_count", 0),
            "total_sent":       self._data.get("total_sent", 0),
            "tracked_keys":     len(self._data.get("sent", {})),
        }

    def clear_history(self) -> None:
        """Reset sent history (useful for testing or manual reset)."""
        self._data["sent"] = {}
        self._data["suppressed_count"] = 0
        self._data["total_sent"] = 0
        self._save_state()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dedup_key(self, alert: Dict) -> str:
        """Create deduplication key from alert type + subject + severity."""
        alert_type = alert.get("type", "alert")
        strategy = alert.get("strategy", alert.get("subject", "system"))
        severity = alert.get("severity", "MEDIUM")
        return f"{alert_type}:{strategy}:{severity}"

    def _is_throttled(self, key: str, severity: str) -> bool:
        """Return True if this key is still within its throttle window."""
        last_sent_iso = self._data.get("sent", {}).get(key)
        if not last_sent_iso:
            return False  # Never sent → not throttled

        throttle_mins = THROTTLE_MINUTES.get(severity, 240)
        if throttle_mins == 0:
            return False  # CRITICAL: always send

        try:
            last_sent = datetime.datetime.fromisoformat(last_sent_iso)
        except (ValueError, TypeError):
            return False  # Corrupted timestamp → not throttled

        elapsed_mins = (
            clock.utcnow() - last_sent
        ).total_seconds() / 60.0

        return elapsed_mins < throttle_mins

    def _record_sent(self, key: str) -> None:
        """Record that an alert with this key was just sent."""
        if "sent" not in self._data:
            self._data["sent"] = {}
        self._data["sent"][key] = clock.utcnow().isoformat()

    def _load_state(self) -> None:
        """Load persisted aggregator state from disk (if present)."""
        path = self._path(OUTPUT_PATH)
        persisted = atomic_load(path, default=None)
        if isinstance(persisted, dict):
            # Merge persisted sent history into self._data
            self._data["sent"] = persisted.get("sent", {})
            self._data["suppressed_count"] = persisted.get("suppressed_count", 0)
            self._data["total_sent"] = persisted.get("total_sent", 0)

    def _save_state(self) -> None:
        """Persist aggregator state atomically."""
        atomic_save(self._data, self._path(OUTPUT_PATH))

    # ------------------------------------------------------------------
    # BaseAnalytics required
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict:
        return self._data

    def save(self, data=None, path=None) -> str:  # type: ignore[override]
        """Override to use _save_state (already uses atomic_save)."""
        self._save_state()
        return self._path(OUTPUT_PATH)
