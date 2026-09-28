# FOUNDEROS_FIDELITY_PASS_REPORT

This pass started **from the actual FounderOS `/brain` implementation** (cloned, MIT) and adapted its
visual system onto Earn DeFi's real data — not a from-scratch lookalike. Read-only; UI ≠ canonical.

## A. Actual FounderOS files inspected (`Bennettxai/FounderOS-DEMO` @ `ad46d772…`)
- `app/brain/page.tsx` (route/composition), `components/BrainGraphView.tsx`, `components/KnowledgeGraph.tsx`
  (2,858 lines — node/edge/background render, `hexPts`, `CAT` tier radii, `EDGE_COLOR`, `TIER_OPACITY`).
- `lib/tree-layout.ts` — `radialRestLayout`, `responsiveRingR` (`RING_FRAC=[0,105/600,152/600,200/600,248/600]`,
  `SECTOR_FILL=0.84`), `edgeArc`, `branchPath`, `branchWidth`, `round2`.
- `lib/graph-lens.ts` (lens/focus), `lib/kg-colors.ts` (themed palette — "black & white OS, colour is a
  rare accent"), `app/globals.css` (mono theme tokens, `--ease: cubic-bezier(.32,.72,0,1)`).

## B. Direct reuse
- **d3-force** engine (vendored self-contained, ISC/BSD) — `studio_shell/vendor/{d3-force,d3-quadtree,d3-dispatch,d3-timer}.js`.

## C. Adapted code (COPY + ADAPT, provenance in file headers)
- **`studio_shell/vendor/founderos_layout.js`** — `radialRestLayout` (concentric density-weighted rings),
  `responsiveRingR`, `hexPts` (hex nodes), `edgeArc` (bowed edges), `branchWidth`, `round2` — ported
  **verbatim in behaviour** from `lib/tree-layout.ts` + `KnowledgeGraph.tsx` (TS → ESM, types stripped,
  `pillars` generalized). Header cites repo/commit/files/license.
- **`studio_shell/graph.js` / `graph.html`** — reproduce FounderOS's visual system: near-monochrome
  canvas + faint grid + **concentric construction rings + radial spokes**; small **hex** nodes, thin
  strokes, restrained stroke-only accents, subtle glow on hubs; **mono uppercase** typography; top
  mode-switch + **filter chips**; right **DIRECTORY/lens** (real counts + tracks legend); premium **lens
  inspector**; **domain focus re-layout** (focused domain spreads children on a wide arc, others recede);
  zoom/pan; RU/EN.

## D. Rejected components (measured reason)
- `KnowledgeGraph.tsx` **wholesale** (2,858 lines, ~20 internal deps: brain-store/departments/agents/
  memory-core/personnel) — domain-entangled, not liftable. Extracted the **presentation layer** (the pure
  layout math + node/edge/ring idioms) and preserved behaviour; the React component + its data model were not copied.
- `NeuralGraph.tsx` (feedforward view), `PersonaBrainGraph.tsx`, `brain-constellation`/`memory-core` — FounderOS-domain-specific; not this pass.

## E. Before vs after
- **Before:** big saturated filled circles, straight edges, random float, empty dark bg → "d3-force demo".
- **After:** small hex nodes, thin bowed edges, concentric rings + grid + spokes, mono monochrome, lens +
  directory, focus re-layout → the FounderOS `/brain` **class of interface**, now Earn DeFi.

## F. UI screenshots (`docs/studio_shell_visual_review/`)
`FOUNDEROS_ORIGINAL.png` · `EARN_DEFI_FIDELITY_UNIVERSE.png` · `EARN_DEFI_FIDELITY_OPPORTUNITIES_FOCUS.png`
· `EARN_DEFI_FIDELITY_AAVE_FOCUS.png` · `EARN_DEFI_FIDELITY_SYSTEM.png` · `EARN_DEFI_FIDELITY_WIDE.png` ·
`EARN_DEFI_FIDELITY_MOBILE.png` · `EARN_DEFI_FIDELITY_UNIVERSE_EN.png`.

## G. Graph interaction evidence
Click a domain → **re-layout** (children spread, others recede) + inspector (`OPPORTUNITIES_FOCUS`). Click a
leaf (`AAVE_FOCUS`) → neighbours lit, rest dimmed, **lens inspector** with real metrics + evidence + provenance.
Chips/directory focus domains. Reset returns to Universe. Zoom/pan on the canvas.

## H. Desktop verification
1440×900 + 1920×1080 captured. Meets the bar: FounderOS-derived visual system, structured grid/radial
background, radial hierarchy, no overlapping labels (leaf labels revealed only on focus), restrained hex
nodes, mono typography, bowed edges, focus re-layout, zoom/pan, real data, honest states, lens inspector,
directory, RU/EN.

## I. Mobile verification
390px captured (`EARN_DEFI_FIDELITY_MOBILE.png`): graph + construction rings + **bottom-sheet** inspector;
track distinction by shape (PAPER dashed, UNKNOWN dotted). **Gap:** domain-hub labels collide at phone
scale — mobile should default to **domains-only** (tap → children). Flagged, not yet done (desktop was the priority).

## J. RU/EN verification
`EARN_DEFI_FIDELITY_UNIVERSE.png` (RU) vs `EARN_DEFI_FIDELITY_UNIVERSE_EN.png` (EN): nav, chips, directory,
inspector, tracks, legend all switch; technical identifiers (TASK/`op:*`, protocol names) stay verbatim.

## K. Real data sources (read-only)
`data/adapter_status.json` (protocol APY/TVL/live), `chains_status.json`, `risk_alerts.json`,
`golive_status.json`, `capital_config.json` (PAPER), `mission-state/v04/ledger.json`, `agent_registry.json`
→ `studio_shell/universe.json` (27 nodes/26 edges), each node provenanced + freshness + track.

## L. License / provenance
FounderOS MIT (© 2026 FounderOS) — attribution kept in `founderos_layout.js` + `graph.js` headers
(repo, commit `ad46d772`, source files, COPY+ADAPT). d3-force ISC/BSD (vendor/PROVENANCE.md). Clones live in
git-ignored `reference/` (not production).

## M. Remaining visual gaps (honest)
1. **Mobile** should default to **domains-only**; current phone view shows full graph → hub-label collision.
2. **Composition centering** — the opportunities-heavy sector pulls mass toward one arc (density weighting);
   could balance sector angles or recenter.
3. **Construction rings** are faint — could be a touch stronger for the "technical canvas" feel.
4. Inspector `WHY?/Evidence/Open` are present but **not yet wired** to a decision-trace view.
None change the class of interface; all are refinements on an already FounderOS-grade desktop.

## N. Recommended next step
Mobile domains-only model (tap domain → children, bottom-sheet) — the single highest-value refinement —
then wire `WHY?` to a decision-trace lens. No backend/realtime/money-path.
