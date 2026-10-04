"""capital_shadow.verify — pre-sign owner verification (ADR-556 binding review, CRITICAL finding #1,
hardened further by the second independent re-review's MEDIUM finding N1).

``python -m spa_core.capital_shadow.verify --intent <id> --payload <what the wallet shows> \\
    --to-address <tx target> --value <wei> --operation <0|1> --chain-id <id>``.

Read-only: decodes the payload against the PINNED registry's own expected method for this intent's
action/venue (never the venue's bare name — see the bug note below) with STRICT calldata rules
(exact length, canonical words — N1c), diffs every field against the pinned registry / the intent's
own notional / the configured owner Safe, confirms the intent actually reached a point a human was
ever meant to act on (N1a), checks the freshness of every risk input file (N1b), checks expiry from
``now``, re-reads the CURRENT risk state (kill switch / derisk / RiskPolicy / depeg-in-band — N1d),
checks the wallet's own required fields (value/operation/chain_id — N1e), and — only once every
other check is clean — re-simulates the DECODED call from the Safe's own address. Any difference, or
anything this layer cannot prove, is an ABORT. Exit 0 on PASS, 2 on ABORT.

**The CRITICAL bug this replaces (reproduced 2026-10-04):** the previous implementation called
``abi.decode_call(payload_hex, [intent.get("instrument")])`` — ``instrument`` is a VENUE NAME
(e.g. ``"aave_v3"``), never a function signature, so ``decode_call`` always returned ``None`` and —
because a ``None`` decode added NO mismatch — a completely different method (e.g. a plain ERC-20
``transfer(attacker, 1e12)``) decoded to nothing, flagged nothing, and reached ``PASS``. Every one
of the gaps that bug exposed (receiver/target/asset/amount never compared, re-simulation on the
wrong sender, expiry never checked) is fixed here; see
``spa_core/tests/test_capital_shadow_owner_boundary.py`` for the reproduced-attack regression.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from spa_core.capital_shadow import contract, intent as intent_mod, ledger, machine, simulate, tokens
from spa_core.capital_shadow.keccak import selector as compute_selector

#: read-only configuration of the owner's Safe — env wins, else a (read-only) data file. Neither is
#: ever written by this layer; none configured today, by design, until the owner sets one up.
OWNER_SAFE_ENV = "SPA_OWNER_SAFE_ADDRESS"
OWNER_SAFE_FILE = "owner_safe.json"

#: a uint256 "infinite approval" — never acceptable on an APPROVE this layer verifies (mirrors
#: machine.policy_violation's own rule, applied here against the DECODED payload, not the simulation).
UNLIMITED_APPROVAL = 2 ** 256 - 1

#: review N1b: how stale a risk input file may be before verify refuses to trust it. Exposed so
#: readiness.py's `kill_switch_clear` gate (another agent's change) can reuse the SAME rule rather
#: than inventing a second freshness window that could silently drift from this one.
FRESHNESS_MAX_AGE_H = 26.0
#: review N1b: every file whose freshness gates a signature.
FRESHNESS_RELPATHS = ("kill_switch_status.json", "derisk_status.json", "current_positions.json")

#: review N1d: the stable asset's depeg price must stay within +/-0.5% of its peg (1.0) — same
#: order of magnitude as RiskPolicy's own tolerance for a "stable" asset; outside this is not a
#: stablecoin signature to trust, regardless of what the intent itself assumed at build time.
DEPEG_BAND = (0.995, 1.005)

#: review N1e: a Safe's `operation` field — 0 = CALL (every action this layer ever builds), 1 =
#: DELEGATECALL (never acceptable: it would run arbitrary code with the Safe's own storage/context).
SAFE_OPERATION_CALL = 0
SAFE_OPERATION_DELEGATECALL = 1

#: positional argument names for every signature this registry can produce — MUST match
#: simulate.py's own ``_supply_args``/``_withdraw_args``/``encode_action`` construction exactly, keyed
#: by the full signature (never by action_type alone: aave's and comet's supply/withdraw differ in
#: arg COUNT under the same action_type, and conflating them would silently misname an argument).
ARG_NAMES_BY_SIGNATURE = {
    "supply(address,uint256,address,uint16)": ("asset", "amount", "onBehalfOf", "referralCode"),
    "supply(address,uint256)": ("asset", "amount"),
    "withdraw(address,uint256,address)": ("asset", "amount", "to"),
    "withdraw(address,uint256)": ("asset", "amount"),
    "deposit(uint256,address)": ("assets", "receiver"),
    "redeem(uint256,address,address)": ("shares", "receiver", "owner"),
    "approve(address,uint256)": ("spender", "amount"),
}
#: the TYPE of each positional argument, same keys/order as ARG_NAMES_BY_SIGNATURE — needed for the
#: strict decoder's canonical-encoding checks (N1c).
ARG_TYPES_BY_SIGNATURE = {
    "supply(address,uint256,address,uint16)": ("address", "uint256", "address", "uint16"),
    "supply(address,uint256)": ("address", "uint256"),
    "withdraw(address,uint256,address)": ("address", "uint256", "address"),
    "withdraw(address,uint256)": ("address", "uint256"),
    "deposit(uint256,address)": ("uint256", "address"),
    "redeem(uint256,address,address)": ("uint256", "address", "address"),
    "approve(address,uint256)": ("address", "uint256"),
}
#: argument names that must equal the owner's own Safe — never the simulation's synthetic sender.
RECEIVER_ARG_NAMES = ("onBehalfOf", "to", "receiver", "owner")

_ACTION_METHOD_KEY = {
    contract.ACTION_SUPPLY: "supply", contract.ACTION_WITHDRAW: "withdraw",
    contract.ACTION_DEPOSIT_4626: "deposit", contract.ACTION_REDEEM_4626: "redeem",
}

_WORD = 32


# ── read-only helpers over the PINNED registry (never the simulation's own call) ───────────────────

def configured_owner_safe(data_dir: Path) -> Optional[str]:
    """Env (``SPA_OWNER_SAFE_ADDRESS``) wins; else ``data/capital_shadow/owner_safe.json``
    (``{"address": "0x..."}``), read-only. ``None`` when neither exists — today, always."""
    env_val = os.environ.get(OWNER_SAFE_ENV)
    if env_val:
        return env_val
    path = Path(data_dir) / contract.DATA_SUBDIR / OWNER_SAFE_FILE
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    addr = doc.get("address") if isinstance(doc, dict) else None
    return addr if isinstance(addr, str) and addr else None


def _venue(an_intent: dict) -> Optional[dict]:
    venue_name = an_intent.get("network_or_venue")
    return tokens.venue(venue_name) if isinstance(venue_name, str) else None


def pinned_asset_address(an_intent: dict) -> Optional[str]:
    """The underlying asset's pinned token address for this intent (never a slot/guess)."""
    ven = _venue(an_intent)
    if ven is None:
        return None
    tok = tokens.token(ven.get("chain_id"), an_intent.get("from_asset") or ven.get("asset"))
    return tok["address"] if tok else None


