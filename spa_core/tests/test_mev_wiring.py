"""
Tests for MEV-protection wiring into adapter live-execution paths.

Sprint v3.52 / SPA-V352. The MEV protection layer (mev_protection.py, v3.26)
existed but NO adapter actually routed its broadcast through it — every adapter
called eth_signer.send_raw_transaction directly, so Flashbots routing was dead
code in the real execution path. This sprint wires it in:

  * T2 adapters (yearn, maple, sky, euler) — consume the broadcast result as a
    dict; now call mev_protection.send_raw_transaction_auto.
  * T1 adapters (aave, compound) — consume a tx-hash string then poll; their
    _send_raw_tx chokepoint now routes through the fail-CLOSED
    mev_protection.guard_broadcast in live mode.

AUDIT #3/#4 HARDENING (execution-correctness sprint): _send_raw_tx no longer falls
through to the public mempool on a protected-broadcast failure ("never block the
public path" defeated MEV protection + broke the private-only contract). It now
routes through guard_broadcast (gas/MEV-aware, fail-CLOSED) and ABORTS — raising,
never broadcasting — on a guard ABORT or a FAILED protected broadcast. The public
RPC path remains ONLY for the MEV-OFF / not-live case (byte-for-byte legacy).

All tests are offline (no network).
"""
import inspect
import unittest.mock as mock

import pytest

from spa_core.execution import mev_protection
from spa_core.execution.mev_protection import (
    send_raw_transaction_auto,
    broadcast_protected_hash,
)
from spa_core.utils.errors import SourceError

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
        # AUDIT #4: the REAL live path now routes through the fail-CLOSED guard
        # (gas/MEV-aware), not a bare send_protected.
        assert "mev_protection.guard_broadcast" in src, (
            f"{modpath}._send_raw_tx must route through guard_broadcast in live mode"
        )
        assert "is_mev_protection_enabled" in src

    @pytest.mark.parametrize("modpath", T1_MODULES)
    def test_send_raw_tx_no_public_fallback_on_protected_failure(self, modpath):
        # AUDIT #3: the public-mempool fallback ("never block the public path")
        # must be GONE — a failed protected broadcast ABORTS (fail-CLOSED).
        src = _source(modpath)
        assert "never block the public path" not in src
        assert "no public-mempool fallback" in src

    @pytest.mark.parametrize("modpath", T1_MODULES)
    def test_send_raw_tx_keeps_public_path_for_mev_off(self, modpath):
        src = _source(modpath)
        # The legacy public path remains ONLY for the MEV-OFF / not-live case.
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
        # WS-5.1: send_protected self-checks SPA_EXEC_ARMED — arm to exercise the
        # armed flashbots routing (reset by monkeypatch after the test).
        monkeypatch.setenv("SPA_EXEC_ARMED", "1")
        with mock.patch("spa_core.execution.mev_protection._send_to_endpoint",
                        return_value={"result": "0x" + "ee" * 32}):
            result = send_raw_transaction_auto(self.FAKE_TX, self.FAKE_RPC)
        assert result["status"] == "PENDING"
        assert result["protection"] == "flashbots"


# ─── broadcast_protected_hash: hash-returning helper for T1 ───────────────────

class TestBroadcastProtectedHash:
    @pytest.fixture(autouse=True)
    def _arm_exec(self, monkeypatch):
        # WS-5.1: broadcast_protected_hash → send_protected self-checks
        # SPA_EXEC_ARMED. Arm to exercise the routing (reset per test).
        monkeypatch.setenv("SPA_EXEC_ARMED", "1")

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
            with pytest.raises((RuntimeError, SourceError)):
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
                with pytest.raises((RuntimeError, SourceError)):
                    broadcast_protected_hash("0xabc")
                pub.assert_not_called()


# ─── T1 _send_raw_tx behavioural routing ──────────────────────────────────────

def _t1_adapters():
    from spa_core.execution.aave_v3_adapter import AaveV3Adapter
    from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
    return [AaveV3Adapter, CompoundV3Adapter]


class TestT1SendRawTxRouting:
    SIGNED = "0x" + "fa" * 50

    @pytest.fixture(autouse=True)
    def _arm_exec(self, monkeypatch):
        # WS-5.2 STRUCTURAL guard: _send_raw_tx now self-checks SPA_EXEC_ARMED.
        # These tests exercise the ARMED broadcast-routing logic, so arm here.
        # The guard-coverage test (test_execution_guard_coverage.py) proves the
        # NON-armed block. SPA_EXEC_ARMED is reset by monkeypatch after each test.
        monkeypatch.setenv("SPA_EXEC_ARMED", "1")

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
    def test_protected_when_on_and_live(self, Adapter, monkeypatch):
        # AUDIT #4: live + MEV-on routes through guard_broadcast; the public path
        # must NEVER be touched.
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        fb_hash = "0x" + "22" * 32
        monkeypatch.setattr(a, "_get_gas_price", lambda: 20_000_000_000)  # 20 gwei
        monkeypatch.setattr(a, "_rpc_first",
                            lambda m, p: pytest.fail("public path used"))
        with mock.patch(
            "spa_core.execution.mev_protection.guard_broadcast",
            return_value={"status": "PENDING", "tx_hash": fb_hash,
                          "endpoint": "flashbots"},
        ) as gb:
            assert a._send_raw_tx(self.SIGNED) == fb_hash
            gb.assert_called_once()
            # fail-CLOSED: private-only, no public fallback handed to the guard.
            assert gb.call_args.kwargs["fallback_rpc"] is None

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_aborts_no_public_fallback_when_protected_fails(self, Adapter, monkeypatch):
        # AUDIT #3: a FAILED protected broadcast must ABORT (raise) — it must NOT
        # fall through to the public mempool.
        from spa_core.utils.errors import ValidationError
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        monkeypatch.setattr(a, "_get_gas_price", lambda: 20_000_000_000)
        monkeypatch.setattr(
            a, "_rpc_first",
            lambda m, p: pytest.fail("public mempool reached on protected failure"),
        )
        with mock.patch(
            "spa_core.execution.mev_protection.guard_broadcast",
            return_value={"status": "FAILED", "reason": "all endpoints down"},
        ):
            with pytest.raises(ValidationError):
                a._send_raw_tx(self.SIGNED)

    @pytest.mark.parametrize("Adapter", _t1_adapters())
    def test_aborts_no_public_fallback_on_guard_abort(self, Adapter, monkeypatch):
        # AUDIT #3/#4: a guard ABORT (gas spike / stale oracle / sandwich) must
        # raise and broadcast nothing — never the public path.
        from spa_core.utils.errors import ValidationError
        monkeypatch.setenv("SPA_MEV_PROTECTION", "true")
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        a = Adapter()
        monkeypatch.setattr(a, "_get_gas_price", lambda: 20_000_000_000)
        monkeypatch.setattr(
            a, "_rpc_first",
            lambda m, p: pytest.fail("public mempool reached on guard ABORT"),
        )
        with mock.patch(
            "spa_core.execution.mev_protection.guard_broadcast",
            return_value={"status": "ABORTED", "reason": "gas spike 5x → ABORT"},
        ):
            with pytest.raises(ValidationError):
                a._send_raw_tx(self.SIGNED)

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
