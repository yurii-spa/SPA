"""
MonthlySummaryReport (MP-614)
=============================
Агрегирует до 4 последних недель из data/weekly_summary.json и формирует
месячную сводку по APY, статусам дней, доминирующему вердикту, топ-цепочкам
и выносит месячный вердикт EXCELLENT/GOOD/FAIR/POOR.

Source file consumed:
    data/weekly_summary.json   — ring-buffer до 12 weekly summary report-ов

Output file (ring-buffer 12 месяцев):
    data/monthly_summary.json

Design constraints
------------------
* Pure stdlib — никаких внешних зависимостей.
* Read-only за исключением save_report() — атомарная запись (tmp + os.replace).
* Никогда не падает на happy path; все ошибки загрузки обрабатываются gracefully.
* Telegram message ≤ 1500 chars.
* НЕ импортирует risk/, execution/, monitoring/, allocator/, cycle_runner.

Public API
----------
``MonthlySummaryReport(data_path: Optional[str] = None)``

Methods:
    - ``load_weekly_history()``  → list[dict]
    - ``get_last_4_weeks(history)``  → list[dict]
    - ``compute_monthly_stats(values, metric_name)``  → MonthlyStats
    - ``generate_report()``  → MonthlySummaryReportData
    - ``save_report(report=None)``  → str  (path written)
    - ``format_telegram_message(report=None)``  → str
    - ``to_dict(report=None)``  → dict

CLI
---
``python3 -m spa_core.analytics.monthly_summary_report --check``   (default, no write)
``python3 -m spa_core.analytics.monthly_summary_report --run``     (+ atomic save)
``python3 -m spa_core.analytics.monthly_summary_report --data-dir PATH``

MP-614.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_FILENAME: str = "weekly_summary.json"
_OUTPUT_FILENAME: str = "monthly_summary.json"
_RING_BUFFER_MAX: int = 12           # храним 12 месяцев
_WEEKS_PER_MONTH: int = 4
_TELEGRAM_MAX_CHARS: int = 1500
_TELEGRAM_ELLIPSIS: str = "…"

# Trend thresholds
_TREND_RISING_DELTA: float = 0.1    # last > first + 0.1 → RISING
_TREND_FALLING_DELTA: float = 0.1   # last < first - 0.1 → FALLING

# Verdict thresholds (op_days scaled to month: was 5/4 per week → 20/16 per month)
_EXCELLENT_APY: float = 6.0
_EXCELLENT_OP_DAYS: int = 20
_GOOD_APY: float = 5.0
_GOOD_OP_DAYS: int = 16
_FAIR_APY: float = 4.0

# Verdict values
_VERDICT_EXCELLENT: str = "EXCELLENT"
_VERDICT_GOOD: str = "GOOD"
_VERDICT_FAIR: str = "FAIR"
_VERDICT_POOR: str = "POOR"

# Verdict priority for tie-breaking (best first)
_VERDICT_PRIORITY: List[str] = [
    _VERDICT_EXCELLENT,
    _VERDICT_GOOD,
    _VERDICT_FAIR,
    _VERDICT_POOR,
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MonthlyStats:
    """Статистика по одному показателю за месяц."""
    metric_name: str
    values: List[float]       # значения по неделям (chronological order)
    avg: float
    min: float
    max: float
    trend: str                # "RISING" / "FALLING" / "STABLE"

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "values": list(self.values),
            "avg": self.avg,
            "min": self.min,
            "max": self.max,
            "trend": self.trend,
        }


@dataclass
class MonthlySummaryReportData:
    """Полная месячная сводка."""
    generated_at: str         # ISO UTC timestamp
    month_start: str          # week_start первой недели
    month_end: str            # week_end последней недели
    weeks_covered: int        # сколько недель реально есть данных

    # APY статистика (по avg каждой недели)
    apy_stats: MonthlyStats

    # Статус дней (суммарно за месяц)
    total_operational_days: int
    total_degraded_days: int
    total_critical_days: int
    best_week_apy: float
    worst_week_apy: float

    # Вердикты
    dominant_verdict: str            # самый частый weekly_verdict за месяц
    verdict_distribution: Dict[str, int]

    # Топ цепочка
    top_chain_this_month: str
    top_chain_apy: float

    # Месячный вердикт
    monthly_verdict: str             # "EXCELLENT" / "GOOD" / "FAIR" / "POOR"
    summary_line: str

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "month_start": self.month_start,
            "month_end": self.month_end,
            "weeks_covered": self.weeks_covered,
            "apy_stats": self.apy_stats.to_dict(),
            "total_operational_days": self.total_operational_days,
            "total_degraded_days": self.total_degraded_days,
            "total_critical_days": self.total_critical_days,
            "best_week_apy": self.best_week_apy,
            "worst_week_apy": self.worst_week_apy,
            "dominant_verdict": self.dominant_verdict,
            "verdict_distribution": dict(self.verdict_distribution),
            "top_chain_this_month": self.top_chain_this_month,
            "top_chain_apy": self.top_chain_apy,
            "monthly_verdict": self.monthly_verdict,
            "summary_line": self.summary_line,
        }


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
# MonthlySummaryReport
# ---------------------------------------------------------------------------

class MonthlySummaryReport:
    """
    Aggregate last 4 weekly summary reports into a monthly summary.

    Parameters
    ----------
    data_path:
        Path to the ``data/`` directory. Defaults to the ``data/`` folder
        next to the project root (resolved relative to this file).
    """

    SOURCE_FILE: str = _SOURCE_FILENAME
    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX
    WEEKS_PER_MONTH: int = _WEEKS_PER_MONTH

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data")
        self.data_path = Path(data_path)
        self._report: Optional[MonthlySummaryReportData] = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_weekly_history(self) -> List[dict]:
        """
        Read data/weekly_summary.json and return all history entries.

        Returns [] if the file is missing, unreadable, or has no history.
        """
        path = self.data_path / self.SOURCE_FILE
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return []
            history = data.get("history", [])
            if not isinstance(history, list):
                return []
            return [item for item in history if isinstance(item, dict)]
        except Exception:
            return []

    def get_last_4_weeks(self, history: List[dict]) -> List[dict]:
        """
        Return the last 4 entries from the ring-buffer, sorted ascending by
        generated_at. Returns fewer entries if the buffer has less than 4.
        """
        if not history:
            return []

        def _sort_key(entry: dict) -> str:
            ts = entry.get("generated_at", "")
            return ts if isinstance(ts, str) else ""

        sorted_history = sorted(history, key=_sort_key)
        return sorted_history[-self.WEEKS_PER_MONTH:]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def compute_monthly_stats(
        self, values: List[float], metric_name: str
    ) -> MonthlyStats:
        """
        Compute avg, min, max, and trend for a list of float values.

        If values is empty, returns a MonthlyStats with avg=min=max=0.0 and
        trend=STABLE.
        """
        if not values:
            return MonthlyStats(
                metric_name=metric_name,
                values=[],
                avg=0.0,
                min=0.0,
                max=0.0,
                trend="STABLE",
            )

        avg = sum(values) / len(values)
        return MonthlyStats(
            metric_name=metric_name,
            values=list(values),
            avg=avg,
            min=min(values),
            max=max(values),
            trend=_compute_trend(values),
        )

    def _determine_verdict(self, avg_apy: float, op_days: int) -> str:
        """
        Compute monthly verdict.

        EXCELLENT : avg APY > 6.0% AND ≥ 20 operational days
        GOOD      : avg APY > 5.0% OR ≥ 16 operational days
        FAIR      : avg APY > 4.0%
        POOR      : otherwise
        """
        if avg_apy > _EXCELLENT_APY and op_days >= _EXCELLENT_OP_DAYS:
            return _VERDICT_EXCELLENT
        if avg_apy > _GOOD_APY or op_days >= _GOOD_OP_DAYS:
            return _VERDICT_GOOD
        if avg_apy > _FAIR_APY:
            return _VERDICT_FAIR
        return _VERDICT_POOR

    def _compute_dominant_verdict(self, verdicts: List[str]) -> str:
        """
        Return the most frequent verdict among the weekly verdicts.

        On a tie, pick the best by priority EXCELLENT > GOOD > FAIR > POOR.
        Empty list → "POOR".
        """
        if not verdicts:
            return _VERDICT_POOR

        counts: Dict[str, int] = {}
        for v in verdicts:
            if not isinstance(v, str) or not v:
                continue
            counts[v] = counts.get(v, 0) + 1

        if not counts:
            return _VERDICT_POOR

        max_count = max(counts.values())
        tied = [v for v, c in counts.items() if c == max_count]

        # Among tied, prefer highest priority (lowest index in priority list).
        def _priority(v: str) -> int:
            return _VERDICT_PRIORITY.index(v) if v in _VERDICT_PRIORITY else len(_VERDICT_PRIORITY)

        tied.sort(key=_priority)
        return tied[0]

    def _extract_top_chain(self, weeks: List[dict]) -> Tuple[str, float]:
        """
        Extract the chain with the highest average ``top_chain_apy`` across
        all weeks, aggregating by ``top_chain_this_week``.

        Returns (chain_name, avg_apy). Falls back to ("", 0.0) if no chain data.
        """
        chain_apys: Dict[str, List[float]] = {}

        for week in weeks:
            chain = week.get("top_chain_this_week", "")
            if not isinstance(chain, str) or not chain:
                continue
            apy = _safe_float(week.get("top_chain_apy", 0.0))
            chain_apys.setdefault(chain, []).append(apy)

        if not chain_apys:
            return ("", 0.0)

        best_chain = max(
            chain_apys, key=lambda c: sum(chain_apys[c]) / len(chain_apys[c])
        )
        best_avg = sum(chain_apys[best_chain]) / len(chain_apys[best_chain])
        return (best_chain, best_avg)

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    def generate_report(self) -> MonthlySummaryReportData:
        """
        Generate the monthly summary report.

        If 0 weeks of data are available, returns a zero-filled report with
        verdict=POOR.
        """
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()

        history = self.load_weekly_history()
        weeks = self.get_last_4_weeks(history)

        if not weeks:
            empty_stats = self.compute_monthly_stats([], "weekly_apy_avg_pct")
            self._report = MonthlySummaryReportData(
                generated_at=generated_at,
                month_start="",
                month_end="",
                weeks_covered=0,
                apy_stats=empty_stats,
                total_operational_days=0,
                total_degraded_days=0,
                total_critical_days=0,
                best_week_apy=0.0,
                worst_week_apy=0.0,
                dominant_verdict=_VERDICT_POOR,
                verdict_distribution={},
                top_chain_this_month="",
                top_chain_apy=0.0,
                monthly_verdict=_VERDICT_POOR,
                summary_line="Month: no data available",
            )
            return self._report

        # Timestamps: month_start from first week's week_start, month_end from
        # last week's week_end (fall back to generated_at if missing).
        first_week = weeks[0]
        last_week = weeks[-1]
        month_start = first_week.get("week_start", "") or first_week.get("generated_at", "")
        month_end = last_week.get("week_end", "") or last_week.get("generated_at", "")
        if not isinstance(month_start, str):
            month_start = ""
        if not isinstance(month_end, str):
            month_end = ""

        # APY values = avg APY of each week
        apy_values: List[float] = []
        for week in weeks:
            stats = week.get("apy_stats", {})
            if isinstance(stats, dict):
                apy_values.append(_safe_float(stats.get("avg", 0.0)))
            else:
                apy_values.append(0.0)

        apy_stats = self.compute_monthly_stats(apy_values, "weekly_apy_avg_pct")

        # Sum day-status counts across weeks
        total_operational_days = 0
        total_degraded_days = 0
        total_critical_days = 0
        for week in weeks:
            total_operational_days += int(_safe_float(week.get("operational_days", 0)))
            total_degraded_days += int(_safe_float(week.get("degraded_days", 0)))
            total_critical_days += int(_safe_float(week.get("critical_days", 0)))

        best_week_apy = max(apy_values) if apy_values else 0.0
        worst_week_apy = min(apy_values) if apy_values else 0.0

        # Verdict distribution + dominant verdict
        verdicts: List[str] = []
        verdict_distribution: Dict[str, int] = {}
        for week in weeks:
            v = week.get("weekly_verdict", "")
            if isinstance(v, str) and v:
                verdicts.append(v)
                verdict_distribution[v] = verdict_distribution.get(v, 0) + 1
        dominant_verdict = self._compute_dominant_verdict(verdicts)

        # Top chain
        top_chain, top_chain_apy = self._extract_top_chain(weeks)

        # Monthly verdict
        monthly_verdict = self._determine_verdict(apy_stats.avg, total_operational_days)

        # Summary line
        weeks_covered = len(weeks)
        summary_line = (
            f"Month: APY avg {apy_stats.avg:.2f}% "
            f"({apy_stats.min:.2f}→{apy_stats.max:.2f}%), "
            f"{weeks_covered}/{self.WEEKS_PER_MONTH} weeks, "
            f"{total_operational_days} operational days"
        )

        self._report = MonthlySummaryReportData(
            generated_at=generated_at,
            month_start=month_start,
            month_end=month_end,
            weeks_covered=weeks_covered,
            apy_stats=apy_stats,
            total_operational_days=total_operational_days,
            total_degraded_days=total_degraded_days,
            total_critical_days=total_critical_days,
            best_week_apy=best_week_apy,
            worst_week_apy=worst_week_apy,
            dominant_verdict=dominant_verdict,
            verdict_distribution=verdict_distribution,
            top_chain_this_month=top_chain,
            top_chain_apy=top_chain_apy,
            monthly_verdict=monthly_verdict,
            summary_line=summary_line,
        )
        return self._report

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: Optional[MonthlySummaryReportData] = None) -> str:
        """
        Atomically save the monthly summary to data/monthly_summary.json.

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

        existing: dict = {
            "schema_version": 1,
            "source": "monthly_summary_report",
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

        if len(history) > self.RING_BUFFER_SIZE:
            history = history[-self.RING_BUFFER_SIZE:]

        payload = {
            "schema_version": 1,
            "source": "monthly_summary_report",
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
        self, report: Optional[MonthlySummaryReportData] = None
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
            _VERDICT_EXCELLENT: "🟢",
            _VERDICT_GOOD:      "✅",
            _VERDICT_FAIR:      "🟡",
            _VERDICT_POOR:      "🔴",
        }

        _TREND_LABEL = {
            "RISING":  "📈 RISING month",
            "FALLING": "📉 FALLING month",
            "STABLE":  "➡️ STABLE month",
        }

        verdict_emoji = _VERDICT_EMOJI.get(r.monthly_verdict, "⚪")
        trend_arrow = _trend_arrow(r.apy_stats.trend)
        trend_label = _TREND_LABEL.get(r.apy_stats.trend, "➡️ STABLE month")

        lines: List[str] = [
            f"🗓 Monthly Summary — {r.monthly_verdict} {verdict_emoji}",
            f"Weeks covered: {r.weeks_covered}/{self.WEEKS_PER_MONTH} | "
            f"Operational days: {r.total_operational_days}",
            (
                f"APY: avg {r.apy_stats.avg:.2f}%"
                + (
                    f" | min {r.apy_stats.min:.2f}%"
                    f" | max {r.apy_stats.max:.2f}%"
                    f" | trend {trend_arrow}"
                    if r.weeks_covered > 0
                    else ""
                )
            ),
        ]

        if r.weeks_covered > 0:
            lines.append(
                f"Best week: {r.best_week_apy:.2f}% | Worst: {r.worst_week_apy:.2f}%"
            )
            lines.append(f"Dominant verdict: {r.dominant_verdict}")

        if r.top_chain_this_month:
            lines.append(
                f"Top chain: {r.top_chain_this_month} {r.top_chain_apy:.1f}%"
            )

        if r.total_degraded_days > 0 or r.total_critical_days > 0:
            lines.append(
                f"⚠️ Degraded: {r.total_degraded_days}d | "
                f"Critical: {r.total_critical_days}d"
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

    def to_dict(self, report: Optional[MonthlySummaryReportData] = None) -> dict:
        """
        Return the report as a plain JSON-serializable dict.

        Calls generate_report() if no report is provided or cached.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report
        assert report is not None
        return report.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Monthly Summary Report (MP-614) — 4-week aggregation of weekly summaries."
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
        help="Compute report and save atomically to data/monthly_summary.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    reporter = MonthlySummaryReport(data_path=args.data_dir)
    report = reporter.generate_report()

    print(reporter.format_telegram_message(report))
    print("\n" + "=" * 60)
    print(report.summary_line)

    if args.run:
        path = reporter.save_report(report)
        print(f"\n[MonthlySummaryReport] ✅ Saved → {path}")
    else:
        print(
            "\n[MonthlySummaryReport] Check mode — no file written (use --run to save)."
        )


if __name__ == "__main__":
    main()
