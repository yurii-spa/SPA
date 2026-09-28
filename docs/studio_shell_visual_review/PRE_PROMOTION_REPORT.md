# PRE_PROMOTION_REPORT

Pre-promotion hardening. No push, no deploy, no production restart, no product features, no UI redesign.
Candidate branch `feature/mobile-owner-remote` untouched; the local integration was done in a throwaway
git worktree and removed.

## ADR_492_STATUS
**OWNER_REVIEW** (downgraded from a premature ACCEPTED). The Owner approved PREPARING/WIRING studio_shell
safety/core tests into candidate CI, but did NOT explicitly say «ACCEPT ADR-492». The CI implementation stays
in place for validation; ACCEPTED needs an explicit Owner accept. The AI must not infer acceptance.

## HANDOFF_AUTHORITY / HANDOFF_CONCURRENCY
- **Concurrency fixed:** handoffs are now **one immutable file per session** (`data/handoffs/<ts>-<project>.json`),
  not a single append-only JSONL → parallel AI branches add different files → **no merge hotspot**. A generated
  index + backread of the legacy `data/studio_handoffs.jsonl` are retained. (ADR-493.)
- **Authorities (no duplicate):** `docs/journal/` = **prose authority**; per-session records = machine-readable
  **index** (not a second prose authority); task lifecycle/state stays in the **mission ledger**; releases =
  `data/golive_status.json` + `PROJECT_CONTROL/11_CHANGELOG.md`.
- **Missing-file behaviour:** the Context Pack degrades to the newest journal filename (already so). Handoff
  write failure returns `HANDOFF_WRITE_FAILED` (surfaced, not swallowed).

## TASK_RELATIONSHIP_AUTHORITY
Audited the existing work objects: the **mission ledger** (`items`/`missions`/`work_graph`) is the director
subsystem's object — out of scope to modify and concurrency-owned by other work; **tracker cards** hold only a
few frontmatter fields and are a partial/different id-space. → Neither can own the full ref set, so a small
**Relationship Registry** is justified (**ADR-493, PROPOSED**): LINKS only (never lifecycle/state), **one record
per task** (`data/task_links/<id>.json`, concurrency-safe vs one giant JSON), every relation **provenance-typed**,
and **no silent failure** (`record_link` returns `LINKAGE_WRITE_FAILED`, surfaced + recoverable; the canonical
task still succeeds — the `except: pass` is removed).

## HEURISTIC_SEMANTICS
Relationship confidence/origin is now explicit: **EXPLICIT · DERIVED · HEURISTIC · UNKNOWN**. Only EXPLICIT and
verified-DERIVED relations feed canonical WHY. Keyword-based project assignment is labelled **HEURISTIC**;
research-orphan classification is **LIKELY_STANDALONE / LIKELY_MISSING_LINK (confidence HEURISTIC)** — never
shown as fact; only an in-text marker (e.g. "obsolete") is **DERIVED**. Task Detail shows per-link origin badges.

## PROMOTION_MANIFEST
Candidate & origin/main have **unrelated histories** + 39 tangled commits (only ~17 mine) → **do NOT cherry-pick
39 commits; SQUASH the net deliverable onto fresh origin/main.** Deliverable = clean-add packages
`spa_core/owner_remote/`, `spa_core/studio_os/`, `studio_shell/`, my new ADRs, `docs/studio_shell_visual_review/`,
`docs/architecture/`, `data/studio_projects.json` + `data/task_links/` + `data/handoffs/`; **KEEP**. Regenerated
UI artifacts (`studio_shell/*.json`) — **SQUASH** (derived; rebuild on integration). Shared files
(`spa_core/telegram/bot.py`, `CLAUDE.md`, `.github/workflows/{test,ci}.yml`, `docs/decisions/INDEX.md`,
`spa_core/tests/test_ci_covers_every_test_dir.py`) DIFFER from origin → **3-way merge** (my changes are additive
— apply the additions onto origin's current versions, do not overwrite). **DROP** intermediate fix/doc commits
superseded by later ones (the net content is what promotes).

### ⛔ HARD promotion blocker found by the dry run — ADR NUMBER COLLISION
origin/main already has **ADR-488/489/490/491** on DIFFERENT topics (e.g. origin `ADR-490-portfolio-level-
decision-owner-does-not-exist` vs mine `ADR-490-canonical-repository`; origin's HEAD commit even cites its own
`ADR-491`). Highest ADR on origin = **491**. Promoting my ADR-488–491 as-is creates **duplicate ADR numbers**.
→ My ADRs must be **renumbered to 492–497** (488→492 … 493→497) with **all references updated** (registry,
context provenance strings, tests, repo_status policy string, INDEX, STATE.md, reports) BEFORE promotion.
**Not done unilaterally** — the Owner accepted the decisions AS «ADR-490» and «ADR-491», so renumbering the
accepted decisions is an Owner-aware action, not an AI edit.

## LOCAL_INTEGRATION_BRANCH / INTEGRATION_TESTS
Dry run in a throwaway worktree from origin/main `13561f72` (candidate + the 210 unrelated dirty files never
touched). Applied the Studio OS net content. Results:
- `build_studio_core.py` ✓ (775 index items) · `build_slice.py` ✓ (Aave/Pendle) on the fresh base.
- Tests **113 passed / 1 failed**. The 1 failure = `test_search_finds_cross_object_history` asserting
  "canonical repository"→ADR-490 — a **direct symptom of the ADR-490 collision** (origin's ADR-490 is a
  different topic; my ADR-490-canonical wasn't uniquely resolvable). Renumbering fixes it. No other failure.
- Telegram gateway + all `spa_core.studio_os` / `owner_remote` imports ✓ (startup smoke).

## INTEGRATION_VISUAL_PARITY
**Confirmed identical** to the accepted candidate: same Studio-OS taxonomy sidebar, Memory/Search authority
ranking ("канон › отчёт"), "Position Passport" resolves, Work/Universe render. Screenshots
`INTEGRATION_{OVERVIEW,WORK,MEMORY,SYSTEM,UNIVERSE}.png` in `~/Desktop/StudioOS-ARB-Review/`.

## SHAs
- CANDIDATE_SHA  = `3e484752ec70`
- ORIGIN_MAIN_SHA = `13561f72c8c4`
- INTEGRATION_SHA = (ephemeral worktree, removed — built on origin/main + net content)
- PRODUCTION_SHA = `aeaab8bdca3b`

## FILES_EXCLUDED
- 210 unrelated dirty working-tree files (director/mission/rollback/zero-touch) — preserved, never promoted.
- Regenerated `studio_shell/*.json` (rebuilt on integration, not carried as history).

## REMAINING_OWNER_ACTIONS
1. **Decide ADR renumbering** (my 488–491 collide with origin's) — the accepted ADR-490/491 get new numbers;
   Owner-aware because it changes the identity of decisions the Owner accepted by number.
2. Accept/deny **ADR-492 (OWNER_REVIEW)** and **ADR-493 (PROPOSED)**.
3. Authorize the promotion push (squash + 3-way-merge the shared files) → origin/main (ADR-490 path).
4. Telegram production deploy/restart (separate).

## READY_FOR_OWNER_PROMOTION = NO
Blocked on the **ADR-number collision (renumber 488–491)** and the **3-way merge of 5 shared files** — both
must be resolved before a clean push. The code itself is proven to build, test (113/1, the 1 being the
collision), import, and render identically on a fresh origin/main base. Nothing pushed, merged, or deployed.
