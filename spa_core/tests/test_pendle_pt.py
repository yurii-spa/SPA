"""
Unit tests for spa_core/adapters/pendle_pt.py — MP-201.

All tests use unittest.mock to intercept urllib.request.urlopen; zero live
network calls.  Pattern mirrors test_morpho_blue_adapter.py.

Run:
    python3 -m pytest spa_core/tests/test_pendle_pt.py -v
"""
from __future__ import annotations

import datetime
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from spa_core.adapters.pendle_pt import (
    PENDLE_MIN_TVL_USD,
    PendleMarketData,
    PendlePTAdapter,
    _days_to_maturity,
    _is_stablecoin,
    _parse_market,
    _parse_maturity,
    get_pendle_apy,
)

# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _future_date(days: int) -> str:
    """Return an ISO-8601 datetime string 'days' from today (for expiry field)."""
    d = datetime.date.today() + datetime.timedelta(days=days)
    return d.isoformat() + "T00:00:00.000Z"


def _make_raw_market(
    address: str = "0xABCD",
    pt_symbol: str = "PT-sUSDe-27MAR2026",
    underlying_symbol: str = "sUSDe",
    implied_apy: float = 0.089,
    underlying_apy: float = 0.145,
    tvl_usd: float = 25_000_000.0,
    liquidity_usd: float = 10_000_000.0,
    days_to_expiry: int = 120,
    is_expired: bool = False,
    chain_id: int = 1,
) -> dict:
    """Build a minimal Pendle API market dict in the expected response shape."""
    expiry = _future_date(days_to_expiry)
    return {
        "address": address,
        "expiry": expiry,
        "chainId": chain_id,
        "isExpired": is_expired,
        "pt": {
            "address": "0xPT" + address,
            "symbol": pt_symbol,
            "name": pt_symbol,
            "price": {"usd": str(round(1 / (1 + implied_apy), 4))},
        },
        "underlyingAsset": {
            "address": "0xUA",
            "symbol": underlying_symbol,
            "name": underlying_symbol,
        },
        "tvl": {"usd": str(tvl_usd)},
        "liquidity": {"usd": str(liquidity_usd)},
        "impliedApy": implied_apy,
        "underlyingInterestApy": underlying_apy,
        "underlyingRewardApy": 0.0,
        "pendleApy": 0.01,
        "feeApy": 0.002,
        "ytFloatingApy": 0.20,
    }


