# SPA Telegram Bot — UX Design (menus · navigation · layouts)

**Status:** DESIGN DOC — owner-review before build. Not implemented here.
**Date:** 2026-06-26 · **Author:** UX (Senior)
**Scope:** This doc owns the **menu tree, navigation model, screen layouts (mockups), bilingual copy (EN|RU)**.
The **service/push-digest tiers** (how the bot process runs, polling, dedup, dispatch) are owned by the
ARCHITECT's technical doc — this doc references those touchpoints but does not specify them.

**Brand rules (binding, honesty-first):**
- Every number carries an **honest label**: `paper`, `advisory`, `read-only`, `simulation`. No claim sounds live.
- Money source of truth: `data/paper_trading_status.json` / `data/equity_curve_daily.json` (`is_demo:false`, `execution_mode:read_only_simulation`).
- Track day counts the **real** track (`real_days`), not raw bars. Today: **5/30 real** (anchor 2026-06-22), 17 days running.
- Go-live is **27/29** — the two open are time-gated (`gap_monitor_30d`, `min_track_days_30`), nothing to "fix".
- Strategy verdicts come from the Structural Desk: Rates Desk **GO**, RWA Backstop **measurement-GO / book NO-GO**, Liquidator **NO-GO**.
- LLM is FORBIDDEN in risk/kill — the bot never editorializes; it surfaces deterministic engine output verbatim with formatting only.

---

## 1. Design language

**Inline keyboards** (buttons under a message) + **`editMessageText`** for drill-down: tapping a button
**edits the same message in place** — no message spam, the chat stays one clean evolving panel.

Every screen follows the same skeleton:

```
<breadcrumb header>            ← where am I (Home › Strategies › Rates Desk)
<title line + honest label>
─────────────────────         ← thin rule (em-dash run) separates header from body
<body: sections, key numbers up top, monospace tables where useful>
─────────────────────
<freshness footer>            ← "updated 06:00 UTC · paper"
[ inline button grid ]
[ ◀ Back ]  [ 🏠 Home ]        ← navigation row, always last
```

**Visual anchors (emoji = meaning, used consistently):**

| Emoji | Meaning | | Emoji | Meaning |
|---|---|---|---|---|
| 📊 | Portfolio / equity | | ✅ | pass / healthy / SAFE |
| 🎯 | Go-Live gate | | ⛔ | fail / NO-GO / kill |
| 🏦 | Strategies / desks | | ⚠️ | warning / advisory caution |
| 🩺 | Health (agents/system) | | ◐ | partial / measurement-only |
| 📅 | Reports | | ⏳ | time-gated / pending |
| 🛡️ | Refusal / risk gate | | 🔬 | research / advisory |
| ⚙️ | Settings | | 💤 | muted |
| 📈 | up / yield | | 📉 | down / drawdown |

**Tone:** terse, factual, scannable. Numbers right-aligned in monospace blocks. No hype words.

---

## 2. The menu tree (drill-down)

```
🏠 HOME
│
├── 📊 Portfolio
│     ├── Track (5/30, equity curve, daily yield, regime)
│     ├── Positions (per-protocol allocation table)
│     └── Equity history (7d / 30d / all sparkline)
│
├── 🎯 Go-Live
│     ├── Summary (27/29, the 2 open blockers, ETA)
│     ├── Criteria — Passed (27 ✅, paged)
│     └── Criteria — Open (2 ⏳ time-gated)
│
├── 🏦 Strategies  (the Structural Desk + sleeves)
│     ├── 🏦 Rates Desk          → verdict GO → sleeves → sleeve detail
│     ├── 🛡️ RWA Safety Board    → verdict ◐ → per-asset exit-liquidity
│     ├── 🔬 Structural Desk      → 3 theses verdict map
│     └── 🛡️ Refusal Log         → per-underlying SAFE/REFUSE tail scores
│
├── 🩺 Health
│     ├── Agents (44 ✅ / 2 ⛔, list paged)
│     ├── System (7 domains)
│     └── Last cycle (ts, status, freshness)
│
├── 📅 Reports
│     ├── 📅 Today  (daily digest, on demand)
│     ├── 📆 This week (weekly report)
│     └── 🗂️ History (last 7 daily digests)
│
├── ⚠️ Warnings
│     ├── Active (open warnings, urgent first)
│     └── Recent (resolved, last 7d)
│
└── ⚙️ Settings
      ├── 🌐 Language  (EN ⇄ RU)
      ├── 🔔 Digests   (daily on/off · weekly on/off)
      ├── 🚨 Warnings  (critical-only / all / off)
      └── 💤 Mute      (1h / 8h / until I unmute)
```

