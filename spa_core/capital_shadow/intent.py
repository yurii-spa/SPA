"""capital_shadow.intent — WP-A01 ``CapitalActionIntent`` construction (ADR-556, incl. binding review).

Builds UNSIGNED intents only. Nothing here signs, submits, approves or moves a single unit of
value. Two builders:

* :func:`build_current_intents` — projects each DeFi book's OWN latest paper decision
  (never manufactures an action: HOLD / CIO-abstention / no-new-trade all collapse to
  ``NO_ACTION`` with a reason).
* :func:`build_scenario_intents` — deterministic, labelled ``TEST_SCENARIO:<name>`` fixtures used
  to exercise the rest of the pipeline end to end without ever reaching a real recommendation.

Every intent carries exactly :data:`contract.INTENT_FIELDS` — no more, no fewer (contract test).
``intent_id`` is a content hash over :data:`contract.INTENT_ID_FIELDS` (same snapshot ⇒ same id).

# LLM_FORBIDDEN — every rule below is deterministic and reproducible from the same inputs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.capital_shadow import contract
from spa_core.investment_cio import contract as _cio_contract
from spa_core.utils.observation import observed

# ── generic helpers ──────────────────────────────────────────────────────────────────────────────


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_hex(text.encode("utf-8"))


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> tuple[Optional[Any], Optional[bytes]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    try:
        return json.loads(raw), raw
    except (ValueError, UnicodeDecodeError):
        return None, raw


def _file_digest(path: Path) -> Optional[str]:
    try:
        return _sha256_hex(path.read_bytes())
    except OSError:
        return None


def intent_id_for(fields: dict) -> str:
    """sha256 of the canonical JSON of exactly :data:`contract.INTENT_ID_FIELDS`."""
    subset = {k: fields.get(k) for k in contract.INTENT_ID_FIELDS}
    return _sha256_text(_canonical(subset))


# ── risk_snapshot sub-fields — each carries value / as_of / digest / state / reason ────────────────


def _snap_field(value: Any, *, as_of: Optional[str], digest: Optional[str],
                 state: str = contract.MEASURED, reason: Optional[str] = None) -> dict:
    return {"state": state, "value": value, "as_of": as_of, "digest": digest, "reason": reason}


def read_kill_switch_state(data_dir: Path) -> dict:
    """``state`` is whatever string the writer publishes, verbatim — never validated against a
    fixed set here, because the explicit-``state`` path below passes it straight through.
    review round-3 L4: the REAL writer (``spa_core/governance/kill_switch.py``, ADR-531) publishes
    an EXPLICIT ``state`` of ``TRIGGERED`` / ``UNMEASURED`` / ``CLEAR_PARTIAL`` / ``CLEAR`` — never
    ``HARD_KILL``/``SOFT_DERISK``/``ARMED`` (an earlier version of this docstring named those three
    and led a caller to allowlist-match on names the real writer never produces, review L4). The
    legacy fallback below (``triggered`` bool, no explicit ``state`` field) is a SEPARATE, older
    shape and still derives ``HARD_KILL``/``CLEAR_PARTIAL`` — every caller comparing this value
    must treat anything other than exactly ``"CLEAR"`` as not-clear (fail-closed), never allowlist
    a fixed set of "bad" names.

    When no explicit ``state`` is published we fall back to ``triggered``, and the fallback itself
    is CLEAR_PARTIAL (not full CLEAR): a boolean collapses SOFT_DERISK and CLEAR into the same
    ``False``, so "not triggered" is not full confidence that nothing is de-risking.
    """
    path = Path(data_dir) / "kill_switch_status.json"
    doc, raw = _read_json(path)
    digest = _sha256_hex(raw) if raw is not None else None
    as_of = observed(doc, "generated_at", kind=str) if isinstance(doc, dict) else None
    if doc is None:
        return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                            reason="kill_switch_status.json unavailable")
    explicit = observed(doc, "state", kind=str)
    if explicit is not None:
        return _snap_field(explicit, as_of=as_of, digest=digest)
    triggered = observed(doc, "triggered", kind=bool)
    if triggered is True:
        return _snap_field("HARD_KILL", as_of=as_of, digest=digest,
                            reason="derived from triggered=true (no explicit state field)")
    if triggered is False:
        return _snap_field("CLEAR_PARTIAL", as_of=as_of, digest=digest,
                            reason="fallback used: no explicit state field, only triggered=false "
                                   "(cannot distinguish CLEAR from SOFT_DERISK)")
    return _snap_field(None, as_of=as_of, digest=digest, state=contract.NOT_MEASURED,
                        reason="kill_switch_status.json has neither state nor triggered")


def read_derisk_state(data_dir: Path) -> dict:
    path = Path(data_dir) / "derisk_status.json"
    doc, raw = _read_json(path)
    digest = _sha256_hex(raw) if raw is not None else None
    as_of = observed(doc, "generated_at", kind=str) if isinstance(doc, dict) else None
    if doc is None:
        return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                            reason="derisk_status.json unavailable")
    active = observed(doc, "active", kind=bool)
    if active is None:
        active = observed(doc, "derisk", kind=bool)
    if active is None:
        return _snap_field(None, as_of=as_of, digest=digest, state=contract.NOT_MEASURED,
                            reason="derisk_status.json has no active/derisk field")
    return _snap_field(bool(active), as_of=as_of, digest=digest)


def read_riskpolicy_state(data_dir: Path) -> dict:
    """``value`` = ``{"verdict": "PASS"|"FAIL", "version": "v1.0"}`` read from
    ``current_positions.json`` (``policy_compliant`` / ``policy_version``) — never changed here."""
    path = Path(data_dir) / "current_positions.json"
    doc, raw = _read_json(path)
    digest = _sha256_hex(raw) if raw is not None else None
    as_of = observed(doc, "generated_at", kind=str) if isinstance(doc, dict) else None
    if doc is None:
        return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                            reason="current_positions.json unavailable")
    compliant = observed(doc, "policy_compliant", kind=bool)
    version = observed(doc, "policy_version", kind=str)
    if compliant is None or version is None:
        return _snap_field(None, as_of=as_of, digest=digest, state=contract.NOT_MEASURED,
                            reason="policy_compliant/policy_version not readable")
    verdict = "PASS" if compliant else "FAIL"
    return _snap_field({"verdict": verdict, "version": version}, as_of=as_of, digest=digest)


def read_cio_state(data_dir: Path, now: datetime) -> dict:
    """``value`` = ``{"recommendation_id":..., "stance":...}`` via the canonical CIO reader."""
    from spa_core.investment_cio import read as cio_read
    try:
        result = cio_read.latest(Path(data_dir), now=now)
    except Exception as exc:  # the CIO reader is read-only; a crash there is NOT a license to guess
        return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                            reason=f"investment_cio.read.latest raised: {exc!r}")
    if result.get("state") != contract.MEASURED:
        return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                            reason=result.get("reason") or "CIO recommendation not available")
    rec = result.get("recommendation") or {}
    rec_id = rec.get("recommendation_id")
    stance = rec.get("stance")
    digest = _sha256_text(_canonical(rec))
    return _snap_field({"recommendation_id": rec_id, "stance": stance}, as_of=rec.get("generated_at"),
                        digest=digest)


def book_digest_and_asof(data_dir: Path, book_relpath: str) -> tuple[Optional[str], Optional[str], Optional[Any]]:
    """Returns ``(sha256_of_book_file, as_of, doc)``. ``as_of`` prefers the book's own
    ``last_cycle_at`` / ``generated_at`` field, else the file mtime."""
    path = Path(data_dir) / book_relpath
    doc, raw = _read_json(path)
    if raw is None:
        return None, None, None
    digest = _sha256_hex(raw)
    as_of = None
    if isinstance(doc, dict):
        as_of = observed(doc, "last_cycle_at", kind=str) or observed(doc, "generated_at", kind=str)
    elif isinstance(doc, list) and doc and isinstance(doc[-1], dict):
        as_of = doc[-1].get("ts") or doc[-1].get("as_of")
    if as_of is None:
        try:
            as_of = _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
        except OSError:
            as_of = None
    return digest, as_of, doc


def read_depeg_state(data_dir: Path) -> dict:
    """Always NOT_MEASURED today: no real measured depeg price source exists. The ``hy_cycle``
    hard-coded ``0.0`` is explicitly REJECTED as a measurement (ADR-556 review #12) — it is named
    here, not silently substituted."""
    return _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                        reason="no real measured depeg price source; hy_cycle's hard-coded 0.0 is "
                               "rejected as a measurement, not used as a stand-in")


def build_risk_snapshot(data_dir: Path, now: datetime, *, book_digest: Optional[str],
                         book_as_of: Optional[str]) -> dict:
    """The full ``risk_snapshot`` cell group, shared by :func:`build_current_intents` /
    :func:`build_scenario_intents` AND by ``machine.recheck`` (same function, same inputs — a
    TOCTOU check that computed the fields differently from how they were first read would not be
    a check at all)."""
    kill = read_kill_switch_state(data_dir)
    derisk = read_derisk_state(data_dir)
    riskpolicy = read_riskpolicy_state(data_dir)
    cio = read_cio_state(data_dir, now)
    depeg = read_depeg_state(data_dir)
    book = _snap_field(book_digest, as_of=book_as_of, digest=book_digest,
                        state=contract.MEASURED if book_digest is not None else contract.NOT_MEASURED,
                        reason=None if book_digest is not None else "book file unavailable")
    return {
        "kill_switch": kill,
        "derisk": derisk,
        "riskpolicy_verdict": _snap_field(
            (riskpolicy["value"] or {}).get("verdict") if riskpolicy["state"] == contract.MEASURED else None,
            as_of=riskpolicy["as_of"], digest=riskpolicy["digest"], state=riskpolicy["state"],
            reason=riskpolicy["reason"]),
        "riskpolicy_version": _snap_field(
            (riskpolicy["value"] or {}).get("version") if riskpolicy["state"] == contract.MEASURED else None,
            as_of=riskpolicy["as_of"], digest=riskpolicy["digest"], state=riskpolicy["state"],
            reason=riskpolicy["reason"]),
        "cio_recommendation_id": _snap_field(
            (cio["value"] or {}).get("recommendation_id") if cio["state"] == contract.MEASURED else None,
            as_of=cio["as_of"], digest=cio["digest"], state=cio["state"], reason=cio["reason"]),
        "cio_stance": _snap_field(
            (cio["value"] or {}).get("stance") if cio["state"] == contract.MEASURED else None,
            as_of=cio["as_of"], digest=cio["digest"], state=cio["state"], reason=cio["reason"]),
        "book_state_digest": book,
        "depeg": depeg,
    }


def snapshot_unknowns(risk_snapshot: dict) -> list:
    unknowns = []
    for name, cell in risk_snapshot.items():
        if cell.get("state") != contract.MEASURED:
            unknowns.append({"field": name, "state": cell.get("state"), "reason": cell.get("reason")})
    return unknowns


# ── intent assembly ──────────────────────────────────────────────────────────────────────────────


def _base_fields(*, now: datetime, pin: dict, sleeve_id: str, strategy_id: str, action_type: str,
                  network_or_venue: Any, instrument: Optional[str], from_asset: Optional[str],
                  to_asset: Optional[str], notional: Optional[float], notional_unit: Optional[str],
                  source_recommendation_id: Optional[str], source_role_id: str, source_book_decision: Optional[str],
                  risk_snapshot: dict, unknowns: list, reason: str, scenario: str,
                  ttl_s: int = contract.INTENT_TTL_SHADOW_S, expected_price: Any = None,
                  max_slippage: Any = None, expected_fees: Any = None, expected_gas: Any = None,
                  expected_position_after: Any = None, constraints: Optional[dict] = None,
                  evidence_refs: Optional[list] = None) -> dict:
    created_at = _iso(now)
    expires_at = _iso(now + timedelta(seconds=ttl_s))
    fields = {
        "schema_version": contract.SCHEMA_INTENT,
        "created_at": created_at,
        "expires_at": expires_at,
        "pinned_block": pin,
        "source_recommendation_id": source_recommendation_id,
        "source_role_id": source_role_id,
        "source_book_decision": source_book_decision,
        "sleeve_id": sleeve_id,
        "strategy_id": strategy_id,
        "action_type": action_type,
        "network_or_venue": network_or_venue,
        "instrument": instrument,
        "from_asset": from_asset,
        "to_asset": to_asset,
        "notional": notional,
        "notional_unit": notional_unit,
        "expected_price": expected_price,
        "max_slippage": max_slippage,
        "expected_fees": expected_fees,
        "expected_gas": expected_gas,
        "expected_position_after": expected_position_after,
        "risk_snapshot": risk_snapshot,
        "constraints": constraints or {},
        "evidence_refs": evidence_refs or [],
        "simulation_required": action_type != contract.ACTION_NO_ACTION,
        "owner_action_required": True,
        "execution_mode": contract.LAYER_MODE,
        "reason": reason,
        "unknowns": unknowns,
        "scenario": scenario,
        "policy_version": contract.POLICY_VERSION,
    }
    fields["intent_id"] = intent_id_for(fields)
    assert set(fields.keys()) == set(contract.INTENT_FIELDS), sorted(set(fields) ^ set(contract.INTENT_FIELDS))
    return fields


def _no_action(*, now: datetime, pin: dict, sleeve_id: str, risk_snapshot: dict, unknowns: list, reason: str,
                source_recommendation_id: Optional[str] = None, source_book_decision: Optional[str] = None,
                scenario: str = contract.SCENARIO_CURRENT, constraints: Optional[dict] = None,
                date_scoped: bool = False) -> dict:
    # constraints (trade_id/protocol) is carried through even on a NO_ACTION/blocked outcome
    # (review #7) — the "already recorded" check is keyed on this, and dropping it on a blocked
    # intent is exactly how a trade blocked by CIO disagreement used to get replayed later as if
    # it had never been seen.
    strategy_id = f"{sleeve_id}:no_action"
    if date_scoped:
        # review N6: a NO_ACTION built with an UNMEASURED pin has a CONSTANT pinned_block across
        # every cycle (nothing else in contract.INTENT_ID_FIELDS varies either), so every day's
        # attempt used to hash to the IDENTICAL intent_id — machine.record_intent's idempotent
        # behaviour then meant only ONE such attempt was ever recorded, no matter how many cycles
        # actually tried. strategy_id IS in INTENT_ID_FIELDS, so folding the run's own UTC date
        # into it (only for this case) gives each day's attempt its own id, without touching the
        # frozen contract.
        strategy_id += ":" + now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return _base_fields(now=now, pin=pin, sleeve_id=sleeve_id, strategy_id=strategy_id,
                        action_type=contract.ACTION_NO_ACTION, network_or_venue=None, instrument=None,
                        from_asset=None, to_asset=None, notional=None, notional_unit=None,
                        source_recommendation_id=source_recommendation_id, source_role_id=contract.SOURCE_ROLE_ID,
                        source_book_decision=source_book_decision, risk_snapshot=risk_snapshot,
                        unknowns=unknowns, reason=reason, scenario=scenario, constraints=constraints)


# ── risk gate (review #8): unknown/unsafe risk never falls through as "safe" ────────────────────

def risk_blockers(risk_snapshot: dict) -> list:
    """Names every CURRENT reason an action intent is forbidden: kill switch not exactly CLEAR,
    derisk not CONFIRMED inactive, RiskPolicy verdict not PASS, depeg not MEASURED. ``None == None``
    (both sides unmeasured) is never treated as "nothing changed, so it's safe" — unknown is never
    safe, here or in :func:`spa_core.capital_shadow.machine.recheck`."""
    reasons = []
    kill = risk_snapshot.get("kill_switch") or {}
    if kill.get("value") != "CLEAR":
        reasons.append(f"kill switch is {kill.get('value')!r}, not exactly CLEAR")
    derisk = risk_snapshot.get("derisk") or {}
    if derisk.get("state") != contract.MEASURED or derisk.get("value") is not False:
        reasons.append(f"derisk is not confirmed inactive (state={derisk.get('state')}, value="
                      f"{derisk.get('value')!r})")
    riskpolicy = risk_snapshot.get("riskpolicy_verdict") or {}
    if riskpolicy.get("value") != "PASS":
        reasons.append(f"RiskPolicy verdict is {riskpolicy.get('value')!r}, not PASS")
    depeg = risk_snapshot.get("depeg") or {}
    if depeg.get("state") != contract.MEASURED:
        reasons.append("depeg is not MEASURED (an unmeasured price risk is never treated as safe)")
    return reasons


# ── CURRENT_STATE (never manufactures an action) ────────────────────────────────────────────────

#: review #3: the non-candidate sleeve id every TEST_SCENARIO intent uses — never one of the three
#: real DeFi sleeve ids. readiness.py filters ledger rows by this exact string so scenario evidence
#: can never feed a real sleeve's gates.
CANARY_SLEEVE = "scenario_canary"


def is_test_scenario(scenario_value: Any) -> bool:
    """True iff ``scenario_value`` is a TEST_SCENARIO marker — matched CASE-INSENSITIVELY on
    :data:`contract.SCENARIO_TEST_PREFIX` (review round-3 L5: machine.py's scenario ceiling
    matched the prefix case-SENSITIVELY, so a lowercase ``"test_scenario:..."`` intent was treated
    as a CURRENT_STATE one and could advance past SHADOW_EXECUTED exactly like a real decision —
    the ceiling exists specifically to stop fixture/test intents from ever reaching
    pilot-readiness states). The ONE shared check: machine.py / readiness.py / read.py / run.py /
    reconcile.py all call this rather than each re-implementing their own
    ``.startswith(contract.SCENARIO_TEST_PREFIX)`` (one name, one object — the same defect class
    CLAUDE.md warns against for adapter registries)."""
    return isinstance(scenario_value, str) and \
        scenario_value.lower().startswith(contract.SCENARIO_TEST_PREFIX.lower())

#: sleeve_id -> (rationale file, book file) — the book is the book's OWN paper decision, never a
#: second source of truth (ADR-556 review #11: the intent comes from the book, not from the CIO).
_SLEEVE_SOURCES = {
    "defi_conservative": ("allocation_rationale.json", "trades.json"),
    "defi_balanced": ("allocation_rationale_balanced.json", "hy_paper_trading.json"),
    "defi_aggressive": ("allocation_rationale_aggressive.json", "lp_paper_trading.json"),
}


def _rationale_verdict(data_dir: Path, rationale_relpath: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns ``(verdict, detail, reason_if_absent)``.

    The REAL field is ``decision_shadow.decision`` (ADR-060 / `cycle_gates.py` shape, e.g.
    ``{"decision": "HOLD", "reasons": ["gain_below_band:0.098pp<0.500pp", ...], "gain_pp": 0.098,
    "required_gain_pp": 0.5, ...}``); ``verdict``/``message`` are accepted too (back-compat with
    fixtures and any future rename), but ``decision``/``reasons`` are tried FIRST — a prior cut of
    this reader only ever looked for ``verdict``, which does not exist on the real book, so every
    real HOLD was silently invisible to this layer (found via an integration run against real data).
    """
    path = Path(data_dir) / rationale_relpath
    doc, raw = _read_json(path)
    if doc is None:
        return None, None, f"allocation rationale unavailable: {rationale_relpath}"
    shadow = observed(doc, "decision_shadow", kind=dict)
    verdict = None
    detail = None
    if shadow is not None:
        verdict = observed(shadow, "decision", kind=str) or observed(shadow, "verdict", kind=str)
        reasons = observed(shadow, "reasons", kind=list)
        message = observed(shadow, "message", kind=str)
        gain_pp = observed(shadow, "gain_pp", kind=(int, float))
        required_gain_pp = observed(shadow, "required_gain_pp", kind=(int, float))
        if message:
            detail = message
        elif reasons:
            detail = "; ".join(str(r) for r in reasons[:3])
        elif gain_pp is not None and required_gain_pp is not None:
            detail = f"gain {gain_pp}pp < required {required_gain_pp}pp"
        elif gain_pp is not None:
            detail = f"gain {gain_pp}pp"
    else:
        verdict = observed(doc, "verdict", kind=str)
    if verdict is None:
        return None, None, f"allocation rationale has no decision/verdict: {rationale_relpath}"
    return verdict, detail, None


def _trade_deltas(trade: dict) -> list:
    """Every ``(protocol, delta)`` with a MATERIAL non-zero delta in one trade — never just the
    largest (review #7: taking only the largest delta silently drops every other leg of the same
    trade, and those legs then never get their own intent, ever)."""
    frm = trade.get("from_allocation") or {}
    to = trade.get("to_allocation") or {}
    out = []
    for proto, to_val in to.items():
        if not isinstance(to_val, (int, float)) or isinstance(to_val, bool):
            continue
        from_val = frm.get(proto, 0.0)
        if not isinstance(from_val, (int, float)) or isinstance(from_val, bool):
            continue
        delta = to_val - from_val
        if abs(delta) >= 1e-9:
            out.append((proto, delta))
    return out


#: marker constraints key set on the ONE final NO_ACTION a stale, never-actioned trade gets
#: (review N6) — once this marker is seen, the trade is permanently done, no more retries.
_TRADE_STALE_FINAL = "trade_stale_final"

TRADE_CONSUMED = "consumed"            # a real ACTION intent was recorded — never retried again
TRADE_STALE_CONSUMED = "stale_consumed"  # the final "trade stale" NO_ACTION was already recorded
TRADE_RETRY = "retry"                  # only blocked NO_ACTION attempts exist; age < window — try again
TRADE_GO_STALE = "go_stale"            # only blocked NO_ACTION attempts exist; age >= window — finalize
TRADE_FRESH = "fresh"                  # never attempted before

#: review N6 (round 3 re-review): production runs the daily cycle ONCE a day (09:45) — a trade
#: blocked on day 1 and cleared on day 2 must still get retried, so this window is deliberately
#: NOT contract.INTENT_TTL_SHADOW_S (6h; that is a DIFFERENT thing — a single intent's own
#: expiry). 72h means at least THREE daily cycles get a real chance before a trade is finalized
#: stale. contract.py is frozen (not editable from this file scope) — this is a local constant,
#: same pattern as CANARY_SLEEVE above.
TRADE_RETRY_WINDOW_S = 72 * 3600  # >= 3 daily cycles at a once-per-day cadence


def _trade_attempt_state(data_dir: Path, sleeve_id: str, trade_id: str, protocol: str,
                          now: datetime) -> tuple[str, Optional[datetime]]:
    """review N6: a trade blocked by a missing pin / an unsafe risk snapshot / CIO disagreement
    used to be consumed PERMANENTLY by that one blocked NO_ACTION (any state at all for the
    ``(trade_id, protocol)`` key stopped every future attempt, forever — even once the blocking
    condition resolved). Only a REAL action-type intent now consumes a trade immediately; a
    blocked NO_ACTION stays retry-eligible while the trade's own age (time since its FIRST
    attempt) is under :data:`TRADE_RETRY_WINDOW_S` — deliberately WIDER than a single intent's
    own TTL, to survive the daily cadence of the real cycle (review N6, round 3: at
    contract.INTENT_TTL_SHADOW_S == 6h, a trade blocked on day 1 and cleared on day 2 was
    finalized stale before the daily cycle ever got to retry it — the original symptom survived
    the first fix). Past that, one final NO_ACTION ("trade stale") is recorded and marked so it is
    never reconsidered again."""
    from spa_core.capital_shadow import ledger as cs_ledger
    try:
        entries = cs_ledger.read_all(data_dir)
    except Exception:
        return TRADE_FRESH, None
    first_seen: Optional[datetime] = None
    for e in entries:
        if e.get("kind") != "intent":
            continue
        payload = e.get("payload") or {}
        if payload.get("sleeve_id") != sleeve_id:
            continue
        c = payload.get("constraints") or {}
        if c.get("trade_id") != trade_id or c.get("protocol") != protocol:
            continue
        if payload.get("action_type") != contract.ACTION_NO_ACTION:
            return TRADE_CONSUMED, None
        if c.get(_TRADE_STALE_FINAL):
            return TRADE_STALE_CONSUMED, None
        created_at = payload.get("created_at")
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) \
                if isinstance(created_at, str) else None
        except ValueError:
            dt = None
        if dt is not None and (first_seen is None or dt < first_seen):
            first_seen = dt
    if first_seen is None:
        return TRADE_FRESH, None
    age_s = (now - first_seen).total_seconds()
    if age_s >= TRADE_RETRY_WINDOW_S:
        return TRADE_GO_STALE, first_seen
    return TRADE_RETRY, first_seen


