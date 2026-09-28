# ADR-492: Studio OS Hybrid Shell / Cockpit — architecture & read-only v0

- **Status:** ACCEPTED (v0 read-only vertical slice implemented) · 2026-09-27 · owner: @yurii
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-488). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.
- **Supersedes/relates:** ADR-469 (mission control plane, read model), ADR-473 (periodic tick),
  ADR-475 (durable mission state root). Distinct from the Investment Cockpit (`landing/**`).

## Context

Studio OS needs a visible, premium, **bilingual (RU/EN), mobile-friendly** operational interface
that answers, in ~10 seconds: what is running / waiting / blocked / needs my decision / what did
the studio build / is it healthy / what changed. The owner decided (directive 2026-09-27) on a
**hybrid** of two references — operational **Mission Control** clarity + a **living Studio View** —
built as **our** product, not a clone, and driven by **real canonical state**.

Evidence audited (2026-09-27):
- **`builderz-labs/mission-control`** (Next.js 16, Zustand, SSE+WS+smart-poll, SQLite, MIT with
  LICENSE file, ~70 Playwright tests). Office view is **2D DOM/CSS + rAF**; memory graph = reagraph
  (WebGL). Strong task pipeline + approval gate. Desktop-first. Monolithic 100 KB+ panels.
- **`glglak/agent-mission-control`** (Next.js 14, Fastify+SQLite bridge, WS+1.5 s polling). Live
  office is a **2D `<canvas>` pixel-art** renderer; its Three.js/R3F code is **dead/unwired**. No
  tests, **no LICENSE file** (MIT declared only), no auth, not mobile-ready. Clean pure
  `reduce(state,event)` engine + zone/room model.
- **Existing prototype** `spa_director_os_prototype_v2.html`: static, no-framework, dark theme with
  CSS design tokens — a proven visual language, but demo-only.
- **Director OS doctrine** (ADR-469): read-only, snapshot/projection-driven mission control; Phase-9
  audit ships **zero action buttons** in v1.
- **Current canonical state** is real and readable today: `mission-state/v04/ledger.json`
  (missions/items/work_graph/`mission_dispatch_disabled`), `architecture/*.json`, `data/*.json`
  (freshness-labelled), tracker `_BOARD.md` (needs-owner), `/tmp` plane logs, git.

**Decisive cross-finding:** *both* premium references render their spatial view in **2D**, not 3D
WebGL. This refutes the assumption that heavy 3D is required for a compelling Studio View.

## Decision

1. **Hybrid, our product.** Two modes over one shared canonical-derived read model: **Mission
   Control** (Overview/Work/Decisions/Roles/System) and **Studio View** (spatial zones). Same
   `read_model.json`; same task entity across modes.
2. **Studio View = DOM/CSS 2.5D** (not Three.js). Best mobile performance, accessibility, and
   maintainability with no build step — and it is what both references actually ship. Renderer choice
   is revisitable behind the zone/state model.
3. **Read model = derived projection with provenance.** A stdlib projector
   (`studio_shell/build_read_model.py`) reads canon and emits `read_model.json`; every entity carries
   a `source` back to canon. **UI ≠ canonical state.**
4. **Read-only first (v0).** No action endpoints, no write path — matching ADR-469 Phase-9. Safe
   controls (Approve/Reject/Retry/Pause) are added later, each mapped to an audited deterministic
   backend command.
5. **i18n is first-class.** Translation keys, RU+EN of equal quality, remembered preference; no
   hard-coded strings. Technical identifiers (TASK/`wi-…`, ADR-xxx, PROVIDER, CANDIDATE, GitHub) stay
   verbatim.
6. **Mobile-first.** Desktop sidebar / mobile bottom-nav + top bar; Studio View becomes a scrollable
   single-column zone map; reduced-motion honored.
7. **No-build vanilla stack** for v0 (HTML/CSS/ES-module JS + stdlib server), consistent with the
   repo's stdlib-only, local-first, no-paid-dependency posture. React/Vite deferred until a write
   path or realtime complexity justifies it.
8. **Boundaries preserved.** Loopback-only bind; no secrets in payloads; Investment Engine stays a
   separate product the UI may *display* but never *act on*; green/yellow/red permission zones remain
   real semantics.

## Alternatives considered & rejected

- **Adopt a reference repo as the base.** Rejected: both are desktop-first, store-coupled, monolithic
  (100 KB+ panels), one has no tests/LICENSE/auth. Reuse **concepts** (pipeline, zones, smart-poll,
  SSE-dispatch), not code.
- **Three.js / React-Three-Fiber Studio View.** Rejected for v0: heavy for mobile/battery, larger
  build/maintenance, and unnecessary — 2D is the proven premium path. Kept as a future seam.
- **React/Next.js + SQLite read DB now.** Deferred: adds build/native-module/deploy weight before a
  write path exists; a rebuildable JSON projection is sufficient and simpler for read-only v0.
- **Realtime SSE/WS now.** Deferred: 30 s polling of a rebuilt projection is adequate for v0; realtime
  is a later seam.

## Consequences

- A working, honest, bilingual read-only Shell exists and is bound to live canon (2 missions, 12 work
  items, 5 owner decisions, dispatch CLOSED, go-live shown STALE).
- Later, separately-audited steps: (a) realtime read model (SSE or file-watch); (b) a local
  rebuildable read DB if projection cost grows; (c) safe actions, each an audited deterministic
  command with permission/validation/audit trail; (d) capacity/activity feed once
  `wi-5e710b72…` (mission feed) lands; (e) optional replay.
- Freshness gaps are surfaced, not hidden: `telegram_bot_capabilities.json` and
  `code_sync_status.json` are absent → shown as not-measured.

## Risks & failure modes

- **Stale sources read as current.** Mitigated: per-source LIVE/RECENT/STALE/UNKNOWN labels + tests.
- **UI drifting into a second source of truth.** Mitigated: derived projection + per-entity `source`;
  no write path in v0.
- **Studio View becoming decorative.** Mitigated: zones/agents bound to ledger counts; empty zones say
  "empty"; no fabricated activity.
- **Secret exposure in the browser.** Mitigated: projector never reads secrets; loopback-only; test
  asserts no secret-value patterns in the payload.

## Rollback / migration

Fully additive and isolated under `studio_shell/` (+ this ADR). Removing the directory removes the
feature with zero canonical impact; `read_model.json` is regenerable and disposable. No canonical
state, no daemons, no accepted migration artifacts are touched.

## Acceptance (v0, met)

Owner can open it locally, switch RU↔EN, use desktop and iPhone-sized viewport, see real health/work/
roles/provider-candidate state, open task detail, open Studio View with real tasks/roles represented
spatially, click a token to reach the same canonical task, see stale/unknown honestly, see no fake
data, and confirm no secrets in payloads. Contract test: `studio_shell/test_read_model.py` (9 green).
