"""
spa_core/tests/test_rates_desk_feeds.py — the Rates-Desk DATA LAYER (feeds.py) tests.

PURE / no network: every feed gets an injected fake fetcher (or an in-memory deep dataset). Proves,
per the brief §1-2:
  • each feed emits VALID contract dataclasses (RateQuote / UnderlyingRisk) with the right shapes,
    venues, kinds, Decimal types;
  • the §9 exit-liquidity model is MONOTONIC in pool depth and NON-INCREASING (discounted) in the
    redemption SLA, and fail-CLOSEs on bad inputs;
  • hedge_available is HONEST (False everywhere while no keyless Boros venue exists);
  • build_surface assembles a coherent surface in BOTH backtest (deep history) and live (/active)
    modes — one function, one source of truth — and caches atomically;
  • fail-CLOSED on malformed data (raises, never fabricates);
  • deterministic (same inputs → identical surface twice).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import socket
from decimal import Decimal

import pytest

from spa_core.strategy_lab.rates_desk import config, feeds
from spa_core.strategy_lab.rates_desk.contracts import (
    RateQuote,
    RateVenue,
    UnderlyingKind,
    UnderlyingRisk,
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# NETWORK ISOLATION (CI-safe, deterministic-order-safe)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# Root cause of the historical live-test flake: the feeds default to the SHARED real fetcher
# (feeds._http_fetch → urllib.urlopen). A *_live_* test that is constructed without an injected
# fetcher (or where one path falls through to the default) reaches the live Pendle/DeFiLlama endpoint.
# Whether that endpoint answered depended on (a) network availability in the runner and (b) which
# earlier test had already warmed/poisoned the live snapshot — i.e. an intra-module live-network
# coupling that only surfaced under deterministic collection order, not under -p randomly. The two
# guards below remove BOTH degrees of freedom: every test in this module is forbidden from opening a
# real socket (so any accidental fall-through to the default fetcher fails LOUDLY and deterministically
# instead of flaking), and the live-mode tests skip cleanly when the endpoint is genuinely unreachable.

_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_CREATE_CONNECTION = socket.create_connection


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Module-wide: forbid real outbound sockets. The whole suite is PURE (every feed gets an injected
    fetcher); a real connection means a test accidentally fell through to feeds._http_fetch. Turn that
    latent live coupling into a deterministic, order-independent failure."""

    def _blocked(*_a, **_k):  # pragma: no cover - only hit on a regression
        raise RuntimeError(
            "real network access is forbidden in test_rates_desk_feeds: a feed fell through to the "
            "default _http_fetch instead of using an injected fetcher")

    monkeypatch.setattr(socket.socket, "connect", _blocked, raising=True)
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=True)
    yield


