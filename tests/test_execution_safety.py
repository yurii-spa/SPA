"""
tests/test_execution_safety.py

20 тестов аудита безопасности execution модулей.

Sprint v10.24 — MP-1408: Execution Safety Audit.

Проверяет что:
  1. Все функции с send/execute в T2 адаптерах → LiveTradingForbiddenError
  2. T1 адаптеры: _sign_and_send → LiveTradingForbiddenError
  3. Morpho: _send_raw_tx и _sign_and_send → LiveTradingForbiddenError
  4. SafeTxBuilder.submit_proposal → LiveTradingForbiddenError
  5. LiveTradingGate заблокирован по умолчанию
  6. Аудит-документ существует и содержит ключевые маркеры
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.errors import LiveTradingForbiddenError
from spa_core.safety.live_trading_gate import LiveTradingGate
from spa_core.execution.safe_tx_builder import SafeTxBuilder

_SAFE_ADDR = "0x0000000000000000000000000000000000000001"
_AUDIT_DOC = _REPO_ROOT / "docs" / "EXECUTION_SAFETY_AUDIT_20260619.md"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_forbidden(name, fn):
    """Assert that fn() raises LiveTradingForbiddenError."""
    with pytest.raises(LiveTradingForbiddenError, match=".*"):
        fn()


# ── 1. T1 адаптеры: _sign_and_send ───────────────────────────────────────────

class TestT1AdapterSignAndSend:
    def test_aave_v3_sign_and_send_forbidden(self):
        """ES01 — AaveV3Adapter._sign_and_send → LiveTradingForbiddenError."""
        from spa_core.execution.aave_v3_adapter import AaveV3Adapter
        a = AaveV3Adapter()
        _assert_forbidden(
            "AaveV3Adapter._sign_and_send",
            lambda: a._sign_and_send(None, "", to="", data="", nonce=0, chain_id=1, gas_price=0),
        )

    def test_compound_v3_sign_and_send_forbidden(self):
        """ES02 — CompoundV3Adapter._sign_and_send → LiveTradingForbiddenError."""
        from spa_core.execution.compound_v3_adapter import CompoundV3Adapter
        c = CompoundV3Adapter()
        _assert_forbidden(
            "CompoundV3Adapter._sign_and_send",
            lambda: c._sign_and_send(None, "", to="", data="", nonce=0, chain_id=1, gas_price=0),
        )


# ── 2. Morpho: _send_raw_tx и _sign_and_send ─────────────────────────────────

class TestMorphoAdapterForbidden:
    def test_morpho_send_raw_tx_forbidden(self):
        """ES03 — MorphoAdapter._send_raw_tx → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        m = MorphoAdapter()
        _assert_forbidden("MorphoAdapter._send_raw_tx", lambda: m._send_raw_tx("0xdeadbeef"))

    def test_morpho_sign_and_send_forbidden(self):
        """ES04 — MorphoAdapter._sign_and_send → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.morpho_adapter import MorphoAdapter
        m = MorphoAdapter()
        _assert_forbidden(
            "MorphoAdapter._sign_and_send",
            lambda: m._sign_and_send(None, "", to="", data="", nonce=0, chain_id=1, gas_price=0),
        )


# ── 3. T2 адаптеры: _execute_tx_pair и _execute_single_tx ────────────────────

class TestEulerV2AdapterForbidden:
    def test_execute_tx_pair_forbidden(self):
        """ES05 — EulerV2Adapter._execute_tx_pair → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter
        eu = EulerV2Adapter()
        _assert_forbidden(
            "EulerV2Adapter._execute_tx_pair",
            lambda: eu._execute_tx_pair(None, None, None, None, "supply"),
        )

    def test_execute_single_tx_forbidden(self):
        """ES06 — EulerV2Adapter._execute_single_tx → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.euler_v2_adapter import EulerV2Adapter
        eu = EulerV2Adapter()
        _assert_forbidden(
            "EulerV2Adapter._execute_single_tx",
            lambda: eu._execute_single_tx(None, None, None, "withdraw"),
        )


class TestMapleAdapterForbidden:
    def test_execute_tx_pair_forbidden(self):
        """ES07 — MapleAdapter._execute_tx_pair → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.maple_adapter import MapleAdapter
        ma = MapleAdapter()
        _assert_forbidden(
            "MapleAdapter._execute_tx_pair",
            lambda: ma._execute_tx_pair(None, None, None, None, "supply"),
        )

    def test_execute_single_tx_forbidden(self):
        """ES08 — MapleAdapter._execute_single_tx → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.maple_adapter import MapleAdapter
        ma = MapleAdapter()
        _assert_forbidden(
            "MapleAdapter._execute_single_tx",
            lambda: ma._execute_single_tx(None, None, None, "withdraw"),
        )


class TestSkySUSDSAdapterForbidden:
    def test_execute_tx_pair_forbidden(self):
        """ES09 — SkySUSDSAdapter._execute_tx_pair → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.sky_susds_adapter import SkySUSDSAdapter
        sk = SkySUSDSAdapter()
        _assert_forbidden(
            "SkySUSDSAdapter._execute_tx_pair",
            lambda: sk._execute_tx_pair(None, None, None, None, "supply"),
        )

    def test_execute_single_tx_forbidden(self):
        """ES10 — SkySUSDSAdapter._execute_single_tx → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.sky_susds_adapter import SkySUSDSAdapter
        sk = SkySUSDSAdapter()
        _assert_forbidden(
            "SkySUSDSAdapter._execute_single_tx",
            lambda: sk._execute_single_tx(None, None, None, "withdraw"),
        )


class TestYearnV3AdapterForbidden:
    def test_execute_tx_pair_forbidden(self):
        """ES11 — YearnV3Adapter._execute_tx_pair → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter
        ye = YearnV3Adapter()
        _assert_forbidden(
            "YearnV3Adapter._execute_tx_pair",
            lambda: ye._execute_tx_pair(None, None, None, None, "supply"),
        )

    def test_execute_single_tx_forbidden(self):
        """ES12 — YearnV3Adapter._execute_single_tx → LiveTradingForbiddenError."""
        from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter
        ye = YearnV3Adapter()
        _assert_forbidden(
            "YearnV3Adapter._execute_single_tx",
            lambda: ye._execute_single_tx(None, None, None, "withdraw"),
        )


