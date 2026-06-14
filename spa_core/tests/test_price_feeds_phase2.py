"""
Phase 2 tests for PriceFeedFetcher — live Chainlink RPC integration.

Deterministic, network-free. Every test that activates live mode patches
``urllib.request.urlopen`` so no real HTTP call is made. Confirms:

  * _strip_fragment_with_hint: extracts (clean_url, hint) for known
    provider hints and returns (url, None) when no fragment is present.
  * _eth_call helper: payload shape, hex result extraction, timeout
    propagation, RPC error envelope handling.
  * _decode_chainlink_answer: 8-decimal scaling, two's-complement int256,
    too-short hex raises.
  * Live _fetch_price_rpc:
      - chainlink: → real eth_call + decode round-trip
      - zero-address chainlink placeholder → short-circuit None
      - non-chainlink hint (pyth/redstone) → None (deferred)
      - RPC exception → [FALLBACK] WARNING + None (next endpoint tries)
      - dry_run=True path still returns None (backwards compat with Phase 1)
  * fetch_prices(use_synthetic=False) integration with all endpoints
    mocked: Chainlink succeeds → real price returned for that coin; all
    endpoints fail → synthetic backup for that coin.

Run from repo root::

    python -m pytest spa_core/tests/test_price_feeds_phase2.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is on the path (mirrors test_price_feeds.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_pipeline.price_feeds import PriceFeedFetcher  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _fake_urlopen_response(payload: dict) -> MagicMock:
    """Build a context-manager mock mimicking urllib.request.urlopen()."""
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def _build_latest_answer_hex(raw: int) -> str:
    """int256 → 32-byte two's-complement hex string with 0x prefix."""
    if raw < 0:
        raw = (1 << 256) + raw  # two's complement
    return "0x" + format(raw, "064x")


# ─── TestStripFragment ────────────────────────────────────────────────────────


class TestStripFragment:
    """_strip_fragment_with_hint extracts (clean_url, hint)."""

    def test_chainlink_hint_extracted(self):
        url = (
            "https://eth.llamarpc.com#chainlink:"
            "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"
        )
        clean, hint = PriceFeedFetcher._strip_fragment_with_hint(url)
        assert clean == "https://eth.llamarpc.com"
        assert hint == (
            "chainlink:0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"
        )

    def test_no_fragment_returns_none_hint(self):
        url = "https://hermes.pyth.network/api/latest_price_feeds?ids[]=USDC"
        clean, hint = PriceFeedFetcher._strip_fragment_with_hint(url)
        assert clean == url
        assert hint is None

    def test_query_string_preserved(self):
        url = "https://api.redstone.finance/prices?symbol=USDC#redstone:foo"
        clean, hint = PriceFeedFetcher._strip_fragment_with_hint(url)
        assert clean == "https://api.redstone.finance/prices?symbol=USDC"
        assert hint == "redstone:foo"


# ─── TestEthCallHelper ────────────────────────────────────────────────────────


class TestEthCallHelper:
    """Direct unit tests for PriceFeedFetcher._eth_call (stdlib-only)."""

    def test_payload_shape_and_hex_extraction(self):
        """_eth_call posts a well-formed JSON-RPC body and returns 0x hex."""
        fetcher = PriceFeedFetcher(dry_run=False)
        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.header_items())
            return _fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1, "result": "0xdeadbeef"}
            )

        with patch(
            "data_pipeline.price_feeds.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            out = fetcher._eth_call(
                "https://example.com/rpc",
                to="0xabc",
                data="0x50d25bcd",
            )

        assert out == "0xdeadbeef"
        assert captured["url"] == "https://example.com/rpc"
        assert captured["timeout"] == PriceFeedFetcher.RPC_TIMEOUT_SECONDS
        body = captured["body"]
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "eth_call"
        assert body["params"][0]["to"] == "0xabc"
        assert body["params"][0]["data"] == "0x50d25bcd"
        assert body["params"][1] == "latest"
        # urllib header keys are title-cased.
        assert captured["headers"].get("Content-type") == "application/json"

    def test_rpc_error_envelope_raises(self):
        """JSON-RPC `error` field surfaces as RuntimeError."""
        fetcher = PriceFeedFetcher(dry_run=False)
        with patch(
            "data_pipeline.price_feeds.urllib.request.urlopen",
            return_value=_fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1,
                 "error": {"code": -32000, "message": "bad"}}
            ),
        ):
            with pytest.raises(RuntimeError, match="RPC error"):
                fetcher._eth_call("https://x", "0xabc", "0x50d25bcd")

    def test_timeout_raises_runtimeerror(self):
        """urllib OSError/TimeoutError gets wrapped into RuntimeError."""
        fetcher = PriceFeedFetcher(dry_run=False)

        def boom(req, timeout=None):
            raise TimeoutError("simulated")

        with patch(
            "data_pipeline.price_feeds.urllib.request.urlopen",
            side_effect=boom,
        ):
            with pytest.raises(RuntimeError, match="HTTP failure"):
                fetcher._eth_call("https://x", "0xabc", "0x50d25bcd")

    def test_missing_result_field_raises(self):
        """`result` absent / not 0x-prefixed → RuntimeError."""
        fetcher = PriceFeedFetcher(dry_run=False)
        with patch(
            "data_pipeline.price_feeds.urllib.request.urlopen",
            return_value=_fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1, "result": "garbage"}
            ),
        ):
            with pytest.raises(RuntimeError, match="missing/invalid result"):
                fetcher._eth_call("https://x", "0xabc", "0x50d25bcd")


