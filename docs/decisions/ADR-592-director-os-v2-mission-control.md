# ADR-592 · Director OS v2 = Mission Control evolved: one read-only owner cockpit, Company Truth computed on read

- **Status:** Accepted (2026-10-06, RM-TRUTH-01 Wave 2). Design: `docs/rm_truth/DIRECTOR_OS_V2_DESIGN.md`; implemented by WP1 (Company Truth read model) and WP2 (mobile owner UI).
- **Date:** 2026-10-05
- **Epic:** RM-TRUTH-01 (contract C9, with C3, C4, C5, C6, C10 and C11 of ADR-580)
- **Supersedes (presentation only):** Director OS web cockpit `:8788` (`scripts/cartographer/director_build|director_server`, launchd `com.spa.director_build`, `com.spa.director_server`), Studio Shell (`studio_shell/`, `:8778`, ADR-492), the repo dashboard `:8767` (`com.spa.dashboard`)
- **Restates as accepted:** the Director OS charter ("reads, derives, never a second backlog / memory / truth"). Origin ADR-492 and ADR-552 cite it as "ADR-469". On origin that number is an unrelated ADR. The only text is `SPA_control_plane_audit/16-…ARCHITECTURE.md` §13 plus an off-origin shadow `~/studio-os-scratch/v03/docs/decisions/ADR-469-studio-os-v03-mission-control-plane.md` (status `DECISION_PROPOSED`, 2026-09-24, and about a mission graph rather than the charter).
- **Keeps:** Mission Control (ADR-552) as the single cockpit; `spa_core/studio_os/director_report.py` as the text read model behind Telegram `/report` and Bridge `/needs`; the Nimbalyst board.
- **Owner subjects touched (ADR-285):** none decided here. Unloading launchd agents is a prod-agent action (`.claude/rules/deployment.md` p. 6). Deleting the 4.8 GB Director bundle is irreversible (subject 3). Both are listed under "What stays with the owner".

## Context

- **The owner cockpit has been built seven times.** Four of those builds happened between 2026-09-20 and 2026-10-03 (MASTER_CURRENT_STATE_MAP §0, A5 §3).
- **The same owner queue is shown with different counts.** Origin has 11, the prod bot 12, Director OS shows "6 ждут вашего решения", and Mission Control 11. Mission Control also shows a second "pending 4".
- **Mission Control and Director OS disagree on the same cards.**
  - Mission Control labelled subjects by keyword (`risk_class()`).
  - Director labelled them with a different keyword list (`SUBJECT_HINTS`).
- **Each cockpit has its own blind spots and strengths.**
  - Director OS has the more honest triage ("6 real / 11 queue defects") and per-item provenance.
  - It also shows a dead source as a live gate: "приёмка не получена 107 дней" is read from `data/gate_status.json`, which is frozen since 2026-06-20.
  - Its publish has been frozen since 2026-09-20.
- **Mission Control is the one that is live and mostly honest.** It rebuilds every 300 s and declares an UNKNOWN form for 30 contract rows. Measured on 2026-10-05, bundle `b-20261005T143018Z` showed these defects:
  1. It shows `current_epic = #10 Later engines — QUEUED`. RM-TRUTH-01 is not on `docs/ROADMAP.md`, and the parser falls back to the first QUEUED item when nothing is in progress.
  2. It shows backups as `HEALTHY` while `offsite_is_real_remote=false`.
  3. It has no scoped readiness and no Problems view.
  4. Its first level shows commit hashes and launchd labels.
- **The failure the charter forbids has already happened once.** A projection grew into a second truth: Studio Shell answered GREEN from an empty projection (ADR-521).

## Decision

1. **One cockpit.** Director OS v2 *is* Mission Control (`spa_core/studio_os/mission_control.py` + `mission_build.py` + `mission_server.py` + `mission_ui/`), evolved in place.
   - No eighth cockpit, no new server, no new port and no new launchd agent.
   - Local stays `127.0.0.1:8790`. The phone uses `:8792` behind Cloudflare Access, unchanged from ADR-552.

2. **Charter (accepted text).** Director OS **reads**. It **derives**. It never writes state, never touches the money path, and never becomes a second engine, backlog, memory or source of truth.
   - Owner answers and intake stay in their owning mechanisms: the SPA bot for decisions and the kill switch, and the Bridge bot through `owner_remote.cli` confirm-first.
   - The cockpit only links to them.
   - The UI has **no** control that moves money, arms or clears the kill switch, answers a decision, or changes a card.

