"""
tests/test_safe_tx_builder.py

25 тестов для spa_core/execution/safe_tx_builder.py.

Sprint v10.23 — MP-1407: TODO resolution + validation + gas estimation.

Покрытие:
  - SafeTxBuilder создание и режимы
  - build_allocate_tx / build_withdraw_tx (paper + live)
  - @live_trading_forbidden на submit_proposal
  - Validation (amount, whitelist, safe_address, proposal)
  - Gas estimation (estimate_gas_dry_run)
  - ABI encode helpers (_abi_encode_address, _abi_encode_uint256)
  - describe(), get_safe_tx_service_url(), get_chain_id(), get_safe_address()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.execution.safe_tx_builder import (
    SafeTxBuilder,
    PROTOCOL_WHITELIST,
    SINGLE_SIG_THRESHOLD_USD,
    SAFE_TX_SERVICE_URLS,
    _usd_to_usdc_raw,
    _abi_encode_address,
    _abi_encode_uint256,
    _validate_safe_address,
    _encode_allocate_stub,
    _encode_withdraw_stub,
)
from spa_core.utils.errors import LiveTradingForbiddenError

_SAFE_ADDR  = "0x0000000000000000000000000000000000000001"
_SAFE_ADDR2 = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def paper_builder():
    """SafeTxBuilder в paper mode (по умолчанию)."""
    return SafeTxBuilder(safe_address=_SAFE_ADDR, chain_id=1)


@pytest.fixture
def live_builder(monkeypatch):
    """SafeTxBuilder в live mode (с заглушками адресов в whitelist)."""
    monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
    # Устанавливаем временные адреса в whitelist
    original = dict(PROTOCOL_WHITELIST)
    PROTOCOL_WHITELIST["aave_v3"]     = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    PROTOCOL_WHITELIST["compound_v3"] = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    PROTOCOL_WHITELIST["yearn_v3"]    = "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    PROTOCOL_WHITELIST["euler_v2"]    = "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
    builder = SafeTxBuilder(safe_address=_SAFE_ADDR, chain_id=1)
    yield builder
    # Восстанавливаем
    PROTOCOL_WHITELIST.update(original)
    for k in list(PROTOCOL_WHITELIST.keys()):
        if k not in original:
            del PROTOCOL_WHITELIST[k]


# ── Тест 1: SafeTxBuilder создаётся в paper mode ──────────────────────────────

class TestSafeTxBuilderCreation:
    def test_created_in_paper_mode_by_default(self, paper_builder):
        """T01 — без SPA_EXECUTION_MODE=live → paper mode."""
        assert paper_builder.is_paper_mode() is True

    def test_live_mode_with_env(self, monkeypatch):
        """T02 — SPA_EXECUTION_MODE=live → live mode."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        b = SafeTxBuilder(_SAFE_ADDR)
        assert b.is_paper_mode() is False

    def test_invalid_address_raises_value_error(self):
        """T03 — некорректный адрес → ValueError."""
        with pytest.raises(ValueError, match="safe_address"):
            SafeTxBuilder("not_an_address")

    def test_invalid_address_no_0x_prefix(self):
        """T04 — адрес без 0x → ValueError."""
        with pytest.raises(ValueError, match="0x"):
            SafeTxBuilder("AbCdEf0123456789AbCdEf0123456789AbCdEf01")

    def test_invalid_chain_id_raises(self):
        """T05 — chain_id=0 → ValueError."""
        with pytest.raises(ValueError, match="chain_id"):
            SafeTxBuilder(_SAFE_ADDR, chain_id=0)

    def test_negative_chain_id_raises(self):
        """T06 — chain_id=-1 → ValueError."""
        with pytest.raises(ValueError, match="chain_id"):
            SafeTxBuilder(_SAFE_ADDR, chain_id=-1)


# ── Тест 2: build_allocate_tx / build_withdraw_tx в paper mode ───────────────

class TestPaperModeNoOp:
    def test_allocate_paper_returns_empty(self, paper_builder):
        """T07 — build_allocate_tx в paper mode → {}."""
        assert paper_builder.build_allocate_tx("aave_v3", 500.0) == {}

    def test_withdraw_paper_returns_empty(self, paper_builder):
        """T08 — build_withdraw_tx в paper mode → {}."""
        assert paper_builder.build_withdraw_tx("compound_v3", 200.0) == {}

    def test_paper_ignores_nonce(self, paper_builder):
        """T09 — nonce игнорируется в paper mode."""
        result = paper_builder.build_allocate_tx("aave_v3", 100.0, nonce=999)
        assert result == {}


