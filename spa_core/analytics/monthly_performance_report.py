"""Monthly Performance Report (MP-1252).

Produces a detailed monthly performance report for the live paper track,
comparing SPA against the "lazy Aave" benchmark (park 100% in Aave V3 at
``BENCHMARK_AAVE_APY``):

  * Period (e.g. first partial month 2026-06-10 → 2026-06-21).
  * Active-strategy allocation snapshot (latest positions).
  * Daily SPA returns vs benchmark daily accrual (apy / 365 per day).
  * Cumulative alpha = paper cumulative return − benchmark cumulative return.
  * Capital framing: "lazy Aave → $X, SPA → $Y, alpha → $Z".
  * Risk metrics: annualised Sharpe, max daily drawdown, days positive.

Outputs (atomic):
  * ``data/monthly_reports/<YYYY-MM>.json``
  * ``data/monthly_reports/<YYYY-MM>.md``

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace (via spa_core.utils.atomic).
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.monthly_performance_report --check
    python3 -m spa_core.analytics.monthly_performance_report --run
    python3 -m spa_core.analytics.monthly_performance_report --run --month 2026-06

MP-1252.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.analytics.strategy_benchmark_tracker import (
    BENCHMARK_AAVE_APY,
    DEFAULT_ACTIVE_STRATEGY,
)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_REPORTS_SUBDIR = "monthly_reports"

_DAYS_PER_YEAR = 365.0
_INITIAL_CAPITAL = 100_000.0


def _safe_float(val: Any) -> Optional[float]:
    if isinstance(val, bool):
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _stdev(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# MonthlyPerformanceReport
# ---------------------------------------------------------------------------


class MonthlyPerformanceReport:
    """Builds a monthly SPA-vs-lazy-Aave performance report.

    Parameters
    ----------
    data_dir : str or Path, optional
        Data directory. Defaults to repo ``data/``.
    month : str
        Target month ``"YYYY-MM"`` (default ``"2026-06"``).
    benchmark_apy : float
        Lazy-Aave benchmark APY in % (default 3.10).
    active_strategy_id : str
        Live strategy id label (default ``"S0"``).
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        month: str = "2026-06",
        benchmark_apy: float = BENCHMARK_AAVE_APY,
        active_strategy_id: str = DEFAULT_ACTIVE_STRATEGY,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.month = month
        self.benchmark_apy = float(benchmark_apy)
        self.active_strategy_id = (active_strategy_id or "").upper()

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def _load_equity(self) -> List[Dict[str, Any]]:
        path = self.data_dir / "equity_curve_daily.json"
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        daily = raw.get("daily") if isinstance(raw, dict) else None
        return [d for d in daily if isinstance(d, dict)] if isinstance(daily, list) else []

    def _month_days(self) -> List[Dict[str, Any]]:
        """Real-track entries within the target month (exclude warmup)."""
        out = []
        for d in self._load_equity():
            date = d.get("date", "")
            if not isinstance(date, str) or not date.startswith(self.month):
                continue
            if d.get("is_warmup", False):
                continue
            out.append(d)
        return out

    # -----------------------------------------------------------------------
    # Core computation
    # -----------------------------------------------------------------------

    def build(self) -> Dict[str, Any]:
        """Compute the full monthly report dict."""
        days = self._month_days()
        bench_apy = self.benchmark_apy
        bench_daily_pct = bench_apy / _DAYS_PER_YEAR  # benchmark daily return, %

        if not days:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "month": self.month,
                "available": False,
                "active_strategy_id": self.active_strategy_id,
                "benchmark_aave_apy": round(bench_apy, 4),
                "note": "No real (non-warmup) track data for this month.",
            }

        first, last = days[0], days[-1]
        start_equity = _safe_float(first.get("open_equity")) or _INITIAL_CAPITAL
        end_equity = _safe_float(last.get("close_equity")) or _safe_float(
            last.get("equity")
        ) or start_equity

        # Per-day comparison vs benchmark.
        daily_rows: List[Dict[str, Any]] = []
        spa_daily_returns: List[float] = []  # fractional, for risk metrics
        positive_days = 0
        worst_daily_return = None  # max daily drawdown = most negative daily return
        for d in days:
            r_pct = _safe_float(d.get("daily_return_pct")) or 0.0
            spa_daily_returns.append(r_pct / 100.0)
            if r_pct > 0:
                positive_days += 1
            if worst_daily_return is None or r_pct < worst_daily_return:
                worst_daily_return = r_pct
            daily_rows.append({
                "date": d.get("date"),
                "spa_return_pct": round(r_pct, 6),
                "benchmark_return_pct": round(bench_daily_pct, 6),
                "daily_alpha_pct": round(r_pct - bench_daily_pct, 6),
                "spa_equity": _safe_float(d.get("close_equity")) or _safe_float(d.get("equity")),
            })

        span_days = len(days)
        # Cumulative SPA vs benchmark over the month, compounded from start_equity.
        spa_total_return_pct = (end_equity / start_equity - 1.0) * 100.0
        bench_daily_frac = bench_apy / 100.0 / _DAYS_PER_YEAR
        lazy_aave_value = start_equity * (1.0 + bench_daily_frac) ** span_days
        bench_total_return_pct = (lazy_aave_value / start_equity - 1.0) * 100.0
        cumulative_alpha_pct = spa_total_return_pct - bench_total_return_pct
        alpha_usd = end_equity - lazy_aave_value

        # Annualised projection of realised return.
        annualized_pct = (
            (1.0 + spa_total_return_pct / 100.0) ** (_DAYS_PER_YEAR / span_days) - 1.0
        ) * 100.0

        # Risk metrics.
        mean_daily = sum(spa_daily_returns) / len(spa_daily_returns)
        sd_daily = _stdev(spa_daily_returns)
        if sd_daily > 0:
            sharpe = (mean_daily / sd_daily) * math.sqrt(_DAYS_PER_YEAR)
            sharpe_val: Optional[float] = round(sharpe, 4)
        else:
            # Monotonic accrual → zero downside variance → Sharpe undefined.
            sharpe_val = None
        # "max daily drawdown" framed as the worst single-day return.
        max_daily_drawdown_pct = round(min(0.0, worst_daily_return or 0.0), 6)

        allocation = self._allocation_snapshot(last)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "monthly_performance_report",
            "mp": "MP-1252",
            "month": self.month,
            "available": True,
            "active_strategy_id": self.active_strategy_id,
            "period": {
                "start": first.get("date"),
                "end": last.get("date"),
                "track_days": span_days,
            },
            "capital": {
                "start_equity_usd": round(start_equity, 2),
                "spa_value_usd": round(end_equity, 2),
                "lazy_aave_value_usd": round(lazy_aave_value, 2),
                "alpha_usd": round(alpha_usd, 2),
            },
            "returns": {
                "spa_total_return_pct": round(spa_total_return_pct, 4),
                "benchmark_total_return_pct": round(bench_total_return_pct, 4),
                "cumulative_alpha_pct": round(cumulative_alpha_pct, 4),
                "spa_annualized_pct": round(annualized_pct, 4),
                "benchmark_apy_pct": round(bench_apy, 4),
                "alpha_annualized_pct": round(annualized_pct - bench_apy, 4),
            },
            "risk": {
                "sharpe_annualized": sharpe_val,
                "max_daily_drawdown_pct": max_daily_drawdown_pct,
                "days_positive": positive_days,
                "days_total": span_days,
                "daily_volatility_pct": round(sd_daily * 100.0, 6),
            },
            "allocation": allocation,
            "daily": daily_rows,
            "note": (
                "Stablecoin yield accrual is near-monotonic, so daily volatility is "
                "tiny and annualised Sharpe is structurally high (null when zero "
                "variance) — a property of the asset class, not an error."
            ),
        }

    def _allocation_snapshot(self, last_day: Dict[str, Any]) -> Dict[str, Any]:
        """Latest active-strategy allocation (protocol → USD and weight %)."""
        positions = last_day.get("positions")
        if not isinstance(positions, dict) or not positions:
            return {"total_usd": 0.0, "positions": []}
        clean = {
            k: (_safe_float(v) or 0.0)
            for k, v in positions.items()
            if (_safe_float(v) or 0.0) > 0
        }
        total = sum(clean.values())
        rows = [
            {
                "protocol": k,
                "usd": round(v, 2),
                "weight_pct": round(v / total * 100.0, 4) if total > 0 else 0.0,
            }
            for k, v in sorted(clean.items(), key=lambda kv: kv[1], reverse=True)
        ]
        return {"total_usd": round(total, 2), "num_positions": len(rows), "positions": rows}

    # -----------------------------------------------------------------------
    # Markdown rendering
    # -----------------------------------------------------------------------

    def render_markdown(self, report: Dict[str, Any]) -> str:
        if not report.get("available"):
            return (
                f"# SPA Monthly Performance — {report.get('month')}\n\n"
                f"_{report.get('note', 'No data available.')}_\n"
            )

        per = report["period"]
        cap = report["capital"]
        ret = report["returns"]
        risk = report["risk"]
        alloc = report["allocation"]

        lines: List[str] = []
        lines.append(f"# SPA Monthly Performance — {report['month']}")
        lines.append("")
        lines.append(
            f"**Period:** {per['start']} → {per['end']} "
            f"({per['track_days']} live days)  |  "
            f"**Active strategy:** {report['active_strategy_id']}  |  "
            f"**Benchmark:** lazy Aave @ {ret['benchmark_apy_pct']:.2f}%"
        )
        lines.append("")
        lines.append("## Headline")
        lines.append("")
        lines.append(f"- **Paper APY (annualised):** {ret['spa_annualized_pct']:.2f}%")
        lines.append(f"- **Lazy-Aave benchmark:** {ret['benchmark_apy_pct']:.2f}%")
        lines.append(f"- **Alpha vs Aave:** {ret['alpha_annualized_pct']:+.2f}%/yr")
        lines.append("")
        lines.append("## Capital — what the month was worth")
        lines.append("")
        lines.append(f"- If we had used **lazy Aave**: **${cap['lazy_aave_value_usd']:,.2f}**")
        lines.append(f"- With **SPA**: **${cap['spa_value_usd']:,.2f}**")
        lines.append(f"- **Alpha:** **${cap['alpha_usd']:+,.2f}**")
        lines.append("")
        lines.append("## Returns")
        lines.append("")
        lines.append("| Metric | SPA | Lazy Aave | Alpha |")
        lines.append("|---|--:|--:|--:|")
        lines.append(
            f"| Cumulative return | {ret['spa_total_return_pct']:+.4f}% | "
            f"{ret['benchmark_total_return_pct']:+.4f}% | "
            f"{ret['cumulative_alpha_pct']:+.4f}% |"
        )
        lines.append(
            f"| Annualised | {ret['spa_annualized_pct']:.2f}% | "
            f"{ret['benchmark_apy_pct']:.2f}% | "
            f"{ret['alpha_annualized_pct']:+.2f}% |"
        )
        lines.append("")
        lines.append("## Risk")
        lines.append("")
        sharpe = (
            f"{risk['sharpe_annualized']:.2f}"
            if risk["sharpe_annualized"] is not None
            else "n/a (zero variance)"
        )
        lines.append(f"- **Sharpe (annualised):** {sharpe}")
        lines.append(f"- **Max daily drawdown:** {risk['max_daily_drawdown_pct']:.4f}%")
        lines.append(
            f"- **Days positive:** {risk['days_positive']}/{risk['days_total']}"
        )
        lines.append(f"- **Daily volatility:** {risk['daily_volatility_pct']:.4f}%")
        lines.append("")
        lines.append(f"## Allocation (latest, {alloc.get('num_positions', 0)} positions)")
        lines.append("")
        lines.append("| Protocol | USD | Weight |")
        lines.append("|---|--:|--:|")
        for p in alloc.get("positions", []):
            lines.append(f"| {p['protocol']} | ${p['usd']:,.2f} | {p['weight_pct']:.2f}% |")
        lines.append("")
        lines.append("## Daily returns vs benchmark")
        lines.append("")
        lines.append("| Date | SPA | Aave (3.1%/365) | Daily alpha |")
        lines.append("|---|--:|--:|--:|")
        for row in report["daily"]:
            lines.append(
                f"| {row['date']} | {row['spa_return_pct']:+.4f}% | "
                f"{row['benchmark_return_pct']:.4f}% | {row['daily_alpha_pct']:+.4f}% |"
            )
        lines.append("")
        lines.append(f"_{report['note']}_")
        lines.append("")
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save(self) -> Dict[str, str]:
        """Build + atomically write both JSON and Markdown. Returns paths."""
        report = self.build()
        out_dir = self.data_dir / _REPORTS_SUBDIR
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{self.month}.json"
        md_path = out_dir / f"{self.month}.md"
        atomic_save(report, str(json_path))
        # atomic_save serialises to JSON; write Markdown via tmp+replace too.
        self._atomic_write_text(md_path, self.render_markdown(report))
        return {"json": str(json_path), "md": str(md_path)}

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        import os
        import tempfile
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Monthly Performance Report (MP-1252) — SPA vs lazy Aave."
    )
    parser.add_argument("--check", action="store_true", default=True,
                        help="Compute and print without writing (default).")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically save JSON + Markdown.")
    parser.add_argument("--month", default="2026-06", help="Target month YYYY-MM.")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR),
                        help="Data directory path.")
    args = parser.parse_args(argv)

    rpt = MonthlyPerformanceReport(data_dir=args.data_dir, month=args.month)
    report = rpt.build()
    print(rpt.render_markdown(report))

    if args.run:
        paths = rpt.save()
        print(f"\nSaved → {paths['json']}")
        print(f"Saved → {paths['md']}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
