# Independent re-review (round 3) — pusher strict mode, rmtruth/fixG 8e416ade1

Reviewer: independent, read-only. Own worktree /tmp/spa_rmt_rvp3 (removed). No GitHub calls; fakes + code trace only.
Probe/mutation scripts: scratchpad/rv3/{probe_dry.py,mut3.py}.

## VERDICT: CHANGES_REQUIRED — minor, NOT a safety hole. All round-2 safety findings CLOSED; one new P2 (CLI dry-run crash) introduced by the P2 dry-run fix.

## Round-2 findings
- **P1-NEW (single-file Contents PUT does not pin the parent): CLOSED.** `push_file(expected_base=...)` now delegates at function level to
  `_push_file_via_batch` -> `batch_push([one file])`. That path builds `create_commit(parent=pinned)` and then a non-force PATCH, and 409/422 raises `BaseDriftRefused`.
  No Contents PUT remains in strict mode (asserted by `test_strict_mode_single_file_uses_batch_push_not_contents_put`).
  Every strict refusal folds to `{"ok": False, "diverged": True}`, and the single-file CLI path prints FAIL with exit != 0.
- **P2 single-file strict 409 test: CLOSED.** `test_strict_mode_single_file_push_file_also_stops_on_409_no_second_commit` covers it:
  exactly 1 commit with parent = pin, and 0 ref updates.
- **P2 vacuous `or True`: CLOSED.** It is replaced by real asserts on `--expected-base` and the given sha in the error text.
- **P2 short-sha prefix: CLOSED.** `assert_expected_base` requires `_is_sha40` before any network call and raises `ExpectedBaseNotExact` (a subclass of `BaseDriftRefused`, so rc=4 in batch).
  The comparator is now exact equality.
- **P2 dry-run skips the HEAD check: HALF-CLOSED.**
  - At function level, `batch_push` runs `assert_expected_base` before its dry-run branch. It makes only 2 read-only GETs (git/ref/heads/main, git/commits/<sha>): no POST, PATCH or PUT. This was verified by running main() under the fakes.
  - **P2-NEW BUG:** `main()` always routes `--dry-run` through the per-file `push_file` loop. In strict mode the result is `{"ok", "dry_run", "path", "base_commit"}` with NO `"action"` key.
    `main()` then does `print(f"{r['path']} → {r['action']}")` (around line 2763), which raises `KeyError: 'action'`. Reproduced for 1 file and for 3 files.
    So `push_to_github.py --dry-run --expected-base <good sha>` exits with a traceback on a VALID pin. It fails closed with no writes, but the advertised pre-validation is unusable from the CLI.
  - Fix: return `"action": "would commit on pinned base <sha8>"` from `_push_file_via_batch` in dry-run, or use `r.get("action")` in main.
  - Add a test: a main()-level `--dry-run --expected-base` run gives rc 0, makes only GETs, and a wrong sha gives FAIL with rc != 0.

## Default mode
Unchanged. The net diff vs ddc680757 on non-strict paths:
- `push_file` gains only the `if expected_base is not None:` delegation; everything after it is identical to the baseline (the 86eefa152 strict blocks were fully removed).
- `batch_push`, `assert_base_tree_matches`, `build_entries` and `guard_overwrite` change only under `expected_base`, `strict` or `strict_base`.
- The 409/422 rebuild and `rebase_append` are untouched.

## Tests (SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly, private TMPDIR)
- Strict + remote-blob suites: 33 passed.
- All pusher suites (`test_push_*`, copy guard, registry index guard, `safe_site_push*`, pre_push_guard, no_live_push_state, shared_memory_unmeasured_base): 341 passed, 1 skipped.

## Mutation (9 strict branches, source restored, cmp-verified clean): 7 KILLED, 2 SURVIVED
- KILLED: removed delegation; removed sha40 form check; batch strict 409 STOP; via_batch Divergence->ok; via_batch drops expected_base; strict build_entries; strict tree-match.
- SURVIVED: M3 exact->prefix compare is EQUIVALENT (the sha40 gate comes first), which is fine.
- SURVIVED: M6 (dry-run returns before `batch_push`, so no HEAD check) has NO test. This is the same gap as P2-NEW.

## P3 (optional)
`_push_file_via_batch` reports `verified: "match"` unconditionally, even when the blob or ref verdict was "unmeasured" (`batch_push` only prints that). The default path distinguishes the two.
