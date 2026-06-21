#!/usr/bin/env python3
"""
Standalone тесты для Aerodrome (Base) / Velodrome (Optimism) AMM-адаптеров и
стратегии S41 Base+Op AMM Stable Yield (MP v12.51).

Покрывают:
  - AerodromeUsdcAdapter        (Aerodrome USDC-USDT stable LP, Base, T2) — НОВЫЙ
  - VelodromeOptimismAdapter    (Velodrome USDC-USDT stable LP, Optimism, T2) —
                                переиспользуется (уже существует, не дублируем)
  - S41AmmStableYield           (15% Aero + 10% Velo + 40% Aave + 30% Comp + 5% cash)
  - Registry wiring (адаптеры + стратегия)

Запуск:  python3 tests/test_aerodrome_velodrome.py
         python3 -m pytest tests/test_aerodrome_velodrome.py -v

Не требует pytest — использует только stdlib unittest. Все сетевые вызовы
замоканы; тесты детерминированы и оффлайн.
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.aerodrome_usdc_adapter import (
    APY_FALLBACK as AERO_FALLBACK,
    LP_TVL_FLOOR_USD as AERO_LP_FLOOR,
    AerodromeUsdcAdapter,
)
from spa_core.adapters.velodrome_optimism_adapter import (
    APY_FALLBACK as VELO_FALLBACK,
    VelodromeOptimismAdapter,
)
from spa_core.strategies.s41_amm_stable_yield import (
    FALLBACK_APY as S41_FALLBACK,
    WEIGHTS as S41_WEIGHTS,
    S41AmmStableYield,
)


# ---------------------------------------------------------------------------
# Helpers — мок DeFiLlama urlopen
# ---------------------------------------------------------------------------

def _defillama_bytes(pools: list) -> bytes:
    return json.dumps({"status": "success", "data": pools}).encode("utf-8")


class _FakeResponse:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _patch_pools(module_path: str, pools: list):
    return patch(
        f"{module_path}.urllib.request.urlopen",
        return_value=_FakeResponse(_defillama_bytes(pools)),
    )


def _patch_error(module_path: str, exc: Exception):
    return patch(
        f"{module_path}.urllib.request.urlopen",
        side_effect=exc,
    )


def _pool(project, symbol, chain, apy=5.0, tvl=50_000_000.0, pool_id="p"):
    return {
        "pool": pool_id,
        "project": project,
        "symbol": symbol,
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
    }


_AERO_MOD = "spa_core.adapters.aerodrome_usdc_adapter"
_VELO_MOD = "spa_core.adapters.velodrome_optimism_adapter"


# ===========================================================================
# Aerodrome Base (16 tests)
# ===========================================================================

class TestAerodromeBase(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = AerodromeUsdcAdapter()
        self.assertEqual(a.CHAIN, "base")
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")
        self.assertEqual(a.CHAIN_ID, 8453)

    def test_02_protocol_keys(self):
        a = AerodromeUsdcAdapter()
        self.assertEqual(a.PROTOCOL_ID, "aerodrome-base")
        self.assertEqual(a.PROTOCOL, "aerodrome_base")
        self.assertEqual(a.pool_id, "aerodrome-usdc-usdt-base")

    def test_03_tvl_above_floor(self):
        a = AerodromeUsdcAdapter()
        self.assertGreaterEqual(a.TVL_USD, 5_000_000)

    def test_04_risk_score_range(self):
        a = AerodromeUsdcAdapter()
        self.assertGreater(a.RISK_SCORE, 0.0)
        self.assertLessEqual(a.RISK_SCORE, 1.0)

    def test_05_fallback_is_conservative(self):
        # AERO награды волатильны → консервативный fallback 4.5%
        self.assertAlmostEqual(AERO_FALLBACK, 4.5, places=5)
        self.assertAlmostEqual(AerodromeUsdcAdapter().APY_FALLBACK, 4.5, places=5)

    def test_06_live_apy_stable_pair(self):
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-v2", "USDC-USDT", "Base", apy=8.19, tvl=2_000_000.0)]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 8.19, places=5)

    def test_07_matches_slipstream_project(self):
        # Реальный USDC-USDT пул живёт на aerodrome-slipstream — должен матчиться
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-slipstream", "USDC-USDT", "Base", apy=7.5, tvl=2e6)]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 7.5, places=5)

    def test_08_requires_both_stable_tokens(self):
        # Пул только с USDC (single asset / волатильная пара) не матчится
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-v2", "USDC-AERO", "Base", apy=30.0, tvl=9e8)]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), AERO_FALLBACK, places=5)

    def test_09_fallback_on_network_error(self):
        a = AerodromeUsdcAdapter()
        with _patch_error(_AERO_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), AERO_FALLBACK, places=5)

    def test_10_ignores_wrong_chain(self):
        a = AerodromeUsdcAdapter()
        pools = [
            _pool("aerodrome-v2", "USDC-USDT", "Optimism", apy=15.0, tvl=9e8),
            _pool("aerodrome-v2", "USDC-USDT", "Base", apy=4.2, tvl=2e6),
        ]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 4.2, places=5)

    def test_11_picks_highest_tvl(self):
        a = AerodromeUsdcAdapter()
        pools = [
            _pool("aerodrome-v2", "USDC-USDT", "Base", apy=3.0, tvl=600_000.0, pool_id="lo"),
            _pool("aerodrome-slipstream", "USDC-USDT", "Base", apy=8.0, tvl=2_000_000.0, pool_id="hi"),
        ]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 8.0, places=5)

    def test_12_ignores_anomalous_apy(self):
        # APY > _APY_MAX (50%) отбрасывается → fallback
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-v2", "USDC-USDT", "Base", apy=120.0, tvl=2e6)]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), AERO_FALLBACK, places=5)

    def test_13_ignores_thin_pool(self):
        # TVL ниже _MIN_POOL_TVL (500K) не считается живым → fallback
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-v2", "USDC-USDT", "Base", apy=9.0, tvl=100_000.0)]
        with _patch_pools(_AERO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), AERO_FALLBACK, places=5)

    def test_14_yield_info_decimal(self):
        a = AerodromeUsdcAdapter()
        pools = [_pool("aerodrome-v2", "USDC-USDT", "Base", apy=5.0, tvl=2e6)]
        with _patch_pools(_AERO_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.05, places=6)
        self.assertEqual(info.tier, "T2")
        self.assertEqual(info.protocol, "aerodrome_base")

    def test_15_is_lp_position(self):
        a = AerodromeUsdcAdapter()
        self.assertTrue(a.health_check()["is_lp_position"])
        self.assertTrue(a.to_dict()["is_lp_position"])

    def test_16_health_and_writestate(self):
        a = AerodromeUsdcAdapter()
        h = a.health_check()
        self.assertEqual(h["status"], "ok")
        self.assertTrue(h["tvl_floor_ok"])
        ws = a.get_write_state()
        self.assertEqual(ws["write_state"], "read_only")
        self.assertEqual(ws["chain"], "base")
        self.assertTrue(ws["is_lp_position"])

    # ── ADR-050: $20M LP depth floor + pool_depth_check ──────────────────

    def test_17_lp_tvl_floor_is_20m(self):
        # ADR-050: LP positions require a $20M floor (vs $5M for lending)
        self.assertEqual(AERO_LP_FLOOR, 20_000_000)
        self.assertEqual(AerodromeUsdcAdapter().LP_TVL_FLOOR_USD, 20_000_000)

    def test_18_thin_pool_flagged_below_floor(self):
        # $2M pool < $20M LP floor → THIN_POOL
        a = AerodromeUsdcAdapter()
        depth = a.pool_depth_check(2_000_000.0)
        self.assertTrue(depth["thin_pool"])
        self.assertEqual(depth["flag"], "THIN_POOL")
        self.assertIsNotNone(depth["warning"])
        self.assertIn("$20M depth floor", depth["warning"])
        self.assertIn("1% of TVL", depth["warning"])

    def test_19_thin_pool_caps_at_1pct_of_tvl(self):
        # At $2M TVL the 1% cap = $20k; equals max T2 position at $100k portfolio
        a = AerodromeUsdcAdapter()
        depth = a.pool_depth_check(2_000_000.0, portfolio_usd=100_000.0)
        self.assertAlmostEqual(depth["max_position_usd"], 20_000.0, places=2)
        self.assertAlmostEqual(depth["capped_position_usd"], 20_000.0, places=2)
        self.assertAlmostEqual(depth["max_pool_participation_pct"], 1.0, places=4)

    def test_20_thin_pool_market_moving_when_scaled(self):
        # At $1M portfolio, $200k in a $2M pool = 10% → still THIN_POOL, cap bites
        a = AerodromeUsdcAdapter()
        depth = a.pool_depth_check(2_000_000.0, portfolio_usd=1_000_000.0)
        self.assertTrue(depth["thin_pool"])
        self.assertAlmostEqual(depth["max_position_usd"], 200_000.0, places=2)
        # capped at 1% of $2M = $20k, far below the $200k naive max
        self.assertAlmostEqual(depth["capped_position_usd"], 20_000.0, places=2)

    def test_21_deep_pool_passes(self):
        # $50M pool ≥ $20M floor and ≥ 20× max position → OK
        a = AerodromeUsdcAdapter()
        depth = a.pool_depth_check(50_000_000.0)
        self.assertFalse(depth["thin_pool"])
        self.assertEqual(depth["flag"], "OK")
        self.assertIsNone(depth["warning"])

    def test_22_health_exposes_lp_floor(self):
        h = AerodromeUsdcAdapter().health_check()
        self.assertEqual(h["lp_tvl_floor_usd"], 20_000_000)
        # headline protocol TVL ($50M) clears the LP floor
        self.assertTrue(h["lp_tvl_floor_ok"])


# ===========================================================================
# Velodrome Optimism (reused adapter — 6 tests)
# ===========================================================================

class TestVelodromeReused(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = VelodromeOptimismAdapter()
        self.assertEqual(a.CHAIN, "optimism")
        self.assertEqual(a.TIER, "T2")

    def test_02_protocol_keys(self):
        a = VelodromeOptimismAdapter()
        self.assertEqual(a.PROTOCOL_ID, "velodrome-optimism")
        self.assertEqual(a.PROTOCOL, "velodrome_optimism")

    def test_03_live_apy_stable_pair(self):
        a = VelodromeOptimismAdapter()
        pools = [_pool("velodrome-v2", "USDC-USDT", "Optimism", apy=1.85)]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 1.85, places=5)

    def test_04_op_mainnet_label(self):
        # DeFiLlama иногда маркирует Optimism как "OP Mainnet"
        a = VelodromeOptimismAdapter()
        pools = [_pool("velodrome-v3", "USDC-USDT", "OP Mainnet", apy=2.1)]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 2.1, places=5)

    def test_05_fallback_on_error(self):
        a = VelodromeOptimismAdapter()
        with _patch_error(_VELO_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), VELO_FALLBACK, places=5)

    def test_06_is_lp_position(self):
        a = VelodromeOptimismAdapter()
        self.assertTrue(a.to_dict()["is_lp_position"])


# ===========================================================================
# S41 Base+Op AMM Stable Yield (9 tests)
# ===========================================================================

class TestS41AmmStableYield(unittest.TestCase):
    def test_01_identity(self):
        s = S41AmmStableYield()
        self.assertEqual(s.STRATEGY_ID, "S41")
        self.assertEqual(s.TIER, "T2")

    def test_02_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(S41_WEIGHTS.values()), 1.0, places=8)

    def test_03_allocation_matches_spec(self):
        s = S41AmmStableYield()
        alloc = s.get_allocation()
        self.assertAlmostEqual(alloc["aerodrome_base"], 0.15, places=8)
        self.assertAlmostEqual(alloc["velodrome_optimism"], 0.10, places=8)
        self.assertAlmostEqual(alloc["aave_v3"], 0.40, places=8)
        self.assertAlmostEqual(alloc["compound_v3"], 0.30, places=8)
        self.assertAlmostEqual(alloc["cash"], 0.05, places=8)

    def test_04_expected_apy_fallback(self):
        # 0.15*4.5 + 0.10*4.0 + 0.40*3.1 + 0.30*3.3 = 3.305
        s = S41AmmStableYield()
        self.assertAlmostEqual(s.get_expected_apy(), 3.305, places=3)

    def test_05_expected_apy_with_live_emissions(self):
        # AERO/VELO upside поднимает blended APY
        s = S41AmmStableYield()
        apy_map = {"aerodrome_base": 8.0, "velodrome_optimism": 6.0}
        # 0.15*8 + 0.10*6 + 0.40*3.1 + 0.30*3.3 = 1.2+0.6+1.24+0.99 = 4.03
        self.assertAlmostEqual(s.get_expected_apy(apy_map=apy_map), 4.03, places=3)

    def test_06_risk_summary_tier_split(self):
        s = S41AmmStableYield()
        rs = s.get_risk_summary()
        self.assertAlmostEqual(rs["t1_weight_pct"], 70.0, places=2)
        self.assertAlmostEqual(rs["t2_weight_pct"], 25.0, places=2)
        self.assertAlmostEqual(rs["cash_weight_pct"], 5.0, places=2)

    def test_07_t2_within_policy_caps(self):
        # T2 total ≤ 50% (ADR-019); каждый T2 protocol ≤ 20%
        s = S41AmmStableYield()
        alloc = s.get_allocation()
        t2 = alloc["aerodrome_base"] + alloc["velodrome_optimism"]
        self.assertLessEqual(t2, 0.50)
        self.assertLessEqual(alloc["aerodrome_base"], 0.20)
        self.assertLessEqual(alloc["velodrome_optimism"], 0.20)

    def test_08_simulate_positions(self):
        s = S41AmmStableYield()
        sim = s.simulate(100_000.0)
        self.assertEqual(sim["status"], "ok")
        self.assertAlmostEqual(sim["allocation"]["aerodrome_base"], 15_000.0, places=2)
        self.assertAlmostEqual(sim["allocation"]["velodrome_optimism"], 10_000.0, places=2)
        self.assertAlmostEqual(
            sim["expected_annual_yield_usd"], 100_000.0 * 3.305 / 100.0, places=2
        )

    def test_09_suspended_renormalizes(self):
        # Если Velodrome suspended — веса перенормируются к 1.0
        s = S41AmmStableYield()
        alloc = s.get_allocation(suspended={"velodrome_optimism"})
        self.assertNotIn("velodrome_optimism", alloc)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=8)
        self.assertIn("cash", alloc)

    def test_10_thin_pool_reduces_aerodrome(self):
        # ADR-050: pool TVL < $20M → Aerodrome sleeve cut 15% → 5%, renorm to 1.0
        s = S41AmmStableYield()
        alloc = s.get_allocation(aerodrome_tvl_usd=2_000_000.0)
        # raw weight pre-renorm: aero 0.05, others 0.10/0.40/0.30/0.05 sum=0.90
        self.assertAlmostEqual(alloc["aerodrome_base"], 0.05 / 0.90, places=6)
        self.assertLess(alloc["aerodrome_base"], 0.15)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=8)

    def test_11_deep_pool_keeps_full_aerodrome(self):
        # Pool ≥ $20M → full 15% spec weight retained
        s = S41AmmStableYield()
        alloc = s.get_allocation(aerodrome_tvl_usd=50_000_000.0)
        self.assertAlmostEqual(alloc["aerodrome_base"], 0.15, places=8)
        # no TVL supplied → back-compat static weight
        self.assertAlmostEqual(
            s.get_allocation()["aerodrome_base"], 0.15, places=8
        )


# ===========================================================================
# Registry wiring (4 tests)
# ===========================================================================

class TestRegistryWiring(unittest.TestCase):
    def test_01_aerodrome_registered(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, _, _ in ADAPTER_REGISTRY]
        self.assertIn("aerodrome_base", keys)
        self.assertIn("velodrome_optimism", keys)

    def test_02_aerodrome_is_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, _ in ADAPTER_REGISTRY:
            if key in ("aerodrome_base", "velodrome_optimism"):
                self.assertEqual(tier, "T2", f"{key} tier mismatch")

    def test_03_aerodrome_in_multichain_dict(self):
        from spa_core.adapters import MULTICHAIN_L2_ADAPTERS
        self.assertIn("aerodrome-base", MULTICHAIN_L2_ADAPTERS)
        self.assertIn("velodrome-optimism", MULTICHAIN_L2_ADAPTERS)

    def test_04_s41_registered(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S41")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")
        self.assertEqual(meta.type, "lp")
        self.assertEqual(meta.handler_class, "S41AmmStableYield")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestAerodromeBase,
        TestVelodromeReused,
        TestS41AmmStableYield,
        TestRegistryWiring,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*60}\nAerodrome/Velodrome + S41: {passed}/{total} тестов прошло")
    sys.exit(0 if not (result.failures or result.errors) else 1)