**Depth:** Home (L0) → Section (L1) → Detail / leaf (L2), occasionally L3 (Rates Desk → sleeve → sleeve detail).
Never deeper than 3 taps from Home to any number.

---

## 3. Navigation model

- **Single evolving message.** The bot keeps **one panel message** per chat. Every button edits it via
  `editMessageText` (text + `reply_markup`). No new messages for navigation → no scroll spam.
- **Two reserved nav buttons on the last row of every non-home screen:** `[ ◀ Back ]` (one level up) and
  `[ 🏠 Home ]` (straight to L0). Home screen shows neither (it is the root) — instead a `[ 🔄 Refresh ]`.
- **Breadcrumb header** on every screen: `Home › Strategies › Rates Desk`. RU: `Дом › Стратегии › Rates Desk`.
- **Callback-data convention** (for the build team): `nav:<path>` e.g. `nav:home`, `nav:portfolio.track`,
  `nav:strategies.rates.fixedcarry`; action buttons use `act:<verb>:<arg>` e.g. `act:setlang:ru`,
  `act:mute:8h`, `act:report:today`. Back is computed as the parent of the current path (no separate state needed).
- **Paging** (long lists: agents, criteria, history): `[ ◀ ]  3/5  [ ▶ ]` row above the nav row; callback `pg:<path>:<n>`.
- **Push messages are separate** from the panel. A pushed daily digest / warning arrives as its **own** message
  (so it survives in history) and carries a `[ Open in menu ▸ ]` button that jumps the panel to the relevant view.
- **Stale-guard:** the freshness footer shows the source timestamp; if data is older than its expected cadence the
  footer turns `⚠️ stale (Nh old)` — honest, never hidden.
- **Language is per-chat**, applied to every screen including pushes. Toggle in Settings; takes effect on next edit.
- **Deep entry / `/start`:** any command (`/start`, `/menu`, `/status`) (re)spawns the Home panel. Legacy
  text commands (`/portfolio`, `/today`, `/week`, `/agents`) are kept as **shortcuts** that open the panel
  directly on the matching screen.

---

## 4. Key screen mockups

> Mockups show the literal message text + the inline-button grid. `[ … ]` = a button. Rows are stacked.
> EN shown; RU copy in §6. Numbers are live samples from `data/*` on 2026-06-26.

### 4.1 HOME (L0)

```
🏠  SPA Monitor                       paper · read-only
─────────────────────────────────────────────
Equity   $100,190.22   ▲ +0.19%
Track    Day 5 / 30    (real)    Go-Live 27/29
Today    +$9.91   ·   APY 3.61%   ·   regime VOLATILE
Health   ✅ system OK   ·   ⛔ 2 agents
─────────────────────────────────────────────
updated 06:00 UTC · tap a section

[ 📊 Portfolio ]   [ 🎯 Go-Live ]
[ 🏦 Strategies ]  [ 🩺 Health ]
[ 📅 Reports ]     [ ⚠️ Warnings ]
[ ⚙️ Settings ]    [ 🔄 Refresh ]
```

The Home panel doubles as the at-a-glance dashboard: the 4 vital lines (equity, track, today, health)
are always the first thing you see, before any tap. A ⛔ in the health line is the only "alarm" allowed at L0.

