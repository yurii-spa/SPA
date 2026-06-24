"""
spa_core/alerts/research_progress_telegram.py

Weekly research progress report for Telegram.
Sent every Monday at 09:00 (via launchd).

Reads gate/source/regime data from local JSON files and formats a concise
Russian-language message for the SPA Telegram channel.

Credentials are read from macOS Keychain at runtime — never stored in files.
  security find-generic-password -s TELEGRAM_BOT_TOKEN_SPA -w
  security find-generic-password -s TELEGRAM_CHAT_ID_SPA -w

MP-1346 (v9.62)
stdlib only, no external dependencies.

Format example:
  📊 SPA Research Update — Неделя N

  CPA Gate Status:
  ✅ Backtest Gate: PASS
  ✅ Pre-Paper Gate: PASS
  ⏳ Paper Trading: Идёт (X дней, Y очков)
  🔒 Live: ЗАБЛОКИРОВАНО

  Research Стратегии:
  📈 RS-001 Anti-Crisis: ~18.2% APY (target)
     Статус: Разрешён

  📈 RS-002 Cashflow LP: ~29.2% gross / ~15% net
     Статус: ПРИОСТАНОВЛЕНО (медвежий рынок)

  Источники данных: 8 из 24 чистых (33%)

  Следующие шаги:
  1. Найти DeFiLlama pool ID для GMX v2
  2. Подписать owner acceptance
  3. Дождаться 30 дней paper trading
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_HTTP_TIMEOUT_S = 10


class ResearchProgressTelegram:
    """
    Builds and sends weekly research progress Telegram report.

    All sections are graceful: missing / malformed JSON files return
    placeholder text rather than raising exceptions.

    Args:
        bot_token: Telegram bot token.  None → read from macOS Keychain.
        chat_id:   Telegram chat id.    None → read from macOS Keychain.
        base_dir:  Root of the SPA repo (default: current working directory).
    """

    # ── RS-001 static targets ──────────────────────────────────────────────────
    _RS001_APY_TARGET    = 18.2
    _RS001_ALLOCATION_PCT = 15.0      # clean-source share currently usable

    # ── RS-002 static targets ──────────────────────────────────────────────────
    _RS002_APY_GROSS     = 29.2
    _RS002_APY_NET       = 15.0
    _RS002_IL_DRAG_PCT   = 12.0       # BTC ±30% scenario

    # ── Default next-step backlog ──────────────────────────────────────────────
    _DEFAULT_NEXT_STEPS = [
        "Найти DeFiLlama pool ID для GMX v2",
        "Подписать owner acceptance (ADR-002)",
        "Дождаться 30 дней paper trading для GoLive",
    ]

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id:   Optional[str] = None,
        base_dir:  str = ".",
    ) -> None:
        self._bot_token = bot_token
        self._chat_id   = chat_id
        self._base_dir  = Path(base_dir)

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_message(self) -> str:
        """
        Build the full weekly Telegram message in Russian.

        Reads gate status, source pipeline, and regime data.
        Graceful fallback for any missing files.

        Returns a non-empty string in all cases.
        """
        today   = datetime.datetime.now(datetime.timezone.utc)
        week_no = today.isocalendar()[1]

        lines: list[str] = [
            f"📊 *SPA Research Update — Неделя {week_no}*\n",
            self.gate_section(),
            self.strategy_section(),
            self.source_section(),
            self.next_steps_section(),
        ]
        return "\n".join(lines)

    def gate_section(self) -> str:
        """
        Gate status section.

        Reads: data/backtest/pre_paper_backtest_gate.json,
               data/backtest/paper_ready_gate.json,
               data/paper_trading_status.json.

        Returns a formatted string containing Backtest and Pre-Paper labels.
        """
        backtest_status  = self._read_backtest_status()
        paper_ready      = self._read_paper_ready()
        paper_status_obj = self._read_paper_trading_status()

        # Backtest gate
        bt_pass = backtest_status.get("status") == "PASS"
        bt_icon = "✅" if bt_pass else "❌"
        bt_line = f"{bt_icon} Backtest Gate: {backtest_status.get('status', 'UNKNOWN')}"

        # Pre-Paper gate
        pp_pass = backtest_status.get("paper_test_can_be_designed", False)
        pp_icon = "✅" if pp_pass else "❌"
        pp_line = f"{pp_icon} Pre-Paper Gate: {'PASS' if pp_pass else 'NOT READY'}"

        # Paper trading
        days   = paper_status_obj.get("days_running", 0)
        active = paper_status_obj.get("paper_active", False)
        if active and days > 0:
            pt_line = f"⏳ Paper Trading: Идёт ({days} дней)"
        elif paper_ready.get("status") == "READY":
            pt_line = "✅ Paper Trading: ГОТОВ"
        else:
            pt_line = "⏳ Paper Trading: Ожидает запуска"

        # Live
        owner_ok  = paper_ready.get("paper_trading_allowed", False)
        live_icon = "✅" if owner_ok else "🔒"
        live_line = f"{live_icon} Live: {'РАЗРЕШЕНО' if owner_ok else 'ЗАБЛОКИРОВАНО'}"

        return "CPA Gate Status:\n" + "\n".join(
            ["  " + l for l in (bt_line, pp_line, pt_line, live_line)]
        )

    def strategy_section(self) -> str:
        """
        RS-001 and RS-002 section.

        Returns a formatted string containing 'RS-001' and 'RS-002'.
        """
        regime = self._read_regime()

        # RS-001 — Anti-Crisis Hedge
        rs001_status = "Разрешён (действует в любом режиме)"
        rs001_block  = [
            f"📈 *RS-001 Anti-Crisis Hedge* — ~{self._RS001_APY_TARGET:.1f}% APY (target)",
            f"   Чистых данных: {self._RS001_ALLOCATION_PCT:.0f}% аллокации",
            f"   Статус: {rs001_status}",
        ]

        # RS-002 — Cashflow LP
        if regime == "bear":
            rs002_status = "ПРИОСТАНОВЛЕНО (медвежий рынок — IL драг слишком высок)"
        else:
            rs002_status = f"Разрешён (режим: {regime.upper()})"

        rs002_block = [
            f"📈 *RS-002 Cashflow LP* — ~{self._RS002_APY_GROSS:.1f}% gross / ~{self._RS002_APY_NET:.1f}% net",
            f"   IL драг при BTC ±30%: ~{self._RS002_IL_DRAG_PCT:.0f}%",
            f"   Статус: {rs002_status}",
        ]

        return "\nResearch Стратегии:\n" + "\n".join(rs001_block) + "\n\n" + "\n".join(rs002_block)

    def source_section(self) -> str:
        """
        Source quality section.

        Returns a string containing at least two numbers (clean / total).
        """
        clean, total, by_state = self._read_source_counts()

        pct  = (clean * 100 // total) if total > 0 else 0
        line = f"\nИсточники данных: {clean} из {total} чистых ({pct}%)"

        # Break-down by status
        detail: list[str] = []
        labels = {
            "pending":       "на проверке",
            "review":        "требуют ревью",
            "source_needed": "нет источника",
            "manual_proxy":  "ручной прокси",
            "research_only": "только исследование",
        }
        for key, label in labels.items():
            cnt = by_state.get(key, 0)
            if cnt:
                detail.append(f"    {cnt} {label}")

        if detail:
            line += "\n" + "\n".join(detail)

        return line

    def next_steps_section(self) -> str:
        """
        Next 3 steps section.

        Returns a string with at least 1 numbered step.
        """
        steps = self._resolve_next_steps()
        lines = ["\nСледующие шаги:"]
        for i, step in enumerate(steps[:3], start=1):
            lines.append(f"  {i}. {step}")
        return "\n".join(lines)

    def send(self) -> bool:
        """
        Build and send the weekly progress message via Telegram API.

        Reads credentials from macOS Keychain if not provided at construction.
        Never raises — returns False on any failure.

        Returns:
            True on successful send (HTTP 200 + ok=True), False otherwise.
        """
        try:
            token   = self._resolve_token()
            chat_id = self._resolve_chat_id()
        except EnvironmentError:
            return False

        text = self.build_message()
        # FLOOD-GUARD: route through the canonical rate-limited client so research
        # progress messages share the cross-process flood guard. Transport only —
        # same Markdown message. Credentials are re-resolved by the canonical
        # client from the same Keychain entries (TELEGRAM_*_SPA).
        _ = (token, chat_id)  # presence already validated above
        try:
            from spa_core.alerts.telegram_client import send_message
            return send_message(text, parse_mode="Markdown")
        except Exception:  # noqa: BLE001
            return False

    # ── Private data readers ───────────────────────────────────────────────────

    def _read_backtest_status(self) -> dict:
        path = self._base_dir / "data" / "backtest" / "pre_paper_backtest_gate.json"
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return {}

    def _read_paper_ready(self) -> dict:
        path = self._base_dir / "data" / "backtest" / "paper_ready_gate.json"
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return {}

    def _read_paper_trading_status(self) -> dict:
        path = self._base_dir / "data" / "paper_trading_status.json"
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return {"paper_active": True, "days_running": data.get("days_running", 0)}
        except Exception:  # noqa: BLE001
            return {"paper_active": False, "days_running": 0}

    def _read_regime(self) -> str:
        """Returns normalised regime: bull / bear / neutral."""
        path = self._base_dir / "data" / "market_regime.json"
        _map = {
            "bull": "bull", "bear": "bear",
            "sideways": "neutral", "volatile": "neutral",
            "stable": "neutral", "neutral": "neutral",
        }
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            raw = str(data.get("regime", "neutral")).lower()
            return _map.get(raw, "neutral")
        except Exception:  # noqa: BLE001
            return "neutral"

    def _read_source_counts(self) -> tuple[int, int, dict]:
        """Returns (clean, total, by_state_dict)."""
        try:
            from spa_core.backtesting.source_pipeline import SourcePipeline
            pipeline  = SourcePipeline(
                data_dir=str(self._base_dir / "data" / "backtest")
            )
            by_state  = pipeline.source_summary()
            total     = sum(by_state.values())
            clean     = by_state.get("clean_included", 0)
            return clean, total, by_state
        except Exception:  # noqa: BLE001
            return 0, 0, {}

    def _resolve_next_steps(self) -> list[str]:
        """
        Return next-step list.

        Reads data/backtest/paper_ready_gate.json blockers to auto-generate
        steps; falls back to static defaults.
        """
        paper_ready = self._read_paper_ready()
        blockers    = paper_ready.get("blockers", [])
        if blockers:
            return [str(b) for b in blockers[:3]]
        return list(self._DEFAULT_NEXT_STEPS)

    # ── Credential resolution ──────────────────────────────────────────────────

    def _resolve_token(self) -> str:
        if self._bot_token is not None:
            return self._bot_token
        return self._read_keychain("TELEGRAM_BOT_TOKEN_SPA")

    def _resolve_chat_id(self) -> str:
        if self._chat_id is not None:
            return self._chat_id
        return self._read_keychain("TELEGRAM_CHAT_ID_SPA")

    @staticmethod
    def _read_keychain(service: str) -> str:
        """Read a generic password from macOS Keychain via subprocess."""
        import subprocess
        try:
            proc = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-a", "spa", "-w"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            raise EnvironmentError(f"Keychain read failed for service '{service}'") from exc
        value = (proc.stdout or "").strip()
        if proc.returncode != 0 or not value:
            raise EnvironmentError(
                f"Telegram credential '{service}' not found in Keychain"
            )
        return value
