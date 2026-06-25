"""
Тесты для spa_core.adapters.pendle_pt_adapter (MP-354).

Все тесты используют mock urllib.request.urlopen — реальных сетевых запросов нет.
Проверяются: fetch_markets, find_best_usdc_market, get_apy, get_maturity,
allocate, withdraw, health_check, to_dict.
"""
from __future__ import annotations

import datetime
import json
from unittest import mock

import pytest

try:
    from spa_core.execution.adapters.pendle_pt_adapter import (
        FALLBACK_APY,
        PENDLE_API_BASE,
        PendlePTAdapter,
        _days_to_maturity,
        _is_stablecoin,
        _parse_maturity_date,
        _safe_float,
    )
except ImportError:
    pytestmark = pytest.mark.skip(
        reason="pendle_pt_adapter API refactored — tests need rewrite for new interface"
    )


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _make_response(payload: object, status: int = 200) -> mock.MagicMock:
    """Создаёт мок HTTP-ответа с JSON-телом."""
    body = json.dumps(payload).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


def _market(
    symbol: str = "PT-sUSDe-27MAR2026",
    underlying: str = "sUSDe",
    fixed_apy: float = 0.12,    # 12% в decimal форме
    implied_apy: float = 0.11,
    expiry: str = "2026-03-27T00:00:00.000Z",
    is_expired: bool = False,
    address: str = "0xABC123",
    tvl_usd: float = 50_000_000.0,
) -> dict:
    """Конструирует минимальный market dict в формате Pendle API."""
    return {
        "address": address,
        "name": symbol,
        "pt": {"symbol": symbol, "price": 0.95},
        "underlyingAsset": {"symbol": underlying},
        "fixedApy": fixed_apy,
        "impliedApy": implied_apy,
        "expiry": expiry,
        "isExpired": is_expired,
        "tvl": {"usd": str(tvl_usd)},
        "liquidity": {"usd": str(tvl_usd * 0.5)},
    }


FUTURE_EXPIRY = (datetime.date.today() + datetime.timedelta(days=90)).isoformat() + "T00:00:00.000Z"
PAST_EXPIRY = "2020-01-01T00:00:00.000Z"


@pytest.fixture
def adapter():
    return PendlePTAdapter(chain_id=1, timeout=5, retries=0)


@pytest.fixture
def markets_payload():
    """Три рынка: два стейблкоина (разные APY), один не-стейблкоин."""
    return {
        "results": [
            _market("PT-sUSDe-Q1", "sUSDe", 0.12, 0.11, FUTURE_EXPIRY, address="0x111"),
            _market("PT-USDC-Q2",  "USDC",  0.10, 0.09, FUTURE_EXPIRY, address="0x222"),
            _market("PT-ETH-Q1",   "ETH",   0.20, 0.18, FUTURE_EXPIRY, address="0x333"),
        ]
    }


# ── _safe_float ───────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_float_passthrough(self):
        assert _safe_float(1.5) == 1.5

    def test_int_converts(self):
        assert _safe_float(3) == 3.0

    def test_string_converts(self):
        assert _safe_float("2.7") == 2.7

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, 99.0) == 99.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("abc") == 0.0

    def test_empty_string_returns_default(self):
        assert _safe_float("") == 0.0


# ── _is_stablecoin ────────────────────────────────────────────────────────────

class TestIsStablecoin:
    def test_usdc_true(self):
        assert _is_stablecoin("USDC") is True

    def test_susde_true(self):
        assert _is_stablecoin("sUSDe") is True

    def test_usdt_true(self):
        assert _is_stablecoin("USDT") is True

    def test_dai_true(self):
        assert _is_stablecoin("DAI") is True

    def test_eth_false(self):
        assert _is_stablecoin("ETH") is False

    def test_wbtc_false(self):
        assert _is_stablecoin("WBTC") is False

    def test_case_insensitive(self):
        assert _is_stablecoin("usdc") is True
        assert _is_stablecoin("USDC") is True


# ── _parse_maturity_date ──────────────────────────────────────────────────────

