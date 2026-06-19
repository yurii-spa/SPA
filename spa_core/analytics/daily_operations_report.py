"""
DailyOperationsReport (MP-606)
==============================
Comprehensive daily operations report that aggregates outputs of all
analytics modules into a single unified document.

Source files consumed (all optional — missing files are silently skipped):

    data/integrated_risk.json           — integrated risk dashboard (weighted signals)
    data/yield_attribution_tracker.json — per-protocol yield attribution
    data/multi_chain_report.json        — multi-chain monitor (adapters, TVL, APY)
    data/tournament_ranking.json        — tournament strategy ranking (S0–S18)
    data/peg_report.json                — peg stability monitor (USDC/DAI/FRAX)
    data/paper_trading_status.json      — paper trading status (day number)

Output file (ring-buffer 30 reports):

    data/daily_ops_report.json

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Read-only except :meth:`save` which writes atomically (tmp + ``os.replace``).
* Never raises on the happy path; all data-load failures degrade gracefully.
* Telegram message ≤ 4 000 characters (hard-truncated with ellipsis).
* Does NOT import risk/, execution/, monitoring/, allocator/, cycle_runner.

Public API
----------
``DailyOperationsReport(data_path: Optional[str] = None)``

Methods:
    - ``generate()`` → DailyOpsReport
    - ``save(output_path=None)`` → str  (path written)
    - ``format_telegram_message()`` → str
    - ``format_summary()`` → str
    - ``to_dict()`` → dict

CLI
---
``python3 -m spa_core.analytics.daily_operations_report --check``   (default, no write)
``python3 -m spa_core.analytics.daily_operations_report --run``     (+ atomic save)
``python3 -m spa_core.analytics.daily_operations_report --data-dir PATH``
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORT_FILENAME: str = "daily_ops_report.json"
_RING_BUFFER_MAX: int = 30
_TELEGRAM_MAX_CHARS: int = 4000
_TELEGRAM_ELLIPSIS: str = "…"
_FRESHNESS_HOURS: float = 2.0

# Source filenames
_SRC_INTEGRATED_RISK: str = "integrated_risk.json"
_SRC_YIELD_TRACKER: str = "yield_attribution_tracker.json"
_SRC_MULTI_CHAIN: str = "multi_chain_report.json"
_SRC_TOURNAMENT: str = "tournament_ranking.json"
_SRC_PEG: str = "peg_report.json"
_SRC_PAPER_STATUS: str = "paper_trading_status.json"

# Section status values
_STATUS_OK: str = "OK"
_STATUS_WARNING: str = "WARNING"
_STATUS_CRITICAL: str = "CRITICAL"
_STATUS_UNKNOWN: str = "UNKNOWN"

# Overall report status values
_OVERALL_OPERATIONAL: str = "OPERATIONAL"
_OVERALL_DEGRADED: str = "DEGRADED"
_OVERALL_CRITICAL: str = "CRITICAL"

# Integrated-risk level → section status mapping
_RISK_LEVEL_MAP: Dict[str, str] = {
    "GREEN": _STATUS_OK,
    "YELLOW": _STATUS_WARNING,
    "ORANGE": _STATUS_WARNING,
    "RED": _STATUS_CRITICAL,
}

# Peg overall_status → section status mapping
_PEG_STATUS_MAP: Dict[str, str] = {
    "GREEN": _STATUS_OK,
    "YELLOW": _STATUS_WARNING,
    "RED": _STATUS_CRITICAL,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OpsReportSection:
    """One thematic block of the daily operations report."""
    name: str            # "risk" / "yield" / "chains" / "strategies" / "peg"
    status: str          # "OK" / "WARNING" / "CRITICAL" / "UNKNOWN"
    headline: str        # Single-line main finding
    details: dict        # Raw data extracted from source JSON
    data_source: str     # Filename of source JSON (e.g. "integrated_risk.json")
    data_fresh: bool     # True if source data is < 2 hours old

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "headline": self.headline,
            "details": self.details,
            "data_source": self.data_source,
            "data_fresh": self.data_fresh,
        }


@dataclass
class DailyOpsReport:
    """Complete daily operations report aggregating all analytics."""
    report_date: str          # YYYY-MM-DD
    generated_at: str         # ISO UTC timestamp
    day_number: int           # Days since paper trading started
    overall_status: str       # "OPERATIONAL" / "DEGRADED" / "CRITICAL"
    sections: List[OpsReportSection]
    portfolio_summary: dict   # {total_allocated_usd, effective_apy, daily_yield_usd}
    risk_summary: dict        # {overall_level, top_risk}
    strategy_summary: dict    # {best_strategy, best_apy, active_count}
    chain_summary: dict       # {best_chain, l2_adapters_count}
    peg_summary: dict         # {all_stable, critical_count}
    action_items: List[str]   # Concrete actions required
    auto_generated: bool = True

    def to_dict(self) -> dict:
        return {
            "report_date": self.report_date,
            "generated_at": self.generated_at,
            "day_number": self.day_number,
            "overall_status": self.overall_status,
            "sections": [s.to_dict() for s in self.sections],
            "portfolio_summary": self.portfolio_summary,
            "risk_summary": self.risk_summary,
            "strategy_summary": self.strategy_summary,
            "chain_summary": self.chain_summary,
            "peg_summary": self.peg_summary,
            "action_items": self.action_items,
            "auto_generated": self.auto_generated,
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp robustly. Returns None on failure."""
    try:
        ts_str = ts_str.strip()
        # Normalize Z suffix (Python 3.10 fromisoformat does not support Z)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DailyOperationsReport
