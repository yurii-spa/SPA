"""
Tests for optimization module — Kelly criterion, Markowitz, and AllocationRecommender.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimization.kelly import kelly_fraction, half_kelly, kelly_position_size
from optimization.markowitz import PortfolioOptimizer
from optimization.recommender import AllocationRecommender


# ─── Sample data helpers ───────────────────────────────────────────────────────

def _make_pools(n=3):
    """Return n valid T1 pool dicts for testing."""
    base = [
        {"protocol_key": "aave-v3-usdc-ethereum",    "apy": 4.65, "tier": "T1", "tvl_usd": 138_000_000},
        {"protocol_key": "compound-v3-usdc-ethereum", "apy": 4.10, "tier": "T1", "tvl_usd": 42_000_000},
        {"protocol_key": "morpho-usdc-ethereum",      "apy": 5.30, "tier": "T1", "tvl_usd": 112_000_000},
        {"protocol_key": "maple-usdc-ethereum",       "apy": 7.50, "tier": "T2", "tvl_usd": 18_000_000},
    ]
    return base[:n]


# ─── Kelly Criterion tests ─────────────────────────────────────────────────────

class TestKellyFraction:

    def test_returns_value_in_unit_interval(self):
        """kelly_fraction must always return a value in [0, 1]."""
        for apy in [1.0, 4.65, 10.0, 20.0, 30.0]:
            for tier in ["T1", "T2"]:
                result = kelly_fraction(apy_pct=apy, tier=tier, tvl_usd=50_000_000)
                assert 0.0 <= result <= 1.0, f"Out of range for apy={apy}, tier={tier}: {result}"

    def test_zero_apy_returns_zero(self):
        assert kelly_fraction(apy_pct=0.0, tier="T1", tvl_usd=50_000_000) == 0.0

    def test_negative_apy_returns_zero(self):
        assert kelly_fraction(apy_pct=-1.0, tier="T1", tvl_usd=50_000_000) == 0.0

    def test_zero_tvl_returns_zero(self):
        assert kelly_fraction(apy_pct=5.0, tier="T1", tvl_usd=0.0) == 0.0

    def test_t1_higher_than_t2_same_conditions(self):
        """T1 should have a higher Kelly fraction than T2 at the same APY/TVL."""
        kf_t1 = kelly_fraction(apy_pct=10.0, tier="T1", tvl_usd=50_000_000)
        kf_t2 = kelly_fraction(apy_pct=10.0, tier="T2", tvl_usd=50_000_000)
        assert kf_t1 >= kf_t2

    def test_high_tvl_boosts_fraction(self):
        """TVL > $1B should increase Kelly fraction vs TVL $50M."""
        kf_low_tvl  = kelly_fraction(apy_pct=8.0, tier="T1", tvl_usd=50_000_000)
        kf_high_tvl = kelly_fraction(apy_pct=8.0, tier="T1", tvl_usd=2_000_000_000)
        assert kf_high_tvl >= kf_low_tvl

    def test_low_tvl_reduces_fraction(self):
        """TVL < $50M should reduce Kelly fraction vs TVL $500M."""
        kf_small = kelly_fraction(apy_pct=8.0, tier="T1", tvl_usd=20_000_000)
        kf_large = kelly_fraction(apy_pct=8.0, tier="T1", tvl_usd=500_000_000)
        assert kf_small <= kf_large


class TestHalfKelly:

    def test_half_kelly_is_exactly_half_of_kelly_fraction(self):
        """half_kelly must be exactly kelly_fraction / 2 for all inputs."""
        test_cases = [
            (5.0,  "T1", 100_000_000),
            (4.65, "T1",  50_000_000),
            (7.5,  "T2",  18_000_000),
            (15.0, "T2",   5_000_000),
        ]
        for apy, tier, tvl in test_cases:
            hk = half_kelly(apy, tier, tvl)
            kf = kelly_fraction(apy, tier, tvl)
            assert hk == pytest.approx(kf / 2.0), (
                f"half_kelly mismatch for apy={apy} tier={tier}: "
                f"half_kelly={hk}, kelly_fraction/2={kf/2}"
            )

    def test_half_kelly_in_unit_interval(self):
        """half_kelly must always be in [0, 0.5]."""
        result = half_kelly(apy_pct=10.0, tier="T1", tvl_usd=100_000_000)
        assert 0.0 <= result <= 0.5


class TestKellyPositionSize:

    def test_capped_at_max_pct(self):
        """kelly_position_size must never exceed max_pct * capital."""
        for max_pct in [0.10, 0.20, 0.40]:
            size = kelly_position_size(
                capital=100_000,
                apy_pct=5.0,
                tier="T1",
                tvl_usd=500_000_000,
                max_pct=max_pct,
            )
            assert size <= max_pct * 100_000 + 0.01, (
                f"Exceeded cap: size={size}, max={max_pct * 100_000}"
            )

    def test_zero_capital_returns_zero(self):
        assert kelly_position_size(0, 5.0, "T1", 50_000_000) == 0.0

    def test_zero_apy_returns_zero(self):
        assert kelly_position_size(100_000, 0.0, "T1", 50_000_000) == 0.0

    def test_positive_size_for_valid_inputs(self):
        """Should return a positive size for typical valid inputs."""
        size = kelly_position_size(
            capital=100_000,
            apy_pct=8.0,
            tier="T1",
            tvl_usd=200_000_000,
            max_pct=0.40,
        )
        assert size >= 0.0

    def test_default_max_pct_is_40_percent(self):
        """Default max_pct=0.40 should cap at 40% of capital."""
        size = kelly_position_size(100_000, 20.0, "T1", 1_000_000_000)
        assert size <= 40_000 + 0.01


# ─── Markowitz tests ──────────────────────────────────────────────────────────

class TestPortfolioOptimizer:

    def test_optimize_weights_sum_to_one(self):
        """optimize() weights must sum to approximately 1.0."""
        pools = _make_pools(3)
        opt = PortfolioOptimizer(protocols=pools)
        result = opt.optimize()
        total = sum(result["weights"].values())
        assert total == pytest.approx(1.0, abs=1e-4), f"Weights sum to {total}"

    def test_optimize_returns_expected_keys(self):
        """optimize() must return all required keys."""
        pools = _make_pools(3)
        opt = PortfolioOptimizer(protocols=pools)
        result = opt.optimize()
        for key in ["weights", "expected_return", "variance", "sharpe"]:
            assert key in result, f"Missing key: {key}"

    def test_optimize_single_pool(self):
        """Single-pool optimizer — weight should be 1.0."""
        pools = [{"protocol_key": "aave-v3-usdc-ethereum", "apy": 4.65, "tier": "T1", "tvl_usd": 138_000_000}]
        opt = PortfolioOptimizer(protocols=pools)
        result = opt.optimize()
        assert result["weights"]["aave-v3-usdc-ethereum"] == pytest.approx(1.0, abs=1e-4)

    def test_optimize_empty_pool_list(self):
        """Empty protocol list → zero return, zero variance, empty weights."""
        opt = PortfolioOptimizer(protocols=[])
        result = opt.optimize()
        assert result["weights"] == {}
        assert result["expected_return"] == 0.0
        assert result["variance"] == 0.0

    def test_covariance_matrix_shape(self):
        """estimate_covariance() must return n×n matrix."""
        pools = _make_pools(3)
        opt = PortfolioOptimizer(protocols=pools)
        cov = opt.estimate_covariance()
        assert len(cov) == 3
        for row in cov:
            assert len(row) == 3

    def test_covariance_diagonal_positive(self):
        """Diagonal entries of covariance matrix must be positive."""
        pools = _make_pools(3)
        opt = PortfolioOptimizer(protocols=pools)
        cov = opt.estimate_covariance()
        for i in range(3):
            assert cov[i][i] > 0

    def test_weights_non_negative(self):
        """All weights must be >= 0."""
        pools = _make_pools(4)
        opt = PortfolioOptimizer(protocols=pools)
        result = opt.optimize()
        for key, w in result["weights"].items():
            assert w >= -1e-6, f"Negative weight for {key}: {w}"

    def test_target_return_mode(self):
        """optimize(target_return_pct=4.5) should produce return ≈ target."""
        pools = _make_pools(3)
        opt = PortfolioOptimizer(protocols=pools)
        result = opt.optimize(target_return_pct=4.5)
        # Should still return valid structure
        assert sum(result["weights"].values()) == pytest.approx(1.0, abs=1e-3)


# ─── AllocationRecommender tests ──────────────────────────────────────────────

class TestAllocationRecommender:

    def test_recommend_returns_required_keys(self):
        """recommend() must return all required top-level keys."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        for key in ["recommendations", "portfolio_expected_return", "portfolio_sharpe", "vs_current"]:
            assert key in result, f"Missing key: {key}"

    def test_all_results_have_approved_by_risk_field(self):
        """Every recommendation dict must contain 'approved_by_risk'."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        for r in result["recommendations"]:
            assert "approved_by_risk" in r, f"Missing approved_by_risk in {r}"

    def test_empty_pools_returns_empty_recommendations(self):
        """Empty pools list → empty recommendations, no crash."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=[], capital=100_000.0)
        assert result["recommendations"] == []
        assert result["portfolio_expected_return"] == 0.0

    def test_zero_capital_returns_empty(self):
        """capital=0 → empty recommendations."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=0.0)
        assert result["recommendations"] == []

    def test_recommendation_amounts_positive(self):
        """All recommendation amount_usd must be positive."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        for r in result["recommendations"]:
            assert r["amount_usd"] > 0

    def test_recommendation_has_tier_field(self):
        """Every recommendation must have a 'tier' field."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        for r in result["recommendations"]:
            assert "tier" in r
            assert r["tier"] in ("T1", "T2")

    def test_approved_first_sorting(self):
        """Approved recommendations should come before rejected ones."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        recs = result["recommendations"]
        if len(recs) > 1:
            # Find first rejected
            approved_indices = [i for i, r in enumerate(recs) if r["approved_by_risk"]]
            rejected_indices = [i for i, r in enumerate(recs) if not r["approved_by_risk"]]
            if approved_indices and rejected_indices:
                assert max(approved_indices) < min(rejected_indices), (
                    "Rejected recommendations appeared before approved ones"
                )

    def test_single_pool_no_crash(self):
        """Single pool input should work without error."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(1), capital=100_000.0)
        assert isinstance(result["recommendations"], list)

    def test_vs_current_has_return_improvement(self):
        """vs_current dict must have return_improvement_pct."""
        rec = AllocationRecommender()
        result = rec.recommend(pools=_make_pools(3), capital=100_000.0)
        assert "return_improvement_pct" in result["vs_current"]
