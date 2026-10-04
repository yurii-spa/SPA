"""spa_core/capital_shadow/simulate.py — read-only simulation of one CapitalActionIntent (ADR-556 WP-S02/S03).

Every record is labelled ``contract.SIM_LABEL`` ("SIMULATED_UNDER_ASSUMED_STATE") and carries the frozen
``contract.NOT_PROVEN`` list — this NEVER proves a real wallet's balance, a Safe's threshold, gas at
inclusion, MEV, oracle movement, or allow-list/KYC behaviour for the real sender (review #2). The sender
is a deterministic, NEVER-FUNDED synthetic address derived from the intent id; a real pilot runbook
names the owner's own Safe instead (review #1) — nothing produced here is a signing payload.

Design notes worth knowing before reading an output record (also reported as contract gaps upstream):

* ``tokens.py`` pins the UNDERLYING asset's (USDC) storage slots only. SUPPLY / DEPOSIT_4626 / APPROVE
  pull or set rights over that asset FROM the synthetic sender, so their balance/allowance can be
  established and VERIFIED by state override + read-back. WITHDRAW / REDEEM_4626 instead need the
  VENUE'S OWN position token (an aToken, a Comet account balance, or the vault's own ERC-20 shares) —
  no slot for that token is declared anywhere, so those two actions cannot get a funded synthetic
  sender; their "action_eth_call" / gas checks are honestly ``NOT_MEASURED`` rather than a misleading
  FAIL, and the informative signal for them is :func:`unwind_probe` (available on-chain liquidity vs the
  position) via the ``post_state`` check — exactly the unwind-path evidence review #7 asks for.
* Aave v3 reserves live in the aToken contract, not the Pool, and no aToken address is pinned in
  ``tokens.py`` — :func:`unwind_probe` on ``aave_v3`` is therefore ``NOT_MEASURED`` by the same honesty
  rule, not a fabricated number.

# LLM_FORBIDDEN — every check here is a deterministic read, never a judgement call.
"""
from __future__ import annotations

import datetime
from typing import Optional

from spa_core.capital_shadow import abi, contract, tokens
from spa_core.capital_shadow.keccak import keccak256
from spa_core.capital_shadow.rpc import RpcClient

#: no contract constant exists for this — documented here, enforced here (review #11: gas ceiling check).
GAS_CEILING = 600_000
#: ERC-4626 "returned shares vs previewDeposit at the same block" tolerance.
PREVIEW_TOLERANCE = 0.0001
#: review #7: unwind_path needs measured available liquidity >= 3x the position.
UNWIND_LIQUIDITY_MULTIPLE = 3
UINT256_MAX = (1 << 256) - 1

_ACTIONS_CALLABLE_BY_SYNTHETIC_SENDER = (contract.ACTION_SUPPLY, contract.ACTION_DEPOSIT_4626, contract.ACTION_APPROVE)


def synthetic_sender(intent_id: str) -> str:
    """Deterministic, NEVER-FUNDED sender derived from the intent id — never a real wallet (review #1/#2)."""
    digest = keccak256(str(intent_id).encode("utf-8"))
    return "0x" + digest[:20].hex()


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(name: str, state: str, detail: str) -> dict:
    return {"check": name, "state": state, "detail": detail}


def _overall_result(checks: list) -> str:
    states = [c["state"] for c in checks]
    if any(s == contract.SIM_FAIL for s in states):
        return contract.SIM_FAIL
    if any(s == contract.NOT_MEASURED for s in states):
        return contract.NOT_MEASURED
    if states and all(s == contract.SIM_PASS for s in states):
        return contract.SIM_PASS
    return contract.NOT_MEASURED  # empty checks is itself "nothing measured" — fail-closed


# ── WP-S03: build the call (never a signing payload) ───────────────────────────────────────────────
def _supply_args(ven: dict, asset_addr: Optional[str], amount: int, sender: str) -> list:
    if ven["kind"] == "aave_pool":
        return [{"name": "asset", "type": "address", "value": asset_addr},
                {"name": "amount", "type": "uint256", "value": amount},
                {"name": "onBehalfOf", "type": "address", "value": sender},
                {"name": "referralCode", "type": "uint16", "value": 0}]
    if ven["kind"] == "comet":
        return [{"name": "asset", "type": "address", "value": asset_addr},
                {"name": "amount", "type": "uint256", "value": amount}]
    raise ValueError(f"encode_action: SUPPLY not defined for venue kind {ven['kind']!r}")


def _withdraw_args(ven: dict, asset_addr: Optional[str], amount: int, sender: str) -> list:
    if ven["kind"] == "aave_pool":
        return [{"name": "asset", "type": "address", "value": asset_addr},
                {"name": "amount", "type": "uint256", "value": amount},
                {"name": "to", "type": "address", "value": sender}]
    if ven["kind"] == "comet":
        return [{"name": "asset", "type": "address", "value": asset_addr},
                {"name": "amount", "type": "uint256", "value": amount}]
    raise ValueError(f"encode_action: WITHDRAW not defined for venue kind {ven['kind']!r}")


