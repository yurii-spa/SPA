# LLM_FORBIDDEN
"""
SPA Tournament Telegram Notifications v1.0
spa_core/tournament/tournament_telegram.py

Sends tournament-specific Telegram messages:
  - Daily standings (top-5 with paper P&L)
  - Promotion alerts (paper → live advisory)
  - Rank-change alerts for top-3

LLM_FORBIDDEN: no AI calls. Pure formatting + stdlib urllib.
Constraints
-----------
* stdlib only
* Keychain tokens via subprocess; graceful skip if unavailable
* Never raises — all public methods return bool and swallow exceptions
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

DASHBOARD_URL = "https://yuriiykulieshov.github.io/SPA_Claude/"

# Rank medals for top-3
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _keychain_secret(service: str) -> str:
    """Read a secret from macOS Keychain. Returns '' on any failure."""
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
    except Exception as exc:
        _log.debug("Keychain lookup failed for %s: %s", service, exc)
        return ""


class TournamentTelegram:
    """
    Telegram notification sender for the Tournament Engine.

    Token resolution order:
      1. Environment variables (SPA_TELEGRAM_TOKEN_TOURNAMENT / SPA_TELEGRAM_CHAT_ID_TOURNAMENT)
      2. Keychain services TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA
      3. Fallback env vars SPA_TELEGRAM_TOKEN / SPA_TELEGRAM_CHAT_ID

    If none found → available=False → all methods return False without raising.
    """

    def __init__(self) -> None:
        self.token = (
            os.getenv("SPA_TELEGRAM_TOKEN_TOURNAMENT", "").strip()
            or _keychain_secret("TELEGRAM_BOT_TOKEN_SPA")
            or os.getenv("SPA_TELEGRAM_TOKEN", "").strip()
        )
        self.chat_id = (
            os.getenv("SPA_TELEGRAM_CHAT_ID_TOURNAMENT", "").strip()
            or _keychain_secret("TELEGRAM_CHAT_ID_SPA")
            or os.getenv("SPA_TELEGRAM_CHAT_ID", "").strip()
        )
        self.available = bool(self.token and self.chat_id)
        if not self.available:
            _log.debug(
                "TournamentTelegram: no credentials found — messages will be skipped"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Core send
    # ─────────────────────────────────────────────────────────────────────────

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        POST a message to the Telegram Bot API.
        Returns True on success, False on any failure. Never raises.
        """
        if not self.available:
            _log.debug("TournamentTelegram.send: skipped (not configured)")
            return False

        # FLOOD-GUARD: honour the shared cross-process rate limit before sending.
        # We POST directly with this instance's resolved credentials, so call the
        # guard explicitly rather than routing through telegram_client.send_message
        # (which reads its own Keychain credentials and ignores SPA_TELEGRAM_*).
        try:
            from spa_core.alerts.telegram_client import flood_guard_ok
            if not flood_guard_ok(text):
                return False
        except Exception:  # noqa: BLE001 — guard error must never block a send
            pass

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as exc:
            _log.warning("TournamentTelegram HTTP error %s: %s", exc.code, exc.reason)
            return False
        except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
            _log.error("Telegram unexpected error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Tournament-specific senders
    # ─────────────────────────────────────────────────────────────────────────

    def send_daily_standings(
        self,
        top5: List[Dict[str, Any]],
        shadow: Optional[Dict[str, Any]] = None,
        date_str: Optional[str] = None,
    ) -> bool:
        """
        Send daily top-5 tournament standings with paper P&L.

        Example output:
            🏆 SPA Tournament — 2026-06-22

            Daily standings (shadow paper trading):

            🥇 #1 s12_base_layer_yield
               Sharpe: 196.17 | Paper APY: 4.10%
               Today yield: +$1.12 | Days tracked: 5

            🥈 #2 s5_pendle_enhanced
               Sharpe: 185.48 | Paper APY: 1.34%
               Today yield: +$0.37 | Days tracked: 5
            ...
            📊 Dashboard
        """
        if not top5:
            return False

        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        shadow = shadow or {}
        daily_results: List[Dict] = shadow.get("daily_results", [])

        # Find today's results
        today_entry = next(
            (dr for dr in daily_results if dr.get("date") == date_str),
            {},
        )
        today_strategies: Dict[str, Dict] = {
            s["strategy_id"]: s
            for s in today_entry.get("strategies", [])
        }

        try:
            lines: List[str] = [
                f"🏆 <b>SPA Tournament — {date_str}</b>",
                "",
                "Daily standings (shadow paper trading):",
                "",
            ]

            for s in top5[:5]:
                rank = s.get("rank", 0)
                sid = s.get("strategy_key") or s.get("id", "?")
                sharpe = s.get("sharpe", 0.0)
                paper_apy = s.get("paper_apy", s.get("annual_return_pct", 0.0))
                days_active = s.get("days_active", 0)

                medal = _MEDALS.get(rank, f"#{rank}")
                today_data = today_strategies.get(sid, {})
                today_yield = today_data.get("daily_yield_usd", 0.0)
                yield_sign = "+" if today_yield >= 0 else ""
                today_apy = today_data.get("annualised_apy_pct", 0.0)

                lines.append(
                    f"{medal} <b>#{rank} {sid}</b>\n"
                    f"   Sharpe: {sharpe:.2f} | Paper APY: {paper_apy:.2f}%\n"
                    f"   Today yield: {yield_sign}${today_yield:.2f} "
                    f"({today_apy:.2f}% ann.) | Days: {days_active}"
                )
                lines.append("")

            lines.append(f'📊 <a href="{DASHBOARD_URL}">View Dashboard</a>')

            text = "\n".join(lines)
            return self.send(text)

        except Exception as exc:
            _log.error("send_daily_standings failed: %s", exc)
            return False

    def send_promotion_alert(
        self,
        strategy_name: str,
        phase_from: str,
        phase_to: str,
    ) -> bool:
        """
        Send alert when a strategy is promoted between phases.

        Example output:
            🎯 SPA Tournament — Promotion Alert

            📈 s12_base_layer_yield is ready for promotion!

            paper_30d → live

            ⚠️ Advisory only — manual review required
            Criteria met: Sharpe ✅ | Days ✅ | APY ✅ | Drawdown ✅

            📊 Dashboard
        """
        try:
            arrow = f"{phase_from} → {phase_to}"
            is_to_live = phase_to == "live"
            icon = "🚀" if is_to_live else "📈"
            warning = (
                "\n⚠️ <b>Advisory only</b> — manual review required before activation"
                if is_to_live else ""
            )

            text = (
                f"🎯 <b>SPA Tournament — Promotion Alert</b>\n"
                f"\n"
                f"{icon} <b>{strategy_name}</b> is ready for promotion!\n"
                f"\n"
                f"<code>{arrow}</code>"
                f"{warning}\n"
                f"\n"
                f'📊 <a href="{DASHBOARD_URL}">View Dashboard</a>'
            )
            return self.send(text)

        except Exception as exc:
            _log.error("send_promotion_alert failed: %s", exc)
            return False

    def send_position_change(
        self,
        strategy_name: str,
        old_rank: Optional[int],
        new_rank: int,
    ) -> bool:
        """
        Send alert when a strategy changes position in top-3.

        Example output:
            📊 SPA Tournament — Rank Change

            📉 s5_pendle_enhanced: #2 → #3

        or for entering top-3:
            📊 SPA Tournament — Rank Change

            📈 s12_base_layer_yield: entered top-3 at #2
        """
        try:
            if old_rank is None:
                # Entered top-3 for first time
                medal = _MEDALS.get(new_rank, f"#{new_rank}")
                text = (
                    f"📊 <b>SPA Tournament — Rank Change</b>\n"
                    f"\n"
                    f"🆕 <b>{strategy_name}</b> entered top-3 at {medal}"
                )
            else:
                direction = "📈" if new_rank < old_rank else "📉"
                old_medal = _MEDALS.get(old_rank, f"#{old_rank}")
                new_medal = _MEDALS.get(new_rank, f"#{new_rank}")
                text = (
                    f"📊 <b>SPA Tournament — Rank Change</b>\n"
                    f"\n"
                    f"{direction} <b>{strategy_name}</b>: "
                    f"{old_medal} → {new_medal}"
                )
            return self.send(text)

        except Exception as exc:
            _log.error("send_position_change failed: %s", exc)
            return False

    def send_daily_error_report(
        self,
        date_str: str,
        errors: List[str],
    ) -> bool:
        """
        Send an error summary if the daily cycle encountered issues.

        Example output:
            ⚠️ SPA Tournament — Daily Errors (2026-06-22)

            2 error(s) detected:
            • update_shadow_day: APY data unavailable
            • telegram: timeout
        """
        if not errors:
            return False
        try:
            lines = [
                f"⚠️ <b>SPA Tournament — Daily Errors ({date_str})</b>",
                f"\n{len(errors)} error(s) detected:",
            ]
            for e in errors[:10]:  # cap at 10 lines
                lines.append(f"• {e}")

            text = "\n".join(lines)
            return self.send(text)
        except Exception as exc:
            _log.error("send_daily_error_report failed: %s", exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Formatting helpers (pure functions — no network, usable in tests)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_daily_standings(
        top5: List[Dict[str, Any]],
        today_strategies: Dict[str, Dict],
        date_str: str,
    ) -> str:
        """
        Return the formatted standings string (no network call).
        Exposed as a static method so tests can verify formatting without
        creating a real TournamentTelegram instance with credentials.
        """
        lines: List[str] = [
            f"🏆 <b>SPA Tournament — {date_str}</b>",
            "",
            "Daily standings (shadow paper trading):",
            "",
        ]
        for s in top5[:5]:
            rank = s.get("rank", 0)
            sid = s.get("strategy_key") or s.get("id", "?")
            sharpe = s.get("sharpe", 0.0)
            paper_apy = s.get("paper_apy", s.get("annual_return_pct", 0.0))
            days_active = s.get("days_active", 0)
            medal = _MEDALS.get(rank, f"#{rank}")
            today_data = today_strategies.get(sid, {})
            today_yield = today_data.get("daily_yield_usd", 0.0)
            yield_sign = "+" if today_yield >= 0 else ""
            today_apy = today_data.get("annualised_apy_pct", 0.0)

            lines.append(
                f"{medal} <b>#{rank} {sid}</b>\n"
                f"   Sharpe: {sharpe:.2f} | Paper APY: {paper_apy:.2f}%\n"
                f"   Today yield: {yield_sign}${today_yield:.2f} "
                f"({today_apy:.2f}% ann.) | Days: {days_active}"
            )
            lines.append("")

        lines.append(f'📊 <a href="{DASHBOARD_URL}">View Dashboard</a>')
        return "\n".join(lines)

    @staticmethod
    def format_promotion_alert(
        strategy_name: str,
        phase_from: str,
        phase_to: str,
    ) -> str:
        """Return formatted promotion alert string (no network)."""
        arrow = f"{phase_from} → {phase_to}"
        is_to_live = phase_to == "live"
        icon = "🚀" if is_to_live else "📈"
        warning = (
            "\n⚠️ <b>Advisory only</b> — manual review required before activation"
            if is_to_live else ""
        )
        return (
            f"🎯 <b>SPA Tournament — Promotion Alert</b>\n"
            f"\n"
            f"{icon} <b>{strategy_name}</b> is ready for promotion!\n"
            f"\n"
            f"<code>{arrow}</code>"
            f"{warning}\n"
            f"\n"
            f'📊 <a href="{DASHBOARD_URL}">View Dashboard</a>'
        )

    @staticmethod
    def format_position_change(
        strategy_name: str,
        old_rank: Optional[int],
        new_rank: int,
    ) -> str:
        """Return formatted rank-change string (no network)."""
        if old_rank is None:
            medal = _MEDALS.get(new_rank, f"#{new_rank}")
            return (
                f"📊 <b>SPA Tournament — Rank Change</b>\n"
                f"\n"
                f"🆕 <b>{strategy_name}</b> entered top-3 at {medal}"
            )
        direction = "📈" if new_rank < old_rank else "📉"
        old_medal = _MEDALS.get(old_rank, f"#{old_rank}")
        new_medal = _MEDALS.get(new_rank, f"#{new_rank}")
        return (
            f"📊 <b>SPA Tournament — Rank Change</b>\n"
            f"\n"
            f"{direction} <b>{strategy_name}</b>: "
            f"{old_medal} → {new_medal}"
        )