def _conservative_intents(data_dir: Path, now: datetime, pin: dict, risk_snapshot: dict, unknowns: list,
                           cio_rec_id: Optional[str]) -> list:
    sleeve_id = "defi_conservative"
    rationale_relpath, _ = _SLEEVE_SOURCES[sleeve_id]
    verdict, detail, absent_reason = _rationale_verdict(data_dir, rationale_relpath)
    if absent_reason:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=absent_reason, source_recommendation_id=cio_rec_id)]
    if verdict == "HOLD":
        reason = "book verdict HOLD" + (f" ({detail})" if detail else "")
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=reason, source_recommendation_id=cio_rec_id, source_book_decision=verdict)]

    doc, _ = _read_json(Path(data_dir) / "trades.json")
    if not isinstance(doc, list) or not doc:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason="trades.json has no recorded trade", source_recommendation_id=cio_rec_id,
                           source_book_decision=verdict)]
    last_trade = doc[-1]
    if not isinstance(last_trade, dict):
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason="trades.json last entry is malformed", source_recommendation_id=cio_rec_id,
                           source_book_decision=verdict)]
    trade_id = str(last_trade.get("trade_id") or last_trade.get("ts") or "") or None
    if trade_id is None:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason="last trade has no trade_id/ts to key on (never guessed)",
                           source_recommendation_id=cio_rec_id, source_book_decision=verdict)]
    deltas = _trade_deltas(last_trade)
    if not deltas:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=f"trade {trade_id} has no material per-protocol delta",
                           source_recommendation_id=cio_rec_id, source_book_decision=verdict)]

    blockers = risk_blockers(risk_snapshot)
    out = []
    for proto, delta in deltas:
        key = {"trade_id": trade_id, "protocol": proto}
        state, first_seen = _trade_attempt_state(data_dir, sleeve_id, trade_id, proto, now)
        if state in (TRADE_CONSUMED, TRADE_STALE_CONSUMED):
            continue  # permanently done — a real action was created, or it already went stale
        if state == TRADE_GO_STALE:
            # review N6 (found by test_n6_blocked_trade_stays_retry_eligible_within_ttl_then_goes_stale):
            # INTENT_ID_FIELDS (frozen) has no "constraints"/"reason" field, so WITHOUT date-scoping
            # this finalizing NO_ACTION's content hash is IDENTICAL to the ordinary blocked-retry
            # NO_ACTION it follows — record_intent's idempotent append would then silently keep the
            # OLD (non-final) ledger row forever, and _trade_attempt_state would never see the
            # _TRADE_STALE_FINAL marker, re-declaring "stale" on every subsequent cycle instead of
            # consuming the trade exactly once.
            out.append(_no_action(
                now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                reason=f"trade {trade_id} protocol {proto}: stale — blocked since {first_seen.isoformat()} "
                      f"with no action ever created, now past the {TRADE_RETRY_WINDOW_S}s retry window (>= 3 daily cycles)",
                source_recommendation_id=cio_rec_id, source_book_decision=verdict,
                constraints={**key, _TRADE_STALE_FINAL: True}, date_scoped=True))
            continue
        # state is FRESH or RETRY — attempt now.
        if blockers:
            out.append(_no_action(
                now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                reason=f"trade {trade_id} protocol {proto}: blocked by current risk state — " + "; ".join(blockers),
                source_recommendation_id=cio_rec_id, source_book_decision=verdict, constraints=key))
            continue
        if pin.get("state") != contract.MEASURED:
            out.append(_no_action(
                now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                reason=f"trade {trade_id} protocol {proto}: no pinned block (review #12 — an action intent is "
                      f"never built without a MEASURED pin, to avoid colliding content hashes across cycles)",
                source_recommendation_id=cio_rec_id, source_book_decision=verdict, constraints=key,
                date_scoped=True))
            continue
        action_type = contract.ACTION_SUPPLY if delta > 0 else contract.ACTION_WITHDRAW
        out.append(_base_fields(
            now=now, pin=pin, sleeve_id=sleeve_id, strategy_id=f"{sleeve_id}:rebalance", action_type=action_type,
            # network_or_venue MUST be a tokens.VENUES key (simulate.py looks the venue up by this
            # exact field, never by chain id) — found via an integration run.
            network_or_venue=proto, instrument=proto, from_asset="USDC", to_asset="USDC",
            notional=round(abs(delta), 2), notional_unit="USDC", source_recommendation_id=cio_rec_id,
            source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=verdict, risk_snapshot=risk_snapshot,
            unknowns=unknowns, reason=f"book trade {trade_id} delta on {proto}: {delta:+.2f} USDC",
            scenario=contract.SCENARIO_CURRENT, constraints=key))
    if not out:
        out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                              reason=f"trade {trade_id}: every protocol delta already consumed",
                              source_recommendation_id=cio_rec_id, source_book_decision=verdict))
    return out


