"""
Paper-trading bootstrap Monte Carlo forward equity projection (SPA-V395).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). The existing paper-trading analytics all look
*backwards* — headline ratios (``risk_metrics.py`` / SPA-V380), trailing windows
(``rolling_performance.py`` / SPA-V381), drawdown episodes
(``drawdown_analysis.py`` / SPA-V382), the return distribution + tail risk
(``return_distribution.py`` / SPA-V383), the calendar/streak view
(``calendar_returns.py`` / SPA-V384) and the benchmark-relative battery
(``benchmark_comparison.py`` / SPA-V394). What none of them answer is "given the
*shape* of the realised daily returns so far, what might the portfolio look like
``N`` days from now, and how wide is the cone of outcomes" — the forward-looking
projection an investor/reporting layer wants next to the equity sparkline.

It answers that with a **non-parametric bootstrap Monte Carlo**: it resamples the
realised daily-return series (sampling *with replacement*) to build many
synthetic forward equity paths, compounds each over the horizon and summarises
the distribution of terminal outcomes plus a confidence-band view of the path.

Method (bootstrap / historical resampling):
    For each of ``num_simulations`` simulations, draw ``horizon_days`` daily
    returns uniformly at random *with replacement* from the realised history and
    compound them onto ``start_equity``. This makes no parametric (normality)
    assumption — it inherits the empirical mean, volatility, skew and fat tails
    of the actual returns. A seeded ``random.Random`` makes the whole projection
    deterministic and reproducible.

Design notes / safety:
  * Pure stdlib (json, math, statistics, random, datetime, pathlib, logging,
    argparse) — mirrors the no-external-dependency style of the sibling modules.
    No web3, no numpy/pandas/scipy, no network.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. It is pure portfolio-performance analytics.
  * Defensive: degenerate inputs (empty history, 0 or 1 day of realised returns,
    ``horizon_days <= 0``, ``num_simulations <= 0``) never raise — they return a
    valid, stable, empty-ish schema (``num_historical_returns`` reflects the data
    and the probability / percentile fields fall back to ``start_equity`` or
    ``None``).

Output schema (see ``compute_monte_carlo_projection``):
    inputs                  echo of the run parameters + realised return stats
    terminal_equity         percentiles (p5..p95) + mean/min/max/stdev of the
                            simulated terminal equity
    terminal_return_pct     same percentiles + mean for total return % vs
                            start_equity
    probability_of_profit   fraction of sims ending above start_equity
    probability_of_loss     fraction of sims ending below start_equity
    expected_max_drawdown_pct  mean over sims of each path's worst intra-path
                            drawdown (<= 0)
    equity_percentile_bands p5/p50/p95 equity at a handful of control days along
                            the horizon (for confidence-band charts)

CLI::

    python -m spa_core.analytics_lab.monte_carlo_projection
    python -m spa_core.analytics_lab.monte_carlo_projection --history data/pnl_history.json \\
        --out data/monte_carlo_projection.json --horizon 30 --simulations 10000 --seed 42
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.monte_carlo_projection")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "monte_carlo_projection.json"

# Run defaults. The seed is fixed so the persisted report is deterministic.
DEFAULT_HORIZON_DAYS = 30
DEFAULT_NUM_SIMULATIONS = 10000
DEFAULT_SEED = 42
DEFAULT_START_EQUITY_FALLBACK = 10000.0
DEFAULT_CONFIDENCE_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# Number of control days sampled along the horizon for the confidence bands.
DEFAULT_BAND_POINTS = 10


def _daily_returns_fraction(curve: list[dict]) -> list[float]:
    """Realised daily returns as *fractions* — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the resample toward zero. Mirrors the convention
    used by ``return_distribution._daily_returns`` / ``benchmark_comparison``,
    but converts percent -> fraction for compounding.
    """
    return [bar["daily_return_pct"] / 100.0 for bar in curve[1:]]


def _percentile_key(level: float) -> str:
    """Map a confidence level (fraction) to a stable key, e.g. 0.05 -> 'p5'."""
    return "p" + format(level * 100.0, "g")


def _percentile(sorted_values: list[float], level: float) -> float:
    """Linear-interpolation percentile (NIST/Excel ``PERCENTILE.INC`` style).

    ``sorted_values`` must be ascending and non-empty. ``level`` in [0, 1].
    Mirrors ``return_distribution._percentile`` (which takes percent 0..100).
    """
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = level * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _rnd(x: float | None, places: int = 2) -> float | None:
    """Round helper that passes ``None`` through unchanged."""
    return None if x is None else round(x, places)


def _start_equity_from_curve(curve: list[dict]) -> float:
    """Default starting equity: the last day's close (fallback constant)."""
    if curve:
        close = curve[-1].get("close_equity")
        if isinstance(close, (int, float)) and not isinstance(close, bool):
            return float(close)
    return DEFAULT_START_EQUITY_FALLBACK