### 4.2 Portfolio › Track (L2)

```
Home › Portfolio › Track            paper · simulation
─────────────────────────────────────────────
📊  TRACK STATUS
Equity        $100,190.22
Total return  ▲ +0.19%        since 2026-06-10
Real track    Day 5 / 30      anchor 2026-06-22
Days running  17

Today
  Daily yield   +$9.91
  Daily return  +0.0099%
  APY (today)   3.61%
  Regime        VOLATILE

Drawdown      0.00% (real)    kill at −5%
Best day      +0.016%  2026-06-21
Vol (daily)   0.0025%
─────────────────────────────────────────────
updated 06:00 UTC · is_demo:false

[ 📦 Positions ]   [ 📈 Equity history ]
[ ◀ Back ]         [ 🏠 Home ]
```

### 4.3 Portfolio › Positions (L2)

```
Home › Portfolio › Positions        paper · simulation
─────────────────────────────────────────────
📦  ALLOCATION   ($100,190 deployed across 7)

 Protocol            USD       %
 ──────────────  ────────  ─────
 aave_v3          23,250    23.2
 compound_v3      15,852    15.8
 maple            15,852    15.8
 spark_susds      13,739    13.7
 morpho_steak.    10,568    10.5
 euler_v2         10,568    10.5
 yearn_v3          3,170     3.2
 ──────────────  ────────  ─────
 cash buffer       7,191     7.2

Model  risk_adjusted  ·  last trade T017
─────────────────────────────────────────────
updated 06:00 UTC · live feed: 34 adapters

[ ◀ Back ]   [ 🏠 Home ]
```

### 4.4 Go-Live › Summary (L1)

```
Home › Go-Live                      gate v6.0 · honest
─────────────────────────────────────────────
🎯  GO-LIVE READINESS

      27 / 29  PASS        ⛔ NOT READY

Open (both time-gated — nothing to fix):
  ⏳ min_track_days_30    5 / 30 real days
  ⏳ gap_monitor_30d      needs 30 continuous

ETA  ~25 more real track-days → ~2026-07-21
All code/data/risk criteria already pass.
─────────────────────────────────────────────
updated 06:00 UTC

[ ✅ Passed (27) ]   [ ⏳ Open (2) ]
[ ◀ Back ]          [ 🏠 Home ]
```

### 4.5 Go-Live › Criteria — Passed (L2, paged)

```
Home › Go-Live › Passed             page 1 / 3
─────────────────────────────────────────────
✅  PASSED CRITERIA  (27)

 ✅ equity_curve_real
 ✅ trades_real
 ✅ status_real
 ✅ no_demo_data
 ✅ data_fresh_48h
 ✅ cycle_runner_exists
 ✅ compound_v3_adapter
 ✅ morpho_steakhouse_adapter
 ✅ aave_arbitrum_adapter
 ✅ pendle_pt_adapter
─────────────────────────────────────────────
[ ◀ ]   1 / 3   [ ▶ ]
[ ◀ Back ]      [ 🏠 Home ]
```

### 4.6 Strategies (L1)

```
Home › Strategies                   advisory · no live capital
─────────────────────────────────────────────
🏦  THE STRUCTURAL DESK

Three theses, honest verdicts:
  ✅  Rates Desk         GO        carry is fundable
  ◐   RWA Safety Board   meas-GO   book NO-GO (off-code)
  ⛔  Liquidator          NO-GO     too small (<$20M bar)

All sleeves are ADVISORY — simulate only, never
allocate live, never touch the go-live track.
─────────────────────────────────────────────
RWA floor benchmark  3.4%  (live tokenized T-bills)

[ 🏦 Rates Desk ]      [ 🛡️ RWA Board ]
[ 🔬 Structural Desk ] [ 🛡️ Refusal Log ]
[ ◀ Back ]            [ 🏠 Home ]
```

### 4.7 Strategies › Rates Desk (L2)

