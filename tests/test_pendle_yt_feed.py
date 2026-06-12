"""
tests/test_pendle_yt_feed.py — MP-427

Тесты для spa_core.price_feeds.pendle_yt_feed

Группы
------
TestFetchDeFiLlamaPools     — _fetch_defillama_pools (3 теста)
TestExtractApyDeFiLlama     — _extract_apy_from_defillama (5 тестов)
TestComputeYtApyPendleV2    — _compute_yt_apy_from_market (4 теста)
TestExtractApyPendleV2      — _extract_apy_from_pendle_v2 (3 теста)
TestGetPendleYtApy          — get_pendle_yt_apy (7 тестов)
TestGetPendleYtApyWithSource — get_pendle_yt_apy_with_source (3 тестов)

Итого: 25 тестов
"""
from __future__ import annotations

import io
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.price_feeds.pendle_yt_feed import (
    FALLBACK_APY,
    APY_MIN_PCT,
    APY_MAX_PCT,
    MIN_TVL_USD,
    _fetch_defillama_pools,
    _extract_apy_from_defillama,
    _fetch_pendle_v2_markets,
    _compute_yt_apy_from_market,
    _extract_apy_from_pendle_v2,
    get_pendle_yt_apy,
    get_pendle_yt_apy_with_source,
)


# ── Вспомогательные фабрики ───────────────────────────────────────────────────

def _make_defillama_response(pools: list) -> bytes:
    """Сериализовать в bytes как DeFiLlama /pools."""
    return json.dumps({"status": "success", "data": pools}).encode()


def _make_pendle_pool(
    symbol: str = "YT-sUSDe-27MAR2025",
    apy: float = 35.0,
    tvl: float = 5_000_000.0,
    project: str = "pendle-v2",
    chain: str = "Ethereum",
) -> dict:
    return {"pool": "uuid-1", "project": project, "symbol": symbol,
            "apy": apy, "tvlUsd": tvl, "chain": chain}


def _make_pendle_v2_response(markets: list) -> bytes:
    return json.dumps({"total": len(markets), "results": markets}).encode()


def _make_pendle_v2_market(
    symbol: str = "PT-sUSDe/USDC",
    implied_apy: float = 0.08,
    underlying_apy: float = 0.12,
    yt_price_pct: float = 0.25,
    liquidity_usd: float = 10_000_000.0,
    underlying_symbol: str = "sUSDe",
) -> dict:
    return {
        "symbol": symbol,
        "impliedApy": implied_apy,
        "underlyingApy": underlying_apy,
        "ytPricePct": yt_price_pct,
        "liquidity": {"usd": str(liquidity_usd)},
        "underlyingAsset": {"symbol": underlying_symbol},
    }