def encode_action(intent: dict, *, sender: Optional[str] = None) -> dict:
    """``{"to","signature","selector","args":[{"name","type","value"}],"data"}`` — never calldata to sign.

    Uses the synthetic sender as receiver/onBehalfOf IN SIMULATION ONLY (review #1) UNLESS ``sender`` is
    given — e.g. ``verify.py`` re-simulating the decoded call from the OWNER'S Safe address before a
    pre-sign check (follow-up to review #1/#2): the embedded receiver/onBehalfOf/owner argument must then
    be the Safe, not the placeholder, or the re-simulation would prove nothing about the real call.
    ``sender``, when given, is used AS-IS (``simulate_intent`` is the one place that validates it).
    ``intent`` must carry a resolved ``chain_id`` (callers merge the venue's chain_id in before calling
    this for APPROVE).
    """
    action = intent["action_type"]
    sender = sender or synthetic_sender(intent["intent_id"])
    notional_unit = intent.get("notional_unit")

    if action == contract.ACTION_APPROVE:
        chain_id = intent["chain_id"]
        ven = tokens.venue(intent["network_or_venue"])
        if ven is None or not ven.get("address"):
            raise ValueError("encode_action: APPROVE needs a venue with a pinned address")
        tok = tokens.token(chain_id, intent.get("from_asset") or ven.get("asset"))
        if tok is None:
            raise ValueError("encode_action: APPROVE needs a known token")
        amount = tokens.to_base_units(intent["notional"], notional_unit, tok)  # review #4: scale by decimals
        signature = "approve(address,uint256)"
        args = [{"name": "spender", "type": "address", "value": ven["address"]},
                {"name": "amount", "type": "uint256", "value": amount}]
        data = abi.function_call(signature, [a["value"] for a in args])
        return {"to": tok["address"], "signature": signature, "selector": data[:10], "args": args, "data": data}

    ven = tokens.venue(intent["network_or_venue"])
    if ven is None or not ven.get("address"):
        raise ValueError(f"encode_action: unknown or address-less venue {intent.get('network_or_venue')!r}")
    tok = tokens.token(ven["chain_id"], intent.get("from_asset") or ven["asset"])
    if tok is None:
        raise ValueError(f"encode_action: asset not in the pinned token registry for venue {ven['name']!r}")
    amount = tokens.to_base_units(intent["notional"], notional_unit, tok)  # review #4: scale by decimals
    asset_addr = tok["address"]

    if action == contract.ACTION_SUPPLY:
        args = _supply_args(ven, asset_addr, amount, sender)
        signature = ven["methods"]["supply"]
    elif action == contract.ACTION_WITHDRAW:
        args = _withdraw_args(ven, asset_addr, amount, sender)
        signature = ven["methods"]["withdraw"]
    elif action == contract.ACTION_DEPOSIT_4626:
        args = [{"name": "assets", "type": "uint256", "value": amount},
                {"name": "receiver", "type": "address", "value": sender}]
        signature = ven["methods"]["deposit"]
    elif action == contract.ACTION_REDEEM_4626:
        args = [{"name": "shares", "type": "uint256", "value": amount},
                {"name": "receiver", "type": "address", "value": sender},
                {"name": "owner", "type": "address", "value": sender}]
        signature = ven["methods"]["redeem"]
    else:
        raise ValueError(f"encode_action: unsupported action_type {action!r}")

    data = abi.function_call(signature, [a["value"] for a in args])
    return {"to": ven["address"], "signature": signature, "selector": data[:10], "args": args, "data": data}


# ── record builders for the paths that never reach a chain read ───────────────────────────────────
def _empty_block() -> dict:
    return {"number": None, "hash": None, "operators": []}


def _skeleton(intent: dict, simulated_at: str, chain_id, sender: str, checks: list, result: str,
              post_state: dict, call: Optional[dict] = None, block: Optional[dict] = None,
              gas_estimate: Optional[dict] = None, revert_reason: Optional[str] = None,
              security_events: Optional[list] = None, sender_kind: str = "synthetic") -> dict:
    return {
        "schema": contract.SCHEMA_SIMULATION,
        "intent_id": intent.get("intent_id"),
        "label": contract.SIM_LABEL,
        "not_proven": list(contract.NOT_PROVEN),
        "trust_model": contract.TRUST_MODEL,
        "chain_id": chain_id,
        "block": block or _empty_block(),
        "sender": sender,
        "sender_kind": sender_kind,
        "checks": checks,
        "call": call or {"signature": None, "selector": None, "args_readable": None},
        "gas_estimate": gas_estimate or contract.absent(contract.NOT_MEASURED, reason="not attempted",
                                                         source="simulate", as_of=simulated_at),
        "result": result,
        "revert_reason": revert_reason,
        "post_state": post_state,
        "security_events": list(security_events or []),
        "simulated_at": simulated_at,
    }


