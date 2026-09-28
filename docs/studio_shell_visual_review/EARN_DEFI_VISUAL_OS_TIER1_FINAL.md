# EARN DEFI VISUAL OS — TIER-1 FINAL (punch-list corrections)

Fixed ONLY the ARB-named blockers (2 internal passes). No redesign, no new features, no repo search,
no architecture/backend/money-path change. All success conditions verified visually + programmatically.

## Blockers fixed
1. **Desktop Universe — label collisions:** deterministic **radial label anchoring** (hub labels pushed
   outward along their radius; centre EARN DEFI protected). **Root cause also fixed:** the `chains` node
   was a *second* hub in the `opportunities` domain → it floated to the centre with a duplicate
   "ВОЗМОЖНОСТИ" label overlapping EARN DEFI. Now only the **primary** domain hub is a hub; secondary hubs
   are positioned leaf nodes. Verified clean at **1440×900 and 1920×1080**.
2. **Desktop Universe — composition:** replaced density-weighting with an **equal-angle radial layout**
   (5 domains symmetric around a central EARN DEFI), canvas-filling (scale 1.34 desktop). Intentional,
   balanced; no fake nodes.
3. **Mobile Universe — domains-only:** default renders **EARN DEFI + 5 domain hexes only** (no leaves, no
   directory, no filter chips). Tap a domain → focus into it → its children appear; root/back → domains.
4. **Mobile WHY — vertical trace:** replaced the wide graph with a **vertical causal trace** — grouped
   stages Object → Source → Evidence{APY,TVL} → Facts{APY,TVL} → **Deterministic Gates**{APY band, TVL floor}
   → RiskPolicy Decision → Result, with a single TRACE-PARTIAL banner. **LLM** appears as a side-status
   ("LLM · NO AUTHORITY · ABSENT"). Tap a row → detail sheet. Gates = red squares, decision = diamond.
5. **Mobile global overflow:** programmatic check `document.documentElement.scrollWidth <= innerWidth`
   = **true** for home/universe/system/why at **390 and 430**. Long text wraps/ellipsis; redundant top
   READ-ONLY chip hidden on mobile.
6. **Mobile bottom nav:** exactly **4 items** — Overview · Universe · System · Why? (DOM-verified: 4
   buttons); all fit, no clipped 5th, no horizontal scroll.
7. **⌘K:** the dead stub button was **removed** (per option B).

## Verification (not trusting CSS)
- **Programmatic overflow:** ok=true for {home, universe, system, why} × {390, 430}.
- **Console:** 0 SyntaxError/TypeError across views (fixed an earlier `applyView` collision).
- **Visual inspection** of every FINAL_* screenshot (desktop 1440/1920 + mobile 390/430).

## Not regressed
HOME (command center), SYSTEM (MC-adapted panels), WHY (desktop trace) desktop quality intact; RU/EN both
work (`FINAL_HOME.png` RU vs `FINAL_HOME_EN.png` EN). Architecture boundaries unchanged: UI ≠ source of truth,
graph ≠ workflow engine, no 2nd backend/DB, read-only, no money path, RiskPolicy untouched. Real data only;
honest UNKNOWN/STALE/PARTIAL.

## Screenshots (`docs/studio_shell_visual_review/`)
Desktop: `FINAL_HOME.png` · `FINAL_HOME_EN.png` · `FINAL_UNIVERSE.png` · `FINAL_OPPORTUNITY.png` ·
`FINAL_SYSTEM.png` · `FINAL_WHY.png` · `FINAL_WIDE.png`.
Mobile 390: `FINAL_MOBILE_HOME.png` · `FINAL_MOBILE_UNIVERSE.png` · `FINAL_MOBILE_UNIVERSE_FOCUS.png` ·
`FINAL_MOBILE_SYSTEM.png` · `FINAL_MOBILE_WHY.png`.
Mobile 430: `FINAL_MOBILE_HOME_430.png` · `FINAL_MOBILE_UNIVERSE_430.png`.
Baselines: `01_FOUNDEROS_ORIGINAL_HOME.png` · `02_FOUNDEROS_ORIGINAL_BRAIN.png` · `03_FOUNDEROS_ORIGINAL_FUNNEL.png`.

## Local URL
`python3 -m http.server 8899 --bind 127.0.0.1 -d studio_shell` → `http://127.0.0.1:8899/graph.html`
(`?view=home|universe|opportunities|capital|risk|system|decisions|why&lang=ru|en`).

## Files changed
`studio_shell/graph.js` (equal-angle layout, radial label anchoring, primary-hub rule, mobile domains-only,
overflow hook, removed dead alias/import), `studio_shell/graph.html` (removed ⌘K, mobile overflow guards +
WHY-mobile styles + bottom-nav sizing + banner fix), `studio_shell/syswhy.js` (mobile vertical WHY renderer),
`studio_shell/build_why.py` (EXECUTED-policy provenance). `docs/journal/2026-W39.md`.

## Remaining (cosmetic, non-blocking)
Universe still reads slightly opportunities-weighted (its sector has the most children — honest, not a defect);
right-edge domain label sits close to the mobile viewport edge but within it.
