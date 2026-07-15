# Phase-1 P0 — Dashboard SPA Build Checklist

> Source of truth for B1 (DashboardShell → true SPA on /dashboard-preview).
> Every acceptance criterion must be checked LIVE before promotion to /dashboard.
> Status column: PENDING · SHIPPED · LIVE-VERIFIED (date, how) · BLOCKED (on what).

## P0 requirements (owner directive 2026-07-15)

| # | Requirement | Status | Notes |
|---|---|---|---|
| R1 | Sidebar switches central VIEW with NO page reload | **SHIPPED** (2026-07-15) | Hash routing via `window.history.pushState` + `hashchange` listener; `renderView()` swaps component without unmounting shell |
| R2 | ONE shared live-data connection for KPI strip | **SHIPPED** (2026-07-15) | Single `useEffect` polls `/api/ssot/facts` (15s) and `/api/live/fleet` (30s) at root level; persists across view switches |
| R3 | Per-view URL routing `/dashboard/<view>` | **SHIPPED** (2026-07-15) | Hash-based: `/dashboard-preview#overview`, `#positions`, `#monitoring`, `#research`. Bookmarkable, shareable, back-navigable |
| R4 | Migrate /board+/risk+/monitoring+/research into views | **SHIPPED (content)** — 301s deferred | DfbScreener → positions, RtmrMonitor → monitoring, ResearchView → research, DashboardLive → overview. Standalone 301s deferred until owner approves promotion |
| R5 | Drop marketing header/footer for compact dashboard topbar | **SHIPPED** (2026-07-15) | `app={true}` on Layout suppresses SiteHeader/PaperStrip/SiteFooter; DashboardSPAApp provides its own topbar + sidebar chrome |
| R6 | Add 'Last updated HH:MM:SS' to KPI row | **SHIPPED** (2026-07-15) | `fmtTime(lastUpdated)` in KPI strip; green when live, faint + "snapshot" sub-label before first API response |
| R7 | Fix fleet-card WARNING-stale presentation | **SHIPPED** (2026-07-15) | `FleetChip`: STALE → dim italic amber chip labelled "Fleet: STALE" (not "WARNING · stale"); CRIT/WARN/OK each distinct |
| R8 | Wrap existing DashboardLive island UNCHANGED | **SHIPPED** (2026-07-15) | DashboardLive imported as a React component inside DashboardSPAApp — zero internal edits. `initialFacts` seeded from snapshot |
| R9 | Keep on /dashboard-preview (do NOT promote to /dashboard) | **SHIPPING CONSTRAINT** | dashboard-preview.astro only. /dashboard untouched. |
| R10 | Owner visual approval before promotion | **PENDING** | Owner checks earn-defi.com/dashboard-preview; says "промоутим" → one-edit promotion |

## Owner acceptance test (spec §7 browser checks)

> These CANNOT be verified by curl — require browser + devtools. Check before saying "promoted."

- [ ] Sidebar + topbar + KPI strip render without horizontal scroll at 1280 / 1440 / 1920px
- [ ] Sidebar collapse button (256⇄64px) works; state persists on page refresh (localStorage)
- [ ] On mobile (<900px): sidebar becomes horizontal scroll strip above the main content
- [ ] Clicking each nav item (Overview / Positions / Monitoring / Research) switches content with NO page reload (URL hash changes, back button works)
- [ ] KPI strip "Last updated" shows HH:MM:SS; turns green when live API responds
- [ ] Fleet chip shows "Fleet: STALE" (dim italic amber) when fleet data is stale — NOT "WARNING · stale"
- [ ] Overview view: DashboardLive loads and polls normally (all its internal tabs work)
- [ ] Positions view: DfbScreener loads (shows "Unavailable" gracefully if API offline)
- [ ] Monitoring view: RtmrMonitor loads and polls
- [ ] Research view: three desk cards with GO/measurement-GO/NO-GO badges

## Promotion procedure (when owner says "промоутим")

1. In `dashboard.astro`: import `DashboardSPAApp` instead of `DashboardLive` + `DashboardShell`.
   Pass `initialFacts` from snapshot. Set `app={true}` on Layout.
2. Add 301 redirects: `/board` → `/dashboard#positions`, `/monitoring` → `/dashboard#monitoring`,
   `/research` → `/dashboard#research`. Use `_redirects` or `astro.config.mjs` redirects.
3. Delete `dashboard-preview.astro` + remove `shell/DashboardShell.astro` (superseded).
4. Run `npm run build` in `landing/` — verify exit 0.
5. Push to origin/main → CF deploys.
6. Live-verify: curl -L https://earn-defi.com/dashboard shows the SPA chrome.

## Architecture diagram

```
/dashboard-preview
  Layout (app=true — no marketing chrome, CSS vars + i18n runtime)
    preview banner
    DashboardSPAApp (client:load)
      ├── aside.spa-sidebar (256/64px collapsible, sticky)
      │     └── nav.spa-nav (VIEWS buttons → navigate(id) → hash change)
      └── div.spa-body
            ├── header.spa-topbar (title + FleetChip + "Check wallet" CTA)
            ├── div.spa-kpi (shared: /api/ssot/facts + /api/live/fleet, 15/30s)
            │     ├── NAV · Paper APY · Track days · Go-live gates
            │     └── Last updated HH:MM:SS
            └── main#spa-main (view content)
                  ├── #overview  → <DashboardLive initialFacts={facts} /> (UNCHANGED)
                  ├── #positions → <DfbScreener />
                  ├── #monitoring→ <RtmrMonitor />
                  └── #research  → <ResearchView /> (inline — desk cards + links)
```
