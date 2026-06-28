"""Property-fuzz of the NON-DeFiLlama feeds (Sprint "Proof That Doesn't Rot", WS4 §4.2).

STDLIB-ONLY (seeded ``random.Random`` — NO ``hypothesis``), deterministic, fail-CLOSED, no
network (every fetch is an injected ``FakeFetcher`` returning a malformed/edge payload). Mirrors
the proven ``test_defillama_feed_fuzz.py`` pattern, applied to the feeds the DeFiLlama fuzz does
NOT cover:

  • funding_feed.FundingFeed   — the 5-venue CEX/DEX ETH-perp funding median (per-venue row
                                 parsers + cross-venue median).
  • rwa_feed.RWAFeed           — the live tokenized-T-bill risk-free FLOOR.
  • price_feed.PriceFeed       — ETH + LST/LRT USD prices via the coins API.
  • rates_desk.feeds._D / feeds._apr_to_decimal — the Rates-Desk numeric parser at the heart of
                                 the RateSurface (whose output is cached + served by the proof API).

The contract under test, asserted for EVERY input:

  1. The parser NEVER raises an UNHANDLED exception (only the feeds' own fail-CLOSED
     ``InvalidDataError`` / ``FeedError`` / ``FetchError`` is allowed).
  2. It NEVER emits a NaN/inf number (a non-finite funding rate / price / floor / Decimal is a
     fabricated value: it poisons medians, ``x < 0`` checks, and the cached surface).
  3. It NEVER fabricates a fallback yield/price on bad input — bad/missing → raise (fail-CLOSED) or
     an explicitly empty result, never an invented benign number.

REAL BUGS this fuzz found + fixed (minimal fail-closed guards, behaviour-preserving on valid data):
  • funding_feed: a NaN/inf funding-rate token poisoned the per-day cross-venue median (and slipped
    past ``rate < 0`` since NaN comparisons are always False). → ``_finite_rate`` rejects non-finite.
  • price_feed:   a bare JSON NaN/inf price passed ``price <= 0`` (False for NaN) and leaked into
    the snapshot/history. → ``math.isfinite`` guard in ``_extract_price`` + ``_parse_chart``.
  • rates_desk.feeds._D: ``Decimal("NaN")`` / ``Decimal("Infinity")`` are valid Decimals, so
    ``float("nan")``/``"NaN"`` parsed into a non-finite quoted_rate/tvl. → ``_D`` rejects non-finite.

Run:  python3 -m pytest spa_core/tests/test_feeds_fuzz.py -p no:randomly -q
"""
from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategy_lab.base import InvalidDataError  # noqa: E402
from spa_core.strategy_lab.data import funding_feed as _ff  # noqa: E402
from spa_core.strategy_lab.data import rwa_feed as _rwa  # noqa: E402
from spa_core.strategy_lab.data import price_feed as _pf  # noqa: E402
from spa_core.strategy_lab.data._http import FetchError  # noqa: E402
from spa_core.strategy_lab.rates_desk import feeds as _rd_feeds  # noqa: E402

# The fail-CLOSED exception family every feed is allowed to raise (and ONLY this family).
_OK_EXC = (InvalidDataError, _rd_feeds.FeedError, FetchError)

# ─── shared weird-value alphabet ──────────────────────────────────────────────
_UNICODE = ["", "ünïcödé", "🦙", "项目", "\x00​", "a" * 200, "NaN", "Infinity"]
_WEIRD_NUMS = [
    0, -1, 1, 8.5, -3.0, 1e9, 1e308, 1e400,
    float("nan"), float("inf"), float("-inf"),
    "8.5", "nan", "NaN", "Infinity", "-inf", "  7.0  ", "", "abc", "1e999",
    None, True, False, [], {}, {"usd": 5.0},
]


def _rand_scalar(rng: random.Random):
    return rng.choice(_WEIRD_NUMS + _UNICODE)


