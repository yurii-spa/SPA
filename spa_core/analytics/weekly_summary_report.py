"""
WeeklySummaryReport (MP-610)
============================
Агрегирует 7 дней истории из data/daily_ops_report.json и формирует
недельную сводку по APY, статусам дней, топ-цепочкам и выносит вердикт.

Source file consumed:
    data/daily_ops_report.json   — ring-buffer до 30 daily ops report-ов

Output file (ring-buffer 12 недель):
    data/weekly_summary.json

Design constraints
------------------
* Pure stdlib — никаких внешних зависимостей.
* Read-only за исключением save_report() — атомарная запись (tmp + os.replace).
* Никогда не падает на happy path; все ошибки загрузки обрабатываются gracefully.
* Telegram message ≤ 1500 chars.
* НЕ импортирует risk/, execution/, monitoring/, allocator/, cycle_runner.

Public API
----------
``WeeklySummaryReport(data_path: Optional[str] = None)``

Methods:
    - ``load_daily_history()``  → list[dict]
    - ``get_last_7_days(history)``  → list[dict]
    - ``compute_weekly_stats(values, metric_name)``  → WeeklyStats
    - ``generate_report()``  → WeeklySummaryReportData
    - ``save_report(report=None)``  → str  (path written)
    - ``format_telegram_message(report=None)``  → str
    - ``to_dict(report=None)``  → dict

CLI
---
``python3 -m spa_core.analytics.weekly_summary_report --check``   (default, no write)
``python3 -m spa_core.analytics.weekly_summary_report --run``     (+ atomic save)
``python3 -m spa_core.analytics.weekly_summary_report --data-dir PATH``

MP-610.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HISTORY_FILENAME: str = "daily_ops_report.json"
_OUTPUT_FILENAME: str = "weekly_summary.json"
_RING_BUFFER_MAX: int = 12           # храним 12 недель
_TELEGRAM_MAX_CHARS: int = 1500
_TELEGRAM_ELLIPSIS: str = "…"

# Trend thresholds
_TREND_RISING_DELTA: float = 0.1    # last > first + 0.1 → RISING
_TREND_FALLING_DELTA: float = 0.1   # last < first - 0.1 → FALLING

# Verdict thresholds
_EXCELLENT_APY: float = 6.0
_EXCELLENT_OP_DAYS: int = 5
_GOOD_APY: float = 5.0
_GOOD_OP_DAYS: int = 4
_FAIR_APY: float = 4.0

# Day status values (matching DailyOpsReport.overall_status)
_STATUS_OPERATIONAL: str = "OPERATIONAL"
_STATUS_DEGRADED: str = "DEGRADED"
_STATUS_CRITICAL: str = "CRITICAL"

# Verdict values
_VERDICT_EXCELLENT: str = "EXCELLENT"
_VERDICT_GOOD: str = "GOOD"
_VERDICT_FAIR: str = "FAIR"
_VERDICT_POOR: str = "POOR"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WeeklyStats:
    """Статистика по одному показателю за неделю."""
    metric_name: str
    values: List[float]       # значения по дням (chronological order)
    avg: float
    min: float
    max: float
    trend: str                # "RISING" / "FALLING" / "STABLE"


@dataclass
class WeeklySummaryReportData:
    """Полная недельная сводка."""
    generated_at: str         # ISO UTC timestamp
    week_start: str           # ISO строка самого старого снапшота
    week_end: str             # ISO строка самого нового снапшота
    days_covered: int         # сколько дней реально есть данных

    # APY статистика
    apy_stats: WeeklyStats    # effective_apy_pct по дням

    # Статус дней
    operational_days: int     # дни со статусом OPERATIONAL
    degraded_days: int        # дни со статусом DEGRADED
    critical_days: int        # дни со статусом CRITICAL
    best_day_apy: float
    worst_day_apy: float

    # Топ цепочка
    top_chain_this_week: str  # цепочка с наибольшей avg APY
    top_chain_apy: float

    # Недельный вердикт
    weekly_verdict: str       # "EXCELLENT" / "GOOD" / "FAIR" / "POOR"
    summary_line: str         # e.g. "Week: APY avg 5.2% (5.0→5.4%), 6/7 operational"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: object) -> float:
    """Coerce value to float; return 0.0 on failure or bool."""
    if isinstance(val, bool):
        return 0.0
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp, returning None on failure."""
    try:
        ts_str = ts_str.strip()
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _compute_trend(values: List[float]) -> str:
    """
    Compute trend based on last vs first value.

    RISING  : last > first + 0.1
    FALLING : last < first - 0.1
    STABLE  : otherwise
    """
    if len(values) < 2:
        return "STABLE"
    first = values[0]
    last = values[-1]
    if last > first + _TREND_RISING_DELTA:
        return "RISING"
    if last < first - _TREND_FALLING_DELTA:
        return "FALLING"
    return "STABLE"


