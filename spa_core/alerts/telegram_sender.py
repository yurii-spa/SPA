"""
SPA Telegram Alerts — sends via Telegram Bot API.
Simpler than email: no SMTP, no app passwords.

Setup:
  1) Open Telegram → search @BotFather → /newbot → name it "SPA Alerts" → get token
  2) Message your new bot (any text) → open
     https://api.telegram.org/bot{TOKEN}/getUpdates → find chat.id
  3) Add GitHub secrets: SPA_TELEGRAM_TOKEN  and  SPA_TELEGRAM_CHAT_ID

Secrets: SPA_TELEGRAM_TOKEN, SPA_TELEGRAM_CHAT_ID
"""
import os
import logging
from spa_core.utils import clock

log = logging.getLogger("spa.alerts.telegram")

DASHBOARD_URL = "https://yuriiykulieshov.github.io/SPA_Claude/"


class TelegramSender:
    """
    Sends Telegram messages via the Bot API using only stdlib urllib.
    Never raises — all public methods return bool and swallow exceptions.
    """

    def __init__(self) -> None:
        self.token   = os.getenv("SPA_TELEGRAM_TOKEN", "").strip()
        self.chat_id = os.getenv("SPA_TELEGRAM_CHAT_ID", "").strip()
        self.available = bool(self.token and self.chat_id)
        if not self.available:
            log.debug("Telegram not configured — SPA_TELEGRAM_TOKEN / SPA_TELEGRAM_CHAT_ID not set.")

    # -----------------------------------------------------------------------
    # Core send
    # -----------------------------------------------------------------------

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        POST a message to the Telegram Bot API.
        Returns True on success, False on any failure. Never raises.
        """
        # RETIRED as a Telegram push (Phase-1 Telegram rebuild). telegram_sender
        # is superseded by push_policy (critical) + the digest builders. Routed
        # to the digest queue, never pushed. Always returns False. Never raises.
        try:
            from spa_core.telegram import push_policy
            push_policy.enqueue_digest(
                "telegram_sender", "Sender message", text,
                reason="telegram_sender_retired_push",
            )
        except Exception as exc:
            log.error(f"telegram_sender digest route error: {exc}")
        return False

    # -----------------------------------------------------------------------
    # Formatted senders
    # -----------------------------------------------------------------------

    def send_risk_alert(self, alerts: list[dict], portfolio: dict) -> bool:
        """
        Send a risk alert message when thresholds are breached.

        Example output:
            🚨 <b>SPA Risk Alert</b>

            ⚠️ <b>2 alert(s) detected</b>

            • CRITICAL: Maple concentration 48% > 45% limit
            • WARNING: Portfolio drawdown -2.1% approaching 5% kill switch

            💰 Portfolio: $100,138 | PnL: +$138 (+0.14%)
            📊 <a href="...">View Dashboard</a>
        """
        if not self.available:
            return False

        try:
            count     = len(alerts)
            total_val = portfolio.get("total_capital_usd", 0)
            pnl_usd   = portfolio.get("total_pnl_usd", 0)
            pnl_pct   = portfolio.get("total_pnl_pct", 0)
            pnl_sign  = "+" if pnl_usd >= 0 else ""

            # Alert lines
            lines = []
            for a in alerts:
                sev      = a.get("severity", "warning").upper()
                protocol = a.get("protocol", a.get("protocol_key", ""))
                message  = a.get("message", "")
                entry = f"• {sev}"
                if protocol:
                    entry += f": {protocol}"
                    if message:
                        entry += f" — {message}"
                elif message:
                    entry += f": {message}"
                lines.append(entry)

            alert_block = "\n".join(lines)

            text = (
                f"🚨 <b>SPA Risk Alert</b>\n"
                f"\n"
                f"⚠️ <b>{count} alert(s) detected</b>\n"
                f"\n"
                f"{alert_block}\n"
                f"\n"
                f"💰 Portfolio: ${total_val:,.0f} | PnL: {pnl_sign}${pnl_usd:,.0f} ({pnl_sign}{pnl_pct:.2f}%)\n"
                f'📊 <a href="{DASHBOARD_URL}">View Dashboard</a>'
            )
            return self.send(text)

        except Exception as exc:
            log.error(f"send_risk_alert failed: {exc}")
            return False

    def send_cycle_summary(self, portfolio: dict, positions: list[dict]) -> bool:
        """
        Send a compact 4-hour cycle summary.

        Example output:
            📊 <b>SPA 4h Report</b> · 16:00

            💰 $100,138 | <b>+0.14%</b>
            📈 APY: 4.35% weighted avg

            Positions:
            • Aave V3: $40K @4.23%
            • Compound: $35K @4.02%
            • Maple: $20K @4.80%

            🟢 No alerts | Cash: 5%
        """
        if not self.available:
            return False

        try:
            now_str   = clock.utcnow().strftime("%H:%M")
            total_val = portfolio.get("total_capital_usd", 0)
            pnl_pct   = portfolio.get("total_pnl_pct", 0)
            pnl_sign  = "+" if pnl_pct >= 0 else ""
            cash_usd  = portfolio.get("cash_usd", 0)
            invested  = portfolio.get("invested_usd", total_val)
            cash_pct  = round(cash_usd / total_val * 100) if total_val else 0

            # Weighted-average APY
            open_pos = [p for p in positions if p.get("status") == "open"]
            if open_pos and invested:
                w_apy = sum(
                    (p.get("current_apy", 0) or 0)
                    * (p.get("current_value_usd", p.get("entry_value_usd", 0)) or 0)
                    for p in open_pos
                ) / invested
            else:
                apys  = [p.get("current_apy", 0) or 0 for p in open_pos]
                w_apy = (sum(apys) / len(apys)) if apys else 0.0

            # Position lines (compact: $40K @4.23%)
            pos_lines = []
            for p in open_pos:
                name  = p.get("protocol_key", p.get("protocol", "?"))
                val   = p.get("current_value_usd", p.get("entry_value_usd", 0)) or 0
                apy   = p.get("current_apy", 0) or 0
                val_k = f"${val/1000:.0f}K" if val >= 1000 else f"${val:,.0f}"
                pos_lines.append(f"• {name}: {val_k} @{apy:.2f}%")

            pos_block = "\n".join(pos_lines) if pos_lines else "• (no open positions)"
            alert_status = "🟢 No alerts" if True else "🔴 Alerts active"  # caller can override

            text = (
                f"📊 <b>SPA 4h Report</b> · {now_str}\n"
                f"\n"
                f"💰 ${total_val:,.0f} | <b>{pnl_sign}{pnl_pct:.2f}%</b>\n"
                f"📈 APY: {w_apy:.2f}% weighted avg\n"
                f"\n"
                f"Positions:\n"
                f"{pos_block}\n"
                f"\n"
                f"{alert_status} | Cash: {cash_pct}%"
            )
            return self.send(text)

        except Exception as exc:
            log.error(f"send_cycle_summary failed: {exc}")
            return False

    def send_golive_update(self, readiness: dict) -> bool:
        """
        Send weekly go-live status update (suggested every Monday).

        Example output:
            🎯 <b>SPA Go-Live Update</b>

            Verdict: 🔴 NOT READY (5/8 criteria)
            Days remaining: 54

            ❌ Paper Duration: 1/50 days
            ✅ PnL: +$138
            ✅ No Critical Alerts
            [...]

            Next milestone: 2026-07-21
        """
        if not self.available:
            return False

        try:
            verdict       = readiness.get("verdict", "NOT_READY")
            verdict_emoji = readiness.get("verdict_emoji", "🔴")
            summary       = readiness.get("summary", "")
            days_remain   = readiness.get("days_remaining", "?")
            criteria      = readiness.get("criteria", [])
            next_milestone = readiness.get("next_milestone", "")

            # Criteria lines
            crit_lines = []
            for c in criteria:
                icon  = "✅" if c.get("passed") else "❌"
                label = c.get("label", c.get("name", "?"))
                value = c.get("value_str", c.get("current", ""))
                entry = f"{icon} {label}"
                if value:
                    entry += f": {value}"
                crit_lines.append(entry)

            crit_block = "\n".join(crit_lines) if crit_lines else "(no criteria data)"

            passed = sum(1 for c in criteria if c.get("passed"))
            total  = len(criteria)
            score  = f"{passed}/{total}" if total else summary

            text = (
                f"🎯 <b>SPA Go-Live Update</b>\n"
                f"\n"
                f"Verdict: {verdict_emoji} {verdict} ({score} criteria)\n"
                f"Days remaining: {days_remain}\n"
                f"\n"
                f"{crit_block}"
            )
            if next_milestone:
                text += f"\n\nNext milestone: {next_milestone}"

            return self.send(text)

        except Exception as exc:
            log.error(f"send_golive_update failed: {exc}")
            return False
