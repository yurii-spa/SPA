# 45 — Builder OS Workflow (one task per iteration)

> **This doc resolves the `docs/45` reference in the root `CLAUDE.md`** ("Workflow (Builder OS,
> `docs/45`)"). It is the operating loop every Claude Code session follows when building the SPA
> Yield Lab / AI Investment OS research layer. It is the *workflow*; the agents that support it are in
> [`docs/09_builder_os_architecture.md`](09_builder_os_architecture.md); the full rulebook is
> [`docs/28_claude_code_master_instructions.md`](28_claude_code_master_instructions.md).
>
> **Note on numbering.** The index [`docs/00_index.md`](00_index.md) and backlog task **COMPLIANCE-001**
> also reserve the `45` number for a compliance-surface map (`45_compliance_map.md`). This file
> (`45_builder_os_workflow.md`) is the Builder OS workflow the root `CLAUDE.md` points at; the two are
> distinct files that share the `45` prefix. If the compliance map is later written, keep it under its
> own `45_compliance_map.md` name to avoid clobbering this one.

---

## 1. The loop (this is the whole thing)

```
1. READ        docs/00_index.md → docs/06 (invariants) → docs/28 (master instructions)
                 → the relevant architecture doc(s) → docs/29 (backlog)
2. PICK        exactly ONE task from docs/29 (highest priority whose deps are satisfied,
                 research-layer only; skip owner-gated tasks until the owner answers)
3. PLAN        copy docs/templates/task_plan.md → scope, inputs, outputs, acceptance
4. SCOPE-GATE  is this research-layer only? if it touches runtime execution / RiskPolicy /
                 kill-switch / dashboard / security-sensitive behaviour / keys / signing /
                 funds / deploy → STOP and ask the owner (do NOT proceed)
5. DO          modify ONLY the files the task requires; smallest change; no drift, no hidden work
6. TEST        any code change → deterministic, no-network, sandbox-fixture tests; suite green
7. DOCUMENT    any behaviour change → update the doc that describes it, same iteration
8. REPORT      copy docs/templates/work_report.md → files, what changed, tests, invariant re-confirm
9. STOP        one task done. Do NOT commit or push unless the owner asks. Next iteration = new loop.
```

No big-bang rewrites. One task per iteration. No architecture drift. No hidden behaviour.

---

## 2. Step detail

**Step 1 — Read (always, in order).** [`docs/00_index.md`](00_index.md) for the map,
[`docs/06_spa_core_invariants.md`](06_spa_core_invariants.md) for what must never break,
[`docs/28_claude_code_master_instructions.md`](28_claude_code_master_instructions.md) for the rules,
then the architecture doc that owns the area you are touching (e.g.
[`docs/07`](07_yield_lab_architecture.md) for lifecycle, [`docs/08`](08_ai_investment_os_architecture.md)
for Investment agents, [`docs/09`](09_builder_os_architecture.md) for Builder agents,
[`docs/14`](14_risk_scoring_v2.md) for Risk Scoring), then
[`docs/29_backlog.md`](29_backlog.md). Also read [`docs/02`](02_current_architecture_audit.md) so you
do not duplicate the substantial research layer that already exists.

**Step 2 — Pick one task.** From `docs/29`, choose the highest-priority task whose dependencies are
satisfied and that is research-layer only. Prefer P1 over P2 over P3, MVP over later. **Skip any task
marked owner-gated** until the owner has answered. One task — not two, not a theme.

**Step 3 — Plan.** Copy [`docs/templates/task_plan.md`](templates/task_plan.md) (CCW-001) and fill it
in: the one-line goal, inputs to read, files to create/extend (new research dirs only for data/code),
docs to update, acceptance criteria (mirror the backlog `acc:` line), and the exact self-contained CC
prompt for the task.

**Step 4 — Scope gate (the load-bearing step).** Confirm the task is docs / schemas / templates /
tests / non-runtime research modules in NEW directories. If it would touch **runtime execution, the
deterministic RiskPolicy, the two-tier kill-switch, the public dashboard / cockpit / DFB board /
site, security-sensitive behaviour, private keys / signing, fund movement, or deployment → STOP and
ask the owner** (`docs/28` §13, `docs/06` F20). Do not "just prototype" across that line.

