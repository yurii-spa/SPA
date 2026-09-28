# TRUSTED_BOOTSTRAP_FINAL_REPORT

ARB final gate: the launcher itself must not be mutable by autosync. Evidence-first audit + reuse of the
existing root-owned trusted plane + tamper hard-gate proof. **No production change**: no restart, no Telegram,
no launchd edit, no capital, no RiskPolicy; ADR-500 stays PROPOSED. Candidate only, not pushed.

## ENTRYPOINT_AUDIT (actual loaded plists)
Every fleet/cycle process's FIRST executed file is inside the autosync domain — the launcher is mutable:

| SERVICE | LAUNCHD_LABEL | PROGRAM_ARGUMENTS (first file) | IN_AUTOSYNC_DOMAIN | USER | RESTART | MONEY_PATH |
|---|---|---|---|---|---|---|
| Daily paper cycle | com.spa.daily_cycle | `/bin/bash ~/Documents/SPA_Claude/scripts/run_daily_paper_cycle.sh` | **YES** (`scripts/`) | yuriikulieshov | scheduled | **YES** (`cycle_runner --live`) |
| Strategy lab | com.spa.strategy_lab_paper | `/bin/bash …/scripts/agent_strategy_lab_paper.sh` | **YES** | user | KeepAlive/sched | advisory |
| Telegram | com.spa.telegram_bot | `/bin/bash …/scripts/agent_telegram_bot.sh` | **YES** | user | KeepAlive | no |
| Watchdog | com.spa.watchdog | `/bin/bash …/scripts/agent_watchdog.sh` | **YES** | user | sched | no |
| Orchestrator | com.spa.orchestrator | `/bin/bash …/scripts/agent_orchestrator.sh` | **YES** | user | sched | no |
| (all ~84 com.spa.* agents) | — | `/bin/bash …/scripts/agent_<role>.sh` → `agent_template.sh` | **YES** | user | — | mixed |

All go `/bin/bash …/scripts/*.sh` → `agent_template.sh` (or the cycle script), **all inside `scripts/` (∈ autosync CODE_PATHS)**. Confirmed the boundary defect: unapproved code could replace the guard.

## EXISTING_TRUSTED_RUNNER_REUSE
An accepted root-owned trusted plane already exists and is reused (not reinvented): **`/Library/Application Support/StudioOS/`** (root:admin) with `bin/worker_runner-<sha256>.py` at **root:wheel 0444**, sudo-gated installer `scripts/worker_plane/install-studio-worker-plane.sh`, `secrets/` restricted to `studio-provider`, user-deny ACLs on `exchange/inbox`, and `scripts/shadow/execution_fence.py` identity planes (worker/provider uid). **Live permission proof:** `touch "/Library/Application Support/StudioOS/bin/…"` → **Permission denied** — the user identity agents run as cannot write the plane. Content-addressed + hash-verified + owner-gated-install + restricted-perms is exactly the pattern the Trusted Bootstrap needs.

## TRUSTED_LAUNCHER_LOCATION
`/Library/Application Support/StudioOS/bin/release_launcher-<sha256>.py` (root:wheel 0444), installed by the worker-plane installer pattern under sudo. Reference logic built + tested at `spa_core/studio_os/release_launcher.py`.

## TRUSTED_LAUNCHER_AUTHORITY
Root-owned, user-write-denied. launchd ProgramArguments repoint to it (outside autosync). It never reads/execs the mutable project tree; it resolves the approved release and execs only from it.

## APPROVAL_AUTHORITY
`approved_release.json`, the ACTIVE pointer, and `releases/<sha>/` all live in the **root-owned trusted plane** (user-write-denied). **Owner approval = a root/sudo write; the only write path.** Agents MAY observe CANONICAL / prepare STAGED / report DEPLOYMENT_REQUIRED; agents MUST NOT change APPROVED/ACTIVE, modify the launcher, or bypass it. The launcher itself never writes approval (proven: `test_launcher_never_writes_approval`).

## SERVICE_ENTRYPOINT_MAP
Fixed allow-list in the launcher (immutable), never in the approval file — an approval names only a SHA:
`paper-cycle → -m spa_core.paper_trading.cycle_runner --verbose --live` · `orchestrator → -m spa_core.orchestrator.adapter_orchestrator` · `telegram → -m spa_core.telegram.bot` · `agent:<role> → -m <module>` from a role manifest INSIDE the approved release (trusted content, `spa_core.`-prefixed only). No arbitrary shell reachable (`test_service_allowlist_and_no_arbitrary_command`).