def _network_available(host: str = "8.8.8.8", port: int = 53, timeout: float = 0.5) -> bool:
    """Best-effort liveness probe that bypasses the autouse guard by calling the SAVED real
    socket.connect directly (the guard patches socket.socket.connect, which create_connection uses
    internally). Lets a live-mode test SKIP on a CI box with no egress instead of erroring. Never raises."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        _REAL_SOCKET_CONNECT(sock, (host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# §9 exit-liquidity model
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def test_exit_liquidity_monotonic_in_depth():
    a = feeds.exit_liquidity_usd(Decimal("1000000"), 0)
    b = feeds.exit_liquidity_usd(Decimal("2000000"), 0)
    c = feeds.exit_liquidity_usd(Decimal("5000000"), 0)
    assert a < b < c
    assert isinstance(a, Decimal)


def test_exit_liquidity_discounted_by_sla():
    """Longer redemption cooldown → strictly less usable one-tick exit (until the floor)."""
    none = feeds.exit_liquidity_usd(Decimal("1000000"), 0)
    one = feeds.exit_liquidity_usd(Decimal("1000000"), 86400)
    seven = feeds.exit_liquidity_usd(Decimal("1000000"), 86400 * 7)
    assert none > one > seven


def test_exit_liquidity_sla_floor_clamped():
    """A very long SLA cannot drive usable depth below the documented floor fraction."""
    huge_sla = feeds.exit_liquidity_usd(Decimal("1000000"), 86400 * 365)
    band = config.exit_price_impact_band()
    floor = Decimal(str(config.SLA_DISCOUNT_FLOOR))
    expected_min = Decimal("1000000") * band * floor
    assert huge_sla == expected_min


def test_exit_liquidity_zero_depth_is_zero():
    assert feeds.exit_liquidity_usd(Decimal("0"), 86400) == Decimal("0")


def test_exit_liquidity_fail_closed_negative_depth():
    with pytest.raises(feeds.FeedError):
        feeds.exit_liquidity_usd(Decimal("-1"), 0)


def test_exit_liquidity_fail_closed_negative_sla():
    with pytest.raises(feeds.FeedError):
        feeds.exit_liquidity_usd(Decimal("1000000"), -1)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# PendleMarketFeed
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _deep_dataset():
    """A minimal in-memory deep dataset (the shape pendle_pt_history.build()/load() emit)."""
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "method": "test",
        "underlyings": ["sUSDe", "ezETH"],
        "window": {"start": "2025-01-01", "end": "2025-01-02"},
        "markets": {
            "PT-sUSDE-26DEC2025": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-26DEC2025",
                "market_address": "0xMKT_SUSDE", "pt_address": "0xPT_SUSDE",
                "maturity": "2025-12-26", "method": "direct_api_implied",
                "series": [
                    {"date": "2025-01-01", "implied_yield": 0.11, "underlying_yield": 0.09, "pt_price": None},
                    {"date": "2025-01-02", "implied_yield": 0.10, "underlying_yield": 0.09, "pt_price": None},
                ],
            },
            "PT-ezETH-26SEP2025": {
                "underlying": "ezETH", "kind": "lrt", "symbol": "PT-ezETH-26SEP2025",
                "market_address": "0xMKT_EZETH", "pt_address": "0xPT_EZETH",
                "maturity": "2025-09-26", "method": "direct_api_implied",
                "series": [
                    {"date": "2025-01-01", "implied_yield": 0.22, "underlying_yield": 0.04, "pt_price": None},
                ],
            },
        },
    }


def test_pendle_feed_historical_emits_valid_rate_quotes():
    deep = _deep_dataset()
    feed = feeds.PendleMarketFeed()
    rows = feed.quotes_for_date("2025-01-01", deep, hedge_by_underlying={"susde": False})
    assert len(rows) == 2
    for q in rows:
        assert isinstance(q, RateQuote)
        assert q.venue is RateVenue.PENDLE_PT
        assert q.protocol == "pendle"
        assert isinstance(q.quoted_rate, Decimal)
        assert isinstance(q.exit_liquidity_usd, Decimal)
        assert q.tenor_seconds > 0
        assert q.as_of == "2025-01-01"
    susde = [q for q in rows if q.underlying == "susde"][0]
    assert susde.kind is UnderlyingKind.STABLE_SYNTH
    assert susde.quoted_rate == Decimal("0.11")
    ez = [q for q in rows if q.underlying == "ezeth"][0]
    assert ez.kind is UnderlyingKind.LRT
    # ezETH SLA is longer than sUSDe? both 7d here — exit liquidity reflects the §9 model on hist depth
    assert susde.exit_liquidity_usd > 0


def test_pendle_feed_exit_liquidity_tracks_contemporaneous_tvl():
    """§9 calibration fix: when the deep series carries a per-day `tvl_usd`, the exit_liquidity proxy
    is tied to that CONTEMPORANEOUS depth and SHRINKS as TVL collapses (the Oct-2025 lesson), NOT to a
    stale/peak constant. Two days of the SAME market with a TVL collapse → strictly smaller exit."""
    deep = {
        "generated_at": "2026-01-01T00:00:00+00:00", "method": "test",
        "underlyings": ["sUSDe"], "window": {"start": "2025-10-01", "end": "2025-11-15"},
        "markets": {
            "PT-sUSDE-27NOV2025": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-27NOV2025",
                "market_address": "0xMKT", "pt_address": "0xPT", "maturity": "2025-11-27",
                "method": "direct_api_implied",
                "series": [
                    {"date": "2025-10-01", "implied_yield": 0.10, "underlying_yield": 0.09,
                     "tvl_usd": 142_000_000, "pt_price": None},
                    {"date": "2025-11-15", "implied_yield": 0.10, "underlying_yield": 0.09,
                     "tvl_usd": 88_000_000, "pt_price": None},
                ],
            },
        },
    }
    feed = feeds.PendleMarketFeed()
    peak = feed.quotes_for_date("2025-10-01", deep)[0]
    trough = feed.quotes_for_date("2025-11-15", deep)[0]
    # tvl_usd carried verbatim from the contemporaneous series
    assert peak.tvl_usd == Decimal("142000000")
    assert trough.tvl_usd == Decimal("88000000")
    # the proxy SHRANK with the real pool depth (this is the whole fix)
    assert trough.exit_liquidity_usd < peak.exit_liquidity_usd
    # and shrank proportionally to TVL (exit = depth * band * sla_discount, linear in depth)
    ratio = trough.exit_liquidity_usd / peak.exit_liquidity_usd
    assert abs(ratio - Decimal("88") / Decimal("142")) < Decimal("0.0001")


def test_pendle_feed_exit_liquidity_falls_back_when_tvl_absent():
    """An OLD deep file (no `tvl_usd` in the series) fail-CLOSEs to the documented depth constant — so
    the model still has an honest, auditable input even on a pre-fix dataset (it just can't shrink)."""
    deep = _deep_dataset()  # the legacy shape: series carry NO tvl_usd
    feed = feeds.PendleMarketFeed()
    q = feed.quotes_for_date("2025-01-01", deep)[0]
    expected_depth = Decimal(str(config.PENDLE_HIST_POOL_DEPTH_USD))
    assert q.exit_liquidity_usd == feeds.exit_liquidity_usd(
        expected_depth, config.redemption_sla_seconds(q.underlying))


def test_pendle_feed_tvl_zero_falls_back_to_constant():
    """A non-positive / placeholder TVL (Pendle reports tvl≈0.1 at a market's pre-liquidity inception
    via the dust path; an explicit 0 here) degrades to the documented constant, never a 0 exit that
    would silently look like 'no market'. (A real tiny-but-positive TVL is used verbatim elsewhere.)"""
    deep = {
        "generated_at": "x", "method": "test", "underlyings": ["sUSDe"],
        "window": {"start": "2025-01-01", "end": "2025-01-01"},
        "markets": {
            "PT-sUSDE-26DEC2025": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-26DEC2025",
                "market_address": "0xMKT", "pt_address": "0xPT", "maturity": "2025-12-26",
                "method": "direct_api_implied",
                "series": [{"date": "2025-01-01", "implied_yield": 0.10, "underlying_yield": 0.09,
                            "tvl_usd": 0, "pt_price": None}],
            },
        },
    }
    feed = feeds.PendleMarketFeed()
    q = feed.quotes_for_date("2025-01-01", deep)[0]
    expected = feeds.exit_liquidity_usd(Decimal(str(config.PENDLE_HIST_POOL_DEPTH_USD)),
                                        config.redemption_sla_seconds("susde"))
    assert q.exit_liquidity_usd == expected


