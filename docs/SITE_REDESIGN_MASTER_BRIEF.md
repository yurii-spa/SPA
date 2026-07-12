# SITE REDESIGN MASTER BRIEF (v3 — audited, marketing-first)

> **⚠️ EXECUTION LAYER LIVES IN `docs/redesign/` — start at `docs/redesign/00_INDEX.md`.**
> This brief = strategy/priorities; the redesign/ specs = task-level detail (files, EN+RU copy,
> data sources, acceptance criteria, verification). Where a spec is more concrete, follow the spec.

> **What this is:** the external-analyst audit of `docs/PRODUCT_REDESIGN_ROADMAP_H2_2026.md` (v2),
> commissioned by the owner 2026-07-12, rebuilt into the **authoritative execution brief**.
> **Where this brief and roadmap-v2 conflict, THIS BRIEF WINS.** Roadmap-v2 stays as background.
>
> **Inputs:** (1) line-level fact-check of every code claim in roadmap-v2 against the repo;
> (2) full cross-check against the prior 7-architect audit `docs/SITE_UIUX_BACKLOG.md` (40 items)
> so nothing already found gets lost; (3) fresh competitive marketing research (Ethena, Ondo,
> Maple, Yearn, Superform, Nexo, revoke.cash/De.Fi funnels, Robinhood-style waitlists) + a blunt
> conversion critique of the live earn-defi.com.
>
> **Owner directive override (2026-07-12, supersedes roadmap-v2 §5):** the site must SELL.
> Think like a marketer, not a compliance officer. All legal/solicitation work is a **separate
> deferred track** (after long paper + live test on owner's own money) — it must NOT sit on the
> critical path, gate P0 tasks, or dominate copy. What remains as a hard floor (because it IS
> the marketing moat, not because it's legal): **never fabricate a number, never label paper as
> live** — everything else (framing, urgency, FOMO mechanics, aspiration) is fair game.

---

## 1. Audit verdict on roadmap-v2

**Spine APPROVED:** two-door funnel (dashboard-showroom → Checkup → /pilot), app-surface
shell mode-switch (marketing pages stay single-column), instrument-first, "prove the shell on
one page before extracting the kit". Keep all of it.

**Rejected / corrected:**

| # | Roadmap-v2 says | Reality (code-verified) | Consequence |
|---|---|---|---|
| 1 | "No shared component kit; two drifting CSS systems; 5 near-black bgs + 5 header treatments" | **FALSE — stale.** `landing/src/components/ui/` kit exists (Badge/Button/Card/Table/StatusPill/… + `tokens.js`), imported by ~32 files; ONE `:root` token block in `Layout.astro`; ONE canonical `SiteHeader`. That language is quoted from `docs/SITE_DESIGN_SYSTEM.md` §1.1 which is a pre-rebuild SPEC audit. | **A1/A2 shrink from L+L to M total**: extend the existing kit (add StatCard/DataTable-sort/Drawer/Tabs/FilterChips + state kit), don't build one. Update SITE_DESIGN_SYSTEM.md status header. Phase-0 estimate drops. |
| 2 | "/dashboard polls 6 endpoints @15s" | **~24 endpoints** (SSOT + 23 independent feeds, `DashboardLive.jsx:780-804`), each with its own offline state + PanelBoundary. | Re-shelling /dashboard is **L+, riskiest single task in the plan** — do it as layout-wrapper-around-existing-island first (shell OUTSIDE, island intact), not a rewrite. |
| 3 | "Live WaitlistForm on Checkup = most exposed artifact, LEGAL-0 must review NOW" | **No `WaitlistForm` exists anywhere in `landing/`** (zero grep hits). Only live capture form = `/pilot` (POST `/api/pilot/request` → Telegram, built 2026-07-12, tests exist). | **Kill LEGAL-0 as P0.** Its premise is false. Legal review moves to the deferred legal track. |
| 4 | "36 pages, 34/36 narrow columns" | Directionally TRUE (35/36 of *top-level* pages; **95 page files** total incl. subdirs: academy 28, cockpit 7, board 5, admin 6, strategies 11…). | Cruft-consolidation (Workstream J) is bigger than v2 sized; page inventory in §7. |
| 5 | (missing entirely) | Prior 40-item audit `docs/SITE_UIUX_BACKLOG.md`: ~19 shipped, ~16 still open — v2 silently drops `/admin` zero-auth, personal Gmail on selling pages, single-source-of-numbers plumbing, marketing-IA consolidation. | Carried forward explicitly in §6. **Do not retire SITE_UIUX_BACKLOG.md until §6 items land.** |
| 6 | Sequencing: all conversion value gated behind a 6–8-week Phase-0 shell build | Marketing research: the highest-ROI fixes are **framing + plumbing, not layout** — doable in days. | **New Phase 0 = SELL SPRINT (§4)** ships first; the shell becomes Phase 1. |

---

## 2. The marketing thesis (from competitive research — read before writing any copy)

What every Tier-1 comp does above the fold: **one big number + one verb CTA + a 3-item trust
strip.** Nobody leads with methodology. Everyone anchors yield **against banks/T-bills** (3–5%
only sounds good next to 0.5%). Ethena advertises a **period-average** APY, not spot — exactly
the fix for our volatile `apy_today_pct`. Ethena turned attestations into homepage marketing;
our refusal log + hash-chain + verifier is *rarer* than their PoR and currently presented like
engineering docs.

**Core reframe: stop selling the yield number, sell the floor + verified upside pipeline.**
- We cannot win a headline-APY war at 3.3% and we don't need to: 3.3% realized with **0.0%
  realized drawdown** next to "bank 0.4% / T-bills ~3.5% you can't audit" is a strong pitch.
- The 15–25%/up-to-20% research tiers are the aspiration engine: "our engine already found
  them — **and found their tails — so it refuses to run them live until they pass 30 forward
  days + a real vol event. That refusal is the product. Want in when they clear?**" Same facts,
  opposite valence: from confession → controlled pipeline.
- The 30-day evidenced track is a **built-in countdown** (progress bar = urgency with zero
  fabrication). The aggressive-tier gate is **built-in scarcity** (early-access list).

**Vocabulary discipline (single most important copy rule):** `X% realized` for the live
conservative track (stable track-to-date annualized, never the volatile daily spot);
`up to Y% target` for research tiers (owner already decided "up to {max}%" display — keep it,
but ALWAYS pair with the word *target* and the tail). Never "expected/projected/guaranteed".
One canonical numbers source (`landing/src/lib/tier_bands.json` + track API) — **three surfaces
currently tell three different stories (up-to-6/12/20 vs 15–25 vs spot ~4.4% vs ~3.3%) and that
contradiction is instant credibility death for exactly the sophisticated visitor we want.**

**Blunt critique of the live site (fix targets):** homepage hero sells the free tool, not the
business; checkup report captures nothing and computes no yield-gap (100% funnel leak at the
strongest moment); /packages is an engineer's risk memo wearing a pricing-page URL (5 numbers
per tier, internal jargon "L6 / outside RiskPolicy / NOT yet trustworthy" above the fold);
/pilot headline is 15 words of jargon with no human, no calendar; zero urgency mechanics
anywhere.

---

## 3. Workstreams (v2's A–J kept, plus M and N)

| # | Workstream | Change vs v2 |
|---|---|---|
| **M** | **Conversion mechanics / sell sprint** *(NEW — Phase 0)* | The 12 marketing moves, §4 |
| **N** | **Single source of numbers** *(NEW — from UX-24/25/28/29/30/32)* | One canonical number set + CI lint; prerequisite for all selling copy |
| **U** | **One-product seam: Checkup ⇄ site** *(NEW — §5b)* | checkup.earn-defi.com must feel like a PAGE of earn-defi.com, not a second site — long before the gated D2 merge |
| A | Component kit | **Rescoped: EXTEND existing `ui/` kit**, not build |
| B | Dashboard-shell | Kept; /dashboard re-shell = wrapper-first, L+ |
| C | Checkup conversion layer | Kept; copy tone flips per §2 |
| D | Board → Checkup migration | Kept, gated, LAST |
| E | SEO/acquisition content | Kept |
| F | Measurement/instrumentation | Kept — runs parallel with Phase 0 from day 1 |
| G/H | Perf / a11y | Kept as Phase-1+ gates |
| I | Post-lead ops | Kept |
| J | Cruft → /admin | Kept **but hard-blocked on admin auth (§6 UX-18 / Q-OWN-03)** |
| ~~LEGAL~~ | ~~LEGAL-0 / C10-as-gate~~ | **Moved off critical path** → deferred legal track. Keep the existing footer disclaimer boilerplate as-is; do not add new legal copy to hero/CTA surfaces. |

---

## 4. Phase 0 — SELL SPRINT (do FIRST; ~1–2 weeks; no shell required)

Run **F1/F2 instrumentation in parallel from day 1** (wire `spaTrack` funnel events:
door → report/calculator view → CTA click → /pilot or early-access submit; the beacon +
109 `data-track` attrs already exist — this is wiring, not building). Baseline numbers before
copy changes where possible; don't block shipping on it.

Order within the sprint = dependency order: **N/M5 (numbers) → M1/M2/M10 (framing) →
M3/M4/M12 (mechanics) → M7/M9 (capture) → M6/M11 (reinforcement)**.

- **M5 / N1 — One canonical number everywhere.** `[P0][M]` Kill remaining volatile
  `apy_today_pct` displays; conservative shows **"~3.3% realized (track-to-date)"** with the
  owner-decided "up to 6%" as the band, not the headline; reconcile RWA floor 3.3-vs-3.4
  (UX-30); all tier numbers read from `tier_bands.json` / track API only (UX-25); fix nav
  teaching two names per tier (UX-28); null-live tiers render target band + "not yet
  paper-tracked", not "—" (UX-29). Then **N2 `[P1][S]`: CI lint** banning inline tier-name
  literals + hardcoded APY strings outside the canonical sources (UX-32). *Acceptance: grep
  for APY literals on pages returns only canonical-source reads; every page tells one story.*
- **M1 — Homepage hero rewrite** (`index.astro`). `[P0][S]` Lead with the yield desk, not the
  free tool: headline class "A stablecoin yield desk that proves every number"; sub: "~3.3%
  realized on the live conservative track, 0.0% realized drawdown · up to 20% targets in
  research, published with their tails". Dual CTA: **"Check your wallet free"** (keeps checkup
  as door #1) + **"See the live track"**. *Acceptance: hero communicates product-in-5-seconds;
  checkup stays one click away.*
- **M2 — Comparison bar** (component; homepage + /packages). `[P0][S]` "Bank savings ~0.4% ·
  US T-bills ~3.5% · **SPA Conservative ~3.3% realized, auditable block-by-block** · Aggressive
  up to 20% target (research)". The single highest-impact block per research (Superform/Ethena
  pattern).
