"""
spa_core.strategies.comparator — aggregate & rank shadow-strategy portfolios.

Reads every ``data/strategies/{name}.json`` portfolio, computes per-strategy
performance metrics (PnL, Sharpe, Sortino, max drawdown, best/worst day) and
ranks them by Sortino (the primary metric — it penalises downside volatility
only). Writes a leaderboard to ``data/strategy_shadow_comparison.json``.

Note on the output path: the sprint spec named ``data/strategy_comparison.json``,
but that file is already an *export-pipeline-owned* artifact (the legacy
v1_passive/v2_aggressive dashboard comparison, a different schema). Following the
project's v3.79 precedent (orchestrator wrote ``adapter_orchestrator_status.json``
rather than clobber the execution-owned ``adapter_status.json``), the shadow
framework writes to a distinct file so it cannot break the existing dashboard.

CLI::
    python3 -m spa_core.strategies.comparator [--verbose]

Stdlib only. Read-only/advisory.
"""
from __future__ import annotations

import argparse
import json
import sys
from math import sqrt
from pathlib import Path
from spa_core.utils.atomic import atomic_save

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data" / "strategies"
_OUTPUT = _PROJECT_ROOT / "data" / "strategy_shadow_comparison.json"

# Files in data/strategies/ that are NOT portfolios.
_NON_PORTFOLIO = {"run_log.json"}

# Trading-days-per-year used to annualise Sharpe/Sortino. Each step is one day.
_ANNUALISATION = 365

#: Minimum equity-curve points before a Sharpe ratio is reported (else null).
MIN_POINTS_FOR_SHARPE = 5

#: Human-readable labels, keyed by strategy name (kept in sync with the modules).
_LABELS = {
    "s0_baseline": "Baseline (Equal Weight)",
    "s1_concentration": "Concentration",
    "s2_momentum": "APY Momentum",
    "s3_risk_parity": "Risk Parity+",
    "s4_kelly": "Half-Kelly",
    "s5_yield_spread": "Yield Spread",
}


def _load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
def _returns(equity_curve: list[dict]) -> list[float]:
    """Per-step fractional returns from an equity curve."""
    rets: list[float] = []
    prev = None
    for pt in equity_curve or []:
        eq = pt.get("equity") if isinstance(pt, dict) else None
        if eq is None:
            continue
        eq = float(eq)
        if prev is not None and prev > 0:
            rets.append(eq / prev - 1.0)
        prev = eq
    return rets


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sqrt(sum((v - mean) ** 2 for v in values) / n)


def _sharpe(rets: list[float]) -> float | None:
    if len(rets) < 2:
        return None
    sd = _std(rets)
    if sd <= 0:
        return 0.0
    mean = sum(rets) / len(rets)
    return (mean / sd) * sqrt(_ANNUALISATION)


def _sortino(rets: list[float]) -> float | None:
    """Sortino ratio — downside-deviation only (the primary ranking metric)."""
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        # No downside observed: positive mean -> strongly favourable, else flat.
        return float("inf") if mean > 0 else 0.0
    dd = sqrt(sum(r * r for r in downside) / len(rets))
    if dd <= 0:
        return 0.0
    return (mean / dd) * sqrt(_ANNUALISATION)


def _max_drawdown(equity_curve: list[dict]) -> float:
    """Largest peak-to-trough decline as a positive fraction (0.05 = 5%)."""
    peak = None
    max_dd = 0.0
    for pt in equity_curve or []:
        eq = pt.get("equity") if isinstance(pt, dict) else None
        if eq is None:
            continue
        eq = float(eq)
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _portfolio_paths() -> list[Path]:
    if not _DATA_DIR.exists():
        return []
    return sorted(
        p for p in _DATA_DIR.glob("*.json") if p.name not in _NON_PORTFOLIO
    )


def build_comparison(now_iso: str | None = None) -> dict:
    """Build the leaderboard dict from all persisted shadow portfolios."""
    rows: list[dict] = []
    max_days = 0
    for path in _portfolio_paths():
        data = _load_json(path)
        if not data:
            continue
        name = data.get("name") or path.stem
        initial = float(data.get("initial_capital", 100_000.0)) or 100_000.0
        equity = float(data.get("equity", initial))
        curve = data.get("equity_curve") or []
        rets = _returns(curve)
        days = len(curve)
        max_days = max(max_days, days)

        sharpe = _sharpe(rets) if days >= MIN_POINTS_FOR_SHARPE else None
        sortino = _sortino(rets)
        rows.append(
            {
                "name": name,
                "label": _LABELS.get(name, name),
                "equity": round(equity, 2),
                "pnl_pct": round((equity / initial - 1.0) * 100.0, 6),
                "days_running": days,
                "sharpe": _clean(sharpe),
                "sortino": _clean(sortino),
                "max_drawdown": round(_max_drawdown(curve), 6),
                "best_day_pct": round(max(rets) * 100.0, 6) if rets else None,
                "worst_day_pct": round(min(rets) * 100.0, 6) if rets else None,
            }
        )

    # Rank by Sortino, descending. None sorts last; +inf (no downside) sorts top.
    def _sort_key(r):
        s = r["sortino"]
        if s is None:
            return (0, 0.0)
        if s == float("inf"):
            return (2, 0.0)
        return (1, s)

    rows.sort(key=_sort_key, reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["rank_by_sortino"] = i

    return {
        "updated_at": now_iso,
        "strategies": rows,
        "best_strategy": rows[0]["name"] if rows else None,
        "days_running": max_days,
    }


def _clean(value):
    """Serialise +inf Sortino as a large sentinel; None stays null."""
    if value is None:
        return None
    if value == float("inf"):
        return 999.0
    if value == float("-inf"):
        return -999.0
    return round(value, 6)


def write_comparison(now_iso: str | None = None, output: Path = _OUTPUT) -> dict:
    doc = build_comparison(now_iso)
    _atomic_write(output, doc)
    return doc


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank shadow strategies by Sortino.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    doc = write_comparison(_now_iso())
    rows = doc["strategies"]
    print(
        f"COMPARISON {len(rows)} strategies | best={doc['best_strategy']} | "
        f"days={doc['days_running']}"
    )
    if args.verbose:
        for r in rows:
            srt = "n/a" if r["sortino"] is None else f"{r['sortino']:.3f}"
            shp = "n/a" if r["sharpe"] is None else f"{r['sharpe']:.3f}"
            print(
                f"  #{r['rank']} {r['label']:24s} equity=${r['equity']:>12,.2f}  "
                f"pnl={r['pnl_pct']:+.4f}%  sortino={srt}  sharpe={shp}  "
                f"maxDD={r['max_drawdown']*100:.3f}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
