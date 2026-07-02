# 36 — BTC Capital Cycle Machine (§13)

> **DECISION-SUPPORT ONLY — NOT AUTO-TRADING.** This document describes a **human-approval-gated**
> framework for reasoning about BTC through its market cycle. It is **not a bot**, does **not** hold
> keys, does **not** sign or move funds, and is **not** wired to any execution path
> ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §B, ADR-YL-007). Every allocation change it
> suggests is a **recommendation** that a human reviews and approves. Default autonomy = L0/L1 only.
>
> **No invented numbers.** Every threshold, metric reading, APY, TVL, or price band below is a
> *category / method*, never a live figure. All concrete values are marked `requires verification`
> (`source TBD`). The desk never presents an unverified number as fact.

**Purpose.** BTC is not a yield instrument — it is a **cyclical capital engine**. The edge (if any) is
*discipline*: accumulate when the cycle is cheap and fearful, take profit in ladders when it is
expensive and euphoric, rotate to stables to reduce drawdown, and earn a modest, honest yield *while*
holding — without ever being paid to carry tail risk we cannot underwrite. This file is the
**operational playbook**: 8 phases, each with identification, metrics, confidence, allocation
behavior, and forbidden actions.

**Relationship to existing code.** SPA already ships a deterministic
[`bull_cycle_detector`](../spa_core/strategies/bull_cycle_detector.py) (ADR-018) that classifies the
**DeFi-yield** market (BEAR/NEUTRAL/BULL) from a rolling median APY and sets **tier allocation caps**.
This document is **complementary, not a duplicate**: it reasons about the **BTC price/capital cycle**
(8 phases), not the yield-APY regime. Where a real detector is ever built for this, it must reuse the
determinism, fail-safe-NEUTRAL, and atomic-write discipline of `bull_cycle_detector`, and it likewise
must remain **advisory** (it never overrides the deterministic RiskPolicy or the two-tier kill-switch).
The analytical companion is [`15_btc_cycle_framework.md`](15_btc_cycle_framework.md).

---

## 0. How to read a phase

Each of the 8 phases below is specified with the same fields:

- **How to identify** — the qualitative signature.
- **Metrics to monitor** — the indicators whose *pattern* (not absolute number) flags the phase.
- **Confidence score** — how sure the framework is; low confidence → smaller, slower moves and more
  human review (never a large move on a low-confidence read).
- **BTC allocation behavior / Stablecoin allocation behavior** — directional bias, not a fixed %.
- **Buy / hold / reduce / hedge logic** — the decision rule.
- **Profit-taking ladder / Re-entry ladder** — staged, rules-based, never all-at-once.
- **Hedge rules** — when (and only when) a hedge is considered.
- **Forbidden actions** — hard "never" for the phase.
- **Yield-while-holding-BTC / Yield-while-holding-stables** — the honest, low-risk income options.
- **Emergency rules / Human-approval triggers** — the safety layer.

> The **confidence score** is itself `requires verification` in construction: it is a weighted blend
> of metric agreement, data freshness, and history depth. It is documented here as a *method*, not a
> live value. Low confidence is the default in ambiguous conditions.

---

## 1. Metrics universe (all `requires verification` / `source TBD`)

The framework watches these families of metrics. **None** has a hardcoded trigger level in this
document — each is used for its *pattern and relative position*, and every reading must be pulled from
a verified, freshness-checked feed before use (evidence discipline,
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)).

