# 00 — Yield Lab Documentation Index

This is the index for the SPA **Yield Lab / AI Investment OS** research-layer documentation set.
It maps the full planned docs set, marks what already exists versus what is planned, and points to
the durable charter.

**Charter (permanent reference):** [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md)
— the one-page founder charter. Where any doc and the charter diverge, the charter's *intent* governs.

**Scope discipline.** These are research-layer documents. They do not modify runtime code, the
deterministic RiskPolicy, the kill-switch, the public dashboard, or deployment. See
[`06_spa_core_invariants.md`](06_spa_core_invariants.md) for the invariants every session preserves,
and [`02_current_architecture_audit.md`](02_current_architecture_audit.md) for the honest map of
what already exists (a substantial research layer is already built — do not duplicate it).

**Status legend:** `EXISTS` = written · `PLANNED` = not yet written · `PARTIAL` = codified culture/code
exists, doc pending.

---

## Overview

| Doc | Status | Purpose |
|---|---|---|
| `00_index.md` | EXISTS | This index. |
| `01_mission_and_scope.md` | PLANNED | Mission, capital-preservation-first framing, autonomy levels (L0/L1 now). |
| `02_current_architecture_audit.md` | **EXISTS** | Honest audit: what the charter assumes vs what already exists in the repo. |
| `03_glossary.md` | PLANNED | Shared vocabulary (yield source, evidence level, capital tier, sleeve). |

## Architecture

| Doc | Status | Purpose |
|---|---|---|
| `04_layered_architecture.md` | PLANNED | SPA Core → Yield Lab → AI Investment OS → Builder OS → Execution Support. |
| `05_research_layer_topology.md` | PLANNED | How strategy_lab/redteam/riskwire/dfb/compliance fit the charter vocabulary. |
| `06_spa_core_invariants.md` | **EXISTS** | Permanent invariants the research layer is built around, never through. |
| `23_data_architecture.md` | PLANNED | Data-flow topology (stub → expand at MVP 2-3). |
| `24_db_schema.md` | PLANNED | Card / evidence / decision-log schema (future). |
| `25_api_spec.md` | PLANNED | Research-layer read-API surface (future). |

## Yield / Strategy

| Doc | Status | Purpose |
|---|---|---|
| `07_yield_lab_lifecycle.md` | PLANNED | idea → research → paper → small-capital → approved / frozen / retired. |
| `11_strategy_card_system.md` | PLANNED | Strategy Card schema + template + lifecycle binding. |
| `12_protocol_cards.md` | PLANNED | Protocol due-diligence card system. |
| `13_stablecoin_cards.md` | PLANNED | Stablecoin due-diligence card system (peg mechanism, backing, redemption). |
| `33_yield_thesis_map.md` | **EXISTS** | Flagship map: where the yield actually comes from (stablecoin / BTC / ETH). |
| `34_capital_tiers.md` | PLANNED | Strategy universe by capital tier ($100k → $100M+). |
| `35_discovery_engine.md` | PLANNED | How candidate strategies are discovered and screened. |
| `38_stablecoin_yield_engine.md` | PLANNED | Deep dive on the stablecoin yield domain. |
| `44_first_20_strategies.md` | PLANNED | First strategy roster to card and evaluate. |

## Risk

| Doc | Status | Purpose |
|---|---|---|
| `14_risk_scoring_v2.md` | PLANNED | Advisory 0–100 sub-scores (never a hard gate). |
| `31_open_questions.md` | **EXISTS** | Unresolved tensions / risks the docs must hold honestly. |
| `37_apy_realism_and_evidence_standard.md` | **EXISTS** | Evidence levels L0–L6 + APY taxonomy + hard claim rules. |
| `40_data_quality.md` | PLANNED | Data-quality gating for research inputs (stub). |
| `43_dangerous_strategies.md` | PLANNED | Catalogue of strategies the desk refuses and why (stub). |

## BTC / ETH

| Doc | Status | Purpose |
|---|---|---|
| `15_btc_cycle.md` | PLANNED | BTC capital-cycle decision-support framework. |
| `16_eth_yield.md` | PLANNED | ETH staking / restaking / yield decision-support framework. |
| `36_btc_capital_cycle_machine.md` | PLANNED | BTC accumulation / rotation / profit-ladder machine (decision-support). |

## Agents

| Doc | Status | Purpose |
|---|---|---|
| `10_agent_architecture.md` | PLANNED | Investment OS + Builder OS agent roles and guardrails. |
| `28_cc_master_instructions.md` | PLANNED | Claude Code master instructions for future research sessions. |
| `agent_prompts/` | PLANNED | Per-agent prompt templates (discovery, protocol DD, red-team, reporting). |

## Data / API / Dashboard

| Doc | Status | Purpose |
|---|---|---|
| `26_dashboard.md` | PLANNED | Research-layer dashboard expansion plan (much later). |
| `41_performance_reporting.md` | PLANNED | Performance / attribution reporting templates. |

## Governance / Compliance

| Doc | Status | Purpose |
|---|---|---|
| `39_ic_workflow.md` | PLANNED | Investment-committee memo + approval workflow. |
| `42_external_capital.md` | PLANNED | External-capital readiness (legal review gated). |
| `45_compliance_map.md` | PLANNED | Compliance-surface map (cross-references existing `compliance/`). |

## Planning

| Doc | Status | Purpose |
|---|---|---|
| `29_backlog.md` | PLANNED | Prioritized research-layer backlog. |
| `30_first_30_days.md` | PLANNED | First-30-days execution plan. |

## ADRs

| Doc | Status | Purpose |
|---|---|---|
| `adr/ADR-YL-###` | PLANNED | Yield-Lab ADRs, namespaced **ADR-YL-###** to avoid collision with existing `docs/adr/ADR-0xx`. |

---

**Cross-references:** the existing research layer is `spa_core/strategy_lab/`
(`aggressive_lab`, `rates_desk`, `rwa_backstop`, `liquidator`, `underwriting`),
`spa_core/redteam/`, `spa_core/riskwire/`, `spa_core/dfb/`, `spa_core/compliance/`.
These are already built. New docs *formalize and unify* them into the charter vocabulary —
they do not propose duplicating them.