def test_contemporaneous_pool_depth_helper_failclosed():
    """The config helper: a real positive TVL is used verbatim; None / 0 / garbage → the constant."""
    const = Decimal(str(config.PENDLE_HIST_POOL_DEPTH_USD))
    assert config.contemporaneous_pool_depth_usd(50_000_000) == Decimal("50000000")
    assert config.contemporaneous_pool_depth_usd(None) == const
    assert config.contemporaneous_pool_depth_usd(0) == const
    assert config.contemporaneous_pool_depth_usd(-5) == const
    assert config.contemporaneous_pool_depth_usd("not-a-number") == const
    # a genuinely tiny but positive depth is honest, used verbatim (the exit gate refuses to size in)
    assert config.contemporaneous_pool_depth_usd(0.1) == Decimal("0.1")


def test_pendle_feed_date_without_sample_absent():
    deep = _deep_dataset()
    feed = feeds.PendleMarketFeed()
    rows = feed.quotes_for_date("2025-01-02", deep)
    # only sUSDe has a 2025-01-02 sample; ezETH does not
    assert {q.underlying for q in rows} == {"susde"}


def test_pendle_feed_fail_closed_malformed_market():
    deep = _deep_dataset()
    deep["markets"]["PT-sUSDE-26DEC2025"].pop("series")
    feed = feeds.PendleMarketFeed()
    with pytest.raises(feeds.FeedError):
        feed.quotes_for_date("2025-01-01", deep)


def test_pendle_feed_live_active_endpoint():
    active = {
        "markets": [
            {"address": "0xLIVE_SUSDE", "expiry": "2026-12-26T00:00:00.000Z",
             "impliedApy": 0.095, "tvl": {"usd": 12_000_000},
             "pt": {"address": "0xPTL", "symbol": "PT-sUSDE-26DEC2026"}},
            {"address": "0xLIVE_WRAP", "expiry": "2026-12-26T00:00:00.000Z",
             "impliedApy": 0.30, "liquidity": {"usd": 3_000_000},
             "pt": {"address": "0xPTW", "symbol": "PT-zs-ezETH-26DEC2026"}},  # wrapper → rejected
        ]
    }
    feed = feeds.PendleMarketFeed(fetcher=lambda url: active)
    rows = feed.quotes_live("2026-01-01", hedge_by_underlying={"susde": False})
    assert len(rows) == 1  # wrapper variant rejected by _match_underlying
    q = rows[0]
    assert q.underlying == "susde"
    assert q.tvl_usd == Decimal("12000000")
    assert q.quoted_rate == Decimal("0.095")
    assert q.venue is RateVenue.PENDLE_PT


