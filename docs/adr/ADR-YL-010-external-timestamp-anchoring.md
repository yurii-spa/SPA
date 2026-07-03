# ADR-YL-010 — External timestamp anchoring (OpenTimestamps / Bitcoin)

**Status:** ACCEPTED (2026-07-03, owner-directed provenance sprint)
**Owners:** owner + autonomous engine
**Relates:** `docs/PROOF_CHAIN_SPEC.md` (the self-hosted chain), ADR-YL-006 (evidence levels), ADR-YL-009 (canonical docs)

## Context

The SPA proof chain (`data/rates_desk/decision_log.jsonl` + `anchors.jsonl`, plus the tournament /
equity / NAV / sleeve / underwriting chains) is **self-hosted**. Every entry hash and every
head-checkpoint anchor is written by a single operator. The hash-chain proves **integrity** — that
nothing was silently rewritten *relative to a previously-recorded checkpoint* — but it does **not**
prove **existence-in-time**: a determined single operator could regenerate the entire chain with
back-dated timestamps, because the timestamps and checkpoints are all ours. An external due-diligence
skeptic is right to discount a purely self-hosted timeline.

## Decision

Add an **append-only external-anchoring layer ON TOP of the existing chain** (the chain is never
mutated). At each daily head-checkpoint, submit the chain's `head_hash` to the **OpenTimestamps**
calendar network, which aggregates it into a **Bitcoin** transaction. The resulting `.ots` proof lets
anyone independently prove — with their **own** `ots verify`, no SPA code, no trust in us — that the
head_hash existed no later than a specific Bitcoin block's time. **Bitcoin is the external clock we do
not control.**

**Implementation** (`spa_core/audit/ots_anchor.py`, `scripts/ots_anchor.py`):
- Stdlib-only codebase — we **shell out** to the reference `ots` (opentimestamps-client) binary as an
  external system tool (like `git`/`curl`), resolved via `$SPA_OTS_BIN` or PATH. **No third-party
  import** enters the codebase, preserving the stdlib-only runtime invariant.
- `proofs/ots/<head_hash>.head` holds exactly the head_hash; `ots stamp` produces `<…>.head.ots`.
  `proofs/ots/ots_anchors.jsonl` is an **append-only, idempotent-per-head** ledger; pending→confirmed
  upgrades append a new `ots_upgrade` event (prior lines never rewritten).
- **Graceful degradation**: if the `ots` client is absent, the digest file + a `client_unavailable`
  ledger line are still written, and the digest — committed to the **public** GitHub repo by the normal
  push — already gives a weaker independent timestamp (GitHub's commit clock). The Bitcoin proof is
  filled in later via `ots upgrade`. So the pipeline never blocks.

## Invariants preserved (confirmed)

1. **No private keys / no signing / no fund movement.** OpenTimestamps is a *proof of existence*, not a
   signature: it commits the digest into a public Merkle tree the calendars aggregate on-chain, and
   verification walks the Merkle path to a Bitcoin block header. The module only reads a hash and writes
   proof files — verified by a source-scan test (`test_ots_anchor.py::test_no_private_keys_or_signing`).
2. **Existing chain not mutated** — additive layer only; append-only ledger; upgrades append, never rewrite.
3. **Runtime strategies / RiskPolicy untouched** — this is an audit-provenance job, not in the execution path.

## Verification for a skeptic

- The zero-dep verifier `scripts/verify_spa.py` gained surface **[I]**: it confirms the digest↔chain-head
  **linkage** (each `<head>.head` re-creates exactly its head_hash) and prints the exact
  `ots verify proofs/ots/<head>.head.ots` command to run with an independent client.
- The public `/verify` page documents surface **#8 external timestamp anchoring** with the honest caveat.

## Honest scope

OTS proofs begin at the **adoption date (2026-07-03)** — history *before* the first stamp is not
Bitcoin-anchored. The immediate **retro-anchor of today's head** (`3a467bed…`, chain_length 580) proves
"everything in the chain that exists today existed **no later than today**" — a forward-only guarantee
from here on, not a retroactive claim about past dates.

## Consequences

- Daily agent runs `python3 scripts/ots_anchor.py both` (stamp latest head + upgrade pending) — wired in
  the deploy checklist (owner-gated; not auto-deployed by this branch).
- The provenance claim upgrades from "self-hosted integrity" to "**Bitcoin-anchored existence from
  2026-07-03 onward**", independently checkable without SPA.

*Research/audit-layer ADR; no runtime/RiskPolicy/execution change. Branch `fix/external-anchoring`.*
