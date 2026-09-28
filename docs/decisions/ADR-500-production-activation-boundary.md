# ADR-500: Production activation boundary — Canonical ≠ Staging ≠ Activation

- **Status:** ACCEPTED (Owner explicitly accepted the architecture 2026-09-28: «I explicitly ACCEPT ADR-499 … Trusted Bootstrap»; renumbered 499→500 due to concurrent ADR allocation). Canonicalization to origin/main (Phase 1) + the privileged install remain owner-gated. Follow-up
  to ADR-494, which said "push → autosync → owner-gated restart" but did not make the three code-states
  distinct. This ADR does not rewrite ADR-494's history; it clarifies and constrains it.
  > Numbered 499 (not 498): while this was drafted, an automatic director cycle advanced origin/main
  > (603b3007) and took ADR-498 for a different topic. My promotion 5b652577 remains an ancestor (preserved).
  > Renumbered 499 → 500 before canonical promotion due to CONCURRENT ADR allocation (an automatic
  > origin/main writer took ADR-499 for another topic — the 3rd such race this series; see the P1 note).
  > Numbering only; accepted architecture unchanged.
- **Scope:** deployment boundary only. No money path, no RiskPolicy, no capital, no execution change. Read-only
  measurement + a fail-CLOSED restart guard. Nothing here restarts, deploys, or edits launchd.

> ## REVISION 2 — TRUSTED BOOTSTRAP BOUNDARY (2026-09-28, ARB final gate)
> ARB accepted Option B conceptually but blocked acceptance on one boundary: **the launcher itself must not be
> mutable by autosync.** Audited (evidence): every launchd entrypoint is `/bin/bash
> ~/Documents/SPA_Claude/scripts/<agent_*.sh | run_daily_paper_cycle.sh>` — the first executed file is inside
> the autosync domain (`scripts/` ∈ CODE_PATHS), so a future origin/main change could replace the guard.
> **Reuse (not invent):** an accepted root-owned trusted plane already exists — `/Library/Application
> Support/StudioOS/` (root:admin; user-write **denied**, proven by a live `touch → Permission denied`), with a
> sha256-pinned `worker_runner-<sha>.py` at `root:wheel 0444`, sudo-gated installer
> (`scripts/worker_plane/install-studio-worker-plane.sh`), user-deny ACLs, and `scripts/shadow/execution_fence.py`
> identity planes. The Trusted Bootstrap reuses this exact pattern:
> - **Trusted launcher** installed as `/Library/Application Support/StudioOS/bin/release_launcher-<sha256>.py`
>   (root:wheel 0444) — the user (hence any agent/autosync) cannot modify it.
> - **launchd ProgramArguments repoint** to the trusted launcher (outside autosync), not `scripts/*.sh`.
> - The launcher reads **APPROVED** from a root-owned control file the user cannot write, maps a FIXED service
>   id (`paper-cycle`/`orchestrator`/`telegram`/`agent:<role>`) to an **allow-listed** argv (never arbitrary
>   shell from the approval file), resolves the immutable `releases/<APPROVED>/`, and execs ONLY from there.
> - **FAIL CLOSED before application code loads** on: approval missing · sha invalid · release missing/corrupt ·
>   service/role not allow-listed. It never reads or executes anything from the mutable project tree.
> Proven by `spa_core/studio_os/release_launcher.py` + `spa_core/tests/test_trusted_bootstrap.py` — the TAMPER
> HARD GATE: a malicious staged tree (evil `agent_template.sh`, `run_daily_paper_cycle.sh`, `spa_core/probe.py`
> printing `BYPASS`) never executes across daily-cycle/restart/self-heal/reboot; only the approved release runs,
> or fail-closed.
>
> **Control-file authority + permissions:** `approved_release.json`, the ACTIVE pointer, the `releases/<sha>/`
> material, and the launcher all live in the **root-owned trusted plane** (`/Library/Application
> Support/StudioOS/`), user-write-denied. An agent MAY observe CANONICAL, prepare STAGED, and report
> DEPLOYMENT_REQUIRED; an agent MUST NOT change APPROVED/ACTIVE, modify the launcher, or bypass it. **Owner
> approval (a root/sudo write) is the only write path.** These are PRIVILEGED OWNER ACTIONS (below), stated and
> NOT performed.
>
> **Privileged owner actions required (sudo — NOT performed):** (1) install `release_launcher-<sha>.py` into
> `/Library/Application Support/StudioOS/bin/` (root:wheel 0444) via the worker-plane installer pattern;
> (2) repoint the launchd plists' ProgramArguments to it; (3) create the root-owned `approved_release.json` +
> `releases/` (owner-writable only); (4) seed APPROVED with the current known-good release. Until then the
> boundary is DESIGNED + PROVEN but NOT enforced in production.
>
> **READY_FOR_OWNER_ACCEPT gate (all now met in proof, not yet in production):** immutable-release exec proven ·
> launcher outside autosync authority (reuses root plane) · approval unchangeable by ordinary worker (OS perms,
> proven live) · daily/restart/self-heal/reboot all enter through the trusted launcher · tamper test passes.
> Stays **PROPOSED** pending owner acceptance + the privileged install.

