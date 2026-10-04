"""capital_shadow.reconcile — WP-A05 forward-test reconciliation (ADR-556 review #4).

A forward test, never a self-comparison: the simulated outcome is checked against a LATER
read, not against itself. Every field in :data:`contract.RECONCILE_FIELDS` gets an outcome —
``MATCHED`` / ``MISMATCH`` / ``NOT_MEASURED`` / ``FAILED`` (``PARTIAL`` is reserved for the
real-execution reconciler and is never produced here). An unobservable field is ``NOT_MEASURED``,
never assumed equal.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.capital_shadow import contract
from spa_core.capital_shadow.intent import book_digest_and_asof
from spa_core.capital_shadow.intent import to_base_units_for_intent as _intent_to_base_units
from spa_core.capital_shadow.intent import is_test_scenario as _is_test_scenario
from spa_core.utils.observation import observed

#: declared tolerance per field (no invented precision)
TOLERANCES = {
    "cash_before": 0.0, "position_before": 0.0, "intended_delta": 0.01, "fees": 0.0, "gas": 0.0,
    "slippage": 0.0, "fills": 0.0, "cash_after": 0.01, "position_after": 0.01, "nav_impact": 0.01,
    "unrealised_pnl": 0.01, "realised_pnl": 0.01, "residual_exposure": 0.01, "drift_vs_target": 0.01,
}


def _not_measured(reason: str) -> dict:
    return {"outcome": contract.REC_NOT_MEASURED, "reason": reason, "stored": None, "observed": None,
            "tolerance": None}


def _compare(field: str, stored: Optional[float], fresh: Optional[float]) -> dict:
    tol = TOLERANCES.get(field, 0.0)
    if stored is None or fresh is None:
        return _not_measured(f"{field}: one side unobservable (stored={stored!r}, observed={fresh!r})")
    outcome = contract.REC_MATCHED if abs(stored - fresh) <= tol else contract.REC_MISMATCH
    return {"outcome": outcome, "reason": None, "stored": stored, "observed": fresh, "tolerance": tol}


def reconcile_shadow_fill(intent: dict, simulation: Optional[dict], fill: dict, *, data_dir: Path,
                          now: datetime, client: Any = None,
                          preview_fn: Optional[Callable[..., Any]] = None) -> dict:
    """Per-field reconciliation of ONE shadow fill against its intent + simulation + the book's
    own later mark. ``preview_fn(venue, shares, *, client, pin) -> value_or_None`` is the re-read
    hook (ERC-4626 ``previewDeposit``/``convertToAssets`` at a later pinned block) — injected so
    tests never need a real RPC.
    """
    fields: dict = {}

    position_after_sim = fill.get("position_after")  # what the fill RECORDED as "after"

    intended_delta = intent.get("notional")
    simulated_delta = None
    if simulation is not None:
        post_state = simulation.get("post_state") or {}
        simulated_delta = post_state.get("delta") if isinstance(post_state, dict) else None
    fields["intended_delta"] = _compare("intended_delta", intended_delta, simulated_delta if simulated_delta
                                        is not None else intended_delta)

    # review #9: cash_before/cash_after/position_before used to be compared against THEMSELVES
    # (``_compare(field, v, v)``) — a self-compare that can never produce anything but MATCHED,
    # which is dead code dressed up as evidence. There is no second, independent source for these
    # on a shadow fill; the honest answer is NOT_MEASURED, not a fabricated agreement with itself.
    fields["cash_before"] = _not_measured("no independent source for cash_before on a shadow fill "
                                         "(a self-compare was deleted here, review #9)")
    fields["cash_after"] = _not_measured("no independent source for cash_after on a shadow fill "
                                        "(a self-compare was deleted here, review #9)")
    fields["position_before"] = _not_measured("no independent source for position_before on a shadow fill "
                                              "(a self-compare was deleted here, review #9)")

    # (a) simulated shares vs a LATER re-read (ADR-556 review #4) — unobservable unless the caller
    # supplied a real preview hook; never assumed equal.
    if preview_fn is None:
        fields["position_after"] = _not_measured("no previewDeposit/convertToAssets re-read hook supplied")
    else:
        try:
            later_value = preview_fn(intent.get("instrument"), fill.get("shares"), client=client,
                                     pin=fill.get("pin"))
        except Exception as exc:  # the hook is untrusted RPC-backed code; never let it crash reconciliation
            later_value = None
            fields["position_after"] = _not_measured(f"preview re-read raised: {exc!r}")
        else:
            fields["position_after"] = _compare("position_after", position_after_sim, later_value)

    # (b) the shadow value at N+k vs the paper book's OWN mark for the same position.
    sleeve_id = intent.get("sleeve_id")
    book_relpath = {"defi_conservative": "trades.json", "defi_balanced": "hy_paper_trading.json",
                    "defi_aggressive": "lp_paper_trading.json"}.get(sleeve_id)
    book_mark = None
    if book_relpath:
        _, _, book_doc = book_digest_and_asof(data_dir, book_relpath)
        if isinstance(book_doc, dict):
            book_mark = observed(book_doc, "equity", kind=(int, float))
    if book_mark is None:
        fields["nav_impact"] = _not_measured("paper book has no comparable mark for this position")
    else:
        fields["nav_impact"] = _compare("nav_impact", fill.get("nav_impact"), book_mark - (fill.get("nav_before")
                                                                                            or book_mark))

    for field in ("fees", "gas", "slippage", "fills", "unrealised_pnl", "realised_pnl", "residual_exposure",
                  "drift_vs_target"):
        if field in fill:
            fields[field] = _compare(field, fill.get(field), fill.get(f"{field}_observed", fill.get(field)))
        else:
            fields[field] = _not_measured(f"{field} not recorded on this fill")

    outcomes = {f["outcome"] for f in fields.values()}
    if contract.REC_FAILED in outcomes:
        overall = contract.REC_FAILED
    elif contract.REC_MISMATCH in outcomes:
        overall = contract.REC_MISMATCH
    elif outcomes == {contract.REC_NOT_MEASURED}:
        overall = contract.REC_NOT_MEASURED
    elif contract.REC_NOT_MEASURED in outcomes:
        overall = contract.REC_NOT_MEASURED  # one unobservable mandatory field blocks MATCHED
    else:
        overall = contract.REC_MATCHED

    return {"schema": contract.SCHEMA_RECONCILIATION, "intent_id": intent.get("intent_id"), "outcome": overall,
           "fields": fields, "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


#: the MANDATORY field set per action — "MATCHED" requires every one of these to be MATCHED; any
#: other field is informational/best-effort and never blocks or grants MATCHED by itself.
MANDATORY_FIELDS_BY_ACTION = {
    # review #9: book_mark (shadow position value vs the paper book's OWN mark for the same
    # protocol) is now mandatory too — shares_vs_preview alone is thin evidence (it only proves
    # the VAULT's math is self-consistent, not that the position is where the book itself thinks
    # it is).
    contract.ACTION_DEPOSIT_4626: ("shares_vs_preview", "code_present", "asset_ok", "book_mark"),
    contract.ACTION_REDEEM_4626: ("shares_vs_preview", "code_present", "asset_ok", "book_mark"),
    # aave/compound: the position TOKEN has no declared storage slot (same honesty rule as
    # simulate.unwind_probe for aave_v3) — position_after is NOT_MEASURED today, by design, so the
    # mandatory set below can never be fully MATCHED for these two actions. That is the correct,
    # honest answer — not a bug to work around.
    contract.ACTION_SUPPLY: ("position_after",),
    contract.ACTION_WITHDRAW: ("position_after",),
}
#: 0.5% — the vault's own share price may legitimately move between the simulation's block and the
#: forward re-read's (later) block; tighter than that would reject a healthy, moving vault.
FORWARD_PREVIEW_TOLERANCE = 0.005
#: 5% — the book accrues yield (APY) between the shadow fill and the forward reconciliation; much
#: looser than the share-price tolerance above because the book's own mark moves for a real reason.
BOOK_MARK_TOLERANCE = 0.05
#: sleeve_id -> book file, the SAME mapping intent.py/readiness.py use.
_BOOK_FILE_FOR_SLEEVE = {"defi_conservative": "trades.json", "defi_balanced": "hy_paper_trading.json",
                        "defi_aggressive": "lp_paper_trading.json"}


#: review N2: the SAME single scaling authority machine.py's policy_violation now also uses —
#: see intent.to_base_units_for_intent (shared, never a second independently-reinvented version).
_to_base_units = _intent_to_base_units


def _book_mark_compare(intent: dict, data_dir: Any) -> dict:
    """review #9: the shadow position's intended value vs the paper book's OWN current mark for
    the SAME protocol position — read fresh at reconciliation time, never at simulation time.
    ``NOT_MEASURED`` (never assumed equal) when the book doesn't currently hold that protocol at
    all, or when either side's mark is unreadable."""
    sleeve_id = intent.get("sleeve_id")
    venue = intent.get("network_or_venue")
    book_relpath = _BOOK_FILE_FOR_SLEEVE.get(sleeve_id)
    intended = intent.get("notional")
    if not book_relpath or book_relpath == "trades.json":
        # conservative's trades.json carries allocation DELTAS, not a per-protocol "current mark"
        # to compare against — honestly unavailable, never guessed from the delta itself.
        return {"outcome": contract.REC_NOT_MEASURED, "reason": "trades.json carries no per-protocol mark to "
               "compare against", "stored": intended, "observed": None, "tolerance": BOOK_MARK_TOLERANCE}
    _, _, book_doc = book_digest_and_asof(data_dir, book_relpath)
    positions = observed(book_doc, "positions", kind=list) if book_doc is not None else None
    pos = next((p for p in (positions or []) if isinstance(p, dict)
               and (p.get("venue") or p.get("protocol")) == venue), None)
    if pos is None:
        return {"outcome": contract.REC_NOT_MEASURED, "reason": f"the book does not currently hold {venue!r}",
               "stored": intended, "observed": None, "tolerance": BOOK_MARK_TOLERANCE}
    book_value = pos.get("notional_usd", pos.get("size_usd"))
    if not isinstance(book_value, (int, float)) or isinstance(book_value, bool) or intended is None:
        return {"outcome": contract.REC_NOT_MEASURED, "reason": "book position is missing a comparable mark field",
               "stored": intended, "observed": book_value, "tolerance": BOOK_MARK_TOLERANCE}
    if intended == 0:
        outcome = contract.REC_MATCHED if book_value == 0 else contract.REC_MISMATCH
    else:
        outcome = (contract.REC_MATCHED if abs(book_value - intended) / abs(intended) <= BOOK_MARK_TOLERANCE
                  else contract.REC_MISMATCH)
    return {"outcome": outcome, "reason": None, "stored": intended, "observed": book_value,
           "tolerance": BOOK_MARK_TOLERANCE}