def test_pendle_feed_live_active_rich_shape_multiple_underlyings():
    """The REAL /markets/active shape: each market is a FLAT dict with `name` (the underlying symbol),
    `expiry`, a `pt` chain-address string, and a `details` block carrying impliedApy + liquidity. The
    feed must surface ALL current target underlyings (sUSDe/USDe/sUSDS/wstETH) from this shape — this is
    the enrichment that fixes the thin-live-surface bug (the old paged /markets endpoint surfaced only
    ~2). A nested-wrapper underlying name (jrUSDe) is rejected; a depthless market is skipped."""
    active = {"markets": [
        {"name": "sUSDe", "expiry": "2030-08-13T00:00:00.000Z",
         "pt": "1-0xSUSDE", "details": {"impliedApy": 0.043, "liquidity": 9_000_000}},
        {"name": "USDe", "expiry": "2030-08-13T00:00:00.000Z",
         "pt": "1-0xUSDE", "details": {"impliedApy": 0.053, "liquidity": 450_000}},
        {"name": "sUSDS", "expiry": "2030-11-26T00:00:00.000Z",
         "pt": "1-0xSUSDS", "details": {"impliedApy": 0.049, "liquidity": 5_800_000}},
        {"name": "wstETH", "expiry": "2031-12-30T00:00:00.000Z",
         "pt": "1-0xWSTETH", "details": {"impliedApy": 0.025, "liquidity": 2_600_000}},
        {"name": "jrUSDe", "expiry": "2030-08-13T00:00:00.000Z",   # nested wrapper → rejected
         "pt": "1-0xJR", "details": {"impliedApy": 0.20, "liquidity": 1_000_000}},
        {"name": "sUSDe", "expiry": "2030-08-13T00:00:00.000Z",     # depthless → skipped
         "pt": "1-0xNODEPTH", "details": {"impliedApy": 0.04, "liquidity": 0}},
    ]}
    feed = feeds.PendleMarketFeed(fetcher=lambda url: active)
    rows = feed.quotes_live("2026-06-26")
    uls = sorted(q.underlying for q in rows)
    assert uls == ["susde", "susds", "usde", "wsteth"]  # all 4 targets, wrapper + depthless dropped
    susds = [q for q in rows if q.underlying == "susds"][0]
    assert susds.kind is UnderlyingKind.STABLE_RWA
    assert susds.quoted_rate == Decimal("0.049")
    assert susds.tvl_usd == Decimal("5800000")
    wst = [q for q in rows if q.underlying == "wsteth"][0]
    assert wst.kind is UnderlyingKind.LST
    assert wst.tvl_usd == Decimal("2600000")
    for q in rows:
        assert q.venue is RateVenue.PENDLE_PT
        assert isinstance(q.quoted_rate, Decimal) and q.exit_liquidity_usd > 0


def test_pendle_feed_live_fail_closed_bad_payload():
    feed = feeds.PendleMarketFeed(fetcher=lambda url: "not an object")
    with pytest.raises(feeds.FeedError):
        feed.quotes_live("2026-01-01")


def test_pendle_feed_live_default_fetcher_skips_when_offline():
    """A PendleMarketFeed built WITHOUT an injected fetcher uses the live endpoint. In CI (no egress)
    this must SKIP, never fail — proving the suite does not REQUIRE live network. The autouse network
    guard also guarantees it can never silently succeed against a real socket."""
    if not _network_available():
        pytest.skip("no network egress — live Pendle endpoint unreachable (CI-safe skip)")
    # Network is up but the autouse guard still forbids real sockets inside the suite, so the live
    # call is expected to be blocked deterministically rather than reaching out.
    feed = feeds.PendleMarketFeed()  # default real fetcher
    with pytest.raises((RuntimeError, feeds.FeedError, OSError)):
        feed.quotes_live("2026-01-01")


