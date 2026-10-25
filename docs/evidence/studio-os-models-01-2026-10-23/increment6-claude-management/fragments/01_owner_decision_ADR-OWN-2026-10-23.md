# Excerpt: docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md lines 1–85 (at aaec91755, unchanged)

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

## Owner clarification — 2026-10-25: Claude Pro for management

- Decision owner: Yurii Kulieshov; recorded by ARB from the owner's request to connect his Claude Pro subscription for management.
- Status: requirement accepted for design; the actual account, plan, billing safeguards and production connection are not verified by this record.
- Reuse the official Claude Code CLI and the existing `claude_subscription_cli` seam for architecture review, planning and preparation of implementation tasks. Support the owner's Pro subscription and compatible Max access; do not require another subscription or an API account. The same provider may serve different roles without changing their permissions. Company memory remains the existing files and Git.
- Authentication stays in the official client. Do not extract or copy OAuth tokens into SDKs, adapters, context packs or reports. Reuse the intended signed-in profile; an explicitly selected `CLAUDE_CONFIG_DIR` may separate accounts when needed. Do not log out, replace credentials or change the active implementer's account automatically. Account/plan facts must be reported from safe status metadata or marked UNKNOWN.
- Stay within included subscription usage. Do not silently use API credentials, cloud billing, paid usage credits or another provider. Detect and refuse a billing mode outside the intended subscription; unknown paid-overage settings must remain UNKNOWN rather than a promise of no charges. Changes to payment settings are the owner's decision.
- Management and implementation share the subscription's limits. A quota refusal preserves the task and reports a pause; do not repeatedly poll with model calls or infer subscription charges from CLI cost estimates.
- Acceptance: an explicitly selected subscription profile can perform a safe management task through the existing contract; unavailable login, quota and unsupported billing mode have clear outcomes; owner authority and all existing safety gates remain unchanged. This does not authorize local inference, a new production provider, paid fallback or service changes.

Rationale: reuse the owner's paid access for management and development while preserving model-independent roles and bounded costs. Alternatives rejected: a separate API dependency for management, exported subscription credentials, and implicit paid continuation. Consequence: management consumes the same quota as development and can pause when that quota is exhausted.

Provider references checked 2026-10-25: [Pro/Max access and shared limits](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [official authentication and profiles](https://code.claude.com/docs/en/authentication), [paid usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

## Owner sequencing directive — 2026-10-25: Claude now, local models after the new Mac mini

- Decision owner: Yurii Kulieshov; recorded by ARB from: «я бы клод тестировал пока мак мини не купил новый».
- Status: accepted for the next bounded management test, within the existing subscription and permissions.
- Next step: use the existing official Claude Code subscription seam and `memory arch-review` for one useful
  management/architecture task. Supply fresh canonical context and check factual accuracy, unknowns,
  priorities, owner authority and the usefulness of its proposed implementation task. Preserve output as a
  proposal for ARB review; do not execute the generated task automatically.
- Reuse the intended authenticated subscription profile; do not switch accounts or represent an observed
  Max profile as a verified Pro connection. Included-usage and no-paid-fallback restrictions above remain.
- Defer real Ollama inference and real weight-copy preparation until the owner's new Mac mini is available.
  Availability of the new hardware is not automatic permission to start: a bounded launch still needs its
  own owner authorization. No hardware purchase or model download is authorized by this directive.
- Keep the accepted local-probe preparation (`5a0d497f0`) and its evidence. Do not delete it, repeat its audit,
  or make local-provider qualification a prerequisite for useful work with Claude.

Rationale: deliver useful management behaviour using the owner's current access while postponing local
compute experiments until the planned hardware change. Alternatives: run Qwen on the current Mac (deferred
by the owner); block all management work until a second provider is qualified (rejected). Consequences:
model-independent architecture remains P1, Claude management is the immediate test, and actual Pro-profile
qualification, billing safeguards and second-provider qualification remain separate evidence questions.

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

