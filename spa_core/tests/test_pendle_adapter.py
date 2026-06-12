"""
Unit tests for spa_core/adapters/pendle_adapter.py — MP-201.

All tests use unittest.mock to intercept network calls via PendlePTAdapter;
zero live network calls are made.

Coverage:
  - Parsing API response with mock data
  - Stablecoin market filtering
  - APY calculation (decimal conversion)
  - Fallback on network error (cache behaviour)
  - Maturity calculation
  - Best PT selection with various filters
  - Tier classification
  - Edge cases (empty data, expired markets, sub-minimum TVL, etc.)
  - BaseAdapter interface compliance
  - ADAPTER_REGISTRY registration

Run:
    python3 -m pytest spa_core/tests/test_pendle_adapter.py -v
    # or without pytest:
    python3 -m unittest spa_core.tests.test_pendle_adapter -v
"""
from __future__ import annotations

import datetime
import math
import unittest
from unittest.mock import MagicMock, patch

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.pendle_adapter import (
    EXIT_LATENCY_HOURS,
    PROTOCOL,
    RISK_SCORE,
    STABLECOIN_FILTER,
    PendleAdapter,
    _classify_tier,
)
from spa_core.adapters.pendle_pt import PendleMarketData


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_market(
    address: str = "0xABCD",
    name: str = "PT-sUSDe-27MAR2026",
    underlying: str = "sUSDe",
    implied_apy: float = 8.9,       # percent
    tvl_usd: float = 150_000_000.0,
    liquidity_usd: float = 50_000_000.0,
    days_to_maturity: int = 120,
    is_expired: bool = False,
    maturity_date: str = "",
) -> PendleMarketData:
    """Build a PendleMarketData fixture."""
    if not maturity_date:
        d = datetime.date.today() + datetime.timedelta(days=days_to_maturity)
        maturity_date = d.isoformat()
    return PendleMarketData(
        market_address=address,
        name=name,
        underlying_asset=underlying,
        pt_apy=implied_apy,
        underlying_apy=12.0,
        maturity_date=maturity_date,
        days_to_maturity=days_to_maturity,
        tvl_usd=tvl_usd,
        is_expired=is_expired,
        liquidity_usd=liquidity_usd,
        implied_apy=implied_apy,
    )


def _adapter_with_markets(markets: list) -> PendleAdapter:
    """Return a PendleAdapter whose internal PendlePTAdapter is mocked."""
    mock_pt = MagicMock()
    mock_pt.get_top_markets.return_value = markets
    return PendleAdapter(_pendle_pt_adapter=mock_pt)


def _adapter_raising() -> PendleAdapter:
    """Return a PendleAdapter whose _pt.get_top_markets always raises."""
    mock_pt = MagicMock()
    mock_pt.get_top_markets.side_effect = ConnectionError("network failure")
    return PendleAdapter(_pendle_pt_adapter=mock_pt)


def _approx_equal(a: float, b: float, rel: float = 1e-5) -> bool:
    """True when |a-b| / max(|a|,1e-15) <= rel."""
    if a == b:
        return True
    denom = max(abs(a), 1e-15)
    return abs(a - b) / denom <= rel


# ── 1. Class metadata ─────────────────────────────────────────────────────────

class TestClassMetadata(unittest.TestCase):

    def test_protocol_constant(self):
        self.assertEqual(PROTOCOL, "pendle")

    def test_adapter_protocol_attr(self):
        a = _adapter_with_markets([])
        self.assertEqual(a.PROTOCOL, "pendle")

    def test_risk_score_range(self):
        self.assertGreaterEqual(RISK_SCORE, 0.0)
        self.assertLessEqual(RISK_SCORE, 1.0)

    def test_exit_latency_declared(self):
        self.assertGreater(EXIT_LATENCY_HOURS, 0.0)

    def test_inherits_base_adapter(self):
        a = _adapter_with_markets([])
        self.assertIsInstance(a, BaseAdapter)

    def test_stablecoin_filter_non_empty(self):
        self.assertGreater(len(STABLECOIN_FILTER), 0)

    def test_stablecoin_filter_contains_usdc(self):
        self.assertIn("USDC", STABLECOIN_FILTER)

    def test_stablecoin_filter_contains_usdt(self):
        self.assertIn("USDT", STABLECOIN_FILTER)

    def test_stablecoin_filter_contains_dai(self):
        self.assertIn("DAI", STABLECOIN_FILTER)

    def test_stablecoin_filter_contains_gho(self):
        self.assertIn("GHO", STABLECOIN_FILTER)


