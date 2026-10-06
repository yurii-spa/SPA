# Independent re-review (round 4): pusher strict mode, rmtruth/fixG 1ea35cf24

Reviewer: independent and read-only. I worked only in my own worktree, /tmp/spa_rmt_rvp4, which is now removed. No GitHub calls were made. I used fakes, a code trace and mutation runs.
The mutation script is at scratchpad/rv4/mut4.py. The source was restored afterwards and the worktree was clean.

## VERDICT: CLOSED

## Round-3 findings
- **P2 CLI `--dry-run --expected-base` KeyError 'action': CLOSED.**
  - `_push_file_via_batch` dry-run now returns `action` ("would commit on pinned base <sha8>"), and `main()` also uses `r.get('action', …)`.
  - New main()-level tests cover three cases:
    - Correct sha with 1 file and with 3 files: rc 0, at least one GET, no POST/PATCH/PUT.
    - Wrong sha: rc != 0 with no writes.
- **Surviving mutant "dry-run skips HEAD check": CLOSED (KILLED).**
  - The early return in `_push_file_via_batch` (M1) is now killed.
  - So is moving `batch_push`'s dry-run ahead of `assert_expected_base` (M2).
  - The killing test is `test_strict_mode_dry_run_still_checks_head_before_returning`.
- **P3 `verified: 'match'` when unmeasured: CLOSED.**
  - `batch_push` gathers the blob and ref verdicts into `verify_sink`. The result is "match" only when the sink is non-empty and every verdict is a match; otherwise it is "unmeasured".
  - `_push_file_via_batch` passes that value through, with `.get(..., "unmeasured")`.
  - `main()` already marks a non-match result as "[сверка НЕ ИЗМЕРЕНА]", which is consistent with the default Contents-PUT path.

## Default behaviour cannot change through verify_sink (traced)
- `create_blob_from_bytes`, `update_ref` and `build_entries` all default to `verify_sink=None`. When it is None, the only new statement (`if verify_sink is not None: append`) is skipped.
- Other callers pass nothing, so they behave exactly as before.
- The append happens after the existing mismatch raise and unmeasured print. An HTTPError from `_api` comes before the append, so the 409/422 retry branch is unaffected.
- `batch_push` always passes its own list. The only observable delta is an additive `"verified"` key in its return dict.
  - Its consumers are `push_to_github_batch.py`, `checkpoint_deliver.py` (`dict(...)`) and `_push_file_via_batch`. None of them compares the dict for equality.
- The default retry path still calls `build_entries` and `update_ref` with the same arguments, plus the sink.

## Widened stubs
- `test_entry_guard_rename_and_full_list`: the `**_` only swallows `verify_sink`. Its assertions on `self.blobs` are unchanged.
- `test_push_batch_atomic` `flaky_update`: `**kw` is forwarded to the real `update_ref`, so the stub is stronger than before. No assertion was weakened.

## Cumulative strict mode: still satisfied
These tests are present and green:
- An additive INDEX.md update at an unchanged base passes with no `--allow-overwrite` (`test_strict_mode_passes_without_any_flag_when_remote_equals_base`).
- STOP on any drift:
  - HEAD moved, single file and batch.
  - Append-only divergence: STOP with no rebase.
  - 409 on ref update: STOP with no second commit, single file and batch.
  - Path appeared after the pin.
  - Live sha None.
  - Truncated tree is unmeasured.
- No auto-rebase in strict mode. Default-mode rebase_append and the 409 rebuild are still asserted unchanged.
- The expected base must be exactly 40 hex characters: a short prefix is rejected and `ExpectedBaseNotExact` is a `BaseDriftRefused`.

## Tests (SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly, private TMPDIR)
- Strict + remote-blob suites: 42 passed.
- All 24 pusher suites: 485 passed, 1 skipped, 2 subtests.
  - These are `test_push_*`, copy guard, registry index guard, `safe_site_push*`, pre_push_guard, no_live_push_state, shared_memory_unmeasured_base, checkpoint_deliver, entry_guard, autopush, push_registry and problem_push_linkage.
  - The run also prints a network-guard notice for `test_checkpoint_deliver::test_branch_for_builds_wip_branch`. It already appears at 8e416ade1 (476 passed there), so this commit did not cause it.

## Mutation: 10 mutants, 7 KILLED, 3 SURVIVED (none of the 3 blocks)
- KILLED:
  - M1, the via_batch dry-run early return.
  - M2, batch dry-run before the HEAD check.
  - M3, the action key removed.
  - M4, "match" hardcoded in via_batch.
  - M5, the aggregate always "match".
  - M6, the ref sink dropped.
  - M7, the blob sink dropped.
- SURVIVED:
  - M9, empty sink read as "match": equivalent, because `changed` is non-empty, so there is always at least one blob and a ref.
  - M10, `main()` back to `r['action']`: this was a belt-and-braces change, and M3 covers the key itself.
  - M8, the sink not reset on the default-mode 409/422 retry: no test covers it.
    - Effect: an unmeasured verdict for an orphan first-attempt blob could only make the result stricter ("unmeasured"), never falsely "match".
    - It is default mode only; strict mode STOPs before any retry.
    - Severity: P3, optional. A test is possible but not required.