def test_pendle_feed_live_real_surface_is_not_thin_when_reachable():
    """When the live Pendle endpoint is genuinely reachable, the enriched feed surfaces a SANE number
    of current target PT markets (>= 3 — the thin-surface threshold). This is the regression guard for
    the bug this fix targets: the old feed surfaced only ~2. Skips cleanly with no egress (CI-safe).

    NOTE: this is the ONE test that legitimately reaches the network, so it must bypass the autouse
    socket guard by calling the real fetcher OUTSIDE the patched path — we instead probe liveness and,
    when up, restore the real socket for the duration of the call."""
    if not _network_available():
        pytest.skip("no network egress — live Pendle endpoint unreachable (CI-safe skip)")
    import datetime
    # temporarily restore real sockets (the autouse guard patched them) for this one live call
    socket.socket.connect = _REAL_SOCKET_CONNECT
    socket.create_connection = _REAL_CREATE_CONNECTION
    feed = feeds.PendleMarketFeed()
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    try:
        rows = feed.quotes_live(today)
    except (OSError, feeds.FeedError) as exc:  # transient endpoint hiccup → skip, don't flake
        pytest.skip(f"live Pendle endpoint not answering cleanly: {exc}")
    # the enriched live surface is NOT thin — at least the thin-surface floor of current targets
    assert len(rows) >= 3, f"live surface unexpectedly thin ({len(rows)} PT markets) — feed regression"
    for q in rows:
        assert q.venue is RateVenue.PENDLE_PT
        assert q.quoted_rate is not None and q.exit_liquidity_usd > 0
        assert q.tenor_seconds > 0  # only non-expired markets


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# LendingRateFeed
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _lending_fetcher():
    pools = {
        "status": "success",
        "data": [
            {"pool": "aave-usdc", "project": "aave-v3", "chain": "Ethereum", "symbol": "USDC",
             "apy": 4.5, "apyBase": 4.2, "apyBaseBorrow": 5.6, "tvlUsd": 800_000_000},
            {"pool": "morpho-usdc", "project": "morpho-blue", "chain": "Ethereum", "symbol": "USDC",
             "apy": 5.0, "apyBase": 4.8, "tvlUsd": 200_000_000},
        ],
    }
    lendborrow = [
        {"pool": "aave-usdc", "apyBaseBorrow": 5.6, "ltv": 0.77,
         "totalSupplyUsd": 800_000_000, "totalBorrowUsd": 600_000_000, "debtCeilingUsd": 1_000_000_000},
        {"pool": "morpho-usdc", "apyBaseBorrow": 6.1, "ltv": 0.86,
         "totalSupplyUsd": 200_000_000, "totalBorrowUsd": 100_000_000},
    ]

    def fetcher(url: str):
        if "lendBorrow" in url:
            return lendborrow
        if "pools" in url:
            return pools
        raise AssertionError(f"unexpected url {url}")

    return fetcher


def test_lending_feed_emits_supply_and_borrow_legs():
    feed = feeds.LendingRateFeed(fetcher=_lending_fetcher())
    rows = feed.quotes("2026-06-25")
    assert all(isinstance(q, RateQuote) and q.venue is RateVenue.LENDING for q in rows)
    aave = [q for q in rows if q.protocol == "aave-v3"]
    supply = [q for q in aave if q.market_id.endswith(":supply")][0]
    borrow = [q for q in aave if q.market_id.endswith(":borrow")][0]
    assert supply.quoted_rate == Decimal("4.2") / Decimal("100")
    assert borrow.quoted_rate == Decimal("5.6") / Decimal("100")
    # utilization = 600M/800M = 0.75; ltv passed through
    assert supply.utilization == Decimal("0.75")
    assert supply.ltv == Decimal("0.77")
    assert borrow.utilization == Decimal("0.75")


def test_lending_feed_cap_headroom():
    feed = feeds.LendingRateFeed(fetcher=_lending_fetcher())
    rows = feed.quotes("2026-06-25")
    aave_supply = [q for q in rows if q.protocol == "aave-v3" and q.market_id.endswith(":supply")][0]
    # cap 1B - borrow 600M = 400M headroom
    assert aave_supply.cap_headroom_usd == Decimal("400000000")


def test_lending_feed_fail_closed_no_match():
    empty = {"status": "success", "data": [{"pool": "x", "project": "nope", "chain": "Ethereum",
                                            "symbol": "DAI", "apy": 1.0, "tvlUsd": 1}]}
    feed = feeds.LendingRateFeed(fetcher=lambda url: empty if "pools" in url else [])
    with pytest.raises(feeds.FeedError):
        feed.quotes("2026-06-25")


def test_lending_feed_fail_closed_bad_payload():
    feed = feeds.LendingRateFeed(fetcher=lambda url: {"status": "error"})
    with pytest.raises(feeds.FeedError):
        feed.quotes("2026-06-25")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# BorosFeed — honest hedge_available
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def test_boros_hedge_available_honest_false():
    feed = feeds.BorosFeed()
    flags = feed.hedge_available(["sUSDe", "ezETH", "USDe"])
    assert flags == {"susde": False, "ezeth": False, "usde": False}
    assert feeds.BorosFeed.HEDGE_ENABLED is False


def test_boros_quotes_empty_while_no_venue():
    feed = feeds.BorosFeed()
    assert feed.quotes("2026-06-25") == []


def test_boros_quotes_fail_closed_bad_as_of():
    feed = feeds.BorosFeed()
    with pytest.raises(feeds.FeedError):
        feed.quotes("not-a-date")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# UnderlyingRiskFeed
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
class _FakeFunding:
    """Median 8h funding series with a known negative fraction over the trailing window."""

    def __init__(self, series):
        self._series = series

    def history(self, start_date=None, end_date=None):
        return {d: v for d, v in self._series.items() if (start_date is None or d >= start_date)
                and (end_date is None or d <= end_date)}


