# SPA — Unified Site Architecture & Design System

> **Status:** SPEC (read-only / not yet built). Source of truth for the full rebuild of
> earn-defi.com. Builders implement directly from this document.
> **Author:** Product Architect / Design Lead audit.
> **Scope:** Astro landing (`landing/src/**`) + standalone data apps (`landing/public/*.html`).

---

## 0. TL;DR

The site is fragmented because **there is no shared chrome**. The header/nav lives *inside*
`Hero.astro` (homepage only); every other page hand-rolls its own `<nav>`; the standalone
HTML apps (`app`, `packages`, `tournament`, `agents`, `control`) each ship their own CSS
system. There are **4 conflicting brand names**, **2 competing dashboard URLs**
(`/app` vs `/dashboard`), **7 abandoned `agents-*` design experiments**, and **3 different
accent colors used for the same "eyebrow" label** role.

The fix: **one positioning statement → one design-token file → one canonical Header + Footer
component on every page → 4 page templates → a pruned sitemap.** Then rebuild.

---

## 1. FRAGMENTATION AUDIT (concrete, evidence-based)

### 1.1 Header / navigation is structurally broken

| Page group | Where nav comes from | Pattern |
|---|---|---|
| `index.astro` | `<nav>` hard-coded **inside `Hero.astro`** (`top-10 absolute`) | logo + Methodology · Risk · Packages · Agents · Tournament + **Dashboard→`/app`** |
| `methodology`, `fees`, `faq`, `strategies/index`, `blog/index` | each page's **own inline `<nav>`** | logo + breadcrumb + 1–2 links + **Dashboard→`/dashboard`** |
| `risk`, `trust`, `due-diligence`, `security`, `risk-disclosure`, `emergency-withdrawal` | each page's **own inline `<nav>`** | **"← Back to earn-defi.com"** arrow + tiny mono slug, **no nav links, no Dashboard CTA** |
| `status.astro` | its own **`<header>`** (not `<nav>`) with different bg `#0d0d0d` | "← SPA" + "Updated {date}" |
| `app.html`, `tournament.html` | **no header at all** (0 `<nav>`/`<header>`) | — |
| `packages.html`, `control.html` | own `.nav` pill row, emoji links | ← Landing · 📊 Dashboard · 📦 Packages · 🏆 Tournament · 🤖 Agents · 🛰️ Control |

**Net effect:** at least **5 distinct header treatments**; nav link set, order, and styling
differ on nearly every page; the doc pages (`risk`, `trust`, etc.) are dead-ends with no way
to reach the rest of the site except the browser back button.

### 1.2 Navigation link inconsistencies

- **Dashboard CTA target is split:** `href="/app"` appears 6×, `href="/dashboard"` 17×.
  `/dashboard` is a redirect stub → `/app`. So 17 links take an extra hop. There must be ONE.
- **Different link sets per page:** Hero shows {Methodology, Risk, Packages, Agents, Tournament};
  `fees` shows {Home, Methodology}; `faq` shows {Home, Methodology, Risk};
  `strategies/index` shows {Home, Risk Disclosure}; doc pages show {} (back-arrow only).
- **`/packages`, `/agents`, `/tournament`, `/control`** are reachable from the homepage Hero
  and the emoji nav of the public apps, but **invisible from any Astro doc page**.
- **Redirect chain / conflict:** `_redirects` maps `/status → /dashboard#golive` AND
  `/dashboard → /app`, while a real `status.astro` page also exists → ambiguous routing.

### 1.3 The homepage "packages" problem

- There are **two parallel, competing "packages" concepts** with different vocabulary, data,
  and visual language:
  - **Homepage `StrategySelector` + `StrategyCard`** → 3 named strategies *Preserve (6%) /
    Core (5%) / Max Yield (15%)*, status badges (paper-tracked / target-profile / coming-soon),
    risk bars, Tailwind/Inter dark cards.
  - **`/packages.html`** → 3 *risk-tier packages* (Conservative / Balanced / Aggressive),
    live API `tier1/packages`, totally different CSS (`--bg:#0b0f17`, system-ui font, emoji),
    different numbers.
