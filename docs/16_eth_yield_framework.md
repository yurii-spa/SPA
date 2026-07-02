# 16 — ETH Yield Framework (§15)

> **DECISION-SUPPORT ONLY — NOT AUTO-TRADING.** This is a **research and recommendation** framework for
> reasoning about ETH yield and ETH cycle rotation. It holds no keys, signs nothing, moves no funds, is
> not wired to any execution path, and never overrides the deterministic RiskPolicy or the two-tier
> kill-switch ([`06_spa_core_invariants.md`](06_spa_core_invariants.md), ADR-YL-007). Default autonomy =
> L0/L1 (research / recommendation only).
>
> **No invented numbers.** Every APY, TVL, peg, queue length, and reward figure below is a *category or
> method* marked `requires verification` / `source TBD`. The desk never presents an unverified number as
> fact ([`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)).

**Purpose.** ETH is unusual: unlike BTC, it carries a **real, durable base yield** (staking). This file
frames how the desk researches that yield honestly — native staking, liquid staking (LST), liquid
restaking (LRT), and the derivative/rotation strategies around ETH — and, critically, **when NOT to
chase ETH yield**. It is the ETH companion to the BTC framework in
[`15_btc_cycle_framework.md`](15_btc_cycle_framework.md) and draws its yield-source honesty from
[`33_yield_thesis_map.md`](33_yield_thesis_map.md) Domain C.

**Relationship to existing code.** SPA already runs the **`eth_lst_neutral`** sleeve in
[`spa_core/strategy_lab/`](../spa_core/strategy_lab/) — a **β≈0 hedged** book that pairs **plain LST**
(stETH/rETH, *not* LRT) spot with a short ETH-perp. The desk deliberately prefers **plain LST over LRT**
for the safe neutral sleeve (LSTs sit closer to peg → smaller depeg residual when hedged). The
directional/LRT variants (`variant_n` hedged, `variant_d` directional) are studied as **isolated,
research-only** sleeves. This document is the analytical framing around those sleeves; it does not
change their code or wiring.

---

## 1. ETH yield mechanisms (honest, by yield source)

### 1.1 Native staking
- **Yield source.** Real ETH staking rewards: consensus issuance + priority fees + MEV.
- **Who pays.** The Ethereum protocol + block-space demand.
- **Category.** Preserve → Core (real base yield), `requires verification`.
- **Why it can disappear.** Staking rate falls as participation rises; slashing; validator-set
  dynamics.
- **Risks.** **Slashing** (correlated-failure / operator risk); **validator exit / withdrawal queue**
  length under stress; operational (key management is *off-code* for the desk — non-custodial invariant).
- **Posture.** Real and durable, but native staking implies validator operations the desk does **not**
  custody; in practice accessed via LST (below).

### 1.2 Liquid staking (LST — stETH / rETH)
- **Yield source.** Same real staking rewards, tokenized and liquid.
- **Category.** Preserve → Core (real base yield), `requires verification`.
- **Risks.** **LST/ETH de-peg** (secondary-market discount under stress); **withdrawal-queue** length;
  smart-contract risk; operator concentration.
- **Posture.** The **preferred** ETH base-yield instrument; safe leg of the `eth_lst_neutral` sleeve.

### 1.3 Liquid restaking (LRT — eETH etc.)
- **Yield source.** Staking yield **+ restaking/AVS rewards + points** — much of the excess is
  **speculative / incentive**, not real economic yield.
- **Category.** Enhanced → Max (mostly incentive/speculative), `requires verification`.
- **Risks.** **Additional slashing surface** (restaking rehypothecates stake to secure AVS services);
  **de-peg** (LRTs de-peg *more* than LSTs); **points-farming trap** (points may never convert);
  thinner secondary liquidity → harder to hedge cleanly.
- **Posture.** **Conditional REFUSE.** LRT excess over LST is largely incentive/tail-comp. Isolated,
  research-only; the desk prefers plain LST for hedged books
  ([`33_yield_thesis_map.md`](33_yield_thesis_map.md) C2).

### 1.4 ETH lending
- **Yield source.** Borrow demand for ETH.
- **Category.** Preserve → Core — real but **modest** (utilization-dependent), `requires verification`.
- **Risks.** Low utilization → low APY; smart-contract; oracle; withdrawal freeze under stress.

### 1.5 ETH as collateral
- **Nature.** **Not yield** — a liquidity unlock (borrow stables against ETH).
- **Risk.** **Liquidation** on an ETH drawdown; adds liquidation risk to any stable-side deployment it
  funds. Treated as a risk overlay, not an income source.

### 1.6 ETH basis / cash-and-carry / funding capture
- **Yield source.** Spot–future basis / perp funding, delta-neutral.
- **Category.** Enhanced → Max (regime-dependent), `requires verification`.
- **Risks.** **Basis compression**; **funding reversal** (flips negative); **CEX-leg is custody / legal
  gated and off-code**; hedge-break; counterparty.
- **Posture.** Decision-support only; isolated; funding-kill logic and red-team required before any
  paper approval. (The desk's `rates_desk` `BASIS_HEDGE` shape is **BLOCKED-NO-HEDGE** — CEX leg not
  built.)

### 1.7 ETH covered calls / options
- **Yield source.** Option premium (selling upside) = **short-vol tail-comp**.
- **Category.** Enhanced (premium-dependent), `requires verification`.
- **Risks.** **Caps upside in a rally**; vol crush; assignment; venue/counterparty.
- **Posture.** **REFUSE naked.** Only ever a small, defined, human-approved **overlay** on already-held
  ETH; never leveraged.

### 1.8 ETH DeFi yield (LP / vaults on ETH)
- **Yield source.** Trading fees + incentives on ETH-denominated pools/vaults.
- **Category.** Core (base fees) → Enhanced (with incentives), `requires verification`.
- **Risks.** Impermanent loss; incentive cliff (subsidy ≠ sustainable yield — must be split out);
  smart-contract; underlying-asset de-peg.
- **Posture.** Base-fee vs incentive split mandatory before any claim
  ([`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)).

