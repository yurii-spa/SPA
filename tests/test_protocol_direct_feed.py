"""tests/test_protocol_direct_feed.py

Unit tests for spa_core.price_feeds.protocol_direct_feed (ADR-028 Phase 2).

Test groups
-----------
TestConstants             — module-level constants and registry (4 tests)
TestRayToApyPct           — _ray_to_apy_pct conversion helper (5 tests)
TestParsers               — _parse_aave / _parse_compound / _parse_morpho (8 tests)
TestHttpHelpers           — _http_get / _http_post_graphql internals (4 tests)
TestFetchApyDirect        — fetch_apy_direct: fallback / success / unknown (4 tests)
TestFetchAllDirect        — fetch_all_direct: keys, types, independence (3 tests)
TestMergeWithDefiLlama    — merge_with_defi_llama: consensus + divergence (6 tests)

Total: 34 tests
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.price_feeds.protocol_direct_feed import (
    # Constants
    DIVERGENCE_ALARM_BPS,
    APY_MIN_PCT,
    APY_MAX_PCT,
    RAY,
    SECONDS_PER_YEAR,
    T1_ADAPTERS,
    DIRECT_ENDPOINTS,
    # Parsers
    _ray_to_apy_pct,
    _parse_aave,
    _parse_compound,
    _parse_morpho,
    # HTTP helpers
    _http_get,
    _http_post_graphql,
    # Public API
    fetch_apy_direct,
    fetch_all_direct,
    merge_with_defi_llama,
)


# ── Fixtures / factories ──────────────────────────────────────────────────────

def _aave_response(liquidity_rate: str = "31709791983764585603") -> dict:
    """Minimal Aave V3 GraphQL response with one USDC reserve."""
    return {
        "data": {
            "reserves": [
                {"liquidityRate": liquidity_rate, "symbol": "USDC"}
            ]
        }
    }


def _compound_response(net_supply_apy: str = "0.0481") -> dict:
    """Minimal Compound V3 REST response (wrapped format)."""
    return {"market": {"net_supply_apy": net_supply_apy}}


def _morpho_response(supply_apy: float = 0.048) -> dict:
    """Minimal Morpho Blue GraphQL response with one market."""
    return {
        "data": {
            "markets": [
                {"state": {"supplyApy": supply_apy}, "inputToken": {"symbol": "USDC"}}
            ]
        }
    }


def _make_urlopen_cm(body: bytes):
    """Return a MagicMock context-manager that yields a response-like object."""
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ════════════════════════════════════════════════════════════════════════════
# 1. Constants
# ════════════════════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):

    def test_t1_adapters_contains_all_three(self):
        """T1_ADAPTERS must contain exactly aave_v3, compound_v3, morpho_blue."""
        self.assertIn("aave_v3", T1_ADAPTERS)
        self.assertIn("compound_v3", T1_ADAPTERS)
        self.assertIn("morpho_blue", T1_ADAPTERS)

    def test_direct_endpoints_registry_complete(self):
        """DIRECT_ENDPOINTS must have required fields for every adapter."""
        required_fields = {"url", "method", "parser", "fallback_apy"}
        for adapter_id, entry in DIRECT_ENDPOINTS.items():
            with self.subTest(adapter=adapter_id):
                for field in required_fields:
                    self.assertIn(field, entry, f"{adapter_id} missing field {field!r}")

    def test_divergence_alarm_bps_value(self):
        """DIVERGENCE_ALARM_BPS must equal 150."""
        self.assertEqual(DIVERGENCE_ALARM_BPS, 150)

    def test_fallback_apy_values_in_bounds(self):
        """Every fallback_apy must be within [APY_MIN_PCT, APY_MAX_PCT]."""
        for adapter_id, entry in DIRECT_ENDPOINTS.items():
            fallback = entry["fallback_apy"]
            with self.subTest(adapter=adapter_id):
                self.assertGreaterEqual(fallback, APY_MIN_PCT)
                self.assertLessEqual(fallback, APY_MAX_PCT)


# ════════════════════════════════════════════════════════════════════════════
# 2. RAY → APY conversion
# ════════════════════════════════════════════════════════════════════════════

class TestRayToApyPct(unittest.TestCase):

    def test_zero_rate_gives_zero_apy(self):
        """A rate of 0 should yield 0% APY (no earnings)."""
        apy = _ray_to_apy_pct("0")
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 0.0, places=6)

    def test_known_rate_approx_4pct(self):
        """A rate corresponding to ~4% APY should parse close to 4%."""
        # per_second = log(1.04) / SECONDS_PER_YEAR
        per_second = math.log(1.04) / SECONDS_PER_YEAR
        ray_rate = int(per_second * RAY)
        apy = _ray_to_apy_pct(str(ray_rate))
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 4.0, delta=0.05)

    def test_accepts_int_input(self):
        """_ray_to_apy_pct should accept integer inputs (not just strings)."""
        apy = _ray_to_apy_pct(0)
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 0.0, places=6)

    def test_negative_rate_returns_none(self):
        """Negative liquidityRate is invalid → returns None."""
        result = _ray_to_apy_pct(-1e18)
        self.assertIsNone(result)

    def test_non_numeric_returns_none(self):
        """Non-numeric string → returns None, does not raise."""
        result = _ray_to_apy_pct("not-a-number")
        self.assertIsNone(result)


# ════════════════════════════════════════════════════════════════════════════
# 3. Parsers
# ════════════════════════════════════════════════════════════════════════════

class TestParsers(unittest.TestCase):

    # ── _parse_aave ──────────────────────────────────────────────────────────

    def test_parse_aave_valid_response(self):
        """_parse_aave should return a float for a well-formed Aave response."""
        # liquidityRate ~ 3% APY: rate_per_sec = log(1.03)/SECONDS_PER_YEAR
        per_second = math.log(1.03) / SECONDS_PER_YEAR
        ray_rate = int(per_second * RAY)
        payload = _aave_response(liquidity_rate=str(ray_rate))
        apy = _parse_aave(payload)
        self.assertIsNotNone(apy)
        self.assertIsInstance(apy, float)
        self.assertAlmostEqual(apy, 3.0, delta=0.1)

    def test_parse_aave_empty_reserves(self):
        """Empty reserves list → _parse_aave returns None."""
        payload = {"data": {"reserves": []}}
        self.assertIsNone(_parse_aave(payload))

    def test_parse_aave_missing_data_key(self):
        """Missing 'data' key → _parse_aave returns None gracefully."""
        self.assertIsNone(_parse_aave({}))

    def test_parse_aave_missing_liquidity_rate(self):
        """Reserve entry without liquidityRate → _parse_aave returns None."""
        payload = {"data": {"reserves": [{"symbol": "USDC"}]}}
        self.assertIsNone(_parse_aave(payload))

    # ── _parse_compound ──────────────────────────────────────────────────────

    def test_parse_compound_decimal_fraction(self):
        """net_supply_apy=0.048 (decimal fraction) → returns 4.8%."""
        payload = _compound_response("0.048")
        apy = _parse_compound(payload)
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 4.8, places=4)

    def test_parse_compound_flat_response(self):
        """Flat (unwrapped) Compound response shape is also supported."""
        payload = {"net_supply_apy": "0.050"}
        apy = _parse_compound(payload)
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 5.0, places=4)

    def test_parse_compound_missing_field(self):
        """Response without net_supply_apy → _parse_compound returns None."""
        self.assertIsNone(_parse_compound({"market": {"other_field": 1}}))

    # ── _parse_morpho ────────────────────────────────────────────────────────

    def test_parse_morpho_valid_response(self):
        """_parse_morpho should return float for well-formed Morpho response."""
        payload = _morpho_response(supply_apy=0.052)
        apy = _parse_morpho(payload)
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 5.2, places=4)

    def test_parse_morpho_empty_markets(self):
        """Empty markets list → _parse_morpho returns None."""
        payload = {"data": {"markets": []}}
        self.assertIsNone(_parse_morpho(payload))


# ════════════════════════════════════════════════════════════════════════════
# 4. HTTP helpers
# ════════════════════════════════════════════════════════════════════════════

class TestHttpHelpers(unittest.TestCase):

    def test_http_get_success(self):
        """_http_get returns parsed dict when urlopen succeeds."""
        body = json.dumps({"net_supply_apy": "0.048"}).encode()
        cm = _make_urlopen_cm(body)
        with patch("urllib.request.urlopen", return_value=cm):
            result = _http_get("https://example.com", timeout=5)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["net_supply_apy"], "0.048")

    def test_http_get_url_error_returns_none(self):
        """_http_get returns None on URLError — does not raise."""
        with patch("urllib.request.urlopen", side_effect=URLError("timeout")):
            result = _http_get("https://example.com", timeout=5)
        self.assertIsNone(result)

    def test_http_post_graphql_success(self):
        """_http_post_graphql returns parsed dict when POST succeeds."""
        body = json.dumps(_aave_response("12345678901234567890")).encode()
        cm = _make_urlopen_cm(body)
        with patch("urllib.request.urlopen", return_value=cm):
            result = _http_post_graphql("https://example.com/graphql", "{}", timeout=5)
        self.assertIsInstance(result, dict)
        self.assertIn("data", result)

    def test_http_post_graphql_url_error_returns_none(self):
        """_http_post_graphql returns None on URLError — does not raise."""
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            result = _http_post_graphql("https://example.com/graphql", "{}", timeout=5)
        self.assertIsNone(result)


# ════════════════════════════════════════════════════════════════════════════
# 5. fetch_apy_direct
# ════════════════════════════════════════════════════════════════════════════

class TestFetchApyDirect(unittest.TestCase):

    def test_fetch_returns_float(self):
        """fetch_apy_direct always returns a float."""
        # Mock network failure → fallback
        with patch("urllib.request.urlopen", side_effect=URLError("err")):
            result = fetch_apy_direct("aave_v3")
        self.assertIsInstance(result, float)

    def test_fallback_on_network_error(self):
        """On URLError, fetch_apy_direct returns the configured fallback_apy."""
        fallback = DIRECT_ENDPOINTS["aave_v3"]["fallback_apy"]
        with patch("urllib.request.urlopen", side_effect=URLError("network unreachable")):
            apy = fetch_apy_direct("aave_v3")
        self.assertEqual(apy, fallback)

    def test_fallback_on_compound_network_error(self):
        """Compound V3 adapter also returns fallback on network error."""
        fallback = DIRECT_ENDPOINTS["compound_v3"]["fallback_apy"]
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            apy = fetch_apy_direct("compound_v3")
        self.assertEqual(apy, fallback)

    def test_fallback_on_morpho_network_error(self):
        """Morpho Blue adapter also returns fallback on network error."""
        fallback = DIRECT_ENDPOINTS["morpho_blue"]["fallback_apy"]
        with patch("urllib.request.urlopen", side_effect=URLError("timeout")):
            apy = fetch_apy_direct("morpho_blue")
        self.assertEqual(apy, fallback)

    def test_unknown_adapter_returns_zero(self):
        """Unknown adapter_id returns 0.0 — does not raise."""
        result = fetch_apy_direct("unknown_protocol_xyz")
        self.assertEqual(result, 0.0)

    def test_success_aave_direct(self):
        """fetch_apy_direct("aave_v3") returns parsed APY when endpoint works."""
        # ~3% APY rate in RAY
        per_second = math.log(1.03) / SECONDS_PER_YEAR
        ray_rate = int(per_second * RAY)
        payload = _aave_response(liquidity_rate=str(ray_rate))
        body = json.dumps(payload).encode()
        cm = _make_urlopen_cm(body)
        with patch("urllib.request.urlopen", return_value=cm):
            apy = fetch_apy_direct("aave_v3")
        self.assertIsInstance(apy, float)
        self.assertAlmostEqual(apy, 3.0, delta=0.1)

    def test_success_compound_direct(self):
        """fetch_apy_direct("compound_v3") returns parsed APY when endpoint works."""
        payload = _compound_response("0.048")
        body = json.dumps(payload).encode()
        cm = _make_urlopen_cm(body)
        with patch("urllib.request.urlopen", return_value=cm):
            apy = fetch_apy_direct("compound_v3")
        self.assertIsInstance(apy, float)
        self.assertAlmostEqual(apy, 4.8, places=3)

    def test_success_morpho_direct(self):
        """fetch_apy_direct("morpho_blue") returns parsed APY when endpoint works."""
        payload = _morpho_response(supply_apy=0.058)
        body = json.dumps(payload).encode()
        cm = _make_urlopen_cm(body)
        with patch("urllib.request.urlopen", return_value=cm):
            apy = fetch_apy_direct("morpho_blue")
        self.assertIsInstance(apy, float)
        self.assertAlmostEqual(apy, 5.8, places=3)


# ════════════════════════════════════════════════════════════════════════════
# 6. fetch_all_direct
# ════════════════════════════════════════════════════════════════════════════

class TestFetchAllDirect(unittest.TestCase):

    def test_fetch_all_direct_keys(self):
        """fetch_all_direct must return all 3 T1 adapter keys."""
        with patch("urllib.request.urlopen", side_effect=URLError("offline")):
            result = fetch_all_direct()
        self.assertIn("aave_v3", result)
        self.assertIn("compound_v3", result)
        self.assertIn("morpho_blue", result)

    def test_fetch_all_direct_returns_dict(self):
        """fetch_all_direct returns a dict."""
        with patch("urllib.request.urlopen", side_effect=URLError("offline")):
            result = fetch_all_direct()
        self.assertIsInstance(result, dict)

    def test_all_values_are_floats(self):
        """Every value in the fetch_all_direct result must be a float."""
        with patch("urllib.request.urlopen", side_effect=URLError("offline")):
            result = fetch_all_direct()
        for adapter_id, apy in result.items():
            with self.subTest(adapter=adapter_id):
                self.assertIsInstance(apy, float)

    def test_fetch_all_direct_fallbacks_on_network_error(self):
        """With network down, fetch_all_direct returns configured fallback values."""
        with patch("urllib.request.urlopen", side_effect=URLError("no network")):
            result = fetch_all_direct()
        for adapter_id in T1_ADAPTERS:
            expected = DIRECT_ENDPOINTS[adapter_id]["fallback_apy"]
            self.assertEqual(
                result[adapter_id], expected,
                f"{adapter_id}: expected fallback {expected}, got {result[adapter_id]}"
            )

    def test_fetch_all_direct_does_not_raise(self):
        """fetch_all_direct must not propagate any exception."""
        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            try:
                result = fetch_all_direct()
            except Exception as exc:  # noqa: BLE001
                self.fail(f"fetch_all_direct raised an exception: {exc}")
        self.assertIsInstance(result, dict)


# ════════════════════════════════════════════════════════════════════════════
# 7. merge_with_defi_llama
# ════════════════════════════════════════════════════════════════════════════

class TestMergeWithDefiLlama(unittest.TestCase):

    def _make_direct(self, aave=3.5, compound=4.0, morpho=4.8):
        return {
            "aave_v3": aave,
            "compound_v3": compound,
            "morpho_blue": morpho,
        }

    def _make_llama(self, aave=3.5, compound=4.0, morpho=4.8):
        return {
            "aave_v3": aave,
            "compound_v3": compound,
            "morpho_blue": morpho,
            "yearn_v3": 5.5,   # Tier 2 only adapter
            "euler_v2": 5.2,
        }

    def test_merge_consensus_direct_wins(self):
        """Direct (Tier 1) value must override DeFiLlama (Tier 2) for T1 keys."""
        direct = self._make_direct(aave=3.8)
        llama = self._make_llama(aave=3.5)
        merged = merge_with_defi_llama(direct, llama)
        self.assertAlmostEqual(merged["aave_v3"], 3.8, places=6)

    def test_merge_llama_only_keys_preserved(self):
        """Keys only in llama (not in direct) must survive in the merged result."""
        direct = self._make_direct()
        llama = self._make_llama()
        merged = merge_with_defi_llama(direct, llama)
        self.assertIn("yearn_v3", merged)
        self.assertAlmostEqual(merged["yearn_v3"], 5.5, places=6)
        self.assertIn("euler_v2", merged)

    def test_merge_no_divergence_no_warning(self):
        """No WARNING emitted when sources agree (delta < 150 bps)."""
        direct = self._make_direct(aave=3.5)
        llama = self._make_llama(aave=3.51)   # delta = 1 bps
        with self.assertLogs("spa_core.price_feeds.protocol_direct_feed", level="WARNING") as cm:
            # Force at least one log line so assertLogs doesn't fail on empty
            import logging as _lg
            _lg.getLogger("spa_core.price_feeds.protocol_direct_feed").warning("__probe__")
            merge_with_defi_llama(direct, llama)
        # Only the probe warning should appear; no DIVERGENCE ALARM
        alarm_logs = [l for l in cm.output if "DIVERGENCE ALARM" in l]
        self.assertEqual(len(alarm_logs), 0, f"Unexpected divergence alarm: {alarm_logs}")

    def test_merge_alarm_on_divergence_over_150_bps(self):
        """WARNING logged when |direct - llama| > 150 bps."""
        # delta = 2% = 200 bps → should trigger alarm
        direct = self._make_direct(aave=5.5)
        llama = self._make_llama(aave=3.5)   # 5.5 - 3.5 = 2.0% = 200 bps
        with self.assertLogs("spa_core.price_feeds.protocol_direct_feed", level="WARNING") as cm:
            merge_with_defi_llama(direct, llama)
        alarm_logs = [l for l in cm.output if "DIVERGENCE ALARM" in l and "aave_v3" in l]
        self.assertGreater(len(alarm_logs), 0, "Expected DIVERGENCE ALARM log not found")

    def test_merge_alarm_threshold_exactly_150_bps_no_alarm(self):
        """Exactly 150 bps delta should NOT trigger alarm (threshold is strictly >)."""
        direct = self._make_direct(aave=5.0)
        llama = self._make_llama(aave=3.5)   # 5.0 - 3.5 = 1.5% = 150 bps exactly
        with self.assertLogs("spa_core.price_feeds.protocol_direct_feed", level="WARNING") as cm:
            _lg = __import__("logging")
            _lg.getLogger("spa_core.price_feeds.protocol_direct_feed").warning("__probe__")
            merge_with_defi_llama(direct, llama)
        alarm_logs = [l for l in cm.output if "DIVERGENCE ALARM" in l]
        self.assertEqual(len(alarm_logs), 0, f"Unexpected alarm at exactly 150 bps: {alarm_logs}")

    def test_merge_alarm_at_151_bps(self):
        """151 bps delta MUST trigger alarm."""
        direct = self._make_direct(aave=3.5 + 1.51)   # +1.51% = 151 bps
        llama = self._make_llama(aave=3.5)
        with self.assertLogs("spa_core.price_feeds.protocol_direct_feed", level="WARNING") as cm:
            merge_with_defi_llama(direct, llama)
        alarm_logs = [l for l in cm.output if "DIVERGENCE ALARM" in l and "aave_v3" in l]
        self.assertGreater(len(alarm_logs), 0, "Expected DIVERGENCE ALARM at 151 bps")

    def test_merge_returns_dict(self):
        """merge_with_defi_llama always returns a dict."""
        result = merge_with_defi_llama({}, {})
        self.assertIsInstance(result, dict)

    def test_merge_does_not_raise_on_bad_input(self):
        """merge_with_defi_llama must not raise on unusual inputs."""
        try:
            merge_with_defi_llama({}, {})
            merge_with_defi_llama({"aave_v3": 3.5}, {})
            merge_with_defi_llama({}, {"aave_v3": 3.5})
        except Exception as exc:  # noqa: BLE001
            self.fail(f"merge_with_defi_llama raised: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