def _assert_finite_or_none(test, v, ctx=""):
    if v is None:
        return
    if isinstance(v, float):
        test.assertTrue(math.isfinite(v), f"NON-FINITE leak: {v!r} {ctx}")


# ══════════════════════════════════════════════════════════════════════════════
# 1) funding_feed — the 5-venue median (per-venue row parsers + cross-venue merge)
# ══════════════════════════════════════════════════════════════════════════════
def _rand_funding_row(rng: random.Random, ts_field: str) -> dict:
    row = {ts_field: rng.choice([1_700_000_000_000, 1_700_000_000_000.0, "1700000000000",
                                 None, "x", -5, float("nan")]),
           "fundingRate": _rand_scalar(rng), "symbol": "ETHUSDT"}
    for k in list(row):
        if rng.random() < 0.15:
            del row[k]
    return row


def _rand_binance_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.15:
        return rng.choice([[], {}, None, 42, "x", [1, 2, 3]])
    return [_rand_funding_row(rng, "fundingTime") for _ in range(rng.randint(0, 5))]


def _rand_bybit_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([{}, {"retCode": 1}, {"retCode": 0}, {"retCode": 0, "result": "x"},
                           None, [], 5])
    rows = [_rand_funding_row(rng, "fundingRateTimestamp") for _ in range(rng.randint(0, 5))]
    return {"retCode": 0, "result": {"list": rows}}


def _rand_okx_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([{}, {"code": "1"}, {"code": "0"}, {"code": "0", "data": "x"}, None, 5])
    return {"code": "0", "data": [_rand_funding_row(rng, "fundingTime")
                                  for _ in range(rng.randint(0, 5))]}


def _rand_kucoin_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([{}, {"code": "1"}, {"code": "200000"},
                           {"code": "200000", "data": "x"}, None])
    return {"code": "200000", "data": [_rand_funding_row(rng, "timepoint")
                                       for _ in range(rng.randint(0, 5))]}


def _rand_hl_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([[], {}, None, 42, "x"])
    return [_rand_funding_row(rng, "time") for _ in range(rng.randint(0, 5))]


