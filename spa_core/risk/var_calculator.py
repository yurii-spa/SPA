"""
spa_core/risk/var_calculator.py

Advanced Value-at-Risk (VaR) calculator for the SPA paper portfolio — v2.

Computes four institutional-grade tail-risk measures from the real daily
equity curve (``data/equity_curve_daily.json``):

  * Historical VaR (95% / 99%)   — empirical quantile of daily returns.
  * Parametric VaR (95% / 99%)   — normal-distribution closed form (μ, σ).
  * Expected Shortfall / CVaR95  — mean of the worst 5% of days.
  * Monte-Carlo VaR (30-day)     — 1000 simulated 30-day paths, 5% tail.

All headline figures are expressed as a **percent of portfolio value**
(e.g. ``1.25`` means 1.25%); USD equivalents are also reported.

Design constraints (SPA FORBIDDEN rules):
  * stdlib only — no external dependencies.
  * Atomic writes — tmp file + os.replace, never a bare open(..,"w").
  * Pure / deterministic — Monte-Carlo uses a fixed seed.
  * LLM FORBIDDEN — this is risk-domain deterministic code.

CLI:
    python3 -m spa_core.risk.var_calculator --check            # compute, no write
    python3 -m spa_core.risk.var_calculator --run              # + atomic write
    python3 -m spa_core.risk.var_calculator --run --data-dir data
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
from typing import Optional

__all__ = [
    "VaRCalculator",
    "percentile",
    "DEFAULT_CAPITAL",
    "MONTE_CARLO_SIMS",
    "MONTE_CARLO_HORIZON_DAYS",
]

DEFAULT_CAPITAL = 100_000.0
MONTE_CARLO_SIMS = 1000
MONTE_CARLO_HORIZON_DAYS = 30
MONTE_CARLO_SEED = 42

# One-sided normal z-scores for parametric VaR.
Z_SCORE = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}

OUTPUT_FILENAME = "var_analytics_v2.json"


# ─── Math helpers ────────────────────────────────────────────────────────────

def percentile(sorted_values: list, p: float) -> float:
    """
    Linear-interpolation percentile (numpy 'linear' method).

    Args:
        sorted_values: values sorted ascending. Must be non-empty.
        p: quantile in [0, 1].

    Returns:
        The interpolated value at quantile ``p``.
    """
    if not sorted_values:
        raise ValueError("percentile() requires at least one value")
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    p = min(1.0, max(0.0, p))
    rank = p * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_values[lo])
    frac = rank - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def _atomic_write_json(path: str, payload: dict) -> None:
    """Write JSON atomically: tmp file in same dir + os.replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


# ─── Calculator ──────────────────────────────────────────────────────────────

