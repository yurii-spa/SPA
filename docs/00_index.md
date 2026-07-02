# 00 — Yield Lab Documentation Index

This is the index for the SPA **Yield Lab / AI Investment OS** research-layer documentation set.
It maps the docs that actually exist on disk (this branch), marks each one's completeness, and points
to the durable charter.

**Charter (permanent reference):** [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md)
— the one-page founder charter. Where any doc and the charter diverge, the charter's *intent* governs.

**Scope discipline.** These are research-layer documents. They do not modify runtime code, the
deterministic RiskPolicy, the kill-switch, the public dashboard, or deployment. See
[`06_spa_core_invariants.md`](06_spa_core_invariants.md) for the invariants every session preserves,
and [`02_current_architecture_audit.md`](02_current_architecture_audit.md) for the honest map of
what already exists (a substantial research layer is already built — do not duplicate it).

**Status legend:**
- `DONE` — written with real content for its current scope.
- `STUB` — a Priority-3 placeholder that defines shape/intent only; expands at MVP 2-3 (self-labels
  `**Status: STUB.**` at the top).
- `PARTIAL` — culture/code exists and the doc is under active expansion by a parallel sprint agent.
- `PLANNED` — referenced but not yet on disk (owned by a parallel agent this sprint).

> **Numbering note (honest deviation).** The charter's original §8 outline placed
> `03_product_vision` / `04_product_lines` / `05_system_architecture` at those slots. The
> implemented docs instead use **`03_glossary`**, **`04_layered_architecture`**, and
> **`05_research_topology_map`** — the product-vision/product-lines/system-architecture material was
> folded into [`01_project_overview.md`](01_project_overview.md), [`04_layered_architecture.md`](04_layered_architecture.md),
> and [`02_current_architecture_audit.md`](02_current_architecture_audit.md) respectively. This is a
> deliberate deviation from the charter's raw numbering; the *intent* is preserved. Filenames on disk
> are authoritative — trust this table, not the charter's illustrative section numbers.
>
> **Companion docs.** Three numbers carry a primary doc plus a companion, disambiguated with an `a`
> suffix so each number stays unique: **`07`** (`07_yield_lab_architecture` + `07a_sleeve_status`),
> **`26`** (`26_dashboard_specification` + `26a_surfaces`), **`35`** (`35_strategy_discovery_engine` +
> `35a_screening_rubric`). The `a` file is always the companion; the base number is cross-referenced.

---

## Overview & foundation

| Doc | Status | Purpose |
|---|---|---|
| `00_index.md` | DONE | This index. |
| `01_project_overview.md` | DONE | Mission, scope, capital-preservation-first framing, autonomy levels, product vision. |
| `02_current_architecture_audit.md` | DONE | Honest audit: what the charter assumes vs what already exists in the repo. |
| `03_glossary.md` | DONE | Shared vocabulary (yield source, evidence level, capital tier, sleeve). |
| `06_spa_core_invariants.md` | DONE | Permanent invariants the research layer is built around, never through. |

## Architecture

| Doc | Status | Purpose |
|---|---|---|
| `04_layered_architecture.md` | DONE | SPA Core → Yield Lab → AI Investment OS → Builder OS → Execution Support. |
| `05_research_topology_map.md` | DONE | How `strategy_lab`/`redteam`/`riskwire`/`dfb`/`compliance` map to charter vocabulary + evidence levels. |
| `17_portfolio_construction.md` | DONE | Portfolio construction / allocation framing across sleeves. |
| `23_data_architecture.md` | STUB | Data-flow topology shape (expand at MVP 2-3). |
| `24_database_schema.md` | STUB | Card / evidence / decision-log persistent-store schema (future). |
| `25_api_specification.md` | STUB | Research-layer read-API surface (future). |

## Yield / Strategy

| Doc | Status | Purpose |
|---|---|---|
| `07_yield_lab_architecture.md` | DONE | Yield Lab lifecycle idea → research → paper → small-capital → approved / frozen / retired. |
| `07a_sleeve_status.md` | DONE | Companion to 07: existing `strategy_lab` sleeves mapped onto lifecycle states. |
| `11_strategy_card_system.md` | DONE | Strategy Card schema + template + lifecycle binding. |
| `12_protocol_card_system.md` | DONE | Protocol due-diligence card system. |
| `13_stablecoin_card_system.md` | DONE | Stablecoin due-diligence card system (peg, backing, redemption). |
| `33_yield_thesis_map.md` | DONE | Flagship map: where the yield actually comes from (stablecoin / BTC / ETH). |
| `34_capital_tiers_strategy.md` | DONE | Strategy universe by capital tier ($100k → $100M+). |
| `35_strategy_discovery_engine.md` | DONE | How candidate strategies are discovered and fed to screening. |
| `35a_screening_rubric.md` | DONE | Companion to 35: hard-reject + human-review + red-team triggers rubric. |
| `38_stablecoin_yield_engine.md` | DONE | Deep dive on the stablecoin yield domain. |
| `44_research_first_20_strategies.md` | STUB | First strategy roster to card and evaluate. |

## Risk

| Doc | Status | Purpose |
|---|---|---|
| `14_risk_scoring_v2.md` | DONE | Advisory 0–100 sub-scores (never a hard gate). |
| `31_open_questions.md` | DONE | Unresolved tensions / risks the docs must hold honestly. |
| `37_apy_realism_and_evidence_standard.md` | DONE | Evidence levels L0–L6 + APY taxonomy + hard claim rules. |
| `40_data_quality_framework.md` | STUB | Data-quality gating for research inputs. |
| `43_dangerous_strategies.md` | STUB | Catalogue of strategy patterns the desk refuses and why. |

## BTC / ETH

