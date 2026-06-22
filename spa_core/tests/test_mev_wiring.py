"""
Tests for MEV-protection wiring into adapter live-execution paths.

Sprint v3.52 / SPA-V352. The MEV protection layer (mev_protection.py, v3.26)
existed but NO adapter actually routed its broadcast through it — every adapter
called eth_signer.send_raw_transaction directly, so Flashbots routing was dead
code in the real execution path. This sprint wires it in:

  * T2 adapters (yearn, maple, sky, euler) — consume the broadcast result as a
    dict; now call mev_protection.send_raw_transaction_auto.
  * T1 adapters (aave, compound) — consume a tx-hash string then poll; their
    _send_raw_tx chokepoint now prefers Flashbots in live mode, falling back to
    the public RPC path on any routing error.

All tests are offline (no network).
"""
import inspect
import unittest.mock as mock

import pytest

from spa_core.execution.mev_protection import (
    send_raw_transaction_auto,
    broadcast_protected_hash,
)

T2_MODULES = [
    "spa_core.execution.adapters.yearn_v3_adapter",
    "spa_core.execution.adapters.maple_adapter",
    "spa_core.execution.adapters.sky_susds_adapter",
    "spa_core.execution.adapters.euler_v2_adapter",
]
T1_MODULES = [
    "spa_core.execution.aave_v3_adapter",
    "spa_core.execution.compound_v3_adapter",
]


def _source(modpath):
    mod = __import__(modpath, fromlist=["*"])
    return inspect.getsource(mod)


# ─── Source-level wiring guards ───────────────────────────────────────────────

class TestT2Wiring:
    @pytest.mark.parametrize("modpath", T2_MODULES)
    def test_imports_mev_auto(self, modpath):
        src = _source(modpath)
        assert "send_raw_transaction_auto" in src, (
            f"{modpath} must route broadcast through send_raw_transaction_auto"
        )

    @pytest.mark.parametrize("modpath", T2_MODULES)
    def test_no_direct_broadcast(self, modpath):
        src = _source(modpath)
        assert "send_raw_transaction(signed.hex()" not in src, (
            f"{modpath} still calls eth_signer.send_raw_transaction directly"
        )

    @pytest.mark.parametrize("modpath", T2_MODULES)
    def test_failure_check_includes_failed(self, modpath):
        src = _source(modpath)
        # Broadened revert/failure check now also catches a FAILED broadcast
        assert '("0x0", "FAILED")' in src, (
            f"{modpath} should treat a FAILED broadcast as a failed phase"
        )


class TestT1Wiring:
    @pytest.mark.parametrize("modpath", T1_MODULES)
    def test_send_raw_tx_routes_through_mev(self, modpath):
        src = _source(modpath)
        assert "mev_protection.send_protected" in src, (
            f"{modpath}._send_raw_tx must prefer Flashbots in live mode"
        )
        assert "is_mev_protection_enabled" in src

    @pytest.mark.parametrize("modpath", T1_MODULES)
    def test_send_raw_tx_keeps_public_fallback(self, modpath):
        src = _source(modpath)
        # Public path must remain so default behaviour is unchanged
        assert '_rpc_first("eth_sendRawTransaction"' in src


# ─── send_raw_transaction_auto: consistent dict contract ──────────────────────

