"""
Consolidated paper-trading performance tearsheet (SPA-V396).

Read-only *aggregation* layer that sits on top of every other paper-trading
analytics module. Where the individual modules each answer one question —

  * ``equity_curve.py``        (SPA-V379)  daily equity curve
  * ``risk_metrics.py``        (SPA-V380)  Sharpe / Sortino / Calmar / profit factor
  * ``rolling_performance.py`` (SPA-V381)  trailing 7d / 30d windows
  * ``drawdown_analysis.py``   (SPA-V382)  drawdown episodes + time underwater
  * ``return_distribution.py`` (SPA-V383)  daily-return shape + VaR / CVaR
  * ``calendar_returns.py``    (SPA-V384)  monthly / weekly / day-of-week + streaks
  * ``benchmark_comparison.py``(SPA-V394)  excess return / tracking error / IR
  * ``monte_carlo_projection.py`` (SPA-V395) forward equity projection

— this module stitches the *headline* figure(s) from each of those reports into
a single one-stop ``performance_tearsheet.json``. That single object is exactly
what an investor-report / dashboard / digest layer wants to render: it no longer
has to open eight files and know each one's schema.

Design notes / safety:
  * Pure stdlib (json, datetime, pathlib, logging, argparse) — mirrors the
    no-external-dependency style of the sibling modules. No web3 / numpy /
    pandas / scipy / network.
  * STRICTLY READ-ONLY. This module reads the *derived report JSONs* that the
    sibling modules already wrote (it does not even read pnl_history directly,
    let alone any trading state). It never touches the execution path, risk
    policy, wallets, or any money-moving code.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance presentation.
  * Defensive: a missing / empty / malformed source report degrades to
    ``{"available": false, ...}`` for that section. The aggregation never
    raises and the schema stays stable regardless of which inputs exist.

Freshness / coverage:
    The ``sources`` block records, per input report, whether it was found, its
    own ``generated_at`` timestamp, and an ``age_hours`` relative to tearsheet
    build time (None if the timestamp is missing/unparseable). ``coverage``
    summarises how many of the expected reports were available — a quick
    "is the analytics pipeline complete" signal for a dashboard.

CLI::

    python -m spa_core.paper_trading.performance_tearsheet
    python -m spa_core.paper_trading.performance_tearsheet --data-dir data \\
        --out data/performance_tearsheet.json --stale-hours 12
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# Default location of the data directory (repo-root/data) relative to this file.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _REPO_ROOT / "data"
DEFAULT_OUT = DEFAULT_DATA_DIR / "performance_tearsheet.json"

# A report is flagged "stale" if its generated_at is older than this many hours.
DEFAULT_STALE_HOURS = 24.0

# Maps the logical section name -> source report filename in the data dir.
SOURCE_FILES: dict[str, str] = {
    "equity_curve": "equity_curve_daily.json",
    "risk_metrics": "risk_metrics.json",
    "rolling_performance": "rolling_performance.json",
    "drawdown_analysis": "drawdown_analysis.json",
    "return_distribution": "return_distribution.json",
    "calendar_returns": "calendar_returns.json",
    "benchmark_comparison": "benchmark_comparison.json",
    "monte_carlo_projection": "monte_carlo_projection.json",
}


# ─── Helpers ────────────────────────────────────────────────────────────────


def _load_json(path: Path) -> Optional[dict]:
    """Load a JSON object from *path*; return None on any failure (read-only)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        logger.debug("Source %s is not a JSON object (got %s)", path, type(data).__name__)
        return None
    except FileNotFoundError:
        logger.debug("Source report not found: %s", path)
        return None
    except (OSError, ValueError) as exc:  # malformed / unreadable
        logger.debug("Could not read source report %s: %s", path, exc)
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return tz-aware datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    # Tolerate a trailing 'Z' (UTC) which fromisoformat historically rejects.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_hours(generated_at: Any, now: datetime) -> Optional[float]:
    """Hours between *generated_at* and *now*; None if unparseable."""
    dt = _parse_ts(generated_at)
    if dt is None:
        return None
    delta = now - dt
    return round(delta.total_seconds() / 3600.0, 4)


def _pick(d: Optional[dict], *keys: str) -> dict:
    """Return a sub-dict of *d* limited to *keys* (missing keys -> None).

    Defensive: a None / non-dict input yields all-None values, so callers get a
    stable schema regardless of whether the source report existed.
    """
    src = d if isinstance(d, dict) else {}
    return {k: src.get(k) for k in keys}


# ─── Section extractors ─────────────────────────────────────────────────────
#
# Each extractor takes the *loaded source report* (or None) and returns a flat,
# headline-only dict. They never raise.


