# ADR-533: Three DeFi paper portfolios — different mechanics, own versions, one status read model

- **Status:** ACCEPTED · 2026-10-01 · owner: @yurii (owner epic «THREE DEFI PAPER PORTFOLIOS — STRATEGY
  MECHANICS, OPERATIONS AND WEBSITE», autonomous execution authorised in it; package A–D of ADR-532 NOT
  approved by it)
- **Builds on:** ADR-530 (audit), ADR-531 (sleeve-econ-v2), ADR-532 (defi_engine foundation).
- **Not changed:** RiskPolicy v1.0, every protocol tier label, every limit and stop of the main book, the
  Conservative track (never reset), live capital (0), the Trading Research Engine. No new agent.

## Owner requirement

Conservative, Balanced and Aggressive are three separate PAPER portfolios. They must:
- differ by investment MECHANIC, not only by protocol tier;
- each carry its own version, accounting, limits and observable state;
- be shown truthfully on the site and in the Director;
- keep their history and the explanation of every decision.

## Audit before the change (2026-10-01, live tree)

| | Conservative | Balanced | Aggressive |
|---|---|---|---|
| Executes | allocator → RiskPolicy, stablecoin supply | sleeve: top-4 floating stablecoin supply | sleeve: top-2 floating supply, 60 % cap |
| Process / schedule | `com.spa.daily_cycle`, daily | `com.spa.hy_cycle`, hourly, one accounting row a day | `com.spa.lp_cycle`, hourly, one row a day |
| Book | `current_positions.json` + `equity_curve_daily.json` | `hy_paper_trading.json` | `lp_paper_trading.json` |
| Strategy version | none recorded | `hy_cycle_v1.2` (code), none in rows | `lp_cycle_v1.2` (code), none in rows |
| Accounting version | ADR-298 main book | `sleeve-econ-v2` boundary set by the first v2 row, 2026-10-02 | same |
| Last run / row | 17:24Z / 2026-10-01 | 19:55Z / 2026-10-01 (v1 row) | 19:55Z / 2026-10-01 (v1 row) |
| Last decision | CIO HOLD (gain 0.084 pp < 0.5 pp, payback 109 d) | ENTER, no moves | no moves |
| Positions / cash / debt | 5 legs, $5k cash, no debt | 4 legs, no cash field, no debt | 2 legs, no cash field, no debt |
| Site status source | shelf `site_numbers` (weekly) → `packages.astro` | same | same |
| UI branch saying "not running" | — | `packages.astro:106` «restarted… no corrected days yet» | same |

The two sleeves were RUNNING with no recorded strategy version. Balanced and Aggressive were the SAME
mechanic: floating stablecoin supply.

## Decision

**Three mandates** (`spa_core/paper_trading/strategy_mandates.py`). Each mandate carries:
- strategy id and version, plus the accounting version recorded separately;
- yield source and instruments;
- entry, hold and exit rules, and the cost model;
- limits and stop;
- roles and references.

| Package | Mechanic (version) | What is new |
|---|---|---|
| Conservative | `conservative-lending-v1`: unlevered T1/T2 supply under RiskPolicy | nothing changes in its book; the mandate is recorded. Its mismatches with the mandate's "clear yield and exit" preference (maple: 14-day redemption queue, 20 % of the book) are SHOWN, not traded away |
| Balanced | `balanced-fixed-carry-v1`: Pendle PT bought at a discount and held to maturity (≤ 40 % of equity, ≤ 25 % per market) next to floating supply | `pt_carry.py`: PT legs marked at the OBSERVED PT price, accepted only when it agrees with the implied-APY price (0.5 %); redeemed at par at expiry; yield is earned only through the price |
| Aggressive | `aggressive-susde-loop-v1`: a SIMULATED sUSDe-collateral / PYUSD-debt loop on Morpho Blue market `0x90ef…` (LLTV 0.915), ≤ 50 % of the book, next to concentrated supply | `loop_book.py` (below) |

**How `loop_book.py` models the loop:**
- **collateral** = units × the market's own oracle price;
- **debt** = Morpho borrow shares × borrow share price, grown by the observed rate since `lastUpdate`;
- **HF / LTV** are recomputed every hourly run;
- **deleverage** at HF < 1.15, **unwind** at HF < 1.08 or implied USDe < 0.97;
- **liquidation** simulated with Morpho Blue's LIF formula, bad debt named;
- **stress** scenarios: depeg 5/10/20/30 %, borrow spike, zero yield;
- **entry** only when the levered carry, after round-trip cost, beats the unlevered yield by 1 pp.

**Data — primary sources, quorum, third outcome:**
- `onchain_read.py`: read-only `eth_call`, 2-witness quorum over public RPCs;
- `morpho_market.py`: market params, state, oracle price, sUSDe share price, all on-chain. The borrow APY comes from the Morpho API and DeFiLlama, which must agree;
- `pendle_market.py`: the Pendle active list plus each market's observed PT price.

Any missing input ⇒ `ok=False` with a reason. The model then holds and does not value at an invented price.

