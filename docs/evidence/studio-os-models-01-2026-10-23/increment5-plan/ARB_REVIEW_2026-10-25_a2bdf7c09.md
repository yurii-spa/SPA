# ARB review — increment 5 preparation, 2026-10-25

- Decision owner: ARB (ChatGPT); product owner: Yurii Kulieshov.
- Reviewed candidate: `a2bdf7c09895f3e670462a190121e1652ca5cddb`.
- Observed HEAD: `adf195aa9eb44bdc2381c3f2f7afc6c30d02ff81`; only documentation above the candidate.
- Input: Claude report `Вставленный текст(20261025-111149).txt`, actual changed code and independent checks.
- Decision: the package advances preparation, but final acceptance and a real model probe remain pending.
  Next implementation scope is limited to result provenance/final verdict and incomplete RSS measurements.
  This decision does not authorize inference, copying real weights, production delivery or provider activation.

## Confirmed evidence

- Owner's Claude Pro management requirements are committed in `ba577d3bb` (ROADMAP and ADR-OWN); this does
  not prove an actual Pro-profile connection or billing safeguards.
- GitHub CI `40178318027` was independently read; the downloaded report artifact SHA-256 matched GitHub's
  digest. Report SHA matches the reviewed candidate: 135805 population, 135084 passed, 2 failed, 719 skipped,
  0 errors, 0 not obtained, 0 collection errors, 12/12 shards complete. Failure identities are the same two
  known office/producer-tick tests. No new failing identities relative to the previous reviewed candidate;
  this is not a green CI or a §49 NO_REGRESSION decision.
- ARB ran the contract, memory-answer integration and probe target tests with process-dependent probe scenes
  deselected: 83 passed, 12 deselected in 0.63 s. Local process scenes were not independently revalidated.
- Previous malformed-answer controls and false-success-on-unresolved-ownership cases are covered and pass.
  Diff whitespace check passed; working tree was clean before this review file was added.
- No real Ollama server, model, weight copying, LLM call or production mutation was performed by ARB.

## R1 — old child result can become a successful new run (blocks final acceptance)

`probe.launch` reuses `out_dir/probe_record.json`, reads it after the helper exits, and replaces its `run_id`
with the current identifier. The child record has no checked binding to this launch. Helper return codes
other than 124/125 are not required to be zero before success.

Independent reproduction, entirely with temporary files and mocked helper/sweep (no processes or signals):

1. Put a previous result in `probe_record.json`: status ok, grade PASS, server_stopped true, old run_id.
2. Let the helper return without writing a new record; let the final sweep report closed true.
3. For helper return codes 0, 1, 3 and -15, launch reports status ok, verdict.success true, CLI exit 0 and
   relabels the old result with the new run_id.

A missing context file before the child's record is created is one concrete failure path that can leave
an earlier record behind. This review simulated its terminal conditions; it did not run a real process.

Required outcome: only a result produced for the current launch can be accepted; all nonzero helper codes
prevent success; absent/mismatching provenance prevents success even with helper rc 0. Preserve prior
evidence rather than deleting it. The final success predicate must explicitly require ownership_closed
true; the current predicate also accepts an otherwise passing record when this field is absent. A child's
intermediate outcome must not be presented as the final launch verdict.

## R2 — absent process data becomes 0 MB (blocks resource-guard acceptance)

`rss_mb([424242], ps_out='')` and the same call with `ps_out='parse failed'` both return 0.0. The PID here is
synthetic; no process with this PID was inspected or signalled. Rows absent for requested processes are
silently replaced by zero, so failure to obtain a usable process measurement can pass as low consumption.

Required outcome: empty/unparseable process data and an unmeasured still-required process produce a
measurement failure and stop the probe. A confirmed process exit may be treated separately, but absence
from one table alone is not a successful zero measurement. Preserve detached-runner accounting and avoid
counting or signalling unrelated processes. Test the final failed verdict as well as the parser exception.

## Rationale, alternatives and consequences

- Selected: a bounded correction of these two concrete defects, retaining the existing architecture,
  grader, timeout helper and isolation design. Expected active-work budget: 45–60 minutes, with CI wait
  reported separately; no speculative system-wide audit or repeated mutation campaign.
- Rejected: accept the launcher now and rely on always using a fresh output directory. It leaves a false
  success path in the canonical command and does not fix missing resource measurements.
- Rejected: rebuild the launcher/provider framework or reopen unrelated backlog items. No evidence here
  justifies that scope.
- Consequence: complete the focused tests and required checks, then one full CI on the finished candidate.
  Do not rerun the old candidate or declare success from target tests alone. Real probe remains subject to
  the existing separate owner decision; existing services, model assignments and accounts stay unchanged.

## Acceptance criteria for the bounded follow-up