def pinned_venue_address(an_intent: dict) -> Optional[str]:
    ven = _venue(an_intent)
    return ven.get("address") if ven else None


def pinned_chain_id(an_intent: dict) -> Optional[int]:
    ven = _venue(an_intent)
    return ven.get("chain_id") if ven else None


def expected_signature(an_intent: dict) -> Optional[str]:
    """The ONE registry method signature this intent's action/venue expects — never the venue's
    bare NAME (the exact shape of the CRITICAL bug this module replaces)."""
    action = an_intent.get("action_type")
    if action == contract.ACTION_APPROVE:
        return "approve(address,uint256)"
    ven = _venue(an_intent)
    if ven is None:
        return None
    method_key = _ACTION_METHOD_KEY.get(action)
    if method_key is None:
        return None
    return (ven.get("methods") or {}).get(method_key)


def expected_to_address(an_intent: dict) -> Optional[str]:
    """The pinned contract the wallet's ``to`` field must equal: the token for APPROVE (you call
    ``approve`` ON the token), the venue itself for every other action."""
    if an_intent.get("action_type") == contract.ACTION_APPROVE:
        return pinned_asset_address(an_intent)
    return pinned_venue_address(an_intent)


def expected_amount_base_units(an_intent: dict) -> Optional[int]:
    """The intent's own ``notional``, converted to the asset's base units
    (``Decimal(notional) * 10**decimals`` — exact, never float rounding). A real
    ``simulate.to_base_units`` may land in ``simulate.py`` from a sibling change; this helper is a
    self-contained equivalent so ``verify`` never depends on that landing first."""
    ven = _venue(an_intent)
    notional = an_intent.get("notional")
    if ven is None or notional is None:
        return None
    tok = tokens.token(ven.get("chain_id"), an_intent.get("from_asset") or ven.get("asset"))
    if tok is None:
        return None
    try:
        return int(Decimal(str(notional)) * (Decimal(10) ** tok["decimals"]))
    except (ArithmeticError, ValueError, TypeError):
        return None


