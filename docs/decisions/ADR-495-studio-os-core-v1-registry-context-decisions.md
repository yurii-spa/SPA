# ADR-495: Studio OS Core V1 — Project Registry, Context Pack, Decision seam, Handoff

- **Status:** ACCEPTED (Owner explicitly confirmed 2026-09-28: «ACCEPT ADR-494 and ADR-495») · drafted 2026-09-27 · owner: @yurii
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-491). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.
- **Goal:** make Studio OS the *persistent company* so a fresh AI session continues Earn DeFi from
  canonical state without the Owner re-explaining anything. Reuse-first: an audit found ALL twelve
  persistent-project capabilities already exist (ledger, tracker, ADRs×419, journal, roadmap, research,
  health, security). We add **projections + one small registry**, never a second database.

## Decisions

### 1. Project Registry — the one missing canonical object
A small deterministic file `data/studio_projects.json` names the projects as first-class objects with
**pointers** (never copied content) to the existing canonical sources. V1 projects: `studio-os`,
`earn-defi-product`, `investment-engine`. Boundary preserved: **Studio OS manages WORK ON the Investment
Engine; the Investment Engine owns financial truth** — no financial state is copied into Studio OS canon.
Schema per project: `project_id, name, purpose, status, owner, repositories, canonical_docs,
architecture_docs, roadmap, task_sources, decision_sources, research_sources, release_sources,
runtime_components, interfaces, dependencies, last_handoff, updated_at`. Reader/validator:
`spa_core/studio_os/registry.py`. Guarded by a test.

### 2. Project Context Pack — generated, disposable (CORE)
`spa_core/studio_os/context.py::build_context_pack(project_id)` assembles a **read-only projection** from
canonical sources (registry + `mission-state/v04/ledger.json` via the existing read_model + `docs/decisions`
+ roadmap + `docs/journal` + health + research). Sections: purpose · boundaries · accepted decisions ·
roadmap · active/blocked/recent work · recent releases · research/evidence · risks · runtime health · last
handoff · next recommended work — **each with provenance**. Emitted to `studio_shell/project_context.json`
for the UI and re-runnable any time. It is NOT a maintained truth source; it is regenerated from canon.

### 3. Decision seam — close CANONICAL_DECISION_WRITE=NOT_AVAILABLE
Flow **PROPOSED → Owner Confirm → ACCEPTED**, reusing the existing ADR system as the canonical decision
authority (no competing authority invented). `spa_core/studio_os/decisions.py`:
- `propose_decision(...)` writes a decision **DRAFT** (status `PROPOSED`) under `docs/decisions/drafts/` —
  any session (Telegram/Web) may create drafts; a draft is not an accepted decision.
- `accept_decision(draft_id, ...)` — **Owner-gated** — promotes a draft to a numbered `ADR-NNN` (status
  `ACCEPTED`) via the existing `scripts/adr_number.py` numbering, records date/owner/problem/decision/
  rationale/alternatives/consequences/evidence/related-tasks/supersedes. Never auto-accepts.
The Owner Remote decision path now reports the draft id + "ACCEPTED requires Owner confirm", instead of
NOT_AVAILABLE.

### 4. Session Handoff — structured, reuse the journal
`spa_core/studio_os/handoff.py::write_handoff(...)` appends a machine-readable record to
`data/studio_handoffs.jsonl` (outcomes/evidence only — never chain-of-thought): requested · done · changed ·
decisions · evidence · test-results · commits · open-questions · blockers · next-action · owner-action. The
human journal (`docs/journal/`) remains; the jsonl is the queryable index the Context Pack reads for
`last_handoff`. No duplicate prose store.

### 5. Global retrieval — deterministic, local
`spa_core/studio_os/search.py` builds an in-memory index over projects/tasks/decisions/research/releases/
handoffs from the same canonical sources and answers substring/keyword queries (e.g. "Position Passport")
with typed references. No AI search, no external service.

## Consequences
- A fresh session reads one generated Context Pack + follows pointers to canon — the continuity test
  (fresh-worker reconstruction) becomes a runnable gate.
- Desktop Command Center (Overview/Projects/Work/Decisions/Research/Memory/Releases/System + search)
  renders these projections; no decorative pages, no fake data.
- No new DB, no second task/memory/decision authority; the ADR system stays THE decision authority.
