# 25 — API Specification (§34)

**Purpose.** Specify the Yield Lab research-layer API surface: the existing routes that must stay
stable, the planned additive endpoint groups (with method, purpose, and MVP timing), the read-only /
decision-support contract, versioning, and auth. This is the read surface over the research store
([`24_database_schema.md`](24_database_schema.md)) and the data source for the internal dashboard
([`26_dashboard_specification.md`](26_dashboard_specification.md)).

**Existing, in-scope-to-preserve API.** A live read-API already exists at `spa_core/api/server.py`
(FastAPI, port 8765, exposed via `api.earn-defi.com`). It serves the public dashboard and cockpit. The
planned research-layer endpoints below are **additive**; the existing API and the public dashboard it
feeds **must stay intact** ([`06_spa_core_invariants.md`](06_spa_core_invariants.md), invariants D-13,
E). Auth remains via Keychain-provided keys (`SPA_API_KEY`, gated by `SPA_API_REQUIRE_AUTH`); **no
secrets in files**.

**Cross-references:** [`24_database_schema.md`](24_database_schema.md) (backing store),
[`26_dashboard_specification.md`](26_dashboard_specification.md) (consumer),
[`23_data_architecture.md`](23_data_architecture.md) (upstream data),
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) (APY display rules).

---

## 1. Existing API inventory (must stay stable)

These live routes in `spa_core/api/server.py` are preserved unchanged:

| Route group | Purpose |
|---|---|
| `/api/live/*` | Live portfolio / equity / positions for the public dashboard |
| `/api/live/safety` | Public two-tier kill-switch state + evidenced drawdown |
| `/api/rates-desk/{surface,opportunities,decisions,proof}` | Rate surface, opportunities, entries+refusals+proof_hash, proof-chain |
| `/api/refusal` | Per-underlying SAFE/WATCH/REFUSE/UNKNOWN |
| `/api/strategy-lab/promotion` | Sleeve promotion ladder |
| `/api/tournament` | Tournament live data |

**Rule:** research-layer endpoints are added under **new prefixes** (`/api/yl/*`); no existing route is
renamed, removed, or changed in shape.

---

## 2. Planned research-layer endpoint groups (additive, `/api/yl/*`)

All read-only (`GET`) unless noted; every group marked MVP-1 / MVP-2-3 / Later.

| Group | Endpoints (indicative) | Purpose | MVP |
|---|---|---|---|
| **Strategies** | `GET /api/yl/strategies`, `GET /api/yl/strategies/{id}`, `GET /api/yl/strategies/{id}/lifecycle` | List / detail / lifecycle status | 1 |
| **Candidates** | `GET /api/yl/candidates`, `GET /api/yl/candidates/{id}/screens` | Discovery queue + screen results | 2 |
| **Protocols** | `GET /api/yl/protocols`, `GET /api/yl/protocols/{id}` | Protocol cards, audit/governance status | 2 |
| **Stablecoins** | `GET /api/yl/stablecoins`, `GET /api/yl/stablecoins/{id}` | Stablecoin cards, peg/backing status | 2 |
| **Risk** | `GET /api/yl/risk/{strategy_id}` | Advisory Risk Scoring v2 sub-scores + spread-attribution score | 2 |
| **Portfolio** | `GET /api/yl/allocations`, `GET /api/yl/portfolio/snapshots` | Recommended allocations, snapshots, capital-tier context | 2 |
| **Agents** | `GET /api/yl/agents`, `GET /api/yl/agents/{id}/runs` | Agent runs, outputs, health | 2 |
| **Reports** | `GET /api/yl/reports`, `GET /api/yl/reports/{id}` | Generated performance/attribution reports | 2-3 |
| **Approvals** | `GET /api/yl/ic-memos`, `GET /api/yl/decisions` | IC memos, approval state, hash-chained decision log | 2-3 |

Every response that includes an APY figure **must** carry: risk category, last-verified date,
yield-source explanation, and evidence level — and may only surface a value at **L2+**
([`37`](37_apy_realism_and_evidence_standard.md) §3). Responses omit any figure that fails these
conditions rather than showing an unqualified number.

---

## 3. Read-only / decision-support contract

- The research API is **read-only / decision-support**. No endpoint triggers execution, signing, fund
  movement, or allocation changes (invariants A/B, [`06`](06_spa_core_invariants.md)). There are no
  write/POST endpoints that move capital; the only writes ever contemplated are internal research
  annotations (IC memo drafts), which are still non-custodial and human-approved.
- Risk Scoring v2 exposed here is **advisory only** — never a gate, never wired to execution
  ([`14_risk_scoring_v2.md`](14_risk_scoring_v2.md)).
- Fail-closed: if the backing store or a feed is stale, the endpoint returns the last-good value **with
  an age/staleness marker**, or `unknown` — never a fabricated number.

---

## 4. Versioning, auth, MVP

- **Versioning.** Additive-only against existing routes; research routes namespaced `/api/yl/`. Breaking
  changes require a new version prefix; a deprecation window is published before any removal.
- **Auth & access.** Keychain-provided key (`SPA_API_KEY`); `SPA_API_REQUIRE_AUTH` gates enforcement.
  Public surfaces expose only L2+ qualified data; internal surfaces (candidates, agent runs, IC memos)
  require auth. Rate limits per surface (`requires verification` for exact limits).
- **MVP prioritization.** MVP-1: Strategies (read over existing research artifacts). MVP 2-3:
  Candidates, Protocols, Stablecoins, Risk, Portfolio, Agents. Later: Reports, Approvals (follow the
  database phases, [`24`](24_database_schema.md) §4).
