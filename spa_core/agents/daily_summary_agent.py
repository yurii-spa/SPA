#!/usr/bin/env python3
"""Daily Performance Summary Agent (MP-1578 / Improvement 3).

Runs once per day (intended at 08:00 UTC, after the daily cycle) and produces
a single human-readable performance digest of the paper-trading track, then:

  * sends it to Telegram (HTML formatting, reusing the existing bot creds), and
  * persists it to ``data/daily_summaries/YYYY-MM-DD.json``.

Inputs (all read-only, all fail-safe)
=====================================
  * ``equity_curve_daily.json``     → equity, returns, drawdown, day count
  * ``tournament_results.json``     → best / worst strategy
  * ``golive_status.json``          → go-live readiness + blockers
  * ``paper_trading_status.json``   → APY today, kill-switch, positions

Output summary dict keys
========================
  ``date, day_N, equity, paper_apy, total_return_pct, best_strategy,
  worst_strategy, golive_status, golive_ready, key_risks``

Design / safety
===============
* STRICTLY READ-ONLY / ADVISORY. Reads JSON, sends a message, writes its own
  summary file. Touches NO allocator / risk / execution state and NO capital.
* Stdlib only. Telegram via the existing ``spa_core.telegram.bot`` (urllib).
* No LLM (this is a reporting agent, but kept LLM-free — deterministic
  formatting only; safe and reproducible).
* Fail-safe: a missing input degrades to safe defaults; a Telegram failure is
  reported (``telegram_sent=False``) but never raises. The summary is still
  written.

CLI
===
    python3 -m spa_core.agents.daily_summary_agent --check        # build + print only
    python3 -m spa_core.agents.daily_summary_agent --run          # + save + telegram
    python3 -m spa_core.agents.daily_summary_agent --run --no-telegram
    python3 -m spa_core.agents.daily_summary_agent --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Drawdown magnitude (%) above which we flag it as a key risk.
DRAWDOWN_RISK_PCT = 2.0
# Single-position weight (%) above which we flag concentration as a key risk.
CONCENTRATION_RISK_PCT = 38.0


# ─── IO helpers (fail-safe) ─────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("daily_summary: unreadable %s (%s)", path, exc)
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─── Strategy ranking ───────────────────────────────────────────────────────


def _rank_strategies(tournament: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{best, worst}`` strategy descriptors from tournament results.

    Sorts by ``net_apy`` primarily; when all net_apy are equal (e.g. 0.0 early
    in the track) falls back to ``composite_score``. Returns empty descriptors
    if there are no strategies.
    """
    strategies = []
    if isinstance(tournament, dict):
        strategies = tournament.get("strategies") or []
    strategies = [s for s in strategies if isinstance(s, dict)]
    if not strategies:
        empty = {"strategy_id": None, "net_apy": 0.0, "composite_score": 0.0}
        return {"best": dict(empty), "worst": dict(empty)}

    def _key(s: Dict[str, Any]):
        return (_coerce_float(s.get("net_apy")), _coerce_float(s.get("composite_score")))

    ordered = sorted(strategies, key=_key, reverse=True)
    best = ordered[0]
    worst = ordered[-1]

    def _desc(s: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_id": s.get("strategy_id"),
            "net_apy": round(_coerce_float(s.get("net_apy")), 4),
            "composite_score": round(_coerce_float(s.get("composite_score")), 6),
        }

    return {"best": _desc(best), "worst": _desc(worst)}


def _max_position_pct(positions: Dict[str, Any]) -> float:
    if not isinstance(positions, dict) or not positions:
        return 0.0
    vals = [_coerce_float(v) for v in positions.values() if _coerce_float(v) > 0]
    total = sum(vals)
    if total <= 0:
        return 0.0
    return max(vals) / total * 100.0


