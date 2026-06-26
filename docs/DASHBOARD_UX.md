# SPA — Dashboard UX Design (Console, honest live mirror)

> **Status:** DESIGN SPEC (read-only / not yet built). Owner reviews before any rebuild.
> **Author:** Senior UX Designer (visual/UX half). Pairs with the Architect's data-flow doc
> (the wiring half) — this doc owns layout, hierarchy, honesty-in-the-UI, and mockups.
> **Coherence target:** `docs/SITE_DESIGN_SYSTEM.md` — same Console tokens, same worldview as
> earn-defi.com and the Telegram bot. One product, three surfaces, one voice.
> **Scope:** the live dashboard (`/app`) + the question of `investor_portal.html`.
> **Honesty rule (non-negotiable):** paper/advisory labels on every number, a visible freshness
> indicator, no fabricated fallbacks, the real 5/30 reset story shown — never the old padded 15.

---

## 0. TL;DR

The owner is right: the dashboard is **a separate world**. It has its own light-theme leftovers,
its own brand name ("Stable Portfolio Agent" — a name we retired everywhere else), **12+ hidden
tabs**, **30+ raw JSON fetches** with no shared freshness model, and zero shared chrome with
earn-defi.com. It reads like an internal debug console, not the public live mirror of an
honesty-first research project.

**The fix:** one Console-tokened single-page dashboard, on the same header/footer/paper-strip as
the site, organized around the **honest headline first** (track 5/30 · equity · go-live 27/29),
then six purposeful sections (Portfolio · Go-Live · Strategies/Structural-Desk · Health ·
Refusal/Honesty · Reports). One global freshness indicator. Every number carries a `paper` /
`advisory` / `live`-vs-`stale` label. The 12 debug tabs collapse into one scroll + a small
"Ops (advanced)" drawer. `investor_portal.html` is **retired** — it is a stale, divergent copy of
the same data for an audience (external investors) that does not exist yet (we are not raising
capital). One dashboard.

---

## 1. CURRENT-STATE AUDIT (what makes it "a separate world")

Evidence from `index.html` (the github.io dashboard), `landing/public/app.html` (the `/app` copy),
and `investor_portal.html`.

### 1.1 Off-brand identity
- `<title>SPA — Stable Portfolio Agent</title>` and `<h1>Stable Portfolio Agent — SPA</h1>`.
  The site design system **retired** "Stable Portfolio Agent" (one of 4 conflicting expansions);
  user-facing surfaces should show just **SPA** + "systematic onchain stablecoin yield."
- `investor_portal.html` shows a third name: **"SPA Investor Portal"** and a `DEMO`/`LIVE` badge
  vocabulary that exists nowhere else.

### 1.2 Two/three CSS worlds, none of them the Console
- `index.html` still carries **light-theme leftovers**: `h1 { color:#1a1a1a }`, kanban columns in
  pastels (`#EFEDE6`, `#E2EDF7`, `#F5ECD8`), tag chips in 8 hand-picked light colors. A dark body
  was bolted on top (`--spa-bg:#0b0c10`) but the inner widgets never got retoned.
- `investor_portal.html` uses the **GitHub palette** (`--bg:#0d1117 --accent:#58a6ff
  --purple:#bc8cff`) — none of which are Console tokens. It even reintroduces the retired purple.
- None of the three use the design-system tokens (`--bg-base:#0A0C10`, `--accent:#5B8DEF`,
  `--data-teal:#36C2B4`, semantic `--ok/--warn/--danger`). Result: three near-blacks, three accents.

### 1.3 Tab sprawl / debug-console feel
- `index.html` has **15 tab buttons**, of which ~8 are `style="display:none"` (analytics, system,
  ops, decisions, backlog, team…). It is an internal kanban/agent console wearing a dashboard hat.
  A public mirror should not lead with **Kanban, Decisions, Team** tabs.
- Tabs visible: Performance · Strategies · Backtest · Protocols · Risk · Dashboard · GoLive ·
  Evidence · Tournament. No clear primary read; the honest headline (5/30, equity, go-live) is not
  the first thing you see.

