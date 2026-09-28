# RUNTIME ACCESSIBILITY — DEFECT, HARDENING, RECOVERY, DRIFT (architecture-review v2)

Checkpoint D failed: the trusted 3.13 runtime installed at Checkpoint C is **content-correct (digest
`09eecca2…`) but root-owned mode 0700/0400 — inaccessible to the fleet user**. The launcher would `os.execv`
that interpreter as the user → the app could not start. This record supersedes the earlier R1 (`rm -rf` +
reinstall) proposal. **No privileged action taken; the installed runtime is untouched.** Not pushed.

## Defect (root cause)
Source miniconda stdlib is 0700/0600; `build_trusted_runtime.sh` `rsync -a` preserved it; the installer only
*removed* write (`go-w`, `a-w`) + `chown root:wheel` and validated Python **as root** (root can read 0700). The
content digest does not validate permissions. Result: root-owned 0700 tree the fleet user can't traverse/read;
the as-user reason was suppressed by `2>/dev/null`.

## Hardening (candidate `<HEAD>`, reviewed, NOT pushed)
`install_trusted_bootstrap.sh`:
- **Explicit installed permission model** (TEMP, before publish): dirs **0755**, library files **0644**, exe
  **0755**, all root-owned → fleet user reads/traverses/executes, cannot write. (Digest unchanged — content-only.)
- **`verify_runtime_tree` = AS-USER EFFECTIVE verification** (`sudo -u` when root, else direct; **identity check
  refuses to certify for another user**): a Python walk under `os.access(R_OK/W_OK/X_OK)` + `os.lstat` that checks
  **accessibility, actual file readability, effective non-writability (honors ACLs — not just mode bits),
  object-type + symlink rejection, group/other-write hygiene, root-ownership**; **exit status is authoritative**;
  errors **surfaced**. Then digest + 3.13 startup + relocation + isolation **as the user**. Runs **before atomic
  publish** and **on REUSE**.
- **Pre-canary approved-release import as the fleet user** (step 6b): the trusted 3.13 imports the approved
  release paths (`deployment_acceptance`/`cycle_runner`/`adapter_orchestrator`) with the release materialised —
  a **separate** end-to-end step because the release is installed after the runtime.
New installer sha **`a84076ae1dbd00965c97e92b845e47ea7f9db1473578f070d3c2c7f91ea84c5d`**; launcher/runtime-digest
unchanged (`eec1ae58…`/`09eecca2…`).

## Full installer side-effect audit (why NOT re-run it for recovery)
Re-running `install_trusted_bootstrap.sh` on the broken state: step 0 finds the existing runtime and, with the
fixed as-user check, **FAILS CLOSED and leaves it untouched** — it never reaches the later steps, so it cannot
recover. And if it *did* proceed it would needlessly **overwrite the launcher** (`cp`), **`rm -rf` + re-materialise
the release**, and **rewrite approval + runtime.json** — churn on correct artifacts. → Recovery must be a
**separate, narrowly-scoped** step touching only the runtime directory.

## Recovery procedure (`scripts/recover_trusted_runtime.sh`, OWNER sudo — NOT executed here)
Touches **only** the one content-addressed runtime dir; preserves launcher/release/approval/runtime.json.
Atomic, reversible, fail-closed. Driven by an **explicit state machine** whose state decides cleanup:

`INIT → PREPARE → TEMP_VERIFIED → QUARANTINED → PUBLISHED`

1. **Preconditions:** the control files exist; destination realpath is strictly under the trusted toolchains
   root; `runtime.json` `runtime_id`/`app_python` match the target; the runtime is present, **not a symlink**,
   digest `09eecca2…` (verified under `--execute`; deferred in `--dry-run` since a root-owned 0700 tree is
   unreadable by non-root), and it **fails as-user verify**. A staged **good** bundle is provided. **Stop** if it
   already passes (recovery not needed) or a precondition fails.
