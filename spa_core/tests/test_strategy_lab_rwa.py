"""Tests for spa_core.strategy_lab.data.rwa_feed — the LIVE tokenized-T-bill risk-free floor.

Hermetic: every RWAFeed takes an injected `fetcher` (url -> json); no network. The config
wiring is exercised by monkeypatching rwa_feed.current_rwa_floor_pct so we never touch disk
or network and can assert both the live-rate path and the fail-safe fallback to the committed
literal.

What the floor must be (per docs/RESEARCH_EXPANSION_2026-06-25.md): a TVL-weighted blend of the
native tokenized-Treasury issuer pools (BUIDL/USYC/USDY/OUSG/USTB/TBILL), ~3.3–3.5%, replacing
the hardcoded 4.5% — with the literal kept ONLY as a conservative offline fallback.
"""
# LLM_FORBIDDEN
import json
import os
import tempfile
from pathlib import Path

import pytest

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data import rwa_feed as RWA
from spa_core.strategy_lab.data.rwa_feed import RWAFeed
from spa_core.strategy_lab import config as cfg


# ── fake fetcher (url-substring routing, mirrors http_fetch) ──────────────────────────────────
class FakeFetcher:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for needle, payload in self.routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"no fake route for {url}")


# ── canonical good /pools payload (native tokenized-T-bill issuer pools) ──────────────────────
def good_pools():
    return {"status": "success", "data": [
        # Qualifying native issuer pools (TVL ≥ $5M, sane apy).
        {"project": "circle-usyc",      "symbol": "USYC",  "chain": "BSC",
         "apy": 3.16, "tvlUsd": 3_043_000_000.0, "pool": "p-usyc"},
        {"project": "ondo-yield-assets", "symbol": "USDY", "chain": "Ethereum",
         "apy": 3.55, "tvlUsd": 1_111_000_000.0, "pool": "p-usdy"},
        {"project": "blackrock-buidl",  "symbol": "BUIDL", "chain": "Ethereum",
         "apy": 3.54, "tvlUsd": 830_000_000.0, "pool": "p-buidl"},
        {"project": "ondo-yield-assets", "symbol": "OUSG", "chain": "Ethereum",
         "apy": 3.80, "tvlUsd": 255_000_000.0, "pool": "p-ousg"},
        {"project": "invesco-ustb",     "symbol": "USTB",  "chain": "Ethereum",
         "apy": 3.77, "tvlUsd": 605_000_000.0, "pool": "p-ustb"},
        {"project": "openeden-tbill",   "symbol": "TBILL", "chain": "Ethereum",
         "apy": 3.29, "tvlUsd": 33_000_000.0, "pool": "p-tbill"},
        # NOISE that must be excluded:
        # 1) a dust mirror of an issuer pool (below TVL floor)
        {"project": "blackrock-buidl",  "symbol": "BUIDL", "chain": "Arbitrum",
         "apy": 3.20, "tvlUsd": 100.0, "pool": "p-buidl-dust"},
        # 2) a 0% flux re-listing (out of sane band)
        {"project": "flux-finance",     "symbol": "OUSG",  "chain": "Ethereum",
         "apy": 0.0, "tvlUsd": 38_000_000.0, "pool": "p-flux"},
        # 3) an unrelated high-yield LP that contains a T-bill token (wrong project)
        {"project": "camelot-v3",       "symbol": "USDY-USDC", "chain": "Arbitrum",
         "apy": 42.0, "tvlUsd": 7_000_000.0, "pool": "p-lp"},
    ]}


def _temp_cache(tmp):
    return Path(tmp) / "rwa_floor.json"


