# PHASE 1 — DASHBOARD SHELL SPEC

> Goal: app surfaces stop being narrow scroll-columns and become a DeBank/Zapper-class shell.
> **Prove it on `/dashboard` first, wrapper-style, then extract.** Marketing pages stay
> single-column — do NOT shell them.

## 1. Critical constraint (from fact-check)

`DashboardLive.jsx` polls **SSOT + 23 endpoints @15s** with per-feed offline states,
`PanelBoundary` per panel, and an explicit "HONESTY CONTRACT" (lines ~20-28: a dead feed goes
grey individually, never breaks siblings, never fakes liveness). **Re-shelling = wrapping, not
rewriting.** Any change that touches feed logic is out of scope for B2.

## 2. B1 — `DashboardShell` component (`landing/src/components/shell/`)

- `DashboardShell.astro` (static chrome; islands live inside):
  - **Sidebar** 256px, collapsible to 64px icons (localStorage persist), sections:
    Overview · Positions · Strategies · Risk · Monitoring · Research · (admin-only: Operator).
    Active-state from `Astro.url.pathname`.
  - **Topbar** sticky: page title · global LiveChip (SSOT phase) · kill-switch state pill
    (`/api/live/safety`) · EN|RU · "Check your wallet" CTA.
  - **Main**: fluid `max-w-[1440px]`, 12-col CSS grid, `gap-4`; slots: `kpi` (full-width
    strip) · `main` (8 cols) · `rail` (4 cols, right context rail) · full-width below.
  - Mobile (<768px): sidebar → bottom icon bar; rail stacks under main; topbar keeps LiveChip.
- Tokens: reuse the existing `Layout.astro :root` block — NO new colors. P&L green/red only
  for P&L numbers; one accent for interactive.
- The shell page still uses `Layout.astro` (header/footer stay for brand continuity) with a
  `shell={true}` prop that suppresses the narrow-column wrapper.

## 3. B2 — `/dashboard` re-shell (wrapper-first, 2 steps)

- **Step 1 (safe):** `dashboard.astro` renders `DashboardShell`; `<DashboardLive client:load>`
  mounts UNCHANGED into the `main`+full-width region; `<RtmrMonitor client:visible>` moves to
  the `rail`. Zero JSX changes inside DashboardLive. Ship, validate 15s polling + offline
  states still work (block API host in devtools; every panel must degrade individually).
- **Step 2 (incremental):** split DashboardLive's top summary into the shell's `kpi` slot as a
  `KpiStrip` (equity · realized APY track-to-date · evidenced days · kill-switch tier · cash
  buffer — sources it already fetches). Move section-nav to sidebar anchors. One PR per panel
  group; HONESTY CONTRACT comment travels with any moved code.
- **Gate before A1:** F2 baseline comparison + a week of error-free polling in prod.

## 4. A1 — Kit extension (AFTER the gate) — extend `landing/src/components/ui/`

Existing (do not rebuild): Badge, Button, Card, Eyebrow, LiveChip, PageHeader, Section,
StatusPill, Table/Td/Th, kit.jsx, tokens.js, riskStyles.js. **Add:**
- `StatCard` (label, value, delta, spark?, evidence-tag, offline state)
- `DataTable` (sortable columns, sticky header, dense mode, row-click → Drawer, per-row
  sparkline cell; TanStack optional — stdlib-first if feasible in Astro islands)
- `Drawer` (right slide-over, focus-trap, Esc/overlay close, a11y per H1)
- `Tabs`, `FilterChips`, `SectionHeader`
- **State kit** (first-class): `EmptyState`, `ErrorState`, `LoadingSkeleton`, `OfflineBadge` —
  the honesty differentiator; every data component accepts `state` and renders these.
Document each in `docs/SITE_DESIGN_SYSTEM.md` (update its header: SPEC → PARTIALLY BUILT,
link the kit; kill the stale "5 near-black bgs / 2 CSS systems" §1.1 claims or mark historic).

## 5. A2 — Token sync Astro ⇄ Checkup

Single source `landing/src/styles/tokens.css` (extract the `:root` block); checkup repo copies
it verbatim with the `SYNC-SOURCE` header (U1 already ported chrome). QA1 later: a CI check
that diffs the two token files and fails on drift (GitHub Actions, NOT CF prebuild).

## 6. B3+ rollout order (Phase 2)

Checkup report FIRST (B6 — it's the conversion vehicle), then `/monitoring`,
`/aggressive-lab`, `/packages` app-sections, then `/admin/*`. Each conversion: shell + KPI
strip + DataTable + Drawer, one page per push, build-green, screenshot proof.

## 7. Acceptance (B1+B2)

- `/dashboard` on desktop: sidebar + topbar + KPI strip + grid; no horizontal scroll at
  1280/1440/1920; mobile bottom-bar works.
- All 24 feeds still poll @15s; per-feed offline degradation intact (devtools test recorded).
- Lighthouse: LCP no worse than pre-shell baseline (F1 captured); CLS < 0.1.
- Keyboard: sidebar and topbar fully tabbable; drawer focus-trapped (when added).
