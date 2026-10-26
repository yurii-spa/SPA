# ARB — accept R1 implementation; finish the release guard

Date: 2026-10-26, Europe/Madrid. Decision owner: ChatGPT / ARB.
Implementer: Claude Code. Deployment authority: Yurii.
Source: full attachment «Вставленный текст(20261026-125130).txt», 306 lines.

## Superseding follow-up — v3 ready for publication and full CI

Date: 2026-10-26, Europe/Madrid. Decision owner: ChatGPT / ARB.
The release-builder conflict refusal is ACCEPTED. R1/R2/U1 remain accepted; no further implementation
round is requested. The earlier blocker/next-package sections below are historical.

Independently checked after Claude's v3 report:
- Local/remote integration HEAD 9cadd32b260a36725b7a3ca73eaf59ac1730e03e; clean before these ARB doc edits.
- Server main still 37e06e185dfaddd24ca9a3e0f993e118fd20a9ba at review time.
- Release 6ca0ce2a8cff3b2d44aa94e9e32f7b3c499736b7 has exactly that parent. All 23 changed paths,
  statuses and blob hashes match RELEASE_MANIFEST_v3.txt. Integration code unchanged since aac3b4316.
- Ran the unchanged v3 builder against ARB's previous private conflicting-base control:
  exit 5, HEAD remains the base, no release manifest, refusal marker present, directory preserved.
  Evidence: /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-release-guard-j6frb0y4/v3_findings.json
- Read local release test evidence: 975 passed, 1 warning, 10 subtests; this is Claude's local evidence,
  not an independent rerun or full CI. Two previous integration CI errors remain open.
- Read release-tree workflow push triggers: the present push workflows are main-only; publication
  to release/task-prep-20261026 is not a main push. Full ci-control is to be dispatched explicitly
  with inputs.sha equal to the COMPLETE release SHA.
- Fixed a malformed push refspec in DELIVERY.md (:refs/heads/ was missing). No implementation changed.

Next action is ONE bounded publication/validation package: publish the exact local release SHA to
release/task-prep-20261026, no force; dispatch one complete ci-control run for that exact SHA; retain
manifest/JUnit/results and compare against evidence for the exact main base. Do not assume the old
+28 baseline remains exhaustive and do not waive mandatory checks. Report any missing baseline evidence.
The CI input stays pinned while main moves; assess main drift before any eventual promotion.

Owner authorization, 2026-10-26 Europe/Madrid: Yurii answered «Да разрешаю» to the explicit request
for Claude to publish release/task-prep-20261026 at 6ca0ce2a8cff3b2d44aa94e9e32f7b3c499736b7 and run
one full CI of that exact SHA. This permission persists and requires no reconfirmation.
Executor: Claude Code. Publication/CI have not been performed by ARB.
Scope: normal non-force push of this exact release SHA to that exact branch, then one complete ci-control
run pinned to it. If a matching run already exists, reuse it instead of dispatching a duplicate.
If the branch already points elsewhere, stop rather than overwrite it. Main movement during the run
does not change the approved CI SHA. Existing integration-branch documentation permissions remain.
It grants no main merge/push, production sync, feature enablement, model call or restart.
Rationale: validate the concrete reviewed release before considering production delivery. Alternative
of another integration-only run was rejected because it measures a different tree. Consequence:
remote release branch and one CI record become review evidence; deployment remains separately gated.
Full release CI is pending, so production delivery and NO_REGRESSION are not accepted.
Rationale: the reported implementation boundary is now closed; testing the assembled release is the
next useful evidence. A further general audit or repeated full integration run adds no release proof.

## Decision and scope

The remaining R1 code-content identity correction is ACCEPTED in candidate aac3b4316.
R2 and U1 remain accepted; do not reopen their audits or call a real model again.
This accepts the functional correction, not a clean CI, deployment or automatic execution.
The release builder is NOT accepted yet: its conflict path returns success. Fix this one boundary,
then prepare the exact main-based release commit and evidence for a single owner delivery decision.

Rationale: code identity now covers committed code trees, working diff and untracked code bytes;
freshness is independently checked by both reuse and the reader. Documentation-only commits outside
context do not invalidate a plan; context documents remain separately bound. Old records fail stale.
A pinned root is accepted as the explicitly named reference for preparation, not proof that production
has the same code. That equality is a delivery check, not an assumption.

## Evidence checked independently