1. Old, missing or mismatched child records cannot be accepted or relabelled as current results, even on rc 0.
2. Every nonzero helper code prevents final success; current valid record + rc 0 + confirmed cleanup can pass.
3. Missing/null/false ownership_closed prevents a final successful verdict; record and CLI agree.
4. Failed RSS measurement cannot become 0 MB and cannot yield a successful probe; valid measurement still works.
5. Prior evidence remains intact; normal owned-process cleanup and unrelated-process preservation remain covered.
6. Report exact tested SHA, target checks and completed full CI, retaining the known §49 limitations.

## Follow-up acceptance — 2026-10-25, candidate 5a0d497f0

Decision owner: ARB (ChatGPT); real model activation remains a separate decision of Yurii Kulieshov.
This section resolves the earlier R1/R2 review; the original findings above remain historical evidence.

**Decision: ACCEPTED as preparation for one bounded local-provider probe**, on tested candidate
`5a0d497f0ce7c9f7fe8740cf8e982ff1eb66ec0e` (code commit `a490f2979`). Observed HEAD before this annotation:
`95ea39f1795ef4f48f86a9642f65937b4314b584`; changes above the tested candidate are documentation only.
This acceptance is not a real provider qualification, production delivery, green CI or §49 NO_REGRESSION.

Evidence independently checked by ARB:

- Inspected the actual R1/R2 code and test diff. Each launch creates a fresh `runs/<run_id>/` directory,
  retains the child's record, checks its run id, and requires helper rc 0 and explicit confirmed ownership
  for final success. Intermediate `child_outcome` is explicitly non-final.
- Repeated 12 controlled provenance/return-code cases without processes: missing, mismatching and current
  records, each with rc 0/1/3/-15. Only a current passing record with rc 0 succeeded; CLI and record agreed;
  old records remained byte-for-byte intact.
- Independently verified empty/malformed/missing RSS data refuses for present or unknown synthetic process
  state; confirmed exit is distinct and valid measurements still sum correctly. No OS query or signal was
  made for the synthetic PID.
- Target checks: 103 passed, 13 process-dependent probe cases deselected locally, 0.76 s. The real Mac
  process behaviour remains an empirical question for the bounded probe; local deselection is not acceptance
  evidence for those process scenes.
- Read GitHub CI `40190831822` and verified the downloaded report artifact's SHA-256 against GitHub's digest.
  Report SHA matches the tested candidate. 135826 population; 135105 passed; 2 failed; 719 skipped; 0 errors,
  0 missing, 0 collection errors; 12/12 shards complete. The failing identities are the same two known §49
  producer-tick tests, with no new failing identities relative to the previous reviewed candidate.
- Diff whitespace check passed. No inference, Ollama server launch, real model copying, production mutation,
  account switch, financial change or new CI dispatch was performed by ARB.

Rationale: the two concrete acceptance blockers are closed with evidence, and the focused change introduces
no observed new CI failures. Another general audit or another run of this same full CI is not justified.
Alternative rejected: declare the local model qualified from fake-server tests. Real transport, process
visibility, memory use and answer quality still require observation.

### Concrete next step for the owner's decision (NOT yet authorized or executed)

One `qwen3.5:4b` probe, using the current `prepare-store` then `launch --models-dir` commands in PLAN.md:

- Copy only the selected already-installed model into a new private store (approximately 3.4 GB according
  to the earlier inventory); no download, shared-store overwrite or deletion. If preparation fails, stop
  before launching; an existing destination is not permission to reuse it implicitly.
- Use the fixed `probe_context.md` and its four factual questions; it is a historical test fixture, not a
  claim that its recorded HEAD is today's project HEAD.
- One request, no tools, no retry; helper deadline 180 s, with bounded cleanup afterward. Private loopback
  port 11535, private store, current resource guards (free memory >=40%, pressure <=1, swap growth <=1 GB,
  owned-server/runner RSS <=6 GB). Any refused/unmeasured precondition ends this attempt.
- Keep the existing service, model-role assignments, production, tracker, financial rules and account
  settings unchanged. No paid API or automatic fallback. Preserve the evidence and private copy afterward.
- Record answer/grade, final verdict, process closure, timing, usage actually reported, resource samples
  and any observed shared-store changes. No automatic code repair, repeated model attempt or role admission
  follows a failure or an inconclusive answer.
- A passing result supports only this short scenario. Claude Pro management connection and its billing
  safeguards remain a separate open part of MODELS-01.

### Subsequent owner direction — 2026-10-25

Yurii selected testing Claude management now and deferring local models until the new Mac mini. The local
probe proposed above is therefore DEFERRED, not authorized; its preparation acceptance remains valid for
the stated candidate and scope. No real weights are to be copied and no Ollama inference started under the
current package. The updated execution order is recorded in ROADMAP and ADR-OWN-2026-10-23. This neither
authorizes a hardware purchase nor schedules an automatic launch when hardware becomes available.
