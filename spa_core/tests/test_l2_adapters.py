"""Tests for L2 adapters and chain_limits (MP-203).

Covers:
  - AaveV3ArbitrumAdapter, AaveV3BaseAdapter, CompoundV3BaseAdapter,
    MorphoBlueBaseAdapter: instantiation, constants, fetch() with injected
    fake feeds, get_yield_info(), error paths.
  - spa_core.risk.chain_limits: check_chain_limits(), get_default_chain_map().

38 deterministic pure-Python tests. No network, no DB, no sleep.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import pytest

# Ensure the spa_core package root is on the path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.l2_adapters import (
    AaveV3ArbitrumAdapter,
    AaveV3BaseAdapter,
    CompoundV3BaseAdapter,
    MorphoBlueBaseAdapter,
    L2_ADAPTER_REGISTRY,
)
from spa_core.risk.chain_limits import check_chain_limits, get_default_chain_map


# ─── Fake feed helpers ────────────────────────────────────────────────────────

class _FakeFeedOk:
    """Injects fixed APY=0.05 (5%) and TVL=10_000_000."""

    def get_apy(self, project: str, symbol: str, chain: str = "Ethereum") -> float:
        return 0.05

    def get_tvl(self, project: str, symbol: str, chain: str = "Ethereum") -> float:
        return 10_000_000.0


class _FakeFeedNoneApy:
    """Returns None APY (feed unavailable scenario)."""

    def get_apy(self, project: str, symbol: str, chain: str = "Ethereum") -> None:
        return None

    def get_tvl(self, project: str, symbol: str, chain: str = "Ethereum") -> Optional[float]:
        return 5_000_000.0


class _FakeFeedRaises:
    """Simulates a network error by raising on any call."""

    def get_apy(self, project: str, symbol: str, chain: str = "Ethereum"):
        raise RuntimeError("simulated network error")

    def get_tvl(self, project: str, symbol: str, chain: str = "Ethereum"):
        raise RuntimeError("simulated network error")


# ─── 1. Adapter instantiation ─────────────────────────────────────────────────

class TestAdapterInstantiation:

    def test_aave_v3_arbitrum_creates_with_fake_feed(self):
        a = AaveV3ArbitrumAdapter(feed=_FakeFeedOk())
        assert a is not None

    def test_aave_v3_base_creates_with_fake_feed(self):
        a = AaveV3BaseAdapter(feed=_FakeFeedOk())
        assert a is not None

    def test_compound_v3_base_creates_with_fake_feed(self):
        a = CompoundV3BaseAdapter(feed=_FakeFeedOk())
        assert a is not None

    def test_morpho_blue_base_creates_with_fake_feed(self):
        a = MorphoBlueBaseAdapter(feed=_FakeFeedOk())
        assert a is not None


# ─── 2. Adapter class-level constants ─────────────────────────────────────────

class TestAdapterConstants:

    # DEFILLAMA_CHAIN
    def test_aave_v3_arbitrum_chain(self):
        assert AaveV3ArbitrumAdapter.DEFILLAMA_CHAIN == "Arbitrum"

    def test_aave_v3_base_chain(self):
        assert AaveV3BaseAdapter.DEFILLAMA_CHAIN == "Base"

    def test_compound_v3_base_chain(self):
        assert CompoundV3BaseAdapter.DEFILLAMA_CHAIN == "Base"

    def test_morpho_blue_base_chain(self):
        assert MorphoBlueBaseAdapter.DEFILLAMA_CHAIN == "Base"

    # TIER must be T2 for all L2 adapters
    def test_all_l2_adapters_are_t2(self):
        for cls in (AaveV3ArbitrumAdapter, AaveV3BaseAdapter,
                    CompoundV3BaseAdapter, MorphoBlueBaseAdapter):
            assert cls.TIER == "T2", f"{cls.__name__} should be T2"

    # T2_CAP
    def test_all_l2_t2_cap_is_020(self):
        for cls in (AaveV3ArbitrumAdapter, AaveV3BaseAdapter,
                    CompoundV3BaseAdapter, MorphoBlueBaseAdapter):
            assert cls.T2_CAP == 0.20, f"{cls.__name__} T2_CAP should be 0.20"

    # EXIT_LATENCY_HOURS
    def test_all_l2_exit_latency_zero(self):
        for cls in (AaveV3ArbitrumAdapter, AaveV3BaseAdapter,
                    CompoundV3BaseAdapter, MorphoBlueBaseAdapter):
            assert cls.EXIT_LATENCY_HOURS == 0.0, \
                f"{cls.__name__} EXIT_LATENCY_HOURS should be 0.0"

    # pool_id
    def test_aave_v3_arbitrum_pool_id(self):
        assert AaveV3ArbitrumAdapter.pool_id == "aave-v3-usdc-arbitrum"

    def test_aave_v3_base_pool_id(self):
        assert AaveV3BaseAdapter.pool_id == "aave-v3-usdc-base"

    def test_compound_v3_base_pool_id(self):
        assert CompoundV3BaseAdapter.pool_id == "compound-v3-usdc-base"

    def test_morpho_blue_base_pool_id(self):
        assert MorphoBlueBaseAdapter.pool_id == "morpho-blue-usdc-base"

    # L2_ADAPTER_REGISTRY
    def test_l2_registry_has_four_entries(self):
        assert len(L2_ADAPTER_REGISTRY) == 4

    def test_l2_registry_all_t2(self):
        for _, tier, _ in L2_ADAPTER_REGISTRY:
            assert tier == "T2"


# ─── 3. fetch() — required keys ───────────────────────────────────────────────

REQUIRED_KEYS = {"pool_id", "protocol", "tier", "chain", "apy", "tvl",
                 "status", "live_data", "source", "ts"}


class TestFetchReturnStructure:

    def _check_keys(self, adapter_cls):
        a = adapter_cls(feed=_FakeFeedOk())
        result = a.fetch()
        missing = REQUIRED_KEYS - result.keys()
        assert not missing, f"{adapter_cls.__name__}.fetch() missing keys: {missing}"

    def test_aave_v3_arbitrum_fetch_has_required_keys(self):
        self._check_keys(AaveV3ArbitrumAdapter)

    def test_aave_v3_base_fetch_has_required_keys(self):
        self._check_keys(AaveV3BaseAdapter)

    def test_compound_v3_base_fetch_has_required_keys(self):
        self._check_keys(CompoundV3BaseAdapter)

    def test_morpho_blue_base_fetch_has_required_keys(self):
        self._check_keys(MorphoBlueBaseAdapter)

    def test_fetch_chain_is_lowercase(self):
        a = AaveV3ArbitrumAdapter(feed=_FakeFeedOk())
        result = a.fetch()
        assert result["chain"] == "arbitrum"

    def test_fetch_base_chain_is_lowercase(self):
        a = AaveV3BaseAdapter(feed=_FakeFeedOk())
        result = a.fetch()
        assert result["chain"] == "base"


# ─── 4. fetch() — live feed OK ────────────────────────────────────────────────

class TestFetchLiveFeedOk:

    def _check_ok(self, adapter_cls):
        a = adapter_cls(feed=_FakeFeedOk())
        result = a.fetch()
        assert result["status"] == "ok"
        assert result["apy"] == pytest.approx(0.05)
        assert result["tvl"] == pytest.approx(10_000_000.0)
        assert result["live_data"] is True
        assert result["error"] is None

    def test_aave_v3_arbitrum_ok(self):
        self._check_ok(AaveV3ArbitrumAdapter)

    def test_aave_v3_base_ok(self):
        self._check_ok(AaveV3BaseAdapter)

    def test_compound_v3_base_ok(self):
        self._check_ok(CompoundV3BaseAdapter)

    def test_morpho_blue_base_ok(self):
        self._check_ok(MorphoBlueBaseAdapter)


# ─── 5. fetch() — error paths ─────────────────────────────────────────────────

class TestFetchErrorPaths:

    def test_feed_raises_returns_error_status(self):
        a = AaveV3ArbitrumAdapter(feed=_FakeFeedRaises())
        result = a.fetch()
        assert result["status"] == "error"
        assert result["apy"] is None
        assert result["live_data"] is False
        assert "RuntimeError" in result["error"]

    def test_feed_raises_base_returns_error_status(self):
        a = MorphoBlueBaseAdapter(feed=_FakeFeedRaises())
        result = a.fetch()
        assert result["status"] == "error"
        assert result["live_data"] is False

    def test_none_apy_returns_error_status(self):
        a = AaveV3BaseAdapter(feed=_FakeFeedNoneApy())
        result = a.fetch()
        assert result["status"] == "error"
        assert result["apy"] is None
        assert result["live_data"] is False

    def test_none_apy_still_populates_tvl(self):
        """TVL is populated even when APY is None (partial data is better than none)."""
        a = CompoundV3BaseAdapter(feed=_FakeFeedNoneApy())
        result = a.fetch()
        assert result["tvl"] == pytest.approx(5_000_000.0)

    def test_fetch_never_raises(self):
        a = AaveV3ArbitrumAdapter(feed=_FakeFeedRaises())
        # Must complete without raising.
        result = a.fetch()
        assert isinstance(result, dict)

    def test_ts_is_recent(self):
        a = AaveV3BaseAdapter(feed=_FakeFeedOk())
        before = time.time()
        result = a.fetch()
        after = time.time()
        assert before <= result["ts"] <= after


# ─── 6. get_yield_info() ──────────────────────────────────────────────────────

class TestGetYieldInfo:

    def _check(self, adapter_cls, expected_chain):
        a = adapter_cls(feed=_FakeFeedOk())
        yi = a.get_yield_info()
        assert yi.tier == "T2"
        assert yi.apy == pytest.approx(0.05)
        assert yi.tvl_usd == pytest.approx(10_000_000.0)
        assert yi.exit_latency_hours == 0.0

    def test_aave_v3_arbitrum_yield_info(self):
        self._check(AaveV3ArbitrumAdapter, "arbitrum")

    def test_aave_v3_base_yield_info(self):
        self._check(AaveV3BaseAdapter, "base")

    def test_compound_v3_base_yield_info(self):
        self._check(CompoundV3BaseAdapter, "base")

    def test_morpho_blue_base_yield_info(self):
        self._check(MorphoBlueBaseAdapter, "base")


# ─── 7. chain_limits — get_default_chain_map() ────────────────────────────────

class TestGetDefaultChainMap:

    def test_returns_dict(self):
        m = get_default_chain_map()
        assert isinstance(m, dict)

    def test_mainnet_adapters_are_ethereum(self):
        m = get_default_chain_map()
        for key in ("aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "euler_v2", "maple"):
            assert m.get(key) == "ethereum", f"{key} should map to ethereum"

    def test_l2_adapters_in_map(self):
        m = get_default_chain_map()
        assert m.get("aave_v3_arbitrum") == "arbitrum"
        assert m.get("aave_v3_base") == "base"
        assert m.get("compound_v3_base") == "base"
        assert m.get("morpho_blue_base") == "base"

    def test_map_has_at_least_10_entries(self):
        m = get_default_chain_map()
        assert len(m) >= 10


# ─── 8. chain_limits — check_chain_limits() ──────────────────────────────────

class TestCheckChainLimits:

    # ── clean portfolios pass ────────────────────────────────────────────────

    def test_empty_allocation_ok(self):
        result = check_chain_limits({})
        assert result["ok"] is True
        assert result["violations"] == []
        assert result["l2_total_pct"] == 0.0

    def test_pure_ethereum_portfolio_ok(self):
        # 0.40 + 0.15 + 0.10 = 0.65 on Ethereum — within 70% limit
        alloc = {"aave_v3": 0.40, "compound_v3": 0.15, "morpho_blue": 0.10}
        result = check_chain_limits(alloc)
        assert result["ok"] is True

    def test_ethereum_at_70pct_ok(self):
        # 70% on Ethereum — well within new 90% limit (MP-352)
        alloc = {"aave_v3": 0.40, "compound_v3": 0.30}
        result = check_chain_limits(alloc)
        assert result["ok"] is True
        assert result["chain_breakdown"]["ethereum"] == pytest.approx(0.70)

    def test_mixed_mainnet_and_l2_ok(self):
        alloc = {
            "aave_v3": 0.30,       # ethereum
            "compound_v3": 0.20,   # ethereum  → total ethereum = 0.50
            "aave_v3_arbitrum": 0.15,  # arbitrum
            "aave_v3_base": 0.15,      # base  → total L2 = 0.30
        }
        result = check_chain_limits(alloc)
        assert result["ok"] is True
        assert result["l2_total_pct"] == pytest.approx(0.30)

    # ── single-chain > 90% → violation (MP-352: threshold raised 70%→90%) ──────

    def test_ethereum_over_70pct_now_ok(self):
        """MP-352: 75% ethereum used to trigger violation at 70%, now OK at 90% limit."""
        alloc = {"aave_v3": 0.40, "compound_v3": 0.35}  # 75% ethereum
        result = check_chain_limits(alloc)
        # With new 90% limit, 75% is within bounds
        assert result["ok"] is True, (
            f"MP-352: 75% ethereum must be OK with new 90% limit. "
            f"Violations: {result['violations']}"
        )

    def test_ethereum_84pct_ok_mp352(self):
        """MP-352: 84% ethereum (max seen in logs) must NOT trigger violation."""
        alloc = {"aave_v3": 0.40, "compound_v3": 0.25, "morpho_blue": 0.19}
        result = check_chain_limits(alloc)
        assert result["ok"] is True

    def test_ethereum_over_90pct_violation(self):
        """MP-352: 91% ethereum must trigger violation with new 90% limit."""
        alloc = {"aave_v3": 0.50, "compound_v3": 0.41}  # 91% ethereum
        result = check_chain_limits(alloc)
        assert result["ok"] is False
        assert any("ethereum" in v.lower() for v in result["violations"])

    def test_single_chain_at_91pct_violation(self):
        """MP-352: 91% on any single chain → violation."""
        alloc = {"aave_v3": 0.91}
        result = check_chain_limits(alloc)
        assert result["ok"] is False

    def test_single_chain_at_90pct_ok(self):
        """MP-352: Exactly 90% on any single chain must pass (≤ not <)."""
        alloc = {"aave_v3": 0.90}
        result = check_chain_limits(alloc)
        assert result["ok"] is True

    # ── L2 combined > 50% → violation ───────────────────────────────────────

    def test_l2_over_50pct_violation(self):
        alloc = {
            "aave_v3_arbitrum": 0.30,  # arbitrum
            "aave_v3_base": 0.22,      # base → L2 total = 0.52
        }
        result = check_chain_limits(alloc)
        assert result["ok"] is False
        assert any("l2" in v.lower() for v in result["violations"])

    def test_l2_exactly_50pct_ok(self):
        alloc = {
            "aave_v3_arbitrum": 0.25,
            "aave_v3_base": 0.25,
        }
        result = check_chain_limits(alloc)
        assert result["ok"] is True
        assert result["l2_total_pct"] == pytest.approx(0.50)

    def test_l2_51pct_violation(self):
        alloc = {
            "aave_v3_arbitrum": 0.26,
            "aave_v3_base": 0.25,   # total = 0.51
        }
        result = check_chain_limits(alloc)
        assert result["ok"] is False

    # ── chain_breakdown ──────────────────────────────────────────────────────

    def test_chain_breakdown_correct(self):
        alloc = {"aave_v3": 0.40, "aave_v3_arbitrum": 0.20}
        result = check_chain_limits(alloc)
        assert result["chain_breakdown"]["ethereum"] == pytest.approx(0.40)
        assert result["chain_breakdown"]["arbitrum"] == pytest.approx(0.20)

    def test_unknown_protocol_assigned_to_unknown(self):
        alloc = {"some_new_protocol": 0.10}
        result = check_chain_limits(alloc)
        assert "unknown" in result["chain_breakdown"]
        assert result["chain_breakdown"]["unknown"] == pytest.approx(0.10)

    def test_custom_chain_map_used(self):
        custom_map = {"proto_x": "arbitrum", "proto_y": "arbitrum"}
        alloc = {"proto_x": 0.30, "proto_y": 0.25}  # L2 = 0.55 → violation
        result = check_chain_limits(alloc, chain_map=custom_map)
        assert result["ok"] is False
        assert result["l2_total_pct"] == pytest.approx(0.55)

    def test_negative_weights_ignored(self):
        alloc = {"aave_v3": 0.40, "morpho_blue": -0.10}
        result = check_chain_limits(alloc)
        assert result["chain_breakdown"]["ethereum"] == pytest.approx(0.40)

    def test_result_keys_present(self):
        result = check_chain_limits({})
        assert "ok" in result
        assert "violations" in result
        assert "l2_total_pct" in result
        assert "chain_breakdown" in result
