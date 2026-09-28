# STUDIO_VISUAL_V1_ARCHITECTURE_REPORT

Direction pass for Studio View v1 + a real-data-bound spatial prototype. **No full redesign built.**
Foundations accepted by ARB are preserved (read model, task entities, bilingual, read-only, DOM
Mission Control). This report does **not** decide 2.5D-vs-3D for the Owner — it frames the choice
and shows a direction prototype to judge before committing a renderer.

Prototype images (real read model — 2 missions, 12 work items [10 done / 2 failed], 5 owner
decisions, dispatch CLOSED):
- `PROTO_desktop_1440_ru_studio.png`
- `PROTO_wide_1920_ru_studio.png`
- `PROTO_mobile_390_ru_studio.png`

## A. Screenshot-based critique of current v0
- **Mission Control:** acceptable functional base (real KPIs, honest stale badges, activity, drill-down).
- **Studio View:** the core miss — seven rectangular columns read as *another dashboard*, not a space.
  No depth, no rooms, no movement, no sense of a building. Does not deliver "see my AI company working."
- **Wide screen:** the floor/content occupied the top strip; most of a 1920×1080 canvas was empty black.
- **Mobile:** structural — KPI grid can overflow horizontally; mode switch clips; Studio View was just
  stacked giant rooms; Task Detail right-aligned values (long ids / reason / provenance) leave the viewport.
- **Banner:** the permanent read-only/dispatch sentence dominated visually.
- **Work:** too technical — raw backend reason codes compete with the human title.
- **Decisions:** equal-weight raw cards; no urgency/risk/recommendation hierarchy.

## B. Mission Control elements to preserve
Canonical read model + provenance; task entity model; RU/EN i18n architecture; route/nav model;
status semantics (`ui_state_map`); read-only security model; DOM efficiency; the dark visual direction.

## C. Mission Control elements to refine (later, not now)
Stronger Studio-OS identity + premium typography + material/depth; simplify technical text; **compact
system-state chip** (prototyped: READ ONLY · SAFE MODE · DISPATCH CLOSED, expandable); **Work** →
primary human title + secondary metadata (id/role/project/model/state/time/evidence), reasons demoted;
**Decisions** → owner-focused (what/why/urgency/risk/AI recommendation/alternatives/consequences/evidence).

## D. Studio View shortcomings
Flat cards; no spatial depth or architecture; movement carries no meaning; wide-screen waste; mobile =
vertical stack; generic tokens without agent/task identity; no path/flow between zones.

## E. Three rendering architectures compared (Studio View only)
| Criterion | (1) DOM/CSS 2.5D isometric *(this prototype)* | (2) PixiJS 2D/2.5D (WebGL2D) | (3) Three.js / React-Three-Fiber (true 3D) |
|---|---|---|---|
| Visual ceiling | Good (isometric depth, glow, glass) — not volumetric | High 2.5D (sprites, particles, lighting-ish) | Highest (real depth, camera, materials, lighting) |
| Mobile perf/battery | Best (cheap DOM) | Good (single GL context, tuned) | Heaviest (GPU/battery; needs tiers/LOD) |
| Implementation complexity | Low (no build) | Medium (scene/sprite mgmt) | High (scene graph, assets, shaders) |
| Accessibility | Best (DOM nodes, ARIA) | Poor (canvas) → needs DOM shadow | Poor (canvas) → needs DOM shadow |
| Maintainability | High | Medium | Medium-low (assets/materials upkeep) |
| Integrate w/ vanilla Shell | Native (already) | Needs bundler | Needs bundler (Vite) |
| Lazy-load / code-split | N/A (tiny) | Yes | Yes (essential) |
| Fallback | Is the fallback | Needs one | Needs 2.5D/DOM fallback |
| Interaction (pan/zoom/pick) | Limited (CSS) | Good | Best (raycasting, camera) |
| Bundle weight | ~0 | ~100–150 KB | ~150–300 KB+ (R3F/drei) |

## F. Recommended Studio renderer (phased; Owner decides)
1. **Near-term (low risk, high uplift):** promote the **CSS isometric** Studio View (this prototype) into
   the Shell as the real Studio View — it already reads as a premium spatial building, is mobile-safe,
   needs no build, and is bound to canon. This *replaces* the flat-card v0 immediately.
2. **Target (premium/volumetric):** behind the mount seam, spike a **React-Three-Fiber** true-3D Studio
   scene consuming the **same read model**; A/B against the CSS isometric on a real iPhone.
3. **Owner picks** the production renderer from the A/B. CSS isometric remains the guaranteed fallback
   (low-end, reduced-motion, no-WebGL). *I recommend R3F for the eventual volumetric target, but do not
   decide it here.*

## G. Desktop spatial concept
Isometric **operations building**: rooms (Owner Command Center · Intake · Research Lab · Product Studio ·
Engineering · Review/QA · Sandbox/Canary · Reliability · Memory) as *spaces* with floor tiles, wall
thickness, glass edges, ambient per-room glow, a faint floor grid, and dashed **flow paths** between
zones. Tasks are lights at desks; owner decisions cluster in the gold Command Center; a contextual side
panel carries KPIs + waiting-for-owner. Empty rooms are quiet/dimmed (honest).

