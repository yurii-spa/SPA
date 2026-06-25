"""performance_report.py — генератор tear sheet данных из equity curve.

Read-only/advisory. Пишет data/tear_sheet.json.

Metrics:
  - Total return %
  - Annualized APY (compound)
  - Max drawdown %
  - Track length (days) / N observations
  - Sharpe ratio  (requires n >= 30, else null)
  - Sortino ratio (requires n >= 30, else null)
  - Calmar ratio  (requires n >= 365, else null)
  - vs_benchmark  (Aave V3 USDC APY from adapter_status.json)

CLI:
  python3 -m spa_core.paper_trading.performance_report --check   # compute + print (default)
  python3 -m spa_core.paper_trading.performance_report --run     # compute + atomic write + print
  python3 -m spa_core.paper_trading.performance_report --run --data-dir <dir>

Exit 0 always. Pure stdlib. Advisory only.
"""

import argparse
import json
import math
import os
import sys
from datetime import date, datetime
from spa_core.utils.atomic import atomic_save


# ─── Data loaders ─────────────────────────────────────────────────────────────

def load_equity_curve(data_dir: str) -> dict:
    """Load equity_curve_daily.json from data_dir."""
    path = os.path.join(data_dir, "equity_curve_daily.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_benchmark_apy(data_dir: str) -> float | None:
    """Read Aave V3 USDC APY from adapter_status.json.

    Returns the mock APY (float, %) or None if unavailable.
    """
    path = os.path.join(data_dir, "adapter_status.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for adapter in data.get("adapters", []):
            if adapter.get("protocol_key") == "aave-v3":
                mock = adapter.get("mock_apy", {})
                eth = mock.get("ethereum", {})
                val = eth.get("USDC")
                if val is not None:
                    return float(val)
    except Exception:
        pass
    return None


# ─── Statistical helpers ───────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    """Sample standard deviation (ddof=1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    variance = sum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def compute_max_drawdown(daily: list[dict]) -> float:
    """Return maximum peak-to-trough drawdown in percent.

    Uses close_equity (falling back to equity) for each entry.
    """
    if not daily:
        return 0.0

    def _eq(entry: dict) -> float:
        return float(entry.get("close_equity", entry.get("equity", 0.0)))

    peak = _eq(daily[0])
    max_dd = 0.0
    for entry in daily:
        eq = _eq(entry)
        if eq > peak:
            peak = eq
        if peak > 0.0:
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def compute_sharpe(returns: list[float], min_obs: int = 30) -> float | None:
    """Annualised Sharpe ratio (risk-free = 0).

    Returns None if len(returns) < min_obs.
    Daily returns expected as percentage points (e.g. 0.0087 for 0.0087%).

    Zero-volatility edge case: a constant non-zero return has no risk, so the
    Sharpe diverges — we return +/-inf with the sign of the mean. Only a series
    that is also zero-mean (e.g. all 0.0) is genuinely undefined → None.
    """
    if len(returns) < min_obs:
        return None
    mu = _mean(returns)
    sigma = _std(returns)
    if sigma == 0.0:
        if mu > 0:
            return math.inf
        if mu < 0:
            return -math.inf
        return None
    return (mu / sigma) * math.sqrt(365.0)


def compute_sortino(returns: list[float], min_obs: int = 30) -> float | None:
    """Annualised Sortino ratio (risk-free = 0).

    Returns None if len(returns) < min_obs or no downside returns.
    """
    if len(returns) < min_obs:
        return None
    mu = _mean(returns)
    downside = [r for r in returns if r < 0.0]
    if not downside:
        return None
    # Downside deviation (not sample — use population mean of squared negatives)
    ds_variance = sum(r ** 2 for r in downside) / len(downside)
    ds_std = math.sqrt(ds_variance)
    if ds_std == 0.0:
        return None
    return (mu / ds_std) * math.sqrt(365.0)


def compute_calmar(annualized_apy_pct: float, max_drawdown_pct: float, min_obs: int = 365) -> float | None:
    """Calmar ratio = annualized return / max drawdown.

    Returns None if n_observations < min_obs or drawdown is 0.
    Note: caller must pass n_observations separately and check before calling,
    or this function receives it directly.
    """
    if max_drawdown_pct == 0.0:
        return None
    return annualized_apy_pct / max_drawdown_pct


# ─── Core computation ──────────────────────────────────────────────────────────

def compute_report(data_dir: str = "data") -> dict:
    """Compute all tear-sheet metrics. Returns dict (available=True|False)."""
    generated_at = datetime.utcnow().isoformat() + "+00:00"

    # Load equity curve
    try:
        curve = load_equity_curve(data_dir)
    except FileNotFoundError:
        return {
            "available": False,
            "error": "equity_curve_daily.json not found",
            "generated_at": generated_at,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "generated_at": generated_at,
        }

    daily = curve.get("daily", [])
    if not daily:
        return {
            "available": False,
            "error": "No daily entries in equity curve",
            "generated_at": generated_at,
        }

    # Equity boundaries
    first_entry = daily[0]
    last_entry = daily[-1]
    first_equity = float(first_entry.get("open_equity", first_entry.get("equity", 0.0)))
    last_equity = float(last_entry.get("close_equity", last_entry.get("equity", 0.0)))

    track_start = first_entry.get("date", "")
    track_end = last_entry.get("date", "")

    # Track days
    try:
        d1 = date.fromisoformat(track_start)
        d2 = date.fromisoformat(track_end)
        track_days = (d2 - d1).days + 1
    except Exception:
        track_days = len(daily)

    n_observations = len(daily)

    # Total return
    if first_equity > 0.0:
        total_return_pct = (last_equity - first_equity) / first_equity * 100.0
    else:
        total_return_pct = 0.0

    # Annualised APY (compound)
    if track_days > 0 and first_equity > 0.0:
        annualized_apy_pct = ((1.0 + total_return_pct / 100.0) ** (365.0 / track_days) - 1.0) * 100.0
    else:
        annualized_apy_pct = 0.0

    # Max drawdown
    max_drawdown_pct = compute_max_drawdown(daily)

    # Daily returns for Sharpe/Sortino: day-over-day % change from equity values
    equities = [float(e.get("close_equity", e.get("equity", 0.0))) for e in daily]
    daily_returns: list[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        if prev > 0.0:
            daily_returns.append((equities[i] - prev) / prev * 100.0)
        else:
            daily_returns.append(0.0)

    # Sharpe (need 30 observations = len(daily) >= 30)
    if n_observations < 30:
        sharpe_ratio = None
        sharpe_need_days = 30
    else:
        sharpe_ratio = compute_sharpe(daily_returns, min_obs=0)
        sharpe_need_days = None

    # Sortino
    if n_observations < 30:
        sortino_ratio = None
        sortino_need_days = 30
    else:
        sortino_ratio = compute_sortino(daily_returns, min_obs=0)
        sortino_need_days = None

    # Calmar (need 365 observations)
    if n_observations < 365:
        calmar_ratio = None
        calmar_need_days = 365
    else:
        calmar_ratio = compute_calmar(annualized_apy_pct, max_drawdown_pct)
        calmar_need_days = None

    # Benchmark
    benchmark_apy_pct = load_benchmark_apy(data_dir)
    if benchmark_apy_pct is not None:
        alpha_vs_benchmark_pct = annualized_apy_pct - benchmark_apy_pct
    else:
        alpha_vs_benchmark_pct = None

    return {
        "available": True,
        "generated_at": generated_at,
        "track_start": track_start,
        "track_end": track_end,
        "track_days": track_days,
        "total_return_pct": round(total_return_pct, 6),
        "annualized_apy_pct": round(annualized_apy_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
        "sharpe_need_days": sharpe_need_days,
        "sortino_ratio": round(sortino_ratio, 4) if sortino_ratio is not None else None,
        "sortino_need_days": sortino_need_days,
        "calmar_ratio": round(calmar_ratio, 4) if calmar_ratio is not None else None,
        "calmar_need_days": calmar_need_days,
        "benchmark_apy_pct": benchmark_apy_pct,
        "alpha_vs_benchmark_pct": round(alpha_vs_benchmark_pct, 4) if alpha_vs_benchmark_pct is not None else None,
        "n_observations": n_observations,
    }


# ─── Persistence ──────────────────────────────────────────────────────────────

def persist_report(report: dict, data_dir: str = "data") -> str:
    """Atomically write report to data/tear_sheet.json.

    Uses tmp-file + os.replace (POSIX atomic). Returns output path.
    """
    out_path = os.path.join(data_dir, "tear_sheet.json")
    atomic_save(report, str(out_path))
    return out_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPA performance tear sheet generator (read-only/advisory)"
    )
    parser.add_argument("--run", action="store_true", help="Compute and write tear_sheet.json")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write, default)")
    parser.add_argument("--data-dir", default="data", metavar="DIR", help="Data directory (default: data)")
    args = parser.parse_args()

    try:
        report = compute_report(args.data_dir)
        if args.run:
            path = persist_report(report, args.data_dir)
            print(f"[performance_report] Wrote {path}")
        print(json.dumps(report, indent=2))
    except Exception as exc:  # pragma: no cover
        print(f"[performance_report] Error: {exc}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
