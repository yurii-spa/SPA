"""
Paper-trading calendar / periodic returns & streak analysis (SPA-V384).

Read-only analytics layer that sits on top of the daily equity curve produced
by :mod:`spa_core.paper_trading.equity_curve` (SPA-V379). Where the existing
modules give all-time risk ratios (V380), trailing windows (V381), drawdown
episodes (V382) and the return *distribution* (V383), this module answers a
different question: **how did the strategy do period-by-period on the
calendar, and how do wins/losses cluster into streaks?**

It produces:
  * Monthly returns   — daily returns compounded within each calendar month
    (YYYY-MM), plus per-month positive/negative day counts and best/worst day.
  * Weekly returns    — daily returns compounded within each ISO week
    (ISO year-week, e.g. ``2026-W21``).
  * Day-of-week seasonality — mean / total compounded return and win-rate for
    each weekday (Mon..Sun), to expose any day-of-week bias.
  * Streak analysis   — current and longest winning / losing streaks (runs of
    consecutive positive / negative daily returns), with start/end dates.

Design notes / safety:
  * Pure stdlib (json, statistics, datetime, pathlib, logging) — mirrors the
    no-external-dependency style of the sibling analytics modules. No web3, no
    pandas/numpy.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    the risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via the equity-curve builder) and writes a derived
    report JSON. NOT feed-health (SPA-BL-011 freeze respected).
  * Defensive: a missing / empty / malformed history yields an empty-but-valid
    report (stable schema). Functions never raise on bad data.

Return convention:
  All returns are percentages. Day-1 of the equity curve carries a seed
  ``daily_return_pct`` of 0.0 (not a realised return); it is excluded from
  streaks, seasonality and positive/negative counts, but its date still
  anchors the month/week it belongs to.

CLI::

    python -m spa_core.analytics_lab.calendar_returns
    python -m spa_core.analytics_lab.calendar_returns --history data/pnl_history.json \\
        --out data/calendar_returns.json
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)

log = logging.getLogger("spa.analytics_lab.calendar_returns")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "calendar_returns.json"

# Weekday index (date.weekday(): Mon=0 .. Sun=6) -> label.
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _compound_pct(returns_pct: list[float]) -> float:
    """Geometrically compound a list of percentage daily returns.

    ``[1.0, -2.0]`` -> (1.01 * 0.98 - 1) * 100. Empty list -> 0.0.
    """
    factor = 1.0
    for r in returns_pct:
        factor *= 1.0 + r / 100.0
    return (factor - 1.0) * 100.0


def _parse_iso_date(value: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` curve date string to a ``date`` (None on error)."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _realised_bars(curve: list[dict]) -> list[dict]:
    """Return curve bars excluding the seed day-1 (whose return is a 0.0 seed).

    The first bar's ``daily_return_pct`` is always a seed 0.0, so it is dropped
    for return-based aggregation. All later bars are kept as-is.
    """
    return curve[1:] if len(curve) > 1 else []


def compute_monthly_returns(curve: list[dict]) -> list[dict]:
    """Compound daily returns within each calendar month (YYYY-MM).

    Returns a list ordered ascending by month. Each entry::

        {month, return_pct, num_days, positive_days, negative_days,
         best_day, worst_day, first_date, last_date}
    """
    bars = _realised_bars(curve)
    by_month: dict[str, list[dict]] = {}
    for bar in bars:
        d = _parse_iso_date(bar.get("date", ""))
        if d is None:
            continue
        by_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(bar)

    out: list[dict] = []
    for month in sorted(by_month):
        group = by_month[month]
        rets = [b["daily_return_pct"] for b in group]
        best = max(group, key=lambda b: b["daily_return_pct"])
        worst = min(group, key=lambda b: b["daily_return_pct"])
        out.append({
            "month":         month,
            "return_pct":    round(_compound_pct(rets), 4),
            "num_days":      len(group),
            "positive_days": sum(1 for r in rets if r > 0),
            "negative_days": sum(1 for r in rets if r < 0),
            "best_day":      {"date": best["date"],
                              "daily_return_pct": best["daily_return_pct"]},
            "worst_day":     {"date": worst["date"],
                              "daily_return_pct": worst["daily_return_pct"]},
            "first_date":    group[0]["date"],
            "last_date":     group[-1]["date"],
        })
    return out


def compute_weekly_returns(curve: list[dict]) -> list[dict]:
    """Compound daily returns within each ISO week (``ISOyear-Www``).

    Returns a list ordered ascending by ISO week. Each entry::

        {week, return_pct, num_days, positive_days, negative_days,
         first_date, last_date}
    """
    bars = _realised_bars(curve)
    by_week: dict[str, list[dict]] = {}
    for bar in bars:
        d = _parse_iso_date(bar.get("date", ""))
        if d is None:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        by_week.setdefault(f"{iso_year:04d}-W{iso_week:02d}", []).append(bar)

    out: list[dict] = []
    for week in sorted(by_week):
        group = by_week[week]
        rets = [b["daily_return_pct"] for b in group]
        out.append({
            "week":          week,
            "return_pct":    round(_compound_pct(rets), 4),
            "num_days":      len(group),
            "positive_days": sum(1 for r in rets if r > 0),
            "negative_days": sum(1 for r in rets if r < 0),
            "first_date":    group[0]["date"],
            "last_date":     group[-1]["date"],
        })
    return out


def compute_day_of_week(curve: list[dict]) -> list[dict]:
    """Day-of-week seasonality over realised daily returns.

    Returns a 7-entry list (Mon..Sun, always present even if 0 samples)::

        {weekday, num_days, mean_return_pct, total_return_pct, win_rate_pct}
    """
    bars = _realised_bars(curve)
    buckets: dict[int, list[float]] = {i: [] for i in range(7)}
    for bar in bars:
        d = _parse_iso_date(bar.get("date", ""))
        if d is None:
            continue
        buckets[d.weekday()].append(bar["daily_return_pct"])

    out: list[dict] = []
    for idx in range(7):
        rets = buckets[idx]
        n = len(rets)
        mean_ret = round(statistics.fmean(rets), 4) if n else None
        wins = sum(1 for r in rets if r > 0)
        win_rate = round(wins / n * 100.0, 2) if n else None
        out.append({
            "weekday":          _WEEKDAY_LABELS[idx],
            "num_days":         n,
            "mean_return_pct":  mean_ret,
            "total_return_pct": round(_compound_pct(rets), 4) if n else 0.0,
            "win_rate_pct":     win_rate,
        })
    return out


def _scan_streaks(bars: list[dict]) -> list[dict]:
    """Collapse a sequence of realised bars into win/loss/flat runs.

    Each run::  {kind: 'win'|'loss'|'flat', length, start_date, end_date,
                 return_pct}  where return_pct is the compounded run return.
    Adjacent days are in the same run iff they share the same sign of
    daily_return_pct (>0 win, <0 loss, ==0 flat).
    """
    runs: list[dict] = []
    cur_kind: str | None = None
    cur: list[dict] = []

    def _kind(r: float) -> str:
        return "win" if r > 0 else "loss" if r < 0 else "flat"

    def _flush() -> None:
        if not cur:
            return
        rets = [b["daily_return_pct"] for b in cur]
        runs.append({
            "kind":       cur_kind,
            "length":     len(cur),
            "start_date": cur[0]["date"],
            "end_date":   cur[-1]["date"],
            "return_pct": round(_compound_pct(rets), 4),
        })

    for bar in bars:
        k = _kind(bar["daily_return_pct"])
        if k != cur_kind:
            _flush()
            cur_kind = k
            cur = [bar]
        else:
            cur.append(bar)
    _flush()
    return runs


def compute_streaks(curve: list[dict]) -> dict:
    """Winning / losing streak analysis over realised daily returns.

    Returns::

        {runs: [...], current_streak: {...}|None,
         longest_win_streak: {...}|None, longest_loss_streak: {...}|None}

    A streak is a maximal run of consecutive same-sign daily returns. Flat
    (==0) days break both win and loss streaks. ``current_streak`` is the last
    run in the series (may be flat); the longest-win / longest-loss summaries
    consider only win / loss runs respectively.
    """
    bars = _realised_bars(curve)
    runs = _scan_streaks(bars)
    if not runs:
        return {
            "runs":                [],
            "current_streak":      None,
            "longest_win_streak":  None,
            "longest_loss_streak": None,
        }

    win_runs = [r for r in runs if r["kind"] == "win"]
    loss_runs = [r for r in runs if r["kind"] == "loss"]
    longest_win = max(win_runs, key=lambda r: r["length"]) if win_runs else None
    longest_loss = max(loss_runs, key=lambda r: r["length"]) if loss_runs else None
    return {
        "runs":                runs,
        "current_streak":      runs[-1],
        "longest_win_streak":  longest_win,
        "longest_loss_streak": longest_loss,
    }


def compute_summary(curve: list[dict], monthly: list[dict], streaks: dict) -> dict:
    """Headline roll-up across the calendar aggregations.

    Stable schema with None/0 fields when there is no realised data.
    """
    bars = _realised_bars(curve)
    if not bars:
        return {
            "num_realised_days":   0,
            "num_months":          0,
            "num_weeks":           0,
            "best_month":          None,
            "worst_month":         None,
            "positive_months":     0,
            "negative_months":     0,
            "longest_win_streak":  0,
            "longest_loss_streak": 0,
            "current_streak_kind": None,
            "current_streak_len":  0,
            "first_date":          None,
            "last_date":           None,
        }

    best_month = max(monthly, key=lambda m: m["return_pct"]) if monthly else None
    worst_month = min(monthly, key=lambda m: m["return_pct"]) if monthly else None
    lws = streaks.get("longest_win_streak")
    lls = streaks.get("longest_loss_streak")
    cur = streaks.get("current_streak")
    return {
        "num_realised_days":   len(bars),
        "num_months":          len(monthly),
        "num_weeks":           len({tuple(_parse_iso_date(b["date"]).isocalendar()[:2])
                                    for b in bars if _parse_iso_date(b["date"])}),
        "best_month":          ({"month": best_month["month"],
                                 "return_pct": best_month["return_pct"]}
                                if best_month else None),
        "worst_month":         ({"month": worst_month["month"],
                                 "return_pct": worst_month["return_pct"]}
                                if worst_month else None),
        "positive_months":     sum(1 for m in monthly if m["return_pct"] > 0),
        "negative_months":     sum(1 for m in monthly if m["return_pct"] < 0),
        "longest_win_streak":  lws["length"] if lws else 0,
        "longest_loss_streak": lls["length"] if lls else 0,
        "current_streak_kind": cur["kind"] if cur else None,
        "current_streak_len":  cur["length"] if cur else 0,
        "first_date":          bars[0]["date"],
        "last_date":           bars[-1]["date"],
    }


def generate_calendar_returns_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Build the full calendar-returns report and (optionally) persist it.

    Returns ``{"generated_at", "source", "summary", "monthly", "weekly",
    "day_of_week", "streaks"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)

    monthly = compute_monthly_returns(curve)
    weekly = compute_weekly_returns(curve)
    day_of_week = compute_day_of_week(curve)
    streaks = compute_streaks(curve)
    summary = compute_summary(curve, monthly, streaks)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "summary":      summary,
        "monthly":      monthly,
        "weekly":       weekly,
        "day_of_week":  day_of_week,
        "streaks":      streaks,
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "calendar returns report written: %s (%d months, %d weeks)",
                out, summary["num_months"], summary["num_weeks"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write calendar returns report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Calendar/periodic returns & streak analysis from P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/calendar_returns.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_calendar_returns_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
    )
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