| Family | Metric | What it tells us | Availability |
|---|---|---|---|
| Valuation / on-chain | **MVRV** (market-value / realized-value) | Aggregate unrealized profit/loss; extreme highs = distribution risk | `requires verification / source TBD` |
| Valuation / on-chain | **NUPL** (net unrealized profit/loss) | Euphoria vs capitulation banding | `requires verification / source TBD` |
| Valuation / on-chain | **Realized price** | Aggregate cost basis; price below = capitulation zone | `requires verification / source TBD` |
| Holder behavior | **LTH behavior** (long-term-holder supply / spending) | Accumulation vs distribution by strong hands | `requires verification / source TBD` |
| Exchange | **Exchange reserves** (BTC on exchanges) | Falling = accumulation/withdrawal to cold; rising = sell-pressure | `requires verification / source TBD` |
| Flows | **ETF flows** (net creations/redemptions) | Institutional demand pulse | `requires verification / source TBD` |
| Derivatives | **Funding rate** | Leverage/positioning bias; extreme positive = froth | `requires verification / source TBD` |
| Derivatives | **Open interest (OI)** | Leverage build-up; OI + price divergence = fragility | `requires verification / source TBD` |
| Derivatives | **Options skew** | Demand for downside vs upside protection | `requires verification / source TBD` |
| Liquidity | **Stablecoin supply** (aggregate) | Dry-powder on the sidelines | `requires verification / source TBD` |
| Macro | **Macro liquidity** (net liquidity proxy) | Risk-asset tailwind/headwind | `requires verification / source TBD` |
| Macro | **DXY** (dollar index) | Inverse risk-appetite proxy | `requires verification / source TBD` |
| Macro | **Rates** (front-end / real yields) | Cost of capital / RWA-floor competition | `requires verification / source TBD` |
| Sentiment | **Sentiment index** (fear/greed) | Crowd positioning extreme | `requires verification / source TBD` |
| Sentiment | **Search trends** | Retail attention pulse | `requires verification / source TBD` |

**No single metric decides a phase.** Phase classification is a *confluence* judgment across families;
a lone extreme metric raises attention and lowers confidence, it does not trigger a move.

---

## 2. The 8 market phases

### Phase 1 — Accumulation

- **How to identify.** Price basing after a prolonged decline; volatility and attention low; strong
  hands quietly adding. The "boring bottom."
- **Metrics.** MVRV/NUPL near or below neutral; price near/under realized price; LTH supply rising;
  exchange reserves falling; stablecoin supply elevated (dry powder); sentiment fearful; low OI/funding.
- **Confidence.** Often *moderate* — bottoms are only obvious later; keep moves staged.
- **BTC allocation behavior.** Bias **up**, slowly, via ladder. This is the preferred zone to build.
- **Stablecoin allocation behavior.** Draw *down* stables gradually to fund the BTC ladder; keep the
  cash buffer intact.
- **Buy / hold / reduce / hedge.** **BUY** (laddered) / hold core / no reduce / no hedge needed.
- **Profit-taking ladder.** N/A (we are building, not distributing).
- **Re-entry ladder.** Staged buys on defined pullback bands (`bands: requires verification`), each
  tranche a fixed fraction of intended add; never deploy the full sidelined stack at once.
- **Hedge rules.** None (hedging a position you are trying to build is self-defeating).
- **Forbidden actions.** No leverage; no all-in; no chasing a green candle; no yield mechanism that
  risks the principal you are accumulating.
- **Yield while holding BTC.** Only honest, near-0 options (see §3): cold storage is the baseline;
  vetted-custody lending only if it does not impair the accumulation thesis.
- **Yield while holding stables.** Park sidelined stables in **RWA T-bills / overcollateralized
  lending** (Preserve tier) so dry powder still earns the floor while it waits.
- **Emergency rules.** If a structural-break invalidates the thesis (e.g. verified exchange-solvency
  event), pause the ladder and escalate.
- **Human-approval triggers.** Any BTC add above the per-tranche size; any draw on the cash buffer.

### Phase 2 — Recovery

- **How to identify.** Price reclaiming key ranges off the base; participation returning; still broadly
  disbelieved.
- **Metrics.** MVRV/NUPL rising off lows; price above realized price; exchange reserves still falling;
  ETF flows turning positive; funding neutral-to-mild-positive.
- **Confidence.** *Moderate → building*.
- **BTC allocation behavior.** Continue the accumulation bias; slow the pace as price rises.
- **Stablecoin allocation behavior.** Continue funding adds, but preserve a larger buffer than in
  deep accumulation (whipsaw risk).
- **Buy / hold / reduce / hedge.** **BUY (smaller tranches)** / hold / no reduce / no hedge.
- **Profit-taking ladder.** N/A yet.
- **Re-entry ladder.** Same laddered rule as Phase 1 with **smaller** tranche sizing as price recovers.
- **Hedge rules.** None.
- **Forbidden actions.** No FOMO up-sizing of tranches as price rises; no leverage.
- **Yield while holding BTC / stables.** Same honest options as Phase 1.
- **Emergency rules.** Failed reclaim → revert to Phase-1 pacing.
- **Human-approval triggers.** Same size/buffer triggers.

### Phase 3 — Early Bull

