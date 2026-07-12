# PRODUCT & UX REDESIGN ROADMAP — H2 2026 → H1 2027

> **Owner directive (2026-07-12):** stop shipping small fixes; make earn-defi.com + DeFi Checkup a
> **Tier-1 product**. Move off "everything crammed into a narrow column on one long page" to a
> **modern dashboard-shell** (DeBank/Zapper/Zerion class). Make **Checkup the selling/conversion
> layer** for the yield strategies — so a non-technical USDT holder with no wallet still wants to
> **contact us**. Board → Checkup is a separate later project (legal-gated). This doc is the
> 6–12 month backlog: research → phased plan → definition of done.
>
> **Source research (2026-07-12, 3 parallel agents):** modern DeFi-dashboard UX teardown ·
> Checkup-as-conversion-layer strategy · current-site UX audit. Findings summarized inline; the
> per-item backlog below is the consolidated, prioritized output.

---

## 0. The core finding (evidence-backed)

The owner's complaint is **100% accurate**. Audit of the code:
- **SPA landing:** 36 public pages, **34/36 render in a `max-w-3xl…5xl` centered column** (48–64rem) — on a 1920px screen that's a ~640–960px column with huge dead margins. `Layout.astro` is header→body→footer stack; **no page has a sidebar / 12-col grid / dashboard-shell.**
- **Dashboards are long-scroll, not glanceable:** `/dashboard` (6-tab vertical stack), `/cockpit` ("5 questions" sequential sections), Checkup report (820px reading column of stacked cards).
- **No shared component kit:** cards/tables/badges are ad-hoc inline styles; `SITE_DESIGN_SYSTEM.md` exists as SPEC-only ("not yet built"); two CSS systems (Astro Tailwind vs Checkup globals) drift.

**The fix is a structural mode-switch, not "make it prettier":**
- **Marketing pages stay single-column** (correct for landing / track-record / research long-form).
- **App surfaces** (`/dashboard`, `/monitoring`, `/aggressive-lab`, `/packages`, `/admin`, Checkup report) move to a **persistent sidebar + sticky topbar + 12-col grid + KPI strip + grouped sortable tables + detail drawers.**

**The modern pattern (what DeBank/Zapper/Zerion/DeFiLlama/De.Fi all share):**
sidebar 256/64px · sticky topbar (search, context, time-range, last-updated) · fluid `max-w-[1440px]`
12-col/24px grid · KPI stat-card strip (28–32px numbers, arrow+color deltas) · **data as sticky
sortable tables** (left-align text / right-align monospace / center badges), grouped/collapsible ·
filter chips + tabs instead of sub-pages · **row-click → side-drawer**, not a new page · dark
financial tokens (near-black elevated surfaces, one accent, P&L-only green/red, tabular-nums).

---

## 1. Four workstreams

| # | Workstream | Goal | Owner-gated? |
|---|---|---|---|
| **A** | **Design-system + component kit** | One shared language (StatCard/DataTable/FilterChips/Drawer/Tabs/Shell) across both repos | No |
| **B** | **Dashboard-shell redesign** | App surfaces → modern shell (DeBank class) | No |
| **C** | **Checkup conversion layer** | Convert wallet-scanners AND no-wallet USDT holders → `/pilot` contact | Copy/legal = flag |
| **D** | **Board → Checkup migration** | DFB risk-screener becomes a Checkup feature | **Yes** (legal + product, LATER) |

Honesty is a hard constraint on **all** of C (see §6): non-custodial, paper-stage, "not an offer,"
never present ~3.3% as live/guaranteed, never solicit an unregistered fund.

---

## 2. Phased plan