def _hyLP_intents(data_dir: Path, now: datetime, pin: dict, risk_snapshot: dict, unknowns: list,
                   sleeve_id: str, cio_rec_id: Optional[str]) -> list:
    rationale_relpath, book_relpath = _SLEEVE_SOURCES[sleeve_id]
    verdict, detail, absent_reason = _rationale_verdict(data_dir, rationale_relpath)
    _, _, book_doc = book_digest_and_asof(data_dir, book_relpath)
    if book_doc is None:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=f"book unavailable: {book_relpath}", source_recommendation_id=cio_rec_id)]
    regime = observed(book_doc, "regime", kind=str)
    positions = observed(book_doc, "positions", kind=list)
    if regime == "EXIT" or not positions:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=f"book regime {regime!r} (no open positions)",
                           source_recommendation_id=cio_rec_id, source_book_decision=verdict)]
    if absent_reason:
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason=absent_reason, source_recommendation_id=cio_rec_id)]
    if verdict == "HOLD":
        return [_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                           reason="book verdict HOLD" + (f" ({detail})" if detail else ""),
                           source_recommendation_id=cio_rec_id, source_book_decision=verdict)]

    blockers = risk_blockers(risk_snapshot)
    out = []
    for idx, pos in enumerate(positions):
        if not isinstance(pos, dict):
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns, reason=f"position[{idx}] is not an object (never defaulted)",
                                  source_recommendation_id=cio_rec_id, source_book_decision=verdict))
            continue
        venue = pos.get("venue") or pos.get("protocol")
        if not venue:
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns,
                                  reason=f"position[{idx}] missing venue/protocol field (never defaulted to "
                                        f"'unknown_venue')", source_recommendation_id=cio_rec_id,
                                  source_book_decision=verdict))
            continue
        opened = pos.get("opened")
        if not opened:
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns, reason=f"position {venue!r} missing 'opened' field — cannot "
                                  f"key the trade", source_recommendation_id=cio_rec_id,
                                  source_book_decision=verdict, constraints={"protocol": venue}))
            continue
        notional = pos.get("notional_usd", pos.get("size_usd"))
        if not isinstance(notional, (int, float)) or isinstance(notional, bool):
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns,
                                  reason=f"position {venue!r} missing notional_usd/size_usd field (never "
                                        f"defaulted to 0.0)", source_recommendation_id=cio_rec_id,
                                  source_book_decision=verdict, constraints={"trade_id": f"{venue}:{opened}",
                                  "protocol": venue}))
            continue
        trade_id = f"{venue}:{opened}"
        key = {"trade_id": trade_id, "protocol": venue}
        state, first_seen = _trade_attempt_state(data_dir, sleeve_id, trade_id, venue, now)
        if state in (TRADE_CONSUMED, TRADE_STALE_CONSUMED):
            continue  # permanently done — a real action was created, or it already went stale
        if state == TRADE_GO_STALE:
            # review N6: same fix as _conservative_intents' GO_STALE branch — date-scoped so this
            # FINAL NO_ACTION never content-hash-collides with the ordinary blocked-retry NO_ACTION
            # it follows (INTENT_ID_FIELDS carries no "constraints"/"reason" field).
            out.append(_no_action(
                now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                reason=f"position {venue!r} ({trade_id}): stale — blocked since {first_seen.isoformat()} with "
                      f"no action ever created, now past the {TRADE_RETRY_WINDOW_S}s retry window (>= 3 daily cycles)",
                source_recommendation_id=cio_rec_id, source_book_decision=verdict,
                constraints={**key, _TRADE_STALE_FINAL: True}, date_scoped=True))
            continue
        # state is FRESH or RETRY — attempt now.
        if blockers:
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns,
                                  reason=f"position {venue!r} ({trade_id}): blocked by current risk state — "
                                        + "; ".join(blockers), source_recommendation_id=cio_rec_id,
                                  source_book_decision=verdict, constraints=key))
            continue
        if pin.get("state") != contract.MEASURED:
            out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                  unknowns=unknowns, reason=f"position {venue!r} ({trade_id}): no pinned block "
                                  f"(review #12)", source_recommendation_id=cio_rec_id,
                                  source_book_decision=verdict, constraints=key, date_scoped=True))
            continue
        out.append(_base_fields(
            now=now, pin=pin, sleeve_id=sleeve_id, strategy_id=f"{sleeve_id}:rebalance",
            action_type=contract.ACTION_DEPOSIT_4626, network_or_venue=venue, instrument=venue, from_asset="USDC",
            to_asset=venue, notional=notional, notional_unit="USDC", source_recommendation_id=cio_rec_id,
            source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=verdict, risk_snapshot=risk_snapshot,
            unknowns=unknowns, reason=f"book position {trade_id} on {venue}", scenario=contract.SCENARIO_CURRENT,
            constraints=key))
    if not out:
        out.append(_no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                              reason="no new position since last recorded intent",
                              source_recommendation_id=cio_rec_id, source_book_decision=verdict))
    return out