- **How to identify.** Sustained higher-highs; broad participation; belief returning; the DeFi-yield
  regime may flip BULL in [`bull_cycle_detector`](../spa_core/strategies/bull_cycle_detector.py).
- **Metrics.** NUPL solidly positive but not extreme; OI rising; funding positive; stablecoin supply
  being deployed; ETF inflows steady.
- **Confidence.** *Higher*.
- **BTC allocation behavior.** **Hold the built position.** Adds only on defined pullbacks; the bulk of
  accumulation should already be done.
- **Stablecoin allocation behavior.** Buffer restored to a comfortable level; deploy remaining
  sidelined stables into yield (they are no longer needed as a buying reserve at this pace).
- **Buy / hold / reduce / hedge.** **HOLD** (add on dips) / no reduce / no hedge.
- **Profit-taking ladder.** N/A (early — do not take profit into strength here).
- **Re-entry ladder.** Only on defined pullback bands; small.
- **Hedge rules.** None yet.
- **Forbidden actions.** No selling the core into early strength; no leverage; no chasing.
- **Yield while holding BTC / stables.** Honest options (§3); RWA floor for buffer stables.
- **Emergency rules.** Sharp trend break → downgrade phase, re-check confidence.
- **Human-approval triggers.** Any pullback add.

### Phase 4 — Mid Bull

- **How to identify.** Strong, orderly uptrend; leverage building; the crowd is confident but not yet
  euphoric.
- **Metrics.** MVRV/NUPL elevated; OI and funding elevated; skew tilting toward upside calls; search
  trends rising.
- **Confidence.** *High on trend, rising caution on froth.*
- **BTC allocation behavior.** **Begin the first, small rungs of the profit-taking ladder.** Trim
  *strength*, not the whole position.
- **Stablecoin allocation behavior.** Stables **begin rising** as profit-taking rungs convert BTC to
  cash; that cash goes to the RWA floor.
- **Buy / hold / reduce / hedge.** **HOLD core; REDUCE on the ladder** / consider a *light* hedge only
  if froth metrics spike.
- **Profit-taking ladder.** Staged rungs at defined strength bands (`bands: requires verification`),
  each rung a **fixed small fraction** of the position — never a single large exit.
- **Re-entry ladder.** Only on meaningful pullbacks; sizing modest.
- **Hedge rules.** A **light, decision-support** downside hedge may be *proposed* if funding/OI/skew
  are simultaneously extreme; hedge is small, defined-cost, and human-approved (never a naked
  short-vol structure — see §3).
- **Forbidden actions.** No leverage; no selling the entire position; no naked options selling.
- **Yield while holding BTC / stables.** §3 honest options; rising stables earn the RWA floor.
- **Emergency rules.** Vertical/parabolic acceleration → advance to Phase 5 posture early.
- **Human-approval triggers.** Every ladder rung; any hedge; any leverage request (always denied).

### Phase 5 — Euphoria

- **How to identify.** Parabolic price; universal bullishness; "this time is different"; leverage and
  attention at extremes.
- **Metrics.** MVRV/NUPL in historically extreme bands; funding very positive; OI at extremes; skew
  heavily call-side; search trends spiking; stablecoin supply heavily deployed.
- **Confidence.** *High that risk is elevated* (even if the exact top is unknowable).
- **BTC allocation behavior.** **Accelerate the profit-taking ladder.** This is the primary
  distribution zone for discretionary size above the long-term core.
- **Stablecoin allocation behavior.** Stables **rising materially**; parked in Preserve-tier yield.
- **Buy / hold / reduce / hedge.** **REDUCE (accelerated ladder); HEDGE considered** / no buying.
- **Profit-taking ladder.** Larger, faster rungs at successive extreme bands; still staged, never one
  click.
- **Re-entry ladder.** **Suspended** — do not buy euphoria.
- **Hedge rules.** A defined-cost, human-approved protective hedge is *most* justified here; still
  small, still never naked short-vol, still decision-support only.
- **Forbidden actions.** No new buys; no leverage; no selling protection (no naked calls/puts); no
  "one more leg" thesis-drift.
- **Yield while holding BTC / stables.** Reduce BTC-yield exposure (risk-off); stables to RWA floor.
- **Emergency rules.** If distribution/exhaustion signatures confirm, jump to Phase 6 pacing.
- **Human-approval triggers.** Every accelerated rung; every hedge; any deviation from the ladder.