3. **Company Truth is computed on read (C4).**
   - A pure module `spa_core/studio_os/company_truth.py` is called **only** by `mission_control.build()`.
   - Every value is a cell `{value, metric_type, state, as_of, canon, freshness, unknown_ru}`.
     - `canon` names the canonical writer artifact or function (C1, `architecture/provenance.json`).
     - `state ∈ MEASURED | MEASURED_ZERO | NOT_MEASURED | NOT_ENOUGH_HISTORY | STALE | CORRUPT` (inv. #17). A missing source renders the cell's Russian UNKNOWN text, never 0, empty or green.
   - There is no stored Company Truth file. The bundle's `mission.json` is a **render cache** read only by `mission_server`. Deleting it and rebuilding from canon with the same `now` must give a byte-identical model.
   - **No agent, gate, monitor, bot or script may import `company_truth` or read a Mission Control bundle.** This is enforced by an import ratchet in the same way as the `spa_core/execution` ban. The allowlist is `mission_control.py` and its tests.
   - Shared primitives are what other readers reuse:
     - `readiness_scopes.scoped_readiness`
     - `owner_queue.subject.subject_of`
     - `problem_store.load_store`
     - `trading_research.read_model.trading_lab_view`
     - `capital_shadow` / `investment_cio` / `research_factory` `read.latest`
     - `defi_engine.package_status.public_view`
     - `reporting.compound_apy`

     `director_report` keeps using these primitives and never the Company Truth composition.

4. **Readiness is scoped, never one green (C3).** The cockpit shows the six `readiness_scopes` scopes side by side.
   - Any worst-of badge is labelled "худшее из N областей — не оценка здоровья".
   - Inventory "29/29" is never shown as readiness.

5. **One owner queue, declared subjects (C5).**
   - Subjects come only from `subject:` frontmatter through `owner_queue.subject`.
   - A missing subject means UNKNOWN. Those cards are shown as "тема не объявлена — разбирает агент", separately from the owner's real questions.
   - Director's triage semantics (owner subject / queue defect / re-measure premise) are carried into Mission Control. `risk_class()` keyword guessing is gone.

6. **Information architecture.** The cockpit has an Owner Home in plain Russian with a five-tile strip: Система · Доходность · Продукт · Что делает Claude · Нужно от меня. It has three domains:
   - CAPITAL
   - STUDIO OS (absorbs today's "System" tab)
   - EARN DEFI PRODUCT

   Commit hashes, PIDs, launchd labels and JSON paths appear only in drill-down evidence, never on the first level. The spec is in `DIRECTOR_OS_V2_DESIGN.md`.

7. **"What is Claude working on" is derived, not stored.** The canon is the existing announcement log `data/session_changes.jsonl` (writer `scripts/log_session_change.py`), with liveness from the existing `session_state()`, the epic from `docs/ROADMAP.md`, and the stage from `build_loop.lineage`. No new store.

8. **One fleet definition (C11).** Typed counts are derived from `architecture/manifest.json` × `launchctl list` (through `director_report`) × `agent_health.json` × `architecture/roles.json`. The headline is "в норме X из Y объявленных".

9. **Backups are reported as three facts (C10):** LOCAL_BACKUP, OFF_HOST_BACKUP and RECOVERY_TESTED. When `is_real_remote` is not true, OFF_HOST is `SAME_HOST` and never green.

10. **`director_report` stays** as the Telegram text read model. It may not grow a web surface again.

## Retirement (presentation superseded; actions belong to the owner)

| Surface | Verdict | What happens | Who |
|---|---|---|---|
| Director OS `:8788` (`com.spa.director_server`, `com.spa.director_build`) | SUPERSEDED (presentation) | Its triage and provenance semantics are ported into Mission Control first. Then unload both agents and mark them `intent: retired` in the manifest (the C11 rule: retired = unloaded **and** recorded). The 4.8 GB bundle directory is deleted only on explicit owner approval. | owner (unload; delete) · agent (port; manifest edit after the unload) |
| Studio Shell `:8778` | SUPERSEDED | Not running and absent from prod. Archive the code by ADR; do not delete history. | agent |
| `:8767` `com.spa.dashboard` (+ `dashboard_watcher`) | SUPERSEDED, unsafe | It serves the repo root including `.git/` on loopback. Unload it. | owner |
| `director_report.py` | KEEP | Text read model for Telegram `/report` and Bridge `/needs`. | — |

## Acceptance (machine, before the epic is called done)

- **`test_company_truth_import_ratchet`.** Only the allowlist imports `company_truth`, and no file outside `mission_server` and `mission_build` names the bundle path.
- **`test_mission_rebuild_from_canon`.** Delete the bundle, rebuild with a fixed `now`, and expect an identical model and identical rendered first-level text.
- **`test_unknown_when_canon_missing`.** Removing each canon in turn yields the declared Russian UNKNOWN for that cell and never 0, `[]` or green.
- **`test_no_money_action_reachable`.**
  - The static UI has no form, no `fetch` with a non-GET method, and no `act:`/`/pause` link.
  - The server answers 405 to anything other than GET and HEAD.
- **`test_scoped_readiness_never_collapsed`.** All six scopes are present, and no field named `overall`/`ready` outside a scope is green-coloured.
- **`test_first_level_has_no_raw_ids`.** The rendered Home and domain first levels carry no 7–40-hex commit hashes, no `com.spa.` labels, no `pid`, and no `data/…json` path.

## What stays with the owner

- Unload `com.spa.director_server`, `com.spa.director_build`, `com.spa.dashboard`, `com.spa.dashboard_watcher` (deployment.md p. 6).
- Delete Director's 4.8 GB bundle directory and any worktrees (subject 3).
- Any public wording that the cockpit mirrors, for example the public "Go-live progress 29/29" (subject 2). The cockpit only reports it.

## Consequences

- **Plus:**
  - One URL answers the owner's 30-second questions.
  - Every number links to its canon.
  - The cockpit cannot become a second truth by construction, because the ratchet makes it impossible for anything to consume it.
- **Minus:**
  - Typed fleet and "what Claude does" depend on sessions announcing themselves. Interactive sessions that do not announce show as "необъявленная работа: N", which is honest but noisy until the protocol is followed.
  - Until cards declare `subject:`, every queued question shows "тема не объявлена".
- **Forbidden:**
  - a Company Truth file;
  - any reader of the bundle other than the server;
  - a cockpit button with side effects;
  - a single overall-green badge;
  - showing inventory 29/29 as readiness;
  - an eighth cockpit.

## Number hygiene

Drafted as «ADR-571»; parallel cycles took 567–575 on origin while RM-TRUTH-01 was in flight, so the epic
moved its decisions to a reserved block: ADR-580 (contracts, delivered 96a935fda), ADR-590 (Trading
lineage), ADR-591 (memory), ADR-592 (this), ADR-593 (Conservative backfill). Checked with
`scripts/adr_number.py check` immediately before delivery.
