"""capital_shadow.machine — WP-A04 deterministic state machine (ADR-556).

No transition leads to execution. ``OWNER_GATE`` is terminal for the machine: crossing it is an
owner act outside this system. Every legal transition appends exactly one evidence record to the
ledger; a repeated transition is idempotent; an illegal one is refused — loudly, never silently
clamped to something "close enough".

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.capital_shadow import contract, ledger
from spa_core.capital_shadow.intent import build_risk_snapshot, book_digest_and_asof, risk_blockers, \
    _SLEEVE_SOURCES, is_test_scenario


class IllegalTransition(Exception):
    """``to_state`` is not reachable from the intent's current state (or the scenario ceiling)."""


class IntentExpired(Exception):
    """``now`` is past ``expires_at`` — the caller must acknowledge via an explicit EXPIRED
    transition rather than being silently redirected."""


def _parse_ts(value: str) -> datetime:
    v = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(intent: dict, now: datetime) -> bool:
    """Expiry computed from ``now`` EVERY time — never cached from a stored state."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now >= _parse_ts(intent["expires_at"])


def current_state(data_dir: Path, intent_id: str) -> str:
    """The last recorded transition's ``to_state`` for this intent, or :data:`contract.S_DRAFT`
    if only the intent itself (no transition yet) is on the ledger."""
    last = None
    for e in ledger.read_all(data_dir):
        if e.get("kind") == "transition" and e.get("key", [None])[1:2] == [intent_id]:
            if last is None or e["seq"] > last["seq"]:
                last = e
    if last is not None:
        return last["payload"]["to_state"]
    return contract.S_DRAFT


def _is_scenario(intent: dict) -> bool:
    # review round-3 L5: delegates to intent.is_test_scenario (case-INSENSITIVE on the prefix) —
    # see that function's docstring for why a case-sensitive match here was a safety gap: it let
    # a lowercase "test_scenario:..." intent advance past SCENARIO_MAX_STATE like a real decision.
    return is_test_scenario(intent.get("scenario"))


_ORDER = contract.HAPPY_PATH  # DRAFT..OWNER_GATE, in order


def _exceeds_scenario_ceiling(to_state: str) -> bool:
    if to_state not in _ORDER:
        return False  # a failure state is never "past" the ceiling in this sense
    return _ORDER.index(to_state) > _ORDER.index(contract.SCENARIO_MAX_STATE)


def record_intent(data_dir: Path, intent: dict, now: datetime) -> tuple[dict, bool]:
    """Register the intent itself on the ledger (kind=``intent``, key=(intent_id,)). Idempotent:
    the same ``intent_id`` (same content hash) is a no-op the second time."""
    return ledger.append_idempotent(data_dir, kind="intent", key=("intent", intent["intent_id"]),
                                    payload=intent, now=now)


def advance(data_dir: Path, intent: dict, to_state: str, evidence: dict, now: datetime) -> dict:
    """Append one transition. Refuses (raises) illegal transitions, a scenario past its ceiling,
    and an expired intent moving anywhere but EXPIRED/CANCELLED/INCIDENT. A repeated transition
    returns the EXISTING record (idempotent), never a second row."""
    if to_state not in contract.TRANSITIONS and to_state not in contract.FAILURE_STATES \
            and to_state != contract.S_OWNER_GATE:
        raise IllegalTransition(f"{to_state!r} is not a known state")
    intent_id = intent["intent_id"]
    # review #12: expiry is checked BEFORE idempotency, always against `now`, never cached. The
    # old order let an intent that was VALIDATED before it expired be handed back as "VALIDATED"
    # forever afterwards too — the idempotency short-circuit returned the old record without ever
    # re-checking whether the CALLER's own `now` is past expires_at. A caller must never be told an
    # expired intent is still VALIDATED merely because that was true once, earlier.
    if is_expired(intent, now) and to_state not in (contract.S_EXPIRED, contract.S_CANCELLED, contract.S_INCIDENT):
        raise IntentExpired(f"intent {intent_id} expired at {intent['expires_at']}; only EXPIRED/CANCELLED/"
                            f"INCIDENT may be recorded now")
    # idempotency SECOND: a repeated transition is a no-op, never re-judged against the NEW
    # current state — which, after the first success, already equals to_state and would make a
    # same-state "transition" look illegal even though it is just a resumed repeat.
    existing = ledger.find_by_key(data_dir, "transition", ("transition", intent_id, to_state))
    if existing is not None:
        return existing
    cur = current_state(data_dir, intent_id)
    allowed = contract.TRANSITIONS.get(cur, ())
    if to_state not in allowed:
        raise IllegalTransition(f"{cur!r} -> {to_state!r} is not in contract.TRANSITIONS")
    if _is_scenario(intent) and _exceeds_scenario_ceiling(to_state):
        raise IllegalTransition(f"TEST_SCENARIO intent cannot pass {contract.SCENARIO_MAX_STATE!r} "
                                f"(review #12); refused {to_state!r}")
    payload = {"intent_id": intent_id, "from_state": cur, "to_state": to_state, "evidence": evidence,
              "sleeve_id": intent.get("sleeve_id"), "scenario": intent.get("scenario")}
    entry, created = ledger.append_idempotent(data_dir, kind="transition", key=("transition", intent_id, to_state),
                                              payload=payload, now=now)
    return entry


# ── TOCTOU recheck (review #9) ───────────────────────────────────────────────────────────────────

def recheck(intent: dict, data_dir: Path, now: datetime) -> dict:
    """Re-read the risk snapshot fresh and diff against what the intent was built with. Returns
    ``{"mismatches": {field: {...}}, "verdict": None|"RISK_BLOCKED"|"STALE"}``. Used immediately
    before ``SHADOW_EXECUTED`` and before ``MANUAL_PILOT_READY``."""
    sleeve_id = intent.get("sleeve_id")
    book_relpath = _SLEEVE_SOURCES.get(sleeve_id, (None, None))[1]
    book_digest = None
    book_as_of = None
    if book_relpath:
        book_digest, book_as_of, _ = book_digest_and_asof(data_dir, book_relpath)
    fresh = build_risk_snapshot(data_dir, now, book_digest=book_digest, book_as_of=book_as_of)
    stored = intent.get("risk_snapshot") or {}

    mismatches = {}
    for field in ("kill_switch", "derisk", "riskpolicy_verdict", "riskpolicy_version", "cio_recommendation_id",
                  "book_state_digest", "depeg"):
        old = (stored.get(field) or {}).get("value")
        new = (fresh.get(field) or {}).get("value")
        if old != new:
            mismatches[field] = {"stored": old, "current": new}

    # review #11 / ADR table #25: a book that enters HOLD after the intent was built is re-derived
    # independently (never inferred from book_state_digest alone — a verdict can flip without the
    # underlying book FILE changing, e.g. a separate rationale file).
    rationale_relpath = _SLEEVE_SOURCES.get(sleeve_id, (None, None))[0]
    if rationale_relpath:
        from spa_core.capital_shadow.intent import _rationale_verdict
        current_verdict, _, _ = _rationale_verdict(data_dir, rationale_relpath)
        stored_verdict = intent.get("source_book_decision")
        if current_verdict == "HOLD" and stored_verdict != "HOLD":
            mismatches["book_verdict"] = {"stored": stored_verdict, "current": current_verdict}

    # review #8: comparing stored vs fresh is a DRIFT check, not a SAFETY check — "None == None"
    # (kill switch unmeasured both at build time and now) produces no mismatch at all, yet is not
    # safe to act on. The CURRENT snapshot is independently required to be safe in its own right.
    current_blockers = risk_blockers(fresh)

    verdict = None
    risk_blocking = {"kill_switch", "derisk", "riskpolicy_verdict", "riskpolicy_version", "book_state_digest",
                     "depeg", "book_verdict"}
    if current_blockers:
        verdict = contract.S_RISK_BLOCKED
    elif risk_blocking & set(mismatches):
        verdict = contract.S_RISK_BLOCKED
    elif "cio_recommendation_id" in mismatches:
        verdict = contract.S_STALE
    return {"mismatches": mismatches, "verdict": verdict, "fresh_risk_snapshot": fresh,
           "current_blockers": current_blockers}


#: default ceiling when an intent declares none (constraints.gas_ceiling overrides it)
GAS_CEILING_DEFAULT = 500_000
#: a uint256 "infinite approval" — never acceptable (review, failure #22)
UNLIMITED_APPROVAL = 2 ** 256 - 1


def policy_violation(intent: dict, sim_record: dict) -> Optional[str]:
    """A PASSing simulation can still be a policy violation: unmeasured gas (#10 — an unknown cost
    is never treated as an acceptable one), excessive gas (#11), a missing approve amount (#10 —
    cannot confirm it equals the notional, so it is refused rather than assumed fine), or an
    approve amount that is not exactly the intent's own notional (#22, never unlimited). Returns a
    reason string, or ``None``."""
    gas = sim_record.get("gas_estimate")
    gas_val = gas.get("value") if isinstance(gas, dict) else gas
    gas_measured = (gas.get("state") == contract.MEASURED) if isinstance(gas, dict) else (gas_val is not None)
    if not gas_measured or gas_val is None:
        return "gas not measured — refusing to treat an unmeasured cost as a safe one"
    ceiling = (intent.get("constraints") or {}).get("gas_ceiling", GAS_CEILING_DEFAULT)
    if isinstance(gas_val, (int, float)) and not isinstance(gas_val, bool) and gas_val > ceiling:
        return f"excessive gas: estimate {gas_val} > ceiling {ceiling}"
    if intent.get("action_type") == contract.ACTION_APPROVE:
        from spa_core.capital_shadow.intent import parse_args_readable
        args = parse_args_readable((sim_record.get("call") or {}).get("args_readable"))
        amount_arg = next((a for a in args if a.get("name") in ("amount", "value")), None)
        if amount_arg is None:
            return "approve amount missing from the simulated call — cannot confirm it equals the intent's notional"
        val = amount_arg.get("value")
        if isinstance(val, str):
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    val = None
        if val == UNLIMITED_APPROVAL:
            return "excessive allowance: approve requested UNLIMITED, must equal the intent's own notional"
        if val is None:
            return "approve amount unreadable from the simulated call — cannot confirm it equals the notional"
        # review N2: the simulated call's amount is in BASE units (what actually gets encoded
        # on-chain) — it must be compared against the intent's notional ALSO converted to base
        # units, via the SAME scaling authority simulate.py uses, never the raw human notional. A
        # correct 1000 USDC approve (1_000_000_000 base units at 6 decimals) used to be compared
        # against the bare human float 1000.0 and always fail; a 0.001 USDC approve (1000 base
        # units) used to coincidentally "match" 1000.0 and always pass — both wrong.
        from spa_core.capital_shadow.intent import to_base_units_for_intent
        expected = to_base_units_for_intent(intent)
        # review round-3 item L1 (fail-CLOSED, inv. #2): the OLD guard
        # (`isinstance(val, (int, float)) and not isinstance(val, bool) and expected is not None`)
        # SKIPPED the whole comparison — i.e. returned "no violation" — whenever `expected` could
        # not be resolved (unknown venue/token/decimals) OR `val` was a bool/float. "Cannot verify"
        # is never the same as "verified safe"; both are now violations in their own right.
        if expected is None:
            return ("cannot resolve the intent's own notional to base units (unknown venue/token/decimals) "
                    "— refusing to confirm the approve amount equals it")
        if not isinstance(val, int) or isinstance(val, bool):
            return f"approve amount {val!r} is not a plain integer in base units — cannot confirm it " \
                   f"equals the intent's notional"
        if val != expected:
            return f"excessive allowance: approve arg {val!r} base units != intent notional {expected!r} base units"
    return None
