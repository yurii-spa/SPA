# DESIGN SPEC — earn-defi.com v2
## SPA (Stable Portfolio Agent) · Product Site Redesign

**Version:** 2.0  
**Date:** 2026-06-19  
**Stack:** Astro 4 SSG · CSS custom properties · Zero JS frameworks on critical path  
**Audience:** Family offices, allocators, private capital · $25K–$250K AUM  
**Design language:** Dark-first · Data-dense but legible · No DeFi degen aesthetics

---

## TABLE OF CONTENTS

1. [Design Principles](#1-design-principles)
2. [Color & Typography Tokens](#2-color--typography-tokens)
3. [Main Page — Section Breakdown](#3-main-page--section-breakdown)
4. [StrategyCard Component Spec](#4-strategycard-component-spec)
5. [/trust Page Spec](#5-trust-page-spec)
6. [/security & /emergency-withdrawal Stubs](#6-security--emergency-withdrawal-stubs)
7. [Mobile UX](#7-mobile-ux)
8. [Copywriting Rules](#8-copywriting-rules)
9. [Implementation Notes](#9-implementation-notes)

---

## 1. DESIGN PRINCIPLES

### 1.1 Core Directives

| # | Directive | Rationale |
|---|---|---|
| P1 | **Strategy first, metrics second** | Allocators choose risk posture before they look at numbers |
| P2 | **Paper ≠ Live** | Visual separation mandatory everywhere metrics appear |
| P3 | **APY is a variable, not a promise** | Every APY figure carries a disclaimer tag |
| P4 | **Earn trust before asking for capital** | CTA hierarchy: Learn → Verify → Then Act |
| P5 | **Risk gradient is spatial** | Cards always left = safer, right = higher risk |
| P6 | **Never: safe, guaranteed, protected, risk-free** | Banned words — hard rule |
| P7 | **Dense but not cluttered** | One primary number per card section |
| P8 | **Transparency over polish** | Show methodology links, on-chain references, real dates |

### 1.2 Persona Reference

**Primary:** Sofia K., family office investment manager, 38, Zurich  
— Manages $40M across alternatives  
— Evaluates products via: track record, team, methodology, risk controls  
— Red flags: inflated APY claims, opaque fees, lack of legal docs  
— Does not self-custody; needs audit trail

**Secondary:** Marcus T., independent allocator, 44, Singapore  
— $500K discretionary allocation budget  
— Comfortable with DeFi mechanics, skeptical of "yield farming"  
— Wants: protocol risk breakdown, drawdown history, exit conditions

---

## 2. COLOR & TYPOGRAPHY TOKENS

### 2.1 Base Tokens (existing, keep as-is)

```css
/* Base */
--color-bg:          #0f0f0f;
--color-bg-raised:   #161616;
--color-bg-card:     #1a1a1a;
--color-bg-muted:    #222222;

/* Text */
--color-text-primary:   #f0f0f0;
--color-text-secondary: #a0a0a0;
--color-text-muted:     #666666;
--color-text-inverse:   #0f0f0f;

/* Borders */
--color-border:         #2a2a2a;
--color-border-subtle:  #1f1f1f;

/* Existing accents */
--color-apy-green:   #22c55e;   /* positive yield */
--color-risk-red:    #ef4444;   /* risk / warning */
--color-warning:     #f59e0b;   /* caution states */
```

### 2.2 New Tokens — Strategy Risk Gradient

```css
/* Risk level badge colors */
--color-risk-low:         #34d399;   /* emerald-400 — Preserve */
--color-risk-low-bg:      #064e3b1a; /* transparent tint */
--color-risk-low-border:  #065f46;

--color-risk-medium:      #60a5fa;   /* blue-400 — Core */
--color-risk-medium-bg:   #1e3a5f1a;
--color-risk-medium-border: #1d4ed8;

--color-risk-high:        #f97316;   /* orange-400 — Max Yield */
--color-risk-high-bg:     #431a051a;
--color-risk-high-border: #c2410c;
```

### 2.3 New Tokens — Status Badges

```css
/* Status badge tokens */
--badge-paper-tracked-bg:      #1a2a1a;
--badge-paper-tracked-border:  #22c55e;
--badge-paper-tracked-text:    #86efac;   /* green-300 */

--badge-target-profile-bg:     #1f1f2e;
--badge-target-profile-border: #6366f1;
--badge-target-profile-text:   #a5b4fc;   /* indigo-300 */
/* Usage: This strategy is described but metrics are TARGET, not historical */

--badge-coming-soon-bg:        #1f1f1f;
--badge-coming-soon-border:    #3f3f46;
--badge-coming-soon-text:      #71717a;   /* zinc-500 */

--badge-live-bg:               #052e16;
--badge-live-border:           #16a34a;
--badge-live-text:             #4ade80;
/* Pulsing green dot indicator when status = live */
```

### 2.4 New Tokens — Card States

```css
/* Card selected / hover state */
--card-hover-border:  #3a3a3a;
--card-selected-border: var(--color-risk-medium); /* adapts per strategy */
--card-selected-glow:   0 0 0 1px var(--card-selected-border),
                        0 4px 24px rgba(96, 165, 250, 0.08);

/* Card: "current strategy" indicator (Core is current active) */
--card-current-accent: #60a5fa;
--card-current-bar-h:  3px;      /* top border bar for active card */
```

### 2.5 Typography Scale

```css
/* Display — Hero headline */
--font-display-xl:   clamp(2.25rem, 5vw, 3.75rem); /* 36→60px */
--font-display-l:    clamp(1.75rem, 3.5vw, 2.5rem); /* 28→40px */

/* Section headers */
--font-section-head: 1.375rem;   /* 22px */
--font-section-sub:  0.9375rem;  /* 15px, --color-text-secondary */

/* Card components */
--font-card-label:   0.6875rem;  /* 11px, uppercase, ls 0.08em */
--font-card-apy:     2rem;       /* 32px, bold, tabular nums */
--font-card-body:    0.875rem;   /* 14px */

/* Badge */
--font-badge:        0.6875rem;  /* 11px, weight 600 */

/* Legal/disclaimer */
--font-legal:        0.75rem;    /* 12px, --color-text-muted */
```

### 2.6 Spacing System (8px base)

```
4px  — icon gap, tight inline
8px  — component internal padding
12px — small element gap
16px — standard element spacing
24px — card internal padding
32px — section sub-gap
48px — section gap (mobile)
64px — section gap (desktop)
96px — major section gap
```

---

## 3. MAIN PAGE — SECTION BREAKDOWN

Page URL: `earn-defi.com/`  
Max content width: `1200px`  
Horizontal padding: `clamp(16px, 4vw, 48px)`

---

### Section 1 — HERO

**Purpose:** Communicate what SPA is and who it's for in under 5 seconds. Establish credibility through language precision (no hype).

**Layout:** Full-viewport-height section. Vertically centered content block, max 640px wide. Background: `--color-bg` + subtle grid texture (1px lines at 40px, opacity 3%).

#### 1a. Pre-headline eyebrow tag

```
[  SPA · STABLE PORTFOLIO AGENT  ]
```
— Monospace font (`font-mono`), 11px, letter-spacing 0.12em  
— Color: `--color-text-muted`  
— Not a badge, just inline text  

#### 1b. Headline

```
Institutional-grade DeFi yield.
Managed by protocol, not promises.
```

— `--font-display-xl`  
— Color: `--color-text-primary`  
— Line 2 slightly lighter (85% opacity) to create hierarchy  
— NO gradient text, NO glowing effects — trust signal  

#### 1c. Sub-headline

```
SPA allocates capital across audited DeFi protocols using a
deterministic risk policy. Paper-tracked since June 2026.
```

— 17px, `--color-text-secondary`  
— Max 520px wide  
— "Paper-tracked since June 2026" — key credibility anchor, always include date  

#### 1d. CTA Hierarchy (three levels, left-aligned on desktop, stacked mobile)

```
PRIMARY:   [ Choose Your Strategy ↓ ]       ← scrolls to Strategy Selector
SECONDARY: [ Access Dashboard ]             ← opens dashboard (new tab)
TERTIARY:  [ Start Due Diligence →  ]       ← links to /trust
```

**Primary CTA styling:**
- Background: `#f0f0f0` (light fill on dark bg)
- Text: `--color-text-inverse` (#0f0f0f)
- Padding: 12px 28px
- Border-radius: 6px
- Font: 15px, weight 600

**Secondary CTA styling:**
- Background: transparent
- Border: 1px solid `--color-border`
- Text: `--color-text-primary`
- Same dimensions as primary

**Tertiary CTA styling:**
- No background, no border
- Text: `--color-text-secondary`
- Arrow → inline
- Underline on hover

#### 1e. Hero Trust Strip (below CTAs, 48px margin-top)

Single horizontal row of 4 micro-stats, separated by `|`:

```
Paper track since Jun 2026  |  $100K virtual capital  |  Deterministic risk policy  |  0 external dependencies
```

— 12px, `--color-text-muted`  
— These are verifiable facts, not marketing claims  

#### 1f. Hero Scroll Indicator

Minimal animated chevron `↓` below trust strip. Disappears after first scroll. CSS animation only (no JS).

---

### Section 2 — STRATEGY SELECTOR

**Purpose:** This is the core conversion point. User picks their risk profile. First impression of product depth.

**Headline:**

```
Choose your risk profile
```

— `--font-section-head`  
— Followed immediately (8px) by:  
```
Three distinct strategies. Different risk postures. One managed system.
```
— 14px, `--color-text-secondary`

#### 2a. Risk Gradient Visual Header

Above the three cards, a visual strip showing risk direction:

```
LOWER RISK ————————————————————————————— HIGHER RISK
     ●                    ●                    ●
  Preserve               Core              Max Yield
```

— The line is a CSS gradient: `--color-risk-low` → `--color-risk-medium` → `--color-risk-high`  
— 1px height, full card-area width  
— Dots are 8px circles in their respective risk colors  
— Labels in 11px monospace, colored per risk level  
— On mobile: hide this strip; risk is communicated via card badge only  

#### 2b. Card Grid

```
Desktop: 3-column grid, 24px gap
Tablet (768–1024px): 3-column grid, 16px gap (narrower cards)
Mobile (<768px): single column, full width
```

Cards: see Section 4 (StrategyCard Component Spec) for full detail.

Card order (always left → right, never reordered):
1. **Preserve** — Lower Risk
2. **Core** ← `[CURRENT · PAPER TRACKED]` highlight
3. **Max Yield** — Higher Risk / Coming Soon

#### 2c. Post-Card Disclaimer

Immediately below card row:

```
APY figures are targets based on current protocol rates, not guaranteed returns.
Paper tracking uses virtual capital. Past simulated performance does not indicate
future results. See Risk Disclosure for full methodology.
```

— 12px, `--color-text-muted`  
— Centered, max 680px wide  
— "Risk Disclosure" links to `/risk`  

---

### Section 3 — CURRENT PAPER TRACK RECORD

**Purpose:** Show real (paper) performance data for the active strategy (Core). Visually disambiguated from "target profiles."

**Headline:**

```
Paper Track Record — Core Strategy
```

Subline: `Active since June 10, 2026 · Virtual capital: $100,000 USDC`

**CRITICAL visual treatment: PAPER CONTEXT BANNER**

A persistent banner above all metrics in this section:

```
┌─────────────────────────────────────────────────────────────────┐
│  📋  PAPER TRADING  ·  Virtual capital only  ·  No real funds   │
└─────────────────────────────────────────────────────────────────┘
```
— Background: `#1a1a00` (very dark amber tint)  
— Border: 1px solid `#3d3000`  
— Text: `#fbbf24` (amber-400), 12px  
— This banner is NOT dismissible  

#### 3a. Metric Grid (2×3 on desktop, stacked on mobile)

| Metric | Value style | Label |
|---|---|---|
| Days tracked | Large number, `--color-text-primary` | "Days tracked (paper)" |
| Portfolio APY (paper) | `--color-apy-green`, bold | "Actual paper APY *" |
| Virtual equity | Standard number | "Virtual equity (started $100K)" |
| Max drawdown | `--color-risk-red` if >0 | "Max drawdown (paper)" |
| Rebalance events | Standard | "Rebalances executed" |
| Risk blocks | `--color-warning` | "RiskPolicy blocks (this period)" |

Footer footnote (*): `"APY calculated on virtual paper portfolio. Variable, not guaranteed."`

#### 3b. Mini Equity Curve

Small sparkline chart (no axes labels except start/now endpoints):
- Width: 100%, Height: 80px
- Line color: `--color-apy-green`
- Area fill: gradient from line color (20% opacity) to transparent
- Show start value and current value as tooltips on hover
- Paper watermark: light "PAPER" text centered in chart area, 10% opacity

Implementation: SVG path or canvas, no external charting library on critical path. Can lazy-load.

#### 3c. "Why paper matters" callout

```
[ Why paper track record? ]
SPA operates in paper mode for a minimum of 30 days before any
live deployment. This ensures strategy behavior is verified under
real market conditions before real capital is at risk.
```

— Expandable accordion, collapsed by default  
— `[+]` toggle  

---

### Section 4 — HOW SPA WORKS

**Purpose:** Explain the system in 3 clear steps. No technical jargon beyond what's necessary. Links to methodology.

**Headline:** `How SPA manages capital`

**Layout:** 3-column on desktop (or 3-step horizontal with connectors), stacked on mobile.

#### Step 1 — READ

```
Icon: 👁 or custom SVG (eye / data stream)

Title: "Read market conditions"

Body: "Every day, SPA queries live APY and TVL data from
whitelisted DeFi protocols via on-chain and aggregator feeds.
No human judgment. No manual override."

Link: [ View adapter registry → ]
```

#### Step 2 — EVALUATE

```
Icon: ⚖️ or custom SVG (scales / shield)

Title: "Apply deterministic risk policy"

Body: "A fixed rule-set — not AI, not human discretion —
evaluates each protocol against 6 hard limits: TVL floor,
concentration caps, APY bounds, drawdown kill-switch.
Policy version v1.0 is locked during paper period."

Link: [ Read risk policy → ] (links to /risk)
```

#### Step 3 — REBALANCE

```
Icon: ⟳ or custom SVG (arrows cycling)

Title: "Rebalance if threshold crossed"

Body: "When target allocation drifts beyond threshold,
SPA executes a virtual rebalance trade. Each trade is
logged with timestamp, rationale, and position delta."

Link: [ View trade log → ] (links to dashboard/trades)
```

**Connector between steps:** A subtle dashed line → on desktop. Not visible on mobile.

---

### Section 5 — TRUST & TRANSPARENCY STRIP

**Purpose:** Quick confidence builders before the detailed /trust page. 4 pillars.

**Headline:** `Built for allocators who verify, not assume`

**Layout:** 2×2 grid on desktop/tablet, stacked on mobile.

#### Pillar 1 — On-chain verifiable

```
Title: "On-chain verifiable"
Body: "All protocol selections reference live on-chain data.
No black-box signals."
Link: [ Adapter methodology → ]
```

#### Pillar 2 — Deterministic policy

```
Title: "No discretionary moves"
Body: "RiskPolicy v1.0 is a deterministic rule-set. No AI,
no LLM, no human override in the allocation loop."
Link: [ Policy v1.0 → ]
```

#### Pillar 3 — Full audit trail

```
Title: "Every decision is logged"
Body: "Every rebalance, every risk block, every cycle
produces a structured JSON log entry. Available for review."
Link: [ View logs → ]
```

#### Pillar 4 — Emergency exit

```
Title: "Clear exit mechanism"
Body: "5% portfolio drawdown triggers automatic full exit
to cash. Manual emergency exit available anytime."
Link: [ Emergency withdrawal → ] (links to /emergency-withdrawal)
```

**After the 4 pillars, a single CTA:**

```
[ Full transparency report → /trust ]
```
— Right-aligned, secondary button style  

---

### Section 6 — RISK GATES SNAPSHOT

**Purpose:** Show that the system has hard stops. Builds trust with allocators who care about downside management. Shows live status.

**Headline:** `Active risk gates`  
**Subline:** `These parameters run on every cycle. Cannot be overridden.`

**Layout:** Compact table (not cards) — allocators trust tables more than marketing tiles.

```
┌────────────────────────────────┬──────────────┬───────────────┐
│ Parameter                      │ Limit        │ Current status│
├────────────────────────────────┼──────────────┼───────────────┤
│ Protocol TVL floor             │ ≥ $5M        │ ✓ All pass    │
│ Per-protocol allocation cap    │ ≤ 40% (T1)   │ ✓ Within      │
│ T2 protocol total cap          │ ≤ 50%        │ ✓ Within      │
│ APY range for new positions    │ 1% – 30%     │ ✓ In range    │
│ Minimum cash buffer            │ ≥ 5%         │ ✓ Held        │
│ Portfolio drawdown kill-switch │ ≥ 5% → exit  │ ✓ Not triggered│
└────────────────────────────────┴──────────────┴───────────────┘
```

— Status column: green check `✓` for pass, amber `⚠` for near-limit, red `✗` for breach  
— "Current status" pulls from `data/risk_policy_blocks.json` via Astro data fetch at build time  
— Footer: `"Last verified: [build timestamp]"` — 12px muted  
— Link below table: `[ Full risk policy v1.0 → /risk ]`  

---

### Section 7 — FEES PREVIEW

**Purpose:** Give fee clarity upfront — allocators want this before going deeper.

**Headline:** `Fee structure`

**Layout:** Simple 3-column horizontal rule (desktop), stacked (mobile).

```
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│  Management fee     │ │  Performance fee     │ │  Exit fee           │
│                     │ │                      │ │                     │
│  0% during paper    │ │  0% during paper     │ │  None               │
│  period             │ │  period              │ │                     │
│                     │ │                      │ │                     │
│  [To be announced   │ │  [To be announced    │ │  Emergency exit:    │
│   at go-live]       │ │   at go-live]        │ │  always available   │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
```

Below: `Full fee methodology will be published before go-live. Target: 2026-08-01.`  
Link: `[ Fee methodology → /fees ]`

---

### Section 8 — DUE DILIGENCE CTA

**Purpose:** Convert allocator-persona visitors who want to go deep before committing. This is the second primary conversion goal (after strategy selection).

**Layout:** Full-width dark section, slightly raised background (`--color-bg-raised`). Max content 700px centered.

**Headline:** `Ready to do your due diligence?`

**Body:**

```
We've built SPA for allocators who verify before they deploy.
Start with the methodology, review the risk policy, examine
the trade log — in whatever order makes sense for your process.
```

**CTA Row (two equal cards side-by-side on desktop, stacked mobile):**

Card A:
```
[ For Allocators ]
Full documentation package: methodology, risk policy,
adapter registry, track record data, legal framework.
[ Start Due Diligence → /trust ]
```

Card B:
```
[ Schedule a Call ]
15-minute intro call for qualified allocators.
Minimum: $25K consideration.
[ Request Intro ]  ← opens email link or Calendly
```

Both cards: border `--color-border`, radius 8px, padding 24px, no fill.

---

### Section 9 — RISK WARNING

**Purpose:** Legal protection + trust signal. Allocators respect transparent risk disclosure; it makes the rest of the site more credible, not less.

**Layout:** Full-width, very subtle background `--color-bg-muted`. Text only, no decorative elements.

**Content:**

```
RISK DISCLOSURE

DeFi protocols involve smart contract risk, oracle risk, liquidity risk,
and regulatory uncertainty. Yield rates are variable and determined by
market conditions — they are not guaranteed and may be zero or negative.

SPA currently operates in paper trading mode with virtual capital only.
No real funds are allocated during this phase. Historical paper performance
does not indicate future live trading results.

Participation in SPA is available to qualified investors only, subject to
applicable local regulations. This website does not constitute investment
advice. Consult your financial and legal advisors before making any allocation.

Go-live target: August 1, 2026, subject to readiness criteria.
```

— 13px, `--color-text-muted`  
— Line height: 1.7  
— Max width: 780px, centered  
— No headers, no bullets — reads as continuous legal prose  
— Small top rule `———` as visual separator  

---

## 4. STRATEGYCARD COMPONENT SPEC

### 4.1 Anatomy

Full card height: ~320px desktop, auto on mobile.  
Card width: fills grid column.  
Background: `--color-bg-card` (#1a1a1a)  
Border: 1px solid `--color-border` (#2a2a2a)  
Border-radius: 10px  
Padding: 24px  

```
┌─────────────────────────────────────┐  ← border, border-radius
│ [STATUS BADGE]           [RISK BADGE]│  ← Row 1: badges
│                                     │
│ Strategy Name                       │  ← Row 2: name
│ One-liner description               │  ← Row 3: subtitle
│                                     │
│ ─────────────────────────────────── │  ← divider
│                                     │
│ Target APY          Risk Level      │  ← Row 4: primary metrics
│ ~6%*                Lower           │
│                                     │
│ ─────────────────────────────────── │
│                                     │
│ Protocol tier: Tier 1 only          │  ← Row 5: feature list
│ Max allocation cap: 40%             │
│ Auto-rebalance: Daily               │
│                                     │
│ ─────────────────────────────────── │
│                                     │
│ [  SELECT THIS PROFILE  ]           │  ← Row 6: CTA
└─────────────────────────────────────┘
```

### 4.2 Element Hierarchy & Styling

#### Status Badge (top-left)

```
PAPER TRACKED       → --badge-paper-tracked-*
TARGET PROFILE      → --badge-target-profile-*
COMING SOON         → --badge-coming-soon-*
LIVE                → --badge-live-* + pulsing dot
```

Badge shape: pill (border-radius: 100px), padding 3px 10px.  
Font: 11px, weight 600, letter-spacing 0.06em.  
No icon for most states; LIVE gets `●` pulsing dot (CSS animation, 2s ease infinite).

#### Risk Badge (top-right)

```
Lower     → --color-risk-low + bg + border
Medium    → --color-risk-medium + bg + border
Higher    → --color-risk-high + bg + border
```

Same pill shape as status badge. Includes small square icon at left:

```css
/* Lower: green square */
/* Medium: blue-filled square */
/* Higher: orange-filled square */
```

**Risk icon pattern:** 3 horizontal bars where fill indicates risk:
```
Lower:  [■ □ □]  — 1 of 3 bars filled
Medium: [■ ■ □]  — 2 of 3 bars filled
Higher: [■ ■ ■]  — 3 bars filled
```
Use SVG icons, 12×8px, same color as badge text.

#### Strategy Name

Font: 18px, weight 700, `--color-text-primary`  
Margin-top: 16px from badges  

#### Subtitle

Font: 13px, `--color-text-secondary`  
Margin-top: 4px  
Max 2 lines  

Examples:
- Preserve: "Capital preservation focus. T1 protocols only."
- Core: "Balanced yield and risk. T1 + selective T2."
- Max Yield: "Aggressive yield via looping strategies. T2 + leverage."

#### Divider

`border-top: 1px solid --color-border-subtle`  
Margin: 20px 0  

#### Primary Metrics Row

Two metrics side by side:

**Left — Target APY:**
```
Label:  "Target APY"   11px, --font-card-label, uppercase, muted
Value:  "~6%"          --font-card-apy (32px), bold, tabular-nums
        color: --color-apy-green
Note:   "*variable"    10px, --color-text-muted, directly under value
```

For "TARGET PROFILE" and "COMING SOON" states:
```
Value shows "~6%"
Under value, italic note: "Target profile · not yet tracked"
Color: --color-text-muted (not green) until paper tracking confirmed
```

**Right — Risk Level:**
```
Label:  "Risk Level"   same as APY label
Value:  "Lower"        20px, bold
        color: --color-risk-low (adapts per strategy)
```

#### Feature List (condensed)

3–4 bullet rows, 13px, `--color-text-secondary`.  
Left: small checkmark icon `✓` in `--color-text-muted`.  
Line height: 1.8.  
No bold anywhere in feature list.

Preserve:
```
✓  Tier 1 protocols only (Aave V3, Compound V3, Morpho)
✓  Maximum 40% per-protocol
✓  Daily rebalance cycle
✓  Minimum 5% cash buffer
```

Core (current paper):
```
✓  Tier 1 + selective Tier 2
✓  Paper tracked · 9 days data
✓  Daily rebalance cycle
✓  GoLive target: Aug 1, 2026
```

Max Yield:
```
✗  Not yet available
·  Looping strategies (S8, S9, S10)
·  Strategy design complete
·  Launch pending Core go-live
```
(For Max Yield: `✗` in muted instead of check; items 2–4 use `·` dot)

#### Card CTA

**State: PAPER TRACKED (Core)**
```
[ VIEW LIVE DASHBOARD ]   ← primary, white fill, dark text
[ Methodology → ]         ← text link below button
```

**State: TARGET PROFILE (Preserve)**
```
[ JOIN WAITLIST ]         ← primary, filled
[ Learn about Preserve → ]← text link
```

**State: COMING SOON (Max Yield)**
```
[ NOTIFY ME ON LAUNCH ]   ← secondary (outline), grayed
  (no secondary text link)
```

Button: full width, 12px 0 padding, 6px border-radius.

### 4.3 States

#### 4.3.1 — PAPER TRACKED

The **Core** card in current state:

- Top bar: 3px solid `--color-apy-green` at top edge of card (like a bookmark ribbon)
- Status badge: `PAPER TRACKED`
- APY label changed to: `"Paper APY (current)"`
- APY value in `--color-apy-green`
- Feature list shows real tracked days count
- Small banner below metrics: `"9 days · $100K virtual · see dashboard →"`

#### 4.3.2 — TARGET PROFILE

Used for Preserve strategy (defined but not yet paper-tracking independently):

- No top bar
- Status badge: `TARGET PROFILE` in indigo
- APY value: displayed but in `--color-text-muted` (not green)
- Below APY: italic `"Target, not yet verified"`
- CTA: "Join Waitlist"

#### 4.3.3 — COMING SOON

Used for Max Yield:

- Entire card slightly desaturated: apply `filter: saturate(0.4)` to card interior (not border)
- Status badge: `COMING SOON` in zinc
- APY field shows `"TBD"` in muted
- Risk badge visible, Higher, but also muted
- CTA: outline button, disabled cursor (pointer-events: none if no action attached)
- Tooltip on hover: `"Max Yield launches after Core go-live · Target: Aug 2026"`

#### 4.3.4 — LIVE (future state, design it now)

- Top bar: 3px pulsing green at top edge (CSS animation: opacity 0.6→1 over 2s)
- Status badge: `● LIVE` with pulsing dot
- APY updates to actual live APY (not "paper")
- Below APY: `"Live · actual capital deployed"`
- Feature list shows real days live
- CTA: `[ ALLOCATE CAPITAL ]` ← primary, filled

### 4.4 Hover & Active States

```css
.strategy-card {
  transition: border-color 200ms ease,
              box-shadow 200ms ease,
              transform 100ms ease;
}

.strategy-card:hover {
  border-color: var(--card-hover-border);  /* #3a3a3a */
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  transform: translateY(-2px);
}

/* Selected state (if card is chosen) */
.strategy-card[data-selected="true"] {
  border-color: var(--card-selected-border);
  box-shadow: var(--card-selected-glow);
}

/* Coming soon: no hover lift */
.strategy-card[data-status="coming-soon"]:hover {
  transform: none;
  border-color: var(--color-border);
}
```

### 4.5 Mobile Responsive

On `<768px`:
- Cards go full width, stacked vertically
- Risk gradient strip HIDDEN (redundant on mobile)
- Risk badges remain visible
- APY font-size: reduce to 24px
- Feature list: reduce to 3 items max (hide 4th)
- Status badge + risk badge: both on same row, space-between
- CTA button: full width

On `768–1024px` (tablet):
- 3-column layout preserved but with tighter padding (16px card)
- Font sizes stay same
- Feature list: 3 items

---

## 5. /TRUST PAGE SPEC

URL: `earn-defi.com/trust`  
Purpose: Answer every material question an allocator has before deploying capital.  
Tone: Professional, factual, occasionally direct. Not defensive. Not marketing.

**Meta:** `<title>Trust & Transparency — SPA by earn-defi.com</title>`

---

### 5.0 Page-level design

Background: `--color-bg` (same as main)  
Left nav sidebar (desktop): sticky TOC linking to each section  
Max content width: 860px (narrower than main — this is a reading document)  
No decorative elements, no hero image — document aesthetic  

---

### 5.1 Page Header

```
TRUST & TRANSPARENCY
────────────────────────────────────────────────────────

SPA is built for allocators who verify everything.
This page answers the 9 questions we'd ask if we were evaluating SPA.
Last reviewed: June 19, 2026.
```

— The "9 questions" framing immediately orients the reader  
— Last reviewed date is important — builds recency trust  

---

### 5.2 Nine Mandatory Questions

Each question is a collapsible section (open by default on desktop, collapsed on mobile):

**Design of each question block:**
```
┌──────────────────────────────────────────────────┐
│  Q3.                                             │
│  Who controls the allocation weights?            │
│                                                  │
│  [Answer prose 2–4 paragraphs]                   │
│                                                  │
│  [ Verify on-chain → ] or [ Read policy → ]      │
└──────────────────────────────────────────────────┘
```

— Question number: 40px, bold, `--color-text-muted`  
— Question text: 22px, `--color-text-primary`  
— Answer: 15px, `--color-text-secondary`, line-height 1.75  
— CTA link: `--color-apy-green` text, no underline, `→` arrow  

---

**Q1 — Who controls the allocation weights?**

Answer:  
The allocation weights are determined entirely by `StrategyAllocator` (v1.x), a deterministic Python module that applies `RiskPolicy v1.0` rules to live protocol data. No human, no AI, no LLM, no discretionary override can change allocation weights in real time.

The only way to change how allocations are made is to:
1. Author a new ADR (Architectural Decision Record) with full rationale
2. Snapshot the new policy version in `spa_core/risk/versions/`
3. Deploy a new version of the system

Policy version v1.0 is locked for the entire paper trading period.

`[ Read RiskPolicy v1.0 → ]` · `[ View ADR log → ]`

---

**Q2 — Can you manually override a trade?**

Answer:  
No. There is no UI, API, or CLI command that allows manual trade execution in paper mode. `RiskPolicy.approved = False` cannot be overridden by any agent, including the operator.

The only administrative actions available to the operator are:
- Starting/stopping the daily cycle
- Emergency exit trigger (which closes all positions to 100% cash)

Manual trades are explicitly prohibited by system design to prevent discretionary bias in the paper track record.

`[ View emergency procedures → /emergency-withdrawal ]`

---

**Q3 — What happens if a protocol gets hacked?**

Answer:  
SPA does not currently integrate real-time exploit detection. The primary protection mechanism is the TVL floor: if protocol TVL drops rapidly below $5M (consistent with a hack drain), the protocol fails the `tvl_floor` check and SPA cannot allocate to it on the next cycle.

Additionally, the 5% portfolio drawdown kill-switch would trigger if a hack causes mark-to-market losses exceeding 5% of total portfolio value, moving all positions to cash.

This is a known limitation of the current paper period design. A dedicated oracle-based anomaly detection module is on the roadmap.

`[ View kill-switch parameters → ]`

---

**Q4 — Who audited the smart contracts SPA interacts with?**

Answer:  
SPA does not deploy or control any smart contracts. It interacts exclusively with existing, production DeFi protocols. Each whitelisted protocol in the T1 registry has undergone independent third-party security audits.

Audit references by protocol:
- **Aave V3:** [audit reports at aave.com/security]
- **Compound V3:** [audit reports at compound.finance/security]
- **Morpho Steakhouse:** [audit references at morpho.org]

SPA's own code (Python, stdlib only) does not execute on-chain and therefore has no smart contract attack surface during paper mode.

`[ View adapter registry → ]` · `[ View whitelisted protocols → ]`

---

**Q5 — How can I verify the track record is real?**

Answer:  
The paper track record is maintained in `data/trades.json` and `data/equity_curve_daily.json`, published to GitHub on each cycle run. Each record includes:
- ISO 8601 timestamp
- `is_demo: false` flag (confirmed real-cycle, not test data)
- Protocol name, position delta, rationale code
- Cycle sequence number for gap detection

`data/gap_monitor.json` tracks continuity — any missing day is flagged and pushes the go-live date back.

The track record starts June 10, 2026. All data before that date is marked as demo/invalid.

`[ View GitHub repository → ]` · `[ View trade log → ]`

---

**Q6 — What are the fees?**

Answer:  
During paper trading: **zero fees**. No management fee, no performance fee.

Fee structure for live deployment will be published no later than 2 weeks before the go-live date (target: August 1, 2026). The structure will follow industry norms for DeFi managed accounts.

There is no exit fee. The emergency withdrawal mechanism is always available at no cost.

`[ Fee methodology (coming) → /fees ]`

---

**Q7 — What is the minimum allocation?**

Answer:  
Paper period: No minimum — the virtual portfolio represents $100,000 USDC.

Live deployment: Minimum allocation is $25,000 USDC. Maximum per-participant allocation in the initial cohort has not yet been set.

Onboarding requires completion of a brief questionnaire and KYC/AML verification process (details TBD for live phase).

---

**Q8 — How do I exit?**

Answer:  
Two exit mechanisms exist:

**Normal exit:** Submit exit request via the investor portal. Target execution: next daily cycle (within 24 hours). All positions liquidated to USDC, which is returned to the specified withdrawal address.

**Emergency exit:** Available at any time, independent of the daily cycle. Triggers full liquidation to USDC. No fee. See `/emergency-withdrawal` for full procedure.

The 5% drawdown kill-switch is automatic — it does not require any action from the investor.

`[ Emergency withdrawal procedure → /emergency-withdrawal ]`

---

**Q9 — What jurisdiction governs this?**

Answer:  
SPA is currently in paper trading mode and does not involve real capital. The legal framework for live deployment is being finalized and will be published before go-live.

Target structure: [TBD — entity jurisdiction]. Investor agreements will be made available no later than 4 weeks before go-live.

All investor-facing legal documents are stored in `docs/legal/` and shared with participants via the onboarding process.

---

### 5.3 Operator Information Block

```
ABOUT THE OPERATOR
──────────────────────────────────────────────────

SPA is operated by [entity TBD]. Contact: [email]
GitHub: [repo link] — read-only public access to trade logs and system code.

Telegram updates for registered participants: [channel link]

For due diligence requests, contact: [email]
```

---

### 5.4 /trust Page Footer

Same footer as main page, no changes.

---

## 6. /SECURITY & /EMERGENCY-WITHDRAWAL STUBS

These pages exist as reference documents. Design is functional (document-style), not marketing.

### /security

**Sections:**
1. Code security model (stdlib only, no external dependencies, no cloud calls)
2. Key management (PAT rotation, Keychain storage — never in files)
3. Secrets policy (describe incident/lesson of June 10, 2026 — transparency)
4. LLM exclusion from risk/execution components
5. Audit approach (what SPA has been reviewed for)

### /emergency-withdrawal

**Sections:**
1. How to trigger emergency exit (step by step)
2. What happens: all positions → USDC, within [X] hours
3. Automatic trigger: 5% drawdown kill-switch
4. Contact protocol if system is unresponsive
5. Estimated timeline for settlement

Each section: plain prose, numbered steps where applicable, no marketing language.

---

## 7. MOBILE UX

### 7.1 Sticky CTA — Bottom Bar

Appears after user scrolls past hero section (JS `IntersectionObserver` on hero CTA button).  
Disappears when user reaches Risk Warning footer section.

```
┌───────────────────────────────────────────────────┐
│  SPA · earn-defi.com            [Choose Strategy] │
└───────────────────────────────────────────────────┘
```

— Height: 56px  
— Background: `--color-bg-raised` + `backdrop-filter: blur(12px)`  
— Border-top: 1px solid `--color-border`  
— Left: site name, 13px, muted  
— Right: primary CTA button  
— Button: white fill, dark text, 10px 20px padding  
— `position: fixed; bottom: 0; left: 0; right: 0; z-index: 100`  
— Transition: `transform 300ms ease` (slides up from below)

**Behavior states:**
- Hidden (default / above hero)
- Visible (after hero leaves viewport)
- Hidden again (when footer enters viewport)
- NOT shown: on desktop (≥1024px), only mobile/tablet

### 7.2 Strategy Cards on Mobile

Single column, full viewport width minus padding:

```
Card width: 100%
Padding: 20px
Gap between cards: 16px

Scroll direction: vertical (natural document flow)
NOT a horizontal carousel — allocators need to compare, not swipe

Cards order: Preserve → Core → Max Yield (top to bottom)
Risk direction note above cards: hidden on mobile
Risk badge on each card: sufficient orientation signal
```

Swipe gesture: none (avoid ambiguity with page scroll)

### 7.3 Breakpoint Summary

```
<480px   — mobile small  — 1 col, reduced typography, single CTA
480–768px — mobile large  — 1 col, standard typography
768–1024px — tablet       — 3-col cards, full nav
1024px+  — desktop       — full layout
```

### 7.4 Touch Targets

All interactive elements: minimum 44×44px touch target.  
Card CTAs: full width on mobile = naturally satisfied.  
Navigation links: 48px height.  

---

## 8. COPYWRITING RULES

### 8.1 Banned Words (absolute)

| Banned | Replacement |
|---|---|
| safe | lower-risk, T1-only |
| guaranteed | target, variable |
| protected | risk-gated |
| risk-free | (no equivalent — just don't imply it) |
| secure yield | audited protocols |
| passive income | managed yield |
| earn while you sleep | automated yield management |

### 8.2 Required Qualifiers

Every APY figure MUST have one of:
- `*` + footnote `"variable, not guaranteed"`
- `(target)` inline qualifier
- `(paper)` if from paper track record

Never: standalone `"6% APY"` without qualifier.

### 8.3 Paper vs Live Language

| Context | Correct | Wrong |
|---|---|---|
| Track record section | "Paper APY" | "Our APY" |
| Strategy description | "Target APY" or "~6%*" | "We return 6%" |
| Dashboard link | "View paper dashboard" | "View our performance" |

### 8.4 Tone Reference

**Do:**
- "SPA has executed 12 rebalances over 9 paper-tracked days"
- "If protocol TVL drops below $5M, SPA stops allocating to it"
- "No allocation decision can be overridden — not by us, not by anyone"

**Don't:**
- "Our proprietary algorithm maximizes your yield"
- "Sit back and watch your money grow"
- "We protect your capital"

---

## 9. IMPLEMENTATION NOTES

### 9.1 Astro 4 File Structure

```
src/
  pages/
    index.astro          ← main page
    trust.astro          ← /trust
    security.astro       ← /security
    emergency-withdrawal.astro
    risk.astro
    fees.astro
  components/
    StrategyCard.astro   ← strategy card component
    RiskGatesTable.astro ← risk gates snapshot
    PaperBanner.astro    ← paper context banner (reusable)
    StickyCTA.astro      ← mobile sticky CTA
    SparklineChart.astro ← equity curve mini-chart
    StatusBadge.astro    ← status/risk badge primitives
  layouts/
    BaseLayout.astro
  styles/
    tokens.css           ← all CSS custom properties
    global.css
  data/
    strategies.json      ← strategy definitions (name, APY, risk, status)
    risk_gates.json      ← risk policy parameters for display
```

### 9.2 Data Flow

- `strategies.json` — static, updated manually when strategy status changes
- `risk_gates.json` — built from `data/risk_policy_blocks.json` at build time
- Paper track record metrics — fetched from GitHub raw URL at build time (Astro static fetch)
- No runtime API calls from the browser — pure SSG

### 9.3 Performance Budget

- First Contentful Paint: < 1.2s
- Time to Interactive: < 2.0s
- Total JS bundle: < 30KB (sticky CTA, sparkline only)
- No external fonts (use system font stack)
- Strategy cards: rendered server-side via Astro, no hydration needed
- Sparkline: lazy-loaded with `loading="lazy"` equivalent

### 9.4 System Font Stack

```css
--font-sans: ui-sans-serif, system-ui, -apple-system,
             BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-mono: ui-monospace, "Cascadia Code", "SF Mono",
             Menlo, Consolas, monospace;
```

No Google Fonts, no CDN font dependencies — privacy and performance.

### 9.5 Open Questions / Decisions Needed

| # | Question | Owner | Notes |
|---|---|---|---|
| OQ-1 | Calendly vs email form for "Schedule a Call" CTA | Product | Prefer email for lower friction |
| OQ-2 | Which GitHub repo to link to (public?) | Operator | Public = trust signal |
| OQ-3 | Waitlist mechanism for Preserve strategy | Product | Simple email form → Notion? |
| OQ-4 | Legal entity name for /trust operator block | Legal | TBD before go-live |
| OQ-5 | Actual go-live fee structure | Finance | Publish 2 weeks before go-live |
| OQ-6 | /fees page content | Product | Stub now, fill before go-live |
| OQ-7 | Telegram channel for Preserve waitlist | Ops | Separate from Core participants? |

---

*Design Spec v2.0 — SPA / earn-defi.com*  
*Prepared: 2026-06-19*  
*Next review: on go-live milestone (target 2026-08-01)*
