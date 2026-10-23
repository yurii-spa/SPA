# ADR-OWN-2026-10-23 · Model-independent Studio OS and bounded verification

- Date: 2026-10-23 (Europe/Madrid).
- Decision owner: Yurii Kulieshov.
- Recorded by: Architecture Review Board.
- Status: owner directive accepted for priority and design; implementation and production activation are not claimed.
- Source: owner's instruction of 2026-10-23: avoid repeated 6–12 hour whole-system audits; make interchangeable models at multiple levels, including the architect, an important roadmap priority.
- Related: ADR-423 (deferred local LLM/router work), ADR-527 (memory), ADR-610 (architect continuity), ADR-763 / ROADMAP item 17.

## Decision and priority

**STUDIO-OS-MODELS-01 is P1 and the next bounded Studio OS macro after the current stage-8 checkpoint.**
It is not conditional on closing every item of technical debt. Mandatory release gates and the explicit remaining risks still apply to the actions they protect. Product work may proceed within existing safe boundaries.

The Architecture Review Board/architect and the implementation worker are roles, not vendor names. ChatGPT and Claude Code are the current participants. A compatible cloud or local model can fulfil an approved role after that role's capability and quality checks; the model never becomes the owner or acquires new permissions by being selected.

This directive reopens the design/roadmap deferral in ADR-423 points 1–3. It does not activate a new production provider or resume resource-heavy local-model experiments. ADR-423's prohibition on automatic paid API fallback, the hardware-purchase deferral and resource safeguards remain. No provider, service, subscription or hardware purchase is authorized by this priority change.

## Starting evidence and scope limit

- docs/MEMORY_ARCHITECTURE.md already treats AI sessions (Claude, Codex, local models) as replaceable workers and files/Git as memory.
- docs/continuity/ARCHITECT_CONTEXT.md and BOOTSTRAP.md already provide a continuity path; reuse it.
- ADR-423 deferred a production router and kept Claude Subscription as the only production AI provider as of 2026-09-19. Its measurements are historical, not a current host inventory.
- Selected current source call sites remain provider-specific: spa_core/studio_os/memory/answer.py calls the Claude CLI; spa_core/dev_agents/architect.py uses an Anthropic client. These observations do not establish which callers are active in production.
- No complete model router, working local adapter, or provider-independent architect execution is accepted on this evidence.

Inspect only the existing model-call seams, role declarations and continuity interfaces needed for the first slice. Do not repeat a system-wide audit or replace existing components without inspecting them.

## Architecture and first increments

1. **Portable architect and reviewer context.** Reuse the existing memory/continuity assembler for a versioned role package: task, owner intent, relevant decisions, allowed actions, exact code revision, evidence references and open risks. A fresh architect can recover the state without chat history. Unknown/stale inputs remain explicit.
2. **One provider contract and role configuration.** Keep stable role identifiers separate from provider/model identifiers. Declare required capabilities, allowed tools, input/output format, context limit, deadline, retry limit and resource budget. Unsupported combinations refuse; no silent escalation or fallback.
3. **Small interchangeable execution slice.** Wrap the existing approved Claude subscription path; prepare an independently selectable second adapter using fixtures before any production activation. Local-provider qualification is a separately bounded canary on a safe task after resources and limits are specified. Do not benchmark every model.
4. **Observed resource use.** Attribute model calls, elapsed time, retries and failures to task/role/provider. Record tokens or quota only when actually exposed; missing accounting is UNKNOWN. Do not infer subscription charges from token counts.

The first reviewable result is one safe task recovered by a fresh architect and processed through the same role/provider contract without a provider-specific workflow rewrite. New provider activation remains a separate delivery step. Subsequent slices are selected from actual gaps, not a speculative framework backlog.

## Acceptance

- Owner intent, decisions and task state survive replacement of an AI session; existing memory is reused.
- Architect/ARB role, implementation role and owner authority remain distinct.
- Provider choice changes through explicit configuration at the existing execution seam; permissions do not change.
- A fixture-backed second adapter exercises the same input/output/refusal contract; an unavailable or unqualified provider cannot silently receive the role.
- A real second-provider canary, when authorized and available, reports quality, time and resource use for the stated task. Fixture success is not production readiness.
- Timeouts, cancellation, malformed output and quota exhaustion preserve task state; retries are bounded.
- Credentials are not copied into context packs or reports.
- No LLM is introduced into risk, execution, monitoring or kill components; Investment Engine and Product Studio stay separate.
- No autonomous real-capital movement, risk-limit/rate change, paid API fallback or owner approval is enabled.

## Bounded verification policy

This is an instruction to reduce duplicate work, not permission to remove mandatory checks or introduce the previously unapproved two-tier test scheme.

- Each package states the concrete change, affected components, acceptance checks and a time/resource estimate before implementation.
- Reuse previous evidence only with explicit SHA, environment, scope and results. Do not transfer a green claim to an untested revision.
- During implementation, run the checks needed by the change and its known failure modes. Batch changes into one stable candidate for the required full CI; repeat only after relevant changes, failures or an explicit acceptance requirement.
- Do not run another whole-system or second independent AI audit by default. A new broad review needs a concrete unresolved risk and a scope.
- Read results from already running CI/census jobs; do not start replacements merely to wait or collect another report.
- Separate model work, test runtime and waiting in accounting. Wait through a bounded monitor/notification rather than repeated LLM polling; final evidence ingestion must still occur.
- On exceeding the stated budget, checkpoint the work and name the reason and remaining steps. Do not expand scope silently.
- New findings are triaged and recorded; a confirmed critical finding blocks the affected action. Unrelated findings do not automatically expand the current package.
- Planning-only changes do not justify extra verification beyond existing repository requirements. Do not send a separate planning-only push that unnecessarily triggers the expensive census; batch delivery appropriately.

## Alternatives and consequences

- Keep one vendor permanently: rejected because it binds the company to one worker, account and model.
- Build a universal agent platform or migrate every caller at once: rejected because it creates another long infrastructure project.
- Immediately enable local models or paid fallback: not selected; quality, resource and cost restrictions still apply.
- First exhaust all technical debt: rejected as a prerequisite for this priority; safety gates remain action-specific.

Consequences: a small stable provider seam, portable architect context and honest cost/quality evidence become explicit deliverables. Different roles may use different qualified providers. Portability does not promise that every model can perform every task, that local inference is automatically cheaper, or that a provider has access to another product's private chat history.