### 1.4 No coherent freshness / honesty model
- **30+ independent `fetch()` calls**, each with its own `?_=ts` cache-bust, no single
  "as-of / live / N h stale" indicator. Different panels can silently show data from different
  cycles. The user cannot tell what is live vs. cached vs. a static fallback.
- `investor_portal.html` *does* have a staleness banner (>24h) and a no-data banner — good
  instincts — but it is isolated to that orphan file and uses non-Console styling.
- Honesty labels are inconsistent: a `DEMO` badge here, an `is_demo` flag there, no consistent
  `paper` / `advisory` chip taxonomy matching the bot and the site.

### 1.5 The 3-frontend / "separate world" problem (confirmed)
- `index.html` (github.io root) and `landing/public/app.html` are **near-identical 13.3k-line
  twins** that must be hand-kept in sync — they already drift.
- `investor_portal.html` is a **fourth** divergent view of the same numbers for an audience that
  does not exist (not raising capital), reading from its own `investor_portal_data.json`.
- Net: 4 files, 3 palettes, 3 brand names, no shared chrome with earn-defi.com.

### 1.6 It doesn't mirror the *worldview*
The real product has a strong, honest worldview the dashboard fails to express:
- the **5/30 honest reset** (everything pre-2026-06-10 is demo and void; the 37 snapshots are
  shown honestly as **5 real track-days**, not 15 padded ones);
- the **structural-desk verdicts** (Rates Desk **GO** / RWA Repo Backstop **measurement-GO / book
  NO-GO** / Liquidator **NO-GO**) — a system that says *no* on the record;
- the **refusal log** (the rates desk refuses toxic books) and **data-quality honesty** (tier1
  ranking marked `DEGENERATE / not trustworthy` because it ran on mock data).
None of this is surfaced. The dashboard shows widgets; the product has a thesis. The dashboard
should *be* the thesis, live.

---

## 2. PRINCIPLES (the dashboard's job)

1. **One coherent product.** Same Console tokens, header, footer, paper-strip, and voice as
   earn-defi.com and the Telegram bot. The dashboard is the `/system` → `/app` surface of the same
   site, not a separate app.
2. **Honest headline first.** The top of the page answers the only three questions that matter:
   *How honest is the track? (5/30) · What's the equity? · Are we go-live? (27/29)* — before any
   widget.
3. **Every number is labeled.** A small chip on every metric: `paper`, `advisory`, `live`, or
   `stale`. No bare numbers. No fabricated fallbacks — missing data renders as `—` with a reason.
4. **Freshness is global and visible.** One status line ties to the API freshness: `● live ·
   updated 14m ago` or `◐ stale · last cycle 27h ago` or `○ unavailable`. Per-panel chips inherit
   it when a panel is older than the page.
5. **Say no, on the record.** Refusals and NO-GO verdicts are first-class content, not buried.
   A system that publishes its own *no* is the trust proposition.
6. **Owner-grade, public-safe.** It is the owner's ops dashboard *and* the public live mirror — so
   no secrets, no kanban/team internals on the main view; advanced ops live in a labeled drawer.

---

## 3. COHERENCE-WITH-SITE RECOMMENDATION (resolve the 3 frontends)

**Recommendation: collapse to ONE dashboard.**

| File | Decision | Why |
|---|---|---|
| `index.html` (github.io) | **Retire as the product dashboard.** Keep only as a thin redirect to `/app` (or delete). | A 13k-line debug twin; off-brand; duplicates `/app`. |
| `landing/public/app.html` (`/app`) | **KEEP — this is the one canonical dashboard.** Rebuild on Console tokens + shared chrome per this doc. | It already lives inside the site at the canonical `/app` URL (`docs/SITE_DESIGN_SYSTEM.md §6`). |
| `investor_portal.html` | **Retire.** | Separate audience (external investors) that does not exist — we are **not raising capital**. A 4th divergent copy = drift + an honesty risk (an "investor portal" implies solicitation). |
| The kanban / decisions / team / agents internals | **Move to `/system` ops surfaces** (or an "Ops (advanced)" drawer on `/app`), not the main dashboard. | Internal operations ≠ the public live mirror. |

