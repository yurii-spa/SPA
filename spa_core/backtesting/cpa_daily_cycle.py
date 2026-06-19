"""
spa_core/backtesting/cpa_daily_cycle.py

Daily CPA cycle runner. Intended to be called once per day from launchd.
Performs:
  1. Gate check (BacktestGate.four_state_status)
  2. Source pipeline status
  3. Evidence accumulation update (if paper trading active)
  4. Market regime detection
  5. Research strategy gate check (RS-001/RS-002 allowed in current regime?)
  6. Governance event logging
  7. Telegram report (if configured)

Output: data/cpa/daily_cycle_YYYY-MM-DD.json

MP-1345 (v9.61)
stdlib only, atomic writes, LLM FORBIDDEN.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Optional


# ── Regime normalisation map ───────────────────────────────────────────────────
#   Maps raw regime strings (uppercase from regime_detector / JSON)
#   to the canonical three-state set used by CPA: bull / bear / neutral.
_REGIME_MAP = {
    "bull":     "bull",
    "bear":     "bear",
    "sideways": "neutral",
    "volatile": "neutral",
    "stable":   "neutral",
    "neutral":  "neutral",
}


class CPADailyCycle:
    """
    Daily CPA methodology cycle runner.

    One instance per day; create a fresh instance in each launchd invocation.

    Args:
        base_dir: Root of the SPA repo (default: current working directory).
        date:     ISO date string ``YYYY-MM-DD`` for this cycle.
                  Defaults to today in UTC.  Pass an explicit value in tests.
    """

    def __init__(self, base_dir: str = ".", date: Optional[str] = None) -> None:
        self._base_dir = Path(base_dir)
        self._date = date or datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Run full daily CPA cycle.

        Returns a summary dict with all 7 section results.
        Never raises — each section is guarded individually.
        """
        sections: dict = {}

        sections["gate_check"]      = self.gate_check()
        sections["source_status"]   = self.source_status()
        sections["evidence_update"] = self.evidence_update()
        sections["regime_check"]    = self.regime_check()
        sections["research_gates"]  = self.research_gates()
        sections["governance_log"]  = self.governance_log()

        result = {
            "date":     self._date,
            "sections": sections,
        }

        # Section 7 — Telegram (best-effort)
        tg_ok = self.send_telegram(result)
        sections["telegram"] = {
            "sent":    tg_ok,
            "skipped": not tg_ok,
        }

        return result

    # ── Section 1 ──────────────────────────────────────────────────────────────

    def gate_check(self) -> dict:
        """
        Section 1: 4-state gate status.

        Keys: backtest, pre_paper, paper, live, blockers.
        Returns an UNKNOWN dict if gate files are missing.
        """
        try:
            from spa_core.backtesting.gate import BacktestGate
            gate = BacktestGate(
                backtest_dir=str(self._base_dir / "data" / "backtest")
            )
            return gate.four_state_status()
        except Exception as exc:  # noqa: BLE001
            return {
                "backtest":  "UNKNOWN",
                "pre_paper": "UNKNOWN",
                "paper":     "UNKNOWN",
                "live":      "BLOCKED",
                "blockers":  [str(exc)],
                "error":     str(exc),
            }

    # ── Section 2 ──────────────────────────────────────────────────────────────

    def source_status(self) -> dict:
        """
        Section 2: source pipeline counts.

        Returns total source count, clean_included count, and per-state breakdown.
        Graceful: returns zeros if source pipeline is unavailable.
        """
        try:
            from spa_core.backtesting.source_pipeline import SourcePipeline
            pipeline = SourcePipeline(
                data_dir=str(self._base_dir / "data" / "backtest")
            )
            summary   = pipeline.source_summary()
            total     = sum(summary.values())
            clean     = summary.get("clean_included", 0)
            return {
                "total":         total,
                "clean_included": clean,
                "by_state":      summary,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "total":         0,
                "clean_included": 0,
                "by_state":      {},
                "error":         str(exc),
            }

    # ── Section 3 ──────────────────────────────────────────────────────────────

    def evidence_update(self) -> dict:
        """
        Section 3: paper trading evidence accumulation.

        Reads data/paper_trading_status.json.
        Never raises — returns paper_active=False if the file is absent.
        """
        path = self._base_dir / "data" / "paper_trading_status.json"
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return {
                "paper_active":   True,
                "days_running":   data.get("days_running", 0),
                "current_equity": data.get("current_equity"),
                "apy_today_pct":  data.get("apy_today_pct"),
                "is_demo":        data.get("is_demo", True),
                "last_cycle_ts":  data.get("last_cycle_ts"),
            }
        except FileNotFoundError:
            return {
                "paper_active": False,
                "days_running": 0,
                "note":         "paper_trading_status.json not found",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "paper_active": False,
                "days_running": 0,
                "error":        str(exc),
            }

    # ── Section 4 ──────────────────────────────────────────────────────────────

    def regime_check(self) -> dict:
        """
        Section 4: current market regime.

        Reads data/market_regime.json.
        Normalises raw regime labels to one of: bull / bear / neutral.
        Returns regime="neutral" if the file is absent or unreadable.
        """
        path = self._base_dir / "data" / "market_regime.json"
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            raw    = str(data.get("regime", "neutral")).lower()
            regime = _REGIME_MAP.get(raw, "neutral")
            return {
                "regime":         regime,
                "raw_regime":     data.get("regime"),
                "t1_avg_apy":     data.get("t1_avg_apy"),
                "recommendation": data.get("recommendation"),
                "detected_at":    data.get("detected_at"),
            }
        except FileNotFoundError:
            return {
                "regime":  "neutral",
                "note":    "market_regime.json not found — defaulting to neutral",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "regime": "neutral",
                "error":  str(exc),
            }

    # ── Section 5 ──────────────────────────────────────────────────────────────

    def research_gates(self) -> dict:
        """
        Section 5: RS-001 / RS-002 strategy gate check for the current regime.

        RS-001 Anti-Crisis Hedge  — allowed in all market regimes.
        RS-002 Cashflow LP        — PAUSED in bear markets (IL risk too high).
        """
        regime_data = self.regime_check()
        regime      = regime_data.get("regime", "neutral")

        # RS-001: Anti-Crisis — allowed everywhere
        rs001 = {
            "strategy": "RS-001",
            "name":     "Anti-Crisis Hedge",
            "allowed":  True,
            "reason":   "Anti-crisis hedge is permitted in all market regimes",
        }

        # RS-002: Cashflow LP — blocked in bear
        if regime == "bear":
            rs002 = {
                "strategy": "RS-002",
                "name":     "Cashflow LP",
                "allowed":  False,
                "reason":   "PAUSED — bear market: IL drag exceeds target yield",
            }
        else:
            rs002 = {
                "strategy": "RS-002",
                "name":     "Cashflow LP",
                "allowed":  True,
                "reason":   f"Allowed in {regime} regime",
            }

        return {
            "regime":  regime,
            "RS-001":  rs001,
            "RS-002":  rs002,
        }

    # ── Section 6 ──────────────────────────────────────────────────────────────

    def governance_log(self) -> dict:
        """
        Section 6: governance event log entry for today.

        Reads data/governance_events.json (if present) and counts pending proposals.
        Returns a governance summary dict; never raises.
        """
        events_path = self._base_dir / "data" / "governance_events.json"
        try:
            with open(events_path, encoding="utf-8") as fh:
                events = json.load(fh)
            if not isinstance(events, list):
                events = []
            pending_count = sum(
                1 for e in events if isinstance(e, dict) and e.get("status") == "pending"
            )
        except FileNotFoundError:
            events        = []
            pending_count = 0
        except Exception:  # noqa: BLE001
            events        = []
            pending_count = 0

        return {
            "date":              self._date,
            "event":             "daily_cpa_governance_check",
            "total_events":      len(events),
            "pending_proposals": pending_count,
            "note": (
                "No pending governance proposals"
                if pending_count == 0
                else f"{pending_count} pending proposal(s) — review required"
            ),
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self, result: dict) -> str:
        """
        Atomic save of the cycle result to data/cpa/daily_cycle_YYYY-MM-DD.json.

        Returns the absolute path of the written file.
        Uses tmp + os.replace for atomicity.
        """
        out_dir = self._base_dir / "data" / "cpa"
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"daily_cycle_{self._date}.json"
        out_path = out_dir / filename
        tmp_path = out_dir / (filename + ".tmp")

        content = json.dumps(result, indent=2, ensure_ascii=False)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(out_path))

        return str(out_path)

    # ── Telegram ───────────────────────────────────────────────────────────────

    def to_telegram_message(self, result: dict) -> str:
        """
        Format the cycle result as a concise Russian-language Telegram message.

        Returns a non-empty string in all cases (graceful fallback).
        """
        sections = result.get("sections", {})
        gate     = sections.get("gate_check", {})
        evidence = sections.get("evidence_update", {})
        regime   = sections.get("regime_check", {})
        rg       = sections.get("research_gates", {})
        src      = sections.get("source_status", {})

        # ── helpers ───────────────────────────────────────────────────────────
        def _icon(val: str, pass_vals=("PASS", "READY")) -> str:
            return "✅" if str(val).upper() in pass_vals else "❌"

        lines = [f"📊 *SPA CPA Daily — {self._date}*\n"]

        # Gate status
        lines.append("*Ворота:*")
        lines.append(f"  {_icon(gate.get('backtest',''))} Бэктест: {gate.get('backtest', '?')}")
        lines.append(f"  {_icon(gate.get('pre_paper',''))} Pre-Paper: {gate.get('pre_paper', '?')}")
        lines.append(
            f"  {'✅' if gate.get('paper') == 'READY' else '⏳'} "
            f"Paper: {gate.get('paper', '?')}"
        )
        lines.append(
            f"  {'✅' if gate.get('live') == 'READY' else '🔒'} "
            f"Live: {gate.get('live', '?')}\n"
        )

        # Evidence
        if evidence.get("paper_active"):
            days  = evidence.get("days_running", 0)
            apy   = evidence.get("apy_today_pct") or 0.0
            lines.append(f"*Paper Trading:* {days} дней, APY {apy:.2f}%\n")
        else:
            lines.append("*Paper Trading:* не запущен\n")

        # Regime
        reg_label = str(regime.get("regime", "?")).upper()
        lines.append(f"*Режим рынка:* {reg_label}")
        t1_apy = regime.get("t1_avg_apy")
        if t1_apy is not None:
            lines.append(f"  T1 avg APY: {t1_apy:.2f}%")
        lines.append("")

        # Research gates
        rs001 = rg.get("RS-001", {})
        rs002 = rg.get("RS-002", {})
        lines.append("*Стратегии:*")
        lines.append(
            f"  {'✅' if rs001.get('allowed') else '❌'} "
            f"RS-001 Anti-Crisis: {'разрешён' if rs001.get('allowed') else 'заблокирован'}"
        )
        lines.append(
            f"  {'✅' if rs002.get('allowed') else '⏸'} "
            f"RS-002 Cashflow LP: {'разрешён' if rs002.get('allowed') else 'приостановлен'}"
        )
        lines.append("")

        # Source counts
        total = src.get("total", 0)
        clean = src.get("clean_included", 0)
        if total:
            lines.append(f"*Источники:* {clean}/{total} чистых ({clean*100//total}%)")

        return "\n".join(lines)

    def send_telegram(self, result: dict) -> bool:
        """
        Send the cycle Telegram message via TelegramResearchAlerts._send().

        Returns True on success, False on any failure (credential/network).
        Never raises.
        """
        try:
            from spa_core.alerts.telegram_research_alerts import TelegramResearchAlerts
            msg    = self.to_telegram_message(result)
            alerts = TelegramResearchAlerts()
            return alerts._send(msg)
        except Exception:  # noqa: BLE001
            return False
