"""
Tests for spa_core/execution/eth_signer.py (Sprint v3.24 — eth_account refactor).

All tests use a deterministic secp256k1 test key that is public knowledge
(do NOT use any of these private keys on mainnet or with real funds).

Test key #1 (Ethereum dev standard test key #1):
    private_key = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
    address     = 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266   (checksummed)

Test key #2 (index 1 from the same mnemonic):
    private_key = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
    address     = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8
"""
from __future__ import annotations

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

# Hardhat / Foundry default test private keys (publicly known)
_PK1_NO_PREFIX = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_PK1_WITH_PREFIX = "0x" + _PK1_NO_PREFIX
_ADDR1 = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"  # checksummed

_PK2_NO_PREFIX = "59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
_PK2_WITH_PREFIX = "0x" + _PK2_NO_PREFIX
_ADDR2 = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

_SAMPLE_TX = {
    "to":                   "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    "value":                0,
    "gas":                  21000,
    "maxFeePerGas":         30_000_000_000,  # 30 gwei
    "maxPriorityFeePerGas": 2_000_000_000,   # 2 gwei
    "nonce":                0,
    "chainId":              1,
    "data":                 b"",
}


# ─── 1. get_address_from_private_key ──────────────────────────────────────────

class TestGetAddress:
    def test_returns_checksummed_address(self):
        from spa_core.execution.eth_signer import get_address_from_private_key
        addr = get_address_from_private_key(_PK1_NO_PREFIX)
        assert addr == _ADDR1, f"Expected {_ADDR1}, got {addr}"

    def test_accepts_0x_prefix(self):
        from spa_core.execution.eth_signer import get_address_from_private_key
        addr = get_address_from_private_key(_PK1_WITH_PREFIX)
        assert addr == _ADDR1

    def test_different_key_different_address(self):
        from spa_core.execution.eth_signer import get_address_from_private_key
        addr = get_address_from private_key(_PK2_NO_PREFIX)
        assert addr == _ADDR2
        assert addr != _ADDR1

    def test_short_key_raises_value_error(self):
        from spa_core.execution.eth_signer import get_address_from_private_key
        with pytest.raises(ValueError, match="64 hex chars"):
            get_address_from_private_key("deadbeef")  # too short

    def test_wrong_length_raises(self):
        from spa_core.execution.eth_signer import get_address_from_private_key
        with pytest.raises(ValueError):
            get_address_from_private_key("0x" + "ab" * 10)  # only 20 bytes


# ─── 2. sign_transaction ──────────────────────────────────────────────────────

class TestSignTransaction:
    def test_returns_bytes(self):
        from spa_core.execution.eth_signer import sign_transaction
        raw = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        assert isinstance(raw, bytes), f"Expected bytes, got {type(raw)}"

    def test_starts_with_type2_byte(self):
        """EIP-2718 type-2 envelope must start with 0x02."""
        from spa_core.execution.eth_signer import sign_transaction
        raw = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        assert raw[0] == 0x02, f"Expected 0x02 type byte, got {raw[0]:#04x}"

    def test_deterministic_same_hash(self):
        """Two calls with the same inputs must produce the same raw bytes."""
        from spa_core.execution.eth_signer import sign_transaction
        raw1 = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        raw2 = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        assert raw1 == raw2, "sign_transaction must be deterministic"

    def test_accepts_0x_prefix_on_key(self):
        from spa_core.execution.eth_signer import sign_transaction
        raw_no_prefix = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        raw_with_prefix = sign_transaction(_PK1_WITH_PREFIX, _SAMPLE_TX)
        assert raw_no_prefix == raw_with_prefix

    def test_different_keys_produce_different_signatures(self):
        from spa_core.execution.eth_signer import sign_transaction
        raw1 = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        raw2 = sign_transaction(_PK2_NO_PREFIX, _SAMPLE_TX)
        assert raw1 != raw2

    def test_wrong_key_length_raises_value_error(self):
        from spa_core.execution.eth_signer import sign_transaction
        with pytest.raises(ValueError, match="64 hex chars"):
            sign_transaction("deadbeef", _SAMPLE_TX)

    def test_data_as_hex_string(self):
        """data field as 0x-prefixed hex string is accepted."""
        from spa_core.execution.eth_signer import sign_transaction
        tx = dict(_SAMPLE_TX, data="0x095ea7b3")
        raw = sign_transaction(_PK1_NO_PREFIX, tx)
        assert isinstance(raw, bytes)
        assert len(raw) > 20

    def test_signed_tx_is_decodable_by_eth_account(self):
        """eth_account should be able to recover the signer from the signed tx."""
        from spa_core.execution.eth_signer import sign_transaction
        from eth_account import Account
        raw = sign_transaction(_PK1_NO_PREFIX, _SAMPLE_TX)
        tx_hex = "0x" + raw.hex()
        recovered = Account.recover_transaction(tx_hex)
        assert recovered.lower() == _ADDR1.lower(), (
            f"Recovered signer {recovered} != expected {_ADDR1}"
        )


