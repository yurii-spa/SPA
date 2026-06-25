"""
Phase 2 tests for CompoundV3Adapter — live on-chain RPC integration.

Deterministic, network-free. Every test patches ``urllib.request.urlopen``
(or _call_with_fallback) so no real HTTP call is made. Confirms:

  * _eth_call helper: URL fragment stripping, payload shape, hex result
    extraction, timeout, error envelope.
  * _call_with_fallback routing: first failure → second succeeds, all-fail
    raises, fragment stripped from each URL.
  * Live get_supply_apy: known per-second rate → APY decode, bad asset →
    ValueError, RPC failure → mock fallback (no exception), unsupported
    chain raises in __init__.
  * Live get_supply_balance: balanceOf round-trip with 6-decimal USDC
    scaling, missing wallet env var → fallback, RPC failure → fallback.

Mirrors test_aave_v3_adapter_phase2.py 1:1 for the Compound topology
(single-Comet, balanceOf directly, getUtilization+getSupplyRate chained).

Run from repo root::

    python -m pytest spa_core/tests/test_compound_v3_adapter_phase2.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is on the path (mirrors test_compound_v3_adapter.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.compound_v3_adapter import CompoundV3Adapter  # noqa: E402
from spa_core.utils.errors import SourceError  # noqa: E402


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


def _uint256_hex(value: int) -> str:
    """uint256 → 32-byte hex string with 0x prefix."""
    return "0x" + format(value, "064x")


# ─── TestEthCallHelper ────────────────────────────────────────────────────────


class TestEthCallHelper:
    """Direct unit tests for CompoundV3Adapter._eth_call (stdlib-only)."""

    def test_strip_fragment_removes_compound_hint(self):
        url = (
            "https://eth.llamarpc.com#compound-v3-comet:"
            "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        )
        assert (
            CompoundV3Adapter._strip_fragment(url)
            == "https://eth.llamarpc.com"
        )
        # No fragment → unchanged.
        assert (
            CompoundV3Adapter._strip_fragment("https://example.com/rpc")
            == "https://example.com/rpc"
        )

    def test_payload_shape_and_hex_extraction(self):
        """_eth_call posts a well-formed JSON-RPC body and returns 0x hex."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        captured: dict = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["headers"] = dict(req.header_items())
            return _fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1, "result": "0xfeedface"}
            )

        with patch(
            "execution.compound_v3_adapter.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            out = adapter._eth_call(
                "https://example.com/rpc",
                to="0xabc",
                data="0x6f307dc3",
            )

        assert out == "0xfeedface"
        assert captured["url"] == "https://example.com/rpc"
        # 5-second timeout is the documented constant.
        assert captured["timeout"] == CompoundV3Adapter.RPC_TIMEOUT_SECONDS
        body = captured["body"]
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "eth_call"
        assert body["params"][0]["to"] == "0xabc"
        assert body["params"][0]["data"] == "0x6f307dc3"
        assert body["params"][1] == "latest"
        # Content-Type set so JSON-RPC servers accept the body.
        assert captured["headers"].get("Content-type") == "application/json"

    def test_rpc_error_envelope_raises(self):
        """JSON-RPC `error` field surfaces as SourceError."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with patch(
            "execution.compound_v3_adapter.urllib.request.urlopen",
            return_value=_fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1,
                 "error": {"code": -32000, "message": "bad"}}
            ),
        ):
            with pytest.raises(SourceError, match="RPC error"):
                adapter._eth_call("https://x", "0xabc", "0x6f307dc3")

    def test_timeout_raises_runtimeerror(self):
        """urllib OSError/TimeoutError gets wrapped into SourceError."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)

        def boom(req, timeout=None):
            raise TimeoutError("simulated")

        with patch(
            "execution.compound_v3_adapter.urllib.request.urlopen",
            side_effect=boom,
        ):
            with pytest.raises(SourceError, match="HTTP failure"):
                adapter._eth_call("https://x", "0xabc", "0x6f307dc3")


# ─── TestFallbackRouting ──────────────────────────────────────────────────────


