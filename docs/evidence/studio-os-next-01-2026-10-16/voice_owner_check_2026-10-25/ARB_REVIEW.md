# ARB — voice intake checkpoint, 2026-10-25

- Decision owner: ARB (ChatGPT); product owner: Yurii Kulieshov.
- Reviewed HEAD: `cf3a33b0cff0b3131427ddb6a748cdd0adf11b73`, clean before ARB documentation edits.
- Code change: `391d2c75d7ab1c4968059463049c0154bbbfe77e` (the final pasted report's `0f6b1d7…` is not its SHA).
- Fully tested candidate: `33b3219ac8b59ca56d49fa6b1e35fdcc04febf4c`, CI 40209078724.
- Decision: accept the narrow notification correction and the temporary-data checkpoint for this candidate.
  Do not infer production delivery, owner iPhone acceptance, automatic execution of ordinary requests,
  green CI or §49 NO_REGRESSION.

## Independent checks and evidence limits

ARB read the code diff, existing acceptance rule, dispatcher, composer submission path, scene and report.
The only implementation change since `f1537bf9e` is the notification heading; one test was added.
`test_cockpit_loop.py` and `test_cockpit_dispatch.py`: **47 passed in 5.26 s** under the existing Miniconda
Python environment. `git diff --check f1537bf9e..HEAD` is clean. No model call or new full CI was launched.

ARB fetched CI 40209078724 directly, verified the artifact SHA-256 against GitHub's digest, and read
`ci-control-report/report.json`: exact tested SHA above; RED; **135827 total, 135106 passed, 2 failed,
719 skipped, 0 errors, 0 not obtained, 0 collect errors, 12/12 shards complete**. The failed node IDs are
the same two §49 producer tests as the previously verified `5a0d497f0` baseline (CI 40190831822).
There are no new failed node IDs against that baseline. `cf3a33b0c` adds only CI/journal documents to
`33b3219ac`; it has no separate full-CI result.

The scene demonstrates application control flow using temporary paths, supplied provenance and fake
notifications/probe results. It does not exercise the real microphone, transcription, Access JWT,
Telegram delivery or owner-visible latency. Its before/after directory-name comparison is not a byte-level
production integrity check. ARB did not repeat the production inspection or run the live phone path.

## Corrected owner instructions

The current composer requires a kind selection; voice opening does not preselect it. The owner script
now includes **«Что это» → «Задача»**. After success the UI clears text and assigns a new submission ID.
A retry of a preserved failed request retains the old ID; manually entering text again after success
is a new intent. The old instruction to resend after success was wrong; the UI need not be changed.

The notification outbox is explicitly at-least-once. The existing crash test proves a repeated message
after an uncertain delivery. Two logical events in the normal scene are not a strict two-message cap.
The observed two-hour cycle is not a delivery deadline. Initial submission and asynchronous processing
must not be presented as one completed five-minute check. These are documentation corrections, not
new implementation blockers. Original scene outputs remain unchanged.

## Product decision: prepare the task before execution

Problem: an ordinary owner request is received but remains `no_probe`; the current next step exposes
internal probe names. Asking the owner to choose a machine check does not solve understanding the task.

The existing `.claude/rules/acceptance.md` already allows the taking session to declare the criterion
BEFORE work. It forbids changing that criterion during work and requires meaningful machine checks with
positive/negative controls. It does not require the owner to know probe identifiers. The dispatcher
remains deterministic and must not acquire an LLM call.

Selected next bounded candidate: reuse the existing memory/architect/provider seam to turn ONE ordinary
request into a reviewable preparation result: intended outcome, scope, evidence/acceptance proposal,
unknowns and required permissions. Preserve the original request and bind the proposal to its hash and
the code/context revision. This is task preparation, not task execution, a tracker writer or a new router.
Inspect the existing seams first; if `memory arch-review` already delivers this result, reuse it rather
than creating a parallel component. Implement only a demonstrated missing connection/validation surface.

A registered probe name is not proof that it measures the requested outcome. A proposed unrelated but
green probe must not make the task ready for execution. Missing or ambiguous criteria produce a plain
question or a proposal to develop a check; they never fall back to “any registered probe”. A proposed
new check is not itself an installed/accepted check. Final acceptance remains deterministic.

First delivery is a candidate on temporary inputs with an owner-readable plan; it does not alter a real
card, set `acceptance_probe`, claim work, schedule a worker or mark anything done. Review/approval of a
plan must not be fabricated as a schema flag or model text. Plan freshness and execution permission
remain explicit barriers for any later integration. No new approval is imposed on already permitted
work merely because a draft exists; actual authority comes from the existing action policy.

Alternatives: require the owner to pick probes in a new UI (not selected as the default); let the model
choose acceptance inside the dispatcher or after work (rejected); rebuild intake or audit the whole
system (unnecessary). Consequence: the next increment advances model-independent management while
ordinary live execution remains unconnected until the preparation/execution boundary is reviewed.

## Bounded acceptance and next work

- Scope: 60–90 minutes active; reuse completed checks and accepted components. No second AI audit.
- One ordinary request without internal probe names yields a useful plan or a specific clarification.
  Cover an ambiguous request, a request outside existing authority, invalid/unrelated probe suggestions,
  changed input/context, and provider refusal/quota without task loss or repeated paid calls.
- Tests/scenes use temporary files and a fixture adapter. No fresh real management call is needed for
  this package; fixture success is not real-model quality acceptance. Keep role/provider independent.
- Preserve original task/context/output provenance and existing sanitization/resource bounds. Do not
  create a second memory, scheduler, provider adapter, automatic paid fallback or arbitrary code execution.
- One full CI on the finished candidate only if implementation changes; otherwise existing mandatory
  documentation checks. Compare against `33b3219ac` / CI 40209078724, not an older baseline.
- Current owner phone check can proceed independently using corrected `OWNER_SCRIPT.md`. ARB/Claude
  do not submit it on the owner's behalf. Deployment of the notification fix remains separately gated.
- No production writes/restarts, main/merge, stash/deletions, tracker repair apply, local inference or
  weight copy. Assignments null, ADR-762 OFF, weekly_backup ON, real capital $0.
