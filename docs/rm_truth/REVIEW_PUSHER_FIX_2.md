# Independent re-review (round 2) — pusher strict mode `--expected-base` (rmtruth/fixG 86eefa152)

Reviewer: independent, read-only. Own worktree /tmp/spa_rmt_rvp2 (removed at the end, clean). No GitHub calls were made; everything was measured offline against the fakes plus a code trace.

## VERDICT: CHANGES_REQUIRED (one P1, small fix; the batch path is CLOSED)

## (1) Is `--expected-base` a tightening, not a bypass? YES
- It only ADDS refusals: `BaseDriftRefused` and `RemoteMovedDuringRead`, both subclasses of `DivergenceRefused`, so `main()` exits with rc=4. `--allow-overwrite` does not lift them, because the strict check in `guard_overwrite` runs before every allow-branch. It loosens nothing: it adds no flag and skips no guard. ADR, change-evidence and owner-gate interlocks in `main()` run unchanged.
- **Batch path (Git Data API, used whenever more than 1 file and not dry-run): all owner conditions hold end-to-end. Trace:**
  1. `assert_expected_base` runs first, before any write.
  2. `remote_tree_modes` reads the pinned tree.
  3. `assert_base_tree_matches(strict=True)` STOPs on four cases: live≠pinned, live None for a known path, a path that appeared after the pin, and a truncated tree.
  4. `build_entries` passes `guard_sha` from the pinned tree and `strict_base=True`. `guard_overwrite` raises on any state ≠ SAFE (including UNMEASURED) BEFORE `rebase_append`, so `rebase_append` cannot be reached.
  5. `create_tree(base_tree=pinned)` and `create_commit(parent=pinned base)` follow.
  6. `update_ref` is a non-force PATCH, and 409/422 ⇒ `BaseDriftRefused` with no second commit.

  A non-force PATCH whose commit has parent = expected base cannot land on any other base. If HEAD moved, GitHub rejects it as not a fast-forward, and that is a STOP. **There is no window on this path. Confirmed.**
- **P1-NEW (single-file path; `main()` routes exactly 1 file, non-dry-run, through `push_file`, which uses the Contents API PUT).** The head check, pinned-tree read, strict guard and 409/422 STOP are all present. However, the Contents API PUT pins only the FILE's blob `sha`, not the parent commit. GitHub commits onto whatever HEAD is current at PUT time. Suppose another writer commits OTHER paths between `assert_expected_base` and the PUT (the autopush and the daily cycle exist). The PUT then succeeds with no 409/422, and our commit lands on a base ≠ `--expected-base` with no STOP. There is no post-check of the parent either. That violates "remote bytes must equal the exact expected origin commit". The window is narrow (seconds), but the brief asked to confirm there is none, and on this path there is one. The fakes cannot show it, because `FakeOrigin.head_commit` is fixed and the PUT ignores the parent.
  **Fix (one line):** in strict mode, route single-file delivery through `batch_push`, which works for one file (the tests already call it that way):
  `if (len(all_files) > 1 or args.expected_base) and not args.dry_run:`
  Alternatively, make `push_file` refuse `expected_base` and require batch. Add a test where the fake HEAD advances between the head check and the write and the write must STOP or refuse to land.

## (2) Default mode is unchanged: YES
Every change is gated on `expected_base is not None`, `strict`, or `strict_base`:
- `assert_base_tree_matches(strict=False)` behaves as before. Hoisting `pinned` above the None check does not change behaviour.
- In default mode `guard_sha = remote_sha` and the guard receives `strict_base=False`.
- The 409/422 rebuild and `rebase_append` are unchanged. The default control tests (`test_default_mode_*`) and the original additive auto-rebase test stay green.
- The only structural change is the `try/except DivergenceRefused` wrapper around `get_file_sha` in `push_file`. That cannot fire in default mode.

## (3) Tests
- Strict-mode and remote-blob suites: **29 passed**. All pusher suites (`test_push_*.py`, copy guard, registry index guard, shared-memory base, safe_site_push*, pre_push_guard): **324 passed**. Run in the CI environment (`SPA_ENV=ci`, `PYTHONHASHSEED=0`, `-p no:randomly`, private TMPDIR).
- I mutated 12 strict-mode branches (`scratchpad/rmtruth/mut2.py`; the original file was restored and the tree was clean): 9 were KILLED and 3 SURVIVED.
  - M7 (`push_file` uses the pinned sha) and M8 (`build_entries` uses `guard_sha` from the pinned tree) survive as equivalent mutants. After the strict `assert_base_tree_matches`, live == pinned, so contract (b) is redundant. That is acceptable.
  - M2 survives: removing the single-file strict 409/422 STOP leaves the tests green. It is almost equivalent, because the recursive retry re-runs the head check and STOPs if HEAD moved. Still, no test covers single-file strict 409/422 (P2).
- P2: `test_strict_mode_head_moved_stops_before_any_write_single_file` contains a vacuous `... or True` assert on the error text. Its other asserts (no PUT, no blob, no ref update) are real.

## (4) Other findings (P2, non-blocking)
- `--dry-run --expected-base` never checks HEAD: dry-run always goes through `push_file`, which returns before the strict block. A dry-run therefore cannot pre-validate the pin.
- `_sha_matches_expected` accepts a prefix of 4 or more hex characters. The owner asked for the "EXACT expected origin commit", so require 40 hex in strict mode (or at least 12).

Close condition: fix P1-NEW (route strict single-file through batch) and add a test where HEAD advances during the write. The P2s are optional.
