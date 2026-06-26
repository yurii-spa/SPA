"""
Paper-trading return-regime / trend-phase segmentation (SPA-V400).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). Every other paper_trading analytic in the
V380–V399 suite treats the realised return series either as an *unordered bag*
of numbers — ``risk_metrics`` (V380) reduces it to Sharpe/Sortino/Calmar,
``return_distribution`` (V383) describes its *shape* and tails, ``advanced_ratios``
(V397) adds Omega/Ulcer, concentration analytics reduce it to HHI — or it *tests
statistical memory* of the ordering (``serial_dependence`` V399: ACF / Ljung-Box
/ runs / variance-ratio / Hurst).

This module fills a different gap: it provides the first **structural
segmentation of the realised equity path into directional phases (regimes)**.
Where serial_dependence asks "is the *ordering* random?", this module asks the
purely descriptive question "*when* was the portfolio trending up, trending
down, or going sideways, and *for how long*?". It is a decomposition of the
PATH, not a randomness test.

Method — zig-zag / swing segmentation:
    A classic charting "zig-zag" walks the close-equity series, tracking the
    running local extreme in the current direction. A *pivot* (reversal) is
    confirmed when the retracement away from the last extreme exceeds
    ``threshold_pct`` (default 1.0%). Each confirmed leg becomes a segment with:

        direction     "advance" (up leg) / "decline" (down leg) / "flat"
        start_date    date of the leg's starting pivot
        end_date      date of the leg's ending pivot
        start_equity  close equity at the start pivot
        end_equity    close equity at the end pivot
        return_pct    (end_equity / start_equity - 1) * 100
        length_days   number of daily steps spanned (>= 1)
        magnitude_pct abs(return_pct)

Flat-phase convention:
    The threshold filter means no *confirmed* swing can have a magnitude below
    ``threshold_pct`` — sub-threshold wiggles are absorbed into the in-progress
    leg rather than spawning segments. A "flat" label is therefore only assigned
    to the *final, still-open* leg if, at the end of the series, its accumulated
    magnitude is still below ``threshold_pct`` (i.e. the path drifted sideways
    without ever confirming a direction). This keeps the segmentation honest:
    flat means "never moved enough to call a trend", not "small confirmed move".
    Confirmed legs are always advance/decline. ``flat`` aggregates are reported
    for schema stability and will usually be the single trailing chop leg, if any.

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors serial_dependence.py / advanced_ratios.py. No web3, no
    numpy/pandas/scipy, no network.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, monitoring, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0/1 day, flat/zero-variance series, a series
    that only ever moves one way) never raise. Statistics that are undefined
    return ``None`` and the schema stays stable. The compute function NEVER
    raises on bad data — callers always get a dict.

CLI::

    python -m spa_core.paper_trading.regime_segmentation
    python -m spa_core.paper_trading.regime_segmentation --history data/pnl_history.json \\
        --out data/regime_segmentation.json --threshold 1.0
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.regime_segmentation")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "regime_segmentation.json"

# Default reversal threshold (in %) for confirming a zig-zag pivot.
DEFAULT_THRESHOLD_PCT = 1.0

# Coarse-trend-label thresholds (fractions of total advance/decline magnitude).
_TREND_DOMINANCE = 0.60


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded. Kept for parity with the sibling modules; the segmentation itself
    works directly off close-equity levels.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _closes(curve: list[dict]) -> list[tuple[str, float]]:
    """Ordered (date, close_equity) pairs from the daily curve."""
    return [(bar["date"], float(bar["close_equity"])) for bar in curve]


def _make_segment(points: list[tuple[str, float]], lo: int, hi: int,
                  threshold_pct: float, force_open: bool = False) -> dict:
    """Build a segment dict spanning points[lo..hi] (inclusive indices).

    ``direction`` is advance/decline by the sign of the move, unless the move's
    magnitude is below ``threshold_pct`` (only possible for the trailing open
    leg), in which case it is labelled "flat".
    """
    start_date, start_equity = points[lo]
    end_date, end_equity = points[hi]
    if start_equity == 0.0:
        return_pct = 0.0
    else:
        return_pct = (end_equity / start_equity - 1.0) * 100.0
    magnitude_pct = abs(return_pct)
    if force_open and magnitude_pct < threshold_pct:
        direction = "flat"
    elif return_pct > 0.0:
        direction = "advance"
    elif return_pct < 0.0:
        direction = "decline"
    else:
        direction = "flat"
    return {
        "direction":     direction,
        "start_date":    start_date,
        "end_date":      end_date,
        "start_equity":  round(start_equity, 2),
        "end_equity":    round(end_equity, 2),
        "return_pct":    round(return_pct, 6),
        "length_days":   hi - lo,
        "magnitude_pct": round(magnitude_pct, 6),
    }


def _zigzag_segments(points: list[tuple[str, float]],
                     threshold_pct: float) -> list[dict]:
    """Zig-zag swing segmentation of the close-equity series.

    Walks the series tracking the running extreme of the in-progress leg. When
    the price retraces from that extreme by more than ``threshold_pct`` (a
    fractional move, not absolute dollars), the leg is closed at the extreme and
    a new leg begins in the opposite direction.

    Returns an ordered list of segment dicts. The final leg (from the last
    confirmed pivot to the end of the series) is always emitted as an open leg
    (and may be labelled "flat" if it never moved past the threshold).
    """
    n = len(points)
    if n < 2:
        return []

    threshold = max(0.0, float(threshold_pct)) / 100.0

    segments: list[dict] = []
    pivot_idx = 0                      # index of the last confirmed pivot
    ext_idx = 1                        # index of the running extreme of this leg
    direction = 0                      # +1 up leg, -1 down leg, 0 undetermined

    # Seed the initial direction from the first non-flat move past the pivot.
    for i in range(1, n):
        _d, price = points[i]
        _pd, pivot_price = points[pivot_idx]
        if pivot_price == 0.0:
            ext_idx = i
            continue
        move = price / pivot_price - 1.0
        if move > 0:
            direction = 1
        elif move < 0:
            direction = -1
        else:
            direction = 0
        ext_idx = i
        break
    else:  # all equal to the pivot price → totally flat series
        segments.append(_make_segment(points, 0, n - 1, threshold_pct,
                                       force_open=True))
        return segments

    if direction == 0:
        # First differing price had a zero move (e.g. pivot==0); treat as flat.
        segments.append(_make_segment(points, 0, n - 1, threshold_pct,
                                       force_open=True))
        return segments

    _d, ext_price = points[ext_idx]

    for i in range(ext_idx + 1, n):
        _d, price = points[i]
        if direction == 1:
            if price > ext_price:
                ext_price = price
                ext_idx = i
            elif ext_price != 0.0 and (price / ext_price - 1.0) <= -threshold:
                # Confirmed downward reversal: close the up leg at the extreme.
                segments.append(
                    _make_segment(points, pivot_idx, ext_idx, threshold_pct))
                pivot_idx = ext_idx
                direction = -1
                ext_price = price
                ext_idx = i
        else:  # direction == -1
            if price < ext_price:
                ext_price = price
                ext_idx = i
            elif ext_price != 0.0 and (price / ext_price - 1.0) >= threshold:
                # Confirmed upward reversal: close the down leg at the extreme.
                segments.append(
                    _make_segment(points, pivot_idx, ext_idx, threshold_pct))
                pivot_idx = ext_idx
                direction = 1
                ext_price = price
                ext_idx = i

    # Emit the trailing, still-open leg from the last pivot to the series end.
    segments.append(_make_segment(points, pivot_idx, n - 1, threshold_pct,
                                  force_open=True))
    return segments


def _phase_summary(segments: list[dict], direction: str) -> dict:
    """Aggregate per-phase statistics for one direction (advance/decline/flat)."""
    legs = [s for s in segments if s["direction"] == direction]
    if not legs:
        return {
            "count":           0,
            "total_return_pct": 0.0,
            "mean_return_pct": None,
            "max_return_pct":  None,
            "mean_length_days": None,
            "max_length_days": None,
            "longest": None,
        }
    returns = [s["return_pct"] for s in legs]
    lengths = [s["length_days"] for s in legs]
    longest = max(legs, key=lambda s: s["length_days"])
    # For advance, "max" return is the most positive; for decline, most negative.
    if direction == "decline":
        max_return = min(returns)
    else:
        max_return = max(returns)
    return {
        "count":            len(legs),
        "total_return_pct": round(sum(returns), 6),
        "mean_return_pct":  round(statistics.fmean(returns), 6),
        "max_return_pct":   round(max_return, 6),
        "mean_length_days": round(statistics.fmean(lengths), 6),
        "max_length_days":  max(lengths),
        "longest": {
            "start_date":    longest["start_date"],
            "end_date":      longest["end_date"],
            "length_days":   longest["length_days"],
            "magnitude_pct": longest["magnitude_pct"],
        },
    }


def _extreme_segment(segments: list[dict], direction: str) -> dict | None:
    """The segment of ``direction`` with the largest magnitude_pct (or None)."""
    legs = [s for s in segments if s["direction"] == direction]
    if not legs:
        return None
    seg = max(legs, key=lambda s: s["magnitude_pct"])
    return {
        "start_date":    seg["start_date"],
        "end_date":      seg["end_date"],
        "return_pct":    seg["return_pct"],
        "magnitude_pct": seg["magnitude_pct"],
        "length_days":   seg["length_days"],
    }


def _trend_summary(segments: list[dict], curve: list[dict]) -> str:
    """Coarse, conservative trend label for the whole series.

    Combines the sign of the total cumulative return with the relative share of
    advance vs decline magnitude across confirmed legs. Only commits to
    up/down-trending when both the net move and the dominant phase magnitude
    agree; otherwise "choppy".
    """
    if len(curve) < 2 or not segments:
        return "insufficient_data"

    cum = curve[-1].get("cumulative_return_pct", 0.0) or 0.0
    adv_mag = sum(s["magnitude_pct"] for s in segments if s["direction"] == "advance")
    dec_mag = sum(s["magnitude_pct"] for s in segments if s["direction"] == "decline")
    total_mag = adv_mag + dec_mag
    if total_mag <= 0.0:
        return "choppy"
    adv_share = adv_mag / total_mag
    dec_share = dec_mag / total_mag

    if cum > 0.0 and adv_share >= _TREND_DOMINANCE:
        return "uptrending"
    if cum < 0.0 and dec_share >= _TREND_DOMINANCE:
        return "downtrending"
    return "choppy"


def compute_regime_segmentation(
    curve: list[dict],
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> dict:
    """Segment a daily equity curve into directional regimes (read-only).

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        threshold_pct: zig-zag reversal threshold in percent.

    Returns:
        A stable-schema dict; undefined statistics are ``None``. Never raises.
    """
    threshold_pct = max(0.0, float(threshold_pct))
    points = _closes(curve)
    n = len(points)

    if n < 2:
        return {
            "execution_mode":  "read_only_simulation",
            "threshold_pct":   round(threshold_pct, 6),
            "num_days":        n,
            "first_date":      points[0][0] if n else None,
            "last_date":       points[-1][0] if n else None,
            "num_segments":    0,
            "segments":        [],
            "advance":         _phase_summary([], "advance"),
            "decline":         _phase_summary([], "decline"),
            "flat":            _phase_summary([], "flat"),
            "current_regime":  None,
            "largest_advance": None,
            "largest_decline": None,
            "trend_summary":   "insufficient_data",
        }

    segments = _zigzag_segments(points, threshold_pct)
    current = segments[-1] if segments else None
    current_regime = None
    if current is not None:
        current_regime = {
            "direction":    current["direction"],
            "start_date":   current["start_date"],
            "end_date":     current["end_date"],
            "length_days":  current["length_days"],
            "return_pct":   current["return_pct"],
            "magnitude_pct": current["magnitude_pct"],
        }

    return {
        "execution_mode":  "read_only_simulation",
        "threshold_pct":   round(threshold_pct, 6),
        "num_days":        n,
        "first_date":      points[0][0],
        "last_date":       points[-1][0],
        "num_segments":    len(segments),
        "segments":        segments,
        "advance":         _phase_summary(segments, "advance"),
        "decline":         _phase_summary(segments, "decline"),
        "flat":            _phase_summary(segments, "flat"),
        "current_regime":  current_regime,
        "largest_advance": _extreme_segment(segments, "advance"),
        "largest_decline": _extreme_segment(segments, "decline"),
        "trend_summary":   _trend_summary(segments, curve),
    }


def generate_regime_segmentation_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> dict:
    """Build the full regime-segmentation report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        threshold_pct: zig-zag reversal threshold in percent.

    Returns:
        ``{"generated_at", "source", "segmentation"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "segmentation": compute_regime_segmentation(curve, threshold_pct),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "regime segmentation report written: %s (%d days, %d segments, trend=%s)",
                out, report["segmentation"]["num_days"],
                report["segmentation"]["num_segments"],
                report["segmentation"]["trend_summary"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write regime segmentation report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Segment the paper-trading daily equity curve into "
                    "directional regimes (advance / decline / flat swings) via "
                    "a zig-zag reversal detector. Read-only path decomposition.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/regime_segmentation.json)",
    )
    p.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD_PCT,
        help=f"zig-zag reversal threshold in %% (default: {DEFAULT_THRESHOLD_PCT})",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_regime_segmentation_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        threshold_pct=args.threshold,
    )
    print(json.dumps(report["segmentation"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