- **Haphazard hierarchy on the card:** `StrategyCard` stacks 8 blocks of equal visual weight
  (status, name, tagline, APY, risk bars, description, who-it's-for, yield sources, CTA) with
  no clear primary read. The APY (the number that matters) competes with everything around it.
  Target APY `15%` on "Max Yield" reads as a promise despite the "coming-soon" status — a
  trust/tone risk for a transparency-first project.
- Strategy naming collides: card names (Preserve/Core/Max Yield) ≠ package names
  (Conservative/Balanced/Aggressive) ≠ internal engine sleeves. A visitor cannot map them.

### 1.4 Visual / token inconsistency

- **Two CSS systems:** Astro pages use Tailwind + `tailwind.config` tokens (accent = blue
  `#3b82f6`, surface `#0a0a0a`, Inter + JetBrains Mono). Standalone HTML pages use bespoke
  CSS-variable palettes — `packages.html` `--bg:#0b0f17 --card:#131a26 --acc:#3b82f6 --p:#8b5cf6`,
  `tournament.html` `#0d1117`, `status.astro` `#0d0d0d`, `dashboard.astro` redirect `#0b0c10`.
  At least **5 different "near-black" backgrounds** in use.
- **Fonts diverge:** Layout loads only Inter (weights 300–700) from Google Fonts, but the
  Tailwind config declares mono = "JetBrains Mono" which is **never loaded** in the Astro
  layout (so `font-mono` falls back to system mono). `app.html`/`tournament.html` *do* load
  JetBrains Mono. Inconsistent type rendering between marketing and app surfaces.
- **Eyebrow label color drift:** the small uppercase section label uses `text-accent-400`
  (66×), `text-green-400/70` (30×), `text-amber-400/70` (13×) for the *same role* with no
  semantic rule. Reads as three different brands.
- **Purple `--p:#8b5cf6`** appears only in `packages.html`, in nothing else.

### 1.5 Duplicated / competing / dead components

- **7 abandoned design experiments** shipped in `public/`: `agents-gallery.html`,
  `agents-map.html`, `agents-minimal.html`, `agents-spatial.html`, `agents-story.html`,
  `agents-terminal.html`, `agents2.html` — plus the live `agents.html`. **8 versions of one page.**
- `dashboard.astro` is a redirect-only stub (dead weight; `_redirects` already handles it).
- Live-stats logic is duplicated: `LiveStats.astro`, `LiveStatsWidget.jsx`,
  `GoLiveWidget.astro`, `RiskGatesSnapshot.astro`, `PaperTrackRecord.astro` all fetch/show
  overlapping live-API state with different framing.
- Fee content appears in `FeeStructure.astro`, the `/fees` page, and the homepage FAQ.

### 1.6 Brand / messaging inconsistency

- **4 different expansions of "SPA":** "Smart Passive Aggregator" (7×), "Stable Portfolio
  Agent" (4×, app.html title), "Stablecoin Portfolio Algorithm" (3×, OG site_name), plus the
  tagline "Systematic onchain stablecoin yield". The OG `site_name`, the `<title>`s, and the
  body copy disagree.
- Tone splits between **"family offices / private allocators"** (StrategyCard who-it's-for)
  and **"personal research project, not raising capital"** (Hero/Footer banner). These
  contradict each other on the same homepage.

### 1.7 Information-architecture gaps

- No global header → no discoverability of `/packages`, `/agents`, `/tournament`, `/control`,
  `/blog`, `/status` from most pages.
- Overlapping doc pages with unclear boundaries: `methodology` vs `due-diligence`
  (both "methodology & evidence"); `risk` vs `risk-disclosure`; `trust` vs `security`.
- No breadcrumb/active-state system; no "you are here".
- `/status` semantics ambiguous (page exists + redirect exists).

---

## 2. CORE PRODUCT IDEA / POSITIONING (the unifying concept)

### One-line positioning

> **SPA is a personal research project building an honest, public 30-day track record for a
> deterministic, LLM-free DeFi stablecoin-yield optimizer — in paper trading, not raising capital.**

### Brand decision (resolve the name)

- **Display name everywhere:** **SPA** (logotype) with the descriptor
  **"systematic onchain stablecoin yield."**
- **Retire** "Smart Passive Aggregator", "Stable Portfolio Agent", "Stablecoin Portfolio
  Algorithm" from all *user-facing* surfaces (`<title>`, OG, copy). SPA stays an
  un-expanded mark on the site. (Internal docs may keep "Smart Passive Aggregator".)
- **Domain line:** `earn-defi.com` shown as a quiet mono subtitle next to the logo.

### Value proposition (the three pillars everything ladders up to)

1. **Deterministic & honest.** A rules-only RiskPolicy (no LLM in risk/execution). Every
   decision is reproducible and logged.
2. **Transparent by default.** The dashboard, every paper trade, every risk-gate decision,
   the equity curve, and the go-live checklist are public and live.
3. **Track record before capital.** Paper-validating on live data since June 10, 2026; not
   soliciting or holding any user funds; go-live is own-capital only after 30 honest days.

### Tone of voice

Quiet, precise, institutional-quant. Numbers over adjectives. State limitations plainly
(paper, variable, not a forecast, not investment advice). **No hype, no "earn X%" promises,
no sales pressure.** Every yield figure is paired with a "paper / variable / not guaranteed"
qualifier. This is a lab notebook, not a fund pitch.

### Messaging guardrails (must hold on every page)

- Always say **paper / simulation** near any performance number.
- Never imply capital raising, deposits, withdrawals, or onboarding.
- Drop the "family offices / private allocators" audience framing — it contradicts
  "not raising capital." Audience = **technical peers, researchers, and the owner's own record.**

---

## 3. UNIFIED DESIGN SYSTEM

> Single source of tokens. Astro pages consume via Tailwind config; standalone HTML apps
> consume via a shared `:root` CSS-variable block (same hex values) so both surfaces match.

### 3.1 Color tokens (dark, institutional-quant)

```
/* Backgrounds — ONE near-black scale (kill the 5 competing blacks) */
--bg-base:        #0A0C10   /* page background, everywhere */
--bg-surface:     #11141A   /* cards, panels */
--bg-surface-2:   #181C24   /* nested panels, table header rows */
--bg-elevated:    #1E232C   /* hover / popover */
--border:         #232934   /* hairline borders (replaces white/5, white/10) */
--border-strong:  #313945   /* card hover border */

/* Text */
--text-primary:   #E8EAF0   /* headings, key numbers */
--text-secondary: #A6ADBB   /* body */
--text-muted:     #868D99   /* captions, mono labels, disclaimers — WCAG AA 5.5:1 (Q-OWN-21) */
--text-faint:     #727A88   /* eyebrow dim, microcopy — WCAG AA 4.3:1 (Q-OWN-21) */

/* Brand accent — refined indigo-blue (single primary) */
--accent:         #5B8DEF   /* primary accent, links, primary CTA */
--accent-hover:   #79A4F5
--accent-dim:     #2C4A8A   /* borders/glow at low opacity */
--accent-bg:      rgba(91,141,239,0.10)

/* Secondary accent — quant teal (data viz, live ticks) */
--data-teal:      #36C2B4

/* Semantic (use ONLY for meaning, never as decoration/eyebrow color) */
--ok:             #34D399   /* pass / live / healthy */
--warn:           #F2B53C   /* paper-mode banner, pending, caution */
--danger:         #F26D6D   /* fail, kill-switch, error */
--info:           #5B8DEF   /* = accent */
```

**Rules:**
- Eyebrow / section-label color is **always `--text-faint` or `--accent`** — *never* green/amber.
  Green and amber are reserved for **status semantics only** (a passing gate, the paper banner).
- The recurring **paper-trading banner** is the only persistent amber surface:
  `bg: var(--warn) @ 10% / border var(--warn) @ 20% / text var(--warn) @ 85%`.
- Retire purple `#8b5cf6` entirely.

### 3.2 Typography

```
Font families:
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif
  --font-mono: 'JetBrains Mono', 'SFMono-Regular', ui-monospace, monospace
```
- **Load BOTH** Inter (400/500/600/700) **and** JetBrains Mono (400/500/600) in the global
  layout (`landing/src/layouts/Layout.astro`) and in every standalone HTML `<head>`. (Today
  the Astro layout loads only Inter — fix.)
- Mono is used for: numbers/APY/equity, eyebrow labels, code, slugs, data tables, live ticks.

**Type scale (rem / line-height / weight):**

| Token | Size | LH | Weight | Use |
|---|---|---|---|---|
| `display` | 3.5rem (56) | 1.05 | 700 | Hero H1 (desktop) |
| `h1` | 2.25rem (36) | 1.15 | 700 | Page titles |
| `h2` | 1.5rem (24) | 1.25 | 600 | Section heads |
| `h3` | 1.25rem (20) | 1.3 | 600 | Card titles |
| `body-lg` | 1.125rem (18)| 1.6 | 400 | Hero sub, lede |
| `body` | 1rem (16) | 1.6 | 400 | Default text |
| `small` | 0.875rem (14)| 1.5 | 400 | Captions, secondary |
| `eyebrow` | 0.75rem (12) | 1.4 | 600 | Mono uppercase, letter-spacing .12em |
| `metric` | 2.5rem (40) | 1.0 | 700 | Big numbers (mono) |

Hero `display` scales down: 56 → 40 (tablet) → 32 (mobile).

### 3.3 Spacing scale (8px base)

`4, 8, 12, 16, 24, 32, 48, 64, 96, 128` px → tokens `space-1 … space-10`.
- Section vertical padding: **96px desktop / 64px tablet / 48px mobile**.
- Content max-widths: marketing sections `1152px` (max-w-6xl); doc/article body `768px`
  (max-w-3xl); data-app tables `1040px`.
- Card inner padding: `24px` (mobile) → `32px` (desktop).

### 3.4 Radius

`--r-sm: 8px` (buttons, chips) · `--r-md: 12px` (inputs, small cards) ·
`--r-lg: 16px` (cards) · `--r-xl: 24px` (hero panels, feature cards) · `--r-full: 9999px` (pills).

### 3.5 Shadows & elevation

```
--shadow-sm:  0 1px 2px rgba(0,0,0,.4)
--shadow-md:  0 4px 16px rgba(0,0,0,.45)
--shadow-cta: 0 6px 20px rgba(91,141,239,.25)   /* accent glow on primary CTA */
```
Dark UI relies on **border + bg-step** for elevation more than shadow. Cards = surface bg +
1px `--border`; hover = `--border-strong`. Avoid heavy drop shadows.

### 3.6 Motion

- Durations: `120ms` (hover/color), `200ms` (transform), `400ms` (entrance).
- Easing: `cubic-bezier(.4,0,.2,1)`.
- Allowed: color/opacity transitions, subtle 2–4px translate on hover, slow pulse on the
  single live-status dot (`pulse 3s`).
- Forbidden: parallax, autoplay carousels, large scroll-jacking, anything that delays LCP.
- Respect `prefers-reduced-motion`.

---

## 4. GLOBAL COMPONENTS (appear on EVERY page)

### 4.1 Canonical Header (`components/SiteHeader.astro` — NEW, replaces all inline navs)

Sticky, `height 64px`, `bg: var(--bg-base)` at 80% + `backdrop-blur`, bottom `1px --border`.

**Left:** logo (`favicon.svg`, 28px) + **SPA** wordmark + mono `earn-defi.com` (hidden < sm).
Logo links to `/`.

**Center / right (primary nav — exact link set & order):**

| # | Label (EN) | Label (RU) | Href | Priority |
|---|---|---|---|---|
| 1 | Methodology | Методология | `/methodology` | primary |
| 2 | Strategies | Стратегии | `/strategies` | primary |
| 3 | Track Record | Трек-рекорд | `/track-record` | primary |
| 4 | Research | Исследование | `/research` (blog) | secondary |
| 5 | System | Система | `/system` (status/agents/control hub) | secondary |
| — | **Dashboard ↗** | **Дашборд ↗** | **`/app`** | **CTA (accent outline button)** |
| — | EN \| RU | — | toggle | far right |

**Rules:**
- The Dashboard CTA href is **`/app` everywhere** (kill the 17 `/dashboard` links; keep the
  redirect only as a safety net).
- Active link gets `--text-primary` + 2px accent underline; others `--text-secondary`.
- The **EN|RU toggle moves INTO the header** (right of the CTA). Remove the free-floating
  fixed `#spa-lang-toggle` from the layout so it stops overlapping page content. Keep the
  same `data-ru` runtime mechanism.
- **Mobile (< md):** logo + hamburger → slide-down panel listing all nav items + CTA + toggle.
- Standalone HTML apps embed the **same header markup** (a small shared partial / copy) using
  the shared `:root` tokens so chrome is pixel-identical to the Astro pages.

### 4.2 Persistent Paper-Mode Strip

A single thin amber strip directly under the header on **every** page (currently duplicated in
Hero + Footer):
> "Personal research project — paper-testing & tuning, not raising capital."
`bg --warn@10% / border-bottom --warn@20% / text --warn@85% / 12px`. One component, one place.

### 4.3 Canonical Footer (`components/SiteFooter.astro` — keep & standardize)

Keep current 4-column structure, retoken to the palette. Columns:

- **Brand:** logo + descriptor "Systematic onchain stablecoin yield. Research project in paper
  validation since June 10, 2026." + a "Paper Trading Mode" status dot.
- **Research:** Methodology · Evidence (`/due-diligence`) · Track Record · Research journal.
- **Documentation:** Risk · Trust & Security · System status.
- **Legal:** Risk Disclosure · Disclaimer.
- **Bottom row:** "© 2026 earn-defi.com · Not investment advice · Not a regulated financial
  service · Research project" + "No personal data collected or stored."

Footer link set must be a **superset** of the header nav (footer can expose the long tail;
header carries the 5 primary destinations).

### 4.4 Buttons

| Variant | Style |
|---|---|
| Primary | `bg --accent`, text white, `--r-sm`, `--shadow-cta`, hover `--accent-hover` |
| Secondary | transparent, `1px --border` → hover `--border-strong`, text `--text-secondary`→primary |
| CTA-outline (header) | `1px --accent@50%`, text `--accent`, 12px, hover brighten |
| Ghost/link | text `--accent`, underline-offset on hover |
| Disabled | `--text-muted`, `1px --border`, `cursor:not-allowed` (e.g. "Coming Soon") |

Sizes: sm `padding 8/14`, md `12/24`, lg `16/28`.

### 4.5 Cards

Base: `bg --bg-surface`, `1px --border`, `--r-lg`, padding 24/32, hover `--border-strong`.
Variants: **metric card** (big mono number + label), **doc card** (title + body),
**strategy card** (see §5.3), **status card** (semantic left border 3px).

### 4.6 Section pattern

Every marketing section = `eyebrow (mono, --text-faint/accent)` → `h2` → optional lede →
content. Consistent 96px vertical rhythm. Eyebrow color is **never** green/amber.

---

## 5. PAGE TEMPLATES

### 5.1 Marketing template
Header + paper strip → Hero / sections (max-w-6xl) → Disclaimer → Footer.
Used by: Home, Strategies index, strategy detail, Track Record.

### 5.2 Document/article template
Header + paper strip → page title block (eyebrow + h1 + lede) → **max-w-3xl** prose with
consistent `h2`/`h3`/list/callout styles → "Related" links → Footer.
Used by: Methodology, Risk, Trust, Security, Fees, FAQ, Risk Disclosure, Due Diligence,
Emergency Withdrawal, Research/blog posts.
**Replaces** the back-arrow dead-end nav on doc pages with the full canonical header.

### 5.3 Data-app template (packages / tournament / agents / control / dashboard)
Same header + paper strip (shared markup, shared `:root` tokens) → app title row + live-source
chip (`Live from api.earn-defi.com · regime · updated …`) → app body → minimal footer note.
All built on the SAME tokens; no bespoke palettes.

**Dashboard (`/app`)** stays the canonical live dashboard. Retoken to the palette, add the
shared header so it stops being chrome-less.

#### Packages presentation (fix the "haphazard" problem)
- **Unify the two systems.** Pick ONE taxonomy and use it on both the homepage card grid and
  `/packages`. Recommended: keep the **named strategies Preserve / Core / Max Yield** as the
  public face; treat "risk-tier packages" as the live data feeding those same three cards.
  Map names ↔ tiers explicitly (Preserve=Conservative, Core=Balanced, Max Yield=Aggressive).
- **Clean tier card hierarchy** (top → bottom, strict visual weight order):
  1. **Tier name** (h3) + 3px semantic top border (teal=Preserve / accent=Core / amber=Max Yield).
  2. **Status pill** (Paper-tracked / Target profile / Coming soon).
  3. **APY — the hero number** (`metric`, mono) with an immediate small caption
     "paper · variable · not guaranteed". This is the single dominant element.
  4. **2–3 key facts only** as a tight definition list (risk band, max drawdown, tier mix).
  5. Short one-line "who/what it is".
  6. Single CTA ("View strategy details").
- **Cut** yield-source chip walls and dual descriptions from the card; move detail to the
  strategy page. Three cards, identical structure, equal height, clear primary read on APY.
- Remove the "15% target" headline prominence for the coming-soon tier (show as a *range*, de-emphasized, with a clear "not in paper track" note) to protect the transparency-first tone.

---

## 6. INFORMATION ARCHITECTURE (definitive sitemap)

```
/                      Home (marketing)
/methodology           How it works: deterministic engine, RiskPolicy, daily cycle
/strategies            Strategy index (3 unified tier cards)
   /strategies/preserve
   /strategies/core
   /strategies/max-yield
/track-record          NEW canonical page: live equity curve + paper stats + go-live progress
                       (absorbs PaperTrackRecord + GoLiveWidget + status content)
/risk                  Risk philosophy & controls   (doc)
/risk-disclosure       Legal risk disclosure        (doc, legal)
/trust                 Trust & architecture          ← MERGE security into this as a section
/fees                  Fee model (illustrative, live-phase only)   (doc)
/faq                   FAQ  (doc)  — methodology questions only
/research              Research journal / blog index (was /blog)
   /research/<post>
/system                NEW hub for operational surfaces:
   /app                Live dashboard (canonical; /dashboard 302→ here)
   /packages           Risk-tier packages (unified taxonomy)
   /tournament         Strategy tournament
   /agents             Autonomous agent fleet
   /control            Control plane (Tier-1)
   /status             System status  (or fold into /system)
```

### Merge / cut / keep decisions

**CUT (delete from `public/`):** `agents-gallery.html`, `agents-map.html`,
`agents-minimal.html`, `agents-spatial.html`, `agents-story.html`, `agents-terminal.html`,
`agents2.html` (7 abandoned experiments). Keep one `agents.html`.
**CUT:** `dashboard.astro` redirect stub (let `_redirects` own it).
**MERGE:** `security.astro` → a section inside `/trust` (overlapping scope).
**MERGE:** `due-diligence` evidence content → `/track-record` + `/methodology`
(both currently claim "methodology & evidence").
**MERGE/CLARIFY:** `status.astro` → `/system` (or `/status` under it); remove the
`/status → /dashboard#golive` redirect that conflicts with the page.
**KEEP & retemplate:** index, methodology, strategies/*, risk, risk-disclosure, trust, fees,
faq, blog→research, app, packages, tournament, agents, control.
**Resolve redirects:** exactly one Dashboard URL = `/app`; `/dashboard 302→/app` stays as
safety net only.

---

## 7. THREE HOMEPAGE CREATIVE DIRECTIONS

> All three share §2 positioning, §3 tokens, §4 header/footer/paper-strip, and the unified
> tier-card spec (§5.3). They differ only in layout, hero concept, and emotional emphasis.
> Each is a buildable brief.

### Direction A — "Instrument" (institutional-quant, data-forward) — *recommended default*

- **Emotional tone:** a live trading desk / lab instrument. Calm authority, numbers-first.
- **Hero:** split layout. Left = H1 "Systematic onchain stablecoin yield." + 2-line research
  framing + primary CTA "Methodology" / secondary "View live dashboard". Right = a **live
  mini-panel** (paper day N, current paper APY, equity sparkline, "X/29 go-live criteria"),
  pulled from the live API, with mono type. Background = subtle dark gradient, no imagery.
- **Section order:** Hero → **Live track strip** (4 metric cards: paper days, paper APY,
  drawdown, go-live progress) → How it works (3-step deterministic cycle) → **Strategies**
  (3 unified tier cards) → Risk gates snapshot (the deterministic policy, table) → Methodology
  & evidence CTA → FAQ → Disclaimer → Footer.
- **Packages/track/methodology featured:** track record is the *hero's right rail* and the
  first section; strategies are clean tier cards mid-page; methodology is the primary CTA.

### Direction B — "Field Notes" (editorial / trust-first storytelling)

- **Emotional tone:** an honest lab notebook. Warm, literary, transparency as the story.
- **Hero:** centered, single column, generous whitespace. Large `display` headline
  "Building an honest track record — in public." + a dated dek "Paper trading since
  June 10, 2026. Day N. No capital raised." One quiet primary CTA "Read the methodology".
- **Section order:** Hero → **narrative timeline** ("Why paper first → how the engine decides
  → what we log → when go-live") → an embedded **latest research entry** (pull newest
  `/research` post) → Strategies as a calm 3-card row → live track record block → principles
  ("Deterministic. Transparent. Track record before capital.") → FAQ → Footer.
- **Packages/track/methodology featured:** methodology and the *story* lead; strategies and
  track record support it; research journal is surfaced on the homepage to prove ongoing work.

### Direction C — "Console" (minimal / product-led)

- **Emotional tone:** stripped, confident, product = the dashboard. Minimal marketing.
- **Hero:** near-full-viewport. One line H1, one line sub, one dominant CTA "Open dashboard ↗"
  + ghost "Methodology". A single live status line in mono under the CTA
  ("● paper mode · day N · ~X% paper APY · Y/29 criteria"). Almost no chrome.
- **Section order:** Hero → **one** combined band: 3 tier cards inline with a compact live
  equity sparkline beside them → a 3-bullet "how it works" → minimal footer with the long-tail
  links. Everything above the fold or one scroll.
- **Packages/track/methodology featured:** strategies (tier cards) ARE the main content block;
  track record is a compact inline sparkline; methodology demoted to a secondary link. Best if
  the goal is to drive visitors straight into `/app`.

---

## 8. BUILD ORDER (for implementer agents)

1. Create token layer: extend `tailwind.config` with §3 values **and** a shared
   `public/tokens.css` `:root` block (same hex) for standalone HTML apps. Load Inter +
   JetBrains Mono in `Layout.astro` and every standalone `<head>`.
2. Build `SiteHeader.astro` (§4.1) + `PaperStrip.astro` (§4.2); move EN|RU toggle into header;
   remove the floating toggle and the in-Hero nav.
3. Refactor `Layout.astro` to render Header + PaperStrip + `<slot/>` + Footer so **every**
   Astro page gets identical chrome; delete all inline `<nav>`/`<header>` from pages.
4. Retoken `SiteFooter.astro` (§4.3); unify `Disclaimer`.
5. Rebuild `StrategyCard`/`StrategySelector` to the clean tier-card hierarchy (§5.3) and unify
   with `/packages` taxonomy.
6. Embed shared header + tokens into `app/packages/tournament/agents/control` HTML.
7. Apply IA changes (§6): cut the 7 `agents-*` files + `dashboard.astro`, merge security→trust,
   add `/track-record` and `/system`, fix `/app` vs `/dashboard` links and the `/status` redirect.
8. Implement chosen homepage direction (default: A).

---

*End of spec. No site files were modified — analysis & spec only.*