## H. Wide-screen concept
The floorplan **dominates** the canvas (larger rooms, centered vertically — see the wide prototype),
with contextual panels living in the margins and room for future ambient environment + room-activity
detail. No large dead black areas.

## I. Mobile Studio concept
**Distinct model, not stacked rooms** (see mobile prototype): a compact isometric **mini-map** up top +
an **Owner Home** bottom sheet (Waiting/Running/Blocked/Failed/Done strip + real decision cards) + bottom
nav. Future: tap a zone → **room focus**, swipe **carousel** between rooms, task/agent **bottom sheet**;
same spatial world + state model.

## J. Agent/task visual model
Every token = a **real** work item (or owner decision); color by normalized state
(running/review/owner_wait/blocked/failed/done/decision); the Command Center holds decisions; each room
shows a token cluster + a label chip (name + count). Tap/click → the **same canonical task drawer**
(shared entity, provenance to `ledger.json`). No fabricated agents; empty rooms stay quiet. Later: agent
identity (role/model) on the token + hover card.

## K. Animation / state-transition model
Motion **explains transitions**, never wandering: a token travels along the flow path on a real state
change — Intake→Research→Product→Engineering→Review→Owner/Done; Review→Memory (done); Engineering→
Reliability (failure). Arrival = brief pulse; running = gentle pulse; failure = red pulse toward
Reliability; done = settle in Memory. Driven by read-model diffs (later the event stream). Reduced-motion
renders the same states statically.

## L. Shared state integration
One projector → `read_model.json` → shared entity model → **Mission Control DOM renderer** *and* **Studio
renderer**, both reading the **same** tasks/decisions/zones (`ui_state_map`/`zone_map` already isolated).
The renderer is swappable without touching Mission Control or canon; **no duplicate task truth**;
provenance preserved end-to-end.

## M. Performance strategy
Code-split/lazy-load any WebGL renderer (loads **only** when Studio tab opens → Mission Control and mobile
stay light); device tiers (detail/LOD), capped device-pixel-ratio, instancing, visibility culling, pause
rendering when tab hidden, token-count caps, throttled data refresh (E3 later). The CSS isometric path is
inherently light and is the low-tier target.

## N. Accessibility / reduced-motion / fallback
Mission Control remains the **fully accessible equivalent** (all info reachable in DOM). The Studio canvas
gets an ARIA summary + a keyboard-navigable task list mirror; reduced-motion disables token motion;
low-end / no-WebGL falls back to the CSS isometric (or the DOM list); status is never color-only (labels +
position + shape).

## O. Mobile responsive repair plan (BLOCKING — precedes Studio v1 "usable")
- Strict viewport: `max-width:100%`, `overflow-x:hidden` on shell; no fixed widths beyond viewport.
- KPI grid: 2-column auto on phones (never horizontal scroll).
- Mode switch: fits (segmented icon+label) in the mobile top bar.
- **Task Detail → true mobile sheet/page:** stack key/value vertically; long ids/reason/provenance
  **wrap or truncate with reveal/copy** (fixes the `08` clip).
- Studio View: mini-map / carousel (per §I), not stacked rooms.
- Bottom nav: usable, safe-area insets.
- Verify at **320 / 390 / 430** px — zero horizontal overflow.

## P. Design-system evolution
Material/glass tokens + restrained glow; premium display type + mono for ids; spacing scale;
elevation/depth; task-token + agent-identity + zone-identity (icon/color) systems; compact system-state
chips; status/risk palette. Principle: **premium = restraint + precision**, no visual noise.

## Q. Risks and tradeoffs
3D bundle/build weight (mitigate: lazy code-split behind the seam); mobile GPU/battery (device tiers +
CSS fallback); canvas a11y (DOM equivalent mandatory); asset/material maintenance; over-engineering if the
scene stays small (both references shipped 2D for this reason). Mitigation throughline: **seam +
lazy-load + fallback + prototype-before-commit**.

## R. Vertical-slice implementation plan
1. **Mobile responsive repair + compact system-state chip** (blocking; §O). No new renderer, no realtime.
2. **Promote CSS isometric Studio View into the Shell** (replace flat grid; live-bound; drill-down to the
   shared task drawer; reduced-motion; wide fills canvas; mobile mini-map).
3. **State-transition motion** along flow paths (tokens travel on real state change).
4. **R3F spike behind the seam** (same read model) + iPhone A/B vs CSS isometric.
5. **Owner selects** the production renderer.

## S. Acceptance criteria
Mobile: no horizontal overflow at 320/390/430; Task Detail a readable sheet (long ids wrap/truncate+copy);
KPI adapts 1–2 col; mode switch + bottom nav fit. Studio View reads as a **space** (rooms/depth), bound to
real data, wide fills the canvas, RU/EN, reduced-motion, tokens drill to the same canonical task, no fake
agents, no secrets. Owner accepts the visual direction from the prototype.

## T. Exact first implementation task (recommended)
**"Studio Shell — mobile responsive repair + compact system-state chip"** (report §O). It is the ARB-named
**blocking** issue, unblocks "mobile usable," is low-risk (no renderer/realtime), and is independently
acceptance-testable at 320/390/430 with before/after screenshots. The **CSS isometric Studio View
promotion** (§R.2) is the immediate follow-on once mobile structure is sound. Both precede any WebGL
renderer or E3 realtime.
