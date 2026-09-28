# Studio OS Shell v0 — Visual Review Package

Prepared for Owner + ARB visual review. **Every screenshot is the REAL current v0**, rendered
from the **current real read model** (`studio_shell/read_model.json`, rebuilt at capture time) via
headless Chrome against the actual Shell code. No screenshot was beautified, no task/agent was
fabricated, and stale/unknown states are left visible. No code was changed to improve the shots.

- Captured: 2026-09-27. Read model at capture: 2 missions · 12 work items (10 done / 2 failed) ·
  5 owner decisions · dispatch **CLOSED** (ARB §H) · go-live shown **STALE**.
- Capture method: `studio_shell/build_snapshot.py` (self-contained offline build of the same app)
  → headless Chrome `--screenshot` at device-scale 2. Task-detail shots invoke the app's **real**
  `openTask()` on a **real** work item (a failed one) — same drill-down a click produces.

## Screenshots

| # | File | View |
|---|---|---|
| 1 | `01_desktop_ru_overview.png` | Desktop RU — Overview |
| 2 | `02_desktop_ru_work.png` | Desktop RU — Work |
| 3 | `03_desktop_ru_studio.png` | Desktop RU — Studio View |
| 4 | `04_desktop_ru_task_detail.png` | Desktop RU — Task Detail open (real failed work item + provenance) |
| 5 | `05_desktop_ru_decisions.png` | Desktop RU — Decisions (5 real owner cards, read-only) |
| 6 | `06_mobile_ru_home_overview.png` | Mobile RU — Owner/Home (Overview) |
| 7 | `07_mobile_ru_studio.png` | Mobile RU — Studio View |
| 8 | `08_mobile_ru_task_detail.png` | Mobile RU — Task Detail open |
| 9 | `09_desktop_en_overview.png` | Desktop EN — Overview |
| 10 | `10_desktop_en_studio.png` | Desktop EN — Studio View |
| 11 | `11_wide_ru_studio.png` | Wide (1920×1080) RU — Studio View, for visual evaluation |

## Known v0 issue visible in the package (not patched — surfaced honestly)

- **Mobile Task Detail (`08`) — right-aligned values clip off-screen** (long mono ids, reason
  code, provenance). Real responsive defect in the drawer's `space-between` rows at 390 px. Left
  as-is for this review; it is a small CSS fix (stack key/value vertically on mobile), queued, not
  done here to honor "don't change code to make the screenshots look better."

## A. From the old Director OS prototype (`spa_director_os_prototype_v2.html`)

- The **dark premium visual language** and **CSS design tokens** (`--bg / --brand / --green /
  --yellow / --red / --cyan / --radius`) — adapted, not copied.
- **Sidebar + content-grid** desktop layout; **section taxonomy** (Overview / Work / Decisions /
  Roles / System); **owner-focused Russian** framing; **read-only / safe-mode** posture;
  **green/yellow/red** zone semantics.

## B. Ideas from `builderz-labs/mission-control` (concepts only, no code)

- **Task pipeline** with normalized states + **drill-down** to a detail view.
- **Owner decisions / approval-gate** concept (we render it **read-only** in v0).
- **System/observability drill-down** and **cost/plan** surfacing (we show plan + $/cycle).
- **Command-center** framing and the **smart-poll** idea (we poll the rebuilt projection).
- Confirmation that a **2D DOM/CSS** "office" is a legitimate premium approach (their office is 2D).

## C. Ideas from `glglak/agent-mission-control` (concepts only, no code)

- The **living-studio metaphor**: agents as **tokens placed in zones**, **animated by state**,
  moving between areas as work transitions.
- The **zone/room model** and **state-derived placement** (their `detectZone` → our documented
  UI-state→zone map).
- **Replay** of recent activity (noted as a future idea; not in v0).
- We reused none of its code (no LICENSE file; monolithic renderer; its 3D is dead code).

## D. Original to our Studio OS

- A **stdlib canonical read-model projector** with **per-entity provenance** (`source` back to
  `ledger.json` / cards / architecture files) — the UI is a **projection, never a source of truth**.