class TestFundingFeedFuzz(unittest.TestCase):
    N_CASES = 400

    def test_fuzz_row_parsers_never_raise_unhandled_never_nonfinite(self):
        rng = random.Random(0xF00D)
        parsers = [
            (_ff._rows_binance, _rand_binance_payload),
            (_ff._rows_bybit, _rand_bybit_payload),
            (_ff._rows_okx, _rand_okx_payload),
            (_ff._rows_kucoin, _rand_kucoin_payload),
            (_ff._rows_hyperliquid, _rand_hl_payload),
        ]
        for i in range(self.N_CASES):
            parse, gen = rng.choice(parsers)
            payload = gen(rng)
            ctx = f"[case {i}] {parse.__name__} payload={payload!r:.120}"
            try:
                rows = parse(payload)
            except _OK_EXC:
                continue  # fail-CLOSED is the allowed outcome
            except Exception as exc:  # noqa: BLE001
                self.fail(f"{parse.__name__} RAISED unhandled {type(exc).__name__}: {exc} {ctx}")
            # A clean parse must yield ONLY finite rates (the bug we fixed).
            for ts, rate in rows:
                self.assertIsInstance(rate, float, ctx)
                self.assertTrue(math.isfinite(rate), f"NON-FINITE funding rate {rate!r} {ctx}")

    def test_fuzz_full_feed_history_never_nonfinite(self):
        """End-to-end: a FakeFetcher that routes each venue URL to a random payload. The merged
        median is EITHER raised (no venue produced data) OR a dict of FINITE rates — never NaN."""
        rng = random.Random(0xBEEF)
        for i in range(120):
            def fake(url, _rng=rng):
                u = url.lower()
                if "binance" in u:
                    return _rand_binance_payload(_rng)
                if "bybit" in u:
                    return _rand_bybit_payload(_rng)
                if "okx" in u:
                    return _rand_okx_payload(_rng)
                if "kucoin" in u:
                    return _rand_kucoin_payload(_rng)
                return _rand_hl_payload(_rng)  # hyperliquid
            feed = _ff.FundingFeed(fetcher=fake, page_delay_s=0.0)
            ctx = f"[feed case {i}]"
            try:
                series = feed.history()
            except _OK_EXC:
                continue
            except Exception as exc:  # noqa: BLE001
                self.fail(f"FundingFeed.history RAISED {type(exc).__name__}: {exc} {ctx}")
            self.assertIsInstance(series, dict, ctx)
            for d, rate in series.items():
                self.assertTrue(math.isfinite(rate), f"NON-FINITE median {rate!r} on {d} {ctx}")

    # ── pinned real-bug regressions ──────────────────────────────────────────
    def test_pin_nan_funding_rate_rejected(self):
        for tok in ["NaN", "Infinity", "-Infinity", float("nan"), float("inf")]:
            payload = [{"symbol": "ETHUSDT", "fundingTime": 1_700_000_000_000,
                        "fundingRate": tok}]
            with self.assertRaises(InvalidDataError, msg=f"NaN rate {tok!r} not rejected"):
                _ff._rows_binance(payload)

    def test_pin_valid_funding_rate_preserved(self):
        payload = [{"symbol": "ETHUSDT", "fundingTime": 1_700_000_000_000,
                    "fundingRate": "0.0001"}]
        rows = _ff._rows_binance(payload)
        self.assertEqual(rows, [(1_700_000_000_000, 0.0001)])
        merged = _ff._merge_median([_ff._rows_to_by_date(dict(rows))])
        for v in merged.values():
            self.assertTrue(math.isfinite(v))

    def test_pin_one_bad_venue_does_not_fabricate(self):
        """A NaN-poisoned venue must NOT leak NaN into the median; the median is over the rest."""
        good = [{"symbol": "ETHUSDT", "fundingTime": 1_700_000_000_000, "fundingRate": "0.0002"}]
        poisoned = [{"symbol": "ETHUSDT", "fundingTime": 1_700_000_000_000, "fundingRate": "NaN"}]
        b = _ff._try_venue(lambda: _ff._parse_binance(good))
        p = _ff._try_venue(lambda: _ff._parse_bybit({"retCode": 0,
                                                     "result": {"list": [
                                                         {"fundingRate": "NaN",
                                                          "fundingRateTimestamp": "1700000000000"}]}}))
        _ = poisoned
        merged = _ff._merge_median([b, p])  # p contributes {} (fail-OPEN per-venue)
        for v in merged.values():
            self.assertTrue(math.isfinite(v), f"NaN venue poisoned median: {v!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 2) rwa_feed — the tokenized-T-bill FLOOR (fail-CLOSED, never a fabricated yield)
# ══════════════════════════════════════════════════════════════════════════════
def _rand_rwa_pool(rng: random.Random) -> object:
    if rng.random() < 0.1:
        return rng.choice([None, 5, "x", []])
    sel = rng.choice(_rwa.SELECTORS)
    pool = {
        "project": rng.choice([sel["project"], "random-proj", "", None, 7] + _UNICODE),
        "symbol": rng.choice([sel["symbol"], sel["symbol"].lower(), "", None] + _UNICODE),
        "chain": rng.choice(["Ethereum", "", None]),
        "apy": _rand_scalar(rng),
        "tvlUsd": _rand_scalar(rng),
        "pool": rng.choice(["uuid-x", None, 5, ""]),
    }
    for k in list(pool):
        if rng.random() < 0.15:
            del pool[k]
    return pool


def _rand_rwa_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([{}, {"status": "error"}, {"status": "success"},
                           {"status": "success", "data": "x"},
                           {"status": "success", "data": []}, None, [], 42])
    return {"status": "success",
            "data": [_rand_rwa_pool(rng) for _ in range(rng.randint(0, 6))]}


class TestRWAFeedFuzz(unittest.TestCase):
    N_CASES = 300

    def test_fuzz_compute_never_fabricates_never_nonfinite(self):
        rng = random.Random(0x12345)
        for i in range(self.N_CASES):
            payload = _rand_rwa_payload(rng)
            feed = _rwa.RWAFeed(fetcher=lambda _u, _p=payload: _p)
            ctx = f"[rwa case {i}] payload={payload!r:.120}"
            try:
                res = feed.compute()
            except _OK_EXC:
                continue  # fail-CLOSED: <min_pools qualified → raised (never a fabricated floor)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"RWAFeed.compute RAISED {type(exc).__name__}: {exc} {ctx}")
            floor = res["floor_apy_pct"]
            self.assertTrue(math.isfinite(floor), f"NON-FINITE floor {floor!r} {ctx}")
            # a real blended T-bill floor sits in the sane band the feed enforces per-pool.
            self.assertGreaterEqual(floor, _rwa.MIN_SANE_APY_PCT - 1e-9, ctx)
            self.assertLessEqual(floor, _rwa.MAX_SANE_APY_PCT + 1e-9, ctx)
            self.assertGreaterEqual(res["n_pools"], 2, ctx)

    def test_pin_nan_apy_pool_does_not_qualify(self):
        """A NaN/inf apy in a matching pool must NOT pass the sane-band gate (fail-CLOSED)."""
        pools = [{"project": "ondo-yield-assets", "symbol": "USDY", "apy": float("nan"),
                  "tvlUsd": 1e8, "pool": "p1"},
                 {"project": "blackrock-buidl", "symbol": "BUIDL", "apy": float("inf"),
                  "tvlUsd": 1e8, "pool": "p2"}]
        self.assertEqual(_rwa._qualifying_pools(pools, 5e6), [])

    def test_pin_valid_floor_computed(self):
        pools = [{"project": "ondo-yield-assets", "symbol": "USDY", "apy": 3.5,
                  "tvlUsd": 1e9, "pool": "p1"},
                 {"project": "blackrock-buidl", "symbol": "BUIDL", "apy": 3.5,
                  "tvlUsd": 8e8, "pool": "p2"}]
        feed = _rwa.RWAFeed(fetcher=lambda _u: {"status": "success", "data": pools})
        res = feed.compute()
        self.assertTrue(math.isfinite(res["floor_apy_pct"]))
        self.assertAlmostEqual(res["floor_apy_pct"], 3.5, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# 3) price_feed — ETH + LST/LRT USD prices (NaN price must never leak)
# ══════════════════════════════════════════════════════════════════════════════
def _rand_price_payload(rng: random.Random):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice([{}, {"coins": {}}, {"coins": "x"}, None, [], 42,
                           {"coins": {"ethereum:0xbad": {"price": float("nan")}}}])
    coins = {}
    for sym, addr in _pf.TOKENS.items():
        if rng.random() < 0.85:
            coins[f"ethereum:{addr}"] = {
                "price": _rand_scalar(rng), "symbol": sym.upper(),
                "timestamp": rng.choice([1_700_000_000, "x", None, float("nan")]),
            }
    return {"coins": coins}


class TestPriceFeedFuzz(unittest.TestCase):
    N_CASES = 300

    def test_fuzz_current_never_nonfinite_never_unhandled(self):
        rng = random.Random(0x5151)
        for i in range(self.N_CASES):
            payload = _rand_price_payload(rng)
            feed = _pf.PriceFeed(fetcher=lambda _u, _p=payload: _p)
            ctx = f"[price case {i}]"
            try:
                snap = feed.current()
            except _OK_EXC:
                continue  # fail-CLOSED: any missing/invalid price → raised
            except Exception as exc:  # noqa: BLE001
                self.fail(f"PriceFeed.current RAISED {type(exc).__name__}: {exc} {ctx}")
            prices = snap.get("prices", snap) if isinstance(snap, dict) else {}
            for k, v in (prices.items() if isinstance(prices, dict) else []):
                _assert_finite_or_none(self, v, f"{ctx} key={k}")
            # the ratio map must also be finite
            ratios = snap.get("lrt_eth_ratio", {}) if isinstance(snap, dict) else {}
            for k, v in (ratios.items() if isinstance(ratios, dict) else []):
                _assert_finite_or_none(self, v, f"{ctx} ratio={k}")

    def test_pin_nan_price_rejected(self):
        from spa_core.strategy_lab.data.price_feed import TOKENS
        for bad in [float("nan"), float("inf"), float("-inf")]:
            coins = {f"ethereum:{a}": {"price": bad, "symbol": s.upper(),
                                       "timestamp": 1_700_000_000}
                     for s, a in TOKENS.items()}
            feed = _pf.PriceFeed(fetcher=lambda _u, _c=coins: {"coins": _c})
            with self.assertRaises(InvalidDataError, msg=f"NaN price {bad!r} not rejected"):
                feed.current()

    def test_pin_valid_price_preserved(self):
        from spa_core.strategy_lab.data.price_feed import TOKENS
        coins = {f"ethereum:{a}": {"price": 2000.0 if s == "eth" else 1.0, "symbol": s.upper(),
                                   "timestamp": 1_700_000_000}
                 for s, a in TOKENS.items()}
        feed = _pf.PriceFeed(fetcher=lambda _u: {"coins": coins})
        snap = feed.current()
        prices = snap.get("prices", snap)
        self.assertTrue(math.isfinite(prices["eth"]))
        self.assertEqual(prices["eth"], 2000.0)


# ══════════════════════════════════════════════════════════════════════════════
# 4) rates_desk.feeds._D — the Rates-Desk numeric parser (feeds the cached surface)
# ══════════════════════════════════════════════════════════════════════════════
class TestRatesDeskNumericFuzz(unittest.TestCase):
    N_CASES = 400

    def test_fuzz_D_never_nonfinite_never_unhandled(self):
        rng = random.Random(0xD0D0)
        for i in range(self.N_CASES):
            x = _rand_scalar(rng)
            ctx = f"[_D case {i}] x={x!r}"
            try:
                d = _rd_feeds._D(x)
            except _OK_EXC:
                continue  # fail-CLOSED
            except Exception as exc:  # noqa: BLE001
                self.fail(f"_D RAISED unhandled {type(exc).__name__}: {exc} {ctx}")
            self.assertTrue(d.is_finite(), f"NON-FINITE Decimal {d!r} {ctx}")

    def test_fuzz_apr_to_decimal_never_nonfinite(self):
        rng = random.Random(0xAA55)
        for i in range(self.N_CASES):
            x = _rand_scalar(rng)
            try:
                d = _rd_feeds._apr_to_decimal(x)
            except _OK_EXC:
                continue
            except Exception as exc:  # noqa: BLE001
                self.fail(f"_apr_to_decimal RAISED {type(exc).__name__}: {exc} [x={x!r}]")
            self.assertTrue(d.is_finite(), f"NON-FINITE apr Decimal {d!r} [x={x!r}]")

    def test_pin_nan_inf_decimal_rejected(self):
        for tok in [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"]:
            with self.assertRaises(_rd_feeds.FeedError, msg=f"{tok!r} not rejected"):
                _rd_feeds._D(tok)

    def test_pin_valid_decimal_preserved(self):
        from decimal import Decimal
        self.assertEqual(_rd_feeds._D("8.5"), Decimal("8.5"))
        self.assertEqual(_rd_feeds._D(8.5), Decimal("8.5"))
        self.assertTrue(_rd_feeds._D("1e400").is_finite())  # Decimal exponent is unbounded — honest


if __name__ == "__main__":
    unittest.main(verbosity=2)