### Phase 6 — Distribution

- **How to identify.** Price stalling at highs; choppy, lower-highs forming; strong hands selling into
  strength; volatility rising.
- **Metrics.** LTH supply falling (distribution); exchange reserves rising (coins moving to sell);
  NUPL rolling over from extremes; funding whippy; OI unwinding.
- **Confidence.** *Moderate-to-high that the cycle is topping.*
- **BTC allocation behavior.** **Finish the profit-taking ladder** on discretionary size; keep only the
  intended long-term core.
- **Stablecoin allocation behavior.** Stables at their **cycle-high** target; RWA-floor deployed.
- **Buy / hold / reduce / hedge.** **REDUCE remaining ladder; HEDGE core if warranted** / no buys.
- **Profit-taking ladder.** Complete remaining rungs; do not wait for a perfect top.
- **Re-entry ladder.** Suspended.
- **Hedge rules.** Protective, defined-cost, human-approved hedge on the retained core is reasonable
  here; still decision-support, never naked short-vol.
- **Forbidden actions.** No buying the dip *yet* (distribution ≠ accumulation); no leverage; no
  round-tripping realized gains chasing a re-acceleration.
- **Yield while holding BTC / stables.** Minimal BTC-yield risk; stables to RWA floor.
- **Emergency rules.** Confirmed breakdown → Phase 7.
- **Human-approval triggers.** Every remaining rung; every hedge.

### Phase 7 — Early Bear

- **How to identify.** Confirmed downtrend; lower-highs and lower-lows; disbelief that the top is in;
  bounces sold.
- **Metrics.** NUPL falling toward neutral; exchange reserves elevated; funding negative-leaning;
  sentiment souring; macro-liquidity/DXY/rates possibly headwind.
- **Confidence.** *Moderate-to-high on trend-down.*
- **BTC allocation behavior.** **Hold long-term core only.** Do not average down early — bear markets
  are long.
- **Stablecoin allocation behavior.** Stables **high**, earning the RWA floor; this is the "dry powder
  rebuild" phase.
- **Buy / hold / reduce / hedge.** **HOLD core; no adds** / hedge may remain / no leverage.
- **Profit-taking ladder.** Done (from Phases 4–6).
- **Re-entry ladder.** **Not yet armed** — wait for capitulation signatures before laddering back in.
- **Hedge rules.** An existing protective hedge may be held/rolled per rules; no new speculative shorts.
- **Forbidden actions.** No catching the knife; no leverage; no revenge-buying; no yield mechanism that
  risks principal in a falling market.
- **Yield while holding BTC / stables.** Conservative only; stables to RWA floor.
- **Emergency rules.** Cascade/liquidation event → preserve capital, do not deploy into the cascade.
- **Human-approval triggers.** Any add (should be denied this phase); any hedge change.

### Phase 8 — Capitulation

- **How to identify.** Sharp, high-volume flush; maximum fear; price under aggregate cost basis;
  forced selling.
- **Metrics.** Price below realized price; MVRV/NUPL in capitulation bands; exchange reserves spiking
  then reversing; sentiment at extreme fear; funding deeply negative.
- **Confidence.** *Moderate* — capitulations can extend; ladder, don't lunge.
- **BTC allocation behavior.** **Arm the re-entry ladder.** Begin *small* staged buys into fear — this
  is where Phase-1 accumulation begins again.
- **Stablecoin allocation behavior.** Begin deploying sidelined stables into the BTC ladder while
  keeping the cash buffer.
- **Buy / hold / reduce / hedge.** **BUY (small, laddered); remove hedges into the flush** / hold core.
- **Profit-taking ladder.** N/A.
- **Re-entry ladder.** Staged buys at successive fear/valuation bands (`bands: requires verification`),
  small tranches; capitulations overshoot, so keep reserve for lower rungs.
- **Hedge rules.** Protective hedges are *closed* into capitulation (their job is done); no new shorts.
- **Forbidden actions.** No all-in bottom-calling; no leverage; no deploying the cash buffer itself.
- **Yield while holding BTC / stables.** Honest options resume slowly; stables still to RWA floor until
  deployed.
- **Emergency rules.** If capitulation is driven by a **structural** failure (verified protocol/custody
  collapse, not just price), **do not buy** — escalate; the thesis may be broken, not merely cheap.
