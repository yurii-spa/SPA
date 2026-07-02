# 00 — Yield Lab Documentation Index (master)

The single master index for the SPA **Yield Lab / AI Investment OS** documentation. Per
[`ADR-YL-009`](adr/ADR-YL-009-canonical-documentation-structure.md), the docs are **one canonical
system with two layers** — OPERATIONAL (site-facing) and FRAMEWORK (why & how) — with exactly one
canonical file per concept.

**Charter (permanent reference):** [`prompts/claude_code/yield_lab_master.md`](../prompts/claude_code/yield_lab_master.md).
Where the charter's *illustrative* numbers (e.g. "10–15%", product-line APY bands) differ from the
operational canon, **the canon governs** — the charter's *intent* is preserved, its raw numbers are a
search range, not a promise (see [`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).

**Scope discipline.** Research-layer only — no runtime code, RiskPolicy, kill-switch, dashboard, or
deploy. Invariants: [`06_spa_core_invariants.md`](06_spa_core_invariants.md). Honest map of what already
exists (do not duplicate): [`02_current_architecture_audit.md`](02_current_architecture_audit.md).

---

## Canonical source per concept (ADR-YL-009 §"the map")

> **Rule:** one concept, one file. Every other mention **links** here; none restates the content.

| Concept | Canonical file |
|---|---|
| Yield Lab **mandate** (spread over floor; every bp risk-explained; unexplained → reject) | [`adr/ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) |
| **RWA floor** (~3.4%, live/dynamic) | `data/rwa_feed.py` → surfaced in [`decision_index.md`](decision_index.md) / [`non_ethena_ladder.md`](non_ethena_ladder.md) |
| **Evidence levels** L0–L6 | [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) |
| **Underwriting method** (Q1→Q4 tree + reason-codes) | [`underwriting_rubric.md`](underwriting_rubric.md) |
| **Verdicts** ↔ **lifecycle status** | verdicts: [`underwriting_rubric.md`](underwriting_rubric.md) · lifecycle + bridge: [`07_yield_lab_architecture.md`](07_yield_lab_architecture.md) (OQ-11) |
| **Product lines** (Preserve/Core/…) | [`17_portfolio_construction.md`](17_portfolio_construction.md) (spread-based, canonical; APY bands elsewhere = illustrative, OQ-12) |
| **Capital tiers** | [`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md) |
| **Live decisions** (per-candidate verdicts) | [`decision_index.md`](decision_index.md) |
| **Fundable ladder / portfolio** | [`non_ethena_ladder.md`](non_ethena_ladder.md) |
| **Honest edge finding** ($10M = trust/relationships off-code) | [`STRUCTURAL_DESK.md`](STRUCTURAL_DESK.md) + [`non_ethena_ladder.md`](non_ethena_ladder.md) |

---

## Layer A — OPERATIONAL docs (referenced by the public site; keep names/paths)

These are the "decisions are the product" surface. The public site (`landing/src`) links them; **do not
rename or break them.** All 14 current site references resolve to real files.

- [`decision_index.md`](decision_index.md) — every candidate's ADR-YL-008 verdict + spread + evidence (the audit surface).
- [`underwriting_rubric.md`](underwriting_rubric.md) — the reusable method (Q1→Q4 tree + reason-code taxonomy) distilled from real decisions.
- [`yield_landscape_2026.md`](yield_landscape_2026.md) — **whole-map synthesis** of the honest 2026 stablecoin-yield landscape (floor / ADVANCE rungs / 8-12% / REFUSE archetypes / pick-two).
- [`non_ethena_ladder.md`](non_ethena_ladder.md) — the assembled honest fundable book (~4.75% non-Ethena; the pick-two trade-off).
- [`STRUCTURAL_DESK.md`](STRUCTURAL_DESK.md) · [`RATES_DESK_VALIDATION.md`](RATES_DESK_VALIDATION.md) · [`DD_PACK.md`](DD_PACK.md) · [`FUNDABILITY.md`](FUNDABILITY.md) · [`LIQUIDATOR_DERISK.md`](LIQUIDATOR_DERISK.md) · [`PROOF_CHAIN_SPEC.md`](PROOF_CHAIN_SPEC.md) · [`COMPETITIVE_POSITION.md`](COMPETITIVE_POSITION.md) · [`VERIFIER_RELEASE.md`](VERIFIER_RELEASE.md) · [`DFB_METHODOLOGY.md`](DFB_METHODOLOGY.md) · [`SITE_DESIGN_SYSTEM.md`](SITE_DESIGN_SYSTEM.md) / [`SITE_DESIGN_SYSTEM_V2.md`](SITE_DESIGN_SYSTEM_V2.md).

---

## Layer B — FRAMEWORK docs (the "why & how"; reference operational + ADRs, don't duplicate)

**Overview & foundation:** [`01_project_overview`](01_project_overview.md) · [`02_current_architecture_audit`](02_current_architecture_audit.md) · [`03_glossary`](03_glossary.md) · [`04_layered_architecture`](04_layered_architecture.md) · [`05_research_topology_map`](05_research_topology_map.md) · [`06_spa_core_invariants`](06_spa_core_invariants.md)

**Architecture:** [`07_yield_lab_architecture`](07_yield_lab_architecture.md) (+ companion [`07a_sleeve_status`](07a_sleeve_status.md)) · [`08_ai_investment_os_architecture`](08_ai_investment_os_architecture.md) · [`09_builder_os_architecture`](09_builder_os_architecture.md) · [`10_agent_architecture`](10_agent_architecture.md)

**Card systems:** [`11_strategy_card_system`](11_strategy_card_system.md) · [`12_protocol_card_system`](12_protocol_card_system.md) · [`13_stablecoin_card_system`](13_stablecoin_card_system.md) · [`14_risk_scoring_v2`](14_risk_scoring_v2.md)

**Cycle/portfolio frameworks:** [`15_btc_cycle_framework`](15_btc_cycle_framework.md) · [`16_eth_yield_framework`](16_eth_yield_framework.md) · [`17_portfolio_construction`](17_portfolio_construction.md) *(canonical product-lines)*

**Ops/governance/compliance:** [`18_monitoring_and_alerting`](18_monitoring_and_alerting.md) · [`19_execution_support`](19_execution_support.md) · [`20_human_in_the_loop_governance`](20_human_in_the_loop_governance.md) · [`21_security_and_custody_rules`](21_security_and_custody_rules.md) · [`22_compliance_surface`](22_compliance_surface.md)

**Data/API/dashboard (P3 stubs):** [`23_data_architecture`](23_data_architecture.md) · [`24_database_schema`](24_database_schema.md) · [`25_api_specification`](25_api_specification.md) · [`26_dashboard_specification`](26_dashboard_specification.md) (+ companion [`26a_surfaces`](26a_surfaces.md))

**Process:** [`28_claude_code_master_instructions`](28_claude_code_master_instructions.md) · [`29_backlog`](29_backlog.md) · [`30_first_30_days_plan`](30_first_30_days_plan.md) · [`31_open_questions`](31_open_questions.md) · [`45_builder_os_workflow`](45_builder_os_workflow.md)

**Yield frameworks:** [`33_yield_thesis_map`](33_yield_thesis_map.md) · [`34_capital_tiers_strategy`](34_capital_tiers_strategy.md) *(canonical capital-tiers)* · [`35_strategy_discovery_engine`](35_strategy_discovery_engine.md) (+ companion [`35a_screening_rubric`](35a_screening_rubric.md)) · [`36_btc_capital_cycle_machine`](36_btc_capital_cycle_machine.md) · [`37_apy_realism_and_evidence_standard`](37_apy_realism_and_evidence_standard.md) *(canonical evidence-levels)* · [`38_stablecoin_yield_engine`](38_stablecoin_yield_engine.md)

**Reports/IC/readiness (P3 stubs):** [`39_investment_committee_workflow`](39_investment_committee_workflow.md) · [`40_data_quality_framework`](40_data_quality_framework.md) · [`41_performance_reporting_methodology`](41_performance_reporting_methodology.md) · [`42_external_capital_readiness`](42_external_capital_readiness.md) · [`43_dangerous_strategies`](43_dangerous_strategies.md) · [`44_research_first_20_strategies`](44_research_first_20_strategies.md)

---

## Layer C — ADRs (Yield Lab)

[`ADR-YL-001`](adr/ADR-YL-001-existing-spa-core-preserved.md) existing-core-preserved · [`ADR-YL-002`](adr/ADR-YL-002-llm-forbidden-in-execution-path.md) LLM-forbidden · [`ADR-YL-003`](adr/ADR-YL-003-yield-lab-added-as-research-layer.md) research-layer · [`ADR-YL-004`](adr/ADR-YL-004-risk-scoring-v2-is-advisory-not-execution-gate.md) risk-scoring-advisory · [`ADR-YL-005`](adr/ADR-YL-005-execution-support-is-non-custodial.md) non-custodial · [`ADR-YL-006`](adr/ADR-YL-006-apy-claims-require-evidence-levels.md) evidence-levels · [`ADR-YL-007`](adr/ADR-YL-007-btc-eth-cycle-modules-are-decision-support-not-autotrading.md) decision-support · **[`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md) unified mandate (canonical)** · **[`ADR-YL-009`](adr/ADR-YL-009-canonical-documentation-structure.md) canonical doc structure (this map)**.

---

## Numbering & companion notes (honest deviations)

- **§8 numbering deviation:** the charter's §8 outline placed `03_product_vision / 04_product_lines /
  05_system_architecture` at those slots; the implemented docs use **`03_glossary` / `04_layered_architecture` /
  `05_research_topology_map`** — that material folded into `01`, `04`, `02`. Filenames on disk are
  authoritative; trust this index, not the charter's raw section numbers.
- **Companion docs** (`a`-suffix keeps each number unique): `07`(+`07a_sleeve_status`), `26`(+`26a_surfaces`),
  `35`(+`35a_screening_rubric`).
- **Status:** most Layer-B docs are DONE; the P3 set (23,24,25,26,39,40,41,42,43,44) self-label `STUB`
  (expand at MVP 2-3). Open questions: [`31_open_questions.md`](31_open_questions.md).