# ── matching / computation ────────────────────────────────────────────────────────────────────
def test_matches_only_native_tbill_pools():
    with tempfile.TemporaryDirectory() as tmp:
        feed = RWAFeed(fetcher=FakeFetcher({"pools": good_pools()}), cache_path=_temp_cache(tmp))
        res = feed.compute()
    labels = {p["label"] for p in res["pools"]}
    # 6 native issuer pools qualify; dust/0%/LP excluded.
    assert res["n_pools"] == 6
    assert labels == {
        "circle-usyc:USYC", "ondo-yield-assets:USDY", "blackrock-buidl:BUIDL",
        "ondo-yield-assets:OUSG", "invesco-ustb:USTB", "openeden-tbill:TBILL",
    }
    assert "camelot-v3:USDY-USDC" not in labels  # LP excluded
    assert all(p["tvl_usd"] >= RWA.DEFAULT_TVL_FLOOR_USD for p in res["pools"])


def test_tvl_weighted_floor_is_realistic():
    with tempfile.TemporaryDirectory() as tmp:
        feed = RWAFeed(fetcher=FakeFetcher({"pools": good_pools()}), cache_path=_temp_cache(tmp))
        res = feed.compute()
    # Hand-computed TVL-weighted mean of the 6 qualifying pools.
    pools = [
        (3.16, 3_043_000_000.0), (3.55, 1_111_000_000.0), (3.54, 830_000_000.0),
        (3.80, 255_000_000.0), (3.77, 605_000_000.0), (3.29, 33_000_000.0),
    ]
    tot = sum(t for _, t in pools)
    expected = sum(a * t for a, t in pools) / tot
    assert res["method"] == "tvl_weighted"
    assert res["floor_apy_pct"] == pytest.approx(expected, abs=1e-6)
    assert res["floor_apy_pct"] == pytest.approx(res["tvl_weighted_apy_pct"], abs=1e-9)
    # Sits in the documented ~3.3–3.5% band (USYC's $3B dominates the weight).
    assert 3.0 <= res["floor_apy_pct"] <= 3.6
    # Median is computed and differs from the weighted mean.
    assert res["median_apy_pct"] == pytest.approx(3.545, abs=1e-6)


def test_tvl_floor_drops_dust_and_band_drops_zero_and_extreme():
    """A custom higher TVL floor drops the smaller real pools too — proving the filter works."""
    with tempfile.TemporaryDirectory() as tmp:
        feed = RWAFeed(
            fetcher=FakeFetcher({"pools": good_pools()}),
            tvl_floor_usd=500_000_000.0,
            cache_path=_temp_cache(tmp),
        )
        res = feed.compute()
    labels = {p["label"] for p in res["pools"]}
    # Only pools ≥ $500M: USYC, USDY, BUIDL, USTB.
    assert labels == {
        "circle-usyc:USYC", "ondo-yield-assets:USDY",
        "blackrock-buidl:BUIDL", "invesco-ustb:USTB",
    }


# ── schema validation: fail-CLOSED, no fabrication ────────────────────────────────────────────
def test_raises_on_non_success_status():
    feed = RWAFeed(fetcher=FakeFetcher({"pools": {"status": "error", "data": []}}))
    with pytest.raises(InvalidDataError):
        feed.compute()


def test_raises_on_empty_data():
    feed = RWAFeed(fetcher=FakeFetcher({"pools": {"status": "success", "data": []}}))
    with pytest.raises(InvalidDataError):
        feed.compute()


def test_raises_on_non_object_payload():
    feed = RWAFeed(fetcher=FakeFetcher({"pools": ["not", "an", "object"]}))
    with pytest.raises(InvalidDataError):
        feed.compute()


def test_raises_when_too_few_pools_qualify():
    """Only one native pool present → below min_pools (2) → fail-CLOSED, never a 1-pool floor."""
    one = {"status": "success", "data": [
        {"project": "circle-usyc", "symbol": "USYC", "chain": "BSC",
         "apy": 3.16, "tvlUsd": 3_043_000_000.0, "pool": "p-usyc"},
    ]}
    feed = RWAFeed(fetcher=FakeFetcher({"pools": one}))
    with pytest.raises(InvalidDataError):
        feed.compute()