# ── 4. SafeTxBuilder.submit_proposal ─────────────────────────────────────────

class TestSafeTxBuilderSubmitForbidden:
    def test_submit_proposal_forbidden_paper(self):
        """ES13 — SafeTxBuilder.submit_proposal в paper mode → LiveTradingForbiddenError."""
        b = SafeTxBuilder(_SAFE_ADDR)
        _assert_forbidden("SafeTxBuilder.submit_proposal", lambda: b.submit_proposal({}))

    def test_submit_proposal_forbidden_live_mode(self, monkeypatch):
        """ES14 — SafeTxBuilder.submit_proposal в live mode (gate inactive) → LiveTradingForbiddenError."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        b = SafeTxBuilder(_SAFE_ADDR)
        _assert_forbidden("SafeTxBuilder.submit_proposal (live)", lambda: b.submit_proposal({"test": 1}))


# ── 5. LiveTradingGate: заблокирован по умолчанию ────────────────────────────

class TestLiveTradingGateDefault:
    def test_gate_locked_by_default(self, tmp_path):
        """ES15 — LiveTradingGate заблокирован по умолчанию (active=False)."""
        gate = LiveTradingGate(base_dir=str(tmp_path))
        assert gate.is_active() is False

    def test_require_live_gate_raises_when_locked(self, tmp_path):
        """ES16 — require_live_gate() → LiveTradingForbiddenError когда gate LOCKED."""
        gate = LiveTradingGate(base_dir=str(tmp_path))
        with pytest.raises(LiveTradingForbiddenError):
            gate.require_live_gate()

    def test_gate_not_activated_without_prerequisites(self, tmp_path):
        """ES17 — activate() без prerequisites → False, gate остаётся LOCKED."""
        gate = LiveTradingGate(base_dir=str(tmp_path))
        fake_key = "a" * 64   # valid SHA256 format
        result = gate.activate(fake_key, "test")
        assert result is False
        assert gate.is_active() is False

    def test_gate_activation_requires_valid_sha256_key(self, tmp_path):
        """ES18 — activate() с коротким ключом → False."""
        gate = LiveTradingGate(base_dir=str(tmp_path))
        result = gate.activate("tooshort", "test")
        assert result is False


# ── 6. Аудит-документ существует и корректен ─────────────────────────────────

class TestAuditDocumentExists:
    def test_audit_document_exists(self):
        """ES19 — docs/EXECUTION_SAFETY_AUDIT_20260619.md существует."""
        assert _AUDIT_DOC.exists(), f"Audit document not found: {_AUDIT_DOC}"

    def test_audit_document_contains_guarded_keyword(self):
        """ES20 — Аудит-документ содержит 'GUARDED' и 'live_trading_forbidden'."""
        assert _AUDIT_DOC.exists(), "Audit document missing"
        content = _AUDIT_DOC.read_text(encoding="utf-8")
        assert "GUARDED" in content, "Audit doc must contain 'GUARDED' status markers"
        assert "live_trading_forbidden" in content, (
            "Audit doc must reference @live_trading_forbidden decorator"
        )
        assert "LiveTradingForbiddenError" in content, (
            "Audit doc must mention LiveTradingForbiddenError"
        )