def _mock_urlopen(raw_markets: list[dict]):
    """
    Return a context-manager mock for urllib.request.urlopen that yields
    a JSON payload with {'results': raw_markets}.
    """
    payload = json.dumps({"results": raw_markets, "total": len(raw_markets)}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── 1. test_fetch_markets_parses_response ─────────────────────────────────────

class TestFetchMarketsParses:
    """Adapter correctly parses a standard Pendle API markets response."""

    def test_returns_list_of_market_data(self):
        raw = [_make_raw_market()]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()
        assert isinstance(markets, list)

    def test_parsed_fields_correct(self):
        raw = [_make_raw_market(
            address="0xDEAD",
            pt_symbol="PT-sUSDe-27MAR2026",
            underlying_symbol="sUSDe",
            implied_apy=0.089,
            tvl_usd=30_000_000.0,
            days_to_expiry=90,
        )]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()

        assert len(markets) == 1
        m = markets[0]
        assert m.market_address == "0xDEAD"
        assert m.underlying_asset == "sUSDe"
        assert m.tvl_usd == pytest.approx(30_000_000.0)
        assert m.pt_apy == pytest.approx(8.9, abs=0.01)
        assert m.is_expired is False
        assert m.days_to_maturity > 0

    def test_accepts_data_key_instead_of_results(self):
        """API may return 'data' instead of 'results'."""
        raw_market = _make_raw_market()
        payload = json.dumps({"data": [raw_market]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            markets = adapter.get_top_markets()
        assert len(markets) == 1

    def test_accepts_bare_list_response(self):
        """API may return a bare JSON array."""
        raw_market = _make_raw_market()
        payload = json.dumps([raw_market]).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            markets = adapter.get_top_markets()
        assert len(markets) == 1


# ── 2. test_filter_expired_markets ───────────────────────────────────────────

class TestFilterExpiredMarkets:
    """Expired markets are excluded from results."""

    def test_expired_flag_excluded(self):
        raw = [_make_raw_market(is_expired=True, days_to_expiry=0)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()
        assert markets == []

    def test_non_expired_passes(self):
        raw = [_make_raw_market(is_expired=False, days_to_expiry=90)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()
        assert len(markets) == 1


# ── 3. test_filter_by_min_tvl ────────────────────────────────────────────────

class TestFilterByMinTvl:
    """Markets below the TVL floor are excluded."""

    def test_below_tvl_floor_excluded(self):
        raw = [_make_raw_market(tvl_usd=1_000_000.0)]  # $1M < $5M
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(min_tvl_usd=PENDLE_MIN_TVL_USD)
        assert markets == []

    def test_at_tvl_floor_passes(self):
        raw = [_make_raw_market(tvl_usd=PENDLE_MIN_TVL_USD)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(min_tvl_usd=PENDLE_MIN_TVL_USD)
        assert len(markets) == 1

    def test_above_tvl_floor_passes(self):
        raw = [_make_raw_market(tvl_usd=100_000_000.0)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(min_tvl_usd=PENDLE_MIN_TVL_USD)
        assert len(markets) == 1


# ── 4. test_stablecoin_filter ────────────────────────────────────────────────

class TestStablecoinFilter:
    """Non-stablecoin underlyings are excluded when stablecoin_only=True."""

    def test_non_stablecoin_excluded(self):
        raw = [_make_raw_market(
            underlying_symbol="weETH",  # Wrapped ether — not stable
            pt_symbol="PT-weETH-27MAR2026",
        )]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(stablecoin_only=True)
        assert markets == []

    def test_usdc_passes(self):
        raw = [_make_raw_market(underlying_symbol="USDC", pt_symbol="PT-USDC-26DEC2026")]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(stablecoin_only=True)
        assert len(markets) == 1

    def test_susde_passes(self):
        raw = [_make_raw_market(underlying_symbol="sUSDe", pt_symbol="PT-sUSDe-MAR2026")]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(stablecoin_only=True)
        assert len(markets) == 1

    def test_non_stablecoin_passes_when_filter_off(self):
        raw = [_make_raw_market(underlying_symbol="weETH", pt_symbol="PT-weETH-MAR2026")]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(stablecoin_only=False)
        assert len(markets) == 1

    def test_stablecoin_keywords(self):
        for sym in ["USDT", "DAI", "FRAX", "GHO", "USDe", "crvUSD"]:
            assert _is_stablecoin(sym), f"Expected {sym} to be recognised as stablecoin"

    def test_non_stablecoin_keyword(self):
        for sym in ["weETH", "WBTC", "stETH", "ezETH"]:
            assert not _is_stablecoin(sym), f"Expected {sym} NOT to be stablecoin"


# ── 5. test_best_market_highest_apy_selected ─────────────────────────────────

class TestBestMarketHighestApy:
    """get_best_market() returns the market with the highest pt_apy."""

    def test_highest_apy_selected_from_multiple(self):
        raw = [
            _make_raw_market(address="0xA", implied_apy=0.075),  # 7.5%
            _make_raw_market(address="0xB", implied_apy=0.095),  # 9.5% ← best
            _make_raw_market(address="0xC", implied_apy=0.060),  # 6.0%
        ]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            best = adapter.get_best_market()

        assert best is not None
        assert best.market_address == "0xB"
        assert best.pt_apy == pytest.approx(9.5, abs=0.01)

    def test_returns_none_when_no_eligible_markets(self):
        raw = []  # empty response
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            best = adapter.get_best_market()
        assert best is None

    def test_sorted_descending_in_top_markets(self):
        raw = [
            _make_raw_market(address="0xLOW", implied_apy=0.060),
            _make_raw_market(address="0xHIGH", implied_apy=0.110),
            _make_raw_market(address="0xMID", implied_apy=0.085),
        ]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()

        apys = [m.pt_apy for m in markets]
        assert apys == sorted(apys, reverse=True)


# ── 6. test_to_adapter_format_structure ──────────────────────────────────────

class TestToAdapterFormat:
    """to_adapter_format() produces a correctly shaped SPA dict."""

    def _make_market(self, **kwargs) -> PendleMarketData:
        defaults = dict(
            market_address="0xDEAD",
            name="PT-sUSDe-27MAR2026",
            underlying_asset="sUSDe",
            pt_apy=8.9,
            underlying_apy=14.5,
            maturity_date="2026-03-27",
            days_to_maturity=90,
            tvl_usd=25_000_000.0,
            is_expired=False,
            liquidity_usd=10_000_000.0,
            implied_apy=8.9,
        )
        defaults.update(kwargs)
        return PendleMarketData(**defaults)

    def test_required_keys_present(self):
        m = self._make_market()
        fmt = PendlePTAdapter.to_adapter_format(m)
        for key in ("id", "name", "tier", "apy", "tvl_usd", "is_available", "source", "details"):
            assert key in fmt, f"Missing key: {key}"

    def test_id_is_pendle_pt(self):
        fmt = PendlePTAdapter.to_adapter_format(self._make_market())
        assert fmt["id"] == "pendle_pt"

    def test_tier_is_t2(self):
        fmt = PendlePTAdapter.to_adapter_format(self._make_market())
        assert fmt["tier"] == "T2"

    def test_apy_matches_pt_apy(self):
        m = self._make_market(pt_apy=9.1)
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["apy"] == pytest.approx(9.1)

    def test_tvl_usd_propagated(self):
        m = self._make_market(tvl_usd=42_000_000.0)
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["tvl_usd"] == pytest.approx(42_000_000.0)

    def test_is_available_false_when_expired(self):
        m = self._make_market(is_expired=True)
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["is_available"] is False

    def test_is_available_true_when_not_expired(self):
        m = self._make_market(is_expired=False)
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["is_available"] is True

    def test_source_is_pendle_api(self):
        fmt = PendlePTAdapter.to_adapter_format(self._make_market())
        assert fmt["source"] == "pendle_api"

    def test_details_has_maturity_and_underlying(self):
        m = self._make_market(maturity_date="2026-06-27", underlying_asset="sUSDe")
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["details"]["maturity_date"] == "2026-06-27"
        assert fmt["details"]["underlying"] == "sUSDe"

    def test_details_has_market_address(self):
        m = self._make_market(market_address="0xCAFE")
        fmt = PendlePTAdapter.to_adapter_format(m)
        assert fmt["details"]["market_address"] == "0xCAFE"


# ── 7. test_graceful_fallback_on_api_error ───────────────────────────────────

class TestGracefulFallback:
    """get_pendle_apy() returns a valid fallback dict when the API fails."""

    def test_fallback_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("unreachable")):
            result = get_pendle_apy(fallback_apy=7.0)

        assert result["apy"] == pytest.approx(7.0)
        assert result["is_available"] is False
        assert result["source"] == "fallback"

    def test_fallback_on_http_error(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(None, 500, "Server Error", {}, None)):
            result = get_pendle_apy(fallback_apy=7.0)

        assert result["source"] == "fallback"
        assert result["apy"] == pytest.approx(7.0)

    def test_fallback_on_json_decode_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json {{{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = get_pendle_apy(fallback_apy=7.0)

        assert result["source"] == "fallback"
        assert result["is_available"] is False

    def test_fallback_on_empty_results(self):
        """No eligible markets → fallback."""
        with patch("urllib.request.urlopen", return_value=_mock_urlopen([])):
            result = get_pendle_apy(fallback_apy=7.0)
        assert result["source"] == "fallback"

    def test_fallback_dict_has_required_shape(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = get_pendle_apy(fallback_apy=5.5)
        for key in ("id", "name", "tier", "apy", "tvl_usd", "is_available", "source"):
            assert key in result

    def test_custom_fallback_apy_propagated(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = get_pendle_apy(fallback_apy=9.9)
        assert result["apy"] == pytest.approx(9.9)


# ── 8. test_days_to_maturity_calculation ────────────────────────────────────

class TestDaysToMaturityCalculation:
    """_days_to_maturity() and _parse_maturity() produce correct values."""

    def test_future_date_positive_days(self):
        future = datetime.date.today() + datetime.timedelta(days=90)
        assert _days_to_maturity(future) == 90

    def test_past_date_returns_zero(self):
        past = datetime.date.today() - datetime.timedelta(days=5)
        assert _days_to_maturity(past) == 0

    def test_today_returns_zero(self):
        assert _days_to_maturity(datetime.date.today()) == 0

    def test_none_returns_zero(self):
        assert _days_to_maturity(None) == 0

    def test_parse_maturity_iso_with_time(self):
        d = _parse_maturity("2026-06-27T00:00:00.000Z")
        assert d == datetime.date(2026, 6, 27)

    def test_parse_maturity_plain_date(self):
        d = _parse_maturity("2026-12-31")
        assert d == datetime.date(2026, 12, 31)

    def test_parse_maturity_empty_returns_none(self):
        assert _parse_maturity("") is None
        assert _parse_maturity(None) is None  # type: ignore[arg-type]

    def test_parse_maturity_invalid_returns_none(self):
        assert _parse_maturity("not-a-date") is None

    def test_market_days_to_maturity_in_adapter(self):
        """End-to-end: adapter correctly reflects days_to_maturity from expiry."""
        future_days = 90
        raw = [_make_raw_market(days_to_expiry=future_days)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets()
        assert len(markets) == 1
        # Allow ±1 day for test execution timing
        assert abs(markets[0].days_to_maturity - future_days) <= 1


# ── 9. test_maturity_window_filter ──────────────────────────────────────────

class TestMaturityWindowFilter:
    """Markets outside the allowed maturity window are excluded."""

    def test_too_far_maturity_excluded(self):
        raw = [_make_raw_market(days_to_expiry=400)]  # 400 > 365
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(max_days_to_maturity=365)
        assert markets == []

    def test_too_close_maturity_excluded(self):
        raw = [_make_raw_market(days_to_expiry=3)]  # 3 < 7
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(min_days_to_maturity=7)
        assert markets == []

    def test_in_window_passes(self):
        raw = [_make_raw_market(days_to_expiry=90)]
        adapter = PendlePTAdapter()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            markets = adapter.get_top_markets(min_days_to_maturity=7, max_days_to_maturity=365)
        assert len(markets) == 1


# ── 10. test_get_pendle_apy_live_path ────────────────────────────────────────

class TestGetPendleApyLivePath:
    """get_pendle_apy() returns correct live data when API responds."""

    def test_returns_live_apy_from_best_market(self):
        raw = [_make_raw_market(implied_apy=0.093, tvl_usd=20_000_000.0, days_to_expiry=120)]
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            result = get_pendle_apy()

        assert result["source"] == "pendle_api"
        assert result["is_available"] is True
        assert result["apy"] == pytest.approx(9.3, abs=0.01)

    def test_id_and_tier_correct(self):
        raw = [_make_raw_market(implied_apy=0.080, days_to_expiry=60)]
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(raw)):
            result = get_pendle_apy()
        assert result["id"] == "pendle_pt"
        assert result["tier"] == "T2"


# ── 11. test_parse_market_unit ───────────────────────────────────────────────

class TestParseMarketUnit:
    """Unit tests for _parse_market() in isolation."""

    def test_valid_market_parsed(self):
        raw = _make_raw_market()
        m = _parse_market(raw)
        assert isinstance(m, PendleMarketData)

    def test_missing_address_returns_none(self):
        raw = _make_raw_market()
        raw["address"] = ""
        assert _parse_market(raw) is None

    def test_tvl_as_plain_float(self):
        """Some API versions may return tvl as a plain float, not nested dict."""
        raw = _make_raw_market()
        raw["tvl"] = 50_000_000.0  # plain float instead of {"usd": "..."}
        m = _parse_market(raw)
        assert m is not None
        assert m.tvl_usd == pytest.approx(50_000_000.0)

    def test_liquidity_as_plain_float(self):
        raw = _make_raw_market()
        raw["liquidity"] = 3_000_000.0
        m = _parse_market(raw)
        assert m is not None
        assert m.liquidity_usd == pytest.approx(3_000_000.0)

    def test_apy_decimal_to_percent_conversion(self):
        raw = _make_raw_market(implied_apy=0.075)
        m = _parse_market(raw)
        assert m is not None
        assert m.pt_apy == pytest.approx(7.5, abs=0.01)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