def test_raises_when_all_pools_below_floor():
    dust = {"status": "success", "data": [
        {"project": "circle-usyc", "symbol": "USYC", "chain": "BSC",
         "apy": 3.16, "tvlUsd": 100.0, "pool": "p1"},
        {"project": "blackrock-buidl", "symbol": "BUIDL", "chain": "Ethereum",
         "apy": 3.54, "tvlUsd": 100.0, "pool": "p2"},
    ]}
    feed = RWAFeed(fetcher=FakeFetcher({"pools": dust}))
    with pytest.raises(InvalidDataError):
        feed.compute()


# ── caching: atomic write + fresh-serve ───────────────────────────────────────────────────────
def test_refresh_writes_atomic_cache_and_current_serves_it():
    with tempfile.TemporaryDirectory() as tmp:
        cache = _temp_cache(tmp)
        fetcher = FakeFetcher({"pools": good_pools()})
        feed = RWAFeed(fetcher=fetcher, cache_path=cache)
        res = feed.refresh()
        assert cache.exists()
        on_disk = json.loads(cache.read_text())
        assert on_disk["floor_apy_pct"] == res["floor_apy_pct"]
        assert "generated_at" in on_disk
        # No leftover temp files in the cache dir.
        assert not [p for p in Path(tmp).iterdir() if p.suffix == ".tmp"]

        # Fresh cache is served WITHOUT a second fetch.
        n_calls = len(fetcher.calls)
        val = feed.current_rwa_floor_pct(max_age_hours=24.0)
        assert val == pytest.approx(res["floor_apy_pct"])
        assert len(fetcher.calls) == n_calls  # served from cache, no refetch


def test_current_refetches_when_cache_stale():
    with tempfile.TemporaryDirectory() as tmp:
        cache = _temp_cache(tmp)
        # Write a stale cache by hand (old timestamp).
        cache.write_text(json.dumps({
            "floor_apy_pct": 9.99, "generated_at": "2000-01-01T00:00:00+00:00",
        }))
        fetcher = FakeFetcher({"pools": good_pools()})
        feed = RWAFeed(fetcher=fetcher, cache_path=cache)
        val = feed.current_rwa_floor_pct(max_age_hours=1.0)
        assert val != pytest.approx(9.99)          # stale value not used
        assert any("pools" in u for u in fetcher.calls)  # it refetched


