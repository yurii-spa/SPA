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
from spa_core.strategy_lab.data.funding_feed import (
    FundingFeed, BINANCE_URL, BYBIT_URL,
    _rows_binance, _rows_bybit, _rows_okx, _rows_kucoin, _rows_hyperliquid,
    _parse_hyperliquid, _hl_8h_by_date, HL_HOURS_PER_8H,
)
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


# canonical good payloads for the new venues ---------------------------------------------------
def good_okx(rate="0.00020000", day_ms=1782288000000):
    # OKX: code is a STRING "0"; fundingTime is a STRING ms; 8h settlement
    return {"code": "0", "msg": "", "data": [
        {"instId": "ETH-USDT-SWAP", "fundingRate": rate, "fundingTime": str(day_ms),
         "realizedRate": rate},
    ]}


def good_kucoin(rate=0.00025, day_ms=1782288000000):
    # KuCoin: code is a STRING "200000"; fundingRate is a FLOAT; timepoint is an int ms; 8h
    return {"code": "200000", "data": [
        {"symbol": "ETHUSDTM", "fundingRate": rate, "timepoint": day_ms},
    ]}


def good_hyperliquid(rate="0.0000125", day_ms=1782288000000, hours=24):
    # Hyperliquid: HOURLY list; fundingRate is a STRING; time is int ms. Anchor to the UTC
    # midnight of day_ms so all `hours` entries fall on the SAME UTC date.
    midnight = (day_ms // 86400000) * 86400000
    return [
        {"coin": "ETH", "fundingRate": rate, "premium": "-0.0003", "time": midnight + h * 3600000}
        for h in range(hours)
    ]


# ── FUNDING: per-venue PARSER schema validation RAISES (fail-CLOSED at venue level) ────────────
# NOTE: history() now degrades gracefully (median of whoever returned), so a single bad venue no
# longer aborts the whole call. Schema validation is still strict — proven at the parser level.
def test_funding_binance_not_list_raises():
    with pytest.raises(InvalidDataError):
        _rows_binance({"oops": 1})


def test_funding_binance_empty_list_raises():
    with pytest.raises(InvalidDataError):
        _rows_binance([])


def test_funding_binance_missing_rate_raises():
    with pytest.raises(InvalidDataError):
        _rows_binance([{"symbol": "ETHUSDT", "fundingTime": 1782288000000}])


def test_funding_binance_empty_rate_raises():
    with pytest.raises(InvalidDataError):
        _rows_binance([{"symbol": "ETHUSDT", "fundingTime": 1782288000000, "fundingRate": ""}])


def test_funding_bybit_retcode_nonzero_raises():
    with pytest.raises(InvalidDataError):
        _rows_bybit({"retCode": 10001, "retMsg": "bad", "result": {"list": []}})


def test_funding_bybit_empty_list_raises():
    with pytest.raises(InvalidDataError):
        _rows_bybit({"retCode": 0, "result": {"list": []}})


def test_funding_bybit_missing_result_raises():
    with pytest.raises(InvalidDataError):
        _rows_bybit({"retCode": 0})


# OKX parser schema validation -----------------------------------------------------------------
def test_funding_okx_bad_code_raises():
    with pytest.raises(InvalidDataError):
        _rows_okx({"code": "50011", "msg": "rate limit", "data": []})


def test_funding_okx_not_dict_raises():
    with pytest.raises(InvalidDataError):
        _rows_okx([1, 2, 3])


def test_funding_okx_empty_data_raises():
    with pytest.raises(InvalidDataError):
        _rows_okx({"code": "0", "data": []})


def test_funding_okx_missing_rate_raises():
    with pytest.raises(InvalidDataError):
        _rows_okx({"code": "0", "data": [{"fundingTime": "1782288000000"}]})


def test_funding_okx_bad_time_raises():
    with pytest.raises(InvalidDataError):
        _rows_okx({"code": "0", "data": [{"fundingRate": "0.0001", "fundingTime": "notms"}]})


def test_funding_okx_good_parses():
    rows = _rows_okx(good_okx("0.0002", 1782288000000))
    assert rows == [(1782288000000, pytest.approx(0.0002))]


# KuCoin parser schema validation --------------------------------------------------------------
def test_funding_kucoin_bad_code_raises():
    with pytest.raises(InvalidDataError):
        _rows_kucoin({"code": "400100", "msg": "bad", "data": []})


def test_funding_kucoin_empty_data_raises():
    with pytest.raises(InvalidDataError):
        _rows_kucoin({"code": "200000", "data": []})


def test_funding_kucoin_missing_rate_raises():
    with pytest.raises(InvalidDataError):
        _rows_kucoin({"code": "200000", "data": [{"timepoint": 1782288000000}]})


def test_funding_kucoin_bad_time_raises():
    with pytest.raises(InvalidDataError):
        _rows_kucoin({"code": "200000", "data": [{"fundingRate": 0.0001, "timepoint": "x"}]})


def test_funding_kucoin_good_parses():
    rows = _rows_kucoin(good_kucoin(0.00025, 1782288000000))
    assert rows == [(1782288000000, pytest.approx(0.00025))]


# Hyperliquid parser schema validation ---------------------------------------------------------
def test_funding_hyperliquid_not_list_raises():
    with pytest.raises(InvalidDataError):
        _rows_hyperliquid({"oops": 1})


def test_funding_hyperliquid_empty_list_raises():
    with pytest.raises(InvalidDataError):
        _rows_hyperliquid([])


def test_funding_hyperliquid_missing_rate_raises():
    with pytest.raises(InvalidDataError):
        _rows_hyperliquid([{"coin": "ETH", "time": 1782288000000}])


def test_funding_hyperliquid_bad_time_raises():
    with pytest.raises(InvalidDataError):
        _rows_hyperliquid([{"coin": "ETH", "fundingRate": "0.0000125", "time": "nope"}])


# Hyperliquid HOURLY → 8h normalization --------------------------------------------------------
def test_funding_hyperliquid_hourly_to_8h_normalization():
    # 24 hourly entries of 0.0000125 on one UTC day → sum = 24*0.0000125 = 0.0003;
    # per-8h = 0.0003 / 3 = 0.0001. Comparable to an 8h venue's per-period rate.
    day_ms = 1782288000000  # 00:00 UTC
    payload = good_hyperliquid("0.0000125", day_ms, hours=24)
    by_date = _parse_hyperliquid(payload)
    (date, vals), = by_date.items()
    assert len(vals) == 1  # one 8h-equivalent observation per HL day
    assert vals[0] == pytest.approx(0.0003 / HL_HOURS_PER_8H)
    assert vals[0] == pytest.approx(0.0001)


def test_funding_hyperliquid_normalization_sums_per_day():
    # Two distinct hourly rates on the same day sum, then /3.
    day_ms = 1782288000000
    payload = [
        {"coin": "ETH", "fundingRate": "0.00001", "premium": "0", "time": day_ms},
        {"coin": "ETH", "fundingRate": "0.00002", "premium": "0", "time": day_ms + 3600000},
    ]
    out = _hl_8h_by_date(dict((r["time"], float(r["fundingRate"])) for r in payload))
    (date, vals), = out.items()
    assert vals[0] == pytest.approx((0.00001 + 0.00002) / HL_HOURS_PER_8H)


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


def test_funding_median_across_all_five_venues():
    # Five venues, one 8h-equivalent observation each on the same day:
    #   binance 0.0001, bybit 0.0003, okx 0.0002, kucoin 0.00025, HL 0.0001 (from 24×0.0000125/3)
    # union (sorted) = [0.0001, 0.0001, 0.0002, 0.00025, 0.0003] → median = 0.0002
    day_ms = 1782288000000
    routes = {
        "fapi.binance": good_binance("0.00010000", day_ms),
        "bybit": good_bybit("0.00030000", day_ms),
        "okx.com": good_okx("0.00020000", day_ms),
        "kucoin": good_kucoin(0.00025, day_ms),
        "hyperliquid": good_hyperliquid("0.0000125", day_ms, hours=24),
    }
    series = FundingFeed(fetcher=FakeFetcher(routes)).history()
    assert len(series) == 1
    (date, val), = series.items()
    assert val == pytest.approx(0.0002)


def test_funding_one_venue_down_uses_median_of_rest():
    # OKX route raises (down); the median is taken over the other four venues.
    # remaining union = [binance 0.0001, bybit 0.0003, kucoin 0.00025, HL 0.0001] sorted
    #   = [0.0001, 0.0001, 0.00025, 0.0003] → median = (0.0001 + 0.00025)/2 = 0.000175
    day_ms = 1782288000000
    routes = {
        "fapi.binance": good_binance("0.00010000", day_ms),
        "bybit": good_bybit("0.00030000", day_ms),
        "okx.com": InvalidDataError("okx down"),
        "kucoin": good_kucoin(0.00025, day_ms),
        "hyperliquid": good_hyperliquid("0.0000125", day_ms, hours=24),
    }
    series = FundingFeed(fetcher=FakeFetcher(routes)).history()
    (date, val), = series.items()
    assert val == pytest.approx((0.0001 + 0.00025) / 2)


def test_funding_only_one_venue_alive_still_returns():
    # Four venues missing/raising, only bybit returns → median = bybit's single value (no raise).
    day_ms = 1782288000000
    routes = {
        "fapi.binance": InvalidDataError("down"),
        "bybit": good_bybit("0.00030000", day_ms),
        "okx.com": InvalidDataError("down"),
        "kucoin": InvalidDataError("down"),
        "hyperliquid": InvalidDataError("down"),
    }
    series = FundingFeed(fetcher=FakeFetcher(routes)).history()
    (date, val), = series.items()
    assert val == pytest.approx(0.0003)


def test_funding_all_venues_down_raises():
    # Every venue raises → merged series empty → fail-CLOSED.
    routes = {k: InvalidDataError("down")
              for k in ("fapi.binance", "bybit", "okx.com", "kucoin", "hyperliquid")}
    with pytest.raises(InvalidDataError):
        FundingFeed(fetcher=FakeFetcher(routes)).history()


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


# ══════════════════════════════════════════════════════════════════════════════════════════════
# PAGINATION — deep historical fetch over a window, all with INJECTED multi-page fakes (no net).
# ══════════════════════════════════════════════════════════════════════════════════════════════
import datetime as _dt


def _ms(date_iso, settle=0):
    """ms timestamp for a UTC date + 0/1/2 → 00:00/08:00/16:00 settle."""
    d = _dt.date.fromisoformat(date_iso)
    base = _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc)
    return int((base + _dt.timedelta(hours=8 * settle)).timestamp() * 1000)


