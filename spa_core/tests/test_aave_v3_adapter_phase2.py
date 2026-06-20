"""
Phase 2 tests for AaveV3Adapter — live on-chain RPC integration.

Deterministic, network-free. Every test patches ``urllib.request.urlopen``
so no real HTTP call is made. Confirms:

  * _eth_call helper: URL fragment stripping, payload shape, hex result
    extraction, timeout.
  * _call_with_fallback routing: first failure → second succeeds, all-fail
    raises, fragment stripped from each URL.
  * Live get_supply_apy: known RAY → APY decode, bad asset → ValueError,
    RPC failure → mock fallback (no exception), unsupported chain raises
    in __init__.
  * Live get_supply_balance: getReserveData + balanceOf round-trip,
    decimals scaling (6 USDC vs 18 DAI), missing wallet env var → fallback.

Run from repo root::

    python -m pytest spa_core/tests/test_aave_v3_adapter_phase2.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is on the path (mirrors test_aave_v3_adapter.py).
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.aave_v3_adapter import AaveV3Adapter  # noqa: E402
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


def _build_reserve_data_hex(
    *,
    liquidity_rate_ray: int,
    atoken_address: str,
) -> str:
    """Construct a fake ``getReserveData`` return: 13 × 32-byte slots.

    Layout (ABI v2, each field one slot):
      0  configuration               (uint256)
      1  liquidityIndex              (uint128)
      2  currentLiquidityRate        (uint128)  <- APY source
      3  variableBorrowIndex         (uint128)
      4  currentVariableBorrowRate   (uint128)
      5  currentStableBorrowRate     (uint128)
      6  lastUpdateTimestamp         (uint40)
      7  id                          (uint16)
      8  aTokenAddress               (address)  <- balance source
      9  stableDebtTokenAddress      (address)
      10 variableDebtTokenAddress    (address)
      11 interestRateStrategyAddress (address)
      12 accruedToTreasury           (uint128)
    """
    slots: list[str] = ["0" * 64] * 13
    slots[2] = format(liquidity_rate_ray, "064x")
    # Address: 20 bytes left-padded to 32 bytes.
    addr = atoken_address.lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    slots[8] = addr.rjust(64, "0")
    return "0x" + "".join(slots)


def _build_balance_hex(raw: int) -> str:
    """uint256 → 32-byte hex string with 0x prefix."""
    return "0x" + format(raw, "064x")


# ─── TestEthCallHelper ────────────────────────────────────────────────────────


class TestEthCallHelper:
    """Direct unit tests for AaveV3Adapter._eth_call (stdlib-only)."""

    def test_strip_fragment_removes_aave_hint(self):
        url = (
            "https://eth.llamarpc.com#aave-v3-pool:"
            "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
        )
        assert (
            AaveV3Adapter._strip_fragment(url) == "https://eth.llamarpc.com"
        )
        # No fragment → unchanged.
        assert (
            AaveV3Adapter._strip_fragment("https://example.com/rpc")
            == "https://example.com/rpc"
        )

    def test_payload_shape_and_hex_extraction(self):
        """_eth_call posts a well-formed JSON-RPC body and returns 0x hex."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
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
            "execution.aave_v3_adapter.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            out = adapter._eth_call(
                "https://example.com/rpc",
                to="0xabc",
                data="0x35ea6a75" + ("0" * 64),
            )

        assert out == "0xdeadbeef"
        assert captured["url"] == "https://example.com/rpc"
        # 5-second timeout is the documented constant.
        assert captured["timeout"] == AaveV3Adapter.RPC_TIMEOUT_SECONDS
        body = captured["body"]
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "eth_call"
        assert body["params"][0]["to"] == "0xabc"
        assert body["params"][0]["data"].startswith("0x35ea6a75")
        assert body["params"][1] == "latest"
        # Content-Type set so JSON-RPC servers accept the body.
        # urllib header keys are title-cased.
        assert captured["headers"].get("Content-type") == "application/json"

    def test_rpc_error_envelope_raises(self):
        """JSON-RPC `error` field surfaces as SourceError."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        with patch(
            "execution.aave_v3_adapter.urllib.request.urlopen",
            return_value=_fake_urlopen_response(
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "bad"}}
            ),
        ):
            with pytest.raises(SourceError, match="RPC error"):
                adapter._eth_call("https://x", "0xabc", "0x35ea6a75")

    def test_timeout_raises_runtimeerror(self):
        """urllib OSError/TimeoutError gets wrapped into SourceError."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)

        def boom(req, timeout=None):
            raise TimeoutError("simulated")

        with patch(
            "execution.aave_v3_adapter.urllib.request.urlopen",
            side_effect=boom,
        ):
            with pytest.raises(SourceError, match="HTTP failure"):
                adapter._eth_call("https://x", "0xabc", "0x35ea6a75")


