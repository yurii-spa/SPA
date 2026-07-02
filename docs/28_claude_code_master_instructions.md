# 28 — Claude Code Master Instructions (permanent)

> Permanent instruction doc for every future Claude Code session on the SPA Yield Lab / AI
> Investment OS. Read this **and** [`06_spa_core_invariants.md`](06_spa_core_invariants.md) +
> [`02_current_architecture_audit.md`](02_current_architecture_audit.md) before doing anything.
> The durable one-page charter is [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md);
> where this doc and the charter diverge, the charter's *intent* governs.

## 1. Project summary

SPA (earn-defi.com) is a deterministic, paper-tracked stablecoin **yield optimizer** with a
substantial research/risk/refusal layer already built (`strategy_lab/`, `redteam/`, `riskwire/`,
`dfb/`, `compliance/`, `tournament/`). The Yield Lab work **formalizes and unifies** that layer into
one vocabulary (Strategy/Protocol/Stablecoin Cards, a single lifecycle, capital tiers, agents). It
does **not** rebuild it.

## 2. Founder vision

Discover and validate real mechanisms for **≥10% annualized** (target **12–15%**, opportunistic
15–20% only in limited high-risk sleeves) on **stablecoins, BTC, ETH** — with **capital preservation
first**. Do not dilute into a plain 5–8% optimizer; do not chase yield past the risk it compensates.

## 3. SPA Core principles (never violate — see docs/06 for the full list + enforcement points)

- Deterministic **RiskPolicy `v1.0`** is the sole hard execution gate; `approved=False` is final.
- **No LLM** in risk / execution / monitoring / kill paths. Risk Scoring v2 is **advisory only**.
- Two-tier kill-switch (SOFT −5% / HARD −10%) is owner/ADR-gated; do not change without an ADR.
- **No private keys, seeds, signing, or fund movement** anywhere. Execution Support is non-custodial,
  human-in-the-loop only. Never import `spa_core/execution/` from read-only / research code.
- **stdlib-only runtime**; **atomic writes** (`atomic_save`) on state files; paper track + GoLive
  honesty (evidenced ≠ backfill); public proof/refusal chains stay intact.
- Every APY claim carries an **evidence level L0–L6** (`docs/37`) + source + risk category + date.

## 4. Target layered architecture

1. **SPA Core** — deterministic paper-tracked optimizer (trust foundation).
2. **Yield Lab** — closed research layer that searches for / tests / rejects / validates higher-yield
   strategies before any public exposure (`docs/07`).
3. **AI Investment OS** — research/decision-support agents (`docs/10`).
4. **Builder OS** — dev-support agents (docs, backlog, prompts, QA).
5. **Execution Support** — non-custodial, human-in-the-loop; prepares checklists/approvals, never
   signs, never controls funds.

## 5. Hard constraints & security rules

Sourced from `docs/06`. AI/LLM **MUST NOT**: hold keys/seeds, sign, move/withdraw funds, bypass or
weaken RiskPolicy, override hard gates, change allocation without human approval, run autonomous
execution, secretly alter strategy logic, present unverified APY as verified, or market guaranteed
returns. Never write secrets/PAT/tokens to any file (read Keychain at runtime). Default autonomy is
**L0 (research) / L1 (recommendation)** only.

## 6. Safe-change process

1. Read this doc + `docs/06` + `docs/02`. 2. Pick **one** task from `docs/29` (§9 below). 3. Confirm
it is research-layer only (docs / schemas / templates / tests / non-runtime research modules in NEW
dirs). 4. If it touches runtime execution, RiskPolicy, the public dashboard, security-sensitive
behavior, keys/signing, funds, or deployment → **STOP and ask the owner** (§13). 5. Make the smallest
change; add/adjust tests; update the doc that describes it. 6. Report (§12). No big-bang rewrites, one
task per iteration, no hidden behavior, no architecture drift.

## 7. Docs-first process

New capability → write/extend its doc **before or with** the code. Docs live under `docs/NN_*.md`
(numbering already reserved in `docs/00_index.md`; `NN_lowercase` names are collision-free). ADRs are
namespaced **ADR-YL-###** to avoid collision with existing `docs/adr/ADR-0xx`. Behavior change ⇒ doc
update in the same iteration.

## 8. Test requirements

Any code change requires tests (`spa_core/tests/` / `tests/`, stdlib-`unittest`/`pytest`, no network,
deterministic, no live `data/` mutation — use sandbox fixtures). Keep the suite green
(`python3 -m pytest spa_core/tests/ -q`). New research modules ship with their own tests. Never let a
test run mutate the live paper track (`equity_curve_daily.json` etc.).

## 9. How to choose tasks

One task per iteration from the `docs/29` backlog. Prefer: higher priority, satisfied dependencies,
research-layer-only, MVP over later. Skip anything marked owner-gated until the owner answers. Mark
the task DONE in your report and note follow-ups.

## 10. Don't break the public dashboard / runtime data

- **Dashboard / cockpit / DFB board / site** (`landing/`, `deploy-landing.yml`) — out of scope. Do
  not edit; plan only via `docs/26`. Verify deploys by GitHub Actions run conclusion + real content,
  never by curl status code (a 404.html can return HTTP 200).
- **Runtime `data/*.json`** — do **not** write, migrate, or reshape. Research-layer card/evidence data
  goes in **NEW** directories only. Existing `data/*/` subdirs are untouched.

## 11. Prompts / agents / execution-support

Agents are **prompts + schemas + architecture only** — no autonomous agents in production. Build on
existing `spa_core/{agents,dev_agents,agent_runtime,redteam}`; default autonomy L0/L1. Execution
Support stays non-custodial, human-in-the-loop; it prepares unsigned checklists/approvals and never
touches keys or funds. See `docs/10`.

## 12. How to report completed work

Report: (a) task_id + title, (b) files created/edited (absolute paths), (c) what changed and why,
(d) tests added/run + result, (e) invariants re-confirmed (no execution-path change; no
key/signing; RiskPolicy not weakened; Risk Scoring v2 advisory; BTC/ETH decision-support; no APY
claimed verified without evidence), (f) follow-ups / owner-gated items. Do **not** commit or push
unless the owner asks.

## 13. STOP-and-ask rule

**Before touching runtime execution, the deterministic RiskPolicy, the public dashboard, security-
sensitive behavior, private keys / signing, fund movement, or deployment — STOP and ask the owner.**
Research-layer docs / schemas / templates / tests / non-runtime modules in new dirs may proceed.

## 14. What NOT to do

No big-bang rewrite; no deleting existing architecture; no LLM in risk/exec/monitoring/kill; no
keys/signing/funds/autonomous trading; no weakening RiskPolicy or the kill-switch; no hardcoded
secrets; no editing the dashboard/deploy; no touching runtime `data/*.json`; no duplicating the
existing research layer; no inventing APY/TVL/facts (unknown = "requires verification"); no
committing/pushing without owner request.
