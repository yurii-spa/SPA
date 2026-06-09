"""
alert_dispatcher.py — SPA-V390 alert delivery + persistent ring buffer.

Responsibilities:
  * Persist every alert to data/alert_log.json as a bounded ring buffer (100).
  * In dry-run mode: log only (no network).
  * With SMTP configured: send via smtplib.SMTP_SSL.

Atomic writes only (tmp file + os.replace). stdlib only.
"""

from __future__ import annotations

import json
import os
import smtplib
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import List

from .alert_config import AlertConfig, SEVERITY_RANK
from .alert_rules import Alert

RING_BUFFER_MAX = 100

# data/ dir relative to project root (spa_core/alerts/ → up two levels).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = _PROJECT_ROOT / "data" / "alert_log.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload) -> None:
    """Write JSON atomically: temp file in same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


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
    """Append new entries, keep only the most recent RING_BUFFER_MAX."""
    existing = _load_log(log_path)
    stamped = []
    for entry in new_entries:
        rec = dict(entry)
        rec.setdefault("logged_at", _now_iso())
        rec["sent_via"] = sent_via
        stamped.append(rec)
    combined = existing + stamped
    if len(combined) > RING_BUFFER_MAX:
        combined = combined[-RING_BUFFER_MAX:]
    payload = {
        "schema_version": 1,
        "source": "alert_dispatcher",
        "updated_at": _now_iso(),
        "count": len(combined),
        "max_entries": RING_BUFFER_MAX,
        "entries": combined,
    }
    _atomic_write_json(log_path, payload)
    return combined


def _format_email_body(alerts: List[Alert]) -> str:
    lines = ["SPA Alert digest", "=" * 40, ""]
    for a in alerts:
        lines.append(f"[{a.severity}] {a.title}")
        lines.append(f"    {a.body}")
        lines.append(f"    at {a.timestamp}")
        lines.append("")
    return "\n".join(lines)


def _send_email(alerts: List[Alert], config: AlertConfig) -> dict:
    """Send a single digest email via SMTP_SSL. Returns a result dict."""
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
    alerts: List[Alert],
    config: AlertConfig,
    log_path=None,
) -> dict:
    """
    Persist alerts to the ring buffer and, when SMTP is configured and not in
    dry-run, email the alerts that meet the minimum email severity.

    Returns a summary dict. Never raises on SMTP failure — failures are
    captured in the returned dict and the alerts are still logged.
    """
    path = Path(log_path) if log_path else DEFAULT_LOG_PATH

    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for a in alerts:
        if a.severity in counts:
            counts[a.severity] += 1

    # Decide whether we actually email.
    mailable = [a for a in alerts if config.should_email(a.severity)]
    will_send = (
        bool(mailable)
        and not config.dry_run
        and config.smtp_configured
    )

    send_result: dict = {"sent": False}
    sent_via = "dry_run"
    error = None

    if will_send:
        try:
            send_result = _send_email(mailable, config)
            sent_via = "smtp"
        except Exception as exc:  # noqa: BLE001 — never let SMTP crash logging
            error = f"{type(exc).__name__}: {exc}"
            send_result = {"sent": False, "error": error}
            sent_via = "smtp_failed"

    # Always persist to ring buffer (even when there are zero alerts we still
    # leave the log untouched if nothing to add).
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