# ─── 3. sign_message ──────────────────────────────────────────────────────────

class TestSignMessage:
    def test_returns_hex_string(self):
        from spa_core.execution.eth_signer import sign_message
        sig = sign_message("hello SPA", _PK1_NO_PREFIX)
        assert isinstance(sig, str)
        assert sig.startswith("0x")

    def test_signature_length(self):
        """EIP-191 signature is 65 bytes = 130 hex chars + '0x' prefix."""
        from spa_core.execution.eth_signer import sign_message
        sig = sign_message("hello SPA", _PK1_NO_PREFIX)
        assert len(sig) == 132, f"Expected 132 chars (0x + 130), got {len(sig)}"

    def test_recoverable(self):
        """eth_account should recover the signer from the signature."""
        from spa_core.execution.eth_signer import sign_message
        from eth_account import Account
        from eth_account.messages import encode_defunct
        message = "test message for SPA v3.24"
        sig = sign_message(message, _PK1_NO_PREFIX)
        msg_obj = encode_defunct(text=message)
        recovered = Account.recover_message(msg_obj, signature=sig)
        assert recovered.lower() == _ADDR1.lower()

    def test_accepts_bytes_message(self):
        from spa_core.execution.eth_signer import sign_message
        sig = sign_message(b"\x00\x01\x02", _PK1_NO_PREFIX)
        assert sig.startswith("0x")

    def test_wrong_key_raises(self):
        from spa_core.execution.eth_signer import sign_message
        with pytest.raises(ValueError):
            sign_message("hello", "tooshort")


# ─── 4. keccak256 ─────────────────────────────────────────────────────────────

class TestKeccak256:
    def test_empty_bytes_known_hash(self):
        """keccak256(b'') = 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"""
        from spa_core.execution.eth_signer import keccak256
        result = keccak256(b"")
        expected = bytes.fromhex(
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
        )
        assert result == expected, f"keccak256(b'') mismatch: {result.hex()}"

    def test_returns_32_bytes(self):
        from spa_core.execution.eth_signer import keccak256
        assert len(keccak256(b"hello world")) == 32

    def test_known_vector(self):
        """keccak256('Transfer(address,address,uint256)') = 0xddf252ad..."""
        from spa_core.execution.eth_signer import keccak256
        selector_full = keccak256(b"Transfer(address,address,uint256)")
        # First 4 bytes = 0xddf252ad (ERC-20 Transfer selector)
        assert selector_full[:4].hex() == "ddf252ad"


# ─── 5. encode_function_call ──────────────────────────────────────────────────

class TestEncodeFunctionCall:
    def test_approve_selector(self):
        """ERC-20 approve(spender, amount) calldata."""
        from spa_core.execution.eth_signer import encode_function_call
        spender = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        amount = 1000 * 10 ** 6  # 1000 USDC (6 decimals)
        calldata = encode_function_call("095ea7b3", spender, amount)
        assert len(calldata) == 4 + 32 + 32  # selector + 2 × uint256 slots
        assert calldata[:4].hex() == "095ea7b3"

    def test_bad_selector_raises(self):
        from spa_core.execution.eth_signer import encode_function_call
        with pytest.raises(ValueError, match="4 bytes"):
            encode_function_call("0xdeadbeef00", 42)  # 5 bytes

    def test_unsupported_type_raises(self):
        from spa_core.execution.eth_signer import encode_function_call
        with pytest.raises(TypeError, match="unsupported type"):
            encode_function_call("095ea7b3", [1, 2, 3])  # list not supported

    def test_bool_encoding(self):
        from spa_core.execution.eth_signer import encode_function_call
        data = encode_function_call("12345678", True, False)
        # True → 0x0...01, False → 0x0...00
        assert data[4:36] == (1).to_bytes(32, "big")
        assert data[36:68] == (0).to_bytes(32, "big")
