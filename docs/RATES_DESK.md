# SPA Rates Desk — on-chain rates / basis sleeve (validated thesis-#1)

**Status:** validated build — Phase-0 `FixedCarry` is **GO** and runs as a live (paper) forward track.
ADVISORY ONLY: simulates carry, moves **no live capital**, never touches the go-live track.
**Date:** 2026-06-26 · **Module:** `spa_core/strategy_lab/rates_desk/` · **Doc deps:** `docs/RATES_DESK_DERISK.md`
(the §8 de-risk), `docs/RATES_DESK_VALIDATION.md` (the two verdicts).
**Conventions:** stdlib-only, deterministic, **LLM-FORBIDDEN** in risk/kill, **fail-CLOSED** (missing/invalid
data raises or scores as MAX tail-risk — never a silent pass), atomic writes (`spa_core.utils.atomic`).

---

## The thesis (validated)

The edge is a **risk-adjusted fair-value model for tokenized yield** that **(a) harvests genuinely-mispriced
carry** and **(b) REFUSES yield that is just tail-risk compensation** (the ezETH / over-levered-USDe pattern).
The question before any capital — *does the risk engine separate "real excess spread" from "tail-comp you'll
pay back"?* — was answered **yes** over the real 2024-06 → 2026-06 history (see Validation below).

---

## The engine (data flow)

```
feeds.build_surface(as_of)            → live fixed/implied-rate RateSurface
  (Pendle PT / lending / Boros quotes + per-underlying UnderlyingRisk + honest hedge_available map)
        │
        ▼
FairValueEngine (fair_value_engine.py)
  kind-aware baseline (LST=staking yield; LRT=staking ONLY — restaking premium NOT in baseline)
  minus 5 STRUCTURAL haircuts → fair implied yield  → YieldDecomposition (gross/baseline/haircut/net)
        │
        ▼
REFUSAL-FIRST gate (rate_policy.py: evaluate_entry / evaluate_hold)
  composes UNDER the global spa_core.risk.policy.RiskPolicy — only ever MORE restrictive.
  REFUSES when net edge ≤ 0 / tail-risk too high / TVL or exit-liquidity floor / no hedge where required.
  Continuous hold-kill (negative-funding streak, depeg, drawdown) → KillState.
        │
        ▼
OpportunityEngine.scan(surface, risks, as_of)
  enumerates the FOUR trade shapes per underlying, computes gross/net edge + exit-bound raw size,
  ranks by net_edge. NO risk veto here (that is the gate's job) — only shape feasibility + economics.
```

All decisions (ENTRY **and** REFUSAL) are hashed into the **proof chain** (`proof_chain.record_decisions`)
— the public "what we traded AND what we refused + why" record.

---

## The four trade shapes (`contracts.TradeShape`)

| shape | id | what | status |
|---|---|---|---|
| A | `FIXED_CARRY` | buy PT, hold to maturity — lock a fixed rate | **VALIDATED (GO) — the live-paper sleeve** |
| B | `LEVERED_CARRY` | borrow stable, buy PT — amplify the spread | research-only (gated leverage) until it clears the gate |
| C | `BASIS_HEDGE` | PT long vs forward-funding short — isolate the basis | **BLOCKED-NO-HEDGE — deferred** (CEX-leg not built) |
| D | `RATE_MATRIX` | cross-venue rate-arbitrage rotation (argmax venue, anti-churn hysteresis) | research-only until it clears the gate |

Sleeves (`sleeves.py`, all `Strategy` ABC, `IS_ADVISORY=True`, gated by `rate_policy`): `FixedCarrySleeve`
(Phase-0, GO) + Phase-1 `BasisHedgeSleeve` / `LeveredCarrySleeve` / `RateMatrixSleeve`.

---

## Feeds (`feeds.py`, keyless, fail-CLOSED)

- **Pendle PT** (`PENDLE_PT`) — fixed-rate principal-token quotes; `pendle_pt_history.py` paginates the
  keyless endpoint for the deep history used by the backtest/validation.
