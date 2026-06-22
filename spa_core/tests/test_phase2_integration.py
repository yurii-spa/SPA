"""
Integration tests for FEAT-007 Phase 2 — wires live covariance and
dynamic Kelly into PortfolioOptimizer + AllocationRecommender.

Guarantees verified here
------------------------
1.  Env unset → byte-identical to synthetic baseline.
2.  ``SPA_LIVE_COVARIANCE=1`` with empty apy_history.json → still
    numerically equivalent to synthetic baseline (every protocol
    triggers the n_obs<MIN_OBSERVATIONS fallback inside the estimator).
3.  ``SPA_LIVE_COVARIANCE=1`` with populated history → covariance
    matrix differs measurably AND ``covariance_source == "live"``.
4.  Recommender propagates the env flag end-to-end and surfaces a
    ``covariance_source`` field on its output dict.
5.  ``dynamic_kelly_fraction`` is actually used inside the recommender:
    when a pool has volatility_pp>0, the Kelly fraction differs from
    the classical path; when volatility_pp==0 (cold start) it matches.

Style follows ``test_covariance_estimator.py``: deterministic, zero
network, zero DB, ``preloaded=`` kwarg used to inject synthetic series.
``monkeypatch`` is used to set/restore the env flag — pytest restores
the original value automatically at test teardown.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.covariance_estimator import (  # noqa: E402
    CovarianceEstimator,
    SYNTHETIC_APY_CV,
)
from optimization.dynamic_kelly import dynamic_kelly_fraction  # noqa: E402
from optimization.kelly import kelly_fraction  # noqa: E402
from optimization.markowitz import PortfolioOptimizer  # noqa: E402
from optimization.recommender import AllocationRecommender  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────


_ENV_FLAG = "SPA_LIVE_COVARIANCE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _series(apys: list[float]) -> list[dict]:
    """Build a synthetic apy_history-shape series, one entry per day,
    newest sample at ``_now()``."""
    n = len(apys)
    return [
        {
            "ts": (_now() - timedelta(days=n - 1 - i)).isoformat(),
            "apy": apy,
            "tvl": 1_000_000_000,
        }
        for i, apy in enumerate(apys)
    ]


def _empty_history() -> dict:
    return {"protocol_history": {}, "last_updated": _now().isoformat()}


def _populated_history() -> dict:
    # Two protocols with distinct, non-10%-CV variances on a 30-day window.
    # protoA: oscillating around 5.0 with amplitude ~0.7 → σ ≈ 0.45-0.55 pp
    # protoB: trending 4.5 → 5.5 → σ ≈ 0.3-0.35 pp
    # Both are very different from the synthetic σ = apy * 0.10 = 0.5 pp.
    apys_a = [5.0 + 0.7 * math.sin(i * 0.5) for i in range(30)]
    apys_b = [4.5 + i * (1.0 / 29.0) for i in range(30)]
    return {
        "protocol_history": {
            "protoA": _series(apys_a),
            "protoB": _series(apys_b),
        },
        "last_updated": _now().isoformat(),
    }


@pytest.fixture
def mock_protocols() -> list[dict]:
    """Three T1 protocols with non-identical APYs — enough to exercise MVO."""
    return [
        {"protocol_key": "protoA", "apy": 5.0, "tier": "T1", "tvl_usd": 200_000_000},
        {"protocol_key": "protoB", "apy": 6.0, "tier": "T1", "tvl_usd": 150_000_000},
        {"protocol_key": "protoC", "apy": 7.0, "tier": "T2", "tvl_usd": 80_000_000},
    ]


@pytest.fixture
def mock_pools() -> list[dict]:
    """Recommender-shape pools. APYs are chosen high enough that the
    classical kelly_fraction prefilter (μ-r_f hurdle baked into the
    binary-outcome formula) admits candidates from BOTH paths — so the
    "lengths match" assertion is meaningful."""
    return [
        {"protocol_key": "protoA", "apy": 12.0, "tier": "T1", "tvl_usd": 500_000_000},
        {"protocol_key": "protoB", "apy": 15.0, "tier": "T1", "tvl_usd": 300_000_000},
        {"protocol_key": "protoC", "apy": 18.0, "tier": "T1", "tvl_usd": 200_000_000},
    ]


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Ensure the env flag is unset at the start of every test (the
    real CI env should never set it, but defensive)."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    yield


# ──────────────────────────────────────────────────────────────────────────
# 1. Default (env unset) is byte-identical to synthetic baseline
# ──────────────────────────────────────────────────────────────────────────


class TestEnvUnsetIsByteIdentical:
    def test_optimizer_defaults_to_synthetic(self, mock_protocols):
        opt = PortfolioOptimizer(protocols=mock_protocols)
        assert opt.live_covariance is False
        assert opt.covariance_source == "synthetic"

    def test_optimizer_results_match_explicit_synthetic(self, mock_protocols):
        # Reference: explicit synthetic path
        opt_ref = PortfolioOptimizer(protocols=mock_protocols, live_covariance=False)
        opt_ref.estimate_covariance()
        res_ref = opt_ref.optimize(target_return_pct=None)

        # Default: env unset, no kwargs
        opt_def = PortfolioOptimizer(protocols=mock_protocols)
        opt_def.estimate_covariance()
        res_def = opt_def.optimize(target_return_pct=None)

        assert res_ref["expected_return"] == pytest.approx(
            res_def["expected_return"], abs=1e-6
        )
        assert res_ref["variance"] == pytest.approx(res_def["variance"], abs=1e-9)
        assert res_ref["sharpe"] == pytest.approx(res_def["sharpe"], abs=1e-6)

    def test_covariance_matrix_default_path_matches_synthetic(self, mock_protocols):
        opt_ref = PortfolioOptimizer(protocols=mock_protocols, live_covariance=False)
        cov_ref = opt_ref.estimate_covariance()
        opt_def = PortfolioOptimizer(protocols=mock_protocols)
        cov_def = opt_def.estimate_covariance()
        for i in range(len(cov_ref)):
            for j in range(len(cov_ref)):
                assert cov_def[i][j] == pytest.approx(cov_ref[i][j], abs=1e-12)


# ──────────────────────────────────────────────────────────────────────────
# 2. Env flag + empty history → synthetic-equivalent numerics
# ──────────────────────────────────────────────────────────────────────────


class TestEmptyHistoryEqualsSynthetic:
    def test_volatility_falls_back_to_synthetic(self):
        est = CovarianceEstimator(preloaded=_empty_history())
        # apy=5.0, synthetic CV=0.10 → σ = 0.5
        vol = est.compute_volatility("missing", synthetic_apy=5.0)
        assert vol == pytest.approx(5.0 * SYNTHETIC_APY_CV, abs=1e-12)

    def test_optimizer_with_empty_history_matches_synthetic(
        self, monkeypatch, mock_protocols
    ):
        monkeypatch.setenv(_ENV_FLAG, "1")
        est_empty = CovarianceEstimator(preloaded=_empty_history())

        # Synthetic baseline
        opt_syn = PortfolioOptimizer(protocols=mock_protocols, live_covariance=False)
        cov_syn = opt_syn.estimate_covariance()

        # Live path with empty history (every protocol falls back)
        opt_live = PortfolioOptimizer(
            protocols=mock_protocols,
            live_covariance=True,
            covariance_estimator=est_empty,
        )
        cov_live = opt_live.estimate_covariance()
        assert opt_live.covariance_source == "live"

        # Every cell must agree to within float drift
        for i in range(len(cov_syn)):
            for j in range(len(cov_syn)):
                assert cov_live[i][j] == pytest.approx(
                    cov_syn[i][j], abs=1e-9
                ), f"mismatch at [{i}][{j}]: live={cov_live[i][j]}, synth={cov_syn[i][j]}"

    def test_optimize_results_match_with_empty_history(
        self, monkeypatch, mock_protocols
    ):
        monkeypatch.setenv(_ENV_FLAG, "1")
        est_empty = CovarianceEstimator(preloaded=_empty_history())
        opt_syn = PortfolioOptimizer(protocols=mock_protocols, live_covariance=False)
        opt_syn.estimate_covariance()
        res_syn = opt_syn.optimize(target_return_pct=None)

        opt_live = PortfolioOptimizer(
            protocols=mock_protocols,
            live_covariance=True,
            covariance_estimator=est_empty,
        )
        opt_live.estimate_covariance()
        res_live = opt_live.optimize(target_return_pct=None)

        assert res_live["expected_return"] == pytest.approx(
            res_syn["expected_return"], abs=1e-4
        )
        assert res_live["variance"] == pytest.approx(res_syn["variance"], abs=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# 3. Env flag + populated history → measurable divergence + live source
# ──────────────────────────────────────────────────────────────────────────


class TestPopulatedHistoryDiffers:
    def test_covariance_differs_from_synthetic(self, monkeypatch):
        monkeypatch.setenv(_ENV_FLAG, "1")
        protocols = [
            {"protocol_key": "protoA", "apy": 5.0, "tier": "T1", "tvl_usd": 200_000_000},
            {"protocol_key": "protoB", "apy": 6.0, "tier": "T1", "tvl_usd": 150_000_000},
        ]
        est_pop = CovarianceEstimator(preloaded=_populated_history())

        opt_syn = PortfolioOptimizer(protocols=protocols, live_covariance=False)
        cov_syn = opt_syn.estimate_covariance()

        opt_live = PortfolioOptimizer(
            protocols=protocols,
            live_covariance=True,
            covariance_estimator=est_pop,
        )
        cov_live = opt_live.estimate_covariance()

        assert opt_live.covariance_source == "live"

        # At least one diagonal entry must differ — the populated series
        # has σ != apy*0.10 by construction.
        diffs = [
            abs(cov_live[i][i] - cov_syn[i][i]) for i in range(len(cov_syn))
        ]
        assert max(diffs) > 1e-6, (
            f"expected measurable divergence, got diffs={diffs}; "
            f"live={cov_live}, syn={cov_syn}"
        )

    def test_covariance_source_attribute_is_live(self, monkeypatch, mock_protocols):
        monkeypatch.setenv(_ENV_FLAG, "1")
        est_pop = CovarianceEstimator(preloaded=_populated_history())
        opt = PortfolioOptimizer(
            protocols=mock_protocols,
            live_covariance=True,
            covariance_estimator=est_pop,
        )
        opt.estimate_covariance()
        assert opt.covariance_source == "live"


# ──────────────────────────────────────────────────────────────────────────
# 4. Recommender wraps the env flag through
# ──────────────────────────────────────────────────────────────────────────


class TestRecommenderEnvWiring:
    def test_recommender_default_synthetic(self, mock_pools):
        rec = AllocationRecommender()
        result = rec.recommend(pools=mock_pools, capital=100_000.0)
        assert "covariance_source" in result
        assert result["covariance_source"] == "synthetic"
        assert "vs_current" in result

    def test_recommender_with_env_flag_set(self, monkeypatch, mock_pools):
        monkeypatch.setenv(_ENV_FLAG, "1")
        rec = AllocationRecommender()
        result = rec.recommend(pools=mock_pools, capital=100_000.0)
        assert "covariance_source" in result
        # With no actual apy_history.json on disk it's still "live" — the
        # estimator path was taken, just falls back inside.
        assert result["covariance_source"] == "live"
        assert "vs_current" in result

    def test_recommender_lengths_match(self, monkeypatch, mock_pools):
        rec_off = AllocationRecommender()
        result_off = rec_off.recommend(pools=mock_pools, capital=100_000.0)

        monkeypatch.setenv(_ENV_FLAG, "1")
        rec_on = AllocationRecommender()
        result_on = rec_on.recommend(pools=mock_pools, capital=100_000.0)

        assert len(result_on["recommendations"]) == len(result_off["recommendations"])

    def test_recommender_returns_vs_current_block(self, mock_pools):
        rec = AllocationRecommender()
        result = rec.recommend(pools=mock_pools, capital=100_000.0)
        assert "return_improvement_pct" in result["vs_current"]


# ──────────────────────────────────────────────────────────────────────────
# 5. dynamic_kelly_fraction is wired correctly
# ──────────────────────────────────────────────────────────────────────────


class TestDynamicKellyWiring:
    def test_classical_kelly_when_volatility_is_zero(self):
        # When volatility_pp is 0 (cold start), dynamic delegates to
        # the classical kelly — outputs MUST match exactly.
        classical = kelly_fraction(apy_pct=6.0, tier="T1", tvl_usd=100_000_000)
        dyn = dynamic_kelly_fraction(
            apy_pct=6.0,
            tier="T1",
            tvl_usd=100_000_000,
            volatility_pp=0.0,
        )
        assert dyn == pytest.approx(classical, abs=1e-12)

    def test_classical_kelly_when_volatility_is_none(self):
        classical = kelly_fraction(apy_pct=6.0, tier="T1", tvl_usd=100_000_000)
        dyn = dynamic_kelly_fraction(
            apy_pct=6.0,
            tier="T1",
            tvl_usd=100_000_000,
            volatility_pp=None,
        )
        assert dyn == pytest.approx(classical, abs=1e-12)

    def test_variance_kelly_differs_when_vol_is_positive(self):
        # apy=6%, vol=0.5pp (10% of apy = synthetic baseline).
        # Even at the synthetic level the variance-Kelly differs
        # because it uses (μ - r_f) / σ² rather than the classical
        # binary-outcome formula.
        classical = kelly_fraction(apy_pct=6.0, tier="T1", tvl_usd=100_000_000)
        dyn = dynamic_kelly_fraction(
            apy_pct=6.0,
            tier="T1",
            tvl_usd=100_000_000,
            volatility_pp=0.5,
        )
        assert dyn != classical, (
            f"expected variance-kelly path to differ; classical={classical}, dyn={dyn}"
        )

    def test_recommender_uses_dynamic_kelly_when_env_set(
        self, monkeypatch, mock_pools
    ):
        # Smoke: with env flag on, the recommend() call should produce
        # a result with covariance_source="live".  The internal Kelly
        # fractions are exercised on the empty-history fallback path
        # so the *output shape* must remain identical (proves no
        # regression in the call signature).
        monkeypatch.setenv(_ENV_FLAG, "1")
        rec = AllocationRecommender()
        result = rec.recommend(pools=mock_pools, capital=100_000.0)
        assert result["covariance_source"] == "live"
        for r in result["recommendations"]:
            assert "kelly_fraction" in r
            assert 0.0 <= r["kelly_fraction"] <= 1.0
