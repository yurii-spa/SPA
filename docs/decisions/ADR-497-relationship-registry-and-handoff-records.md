# ADR-497: Relationship Registry + per-session handoff records (concurrency-safe, provenance-typed)

- **Status:** ACCEPTED (Owner explicitly confirmed 2026-09-28: «I explicitly accept the concurrency-safe per-session handoff records and LINKS-only Relationship Registry with EXPLICIT / DERIVED / HEURISTIC / UNKNOWN provenance») · owner: @yurii
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-493). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.

## Context
Pre-promotion audit: a single append-only `data/studio_handoffs.jsonl` and a single `data/studio_task_links.json`
are **merge hotspots** under parallel AI branches (two workers append → both branches touch the same file →
conflict). And the existing canonical work objects cannot own the full relationship set: the **mission ledger**
(`items`/`missions`/`work_graph`) is the director subsystem's object — out of scope to modify and concurrency-
owned by other work; **tracker cards** hold only a few frontmatter fields and are a partial/different id-space.

## Decision

### A. Relationship Registry — LINKS only, never lifecycle/state
A Studio OS overlay that stores **relationships**, never task state (state stays in the mission ledger).
- **One record per task**: `data/task_links/<task_id>.json` (a directory, not one giant JSON) → parallel
  branches add different files → no conflict hotspot. A generated `studio_shell/task_links.json` index is a
  disposable projection for the UI.
- **Every relation is provenance-typed** with an origin/confidence class:
  `EXPLICIT` (owner/author stated it) · `DERIVED` (verified reference — a decision literally names the object)
  · `HEURISTIC` (keyword/pattern guess) · `UNKNOWN`. Only **EXPLICIT** and verified **DERIVED** relations may
  participate in canonical WHY / decision provenance; HEURISTIC is advisory and labelled as such.
- **No silent failure.** Canonical relationship persistence never uses `except: pass`. If a link write fails,
  it returns `LINKAGE_WRITE_FAILED` (recorded), task creation still succeeds, and the failure is recoverable.

### B. Handoff records — one session = one file + generated index
`data/handoffs/<ts>-<project>.json` (immutable per-session record, outcomes only) + a generated
`data/studio_handoffs_index.json` (disposable). Removes the append-JSONL merge hotspot. Backward read of the
legacy `data/studio_handoffs.jsonl` is retained.

## Authorities (no duplicate authority)
| Concern | Authority |
|---|---|
| Task lifecycle/state | mission ledger (`mission-state/v04/ledger.json`) — unchanged |
| Task **relationships** | Relationship Registry (`data/task_links/`) — LINKS only |
| Session outcomes (prose) | `docs/journal/` — the human narrative authority |
| Session outcomes (machine) | per-session handoff records (`data/handoffs/`) — queryable index; NOT a second prose authority |
| Releases | `data/golive_status.json` + `PROJECT_CONTROL/11_CHANGELOG.md` |

## Consequences
- Parallel AI branches no longer collide on one JSON/JSONL.
- The Context Pack reads the generated indices; if a record is missing it degrades to the journal (already so).
- Heuristic assignments are never shown as fact.