class TestAutoReturnContract:
    FAKE_TX = "0x" + "cc" * 80
    FAKE_RPC = "https://rpc.example.com"

    def test_public_path_normalises_hash_to_dict(self, monkeypatch):
        """Real eth_signer returns a hash STR; auto must hand back a dict."""
        monkeypatch.delenv("SPA_MEV_PROTECTION", raising=False)
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        tx_hash = "0x" + "ab" * 32
        with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                        return_value=tx_hash):
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
        assert isinstance(result, dict)
        assert result["tx_hash"] == tx_hash
        assert result["status"] == "PENDING"
        assert result["protection"] == "none"
        assert result["endpoint"] == self.FAKE_RPC
        # The .get() the adapters rely on must be safe and non-revert
        assert result.get("status") not in ("0x0", "FAILED")

    def test_public_path_passes_dict_through(self, monkeypatch):
        monkeypatch.delenv("SPA_MEV_PROTECTION", raising=False)
        monkeypatch.delenv("SPA_EXECUTION_MODE", raising=False)
        receipt = {"status": "0x1", "tx_hash": "0x" + "dd" * 32}
        with mock.patch("spa_core.execution.eth_signer.send_raw_transaction",
                        return_value=receipt):
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
        assert result is receipt

    def test_flashbots_path_returns_dict_when_live(self, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value={"result": "0x" + "ee" * 32}):
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
        assert result["status"] == "PENDING"
        assert result["protection"] == "flashbots"


# ─── broadcast_protected_hash: hash-returning helper for T1 ───────────────────

class TestBroadcastProtectedHash:
    def test_returns_hash_on_success(self):
        tx_hash = "0x" + "12" * 32
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value={"result": tx_hash}):
            assert broadcast_protected_hash("0xabc") == tx_hash

    def test_raises_when_all_endpoints_fail(self):
        def boom(url, payload, timeout):
            raise ConnectionError("down")
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        side_effect=boom):
            with pytest.raises(RuntimeError):
                broadcast_protected_hash("0xabc")

    def test_no_silent_public_fallback(self):
        """broadcast_protected_hash must NOT fall through to a public RPC."""
        def boom(url, payload, timeout):
            raise ConnectionError("down")
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        side_effect=boom):
            with mock.patch(
                "spa_core.execution.eth_signer.send_raw_transaction"
            ) as pub:
                with pytest.raises(RuntimeError):
                    broadcast_protected_hash("0xabc")
                pub.assert_not_called()


# ─── T1 _send_raw_tx behavioural routing ──────────────────────────────────────

def _t1_adapters():
    from spa_core.execution.aave_v3_adapter import AaveV3Adapter
    from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
    return [AaveV3Adapter, CompoundV3Adapter]


class TestT1SendRawTxRouting:
    SIGNED = "0x" + "fa" * 50

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_public_when_mev_off(self, Adapter, monkeypatch):
        monkeypatch.delenv("SPA_MEV_PROTECTION", raising=False)
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        pub_hash = "0x" + "11" * 32
        monkeypatch.setattr(a, "_rpc_first", lambda m, p: pub_hash)
        with mock.patch(
            "spa_core.execution.mev_protection.send_protected"
        ) as fb:
            assert a._send_raw_tx(self.SIGNED) == pub_hash
            fb.assert_not_called()

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_flashbots_when_on_and_live(self, Adapter, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        fb_hash = "0x" + "22" * 32
        monkeypatch.setattr(a, "_rpc_first",
                            lambda m, p: pytest.fail("public path used"))
        with mock.patch(
            "spa_core.execution.mev_protection.send_protected",
            return_value={"status": "PENDING", "tx_hash": fb_hash,
                          "endpoint": "flashbots"},
        ):
            assert a._send_raw_tx(self.SIGNED) == fb_hash

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_falls_back_to_public_when_flashbots_fails(self, Adapter, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        pub_hash = "0x" + "33" * 32
        monkeypatch.setattr(a, "_rpc_first", lambda m, p: pub_hash)
        with mock.patch(
            "spa_core.execution.mev_protection.send_protected",
            return_value={"status": "FAILED", "reason": "all endpoints down"},
        ):
            assert a._send_raw_tx(self.SIGNED) == pub_hash

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_not_live_uses_public(self, Adapter, monkeypatch):
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "paper")  # not live
        a = Adapter()
        pub_hash = "0x" + "44" * 32
        monkeypatch.setattr(a, "_rpc_first", lambda m, p: pub_hash)
        with mock.patch(
            "spa_core.execution.mev_protection.send_protected"
        ) as fb:
            assert a._send_raw_tx(self.SIGNED) == pub_hash
            fb.assert_not_called()