def _derive_key_risks(
    status: Dict[str, Any],
    equity: Dict[str, Any],
    golive: Dict[str, Any],
) -> List[str]:
    """Deterministic list of human-readable key risks. Empty list = all clear."""
    risks: List[str] = []

    # kill-switch
    if isinstance(status, dict) and status.get("kill_switch_active"):
        reason = status.get("kill_switch_reason") or "active"
        risks.append(f"Kill switch active: {reason}")

    # drawdown (prefer summary roll-up)
    dd = 0.0
    summ = equity.get("summary") if isinstance(equity, dict) else None
    if isinstance(summ, dict):
        dd = abs(_coerce_float(summ.get("max_drawdown_pct")))
    if dd > DRAWDOWN_RISK_PCT:
        risks.append(f"Max drawdown {dd:.2f}% exceeds {DRAWDOWN_RISK_PCT:.1f}%")

    # concentration
    positions = status.get("current_positions") if isinstance(status, dict) else None
    max_pos = _max_position_pct(positions or {})
    if max_pos > CONCENTRATION_RISK_PCT:
        risks.append(f"Concentration {max_pos:.1f}% near 40% cap")

    # go-live blockers
    if isinstance(golive, dict):
        blockers = golive.get("blockers") or []
        for b in blockers:
            risks.append(f"GoLive blocker: {b}")

    return risks


# ─── The agent ──────────────────────────────────────────────────────────────


