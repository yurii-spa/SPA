"""
QuarterlySummaryReport (MP-643)
===============================
Агрегирует до 3 последних месяцев из data/monthly_summary.json и формирует
квартальную сводку по APY, доминирующему месячному вердикту, тренду квартала,
топ-цепочке и выносит квартальный вердикт EXCELLENT/GOOD/FAIR/POOR.

Source file consumed:
    data/monthly_summary.json   — ring-buffer месячных сводок
                                   (MonthlySummaryReport, MP-614)

Output file (ring-buffer 8 кварталов):
    data/quarterly_summary.json

Design constraints
------------------
* Pure stdlib — никаких внешних зависимостей.
* Read-only за исключением save_report() — атомарная запись (tmp + os.replace).
* Никогда не падает на happy path; все ошибки загрузки обрабатываются gracefully
  (missing/empty/malformed source → report с available=False).
* Telegram message ≤ 1500 chars.
* НЕ импортирует risk/, execution/, monitoring/, allocator/, cycle_runner.

Public API
----------
``QuarterlySummaryReport(data_path: Optional[str] = None)``

Methods:
    - ``load_monthly_history()``  → list[dict]
    - ``get_last_3_months(history)``  → list[dict]
    - ``compute_quarterly_stats(values, metric_name)``  → QuarterlyStats
    - ``generate_report()``  → QuarterlySummaryReportData
    - ``save_report(report=None)``  → str  (path written)
    - ``format_telegram_message(report=None)``  → str
    - ``to_dict(report=None)``  → dict

CLI
---
``python3 -m spa_core.analytics.quarterly_summary_report --check``   (default, no write)
``python3 -m spa_core.analytics.quarterly_summary_report --run``     (+ atomic save)
``python3 -m spa_core.analytics.quarterly_summary_report --data-dir PATH``

MP-643.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_FILENAME: str = "monthly_summary.json"
_OUTPUT_FILENAME: str = "quarterly_summary.json"
_RING_BUFFER_MAX: int = 8             # храним 8 кварталов
_MONTHS_PER_QUARTER: int = 3
_TELEGRAM_MAX_CHARS: int = 1500
_TELEGRAM_ELLIPSIS: str = "…"

# Trend thresholds (first vs last month avg APY)
_TREND_RISING_DELTA: float = 0.1     # last > first + 0.1 → RISING
_TREND_FALLING_DELTA: float = 0.1    # last < first - 0.1 → FALLING

# Verdict thresholds — scaled ×3 from the monthly module thresholds.
# Monthly: EXCELLENT 6.0 / GOOD 5.0 / FAIR 4.0 → quarterly mean APY same scale.
_EXCELLENT_APY: float = 6.0
_GOOD_APY: float = 5.0
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
class QuarterlyStats:
    """Статистика по одному показателю за квартал."""
    metric_name: str
    values: List[float]       # значения по месяцам (chronological order)
    mean: float
    min: float
    max: float
    trend: str                # "RISING" / "FALLING" / "STABLE"

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "values": list(self.values),
            "mean": self.mean,
            "min": self.min,
            "max": self.max,
            "trend": self.trend,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QuarterlyStats":
        raw_vals = d.get("values", [])
        values = [_safe_float(v) for v in raw_vals] if isinstance(raw_vals, list) else []
        return cls(
            metric_name=str(d.get("metric_name", "")),
            values=values,
            mean=_safe_float(d.get("mean", 0.0)),
            min=_safe_float(d.get("min", 0.0)),
            max=_safe_float(d.get("max", 0.0)),
            trend=str(d.get("trend", "STABLE")),
        )


@dataclass
class QuarterlySummaryReportData:
    """Полная квартальная сводка."""
    generated_at: str         # ISO UTC timestamp
    available: bool           # есть ли данные для агрегации
    quarter_start: str        # month_start первого месяца
    quarter_end: str          # month_end последнего месяца
    months_covered: int       # сколько месяцев реально есть данных

    # APY статистика (по avg каждого месяца)
    apy_stats: QuarterlyStats

    # Лучший / худший месяц
    best_month_apy: float
    worst_month_apy: float

    # Вердикты
    dominant_monthly_verdict: str       # самый частый monthly_verdict
    verdict_distribution: Dict[str, int]

    # Топ цепочка
    top_chain_this_quarter: str
    top_chain_apy: float

    # Квартальный вердикт
    quarterly_verdict: str              # "EXCELLENT" / "GOOD" / "FAIR" / "POOR"
    summary_line: str

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "available": self.available,
            "quarter_start": self.quarter_start,
            "quarter_end": self.quarter_end,
            "months_covered": self.months_covered,
            "apy_stats": self.apy_stats.to_dict(),
            "best_month_apy": self.best_month_apy,
            "worst_month_apy": self.worst_month_apy,
            "dominant_monthly_verdict": self.dominant_monthly_verdict,
            "verdict_distribution": dict(self.verdict_distribution),
            "top_chain_this_quarter": self.top_chain_this_quarter,
            "top_chain_apy": self.top_chain_apy,
            "quarterly_verdict": self.quarterly_verdict,
            "summary_line": self.summary_line,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QuarterlySummaryReportData":
        stats_raw = d.get("apy_stats", {})
        stats = (
            QuarterlyStats.from_dict(stats_raw)
            if isinstance(stats_raw, dict)
            else QuarterlyStats("", [], 0.0, 0.0, 0.0, "STABLE")
        )
        dist_raw = d.get("verdict_distribution", {})
        dist: Dict[str, int] = {}
        if isinstance(dist_raw, dict):
            for k, v in dist_raw.items():
                try:
                    dist[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        return cls(
            generated_at=str(d.get("generated_at", "")),
            available=bool(d.get("available", False)),
            quarter_start=str(d.get("quarter_start", "")),
            quarter_end=str(d.get("quarter_end", "")),
            months_covered=int(_safe_float(d.get("months_covered", 0))),
            apy_stats=stats,
            best_month_apy=_safe_float(d.get("best_month_apy", 0.0)),
            worst_month_apy=_safe_float(d.get("worst_month_apy", 0.0)),
            dominant_monthly_verdict=str(d.get("dominant_monthly_verdict", _VERDICT_POOR)),
            verdict_distribution=dist,
            top_chain_this_quarter=str(d.get("top_chain_this_quarter", "")),
            top_chain_apy=_safe_float(d.get("top_chain_apy", 0.0)),
            quarterly_verdict=str(d.get("quarterly_verdict", _VERDICT_POOR)),
            summary_line=str(d.get("summary_line", "")),
        )


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
# QuarterlySummaryReport
# ---------------------------------------------------------------------------

class QuarterlySummaryReport:
    """
    Aggregate last 3 monthly summary reports into a quarterly summary.

    Parameters
    ----------
    data_path:
        Path to the ``data/`` directory. Defaults to the ``data/`` folder
        next to the project root (resolved relative to this file).
    """

    SOURCE_FILE: str = _SOURCE_FILENAME
    OUTPUT_FILE: str = _OUTPUT_FILENAME
    RING_BUFFER_SIZE: int = _RING_BUFFER_MAX
    MONTHS_PER_QUARTER: int = _MONTHS_PER_QUARTER

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data")
        self.data_path = Path(data_path)
        self._report: Optional[QuarterlySummaryReportData] = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_monthly_history(self) -> List[dict]:
        """
        Read data/monthly_summary.json and return all history entries.

        Returns [] if the file is missing, unreadable, malformed, or has no
        history.
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

    def get_last_3_months(self, history: List[dict]) -> List[dict]:
        """
        Return the last 3 entries from the ring-buffer, sorted ascending by
        generated_at. Returns fewer entries if the buffer has less than 3.
        """
        if not history:
            return []

        def _sort_key(entry: dict) -> str:
            ts = entry.get("generated_at", "")
            return ts if isinstance(ts, str) else ""

        sorted_history = sorted(history, key=_sort_key)
        return sorted_history[-self.MONTHS_PER_QUARTER:]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    def compute_quarterly_stats(
        self, values: List[float], metric_name: str
    ) -> QuarterlyStats:
        """
        Compute mean, min, max, and trend for a list of float values.

        If values is empty, returns a QuarterlyStats with mean=min=max=0.0 and
        trend=STABLE.
        """
        if not values:
            return QuarterlyStats(
                metric_name=metric_name,
                values=[],
                mean=0.0,
                min=0.0,
                max=0.0,
                trend="STABLE",
            )

        mean = sum(values) / len(values)
        return QuarterlyStats(
            metric_name=metric_name,
            values=list(values),
            mean=mean,
            min=min(values),
            max=max(values),
            trend=_compute_trend(values),
        )

    def _determine_verdict(self, mean_apy: float) -> str:
        """
        Compute quarterly verdict using thresholds scaled ×3 from the monthly
        module (same APY scale).

        EXCELLENT : mean APY >= 6.0%
        GOOD      : mean APY >= 5.0%
        FAIR      : mean APY >= 4.0%
        POOR      : otherwise
        """
        if mean_apy >= _EXCELLENT_APY:
            return _VERDICT_EXCELLENT
        if mean_apy >= _GOOD_APY:
            return _VERDICT_GOOD
        if mean_apy >= _FAIR_APY:
            return _VERDICT_FAIR
        return _VERDICT_POOR

    def _compute_dominant_verdict(self, verdicts: List[str]) -> str:
        """
        Return the most frequent verdict among the monthly verdicts.

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
            return (
                _VERDICT_PRIORITY.index(v)
                if v in _VERDICT_PRIORITY
                else len(_VERDICT_PRIORITY)
            )

        tied.sort(key=_priority)
        return tied[0]

    def _extract_top_chain(self, months: List[dict]) -> Tuple[str, float]:
        """
        Extract the most frequent chain across the months (by
        ``top_chain_this_month``), with its average ``top_chain_apy``.

        On a tie in frequency, prefer the chain with the higher average APY.
        Returns (chain_name, avg_apy). Falls back to ("", 0.0) if no chain data.
        """
        chain_apys: Dict[str, List[float]] = {}
        chain_counts: Dict[str, int] = {}

        for month in months:
            chain = month.get("top_chain_this_month", "")
            if not isinstance(chain, str) or not chain:
                continue
            apy = _safe_float(month.get("top_chain_apy", 0.0))
            chain_apys.setdefault(chain, []).append(apy)
            chain_counts[chain] = chain_counts.get(chain, 0) + 1

        if not chain_counts:
            return ("", 0.0)

        def _avg(c: str) -> float:
            vals = chain_apys.get(c, [])
            return sum(vals) / len(vals) if vals else 0.0

        # Most frequent; tie-break by higher average APY.
        best_chain = max(chain_counts, key=lambda c: (chain_counts[c], _avg(c)))
        return (best_chain, _avg(best_chain))

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    def _empty_report(self, generated_at: str) -> QuarterlySummaryReportData:
        """Return a zero-filled 'no data available' report (never crashes)."""
        empty_stats = self.compute_quarterly_stats([], "monthly_apy_avg_pct")
        return QuarterlySummaryReportData(
            generated_at=generated_at,
            available=False,
            quarter_start="",
            quarter_end="",
            months_covered=0,
            apy_stats=empty_stats,
            best_month_apy=0.0,
            worst_month_apy=0.0,
            dominant_monthly_verdict=_VERDICT_POOR,
            verdict_distribution={},
            top_chain_this_quarter="",
            top_chain_apy=0.0,
            quarterly_verdict=_VERDICT_POOR,
            summary_line="Quarter: no data available",
        )

    def generate_report(self) -> QuarterlySummaryReportData:
        """
        Generate the quarterly summary report.

        If 0 months of data are available, returns a zero-filled report with
        available=False and verdict=POOR.
        """
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()

        history = self.load_monthly_history()
        months = self.get_last_3_months(history)

        if not months:
            self._report = self._empty_report(generated_at)
            return self._report

        first_month = months[0]
        last_month = months[-1]
        quarter_start = (
            first_month.get("month_start", "")
            or first_month.get("generated_at", "")
        )
        quarter_end = (
            last_month.get("month_end", "")
            or last_month.get("generated_at", "")
        )
        if not isinstance(quarter_start, str):
            quarter_start = ""
        if not isinstance(quarter_end, str):
            quarter_end = ""

        # APY values = avg/mean APY of each month
        apy_values: List[float] = []
        for month in months:
            stats = month.get("apy_stats", {})
            if isinstance(stats, dict):
                # monthly module uses "avg"; tolerate "mean" as well
                if "avg" in stats:
                    apy_values.append(_safe_float(stats.get("avg", 0.0)))
                else:
                    apy_values.append(_safe_float(stats.get("mean", 0.0)))
            else:
                apy_values.append(0.0)

        apy_stats = self.compute_quarterly_stats(apy_values, "monthly_apy_avg_pct")

        best_month_apy = max(apy_values) if apy_values else 0.0
        worst_month_apy = min(apy_values) if apy_values else 0.0

        # Verdict distribution + dominant monthly verdict
        verdicts: List[str] = []
        verdict_distribution: Dict[str, int] = {}
        for month in months:
            v = month.get("monthly_verdict", "")
            if isinstance(v, str) and v:
                verdicts.append(v)
                verdict_distribution[v] = verdict_distribution.get(v, 0) + 1
        dominant_verdict = self._compute_dominant_verdict(verdicts)

        # Top chain
        top_chain, top_chain_apy = self._extract_top_chain(months)

        # Quarterly verdict (thresholds scaled ×3 from monthly module)
        quarterly_verdict = self._determine_verdict(apy_stats.mean)

        months_covered = len(months)
        summary_line = (
            f"Quarter: APY mean {apy_stats.mean:.2f}% "
            f"({apy_stats.min:.2f}→{apy_stats.max:.2f}%), "
            f"{months_covered}/{self.MONTHS_PER_QUARTER} months, "
            f"verdict {quarterly_verdict}"
        )

        self._report = QuarterlySummaryReportData(
            generated_at=generated_at,
            available=True,
            quarter_start=quarter_start,
            quarter_end=quarter_end,
            months_covered=months_covered,
            apy_stats=apy_stats,
            best_month_apy=best_month_apy,
            worst_month_apy=worst_month_apy,
            dominant_monthly_verdict=dominant_verdict,
            verdict_distribution=verdict_distribution,
            top_chain_this_quarter=top_chain,
            top_chain_apy=top_chain_apy,
            quarterly_verdict=quarterly_verdict,
            summary_line=summary_line,
        )
        return self._report

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: Optional[QuarterlySummaryReportData] = None) -> str:
        """
        Atomically save the quarterly summary to data/quarterly_summary.json.

        Maintains a ring-buffer of up to RING_BUFFER_SIZE (8) reports in the
        ``history`` list. Calls generate_report() if no report provided.

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
            "source": "quarterly_summary_report",
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
            "source": "quarterly_summary_report",
            "ring_buffer_max": self.RING_BUFFER_SIZE,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp → os.replace
        out_dir = os.path.dirname(output_path) or "."
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass
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
        self, report: Optional[QuarterlySummaryReportData] = None
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
            "RISING":  "📈 RISING quarter",
            "FALLING": "📉 FALLING quarter",
            "STABLE":  "➡️ STABLE quarter",
        }

        if not r.available:
            lines = [
                "🗓 Quarterly Summary — no data available",
                f"⏱ {r.generated_at[:19]}Z",
            ]
            msg = "\n".join(lines)
            if len(msg) > _TELEGRAM_MAX_CHARS:
                msg = msg[: _TELEGRAM_MAX_CHARS - len(_TELEGRAM_ELLIPSIS)] + _TELEGRAM_ELLIPSIS
            return msg

        verdict_emoji = _VERDICT_EMOJI.get(r.quarterly_verdict, "⚪")
        trend_arrow = _trend_arrow(r.apy_stats.trend)
        trend_label = _TREND_LABEL.get(r.apy_stats.trend, "➡️ STABLE quarter")

        lines: List[str] = [
            f"🗓 Quarterly Summary — {r.quarterly_verdict} {verdict_emoji}",
            f"Months covered: {r.months_covered}/{self.MONTHS_PER_QUARTER}",
            (
                f"APY: mean {r.apy_stats.mean:.2f}%"
                f" | min {r.apy_stats.min:.2f}%"
                f" | max {r.apy_stats.max:.2f}%"
                f" | trend {trend_arrow}"
            ),
            f"Best month: {r.best_month_apy:.2f}% | Worst: {r.worst_month_apy:.2f}%",
            f"Dominant monthly verdict: {r.dominant_monthly_verdict}",
        ]

        if r.top_chain_this_quarter:
            lines.append(
                f"Top chain: {r.top_chain_this_quarter} {r.top_chain_apy:.1f}%"
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

    def to_dict(self, report: Optional[QuarterlySummaryReportData] = None) -> dict:
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
        description="Quarterly Summary Report (MP-643) — 3-month aggregation of monthly summaries."
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
        help="Compute report and save atomically to data/quarterly_summary.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    reporter = QuarterlySummaryReport(data_path=args.data_dir)
    report = reporter.generate_report()

    print(reporter.format_telegram_message(report))
    print("\n" + "=" * 60)
    print(report.summary_line)

    if args.run:
        path = reporter.save_report(report)
        print(f"\n[QuarterlySummaryReport] ✅ Saved → {path}")
    else:
        print(
            "\n[QuarterlySummaryReport] Check mode — no file written (use --run to save)."
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
