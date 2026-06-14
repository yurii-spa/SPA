"""
Tests for spa_core.analytics.covariance_estimator (FEAT-007 Phase 1).

Deterministic, zero-network, zero-DB.  Every test constructs the
estimator with a hand-crafted ``preloaded`` payload so disk I/O is never
exercised in CI.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.covariance_estimator import (
    CovarianceEstimator,
    DEFAULT_WINDOW_DAYS,
    MIN_OBSERVATIONS,
    SYNTHETIC_APY_CV,
    SYNTHETIC_CROSS_TIER_CORR,
    SYNTHETIC_SAME_TIER_CORR,
    _parse_iso,
    _safe_pearson,
    _safe_stdev,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers — fixture builders
# ──────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _series(apys: list[float], *, days_back_start: int = None) -> list[dict]:
    """
    Build an APYTracker-shape series ending NOW.

    ``apys[0]`` is the OLDEST observation; ``apys[-1]`` is the most
    recent.  Spacing is 1 day between samples.  ``days_back_start``, if
    supplied, overrides the offset of the FIRST sample (otherwise
    derived from len(apys)).
    """
    n = len(apys)
    start_back = days_back_start if days_back_start is not None else n - 1
    out = []
    for i, apy in enumerate(apys):
        ts = _now() - timedelta(days=start_back - i)
        out.append({"ts": ts.isoformat(), "apy": apy, "tvl": 1_000_000_000})
    return out


def _payload(protocols: dict[str, list[dict]]) -> dict:
    """Wrap a dict of {protocol_key: series} in the APYTracker schema."""
    return {
        "protocol_history": protocols,
        "last_updated": _now().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────
# _parse_iso
# ──────────────────────────────────────────────────────────────────────────


class TestParseIso:
    def test_valid_utc_with_offset(self):
        dt = _parse_iso("2026-05-27T12:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_z_suffix_normalised(self):
        # APYTracker writes "...+00:00" but be defensive about Z-suffix
        dt = _parse_iso("2026-05-27T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_garbage_returns_none(self):
        assert _parse_iso("not-a-date") is None
        assert _parse_iso("") is None

    def test_non_string_returns_none(self):
        assert _parse_iso(123) is None  # type: ignore[arg-type]
        assert _parse_iso(None) is None  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# _safe_stdev / _safe_pearson
# ──────────────────────────────────────────────────────────────────────────


class TestSafeStats:
    def test_stdev_empty_returns_zero(self):
        assert _safe_stdev([]) == 0.0

    def test_stdev_single_returns_zero(self):
        assert _safe_stdev([4.0]) == 0.0

    def test_stdev_normal_case(self):
        # Sample stdev (Bessel) of [4, 5, 6] is 1.0 exactly
        assert abs(_safe_stdev([4.0, 5.0, 6.0]) - 1.0) < 1e-9

    def test_pearson_perfect_positive(self):
        # n=7 to meet MIN_OBSERVATIONS gate
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]
        assert abs(_safe_pearson(xs, ys) - 1.0) < 1e-9

    def test_pearson_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        ys = [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        assert abs(_safe_pearson(xs, ys) - (-1.0)) < 1e-9

    def test_pearson_too_few_observations(self):
        # MIN_OBSERVATIONS = 7
        xs = [1.0, 2.0, 3.0]
        ys = [4.0, 5.0, 6.0]
        assert _safe_pearson(xs, ys) == 0.0

    def test_pearson_constant_series_returns_zero(self):
        xs = [5.0] * 10
        ys = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _safe_pearson(xs, ys) == 0.0


# ──────────────────────────────────────────────────────────────────────────
# CovarianceEstimator — protocols() / cold-start
# ──────────────────────────────────────────────────────────────────────────


class TestEstimatorProtocols:
    def test_empty_store_returns_empty_protocols(self):
        est = CovarianceEstimator(preloaded={"protocol_history": {}})
        assert est.protocols() == []

    def test_missing_file_treated_as_empty(self, tmp_path):
        est = CovarianceEstimator(history_file=str(tmp_path / "nonexistent.json"))
        assert est.protocols() == []

    def test_sorted_protocol_keys(self):
        payload = _payload({
            "aave:USDC": _series([4.0] * 10),
            "compound:USDC": _series([3.5] * 10),
            "morpho:USDC": _series([4.2] * 10),
        })
        est = CovarianceEstimator(preloaded=payload)
        assert est.protocols() == ["aave:USDC", "compound:USDC", "morpho:USDC"]


# ──────────────────────────────────────────────────────────────────────────
# compute_volatility — live + fallback
# ──────────────────────────────────────────────────────────────────────────


class TestVolatility:
    def test_live_estimate_when_enough_data(self):
        # 10 observations, deterministic variance — stdev of [4,5,6,4,5,6,4,5,6,4]
        apys = [4.0, 5.0, 6.0, 4.0, 5.0, 6.0, 4.0, 5.0, 6.0, 4.0]
        payload = _payload({"aave:USDC": _series(apys)})
        est = CovarianceEstimator(preloaded=payload)
        vol = est.compute_volatility("aave:USDC")
        # statistics.stdev(apys) ≈ 0.8755
        assert 0.85 < vol < 0.90

    def test_fallback_when_insufficient_data(self):
        apys = [4.0, 5.0, 6.0]  # only 3 observations, below MIN_OBSERVATIONS=7
        payload = _payload({"aave:USDC": _series(apys)})
        est = CovarianceEstimator(preloaded=payload)
        vol = est.compute_volatility("aave:USDC", synthetic_apy=5.0)
        # synthetic = 5.0 * 0.10 = 0.5
        assert abs(vol - 0.5) < 1e-9

    def test_fallback_without_synthetic_apy_returns_zero(self):
        payload = _payload({"aave:USDC": _series([4.0, 5.0])})  # < MIN_OBSERVATIONS
        est = CovarianceEstimator(preloaded=payload)
        assert est.compute_volatility("aave:USDC") == 0.0

    def test_unknown_protocol_returns_zero(self):
        est = CovarianceEstimator(preloaded={"protocol_history": {}})
        assert est.compute_volatility("nonexistent") == 0.0

    def test_window_filters_out_old_entries(self):
        # 10 fresh days + 1 very old observation (180 days back)
        fresh = _series([5.0] * 10)
        old_ts = _now() - timedelta(days=180)
        ancient = {"ts": old_ts.isoformat(), "apy": 999.0, "tvl": 0}
        payload = _payload({"aave:USDC": [ancient] + fresh})
        est = CovarianceEstimator(preloaded=payload)
        vol = est.compute_volatility("aave:USDC", window_days=30)
        # The ancient outlier must NOT be in the window — stdev of [5]*10 = 0
        assert vol == 0.0


# ──────────────────────────────────────────────────────────────────────────
# compute_correlation — live + fallback
# ──────────────────────────────────────────────────────────────────────────


class TestCorrelation:
    def test_self_correlation_always_one(self):
        payload = _payload({"aave:USDC": _series([5.0] * 10)})
        est = CovarianceEstimator(preloaded=payload)
        assert est.compute_correlation("aave:USDC", "aave:USDC") == 1.0

    def test_perfect_positive_correlation(self):
        # Same series for both protocols, scaled by 2
        ts_now = _now()
        series_a = []
        series_b = []
        for i in range(10):
            ts = (ts_now - timedelta(days=10 - i)).isoformat()
            series_a.append({"ts": ts, "apy": 4.0 + i * 0.1, "tvl": 1e9})
            series_b.append({"ts": ts, "apy": 8.0 + i * 0.2, "tvl": 1e9})
        payload = _payload({"a": series_a, "b": series_b})
        est = CovarianceEstimator(preloaded=payload)
        rho = est.compute_correlation("a", "b")
        assert abs(rho - 1.0) < 1e-9

    def test_perfect_negative_correlation(self):
        ts_now = _now()
        series_a = []
        series_b = []
        for i in range(10):
            ts = (ts_now - timedelta(days=10 - i)).isoformat()
            series_a.append({"ts": ts, "apy": 4.0 + i * 0.1, "tvl": 1e9})
            series_b.append({"ts": ts, "apy": 10.0 - i * 0.1, "tvl": 1e9})
        payload = _payload({"a": series_a, "b": series_b})
        est = CovarianceEstimator(preloaded=payload)
        rho = est.compute_correlation("a", "b")
        assert abs(rho - (-1.0)) < 1e-9

    def test_no_overlap_falls_back_to_same_tier(self):
        # Series A in 2026-04, series B in 2026-05 — no shared timestamps
        ts_now = _now()
        far_back = ts_now - timedelta(days=60)
        series_a = [
            {"ts": (far_back - timedelta(days=i)).isoformat(), "apy": 5.0, "tvl": 1e9}
            for i in range(10)
        ]
        series_b = [
            {"ts": (ts_now - timedelta(days=i)).isoformat(), "apy": 6.0, "tvl": 1e9}
            for i in range(10)
        ]
        payload = _payload({"a": series_a, "b": series_b})
        est = CovarianceEstimator(preloaded=payload)
        rho = est.compute_correlation("a", "b", window_days=30, same_tier=True)
        assert rho == SYNTHETIC_SAME_TIER_CORR

    def test_no_overlap_falls_back_to_cross_tier(self):
        payload = _payload({"a": [], "b": []})
        est = CovarianceEstimator(preloaded=payload)
        rho = est.compute_correlation("a", "b", same_tier=False)
        assert rho == SYNTHETIC_CROSS_TIER_CORR

    def test_no_overlap_no_tier_hint_returns_zero(self):
        payload = _payload({"a": [], "b": []})
        est = CovarianceEstimator(preloaded=payload)
        assert est.compute_correlation("a", "b") == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Matrix shapes
# ──────────────────────────────────────────────────────────────────────────


class TestMatrices:
    def _three_protocol_payload(self):
        ts_now = _now()
        out = {}
        for proto, base in [("aave:USDC", 4.0), ("compound:USDC", 4.2), ("morpho:USDC", 4.5)]:
            out[proto] = [
                {"ts": (ts_now - timedelta(days=10 - i)).isoformat(),
                 "apy": base + 0.05 * i, "tvl": 1e9}
                for i in range(10)
            ]
        return _payload(out)

    def test_covariance_matrix_is_symmetric(self):
        est = CovarianceEstimator(preloaded=self._three_protocol_payload())
        cov = est.compute_covariance_matrix(window_days=30)
        keys = list(cov.keys())
        for i, k_i in enumerate(keys):
            for j, k_j in enumerate(keys):
                assert abs(cov[k_i][k_j] - cov[k_j][k_i]) < 1e-12, \
                    f"Not symmetric at ({k_i}, {k_j})"

    def test_correlation_matrix_diagonal_one(self):
        est = CovarianceEstimator(preloaded=self._three_protocol_payload())
        corr = est.compute_correlation_matrix(window_days=30)
        for k in corr:
            assert corr[k][k] == 1.0

    def test_covariance_diagonal_is_variance(self):
        est = CovarianceEstimator(preloaded=self._three_protocol_payload())
        cov = est.compute_covariance_matrix(window_days=30)
        for k in cov:
            sigma = est.compute_volatility(k, window_days=30)
            assert abs(cov[k][k] - sigma * sigma) < 1e-12

    def test_protocols_subset_filter(self):
        est = CovarianceEstimator(preloaded=self._three_protocol_payload())
        cov = est.compute_covariance_matrix(
            window_days=30, protocols=["aave:USDC", "morpho:USDC"]
        )
        assert set(cov.keys()) == {"aave:USDC", "morpho:USDC"}
        for k in cov:
            assert set(cov[k].keys()) == {"aave:USDC", "morpho:USDC"}


# ──────────────────────────────────────────────────────────────────────────
# summary() — JSON export shape
# ──────────────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_marks_fallback_for_thin_data(self):
        payload = _payload({"a": _series([5.0, 5.1])})  # 2 obs < MIN
        est = CovarianceEstimator(preloaded=payload)
        s = est.summary()
        assert s["protocols"]["a"]["fallback"] is True
        assert s["protocols"]["a"]["n_obs"] == 2

    def test_summary_no_fallback_when_enough_data(self):
        payload = _payload({"a": _series([5.0 + i * 0.01 for i in range(15)])})
        est = CovarianceEstimator(preloaded=payload)
        s = est.summary()
        assert s["protocols"]["a"]["fallback"] is False
        assert s["protocols"]["a"]["n_obs"] == 15
        assert s["protocols"]["a"]["volatility_pp"] > 0

    def test_summary_top_level_metadata(self):
        est = CovarianceEstimator(preloaded={"protocol_history": {}})
        s = est.summary(window_days=60)
        assert s["window_days"] == 60
        assert s["min_observations"] == MIN_OBSERVATIONS
        assert "computed_at" in s
        assert s["protocols"] == {}