- **M3 — Yield calculator with slider** (component; /packages + homepage section). `[P0][M]`
  "$50,000 → ~$1,650/yr at the realized rate" solid line; dashed line "if aggressive targets
  validate: up to $10,000/yr — research stage, max backtest drawdown ~50%". Dual-line +
  tail-in-the-calculator = selling AND fabrication-proof. Nexo/Superform pattern; user sells
  himself.
- **M4 — Live trust/counter strip** (component under hero). `[P0][S]` Four live items from
  existing APIs: **"N/30 evidenced days"** (progress bar), **"0.0% realized drawdown"** (our
  most marketable number, currently buried), **"N strategies refused for live capital"**
  (refusal count), **"Non-custodial · 45 autonomous monitors 24/7"**.
- **M12 — Progress-bar countdown as a feature.** `[P0][S]` The 30-day gate rendered fat and
  prominent ("go-live validation: day N of 30") + "follow the countdown" CTA → early-access
  list (M7). Urgency with zero fabrication.
- **M7 — Aggressive-tier early-access list.** `[P0][M]` Robinhood-pattern waitlist: "Aggressive
  goes live only after 30 forward days + 1 real vol event — **join to get the validation report
  first**" + position number ("You're #23"). Reuse `/api/pilot/request` infra with a
  `source=early_access` tag; counter on /admin. *This turns our gating criteria into scarcity.*
