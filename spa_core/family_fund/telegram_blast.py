"""
SPA Family Fund — Telegram Blast Notifications (Phase 0)
Reads bot token / chat ID from macOS Keychain via subprocess.
Pure stdlib. No external dependencies.
SECRETS POLICY: No tokens ever written to this file or any generated artifact.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from spa_core.family_fund.models import InvestorStatement
from spa_core.utils.errors import ConfigError

__all__ = ["TelegramBlast"]

_MONTH_NAMES_EN = {
    "01": "January", "02": "February", "03": "March",
    "04": "April",   "05": "May",      "06": "June",
    "07": "July",    "08": "August",   "09": "September",
    "10": "October", "11": "November", "12": "December",
}

_LEVEL_EMOJI = {
    "info":     "ℹ️",
    "warn":     "⚠️",
    "critical": "🚨",
}


class TelegramBlast:
    """
    One-click Telegram notifications for the Family Fund.

    Credentials are fetched on-demand from macOS Keychain:
      - TELEGRAM_BOT_TOKEN_SPA
      - TELEGRAM_CHAT_ID_SPA

    Usage:
        blast = TelegramBlast()
        blast.send_monthly_report("2026-06", statements)
    """

    _TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """
        token / chat_id: if provided, skip Keychain lookup (useful for tests).
        """
        self._token_override = token
        self._chat_id_override = chat_id

    # ------------------------------------------------------------------ #
    # Keychain
    # ------------------------------------------------------------------ #

    def _get_token(self, key: str) -> str:
        """
        Read a secret from macOS Keychain via the `security` CLI.
        Raises RuntimeError if the secret is not found.
        """
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", key,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ConfigError(
                key,
                f"Keychain lookup failed: {result.stderr.strip()}",
            )
        return result.stdout.strip()

    def _resolve_credentials(self):
        """Return (token, chat_id) — from overrides or Keychain."""
        token = (
            self._token_override
            if self._token_override is not None
            else self._get_token("TELEGRAM_BOT_TOKEN_SPA")
        )
        chat_id = (
            self._chat_id_override
            if self._chat_id_override is not None
            else self._get_token("TELEGRAM_CHAT_ID_SPA")
        )
        return token, chat_id

    # ------------------------------------------------------------------ #
    # HTTP transport
    # ------------------------------------------------------------------ #

    def _post(self, token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
        """
        Send a Telegram message via the Bot API.
        Returns the API response dict.
        Raises urllib.error.HTTPError / RuntimeError on failure.
        """
        url = self._TELEGRAM_API.format(token=token)
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def send_monthly_report(
        self, period: str, statements: List[InvestorStatement]
    ) -> dict:
        """
        Send a Markdown monthly report to the configured Telegram chat.

        Format:
            📊 SPA Monthly Report — June 2026

            👥 Investors: N
            💰 Total P&L: $X,XXX.XX (Y.YY%)
            📈 APY (ann.): Z.ZZ%

            _Generated at: ..._
        """
        year_str, month_str = period[:4], period[5:7]
        month_name = _MONTH_NAMES_EN.get(month_str, month_str)

        total_pnl = sum(s.pnl_usd for s in statements)
        avg_pnl_pct = (
            sum(s.pnl_pct for s in statements) / len(statements)
            if statements else 0.0
        )
        avg_apy = (
            sum(s.apy_annualized for s in statements) / len(statements)
            if statements else 0.0
        )

        pnl_sign = "+" if total_pnl >= 0 else ""

        text = (
            f"📊 *SPA Monthly Report — {month_name} {year_str}*\n\n"
            f"👥 Investors: {len(statements)}\n"
            f"💰 Total P&L: `{pnl_sign}{total_pnl:,.2f} USD` "
            f"({pnl_sign}{avg_pnl_pct:.2f}%)\n"
            f"📈 APY (ann.): `{avg_apy:.2f}%`\n\n"
            f"_Generated at: {statements[0].generated_at if statements else 'n/a'}_"
        )

        token, chat_id = self._resolve_credentials()
        return self._post(token, chat_id, text)

    def send_alert(self, message: str, level: str = "info") -> dict:
        """
        Send a short alert to the Telegram chat.

        level: "info" | "warn" | "critical"
        """
        emoji = _LEVEL_EMOJI.get(level, _LEVEL_EMOJI["info"])
        level_label = level.upper()
        text = f"{emoji} *[SPA Fund Alert — {level_label}]*\n\n{message}"

        token, chat_id = self._resolve_credentials()
        return self._post(token, chat_id, text)
