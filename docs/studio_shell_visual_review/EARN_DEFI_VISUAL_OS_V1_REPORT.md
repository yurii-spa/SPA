# EARN_DEFI_VISUAL_OS_V1_REPORT

One integrated visual operating system — **UNIVERSE + SYSTEM + WHY?** — from the accepted parts.
Read-only; canonical ownership unchanged; no second backend/DB/source-of-truth; no money path.

## A. Delta check
Branch `HEAD` @ `84150c7cb`; `studio_shell/` + read models present; clones unchanged
(`FounderOS-DEMO ad46d77`, `mission-control e28edf8`). No drift/blocker → implemented directly.

## B. FounderOS reuse (UNIVERSE)
Kept the FounderOS-fidelity graph: **d3-force** engine (vendored) + **`vendor/founderos_layout.js`**
(COPY+ADAPT of `lib/tree-layout.ts` `radialRestLayout`/`responsiveRingR`/`edgeArc` + `KnowledgeGraph.tsx`
`hexPts`) — concentric density-weighted rings, **hexagonal** nodes, bowed edges, mono-monochrome canvas +
grid + construction rings, Lens/Directory, focus **re-layout**, zoom/pan.

## C. Mission Control reuse (SYSTEM)  — concrete COPY+ADAPT
`studio_shell/syswhy.js::renderSystem` reproduces two real MC presentation patterns onto our design +
real data:
- **`src/components/layout/live-feed.tsx`** → **ЖИВАЯ ЛЕНТА / LIVE FEED**: pulsing-dot header + count +
  timestamped rows with per-item status dot (bound to `read_model.activity` = real ledger transitions).
- **`src/components/dashboard/widgets/fleet-status-widget.tsx`** → **РАБОТА / WORK** status rows
  (label + count + colored dot) and the EXECUTION/HEALTH panels.
Classification: **MISSION_CONTROL_ADAPTED** (presentation patterns lifted; their Tailwind classes, Zustand
store, SQLite backend and data NOT imported — those are backend-coupled). No control plane imported.

## D. Optimal Engine concept use (WHY)
`Bennettxai/OptimalEngine` (MIT, Elixir backend) is **not** run/linked. Its **concept**
`source → evidence → fact → rule/gate → decision → result` shapes the WHY trace model only
(**OPTIMAL_ENGINE_CONCEPT**). No second memory authority / knowledge DB.

## E. Architecture
`Investment Engine + Studio OS canonical state → safe read interfaces → derived UI read model
(read_model.json / universe.json / why_aave.json) → UI adapter → {UNIVERSE, SYSTEM, WHY}`. UI is a
projection; each entity carries `provenance`. Graph ≠ workflow engine; MC ≠ control plane; OptimalEngine ≠ backend.

## F. Data sources (read-only, real)
`data/adapter_status.json` (protocol APY/TVL/live), `chains_status.json`, `risk_alerts.json`,
`golive_status.json`, `capital_config.json` (PAPER), `mission-state/v04/ledger.json`, `agent_registry.json`
→ `universe.json` (27/26) + `read_model.json` (SYSTEM) + `why_aave.json` (11/11, `trace_partial=true`).

## G. UNIVERSE
FounderOS-fidelity hex/ring graph; center EARN DEFI → domains (OPPORTUNITIES/FACTORY/CAPITAL/RISK/SYSTEM);
click domain → real **re-layout** (children spread, others recede); click Aave V3 → Lens inspector with
real APY 3.5% **UNEVIDENCED**, TVL $12.0B **static**, **STALE**, provenance; chips + directory; zoom/pan; RU/EN.

## H. SYSTEM
Split: system topology graph (left) + MC-adapted operational column (right): **WORK** (owner-wait 5 /
failed 2 / done 10 …), **EXECUTION** (dispatch CLOSED, provider/candidate planes), **HEALTH** (GoLive
27/29·STALE, alerts 17, fleet 71/80·STALE), **LIVE FEED** (real ledger transitions). Honest `NOT MEASURED`
where no source. Mobile: panels prioritized under a compact topology.