### Phase 0 — Foundation (now, ~2–4 wks) · prove the pattern on ONE surface
- **A1** Build shared **component kit**: `StatCard`, `DataTable` (sortable/sticky/dense), `FilterChips`, `Drawer` (slide-over), `Tabs`, `SectionHeader`, `Badge`. Document in `SITE_DESIGN_SYSTEM.md` (move from SPEC → built). `[P0][M]`
- **A2** Consolidate **design tokens** (color/spacing/type/radius/shadow) into one source; sync Astro ↔ Checkup; kill the 5 near-black backgrounds + 5 header treatments. `[P0][M]`
- **B1** Build **`DashboardShell`** layout (256/64px collapsible sidebar + sticky topbar + fluid `max-w-[1440px]` 12-col grid). `[P0][M]`
- **B2** Rebuild **`/dashboard`** on the shell: KPI strip (Net Equity / APY+evidence / Drawdown+Kill-tier / Track N-30 / Cash Buffer / Positions) + hero equity chart with 24h/7d/30d/1y/all toggle + allocation donut + **DeBank-style protocol-grouped sortable positions table** + right context rail (RTMR/funding/refusals). `[P0][L]`
- **Gate:** `/dashboard` proves the shell before rolling out. Ship, measure, then scale.

### Phase 1 — Conversion layer (Q3 2026) · the money path
- **C1** Checkup: persistent **"No wallet to scan? →"** door on home + result, routing to the no-wallet path. `[P0][S]`
- **C2** Build **Stablecoin Safety Snapshot** — 3–4 tap micro-quiz (holdings band / where / which stables / goal) → ungated, personalized-feeling result (no PII to see it). `[P0][M]`
- **C3** Ensure **first report never gated** by email/login (protect value-first aha). `[P0][S]`
- **C4** Rewrite `/pilot`: "real person reaches out, no obligation, not an offer," + source + holdings-band fields (already has the form + Telegram from 2026-07-12). `[P0][S]`
- **C5** End every report (scan + snapshot) with a **"what to do about this" next-step panel** naming the un-fixable gap → bridges to the SPA approach (no promised returns). `[P1][M]`
- **C6** Build **"How we think about stablecoin yield (honestly)"** bridge page: approach + real ~3.3% paper state + non-custodial + public track-record link. `[P1][M]`
- **C7** **Dual-CTA** everywhere (self-serve result **+** "talk to a human"). `[P1][S]`
- **C8** **Trust-signal band** (non-custodial / honest-first / public track record / "we show the bad news") on both entry doors. `[P1][S]`
- **C9** **Nurture sequence** (thank-you → risks explained → honest track update → walkthrough) — education-led, no return promises. Reuses Q-OWN-07 email infra. `[P1][M]` *(infra owner-gated)*
- **C10** Reusable **"not financial advice / not an offer / not accepting external capital yet"** disclaimer component on every conversion surface. `[P0][S]`

### Phase 2 — Roll out the shell (Q4 2026)
- **B3** Convert `/monitoring`, `/aggressive-lab`, `/packages`, `/admin` onto `DashboardShell`. `[P1][L]`
- **B4** Row-click **slide-over detail drawer** (position/strategy/pool) replacing scroll-to-section. `[P1][M]`
- **B5** **Filter-chip + sortable sticky table** for every long list (35 adapters, 60 strategies, tournament) with per-row sparklines (DeFiLlama pattern). `[P1][M]`
- **B6** **Rebuild Checkup report** (`ReportDashboard.tsx`): tabbed panels (Overview / Approvals / Positions / Risk / History) + top KPI strip (Wallet Health Score à la De.Fi) + TanStack sortable tables + detail drawer; condense the 400px hero to ~120px. `[P1][L]`
- **B7** **"Risk Health" scorecard** as a first-class dashboard citizen (kill-tier / drawdown / evidence-mix / refusals) — De.Fi Shield analog. `[P1][S]`
- **B8** Sticky **quick-access metric bar** (NAV / APY / equity / kill-switch) across app surfaces. `[P1][S]`
- **B9** Dark-mode financial token pass + tabular-nums + a11y (arrows/patterns, not color-only). `[P2][S]`
- **B10** Responsive shell (sidebar → icons → mobile bottom bar; tables → accordion + FAB). `[P2][M]`