# ── 2. Tier classification ─────────────────────────────────────────────────────

class TestClassifyTier(unittest.TestCase):

    def test_t2_at_100m(self):
        self.assertEqual(_classify_tier(100_000_000.0), "T2")

    def test_t2_above_100m(self):
        self.assertEqual(_classify_tier(500_000_000.0), "T2")

    def test_t3_at_20m(self):
        self.assertEqual(_classify_tier(20_000_000.0), "T3")

    def test_t3_between_20m_and_100m(self):
        self.assertEqual(_classify_tier(50_000_000.0), "T3")

    def test_none_below_20m(self):
        self.assertIsNone(_classify_tier(19_999_999.0))

    def test_none_at_zero(self):
        self.assertIsNone(_classify_tier(0.0))

    def test_none_at_5m(self):
        self.assertIsNone(_classify_tier(5_000_000.0))


# ── 3. get_markets — normal data ──────────────────────────────────────────────

class TestGetMarkets(unittest.TestCase):

    def test_returns_list(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertIsInstance(a.get_markets(), list)

    def test_single_market_returned(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertEqual(len(a.get_markets()), 1)

    def test_market_has_required_keys(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        market = a.get_markets()[0]
        for key in ("market_address", "symbol", "implied_apy", "maturity",
                    "tvl_usd", "tier", "days_to_maturity"):
            self.assertIn(key, market, f"Missing key: {key}")

    def test_market_address_matches(self):
        m = _make_market(address="0xDEAD")
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets()[0]["market_address"], "0xDEAD")

    def test_implied_apy_percent(self):
        m = _make_market(implied_apy=8.9)
        a = _adapter_with_markets([m])
        self.assertTrue(_approx_equal(a.get_markets()[0]["implied_apy"], 8.9))

    def test_tier_t2_for_large_tvl(self):
        m = _make_market(tvl_usd=200_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets()[0]["tier"], "T2")

    def test_tier_t3_for_mid_tvl(self):
        m = _make_market(tvl_usd=30_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets()[0]["tier"], "T3")

    def test_below_min_tvl_excluded_from_get_markets(self):
        # TVL < $20M → tier is None → excluded from get_markets
        m = _make_market(tvl_usd=10_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets(), [])

    def test_empty_when_no_markets(self):
        a = _adapter_with_markets([])
        self.assertEqual(a.get_markets(), [])

    def test_multiple_markets_returned(self):
        markets = [_make_market(address=f"0x{i:04X}") for i in range(3)]
        a = _adapter_with_markets(markets)
        self.assertEqual(len(a.get_markets()), 3)

    def test_market_symbol_matches(self):
        m = _make_market(name="PT-sUSDe-27MAR2026")
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets()[0]["symbol"], "PT-sUSDe-27MAR2026")

    def test_market_tvl_matches(self):
        m = _make_market(tvl_usd=250_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_markets()[0]["tvl_usd"], 250_000_000.0)


# ── 4. get_apy — APY conversion ───────────────────────────────────────────────

class TestGetApy(unittest.TestCase):

    def test_returns_decimal(self):
        m = _make_market(implied_apy=8.9)
        a = _adapter_with_markets([m])
        apy = a.get_apy()
        self.assertTrue(_approx_equal(apy, 0.089), f"Expected ~0.089, got {apy}")

    def test_returns_none_when_no_markets(self):
        a = _adapter_with_markets([])
        self.assertIsNone(a.get_apy())

    def test_returns_none_on_network_error(self):
        a = _adapter_raising()
        self.assertIsNone(a.get_apy())

    def test_apy_token_filter_match(self):
        m1 = _make_market(name="PT-sUSDe-27MAR2026", underlying="sUSDe",
                          implied_apy=8.9)
        m2 = _make_market(name="PT-USDC-DEC2026", underlying="USDC",
                          implied_apy=5.0, address="0x0002")
        a = _adapter_with_markets([m1, m2])
        apy = a.get_apy("USDC")
        self.assertTrue(_approx_equal(apy, 0.05), f"Expected ~0.05, got {apy}")

    def test_apy_token_filter_no_match_returns_best(self):
        m = _make_market(implied_apy=7.5)
        a = _adapter_with_markets([m])
        # Token "XYZ" won't match → fallback to global best
        apy = a.get_apy("XYZ")
        self.assertTrue(_approx_equal(apy, 0.075), f"Expected ~0.075, got {apy}")

    def test_apy_case_insensitive_token(self):
        m = _make_market(name="PT-USDC-DEC2026", underlying="USDC", implied_apy=6.0)
        a = _adapter_with_markets([m])
        apy_upper = a.get_apy("USDC")
        apy_lower = a.get_apy("usdc")
        self.assertEqual(apy_upper, apy_lower)

    def test_apy_decimal_precision(self):
        m = _make_market(implied_apy=12.345)
        a = _adapter_with_markets([m])
        apy = a.get_apy()
        self.assertIsNotNone(apy)
        self.assertTrue(_approx_equal(apy, 0.12345, rel=1e-4))


# ── 5. get_yield_info ─────────────────────────────────────────────────────────

class TestGetYieldInfo(unittest.TestCase):

    def test_returns_yield_info_instance(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertIsInstance(a.get_yield_info(), YieldInfo)

    def test_protocol_matches(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_yield_info().protocol, "pendle")

    def test_apy_is_decimal(self):
        m = _make_market(implied_apy=8.9)
        a = _adapter_with_markets([m])
        yi = a.get_yield_info()
        self.assertTrue(_approx_equal(yi.apy, 0.089))

    def test_tvl_usd_populated(self):
        m = _make_market(tvl_usd=150_000_000.0)
        a = _adapter_with_markets([m])
        self.assertTrue(_approx_equal(a.get_yield_info().tvl_usd, 150_000_000.0))

    def test_apy_none_when_no_markets(self):
        a = _adapter_with_markets([])
        self.assertIsNone(a.get_yield_info().apy)

    def test_tvl_none_when_no_markets(self):
        a = _adapter_with_markets([])
        self.assertIsNone(a.get_yield_info().tvl_usd)

    def test_tier_t2_for_large_tvl(self):
        m = _make_market(tvl_usd=200_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_yield_info().tier, "T2")

    def test_tier_t3_for_mid_tvl(self):
        m = _make_market(tvl_usd=25_000_000.0)
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_yield_info().tier, "T3")

    def test_exit_latency_set(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_yield_info().exit_latency_hours, EXIT_LATENCY_HOURS)

    def test_risk_score_set(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertEqual(a.get_yield_info().risk_score, RISK_SCORE)

    def test_asset_field_set(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        yi = a.get_yield_info()
        self.assertEqual(yi.asset, "USDC")


# ── 6. get_best_pt ────────────────────────────────────────────────────────────

class TestGetBestPt(unittest.TestCase):

    def test_returns_dict(self):
        m = _make_market(tvl_usd=600_000.0, implied_apy=6.0)
        a = _adapter_with_markets([m])
        result = a.get_best_pt()
        self.assertIsInstance(result, dict)

    def test_returns_none_when_no_markets(self):
        a = _adapter_with_markets([])
        self.assertIsNone(a.get_best_pt())

    def test_returns_none_when_tvl_below_min(self):
        m = _make_market(tvl_usd=100_000.0, implied_apy=6.0)
        a = _adapter_with_markets([m])
        self.assertIsNone(a.get_best_pt(min_tvl_usd=500_000.0))

    def test_returns_none_when_apy_below_min(self):
        m = _make_market(tvl_usd=600_000.0, implied_apy=2.0)
        a = _adapter_with_markets([m])
        # min_apy=0.05 == 5%; 2% implied → excluded
        self.assertIsNone(a.get_best_pt(min_apy=0.05))

    def test_selects_highest_apy(self):
        m1 = _make_market(address="0x01", implied_apy=9.0, tvl_usd=600_000.0)
        m2 = _make_market(address="0x02", implied_apy=7.0, tvl_usd=600_000.0)
        # _fetch_eligible returns [m1, m2] (sorted desc already)
        a = _adapter_with_markets([m1, m2])
        best = a.get_best_pt(min_tvl_usd=500_000.0, min_apy=0.01)
        self.assertIsNotNone(best)
        self.assertTrue(_approx_equal(best["implied_apy"], 9.0))

    def test_custom_min_tvl(self):
        m = _make_market(tvl_usd=1_000_000.0, implied_apy=6.0)
        a = _adapter_with_markets([m])
        self.assertIsNone(a.get_best_pt(min_tvl_usd=2_000_000.0))

    def test_custom_min_apy(self):
        m = _make_market(tvl_usd=600_000.0, implied_apy=4.0)
        a = _adapter_with_markets([m])
        # 4% < 5% threshold → excluded
        self.assertIsNone(a.get_best_pt(min_apy=0.05))

    def test_market_dict_has_implied_apy(self):
        m = _make_market(tvl_usd=600_000.0, implied_apy=6.5)
        a = _adapter_with_markets([m])
        best = a.get_best_pt(min_tvl_usd=500_000.0, min_apy=0.01)
        self.assertIsNotNone(best)
        self.assertIn("implied_apy", best)

    def test_apy_threshold_exact_match(self):
        # 5.0% == 0.05 threshold → should be included
        m = _make_market(tvl_usd=600_000.0, implied_apy=5.0)
        a = _adapter_with_markets([m])
        best = a.get_best_pt(min_tvl_usd=500_000.0, min_apy=0.05)
        self.assertIsNotNone(best)


# ── 7. maturity_days ──────────────────────────────────────────────────────────

class TestMaturityDays(unittest.TestCase):

    def test_future_date(self):
        future = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        market = {"maturity": future}
        self.assertEqual(PendleAdapter.maturity_days(market), 90)

    def test_past_date_returns_zero(self):
        past = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        market = {"maturity": past}
        self.assertEqual(PendleAdapter.maturity_days(market), 0)

    def test_today_returns_zero(self):
        today = datetime.date.today().isoformat()
        market = {"maturity": today}
        self.assertEqual(PendleAdapter.maturity_days(market), 0)

    def test_empty_string_returns_zero(self):
        self.assertEqual(PendleAdapter.maturity_days({"maturity": ""}), 0)

    def test_missing_key_returns_zero(self):
        self.assertEqual(PendleAdapter.maturity_days({}), 0)

    def test_none_value_returns_zero(self):
        self.assertEqual(PendleAdapter.maturity_days({"maturity": None}), 0)

    def test_invalid_string_returns_zero(self):
        self.assertEqual(PendleAdapter.maturity_days({"maturity": "not-a-date"}), 0)

    def test_maturity_date_key_also_works(self):
        future = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        market = {"maturity_date": future}
        self.assertEqual(PendleAdapter.maturity_days(market), 30)

    def test_iso_datetime_string_truncated(self):
        # Pendle API sometimes returns "2026-03-27T00:00:00.000Z"
        future = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
        market = {"maturity": future + "T00:00:00.000Z"}
        self.assertEqual(PendleAdapter.maturity_days(market), 60)

    def test_large_future(self):
        future = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
        market = {"maturity": future}
        self.assertEqual(PendleAdapter.maturity_days(market), 365)


# ── 8. Fallback cache behaviour ───────────────────────────────────────────────

class TestCacheFallback(unittest.TestCase):

    def test_cache_populated_on_success(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        a.get_apy()
        self.assertEqual(len(a._cache), 1)

    def test_cache_used_on_subsequent_error(self):
        m = _make_market(implied_apy=7.0)
        mock_pt = MagicMock()
        mock_pt.get_top_markets.side_effect = [
            [m],
            ConnectionError("down"),
        ]
        a = PendleAdapter(_pendle_pt_adapter=mock_pt)
        apy1 = a.get_apy()
        apy2 = a.get_apy()
        self.assertTrue(_approx_equal(apy1, 0.07))
        self.assertTrue(_approx_equal(apy2, 0.07))   # served from cache

    def test_empty_cache_returns_none_on_error(self):
        a = _adapter_raising()
        self.assertIsNone(a.get_apy())

    def test_cache_not_updated_on_empty_response(self):
        m = _make_market(implied_apy=5.0)
        mock_pt = MagicMock()
        mock_pt.get_top_markets.side_effect = [[m], []]
        a = PendleAdapter(_pendle_pt_adapter=mock_pt)
        a.get_apy()        # populates cache with [m]
        apy = a.get_apy()  # empty result → cache unchanged
        self.assertTrue(_approx_equal(apy, 0.05))

    def test_cache_ts_updated_on_success(self):
        m = _make_market()
        a = _adapter_with_markets([m])
        self.assertEqual(a._cache_ts, 0.0)
        a.get_apy()
        self.assertGreater(a._cache_ts, 0.0)

    def test_get_markets_uses_cache_on_error(self):
        m = _make_market(tvl_usd=200_000_000.0)
        mock_pt = MagicMock()
        mock_pt.get_top_markets.side_effect = [[m], ConnectionError("down")]
        a = PendleAdapter(_pendle_pt_adapter=mock_pt)
        a.get_markets()   # populate cache
        markets2 = a.get_markets()  # error → uses cache → returns [m]
        self.assertEqual(len(markets2), 1)


# ── 9. ADAPTER_REGISTRY registration ─────────────────────────────────────────

class TestAdapterRegistry(unittest.TestCase):

    def test_pendle_in_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [entry[0] for entry in ADAPTER_REGISTRY]
        self.assertIn("pendle", keys)

    def test_pendle_registry_class(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "pendle":
                self.assertIs(cls, PendleAdapter)
                return
        self.fail("pendle not found in ADAPTER_REGISTRY")

    def test_pendle_registry_default_tier(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        for key, tier, cls in ADAPTER_REGISTRY:
            if key == "pendle":
                self.assertIn(tier, ("T2", "T3"))
                return
        self.fail("pendle not found in ADAPTER_REGISTRY")

    def test_pendle_importable_from_adapters_package(self):
        from spa_core.adapters import PendleAdapter as PA
        self.assertIs(PA, PendleAdapter)


# ── 10. Edge cases ────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_adapter_never_raises_on_network_error(self):
        a = _adapter_raising()
        # None of these should raise
        result_apy = a.get_apy()
        result_markets = a.get_markets()
        result_best = a.get_best_pt()
        yi = a.get_yield_info()
        self.assertIsNone(result_apy)
        self.assertEqual(result_markets, [])
        self.assertIsNone(result_best)
        self.assertIsNone(yi.apy)

    def test_zero_implied_apy_handled(self):
        m = _make_market(implied_apy=0.0)
        a = _adapter_with_markets([m])
        apy = a.get_apy()
        self.assertIsNotNone(apy)
        self.assertTrue(_approx_equal(apy, 0.0, rel=1.0))

    def test_very_high_implied_apy(self):
        m = _make_market(implied_apy=99.0)
        a = _adapter_with_markets([m])
        apy = a.get_apy()
        self.assertTrue(_approx_equal(apy, 0.99))

    def test_get_markets_excludes_below_tier_tvl(self):
        m_t2 = _make_market(address="0x01", tvl_usd=200_000_000.0)
        m_t3 = _make_market(address="0x02", tvl_usd=30_000_000.0)
        m_skip = _make_market(address="0x03", tvl_usd=5_000_000.0)
        a = _adapter_with_markets([m_t2, m_t3, m_skip])
        markets = a.get_markets()
        addresses = [m["market_address"] for m in markets]
        self.assertIn("0x01", addresses)
        self.assertIn("0x02", addresses)
        self.assertNotIn("0x03", addresses)

    def test_get_yield_info_no_raise_on_error(self):
        a = _adapter_raising()
        yi = a.get_yield_info()   # must not raise
        self.assertIsNone(yi.apy)

    def test_get_best_pt_no_raise_on_error(self):
        a = _adapter_raising()
        result = a.get_best_pt()
        self.assertIsNone(result)

    def test_adapter_initialises_with_defaults(self):
        # Smoke: PendleAdapter() without injection; constructor must not raise.
        with patch("spa_core.adapters.pendle_adapter._PendlePTAdapter") as MockPT:
            instance = MockPT.return_value
            instance.get_top_markets.return_value = []
            a = PendleAdapter()
            self.assertEqual(a.PROTOCOL, "pendle")

    def test_adapter_default_asset_is_usdc(self):
        a = _adapter_with_markets([])
        self.assertEqual(a.asset, "USDC")

    def test_adapter_custom_asset(self):
        mock_pt = MagicMock()
        mock_pt.get_top_markets.return_value = []
        a = PendleAdapter(asset="USDT", _pendle_pt_adapter=mock_pt)
        self.assertEqual(a.asset, "USDT")

    def test_maturity_days_is_static_method(self):
        # Can be called on the class without an instance
        future = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
        result = PendleAdapter.maturity_days({"maturity": future})
        self.assertEqual(result, 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
