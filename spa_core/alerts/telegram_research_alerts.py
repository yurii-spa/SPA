"""
spa_core/alerts/telegram_research_alerts.py

Telegram alerts for research strategy milestones and source quality changes.

Sends alerts to the SPA Telegram channel for RS-001 and RS-002 research events.
Credentials are read from macOS Keychain at runtime (never stored in files).

Alert triggers:
  1. Source promoted: PENDING → CLEAN_INCLUDED
     → "🔬 Source Promoted: {source} is now clean evidence!"
  2. Cash drag exceeds threshold:
     → "⚠️ PIT Cash Drag Alert: {pct}% of backtest in defensive cash"
  3. Owner acceptance signed:
     → "✅ Owner Acceptance Signed — Paper Trading can begin!"
  4. Research exclusion warning:
     → "📊 Research Note: {strategy} uses SOURCE_NEEDED data ({pct}% of allocation)"
  5. Weekly research digest:
     → "📋 Weekly Research Digest\nRS-001 shadow: +{X}%\nRS-002 shadow: +{Y}%"

Format: Markdown, messages in Russian for user Yurii.
stdlib only. No external dependencies.

Secrets policy (incident 2026-06-10): bot token and chat_id are NEVER stored in
files — always read at runtime from macOS Keychain via:
  security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w
  security find-generic-password -s TELEGRAM_CHAT_ID_SPA -w

Tests must mock urllib.request.urlopen and subprocess.run to avoid real network calls.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

log = logging.getLogger("spa.alerts.telegram_research_alerts")

# ── Keychain keys ─────────────────────────────────────────────────────────────
_TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
_CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"
_KEYCHAIN_ACCOUNT = "spa"

# ── HTTP settings ─────────────────────────────────────────────────────────────
_HTTP_TIMEOUT_S = 10
_TELEGRAM_API_BASE = "https://api.telegram.org"


def _read_keychain(service: str) -> str:
    """
    Read a generic password from macOS Keychain.

    Raises:
        EnvironmentError: if the Keychain entry is not found or the
                          subprocess call fails.
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
            timeout=_HTTP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError(
            f"Keychain read failed for service '{service}'"
        ) from exc

    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        raise EnvironmentError(
            f"Telegram credential '{service}' not found in Keychain"
        )
    return value