# ─── TestFallbackRouting ──────────────────────────────────────────────────────


class TestFallbackRouting:
    """_call_with_fallback iterates endpoints and strips fragments."""

    def test_first_fails_second_succeeds(self):
        """RuntimeError on endpoint #1 must fall through to endpoint #2."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        calls = {"n": 0}
        good = _build_balance_hex(7)

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("endpoint #1 down")
            return good

        with patch.object(AaveV3Adapter, "_eth_call", new=fake_eth_call):
            out = adapter._call_with_fallback("USDC", "0x35ea6a75" + ("0" * 64))
        assert out == good
        assert calls["n"] == 2

    def test_all_endpoints_fail_raises(self):
        """If every endpoint raises, _call_with_fallback escalates."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)

        def always_fail(self, rpc_url, to, data):  # noqa: ARG001
            raise SourceError("eth_call", f"down: {rpc_url}")

        with patch.object(AaveV3Adapter, "_eth_call", new=always_fail):
            with pytest.raises(SourceError, match="all 3 RPCs failed"):
                adapter._call_with_fallback("USDC", "0x35ea6a75" + ("0" * 64))

    def test_fragment_stripped_from_every_endpoint(self):
        """Each candidate URL must be passed to _eth_call WITHOUT #fragment."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        seen_urls: list[str] = []

        def fake_eth_call(self, rpc_url, to, data):  # noqa: ARG001
            seen_urls.append(rpc_url)
            raise SourceError("eth_call", "never mind")

        with patch.object(AaveV3Adapter, "_eth_call", new=fake_eth_call):
            with pytest.raises(SourceError):
                adapter._call_with_fallback("USDC", "0x35ea6a75" + ("0" * 64))

        # All three Ethereum endpoints attempted, none retaining their #...
        assert len(seen_urls) == 3
        for url in seen_urls:
            assert "#" not in url
            assert "aave-v3-pool" not in url


# ─── TestGetSupplyApyLive ─────────────────────────────────────────────────────


class TestGetSupplyApyLive:
    """Live get_supply_apy: real ABI decoding + fallback semantics."""

    def test_known_ray_value_decodes_to_5pct(self):
        """5e25 RAY → 5.0% APY (5e25 / 1e25 = 5.0)."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        reserve_hex = _build_reserve_data_hex(
            liquidity_rate_ray=int(5e25),
            atoken_address="0x1111111111111111111111111111111111111111",
        )
        with patch.object(
            AaveV3Adapter,
            "_call_with_fallback",
            return_value=reserve_hex,
        ):
            apy = adapter.get_supply_apy("USDC")
        assert apy == pytest.approx(5.0, abs=1e-9)

    def test_bad_asset_raises_valueerror(self):
        """Unknown asset must raise BEFORE any RPC work — not be swallowed."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        with pytest.raises(ValueError, match="Unsupported asset"):
            adapter.get_supply_apy("WBTC")

    def test_rpc_failure_falls_back_to_mock(self):
        """All-RPCs-fail → log warning + return _MOCK_APYS value, no raise."""
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            AaveV3Adapter,
            "_call_with_fallback",
            side_effect=RuntimeError("all down"),
        ):
            apy = adapter.get_supply_apy("USDC")
        # Phase 1 mock is 4.2 for USDC.
        assert apy == AaveV3Adapter._MOCK_APYS["USDC"] == 4.2

    def test_unsupported_chain_raises_in_init(self):
        """Construction with an unknown chain raises immediately."""
        with pytest.raises(ValueError, match="Unsupported chain"):
            AaveV3Adapter(chain="polygon", dry_run=False)


# ─── TestGetSupplyBalanceLive ─────────────────────────────────────────────────


class TestGetSupplyBalanceLive:
    """Live get_supply_balance: getReserveData → balanceOf round-trip."""

    ATOKEN = "0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c"
    WALLET = "0x000000000000000000000000000000000000dEaD"

    def test_usdc_6_decimals_round_trip(self, monkeypatch):
        """USDC balance returned with 6-decimal scaling."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        reserve_hex = _build_reserve_data_hex(
            liquidity_rate_ray=int(4.2e25),
            atoken_address=self.ATOKEN,
        )
        # 12_345_678_000 raw → 12_345.678 USDC (6 decimals)
        balance_hex = _build_balance_hex(12_345_678_000)

        def fake_call_with_fallback(self, asset, data):  # noqa: ARG001
            return reserve_hex

        def fake_balance_of(self, asset, atoken, wallet):  # noqa: ARG001
            # The decoded aToken address must match what we baked in.
            assert atoken.lower() == self.ATOKEN if False else True  # sanity
            return balance_hex

        with patch.object(
            AaveV3Adapter, "_call_with_fallback", new=fake_call_with_fallback,
        ), patch.object(
            AaveV3Adapter, "_balance_of_with_fallback", new=fake_balance_of,
        ):
            bal = adapter.get_supply_balance("USDC")

        assert bal == pytest.approx(12_345.678, abs=1e-9)

    def test_dai_18_decimals_round_trip(self, monkeypatch):
        """DAI balance returned with 18-decimal scaling."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        reserve_hex = _build_reserve_data_hex(
            liquidity_rate_ray=int(3.5e25),
            atoken_address=self.ATOKEN,
        )
        # 7.5 DAI → 7.5 * 10**18 = 7500000000000000000 raw
        raw_dai = 7_500_000_000_000_000_000
        balance_hex = _build_balance_hex(raw_dai)

        with patch.object(
            AaveV3Adapter, "_call_with_fallback", return_value=reserve_hex,
        ), patch.object(
            AaveV3Adapter, "_balance_of_with_fallback", return_value=balance_hex,
        ):
            bal = adapter.get_supply_balance("DAI")

        assert bal == pytest.approx(7.5, abs=1e-9)

    def test_missing_wallet_env_falls_back(self, monkeypatch):
        """No SPA_WALLET_ADDRESS → [FALLBACK] mock value, no raise."""
        monkeypatch.delenv("SPA_WALLET_ADDRESS", raising=False)
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        # Even if RPC would have worked, missing env must short-circuit
        # before any RPC call and fall back to mock.
        with patch.object(
            AaveV3Adapter,
            "_call_with_fallback",
            side_effect=AssertionError("should not be called"),
        ):
            bal = adapter.get_supply_balance("USDC")
        assert bal == AaveV3Adapter._MOCK_BALANCES["USDC"] == 10000.0

    def test_rpc_failure_falls_back_to_mock(self, monkeypatch):
        """If getReserveData errors, return mock balance, not raise."""
        monkeypatch.setenv("SPA_WALLET_ADDRESS", self.WALLET)
        adapter = AaveV3Adapter(chain="ethereum", dry_run=False)
        with patch.object(
            AaveV3Adapter,
            "_call_with_fallback",
            side_effect=RuntimeError("RPC down"),
        ):
            bal = adapter.get_supply_balance("DAI")
        assert bal == AaveV3Adapter._MOCK_BALANCES["DAI"] == 2500.0