```
Home › Strategies › Rates Desk      advisory · paper
─────────────────────────────────────────────
🏦  RATES DESK            verdict ✅ GO

Refusal-first fair-value for tokenized rates/carry.
Pipeline: RESEARCH → BACKTEST → WALK-FWD → PAPER
          → CANARY → FULL

Sleeves (4)              beats 3.4% floor?
  FixedCarry             ✅ yes   (live-paper)
  …                      tap to open
─────────────────────────────────────────────
as_of 2026-06-25 · LLM-forbidden · fail-closed

[ FixedCarry ▸ ]   [ other sleeves ▸ ]
[ ◀ Back ]         [ 🏠 Home ]
```

### 4.8 Strategy detail — Rates Desk verdict (L3, leaf)

```
Home › Strategies › Rates Desk › FixedCarry   advisory
─────────────────────────────────────────────
🏦  FIXEDCARRY               ✅ GO

Verdict   validated, runs live-paper
Question  "does the engine separate real spread
          from tail-comp?"  → answered YES
          over real 2024-06 → 2026-06 history

Promotion criteria
  ✅ beats RWA floor (risk-adj, covers drawdown)
  ✅ capacity sufficient
  … (tap for full criteria)

Refusal gate
  🛡️ refuses every toxic LRT book (ezETH pattern)
─────────────────────────────────────────────
advisory · moves NO live capital · floor 3.4%

[ 📋 Full criteria ]  [ 🛡️ Refusal Log ]
[ ◀ Back ]           [ 🏠 Home ]
```

### 4.9 Strategies › Refusal Log (L2)

```
Home › Strategies › Refusal Log     advisory · 2026-06-26
─────────────────────────────────────────────
🛡️  REFUSAL ENGINE          all within safe band

refuse ≥ 0.45 · safe band ≤ 0.30 · fail-closed

 Underlying   tail   verdict
 ──────────  ─────  ────────
 ezeth        0.118   ✅ SAFE
 reth         0.135   ✅ SAFE
 weeth        0.112   ✅ SAFE
 steth        0.092   ✅ SAFE
 eeth         0.082   ✅ SAFE

No book currently refused. Engine fires REFUSE
automatically when any score crosses 0.45.
─────────────────────────────────────────────
model rates_desk_refusal_engine · LLM-forbidden

[ ezeth ▸ ] [ reth ▸ ] [ weeth ▸ ]
[ ◀ Back ]  [ 🏠 Home ]
```

### 4.10 Health › Agents (L2, paged)

```
Home › Health › Agents              page 1 / 5
─────────────────────────────────────────────
🩺  AGENTS        44 ✅   ·   2 ⛔   ·   46 total
                  overall ⛔ CRITICAL

 ✅ agent_health           60m
 ✅ analytics_tier_b       12m
 ✅ analytics_tier_c      829m  (daily)
 ✅ apiserver           always-on
 ⛔ <critical agent>      ...   exit≠0
 ...
─────────────────────────────────────────────
[ ◀ ]   1 / 5   [ ▶ ]      [ ⛔ Only failing ]
[ ◀ Back ]                 [ 🏠 Home ]
```

The `[ ⛔ Only failing ]` filter jumps straight to the 2 critical agents — the fast path when overall is CRITICAL.

### 4.11 Health › System (L2)

```
Home › Health › System              monitor · 7 domains
─────────────────────────────────────────────
🩺  SYSTEM HEALTH           overall ✅ INFO

 CRITICAL 0 · WARNING 0 · INFO 2 · OK 32

 ✅ d1 data pipeline
 ✅ d2 connectivity
 ℹ️ d3 strategy quality
 ✅ d4 external feeds
 ✅ d5 code integrity
 ℹ️ d6 risk gates
 ✅ d7 hygiene
─────────────────────────────────────────────
run 20260625T1832 · fingerprint da39a3ee

[ ◀ Back ]   [ 🏠 Home ]
```

