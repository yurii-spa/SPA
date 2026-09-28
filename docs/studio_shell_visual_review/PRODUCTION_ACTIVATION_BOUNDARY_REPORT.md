# PRODUCTION_ACTIVATION_BOUNDARY_REPORT

Evidence-first audit + designed fix for the P0 that the autosync staged newly-promoted code into the active
production tree. **Nothing applied to production**: no restart, no Telegram, no capital, no RiskPolicy, no
launchd/autosync edit, no deploy. Candidate commit `4e175e9d` (not pushed). STOP for ARB review.

## AUTOSYNC_AUDIT
| Field | Finding |
|---|---|
| AUTOSYNC_SERVICE | `scripts/code_sync_from_origin.sh` — NOT a dedicated launchd agent; invoked from `agent_template.sh:161` (the canonical wrapper every fleet agent execs) before running the agent's module, and from `run_daily_paper_cycle.sh:85`. |
| SOURCE | `origin/main` via `git fetch` + `git checkout origin/main -- <paths>` (never `reset`, never touches HEAD). |
| DESTINATION | `~/Documents/SPA_Claude` — the **active runtime tree** (no staging dir). |
| COPIES | Whole dirs: `spa_core/ scripts/ tests/ architecture/` + `push_to_github*.py` + `CLAUDE.md` + `.claude/rules/`. NEVER `data/ docs/ studio_shell/ .github/`. |
| TRIGGER | Per-agent, soft + throttled `SYNC_MAX_AGE=600s` (10 min); + daily cycle. Not interval-daemon, not filesystem-watch — it piggybacks on agent startup. |
| ACTIVE_RUNTIME_PATH | `~/Documents/SPA_Claude/spa_core/…` (launchd execs `agent_<name>.sh` → `agent_template.sh` → the module, loaded from this tree). |
| CHECKS_GIT_SHA | Converges the tree to `origin/main` and records it in `data/code_sync_status.json`, but has **no approved-SHA gate** — it stages whatever origin holds. |
| STAGING_DIR | **None.** |
| OWNER_APPROVAL | **None.** |
| WRITES_INTO_ACTIVE_TREE | **YES** — this is the defect. |
| RESTART_RISK | **RESTART_WOULD_ACTIVATE** — the tree already holds `5b652577`; the next start of any agent loads it. |

## CURRENT_RISK
**RESTART_WOULD_ACTIVATE.** Evidence: `data/code_sync_status.json` = `{result: IN_SYNC, origin_main: 5b652577, files_changed:0, ts: 2026-09-28T10:21:33Z}` (filesystem converged to the promoted SHA ~1 min after the push); running processes still hold pre-push in-memory code (Telegram bot up since 2026-09-27 03:26; only 28-Sept fleet starts were 11:12, before the 10:10Z push) → **inert now, but any restart activates staged code**. Mitigating (not eliminating) factor: money-path isolation holds — no `paper_trading/risk/governance/execution/adapters` module imports the promoted packages, and the promotion ADDED only new packages (0 existing files modified), so even a money-path restart loads byte-identical execution code. Surfaced as **P0**; autosync NOT autonomously disabled (owner-gated).

## CANONICAL_SHA / STAGED_SHA / ACTIVE_SHA
- CANONICAL_SHA = `5b652577` (origin/main)
- STAGED_SHA    = `5b652577` (on the production filesystem — what a restart would load)
- ACTIVE_SHA    = **UNKNOWN** — the fleet records no active-release marker, and the in-tree checkout destroyed the evidence of what was loaded. Provably ≠ STAGED and predates `5b652577`. **Not faked from a repo HEAD** (production git HEAD `aeaab8bd` is git-only and NOT what executes).

## RESTART_BEHAVIOR / SELF_HEAL_BEHAVIOR / REBOOT_BEHAVIOR
All three go through `agent_template.sh` (sync-then-exec) → today all **would activate the staged `5b652577`**. With the proposed guard wired, all three call the same pure `restart_decision(staged, approved)` and fail-CLOSED (`DEPLOYMENT_APPROVAL_REQUIRED`) or load the approved release — path-independent, so none can bypass approval.

## SELECTED_ARCHITECTURE
**Option A — minimal in-tree gate** (smallest safe correction): autosync records STAGED and only checks code into the tree when `STAGED == APPROVED` (else fail-CLOSED, tree stays on approved release); `agent_template.sh` gains the restart guard; each agent writes `data/active_release.json` at startup. Reuses the existing script + status file; no launchd/path change.

