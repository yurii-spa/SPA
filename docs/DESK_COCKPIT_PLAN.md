# Desk Cockpit — Reality Map + Sprint-0 Execution Plan

> Senior-architect grounding of the owner's «Desk Cockpit» PRD against SPA's REAL backend.
> READ-ONLY analysis + the Sprint-0 hard gate. Screens are NOT built here — this is the map + the gate.
>
> **Verdict up front:** the Cockpit is a genuinely great fit. SPA's whole identity already IS
> refusal / kill / attribution / risk-first, so the doctrine matches the desk. **~80% of the data
> contract already exists** in the backend and is served over `api.earn-defi.com`. Sprint 0 is
> therefore **mostly a RESHAPE + a primitives library**, NOT a from-scratch backend. The three
> genuinely-new backend pieces are: (1) a unified Decision+Refusal read-facade, (2) per-condition
> Kill-Gauge headroom, (3) the realtime `/stream` producers. Everything else is reshape or rename.

---

## 0. Source-of-truth anchors (what I read)

| Area | Authoritative file(s) |
|---|---|
| Portfolio/NAV | `spa_core/api/routers/misc.py` (`/api/portfolio`), `routers/live.py` (`/api/live/portfolio`), `data/paper_trading_status.json`, `equity_curve_daily.json`, `current_positions.json` |
| Kill / safety | `spa_core/governance/kill_switch.py` (4 triggers + two-tier), `routers/live.py::/api/live/safety`, `data/{kill_switch_status,derisk_status}.json` |
| Decisions/Refusals | `spa_core/strategy_lab/rates_desk/{proof_chain,rate_policy,refusal_engine}.py`, `data/rates_desk/decision_log.jsonl`, `data/refusal_status.json`, DFB `routers/dfb*.py` |
| Attribution | `spa_core/strategy_lab/forward_analytics.py` → `data/forward_analytics.json`, `routers/optimizer.py::/api/captured-book` |
| Exit-NAV | `spa_core/strategy_lab/rates_desk/exit_nav.py` → `data/rates_desk/exit_nav.json`, `/api/rates-desk/exit-nav` |
| Regime | `spa_core/analysis/market_regime.py` → `data/market_regime.json` (written by cycle_runner); `/api/tier1/regime` |
| Tournament/strategies | `routers/tournament.py`, `routers/strategy_lab.py` (`/api/strategy-lab`, `/promotion`) |
| Backtest | `routers/misc.py::/api/backtest*`, `routers/tier1.py::/api/tier1/*`, `spa_core/backtesting/` |
| Realtime | `spa_core/api/agent_broadcaster.py`, `routers/misc.py` (`/ws/agents`, `/api/events` SSE), `_shared.py::EventQueue` |
| UI kit | `landing/src/components/ui/{tokens,kit.jsx,riskStyles,index}.js`, `.astro` primitives; `landing/src/components/DashboardLive.jsx`; `landing/src/pages/dashboard.astro` |
| Freshness convention | `routers/live.py` — `_fetched_at`(epoch) + `stale`(bool) + `NO_CACHE_HEADERS`; proof endpoints use `generated_at`/`as_of` |

---

## 1. THE REALITY MAP — Cockpit contract → SPA reality

Legend: **✅ HAVE** (exists, cite it) · **◐ PARTIAL** (exists, reshape/field-add needed) · **⛔ GAP** (build).

### 1.1 Contract objects / endpoints

