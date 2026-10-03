# ADR-551 · Build Loop v1 + agent output governance + resource guardrails

- **Status:** ACCEPTED (owner epic 2026-10-03, «BUILD LOOP v1 + AGENT OUTPUT GOVERNANCE + RESOURCE GUARDRAILS»)
- **Date:** 2026-10-03
- **Scope:** the development loop and the machine it runs on. NOT touched: DeFi strategy mechanics, RiskPolicy,
  kill-switch thresholds, real-capital permissions, Trading Research behaviour. Real capital = 0.
- **Related:** ADR-066 (manifest), ADR-146 (agent closing with evidence), ADR-285 (owner boundary), ADR-527 (memory),
  ADR-537 (memory before change), ADR-546 (87 GB of abandoned stands), ADR-548 (previous epic).

## Phase 0 — what existed (audit 2026-10-03, four independent read-only audits)

| Component | Verdict | Evidence |
|---|---|---|
| Canonical task store = tracker cards (1176 on origin) | IMPLEMENTED | `.nimbalyst/trackers/*.yaml`, `nimbalyst-local/tracker/` |
| Production tree's tracker = origin | WRONG | 742 vs 1176 cards, HEAD 2026-08-29 (code-sync moves code, not cards) |
| `KANBAN.json` (MP-xxx) | WRONG (dead) | last updated 2026-06-22 |
| Order series G-nn | MISSING as a store | prose sections in 86 ADRs |
| Studio Bridge / mission ledgers | PARTIAL (parallel stores) | `studio_bridge/state/bridge.db`, `mission-state/` |
| Card transition table | MISSING | point rules only in `queue.set_status` |
| Evidence on closing | WRONG for `done` | only `owner-done` needed evidence; 0/135 closed agent cards carried any |
| Card id / owner role / commit link fields | MISSING | id = filename; no owner/commit fields |
| Commit → card / ADR link | PARTIAL | 14% name a card, 65% an ADR (since 2026-09-01) |
| Commit → session / agent | PARTIAL | one shared author identity; model trailer in 22%, session URL in 4% |
| Release ledger / outcome after release | MISSING | latest-state files only |
| Artifact → owner / purpose | MISSING | no CODEOWNERS; manifest has no owner; site artifacts absent from manifest |
| Memory: artifact-keyed lineage | MISSING | lineage keyed by ADR id only; no git/code in the index |
| Autonomous site publisher (orchestrator) | IMPLEMENTED gate | `SPA_AUTONOMOUS=1` → `safe_site_push` → `check_owner_gate` |
| R&D agent site gate | MISSING | `novel_edge_rnd` ran `claude -p --dangerously-skip-permissions`, told to push to main, without `SPA_AUTONOMOUS`; no timeout, no run id |
| `com.spa.autopush` | WRONG | executes any `scripts/push_v*.sh` with no guard (dormant) |
| CMO drafts → publish | PARTIAL | 80 drafts, 44 approved, 0 published — no publisher |
| Free-disk / memory / swap watch | MISSING | no fleet agent measured them; both ENOSPC windows (10-02 22:58Z, 10-03 07:55Z) alerted nobody |
| Worktree reaper | IMPLEMENTED, never scheduled | last real run 2026-09-27; 95 registered worktrees |
| `mkdtemp` stand cleanup | PARTIAL | g17_/g18_ fixed (ADR-546); 84 call sites, 35 without cleanup |
| Heavy-job admission / concurrency | MISSING | orchestrator lock (N=1) only; nothing limits parallel full suites |
| Critical-service priority | MISSING | no `Nice`/`ProcessType`/limits on any paper scheduler |

Incidents investigated:
- **B. 87 GB of stands.** `heir_all_rows_price.measure()` / `judge_alone_price` copied `data/` five times per call with
  `mkdtemp(prefix="g17_"/"g18_")` into the per-user temp root and never removed them (ADR-546 fixed the two tools);
  nothing swept the temp root and nothing watched free disk. Recurrence: still possible for the 35 other call sites →
  now bounded by the TTL sweep and alerted by the guard.
- **C. The killed Claude session.** Memory pressure: two concurrent full suites plus parallel worktree shards
  (docs/audits/p0-ci-resource-admission.md: free memory 0.1 GB, six jobs killed). No admission control and no priority
  separation existed; the paper schedulers ran at the same priority as test shards.
- **D. Parallel trees.** Advisory session declarations only; nothing stopped two workers on one tree.

## Decision

