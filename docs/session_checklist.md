# Session Checklist (session-start)

> **Task:** CCW-004. Run this at the **start of every** SPA Yield Lab / AI Investment OS session,
> before doing anything else. Keeps every session inside the safe-change process (`docs/28` §6).
> **Related:** `docs/28` (master instructions), `docs/06` (invariants), `docs/29` (backlog),
> `PROGRESS.md`, `docs/templates/task_plan.md` (CCW-001), `docs/templates/work_report.md` (CCW-002).

## 1. Read first (before touching anything)

- [ ] `docs/28_claude_code_master_instructions.md` — the workflow + STOP-ask rule
- [ ] `docs/06_spa_core_invariants.md` — the non-negotiable invariants
- [ ] `PROGRESS.md` — current state / what's done / what's next
- [ ] (recommended) `docs/02_current_architecture_audit.md` and the durable charter
      `prompts/claude_code/yield_lab_master.md`

## 2. Pick exactly ONE backlog task

- [ ] Choose **one** task from `docs/29` (one task per iteration — `docs/28` §9).
- [ ] Prefer: higher priority, satisfied deps, research-layer-only, MVP over later.
- [ ] Skip anything **owner-gated** until the owner answers.
- [ ] Confirm it is **research-layer only** (docs / schemas / templates / tests / non-runtime modules
      in NEW dirs). Draft a task plan (`docs/templates/task_plan.md`).

## 3. STOP-ask gate (before proceeding)

STOP and ask the owner **before** touching any of these — they are **not** research-layer:

- [ ] runtime execution / the daily cycle / any run against **live `data/`**
- [ ] the deterministic **RiskPolicy** or the two-tier **kill-switch**
- [ ] the **public dashboard** / cockpit / site / **deployment** (`landing/`, `deploy-landing.yml`)
- [ ] security-sensitive behavior, **private keys / signing / fund movement**

If the task drifts into any of the above → **STOP and ask** (`docs/28` §13). Otherwise proceed.

## 4. Do the work (safe-change discipline)

- [ ] Smallest change; no big-bang rewrite; no hidden behavior; no architecture drift.
- [ ] Any code change ⇒ tests (stdlib, no network, no live-`data/` mutation — use sandbox fixtures).
- [ ] Behavior change ⇒ update the doc that describes it, same iteration.
- [ ] Invent no numbers (floor / APY / TVL / capacity) — unknown = "requires verification".
- [ ] Run the security pre-commit checklist (`docs/security_review.md`) before committing.

## 5. Report

- [ ] Write a work report (`docs/templates/work_report.md`) with the invariant re-confirm block.
- [ ] **Do not commit or push unless the owner asks.**