class PagedFetcher:
    """Routes a url-substring to a SEQUENCE of payloads (one per successive call). Each call to a
    matching route pops the next payload; the last payload repeats once exhausted. Lets a single
    feed see several distinct 'pages' across its pagination loop. Records call urls."""

    def __init__(self, routes):
        # routes: {needle: [payload, payload, ...]}  (a non-list is treated as a 1-page route)
        self.routes = {k: (v if isinstance(v, list) else [v]) for k, v in routes.items()}
        self._idx = {k: 0 for k in self.routes}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for needle, pages in self.routes.items():
            if needle in url:
                i = self._idx[needle]
                payload = pages[min(i, len(pages) - 1)]
                self._idx[needle] = i + 1
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"no fake route for {url}")


# ── FUNDING pagination ────────────────────────────────────────────────────────────────────────
def test_funding_pagination_assembles_multiple_pages():
    # Binance: page1 = 1000 rows ending mid-window (full page → loop continues), page2 = tail.
    page1 = [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-01") + i, "fundingRate": "0.0001"}
             for i in range(1000)]
    page2 = [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-03"), "fundingRate": "0.0002"}]
    # Bybit: descending, one short page (<200) → stops immediately. Cover same days.
    bybit_pg = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.0003", "fundingRateTimestamp": str(_ms("2024-06-03"))},
        {"symbol": "ETHUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(_ms("2024-06-01"))},
    ]}}
    fetcher = PagedFetcher({"fapi.binance": [page1, page2], "bybit": bybit_pg})
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-03")
    # 2024-06-01 present (from page1 + bybit), 2024-06-03 present (from page2 + bybit)
    assert "2024-06-01" in series
    assert "2024-06-03" in series
    # binance made >1 call (paginated through the full page1)
    assert sum("fapi.binance" in u for u in fetcher.calls) >= 2


