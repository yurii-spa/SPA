# 09 — Builder OS Architecture (9 Builder Agents)

> **This is the deep per-agent specification for the Builder OS** — the dev-support layer that helps
> future Claude Code sessions build the Yield Lab / AI Investment OS *safely and one task at a time*.
> [`docs/10_agent_architecture.md`](10_agent_architecture.md) is the combined *index*; this doc is the
> *detail* for the 9 Builder agents. Its companion is
> [`docs/08_ai_investment_os_architecture.md`](08_ai_investment_os_architecture.md) (the 16 Investment
> agents). The **workflow** these agents operate inside is
> [`docs/45_builder_os_workflow.md`](45_builder_os_workflow.md).
>
> **State of the world (honest).** No autonomous Builder agents run in production. This is
> **prompts + schemas + architecture only**, default autonomy **L0/L1**. Builder agents produce
> plans, reviews, tests, and doc/backlog updates for a human-driven Claude Code session — they do not
> deploy, do not touch runtime execution, and do not change the RiskPolicy. They **build on existing**
> `spa_core/dev_agents/` (`architect.py`, `tester.py`) and `spa_core/agent_runtime/`; per-agent prompt
> templates live in [`prompts/agents/`](../prompts/agents/).

---

## 1. Universal contract (applies to every one of the 9)

Read [`docs/28`](28_claude_code_master_instructions.md) (the Claude Code master instructions) and
[`docs/06`](06_spa_core_invariants.md) (invariants) before doing any Builder work. Every Builder
agent inherits:

- **Autonomy L0/L1.** Output is a plan, review, test, doc edit, or backlog change for a human session
  — never a deploy, a runtime edit, or an execution change.
- **Universal FORBIDDEN:** change runtime execution / RiskPolicy / the kill-switch; deploy the
  dashboard or production; write execution-owned state or mutate the live paper track
  (`equity_curve_daily.json` etc.); import `spa_core/execution/` from research code; introduce keys /
  signing / funds; hardcode secrets; big-bang rewrite; hide behaviour.
- **STOP-and-ask boundary.** The moment a task would touch runtime execution, the deterministic
  RiskPolicy, the public dashboard/cockpit/board, security-sensitive behaviour, keys/signing, funds,
  or deployment → **STOP and ask the owner** (`docs/28` §13). Research-layer docs / schemas /
  templates / tests / non-runtime modules in NEW dirs may proceed.
- **One task per iteration; tests for code; docs for behaviour.** No architecture drift; the smallest
  change that satisfies exactly one backlog task (`docs/45`).
- **Error mode = flag, don't guess.** Missing dependency, ambiguous scope, or an invariant conflict →
  flag and stop, never improvise.

---

## 2. The 9 Builder agents

### 2.1 Documentation Agent
Keeps the docs current with behaviour. When code or an ADR changes, it updates the doc that describes
it *in the same iteration* (docs-first discipline, `docs/28` §7). It edits docs only — it never
changes runtime code to make a doc "true."

| Field | Value |
|---|---|
| Role | Keep docs in sync with behaviour |
| Inputs | Code diffs, existing docs, ADRs |
| Outputs | Doc create/extend edits |
| Downstream | All future sessions |
| Allowed | Edit docs / ADRs |
| FORBIDDEN | Change runtime code; invent facts to fit a doc |
| Validation / error | Doc-vs-behaviour drift → flag |
| Human approval | Review |
| Frequency | On change |
| Prompt / code | [`prompts/agents/documentation_agent.md`](../prompts/agents/documentation_agent.md) |

### 2.2 Architecture Agent
Reviews proposed designs against the invariants (`docs/06`) before code is written. It can recommend
and can **block** a design that violates an invariant; it cannot approve an invariant *change* — that
is an ADR + owner decision.

| Field | Value |
|---|---|
| Role | Review designs against invariants |
| Inputs | Design proposals, `docs/06`, existing architecture docs |
| Outputs | Architecture review (+ ADR-YL draft if needed) |
| Downstream | Owner, Code Planning |
| Allowed | Review, recommend, block on invariant conflict |
| FORBIDDEN | Approve an invariant change (owner + ADR only) |
| Validation / error | Invariant conflict → block and escalate |
| Human approval | Required for any invariant-adjacent design |
| Frequency | On proposal |
| Prompt / code | Prompt *pending*; builds on `spa_core/dev_agents/architect.py` |

