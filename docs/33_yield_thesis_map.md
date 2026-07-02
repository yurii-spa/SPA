# 33 — Yield Thesis Map

**Purpose.** This is the flagship research document. It answers one question honestly for every
mechanism the desk may touch: **where does the yield actually come from?** For each mechanism it
records the yield source, who pays it, why it exists, why it can disappear, an APY-range *category*
(never an invented live number), required data sources, main risks, capacity-estimate method,
liquidity constraints, operational complexity, product-line fit, capital-tier fit, validation path,
red-team questions, and emergency-exit conditions.

**Reading rules.**
- **No invented numbers.** APY is expressed only as a range *category*. Any concrete APY or TVL below
  is written as `requires verification`. Range categories follow the charter product lines:
  **Preserve 4–7% · Core 7–10% · Enhanced 10–13% · Max 13–18% · Experimental 18–25%+.**
- A category is *where a mechanism can plausibly sit*, not a promise. Actual placement depends on
  live, verified data (see [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md)).
- Where SPA already implements a mechanism, the row cross-references the module. See
  [`02_current_architecture_audit.md`](02_current_architecture_audit.md).
- **REFUSE markers.** Several mechanisms are, on inspection, *compensation for tail risk* rather than
  a real edge. Those are marked **REFUSE / research-only**. The desk's stated posture is that it holds
  a conservative book and refuses risk-compensation yield it cannot justify
  ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §E).

**Honest framing.** SPA Core's audited finding is that *pure yield does not beat the ~3.4% RWA floor
(`requires verification`) at fundable scale by a durable margin*. The higher categories below exist so
the Yield Lab can **study, paper-test, and mostly refuse** them — not so they can be marketed. Capital
preservation outranks maximum yield.

---

## 0. Taxonomy of yield sources (the five honest buckets)

Every mechanism reduces to one or more of these. Knowing the bucket tells you why the yield can
vanish.

| Bucket | What is really paid | Disappears when |
|---|---|---|
| **Borrow demand** | Borrowers pay lenders interest | Borrowing demand falls / utilization drops |
| **Risk premium (tail-comp)** | You are paid to hold a risk others avoid (depeg, credit, liquidation) | The risk is repriced or materializes; **frequent REFUSE bucket** |
| **Basis / funding** | Spot–derivative spread or perp funding | Basis compresses / funding flips negative |
| **Incentives / subsidy** | Protocol/token emissions, points, airdrops | Emissions end, token falls, points don't convert |
| **Real economic yield** | T-bill coupon, private-credit interest, real-world cashflow | Rates fall / borrower defaults / redemption freezes |

The single most important honesty test: **is the yield real economic return, or am I being paid to
carry tail risk?** If the latter, the default answer is REFUSE unless red-team clears it.

---

## Domain A — Stablecoin Yield

### A1. Overcollateralized lending (Aave / Spark / Compound / Euler)

| Field | Value |
|---|---|
| Yield source | Borrow demand (variable rate) |
| Who pays | On-chain borrowers of the stablecoin |
| Why it exists | Leverage / working-capital demand for stablecoins |
| Why it can disappear | Utilization falls; rates compress; liquidity migrates |
| APY category | Preserve → Core |
| Data sources | On-chain reserve rates, utilization, TVL (DeFiLlama `requires verification`); adapter feeds |
| Main risks | Smart-contract exploit; oracle failure; utilization spike freezing withdrawals; governance |
| Capacity method | Deployable = f(pool liquidity, utilization headroom, per-protocol cap); size so that entry does not move the rate materially |
| Liquidity constraints | Withdrawals gated by available (non-borrowed) liquidity |
| Ops complexity | Low |
| Product line | Preserve / Core |
| Capital tier | $100k → $10M+ (cap-bounded; concentration limits bite past pool-share thresholds) |
| Validation | L1 historical → L2 source-verified → L3 paper-tracked |
| Red-team Qs | Exploit history? Oracle design? Withdrawal freeze under stress? Governance capture? |
| Emergency exit | Withdraw to cash; if frozen, wait for utilization to fall — size for this in advance |
| SPA today | Read-only adapters (`spa_core/adapters/`, RiskPolicy caps: TVL ≥ $5M, per-protocol T1 40% / T2 20%) |

