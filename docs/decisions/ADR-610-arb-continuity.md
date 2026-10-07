# ADR-610 · ARB continuity: a fresh AI session recovers the company from canonical files, and knows when that context is stale

- **Status:** Accepted
- **Date:** 2026-10-07
- **Author/approved by:** owner directive «EPIC: ARB-CONTINUITY-01 + OWNER CONTROL & RECOVERY HARDENING»
  (2026-10-07, autonomous overnight macro-epic: «Work autonomously through AUDIT → DESIGN → IMPLEMENT → TEST →
  INDEPENDENT REVIEW → … → CLOSEOUT»); implemented by the interactive Claude Code session, Wave A.
- **Builds on:** ADR-527 (memory, single roadmap), ADR-580 (company-truth contracts), ADR-591 (memory hybrid),
  ADR-592 (Director OS v2 = Mission Control, Company Truth computed on read).
- **Boundary (ADR-285):** nothing here moves money, publishes a number, renames a tier or deletes data.
  REAL CAPITAL = $0, NO LIVE EXECUTION.

## Context

AI sessions (ChatGPT as the Architecture Review Board, Claude Code as the implementation worker) are
temporary. Each new session re-learned the company from chat or from stale summaries: the root
`CURRENT_STATE.md` mixes June–August snapshots (its own header says only one block is authoritative);
`docs/STATE.md` is a ≤150-line journal-like ratchet; the memory assembler answers questions but is not a
session entry point. A ChatGPT Work candidate (2026-10-06, outside the repo, base `ca36750d`) proposed a
deterministic generator and four artifacts; it was audited against the post-RM-TRUTH-01 canon and reused
for its concepts and tests, not copied (its preview state was stale and its generator imported a private
parser and wrote outside the repo).

Owner requirements (directive §3–§6, quoted): «CURRENT_STATE.md … is a GENERATED / DERIVED read model. It
must not become a second canonical state store»; «Every nontrivial state field must have provenance.
UNKNOWN is valid. Guessing is forbidden»; «Never silently operate from stale context»; «No duplicate ADR
store. This is an index over canonical decisions»; «Do NOT rewrite Owner intent to fit current
implementation.»

## Decision

1. **Four artifacts in `docs/continuity/`, two kinds.** CURATED (hand-written, change rarely):
   `ARCHITECT_CONTEXT.md`, `OWNER_INTENT_LEDGER.md`, `BOOTSTRAP.md`, `CURRENT_STATE.schema.json`,
   `FRESH_SESSION_PROMPT.md`. GENERATED (authority `DERIVED`, never edited by hand): `CURRENT_STATE.md`,
   `ARCHITECT_DECISION_INDEX.md`, `state.json`. The root `CURRENT_STATE.md` stays as legacy history
   (guarded by `test_doc_drift`, written by `scripts/update_current_state.sh`) with a pointer banner; it is
   no longer the session entry point.
2. **One generator inside the existing memory package**: `spa_core/studio_os/memory/continuity.py`
   (`python -m spa_core.studio_os.memory continuity build|check`). Stdlib, deterministic, byte-stable for
   identical inputs, no network, no model, no database, no scheduler, no secrets (memory's sanitizer +
   path/e-mail redaction). It reuses memory's truth resolver (`Truth`, `adr_id`) for decision status.
3. **No second truth.** Runtime facts come only from two explicit files: the production code-sync receipt
   (`data/code_sync_status.json` → production code identity) and the PUBLISHED Mission Control bundle
   (`mission.json` → its Company Truth section). Company Truth is not recomputed and not imported
   (the ADR-592 import ratchet stays empty); the generator projects the cells the cockpit already shows,
   each with its canon, state and «as of».
