# SPA — Unified Design Standard **V2** (whole-site cohesion)

> **Status:** SPEC — read-only audit + actionable standard. Feeds the **Wave-2 unification** build.
> **Supersedes/extends:** `docs/SITE_DESIGN_SYSTEM.md` (V1). V1's *token layer, header, footer,
> paper-strip, IA* were **built and shipped** (see `Layout.astro`, `tailwind.config.mjs`,
> `SiteHeader.astro`). V2 addresses what V1 never covered: the site has since grown a **/dashboard
> console**, a **DFB /board risk-explorer** (5 pages + 4 React islands), and a **/academy portal**
> (24 pages + ~30 components). These new surfaces re-diverged. V2 is the plan to bring the WHOLE
> site — marketing + console + board + academy — onto ONE render dialect.
> **Author:** UX/UI Design Lead audit, 2026-07-01. **No site files modified.**
> **Baseline:** `cd landing && npm run build` → **64 pages, 0 errors** (clean).

---

## 0. TL;DR — the one sentence

**The tokens are already correct and universal; the problem is that four different surface groups
render the *same tokens four different ways*, and the site's core risk-color language (A/B/C/D +
SAFE/WATCH/REFUSE) is inconsistent — even semantically self-contradictory — across them.** The fix
is not new tokens. It is a **single render dialect** (CSS custom properties everywhere), **one
canonical risk-color map** shared by every surface, and a **shared component kit** (Badge / Table /
StatusPill / Card / Hero) so the console, board, academy, and marketing pages stop each rolling
their own.

**The site feels like "several products stitched together" for exactly 3 reasons, in rank order:**
1. **The risk-color language is rendered 4 incompatible ways and disagrees with itself** (§2.1).
2. **The eyebrow/section-label color is still random** — 105× accent vs 55× green, no rule (§2.2).
3. **Every surface rolls its own Badge / Table / Card / Hero** — measurably different sizes & styles
   for the same element on different pages (§2.3).

---

## 1. WHAT V1 GOT BUILT (so we don't re-litigate it)

Confirmed shipped and healthy — **keep, do not touch**:

- **Token layer** — `landing/src/layouts/Layout.astro:80-110` (`:root` block) + `tailwind.config.mjs`
  carry the full V1 palette/type/radius/shadow/motion. Both surfaces (CSS vars for islands, Tailwind
  classes for `.astro`) read the *same* hex. This is the single source of truth and it is good.
- **Canonical chrome** — `Layout.astro:115-120` renders `SiteHeader` + `PaperStrip` + `<slot/>` +
  `SiteFooter` on every Astro page. Every audited surface (marketing, `/dashboard`, `/board/*`,
  `/academy/*`) correctly inherits it. No page rolls its own header anymore. **This is done.**
- **Fonts** — Inter + JetBrains Mono both loaded (`Layout.astro:70-73`). V1's "mono never loaded"
  bug is fixed.
- **EN|RU** — the `data-ru` + `#spa-lang-toggle` runtime (`Layout.astro:125-175`) lives in the
  header and works site-wide.
- **The gold-standard surface exists**: `components/DashboardLive.jsx` (2824 lines, the entire
  `/dashboard` console) is **100% token-clean** — **zero** hardcoded hex, **zero** Tailwind color
  literals, every color is `var(--…)` (41× `var(--danger)`, 24× `var(--ok)`, 21× `var(--data-teal)`,
  etc.). **This file IS the target dialect.** V2 = "make every other surface look like DashboardLive."

---

## 2. THE FRAGMENTATION AUDIT (concrete, evidence-based, per surface group)

### 2.1 The load-bearing problem: FOUR dialects for ONE risk-color language

The site's identity IS the risk taxonomy — **A/B/C/D tiers** and **SAFE / WATCH / REFUSE** verdicts.
It is rendered **four mutually-incompatible ways**:

| # | Dialect | Where | Example |
|---|---|---|---|
| 1 | **CSS-var tokens** (canonical) | `DashboardLive.jsx`, academy islands | `color: 'var(--danger)'` (`RefusalGateWalkthrough.jsx:134`) |
| 2 | **Raw hex literals** | DFB islands (`DfbScreener/PoolDetail/Alerts/Portfolio.jsx`) | `SAFE: { fg: '#34D399' }` (`DfbScreener.jsx:62`) |
| 3 | **Tailwind semantic utilities** | ~37 marketing `.astro` pages | `bg-red-500/10 … text-red-300` (`refusals.astro:277`, `system.astro:233`) |
| 4 | **Ad-hoc off-palette hex** | DFB alerts, portfolio | `#F2963C` orange (`DfbAlerts.jsx:52`), `#0b0d12` (`DfbPortfolio.jsx:198`) |

**Why this is not cosmetic — three concrete self-contradictions:**

**(a) REFUSE is two different reds.** Token `--danger = #F26D6D` (soft coral). Tailwind `red-500 =
#EF4444` / `red-300 = #FCA5A5` (harder red). So the *same* REFUSE verdict is coral in the academy &
DFB but a harder red on `refusals.astro:277`, `system.astro:233`, `rates-desk.astro`,
`rwa-backstop.astro`. Side by side they don't match.

**(b) SAFE is green in one place, teal in another.** DFB `SAFE = green #34D399` (`DfbScreener.jsx:62`);
`system.astro:231` renders the SAFE pill **teal** (`bg-teal-500/10 text-teal-300`); academy
`RefusalGateWalkthrough.jsx:134` uses `var(--ok)` = **green**. So a user learns "SAFE = green" in the
academy, sees "SAFE = green" on the board, then sees "SAFE = teal" on `/system`. Two colors, one word.

**(c) The A/B/C/D tier→color map is internally CONTRADICTORY.** The two islands that both render the
A/B/C/D scale disagree on C and D:

| | A | B | C | D |
|---|---|---|---|---|
| **DFB** (`DfbScreener.jsx:52-55`) | green `#34D399` | blue `#79A4F5` | **amber** `#F2B53C` | **red** `#F26D6D` |
| **Academy** (`RefusalGateWalkthrough.jsx:187`) | **teal** `--data-teal` | blue `--accent` | **red** `--danger` | **amber** `--warn` |

C and D are **swapped** between the two surfaces, and A is green vs teal. This is a genuine semantic
clash: the risk-severity color of a "C" pool is amber on `/board` and red in `/academy`.

> **This single inconsistency does more to make the site feel like several products than anything
> else** — the risk language is the product, and it renders four ways and disagrees with itself.

### 2.2 Eyebrow / section-label color is still random (V1's #1 rule, unfixed — and WORSE)

V1 §3.1 mandated: *"eyebrow color is always `--text-faint` or `--accent`, never green/amber."*
Reality today:
- `text-accent-*` used **105×**, `text-green-400` used **55×** for the *same* eyebrow role
  (V1 measured 66 / 30 — the drift has **grown**, not shrunk).
- e.g. `track-record.astro:56` eyebrow is `text-teal-300/70`; other pages use `text-accent-400`;
  others `text-text-faint`. Three brands for one label role.

### 2.3 Every surface rolls its own components (measurable size drift)

- **Badge defined 3× independently** in the DFB with **different sizes**: `DfbScreener.jsx:81`
  (`padding 2px 8px`, `fontSize 11`), `DfbPoolDetail.jsx:48` & `DfbPortfolio.jsx:49`
  (`padding 3px 10px`, `fontSize 12`), and `DfbAlerts.jsx:246` hand-rolls a 4th inline pill. So the
  same SAFE/REFUSE badge is physically a different size on the screener vs. the pool vs. the portfolio
  vs. alerts.
- **Table implemented 3× independently** (screener `DfbScreener.jsx:239`, pool `DfbPoolDetail.jsx:200`,
  portfolio `DfbPortfolio.jsx:262`) with different wrapper radii (16 / 12 / 12) and different header
  styles (`--text-muted`+mono+uppercase vs `--text-faint`+no-mono). The portfolio grid visibly looks
  "less finished" than its siblings.
- **Two card treatments coexist site-wide**: **23 files** use translucent `bg-white/[0.02]` overlay
  cards; **50 files** use solid `bg-bg-surface`. An academy card and a `/refusals` card side by side
  are different surfaces.
