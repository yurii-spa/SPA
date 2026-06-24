"""
spa_core/tests/test_strategy_lab_data.py — Strategy Lab DATA LAYER tests.

All offline: every feed takes an injected `fetcher` callable (url -> json), so no network is
touched. The real fetch path (urllib) is only exercised by the feeds' __main__ on the Mac.

Coverage:
  - schema validation RAISES InvalidDataError on malformed / empty / missing-field responses
    (the critical fail-CLOSED behaviour) — funding (both venues), price (current + chart),
    restaking;
  - median funding across two venues (robust to a single-venue outlier);
  - MarketData forward-fill WITH limit + gap flagging beyond the limit;
  - MarketData.snapshot assembles a valid MarketSnapshot;
  - historical_range ascending ordering + bad-range rejection.
"""
# LLM_FORBIDDEN
import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.data.funding_feed import FundingFeed, BINANCE_URL, BYBIT_URL
from spa_core.strategy_lab.data.price_feed import PriceFeed, TOKENS, CHAIN
from spa_core.strategy_lab.data.restaking_feed import RestakingFeed
from spa_core.strategy_lab.data.market_data import MarketData


# ── fake fetchers (FakeFeed pattern) ─────────────────────────────────────────────────────────
class FakeFetcher:
    """Maps url-substring -> payload (or a callable raising). Mimics http_fetch(url)->json."""

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


# canonical good payloads ----------------------------------------------------------------------
def good_binance(rate="0.00010000", day_ms=1782288000000):
    # one entry per day (00:00, 08:00, 16:00 settle on the same UTC date)
    return [
        {"symbol": "ETHUSDT", "fundingTime": day_ms, "fundingRate": rate, "markPrice": "3000"},
    ]


def good_bybit(rate="0.00030000", day_ms=1782288000000):
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"category": "linear", "list": [
            {"symbol": "ETHUSDT", "fundingRate": rate, "fundingRateTimestamp": str(day_ms)},
        ]},
    }


def good_current():
    coins = {}
    for sym, addr in TOKENS.items():
        price = 3000.0 if sym == "eth" else 3090.0  # lrt slightly above eth
        coins[f"{CHAIN}:{addr}"] = {"price": price, "symbol": sym, "timestamp": 1, "confidence": 0.99}
    return {"coins": coins}


def good_chart_for(addr, price, ts=1782288000):
    return {"coins": {f"{CHAIN}:{addr}": {"symbol": "X", "prices": [{"timestamp": ts, "price": price}]}}}