def _mock_urlopen(response_bytes: bytes):
    """Вернуть context-manager mock для urllib.request.urlopen."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=io.BytesIO(response_bytes))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ══════════════════════════════════════════════════════════════════════════════
# TestFetchDeFiLlamaPools
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchDeFiLlamaPools(unittest.TestCase):
    """_fetch_defillama_pools — сетевой уровень."""

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_list_on_success(self, mock_open):
        pools = [_make_pendle_pool()]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))
        result = _fetch_defillama_pools()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_none_on_url_error(self, mock_open):
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("connection refused")
        result = _fetch_defillama_pools()
        self.assertIsNone(result)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_none_on_invalid_json(self, mock_open):
        mock_open.return_value = _mock_urlopen(b"NOT JSON {{{")
        result = _fetch_defillama_pools()
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════════════════════════
# TestExtractApyDeFiLlama
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractApyDeFiLlama(unittest.TestCase):
    """_extract_apy_from_defillama — логика выбора пула."""

    def test_returns_none_on_empty_list(self):
        self.assertIsNone(_extract_apy_from_defillama([]))

    def test_returns_none_if_no_pendle_pools(self):
        pools = [_make_pendle_pool(project="aave-v3", apy=5.0)]
        self.assertIsNone(_extract_apy_from_defillama(pools))

    def test_prefers_yt_symbol_over_pt(self):
        pools = [
            _make_pendle_pool(symbol="PT-sUSDe-27MAR2025", apy=10.0, tvl=5_000_000),
            _make_pendle_pool(symbol="YT-sUSDe-27MAR2025", apy=38.0, tvl=5_000_000),
        ]
        result = _extract_apy_from_defillama(pools)
        # Только YT-пул должен пройти «yt» фильтр → медиана из [38.0] = 38.0
        self.assertAlmostEqual(result, 38.0)

    def test_filters_below_min_tvl(self):
        pools = [
            _make_pendle_pool(symbol="YT-sUSDe-27MAR2025", apy=35.0, tvl=100_000),
        ]
        # tvl < MIN_TVL_USD → пул отклонён → None
        self.assertIsNone(_extract_apy_from_defillama(pools, min_tvl=MIN_TVL_USD))

    def test_median_calculation_odd(self):
        """Медиана из нечётного числа APY."""
        pools = [
            _make_pendle_pool(symbol="YT-A", apy=20.0, tvl=2_000_000),
            _make_pendle_pool(symbol="YT-B", apy=40.0, tvl=2_000_000),
            _make_pendle_pool(symbol="YT-C", apy=30.0, tvl=2_000_000),
        ]
        # Sorted: [20, 30, 40] → median = 30.0
        result = _extract_apy_from_defillama(pools)
        self.assertAlmostEqual(result, 30.0)


# ══════════════════════════════════════════════════════════════════════════════
# TestComputeYtApyPendleV2
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeYtApyPendleV2(unittest.TestCase):
    """_compute_yt_apy_from_market — формула YT APY."""

    def test_standard_calculation(self):
        """implied=8%, underlying=12%, ytPricePct=0.25 → lev=4 → excess=4% → 16%."""
        m = _make_pendle_v2_market(implied_apy=0.08, underlying_apy=0.12, yt_price_pct=0.25)
        result = _compute_yt_apy_from_market(m)
        self.assertIsNotNone(result)
        # excess=0.04, leverage=4.0 → yt_apy = 0.04*4*100 = 16.0
        self.assertAlmostEqual(result, 16.0, places=3)

    def test_returns_none_if_yt_price_zero(self):
        m = _make_pendle_v2_market(yt_price_pct=0.0)
        self.assertIsNone(_compute_yt_apy_from_market(m))

    def test_returns_none_if_excess_negative(self):
        """underlying < implied → YT не profitable."""
        m = _make_pendle_v2_market(implied_apy=0.12, underlying_apy=0.08, yt_price_pct=0.25)
        self.assertIsNone(_compute_yt_apy_from_market(m))

    def test_handles_missing_keys_gracefully(self):
        """Отсутствующие ключи → None, не exception."""
        result = _compute_yt_apy_from_market({})
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════════════════════════
# TestExtractApyPendleV2
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractApyPendleV2(unittest.TestCase):
    """_extract_apy_from_pendle_v2 — фильтрация и медиана."""

    def test_returns_none_on_empty_markets(self):
        self.assertIsNone(_extract_apy_from_pendle_v2([]))

    def test_filters_non_stablecoin_markets(self):
        """Рынок ETH/WETH не должен пройти stablecoin-фильтр."""
        market = _make_pendle_v2_market(
            underlying_symbol="WETH",
            implied_apy=0.04, underlying_apy=0.08, yt_price_pct=0.25,
        )
        self.assertIsNone(_extract_apy_from_pendle_v2([market]))

    def test_returns_median_for_stablecoin_markets(self):
        """Два USDC-рынка → медиана их YT APY."""
        m1 = _make_pendle_v2_market(
            underlying_symbol="sUSDe",
            implied_apy=0.06, underlying_apy=0.12, yt_price_pct=0.25,
            liquidity_usd=5_000_000,
        )
        m2 = _make_pendle_v2_market(
            underlying_symbol="USDC",
            implied_apy=0.04, underlying_apy=0.10, yt_price_pct=0.25,
            liquidity_usd=5_000_000,
        )
        # m1: excess=0.06, lev=4 → 24.0%
        # m2: excess=0.06, lev=4 → 24.0%
        result = _extract_apy_from_pendle_v2([m1, m2])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 24.0, places=2)


# ══════════════════════════════════════════════════════════════════════════════
# TestGetPendleYtApy
# ══════════════════════════════════════════════════════════════════════════════

class TestGetPendleYtApy(unittest.TestCase):
    """get_pendle_yt_apy — публичный API, приоритеты источников."""

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_defillama_apy_when_available(self, mock_open):
        """Источник 1 (DeFiLlama) доступен → возвращает его APY."""
        pools = [_make_pendle_pool(symbol="YT-sUSDe-27MAR2025", apy=36.0, tvl=5_000_000)]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))
        result = get_pendle_yt_apy(
            _defillama_url="https://mock-defillama/pools",
            _pendle_v2_url="https://mock-pendle-v2/markets",
        )
        self.assertAlmostEqual(result, 36.0)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_fallback_to_pendle_v2_when_defillama_empty(self, mock_open):
        """DeFiLlama возвращает пустой список → fallback на Pendle V2."""
        # Первый вызов (DeFiLlama) → пустой список
        defillama_resp = json.dumps({"data": []}).encode()
        # Второй вызов (Pendle V2) → валидный рынок
        market = _make_pendle_v2_market(
            underlying_symbol="sUSDe",
            implied_apy=0.07, underlying_apy=0.12, yt_price_pct=0.25,
            liquidity_usd=8_000_000,
        )
        pendle_v2_resp = _make_pendle_v2_response([market])

        mock_open.side_effect = [
            _mock_urlopen(defillama_resp),
            _mock_urlopen(pendle_v2_resp),
        ]
        result = get_pendle_yt_apy(
            _defillama_url="https://mock-defillama/pools",
            _pendle_v2_url="https://mock-pendle-v2/markets",
        )
        # excess = 0.12-0.07=0.05, leverage=4 → 20.0%
        self.assertAlmostEqual(result, 20.0, places=1)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_fallback_when_both_sources_fail(self, mock_open):
        """Оба источника недоступны → возвращает fallback=28.4."""
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("network error")
        result = get_pendle_yt_apy(
            _defillama_url="https://mock-fail/pools",
            _pendle_v2_url="https://mock-fail/markets",
        )
        self.assertEqual(result, FALLBACK_APY)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_custom_fallback_value_is_respected(self, mock_open):
        """Кастомный fallback передаётся корректно."""
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("x")
        result = get_pendle_yt_apy(fallback=15.0)
        self.assertEqual(result, 15.0)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_result_within_valid_range(self, mock_open):
        """Результат всегда в [APY_MIN_PCT, APY_MAX_PCT] или fallback."""
        pools = [_make_pendle_pool(symbol="YT-sUSDe", apy=55.0, tvl=5_000_000)]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))
        result = get_pendle_yt_apy()
        # 55.0 < APY_MAX_PCT(120) → OK
        self.assertGreaterEqual(result, APY_MIN_PCT)
        self.assertLessEqual(result, APY_MAX_PCT)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_apy_above_max_filtered_out(self, mock_open):
        """APY > APY_MAX_PCT отфильтровывается → другой пул или fallback."""
        pools = [
            _make_pendle_pool(symbol="YT-sUSDe", apy=200.0, tvl=5_000_000),  # аномалия
            _make_pendle_pool(symbol="YT-USDC",  apy=30.0,  tvl=5_000_000),  # норма
        ]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))
        result = get_pendle_yt_apy()
        # 200% отфильтрован, 30% принят
        self.assertAlmostEqual(result, 30.0)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_returns_float_type(self, mock_open):
        """Возвращаемое значение всегда float."""
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("x")
        result = get_pendle_yt_apy()
        self.assertIsInstance(result, float)


# ══════════════════════════════════════════════════════════════════════════════
# TestGetPendleYtApyWithSource
# ══════════════════════════════════════════════════════════════════════════════

class TestGetPendleYtApyWithSource(unittest.TestCase):
    """get_pendle_yt_apy_with_source — кортеж (apy, source_name)."""

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_source_is_defillama_when_available(self, mock_open):
        pools = [_make_pendle_pool(symbol="YT-sUSDe", apy=33.0, tvl=5_000_000)]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))
        apy, source = get_pendle_yt_apy_with_source()
        self.assertEqual(source, "defillama")
        self.assertAlmostEqual(apy, 33.0)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_source_is_fallback_when_all_fail(self, mock_open):
        import urllib.error
        mock_open.side_effect = urllib.error.URLError("x")
        apy, source = get_pendle_yt_apy_with_source()
        self.assertEqual(source, "fallback")
        self.assertEqual(apy, FALLBACK_APY)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_source_is_pendle_v2_when_defillama_empty(self, mock_open):
        defillama_empty = json.dumps({"data": []}).encode()
        market = _make_pendle_v2_market(
            underlying_symbol="sUSDe",
            implied_apy=0.05, underlying_apy=0.15, yt_price_pct=0.20,
            liquidity_usd=6_000_000,
        )
        pendle_v2_resp = _make_pendle_v2_response([market])
        mock_open.side_effect = [
            _mock_urlopen(defillama_empty),
            _mock_urlopen(pendle_v2_resp),
        ]
        apy, source = get_pendle_yt_apy_with_source()
        self.assertEqual(source, "pendle_v2")
        # excess=0.10, lev=5 → 50%
        self.assertAlmostEqual(apy, 50.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# TestS11Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestS11Integration(unittest.TestCase):
    """Интеграционный тест: S11HybridYieldMax использует live APY через MP-427."""

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_s11_run_day_picks_up_live_pendle_apy(self, mock_open):
        """run_day() без apy_map должен попробовать live fetch и использовать его."""
        from spa_core.strategies.s11_hybrid_yield_max import S11HybridYieldMax

        live_apy = 42.0
        pools = [_make_pendle_pool(symbol="YT-sUSDe", apy=live_apy, tvl=5_000_000)]
        mock_open.return_value = _mock_urlopen(_make_defillama_response(pools))

        s = S11HybridYieldMax(capital=100_000.0)
        result = s.run_day(apy_map=None)

        # Стратегия должна быть в bull-режиме (live APY=42 > MIN=12)
        self.assertEqual(result["mode"], "bull")
        # expected_apy = 0.45*42 + 0.30*6.5 + 0.15*2.78 + 0.10*4.74
        #              = 18.9 + 1.95 + 0.417 + 0.474 = 21.741
        expected = 0.45 * 42.0 + 0.30 * 6.5 + 0.15 * 2.78 + 0.10 * 4.74
        self.assertAlmostEqual(result["expected_apy"], expected, places=2)

    @patch("spa_core.price_feeds.pendle_yt_feed.urllib.request.urlopen")
    def test_s11_run_day_uses_fallback_on_feed_failure(self, mock_open):
        """При недоступном feed run_day() работает с APY_DEFAULTS["pendle_yt"]=28.4."""
        import urllib.error
        from spa_core.strategies.s11_hybrid_yield_max import S11HybridYieldMax, APY_DEFAULTS

        mock_open.side_effect = urllib.error.URLError("network")

        s = S11HybridYieldMax(capital=100_000.0)
        result = s.run_day(apy_map=None)

        self.assertEqual(result["mode"], "bull")
        # При fallback APY_DEFAULTS["pendle_yt"]=28.4 → blended≈15.621%
        expected = 0.45 * APY_DEFAULTS["pendle_yt"] + 0.30 * 6.5 + 0.15 * 2.78 + 0.10 * 4.74
        self.assertAlmostEqual(result["expected_apy"], expected, places=2)


if __name__ == "__main__":
    unittest.main()