def _band_day_indices(horizon_days: int, max_points: int) -> list[int]:
    """Control-day indices (1-based, into [1, horizon_days]) for the bands.

    Returns up to ``max_points`` roughly-evenly-spaced days, always including
    the final day so the band terminates at the horizon.
    """
    if horizon_days <= 0:
        return []
    if horizon_days <= max_points:
        return list(range(1, horizon_days + 1))
    # Evenly spaced across [1, horizon_days], inclusive of both ends.
    days = sorted({
        int(round(1 + i * (horizon_days - 1) / (max_points - 1)))
        for i in range(max_points)
    })
    if days[-1] != horizon_days:
        days[-1] = horizon_days
    return days


def compute_monte_carlo_projection(
    curve: list[dict],
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    start_equity: float | None = None,
    seed: int | None = None,
    confidence_levels: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCE_LEVELS,
    include_paths: bool = False,
    band_points: int = DEFAULT_BAND_POINTS,
) -> dict:
    """Bootstrap Monte Carlo forward equity projection from a daily curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        horizon_days: number of forward days to project.
        num_simulations: number of bootstrap paths.
        start_equity: starting capital; defaults to the last day's close equity
            (or ``10000.0`` when there is no curve).
        seed: PRNG seed for reproducibility (``random.Random(seed)``).
        confidence_levels: percentile levels (fractions in (0, 1)).
        include_paths: when True, also return every full simulated equity path
            under ``"simulated_paths"`` (off by default to keep the JSON small).
        band_points: number of control days sampled for ``equity_percentile_bands``.

    Returns:
        A stable-schema projection dict. Degenerate inputs (no realised returns,
        non-positive horizon/simulations) yield a valid empty-ish projection
        rather than raising.
    """
    levels = sorted(float(c) for c in confidence_levels)
    start = float(start_equity) if start_equity is not None else _start_equity_from_curve(curve)
    returns = _daily_returns_fraction(curve)
    n_hist = len(returns)

    mean_daily = statistics.fmean(returns) if n_hist else None
    vol_daily = statistics.pstdev(returns) if n_hist >= 1 else None

    inputs = {
        "horizon_days":          int(horizon_days),
        "num_simulations":       int(num_simulations),
        "start_equity":          _rnd(start),
        "num_historical_returns": n_hist,
        "seed":                  seed,
        "mean_daily_return_pct": None if mean_daily is None else round(mean_daily * 100.0, 6),
        "daily_volatility_pct":  None if vol_daily is None else round(vol_daily * 100.0, 6),
    }

    # Empty-but-stable terminal blocks (used for every degenerate branch).
    empty_terminal_equity = {_percentile_key(c): None for c in levels}
    empty_terminal_equity.update({"mean": None, "min": None, "max": None, "stdev": None})
    empty_terminal_return = {_percentile_key(c): None for c in levels}
    empty_terminal_return["mean"] = None

    base = {
        "inputs":                  inputs,
        "terminal_equity":         dict(empty_terminal_equity),
        "terminal_return_pct":     dict(empty_terminal_return),
        "probability_of_profit":   None,
        "probability_of_loss":     None,
        "expected_max_drawdown_pct": None,
        "equity_percentile_bands": [],
    }
    if include_paths:
        base["simulated_paths"] = []

    # Degenerate: nothing to resample, or a non-positive run shape. The terminal
    # equity is simply the (unchanged) start equity at every percentile so the
    # schema stays stable and chartable.
    if n_hist == 0 or horizon_days <= 0 or num_simulations <= 0:
        flat_equity = {_percentile_key(c): _rnd(start) for c in levels}
        flat_equity.update({
            "mean": _rnd(start), "min": _rnd(start),
            "max": _rnd(start), "stdev": 0.0,
        })
        flat_return = {_percentile_key(c): 0.0 for c in levels}
        flat_return["mean"] = 0.0
        base["terminal_equity"] = flat_equity
        base["terminal_return_pct"] = flat_return
        base["probability_of_profit"] = None
        base["probability_of_loss"] = None
        base["expected_max_drawdown_pct"] = None
        return base

    rng = random.Random(seed)
    band_days = _band_day_indices(horizon_days, band_points)
    band_day_set = set(band_days)
    # Collect equity at each control day across sims for the confidence bands.
    band_samples: dict[int, list[float]] = {d: [] for d in band_days}

    terminal_equities: list[float] = []
    max_drawdowns: list[float] = []
    all_paths: list[list[float]] = [] if include_paths else []

    for _sim in range(num_simulations):
        equity = start
        peak = start
        worst_dd = 0.0
        path = [] if include_paths else None
        for day in range(1, horizon_days + 1):
            r = returns[rng.randrange(n_hist)]
            equity *= (1.0 + r)
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (equity / peak - 1.0) * 100.0
                if dd < worst_dd:
                    worst_dd = dd
            if path is not None:
                path.append(equity)
            if day in band_day_set:
                band_samples[day].append(equity)
        terminal_equities.append(equity)
        max_drawdowns.append(worst_dd)
        if include_paths and path is not None:
            all_paths.append([round(e, 2) for e in path])

    sorted_eq = sorted(terminal_equities)
    term_equity = {_percentile_key(c): _rnd(_percentile(sorted_eq, c)) for c in levels}
    term_equity.update({
        "mean":  _rnd(statistics.fmean(terminal_equities)),
        "min":   _rnd(sorted_eq[0]),
        "max":   _rnd(sorted_eq[-1]),
        "stdev": _rnd(statistics.pstdev(terminal_equities)) if len(terminal_equities) >= 1 else 0.0,
    })

    def _to_return_pct(eq: float) -> float:
        return (eq / start - 1.0) * 100.0 if start else 0.0

    sorted_ret = [_to_return_pct(e) for e in sorted_eq]
    term_return = {_percentile_key(c): _rnd(_percentile(sorted_ret, c), 4) for c in levels}
    term_return["mean"] = _rnd(_to_return_pct(statistics.fmean(terminal_equities)), 4)

    profits = sum(1 for e in terminal_equities if e > start)
    losses = sum(1 for e in terminal_equities if e < start)
    prob_profit = profits / len(terminal_equities)
    prob_loss = losses / len(terminal_equities)

    expected_max_dd = statistics.fmean(max_drawdowns) if max_drawdowns else None

    bands = []
    for d in band_days:
        samples = sorted(band_samples[d])
        if not samples:
            continue
        bands.append({
            "day": d,
            "p5":  _rnd(_percentile(samples, 0.05)),
            "p50": _rnd(_percentile(samples, 0.50)),
            "p95": _rnd(_percentile(samples, 0.95)),
        })

    result = {
        "inputs":                  inputs,
        "terminal_equity":         term_equity,
        "terminal_return_pct":     term_return,
        "probability_of_profit":   round(prob_profit, 4),
        "probability_of_loss":     round(prob_loss, 4),
        "expected_max_drawdown_pct": _rnd(expected_max_dd, 4),
        "equity_percentile_bands": bands,
    }
    if include_paths:
        result["simulated_paths"] = all_paths
    return result