### A2. Borrowing / recursive looping (leverage on lending)

| Field | Value |
|---|---|
| Yield source | Amplified borrow-demand spread (supply APY − borrow APY, levered) |
| Who pays | Borrowers, minus your own borrow cost |
| Why it exists | Positive supply-minus-borrow spread on correlated assets |
| Why it can disappear | Spread inverts; borrow rate spikes; liquidation cascade |
| APY category | Enhanced → Max (leverage-dependent) |
| Data sources | Live supply/borrow rates, LTV, liquidation thresholds, oracle price |
| Main risks | **Liquidation**; rate inversion; oracle lag; de-peg of looped asset |
| Capacity method | Bounded by liquidation buffer and pool depth; capacity shrinks as leverage rises |
| Liquidity constraints | Must be able to unwind before a liquidation price is hit |
| Ops complexity | High (continuous health-factor monitoring) |
| Product line | Max / Experimental only, isolated sleeve |
| Capital tier | Small sleeves only; scales poorly |
| Validation | Full red-team mandatory before any paper approval |
| Red-team Qs | Health factor under −20% shock? Borrow-rate spike? Oracle manipulation? Hidden leverage? |
| Emergency exit | De-lever first, always; unwind speed is the binding constraint |
| SPA today | Studied and **REFUSED** in `spa_core/strategy_lab/aggressive_lab/` (dated liquidation drawdowns recorded) |

> **REFUSE default.** Recursive looping is largely tail-comp: the extra APY compensates for
> liquidation risk. Research-only.

### A3. Morpho vaults / peer-matched lending

| Field | Value |
|---|---|
| Yield source | Borrow demand, peer-to-peer matched (improved rate) |
| Who pays | Matched borrowers |
| Why it exists | Matching improves the spread capture vs pooled lending |
| Why it can disappear | Fallback to underlying pool rate when unmatched; curator risk |
| APY category | Core → Enhanced |
| Data sources | Vault rates, curator/allocation config, underlying market, TVL (`requires verification`) |
| Main risks | Curator misallocation; underlying-market risk; contract risk |
| Capacity method | Vault capacity + underlying-market depth; curator concentration limits |
| Liquidity constraints | Depends on underlying market liquidity and vault utilization |
| Ops complexity | Medium (curator due diligence required) |
| Product line | Core / Enhanced |
| Capital tier | $100k → several $M |
| Validation | L1 → L2 → L3; protocol + curator card required |
| Red-team Qs | Who is the curator? Allocation limits? Underlying-market fragility? |
| Emergency exit | Withdraw subject to underlying liquidity |
| SPA today | Adapter present (read-only); curator DD not yet carded |

### A4. Pendle PT — fixed-rate (buy PT to maturity)

| Field | Value |
|---|---|
| Yield source | Fixed implied rate locked by buying principal-token at discount |
| Who pays | Yield-token buyers on the other side of the split |
| Why it exists | Market splits yield into fixed (PT) + variable (YT); PT holders lock a rate |
| Why it can disappear | Underlying-yield source fails; PT price gaps; thin secondary liquidity |
| APY category | Core → Enhanced (depends on underlying) |
| Data sources | Pendle market data, PT/YT prices, maturity, underlying-yield feed |
| Main risks | Underlying protocol/stablecoin risk; liquidity to exit before maturity; smart-contract |
| Capacity method | Bounded by PT pool depth per maturity — **thin**; capacity is the binding constraint |
| Liquidity constraints | Exit before maturity needs secondary liquidity; hold-to-maturity is the safe path |
| Ops complexity | Medium |
| Product line | Enhanced (validated) |
| Capital tier | Small–mid; capacity-cliff at larger sizes (thin PT depth) |
| Validation | Already validated as thesis #1 (refusal-first) |
| Red-team Qs | Underlying-yield durability? Exit liquidity? Which underlying is toxic (LRT PTs)? |
| Emergency exit | Hold to maturity (safest); or sell PT into secondary at a discount |
| SPA today | Implemented as **FixedCarry** in `spa_core/strategy_lab/rates_desk/` (validated, live-paper, refusal-first gate) |