### 1. Task lifecycle (no second task system)
The task is the tracker card. `spa_core/owner_queue/queue.py` now holds the ONE transition table
`CARD_TRANSITIONS` (keyed by status; derived from every transition recorded in the cards' own trails, plus their
logical counterparts) and `check_lifecycle()`, enforced inside `set_status`:
- a status outside the vocabulary is refused (a typo would hide a card from every filter);
- a transition the table does not allow is refused; re-opening stays allowed (visible beats vanished);
- **closing (`done` / `owner-done`) needs `closed_by` and `evidence`**, recorded in the card's own trail
  (a card carried to an existing path closes without, as before);
- **an owner decision is closed by an agent only on the owner's recorded answer** (`owner_choice` /
  `owner_answer_via` / `owner_answered_at`, or `owner-accepted`); a misrouted card still goes `ingested` (ADR-285).
- CLI: `orchestrator_queue.py set-status <card> done --closed-by <who> --evidence <what>`.

`spa_core/studio_os/build_loop.py` DERIVES the lifecycle IDEA → TASK → ASSIGNED → RUN → ARTIFACT → REVIEW →
DECISION → RELEASE → OUTCOME → MEMORY for any card from the card, origin's git history (commits naming the card),
the production commit code-sync delivered, and the memory index — each stage DONE / MISSING / UNKNOWN with its
evidence (`python -m spa_core.studio_os.build_loop lineage <card>`; `board` for active / blocked / owner gates).

### 2. Artifact provenance
`architecture/provenance.json` holds only human/decision facts per significant artifact (purpose and its source,
source task, source decision, producer role and run, reviewer, owner role, status, consumers). Git facts are derived
at query time; fleet data artifacts resolve through `architecture/manifest.json`. `spa_core/studio_os/provenance.py
explain <id|path|element-id>` answers ARTIFACT → … → CURRENT STATUS. Statuses: ACTIVE · EXPERIMENTAL · SUPERSEDED ·
DEPRECATED · UNKNOWN_PURPOSE. **The removal verdict is never a plain yes**; UNKNOWN_PURPOSE ⇒ NO (UNKNOWN is not
OBSOLETE, ADR-537). The registry is a canonical memory source (one chunk per artifact).

### 3. Supervision of autonomous output
`spa_core/studio_os/orphans.py::supervise()` gives every autonomous output one disposition: ACCEPTED_INTO_BACKLOG ·
MERGED · REVIEWED_AND_RELEASED · REJECTED · ARCHIVED_AS_RESEARCH · NEEDS_REVIEW (default). Holes closed:
- `novel_edge_rnd` now exports `SPA_AUTONOMOUS=1` (the site owner-gate interlock applies), runs through
  `claude_run_with_timeout.py` (run id, 4 h term, child ownership) at nice 10;
- `auto_push.sh` executes only names on `scripts/auto_push_allowlist.txt` (empty) and reports the rest;
- the orchestrator's `claude` (and every pytest child) starts at nice 10.

### 4. Orphan report (report only)
`orphans.report()` — pages without lineage, undeclared agent output, artifacts without readers, workers not in the
manifest and vice versa, duplicate canonical-looking docs, stale in-progress cards, abandoned worktrees, stray temp
trees — each with last activity, known owner/purpose, removal risk and recommended action. Nothing is deleted or
disabled. Written daily to `data/orphan_report.json`.