def _balance_readback_check(q: dict, expected: int) -> dict:
    if q.get("state") == contract.MEASURED and not q.get("revert"):
        reported = abi.decode_uint256(q["result"])
        if reported == expected:
            return _check("balance_override_readback", contract.SIM_PASS, f"balanceOf(sender) == {expected}")
        return _check("balance_override_readback", contract.NOT_MEASURED,
                      "slot layout unverified: balanceOf mismatch after override")
    return _check("balance_override_readback", contract.NOT_MEASURED,
                  q.get("reason", "slot layout unverified: readback not measured"))


def _allowance_readback_check(q: dict, expected: int) -> dict:
    if q.get("state") == contract.MEASURED and not q.get("revert"):
        reported = abi.decode_uint256(q["result"])
        if reported == expected:
            return _check("allowance_override_readback", contract.SIM_PASS, f"allowance(sender,spender) == {expected}")
        return _check("allowance_override_readback", contract.NOT_MEASURED,
                      "slot layout unverified: allowance mismatch after override")
    return _check("allowance_override_readback", contract.NOT_MEASURED,
                  q.get("reason", "slot layout unverified: readback not measured"))


def _deposit_post_state_impl(cl: RpcClient, ven: dict, amount: int, action_result_hex, block_number) -> dict:
    preview_data = abi.function_call(ven["methods"]["previewDeposit"], [amount])
    pq = cl.quorum("eth_call", [{"to": ven["address"], "data": preview_data}], block_number)
    if pq.get("state") != contract.MEASURED or pq.get("revert"):
        return {"check": "shares_vs_preview", "state": contract.NOT_MEASURED,
                "detail": pq.get("reason", "previewDeposit not measured"),
                "shares_returned": None, "preview_deposit": None}
    preview_shares = abi.decode_uint256(pq["result"])
    if not action_result_hex:
        return {"check": "shares_vs_preview", "state": contract.NOT_MEASURED,
                "detail": "deposit() returned no value (not measured or reverted) — nothing to compare",
                "shares_returned": None, "preview_deposit": preview_shares}
    returned_shares = abi.decode_uint256(action_result_hex)
    within = (returned_shares == 0) if preview_shares == 0 else (
        abs(returned_shares - preview_shares) / preview_shares <= PREVIEW_TOLERANCE)
    return {"check": "shares_vs_preview", "state": contract.SIM_PASS if within else contract.SIM_FAIL,
            "detail": f"returned={returned_shares} preview={preview_shares} tolerance={PREVIEW_TOLERANCE}",
            "shares_returned": returned_shares, "preview_deposit": preview_shares}


# ── WP-A05-adjacent: the available-liquidity / unwind-capacity probe (review #7) ────────────────────
def unwind_probe(venue_name: str, position_assets_base_units: int, *, client: RpcClient) -> dict:
    """``{state, available_liquidity (cell), ratio, detail}`` — PASS needs available >= 3x the position.

    "Available liquidity" is read where the asset actually sits: the Comet contract itself for
    ``compound_v3``, the vault itself for an ERC-4626 venue. For ``aave_v3`` the reserve sits in the
    aToken contract, whose address is NOT in the pinned registry (a named contract gap) — NOT_MEASURED,
    never a guessed number.
    """
    ven = tokens.venue(venue_name)
    if ven is None:
        return {"state": contract.NOT_MEASURED, "reason": f"unknown venue {venue_name!r}",
                "available_liquidity": None, "ratio": None, "detail": f"unknown venue {venue_name!r}"}
    if ven["kind"] == "permissioned":
        return {"state": contract.SIM_NOT_SIMULATABLE, "available_liquidity": None, "ratio": None,
                "detail": "permissioned venue — not simulatable"}
    if ven["kind"] == "aave_pool":
        return {"state": contract.NOT_MEASURED, "available_liquidity": None, "ratio": None,
                "detail": "aToken address not declared in the pinned registry — Aave v3 reserves live in "
                          "the aToken contract, not the Pool (contract gap, not a measurement)"}
    if not ven.get("address"):
        return {"state": contract.NOT_MEASURED, "available_liquidity": None, "ratio": None,
                "detail": f"no address pinned for venue {venue_name!r}"}

    tok = tokens.token(ven["chain_id"], ven["asset"])
    if tok is None:
        return {"state": contract.NOT_MEASURED, "available_liquidity": None, "ratio": None,
                "detail": "asset not in the pinned token registry"}

    pinned = client.pin_block()
    if pinned.get("state") != contract.MEASURED:
        return {"state": contract.NOT_MEASURED, "available_liquidity": None, "ratio": None,
                "detail": pinned.get("reason", "block not pinned")}

    data = abi.function_call("balanceOf(address)", [ven["address"]])
    q = client.quorum("eth_call", [{"to": tok["address"], "data": data}], pinned["number"])
    if q.get("state") != contract.MEASURED or q.get("revert"):
        return {"state": contract.NOT_MEASURED, "available_liquidity": None, "ratio": None,
                "detail": q.get("reason", "liquidity not measured")}

    available = abi.decode_uint256(q["result"])
    position = int(position_assets_base_units)
    ratio = (available / position) if position else None
    passed = position > 0 and available >= UNWIND_LIQUIDITY_MULTIPLE * position
    cell = contract.measured(available, unit="base_units", source="balanceOf(address) quorum",
                              as_of=None, n=len(q.get("operators", [])))
    return {"state": contract.SIM_PASS if passed else contract.SIM_FAIL, "available_liquidity": cell,
            "ratio": ratio, "detail": f"available={available} need>={UNWIND_LIQUIDITY_MULTIPLE}x{position}"}