def _apply_cio_gate(book_intent: dict, *, cio_cell: dict, cio_stance: Optional[str], cio_rec_id: Optional[str],
                     now: datetime, pin: dict, sleeve_id: str, risk_snapshot: dict, unknowns: list) -> dict:
    """CIO consistency gate (review #11): abstention or disagreement forces NO_ACTION, naming BOTH
    the book's own finding and why the CIO blocked it. ``constraints`` (the trade_id/protocol key,
    review #7) is always carried forward — a blocked intent must still be recognisable as "already
    handled" on the next cycle, or it gets replayed as if it were new."""
    constraints = book_intent.get("constraints")
    if cio_cell["state"] != contract.MEASURED:
        reason = f"CIO recommendation not available: {cio_cell['reason']}; book said: {book_intent['reason']}"
        if book_intent["action_type"] == contract.ACTION_NO_ACTION:
            book_intent["reason"] = reason
            return book_intent
        return _no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                          reason=reason, source_book_decision=book_intent.get("source_book_decision"),
                          constraints=constraints)
    if cio_stance == _cio_contract.STANCE_INSUFFICIENT:
        reason = f"CIO stance INSUFFICIENT_EVIDENCE; book said: {book_intent['reason']}"
        if book_intent["action_type"] == contract.ACTION_NO_ACTION:
            book_intent["reason"] = reason
            return book_intent
        return _no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                          reason=reason, source_recommendation_id=cio_rec_id,
                          source_book_decision=book_intent.get("source_book_decision"), constraints=constraints)
    if (book_intent["action_type"] != contract.ACTION_NO_ACTION
            and cio_stance in (_cio_contract.STANCE_HOLD, _cio_contract.STANCE_NONE)):
        return _no_action(now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot, unknowns=unknowns,
                          reason=f"CIO stance {cio_stance} disagrees with book action — no action manufactured; "
                                f"book said: {book_intent['reason']}", source_recommendation_id=cio_rec_id,
                          source_book_decision=book_intent.get("source_book_decision"), constraints=constraints)
    return book_intent


