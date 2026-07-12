# PHASE 0 — SELL SPRINT: TASK-LEVEL SPEC

> Execute in this order: **F1 (wire funnel events, day 1, parallel) → N1 → M1 → M2 → M10 →
> M3 → M4+M12 → M7 → M9 → U1→U2→U3 → M6 → M8 → M11 → N2 → F2.**
> Each task: Goal / Files / Implementation / Copy (EN+RU) / Acceptance / Verify.
> Push per task or small batches; announce each; build-green gate always.

---

## N1 — One canonical number everywhere `[P0][M]`

**Goal:** every APY/track number on both properties reads from one source; the site tells ONE
story: *~3.3% realized (conservative, live paper track) · up to 6/12/20% bands · research
targets always labeled target, always with tail.*

**Canonical sources (only these):**
- `landing/src/lib/tier_bands.json` — tier bands/labels (owner-decided display "up to {max}%").
- Track APIs for realized/live values: `/api/ssot/facts` (global), `/api/v1/golive`
  (evidenced days), `/api/live/safety` (evidenced drawdown). Realized conservative APY =
  track-to-date annualized from the track API — NEVER the volatile daily `apy_today_pct`.
- New file `landing/src/lib/canonical_numbers.js` (create): exports
  `REALIZED_CONSERVATIVE_APY_FALLBACK = 3.3`, `RWA_FLOOR_PCT = 3.4`,
  `AGGRESSIVE_MAX_BACKTEST_DD_PCT = 50`, `BANK_SAVINGS_APY_PCT = 0.4` (+ source URL consts).
  Static fallbacks only — live value always preferred when API is up.

