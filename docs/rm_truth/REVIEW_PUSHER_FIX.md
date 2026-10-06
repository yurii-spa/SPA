# Independent review — pusher >1MB fix (rmtruth/fixG ddc680757, diff c97162f78..ddc680757)

Reviewer: independent; read-only; own worktree /tmp/spa_rmt_rvp (removed at end). No GitHub writes (one read-only tree GET).

## VERDICT: CHANGES_REQUIRED

## What is correct
- `get_blob_bytes`: 40-hex check before any network call; every exception, non-base64, bad encoding -> `RemoteBlobUnavailable`; `git_blob_sha(bytes) == blob_sha` is checked on EVERY blob read (mismatch -> `RemoteBlobShaMismatch`). It never returns None or "safe".
- `get_file_content(expected_sha=)` does not re-read the branch; it maps every blob failure to `None`. Callers fail closed on None + known sha (`guard_content_loss`/`guard_entry_loss` -> "НЕ ПРОЧИТАНО"; `rebase_append` None -> `DivergenceRefused`). The no-pin path reads Contents, and when content is missing it reads the blob by the SHA that the same response named. The bytes match the sha they claim. I found no path where None or an exception becomes "safe" inside these functions.
- Batch flow: `get_base_ref` pins commit+tree, then `split_unchanged` reads live shas, `remote_tree_modes(pinned tree)` gives modes+shas, `assert_base_tree_matches` runs, then guards (`guard_overwrite` reads bytes by the same sha), blobs, tree(base_tree=pinned), commit(parent=pinned), PATCH ref with force=False. For paths that exist in the pinned tree, guard bytes == bytes of the pinned base commit. That is correct.
- The real origin tree is NOT truncated (measured: 8864 entries, truncated=False, INDEX.md present). The pin check is therefore live for INDEX.md.
- Shims: `scripts/push_to_github.py` and `push_to_github_batch.py` re-export from root. The only external user of the old 2-tuple is the root module, and the shim re-export of `remote_tree_modes` stays compatible.
- Tests: the 13 new tests plus all pusher suites give **355 passed** (TMPDIR outside any git repo). With the sandbox TMPDIR, 23 tests fail on BOTH base c97162f78 and ddc680757 with an identical set, so they are environmental and not this change. 10 of 13 new tests fail on the old code, so they are real positive controls. The 5 updated test files only add the `expected_sha=None` kwarg to fakes. One fake tree sha changed from "x"*40 to the real sha. That change is justified and weakens nothing.

## Findings
**P0-1 — AUTO-REBASE newly enabled for INDEX.md; contradicts "NO AUTO-REBASE" and "remote changed since candidate ⇒ STOP".**
`test_additive_only_large_index_update_passes_without_any_flag` builds the case where the remote has changed since candidate preparation (remote = base + another session's row). It asserts the push SUCCEEDS with `landed == remote_now + my_row`, which is `rebase_append` merging our tail onto a newer remote. Before this fix, >1MB files could not reach `rebase_append` because the remote bytes were None, so they refused. The fix therefore newly enables content auto-rebase for INDEX.md. Required scenario (c) is tested only with a mid-file edit, so the append case of "remote changed" is not a STOP. `rebase_append` itself is pre-existing behaviour for <1MB journals. Fix: in the owner-sanctioned delivery mode, DIVERGED must STOP even if the change is append-only. Use a flag or policy, or make the additive test cover "remote == candidate base + our rows only", and flip test (e) to expect a refusal. Note: there is still no notion of an "expected origin commit" supplied by the caller. Divergence is per-file versus the checkout's origin/main.

**P1-1 — 409/422 ref-update retry re-parents onto a newer origin (pre-existing, not introduced).**
On a non-fast-forward error the code re-reads the base and re-runs `assert_base_tree_matches` and `build_entries` (overwrite/entry/name/stale-base guards, including `rebase_append`) against the fresh base. It then recommits on the new parent and PATCHes, and only prints "recommit". The ADR-number and change-evidence interlocks run once in main() on local files and are not re-run. Those checks are mostly independent of the base. This is a silent re-parent onto a newer origin. The code existed at c97162f78; this commit only adapts the tuple and adds the drift assert. Per owner policy it must become a STOP: raise on 409/422 with "origin moved, re-prepare the candidate". It needs a test.

**P1-2 — the new STOP-on-drift code has zero tests.** `assert_base_tree_matches`/`RemoteMovedDuringRead` are not exercised by any test (grep of spa_core/tests, tests, scripts/tests). All large-file and stale-base tests go through single-file `push_file` (Contents API). None goes through `batch_push` with a >1MB file. Add batch-path controls: live sha != pinned -> STOP; the retry path; a large INDEX.md through batch.

**P2-1 — `assert_base_tree_matches` skips two drift and read-failure cases** (measured by direct call):
(a) live sha None while the path exists in the pinned tree, which is a live read failure: PASS. Downstream this becomes UNMEASURED. INDEX.md is still refused as shared memory, but other paths push over the base with only a note. That is pre-existing unmeasured-non-blocking behaviour.
(b) live sha present while the path is absent from a non-truncated pinned tree, meaning the file appeared after the pin: PASS.
Simpler and stronger: use the pinned tree sha as the authoritative `remote_sha` for the guards. When the tree is not truncated, absence in the tree means a new file. STOP when it is truncated or ambiguous.

**P2-2** — The docstring of `get_file_content` still describes it as "ТОЛЬКО для пере-базы". It is fine otherwise.

## Required-scenario coverage
normal <1MB ✔ · >1MB ✔ · remote changed ✔ only for a mid-edit (append case auto-rebases, P0-1) · local removes rows ✔ (guard-level) · additive-only ✔ but via auto-rebase (P0-1) · Contents down + Blob OK ✔ (expected_sha path) · Blob SHA mismatch ✔ · read failure ⇒ STOP ✔ at blob level; live `get_file_sha` failure is not covered (P2-1a).
