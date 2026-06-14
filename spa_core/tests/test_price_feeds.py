"""
Tests for PriceFeedFetcher (FEAT-006 Phase 1).

12 deterministic pure-Python tests. No DB, no network, no sleep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_pipeline.price_feeds import PriceFeedFetcher


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fetcher() -> PriceFeedFetcher:
    return PriceFeedFetcher()


# ─── Synthetic generator ──────────────────────────────────────────────────────


def test_synthetic_returns_all_stablecoins(fetcher):
    """fetch_prices_synthetic returns exactly the 4 stablecoins."""
    prices = fetcher.fetch_prices_synthetic()
    assert set(prices.keys()) == set(PriceFeedFetcher.STABLECOINS)
    assert len(prices) == 4


def test_synthetic_prices_near_one(fetcher):
    """Every synthetic price sits inside [0.99, 1.01]."""
    prices = fetcher.fetch_prices_synthetic()
    for sym, price in prices.items():
        assert 0.99 <= price <= 1.01, f"{sym} drifted: {price}"


def test_synthetic_is_deterministic(fetcher):
    """Same seed → byte-identical dict."""
    a = fetcher.fetch_prices_synthetic(seed=123)
    b = fetcher.fetch_prices_synthetic(seed=123)
    assert a == b
    # Different seed should (almost certainly) differ at least one value
    c = fetcher.fetch_prices_synthetic(seed=124)
    assert a != c


# ─── Depeg detection ──────────────────────────────────────────────────────────


def test_detect_depeg_empty_when_pegged(fetcher):
    """All prices at $1.00 → no depeg events."""
    prices = {sym: 1.0 for sym in PriceFeedFetcher.STABLECOINS}
    assert fetcher.detect_depeg(prices) == []


def test_detect_depeg_warn(fetcher):
    """price 1.025 with threshold 0.02 → WARN severity (|dev|=2.5%, < 4%)."""
    prices = {"USDC": 1.025}
    events = fetcher.detect_depeg(prices, threshold=0.02)
    assert len(events) == 1
    assert events[0]["symbol"] == "USDC"
    assert events[0]["severity"] == "WARN"


def test_detect_depeg_critical(fetcher):
    """price 0.94 with threshold 0.02 → CRITICAL (|dev|=6% ≥ 4%)."""
    prices = {"DAI": 0.94}
    events = fetcher.detect_depeg(prices, threshold=0.02)
    assert len(events) == 1
    assert events[0]["symbol"] == "DAI"
    assert events[0]["severity"] == "CRITICAL"


def test_detect_depeg_default_threshold(fetcher):
    """When threshold=None, DEFAULT_DEPEG_THRESHOLD (0.02) is used."""
    # 1.015 deviation = 1.5% which is < 2% default threshold → no event
    prices_pegged = {"USDT": 1.015}
    assert fetcher.detect_depeg(prices_pegged, threshold=None) == []
    # 1.03 deviation = 3% → WARN under default 0.02 threshold
    prices_warn = {"USDT": 1.03}
    events = fetcher.detect_depeg(prices_warn, threshold=None)
    assert len(events) == 1
    assert events[0]["severity"] == "WARN"


def test_detect_depeg_returns_deviation_pct(fetcher):
    """deviation_pct is a signed percentage value (price - 1.0) * 100."""
    prices = {"USDC": 0.95, "USDT": 1.06}
    events = fetcher.detect_depeg(prices, threshold=0.02)
    by_sym = {e["symbol"]: e for e in events}
    assert by_sym["USDC"]["deviation_pct"] == pytest.approx(-5.0, abs=1e-6)
    assert by_sym["USDT"]["deviation_pct"] == pytest.approx(6.0, abs=1e-6)
    # Required keys present
    for ev in events:
        assert set(ev.keys()) == {"symbol", "price", "deviation_pct", "severity"}


# ─── JSON dump ────────────────────────────────────────────────────────────────


def test_dump_prices_json_writes_file(fetcher, tmp_path):
    """dump_prices_json creates the target file."""
    out = tmp_path / "price_feeds.json"
    returned = fetcher.dump_prices_json(out_path=out)
    assert returned == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_dump_prices_json_schema(fetcher, tmp_path):
    """Dumped JSON contains the documented top-level keys."""
    out = tmp_path / "price_feeds.json"
    fetcher.dump_prices_json(out_path=out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload.keys()) >= {"timestamp", "prices", "depeg_events", "threshold"}
    assert isinstance(payload["prices"], dict)
    assert set(payload["prices"].keys()) == set(PriceFeedFetcher.STABLECOINS)
    assert isinstance(payload["depeg_events"], list)
    assert payload["threshold"] == PriceFeedFetcher.DEFAULT_DEPEG_THRESHOLD


# ─── fetch_prices wrapper ─────────────────────────────────────────────────────


def test_fetch_prices_synthetic_branch(fetcher):
    """fetch_prices(use_synthetic=True) returns 4 keys, all near $1.00."""
    prices = fetcher.fetch_prices(use_synthetic=True)
    assert set(prices.keys()) == set(PriceFeedFetcher.STABLECOINS)
    for price in prices.values():
        assert 0.99 <= price <= 1.01


def test_fetch_prices_rpc_falls_back_to_synthetic(fetcher):
    """When all RPCs return None (Phase 1 scaffold), the synthetic
    backup is used so every coin still ends up with a price."""
    prices = fetcher.fetch_prices(use_synthetic=False)
    assert set(prices.keys()) == set(PriceFeedFetcher.STABLECOINS)
    for sym, price in prices.items():
        # Fallback values come from the deterministic synthetic generator
        assert 0.99 <= price <= 1.01, f"{sym} fallback out of band: {price}"


# ─── Scaffold sanity ──────────────────────────────────────────────────────────


def test_rpc_endpoints_have_three_per_coin():
    """Every stablecoin has exactly 3 RPC endpoints configured."""
    for sym in PriceFeedFetcher.STABLECOINS:
        endpoints = PriceFeedFetcher.RPC_ENDPOINTS[sym]
        assert len(endpoints) == 3, f"{sym} has {len(endpoints)} endpoints, expected 3"
        for url in endpoints:
            assert url.startswith("https://"), f"{sym} endpoint not https: {url}"