def build_current_intents(data_dir: Path, now: datetime, pin: dict) -> list:
    """One intent per (sleeve, protocol-delta) — never manufactures an action: a HOLD verdict, an
    abstaining/disagreeing CIO, a missing file, unsafe current risk, a missing pin, or an unmoved
    book all collapse to ``NO_ACTION`` with a named reason. A sleeve with several protocol deltas
    in one trade gets ONE intent PER delta (review #7), never just the largest."""
    data_dir = Path(data_dir)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cio_cell = read_cio_state(data_dir, now)
    cio_rec_id = (cio_cell["value"] or {}).get("recommendation_id") if cio_cell["state"] == contract.MEASURED else None
    cio_stance = (cio_cell["value"] or {}).get("stance") if cio_cell["state"] == contract.MEASURED else None

    out = []
    for sleeve_id in ("defi_conservative", "defi_balanced", "defi_aggressive"):
        _, book_relpath = _SLEEVE_SOURCES[sleeve_id]
        book_digest, book_as_of, _ = book_digest_and_asof(data_dir, book_relpath)
        risk_snapshot = build_risk_snapshot(data_dir, now, book_digest=book_digest, book_as_of=book_as_of)
        unknowns = snapshot_unknowns(risk_snapshot)

        # The book is read FIRST, always — read-only and cheap — so its own reason (e.g. a real
        # HOLD verdict) is never hidden behind a CIO-level early exit (found via an integration run).
        if sleeve_id == "defi_conservative":
            book_intents = _conservative_intents(data_dir, now, pin, risk_snapshot, unknowns, cio_rec_id)
        else:
            book_intents = _hyLP_intents(data_dir, now, pin, risk_snapshot, unknowns, sleeve_id, cio_rec_id)

        for book_intent in book_intents:
            out.append(_apply_cio_gate(book_intent, cio_cell=cio_cell, cio_stance=cio_stance, cio_rec_id=cio_rec_id,
                                       now=now, pin=pin, sleeve_id=sleeve_id, risk_snapshot=risk_snapshot,
                                       unknowns=unknowns))
    return out


