# 25 — API Specification (§34)

**Status: STUB.** This document is a Priority-3 placeholder for the *future* Yield Lab research-layer
API surface. It lists the planned endpoint groups and per-group MVP timing only. It does not specify
request/response schemas yet.

**Existing, in-scope-to-preserve API.** A live read-API already exists at
`spa_core/api/server.py` (FastAPI, port 8765, exposed via `api.earn-defi.com`). It serves the public
dashboard and cockpit (e.g. `/api/live/*`, `/api/rates-desk/*`, `/api/refusal`,
`/api/strategy-lab/*`). The planned research-layer endpoints below are **additive**; the existing API
and the public dashboard it feeds **must stay intact** (see `06_spa_core_invariants.md`, invariants
D-13, E). Any auth remains via Keychain-provided keys; no secrets in files.

**Cross-references:** `docs/24_database_schema.md` (backing store), `docs/26_dashboard_specification.md`
(consumer), `docs/23_data_architecture.md` (upstream data).

## Planned contents (outline only)

- **Existing API inventory** — enumerate current `spa_core/api/server.py` routes that stay stable.
- **Planned endpoint groups (each marked MVP-or-later):**
  - Strategies — list / detail / lifecycle status.
  - Candidates — discovery queue, screen results.
  - Protocols — protocol cards, audit/governance status.
  - Stablecoins — stablecoin cards, peg/backing status.
  - Risk — advisory Risk Scoring v2 sub-scores (advisory only, never a gate).
  - Portfolio — allocations, snapshots, capital-tier context.
  - Agents — agent runs, outputs, health.
  - Reports — generated performance/attribution reports.
  - Approvals — IC memos, approval state, decision log.
- **Read-only contract** — research API is read-only / decision-support; never triggers execution,
  signing, or fund movement (invariants A/B).
- **Versioning & stability** — additive-only vs existing routes; deprecation policy.
- **Auth & access** — key handling via Keychain; rate limits; public vs internal surfaces.
- **MVP prioritization** — which groups are MVP-1 vs MVP-2/3 vs later.

TODO: expand at MVP 2-3 stage.