- **Hero H1 size drifts**: `text-4xl sm:text-5xl` (40×) vs `text-3xl sm:text-4xl` (21×) vs
  `text-2xl sm:text-3xl` (3×) with no rule for which page-type gets which. e.g. `/board/portfolio`
  uses the smaller `text-3xl sm:text-4xl` while its sibling `/board/index` and `/board/methodology`
  use `text-4xl sm:text-5xl`; `/board/pool` has **no hero at all** and renders its title as a raw
  `fontSize:32` inside the island (`DfbPoolDetail.jsx:171`).

### 2.4 Per-surface-group summary

| Group | Chrome | Token discipline | Verdict |
|---|---|---|---|
| **`/dashboard` console** (`DashboardLive.jsx`) | ✅ Layout | ✅ **100% CSS-var, 0 literals** | **Gold standard — the model** |
| **/academy** (24 pg + ~30 cmp) | ✅ Layout | ◐ mostly CSS-var; ~20 rgba tint literals (no `--ok-bg/--warn-bg/--danger-bg` token exists); light-theme cert palette hardcoded (`AnalystCertificate.jsx:156-171`); confetti + 🔥/🎉 emoji chrome off-brand | Good discipline, tone-drift |
| **DFB /board** (5 pg + 4 islands) | ✅ Layout | ✗ **all raw hex**; off-palette `#F2963C`, `#9aa3b2`, `#0b0d12`; 3× Badge, 3× Table; A/B/C/D map contradicts academy | **Worst offender** |
| **Marketing** (~37 `.astro`) | ✅ Layout | ✗ **Tailwind semantic literals** for all verdicts (`red-*/emerald-*/teal-*/amber-*`); eyebrow color random; 2 card patterns | Pervasive Tailwind-dialect drift |
| **Global shell** | ✅ shipped | ✅ | Keep |

### 2.5 Off-palette / broken specifics (punch-list feeders)

- `#F2963C` — invented "high severity" orange, `DfbAlerts.jsx:52`; appears **nowhere else** in repo.
- `#9aa3b2` — UNKNOWN/fallback grey, used 6× in DFB; not a token (`DfbScreener.jsx:57,66`,
  `DfbAlerts.jsx:55`, `board/methodology.astro:21-25,249-251`).
- `#0b0d12` — a **5th near-black** used as a button label, `DfbPortfolio.jsx:198` (the exact thing
  the token comment says the scale "kills").
- `#3b82f6` — **old V1 blue** still hardcoded in 3 SVG strokes: `TrustSignals.astro:41,67`,
  `HowItWorks.astro:34` (should be `--accent #5B8DEF`).
- Native `<input type="checkbox">` / `<select>` render OS-default (light) on dark surfaces —
  `DfbScreener.jsx:233`, `DfbAlerts.jsx:186` — the only visible light-mode leaks.
- `AnalystCertificate.jsx:156-171` — full white-card light palette hardcoded (`#fff`, `#f6f8fc`,
  `#374151`, `#9CA3AF`), several duplicating existing tokens.
- Motion drift: DFB live-dot uses inline `animation:'pulse 3s ease-in-out'` (`DfbScreener.jsx:210`)
  instead of the config's `pulse-slow` token (different easing).

---

## 3. THE UNIFIED DESIGN STANDARD (what Wave-2 implements)

