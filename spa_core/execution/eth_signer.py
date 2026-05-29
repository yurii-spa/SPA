"""
eth_signer.py — Minimal EIP-1559 transaction signer for SPA.

Uses ``eth_account`` (https://github.com/ethereum/eth-account) for all
cryptographic operations (ECDSA / secp256k1 / Keccak-256).  The previous
hand-rolled implementation has been replaced to eliminate the risk of a
silent bug in bespoke cryptography code that handles real private keys.

Requires:  eth-account>=0.10.0  (already in requirements.txt).

Public API (preserved from the previous implementation)
--------------------------------------------------------
sign_transaction(private_key_hex, tx_dict) -> bytes
    Build + sign an EIP-1559 (type-2) transaction.  Returns raw tx bytes.

get_address_from_private_key(private_key_hex) -> str
    Derive the checksummed ``0x...`` Ethereum address from a hex private key.

sign_message(message, private_key_hex) -> str
    Sign an Ethereum prefixed message (EIP-191).  Returns 0x-prefixed hex
    signature string (65 bytes = r + s + v).

encode_function_call(selector_hex, *args) -> bytes
    ABI-encode a function call (uint256 / address / bool args only — enough
    for ERC-20 approve + Aave / Compound supply / withdraw).

keccak256(data) -> bytes
    Return the 32-byte Ethereum keccak-256 hash of *data*.

get_nonce(address, rpc_url) -> int
    eth_getTransactionCount("pending").

estimate_gas(tx_dict, rpc_url) -> int
    eth_estimateGas.

get_base_fee(rpc_url) -> int
    Latest block baseFeePerGas (wei).

send_raw_transaction(signed_tx_hex, rpc_url) -> str
    eth_sendRawTransaction → tx hash string.

Sprint v3.24 — replaced bespoke ECDSA/Keccak with eth_account.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


# ─── eth_account lazy loader ──────────────────────────────────────────────────

def _get_account():
    """Lazy-import eth_account.Account.

    Returns the ``Account`` class (``eth_account.Account``).

    Raises:
        ImportError: If eth_account is not installed.
            Install with: pip install eth-account>=0.10.0
    """
    try:
        from eth_account import Account  # type: ignore
        return Account
    except ImportError as exc:
        raise ImportError(
            "eth_signer requires the 'eth-account' package. "
            "Install it with: pip install eth-account>=0.10.0"
        ) from exc


# ─── Keccak-256 via eth_hash (bundled with eth_account) ───────────────────────

def keccak256(data: bytes) -> bytes:
    """Return the 32-byte Ethereum keccak-256 hash of *data*.

    Delegates to ``eth_hash.auto.keccak`` which is bundled with eth_account
    and uses the fastest available backend (pysha3 > pycryptodome > pure Python).
    """
    try:
        from eth_hash.auto import keccak  # type: ignore
        return keccak(data)
    except ImportError:
        # Fallback: use eth_account's internal keccak
        from eth_account._utils.signing import keccak as _keccak  # type: ignore
        return _keccak(primitive=data)


# ─── Address derivation ───────────────────────────────────────────────────────

def get_address_from_private_key(private_key_hex: str) -> str:
    """Derive the Ethereum address (checksummed, 0x-prefixed) from a hex private key.

    Args:
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).

    Returns:
        EIP-55 checksummed ``0x...`` address string.

    Raises:
        ValueError: If the key length is wrong or not valid hex.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex.lstrip("0x") if private_key_hex.startswith("0x") else private_key_hex
    if len(pk_hex) != 64:
        raise ValueError(
            f"Private key must be 64 hex chars (0x prefix optional); "
            f"got length {len(pk_hex)}"
        )
    Account = _get_account()
    normalised = "0x" + pk_hex
    return Account.from_key(normalised).address


# ─── EIP-1559 transaction signing ─────────────────────────────────────────────