### 4.12 Reports › Daily digest (L2, also pushed)

```
Home › Reports › Today              📅 2026-06-26 · paper
─────────────────────────────────────────────
📅  DAILY DIGEST

Track    Day 5 / 30 (real)   ·   Go-Live 27/29
Equity   $100,190.22         ▲ +0.19% total
Today    +$9.91   ·   +0.0099%   ·   APY 3.61%
Regime   VOLATILE
Cycle    ✅ ok @ 06:00 UTC

Movements
  📈 best held    aave_v3
  📦 7 protocols  ·  cash 7.2%

Warnings   ⛔ 2 agents critical (tap ⚠️)
─────────────────────────────────────────────
read-only simulation · is_demo:false

[ ⚠️ Warnings (2) ]  [ 📦 Positions ]
[ 📆 Weekly ]        [ 🏠 Home ]
```

When **pushed** (08:05 UTC), the same body arrives as its own message with a single
`[ Open in menu ▸ ]` button instead of the nav row.

### 4.13 Reports › Weekly report (L2, also pushed)

```
Home › Reports › Weekly             📆 week of 2026-06-20 · paper
─────────────────────────────────────────────
📆  WEEKLY REPORT

TRACK
  Real days     +5  →  5 / 30   (anchor 06-22)
  Go-Live       27 / 29   (2 time-gated)
  ETA go-live   ~2026-07-21

PERFORMANCE  (paper)
  Equity        $100,134.79 → $100,190.22
  Week return   ▲ +0.055%
  Avg daily     +$9.7 / day   ·   APY ~3.6%
  Drawdown      0.00%   (kill at −5%)
  Best / worst  +0.016% / 0.000%

STRATEGY VERDICTS  (advisory)
  ✅ Rates Desk      GO       carry fundable
  ◐  RWA Board       meas-GO  book NO-GO
  ⛔ Liquidator       NO-GO    too small
  🛡️ Refusal         all SAFE (no book refused)

HEALTH
  System   ✅ OK (0 critical domains)
  Agents   ⛔ 2 critical / 44 ok — see Health
─────────────────────────────────────────────
read-only simulation · floor benchmark 3.4%

[ 📊 Track ]    [ 🩺 Health ]
[ 🏦 Strategies ] [ 🏠 Home ]
```

### 4.14 Warnings › Active (L1) + a single warning

**List view:**
```
Home › Warnings                     2 active
─────────────────────────────────────────────
⚠️  ACTIVE WARNINGS

 ⛔ CRITICAL  agent_health
    2 agents down · overall CRITICAL
    since 16:49 UTC

 (no other active warnings)
─────────────────────────────────────────────
[ ⛔ agent_health ▸ ]
[ 🗂️ Recent (7d) ]
[ ◀ Back ]   [ 🏠 Home ]
```

**Pushed real-time warning** (own message, urgent, distinct framing):
```
🚨🚨  CRITICAL WARNING  🚨🚨
─────────────────────────────────────────────
⛔  AGENTS CRITICAL

2 of 46 agents are down (overall CRITICAL).
Detected 16:49 UTC.

This is a monitoring alert — paper track is
read-only and is NOT at financial risk.
─────────────────────────────────────────────
[ 🩺 Open Health ▸ ]   [ 💤 Mute 8h ]
```

**Warning taxonomy & framing** (each pushed as its own message, never silent-edited):

| Trigger | Header | Urgency framing | Drill button |
|---|---|---|---|
| Kill-switch active (drawdown ≥ −5%) | `🚨🚨 KILL-SWITCH 🚨🚨` | highest — "all positions flat (paper)" | `[ 📊 Track ▸ ]` |
| Cycle failed / missed | `🚨 CYCLE FAILURE` | high — "daily cycle did not run" | `[ 🩺 Last cycle ▸ ]` |
| Agents CRITICAL | `🚨🚨 CRITICAL WARNING 🚨🚨` | high — monitoring, not financial | `[ 🩺 Open Health ▸ ]` |
| Refusal engine fires REFUSE | `⚠️ REFUSAL FIRED` | medium — advisory book refused | `[ 🛡️ Refusal ▸ ]` |
| Data stale > cadence | `⚠️ STALE DATA` | low — "feed N h old" | `[ 🩺 System ▸ ]` |