- **Human-approval triggers.** Every re-entry tranche; every hedge removal; any cash-buffer draw.

---

## 3. Yield-while-holding options (honest, low-risk)

The desk's posture ([`33_yield_thesis_map.md`](33_yield_thesis_map.md) Domain B): **"yield on BTC" is
mostly small or tail-compensation.** These are decision-support overlays on *already-held* assets,
never a reason to take principal risk with the cycle position.

**While holding BTC:**
- **Cold storage / self-custody baseline** — zero yield, minimal counterparty risk. Often the correct
  answer (see [`15_btc_cycle_framework.md`](15_btc_cycle_framework.md) §"cold storage beats yield").
- **BTC lending** — honest **~0% APY** (`requires verification`); BTC is rarely borrowed on-chain.
  SPA ships read-only `tbtc_lending` / `cbbtc_lending` advisory adapters
  ([`spa_core/adapters/btc_lending.py`](../spa_core/adapters/btc_lending.py)). **WBTC excluded**
  (governance overhang, `requires verification`); **LBTC-restaking REFUSED** (points/airdrop-leverage).
- **BTC basis / cash-and-carry / funding capture** — real in bull regimes but **CEX-leg is custody /
  legal gated and off-code**; decision-support only, isolated, red-team required.
- **BTC covered calls** — option premium = **short-vol tail-comp**; **REFUSE naked**; only ever a
  small, defined, human-approved overlay on already-held BTC in Phases 4–6, never leveraged.

**While holding stablecoins:**
- **RWA tokenized T-bills** — the honest **Preserve floor** (`≈ requires verification`); the default
  home for sidelined dry powder.
- **Overcollateralized lending (Aave/Spark/Compound/Euler)** — real borrow-demand yield, Preserve→Core,
  RiskPolicy-capped (TVL ≥ $5M, per-protocol/T2 caps).
- **Morpho vaults / stable LP (base fees)** — Core; curator / incentive-split due-diligence required
  before any claim.

> Every yield option above is subordinate to the deterministic **RiskPolicy** and the two-tier
> **kill-switch** ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §A). None of them may be
> auto-executed by this framework.

---

## 4. Global emergency & human-approval layer

**Emergency rules (all phases):**
- A **structural-failure** signal (verified custody/exchange/protocol collapse, oracle failure, chain
  halt) **overrides phase logic**: preserve capital, do not deploy, escalate to a human immediately.
- The framework **cannot** override the deterministic RiskPolicy or the two-tier kill-switch, and never
  tries to.
- Fail-safe default is **HOLD / do-nothing** on ambiguous or stale data — never a large move on a
  low-confidence or stale read (mirrors `bull_cycle_detector`'s NEUTRAL fallback).

**Human-approval triggers (all phases):**
- Any BTC↔stable rotation beyond a defined per-tranche size.
- Any hedge open/close/roll.
- Any draw on the minimum cash buffer.
- Any phase transition that changes the directional bias (BUY→REDUCE or REDUCE→BUY).
- **Any leverage request → automatically denied** (leverage is forbidden across all phases here).

**Forbidden actions (global, all phases):**
- No private-key handling, no signing, no fund movement, no autonomous execution.
- No leverage; no naked short-vol (naked calls/puts); no points/airdrop-leverage yield.
- No presenting paper/backtest cycle-timing as live performance; no invented metric readings.

---

## 5. Cross-references

- Analytical companion (metrics, valuation, confidence math, BTC yield-risk detail):
  [`15_btc_cycle_framework.md`](15_btc_cycle_framework.md).
- Yield-source honesty for every BTC mechanism: [`33_yield_thesis_map.md`](33_yield_thesis_map.md)
  Domain B.
- Existing deterministic yield-regime detector (complementary, not duplicated):
  [`bull_cycle_detector`](../spa_core/strategies/bull_cycle_detector.py) / ADR-018.
- Evidence discipline for any number this framework surfaces:
  [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md).
- Hard invariants this framework must never violate:
  [`06_spa_core_invariants.md`](06_spa_core_invariants.md).

---

*Decision-support framework, human-approval-gated, advisory. Not auto-trading (ADR-YL-007). No
private keys, no signing, no fund movement. All metric/APY/price values are categories or method
descriptions marked `requires verification` — none is a live figure.*
