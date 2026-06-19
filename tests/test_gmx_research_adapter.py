"""tests/test_gmx_research_adapter.py — 35 tests for GMXResearchAdapter (MP-1307 v9.23)

Покрытие:
  T01–T05  Модульные константы (RESEARCH_ONLY, SOURCE_ID, FALLBACK_APY_PCT и др.)
  T06–T08  is_research_only()
  T09–T13  source_metadata() структура
  T14–T20  fetch_apy() при сбое сети — fallback, dict, ключи
  T21–T26  fetch_apy() с мокированной DeFiLlama (успешный ответ)
  T27–T29  btc_exposure_apy() / eth_exposure_apy() > 0
  T30–T32  btc/eth exposure при сбое сети = FALLBACK_APY_PCT
  T33      invalidate_cache()
  T34      is_in_range / chain param
  T35      Конструктор с нестандартным chain
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

# Настройка пути
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.gmx_research import (
    DEFI_LLAMA_POOLS_URL,
    FALLBACK_APY_PCT,
    RESEARCH_ONLY,
    REQUEST_TIMEOUT_S,
    SOURCE_ID,
    GMXResearchAdapter,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_defillama_response(pools: list) -> bytes:
    """Формирует JSON-ответ DeFiLlama в правильном формате."""
    return json.dumps({"status": "success", "data": pools}).encode()


def _glp_pool(chain: str = "Arbitrum", apy: float = 28.5, tvl: float = 500_000_000) -> dict:
    return {
        "project": "gmx",
        "symbol": "GLP",
        "chain": chain,
        "apy": apy,
        "tvlUsd": tvl,
        "pool": f"gmx-glp-{chain.lower()}",
    }


def _gm_pool(asset: str = "BTC", apy: float = 22.0, tvl: float = 200_000_000) -> dict:
    return {
        "project": "gmx-v2",
        "symbol": f"GM:{asset}-USDC",
        "chain": "Arbitrum",
        "apy": apy,
        "tvlUsd": tvl,
        "pool": f"gmx-v2-gm-{asset.lower()}",
    }


def _make_adapter_with_mock_response(pools: list) -> GMXResearchAdapter:
    """Возвращает адаптер с замоканным _fetch_pools."""
    adapter = GMXResearchAdapter()
    adapter._cache = pools
    adapter._cache_ts = float("inf")  # кэш никогда не истечёт в тестах
    return adapter


def _make_network_failing_adapter() -> GMXResearchAdapter:
    """Возвращает адаптер, который всегда получает URLError при _fetch_pools."""
    adapter = GMXResearchAdapter()
    adapter._fetch_pools = lambda: None  # всегда None (network fail)
    return adapter


# ── T01–T05: module-level constants ──────────────────────────────────────────

class TestModuleConstants(unittest.TestCase):

    def test_T01_research_only_is_true(self):
        """RESEARCH_ONLY модульная константа должна быть True."""
        self.assertTrue(RESEARCH_ONLY)

    def test_T02_source_id_value(self):
        """SOURCE_ID = 'gmx_research'."""
        self.assertEqual(SOURCE_ID, "gmx_research")

    def test_T03_fallback_apy_is_15(self):
        """FALLBACK_APY_PCT = 15.0."""
        self.assertEqual(FALLBACK_APY_PCT, 15.0)

    def test_T04_timeout_is_5(self):
        """REQUEST_TIMEOUT_S = 5."""
        self.assertEqual(REQUEST_TIMEOUT_S, 5)

    def test_T05_defi_llama_url(self):
        """DEFI_LLAMA_POOLS_URL содержит правильный домен."""
        self.assertIn("yields.llama.fi", DEFI_LLAMA_POOLS_URL)
        self.assertIn("pools", DEFI_LLAMA_POOLS_URL)


# ── T06–T08: is_research_only() ──────────────────────────────────────────────

class TestIsResearchOnly(unittest.TestCase):

    def test_T06_is_research_only_returns_true(self):
        """is_research_only() должен возвращать True."""
        adapter = GMXResearchAdapter()
        self.assertTrue(adapter.is_research_only())

    def test_T07_is_research_only_is_bool(self):
        """is_research_only() возвращает bool, а не просто truthy."""
        adapter = GMXResearchAdapter()
        self.assertIsInstance(adapter.is_research_only(), bool)

    def test_T08_is_research_only_equals_module_constant(self):
        """is_research_only() == RESEARCH_ONLY."""
        adapter = GMXResearchAdapter()
        self.assertEqual(adapter.is_research_only(), RESEARCH_ONLY)


# ── T09–T13: source_metadata() ───────────────────────────────────────────────

class TestSourceMetadata(unittest.TestCase):

    def setUp(self):
        self.adapter = GMXResearchAdapter()
        self.meta = self.adapter.source_metadata()

    def test_T09_metadata_is_dict(self):
        """source_metadata() возвращает dict."""
        self.assertIsInstance(self.meta, dict)

    def test_T10_metadata_has_source_id(self):
        """source_metadata() содержит ключ 'source_id'."""
        self.assertIn("source_id", self.meta)
        self.assertEqual(self.meta["source_id"], SOURCE_ID)

    def test_T11_metadata_research_only_flag(self):
        """source_metadata()['research_only'] == True."""
        self.assertIn("research_only", self.meta)
        self.assertTrue(self.meta["research_only"])

    def test_T12_metadata_has_endpoint(self):
        """source_metadata()['endpoint'] совпадает с DEFI_LLAMA_POOLS_URL."""
        self.assertIn("endpoint", self.meta)
        self.assertEqual(self.meta["endpoint"], DEFI_LLAMA_POOLS_URL)

    def test_T13_metadata_has_fallback_apy(self):
        """source_metadata()['fallback_apy_pct'] = 15.0."""
        self.assertIn("fallback_apy_pct", self.meta)
        self.assertEqual(self.meta["fallback_apy_pct"], FALLBACK_APY_PCT)


# ── T14–T20: fetch_apy() при сбое сети ───────────────────────────────────────

class TestFetchApyNetworkFailure(unittest.TestCase):
    """При сбое сети fetch_apy() должен возвращать dict с fallback APY."""

    def setUp(self):
        self.adapter = _make_network_failing_adapter()

    def test_T14_fetch_apy_returns_dict_on_failure(self):
        """fetch_apy() возвращает dict даже при сбое сети."""
        result = self.adapter.fetch_apy()
        self.assertIsInstance(result, dict)

    def test_T15_fetch_apy_does_not_raise_on_network_error(self):
        """fetch_apy() не бросает исключений при сбое сети."""
        try:
            self.adapter.fetch_apy()
        except Exception as exc:
            self.fail(f"fetch_apy() raised {exc!r}")

    def test_T16_fetch_apy_has_glp_arbitrum_key(self):
        """fetch_apy() возвращает ключ 'gmx_glp_arbitrum'."""
        result = self.adapter.fetch_apy()
        self.assertIn("gmx_glp_arbitrum", result)

    def test_T17_fetch_apy_has_v2_btc_key(self):
        """fetch_apy() возвращает ключ 'gmx_v2_btc'."""
        result = self.adapter.fetch_apy()
        self.assertIn("gmx_v2_btc", result)

    def test_T18_fetch_apy_has_v2_eth_key(self):
        """fetch_apy() возвращает ключ 'gmx_v2_eth'."""
        result = self.adapter.fetch_apy()
        self.assertIn("gmx_v2_eth", result)

    def test_T19_fallback_apy_is_15(self):
        """При сбое сети APY = FALLBACK_APY_PCT = 15.0."""
        result = self.adapter.fetch_apy()
        for key, entry in result.items():
            self.assertAlmostEqual(
                entry["apy"], FALLBACK_APY_PCT, places=3,
                msg=f"key '{key}' apy should be fallback {FALLBACK_APY_PCT}"
            )

    def test_T20_fallback_flag_is_true(self):
        """При сбое сети entry['fallback'] == True."""
        result = self.adapter.fetch_apy()
        for key, entry in result.items():
            self.assertTrue(
                entry["fallback"],
                msg=f"key '{key}': expected fallback=True"
            )


# ── T21–T26: fetch_apy() с мокированной DeFiLlama ────────────────────────────

class TestFetchApyMockedResponse(unittest.TestCase):
    """Проверяем парсинг данных при корректном ответе DeFiLlama."""

    def _make_adapter(self, pools):
        return _make_adapter_with_mock_response(pools)

    def test_T21_glp_arbitrum_apy_parsed(self):
        """APY для gmx_glp_arbitrum берётся из DeFiLlama."""
        pools = [_glp_pool("Arbitrum", apy=30.0)]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        self.assertAlmostEqual(result["gmx_glp_arbitrum"]["apy"], 30.0, places=1)

    def test_T22_glp_arbitrum_not_fallback_when_found(self):
        """Если пул найден, fallback=False."""
        pools = [_glp_pool("Arbitrum", apy=28.5)]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        self.assertFalse(result["gmx_glp_arbitrum"]["fallback"])

    def test_T23_v2_btc_apy_parsed(self):
        """APY для gmx_v2_btc берётся из GMX v2 BTC пула."""
        pools = [_gm_pool("BTC", apy=22.5)]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        self.assertAlmostEqual(result["gmx_v2_btc"]["apy"], 22.5, places=1)

    def test_T24_v2_eth_apy_parsed(self):
        """APY для gmx_v2_eth берётся из GMX v2 ETH пула."""
        pools = [_gm_pool("ETH", apy=18.3)]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        self.assertAlmostEqual(result["gmx_v2_eth"]["apy"], 18.3, places=1)

    def test_T25_best_tvl_pool_wins(self):
        """Из нескольких GLP пулов выбирается с наибольшим TVL."""
        pools = [
            _glp_pool("Arbitrum", apy=10.0, tvl=100_000),
            _glp_pool("Arbitrum", apy=35.0, tvl=900_000_000),  # winner
        ]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        self.assertAlmostEqual(result["gmx_glp_arbitrum"]["apy"], 35.0, places=1)

    def test_T26_unknown_project_pool_ignored(self):
        """Пулы с чужим project игнорируются."""
        pools = [
            {"project": "curve", "symbol": "GLP", "chain": "Arbitrum",
             "apy": 99.0, "tvlUsd": 1e9}
        ]
        adapter = self._make_adapter(pools)
        result = adapter.fetch_apy()
        # Нет GMX пулов → fallback
        self.assertAlmostEqual(result["gmx_glp_arbitrum"]["apy"], FALLBACK_APY_PCT, places=1)


# ── T27–T29: btc_exposure_apy() / eth_exposure_apy() > 0 ────────────────────

class TestExposureApy(unittest.TestCase):

    def test_T27_btc_exposure_apy_gt_0_with_data(self):
        """btc_exposure_apy() > 0 при наличии данных из DeFiLlama."""
        adapter = _make_adapter_with_mock_response([
            _gm_pool("BTC", apy=22.0),
            _glp_pool("Arbitrum", apy=28.0),
        ])
        self.assertGreater(adapter.btc_exposure_apy(), 0)

    def test_T28_eth_exposure_apy_gt_0_with_data(self):
        """eth_exposure_apy() > 0 при наличии данных из DeFiLlama."""
        adapter = _make_adapter_with_mock_response([
            _gm_pool("ETH", apy=18.0),
            _glp_pool("Arbitrum", apy=28.0),
        ])
        self.assertGreater(adapter.eth_exposure_apy(), 0)

    def test_T29_exposure_apy_returns_float(self):
        """btc/eth exposure_apy() возвращают float."""
        adapter = _make_network_failing_adapter()
        self.assertIsInstance(adapter.btc_exposure_apy(), float)
        self.assertIsInstance(adapter.eth_exposure_apy(), float)


# ── T30–T32: btc/eth exposure при сбое сети = FALLBACK_APY_PCT ───────────────

class TestExposureApyFallback(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_network_failing_adapter()

    def test_T30_btc_exposure_fallback_on_network_error(self):
        """btc_exposure_apy() = FALLBACK_APY_PCT при сбое сети."""
        result = self.adapter.btc_exposure_apy()
        self.assertAlmostEqual(result, FALLBACK_APY_PCT, places=3)

    def test_T31_eth_exposure_fallback_on_network_error(self):
        """eth_exposure_apy() = FALLBACK_APY_PCT при сбое сети."""
        result = self.adapter.eth_exposure_apy()
        self.assertAlmostEqual(result, FALLBACK_APY_PCT, places=3)

    def test_T32_exposure_apy_always_positive(self):
        """btc/eth exposure_apy() всегда > 0."""
        self.assertGreater(self.adapter.btc_exposure_apy(), 0)
        self.assertGreater(self.adapter.eth_exposure_apy(), 0)


# ── T33: invalidate_cache() ───────────────────────────────────────────────────

class TestInvalidateCache(unittest.TestCase):

    def test_T33_invalidate_cache_clears_state(self):
        """invalidate_cache() сбрасывает кэш адаптера."""
        adapter = _make_adapter_with_mock_response([_glp_pool()])
        # Убеждаемся, что кэш заполнен
        self.assertIsNotNone(adapter._cache)
        adapter.invalidate_cache()
        self.assertIsNone(adapter._cache)
        self.assertEqual(adapter._cache_ts, 0.0)


# ── T34: chain parameter ──────────────────────────────────────────────────────

class TestChainParam(unittest.TestCase):

    def test_T34_chain_stored_lowercase(self):
        """chain передаётся и хранится в нижнем регистре."""
        adapter = GMXResearchAdapter(chain="Arbitrum")
        self.assertEqual(adapter.chain, "arbitrum")


# ── T35: urllib mock — полная изоляция от сети ────────────────────────────────

class TestUrllibMock(unittest.TestCase):
    """Использует unittest.mock для эмуляции urllib.request.urlopen."""

    def test_T35_urllib_mock_integration(self):
        """Адаптер корректно разбирает мокированный ответ urllib."""
        pools = [
            _glp_pool("Arbitrum", apy=27.0, tvl=600_000_000),
            _gm_pool("BTC", apy=20.0),
            _gm_pool("ETH", apy=16.0),
        ]
        mock_bytes = _make_defillama_response(pools)

        # Мокируем urllib.request.urlopen
        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = mock_bytes
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = unittest.mock.MagicMock(return_value=False)

        adapter = GMXResearchAdapter()
        with unittest.mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = adapter.fetch_apy()

        self.assertAlmostEqual(result["gmx_glp_arbitrum"]["apy"], 27.0, places=1)
        self.assertAlmostEqual(result["gmx_v2_btc"]["apy"], 20.0, places=1)
        self.assertAlmostEqual(result["gmx_v2_eth"]["apy"], 16.0, places=1)
        # Не fallback
        self.assertFalse(result["gmx_glp_arbitrum"]["fallback"])


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
