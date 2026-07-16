"""
Paper-trading rolling-window performance metrics (SPA-V381).

Read-only analytics layer that sits *alongside* ``risk_metrics.py`` (SPA-V380)
and *on top of* the daily equity curve from ``equity_curve.py`` (SPA-V379).

Where ``equity_curve`` answers "what did equity do each day" and
``risk_metrics`` answers "how good was the *whole* path on a risk-adjusted
basis", this module answers the **time-localized** question a reporting layer /
investor digest wants next: "how do the last 7 / 30 days look *right now*, and
how has the trailing-window return drifted over time?". That recency view is
what surfaces a regime change (a recently deteriorating book) that an all-time
average quietly washes out.

Design notes / safety:
  * Pure stdlib (json, statistics, datetime, pathlib, logging) — mirrors the
    no-external-dependency style of equity_curve.py / risk_metrics.py. No web3,
    no numpy/pandas.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0 / 1 day, a window longer than the history,
    zero volatility) never raise — undefined quantities return ``None`` / 0 and
    the schema stays stable.

Window semantics:
  A "window of W days" is the last ``W`` *realised* return days. Day 1 of the
  whole history carries a 0.0 seed return (no prior close), so — exactly like
  risk_metrics — it is excluded from the realised-return series before windows
  are sliced. A window therefore never counts the seed as a flat day.

Per-window summary (``compute_window_metrics``):
    window                  the requested W
    days_in_window          realised return days actually used (<= W)
    window_return_pct       compounded return over the window
    mean_daily_return_pct   arithmetic mean of the window's daily returns
    window_volatility_pct   population stdev of the window's daily returns
    window_max_drawdown_pct worst close-to-peak drawdown *within* the window
    positive_days / negative_days
    best_day / worst_day    {date, daily_return_pct}
    first_date / last_date

Rolling series (``compute_rolling_series``):
    one point per realised day — the trailing-W return & volatility ending that
    day — so a dashboard can sparkline "rolling 7d return" over time.

CLI::

    python -m spa_core.analytics_lab.rolling_performance
    python -m spa_core.analytics_lab.rolling_performance \\
        --history data/pnl_history.json \\
        --out data/rolling_performance.json --windows 7 30 90
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)

log = logging.getLogger("spa.analytics_lab.rolling_performance")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "rolling_performance.json"

# Trailing windows (in realised-return days) reported by default.
DEFAULT_WINDOWS = (7, 30)


def _realised_bars(curve: list[dict]) -> list[dict]:
    """Daily bars carrying a *realised* return — every bar after the seed day.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close); excluding it
    keeps a flat seed day from being mistaken for a real flat trading day.
    """
    return curve[1:]


def _compound_return_pct(returns: list[float]) -> float:
    """Compound a list of daily returns (percent) into a window return (percent)."""
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    return (growth - 1.0) * 100.0


def _window_max_drawdown_pct(bars: list[dict]) -> float:
    """Worst close-to-peak drawdown *within* a window of bars (<= 0).

    Computed from the window's own ``close_equity`` path with the running peak
    seeded at the first close in the window — i.e. drawdown is measured
    relative to the window, not the all-time peak.
    """
    peak = None
    worst = 0.0
    for bar in bars:
        close = bar.get("close_equity")
        if not isinstance(close, (int, float)) or isinstance(close, bool):
            continue
        if peak is None or close > peak:
            peak = close
        if peak:
            dd = (close / peak - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return worst


def compute_window_metrics(curve: list[dict], window: int) -> dict:
    """Summarise the latest trailing ``window`` of realised return days.

    Args:
        curve: daily bars from ``equity_curve.build_daily_equity_curve``.
        window: number of trailing realised-return days to summarise.

    Returns:
        A stable-schema dict (zeroed / None when there is no usable history).
    """
    base = {
        "window":                  int(window),
        "days_in_window":          0,
        "window_return_pct":       0.0,
        "mean_daily_return_pct":   0.0,
        "window_volatility_pct":   0.0,
        "window_max_drawdown_pct": 0.0,
        "positive_days":           0,
        "negative_days":           0,
        "best_day":                None,
        "worst_day":               None,
        "first_date":              None,
        "last_date":               None,
    }
    if window <= 0:
        return base

    realised = _realised_bars(curve)
    if not realised:
        return base

    win_bars = realised[-window:]
    returns = [b["daily_return_pct"] for b in win_bars]
    n = len(win_bars)

    best = max(win_bars, key=lambda b: b["daily_return_pct"])
    worst = min(win_bars, key=lambda b: b["daily_return_pct"])

    return {
        "window":                  int(window),
        "days_in_window":          n,
        "window_return_pct":       round(_compound_return_pct(returns), 4),
        "mean_daily_return_pct":   round(statistics.fmean(returns), 4),
        "window_volatility_pct":   round(statistics.pstdev(returns), 4) if n >= 1 else 0.0,
        "window_max_drawdown_pct": round(_window_max_drawdown_pct(win_bars), 4),
        "positive_days":           sum(1 for r in returns if r > 0),
        "negative_days":           sum(1 for r in returns if r < 0),
        "best_day":                {"date": best["date"],
                                    "daily_return_pct": best["daily_return_pct"]},
        "worst_day":               {"date": worst["date"],
                                    "daily_return_pct": worst["daily_return_pct"]},
        "first_date":              win_bars[0]["date"],
        "last_date":               win_bars[-1]["date"],
    }


def compute_rolling_series(curve: list[dict], window: int) -> list[dict]:
    """Per-day trailing-``window`` return & volatility ending on each day.

    One point per realised return day, so a consumer can sparkline how the
    trailing-window return drifted over time. Empty list when there is no
    realised history or ``window`` is non-positive.
    """
    if window <= 0:
        return []
    realised = _realised_bars(curve)
    series: list[dict] = []
    for i in range(len(realised)):
        win_bars = realised[max(0, i - window + 1): i + 1]
        returns = [b["daily_return_pct"] for b in win_bars]
        series.append({
            "date":                realised[i]["date"],
            "days_in_window":      len(win_bars),
            "window_return_pct":   round(_compound_return_pct(returns), 4),
            "window_volatility_pct": (
                round(statistics.pstdev(returns), 4) if len(returns) >= 1 else 0.0
            ),
        })
    return series


def compute_rolling_performance(
    curve: list[dict],
    windows: tuple[int, ...] | list[int] = DEFAULT_WINDOWS,
) -> dict:
    """Compute per-window summaries + rolling series for each requested window.

    Returns:
        ``{"windows": [W, ...], "by_window": {str(W): {"summary", "series"}}}``.
        Windows are de-duplicated and sorted ascending; non-positive windows
        are dropped.
    """
    clean_windows = sorted({int(w) for w in windows if int(w) > 0})
    by_window = {
        str(w): {
            "summary": compute_window_metrics(curve, w),
            "series":  compute_rolling_series(curve, w),
        }
        for w in clean_windows
    }
    return {"windows": clean_windows, "by_window": by_window}


def generate_rolling_performance_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    windows: tuple[int, ...] | list[int] = DEFAULT_WINDOWS,
) -> dict:
    """Build the full rolling-performance report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        windows: trailing windows (in realised-return days) to report.

    Returns:
        ``{"generated_at", "source", "windows", "by_window"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    rolling = compute_rolling_performance(curve, windows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "windows":      rolling["windows"],
        "by_window":    rolling["by_window"],
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "rolling performance report written: %s (windows=%s)",
                out, rolling["windows"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write rolling performance report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute rolling-window performance metrics from P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/rolling_performance.json)",
    )
    p.add_argument(
        "--windows", type=int, nargs="+", default=list(DEFAULT_WINDOWS),
        help="trailing windows in days (default: 7 30)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_rolling_performance_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        windows=args.windows,
    )
    summaries = {w: report["by_window"][w]["summary"] for w in report["by_window"]}
    print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
