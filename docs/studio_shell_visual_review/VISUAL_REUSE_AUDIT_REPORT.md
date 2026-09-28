# VISUAL_REUSE_AUDIT_REPORT — openclawfice/openclawfice (+ FounderOS-DEMO)

Reuse-first audit of the named "WOW virtual-office" reference. Findings are from **reading the
actual repository** (GitHub API tree + raw source files + the author's own in-repo screenshot),
not README/screenshots alone. **No adaptation spike was built** — because the audit surfaced hard,
measured blockers, and the standing rule is: on an incompatible/impossible reuse, state the measured
reason and STOP, never silently fall back to building our own.

## A. Exact repository audited
`github.com/openclawfice/openclawfice` (primary). Secondary re-check: `github.com/Bennettxai/FounderOS-DEMO`.

## B. Commit / version
openclawfice: default branch `main`, created 2026-02-23, last push **2026-05-12T16:49:18Z**, 245 files,
not archived, size ~10.5 MB. Next.js `^15.1.0`, React `^19`, 14 total deps.
FounderOS-DEMO: `main`, last push 2026-09-21, Next.js `^14.2`, React `^18`.

## C. License  — **BLOCKER**
openclawfice: **AGPL-3.0** (confirmed in the `LICENSE` file: "GNU Affero General Public License v3.0",
© 2026 Tyler Henkel, **and** `package.json "license": "AGPL-3.0"`), **plus a `CLA.md`** (contributor
license agreement). AGPL-3.0 is **strong network-copyleft**: if its code is incorporated into Studio OS
and users interact with the result over a network, the **entire combined work's source must be released
under AGPL-3.0**. That is incompatible with a proprietary Studio OS / Investment Engine platform unless
the Owner makes an explicit legal decision to AGPL-license the combined work — an owner/legal matter
(border predmet №2/№3), not an engineering choice I may make.
FounderOS-DEMO: **MIT** (permissive) — usable, but see D/E (not a 3D engine).

## D. Actual renderer  — **BLOCKER (premise is false)**
openclawfice is **NOT a 3D application.** Measured:
- **Zero** 3D/graphics dependencies — no `three`, `@react-three/fiber`, `@react-three/drei`, `babylon`,
  `pixi.js`, `phaser`, `gsap` (deps = Next.js + React + `ws` + 11 utilities).
- **Zero** `canvas` / `webgl` / `getContext` / `three.` usages in the office code (`components/Room.tsx`,
  `MeetingRoom.tsx`, `OfficeEvents.tsx`, `app/page.tsx` — all 0 hits).
- **4 asset files total**: `public/icon.svg`, `og-image.png`, `screenshot.png`, `screenshot-demo.png`
  (an icon + marketing images). **No 3D models** (`.glb/.gltf/.fbx`), **no textures/HDR**, **no sprites**.
- `components/Room.tsx` is self-described in code: **"Pixel-art room decorations — small ambient details
  for Sims vibe"** — rooms/props (monitors, plants, coffee cups) are drawn as inline-CSS `<div>`s with
  `imageRendering: 'pixelated'`.
The rendering engine is therefore **DOM/React + inline CSS pixel-art**, i.e. 2D. The author's own
screenshot (`REFERENCE_openclawfice_original.png`) confirms a **cartoon pixel-art "Sims-style" office**
(agents Nova/Forge/Lens/Pixel/Cipher in Work Room / Meeting Room / Lounge).
FounderOS-DEMO: also **no 3D deps** — a DOM "business command center" dashboard.

## E. Original scene architecture
A Next.js 15 app: a DOM "virtual office" agent **simulation** — rooms (`Room.tsx`, `MeetingRoom.tsx`),
NPC characters (`NPC.tsx`, `NPCParticles.tsx`), chat bubbles, meetings, achievements, command palette,
quest log, activity heatmap — driven by `/api/office/*` routes (chat, meeting, logs, autowork) and `ws`.
It is a polished **2D pixel-art** agent-office toy/product, not a spatial 3D engine, camera, or lighting.

## F. Reusable visual components
As a **3D base: none** (there is no 3D). As DOM concepts (were license compatible): room-decor idioms,
NPC/chat-bubble/meeting patterns, command palette, activity heatmap. But all are AGPL and pixel-art.

## G. External asset licenses
No external 3D/model/texture/sound assets exist to license (only an SVG icon + PNGs, all under the
repo's AGPL). So there is no third-party asset kit to reuse from here.

## H. Integration compatibility
Even setting license aside, the repo is a **whole Next.js product**, not an isolable 3D renderer module.
There is no self-contained "office engine" to mount inside our Shell; the office is entangled with its
own Next.js routes, `ws` server, and app pages. And its output is pixel-art DOM, not the volumetric
Studio View the Owner asked for.

## I. Reuse map
| Element | Classification | Measured reason |
|---|---|---|
| Building shell / rooms | **CANNOT REUSE** | AGPL-3.0; DOM pixel-art, not 3D geometry |
| Room geometry / layout | **CANNOT REUSE** | No 3D geometry exists (inline-CSS divs) |
| Materials / lighting / camera / controls | **CANNOT REUSE** | Do not exist (no 3D renderer) |
| Agent models / animations | **CANNOT REUSE** | Pixel-art CSS NPCs; AGPL; on the Owner's avoid-list |
| Desks / workstations / furniture | **CANNOT REUSE** | Inline-CSS pixel decor; AGPL |
| UI overlays / navigation | **CANNOT REUSE** | AGPL; bound to its own app |
| Movement / event system | **CANNOT REUSE** | AGPL; its own `/api/office` + `ws` engine |
| Task representation | **REPLACE DATA SOURCE (moot)** | Blocked upstream by license + non-3D |
| Responsive / mobile | **CANNOT REUSE** | AGPL; desktop DOM toy |

## J. Data-adapter design
N/A for this repo — reuse is blocked before an adapter is meaningful. (Our existing
`read_model.json` + zone/state maps remain the correct adapter surface for whatever renderer we choose.)

## K. Exact code reused / adapted
**None.** No code was copied or adapted (correct under the AGPL blocker and the non-3D premise).

## L. Exact code that had to be replaced
N/A — nothing was taken to replace. No spike was built.

## M. Screenshots — original vs adapted
- **Original:** `REFERENCE_openclawfice_original.png` (the author's in-repo screenshot — real appearance:
  2D pixel-art Sims-style office).
- **Adapted:** **not produced.** Producing an adapted spike would require copying/modifying AGPL code
  into our tree (creating an AGPL derivative — the exact thing needing an Owner legal decision) and would
  not deliver a 3D result. Per the critical rule I did **not** build one, and I did **not** substitute a
  from-scratch scene dressed up as "adapted."

## N. Risks
- **Legal (highest):** embedding AGPL-3.0 code obliges releasing the combined Studio OS source under
  AGPL to network users; the CLA adds contributor terms. Irreversible if shipped.
- **Premise risk:** the strategy assumed a reusable *3D* office engine; measured reality is DOM pixel-art.
- **Aesthetic:** the pixel-art / cartoon "Sims" look is explicitly on the Owner's own avoid-list.
- **Isolation:** not an extractable renderer module.

## O. Recommendation
`openclawfice` is **not a viable reuse base** for a premium/true-3D Studio View: (1) AGPL-3.0 + CLA is
incompatible with proprietary Studio OS absent an explicit Owner legal decision; (2) it contains **no 3D
engine or assets** — it is DOM pixel-art; (3) its aesthetic is the one the Owner asked to avoid. Any one
of these blocks it; together they are conclusive. `FounderOS-DEMO` (MIT) is a DOM dashboard, not a 3D
office — usable only for product/UX *ideas*, not as a visual base.

**Reuse-first is still the right strategy — but it must target a genuinely 3D, permissively-licensed
base.** Recommended next step (for Owner/ARB approval, not started here): audit **permissively-licensed
(MIT/Apache-2.0/CC0)** true-3D candidates — e.g. an MIT React-Three-Fiber office/room starter + a **CC0
low-poly asset kit** (such as Kenney.nl CC0 furniture/character packs) — mount behind the existing Studio
View seam, and feed it our `read_model`. That preserves reuse-first while keeping licensing clean and the
result actually 3D. If the Owner specifically wants openclawfice regardless, that requires an explicit
decision to accept AGPL-3.0 for the combined work — and even then it yields a pixel-art DOM office, not
the volumetric experience described.
