# TRUSTED_BOOTSTRAP_CUTOVER_REPORT

Owner accepted ADR-499 (Trusted Bootstrap) and authorized the cutover. Executed the non-privileged, safe parts;
the privileged (root/sudo) install + launchd repoint **cannot be performed by this agent** (no passwordless
sudo, and system/launchd modification is owner-scoped) and are handed off with an exact, dry-run-proven
installer. **No production code executed, no fleet restart, no Telegram, no capital, no RiskPolicy change.**

## ADR
**ACCEPTED** (architecture). Renumbered **499 → 500** — an automatic origin/main writer took ADR-499 for a
different topic (`ADR-499-g17-subject-removed-at-the-source`); this is the **3rd** concurrent-allocation race
this series (498, 499). Numbering-only, substance unchanged, provenance recorded. File:
`docs/decisions/ADR-500-production-activation-boundary.md`.

## CANONICAL_PROMOTION (Phase 1)
**NOT completed — prepared, and honestly blocked by two things:** (a) the **active ADR-number race** (500 is
free now but auto-writers advanced origin/main twice during this task — `603b3007 → 96c8ba52`), and (b) the
`docs/decisions/INDEX.md` **>1 MB** file forces `push_to_github.py` into `--allow-overwrite`, an owner-gated
step. It is also **not blocking** the cutover: the installer materialises the approved release from local git
objects and installs the launcher from the reviewed artifact — neither needs the boundary code on origin/main
first. Recommendation: land the **P1 ADR-allocation fix** (below) before canonicalizing, or authorize the
`--allow-overwrite` push. Boundary work is committed on candidate `cab218c6` (not pushed).

## TRUST_CLOSURE (Phase 2) — a real STOP-condition found and fixed
The draft launcher imported `spa_core.studio_os.release_activation` — a **mutable pre-exec dependency** (that
module lives in the autosync tree). Per ARB Phase 2 this is a STOP. **Fixed:** `release_launcher.py` is now
**stdlib-only** (`__future__`, `json`, `pathlib`; verified by AST — zero project imports), self-contained. It
execs the approved release with **`python -E -s`** (empirically proven: ignores an injected `PYTHONPATH` and
user-site while keeping the release dir on the path; `-I` was rejected — it drops cwd so `-m` can't find the
release). Interpreter path is the fixed root-plane toolchain, not `$PATH`. **PASS.**

## LAUNCHER_SHA / LAUNCHER_PERMISSIONS
`release_launcher.py` sha256 = **`acf40aebc537e9f9a2e827695810f57a19b60fc963d7c9dbea68f3c5105c8fe1`**.
Install target (root:wheel **0444**, user-write-denied): `/Library/Application Support/StudioOS/bin/release_launcher-<sha>.py`. Not installed (sudo).

## APPROVED_RELEASE
`5b65257784441f61568e6c3bd22e9d0a1e928c83` — validated per the owner's release gate: **exists in local git
objects · still an ancestor of origin/main · has `cycle_runner.py` + `run_daily_paper_cycle.sh` + full
spa_core/risk/governance · no later commit required for services to start.** Not auto-substituted with the
newer canonical.

## RELEASE_MATERIALIZATION
`scripts/install_trusted_bootstrap.sh` (owner-run sudo) materialises `5b652577` via `git archive` (local, no
network) → temp → `.release_sha` stamp → completeness check → atomic rename → `releases/<sha>/` root:wheel
**read-only**. **Dry-run proven** (verifies launcher sha + approved object, then the install/materialise/approval
flow; fail-closed on any mismatch — demonstrated live when a stale sha was rejected). Not run (sudo).

## APPROVAL_PERMISSIONS
`approved_release.json` + `releases/` + launcher all in the **root-owned trusted plane** `/Library/Application
Support/StudioOS/` — **user-write-denied, proven live** (`touch …/bin/… → Permission denied`). Approval carries
**only a SHA, never a command**. The launcher **never writes approval** (static-proof test). Owner approval (a
root write) is the only write path. The installer's Step 6 proves `sudo -u <user> test -w` fails on all three.

