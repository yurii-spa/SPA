"""
spa_core.strategies.backtester — historical pre-screening for shadow strategies.

Sprint C / v3.91 — "Backtest Contour".

Before a candidate allocation policy is allowed into the live shadow-paper
fan-out (the v3.90 runner), it is replayed here against a sequence of historical
orchestrator snapshots. Every strategy is graded on *honest* metrics (Sortino +
bootstrap Sharpe CI from :mod:`spa_core.analytics.honest_metrics`) and given a
binary ``passed_screening`` verdict.

A snapshot is a compact historical record::

    {"ts": float, "adapters": {pool_id: {"apy": float, "tvl": float, ...}}}

which this module normalises to the orchestrator status shape the existing
strategies + :class:`VirtualPortfolio` already understand, so no strategy code
has to change.

Stdlib only (``random`` for synthetic history). Advisory/read-only: nothing here
imports execution, feed_health or the deterministic risk agents.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..analytics.honest_metrics import compute_sortino, compute_sharpe_with_ci
from .base import apply_risk_policy, tier_map
from .vportfolio import VirtualPortfolio

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"
_SCREENING_OUT = _DATA_DIR / "strategy_screening.json"

#: Default base APYs for synthetic history (percent). All Tier-2 protocols.
SYNTHETIC_BASE_APY = {
    "morpho_blue": 8.3,
    "yearn_v3": 7.2,
    "euler_v2": 9.1,
    "maple": 10.5,
}

#: Synthetic random-walk parameters.
SYNTHETIC_DRIFT = 0.5   # +/- max APY move per step (percentage points)
SYNTHETIC_APY_MIN = 1.0
SYNTHETIC_APY_MAX = 25.0

#: A strategy with fewer than this many usable data points cannot be *rejected*
#: on performance — there simply is not enough evidence.
SCREENING_MIN_POINTS = 5


@dataclass
class BacktestResult:
    """Outcome of replaying one strategy over a historical snapshot series."""

    strategy_name: str
    equity_curve: list = field(default_factory=list)  # [{ts, equity, pnl_pct}, ...]
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    sortino: dict = field(default_factory=dict)
    sharpe_with_ci: dict = field(default_factory=dict)
    max_drawdown_pct: float = 0.0
    n_rebalances: int = 0
    passed_screening: bool = False
    screening_notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_snapshot(snap: dict) -> dict:
    """Convert a compact historical snapshot to orchestrator-status shape.

    Input::  {"ts": float, "adapters": {pool_id: {"apy": .., "tvl": ..}}}
    Output:: {"run_ts": ts, "adapters": [{"protocol", "apy_pct", "tvl_usd",
              "status", "tier", "health_score"}, ...]}

    Tiers are not carried in the compact form, so every pool defaults to ``T2``
    (the stricter concentration cap) — matching the convention in ``base.py``.
    Snapshots already in orchestrator shape (``adapters`` is a list) pass through
    unchanged.
    """
    adapters = (snap or {}).get("adapters")
    if isinstance(adapters, list):
        return snap  # already orchestrator-shaped
    out_adapters = []
    for pool_id, fields in (adapters or {}).items():
        fields = fields if isinstance(fields, dict) else {}
        apy = fields.get("apy", fields.get("apy_pct"))
        try:
            apy = float(apy)
        except (TypeError, ValueError):
            continue
        out_adapters.append(
            {
                "protocol": str(pool_id),
                "apy_pct": apy,
                "tvl_usd": float(fields.get("tvl", fields.get("tvl_usd", 0.0)) or 0.0),
                "status": str(fields.get("status", "ok")),
                "tier": str(fields.get("tier", "T2")).upper(),
                "health_score": float(fields.get("health_score", 1.0) or 0.0),
            }
        )
    return {"run_ts": snap.get("ts"), "adapters": out_adapters}


def _returns_from_curve(equity_curve: list) -> list[float]:
    """Step-over-step fractional returns from an equity curve of dicts."""
    rets: list[float] = []
    prev = None
    for pt in equity_curve:
        eq = pt.get("equity") if isinstance(pt, dict) else pt
        try:
            eq = float(eq)
        except (TypeError, ValueError):
            continue
        if prev is not None and prev > 0:
            rets.append(eq / prev - 1.0)
        prev = eq
    return rets


def _max_drawdown_pct(equity_curve: list) -> float:
    peak = None
    max_dd = 0.0
    for pt in equity_curve:
        eq = pt.get("equity") if isinstance(pt, dict) else pt
        try:
            eq = float(eq)
        except (TypeError, ValueError):
            continue
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd * 100.0


class StrategyBacktester:
    """Replay a strategy over historical snapshots and grade it honestly."""

    def __init__(self, capital: float = 100_000.0):
        self.capital = float(capital)

    def run(self, strategy, historical_snapshots: list) -> BacktestResult:
        """Replay ``strategy`` across ``historical_snapshots`` (chronological).

        Each snapshot advances an ephemeral :class:`VirtualPortfolio` one step:
        raw target weights -> uniform risk guard -> yield accrual + rebalance.
        The resulting equity curve is graded with the honest metrics and a
        ``passed_screening`` verdict is attached.
        """
        name = getattr(strategy, "name", strategy.__class__.__name__)
        vp = VirtualPortfolio(name=name, capital=self.capital)

        equity_curve: list = []
        n_rebalances = 0
        history: list = []

        for raw_snap in historical_snapshots or []:
            snap = _normalize_snapshot(raw_snap)
            ts = snap.get("run_ts") or raw_snap.get("ts")
            caps = tier_map(snap)
            state = {"history": list(history)}

            raw_weights = strategy.target_weights(snap, state)
            weights = apply_risk_policy(raw_weights, caps)
            if weights:
                n_rebalances += 1

            vp.step(snap, weights, ts)
            equity_curve.append(
                {
                    "ts": ts,
                    "equity": round(vp.equity, 6),
                    "pnl_pct": round((vp.equity / self.capital - 1.0) * 100.0, 6),
                }
            )
            # Feed this snapshot into history so momentum/risk-parity strategies
            # see a growing per-pool APY series, mirroring the live runner.
            history.append({"run_ts": ts, "adapters": snap.get("adapters", [])})

        rets = _returns_from_curve(equity_curve)
        sortino = compute_sortino(rets)
        sharpe = compute_sharpe_with_ci(rets)
        final_equity = equity_curve[-1]["equity"] if equity_curve else self.capital
        total_return_pct = (final_equity / self.capital - 1.0) * 100.0

        passed, notes = self._screen(sortino, len(equity_curve))

        return BacktestResult(
            strategy_name=name,
            equity_curve=equity_curve,
            final_equity=round(final_equity, 6),
            total_return_pct=round(total_return_pct, 6),
            sortino=sortino,
            sharpe_with_ci=sharpe,
            max_drawdown_pct=round(_max_drawdown_pct(equity_curve), 6),
            n_rebalances=n_rebalances,
            passed_screening=passed,
            screening_notes=notes,
        )

    @staticmethod
    def _screen(sortino: dict, n_points: int) -> tuple[bool, list]:
        """Pass if Sortino is positive, or if there is too little data to reject."""
        notes: list = []
        sval = sortino.get("value")

        if n_points < SCREENING_MIN_POINTS:
            notes.append(
                f"only {n_points} data points (<{SCREENING_MIN_POINTS}) — "
                f"insufficient evidence to reject; passed by default"
            )
            return True, notes

        if sval is None:
            notes.append(
                "Sortino is undefined (no downside observed) — treated as "
                "non-negative; passed"
            )
            return True, notes

        if sval > 0:
            notes.append(f"Sortino {sval:.3f} > 0 — passed")
            return True, notes

        notes.append(f"Sortino {sval:.3f} <= 0 — rejected")
        return False, notes


def generate_synthetic_history(n_steps: int = 30, pools: dict | None = None) -> list:
    """Generate ``n_steps`` synthetic snapshots via a bounded APY random walk.

    Each step every pool's APY drifts by up to ±:data:`SYNTHETIC_DRIFT` pp and is
    clamped to ``[SYNTHETIC_APY_MIN, SYNTHETIC_APY_MAX]``. ``random.seed(42)`` is
    set internally for reproducibility. Returns snapshots in the compact form::

        {"ts": float, "adapters": {pool_id: {"apy": float, "tvl": float}}}
    """
    base = dict(pools or SYNTHETIC_BASE_APY)
    random.seed(42)

    current = dict(base)
    snapshots: list = []
    base_ts = 1_700_000_000.0  # fixed epoch start; ts is only a label
    for i in range(int(n_steps)):
        ts = base_ts + i * 86_400.0  # one day per step
        adapters: dict = {}
        for pool_id, apy in current.items():
            drift = random.uniform(-SYNTHETIC_DRIFT, SYNTHETIC_DRIFT)
            apy = max(SYNTHETIC_APY_MIN, min(SYNTHETIC_APY_MAX, apy + drift))
            current[pool_id] = apy
            adapters[pool_id] = {
                "apy": round(apy, 4),
                "tvl": 50_000_000.0,
                "tier": "T2",
                "status": "ok",
            }
        snapshots.append({"ts": ts, "adapters": adapters})
    return snapshots


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_strategy_screening(n_steps: int = 30, write: bool = True) -> dict:
    """Backtest every registered shadow strategy on synthetic history.

    Returns a comparison document and (by default) writes it atomically to
    ``data/strategy_screening.json``::

        {
          "n_steps": int,
          "strategies": {
            name: {sortino, total_return_pct, max_drawdown_pct, passed_screening},
            ...
          },
          "passed": int, "failed": int
        }
    """
    from . import STRATEGY_REGISTRY  # lazy: avoid hard import-time dependency

    history = generate_synthetic_history(n_steps=n_steps)
    bt = StrategyBacktester()

    table: dict = {}
    passed = 0
    for strat in STRATEGY_REGISTRY:
        res = bt.run(strat, history)
        table[res.strategy_name] = {
            "label": getattr(strat, "label", res.strategy_name),
            "risk_level": getattr(strat, "risk_level", "unknown"),
            "sortino": res.sortino,
            "sharpe_with_ci": res.sharpe_with_ci,
            "total_return_pct": res.total_return_pct,
            "max_drawdown_pct": res.max_drawdown_pct,
            "final_equity": res.final_equity,
            "n_rebalances": res.n_rebalances,
            "passed_screening": res.passed_screening,
            "screening_notes": res.screening_notes,
        }
        if res.passed_screening:
            passed += 1

    doc = {
        "schema_version": "1.0",
        "sprint": "v3.91",
        "n_steps": n_steps,
        "n_strategies": len(table),
        "passed": passed,
        "failed": len(table) - passed,
        "strategies": table,
    }
    if write:
        _atomic_write(_SCREENING_OUT, doc)
    return doc


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest-screen all shadow strategies.")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    doc = run_strategy_screening(n_steps=args.steps, write=not args.no_write)
    print(
        f"SCREENING {doc['n_strategies']} strategies | "
        f"{doc['passed']} passed | {doc['failed']} failed | {doc['n_steps']} steps"
    )
    if args.verbose:
        for name, r in doc["strategies"].items():
            sval = r["sortino"].get("value")
            sstr = f"{sval:+.3f}" if isinstance(sval, (int, float)) else "  N/A"
            flag = "PASS" if r["passed_screening"] else "FAIL"
            print(
                f"  {name:18s} sortino={sstr}  ret={r['total_return_pct']:+7.3f}%  "
                f"maxDD={r['max_drawdown_pct']:5.2f}%  [{flag}]"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
