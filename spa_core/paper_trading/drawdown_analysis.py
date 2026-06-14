"""
Paper-trading drawdown-episode analysis (SPA-V382).

Read-only analytics layer that sits *alongside* ``risk_metrics.py`` (SPA-V380)
and ``rolling_performance.py`` (SPA-V381) and *on top of* the daily equity
curve from ``equity_curve.py`` (SPA-V379).

Where ``equity_curve`` reports a single all-time ``max_drawdown_pct`` and
``risk_metrics`` folds drawdown into one Calmar ratio, neither answers the
question an investor report / risk review actually asks about drawdowns:
**"how many distinct drawdown episodes were there, how deep and how long was
each peak→trough→recovery cycle, how long did we spend underwater, and are we
underwater *right now*?"**. This module enumerates those episodes explicitly.

A *drawdown episode* is a contiguous stretch of the daily close-equity path
that runs from a prior all-time peak, down through a trough, back up to the day
equity first recovers to (or above) that peak. The final episode may still be
*ongoing* (equity never reclaimed the peak before the history ended).

Design notes / safety:
  * Pure stdlib (json, statistics, datetime, pathlib, logging) — mirrors the
    no-external-dependency style of equity_curve.py / risk_metrics.py /
    rolling_performance.py. No web3, no numpy/pandas.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Defensive: degenerate inputs (empty / monotonically-rising curve, a single
    bar, non-numeric closes) never raise — they yield an empty-but-valid
    episode list and a zeroed-but-stable summary schema.

Drawdown definition:
  Episodes are measured from ``close_equity`` against the running all-time peak
  close. ``max_drawdown_pct`` of an episode is ``(trough / peak - 1) * 100``
  (<= 0). Durations are whole UTC calendar days between the relevant bar dates.

Per-episode dict (``find_drawdown_episodes``):
    peak_date / peak_equity         the high the episode fell from
    trough_date / trough_equity     the deepest point of the episode
    recovery_date                   first day equity reclaimed the peak (or
                                    None if the episode is still ongoing)
    max_drawdown_pct                (trough / peak - 1) * 100  (<= 0)
    drawdown_days                   calendar days peak_date -> trough_date
    recovery_days                   calendar days trough_date -> recovery_date
                                    (None if ongoing)
    total_days                      calendar days peak_date -> recovery_date
                                    (or last observed date if ongoing)
    recovered                       bool — did equity reclaim the peak?

Summary roll-up (``compute_drawdown_summary``):
    num_episodes, recovered_episodes, ongoing_episodes,
    max_drawdown_pct + max_drawdown_episode,
    avg_drawdown_pct, longest_drawdown_days, longest_recovery_days,
    currently_in_drawdown, current_drawdown_pct, current_drawdown_days,
    time_underwater_pct, total_days, first_date, last_date.

CLI::

    python -m spa_core.paper_trading.drawdown_analysis
    python -m spa_core.paper_trading.drawdown_analysis \\
        --history data/pnl_history.json \\
        --out data/drawdown_analysis.json --min-depth 0.5
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

log = logging.getLogger("spa.paper_trading.drawdown_analysis")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "drawdown_analysis.json"

# Episodes shallower than this absolute depth (in percent) are dropped from the
# reported set by default — 0.0 keeps every episode, including 1-cent dips.
DEFAULT_MIN_DEPTH_PCT = 0.0


def _day_diff(start_date: str, end_date: str) -> int | None:
    """Whole calendar days between two ``YYYY-MM-DD`` strings (>= 0).

    Returns None if either date is missing or unparseable, so a malformed bar
    never raises — duration fields simply degrade to None.
    """
    try:
        d0 = datetime.fromisoformat(start_date).date()
        d1 = datetime.fromisoformat(end_date).date()
    except (TypeError, ValueError):
        return None
    return (d1 - d0).days


def _valid_close(bar: dict) -> float | None:
    """Return a bar's numeric ``close_equity`` or None (bools rejected)."""
    close = bar.get("close_equity")
    if not isinstance(close, (int, float)) or isinstance(close, bool):
        return None
    return float(close)


def _finalize_episode(
    peak_date: str,
    peak_equity: float,
    trough_date: str,
    trough_equity: float,
    recovery_date: str | None,
    last_date: str,
) -> dict:
    """Assemble a single episode dict with depth + duration fields."""
    max_dd = (trough_equity / peak_equity - 1.0) * 100.0 if peak_equity else 0.0
    recovered = recovery_date is not None
    drawdown_days = _day_diff(peak_date, trough_date)
    recovery_days = _day_diff(trough_date, recovery_date) if recovered else None
    total_days = _day_diff(peak_date, recovery_date if recovered else last_date)
    return {
        "peak_date":        peak_date,
        "peak_equity":      round(peak_equity, 2),
        "trough_date":      trough_date,
        "trough_equity":    round(trough_equity, 2),
        "recovery_date":    recovery_date,
        "max_drawdown_pct": round(max_dd, 4),
        "drawdown_days":    drawdown_days,
        "recovery_days":    recovery_days,
        "total_days":       total_days,
        "recovered":        recovered,
    }


