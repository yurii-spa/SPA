# ARB review — cockpit record preparation candidate

Date: 2026-10-26, Europe/Madrid.
Decision owner: ChatGPT / ARB. Implementer: Claude Code. Owner authority: Yurii.
Report reviewed fully: Вставленный текст(20261026-081548).txt, 283 lines.

## Decision

Accept the bounded census-test fixture correction (6879ce431) and acknowledge that the existing cockpit
read model/UI now displays a preparation on temporary data. The whole record-preparation package is NOT
accepted for connection or delivery yet: freshness/reuse and concurrent output integrity have reproduced
defects; the owner-facing preview also needs finishing.

The previous task-prep result-contract R1/R2 remains accepted; do not reopen it or the census work.
The findings below concern the NEW record connection. No new whole-system audit or model call is requested.
One repair package should close these findings and produce a usable mobile preview plus a concrete prepared
delivery package. Execution, live scheduling, model routing and deployment remain outside this package.

Rationale: a plan may be shown as current when the model saw different input; simultaneous preparations
currently share an output directory. Both contradict the accepted preparation contract before any question
of autonomous execution arises. Alternatives rejected: accepting these as cosmetic, broad system redesign,
or routing around the existing cockpit. Consequence: finish the existing implementation; preserve all
evidence and the independently accepted timeout correction.

## Independently established

- Working copy: /private/tmp/spa_wt_taskprep_20261025T234122Z.
  HEAD and GitHub branch ref agree: 0d3a85e24d236619e2d9b24def628c1cf23a2f95.
  Worktree was clean before ARB documentation edits.
- CI-tested candidate: 1215d3b775ca5945cb1a2ac7c3b0be991a0bce42.
  Only CI documentation and W44 journal were added above it.
- GitHub CI 40250024701: completed/failure. Downloaded report archive digest matches GitHub SHA-256.
  135886 total; 135165 passed; 2 failed; 719 skipped; 0 error/not obtained/collection errors;
  12/12 shards complete. The two failure IDs exactly match the prior §49 failures:
  * spa_core/tests/test_office_declaration_doors.py::TheLiveAnswerOfTheOrder::test_every_office_artifact_has_a_measurable_producer_tick
  * spa_core/tests/test_office_subject_drift_producer_tick.py::test_the_live_office_can_measure_the_tick_of_every_artifact_it_reads
  Thus the previous timeout is absent, no new failed IDs versus either supplied baseline.
  CI is RED; no overall NO_REGRESSION or production acceptance.
- ARB target run: test_task_prep_record.py + test_task_prep.py +
  test_list_identity_census.py::MeasureRefusesInsteadOfGuessing: 66 passed in 15.50 s.
- Read the changed implementation/tests, preview generator/README, and inspected the actual 430px screenshot.
  The screenshot is a fixture scene. It does not prove live phone/voice/Telegram operation.
- Two full CI runs were reported: first found an implementation defect, second tested the corrected SHA.
  The second run was justified by a changed candidate after failure; the omitted prerequisite check
  should be corrected in the existing checklist, not by introducing another audit/testing tier.
- ARB did not call a model, start CI, launch a server, restart services or write to production/tracker.

## R1 — preparation identity and freshness, reproduced on temporary data

A. Extra source changes DURING adapter execution:
- context.md contains SOURCE VERSION A;
- adapter changes extra.md to SOURCE VERSION B;
- sources_sha256 records B, because run_review hashes extra sources AFTER execute;
- returned preparation state is current.
The model's actual input and the freshness reference therefore describe different bytes.

B. Add a NEW extra-context path to a repeated prepare_record call:
- action is unchanged, provider call count stays 1;
- the reused context does not contain the newly requested source.
Deduplication only compares OLD recorded sources; it does not bind the requested source set,
handover/roadmap selection, verified revision or provider/configuration of the new call.

C. Change the card DURING adapter execution:
- prepare_record returns current using the old in-memory card text;
- preparation_state on the actual reread card returns stale.
The explicit CLI can therefore report success for an already changed request.

Required correction:
- capture raw source bytes/fingerprints at the same read that contributes to the prompt; retain the
  sanitized context fingerprint separately. Do not relabel an old answer with post-call source bytes;