# ─── TestDecodeChainlinkAnswer ────────────────────────────────────────────────


class TestDecodeChainlinkAnswer:
    """latestAnswer() int256 → float decoding."""

    def test_dollar_one_at_8_decimals(self):
        """100_000_000 raw (= 1.00 * 1e8) → 1.0."""
        hex_str = _build_latest_answer_hex(100_000_000)
        out = PriceFeedFetcher._decode_chainlink_answer(hex_str, decimals=8)
        assert out == pytest.approx(1.0, abs=1e-9)

    def test_minor_depeg(self):
        """99_500_000 raw → 0.995."""
        hex_str = _build_latest_answer_hex(99_500_000)
        out = PriceFeedFetcher._decode_chainlink_answer(hex_str, decimals=8)
        assert out == pytest.approx(0.995, abs=1e-9)

    def test_negative_answer_twos_complement(self):
        """Chainlink answers are int256 — negative values must decode."""
        hex_str = _build_latest_answer_hex(-12345)
        out = PriceFeedFetcher._decode_chainlink_answer(hex_str, decimals=8)
        assert out == pytest.approx(-12345 / 1e8, abs=1e-12)

    def test_too_short_hex_raises(self):
        with pytest.raises(RuntimeError, match="too short"):
            PriceFeedFetcher._decode_chainlink_answer("0xdead", decimals=8)


# ─── TestFetchPriceRpcLive ────────────────────────────────────────────────────


class TestFetchPriceRpcLive:
    """_fetch_price_rpc dispatch in live mode."""

    CHAINLINK_URL = (
        "https://eth.llamarpc.com#chainlink:"
        "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"
    )

    def test_dry_run_returns_none(self):
        """Backwards compat: dry_run=True short-circuits to None."""
        fetcher = PriceFeedFetcher(dry_run=True)
        out = fetcher._fetch_price_rpc("USDC", self.CHAINLINK_URL)
        assert out is None

    def test_chainlink_round_trip(self):
        """chainlink hint → eth_call + decode → returns price near $1."""
        fetcher = PriceFeedFetcher(dry_run=False)
        hex_answer = _build_latest_answer_hex(100_010_000)  # $1.0001

        captured: dict = {}

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            captured["url"] = rpc_url
            captured["to"] = to
            captured["data"] = data
            return hex_answer

        with patch.object(PriceFeedFetcher, "_eth_call", new=fake_eth_call):
            price = fetcher._fetch_price_rpc("USDC", self.CHAINLINK_URL)

        assert price == pytest.approx(1.0001, abs=1e-9)
        # The URL must be passed WITHOUT the fragment.
        assert captured["url"] == "https://eth.llamarpc.com"
        # The contract address must be the Chainlink feed from the fragment.
        assert (
            captured["to"]
            == "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"
        )
        # The calldata must be exactly the latestAnswer() selector.
        assert captured["data"] == PriceFeedFetcher.SELECTOR_LATEST_ANSWER

    def test_zero_address_chainlink_skipped(self):
        """USDS placeholder (zero-address feed) → None without an RPC call."""
        fetcher = PriceFeedFetcher(dry_run=False)
        usds_url = (
            "https://eth.llamarpc.com#chainlink:"
            "0x0000000000000000000000000000000000000000"
        )

        def boom(self, rpc_url, to, data):  # noqa: ARG001
            raise AssertionError("eth_call must not be invoked for zero addr")

        with patch.object(PriceFeedFetcher, "_eth_call", new=boom):
            out = fetcher._fetch_price_rpc("USDS", usds_url)
        assert out is None

    def test_non_chainlink_hint_returns_none(self):
        """Pyth / RedStone gateways are deferred → return None."""
        fetcher = PriceFeedFetcher(dry_run=False)
        pyth_url = (
            "https://hermes.pyth.network/api/latest_price_feeds?ids[]=USDC"
        )
        # No fragment at all on the Pyth URL → hint is None → returns None.
        assert fetcher._fetch_price_rpc("USDC", pyth_url) is None

    def test_rpc_exception_falls_back_to_none(self, caplog):
        """eth_call exception → [FALLBACK] WARNING + None (next URL tries)."""
        fetcher = PriceFeedFetcher(dry_run=False)

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            raise RuntimeError("simulated RPC outage")

        import logging as _logging
        with caplog.at_level(_logging.WARNING, logger="spa.price_feeds"):
            with patch.object(
                PriceFeedFetcher, "_eth_call", new=fake_eth_call,
            ):
                out = fetcher._fetch_price_rpc("USDC", self.CHAINLINK_URL)
        assert out is None
        # The [FALLBACK] WARNING must have been emitted.
        assert any("[FALLBACK]" in rec.getMessage() for rec in caplog.records)

    def test_insane_decoded_price_falls_back(self):
        """If decode yields out-of-band ($1e6) → sanity gate → None."""
        fetcher = PriceFeedFetcher(dry_run=False)
        # Decode would return ~99999.99 — sanity gate (>1000) → reject.
        hex_answer = _build_latest_answer_hex(10_000_000_000_000)

        with patch.object(
            PriceFeedFetcher, "_eth_call", return_value=hex_answer,
        ):
            out = fetcher._fetch_price_rpc("USDC", self.CHAINLINK_URL)
        assert out is None


