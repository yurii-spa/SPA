# 44 — Research: First 20 Strategies (§41)

**Purpose.** This is the desk's opening research roster — the first 20 strategies to study, in
priority order and grouped by domain and product line. For each it records **why research it first**,
its **yield source**, its **main risk**, the **first data to collect**, its **product-line fit**, its
**capital-tier fit**, and whether it is **MVP-testable** now. It is the concrete work queue that
operationalizes the Yield Thesis Map ([`33_yield_thesis_map.md`](33_yield_thesis_map.md)) under the
unified mandate ([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).

**Reading rules.**
- **No invented numbers.** No APY or TVL is asserted here. Any concrete figure lives in a Strategy Card
  at MVP 2-3 with an evidence level (L0–L6, [`37`](37_apy_realism_and_evidence_standard.md)); here every
  such figure would be `requires verification`.
- **Listing ≠ approval.** Every candidate must pass the full Yield Lab lifecycle
  ([`07_yield_lab_lifecycle.md`](07_yield_lab_lifecycle.md)) — yield-source verification, protocol /
  stablecoin review, liquidity review, Risk Scoring v2 (advisory), red-team, paper-test, human approval
  — before any live use. Capital preservation first (charter).
- **Ordered by honesty, not by yield.** The roster starts at the RWA floor benchmark and works outward;
  every Enhanced/Max entry is evaluated as **spread over the live floor, fully risk-explained**
  ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)), never as absolute APY.
- **Where SPA already implements a mechanism**, the entry cross-references the module so research
  extends existing work rather than duplicating it ([`02_current_architecture_audit.md`](02_current_architecture_audit.md)).

