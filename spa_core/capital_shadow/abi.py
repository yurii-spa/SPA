"""spa_core/capital_shadow/abi.py — stdlib ABI encode/decode for the static types this package touches.

Only the types ``capital_shadow`` venues actually use: ``address``, ``uint256``, ``uint16``, ``bool``,
``bytes32`` — plus decoding a single returned ``uint256`` / ``bool`` / ``address`` / ``string`` and the
standard ``Error(string)`` revert payload (selector ``0x08c379a0``). No ``eth_abi`` import at runtime
(invariant #4); cross-checked against ``eth_abi`` in tests when that package happens to be importable.

# LLM_FORBIDDEN — ABI encoding is a deterministic bijection, not a judgement call.
"""
from __future__ import annotations

from typing import Optional

from spa_core.capital_shadow.keccak import keccak256, selector

_WORD = 32
ERROR_STRING_SELECTOR = "0x08c379a0"


def _parse_types(signature: str) -> list:
    """The comma-separated argument types out of ``name(type1,type2)``; ``()`` yields ``[]``."""
    inner = signature[signature.index("(") + 1: signature.rindex(")")]
    return [t.strip() for t in inner.split(",") if t.strip()]


def _hexbody(data) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if not isinstance(data, str):
        raise TypeError(f"abi: expected a 0x-hex string or bytes, got {type(data).__name__}")
    return bytes.fromhex(data[2:] if data.startswith(("0x", "0X")) else data)


# ── EIP-55 checksum (needed to validate a caller-supplied sender override — e.g. verify.py's owner
# Safe address — is a real 20-byte address and not a typo, before it is ever used in a simulation) ──
def to_checksum_address(address: str) -> str:
    """The EIP-55 mixed-case checksum encoding of a 20-byte hex address."""
    body = address.lower().replace("0x", "", 1) if address.lower().startswith("0x") else address.lower()
    if len(body) != 40 or any(c not in "0123456789abcdef" for c in body):
        raise ValueError(f"not a 20-byte hex address: {address!r}")
    hash_hex = keccak256(body.encode("ascii")).hex()
    out = [c.upper() if c.isalpha() and int(h, 16) >= 8 else c for c, h in zip(body, hash_hex)]
    return "0x" + "".join(out)


def is_checksummed_address(address) -> bool:
    """True iff ``address`` is a syntactically valid 20-byte ``0x`` address AND — if it mixes case —
    matches its own EIP-55 checksum. All-lowercase or all-uppercase hex is accepted as "no checksum
    was encoded" (EIP-55's own leniency); a MIXED-case address that does not match its checksum
    (a typo'd address is overwhelmingly likely to land here) is rejected."""
    if not isinstance(address, str) or not address.startswith("0x"):
        return False
    body = address[2:]
    if len(body) != 40 or any(c not in "0123456789abcdefABCDEF" for c in body):
        return False
    if body == body.lower() or body == body.upper():
        return True
    try:
        return to_checksum_address(address) == address
    except ValueError:
        return False


# ── encoders (static types only — every type this package's signatures use) ────────────────────────
def encode_address(value: str) -> bytes:
    v = value.lower().replace("0x", "")
    if len(v) != 40:
        raise ValueError(f"not a 20-byte address: {value!r}")
    return bytes(12) + bytes.fromhex(v)


def encode_uint(value: int, bits: int = 256) -> bytes:
    value = int(value)
    if value < 0 or value >= (1 << bits):
        raise ValueError(f"uint{bits} out of range: {value}")
    return value.to_bytes(_WORD, "big")


def encode_bool(value: bool) -> bytes:
    return encode_uint(1 if value else 0, 256)


def encode_bytes32(value) -> bytes:
    b = _hexbody(value) if isinstance(value, str) else bytes(value)
    if len(b) > 32:
        raise ValueError("bytes32 overflow")
    return b + bytes(32 - len(b))


_ENCODERS = {
    "address": encode_address,
    "uint256": lambda v: encode_uint(v, 256),
    "uint16": lambda v: encode_uint(v, 16),
    "bool": encode_bool,
    "bytes32": encode_bytes32,
}


def encode_args(types: list, values: list) -> bytes:
    if len(types) != len(values):
        raise ValueError(f"abi: {len(types)} types but {len(values)} values")
    out = bytearray()
    for t, v in zip(types, values):
        enc = _ENCODERS.get(t)
        if enc is None:
            raise ValueError(f"unsupported static ABI type for capital_shadow: {t!r}")
        out += enc(v)
    return bytes(out)


def function_call(signature: str, args: list) -> str:
    """0x-hex calldata for ``name(type,...)`` applied to positional ``args`` — selector + encoded body."""
    types = _parse_types(signature)
    body = encode_args(types, list(args))
    return selector(signature) + body.hex()


# ── decoders ─────────────────────────────────────────────────────────────────────────────────────
def _word(data, index: int) -> bytes:
    raw = _hexbody(data)
    start = index * _WORD
    chunk = raw[start:start + _WORD]
    if len(chunk) < _WORD:
        raise ValueError(f"abi: truncated return data, wanted word {index}")
    return chunk


def decode_uint256(data) -> int:
    return int.from_bytes(_word(data, 0), "big")


def decode_bool(data) -> bool:
    return decode_uint256(data) != 0


def decode_address(data) -> str:
    return "0x" + _word(data, 0)[-20:].hex()


def decode_string(data) -> str:
    """Head-tail ABI string ``[offset][length][bytes...]`` — the shape of a single dynamic return."""
    raw = _hexbody(data)
    if len(raw) < 2 * _WORD:
        raise ValueError("abi: truncated dynamic string")
    length = int.from_bytes(raw[_WORD:2 * _WORD], "big")
    start = 2 * _WORD
    return raw[start:start + length].decode("utf-8", errors="replace")


def decode_revert_reason(data) -> Optional[str]:
    """Decode a standard ``Error(string)`` revert payload (``0x08c379a0...``); ``None`` if not that shape."""
    if not isinstance(data, str) or not data.lower().startswith(ERROR_STRING_SELECTOR):
        return None
    try:
        return decode_string("0x" + data[len(ERROR_STRING_SELECTOR):])
    except Exception:  # noqa: BLE001 — an unparseable revert body is reported raw by the caller, not here
        return None


def decode_call(data: str, signatures: list) -> Optional[dict]:
    """Match calldata's 4-byte selector against known ``signatures`` (static args only); used by ``verify``."""
    if not isinstance(data, str) or not data.startswith("0x") or len(data) < 10:
        return None
    sel = data[:10].lower()
    for sig in signatures:
        if selector(sig) != sel:
            continue
        types = _parse_types(sig)
        body = data[10:]
        args = []
        for i, t in enumerate(types):
            word_hex = body[i * 64:(i + 1) * 64]
            if len(word_hex) < 64:
                return None
            word = "0x" + word_hex
            if t == "address":
                args.append(decode_address(word))
            elif t.startswith("uint"):
                args.append(decode_uint256(word))
            elif t == "bool":
                args.append(decode_bool(word))
            elif t == "bytes32":
                args.append(word)
            else:
                return None
        return {"signature": sig, "args": args}
    return None