### 2.3 Code Planning Agent
Turns a single backlog task (`docs/29`) into a **stepwise plan and a self-contained Claude Code
prompt** (via [`docs/templates/task_plan.md`](templates/task_plan.md)). It plans; it does not
implement runtime or execution code.

| Field | Value |
|---|---|
| Role | Turn one backlog task into a stepwise plan + CC prompt |
| Inputs | `docs/29`, relevant arch docs, code |
| Outputs | Task plan (`docs/templates/task_plan.md`) + exact CC prompt |
| Downstream | The session that runs the task |
| Allowed | Plan |
| FORBIDDEN | Implement runtime / execution code |
| Validation / error | Missing dependency → flag, do not plan around it |
| Human approval | — (plan is inert until a session runs it) |
| Frequency | Per task |
| Prompt / code | [`prompts/agents/code_planning_agent.md`](../prompts/agents/code_planning_agent.md) |

### 2.4 Backlog Agent
Maintains and prioritises `docs/29`. It adds tasks, records completions, and orders by
priority/dependency — but it never silently re-prioritises an owner-gated item.

| Field | Value |
|---|---|
| Role | Maintain / prioritise the backlog |
| Inputs | Docs, session findings, dependencies |
| Outputs | Backlog updates (`docs/29`) |
| Downstream | All sessions |
| Allowed | Edit backlog |
| FORBIDDEN | Silently re-prioritise owner-gated tasks |
| Validation / error | Dependency cycle → flag |
| Human approval | Review |
| Frequency | Weekly / on new findings |
| Prompt / code | Prompt *pending* |

### 2.5 QA Agent
Adds tests and keeps the suite green. Tests are deterministic, no-network, and use sandbox fixtures —
they must **never** mutate the live paper track or runtime `data/` (`docs/28` §8, and the standing
track-corruption hazard).

| Field | Value |
|---|---|
| Role | Add tests; keep the suite green |
| Inputs | Code, existing tests |
| Outputs | Test additions + run results |
| Downstream | Release Manager, all sessions |
| Allowed | Add tests, run suite |
| FORBIDDEN | Mutate the live track or runtime `data/`; add network calls |
| Validation / error | A test that writes live `data/` → block |
| Human approval | — |
| Frequency | Per code change |
| Prompt / code | [`prompts/agents/qa_agent.md`](../prompts/agents/qa_agent.md); builds on `spa_core/dev_agents/tester.py` |

### 2.6 Security Review Agent
Scans diffs and config for secrets, keys, execution-path bypass, and the known failure patterns (PAT
leaks; direct-primitive execution bypass). A secret in a file or an unresolved finding is a
hard-block, not a warning.

| Field | Value |
|---|---|
| Role | Scan for secrets / keys / execution bypass |
| Inputs | Diffs, config, workflow files |
| Outputs | Security review |
| Downstream | Owner, Release Manager |
| Allowed | Review, hard-block |
| FORBIDDEN | Ship on an unresolved finding |
| Validation / error | Secret in a file / exec bypass → hard-block |
| Human approval | Required |
| Frequency | Per change |
| Prompt / code | Prompt *pending*; relates to `spa-lint.yml` (LLM-forbidden lint), proof-gate |

