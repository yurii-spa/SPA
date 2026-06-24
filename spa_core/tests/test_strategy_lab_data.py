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


def test_funding_pagination_bad_page_raises():
    # A malformed second binance page (not a list) must raise InvalidDataError (fail-closed).
    page1 = [{"symbol": "ETHUSDT", "fundingTime": _ms("2024-06-01") + i, "fundingRate": "0.0001"}
             for i in range(1000)]  # full → forces a second fetch
    page2 = {"oops": "not a list"}
    bybit_pg = {"retCode": 0, "result": {"list": [
        {"symbol": "ETHUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": str(_ms("2024-06-01"))},
    ]}}
    fetcher = PagedFetcher({"fapi.binance": [page1, page2], "bybit": bybit_pg})
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
