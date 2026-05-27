"""
Tests for spa_core.optimization.dynamic_kelly (FEAT-007 Phase 1).

The cardinal invariant being tested:
    When volatility_pp is None or <= 0, dynamic_* MUST return EXACTLY
    the same number as the classical kelly.* equivalents.

This guarantees Phase 1 is byte-identical for every existing caller.
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from optimization.kelly import (
    half_kelly,
    kelly_fraction,
    kelly_position_size,
)
from optimization.dynamic_kelly import (
    dynamic_half_kelly,
    dynamic_kelly_fraction,
    dynamic_position_size,
)


# ──────────────────────────────────────────────────────────────────────────
# Fallback parity — strict superset of the old API
# ──────────────────────────────────────────────────────────────────────────


class TestFallbackParity:
    @pytest.mark.parametrize("apy,tier,tvl", [
        (5.5, "T1", 5_000_000_000),
        (8.0, "T2", 100_000_000),
        (3.0, "T1", 2_000_000_000),
        (15.0, "T2", 30_000_000),  # low-TVL T2
        (0.5, "T1", 1_000_000_000),  # below T1 threshold
    ])
    def test_kelly_fraction_falls_through_when_vol_none(self, apy, tier, tvl):
        a = kelly_fraction(apy, tier, tvl)
        b = dynamic_kelly_fraction(apy, tier, tvl, volatility_pp=None)
        assert a == b

    @pytest.mark.parametrize("vol_pp", [0.0, -1.0, -100.0])
    def test_kelly_fraction_falls_through_when_vol_non_positive(self, vol_pp):
        a = kelly_fraction(5.5, "T1", 5_000_000_000)
        b = dynamic_kelly_fraction(
            5.5, "T1", 5_000_000_000, volatility_pp=vol_pp
        )
        assert a == b

    def test_half_kelly_parity(self):
        a = half_kelly(5.5, "T1", 5_000_000_000)
        b = dynamic_half_kelly(5.5, "T1", 5_000_000_000)
        assert a == b

    def test_position_size_parity(self):
        a = kelly_position_size(100_000, 5.5, "T1", 5_000_000_000)
        b = dynamic_position_size(100_000, 5.5, "T1", 5_000_000_000)
        assert a == b


# ──────────────────────────────────────────────────────────────────────────
# Variance-Kelly formula
# ──────────────────────────────────────────────────────────────────────────


class TestVarianceKelly:
    def test_known_value_aave_typical(self):
        # apy=7%, vol=1pp, rf=5%  →  excess=2pp=0.02, σ²=0.0001
        # f* = 0.02 / 0.0001 = 200 → clamped to 1.0
        f = dynamic_kelly_fraction(
            7.0, "T1", 5_000_000_000, volatility_pp=1.0
        )
        assert f == 1.0  # clamped

    def test_below_risk_free_returns_zero(self):
        # apy below rf=5% → excess negative → 0
        f = dynamic_kelly_fraction(
            3.0, "T1", 5_000_000_000, volatility_pp=2.0
        )
        assert f == 0.0

    def test_high_vol_low_apy_modest_allocation(self):
        # apy=6%, vol=10pp → excess=0.01, σ²=0.01 → f*=1.0 → clamped
        # apy=6%, vol=20pp → excess=0.01, σ²=0.04 → f*=0.25
        f = dynamic_kelly_fraction(
            6.0, "T1", 5_000_000_000, volatility_pp=20.0
        )
        assert abs(f - 0.25) < 1e-9

    def test_zero_volatility_falls_back_to_classical(self):
        # When volatility_pp=0, should behave like classical kelly_fraction
        # rather than divide-by-zero.
        a = dynamic_kelly_fraction(
            5.5, "T1", 5_000_000_000, volatility_pp=0.0
        )
        b = kelly_fraction(5.5, "T1", 5_000_000_000)
        assert a == b

    def test_clamped_to_unit_interval(self):
        # Result MUST be in [0, 1] regardless of inputs
        f = dynamic_kelly_fraction(
            50.0, "T1", 5_000_000_000, volatility_pp=0.1
        )
        assert 0.0 <= f <= 1.0

    def test_custom_risk_free_rate(self):
        # apy=7%, vol=5pp, rf=2%  →  excess=5pp=0.05, σ²=0.0025
        # f* = 0.05 / 0.0025 = 20 → clamped to 1.0
        f = dynamic_kelly_fraction(
            7.0, "T1", 5e9, volatility_pp=5.0, risk_free_rate_pct=2.0
        )
        assert f == 1.0

        # apy=7%, vol=5pp, rf=6%  →  excess=1pp=0.01
        # f* = 0.01 / 0.0025 = 4 → clamped to 1.0
        # Use vol=20pp instead to get a non-clamped value
        # apy=7%, vol=20pp, rf=6%  →  excess=0.01, σ²=0.04
        # f* = 0.01 / 0.04 = 0.25
        f = dynamic_kelly_fraction(
            7.0, "T1", 5e9, volatility_pp=20.0, risk_free_rate_pct=6.0
        )
        assert abs(f - 0.25) < 1e-9


# ──────────────────────────────────────────────────────────────────────────
# Position sizing — cap enforcement
# ──────────────────────────────────────────────────────────────────────────


class TestPositionSize:
    def test_cap_enforced_in_variance_path(self):
        # Without cap, f* would be > max_pct → cap should bite
        size = dynamic_position_size(
            100_000, 7.0, "T1", 5e9, volatility_pp=1.0, max_pct=0.10
        )
        assert size == pytest.approx(10_000.0)

    def test_zero_capital_returns_zero(self):
        size = dynamic_position_size(
            0, 7.0, "T1", 5e9, volatility_pp=1.0
        )
        assert size == 0.0

    def test_zero_apy_returns_zero(self):
        size = dynamic_position_size(
            100_000, 0.0, "T1", 5e9, volatility_pp=1.0
        )
        assert size == 0.0

    def test_half_kelly_is_actually_half(self):
        # half-kelly should be exactly f*/2 when f* is not clamped
        # apy=6%, vol=20pp, rf=5% → excess=0.01, σ²=0.04 → f* = 0.25
        f = dynamic_kelly_fraction(6.0, "T1", 5e9, volatility_pp=20.0)
        h = dynamic_half_kelly(6.0, "T1", 5e9, volatility_pp=20.0)
        assert abs(h - f / 2.0) < 1e-9