4. **Freshness gate** (`check`): CONTEXT_STALE when a canonical input changed/appeared/vanished. Inputs:
   CLAUDE.md, ROADMAP, `docs/STATE.md`, `docs/decisions/INDEX.md`, memory_truth, roles, the curated contract,
   the generator, every ADR cited by a decision topic or intent, the latest accepted epic's ADR, a digest of who
   supersedes the cited ADRs, and the NAME LIST of every ADR in both registries (`docs/decisions/`, `docs/adr/`)
   — ANY new or removed ADR is material, because the index may lack it (review P1-2). Also stale when the
   origin server (asked with `git ls-remote`, never the cached tracking ref — ADR-362) is ahead of the root
   with any input or ADR change, the generator/contract changed, the production release moved by any change
   outside the generated outputs, the production identity can no longer be verified, runtime facts are older
   than 24 h, the outputs were edited or are missing, or the latest accepted epic changed.
   CONTEXT_PARTIAL — never FRESH — when sections are UNKNOWN/PARTIAL, runtime truth was absent, or the origin
   server could not be asked at check time (review P1-3). A runtime section without an observation time is
   PARTIAL, not MEASURED (review P1-5). **A moved commit with byte-identical canonical inputs and no ADR change
   is a note, not staleness** — the committed CURRENT_STATE can never name the commit that contains it.
   Owner-queue cards (`nimbalyst-local/tracker/`) are deliberately NOT hashed inputs: hundreds of cards change
   daily; the queue reaches the context through Mission Control's `decisions` cell (runtime, ≤24 h) and the
   epic-level gates through the ROADMAP «Owner gates:» clause, which is an input.
   **One authoritative copy per context (review P1-4):** on the production Mac `data/continuity/`
   (`copy_role: PRODUCTION`, rebuilt every 30 minutes); off the machine the committed `docs/continuity/`
   (`copy_role: COMMITTED_SNAPSHOT`, carrying `verdict_at_generation` and `root_dirty_inputs`). The copies are
   never compared or merged; `check` prints the file it judged. Cross-registry number reuse (`docs/adr` vs
   `docs/decisions`) is shown as AMBIGUOUS NUMBER; the class still resolves from `docs/decisions` (canonical,
   ADR-527). Profile effective dates are read from the deciding ADR («Date of decision» → «Date» → status line).
5. **Fail-CLOSED build.** A missing required source, a symlinked source, a duplicate or incomplete intent, a
   schema violation, a value without provenance, a public metric whose runtime type differs from the
   declared one (ADR-580 C2: TARGET / OBSERVED / REALIZED_PAPER / MODELLED / BACKTEST never collapse) or a
   source changing during generation refuses the build; nothing is written.
6. **Decision index = navigation, class resolved from canon.** Each topic declares CURRENT / EXPERIMENTAL
   / SUPERSEDED / REJECTED with its reason; a cited ADR that is superseded, not accepted, missing or
   ambiguous overrides the declaration (it cannot stay CURRENT).
7. **Owner intent is curated, its status derived.** The ledger keeps the owner's words with citations
   (UNKNOWN where no canonical file records them); `CURRENT_STATE.md` «Intents» derives whether each intent's
   decisions are still current.
8. **Epic-level Owner gates, debt and next safe action live in `docs/ROADMAP.md`** as «Owner gates:»,
   «Remaining debt:», «Next safe action:» clauses of the epic's item — the single roadmap, not a new store.
9. **Update seam:** the production copy `data/continuity/` is rebuilt on the existing 30-minute
   `com.spa.system_briefing` tick (after the mirror sync and memory `ensure-fresh`, `|| true`, `perl alarm`),
   root = the origin mirror. The committed copy is rebuilt by the delivering session after production sync.
10. **Strict promotion guard is the delivery rule** (owner decisions 2026-10-06: no `--allow-overwrite`, fix
    the guard): `push_to_github.py --expected-base <40-hex>`, STOP on drift, no force, no rebase-append;
    review trail `docs/rm_truth/REVIEW_PUSHER_FIX_*.md`.

## Consequences

- A fresh session follows `docs/continuity/BOOTSTRAP.md`; without a machine it applies the header rule
  (older than 24 h or a different origin head ⇒ stale).
- The committed copy goes stale with each canonical change; that is honest, and the rebuild is seconds.
- Memory indexes the curated contract as canon (authority 2) and the generated files as DERIVED
  (authority 0), so retrieval never ranks a read model as a decision.
- Not decided here: the public↔internal profile mapping (owner subject №2) — it is RECORDED, unchanged.

## Acceptance

`spa_core/tests/test_arb_continuity.py` (hermetic: byte-stable rebuild, stale on a changed source, fresh
after rebuild, the failure scenarios of directive §12) and `spa_core/tests/test_arb_fresh_session.py`
(36 questions answered from the generated files only, each with source and current/superseded status;
UNKNOWN allowed, a wrong confident answer fails). An independent LLM run from `FRESH_SESSION_PROMPT.md`
is a separate acceptance step and is not claimed by this ADR.