Every warning honestly states whether it is **financial** vs **monitoring/advisory** (the track is paper / read-only).

### 4.15 Settings (L1)

```
Home › Settings                     ⚙️
─────────────────────────────────────────────
⚙️  SETTINGS

Language    🇬🇧 EN  (active)
Daily       🔔 ON   08:05 UTC
Weekly      🔔 ON   Mon 08:10 UTC
Warnings    🚨 Critical only
Mute        — not muted
─────────────────────────────────────────────
[ 🌐 Language: RU ]    [ 🔔 Daily: OFF ]
[ 🔔 Weekly: OFF ]     [ 🚨 Warnings ▸ ]
[ 💤 Mute ▸ ]
[ ◀ Back ]            [ 🏠 Home ]
```

**Sub-toggles** (each edits in place, reflecting the new state immediately):
- `🌐 Language` → toggles `EN ⇄ RU`, re-renders the whole panel in the new language.
- `🔔 Daily / Weekly` → on/off toggle each.
- `🚨 Warnings ▸` → opens a 3-way choice: `[ All ] [ Critical only ] [ Off ]`.
- `💤 Mute ▸` → `[ 1h ] [ 8h ] [ Until I unmute ]`; while muted, Home footer shows `💤 muted (Nh left)`.

---

## 5. Information-layout rules (the "beautiful" spec)

1. **Vital numbers first.** Each view leads with the 1–4 numbers that answer "is everything OK?" before any detail.
2. **One honest label per screen**, top-right of the header (`paper`, `advisory`, `read-only · simulation`).
3. **Monospace tables** for any 2+ column data (positions, criteria, refusal scores, agents): right-align numbers,
   align decimal points, use a `──` rule row between header and body and before totals.
4. **Em-dash rules** (`─────`) separate header / body / footer — three bands on every screen.
5. **Emoji as the leftmost glyph** of a status line so the eye scans a vertical column of ✅/⛔/⏳.
6. **Freshness footer** always present: source timestamp + provenance (`is_demo:false`, `LLM-forbidden`, model name).
7. **No paragraphs of prose.** Engine "reasons" are truncated to one line with a `▸` to expand.
8. **Color via emoji only** (Telegram has no text color): green ✅ / red ⛔ / amber ⚠️ / blue ℹ️ / grey ⏳💤.
9. **Numbers match the JSON exactly** — the bot formats, never recomputes. Percent vs decimal normalized at the formatter.
10. **Buttons read as verbs/destinations**, ≤ ~16 chars, ≤ 2 per row (3 only for tiny chips like pager / chips).

---

## 6. Bilingual EN | RU

Language is per-chat (Settings). Every string has an EN and RU form; **proper nouns stay as-is**
(protocol names, `Rates Desk`, `FixedCarry`, `aave_v3`, criteria keys, `VOLATILE`). Numbers/labels localize.

**Home buttons**

| EN | RU |
|---|---|
| 📊 Portfolio | 📊 Портфель |
| 🎯 Go-Live | 🎯 Go-Live |
| 🏦 Strategies | 🏦 Стратегии |
| 🩺 Health | 🩺 Здоровье |
| 📅 Reports | 📅 Отчёты |
| ⚠️ Warnings | ⚠️ Предупреждения |
| ⚙️ Settings | ⚙️ Настройки |
| 🔄 Refresh | 🔄 Обновить |
| ◀ Back | ◀ Назад |
| 🏠 Home | 🏠 Домой |

**Breadcrumbs:** `Home › Strategies › Rates Desk` → `Дом › Стратегии › Rates Desk`.

**Honest labels**

