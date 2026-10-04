"""capital_shadow.runbook — owner runbook generator (ADR-556 binding review, CRITICAL finding #1 /
HIGH finding #2 / HIGH finding #6).

The runbook is NEVER a signing payload. It never contains raw calldata or hex to paste, never a
key, never an instruction to automate submission. It contains a human-readable description of the
contract/method/selector/arguments — built ENTIRELY from the PINNED registry + the intent's own
declared fields, never from the simulation's own call (see the bug note below) — amount always
``OWNER_DECISION_REQUIRED``, the simulation evidence, prerequisites, abort criteria, the post-action
reconciliation procedure, the unwind procedure and kill actions. It expires in <= 1h
(:data:`contract.INTENT_TTL_PILOT_S`, measured from generation time, never wall-clock-recomputed
later). Generated ONLY for a ``MANUAL_PILOT_READY`` readiness state and a non-scenario intent — this
is unreachable today (four BLOCKS_ALL_PILOTS system blockers), by construction and by test.

**HIGH finding #2 (fixed here):** the previous implementation displayed the SIMULATION's own
``onBehalfOf``/``amount`` right next to the printed label ``OWNER_SAFE`` — but the simulation's
sender is a synthetic, NEVER-FUNDED, keyless address (``simulate.synthetic_sender``), not the
owner's real Safe, and its amount is whatever the simulator happened to run, not
``OWNER_DECISION_REQUIRED``. The only thing standing between that and an owner's hardware wallet was
a bare ``assert`` — stripped entirely under ``python -O``. This version builds every displayed
argument from the pinned registry + the intent, never touches the simulation's own call/args, and
replaces every such assert with an explicit :class:`RunbookRefused`.

**HIGH finding #6 (fixed here):** at most ONE outstanding owner action may exist per sleeve at a
time. ``generate`` refuses while an earlier one is still open (not EXPIRED-by-now / CANCELLED /
RECONCILED) and records the new one on the ledger (kind ``owner_action``) before returning text.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from spa_core.capital_shadow import contract, ledger, machine, tokens, verify
from spa_core.capital_shadow.keccak import selector as compute_selector


class RunbookRefused(Exception):
    """The sleeve is not MANUAL_PILOT_READY, the intent is a TEST_SCENARIO fixture or expired, the
    intent's own sleeve does not match the report it was evaluated for, an outstanding owner
    action already exists for this sleeve, or the rendered text would leak raw hex."""


def _readable_call(an_intent: dict, receiver_display: str) -> tuple:
    """``(contract_address, method_signature, selector, arg_lines_text)`` — built ENTIRELY from the
    pinned registry (``verify.expected_signature``/``expected_to_address``/``pinned_*_address``) and
    the intent's own declared fields. Never reads the simulation's own ``call``/``args`` (HIGH
    finding #2 — that was the SYNTHETIC sender's call, not what the owner would sign)."""
    sig = verify.expected_signature(an_intent)
    to_addr = verify.expected_to_address(an_intent)
    if sig is None or to_addr is None:
        return "UNKNOWN", "UNKNOWN", "UNKNOWN", "      - (no pinned registry entry for this action/venue)"
    selector_hex = compute_selector(sig)
    names = verify.ARG_NAMES_BY_SIGNATURE.get(sig, ())
    asset_addr = verify.pinned_asset_address(an_intent)
    venue_addr = verify.pinned_venue_address(an_intent)
    lines = []
    for name in names:
        if name in ("amount", "assets", "shares"):
            value = "OWNER_DECISION_REQUIRED"
        elif name in verify.RECEIVER_ARG_NAMES:
            value = receiver_display
        elif name == "spender":
            value = venue_addr or "UNKNOWN"
        elif name == "asset":
            value = asset_addr or "UNKNOWN"
        elif name == "referralCode":
            value = "0"
        else:
            value = "UNKNOWN"
        lines.append(f"      - {name}: {value}")
    return to_addr, sig, selector_hex, ("\n".join(lines) or "      - (none)")


def generate(report: dict, intent: dict, simulation: Optional[dict], *, data_dir: Optional[Path] = None,
            now: Optional[datetime] = None) -> Optional[str]:
    if report.get("readiness_state") != contract.R_MANUAL_PILOT_READY:
        raise RunbookRefused(f"sleeve {report.get('candidate_sleeve')!r} is "
                             f"{report.get('readiness_state')!r}, not MANUAL_PILOT_READY — no runbook")
    scenario = intent.get("scenario")
    if isinstance(scenario, str) and scenario.startswith(contract.SCENARIO_TEST_PREFIX):
        raise RunbookRefused("a TEST_SCENARIO intent never gets a real owner runbook (review #12)")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # review N3: a runbook is only ever generated for the SAME sleeve the report evaluated — a
    # cross-sleeve mixup (report for A, intent belonging to B) must refuse, never silently fall
    # back to whichever side happened to name a sleeve.
    intent_sleeve = intent.get("sleeve_id")
    report_sleeve = report.get("candidate_sleeve")
    if intent_sleeve != report_sleeve:
        raise RunbookRefused(f"intent.sleeve_id={intent_sleeve!r} != report.candidate_sleeve="
                             f"{report_sleeve!r} — refusing a cross-sleeve runbook")
    sleeve_id = report_sleeve
    intent_id = intent.get("intent_id")

    # review N3: re-issuing a runbook for an intent that has ALREADY expired is refused outright —
    # a new intent is required, never a runbook dressed up for a payload that can no longer be
    # validly signed anyway.
    if machine.is_expired(intent, now):
        raise RunbookRefused(f"intent {intent_id!r} expired at {intent.get('expires_at')!r} — a new intent is "
                             f"required, not a re-issued runbook")

    if data_dir is not None:
        data_dir = Path(data_dir)

    expires_at_dt = now + timedelta(seconds=contract.INTENT_TTL_PILOT_S)
    expires_at = expires_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    owner_safe = verify.configured_owner_safe(data_dir) if data_dir is not None else None
    receiver_display = (f"OWNER_SAFE (configured address: {owner_safe})" if owner_safe
                        else "OWNER_SAFE (NOT CONFIGURED)")

    contract_address, method_sig, selector_hex, arg_lines = _readable_call(intent, receiver_display)

    block = (simulation or {}).get("block") or {}
    witnesses = ", ".join(w for w in (block.get("operators") or [])) or "UNKNOWN"

    lines = [
        "SPA RM-LIVE-01 · OWNER PILOT RUNBOOK (manual, owner-executed only)",
        "=" * 70,
        f"generated_at:      {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"expires_at:        {expires_at}  (<= 1h from generation — re-run `verify` before signing "
        f"if past this)",
        f"sleeve:            {sleeve_id}",
        f"intent_id:         {intent_id}",
        f"real_capital_usd:  {contract.REAL_CAPITAL_USD}",
        f"authorization:     {contract.AUTHORIZATION_TEXT}",
        "",
        "WHAT THE OWNER WOULD BE SIGNING (human-readable — NOT a calldata payload):",
        f"  contract (pinned registry):  {contract_address}",
        f"  method:                       {method_sig}",
        f"  selector:                     {selector_hex}",
        f"  arguments:",
        arg_lines,
        f"  amount:                        OWNER_DECISION_REQUIRED",
        f"  receiver / onBehalfOf:         {receiver_display}",
        "",
        "SIMULATION EVIDENCE (SIMULATED_UNDER_ASSUMED_STATE — not proof of the real wallet state):",
        f"  pinned block number:          {block.get('number', 'UNKNOWN')}",
        f"  pinned block hash:            {block.get('hash', 'UNKNOWN')}",
        f"  witnessing RPC operators:     {witnesses}",
        f"  registry digest:              {tokens.registry_digest()}",
        "",
        "PREREQUISITES (owner must verify before signing):",
        "  1. Run: python -m spa_core.capital_shadow.verify --intent <id> --payload <wallet-shown-payload> "
        "--to-address <wallet-shown-target>",
        "  2. Confirm PASS, not ABORT, on the verify output.",
        "  3. Confirm the hardware wallet clear-signs contract + method + amount you intend.",
        "  4. Confirm kill switch is CLEAR and RiskPolicy verdict is PASS at the moment of signing.",
        "",
        "ABORT CRITERIA:",
        "  - verify reports ABORT for ANY reason.",
        "  - the wallet-displayed receiver is not your own Safe.",
        "  - more than 1h has elapsed since this runbook was generated.",
        "  - kill switch state is not CLEAR at signing time.",
        "",
        "POST-ACTION RECONCILIATION PROCEDURE:",
        "  1. Record the transaction hash.",
        "  2. Run the post-execution reconciler for this sleeve once the tx is included.",
        "  3. The sleeve remains AWAITING_RECONCILIATION until that reconciliation reports MATCHED.",
        "",
        "UNWIND PROCEDURE:",
        "  - A simulated WITHDRAW/REDEEM for this exact position has already passed with measured "
        "available liquidity >= 3x the position (unwind_path gate). Use the same manual, "
        "owner-signed process to exit.",
        "",
        "KILL ACTIONS:",
        "  - The automated kill switch (two-tier drawdown ladder) still applies at the account level; "
        "it cannot reach this manual pilot directly because the pilot is not under automated control.",
        "  - To abort a pending signature: simply do not sign. Nothing here submits anything automatically.",
    ]
    text = "\n".join(lines)

    # only three places may ever carry hex: the pinned contract address line, the selector line, and
    # the block-hash line; the arguments block is excluded from this scan entirely because
    # `_readable_call` builds it STRICTLY from the pinned registry (never the simulation's own
    # call) — it is trusted by construction, not by this check. Anything else leaking "0x" is raw
    # material this runbook must never show. Replaces the old bare `assert` (HIGH #2: silently
    # stripped under `python -O`) with an explicit refusal.
    _hex_allowed_markers = ("pinned block hash", "selector:", "contract (pinned registry):",
                            "receiver / onBehalfOf:")
    leaking = [ln for ln in lines if ln is not arg_lines and "0x" in ln
              and not any(marker in ln for marker in _hex_allowed_markers)]
    if leaking:
        raise RunbookRefused(f"runbook would leak raw hex outside the explicitly-allowed lines: {leaking!r}")

    if data_dir is not None and sleeve_id and intent_id:
        # HIGH finding #6 / review N3: the OUTSTANDING check and this append happen together,
        # under ONE lock acquisition (see ledger.open_owner_action_if_none_outstanding's own
        # docstring for the race this closes). Every ISSUANCE gets its own key — re-issuing for
        # the SAME intent is allowed (a new audit row, not a silent no-op); a DIFFERENT intent's
        # still-open action refuses here, as late as possible, so a refusal never leaves a
        # half-built runbook looking like it succeeded.
        try:
            ledger.open_owner_action_if_none_outstanding(data_dir, sleeve_id=sleeve_id, intent_id=intent_id,
                                                         block=block.get("number"), expires_at=expires_at, now=now)
        except ledger.OwnerActionAlreadyOpen as exc:
            raise RunbookRefused(str(exc)) from exc
    return text