| Cockpit object → endpoint | Status | SPA reality (cite) | Gap / reshape |
|---|---|---|---|
| **PortfolioSnapshot** `/api/portfolio` | ✅ HAVE | `misc.py::get_portfolio` + `live.py::/api/live/portfolio` merge `paper_trading_status`+`equity_curve_daily`+`current_positions`. Fields: `total_capital_usd, deployed_usd, cash_usd, cash_pct, total_pnl_usd, total_return_pct, apy_pct, real_track_days`. | Add `ts`+`stale` to the `misc.py` variant (only `/api/live/*` stamps freshness today). Rename-map to `nav`/`delta` in the primitive, not the backend. |
| **StrategySnapshot[]** `/api/strategies` + `/{id}` | ◐ PARTIAL | `/api/strategy-lab` rows: `id, name, mandate, net_apy_pct, max_drawdown_pct, sharpe, beta_to_eth, funding_drag_pct, beats_rwa_floor, killed, kill_reason, yield_basis`. `/api/tournament` leaderboard (Sharpe-ranked, `paper_apy`). | No `/{id}` detail route (only aggregate). `/api/strategy-lab/{id}` = **thin new route** (filter existing list). No rename of data. |
| **Position / Fill** `/api/positions/{id}` | ◐ PARTIAL | `/api/positions` (list) + `current_positions.json` (23 positions). **SPA is PAPER → there are no fills**; "positions" = the virtual book, "fills" = `trades.json` (ring-buffer 500) via `/api/trades`. | No `/{id}` route. Reshape: PositionTable reads `/api/positions`; the "Fill" concept maps to `/api/trades`. Honest label: *paper book, no on-chain fills*. |
| **Decision + Refusal** `/api/decisions` + `/api/refusals` | ◐ PARTIAL | **Rates-Desk already unifies both in ONE log**: `data/rates_desk/decision_log.jsonl` (`kind∈{ENTRY,REFUSAL}`, hash-chained) via `/api/rates-desk/decisions` + `/api/rates-desk/refusals` + `/api/rates-desk/proof`. Per-underlying verdicts: `/api/refusal` (`refusal_status.json`, SAFE/WATCH/REFUSE/UNKNOWN). DFB refusals: `/api/dfb/v1/refusals`, alerts: `/api/dfb/alerts`. | **No cross-desk unified stream.** ≥5 independent emitters, 3 incompatible chain formats. GAP = a read-only **aggregator facade** `/api/decisions` + `/api/refusals` that merges rates-desk + DFB into one normalized shape. NOT a new emitter — a reshape/merge layer. |
| **TournamentState** `/api/tournaments/{id}` | ✅ HAVE | `/api/tournament` (`mass_results.leaderboard`, `tournament.ranked_strategies/top_5`, `meta.rank_metric`), `/api/tournament/status`. | Single tournament today → `{id}` is cosmetic. Rename in primitive. |
| **BacktestResult** `/api/backtests/{id}` | ◐ PARTIAL | `/api/backtest/summary` (`total_return_pct, sharpe_ratio, max_drawdown, win_rate, best_day, worst_day`), `/api/backtest/replay` (per-day frames), `/api/backtest/compare`, `/api/tier1/{monte-carlo,walk-forward,nav,packages}`. | `/api/backtest` (base) is a **deprecated synthetic stub** — do not use. No per-id route. Reshape onto `summary`+`replay`. Tier1 files are pipeline-shaped (not strongly typed). |
| **Regime** `/api/regime` | ⛔ GAP (data ✅) | `data/market_regime.json` written every cycle: `regime∈{STABLE,HIGH_YIELD,COMPRESSED_YIELD,VOLATILE}`, `t1_avg_apy, recommendation, detected_at`. Also `/api/tier1/regime` (backtest regime, `current`+`labels`). | The **live** regime file has **no endpoint**. GAP = a 15-line `/api/regime` passthrough (verbatim + `_fetched_at`/`stale`). Trivial. |
| **`/stream`** (SSE/WS push: nav/delta/kill/decision/refusal/funding) | ⛔ GAP (transport ✅) | SSE `/api/events` + WS `/ws/agents` EXIST, backed by `_shared.py::EventQueue` + `agent_broadcaster.py`. But they carry **only canned agent-activity/thought/snapshot** events. Nothing pushes nav/kill/decision/refusal. | Transport is reusable as-is (`event_queue.push({type,...})` fans out any dict). GAP = **producers**: cycle_runner/kill_switch/rates-desk tick must call `event_queue.push()`. Sprint-0 can defer this → **poll @15s first (already works), stream later**. |
| Envelope: every response carries `ts` + `stale` | ◐ PARTIAL | `/api/live/*` stamps `_fetched_at`+`stale`+`NO_CACHE_HEADERS`. Proof/advisory endpoints use `generated_at`/`as_of`. | GAP = normalize. Cockpit primitive **StaleGuard** should read BOTH idioms (`_fetched_at||generated_at`, `stale` derived from age). Reshape at the read layer, not a backend rewrite. |

### 1.2 Signature UI primitives → existing components