| EN | RU |
|---|---|
| paper · read-only | бумага · read-only |
| advisory · no live capital | advisory · без живого капитала |
| simulation | симуляция |
| NOT READY | НЕ ГОТОВ |
| time-gated — nothing to fix | ждём по времени — чинить нечего |
| moves NO live capital | живой капитал не двигает |
| monitoring alert, not financial | алерт мониторинга, не финансовый |

**Home (RU) example**

```
🏠  SPA Monitor                       бумага · read-only
─────────────────────────────────────────────
Капитал    $100 190.22   ▲ +0.19%
Трек       День 5 / 30   (реальный)   Go-Live 27/29
Сегодня    +$9.91   ·   APY 3.61%   ·   режим VOLATILE
Здоровье   ✅ система OK   ·   ⛔ 2 агента
─────────────────────────────────────────────
обновлено 06:00 UTC · выберите раздел

[ 📊 Портфель ]   [ 🎯 Go-Live ]
[ 🏦 Стратегии ]  [ 🩺 Здоровье ]
[ 📅 Отчёты ]     [ ⚠️ Предупреждения ]
[ ⚙️ Настройки ]  [ 🔄 Обновить ]
```

**Daily digest (RU) header example**

```
📅  ДНЕВНОЙ ОТЧЁТ
Трек    День 5 / 30 (реальный)   ·   Go-Live 27/29
Капитал $100 190.22              ▲ +0.19% всего
Сегодня +$9.91   ·   +0.0099%   ·   APY 3.61%
Режим   VOLATILE
Цикл    ✅ ok @ 06:00 UTC
```

**Number formatting:** EN uses `$100,190.22`; RU uses thin-space groups `$100 190.22` (or keep `,` if simpler —
owner to choose). Dates ISO (`2026-06-26`) in both. Percent always `+0.19%` style.

---

## 7. Data-source map (each view → file)

| View | Source file(s) |
|---|---|
| Home vitals | `paper_trading_status.json`, `golive_status.json`, `agent_health.json`, `system_health.json` |
| Portfolio · Track | `paper_trading_status.json`, `equity_curve_daily.json` |
| Portfolio · Positions | `paper_trading_status.json` (`current_positions`) |
| Go-Live | `golive_status.json` (`checks`, `passed/total`) |
| Strategies · overview | `docs/STRUCTURAL_DESK.md` verdict table (static) + `rates_desk/rates_desk_promotion.json` |
| Rates Desk / sleeves | `rates_desk/rates_desk_promotion.json`, `rate_surface.json` |
| RWA Board | `rwa_safety_board.json` (per-asset exit liquidity / NAV) |
| Refusal Log | `refusal_status.json` (`underlyings[].metrics`, thresholds) |
| Health · Agents | `agent_health.json` |
| Health · System | `system_health.json` |
| Daily / Weekly | the above, composed by `spa_core/reporting/{daily,weekly}_telegram_report.py` |
| Warnings | killswitch state, cycle heartbeat, `agent_health.json` (CRITICAL), `refusal_status.json` |

> The bot **reads files verbatim** (live API returns them as-is) and only formats — consistent with the
> "no recompute, honest labels" rule. Stale data shows the ⚠️ stale footer rather than a guessed value.

---

## 8. Handoff to ARCHITECT (boundaries)

This doc defines: **menu tree, callback-data scheme, navigation (single-panel `editMessageText` + Back/Home),
screen layouts, warning taxonomy framing, EN|RU copy, data-source map.**

The ARCHITECT's doc owns: the bot **service/runtime**, push-digest **scheduling/dispatch tiers**, dedup,
per-chat state storage, polling/long-poll vs webhook, and how pushes are triggered by the launchd agents.
Touchpoints we depend on them for: (a) push messages carry `[ Open in menu ▸ ]` deep-links; (b) per-chat
language + digest/mute prefs are persisted; (c) the warning triggers in §4.14 map to real monitor events.

*End of UX design doc — owner review requested before build.*