class TestFallbackRouting:
    """_call_with_fallback iterates endpoints and strips fragments."""

    def test_first_fails_second_succeeds(self):
        """RuntimeError on endpoint #1 must fall through to endpoint #2."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        calls = {"n": 0}
        good = _uint256_hex(42)

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("endpoint #1 down")
            return good

        with patch.object(
            CompoundV3Adapter, "_eth_call", new=fake_eth_call,
        ):
            out = adapter._call_with_fallback(
                "USDC", CompoundV3Adapter.SELECTOR_GET_UTILIZATION,
            )
        assert out == good
        assert calls["n"] == 2

    def test_all_endpoints_fail_raises(self):
        """If every endpoint raises, _call_with_fallback escalates."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)

        def always_fail(self, rpc_url, to, data):  # noqa: ARG001
            raise SourceError("eth_call", f"down: {rpc_url}")

        with patch.object(CompoundV3Adapter, "_eth_call", new=always_fail):
            with pytest.raises(SourceError, match="all 3 RPCs failed"):
                adapter._call_with_fallback(
                    "USDC", CompoundV3Adapter.SELECTOR_GET_UTILIZATION,
                )

    def test_fragment_stripped_from_every_endpoint(self):
        """Each candidate URL must be passed to _eth_call WITHOUT #fragment."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        seen_urls: list[str] = []

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            seen_urls.append(rpc_url)
            raise SourceError("eth_call", "never mind")

        with patch.object(CompoundV3Adapter, "_eth_call", new=fake_eth_call):
            with pytest.raises(SourceError):
                adapter._call_with_fallback(
                    "USDC", CompoundV3Adapter.SELECTOR_GET_UTILIZATION,
                )

        # All three Ethereum endpoints attempted, none retaining their #...
        assert len(seen_urls) == 3
        for url in seen_urls:
            assert "#" not in url
            assert "compound-v3-comet" not in url


# ─── TestGetSupplyApyLive ─────────────────────────────────────────────────────


class TestGetSupplyApyLive:
    """Live get_supply_apy: real per-second-rate decoding + fallback."""

    def test_known_per_second_rate_decodes_to_5pct(self):
        """A per-second rate that annualises to 5.0% must decode to 5.0.

        Target APY = 5.0% → rate_per_second (1e18-scaled) =
            (5.0 / 100) * 1e18 / 31_536_000
            ≈ 1_585_489_599
        """
        target_apy_pct = 5.0
        rate_per_second = int(
            target_apy_pct / 100 * 1e18 / CompoundV3Adapter.SECONDS_PER_YEAR
        )
        util_hex = _uint256_hex(int(0.85 * 1e18))  # 85% utilization
        rate_hex = _uint256_hex(rate_per_second)

        # Sequence: (1) getUtilization, (2) getSupplyRate(utilization).
        calls: list[str] = []

        def fake_call_with_fallback(self, asset, data):  # noqa: ARG001
            calls.append(data)
            if data == CompoundV3Adapter.SELECTOR_GET_UTILIZATION:
                return util_hex
            # getSupplyRate(utilization) starts with the rate selector.
            if data.startswith(CompoundV3Adapter.SELECTOR_GET_SUPPLY_RATE):
                # Caller must have padded utilization into 32 bytes.
                expected_arg = format(int(0.85 * 1e18), "064x")
                assert data.endswith(expected_arg), (
                    f"getSupplyRate calldata missing utilization arg: {data}"
                )
                return rate_hex
            raise AssertionError(f"Unexpected calldata: {data}")

        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            CompoundV3Adapter,
            "_call_with_fallback",
            new=fake_call_with_fallback,
        ):
            apy = adapter.get_supply_apy("USDC")

        # Allow tiny int-truncation noise from the rate_per_second conversion.
        assert apy == pytest.approx(target_apy_pct, abs=1e-6)
        # Confirm both expected calls were dispatched in the right order.
        assert calls[0] == CompoundV3Adapter.SELECTOR_GET_UTILIZATION
        assert calls[1].startswith(CompoundV3Adapter.SELECTOR_GET_SUPPLY_RATE)

    def test_bad_asset_raises_valueerror(self):
        """Unknown asset must raise BEFORE any RPC work — not be swallowed."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with pytest.raises(ValueError):
            adapter.get_supply_apy("USDT")
        with pytest.raises(ValueError):
            adapter.get_supply_apy("FRAX")

    def test_rpc_failure_falls_back_to_mock(self):
        """All-RPCs-fail → log warning + return _MOCK_APYS value, no raise."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            CompoundV3Adapter,
            "_call_with_fallback",
            side_effect=RuntimeError("all down"),
        ):
            apy = adapter.get_supply_apy("USDC")
        assert apy == CompoundV3Adapter._MOCK_APYS["USDC"] == 4.5

    def test_supply_rate_call_failure_falls_back(self):
        """Second-leg failure (getSupplyRate) still triggers fallback."""
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        util_hex = _uint256_hex(int(0.5 * 1e18))

        def fake_call(self, asset, data):  # noqa: ARG001
            if data == CompoundV3Adapter.SELECTOR_GET_UTILIZATION:
                return util_hex
            raise RuntimeError("getSupplyRate down")

        with patch.object(
            CompoundV3Adapter, "_call_with_fallback", new=fake_call,
        ):
            apy = adapter.get_supply_apy("USDC")
        assert apy == CompoundV3Adapter._MOCK_APYS["USDC"] == 4.5

    def test_unsupported_chain_raises_in_init(self):
        """Construction with an unknown chain raises immediately."""
        with pytest.raises(ValueError):
            CompoundV3Adapter(chain="polygon", dry_run=False)


# ─── TestGetSupplyBalanceLive ─────────────────────────────────────────────────


class TestGetSupplyBalanceLive:
    """Live get_supply_balance: Comet.balanceOf → 6-decimal scaling."""

    WALLET = "0x000000000000000000000000000000000000dEaD"

    def test_usdc_6_decimals_round_trip(self, monkeypatch):
        """USDC balance returned with 6-decimal scaling."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        # 12_345_678_000 raw → 12_345.678 USDC (6 decimals)
        balance_hex = _uint256_hex(12_345_678_000)

        captured: dict = {}

        def fake_call_with_fallback(self, asset, data):  # noqa: ARG001
            captured["data"] = data
            return balance_hex

        with patch.object(
            CompoundV3Adapter,
            "_call_with_fallback",
            new=fake_call_with_fallback,
        ):
            bal = adapter.get_supply_balance("USDC")

        assert bal == pytest.approx(12_345.678, abs=1e-9)
        # Confirm we hit balanceOf with the padded wallet arg.
        assert captured["data"].startswith(CompoundV3Adapter.SELECTOR_BALANCE_OF)
        # Wallet (no 0x) right-padded to 32 bytes.
        wallet_padded = self.WALLET[2:].lower().rjust(64, "0")
        assert captured["data"].endswith(wallet_padded)

    def test_missing_wallet_env_falls_back(self, monkeypatch):
        """No SPA_WALLET_ADDRESS → [FALLBACK] mock value, no raise."""
        monkeypatch.delenv("SPA_WALLET_ADDRESS", raising=False)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        # Even if RPC would have worked, missing env must short-circuit
        # before any RPC call and fall back to mock.
        with patch.object(
            CompoundV3Adapter,
            "_call_with_fallback",
            side_effect=AssertionError("should not be called"),
        ):
            bal = adapter.get_supply_balance("USDC")
        assert bal == CompoundV3Adapter._MOCK_BALANCES["USDC"] == 8000.0

    def test_rpc_failure_falls_back_to_mock(self, monkeypatch):
        """If balanceOf errors, return mock balance, not raise."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            CompoundV3Adapter,
            "_call_with_fallback",
            side_effect=RuntimeError("RPC down"),
        ):
            bal = adapter.get_supply_balance("USDC")
        assert bal == CompoundV3Adapter._MOCK_BALANCES["USDC"] == 8000.0

    def test_bad_asset_raises_valueerror(self, monkeypatch):
        """Unknown asset raises BEFORE the env check."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = CompoundV3Adapter(chain="ethereum", dry_run=False)
        with pytest.raises(ValueError):
            adapter.get_supply_balance("USDT")