- bind a preparation to a deterministic input identity: full request/card identity, selected source
  set and relevant source bytes, meaningful revision fields, explicit role/provider/config inputs.
  Time of generation must not invalidate an otherwise identical request; new inputs must not be ignored;
- validate current invocation before reuse; reread current card/source inputs after the call and when
  displaying. Changed input => stale/refused, never success/current. Preserve the old record unchanged;
- keep model/tool freedom and the existing provider contract; do not introduce a new universal platform.

## R2 — concurrent requests share one result directory, reproduced

Two threads entered prepare_record for the same card/input/time, with a barrier inside the fixture adapter.
Observed: TWO provider calls; BOTH returned action=prepared with the SAME run directory; only ONE stored
run remained. out.exists() before the call and later mkdir(exist_ok=True) do not reserve the operation.
This is a collision/overwrite path even though the sequential repeat test passes.

Required correction:
- serialize or atomically claim preparation for the same input before invoking a provider, with a
  process-safe mechanism scoped to the preparation store, not a new global tracker lock;
- atomically reserve unique output directories and preserve all prior/partial evidence;
- a concurrent loser must not call the provider or overwrite the winner (explicit busy/refused is fine);
- interruption cannot make partial output look complete or leave a claim permanently authorizing success;
- test concurrency across processes plus interruption at the claim/write boundary on temporary data.
  No real provider is needed for these controls.

The ARB reproductions and current temporary artifacts are at:
 /var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-record-prep-repro-t14wzbg6/findings.json
They changed only their own temporary scenes.

## U1 — finish the same owner-facing block

The inspected 430px screenshot shows clipped right-hand text and exposes NO PLAN, NEW CHECK NEEDED,
UNKNOWN, subject NONE, card_acceptance.PROBES and English diagnostic reasons as primary text.
The clarification case says “план подготовлен” while showing “План: NO PLAN”.
This does not meet “понятный план или вопрос, простыми словами”.
The report attributes clipping to existing layout; ARB has not measured before/after causality.
The acceptance issue is the delivered candidate view, regardless of whether every CSS defect is new.

Keep the same UI and existing details disclosure:
- clarification => “Нужно уточнение” with the question; do not show a fictitious plan;
- plan => short intended outcome, steps, and honest execution state;
- show plain reasons such as “Проверка результата ещё не назначена; работа не начата”;
- put internal identifiers, raw model markers, source fingerprints and diagnostic details under the
  existing technical-details disclosure; do not hide the fact that authority is unverified;
- make the touched record/preparation block fit 390px and 430px without clipped text or horizontal scroll;
- keep text-node rendering and label fixtures accurately. This is not a redesign of the whole cockpit.

## Next bounded package and acceptance

Complete R1, R2 and U1 together, 60–90 minutes active work; do not spend this on repeated broad audits.
Show:
1. The three R1 scenarios fail on old code and pass after the correction.
2. Concurrent preparation invokes the fixture once; earlier and interrupted evidence is preserved.
3. Changed/unknown source data never display current; incomplete/refused never display a ready plan.
4. Actual candidate UI at 390/430px with a readable plan, a question, stale and failed cases, safe text.
5. Relevant mandatory checks, including prior_run_operand_census BEFORE full CI; preserve the accepted
   census tests. Then one full CI on the finished code SHA, compared to 1215d3b77 / 40250024701.
   If code changes after a failing CI, the new code needs its own truthful result, not reuse of the old SHA.
6. A concrete prepared delivery/rollback note: selected preparation-store path and explicit caller,
   integration points, dependencies, switches, smoke test, and limits. No installation or restart now.
   Do not choose or enable automatic execution/acceptance-probe assignment as part of this correction.

Preserve the three ARB documentation edits (this review, ROADMAP and handover) and include them in the
next ordinary branch commit. No deletions, clean/prune/stash operations, main/merge/force push, deployment,
production/tracker writes, schedule changes, service restarts, local models or new real model calls.
Assignments null; ADR-762 OFF; weekly_backup ON; real capital $0; paper history untouched.
