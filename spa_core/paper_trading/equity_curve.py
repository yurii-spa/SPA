"""
Paper-trading daily equity-curve tracker (SPA-V379).

Read-only analytics layer over ``data/pnl_history.json``. The paper-trading
engine appends intraday P&L snapshots to that file (every ~4h); this module
resamples those snapshots into a **daily equity curve** and a roll-up summary
so the Go-Live dashboard / reporting layer can render an equity sparkline and
headline performance figures without re-scanning the raw intraday history.

Design notes / safety:
  * Pure stdlib (json, statistics, datetime, pathlib, logging) — mirrors the
    no-external-dependency style of the execution adapters. No web3, no pandas.
  * STRICTLY READ-ONLY w.r.t. trading state. This module never touches the
    execution path, the risk policy, wallets, or any money-moving code. It
    only reads pnl_history.json and writes a derived report JSON.
  * Defensive parsing: malformed / partial snapshots are skipped (logged at
    DEBUG), a missing or empty source file yields an empty-but-valid report.
    The function never raises on bad data — callers always get a dict.

Equity definition:
  Each snapshot's "equity" is its ``total_capital_usd`` (deployed + cash,
  net of P&L). This matches how pnl_history.json already reports the mark.

Daily bar (one per UTC calendar day with >=1 snapshot):
    date                ISO date (YYYY-MM-DD, UTC)
    open_equity         first snapshot equity of the day
    close_equity        last snapshot equity of the day
    high_equity         max equity across the day's snapshots
    low_equity          min equity across the day's snapshots
    snapshots           number of snapshots that fell on the day
    daily_return_pct    (close / prev_day_close - 1) * 100  (0.0 on day 1)
    cumulative_return_pct  (close / first_day_open - 1) * 100
    drawdown_pct        (close / running_peak_close - 1) * 100  (<= 0)

Summary roll-up:
    start_equity, end_equity, total_return_pct, num_days, num_snapshots,
    best_day / worst_day (date + daily_return_pct), max_drawdown_pct,
    positive_days, negative_days, daily_volatility_pct (stdev of daily
    returns), first_date, last_date.

CLI::

    python -m spa_core.paper_trading.equity_curve
    python -m spa_core.paper_trading.equity_curve --history data/pnl_history.json \\
        --out data/equity_curve_daily.json
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.paper_trading.equity_curve")

# Default I/O locations relative to the project root (two levels up from this
# file: spa_core/paper_trading/equity_curve.py -> project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_PATH = _PROJECT_ROOT / "data" / "pnl_history.json"
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "equity_curve_daily.json"

# The snapshot field we treat as the portfolio mark.
EQUITY_FIELD = "total_capital_usd"


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp (``...Z`` or ``+00:00``) to aware UTC.

    Returns None if the value is missing or unparseable (caller skips the
    record). Naive timestamps are assumed to be UTC.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    # datetime.fromisoformat (3.10) doesn't accept a trailing 'Z'.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_pnl_history(history_path: str | Path = DEFAULT_HISTORY_PATH) -> list[dict]:
    """Load the raw P&L snapshot list from ``history_path``.

    Returns an empty list (never raises) if the file is missing, empty, or
    not a JSON array — so the rest of the pipeline degrades gracefully.
    """
    path = Path(history_path)
    if not path.exists():
        log.warning("pnl_history not found at %s — empty curve", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (ValueError, OSError) as exc:
        log.warning("pnl_history unreadable (%s) — empty curve", exc)
        return []
    if not isinstance(raw, list):
        log.warning("pnl_history is not a JSON array (%s) — empty curve", type(raw))
        return []
    return raw


def _clean_snapshots(records: list[dict]) -> list[tuple[datetime, float, dict]]:
    """Filter to (timestamp, equity, record) tuples sorted ascending by time.

    Drops records lacking a parseable timestamp or a numeric equity field.
    """
    cleaned: list[tuple[datetime, float, dict]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        ts = _parse_timestamp(rec.get("timestamp"))
        if ts is None:
            log.debug("skip snapshot with bad timestamp: %r", rec.get("timestamp"))
            continue
        equity = rec.get(EQUITY_FIELD)
        if not isinstance(equity, (int, float)) or isinstance(equity, bool):
            log.debug("skip snapshot with bad %s: %r", EQUITY_FIELD, equity)
            continue
        cleaned.append((ts, float(equity), rec))
    cleaned.sort(key=lambda t: t[0])
    return cleaned


def build_daily_equity_curve(records: list[dict]) -> list[dict]:
    """Resample intraday P&L snapshots into one bar per UTC calendar day.

    Args:
        records: raw snapshot dicts (as stored in pnl_history.json).

    Returns:
        List of daily-bar dicts ordered ascending by date. Empty list if no
        usable snapshots.
    """
    cleaned = _clean_snapshots(records)
    if not cleaned:
        return []

    # Group snapshots by UTC date, preserving intra-day order.
    by_day: dict[str, list[tuple[datetime, float]]] = {}
    for ts, equity, _rec in cleaned:
        day = ts.date().isoformat()
        by_day.setdefault(day, []).append((ts, equity))

    curve: list[dict] = []
    first_open: float | None = None
    prev_close: float | None = None
    running_peak: float | None = None

    for day in sorted(by_day):
        snaps = by_day[day]  # already in ascending ts order (cleaned was sorted)
        equities = [e for _ts, e in snaps]
        open_equity = equities[0]
        close_equity = equities[-1]
        high_equity = max(equities)
        low_equity = min(equities)

        if first_open is None:
            first_open = open_equity
        if running_peak is None or close_equity > running_peak:
            running_peak = close_equity

        daily_return_pct = (
            0.0 if prev_close in (None, 0)
            else (close_equity / prev_close - 1.0) * 100.0
        )
        cumulative_return_pct = (
            0.0 if first_open in (None, 0)
            else (close_equity / first_open - 1.0) * 100.0
        )
        drawdown_pct = (
            0.0 if running_peak in (None, 0)
            else (close_equity / running_peak - 1.0) * 100.0
        )

        curve.append({
            "date":                  day,
            "open_equity":           round(open_equity, 2),
            "close_equity":          round(close_equity, 2),
            "high_equity":           round(high_equity, 2),
            "low_equity":            round(low_equity, 2),
            "snapshots":             len(snaps),
            "daily_return_pct":      round(daily_return_pct, 4),
            "cumulative_return_pct": round(cumulative_return_pct, 4),
            "drawdown_pct":          round(drawdown_pct, 4),
        })
        prev_close = close_equity

    return curve


def compute_summary(curve: list[dict]) -> dict:
    """Roll a daily curve up into headline performance metrics.

    Returns a dict with zeroed/None fields when ``curve`` is empty so the
    schema is stable for downstream consumers.
    """
    if not curve:
        return {
            "num_days":             0,
            "num_snapshots":        0,
            "start_equity":         None,
            "end_equity":           None,
            "total_return_pct":     0.0,
            "best_day":             None,
            "worst_day":            None,
            "max_drawdown_pct":     0.0,
            "positive_days":        0,
            "negative_days":        0,
            "daily_volatility_pct": 0.0,
            "first_date":           None,
            "last_date":            None,
        }

    start_equity = curve[0]["open_equity"]
    end_equity = curve[-1]["close_equity"]
    total_return_pct = (
        0.0 if start_equity in (None, 0)
        else (end_equity / start_equity - 1.0) * 100.0
    )

    # Daily returns: skip day 1 (its 0.0 is a seed, not a realised return).
    daily_returns = [bar["daily_return_pct"] for bar in curve[1:]]
    best = max(curve, key=lambda b: b["daily_return_pct"])
    worst = min(curve, key=lambda b: b["daily_return_pct"])
    max_dd = min(bar["drawdown_pct"] for bar in curve)
    positive_days = sum(1 for r in daily_returns if r > 0)
    negative_days = sum(1 for r in daily_returns if r < 0)
    volatility = (
        round(statistics.pstdev(daily_returns), 4) if len(daily_returns) >= 1 else 0.0
    )

    return {
        "num_days":             len(curve),
        "num_snapshots":        sum(bar["snapshots"] for bar in curve),
        "start_equity":         start_equity,
        "end_equity":           end_equity,
        "total_return_pct":     round(total_return_pct, 4),
        "best_day":             {"date": best["date"],
                                 "daily_return_pct": best["daily_return_pct"]},
        "worst_day":            {"date": worst["date"],
                                 "daily_return_pct": worst["daily_return_pct"]},
        "max_drawdown_pct":     round(max_dd, 4),
        "positive_days":        positive_days,
        "negative_days":        negative_days,
        "daily_volatility_pct": volatility,
        "first_date":           curve[0]["date"],
        "last_date":            curve[-1]["date"],
    }


def generate_equity_curve_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Build the full daily-equity-curve report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).

    Returns:
        ``{"generated_at", "source", "summary", "daily"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "summary":      compute_summary(curve),
        "daily":        curve,
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "equity curve report written: %s (%d days)",
                out, report["summary"]["num_days"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write equity curve report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build a daily equity curve from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/equity_curve_daily.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_equity_curve_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
    )
    s = report["summary"]
    print(json.dumps(s, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