## I. WHY?
Real deterministic decision trace for **Aave V3**: `adapter_status` → APY/TVL evidence (UNEVIDENCED) →
facts → **RiskPolicy gates** (APY band 1–30% PASS; **TVL floor $5M live** UNEVIDENCED per ADR-053 as
tvl_source=static) → **RiskPolicy decision** (UNEVIDENCED, fail-CLOSED) → **Not in live allocation (PAPER)**.
**Deterministic gate = red square; LLM = violet dashed hex, ABSENT** (invariant #3 — no LLM authority over
capital); banner **TRACE PARTIAL** with the exact missing segment. No fabricated edges.

## J. Mobile (390px)
UNIVERSE (domains + focus + bottom-sheet), SYSTEM (compact graph + stacked operational panels + live feed),
WHY (vertical trace + bottom-sheet). Header fits; no page horizontal scroll. **Gap:** long HEALTH values can
truncate at the panel edge; UNIVERSE mobile still shows children (domains-only default not yet enforced).

## K. RU/EN
All three surfaces + chips, directory, panels, live feed, WHY banner/legend switch (`02` RU vs `03` EN).
Technical identifiers (`wi-…`, protocol names, PROVIDER/CANDIDATE, ADR) stay verbatim.

## L. Tests
`build_read_model.py` / `build_universe_graph.py` / `build_why.py` run clean; `test_read_model.py` 9/9;
all three surfaces render under headless Chrome (10 screenshots). *Gap:* no dedicated graph/why projector unit test yet.

## M. Provenance
d3-force = FOUNDEROS_DIRECT_REUSE (vendored, ISC/BSD). founderos_layout.js = FOUNDEROS_ADAPTED
(`ad46d77`, tree-layout.ts + KnowledgeGraph.tsx, MIT, headers cite it). syswhy.js SYSTEM panels =
MISSION_CONTROL_ADAPTED (`e28edf8`, live-feed.tsx + fleet-status-widget.tsx, MIT). WHY model =
OPTIMAL_ENGINE_CONCEPT + NEW_GLUE. Data binding = EXISTING_SPA. Clones in git-ignored `reference/`.

## N. Remaining gaps
1. Mobile UNIVERSE domains-only default + HEALTH value wrap.
2. UNIVERSE composition leans to the opportunities-heavy sector.
3. WHY inspector actions and cross-surface deep-links (Universe↔Why for same entity) not fully wired.
4. Projector unit tests for universe/why.

## O. Exact files changed / added
Added: `studio_shell/build_why.py`, `studio_shell/why_aave.json`, `studio_shell/syswhy.js`,
`studio_shell/vendor/founderos_layout.js`, `studio_shell/build_universe_graph.py`, `studio_shell/universe.json`.
Modified: `studio_shell/graph.html`, `studio_shell/graph.js` (nav UNIVERSE/SYSTEM/WHY, fetch read_model+why,
mode routing, SYSTEM panels, WHY trace + inspector). `docs/journal/2026-W39.md`. No canonical/backend/money-path.

## P. Local URL
`python3 -m http.server 8899 --bind 127.0.0.1 -d studio_shell` → `http://127.0.0.1:8899/graph.html`
(`?mode=universe|system|why&lang=ru|en`). Rebuild data: `python3 studio_shell/build_{read_model,universe_graph,why}.py`.

## Q. Screenshot paths (`docs/studio_shell_visual_review/`)
`01_FOUNDEROS_ORIGINAL.png` · `02_EARN_DEFI_UNIVERSE_RU.png` · `03_EARN_DEFI_UNIVERSE_EN.png` ·
`04_EARN_DEFI_OPPORTUNITY_FOCUS.png` · `05_EARN_DEFI_SYSTEM.png` · `06_EARN_DEFI_WHY.png` ·
`07_EARN_DEFI_WIDE.png` · `08_EARN_DEFI_MOBILE_UNIVERSE.png` · `09_EARN_DEFI_MOBILE_SYSTEM.png` ·
`10_EARN_DEFI_MOBILE_WHY.png`.