# ── WP-A05 forward reconciliation (ADR-556 binding review #4) ──────────────────────────────────────
# Added for the forward-test reconciler in reconcile.py: both functions take an EXPLICIT, REQUIRED
# ``client`` (never default-constructed) so a caller can inject a fake in tests, or a real
# ``RpcClient`` pinned at whatever block is current when the forward pass runs — always LATER than
# the original simulation's block, never the same client/pin reused. Neither function changes any
# existing behaviour above; both are pure additions.

def preview_deposit_at(venue_name: str, amount_base_units: int, *, client: RpcClient) -> dict:
    """Re-reads ERC-4626 ``previewDeposit(amount)`` at ``client``'s CURRENT pinned block (a forward
    read, never the original simulation's block). ``{state, preview_shares, block, code_present,
    asset_ok, reason}`` — ``NOT_MEASURED`` (never a guess) when the venue isn't a previewable vault,
    the block can't be pinned, or either call fails."""
    ven = tokens.venue(venue_name)
    if ven is None or ven.get("kind") != "erc4626" or not ven.get("address") \
            or "previewDeposit" not in ven.get("methods", {}):
        return {"state": contract.NOT_MEASURED, "preview_shares": None, "block": None, "code_present": None,
                "asset_ok": None, "reason": f"venue {venue_name!r} is not a previewable ERC-4626 vault"}
    pinned = client.pin_block()
    if pinned.get("state") != contract.MEASURED:
        return {"state": contract.NOT_MEASURED, "preview_shares": None, "block": None, "code_present": None,
                "asset_ok": None, "reason": pinned.get("reason", "block not pinned")}
    block_number = pinned["number"]

    code_q = client.quorum("eth_getCode", [ven["address"]], block_number)
    code_present = (code_q.get("state") == contract.MEASURED and not code_q.get("revert")
                    and code_q.get("result") not in (None, "0x"))

    # review #9: "some address came back" is not a check — asset_ok must mean the vault's asset()
    # equals the PINNED REGISTRY token address for this venue (case-insensitive), the same bar
    # simulate_intent's own "venue_asset_matches_token" check holds the first simulation to.
    asset_ok = None
    if "asset" in ven.get("methods", {}):
        expected_tok = tokens.token(ven["chain_id"], ven.get("asset"))
        asset_data = abi.function_call(ven["methods"]["asset"], [])
        asset_q = client.quorum("eth_call", [{"to": ven["address"], "data": asset_data}], block_number)
        if asset_q.get("state") == contract.MEASURED and not asset_q.get("revert"):
            try:
                reported_addr = abi.decode_address(asset_q["result"])
                asset_ok = expected_tok is not None and reported_addr.lower() == expected_tok["address"].lower()
            except (ValueError, IndexError):
                asset_ok = False

    preview_data = abi.function_call(ven["methods"]["previewDeposit"], [int(amount_base_units)])
    pq = client.quorum("eth_call", [{"to": ven["address"], "data": preview_data}], block_number)
    if pq.get("state") != contract.MEASURED or pq.get("revert"):
        return {"state": contract.NOT_MEASURED, "preview_shares": None, "block": block_number,
                "code_present": code_present, "asset_ok": asset_ok,
                "reason": pq.get("reason", "previewDeposit not measured at the new block")}
    return {"state": contract.MEASURED, "preview_shares": abi.decode_uint256(pq["result"]), "block": block_number,
            "code_present": code_present, "asset_ok": asset_ok, "reason": None}