def good_pools():
    return {"status": "success", "data": [
        {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH", "apy": 2.85, "tvlUsd": 2.8e9},
        {"project": "renzo", "chain": "Ethereum", "symbol": "EZETH", "apy": 1.94, "tvlUsd": 8e7},
    ]}


# ── FUNDING: schema validation raises ─────────────────────────────────────────────────────────
def test_funding_binance_not_list_raises():
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": {"oops": 1}, "bybit": good_bybit()}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_binance_empty_list_raises():
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": [], "bybit": good_bybit()}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_binance_missing_rate_raises():
    bad = [{"symbol": "ETHUSDT", "fundingTime": 1782288000000}]  # no fundingRate
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": bad, "bybit": good_bybit()}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_binance_empty_rate_raises():
    bad = [{"symbol": "ETHUSDT", "fundingTime": 1782288000000, "fundingRate": ""}]
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": bad, "bybit": good_bybit()}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_bybit_retcode_nonzero_raises():
    bad = {"retCode": 10001, "retMsg": "bad", "result": {"list": []}}
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": good_binance(), "bybit": bad}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_bybit_empty_list_raises():
    bad = {"retCode": 0, "result": {"list": []}}
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": good_binance(), "bybit": bad}))
    with pytest.raises(InvalidDataError):
        f.history()


def test_funding_bybit_missing_result_raises():
    f = FundingFeed(fetcher=FakeFetcher({"fapi.binance": good_binance(), "bybit": {"retCode": 0}}))
    with pytest.raises(InvalidDataError):
        f.history()


# ── FUNDING: median of two venues ─────────────────────────────────────────────────────────────
def test_funding_median_two_venues_same_day():
    # one entry each: binance 0.0001, bybit 0.0003 → median of [0.0001, 0.0003] = 0.0002
    day_ms = 1782288000000
    routes = {
        "fapi.binance": good_binance("0.00010000", day_ms),
        "bybit": good_bybit("0.00030000", day_ms),
    }
    series = FundingFeed(fetcher=FakeFetcher(routes)).history()
    assert len(series) == 1
    (date, val), = series.items()
    assert val == pytest.approx(0.0002)


def test_funding_median_robust_to_outlier():
    # binance has two normal entries + bybit one huge outlier on the same day.
    # union = [0.0001, 0.0001, 0.5] → median 0.0001 (outlier does not dominate).
    day_ms = 1782288000000
    binance = [
        {"symbol": "ETHUSDT", "fundingTime": day_ms, "fundingRate": "0.0001"},
        {"symbol": "ETHUSDT", "fundingTime": day_ms + 1, "fundingRate": "0.0001"},
    ]
    bybit = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.5", "fundingRateTimestamp": str(day_ms)},
    ]}}
    series = FundingFeed(fetcher=FakeFetcher({"fapi.binance": binance, "bybit": bybit})).history()
    (date, val), = series.items()
    assert val == pytest.approx(0.0001)


def test_funding_latest_returns_most_recent():
    d1, d2 = 1782288000000, 1782288000000 + 86400000  # two distinct days
    binance = [
        {"symbol": "ETHUSDT", "fundingTime": d1, "fundingRate": "0.0001"},
        {"symbol": "ETHUSDT", "fundingTime": d2, "fundingRate": "0.0002"},
    ]
    bybit = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(d1)},
        {"symbol": "ETHUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": str(d2)},
    ]}}
    date, val = FundingFeed(fetcher=FakeFetcher({"fapi.binance": binance, "bybit": bybit})).latest()
    assert val == pytest.approx(0.0002)


# ── PRICE: schema validation raises ───────────────────────────────────────────────────────────
def test_price_current_missing_coins_raises():
    p = PriceFeed(fetcher=FakeFetcher({"current": {"nope": {}}}))
    with pytest.raises(InvalidDataError):
        p.current()


def test_price_current_missing_token_raises():
    # coins present but eeth entry absent
    coins = {f"{CHAIN}:{TOKENS['eth']}": {"price": 3000.0}}
    p = PriceFeed(fetcher=FakeFetcher({"current": {"coins": coins}}))
    with pytest.raises(InvalidDataError):
        p.current()


def test_price_current_zero_price_raises():
    coins = {f"{CHAIN}:{addr}": {"price": 0} for addr in TOKENS.values()}
    p = PriceFeed(fetcher=FakeFetcher({"current": {"coins": coins}}))
    with pytest.raises(InvalidDataError):
        p.current()


def test_price_current_ok_and_ratio():
    p = PriceFeed(fetcher=FakeFetcher({"current": good_current()}))
    cur = p.current()
    assert cur["prices"]["eth"] == 3000.0
    # lrt 3090 / eth 3000 = 1.03
    assert cur["ratios"]["eeth"] == pytest.approx(1.03)


def test_price_chart_empty_prices_raises():
    # chart route per token id; eth chart has empty prices
    routes = {f"chart/{CHAIN}:{TOKENS['eth']}": {"coins": {f"{CHAIN}:{TOKENS['eth']}": {"prices": []}}}}
    # other tokens won't be reached because eth is first; but make routes resilient
    p = PriceFeed(fetcher=FakeFetcher(routes))
    with pytest.raises(InvalidDataError):
        p.history(span=3)


