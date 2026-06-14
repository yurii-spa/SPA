"""
Generates allocation recommendations by combining:
1. Kelly sizing (individual position limits)
2. Markowitz (portfolio-level optimization)
3. RiskPolicy (hard constraints — never bypassed)

Workflow:
  1. Filter candidate pools to those accepted by Kelly (fraction > 0)
  2. Run Markowitz optimization on accepted candidates
  3. Scale Markowitz weights by Kelly fractions (more conservative sizing)
  4. For each candidate, run RiskPolicy.check_new_position() with proposed size
  5. Return only approved recommendations; flag rejected ones with approved_by_risk=False

Edge cases handled:
  - Empty pools list → empty recommendations
  - All pools rejected by RiskPolicy → empty recommendations with explanation
  - capital = 0 → empty recommendations
  - Single pool → trivially optimized
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Optional

# Make sure spa_core sub-packages resolve whether called from spa_core/ or above
sys.path.insert(0, str(Path(__file__).parent.parent))

from optimization.kelly import kelly_fraction, kelly_position_size
from optimization.markowitz import PortfolioOptimizer
from risk.policy import RiskPolicy, PortfolioState, Position

log = logging.getLogger(__name__)

# Minimum Kelly half-fraction to consider a pool worthy of inclusion in MVO
_MIN_KELLY_FRACTION = 0.01   # pools with half-Kelly < 1% are skipped
# Maximum Markowitz weight before Kelly scaling (safety guardrail)
_MAX_MARKOWITZ_WEIGHT = 0.60
# Risk-free proxy rate (must match markowitz.py)
_RISK_FREE_PCT = 5.0


class AllocationRecommender:
    """
    Combines Kelly + Markowitz + RiskPolicy to produce allocation recommendations.

    Usage:
        rec = AllocationRecommender()
        result = rec.recommend(pools=pools_data, capital=100_000.0)
    """

    def __init__(self, risk_policy: Optional[RiskPolicy] = None):
        self.risk_policy = risk_policy or RiskPolicy()
        self.optimizer: Optional[PortfolioOptimizer] = None   # exposed for efficient_frontier

    # ── Public API ────────────────────────────────────────────────────────────

    def recommend(
        self,
        pools: list[dict],
        capital: float,
        current_positions: Optional[list] = None,
    ) -> dict:
        """
        Generate allocation recommendations.

        Parameters
        ----------
        pools : list of pool dicts (from protocols.json / DB query).
            Required keys per pool: protocol_key, apy (or apy_total), tier, tvl_usd
            Optional: weight (float, current weight in portfolio)
        capital : total portfolio capital in USD
        current_positions : list of current position dicts (from trader.get_status())
            Used to compute vs_current improvement metrics.

        Returns
        -------
        dict with keys:
            recommendations   : list of recommendation dicts
            portfolio_expected_return : float (%)
            portfolio_sharpe  : float
            vs_current        : {"return_improvement_pct": float}
        """
        # ── Guard: edge cases ─────────────────────────────────────────────
        empty_result = {
            "recommendations": [],
            "portfolio_expected_return": 0.0,
            "portfolio_sharpe": 0.0,
            "vs_current": {"return_improvement_pct": 0.0},
            "covariance_source": "synthetic",
        }

        if capital <= 0:
            log.warning("AllocationRecommender: capital=0, returning empty recommendations")
            return empty_result

        if not pools:
            log.warning("AllocationRecommender: no pools provided")
            return empty_result

        # ── Normalise pool field names ─────────────────────────────────────
        normalised = []
        for p in pools:
            apy = float(p.get("apy") or p.get("apy_total") or 0.0)
            tvl = float(p.get("tvl_usd") or 0.0)
            key = p.get("protocol_key") or p.get("key") or ""
            tier = (p.get("tier") or "T2").upper()
            weight = float(p.get("weight") or 0.0)

            if not key or apy <= 0 or tvl <= 0:
                continue   # skip incomplete / zero-yield pools

            normalised.append({
                "protocol_key": key,
                "apy":          apy,
                "tier":         tier,
                "tvl_usd":      tvl,
                "weight":       weight,
            })

        if not normalised:
            log.warning("AllocationRecommender: no valid pools after normalisation")
            return empty_result

        # ── FEAT-007 Phase 2: live covariance / dynamic Kelly toggle ──────
        live = os.getenv("SPA_LIVE_COVARIANCE", "0").lower() in ("1", "true", "yes")

        # Build a per-protocol volatility map only when running live.
        # Lazy-import so the analytics package isn't a hard dep for the
        # synthetic path.
        estimator = None
        vol_map: dict[str, float] = {}
        if live:
            from analytics.covariance_estimator import CovarianceEstimator
            from optimization.dynamic_kelly import dynamic_kelly_fraction

            estimator = CovarianceEstimator()
            for pool in normalised:
                vol_map[pool["protocol_key"]] = estimator.compute_volatility(
                    pool["protocol_key"],
                    synthetic_apy=pool["apy"],
                )

        # ── Step 1: Kelly pre-filter ───────────────────────────────────────
        kelly_fracs: dict[str, float] = {}
        mvo_candidates: list[dict] = []

        for pool in normalised:
            if live:
                kf = dynamic_kelly_fraction(
                    apy_pct=pool["apy"],
                    tier=pool["tier"],
                    tvl_usd=pool["tvl_usd"],
                    volatility_pp=vol_map.get(pool["protocol_key"]),
                )
            else:
                kf = kelly_fraction(
                    apy_pct=pool["apy"],
                    tier=pool["tier"],
                    tvl_usd=pool["tvl_usd"],
                )
            half_kf = kf / 2.0
            kelly_fracs[pool["protocol_key"]] = half_kf

            if half_kf >= _MIN_KELLY_FRACTION:
                mvo_candidates.append(pool)

        if not mvo_candidates:
            log.info("AllocationRecommender: all pools filtered out by Kelly criterion")
            empty_with_source = dict(empty_result)
            empty_with_source["covariance_source"] = "live" if live else "synthetic"
            return empty_with_source

        # ── Step 2: Markowitz optimisation ────────────────────────────────
        self.optimizer = PortfolioOptimizer(
            protocols=mvo_candidates,
            live_covariance=live,
            covariance_estimator=estimator,
        )
        self.optimizer.estimate_covariance()
        mvo_result = self.optimizer.optimize(target_return_pct=None)   # max-Sharpe

        mvo_weights: dict[str, float] = mvo_result["weights"]
        mvo_return: float = mvo_result["expected_return"]
        mvo_sharpe: float = mvo_result["sharpe"]

        # ── Step 3: Kelly-scale the Markowitz weights ─────────────────────
        # Combined weight = MVO_weight * Kelly_fraction  (then re-normalise)
        combined: dict[str, float] = {}
        for key, mvo_w in mvo_weights.items():
            kf = kelly_fracs.get(key, 0.0)
            combined[key] = mvo_w * kf

        combined_sum = sum(combined.values())
        if combined_sum < 1e-9:
            log.info("AllocationRecommender: combined Kelly*MVO weights sum to zero")
            return empty_result

        normalised_combined = {k: v / combined_sum for k, v in combined.items()}

        # ── Step 4: Build PortfolioState for RiskPolicy ───────────────────
        portfolio_state = self._build_portfolio_state(capital, current_positions or [])

        # ── Step 5: RiskPolicy check and build recommendations ────────────
        recommendations = []

        for pool in mvo_candidates:
            key = pool["protocol_key"]
            w = normalised_combined.get(key, 0.0)
            if w < 1e-6:
                continue

            proposed_usd = w * capital

            risk_result = self.risk_policy.check_new_position(
                state=portfolio_state,
                protocol_key=key,
                tier=pool["tier"],
                amount_usd=proposed_usd,
                current_apy=pool["apy"],
                tvl_usd=pool["tvl_usd"],
            )

            recommendations.append({
                "protocol_key":    key,
                "amount_usd":      round(proposed_usd, 2),
                "pct":             round(w * 100.0, 4),
                "kelly_fraction":  round(kelly_fracs.get(key, 0.0), 6),
                "expected_apy":    round(pool["apy"], 4),
                "approved_by_risk": risk_result.approved,
                "risk_violations": risk_result.violations,
                "risk_warnings":   risk_result.warnings,
                "tier":            pool["tier"],
            })

            if not risk_result.approved:
                log.info(
                    f"AllocationRecommender: {key} rejected by RiskPolicy — "
                    + "; ".join(risk_result.violations)
                )

        # Sort: approved first, then by amount descending
        recommendations.sort(key=lambda r: (-int(r["approved_by_risk"]), -r["amount_usd"]))

        # ── vs_current comparison ──────────────────────────────────────────
        current_apy = self._current_portfolio_apy(current_positions or [], capital)
        return_improvement = mvo_return - current_apy

        return {
            "recommendations":            recommendations,
            "portfolio_expected_return":  round(mvo_return, 4),
            "portfolio_sharpe":           round(mvo_sharpe, 4),
            "vs_current": {
                "return_improvement_pct": round(return_improvement, 4),
            },
            "covariance_source": getattr(self.optimizer, "covariance_source", "synthetic"),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_portfolio_state(
        capital: float,
        current_positions: list,
    ) -> PortfolioState:
        """
        Build a PortfolioState from raw position dicts returned by trader.get_status().

        The position dicts come from the DB; we map them to Position dataclass.
        Any field that's missing gets a safe default.
        """
        positions = []
        for pos in current_positions:
            try:
                positions.append(Position(
                    protocol_key=pos.get("protocol_key", "unknown"),
                    tier=(pos.get("tier") or "T1").upper(),
                    asset=pos.get("asset", ""),
                    amount_usd=float(pos.get("amount_usd") or 0.0),
                    apy_at_open=float(pos.get("apy_at_open") or 0.0),
                    current_apy=float(pos.get("current_apy") or 0.0),
                    unrealized_pnl_usd=float(pos.get("unrealized_pnl_usd") or 0.0),
                    days_held=float(pos.get("days_held") or 0.0),
                ))
            except Exception as exc:
                log.warning(f"AllocationRecommender: skipping malformed position {pos}: {exc}")

        return PortfolioState(total_capital_usd=capital, positions=positions)

    @staticmethod
    def _current_portfolio_apy(
        current_positions: list,
        capital: float,
    ) -> float:
        """Compute weighted-average APY of the current portfolio."""
        if not current_positions or capital <= 0:
            return 0.0

        total_weighted = 0.0
        total_deployed = 0.0
        for pos in current_positions:
            amt = float(pos.get("amount_usd") or 0.0)
            apy = float(pos.get("current_apy") or 0.0)
            total_weighted += amt * apy
            total_deployed += amt

        if total_deployed < 1e-9:
            return 0.0

        return total_weighted / total_deployed