class _FakePrice:
    """X/ETH ratio history per token."""

    def __init__(self, ratios):
        self._ratios = ratios

    def history_ratios(self, span=90, start_date=None, end_date=None):
        return self._ratios


def _funding_series(n=900, neg_count=180, base=None):
    """A long daily median-funding series anchored at 2024-06-01 spanning ~2.5y (covers the 2025
    backtest as_of, the 2026 risk-test as_of, AND a live as_of of 'today'). ~20% of days negative."""
    import datetime
    base = base or datetime.date(2024, 6, 1)
    out = {}
    for i in range(n):
        d = (base + datetime.timedelta(days=i)).isoformat()
        out[d] = -0.0001 if (i % 5 == 0) else 0.0002  # ~20% negative, spread across the window
    return out


def test_underlying_risk_stable_at_par():
    funding = _FakeFunding(_funding_series())
    feed = feeds.UnderlyingRiskFeed(price_feed=_FakePrice({}), funding_feed=funding)
    risks = feed.risks("2026-04-30", ["susde", "usdy"])
    su = risks["susde"]
    assert isinstance(su, UnderlyingRisk)
    assert su.nav_redemption_value == Decimal("1")
    assert su.peg_distance == Decimal("0")
    assert su.redemption_sla_seconds == 86400 * 7
    assert su.reserve_fund_ratio == Decimal("0.011")  # Ethena ~1.1%
    assert su.nested_protocol_count == 1
    assert Decimal("0") <= su.funding_neg_frac_90d <= Decimal("1")
    assert su.funding_neg_frac_90d > Decimal("0")  # there ARE negative days in the window


def test_underlying_risk_lrt_peg_from_ratio():
    funding = _FakeFunding(_funding_series())
    import datetime
    base = datetime.date(2026, 1, 1)
    # ezETH ratio drifts up then draws down 5% near the end → measurable depeg + downside vol
    ratios = {"ezeth": {}}
    for i in range(120):
        d = (base + datetime.timedelta(days=i)).isoformat()
        if i < 100:
            ratios["ezeth"][d] = 1.02 + i * 0.0001  # value-accruing drift above 1.0
        else:
            ratios["ezeth"][d] = 1.03 - (i - 99) * 0.0015  # drawdown from peak
    feed = feeds.UnderlyingRiskFeed(price_feed=_FakePrice(ratios), funding_feed=funding)
    risks = feed.risks("2026-04-30", ["ezeth"])
    ez = risks["ezeth"]
    assert ez.peg_distance > Decimal("0")          # drawdown-from-peak measured
    assert ez.peg_vol_30d > Decimal("0")           # downside drift present
    assert ez.nested_protocol_count == 2           # restaking layer
    assert ez.market_price < ez.nav_redemption_value  # latest below the peak NAV ref


def test_underlying_risk_fail_closed_missing_lrt_ratio():
    funding = _FakeFunding(_funding_series())
    feed = feeds.UnderlyingRiskFeed(price_feed=_FakePrice({}), funding_feed=funding)
    with pytest.raises(feeds.FeedError):
        feed.risks("2026-04-30", ["ezeth"])  # no ratio series for an ETH underlying → fail-CLOSED


def test_underlying_risk_fail_closed_empty_funding():
    feed = feeds.UnderlyingRiskFeed(price_feed=_FakePrice({}), funding_feed=_FakeFunding({}))
    with pytest.raises(feeds.FeedError):
        feed.risks("2026-04-30", ["susde"])


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# build_surface — the assembler (backtest + live), determinism, caching
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _ezeth_ratio_hist(base=None, n=200):
    """An ezETH X/ETH ratio series (value-accruing drift then a small drawdown) so an LRT underlying
    in the deep dataset gets a real, non-fabricated peg signal in the assembler tests."""
    import datetime
    base = base or datetime.date(2024, 6, 1)
    out = {}
    for i in range(n):
        d = (base + datetime.timedelta(days=i)).isoformat()
        out[d] = 1.02 + i * 0.0001 if i < n - 20 else 1.02 + (n - 21) * 0.0001 - (i - (n - 21)) * 0.0010
    return {"ezeth": out, "weeth": out}


def _risk_feed():
    return feeds.UnderlyingRiskFeed(
        price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series()))


