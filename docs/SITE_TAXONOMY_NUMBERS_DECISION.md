# Site coherence — the 2 OWNER decisions that unblock the biggest UI/UX lever

> ## ✅ DECIDED + EXECUTED 2026-07-11
> Owner chose: **taxonomy = Conservative / Balanced / Aggressive** everywhere; **APY display = "up to X%"**
> (Conservative up-to-6%, Balanced up-to-12%, Aggressive CAPPED at up-to-20%), tail always shown.
> **Implemented across the whole site** (batches 1-4, commits c1207ac2, d7395f46, d84ad71b, c63ee627):
> single source `tier_bands.json`/`strategy_config.json`; **0 old tier-name leftovers** (Preserve/Core/
> Max-Yield gone); bands → "up to X%"; volatile `/packages` LIVE badge killed → "LIVE · evidenced".
> **Remaining minor:** homepage "Current APY" glance still shows the live day-rate (honestly labelled,
> a track metric not a tier claim); URL rename `/strategies/preserve→conservative` (+redirects) deferred;
> UX-26 "which tier is evidenced" — **INVESTIGATED 2026-07-11, needs 1 owner line (public honesty claim,
> not guessed).** FACTS: the live go-live book holds **T1+T2** (aave_v3 + pendle + susde + morpho, equity
> $100,379) and realizes **~3.3-4.2%**. So by COMPOSITION it's **Balanced/Core**, but by REALIZED RETURN it
> sits in the **Conservative** range. Sources disagree: `tier_bands.json` + `/packages` say "Conservative =
> live evidenced"; `strategy_config.json` + memory + the T1+T2 composition say "Balanced/Core =
> paper-tracked" (3 signals vs 2). Right now the HOMEPAGE (via strategy_config) says Balanced=Paper-tracked
> while /packages (via tier_bands) says Conservative=LIVE — a live self-contradiction. **Owner call: is the
> evidenced book labelled Conservative or Balanced?** (My read: it's a T1+T2 = Balanced-composition book
> realizing conservative-range returns — so "Balanced, live, ~3.3% realized so far" is the most defensible;
> but it's your product definition + a public claim.) Once you say which, I align both sources in one pass.


*From the 7-architect audit (`docs/SITE_UIUX_BACKLOG.md`). Everything code-doable is already shipped;
these two decisions are the only thing standing between "fragmented" and "one coherent, selling site".
Pick an answer for each — then I unify EVERY page to a single source of truth in code (one pass), and
the drift can never come back. **I will not invent or change a public number; I only wire pages to read
the value YOU pick.***

---

## DECISION 1 — ONE tier taxonomy (today TWO ship side by side)

The same three tiers are sold under **two disjoint name sets**, cross-wired in the same nav dropdown and
even the same page:

| Slot | Name set A | Name set B |
|---|---|---|
| tier 1 | **Preserve** | **Conservative** |
| tier 2 | **Core** | **Balanced** |
| tier 3 | **Max Yield** | **Aggressive** |

- **"Preserve / Core / Max-Yield"** is used on: `/strategies`, SiteHeader nav, `/methodology`, `/risk`,
  `/due-diligence`, the homepage tier cards, the strategy detail pages, `strategy_config.json`.
- **"Conservative / Balanced / Aggressive"** is used on: `/packages`, `/strategies/index` intro,
  `/annual-contrast`, `/system`, `/aggressive-lab`, the checkup compare table, `tier_bands.json` (primary keys).

**→ Your call:** pick ONE set. *(My recommendation: **Conservative / Balanced / Aggressive** — it's the
industry-standard risk language a stranger understands instantly, best for conversion; "Preserve/Core/
Max-Yield" is more branded/distinctive but teaches the visitor a second vocabulary. Your brand call.)*

---

## DECISION 2 — the canonical NUMBER per tier (today one book shows 7+)

For what is nominally ONE book, the site currently shows all of these:

| Tier | Numbers shown across pages (all real, but conflicting) | Where |
|---|---|---|
| Conservative | **2.7%** · **4.25%** (volatile day-rate) · **~3.3%** (8 pages) · **~3.6%** · **~6%** (target) | homepage card / packages LIVE badge+hero / packages prose / strategy_config / preserve.astro |
| Core | **~5%** · **4–6%** · **6–12%** · live **—** | card / its hero / nav band / snapshot (null, honest) |
| Aggressive | **~15%** · **12%+** · **12–20%** · live **—** | detail / nav / packages / snapshot (null, honest) |
| RWA floor | **~3.4%** everywhere — ✅ **VERIFIED CONSISTENT** (annual-contrast/faq/rates-desk/structural-desk/yield-lab all say ~3.4%). The stray "~3.3%" is the conservative **BOOK** (realized paper return), a DISTINCT concept honestly shown "near the ~3.4% floor" — NOT a floor inconsistency. No action needed; the only nit is `methodology.astro:163` phrasing ("~3.3% real floor" conflates book+floor). | verified 2026-07-11 |

**Root cause (code):** despite comments claiming "single canonical source", only the band-LABEL strings +
the hero snapshot fields were centralized. The per-book APY numbers and the tier NAMES are still
**hardcoded across 8+ pages** → they drift.

**→ Your call:** the canonical value per tier + per metric. *(My recommendation, honesty-first:*
- *Conservative LIVE = the stable **track-to-date** APY of the evidenced book (anchor 2026-06-22), NOT the
  volatile single-day `paper_apy_pct` that swings 3.2%–8.5% and blows past the "2–6%" band. Kill the
  day-rate "LIVE ~X%" badge or relabel it "today's rate (volatile)".*
- *Conservative TARGET = one number (`~3.3%` prose vs `~6%` target contradict — pick one and label it
  clearly "target" vs "realized").*
- *Core / Aggressive LIVE = **—** (no live track — the current honest em-dash is correct; keep it).*
- *Core / Aggressive TARGET = one band each (e.g. Balanced 6–12%, Aggressive 12–20%), labeled "target".*
- *RWA floor = pick **~3.4%** everywhere (it's the live TVL-weighted tokenized-T-bill number).)*

---

## What I execute the moment you answer (code plan, one pass)

1. Make `strategy_config.json` (or `tier_bands.json`) the SINGLE source for BOTH names and numbers; delete
   the other name set / reconcile the two files into one.
2. Replace every hardcoded tier name + APY literal across the 8+ pages with a read from that source
   (`import` + interpolate) — ban inline literals.
3. Add a guard test (like the doc-drift guard) that FAILS if any page hardcodes a tier name/number instead
   of reading the source, so it can never drift again.
4. Fix the honesty tail: Max-Yield homepage card currently frames the aggressive tier as benign
   ("T1+T2, wider diversification, no liquidation") while its own page describes levered PT loops with a
   ~50% tail — align the card to show the tail at the point of choice.

*Answer inline (e.g. "taxonomy = Conservative/Balanced/Aggressive; Conservative live = track-to-date")
and I ship the unification pass immediately. Companion: `docs/SITE_UIUX_BACKLOG.md`.*

---

## What each decision unblocks (the leverage — every remaining backlog item hangs off these)

**DECISION 1 (taxonomy) unblocks →** UX-23 (one canonical name set site-wide), UX-28 (SiteHeader dropdown
stops teaching two names), plus the naming half of UX-25/UX-26.

**DECISION 2 (canonical numbers) unblocks →** UX-14 (kill the volatile /packages LIVE badge → stable
track-to-date), UX-24 (one canonical "current book APY" sourced everywhere), UX-25 (per-tier bands from one
source), UX-26 (which tier is the evidenced book), UX-27 (homepage aggressive card = same tail story as
/packages — the honesty half I already shipped; the number half waits on you), UX-29 (target bands instead
of bare "—"), UX-31 (dynamic day-count in faq). UX-30 (RWA floor) is DONE — already consistent at ~3.4%.
UX-32 (CI lint enforcing single-source) ships WITH the unification.

**OWNER INFRA (separate from the 2 decisions) →** UX-18 ✅ **DONE by owner (verified 2026-07-11: all
`/admin/*` now 302 → Cloudflare Access; public pages still 200)** — the P0 zero-auth admin exposure is
CLOSED. Downstream UX-19/UX-35/UX-36/UX-38 (move operator-depth pages behind the gate / trim footer links
to them) are now lower-risk cleanups since the gate itself exists. UX-16 (a real contact mechanism on /pilot) + UX-17 (which public contact identity
— personal Gmail is on selling pages today) are your business-contact calls.

**IA CONSOLIDATION (your product-shape calls) →** UX-33/UX-34/UX-35/UX-37/UX-40 (collapse the 5-page
trust/risk cluster + the 5 "how it works" pages into a spine, add an above-the-fold trust anchor). I can
propose a concrete merge map on request; the cut/keep decisions are yours.

*Net: **one line from you (the 2 decisions) unblocks ~12 backlog items** I can then ship in a pass. The
admin-auth + contact + IA-consolidation calls are separate owner decisions, flagged here, not blocking.*