def reverify_venue_at_current_block(venue_name: str, asset_symbol: Optional[str], *, client: RpcClient) -> dict:
    """For actions with no observable position-token delta (SUPPLY/WITHDRAW on aave/compound): the
    POSITION can't be re-read (no slot declared, same honesty rule as :func:`unwind_probe`), but the
    venue's chain id, contract code and the asset's ``decimals()`` CAN be — proving identity hasn't
    silently changed, even when the position itself stays ``NOT_MEASURED``.
    ``{state, block, chain_ok, code_ok, decimals_ok, reason}``."""
    ven = tokens.venue(venue_name)
    if ven is None:
        return {"state": contract.NOT_MEASURED, "block": None, "chain_ok": None, "code_ok": None,
                "decimals_ok": None, "reason": f"unknown venue {venue_name!r}"}
    pinned = client.pin_block()
    if pinned.get("state") != contract.MEASURED:
        return {"state": contract.NOT_MEASURED, "block": None, "chain_ok": None, "code_ok": None,
                "decimals_ok": None, "reason": pinned.get("reason", "block not pinned")}
    block_number = pinned["number"]

    chain_q = client.quorum("eth_chainId", [], None)
    chain_ok = chain_q.get("state") == contract.MEASURED and int(chain_q["result"], 16) == ven["chain_id"]

    code_ok = None
    if ven.get("address"):
        code_q = client.quorum("eth_getCode", [ven["address"]], block_number)
        code_ok = (code_q.get("state") == contract.MEASURED and not code_q.get("revert")
                  and code_q.get("result") not in (None, "0x"))

    decimals_ok = None
    tok = tokens.token(ven["chain_id"], asset_symbol) if asset_symbol else None
    if tok is not None:
        dec_data = abi.function_call("decimals()", [])
        dec_q = client.quorum("eth_call", [{"to": tok["address"], "data": dec_data}], block_number)
        if dec_q.get("state") == contract.MEASURED and not dec_q.get("revert"):
            decimals_ok = abi.decode_uint256(dec_q["result"]) == tok["decimals"]

    state = contract.MEASURED if (chain_ok and code_ok) else contract.NOT_MEASURED
    reason = None if state == contract.MEASURED else "chain id or contract code not confirmed at the new block"
    return {"state": state, "block": block_number, "chain_ok": chain_ok, "code_ok": code_ok,
           "decimals_ok": decimals_ok, "reason": reason}