> ## REVISION 2026-09-28 (ARB proof) — SELECTED ARCHITECTURE CHANGED to Option B
> ARB required proof of *exact executable-code selection before exec*. Two facts, both measured:
> (1) `python -m spa_core...` imports from the **filesystem tree** (proven: loads from
> `~/Documents/SPA_Claude/spa_core`), so a marker `APPROVED=A` **cannot** make it execute A while the tree
> holds B — the marker-only Option A is exactly the "NOT acceptable" case. (2) `run_daily_paper_cycle.sh`
> syncs (line 85) then execs `cycle_runner --live` (line 101) from that tree in the same run →
> **SCHEDULED_RUN_WOULD_ACTIVATE**, not merely restart.
> Therefore the marker-only design is INSUFFICIENT and **Option B (immutable `releases/<sha>/` + ACTIVE
> pointer)** is selected: a process execs from an immutable, content-addressed release dir materialised from
> LOCAL git objects; the shared tree is never on its module path. Proven by real subprocess exec +
> `spa_core/studio_os/release_activation.py` + `spa_core/tests/test_release_activation_shell.py`. The pure
> three-state model + guard (`release_state.py`) remain valid; only the *activation mechanism* changes from
> "gate the in-tree checkout" to "exec from an immutable release". Still PROPOSED.
>
> **Bounded Option A vs B (deciding requirement = can we PROVE which code executes before exec?):**
> | criterion | A (in-tree restore/gate) | B (immutable releases/<sha> + pointer) |
> |---|---|---|
> | prove exact code before exec | **NO** (imports from mutable tree; TOCTOU vs autosync) | **YES** (content-addressed dir, self-stamped) |
> | implementation size | smaller (2 scripts) | larger (exec-root resolution) |
> | parallel-agent safety | poor (shared mutable tree, checkout races) | good (each release immutable) |
> | rollback reliability | fragile (re-checkout, non-atomic) | atomic (repoint pointer) |
> | partial-write risk | HIGH (checkout mid-write on money path) | LOW (materialise to temp+rename; active dir untouched) |
> | reboot / self-heal | must re-checkout first (race) | deterministic (exec from release dir) |
> | auditability | weak | strong (`.release_sha` stamp verified before exec) |
> B wins on the deciding requirement despite being larger. A is rejected because it cannot prove exact code.
>
> **APPROVED release material:** comes from LOCAL git objects via `git archive <APPROVED_SHA>` (no network for
> a known local sha), extracted atomically to `releases/<sha>/` (temp dir + rename; a partial materialise is
> discarded, the active release untouched). `exec_root` verifies the dir self-identifies (`.release_sha`)
> before returning it. Object missing → **FAIL_CLOSED** (never fall back to the tree).

## Context — the P0 discovered on 2026-09-28
The owner authorized ONLY canonical promotion to `origin/main` (commit `5b652577`) and explicitly withheld
production deployment/restart. Within ~1 minute the standing autosync `scripts/code_sync_from_origin.sh`
(invoked from `agent_template.sh` before every agent, throttled 10 min, and from `run_daily_paper_cycle.sh`)
did `git checkout origin/main -- <code paths>` **directly into the active runtime tree**
`~/Documents/SPA_Claude`. Measured facts:

- The checkout writes into the ACTIVE tree; there is **no staging directory**, **no approval gate**, and it
  **never touches git HEAD** (so `production.sha` = git HEAD is a FALSE proxy for what executes).
- The running processes still hold their pre-push in-memory code (no restart), so today they are **inert** —
  but the filesystem is no longer pinned to the active release, and **the next restart of ANY agent loads the
  staged code** (`agent_template.sh` syncs-then-execs; this covers manual restart, reboot, crash self-heal,
  and scheduled restart).
