# STUDIO_OS_ACCEPTANCE_PASS_REPORT

> **⚠ ADR RENUMBER (2026-09-28, Owner-authorized):** ADR numbers in this historical report predate canonical
> promotion. Mapping: **488→492 · 489→493 · 490→494 · 491→495 · 492→496 · 493→497** (origin/main already
> occupied 488–491). Numbering only — decisions unchanged. Current truth: `FINAL_PRE_PROMOTION_REPORT.md`.


Acceptance / promotion / linkage pass. No new product features. Owner explicitly ACCEPTED ADR-490/491 and
approved wiring mandatory Studio OS safety/core tests into canonical CI. Push / merge-to-main / production
restart remain **NOT authorized** — none performed.

## OWNER_DECISIONS_REQUIRED  → RESOLVED (owner-confirmed 2026-09-28)
| ADR | Decision | Status |
|---|---|---|
| ADR-490 | Canonical repository + promotion/deployment policy (origin/main = truth; candidate worktree; push→autosync→owner-gated restart) | **ACCEPTED** (owner: «ACCEPT ADR-490 and ADR-491») |
| ADR-491 | Studio OS Core architecture: Project Registry · Context Pack · ADR decision seam · handoff · search — reuse existing canon | **ACCEPTED** |
| ADR-492 | Wire studio_shell/ safety/core tests into canonical CI | **ACCEPTED** (owner approved the prep/wiring) |

## HANDOFF_PERSISTENCE
`data/studio_handoffs.jsonl` was gitignored (runtime-only) → now **force-tracked & committed to HEAD** →
canonical: a fresh clone / another machine contains the handoff history. Journal (`docs/journal/`) stays the
prose authority; the jsonl is the machine-readable outcomes index the Context Pack reads. Not a second DB.
**SESSION_HANDOFF_READY = YES** (persists across sessions and machines).

## CANONICAL_LINKAGE_MODEL
`spa_core/studio_os/links.py` + `data/studio_task_links.json` (canonical): a relationship **overlay keyed by
the existing task id — NOT a second task model**. Fields: project_id · acceptance_criteria · decision_refs ·
research_refs · evidence_refs · implementation_commit · outcome · handoff_ref · release_ref. The Owner-Remote
gateway **persists project_id + source at task CREATION**; Task Detail displays the chain (real where present,
MISSING where absent). A task can travel Idea/Research→Decision→Task→Implementation→Commit→Handoff→Result
(proven by `test_task_link_overlay_travels`). No guessed links.

## ACTIVE_WORK_BACKFILL
Historical mission-ledger work items get a **provable** derived overlay: project_id by keyword + decision_refs
= ADR ids literally named in the item text (none of the current 12 name an ADR → project_id only, honestly).
New work created through the gateway carries project+source from creation. No blind backfill of history.

## RESEARCH_ORPHAN_CLASSIFICATION
13 research / 2 linked / **11 orphans classified** (never fabricated links): **LEGITIMATE_STANDALONE 6**
(competitor/devops/regulatory/cloudflare/fastapi/gnosis — reference material), **MISSING_LINK 2** (landing-
conversion, smart-contract-security — cite the evidence standard but no ADR names them), **UNKNOWN 3**
(investor-cabinet-ux, mac-mini-reliability, frontend-stack). Each carries a stated reason; shown in the
Research UI. Goal = understand *why* unlinked, not 100% linkage.

## CI_INTEGRATION
studio_shell tests are **fast (<1 s total) and CI-safe** (no browser; node — present on GitHub ubuntu — only
for the classifier-parity test), so the whole suite is wired in (no split needed): `read-model invariants ·
classifier parity · RED safety · CSRF/rebinding guards · projector/search/context contracts`. Added
`studio_shell/` to CLAUDE.md prescribed run + `test.yml` + `ci.yml`; removed the `_ALLOWED_UNCOVERED`
exemption; updated the gating-dirs baseline. Gating tests green (prescribed-parity · ci-covers · exclusions).

