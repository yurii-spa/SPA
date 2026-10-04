# Agent identity: stable role IDs, human display names (future Studio OS UX requirement)

> **Source:** owner, 2026-10-03, in the Mission Control v1 closeout message. Status: **future requirement**,
> recorded so it is not lost; it does NOT expand ADR-552 and is not scheduled. Do not create agents to fill names.

## Requirement

1. **Executive roles are unambiguous.**
   - Chief Investment Officer = **CIO**.
   - Chief Operating Officer = **COO**.
   - A Chief Information Officer, if ever used, must never be abbreviated in a way that collides with the
     Investment CIO.
2. **Authority lives on a stable `role_id`.** It never lives on a name:
   ```yaml
   role_id: chief_investment_officer
   title: Chief Investment Officer
   display_name: Штирлиц

   role_id: chief_operating_officer
   title: Chief Operating Officer
   display_name: Шурик
   ```
3. **Display names / nicknames are UI and personality metadata only.** Russian names may be inspired by
   fictional characters, films or actors. They never define permissions, ownership, memory or authority:
   every check, card owner, memory key and manifest entry uses `role_id`.
4. **No new agents merely to fill those names.**

## Where it would land (when scheduled)

- `architecture/manifest.json` agent passports: `role_id` and `display_name` as separate fields.
- Mission Control / Telegram render `display_name (title)`.
- A ratchet that rejects authority checks keyed on display names.

## Candidate (recorded 2026-10-04, RM-LIVE-01 — not implemented, no agent created)

- `role_id: execution_safety_officer` · title «Execution Safety Officer» · display name candidate: to be chosen by
  the owner. The existing capital-shadow boundary (ADR-556: shadow execution, readiness verdict, guards) could carry
  this identity later. Its authority would remain NONE — it certifies nothing. The read-only verifier
  recomputes readiness, and only the owner crosses the money boundary. Recorded as a candidate only.

## Display-name change and a new candidate (2026-10-04, RM-EXPAND-01 / ADR-560)

- The owner selected **Oracle** as the display name of `chief_investment_officer` (was «Штирлиц»). Display metadata
  only; `role_id`, modules and authority unchanged. Single source: `architecture/roles.json` = `investment_cio.contract
  .ROLE_DISPLAY_NAME` (tested), Mission Control reads the contract.
- **Candidate, not created:** `role_id: head_of_research` · title «Head of Research» — would own the Research Factory's
  admission decisions (RESEARCH → PAPER, the evidence gate to CIO_ELIGIBLE); authority over capital NONE; it proposes,
  Oracle allocates on paper, only the owner moves money. `display_name` UNASSIGNED — the owner chooses.
  Suggested characters: Hermione Granger · Spock · Lisbeth Salander · Dr. Ellie Arroway · Sherlock Holmes ·
  Hari Seldon.