| Primitive | Status | Basis in SPA | Notes |
|---|---|---|---|
| **MetricStat** | ◐ | `DashboardLive.jsx::Metric` + `kit.jsx` | Promote `Metric` → shared `ui/kit.jsx` (it's re-defined inline today). |
| **StaleGuard** | ⛔ | freshness convention exists (`_fetched_at`/`stale`) but no wrapper | New primitive: wraps any panel, greys + flags when stale. Small. |
| **TimeToggle** | ⛔ | `equity_curve_daily.json` has full daily series (`date, close_equity, evidenced, drawdown_pct`) | New primitive (7d/30d/all window selector). Pure client. |
| **EquityChart** | ◐ | `DashboardLive.jsx` hand-rolls inline SVG (`Ring`, `Bar`); **no chart lib** (no recharts). Data: `equity_curve_daily.json`. | Build a hand-rolled SVG line chart. **MUST honor `evidenced` flag** — warmup/backfill bars rendered differently (honesty identity). |
| **KillGauge** | ◐ | `/api/live/safety` gives state+tier+reason; `kill_switch.py` computes `evidenced_drawdown_pct` + thresholds (SOFT 5% / HARD 10%). | Value/threshold/headroom **per condition** = ◐: drawdown headroom is computable NOW (dd% vs 5/10), but Sharpe/red-flags headroom is not exposed → see SPA-002. |
| **AttributionWaterfall/Bar** | ✅ | `/api/captured-book::attribution` = `floor_leg_usd + carry_leg_usd = realized_pnl_usd` (`reconciles:true`). Full 3-bucket + combined book in `forward_analytics.json`. | Data literally reconciles to a total → a real waterfall. Only unserved piece = `combined_book_attribution` (add to endpoint, SPA-001-lite). |
| **RiskStrip** | ✅ | `/api/risk` (`violations, warnings, var_usd, var_pct`), `/api/governance`, `/api/live/safety`. | Reshape into a compact strip. |
| **DecisionFeed** | ✅ | `/api/rates-desk/decisions` (ENTRY+REFUSAL rows, chained). | Reshape via the SPA-001 aggregator for cross-desk. |
| **RefusalFeed** (signature) | ✅ | `/api/rates-desk/refusals`, `/api/refusal`, `/api/dfb/v1/refusals`. Hash-chained, publicly verifiable (`/api/rates-desk/proof`). | **Already a public refusal log** (existing `/refusals` page). Cockpit reshapes it. |
| **RegimeBadge** | ◐ | data in `market_regime.json`; needs `/api/regime` (SPA-002). | Trivial once endpoint lands. |
| **PositionTable** | ✅ | `/api/positions` + `Table.astro`/`kit`. | Reshape. Label paper book honestly. |
| **LiqNavTierChart** (signature basis) | ✅ | `/api/rates-desk/exit-nav::schedule` = per-**ticket-size** rows (`$100k…$10M`) with `net_proceeds_usd, haircut_pct, price_impact_frac, time_to_exit_days, flagged`. | **This IS LiqNAV-by-size already** (ticket ladder, not AUM tier — honest naming: "exit NAV by ticket size"). Existing `/exit-nav` page. |
| **TournamentLeaderboard** | ✅ | `/api/tournament` leaderboard. | Reshape. |

### 1.3 Honest scorecard

- **Genuinely new backend/telemetry (owner/backend-gated or real code):** `/api/decisions`+`/api/refusals` cross-desk aggregator (SPA-001), Kill-Gauge per-condition headroom (SPA-002), `/stream` producers (SPA-003, deferrable). That's it.
- **Trivial new routes (passthrough, ~15 lines each):** `/api/regime`, `/api/strategies/{id}`, serve `combined_book_attribution`.
- **Pure reshape / rename of existing served data:** Portfolio, Tournament, Positions, Attribution, Exit-NAV, RiskStrip, RefusalFeed, DecisionFeed.
- **Pure frontend (primitives):** MetricStat, StaleGuard, TimeToggle, EquityChart, KillGauge, waterfall, badges — all hand-rolled SVG/CSS on the existing `tokens.js`/`kit.jsx` foundation (no new charting dep).

---

## 2. SPRINT 0 — THE HARD GATE (concrete plan)

Sprint 0 delivers the **data contract + the primitives library** so every later screen is assembly, not
research. Split into a **telemetry/schema lane** (SPA-001/002/003, backend, read-only) and a
**primitives lane** (SPA-004/005, frontend). The two lanes are **independent → parallel agents**.

### Lane A — Telemetry / schema (backend, read-only, stdlib, fail-closed)

**SPA-001 — Unified Decision+Refusal read-facade** `/api/decisions`, `/api/refusals`
- New router `spa_core/api/routers/cockpit.py` (or extend `misc.py`). **READ-ONLY aggregator** — merges
  existing sources into ONE normalized shape; emits nothing, changes no emitter:
  - rates-desk `decision_log.jsonl` (`kind, ts, underlying, approved, reason, net_edge, entry_hash`),
  - DFB `/api/dfb/v1/refusals` + `/api/dfb/alerts`,
  - per-underlying `refusal_status.json`.
- Normalized row: `{desk, kind(ENTRY|REFUSAL|ALERT), ts, subject, verdict, reason, size_usd?, hash?, source}`.
- Carry `ts`+`stale` (age of newest row). Fail-closed: missing source → that desk absent, never 500.
- **Buildable now** (read-only reshape). No owner gate.

**SPA-002 — Kill-Gauge per-condition headroom** `/api/live/safety` (extend) or `/api/kill/gauge`
- `kill_switch.py` already computes `evidenced_drawdown_pct` + thresholds. Add a READ-ONLY derive that,
  per condition, returns `{condition, value, threshold, headroom, unit, tier}`:
  - drawdown: `value=dd%`, `threshold=5/10`, `headroom=threshold−dd` ✅ computable now,
  - sharpe: `value=real_sharpe`, `threshold=effective` (needs ≥30 evidenced bars → else `UNKNOWN`),
  - red_flags: `value=critical-on-held count`, `threshold=5`,
  - manual: boolean.
- Fail-closed: THIN/UNKNOWN when insufficient evidenced data (never fabricate headroom). Extend
  `/api/live/safety` with a `conditions[]` array (backward-compatible add).
- **Buildable now** — pure derive over existing `kill_switch.py` functions. No new risk logic.

**SPA-003 — `/stream` (SSE) — nav/kill/decision/refusal/funding push** *(DEFERRABLE past Sprint 0)*
- Transport EXISTS (`_shared.py::EventQueue` + SSE `/api/events`). Two-step:
  1. Producers: cycle_runner (nav/regime), `run_kill_switch_check`/`run_derisk_check` (kill/derisk edge),
     rates-desk tick (decision/refusal) call `event_queue.push({type, ...})`.
  2. New `/api/stream` SSE generator filtering by `type`.
- **Sprint-0 decision: SHIP POLL-FIRST.** DashboardLive already polls @15s and works. Stream is a
  latency upgrade, not a blocker. Schedule SPA-003 AFTER S1 lands. (New owner flag: none — reuses
  existing transport; producers are read-only emitters into an in-memory queue.)
- **`/api/regime` + `/api/strategies/{id}` + serve `combined_book_attribution`** — fold these 3 trivial
  passthroughs into SPA-001's router (same PR, ~40 lines total).

### Lane B — Primitives library (frontend, extends existing ui-kit)

**SPA-004 — Cockpit primitives on the existing design system**
- Foundation is `landing/src/components/ui/{tokens.js,kit.jsx,riskStyles.js}` — the Cockpit primitives
  EXTEND this, never fork it. Map:
  - `MetricStat` → promote `DashboardLive::Metric` into `ui/kit.jsx` (shared).
  - `StaleGuard` → new wrapper reading `_fetched_at||generated_at`+`stale`.
  - `RegimeBadge`, `RefusalFeed`/`DecisionFeed` row → `StatusPill` + `VERDICT_TONE` (already maps
    SAFE/WATCH/REFUSE/HARD/SOFT).
  - `RiskStrip`, `PositionTable`, `TournamentLeaderboard` → `Table.astro`/`kit` + tones.
- **Constraint:** DashboardLive currently re-defines `Panel/Metric/Chip/Ring` inline with a LOCAL
  hardcoded tone map that DIVERGES from `tokens.js`. Sprint 0 **converges** these onto `tokens.js`
  (kill the local rgba map) so the Cockpit and the existing dashboard render identically.

**SPA-005 — The 3 signature primitives (hand-rolled SVG, no new dep)**
- `KillGauge` — arc/gauge per kill-condition from SPA-002 `conditions[]` (value/threshold/headroom,
  tone by tier). Inline SVG (like existing `Ring`).
- `RefusalFeed` — the public refusal log (SPA-001 REFUSAL rows), with the hash/`verified` badge from
  `/api/rates-desk/proof` ("don't trust us, check us" identity).
- `AttributionWaterfall` — floor_leg + carry_leg → total from `/api/captured-book` (`reconciles` badge).
- Charting: **hand-rolled inline SVG** (no recharts — package.json has none; matches current approach).
  `EquityChart` MUST style `evidenced:false` bars distinctly (warmup ≠ real track).

### Sprint-0 exit gate (the hard gate — all must be green)
1. `/api/decisions` + `/api/refusals` return a merged normalized feed with `ts`+`stale` (SPA-001). ✅ testable.
2. `/api/live/safety` exposes `conditions[]` with per-condition headroom, THIN-safe (SPA-002). ✅ testable.
3. `/api/regime`, `/api/strategies/{id}`, `combined_book_attribution` served (SPA-001 fold). ✅ testable.
4. Primitives library exists in `ui/kit.jsx` + renders on `tokens.js` (MetricStat, StaleGuard, KillGauge,
   RefusalFeed, AttributionWaterfall, EquityChart, RegimeBadge, PositionTable) — Storybook-less smoke page.
5. DashboardLive local tone map converged onto `tokens.js` (no divergent rgba).
6. Poll-first works (15s); `/stream` explicitly deferred with a written follow-up. 
- Every endpoint: read-only, fail-closed, never-500, `stdlib`-only backend, `_fetched_at`/`stale` stamped.

---

## 3. THE HONEST SCOPE CALL

**This is a multi-sprint build.** Sprint 0 is the leverage point: nail the contract + primitives once,
then every screen S1–S7 is assembly. Recommended order, mapped to SPA reality:

| Order | Screens | SPA reality | Lane |
|---|---|---|---|
| **Sprint 0 (gate)** | contract + primitives | ~80% reshape; 3 real backend items (SPA-001/002/003) | A ∥ B parallel |
| **S1 — Desk Dashboard** | portfolio + kill + regime + attribution + refusal | ALL data exists (`/api/portfolio`, `/api/live/safety`+headroom, `/api/regime`, `/api/captured-book`, `/api/decisions`) | single lane after gate |
| **S2 + S5 — Strategies + Risk** | `/api/strategy-lab` + `/api/tournament` + `/api/risk` + `/api/governance` | exists; S2 & S5 share the RiskStrip/leaderboard primitives → parallelizable | 2 lanes |
| **S3 — Decisions/Refusals** | the public refusal log + proof chain | exists + verifiable (`/api/rates-desk/proof`, verify_spa.py) | 1 lane |
| **S4 — Exit-NAV / LiqNAV** | `/api/rates-desk/exit-nav` ticket ladder | exists (existing `/exit-nav` page to fold in) | 1 lane |
| **S7 + S6 + realtime** | backtest views + `/stream` upgrade | `/api/backtest/summary`+`replay` (avoid the synthetic `/api/backtest` stub) + SPA-003 producers | last (stream is polish) |

**Parallel-agent lanes:** Lane A (backend telemetry) ∥ Lane B (primitives) in Sprint 0. Post-gate, S2∥S5
and S3∥S4 each split cleanly (disjoint endpoints, shared primitives already built).

**Where SPA's real constraints bite (be honest):**
- **Paper, no real positions:** Position/Fill = the *virtual paper book* (`current_positions.json`) + paper
  *trades* (`trades.json`), NOT on-chain fills. The UI must label this honestly ("paper book").
- **THIN track (evidenced ~7–16/30, $0 external capital):** many metrics are UNKNOWN/THIN by design.
  KillGauge Sharpe headroom, DSR, etc. must render `UNKNOWN` fail-closed — never a fabricated number.
  This is the identity, not a bug.
- **`evidenced` flag is load-bearing:** EquityChart/TimeToggle must visually separate evidenced real bars
  from warmup/backfill (`equity_curve_daily.json::daily[].evidenced`). A warmup peak must never look like
  real track (the N1 kill-switch lesson, applied to the UI).
- **Realtime:** `/stream` reuses the existing `EventQueue`/broadcaster transport — but nothing feeds it
  decisions/kill today. Poll @15s ships first; stream is a later latency upgrade, not a Sprint-0 blocker.
- **Fragmented chains:** decisions/refusals live in ≥5 emitters / 3 chain formats. The Cockpit does NOT
  unify the *emitters* (out of scope, risky) — it unifies the *read view* (SPA-001 aggregator). Honest.

**Identity fit (why this is the right build):** the desk's doctrine — idle = positive («capital parked»,
not «doing nothing»), fail-closed UI, no gamification, refusal/kill/attribution front-and-center — maps
1:1 onto SPA's existing honesty posture (refusal log, two-tier kill, evidenced-only track, THIN→UNKNOWN,
public proof chain). The Cockpit is the presentation layer SPA's substance has been waiting for.

**NEW owner flags:** none required for Sprint 0 (all read-only reshape). One to *surface later*: whether
`/stream` should push kill/decision edges (adds live producers into the in-memory queue — benign, but it
touches cycle_runner/kill_switch call sites → worth an explicit go before S7/realtime).

---

*Written by the senior-architect grounding pass. Sprint 0 = SPA-001 (unified decision/refusal facade +
regime/strategy-id/combined-attribution folds) ∥ SPA-002 (per-condition kill headroom) on Lane A;
SPA-004/005 (primitives on tokens.js, 3 signature elements) on Lane B. SPA-003 (/stream) deferred
poll-first. Execute top-to-bottom.*
