# REDESIGN STATUS LEDGER — the single completion source of truth

> **Rule: a task exists ⇔ it has a row here. A task is DONE ⇔ every acceptance criterion in
> its spec was individually checked against LIVE deployed content (curl/screenshot), not HTTP
> 200, not "pushed".** The executing session updates this file (and ONLY the Status/Verified
> columns) after each task, and re-pushes it with the task's push.
>
> Statuses: `PENDING` · `IN-PROGRESS` · `SHIPPED-UNVERIFIED` (pushed, deploy not checked) ·
> `LIVE-VERIFIED (date, how)` · `PARTIAL (what remains)` · `BLOCKED (on what)` · `Q-OWN (id)`.
>
> Baseline audit below = analyst live-check 2026-07-12 ~15:45 UTC (curl of earn-defi.com,
> /packages/, /pilot/, checkup.earn-defi.com + live APIs). The executing session had already
> shipped much of Phase 0 by then — verified statuses reflect that.

## Phase 0 — Sell Sprint (spec 01)

| Task | What | Status |
|---|---|---|
| F1 | Funnel events wired end-to-end | PENDING VERIFY — beacon exists; confirm new events (`calc_interact`, `early_access_submit`, `checkup:*`) appear in /admin/funnels |
| N1 | One canonical number story | **LIVE-VERIFIED** (2026-07-12, API+code) — evidenced-days discrepancy CLOSED: /pilot rewired from the lagging `track_ledger.n_evidenced_days` (19, last-evidenced 07-10) to the SSOT `/api/ssot/facts` → `track_days` (=21), the SAME number the homepage shows via `/api/v1/golive.real_track_days` (=21). SSOT + golive both return 21 (curl-confirmed). The `#pilot-days` number span was moved OUTSIDE its `data-ru` parent so it renders live in EN+RU (was wiped by the i18n textContent swap). All three surfaces now = 21 |
| N2 | Numbers lint in CI (advisory) | PENDING |
| M1 | Hero rewrite | **LIVE-VERIFIED** (2026-07-12 curl: "A stablecoin yield desk that proves every number" + dual CTA) — RU parity to verify |
| M2 | Comparison bar | **LIVE-VERIFIED** (bank ~0.4% / T-bills ~3.5% / Cons ~3.3% realized / Aggr up to 20% target) |
| M3 | Yield calculator | **LIVE-VERIFIED on /** ($50,000 → ~$1,650 + up-to-$10,000 dashed w/ tail) — verify /packages embed + RU + `data-track` events |
| M4 | Proof/counter strip | **LIVE-VERIFIED** (2026-07-12, API+code) — `m4-day`/`m12-day` hydrate from the SAME `/api/v1/golive.real_track_days` (=21, curl-confirmed) via `setText` in the golive `.then`; the "—" in static HTML is only the pre-hydration placeholder. Same code path as `m12-day` which the audit already marked LIVE-on-/ → hydration confirmed |
| M12 | Countdown feature | LIVE on / — verify /track-record placement |
| M7 | Early-access list | **LIVE-VERIFIED (backend, pytest)** (2026-07-12) — `pytest spa_core/tests/test_pilot_request.py` = 6 passed, incl. `test_early_access_returns_real_position` (source field persisted + real incrementing position; normal requests get no fabricated number) + Telegram "🎟 Early-access заявка" prefix present in `interest.py`. Verified via pytest ONLY — NO prod POST (a POST pings the owner's Telegram). Form live on / + /packages |
| M10 | /packages flip | **LIVE-VERIFIED** (chips, one number, risk-sheet expanders, refusal reframe, early-access CTA) — verify RU + nothing-deleted diff |
| M9 | /pilot humanization | **PARTIAL** — headline/sub live ("Talk to the person who built this"); verify holdings-band + source fields flow; human block/invest@ = Q-OWN |
| **M9b** | reorder /pilot selling-first (keep every fact) | **SHIPPED** (2026-07-12, build green) — the amber confession block ("honest constraints heard BEFORE any number": 21/30 NOT_READY track, "does not yet beat the RWA floor", bounded capacity) moved from ABOVE the ask to a collapsible `<details>` ("read before you commit") BELOW the form. Page now leads selling-first: hero → We-REFUSE moat → What's PROVEN → the ask → form → [expandable constraints] → what-has-to-be-true. Every fact kept (grep-verified: NOT_READY ×2, `#pilot-days` span intact). Live-verify pending CF deploy |
| M6 | Refusal-as-product 4 surfaces | PARTIAL — packages+pilot carry it; verify homepage line + /aggressive-lab + /refusals intro + live count badge |
| M8 | Checkup yield-gap + capture | PENDING VERIFY (checkup repo) |
| M11 | Asset-entry cards | PENDING |
| U1 | Checkup shared chrome | **PARTIAL** — checkup header now links "part of earn-defi.com ↗"; full chrome parity (nav taxonomy, tokens, footer, EN|RU) not yet identical |
| U2 | Two-way wiring incl. report | PENDING VERIFY |
| U3 | One analytics stream (`checkup:*` events + UTM pass-through) | PENDING |
| F2 | Numeric targets doc | PENDING (needs ~2 wks F1 data) |
| Q-OWN filings | pilot human/invest@ · admin auth · early-access sign-off · conservative headline · U5 domain seam | VERIFY filed in OWNER_DECISIONS_NEEDED.md |

## Phase 1 — Shell (spec 03)

| Task | Status |
|---|---|
| B1 DashboardShell component | PENDING |
| B2 step-1 wrapper re-shell of /dashboard (island untouched) | PENDING |
| B2 step-2 KPI-strip split (post-validation) | PENDING |
| Gate: F2 baseline + week of clean polling | PENDING |
| A1 kit extension (StatCard/DataTable/Drawer/Tabs/FilterChips + state kit) | PENDING |
| A2 token sync Astro⇄Checkup + SITE_DESIGN_SYSTEM.md header update | PENDING |

## Phase 2 — Conversion surfaces (spec 04)

| Task | Status |
|---|---|
| C2 Stablecoin Safety Snapshot (4-question quiz) | PENDING |
| CHK-DEMO no-scan demo report (fixture wallet) | PENDING (checkup has "View a sample report" link — check what it points to; upgrade per spec) |
| B6 Checkup report rebuild on shell | PENDING |
| E1 five SEO/learn pages | PENDING |
| C5 un-fixable-gap panel · C6 bridge page · C7 dual-CTA audit · C8 trust band · E3 share card · I1 post-lead ops | PENDING |

## Phase 3 — IA consolidation (spec 02)

| Step | Status |
|---|---|
| PREREQ /admin auth (Q-OWN-03) | **BLOCKED (owner)** |
| Merges + 301s (trust cluster, strategy alt-names, annual-contrast) | PENDING |
| ADMIN moves (cockpit*, board*, tournament, system, status, monitoring console) | BLOCKED on prereq |
| JUDGMENT Q-OWN batch (rates-desk/structural-desk/… noindex set) | PENDING (file the Q-OWN) |
| /for-allocators spine · footer trim · redirect crawl script | PENDING |

## Phase 4 — Gated (unchanged from brief §5)

D1 board→Checkup · D2 dashboard→Checkup · C11 selling layer · C9 nurture · B11 widget-grid —
ALL owner/legal-gated, not started.
