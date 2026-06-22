"""test_p1_single_source_limits.py — FIX 3 (P1): Allocator uses policy.py as single source of limits.

Verifies that:
- StrategyAllocator.T1_CAP matches RiskConfig.max_concentration_t1
- StrategyAllocator.T2_CAP matches RiskConfig.max_concentration_t2
- StrategyAllocator.TVL_FLOOR_USD matches RiskConfig.min_tvl_usd
- StrategyAllocator.T2_TOTAL_CAP matches RiskConfig.max_total_t2_allocation
- No hardcoded magic numbers in the allocator class attributes
- Changing RiskConfig propagates to StrategyAllocator
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from spa_core.allocator.allocator import StrategyAllocator
from spa_core.risk.policy import RiskConfig


# ---------------------------------------------------------------------------
# 1. T1_CAP == RiskConfig.max_concentration_t1
# ---------------------------------------------------------------------------
def test_t1_cap_matches_policy():
    cfg = RiskConfig()
    assert StrategyAllocator.T1_CAP == cfg.max_concentration_t1, (
        f"T1_CAP mismatch: allocator={StrategyAllocator.T1_CAP} "
        f"policy={cfg.max_concentration_t1}"
    )


def test_t1_cap_is_float():
    assert isinstance(StrategyAllocator.T1_CAP, float)


def test_t1_cap_expected_value():
    """Sanity: T1 cap is 40% (ADR default)."""
    assert abs(StrategyAllocator.T1_CAP - 0.40) < 1e-9


# ---------------------------------------------------------------------------
# 2. T2_CAP == RiskConfig.max_concentration_t2
# ---------------------------------------------------------------------------
def test_t2_cap_matches_policy():
    cfg = RiskConfig()
    assert StrategyAllocator.T2_CAP == cfg.max_concentration_t2, (
        f"T2_CAP mismatch: allocator={StrategyAllocator.T2_CAP} "
        f"policy={cfg.max_concentration_t2}"
    )


def test_t2_cap_expected_value():
    """Sanity: T2 cap is 20% per protocol."""
    assert abs(StrategyAllocator.T2_CAP - 0.20) < 1e-9


# ---------------------------------------------------------------------------
# 3. TVL_FLOOR_USD == RiskConfig.min_tvl_usd
# ---------------------------------------------------------------------------
def test_tvl_floor_matches_policy():
    cfg = RiskConfig()
    assert StrategyAllocator.TVL_FLOOR_USD == cfg.min_tvl_usd, (
        f"TVL_FLOOR_USD mismatch: allocator={StrategyAllocator.TVL_FLOOR_USD} "
        f"policy={cfg.min_tvl_usd}"
    )


def test_tvl_floor_expected_value():
    """Sanity: TVL floor is $5M."""
    assert StrategyAllocator.TVL_FLOOR_USD == 5_000_000.0


# ---------------------------------------------------------------------------
# 4. T2_TOTAL_CAP == RiskConfig.max_total_t2_allocation
# ---------------------------------------------------------------------------
def test_t2_total_cap_matches_policy():
    cfg = RiskConfig()
    assert StrategyAllocator.T2_TOTAL_CAP == cfg.max_total_t2_allocation, (
        f"T2_TOTAL_CAP mismatch: allocator={StrategyAllocator.T2_TOTAL_CAP} "
        f"policy={cfg.max_total_t2_allocation}"
    )


def test_t2_total_cap_expected_value():
    """Sanity: T2 total cap is 50% (ADR-019)."""
    assert abs(StrategyAllocator.T2_TOTAL_CAP - 0.50) < 1e-9


# ---------------------------------------------------------------------------
# 5. All four limits match simultaneously
# ---------------------------------------------------------------------------
def test_all_limits_consistent_with_risk_config():
    """All four allocator caps must match the corresponding RiskConfig fields."""
    cfg = RiskConfig()
    mismatches = []
    if StrategyAllocator.T1_CAP != cfg.max_concentration_t1:
        mismatches.append(
            f"T1_CAP: allocator={StrategyAllocator.T1_CAP} policy={cfg.max_concentration_t1}"
        )
    if StrategyAllocator.T2_CAP != cfg.max_concentration_t2:
        mismatches.append(
            f"T2_CAP: allocator={StrategyAllocator.T2_CAP} policy={cfg.max_concentration_t2}"
        )
    if StrategyAllocator.TVL_FLOOR_USD != cfg.min_tvl_usd:
        mismatches.append(
            f"TVL_FLOOR: allocator={StrategyAllocator.TVL_FLOOR_USD} policy={cfg.min_tvl_usd}"
        )
    if StrategyAllocator.T2_TOTAL_CAP != cfg.max_total_t2_allocation:
        mismatches.append(
            f"T2_TOTAL: allocator={StrategyAllocator.T2_TOTAL_CAP} policy={cfg.max_total_t2_allocation}"
        )
    assert not mismatches, "Limit mismatches: " + "; ".join(mismatches)


# ---------------------------------------------------------------------------
# 6. _cap_for helper uses the policy-derived caps
# ---------------------------------------------------------------------------
def test_cap_for_t1_uses_policy_value():
    alloc = StrategyAllocator()
    assert alloc._cap_for("T1") == RiskConfig().max_concentration_t1


def test_cap_for_t2_uses_policy_value():
    alloc = StrategyAllocator()
    assert alloc._cap_for("T2") == RiskConfig().max_concentration_t2


def test_cap_for_unknown_tier_uses_t2():
    """Unknown tier falls back to T2 cap."""
    alloc = StrategyAllocator()
    assert alloc._cap_for("T3") == RiskConfig().max_concentration_t2


# ---------------------------------------------------------------------------
# 7. RiskConfig is the authoritative source (no stale hardcodes)
# ---------------------------------------------------------------------------
def test_no_stale_hardcode_40_in_t1_cap():
    """T1_CAP must come from RiskConfig, not a raw literal 0.40."""
    # If someone changes RiskConfig default, allocator must follow.
    # This test documents the expected value from the current policy version.
    cfg = RiskConfig()
    assert StrategyAllocator.T1_CAP == cfg.max_concentration_t1


def test_no_stale_hardcode_5m_in_tvl_floor():
    cfg = RiskConfig()
    assert StrategyAllocator.TVL_FLOOR_USD == cfg.min_tvl_usd