**Experiments:**
- A change of mechanic opens a new experiment in the SAME canonical book: `ensure_experiment` is idempotent and records the explicit initial state.
- Earlier rows are untouched and stay in the closed `<package>-legacy-lending` experiment.
- Published figures count only the current experiment's rows (`generate_track_snapshot._sleeve_paper_track`).

**Evidence of scheduled runs:** `paper_observations.py` writes one line per run and hour slot. A re-run in the same slot appends nothing, and missed hours are visible as gaps.

**Replay:** the sleeve archive records the mechanic sub-book. `sleeve_replay` re-derives its close value from the recorded legs and inputs, and checks that floating part + sub-book = book equity.

**One read model:** `defi_engine/package_status.py`. Each package carries:
- **work:** NOT_STARTED / RUNNING / PAUSED / FAILED;
- **data:** HEALTHY / WAITING_FOR_DATA / DEGRADED / HOLD, with the reason;
- **history:** WARMUP / ACCUMULATING / REPORTABLE (30), counted for the CURRENT version only;
- the running version vs the installed version that is waiting for its first row.

The site snapshot (`package_status`) and the Director (`render_defi`) read this one model.

**Roles** (one implementation, configured per package; no new agent):
- opportunity scan;
- net economics;
- position simulation;
- risk & stress;
- debt supervision;
- liquidity / exit;
- portfolio supervision;
- independent review.

## First measured decisions (live inputs, 2026-10-01 ~20:30Z)

- **Balanced:** PT-sUSDS-26NOV2026 (`0x9c56…`). Implied 4.886 %, observed price 0.99277 against implied-derived 0.99282 (a 0.005 % gap), liquidity $4.84 M. It is eligible against a floating benchmark of ≈5.4 %, minus 1 pp. Sandbox day 1 bought $24.8 k, capped at 25 % per market.
- **Aggressive:** yield 5.29 % (live sUSDe) against borrow 4.73 %. Morpho API and DeFiLlama agree, at 90.3 % utilisation. The levered net is 5.65 %, below the 6.29 % hurdle, so the loop HOLDs with that reason. The mechanic runs and supervises; it does not enter for a better-looking status.

## Phase-1 package A–D (ADR-532) — re-split, not executed

| Item | Kind | Status |
|---|---|---|
| A: `ethena_susde` = `susde` (pool 66985a81) | data / identity fact (same pool measured) | label change is still a tier decision → owner |
| A: `moonwell_base` T3 | class score 0.75 after the Nov-2025 hack vs canon 0.45 — an evidenced inconsistency | tier decision → owner |
| A: `stusd`, `usual_usd0pp` T3 | NO evidence beyond a stricter copy | **withdrawn** — T3 is not assigned without evidence |
| A: `policy_enforcer` T1 for `aave_v3_base` / `morpho_steakhouse` | risk-policy (final validator) | owner |
| B: Conservative 3 % | public promise vs trigger | the published "≤3 %" is a target band, held by no trigger. A halt-new trigger at 3 % would NOT guarantee a loss ≤ 3 %. Either the wording changes (subject №2) or a trigger is added (risk policy) → owner |
| C: RTMR liquidity scopes and rate sensor | main-book de-risk ladder | owner. The new paper mechanics carry their OWN supervision in this ADR: loop HF every hour, PT mark confirmation |
| D: delta-neutral from mechanic | sleeve check | unchanged. The loop is supervised by HF and depeg, not by the stamp |

## Production evidence (2026-10-01 → 2026-10-02)

| Step | Evidence |
|---|---|
| Delivery | `1ddd16fc` (mechanics, read model, Director), `f1ee13cb` (backup of run evidence), `979de337` (Balanced benchmark fix), `aeaea66b` + `e1fcb643` (site); code sync 21:34Z, `deployment_acceptance` OK |
| First scheduled runs | 2026-10-01 21:55Z: observations in `data/paper_observations/{balanced,aggressive}.jsonl` (Pendle ok, Morpho ok) |
| New versions start | 2026-10-02 00:55Z, first accounting rows: `balanced-fixed-carry-v1@2026-10-02` and `aggressive-susde-loop-v1@2026-10-02`; Aggressive loop ENTERED (borrow 4.20 %, sUSDe 5.30 %, levered net 6.51 % ≥ hurdle 6.29 %; HF 1.307; debt $116,692; collateral $166,703; cost $119.55) |
| Idempotence + restart | 00:59Z `launchctl kickstart -k` both sleeves in the same hour slot: no 2nd row, no 2nd loop entry, no 2nd observation; state survived |
| Second scheduled run | 01:59Z slot T01 both books; loop supervised (HF 1.307145, LTV 0.70, measured) |
| Old history | Balanced/Aggressive: 39 earlier rows kept in the closed `*-legacy-lending` experiment; Conservative track not touched (101 evidenced days) |
| Site | `/packages` after JS: three statuses from the read model (RU and EN), versions + experiment dates, last run, data state with a natural-language reason, PAPER; strategy pages describe the actual mechanics; owner gate CLEAN |

**Defect found by the first production decision:** Balanced refused PT-sUSDS against a floating
benchmark of 7.34 % made by `aave_v3` at 12.59 % (a jumping series the book does not hold). The benchmark
is now the HELD floating legs' weighted yield (5.04 % that day); the corrected rule decides first on the
2026-10-03 row.