class VaRCalculator:
    """
    Portfolio-level VaR engine working off a list of daily fractional returns.

    A daily return of -0.012 means the portfolio lost 1.2% that day. All VaR
    outputs are positive numbers denoting *losses*; a negative raw quantile
    (i.e. the tail day was still a gain) is floored to 0 for the headline VaR
    but preserved under the ``*_raw_pct`` keys for transparency.
    """

    def __init__(self, returns: Optional[list] = None,
                 capital: float = DEFAULT_CAPITAL) -> None:
        self.returns = [float(r) for r in (returns or [])]
        self.capital = float(capital)

    # -- loaders ---------------------------------------------------------------

    @classmethod
    def from_equity_curve(cls, data_dir: str = "data") -> "VaRCalculator":
        """Build a calculator from data/equity_curve_daily.json."""
        returns = load_daily_returns(data_dir)
        capital = load_capital(data_dir)
        return cls(returns=returns, capital=capital)

    # -- individual measures ---------------------------------------------------

    def historical_var(self, confidence: float) -> float:
        """Empirical VaR as a *fraction* (loss, floored at 0)."""
        if len(self.returns) < 2:
            return 0.0
        ordered = sorted(self.returns)
        q = percentile(ordered, 1.0 - confidence)
        return max(0.0, -q)

    def historical_var_raw(self, confidence: float) -> float:
        """Empirical VaR fraction WITHOUT the zero floor (may be negative)."""
        if len(self.returns) < 2:
            return 0.0
        ordered = sorted(self.returns)
        return -percentile(ordered, 1.0 - confidence)

    def parametric_var(self, confidence: float) -> float:
        """Normal-distribution VaR fraction: z·σ − μ, floored at 0."""
        if len(self.returns) < 2:
            return 0.0
        mu = statistics.fmean(self.returns)
        sigma = statistics.pstdev(self.returns)
        z = Z_SCORE.get(confidence)
        if z is None:
            # generic inverse-CDF approximation for arbitrary confidence
            z = _inv_norm_cdf(confidence)
        return max(0.0, z * sigma - mu)

    def expected_shortfall(self, confidence: float) -> float:
        """CVaR fraction: mean loss of the worst (1-confidence) tail of days."""
        if len(self.returns) < 2:
            return 0.0
        ordered = sorted(self.returns)
        threshold = percentile(ordered, 1.0 - confidence)
        tail = [r for r in ordered if r <= threshold]
        if not tail:
            tail = [ordered[0]]
        return max(0.0, -statistics.fmean(tail))

    def monte_carlo_var(self, confidence: float = 0.95,
                        horizon_days: int = MONTE_CARLO_HORIZON_DAYS,
                        sims: int = MONTE_CARLO_SIMS) -> float:
        """
        Monte-Carlo VaR fraction over ``horizon_days``.

        Draws daily returns from a normal distribution fitted to the history,
        compounds each path over the horizon, and takes the loss at the
        ``1-confidence`` tail. Deterministic via a fixed seed.
        """
        if len(self.returns) < 2:
            return 0.0
        mu = statistics.fmean(self.returns)
        sigma = statistics.pstdev(self.returns)
        rng = random.Random(MONTE_CARLO_SEED)
        horizon_returns = []
        for _ in range(sims):
            growth = 1.0
            for _ in range(horizon_days):
                growth *= 1.0 + rng.gauss(mu, sigma)
            horizon_returns.append(growth - 1.0)
        horizon_returns.sort()
        q = percentile(horizon_returns, 1.0 - confidence)
        return max(0.0, -q)

    # -- aggregate -------------------------------------------------------------

    def analyze(self) -> dict:
        """Compute every measure and return a JSON-serialisable result dict."""
        cap = self.capital
        n = len(self.returns)

        def pct(frac: float) -> float:
            return round(frac * 100.0, 6)

        def usd(frac: float) -> float:
            return round(frac * cap, 2)

        h95 = self.historical_var(0.95)
        h99 = self.historical_var(0.99)
        p95 = self.parametric_var(0.95)
        p99 = self.parametric_var(0.99)
        cvar95 = self.expected_shortfall(0.95)
        mc30 = self.monte_carlo_var(0.95, MONTE_CARLO_HORIZON_DAYS, MONTE_CARLO_SIMS)

        mu = statistics.fmean(self.returns) if n else 0.0
        sigma = statistics.pstdev(self.returns) if n > 1 else 0.0

        return {
            "module": "var_calculator_v2",
            "is_demo": False,
            "n_returns": n,
            "capital_usd": round(cap, 2),
            "mean_daily_return_pct": pct(mu),
            "daily_volatility_pct": pct(sigma),
            # Required headline outputs (percent of portfolio value):
            "VaR95": pct(h95),
            "VaR99": pct(h99),
            "CVaR95": pct(cvar95),
            "monte_carlo_var30d": pct(mc30),
            # Detail block:
            "historical": {
                "var95_pct": pct(h95),
                "var99_pct": pct(h99),
                "var95_raw_pct": pct(self.historical_var_raw(0.95)),
                "var99_raw_pct": pct(self.historical_var_raw(0.99)),
                "var95_usd": usd(h95),
                "var99_usd": usd(h99),
            },
            "parametric": {
                "var95_pct": pct(p95),
                "var99_pct": pct(p99),
                "var95_usd": usd(p95),
                "var99_usd": usd(p99),
            },
            "expected_shortfall": {
                "cvar95_pct": pct(cvar95),
                "cvar95_usd": usd(cvar95),
            },
            "monte_carlo": {
                "horizon_days": MONTE_CARLO_HORIZON_DAYS,
                "simulations": MONTE_CARLO_SIMS,
                "seed": MONTE_CARLO_SEED,
                "var95_30d_pct": pct(mc30),
                "var95_30d_usd": usd(mc30),
            },
        }


