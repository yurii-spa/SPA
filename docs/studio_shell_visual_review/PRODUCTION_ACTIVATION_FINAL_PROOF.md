# PRODUCTION_ACTIVATION_FINAL_PROOF

ARB proof pass. **No production change**: no restart, no Telegram, no launchd, no capital, no RiskPolicy,
ADR-500 NOT accepted (stays PROPOSED). Candidate branch only, not pushed.

## CURRENT_CANONICAL / CURRENT_STAGED / CURRENT_APPROVED / CURRENT_ACTIVE
Re-measured now (origin auto-advanced again since the last report):
- CURRENT_CANONICAL = `603b30077aca` (origin/main — advanced from 5b652577 by an automatic director cycle)
- CURRENT_STAGED    = `603b30077aca` (autosync already converged the production filesystem; `code_sync_status.json` result=SYNCED at 2026-09-28T11:02:07Z)
- CURRENT_APPROVED  = **None** (no approval mechanism exists yet)
- CURRENT_ACTIVE    = **UNKNOWN** (no startup marker; running processes predate the push and the in-tree checkout erased the evidence — not faked from a repo HEAD)
- LAST_AUTOSYNC = 2026-09-28T11:02:07Z → 603b3007 SYNCED · NEXT_KNOWN_AUTOMATIC_EXECUTION = the 08:00 daily paper cycle (and any agent restart / self-heal, throttled 10 min).
- STAGED is **not** still 5b652577 — it tracks canonical automatically, exactly the defect.

## DAILY_CYCLE_EXECUTION_PATH (P0 Q2 — proven)
`scripts/run_daily_paper_cycle.sh`, exact order: `cd ~/Documents/SPA_Claude` (l.37) → **`bash scripts/code_sync_from_origin.sh`** (l.85, converges tree to origin/main) → **`$PYTHON -m spa_core.paper_trading.cycle_runner --verbose --live`** (l.101, the money-path engine, imported from the just-synced tree) → `deploy_site_snapshot.py` (l.133) → `fleet_parity_check.py` (l.146). **The same scheduled invocation syncs then executes the money path from the new filesystem** → **SCHEDULED_RUN_WOULD_ACTIVATE** (strictly worse than restart-only).

## OTHER_SYNC_THEN_EXEC_PATHS
`scripts/agent_template.sh` (the wrapper every fleet agent execs): sync (l.161, soft/throttled 10 min) then `exec` the agent's module from the tree. So both the scheduled cycle and every agent (re)start are sync→exec-from-tree. No other standalone sync→exec script found.

## CURRENT_RISK
**SCHEDULED_RUN_WOULD_ACTIVATE** (highest applicable; `ACTIVE_UNAPPROVED`/`ACTIVE_UNKNOWN` also hold). Evidence: STAGED=603b3007 on disk; next 08:00 cycle syncs-then-runs `cycle_runner --live` from it with no approval gate. Mitigation (does not remove the class): my promotion added only new packages — no money-path file changed — but automatic canonical writers *could* change money-path code and it would auto-activate. Not mitigated in production (owner-gated); surfaced as P0.

## APPROVED_CODE_SOURCE (proven)
LOCAL git objects. `release_activation.materialise_release(sha)` runs `git archive <sha>` (no network for a known-local sha; `git cat-file -e` guards) and extracts atomically to an immutable `releases/<sha>/` (temp dir + rename; a partial materialise is discarded, the active release untouched). `exec_root` verifies the dir self-identifies via `.release_sha` before returning it. Object missing → **FAIL_CLOSED**, never the tree. Proven by `test_release_activation_shell.py::test_approved_material_from_git_objects` + `_missing_release_recovers_from_object`.

## OPTION_A_PROOF
**Marker-only Option A is INSUFFICIENT — proven.** `python -m spa_core...` imports from the filesystem
(`~/Documents/SPA_Claude/spa_core`, demonstrated live), so a marker `APPROVED=A` cannot make it execute A while
the tree holds B. That is the ARB "NOT acceptable" case. Option A could only work by *restoring* APPROVED into
the tree before exec — non-atomic, TOCTOU-racy against the concurrent autosync, partial-write risk on the money
path. Rejected on the deciding requirement.

## OPTION_B_COMPARISON
| criterion | A (in-tree restore/gate) | B (immutable releases/<sha> + pointer) |
|---|---|---|
| **prove exact code before exec** | **NO** (mutable tree, TOCTOU) | **YES** (content-addressed, self-stamped) |
| implementation size | smaller | larger |
| parallel-agent safety | poor (shared mutable tree) | good (each release immutable) |
| rollback reliability | fragile (non-atomic re-checkout) | atomic (repoint pointer) |
| partial-write risk | HIGH | LOW (temp+rename; active untouched) |
| reboot/self-heal | must re-checkout (race) | deterministic (exec from dir) |
| auditability | weak | strong (`.release_sha` verified) |

## SELECTED_ARCHITECTURE
**Option B — immutable `releases/<sha>/` materialised from git objects + owner-approved ACTIVE pointer.**
Selected on the deciding requirement (prove exact code before exec), not on size. Immediate safety stance until
wired: **FAIL_CLOSED** (a start that cannot resolve an approved release executes nothing).