def _find_intent(data_dir: Path, intent_id: str) -> Optional[dict]:
    for e in ledger.read_all(data_dir):
        if e.get("kind") == "intent" and e.get("payload", {}).get("intent_id") == intent_id:
            return e["payload"]
    return None


# ── review N1b: freshness — exposed for readiness.py's kill_switch_clear gate to reuse ──────────

def freshness_check(data_dir: Path, relpath: str, now: datetime, *, max_age_h: float = FRESHNESS_MAX_AGE_H) -> dict:
    """``{"fresh": bool, "age_h": float|None, "reason": str|None}``. Reads ``<data_dir>/<relpath>``'s
    own ``generated_at`` — never a guess, never "no file means fresh". A missing file, missing or
    unparseable ``generated_at``, a future timestamp, or an age over ``max_age_h`` are all
    ``fresh=False`` with a named reason (fail-closed)."""
    path = Path(data_dir) / relpath
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"fresh": False, "age_h": None, "reason": f"{relpath} unavailable or unparseable"}
    generated_at = doc.get("generated_at") if isinstance(doc, dict) else None
    if not isinstance(generated_at, str):
        return {"fresh": False, "age_h": None, "reason": f"{relpath} has no generated_at"}
    try:
        v = generated_at[:-1] + "+00:00" if generated_at.endswith("Z") else generated_at
        ts = datetime.fromisoformat(v)
    except ValueError:
        return {"fresh": False, "age_h": None, "reason": f"{relpath}.generated_at unparseable: {generated_at!r}"}
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now_ = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_h = (now_ - ts).total_seconds() / 3600.0
    if age_h < 0:
        return {"fresh": False, "age_h": age_h, "reason": f"{relpath}.generated_at is in the future"}
    if age_h > max_age_h:
        return {"fresh": False, "age_h": age_h, "reason": f"{relpath} is {age_h:.1f}h old (> {max_age_h}h)"}
    return {"fresh": True, "age_h": age_h, "reason": None}


# ── review N1c: strict calldata decode (kept inside verify.py — never loosens abi.py's own rules) ──

def _parse_strict_types(signature: str) -> list:
    inner = signature[signature.index("(") + 1: signature.rindex(")")]
    return [t.strip() for t in inner.split(",") if t.strip()]


def strict_decode_call(payload_hex: str, signature: str) -> tuple:
    """Stricter than ``abi.decode_call``: refuses a payload whose length is not EXACTLY
    ``4 + 32*n`` bytes for the ``n`` arguments ``signature`` declares (no trailing bytes, nothing
    truncated), and refuses a non-canonical word — an ``address`` whose upper 12 bytes are not
    zero, or a ``bool`` whose word is not exactly 0 or 1. Returns ``(decoded_dict_or_None,
    reason_or_None)``; ``decoded_dict`` has the same ``{"signature", "args"}`` shape as
    ``abi.decode_call`` so callers can treat them interchangeably once decode succeeds."""
    if not isinstance(payload_hex, str) or not payload_hex.startswith(("0x", "0X")):
        return None, "payload is not 0x-hex"
    body_hex = payload_hex[2:]
    if len(body_hex) % 2:
        return None, "payload has an odd number of hex characters"
    try:
        raw = bytes.fromhex(body_hex)
    except ValueError:
        return None, "payload is not valid hex"
    if len(raw) < 4:
        return None, "payload shorter than a 4-byte selector"
    sel = "0x" + raw[:4].hex()
    expected_sel = compute_selector(signature)
    if sel != expected_sel:
        return None, (f"payload did not decode against the expected method {signature!r} — wrong "
                      f"selector/method or malformed calldata (payload selector={sel!r}, "
                      f"expected={expected_sel!r})")
    types = _parse_strict_types(signature)
    expected_len = 4 + _WORD * len(types)
    if len(raw) != expected_len:
        return None, (f"calldata length {len(raw)} != expected {expected_len} (4 + 32*{len(types)} for "
                      f"{signature!r}) — trailing or missing bytes")
    args = []
    for i, t in enumerate(types):
        word = raw[4 + i * _WORD: 4 + (i + 1) * _WORD]
        if t == "address":
            if word[:12] != b"\x00" * 12:
                return None, f"arg {i} ({t}): upper 12 bytes not zero — non-canonical address encoding"
            args.append("0x" + word[12:].hex())
        elif t == "bool":
            val = int.from_bytes(word, "big")
            if val not in (0, 1):
                return None, f"arg {i} ({t}): value {val} is not canonical 0/1"
            args.append(val != 0)
        elif t.startswith("uint"):
            args.append(int.from_bytes(word, "big"))
        elif t == "bytes32":
            args.append("0x" + word.hex())
        else:
            return None, f"arg {i}: unsupported type {t!r} for strict decode"
    return {"signature": signature, "args": args}, None


