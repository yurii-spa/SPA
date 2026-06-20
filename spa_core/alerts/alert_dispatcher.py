"""
alert_dispatcher.py — SPA-V513 centralized alert dispatcher.

Responsibilities:
  * AlertLevel enum: INFO, WARNING, CRITICAL, EMERGENCY
  * Alert dataclass: level, title, message, adapter_id (optional),
    timestamp (ISO-8601 UTC), correlation_id (uuid4)
  * AlertDispatcher:
    - dispatch(alert)             → dict {channels_attempted, channels_succeeded, alert_id}
    - dispatch_to_telegram(alert) → bool (uses TELEGRAM_BOT_TOKEN_SPA + TELEGRAM_CHAT_ID_SPA)
    - dispatch_to_log(alert)      → bool (always True; ring-buffer 1000 → data/alert_log.json)
    - create_alert(level, title, message, adapter_id=None) → Alert
    - get_recent_alerts(n=50)     → list[Alert]
    - suppress_duplicates option: skip same title within cooldown_seconds (default 300)

Atomic writes: tmp-file + os.replace. stdlib only. Never raises on network failure.

LLM_FORBIDDEN — must NOT be imported from risk/, execution/, or monitoring/ domains.

NOTE: The legacy dispatch_alerts() function and Alert/AlertConfig imports from
V390 (SMTP-based) are preserved below for backwards compatibility.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import smtplib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import urllib.request
import urllib.error
from email.message import EmailMessage
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.alerts.dispatcher")

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = _PROJECT_ROOT / "data" / "alert_log.json"
# BUG FIX (TELEGRAM_AUDIT 2026-06-18): persist dedup state across process
# restarts.  Monitors (peg_monitor, etc.) run every 5 min via launchd — each
# run is a NEW process so the old in-memory _title_last_sent dict was always
# empty, making the 300-second cooldown completely ineffective.
DEFAULT_DEDUP_STATE_PATH = _PROJECT_ROOT / "data" / "alert_dispatcher_dedup.json"
RING_BUFFER_MAX = 1000  # new dispatcher uses 1000; legacy used 100

# Telegram API base
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


# ===========================================================================
# AlertLevel
# ===========================================================================
class AlertLevel(enum.Enum):
    """Severity levels ordered from lowest (INFO=1) to highest (EMERGENCY=4)."""
    INFO = 1
    WARNING = 2
    CRITICAL = 3
    EMERGENCY = 4

    def __lt__(self, other: "AlertLevel") -> bool:
        if not isinstance(other, AlertLevel):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: "AlertLevel") -> bool:
        if not isinstance(other, AlertLevel):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: "AlertLevel") -> bool:
        if not isinstance(other, AlertLevel):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: "AlertLevel") -> bool:
        if not isinstance(other, AlertLevel):
            return NotImplemented
        return self.value >= other.value


# ===========================================================================
# Alert dataclass
# ===========================================================================
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utc_timestamp() -> float:
    """Current UTC time as POSIX float seconds."""
    return datetime.now(timezone.utc).timestamp()


@dataclass
class Alert:
    """Immutable alert record produced by AlertDispatcher.create_alert()."""
    level: AlertLevel
    title: str
    message: str
    adapter_id: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    correlation_id: str = field(default_factory=_new_uuid)

    def to_dict(self) -> dict:
        return {
            "level": self.level.name,
            "title": self.title,
            "message": self.message,
            "adapter_id": self.adapter_id,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        level_name = d.get("level", "INFO")
        try:
            level = AlertLevel[level_name]
        except KeyError:
            level = AlertLevel.INFO
        return cls(
            level=level,
            title=str(d.get("title", "")),
            message=str(d.get("message", "")),
            adapter_id=d.get("adapter_id") or None,
            timestamp=d.get("timestamp", _now_iso()),
            correlation_id=d.get("correlation_id", _new_uuid()),
        )


# ===========================================================================
# Internal I/O helpers
# ===========================================================================
def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(payload, str(path))
def _load_log_entries(path: Path) -> List[dict]:
    """Load ring-buffer entries from disk; tolerant of corruption."""
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            entries = data.get("entries", [])
        elif isinstance(data, list):
            entries = data
        else:
            entries = []
        return [e for e in entries if isinstance(e, dict)]
    except (OSError, ValueError, TypeError):
        return []


# ===========================================================================
# Telegram formatting helpers
# ===========================================================================
_LEVEL_EMOJI: Dict[str, str] = {
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "CRITICAL": "🔴",
    "EMERGENCY": "🚨",
}


def _html_escape(text: str) -> str:
    """Minimal HTML escaping for Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_telegram_message(alert: Alert) -> str:
    """Format an Alert as an HTML Telegram message string."""
    emoji = _LEVEL_EMOJI.get(alert.level.name, "📢")
    parts = [
        f"{emoji} <b>[{alert.level.name}] {_html_escape(alert.title)}</b>",
        "",
        _html_escape(alert.message),
    ]
    if alert.adapter_id:
        parts.append(
            f"\n🔌 Adapter: <code>{_html_escape(alert.adapter_id)}</code>"
        )
    parts.append(f"\n🕐 {alert.timestamp}")
    parts.append(f"🆔 <code>{alert.correlation_id}</code>")
    return "\n".join(parts)


