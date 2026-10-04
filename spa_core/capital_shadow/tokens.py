"""spa_core/capital_shadow/tokens.py — pinned, PUBLIC on-chain registry for simulation (ADR-556).

Every address here is a public contract address — no secret material (invariant #7). Each token
declares the storage layout ``simulate.py`` needs to establish a balance/allowance by state override
(ADR-556 WP-S02/S03); each venue declares the methods it exposes. Nothing here calls the network — that
is ``rpc.py``'s job; ``simulate.py`` verifies these slots by READING BACK ``balanceOf``/``allowance`` at
simulation time, because a declared slot is a claim, not a proof (a mismatch is ``NOT_MEASURED``, never
silently trusted).

FiatToken v2.2 (USDC) packs its blacklist flag into the HIGH BIT of the balance storage word — an
override must never set that bit (:func:`balance_override_word` enforces this).

# LLM_FORBIDDEN — the registry is a frozen set of facts, not a judgement call.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from spa_core.capital_shadow.abi import encode_address, encode_uint
from spa_core.capital_shadow.keccak import keccak256

#: FiatTokenV2_2 reserves the top bit of the balance word for the blacklist flag (keep balance < 2**255).
MAX_SAFE_BALANCE = (1 << 255) - 1

TOKENS: dict = {
    1: {
        "USDC": {
            "symbol": "USDC",
            "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "decimals": 6,
            "impl": "FiatTokenV2_2",
            "balance_slot": 9,
            "allowance_slot": 10,
            "balance_high_bit_reserved": True,
        },
    },
}

#: kind in {"aave_pool", "comet", "erc4626", "permissioned"} — exactly the enum ADR-556 names.
VENUES: dict = {
    "aave_v3": {
        "name": "aave_v3", "chain_id": 1, "address": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "kind": "aave_pool", "asset": "USDC",
        "methods": {
            "supply": "supply(address,uint256,address,uint16)",
            "withdraw": "withdraw(address,uint256,address)",
        },
    },
    "compound_v3": {
        "name": "compound_v3", "chain_id": 1, "address": "0xc3d688B66703497DAA19211EEdff47f25384cdc3",
        "kind": "comet", "asset": "USDC",
        "methods": {
            "supply": "supply(address,uint256)",
            "withdraw": "withdraw(address,uint256)",
        },
    },
    "fluid_fusdc": {
        "name": "fluid_fusdc", "chain_id": 1, "address": "0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33",
        "kind": "erc4626", "asset": "USDC",
        "methods": {
            "deposit": "deposit(uint256,address)",
            "redeem": "redeem(uint256,address,address)",
            "previewDeposit": "previewDeposit(uint256)",
            "previewRedeem": "previewRedeem(uint256)",
            "convertToAssets": "convertToAssets(uint256)",
            "maxWithdraw": "maxWithdraw(address)",
            "asset": "asset()",
        },
    },
    "maple": {
        # permissioned=True ⇒ NOT_SIMULATABLE (a synthetic sender cannot pass its allow-list); no address
        # is pinned because no unpermissioned call path exists to verify one against.
        "name": "maple", "chain_id": 1, "address": None, "kind": "permissioned", "asset": "USDC", "methods": {},
    },
    "morpho_blue_base": {
        # chain 8453 (Base) — contract.RPC_OPERATORS declares operators for chain 1 ONLY, so pin_block()
        # already returns NOT_MEASURED ("no override-capable quorum declared for Base") before any address
        # would matter; no address is pinned here (see the capital_shadow report's "contract gaps").
        "name": "morpho_blue_base", "chain_id": 8453, "address": None, "kind": "erc4626", "asset": "USDC",
        "methods": {},
    },
}

PERMISSIONED_KINDS = frozenset({"permissioned"})


def token(chain_id: int, symbol: str) -> dict:
    return TOKENS.get(chain_id, {}).get(symbol)


def venue(name: str) -> dict:
    return VENUES.get(name)


def registry_digest() -> str:
    """Stable content digest of the pinned registry — any silent edit changes this."""
    blob = json.dumps({"tokens": TOKENS, "venues": VENUES}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── storage-slot derivation (Solidity's standard mapping layout) ───────────────────────────────────
def balance_slot(owner: str, base_slot: int) -> str:
    """Slot for ``mapping(address => uint256) balances[owner]`` declared at ``base_slot``."""
    key = encode_address(owner) + encode_uint(base_slot, 256)
    return "0x" + keccak256(key).hex()


def allowance_slot(owner: str, spender: str, base_slot: int) -> str:
    """Slot for ``allowed[owner][spender]`` at ``base_slot`` — ``keccak(spender . keccak(owner . base_slot))``
    (outer mapping key is ``owner``, inner/final key is ``spender`` — FiatTokenV2_2's declared layout)."""
    inner = keccak256(encode_address(owner) + encode_uint(base_slot, 256))
    return "0x" + keccak256(encode_address(spender) + inner).hex()


def balance_override_word(amount: int) -> str:
    """32-byte override value for a balance slot — refuses to ever set FiatTokenV2_2's high (blacklist) bit."""
    amount = int(amount)
    if amount < 0 or amount > MAX_SAFE_BALANCE:
        raise ValueError("balance override would set FiatTokenV2_2's high (blacklist) bit — refused")
    return "0x" + encode_uint(amount, 256).hex()


def allowance_override_word(amount: int) -> str:
    return "0x" + encode_uint(int(amount), 256).hex()


# ── review #4 (ADR-556 post-implementation audit): amounts were NEVER scaled by decimals ───────────
# ``CapitalActionIntent.notional`` is paired with ``notional_unit`` precisely so a caller can say WHICH
# unit it's in (ADR-556 WP-A01). Before this fix every caller did ``int(intent["notional"])`` straight
# into on-chain base units — "1000 USDC" silently simulated 1000 BASE units (0.001 USDC); a live
# fluid_fusdc DEPOSIT_4626 of nominal "1000" returned 820 shares instead of ~820,239,983,xxx, and
# unwind_probe's available/position ratio was inflated ~10^6x for the same reason. This is the ONE
# place that conversion happens — every caller (encode_action, the balance/allowance overrides,
# previewDeposit comparisons, unwind_probe) must route through this function, never re-implement it.
def to_base_units(notional, notional_unit, token: dict) -> int:
    """Convert ``(notional, notional_unit)`` to EXACT integer on-chain base units for ``token``.

    * ``notional_unit == "base_units"``: ``notional`` IS ALREADY base units — accepted only if it is
      (or is numerically equal to) a non-negative integer; a fractional base-unit amount is refused,
      never truncated.
    * ``notional_unit == token["symbol"]`` (e.g. ``"USDC"``): ``notional`` is HUMAN-readable — scaled by
      ``Decimal(str(notional)) * 10**decimals``; the scaled result must land EXACTLY on an integer (a
      human amount carrying more precision than the token supports is refused, never rounded).
    * anything else (missing/unrecognised ``notional_unit``) is refused rather than guessed — fail-closed,
      the same discipline as every other absent-observation path in this package.
    """
    if token is None:
        raise ValueError("to_base_units: unknown token (cannot determine decimals)")
    try:
        d = Decimal(str(notional))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"to_base_units: not a number: {notional!r}") from exc
    if d < 0:
        raise ValueError(f"to_base_units: negative notional {notional!r}")

    if notional_unit == "base_units":
        if d != d.to_integral_value():
            raise ValueError(f"to_base_units: base_units notional must be an integer, got {notional!r}")
        return int(d)

    symbol = token.get("symbol")
    if notional_unit == symbol:
        scaled = d * (Decimal(10) ** token["decimals"])
        if scaled != scaled.to_integral_value():
            raise ValueError(
                f"to_base_units: {notional!r} {notional_unit} has more precision than "
                f"{token['decimals']} decimals for {symbol!r}"
            )
        return int(scaled)

    raise ValueError(
        f"to_base_units: unrecognised notional_unit {notional_unit!r} for token {symbol!r} "
        f"(expected {symbol!r} for human units, or 'base_units')"
    )