## ALTERNATIVES
**Option B — `releases/<sha>/` + ACTIVE symlink**: physical release isolation; activation = repoint symlink (owner-gated); rollback = repoint to prior release. Cleaner but a large fleet-wide path-resolution migration. Recommended as later hardening, not now. (No existing `releases/`/activation mechanism found → nothing to reuse there.)

## FILES_TO_CHANGE
Built now (read-only, candidate `4e175e9d`, NOT applied to production):
- `spa_core/studio_os/release_state.py` (new — three-state measurement + pure guard)
- `spa_core/studio_os/repo_status.py` (release block; git HEAD flagged NOT-active)
- `studio_shell/studio_core.js` (CODE SYNC card → CANONICAL/STAGED/ACTIVE/APPROVED + status)
- `spa_core/tests/test_release_boundary.py` (A–H)
- `docs/decisions/ADR-500-*.md` (PROPOSED) + `INDEX.md`

Proposed for the migration (owner-gated, NOT yet touched): `scripts/agent_template.sh` (startup active-marker write + restart guard), `scripts/code_sync_from_origin.sh` (STAGED-vs-APPROVED gate), seed `data/approved_active_release.json` with the current known-good SHA.

## TESTS
`spa_core/tests/test_release_boundary.py` — **A–H all PASS** (hermetic, tmp markers, no production touch, starts nothing, moves no capital): A canonical moves/ACTIVE unchanged · B autosync stages/ACTIVE unchanged · C unapproved restart can't activate STAGED · D owner-approved activation changes ACTIVE · E failed activation rolls back to previous · F reboot/self-heal can't bypass approval · G reports the three states (UNKNOWN when unproven) · H no money-path path touched (both directions). Studio OS suite still green (11).

## UI_STATUS_MODEL
Project Home CODE SYNC card now shows **CANONICAL / STAGED / ACTIVE (/ APPROVED)** with headline
`⚠ DEPLOYMENT APPROVAL REQUIRED` when ACTIVE is UNKNOWN or STAGED≠ACTIVE, plus the `restart:` decision. Production git HEAD demoted to a provenance line labelled "git HEAD only, NOT active". Live values right now: CANONICAL 5b652577 · STAGED 5b652577 · ACTIVE UNKNOWN · STATUS DEPLOYMENT_APPROVAL_REQUIRED.

## ROLLBACK_MODEL
- CANONICAL rollback = `git revert` the commit on origin/main (never force-push).
- PRODUCTION rollback = set `APPROVED` back to the prior known-good SHA; the guard directs the next restart to it (`LOAD_APPROVED_NOT_STAGED`). No git history rewrite; independent of canonical.

## ADR_REQUIRED
**ADR-500 (PROPOSED)** — `docs/decisions/ADR-500-production-activation-boundary.md`. Does not rewrite ADR-494; clarifies Canonical ≠ Staging ≠ Activation and constrains the autosync. Awaits explicit Owner ACCEPT.

## OWNER_ACTION_REQUIRED
1. Review/accept ADR-500 + Option A. 2. Then (owner-gated) wire the startup active-marker + restart guard + STAGED-vs-APPROVED gate, seeding APPROVED with the current known-good release so nothing activates until an explicit owner activation. 3. Decide whether to pause the autosync in the interim (a production action — not taken autonomously). 4. The eventual owner-gated production restart/Telegram deploy remain separate.

## Final flags
```
CANONICAL_ISOLATED_FROM_ACTIVE = NO   (autosync still writes into the active tree; fix designed+built, NOT applied)
STAGING_MODEL_READY            = YES  (three-state measurement live + tested; ACTIVE honestly UNKNOWN)
RESTART_GUARD_READY            = YES  (pure fail-CLOSED guard implemented + A–H tested; ready to wire, not wired)
PRODUCTION_SAFE_TO_RESTART     = NO   (RESTART_WOULD_ACTIVATE staged 5b652577 without approval; guard not yet wired)
```
## NOTE — origin/main auto-advanced during this work
An automatic director cycle advanced origin/main `5b652577 → 603b3007` while this audit ran. Verified:
**my promotion `5b652577` remains an ancestor (preserved, not overwritten)**; studio_os + ADR-492..497 still
present. That cycle also consumed **ADR-498** for a different topic, so this proposal was renumbered
**498 → ADR-500** (499/500/501 free). This auto-advance is itself further evidence for the boundary: canonical
moves on its own, so STAGED/ACTIVE separation is not optional. My boundary work is on the candidate branch
(unpushed); ADR numbers must be re-verified at any future promotion.

STOP for ARB review. No production restart, no deploy, no launchd/autosync change performed.