def find_drawdown_episodes(
    curve: list[dict],
    min_depth_pct: float = DEFAULT_MIN_DEPTH_PCT,
) -> list[dict]:
    """Enumerate peak→trough→recovery drawdown episodes from a daily curve.

    Args:
        curve: daily bars from ``equity_curve.build_daily_equity_curve``.
        min_depth_pct: drop episodes whose absolute depth is below this many
            percent (default 0.0 keeps all). A small positive value filters
            rounding-level dips.

    Returns:
        Episodes ordered ascending by ``peak_date``. Empty list when the curve
        is empty or never falls below its running peak.
    """
    episodes: list[dict] = []
    bars = [b for b in curve if _valid_close(b) is not None]
    if not bars:
        return episodes

    last_date = bars[-1]["date"]
    threshold = abs(float(min_depth_pct))

    peak_val = _valid_close(bars[0])
    peak_date = bars[0]["date"]
    in_dd = False
    trough_val = peak_val
    trough_date = peak_date

    def _emit(recovery_date: str | None) -> None:
        ep = _finalize_episode(
            peak_date, peak_val, trough_date, trough_val, recovery_date, last_date,
        )
        if abs(ep["max_drawdown_pct"]) >= threshold:
            episodes.append(ep)

    for bar in bars:
        close = _valid_close(bar)
        date = bar["date"]
        if close >= peak_val:
            # New all-time high → if we were underwater, this is the recovery.
            if in_dd:
                _emit(recovery_date=date)
                in_dd = False
            peak_val = close
            peak_date = date
        else:
            # Underwater relative to the running peak.
            if not in_dd:
                in_dd = True
                trough_val = close
                trough_date = date
            elif close < trough_val:
                trough_val = close
                trough_date = date

    # History ended while still underwater → ongoing (unrecovered) episode.
    if in_dd:
        _emit(recovery_date=None)

    return episodes


def compute_drawdown_summary(curve: list[dict], episodes: list[dict]) -> dict:
    """Roll a set of drawdown episodes up into headline drawdown statistics.

    Args:
        curve: the daily curve the episodes were derived from (used for the
            total-span and time-underwater calculations).
        episodes: output of ``find_drawdown_episodes``.

    Returns:
        A stable-schema dict (zeroed / None / False when there are no episodes).
    """
    bars = [b for b in curve if _valid_close(b) is not None]
    first_date = bars[0]["date"] if bars else None
    last_date = bars[-1]["date"] if bars else None
    total_days = _day_diff(first_date, last_date) if bars else None

    base = {
        "num_episodes":          len(episodes),
        "recovered_episodes":    0,
        "ongoing_episodes":      0,
        "max_drawdown_pct":      0.0,
        "max_drawdown_episode":  None,
        "avg_drawdown_pct":      0.0,
        "longest_drawdown_days": None,
        "longest_recovery_days": None,
        "currently_in_drawdown": False,
        "current_drawdown_pct":  0.0,
        "current_drawdown_days": None,
        "time_underwater_pct":   0.0,
        "total_days":            total_days,
        "first_date":            first_date,
        "last_date":             last_date,
    }
    if not episodes:
        return base

    recovered = [e for e in episodes if e["recovered"]]
    ongoing = [e for e in episodes if not e["recovered"]]
    worst = min(episodes, key=lambda e: e["max_drawdown_pct"])

    dd_days = [e["drawdown_days"] for e in episodes if e["drawdown_days"] is not None]
    rec_days = [e["recovery_days"] for e in recovered if e["recovery_days"] is not None]

    # Time spent underwater: sum of each episode's total_days (peak→recovery, or
    # peak→last for an ongoing one) as a fraction of the whole observed span.
    underwater_days = sum(e["total_days"] for e in episodes if e["total_days"] is not None)
    time_underwater = (
        (underwater_days / total_days) * 100.0
        if isinstance(total_days, int) and total_days > 0
        else 0.0
    )

    # "Current" drawdown = the trailing ongoing episode, if any.
    current = ongoing[-1] if ongoing else None

    base.update({
        "recovered_episodes":    len(recovered),
        "ongoing_episodes":      len(ongoing),
        "max_drawdown_pct":      worst["max_drawdown_pct"],
        "max_drawdown_episode":  worst,
        "avg_drawdown_pct":      round(
            statistics.fmean(e["max_drawdown_pct"] for e in episodes), 4),
        "longest_drawdown_days": max(dd_days) if dd_days else None,
        "longest_recovery_days": max(rec_days) if rec_days else None,
        "currently_in_drawdown": current is not None,
        "current_drawdown_pct":  current["max_drawdown_pct"] if current else 0.0,
        "current_drawdown_days": current["total_days"] if current else None,
        "time_underwater_pct":   round(min(time_underwater, 100.0), 4),
    })
    return base


def generate_drawdown_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    min_depth_pct: float = DEFAULT_MIN_DEPTH_PCT,
) -> dict:
    """Build the full drawdown-analysis report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        min_depth_pct: minimum absolute episode depth (percent) to include.

    Returns:
        ``{"generated_at", "source", "min_depth_pct", "summary", "episodes"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    episodes = find_drawdown_episodes(curve, min_depth_pct=min_depth_pct)
    report = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "source":        str(history_path),
        "min_depth_pct": abs(float(min_depth_pct)),
        "summary":       compute_drawdown_summary(curve, episodes),
        "episodes":      episodes,
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "drawdown analysis report written: %s (%d episodes)",
                out, len(episodes),
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write drawdown analysis report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyse drawdown episodes from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/drawdown_analysis.json)",
    )
    p.add_argument(
        "--min-depth", type=float, default=DEFAULT_MIN_DEPTH_PCT,
        help="minimum absolute episode depth in percent to include (default 0.0)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_drawdown_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        min_depth_pct=args.min_depth,
    )
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