# ── RESTAKING: schema validation + matching ──────────────────────────────────────────────────
def test_restaking_bad_status_raises():
    r = RestakingFeed(fetcher=FakeFetcher({"pools": {"status": "error", "data": []}}))
    with pytest.raises(InvalidDataError):
        r.apys()


def test_restaking_empty_data_raises():
    r = RestakingFeed(fetcher=FakeFetcher({"pools": {"status": "success", "data": []}}))
    with pytest.raises(InvalidDataError):
        r.apys()


def test_restaking_no_match_raises():
    pools = {"status": "success", "data": [
        {"project": "aave-v3", "chain": "Ethereum", "symbol": "USDC", "apy": 4.0, "tvlUsd": 1e9},
    ]}
    r = RestakingFeed(fetcher=FakeFetcher({"pools": pools}))
    with pytest.raises(InvalidDataError):
        r.apys()


def test_restaking_match_returns_decimal():
    r = RestakingFeed(fetcher=FakeFetcher({"pools": good_pools()}))
    apys = r.apys()
    assert apys["eeth"] == pytest.approx(0.0285)
    assert apys["weeth"] == pytest.approx(0.0285)
    assert apys["ezeth"] == pytest.approx(0.0194)


# ── MarketData: injected feeds ────────────────────────────────────────────────────────────────
def _build_md(tmp_path, funding=None, prices=None, ratios=None, restaking=None,
              defi=None, ff_limit=2):
    """MarketData with feeds stubbed via small objects (not the http layer)."""

    class _F:
        def __init__(s, series): s.series = series
        def history(s): return dict(s.series)

    class _P:
        def __init__(s, ph, rh): s.ph, s.rh = ph, rh
        def history(s, span=90): return {k: dict(v) for k, v in s.ph.items()}
        def history_ratios(s, span=90): return {k: dict(v) for k, v in s.rh.items()}

    class _R:
        def __init__(s, a): s.a = a
        def apys(s): return dict(s.a)

    md = MarketData(
        funding_feed=_F(funding or {}),
        price_feed=_P(prices or {}, ratios or {}),
        restaking_feed=_R(restaking or {}),
        defi_apy_series=defi,
        cache_dir=tmp_path / "mdcache",
        ff_limit_days=ff_limit,
    )
    md.refresh()
    return md


def test_marketdata_snapshot_valid(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-20": 0.0002},
        prices={"eth": {"2026-06-20": 3000.0}, "eeth": {"2026-06-20": 3090.0}},
        ratios={"eeth": {"2026-06-20": 1.03}},
        restaking={"eeth": 0.0285},
    )
    snap = md.snapshot("2026-06-20")
    assert isinstance(snap, MarketSnapshot)
    assert snap.funding_rate_8h == pytest.approx(0.0002)
    assert snap.eth_price_usd == 3000.0
    assert snap.lrt_price_usd["eeth"] == 3090.0
    assert snap.lrt_eth_ratio["eeth"] == 1.03
    assert snap.restaking_apy["eeth"] == 0.0285
    assert "funding_rate_8h" not in snap.gaps
    assert not snap.ff_filled
    # contract accessor works
    assert snap.require("eth_price") == 3000.0


def test_marketdata_forward_fill_within_limit(tmp_path):
    # value on the 18th, ask for the 20th (2 days later) → ff with limit=2 succeeds, flagged.
    md = _build_md(
        tmp_path,
        funding={"2026-06-18": 0.0005},
        prices={"eth": {"2026-06-18": 3000.0}},
        ratios={},
        restaking={"eeth": 0.03},
        ff_limit=2,
    )
    snap = md.snapshot("2026-06-20")
    assert snap.funding_rate_8h == pytest.approx(0.0005)
    assert "funding_rate_8h" in snap.ff_filled
    assert "funding_rate_8h" not in snap.gaps


