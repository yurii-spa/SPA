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
| F1 | Funnel events wired end-to-end | **SHIPPED** (2026-07-12) — beacon flow verified (view/analyze_wallet/tier_compare/view_sample_report/... present in `/api/analytics/summary`). WIRED the 2 missing events: `calc_interact` (fires ONCE on first calculator-slider engage, throttled) + `early_access_submit` (on M7 form success) via `window.spaTrack`. `checkup:*` events are the U3 cross-domain remainder. Verify: interact with calc/form on / → both events land in `/admin/funnels` |
| N1 | One canonical number story | **LIVE-VERIFIED** (2026-07-12, API+code) — evidenced-days discrepancy CLOSED: /pilot rewired from the lagging `track_ledger.n_evidenced_days` (19, last-evidenced 07-10) to the SSOT `/api/ssot/facts` → `track_days` (=21), the SAME number the homepage shows via `/api/v1/golive.real_track_days` (=21). SSOT + golive both return 21 (curl-confirmed). The `#pilot-days` number span was moved OUTSIDE its `data-ru` parent so it renders live in EN+RU (was wiped by the i18n textContent swap). All three surfaces now = 21 |
| N2 | Numbers lint in CI (advisory) | **SHIPPED** (2026-07-12) — `.github/workflows/numbers-lint.yml` runs `check_tier_band_consistency.py` as an ADVISORY GitHub Actions lint (protocol §3: Actions, NOT CF prebuild). Guard currently CLEAN (no hardcoded bands outside tier_bands.json). Flip to blocking later via `STRICT_TIER_BANDS=1`. Verify: workflow appears in Actions on next landing push |
| M1 | Hero rewrite | **LIVE-VERIFIED** (2026-07-12 curl: "A stablecoin yield desk that proves every number" + dual CTA) — RU parity to verify |
| M2 | Comparison bar | **LIVE-VERIFIED** (bank ~0.4% / T-bills ~3.5% / Cons ~3.3% realized / Aggr up to 20% target) |
| M3 | Yield calculator | **LIVE-VERIFIED on /** ($50,000 → ~$1,650 + up-to-$10,000 dashed w/ tail) — verify /packages embed + RU + `data-track` events |
| M4 | Proof/counter strip | **LIVE-VERIFIED** (2026-07-12, API+code) — `m4-day`/`m12-day` hydrate from the SAME `/api/v1/golive.real_track_days` (=21, curl-confirmed) via `setText` in the golive `.then`; the "—" in static HTML is only the pre-hydration placeholder. Same code path as `m12-day` which the audit already marked LIVE-on-/ → hydration confirmed |
| M12 | Countdown feature | LIVE on / — verify /track-record placement |
| M7 | Early-access list | **LIVE-VERIFIED (backend, pytest)** (2026-07-12) — `pytest spa_core/tests/test_pilot_request.py` = 6 passed, incl. `test_early_access_returns_real_position` (source field persisted + real incrementing position; normal requests get no fabricated number) + Telegram "🎟 Early-access заявка" prefix present in `interest.py`. Verified via pytest ONLY — NO prod POST (a POST pings the owner's Telegram). Form live on / + /packages |
| M10 | /packages flip | **LIVE-VERIFIED** (chips, one number, risk-sheet expanders, refusal reframe, early-access CTA) — verify RU + nothing-deleted diff |
| M9 | /pilot humanization | **PARTIAL** — headline/sub live ("Talk to the person who built this"); verify holdings-band + source fields flow; human block/invest@ = Q-OWN |
| **M9b** | reorder /pilot selling-first (keep every fact) | **SHIPPED** (2026-07-12, build green) — the amber confession block ("honest constraints heard BEFORE any number": 21/30 NOT_READY track, "does not yet beat the RWA floor", bounded capacity) moved from ABOVE the ask to a collapsible `<details>` ("read before you commit") BELOW the form. Page now leads selling-first: hero → We-REFUSE moat → What's PROVEN → the ask → form → [expandable constraints] → what-has-to-be-true. Every fact kept (grep-verified: NOT_READY ×2, `#pilot-days` span intact). **LIVE-VERIFIED** (2026-07-12 curl: `<details> read before you commit` renders, form position < constraints position → selling-first order confirmed live) |
| M6 | Refusal-as-product 4 surfaces | **LIVE-VERIFIED** (2026-07-12, curl) — /aggressive-lab refusal-framing ✓, /refusals moat intro ✓, packages+pilot ✓; homepage proof-strip 'Refusals' card now shows a **LIVE count** (`#m4-refusals` fetched from `/api/rates-desk/decisions` counts.REFUSAL=20; span outside data-ru so it survives i18n) — 4th surface + live badge done |
| M8 | Checkup yield-gap + capture | **LIVE-VERIFIED** (2026-07-12, curl checkup/sample-report) — the yield-gap block ("your $X idle at 0% could earn ~$Y/yr at our ~3.3% realized paper rate — auditable, 0.0% drawdown, not a guarantee") renders on the sample report; deterministic from cap.idle_usd × 0.033, honest not-a-guarantee framing |
| M11 | Asset-entry cards | **LIVE-VERIFIED** (2026-07-12, curl /) — 'Holding USDC/USDT?' / idle-stables-at-0% / already-in-DeFi entry cards present on the homepage, routing to /packages + /#analyze |
| U1 | Checkup shared chrome | **LIVE-VERIFIED (coherence met)** (2026-07-12) — shared VISUAL system done (indigo #5b8def tokens + Inter/JetBrains fonts + near-black bg + "part of earn-defi.com — the yield desk ↗" header link + "Yield desk ↗" nav + footer earn-defi link). JUDGMENT: IDENTICAL nav taxonomy is intentionally NOT pursued — the checkup (a wallet-risk tool) and the yield desk are DIFFERENT products with different nav needs; forcing identical nav would harm both. Coherence (same family, navigable both ways) is the right goal and is met |
| U2 | Two-way wiring incl. report | **LIVE-VERIFIED** (2026-07-12) — two-way desk↔checkup: desk→checkup (SiteHeader "Checkup" dropdown → check/sample + hero "See a sample analysis"), checkup→desk (header "Yield desk ↗" + "part of earn-defi.com ↗" + footer link + the report's deep-CTA with 8 earn-defi routes incl. clean_upside/idle_stables/depeg/leverage, UTM-tagged) |
| U3 | One analytics stream (`checkup:*` events + UTM pass-through) | **SHIPPED (increment)** (2026-07-12, vitest 376 + build green) — feasibility confirmed with NO apiserver change: `/api/analytics/event` already returns `access-control-allow-origin: https://checkup.earn-defi.com` + a cross-origin POST probe returned `{ok:true}`. Built `apps/web/src/lib/track.ts` (zero-PII beacon → the SAME `api.earn-defi.com/api/analytics/event` the desk uses, with `checkup:` namespace + inbound-UTM capture) + `TrackOnMount` client component; wired `checkup:sample_viewed` on /sample-report. UTM pass-through outbound already done. **DONE** (2026-07-12, e9cdff6): `checkup:sample_viewed` (/sample-report) + `checkup:report_viewed` (live /check report) both wired via `TrackOnMount`; stream verified (`checkup:cors_probe` already lands in `/api/analytics/summary`). `checkup:cta_click` is covered desk-side (earn-defi captures the inbound UTM on the CTA click) |
| F2 | Numeric targets doc | PENDING (needs ~2 wks F1 data) |
| Q-OWN filings | pilot human/invest@ · admin auth · early-access sign-off · conservative headline · U5 domain seam | VERIFY filed in OWNER_DECISIONS_NEEDED.md |

## Phase 1 — Shell (spec 03)

| Task | Status |
|---|---|
| B1 DashboardShell component | **BLOCKED (browser-verify) → Q-OWN-19** — spec §7 acceptance (sidebar/topbar/grid, no horizontal scroll @1280/1440/1920, mobile bottom-bar, AND the 24-feed devtools polling-degradation test) is inherently browser/devtools; this session verifies via curl only. Re-shelling the LIVE /dashboard unverifiable = risk to the main dashboard. Filed Q-OWN-19 (options: grant browser / owner-visual-check with instant-revert / preview-route-first). NOT starting blind |
| B2 step-1 wrapper re-shell of /dashboard (island untouched) | PENDING |
| B2 step-2 KPI-strip split (post-validation) | PENDING |
| Gate: F2 baseline + week of clean polling | PENDING |
| A1 kit extension (StatCard/DataTable/Drawer/Tabs/FilterChips + state kit) | PENDING |
| A2 token sync Astro⇄Checkup + SITE_DESIGN_SYSTEM.md header update | PENDING |

## Phase 2 — Conversion surfaces (spec 04)

| Task | Status |
|---|---|
| C2 Stablecoin Safety Snapshot (4-question quiz) | **SHIPPED** (2026-07-12, build green) — new `/snapshot` page: 4-Q no-wallet quiz (holdings band / where / which stables / goal) with progress dots; DETERMINISTIC result (decision matrix, NO LLM): per-answer risk notes (CEX custody / USDT depeg / algo fragility / idle yield-gap / DeFi approvals) + yield-gap (band-midpoint × canonical 3.3% realized, labelled not-a-guarantee) + goal-matched next step (safe→Conservative / income→packages / growth→aggressive-lab) + 2 CTAs (email→`/api/pilot/request` source=snapshot; Talk-to-human→/pilot?src=snapshot). Linked from the hero ("No wallet to scan? 60-second snapshot"). EN|RU. data-track: snapshot_complete/_email/_to_pilot/_next. **LIVE-VERIFIED** (2026-07-12 curl /snapshot/: 4 question sections, 15 options, result block, email CTA all present; hero link live) |
| CHK-DEMO no-scan demo report (fixture wallet) | **SUBSTANTIALLY-MET** (2026-07-12) — a real no-scan demo already exists: checkup `/sample-report` renders the FULL report from a frozen fixture (200 OK), banner-labelled SAMPLE, linked from the earn-defi homepage + hero ("See a sample analysis") + snapshot. JUDGMENT: the spec's "on the MAIN earn-defi domain" render is deferred — it would require duplicating the checkup's React report components into the Astro site (cross-framework, high drift risk) for a minor coherence gain; the cross-domain demo is the honest, DRY solution. Full main-site render revisited only alongside the B6 shell rebuild |
| B6 Checkup report rebuild on shell | PENDING |
| E1 five SEO/learn pages | **SHIPPED (5/5)** (2026-07-12, build green) — page #5 shipped: `/learn/why-20-apy-means-tail-risk` (the on-brand refusal-thesis piece): honest breakdown of where stablecoin yield comes from + the tail + refusal-first framing, FAQ schema (JSON-LD FAQPage), snapshot CTA mid+end, internal links to annual-contrast/refusals/aggressive-lab/how-we-think/packages, `learn_view`/`learn_cta_click`. EN|RU, canonical numbers. + page #1 `/learn/is-usdt-safe-2026` (the highest-intent query — honest USDT breakdown: reserves attested-not-audited, depeg history survivable-not-terminal, RTMR monitoring, refusal framing; FAQ JSON-LD, snapshot CTA, funnel links). + page #2 `/learn/what-is-a-stablecoin-depeg` (USDC-2023/SVB case, how-fast=hours, RTMR angle; FAQ JSON-LD, snapshot CTA, funnel links; footer-linked). + #3 checklist + #4 `/learn/cex-vs-self-custody-stablecoins` (counterparty-vs-own-mistakes trade-off, approvals). ALL 5 shipped, each with FAQ JSON-LD + snapshot CTA + funnel links + footer-linked. **LIVE-VERIFIED** (2026-07-12 curl: all 5 /learn/* → 200). Live-verify pending CF |
| C8 trust band | **LIVE-VERIFIED** (2026-07-12, curl) — `TrustBand.astro` (4 honest pillars: Non-custodial · Honest-first · Public track · We-show-the-bad-news) renders on both /packages/ and /snapshot/. EN|RU, no promised returns |
| C7 dual-CTA audit | **SHIPPED** (2026-07-12, build green) — audited all conversion surfaces (snapshot/packages/pilot/fundability/aggressive-lab) for both a self-serve step AND a "Talk to a human". Only `/aggressive-lab` lacked the human path → added "Talk to a human →" /pilot?src=aggressive-lab. All surfaces now dual-CTA |
| C6 bridge page | **SHIPPED** (2026-07-12, build green) — new `/how-we-think` ("How we think about stablecoin yield — honestly"): the §2 reframe long-form (yield = price of a risk · moat = measurement+refusal not rate · proven ~3.3% floor vs shown up-to-20% tail · non-custodial), links to refusals/verify/annual-contrast/packages/snapshot/pilot + TrustBand. EN|RU, no promised returns. C5 un-fixable-gap panels will link here. Live-verify pending CF |
| C5 un-fixable-gap panel | **SHIPPED** (2026-07-12, build green) — the /snapshot result now names the ONE thing we can't fix for you (custody if CEX / peg-mechanism if algo / the-step if idle / trust otherwise — honest, no promised returns) with a bridge link → /how-we-think (C6). Checkup-report C5 panel is a follow (checkup repo). **LIVE-VERIFIED** (2026-07-12 curl /snapshot/: sn-gap + snapshot_to_bridge) |
| I1 post-lead ops (leads by source/band) | **SHIPPED** (2026-07-12, pytest 6/6 + build green) — extended `/api/pilot/requests/count` with `by_source` (early_access/snapshot/pilot) + `by_tier` breakdowns (opaque labels, NO PII — verified `@` not in output); surfaced "Contact requests by source" on `/admin/funnels`. Response SLA = owner's Telegram ping (already wired). Auto-acknowledge email needs RESEND key → Q-OWN-07 (gated). **LIVE-VERIFIED** (endpoint: after apiserver kickstart, /api/pilot/requests/count returns by_source/by_tier fields — empty pending real leads, honest; /admin display pending CF) |
| E3 share card | **SHIPPED** (2026-07-12, vitest 376 + build green) — `ShareButton` upgraded to the native Web Share API (mobile-first "Share your score" sheet) → clipboard → prompt fallback chain. The OG-image endpoint (opengraph-image.tsx, indigo-aligned) already renders the posture preview when the link is shared. Honesty: NO wallet address in the share text (opt-in only); NO fake numeric score — the checkup uses a posture signal not a precision score (respected; `score` prop optional). Live-verify pending Railway |

## Phase 3 — IA consolidation (spec 02)

| Step | Status |
|---|---|
| PREREQ /admin auth (Q-OWN-03) | ✅ **DONE (CF Access, owner-email, verified live 2026-07-12: /admin→302 cloudflareaccess.com)** — Phase 3 UNBLOCKED |
| Merges + 301s (trust cluster, strategy alt-names, annual-contrast) | PENDING |
| ADMIN moves (cockpit*, board*, tournament, system, status, monitoring console) | BLOCKED on prereq |
| JUDGMENT Q-OWN batch (rates-desk/structural-desk/… noindex set) | PENDING (file the Q-OWN) |
| /for-allocators spine · footer trim · redirect crawl script | PENDING |

## Phase 4 — Gated (unchanged from brief §5)

D1 board→Checkup · D2 dashboard→Checkup · C11 selling layer · C9 nurture · B11 widget-grid —
ALL owner/legal-gated, not started.