### A5. Pendle YT / points farming (variable, speculative)

| Field | Value |
|---|---|
| Yield source | Leveraged exposure to variable yield + points/airdrop speculation |
| Who pays | Nobody guarantees it — value is speculative future emissions/points |
| Why it exists | YT concentrates variable yield + point accrual |
| Why it can disappear | Points don't convert; yield falls; YT decays to zero at maturity |
| APY category | Experimental (mostly unrealizable) |
| Data sources | Points programs (opaque), YT price, underlying yield |
| Main risks | Points never monetize; YT time-decay; speculation |
| Capacity method | Not sizable as a real yield strategy |
| Liquidity constraints | Thin, speculative |
| Ops complexity | High |
| Product line | None (advisory research only) |
| Capital tier | Not fundable |
| Validation | Treated as speculation, not yield |
| Red-team Qs | Do points convert to cash? At what rate? Is this an airdrop-leverage trap? |
| Emergency exit | Sell YT into whatever liquidity exists |
| SPA today | **REFUSE** — points/airdrop-leverage explicitly rejected (see BTC LBTC note, invariants) |

### A6. Ethena / sUSDe basis (delta-neutral funding)

| Field | Value |
|---|---|
| Yield source | Perp funding + staking basis on a delta-neutral (long spot / short perp) book |
| Who pays | Perp longs paying funding to shorts |
| Why it exists | Persistent positive funding in bull regimes |
| Why it can disappear | **Funding flips negative**; custody/CEX counterparty failure; collateral de-peg |
| APY category | Enhanced → Max (regime-dependent, funding-dependent) |
| Data sources | Multi-venue funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid — median), collateral composition, sUSDe redemption |
| Main risks | Funding reversal; CEX counterparty; collateral custody; de-peg; regime shift |
| Capacity method | Bounded by funding depth across venues + collateral capacity; funding compresses with size |
| Liquidity constraints | Redemption windows; CEX withdrawal limits |
| Ops complexity | High (custody + hedge management) |
| Product line | Max (isolated, regime-gated) |
| Capital tier | Mid; scales with funding depth, not linearly |
| Validation | Red-team mandatory; funding-kill logic required |
| Red-team Qs | What happens on sustained negative funding? CEX default? Collateral de-peg? |
| Emergency exit | Unwind hedge + redeem; funding-kill trigger |
| SPA today | Studied in `spa_core/strategy_lab/aggressive_lab/`; funding feed exists (`data/funding_feed.py`, `requires verification`); sUSDe funding-kill noted |

> **Conditional REFUSE.** Real basis yield exists, but much of the *excess* is tail-comp for funding
> reversal + counterparty risk. Enters only through a funding-kill-gated, isolated sleeve.

### A7. Funding-rate arbitrage / cash-and-carry / basis (generic)

| Field | Value |
|---|---|
| Yield source | Spot–future / perp basis captured delta-neutral |
| Who pays | The leveraged long side (funding) |
| Why it exists | Structural long-bias in crypto → positive funding |
| Why it can disappear | Funding flips; basis compresses; venue risk |
| APY category | Enhanced → Max (regime-dependent) |
| Data sources | Multi-venue funding + basis feeds, borrow/lend for the spot leg |
| Main risks | Funding reversal; counterparty; execution slippage on both legs |
| Capacity method | Aggregate funding depth across venues; capacity is regime- and venue-limited |
| Liquidity constraints | Both legs must be exitable simultaneously |
| Ops complexity | High (two-venue, continuous rebalance) |
| Product line | Max, isolated |
| Capital tier | Mid; requires CEX venue access (custody/legal gated) |
| Validation | Red-team mandatory; CEX-leg custody is off-code |
| Red-team Qs | Funding reversal survival? Venue default? Basis-collapse behavior? |
| Emergency exit | Close both legs; if one venue frozen, the hedge breaks — size for it |
| SPA today | Rates Desk `BASIS_HEDGE` shape is **BLOCKED-NO-HEDGE** (CEX leg not built) in `rates_desk/` |