def test_funding_pagination_dedup_by_timestamp():
    # Same funding timestamp appears in two binance pages → counted ONCE (dedup by ts).
    ts = _ms("2024-06-02")
    full = [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-01") + i, "fundingRate": "0.0001"}
            for i in range(999)]
    full.append({"symbol": "ETHUSDT", "fundingTime": ts, "fundingRate": "0.0001"})  # 1000th
    page2 = [{"symbol": "ETHUSDT", "fundingTime": ts, "fundingRate": "0.0001"}]  # duplicate ts
    bybit_pg = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(ts)},
    ]}}
    fetcher = PagedFetcher({"fapi.binance": [full, page2], "bybit": bybit_pg})
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-02")
    # all entries are 0.0001 → median 0.0001 regardless, but the point is the day exists once.
    assert series["2024-06-02"] == pytest.approx(0.0001)


def test_funding_pagination_stops_at_window_bounds():
    # Binance returns rows BEYOND end_date in the first page; those must be excluded + loop stops.
    page = [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-01"), "fundingRate": "0.0001"},
            {"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-10"), "fundingRate": "0.0009"}]
    bybit_pg = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(_ms("2024-06-01"))},
    ]}}
    fetcher = PagedFetcher({"fapi.binance": [page], "bybit": bybit_pg})
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-05")
    assert "2024-06-01" in series
    assert "2024-06-10" not in series  # beyond end_date → excluded