def test_build_surface_backtest_assembles_coherent_surface():
    deep = _deep_dataset()
    quotes, risks = feeds.build_surface(
        as_of="2025-01-01",
        deep=deep,
        pendle_feed=feeds.PendleMarketFeed(),
        lending_feed=feeds.LendingRateFeed(fetcher=_lending_fetcher()),
        boros_feed=feeds.BorosFeed(),
        risk_feed=feeds.UnderlyingRiskFeed(
            price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series())),
        include_lending=True,
    )
    # PT quotes (sUSDe + ezETH) + lending USDC legs
    venues = {q.venue for q in quotes}
    assert RateVenue.PENDLE_PT in venues
    assert RateVenue.LENDING in venues
    # ezETH is an LRT → it needs a ratio series; we used STABLE-only risk feed, so build must have
    # raised UNLESS ezETH appears. It DOES appear (PT quote), so risk_feed must serve it. Confirm
    # the coherent-surface contract: every quote underlying has a risk row.
    ul_quotes = {q.underlying for q in quotes}
    assert ul_quotes <= set(risks)  # every quoted underlying has a risk row
    for r in risks.values():
        assert isinstance(r, UnderlyingRisk)
        assert r.as_of == "2025-01-01"


def test_build_surface_live_mode():
    active = {"markets": [
        {"address": "0xLIVE_SUSDE", "expiry": "2030-12-26T00:00:00.000Z", "impliedApy": 0.095,
         "tvl": {"usd": 12_000_000}, "pt": {"address": "0xPTL", "symbol": "PT-sUSDE-26DEC2030"}},
    ]}
    quotes, risks = feeds.build_surface(
        as_of=None,  # live
        pendle_feed=feeds.PendleMarketFeed(fetcher=lambda url: active),
        lending_feed=feeds.LendingRateFeed(fetcher=_lending_fetcher()),
        boros_feed=feeds.BorosFeed(),
        risk_feed=_risk_feed(),
        include_lending=True,
    )
    assert any(q.venue is RateVenue.PENDLE_PT and q.underlying == "susde" for q in quotes)
    assert "susde" in risks


def test_build_surface_hedge_flag_propagates_honestly():
    deep = _deep_dataset()
    quotes, _ = feeds.build_surface(
        as_of="2025-01-01", deep=deep,
        pendle_feed=feeds.PendleMarketFeed(),
        lending_feed=feeds.LendingRateFeed(fetcher=_lending_fetcher()),
        boros_feed=feeds.BorosFeed(),
        risk_feed=feeds.UnderlyingRiskFeed(
            price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series())),
    )
    # honest: no keyless Boros → every quote's hedge flag is False
    assert all(q.hedge_available is False for q in quotes)


def test_build_surface_deterministic():
    deep = _deep_dataset()
    kw = dict(
        as_of="2025-01-01", deep=deep,
        pendle_feed=feeds.PendleMarketFeed(),
        lending_feed=feeds.LendingRateFeed(fetcher=_lending_fetcher()),
        boros_feed=feeds.BorosFeed(),
        risk_feed=feeds.UnderlyingRiskFeed(
            price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series())),
    )
    q1, r1 = feeds.build_surface(**kw)
    q2, r2 = feeds.build_surface(**kw)
    assert [feeds._quote_to_dict(q) for q in q1] == [feeds._quote_to_dict(q) for q in q2]
    assert {u: feeds._risk_to_dict(r) for u, r in r1.items()} == \
           {u: feeds._risk_to_dict(r) for u, r in r2.items()}


def test_build_surface_caches_atomically(tmp_path):
    deep = _deep_dataset()
    out = tmp_path / "rate_surface.json"
    feeds.build_surface(
        as_of="2025-01-01", deep=deep,
        pendle_feed=feeds.PendleMarketFeed(),
        lending_feed=feeds.LendingRateFeed(fetcher=_lending_fetcher()),
        boros_feed=feeds.BorosFeed(),
        risk_feed=feeds.UnderlyingRiskFeed(
            price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series())),
        cache=True, out_path=out,
    )
    assert out.exists()
    blob = json.loads(out.read_text())
    assert blob["mode"] == "backtest"
    assert blob["as_of"] == "2025-01-01"
    assert isinstance(blob["quotes"], list) and blob["quotes"]
    assert isinstance(blob["underlying_risk"], dict)
    assert blob["hedge_available"]  # the honest hedge map is recorded
    # no leftover temp files in the dir
    assert not list(tmp_path.glob(".*tmp"))


def test_build_surface_without_lending():
    deep = _deep_dataset()
    quotes, _ = feeds.build_surface(
        as_of="2025-01-01", deep=deep,
        pendle_feed=feeds.PendleMarketFeed(),
        boros_feed=feeds.BorosFeed(),
        risk_feed=feeds.UnderlyingRiskFeed(
            price_feed=_FakePrice(_ezeth_ratio_hist()), funding_feed=_FakeFunding(_funding_series())),
        include_lending=False,
    )
    assert all(q.venue is RateVenue.PENDLE_PT for q in quotes)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FIX 2 — KillState.high_util_since: continuous utilization-trap tracking (evaluate_hold)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# The brief's evaluate_hold must fire UTILIZATION_TRAP only when utilization stays above the ceiling