def _trend_arrow(trend: str) -> str:
    """Return emoji arrow for trend."""
    if trend == "RISING":
        return "↗️"
    if trend == "FALLING":
        return "↘️"
    return "→"


# ---------------------------------------------------------------------------
# WeeklySummaryReport
# ---------------------------------------------------------------------------

class WeeklySummaryReport:
    """
    Aggregate last 7 daily ops reports into a weekly summary.

    Parameters
    ----------
    data_path:
        Path to the ``data/`` directory. Defaults to the ``data/`` folder
        next to the project root (resolved relative to this file).
    """

    HISTORY_FILE: str = _HISTORY_FILENAME
    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data")
        self.data_path = Path(data_path)
        self._report: Optional[WeeklySummaryReportData] = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_daily_history(self) -> List[dict]:
        """
        Read data/daily_ops_report.json and return all history entries.

        Returns [] if the file is missing, unreadable, or has no history.
        """
        path = self.data_path / self.HISTORY_FILE
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return []
            history = data.get("history", [])
            if not isinstance(history, list):
                return []
            # Filter to dicts only
            return [item for item in history if isinstance(item, dict)]
        except Exception:
            return []

    def get_last_7_days(self, history: List[dict]) -> List[dict]:
        """
        Return the last 7 entries from the ring-buffer, sorted ascending by
        generated_at. Returns fewer entries if the buffer has less than 7.
        """
        if not history:
            return []

        # Sort by generated_at ascending (lexicographic ISO sort works for UTC timestamps)
        def _sort_key(entry: dict) -> str:
            ts = entry.get("generated_at", "")
            return ts if isinstance(ts, str) else ""

        sorted_history = sorted(history, key=_sort_key)
        return sorted_history[-7:]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def compute_weekly_stats(
        self, values: List[float], metric_name: str
    ) -> WeeklyStats:
        """
        Compute avg, min, max, and trend for a list of float values.

        If values is empty, returns a WeeklyStats with avg=min=max=0.0 and
        trend=STABLE.
        """
        if not values:
            return WeeklyStats(
                metric_name=metric_name,
                values=[],
                avg=0.0,
                min=0.0,
                max=0.0,
                trend="STABLE",
            )

        avg = sum(values) / len(values)
        return WeeklyStats(
            metric_name=metric_name,
            values=list(values),
            avg=avg,
            min=min(values),
            max=max(values),
            trend=_compute_trend(values),
        )

    def _determine_verdict(self, avg_apy: float, operational_days: int) -> str:
        """
        Compute weekly verdict.

        EXCELLENT : avg APY > 6.0% AND ≥ 5 operational days
        GOOD      : avg APY > 5.0% OR ≥ 4 operational days
        FAIR      : avg APY > 4.0%
        POOR      : otherwise
        """
        if avg_apy > _EXCELLENT_APY and operational_days >= _EXCELLENT_OP_DAYS:
            return _VERDICT_EXCELLENT
        if avg_apy > _GOOD_APY or operational_days >= _GOOD_OP_DAYS:
            return _VERDICT_GOOD
        if avg_apy > _FAIR_APY:
            return _VERDICT_FAIR
        return _VERDICT_POOR

    def _extract_top_chain(self, days: List[dict]) -> tuple[str, float]:
        """
        Extract the chain with the highest average APY across all days.

        Returns (chain_name, avg_apy). Falls back to ("", 0.0) if no chain data.
        """
        chain_apys: dict[str, list[float]] = {}

        for day in days:
            chain_summary = day.get("chain_summary", {})
            if not isinstance(chain_summary, dict):
                continue
            chain = chain_summary.get("best_chain", "")
            if not isinstance(chain, str) or not chain:
                continue
            # Try to get the APY from the chains section details
            sections = day.get("sections", [])
            chain_apy: float = 0.0
            if isinstance(sections, list):
                for sec in sections:
                    if isinstance(sec, dict) and sec.get("name") == "chains":
                        details = sec.get("details", {})
                        if isinstance(details, dict):
                            chain_apy = _safe_float(details.get("best_apy_overall", 0.0))
                        break
            if chain not in chain_apys:
                chain_apys[chain] = []
            chain_apys[chain].append(chain_apy)

        if not chain_apys:
            return ("", 0.0)

        # Find chain with highest average APY
        best_chain = max(chain_apys, key=lambda c: sum(chain_apys[c]) / len(chain_apys[c]))
        best_avg = sum(chain_apys[best_chain]) / len(chain_apys[best_chain])
        return (best_chain, best_avg)

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    def generate_report(self) -> WeeklySummaryReportData:
        """
        Generate the weekly summary report.

        If < 1 day of data is available, returns a zero-filled report with
        verdict=POOR.
        """
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()

        history = self.load_daily_history()
        days = self.get_last_7_days(history)

        if not days:
            empty_stats = self.compute_weekly_stats([], "effective_apy_pct")
            self._report = WeeklySummaryReportData(
                generated_at=generated_at,
                week_start="",
                week_end="",
                days_covered=0,
                apy_stats=empty_stats,
                operational_days=0,
                degraded_days=0,
                critical_days=0,
                best_day_apy=0.0,
                worst_day_apy=0.0,
                top_chain_this_week="",
                top_chain_apy=0.0,
                weekly_verdict=_VERDICT_POOR,
                summary_line="Week: no data available",
            )
            return self._report

        # Timestamps
        week_start = days[0].get("generated_at", "")
        week_end = days[-1].get("generated_at", "")

        # APY values
        apy_values: List[float] = []
        for day in days:
            ps = day.get("portfolio_summary", {})
            if isinstance(ps, dict):
                apy_values.append(_safe_float(ps.get("effective_apy", 0.0)))
            else:
                apy_values.append(0.0)

        apy_stats = self.compute_weekly_stats(apy_values, "effective_apy_pct")

        # Day status counts
        operational_days = 0
        degraded_days = 0
        critical_days = 0
        for day in days:
            status = day.get("overall_status", "")
            if status == _STATUS_OPERATIONAL:
                operational_days += 1
            elif status == _STATUS_DEGRADED:
                degraded_days += 1
            elif status == _STATUS_CRITICAL:
                critical_days += 1

        best_day_apy = apy_stats.max if apy_values else 0.0
        worst_day_apy = apy_stats.min if apy_values else 0.0

        # Top chain
        top_chain, top_chain_apy = self._extract_top_chain(days)

        # Verdict
        weekly_verdict = self._determine_verdict(apy_stats.avg, operational_days)

        # Summary line
        days_covered = len(days)
        if apy_values and len(apy_values) >= 2:
            summary_line = (
                f"Week: APY avg {apy_stats.avg:.1f}% "
                f"({apy_stats.min:.1f}→{apy_stats.max:.1f}%), "
                f"{operational_days}/{days_covered} operational"
            )
        elif apy_values:
            summary_line = (
                f"Week: APY avg {apy_stats.avg:.1f}%, "
                f"{operational_days}/{days_covered} operational"
            )
        else:
            summary_line = f"Week: no APY data, {operational_days}/{days_covered} operational"

        self._report = WeeklySummaryReportData(
            generated_at=generated_at,
            week_start=week_start,
            week_end=week_end,
            days_covered=days_covered,
            apy_stats=apy_stats,
            operational_days=operational_days,
            degraded_days=degraded_days,
            critical_days=critical_days,
            best_day_apy=best_day_apy,
            worst_day_apy=worst_day_apy,
            top_chain_this_week=top_chain,
            top_chain_apy=top_chain_apy,
            weekly_verdict=weekly_verdict,
            summary_line=summary_line,
        )
        return self._report

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: Optional[WeeklySummaryReportData] = None) -> str:
        """
        Atomically save the weekly summary to data/weekly_summary.json.

        Maintains a ring-buffer of up to RING_BUFFER_SIZE (12) reports in
        the ``history`` list. Calls generate_report() if no report provided.

        Returns the path of the written file.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report
        assert report is not None

        output_path = str(self.data_path / self.OUTPUT_FILE)

        # Load existing ring buffer (fail-safe)
        existing: dict = {
            "schema_version": 1,
            "source": "weekly_summary_report",
            "ring_buffer_max": self.RING_BUFFER_SIZE,
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

        report_dict = self.to_dict(report)

        history: List[dict] = existing.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(report_dict)

        # Trim ring buffer
        if len(history) > self.RING_BUFFER_SIZE:
            history = history[-self.RING_BUFFER_SIZE:]

        payload = {
            "schema_version": 1,
            "source": "weekly_summary_report",
            "ring_buffer_max": self.RING_BUFFER_SIZE,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp → os.replace
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
    # Format
    # ------------------------------------------------------------------

    def format_telegram_message(
        self, report: Optional[WeeklySummaryReportData] = None
    ) -> str:
        """
        Format a Telegram-ready message ≤ 1500 characters.

        Calls generate_report() if no report is provided or cached.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report
        assert report is not None

        r = report

        _VERDICT_EMOJI = {
            _VERDICT_EXCELLENT: "🌟",
            _VERDICT_GOOD:      "✅",
            _VERDICT_FAIR:      "🟡",
            _VERDICT_POOR:      "🔴",
        }

        _TREND_LABEL = {
            "RISING":  "📈 RISING week",
            "FALLING": "📉 FALLING week",
            "STABLE":  "➡️ STABLE week",
        }

        verdict_emoji = _VERDICT_EMOJI.get(r.weekly_verdict, "⚪")
        trend_arrow = _trend_arrow(r.apy_stats.trend)
        trend_label = _TREND_LABEL.get(r.apy_stats.trend, "➡️ STABLE week")

        lines: List[str] = [
            f"📅 Weekly Summary — {r.weekly_verdict} {verdict_emoji}",
            f"Days covered: {r.days_covered} | Operational: {r.operational_days}/{r.days_covered}",
            (
                f"APY: avg {r.apy_stats.avg:.2f}%"
                + (
                    f" | min {r.apy_stats.min:.2f}%"
                    f" | max {r.apy_stats.max:.2f}%"
                    f" | trend {trend_arrow}"
                    if r.days_covered > 0
                    else ""
                )
            ),
        ]

        if r.days_covered > 0:
            lines.append(
                f"Best day: {r.best_day_apy:.2f}% | Worst: {r.worst_day_apy:.2f}%"
            )

        if r.top_chain_this_week:
            lines.append(
                f"Top chain: {r.top_chain_this_week} {r.top_chain_apy:.1f}%"
            )

        if r.degraded_days > 0 or r.critical_days > 0:
            lines.append(
                f"⚠️ Degraded: {r.degraded_days}d | Critical: {r.critical_days}d"
            )

        lines.append(trend_label)
        lines.append(f"⏱ {r.generated_at[:19]}Z")

        msg = "\n".join(lines)
        if len(msg) > _TELEGRAM_MAX_CHARS:
            msg = msg[: _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)] + _TELEGRAM_ELLIPSIS
        return msg

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self, report: Optional[WeeklySummaryReportData] = None) -> dict:
        """
        Return the report as a plain JSON-serializable dict.

        Calls generate_report() if no report is provided or cached.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report
        assert report is not None

        r = report
        return {
            "generated_at": r.generated_at,
            "week_start": r.week_start,
            "week_end": r.week_end,
            "days_covered": r.days_covered,
            "apy_stats": {
                "metric_name": r.apy_stats.metric_name,
                "values": r.apy_stats.values,
                "avg": r.apy_stats.avg,
                "min": r.apy_stats.min,
                "max": r.apy_stats.max,
                "trend": r.apy_stats.trend,
            },
            "operational_days": r.operational_days,
            "degraded_days": r.degraded_days,
            "critical_days": r.critical_days,
            "best_day_apy": r.best_day_apy,
            "worst_day_apy": r.worst_day_apy,
            "top_chain_this_week": r.top_chain_this_week,
            "top_chain_apy": r.top_chain_apy,
            "weekly_verdict": r.weekly_verdict,
            "summary_line": r.summary_line,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Weekly Summary Report (MP-610) — 7-day aggregation of daily ops."
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
        help="Compute report and save atomically to data/weekly_summary.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    reporter = WeeklySummaryReport(data_path=args.data_dir)
    report = reporter.generate_report()

    print(reporter.format_telegram_message(report))
    print("\n" + "=" * 60)
    print(report.summary_line)

    if args.run:
        path = reporter.save_report(report)
        print(f"\n[WeeklySummaryReport] ✅ Saved → {path}")
    else:
        print(
            "\n[WeeklySummaryReport] Check mode — no file written (use --run to save)."
        )


if __name__ == "__main__":
    main()