def _record_attempt(data_dir: Path, intent_id: str, to_address: Optional[str], result: dict, now: datetime) -> None:
    """Best-effort audit trail (kind ``owner_verification``) — never raises past a broken ledger:
    the verdict already computed above is the thing the caller (and the owner) must see regardless."""
    payload = {"intent_id": intent_id, "to_address": to_address, "verdict": result.get("verdict"),
              "mismatches": result.get("mismatches"), "executes": False, "real_capital_usd": 0}
    key = ("owner_verification", intent_id, now.strftime("%Y-%m-%dT%H:%M:%SZ"), f"{time.time():.6f}")
    try:
        ledger.append_idempotent(Path(data_dir), kind="owner_verification", key=key, payload=payload, now=now)
    except ledger.LedgerError:
        pass


def verify(intent_id: str, payload_hex: str, *, to_address: str, value: int, operation: int, chain_id: int,
           data_dir: Path, now: datetime, client: Any = None) -> dict:
    """Returns ``{"verdict": "PASS"|"ABORT", "mismatches": [...], ...}``. ``PASS`` requires EVERY
    check below to find nothing wrong — one mismatch anywhere is an ABORT, never a partial pass.

    ``value``/``operation``/``chain_id`` are the OTHER fields a Safe's signing wallet shows besides
    the target address and calldata (review N1e) — REQUIRED inputs, not optional extras: a verify
    that never looked at them could PASS a DELEGATECALL or a non-zero native-value transfer.
    """
    data_dir = Path(data_dir)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    mismatches: list = []

    an_intent = _find_intent(data_dir, intent_id)
    if an_intent is None:
        result = {"verdict": "ABORT", "mismatches": [f"intent {intent_id} not found on the ledger"],
                 "intent_id": intent_id, "to_address": to_address}
        _record_attempt(data_dir, intent_id, to_address, result, now)
        return result

    # (N1a) this intent must actually have REACHED a point a human was ever meant to act on: a
    # real (non-scenario) intent, cleared all the way to MANUAL_PILOT_READY/OWNER_GATE by the
    # machine, with a still-open, THIS-intent's owner_action (a runbook actually issued for it) —
    # never "verify whatever payload against whatever intent happens to be on the ledger".
    state = machine.current_state(data_dir, intent_id)
    if state not in (contract.S_MANUAL_PILOT_READY, contract.S_OWNER_GATE):
        mismatches.append(f"intent state is {state!r}, not MANUAL_PILOT_READY/OWNER_GATE — refusing to verify "
                          f"a payload for an intent that was never cleared to this point")
    if an_intent.get("scenario") != contract.SCENARIO_CURRENT:
        mismatches.append(f"intent scenario is {an_intent.get('scenario')!r}, not CURRENT_STATE — a "
                          f"TEST_SCENARIO/other intent is never something the owner should sign")
    sleeve_id = an_intent.get("sleeve_id")
    owner_action = ledger.outstanding_owner_action(data_dir, sleeve_id, now) if sleeve_id else None
    if owner_action is None or (owner_action.get("payload") or {}).get("intent_id") != intent_id:
        mismatches.append("no recorded, still-open owner_action (runbook) for THIS intent — verify is only "
                          "meaningful after a runbook was actually issued for it")

    # (a) an owner Safe must be configured — nothing here can verify a receiver that does not exist.
    owner_safe = configured_owner_safe(data_dir)
    if not owner_safe:
        mismatches.append("no owner Safe configured — cannot verify a receiver that does not exist")

    # (b) the wallet-shown tx TARGET must equal the PINNED registry address for this action/venue.
    expected_to = expected_to_address(an_intent)
    if expected_to is None:
        mismatches.append(f"no pinned registry address for venue {an_intent.get('network_or_venue')!r} / "
                          f"action {an_intent.get('action_type')!r}")
    elif not isinstance(to_address, str) or to_address.lower() != expected_to.lower():
        mismatches.append(f"to_address mismatch: wallet shows {to_address!r}, pinned registry expects "
                          f"{expected_to!r}")

    # (N1e) native value / Safe operation / chain_id — REQUIRED wallet fields, never optional.
    if value != 0:
        mismatches.append(f"tx value is {value!r}, must be 0 — this layer never moves native currency")
    if operation == SAFE_OPERATION_DELEGATECALL:
        mismatches.append("Safe operation is 1 (DELEGATECALL) — refused unconditionally; only 0 (CALL) is "
                          "ever acceptable")
    elif operation != SAFE_OPERATION_CALL:
        mismatches.append(f"Safe operation is {operation!r}, must be 0 (CALL)")
    expected_chain_id = pinned_chain_id(an_intent)
    if expected_chain_id is None or chain_id != expected_chain_id:
        mismatches.append(f"chain_id mismatch: wallet shows {chain_id!r}, venue expects {expected_chain_id!r}")

    # (c) decode the payload ONLY against the registry signature this action/venue expects — exact
    # selector match AND strict calldata (N1c: exact length, canonical words). This is the exact
    # line the CRITICAL bug got wrong (it passed the venue's NAME, never a signature).
    expected_sig = expected_signature(an_intent)
    decoded_named: dict = {}
    if expected_sig is None:
        mismatches.append(f"no expected method signature for action {an_intent.get('action_type')!r} on venue "
                          f"{an_intent.get('network_or_venue')!r}")
    else:
        decoded, decode_reason = strict_decode_call(payload_hex, expected_sig)
        if decoded is None:
            mismatches.append(decode_reason)
        else:
            names = ARG_NAMES_BY_SIGNATURE.get(expected_sig)
            args = decoded.get("args", [])
            if names is None or len(names) != len(args):
                mismatches.append(f"no named-argument mapping for signature {expected_sig!r} — refusing to "
                                  f"trust an unmapped decode")
            else:
                decoded_named = dict(zip(names, args))

    # (d) field by field, against the PINNED registry / the intent's own notional / the owner Safe —
    # never against the simulation's synthetic sender.
    if decoded_named:
        expected_amount = expected_amount_base_units(an_intent)
        expected_asset = pinned_asset_address(an_intent)
        expected_venue_addr = pinned_venue_address(an_intent)
        for amt_name in ("amount", "assets", "shares"):
            if amt_name in decoded_named:
                payload_amount = decoded_named[amt_name]
                if expected_amount is None or int(payload_amount) != expected_amount:
                    mismatches.append(f"{amt_name} mismatch: payload={payload_amount!r} "
                                      f"expected={expected_amount!r} (base units)")
        if "asset" in decoded_named:
            payload_asset = decoded_named["asset"]
            if expected_asset is None or payload_asset.lower() != expected_asset.lower():
                mismatches.append(f"asset mismatch: payload={payload_asset!r} expected={expected_asset!r}")
        for name in RECEIVER_ARG_NAMES:
            if name in decoded_named:
                payload_receiver = decoded_named[name]
                if not owner_safe or payload_receiver.lower() != owner_safe.lower():
                    mismatches.append(f"{name} mismatch: payload={payload_receiver!r}, must be the owner Safe "
                                      f"({owner_safe!r})")
        if an_intent.get("action_type") == contract.ACTION_APPROVE:
            if "spender" in decoded_named:
                payload_spender = decoded_named["spender"]
                if expected_venue_addr is None or payload_spender.lower() != expected_venue_addr.lower():
                    mismatches.append(f"spender mismatch: payload={payload_spender!r} "
                                      f"expected={expected_venue_addr!r}")
            amt = decoded_named.get("amount")
            if amt is not None and int(amt) == UNLIMITED_APPROVAL:
                mismatches.append("APPROVE requests UNLIMITED allowance — never acceptable; must equal the "
                                  "intent's own amount exactly")

    # (e) expiry computed from `now` every time, never from stored state.
    if machine.is_expired(an_intent, now):
        mismatches.append(f"intent {intent_id} expired at {an_intent.get('expires_at')!r} "
                          f"(now={now.isoformat()})")

    # (N1b) every risk input file must be FRESH — a stale file is not "probably still true".
    for relpath in FRESHNESS_RELPATHS:
        fr = freshness_check(data_dir, relpath, now)
        if not fr["fresh"]:
            mismatches.append(f"{relpath} is not fresh: {fr['reason']}")

    # (f) current risk state — ABSOLUTE, not merely "unchanged since the intent was built": kill
    # switch exactly CLEAR, derisk confirmed inactive, RiskPolicy PASS, depeg MEASURED AND within
    # band (N1d). Anything else aborts — an UNKNOWN here is never treated as safe.
    kill = intent_mod.read_kill_switch_state(data_dir)
    if not (kill["state"] == contract.MEASURED and kill.get("value") == "CLEAR"):
        mismatches.append(f"kill switch is not CLEAR: state={kill['state']!r} value={kill.get('value')!r}")
    derisk = intent_mod.read_derisk_state(data_dir)
    if not (derisk["state"] == contract.MEASURED and derisk.get("value") is False):
        mismatches.append(f"derisk is not confirmed inactive: state={derisk['state']!r} "
                          f"value={derisk.get('value')!r}")
    riskpolicy = intent_mod.read_riskpolicy_state(data_dir)
    rp_verdict = (riskpolicy.get("value") or {}).get("verdict") if riskpolicy["state"] == contract.MEASURED else None
    if rp_verdict != "PASS":
        mismatches.append(f"RiskPolicy verdict is not PASS: state={riskpolicy['state']!r} verdict={rp_verdict!r}")
    depeg = intent_mod.read_depeg_state(data_dir)
    if depeg["state"] != contract.MEASURED:
        mismatches.append(f"depeg is not MEASURED: state={depeg['state']!r} reason={depeg.get('reason')!r}")
    else:
        price = depeg.get("value")
        if not isinstance(price, (int, float)) or isinstance(price, bool) \
                or not (DEPEG_BAND[0] <= price <= DEPEG_BAND[1]):
            mismatches.append(f"depeg price {price!r} outside band {DEPEG_BAND} — not a stablecoin signature "
                              f"to trust")

    # defense in depth: did anything the ORIGINAL intent itself recorded drift since it was built?
    # (the absolute checks above are the real gate; this additionally catches e.g. a CIO
    # recommendation superseded or the book itself moving under the intent.)
    rc = machine.recheck(an_intent, data_dir, now)
    if rc["verdict"] is not None:
        mismatches.append(f"recheck verdict={rc['verdict']!r} mismatches={rc['mismatches']}")

    # (g) re-simulate the DECODED call from the owner's OWN Safe, at the CURRENT pinned block — never
    # the stored intent's synthetic sender. Only trusted if the simulator actually supports
    # overriding the sender; otherwise this is reported, never silently treated as a pass.
    if not mismatches and owner_safe:
        sim_params = inspect.signature(simulate.simulate_intent).parameters
        if "sender" in sim_params:
            try:
                sim_record = simulate.simulate_intent(an_intent, client=client,
                                                       now=now.strftime("%Y-%m-%dT%H:%M:%SZ"), sender=owner_safe)
            except Exception as exc:  # noqa: BLE001 — a crash in re-simulation is a mismatch, never a pass
                mismatches.append(f"re-simulation from the Safe raised: {exc!r}")
            else:
                if sim_record.get("result") != contract.SIM_PASS:
                    mismatches.append(f"re-simulation from the Safe is {sim_record.get('result')!r}, not PASS")
        else:
            mismatches.append("re-simulation from the Safe is unsupported: the simulator has no sender "
                              "override — cannot prove the call succeeds from the real signer, only from a "
                              "synthetic one")

    verdict = "ABORT" if mismatches else "PASS"
    result = {"verdict": verdict, "mismatches": mismatches, "intent_id": intent_id, "to_address": to_address}
    _record_attempt(data_dir, intent_id, to_address, result, now)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spa_core.capital_shadow.verify")
    parser.add_argument("--intent", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--to-address", required=True, help="the tx TARGET the wallet shows, before signing")
    parser.add_argument("--value", type=int, required=True, help="native-currency value the wallet shows; must be 0")
    parser.add_argument("--operation", type=int, required=True,
                        help="Safe operation the wallet shows; 0=CALL (only acceptable value), 1=DELEGATECALL")
    parser.add_argument("--chain-id", type=int, required=True, dest="chain_id",
                        help="chain id the wallet shows; must equal the venue's own chain")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    result = verify(args.intent, args.payload, to_address=args.to_address, value=args.value,
                    operation=args.operation, chain_id=args.chain_id, data_dir=Path(args.data_dir), now=now)
    print(f"VERDICT: {result['verdict']}")
    for m in result["mismatches"]:
        print(f"  MISMATCH: {m}")
    return contract.EXIT_OK if result["verdict"] == "PASS" else contract.EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
