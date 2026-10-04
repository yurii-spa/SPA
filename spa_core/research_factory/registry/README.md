# `spa_core/research_factory/registry/` — ADR-564 (RM-EVIDENCE-01) package E3

Git-tracked, hand-curated registries. Both files are read by `evidence_contract`'s helpers
(`origin_groups()` / `role_entry()` for `origins.json`; the curated-fact door, `FACT_FIELDS`, for
`facts.jsonl`) — never written by runtime code.

## `origins.json`

One entry per origin id (`evidence_contract.ORIGIN_RE`: `issuer:` / `venue:` / `regulator:` /
`auditor:` / `administrator:` / `custodian:` / `agent:` / `chain:` / `aggregator:` / `model:` /
`engine:` prefix). Each value:

| field | meaning |
|---|---|
| `group` | the affiliation GROUP independence is counted over (`origin_groups()`, review #11). Two origins sharing a group are ONE independent witness, never two. |
| `affiliated_with` | other origin ids known to share control/ownership (informational). |
| `appointed_by` | the origin that appoints this party, where known (e.g. a fund administrator appointed by the issuer it serves) — informational provenance; not yet read by any coded gate (`role_entry()`'s `DOCUMENTED` check currently compares `group` only). |
| `note` | free-text citation of where this fact comes from. |

Curated from the Phase-0 citation seed (2026-10-04, `scratchpad/ev/phase0_citations.md`) — every
id is cited there or in `docs/decisions/ADR-564-research-evidence-and-paper-admission.md`'s
Phase-0 gap map. Circle acquired Hashnote ⇒ `issuer:hashnote` / `issuer:circle` share one group.

## `facts.jsonl`

One JSON object per line, `evidence_contract.FACT_FIELDS` exactly (no extra keys). The ONLY door
for `official_doc` / `regulatory_filing` facts (ADR-564 binding #15). `curated_by` names the
curating session (`"RM-EVIDENCE-01 Phase-0 audit"`); `reviewed_by` stays `null` here — a
DIFFERENT session reviews before it counts as reviewed (the curating session never self-reviews).

### A review is bound to CONTENT, not to a `fact_id` label (re-review H6, 2026-10-04)

`reviewed_by` alone used to be a self-certification: nothing ever checked that the fact's
*content* was what got reviewed, and no code ever read `fact_reviews/`. `registry_loader.py` now
requires, for a fact to be usable, ALL of:

1. `row["fact_sha256"] == evidence_contract.fact_content_sha256(row)` — the row matches its own
   stamped hash (every field except `fact_sha256`/`reviewed_by`; editing `value`/`quote`/`ref`/…
   after stamping breaks this).
2. A committed record in `fact_reviews/*.json` (schema `fact-review/1`) whose `reviewer` equals
   this row's `reviewed_by`, containing an entry for this exact `fact_id` **at this exact
   `fact_sha256`**, with `verdict == "CONFIRMED"`.

A ref with no HTTP host (`eth_call:`/`chain:` prefix) is likewise checkable only when it is a
genuine chain-native read: `channel == "on_chain"` AND `claim_type` is one of
`evidence_contract.CHAIN_NATIVE_CLAIMS` — not merely shaped like one, on any channel.

Two review rounds are committed: `fact_reviews/2026-10-04-round1.json` reviewed the PRE-recuration
content (hashed from the pre-recuration snapshot), `…-round2.json` reviewed what remediation
re-curation produced afterward (hashed from that later content). Content that moved again after
being reviewed — `fact-023`/`024`/`025` had `page_sha256` cleared to `null` after round 2 CONFIRMED
them against a non-null value — is unusable again: the hash the reviewer confirmed no longer
equals the row's current hash. That is the mechanism working, not a bug to paper over.

Known, deliberate conflicts (recorded as two separate facts, never merged or "resolved" by this
audit):

* **USDY issuer** — Ondo's own docs name the issuer as "Ondo USDY LLC" in one place and "Ondo
  Global Markets (BVI) Limited" in another. Both facts are kept, both `subject_to_change=true`.
* **OUSG ↔ Ondo I LP** — the legal-entity link is INFERRED (a structurally-matching Form D, not a
  statement from Ondo that this IS OUSG's legal entity), recorded as a `legal_entity_link_inferred`
  fact whose `value.state == "UNKNOWN"` with a `reason`, never promoted to `DOCUMENTED`.

Regenerated once by `/private/tmp/claude-501/.../scratchpad/ev/gen_facts.py` (not shipped) —
edits to facts go through that script or directly to the JSONL. `page_sha256` is a content hash
of the cited page (curator-supplied, not re-verified by the loader); `fact_sha256` is NOT a hash
of the quote — it is `evidence_contract.fact_content_sha256(row)`, the canonical hash of the
WHOLE row (every field except itself and `reviewed_by`). Editing a fact's `value`/`quote`/`ref`
without recomputing `fact_sha256` makes the fact unusable (see the binding section above) — that
is deliberate, not a bug.
