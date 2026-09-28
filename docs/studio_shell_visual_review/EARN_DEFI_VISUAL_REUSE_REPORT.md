# EARN DEFI — VISUAL REUSE REPORT (FounderOS graph → real Earn DeFi data)

Reuse-first: audited the real repos, **ran the FounderOS original**, reused the actual graph
**engine**, and bound it to **real read-only SPA data**. No fabricated activity, no second source
of truth, no money-path change, UI ≠ canonical.

## A. CURRENT SPA (OBSERVED / DERIVED / MISSING)
- **OBSERVED** (read-only canonical/derived): deterministic RiskPolicy v1.0 (`spa_core/risk/policy.py`,
  invariants in CLAUDE.md); `ADAPTER_REGISTRY` = 36; **real market data** `data/adapter_status.json`
  (per-protocol `apy/live_apy/live_apy_fresh/tvl_usd/tvl_source`), `data/chains_status.json`;
  `data/risk_alerts.json`; `data/golive_status.json` (27/29, blockers, **STALE**); mission ledger
  `~/studio-os-scratch/mission-state/v04/ledger.json` (missions/items, `mission_dispatch_disabled` =
  CLOSED); `data/agent_registry.json` (fleet snapshot, **STALE**); provider/candidate planes (logs).
- **DERIVED** (mine, this + prior): `read_model.json` (cockpit), **`universe.json`** (27 nodes/26 edges).
- **MISSING / not-a-clean-read-source**: an investor-facing **strategy lifecycle** projection (FACTORY
  shown `UNKNOWN`); a stable **Capital positions** read source (only PAPER capital — shown `PAPER`);
  `telegram_bot_capabilities.json` / `code_sync_status.json` (absent). Surfaced honestly, not faked.

## B. EXTERNAL REPOS (cloned to `reference/`, out of production; SHAs recorded)
| Repo | SHA | License | Role |
|---|---|---|---|
| `Bennettxai/FounderOS-DEMO` | `ad46d772744ce93e898a203526e2a2967e583205` | **MIT** | visual graph base |
| `builderz-labs/mission-control` | `e28edf8b28c85a32f1fd55ac577d325df6b16e4a` | **MIT** | operational UX (reagraph WebGL, SSE/poll) |
| `Bennettxai/OptimalEngine` | (identified) | **MIT** | Elixir "second-brain" backend — **rejected** (would be a second source of truth) |

`OPTIMAL_ENGINE_IDENTIFIED=YES` — `Bennettxai/OptimalEngine` (MIT, Elixir): the brain **backend**
(topology/memory/retrieval), **not** the graph UI; not reused (SPA stays canonical).

## C. FOUNDEROS MATCH — YES (verified by running it)
Installed (isolated npm cache — the global cache was corrupted), **seeded** (32 agents / 34 tools /
22 roadmap), ran `next dev`. The dynamic graph is at **`/brain`** (`app/brain/page.tsx` → `BrainGraphView`
→ `KnowledgeGraph.tsx`): a **RADIAL / NEURAL** d3-force graph with lens filters (Entity/Function/Action),
legend, directory — the premium operator console the demo shows. Screenshot: `FOUNDEROS_ORIGINAL.png`
(the demo graph is sparse because its brain-store markdown isn't mounted — "brain-store not mounted" —
but the engine + UX are present and confirmed).

## D. REUSE (direct)
- **`d3-force` v3.0.0** — the exact physics engine `FounderOS KnowledgeGraph.tsx` uses. Vendored,
  **self-contained** (4 local ESM files: d3-force + d3-quadtree + d3-dispatch + d3-timer; ISC/BSD-3,
  permissive), no build step, offline-safe → `studio_shell/vendor/` (+ `PROVENANCE.md`).

## E. ADAPT (patterns, with provenance)
- FounderOS `components/KnowledgeGraph.tsx` + `lib/graph-lens.ts` **interaction patterns**: radial force
  config (`forceManyBody`+`forceLink`+`forceCollide`+`forceCenter`+`forceX/Y`), **click-to-focus dim**
  (lens), zoom/pan, **SVG render**. Adapted into `studio_shell/graph.js` (header cites the source).

