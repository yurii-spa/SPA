# SITE UI/UX BACKLOG — deep architect audit (2026-07-11)

> 7-architect parallel audit (`site-uiux-audit` wf_0b25760f, 8 agents, ~769k tok) of earn-defi.com
> (public site + /admin + DeFi Checkup funnel). 50 findings → 40 deduped prioritized items.
> Owner directive: one coherent SELLING customer journey — consistent numbers/naming, clear
> conversion, professional (not a childish toy).

**OWNER-GATED (flag, don't invent):** public tier NUMBERS + tier NAMING (Preserve/Core/Max-Yield
vs Conservative/Balanced/Aggressive — pick ONE) + legal copy + /admin auth (Cloudflare Access).
Code CAN unify to a single source of truth + fix cross-wiring/mislabeling without changing a value.

## Customer journey map

IDEAL PATH: Stranger lands (Google/social/referral) → within 5s reads ONE clear promise and ONE trust anchor → uses the free DeFi Checkup hook (paste wallet, read-only, no email) → sees a warm, plain-language read of their portfolio's risk → is bridged from "here's your risk" to "here's a desk that manages exactly this, honestly" → reaches /packages and compares three coherently-named tiers with one consistent number-per-tier and the tail always shown at the point of choice → chooses to engage → lands on /pilot and completes a real conversion action (email/form) → operator sees the lead in a GATED /admin console.

WHERE THE SITE DIVERGES:
1) FIRST IMPRESSION IS SPLIT-BRAINED. Meta/OG sell a "yield optimizer"; the hero sells a "wallet checkup." Two competing headlines stack above the fold (page H1 vs WalletCheck wc-title). The single most important interactive element (WalletCheck) defaults to Russian on an English-first site (confirmed: useState('ru') + RU fallback), risking a flash-of-Russian on a stranger's first paint. The eyebrow leads with four negations before any benefit, and no concrete trust anchor sits above the fold.

2) THE FUNNEL HAS NO EXIT. The stated endpoint /pilot is orphaned — unreachable from top nav and homepage; only a fundability card and a footer link reach it. Worse, /pilot itself has NO contact mechanism (no email, form, or calendar) — the conversion page cannot convert. Every "Analyze Wallet" CTA scroll-loops to the hero or cross-navigates to a separate checkout app; tier/packages/proof pages circle sideways (Preserve↔Core↔Max, proof→proof) and never terminate in an ask. Contact identity is fragmented (personal Gmail on selling pages, invest@ buried on FAQ, nothing on /pilot).

3) THE PRODUCT LOOKS LIKE TWO HALF-BUILT PRODUCTS. The same three tiers ship under two disjoint name sets (Preserve/Core/Max-Yield vs Conservative/Balanced/Aggressive), cross-wired in the same nav dropdown and even the same page (system.astro). Each tier shows a different headline APY per page; the same conservative/core book is stated as 7+ different numbers (2.7% / ~3.3% / ~3.6% / ~4.25% / ~4.5% / 4–6% / ~6%). The homepage tags a target-only tier "Paper-tracked" (an honesty-invariant breach) and softens the aggressive tier's ~50% tail under "T1+T2, wider diversification" framing exactly where the buyer chooses.

4) THE PUBLIC/ADMIN SPLIT IS NAV-ONLY. /admin has ZERO auth (self-admits "access control in Phase 5") yet exposes the live pilot pipeline, analytics, and decision ledger. The sitemap globs every page and emits ~15 operator internals to crawlers; the footer re-dumps all ~35 pages the header just hid; /cockpit-kit (a synthetic-data dev Storybook) is publicly indexed with a canonical tag.