class TelegramResearchAlerts:
    """
    Sends Telegram alerts for research strategy events (RS-001, RS-002).

    Instantiate with explicit credentials (for tests) or without to read
    them from macOS Keychain at first use.

    Usage::

        alerts = TelegramResearchAlerts()  # reads from Keychain
        alerts.source_promoted_alert("source-xyz", "PENDING", "CLEAN_INCLUDED")
        alerts.cash_drag_alert(91.5)
        alerts.owner_acceptance_signed_alert("Yurii")
        alerts.weekly_digest(rs001_shadow_pct=2.3, rs002_shadow_pct=1.7)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            bot_token: Telegram bot token.  None → read from Keychain on first send.
            chat_id:   Telegram chat id.    None → read from Keychain on first send.
        """
        self._bot_token = bot_token
        self._chat_id = chat_id

    # ── Public alert methods ───────────────────────────────────────────────────

    def source_promoted_alert(
        self,
        source_id: str,
        old_state: str,
        new_state: str,
    ) -> bool:
        """
        Alert: a research source was promoted to CLEAN_INCLUDED.

        Returns True on successful send, False on any error.
        """
        text = (
            f"🔬 *Source Promoted: {source_id}*\n"
            f"\n"
            f"Источник повышен: `{old_state}` → `{new_state}`\n"
            f"Источник теперь является чистым свидетельством и включён в расчёт!\n"
            f"\n"
            f"_Стратегии RS-001/RS-002 обновлены._"
        )
        return self._send(text)

    def cash_drag_alert(
        self,
        pct: float,
        strategy: str = "RS-001",
    ) -> bool:
        """
        Alert: PIT cash drag exceeds threshold.

        Args:
            pct:      Cash drag percentage (0–100).
            strategy: Strategy name (default RS-001).

        Returns True on successful send, False on any error.
        """
        text = (
            f"⚠️ *PIT Cash Drag Alert — {strategy}*\n"
            f"\n"
            f"{pct:.1f}% времени бэктест находился в защитном кеше.\n"
            f"\n"
            f"Это подтверждает высокий cash drag в режиме PIT strict. "
            f"Протоколы, запущенные в 2024+, недоступны в 2022–2023 при PIT-фильтрации.\n"
            f"\n"
            f"_Стратегия: {strategy}_"
        )
        return self._send(text)

    def owner_acceptance_signed_alert(self, owner: str) -> bool:
        """
        Alert: Owner acceptance has been signed — paper trading can begin.

        Args:
            owner: Name of the owner who signed.

        Returns True on successful send, False on any error.
        """
        text = (
            f"✅ *Owner Acceptance Signed*\n"
            f"\n"
            f"Владелец *{owner}* подтвердил запуск бумажной торговли!\n"
            f"\n"
            f"Paper Trading может начаться согласно ADR-002 (GoLive transfer rule).\n"
            f"GoLiveChecker будет отслеживать 30 дней непрерывного трека.\n"
            f"\n"
            f"_Подпись получена. Система готова к переходу на реальный трек._"
        )
        return self._send(text)

    def research_exclusion_warning(
        self,
        strategy: str,
        source_needed_pct: float,
    ) -> bool:
        """
        Alert: a research strategy uses SOURCE_NEEDED data above threshold.

        Args:
            strategy:          Strategy name (e.g. "RS-001").
            source_needed_pct: Percentage of allocation using SOURCE_NEEDED data.

        Returns True on successful send, False on any error.
        """
        text = (
            f"📊 *Research Note — {strategy}*\n"
            f"\n"
            f"Стратегия `{strategy}` использует SOURCE_NEEDED данные "
            f"в {source_needed_pct:.1f}% аллокации.\n"
            f"\n"
            f"Источники в статусе SOURCE_NEEDED ещё не верифицированы. "
            f"Результаты бэктеста могут быть ненадёжными.\n"
            f"\n"
            f"_Рекомендация: дождаться перевода источников в CLEAN_INCLUDED._"
        )
        return self._send(text)

    def weekly_digest(
        self,
        rs001_shadow_pct: float = 0.0,
        rs002_shadow_pct: float = 0.0,
    ) -> bool:
        """
        Weekly research digest: RS-001 and RS-002 shadow performance.

        Args:
            rs001_shadow_pct: RS-001 shadow P&L for the week (%).
            rs002_shadow_pct: RS-002 shadow P&L for the week (%).

        Returns True on successful send, False on any error.
        """
        sign_001 = "+" if rs001_shadow_pct >= 0 else ""
        sign_002 = "+" if rs002_shadow_pct >= 0 else ""

        text = (
            f"📋 *Weekly Research Digest*\n"
            f"\n"
            f"RS-001 shadow: {sign_001}{rs001_shadow_pct:.2f}%\n"
            f"RS-002 shadow: {sign_002}{rs002_shadow_pct:.2f}%\n"
            f"\n"
            f"_Данные обновляются автоматически. "
            f"Используйте дашборд для подробной аналитики._"
        )
        return self._send(text)

    # ── Internal send ──────────────────────────────────────────────────────────

    def _send(self, text: str) -> bool:
        """
        Sends a Markdown message to the configured Telegram chat.

        Reads credentials from Keychain if not provided at construction.
        Fail-safe: any error (network, credentials, HTTP) → WARNING log + False.
        Never raises.

        Returns:
            True on success (HTTP 200 + ok=True), False otherwise.
        """
        # RETIRED as a Telegram push (Phase-1 Telegram rebuild). Research alerts
        # are on-demand (the bot's /research view); they no longer interrupt the
        # owner. The composed text is routed to the digest queue. Always returns
        # False. Never raises.
        try:
            from spa_core.telegram import push_policy
            push_policy._enqueue_digest(
                push_policy._tg_dir(),
                {
                    "ts": push_policy._now_iso(),
                    "event_key": "research_alert",
                    "severity": "INFO",
                    "title": "Research alert",
                    "body": (text or "")[:500],
                    "reason": "telegram_research_alerts_retired_push",
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return False

    # ── Credential resolution ──────────────────────────────────────────────────

    def _resolve_token(self) -> str:
        """Returns bot token (explicit or from Keychain)."""
        if self._bot_token is not None:
            return self._bot_token
        return _read_keychain(_TOKEN_SERVICE)

    def _resolve_chat_id(self) -> str:
        """Returns chat id (explicit or from Keychain)."""
        if self._chat_id is not None:
            return self._chat_id
        return _read_keychain(_CHAT_ID_SERVICE)
