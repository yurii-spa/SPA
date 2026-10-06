# REVIEW_INTEGRATION_3: RM-TRUTH-01 `rmtruth/candidate` HEAD d874098f9

Reviewer: independent re-reviewer, round 3. Read-only.

- Fix diff reviewed: `5e0c122fa..d874098f9` (fix commit a4de6b87e).
- Not touched: /tmp/spa_rmtruth01, prod, the mirror. Nothing was pushed and no agents were touched.
- Own disposable worktree: /tmp/spa_rmt_rr3, removed at the end.
- Reproductions: `scratchpad/rr3/` (`repro_n1.py`, plus a fake prod tree under a fake `HOME`).
- Date: 2026-10-05.

## Verdict: **CLOSED**

N1, N2 and N3 are closed. There are no P0 or P1 findings. Three minor items remain, R1–R3, all P2 or info. None of them blocks the merge.

## 1. N1: own reproduction

**Setup:**
- `HOME=<scratch>/fakehome`, which makes `DEFAULT_LIVE_ROOT` resolve to `fakehome/Documents/SPA_Claude`. I asserted this inside the script.
- That fake prod tree is an APFS clone of the candidate (`cp -Rc`) and carries 1194 tracker cards.
- The stand is built by the real `ensure_faithful_stand(stand, FAKEPROD)`.
- The child is launched exactly like `run_arm`/`run_probe`:
  - `SPA_SANDBOX=1`, `SPA_LIVE_ROOT=<stand>`, `SPA_DATA_DIR=<stand>/data`;
  - `PYTHONPATH=FAKEPROD`, `cwd=FAKEPROD`.
- The child imports `owner_queue.queue` and calls `create_card("inbox", …)`.

| arm | TRACKER_DIR realpath | card landed | owner_decisions._live_tracker_dir |
|---|---|---|---|
| **new** (candidate stand) | `<stand>/nimbalyst-local/tracker` (a real copy) | `<stand>/…/inbox-test-n1-utechka.md` | `<stand>/…/tracker` |
| **old** (pre-fix symlink-everything stand, replayed) | **SandboxLeakError** from `assert_not_prod_realpath` | none | refused (it imports queue) |

- The fake-prod `nimbalyst-local` sha256 tree hash is **identical** before and after both arms.
- Both fix links work independently: the copy confines the write, and the "within" guard refuses the old-shape leak.

**Stand state after the fix (resolved inside the child):**

| path | where it resolves |
|---|---|
| `landing/src/data` | stand copy |
| `spa_core/database/spa.db` | stand copy |
| `.git` | **ABSENT** |
| `KANBAN.json`, `docs/`, `inbox/`, `architecture/`, `scripts/` | still resolve **into prod** through the symlinks (see R1) |

**Copy cost:**
- 0.20 s per stand for an 11 MB `nimbalyst-local`, against 0.004 s for the old symlink-only stand.
- Prod `nimbalyst-local` is 6.8 MB with 747 cards, plus 316 KB for `landing/src/data` and 140 KB for `spa.db`.
- Three stands per measurement is therefore well under 1 s and about 22 MB of tmp.
- Every caller of `build_stands` uses a TemporaryDirectory or tmp, so stale old-style symlinked stands are not reused.

**`__file__` escape (generate_track_snapshot `OUT = Path(__file__).resolve().parents[1]/landing/...`):**
- All three harnesses put `tree_root` on `PYTHONPATH` and use it as `cwd`, so code is imported from `tree_root` itself, not through the stand's symlinks.
- Any `__file__`-rooted writer therefore targets `tree_root` exactly as it did before stands existed.
- Census children import readers; they do not run producers' `__main__`.
- This is **PRE_EXISTING** and not widened by N1's fix.

**`.git` omission:**
- No `live_root()/".git"` reader exists. The only `live_root()` callers are:
  - `owner_queue.queue`;
  - `owner_decisions._live_tracker_dir`;
  - `owner_answer_delivery.resolve_root`.
