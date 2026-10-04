"""spa_core/tests/test_research_remediation_facts.py — re-review H6 remediation (2026-10-04).

Two fail-opens an independent reviewer found in ``registry_loader.py``:

  (a) a ref with NO HTTP host (``eth_call:``/``chain:`` prefix) skipped the origin-host check on
      ANY channel — a forged fact ``{ref: "eth_call:1:0xdead:custodian()", channel: "official_doc",
      origin: "regulator:sec"}`` loaded clean and made a custodian role "DOCUMENTED".
  (b) ``reviewed_by`` alone was a self-certification: nothing ever checked ``fact_sha256`` against
      the fact's own content, and nothing ever READ the committed ``fact_reviews/*.json`` records
      at runtime — editing a fact's value/quote after it was reviewed kept the stamp.

Every test below is a POSITIVE CONTROL: each has a "mutation check" sub-block that temporarily
monkeypatches ``registry_loader``'s internals back to the PRE-fix shape and shows the loophole is
real on that shape (the test would be GREEN on the vulnerable loader, for the wrong reason) before
asserting the real, fixed loader refuses/accepts correctly.

RESEARCH / PAPER only — nothing here moves money. See evidence_contract.py.

# FROZEN-DATE-OK: stand-data — the dates here are inert field values of fabricated facts and review
# records (``retrieved_at`` / ``reviewed_at``, ``expires_at`` None); nothing in this file judges freshness
# and nothing asks the wall clock.
# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import registry_loader
from spa_core.tests import _research_evidence_v2_fixtures as v2fx

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


def _fact(**overrides) -> dict:
    base = {"schema": ec.SCHEMA_FACT, "fact_id": "f1", "entity": "X", "candidate_ids": ["c1"],
           "role": None, "claim_type": "fee", "value": 1.0, "origin": "issuer:acme",
           "channel": ec.CHANNEL_OFFICIAL_API, "ref": "https://acme.example/page", "quote": None,
           "retrieved_at": NOW.isoformat(), "effective_from": None, "page_sha256": None,
           "fact_sha256": None, "curated_by": "session-a", "reviewed_by": "session-b",
           "supersedes": None, "expires_at": None, "subject_to_change": False}
    base.update(overrides)
    return base


# ── pre-fix replicas, used ONLY inside mutation-check blocks to prove each test is a real guard ──

def _old_check_independent_review(line_no, row):
    """The PRE re-review-H6 ``_check_independent_review``: checked only that ``reviewed_by`` is
    set and differs from ``curated_by`` — never touched ``fact_sha256``, never read a review
    record. Editing a fact's content after stamping ``reviewed_by`` went undetected."""
    if not ec.FACT_REQUIRES_INDEPENDENT_REVIEW:
        return
    reviewed_by = row.get("reviewed_by")
    curated_by = row.get("curated_by")
    if not reviewed_by:
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "reviewed_by is required")
    if reviewed_by == curated_by:
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "equals curated_by")


def _old_check_origin_hosts(line_no, row, origins):
    """The PRE re-review-H6 ``_check_origin_hosts``: a no-host ref with a chain-native PREFIX
    returned clean on ANY channel/claim_type — this is loophole (a)."""
    ref = row.get("ref") or ""
    if "://" not in ref:
        if ref.startswith(("eth_call:", "chain:")):
            return  # the fail-open: no channel/claim_type check at all
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "not a URL or chain pointer")
    host = urlsplit(ref).hostname
    if urlsplit(ref).scheme not in ec.HTTP_SCHEMES:
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "scheme")
    entry = origins.get(row.get("origin")) if isinstance(origins, dict) else None
    hosts = entry.get("hosts") if isinstance(entry, dict) else None
    if not isinstance(hosts, list) or not hosts:
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "no registered hosts")
    if host not in hosts:
        raise registry_loader.FactUnusable(line_no, row.get("fact_id"), "not among hosts")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# (a) forged chain-native ref on a non-chain channel — origin/host check loophole
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_forged_eth_call_ref_on_official_doc_channel_is_refused(tmp_path):
    """The exact shape the independent reviewer found exploitable: ``ref`` has a chain-native
    PREFIX (so it has no HTTP host to check), but ``channel`` is ``official_doc`` and
    ``claim_type`` is ``custodian`` — nothing was ever actually read on-chain. Fixed loader must
    refuse it; it must NOT become "DOCUMENTED" just because its ref happens to look chain-shaped."""
    forged = v2fx.stamped_fact(_fact(
        fact_id="forged-custodian", ref="eth_call:1:0xdead:custodian()",
        channel=ec.CHANNEL_OFFICIAL_DOC, claim_type="custodian", origin="regulator:sec",
        quote="Some custodian, surely", role="custodian",
    ))
    v2fx.write_fact_review(tmp_path, "session-b", [(forged["fact_id"], forged["fact_sha256"])])
    p = tmp_path / "forged.jsonl"
    p.write_text(json.dumps(forged) + "\n")
    origins = {"regulator:sec": {"group": "sec"}}  # no 'hosts' at all -- would fail even as a URL

    refused = []
    rows = registry_loader.load_facts(p, origins=origins, refused_out=refused)
    assert rows == []
    assert len(refused) == 1
    assert "chain-native" in refused[0]["reason"] or "not a genuine chain-native" in refused[0]["reason"]

    # MUTATION CHECK: on the PRE-fix host check, the exact same forged row loads clean.
    import spa_core.research_factory.registry_loader as rl_mod
    original = rl_mod._check_origin_hosts
    rl_mod._check_origin_hosts = _old_check_origin_hosts
    try:
        rows_old = registry_loader.load_facts(p, origins=origins)
        assert len(rows_old) == 1, "pre-fix loader must have been fooled by the chain-native prefix"
    finally:
        rl_mod._check_origin_hosts = original