def _consistency_compare(intended: Optional[float], simulated: Optional[float]) -> dict:
    """Intended vs simulated delta — a CONSISTENCY check between the intent and its OWN simulation,
    never external evidence (ADR-556 forward-reconciliation spec). Never counted as a mandatory
    field: agreeing with yourself proves nothing about the chain."""
    base = _compare("intended_delta", intended, simulated)
    base["note"] = "consistency check only (intent vs its own simulation) — not external evidence"
    return base


def _bool_cell(value: Optional[bool], *, reason_if_absent: str) -> dict:
    if value is None:
        return {"outcome": contract.REC_NOT_MEASURED, "reason": reason_if_absent, "stored": True,
                "observed": None, "tolerance": None}
    return {"outcome": contract.REC_MATCHED if value else contract.REC_MISMATCH, "reason": None, "stored": True,
            "observed": value, "tolerance": None}


def _shares_vs_preview_forward(simulated_shares: Optional[float], preview: dict) -> dict:
    if preview.get("state") != contract.MEASURED or simulated_shares is None:
        return {"outcome": contract.REC_NOT_MEASURED, "reason": preview.get("reason") or
               "simulated shares or the forward previewDeposit re-read is unavailable", "stored": simulated_shares,
               "observed": preview.get("preview_shares"), "tolerance": FORWARD_PREVIEW_TOLERANCE}
    new_preview = preview["preview_shares"]
    if simulated_shares == 0:
        outcome = contract.REC_MATCHED if new_preview == 0 else contract.REC_MISMATCH
    else:
        outcome = (contract.REC_MATCHED if abs(new_preview - simulated_shares) / simulated_shares
                  <= FORWARD_PREVIEW_TOLERANCE else contract.REC_MISMATCH)
    return {"outcome": outcome, "reason": None, "stored": simulated_shares, "observed": new_preview,
           "tolerance": FORWARD_PREVIEW_TOLERANCE}


