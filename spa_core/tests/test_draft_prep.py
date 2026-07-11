"""Tests for E1 draft_prep — the level-A UNSIGNED draft-prep layer.

Locks the hard safety contract: never signs, de-risk-only, no fabrication, honesty
fields required, isolated from the signing primitives, deterministic calldata.
"""
import inspect
import re

import pytest

from spa_core.execution import draft_prep
from spa_core.execution.draft_prep import prepare_draft, DraftReview, DERISK_KINDS


A = "0x1111111111111111111111111111111111111111"  # spender
T = "0x2222222222222222222222222222222222222222"  # token


def _revoke(**over):
    rec = {"kind": "revoke_approval", "token": T, "spender": A,
           "evidence_level": "L2", "tail": "a malicious spender can drain the balance"}
    rec.update(over)
    return rec


# --- revoke_approval: correct, unsigned, human-signed --------------------------
def test_revoke_builds_correct_approve_zero_calldata():
    d = prepare_draft(_revoke(chain_id=1))
    assert not d.refused
    tx = d.unsigned_tx
    assert tx["to"] == T
    assert tx["value"] == "0x0"
    assert tx["chainId"] == 1
    # approve(address,uint256) selector + spender word + ZERO amount word
    expected = ("0x095ea7b3"
                + "0" * 24 + "1" * 40          # spender left-padded to 32 bytes
                + "0" * 64)                      # amount = 0
    assert tx["data"] == expected


def test_every_draft_is_unsigned_and_human_signed():
    d = prepare_draft(_revoke())
    assert d.signed is False
    assert d.requires_human_signature is True
    assert d.de_risk_only is True
    assert "OWN wallet" in d.signer
    assert d.mode == "draft"


def test_evidence_and_tail_surface_on_output():
    d = prepare_draft(_revoke(evidence_level="L3"))
    assert d.evidence_level == "L3"
    assert d.tail  # non-empty
    assert d.refusal_note  # de-risk framing present


# --- de-risk ONLY: exposure-increasing intents refused -------------------------
@pytest.mark.parametrize("kind", ["allocate", "supply", "borrow", "leverage", "loop", "stake", "buy", "increase"])
def test_exposure_increasing_kinds_refused(kind):
    d = prepare_draft({"kind": kind, "evidence_level": "L2", "tail": "x"})
    assert d.refused
    assert d.unsigned_tx is None
    assert "de-risk" in d.reason.lower() or "increase" in d.reason.lower()


# --- no fabrication: bad/missing addresses fail-closed -------------------------
@pytest.mark.parametrize("bad", ["", "0x123", "not-an-addr", "0xZZ11111111111111111111111111111111111111"])
def test_invalid_spender_refused(bad):
    d = prepare_draft(_revoke(spender=bad))
    assert d.refused and d.unsigned_tx is None


@pytest.mark.parametrize("bad", ["", "0xabc", None])
def test_invalid_token_refused(bad):
    d = prepare_draft(_revoke(token=bad))
    assert d.refused and d.unsigned_tx is None


# --- honesty fields are mandatory ----------------------------------------------
def test_missing_evidence_refused():
    r = _revoke(); del r["evidence_level"]
    assert prepare_draft(r).refused


def test_bad_evidence_level_refused():
    assert prepare_draft(_revoke(evidence_level="L9")).refused


def test_missing_tail_refused():
    r = _revoke(); r["tail"] = "   "
    assert prepare_draft(r).refused


# --- unsupported / malformed input ---------------------------------------------
def test_unknown_kind_refused():
    d = prepare_draft({"kind": "teleport", "evidence_level": "L1", "tail": "x"})
    assert d.refused and "unsupported" in d.reason.lower()


def test_missing_kind_refused():
    assert prepare_draft({"evidence_level": "L1", "tail": "x"}).refused


def test_non_dict_refused():
    assert prepare_draft("nope").refused
    assert prepare_draft(None).refused


def test_bad_chain_id_refused():
    assert prepare_draft(_revoke(chain_id=0)).refused
    assert prepare_draft(_revoke(chain_id="mainnet")).refused


# --- reduce/withdraw: honest review-only, no fabricated calldata ----------------
@pytest.mark.parametrize("kind", ["reduce_position", "withdraw", "full_exit"])
def test_reduce_kinds_are_review_only_not_fabricated(kind):
    d = prepare_draft({"kind": kind, "target": "compound_v3", "evidence_level": "L2",
                       "tail": "exit liquidity may be thin"})
    assert not d.refused
    assert d.unsigned_tx is None            # never fabricated
    assert d.needs_manual_construction is True
    assert "safe_tx_builder" in d.action_summary


# --- determinism ---------------------------------------------------------------
def test_deterministic_calldata():
    a = prepare_draft(_revoke())
    b = prepare_draft(_revoke())
    assert a.unsigned_tx["data"] == b.unsigned_tx["data"]


# --- ISOLATION: never imports the signing primitives ---------------------------
def test_module_does_not_import_capital_primitives():
    # Check actual IMPORT statements (AST), not docstring prose which names the
    # primitives precisely to say they are NOT imported.
    import ast
    tree = ast.parse(inspect.getsource(draft_prep))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.name)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            for n in node.names:
                imported.add(n.name)
    forbidden = {"eth_signer", "wallet", "mev_protection", "send_raw_transaction",
                 "sign_transaction", "send_protected", "assert_live_armed"}
    for imp in imported:
        base = imp.split(".")[-1]
        assert base not in forbidden, f"draft_prep must not import capital primitive '{imp}'"


def test_exec_armed_is_read_only_posture_default_off(monkeypatch):
    monkeypatch.delenv("SPA_EXEC_ARMED", raising=False)
    assert prepare_draft(_revoke()).exec_armed is False


def test_supported_kinds_are_all_derisk():
    # by construction the public supported set == the de-risk set (no exposure-adds)
    assert draft_prep.SUPPORTED_KINDS == DERISK_KINDS


def test_to_dict_roundtrip_serializable():
    import json
    d = prepare_draft(_revoke())
    s = json.dumps(d.to_dict())          # must be JSON-serializable for owner review
    assert '"signed": false' in s
    assert re.search(r'"data": "0x095ea7b3', s)
