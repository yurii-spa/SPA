"""Property-fuzz of the DeFiLlama feed parser boundary (3-day sprint T9).

STDLIB-ONLY (seeded ``random.Random`` — NO ``hypothesis``), deterministic,
fail-CLOSED. Fuzzes the *raw bytes → decode (gzip!) → json.loads → extract
APY/TVL → return* path of ``spa_core/adapters/defillama_feed.py`` (and the
Pendle ``_parse_market`` / ``_safe_float`` boundary, whose ``tvl:null →
liquidity.usd`` fallback is the second documented bug surface).

The contract under test (the whole point of SPA-V398 + the memory bugs):

    For EVERY input — truncated gzip, non-gzip garbage, ``0x8b``-prefixed
    bytes, valid-gzip-invalid-JSON, ``tvl:null``, missing ``apy``, apy as
    string / negative / NaN / inf / huge, empty ``{}`` / ``[]``, partial
    records, wrong types, unicode, huge numbers —

      1. the parser NEVER raises an unhandled exception, and
      2. it returns EITHER ``None``/empty OR well-typed *bounded* data:
         - apy: a FINITE float in a sane band (or ``None``),
         - tvl: a FINITE float ``>= 0`` (or ``None``),
      3. it NEVER fabricates a fallback APY (never a hard-coded non-``None``
         number on bad input).

Pinned real bugs (from memory):
  * gzip-undecompressed (``0x1f 0x8b``)  → ``None``, not a crash.
  * ``tvl: null``                        → liquidity.usd or ``None``, never NaN.
  * missing ``apy``                      → ``None``.
  * NaN / Infinity tokens (json.loads accepts them by default; NaN slips past
    ``apy < 0 or apy > 200`` because NaN comparisons are always False)
                                         → ``None``, never returned as "valid".

Run:  python3 -m pytest spa_core/tests/test_defillama_feed_fuzz.py -p no:randomly -q
"""
from __future__ import annotations

import gzip
import json as _json
import math
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters import defillama_feed as _dl  # noqa: E402
from spa_core.adapters.defillama_feed import DeFiLlamaFeed  # noqa: E402
from spa_core.adapters import pendle_pt as _pp  # noqa: E402


# ─── raw-bytes injection (the repo pattern: patch urlopen → ctx-mgr.read()) ───

def _feed():
    return DeFiLlamaFeed(enabled=True, cache_ttl=300)


def _patch_raw(raw_bytes: bytes):
    """Patch ``urllib.request.urlopen`` so ``resp.read()`` yields raw_bytes."""
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=cm)
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = raw_bytes
    return mock.patch(
        "spa_core.adapters.defillama_feed.urllib.request.urlopen", return_value=cm
    )


# ─── bounded-value contract assertions ───────────────────────────────────────

# A defensible upper bound for *any* honest USD figure we'd accept; values
# beyond this on bad input would be a non-bounded leak, not real data.
_TVL_MAX = 1e15  # $1 quadrillion — larger than any real DeFi pool by orders.


def _assert_apy_bounded(test, apy, ctx=""):
    """apy must be None OR a finite float in the sane band [0, sanity_max]."""
    if apy is None:
        return
    test.assertIsInstance(apy, float, f"apy not float: {apy!r} {ctx}")
    test.assertTrue(math.isfinite(apy), f"apy not finite (NaN/inf leak): {apy!r} {ctx}")
    # fetch_* enforces the [0, APY_SANITY_MAX] band; get_apy is a decimal but
    # still must never be NaN/inf/absurd. Accept a generous superset.
    test.assertGreaterEqual(apy, -1.0, f"apy wildly negative: {apy!r} {ctx}")
    test.assertLessEqual(apy, _dl.APY_SANITY_MAX, f"apy beyond sanity max: {apy!r} {ctx}")


def _assert_tvl_bounded(test, tvl, ctx=""):
    """tvl must be None OR a finite float >= 0 and below the absurd ceiling."""
    if tvl is None:
        return
    test.assertIsInstance(tvl, float, f"tvl not float: {tvl!r} {ctx}")
    test.assertTrue(math.isfinite(tvl), f"tvl not finite (NaN/inf leak): {tvl!r} {ctx}")
    test.assertGreaterEqual(tvl, 0.0, f"tvl negative: {tvl!r} {ctx}")
    test.assertLessEqual(tvl, _TVL_MAX, f"tvl beyond absurd ceiling: {tvl!r} {ctx}")