### State machine (Option B)
| transition | precondition | action | postcondition | fail-CLOSED | audit |
|---|---|---|---|---|---|
| canonical_changed | push to origin/main | — (canonical only) | CANONICAL=new | — | commit sha |
| stage | autosync ran | record STAGED (may still checkout tree — unchanged) | STAGED=new | n/a | code_sync_status.json |
| approve | owner action | write APPROVED=sha; `materialise_release(sha)` | releases/<sha>/ exists, self-stamped | object missing → refuse approve | approved_active_release.json |
| activate | APPROVED==sha, release present | repoint ACTIVE→sha | ACTIVE=sha | corrupt/missing → refuse | active_release.json |
| restart / self_heal / reboot / scheduled_cycle | any | `exec_root(APPROVED)` → exec from release dir | runs APPROVED, not STAGED | no/curropt approval → execute nothing | active marker = execed sha |
| activation_failed | health check red post-activate | keep APPROVED at prior good | ACTIVE stays prior | — | log |
| rollback | owner action | APPROVED←prior good sha (release already materialised) | next start runs prior; **no git rewrite** | prior release missing → re-materialise or refuse | approved marker |

## SHELL_LEVEL_TEST
`spa_core/tests/test_release_activation_shell.py` — hermetic (throwaway git repo + tmp releases), REAL
subprocess exec: with STAGED=B in the tree and APPROVED=A, exec prints `RELEASE_A` (not B); the staged tree is
never the exec root; no approval → FAIL_CLOSED (no app module loads); daily-cycle-staged-B-no-approval cannot
run B; missing release recovers from git object; rollback reactivates the prior release. **7/7 pass.** Plus the
pure state-machine `test_release_boundary.py` A–H (8/8) and `test_studio_os.py` (11/11) — **26 pass**; no
money-path module imports either release module.

## ROLLBACK_PROOF
`test_rollback_reactivates_prior_release`: both A and bad-B materialised; setting APPROVED back to A makes the
next exec run A — proven by subprocess output, **no git history rewrite, no force-push, no network**. Atomic
(pointer repoint). Independent of canonical rollback (`git revert` on origin/main).

## ADR_499_STATUS
**PROPOSED** (unchanged — not accepted). Revised: selected architecture changed from marker-only Option A to
Option B with the proof inline; three-state model + guard retained.

## FILES_REQUIRED_TO_WIRE (owner-gated; NOT touched in production)
1. `scripts/agent_template.sh` — before `exec`: `activation_plan(APPROVED, STAGED)` → materialise if needed →
   exec the module with `releases/<APPROVED>/` at module-path front; FAIL_CLOSED if unapproved; write
   `data/active_release.json` = the sha actually execed.
2. `scripts/run_daily_paper_cycle.sh` — same gate before `cycle_runner --live` (and the later steps).
3. `data/approved_active_release.json` — owner-gated; seed with the current known-good release.
4. (materialiser invoked on `approve`, reusing `release_activation.materialise_release`).
Built + proven now (read-only, candidate): `spa_core/studio_os/release_state.py`, `release_activation.py`,
`repo_status.py` release block, `studio_shell/studio_core.js` CODE SYNC card, tests, ADR-500.

## OWNER_ACTION_REQUIRED
1. Review this proof + Option B. 2. Decide the **interim** stance for the live machine: because the next 08:00
cycle SCHEDULED_RUN_WOULD_ACTIVATE, the only ways to hold production on known code before Option B is wired are
(a) pause the autosync/daily-cycle, or (b) wire the FAIL_CLOSED gate — **both are production actions requiring
your authorization; neither taken.** 3. Then accept ADR-500 + authorize wiring (one agent first, then fleet,
then the cycle). 4. Production restart / Telegram deploy remain separate.

## SECONDARY — P1 ADR number race (filed, not solved here)
`docs/ideas/2026-09-28-adr-number-race-p1.md`: automatic origin/main writers can allocate the same ADR number
concurrently (the ADR-498 collision). Recommend a deterministic allocation / mandatory server-checked pre-push
interlock. No implementation in this task.

## Final flags
```
EXACT_EXECUTABLE_SHA_PROVABLE = YES  (with Option B — proven by real-exec shell test; marker-only Option A = NO)
DAILY_CYCLE_BYPASS_CLOSED     = NO   (sync→exec gate designed+proven, NOT wired to run_daily_paper_cycle.sh)
RESTART_BYPASS_CLOSED         = NO   (guard designed+proven, NOT wired to agent_template.sh)
ROLLBACK_EXECUTABLE_PROVEN    = YES  (repoint→exec prior release proven by subprocess, no history rewrite)
READY_TO_ACCEPT_ADR_499       = NO   (stays PROPOSED; wiring + interim stance are owner decisions)
PRODUCTION_SAFE_TO_RESTART    = NO   (SCHEDULED_RUN_WOULD_ACTIVATE; nothing wired)
```
No production changes. STOP for ARB.