- **Lending** (Aave/Morpho-class) — supply-rate quotes (`include_lending` toggle).
- **Boros** (`BOROS`) — forward-funding venue used as the hedge / forward reference; `hedge_available` is an
  **honest per-underlying** map (false where no real hedge exists → BASIS_HEDGE is correctly BLOCKED).
- A surface with no usable `PENDLE_PT` quote is a **gap**, not a fabricated point.

`UnderlyingKind`: `LST` (stETH/rETH → baseline = staking yield) vs `LRT` (ezETH/rsETH → baseline = staking
ONLY; the restaking premium is deliberately NOT in the baseline, so it shows up as tail-comp the gate refuses).

---

## Validation verdict (`docs/RATES_DESK_VALIDATION.md`)

Two deterministic verdicts over the **real cached 2024-06 → 2026-06 data** + the three stress events:

- **Assertion 1 — REFUSAL fired early → PASS.** Every toxic LRT PT book (ezETH-style) was refused, and the
  refusals were **structural** (haircut-driven), not noise — across the deep real history.
- **Assertion 2 — survivor book beats the floor → GO.** The survivor carry book beats the ~3.4% RWA floor
  **risk-adjusted across the full deep window** (real stress + multiple maturities) in-sample, out-of-sample,
  and in every stress window → **carry leg is real → fundable.**
  - *Note:* locked held-to-maturity carry has near-zero downside variance by construction, so its Sharpe is
    structurally inflated (degenerate) — it is reported as a **not-noise** check only; the GO rests on the
    realized book APY beating the floor across stress, not on a vanilla Sharpe.

`FixedCarry` is therefore the **only** sleeve registered in the live paper service; the rest stay research-only
until they clear the gate (`BasisHedge` is BLOCKED-NO-HEDGE).

---

## The live paper service + agent

`spa_core/strategy_lab/rates_desk/paper_rates.py` paper-trades the validated `FixedCarry` sleeve on the LIVE
rate surface, one tick at a time, into a growing forward carry track.

> **THE captured FixedCarry book.** `data/rates_desk/paper/` is the **single, canonical** captured-paper
> book for the FixedCarry edge — there is exactly **one** capture abstraction (this service). A second,
> derivative reader (`spa_core/paper_trading/sleeve_capture.py`, which re-accrued a parallel bounded book
> off this state) was **deleted 2026-06-28** as a redundant ghost: it was never wired (no agent, no
> `data/captured_sleeves/`, never run) and would have created a divergent second equity number for the same
> edge. Per-sleeve capture lives in each paper service (`paper_rates.py`, `strategy_lab/paper.py`, hy/lp
> cycles); do **not** reintroduce a parallel capture layer on top of them.

- **CLI (one tick):** `python3 -m spa_core.strategy_lab.rates_desk.paper_rates`
- **Restart-survival:** the sleeve book + cash + accrued state is snapshotted to disk after each tick and
  restored on the next start — a relaunch CONTINUES the book rather than zeroing it (frozen Decimal book is
  serialized as a compact JSON-safe snapshot and rebuilt on restore).
- **Idempotent per UTC day:** re-ticking the same calendar day restores the stored pre-tick snapshot and
  replays the single tick → never double-accrues.
- **Fail-CLOSED:** if `build_surface` raises or yields no usable PT quote → no advance, no fabricated point, a
  gap is recorded (and Telegram-alerted), the prior state is left untouched.
- **Proof chain:** every tick feeds entries AND refusals into `proof_chain.record_decisions`.

**Agent:** `com.spa.rates_desk_paper` — `scripts/com.spa.rates_desk_paper.plist`, miniconda python, **hourly**
(`StartInterval 3600`, mirrors `com.spa.strategy_lab_paper`), `RunAtLoad`, restart-survivable. Registered in
`scripts/install_all_agents.sh` (item 22c). Logs → `logs/rates_desk_paper.log` / `.err`.

A separate daily **refusal scorer** — `com.spa.refusal` →
`python3 -m spa_core.strategy_lab.rates_desk.refusal_engine` — scores every tracked underlying from live data
into `data/refusal_status.json` (SAFE / WATCH / REFUSE / UNKNOWN), 05:45 local, advisory.