### 5-6. Resource guardrails and critical-service protection
`architecture/resource_policy.json` is the one policy. `com.spa.resource_guard` (every 5 min,
`spa_core/monitoring/resource_guard.py`):
- disk free on `/System/Volumes/Data` (WARN < 40 GB, CRITICAL < 15 GB), kernel memory-pressure level and swap —
  a probe that fails is NOT_MEASURED (inv. #17);
- processes by RSS, classified CRITICAL (paper schedulers, API, tunnel — derived from what the package-status read
  model and the site depend on) / IMPORTANT / DISPOSABLE (pytest, `claude -p`, headless browsers, /tmp worktrees);
- under memory pressure ≥ warn, DISPOSABLE processes are re-niced (never killed);
- a 2 GB disk reserve is kept while healthy and released at CRITICAL so canonical writers keep room;
- one Tier-1 Telegram alert per incident (`resource_critical`, edge-triggered, resolved on recovery);
- `data/resource_health.json` → Director.

Heavy-job admission (`spa_core/utils/heavy_job.py` + pytest plugin `spa_core/utils/pytest_heavy_admission.py`,
registered in `pytest.ini`): a local full suite (≥ 2000 tests, macOS, not CI) takes a lease — at most 2 at once,
never two live jobs on one tree, refused below 20 GB free disk or at kernel pressure level 4, and the job re-nices
itself to 10. A refusal stops the run before the first test with the reason (exit 4); override
`SPA_HEAVY_ADMISSION=off`.

### Cleanup policy
`com.spa.resource_cleanup` (daily 05:40, `spa_core/monitoring/resource_cleanup.py`):
1. removes ONLY directories whose name starts with an allow-listed prefix under an allow-listed root, older than the
   TTL (24 h), never through a link, never under `never_touch` (production tree, mirror, backups, session
   scratchpads); every removal is logged to `data/resource_cleanup_log.jsonl` (in DR and off-host backups);
2. linked worktrees ONLY through `scripts/reap_stale_worktrees.py` (idle ≥ 24 h, every path proven delivered or
   superseded, archived before removal);
3. writes the orphan report. Anything not clearly disposable is retained and reported.

### 7. Owner read model
Director (`spa_core/studio_os/director_report.py`) gains RESOURCES (overall, disk, pressure, swap, memory by class,
heaviest processes, heavy-job leases, age — a silent guard is «не измерено», not green) and ORPHANS; WORK and OWNER
were already there. No new surface, no second truth.

### 8-9. Memory and recovery
Canonical truth is git: cards on origin, `architecture/provenance.json`, `architecture/resource_policy.json`,
`architecture/manifest.json`. Derived and rebuildable: `data/resource_health.json`, `data/orphan_report.json`,
the memory index. Runtime evidence `data/resource_cleanup_log.jsonl` is in the DR and iCloud backup sets.

## Tests changed on purpose (invariant #16)

- `test_history_check_exact_prior_ask.py`, `test_owner_intake.py`, `test_agent_may_close_cards.py`,
  `test_tracker_status_audit.py`: fixtures that close an owner-decision card now first record the owner's answer
  (the way the Telegram answer path does) — the closing rule is this ADR's, the tests keep testing what they tested;
  closings of agent/inbox cards in fixtures carry `closed_by`/`evidence`. New refusal tests added, none removed.
- `test_owner_control_plane.py`: the healthy fixture includes a fresh resource reading; two new tests (absent ⇒ not
  green; CRITICAL ⇒ red).
- `test_alert_recovery_stuck_events.py`: `resource_critical` registered with its resolving sender.

## Independent review and remediation (2026-10-03)

The first independent review found 17 issues. Each was fixed with a control:

| # | Finding | Fix |
|---|---|---|
| 1 | The findings bridge could no longer auto-close its cards (`done` without evidence; owner-decision questions without an owner answer) | Both bridge callers now pass `--closed-by` / `--evidence` naming the vanished finding. A card with `finding_key` may be RETRACTED to `done` (not `owner-done`): the question ceased to exist, nobody answered for the owner |
| 2 | `$USER_TEMP` was resolved via `os.confstr`, which this Python lacks ⇒ the 87-GB class was skipped silently | The root is resolved via `getconf DARWIN_USER_TEMP_DIR`. An unresolved root is named `unmeasured_roots` and the cleanup exits 2 |
| 3 | Admission did not engage for the prescribed `SPA_ENV=ci` command | CI is detected by `CI` / `GITHUB_ACTIONS`; the prescribed local command takes a lease (verified live: 11,680-test run, reniced 0→10) |
| 4 | Stale leases, pid reuse, pid 0, non-integer pid | Each lease records the process start time; a mismatch or dead pid means the lease is stale and is pruned. pid ≤ 0 and garbage pids are treated as dead |
| 5 | `RELEASED` was claimed without production evidence, and git errors were read as «not an ancestor» | `ON_MAIN_PRODUCTION_UNKNOWN` and `UNKNOWN` are separate states; lineage marks such a RELEASE UNKNOWN, not DONE |
| 6 | xdist workers took leases; exit code 4 collided with pytest's usage error; the cap was not re-checked after a race | Workers skip admission; refusals exit 75 (EX_TEMPFAIL); the race is decided by write time, and the cap is re-checked. A real two-process race test passed 5 runs out of 5 (an earlier name-ordered version let BOTH win, caught by that test) |
| 7 | Stand age came from the top-level mtime only | Age is the newest entry in a bounded walk; a sandbox written deep inside is alive |
| 8 | The 5-minute path walked the sizes of the whole backlog | That path now only counts; bytes are measured by the daily run |
| 9 | `resource_cleanup` had `RunAtLoad=true` | Set to false. The first-run dry run was reviewed before install: 6,261 empty test stands (0.01 GB), none younger than 24.8 h, no unmeasured root |
| 10 | Unlinking the reserve can free 0 bytes under an APFS snapshot | The measured delta is reported, not the nominal size |
| 11 | Owner answers given in Nimbalyst write no answer field; transitions were missing | The owner's own `→ owner-done` / `→ owner-accepted` in the card trail counts as an answer; an agent's `closed_by:` entry does not. Added `needs-owner → new/backlog` and `in-progress → ingested` |
| 12 | Director would stay yellow until the guard is installed | The guard is installed in the same delivery |
| 13 | The orphan regex matched the word «owner» everywhere; routes matched as substrings; lineage matched slug prefixes | Markers are anchored, routes are matched as whole tokens, and slugs as whole tokens (test: `x` ≠ `x-2`) |
| 14 | A failed `launchctl list` produced false findings | It is reported as one NOT MEASURED finding |
| 15 | Short `vp*` prefixes in `/private/tmp` | Removed; only `spa_test_backups_` remains there |
| 16 | autopush refusals were counted as failures | They are counted separately as `refused=` (the C012 regex is a prefix match, so it is unaffected) |
| 17 | pid reuse between the `ps` snapshot and renice | The command line is re-read and must match before renicing |

Found while rebasing: parallel cycles took ADR-549 (#761, `f93ec36bd`) and ADR-550 (#762, `3395b3f5b`) on origin ⇒ this decision is **ADR-551**.

Also changed on purpose (invariant #16):
- `test_claude_run_timeout_ownership.py`: the R&D wrapper moved from NOT_YET_WIRED to WIRED. The 18.09 ARB canary ran clean (10 governed orchestrator cycles with run ids on 2026-10-03), and the list itself says an extension must be an edit of the list.
- `test_findings_to_cards.py`: the closing call must now carry `--closed-by` and an `--evidence` that names the finding (stricter).
- `test_tracker_board_matches_cards.py`: the fixture closes with evidence.
- The `SPA_AUTONOMOUS` block in the R&D wrapper sits below the registry `git fetch`/`git show`, so the line-keyed shell git census baseline is untouched.

Differential: of 24 failures in the 397-file affected run, 17 also fail on the clean base. The other 7 were fixed above (the manifest's `plist_source` check clears on install).

## Second independent review (2026-10-03)

It confirmed findings 2, 3, 4, 9, 10, 13–17 as fixed and found eight more defects. All are fixed, each with a control:

| | Finding | Fix |
|---|---|---|
| A | (critical) The bridge exemption let ANY agent close a bridge-born owner question (16 real cards carry `finding_key`) | Retraction is allowed only for closer `findings_bridge` (the whole bridge family closes under that name), only to `done`, and only on a card with no trail entries (untouched since birth). Controls: a random agent, a touched card and `owner-done` are all refused |
| B | (critical) Answers given in Nimbalyst write no field and no trail, so accepted tasks could not close; a raw-regex trail check could be forged through `SPA_SESSION_ID` | Owner answers are read from PARSED trail items (old/new/source). The owner's word is any of: an answer field; the card leaving `owner-accepted` (agents can never set it); arrival at `owner-done`/`owner-accepted` without `closed_by:`; the card being, or having been, `owner-done` with no agent closure on record. Controls: the Nimbalyst `owner-accepted → in-progress → owner-done` path, `owner-done → ingested → done`, and a forged session id refused |
| C | (critical) The race could still produce two winners (mtime is stamped at write time, not when the lease becomes visible) | `fcntl.flock` on the registry around the whole read → check → write. Control: 6 real processes, exactly 1 wins (repeated) |
| D | A failed code-sync (CHECKOUT_FAILED/ROLLED_BACK) still records `origin_main` ⇒ false RELEASED | Only `IN_SYNC`/`SYNCED` count as production evidence |
| E | A stand whose age walk was capped could be judged old and deleted | Capped ⇒ age NOT MEASURED ⇒ kept and named |
| F | The 5-minute path still walked stands for ages | That path is top-level only (`deep=False`); only the daily run walks |
| G | NOT_MEASURED never alerted, and it tied with CRITICAL | Ranking is CRITICAL > NOT_MEASURED > WARN > OK; a blind guard pushes under its own fingerprint |
| H | Legacy `own-*` cards with a top-level `type:` escaped the owner check | The tracker type falls back to the top-level `type` |

Known and named, not fixed (latent): with `pytest -n` (xdist) the controller never collects, so an xdist run takes no lease. xdist is not installed in the project interpreter.