# CONTINUOUSLY for >= max_utilization_seconds. high_util_since (epoch of first crossing) carries that
# streak across ticks PURELY (state in → state out). These tests prove: a single high tick does NOT
# trap; the streak accrues across ticks with advancing as_of; the trap fires once the duration is met;
# and a tick that drops back below the ceiling RESETS the streak.
from dataclasses import replace  # noqa: E402

from spa_core.strategy_lab.rates_desk.contracts import (  # noqa: E402
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    TradeShape,
)
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_hold  # noqa: E402


_D = Decimal
# require a sustained 1-day high-utilization streak before trapping (vs the back-compat default of 0)
_UTIL_PARAMS = replace(RatePolicyParams(), max_utilization_seconds=86400)


def _util_risk(as_of: str) -> UnderlyingRisk:
    """A structurally HEALTHY underlying so the only thing that can kill is the utilization trap."""
    return UnderlyingRisk(
        underlying="susde", as_of=as_of,
        nav_redemption_value=_D("1"), market_price=_D("1.0003"), peg_distance=_D("0.0003"),
        peg_vol_30d=_D("0.001"), redemption_sla_seconds=86400, reserve_fund_ratio=_D("0.05"),
        funding_neg_frac_90d=_D("0.05"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=_D("0.1"),
    )


def _util_hold_opp(as_of: str, util: str) -> Opportunity:
    q = RateQuote(
        underlying="susde", kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT, protocol="p",
        market_id="pt-susde", tenor_seconds=86400 * 60, as_of=as_of,
        quoted_rate=_D("0.09"), tvl_usd=_D("5e7"), exit_liquidity_usd=_D("2e6"),
        hedge_available=True, utilization=_D(util), ltv=_D("0"),
    )
    return Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=_D("100000"))


def _hold(as_of: str, util: str, state: KillState):
    opp = _util_hold_opp(as_of, util)
    return evaluate_hold(opp, _util_risk(as_of), _D("1"), opp.quote.exit_liquidity_usd,
                         _D("0.05"), _UTIL_PARAMS, state)


def test_util_trap_single_high_tick_does_not_fire():
    """One tick above the ceiling must HOLD (not trap) and STAMP high_util_since for the streak."""
    res, ns = _hold("2026-06-01", "0.99", KillState(entry_carry=_D("0.05")))
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert ns.high_util_since is not None  # crossing recorded


def test_util_trap_fires_only_after_continuous_duration():
    """High utilization sustained ACROSS ticks for >= max_utilization_seconds → UTILIZATION_TRAP."""
    # tick 1 (day 0): first crossing → hold, streak stamped
    r1, s1 = _hold("2026-06-01", "0.99", KillState(entry_carry=_D("0.05")))
    assert r1.approved is True
    since = s1.high_util_since
    # tick 2 (~12h later, still < 1 day continuous) → still HOLD, same streak anchor
    r2, s2 = _hold("2026-06-01T12:00:00+00:00", "0.99", s1)
    assert r2.approved is True
    assert s2.high_util_since == since  # anchor carried forward, not re-stamped
    # tick 3 (day 1, >= 86400s continuous) → TRAP fires
    r3, s3 = _hold("2026-06-02", "0.99", s2)
    assert r3.approved is False
    assert r3.reason == KillReason.UTILIZATION_TRAP
    assert s3.killed is True


def test_util_trap_resets_when_utilization_drops():
    """A tick back below the ceiling clears the streak; a later spike restarts the clock from scratch."""
    # build up a streak
    _, s1 = _hold("2026-06-01", "0.99", KillState(entry_carry=_D("0.05")))
    assert s1.high_util_since is not None
    # utilization recovers → streak cleared
    r2, s2 = _hold("2026-06-01T12:00:00+00:00", "0.50", s1)
    assert r2.approved is True
    assert s2.high_util_since is None
    # a new spike a day later does NOT instantly trap (clock restarted, elapsed 0 < window)
    r3, s3 = _hold("2026-06-02", "0.99", s2)
    assert r3.approved is True
    assert r3.reason == KillReason.NONE
    assert s3.high_util_since is not None


def test_util_trap_default_params_fire_immediately_backcompat():
    """With the default max_utilization_seconds=0, a single high tick traps immediately (back-compat)."""
    opp = _util_hold_opp("2026-06-01", "0.99")
    res, ns = evaluate_hold(opp, _util_risk("2026-06-01"), _D("1"), opp.quote.exit_liquidity_usd,
                            _D("0.05"), RatePolicyParams(), KillState(entry_carry=_D("0.05")))
    assert res.approved is False
    assert res.reason == KillReason.UTILIZATION_TRAP