2. **Active-workload guard (correct launchd domains):** recovery runs under sudo/root, but StudioOS workloads are
   the **fleet user's LaunchAgents** in that user's **GUI domain** `gui/<uid>`. The guard resolves the fleet uid
   (`id -u "$SUDO_USER"`) and home (`dscl … NFSHomeDirectory`, **not** `$HOME`, which under sudo is root's home),
   then probes `launchctl print gui/<uid>/<label>` for LaunchAgents and `system/<label>` for LaunchDaemons by exit
   status. Refuse if any referencing workload is loaded. (A root `launchctl list` cannot prove visibility of the
   user's GUI domain — evidence below.)
3. **PREPARE → build a corrected SIBLING TEMP.** TEMP must **not pre-exist as any object incl. a dangling
   symlink** (`[ -e ] || [ -L ]`) and is claimed **atomically via `mkdir`** (ownership); an unknown pre-existing
   TEMP is **refused, never deleted**. Populate (`cp` → root:wheel → dirs 0755/files 0644/exe 0755) and **verify
   AS THE FLEET USER** → `TEMP_VERIFIED`. Existing runtime **not touched**. **Stop** if TEMP fails verify.
4. **QUARANTINED → `mv <runtime> <.quarantine-…>`** (atomic). Quarantine path must **not pre-exist as any object
   incl. dangling symlink**; **never replaced/deleted**; kept until explicit cleanup approval.
5. **PUBLISHED → `mv TEMP <runtime>`**; then **mandatory post-publish verify AS THE FLEET USER** (full Checkpoint D).
- **Failure-state cleanup (state-driven):** before `QUARANTINED` a failure removes **only a TEMP THIS invocation
  created** (`TEMP_OWNED=1`), existing runtime intact. At `QUARANTINED` (publish did not finish) the path may be
  **EMPTY** → launcher fails-closed `APP_RUNTIME_MISSING` (**no execution**); cleanup **preserves TEMP + quarantine**
  and does **not** auto-restore the broken runtime (**rollback-to-broken ≠ restoration-of-service**); STOP and
  escalate. On success TEMP is consumed by the publish rename; quarantine kept.
- **Before/after evidence:** `ls -la <runtime>` printed pre and post. Quarantine kept until a **separate**
  `sudo rm -rf <.quarantine-…>` approval.
Dry-run verified (no root, no mutation): correct launchd domain (`gui/501`), located control files + the broken
runtime, confirmed it fails as-user verify, planned quarantine→publish, and made **zero** filesystem changes.

## Test evidence (Point 2) + limitations
`spa_core/tests/test_trusted_runtime.py` (real macOS ordinary-user semantics, **not mocked**; skip on
non-macOS/non-3.13, stated). 18 runtime tests incl.: correct→PASS · **unreadable regular file in a traversable
tree**→FAIL · **ACL-granted write (mode-bit checks would miss)**→FAIL · **accessibility failure with empty
stderr caught by exit status** · writable file/subdir/group-other→FAIL · symlink→FAIL · tampered→FAIL(digest) ·
**existing inaccessible runtime→FAIL without mutation** · **diagnostic mode refuses to certify for a different
identity**. Full boundary suite 38 green.
**Untested here (require real root / a root-owned tree — a non-privileged test must not fake it):** the installer
`sudo -u` install branch, whole-tree **root-ownership** enforcement, and the real root→user boundary. These are
covered only at actual sudo-install time (Checkpoint C/D). We deliberately did **not** substitute user-owned
0555/0444 trees as evidence for the root-owned branch.

## Complete canonical-writer map (Point 5, read-only)
The only primitives that mutate origin/main are **`push_to_github.py`** (GitHub API) and raw **`git push`**
(guarded by `scripts/pre_push_check.sh`, fail-closed vs `git ls-remote`). Everything else is a caller.

| Component | Entrypoint | Commit? | Push main? | Direct/Indirect | Calls | Active? |
|---|---|---|---|---|---|---|
| autonomous orchestrator/cycle | `com.spa.orchestrator` → `agent_orchestrator.sh` → cycle session | no (API) | **YES** | INDIRECT | `push_to_github.py` / `checkpoint_deliver.py` | **ACTIVE** |
| `com.spa.autopush` | `auto_push.sh` → drains `scripts/push_v*.sh` | no (API) | **YES** | INDIRECT | each `push_v*.sh` → `push_to_github.py` | **ACTIVE** (0 pending now) |
| `com.spa.mission_tick` | `mission_tick_agent.sh` → mission session | no (API) | **YES** | INDIRECT | `push_to_github.py` | **PAUSED** (absent in `gui/501`) |
| `com.spa.site_freshness` | `agent_site_freshness.sh` | no (API) | YES (site/data scope) | INDIRECT | `push_to_github.py` | ACTIVE |
| `com.spa.novel_edge_rnd` | `agent_novel_edge_rnd.sh` | no (API) | YES | INDIRECT | `push_to_github.py` | ACTIVE |
| `com.spa.director_build` | `cartographer/director_publish.py` | no | **NO** | — | offline dashboard build (`refuse_inside_repository`, "subprocess … kept closed") | ACTIVE (not a writer) |
| `com.spa.director_server` | `cartographer/director_server.py` | no | **NO** | — | HTTP dashboard server | ACTIVE (not a writer) |
| `com.spa.decision_loop` | `spa_core.monitoring.findings_bridge` | no | **NO** | — | records findings locally | ACTIVE (not a writer) |

- **autopush scope resolved:** it runs each pending `scripts/push_v*.sh` exactly once (tracked in `.push_log`);
  its write scope = the union of those scripts' payloads. **0 pending right now** (queue drained) → it cannot
  push anything at this instant, but it is a standing indirect writer for any future `push_v*.sh`.
- **`d573ca0b` attribution:** author `yurii-spa`, 2026-09-28 22:43 — the identity **all** autonomous sessions
  commit as. Workspaces `/tmp/spa_c677_push`, `/tmp/spa_c678` reference G37/ADR-501/`INDEX.md`, so it is an
  **autonomous orchestrator/cycle** delivery (cycle ~677–678), pushed via `push_to_github.py` — **not**
  `mission_tick` (paused; confirmed absent in `gui/501`). Exact spawning agent beyond the cycle lineage: the
  orchestrator plane. My last push `1bcdd0390…` remains an **ancestor** of origin/main (preserved, not clobbered).
- Candidate base has **unrelated history** to origin/main (squash-promotion model; `merge-base = NONE`) — expected.

## Revised canonical-promotion algorithm (Point 6 — STOP on drift, NO auto-rebase)
This repo uses squash-promotion / unrelated candidate history, so an automatic rebase of a security-sensitive
candidate is forbidden. Promotion is a **compare-and-swap that STOPs on drift**, never an auto-rebase:
1. Fetch server truth (`git ls-remote origin main`).
2. Create/freshen a promotion **worktree FROM current `origin/main`**.
3. Materialise **only** the approved narrow artifact set into that worktree.
4. Verify exact hashes against this manifest.
5. Run the required regression/gates **in that canonical-base worktree**.
6. Immediately before push, **re-read the remote tip**.
7. **If remote tip ≠ the validated base → STOP** (do not push).
8. Rebuild/revalidate from the **new** canonical tip (steps 2–5). **Never autonomously rebase** the candidate.
9. Push **only** through the approved guarded writer (`push_to_github.py`, which re-verifies base and fails-closed).
10. **No force push, no `--allow-overwrite`, no hook bypass.**

The remote tip is a **compare-and-swap guard, not permission to auto-rebase.** Optional, owner-gated: for the tight
push window, `launchctl bootout` the confirmed indirect writers (`autopush`, and the orchestrator/cycle agents);
`director_*`/`decision_loop` need no pausing (not writers). Reversible; **not done here.**

## Canonical-promotion proposal (separate)
Promote the hardening as a **narrow batch** — `install_trusted_bootstrap.sh` (unchanged), `build_trusted_runtime.sh`
(unchanged), `scripts/recover_trusted_runtime.sh`, `scripts/pre_commit_check.sh` (gate scoping), the two runtime
test files, `CUTOVER_ARTIFACT_MANIFEST.json`, this doc + journal — via the **STOP-on-drift** algorithm above.
**No INDEX, no `--allow-overwrite`, no force, no hook bypass.** Requires explicit Owner push authorization.
**Recovery of the live broken runtime happens only AFTER** the corrected installer is canonical and the owner
authorizes `recover_trusted_runtime.sh`.

## Constraints honored
No sudo / launchd / canary / scheduler / production activation. Approved release unchanged. Not pushed. Installed
trusted runtime not chmod'd/deleted/replaced/repaired. `mission_tick` + `daily_cycle` re-confirmed PAUSED.