def generate_monte_carlo_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    out_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    start_equity: float | None = None,
    seed: int | None = DEFAULT_SEED,
    confidence_levels: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCE_LEVELS,
    include_paths: bool = False,
    band_points: int = DEFAULT_BAND_POINTS,
) -> dict:
    """Build the full Monte Carlo projection report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        out_path: where to write the report JSON. Pass ``None`` to skip writing
            (compute-only).
        horizon_days, num_simulations, start_equity, seed, confidence_levels,
        include_paths, band_points: forwarded to
            ``compute_monte_carlo_projection``.

    Returns:
        ``{"generated_at", "source", "projection"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "projection":   compute_monte_carlo_projection(
            curve,
            horizon_days=horizon_days,
            num_simulations=num_simulations,
            start_equity=start_equity,
            seed=seed,
            confidence_levels=confidence_levels,
            include_paths=include_paths,
            band_points=band_points,
        ),
    }

    if out_path is not None:
        out = Path(out_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            proj = report["projection"]
            log.info(
                "monte carlo projection report written: %s (%d hist returns, "
                "horizon=%d, sims=%d, p50_terminal=%s, P(profit)=%s)",
                out, proj["inputs"]["num_historical_returns"],
                proj["inputs"]["horizon_days"], proj["inputs"]["num_simulations"],
                proj["terminal_equity"].get("p50"), proj["probability_of_profit"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write monte carlo projection report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bootstrap Monte Carlo forward equity projection from "
                    "paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/monte_carlo_projection.json)",
    )
    p.add_argument(
        "--horizon", type=int, default=DEFAULT_HORIZON_DAYS,
        help=f"forward horizon in days (default: {DEFAULT_HORIZON_DAYS})",
    )
    p.add_argument(
        "--simulations", type=int, default=DEFAULT_NUM_SIMULATIONS,
        help=f"number of bootstrap simulations (default: {DEFAULT_NUM_SIMULATIONS})",
    )
    p.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"PRNG seed for reproducibility (default: {DEFAULT_SEED})",
    )
    p.add_argument(
        "--start-equity", type=float, default=None,
        help="starting equity (default: last day's close equity)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_monte_carlo_report(
        history_path=args.history,
        out_path=None if args.no_write else args.out,
        horizon_days=args.horizon,
        num_simulations=args.simulations,
        start_equity=args.start_equity,
        seed=args.seed,
    )
    print(json.dumps(report["projection"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