# ── Тест 3: Validation в live mode ───────────────────────────────────────────

class TestValidationLiveMode:
    def test_allocate_negative_amount_raises(self, live_builder):
        """T10 — amount_usd <= 0 → ValueError."""
        with pytest.raises(ValueError, match="positive"):
            live_builder.build_allocate_tx("aave_v3", -100.0)

    def test_allocate_zero_amount_raises(self, live_builder):
        """T11 — amount_usd == 0 → ValueError."""
        with pytest.raises(ValueError, match="positive"):
            live_builder.build_allocate_tx("aave_v3", 0.0)

    def test_withdraw_negative_amount_raises(self, live_builder):
        """T12 — amount_usd <= 0 для withdraw → ValueError."""
        with pytest.raises(ValueError, match="positive"):
            live_builder.build_withdraw_tx("aave_v3", -1.0)

    def test_unknown_adapter_returns_empty(self, live_builder):
        """T13 — adapter не в whitelist → {}."""
        result = live_builder.build_allocate_tx("nonexistent_protocol", 500.0)
        assert result == {}

    def test_empty_protocol_address_returns_empty(self, live_builder, monkeypatch):
        """T14 — пустой адрес в whitelist → {}."""
        original = PROTOCOL_WHITELIST.get("morpho_blue", "")
        PROTOCOL_WHITELIST["morpho_blue"] = ""
        result = live_builder.build_allocate_tx("morpho_blue", 500.0)
        PROTOCOL_WHITELIST["morpho_blue"] = original
        assert result == {}


# ── Тест 4: Proposal dict структура в live mode ───────────────────────────────

class TestProposalStructure:
    def test_allocate_returns_dict_with_required_fields(self, live_builder):
        """T15 — build_allocate_tx → dict со всеми обязательными полями."""
        proposal = live_builder.build_allocate_tx("aave_v3", 500.0, nonce=10)
        assert isinstance(proposal, dict)
        for field in ("safe", "to", "value", "data", "operation", "nonce", "chain_id"):
            assert field in proposal, f"Missing field: {field}"

    def test_allocate_small_amount_single_sig_true(self, live_builder):
        """T16 — amount < $1000 → single_sig_eligible=True."""
        proposal = live_builder.build_allocate_tx("aave_v3", 500.0, nonce=1)
        meta = proposal["_spa_metadata"]
        assert meta["single_sig_eligible"] is True

    def test_allocate_large_amount_single_sig_false(self, live_builder):
        """T17 — amount >= $1000 → single_sig_eligible=False."""
        proposal = live_builder.build_allocate_tx("aave_v3", 5000.0, nonce=2)
        meta = proposal["_spa_metadata"]
        assert meta["single_sig_eligible"] is False

    def test_withdraw_always_single_sig(self, live_builder):
        """T18 — withdraw всегда single_sig_eligible=True (kill-switch priority)."""
        proposal = live_builder.build_withdraw_tx("aave_v3", 50_000.0, nonce=3)
        meta = proposal["_spa_metadata"]
        assert meta["single_sig_eligible"] is True

    def test_proposal_calldata_starts_with_0x(self, live_builder):
        """T19 — calldata всегда начинается с 0x."""
        proposal = live_builder.build_allocate_tx("aave_v3", 100.0, nonce=5)
        assert proposal["data"].startswith("0x")


# ── Тест 5: @live_trading_forbidden на submit_proposal ────────────────────────

class TestSubmitProposalForbidden:
    def test_submit_paper_raises(self, paper_builder):
        """T20 — submit_proposal в paper mode → LiveTradingForbiddenError."""
        with pytest.raises(LiveTradingForbiddenError):
            paper_builder.submit_proposal({"safe": "0x123"})

    def test_submit_live_raises(self, live_builder):
        """T21 — submit_proposal в live mode → LiveTradingForbiddenError (gate не активирован)."""
        with pytest.raises(LiveTradingForbiddenError):
            live_builder.submit_proposal({"safe": "0x123"})

    def test_submit_empty_proposal_raises(self, paper_builder):
        """T22 — submit_proposal с {} → LiveTradingForbiddenError."""
        with pytest.raises(LiveTradingForbiddenError):
            paper_builder.submit_proposal({})


# ── Тест 6: Gas estimation ────────────────────────────────────────────────────