**Known literals to replace (verified 2026-07-12; re-grep before editing — lines may drift):**
- `index.astro:107` demo-KPI "Estimated APY 5.4%" → keep (it's a *sample wallet* illustration)
  but label it "sample data" if not already; `:200` "up to 6%", `:213` "up to 12%", `:226`
  "up to 20%", `:207` "~3.3%" → read from `tier_bands.json` + canonical_numbers.
- `packages.astro:6-19,87` band literals; `:50-53` "12–20%" caveat; `:142` "15% vs ~4.5%" →
  same treatment.
- RWA floor stated as both ~3.3% and ~3.4% somewhere (UX-30): grep `3.3` and `3.4` across
  `landing/src` + checkup repo; floor = **3.4** everywhere (it's the rwa_feed live value's
  committed fallback); the *conservative realized* is ~3.3 — the two must never be conflated.
- Nav dropdown teaching two names per tier (UX-28): `SiteHeader.astro` Strategy Lab dropdown —
  only Conservative/Balanced/Aggressive naming (owner-decided); alt names
  (preserve/core/max-yield) never appear in nav.
- Tiers with no live track render "target band + 'not yet paper-tracked'" instead of "—"
  (UX-29): fix in the tier-card components wherever live APY is null.

**Acceptance:** `grep -rnE '(up to [0-9]|[0-9]\.[0-9]% (APY|realized)|~3\.[34])' landing/src/pages landing/src/components` returns only reads
from canonical sources or clearly-labeled sample data; /, /packages, nav, /strategies/* all
tell the same numbers. **Verify:** build green + eyeball all four surfaces EN and RU.

---

## M1 — Homepage hero rewrite `[P0][S]` — `landing/src/pages/index.astro`

**Goal:** hero sells the yield desk (the business), keeps Checkup one click away (the door).

**Copy (EN):**
- Eyebrow: `Non-custodial · paper-stage · every number reproducible`
- H1: `A stablecoin yield desk that proves every number.`
- Sub: `~3.3% realized on the live conservative track — every day evidenced, 0.0% realized
  drawdown. Research tiers target up to 20%, published with their tails, and refused for live
  capital until they earn it.`
- CTA primary (accent): `Check your wallet — free` → `/#analyze`, `data-track="hero_cta_checkup"`
- CTA secondary (ghost): `See the live track` → `/track-record`, `data-track="hero_cta_track"`

**Copy (RU):**
- Eyebrow: `Non-custodial · paper-стадия · каждая цифра воспроизводима`
- H1: `Деск стейблкоин-доходности, который доказывает каждую цифру.`
- Sub: `~3,3% реализовано на живом консервативном треке — каждый день подтверждён, 0,0%
  реализованной просадки. Research-тиры целятся до 20%, публикуются вместе с хвостами и не
  допускаются к живому капиталу, пока его не заслужат.`
- CTA: `Проверить кошелёк — бесплатно` / `Смотреть живой трек`

**Implementation:** replace the current tool-first hero heading block; the `/#analyze` checkup
widget STAYS on the homepage (it's door #1) — it moves visually below the hero + counter strip
(M4). Realized % and drawdown from track API with canonical fallbacks; if API offline, render
fallback WITH the existing offline-honesty style (grey dot), never a fake "live".
**Acceptance:** 5-second test: a stranger can say what the product is and what two actions are
offered. Checkup entry ≤1 click. **Verify:** build; screenshot desktop+mobile, EN+RU.

---

## M2 — Comparison bar `[P0][S]` — new `landing/src/components/CompareBar.astro`

**Goal:** anchor our numbers against what the visitor already knows (Superform/Ethena pattern).

**Content (one horizontal band, 4 cells, placed on `/` under hero and on `/packages` top):**

| Bank savings | Tokenized T-bills | **SPA Conservative** | SPA Aggressive |
|---|---|---|---|
| ~0.4% APY | ~3.4% (live floor) | **~3.3% realized · auditable block-by-block** | up to 20% **target** (research) |

- T-bills cell reads the live RWA-floor feed if exposed via API, else canonical fallback 3.4.
- Footnote (small, one line): `Sources: FDIC national average savings rate; tokenized T-bill
  floor = live TVL-weighted feed; SPA numbers = paper track, evidenced daily.` RU mirror.
- SPA Conservative cell visually emphasized (accent border). Aggressive cell links to
  `/packages#aggressive` with `data-track="compare_aggr_click"`.

**RU cells:** `Банковский вклад ~0,4%` / `Токенизированные T-bills ~3,4% (живой floor)` /
`SPA Conservative ~3,3% реализовано · проверяемо поблочно` / `до 20% target (research)`.

**Acceptance:** renders on / and /packages, responsive (stacks 2×2 on mobile), numbers from
canonical sources. **Verify:** build + mobile screenshot.

---

## M10 — /packages framing flip `[P0][M]` — `landing/src/pages/packages.astro`

**Goal:** pricing-page psychology: ONE number + ONE status chip per tier above the fold;
every honest detail kept but moved into an expandable risk sheet.

**Per-tier card layout (top→bottom):**
1. Tier name + status chip (`LIVE PAPER TRACK` green / `RESEARCH · GATED` amber — from
   strategy_config-driven pills, UX-10 already shipped).
2. THE number: Conservative `~3.3% realized` (sub: `band up to 6%`); Balanced `up to 12%
   target`; Aggressive `up to 20% target`.
3. One-line promise: Cons `The floor that runs while you sleep — 0.0% realized drawdown.` /
   Bal `The middle path — levered carry with a guardian on top.` / Aggr `The engine already
   found the 15–20% strategies. It also found their tails.`
   RU: `Floor, который работает, пока ты спишь — 0,0% реализованной просадки.` /
   `Средний путь — carry с плечом под присмотром стража.` / `Движок уже нашёл стратегии на
   15–20%. И их хвосты тоже.`
4. `<details>` **"Full risk sheet →" / «Полный риск-паспорт →»** containing EVERYTHING
   currently above the fold: drawdown caps, evidence level L0–L6, backtest worst drawdown
   (~50% aggressive), "outside RiskPolicy v1.0", pause/kill rules. Nothing deleted — relocated.
5. CTA: Cons → `/pilot` (`Talk to us`); Aggr → early-access list (M7): `Get the validation
   report first` / `Получить отчёт валидации первым`.
6. Refusal reframe replaces any "NOT yet trustworthy"-style line:
   EN `Refused for live capital until it passes 30 forward days + one real volatility event.
   That refusal is the product.`
   RU `Не допущен к живому капиталу, пока не пройдёт 30 forward-дней и одно реальное
   волатильное событие. Этот отказ — и есть продукт.`

**Also:** calculator (M3) embedded at the bottom of /packages; comparison bar (M2) on top.
**Acceptance:** above-the-fold shows exactly 1 number + 1 chip + 1 line + CTA per tier;
risk sheet opens with all prior facts present; EN|RU. **Verify:** build + before/after
screenshots + grep confirms no honest fact was deleted (diff review).

---

## M3 — Yield calculator `[P0][M]` — new `landing/src/components/YieldCalc.jsx` (island)

**Goal:** the user sells himself (Nexo/Superform pattern), fabrication-proof by construction.

**Spec:**
- Slider: $1,000 → $1,000,000 (log scale, default $50,000) + editable number input.
- Output line 1 (solid, accent): `At the realized conservative rate (~3.3%): ~$1,650 / year`
  — value = amount × realized_rate (live API, fallback canonical).
- Output line 2 (dashed, amber): `If aggressive targets validate (up to 20%): up to $10,000 /
  year — research stage, not live; max backtest drawdown ~50%` — value = amount × 0.20,
  ALWAYS rendered with the tail clause; the tail is part of the component, not optional copy.
- Toggle year/month. Small print: `Paper-stage. Not an offer. Variable, not guaranteed.` /
  RU `Paper-стадия. Не оферта. Ставка переменная, не гарантирована.`
- RU line 1: `По реализованной консервативной ставке (~3,3%): ~$1 650 / год`; line 2: `Если
  aggressive-цели подтвердятся (до 20%): до $10 000 / год — research-стадия, не live;
  макс. просадка в бэктесте ~50%`.
- `data-track="calc_interact"` on first interaction; `calc_cta_click` on its CTA
  (`Talk to us about your amount` / `Обсудить вашу сумму` → `/pilot?src=calc`).
- Placement: `/packages` bottom + homepage section under tiers. `client:visible`.

**Acceptance:** math exact, both lines always co-rendered (no way to see 20% without the
tail), works without JS = graceful static fallback text. **Verify:** build + manual slider
check EN/RU + analytics event visible in `/api/analytics/*`.

---

## M4 — Live trust/counter strip `[P0][S]` — new `landing/src/components/ProofStrip.astro`

**Goal:** Ethena-style "one live number" band under the hero. Four cells, ALL from live APIs
with per-cell offline fallback (grey "—", never fake):

| Cell | Value | Source |
|---|---|---|
| `Day N of 30 — go-live validation` + progress bar | evidenced days | `/api/v1/golive` (gap_monitor criteria) |
| `0.0% realized drawdown` | evidenced drawdown | `/api/live/safety` |
| `N strategies refused for live capital` | refusal count | `/api/refusal` (or rates-desk refusals count) |
| `Non-custodial · ~45 autonomous monitors 24/7` | static | — |

RU: `День N из 30 — валидация go-live` / `0,0% реализованной просадки` / `N стратегий не
допущено к живому капиталу` / `Non-custodial · ~45 автономных мониторов 24/7`.
Each cell links (track-record / packages#risk / refusals / system) with `data-track`.
Placement: `/` under hero; slim variant on `/packages` and `/pilot`.
**Acceptance:** values live; kill API → cells degrade to "—" individually. **Verify:** build +
temporarily block API host in devtools to see degradation.

## M12 — Countdown as feature `[P0][S]` — same component, fat variant

Progress bar (`N/30`) rendered prominently on `/track-record` top + homepage strip cell, with
caption EN `Aggressive tier unlocks only after 30 evidenced forward days + one real volatility
event. Follow the countdown →` RU `Aggressive-тир откроется только после 30 подтверждённых
forward-дней и одного реального волатильного события. Следи за отсчётом →` → CTA to M7 list.
(Same data source as M4 — build once.)

---

## M7 — Aggressive early-access list `[P0][M]`

**Goal:** Robinhood-pattern scarcity from our REAL gate.

**Backend** (`spa_core/api/routers/interest.py` — extend, don't fork):
- `POST /api/pilot/request` gains optional `source` field (`"pilot" | "early_access" | "checkup_report" | "calc"`), stored in `data/pilot_requests.jsonl` per record.
- Response for `early_access`: `{ok: true, position: <count of early_access records>}`.
- Telegram notify: prefix `[EARLY-ACCESS #<position>]`.
- `/api/pilot/requests/count` returns per-source counts (admin page shows both).
- Tests: extend `spa_core/tests/test_pilot_request.py` (source persisted, position increments,
  no email in count endpoint). Run `pytest spa_core/tests/test_pilot_request.py` green.

**Frontend** (`/packages` aggressive card CTA + `/aggressive-lab` + M12 countdown CTA):
- Form: email only. Button EN `Get the validation report first` RU `Получить отчёт валидации
  первым`. Success state: EN `You're #23 on the list. The day the aggressive book clears its
  gate, the full validation report lands in your inbox first.` RU `Вы №23 в списке. В день,
  когда aggressive-книга пройдёт свой гейт, полный отчёт валидации придёт вам первым.`
- `data-track="early_access_submit"`.

**Acceptance:** submit → Telegram ping with position, jsonl record with source, admin count
split, tests green. **Verify:** pytest + one live test submit (owner's own email) + build.

---

## M9 — /pilot humanization `[P0][S]` — `landing/src/pages/pilot.astro`

- H1 EN: `Talk to the person who built this.` RU: `Поговорите с тем, кто это построил.`
- Sub EN: `30 minutes, no pitch, no obligation. You bring your stablecoin situation; we show
  how the desk would think about it — including what we'd refuse.` RU: `30 минут, без питча и
  обязательств. Вы приносите свою ситуацию по стейблкоинам — мы показываем, как деск думал бы
  о ней, включая то, от чего мы бы отказались.`
- Form gains: `source` (auto from `?src=` param) + holdings-band `<select>`
  (`<$10k / $10–50k / $50–250k / $250k+` — same bands F3 will segment by).
- Prerequisites list: rewrite from "reasons not to bother" into 3 bullets of what they GET.
- Q-OWN (file it): owner name/pseudonym + photo + calendar link; invest@ mailbox to replace
  the personal Gmail on selling pages (UX-17 — grep `gmail` in landing/src and swap when
  answered). Ship copy now, add human block when answered.
**Acceptance:** no jargon in H1/sub; band field flows to jsonl + Telegram. **Verify:** build +
test submit + pytest.

---

## U1–U3 — One-product seam (checkup repo: `defi-checkup`, normal git)

- **U1 Shared chrome `[P0][M]`:** port `SiteHeader`/`SiteFooter` markup + the `:root` token
  block from `landing/src/layouts/Layout.astro` into the checkup app shell (its framework's
  layout component). Nav identical incl. links BACK to earn-defi.com sections + EN|RU toggle.
  Manual sync is acceptable; leave a header comment `SYNC-SOURCE: SPA landing Layout.astro
  <date>` in each ported file.
- **U2 Two-way wiring `[P0][S]`:** verify the shipped earn-defi CTA band (UX-11) renders on
  checkup home, report, AND clean-wallet result; add M8's yield-gap line to it. Dashboard side:
  B-ENTRY hook on `/dashboard` — EN `Want your own portfolio read the same honest way? →
  Run a free Checkup` RU `Хотите, чтобы ваш портфель прочитали так же честно? → Бесплатный
  Checkup` (`data-track="dash_to_checkup"`).
- **U3 One analytics stream `[P0][S]`:** copy the `spaTrack` beacon (Layout.astro:271-295
  pattern) into checkup layout, POSTing to the SAME `https://api.earn-defi.com/api/analytics/
  event` with `page` prefixed `checkup:`. Outbound links landing→checkup append
  `?utm_source=site&utm_campaign=<door>`; beacon already persists UTM per session.
**Acceptance:** side-by-side screenshots indistinguishable chrome; events from checkup pages
appear in `/admin/analytics` alongside landing events. **Verify:** checkup `npx vitest run` +
`npm run build -w @spa/web`; deploy; live click-through both directions.

---

## M6 — Refusal-as-product copy pass `[P1][S]`

Surfaces: homepage (one line under tiers), `/packages` (done in M10), `/aggressive-lab`,
`/refusals` intro. Key line EN: `We publish what we refuse to touch — with a hash-chain proof.
Nobody else does.` RU: `Мы публикуем то, к чему отказались прикасаться — с hash-chain
доказательством. Так не делает никто.` + live refusal count badge (M4 source) linking to
`/refusals` and `/verify`. **Acceptance:** refusal story present on all four surfaces, count
live. **Verify:** build.

## M8 — Checkup report yield-gap + optional capture `[P0][M]` (checkup repo)

At the END of every report AND the clean-wallet result (UX-21):
- Compute `idle = stablecoin balance not earning` (already computed for "Estimated APY").
- Block: EN `Your $31,400 sits idle at 0%. At our realized conservative rate that's ~$1,036/yr
  left on the table. [See how the desk would run it →] [Email me this report]` RU `Ваши $31 400
  лежат без дела под 0%. По нашей реализованной консервативной ставке это ~$1 036/год, оставленных
  на столе. [Как деск работал бы с этим →] [Прислать отчёт на почту]`
- `See how` → `earn-defi.com/packages?src=checkup_report` (UTM per U3).
- `Email me` → optional email → `POST https://api.earn-defi.com/api/pilot/request` with
  `source=checkup_report` (one lead inbox; Telegram ping). First report stays ungated (C3).
**Acceptance:** block renders for dirty AND clean wallets; email optional; lead lands in
jsonl+Telegram. **Verify:** vitest + build + live scan test.

## M11 — Asset-entry cards `[P2][S]` — homepage section

Three cards: `Earn on USDC` / `Earn on idle stables` / `Have an Aave/Compound position?` →
each links to the matching tier/strategy page with one-line situation copy. RU mirror.

---

## N2 — Numbers lint `[P1][S]`

`scripts/lint_canonical_numbers.py` (stdlib): greps `landing/src/{pages,components}` for
banned patterns (`up to \d+%`, `\d+\.\d+% (APY|realized)`, tier-name alt literals) outside
`tier_bands.json`/`canonical_numbers.js`/sample-labeled blocks; allowlist file for justified
hits. **Wire into GitHub Actions CI only — NEVER into the CF Pages prebuild** (prebuild exit-1
freezes deploys silently; incident on record). Start advisory (warn), flip to blocking after
one clean week.

## F1 — Funnel instrumentation `[P0][S]` (day 1, parallel)

Event taxonomy (all via existing `spaTrack`/`data-track`): `view` (auto) ·
`hero_cta_checkup|track` · `compare_aggr_click` · `calc_interact` · `calc_cta_click` ·
`early_access_submit` · `pilot_submit` · `dash_to_checkup` · `checkup:view` ·
`checkup:report_view` · `checkup:yieldgap_click` · `checkup:email_report`.
Confirm `spa_core/api/routers/analytics.py` stores source page + UTM; add per-event counts to
`/admin/funnels`. Capture ≥7 days of baseline BEFORE/while copy ships (don't block shipping).

## F2 — Numeric targets `[P1][S]`

After 2 weeks of F1 data, write `docs/redesign/F2_TARGETS.md`: door→pilot %, snapshot
completion %, early-access signups/week, LCP/CLS budget, lead-quality definition (holdings
band ≥ $50k = qualified). These become the Phase-1 gate numbers.

---

## Sprint exit checklist

- [ ] N1 one number story (grep clean) — EN and RU
- [ ] Hero + CompareBar + ProofStrip + countdown live on /
- [ ] /packages flipped (1 number/chip/line per tier + risk sheets + calc)
- [ ] Calculator on /packages and /
- [ ] Early-access list live end-to-end (form→jsonl→Telegram→admin count) + tests green
- [ ] /pilot humanized + band field; Q-OWNs filed (human block, invest@, U5 domain)
- [ ] Checkup: shared chrome (U1), two-way wiring (U2), unified analytics (U3), yield-gap (M8)
- [ ] Refusal story on 4 surfaces (M6)
- [ ] Lint in CI advisory (N2); funnel events flowing (F1)
- [ ] Every push was build-green, announced, API-pushed; deploys verified by real content
