# ARB review — task preparation R1/R2 and first real response

Date: 2026-10-26, Europe/Madrid. Decision owner: ChatGPT / ARB.
Implementation owner: Claude Code. Owner authority remains with Yurii.
Reviewed report: Вставленный текст(20261025-232824).txt, all 1057 lines.

## Decision and scope

Accept the R1/R2 result-contract corrections and the narrow functional demonstration of one real
task-prep response. This does not accept autonomous execution, model qualification, Pro compatibility,
production delivery, full-system stability or §49 NO_REGRESSION.

The next product increment is a candidate connecting one ordinary cockpit record to a visible
preparation in the existing “Мои записи” interface. It prepares and displays; it grants no permission
and assigns no acceptance probe. An owner-wide requirement to approve every ordinary task is NOT introduced.
Existing authority rules remain; the later execution connection must honour them and predeclare a real
outcome check. The model's question “approve every plan or start immediately?” is not a reason to stop
this preparation increment.

Rationale: the real response understood existing components but proposed installing a not-yet-existent
check. Its result is useful input to review, not an executable instruction.
Alternatives: direct installation of model proposals rejected; a new universal approval UI rejected
(ADR-762 remains OFF); more standalone model demos deferred in favour of the visible connection.
Consequence: a useful interface candidate proceeds while execution and deployment remain separate.

## Independently established

- GitHub API branch ref: 22fe8c8cf21df82c237211330986bd2c2abc2a8c.
- Tested candidate: a5724a1028562cdf9f2cc1bb5fe3839e5fa8af9d.
  HEAD adds only the CI report and journal.
- Code diff: arch_review.py and test_task_prep.py. Required sections now feed one preparation
  assessment; rendering and task-prep CLI exit use it. A valid clarification may retain unknown
  authority. Default arch contract preserved.
- Targeted tests in an isolated exact-HEAD copy: 62 passed in 13.37 s.
  Population is 43 task-prep + 19 model-role-review tests; report's “44 task-prep” is a count error.
- GitHub run 40234524248: completed/failure, exact candidate SHA, artifact SHA-256 matches GitHub
  digest. Full report: population 135870, passed 135148, failed 3, skipped 719, errors 0,
  not obtained 0, collect errors 0, 12/12 shards complete.
- Failure IDs:
  - spa_core/tests/test_list_identity_census.py::MeasureRefusesInsteadOfGuessing::test_a_measured_population_with_a_candidate_outside_is_a_finding
  - spa_core/tests/test_office_declaration_doors.py::TheLiveAnswerOfTheOrder::test_every_office_artifact_has_a_measurable_producer_tick
  - spa_core/tests/test_office_subject_drift_producer_tick.py::test_the_live_office_can_measure_the_tick_of_every_artifact_it_reads
- The last two match the prior baseline; the census failure is new. CI remains RED.
- Stored context bytes hash matches review.json; stored request text, after the CLI's newline
  normalization, matches task/request_sha256. One recorded real call, 66.654 s, status ok, one attempt.
- Old backup/vague fixture and increment6/run evidence have no committed diff versus 04f41fbca.
  This does not establish who changed other local directories.
- No model call, full CI launch, production write or restart was performed by ARB in this review.

## Real response and limits

One recorded scenario used claude_subscription_cli, current Max profile. launch_conditions.json
reports same-profile email/org hash matching and cached extra usage OFF (profile fetched 19:18Z,
observed 21:06Z). ARB read the evidence; did not independently query current account settings.
CLI cost 0.309064 is an estimate, not a billing transaction; balance/charge absence not established.
The record names Opus and Haiku; their separate roles are not established.

Useful: correct existing chain, ordinary request blocked at no_probe, readable plan, proposed
end-to-end positive/negative controls, separate delivery and phone observation.
Not approved for execution: automatic probe assignment despite NEW CHECK NEEDED; obsolete CI baseline
62fe88b48; missing acceptance.md; PHYSICAL_ACTION describes the owner's phone test rather than all
implementation work. “context_complete” means declared sources assembled, not semantically sufficient.
not_satisfied falsely labelled a probe is presentation debt, not a reason to repeat the model call.
The original output is preserved; the later real/fixture disclaimer correction is accepted.

