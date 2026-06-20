"""Strategy Benchmark Tracker (MP-1252).

Builds a **3-dimensional** performance comparison for every strategy:

  1. **backtest**  — historical annualised return (from ``backtest_results.json``
                      synthetic 90-day, or ``backtest_results_real.json`` real 365-day).
  2. **paper**     — current live paper-trading track (``equity_curve_daily.json``),
                      only populated for the one strategy that is actually being run live.
  3. **benchmark** — "lazy Aave": park 100% of capital in Aave V3 (~3.10% APY).

For each strategy it reports the *alpha* (excess return) versus the lazy-Aave
benchmark, on both the backtest and (for the live strategy) the paper track.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace (via spa_core.utils.atomic) on every JSON update.
* LLM_FORBIDDEN domain hygiene: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.strategy_benchmark_tracker --check
    python3 -m spa_core.analytics.strategy_benchmark_tracker --run
    python3 -m spa_core.analytics.strategy_benchmark_tracker --run --real
    python3 -m spa_core.analytics.strategy_benchmark_tracker --check --data-dir /path/to/data

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

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "strategy_benchmark.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# "Lazy Aave" benchmark: park 100% of capital in Aave V3, do nothing.
BENCHMARK_AAVE_APY: float = 3.10

# The strategy that maps to the live paper track. The live blended portfolio is
# T1-anchored equal-weight at its core, so S0 (Baseline / Equal Weight) is the
# representative live strategy. Overridable via constructor.
DEFAULT_ACTIVE_STRATEGY: str = "S0"

# Synthetic 90-day backtest is the primary source (matches dashboard numbers);
# the real 365-day file is opt-in via use_real=True.
_SYNTHETIC_FILE = "backtest_results.json"
_REAL_FILE = "backtest_results_real.json"

_DAYS_PER_YEAR = 365.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> Optional[float]:
    """Coerce to finite float; return None on any failure (preserves 'no data')."""
    if isinstance(val, bool):
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _normalize_id(key: str) -> str:
    """Extract the canonical short id ('S0') from a backtest key ('S0_baseline').

    The leading ``S<number>`` token is the strategy id; everything after the
    first underscore is descriptive.
    """
    if not key:
        return key
    head = key.split("_", 1)[0]
    return head.upper()


# ---------------------------------------------------------------------------
# StrategyBenchmarkTracker
# ---------------------------------------------------------------------------


class StrategyBenchmarkTracker:
    """3-way (backtest / paper / benchmark) comparison per strategy.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory containing data files. Defaults to repo ``data/``.
    use_real : bool
        When True read the real 365-day backtest, else the synthetic 90-day.
    active_strategy_id : str
        Strategy id whose paper track is live (default ``"S0"``).
    benchmark_apy : float
        Lazy-Aave benchmark APY in % (default 3.10).
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        use_real: bool = False,
        active_strategy_id: str = DEFAULT_ACTIVE_STRATEGY,
        benchmark_apy: float = BENCHMARK_AAVE_APY,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.use_real = use_real
        self.active_strategy_id = (active_strategy_id or "").upper()
        self.benchmark_apy = float(benchmark_apy)
        self._backtest_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._paper_cache: Optional[Dict[str, Any]] = None

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def _read_json(self, filename: str) -> Optional[Dict[str, Any]]:
        path = self.data_dir / filename
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        return raw if isinstance(raw, dict) else None

    def load_backtest(self) -> Dict[str, Dict[str, Any]]:
        """Load + normalise backtest strategies → ``{ "S0": {...}, ... }``.

        Each value has: ``annualised_return_pct``, ``strategy_name``,
        ``risk_tier``, ``backtest_key`` (original key), ``source``.
        Returns an empty dict when no backtest file is available.
        """
        if self._backtest_cache is not None:
            return self._backtest_cache

        filename = _REAL_FILE if self.use_real else _SYNTHETIC_FILE
        raw = self._read_json(filename)
        if raw is None and self.use_real:
            # graceful fallback to synthetic
            raw = self._read_json(_SYNTHETIC_FILE)
            filename = _SYNTHETIC_FILE
        source = raw.get("data_source", filename) if raw else filename

        out: Dict[str, Dict[str, Any]] = {}
        strategies = raw.get("strategies") if isinstance(raw, dict) else None
        if isinstance(strategies, dict):
            for key, val in strategies.items():
                if not isinstance(val, dict):
                    continue
                sid = _normalize_id(key)
                ann = _safe_float(val.get("annualised_return_pct"))
                if ann is None:
                    ann = _safe_float(val.get("cagr_pct"))
                # On id collision keep the higher-return variant (deterministic).
                if sid in out and out[sid].get("annualised_return_pct") is not None:
                    prev = out[sid]["annualised_return_pct"]
                    if ann is None or (prev is not None and prev >= ann):
                        continue
                out[sid] = {
                    "annualised_return_pct": ann,
                    "strategy_name": val.get("strategy_name", key),
                    "risk_tier": val.get("risk_tier", ""),
                    "backtest_key": key,
                    "source": source,
                }
        self._backtest_cache = out
        return out

    def load_paper_track(self) -> Dict[str, Any]:
        """Summarise the live paper track from ``equity_curve_daily.json``.

        Uses only the *real* (post-teardown) portion of the curve — the days
        with ``is_warmup == False``. Returns annualised realised return plus
        cumulative figures.

        Returns
        -------
        dict
            ``{available, num_days, start_date, end_date, start_equity,
               end_equity, total_return_pct, annualized_pct, current_apy_pct,
               daily_returns_pct}``.  ``available`` is False when no real days.
        """
        if self._paper_cache is not None:
            return self._paper_cache

        empty = {
            "available": False,
            "num_days": 0,
            "start_date": None,
            "end_date": None,
            "start_equity": None,
            "end_equity": None,
            "total_return_pct": None,
            "annualized_pct": None,
            "current_apy_pct": None,
            "daily_returns_pct": [],
        }

        raw = self._read_json("equity_curve_daily.json")
        daily = raw.get("daily") if isinstance(raw, dict) else None
        if not isinstance(daily, list) or not daily:
            self._paper_cache = empty
            return empty

        real = [d for d in daily if isinstance(d, dict) and not d.get("is_warmup", False)]
        if not real:
            real = [d for d in daily if isinstance(d, dict)]
        if not real:
            self._paper_cache = empty
            return empty

        first, last = real[0], real[-1]
        start_equity = _safe_float(first.get("open_equity")) or _safe_float(
            first.get("equity")
        )
        end_equity = _safe_float(last.get("close_equity")) or _safe_float(
            last.get("equity")
        )
        if not start_equity or not end_equity or start_equity <= 0:
            self._paper_cache = empty
            return empty

        start_date = first.get("date")
        end_date = last.get("date")
        # span = number of daily accrual periods that produced total_return.
        # start_equity is the OPEN of the first real day and end_equity is the
        # CLOSE of the last, so every real day contributes one accrual period.
        span_days = max(1, len(real))

        total_return = end_equity / start_equity - 1.0
        annualized = (1.0 + total_return) ** (_DAYS_PER_YEAR / span_days) - 1.0

        daily_returns = [
            r for r in (_safe_float(d.get("daily_return_pct")) for d in real) if r is not None
        ]
        current_apy = _safe_float(last.get("apy_today"))

        summary = {
            "available": True,
            "num_days": len(real),
            "start_date": start_date,
            "end_date": end_date,
            "start_equity": round(start_equity, 2),
            "end_equity": round(end_equity, 2),
            "total_return_pct": round(total_return * 100.0, 4),
            "annualized_pct": round(annualized * 100.0, 4),
            "current_apy_pct": round(current_apy, 4) if current_apy is not None else None,
            "daily_returns_pct": daily_returns,
            "span_days": span_days,
        }
        self._paper_cache = summary
        return summary

    # -----------------------------------------------------------------------
    # Core comparison
    # -----------------------------------------------------------------------

    def get_comparison(self, strategy_id: str) -> Dict[str, Any]:
        """Return the 3-way comparison dict for one strategy id (e.g. ``"S0"``)."""
        sid = (strategy_id or "").upper()
        backtest = self.load_backtest()
        info = backtest.get(sid, {})
        bt_ann = info.get("annualised_return_pct")
        name = info.get("strategy_name", sid)

        is_active = sid == self.active_strategy_id
        paper_ann: Optional[float] = None
        if is_active:
            paper = self.load_paper_track()
            if paper.get("available"):
                paper_ann = paper.get("annualized_pct")

        alpha_bt = (
            round(bt_ann - self.benchmark_apy, 4) if bt_ann is not None else None
        )
        alpha_paper = (
            round(paper_ann - self.benchmark_apy, 4) if paper_ann is not None else None
        )

        return {
            "strategy_id": sid,
            "strategy_name": name,
            "risk_tier": info.get("risk_tier", ""),
            "backtest_annualized": bt_ann,
            "backtest_source": info.get("source"),
            "paper_annualized": paper_ann,
            "benchmark_aave": round(self.benchmark_apy, 4),
            "alpha_vs_aave_backtest": alpha_bt,
            "alpha_vs_aave_paper": alpha_paper,
            "is_active": is_active,
            "verdict": self._verdict(sid, alpha_bt, alpha_paper, is_active),
        }

    @staticmethod
    def _verdict(
        sid: str,
        alpha_bt: Optional[float],
        alpha_paper: Optional[float],
        is_active: bool,
    ) -> str:
        """Human-readable one-liner."""
        if alpha_bt is None:
            return f"{sid} has no backtest data"

        def phrase(alpha: float, label: str) -> str:
            if alpha > 0.05:
                return f"beats Aave by {alpha:.2f}% on {label}"
            if alpha < -0.05:
                return f"lags Aave by {abs(alpha):.2f}% on {label}"
            return f"matches Aave on {label}"

        msg = f"{sid} {phrase(alpha_bt, 'backtest')}"
        if is_active and alpha_paper is not None:
            msg += f"; {phrase(alpha_paper, 'paper')}"
        return msg

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """All strategies ranked by backtest alpha vs lazy Aave (best first)."""
        backtest = self.load_backtest()
        rows = [self.get_comparison(sid) for sid in backtest]
        rows.sort(
            key=lambda r: (
                r["alpha_vs_aave_backtest"]
                if r["alpha_vs_aave_backtest"] is not None
                else float("-inf")
            ),
            reverse=True,
        )
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
        return rows

    def get_active_strategy_vs_benchmark(self) -> Dict[str, Any]:
        """Live comparison: paper track vs lazy Aave over the same window."""
        paper = self.load_paper_track()
        sid = self.active_strategy_id
        bench_apy = self.benchmark_apy

        if not paper.get("available"):
            return {
                "active_strategy_id": sid,
                "available": False,
                "benchmark_aave": round(bench_apy, 4),
                "verdict": f"{sid}: no live paper track yet",
            }

        span_days = paper.get("span_days", max(1, paper["num_days"] - 1))
        start_equity = paper["start_equity"]
        end_equity = paper["end_equity"]

        # Benchmark accrues the lazy-Aave APY over the same elapsed window.
        bench_daily_frac = bench_apy / 100.0 / _DAYS_PER_YEAR
        lazy_aave_value = start_equity * (1.0 + bench_daily_frac) ** span_days
        bench_return_pct = (lazy_aave_value / start_equity - 1.0) * 100.0

        paper_return_pct = paper["total_return_pct"]
        cumulative_alpha_pct = round(paper_return_pct - bench_return_pct, 4)
        alpha_usd = round(end_equity - lazy_aave_value, 2)
        alpha_annualized = round((paper["annualized_pct"] or 0.0) - bench_apy, 4)

        return {
            "active_strategy_id": sid,
            "available": True,
            "track_days": paper["num_days"],
            "span_days": span_days,
            "track_start": paper["start_date"],
            "track_end": paper["end_date"],
            "paper_annualized": paper["annualized_pct"],
            "paper_current_apy": paper["current_apy_pct"],
            "benchmark_aave": round(bench_apy, 4),
            "alpha_vs_aave_annualized": alpha_annualized,
            "cumulative_paper_return_pct": round(paper_return_pct, 4),
            "cumulative_benchmark_return_pct": round(bench_return_pct, 4),
            "cumulative_alpha_pct": cumulative_alpha_pct,
            "spa_value_usd": round(end_equity, 2),
            "lazy_aave_value_usd": round(lazy_aave_value, 2),
            "alpha_usd": alpha_usd,
            "verdict": (
                f"{sid} {'beats' if alpha_annualized >= 0 else 'lags'} lazy Aave by "
                f"{abs(alpha_annualized):.2f}%/yr "
                f"(${alpha_usd:+,.2f} over {paper['num_days']} live days)"
            ),
        }

    # -----------------------------------------------------------------------
    # Snapshot / persistence
    # -----------------------------------------------------------------------

    def build_snapshot(self) -> Dict[str, Any]:
        """Full advisory snapshot: leaderboard + active comparison + meta."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "strategy_benchmark_tracker",
            "mp": "MP-1252",
            "benchmark_aave_apy": round(self.benchmark_apy, 4),
            "active_strategy_id": self.active_strategy_id,
            "backtest_source": (
                _REAL_FILE if self.use_real else _SYNTHETIC_FILE
            ),
            "leaderboard": self.get_leaderboard(),
            "active_vs_benchmark": self.get_active_strategy_vs_benchmark(),
        }

    def save_snapshot(self, output_path: Optional[str] = None) -> str:
        """Atomically write the snapshot to ``data/strategy_benchmark.json``."""
        if output_path is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.data_dir / OUTPUT_FILENAME
        else:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(self.build_snapshot(), str(out_path))
        return str(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Strategy Benchmark Tracker (MP-1252) — backtest/paper/lazy-Aave."
    )
    parser.add_argument("--check", action="store_true", default=True,
                        help="Compute and print without writing (default).")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically save to data/strategy_benchmark.json.")
    parser.add_argument("--real", action="store_true",
                        help="Use the real 365-day backtest instead of synthetic 90-day.")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR),
                        help="Data directory path.")
    parser.add_argument("--active", default=DEFAULT_ACTIVE_STRATEGY,
                        help="Active (live) strategy id. Default S0.")
    args = parser.parse_args(argv)

    tracker = StrategyBenchmarkTracker(
        data_dir=args.data_dir, use_real=args.real, active_strategy_id=args.active
    )

    print("=== Strategy Benchmark Tracker (MP-1252) ===")
    print(f"Backtest source: {'real 365d' if args.real else 'synthetic 90d'}"
          f"   |   Lazy-Aave benchmark: {tracker.benchmark_apy:.2f}%")
    print("")
    print(f"{'Rank':<5}{'ID':<5}{'Strategy':<34}{'Backtest':>9}{'Alpha':>9}{'Paper':>9}")
    print("-" * 71)
    for r in tracker.get_leaderboard():
        bt = f"{r['backtest_annualized']:.2f}%" if r["backtest_annualized"] is not None else "  n/a"
        al = f"{r['alpha_vs_aave_backtest']:+.2f}%" if r["alpha_vs_aave_backtest"] is not None else "  n/a"
        pp = f"{r['paper_annualized']:.2f}%" if r["paper_annualized"] is not None else "   —"
        flag = " ●" if r["is_active"] else ""
        print(f"{r['rank']:<5}{r['strategy_id']:<5}{r['strategy_name'][:32]:<34}"
              f"{bt:>9}{al:>9}{pp:>9}{flag}")

    print("")
    avb = tracker.get_active_strategy_vs_benchmark()
    if avb.get("available"):
        print(f"--- Active strategy {avb['active_strategy_id']} vs lazy Aave (live) ---")
        print(f"  Track:        {avb['track_start']} → {avb['track_end']} "
              f"({avb['track_days']} days)")
        print(f"  Paper APY:    {avb['paper_annualized']:.2f}%  "
              f"(current {avb['paper_current_apy']:.2f}%)")
        print(f"  Lazy Aave:    {avb['benchmark_aave']:.2f}%")
        print(f"  Alpha:        {avb['alpha_vs_aave_annualized']:+.2f}%/yr")
        print(f"  Cumulative:   SPA {avb['cumulative_paper_return_pct']:+.4f}%  vs  "
              f"Aave {avb['cumulative_benchmark_return_pct']:+.4f}%  "
              f"→ alpha {avb['cumulative_alpha_pct']:+.4f}%")
        print(f"  Value:        SPA ${avb['spa_value_usd']:,.2f}  vs  "
              f"lazy Aave ${avb['lazy_aave_value_usd']:,.2f}  "
              f"→ ${avb['alpha_usd']:+,.2f}")
        print(f"  Verdict:      {avb['verdict']}")
    else:
        print(f"--- {avb['verdict']} ---")

    if args.run:
        path = tracker.save_snapshot()
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
