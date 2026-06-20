#!/usr/bin/env python3
"""
Standalone тесты для multichain expansion (Arbitrum / Optimism).

Покрывают новые read-only адаптеры и газовые мониторы:
  - RadiantArbitrumAdapter        (Radiant Capital USDC, Arbitrum, T2)
  - GmxGlpArbitrumAdapter         (GMX GLP, Arbitrum, T2)
  - VelodromeOptimismAdapter      (Velodrome USDC-USDT, Optimism, T2)
  - ArbitrumGasMonitor / OptimismGasMonitor (advisory gas kill-switch)

Запуск:  python3 tests/test_multichain_adapters.py
         python3 -m pytest tests/test_multichain_adapters.py -v

Не требует pytest — использует только stdlib unittest. Все сетевые вызовы
замоканы; тесты детерминированы и оффлайн.
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.radiant_arbitrum_adapter import (
    APY_FALLBACK as RADIANT_FALLBACK,
    RadiantArbitrumAdapter,
)
from spa_core.adapters.gmx_glp_arbitrum_adapter import (
    APY_FALLBACK as GMX_FALLBACK,
    GmxGlpArbitrumAdapter,
)
from spa_core.adapters.velodrome_optimism_adapter import (
    APY_FALLBACK as VELO_FALLBACK,
    VelodromeOptimismAdapter,
)
from spa_core.monitoring.arbitrum_gas_monitor import (
    ARBITRUM_GAS_KILL_DAYS,
    ARBITRUM_GAS_THRESHOLD_GWEI,
    ArbitrumGasMonitor,
)
from spa_core.monitoring.optimism_gas_monitor import (
    OPTIMISM_GAS_KILL_DAYS,
    OPTIMISM_GAS_THRESHOLD_GWEI,
    OptimismGasMonitor,
)


# ---------------------------------------------------------------------------
# Helpers — мок DeFiLlama urlopen
# ---------------------------------------------------------------------------

def _defillama_bytes(pools: list[dict]) -> bytes:
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


def _patch_pools(module_path: str, pools: list[dict]):
    """Патчит urlopen в модуле адаптера, возвращая указанные пулы."""
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


_RADIANT_MOD = "spa_core.adapters.radiant_arbitrum_adapter"
_GMX_MOD = "spa_core.adapters.gmx_glp_arbitrum_adapter"
_VELO_MOD = "spa_core.adapters.velodrome_optimism_adapter"


# ===========================================================================
# Radiant Arbitrum (10 tests)
# ===========================================================================

class TestRadiantArbitrum(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = RadiantArbitrumAdapter()
        self.assertEqual(a.CHAIN, "arbitrum")
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")

    def test_02_protocol_keys(self):
        a = RadiantArbitrumAdapter()
        self.assertEqual(a.PROTOCOL_ID, "radiant-arbitrum")
        self.assertEqual(a.PROTOCOL, "radiant_arbitrum")
        self.assertEqual(a.CHAIN_ID, 42161)

    def test_03_tvl_above_floor(self):
        a = RadiantArbitrumAdapter()
        self.assertGreaterEqual(a.TVL_USD, 5_000_000)

    def test_04_risk_score_range(self):
        a = RadiantArbitrumAdapter()
        self.assertGreater(a.RISK_SCORE, 0.0)
        self.assertLessEqual(a.RISK_SCORE, 1.0)

    def test_05_live_apy(self):
        a = RadiantArbitrumAdapter()
        pools = [_pool("radiant-v2", "USDC", "Arbitrum", apy=6.3)]
        with _patch_pools(_RADIANT_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 6.3, places=5)

    def test_06_fallback_on_network_error(self):
        a = RadiantArbitrumAdapter()
        with _patch_error(_RADIANT_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), RADIANT_FALLBACK, places=5)

    def test_07_ignores_wrong_chain(self):
        a = RadiantArbitrumAdapter()
        pools = [
            _pool("radiant-v2", "USDC", "Ethereum", apy=9.9, tvl=9e8),
            _pool("radiant-v2", "USDC", "Arbitrum", apy=4.7),
        ]
        with _patch_pools(_RADIANT_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 4.7, places=5)

    def test_08_ignores_non_usdc(self):
        a = RadiantArbitrumAdapter()
        pools = [_pool("radiant-v2", "WETH", "Arbitrum", apy=12.0, tvl=9e8)]
        with _patch_pools(_RADIANT_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), RADIANT_FALLBACK, places=5)

    def test_09_yield_info_decimal(self):
        a = RadiantArbitrumAdapter()
        pools = [_pool("radiant-v2", "USDC", "Arbitrum", apy=5.0)]
        with _patch_pools(_RADIANT_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.05, places=6)
        self.assertEqual(info.tier, "T2")
        self.assertEqual(info.protocol, "radiant_arbitrum")

    def test_10_health_and_writestate(self):
        a = RadiantArbitrumAdapter()
        h = a.health_check()
        self.assertEqual(h["status"], "ok")
        self.assertTrue(h["tvl_floor_ok"])
        ws = a.get_write_state()
        self.assertEqual(ws["write_state"], "read_only")
        self.assertEqual(ws["chain"], "arbitrum")


# ===========================================================================
# GMX GLP Arbitrum (10 tests)
# ===========================================================================

class TestGmxGlpArbitrum(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = GmxGlpArbitrumAdapter()
        self.assertEqual(a.CHAIN, "arbitrum")
        self.assertEqual(a.TIER, "T2")

    def test_02_protocol_keys(self):
        a = GmxGlpArbitrumAdapter()
        self.assertEqual(a.PROTOCOL_ID, "gmx-glp-arbitrum")
        self.assertEqual(a.PROTOCOL, "gmx_glp_arbitrum")

    def test_03_not_pure_stablecoin(self):
        a = GmxGlpArbitrumAdapter()
        self.assertFalse(a.health_check()["is_pure_stablecoin"])
        self.assertFalse(a.to_dict()["is_pure_stablecoin"])

    def test_04_higher_risk_than_lending(self):
        # GLP несёт рыночную экспозицию → risk_score выше lending-T2 (Radiant 0.45)
        self.assertGreater(GmxGlpArbitrumAdapter().RISK_SCORE, 0.45)

    def test_05_live_apy_from_defillama(self):
        a = GmxGlpArbitrumAdapter()
        pools = [_pool("gmx-v1", "GLP", "Arbitrum", apy=11.2, tvl=4e8)]
        with _patch_pools(_GMX_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 11.2, places=5)

    def test_06_fallback_on_error(self):
        a = GmxGlpArbitrumAdapter()
        with _patch_error(_GMX_MOD, urllib.error.URLError("down")):
            # GMX-API path тоже бьётся той же мок-ошибкой → fallback
            self.assertAlmostEqual(a.get_apy(), GMX_FALLBACK, places=5)

    def test_07_ignores_non_glp_symbol(self):
        a = GmxGlpArbitrumAdapter()
        pools = [_pool("gmx-v1", "USDC", "Arbitrum", apy=3.0, tvl=9e8)]
        with _patch_pools(_GMX_MOD, pools):
            # нет GLP-пула в DeFiLlama; GMX-API мок вернёт тот же payload без apr → fallback
            self.assertAlmostEqual(a.get_apy(), GMX_FALLBACK, places=5)

    def test_08_apy_max_window_high(self):
        # GLP допускает APY-диапазон шире lending (до 60%)
        a = GmxGlpArbitrumAdapter()
        pools = [_pool("gmx-v1", "GLP", "Arbitrum", apy=42.0, tvl=4e8)]
        with _patch_pools(_GMX_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 42.0, places=5)

    def test_09_yield_info_decimal(self):
        a = GmxGlpArbitrumAdapter()
        pools = [_pool("gmx-v1", "GLP", "Arbitrum", apy=8.0, tvl=4e8)]
        with _patch_pools(_GMX_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.08, places=6)
        self.assertEqual(info.protocol, "gmx_glp_arbitrum")

    def test_10_exit_latency_nonzero(self):
        # GLP redeem не мгновенный (cooldown)
        self.assertGreater(GmxGlpArbitrumAdapter().EXIT_LATENCY_HOURS, 0.0)


# ===========================================================================
# Velodrome Optimism (10 tests)
# ===========================================================================

class TestVelodromeOptimism(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = VelodromeOptimismAdapter()
        self.assertEqual(a.CHAIN, "optimism")
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.CHAIN_ID, 10)

    def test_02_protocol_keys(self):
        a = VelodromeOptimismAdapter()
        self.assertEqual(a.PROTOCOL_ID, "velodrome-optimism")
        self.assertEqual(a.PROTOCOL, "velodrome_optimism")

    def test_03_is_lp_position(self):
        a = VelodromeOptimismAdapter()
        self.assertTrue(a.health_check()["is_lp_position"])
        self.assertTrue(a.to_dict()["is_lp_position"])

    def test_04_live_apy_stable_pair(self):
        a = VelodromeOptimismAdapter()
        pools = [_pool("velodrome-v2", "USDC-USDT", "Optimism", apy=5.5)]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 5.5, places=5)

    def test_05_requires_both_stable_tokens(self):
        # Пул только с USDC (single asset) не должен матчиться как стейбл-пара
        a = VelodromeOptimismAdapter()
        pools = [_pool("velodrome-v2", "USDC-OP", "Optimism", apy=20.0, tvl=9e8)]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), VELO_FALLBACK, places=5)

    def test_06_fallback_on_error(self):
        a = VelodromeOptimismAdapter()
        with _patch_error(_VELO_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), VELO_FALLBACK, places=5)

    def test_07_ignores_wrong_chain(self):
        a = VelodromeOptimismAdapter()
        pools = [
            _pool("velodrome-v2", "USDC-USDT", "Base", apy=15.0, tvl=9e8),
            _pool("velodrome-v2", "USDC-USDT", "Optimism", apy=4.2),
        ]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 4.2, places=5)

    def test_08_picks_highest_tvl(self):
        a = VelodromeOptimismAdapter()
        pools = [
            _pool("velodrome-v2", "USDC-USDT", "Optimism", apy=3.0, tvl=10_000_000.0, pool_id="lo"),
            _pool("velodrome-v2", "USDC-USDT", "Optimism", apy=7.0, tvl=80_000_000.0, pool_id="hi"),
        ]
        with _patch_pools(_VELO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 7.0, places=5)

    def test_09_yield_info_decimal(self):
        a = VelodromeOptimismAdapter()
        pools = [_pool("velodrome-v2", "USDC-USDT", "Optimism", apy=5.0)]
        with _patch_pools(_VELO_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.05, places=6)
        self.assertEqual(info.tier, "T2")

    def test_10_health_writestate(self):
        a = VelodromeOptimismAdapter()
        self.assertEqual(a.health_check()["status"], "ok")
        self.assertEqual(a.get_write_state()["chain"], "optimism")


# ===========================================================================
# Gas monitors (8 tests)
# ===========================================================================

class TestL2GasMonitors(unittest.TestCase):
    def _arb(self, tmp):
        return ArbitrumGasMonitor(data_dir=tmp)

    def _op(self, tmp):
        return OptimismGasMonitor(data_dir=tmp)

    def test_01_arb_record_below_threshold_ok(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = self._arb(tmp).record_reading(gwei=0.05, today=date(2026, 6, 21))
            self.assertEqual(r["action"], "OK")
            self.assertFalse(r["kill_switch_active"])

    def test_02_arb_kill_switch_after_n_days(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            m = self._arb(tmp)
            high = ARBITRUM_GAS_THRESHOLD_GWEI + 5.0
            r = None
            for i in range(ARBITRUM_GAS_KILL_DAYS):
                r = m.record_reading(gwei=high, today=date(2026, 6, 21) + timedelta(days=i))
            self.assertTrue(r["kill_switch_active"])
            self.assertEqual(r["action"], "KILL_SWITCH_ACTIVE")
            self.assertTrue(m.is_kill_switch_active())

    def test_03_arb_reset_after_drop(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            m = self._arb(tmp)
            high = ARBITRUM_GAS_THRESHOLD_GWEI + 5.0
            for i in range(ARBITRUM_GAS_KILL_DAYS):
                m.record_reading(gwei=high, today=date(2026, 6, 21) + timedelta(days=i))
            r = m.record_reading(gwei=0.01, today=date(2026, 6, 21) + timedelta(days=ARBITRUM_GAS_KILL_DAYS))
            self.assertFalse(r["kill_switch_active"])
            self.assertEqual(r["action"], "KILL_SWITCH_RESET")

    def test_04_arb_fallback_gwei(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_error("spa_core.monitoring.arbitrum_gas_monitor",
                              urllib.error.URLError("down")):
                gwei = self._arb(tmp).get_current_gas_gwei()
            self.assertGreaterEqual(gwei, 0.0)

    def test_05_op_record_below_threshold_ok(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = self._op(tmp).record_reading(gwei=0.02, today=date(2026, 6, 21))
            self.assertEqual(r["action"], "OK")

    def test_06_op_kill_switch_after_n_days(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            m = self._op(tmp)
            high = OPTIMISM_GAS_THRESHOLD_GWEI + 3.0
            r = None
            for i in range(OPTIMISM_GAS_KILL_DAYS):
                r = m.record_reading(gwei=high, today=date(2026, 6, 21) + timedelta(days=i))
            self.assertTrue(r["kill_switch_active"])

    def test_07_op_dedup_same_day(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            m = self._op(tmp)
            m.record_reading(gwei=0.02, today=date(2026, 6, 21))
            m.record_reading(gwei=0.03, today=date(2026, 6, 21))
            hist = m.load_history()
            same_day = [r for r in hist["recent_readings"] if r["date"] == "2026-06-21"]
            self.assertEqual(len(same_day), 1)
            self.assertAlmostEqual(same_day[0]["gwei"], 0.03, places=6)

    def test_08_status_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            st = self._arb(tmp).get_status()
            for k in ("chain", "threshold_gwei", "kill_days", "kill_switch_active"):
                self.assertIn(k, st)


# ===========================================================================
# Registry wiring (4 tests)
# ===========================================================================

class TestMultichainRegistry(unittest.TestCase):
    def test_01_new_adapters_registered(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, _, _ in ADAPTER_REGISTRY]
        for k in ("radiant_arbitrum", "gmx_glp_arbitrum", "velodrome_optimism"):
            self.assertIn(k, keys)

    def test_02_new_adapters_are_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, _ in ADAPTER_REGISTRY:
            if key in ("radiant_arbitrum", "gmx_glp_arbitrum", "velodrome_optimism"):
                self.assertEqual(tier, "T2", f"{key} tier mismatch")

    def test_03_no_duplicate_aave_l2(self):
        # Aave Arbitrum/Optimism уже существуют — не должно быть дублей-ключей
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, _, _ in ADAPTER_REGISTRY]
        self.assertEqual(len(keys), len(set(keys)), "duplicate registry keys")
        self.assertIn("aave_arbitrum", keys)
        self.assertIn("aave_v3_optimism", keys)

    def test_04_multichain_dict_instances(self):
        from spa_core.adapters import MULTICHAIN_L2_ADAPTERS
        self.assertIn("radiant-arbitrum", MULTICHAIN_L2_ADAPTERS)
        self.assertIn("gmx-glp-arbitrum", MULTICHAIN_L2_ADAPTERS)
        self.assertIn("velodrome-optimism", MULTICHAIN_L2_ADAPTERS)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestRadiantArbitrum,
        TestGmxGlpArbitrum,
        TestVelodromeOptimism,
        TestL2GasMonitors,
        TestMultichainRegistry,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*60}\nMultichain adapters: {passed}/{total} тестов прошло")
    sys.exit(0 if not (result.failures or result.errors) else 1)
