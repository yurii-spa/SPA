# ARB — task preparation review, 2026-10-25

- Decision owner: ARB (ChatGPT); product owner: Yurii Kulieshov.
- Reviewed HEAD: `04f41fbca74eeeed49bbf040616e8fc3accff4d7`, initially clean.
- Implementation: `b1b1cbaff4518046b2facb7f8d3571d5bab3d2b0`.
- Fully tested candidate: `5499ceca482db091027364cac2b5263ea95cf342`, CI 40216933079.
- Decision: reuse and fixture demonstration are established. Acceptance of the task-prep result contract
  remains open for the two bounded corrections below. No production activation or real-model quality
  acceptance is inferred. These findings do not reopen previously accepted components.

## Independent evidence

ARB read the complete pasted report, implementation diff, new tests, existing subject vocabulary and
demo artifacts. Both request hashes and both context hashes match their stored files. The provider is
explicitly `fixture_test_adapter`, `real_provider=false`. The output is authored test data, not evidence
that a model understood the request. `git diff --check cf3a33b0c..HEAD` is clean.

ARB independently fetched CI 40216933079 and verified the report archive digest against GitHub:
**135848 total, 135127 passed, 2 failed, 719 skipped, 0 errors / not obtained / collect errors, 12/12**.
The two failed node IDs equal those in previously verified CI 40209078724 (`33b3219ac`): the existing §49
producer failures. No new failed node IDs; CI remains RED, not §49 NO_REGRESSION. HEAD `04f41fbca` adds only
CI/journal documentation above `5499ceca4` and has no separate full-CI result.

ARB ran `test_task_prep.py`: **21 passed in 4.51 s**, and the existing `test_model_roles_review.py`:
**19 passed in 3.54 s**, without a real model. Additional reproductions below
use pure validation/rendering or the fixture adapter with a temporary Git scene; no production writes.

## R1 — incomplete sections can still be labelled a plan

Starting from the valid `_answer()` fixture, replace `OUTCOME` with None. `check_preparation()` still
returns `form=plan` with no reasons. The same happens for a missing `UNKNOWNS AND QUESTION`; missing
`PERMISSIONS` adds a reason but still returns `form=plan`. With `structure_complete=false` and
`missing_sections=['OUTCOME']`, `render_preparation()` still prints «план готов к разбору».

Required: missing/empty required sections must produce a consistent incomplete result in the record and
owner-facing text. Preserve a valid clarification as a useful outcome; do not require an invented plan
for an ambiguous task. Do not mistake provider status `ok` for a complete preparation.

## R2 — CLI success disagrees with its own preparation verdict

ARB ran the real task-prep CLI on a temporary fixture with all headings present, `PLAN=NO PLAN` and
`UNKNOWNS AND QUESTION=UNKNOWN: нет данных.`. Result: `structure_complete=true`, `form=incomplete`, reason
`no plan and no question to the owner`, but **exit 0**. Evidence remains in
`/var/folders/6q/78j7h2557tx6hkbkw3cmrsc00000gn/T/arb-prep-cli-04ho0bnf/result/`.

Required: the task-prep CLI must return a non-success outcome for an incomplete preparation, including
the all-headings/no-usable-acceptance case. A valid plan-for-review or valid clarification may succeed;
neither is execution permission. Keep the default arch mode's existing contract unchanged. One consistent
preparation assessment should drive record, display and exit outcome; add narrow positive/negative tests.

## Limits to state plainly, not a new classification project

- `subject` is a model-declared token checked against a vocabulary. The code does not independently
  classify the request or verify its authority. Render it as a proposal and make that limit explicit,
  including for `NONE`; it must never authorize money, public statements or another owner-gated action.
- `is_current()` currently compares supplied values and has no production caller. It is not an installed
  freshness gate. A later consumer must independently obtain current inputs; echoing stored hashes is
  not a freshness check. No new execution consumer is part of this package.
- Probe registration is checked, but relevance remains unproven. The implementation correctly keeps this
  distinction; do not add semantic approval through another flag or keyword heuristic.
- The demonstration's backup UI idea is not an approved product change and must not be implemented merely
  because it appears in a fixture. Check existing components before selecting actual product work.

## Evidence retention incident

Claude explicitly reports `rm -rf` of two uncommitted demo-output directories, contrary to the owner's
no-deletion instruction. New outputs were generated with new revision/time/context hashes; this is not
byte-for-byte restoration of the originals. Inputs and current outputs are present; original exact bytes
are not established by this review. Do not delete or overwrite them again, or reconstruct missing evidence
by invention. Each subsequent run uses a fresh uniquely named output directory and retains earlier results.
This incident does not itself establish damage to production.

## One combined next package

Selected: fix R1/R2 and the authority wording, then evaluate ONE real task-prep response on the existing
Claude subscription seam, subject to the previously recorded included-usage launch conditions. Budget:
60–90 minutes active, one management invocation/attempt, deadline at most 300 s. Reuse existing context,
contract, adapter and checks; no new router, scheduler, memory store or system-wide/second-AI audit.

Suggested request: «Хочу давать обычные задачи голосом с iPhone и видеть в пульте понятный план и результат.
Используй уже готовые части системы». Give the model current, small excerpts of the actual intake,
dispatcher, task-prep and status, so it cannot treat already implemented work as absent. Check whether its
plan respects these facts, distinguishes unknowns, keeps owner authority and proposes a useful next step.
Preserve the answer as a draft; do not execute it or create/update a real tracker card.

Use the intended existing official Claude Code profile, no account or payment changes, no API override or
fallback. Before the real call establish included-subscription conditions for that same profile, including
paid continuation OFF. Prior web observation on an unbound account is not sufficient evidence. If this
cannot be established, complete the code/checks and name that specific missing fact; do not loop or claim
real-model qualification. A successful call establishes only the observed scenario, not general autonomy.

Run required checks and one full CI on the finished candidate; compare to `5499ceca4` / CI 40216933079.
Read the existing runs rather than launching duplicate audits. Current model assignments remain null.
No production/main/merge/service changes, tracker apply, stash/deletion, local inference, weight copying,
financial/risk changes or new paid services. ADR-762 OFF; weekly_backup ON; real capital $0.