def _overview(equity: Optional[dict], risk: Optional[dict]) -> dict:
    s = (equity or {}).get("summary") if isinstance(equity, dict) else None
    m = (risk or {}).get("metrics") if isinstance(risk, dict) else None
    s = s if isinstance(s, dict) else {}
    m = m if isinstance(m, dict) else {}
    return {
        "num_days": s.get("num_days"),
        "first_date": s.get("first_date"),
        "last_date": s.get("last_date"),
        "start_equity": s.get("start_equity"),
        "end_equity": s.get("end_equity"),
        "total_return_pct": s.get("total_return_pct"),
        "annualized_return_pct": m.get("annualized_return_pct"),
        "positive_days": s.get("positive_days"),
        "negative_days": s.get("negative_days"),
        "win_rate_pct": m.get("win_rate_pct"),
    }


def _risk_section(risk: Optional[dict]) -> dict:
    return _pick(
        (risk or {}).get("metrics") if isinstance(risk, dict) else None,
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "profit_factor",
        "win_loss_ratio",
        "daily_volatility_pct",
        "annualized_vol_pct",
        "downside_deviation_pct",
        "max_drawdown_pct",
        "best_day",
        "worst_day",
    )


def _rolling_section(rolling: Optional[dict]) -> dict:
    by_window = (rolling or {}).get("by_window") if isinstance(rolling, dict) else None
    out: dict[str, Any] = {"windows": (rolling or {}).get("windows") if isinstance(rolling, dict) else None}
    if isinstance(by_window, dict):
        # keep only the most useful headline figures per window
        out["by_window"] = {
            str(win): _pick(
                vals if isinstance(vals, dict) else None,
                "return_pct",
                "annualized_return_pct",
                "volatility_pct",
                "sharpe_ratio",
                "max_drawdown_pct",
                "win_rate_pct",
                "num_days",
            )
            for win, vals in by_window.items()
        }
    else:
        out["by_window"] = None
    return out


def _drawdown_section(dd: Optional[dict]) -> dict:
    return _pick(
        (dd or {}).get("summary") if isinstance(dd, dict) else None,
        "max_drawdown_pct",
        "avg_drawdown_pct",
        "num_episodes",
        "recovered_episodes",
        "ongoing_episodes",
        "longest_drawdown_days",
        "longest_recovery_days",
        "currently_in_drawdown",
        "current_drawdown_pct",
        "time_underwater_pct",
    )


def _distribution_section(dist: Optional[dict]) -> dict:
    d = (dist or {}).get("distribution") if isinstance(dist, dict) else None
    d = d if isinstance(d, dict) else {}
    out = {
        k: d.get(k)
        for k in (
            "count",
            "mean_pct",
            "median_pct",
            "stdev_pct",
            "skewness",
            "excess_kurtosis",
            "min_pct",
            "max_pct",
        )
    }
    # VaR / CVaR are dicts keyed by confidence level — surface them whole.
    out["var"] = d.get("var")
    out["cvar"] = d.get("cvar")
    out["percentiles"] = d.get("percentiles")
    return out


def _calendar_section(cal: Optional[dict]) -> dict:
    return _pick(
        (cal or {}).get("summary") if isinstance(cal, dict) else None,
        "num_realised_days",
        "num_months",
        "num_weeks",
        "best_month",
        "worst_month",
        "positive_months",
        "negative_months",
        "longest_win_streak",
        "longest_loss_streak",
        "current_streak_kind",
        "current_streak_len",
    )


def _benchmark_section(bench: Optional[dict]) -> dict:
    return _pick(
        (bench or {}).get("comparison") if isinstance(bench, dict) else None,
        "benchmark_kind",
        "benchmark_annual_pct",
        "portfolio_total_return_pct",
        "benchmark_total_return_pct",
        "excess_total_return_pct",
        "tracking_error_pct",
        "information_ratio",
        "information_ratio_annualized",
        "beta",
        "correlation",
        "up_capture",
        "down_capture",
        "days_outperformed",
        "days_underperformed",
    )


def _projection_section(mc: Optional[dict]) -> dict:
    p = (mc or {}).get("projection") if isinstance(mc, dict) else None
    p = p if isinstance(p, dict) else {}
    return {
        "inputs": p.get("inputs"),
        "terminal_equity": p.get("terminal_equity"),
        "terminal_return_pct": p.get("terminal_return_pct"),
        "probability_of_profit": p.get("probability_of_profit"),
        "probability_of_loss": p.get("probability_of_loss"),
        "expected_max_drawdown_pct": p.get("expected_max_drawdown_pct"),
    }


_EXTRACTORS = {
    "risk": _risk_section,
    "rolling_performance": _rolling_section,
    "drawdown_analysis": _drawdown_section,
    "return_distribution": _distribution_section,
    "calendar_returns": _calendar_section,
    "benchmark_comparison": _benchmark_section,
    "monte_carlo_projection": _projection_section,
}