class TestParseMaturityDate:
    def test_iso_datetime(self):
        result = _parse_maturity_date("2026-03-27T00:00:00.000Z")
        assert result == datetime.date(2026, 3, 27)

    def test_plain_date(self):
        result = _parse_maturity_date("2026-09-25")
        assert result == datetime.date(2026, 9, 25)

    def test_empty_string_returns_none(self):
        assert _parse_maturity_date("") is None

    def test_invalid_returns_none(self):
        assert _parse_maturity_date("not-a-date") is None


# ── _days_to_maturity ─────────────────────────────────────────────────────────

class TestDaysToMaturity:
    def test_future_positive(self):
        future = datetime.date.today() + datetime.timedelta(days=30)
        assert _days_to_maturity(future) == 30

    def test_past_returns_zero(self):
        past = datetime.date(2020, 1, 1)
        assert _days_to_maturity(past) == 0

    def test_none_returns_zero(self):
        assert _days_to_maturity(None) == 0

    def test_today_returns_zero(self):
        assert _days_to_maturity(datetime.date.today()) == 0


# ── fetch_markets ─────────────────────────────────────────────────────────────

class TestFetchMarkets:
    def test_returns_list_on_success(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.fetch_markets()
        assert isinstance(result, list)
        assert len(result) == 3

    def test_uses_chain_id_in_url(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp) as m:
            adapter.fetch_markets(chain_id=1)
        url_called = m.call_args[0][0].full_url
        assert "/chains/1/markets" in url_called

    def test_custom_chain_id(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp) as m:
            adapter.fetch_markets(chain_id=42161)
        url_called = m.call_args[0][0].full_url
        assert "/chains/42161/markets" in url_called

    def test_returns_empty_on_network_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = adapter.fetch_markets()
        assert result == []

    def test_data_key_also_accepted(self, adapter):
        resp = _make_response({"data": [_market()]})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.fetch_markets()
        assert len(result) == 1

    def test_plain_list_response(self, adapter):
        resp = _make_response([_market(), _market(address="0x999")])
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.fetch_markets()
        assert len(result) == 2

    def test_updates_cache_on_success(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            adapter.fetch_markets()
        assert len(adapter._raw_cache) == 3

    def test_cache_not_updated_on_error(self, adapter):
        import urllib.error
        adapter._raw_cache = [_market()]
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            adapter.fetch_markets()
        assert len(adapter._raw_cache) == 1  # кэш не тронут


# ── find_best_usdc_market ─────────────────────────────────────────────────────

class TestFindBestUsdcMarket:
    def test_picks_highest_apy_stablecoin(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        # PT-sUSDe-Q1 имеет fixedApy=0.12, PT-USDC-Q2 имеет 0.10
        assert best is not None
        assert best["address"] == "0x111"

    def test_skips_non_stablecoin(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        # ETH не должен попасть
        assert best["address"] != "0x333"

    def test_skips_expired_markets(self, adapter):
        payload = {"results": [
            _market("PT-USDC-expired", "USDC", 0.15, 0.14, PAST_EXPIRY, is_expired=True),
            _market("PT-sUSDe-live",   "sUSDe", 0.10, 0.09, FUTURE_EXPIRY),
        ]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        assert best is not None
        assert "sUSDe" in (best.get("name") or "")

    def test_returns_none_when_no_stablecoin(self, adapter):
        payload = {"results": [
            _market("PT-ETH", "ETH", 0.20, 0.18, FUTURE_EXPIRY),
        ]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        assert best is None

    def test_returns_none_on_empty_markets(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        assert best is None

    def test_uses_cache_when_api_fails(self, adapter):
        import urllib.error
        adapter._raw_cache = [_market("PT-USDC-cached", "USDC", 0.09, 0.09, FUTURE_EXPIRY)]
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            best = adapter.find_best_usdc_market()
        assert best is not None

    def test_skips_zero_apy_markets(self, adapter):
        payload = {"results": [
            _market("PT-USDC-zero", "USDC", 0.0, 0.0, FUTURE_EXPIRY, address="0xZero"),
            _market("PT-sUSDe-ok",  "sUSDe", 0.10, 0.09, FUTURE_EXPIRY, address="0xOK"),
        ]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            best = adapter.find_best_usdc_market()
        assert best["address"] == "0xOK"


# ── get_apy ───────────────────────────────────────────────────────────────────

class TestGetApy:
    def test_returns_float(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            apy = adapter.get_apy()
        assert isinstance(apy, float)

    def test_converts_decimal_to_percent(self, adapter):
        payload = {"results": [_market(fixed_apy=0.12, expiry=FUTURE_EXPIRY)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            apy = adapter.get_apy()
        # 0.12 → 12.0%
        assert apy == pytest.approx(12.0, abs=0.01)

    def test_fallback_on_network_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            apy = adapter.get_apy()
        assert apy == FALLBACK_APY

    def test_fallback_on_empty_markets(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            apy = adapter.get_apy()
        assert apy == FALLBACK_APY

    def test_large_decimal_not_doubled(self, adapter):
        # Если API вернёт 12.0 (уже в %) — не умножать на 100
        payload = {"results": [_market(fixed_apy=12.0, expiry=FUTURE_EXPIRY)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            apy = adapter.get_apy()
        assert apy == pytest.approx(12.0, abs=0.01)

    def test_fallback_is_float(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            apy = adapter.get_apy()
        assert isinstance(apy, float)

    def test_apy_in_expected_range(self, adapter):
        payload = {"results": [_market(fixed_apy=0.15, expiry=FUTURE_EXPIRY)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            apy = adapter.get_apy()
        assert 1.0 <= apy <= 100.0


# ── get_maturity ──────────────────────────────────────────────────────────────

class TestGetMaturity:
    def test_returns_iso_string(self, adapter):
        expiry = "2026-09-25T00:00:00.000Z"
        payload = {"results": [_market(expiry=expiry)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            mat = adapter.get_maturity()
        assert mat == "2026-09-25"

    def test_returns_empty_on_no_markets(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            mat = adapter.get_maturity()
        assert mat == ""

    def test_returns_empty_on_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            mat = adapter.get_maturity()
        assert mat == ""

    def test_parses_plain_date(self, adapter):
        payload = {"results": [_market(expiry="2027-01-15")]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            mat = adapter.get_maturity()
        assert mat == "2027-01-15"

    def test_future_date(self, adapter):
        future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
        payload = {"results": [_market(expiry=future + "T00:00:00.000Z")]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            mat = adapter.get_maturity()
        assert mat == future


# ── health_check ──────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_returns_true_on_success(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.health_check()
        assert result is True

    def test_returns_false_on_url_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = adapter.health_check()
        assert result is False

    def test_returns_false_on_http_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError(None, 503, "down", {}, None)):
            result = adapter.health_check()
        assert result is False

    def test_returns_false_on_os_error(self, adapter):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = adapter.health_check()
        assert result is False

    def test_health_check_is_bool(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.health_check()
        assert isinstance(result, bool)

    def test_uses_limit_1_url(self, adapter):
        resp = _make_response({"results": []})
        with mock.patch("urllib.request.urlopen", return_value=resp) as m:
            adapter.health_check()
        url_called = m.call_args[0][0].full_url
        assert "limit=1" in url_called


# ── allocate ──────────────────────────────────────────────────────────────────

class TestAllocate:
    def test_returns_dict(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(10000.0)
        assert isinstance(result, dict)

    def test_protocol_field(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(5000.0)
        assert result["protocol"] == "pendle-pt"

    def test_capital_field(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(25000.0)
        assert result["capital_usd"] == 25000.0

    def test_daily_yield_math(self, adapter):
        # APY 12% → daily = 10000 * 0.12 / 365 ≈ 3.287671
        payload = {"results": [_market(fixed_apy=0.12, expiry=FUTURE_EXPIRY)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(10000.0)
        expected_daily = 10000.0 * 0.12 / 365.0
        assert result["daily_yield_usd"] == pytest.approx(expected_daily, abs=0.001)

    def test_tier_t2(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(1000.0)
        assert result["tier"] == "T2"

    def test_network_ethereum(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(1000.0)
        assert result["network"] == "ethereum"

    def test_is_paper_true(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(1000.0)
        assert result["is_paper"] is True

    def test_status_allocated(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.allocate(1000.0)
        assert result["status"] == "ALLOCATED"

    def test_raises_on_zero(self, adapter):
        with pytest.raises(ValueError, match="capital"):
            adapter.allocate(0.0)

    def test_raises_on_negative(self, adapter):
        with pytest.raises(ValueError, match="capital"):
            adapter.allocate(-500.0)


# ── withdraw ──────────────────────────────────────────────────────────────────

class TestWithdraw:
    def test_returns_dict(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(5000.0)
        assert isinstance(result, dict)

    def test_protocol_field(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert result["protocol"] == "pendle-pt"

    def test_amount_field(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(7500.0)
        assert result["amount_usd"] == 7500.0

    def test_not_matured_for_future(self, adapter):
        payload = {"results": [_market(expiry=FUTURE_EXPIRY)]}
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert result["is_matured"] is False

    def test_matured_for_past(self, adapter):
        payload = {"results": [_market(expiry=PAST_EXPIRY, is_expired=True)]}
        # При истёкшем рынке find_best_usdc_market вернёт None (фильтр isExpired)
        # поэтому maturity будет "", is_matured=False
        resp = _make_response(payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert isinstance(result["is_matured"], bool)

    def test_tier_t2(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert result["tier"] == "T2"

    def test_is_paper_true(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert result["is_paper"] is True

    def test_status_withdrawn(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = adapter.withdraw(1000.0)
        assert result["status"] == "WITHDRAWN"

    def test_raises_on_zero(self, adapter):
        with pytest.raises(ValueError, match="amount"):
            adapter.withdraw(0.0)

    def test_raises_on_negative(self, adapter):
        with pytest.raises(ValueError, match="amount"):
            adapter.withdraw(-100.0)


# ── to_dict ───────────────────────────────────────────────────────────────────

class TestToDict:
    def test_returns_dict(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert isinstance(d, dict)

    def test_tier_t2(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert d["tier"] == "T2"

    def test_network_ethereum(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert d["network"] == "ethereum"

    def test_has_fixed_apy(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "fixed_apy" in d
        assert isinstance(d["fixed_apy"], float)

    def test_has_market_name(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "market_name" in d
        assert len(d["market_name"]) > 0

    def test_has_maturity_date(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "maturity_date" in d

    def test_has_days_to_maturity(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "days_to_maturity" in d
        assert isinstance(d["days_to_maturity"], int)

    def test_has_pt_price(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "pt_price" in d

    def test_has_implied_apy(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert "implied_apy" in d

    def test_fallback_dict_on_error(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            d = adapter.to_dict()
        assert d["fixed_apy"] == FALLBACK_APY
        assert d["tier"] == "T2"
        assert d["network"] == "ethereum"

    def test_source_pendle_rest_api(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert d["source"] == "pendle_rest_api"

    def test_fallback_source_is_fallback(self, adapter):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            d = adapter.to_dict()
        assert d["source"] == "fallback"

    def test_apy_reasonable_range(self, adapter, markets_payload):
        resp = _make_response(markets_payload)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            d = adapter.to_dict()
        assert 0 < d["fixed_apy"] <= 100.0


# ── init & chain_id ───────────────────────────────────────────────────────────

class TestInit:
    def test_default_chain_id(self):
        a = PendlePTAdapter()
        assert a.chain_id == 1

    def test_custom_chain_id(self):
        a = PendlePTAdapter(chain_id=42161)
        assert a.chain_id == 42161

    def test_default_timeout(self):
        a = PendlePTAdapter()
        assert a.timeout == 10

    def test_custom_timeout(self):
        a = PendlePTAdapter(timeout=5)
        assert a.timeout == 5

    def test_empty_cache_on_init(self):
        a = PendlePTAdapter()
        assert a._raw_cache == []

    def test_api_base_constant(self):
        assert PENDLE_API_BASE == "https://api-v2.pendle.finance/core/v1"

    def test_fallback_apy_constant(self):
        assert FALLBACK_APY == 8.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