### A8. Delta-neutral (general)

Covered structurally by A6/A7 (basis + funding) and by the ETH-neutral sleeve (C4). Yield source =
basis/funding; risk = hedge break + counterparty. Category Enhanced → Max, isolated, red-team gated.
SPA today: `eth_lst_neutral` sleeve in `strategy_lab/` (β≈0 hedged), and `rates_desk` basis shape blocked.

### A9. Stablecoin LP (Curve / Convex) + stable AMM LP

| Field | Value |
|---|---|
| Yield source | Trading fees + incentive emissions (CRV/CVX etc.) |
| Who pays | Swappers (fees) + protocol treasuries (emissions) |
| Why it exists | Demand for stable-to-stable swaps + liquidity subsidies |
| Why it can disappear | Emissions end; volume dries; **de-peg → impermanent loss becomes permanent** |
| APY category | Core (base fees) → Enhanced (with incentives) |
| Data sources | Pool balances, fee APR, emissions APR, peg spread of pool assets |
| Main risks | De-peg of a pool asset (permanent loss); incentive cliff; contract risk |
| Capacity method | Pool depth; incentive dilution as you add liquidity |
| Liquidity constraints | Exit is easy unless a pool asset has de-pegged (then you exit into the bad asset) |
| Ops complexity | Medium |
| Product line | Core / Enhanced; incentive portion flagged as subsidy |
| Capital tier | $100k → several $M |
| Validation | Base-vs-incentive split mandatory (see doc 37) |
| Red-team Qs | Which pool asset de-pegs first? Emission cliff date? Fee vs subsidy split? |
| Emergency exit | Withdraw balanced; a de-pegged pool returns you the worst asset |
| SPA today | Aerodrome LP adapter present (read-only); incentive-split carding pending |

### A10. RWA / tokenized T-bills (real economic yield — the floor)

| Field | Value |
|---|---|
| Yield source | **Real T-bill coupon** (US Treasury interest) |
| Who pays | The US Treasury, passed through by the issuer |
| Why it exists | Real short-term risk-free rate, tokenized |
| Why it can disappear | Rates fall; issuer/custody/redemption risk; regulatory |
| APY category | Preserve (tracks short rates) — the honest **floor** |
| Data sources | Live tokenized-T-bill feed, TVL-weighted (`data/rwa_feed.py`, ≈3.4% `requires verification`) |
| Main risks | Issuer default; custody; redemption freeze; regulatory reclassification |
| Capacity method | Very large (multi-$B market `requires verification`); capacity rarely binding |
| Liquidity constraints | Redemption windows (T+n); not always instant |
| Ops complexity | Low–medium (KYC/issuer relationship) |
| Product line | Preserve — the benchmark every other strategy must beat risk-adjusted |
| Capital tier | $100k → $100M+ |
| Validation | L1 → L6; this is the reference floor |
| Red-team Qs | Issuer solvency? Custody chain? Redemption under stress? Reg status? |
| Emergency exit | Redeem per issuer window; hold to maturity of underlying bills |
| SPA today | Implemented as `rwa_sleeve` + `data/rwa_feed.py`; the risk-adjusted benchmark for the whole desk |

### A11. Tokenized private credit / Maple-style credit / CeFi institutional lending

