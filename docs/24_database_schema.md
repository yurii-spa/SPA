# 24 — Database Schema (§33)

**Status: STUB.** This document is a Priority-3 placeholder for the *future* persistent-store schema
of the Yield Lab / AI Investment OS. Today the research layer runs on runtime `data/*.json`
state files; a relational store is a later-stage (MVP 2-3+) concern. This stub lists the target
tables and the migration phases only — no column-level detail.

**Scope discipline.** Research-layer only. Runtime `data/*.json` formats remain the source of truth
and are **not migrated** into any database unless explicitly requested by the owner (see
`06_spa_core_invariants.md`, invariant D-10). This document does not change any current storage.

**Cross-references:** `docs/23_data_architecture.md` (data flow), `docs/40_data_quality_framework.md`
(lineage/freshness), `docs/25_api_specification.md` (read surface over these tables).

## Planned contents (outline only)

- **Store choice** — target is PostgreSQL for the research layer; rationale and boundaries.
- **Target tables (~30, names indicative, requires design at MVP 2-3):**
  - `strategies`, `strategy_cards`, `strategy_lifecycle_events`
  - `candidates`, `candidate_screens`
  - `protocols`, `protocol_cards`, `protocol_audits`
  - `stablecoins`, `stablecoin_cards`, `peg_events`
  - `yield_sources`, `apy_observations`, `apy_evidence`
  - `risk_scores`, `risk_subscores`, `red_team_reviews`
  - `capital_tiers`, `allocations`, `portfolio_snapshots`
  - `agents`, `agent_runs`, `agent_outputs`
  - `ic_memos`, `approvals`, `decisions`
  - `alerts`, `reports`, `data_sources`, `data_lineage`, `ingestion_runs`
- **Relationships** — card ↔ evidence ↔ decision-log linkage; lifecycle-status foreign keys.
- **Evidence-level modeling** — how L0–L6 (`docs/37`) is represented and queried.
- **Migration phases A–F (indicative sequencing):**
  - Phase A — schema + read-only mirror of research artifacts.
  - Phase B — candidate/strategy card tables.
  - Phase C — protocol/stablecoin due-diligence tables.
  - Phase D — risk-scoring / red-team / evidence tables.
  - Phase E — IC / approvals / decision-log tables.
  - Phase F — agent-runs / reporting / lineage tables.
- **Non-migration boundary** — explicit list of runtime JSON that stays JSON.

TODO: expand at MVP 2-3 stage.
