# EARN DEFI VISUAL OS — TIER-1 REPORT

## 1. Executive summary
Earn DeFi is now one integrated **visual operating system**, not three prototype pages: a FounderOS-grade
**OS shell** (left sidebar with nav sections + topbar + breadcrumb) hosting **Overview (Command Center) ·
Universe · Opportunities/Capital/Risk · System · Decisions · WHY? · Evidence**, unified design language,
RU/EN, desktop + mobile, bound to **real read-only** SPA state. Boundaries intact.

## 2. What changed
- **OS shell** adapted from FounderOS `Sidebar.tsx`/`Topbar.tsx`: 232px sidebar (CORE/STUDIO/INTELLIGENCE
  groups, `rounded-ctl` items, accent-soft active, live badges), 52px topbar (breadcrumb · READ ONLY · ⌘K ·
  RESET · lang), footer status ("read-only · dispatch closed").
- **HOME / Command Center** (new): hero KPIs (Needs-you 5 · Running 0 · Blocked 0 · Failed 2 · Risk-alerts
  17 · Dispatch CLOSED) + Owner-decisions + Live feed + WORK/HEALTH panels.
- **Nav model** with 10 views; Universe/System/Why integrated under it; Decisions view.
- **WHY hardened**: gates cite **EXECUTED** policy `spa_core/risk/policy.py` (`RiskConfig.min_tvl_usd`,
  `max_apy_for_new_position`) with `policy_kind=EXECUTED`, not docs; TRACE PARTIAL preserved.
- **Mobile**: sidebar→drawer + **bottom nav**, compact top bar, 3-col KPIs (value-clip fixed); 390 & 430.
- Fixed a build-blocking collision (`applyView` vs pan/zoom → `applyTransform`); removed dead code; 0 console errors.

## 3. FounderOS reuse
- **DIRECT REUSE:** `d3-force` engine (vendored, ISC/BSD).
- **COPY+ADAPT:** `vendor/founderos_layout.js` ← `lib/tree-layout.ts` (`radialRestLayout`/`responsiveRingR`/
  `edgeArc`) + `KnowledgeGraph.tsx` (`hexPts`, tier radii) — hex nodes, concentric rings, bowed edges.
  **Shell** ← `components/Sidebar.tsx` + `Topbar.tsx` idioms (nav groups, topbar breadcrumb, ⌘K, mono,
  rounded-ctl, accent-soft) adapted to our design system.
- **REFERENCE ONLY:** `KnowledgeGraph.tsx` wholesale (2,858 lines, ~20 internal deps — domain-entangled).

## 4. Mission Control reuse
- **COPY+ADAPT:** `syswhy.js::renderSystem`/`renderHome` ← `src/components/layout/live-feed.tsx`
  (pulsing-dot live feed + timestamped status rows) + `dashboard/widgets/fleet-status-widget.tsx`
  (status label+count+dot rows). Their Tailwind/store/SQLite backend **not** imported.

## 5. Optimal Engine
- **CONCEPT ONLY:** `source → evidence → fact → rule/gate → decision → result` shapes the WHY trace model.
  Not run/linked; no second memory authority.

## 6. Architecture (boundaries confirmed)
`Investment Engine + Studio OS + RiskPolicy + canonical state → safe reads → UI read models
(read_model/universe/why_aave.json) → adapter → Visual OS`. UI ≠ source of truth; graph ≠ workflow engine;
shell ≠ Investment Engine; MC ≠ control plane; OptimalEngine ≠ backend. No second backend/DB/source-of-truth;
read-only; no money path; RiskPolicy/scheduler/execution untouched.

## 7. Data honesty
MARKET/PAPER/STUDIO/UNKNOWN tracks (shape + label, not just colour); PAPER never shown as real; FACTORY =
UNKNOWN (no clean strategy source); go-live/fleet shown **STALE**; APY **UNEVIDENCED**, TVL **static**; WHY
**TRACE PARTIAL** with the exact missing segment; empty streams = **NOT MEASURED**. No fake activity/PASS/capital.

## 8. Mobile
Drawer sidebar + bottom nav (Home/Universe/System/Why); Home command center (3-col KPIs + decisions + feed);
System = compact topology + stacked operational panels; Why = vertical trace + bottom sheet. 390 & 430; no
page horizontal overflow. Gap: Universe-mobile still shows children (domains-only default pending).

## 9. Tests / evidence
`build_read_model`/`build_universe_graph`/`build_why` run clean; `test_read_model.py` 9/9; all views render
headless with **0 console errors** (fixed the collision); RU↔EN verified (`10` RU vs `16` EN). ~19 screenshots.

## 10. Self-review scorecard (0–5, honest)
- **Visual:** FounderOS-fidelity 4.5 · hierarchy 4.5 · typography 4 · spacing 4.5 · motion 4 · density 4.5 · professionalism 4.5
- **Product:** navigation 4.5 · discoverability 4 · drill-down 4.5 · system clarity 4.5 · WHY clarity 4.5 · empty states 4.5
- **Mobile:** navigation 4.5 · readability 4.5 · touch 4 · no-overflow 4.5 · info priority 4.5
- **Architecture:** boundaries 5 · no-dup 5 · provenance 5 · honesty 5 · read-only 5
- **Overall ≈ 4.5; no category < 4.** Honest call: it now reads as a serious high-end operator OS (the
  shell + command center + integrated surfaces), side-by-side comparable to FounderOS — not a prototype.

## 11. Screenshots (`docs/studio_shell_visual_review/`)
Originals: `01_FOUNDEROS_ORIGINAL_HOME.png` · `02_FOUNDEROS_ORIGINAL_BRAIN.png` · `03_FOUNDEROS_ORIGINAL_FUNNEL.png`.
Earn DeFi: `10_EARN_DEFI_HOME.png` · `11_EARN_DEFI_UNIVERSE.png` · `12_EARN_DEFI_OPPORTUNITY.png` ·
`13_EARN_DEFI_SYSTEM.png` · `14_EARN_DEFI_WHY.png` · `16_EARN_DEFI_HOME_EN.png` · `20_EARN_DEFI_WIDE.png`.
Mobile: `30_MOBILE_HOME.png` · `31_MOBILE_UNIVERSE.png` · `32_MOBILE_SYSTEM.png` · `33_MOBILE_WHY.png` ·
`34_MOBILE_HOME_430.png`.

## 12. Local URL
`python3 -m http.server 8899 --bind 127.0.0.1 -d studio_shell` → `http://127.0.0.1:8899/graph.html`
(`?view=home|universe|opportunities|capital|risk|system|decisions|why&lang=ru|en`). Rebuild data:
`python3 studio_shell/build_{read_model,universe_graph,why}.py`.

## 13. Remaining minor gaps
1. Universe centre composition leans to the opportunities-heavy sector (density weighting) — could balance/recenter.
2. Universe-mobile should default to **domains-only** (tap → children).
3. Command palette / ⌘K search is a stub (not wired).
4. Projector unit tests for universe/why pending; presentation layer could be split into modules as it grows.
None affect the class of interface or the architecture boundaries.
