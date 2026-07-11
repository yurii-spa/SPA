"""
spa_core/execution/draft_prep.py — E1 "level-A" UNSIGNED draft preparation.

Owner-greenlit 2026-07-11 (Signals Cabinet / Execution track E1). This is the thin
"prepare a draft for THIS recommendation → present it for human review" layer that
was deliberately deferred until an explicit owner go-ahead (it lives in the
AVOID-listed ``execution/`` tree).

WHAT IT IS (and is NOT)
-----------------------
Given a de-risking *recommendation* (crossing the advisory→execution boundary as
plain DATA — a dict/JSON, never a code import, so ``execution/`` stays isolated from
advisory/paper/monitoring), it produces an **UNSIGNED, human-reviewable draft
transaction**: the exact calldata a person would sign IN THEIR OWN WALLET, plus a
plain-language summary, the evidence level, the tail, and a de-risk-only refusal note.

It is **level A** (a HUMAN signs). It is NOT the Safe 2-of-N co-sign path (level B —
that is ``safe_tx_builder``) and it is emphatically NOT level C (an agent that holds a
key and moves funds — permanently REJECTED).

HARD SAFETY CONTRACT (enforced here + asserted by tests)
--------------------------------------------------------
* **AI NEVER signs / sends / moves funds.** This module produces a *draft*; every
  output carries ``signed=False`` and ``requires_human_signature=True``. It calls NO
  capital primitive (never imports ``eth_signer`` / ``wallet`` / ``mev_protection``),
  touches NO network, and NEVER flips or requires ``SPA_EXEC_ARMED`` (it only *reads*
  the arming posture, read-only, for display).
* **De-risk ONLY.** Any recommendation whose effect would INCREASE exposure
  (allocate / supply / increase / leverage / borrow / stake …) is REFUSED. We only
  ever help a user REDUCE risk.
* **Non-custodial + no fabrication.** Addresses must be real, well-formed, and
  supplied by the caller — a missing/invalid address is a fail-CLOSED refusal, never a
  placeholder. We never invent an address, amount, or APY.
* **Never sell risk as safety.** Every draft must carry an evidence level (L0–L6) and
  a tail note; a recommendation missing either is refused.
* Deterministic, stdlib-only, fail-CLOSED. Same input → byte-identical calldata.

LLM_FORBIDDEN: no LLM calls anywhere in this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# Read-only posture display ONLY. arming.is_exec_armed() reads an env var and has no
# side effects; it is the guard, not a capital primitive. We never call
# assert_live_armed and never import the signing primitives it protects.
from spa_core.execution.arming import is_exec_armed

__all__ = [
    "prepare_draft",
    "recommendations_from_checkup_approvals",
    "DraftReview",
    "SUPPORTED_KINDS",
    "DERISK_KINDS",
]

# Evidence level for a revoke recommendation: the risky allowance is a DIRECTLY
# on-chain-observed fact (the checkup read it from chain), not a modelled/paper claim.
_ONCHAIN_OBSERVED_EVIDENCE = "L2"

# ---------------------------------------------------------------------------
# Recommendation taxonomy — de-risk ONLY. Anything that would ADD exposure is
# refused up front (fail-closed), never encoded.
# ---------------------------------------------------------------------------
DERISK_KINDS = frozenset({"revoke_approval", "reduce_position", "withdraw", "full_exit"})
# Kinds we can FULLY encode unambiguous, well-known calldata for in v1. Others get a
# descriptive review-only draft (no fabricated protocol calldata).
_FULLY_ENCODED = frozenset({"revoke_approval"})
SUPPORTED_KINDS = DERISK_KINDS
# Explicitly exposure-INCREASING intents — always refused.
_FORBIDDEN_KINDS = frozenset(
    {"allocate", "supply", "deposit", "increase", "leverage", "loop", "borrow", "stake", "buy"}
)

# ERC-20 approve(address,uint256) — first 4 bytes of keccak256, a known constant
# (hardcoded exactly like the adapters + the checkup revokeTx.ts, no keccak dep).
_APPROVE_SELECTOR = "095ea7b3"

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_VALID_EVIDENCE = frozenset({"L0", "L1", "L2", "L3", "L4", "L5", "L6"})

_NOTICE = (
    "UNSIGNED DRAFT for human review. SPA never signs, sends, or moves funds and holds "
    "no private key. YOU review this and sign it in YOUR OWN wallet. Non-custodial."
)


@dataclass
class DraftReview:
    """A human-reviewable, UNSIGNED draft (or a fail-closed refusal)."""

    kind: str
    refused: bool = False
    reason: str = ""
    action_summary: str = ""
    # The unsigned tx a HUMAN signs in their own wallet. None when refused or when v1
    # cannot construct correct calldata (never fabricated).
    unsigned_tx: Optional[dict] = None
    needs_manual_construction: bool = False
    # Invariants — constant by construction, surfaced so a reviewer/test can see them.
    signed: bool = False
    requires_human_signature: bool = True
    de_risk_only: bool = True
    signer: str = "the user, in their OWN wallet (level A) — SPA holds no key"
    # Honesty payload.
    evidence_level: str = ""
    tail: str = ""
    refusal_note: str = ""
    # Read-only posture: proves execution is not armed; even armed, THIS never signs.
    exec_armed: bool = field(default=False)
    mode: str = "draft"
    notice: str = _NOTICE

    def to_dict(self) -> dict:
        return asdict(self)


def _refuse(kind: str, reason: str) -> DraftReview:
    return DraftReview(kind=kind or "unknown", refused=True, reason=reason, unsigned_tx=None)


def _pad32(hex_no_prefix: str) -> str:
    """Left-pad a hex string (no 0x) to a 32-byte (64-hex-char) ABI word."""
    return hex_no_prefix.lower().rjust(64, "0")


def _addr_word(addr: str) -> str:
    return _pad32(addr[2:])


def _uint_word(n: int) -> str:
    return _pad32(format(int(n), "x"))


def _encode_approve(spender: str, amount: int) -> str:
    """ERC-20 approve(spender, amount) calldata = 0x + selector + 2×32-byte args."""
    return "0x" + _APPROVE_SELECTOR + _addr_word(spender) + _uint_word(amount)


def prepare_draft(recommendation: dict) -> DraftReview:
    """Prepare an UNSIGNED, human-reviewable draft for a de-risking recommendation.

    ``recommendation`` is a plain dict (crosses the advisory→execution boundary as
    DATA, preserving isolation). Fail-CLOSED: any missing/invalid field, any
    exposure-increasing intent, or any unsupported kind returns a *refusal*
    (``refused=True``), never a fabricated transaction.

    Required fields (all kinds): ``kind``, ``evidence_level`` (L0–L6), ``tail``.
    ``revoke_approval`` additionally requires ``token`` + ``spender`` (valid
    0x-addresses) and optional ``chain_id`` (default 1).
    """
    if not isinstance(recommendation, dict):
        return _refuse("unknown", "recommendation must be a dict")

    kind = str(recommendation.get("kind", "")).strip().lower()
    if not kind:
        return _refuse("unknown", "missing 'kind'")
    if kind in _FORBIDDEN_KINDS:
        return _refuse(kind, f"refused: '{kind}' would INCREASE exposure — this layer is de-risk-only")
    if kind not in DERISK_KINDS:
        return _refuse(kind, f"unsupported kind '{kind}' (supported: {sorted(DERISK_KINDS)})")

    # Honesty invariants — never sell risk as safety.
    evidence = str(recommendation.get("evidence_level", "")).strip().upper()
    if evidence not in _VALID_EVIDENCE:
        return _refuse(kind, "missing/invalid 'evidence_level' (must be L0–L6)")
    tail = str(recommendation.get("tail", "")).strip()
    if not tail:
        return _refuse(kind, "missing 'tail' — every draft must state the downside")

    reason = str(recommendation.get("reason", "")).strip()
    refusal_note = (
        "De-risking action only (reduce/remove exposure). We never propose acquiring, "
        "chasing yield, or increasing risk. You sign this yourself; SPA moves nothing."
    )

    if kind == "revoke_approval":
        token = str(recommendation.get("token", "")).strip()
        spender = str(recommendation.get("spender", "")).strip()
        if not _ADDR_RE.match(token):
            return _refuse(kind, "invalid/missing 'token' address (no fabrication)")
        if not _ADDR_RE.match(spender):
            return _refuse(kind, "invalid/missing 'spender' address (no fabrication)")
        chain_id = recommendation.get("chain_id", 1)
        try:
            chain_id = int(chain_id)
            if chain_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return _refuse(kind, "invalid 'chain_id'")
        calldata = _encode_approve(spender, 0)  # set allowance to ZERO
        summary = (
            f"Revoke ERC-20 approval: set the allowance that spender {spender} holds on "
            f"token {token} to 0 (chain {chain_id})."
            + (f" Reason: {reason}." if reason else "")
        )
        return DraftReview(
            kind=kind,
            action_summary=summary,
            unsigned_tx={"to": token, "data": calldata, "value": "0x0", "chainId": chain_id},
            evidence_level=evidence,
            tail=tail,
            refusal_note=refusal_note,
            exec_armed=is_exec_armed(),
        )

    # reduce_position / withdraw / full_exit: correct calldata needs per-adapter ABI,
    # live amounts, and an oracle — we do NOT fabricate it here. Return an honest
    # review-only draft pointing at the Safe level-B path (safe_tx_builder proposal).
    target = str(recommendation.get("target", "")).strip()
    summary = (
        f"De-risk intent '{kind}'" + (f" on {target}" if target else "")
        + ": review-only draft. Exact calldata must be built via the Safe proposal path "
        "(execution/safe_tx_builder) with live amounts — not fabricated here."
        + (f" Reason: {reason}." if reason else "")
    )
    return DraftReview(
        kind=kind,
        action_summary=summary,
        unsigned_tx=None,
        needs_manual_construction=True,
        evidence_level=evidence,
        tail=tail,
        refusal_note=refusal_note,
        exec_armed=is_exec_armed(),
    )


def recommendations_from_checkup_approvals(approvals: dict) -> List[dict]:
    """Turn a DeFi-Checkup ``approvals`` finding-set into de-risk ``revoke_approval``
    recommendation dicts ready for :func:`prepare_draft`.

    This is the glue that lets E1 be driven by REAL product output (a wallet checkup) instead
    of hand-authored JSON: checkup finding → recommendation → unsigned draft the user signs.
    Input is the checkup shape ``{"unlimited": [...], "to_unknown": [...]}`` where each item
    carries ``token_address`` / ``spender_address`` (+ optional ``token_symbol`` /
    ``spender_label`` / ``chain_id``). Pure DATA transform (no code import from the checkup /
    advisory side — isolation preserved), deterministic, fail-CLOSED:

    * A finding missing a valid ``token_address`` or ``spender_address`` is SKIPPED — never a
      fabricated address.
    * De-risk ONLY: every emitted recommendation is a ``revoke_approval`` (set allowance to 0).
    * Every recommendation carries the on-chain-observed evidence level + a category-specific
      tail (never sell the finding as safe). De-duped by (token, spender).
    """
    if not isinstance(approvals, dict):
        return []
    out: List[dict] = []
    seen = set()
    _CATEGORIES = (
        ("unlimited", "unlimited allowance",
         "This is an UNLIMITED allowance — if the spender is malicious or compromised it can move "
         "your ENTIRE {sym} balance, now or any time in the future."),
        ("to_unknown", "allowance to an unlabeled/unknown spender",
         "This spender is not in our registry — if it is malicious it can move up to the approved "
         "{sym} amount. Verify you trust it before leaving the allowance open."),
    )
    for key, reason, tail_tmpl in _CATEGORIES:
        items = approvals.get(key)
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            token = str(it.get("token_address", "")).strip()
            spender = str(it.get("spender_address", "")).strip()
            if not _ADDR_RE.match(token) or not _ADDR_RE.match(spender):
                continue  # fail-closed: no fabrication of a missing/invalid address
            dedup = (token.lower(), spender.lower())
            if dedup in seen:
                continue
            seen.add(dedup)
            sym = str(it.get("token_symbol", "") or "token").strip() or "token"
            chain_id = it.get("chain_id") or it.get("chain") or 1
            out.append({
                "kind": "revoke_approval",
                "token": token,
                "spender": spender,
                "chain_id": chain_id,
                "reason": reason,
                "evidence_level": _ONCHAIN_OBSERVED_EVIDENCE,
                "tail": tail_tmpl.format(sym=sym),
            })
    return out
