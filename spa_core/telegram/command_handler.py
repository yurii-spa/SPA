"""
spa_core/telegram/command_handler.py — MP-1492 (Sprint v11.08)

Telegram command handler for SPA bot.
Commands: /status, /golive, /apy, /evidence, /strategies, /help

Pure stdlib. Fail-safe: every handler catches all exceptions and returns
a human-readable error string (never raises to the caller).
LLM FORBIDDEN.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict

from spa_core.utils.atomic import atomic_load

log = logging.getLogger("spa.telegram.command_handler")

COMMANDS: Dict[str, str] = {
    "/status":     "system_status",
    "/golive":     "golive_score",
    "/apy":        "current_apy",
    "/evidence":   "evidence_progress",
    "/strategies": "strategy_tournament",
    "/help":       "help_text",
}


class CommandHandler:
    """Routes Telegram slash-commands to response builders.

    Usage::
        handler = CommandHandler(base_dir="/path/to/repo")
        text = handler.handle("/status")
        # → "🚀 SPA System Status\\nDone: 1185 tasks…"
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = base_dir

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle(self, command: str) -> str:
        """Routes command to appropriate handler. Returns response text.

        Unknown commands return help text. Exceptions are caught and
        returned as a user-friendly error string.
        """
        cmd = command.split()[0].lower() if command else "/help"
        handler_name = f"_cmd_{COMMANDS.get(cmd, 'help_text')}"
        handler: Callable[[], str] = getattr(self, handler_name, self._cmd_help_text)
        try:
            return handler()
        except Exception as exc:
            log.warning("Command %s failed: %s", cmd, exc)
            return f"❌ Error executing {cmd}: {exc}"

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_system_status(self) -> str:
        kanban = atomic_load(f"{self.base_dir}/KANBAN.json", default={})
        done = kanban.get("done_count", 0)
        sprint = kanban.get("sprint_completed", "?")

        # Try to get paper_trading_status
        status = atomic_load(f"{self.base_dir}/data/paper_trading_status.json", default={})
        capital = status.get("total_capital_usd", 100_000)
        pnl_pct = status.get("total_pnl_pct", 0.0)
        pnl_sign = "+" if pnl_pct >= 0 else ""

        return (
            f"🚀 SPA System Status\n"
            f"Done: {done} tasks\n"
            f"Sprint: {sprint}\n"
            f"Capital: ${capital:,.0f}\n"
            f"PnL: {pnl_sign}{pnl_pct:.2f}%\n"
            f"Paper Trading: IN_PROGRESS"
        )

    def _cmd_golive_score(self) -> str:
        try:
            from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport  # type: ignore

            r = GoLiveReadinessReport(self.base_dir)
            rep = r.generate_report()
            score = rep.get("total_score", 0)
            return (
                f"📊 GoLive Score: {score}/100\n"
                f"Status: {'ON_TRACK ✅' if score >= 80 else 'NEEDS_WORK ⚠️'}"
            )
        except Exception as exc:
            # Fallback: read golive_status.json directly
            status = atomic_load(f"{self.base_dir}/data/golive_status.json", default={})
            passed = status.get("passed", 0)
            total = status.get("total", 26)
            ready = status.get("ready", False)
            icon = "✅" if ready else "⚠️"
            return (
                f"📊 GoLive Checker: {passed}/{total} criteria\n"
                f"Status: {'READY ✅' if ready else 'NOT READY ⚠️'}"
            )

    def _cmd_current_apy(self) -> str:
        status = atomic_load(f"{self.base_dir}/data/paper_trading_status.json", default={})
        positions = status.get("positions", [])
        if not positions:
            pos_data = atomic_load(f"{self.base_dir}/data/current_positions.json", default={})
            positions = pos_data.get("positions", [])

        if not positions:
            return "📈 APY: no positions found"

        # Weighted average
        total_val = sum(p.get("current_value_usd", 0) for p in positions)
        if total_val > 0:
            w_apy = sum(
                p.get("current_apy", 0) * p.get("current_value_usd", 0)
                for p in positions
            ) / total_val
        else:
            apys = [p.get("current_apy", 0) for p in positions]
            w_apy = sum(apys) / len(apys) if apys else 0

        lines = [f"📈 Current APY (weighted avg: {w_apy:.2f}%)\n"]
        for p in positions[:5]:
            name = p.get("protocol_key", p.get("protocol", "?"))
            val = p.get("current_value_usd", 0)
            apy = p.get("current_apy", 0)
            lines.append(f"  • {name}: ${val:,.0f} @{apy:.2f}%")

        if len(positions) > 5:
            lines.append(f"  ... and {len(positions) - 5} more")

        return "\n".join(lines)

    def _cmd_evidence_progress(self) -> str:
        curve = atomic_load(
            f"{self.base_dir}/data/equity_curve_daily.json", default=[]
        )
        if isinstance(curve, dict):
            curve = curve.get("entries", [])

        days = len(curve)
        target_days = 30
        pct = min(100, int(days / target_days * 100))

        gap = atomic_load(f"{self.base_dir}/data/gap_monitor.json", default={})
        gaps = gap.get("gap_count", 0)
        continuity = "✅ continuous" if gaps == 0 else f"⚠️ {gaps} gap(s)"

        # Honest go-live target = the evidenced-anchored value the go-live checker
        # surfaces (data/golive_status.json target_date). Fail-safe to "pending".
        golive = atomic_load(f"{self.base_dir}/data/golive_status.json", default={})
        target = golive.get("target_date") if isinstance(golive, dict) else None

        return (
            f"🧾 Evidence Progress\n"
            f"Track days: {days}/{target_days} ({pct}%)\n"
            f"Continuity: {continuity}\n"
            f"Target go-live: {target or 'pending'}"
        )

    def _cmd_strategy_tournament(self) -> str:
        results = atomic_load(
            f"{self.base_dir}/data/tournament_results.json", default={}
        )
        strategies = results.get("strategies", results.get("results", {}))

        if not strategies:
            return "🏆 Tournament: no results available yet"

        lines = ["🏆 Strategy Tournament (top 5)\n"]
        sorted_strats = sorted(
            strategies.items(),
            key=lambda x: x[1].get("sharpe", 0) if isinstance(x[1], dict) else 0,
            reverse=True,
        )
        for i, (sid, data) in enumerate(sorted_strats[:5], 1):
            sharpe = data.get("sharpe", 0) if isinstance(data, dict) else 0
            apy = data.get("apy", 0) if isinstance(data, dict) else 0
            lines.append(f"  {i}. {sid}: Sharpe={sharpe:.2f} APY={apy:.1%}")

        return "\n".join(lines)

    def _cmd_help_text(self) -> str:
        return (
            "SPA Bot Commands:\n"
            "/status — system status & P&L\n"
            "/golive — readiness score (26 criteria)\n"
            "/apy — current yield by position\n"
            "/evidence — paper trading progress\n"
            "/strategies — tournament rankings\n"
            "/help — this message"
        )