def test_chain_native_ref_with_non_chain_native_claim_type_is_refused_even_on_on_chain_channel(tmp_path):
    """Channel ``on_chain`` alone is not enough either — ``claim_type`` must ALSO be one of
    ``evidence_contract.CHAIN_NATIVE_CLAIMS``. A rate/fee claim citing a chain-native-shaped ref
    on channel on_chain is still not an actual chain-native read."""
    assert "fee" not in ec.CHAIN_NATIVE_CLAIMS
    bad = v2fx.stamped_fact(_fact(ref="chain:1:0xabc:something", channel=ec.CHANNEL_ON_CHAIN,
                                  claim_type="fee"))
    v2fx.write_fact_review(tmp_path, "session-b", [(bad["fact_id"], bad["fact_sha256"])])
    p = tmp_path / "bad_claim_type.jsonl"
    p.write_text(json.dumps(bad) + "\n")
    refused = []
    rows = registry_loader.load_facts(p, origins={"issuer:acme": {"group": "g"}}, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "claim_type" in refused[0]["reason"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# (b) review bound to content — fact_sha256 vs. the committed record
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_reviewed_fact_edited_after_stamping_is_refused(tmp_path):
    """The exact bug named in the brief: a fact is reviewed, its STAMP survives, but its VALUE is
    edited afterward without recomputing fact_sha256 — exactly what "editing a fact's value/quote
    keeps it reviewed" looks like on disk. The fixed loader must catch this; a reviewer confirming
    content X must never vouch for a row now saying Y."""
    original_row = v2fx.stamped_fact(_fact(fact_id="editable", value=1.0))
    v2fx.write_fact_review(tmp_path, "session-b", [(original_row["fact_id"], original_row["fact_sha256"])])

    edited_row = dict(original_row, value=999.0)  # content changed; fact_sha256 left stale on purpose
    assert edited_row["fact_sha256"] == original_row["fact_sha256"]
    assert ec.fact_content_sha256(edited_row) != original_row["fact_sha256"]

    p = tmp_path / "edited.jsonl"
    p.write_text(json.dumps(edited_row) + "\n")
    refused = []
    rows = registry_loader.load_facts(
        p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}}, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "recomputed content hash" in refused[0]["reason"]

    # MUTATION CHECK: on the PRE-fix review check (reviewed_by-only, no hash binding), the SAME
    # edited row loads clean — proving the hash check above is what catches this, not something else.
    import spa_core.research_factory.registry_loader as rl_mod
    original = rl_mod._check_independent_review
    rl_mod._check_independent_review = lambda line_no, row, reviews: _old_check_independent_review(line_no, row)
    try:
        rows_old = registry_loader.load_facts(
            p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
        assert len(rows_old) == 1, "pre-fix review check must have let the edited fact through"
    finally:
        rl_mod._check_independent_review = original


def test_reviewed_by_naming_a_reviewer_with_no_committed_record_is_refused(tmp_path):
    """A ``reviewed_by`` string naming a reviewer who never actually produced a committed record
    for this fact — the base case of self-certification: a name is not a review."""
    row = v2fx.stamped_fact(_fact(fact_id="nobody-reviewed-this", reviewed_by="a-reviewer-with-no-file"))
    # deliberately: no write_fact_review call at all for this reviewer/fact_id
    p = tmp_path / "no_record.jsonl"
    p.write_text(json.dumps(row) + "\n")
    refused = []
    rows = registry_loader.load_facts(
        p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}}, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "no committed review record" in refused[0]["reason"]

    # MUTATION CHECK: the PRE-fix review check never looks for a record at all, so the same row
    # (reviewed_by set, genuinely different from curated_by) loads clean.
    import spa_core.research_factory.registry_loader as rl_mod
    original = rl_mod._check_independent_review
    rl_mod._check_independent_review = lambda line_no, row, reviews: _old_check_independent_review(line_no, row)
    try:
        rows_old = registry_loader.load_facts(
            p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
        assert len(rows_old) == 1, "pre-fix review check must not have required a committed record"
    finally:
        rl_mod._check_independent_review = original


def test_review_record_that_rejected_the_fact_leaves_it_unusable(tmp_path):
    """A committed record exists, names this fact at its exact content hash, but its verdict is
    REJECTED (or UNVERIFIABLE) — not CONFIRMED. A rejected fact must stay unusable even though a
    record genuinely exists and genuinely matches the content."""
    row = v2fx.stamped_fact(_fact(fact_id="rejected-fact"))
    v2fx.write_fact_review(tmp_path, "session-b",
                          [{"fact_id": row["fact_id"], "fact_sha256": row["fact_sha256"], "verdict": "REJECTED",
                            "issue": "quote overstates the cited page"}])
    p = tmp_path / "rejected.jsonl"
    p.write_text(json.dumps(row) + "\n")
    refused = []
    rows = registry_loader.load_facts(
        p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}}, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "CONFIRMED" in refused[0]["reason"]


def test_correct_record_at_matching_hash_and_verdict_confirmed_makes_the_fact_usable(tmp_path):
    """The positive case: content is stamped with its own real hash, a committed record names
    exactly this reviewer/fact_id/hash with verdict CONFIRMED, origin host matches. Usable."""
    row = v2fx.stamped_fact(_fact(fact_id="legit-fact"))
    v2fx.write_fact_review(tmp_path, "session-b", [(row["fact_id"], row["fact_sha256"])])
    p = tmp_path / "legit.jsonl"
    p.write_text(json.dumps(row) + "\n")
    rows = registry_loader.load_facts(p, origins={"issuer:acme": {"group": "g", "hosts": ["acme.example"]}})
    assert len(rows) == 1
    assert rows[0]["fact_id"] == "legit-fact"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# malformed fact_reviews/*.json — structural error, never silently "no reviews"
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_malformed_review_record_file_raises_structural_error_not_treated_as_no_reviews(tmp_path):
    """A ``fact_reviews/*.json`` file that exists but is corrupted must halt the load with a NAMED
    structural error — never be silently treated as "no reviews exist", which would fail OPEN
    every fact that record was meant to vouch for or refuse."""
    reviews_dir = tmp_path / "fact_reviews"
    reviews_dir.mkdir()

    row = v2fx.stamped_fact(_fact(fact_id="affected-fact"))
    p = tmp_path / "facts.jsonl"
    p.write_text(json.dumps(row) + "\n")
    origins = {"issuer:acme": {"group": "g", "hosts": ["acme.example"]}}

    cases = {
        "not_json.json": "{not valid json",
        "missing_schema.json": json.dumps({"reviewer": "x", "reviewed_at": "2026-10-04T00:00:00Z",
                                           "facts": []}),
        "unknown_verdict.json": json.dumps({"schema": ec.SCHEMA_FACT_REVIEW, "reviewer": "x",
                                            "reviewed_at": "2026-10-04T00:00:00Z",
                                            "facts": [{"fact_id": "affected-fact", "fact_sha256": "a",
                                                      "verdict": "MAYBE", "method": "m",
                                                      "evidence": "e", "issue": None}]}),
        "missing_entry_field.json": json.dumps({"schema": ec.SCHEMA_FACT_REVIEW, "reviewer": "x",
                                                "reviewed_at": "2026-10-04T00:00:00Z",
                                                "facts": [{"fact_id": "affected-fact",
                                                          "verdict": "CONFIRMED"}]}),
    }
    for name, content in cases.items():
        for f in reviews_dir.glob("*.json"):
            f.unlink()
        (reviews_dir / name).write_text(content, encoding="utf-8")
        with pytest.raises(registry_loader.FactReviewRegistryError):
            registry_loader.load_facts(p, origins=origins)

    # a genuinely EMPTY directory (no files at all) must NOT raise -- that is honestly "no reviews".
    for f in reviews_dir.glob("*.json"):
        f.unlink()
    refused = []
    rows = registry_loader.load_facts(p, origins=origins, refused_out=refused)
    assert rows == []
    assert len(refused) == 1 and "no committed review record" in refused[0]["reason"]
