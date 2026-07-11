# Site coherence — the 2 OWNER decisions that unblock the biggest UI/UX lever

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
| RWA floor | **~3.3%** vs **~3.4%** (sometimes same sentence) | methodology vs yield-lab/structural-desk/faq |

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

*Answer inline (e.g. "taxonomy = Conservative/Balanced/Aggressive; Conservative live = track-to-date;
RWA floor = 3.4%") and I ship the unification pass immediately. Companion: `docs/SITE_UIUX_BACKLOG.md`.*
