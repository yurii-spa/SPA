# Task Plan — <TASK_ID> <title>

> **Task:** CCW-001. **One task per iteration** (`docs/28` §6/§9). Copy this file per task. A task
> plan is research-layer only (docs / schemas / templates / tests / non-runtime modules in NEW dirs).
> If the task would touch runtime execution, RiskPolicy, the public dashboard, security-sensitive
> behavior, keys/signing, funds, or deployment → **STOP and ask the owner** (`docs/28` §13).
> **Related:** `docs/29` (backlog), `docs/28` (workflow), `docs/06` (invariants),
> `docs/templates/work_report.md` (CCW-002).

## 1. Task

- **Task id:** <e.g. PORT-002> · **Title:** <…>
- **Source:** `docs/29` backlog (group: <…>) · **Priority:** <P1/P2/P3> · **Complexity:** <S/M/L>
- **One-line goal:** <what this iteration delivers, nothing more>

## 2. Inputs

- **Read first:** `docs/28`, `docs/06`, `docs/02`, plus: <specific docs/schemas this task depends on>
- **Depends on (backlog deps satisfied?):** <dep task_ids — yes/no> 
- **Reference material / existing modules:** <paths — never invent facts; unknown = "requires verification">

## 3. Outputs

- **Files to create/extend (absolute or repo-relative paths):** <…>
- **New dirs (if any — research data/code goes in NEW dirs only):** <…>
- **Docs to update in the same iteration** (behavior change ⇒ doc update): <…>

## 4. Acceptance criteria

- [ ] <criterion 1 — matches the backlog `acc:` line>
- [ ] Valid Markdown / valid schema / tests green as applicable
- [ ] No invented numbers (floor / APY / TVL / capacity) — unknown = "requires verification"
- [ ] Invariants preserved (`docs/06`): no execution-path change, no keys/signing, RiskPolicy intact,
      Risk Scoring v2 advisory, research-layer only

## 5. Dependencies & scope guard

- **Blocking deps:** <…> · **Blocks:** <…>
- **In scope:** <…> · **Explicitly out of scope:** runtime execution, RiskPolicy, dashboard, deploy
  (STOP-ask if the task drifts into these).

## 6. Claude Code prompt (the exact CC prompt for this task)

```
<paste the single, self-contained prompt a session runs for this task:
 what to read, what to create, constraints — institutional, concise, invent nothing,
 research-layer only, do not commit/push.>
```

## 7. STOP-ask-before-runtime note

> This plan is **inert**. Before running any cycle / backtest / agent against **live `data/`**, or
> before touching runtime execution, RiskPolicy, the kill-switch, the public dashboard, keys/signing,
> funds, or deployment — **STOP and ask the owner** (`docs/28` §13). Use sandbox fixtures for any test
> run; never mutate the live paper track. Do not commit or push unless the owner asks.