# ── TEST_SCENARIO (deterministic fixtures, never reach MANUAL_PILOT_READY) ──────────────────────

def build_scenario_intents(now: datetime, pin: dict, scenario_name: str) -> list:
    """Deterministic fixtures for exercising validate -> simulate -> shadow -> reconcile. Always
    labelled ``TEST_SCENARIO:<name>`` (:data:`contract.SCENARIO_TEST_PREFIX`) so the machine can
    refuse them a path past :data:`contract.SCENARIO_MAX_STATE` by construction."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    scenario = f"{contract.SCENARIO_TEST_PREFIX}{scenario_name}"
    risk_snapshot = {k: _snap_field(None, as_of=None, digest=None, state=contract.NOT_MEASURED,
                                    reason="TEST_SCENARIO — not a real decision")
                      for k in ("kill_switch", "derisk", "riskpolicy_verdict", "riskpolicy_version",
                                "cio_recommendation_id", "cio_stance", "book_state_digest", "depeg")}
    unknowns = snapshot_unknowns(risk_snapshot)

    pin_ok = pin.get("state") == contract.MEASURED
    # review #3: every scenario intent uses this ONE non-candidate sleeve id, never
    # "defi_conservative"/etc. — scenario evidence must never be mistaken for a real sleeve's own
    # simulation/reconciliation evidence by anything matching on sleeve_id. contract.py is FROZEN
    # (not editable here), so this is a local constant, not a contract field.
    sleeve_id = CANARY_SLEEVE

    def mk(action_type, venue, notional, from_asset="USDC", to_asset="USDC", strategy="scenario"):
        # network_or_venue is a tokens.VENUES KEY, never a chain id — simulate.py resolves the
        # whole venue (incl. chain_id) from this one field (found via an integration run).
        # review #12: an ACTION intent is never built without a MEASURED pin — a constant
        # NOT_MEASURED pin is identical across every cycle, so the content hash would collide and
        # every day's intent would look like "already recorded", silently eating real decisions.
        if not pin_ok:
            # review N6: date-scoped (see _no_action) so each day's blocked attempt gets its own
            # id rather than colliding on the SAME constant NOT_MEASURED pin forever.
            return _base_fields(
                now=now, pin=pin, sleeve_id=sleeve_id,
                strategy_id=f"{sleeve_id}:{strategy}:" + now.astimezone(timezone.utc).strftime("%Y-%m-%d"),
                action_type=contract.ACTION_NO_ACTION, network_or_venue=None, instrument=None, from_asset=None,
                to_asset=None, notional=None, notional_unit=None, source_recommendation_id=None,
                source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=None, risk_snapshot=risk_snapshot,
                unknowns=unknowns, reason="no pinned block (review #12 — scenario action intents refuse "
                "without a MEASURED pin, same as current-state ones)", scenario=scenario)
        return _base_fields(
            now=now, pin=pin, sleeve_id=sleeve_id, strategy_id=f"{sleeve_id}:{strategy}",
            action_type=action_type, network_or_venue=venue, instrument=venue, from_asset=from_asset,
            to_asset=to_asset, notional=notional, notional_unit="USDC", source_recommendation_id=None,
            source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=None, risk_snapshot=risk_snapshot,
            unknowns=unknowns, reason=f"deterministic TEST_SCENARIO fixture ({scenario_name})", scenario=scenario)

    return [
        # APPROVE precedes SUPPLY on the SAME venue (aave_v3) — SUPPLY's own simulation overrides
        # the allowance anyway, but the ordering itself is part of the fixture's realism.
        mk(contract.ACTION_APPROVE, "aave_v3", 1000.0, strategy="approve_aave"),
        mk(contract.ACTION_SUPPLY, "aave_v3", 1000.0, strategy="supply_aave"),
        mk(contract.ACTION_DEPOSIT_4626, "fluid_fusdc", 1000.0, to_asset="fluid_fusdc", strategy="deposit_fluid"),
        # WITHDRAW/REDEEM can never reach SIM_PASS in this simulator (no position-token slot is
        # declared to prove a withdrawable balance) — NOT_MEASURED is the expected, correct outcome.
        mk(contract.ACTION_WITHDRAW, "compound_v3", 500.0, strategy="withdraw_compound"),
        mk(contract.ACTION_SUPPLY, "maple", 1000.0, strategy="supply_maple"),  # PERMISSIONED_VENUES -> NOT_SIMULATABLE
        # SPOT_ORDER is routed to exchange_sim.simulate_order, never simulate.simulate_intent, and
        # never feeds a sleeve verdict — it uses the SAME canary sleeve id as every other scenario
        # intent (readiness._NEVER_CANDIDATE never evaluates scenario_canary as a real sleeve).
        mk(contract.ACTION_SPOT_ORDER, "binance_spot", 1000.0, strategy="spot_order"),
    ]


def parse_args_readable(raw: Any) -> list:
    """Normalises a simulation record's ``call.args_readable`` to a
    ``[{"name","type","value"}, ...]`` list.

    The REAL ``simulate.py`` renders it as one comma-joined STRING (``"asset=0x.., amount=1000, "
    "onBehalfOf=0x.., referralCode=0"``), never the ``[{"name","type","value"}]`` list this layer's
    own fixtures use — found via an integration run: code that assumed the list shape raised
    ``AttributeError`` on every real APPROVE/SUPPLY simulation (iterating the string's CHARACTERS).
    Both shapes are accepted here; anything else is treated as empty (never guessed at)."""
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, dict)]
    if isinstance(raw, str):
        out = []
        for pair in raw.split(","):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            out.append({"name": name.strip(), "type": None, "value": value.strip()})
        return out
    return []


def to_base_units_for_intent(intent: dict) -> Optional[int]:
    """The intent's own HUMAN notional (``notional_unit`` == a token symbol, e.g. ``"USDC"``) ->
    EXACT base units, via ``tokens.to_base_units`` — the SINGLE scaling authority ``simulate.py``
    itself uses (never a second, independently-reinvented conversion that could silently disagree
    with the simulator's own; shared by ``reconcile.py`` and ``machine.py``, review N2). ``None``
    (never a guess) when the venue/token/decimals cannot be resolved, or the conversion itself
    refuses (a fractional base-unit amount, or more precision than the token supports)."""
    from spa_core.capital_shadow import tokens
    venue = intent.get("network_or_venue")
    ven = tokens.venue(venue) if isinstance(venue, str) else None
    notional = intent.get("notional")
    if ven is None or notional is None:
        return None
    tok = tokens.token(ven.get("chain_id"), intent.get("from_asset") or ven.get("asset"))
    if tok is None:
        return None
    try:
        return tokens.to_base_units(notional, intent.get("notional_unit"), tok)
    except (ValueError, TypeError):
        return None