- **Honest freshness** surfaced in the UI (LIVE / RECENT / STALE / UNKNOWN); e.g. go-live shows
  **STALE** rather than pretending to be current.
- Studio zones/agents bound to the **real mission ledger** (not a telemetry stream), incl.
  **dispatch-CLOSED** and **permission-zone** surfacing; empty zones say "empty" (no fabrication).
- **First-class RU/EN** i18n; **loopback-only, no-secret** posture; a **shared task entity**
  reachable identically from Mission Control and Studio View; a **no-build** implementation.

## E. What is currently 2D / 2.5D

- **Everything is DOM/CSS.** Studio View = flat zone panels + rounded agent tokens with light CSS
  transitions (pop-in, a running pulse), subtle depth from gradients/borders/shadows. There is
  **no true depth, no camera, no volumetric lighting, no parallax, no 3D geometry**. It is a
  spatial *metaphor* rendered in 2.5D.

## F. What would need to change for a more volumetric / premium / true-3D Studio View

- A **real renderer + scene graph** (Three.js / React-Three-Fiber, or PixiJS for 2.5D-with-depth).
- **3D zone geometry** (floor, desks, walls), **camera** (orbit/pan/zoom), **materials/lighting**
  (glass/metal/soft light), **agent meshes/sprites** with **pathfinding** desk-to-desk, **instancing
  + LOD**, and an **asset pipeline** (models/textures).
- An **animation system driven by the SAME state** (our read model / future event stream) so the
  scene stays a faithful reflection of canon — not decorative.
- **Performance budgets**: FPS targets, device tiers, visibility culling, pause-on-hidden, capped DPR.
- **Crucially, only the RENDERER changes** — the read model, provenance, freshness, and the
  state→zone/agent mapping are already isolated and would be reused unchanged.

## G. Can Mission Control stay normal DOM while a separate Three.js / R3F renderer mounts only inside Studio View?

**Yes — this is a clean, recommended seam.** Mission Control remains DOM/CSS. Studio View becomes a
**mount point** that **lazy-loads** a renderer module consuming the **same `read_model`** (and later
the same event stream). The state→zone/agent mapping already lives in the projector (`zone_map`) and
app, so the renderer is **swappable without touching Mission Control or canon**. Code-split so the 3D
bundle loads **only when the Studio tab is entered** — Mission Control stays light and mobile never
downloads 3D deps unless the user opens Studio View. The current DOM 2.5D Studio View can remain as
the **guaranteed fallback** (low-end devices, reduced-motion, accessibility).

## H. Expected technical & mobile tradeoffs of that approach

- **Bundle/build:** Three.js is ~150 KB+ gzipped (R3F/drei more) and needs a build step (e.g. Vite) —
  a departure from the current no-build v0. Must be code-split/lazy so Mission Control is unaffected.
- **Mobile:** real GPU/battery cost; needs device-tier detection, LOD/reduced detail, capped device
  pixel ratio, paused rendering when hidden, and a **2.5D/DOM fallback** for low-end iOS Safari
  (WebGL context/memory limits). This is exactly why both reference repos shipped 2D.
- **Accessibility:** a 3D canvas is opaque to screen readers → Mission Control must remain the
  fully-accessible equivalent (already the case).
- **Maintenance:** asset pipeline + materials/shaders add ongoing upkeep vs. plain DOM.
- **Upside:** smooth large-scene depth, premium spatial feel, and richer motion that DOM cannot match.
- **Recommendation (for the Owner to decide, not decided here):** prototype an R3F Studio View
  **behind the seam** and compare it against the DOM 2.5D on a real iPhone before committing —
  keeping the read model and state mapping constant so only the renderer is under evaluation.

> **This note does not conclude that 2.5D is the final visual direction.** The DOM 2.5D Studio View
> is the accepted **functional** v0; the Owner's requirement for a premium spatial / possibly true-3D
> Studio visualization remains open, and the architecture above is designed to satisfy it without
> rework of Mission Control, the read model, or any Studio OS boundary.