# ─── Inverse normal CDF (Acklam) ─────────────────────────────────────────────

def _inv_norm_cdf(p: float) -> float:
    """Acklam's rational approximation of the inverse standard-normal CDF."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# ─── Data loading ────────────────────────────────────────────────────────────

def load_daily_returns(data_dir: str = "data") -> list:
    """
    Load daily fractional returns from equity_curve_daily.json.

    Prefers reconstructing returns from the close_equity series (robust); falls
    back to the stored ``daily_return_pct`` (which is in percent units).
    Returns an empty list if the file is missing or malformed.
    """
    path = os.path.join(data_dir, "equity_curve_daily.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception:
        return []
    daily = doc.get("daily") if isinstance(doc, dict) else doc
    if not isinstance(daily, list) or len(daily) < 2:
        return []

    equities = []
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        val = entry.get("close_equity", entry.get("equity", entry.get("nav")))
        if isinstance(val, (int, float)):
            equities.append(float(val))
    if len(equities) >= 2:
        return [
            (equities[i] - equities[i - 1]) / equities[i - 1]
            for i in range(1, len(equities))
            if equities[i - 1] != 0
        ]

    # Fallback: stored daily_return_pct is in percent units → /100 for fraction.
    rets = []
    for entry in daily:
        if isinstance(entry, dict) and isinstance(entry.get("daily_return_pct"), (int, float)):
            rets.append(float(entry["daily_return_pct"]) / 100.0)
    return rets


def load_capital(data_dir: str = "data") -> float:
    """Load portfolio capital from current_positions.json; fallback default."""
    path = os.path.join(data_dir, "current_positions.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            cap = doc.get("capital_usd")
            if isinstance(cap, (int, float)) and cap > 0:
                return float(cap)
        except Exception:
            pass
    return DEFAULT_CAPITAL


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run_mode = "--run" in args
    data_dir = "data"
    for i, a in enumerate(args):
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    calc = VaRCalculator.from_equity_curve(data_dir)
    if not calc.returns:
        print("[var_calculator] no equity-curve returns found — using flat history")
    result = calc.analyze()

    print(f"[var_calculator] n={result['n_returns']} daily returns, "
          f"capital ${result['capital_usd']:,.0f}")
    print(f"  Historical VaR95 = {result['VaR95']:.4f}%   "
          f"(${result['historical']['var95_usd']:,.2f})")
    print(f"  Historical VaR99 = {result['VaR99']:.4f}%   "
          f"(${result['historical']['var99_usd']:,.2f})")
    print(f"  Parametric VaR95 = {result['parametric']['var95_pct']:.4f}%   "
          f"VaR99 = {result['parametric']['var99_pct']:.4f}%")
    print(f"  Expected Shortfall (CVaR95) = {result['CVaR95']:.4f}%   "
          f"(${result['expected_shortfall']['cvar95_usd']:,.2f})")
    print(f"  Monte-Carlo VaR 30d = {result['monte_carlo_var30d']:.4f}%   "
          f"(${result['monte_carlo']['var95_30d_usd']:,.2f})")

    if run_mode:
        out = os.path.join(data_dir, OUTPUT_FILENAME)
        _atomic_write_json(out, result)
        print(f"[var_calculator] saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