def test_funding_pagination_okx_walks_backward():
    # OKX paginates DESCENDING via `after`: page1 = 100 full rows whose EARLIEST is still well
    # inside the (wide) window → loop continues; page2 = the tail down to start_date.
    # 100 × 8h ≈ 33 days, so a window of ~2024-04-01..2024-06-10 keeps page1 above start.
    page1 = {"code": "0", "data": [
        {"fundingRate": "0.0002", "fundingTime": str(_ms("2024-06-10") - i * 28_800_000)}
        for i in range(100)
    ]}
    page2 = {"code": "0", "data": [
        {"fundingRate": "0.0002", "fundingTime": str(_ms("2024-04-01"))},
    ]}
    fetcher = PagedFetcher({
        "okx.com": [page1, page2],
        "fapi.binance": InvalidDataError("isolate okx"),
        "bybit": InvalidDataError("isolate okx"),
        "kucoin": InvalidDataError("isolate okx"),
        "hyperliquid": InvalidDataError("isolate okx"),
    })
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    series = feed.history(start_date="2024-04-01", end_date="2024-06-10")
    assert "2024-06-10" in series
    assert "2024-04-01" in series  # tail came from page2
    # OKX paged at least twice (full first page forced a second `after` fetch)
    assert sum("okx.com" in u for u in fetcher.calls) >= 2


def test_funding_pagination_kucoin_single_window_call():
    # KuCoin returns the whole window in ONE call (no pagination loop).
    fetcher = PagedFetcher({
        "kucoin": {"code": "200000", "data": [
            {"symbol": "ETHUSDTM", "fundingRate": 0.0002, "timepoint": _ms("2024-06-01")},
            {"symbol": "ETHUSDTM", "fundingRate": 0.0002, "timepoint": _ms("2024-06-02")}]},
        "fapi.binance": [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-01"), "fundingRate": "0.0002"}],
        "bybit": {"retCode": 0, "result": {"list": [
            {"symbol": "ETHUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": str(_ms("2024-06-01"))}]}},
        "okx.com": {"code": "0", "data": [
            {"fundingRate": "0.0002", "fundingTime": str(_ms("2024-06-01"))}]},
        "hyperliquid": [{"coin": "ETH", "fundingRate": "0.0000125", "time": _ms("2024-06-01")}],
    })
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-02")
    assert "2024-06-01" in series and "2024-06-02" in series
    assert sum("kucoin" in u for u in fetcher.calls) == 1  # exactly one window call


def test_funding_pagination_hyperliquid_walks_forward_and_normalizes():
    # HL paginates ascending HOURLY; a full day (24 entries) → normalized to one 8h-equiv/day.
    hl_day = [{"coin": "ETH", "fundingRate": "0.0000125", "premium": "0",
               "time": _ms("2024-06-01") + h * 3600000} for h in range(24)]
    fetcher = PagedFetcher({
        "hyperliquid": [hl_day],  # one page that IS a list → wrap so it isn't split per-row
        "fapi.binance": InvalidDataError("down"),  # isolate HL contribution
        "bybit": InvalidDataError("down"),
        "okx.com": InvalidDataError("down"),
        "kucoin": InvalidDataError("down"),
    })
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=3)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-01")
    # only HL alive → median = HL 8h-equiv = 24*0.0000125/3 = 0.0001
    assert series["2024-06-01"] == pytest.approx(0.0001)


