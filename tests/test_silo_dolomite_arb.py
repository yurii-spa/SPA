#!/usr/bin/env python3
"""Standalone тесты для Silo Finance / Dolomite Arbitrum адаптеров (v1.254).

Эти два read-only адаптера заменяют мёртвый Radiant Capital и deprecated GMX GLP
на Arbitrum. Покрытие (25 тестов):
  - SiloArbitrumUSDCAdapter      (Silo Finance USDC, Arbitrum, T2)   — 10 тестов
  - DolomiteArbitrumUSDCAdapter  (Dolomite USDC, Arbitrum, T2)       — 10 тестов
  - Registry wiring + dead-adapter removal                            —  5 тестов

⚠️ TVL обоих протоколов на Arbitrum (USDC) сейчас НИЖЕ RiskPolicy floor $5M
(Silo ~$12K, Dolomite ~$1.47M по DeFiLlama 2026-06-21) → адаптеры регистрируются
как read-only мониторинг-фиды; RiskPolicy не выделяет капитал, пока TVL не вырастет.

Запуск:  python3 tests/test_silo_dolomite_arb.py
         python3 -m pytest tests/test_silo_dolomite_arb.py -v

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

from spa_core.adapters.silo_arbitrum_usdc_adapter import (
    APY_FALLBACK as SILO_FALLBACK,
    SiloArbitrumUSDCAdapter,
)
from spa_core.adapters.dolomite_arbitrum_usdc_adapter import (
    APY_FALLBACK as DOLOMITE_FALLBACK,
    DolomiteArbitrumUSDCAdapter,
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


_SILO_MOD = "spa_core.adapters.silo_arbitrum_usdc_adapter"
_DOLO_MOD = "spa_core.adapters.dolomite_arbitrum_usdc_adapter"


# ===========================================================================
# Silo Finance Arbitrum (10 tests)
# ===========================================================================

class TestSiloArbitrum(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = SiloArbitrumUSDCAdapter()
        self.assertEqual(a.CHAIN, "arbitrum")
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")
        self.assertEqual(a.CHAIN_ID, 42161)

    def test_02_protocol_keys(self):
        a = SiloArbitrumUSDCAdapter()
        self.assertEqual(a.PROTOCOL_ID, "silo-arbitrum")
        self.assertEqual(a.PROTOCOL, "silo_arbitrum")
        self.assertEqual(a.pool_id, "silo-usdc-arbitrum")

    def test_03_tvl_below_floor_honest(self):
        # Честно: текущий TVL Silo USDC на Arbitrum ниже RiskPolicy floor $5M
        a = SiloArbitrumUSDCAdapter()
        self.assertLess(a.TVL_USD, 5_000_000)
        self.assertFalse(a.health_check()["tvl_floor_ok"])

    def test_04_risk_score_range(self):
        a = SiloArbitrumUSDCAdapter()
        self.assertGreater(a.RISK_SCORE, 0.0)
        self.assertLessEqual(a.RISK_SCORE, 1.0)

    def test_05_live_apy(self):
        a = SiloArbitrumUSDCAdapter()
        pools = [_pool("silo-v2", "USDC", "Arbitrum", apy=7.4)]
        with _patch_pools(_SILO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 7.4, places=5)

    def test_06_fallback_on_network_error(self):
        a = SiloArbitrumUSDCAdapter()
        with _patch_error(_SILO_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), SILO_FALLBACK, places=5)
        self.assertAlmostEqual(SILO_FALLBACK, 4.5, places=5)

    def test_07_ignores_wrong_chain(self):
        a = SiloArbitrumUSDCAdapter()
        pools = [
            _pool("silo-v2", "USDC", "Ethereum", apy=9.9, tvl=9e8),
            _pool("silo-v2", "USDC", "Arbitrum", apy=4.67),
        ]
        with _patch_pools(_SILO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 4.67, places=5)

    def test_08_ignores_non_usdc(self):
        a = SiloArbitrumUSDCAdapter()
        pools = [_pool("silo-v2", "WETH", "Arbitrum", apy=12.0, tvl=9e8)]
        with _patch_pools(_SILO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), SILO_FALLBACK, places=5)

    def test_09_yield_info_decimal(self):
        a = SiloArbitrumUSDCAdapter()
        pools = [_pool("silo-v2", "USDC", "Arbitrum", apy=5.0)]
        with _patch_pools(_SILO_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.05, places=6)
        self.assertEqual(info.tier, "T2")
        self.assertEqual(info.protocol, "silo_arbitrum")

    def test_10_health_and_writestate(self):
        a = SiloArbitrumUSDCAdapter()
        h = a.health_check()
        self.assertEqual(h["status"], "ok")
        ws = a.get_write_state()
        self.assertEqual(ws["write_state"], "read_only")
        self.assertEqual(ws["chain"], "arbitrum")


# ===========================================================================
# Dolomite Arbitrum (10 tests)
# ===========================================================================

class TestDolomiteArbitrum(unittest.TestCase):
    def test_01_chain_and_tier(self):
        a = DolomiteArbitrumUSDCAdapter()
        self.assertEqual(a.CHAIN, "arbitrum")
        self.assertEqual(a.TIER, "T2")
        self.assertEqual(a.tier, "T2")
        self.assertEqual(a.CHAIN_ID, 42161)

    def test_02_protocol_keys(self):
        a = DolomiteArbitrumUSDCAdapter()
        self.assertEqual(a.PROTOCOL_ID, "dolomite-arbitrum")
        self.assertEqual(a.PROTOCOL, "dolomite_arbitrum")
        self.assertEqual(a.pool_id, "dolomite-usdc-arbitrum")

    def test_03_tvl_below_floor_honest(self):
        # Честно: текущий TVL Dolomite USDC на Arbitrum ~$1.47M < RiskPolicy floor $5M
        a = DolomiteArbitrumUSDCAdapter()
        self.assertLess(a.TVL_USD, 5_000_000)
        self.assertFalse(a.health_check()["tvl_floor_ok"])

    def test_04_risk_score_range(self):
        a = DolomiteArbitrumUSDCAdapter()
        self.assertGreater(a.RISK_SCORE, 0.0)
        self.assertLessEqual(a.RISK_SCORE, 1.0)

    def test_05_live_apy(self):
        a = DolomiteArbitrumUSDCAdapter()
        pools = [_pool("dolomite", "USDC", "Arbitrum", apy=3.98)]
        with _patch_pools(_DOLO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 3.98, places=5)

    def test_06_fallback_on_network_error(self):
        a = DolomiteArbitrumUSDCAdapter()
        with _patch_error(_DOLO_MOD, urllib.error.URLError("down")):
            self.assertAlmostEqual(a.get_apy(), DOLOMITE_FALLBACK, places=5)
        self.assertAlmostEqual(DOLOMITE_FALLBACK, 4.0, places=5)

    def test_07_ignores_wrong_chain(self):
        a = DolomiteArbitrumUSDCAdapter()
        pools = [
            _pool("dolomite", "USDC", "Ethereum", apy=9.9, tvl=9e8),
            _pool("dolomite", "USDC", "Arbitrum", apy=4.2, tvl=2e6),
        ]
        with _patch_pools(_DOLO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 4.2, places=5)

    def test_08_ignores_non_usdc(self):
        a = DolomiteArbitrumUSDCAdapter()
        pools = [_pool("dolomite", "WBTC", "Arbitrum", apy=12.0, tvl=9e8)]
        with _patch_pools(_DOLO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), DOLOMITE_FALLBACK, places=5)

    def test_09_picks_highest_tvl_pool(self):
        a = DolomiteArbitrumUSDCAdapter()
        pools = [
            _pool("dolomite", "USDC", "Arbitrum", apy=3.6, tvl=200_000.0, pool_id="lo"),
            _pool("dolomite", "USDC", "Arbitrum", apy=3.98, tvl=1_470_000.0, pool_id="hi"),
        ]
        with _patch_pools(_DOLO_MOD, pools):
            self.assertAlmostEqual(a.get_apy(), 3.98, places=5)

    def test_10_yield_info_and_writestate(self):
        a = DolomiteArbitrumUSDCAdapter()
        pools = [_pool("dolomite", "USDC", "Arbitrum", apy=4.0, tvl=1_470_000.0)]
        with _patch_pools(_DOLO_MOD, pools):
            info = a.get_yield_info()
        self.assertAlmostEqual(info.apy, 0.04, places=6)
        self.assertEqual(info.protocol, "dolomite_arbitrum")
        self.assertEqual(a.get_write_state()["write_state"], "read_only")


# ===========================================================================
# Registry wiring + dead-adapter removal (5 tests)
# ===========================================================================

class TestSiloDolomiteRegistry(unittest.TestCase):
    def test_01_new_adapters_registered(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [k for k, _, _ in ADAPTER_REGISTRY]
        self.assertIn("silo_arbitrum", keys)
        self.assertIn("dolomite_arbitrum", keys)

    def test_02_new_adapters_are_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, _ in ADAPTER_REGISTRY:
            if key in ("silo_arbitrum", "dolomite_arbitrum"):
                self.assertEqual(tier, "T2", f"{key} tier mismatch")

    def test_03_dead_adapters_removed(self):
        from spa_core.adapters import ADAPTER_REGISTRY, MULTICHAIN_L2_ADAPTERS
        keys = [k for k, _, _ in ADAPTER_REGISTRY]
        self.assertNotIn("radiant_arbitrum", keys)
        self.assertNotIn("gmx_glp_arbitrum", keys)
        self.assertNotIn("radiant-arbitrum", MULTICHAIN_L2_ADAPTERS)
        self.assertNotIn("gmx-glp-arbitrum", MULTICHAIN_L2_ADAPTERS)

    def test_04_multichain_dict_instances(self):
        from spa_core.adapters import MULTICHAIN_L2_ADAPTERS
        self.assertIn("silo-arbitrum", MULTICHAIN_L2_ADAPTERS)
        self.assertIn("dolomite-arbitrum", MULTICHAIN_L2_ADAPTERS)

    def test_05_exported_classes_importable(self):
        from spa_core.adapters import (
            SiloArbitrumUSDCAdapter as S,
            DolomiteArbitrumUSDCAdapter as D,
        )
        self.assertEqual(S().PROTOCOL, "silo_arbitrum")
        self.assertEqual(D().PROTOCOL, "dolomite_arbitrum")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestSiloArbitrum,
        TestDolomiteArbitrum,
        TestSiloDolomiteRegistry,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'='*60}\nSilo/Dolomite Arbitrum: {passed}/{total} тестов прошло")
    sys.exit(0 if not (result.failures or result.errors) else 1)
