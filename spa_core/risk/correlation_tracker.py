"""
spa_core/risk/correlation_tracker.py

Correlation analytics for the SPA portfolio — v2.

Tracks three families of correlations using the real daily history in
``data/equity_curve_daily.json`` (and ``data/pnl_history.json`` when present):

  1. Protocol co-movement — an N×N Pearson matrix across per-protocol daily
     value-return series (do Aave and Compound move together?).
  2. Strategy vs benchmark — portfolio daily returns correlated against an
     ETH-staking benchmark (~3.5% APY), plus tracking beta / excess return.
  3. APY vs market conditions — blended portfolio APY series correlated with
     the portfolio's own daily return series (a market-condition proxy).

Output: ``data/correlation_matrix.json`` (atomic write). Every reported
coefficient is clamped to the valid Pearson range [-1, 1].

Constraints: stdlib only, atomic writes, deterministic, LLM FORBIDDEN.

CLI:
    python3 -m spa_core.risk.correlation_tracker --check
    python3 -m spa_core.risk.correlation_tracker --run
    python3 -m spa_core.risk.correlation_tracker --run --data-dir data
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Optional

__all__ = ["CorrelationTracker", "pearson", "BENCHMARK_APY"]

BENCHMARK_APY = 0.035            # ETH staking ~3.5% annual
TRADING_DAYS_YEAR = 365
HIGH_CORR_THRESHOLD = 0.80       # flag |r| > 0.8 clusters


def pearson(xs: list, ys: list) -> Optional[float]:
    """
    Pearson correlation coefficient, clamped to [-1, 1].

    Returns None when undefined (fewer than 2 paired points, or either
    series has zero variance).
    """
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs = xs[:n]
    ys = ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0.0 or vy <= 0.0:
        return None
    r = cov / math.sqrt(vx * vy)
    return max(-1.0, min(1.0, r))


def _atomic_write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


def _to_returns(series: list) -> list:
    """Convert a value series to fractional period-over-period returns."""
    out = []
    for i in range(1, len(series)):
        prev = series[i - 1]
        if prev:
            out.append((series[i] - prev) / prev)
    return out


class CorrelationTracker:
    """
    Builds correlation analytics from per-protocol value series and the
    portfolio return / APY series.
    """

    def __init__(self, protocol_series: dict, portfolio_returns: list,
                 apy_series: list) -> None:
        # protocol_series: {protocol: [daily usd value, ...]} (aligned by day)
        self.protocol_series = protocol_series or {}
        self.portfolio_returns = list(portfolio_returns or [])
        self.apy_series = list(apy_series or [])

    @classmethod
    def from_data(cls, data_dir: str = "data") -> "CorrelationTracker":
        protocol_series, portfolio_returns, apy_series = _load_history(data_dir)
        return cls(protocol_series, portfolio_returns, apy_series)

    # -- 1. protocol co-movement matrix ---------------------------------------

    def protocol_matrix(self) -> dict:
        """
        N×N Pearson matrix across per-protocol daily return series.

        Returns {"protocols": [...], "matrix": {p: {q: r|None}}, "clusters": [...]}.
        """
        returns = {
            p: _to_returns(s)
            for p, s in self.protocol_series.items()
            if len(s) >= 3
        }
        protocols = sorted(returns.keys())
        matrix: dict = {}
        clusters = []
        for p in protocols:
            matrix[p] = {}
            for q in protocols:
                if p == q:
                    matrix[p][q] = 1.0
                    continue
                r = pearson(returns[p], returns[q])
                matrix[p][q] = round(r, 6) if r is not None else None
                if r is not None and p < q and abs(r) > HIGH_CORR_THRESHOLD:
                    clusters.append({"pair": [p, q], "r": round(r, 6)})
        return {"protocols": protocols, "matrix": matrix, "clusters": clusters}

    # -- 2. strategy vs benchmark ---------------------------------------------

    def strategy_vs_benchmark(self) -> dict:
        """
        Portfolio returns vs a flat ETH-staking benchmark daily return.

        The benchmark is a constant daily return, so Pearson correlation is
        undefined (zero variance) — reported as None — and we instead surface
        the economically meaningful excess return and ratio.
        """
        bench_daily = BENCHMARK_APY / TRADING_DAYS_YEAR
        bench_series = [bench_daily] * len(self.portfolio_returns)
        r = pearson(self.portfolio_returns, bench_series)  # None: bench is flat
        mean_port = (sum(self.portfolio_returns) / len(self.portfolio_returns)
                     if self.portfolio_returns else 0.0)
        excess_daily = mean_port - bench_daily
        return {
            "benchmark": "ETH staking ~3.5% APY",
            "benchmark_daily_return": round(bench_daily, 8),
            "portfolio_mean_daily_return": round(mean_port, 8),
            "correlation": (round(r, 6) if r is not None else None),
            "correlation_note": (
                "undefined — benchmark is a constant (zero variance)"
                if r is None else ""
            ),
            "excess_daily_return": round(excess_daily, 8),
            "excess_apy_pct": round(excess_daily * TRADING_DAYS_YEAR * 100, 4),
            "outperforms_benchmark": excess_daily > 0,
        }

    # -- 3. apy vs market conditions ------------------------------------------

    def apy_vs_market(self) -> dict:
        """
        Blended-APY series correlated with portfolio daily returns (a proxy
        for prevailing market conditions).
        """
        apy_changes = _to_returns(self.apy_series) if len(self.apy_series) >= 3 else []
        # Align lengths from the tail (both are day-over-day deltas).
        n = min(len(apy_changes), len(self.portfolio_returns))
        r = pearson(apy_changes[-n:], self.portfolio_returns[-n:]) if n >= 2 else None
        return {
            "n_points": n,
            "correlation": (round(r, 6) if r is not None else None),
            "correlation_note": (
                "" if r is not None else "insufficient or constant data"
            ),
        }

    # -- aggregate -------------------------------------------------------------

    def analyze(self) -> dict:
        proto = self.protocol_matrix()
        return {
            "module": "correlation_tracker_v2",
            "is_demo": False,
            "num_protocols": len(proto["protocols"]),
            "num_return_points": len(self.portfolio_returns),
            "protocol_correlations": proto,
            "strategy_vs_benchmark": self.strategy_vs_benchmark(),
            "apy_vs_market": self.apy_vs_market(),
            "high_correlation_clusters": proto["clusters"],
        }


# ─── Data loading ────────────────────────────────────────────────────────────

def _load_history(data_dir: str) -> tuple:
    """
    Returns (protocol_series, portfolio_returns, apy_series).

    protocol_series: {protocol: [usd value per day]} reconstructed from the
    equity curve's per-day ``positions`` maps. Only protocols present on every
    day are kept so the series stay aligned. pnl_history.json is consulted as
    an optional source but is not required.
    """
    path = os.path.join(data_dir, "equity_curve_daily.json")
    if not os.path.exists(path):
        return {}, [], []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return {}, [], []

    daily = doc.get("daily", []) if isinstance(doc, dict) else doc
    if not isinstance(daily, list) or len(daily) < 2:
        return {}, [], []

    # Portfolio return series (fractional) from close_equity.
    equities = []
    apy_series = []
    per_day_positions = []
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        val = entry.get("close_equity", entry.get("equity", entry.get("nav")))
        if isinstance(val, (int, float)):
            equities.append(float(val))
        if isinstance(entry.get("apy_today"), (int, float)):
            apy_series.append(float(entry["apy_today"]))
        if isinstance(entry.get("positions"), dict):
            per_day_positions.append(entry["positions"])

    portfolio_returns = _to_returns(equities)

    # Protocols present on every day → aligned value series.
    protocol_series: dict = {}
    if per_day_positions:
        common = set(per_day_positions[0].keys())
        for pos in per_day_positions[1:]:
            common &= set(pos.keys())
        for proto in common:
            protocol_series[proto] = [
                float(pos.get(proto, 0.0)) for pos in per_day_positions
            ]

    # Optional: merge any explicit pnl_history.json protocol series if present.
    pnl_path = os.path.join(data_dir, "pnl_history.json")
    if os.path.exists(pnl_path):
        try:
            with open(pnl_path, "r", encoding="utf-8") as fh:
                pnl_doc = json.load(fh)
            extra = pnl_doc.get("protocol_series") if isinstance(pnl_doc, dict) else None
            if isinstance(extra, dict):
                for proto, series in extra.items():
                    if isinstance(series, list) and len(series) >= 3:
                        protocol_series[proto] = [float(x) for x in series]
        except Exception:
            pass

    return protocol_series, portfolio_returns, apy_series


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run_mode = "--run" in args
    data_dir = "data"
    for i, a in enumerate(args):
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    tracker = CorrelationTracker.from_data(data_dir)
    result = tracker.analyze()

    print(f"[correlation_tracker] {result['num_protocols']} protocols, "
          f"{result['num_return_points']} return points")
    svb = result["strategy_vs_benchmark"]
    print(f"  vs benchmark: excess APY {svb['excess_apy_pct']:.3f}% "
          f"(outperforms={svb['outperforms_benchmark']})")
    clusters = result["high_correlation_clusters"]
    if clusters:
        print(f"  high-correlation (|r|>{HIGH_CORR_THRESHOLD}) pairs:")
        for c in clusters[:10]:
            print(f"    {c['pair'][0]} ~ {c['pair'][1]}: r={c['r']}")
    else:
        print(f"  no |r|>{HIGH_CORR_THRESHOLD} protocol clusters")

    if run_mode:
        out = os.path.join(data_dir, "correlation_matrix.json")
        _atomic_write_json(out, result)
        print(f"[correlation_tracker] saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