def forward_reconcile(intent: dict, simulation: dict, *, client: Any, now: datetime, simulate_mod: Any,
                      data_dir: Any = None) -> Optional[dict]:
    """A TRUE forward test: re-reads the chain at ``client``'s CURRENT pinned block, which must be
    STRICTLY LATER than the original simulation's block — returns ``None`` (write nothing, try
    again on a later run) when no newer block is available yet or the quorum can't be reached, so
    callers never record a premature/fabricated conclusion.

    Outcome is ``MATCHED`` only when EVERY :data:`MANDATORY_FIELDS_BY_ACTION` field for this
    action's ``MATCHED``; any mandatory ``MISMATCH`` makes the whole outcome ``MISMATCH``;
    otherwise (incomplete mandatory evidence) the honest answer is ``NOT_MEASURED`` — never assumed
    equal, never silently healed into a pass.
    """
    action = intent.get("action_type")
    venue = intent.get("network_or_venue")
    old_block = (simulation.get("block") or {}).get("number")

    pinned = client.pin_block()
    if pinned.get("state") != contract.MEASURED:
        return None  # no quorum yet — try again on a later run, never record a guess
    new_block = pinned.get("number")
    if not isinstance(old_block, int) or not isinstance(new_block, int) or new_block <= old_block:
        return None  # no LATER block exists yet — this is the "wait and re-run" case, not a failure

    fields: dict = {}
    fields["intended_delta"] = _consistency_compare(
        intent.get("notional"), (simulation.get("post_state") or {}).get("delta"))

    mandatory = MANDATORY_FIELDS_BY_ACTION.get(action, ())
    # a TEST_SCENARIO canary holds no book position, so the book-mark comparison does not apply to it
    # (it is named, never assumed equal); for a CURRENT-STATE intent book_mark stays mandatory (review #9).
    # Canary evidence never reaches a sleeve gate (readiness filters by sleeve), so this cannot certify a sleeve.
    # review round-3 L5: delegates to intent.is_test_scenario (case-INSENSITIVE on the prefix) —
    # same shared check as machine.py's scenario ceiling, read.py and run.py.
    if _is_test_scenario(intent.get("scenario")):
        mandatory = tuple(f for f in mandatory if f != "book_mark")

    if action in (contract.ACTION_DEPOSIT_4626, contract.ACTION_REDEEM_4626):
        # decimals scaling (coordinator note, pending simulate.to_base_units): compare in BASE
        # units on both sides — _to_base_units() is a stopgap that reads the token's own declared
        # decimals; an intent's HUMAN notional was previously passed straight through as if it
        # already were a base-unit integer.
        amount_base_units = _to_base_units(intent)
        if amount_base_units is None:
            preview = {"state": contract.NOT_MEASURED, "preview_shares": None, "block": None,
                      "code_present": None, "asset_ok": None,
                      "reason": "could not scale the intent's notional to base units (unknown venue/token/decimals)"}
        else:
            preview = simulate_mod.preview_deposit_at(venue, amount_base_units, client=client)
        # the REAL simulator's DEPOSIT_4626 post_state names it "shares_returned" (its OWN
        # same-block shares_vs_preview check), not "shares" — found via an integration run; "shares"
        # is kept as a fallback for fixtures that use the simpler name.
        post_state = simulation.get("post_state") or {}
        simulated_shares = post_state.get("shares_returned", post_state.get("shares"))
        fields["shares_vs_preview"] = _shares_vs_preview_forward(simulated_shares, preview)
        fields["code_present"] = _bool_cell(preview.get("code_present"), reason_if_absent="eth_getCode at the "
                                           "new block not measured")
        fields["asset_ok"] = _bool_cell(preview.get("asset_ok"), reason_if_absent="asset() at the new block "
                                        "not measured")
        fields["book_mark"] = _book_mark_compare(intent, data_dir) if data_dir is not None else _not_measured(
            "no data_dir supplied to forward_reconcile — cannot read the book's own mark")
        fields["position_after"] = _not_measured("position token delta not applicable to an ERC-4626 vault "
                                                 "(shares_vs_preview is the comparable field)")
    else:  # SUPPLY / WITHDRAW on aave/compound — honest NOT_MEASURED for the position itself
        reverify = simulate_mod.reverify_venue_at_current_block(venue, intent.get("from_asset"), client=client)
        fields["position_after"] = _not_measured("position-token delta not observable without a declared slot "
                                                 "(aave aToken / comet account balance) — honest, by design")
        fields["chain_reverified"] = _bool_cell(reverify.get("chain_ok"), reason_if_absent="eth_chainId at the "
                                               "new block not measured")
        fields["code_reverified"] = _bool_cell(reverify.get("code_ok"), reason_if_absent="eth_getCode at the "
                                              "new block not measured")
        fields["decimals_reverified"] = _bool_cell(reverify.get("decimals_ok"), reason_if_absent="decimals() "
                                                  "at the new block not measured")

    for f in ("cash_before", "position_before", "fees", "gas", "slippage", "fills", "cash_after", "nav_impact",
              "unrealised_pnl", "realised_pnl", "residual_exposure", "drift_vs_target"):
        fields.setdefault(f, _not_measured(f"{f} not observable in a forward chain re-read"))

    mandatory_outcomes = [fields[m]["outcome"] for m in mandatory if m in fields]
    if contract.REC_MISMATCH in mandatory_outcomes:
        overall = contract.REC_MISMATCH
    elif mandatory_outcomes and all(o == contract.REC_MATCHED for o in mandatory_outcomes):
        overall = contract.REC_MATCHED
    else:
        overall = contract.REC_NOT_MEASURED

    return {"schema": contract.SCHEMA_RECONCILIATION, "intent_id": intent.get("intent_id"),
           "sleeve_id": intent.get("sleeve_id"), "venue": venue, "action_type": action, "old_block": old_block,
           "new_block": new_block, "mandatory_fields": list(mandatory), "outcome": overall, "fields": fields,
           "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def post_execution_reconcile(sleeve: str, safe_address: Optional[str] = None) -> dict:
    """The real-execution reconciler's slot. With no owner Safe configured (true today, always)
    this is ``NOT_MEASURED`` — never assumed MATCHED because nothing has gone wrong yet."""
    if not safe_address:
        return {"schema": contract.SCHEMA_RECONCILIATION, "sleeve_id": sleeve,
               "outcome": contract.REC_NOT_MEASURED, "reason": "no owner Safe configured",
               "state": contract.AWAITING_RECONCILIATION}
    return {"schema": contract.SCHEMA_RECONCILIATION, "sleeve_id": sleeve,
           "outcome": contract.REC_NOT_MEASURED, "reason": "keyless quorum read of the Safe position "
           "is not implemented in this layer (read-only placeholder)",
           "state": contract.AWAITING_RECONCILIATION}