| Field | Value |
|---|---|
| Yield source | Interest paid by institutional/private borrowers |
| Who pays | Borrowing funds / trading firms / businesses |
| Why it exists | Off-chain credit demand at a spread over risk-free |
| Why it can disappear | **Borrower default**; underwriting failure; illiquid lockups; opacity |
| APY category | Enhanced → Max (credit-spread dependent) |
| Data sources | Loan-book disclosures (opaque), collateral terms, default history, issuer reporting |
| Main risks | Credit/default; opacity; lockups; no on-chain liquidation; counterparty |
| Capacity method | Loan-book size; but capacity ≠ safety — underwriting quality is the real limit |
| Liquidity constraints | Lockups / no secondary; illiquid by design |
| Ops complexity | High (credit underwriting, legal) |
| Product line | Max / Experimental, legal-review gated |
| Capital tier | Mid–large, custody + legal gated |
| Validation | Credit review + red-team + legal; not code-only |
| Red-team Qs | Who underwrites? Default history? Recovery process? Lockup under stress? |
| Emergency exit | Often **none before maturity** — this is the binding risk |
| SPA today | Not carded; `rwa_backstop/underwriting` probes the *measurement* side (verdict: measurement-GO / book NO-GO) |

> **Conditional REFUSE.** Real yield exists but is dominated by credit + opacity + illiquidity risk.
> Underwriting quality (relationships + legal + capital) is off-code. Research-only until carded.

### A12. OTC treasury / structured products / market-making / incentive farming (survey)

| Mechanism | Yield source | Why it can disappear | Category | Posture |
|---|---|---|---|---|
| OTC treasury desk | Bilateral spread / short-term lending to trusted counterparties | Counterparty default; relationship-gated | Core → Enhanced | Off-code (relationships); research-only |
| Structured products | Packaged options/rates payoff | Payoff path-dependent; embedded short-vol tail | Enhanced → Max | **REFUSE** unless payoff fully decomposed |
| Market-making | Bid-ask spread capture | Inventory / adverse-selection loss; toxic flow | Enhanced → Max | Research-only; needs execution infra |
| Incentive farming | Token emissions / points | Emissions end; token collapses | Experimental | Subsidy, not yield — **flag as incentive**, never card as sustainable |

---

## Domain B — BTC Yield & Cycle (decision-support only)

