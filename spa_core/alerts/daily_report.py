"""
SPA Daily Report Builder — formats a Telegram HTML summary once per 24h.

Reads from data/ JSON files and produces a compact but complete daily digest
covering portfolio value, APY vs target, positions, risk alerts, analytics
stats, and go-live readiness.

Usage (called from export_data.py):
    builder = DailyReportBuilder(data_dir)
    if builder.should_send_daily():
        msg = builder.build_report()
        if sender.send(msg):
            builder.mark_sent()
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.alerts.daily_report")

# Paper-trading target APY from DEV_STRATEGY_v1.0
TARGET_APY = 7.30
PAPER_START_DATE = date(2026, 5, 20)
PAPER_TOTAL_DAYS = 56          # 8 weeks


def _html(text: str) -> str:
    """Escape HTML special characters so the message is safe in HTML parse_mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DailyReportBuilder:
    """
    Builds and rate-limits a once-per-day Telegram HTML message summarising
    portfolio state, APY gap, positions, risk alerts, analytics, and go-live.
    """

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        if data_dir is None:
            # spa_core/alerts/ → spa_core/ → repo_root/ → data/
            data_dir = Path(__file__).parent.parent.parent / "data"
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_report(self) -> str:
        """
        Return a Telegram HTML message (≤ 4000 chars) with the daily digest.
        Never raises — returns a minimal fallback on any error.
        """
        try:
            return self._build()
        except Exception as exc:
            log.error(f"DailyReportBuilder.build_report failed: {exc}", exc_info=True)
            today = date.today().isoformat()
            return f"📊 <b>SPA Daily Report — {today}</b>\n\n⚠️ Report generation error: {_html(str(exc))}"

    def should_send_daily(self, last_sent_file: Optional[str | Path] = None) -> bool:
        """
        Return True if the daily report has NOT yet been sent today (UTC).
        Uses a sentinel file that stores the last-sent ISO date.
        """
        sentinel = self._sentinel_path(last_sent_file)
        today = date.today().isoformat()
        try:
            if sentinel.exists():
                stored = sentinel.read_text(encoding="utf-8").strip()
                return stored != today
        except Exception as exc:
            log.warning(f"should_send_daily: could not read sentinel {sentinel}: {exc}")
        return True

    def mark_sent(self, last_sent_file: Optional[str | Path] = None) -> None:
        """Write today's ISO date to the sentinel file."""
        sentinel = self._sentinel_path(last_sent_file)
        try:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(date.today().isoformat(), encoding="utf-8")
        except Exception as exc:
            log.warning(f"mark_sent: could not write sentinel {sentinel}: {exc}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sentinel_path(self, last_sent_file) -> Path:
        if last_sent_file is None:
            return self.data_dir / ".last_report_sent"
        p = Path(last_sent_file)
        if not p.is_absolute():
            return self.data_dir / last_sent_file
        return p

    def _load(self, filename: str) -> dict:
        """Load a JSON file from data_dir; return {} on any error."""
        path = self.data_dir / filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug(f"_load({filename}): {exc}")
            return {}

    def _build(self) -> str:
        status       = self._load("status.json")
        pnl_hist     = self._load("pnl_history.json")
        risk_data    = self._load("risk_alerts.json")
        analytics    = self._load("advanced_analytics.json")
        golive       = self._load("golive_readiness.json")

        # ---- portfolio -----------------------------------------------
        portfolio  = status.get("portfolio", {})
        positions  = status.get("positions", [])
        total_val  = portfolio.get("total_capital_usd", 100_000.0) or 100_000.0
        pnl_usd    = portfolio.get("total_pnl_usd", 0.0) or 0.0
        cash_usd   = portfolio.get("cash_usd", total_val) or 0.0
        deployed   = portfolio.get("deployed_usd", 0.0) or 0.0

        # pnl % — prefer direct field, fall back to compute
        pnl_pct    = portfolio.get("total_pnl_pct", None)
        if pnl_pct is None:
            initial = 100_000.0
            pnl_pct = (pnl_usd / initial * 100) if initial else 0.0
        else:
            # stored as fraction (0.001) or percent (0.1)?
            if abs(pnl_pct) < 1 and abs(pnl_pct) > 0:
                pnl_pct = pnl_pct * 100   # was stored as fraction

        pnl_sign   = "+" if pnl_usd >= 0 else ""
        pct_sign   = "+" if pnl_pct >= 0 else ""

        # ---- weighted APY from open positions -----------------------
        open_pos   = [p for p in positions if p.get("status", "open") in ("open", None, "")]
        # Also treat positions without explicit status as open
        if not open_pos:
            open_pos = positions

        w_apy = 0.0
        if open_pos and deployed > 0:
            w_apy = sum(
                (p.get("current_apy") or 0.0) * (p.get("amount_usd") or 0.0)
                for p in open_pos
            ) / deployed
        elif open_pos:
            apys = [p.get("current_apy") or 0.0 for p in open_pos if p.get("current_apy")]
            w_apy = sum(apys) / len(apys) if apys else 0.0

        gap   = w_apy - TARGET_APY
        gap_s = f"{gap:+.2f}%"

        # ---- paper trading day counter ------------------------------
        today          = date.today()
        days_elapsed   = (today - PAPER_START_DATE).days
        days_elapsed   = max(0, days_elapsed)

        # ---- risk alerts -------------------------------------------
        alerts      = risk_data.get("alerts", [])
        alert_count = risk_data.get("count", len(alerts))
        crit_count  = sum(1 for a in alerts if a.get("severity") == "critical")
        alert_label = f"{crit_count} critical" if crit_count else f"{alert_count} total" if alert_count else "0 critical"

        # ---- advanced analytics ------------------------------------
        summary   = analytics.get("summary", {})
        sharpe    = summary.get("sharpe_ratio", None)
        max_dd    = summary.get("max_drawdown_pct", None)
        # Fallback to strategy state sharpe / drawdown
        strat     = status.get("strategy", {})
        if sharpe is None:
            sharpe = strat.get("sharpe_to_date", None) or 0.0
        if max_dd is None:
            raw_dd = portfolio.get("total_drawdown_pct", None) or 0.0
            # total_drawdown_pct is stored as a fraction (e.g. 0.012 = 1.2%)
            max_dd = raw_dd * 100 if abs(raw_dd) <= 1.0 else raw_dd
        elif abs(max_dd) <= 1.0 and max_dd != 0.0:
            # advanced_analytics may also store as fraction
            max_dd = max_dd * 100

        # ---- go-live -----------------------------------------------
        verdict      = golive.get("verdict", "NOT_READY")
        gl_summary   = golive.get("summary", "")
        # extract "X/Y criteria" from summary string
        criteria_str = ""
        if gl_summary:
            # e.g. "5/8 criteria passing; ..."
            import re
            m = re.search(r"(\d+/\d+)\s+criteria", gl_summary)
            criteria_str = f" ({m.group(1)} criteria)" if m else ""
        verdict_emoji = golive.get("verdict_emoji", "🔴")

        # ---- position lines -----------------------------------------
        pos_lines = []
        for p in open_pos[:6]:   # cap at 6 to keep message concise
            name    = _html(p.get("protocol", p.get("protocol_key", "?")))
            amt     = p.get("amount_usd") or 0.0
            apy     = p.get("current_apy") or 0.0
            pos_lines.append(f"  {name:<22} ${amt:>10,.0f}  {apy:.2f}% APY")

        if not pos_lines:
            pos_lines.append("  (no open positions — deploying capital)")

        cash_pct = cash_usd / total_val * 100 if total_val else 0.0
        pos_lines.append(f"  {'Cash buffer':<22} ${cash_usd:>10,.0f}  ({cash_pct:.1f}%)")

        # ---- assemble -----------------------------------------------
        report_date = today.isoformat()
        lines = [
            f"📊 <b>SPA Daily Report — {report_date}</b>",
            "",
            f"💰 Portfolio: ${total_val:,.0f} ({pct_sign}{pnl_pct:.2f}% / {pnl_sign}${pnl_usd:,.0f})",
            f"📈 APY (weighted): {w_apy:.2f}%  Target: {TARGET_APY:.2f}%",
            f"🎯 Gap: {gap_s}",
            "",
            "📍 Positions:",
        ]
        lines.extend(pos_lines)
        lines += [
            "",
            f"⚠️  Risk Alerts: {_html(alert_label)}",
            f"📊 Sharpe: {sharpe:.2f}  MaxDD: {max_dd:.1f}%",
            "",
            f"⏱  Paper trading: Day {days_elapsed}/{PAPER_TOTAL_DAYS}",
            f"{verdict_emoji} Go-live: {_html(verdict)}{_html(criteria_str)}",
        ]

        msg = "\n".join(lines)

        # Hard cap at 4000 chars (Telegram limit)
        if len(msg) > 4000:
            msg = msg[:3990] + "\n…"

        return msg