---

## 2. Cross-cutting ETH risks

| Risk | What it is | Where it bites |
|---|---|---|
| **Smart-contract risk** | Bug/exploit in LST/LRT/lending/LP contracts | Every on-chain ETH-yield mechanism |
| **Validator risk** | Slashing / operator failure / correlated downtime | Native staking, LST, LRT (LRT adds AVS slashing) |
| **Bridge risk** | Cross-chain bridge exploit / freeze | Bridged ETH / wrapped forms / L2 deployments |
| **Liquidity risk** | Thin secondary market → cannot exit at fair value | LRT (thinner than LST); exiting hedged legs; withdrawal queues |
| **De-peg risk** | LST/LRT trades below ETH under stress | LST (small residual), **LRT (larger residual)** |
| **Withdrawal-queue risk** | Native unstake is queued, not instant | Native staking, LST redemption under stress |
| **EigenLayer-like restaking risk** | Rehypothecated stake → extra slashing surface + unproven AVS rewards | LRT / restaking |
| **Funding / basis risk** | Funding flips negative; basis compresses | ETH basis / funding-capture sleeves |

Every mechanism above is subordinate to the deterministic RiskPolicy and the two-tier kill-switch, and
none may be auto-executed by this framework.

---

## 3. ETH cycle rotation (decision-support)

Rotation is **relative-value cycle timing**, **not a yield source** — treated exactly like the BTC
cycle framework: staged, rules-based, human-approved, never automated.

- **ETH/BTC rotation** — relative-value timing between the two majors; disappears/fails on mistiming or
  regime change. Decision-support framework only (`bands: requires verification`).
- **ETH/stable rotation** — de-risk / re-risk timing (rotate ETH↔stables to manage drawdown); risk is
  whipsaw / mistiming. Decision-support only.
- **Phase alignment.** ETH cycle phases broadly track the 8 BTC phases in
  [`36_btc_capital_cycle_machine.md`](36_btc_capital_cycle_machine.md) (accumulation → … →
  capitulation); ETH tends to be **higher-beta** than BTC, so allocation bands are *wider* and profit /
  re-entry ladders are staged with that in mind. Concrete band edges are `requires verification`.
- **Idle stables** from any rotation earn the honest **RWA floor** (Preserve;
  [`33_yield_thesis_map.md`](33_yield_thesis_map.md) A10), not a tail-comp mechanism.

Rotation recommendations require the same **human-approval triggers** as BTC (per-tranche size limits,
any hedge, any buffer draw, any bias flip); **leverage is denied** across all rotation logic.

---

## 4. When NOT to chase ETH yield

Do **not** reach for ETH yield when:
- The excess APY is **incentive / points / tail-comp** rather than real economic yield — the LRT case:
  restaking rewards are unproven and points may never convert. Prefer plain LST.
- It requires **additional slashing surface** (restaking) for a spread you cannot underwrite.
- It requires **leverage** or **naked short-vol** (both forbidden here); covered calls only as a small,
  human-approved overlay on held ETH.
- The mechanism forces exposure to a **thin secondary market** or an **unhedgeable de-peg residual**
  (LRT under stress).
- The CEX leg of a basis/funding trade is **custody/legal-gated and off-code** — the hedge is not
  actually built (the desk's basis shape is currently BLOCKED-NO-HEDGE).
- The feed is `requires verification` with no reproducible source, or the claim would exceed its
  evidence level ([`37`](37_apy_realism_and_evidence_standard.md)).

**Prefer, in order:** plain **LST staking** (real base yield) → **ETH lending** (modest, real) →
**ETH DeFi base fees** (incentive-split disclosed) → **hedged neutral sleeve** (`eth_lst_neutral`,
β≈0, isolated) — and hold the honest **RWA floor** on idle stables rather than manufacture ETH yield
that is really tail-comp.

---

## 5. Cross-references

- Existing hedged ETH sleeve (plain-LST + short-perp, β≈0):
  [`spa_core/strategy_lab/`](../spa_core/strategy_lab/) `eth_lst_neutral` (and `variant_n` / `variant_d`
  research-only).
- Yield-source honesty for every ETH mechanism: [`33_yield_thesis_map.md`](33_yield_thesis_map.md)
  Domain C.
- BTC cycle framework (parallel decision-support, phase alignment):
  [`15_btc_cycle_framework.md`](15_btc_cycle_framework.md),
  [`36_btc_capital_cycle_machine.md`](36_btc_capital_cycle_machine.md).
- Evidence discipline: [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md).
- Invariants: [`06_spa_core_invariants.md`](06_spa_core_invariants.md).

---

*Decision-support / research framework, advisory only. Not auto-trading (ADR-YL-007). No private keys,
no signing, no fund movement, no override of RiskPolicy or kill-switch. All APY/TVL/peg/reward values
are categories or method descriptions marked `requires verification` — none is a live figure.*
