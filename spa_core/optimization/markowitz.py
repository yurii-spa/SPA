"""
Simplified Markowitz for DeFi yield portfolio.
Minimises variance for a target return, without numpy/scipy dependency.
Uses gradient descent on portfolio weights.

Mean-Variance Optimization (MVO) framework:
  - Expected return  = weighted sum of protocol APYs
  - Portfolio variance = w^T Σ w  (quadratic form of covariance matrix)
  - Sharpe ratio = (return - risk_free) / sqrt(variance)

Covariance simplification for DeFi:
  - Same-tier protocols share underlying market exposure → ρ = 0.6
  - Cross-tier protocols have lower co-movement → ρ = 0.2
  - Individual variance proxy: (apy * 0.10)^2  (assume 10% CV of APY)

Gradient descent approach:
  - Project weights onto the probability simplex (sum=1, w_i >= 0) each step
  - Minimise a Lagrangian that trades off variance against return shortfall
  - For Sharpe maximisation, directly maximise (Rp - Rf) / sqrt(Vp)
"""

from __future__ import annotations

import math
import os
from typing import Optional

# Risk-free proxy rate (annualised %) — same constant as paper_trading/engine.py
_RISK_FREE_RATE_PCT = 5.0

# Correlation assumptions
_SAME_TIER_CORR = 0.6
_CROSS_TIER_CORR = 0.2

# Coefficient of variation proxy for DeFi APY volatility
_APY_CV = 0.10   # σ_i ≈ apy_i * 0.10


def _project_simplex(weights: list[float]) -> list[float]:
    """
    Project a vector onto the probability simplex:
      { w : sum(w) = 1, w_i >= 0 }

    Uses the O(n log n) algorithm by Duchi et al. (2008).
    Pure Python — no numpy.
    """
    n = len(weights)
    if n == 0:
        return []

    # Sort descending
    u = sorted(weights, reverse=True)
    cssv = 0.0
    rho = 0
    for i, u_i in enumerate(u):
        cssv += u_i
        if u_i - (cssv - 1.0) / (i + 1) > 0:
            rho = i

    theta = (sum(u[: rho + 1]) - 1.0) / (rho + 1)
    return [max(0.0, w - theta) for w in weights]


def _uniform_weights(n: int) -> list[float]:
    if n == 0:
        return []
    return [1.0 / n] * n


