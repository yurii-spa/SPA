# ARB — release CI and reuse of the existing provenance optimization

Date: 2026-10-27, Europe/Madrid. Decision owner: ChatGPT / ARB.
Implementer: Claude Code. Publication/deployment authority: Yurii.

## Decision

The authorized publication and one full CI are completed and accepted as evidence. R1/R2/U1 and the
v3 conflict guard remain accepted. Release 6ca0ce2a8 is NOT cleared for production or NO_REGRESSION.
Next work is a bounded LOCAL portability correction using the existing optimization from 34e5bc85a,
not a new performance audit. First use only its Resolver assignment-list caching hunks: they apply
cleanly and independently reduce the measured hot path without changing the report.

The authorization on 26.10 was for the exact release SHA and one full CI. Do not silently extend it to
a changed release SHA or another full release run. Preserve the published candidate and original CI.
Normal integration documentation commits remain allowed. Prepare the corrected local release before
requesting any further publication/CI decision. No production/main/feature enablement is authorized.

## Independently checked evidence

- Remote release/task-prep-20261026 points to 6ca0ce2a8cff3b2d44aa94e9e32f7b3c499736b7.
- CI 40353173933: report and workflow SHA agree, completed/failure; artifact digest verified:
  sha256:35ea5fb843d26a75324d1ab37b475efc24dd09ced5f65d5fe306b2acd469b130.
  136309 total; 135524 passed; 63 failed; 3 error; 719 skipped; 0 not obtained/collection errors; 12/12.
- Baseline CI 40328594274: d0c3c59ed3ed89743a0296c2a77faaf2dbd3862a, digest verified:
  sha256:76020aaa6e4cc1971088cf4d27597ec702b6db435951cc16d5acaac82d94e761.
  136042 total; 135266 passed; 57 failed; 0 error; 719 skipped; 12/12.
- Recomputed failure-ID comparison: 57 pre-existing, 9 new, 0 fixed. Baseline is approximate:
  the exact release parent is 37e06e185, which adds ADR-820 code/tests and docs over d0c3c59ed.
- Package/UI cohorts really executed: 38 task_prep_record, 43 task_prep, 27 contract, 19 review,
  78 probe, 15 role_pack, 104 owner_view, 26 cockpit_loop; all 350 passed. Both formerly errored
  foreign_markup_reader_census cases passed in this release. Earlier integration CI remains RED.
- Downloaded and digest-verified ctl-shard-8; examined every JUnit attempt and stream summary.
  Shard 8: 4 attempts, 3 crashed_on entries, wall 3613.5 s.

## Correct the causal description

The nine new IDs are NOT one timed-out test followed by eight unexecuted assertions.
There are SEVEN new failed tests with explicit JUnit Timeout (>180 s), all stopped at
Resolver.enter -> ast.walk(fn), plus TWO new internal-error outcomes. The third internal-error
outcome belongs to an ID already failed on the baseline. In total this file has ten reported
timeouts and three internal errors, including its four pre-existing failed IDs.

See arb_new_failures_20261027.json for exact new IDs and JUnit attribution.
This is one repeated expensive code path, but several real timeout observations. No evidence here
quantifies how much the added package versus CI runner load contributed. Do not label it harmless.

## Existing fix found and measured

Commit 34e5bc85a5bbe8d71ba4cb26d8eff2cbe336b974 (22.10) already addressed the same timeout/internal-error
pattern. It contains assignment-list caching per function and whole-census memoization by source bytes.
The current integration branch contains it; main 37e06e185 and release 6ca0ce2a8 do not. Their provenance
scanner and its test file are identical. Historical evidence is recorded in W43, not a new invention.

Blindly copying the current scanner from integ is inappropriate: its diff from the release also includes
319 added / 14 removed implementation lines and 221 test lines with semantic detection changes.
The entire 34e5bc85a patch does not apply cleanly because main lacks that later census structure.
ARB checked compatibility on a temporary copy: its first TWO Resolver hunks apply cleanly.

Independent bounded measurement, same exact release-input tree, two scanner implementations loaded
outside that tree; no input code mutation between measurements:
- original: 100.725 s, 85 rows;
- Resolver-only optimization: 9.365 s, 85 rows;
- complete sorted JSON report bytes identical; common SHA256:
  14c8ae4ce620661204990d44391f3418b70f4f22da802b30c2a6701631bf7df8.
See arb_provenance_timing_20261027.json. This is a local performance/equivalence control, not full CI.
Temporary evidence: /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-provenance-transfer-4s9nzbxg
CI evidence: /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-release-ci-40353173933-43m9taim

Rationale: reuse the already implemented hotspot correction and preserve scanner semantics.
Alternatives rejected: blind full-CI retries; increased timeouts; excluding tests; copying the whole
newer scanner or all integration changes; a broad new profiling project.

## Next bounded Claude package

20–30 active minutes, plus the necessary targeted test runtime:
1. Make a fresh local candidate based on published 6ca0ce2a8. Port only the two Resolver hunks from
   34e5bc85a first. Do not alter detection rules, baseline entries, pytest limits or shard harness.
   Whole-census memoization is unnecessary for the first candidate given the measured 10.8x improvement.
2. Verify exact-parent comparison for this FILE on main 37e06e185 and the local corrected release.
   For the slow exact parent, collect one census/baseline verdict and relevant existing evidence; do not
   repeat the unchanged full-tree traversal for every baseline-metadata case. Reuse ARB's release
   before/after report control. Run the targeted file on the corrected candidate,
   compare outcomes with the exact parent, and preserve pre-existing failures rather than weakening
   assertions. A small control of the same function with different inherited inputs may substantiate
   that only the assignment-node list is cached, never values derived from the current inputs.
3. Run required checks relevant to this change, not a repeated whole-system audit. No full baseline
   CI is needed merely to diagnose this known hotspot. A whole-system no-regression verdict remains
   unestablished without appropriate complete evidence; the approximate baseline must stay labelled.
4. Finish a new local release commit, patch/manifest and updated delivery scope. Show the precise delta
   from 6ca0ce2a8 and the added script path versus the original 23-path package. Keep all old evidence.
5. Correct the one-timeout/eight-cascade wording in the report, update STATE/W44, and include ARB docs.
   Report exact candidate SHA, targeted outcomes, equivalence/performance evidence, remaining debt and
   readiness for one future full CI on the new SHA. Do not push a new release SHA or dispatch another
   full CI now; the earlier authorization was exact and has been carried out.

Do not reopen task-prep, mobile UI or provider audits. No model calls, main/production writes, restart,
schedule/tracker changes, deletion/stash operations or paper reset. Assignments null; ADR-762 OFF;
weekly_backup ON; real capital $0. The next product milestone remains a visible prepared plan in the
working cockpit; the rollout is pending this validation, not a redesign of Studio OS.