def sign_transaction(private_key_hex: str, tx_dict: dict) -> bytes:
    """Build and sign an EIP-1559 (type-2) transaction.

    Delegates to ``eth_account.Account.sign_transaction`` which uses
    battle-tested RFC-6979 deterministic ECDSA on secp256k1.

    Args:
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).
        tx_dict: Must contain:
            ``to``                  → ``0x...`` address string
            ``data``                 → ``0x...`` hex string or ``bytes``
            ``value``                → int (wei); defaults to 0
            ``nonce``                → int
            ``chainId``              → int
            ``maxFeePerGas``         → int (wei)
            ``maxPriorityFeePerGas`` → int (wei)
            ``gas``                  → int (gas limit)

    Returns:
        Raw signed transaction bytes (EIP-2718 envelope, starts with 0x02).

    Raises:
        ValueError: If the private key is malformed.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex.lstrip("0x") if private_key_hex.startswith("0x") else private_key_hex
    if len(pk_hex) != 64:
        raise ValueError(
            f"Private key must be 64 hex chars; got length {len(pk_hex)}"
        )
    normalised_pk = "0x" + pk_hex

    # Normalise data field
    data_raw = tx_dict.get("data", b"")
    if isinstance(data_raw, (bytes, bytearray)):
        data_field: str | bytes = bytes(data_raw)
    else:
        data_field = str(data_raw)

    # Build a clean EIP-1559 tx dict that eth_account accepts
    tx = {
        "to":                   tx_dict["to"],
        "value":                int(tx_dict.get("value", 0)),
        "gas":                  int(tx_dict["gas"]),
        "maxFeePerGas":         int(tx_dict["maxFeePerGas"]),
        "maxPriorityFeePerGas": int(tx_dict["maxPriorityFeePerGas"]),
        "nonce":                int(tx_dict["nonce"]),
        "chainId":              int(tx_dict["chainId"]),
        "data":                 data_field,
        "type":                 2,
    }

    Account = _get_account()
    signed = Account.sign_transaction(tx, private_key=normalised_pk)

    # rawTransaction attribute may differ between eth_account versions
    raw = getattr(signed, "rawTransaction", None)
    if raw is None:
        raw = getattr(signed, "raw_transaction", None)
    if raw is None:
        raise RuntimeError("Signed tx missing rawTransaction attribute ℔ unexpected eth_account version")
    return bytes(raw)


# ─── Message signing (EIP-191) ────────────────────────────────────────────────

def sign_message(message: str | bytes, private_key_hex: str) -> str:
    """Sign an Ethereum prefixed message (EIP-191 personal_sign).

    Wraps ``message`` in the standard Ethereum prefix
    ``"\\x19Ethereum Signed Message:\\n<len>"`` before signing.

    Args:
        message: The message payload — str (UTF-8 encoded) or raw bytes.
        private_key_hex: 64-hex-char private key (``0x`` prefix optional).

    Returns:
        0x-prefixed hex signature string (65 bytes: r + s + v).

    Raises:
        ValueError: If the private key is malformed.
        ImportError: If eth_account is not installed.
    """
    pk_hex = private_key_hex.lstrip("0x") if private_key_hex.startswith("0x") else private_key_hex
    if len(pk_hex) != 64:
        raise ValueError(
            f"Private key must be 64 hex chars; got length {len(pk_hex)}"
        )
    normalised_pk = "0x" + pk_hex

    from eth_account.messages import encode_defunct  # type: ignore

    if isinstance(message, str):
        msg = encode_defunct(text=message)
    else:
        msg = encode_defunct(message)

    Account = _get_account()
    signed = Account.sign_message(msg, private_key=normalised_pk)
    return "0x" + signed.signature.hex()


# ─── ABI encoding ─────────────────────────────────────────────────────────────

def encode_function_call(selector_hex: str, *args: Any) -> bytes:
    """ABI-encode a Solidity function call for uint256 / address / bool args.

    *selector_hex*: 4-byte function selector as ``0xAABBCCDD@` or ``AABBCCDD``.
    *args*: each must be one of:
        - ``int``  → encoded as uint256 (big-endian, 32 bytes)
        - ``str`` starting with ``"0x"`` → treated as an address (20-byte,
          zero-padded to 32 bytes)
        - ``bool`` → encoded as uint256 (0 or 1)

    Returns raw calldata bytes (selector + ABI-encoded args).
    """
    sel = bytes.fromhex((selector_hex.lstrip("0x"))
    if len(sel) != 4:
        raise ValueError(f"Selector must be exactly 4 bytes; got {len(sel)}")
    parts = [sel]
    for i, arg in enumerate(args):
        if isinstance(arg, bool):
            parts.append((1 if arg else 0).to_bytes(32, "big"))
        elif isinstance(arg, int):
            if arg < 0 or arg.bit_length() > 256:
                raise ValueError(
                    f"arg[{i}] = {arg!r}: uint256 must be in [0, 2**256)"
                )
            parts.append(arg.to_bytes(32, "big"))
        elif isinstance(arg, str) and arg.startswith("0x"):
            cleaned = arg[2:].lower()
            if len(cleaned) > 40:
                raise ValueError(
                    f"arg[{i}] address too long: {arg!r}"
                )
            parts.append(bytes.fromhex(cleaned.rjust(40, "0")).rjust(32, b"\x00"))
        else:
            raise TypeError(
                f"arg[{i}] = {arg!r}: unsupported type {type(arg).__name__}. "
                "encode_function_call supports int, bool, and '0x...' address strings."
            )
    return b"".join(parts)


# ─── JSON-RPC helpers ─────────────────────────────────────────────────────────

_RPC_TIMEOUT = 8.0


def _rpc_call(rpc_url: str, method: str, params: list, timeout: float = _RPC_TIMEOUT) -> Any:
    """Post a JSON-RPC call and return the ``result`` field.

    Raises ``RuntimeError`` on HTTP error, JSON-RPC error, or missing result.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{method}: HTTP failure ℔ {exc}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"{method}: malformed JSON ℔ {exc}") from exc

    if "error" in parsed:
        raise RuntimeError(f"{method}: RPC error — {parsed['error']}")
    if "result" not in parsed:
        raise RuntimeError(f"{method}: missing result in {parsed!r}")
    return parsed["result"]


def get_nonce(address: str, rpc_url: str) -> int:
    """Return the pending transaction count (nonce) for *address*."""
    result = _rpc_call(rpc_url, "eth_getTransactionCount", [address, "pending"])
    return int(result, 16)


def get_base_fee(rpc_url: str) -> int:
    """Return the baseFeePerGas of the latest block (wei)."""
    block = _rpc_call(rpc_url, "eth_getBlockByNumber", ["latest", False])
    if not isinstance(block, dict) or "baseFeePerGas" not in block:
        raise RuntimeError(
            f"get_base_fee: no baseFeePerGas in block response: {block!r}"
        )
    return int(block["baseFeePerGas"], 16)


def estimate_gas(tx_dict: dict, rpc_url: str) -> int:
    """Call ``eth_estimateGas`` for *tx_dict*.  Returns gas as int."""
    rpc_tx: dict[str, Any] = {}
    for k, v in tx_dict.items():
        if isinstance(v, int):
            rpc_tx[k] = "0x" + format(v, "x")
        elif isinstance(v, bytes):
            rpc_tx[k] = "0x" + v.hex()
        else:
            rpc_tx[k] = v
    result = _rpc_call(rpc_url, "eth_estimateGas", [rpc_tx])
    return int(result, 16)


def send_raw_transaction(signed_tx_hex: str, rpc_url: str) -> str:
    """Broadcast *signed_tx_hex* via ``eth_sendRawTransaction``.

    *signed_tx_hex* must include the ``0x`` prefix.

    Returns the transaction hash string (``0x...``).
    """
    result = _rpc_call(rpc_url, "eth_sendRawTransaction", [signed_tx_hex])
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError(
            f"eth_sendRawTransaction returned unexpected result: {result!r}"
        )
    return result