## F. REJECT (measured reasons)
- FounderOS `KnowledgeGraph.tsx` **wholesale** — 2,858 lines, ~20 internal deps (brain-store,
  departments, agents, memory-core) — domain-entangled, not liftable. Reuse the **engine + patterns**, not the component.
- `OptimalEngine` — Elixir backend = a second source of truth (violates the boundary).
- `mission-control` **reagraph** (WebGL) — heavier dep; deferred as SYSTEM/operational **reference** for later.
- `openclawfice` — AGPL-3.0 + not a graph engine (prior audit `VISUAL_REUSE_AUDIT_REPORT.md`).

## G. IMPLEMENTATION (files added)
`studio_shell/build_universe_graph.py` (projector) · `studio_shell/universe.json` (derived) ·
`studio_shell/graph.html` · `studio_shell/graph.js` (d3-force graph) ·
`studio_shell/vendor/{d3-force,d3-quadtree,d3-dispatch,d3-timer}.js` + `vendor/PROVENANCE.md` ·
`reference/` (clones, git-ignored). No canonical/backend/money-path files touched.

## H. DATA (real, read-only)
`data/adapter_status.json`, `data/chains_status.json`, `data/risk_alerts.json`,
`data/golive_status.json`, `data/capital_config.json` (PAPER), `mission-state/v04/ledger.json`,
`data/agent_registry.json`. Each node carries `provenance` = canonical source; freshness labelled.

## I. UI (works)
UNIVERSE force-graph (zoom/pan, **focus+dim**, drill-down), **SYSTEM** mode (filtered to infra),
**Opportunity drill-down** (click a protocol → real APY/TVL + evidenced/unevidenced + provenance),
RU/EN switch, tracks MARKET/PAPER/STUDIO/UNKNOWN visually distinct. Local URL:
`http://127.0.0.1:8899/graph.html` (via `python3 -m http.server` in `studio_shell/`, loopback).

## J. MOBILE
Verified at **390px** (`STUDIO_reuse_mobile_universe_ru.png`): graph + **bottom-sheet** drill-down,
mobile top bar, no horizontal overflow. Bottom-sheet is the mobile detail model (not a clipped panel).

## K. MOCKS
**None** in the graph — all nodes are real. Honest absences: FACTORY = `UNKNOWN` (no clean strategy
read source); CAPITAL = `PAPER`; provider/candidate live state = "needs privileged probe". No fake agents/activity.

## L. TESTS
`studio_shell/test_read_model.py` 9/9 (prior); `build_universe_graph.py` runs clean (27/26); graph
renders under headless Chrome (6 screenshots). *Gap:* no dedicated graph-projector unit test yet (→ Next).

## M. RISKS
Keep UI ≠ canon (done: provenance + read-only); graph must not become a workflow engine (it only
renders); Investment-Engine boundary held (CAPITAL = PAPER, zero actions); vendored d3-force pinned +
provenanced. Full-component FounderOS reuse rejected (entangled) — engine+pattern reuse is the correct grain.

## N. PROVENANCE (per component)
- d3-force engine → **FOUNDEROS-ALIGNED DIRECT REUSE** (vendored ISC/BSD).
- radial-force + focus-dim + zoom patterns → **FOUNDEROS_ADAPTED** (`KnowledgeGraph.tsx`, `graph-lens.ts`, MIT).
- Earn DeFi domain model + real-data binding → **NEW_GLUE** + **EXISTING_SPA**.
- SYSTEM/operational patterns → **MISSION_CONTROL** (reference; reagraph deferred).

## O. NEXT (small, recommended)
1. Densify UNIVERSE layout toward FounderOS's **RADIAL rings per domain** + lens filters (Entity/Function/Action → domain/track/status).
2. Enrich **SYSTEM** with Mission-Control activity/detail patterns (still read-only).
3. **Position Passport** as a read-model/UI projection (ADR-gated): classify each field
   AVAILABLE/DERIVABLE/PARTIAL/MISSING with `canonical source → field` provenance; no new persisted entity.
4. Mount this graph as the **Studio View** inside the Shell (behind the existing seam), replacing the flat/isometric v0.
5. Add a graph-projector contract test (shape + provenance + no-secret + honest tracks).