- Local and remote integration HEAD: 1f47378ff4ed636ade29a60c4a4bdcf8eff3a0ce; clean before ARB doc edits.
- Tested SHA: aac3b43167e6eefbf407e2ed311b0cf71c627792. HEAD above it changes only CI documentation/W44.
- Read implementation/test diffs and DELIVERY.md, build_release_v2.sh.txt, enable_switch.patch and file list.
- Independently ran test_task_prep_record.py: 38 passed in 11.77 s, including the new code-content cases.
- GitHub CI 40317312101 completed/failure. Artifact digest independently verified:
  sha256:5434b929c96e12f84e524d01d1edfff669bdaa6fd7e5bfdfa74fb957c4cb5d6a.
  135910 total; 135187 passed; 2 failed; 2 error; 719 skipped; 0 not obtained/collection errors; 12/12.
  The two failed IDs are the previous office §49 failures. The TWO NEW errors are:
  test_foreign_markup_reader_census.py::test_the_live_tree_is_measured_and_the_custodian_is_in_the_class
  test_foreign_markup_reader_census.py::test_the_tree_agrees_with_the_live_measurement_of_adr_594.
  Both report fixture live_tree on shard 10. Claude reports the 180 s timeout; ARB verified the report
  outcomes, not raw runner logs. Artifact saved at:
  /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-ci-40317312101-kmt6budc/report.json
- No CI launch, provider call, production write, restart or live tracker edit by ARB.

## Release blocker — failed git apply check returns exit 0

The builder ends with:
    git diff ... | git apply --check && git diff ... | git apply
    git status --short
Under bash set -e, failure on the left of && does not terminate the script; the subsequent status succeeds.

Independently reproduced with the COMPLETE unchanged builder in a private shared clone. A temporary
commit based on f9282333e73de4c93af863c64173909e12886a49 changes only mission_control.py to force a conflict.
No source repository or production tree was modified.
Observed: stderr says patch does not apply; exit is 0; mission_control.py remains the conflicting version;
new arch_review.py already exists. Thus a partial release can be reported as successfully built.
Temporary control commit: b68144a4819a8d0ae0d87d5d47627e5725d012cf.
Evidence: /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-release-guard-j6frb0y4/findings.json

Required: explicit nonzero refusal for a failed check/apply; no successful release artifact/commit or
promotion after failure. Preserve the incomplete directory as evidence. Controls: conflicting base
returns nonzero, compatible base yields the full intended composition. No tracker/provider redesign.
Alternative rejected: relying on set -e around an AND-list, or treating stderr as a sufficient guard.

## Correct the evidence wording; no broad investigation

1. One local pair (60.17 vs 60.84 s) shows no substantial difference IN THAT PAIR. It does not prove no
   package effect or a runner cause. Keep two new errors visible. Optional diagnosis is one bounded run
   of the affected file on the unchanged tested SHA, preserving original CI; no timeout increase, skip,
   blind whole-CI retries or renewed whole-tree census project.
2. The inspected repository is SHALLOW (git rev-parse --is-shallow-repository = true). Empty merge-base
   there does not establish unrelated histories. Correct the claim to “common ancestor not established
   in this checkout”. A main-based patch remains a reasonable delivery choice without this claim;
   no deep-history download is required to finish the package.
3. release_v2.patch on f9282333e is a DIFFERENT code tree from aac3b4316. The integration full CI does not
   certify it. Report 1388 local release passes as Claude's evidence, not independent full-CI acceptance.
   The reported +28 baseline ratchet cases on main likewise remain scoped baseline evidence.
4. Use only the current version of the builder/patch in DELIVERY steps (the text still names v1).
   Keep historical versions. Update release handover/context so it does not tell the next model to
   repair R1 again. Check the actual context without a model call, including required authority sources.

## Next bounded package

Budget 20–30 active minutes, excluding a necessary bounded test wait. Fix the builder and its refusal
control; correct the evidence wording; assemble a concrete local release commit on a server-verified
main base and capture its file list/hashes. Reuse accepted R1/R2/U1 and model evidence.
Show delivery delta against the relevant current production files, preservation/backup, pinned root,
switch/rollback and the path to full CI for THIS release commit. Do not turn known main debt into this task.
Do not rerun the full integration CI merely to get green. A full release CI is still required before
claiming release verification; no new remote branch/main publication is authorized by this review.
If CI needs publication beyond the already authorized integration branch, name that concrete remaining
step; do not run against a different SHA and call it release verification.

Normal integration-branch commit/push of the fix and these ARB documents remains within scope.
No production/main/merge/force-push, services/schedules, tracker writes, deletion, stash operations,
new model calls or local-model activation. No execution/acceptance_probe assignment.
Assignments null; ADR-762 OFF; weekly_backup ON; real capital $0; paper history untouched.
