#!/usr/bin/env python3
"""Portfolio Optimizer (SPA / MP-1249) — read-only / advisory.

Finds optimal allocation weights across a fixed protocol universe by an
exhaustive **grid search** over weight combinations (step = 5%), scoring each
valid portfolio on its realised 365-day historical APY series. Pure stdlib —
no numpy/scipy. Strictly READ-ONLY and advisory: it reads the historical APY
files and (for the comparison) ``current_positions.json``, and writes only its
own ``data/optimizer_results.json`` artifact. It never touches the allocator,
risk policy, or execution domains.

Universe & categorization
=========================
    T1 (cap 100% each)  : aave_v3_usdc, compound_v3_usdc, sky_susds*
    T2 (cap 20% each,   : yearn_v3_usdc, morpho_blue_usdc
        50% total)

    * sky_susds is a low-volatility stable; per the task spec it is treated as
      T1 for allocation purposes.

Grid search
===========
Weights are enumerated in 5% steps within these bounds (task spec):

    aave     10..60 %
    compound 10..60 %
    sky       0..30 %
    yearn     0..20 %   (T2)
    morpho    0..20 %   (T2)

A combination is valid iff the five weights sum to exactly 100% AND the T2
total (yearn + morpho) ≤ 50%. For every valid combination we build the
365-day portfolio daily-return series and compute:

    * annualized return (CAGR) from the compounded equity curve
    * daily Sharpe  = mean(daily_return) / std(daily_return)
    * max drawdown  = worst peak→trough decline of the equity curve

The blended score follows the task spec verbatim (decimal units):

    score = 0.5 * cagr + 0.3 * sharpe_daily + 0.2 * (1 - max_dd)

APY convention
==============
Each historical file is a list of ``{"date", "apy"}`` where ``apy`` is a
PERCENT (e.g. 3.69 == 3.69% APY). A daily simple return is ``apy / 100 / 365``.

CLI (offline, exit 0 always)::

    python3 -m spa_core.analytics.portfolio_optimizer --check            # compute + print, no write (default)
    python3 -m spa_core.analytics.portfolio_optimizer --run              # + atomic write to data/optimizer_results.json
    python3 -m spa_core.analytics.portfolio_optimizer --run --data-dir <dir>
    python3 -m spa_core.analytics.portfolio_optimizer --step 5          # grid step in percent (default 5)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Universe / categorization
# --------------------------------------------------------------------------- #

UNIVERSE: List[str] = [
    "aave_v3_usdc",
    "compound_v3_usdc",
    "sky_susds",
    "yearn_v3_usdc",
    "morpho_blue_usdc",
]

# Short keys used in the weight dicts (stable order matches UNIVERSE).
KEYS: List[str] = ["aave", "compound", "sky", "yearn", "morpho"]

KEY_TO_FILE: Dict[str, str] = {
    "aave": "aave_v3_usdc",
    "compound": "compound_v3_usdc",
    "sky": "sky_susds",
    "yearn": "yearn_v3_usdc",
    "morpho": "morpho_blue_usdc",
}

TIER: Dict[str, str] = {
    "aave": "T1",
    "compound": "T1",
    "sky": "T1",      # stable, treated as T1 per spec
    "yearn": "T2",
    "morpho": "T2",
}

T2_KEYS = ("yearn", "morpho")

# Grid bounds (percent). (lo, hi) inclusive.
BOUNDS: Dict[str, Tuple[int, int]] = {
    "aave": (10, 60),
    "compound": (10, 60),
    "sky": (0, 30),
    "yearn": (0, 20),
    "morpho": (0, 20),
}

T2_PER_CAP_PCT = 20.0   # max per T2 protocol
T2_TOTAL_CAP_PCT = 50.0  # max T2 total

TRADING_DAYS = 365

# Map current live positions -> universe keys (for STEP 4 comparison).
LIVE_TO_KEY: Dict[str, str] = {
    "aave_v3": "aave",
    "compound_v3": "compound",
    "yearn_v3": "yearn",
    "morpho_blue": "morpho",
    "spark_susds": "sky",
    "susds": "sky",
    "sky_susds": "sky",
}


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def load_series(data_dir: Path) -> Dict[str, List[float]]:
    """Load the APY (percent) series for every universe protocol.

    Returns ``{key: [apy_pct, ...]}`` truncated to the common (shortest)
    length so all series align day-for-day. Raises ValueError on a missing
    or empty file (caller in __main__ converts that to a clean exit).
    """
    raw: Dict[str, List[float]] = {}
    for key in KEYS:
        fpath = data_dir / "historical_apy" / f"{KEY_TO_FILE[key]}.json"
        if not fpath.exists():
            raise ValueError(f"missing history file: {fpath}")
        with fpath.open("r", encoding="utf-8") as fh:
            records = json.load(fh)
        series = [float(r["apy"]) for r in records if r.get("apy") is not None]
        if not series:
            raise ValueError(f"empty series: {fpath}")
        raw[key] = series

    n = min(len(s) for s in raw.values())
    return {key: s[-n:] for key, s in raw.items()}


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def daily_returns(weights: Dict[str, float], series: Dict[str, List[float]]) -> List[float]:
    """Portfolio daily *simple* returns from per-protocol APY-percent series.

    weights are fractions summing to 1.0; daily return of a protocol on day t
    is ``apy_pct / 100 / 365``.
    """
    n = len(next(iter(series.values())))
    out: List[float] = []
    for t in range(n):
        r = 0.0
        for key, w in weights.items():
            if w:
                r += w * (series[key][t] / 100.0 / TRADING_DAYS)
        out.append(r)
    return out


def portfolio_metrics(weights: Dict[str, float], series: Dict[str, List[float]]) -> Dict[str, float]:
    """Compute CAGR, daily Sharpe, max drawdown and expected APY for a portfolio."""
    rets = daily_returns(weights, series)
    n = len(rets)

    # Equity curve (compounded) + max drawdown.
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= (1.0 + r)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Annualized return (CAGR). With n==365 this is ~ the total compounded
    # return over the window; the exponent generalises to any window length.
    cagr = equity ** (TRADING_DAYS / n) - 1.0 if n > 0 and equity > 0 else 0.0

    mean_r = _mean(rets)
    std_r = _std(rets)
    sharpe_daily = mean_r / std_r if std_r > 0 else 0.0

    # Expected (mean) APY = weighted average of each protocol's mean APY.
    exp_apy = sum(w * _mean(series[k]) for k, w in weights.items())

    return {
        "cagr_pct": round(cagr * 100.0, 4),
        "sharpe_daily": round(sharpe_daily, 4),
        "sharpe_annualized": round(sharpe_daily * math.sqrt(TRADING_DAYS), 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "expected_apy_pct": round(exp_apy, 4),
        # raw decimals for scoring
        "_cagr": cagr,
        "_sharpe": sharpe_daily,
        "_max_dd": max_dd,
    }


def blended_score(m: Dict[str, float]) -> float:
    """score = 0.5*cagr + 0.3*sharpe_daily + 0.2*(1 - max_dd) (decimal units)."""
    return 0.5 * m["_cagr"] + 0.3 * m["_sharpe"] + 0.2 * (1.0 - m["_max_dd"])


# --------------------------------------------------------------------------- #
# Grid search
# --------------------------------------------------------------------------- #

def _frange(lo: int, hi: int, step: int) -> List[int]:
    out = []
    v = lo
    while v <= hi:
        out.append(v)
        v += step
    return out


def grid_search(series: Dict[str, List[float]], step: int = 5) -> List[Dict]:
    """Enumerate every valid weight combination and score it.

    Returns a list of portfolio dicts: ``{"weights": {...}, "weights_pct":
    {...}, "metrics": {...}, "score": float}``, one per valid combination.
    """
    if step <= 0:
        raise ValueError("step must be a positive integer (percent)")

    grids = {k: _frange(BOUNDS[k][0], BOUNDS[k][1], step) for k in KEYS}
    results: List[Dict] = []

    for aave in grids["aave"]:
        for compound in grids["compound"]:
            # prune early on partial sum
            if aave + compound > 100:
                continue
            for sky in grids["sky"]:
                if aave + compound + sky > 100:
                    continue
                for yearn in grids["yearn"]:
                    base = aave + compound + sky + yearn
                    if base > 100:
                        continue
                    morpho = 100 - base
                    # morpho must fall on the grid and within its bounds
                    if morpho < BOUNDS["morpho"][0] or morpho > BOUNDS["morpho"][1]:
                        continue
                    if morpho % step != 0:
                        continue
                    # T2 caps
                    if yearn > T2_PER_CAP_PCT or morpho > T2_PER_CAP_PCT:
                        continue
                    if yearn + morpho > T2_TOTAL_CAP_PCT:
                        continue

                    pct = {
                        "aave": aave, "compound": compound, "sky": sky,
                        "yearn": yearn, "morpho": morpho,
                    }
                    weights = {k: v / 100.0 for k, v in pct.items()}
                    metrics = portfolio_metrics(weights, series)
                    results.append({
                        "weights": weights,
                        "weights_pct": pct,
                        "t2_total_pct": yearn + morpho,
                        "metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
                        "score": round(blended_score(metrics), 6),
                    })
    return results


def _clean(p: Dict) -> Dict:
    """Strip internal underscore-prefixed scratch fields for serialization."""
    return p


# --------------------------------------------------------------------------- #
# Comparison vs current live allocation (STEP 4)
# --------------------------------------------------------------------------- #

def current_allocation_apy(data_dir: Path, series: Dict[str, List[float]]) -> Optional[Dict]:
    """Map current_positions.json onto the universe and compute its expected APY.

    Only the positions that map to a universe protocol are considered; their
    USD amounts are renormalized to weights summing to 1.0 so the figure is
    directly comparable to an optimizer portfolio (which is fully invested
    across the universe). Returns None if no positions map.
    """
    fpath = data_dir / "current_positions.json"
    if not fpath.exists():
        return None
    try:
        with fpath.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None

    positions = doc.get("positions") or {}
    mapped: Dict[str, float] = {k: 0.0 for k in KEYS}
    for name, usd in positions.items():
        key = LIVE_TO_KEY.get(name)
        if key:
            mapped[key] += float(usd)

    total = sum(mapped.values())
    if total <= 0:
        return None

    weights = {k: v / total for k, v in mapped.items()}
    metrics = portfolio_metrics(weights, series)
    return {
        "source_file": str(fpath),
        "mapped_usd": {k: round(v, 2) for k, v in mapped.items() if v > 0},
        "weights_pct": {k: round(w * 100.0, 2) for k, w in weights.items() if w > 0},
        "expected_apy_pct": metrics["expected_apy_pct"],
        "cagr_pct": metrics["cagr_pct"],
        "sharpe_daily": metrics["sharpe_daily"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "note": (
            "Weights are the universe-mapped live positions "
            "(aave_v3, compound_v3, yearn_v3, morpho_blue, spark_susds) "
            "renormalized to 100%; non-universe positions are excluded."
        ),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def optimize(data_dir: Path, step: int = 5, run_date: Optional[str] = None) -> Dict:
    """Run the full optimization and assemble the results document."""
    series = load_series(data_dir)
    portfolios = grid_search(series, step=step)
    if not portfolios:
        raise ValueError("grid search produced no valid portfolios")

    by_blended = sorted(portfolios, key=lambda p: p["score"], reverse=True)
    by_return = sorted(portfolios, key=lambda p: p["metrics"]["cagr_pct"], reverse=True)
    by_sharpe = sorted(portfolios, key=lambda p: p["metrics"]["sharpe_daily"], reverse=True)

    if run_date is None:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    comparison: Optional[Dict] = None
    current = current_allocation_apy(data_dir, series)
    if current is not None:
        best = by_blended[0]
        opt_apy = best["metrics"]["expected_apy_pct"]
        cur_apy = current["expected_apy_pct"]
        comparison = {
            "optimal_expected_apy_pct": opt_apy,
            "current_expected_apy_pct": cur_apy,
            "apy_difference_pct": round(opt_apy - cur_apy, 4),
            "optimal_weights_pct": best["weights_pct"],
            "current_weights_pct": current["weights_pct"],
            "summary": (
                f"Optimal (blended) allocation would have returned "
                f"{opt_apy:.2f}% APY vs current {cur_apy:.2f}% "
                f"(+{opt_apy - cur_apy:.2f} pp)."
            ),
        }

    return {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": UNIVERSE,
        "categorization": {k: TIER[k] for k in KEYS},
        "grid_step_pct": step,
        "constraints": {
            "t1_max_pct": 100,
            "t2_per_protocol_max_pct": T2_PER_CAP_PCT,
            "t2_total_max_pct": T2_TOTAL_CAP_PCT,
            "bounds_pct": {k: list(BOUNDS[k]) for k in KEYS},
        },
        "score_formula": "0.5*cagr + 0.3*sharpe_daily + 0.2*(1 - max_drawdown)",
        "num_portfolios_evaluated": len(portfolios),
        "best_by_return": by_return[0],
        "best_by_sharpe": by_sharpe[0],
        "best_blended": by_blended[0],
        "top_10": by_blended[:10],
        "comparison_vs_current": comparison,
    }


def _atomic_write(path: Path, doc: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".opt_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _format_portfolio(p: Dict) -> str:
    w = p["weights_pct"]
    m = p["metrics"]
    parts = ", ".join(f"{k}={w[k]}%" for k in KEYS if w[k])
    return (f"  [{parts}]  apy={m['expected_apy_pct']:.2f}%  "
            f"cagr={m['cagr_pct']:.2f}%  sharpe_d={m['sharpe_daily']:.3f}  "
            f"maxDD={m['max_drawdown_pct']:.2f}%  score={p['score']:.4f}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="portfolio_optimizer",
        description="Grid-search portfolio optimizer over historical APY (read-only).",
    )
    parser.add_argument("--run", action="store_true",
                        help="write results to data/optimizer_results.json (default: --check, no write)")
    parser.add_argument("--check", action="store_true",
                        help="compute and print only, no write (default)")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument("--step", type=int, default=5, help="grid step in percent (default 5)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir()

    try:
        doc = optimize(data_dir, step=args.step)
    except Exception as exc:  # noqa: BLE001 — CLI must never traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 0

    print(f"Portfolio Optimizer — {doc['num_portfolios_evaluated']} valid portfolios "
          f"(step={doc['grid_step_pct']}%)\n")
    print("Best by BLENDED score:")
    print(_format_portfolio(doc["best_blended"]))
    print("Best by RETURN (CAGR):")
    print(_format_portfolio(doc["best_by_return"]))
    print("Best by SHARPE (daily):")
    print(_format_portfolio(doc["best_by_sharpe"]))
    print("\nTop 10 by blended score:")
    for i, p in enumerate(doc["top_10"], 1):
        print(f"{i:2d}.{_format_portfolio(p)}")

    cmp = doc.get("comparison_vs_current")
    if cmp:
        print("\nComparison vs current live allocation:")
        print(f"  {cmp['summary']}")

    if args.run:
        out = data_dir / "optimizer_results.json"
        _atomic_write(out, doc)
        print(f"\nWrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