### State written (`data/rates_desk/paper/`, atomic)
| file | what |
|---|---|
| `rates_desk_fixed_carry_state.json` | restart-survival book snapshot + pre-tick snapshot + meta |
| `rates_desk_fixed_carry_series.json` | growing forward track (equity / net_apy / open-closed books / approvals / refusals), ring-buffer 400 |
| `status.json` | latest tick status (date, gap, sleeve equity / net_apy / last_tick) |

---

## Forward-record analytics + fundability

The hourly `FixedCarry` forward track (`rates_desk_fixed_carry_series.json`) is measured by the
shared **`spa_core/strategy_lab/forward_analytics.py`** scorecard (see `docs/STRATEGY_LAB.md` for the
full module). It is the only track with a held PT carry book, so the **T5 stress overlay** is
attached to it: the canonical 2024–2026 PT mark-down shocks are applied to the *currently-held* book
(read from `rates_desk_fixed_carry_state.json`) on top of the realized forward equity, reporting
per-scenario stressed drawdown + `survives` against the promotion band (`MAX_DD_BAND_PCT = 15%`, NO
looser than the gate). The **T4** scorecard reports the realized APY + attribution vs the ~3.4% RWA
floor and, **honestly**, `UNKNOWN` Sharpe/Sortino until the track reaches `MIN_POINTS_FOR_RATIO`
(7 equity points) — locked held-to-maturity carry has near-zero downside variance, so a vanilla
Sharpe there is a degenerate artifact, never reported as a number. The forward track is ~3–6 days
today → metrics are UNKNOWN by design until ~day 30 (target **2026-07-21**).

The scorecard (`data/forward_analytics.json`) feeds `docs/FUNDABILITY.md` via
`scripts/generate_fundability_onepager.py`. Promotion follows the canonical
`PROMOTION_CRITERIA` in `spa_core/tournament/tournament_engine.py` (Sharpe ≥ 1.5 · ≥ 7 paper days ·
APY ≥ 3% · DD ≥ −15%); `BASIS_HEDGE` stays **BLOCKED-NO-HEDGE** off-ladder (asserted end-to-end in
`spa_core/tests/test_promotion_ladder_e2e.py`).

---

## API (`spa_core/api/server.py`)

| endpoint | what |
|---|---|
| `GET /api/rates-desk/surface` | current `RateSurface` — quotes + per-underlying risk + hedge_available map |
| `GET /api/rates-desk/opportunities` | the four shapes ranked by net_edge (pure scan, no risk veto) |
| `GET /api/rates-desk/decisions?limit=N` | recent decision log incl. REFUSALS, each with its `proof_hash` |
| `GET /api/refusal` | per-underlying daily tail-risk verdict (SAFE / WATCH / REFUSE / UNKNOWN) |

All handlers are read-only and graceful (empty payload, never a 500, when the JSON is absent/corrupt).

---

## Build phases — done vs deferred

| phase | what | status |
|---|---|---|
| De-risk (§8) | risk scorer + fair-value + 2 retro tests over cached history | **DONE** (`docs/RATES_DESK_DERISK.md`) |
| Phase-0 | `RateSurface` + `FairValueEngine` + refusal-first gate + `FixedCarrySleeve` (A) | **DONE — VALIDATED GO** |
| Phase-1 validation | 4-sleeve replay + Assertion 1/2 over deep real data | **DONE** (`docs/RATES_DESK_VALIDATION.md`) |
| Live paper | hourly `FixedCarry` forward track + agent + proof chain | **DONE — this build** |
| `BASIS_HEDGE` (C) | PT long vs forward-funding short | **DEFERRED — BLOCKED-NO-HEDGE** (CEX / Boros leg not built; honest `hedge_available=false`) |
| `LEVERED_CARRY` (B) / `RATE_MATRIX` (D) | gated leverage / cross-venue rotation | research-only until each clears the gate |

---

*Updated 2026-06-26 — initial architecture doc for the validated thesis-#1 rates-desk build + the new
`com.spa.rates_desk_paper` live-paper agent.*