# ─── malformed-payload generators (seeded, deterministic) ────────────────────

_UNICODE = ["", "ünïcödé", "🦙", "项目", "\x00\u200b", "a" * 300, "NaN", "Infinity"]
_WEIRD_NUMS = [
    0, -1, 1, 8.5, -3.0, 250.0, 200.0, 1e9, 1e308, 1e400,
    float("nan"), float("inf"), float("-inf"),
    "8.5", "nan", "NaN", "Infinity", "-inf", "  7.0  ", "", "abc", "1e999",
    None, True, False, [], {}, {"usd": 5.0},
]


def _rand_scalar(rng: random.Random):
    return rng.choice(_WEIRD_NUMS + _UNICODE)


def _rand_pool(rng: random.Random) -> object:
    """A pool record that is *sometimes* a dict, sometimes junk."""
    roll = rng.random()
    if roll < 0.12:
        return rng.choice([None, 42, "x", [], 3.14, True])
    pool = {
        "project": rng.choice(["yearn-finance", "morpho-blue", "", 123, None]
                              + _UNICODE),
        "symbol": rng.choice(["USDC", "usdc", "", None, 7] + _UNICODE),
        "chain": rng.choice(["Ethereum", "ethereum", "Polygon", "", None]),
        "apy": _rand_scalar(rng),
        "tvlUsd": _rand_scalar(rng),
        "pool": rng.choice(["uuid-x", None, 5, ""]),
    }
    # randomly delete fields → partial records / missing apy
    for k in list(pool):
        if rng.random() < 0.2:
            del pool[k]
    return pool


def _rand_payload_bytes(rng: random.Random) -> bytes:
    """Produce one malformed/edge raw HTTP body (bytes)."""
    roll = rng.random()

    if roll < 0.10:
        # truncated gzip: real gzip header bytes then cut off.
        good = gzip.compress(b'{"status":"success","data":[]}')
        return good[: rng.randint(1, max(2, len(good) - 1))]
    if roll < 0.18:
        # 0x8b-prefixed garbage (THE documented gzip-magic bug surface).
        return b"\x1f\x8b" + bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 40)))
    if roll < 0.26:
        # non-gzip raw garbage bytes.
        return bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 64)))
    if roll < 0.34:
        # valid gzip wrapping invalid JSON.
        return gzip.compress(rng.choice([b"not json", b"{", b"[1,2", b"\xff\xfe", b""]))
    if roll < 0.42:
        # valid gzip wrapping a VALID success payload of random pools.
        n = rng.randint(0, 5)
        body = _json.dumps(
            {"status": "success", "data": [_rand_pool(rng) for _ in range(n)]},
            allow_nan=True,
        )
        return gzip.compress(body.encode("utf-8"))
    if roll < 0.55:
        # plain (non-gzip) valid JSON, success wrapper, random pools.
        n = rng.randint(0, 6)
        body = _json.dumps(
            {"status": "success", "data": [_rand_pool(rng) for _ in range(n)]},
            allow_nan=True,
        )
        return body.encode("utf-8")
    if roll < 0.63:
        # success wrapper but 'data' is the wrong type.
        body = _json.dumps(
            {"status": "success", "data": rng.choice([{}, "x", 5, None, {"oops": 1}])}
        )
        return body.encode("utf-8")
    if roll < 0.71:
        # wrong / missing status.
        body = _json.dumps(
            {"status": rng.choice(["error", "", None, 1]), "data": []}
        )
        return body.encode("utf-8")
    if roll < 0.79:
        # top-level is a list / scalar / non-dict.
        body = _json.dumps(rng.choice([[], [1, 2], 42, "string", None]))
        return body.encode("utf-8")
    if roll < 0.87:
        # empty body / whitespace.
        return rng.choice([b"", b"   ", b"\n", b"null", b"{}"])
    if roll < 0.94:
        # NaN/Infinity tokens embedded in an otherwise-valid success payload
        # (json.loads accepts them by default → the documented NaN-leak path).
        pool = {
            "project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
            "apy": rng.choice(["NaN", "Infinity", "-Infinity"]),
            "tvlUsd": rng.choice(["NaN", "Infinity", "1e400"]),
            "pool": "u",
        }
        body = (
            '{"status":"success","data":[{"project":"yearn-finance",'
            '"symbol":"USDC","chain":"Ethereum","apy":'
            + rng.choice(["NaN", "Infinity", "-Infinity"])
            + ',"tvlUsd":'
            + rng.choice(["NaN", "Infinity", "10000000.0"])
            + ',"pool":"u"}]}'
        )
        _ = pool  # keep both shapes around for clarity
        return body.encode("utf-8")
    if roll < 0.97:
        # otherwise-valid matching pool with an absurd-but-FINITE numeric field
        # (1e308 overflows when scaled; passes isfinite but is not real data).
        apy = rng.choice(["8.5", "1e308", "1e307"])
        tvl = rng.choice(["1e308", "1e307", "10000000.0", "1e400"])
        body = ('{"status":"success","data":[{"project":"yearn-finance",'
                '"symbol":"USDC","chain":"Ethereum","apy":' + apy
                + ',"tvlUsd":' + tvl + ',"pool":"u"}]}')
        return body.encode("utf-8")
    # otherwise: deeply nested unicode noise.
    body = _json.dumps(
        {"status": "success",
         "data": [{"project": rng.choice(_UNICODE), "symbol": "USDC",
                   "chain": "Ethereum", "apy": _rand_scalar(rng),
                   "tvlUsd": _rand_scalar(rng)}]},
        allow_nan=True,
    )
    return body.encode("utf-8")