def test_funding_pagination_one_venue_bad_others_carry():
    # Binance pages are malformed (raises internally) but OTHER venues return → call SUCCEEDS
    # with the median of the survivors (graceful degradation in the paginated path too).
    fetcher = PagedFetcher({
        "fapi.binance": {"oops": "bad"},  # _paginate_binance raises → contributes {}
        "bybit": {"retCode": 0, "result": {"list": [
            {"symbol": "ETHUSDT", "fundingRate": "0.0003", "fundingRateTimestamp": str(_ms("2024-06-01"))}]}},
        "okx.com": {"code": "0", "data": [
            {"fundingRate": "0.0001", "fundingTime": str(_ms("2024-06-01"))}]},
        "kucoin": {"code": "200000", "data": [
            {"symbol": "ETHUSDTM", "fundingRate": 0.0002, "timepoint": _ms("2024-06-01")}]},
        "hyperliquid": InvalidDataError("down"),
    })
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=5)
    series = feed.history(start_date="2024-06-01", end_date="2024-06-01")
    # survivors on the day: bybit 0.0003, okx 0.0001, kucoin 0.0002 → median 0.0002
    assert series["2024-06-01"] == pytest.approx(0.0002)


def test_funding_pagination_all_venues_bad_raises():
    # If EVERY venue fails for the window, the merged series is empty → fail-CLOSED (raises).
    # (A single bad venue degrades gracefully; that is covered separately below.)
    fetcher = PagedFetcher({
        "fapi.binance": {"oops": "not a list"},
        "bybit": {"retCode": 10001, "result": {"list": []}},
        "okx.com": {"code": "50011", "data": []},
        "kucoin": {"code": "400", "data": []},
        "hyperliquid": {"oops": 1},
    })
    feed = FundingFeed(fetcher=fetcher, page_delay_s=0, max_pages=10)
    with pytest.raises(InvalidDataError):
        feed.history(start_date="2024-06-01", end_date="2024-06-30")


# ── PRICE pagination ──────────────────────────────────────────────────────────────────────────
def _chart_pts(addr, day_to_price):
    pts = [{"timestamp": int(_dt.datetime.fromisoformat(d + "T00:00:00+00:00").timestamp()),
            "price": p} for d, p in day_to_price.items()]
    return {"coins": {f"{CHAIN}:{addr}": {"symbol": "X", "prices": pts}}}


def test_price_pagination_assembles_and_dedup():
    # Each token paginates forward in MAX_SPAN chunks; here a small window fits one page per
    # token, but we verify the range path merges + computes ratios across the whole range.
    def routes_for():
        r = {}
        for sym, addr in TOKENS.items():
            base = 3000.0 if sym == "eth" else 3090.0
            r[f"chart/{CHAIN}:{addr}"] = _chart_pts(addr, {
                "2024-06-01": base, "2024-06-02": base + 10, "2024-06-03": base + 20,
            })
        return r
    p = PriceFeed(fetcher=PagedFetcher(routes_for()), page_delay_s=0)
    hist = p.history(start_date="2024-06-01", end_date="2024-06-03")
    assert sorted(hist["eth"]) == ["2024-06-01", "2024-06-02", "2024-06-03"]
    assert hist["eth"]["2024-06-01"] == 3000.0
    ratios = p.history_ratios(start_date="2024-06-01", end_date="2024-06-03")
    assert ratios["eeth"]["2024-06-01"] == pytest.approx(3090.0 / 3000.0, rel=1e-6)


def test_price_pagination_multi_page_merges():
    # Force a 2-page walk: page1 ends before end_date (full-ish), page2 has the tail.
    addr = TOKENS["eth"]
    # 365-day page (MAX_SPAN) so the loop advances; we just supply two distinct pages.
    page1 = _chart_pts(addr, {"2024-06-01": 3000.0, "2025-05-31": 4000.0})
    page2 = _chart_pts(addr, {"2025-06-01": 4100.0, "2025-06-02": 4200.0})
    routes = {f"chart/{CHAIN}:{a}": ([page1, page2] if a == addr else
              _chart_pts(a, {"2024-06-01": 3090.0, "2025-06-02": 4300.0}))
              for a in TOKENS.values()}
    p = PriceFeed(fetcher=PagedFetcher(routes), page_delay_s=0, max_pages=5)
    hist = p.history(start_date="2024-06-01", end_date="2025-06-02")
    assert hist["eth"]["2024-06-01"] == 3000.0
    assert hist["eth"]["2025-06-02"] == 4200.0  # came from page2 (merged)


