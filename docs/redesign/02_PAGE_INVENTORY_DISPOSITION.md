# PAGE INVENTORY & DISPOSITION MAP (95 page files, verified 2026-07-12)

> Drives Phase 3 (IA consolidation). Verdicts: **KEEP** (public spine) · **ADMIN** (move behind
> authed /admin — **blocked on Q-OWN-03 auth**) · **MERGE** (fold into a canonical page +
> 301/308) · **JUDGMENT** (per-page owner/SEO call, from UX-05 — these are intentional public
> proof/SEO pages; don't blanket-move). Every moved/merged URL gets a 301/308, never 404.
> Re-verify the list with `ls landing/src/pages` before executing — pages ship weekly.

## Top-level (36)

| Page | Verdict | Notes |
|---|---|---|
| index | KEEP | M1/M2/M4 rework |
| packages | KEEP | M10 flip; canonical pricing surface |
| track-record | KEEP | M12 countdown on top |
| trust | KEEP | becomes the ONE warm trust page (UX-34 target) |
| security, risk, risk-disclosure | MERGE → trust (+1 legal page) | UX-34: 5-page cluster → 1 Trust + 1 legal |
| disclaimer | KEEP (the 1 legal page) | absorbs risk-disclosure legalese |
| research | KEEP | becomes the ONE research hub (UX-35) |
| methodology | KEEP | canonical How-it-works (UX-35); `system`-level detail merges here or ADMIN |
| competitive-position | KEEP | wire from research hub |
| faq, fees, changelog, blog/* (4) | KEEP | |
| pilot | KEEP | M9 |
| emergency-withdrawal | KEEP | trust asset |
| refusals, verify | KEEP | marketing assets (M6) — promote, don't bury |
| annual-contrast | MERGE → packages (section) or KEEP if SEO traffic | orphan today (UX-33) |
| dashboard | KEEP | the showroom; Phase-1 shell |
| aggressive-lab | KEEP (public-linked from nav) | M6 copy pass; it's the aspiration engine |
| readiness | JUDGMENT | overlaps track-record/golive; likely MERGE → track-record |
| yield-lab | JUDGMENT | orphan (UX-33); merge → research or ADMIN |
| monitoring | JUDGMENT | public RTMR proof vs /admin/monitoring dupe (UX-38): keep ONE public "live monitors" section on /trust, full console → ADMIN |
| system, status | ADMIN | operator depth; keep a public status pill in footer |
| cockpit, cockpit-kit | ADMIN | cockpit-kit is a component lab — pure cruft |
| tournament | ADMIN | strategy leaderboard = operator/research depth |
| rates-desk, structural-desk, rwa-backstop, exit-nav | JUDGMENT | intentional SEO/proof pages (UX-05); keep public+noindex-decision per page, link only from research hub |
| proof-of-reserves, fundability, due-diligence | JUDGMENT | due-diligence + fundability feed the allocator spine (UX-37) — keep, wire into /for-allocators |

## Subdirectories (59)

| Group | Verdict | Notes |
|---|---|---|
| academy/* (25) | KEEP | public education asset; wire from nav (already) |
| academy/onboarding/* (3) | KEEP | |
| admin/* (6) | ADMIN (already) | **gate first — zero auth today (UX-18/Q-OWN-03)** |
| blog/* (4) | KEEP | E1 SEO pages land here or as /learn/* |
| board/* (5) | ADMIN now; Phase-4 D1 migrates into Checkup | |
| cockpit/* (5) | ADMIN | |
| strategies/index, conservative, balanced, aggressive, btc, research | KEEP | canonical tier pages |
| strategies/preserve, core, max-yield, leverage-loops | MERGE → canonical tier pages (301) | alt-name dupes teach a second taxonomy (UX-23 decided names) |
| protocols/[slug] | KEEP | SEO long-tail |

## Phase-3 execution order

1. **Prereq: /admin auth exists** (CF Access or token gate — Q-OWN-03). Hard stop before any move.
2. MERGE cluster (trust/risk/security → 1+1; strategy alt-names → canonical; annual-contrast).
   Astro redirects: `export const prerender` + `Astro.redirect` stubs or `_redirects` file
   (CF Pages supports `_redirects`; use 301). Update sitemap filter + footer (UX-19: footer =
   public spine only) + internal links (grep each moved path).
3. ADMIN moves (cockpit*, board*, tournament, system, status, full monitoring console).
4. JUDGMENT set: one Q-OWN block listing each page with a recommendation; owner answers batch.
5. Allocator spine `/for-allocators` (UX-37): fundability → competitive-position →
   due-diligence → pilot ladder, one page linking the four.
6. QA: `npm run build` green; crawl old URLs → assert 301 target 200 (script:
   `scripts/check_redirects.sh` — curl each moved URL on the deploy preview); sitemap contains
   only KEEP pages; Google Search Console note for owner.
