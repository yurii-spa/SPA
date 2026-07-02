# 26 — Dashboard Specification (§35)

**Status: STUB.** This document is a Priority-3 placeholder for the *future* internal Yield Lab /
AI Investment OS dashboard. It lists the planned internal pages only — no layout, component, or
interaction detail.

**Scope discipline — do not break what exists.** The **current public dashboard / Desk Cockpit / DFB
board** (`landing/src/pages/dashboard.astro` + `DashboardLive.jsx`, live via `api.earn-defi.com`,
plus the tournament and rates-desk pages) **must stay intact** (see `06_spa_core_invariants.md`,
invariant D-13). The internal pages below are a **separate, additive** research-layer surface; they
do not replace or restyle the public dashboard, and are a much-later (MVP 2-3+) build.

**Cross-references:** `docs/25_api_specification.md` (data source), `docs/41_performance_reporting_methodology.md`
(reporting rules), `docs/37` (APY evidence display rules).

## Planned contents (outline only)

- **Planned internal pages:**
  - Yield Lab — lifecycle overview across candidates/strategies.
  - Discovery — incoming candidate queue and screens.
  - Candidates — per-candidate detail and screen results.
  - Strategy DB — strategy cards + lifecycle status.
  - Protocol DB — protocol due-diligence cards.
  - Stablecoin Risk — stablecoin cards, peg/backing status.
  - BTC Cycle — decision-support cycle view (advisory).
  - ETH Yield — ETH staking/restaking/yield decision-support view.
  - Risk Scores — advisory Risk Scoring v2 sub-scores (advisory only).
  - Agent Runs — agent run history, outputs, health.
  - IC Memos — investment-committee memos.
  - Alerts — research-layer alerts.
  - Reports — generated performance/attribution reports.
  - Approvals — approval state and decision log.
  - Capital Tiers — strategy universe / caps by tier.
  - APY Evidence — L0–L6 evidence view per strategy/yield source.
- **Display invariants** — never show paper/backtest as live; always show yield source, risk
  category, last-verified date; advisory scores clearly labelled advisory.
- **Access model** — internal vs public surfaces; auth via Keychain keys.
- **MVP prioritization** — which pages are MVP-1 vs MVP-2/3 vs later.

TODO: expand at MVP 2-3 stage.
