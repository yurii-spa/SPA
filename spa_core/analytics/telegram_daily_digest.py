"""Telegram Daily Digest (MP-627).

Aggregates all SPA analytics JSON files into a single, formatted
Telegram MarkdownV2 message and optionally sends it via the Bot API.

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Advisory / read-only: the only disk write is :meth:`save_digest` which
  writes atomically (tmp + ``os.replace``) to
  ``data/telegram_digests/YYYY-MM-DD.txt``.
* All data loads are fail-safe: missing or malformed files degrade
  gracefully (section shows a "data unavailable" notice).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Telegram messages are truncated to 4096 chars (API hard limit).

MarkdownV2 escaping
-------------------
The following characters must be escaped with a backslash in MarkdownV2:
``_ * [ ] ( ) ~ ` > # + - = | { } . !``

Public API
----------
``TelegramDailyDigest(data_dir="data/")``

Methods:
    _load_json(filename)            → dict | list | None
    _format_section(section)        → str
    build_portfolio_section()       → DigestSection
    build_alert_section()           → DigestSection
    build_starvation_section()      → DigestSection
    build_progress_section()        → DigestSection
    build_paper_trading_section()   → DigestSection
    build_forecast_section()        → DigestSection
    build_digest(date_str=None)     → str
    send_digest(bot_token, chat_id, date_str=None) → dict
    save_digest(digest_str, date_str=None)         → str

CLI
---
``python3 -m spa_core.analytics.telegram_daily_digest --check``  (default)
``python3 -m spa_core.analytics.telegram_daily_digest --run``    (+ save)
``python3 -m spa_core.analytics.telegram_daily_digest --data-dir PATH``
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_MESSAGE_LEN: int = 4096
_REQUEST_TIMEOUT: int = 10

# Characters that must be escaped in MarkdownV2
_MDV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"

# Ring-buffer depth for the digest save (unused here — we save by date)
_DIGEST_SUBDIR = "telegram_digests"


# ---------------------------------------------------------------------------
# MarkdownV2 helpers
# ---------------------------------------------------------------------------

def escape_mdv2(text: str) -> str:
    """Escape all MarkdownV2 special characters in *text*.

    Characters escaped: ``\\ _ * [ ] ( ) ~ ` > # + - = | { } . !``
    """
    # Backslash must be first to avoid double-escaping
    result = text.replace("\\", "\\\\")
    for ch in r"_*[]()~`>#+-=|{}.!":
        result = result.replace(ch, f"\\{ch}")
    return result


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class DigestSection:
    """One section of the daily digest."""

    title: str            # Section title (plain text, will be escaped)
    emoji: str            # Leading emoji (not escaped — already safe in MDV2)
    lines: List[str] = field(default_factory=list)  # Content lines (plain text)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TelegramDailyDigest:
    """Build and optionally send the SPA daily digest message.

    Parameters
    ----------
    data_dir : str
        Path to the data directory (default ``"data/"``).
    """

    def __init__(self, data_dir: str = "data/") -> None:
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_json(self, filename: str) -> Optional[Union[dict, list]]:
        """Safely load a JSON file from data_dir.

        Returns the parsed object, or ``None`` if the file is missing,
        empty, or contains invalid JSON.
        """
        path = self.data_dir / filename
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return None
            return json.loads(text)
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
            return None

    def _format_section(self, section: DigestSection) -> str:
        """Format a DigestSection as a MarkdownV2 block.

        Output format::

            EMOJI *Title*
              line1
              line2

        Both the title and each line are escaped for MarkdownV2.
        """
        title_escaped = escape_mdv2(section.title)
        header = f"{section.emoji} *{title_escaped}*"
        if not section.lines:
            return header
        body_lines = [f"  {escape_mdv2(line)}" for line in section.lines]
        return "\n".join([header] + body_lines)

    def _latest(self, data: Union[dict, list, None]) -> Optional[dict]:
        """Extract the 'latest' snapshot from a ring-buffer JSON structure."""
        if data is None:
            return None
        if isinstance(data, dict):
            # Ring-buffer style: data["latest"] or data itself
            if "latest" in data:
                return data["latest"] if isinstance(data["latest"], dict) else None
            return data
        if isinstance(data, list):
            return data[-1] if data and isinstance(data[-1], dict) else None
        return None

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def build_portfolio_section(self) -> DigestSection:
        """Load portfolio state and build the Portfolio section.

        Data sources (in priority order):
        - data/strategy_summary.json
        - data/adapter_status.json (execution-domain, read-only here)
        - data/paper_trading_status.json
        """
        lines: List[str] = []

        # Try strategy_summary first
        data = self._load_json("strategy_summary.json")
        snap = self._latest(data)

        if snap:
            apy = snap.get("total_apy_pct") or snap.get("apy_pct") or snap.get("apy") or 0.0
            capital = snap.get("capital_deployed_usd") or snap.get("total_value_usd") or 0.0
            adapter_count = snap.get("adapter_count") or snap.get("active_adapters") or "N/A"
            lines.append(f"APY: {float(apy):.2f}%")
            lines.append(f"Capital deployed: ${float(capital):,.0f}")
            lines.append(f"Active adapters: {adapter_count}")
        else:
            # Fallback: paper_trading_status
            pts = self._load_json("paper_trading_status.json")
            snap2 = self._latest(pts)
            if snap2:
                apy = snap2.get("current_apy_pct") or snap2.get("apy_pct") or 0.0
                capital = snap2.get("total_value_usd") or snap2.get("capital") or 0.0
                lines.append(f"APY: {float(apy):.2f}%")
                lines.append(f"Capital: ${float(capital):,.0f}")
            else:
                lines.append("Portfolio data unavailable")

        return DigestSection(title="Portfolio Overview", emoji="📊", lines=lines)

    def build_alert_section(self) -> DigestSection:
        """Load alert state and build the Alerts section.

        Data sources:
        - data/alert_threshold_log.json
        - data/alert_report.json
        - data/alerts.json
        """
        lines: List[str] = []

        # Try alert_threshold_log first, then alert_report, then alerts
        data = (
            self._load_json("alert_threshold_log.json")
            or self._load_json("alert_report.json")
            or self._load_json("alerts.json")
        )
        snap = self._latest(data)

        if snap:
            # Count by severity
            alerts_list = snap.get("alerts") or snap.get("triggered") or []
            if isinstance(alerts_list, list):
                critical = sum(
                    1 for a in alerts_list
                    if isinstance(a, dict) and a.get("severity", "").upper() == "CRITICAL"
                )
                warning = sum(
                    1 for a in alerts_list
                    if isinstance(a, dict) and a.get("severity", "").upper() == "WARNING"
                )
                lines.append(f"CRITICAL: {critical}")
                lines.append(f"WARNING: {warning}")
                if critical == 0 and warning == 0:
                    lines.append("All clear - no active alerts")
            else:
                # Flat counts
                critical = snap.get("critical_count") or snap.get("CRITICAL") or 0
                warning  = snap.get("warning_count")  or snap.get("WARNING")  or 0
                lines.append(f"CRITICAL: {critical}")
                lines.append(f"WARNING: {warning}")
        else:
            lines.append("Alert data unavailable")

        return DigestSection(title="Alerts", emoji="🚨", lines=lines)

    #: Отчёт сторожа голодания старше этого срока читается как «замер не состоялся».
    #: Порог — двое суток, а не сутки: сторож пишет отчёт из цикла, а цикл ходит не строго
    #: раз в день, и суточный порог краснел бы на штатном такте (тот же класс, что #242 —
    #: срок годности, спрошенный не у того).
    STARVATION_REPORT_MAX_AGE_H = 48.0

    def build_starvation_section(self) -> DigestSection:
        """Голодающий приказ владельца — в канал, который смерть сессии не выключает.

        **Зачем секция (цикл #422).** Сторож `scripts/check_owner_order_starvation.py`
        говорил ровно одному адресату — промпту той сессии, которая и голодит очередь.
        Сессии здесь умирают регулярно, а мёртвая сессия промпт не читает: находка о
        простоявшем приказе владельца исчезала вместе с ней, не оставив следа нигде.
        Дайджест пишет ДРУГОЙ процесс и по своему такту, поэтому у находки появляется
        путь к владельцу, не зависящий от живости цикла.

        Три исхода, и они РАЗНЫЕ (инв. #17):

        * отчёта нет или он старше `STARVATION_REPORT_MAX_AGE_H` — «НЕ ИЗМЕРЕНО»;
          это НЕ «голода нет». Именно молчание на неизмеренном и есть та авария, из-за
          которой critical-приказ простоял четверо суток при 40+ прошедших циклах;
        * отчёт свежий, находок нет — короткая строка, что мерили и чисто;
        * есть находки — строка «⏳ голодает: …» дословно по карточке-заказчику,
          с числом прошедших мимо циклов (или честным «НЕ ИЗМЕРЕНО» вместо него).

        Data source: ``data/owner_order_starvation.json``
        """
        lines: List[str] = []
        data = self._load_json("owner_order_starvation.json")

        if not isinstance(data, dict):
            return DigestSection(
                title="Приказы владельца", emoji="⏳",
                lines=["голодание НЕ ИЗМЕРЕНО: отчёта сторожа нет "
                       "(owner_order_starvation.json) — это не «всё в порядке»"])

        age_h = self._report_age_hours(data.get("generated_at"))
        if age_h is None:
            lines.append("голодание НЕ ИЗМЕРЕНО: у отчёта сторожа нет разбираемой "
                         "отметки времени")
        elif age_h > self.STARVATION_REPORT_MAX_AGE_H:
            lines.append(f"голодание НЕ ИЗМЕРЕНО: замер устарел на {age_h:.0f}ч "
                         f"(порог {self.STARVATION_REPORT_MAX_AGE_H:.0f}ч) — "
                         f"сторожа некому было запустить")

        findings = data.get("findings")
        findings = findings if isinstance(findings, list) else []
        for f in findings:
            if not isinstance(f, dict):
                continue
            cycles = f.get("cycles_passed")
            cycles_ru = (f"{cycles} циклов мимо" if isinstance(cycles, int)
                         else "циклов мимо: НЕ ИЗМЕРЕНО")
            age = f.get("age_hours")
            age_ru = f"{age:.0f}ч" if isinstance(age, (int, float)) else "возраст НЕ ИЗМЕРЕН"
            lines.append(f"⏳ голодает: {f.get('title') or f.get('path') or '(без имени)'} "
                         f"— {age_ru}, {cycles_ru}")

        if not findings and age_h is not None and age_h <= self.STARVATION_REPORT_MAX_AGE_H:
            lines.append(f"голодающих приказов нет (мерили {age_h:.0f}ч назад)")

        return DigestSection(title="Приказы владельца", emoji="⏳", lines=lines)

    def _report_age_hours(self, generated_at) -> Optional[float]:
        """Возраст отметки в часах; None — отметка не разбирается (НЕ ИЗМЕРЕНО, не ноль).

        Отметка из БУДУЩЕГО НЕ зажимается в ноль (урок #291: испорченные часы и чужой
        часовой пояс приходили к проверкам «самой свежей правдой») — отрицательный
        возраст возвращается как есть и порог свежести его пропускает, но такой отчёт
        уже не выглядит только что снятым.
        """
        if not isinstance(generated_at, str) or not generated_at.strip():
            return None
        try:
            when = datetime.fromisoformat(generated_at.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - when).total_seconds() / 3600.0

    def build_progress_section(self) -> DigestSection:
        """Load go-live progress and build the Progress section.

        Data source: data/progress_tracker.json
        """
        lines: List[str] = []
        data = self._load_json("progress_tracker.json")

        if data and isinstance(data, dict):
            days = data.get("paper_days") or 0
            days_to_go = data.get("days_to_golive") or "N/A"
            target = data.get("go_live_target_date") or "N/A"
            verdict = data.get("summary_verdict") or "N/A"
            equity = data.get("current_equity") or 0.0

            milestones = data.get("milestones") or []
            done_ms = sum(1 for m in milestones if isinstance(m, dict) and m.get("done"))
            total_ms = len(milestones)

            lines.append(f"Paper trading day: {days}")
            lines.append(f"Days to go-live: {days_to_go}")
            lines.append(f"Target date: {target}")
            lines.append(f"Milestones: {done_ms}/{total_ms}")
            lines.append(f"Equity: ${float(equity):,.0f}")
            lines.append(f"Verdict: {verdict}")
        else:
            lines.append("Progress data unavailable")

        return DigestSection(title="Go-Live Progress", emoji="🎯", lines=lines)

    def build_paper_trading_section(self) -> DigestSection:
        """Load paper trading performance and build the Paper Trading section.

        Data sources:
        - data/paper_trading_log.json
        - data/pnl_history.json
        - data/equity_curve_daily.json
        """
        lines: List[str] = []

        data = (
            self._load_json("paper_trading_log.json")
            or self._load_json("pnl_history.json")
        )
        snap = self._latest(data)

        if snap:
            day_n = snap.get("day_number") or snap.get("cycle") or "N/A"
            total_pnl = snap.get("total_pnl_usd") or snap.get("pnl_usd") or 0.0
            best = snap.get("best_strategy") or snap.get("top_strategy") or "N/A"
            lines.append(f"Day: {day_n}")
            lines.append(f"Total PnL: ${float(total_pnl):,.2f}")
            lines.append(f"Best strategy: {best}")
        else:
            # Fallback: equity_curve_daily
            ec_data = self._load_json("equity_curve_daily.json")
            ec = self._latest(ec_data)
            if ec:
                equity = ec.get("equity_usd") or ec.get("value") or 0.0
                date_str = ec.get("date") or ec.get("timestamp") or "N/A"
                lines.append(f"Latest equity: ${float(equity):,.0f}")
                lines.append(f"Date: {date_str}")
            else:
                lines.append("Paper trading data unavailable")

        return DigestSection(title="Paper Trading", emoji="📈", lines=lines)

    def build_forecast_section(self) -> DigestSection:
        """Load yield forecast and build the Forecast section.

        Data source: data/yield_forecast.json (ring-buffer)
        """
        lines: List[str] = []
        data = self._load_json("yield_forecast.json")
        snap = self._latest(data)

        if snap:
            # Try to get 7d and 30d forecasts
            f7  = snap.get("forecast_7d_apy")  or snap.get("apy_7d")  or snap.get("forecast_apy")
            f30 = snap.get("forecast_30d_apy") or snap.get("apy_30d") or None
            trend = snap.get("trend") or snap.get("direction") or "N/A"

            if f7 is not None:
                lines.append(f"7d forecast APY: {float(f7):.2f}%")
            if f30 is not None:
                lines.append(f"30d forecast APY: {float(f30):.2f}%")
            lines.append(f"Trend: {trend}")

            # Top adapter forecast if available
            adapters = snap.get("adapters") or snap.get("per_adapter") or {}
            if isinstance(adapters, dict) and adapters:
                top_id = max(adapters, key=lambda k: float(adapters[k]) if isinstance(adapters[k], (int, float)) else 0.0)
                top_apy = adapters[top_id]
                lines.append(f"Top: {top_id} @ {float(top_apy):.2f}%")
        else:
            lines.append("Forecast data unavailable")

        if not lines:
            lines.append("Forecast data unavailable")

        return DigestSection(title="Yield Forecast", emoji="🔮", lines=lines)

    # ------------------------------------------------------------------
    # Digest assembly
    # ------------------------------------------------------------------

    def build_digest(self, date_str: Optional[str] = None) -> str:
        """Assemble all sections into a single MarkdownV2 Telegram message.

        The message is hard-truncated at ``_MAX_MESSAGE_LEN`` characters
        with a trailing ``…`` if it exceeds the limit.

        Parameters
        ----------
        date_str : str, optional
            ISO date string for the header (defaults to today UTC).

        Returns
        -------
        str
            Fully formatted MarkdownV2 message.
        """
        if date_str is None:
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        sections = [
            self.build_portfolio_section(),
            self.build_alert_section(),
            self.build_starvation_section(),
            self.build_progress_section(),
            self.build_paper_trading_section(),
            self.build_forecast_section(),
        ]

        header = f"🤖 *SPA Daily Digest — {escape_mdv2(date_str)}*"
        divider = "─" * 28
        divider_escaped = escape_mdv2(divider)

        parts = [header, divider_escaped]
        for section in sections:
            parts.append(self._format_section(section))
            parts.append("")  # blank line between sections

        # Footer
        footer = escape_mdv2("Advisory only. Not financial advice.")
        parts.append(divider_escaped)
        parts.append(f"_{footer}_")

        message = "\n".join(parts)

        # Truncate to Telegram's hard limit
        if len(message) > _MAX_MESSAGE_LEN:
            message = message[: _MAX_MESSAGE_LEN - 1] + "…"

        return message

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_digest(
        self,
        bot_token: str,
        chat_id: str,
        date_str: Optional[str] = None,
    ) -> dict:
        """Send the digest via Telegram Bot API.

        Uses ``urllib.request.urlopen`` — no third-party libraries.

        Parameters
        ----------
        bot_token : str
            Telegram Bot API token (e.g. ``"123456:ABC-DEF..."``).
        chat_id : str
            Target chat / channel ID (e.g. ``"-1001234567890"``).
        date_str : str, optional
            Passed to :meth:`build_digest`.

        Returns
        -------
        dict with keys:
            * ``ok``          — bool
            * ``status_code`` — HTTP status code
            * ``message_id``  — int (if ok=True)
            * ``error``       — str (if ok=False)
        """
        # FLOOD-GUARD: route through the canonical rate-limited client so this
        # digest shares the cross-process flood guard. Transport only — same
        # MarkdownV2 message. The ``bot_token``/``chat_id`` args are kept for
        # signature compatibility; the canonical client re-resolves creds from
        # the Keychain (TELEGRAM_*_SPA). message_id is not exposed by the
        # canonical client (returns bool), so it is reported as None on success.
        # RETIRED (Phase-1 Telegram rebuild): this analytics digest no longer
        # pushes Telegram directly — its metrics are folded into the single
        # canonical daily message (``spa_core.telegram.reports.daily``) and the
        # on-demand analytics view. build_digest() still produces the text for
        # those consumers; no send occurs here.
        _ = self.build_digest(date_str=date_str)
        return {
            "ok": False,
            "status_code": 0,
            "error": "retired: use spa_core.telegram.reports.daily",
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_digest(
        self,
        digest_str: str,
        date_str: Optional[str] = None,
    ) -> str:
        """Save the digest text to ``data/telegram_digests/YYYY-MM-DD.txt``.

        Uses atomic write (tmp + ``os.replace``) so the file is never
        partially written.

        Parameters
        ----------
        digest_str : str
            The formatted digest string to save.
        date_str : str, optional
            ISO date string for the filename (defaults to today UTC).

        Returns
        -------
        str
            Absolute path to the written file.
        """
        if date_str is None:
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        dest_dir = self.data_dir / _DIGEST_SUBDIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{date_str}.txt"

        # Atomic write: write to a temp file in the same directory, then rename
        fd, tmp_path = tempfile.mkstemp(dir=str(dest_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(digest_str)
            os.replace(tmp_path, str(dest_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return str(dest_path.resolve())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="TelegramDailyDigest (MP-627) — advisory only"
    )
    parser.add_argument("--check", action="store_true", default=True,
                        help="Build and print digest (default)")
    parser.add_argument("--run", action="store_true",
                        help="Build, print, and save digest")
    parser.add_argument("--data-dir", default="data/",
                        help="Path to data directory (default: data/)")
    args = parser.parse_args(argv)

    digest_obj = TelegramDailyDigest(data_dir=args.data_dir)
    digest_str = digest_obj.build_digest()
    print(digest_str)

    if args.run:
        path = digest_obj.save_digest(digest_str)
        print(f"\nSaved to: {path}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