def test_marketdata_gap_beyond_limit(tmp_path):
    # value on the 18th, ask for the 21st (3 days) → beyond limit=2 → None + gap.
    md = _build_md(
        tmp_path,
        funding={"2026-06-18": 0.0005},
        prices={"eth": {"2026-06-18": 3000.0}},
        ratios={},
        restaking={"eeth": 0.03},
        ff_limit=2,
    )
    snap = md.snapshot("2026-06-21")
    assert snap.funding_rate_8h is None
    assert "funding_rate_8h" in snap.gaps
    assert "funding_rate_8h" not in snap.ff_filled
    # eth price also gapped
    assert snap.eth_price_usd is None
    assert "eth_price_usd" in snap.gaps


def test_marketdata_exact_hit_not_flagged_ff(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-20": 0.0002, "2026-06-19": 0.0001},
        prices={"eth": {"2026-06-20": 3000.0}},
        ratios={},
        restaking={"eeth": 0.03},
    )
    snap = md.snapshot("2026-06-20")
    assert "funding_rate_8h" not in snap.ff_filled


def test_marketdata_historical_range_ordering(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-18": 0.0001, "2026-06-19": 0.0002, "2026-06-20": 0.0003},
        prices={"eth": {"2026-06-18": 3000.0, "2026-06-19": 3010.0, "2026-06-20": 3020.0}},
        ratios={},
        restaking={"eeth": 0.03},
    )
    snaps = md.historical_range("2026-06-18", "2026-06-20")
    dates = [s.date for s in snaps]
    assert dates == ["2026-06-18", "2026-06-19", "2026-06-20"]
    assert dates == sorted(dates)
    assert snaps[0].funding_rate_8h == pytest.approx(0.0001)
    assert snaps[-1].eth_price_usd == 3020.0


def test_marketdata_historical_range_bad_range_raises(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-20": 0.0001},
        prices={"eth": {"2026-06-20": 3000.0}},
        restaking={"eeth": 0.03},
    )
    with pytest.raises(InvalidDataError):
        md.historical_range("2026-06-21", "2026-06-20")


def test_marketdata_latest(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-19": 0.0001, "2026-06-20": 0.0002},
        prices={"eth": {"2026-06-19": 3000.0, "2026-06-20": 3010.0}},
        restaking={"eeth": 0.03},
    )
    snap = md.latest()
    assert snap.date == "2026-06-20"
    assert snap.eth_price_usd == 3010.0


def test_marketdata_defi_apy_assembled(tmp_path):
    md = _build_md(
        tmp_path,
        funding={"2026-06-20": 0.0002},
        prices={"eth": {"2026-06-20": 3000.0}},
        restaking={"eeth": 0.03},
        defi={"aave_v3": {"2026-06-20": 0.045}},
    )
    snap = md.snapshot("2026-06-20")
    assert snap.defi_apy["aave_v3"] == pytest.approx(0.045)


def test_marketdata_cache_shared_across_instances(tmp_path):
    cache = tmp_path / "shared"
    md1 = MarketData(
        funding_feed=type("F", (), {"history": lambda s: {"2026-06-20": 0.0002}})(),
        price_feed=type("P", (), {
            "history": lambda s, span=90: {"eth": {"2026-06-20": 3000.0}},
            "history_ratios": lambda s, span=90: {},
        })(),
        restaking_feed=type("R", (), {"apys": lambda s: {"eeth": 0.03}})(),
        cache_dir=cache,
    )
    md1.refresh()
    # second instance with feeds that would RAISE if called → must read cache, never fetch
    class Boom:
        def history(self, *a, **k): raise AssertionError("should not fetch")
        def history_ratios(self, *a, **k): raise AssertionError("should not fetch")
        def apys(self, *a, **k): raise AssertionError("should not fetch")
    md2 = MarketData(funding_feed=Boom(), price_feed=Boom(), restaking_feed=Boom(),
                     cache_dir=cache)
    snap = md2.snapshot("2026-06-20")
    assert snap.eth_price_usd == 3000.0