# ── WP-S02/S03: the full intent simulation ─────────────────────────────────────────────────────────
def simulate_intent(intent: dict, *, client: Optional[RpcClient] = None, now: Optional[str] = None,
                    sender: Optional[str] = None) -> dict:
    """Simulate one :data:`contract.INTENT_FIELDS`-shaped intent. Never signs, never sends, never holds
    a key. Returns a ``contract.SCHEMA_SIMULATION`` record with every key the contract names, plus
    ``sender_kind``.

    ``sender``: by default the simulation uses a deterministic, NEVER-FUNDED synthetic address derived
    from the intent id (``sender_kind: "synthetic"``). ``verify.py``'s pre-sign check instead needs to
    re-simulate the DECODED call from the OWNER'S own Safe address (ADR-556 review #1's "a pilot needs a
    pre-sign re-simulation from the real Safe") — pass that address here and the record's
    ``sender_kind`` becomes ``"owner_safe"``. The balance/allowance state OVERRIDE still applies to that
    address the same way it does for the synthetic one: it lets the call be simulated, it does NOT prove
    the Safe's real on-chain balance/allowance/nonce — those remain in ``not_proven`` either way. Never a
    key, never a signature; ``sender`` is a plain public address like any other.
    """
    intent_id = intent["intent_id"]
    action = intent["action_type"]
    simulated_at = now or _utcnow()
    if sender is not None:
        if not abi.is_checksummed_address(sender):
            raise ValueError(
                f"simulate_intent: sender override must be a checksummable 20-byte 0x address, got {sender!r}"
            )
        sender_value, sender_kind = sender, "owner_safe"
    else:
        sender_value, sender_kind = synthetic_sender(intent_id), "synthetic"

    if action == contract.ACTION_NO_ACTION:
        checks = [_check("no_action", contract.SIM_PASS, "intent is NO_ACTION — nothing to simulate")]
        return _skeleton(intent, simulated_at, intent.get("chain_id"), sender_value, checks, contract.SIM_PASS,
                         {"check": "no_action", "state": contract.SIM_PASS}, sender_kind=sender_kind)

    if action == contract.ACTION_SPOT_ORDER:
        checks = [_check("venue_kind", contract.NOT_MEASURED,
                         "SPOT_ORDER is simulated by exchange_sim.simulate_order, not simulate_intent")]
        return _skeleton(intent, simulated_at, intent.get("chain_id"), sender_value, checks, contract.NOT_MEASURED,
                         {"check": "spot_order", "state": contract.NOT_MEASURED}, sender_kind=sender_kind)

    venue_name = intent.get("network_or_venue")
    ven = tokens.venue(venue_name) if isinstance(venue_name, str) else None
    if ven is None:
        checks = [_check("venue_lookup", contract.NOT_MEASURED, f"unknown venue {venue_name!r}")]
        return _skeleton(intent, simulated_at, None, sender_value, checks, contract.NOT_MEASURED,
                         {"check": "venue_lookup", "state": contract.NOT_MEASURED}, sender_kind=sender_kind)

    if ven["kind"] in tokens.PERMISSIONED_KINDS or venue_name in contract.PERMISSIONED_VENUES:
        checks = [_check("permissioned_venue", contract.SIM_NOT_SIMULATABLE,
                         f"{ven['name']} is permissioned — a synthetic sender cannot pass its allow-list")]
        return _skeleton(intent, simulated_at, ven.get("chain_id"), sender_value, checks,
                         contract.SIM_NOT_SIMULATABLE, {"check": "permissioned", "state": contract.SIM_NOT_SIMULATABLE},
                         sender_kind=sender_kind)

    chain_id = ven["chain_id"]
    cl = client or RpcClient(chain_id=chain_id)

    pinned = cl.pin_block()
    if pinned.get("state") != contract.MEASURED:
        checks = [_check("block_pin", contract.NOT_MEASURED, pinned.get("reason", "block not pinned"))]
        return _skeleton(intent, simulated_at, chain_id, sender_value, checks, contract.NOT_MEASURED,
                         {"check": "block_pin", "state": contract.NOT_MEASURED},
                         security_events=cl.security_events, sender_kind=sender_kind)
    block_number = pinned["number"]

    if not ven.get("address"):
        checks = [_check("venue_address", contract.NOT_MEASURED, f"no address pinned for venue {venue_name!r}")]
        return _skeleton(intent, simulated_at, chain_id, sender_value, checks, contract.NOT_MEASURED,
                         {"check": "venue_address", "state": contract.NOT_MEASURED},
                         block={"number": pinned["number"], "hash": pinned["hash"], "operators": pinned["operators"]},
                         security_events=cl.security_events, sender_kind=sender_kind)

    checks: list = []
    # SUPPLY/DEPOSIT_4626 PULL the underlying asset from the sender (transferFrom) and so need both a
    # funded balance AND a pre-existing allowance; APPROVE needs neither (it only WRITES an allowance,
    # it consumes no balance and no pre-existing allowance) but can still be called by an empty sender.
    needs_balance_override = action in (contract.ACTION_SUPPLY, contract.ACTION_DEPOSIT_4626)
    attempt_action_call = action in _ACTIONS_CALLABLE_BY_SYNTHETIC_SENDER  # SUPPLY / DEPOSIT_4626 / APPROVE
    tok = tokens.token(chain_id, intent.get("from_asset") or ven["asset"])

    # review #4: notional MUST be scaled by the token's decimals before it is used as on-chain base
    # units — "1000 USDC" is NOT 1000 base units. A scaling failure (unknown token, non-integral
    # precision, negative, unrecognised notional_unit) is a deterministic input defect, so it is a
    # named FAIL, not NOT_MEASURED (we know exactly why this can't proceed; nothing is unmeasurable).
    try:
        amount = tokens.to_base_units(intent["notional"], intent.get("notional_unit"), tok)
    except ValueError as exc:
        checks = [_check("notional_scaling", contract.SIM_FAIL, str(exc))]
        return _skeleton(intent, simulated_at, chain_id, sender_value, checks, contract.SIM_FAIL,
                         {"check": "notional_scaling", "state": contract.SIM_FAIL},
                         block={"number": pinned["number"], "hash": pinned["hash"], "operators": pinned["operators"]},
                         security_events=cl.security_events, sender_kind=sender_kind)

    # 1. chain_id matches
    chain_q = cl.quorum("eth_chainId", [], None)
    if chain_q.get("state") == contract.MEASURED:
        reported = int(chain_q["result"], 16)
        checks.append(_check("chain_id", contract.SIM_PASS if reported == chain_id else contract.SIM_FAIL,
                             f"expected {chain_id}, reported {reported}"))
    else:
        checks.append(_check("chain_id", contract.NOT_MEASURED, chain_q.get("reason", "chain id not measured")))

    # 2. code at instrument
    code_q = cl.quorum("eth_getCode", [ven["address"]], block_number)
    if code_q.get("state") == contract.MEASURED:
        result = code_q.get("result")
        has_code = isinstance(result, str) and result.lower() not in ("0x", "0x0", "")
        nbytes = max(0, (len(result) - 2) // 2) if isinstance(result, str) else 0
        checks.append(_check("code_at_instrument", contract.SIM_PASS if has_code else contract.SIM_FAIL,
                             f"eth_getCode byte-length={nbytes}"))
    else:
        checks.append(_check("code_at_instrument", contract.NOT_MEASURED, code_q.get("reason", "code not measured")))

    # 3. token decimals == registry
    if tok is None:
        checks.append(_check("token_decimals", contract.NOT_MEASURED, "asset not in the pinned token registry"))
    else:
        dec_q = cl.quorum("eth_call", [{"to": tok["address"], "data": abi.function_call("decimals()", [])}],
                          block_number)
        if dec_q.get("state") == contract.MEASURED and not dec_q.get("revert"):
            reported_dec = abi.decode_uint256(dec_q["result"])
            checks.append(_check("token_decimals",
                                 contract.SIM_PASS if reported_dec == tok["decimals"] else contract.SIM_FAIL,
                                 f"registry={tok['decimals']} reported={reported_dec}"))
        else:
            checks.append(_check("token_decimals", contract.NOT_MEASURED, dec_q.get("reason", "decimals not measured")))

    # 4. venue asset == token
    if ven["kind"] == "erc4626" and "asset" in ven.get("methods", {}):
        asset_q = cl.quorum("eth_call", [{"to": ven["address"], "data": abi.function_call(ven["methods"]["asset"], [])}],
                           block_number)
        if asset_q.get("state") == contract.MEASURED and not asset_q.get("revert"):
            reported_addr = abi.decode_address(asset_q["result"]).lower()
            expected_addr = (tok or {}).get("address", "").lower()
            checks.append(_check("venue_asset_matches_token",
                                 contract.SIM_PASS if reported_addr == expected_addr else contract.SIM_FAIL,
                                 f"vault.asset()={reported_addr} expected={expected_addr}"))
        else:
            checks.append(_check("venue_asset_matches_token", contract.NOT_MEASURED,
                                 asset_q.get("reason", "asset() not measured")))
    else:
        ok = tok is not None and ven.get("asset") == (intent.get("from_asset") or ven.get("asset"))
        checks.append(_check("venue_asset_matches_token", contract.SIM_PASS if ok else contract.SIM_FAIL,
                             f"registry venue.asset={ven.get('asset')!r}"))

    # 5/6. balance + allowance override read-back
    overrides: dict = {}
    if needs_balance_override and tok is not None:
        # review #1-followup: the override applies to WHICHEVER sender is in play (synthetic or the
        # owner's Safe) — it lets the call be simulated either way, and proves neither address's REAL
        # balance/allowance/nonce (that stays in not_proven regardless of sender_kind).
        bslot = tokens.balance_slot(sender_value, tok["balance_slot"])
        overrides.setdefault(tok["address"], {"stateDiff": {}})["stateDiff"][bslot] = tokens.balance_override_word(amount)
        balof_data = abi.function_call("balanceOf(address)", [sender_value])
        bq = cl.quorum("eth_call", [{"to": tok["address"], "data": balof_data}, overrides], block_number)
        checks.append(_balance_readback_check(bq, amount))

        aslot = tokens.allowance_slot(sender_value, ven["address"], tok["allowance_slot"])
        overrides[tok["address"]]["stateDiff"][aslot] = tokens.allowance_override_word(amount)
        allow_data = abi.function_call("allowance(address,address)", [sender_value, ven["address"]])
        aq = cl.quorum("eth_call", [{"to": tok["address"], "data": allow_data}, overrides], block_number)
        checks.append(_allowance_readback_check(aq, amount))
    elif needs_balance_override:
        checks.append(_check("balance_override_readback", contract.NOT_MEASURED,
                             "asset not in the pinned token registry"))
        checks.append(_check("allowance_override_readback", contract.NOT_MEASURED,
                             "asset not in the pinned token registry"))
    elif action == contract.ACTION_APPROVE:
        # genuinely N/A, not "tried and failed to measure": approve() consumes no balance and no
        # pre-existing allowance, so no override check applies — nothing is appended here. Padding
        # this with a NOT_MEASURED entry would conflate "doesn't apply" with "couldn't measure" and
        # would make APPROVE structurally unable to ever reach SIM_PASS (contract.py's result rule
        # treats ANY NOT_MEASURED check as NOT_MEASURED overall unless something else already FAILs).
        pass
    else:
        # WITHDRAW/REDEEM_4626: the position-token slot (aToken / Comet balance / vault shares) is a
        # REAL, named gap (see the module docstring) — this one check genuinely could not be measured,
        # so it IS appended and it DOES keep these two action types out of SIM_PASS by construction
        # (fail-closed: this layer cannot prove the pull-side works without a declared slot). The
        # allowance check is simply N/A here (WITHDRAW/REDEEM do not spend an allowance) and is
        # therefore omitted, not padded.
        checks.append(_check("balance_override_readback", contract.NOT_MEASURED,
                             "no declared storage slot for the venue's own position token (aToken / Comet "
                             "balance / vault shares) — the pinned registry declares only the underlying "
                             "asset's slots"))

    intent_for_encode = dict(intent)
    intent_for_encode["chain_id"] = chain_id
    try:
        encoded = encode_action(intent_for_encode, sender=sender_value)
    except ValueError as exc:
        checks.append(_check("encode_action", contract.SIM_FAIL, str(exc)))
        encoded = {"to": ven.get("address"), "signature": None, "selector": None, "args": [], "data": None}

    gas_estimate_cell = contract.absent(contract.NOT_MEASURED, reason="not attempted",
                                        source="eth_estimateGas quorum", as_of=simulated_at)
    revert_reason = None
    post_state = {"check": "unassigned", "state": contract.NOT_MEASURED}

    if attempt_action_call and encoded.get("data"):
        tx = {"to": encoded["to"], "from": sender_value, "data": encoded["data"]}
        call_params = [tx, overrides] if overrides else [tx]

        action_q = cl.quorum("eth_call", call_params, block_number)
        action_result = None
        if action_q.get("state") == contract.MEASURED and not action_q.get("revert"):
            checks.append(_check("action_eth_call", contract.SIM_PASS, "no revert"))
            action_result = action_q.get("result")
        elif action_q.get("revert"):
            revert_reason = abi.decode_revert_reason(action_q.get("revert_data")) or str(action_q.get("revert_data"))
            checks.append(_check("action_eth_call", contract.SIM_FAIL, f"revert: {revert_reason}"))
        else:
            checks.append(_check("action_eth_call", contract.NOT_MEASURED,
                                 action_q.get("reason", "action call not measured")))

        gas_q = cl.quorum("eth_estimateGas", call_params, block_number)
        if gas_q.get("state") == contract.MEASURED and not gas_q.get("revert"):
            gas_val = int(gas_q["result"], 16)
            gas_estimate_cell = contract.measured(gas_val, unit="gas", source="eth_estimateGas quorum",
                                                  as_of=simulated_at, n=len(gas_q.get("operators", [])))
            checks.append(_check("eth_estimateGas", contract.SIM_PASS, f"gas={gas_val}"))
            checks.append(_check("gas_ceiling", contract.SIM_PASS if gas_val <= GAS_CEILING else contract.SIM_FAIL,
                                 f"{gas_val} <= {GAS_CEILING}"))
        elif gas_q.get("revert"):
            checks.append(_check("eth_estimateGas", contract.SIM_FAIL, "estimateGas reverted"))
            checks.append(_check("gas_ceiling", contract.NOT_MEASURED, "no estimate (revert)"))
            gas_estimate_cell = contract.absent(contract.NOT_MEASURED, reason="estimateGas reverted",
                                                source="eth_estimateGas quorum", as_of=simulated_at)
        else:
            checks.append(_check("eth_estimateGas", contract.NOT_MEASURED, gas_q.get("reason", "not measured")))
            checks.append(_check("gas_ceiling", contract.NOT_MEASURED, "no estimate"))
            gas_estimate_cell = contract.absent(contract.NOT_MEASURED, reason=gas_q.get("reason", "not measured"),
                                                source="eth_estimateGas quorum", as_of=simulated_at)

        if action == contract.ACTION_APPROVE:
            is_unlimited = amount == UINT256_MAX
            state = contract.SIM_FAIL if is_unlimited else contract.SIM_PASS
            detail = "excessive allowance" if is_unlimited else f"amount == notional ({amount})"
            checks.append(_check("approve_amount_bounded", state, detail))
            post_state = {"check": "approve_amount", "state": state, "detail": detail}
        elif action == contract.ACTION_DEPOSIT_4626:
            post_state = _deposit_post_state_impl(cl, ven, amount, action_result, block_number)
            checks.append(_check("post_state", post_state["state"], post_state.get("detail", "")))
        else:  # SUPPLY
            ok = action_q.get("state") == contract.MEASURED and not action_q.get("revert")
            measured = action_q.get("state") == contract.MEASURED
            state = contract.SIM_PASS if ok else (contract.SIM_FAIL if measured else contract.NOT_MEASURED)
            detail = ("Aave/Comet post-state is call success + revert-free; no on-chain position token is "
                      "readable without a declared slot")
            post_state = {"check": "call_success", "state": state, "detail": detail}
            checks.append(_check("post_state", state, detail))
    else:
        checks.append(_check("action_eth_call", contract.NOT_MEASURED,
                             "not attempted: WITHDRAW/REDEEM need the venue's own position token, whose "
                             "storage slot is not declared in the pinned registry"))
        checks.append(_check("eth_estimateGas", contract.NOT_MEASURED, "not attempted for the same reason"))
        checks.append(_check("gas_ceiling", contract.NOT_MEASURED, "no estimate"))
        probe = unwind_probe(ven["name"], amount, client=cl)
        post_state = {"check": "unwind_path", "state": probe["state"],
                     "detail": probe.get("detail", probe.get("reason", "")),
                     "available_liquidity": probe.get("available_liquidity"), "ratio": probe.get("ratio")}
        checks.append(_check("post_state", post_state["state"], post_state.get("detail", "")))

    result = _overall_result(checks)
    call_block = {"signature": encoded.get("signature"), "selector": encoded.get("selector"),
                 "args_readable": ", ".join(f"{a['name']}={a['value']}" for a in encoded.get("args", []))}

    return _skeleton(intent, simulated_at, chain_id, sender_value, checks, result, post_state, call=call_block,
                     block={"number": pinned["number"], "hash": pinned["hash"], "operators": pinned["operators"]},
                     gas_estimate=gas_estimate_cell, revert_reason=revert_reason, security_events=cl.security_events,
                     sender_kind=sender_kind)