## CANARY (Phase 6) / FLEET_MIGRATION (Phase 8)
**NOT run — require sudo (owner).** Procedure prepared: pick one benign non-money-path service from the audited
map, back up its plist + hash, repoint ProgramArguments to `<root-python> <launcher> agent:<role>`, reload only
that one, verify (trusted launcher ran · approved 5b652577 executed · ACTIVE marker = 5b652577 · staged
96c8ba52 did NOT run · health good), then a negative control (unapproved SHA → fail-closed). Fleet migration in
batches only after canary + daily-cycle proofs.

## DAILY_CYCLE (Phase 0 + 7)
**PAUSED** (Phase 0 safety, owner-authorized): `launchctl bootout gui/501/com.spa.daily_cycle` — reversible, no
deletion, only the daily cycle, recorded in the journal. Reason: the cutover cannot be completed by the agent
(no sudo) before the next 08:00 run, and the daily cycle is a `sync→cycle_runner --live` path. RESTORE:
`launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.spa.daily_cycle.plist` (or Phase-7 re-enable after the
launcher proof). Phase-7 cutover (repoint the plist to the launcher, service `paper-cycle`) is owner sudo.

## CANONICAL_SHA / STAGED_SHA / APPROVED_SHA / ACTIVE_SHA (now)
CANONICAL `96c8ba526266` · STAGED `96c8ba526266` (autosync IN_SYNC) · APPROVED **None on the machine yet**
(intended `5b652577`, seeded by the install) · ACTIVE **UNKNOWN**.

## TAMPER_PROOF
**PASS** — `test_trusted_bootstrap.py`: a malicious staged tree (evil `agent_template.sh`,
`run_daily_paper_cycle.sh`, `spa_core/probe.py` printing BYPASS) never executes across
daily-cycle/restart/self-heal/reboot; only the approved release runs, or fail-closed. The installed `main()`
records ACTIVE and execs from the release; no-approval → fail-closed with no forged marker.

## ROLLBACK
**PASS** — re-approve the prior release → next start runs it; no git history rewrite, no network, atomic.

## SERVICES_MIGRATED / SERVICES_DEFERRED
Migrated: **0** (privileged). Deferred: **all** (owner sudo) + **Telegram** (separately owner-gated; the bot.py
routing conflict is NOT merged into this cutover).

## TESTS
33 boundary tests pass — `test_release_boundary.py` (A–H state machine) · `test_release_activation_shell.py`
(real-exec: approved runs, staged never, rollback, git-object materialise) · `test_trusted_bootstrap.py`
(tamper hard-gate, service allow-list, no-arbitrary-shell, installed `main()`, rollback). No money-path module
imports any release module.

## OWNER_ACTIONS_REMAINING
1. (optional) Land the **P1 ADR-allocation fix** then canonicalize ADR-500 + boundary code to origin/main
   (Phase 1) — or authorize the `--allow-overwrite` push.
2. **sudo** `scripts/install_trusted_bootstrap.sh --launcher … --launcher-sha256 acf40aeb… --repo <repo-with-5b652577> --approved 5b652577…` (Phases 3–5).
3. Canary one benign service (Phase 6), verify + negative control.
4. Repoint `com.spa.daily_cycle` → launcher `paper-cycle`; prove APPROVED 5b652577 runs while staged is newer; then re-enable (Phase 7).
5. Fleet migration in batches (Phase 8); post-cutover + rollback proofs (Phases 9–10).
6. Telegram remains separate.

## Final flags
```
ADR_499                            = ACCEPTED (architecture; renumbered → ADR-500)
TRUSTED_LAUNCHER_INSTALLED         = NO   (sudo required; installer + sha ready, dry-run proven)
APPROVAL_OWNER_ONLY                = YES  (root-owned plane user-write-denied, proven live; launcher never writes approval)
CANARY                             = NOT_RUN (requires sudo)
DAILY_CYCLE_PROTECTED              = NO   (PAUSED as interim safety, not yet launcher-protected)
ALL_REQUIRED_START_PATHS_PROTECTED = NO   (plists still point to scripts/*.sh; repoint is owner sudo)
STAGED_CANNOT_AUTO_ACTIVATE        = PARTIAL (daily-cycle path paused; agent-restart path not yet launcher-gated)
ROLLBACK                           = PASS
PRODUCTION_ACTIVATION_BOUNDARY     = FAIL (designed + proven + accepted, NOT yet enforced in production)
TELEGRAM_DEPLOYED                  = NO
```
No production changes beyond the owner-authorized reversible daily-cycle pause. STOP after cutover report.