# ─── Aggregation ────────────────────────────────────────────────────────────


def build_tearsheet(
    data_dir: os.PathLike | str = DEFAULT_DATA_DIR,
    *,
    stale_hours: float = DEFAULT_STALE_HOURS,
    now: Optional[datetime] = None,
) -> dict:
    """Aggregate every sibling analytics report into a single tearsheet dict.

    Pure read: opens each ``SOURCE_FILES`` entry under *data_dir*, extracts the
    headline figures and records freshness. Never raises; missing/malformed
    inputs degrade gracefully to ``available: false`` sections.
    """
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    loaded: dict[str, Optional[dict]] = {}
    sources: dict[str, Any] = {}
    available_count = 0
    stale_count = 0

    for name, fname in SOURCE_FILES.items():
        path = data_dir / fname
        report = _load_json(path)
        loaded[name] = report
        present = report is not None
        if present:
            available_count += 1
        generated_at = report.get("generated_at") if present else None
        age = _age_hours(generated_at, now)
        is_stale = bool(age is not None and age > stale_hours)
        if present and is_stale:
            stale_count += 1
        sources[name] = {
            "file": fname,
            "available": present,
            "generated_at": generated_at,
            "age_hours": age,
            "stale": is_stale if present else None,
        }

    # Sections — each carries an `available` flag mirroring its source report.
    sections: dict[str, Any] = {}
    sections["overview"] = {
        "available": loaded["equity_curve"] is not None or loaded["risk_metrics"] is not None,
        **_overview(loaded["equity_curve"], loaded["risk_metrics"]),
    }
    sections["risk"] = {"available": loaded["risk_metrics"] is not None, **_risk_section(loaded["risk_metrics"])}
    sections["rolling_performance"] = {
        "available": loaded["rolling_performance"] is not None,
        **_rolling_section(loaded["rolling_performance"]),
    }
    sections["drawdown_analysis"] = {
        "available": loaded["drawdown_analysis"] is not None,
        **_drawdown_section(loaded["drawdown_analysis"]),
    }
    sections["return_distribution"] = {
        "available": loaded["return_distribution"] is not None,
        **_distribution_section(loaded["return_distribution"]),
    }
    sections["calendar_returns"] = {
        "available": loaded["calendar_returns"] is not None,
        **_calendar_section(loaded["calendar_returns"]),
    }
    sections["benchmark_comparison"] = {
        "available": loaded["benchmark_comparison"] is not None,
        **_benchmark_section(loaded["benchmark_comparison"]),
    }
    sections["monte_carlo_projection"] = {
        "available": loaded["monte_carlo_projection"] is not None,
        **_projection_section(loaded["monte_carlo_projection"]),
    }

    expected = len(SOURCE_FILES)
    coverage = {
        "expected": expected,
        "available": available_count,
        "missing": expected - available_count,
        "stale": stale_count,
        "coverage_pct": round(100.0 * available_count / expected, 4) if expected else 0.0,
        "complete": available_count == expected,
    }

    return {
        "generated_at": now.isoformat(),
        "data_dir": str(data_dir),
        "stale_hours": stale_hours,
        "coverage": coverage,
        "sources": sources,
        "tearsheet": sections,
    }


def _atomic_write_json(obj: dict, out_path: Path) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(out_path))
def generate_tearsheet_report(
    data_dir: os.PathLike | str = DEFAULT_DATA_DIR,
    out_path: os.PathLike | str = DEFAULT_OUT,
    *,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> dict:
    """Build the tearsheet and atomically write it to *out_path*; return it."""
    report = build_tearsheet(data_dir, stale_hours=stale_hours)
    _atomic_write_json(report, Path(out_path))
    return report


# ─── CLI ────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Consolidated paper-trading performance tearsheet (SPA-V396).")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory holding the source analytics JSONs.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output tearsheet JSON path.")
    p.add_argument("--stale-hours", type=float, default=DEFAULT_STALE_HOURS, help="Flag a source report stale beyond this age (hours).")
    p.add_argument("--quiet", action="store_true", help="Suppress the one-line summary.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = generate_tearsheet_report(args.data_dir, args.out, stale_hours=args.stale_hours)
    if not args.quiet:
        cov = report["coverage"]
        ov = report["tearsheet"]["overview"]
        print(
            f"TEARSHEET coverage {cov['available']}/{cov['expected']} "
            f"({cov['coverage_pct']}%) | stale {cov['stale']} | "
            f"total_return {ov.get('total_return_pct')}% over {ov.get('num_days')}d "
            f"-> {args.out}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