5) THE CHECKUP HOOK LEAKS INTENT. The report the user actually reads ends on a low-value waitlist form (whose copy promises alerts the backend doesn't send) instead of the earn-defi money CTA; clean wallets dead-end with no reason to convert; the report opens alarm-first with no warm one-liner.

## Top themes

- THE FUNNEL HAS NO TERMINAL CONVERSION ACTION: /pilot is orphaned from nav/homepage AND has no contact mechanism; every CTA loops back to the checkup hook or sideways between tier/proof pages. The single highest-ROI fix cluster — wire proof/tier/checkup traffic into one consistent 'talk to the desk' ask that actually captures a lead.
- ONE PRODUCT, TWO TAXONOMIES: the same three tiers ship as Preserve/Core/Max-Yield AND Conservative/Balanced/Aggressive, cross-wired in the same menus and pages. This is the biggest 'fragmented toy' signal. Requires an owner naming decision, but the wiring (read labels from one source, ban inline literals) is code-doable once the name is chosen.
- NUMBERS DON'T AGREE: the same conservative/core book is quoted 7+ ways (2.7/3.3/3.6/4.25/4.5/4–6/~6%); the RWA floor is both 3.3% and 3.4%; a target-only tier is stamped 'Paper-tracked'; the LIVE badge uses a volatile single-day rate. Corrosive to an honesty-first pitch. Number values are owner-gated, but the plumbing (single snapshot field, status-pill from config, kill the volatile-day badge source) is code-doable.
- FIRST IMPRESSION IS SPLIT & COLD: competing H1s, meta-vs-hero mismatch, WalletCheck defaults to Russian on an EN site, eyebrow leads with four negations, no above-the-fold trust anchor. Several are pure code fixes with no number/owner dependency.
- PUBLIC/ADMIN SEPARATION IS ONLY IN THE NAV: /admin has zero auth while exposing pipeline/analytics/ledger; sitemap globs operator internals to crawlers; footer re-exposes everything; /cockpit-kit synthetic fixtures are indexed. Real security/leak issue, mostly code-doable (allowlist sitemap, noindex, robots, gate) though CF Access enforcement is owner-gated.
- PAGE PROLIFERATION WITHOUT A SPINE: ~37 crawlable pages, 5 overlapping trust/risk pages, 5 'how it works' pages, orphaned selling content (annual-contrast, readiness, yield-lab), duplicate dashboards (/cockpit vs /dashboard vs /cockpit-kit). IA needs consolidation; some merges are owner-gated, orphan-wiring and dead-page removal are code-doable.
- THE CHECKUP HOOK LEAKS PEAK INTENT: report ends on a waitlist (promising alerts the backend doesn't send) not the earn-defi CTA; clean wallets dead-end; report opens alarm-first with no warm human framing. Directly caps funnel conversion.
- A SHIPPED HARD BUG: funnels.astro inline IIFE is unclosed (opens at L32, no })(); before </script> at L54) — the operator funnel page's data fetches never run. One-line fix, no owner input.

## Prioritized backlog


### — NOW —

**UX-03 · P0 · [S] · ✅solo — Remove /cockpit-kit synthetic-data dev Storybook from the public, indexed build**
- loc: `landing/src/pages/cockpit-kit.astro (self-describes 'vanity test surface... synthetic fixture data'); canonical https://earn-defi.com/cockpit-kit; sitemap.xml.ts globs it`
- problem: A public, canonical-tagged page of synthetic fixture numbers, linked from nowhere, is indexable by search/AI engines — an active trust liability for an 'evidence-tagged, never fabricated' product.
- fix: Move under /admin (or an internal-only path), add <meta name=robots content=noindex,nofollow>, and exclude from sitemap. No customer-facing purpose.

**UX-04 · P0 · [M] · ✅solo — Sitemap globs ALL pages — operator internals leak to crawlers**
- loc: `landing/src/pages/sitemap.xml.ts (import.meta.glob('./**/*.astro') emits every non-/admin page)`
- problem: Confirmed: sitemap globs every .astro page (only excludes /admin, [slug], 404/500), so ~15 operator-depth pages (structural-desk, rates-desk, rwa-backstop, cockpit, board, system, exit-nav, due-diligence, readiness, etc.) are still crawlable/indexable. The public/admin split exists only in the top nav.
- fix: Replace glob-everything with an explicit PUBLIC allowlist (the ~12 header-group pages + core trust/legal). Add operator pages to robots Disallow. This is code-doable without deciding page fates; page re-homing (UX-16..) can follow.

**UX-01 · P1 · [S] · ✅solo — Fix unclosed IIFE in admin/funnels.astro (page-dead SyntaxError)**
- loc: `landing/src/pages/admin/funnels.astro (script opens `(function(){` at L32; no `})();` before `</script>` at L54)`
- problem: Confirmed: the inline IIFE is never closed, so the whole script throws a SyntaxError and none of the analytics/interest/pilot fetches run — every tile stays on '—'/offline permanently. Sibling admin/decision-log.astro closes correctly, confirming a typo.
- fix: Add `})();` immediately after the last `.catch(...)` at L53 and before `</script>`. Run `npm run build` to confirm the page compiles.

**UX-02 · P1 · [S] · ✅solo — WalletCheck defaults to Russian on an English-default site (flash-of-wrong-language)**
- loc: `landing/src/components/WalletCheck.jsx:18 (getLang default 'ru'), :44 (useState('ru')), tr() falls back to T[k].ru`
- problem: Confirmed: getLang() returns 'ru' unless documentElement.lang==='en', React state initializes to 'ru', and tr() falls back to Russian. On an <html lang="en"> site an English-first visitor can see the hero's single most important interactive element render in Russian during hydration — a first-paint trust hit on the primary funnel CTA.
- fix: Default to EN to match site default: useState('en'); getLang() default return 'en'; tr() fall back to T[k].en. Follow the same lang source (spa_lang/html.lang) as the rest of the page.