# ─── TestFetchPricesIntegration ───────────────────────────────────────────────


class TestFetchPricesIntegration:
    """fetch_prices(use_synthetic=False) end-to-end with mocked endpoints."""

    def test_chainlink_success_populates_all_coins(self):
        """All four coins resolve via the [0] Chainlink endpoint."""
        fetcher = PriceFeedFetcher(dry_run=False)
        seen: dict[str, list[str]] = {}

        def fake_fetch_rpc(self, symbol, rpc_url, timeout=5):  # noqa: ARG001
            seen.setdefault(symbol, []).append(rpc_url)
            # Coin-specific deterministic prices.
            return {
                "USDC": 1.0001,
                "USDT": 0.9998,
                "DAI": 1.0003,
                "USDS": 0.9999,
            }[symbol]

        with patch.object(
            PriceFeedFetcher, "_fetch_price_rpc", new=fake_fetch_rpc,
        ):
            prices = fetcher.fetch_prices(use_synthetic=False)

        assert set(prices.keys()) == set(PriceFeedFetcher.STABLECOINS)
        assert prices["USDC"] == pytest.approx(1.0001)
        assert prices["USDT"] == pytest.approx(0.9998)
        assert prices["DAI"] == pytest.approx(1.0003)
        assert prices["USDS"] == pytest.approx(0.9999)
        # First endpoint succeeded → exactly one call per coin.
        for sym in PriceFeedFetcher.STABLECOINS:
            assert len(seen[sym]) == 1

    def test_all_endpoints_fail_falls_back_to_synthetic(self):
        """If every endpoint returns None for every coin → synthetic prices."""
        fetcher = PriceFeedFetcher(dry_run=False)

        def fake_fetch_rpc(self, symbol, rpc_url, timeout=5):  # noqa: ARG001
            return None

        with patch.object(
            PriceFeedFetcher, "_fetch_price_rpc", new=fake_fetch_rpc,
        ):
            prices = fetcher.fetch_prices(use_synthetic=False)

        # Synthetic backup is deterministic — same seed → same dict.
        expected = fetcher.fetch_prices_synthetic()
        assert prices == expected

    def test_first_endpoint_succeeds_second_not_called(self):
        """When [0] returns a price, [1] and [2] must not be tried."""
        fetcher = PriceFeedFetcher(dry_run=False)
        call_counts: dict[str, int] = {}

        def fake_fetch_rpc(self, symbol, rpc_url, timeout=5):  # noqa: ARG001
            call_counts[symbol] = call_counts.get(symbol, 0) + 1
            # Succeed only for the first call.
            if call_counts[symbol] == 1:
                return 1.0
            return None

        with patch.object(
            PriceFeedFetcher, "_fetch_price_rpc", new=fake_fetch_rpc,
        ):
            prices = fetcher.fetch_prices(use_synthetic=False)

        for sym in PriceFeedFetcher.STABLECOINS:
            assert prices[sym] == pytest.approx(1.0)
            # Confirm short-circuit — only 1 call, not 3.
            assert call_counts[sym] == 1


# ─── TestBackwardsCompat ──────────────────────────────────────────────────────


class TestBackwardsCompat:
    """Phase 1 callers (no dry_run kw) must still work byte-identically."""

    def test_default_constructor_is_dry_run_true(self):
        fetcher = PriceFeedFetcher()
        assert fetcher.dry_run is True

    def test_default_constructor_fetch_falls_back_to_synthetic(self):
        """fetch_prices(use_synthetic=False) on default fetcher → synthetic."""
        fetcher = PriceFeedFetcher()  # dry_run=True
        prices = fetcher.fetch_prices(use_synthetic=False)
        expected = fetcher.fetch_prices_synthetic()
        assert prices == expected