**Cross-references:** [`07_yield_lab_lifecycle.md`](07_yield_lab_lifecycle.md),
[`33_yield_thesis_map.md`](33_yield_thesis_map.md),
[`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md),
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md),
[`43_dangerous_strategies.md`](43_dangerous_strategies.md), existing `spa_core/strategy_lab/` and
`spa_core/adapters/`.

**"MVP-testable?"** means: can this be paper-tracked (L3) *now* on live, keyless-or-available data
through the existing harness, without off-code infrastructure (CEX custody, legal, options venues)?
"Yes" = data + mechanism are already reachable; "Partial" = data exists but a leg/gate is missing;
"No — off-code" = requires custody/legal/venue not yet built.

---

## Stablecoin — Conservative (Preserve / Core)

### 1. T1 lending (blue-chip money markets)
- **Why research first.** The deepest, most-audited on-chain base yield; it anchors every lower tier and is already live read-only in SPA — the fastest path to a validated card.
- **Yield source.** Borrow demand (variable supply rate) — real interest from on-chain borrowers ([`33`](33_yield_thesis_map.md) A1).
- **Main risk.** Contract exploit / oracle failure; utilization spike freezing withdrawals; governance.
- **First data to collect.** Live reserve rate, utilization, TVL per pool (DeFiLlama + adapter feeds), exploit/governance history.
- **Product-line fit.** Preserve / Core. · **Capital-tier fit.** $100k → $100M+ (cap-bounded; scales toward the ~$50–100M core ceiling, [`34`](34_capital_tiers_strategy.md) §1).
- **MVP-testable?** **Yes** — read-only adapters already exist (`spa_core/adapters/`); L3 paper track is immediate.

### 2. Tokenized T-bill / RWA cash floor
- **Why research first.** It is the **official baseline** ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)) — every other strategy is judged as spread over this floor, so it must be measured live first, not assumed.
- **Yield source.** Real T-bill coupon (US Treasury interest, passed through by the issuer) — real economic yield ([`33`](33_yield_thesis_map.md) A10).
- **Main risk.** Issuer default; custody chain; redemption freeze; regulatory reclassification.
- **First data to collect.** Live tokenized-T-bill rate, TVL-weighted, per-issuer backing + redemption terms (`data/rwa_feed.py`, ≈3.4% `requires verification`).
- **Product-line fit.** Preserve (the benchmark). · **Capital-tier fit.** $100k → $100M+ (capacity rarely binding).
- **MVP-testable?** **Yes** — `rwa_sleeve` + `data/rwa_feed.py` already implement the live floor.

### 3. Blue-chip savings vaults (audited, transparent)
- **Why research first.** Passive core yield with a clear, disclosed yield source and strong audit coverage; a natural next step above raw lending.
- **Yield source.** Underlying borrow demand / savings-rate mechanism, wrapped in an audited vault (transparent backing).
- **Main risk.** Vault/curator misconfiguration; underlying-market risk; contract risk.
- **First data to collect.** Vault rate, allocation/curator config, underlying market, audit reports, TVL.
- **Product-line fit.** Core. · **Capital-tier fit.** $100k → several $M.
- **MVP-testable?** **Partial** — data is reachable via existing feeds; needs a protocol/curator card before paper-tracking (curator DD not yet carded, [`33`](33_yield_thesis_map.md) A3).

### 4. Short-duration stable LP (correlated stable pairs)
- **Why research first.** Low-IL liquidity provision at the core tier; earns real trading fees with limited depeg surface if pairs stay correlated — a bounded first LP study.
- **Yield source.** Trading fees on stable-to-stable swaps (base fees; incentive portion flagged separately) ([`33`](33_yield_thesis_map.md) A9).
- **Main risk.** Depeg of a pool asset (impermanent loss becomes permanent); incentive cliff; contract risk.
- **First data to collect.** Pool balances, fee APR vs emissions APR (base-vs-incentive split), peg spread of pool assets, exit depth.
- **Product-line fit.** Core (base fees) → Enhanced (with incentives). · **Capital-tier fit.** $100k → several $M.
- **MVP-testable?** **Partial** — Aerodrome LP adapter exists (read-only); base-vs-incentive carding pending before an honest paper track.

---

## Stablecoin — Balanced (Core / Enhanced)

### 5. Curated lending markets (isolated, whitelisted collateral)
- **Why research first.** An enhanced rate over T1 with *bounded* collateral (isolated markets), letting the desk study incremental spread with a contained risk surface.
- **Yield source.** Borrow demand in an isolated market with whitelisted collateral ([`33`](33_yield_thesis_map.md) A3, curated variant).
- **Main risk.** Curator misallocation; collateral quality; underlying-market fragility; contract risk.
- **First data to collect.** Curator identity + allocation limits, collateral whitelist + LTVs, underlying-market depth, rate history.
- **Product-line fit.** Core / Enhanced. · **Capital-tier fit.** $100k → several $M.
- **MVP-testable?** **Partial** — feeds reachable; requires a curator card + spread-attribution before promotion.

### 6. PT fixed-rate (principal token to maturity)
- **Why research first.** Deterministic fixed carry, hold-to-maturity, and **already validated** as the desk's thesis #1 — the reference for a fully risk-explained Enhanced strategy.
- **Yield source.** Fixed implied rate locked by buying the principal token at a discount ([`33`](33_yield_thesis_map.md) A4).
- **Main risk.** Underlying-yield-source failure; thin secondary liquidity to exit before maturity; contract risk; toxic underlyings (LRT PTs).
- **First data to collect.** Pendle market data, PT/YT prices, maturity, underlying-yield feed, PT pool depth per maturity (capacity is the binding constraint).
- **Product-line fit.** Enhanced (validated). · **Capital-tier fit.** small–mid (capacity cliff ~$1–2M at larger sizes, [`34`](34_capital_tiers_strategy.md) §1).
- **MVP-testable?** **Yes** — implemented and live-paper as **FixedCarry** in `spa_core/strategy_lab/rates_desk/` (refusal-first gate).

### 7. Diversified stable LP with fee capture
- **Why research first.** Balanced yield from *real trading fees* across diversified stable pools; extends #4 to study fee capture as the durable (non-subsidy) component.
- **Yield source.** Trading fees (real volume) + optional incentives (flagged as subsidy) ([`33`](33_yield_thesis_map.md) A9).
- **Main risk.** Depeg → permanent loss; volume dries; emission cliff; contract risk.
- **First data to collect.** Fee APR vs emission APR per pool, volume durability, peg spreads, exit mechanics.
- **Product-line fit.** Core / Enhanced. · **Capital-tier fit.** $100k → several $M.
- **MVP-testable?** **Partial** — adapters + feeds exist; needs the base-vs-incentive split carded (mandatory, [`37`](37_apy_realism_and_evidence_standard.md) rule 5).

### 8. Staked-stable / savings-rate wrappers (transparent backing)
- **Why research first.** Yield from a *disclosed* mechanism (e.g. tokenized savings rate) — a clean case for verifying "who pays and why" before touching opaque wrappers.
- **Yield source.** Disclosed savings-rate / borrow-demand mechanism behind a transparent wrapper.
- **Main risk.** Mechanism change (rate can be set to 0 by governance); backing quality; contract risk. Note the SPA invariant: **Sky/sUSDS = 0%** until GSM Pause Delay ≥ 48h confirmed on-chain ([`06`](06_spa_core_invariants.md)).
- **First data to collect.** The disclosed backing + rate mechanism, governance control over the rate, redemption terms, attestation.
- **Product-line fit.** Preserve / Core. · **Capital-tier fit.** $100k → $100M+ (mechanism-dependent).
- **MVP-testable?** **Partial** — data reachable; gated by the specific-mechanism verification (e.g. the Sky pause-delay condition).

---

## Stablecoin — Enhanced (Enhanced)

### 9. Basis / funding carry (delta-neutral, hedged)
- **Why research first.** Real basis yield exists and is a canonical Enhanced mechanism; researching it early forces the desk to build the funding feed and the funding-kill discipline before ever sizing it.
- **Yield source.** Perp funding + spot–derivative basis on a delta-neutral book ([`33`](33_yield_thesis_map.md) A6/A7).
- **Main risk.** Funding flips negative; CEX counterparty / custody; collateral depeg; regime shift.
- **First data to collect.** Multi-venue funding feed (median across venues), basis, collateral composition, redemption/withdrawal limits.
- **Product-line fit.** Enhanced → Max (isolated, regime-gated). · **Capital-tier fit.** mid (scales with funding depth, not linearly).
- **MVP-testable?** **Partial** — funding feed exists (`data/funding_feed.py`, `requires verification`) so the *measurement* is testable; the executable book is CEX-custody-gated (`rates_desk` BASIS_HEDGE = BLOCKED-NO-HEDGE). Cross-ref [`43`](43_dangerous_strategies.md) #13.

### 10. Curated credit vaults (disclosed underwriters)
- **Why research first.** A higher rate with *named* counterparties; researching it establishes the credit-underwriting discipline (measurement side) the desk has already probed.
- **Yield source.** Interest paid by disclosed institutional/private borrowers ([`33`](33_yield_thesis_map.md) A11).
- **Main risk.** Borrower default; opacity; lockups; no on-chain liquidation; counterparty.
- **First data to collect.** Underwriter identity + track record, loan-book disclosures, collateral terms, default/recovery history, lockup terms.
- **Product-line fit.** Max / Experimental (legal-review gated). · **Capital-tier fit.** mid–large, custody + legal gated.
- **MVP-testable?** **No — off-code** for the book (relationships + legal + capital). The **measurement** side is studied in `rwa_backstop/underwriting` (verdict: measurement-GO / book NO-GO). Cross-ref [`43`](43_dangerous_strategies.md) #14.

### 11. Levered PT carry (bounded, liquidation-modeled)
- **Why research first.** The disciplined way to study leverage: enhanced carry *only* with a validated liquidation model — the opposite of the refused naked loop, making it a good boundary case.
- **Yield source.** Amplified fixed-carry spread (PT carry, levered) ([`33`](33_yield_thesis_map.md) A2/A4).
- **Main risk.** Liquidation; borrow-rate spike; oracle lag; underlying-PT depeg. **A leverage-blind backtest previously over-stated this and was caught + fixed** in the rates desk.
- **First data to collect.** Supply/borrow rates, LTV + liquidation thresholds, oracle design, unwind depth, full liquidation-path model under ≥ −20% shock.
- **Product-line fit.** Max / Experimental (isolated). · **Capital-tier fit.** small sleeves only (scales poorly).
- **MVP-testable?** **Partial** — a research sleeve exists (`rates_desk` LeveredCarry) but stays research-only until it passes the gate; **never** deploy without the liquidation model (cross-ref [`43`](43_dangerous_strategies.md) #4).

### 12. Cross-venue stable arbitrage sleeves
- **Why research first.** Spread capture between venues; researching it early maps the real (small) capacity of arb-style edge so the desk does not over-estimate it at scale.
- **Yield source.** Price/rate spread captured across venues (execution edge, not a coupon).
- **Main risk.** Spread compresses to nothing; execution slippage on both legs; venue risk; capacity is tiny.
- **First data to collect.** Cross-venue rate/price spreads, both-leg depth, execution-cost model, historical spread persistence.
- **Product-line fit.** Enhanced (capacity-constrained). · **Capital-tier fit.** small (capacity-capped).
- **MVP-testable?** **Partial** — spread *measurement* is testable on available data; capturing it needs execution infra (off-code for now).

---

## Stablecoin — Aggressive (Max / Experimental)

### 13. Structured yield sleeves (tail-aware)
- **Why research first.** To build the tail-decomposition discipline *before* any structured product is ever considered — the research itself is the safeguard against hidden short-vol.
- **Yield source.** Packaged options/rates payoff (must be fully decomposed) ([`33`](33_yield_thesis_map.md) A12).
- **Main risk.** Embedded short-vol tail; path-dependency; blows up in stress. Default posture is REFUSE unless payoff fully decomposed (cross-ref [`43`](43_dangerous_strategies.md) #12).
- **First data to collect.** Full payoff decomposition (every leg), quantified tail loss, options-venue depth per strike, path-dependency model.
- **Product-line fit.** Max / Experimental (isolated). · **Capital-tier fit.** small.
- **MVP-testable?** **No — off-code** (options venue + full decomposition required); research/red-team only.

### 14. Emerging-protocol lending (post-audit, size-capped)
- **Why research first.** Early access can carry a real, if temporary, spread; researching a disciplined *post-audit, size-capped* framework separates "new protocol worth watching" from "brand-new high-APY trap."
- **Yield source.** Borrow demand on a newer, audited protocol (base) + often emissions (flagged as subsidy).
- **Main risk.** No track record; exploit surface; incentive-only yield; admin/governance risk (cross-ref [`43`](43_dangerous_strategies.md) #20). Strict caps mandatory.
- **First data to collect.** Audits + findings, time-in-production, base-vs-incentive split, admin-key/timelock disclosure, TVL trajectory.
- **Product-line fit.** Max / Experimental (isolated, strict caps). · **Capital-tier fit.** small sleeves only.
- **MVP-testable?** **Partial** — screenable/paper-trackable at tiny size *only after* audit evidence exists; never at launch.

---

## BTC — Cycle / Yield (decision-support)

### 15. BTC capital-cycle rotation (accumulate / ladder)
- **Why research first.** BTC is a core mandate asset; the cycle framework is decision-support (not auto-trading) and is the honest way to express BTC exposure without pretending it is "yield."
- **Yield source.** **Not yield** — capital appreciation + disciplined rotation (cycle timing) ([`33`](33_yield_thesis_map.md) B1).
- **Main risk.** Cycle mistiming; regime change; BTC −50%+ drawdowns are normal; behavioral risk.
- **First data to collect.** Price history, on-chain cycle indicators, macro/ETF-flow context (`requires verification`), ladder-rule backtest.
- **Product-line fit.** BTC Cycle (decision-support). · **Capital-tier fit.** $100k → $100M+ (deep spot market).
- **MVP-testable?** **Partial** — the framework is backtestable/paper-modelable as decision-support; it is **never** APY-claimed and **never** auto-traded ([`06`](06_spa_core_invariants.md) §E).

### 16. Conservative BTC lending (multi-custodian, low-utilization aware)
- **Why research first.** To document the *honest* base yield on BTC (near-0%) so the desk never overstates BTC lending — an important negative result.
- **Yield source.** Borrow demand for BTC — but BTC is rarely borrowed on-chain, so the honest APY is near-0% ([`33`](33_yield_thesis_map.md) B2).
- **Main risk.** Single-custodian failure (cross-ref [`43`](43_dangerous_strategies.md) #15); wrapped-BTC depeg; near-0% yield rarely compensates the risk.
- **First data to collect.** Utilization + supply APY per venue, custodian attestations, wrapped-asset backing (WBTC excluded; LBTC-restaking REFUSED).
- **Product-line fit.** Preserve (near-0). · **Capital-tier fit.** $100k → $100M+ (yield, not capacity, is the constraint).
- **MVP-testable?** **Yes** — read-only `tbtc_lending` / `cbbtc_lending` adapters already report the honest ~0% (`spa_core/adapters/btc_lending.py`, advisory).

### 17. BTC basis / funding (hedged, exchange-diversified)
- **Why research first.** The main way BTC can produce real carry; researching it early forces exchange diversification and counterparty-limit discipline before any sizing.
- **Yield source.** Spot–future basis / perp funding, delta-neutral ([`33`](33_yield_thesis_map.md) B2).
- **Main risk.** Basis compresses; funding flips; CEX counterparty (cross-ref [`43`](43_dangerous_strategies.md) #13); hedge break.
- **First data to collect.** Multi-venue BTC funding + basis, borrow/lend for the spot leg, per-venue custody limits.
- **Product-line fit.** Core → Enhanced (isolated). · **Capital-tier fit.** mid (CEX-access, custody/legal gated).
- **MVP-testable?** **Partial** — funding/basis *measurement* is testable; the executable hedge needs a CEX leg (off-code, custody-gated).

---

## ETH — Staking / Yield (decision-support + real staking yield)

### 18. Plain LST staking (stETH / rETH)
- **Why research first.** Real, durable ETH base yield with the closest-to-peg exposure; it is the safe leg the desk already uses and the anchor for any ETH strategy.
- **Yield source.** **Real ETH staking rewards** (consensus issuance + priority fees + MEV) ([`33`](33_yield_thesis_map.md) C1).
- **Main risk.** Staking rate falls with participation; LST depeg vs ETH; withdrawal-queue length; slashing (diversified by pools); contract risk.
- **First data to collect.** Consensus reward rate, LST/ETH peg, validator-set size, withdrawal-queue history (`requires verification`).
- **Product-line fit.** Core (ETH-denominated base yield). · **Capital-tier fit.** $100k → $100M+ (very deep).
- **MVP-testable?** **Yes** — used as the safe leg of `eth_lst_neutral` (plain LST, not LRT) in `strategy_lab/`.

### 19. Hedged ETH (LST + short perp, β≈0)
- **Why research first.** Turns ETH staking yield into a market-neutral sleeve; it is the desk's recommended hedged-ETH approach and already scaffolded, making it a strong early validation target.
- **Yield source.** LST staking yield with ETH price hedged out via a short perp (β≈0) — the yield is staking, the hedge removes directionality ([`33`](33_yield_thesis_map.md) A8/C1).
- **Main risk.** Hedge break / basis on the perp leg; CEX counterparty; LST depeg residual; funding cost of the short.
- **First data to collect.** LST yield + peg, perp funding cost, hedge-ratio + rebalance cadence, depeg-residual model. **Known caveat:** hedged variants can false-kill on daily-granularity ratio misalignment — align by date, not row index.
- **Product-line fit.** Enhanced (market-neutral). · **Capital-tier fit.** mid (hedge leg custody-gated).
- **MVP-testable?** **Partial** — `eth_lst_neutral` exists and is paper-modelable on live data; a live executable hedge is CEX-gated.

### 20. LRT / restaking (isolated, directional)
- **Why research first.** Higher headline yield that must be *decomposed* — researching it early separates real staking yield from speculative points/AVS rewards, an essential honesty exercise.
- **Yield source.** Staking yield **+ restaking/AVS rewards + points** (much of it speculative/incentive) ([`33`](33_yield_thesis_map.md) C2).
- **Main risk.** Extra slashing surface; LRTs depeg more than LSTs; points may not convert (cross-ref [`43`](43_dangerous_strategies.md) #8); thin secondary liquidity.
- **First data to collect.** LRT/ETH peg, AVS reward data (opaque), points-program terms + realized conversion history, base-vs-points split.
- **Product-line fit.** Max / Experimental (isolated, directional). · **Capital-tier fit.** small sleeves only.
- **MVP-testable?** **Partial** — studied as `variant_n` (hedged) / `variant_d` (directional) in `strategy_lab/`; stays isolated/research-only, and plain LST (#18) is preferred for the safe hedged sleeve.

---

## Roster summary — sequencing logic

| Group | Entries | Research posture |
|---|---|---|
| **Conservative (Preserve/Core)** | 1–4 | Anchor the book + establish the RWA-floor baseline; mostly MVP-testable now. |
| **Balanced (Core/Enhanced)** | 5–8 | Incremental spread with contained risk; carding + spread-attribution before promotion. |
| **Enhanced** | 9–12 | Real spread but custody/legal/capacity gated; measurement testable, execution mostly off-code. |
| **Aggressive (Max/Experimental)** | 13–14 | Build the tail/leverage discipline *before* deployment; default REFUSE without full decomposition. |
| **BTC (decision-support)** | 15–17 | Cycle framework + honest near-0% lending + hedged basis; never auto-traded, never APY-claimed for the cycle. |
| **ETH (staking/yield)** | 18–20 | Real staking base (18), market-neutral sleeve (19), decompose LRT hype (20). |

**The through-line.** The roster starts at the floor (2) and the deepest real yield (1), then works
outward, and **every** step past the floor must have its spread fully explained by a named, accepted,
measurable risk ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)) or it is refused and the
refusal recorded ([`43`](43_dangerous_strategies.md)). Nothing here is approved by being listed; each
entry becomes a full Strategy Card only after passing the lifecycle
([`07`](07_yield_lab_lifecycle.md)) with an evidence level ([`37`](37_apy_realism_and_evidence_standard.md)).