**Step 5 — Do.** Make the smallest change that satisfies exactly the one task. Touch only the files
the task requires. New research data and code live in **NEW** directories — never in runtime
`data/*.json`, never in existing `data/*/` subdirs, never in the live paper track. stdlib-only for any
runtime-adjacent code; atomic writes (`atomic_save`) on any state file.

**Step 6 — Test.** Any code change requires tests under `spa_core/tests/` or `tests/`
(`unittest`/`pytest`), deterministic, no network, using sandbox fixtures. Keep the suite green
(`python3 -m pytest spa_core/tests/ -q`). A test that mutates the live track or runtime `data/` is a
defect — never do it (standing track-corruption hazard).

**Step 7 — Document.** A behaviour change gets its doc updated in the *same* iteration (docs-first,
`docs/28` §7). New capability → write/extend its `docs/NN_*.md`. ADRs are namespaced **ADR-YL-###**.

**Step 8 — Report.** Copy [`docs/templates/work_report.md`](templates/work_report.md) (CCW-002): task
id + title, files created/edited (absolute paths), what changed and why, tests added/run + result,
acceptance criteria met, and the **invariant re-confirm block**, plus follow-ups / owner-gated items.

**Step 9 — Stop.** The iteration is done at one task. **Do not commit or push unless the owner asks**
(`docs/28` §12). The next task is a fresh pass through the loop.

---

## 3. Session checklist (run at the top and bottom of every session)

> There is no separate `session_checklist.md` template — this section is the canonical session
> checklist. Copy it into the work report if useful.

**At the start (before touching anything):**
- [ ] Read `docs/00` → `docs/06` → `docs/28` → relevant arch doc → `docs/29` (Step 1).
- [ ] Read `docs/02` so I do not duplicate the existing research layer.
- [ ] Picked exactly **one** task; it is research-layer only and not owner-gated (Steps 2, 4).
- [ ] Filled a `task_plan.md` with acceptance criteria and the scope gate answered.

**Before writing any file:**
- [ ] The change touches only the files this one task requires; new data/code in NEW dirs only.
- [ ] It does **not** cross the STOP-ask line (runtime / RiskPolicy / kill / dashboard / security /
      keys / funds / deploy). If it does → stopped and asked the owner.

**Before finishing:**
- [ ] Tests added for any code change; suite green; no network; no live-`data/` mutation.
- [ ] Docs updated for any behaviour change (same iteration).
- [ ] `work_report.md` filled, including the invariant re-confirm block.
- [ ] **Invariants re-confirmed:** no execution-path change; no keys/signing/funds; RiskPolicy `v1.0`
      intact; Risk Scoring v2 advisory only; BTC/ETH modules decision-support only; no APY claimed
      verified without an evidence level (`docs/06`, `docs/28` §12).
- [ ] Did **not** commit or push (unless the owner explicitly asked).

---

## 4. Templates this workflow uses

| Template | Task id | When |
|---|---|---|
| [`docs/templates/task_plan.md`](templates/task_plan.md) | CCW-001 | Step 3 — plan one task before doing it |
| [`docs/templates/work_report.md`](templates/work_report.md) | CCW-002 | Step 8 — report the completed task |
| §3 above (inline session checklist) | — | Start and end of every session |

---

**Cross-reference:** [`docs/28`](28_claude_code_master_instructions.md) (master instructions — the
authoritative rulebook this loop enacts), [`docs/09`](09_builder_os_architecture.md) (the Builder
agents that support this loop), [`docs/06`](06_spa_core_invariants.md) (invariants),
[`docs/29`](29_backlog.md) (backlog — the task source), [`docs/02`](02_current_architecture_audit.md)
(what already exists), [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md)
(charter §39). Root [`CLAUDE.md`](../CLAUDE.md) points at this doc as the Builder OS workflow.
