# 26 — Dashboard Specification (§35)

**Purpose.** Specify the internal Yield Lab / AI Investment OS dashboard: the pages, what each shows
and its primary data source ([`25_api_specification.md`](25_api_specification.md)), the display
invariants that keep every number honest, the access model, and MVP sequencing. This is a **separate,
internal** research surface — not the public dashboard.

**Scope discipline — do not break what exists.** The **current public dashboard / Desk Cockpit / DFB
board** (`landing/src/pages/dashboard.astro` + `DashboardLive.jsx`, live via `api.earn-defi.com`, plus
the tournament and rates-desk pages) **must stay intact** ([`06_spa_core_invariants.md`](06_spa_core_invariants.md),
invariant D-13). The internal pages below are **additive**; they do not replace or restyle the public
dashboard, and are a much-later (MVP 2-3+) build. **No paper/backtest shown as live; never invent
APY/TVL.**

**Cross-references:** [`25_api_specification.md`](25_api_specification.md) (data source),
[`41_performance_reporting_methodology.md`](41_performance_reporting_methodology.md) (reporting rules),
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) (APY display rules),
[`14_risk_scoring_v2.md`](14_risk_scoring_v2.md) (advisory-score labeling).

---

## 1. Internal pages

| Page | Shows | Primary source (docs/25) | MVP |
|---|---|---|---|
| **Yield Lab** | Lifecycle overview across candidates/strategies (funnel by status) | `/api/yl/strategies` | 1 |
| **Discovery** | Incoming candidate queue + screen results | `/api/yl/candidates` | 2 |
| **Candidates** | Per-candidate detail, screens, hypothesis | `/api/yl/candidates/{id}` | 2 |
| **Strategy DB** | Strategy cards + lifecycle status + spread-over-floor | `/api/yl/strategies/{id}` | 1 |
| **Protocol DB** | Protocol due-diligence cards (audits, governance, admin keys) | `/api/yl/protocols` | 2 |
| **Stablecoin Risk** | Stablecoin cards, peg/backing status, peg-event history | `/api/yl/stablecoins` | 2 |
| **BTC Cycle** | Decision-support cycle view (advisory, never auto-trade) | `/api/yl/*` + cycle feeds | 2-3 |
| **ETH Yield** | Staking/restaking/hedged decision-support view | `/api/yl/*` + ETH feeds | 2-3 |
| **Risk Scores** | Advisory Risk Scoring v2 sub-scores + spread-attribution score | `/api/yl/risk/{id}` | 2 |
| **Agent Runs** | Agent run history, outputs, health | `/api/yl/agents` | 2 |
| **IC Memos** | Investment-committee memos + stage | `/api/yl/ic-memos` | 2-3 |
| **Alerts** | Research-layer alerts (freshness, outliers, red-team flags) | `/api/yl/*` | 2 |
| **Reports** | Generated performance/attribution reports | `/api/yl/reports` | 2-3 |
| **Approvals** | Approval state + hash-chained decision log | `/api/yl/decisions` | 2-3 |
| **Capital Tiers** | Strategy universe / caps by tier (doc 34) | static + `/api/yl/allocations` | 2 |
| **APY Evidence** | L0–L6 evidence view per strategy/yield source | `/api/yl/strategies/{id}` | 1 |

---

## 2. Display invariants (non-negotiable)

Every page enforces the honesty rules; the dashboard cannot render what these forbid:

1. **Never show paper/backtest as live.** Paper (L3) is labelled "paper"; live is a distinct, separately
   coloured surface ([`37`](37_apy_realism_and_evidence_standard.md) rule 2; [`06`](06_spa_core_invariants.md) C-8).
2. **Never show an APY without** risk category + last-verified date + yield-source explanation, and only
   at **evidence level L2+** ([`37`](37_apy_realism_and_evidence_standard.md) §3). A number missing any of
   these is not rendered.
3. **Always show the evidence level** (L0–L6 badge) next to every performance figure.
4. **Advisory scores are clearly labelled "advisory"** — Risk Scoring v2 is never presented as a gate
   ([`14`](14_risk_scoring_v2.md)).
5. **Spread over floor, not absolute APY** — Enhanced/Max strategies display spread over the live RWA
   floor with the risk-explanation itemization and the `spread_fully_explained` flag
   ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).
6. **Staleness is visible** — any figure past its freshness window shows an age/stale marker (fail-closed
   from the API, doc 25 §3).
7. **Refusals are first-class** — the decision log surfaces refusals as positive results, not hidden.

---

## 3. Access model & MVP

- **Access.** Internal-only pages (Candidates, Agent Runs, IC Memos, Approvals) require auth (Keychain
  `SPA_API_KEY`). Any figure destined for a public surface must already satisfy the L2+ display rules.
  The internal dashboard is a separate deployment from the public site; it does not share styling or
  routing with `dashboard.astro`.
- **MVP prioritization.** MVP-1: Yield Lab, Strategy DB, APY Evidence (over existing research
  artifacts). MVP 2-3: Discovery, Candidates, Protocol/Stablecoin DBs, Risk Scores, Agent Runs, Alerts,
  Capital Tiers. Later: BTC Cycle, ETH Yield, IC Memos, Reports, Approvals — following the API/database
  phases ([`25`](25_api_specification.md), [`24`](24_database_schema.md)).