- Money-path isolation holds *today*: no `paper_trading/risk/governance/execution/adapters` module imports the
  promoted packages, and the promotion ADDED only new packages (zero existing files modified). But "no current
  import" is not a durable guarantee; the boundary must hold structurally, not by luck.

## Decision (PROPOSED) — three states that must never be conflated
| State | Meaning | Source of truth |
|---|---|---|
| **CANONICAL** | code accepted on `origin/main` | `git rev-parse origin/main` |
| **STAGED** | code the autosync placed on the production filesystem (what a restart WOULD load) | `data/code_sync_status.json` → `origin_main` |
| **ACTIVE** | code the running processes were STARTED from | `data/active_release.json` (startup marker) — **UNKNOWN if unproven; never faked from a repo HEAD** |
| **APPROVED** | the release the Owner approved for activation | `data/approved_active_release.json` (owner-gated) |

**Invariant:** a push to `origin/main` may STAGE, but must NEVER change ACTIVE, change the next restart target,
move an ACTIVE pointer, restart agents, or alter owner-gated deployment state. Activation is a separate,
owner-approved step.

## Architecture — reuse-first, two alternatives
No `releases/` or activation mechanism exists today (audited). Two options:

- **Option A — minimal in-tree gate (RECOMMENDED as the smallest safe correction).** Keep the existing
  in-tree checkout and status file, but (1) the autosync records the new SHA as **STAGED** and only checks
  code into the tree when `STAGED == APPROVED`; when they differ it stages the *record* and refuses the
  file-level checkout (fail-CLOSED, logged), leaving the tree on the approved release; (2) `agent_template.sh`
  gains a **restart guard** that consults `restart_decision(staged, approved)` and loads the approved release
  or fails CLOSED with `DEPLOYMENT_APPROVAL_REQUIRED`; (3) each agent writes `data/active_release.json` at
  startup recording the SHA it actually loaded. Reuses `code_sync_from_origin.sh` + its status file; smallest
  diff; no launchd/path changes.
- **Option B — `releases/<sha>/` + ACTIVE symlink (robust, larger migration).** Autosync checks out into
  `releases/<sha>/`; agents load via an `ACTIVE` symlink; activation = repoint the symlink (owner-gated);
  rollback = repoint to the prior `releases/<sha>/`. Cleaner separation but changes how launchd/agents resolve
  paths across the whole fleet — a large, higher-risk migration.

Recommendation: **Option A** now (contains the P0 with minimal blast radius), Option B as a later hardening if
the owner wants physical release isolation.

## Restart guard (pure, already implemented inert)
`spa_core/studio_os/release_state.py::restart_decision(staged, approved)` →
`ACTIVATE_OK` (staged==approved) · `LOAD_APPROVED_NOT_STAGED` (staged≠approved → load the approved one) ·
`DEPLOYMENT_APPROVAL_REQUIRED` (no approved release → fail-CLOSED). Path-independent, so reboot/self-heal/
scheduled restart cannot bypass it. Proven by `spa_core/tests/test_release_boundary.py` (A–H).

## Rollback — two distinct models
- **CANONICAL rollback:** `git revert` the offending commit on `origin/main` (never force-push).
- **PRODUCTION rollback:** set `APPROVED` back to the previous known-good SHA; the restart guard then directs
  the next restart to that release (`LOAD_APPROVED_NOT_STAGED`). No git history rewrite; independent of canonical.

## Migration plan (NOT applied — owner-gated; prepared for ARB)
1. Land the measurement + guard model + UI + tests (read-only, done on the candidate — this ADR).
2. Owner approval of this ADR + Option A.
3. Add the startup `active_release.json` write to `agent_template.sh` (one agent first, verify, then fleet).
4. Add the STAGED-vs-APPROVED gate to `code_sync_from_origin.sh` (fail-CLOSED, positive-control test = the
   2026-09-28 incident).
5. Seed `approved_active_release.json` with the current known-good release so nothing changes until an
   explicit owner activation.
Do NOT disable the autosync or edit launchd before owner approval.

## Acceptance
`spa_core/tests/test_release_boundary.py` green (A–H); `repo_status.status()["release"]` reports CANONICAL/
STAGED/ACTIVE with ACTIVE=UNKNOWN when unproven; Studio OS SYSTEM/CODE-SYNC card shows the three states +
`DEPLOYMENT_APPROVAL_REQUIRED`; no money-path file imports the model (test H).