class TestGasEstimation:
    def test_estimate_gas_returns_dict(self, paper_builder):
        """T23 — estimate_gas_dry_run → dict с ожидаемыми ключами."""
        result = paper_builder.estimate_gas_dry_run("aave_v3", "allocate")
        for key in ("gas_limit", "gas_price_gwei", "estimated_cost_eth",
                    "estimated_cost_usd", "dry_run", "note"):
            assert key in result, f"Missing key: {key}"

    def test_estimate_gas_dry_run_flag(self, paper_builder):
        """T24 — dry_run=True всегда."""
        result = paper_builder.estimate_gas_dry_run("aave_v3")
        assert result["dry_run"] is True

    def test_estimate_gas_different_adapters(self, paper_builder):
        """T25 — разные адаптеры → разные gas_limit."""
        aave  = paper_builder.estimate_gas_dry_run("aave_v3", "allocate")
        comp  = paper_builder.estimate_gas_dry_run("compound_v3", "allocate")
        assert aave["gas_limit"] != comp["gas_limit"]


# ── Дополнительные тесты ──────────────────────────────────────────────────────

class TestHelperMethods:
    def test_get_safe_tx_service_url_mainnet(self, paper_builder):
        """T26 — chain_id=1 → mainnet URL."""
        assert "mainnet" in paper_builder.get_safe_tx_service_url()

    def test_get_safe_tx_service_url_sepolia(self, monkeypatch):
        """T27 — chain_id=11155111 → sepolia URL."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "paper")
        b = SafeTxBuilder(_SAFE_ADDR, chain_id=11155111)
        assert "sepolia" in b.get_safe_tx_service_url()

    def test_get_safe_tx_service_url_unknown_chain(self, monkeypatch):
        """T28 — неизвестный chain_id → пустая строка."""
        monkeypatch.setenv("SPA_EXECUTION_MODE", "paper")
        b = SafeTxBuilder(_SAFE_ADDR, chain_id=999999)
        assert b.get_safe_tx_service_url() == ""

    def test_describe_contains_safe_address(self, paper_builder):
        """T29 — describe() содержит safe_address."""
        d = paper_builder.describe()
        assert d["safe_address"] == _SAFE_ADDR
        assert d["is_paper"] is True
        assert "protocol_whitelist_keys" in d

    def test_usd_to_usdc_raw(self):
        """T30 — $1.0 USD → 1_000_000 raw (6 decimals)."""
        assert _usd_to_usdc_raw(1.0) == 1_000_000
        assert _usd_to_usdc_raw(500.0) == 500_000_000


class TestAbiEncoding:
    def test_abi_encode_address_length(self):
        """T31 — ABI-encoded address = 64 hex chars (32 bytes)."""
        enc = _abi_encode_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
        assert len(enc) == 64
        assert enc[:24] == "0" * 24  # left-padded

    def test_abi_encode_uint256_zero(self):
        """T32 — uint256(0) → 64 zeros."""
        assert _abi_encode_uint256(0) == "0" * 64

    def test_abi_encode_uint256_value(self):
        """T33 — uint256(1_000_000) → correct hex."""
        enc = _abi_encode_uint256(1_000_000)
        assert len(enc) == 64
        assert enc.endswith("f4240")  # 0xf4240 = 1_000_000

    def test_encode_allocate_aave_v3_selector(self, monkeypatch):
        """T34 — _encode_allocate_stub для aave_v3 → правильный selector 617ba037."""
        addr = "0x" + "A" * 40
        calldata = _encode_allocate_stub(addr, 1_000_000, "aave_v3")
        assert calldata.startswith("0x617ba037"), f"Expected selector 617ba037, got {calldata[:10]}"

    def test_encode_withdraw_aave_v3_selector(self, monkeypatch):
        """T35 — _encode_withdraw_stub для aave_v3 → правильный selector 69328dec."""
        addr = "0x" + "A" * 40
        calldata = _encode_withdraw_stub(addr, 1_000_000, "aave_v3")
        assert calldata.startswith("0x69328dec"), f"Expected selector 69328dec, got {calldata[:10]}"


class TestValidateProposal:
    def test_validate_empty_proposal(self, paper_builder):
        """T36 — validate_proposal({}) → ошибки."""
        errors = paper_builder.validate_proposal({})
        assert len(errors) > 0

    def test_validate_non_dict(self, paper_builder):
        """T37 — validate_proposal(None) → ['proposal must be a dict']."""
        errors = paper_builder.validate_proposal(None)  # type: ignore
        assert any("dict" in e for e in errors)