> All BTC-cycle mechanisms are **decision-support**, never auto-trading
> ([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §E, ADR-YL-007). BTC is held for cycle
> exposure; "yield on BTC" is mostly small or tail-comp.

### B1. Accumulation / cycle allocation / profit-taking ladder / BTC↔stable rotation

| Field | Value |
|---|---|
| Yield source | **Not yield** — capital appreciation + disciplined rotation (cycle timing) |
| Who pays | Market (price), not a coupon |
| Why it exists | BTC cycle structure; profit-ladder captures upside, rotation reduces drawdown |
| Why it can disappear | Cycle mistiming; regime change; BTC −50%+ drawdowns are normal |
| APY category | Not an APY — a total-return/decision framework |
| Data sources | Price, on-chain cycle indicators, macro (`requires verification`) |
| Main risks | Drawdown; mistiming; behavioral |
| Capacity method | Deep spot market — capacity rarely binding for this book size |
| Liquidity constraints | Spot BTC is highly liquid |
| Ops complexity | Medium (discipline + rules) |
| Product line | BTC Cycle (decision-support) |
| Capital tier | $100k → $100M+ |
| Validation | Framework-tested, not APY-claimed |
| Red-team Qs | Behavior at −50%? Ladder rule discipline? Rotation whipsaw? |
| Emergency exit | Rotate to stables per ladder rules |
| SPA today | Decision-support framework (planned `15_btc_cycle.md`, `36_btc_capital_cycle_machine.md`) |

### B2. BTC basis / funding / lending / collateralized borrowing

| Mechanism | Yield source | Why it can disappear | Category | Notes |
|---|---|---|---|---|
| BTC basis / cash-and-carry | Spot–future basis, delta-neutral | Basis compresses; funding flips | Core → Enhanced | Needs CEX leg (custody/legal gated) |
| BTC funding capture | Perp funding to shorts | Funding reversal | Enhanced | Regime-dependent; hedge break risk |
| BTC lending | Borrow demand for BTC | **BTC is rarely borrowed on-chain — near-0% APY** | Preserve (near-0) | Honest ~0% (`requires verification`) |
| Collateralized borrowing (BTC as collateral) | Not yield — liquidity unlock | Liquidation on BTC drop | n/a | Enables stable-side deployment; adds liquidation risk |

SPA today: read-only `tbtc_lending` / `cbbtc_lending` adapters, **advisory / ~0% APY**
(`spa_core/adapters/btc_lending.py`); WBTC excluded, LBTC-restaking **REFUSED** (points/airdrop-leverage).

### B3. BTC covered calls / options hedging

| Field | Value |
|---|---|
| Yield source | Option premium (selling upside) |
| Who pays | Call buyers |
| Why it exists | Implied-vol premium; willingness to cap upside for income |
| Why it can disappear | **Caps upside in a rally**; premium collapses in low-vol; assignment risk |
| APY category | Enhanced (premium-dependent) |
| Data sources | Options IV surface, strike/expiry liquidity (`requires verification`) |
| Main risks | Opportunity cost (capped upside); short-vol tail; venue/counterparty |
| Capacity method | Options-market depth per strike — thin at size |
| Liquidity constraints | Thin option books; roll risk |
| Ops complexity | High (options ops + venue) |
| Product line | Max, isolated, decision-support |
| Capital tier | Small–mid |
| Validation | Red-team (short-vol tail) mandatory |
| Red-team Qs | Behavior in a +50% BTC rally? Vol crush? Assignment/venue default? |
| Emergency exit | Buy back calls (costly in a rally) |
| SPA today | Not implemented; decision-support only |

> **REFUSE default on naked short-vol.** Covered calls are short-vol tail-comp; only ever as a
> decision-support overlay on already-held BTC, never leveraged.

### B4. Wrapped-BTC / BTCFi risk · custody / counterparty (cross-cutting)

| Field | Value |
|---|---|
| Nature | Not a yield source — a **risk multiplier** on every BTC-yield mechanism above |
| Why it matters | Wrapped BTC adds bridge/custodian/governance risk on top of the yield |
| Why it bites | Bridge exploit; custodian insolvency; governance capture (e.g. WBTC governance overhang) |
| Category | n/a (risk overlay) |
| Data sources | Custodian attestations, bridge audits, governance structure |
| Main risks | De-peg of wrapped asset; custodian default; bridge hack |
| Posture | WBTC **excluded** (governance overhang, `requires verification`); wrapped-BTC yield only through vetted custody |
| Red-team Qs | Who custodies? Bridge audit? Governance who-can-mint? De-peg history? |
| Emergency exit | Unwrap to native BTC where possible; else exposed to wrapper solvency |
| SPA today | Codified refusals: WBTC excluded, LBTC-restaking rejected |

---

## Domain C — ETH Yield & Cycle (decision-support + real staking yield)

### C1. Native / liquid staking (stETH / rETH — LST)

| Field | Value |
|---|---|
| Yield source | **Real ETH staking rewards** (consensus issuance + priority fees + MEV) |
| Who pays | The Ethereum protocol + block-space demand |
| Why it exists | Validators are paid to secure the chain |
| Why it can disappear | Staking rate falls with participation; slashing; LST de-peg |
| APY category | Preserve → Core (real base yield) |
| Data sources | Consensus reward rate, LST/ETH peg, validator-set size (`requires verification`) |
| Main risks | Slashing (diversified away by pools); LST de-peg vs ETH; withdrawal queue; contract risk |
| Capacity method | Very deep (protocol-level); capacity rarely binding |
| Liquidity constraints | Exit queue for native unstake; LST secondary liquidity otherwise |
| Ops complexity | Low (LST) |
| Product line | Core (as an ETH-denominated base yield) |
| Capital tier | $100k → $100M+ |
| Validation | L1 → L6; real, durable yield |
| Red-team Qs | LST de-peg history? Withdrawal-queue length under stress? Slashing exposure? |
| Emergency exit | Sell LST into secondary, or native-unstake via queue |
| SPA today | Used as the safe leg of `eth_lst_neutral` (**plain LST**, not LRT) in `strategy_lab/` |

### C2. Liquid restaking (LRT — eETH etc.)

| Field | Value |
|---|---|
| Yield source | Staking yield **+ restaking/AVS rewards + points** (much of it speculative) |
| Who pays | AVS services + point/airdrop programs (speculative) |
| Why it exists | Restaking rehypothecates stake to secure additional services |
| Why it can disappear | AVS rewards unproven; points don't convert; **additional slashing surface**; de-peg |
| APY category | Enhanced → Max (mostly incentive/speculative) |
| Data sources | LRT/ETH peg, AVS reward data (opaque), points programs |
| Main risks | Extra slashing surface; de-peg (LRTs de-peg more than LSTs); points-farming trap |
| Capacity method | Constrained by LRT liquidity and hedgeability |
| Liquidity constraints | Thinner secondary than LSTs; harder to hedge cleanly |
| Ops complexity | High |
| Product line | Max / Experimental, isolated |
| Capital tier | Small sleeves |
| Validation | Red-team mandatory; separate base yield from points |
| Red-team Qs | What is real yield vs points? De-peg residual when hedged? AVS slashing? |
| Emergency exit | Exit into thin LRT secondary |
| SPA today | Studied as `variant_n` (hedged) / `variant_d` (directional) in `strategy_lab/`; **plain-LST preferred** over LRT for the safe neutral sleeve |

> **Conditional REFUSE.** LRT excess yield over LST is largely incentive/tail-comp. The desk prefers
> plain LST for hedged books; LRT stays isolated and research-only.

### C3. ETH basis / funding / lending / collateral

| Mechanism | Yield source | Why it can disappear | Category | Notes |
|---|---|---|---|---|
| ETH basis / cash-and-carry | Spot–future basis | Basis compression; funding flip | Enhanced | CEX leg custody/legal gated |
| ETH funding capture | Perp funding | Funding reversal | Enhanced → Max | Regime-dependent |
| ETH lending | Borrow demand for ETH | Low utilization → low APY | Preserve → Core | Real but modest |
| ETH as collateral | Not yield — liquidity unlock | Liquidation on ETH drop | n/a | Adds liquidation risk to stable-side deployment |

### C4. ETH covered calls · ETH/BTC + ETH/stable rotation

| Mechanism | Yield source | Why it can disappear | Category | Posture |
|---|---|---|---|---|
| ETH covered calls | Option premium (short upside) | Caps rally; vol crush; short-vol tail | Enhanced | **REFUSE naked**; overlay-only on held ETH, decision-support |
| ETH/BTC rotation | Not yield — relative-value cycle timing | Mistiming; regime change | n/a | Decision-support framework |
| ETH/stable rotation | Not yield — de-risk / re-risk timing | Whipsaw; mistiming | n/a | Decision-support framework |

SPA today: hedged ETH via `eth_lst_neutral` (β≈0); rotation frameworks are decision-support (planned
`16_eth_yield.md`). Covered calls not implemented.

---

## Cross-domain summary — what the desk keeps vs refuses

| Posture | Mechanisms |
|---|---|
| **Keep (real economic / real borrow-demand yield)** | A1 lending, A3 Morpho vaults, A4 Pendle PT fixed (validated), A9 stable LP (base fees), A10 RWA T-bills (the floor), C1 LST staking, C3/ B2 lending (modest) |
| **Isolated / regime-gated / red-team-cleared only** | A6 sUSDe basis, A7/A8 funding & delta-neutral, B2 BTC basis, C3 ETH basis, C2 LRT (isolated) |
| **REFUSE by default (tail-comp / speculation / off-code)** | A2 looping, A5 Pendle YT/points, A11 private credit (until carded), A12 structured products / naked short-vol, B3/C4 covered calls (except decision-support overlay), LRT excess, wrapped-BTC without vetted custody |

**The through-line:** the desk earns from **real borrow demand and real economic yield**, refuses to
be paid for **tail risk it cannot underwrite**, and treats BTC/ETH cycle work as **decision-support**,
not auto-trading. Every "Keep" mechanism must still clear the evidence standard in
[`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md) before any claim
is made — and no APY on this page is a live number; all are categories or `requires verification`.