## PROMOTION_PLAN (audit only — NO push/merge/restart)
- CURRENT_CANONICAL_SHA  = `e58e162924c8` (origin/main)
- CURRENT_CANDIDATE_SHA  = `a58478507fcf` (feature/mobile-owner-remote)
- CURRENT_PRODUCTION_SHA = `aeaab8bdca3b` (~/Documents/SPA_Claude)
- COMMITS_TO_PROMOTE = the Studio OS / Owner Remote series (`84fbc42c8 … a58478507`, ~18 core commits:
  Visual OS + Owner Remote seams → Telegram gateway → Aave/Pendle slices → Studio OS Core → 30h sprint →
  acceptance). Telegram gateway (`f21b11611`) **is** in the set (Item 9 ✓).
- CONFLICTS = **candidate and origin/main have UNRELATED HISTORIES** (`git merge-tree` → "refusing to merge
  unrelated histories"). A direct merge is impossible → the **clean approach is required**:
  ```
  git fetch origin
  git switch -c integration/studio-os origin/main          # fresh canonical base
  git cherry-pick <the ~18 Studio OS/Owner-Remote commits>  # replay accepted work only
  # resolve conflicts intentionally (studio_shell/*, spa_core/{owner_remote,studio_os}/*, docs/decisions/ADR-49x, CLAUDE.md CI line)
  SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest tests/ spa_core/tests/ scripts/tests/ spa_core/analytics/gross_of/ research/cards/ studio_shell/ -q -p no:randomly
  # then Owner-authorized: push_to_github.py the integration branch → origin/main (ADR-490)
  ```
  Do NOT drag the candidate's unrelated history into main.
- UNRELATED_DIRTY_WORK = **210 uncommitted files** in the working tree (director/mission/rollback/zero-touch —
  other in-flight work; the 59 pre-existing test failures' subject). **Preserve, do not promote.**
- ROLLBACK_POINT = origin/main `e58e162924c8`. Rollback = `git revert` the integration commit on origin/main
  (never force-push — pre-push hook + the 2026-08-29 incident); for a hot agent, restore backup + restart.
- VALIDATION_COMMANDS = the prescribed CI run (above, now incl. `studio_shell/`) + `python3 studio_shell/
  build_studio_core.py` + the Studio OS test files.

## VISUAL_REVIEW  / SCREENSHOT_DIRECTORY
15 fresh screenshots from candidate tip `a58478507` → **`~/Desktop/StudioOS-ARB-Review/`** (+ README index),
non-canonical, ready to upload to ChatGPT/ARB. Console errors: 0. Horizontal overflow: 0 at 390/430/1440/1920.
UI review fixed evident defects this pass (wide-screen empty area, project-home mobile grid/card wrap). No
shell redesign; FounderOS retained.

## TELEGRAM
Gateway is in the promotion set (`f21b11611`). **Not deployed.** Production rollout = a separate Owner-approved
deploy/restart after canonical promotion.

## TESTS
Studio OS + Owner Remote + CI-gating suites green (studio_os 12 · owner_remote incl. OS queries · mobile
parity/CSRF/RED · ci-covers/prescribed-parity). Full regression (prior): 0 introduced (6 fixed) · 59
pre-existing/unrelated.

## CANDIDATE_SHA
`a58478507fcf42c6d581db0620bfd1180a2b6b8a` (branch `feature/mobile-owner-remote`, not pushed).

## REMAINING_BLOCKERS (all owner-gated)
- Canonical promotion (push to origin/main) — clean cherry-pick plan prepared; awaits Owner authorization.
- Telegram production deploy/restart — awaits Owner.
- ARB visual acceptance of the 15 screenshots.

## Flag
**DESKTOP_TIER1_CORE_UX = CANDIDATE_READY_FOR_ARB** (not self-stamped PASS — awaits Owner/ARB screenshot review).