- git-running readers use `cwd=tree_root`, not the stand.
- So no reader changes outcome. A future reader would get an honest ABSENT result (inv. #17), not the prod repo.

## 2. Broadened guard ("equal or within")

**Who sets the marker:**
- Harness children set `SPA_SANDBOX`/`SPA_STAMP_TREE`:
  - `python_reader_clock_doors`, `list_identity_census`, `run_identity_key_price._run_http_probe`;
  - `green_by_construction_census`, `copy_independence_probe`, `artifact_stamp_clock_doors`;
  - `decision_reproducibility` (new).
- Two other code paths read or set it:
  - `redteam/scenarios.py` sets it in-process. That was unchanged and already refused on equality before this change.
  - `rates_desk/proof_chain` only reads it.
- **Nothing** in `.github/`, `launchd/`, `scripts/*.sh`, `check_agent_before_deploy.sh`, `agent_static_probe.sh` or `deployment_acceptance.py` sets it.
- `git diff bbb127730..d874098f9` on those three gate files is empty.
- Prod agents never carry the marker, so the guard is a no-op for them. Pre-deploy gate and deployment_acceptance are unaffected.

**Where each harness points `SPA_LIVE_ROOT`:**
- Its stand in tmp, its sandbox in tmp, its `mkdtemp` worktree, or its disposable copy.
- None of these is inside `~/Documents/SPA_Claude` in the default and prod paths. `artifact_stamp_clock_doors.run(sandbox=True)` uses a tmp box.

**R2:** the one legitimate case now refused is covered under Findings below.

**Tests:** `test_tracker_dir_survives_worktree` (live tree in tmp) and `test_owner_answer_delivery` pass.

## 3. N2 / N3

- **N2 CLOSED.**
  - `_default_runner` now sets `SPA_SANDBOX=1` and `SPA_LIVE_ROOT=sandbox`, the same tmp directory as `SPA_DATA_DIR`. So `live_root()` can never reach `root`, whatever `root` is.
  - The ALLOWLIST entry was removed, which strengthens the ratchet. The ratchet's docstring re-measures this as 7 functions: 6 carry the marker and 1 is allowlisted.
  - The change is journaled in W40 (inv. #16).
  - `test_decision_reproducibility` and `test_sandbox_wiring_ratchet` are green.
- **N3 CLOSED.**
  - `render_studio`'s top `_stats` now carries the tile "ждёт решения, тема не объявлена" with `len(unclear)`.
  - The new 3-test fixture `tests/cartographer/test_director_undeclared_subject_top_row.py` is green.

## 4. Cumulative safety recheck `bbb127730..d874098f9`

The cumulative diff is 93 files, +25011/−437.

| check | result |
|---|---|
| `landing/` | empty |
| `spa_core/risk`, `governance/kill_switch.py`, `spa_core/execution` | empty |
| `*baseline*` | empty (no baseline padding) |
| `spa_core.execution` or LLM SDK imports in the fix diff | none |
| token patterns (ghp_/github_pat_/xox/sk-ant/AKIA/bot-token) in added lines | none; the one hit is the prose memory fact about the 06-10 PAT incident, which contains no secret |

## Tests run (own worktree, `SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly`)

| batch | files | result |
|---|---|---|
| 1 | `test_ensure_faithful_stand_n1`, `test_sandbox_wiring_ratchet`, `test_director_undeclared_subject_top_row`, `test_sandbox_prod_leak_inc1`, `test_tracker_dir_survives_worktree`, `test_decision_reproducibility`, `test_data_dir_env_ratchet` | **47 passed** |
| 2 | `test_live_paths`, `test_python_reader_clock_doors(_wiring)`, `test_list_identity_census(_wiring)`, `test_owner_answer_delivery` | **354 passed**, 68 subtests |
| 3 | `test_owner_queue` | **23 passed** |
| 4 | `test_run_identity_key_price` | **NOT MEASURED**: still running after more than 40 min, so I killed it. It is the CI's job, and the CI is running in /tmp/spa_rmtruth01. |

## Findings

| id | sev | origin | file | evidence | fix |
|---|---|---|---|---|---|
| R1 | P2 (latent) | PRE_EXISTING-shape, narrowed by N1 | `run_identity_key_price.ensure_faithful_stand` | Other mutable paths are still symlinked into prod: `KANBAN.json`, `docs/` (STATE/SYSTEM_BRIEFING), `inbox/`, `architecture/`, `research/`. Any future writer that goes through `live_root()/<these>` would write to prod, and `live_root()` would not refuse, because the stand itself is not in prod. **Measured today:** the only `live_root()` callers are the 3 tracker/delivery resolvers, and all of them now land in the copy. There is no active leak. | Follow-up: invert the policy (symlink only an allow-list of code dirs, copy or omit everything else), or have `live_root()` callers pass their final path through `assert_not_prod_realpath`. |
| R2 | P2 | INTRODUCED (guard broadening) | `live_paths._refuse_if_leaking_to_prod` | "Within `DEFAULT_LIVE_ROOT`" also refuses legitimate disposable trees **nested inside** the prod dir. 14 Claude worktrees live under `~/Documents/SPA_Claude/.claude/worktrees/`. `artifact_stamp_clock_doors.run(root=<such worktree>, sandbox=False)` passes `is_disposable_tree` but now fails: `SPA_LIVE_ROOT=<worktree>` raises SandboxLeakError. **Reproduced** with a fake HOME. The failure is loud (fail-CLOSED, the arm dies), not a leak. The prod and CI paths use tmp and are unaffected. | Document it, or exempt registered `git worktree` roots. The recommended path is `sandbox=True` or a tmp worktree. |
| R3 | info | INTRODUCED (test) | `spa_core/tests/test_ensure_faithful_stand_n1.py` | The network guard reports "RE-INSTALLED mid-run: missing[urlopen]" on `test_nimbalyst_local_lands_as_a_real_copy_not_a_symlink`. Something imported in that test assigns `urlopen` instead of wrapping it. The guard repaired it, so the run is not unguarded. | Find the offending import (likely a module imported via the fake tree) and make it wrap. |
| — | info | — | `owner_decisions._live_tracker_dir` | It does not call `assert_not_prod_realpath`, unlike `queue`. It is safe today because the tracker is copied, and a symmetric hardening would be cheap. | Optional. |