def test_price_pagination_stops_at_window_and_bad_page_raises():
    addr = TOKENS["eth"]
    # eth chart route raises on first call → fail-closed
    routes = {f"chart/{CHAIN}:{addr}": {"coins": {f"{CHAIN}:{addr}": {"prices": []}}}}
    p = PriceFeed(fetcher=PagedFetcher(routes), page_delay_s=0)
    with pytest.raises(InvalidDataError):
        p.history(start_date="2024-06-01", end_date="2024-06-03")


# ── RESTAKING pagination (pool /chart history) ──────────────────────────────────────────────────
def _pools_with_ids():
    return {"status": "success", "data": [
        {"project": "ether.fi-stake", "chain": "Ethereum", "symbol": "WEETH",
         "apy": 2.85, "tvlUsd": 2.8e9, "pool": "POOL_EETH"},
        {"project": "renzo", "chain": "Ethereum", "symbol": "EZETH",
         "apy": 1.94, "tvlUsd": 8e7, "pool": "POOL_EZETH"},
    ]}


def _yields_chart(rows):
    return {"status": "success", "data": [
        {"timestamp": ts, "apy": apy} for ts, apy in rows
    ]}


def test_restaking_history_builds_series_from_chart():
    routes = {
        "pools": _pools_with_ids(),
        "chart/POOL_EETH": _yields_chart([
            ("2024-06-05T23:01:34.685Z", 3.49), ("2024-06-06T23:01:00.000Z", 3.40),
        ]),
        "chart/POOL_EZETH": _yields_chart([
            ("2024-12-13T23:01:38.564Z", 3.46), ("2024-12-14T23:01:00.000Z", 3.40),
        ]),
    }
    r = RestakingFeed(fetcher=PagedFetcher(routes))
    hist = r.history("2024-06-01", "2026-06-24")
    # eeth + weeth share POOL_EETH → both present
    assert hist["eeth"]["2024-06-05"] == pytest.approx(0.0349)
    assert hist["weeth"]["2024-06-06"] == pytest.approx(0.0340)
    assert hist["ezeth"]["2024-12-13"] == pytest.approx(0.0346)


def test_restaking_history_windows_and_drops_out_of_range():
    # ezETH chart starts 2024-12-13; a window ending before that → ezeth absent, eeth present.
    routes = {
        "pools": _pools_with_ids(),
        "chart/POOL_EETH": _yields_chart([("2024-06-05T23:00:00Z", 3.49)]),
        "chart/POOL_EZETH": _yields_chart([("2024-12-13T23:00:00Z", 3.46)]),
    }
    r = RestakingFeed(fetcher=PagedFetcher(routes))
    hist = r.history("2024-06-01", "2024-07-01")
    assert "eeth" in hist
    assert "ezeth" not in hist  # its only point is outside the window


def test_restaking_history_bad_chart_raises():
    routes = {
        "pools": _pools_with_ids(),
        "chart/POOL_EETH": {"status": "error", "data": []},
        "chart/POOL_EZETH": _yields_chart([("2024-12-13T23:00:00Z", 3.46)]),
    }
    r = RestakingFeed(fetcher=PagedFetcher(routes))
    with pytest.raises(InvalidDataError):
        r.history("2024-06-01", "2026-06-24")


# ── MarketData deep window: per-date restaking series flows into snapshots ───────────────────────
def test_marketdata_deep_restaking_series_in_snapshot(tmp_path):
    class _F:
        def history(self, start_date=None, end_date=None):
            return {"2024-06-05": 0.0001, "2024-06-06": 0.0002}

    class _P:
        def history(self, span=90, start_date=None, end_date=None):
            return {"eth": {"2024-06-05": 3000.0, "2024-06-06": 3010.0}}
        def history_ratios(self, span=90, start_date=None, end_date=None):
            return {}

    class _R:
        def history(self, start_date, end_date):
            return {"eeth": {"2024-06-05": 0.035, "2024-06-06": 0.034}}

    md = MarketData(funding_feed=_F(), price_feed=_P(), restaking_feed=_R(),
                    cache_dir=tmp_path / "deep", window=("2024-06-05", "2024-06-06"))
    md.refresh()
    snap = md.snapshot("2024-06-06")
    assert snap.restaking_apy["eeth"] == pytest.approx(0.034)  # per-DATE value, not flat latest
    assert "restaking_apy" not in snap.gaps