**UX-05 · P1 · [S] · ✅solo — Add noindex + robots Disallow to orphaned/operator public pages**
- loc: `landing/src/pages/{annual-contrast,readiness,yield-lab,monitoring,cockpit,cockpit-kit,structural-desk,rates-desk,rwa-backstop,board,system,exit-nav,due-diligence}.astro; robots.txt`
- problem: Multiple operator/orphan pages render with the public layout and are index,follow. Even before deciding merges, they should not be indexed as standalone public results.
- fix: Add robots noindex meta to operator/orphan pages and Disallow them in robots.txt. Pure code, no number/owner decisions. (Merge/cut decisions tracked separately in UX-16/UX-17.)

**UX-06 · P1 · [S] · ✅solo — Collapse two competing hero headlines into one**
- loc: `landing/src/pages/index.astro:60-70 (hero <h1>) + landing/src/components/WalletCheck.jsx:22,69 (wc-title)`
- problem: The page H1 and the WalletCheck island title fire two near-identical headlines in the same eye-scan region — reads unpolished and dilutes the 5-second value prop.
- fix: Drop wc-title (or demote to a one-line label like 'Free · read-only · no email') so the page H1 is the single hero headline. Widget = input box, not a second pitch. No number/owner dependency.

**UX-10 · P1 · [S] · ✅solo — Drive each homepage tier status pill from strategy_config status (stop stamping target-only tiers 'Paper-tracked')**
- loc: `landing/src/pages/index.astro:197,210 (hardcoded 'Paper-tracked') vs landing/src/data/strategy_config.json (preserve status 'target-profile'/'Not paper tracked', max-yield 'coming-soon')`
- problem: Only one book is evidenced, yet the homepage hardcodes a green 'Paper-tracked' pill on target-only tiers — an honesty-invariant breach that presents a not-yet-tracked profile as evidenced. The status values already exist in strategy_config.json, so wiring the pill to config is code-doable without inventing any new number.
- fix: Render each card's pill from strategy_config.json status/status_label (paper-tracked | target-profile | coming-soon). Only the genuinely evidenced tier gets the green pill. Uses existing data; no new/changed public number.

