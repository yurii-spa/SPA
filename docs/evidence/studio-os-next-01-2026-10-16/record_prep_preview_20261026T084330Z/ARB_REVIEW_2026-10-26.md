# ARB follow-up — record preparation fixes and delivery review

Date: 2026-10-26, Europe/Madrid. Decision owner: ChatGPT / ARB.
Implementer: Claude Code. Owner authority remains with Yurii.
Reviewed: the full final report pasted in chat after CI 40295468694.

## Decision

R2 concurrency protection and U1 owner-facing presentation are accepted in the tested candidate scope.
R1's original source-during-call, changed-source-set and card-during-call reproductions are fixed.
R1 is NOT fully closed: meaningful code-version binding is still missing. One remaining case is reproduced
below. Finish that specific boundary and correct the delivery note; do not reopen accepted work.

No production delivery, routing, execution or acceptance-probe assignment is accepted by this review.
No new model call, whole-system audit or additional testing tier is required.

## Evidence independently checked

- Local HEAD and GitHub branch ref: e902243e0a7c39f6b562d642a4b3eda7cfc80f65.
  Tree clean before these ARB documentation edits.
- Tested candidate: e289dcd1cf2f364212ed725cc189e16ac943edaa, code commit abe2bc668.
  Only CI documentation and W44 journal above the candidate.
- GitHub 40295468694: completed/failure; report SHA matches run; artifact digest verified.
  135899 total; 135178 passed; 2 failed; 719 skipped; 0 error/not obtained/collect errors; 12/12.
  Exact failure IDs are the two previously known office producer-tick §49 failures, so no new failed
  IDs versus 1215d3b77. CI remains RED; §49 NO_REGRESSION is not established.
- Independently reran test_task_prep_record.py: 27 passed in 5.69 s, including the two-process and
  SIGKILL controls. Read implementation diff and the new tests.
- Read measurements.json and CDP capture implementation; inspected after_390px_mobile.png.
  Clarification is a question; stale results are labelled stale; raw code/diagnostics are moved to
  technical details; model HTML is rendered as text. Fixture and physical-iPhone limits remain explicit.
- Correction to previous review: the earlier cropped screenshot was not proof of layout overflow.
  The new CDP measurements report viewport widths 390/430 and no overflow; the old candidate at a real
  390px also reports none. ARB accepts that correction and does not claim a former overflow regression.
- No new model call, CI launch, production write, restart or live tracker change by ARB.

## Remaining R1 — code names are not code identity

build_inputs currently includes code_changed_since_verified, which is a LIST OF PATHS from role_pack.
It omits the actual code content/revision fingerprint. preparation_state does not compare code identity
either; it only re-hashes the recorded document/extra sources.

Reproduction on a temporary fixture repository:
1. Keep the same verified_sha and handover/docs.
2. Commit spa_core/x.py with x = 2; prepare the ordinary record.
3. Commit the SAME file with x = 3; re-read the state and repeat prepare_record.
Observed:
- code HEAD changed from 3e2a67d261520fa9f60cdb81468ddf51ae75cefa
  to c081ebabb0369e5083c849e6a86d9d7ea4676342;
- both code_changed_since_verified values are ['spa_core/x.py'];
- identity is unchanged;
- the old preparation is current;
- the new invocation returns unchanged with only the first fixture call.
Evidence:
 /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-code-identity-e289-z7v1q9ds/findings.json

This is the remaining part of the requested revision binding, not a new audit domain.
Required: capture an actual meaningful code snapshot identity, and independently check it both in
deduplication and the read-model freshness verdict. A pinned immutable code snapshot with explicit
refusal on drift is also valid; do not claim that a path list identifies bytes.
Cover committed changes to an already-changed file and uncommitted changes. Same inputs at another
generation time remain reusable. Define treatment of documentation-only commits explicitly.
Old records without this evidence must not silently pass the new code-freshness check.
Display a plain reason such as “изменилась версия кода” when stale. No tracker lock or provider redesign.

Rationale: plan freshness includes the implementation state supplied in the context; a later version
must not inherit an earlier version's current verdict just because filenames stayed the same.
Alternative rejected: storing HEAD informationally while never comparing it.
Consequence: one narrow correction and regression controls remain before readiness review.

## Delivery note — finish without production changes

DELIVERY.md is a draft, not an executable release package yet. Correct these items in the same package:

1. Use concrete --root, handover, verified SHA, config and source locations consistent with the code
   snapshot that will be read by both prepare-record and the cockpit builder. Explain how retained
   documents/commit objects reach that root: copying only code directories does not deliver them.
   Choose a single prepared release scope without overwriting newer origin/main or local production
   changes. Read/diff the relevant paths only; do not start a whole-system audit or copy old directories.
2. The asserted mandatory mission_server restart “because it holds old UI” is not demonstrated:
   Serving.refresh reads the changed bundle pointer and atomically reloads bundle files.
   Determine whether this delivery actually changes an imported server dependency. If only the UI/data
   bundle changes, validate the existing refresh path on a temporary root and avoid an unnecessary restart.
   Never restart production just to find out.
3. Show the exact scoped method to set/remove SPA_TASK_PREP_ROOT in the builder's real launch context,
   without changing other environment values; currently the note only names the environment variable.
4. Keep stale-input edits, concurrent calls and fixture failure probes on TEMPORARY cards/stores.
   Do not edit an owner's live card for a smoke test. Live validation, once authorized, reads the chosen
   record and resulting bundle. Separate intake.my_records raw preparation from the owner_view row:
   preparation.head is an owner_view field, not the raw intake field.
5. Do not require a separate owner decision for each reversible substep. Prepare ONE concrete bounded
   delivery proposal, backup/restore strategy and any actually required restart. Execution still needs
   the owner's approval under the existing session constraints and deployment.md §6; no approval asked now.
   No automatic rollback deletes or destructive sync flags.

## Next package

Close the remaining R1 case plus the delivery-note gaps above. Budget 30–60 active minutes.
Preserve the accepted R2/U1 and previous census correction. All regression scenes temporary, no real model.
Run relevant mandatory checks before one full CI on the final code SHA; base e289dcd1c / 40295468694.
Report the concrete delivery candidate and what would change, without executing it.
If a safe release snapshot cannot be prepared in scope, name the exact mismatch and preserve the tested
implementation; never describe a stale directory copy as ready to deploy.

Include this review and the updated ROADMAP/handover in the next normal integration-branch commit.
Assignments null; ADR-762 OFF; weekly_backup ON; real capital $0; paper history untouched.
No main/merge/force-push, deployment, service/schedule changes, tracker writes, deletion, stash operations,
local-model invocation or new paid/API/real model calls.