# ===========================================================================
# AlertDispatcher
# ===========================================================================
class AlertDispatcher:
    """
    Centralized alert dispatcher supporting multiple delivery channels.

    Channels
    --------
    log      : Always active. Persists to data/alert_log.json (ring-buffer 1000).
    telegram : Active when TELEGRAM_BOT_TOKEN_SPA and TELEGRAM_CHAT_ID_SPA are set.

    Parameters
    ----------
    log_path : Path | str | None
        JSON file for the persistent ring buffer. Defaults to
        ``<project_root>/data/alert_log.json``.
    suppress_duplicates : bool
        When True, alerts with the same title within ``cooldown_seconds`` are
        silently skipped on all channels.
    cooldown_seconds : int
        Deduplication window in seconds (default 300 = 5 minutes).
    """

    def __init__(
        self,
        log_path: Optional[str | Path] = None,
        suppress_duplicates: bool = False,
        cooldown_seconds: int = 300,
        dedup_state_path: Optional[str | Path] = None,
    ) -> None:
        self._log_path: Path = (
            Path(log_path) if log_path else DEFAULT_LOG_PATH
        )
        self.suppress_duplicates: bool = suppress_duplicates
        self.cooldown_seconds: int = cooldown_seconds

        # BUG FIX (TELEGRAM_AUDIT 2026-06-18): persist dedup state to disk so
        # it survives process restarts (launchd starts a new process every 5 min).
        self._dedup_state_path: Path = (
            Path(dedup_state_path) if dedup_state_path
            else DEFAULT_DEDUP_STATE_PATH
        )

        # title → UTC POSIX timestamp of last successful dispatch
        # Loaded from disk on first use; written back after each send.
        self._title_last_sent: Dict[str, float] = self._load_dedup_state()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        adapter_id: Optional[str] = None,
    ) -> Alert:
        """
        Create and return a new Alert. Does NOT dispatch it.

        Parameters
        ----------
        level      : AlertLevel
        title      : short human-readable title
        message    : detailed description
        adapter_id : optional adapter identifier (e.g. "aave_v3")
        """
        return Alert(
            level=level,
            title=title,
            message=message,
            adapter_id=adapter_id,
        )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------
    def _is_suppressed(self, alert: Alert) -> bool:
        """Return True if alert title is within the dedup cooldown window."""
        if not self.suppress_duplicates:
            return False
        last_ts = self._title_last_sent.get(alert.title)
        if last_ts is None:
            return False
        return (_utc_timestamp() - last_ts) < self.cooldown_seconds

    def _record_sent(self, alert: Alert) -> None:
        """Record this alert title as dispatched at the current time."""
        self._title_last_sent[alert.title] = _utc_timestamp()
        # Persist to disk so the next process (5-min launchd restart) sees it.
        self._save_dedup_state()

    # ------------------------------------------------------------------
    # Dedup state persistence (disk)
    # ------------------------------------------------------------------
    def _load_dedup_state(self) -> Dict[str, float]:
        """Load title→timestamp map from disk. Returns {} on any error."""
        try:
            if self._dedup_state_path.exists():
                raw = json.loads(
                    self._dedup_state_path.read_text(encoding="utf-8")
                )
                if isinstance(raw, dict):
                    return {k: float(v) for k, v in raw.items()
                            if isinstance(v, (int, float))}
        except Exception as exc:
            log.warning(
                "alert_dispatcher_dedup.json unreadable (%s) — "
                "starting with empty dedup state", exc
            )
        return {}

    def _save_dedup_state(self) -> None:
        """Atomically write title→timestamp map to disk. Silent on failure."""
        try:
            _atomic_write_json(self._dedup_state_path, self._title_last_sent)
        except Exception as exc:
            log.warning(
                "alert_dispatcher_dedup.json write failed (%s) — "
                "dedup state not persisted", exc
            )

    # ------------------------------------------------------------------
    # Channel: log
    # ------------------------------------------------------------------
    def dispatch_to_log(self, alert: Alert) -> bool:
        """
        Append alert to the persistent JSON ring buffer.

        Always returns True (contract). Never raises — catches all exceptions
        internally and logs them.
        """
        try:
            entry = alert.to_dict()
            entry["logged_at"] = _now_iso()

            existing = _load_log_entries(self._log_path)
            combined = existing + [entry]
            if len(combined) > RING_BUFFER_MAX:
                combined = combined[-RING_BUFFER_MAX:]

            payload = {
                "schema_version": 2,
                "source": "alert_dispatcher",
                "updated_at": _now_iso(),
                "count": len(combined),
                "max_entries": RING_BUFFER_MAX,
                "entries": combined,
            }
            _atomic_write_json(self._log_path, payload)
            log.debug(
                "alert logged [%s] %s (id=%s)",
                alert.level.name,
                alert.title,
                alert.correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("dispatch_to_log error (alert still returns True): %s", exc)
        return True  # contract: always True

    # ------------------------------------------------------------------
    # Channel: Telegram
    # ------------------------------------------------------------------
    def dispatch_to_telegram(self, alert: Alert) -> bool:
        """
        Send alert via Telegram Bot API.

        Reads env vars:
          TELEGRAM_BOT_TOKEN_SPA — bot token
          TELEGRAM_CHAT_ID_SPA   — target chat / channel ID

        Returns False and logs if credentials are absent or the send fails.
        Never raises.
        """
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID_SPA", "").strip()

        if not token or not chat_id:
            log.debug(
                "Telegram not configured "
                "(TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA missing)"
            )
            return False

        text = _format_telegram_message(alert)
        url = _TELEGRAM_API_BASE.format(token=token)
        payload_bytes = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = resp.status == 200
                if ok:
                    log.info(
                        "Telegram alert sent [%s] %s",
                        alert.level.name,
                        alert.title,
                    )
                else:
                    log.warning(
                        "Telegram unexpected status=%d alert_id=%s",
                        resp.status,
                        alert.correlation_id,
                    )
                return ok
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            log.error("Telegram HTTPError %d: %s", exc.code, body)
            return False
        except urllib.error.URLError as exc:
            log.error("Telegram URLError: %s", exc.reason)
            return False
        except Exception as exc:  # noqa: BLE001
            log.error("Telegram unexpected error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------
    def dispatch(self, alert: Alert) -> dict:
        """
        Dispatch alert to all available channels.

        Returns
        -------
        dict
            alert_id           : correlation_id of the alert
            channels_attempted : list of channel names tried
            channels_succeeded : list of channel names that succeeded
            suppressed         : True when deduplication silenced the alert
        """
        if self._is_suppressed(alert):
            log.debug(
                "Alert suppressed (dup within %ds): %s",
                self.cooldown_seconds,
                alert.title,
            )
            return {
                "alert_id": alert.correlation_id,
                "channels_attempted": [],
                "channels_succeeded": [],
                "suppressed": True,
            }

        channels_attempted: List[str] = []
        channels_succeeded: List[str] = []

        # log channel — always attempted
        channels_attempted.append("log")
        if self.dispatch_to_log(alert):
            channels_succeeded.append("log")

        # telegram channel — attempted only when credentials present
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID_SPA", "").strip()
        if token and chat_id:
            channels_attempted.append("telegram")
            if self.dispatch_to_telegram(alert):
                channels_succeeded.append("telegram")

        self._record_sent(alert)

        return {
            "alert_id": alert.correlation_id,
            "channels_attempted": channels_attempted,
            "channels_succeeded": channels_succeeded,
            "suppressed": False,
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def get_recent_alerts(self, n: int = 50) -> List[Alert]:
        """
        Return the most recent *n* alerts from the persistent log.
        Returned in newest-first order.
        """
        entries = _load_log_entries(self._log_path)
        # take last n from the ring buffer (newest at end), then reverse
        recent = entries[-n:] if len(entries) > n else entries[:]
        recent.reverse()
        result: List[Alert] = []
        for e in recent:
            try:
                result.append(Alert.from_dict(e))
            except Exception:  # noqa: BLE001
                pass
        return result


# ===========================================================================
# Legacy V390 compatibility (SMTP-based dispatch_alerts)
# Keep for backwards compatibility — do NOT remove without a migration ADR.
# ===========================================================================
# We re-import the legacy Alert from alert_rules only for the legacy function.
# The new Alert class above is self-contained and does NOT depend on alert_rules.
try:
    from .alert_config import AlertConfig, SEVERITY_RANK
    from .alert_rules import Alert as _LegacyAlert

    _LEGACY_RING_BUFFER_MAX = 100

    def _load_log(path: Path) -> List[dict]:
        try:
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                return data["entries"]
            if isinstance(data, list):
                return data
            return []
        except (OSError, ValueError):
            return []

    def _append_ring_buffer(
        log_path: Path, new_entries: List[dict], sent_via: str
    ) -> List[dict]:
        existing = _load_log(log_path)
        stamped = []
        for entry in new_entries:
            rec = dict(entry)
            rec.setdefault("logged_at", _now_iso())
            rec["sent_via"] = sent_via
            stamped.append(rec)
        combined = existing + stamped
        if len(combined) > _LEGACY_RING_BUFFER_MAX:
            combined = combined[-_LEGACY_RING_BUFFER_MAX:]
        payload = {
            "schema_version": 1,
            "source": "alert_dispatcher",
            "updated_at": _now_iso(),
            "count": len(combined),
            "max_entries": _LEGACY_RING_BUFFER_MAX,
            "entries": combined,
        }
        _atomic_write_json(log_path, payload)
        return combined

    def _format_email_body(alerts: List[_LegacyAlert]) -> str:
        lines = ["SPA Alert digest", "=" * 40, ""]
        for a in alerts:
            lines.append(f"[{a.severity}] {a.title}")
            lines.append(f"    {a.body}")
            lines.append(f"    at {a.timestamp}")
            lines.append("")
        return "\n".join(lines)

    def _send_email(alerts: List[_LegacyAlert], config: "AlertConfig") -> dict:
        msg = EmailMessage()
        severities = {a.severity for a in alerts}
        top = max(alerts, key=lambda a: SEVERITY_RANK.get(a.severity, 0))
        subject = f"[SPA {top.severity}] {len(alerts)} alert(s): {top.title}"
        msg["Subject"] = subject[:200]
        msg["From"] = config.smtp_user
        msg["To"] = ", ".join(config.email_to)
        msg.set_content(_format_email_body(alerts))
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as server:
            server.login(config.smtp_user, config.smtp_pass)
            server.send_message(msg)
        return {
            "sent": True,
            "recipients": list(config.email_to),
            "subject": subject[:200],
            "severities": sorted(severities),
        }

    def dispatch_alerts(
        alerts: List[_LegacyAlert],
        config: "AlertConfig",
        log_path=None,
    ) -> dict:
        """
        Legacy V390 SMTP-based alert dispatch. Preserved for backwards compat.
        Persist alerts to ring buffer (100 entries) and optionally send via SMTP.
        """
        path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        for a in alerts:
            if a.severity in counts:
                counts[a.severity] += 1
        mailable = [a for a in alerts if config.should_email(a.severity)]
        will_send = (
            bool(mailable) and not config.dry_run and config.smtp_configured
        )
        send_result: dict = {"sent": False}
        sent_via = "dry_run"
        error = None
        if will_send:
            try:
                send_result = _send_email(mailable, config)
                sent_via = "smtp"
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                send_result = {"sent": False, "error": error}
                sent_via = "smtp_failed"
        entries = [a.to_dict() for a in alerts]
        if entries:
            _append_ring_buffer(path, entries, sent_via=sent_via)
        return {
            "ok": error is None,
            "dry_run": config.dry_run or not config.smtp_configured,
            "total": len(alerts),
            "counts": counts,
            "mailable": len(mailable),
            "sent": send_result.get("sent", False),
            "sent_via": sent_via,
            "log_path": str(path),
            "error": error,
            "send_result": send_result,
        }

except ImportError:
    # alert_config / alert_rules may not exist in isolated test environments.
    pass
