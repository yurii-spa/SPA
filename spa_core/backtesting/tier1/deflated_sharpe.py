"""
spa_core/backtesting/tier1/deflated_sharpe.py — Tier-1 statistical validation core.

PARALLEL MODEL (does not modify RiskPolicy v1.0, the cycle, or any canonical module).
Pure stdlib (math + statistics.NormalDist), deterministic, LLM-forbidden.

Implements the Bailey & López de Prado family used by institutional quant funds to
defend against backtest overfitting / data-snooping:

  • Probabilistic Sharpe Ratio (PSR) — confidence that the TRUE Sharpe > a benchmark,
    correcting for sample length, skew and kurtosis (non-normal returns).
  • Expected Maximum Sharpe under the null — the Sharpe you'd expect to see from the
    LUCKIEST of N independent trials even if every strategy had zero edge.
  • Deflated Sharpe Ratio (DSR) — PSR measured against that expected-max benchmark.
    This is the key correction the tournament lacked: ranking 64 strategies and picking
    the best inflates its Sharpe; DSR tells you whether the winner is real or lucky.
  • Minimum Track Record Length (minTRL) — how many observations are needed before a
    Sharpe is statistically trustworthy at a given confidence.

Why this matters here: the daily mass_tournament ranks ~64 strategies by Sharpe and
promotes the top ones. Without a multiple-testing correction, the "best strategy" is
partly selection bias. DSR > 0.95 is the institutional bar for "this edge is real".

References: Bailey & López de Prado (2012, 2014), "The Sharpe Ratio Efficient Frontier"
and "The Deflated Sharpe Ratio". All formulas reimplemented in stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from statistics import NormalDist
from typing import List, Sequence

_N = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329
DAYS_PER_YEAR = 365  # stablecoin yield accrues daily


# ---------------------------------------------------------------------------
# Return-series moments (when a full return series is available)
# ---------------------------------------------------------------------------
def moments(returns: Sequence[float]) -> dict:
    """mean, std (sample), skewness, kurtosis (Pearson, normal == 3.0)."""
    n = len(returns)
    if n < 2:
        return {"n": n, "mean": 0.0, "std": 0.0, "skew": 0.0, "kurt": 3.0}
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std == 0:
        return {"n": n, "mean": mean, "std": 0.0, "skew": 0.0, "kurt": 3.0}
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    pop_std = math.sqrt(sum((r - mean) ** 2 for r in returns) / n)
    skew = m3 / (pop_std ** 3)
    kurt = m4 / (pop_std ** 4)
    return {"n": n, "mean": mean, "std": std, "skew": skew, "kurt": kurt}


def sharpe_per_period(returns: Sequence[float], rf_per_period: float = 0.0) -> float:
    m = moments(returns)
    if m["std"] == 0:
        return 0.0
    return (m["mean"] - rf_per_period) / m["std"]


def annualize_sharpe(sr_per_period: float, periods_per_year: int = DAYS_PER_YEAR) -> float:
    return sr_per_period * math.sqrt(periods_per_year)


def deannualize_sharpe(sr_annual: float, periods_per_year: int = DAYS_PER_YEAR) -> float:
    return sr_annual / math.sqrt(periods_per_year)


# ---------------------------------------------------------------------------
# Probabilistic Sharpe Ratio
# ---------------------------------------------------------------------------
def probabilistic_sharpe_ratio(
    sr_per_period: float,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
    sr_benchmark_per_period: float = 0.0,
) -> float:
    """P(true SR > benchmark). sr/benchmark are PER-PERIOD (not annualized).
    Returns a probability in [0, 1]. n_obs is the number of return observations."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr_per_period + ((kurt - 1.0) / 4.0) * (sr_per_period ** 2)
    if denom <= 0:
        denom = 1e-9
    z = (sr_per_period - sr_benchmark_per_period) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _N.cdf(z)


# ---------------------------------------------------------------------------
# Expected maximum Sharpe under the null (multiple-testing benchmark)
# ---------------------------------------------------------------------------
def expected_max_sharpe(sr_variance_across_trials: float, n_trials: int) -> float:
    """Expected max of N_trials Sharpe ratios drawn from N(0, var) — the Sharpe the
    LUCKIEST strategy would show with NO real edge. This is the benchmark the tournament
    winner must beat. sr_variance is the cross-sectional variance of the trials' Sharpe."""
    if n_trials < 2 or sr_variance_across_trials <= 0:
        return 0.0
    sigma = math.sqrt(sr_variance_across_trials)
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return sigma * ((1.0 - _EULER_MASCHERONI) * a + _EULER_MASCHERONI * b)


def deflated_sharpe_ratio(
    sr_per_period: float,
    n_obs: int,
    sr_variance_across_trials: float,
    n_trials: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> dict:
    """DSR = PSR measured against the expected-max-Sharpe benchmark. The strategy's edge
    is considered REAL (not data-snooping) when dsr >= 0.95. All Sharpe values per-period."""
    sr_star = expected_max_sharpe(sr_variance_across_trials, n_trials)
    dsr = probabilistic_sharpe_ratio(sr_per_period, n_obs, skew, kurt, sr_star)
    return {
        "dsr": dsr,
        "sr_benchmark_per_period": sr_star,
        "passes": dsr >= 0.95,
        "n_trials": n_trials,
    }


def min_track_record_length(
    sr_per_period: float,
    skew: float = 0.0,
    kurt: float = 3.0,
    sr_benchmark_per_period: float = 0.0,
    target_prob: float = 0.95,
) -> float:
    """Minimum number of observations for PSR >= target_prob. inf if SR <= benchmark."""
    edge = sr_per_period - sr_benchmark_per_period
    if edge <= 0:
        return float("inf")
    denom = 1.0 - skew * sr_per_period + ((kurt - 1.0) / 4.0) * (sr_per_period ** 2)
    return 1.0 + denom * (_N.inv_cdf(target_prob) / edge) ** 2


def sharpe_variance_across_trials(sharpes: List[float]) -> float:
    """Cross-sectional variance of the trials' Sharpe. UNIT-AGNOSTIC but must match the
    units used elsewhere: pass PER-PERIOD Sharpes so expected_max_sharpe / DSR stay
    consistent with probabilistic_sharpe_ratio (which uses per-period Sharpe)."""
    vals = [s for s in sharpes if s is not None]
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return sum((s - mean) ** 2 for s in vals) / (n - 1)


if __name__ == "__main__":
    # Self-test: 64 trials, winner SR=2.0 annual over 365 days, cross-sectional SR std ~0.8
    import json
    # 64 trials with annualized Sharpe spread; winner = 2.0 annual over 365 daily obs.
    sharpes_annual = [0.8 * NormalDist().inv_cdf((i + 0.5) / 64) for i in range(64)]
    sharpes_annual[-1] = 2.0  # the "winner"
    # Work in PER-PERIOD units throughout (consistent with PSR).
    sharpes_pp = [deannualize_sharpe(s) for s in sharpes_annual]
    var_pp = sharpe_variance_across_trials(sharpes_pp)
    sr_pp = deannualize_sharpe(2.0)
    out = deflated_sharpe_ratio(sr_pp, n_obs=365, sr_variance_across_trials=var_pp, n_trials=64)
    out["psr_vs_zero"] = round(probabilistic_sharpe_ratio(sr_pp, 365), 4)
    out["minTRL_days"] = round(min_track_record_length(sr_pp), 1)
    out["dsr"] = round(out["dsr"], 4)
    out["sr_benchmark_annual"] = round(annualize_sharpe(out["sr_benchmark_per_period"]), 3)
    print(json.dumps(out, indent=2))