# ---------------------------------------------------------------------------

class DailyOperationsReport(BaseAnalytics):
    """
    Aggregate all SPA analytics modules into a daily operations report.

    Parameters
    ----------
    data_path:
        Path to the ``data/`` directory.  Defaults to the ``data/`` folder
        next to the project root (resolved relative to this file).
    """

    OUTPUT_PATH = "data/daily_ops_report.json"

    def __init__(self, data_path: Optional[str] = None) -> None:
        super().__init__()
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data")
        self.data_path = Path(data_path)
        self._report: Optional[DailyOpsReport] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_load(self, filename: str) -> Optional[dict]:
        """
        Load *filename* from ``data_path`` as a JSON dict.

        Returns ``None`` if the file is missing, unreadable, empty,
        or does not contain a JSON object (dict).
        """
        path = self.data_path / filename
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return None
            return data
        except Exception:
            return None

    def _is_fresh(self, data: Optional[dict], max_age_hours: float = _FRESHNESS_HOURS) -> bool:
        """
        Return True if *data* contains a timestamp field that is less than
        *max_age_hours* old (compared to current UTC time).

        Checks root-level keys first: ``generated_at``, ``updated_at``,
        ``last_updated``, ``timestamp``.  Falls back to the same keys inside
        ``data["latest"]`` if present.
        """
        if data is None:
            return False

        _TS_KEYS = ("generated_at", "updated_at", "last_updated", "timestamp")

        ts_str: Optional[str] = None
        for key in _TS_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val:
                ts_str = val
                break

        # Try nested latest dict
        if ts_str is None:
            latest = data.get("latest")
            if isinstance(latest, dict):
                for key in _TS_KEYS:
                    val = latest.get(key)
                    if isinstance(val, str) and val:
                        ts_str = val
                        break

        if ts_str is None:
            return False

        dt = _parse_timestamp(ts_str)
        if dt is None:
            return False

        now = datetime.now(timezone.utc)
        age_hours = (now - dt).total_seconds() / 3600.0
        return age_hours < max_age_hours

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_risk_section(self) -> OpsReportSection:
        """Build risk section from ``integrated_risk.json``."""
        data = self._safe_load(_SRC_INTEGRATED_RISK)
        fresh = self._is_fresh(data)

        if data is None:
            return OpsReportSection(
                name="risk",
                status=_STATUS_UNKNOWN,
                headline="Risk: UNKNOWN — data unavailable",
                details={},
                data_source=_SRC_INTEGRATED_RISK,
                data_fresh=False,
            )

        latest = data.get("latest", {})
        if not isinstance(latest, dict):
            latest = {}

        overall_level = str(latest.get("overall_level", "UNKNOWN")).upper()
        critical_count = int(latest.get("critical_count", 0) or 0)
        warning_count = int(latest.get("warning_count", 0) or 0)
        top_risk = str(latest.get("top_risk", "") or "")
        recommendations = latest.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []

        status = _RISK_LEVEL_MAP.get(overall_level, _STATUS_UNKNOWN)

        if status == _STATUS_CRITICAL:
            headline = f"Risk: {overall_level} — CRITICAL: {top_risk or 'issue detected'}"
        elif status == _STATUS_WARNING:
            headline = f"Risk: {overall_level} — warnings: {warning_count}"
        elif status == _STATUS_OK:
            headline = f"Risk: {overall_level} — no issues"
        else:
            headline = f"Risk: {overall_level} — {top_risk or 'unknown'}"

        return OpsReportSection(
            name="risk",
            status=status,
            headline=headline,
            details={
                "overall_level": overall_level,
                "critical_count": critical_count,
                "warning_count": warning_count,
                "top_risk": top_risk,
                "recommendations": recommendations[:3],
            },
            data_source=_SRC_INTEGRATED_RISK,
            data_fresh=fresh,
        )

    def _build_yield_section(self) -> OpsReportSection:
        """Build yield section from ``yield_attribution_tracker.json``."""
        data = self._safe_load(_SRC_YIELD_TRACKER)
        fresh = self._is_fresh(data)

        if data is None:
            return OpsReportSection(
                name="yield",
                status=_STATUS_UNKNOWN,
                headline="Yield: UNKNOWN — data unavailable",
                details={},
                data_source=_SRC_YIELD_TRACKER,
                data_fresh=False,
            )

        latest = data.get("latest", {})
        if not isinstance(latest, dict):
            latest = {}

        total_allocated = float(latest.get("total_allocated_usd", 0.0) or 0.0)
        daily_yield = float(latest.get("total_daily_yield_usd", 0.0) or 0.0)
        effective_apy = float(latest.get("effective_apy_pct", 0.0) or 0.0)
        top_contributor = str(latest.get("top_contributor", "") or "")

        # Determine status
        if effective_apy > 0:
            status = _STATUS_OK
        elif total_allocated > 0:
            status = _STATUS_WARNING
        else:
            status = _STATUS_UNKNOWN

        allocated_k = total_allocated / 1000.0
        headline = (
            f"Portfolio: ${allocated_k:.0f}K | APY {effective_apy:.2f}% | "
            f"Daily yield ${daily_yield:.2f}"
        )

        return OpsReportSection(
            name="yield",
            status=status,
            headline=headline,
            details={
                "total_allocated_usd": total_allocated,
                "effective_apy_pct": effective_apy,
                "total_daily_yield_usd": daily_yield,
                "top_contributor": top_contributor,
            },
            data_source=_SRC_YIELD_TRACKER,
            data_fresh=fresh,
        )

    def _build_chains_section(self) -> OpsReportSection:
        """Build chains section from ``multi_chain_report.json``."""
        data = self._safe_load(_SRC_MULTI_CHAIN)
        fresh = self._is_fresh(data)

        if data is None:
            return OpsReportSection(
                name="chains",
                status=_STATUS_UNKNOWN,
                headline="Chains: UNKNOWN — data unavailable",
                details={},
                data_source=_SRC_MULTI_CHAIN,
                data_fresh=False,
            )

        latest = data.get("latest", {})
        if not isinstance(latest, dict):
            latest = {}

        best_chain = str(latest.get("best_chain", "") or "")
        best_apy = float(latest.get("best_apy_overall", 0.0) or 0.0)
        total_adapters = int(latest.get("total_adapters", 0) or 0)
        total_tvl = float(latest.get("total_tvl_usd", 0.0) or 0.0)
        l2_premium = latest.get("l2_premium_pct")

        status = _STATUS_OK if best_chain else _STATUS_UNKNOWN

        tvl_b = total_tvl / 1_000_000_000.0
        headline = (
            f"Best chain: {best_chain or 'N/A'} ({best_apy:.1f}%) | "
            f"{total_adapters} adapters | TVL ${tvl_b:.0f}B"
        )

        return OpsReportSection(
            name="chains",
            status=status,
            headline=headline,
            details={
                "best_chain": best_chain,
                "best_apy_overall": best_apy,
                "total_adapters": total_adapters,
                "total_tvl_usd": total_tvl,
                "l2_premium_pct": l2_premium,
            },
            data_source=_SRC_MULTI_CHAIN,
            data_fresh=fresh,
        )

    def _build_strategies_section(self) -> OpsReportSection:
        """Build strategies section from ``tournament_ranking.json``."""
        data = self._safe_load(_SRC_TOURNAMENT)
        fresh = self._is_fresh(data)

        if data is None:
            return OpsReportSection(
                name="strategies",
                status=_STATUS_UNKNOWN,
                headline="Strategies: UNKNOWN — data unavailable",
                details={},
                data_source=_SRC_TOURNAMENT,
                data_fresh=False,
            )

        winner = str(data.get("winner", "") or "")
        strategies = data.get("strategies", [])
        if not isinstance(strategies, list):
            strategies = []

        active_count = len(strategies)

        # Find winner's realised APY from the strategies list
        winner_apy: Optional[float] = None
        for s in strategies:
            if isinstance(s, dict) and s.get("id") == winner:
                raw = s.get("apy_realized")
                if raw is not None and not isinstance(raw, bool):
                    try:
                        winner_apy = float(raw)
                    except (TypeError, ValueError):
                        winner_apy = None
                break

        status = _STATUS_OK if winner else _STATUS_UNKNOWN

        if winner_apy is not None:
            headline = f"{winner} leads at {winner_apy:.1f}% | {active_count} strategies active"
        elif winner:
            headline = f"{winner} leads | {active_count} strategies active"
        else:
            headline = f"Strategies: {active_count} active | no clear leader"

        return OpsReportSection(
            name="strategies",
            status=status,
            headline=headline,
            details={
                "winner": winner,
                "winner_apy": winner_apy,
                "active_count": active_count,
                "tournament_days": int(data.get("tournament_days", 0) or 0),
            },
            data_source=_SRC_TOURNAMENT,
            data_fresh=fresh,
        )

    def _build_peg_section(self) -> OpsReportSection:
        """Build peg section from ``peg_report.json``."""
        data = self._safe_load(_SRC_PEG)
        fresh = self._is_fresh(data)

        if data is None:
            return OpsReportSection(
                name="peg",
                status=_STATUS_UNKNOWN,
                headline="Peg: UNKNOWN — data unavailable",
                details={},
                data_source=_SRC_PEG,
                data_fresh=False,
            )

        overall_status_raw = str(data.get("overall_status", "UNKNOWN") or "UNKNOWN").upper()
        stable = int(data.get("stable", 0) or 0)
        warning_ct = int(data.get("warning", 0) or 0)
        critical_ct = int(data.get("critical", 0) or 0)
        worst_adapter = str(data.get("worst_adapter", "") or "")
        worst_deviation = float(data.get("worst_deviation_pct", 0.0) or 0.0)

        # Derive section status
        if critical_ct > 0:
            status = _STATUS_CRITICAL
            headline = (
                f"CRITICAL: {worst_adapter} depeg {worst_deviation:.2f}%"
            )
        elif warning_ct > 0:
            status = _STATUS_WARNING
            headline = (
                f"WARNING: {worst_adapter} peg deviation {worst_deviation:.2f}%"
            )
        elif overall_status_raw == "GREEN":
            status = _STATUS_OK
            headline = f"All pegs STABLE ({stable} adapters)"
        else:
            status = _PEG_STATUS_MAP.get(overall_status_raw, _STATUS_UNKNOWN)
            headline = f"Peg: {overall_status_raw} — {worst_adapter or 'unknown'}"

        return OpsReportSection(
            name="peg",
            status=status,
            headline=headline,
            details={
                "overall_status": overall_status_raw,
                "stable": stable,
                "warning": warning_ct,
                "critical": critical_ct,
                "worst_adapter": worst_adapter,
                "worst_deviation_pct": worst_deviation,
            },
            data_source=_SRC_PEG,
            data_fresh=fresh,
        )

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def _compute_portfolio_summary(self, yield_data: Optional[dict]) -> dict:
        """Extract portfolio totals from yield attribution data."""
        if yield_data is None:
            return {
                "total_allocated_usd": 0.0,
                "effective_apy": 0.0,
                "daily_yield_usd": 0.0,
            }
        latest = yield_data.get("latest", {})
        if not isinstance(latest, dict):
            latest = {}
        return {
            "total_allocated_usd": float(latest.get("total_allocated_usd", 0.0) or 0.0),
            "effective_apy": float(latest.get("effective_apy_pct", 0.0) or 0.0),
            "daily_yield_usd": float(latest.get("total_daily_yield_usd", 0.0) or 0.0),
        }

    def _compute_day_number(self) -> int:
        """
        Return the number of days the system has been running.

        Reads ``days_running`` from ``paper_trading_status.json``.
        Returns 0 on any error.
        """
        data = self._safe_load(_SRC_PAPER_STATUS)
        if data is None:
            return 0
        days = data.get("days_running")
        if days is None or isinstance(days, bool):
            return 0
        try:
            return int(days)
        except (TypeError, ValueError):
            return 0

    def _determine_overall_status(self, sections: List[OpsReportSection]) -> str:
        """
        Compute overall report status from section statuses.

        * ``CRITICAL``    — any section is CRITICAL
        * ``DEGRADED``    — any section is WARNING (and none are CRITICAL)
        * ``OPERATIONAL`` — no WARNING or CRITICAL sections
        """
        statuses = {s.status for s in sections}
        if _STATUS_CRITICAL in statuses:
            return _OVERALL_CRITICAL
        if _STATUS_WARNING in statuses:
            return _OVERALL_DEGRADED
        return _OVERALL_OPERATIONAL

    def _generate_action_items(self, sections: List[OpsReportSection]) -> List[str]:
        """
        Generate a concrete action list based on section statuses.

        One action item per WARNING/CRITICAL section with domain-specific text.
        """
        items: List[str] = []
        for section in sections:
            if section.status == _STATUS_CRITICAL:
                if section.name == "peg":
                    adapter = section.details.get("worst_adapter", "unknown")
                    dev = section.details.get("worst_deviation_pct", 0.0)
                    items.append(
                        f"CRITICAL: Halt new deposits — peg broken "
                        f"({adapter} {dev:.2f}% deviation)"
                    )
                elif section.name == "risk":
                    top = section.details.get("top_risk", "critical risk detected")
                    items.append(f"CRITICAL: Review risk immediately — {top}")
                else:
                    items.append(
                        f"CRITICAL: Investigate {section.name} — {section.headline}"
                    )
            elif section.status == _STATUS_WARNING:
                if section.name == "risk":
                    top = section.details.get("top_risk", "")
                    items.append(
                        f"WARNING: Review risk signal — {top or section.headline}"
                    )
                elif section.name == "yield":
                    apy = section.details.get("effective_apy_pct", 0.0)
                    items.append(
                        f"WARNING: Low yield detected (APY={apy:.2f}%) — review allocation"
                    )
                elif section.name == "chains":
                    items.append(f"WARNING: Chain data issue — {section.headline}")
                elif section.name == "peg":
                    adapter = section.details.get("worst_adapter", "unknown")
                    dev = section.details.get("worst_deviation_pct", 0.0)
                    items.append(
                        f"WARNING: Monitor peg stability — {adapter} deviation {dev:.2f}%"
                    )
                elif section.name == "strategies":
                    items.append(
                        f"WARNING: Strategy issue — {section.headline}"
                    )
                else:
                    items.append(
                        f"WARNING: Check {section.name} — {section.headline}"
                    )
        return items

    # ------------------------------------------------------------------
    # Main generate
    # ------------------------------------------------------------------

    def generate(self) -> DailyOpsReport:
        """Build the complete daily operations report from all data sources."""
        now = datetime.now(timezone.utc)
        report_date = now.strftime("%Y-%m-%d")
        generated_at = now.isoformat()

        # Build all sections
        risk_section = self._build_risk_section()
        yield_section = self._build_yield_section()
        chains_section = self._build_chains_section()
        strategies_section = self._build_strategies_section()
        peg_section = self._build_peg_section()

        sections: List[OpsReportSection] = [
            risk_section,
            yield_section,
            chains_section,
            strategies_section,
            peg_section,
        ]

        # Portfolio summary from yield tracker
        yield_data = self._safe_load(_SRC_YIELD_TRACKER)
        portfolio_summary = self._compute_portfolio_summary(yield_data)

        risk_summary = {
            "overall_level": risk_section.details.get("overall_level", "UNKNOWN"),
            "top_risk": risk_section.details.get("top_risk", ""),
        }

        strategy_summary = {
            "best_strategy": strategies_section.details.get("winner", ""),
            "best_apy": strategies_section.details.get("winner_apy"),
            "active_count": strategies_section.details.get("active_count", 0),
        }

        chain_summary = {
            "best_chain": chains_section.details.get("best_chain", ""),
            "l2_adapters_count": chains_section.details.get("total_adapters", 0),
        }

        peg_summary = {
            "all_stable": peg_section.status == _STATUS_OK,
            "critical_count": peg_section.details.get("critical", 0),
        }

        day_number = self._compute_day_number()
        overall_status = self._determine_overall_status(sections)
        action_items = self._generate_action_items(sections)

        self._report = DailyOpsReport(
            report_date=report_date,
            generated_at=generated_at,
            day_number=day_number,
            overall_status=overall_status,
            sections=sections,
            portfolio_summary=portfolio_summary,
            risk_summary=risk_summary,
            strategy_summary=strategy_summary,
            chain_summary=chain_summary,
            peg_summary=peg_summary,
            action_items=action_items,
            auto_generated=True,
        )
        return self._report

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, output_path: Optional[str] = None) -> str:
        """
        Atomically save the report to ``data/daily_ops_report.json``.

        Maintains a ring-buffer of up to ``_RING_BUFFER_MAX`` reports in
        the ``history`` list. Calls :meth:`generate` first if the report
        has not been generated yet.

        Returns the path of the written file.
        """
        if self._report is None:
            self.generate()

        if output_path is None:
            output_path = str(self.data_path / _REPORT_FILENAME)

        # Load existing ring buffer (fail-safe)
        existing: dict = {
            "schema_version": 1,
            "source": "daily_operations_report",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "report_count": 0,
            "last_updated": "",
            "latest": {},
            "history": [],
        }
        try:
            with open(output_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            pass

        report_dict = self._report.to_dict()

        history: List[dict] = existing.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(report_dict)

        # Trim ring buffer
        if len(history) > _RING_BUFFER_MAX:
            history = history[-_RING_BUFFER_MAX:]

        payload = {
            "schema_version": 1,
            "source": "daily_operations_report",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp file → os.replace
        out_dir = os.path.dirname(output_path) or "."
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            dir=out_dir,
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name

        os.replace(tmp_path, output_path)
        return output_path

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_telegram_message(self) -> str:
        """
        Format a Telegram-ready message ≤ 4 000 characters.

        Calls :meth:`generate` first if the report has not been generated.
        """
        if self._report is None:
            self.generate()
        r = self._report

        _STATUS_EMOJI = {
            _OVERALL_OPERATIONAL: "🟢",
            _OVERALL_DEGRADED: "🟡",
            _OVERALL_CRITICAL: "🔴",
        }
        _SECTION_EMOJI = {
            "risk":       "⚠️",
            "yield":      "📈",
            "chains":     "⛓",
            "strategies": "🏆",
            "peg":        "🔒",
        }
        _STATUS_ICON = {
            _STATUS_OK:       "✅",
            _STATUS_WARNING:  "⚠️",
            _STATUS_CRITICAL: "🚨",
            _STATUS_UNKNOWN:  "❓",
        }

        status_emoji = _STATUS_EMOJI.get(r.overall_status, "⚪")

        lines: List[str] = [
            f"📊 SPA Daily Ops — {r.report_date}",
            f"Day #{r.day_number}",
            f"Status: {status_emoji} {r.overall_status}",
            "",
            "💰 Portfolio:",
            f"  Allocated: ${r.portfolio_summary.get('total_allocated_usd', 0) / 1000:.0f}K",
            f"  APY: {r.portfolio_summary.get('effective_apy', 0):.2f}%",
            f"  Daily yield: ${r.portfolio_summary.get('daily_yield_usd', 0):.2f}",
            "",
        ]

        for section in r.sections:
            sec_emoji = _SECTION_EMOJI.get(section.name, "📋")
            st_icon = _STATUS_ICON.get(section.status, "❓")
            lines.append(f"{sec_emoji} {section.name.capitalize()}: {st_icon}")
            lines.append(f"  {section.headline}")
            lines.append("")

        if r.action_items:
            lines.append("🎯 Action Items:")
            for item in r.action_items:
                lines.append(f"  • {item}")
            lines.append("")

        lines.append(f"⏱ Generated: {r.generated_at[:19]}Z")

        msg = "\n".join(lines)
        if len(msg) > _TELEGRAM_MAX_CHARS:
            msg = msg[: _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)] + _TELEGRAM_ELLIPSIS
        return msg

    def format_summary(self) -> str:
        """
        One-line summary ≤ 200 characters suitable for log output.

        Calls :meth:`generate` first if the report has not been generated.
        """
        if self._report is None:
            self.generate()
        r = self._report

        summary = (
            f"DailyOps {r.report_date} | Day#{r.day_number} | "
            f"{r.overall_status} | "
            f"APY {r.portfolio_summary.get('effective_apy', 0):.2f}% | "
            f"Risk {r.risk_summary.get('overall_level', 'UNKNOWN')} | "
            f"Actions: {len(r.action_items)}"
        )
        if len(summary) > 200:
            summary = summary[:199] + "…"
        return summary

    def to_dict(self) -> dict:
        """Return the report as a plain dict. Calls :meth:`generate` if needed."""
        if self._report is None:
            self.generate()
        return self._report.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Daily Operations Report (MP-606) — aggregate all SPA analytics."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print report without saving (default when no flag given).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute report and save atomically to data/daily_ops_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    reporter = DailyOperationsReport(data_path=args.data_dir)
    reporter.generate()

    print(reporter.format_telegram_message())
    print("\n" + "=" * 60)
    print(reporter.format_summary())

    if args.run:
        path = reporter.save()
        print(f"\n[DailyOpsReport] ✅ Saved → {path}")
    else:
        print("\n[DailyOpsReport] Check mode — no file written (use --run to save).")


if __name__ == "__main__":
    main()