### 2.7 Data Quality Agent
Gates the *research inputs* the Investment OS consumes — feed freshness, source validity, unit
consistency. Stale or invalid data yields UNKNOWN, never a silently-trusted number (feeds the
Investment agents' abstain-on-unknown contract).

| Field | Value |
|---|---|
| Role | Gate research-input data quality |
| Inputs | Feeds, `data_trust/` / `data_pipeline/` outputs |
| Outputs | Data-quality (DQ) report |
| Downstream | Investment OS agents (`docs/08`) |
| Allowed | Research / gate |
| FORBIDDEN | Trust stale or invalid data |
| Validation / error | Stale / invalid → UNKNOWN |
| Human approval | Advisory |
| Frequency | Continuous |
| Prompt / code | Prompt *pending*; relates to `data_trust/`, `docs/40` |

### 2.8 Release Manager Agent
Coordinates safe change — assembles a release checklist from diffs + CI state — and is the agent most
tightly bound by STOP-and-ask: any deploy of the dashboard or production is owner-gated. It plans a
release; it does not perform one.

| Field | Value |
|---|---|
| Role | Coordinate safe change; assemble release checklist |
| Inputs | Diffs, CI run conclusions |
| Outputs | Release checklist |
| Downstream | Owner |
| Allowed | Plan |
| FORBIDDEN | Deploy the dashboard or production |
| Validation / error | Any deploy scope → **STOP-ask** the owner |
| Human approval | **Required** |
| Frequency | Per release |
| Prompt / code | Prompt *pending* |

### 2.9 Technical Debt Agent
Tracks and prioritises debt found during sessions and audits, feeding it back to the Backlog agent as
scoped tasks. It never turns a debt item into a big-bang refactor — debt is split into one-task-per-
iteration units.

| Field | Value |
|---|---|
| Role | Track / prioritise technical debt |
| Inputs | Code, audits, session findings |
| Outputs | Debt register |
| Downstream | Backlog agent |
| Allowed | Research / register |
| FORBIDDEN | Big-bang refactor |
| Validation / error | Rewrite temptation → split into scoped tasks |
| Human approval | — |
| Frequency | Weekly |
| Prompt / code | Prompt *pending* |

---

## 3. How the Builder OS supports a Claude Code session

The Builder agents map one-to-one onto the phases of the Builder OS workflow
([`docs/45`](45_builder_os_workflow.md)):

```
Backlog agent        → keeps docs/29 prioritised            ─┐
Code Planning agent  → task plan + CC prompt (one task)      │  BEFORE the session
Architecture agent   → invariant review of the design        │
                                                             ─┘
        ▼
   Claude Code session runs ONE task (modify only required files)
        ▼
QA agent             → tests for any code change             ─┐
Documentation agent  → docs updated with behaviour change     │  DURING / AFTER
Security Review agent → secret / key / exec-bypass scan       │
Data Quality agent   → gates research inputs (ongoing)        │
Release Manager      → release checklist (owner-gated deploy) │
Technical Debt agent → registers debt found → Backlog         ─┘
```

A session never skips the STOP-and-ask boundary: if the single task drifts toward runtime execution,
RiskPolicy, the dashboard, security-sensitive behaviour, keys/signing, funds, or deployment, the
session stops and asks the owner (`docs/28` §13). The session closes with the work report
([`docs/templates/work_report.md`](templates/work_report.md)) and its invariant re-confirm block.

---

## 4. Existing code these agents build on (do not duplicate)

- `spa_core/dev_agents/` — `architect.py` (Architecture agent engine), `tester.py` (QA agent engine).
- `spa_core/agent_runtime/` — `runtime.py`, `budget.py`, `mandate.py` (+ `mandates/`) — runtime,
  budget, and mandate constraints shared with the Investment OS.
- CI surface — `spa-lint.yml` (LLM-forbidden lint), proof-gate, test workflows — the Security Review
  and QA agents lean on these rather than reinventing checks.
- Templates the workflow uses: [`docs/templates/task_plan.md`](templates/task_plan.md) (CCW-001),
  [`docs/templates/work_report.md`](templates/work_report.md) (CCW-002).
- Existing Builder prompt templates in [`prompts/agents/`](../prompts/agents/):
  `documentation_agent`, `code_planning_agent`, `qa_agent`. **Pending** (no prompt file yet):
  Architecture, Backlog, Security Review, Data Quality, Release Manager, Technical Debt.

---

**Cross-reference:** [`docs/10`](10_agent_architecture.md) (index),
[`docs/08`](08_ai_investment_os_architecture.md) (Investment OS),
[`docs/45`](45_builder_os_workflow.md) (Builder OS workflow),
[`docs/28`](28_claude_code_master_instructions.md) (CC master instructions),
[`docs/06`](06_spa_core_invariants.md) (invariants), [`docs/29`](29_backlog.md) (backlog),
[`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md) (charter §39).
