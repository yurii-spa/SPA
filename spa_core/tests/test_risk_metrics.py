"""
Tests for the paper-trading risk-adjusted metrics module (SPA-V380).

Stdlib-only, self-contained runner (pytest is not installed in this repo;
mirrors the PASS/FAIL convention of test_equity_curve.py / test_paper_trading.py).

Run::
    python spa_core/tests/test_risk_metrics.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.risk_metrics import (
    ANNUALIZATION_DAYS,
    compute_risk_metrics,
    generate_risk_metrics_report,
)


# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0


def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except AssertionError as exc:
        FAIL += 1
        print(f"  ✗ {name}: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors as fails
        FAIL += 1
        print(f"  ✗ {name}: UNEXPECTED {type(exc).__name__}: {exc}")


def _curve(returns, opens=None):
    """Build a minimal daily curve from a list of daily_return_pct values.

    The first element is the seed day (daily_return_pct forced to 0.0).
    Drawdown is computed from a synthetic close path so max_drawdown_pct is
    realistic for the supplied returns.
    """
    bars = []
    equity = 100.0
    peak = 100.0
    for i, r in enumerate(returns):
        dr = 0.0 if i == 0 else r
        equity *= (1.0 + dr / 100.0)
        peak = max(peak, equity)
        dd = (equity / peak - 1.0) * 100.0
        bars.append({
            "date": f"2026-05-{15 + i:02d}",
            "open_equity": round(equity, 4),
            "close_equity": round(equity, 4),
            "high_equity": round(equity, 4),
            "low_equity": round(equity, 4),
            "snapshots": 1,
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": 0.0,
            "drawdown_pct": round(dd, 6),
        })
    return bars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_empty_curve_stable_schema():
    m = compute_risk_metrics([])
    assert m["num_return_days"] == 0, m
    assert m["sharpe_ratio"] is None, m
    assert m["max_drawdown_pct"] == 0.0, m
    assert m["annualization_days"] == ANNUALIZATION_DAYS, m


def test_single_day_no_returns():
    # Only the seed day → no realised returns.
    m = compute_risk_metrics(_curve([0.0]))
    assert m["num_return_days"] == 0, m
    assert m["win_rate_pct"] is None, m


def test_basic_counts_and_winrate():
    # seed + returns: +1, -0.5, +0.5, -0.25 → 4 return days, 2 wins.
    m = compute_risk_metrics(_curve([0.0, 1.0, -0.5, 0.5, -0.25]))
    assert m["num_return_days"] == 4, m
    assert approx(m["win_rate_pct"], 50.0), m
    assert m["avg_win_pct"] is not None and m["avg_win_pct"] > 0, m
    assert m["avg_loss_pct"] is not None and m["avg_loss_pct"] < 0, m


def test_profit_factor():
    # gains sum = 1.0 + 0.5 = 1.5; losses sum = -0.5 - 0.25 = -0.75 → PF = 2.0
    m = compute_risk_metrics(_curve([0.0, 1.0, -0.5, 0.5, -0.25]))
    assert approx(m["profit_factor"], 2.0, tol=1e-4), m["profit_factor"]


def test_no_losses_profit_factor_none():
    # All-positive *varying* returns → no losing days → profit_factor undefined
    # (None), sortino undefined (zero downside), but vol > 0 so sharpe is finite.
    m = compute_risk_metrics(_curve([0.0, 0.5, 0.3, 0.7]))
    assert m["profit_factor"] is None, m
    assert m["sortino_ratio"] is None, m
    assert m["downside_deviation_pct"] == 0.0, m
    assert m["avg_loss_pct"] is None, m
    assert m["sharpe_ratio"] is not None, m


def test_zero_volatility_sharpe_none():
    # Constant non-zero return → zero stdev → sharpe undefined (div by 0 vol).
    m = compute_risk_metrics(_curve([0.0, 0.3, 0.3, 0.3]))
    assert approx(m["daily_volatility_pct"], 0.0), m
    assert m["sharpe_ratio"] is None, m


def test_annualized_return_geometric():
    # Constant +0.1%/day compounded over the year.
    rets = [0.0] + [0.1] * 10
    m = compute_risk_metrics(_curve(rets))
    growth = (1.001) ** 10
    expected = (growth ** (ANNUALIZATION_DAYS / 10) - 1.0) * 100.0
    assert approx(m["annualized_return_pct"], round(expected, 4), tol=1e-2), (
        m["annualized_return_pct"], expected)


def test_sharpe_sign_and_riskfree():
    # Positive mean return, some vol → positive sharpe; raising the risk-free
    # rate must lower the sharpe ratio.
    rets = [0.0, 0.4, -0.1, 0.3, -0.05, 0.2]
    m0 = compute_risk_metrics(_curve(rets), risk_free_annual_pct=0.0)
    m5 = compute_risk_metrics(_curve(rets), risk_free_annual_pct=5.0)
    assert m0["sharpe_ratio"] is not None and m0["sharpe_ratio"] > 0, m0
    assert m5["sharpe_ratio"] < m0["sharpe_ratio"], (m0["sharpe_ratio"], m5["sharpe_ratio"])


def test_calmar_uses_max_drawdown():
    # A path with a real drawdown → calmar = annual_return / abs(max_dd).
    rets = [0.0, 1.0, -2.0, 0.5, 0.5]
    m = compute_risk_metrics(_curve(rets))
    assert m["max_drawdown_pct"] < 0, m
    if m["calmar_ratio"] is not None:
        expected = m["annualized_return_pct"] / abs(m["max_drawdown_pct"])
        assert approx(m["calmar_ratio"], round(expected, 4), tol=1e-3), m


def test_best_worst_day():
    rets = [0.0, 1.0, -2.0, 0.5]
    m = compute_risk_metrics(_curve(rets))
    assert m["best_day"]["daily_return_pct"] == 1.0, m["best_day"]
    assert m["worst_day"]["daily_return_pct"] == -2.0, m["worst_day"]


def test_sortino_finite_with_losses():
    rets = [0.0, 0.5, -0.3, 0.4, -0.2]
    m = compute_risk_metrics(_curve(rets))
    assert m["downside_deviation_pct"] > 0, m
    assert m["sortino_ratio"] is not None, m
    # Sortino penalises only downside → for a positive-skew series it should
    # not be below sharpe.
    assert m["sortino_ratio"] >= m["sharpe_ratio"] - 1e-6, (
        m["sortino_ratio"], m["sharpe_ratio"])


def test_capital_wipe_guard():
    # A -100%+ day must not raise (e.g. negative growth) → clamped to -100%.
    m = compute_risk_metrics(_curve([0.0, -100.0, 5.0]))
    assert m["annualized_return_pct"] == -100.0, m


def test_report_no_write_smoke():
    # Run against the real history file, compute-only (output_path=None).
    rep = generate_risk_metrics_report(output_path=None)
    assert "metrics" in rep and "generated_at" in rep, rep
    assert isinstance(rep["metrics"]["num_return_days"], int), rep
    # All numeric/None fields must be JSON-serializable & finite where present.
    for k, v in rep["metrics"].items():
        if isinstance(v, float):
            assert math.isfinite(v), (k, v)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_risk_metrics (SPA-V380)")
    run("empty curve → stable schema", test_empty_curve_stable_schema)
    run("single seed day → no returns", test_single_day_no_returns)
    run("counts + win rate", test_basic_counts_and_winrate)
    run("profit factor", test_profit_factor)
    run("no losses → PF/sortino None", test_no_losses_profit_factor_none)
    run("zero vol → sharpe None", test_zero_volatility_sharpe_none)
    run("annualized return geometric", test_annualized_return_geometric)
    run("sharpe sign + risk-free effect", test_sharpe_sign_and_riskfree)
    run("calmar uses max drawdown", test_calmar_uses_max_drawdown)
    run("best/worst day", test_best_worst_day)
    run("sortino finite with losses", test_sortino_finite_with_losses)
    run("capital-wipe guard", test_capital_wipe_guard)
    run("report no-write smoke (real data)", test_report_no_write_smoke)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