**Is `investor_portal` a separate audience view?** Not yet, and building it now contradicts the
positioning ("not raising capital"). The honest dashboard *is* the investor view — the public,
labeled, freshness-stamped track record. **If/when** SPA actually raises external AUM post-go-live,
re-introduce an audience view as a *filtered render of the same canonical dashboard + data* (same
tokens, same freshness model) — never a separate file with its own palette and numbers. Until then:
**one dashboard for everyone.**

So: **the dashboard becomes `/app`** — same `SiteHeader` / `PaperStrip` / `SiteFooter`, same tokens,
linked from the site's `/system` hub and the homepage "View live dashboard" CTA. The "separate
world" disappears because it is literally the same chrome and tokens as the rest of earn-defi.com.

---

## 4. LAYOUT — single-page, honest-headline-first

A single scroll (no hidden tabs) with the shared site chrome. Anchored section nav lets the owner
jump; everything is visible/printable in one page. Advanced ops behind one labeled drawer.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  SiteHeader  (shared)   SPA · earn-defi.com   Methodology Strategies …  EN|RU│
├──────────────────────────────────────────────────────────────────────────┤
│  PaperStrip (shared, amber): Personal research project — paper-testing, not  │
│  raising capital.                                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  FRESHNESS BAR (global, sticky):  ● live · cycle 2026-06-26 06:00 UTC ·      │
│                                    updated 14m ago · read-only simulation    │
├──────────────────────────────────────────────────────────────────────────┤
│  § HERO — the honest headline (3 numbers + verdict)                          │
│  § 1  PORTFOLIO        (equity curve, positions, allocation, daily yield)    │
│  § 2  GO-LIVE          (27/29 + the 2 time-gated blockers, ETA)              │
│  § 3  STRATEGIES /     (structural-desk verdicts: GO / measurement-GO / NO-GO│
│        STRUCTURAL DESK   + tournament w/ data-quality honesty)               │
│  § 4  HEALTH           (agents, system domains, cycle continuity)            │
│  § 5  REFUSAL & HONESTY(refusal log, advisory flags, data-quality caveats)   │
│  § 6  REPORTS          (latest daily / weekly digest, mirrors the bot)       │
│  [ ▸ Ops (advanced) ]  drawer: kanban, decisions, agent fleet, raw JSON      │
├──────────────────────────────────────────────────────────────────────────┤
│  SiteFooter (shared)                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

Section nav (sticky, under the freshness bar on desktop; mono eyebrow style):
`Overview · Portfolio · Go-Live · Strategies · Health · Honesty · Reports`.

---

## 5. HONESTY-IN-THE-UI — the label & freshness system

### 5.1 The label chip taxonomy (one set, shared with the bot)

A tiny mono pill rendered next to every metric/panel title. Exactly these, no others:

| Chip | Token | Meaning | Example |
|---|---|---|---|
| `paper` | `--warn` @ text, `--warn`@12% bg | simulated, no live capital | equity, daily yield, APY |
| `advisory` | `--text-muted` bg, `--text-secondary` text | simulate-only / not allocating live | structural-desk books, new strategies, refusal engine |
| `live` | `--ok` | sourced live from the API this page-load | freshness bar, current APY feed |
| `stale` | `--warn` | data older than its expected cadence | a panel whose cycle is > threshold |
| `unavailable` | `--danger`@text on `--bg-surface-2` | no data — render `—` + reason | structural_break (insufficient data) |
| `not trustworthy` | `--danger` outline | data present but flagged degenerate | tier1 tournament ranking (mock data) |

**Rules:**
- **No bare numbers.** Each metric value is followed by a chip or a one-line caption
  (`paper · variable · not guaranteed`).
- **No fabricated fallbacks.** If a fetch fails or a field is absent, show `—` and the reason
  (`unavailable — only 0 daily returns`). Never substitute a plausible-looking number.
