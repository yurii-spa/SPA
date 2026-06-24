"""
ADR-029: Telegram notifications for strategy promotion decisions.

Reads credentials at runtime from macOS Keychain:
  - TELEGRAM_BOT_TOKEN_SPA  (service name, account "spa")
  - TELEGRAM_CHAT_ID_SPA    (service name, account "spa")

Falls back to env vars of the same name if Keychain is unavailable.

Stdlib only.  No LLM SDK.  No tokens in this file.
All public methods are fail-safe: return bool, never raise.

Tier routing (ADR-029):
  Tier A → AUTO_PROMOTE  (emits ⚡ alert immediately)
  Tier B → PENDING_48H   (emits 🕐 alert; human can CANCEL within 48 h)
  Tier C → MANUAL_REVIEW (emits 🔴 alert; requires USER_APPROVAL)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger("spa.reporting.promotion_notifier")

_KEYCHAIN_ACCOUNT = "spa"
_TOKEN_SERVICE    = "TELEGRAM_BOT_TOKEN_SPA"
_CHAT_ID_SERVICE  = "TELEGRAM_CHAT_ID_SPA"
_HTTP_TIMEOUT_S   = 10
_TELEGRAM_BASE    = "https://api.telegram.org/bot"


def _read_keychain(service: str) -> str:
    """Read one generic password from the macOS Keychain.

    Returns empty string on any failure (never raises).
    """
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", service,
                "-a", _KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            value = (proc.stdout or "").strip()
            if value:
                return value
    except Exception:
        pass
    return ""


def _get_secret(service: str) -> str:
    """Return secret from Keychain; fall back to env var (service name as-is)."""
    value = _read_keychain(service)
    if not value:
        value = os.environ.get(service, "").strip()
    return value


class PromotionNotifier:
    """Sends ADR-029 promotion decision alerts to the configured Telegram chat.

    Credentials are fetched lazily on each call so that rotation takes effect
    without restarting any daemon.

    All public send_* methods:
      - return True on successful delivery
      - return False on missing credentials, HTTP errors, or any exception
      - never raise
    """

    # ------------------------------------------------------------------
    # Credential helpers (overridable in tests via monkeypatching)
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return Telegram bot token from Keychain / env."""
        return _get_secret(_TOKEN_SERVICE)

    def _get_chat_id(self) -> str:
        """Return Telegram chat id from Keychain / env."""
        return _get_secret(_CHAT_ID_SERVICE)

    # ------------------------------------------------------------------
    # Core HTTP sender
    # ------------------------------------------------------------------

    def _send_message(self, text: str) -> bool:
        """POST *text* to Telegram sendMessage endpoint.

        Returns True on HTTP 200, False on any failure.  Never raises.
        """
        token   = self._get_token()
        chat_id = self._get_chat_id()

        if not token or not chat_id:
            log.warning("PromotionNotifier: credentials not configured — message not sent.")
            return False

        # FLOOD-GUARD: route through the canonical rate-limited chokepoint so
        # promotion alerts can never flood Telegram. Transport only — same HTML
        # message. Credential presence is still checked above (test-overridable).
        try:
            from spa_core.alerts.telegram_client import send_message
            ok = send_message(text, parse_mode="HTML")
            if ok:
                log.info("PromotionNotifier: message delivered.")
            return ok
        except Exception as exc:
            log.warning("PromotionNotifier: unexpected error — %s", exc)
            return False

    # ------------------------------------------------------------------
    # Tier A — AUTO_PROMOTE
    # ------------------------------------------------------------------

    def send_tier_a_alert(self, strategy_id: str, metrics: dict) -> bool:
        """Send an AUTO_PROMOTE alert for a Tier-A strategy promotion.

        Expected *metrics* keys (all optional — missing values rendered as N/A):
          - name              str   human-readable strategy name
          - realized_apy      float e.g. 12.3
          - target_apy        float e.g. 10.0
          - sharpe            float
          - max_drawdown_pct  float (magnitude, positive)
          - paper_days        int
        """
        try:
            name             = metrics.get("name", strategy_id)
            realized_apy     = metrics.get("realized_apy")
            target_apy       = metrics.get("target_apy")
            sharpe           = metrics.get("sharpe")
            max_drawdown_pct = metrics.get("max_drawdown_pct")
            paper_days       = metrics.get("paper_days")

            apy_str = f"{realized_apy:.1f}%" if realized_apy is not None else "N/A"
            tgt_str = f"{target_apy:.1f}%"   if target_apy   is not None else "N/A"
            sha_str = f"{sharpe:.2f}"         if sharpe       is not None else "N/A"
            dwd_str = f"{max_drawdown_pct:.1f}%" if max_drawdown_pct is not None else "N/A"
            day_str = str(paper_days)         if paper_days   is not None else "N/A"

            text = (
                f"⚡ <b>AUTO-PROMOTED: {name}</b>\n"
                f"APY: {apy_str} (target: {tgt_str})\n"
                f"Sharpe: {sha_str} | Drawdown: {dwd_str}\n"
                f"Paper days: {day_str} | Action: AUTO_PROMOTE"
            )
            return self._send_message(text)
        except Exception as exc:
            log.warning("send_tier_a_alert failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Tier B — PENDING_48H
    # ------------------------------------------------------------------

    def send_tier_b_alert(self, strategy_id: str, metrics: dict) -> bool:
        """Send a PENDING_48H alert for a Tier-B promotion decision.

        Expected *metrics* keys (all optional):
          - name          str
          - realized_apy  float
          - sharpe        float
          - deadline_iso  str   ISO-8601 (auto-computed as now+48h if absent)
        """
        try:
            name         = metrics.get("name", strategy_id)
            realized_apy = metrics.get("realized_apy")
            sharpe       = metrics.get("sharpe")

            # Compute deadline: provided explicitly or now + 48 h (UTC)
            deadline_iso = metrics.get("deadline_iso")
            if not deadline_iso:
                deadline_dt  = datetime.now(timezone.utc) + timedelta(hours=48)
                deadline_iso = deadline_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            apy_str = f"{realized_apy:.1f}%" if realized_apy is not None else "N/A"
            sha_str = f"{sharpe:.2f}"         if sharpe       is not None else "N/A"

            text = (
                f"🕐 <b>PENDING AUTO-PROMOTE: {name} in 48h</b>\n"
                f"Reply CANCEL to stop auto-promotion.\n"
                f"APY: {apy_str} | Sharpe: {sha_str}\n"
                f"Deadline: {deadline_iso}"
            )
            return self._send_message(text)
        except Exception as exc:
            log.warning("send_tier_b_alert failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Tier C — MANUAL_REVIEW
    # ------------------------------------------------------------------

    def send_tier_c_alert(self, strategy_id: str, metrics: dict, reason: str) -> bool:
        """Send a MANUAL_REVIEW alert for a Tier-C promotion decision.

        Expected *metrics* keys (all optional):
          - name          str
          - realized_apy  float
          - sharpe        float
        """
        try:
            name         = metrics.get("name", strategy_id)
            realized_apy = metrics.get("realized_apy")
            sharpe       = metrics.get("sharpe")

            apy_str = f"{realized_apy:.1f}%" if realized_apy is not None else "N/A"
            sha_str = f"{sharpe:.2f}"         if sharpe       is not None else "N/A"

            text = (
                f"🔴 <b>MANUAL REVIEW REQUIRED: {name}</b>\n"
                f"Reason: {reason}\n"
                f"APY: {apy_str} | Sharpe: {sha_str}\n"
                f"Action: USER_APPROVAL_NEEDED"
            )
            return self._send_message(text)
        except Exception as exc:
            log.warning("send_tier_c_alert failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Cycle health
    # ------------------------------------------------------------------

    def send_health_alert(self, health_report: dict) -> bool:
        """Send a cycle health WARNING or CRITICAL alert.

        Expected *health_report* keys (all optional):
          - overall   str  e.g. "WARNING" or "CRITICAL"
          - checks    list[dict]  each: {"name": str, "status": str, "message": str}
          - timestamp str  ISO-8601 (defaults to now UTC)
        """
        try:
            overall   = health_report.get("overall", "UNKNOWN")
            checks    = health_report.get("checks", [])
            timestamp = health_report.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            emoji = "⚠️" if overall == "WARNING" else "🚨"

            check_lines = []
            for c in checks:
                c_name   = c.get("name", "?")
                c_status = c.get("status", "?")
                c_msg    = c.get("message", "")
                line = f"• {c_name}: {c_status}"
                if c_msg:
                    line += f" — {c_msg}"
                check_lines.append(line)

            checks_block = "\n".join(check_lines) if check_lines else "No check details."

            text = (
                f"{emoji} <b>SPA Health: {overall}</b>\n"
                f"{checks_block}\n"
                f"Time: {timestamp}"
            )
            return self._send_message(text)
        except Exception as exc:
            log.warning("send_health_alert failed: %s", exc)
            return False
