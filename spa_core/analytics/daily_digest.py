"""
DailyDigest (MP-587)
====================

Assembles a single daily digest of portfolio state from all available
analytics JSON files.  Designed as a **read-mostly** module: its only
disk write is the atomic save of the digest ring-buffer.

Source files consumed (all optional — missing files are silently skipped):

    data/monitor_snapshots.json      — portfolio health & active alerts
    data/apy_forecasts.json          — per-adapter APY forecasts
    data/scenario_report.json        — worst-case scenario simulation
    data/attribution_report.json     — Brinson performance attribution
    data/risk_budget_report.json     — risk-budget contributions & BREACHes
    data/withdrawal_history.json     — completed withdrawal log
    data/progress_tracker.json       — days-to-go-live tracker

Output file (ring-buffer 30 days):

    data/daily_digest.json

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Read-only except :meth:`save_digest` which writes atomically
  (tmp + ``os.replace``) to ``data/daily_digest.json``.
* Never raises on the happy path; all data-load failures degrade
  gracefully (key absent → use safe defaults).
* Telegram message ≤ 4 000 characters (hard-truncated with ellipsis).

Public API
----------
``DailyDigest(data_dir: str = "data")``

Methods:
    - ``collect_data(date_str=None)`` → dict
    - ``build_summary(data)`` → dict
    - ``format_telegram_message(summary)`` → str
    - ``save_digest(summary)`` → str  (path written)
    - ``run(date_str=None)`` → dict

CLI
---
``python3 -m spa_core.analytics.daily_digest --check``   (default, no write)
``python3 -m spa_core.analytics.daily_digest --run``     (+ atomic save)
``python3 -m spa_core.analytics.daily_digest --data-dir PATH``
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIGEST_FILENAME: str = "daily_digest.json"
RING_BUFFER_SIZE: int = 30          # keep last 30 daily digests

# Source file names
_SRC_MONITOR    = "monitor_snapshots.json"
_SRC_FORECASTS  = "apy_forecasts.json"
_SRC_SCENARIO   = "scenario_report.json"
_SRC_ATTRIBUTION = "attribution_report.json"
_SRC_RISK_BUDGET = "risk_budget_report.json"
_SRC_WITHDRAWAL  = "withdrawal_history.json"
_SRC_PROGRESS    = "progress_tracker.json"

# Risk-budget status sentinel
_STATUS_BREACH = "BREACH"

# Telegram hard limit (characters)
_TELEGRAM_MAX_CHARS: int = 4000
_TELEGRAM_ELLIPSIS: str  = "…"  # "…"

# Portfolio health levels derived from monitor summary_level
_HEALTH_OK       = "OK"
_HEALTH_WARN     = "WARNING"
_HEALTH_CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# DailyDigest
# ---------------------------------------------------------------------------

class DailyDigest:
    """Assemble a daily portfolio digest from all analytics JSON data files.

    Parameters
    ----------
    data_dir:
        Path to the ``data/`` directory.  Defaults to ``"data"`` (relative
        to the current working directory).
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # 1. collect_data
    # ------------------------------------------------------------------

    def collect_data(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Load all available analytics JSON files from *data_dir*.

        Files that are absent, empty, or malformed are silently skipped;
        their key is set to ``None`` in the returned dict.

        Parameters
        ----------
        date_str:
            ISO-8601 date string (``"YYYY-MM-DD"``) to attach to the
            collected snapshot.  Defaults to today's UTC date.

        Returns
        -------
        dict with keys:
            ``date``, ``monitor``, ``forecasts``, ``scenario``,
            ``attribution``, ``risk_budget``, ``withdrawal``,
            ``progress``
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return {
            "date":        date_str,
            "monitor":     self._load_json(_SRC_MONITOR),
            "forecasts":   self._load_json(_SRC_FORECASTS),
            "scenario":    self._load_json(_SRC_SCENARIO),
            "attribution": self._load_json(_SRC_ATTRIBUTION),
            "risk_budget": self._load_json(_SRC_RISK_BUDGET),
            "withdrawal":  self._load_json(_SRC_WITHDRAWAL),
            "progress":    self._load_json(_SRC_PROGRESS),
        }

    # ------------------------------------------------------------------
    # 2. build_summary
    # ------------------------------------------------------------------

    def build_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Build a structured summary dict from *data* (as returned by
        :meth:`collect_data`).

        Parameters
        ----------
        data:
            Collected data dict.

        Returns
        -------
        dict with keys:
            ``date``               — str: YYYY-MM-DD
            ``generated_at``       — str: ISO-8601 UTC timestamp
            ``portfolio_health``   — str: OK / WARNING / CRITICAL / UNKNOWN
            ``equity_usd``         — float: current portfolio equity (or 0.0)
            ``apy_today_pct``      — float: today's APY % (from progress)
            ``top_opportunities``  — list[dict]: top-3 adapters by forecast APY
            ``risk_flags``         — list[str]: adapter IDs with BREACH status
            ``scenario_worst_case``— dict: worst-case scenario summary (or {})
            ``active_alerts``      — int: count of current alerts
            ``days_to_golive``     — int | None: days until go-live target
            ``attribution_active`` — bool: True when attribution data available
            ``total_active_return``— float: cumulative active return (or 0.0)
            ``withdrawal_count``   — int: total completed withdrawals logged
            ``paper_days``         — int: days of real track record
            ``summary_verdict``    — str: on_track / behind / unknown
        """
        date_str      = data.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        generated_at  = datetime.now(timezone.utc).isoformat()

        # --- portfolio health + equity + active alerts (monitor) ------
        portfolio_health, equity_usd, active_alerts = self._extract_monitor(
            data.get("monitor")
        )

        # --- apy_today_pct, days_to_golive, paper_days, summary_verdict
        apy_today_pct, days_to_golive, paper_days, summary_verdict = (
            self._extract_progress(data.get("progress"))
        )

        # --- top opportunities (forecasts) ----------------------------
        top_opportunities = self._extract_top_opportunities(
            data.get("forecasts"), n=3
        )

        # --- risk flags (risk_budget BREACHes) -------------------------
        risk_flags = self._extract_risk_flags(data.get("risk_budget"))

        # --- scenario worst case --------------------------------------
        scenario_worst_case = self._extract_worst_case(data.get("scenario"))

        # --- attribution ---------------------------------------------
        attribution_active, total_active_return = self._extract_attribution(
            data.get("attribution")
        )

        # --- withdrawal count ----------------------------------------
        withdrawal_count = self._extract_withdrawal_count(
            data.get("withdrawal")
        )

        return {
            "date":                date_str,
            "generated_at":        generated_at,
            "portfolio_health":    portfolio_health,
            "equity_usd":          equity_usd,
            "apy_today_pct":       apy_today_pct,
            "top_opportunities":   top_opportunities,
            "risk_flags":          risk_flags,
            "scenario_worst_case": scenario_worst_case,
            "active_alerts":       active_alerts,
            "days_to_golive":      days_to_golive,
            "attribution_active":  attribution_active,
            "total_active_return": total_active_return,
            "withdrawal_count":    withdrawal_count,
            "paper_days":          paper_days,
            "summary_verdict":     summary_verdict,
        }

    # ------------------------------------------------------------------
    # 3. format_telegram_message
    # ------------------------------------------------------------------

    def format_telegram_message(self, summary: Dict[str, Any]) -> str:
        """Build a Telegram-friendly digest message from *summary*.

        The message is hard-capped at 4 000 characters (Telegram limit).

        Parameters
        ----------
        summary:
            Dict as returned by :meth:`build_summary`.

        Returns
        -------
        str — plain-text message with emoji markers, ≤ 4 000 chars.
        """
        date_str       = summary.get("date", "N/A")
        health         = summary.get("portfolio_health", "UNKNOWN")
        equity         = summary.get("equity_usd", 0.0)
        apy            = summary.get("apy_today_pct", 0.0)
        alerts         = summary.get("active_alerts", 0)
        days_gl        = summary.get("days_to_golive")
        paper_days     = summary.get("paper_days", 0)
        risk_flags     = summary.get("risk_flags", [])
        top_opp        = summary.get("top_opportunities", [])
        worst          = summary.get("scenario_worst_case", {})
        verdict        = summary.get("summary_verdict", "unknown")
        attribution    = summary.get("attribution_active", False)
        active_return  = summary.get("total_active_return", 0.0)
        withdrawals    = summary.get("withdrawal_count", 0)

        # Health emoji
        health_emoji = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(
            health, "❓"
        )
        verdict_emoji = {"on_track": "🟢", "behind": "🔴"}.get(verdict, "🟡")

        lines: List[str] = []
        lines.append(f"📊 *SPA Daily Digest — {date_str}*")
        lines.append("")
        lines.append(f"{health_emoji} *Portfolio Health:* {health}")
        lines.append(f"💰 *Equity:* ${equity:,.2f}")
        lines.append(f"📈 *APY Today:* {apy:.2f}%")
        lines.append(f"🔔 *Active Alerts:* {alerts}")
        lines.append("")

        # Go-live tracker
        if days_gl is not None:
            lines.append(f"🎯 *Go-Live:* {days_gl}d remaining  |  Track: {paper_days}d")
        else:
            lines.append(f"🗓️ *Track Record:* {paper_days} day(s)")
        lines.append(f"{verdict_emoji} *Verdict:* {verdict}")
        lines.append("")

        # Top opportunities
        if top_opp:
            lines.append("🏆 *Top Opportunities (APY Forecast):*")
            for i, opp in enumerate(top_opp, 1):
                adapter_id  = opp.get("adapter_id", "?")
                fcast_apy   = opp.get("forecast_apy", 0.0)
                confidence  = opp.get("confidence", "?")
                lines.append(
                    f"  {i}. {adapter_id} — {fcast_apy:.2f}% ({confidence})"
                )
            lines.append("")

        # Risk flags
        if risk_flags:
            lines.append(f"🚩 *Risk Flags (BREACH):* {', '.join(risk_flags)}")
            lines.append("")

        # Worst-case scenario
        if worst:
            sc_name   = worst.get("scenario_name", "?")
            sc_return = worst.get("portfolio_return_pct", 0.0)
            lines.append(
                f"📉 *Worst Scenario:* {sc_name} → {sc_return:.2f}%"
            )
            lines.append("")

        # Attribution
        if attribution:
            sign = "+" if active_return >= 0 else ""
            lines.append(
                f"📐 *Attribution:* Active return {sign}{active_return:.4f}"
            )
            lines.append("")

        # Withdrawals
        if withdrawals > 0:
            lines.append(f"💸 *Withdrawals Logged:* {withdrawals}")
            lines.append("")

        lines.append("─" * 30)
        lines.append("_SPA — Smart Passive Aggregator (paper mode)_")

        msg = "\n".join(lines)

        # Hard-cap at Telegram limit
        if len(msg) > _TELEGRAM_MAX_CHARS:
            cutoff = _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)
            msg = msg[:cutoff] + _TELEGRAM_ELLIPSIS

        return msg

    # ------------------------------------------------------------------
    # 4. save_digest
    # ------------------------------------------------------------------

    def save_digest(self, summary: Dict[str, Any]) -> str:
        """Atomically append *summary* to the digest ring-buffer file.

        Creates ``data_dir`` if it does not exist.  Maintains a ring-buffer
        of :data:`RING_BUFFER_SIZE` digests (oldest evicted first).
        Uses ``tmp-file + os.replace`` for crash safety.

        Parameters
        ----------
        summary:
            The dict produced by :meth:`build_summary`.

        Returns
        -------
        str — absolute path of the written file.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.data_dir / DIGEST_FILENAME

        # Load existing ring-buffer
        history: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                history = existing.get("history", [])
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, OSError):
                history = []

        history.append(summary)
        if len(history) > RING_BUFFER_SIZE:
            history = history[-RING_BUFFER_SIZE:]

        payload = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "digest_count": len(history),
            "history":      history,
        }

        atomic_save(payload, str(out_path))
        return str(out_path.resolve())

    # ------------------------------------------------------------------
    # 5. run
    # ------------------------------------------------------------------

    def run(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Full pipeline: collect → build → save → return summary.

        Parameters
        ----------
        date_str:
            Optional ISO-8601 date (``"YYYY-MM-DD"``).  Defaults to today.

        Returns
        -------
        dict — the summary produced by :meth:`build_summary`.
        """
        data    = self.collect_data(date_str=date_str)
        summary = self.build_summary(data)
        self.save_digest(summary)
        return summary

    # ==================================================================
    # Private helpers
    # ==================================================================

    def _load_json(self, filename: str) -> Any:
        """Load and parse *filename* from :attr:`data_dir`.

        Returns ``None`` on any error (missing file, empty, malformed JSON).
        """
        path = self.data_dir / filename
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    # --- monitor -------------------------------------------------------

    def _extract_monitor(
        self, monitor_data: Any
    ) -> tuple:
        """Return (portfolio_health, equity_usd, active_alerts).

        *monitor_data* is either:
        * A list of snapshot dicts (most-recent = last element), or
        * A single snapshot dict.
        """
        portfolio_health = "UNKNOWN"
        equity_usd       = 0.0
        active_alerts    = 0

        if not monitor_data:
            return portfolio_health, equity_usd, active_alerts

        # Accept list (ring-buffer) or single dict
        snapshot: Any = None
        if isinstance(monitor_data, list):
            if monitor_data:
                snapshot = monitor_data[-1]
        elif isinstance(monitor_data, dict):
            snapshot = monitor_data

        if not isinstance(snapshot, dict):
            return portfolio_health, equity_usd, active_alerts

        # health from summary_level
        level = snapshot.get("summary_level", "")
        if isinstance(level, str):
            level_up = level.upper()
            if level_up == "OK":
                portfolio_health = _HEALTH_OK
            elif "WARN" in level_up:
                portfolio_health = _HEALTH_WARN
            elif "CRIT" in level_up:
                portfolio_health = _HEALTH_CRITICAL
            elif level_up:
                portfolio_health = level_up

        # equity
        raw_eq = snapshot.get("equity", 0.0)
        try:
            equity_usd = float(raw_eq)
        except (TypeError, ValueError):
            equity_usd = 0.0

        # alerts count
        alerts = snapshot.get("alerts", [])
        if isinstance(alerts, list):
            active_alerts = len(alerts)
        elif isinstance(alerts, int):
            active_alerts = alerts

        return portfolio_health, equity_usd, active_alerts

    # --- progress_tracker ----------------------------------------------

    def _extract_progress(self, progress_data: Any) -> tuple:
        """Return (apy_today_pct, days_to_golive, paper_days, summary_verdict)."""
        apy_today_pct  = 0.0
        days_to_golive: Optional[int] = None
        paper_days     = 0
        summary_verdict = "unknown"

        if not isinstance(progress_data, dict):
            return apy_today_pct, days_to_golive, paper_days, summary_verdict

        try:
            apy_today_pct = float(progress_data.get("apy_today_pct", 0.0))
        except (TypeError, ValueError):
            apy_today_pct = 0.0

        raw_dtg = progress_data.get("days_to_golive")
        if raw_dtg is not None:
            try:
                days_to_golive = int(raw_dtg)
            except (TypeError, ValueError):
                days_to_golive = None

        try:
            paper_days = int(progress_data.get("paper_days", 0))
        except (TypeError, ValueError):
            paper_days = 0

        sv = progress_data.get("summary_verdict", "unknown")
        summary_verdict = sv if isinstance(sv, str) else "unknown"

        return apy_today_pct, days_to_golive, paper_days, summary_verdict

    # --- apy_forecasts -------------------------------------------------

    def _extract_top_opportunities(
        self, forecasts_data: Any, n: int = 3
    ) -> List[Dict[str, Any]]:
        """Return top-N adapters sorted by forecast_apy descending."""
        if not isinstance(forecasts_data, dict):
            return []

        forecasts_dict = forecasts_data.get("forecasts", {})
        if not isinstance(forecasts_dict, dict):
            return []

        candidates: List[Dict[str, Any]] = []
        for adapter_id, fc in forecasts_dict.items():
            if not isinstance(fc, dict):
                continue
            try:
                fcast_apy = float(fc.get("forecast_apy", 0.0))
            except (TypeError, ValueError):
                fcast_apy = 0.0
            confidence = fc.get("confidence", "none")
            candidates.append(
                {
                    "adapter_id":   adapter_id,
                    "forecast_apy": fcast_apy,
                    "confidence":   confidence,
                }
            )

        candidates.sort(key=lambda x: x["forecast_apy"], reverse=True)
        return candidates[:n]

    # --- risk_budget ---------------------------------------------------

    def _extract_risk_flags(self, risk_budget_data: Any) -> List[str]:
        """Return list of adapter IDs with BREACH status from the latest report."""
        if not isinstance(risk_budget_data, dict):
            return []

        # Support ring-buffer (history list) or direct report
        history = risk_budget_data.get("history")
        if isinstance(history, list) and history:
            report = history[-1]
        else:
            report = risk_budget_data

        if not isinstance(report, dict):
            return []

        adapter_details = report.get("adapter_details", [])
        if not isinstance(adapter_details, list):
            return []

        flags: List[str] = []
        for entry in adapter_details:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == _STATUS_BREACH:
                aid = entry.get("adapter_id") or entry.get("id") or "unknown"
                if aid not in flags:
                    flags.append(str(aid))

        return flags

    # --- scenario ------------------------------------------------------

    def _extract_worst_case(self, scenario_data: Any) -> Dict[str, Any]:
        """Extract the worst-case scenario summary from the latest report."""
        if not isinstance(scenario_data, dict):
            return {}

        # Ring-buffer structure: {"history": [...]}
        history = scenario_data.get("history")
        if isinstance(history, list) and history:
            report = history[-1]
        else:
            report = scenario_data

        if not isinstance(report, dict):
            return {}

        worst = report.get("worst_case")
        if not isinstance(worst, dict):
            return {}

        return {
            "scenario_name":       worst.get("scenario_name", "?"),
            "portfolio_return_pct": _safe_float(
                worst.get("portfolio_return_pct", 0.0)
            ),
        }

    # --- attribution ---------------------------------------------------

    def _extract_attribution(self, attribution_data: Any) -> tuple:
        """Return (attribution_active: bool, total_active_return: float)."""
        if not isinstance(attribution_data, dict):
            return False, 0.0

        history = attribution_data.get("history")
        if isinstance(history, list) and history:
            report = history[-1]
        else:
            report = attribution_data

        if not isinstance(report, dict):
            return False, 0.0

        available = bool(report.get("available", False))
        try:
            total_active_return = float(
                report.get("total_active_return", 0.0)
            )
        except (TypeError, ValueError):
            total_active_return = 0.0

        return available, total_active_return

    # --- withdrawal ----------------------------------------------------

    def _extract_withdrawal_count(self, withdrawal_data: Any) -> int:
        """Return total number of completed withdrawal records."""
        if isinstance(withdrawal_data, dict):
            history = withdrawal_data.get("history", withdrawal_data.get("entries"))
            if isinstance(history, list):
                return len(history)
            # count key if present
            count = withdrawal_data.get("count")
            if isinstance(count, int):
                return count
            return 0
        if isinstance(withdrawal_data, list):
            return len(withdrawal_data)
        return 0


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float; return *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="SPA DailyDigest — collect and save daily portfolio digest"
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="Collect data, build summary and atomically save to data/daily_digest.json.",
    )
    p.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="(default) Collect + build + print summary without writing.",
    )
    p.add_argument(
        "--data-dir",
        default="data",
        dest="data_dir",
        help="Path to data/ directory (default: 'data').",
    )
    p.add_argument(
        "--date",
        default=None,
        help="Override date (YYYY-MM-DD).  Defaults to today.",
    )
    return p


def main(argv=None):
    parser = _build_arg_parser()
    args   = parser.parse_args(argv)

    digest  = DailyDigest(data_dir=args.data_dir)
    data    = digest.collect_data(date_str=args.date)
    summary = digest.build_summary(data)
    msg     = digest.format_telegram_message(summary)

    print(msg)
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.run:
        path = digest.save_digest(summary)
        print(f"\n[saved] {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
