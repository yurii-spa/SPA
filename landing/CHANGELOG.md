# Landing Changelog

## v10.36 — 2026-06-19 (MP-1420 — Meta Tags + SEO Audit)

### Added
- `public/robots.txt` — allow all crawlers, sitemap reference
- `public/sitemap.xml` — static sitemap covering all 17 pages with priorities and changefreq
  - Dashboard: daily (highest priority 0.9)
  - Strategies, due-diligence: weekly (0.7–0.8)
  - Risk, legal, FAQ pages: monthly (0.4–0.6)

### Changed
- `src/pages/methodology.astro` — added explicit `canonical="https://earn-defi.com/methodology"`
- `src/pages/fees.astro` — added explicit `canonical="https://earn-defi.com/fees"`

### Verified
- All 17 pages pass meta tags audit:
  - `<title>` — unique per page ✅
  - `<meta name="description">` — present and non-empty ✅
  - `<meta property="og:title">` / `og:description"` — via Layout.astro ✅
  - Canonical URL — explicit or auto-generated from `Astro.site` ✅
  - Favicon — `/favicon.svg` present ✅
- `Layout.astro` provides Twitter Card meta tags for all pages ✅
- `astro.config.mjs` has `site: 'https://earn-defi.com'` for canonical auto-generation ✅

---

## v10.35 — 2026-06-19 (MP-1419 — Landing Build Verification)

### Verified
- Source code audit: all `.astro` and `.jsx` files are syntactically clean
  - `GoLiveWidget.astro` (v10.16) — TypeScript interfaces, `as const`, `Astro.props` all valid
  - `dashboard.astro` (v10.15–16) — Research tab + GoLiveWidget import verified
  - Strategy pages (core/preserve/max-yield/research) — JSON import + non-null assertions valid
  - `tsconfig.json` extends `astro/tsconfigs/strict` — no mismatches found
- `strategy_config.json` shape matches all strategy page usages (3 strategies: preserve/core/max-yield)
- All component imports resolve to existing files ✅

### Notes
- `npm run build` must run on macOS host (node_modules platform-specific).
  Sandbox verification not possible due to macOS→Linux ARM64 node_modules mismatch.
  No code-level errors detected in manual audit.

---

## v10.16 — GoLiveWidget.astro created (MP-1400)
- New component: `src/components/GoLiveWidget.astro`
  - Props: `score`, `etaDays`, `status` (BLOCKED / IN_PROGRESS / READY)
  - Category breakdown: Gates, Evidence, Infrastructure, Financial, Data Sources, Documentation
  - Key blockers list, progress bar with tick marks
- Integrated into `dashboard.astro` as `<GoLiveWidget score={35} etaDays={29} status="BLOCKED" />`

## v10.15 — Research Tab + Source Quality Matrix (MP-1363)
- `dashboard.astro` updated:
  - Research tab added to dashboard (CPA methodology status, paper evidence progress)
  - Source Quality Matrix — 19 sources across CLEAN/PENDING/RESEARCH/NEEDED categories
  - RS-001 Anti-Crisis card (stress test results, 6 allocation slots, 17% source coverage)
  - RS-002 Cashflow LP card (IL scenario projections, SUSPENDED status)
  - Go-Live Timeline section (35/100 readiness score, ~2026-08-01 ETA)