# ─── the property-fuzz test ──────────────────────────────────────────────────

class TestDeFiLlamaFeedFuzz(unittest.TestCase):
    N_CASES = 400

    def test_fuzz_parser_never_raises_never_fabricates(self):
        rng = random.Random(0xC0FFEE)  # deterministic seed
        for i in range(self.N_CASES):
            raw = _rand_payload_bytes(rng)
            ctx = f"[case {i}] raw[:40]={raw[:40]!r}"

            # fetch_* surface (percentage + liveness band) -------------------
            with _patch_raw(raw):
                f = _feed()
                try:
                    pool = f.fetch_pool("yearn-finance", "USDC")
                    apy_p = f.fetch_apy("yearn-finance", "USDC")
                    tvl_p = f.fetch_tvl("yearn-finance", "USDC")
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"fetch_* RAISED {type(exc).__name__}: {exc}  {ctx}")

            if pool is not None:
                self.assertIsInstance(pool, dict, ctx)
                self.assertEqual(set(pool), {"apy", "tvl", "pool_id"}, ctx)
                _assert_apy_bounded(self, pool["apy"], ctx)
                _assert_tvl_bounded(self, pool["tvl"], ctx)
            _assert_apy_bounded(self, apy_p, ctx)
            _assert_tvl_bounded(self, tvl_p, ctx)

            # get_* surface (decimal, no band) -------------------------------
            with _patch_raw(raw):
                g = _feed()
                try:
                    apy_d = g.get_apy("yearn-finance", "USDC")
                    tvl_d = g.get_tvl("yearn-finance", "USDC")
                    pool2 = g.get_pool("yearn-finance", "USDC")
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"get_* RAISED {type(exc).__name__}: {exc}  {ctx}")
            # get_apy is a decimal; bound finiteness + sane decimal band.
            if apy_d is not None:
                self.assertIsInstance(apy_d, float, ctx)
                self.assertTrue(math.isfinite(apy_d), f"get_apy NaN/inf leak: {apy_d!r} {ctx}")
            _assert_tvl_bounded(self, tvl_d, ctx)
            if pool2 is not None:
                self.assertIsInstance(pool2, dict, ctx)

    # ── pinned real-bug regressions ─────────────────────────────────────────

    def test_pin_gzip_undecompressed_returns_none(self):
        # 0x8b magic but undecompressable garbage → None, never a crash.
        bad = bytes([0x1F, 0x8B, 0x08, 0x00]) + b"garbage-not-real-gzip-stream"
        with _patch_raw(bad):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))
            self.assertIsNone(_feed().get_apy("yearn-finance", "USDC"))

    def test_pin_valid_gzip_roundtrips(self):
        # A correctly gzip-compressed valid payload MUST decode and parse.
        pool = {"project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
                "apy": 8.5, "tvlUsd": 10_000_000.0, "pool": "u"}
        body = _json.dumps({"status": "success", "data": [pool]}).encode("utf-8")
        with _patch_raw(gzip.compress(body)):
            self.assertEqual(_feed().fetch_apy("yearn-finance", "USDC"), 8.5)

    def test_pin_missing_apy_returns_none(self):
        pool = {"project": "yearn-finance", "symbol": "USDC", "chain": "Ethereum",
                "tvlUsd": 10_000_000.0, "pool": "u"}  # no 'apy'
        body = _json.dumps({"status": "success", "data": [pool]}).encode("utf-8")
        with _patch_raw(body):
            self.assertIsNone(_feed().fetch_pool("yearn-finance", "USDC"))
            self.assertIsNone(_feed().get_apy("yearn-finance", "USDC"))

    def test_pin_nan_apy_never_returned(self):
        # json.loads accepts NaN; NaN slips past `apy<0 or apy>200`. fail-CLOSED.
        body = (b'{"status":"success","data":[{"project":"yearn-finance",'
                b'"symbol":"USDC","chain":"Ethereum","apy":NaN,'
                b'"tvlUsd":10000000.0,"pool":"u"}]}')
        with _patch_raw(body):
            self.assertIsNone(_feed().fetch_apy("yearn-finance", "USDC"))
        with _patch_raw(body):
            self.assertIsNone(_feed().get_apy("yearn-finance", "USDC"))

    def test_pin_inf_apy_never_returned(self):
        body = (b'{"status":"success","data":[{"project":"yearn-finance",'
                b'"symbol":"USDC","chain":"Ethereum","apy":Infinity,'
                b'"tvlUsd":10000000.0,"pool":"u"}]}')
        with _patch_raw(body):
            self.assertIsNone(_feed().fetch_apy("yearn-finance", "USDC"))
        with _patch_raw(body):
            self.assertIsNone(_feed().get_apy("yearn-finance", "USDC"))

    def test_pin_absurd_finite_tvl_never_returned(self):
        # 1e308 is finite (passes isfinite) but is not real on-chain data and
        # would leak as an unbounded figure. fail-CLOSED → rejected.
        body = (b'{"status":"success","data":[{"project":"yearn-finance",'
                b'"symbol":"USDC","chain":"Ethereum","apy":8.5,'
                b'"tvlUsd":1e308,"pool":"u"}]}')
        with _patch_raw(body):
            tvl = _feed().fetch_tvl("yearn-finance", "USDC")
        _assert_tvl_bounded(self, tvl, "absurd-finite-tvl pin")
        self.assertIsNone(tvl)  # absurd → pool skipped entirely
        with _patch_raw(body):
            self.assertIsNone(_feed().get_tvl("yearn-finance", "USDC"))

    def test_pin_inf_tvl_never_returned(self):
        body = (b'{"status":"success","data":[{"project":"yearn-finance",'
                b'"symbol":"USDC","chain":"Ethereum","apy":8.5,'
                b'"tvlUsd":Infinity,"pool":"u"}]}')
        with _patch_raw(body):
            tvl = _feed().fetch_tvl("yearn-finance", "USDC")
        # Either rejected (None) or bounded — never inf.
        _assert_tvl_bounded(self, tvl, "inf-tvl pin")
        with _patch_raw(body):
            self.assertIsNone(_feed().get_tvl("yearn-finance", "USDC"))