**UX-11 · P1 · [S] · ✅solo — Add a prominent earn-defi CTA band as the final section of the checkup ReportDashboard**
- loc: `apps/web/src/components/check/ReportDashboard.tsx (final <section> ~L484-512 currently WaitlistForm; deepCta target already computed at L89-98,L478)`
- problem: The report the user actually reads ends on a low-value waitlist (peak-intent position) while the earn-defi money CTA is a mid-page text link. Undercuts the repo's own stated funnel design.
- fix: Add a full-width earn-defi CTA band as the final section, personalized via the existing deepCta target (mirror ReportView's .cta-band). Demote the waitlist to a secondary line. Uses existing routing constants; no new numbers.

**UX-07 · P2 · [S] · ✅solo — Re-order hero eyebrow so a benefit precedes the four caveats**
- loc: `landing/src/pages/index.astro:59 (hero-eyebrow), :72 (hero-trust)`
- problem: The first line above the H1 is four negations ('Research-only · Paper testing first · No deposits · No guaranteed returns') before any benefit — a defensive, low-warmth tone.
- fix: Lead the eyebrow with the positive category ('Free DeFi portfolio checkup') and fold the caveats into the existing hero-trust line under the input, where they reassure at the point of action. Copy-only, no numbers changed.

**UX-08 · P2 · [S] · ✅solo — Make the dashboard-preview mock unmistakably illustrative**
- loc: `landing/src/pages/index.astro:100-133 (.dash-preview: $42,500 / 5.4% APY / Risk Score 72)`
- problem: Concrete round dollar/APY figures with only a small 'Example report' pill can read as a real track record and introduce a stray 5.4% APY. Note: 5.4% is illustrative, not a business number — muting/relabeling it does not change any published book number.
- fix: Add a full-width 'Illustrative example — not a real wallet' caption or a 'SAMPLE' watermark above the card; keep numbers obviously non-round or muted. Copy/CSS only.

**UX-12 · P2 · [S] · ✅solo — Fix checkup waitlist copy that promises monitoring alerts the backend doesn't send**
- loc: `apps/web/src/components/WaitlistForm.tsx + copy.ts L257-274 (landing.waitlist) reused in ReportDashboard.tsx L508-510`
- problem: The shared form promises 'detailed report + alert you when your risk changes' in the report context, but the shared copy says it's a capacity waitlist and the component doc admits 'no email is sent in v0' — an overstatement on an honesty-first product.
- fix: Change the report heading/body to match what the list actually does today (capacity notification), OR give the alert list its own distinct copy only if the backend truly sends alerts. Copy-only; describes current behavior, not a business number.

**UX-09 · P3 · [S] · ✅solo — Route lower 'Analyze wallet' CTAs to focus the hero input, not just scroll**
- loc: `landing/src/pages/index.astro:136,328 (btn → /#analyze); landing/src/components/SiteHeader.astro:111,133 (cta-analyze → /#analyze)`
- problem: Multiple 'Analyze wallet' buttons anchor-scroll to /#analyze without acting; reads as 'the button doesn't work'.
- fix: On click, scroll to hero AND input.focus() the wallet field; reduce repetition to one hero input + one final CTA. Pure code.

**UX-13 · P3 · [S] · ✅solo — Centralize checkup→earn-defi CTA routes + add a cross-repo link check**
- loc: `apps/web/src/components/check/ReportDashboard.tsx L89-98 (deepCta → /packages, /methodology, /strategies, /)`
- problem: Hardcoded absolute earn-defi URLs in a separate repo with no shared contract; a route rename silently 404s the funnel with no test catching it.
- fix: Move the four target routes into one constants module and add a lightweight CI/monitor HEAD check on each earn-defi CTA URL. Pure code.


### — NEXT —

**UX-15 · P0 · [M] · 🔒gated/owner — Wire the funnel end-to-end: reachable, consistent /pilot CTA from nav, homepage, tiers, and proof pages**
- loc: `landing/src/components/SiteHeader.astro (groups L25-57, no pilot); landing/src/pages/index.astro (CTAs → /#analyze only); packages.astro:139-143 (→ status/monitoring, no pilot); strategies/*.astro bottoms (loop sideways); fundability.astro is the only inbound pilot link`
- problem: The stated conversion endpoint /pilot is unreachable from top nav and homepage and only linked from one fundability card + footer. Tier/packages/proof pages loop sideways and never present an ask, so a warm visitor has no next click. Wiring is code-doable, but the CTA label/copy and whether 'invest/pilot' becomes a nav item is an owner/positioning decision.
- fix: Add a persistent header-right CTA (e.g. 'Work with us →'), a bottom-of-page pilot CTA on /packages + each tier page + every proof page (fundability/track-record/refusals/verify/exit-nav), and a pilot CTA in the homepage final-cta. Owner picks the CTA label; engineer wires the links.

**UX-16 · P0 · [M] · 🔒gated/owner — Add a real contact mechanism to /pilot so the conversion page can convert**
- loc: `landing/src/pages/pilot.astro (no mailto/form/input/calendar; only anonymous /api/interest beacon on outbound clicks)`
- problem: The page describing 'the honest ask' offers no way to act — no email, form, or calendar; its only outbound links send users to more proof pages. A ready prospect hits a wall. Needs the canonical business email/endpoint (owner) plus honest-framing copy.
- fix: Add a real conversion action at the visual climax of /pilot: a mailto: to the canonical invest@earn-defi.com (prefilled subject) and/or a minimal request-access form (email + wallet-size band + note) posting to the existing interest endpoint, with the 'not an offer; legal review gates external capital' framing beside it. Owner supplies canonical email/endpoint + legal copy.

**UX-18 · P0 · [M] · 🔒gated/owner — Gate all /admin/* routes behind real access control (currently zero auth)**
- loc: `landing/src/layouts/Layout.astro (admin branch L94-96,195-211 'access control in Phase 5'); landing/src/pages/admin/*.astro (index, funnels, decision-log, monitoring, system-health); no _middleware in src (confirmed)`
- problem: The Operator Console ships with no auth, protected only by noindex + not-linked. Anyone guessing /admin/funnels sees the live design-partner pipeline, product analytics, and the decision/refusal ledger — a real business-pipeline leak. Enforcement (Cloudflare Access binding / signed session) is owner-gated infra.
- fix: Enforce Cloudflare Access on earn-defi.com/admin (owner already uses CF Access per project memory) and/or add an Astro middleware that 401s /admin/* without a valid CF-Access JWT. Until enforced, stop /admin/index and /admin/funnels from rendering live pipeline counts. Owner must configure CF Access; engineer wires middleware.

**UX-23 · P0 · [M] · 🔒gated/owner — Adopt ONE canonical public tier name set across the whole site**
- loc: `landing/src/lib/tier_bands.json (en 'Conservative' / alt_en 'Preserve', _note flags owner choice #6); strategy_config.json (Preserve/Core/Max Yield); index.astro:196-233; packages.astro; strategies/{index,preserve,core,max-yield}.astro; SiteHeader.astro:31-35; system.astro:32,37 (both sets on one page)`
- problem: The same three tiers ship under two disjoint names, cross-wired in the same nav dropdown and even the same page — the biggest 'two half-built products' signal. Picking the canonical set is an explicit owner decision (tier_bands _note calls it 'owner choice #6').
- fix: Owner picks ONE public set (reviewers recommend Conservative/Balanced/Aggressive — matches the tail framing and the canonical tier_bands key). Then render every tier label from tier_bands.json[key], rename/redirect /strategies/{preserve,core,max-yield} routes, add a lint/grep ban on inline tier-name literals. Owner decision gates the code.

**UX-24 · P0 · [L] · 🔒gated/owner — Define ONE canonical 'current book APY' number and source it everywhere**
- loc: `track_snapshot.json:16,21; packages.astro:14,85,106; strategies/core.astro:18,46; strategy_config.json:41; preserve.astro:38; strategies/index.astro:67; faq.astro:29; tournament.astro:87; methodology.astro:163`
- problem: The same conservative/core book is stated 7+ ways (2.7 / ~3.3 / ~3.6 / ~4.25 / ~4.5 / 4–6 / ~6%); the LIVE badge contradicts the prose. This is the owner's exact 'everywhere different numbers' complaint and it undermines the honesty pitch. The canonical value + its meaning is owner-gated; the plumbing (one snapshot field referenced everywhere, delete hardcoded strings) is code once decided.
- fix: Owner defines the canonical current-book APY (recommend evidenced track-to-date annualized, not volatile paper_apy_pct) and its label pattern ('target band X / realized-to-date Y'). Compute once in track_snapshot.json, reference everywhere, delete every hardcoded ~3.3/~3.6/~4.5/4–6/~6% string.

**UX-14 · P1 · [S] · 🔒gated/owner — Point the /packages 'LIVE ~X%' badge at a stable track-to-date APY instead of the volatile single-day rate**
- loc: `landing/src/pages/packages.astro:17 (liveApy = snap.paper_apy_pct) rendered at :106; contradicts '~3.3%' prose at :14,:85`
- problem: paper_apy_pct is the single-day annualized rate (swings 3.2–8.5% day to day), so the public Conservative 'LIVE ~%' badge regularly exceeds the stated band and contradicts the '~3.3%' prose inches away. Flagged before, still live. The FIX (change which field the badge reads + relabel 'track-to-date') is code-doable, BUT it requires an owner-blessed canonical track-to-date field/number, so mark it code-doable only once that field exists.
- fix: Add a stable track_to_date_apy_pct to track_snapshot.json (owner-gated value/definition), point the badge at it, and relabel 'track-to-date' not 'LIVE ~'. Then it lands in-band and matches prose.

**UX-17 · P1 · [S] · 🔒gated/owner — Standardize public contact identity — remove personal Gmail from selling pages**
- loc: `mailto:yuriycooleshov@gmail.com in strategies/{preserve,core,max-yield,research}.astro (e.g. preserve.astro:417), due-diligence.astro, security.astro, trust.astro; invest@earn-defi.com only in faq.astro`
- problem: Personal Gmail appears on the exact tier pages a prospect reads before converting, while the business invest@ is buried on FAQ — reads as a hobby project and fragments where leads land.
- fix: Replace the personal Gmail with invest@earn-defi.com across all selling/conversion pages and put the same email on /pilot's CTA. Owner should confirm invest@ is the canonical inbox before the swap.

**UX-25 · P1 · [M] · 🔒gated/owner — Reconcile per-tier APY bands to one source (tier_bands.json) across hero/card/nav/packages**
- loc: `strategy_config.json target_apy (6/5/15); tier_bands.json bands (2–6 / 6–12 / 12%+); core.astro '4–6%'; preserve.astro/StrategyCard '~6%'; SiteHeader nav bands; packages '12–20%' caveat`
- problem: Each tier shows a different headline band per page (Core: ~5% card / 4–6% hero / 6–12% nav; Conservative: 2–6 / ~6; Aggressive: ~15 / 12%+ / 12–20%). Reconciling requires deciding the canonical band per tier (owner), then rendering it everywhere.
- fix: Make tier_bands.json bands the single source; delete or align strategy_config.target_apy to them; render the band string in every hero/card/nav; only the LIVE evidenced page may show a more-precise number, clearly labeled 'live paper' vs 'target band'. Band values owner-gated.

**UX-26 · P1 · [M] · 🔒gated/owner — Reconcile which tier is the real evidenced/paper-tracked book**
- loc: `index.astro:197 (Preserve 'Paper-tracked') vs strategy_config.json (Preserve 'target-profile'/'validation pending'); tier_bands.json conservative.live=true; homepage pkgApy wiring maps Preserve NAME to conservative DATA`
- problem: The homepage pins 'live evidenced' status to a tier its own detail page says isn't tracked — an off-by-one between the two taxonomies that risks overstating an untracked profile. Which tier IS the live book is an owner/factual decision.
- fix: Owner confirms the evidenced book (the $100k-since-2026-06-22 track). Map the 'Paper-tracked' pill + live snapshot to that tier only; mark the others 'Target profile — not yet paper-tracked'. UX-10 does the mechanical pill wiring; this resolves the mapping.

**UX-27 · P1 · [M] · 🔒gated/owner — Make the homepage aggressive/Max-Yield card tell the same tail story as /packages**
- loc: `index.astro:221-232 (Max Yield: 'T1+T2','wider Tier 2 diversification','no open liquidation risk') vs strategies/max-yield.astro + packages.astro (levered PT loops, unhedged, ~50% drawdown, liquidation cascade)`
- problem: At the highest-traffic tier-selection surface the aggressive card is framed as a mild diversification book, contradicting the ~50% tail rendered in its own drawdown cell — the tail is technically present but buried under softer framing at the point of choice, and max-yield.astro's 'no liquidation risk' directly conflicts with packages' 'liquidation-cascade risk'. Requires owner sign-off on the corrected risk copy.
- fix: Replace 'wider Tier 2 diversification / T1+T2' with the real mechanic (levered PT carry loops, unhedged directional — refused for live) and surface the ~50% tail as a prominent warning line. Reconcile the 'no open liquidation risk' vs 'liquidation-cascade risk' conflict. Risk copy is owner-gated.

**UX-19 · P2 · [S] · 🔒gated/owner — Trim the footer to the public spine (stop re-exposing operator surface the nav hid)**
- loc: `landing/src/components/SiteFooter.astro (L5 'surfaces every orphan page'; ~35 links incl /board, /structural-desk, /rates-desk, /rwa-backstop, /exit-nav, /due-diligence, /system, /status)`
- problem: The footer is a catch-all that re-links every operator page the header deliberately removed, defeating the IA split and reading like an org chart.
- fix: Cut to Product (Checkup, Strategies, Track Record, Academy, Dashboard), Company (FAQ, Fees, Blog, Contact), Trust & Legal (Trust, Risk Disclosure). Move operator/proof depth to /admin. Which pages stay public trust vs operator is a light owner call; the trimming itself is code.

**UX-20 · P2 · [M] · ✅solo — Warm one-line plain-language headline atop the checkup report (before the numeric grid)**
- loc: `apps/web/src/components/check/AnalysisSummary.tsx L74-108 + ReportDashboard.tsx L132-153 (posture chip + 6-cell grid + stacked alert cards)`
- problem: The first-run payoff leads alarm-first with a posture chip, stat grid, and warning cards — a cold audit dump with no warm human on-ramp.
- fix: Add one plain-language headline derived from existing topRisk + concentration fields ('Your $X portfolio is mostly USDC on 2 chains; the main thing worth attention is …') above the grid. Uses already-computed fields; no invented numbers.

**UX-21 · P2 · [M] · ✅solo — Give clean-wallet checkup results an upside conversion path**
- loc: `apps/web/src/components/check/ReportDashboard.tsx L98 (fallback deepCta 'Explore SPA strategies →'), L307-311, L448; idle-stables branch only fires at idlePct>=40`
- problem: Clean wallets collapse to 'no risk / no actions' and the weakest generic CTA — the best yield prospects (idle stables) get the least compelling path.
- fix: For clean wallets, pivot to opportunity using already-computed capital_efficiency + estimated_yield and route to /packages with an idle-stables framing. Lower the idle threshold so moderately-idle clean wallets still get a CTA. Uses existing fields; the specific APY phrase should come from the shared canonical number (see UX-24).

**UX-22 · P2 · [M] · ✅solo — Consolidate the two divergent checkup entry forms into one**
- loc: `apps/web/src/components/SubmissionForm.tsx (hero) + check/CheckForm.tsx (/check) + Hero.tsx L40 (button Links to /check instead of submitting hero field)`
- problem: Two near-identical wallet forms with different UX; the hero submit button routes to /check rather than submitting the typed field, and /check shows a second identical form — the user sees the form twice and logic can drift.
- fix: Consolidate to one shared form component; on /check with an address present, collapse the re-entry form; make the hero submit button submit the hero field. Pure code.

**UX-28 · P2 · [S] · 🔒gated/owner — Fix the SiteHeader nav dropdown that teaches two names for one tier**
- loc: `landing/src/components/SiteHeader.astro:31-35 (items labelled Preserve/Core/Max-Yield, descs pull TIER_BANDS.conservative/balanced/aggressive; + /packages + /aggressive-lab links)`
- problem: One dropdown surfaces Preserve AND Conservative, Max Yield AND Aggressive, making the lineup feel larger and undermining 'three tiers' clarity. Depends on the naming decision (UX-23).
- fix: After UX-23, relabel nav items to the canonical set, add a one-line group intro ('Three tiers · Conservative → Aggressive'), keep Aggressive Lab clearly as a drill-down. Gated on UX-23.

**UX-30 · P2 · [S] · 🔒gated/owner — Fix the RWA floor stated as both ~3.3% and ~3.4% (sometimes same sentence)**
- loc: `yield-lab.astro:6,72,145; strategies/index.astro:137; structural-desk.astro:35,434; faq.astro:29; annual-contrast.astro:10,103; methodology.astro:163`
- problem: The reference floor the whole 'we beat the floor' thesis rests on is quoted two ways, reading like a rounding error. The canonical floor value is owner/data-gated (codebase computes ~3.4% dynamically).
- fix: Fix the floor at one value (surface from the live RWA feed field, or hardcode ~3.4% consistently); never write '~3.3% floor' — reserve ~3.3% for the desk book only. Value confirmation is owner/data-gated.

**UX-31 · P2 · [S] · 🔒gated/owner — Replace faq.astro hardcoded 'roughly a third of the way' with the dynamic day count**
- loc: `landing/src/pages/faq.astro:89-90 vs track_snapshot.json:8 (real_track_days=20)`
- problem: FAQ hardcodes 'roughly a third of the way' through 30 days while the snapshot shows 20/30 — a materially wrong, decaying progress claim; every other surface reads it dynamically.
- fix: Read real_track_days from track_snapshot.json (or reword to a non-decaying stance pointing at /track-record). Uses an existing field, but 'is 20 the correct published day count' is a light owner/factual check — treat value as owner-confirmed.

**UX-29 · P3 · [S] · 🔒gated/owner — Render target bands (not bare '—') where live APY is null**
- loc: `track_snapshot.json packages.aggressive/balanced {apy_pct:null,dd_pct:null}; index.astro pkgApy renders '—' for Core/Max`
- problem: Null-live tiers show a bare '—' that reads as broken data rather than deliberate 'no live track yet', while their detail pages assert confident targets.
- fix: Where live is null, render the same tier_bands band string with an explicit 'target · not yet paper-tracked' qualifier (extend the existing tier-cap copy). Band string comes from tier_bands (UX-25); the null-fallback wiring itself is code.


### — LATER —

**UX-33 · P1 · [S] · 🔒gated/owner — Wire orphaned selling/trust pages into the spine or cut them**
- loc: `landing/src/pages/{annual-contrast,readiness,yield-lab}.astro (reachable from neither header nor footer)`
- problem: Strong conversion/trust content (annual-contrast 'cost of chasing yield', readiness 'code proved vs owner-only', yield-lab) is sitemap-only — indexable but unnavigable by humans, wasting effort and diluting crawl surface.
- fix: Merge each into the spine (annual-contrast → /packages or Track Record; readiness → Track Record/status; yield-lab → /research) or cut. Which merges happen is a light IA/owner call.

**UX-34 · P1 · [M] · 🔒gated/owner — Collapse the 5-page trust/risk cluster into one warm Trust + one legal page**
- loc: `landing/src/pages/{trust,security,risk,risk-disclosure,disclaimer}.astro; footer Trust & Legal column`
- problem: Five heavily-overlapping doors (incident response on /trust AND /security; risk on /risk AND /risk-disclosure; /disclaimer defers to /risk-disclosure) read as box-checking and hide the canonical page.
- fix: Collapse to /trust (absorb security's contract/wallet/deploy + risk's philosophy/gates/stress) and one legal page (merge disclaimer into risk-disclosure); redirect the rest to anchors. IA/owner-gated merges.

**UX-35 · P1 · [M] · 🔒gated/owner — Establish one canonical 'How it works' + one research hub; move the rest behind /admin**
- loc: `landing/src/pages/{methodology,system,structural-desk,research,yield-lab}.astro`
- problem: Five 'how/why it works' pages with no spine (methodology vs system vs structural-desk vs research vs yield-lab) — a curious allocator can't tell what to read; several float loose in footer/sitemap.
- fix: Keep /methodology as the public 'how it works' and /research as the research hub (absorbing yield-lab); move /system + /structural-desk (with rates/rwa children) behind /admin. IA/owner-gated.

**UX-32 · P2 · [M] · 🔒gated/owner — Enforce the single-source pattern for tier names + book APY with a CI lint**
- loc: `index.astro:13, packages.astro:5-7, tier_bands.json:2 (all claim 'single canonical source, can never diverge') vs 8+ files still hardcoding ~3.3% + parallel tier names`
- problem: Code comments claim divergence is solved, but only band-label strings and hero snapshot fields were centralized; per-book APY numbers and tier names are still hardcoded, giving a false sense that consistency is handled.
- fix: After UX-23/UX-24, add a CI grep that bans inline tier-name literals and hardcoded book-APY strings so the single-source claim becomes enforced, not aspirational. Depends on the canonical decisions landing first.

**UX-36 · P2 · [M] · 🔒gated/owner — Pick one canonical live dashboard; move the other + cockpit-kit behind /admin**
- loc: `landing/src/pages/{cockpit,dashboard,cockpit-kit}.astro (cockpit.astro self-describes as 'distinct from /dashboard'); footer links /dashboard only`
- problem: Two parallel live front-ends (CockpitDashboard vs DashboardLive) plus synthetic cockpit-kit are all public with no story about which is 'the app' — duplicated build surface and a coherence smell.
- fix: Keep /dashboard as the public number; move /cockpit + its Cockpit* islands under /admin (cockpit-kit already handled in UX-03). Owner decides the canonical surface.

**UX-37 · P2 · [M] · 🔒gated/owner — Create one allocator spine (/for-allocators or /pilot hub) for the investor-pitch pages**
- loc: `landing/src/pages/{fundability,competitive-position,annual-contrast,pilot,due-diligence}.astro (scattered across footer + one nav item)`
- problem: The highest-value audience (allocator/design-partner) is served by 5 pages that are scattered and partly orphaned, with no 'For Allocators / Invest' entry point.
- fix: Build one allocator hub laddering case (fundability) → edge (competitive-position + annual-contrast) → proof (due-diligence, verify) → ask (pilot); add as a nav item if allocators are a real audience. Depends on UX-15/UX-16 conversion wiring; IA/owner-gated.

**UX-40 · P2 · [M] · 🔒gated/owner — Add above-the-fold trust anchor + bridge hero to the yield product**
- loc: `landing/src/pages/index.astro:57-91 (hero: checkup-only value prop; 'Powered by SPA Strategy Lab' footnote); trust signals only at 240-264/307-321`
- problem: The hero is entirely checkup-framed with no concrete above-the-fold credibility marker (evidenced-day count, NAV-reconciled chip, 'paper track since Jun 22'), and the sellable yield desk doesn't surface as a value prop until half the page down — many yield-intent prospects bounce.
- fix: Surface one honest trust chip in the hero (live evidenced-day count / NAV-reconciled state — pulled from existing track_snapshot fields) next to the powered-by line, and add a secondary hero CTA to /packages bridging 'here's your risk → here's a desk that manages it'. Uses existing fields but the exact trust-claim copy is owner-gated.

**UX-38 · P3 · [S] · 🔒gated/owner — Deduplicate the RTMR monitoring surface (public /monitoring vs /admin/monitoring)**
- loc: `landing/src/pages/monitoring.astro + landing/src/pages/admin/monitoring.astro (admin/index links the admin one)`
- problem: RTMR exists as both a public orphan page and an admin page — two copies with unclear ownership; public /monitoring is sitemap-only.
- fix: Keep RTMR under /admin/monitoring for operators; if a public 'we watch risk' proof is wanted, make it a section on /trust rather than a standalone orphan. Remove /monitoring from the public sitemap (covered by UX-04 allowlist). Light owner call.

**UX-39 · P3 · [S] · 🔒gated/owner — Give the checkup compare table a click-worthy conservative framing (don't lead with 'refused')**
- loc: `apps/web/src/components/check/ReportDashboard.tsx L466-481 (Conservative 2–6% / Balanced research-paper / Aggressive 'refused for live')`
- problem: As the bridge to the paid product the compare table leads with the lowest band and a 'refused' tier, and restates the ~3.3% figure under review — if it drifts from earn-defi, the funnel shows two different 'real' APYs.
- fix: Keep the honesty/tail disclosure but frame the conservative tier around 'real, paper-tracked, verifiable' rather than the raw low band; source the APY from the shared canonical value (UX-24) so checkup and earn-defi never disagree. Depends on UX-24.