def test_current_falls_back_to_stale_cache_when_fetch_fails():
    """Fetch fails but a (stale) cache exists → serve cache, do not crash (fail-safe)."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = _temp_cache(tmp)
        cache.write_text(json.dumps({
            "floor_apy_pct": 3.42, "generated_at": "2000-01-01T00:00:00+00:00",
        }))
        feed = RWAFeed(
            fetcher=FakeFetcher({"pools": FetchBoom()}), cache_path=cache,
        )
        assert feed.current_rwa_floor_pct(max_age_hours=1.0) == pytest.approx(3.42)


def test_current_raises_when_fetch_fails_and_no_cache():
    with tempfile.TemporaryDirectory() as tmp:
        feed = RWAFeed(
            fetcher=FakeFetcher({"pools": FetchBoom()}), cache_path=_temp_cache(tmp),
        )
        with pytest.raises(Exception):
            feed.current_rwa_floor_pct()


class FetchBoom(Exception):
    pass


# ── history: per-date TVL-weighted series ─────────────────────────────────────────────────────
def _chart(points):
    return {"status": "success", "data": [
        {"timestamp": ts, "apy": apy} for ts, apy in points
    ]}


def test_history_builds_tvl_weighted_series():
    routes = {
        "pools": good_pools(),
        # only need two pools' charts for the weighting check; route by pool id in url
        "chart/p-usyc": _chart([("2026-06-10T12:00:00Z", 3.10), ("2026-06-11T12:00:00Z", 3.20)]),
        "chart/p-usdy": _chart([("2026-06-10T12:00:00Z", 3.60), ("2026-06-11T12:00:00Z", 3.50)]),
        "chart/p-buidl": _chart([("2026-06-10T12:00:00Z", 3.50)]),
        "chart/p-ousg": _chart([("2026-06-10T12:00:00Z", 3.80)]),
        "chart/p-ustb": _chart([("2026-06-10T12:00:00Z", 3.70)]),
        "chart/p-tbill": _chart([("2026-06-10T12:00:00Z", 3.30)]),
    }
    feed = RWAFeed(fetcher=FakeFetcher(routes))
    series = feed.history("2026-06-10", "2026-06-11")
    assert set(series) == {"2026-06-10", "2026-06-11"}
    # 2026-06-11 only USYC ($3.043B @3.20) and USDY ($1.111B @3.50) have points → weighted.
    w_usyc, w_usdy = 3_043_000_000.0, 1_111_000_000.0
    expected = (3.20 * w_usyc + 3.50 * w_usdy) / (w_usyc + w_usdy)
    assert series["2026-06-11"] == pytest.approx(expected, abs=1e-6)


def test_history_raises_on_bad_chart_schema():
    routes = {"pools": good_pools(), "chart/": {"status": "error", "data": []}}
    feed = RWAFeed(fetcher=FakeFetcher(routes))
    with pytest.raises(InvalidDataError):
        feed.history("2026-06-10", "2026-06-11")


# ── config wiring: live rate when present, literal fallback when absent ────────────────────────
def test_config_returns_live_rate_when_feed_present(monkeypatch):
    monkeypatch.setattr(RWA, "current_rwa_floor_pct", lambda *a, **k: 3.37)
    # default (live on) → live rate, NOT the committed 4.5 literal
    assert cfg.rwa_floor_apy_pct() == pytest.approx(3.37)


def test_config_falls_back_to_literal_when_feed_unavailable(monkeypatch):
    def boom(*a, **k):
        raise InvalidDataError("feed down")
    monkeypatch.setattr(RWA, "current_rwa_floor_pct", boom)
    # feed raises → conservative committed literal (now 3.4, lowered toward the real floor so even
    # the fallback is not a 4.5% overstatement), backtest never crashes
    assert cfg.rwa_floor_apy_pct() == pytest.approx(3.4)


def test_config_live_false_pins_literal():
    # explicit live=False bypasses the feed entirely → committed literal (3.4)
    assert cfg.rwa_floor_apy_pct(live=False) == pytest.approx(3.4)


def test_baseline_and_metrics_pick_up_live_floor(monkeypatch):
    """The RWAFloor baseline and metrics.beats_rwa_floor read config → live rate flows through."""
    from spa_core.strategy_lab.strategies.baselines import RWAFloor
    from spa_core.strategy_lab import metrics as M

    monkeypatch.setattr(RWA, "current_rwa_floor_pct", lambda *a, **k: 3.30)

    # RWAFloor baseline accrues at the LIVE floor (it calls config, ignoring its init apy).
    s = RWAFloor()
    s.init(100_000.0, {"apy_pct": 99.0})  # config wins over this
    from spa_core.strategy_lab.base import MarketSnapshot
    for _ in range(365):
        s.step(MarketSnapshot(date="2026-06-10"))
    # ~3.30% over a year on $100k ≈ $3,300 (compounded daily) — clearly not 4.5%/99%.
    gained = s.equity() - 100_000.0
    assert 3_200.0 < gained < 3_400.0

    # metrics.beats_rwa_floor (no explicit floor) uses the live 3.30 floor:
    # 4.0% APY, 0.5% DD → excess 0.70 > DD 0.5 → True at the 3.30 floor (False at 4.5).
    assert M.beats_rwa_floor(4.0, 0.5) is True