| Doc | Status | Purpose |
|---|---|---|
| `15_btc_cycle_framework.md` | DONE | BTC capital-cycle decision-support framework. |
| `16_eth_yield_framework.md` | DONE | ETH staking / restaking / yield decision-support framework. |
| `36_btc_capital_cycle_machine.md` | DONE | BTC accumulation / rotation / profit-ladder machine (decision-support). |

## Agents / Operations

| Doc | Status | Purpose |
|---|---|---|
| `10_agent_architecture.md` | DONE | Investment OS + Builder OS agent roles and guardrails. |
| `18_monitoring_and_alerting.md` | DONE | Research-layer monitoring / alerting surface. |
| `19_execution_support.md` | PARTIAL | Non-custodial, human-in-the-loop execution support (parallel-sprint expansion). |
| `28_claude_code_master_instructions.md` | DONE | Claude Code master instructions for future research sessions. |

## Data / API / Dashboard

| Doc | Status | Purpose |
|---|---|---|
| `26_dashboard_specification.md` | STUB | Research-layer dashboard expansion plan (much later). |
| `26a_surfaces.md` | DONE | Companion to 26: read-only card/evidence surface mockup (evidence-level badges). |
| `41_performance_reporting_methodology.md` | STUB | Performance / attribution reporting methodology + templates. |

## Governance / Compliance

| Doc | Status | Purpose |
|---|---|---|
| `22_compliance_surface.md` | DONE | Compliance surface (cross-references existing `spa_core/compliance/`). |
| `39_investment_committee_workflow.md` | STUB | Investment-committee memo + approval workflow. |
| `42_external_capital_readiness.md` | STUB | External-capital readiness checklist (legal review gated). |

## Planning

| Doc | Status | Purpose |
|---|---|---|
| `29_backlog.md` | DONE | Prioritized research-layer backlog (source of task IDs). |
| `30_first_30_days_plan.md` | DONE | First-30-days execution plan. |

## PLANNED / parallel-sprint docs (referenced, not yet on disk)

These filenames are cross-referenced from existing docs but are owned by other agents this sprint.
References resolve only once each agent lands its file **at exactly this path**:

| Doc | Referenced by |
|---|---|
| `20_human_in_the_loop_governance.md` | `01_project_overview.md`, `18_monitoring_and_alerting.md` |
| `45_compliance_map.md` | `42_external_capital_readiness.md`, `05_research_topology_map.md` (non-link "future" mention), this index |

> `docs/08`, `docs/09`, `docs/21` are also parallel-agent-owned this sprint but nothing in the Yield
> Lab doc set currently references them (the `08_*`/`01_*` hits elsewhere in the repo are unrelated
> `docs/backtest_handoff/` and `research/` files). `19_execution_support.md` now exists (marked
> PARTIAL above).

---

## Schemas — `docs/schemas/`

JSON Schemas backing the card / lifecycle / scoring system (validated by `tests/test_schemas_valid.py`):

| Schema | Purpose |
|---|---|
| `candidate.schema.json` | Strategy candidate / card record. |
| `lifecycle_state.schema.json` | Yield Lab lifecycle status enum + transitions. |
| `risk_score.schema.json` | Advisory Risk Scoring v2 sub-scores. |
| `capital_tier.schema.json` | Capital-tier definitions ($100k → $100M+). |
| `btc_signal.schema.json` | BTC cycle decision-support signal record. |

## Templates — `docs/templates/`

Fill-in templates for the research workflow: `task_plan.md`, `work_report.md`,
`allocation_proposal.md`, `paper_test_plan.md`, `small_capital_report.md`, `retirement.md`,
`risk_disclosure.md`, `perf_report.md`, `stablecoin_scan.md`, `lst_dd.md`.

## ADRs — `docs/adr/ADR-YL-*`

Yield-Lab ADRs, namespaced **ADR-YL-###** to avoid collision with existing `docs/ADR_0xx` / `docs/ADR-0xx`:

| ADR | Decision |
|---|---|
| `ADR-YL-001` | Existing SPA Core preserved. |
| `ADR-YL-002` | LLM forbidden in the execution path. |
| `ADR-YL-003` | Yield Lab added as a research layer. |
| `ADR-YL-004` | Risk Scoring v2 is advisory, not an execution gate. |
| `ADR-YL-005` | Execution Support is non-custodial. |
| `ADR-YL-006` | APY claims require evidence levels. |
| `ADR-YL-007` | BTC/ETH cycle modules are decision-support, not auto-trading. |
| `ADR-YL-008` | Unified Yield Lab mandate. |
| `ADR-YL-template.md` | Template for new Yield-Lab ADRs. |

## Research harness — `research/`

- `research/lifecycle.py` — lifecycle-transition logic (exercised by `tests/test_lifecycle_transitions.py`).
- `research/cards/validate.py` (+ `test_validate.py`) — card validation.
- `research/*.md` — background research reports (competitor, security, reliability, yield research, etc.).

## Tests (research-layer harness)

Green harness gating this layer:
`research/` · `tests/test_schemas_valid.py` · `tests/test_cards_complete.py` ·
`tests/test_lifecycle_transitions.py` · `tests/test_evidence_levels.py` ·
`tests/test_no_secrets_in_research.py` · `tests/test_no_execution_import.py` ·
`tests/test_yield_thesis_map.py`.

---

**Cross-references:** the existing research layer is `spa_core/strategy_lab/`
(`aggressive_lab`, `rates_desk`, `rwa_backstop`, `liquidator`, `underwriting`),
`spa_core/redteam/`, `spa_core/riskwire/`, `spa_core/dfb/`, `spa_core/compliance/`.
These are already built. New docs *formalize and unify* them into the charter vocabulary —
they do not propose duplicating them.