# ─── Pendle _parse_market / _safe_float boundary (tvl:null → liquidity.usd) ───

class TestPendleParseFuzz(unittest.TestCase):
    N_CASES = 200

    def test_pin_safe_float_rejects_nan_inf(self):
        # _safe_float is the choke point for Pendle tvl/apy/liquidity. It must
        # never emit NaN/inf — those would propagate into allocation as a
        # silently-fabricated bound. fail-CLOSED → fallback (0.0 default).
        for bad in ["NaN", "nan", "inf", "-inf", "Infinity",
                    float("nan"), float("inf"), float("-inf"), "1e400"]:
            r = _pp._safe_float(bad)
            self.assertTrue(math.isfinite(r), f"_safe_float({bad!r}) -> {r!r} (NaN/inf leak)")

    def test_pin_tvl_null_falls_back_never_nan(self):
        # tvl:null → use liquidity.usd; result must be finite >= 0, never NaN.
        raw = {"address": "0xabc", "pt": {"symbol": "PT-sUSDe"},
               "underlyingAsset": {"symbol": "sUSDe"},
               "expiry": "2026-12-25T00:00:00.000Z",
               "liquidity": {"usd": 5_000_000.0}, "tvl": None,
               "impliedApy": 0.089, "underlyingInterestApy": 0.05}
        m = _pp._parse_market(raw)
        self.assertIsNotNone(m)
        self.assertTrue(math.isfinite(m.tvl_usd) and m.tvl_usd >= 0, m.tvl_usd)
        self.assertEqual(m.tvl_usd, 5_000_000.0)

    def test_pin_tvl_null_and_nan_liquidity_is_finite(self):
        raw = {"address": "0xabc", "pt": {"symbol": "PT-x"},
               "underlyingAsset": {"symbol": "x"},
               "expiry": "2026-12-25", "liquidity": {"usd": "NaN"},
               "tvl": None, "impliedApy": "Infinity",
               "underlyingInterestApy": 0.05}
        m = _pp._parse_market(raw)
        if m is not None:
            self.assertTrue(math.isfinite(m.tvl_usd), f"tvl NaN leak: {m.tvl_usd!r}")
            self.assertTrue(math.isfinite(m.liquidity_usd), f"liq NaN leak: {m.liquidity_usd!r}")
            self.assertTrue(math.isfinite(m.pt_apy), f"apy NaN leak: {m.pt_apy!r}")
            self.assertTrue(math.isfinite(m.implied_apy), f"implied NaN leak: {m.implied_apy!r}")

    def test_fuzz_pendle_parse_never_raises_finite_fields(self):
        rng = random.Random(0xBADBEEF)
        keys = ["address", "pt", "underlyingAsset", "expiry", "liquidity",
                "tvl", "impliedApy", "underlyingInterestApy", "isExpired", "chainId"]
        for i in range(self.N_CASES):
            raw = {}
            for k in keys:
                if rng.random() < 0.7:
                    if k in ("pt", "underlyingAsset"):
                        raw[k] = rng.choice([{"symbol": rng.choice(_UNICODE + ["USDC"])},
                                             None, "x", 5, {}])
                    elif k in ("liquidity", "tvl"):
                        raw[k] = rng.choice([{"usd": _rand_scalar(rng)},
                                             _rand_scalar(rng), None, {}])
                    elif k == "expiry":
                        raw[k] = rng.choice(["2026-12-25T00:00:00.000Z", "2026-12-25",
                                             "", "garbage", None, 5, "9999-99-99"])
                    else:
                        raw[k] = _rand_scalar(rng)
            ctx = f"[pendle case {i}] raw={raw!r}"
            try:
                m = _pp._parse_market(raw)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"_parse_market RAISED {type(exc).__name__}: {exc}  {ctx}")
            if m is not None:
                self.assertTrue(math.isfinite(m.tvl_usd), f"tvl NaN/inf: {m.tvl_usd!r} {ctx}")
                self.assertTrue(math.isfinite(m.liquidity_usd), f"liq NaN/inf: {m.liquidity_usd!r} {ctx}")
                self.assertTrue(math.isfinite(m.pt_apy), f"pt_apy NaN/inf: {m.pt_apy!r} {ctx}")
                self.assertTrue(math.isfinite(m.implied_apy), f"implied NaN/inf: {m.implied_apy!r} {ctx}")
                self.assertGreaterEqual(m.tvl_usd, 0.0, ctx)


if __name__ == "__main__":
    unittest.main(verbosity=2)