## New CI failure: bounded treatment

The timeout and local comparative timings are reported by Claude. ARB independently confirmed the
failure ID and read the relevant test/measure implementation; did not repeat the costly census.
Similar local timings and another concurrent workflow do NOT prove runner contention or prove that
the candidate cannot affect timing. Correct language: “new timeout; timings are consistent with an
already fragile test; exact runner cause unconfirmed.”

The test class already substitutes stand construction and probe answers with synthetic module m, yet
calls population(ROOT), which traverses unrelated repository code. Its named outcome is verdict
selection (FINDING/CLEAN/UNMEASURED), not discovery of the entire real population.

ARB explicitly authorizes a narrow test-fixture change under invariant #16: give these synthetic
verdict scenes a small explicit non-empty population consistent with their probe output; retain empty
population/refusal controls and all outcome assertions. Keep the real measure/tally/verdict logic.
Inspect existing real-population coverage and retain it; if the changed test was uniquely exercising a
discovery property, preserve that property with a purposeful small-real-tree control.
No timeout increase, skip, xfail, baseline expansion, production-census rewrite or cached full scan.
Show before/after targeted duration and the existing positive/negative outcome controls.
If this cannot fit the bounded package, record the exact unresolved point, do not silently waive it.

## Next implementation package

1. Continue the same remote branch from the measured HEAD. Establish the actual usable worktree.
   The old /tmp/spa_wt_integ is no longer a Git worktree at ARB observation on 26 October:
   .git absent and it is absent from mirror git worktree list; residual directories remain.
   Branch and commits survive in mirror and GitHub. Cause/actor and any uncommitted loss UNKNOWN.
   Do not clean, delete, prune or reuse that directory. A new unique worktree/clone is allowed.
2. Preserve this review plus the updated ROADMAP and handover from the ARB review copy.
3. Reuse task-prep, mission_control.cockpit_records, owner_view.my_records and existing UI.
   On temporary data, link a preparation to one ordinary voice/text intake record and display
   intended outcome, plan/question, preparation status and honest execution status. Use explicit
   invocation in the candidate; no new schedule, live routing or confirmation mechanism.
   Store outputs under unique paths without overwriting previous runs; never write the preparation
   from a read-model/GET handler. No accepted probe, claim or done state follows from this record.
4. Include acceptance.md and the current CI state in fresh context; identify 62fe88b48 as historical,
   not the next comparison baseline. Bind the displayed plan to card/request and source revisions.
   Caller independently reads current canonical inputs. is_current alone is only a comparator:
   echoing stored hashes is not a freshness check. Incidental generation timestamps must not be
   mistaken for changed task/source content. Changed input => explicitly stale, not an active plan.
5. Controls on temporary data: ordinary input with no probe gets plan/question; duplicate processing
   does not create duplicate cards/plans or overwrite evidence; changed input invalidates displayed
   plan; incomplete/refused result is not “ready”; no auto probe/claim/done; rendered model text
   cannot become HTML/script. Keep the existing voice implementation; a fixture does not prove
   physical iPhone transcription. Provide a reproducible candidate preview from the real read-model/UI.
6. Include the bounded timeout-fixture fix above. Mandatory relevant checks, then ONE full CI on the
   final code SHA. Compare with both a5724a102 (immediate predecessor) and 5499ceca4 (before new timeout);
   report all actual failures, without rebaselining the timeout away. No repeat whole-system audit.
7. Prepare, do not execute, delivery and rollback. One report with preview path, diff, tests, CI,
   remaining execution/deployment gap. Budget: 60–90 minutes active; name a concrete blocker if exceeded.

No new real model call is required in this package: use a labelled fixture and preserve the real
response as evidence. Canonical assignments remain null. ADR-762 OFF, weekly_backup ON, capital $0.
No main/merge/force push, production/tracker writes, repair --apply, service restart, schedule change,
stash action, deletion, local-model inference/weight copies or trading-paper reset.
Ordinary commit/push and one final CI on the existing integration branch remain authorized.