> The token *values* are unchanged from V1 (they're correct). V2 standardizes **how** they're
> consumed, and pins the risk-color language. Every rule below is concrete.

### 3.1 The single render dialect — **CSS custom properties everywhere**

**Rule:** color, in every surface, is expressed as `var(--token)` (islands / inline styles) or its
Tailwind alias that maps to the *same* var (`.astro`). **No raw hex. No `bg-red-500`. No off-palette
literal.** DashboardLive.jsx is the reference implementation.

Two allowed forms:
- **`.astro` pages** → Tailwind classes that already alias the tokens: `text-text-primary`,
  `bg-bg-surface`, `border-border`, `text-accent`, and the **semantic status classes** defined in §3.3.
- **React islands / inline styles** → `style={{ color: 'var(--danger)' }}`.

**Forbidden in all surfaces:** `#EF4444`/`red-500` (use `--danger`), `emerald-*`/`green-400`
(use `--ok`), `amber-*` for eyebrows (see §3.2), bespoke hex (`#F2963C`, `#9aa3b2`, `#0b0d12`,
`#3b82f6`, `#0d1117`).

### 3.2 Type scale (unchanged from V1 — pin it, enforce it)

| Token | Size | LH | Weight | Use |
|---|---|---|---|---|
| `display` | 3.5rem→2.5rem→2rem | 1.05 | 700 | Home hero H1 |
| `h1` | 2.25rem (`text-4xl sm:text-5xl`) | 1.15 | 700 | **All page titles — ONE size** |
| `h2` | 1.5rem | 1.25 | 600 | Section heads |
| `h3` | 1.25rem | 1.3 | 600 | Card titles |
| `body-lg` | 1.125rem | 1.6 | 400 | Lede |
| `body` | 1rem | 1.6 | 400 | Default |
| `small` | 0.875rem | 1.5 | 400 | Captions |
| `eyebrow` | 0.75rem | 1.4 | 600 | Mono, uppercase, `.12em` tracking |
| `metric` | 2.5rem | 1.0 | 700 | Big mono numbers |

**Enforcement rules:**
- **Page title (`h1`) is `text-4xl sm:text-5xl` on EVERY page.** Kill `text-3xl sm:text-4xl`
  page titles (fix `board/portfolio.astro`, `board/pool.astro`). Islands never set a raw `fontSize`
  for a page title.
- **Eyebrow color is `text-text-faint` OR `text-accent` — NEVER green/amber/teal.** Replace all 55×
  `text-green-400` and all `text-teal-300/70` eyebrows. Green/amber/teal are reserved for §3.3
  semantics only. (This is V1's rule, finally enforced.)
- **Kill the `.5px` bespoke sizes** in DFB islands (`13.5`, `12.5`, `10.5` in `DfbScreener.jsx`,
  `DfbPoolDetail.jsx`) — snap to the scale (13→`small`, etc.).

### 3.3 **THE canonical risk-color language** (the most important table in this doc)

One map. Every surface — marketing, board, academy, dashboard — renders these identically.

**A/B/C/D risk tiers** (severity ramp, low→high):

| Tier | Meaning | Token | Hex |
|---|---|---|---|
| **A** | safest | `--data-teal` | `#36C2B4` |
| **B** | moderate | `--accent` | `#5B8DEF` |
| **C** | elevated | `--warn` | `#F2B53C` |
| **D** | highest | `--danger` | `#F26D6D` |

> **Decision (resolves §2.1c):** adopt **DFB's ordering for C/D** (C=amber, D=red) — severity should
> ramp teal→blue→amber→red, so C (elevated) < D (highest) in visual heat. **Fix the academy**
> (`RefusalGateWalkthrough.jsx:187`) to match: A→`--data-teal`, B→`--accent`, C→`--warn`, D→`--danger`.
> **Fix DFB's A** from green `#34D399` to teal `--data-teal` so A ≠ SAFE-green (they're different axes).

**SAFE / WATCH / REFUSE verdicts:**

| Verdict | Token | Hex |
|---|---|---|
| **SAFE / ENTRY / PASS / live** | `--ok` | `#34D399` (green) |
| **WATCH / PENDING / caution** | `--warn` | `#F2B53C` (amber) |
| **REFUSE / FAIL / kill / offline** | `--danger` | `#F26D6D` (coral-red) |
| **UNKNOWN / N-A** | `--text-muted` | `#6B7280` (kills `#9aa3b2`) |

> **Decision (resolves §2.1b):** **SAFE is green (`--ok`) everywhere.** Fix `system.astro:231` (and
> any teal SAFE pill) to green. Teal (`--data-teal`) is **only** the A-tier + data-viz/live-tick
> accent — it is NOT a verdict color. This removes the green-vs-teal SAFE ambiguity site-wide.

**Kill-switch ladder** (already consistent in academy — adopt site-wide): NONE→`--ok`,
SOFT→`--warn`, HARD→`--danger`.

**Add 3 missing background tokens** to `Layout.astro:80-103` (they're implied ~20× via rgba
literals across academy islands and DFB — tokenize them once):
```
--ok-bg:     rgba(52,211,153,0.10);   --ok-border:     rgba(52,211,153,0.30);
--warn-bg:   rgba(242,181,60,0.10);   --warn-border:   rgba(242,181,60,0.30);
--danger-bg: rgba(242,109,109,0.12);  --danger-border: rgba(242,109,109,0.35);
```
Then every risk tint = `background: var(--danger-bg); border-color: var(--danger-border); color: var(--danger)`.
**Kill `#F2963C`** — fold "high severity" into `--danger` or `--warn` (no orange in the palette).

**Tailwind semantic aliases** — add these to `tailwind.config.mjs` so `.astro` pages stop using
`red-500`/`emerald-*`:
```
colors.ok / colors.warn / colors.danger already exist. ADD utility recipes (docs):
  SAFE badge:   class="badge-safe"   → bg-ok/10 border-ok/30 text-ok
  WATCH badge:  class="badge-watch"  → bg-warn/10 border-warn/30 text-warn
  REFUSE badge: class="badge-refuse" → bg-danger/10 border-danger/30 text-danger
```
Implement these as **one shared component** (§3.4 StatusPill), not repeated utility strings.

### 3.4 Canonical components (the shared kit — build once, use everywhere)

Currently each surface rolls its own. Wave-2 ships **one** of each. Recommended location:
`landing/src/components/ui/` (Astro) + a mirror export for islands (`ui/tokens.js` constants that
resolve to `var(--…)` so JSX and Astro share the map).

**Button**
| Variant | Class recipe |
|---|---|
| Primary | `bg-accent text-white rounded-sm shadow-cta hover:bg-accent-hover` · label color `#fff` (allowed only here) |
| Secondary | `bg-transparent border border-border hover:border-border-strong text-text-secondary hover:text-text-primary rounded-sm` |
| CTA-outline (header) | `border border-accent/50 text-accent hover:bg-accent-bg` (already correct in `SiteHeader.astro:77`) |
| Ghost | `text-accent hover:underline underline-offset-4` |
| Disabled | `text-text-muted border border-border cursor-not-allowed` |
Sizes: sm `8/14` · md `12/24` · lg `16/28`. **Fix** `DfbPortfolio.jsx:198` label `#0b0d12` → `#fff`.

**Card** — `bg-bg-surface border border-border rounded-lg p-6 md:p-8 hover:border-border-strong
transition-[border-color] duration-150`. **Pick ONE surface treatment: solid `bg-bg-surface`**
(the 50-file majority). **Retire the translucent `bg-white/[0.02]` variant** (23 files) — migrate
them to `bg-bg-surface`. Variants: `metric` (mono number + label), `doc`, `status` (3px left border
in the §3.3 semantic color).

**Table** — one `<Table>` + `<Th>`/`<Td>`. Wrapper `rounded-lg border border-border overflow-hidden`.
Header row `bg-bg-surface-2`, `<Th>` = `text-text-muted font-mono text-xs uppercase tracking-wide
px-3.5 py-2.5`. Rows hairline `border-border`; hover `bg-bg-elevated`. **Replaces the 3 divergent
DFB tables** (unify radius to `lg`/16, unify `<Th>` to `--text-muted`+mono — fix the portfolio
`--text-faint` header).

**Badge / StatusPill** — one component, props `{ tone: 'ok'|'warn'|'danger'|'accent'|'teal'|'muted',
label }`. Fixed geometry: `inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px]
font-mono` + optional leading dot. Renders `bg: var(--{tone}-bg); border: 1px solid
var(--{tone}-border); color: var(--{tone})`. **Replaces the 4 divergent DFB badges + the marketing
Tailwind pills + the academy pills** — one size, one dialect, everywhere.

**Tabs** — pill row: active `bg-accent-bg text-accent border border-accent/30`, inactive
`text-text-secondary hover:text-text-primary`. (Dashboard already does this — extract it.)

**Input / Select / Checkbox** — dark-styled: `bg-bg-surface-2 border border-border rounded-md
text-text-primary`. **Style the native checkboxes/selects** (`accent-color: var(--accent)`; custom
select chevron) to kill the light-mode leak in `DfbScreener.jsx:233`, `DfbAlerts.jsx:186`.

**Live/offline chip** — one component: `● {source} · updated {t}` where dot = `--ok` (live,
`animation: pulse-slow`) / `--text-muted` (offline). Use the config `pulse-slow` token, not inline
`ease-in-out` (fix `DfbScreener.jsx:210`, `DfbAlerts.jsx:164`, `DfbPoolDetail.jsx:163`).

**Hero / page-title block** — one `<PageHeader>` component: `eyebrow (mono, text-text-faint) → h1
(text-4xl sm:text-5xl) → lede (body-lg, text-text-secondary, max-w-2xl)`. Every page uses it →
kills the H1-size drift and the "no hero on /board/pool" gap. DFB islands must NOT render their own
page title (`DfbPoolDetail.jsx:171` → move title to the page shell's `<PageHeader>`).

### 3.5 Spacing / radius / shadow / motion (unchanged from V1 — enforce)

- Spacing 8px base; section vertical `96/64/48`. Content max-widths: marketing `max-w-6xl`,
  doc/article `max-w-3xl`, dashboard `max-w-5xl` (already used).
- Radius: buttons/chips `sm`(8), inputs/small cards `md`(12), cards `lg`(16), hero panels `xl`(24),
  pills `full`. **Unify DFB table wrappers to `lg`(16)** (currently mixed 16/12).
- Shadow: rely on border+bg-step; `shadow-cta` glow only on primary CTA.
- Motion: `120ms` color / `200ms` transform / `400ms` entrance, ease `cubic-bezier(.4,0,.2,1)`.
  Live dot = `pulse-slow` token. **Respect `prefers-reduced-motion`** (already global,
  `Layout.astro:106-109`).
- **Tone decision (owner):** the academy's confetti (`celebrate.js`) + 🔥-streak / 🎉 / 🎓 emoji
  chrome (`JourneyMap.jsx:97`, `index.astro:82,89`) is the single tonal outlier vs the
  "Bloomberg-terminal-meets-Linear" brand. **Recommendation:** replace emoji glyphs with the
  geometric glyph set the academy's own callouts already use (`◆ ▲ ›`, `Callout.astro:33-35`); keep
  the reduced-motion-safe reveal card, **drop the falling-confetti physics**. Learning-portal warmth
  is fine; consumer-gamification confetti reads off-brand for an institutional-rigor desk.

### 3.6 Page templates (unchanged from V1, now enforced with §3.4 kit)

1. **Marketing** — `PageHeader` → sections (`max-w-6xl`) → `Disclaimer` → footer.
2. **Doc/article** — `PageHeader` → `max-w-3xl` prose → Related → footer.
3. **Data-app** (dashboard / board / tournament) — `PageHeader` + live-chip → app body built on the
   §3.4 kit → minimal note. **DFB /board sub-pages get ONE shared sub-nav component** (today: rich
   card-grid on `/board`, thin breadcrumb elsewhere — unify to one persistent DFB sub-nav across all
   5 board pages).
4. **Academy lesson** — `LessonLayout.astro` (keep; it's well-built) retoned per §3.5 tone decision.

### 3.7 EN|RU

Keep the shipped `data-ru` mechanism. **Rule:** every user-facing string gets a `data-ru` attribute;
the shared §3.4 components must pass `data-ru` through. (DFB islands already localize labels via a
`ru` prop — fold into the shared Badge/StatusPill so verdict translations live in one place, e.g.
`REFUSE/ОТКАЗ`.) Remove the dead ternary `DfbScreener.jsx:356` (`ru ? 'tail-veto' : 'tail-veto'`).

---

## 4. PUNCH LIST (per-surface, ranked by leverage)

**P0 — the risk-color language (fixes the "several products" feel):**
1. Add `--ok-bg/-border`, `--warn-bg/-border`, `--danger-bg/-border` tokens (`Layout.astro`).
2. Fix the A/B/C/D contradiction: academy `RefusalGateWalkthrough.jsx:187` → C=`--warn`, D=`--danger`;
   DFB `DfbScreener.jsx:52` A → `--data-teal` (not green). ONE map (§3.3).
3. Fix SAFE-color contradiction: `system.astro:231` teal SAFE → green `--ok`. SAFE=green everywhere.
4. Migrate ~37 marketing pages off Tailwind `red-*/emerald-*/teal-*/amber-*` verdict literals onto
   the shared StatusPill / `--token` (biggest offenders: `system.astro` 76×, `track-record.astro` 60×,
   `due-diligence.astro` 49×, `refusals.astro`, `rates-desk.astro`, `rwa-backstop.astro`).
5. Migrate DFB islands off raw hex onto `var(--…)` (`DfbScreener/PoolDetail/Alerts/Portfolio.jsx`,
   `board/methodology.astro:21-25`).

**P1 — component unification:**
6. Ship shared `Badge/StatusPill`, `Table/Th/Td`, `Card`, `Button`, `FilterSelect`, `LiveChip`,
   `PageHeader` in `components/ui/`; replace the 3–4 divergent copies in DFB + the ad-hoc marketing
   pills. Fix badge-size drift and the 3 table radii/header styles.
7. Enforce eyebrow rule: replace 55× `text-green-400` + all `text-teal-300/70` eyebrows with
   `text-text-faint`/`text-accent`.
8. One card surface: migrate 23× `bg-white/[0.02]` → `bg-bg-surface`.
9. Enforce `h1 = text-4xl sm:text-5xl` on every page; give `/board/pool` a real `PageHeader`; fix
   `/board/portfolio` H1 size; move `DfbPoolDetail.jsx:171` title into the shell.
10. Unify DFB /board sub-nav into one shared component across all 5 board pages.

**P2 — off-palette / polish:**
11. Kill `#F2963C` (DfbAlerts.jsx:52), `#9aa3b2`→`--text-muted` (6×), `#0b0d12`→`#fff`
    (DfbPortfolio.jsx:198).
12. `#3b82f6`→`--accent` in SVG strokes (`TrustSignals.astro:41,67`, `HowItWorks.astro:34`).
13. Style native checkbox/select (kill light-mode leak, `DfbScreener.jsx:233`, `DfbAlerts.jsx:186`).
14. Tokenize the certificate light palette (`AnalystCertificate.jsx:156-171`); add a small light ramp.
15. Live-dot → `pulse-slow` token (DFB islands); remove dead ternary `DfbScreener.jsx:356`.
16. **Tone (owner call):** academy emoji chrome + confetti → geometric glyphs, drop confetti (§3.5).

---

## 5. BUILD ORDER (Wave-2)

1. **Tokens** — add the 6 `-bg/-border` semantic tokens + kill off-palette hexes in the config.
2. **Shared UI kit** — build `components/ui/{Badge,StatusPill,Table,Card,Button,FilterSelect,
   LiveChip,PageHeader}.astro` + `ui/tokens.js` for islands (all resolve to `var(--…)`).
   Make the risk-color map (§3.3) a single exported constant both `.astro` and `.jsx` import.
3. **DFB /board** (worst offender) — swap the 4 islands onto the kit + `var(--…)`; unify sub-nav.
4. **Marketing pages** — sweep `red-*/emerald-*/teal-*/amber-*` verdicts + green eyebrows +
   `bg-white/[0.02]` onto the kit/tokens (largest file count, mechanical).
5. **Academy** — fix C/D map, add `-bg` tokens usage, tokenize cert, tone pass (owner-gated).
6. **Verify** — `cd landing && npm run build` (must stay 0-error) + a grep gate:
   `grep -rE '#EF4444|red-500|emerald-[0-9]|#F2963C|#9aa3b2|#0b0d12|#3b82f6' src/` → **0 hits**.

---

*End of V2 spec. No site files modified — audit + standard only. `DashboardLive.jsx` is the
reference dialect; the job is to make the other three surface groups look like it.*