class DailySummaryAgent:
    """Builds, formats, sends and persists the daily performance summary."""

    AGENT_ID = "daily_summary_agent"

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        sender: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        # ``sender`` lets tests inject a fake; default lazily builds a TelegramBot.
        self._sender = sender

    # -- build ----------------------------------------------------------------

    def build_summary(self) -> Dict[str, Any]:
        equity = _read_json(self.data_dir / "equity_curve_daily.json", {})
        tournament = _read_json(self.data_dir / "tournament_results.json", {})
        golive = _read_json(self.data_dir / "golive_status.json", {})
        status = _read_json(self.data_dir / "paper_trading_status.json", {})

        summ = equity.get("summary") if isinstance(equity, dict) else {}
        summ = summ if isinstance(summ, dict) else {}

        day_n = 0
        if isinstance(status, dict) and status.get("days_running") is not None:
            day_n = int(_coerce_float(status.get("days_running")))
        elif summ.get("num_days") is not None:
            day_n = int(_coerce_float(summ.get("num_days")))

        ranked = _rank_strategies(tournament)

        # equity: prefer live status, fall back to equity-curve close
        equity_val = None
        if isinstance(status, dict):
            equity_val = status.get("current_equity")
        if equity_val is None:
            equity_val = summ.get("end_equity")

        golive_ready = bool(golive.get("ready")) if isinstance(golive, dict) else False
        golive_passed = golive.get("passed") if isinstance(golive, dict) else None
        golive_total = golive.get("total") if isinstance(golive, dict) else None
        if golive_passed is not None and golive_total is not None:
            golive_status = f"{golive_passed}/{golive_total} {'READY' if golive_ready else 'NOT READY'}"
        else:
            golive_status = "READY" if golive_ready else "UNKNOWN"

        return {
            "date": _today_str(),
            "day_N": day_n,
            "equity": round(_coerce_float(equity_val), 2),
            "paper_apy": round(_coerce_float(
                status.get("apy_today_pct") if isinstance(status, dict) else None), 4),
            "total_return_pct": round(_coerce_float(summ.get("total_return_pct")), 4),
            "daily_return_pct": round(_coerce_float(
                status.get("daily_return_pct") if isinstance(status, dict) else None), 4),
            "best_strategy": ranked["best"],
            "worst_strategy": ranked["worst"],
            "golive_status": golive_status,
            "golive_ready": golive_ready,
            "key_risks": _derive_key_risks(
                status if isinstance(status, dict) else {},
                equity if isinstance(equity, dict) else {},
                golive if isinstance(golive, dict) else {},
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -- format ---------------------------------------------------------------

    @staticmethod
    def format_telegram(summary: Dict[str, Any]) -> str:
        """Render an HTML Telegram message. parse_mode=HTML (escapes '_')."""
        best = summary.get("best_strategy") or {}
        worst = summary.get("worst_strategy") or {}
        risks = summary.get("key_risks") or []
        ready_icon = "✅" if summary.get("golive_ready") else "❌"

        lines = [
            f"<b>📊 SPA Daily Summary — Day {summary.get('day_N', 0)}</b>",
            f"<i>{summary.get('date', '')}</i>",
            "",
            f"💰 Equity: <b>${summary.get('equity', 0):,.2f}</b>",
            f"📈 APY today: <b>{summary.get('paper_apy', 0):.2f}%</b>",
            f"📊 Total return: <b>{summary.get('total_return_pct', 0):+.2f}%</b>",
            "",
            f"🏆 Best: <b>{best.get('strategy_id', '—')}</b> "
            f"(APY {best.get('net_apy', 0):.2f}%, score {best.get('composite_score', 0):.3f})",
            f"🔻 Worst: <b>{worst.get('strategy_id', '—')}</b> "
            f"(APY {worst.get('net_apy', 0):.2f}%, score {worst.get('composite_score', 0):.3f})",
            "",
            f"{ready_icon} GoLive: <b>{summary.get('golive_status', 'UNKNOWN')}</b>",
        ]
        if risks:
            lines.append("")
            lines.append("<b>⚠️ Key risks:</b>")
            for r in risks:
                lines.append(f"• {r}")
        else:
            lines.append("")
            lines.append("✅ No key risks flagged.")
        return "\n".join(lines)

    # -- send -----------------------------------------------------------------

    def _default_sender(self, text: str) -> bool:
        try:
            from spa_core.telegram.bot import TelegramBot
            bot = TelegramBot()
            if not bot.token or not bot.chat_id:
                log.warning("daily_summary: no Telegram creds — skipping send")
                return False
            resp = bot.send_message(text, parse_mode="HTML")
            return bool(resp and resp.get("ok"))
        except Exception as exc:  # noqa: BLE001 — never crash on Telegram
            log.warning("daily_summary: telegram send failed (%s)", exc)
            return False

    def send_telegram(self, summary: Dict[str, Any]) -> bool:
        text = self.format_telegram(summary)
        sender = self._sender or self._default_sender
        try:
            return bool(sender(text))
        except Exception as exc:  # noqa: BLE001
            log.warning("daily_summary: sender raised (%s)", exc)
            return False

    # -- persist --------------------------------------------------------------

    def save(self, summary: Dict[str, Any]) -> Path:
        out_dir = self.data_dir / "daily_summaries"
        out_path = out_dir / f"{summary.get('date', _today_str())}.json"
        atomic_save(summary, str(out_path))
        return out_path

    # -- orchestrate ----------------------------------------------------------

    def run(self, *, send: bool = True, write: bool = True) -> Dict[str, Any]:
        summary = self.build_summary()
        telegram_sent = False
        if send:
            telegram_sent = self.send_telegram(summary)
        if write:
            try:
                self.save(summary)
            except OSError as exc:
                log.warning("daily_summary: save failed (%s)", exc)
        result = dict(summary)
        result["telegram_sent"] = telegram_sent
        return result


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="daily_summary_agent",
        description="Daily paper-trading performance summary (read-only).",
    )
    parser.add_argument("--run", action="store_true",
                        help="build + save + telegram")
    parser.add_argument("--check", action="store_true",
                        help="build + print only (no save, no telegram)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="with --run: save but skip Telegram")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    agent = DailySummaryAgent(data_dir=Path(args.data_dir) if args.data_dir else None)

    if args.run:
        result = agent.run(send=not args.no_telegram, write=True)
        print(agent.format_telegram(result))
        print(f"\n(telegram_sent={result.get('telegram_sent')}, saved daily_summaries/)")
    else:
        summary = agent.build_summary()
        print(agent.format_telegram(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