## AUTOSYNC_BOUNDARY
Autosync (running as user) can write `~/Documents/SPA_Claude/{spa_core,scripts,…}` (STAGED) but **cannot** write `/Library/Application Support/StudioOS/**` (launcher, approved_release.json, releases/) — OS-enforced, proven live. So autosync can stage anything; only an owner-approved SHA, resolved by an unmodifiable launcher, executes.

## TAMPER_TEST (HARD GATE)
`test_trusted_bootstrap.py::test_tamper_staged_tree_never_executes` — a malicious STAGED tree with evil `agent_template.sh`, `run_daily_paper_cycle.sh`, and `spa_core/probe.py` all printing **BYPASS**; simulate daily-cycle / restart / self-heal / reboot. Result: the launcher execs only the approved release (`RELEASE_A`); **BYPASS never executes** (and the test confirms the tree is armed — running from it *would* print BYPASS, so the exec-root choice is what saves it). No approval → fail-CLOSED before any app module loads. **PASS.**

## APPROVAL_MUTATION_TEST
The launcher has no code path that writes approval (static proof, `test_launcher_never_writes_approval`); approval is a root-owned file the user cannot write (OS perms, proven live). Full OS-level enforcement of "ordinary worker cannot change APPROVED" requires the privileged install (below) — stated, not performed.

## ROLLBACK_TEST
`test_trusted_bootstrap.py::test_rollback_reapprove_prior` + `test_release_activation_shell.py::test_rollback_reactivates_prior_release`: A approved → B approved → B bad → re-approve A → next start execs A. No git history rewrite, no autosync rewrite, no network (local A). **PASS.**

## CURRENT_RISK
**SCHEDULED_RUN_WOULD_ACTIVATE** (unchanged; highest applicable). CANONICAL=STAGED=`603b30077aca` (autosync IN_SYNC 2026-09-28T11:12:08Z), ACTIVE=UNKNOWN, APPROVED=None. Next scheduled money-path exec = the 08:00 daily paper cycle (sync→`cycle_runner --live` from the tree). Unsafe until the launcher is wired. Not mitigated in production (owner-gated).

## FILES_TO_BUILD
Built + proven now (read-only, candidate): `spa_core/studio_os/release_state.py`, `release_activation.py`, `release_launcher.py`; tests `test_release_boundary.py` (A–H), `test_release_activation_shell.py` (exec proof), `test_trusted_bootstrap.py` (tamper/rollback); `repo_status` release block; CODE SYNC UI; ADR-500.
To wire in production (privileged, owner): install `release_launcher-<sha>.py` into the root plane; repoint the ~84 launchd plists + `com.spa.daily_cycle` to it; create root-owned `approved_release.json` + `releases/`; a small `approve`/`materialise` step (reusing `release_activation.materialise_release`); seed APPROVED with the current known-good release.

## PRIVILEGED_OWNER_ACTIONS_REQUIRED (sudo — NOT performed)
1. `sudo` install the trusted launcher into `/Library/Application Support/StudioOS/bin/` (root:wheel 0444), via the worker-plane installer pattern. 2. `sudo` repoint launchd ProgramArguments to the launcher. 3. `sudo` create the root-owned `approved_release.json` + `releases/` (owner-writable only, user-deny ACL). 4. Seed APPROVED = current known-good SHA. 5. Decide the interim stance (pause autosync/daily-cycle, or wire fail-CLOSED first) — a production action. None performed.

## ADR_499_STATUS
**PROPOSED** (revised with the Trusted Bootstrap Boundary; not accepted).

## Final flags
```
LAUNCHER_OUTSIDE_AUTOSYNC   = YES  (design reuses the root-owned, user-write-denied plane — proven feasible; NOT installed)
APPROVAL_OWNER_GATED        = YES  (root-owned control file, user-write-denied proven live; launcher never writes it)
ALL_START_PATHS_PROTECTED   = NO   (launchd plists still point to scripts/*.sh; repoint is a privileged owner action, not done)
TAMPER_TEST                 = PASS (malicious staged tree never executes; BYPASS never runs)
ROLLBACK                    = PASS (re-approve prior; no history rewrite, no network)
READY_TO_ACCEPT_ADR_499     = NO   (stays PROPOSED; needs owner acceptance + the privileged install)
PRODUCTION_SAFE_TO_RESTART  = NO   (SCHEDULED_RUN_WOULD_ACTIVATE; nothing wired)
```
No production changes. STOP.