### Phase 3 — Selling layer + pro features (H1 2027, several owner-gated)
- **D1** **Board → Checkup migration**: port 5 DFB pages (Astro → Next.js) + rewire data; position as Checkup "Risk Screener" (pick a safe pool *before* entry). **Owner + legal-gated, separate project.** `[gated][L]`
- **C11** Checkup as **yield selling layer**: the "USDT holder → contact → owner decides offer" funnel, once legal clears the managed/advisory layer. **Owner + legal-gated.** `[gated][L]`
- **B11** Composable **widget-grid / saved-views** for `/admin` + Checkup-pro (Nansen/Arkham pattern). `[P2][L]`
- **C12** Funnel analytics: door (scan vs snapshot) → bridge → `/pilot`, segmented by holdings band (owner needs to know *who's big*). `[P2][M]`
- **C13** EN|RU parity on the whole no-wallet path (RU stablecoin holders = core segment). `[P2][S]`

---

## 3. Named references (for the build)
DeBank (protocol-grouped position table) · Zerion (top perf-chart + time-range toggle) · Zapper
(3-col shell + right context rail) · DeFiLlama (KPI strip + dense sortable/filter tables) · De.Fi
Shield (health-score as first-class surface) · Nansen/Arkham (widget dashboards, saved views) ·
**shadcn/ui + TanStack Table** (concrete primitives for the Next.js report) · Tremor (KPI/chart kit reference).

Conversion refs: DeBank (value-first, no gate) · Nansen (real-free-with-visible-ceiling) · Webacy
(outcome framing + dual CTA) · Harpie/De.Fi (free security scan = credibility) · fintech waitlist
playbook (security-first, non-monetary referral, ~42% lift from personalized CTAs).

---

## 4. Definition of Done (Tier-1 bar)
- App surfaces use the **shell** (sidebar + sticky topbar + 12-col grid), not a narrow column.
- Financial data renders as **sortable sticky tables with tabular-nums**, not stacked prose cards.
- **One documented component kit + token set**, shared across both repos; zero ad-hoc near-black/header drift.
- Checkup converts **both** doors (wallet + no-wallet) onto a single honest `/pilot` path with a dual CTA.
- **Every number carries an evidence level + honesty framing**; nothing reads as a live offer or solicitation.
- Responsive + a11y (color-not-only, keyboard nav, sticky-header tables) pass.
- A hostile reviewer opening `/dashboard` or a Checkup report says "this looks like DeBank," not "this is a long blog page."

## 5. Sequencing logic
Foundation first (**A + B1/B2**) — a shared kit + one proven shell surface de-risks everything after.
Then the **conversion layer (C)** — highest business value, and it can proceed in parallel once the
component kit exists. Roll the shell to the rest (**B3–B10**) in Q4. Board migration + the true
selling layer (**D, C11**) are **last and owner/legal-gated** — do not start them until the legal
questions on managed capital are answered.

## 6. Honesty guardrails (HARD — apply to all of C)
Non-custodial everywhere (never ask for keys/seeds/transfers). Paper-stage, **not** taking external
capital — state it plainly. Never present ~3.3% as live/offered/guaranteed; always label
realized-in-paper / research-stage with a last-verified date. **Never** "invest / deposit / returns /
APY you'll earn / join the fund / allocate." The only ask is **"contact us / get a walkthrough /
follow our progress."** No fabricated risk/APY/depeg numbers — cite real data or say unknown. No
false urgency. Personalization educates on *risk & approach*, never a tailored allocation. The
managed/advisory layer stays an off-page, human, legally-gated conversation the owner initiates.

---

*Created 2026-07-12 from 3 parallel research agents. This is the authoritative product/UX backlog;
individual sprint items are drawn from here. Owner-gated items (D1, C11, and C9/C12 infra) are
flagged and must not be started without sign-off.*