class PortfolioOptimizer:
    """
    Mean-Variance Optimizer for a DeFi yield portfolio.

    Parameters
    ----------
    protocols : list of dicts, each with keys:
        protocol_key : str   — unique identifier
        apy          : float — current APY in percent
        tier         : str   — "T1" or "T2"
        tvl_usd      : float — TVL in USD (informational, not used in MVO directly)
        weight       : float — current portfolio weight (used as warm-start)
    """

    def __init__(
        self,
        protocols: list[dict],
        live_covariance: Optional[bool] = None,
        covariance_estimator: Optional[object] = None,
    ):
        self.protocols = [p for p in protocols if p.get("apy", 0) > 0]
        self._n = len(self.protocols)
        self._cov: Optional[list[list[float]]] = None  # cached covariance

        # ── FEAT-007 Phase 2: live covariance wiring ──────────────────────
        # When the caller leaves ``live_covariance`` unset, read the
        # SPA_LIVE_COVARIANCE env flag.  Default OFF keeps paper-trading
        # numbers byte-identical to the synthetic path.
        if live_covariance is None:
            live_covariance = os.getenv(
                "SPA_LIVE_COVARIANCE", "0"
            ).lower() in ("1", "true", "yes")
        self.live_covariance: bool = bool(live_covariance)

        # Lazy-import the estimator only when needed — avoids a hard
        # dependency on the analytics package for synthetic-only callers
        # and prevents potential circular imports during cold start.
        self._estimator = covariance_estimator
        if self.live_covariance and self._estimator is None:
            from analytics.covariance_estimator import CovarianceEstimator
            self._estimator = CovarianceEstimator()

        # Source attribution for downstream observability ("live" vs
        # "synthetic").  Final value is set after ``estimate_covariance``
        # runs; the initial value reflects the requested mode.
        self.covariance_source: str = "live" if self.live_covariance else "synthetic"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sigma(self, i: int) -> float:
        """Individual APY standard deviation proxy."""
        return self.protocols[i]["apy"] * _APY_CV

    def _corr(self, i: int, j: int) -> float:
        """Pairwise correlation between protocols i and j."""
        if i == j:
            return 1.0
        tier_i = self.protocols[i].get("tier", "T1")
        tier_j = self.protocols[j].get("tier", "T1")
        return _SAME_TIER_CORR if tier_i == tier_j else _CROSS_TIER_CORR

    # ── Public methods ────────────────────────────────────────────────────────

    def estimate_covariance(self) -> list[list[float]]:
        """
        Build covariance matrix.

        Two source paths:

        Synthetic (default, env unset):
            Σ_ij = ρ_ij * σ_i * σ_j
            σ_i = apy_i * 0.10  (10% CV proxy)
            ρ_ij = 0.6 same-tier, 0.2 cross-tier.

        Live (``SPA_LIVE_COVARIANCE=1`` or ``live_covariance=True``):
            Delegates to ``CovarianceEstimator.compute_covariance_matrix``
            with a 90-day rolling window over ``data/apy_history.json``.
            Each protocol with <7 observations transparently falls back
            to the synthetic proxy inside the estimator, so the live path
            with an empty store is provably numerically equivalent to the
            synthetic path — see ADR-012 §"Cold-start blend".

        Returns n×n matrix as list of lists (canonical protocol order).
        Caches result; call again to rebuild after protocols change.
        """
        n = self._n
        cov = [[0.0] * n for _ in range(n)]

        if self.live_covariance and self._estimator is not None and n > 0:
            # Build the inputs the estimator needs to honour its
            # fallback contract for protocols with insufficient history.
            keys = [p["protocol_key"] for p in self.protocols]
            tiers = {
                p["protocol_key"]: p.get("tier", "T1") for p in self.protocols
            }
            synthetic_apys = {
                p["protocol_key"]: p["apy"] for p in self.protocols
            }

            live_matrix = self._estimator.compute_covariance_matrix(
                window_days=90,
                protocols=keys,
                tiers=tiers,
                synthetic_apys=synthetic_apys,
            )

            # Project the dict-of-dicts onto the list-of-lists in the
            # SAME order as ``self.protocols`` (the estimator may return
            # keys in sorted order — we re-index by our canonical layout).
            for i, k_i in enumerate(keys):
                for j, k_j in enumerate(keys):
                    cov[i][j] = float(live_matrix.get(k_i, {}).get(k_j, 0.0))

            self.covariance_source = "live"
        else:
            for i in range(n):
                for j in range(n):
                    cov[i][j] = self._corr(i, j) * self._sigma(i) * self._sigma(j)
            self.covariance_source = "synthetic"

        self._cov = cov
        return cov

    def portfolio_variance(self, weights: list[float]) -> float:
        """
        Compute portfolio variance: w^T Σ w

        Parameters
        ----------
        weights : portfolio weight vector (should sum to 1)

        Returns
        -------
        float — portfolio variance (APY units squared)
        """
        if self._cov is None:
            self.estimate_covariance()
        cov = self._cov
        n = self._n
        var = 0.0
        for i in range(n):
            for j in range(n):
                var += weights[i] * weights[j] * cov[i][j]
        return var

    def portfolio_return(self, weights: list[float]) -> float:
        """
        Compute expected portfolio return: Σ w_i * apy_i

        Parameters
        ----------
        weights : portfolio weight vector

        Returns
        -------
        float — expected portfolio APY in percent
        """
        return sum(
            weights[i] * self.protocols[i]["apy"]
            for i in range(self._n)
        )

    def _sharpe(self, weights: list[float]) -> float:
        """Sharpe ratio using annualised APY and risk-free rate."""
        ret = self.portfolio_return(weights)
        var = self.portfolio_variance(weights)
        std = math.sqrt(var) if var > 0 else 1e-9
        return (ret - _RISK_FREE_RATE_PCT) / std

    def optimize(
        self,
        target_return_pct: Optional[float] = None,
        n_iterations: int = 1000,
        lr: float = 0.05,
        tol: float = 1e-7,
    ) -> dict:
        """
        Optimise portfolio weights via projected gradient descent.

        If target_return_pct is None: maximise Sharpe ratio.
        Otherwise: minimise variance subject to return ≥ target_return_pct.

        Parameters
        ----------
        target_return_pct : target expected return in percent, or None for max-Sharpe
        n_iterations      : max gradient descent iterations (default 1000)
        lr                : initial learning rate (default 0.05)
        tol               : convergence tolerance on objective improvement (default 1e-7)

        Returns
        -------
        dict with keys:
            weights         : {protocol_key: float}
            expected_return : float (%)
            variance        : float
            sharpe          : float
        """
        n = self._n
        if n == 0:
            return {
                "weights": {},
                "expected_return": 0.0,
                "variance": 0.0,
                "sharpe": 0.0,
            }

        if self._cov is None:
            self.estimate_covariance()

        # Warm-start: use existing weights if provided, else uniform
        raw_warm = [p.get("weight", 0.0) for p in self.protocols]
        warm_sum = sum(raw_warm)
        if warm_sum > 1e-9:
            w = [x / warm_sum for x in raw_warm]
        else:
            w = _uniform_weights(n)

        # Penalty coefficient for return constraint (only used when target is set)
        penalty = 50.0

        prev_obj = None

        for iteration in range(n_iterations):
            # ── Compute objective and gradient ─────────────────────────────

            if target_return_pct is None:
                # Maximise Sharpe: gradient of Sharpe w.r.t. w_i
                ret = self.portfolio_return(w)
                var = self.portfolio_variance(w)
                std = math.sqrt(var) if var > 1e-12 else 1e-6
                excess = ret - _RISK_FREE_RATE_PCT
                sharpe_val = excess / std

                # ∂Sharpe/∂w_i = (apy_i / std) - (excess * (∂var/∂w_i) / (2 * std^3))
                # ∂var/∂w_i = 2 * Σ_j cov[i][j] * w_j
                grad = []
                cov = self._cov
                for i in range(n):
                    d_var_dwi = 2.0 * sum(cov[i][j] * w[j] for j in range(n))
                    d_sharpe = (self.protocols[i]["apy"] / std) - (
                        excess * d_var_dwi / (2.0 * std ** 3)
                    )
                    grad.append(d_sharpe)

                obj = sharpe_val

            else:
                # Minimise variance + penalty for shortfall on return
                ret = self.portfolio_return(w)
                var = self.portfolio_variance(w)
                shortfall = max(0.0, target_return_pct - ret)
                obj = -(var + penalty * shortfall ** 2)  # negate so we maximise

                cov = self._cov
                grad = []
                for i in range(n):
                    d_var_dwi = 2.0 * sum(cov[i][j] * w[j] for j in range(n))
                    # ∂penalty/∂w_i = -2 * penalty * shortfall * apy_i  (if shortfall > 0)
                    d_penalty = (
                        -2.0 * penalty * shortfall * self.protocols[i]["apy"]
                        if shortfall > 0
                        else 0.0
                    )
                    grad.append(-(d_var_dwi + d_penalty))  # negate for max

            # ── Adaptive learning rate (simple Armijo-style backtrack) ─────
            step = lr / (1.0 + iteration * 0.001)

            # ── Projected gradient step ────────────────────────────────────
            w_new = _project_simplex([w[i] + step * grad[i] for i in range(n)])

            # ── Convergence check ──────────────────────────────────────────
            if prev_obj is not None and abs(obj - prev_obj) < tol:
                break

            prev_obj = obj
            w = w_new

        # ── Final metrics ──────────────────────────────────────────────────
        expected_ret = self.portfolio_return(w)
        variance = self.portfolio_variance(w)
        sharpe = self._sharpe(w)

        weights_dict = {
            self.protocols[i]["protocol_key"]: round(w[i], 6)
            for i in range(n)
        }

        return {
            "weights": weights_dict,
            "expected_return": round(expected_ret, 4),
            "variance": round(variance, 8),
            "sharpe": round(sharpe, 4),
        }

    def efficient_frontier(
        self,
        n_points: int = 20,
    ) -> list[dict]:
        """
        Compute the efficient frontier by solving MVO for a range of target returns.

        Spans from the minimum-variance portfolio return up to the
        maximum APY available in the pool list.

        Parameters
        ----------
        n_points : number of frontier points (default 20)

        Returns
        -------
        list of dicts: [{target_return, variance, weights}, …]
        """
        n = self._n
        if n == 0:
            return []

        if self._cov is None:
            self.estimate_covariance()

        # Bounds for target return
        min_apy = min(p["apy"] for p in self.protocols)
        max_apy = max(p["apy"] for p in self.protocols)

        if abs(max_apy - min_apy) < 1e-9:
            # All protocols have the same APY — just return one point
            result = self.optimize(target_return_pct=min_apy)
            return [{
                "target_return": min_apy,
                "variance": result["variance"],
                "weights": result["weights"],
            }]

        step = (max_apy - min_apy) / max(1, n_points - 1)
        frontier = []

        for k in range(n_points):
            target = min_apy + k * step
            result = self.optimize(target_return_pct=target)
            frontier.append({
                "target_return": round(target, 4),
                "variance": result["variance"],
                "weights": result["weights"],
            })

        return frontier