- **M10 — /packages framing flip.** `[P0][M]` One number + one status chip per tier card;
  everything else (drawdown caps, L-levels, backtest worst, "outside RiskPolicy") behind an
  expandable **"Full risk sheet →"** (keep every honest fact — move it below the fold).
  Rewrite the "NOT yet trustworthy / refused" copy per §2 reframe (controlled pipeline, not
  confession). Also applies to homepage tier cards (extends shipped UX-27, keeps its honesty).
- **M6 — Refusal-as-product.** `[P1][S]` Copy pass on /packages, /aggressive-lab, /refusals,
  homepage: "We publish what we refuse to touch — nobody else does", refusal count badge
  linking to the public refusal log + verifier. Ethena made PoR marketing; we make refusals
  marketing.
- **M9 — /pilot humanization.** `[P1][S]` Kill the 15-word jargon headline → "Talk to the
  person who built this — 30 minutes, no pitch, no obligation." Add source + holdings-band
  fields (v2's C4). Name/photo/calendar-link = **Q-OWN (§8)**; ship the copy fix now, add the
  human when owner answers. Also remove personal Gmail from selling pages when owner provides
  the invest@ inbox (UX-17, same Q-OWN).
- **M11 — Asset-entry cards** (homepage section). `[P2][S]` "Earn on USDC / on idle stables /
  on your existing Aave position" — entry by user situation, not internal tier taxonomy
  (Yearn pattern).
- **M8 — Checkup report yield-gap + optional capture.** `[P0][M]` **Biggest funnel leak.** In
  the `defi-checkup` repo (separate, private, normal git flow — NOT API-push): report and
  clean-wallet result (UX-21) end with *"Your $X idle at 0% could earn ~$Y/yr at our realized
  conservative rate → see how / email me this report"* → optional email → /pilot bridge. First
  report stays ungated (C3 — protect the aha).

**Sprint DoD:** every number on every page from one source; hero sells the desk; comparison
bar + calculator + counter strip + countdown live; early-access list capturing; /packages
flipped; checkup report captures yield-gap leads; funnel events flowing into
`/api/analytics/event`; `cd landing && npm run build` green before every push.

---

## 5. Phases 1–4 (roadmap-v2 phases, corrected)

- **Phase 1 — Shell on one surface** (v2 Phase-0, rescoped): B1 `DashboardShell`
  (sidebar+topbar+12-col grid) → B2 re-shell `/dashboard` as **wrapper around the existing
  island** (24 feeds intact; no logic rewrite) → gate on F2 numbers → A1 extend `ui/` kit
  (StatCard, sortable DataTable, Drawer, Tabs, FilterChips + empty/error/loading/offline state
  kit) → A2 sync tokens Astro↔Checkup. Update `SITE_DESIGN_SYSTEM.md` header (SPEC → partially
  built + link kit). Realistic: **3–5 wks**, not 6–8 (kit exists).
- **Phase 2 — Conversion surfaces on the shell** (v2 Phase-1 remainder + Phase-2): C2
  no-wallet **Stablecoin Safety Snapshot** quiz (standalone cheap HTML, week 1); **CHK-DEMO**
  no-scan demo report page (owner idea W5); C1 no-wallet door; B-ENTRY dashboard→checkup hook;
  E1 SEO pages ("is USDT safe", "what is a depeg", …) feeding the snapshot; C5/C6/C7/C8
  bridge/trust/dual-CTA; E3 share-card; I1 post-lead SLA + qualification; B6 Checkup report
  rebuild FIRST on shell, then B3 /monitoring /aggressive-lab /packages; B4/B5/B7/B8 tables/
  drawers/scorecards; G1 perf budget; H1 a11y on new primitives; QA1 visual-regression +
  token-drift test; F3 funnel dashboard segmented by holdings band.
### 5b. Workstream U — One-product seam (Checkup ⇄ site, starts in Phase 0/1, NOT gated)

**Problem:** Checkup lives in a separate repo on a separate subdomain (Railway) — without an
explicit workstream it stays "a second site" with its own header, nav and look. The funnel
(dashboard-showroom → Checkup → /pilot) only converts if the user **never notices the seam**.
The full merge (D2: fold dashboard into the Checkup product) is Phase-4/owner-gated — but
*feeling* like one product is cheap and must NOT wait for it:

- **U1 `[P0][M]` Shared chrome.** Checkup renders the SAME header/nav/footer as earn-defi.com
  (same logo, same nav taxonomy incl. Strategy Lab / Track Record / Academy links back to the
  main site, same EN|RU toggle, same "Analyze Wallet" CTA semantics). Implementation: port
  `SiteHeader`/`SiteFooter` markup + tokens into the checkup repo (manual sync is fine at this
  scale; QA1's token-drift test later guards divergence). *Acceptance: screenshot of checkup
  home next to earn-defi.com — indistinguishable chrome.*
- **U2 `[P0][S]` Bidirectional wiring, both directions always visible.** Dashboard → Checkup
  hook = B-ENTRY. Checkup → site: the earn-defi CTA band (UX-11, already shipped) stays on
  every checkup surface incl. the report and clean-wallet result, upgraded by M8's yield-gap
  line. No dead ends in either property.
- **U3 `[P0][S]` One analytics stream.** Checkup pages fire the same `spaTrack` beacon to the
  same `/api/analytics/event` (page + door + UTM), so F-workstream funnel numbers cover the
  WHOLE journey, not just the landing half. Cross-domain: pass/persist the session/UTM params
  through the dashboard→checkup link.
- **U4 `[P1][S]` One demo, one taxonomy.** CHK-DEMO (the no-scan demo report) lives on the
  MAIN site styled by the dashboard shell and is linked from checkup home as "see a sample
  report" — one artifact serving both properties; tier names/numbers on checkup surfaces read
  from the same canonical set as workstream N (no checkup-local APY literals).
- **U5 `[Q-OWN]` Domain seam.** Recommend keeping the subdomain for now (path-unification
  `earn-defi.com/checkup` needs CF routing in front of Railway — owner infra). File as a
  question; revisit at D2.

- **Phase 3 — IA consolidation + cruft → /admin** (J1 + carried UX items, §6): **BLOCKED on
  admin auth.** Then: move operator set (`cockpit*`, `cockpit/*`, `board/*`, `tournament`,
  `system`, `status`, `monitoring`, `readiness`, `rates-desk`, `structural-desk`,
  `rwa-backstop`, `exit-nav`, `proof-of-reserves`, `fundability`, `due-diligence`,
  `yield-lab`) behind /admin with 301/308 redirects; collapse 5-page trust cluster → 1 Trust +
  1 legal (UX-34); one How-it-works + one research hub (UX-35); wire-or-cut orphans (UX-33);
  dedupe `strategies/{preserve,core,max-yield}` alt-name pages against canonical
  conservative/balanced/aggressive; trim footer (UX-19); allocator spine /for-allocators
  (UX-37); keep-noindex judgment set from UX-05 (rates-desk/structural-desk/… are intentional
  SEO proof pages — decide per page, don't blanket-move).
- **Phase 4 — Gated projects:** D1 board→Checkup migration; D2 dashboard→Checkup fold-in; C11
  true selling layer; C9 nurture; B11 widget-grid. All owner/legal-gated, untouched from v2.

---

## 6. Carried-forward items from `docs/SITE_UIUX_BACKLOG.md` (v2 dropped these — do NOT lose)

| UX-ID | Item | Where it lands now |
|---|---|---|
| **UX-18** | **`/admin/*` has ZERO auth today** — and J1 wants to move MORE sensitive surfaces there | **Hard prerequisite for Phase 3.** Owner-side: CF Access (Q-OWN-03). Engineering fallback if owner prefers: server-side shared-token gate on `/admin/*` + admin APIs. Either way: no new surface moves under /admin before auth exists. |
| UX-17 | Personal Gmail on selling pages | M9 / Q-OWN (needs invest@ inbox) |
| UX-24/25/28/29/30/32 | Single-source numbers cluster | Workstream N (Phase 0, §4 M5) |
| UX-33/34/35/37/19/38 | Marketing-IA consolidation cluster | Phase 3 |
| UX-21 | Clean-wallet checkup upside path | M8 |
| UX-40 | Above-the-fold trust anchor + hero yield-bridge | M1+M4 |
| UX-05 (rest) | Judgment-call noindex set | Phase 3, per-page decision |

---

## 7. Facts the executing session must know (verified 2026-07-12)

- Pages: **36 top-level / 95 total** files under `landing/src/pages/` (academy 28, admin 6,
  cockpit 7, board 5, strategies 11, blog 4, protocols 1 dynamic). 35/36 top-level are narrow
  centered columns; only `index.astro` is full-bleed. No dashboard shell exists.
- `Layout.astro`: flat header→slot→footer + one `:root` token block + `admin={true}` slim-bar
  variant + the `spaTrack` beacon (auto view-event, UTM capture, `[data-track]` click relay →
  `POST /api/analytics/event`; server: `spa_core/api/routers/analytics.py`).
- `DashboardLive.jsx`: `POLL_MS = 15_000`, SSOT `/api/ssot/facts` + 23 feeds, per-feed offline
  states, `PanelBoundary` per panel, explicit "HONESTY CONTRACT" comment — **preserve those
  semantics through any re-shell**.
- `/pilot`: form → `POST /api/pilot/request` → `data/pilot_requests.jsonl` + owner Telegram
  (`spa_core/api/routers/interest.py:158`, `_notify_owner_telegram`, count endpoint for /admin,
  tests in `spa_core/tests/test_pilot_request.py`). Reuse this infra for M7.
- Canonical numbers: `landing/src/lib/tier_bands.json` (owner-set display "up to {max}%") +
  track APIs. Current literals to reconcile: index.astro:107 (demo 5.4%), :200/:213/:226
  (up to 6/12/20), :207 (~3.3%); packages.astro:6-87 (bands), :142 (15% vs ~4.5%).
- Nav (SiteHeader): Checkup · Strategy Lab▾ · Track Record · Academy▾ · Research▾ · Trust +
  "Analyze Wallet" CTA + EN|RU. **EN|RU parity required for all new copy** (C13 applies to the
  sell sprint too, at least for hero/packages/pilot).
- Checkup = separate private repo `defi-checkup` (Railway; normal `git commit` + `git push
  HEAD:master`; no npm ci — EBUSY; Node 20). M8/C2/CHK-DEMO/B6 happen there.

## 7b. Execution protocol (non-negotiable — `PROJECT_CONTROL/16_MULTI_SESSION_PROTOCOL.md`)

1. Read `docs/SYSTEM_BRIEFING.md`, then `python3 scripts/log_session_change.py --tail` at start.
2. **Partition by file**; announce every change via `log_session_change.py --summary … --files
   <ABS paths> --verified "…"`.
3. SPA repo pushes ONLY via `python3 push_to_github_batch.py --files <ABS paths> --message
   "…"`. NEVER `git commit/push/reset --hard` on SPA. `git fetch origin` before reading
   `origin/main:<path>`. Checkup repo = normal git.
4. Verify before push: `cd landing && npm run build` (exit 0) for site; `pytest` for
   `spa_core`; checkup: `npx vitest run` + `npm run build -w @spa/web`. Never push red.
   Verify deploys by real content, not HTTP 200 (CF Pages builds `landing/` on push to main).
5. Never touch: live paper track `data/*`, `spa_core/risk/policy.py` (v1.0), `spa_core/
   execution/`, launchd fleet — without owner sign-off.
6. Owner-gated question → append `Q-OWN-NN` block to `docs/OWNER_DECISIONS_NEEDED.md`, keep
   working on non-gated items. Re-read that file each cycle; execute filled ОТВЕТs.
7. Hard content floor (marketing moat, not legalese): no fabricated numbers; paper/backtest
   never labeled live; targets always called targets; tails shown where targets are shown.
   Everything else — punchy, aspirational, urgent — is encouraged.

---

## 8. New owner questions to file as Q-OWN blocks (append, then proceed without blocking)

1. **/pilot human:** owner's display name (or pseudonym) + optional photo + calendar link for
   "talk to the person who built this". (Also: create invest@ mailbox to replace Gmail — UX-17.)
2. **Admin auth choice** (escalation of Q-OWN-03): CF Access (owner infra, 15 min) vs
   engineering token-gate. Phase 3 is blocked until one is picked.
3. **Early-access list (M7) sign-off:** confirm the framing "join to get the validation report
   first" + position numbers. (Recommended: yes — it's the built-in scarcity we already have.)
4. **Conservative headline number:** confirm "~3.3% realized (track-to-date)" as the lead with
   "up to 6%" demoted to band context (keeps the 2026-07-11 display decision, fixes the
   contradiction that kills credibility).
5. **Checkup domain seam (U5):** keep checkup.earn-defi.com subdomain for now, or unify to
   earn-defi.com/checkup (needs CF routing in front of Railway — owner infra). Recommendation:
   keep subdomain until D2; U1–U4 make the seam invisible either way.

---

## 9. Definition of Done (measurable)

- **Phase 0:** one canonical number story site-wide (lint enforced); hero/packages/pilot flipped
  to selling frame; comparison bar + calculator + counter strip + countdown + early-access live;
  checkup yield-gap capture live; funnel events flowing; baseline F2 targets defined;
  **one-product seam started: checkup carries the site's chrome (U1), both directions wired
  (U2), one analytics stream end-to-end (U3).**
- **Product (end-state):** app surfaces on the shell; journey dashboard→checkup(scan/snapshot/
  demo)→bridge→/pilot works end-to-end with numeric conversion targets met; every number carries
  its evidence framing; LCP/CLS within budget; WCAG-AA on new primitives; zero token drift
  (QA1); operator cruft behind authed /admin; old URLs 301.

---

*v3 authored 2026-07-12 by the analyst session (owner-commissioned audit). Supersedes
roadmap-v2 on conflicts. Fact-check, gap-analysis and marketing research summarized in §1–§2;
full agent reports live in the analyst session transcript. Execute Phase 0 first.*