- **The 5/30 reset is explicit.** Track days render as **`5 / 30 real track-days`** with a caption
  *"37 snapshots since reset; pre-2026-06-10 is demo and void."* Never show the 37 as the headline,
  never pad to 15.

### 5.2 The global freshness indicator (ties to API freshness)

A sticky bar directly under the paper-strip. Single source of truth for "how fresh is this page."

```
● live · cycle 2026-06-26 06:00 UTC · updated 14m ago · read-only simulation
```

State machine (thresholds tie to the API / cycle cadence — coordinate exact numbers with the
Architect's data-flow doc; cycle is daily, so suggested bands):

| State | Dot | Condition | Treatment |
|---|---|---|---|
| **live** | `●` `--ok` (slow pulse) | page data ≤ 6h old AND last cycle ≤ 26h | green, "updated Nm ago" |
| **stale** | `◐` `--warn` | last cycle 26–48h, or a panel older than the page | amber bar + per-panel `stale` chips |
| **unavailable** | `○` `--danger` | API unreachable / no cycle data | red bar: "Live API unreachable — showing last cached cycle (timestamp)" or `—` everywhere; never invent |

- Source the timestamp from `generated_at` / cycle `last_cycle_ts` returned by the API (verbatim,
  per the architect's "live API returns files verbatim" finding).
- **Per-panel inheritance:** if any panel's own `generated_at` is older than the page's, that panel
  shows its own `stale · as of <ts>` chip — so a fresh page never hides one cold corner.

---

## 6. SECTION-BY-SECTION SPEC

### § HERO — the honest headline
Three big mono metrics + the go-live verdict, on one band. This is the whole product in one glance.

- **Track:** `5 / 30` real track-days · caption "since 2026-06-10 reset · 25 to go · est. go-live ~2026-07-09". Chip: `paper`.
- **Equity:** `$100,190.22` · `+0.19%` since reset (`--ok` if ≥0). Caption "virtual $100k · daily yield ~$9.9". Chip: `paper`.
- **Go-Live:** `27 / 29` criteria · status pill **NOT READY** (`--warn`) with sub-line "2 blockers, both time-gated (waiting on track-days)". Chip: `live`.
- A one-line thesis under the hero (matches site/bot voice): *"Deterministic, LLM-free DeFi
  stablecoin-yield optimizer. Paper-validating in public. Track record before capital."*

### § 1 — PORTFOLIO  `paper`
- **Equity curve** (Console line, `--data-teal`), x-axis honest: shade/annotate the **demo region
  before 2026-06-10** and label the reset; only the post-reset 5 days are the "real" track.
- **4 metric cards:** Equity · Total return % · Daily yield $/day + APY today (with `regime`) ·
  Max drawdown (vs the kill-switch 5% line).
- **Allocation** donut/bars by protocol with **tier chips** (T1/T2) and per-protocol caps shown as
  a faint ceiling, so the deterministic policy is visible.
- **Current positions** table: protocol · tier · allocation % · APY · TVL-floor ok. Every APY
  carries the unit honestly (we normalize percent vs decimal internally).

### § 2 — GO-LIVE READINESS  `live`
- A **27/29 progress ring** + a checklist grouped: **Passing (27)** collapsed, **Pending (2)**
  expanded. The two pending are time-gated: `gap_monitor_30d` and `min_track_days_30` — each shown
  with *"not a code defect — waiting on N more honest track-days"* and the `estimated_days_to_pass`.
- Honesty note: `autopush_installed` passes on the real Mac but fails in sandbox/CI — show the
  source-of-truth note ("verified via launchctl on the production host").
- No fake "READY soon" optimism — the ETA is the arithmetic of track-days only.

### § 3 — STRATEGIES / STRUCTURAL DESK  `advisory`
The product's spine: it says **yes and no** on the record. Three verdict cards (semantic left
border), verbatim from the structural-desk:

| Card | Verdict pill | One-line finding |
|---|---|---|
| **Rates Desk** | `GO` `--ok` | FixedCarry validated, runs live-paper; refusal fires on toxic LRT books → fundable. |
| **RWA Repo Backstop** | `measurement-GO / book NO-GO` `--warn` | 10/10 RWA assets not cash-like on an executable on-chain exit; measurement GO, the book is off-code (legal/capital). |
| **Liquidator** | `NO-GO` `--danger` | Addressable long-tail ≈ $2–4M/yr gross, ~5–10× below the $20M bar → too small. |

- Below: **Tournament** (top strategies by Sharpe) — **but with the data-quality banner shown
  honestly**: if `tier1_verdict.data_quality.status == DEGENERATE` → a `not trustworthy` chip and
  the verbatim reason ("median Sharpe 44.8 → near-constant mock data; rankings not trustworthy
  until real point-in-time historical APY"). The dashboard must not present degenerate rankings as
  fact.
- All new/T2/T3 strategies carry the `advisory` chip (simulate-only, never allocate live).

### § 4 — HEALTH  `live`
- **Agents:** count from launchctl-equivalent the API exposes (honest "source of truth =
  launchctl/SYSTEM_BRIEFING, not a hardcoded number") + critical/degraded counts. Any
  `exit=1` agent (e.g. morning_digest Telegram issue) shown amber, not hidden.
- **System domains:** the health-monitor's per-domain pass/warn/fail grid.
- **Cycle continuity:** last cycle ts, gap vs the 26h/30h thresholds, and the gap-monitor streak
  (the same continuity that feeds go-live). Ties directly to the freshness bar.

### § 5 — REFUSAL & HONESTY  `advisory`
The differentiator — a system that refuses, shown plainly.
- **Refusal log:** latest refusal-engine output per underlying group (e.g. LRT/restaking): the
  refusal score vs the `refuse_threshold` (0.45) and `safe_band` (0.30), with the toxic-book
  reasons. `advisory` chip; "fail-closed" noted.
- **Data-quality & caveats panel:** a plain-language list of every place the system flags its own
  limits — tier1 `DEGENERATE`, `structural_break: insufficient data (0/12)`, RWA `exit_capacity_72h
  = $0 (documented-only redemption)`. These are *features*, shown with `unavailable` / `not
  trustworthy` chips, not swept away.
- **The reset story** restated: "Honest 5 days, not 15 padded. Everything before 2026-06-10 is
  demo and void."

### § 6 — REPORTS  `live`
- The **latest daily digest** and **weekly report**, rendered to match the Telegram bot's content
  (one worldview across bot + dashboard + site). Plain cards, not raw JSON.
- Link to history; each report stamped with its own `generated_at` and freshness chip.

### ▸ Ops (advanced) — drawer (collapsed by default)
Everything that made the old dashboard a debug console, moved here and clearly labeled internal:
Kanban, Decisions, Agent fleet detail, Backtest internals, raw JSON viewers. Visible to the owner,
out of the public headline read. (Or hosted under `/system` per the site IA — either is coherent.)

---

## 7. MOCKUPS (EN)

### 7.1 Header + paper-strip + freshness bar (every load)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ◆ SPA  earn-defi.com        Methodology  Strategies  Track Record  System    │
│                                              [ Dashboard ↗ ]      EN | RU      │
├────────────────────────────────────────────────────────────────────────────┤
│ ▲ Personal research project — paper-testing & tuning, not raising capital.    │ amber
├────────────────────────────────────────────────────────────────────────────┤
│ ● live   cycle 2026-06-26 06:00 UTC · updated 14m ago · read-only simulation  │ green dot
└────────────────────────────────────────────────────────────────────────────┘
   Overview · Portfolio · Go-Live · Strategies · Health · Honesty · Reports   ← sticky anchor nav
```

Stale / unavailable variants of the freshness bar:
```
◐ stale   last cycle 27h ago · some panels may lag · read-only simulation        (amber)
○ unavailable   Live API unreachable — last cached cycle 2026-06-25 06:00 UTC     (red)
```

### 7.2 HERO — honest headline

```
┌──────────── TRACK ───────┐ ┌──────────── EQUITY ──────┐ ┌──────────── GO-LIVE ─────┐
│  5 / 30   real track-days │ │  $100,190.22       paper │ │  27 / 29        live     │
│  [paper]                  │ │  +0.19% since reset  ▲    │ │  ◑ NOT READY             │
│  since 2026-06-10 reset   │ │  ~$9.9/day · APY ~3.6%   │ │  2 blockers, time-gated  │
│  25 to go · ETA ~Jul 09   │ │  virtual $100k base      │ │  (waiting on track-days) │
└───────────────────────────┘ └──────────────────────────┘ └──────────────────────────┘
  Deterministic, LLM-free DeFi stablecoin-yield optimizer. Paper-validating in public.
  Track record before capital.
```

### 7.3 GO-LIVE checklist

```
 GO-LIVE READINESS                                                    [live]
 ╭─ 27 / 29 ─╮   ▸ Passing (27)                                    [collapsed]
 │   ◑       │   ▾ Pending (2)
 │  93%      │     ⏳ min_track_days_30   — 5/30 honest days · ~25d to pass
 ╰───────────╯     ⏳ gap_monitor_30d     — continuous-track gate · ~25d to pass
                  Both are time-gated, not code defects. Nothing to fix —
                  the gate opens when the honest track reaches 30 days.
                  note: autopush verified via launchctl on production host
                        (always fails in sandbox/CI by design).
```

### 7.4 STRATEGIES / structural-desk verdicts

```
 STRATEGIES — STRUCTURAL DESK VERDICTS                               [advisory]
 ┌─ Rates Desk ──────────────┐ ┌─ RWA Repo Backstop ───────┐ ┌─ Liquidator ─────────────┐
 │ ▏ GO                  ✅   │ │ ▏ measurement-GO/book NO-GO│ │ ▏ NO-GO              ⛔   │
 │ FixedCarry validated,     │ │ 10/10 RWA assets not cash- │ │ Addressable ≈ $2–4M/yr,  │
 │ runs live-paper; refusal  │ │ like on executable on-chain│ │ ~5–10× below $20M bar →  │
 │ fires on toxic LRT books  │ │ exit. Book = legal/capital,│ │ too small to justify the │
 │ → fundable.               │ │ off-code.                  │ │ custody + CEX build.     │
 └───────────────────────────┘ └───────────────────────────┘ └──────────────────────────┘
 (green border)                 (amber border)                 (red border)

 TOURNAMENT  ⚠ rankings [not trustworthy]
   Ran on near-constant mock data (median Sharpe 44.8 → degenerate). Rankings shown
   for transparency only; not valid until real point-in-time historical APY series.
   S-xx … S-xx  [advisory]            (table rendered greyed with the caveat on top)
```

### 7.5 HEALTH

```
 HEALTH                                                               [live]
 Agents     ~42 loaded   crit 0   degraded 1 (morning_digest exit=1, Telegram)
            source of truth: launchctl / SYSTEM_BRIEFING
 Domains    portfolio ✓   risk ✓   data-feed ✓   monitoring ✓   reporting ◐
 Cycle      last 06:00 UTC (14m ago) ✓   gap 0h / 26h threshold   streak 5d
```

### 7.6 REFUSAL & HONESTY

```
 REFUSAL & HONESTY                                                    [advisory]
 Refusal log (rates desk, fail-closed)
   LRT (restaking)   score 0.31  ·  safe-band 0.30 · refuse ≥ 0.45   → WATCHING
   <group>           score 0.52                                       → REFUSED ⛔
 Self-reported limits
   • tournament ranking ......... not trustworthy  (mock data, degenerate)
   • structural break ........... unavailable        (only 0/12 daily returns)
   • RWA 72h exit capacity ...... $0                 (redemption documented-only)
 The reset: honest 5 days, not 15 padded. Pre-2026-06-10 is demo and void.
```

---

## 8. MOCKUPS (RU)

### 8.1 Шапка + плашка paper + индикатор свежести

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ◆ SPA  earn-defi.com        Методология  Стратегии  Трек-рекорд  Система      │
│                                              [ Дашборд ↗ ]        EN | RU      │
├────────────────────────────────────────────────────────────────────────────┤
│ ▲ Личный исследовательский проект — paper-режим, капитал не привлекается.     │ янтарь
├────────────────────────────────────────────────────────────────────────────┤
│ ● онлайн  цикл 2026-06-26 06:00 UTC · обновлено 14 мин назад · симуляция       │
└────────────────────────────────────────────────────────────────────────────┘
   Обзор · Портфель · Go-Live · Стратегии · Здоровье · Честность · Отчёты
```

Варианты индикатора:
```
◐ устарело   последний цикл 27 ч назад · часть панелей может отставать           (янтарь)
○ недоступно Live API недоступен — последний кешированный цикл 2026-06-25 06:00   (красный)
```

### 8.2 ГЕРО — честный заголовок

```
┌──────────── ТРЕК ────────┐ ┌──────────── КАПИТАЛ ─────┐ ┌──────────── GO-LIVE ─────┐
│  5 / 30   реальных дней   │ │  $100 190,22      paper  │ │  27 / 29       онлайн     │
│  [paper]                  │ │  +0,19% с перезапуска ▲  │ │  ◑ НЕ ГОТОВО             │
│  с перезапуска 2026-06-10 │ │  ~$9,9/день · APY ~3,6%  │ │  2 блокера — оба по      │
│  осталось 25 · ~09 июля   │ │  виртуальные $100k       │ │  времени (ждём дни трека)│
└───────────────────────────┘ └──────────────────────────┘ └──────────────────────────┘
  Детерминированный DeFi-оптимизатор доходности по стейблам, без LLM в риске.
  Валидация в paper-режиме, публично. Трек-рекорд раньше капитала.
```

### 8.3 GO-LIVE — чек-лист

```
 ГОТОВНОСТЬ К GO-LIVE                                                 [онлайн]
 ╭─ 27 / 29 ─╮  ▸ Пройдено (27)                                    [свёрнуто]
 │   ◑  93%  │  ▾ Ожидает (2)
 ╰───────────╯    ⏳ min_track_days_30 — 5/30 честных дней · ~25 дн
                  ⏳ gap_monitor_30d   — непрерывность трека · ~25 дн
                  Оба блокера — это просто ожидание 30 честных дней трека.
                  Чинить кодом нечего. autopush проверяется через launchctl
                  на боевом Mac (в sandbox/CI всегда fail — это нормально).
```

### 8.4 Стратегии — вердикты структурного деска

```
 СТРАТЕГИИ — ВЕРДИКТЫ СТРУКТУРНОГО ДЕСКА                              [advisory]
 ┌─ Rates Desk ──────────────┐ ┌─ RWA Repo Backstop ───────┐ ┌─ Liquidator ─────────────┐
 │ ▏ GO                  ✅   │ │ ▏ measurement-GO/book NO-GO│ │ ▏ NO-GO              ⛔   │
 │ FixedCarry валиден, идёт   │ │ 10/10 RWA-активов не cash- │ │ Адресуемое ≈ $2–4M/год,  │
 │ live-paper; refusal сраба- │ │ like при исполнимом on-    │ │ в 5–10× ниже планки $20M │
 │ тывает на токсичных LRT →  │ │ chain-выходе. Книга — это  │ │ → слишком мало для строй-│
 │ fundable.                  │ │ право/капитал, вне кода.   │ │ ки custody + CEX.        │
 └───────────────────────────┘ └───────────────────────────┘ └──────────────────────────┘

 ТУРНИР  ⚠ ранжирование [не достоверно]
   Считано на почти константных mock-данных (медианный Sharpe 44.8 → вырождено).
   Показано только ради прозрачности; невалидно до реальных исторических APY.
```

### 8.5 Здоровье

```
 ЗДОРОВЬЕ                                                             [онлайн]
 Агенты     ~42 загружено   crit 0   деградация 1 (morning_digest exit=1)
            источник истины: launchctl / SYSTEM_BRIEFING
 Домены     портфель ✓  риск ✓  фид ✓  мониторинг ✓  отчёты ◐
 Цикл       последний 06:00 UTC (14 мин назад) ✓  разрыв 0/26ч  серия 5 дн
```

### 8.6 Отказы и честность

```
 ОТКАЗЫ И ЧЕСТНОСТЬ                                                   [advisory]
 Журнал отказов (rates desk, fail-closed)
   LRT (restaking)   балл 0,31 · safe-band 0,30 · отказ ≥ 0,45   → НАБЛЮДЕНИЕ
 Самопризнанные ограничения
   • ранжирование турнира ........ не достоверно  (mock-данные)
   • структурный слом ............ недоступно      (0/12 дн. доходностей)
   • RWA-выход за 72ч ............ $0               (выкуп только «на бумаге»)
 Перезапуск: честные 5 дней, не 15 «дотянутых». До 2026-06-10 — демо, недействительно.
```

---

## 9. VISUAL SPEC (Console tokens — same as the site)

- **Background:** `--bg-base #0A0C10` page · `--bg-surface #11141A` cards · `--bg-surface-2` nested.
- **Accent:** `--accent #5B8DEF` (links/CTA) · `--data-teal #36C2B4` (equity curve, live ticks).
- **Semantic (meaning only):** `--ok #34D399` (pass/live/GO) · `--warn #F2B53C` (paper/pending/
  stale/measurement-GO) · `--danger #F26D6D` (NO-GO/unavailable/not-trustworthy/kill).
- **Type:** Inter (sans) + **JetBrains Mono loaded** for every number, chip, eyebrow, table, ts.
- **Cards:** `--r-lg 16px`, `1px --border`, hover `--border-strong`; status cards get a 3px
  semantic left border (verdict cards). No heavy shadows.
- **Eyebrow/section labels:** mono uppercase, `--text-faint`/`--accent` — **never green/amber**
  (green/amber reserved for status semantics only — same rule as the site).
- **Kill the leftovers:** remove all light-theme hex (`#1a1a1a`, pastel kanban/tag colors), the
  GitHub palette (`#58a6ff`), and purple `#8b5cf6` entirely.
- **Motion:** only color/opacity (120ms) + the single live-dot slow pulse (3s); respect
  `prefers-reduced-motion`. No chart animations (already disabled — keep).

---

## 10. COORDINATION WITH THE ARCHITECT'S DATA-FLOW DOC

This doc owns **visual/UX**; the Architect owns **wiring**. Shared contract points:

1. **One freshness source.** UX renders the global freshness bar + per-panel chips; the Architect
   defines the single endpoint/field (`generated_at` / `last_cycle_ts`) and the live/stale/
   unavailable thresholds the UX consumes. UX must not compute freshness from 30 separate fetches.
2. **Verbatim fields.** Live API returns files verbatim (known finding) — UX binds to the actual
   field shapes (`current_equity`, `apy_today_pct`, `real_days` vs `num_days`) the Architect
   documents; never assume the prompt's field names.
3. **No fabricated fallbacks at any layer.** When `data/*.json` is gitignored and only a static
   fallback exists (known stale-fallback hazard), the Architect flags it as stale → UX renders the
   `stale`/`unavailable` chip, never a clean number.
4. **One dashboard, one data path.** Retiring `index.html` + `investor_portal.html` removes the
   duplicate `investor_portal_data.json` path; the Architect points `/app` at the canonical live
   API + cached cycle files only.
5. **The 5/30 number.** UX shows `real_days` (=5), never `num_days`/`num_snapshots` (=37) as the
   headline. The Architect guarantees the API exposes `real_days` distinctly (PAPER_REAL_START
   guard already exists).

---

*End of design spec. No dashboard files were modified — UX design & mockups only. Pairs with the
Architect's data-flow doc. Owner reviews before any rebuild.*
