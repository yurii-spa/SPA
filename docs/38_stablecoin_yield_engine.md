# 38 — Stablecoin Yield Engine

**Purpose.** The central research machine for the desk's primary focus asset: **stablecoin yield**.
It answers, per stablecoin and per strategy category, *what we are actually holding* and *where the
yield actually comes from* — so no stablecoin is deployed and no yield category is promoted without an
auditable due-diligence record. This is the stablecoin-specific companion to the taxonomy in
[`33_yield_thesis_map.md`](33_yield_thesis_map.md) (Domain A) and is governed by the evidence discipline
in [`37_apy_realism_and_evidence_standard.md`](37_apy_realism_and_evidence_standard.md).

**No invented numbers.** Every concrete APY, TVL, reserve figure, redemption term, or market size below
is written `requires verification`. APY is expressed only as a **range category** (charter product
lines: **Preserve 4–7% · Core 7–10% · Enhanced 10–13% · Max 13–18% · Experimental 18–25%+**). A
category is *where a mechanism can plausibly sit*, never a promise.

**Do not duplicate.** Much of this machine already exists in code — this doc *formalizes and unifies*:
- Fixed/implied-rate carry, refusal-first pricing → `spa_core/strategy_lab/rates_desk/`.
- 10–15%+ strategies the desk paper-tests and mostly **refuses** → `spa_core/strategy_lab/aggressive_lab/`.
- RWA T-bill floor (the benchmark) → `spa_core/strategy_lab/` `rwa_sleeve` + `data/rwa_feed.py`.
- Live protocol APY/TVL feeds → `spa_core/adapters/` + `spa_core/adapters/defillama_feed.py`.
- Risk-first pool screening → `spa_core/dfb/`.
See [`02_current_architecture_audit.md`](02_current_architecture_audit.md) §2.

---

## 1. Stablecoins to track

The tracked set. Each is a **Stablecoin Card** subject (schema in §2); nothing here is a whitelist —
inclusion means *under research*, not *approved*. Approval flows through the Yield Lab lifecycle
([`06_spa_core_invariants.md`](06_spa_core_invariants.md) §E-16).

| Stablecoin | Category (structural) | Backing model (`requires verification`) |
|---|---|---|
| **USDC** | Fiat-backed, regulated | Cash + short T-bills, monthly attestation |
| **USDT** | Fiat-backed | Mixed reserves, attestation (less granular) |
| **DAI** | Crypto/RWA-backed (MakerDAO/Sky) | Overcollateralized crypto + RWA |
| **USDe** | Synthetic (delta-neutral) | Staked-ETH collateral + short perp hedge |
| **sUSDe** | Yield-bearing wrapper of USDe | USDe + basis/funding yield accrual |
| **sUSDS** | Yield-bearing (Sky) | DAI/USDS savings rate (SSR) |
| **PYUSD** | Fiat-backed (PayPal/Paxos) | Cash + T-bills, regulated issuer |
| **RLUSD** | Fiat-backed (Ripple) | Cash + T-bills, regulated issuer |
| **EURC** | Fiat-backed, EUR-denominated | Euro cash reserves (FX exposure vs USD book) |

**Structural note.** USDe/sUSDe are **not** fiat-backed — they are a synthetic delta-neutral position
wearing a stablecoin label; their "yield" is basis/funding (doc 33 A6) and carries funding-reversal +
CEX-counterparty tail risk. EURC introduces **FX risk** against a USD-denominated book. These are not
interchangeable with USDC-class fiat stables and must never be treated as such in allocation.

---

## 2. Per-stablecoin fields to capture (Stablecoin Card)

Every tracked stablecoin carries this record. A missing field caps its max allocation to zero until
filled. All concrete values `requires verification`.

| Field | What to capture |
|---|---|
| **Issuer** | Legal entity, ownership, track record, regulatory registrations. |
| **Backing** | Reserve composition (cash / T-bills / crypto / synthetic), collateralization ratio. |
| **Reserve transparency** | Attestation vs full audit; auditor; cadence; on-chain proof-of-reserves availability. |
| **Redemption** | Who can redeem (direct vs secondary-market only), size limits, T+n settlement, fees, KYC gate. |
| **Liquidity** | On-chain DEX depth + CEX depth; concentration across venues; depth at our tier (compression flag). |
| **Depeg history** | Documented depeg events, magnitude, duration, recovery — dates, not adjectives. |
| **Freeze / blacklist risk** | Can the issuer freeze/blacklist an address? Governance for it? Precedent? |
| **Jurisdiction** | Issuer domicile; applicable regime (MiCA / US / offshore); reclassification risk. |
| **Integrations** | Which lending/vault/LP/Pendle markets accept it; composability = contagion surface. |
| **Max-allocation logic** | Per-stablecoin cap derived from category + transparency + liquidity + depeg history + capital tier ([`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md)). |
| **Emergency-exit** | Fastest safe exit path: direct redemption, DEX swap, or wait; expected slippage/time at our size. |

**Max-allocation logic (deterministic, advisory).** Cap = min of: structural-category cap (fiat-backed
> RWA-backed > synthetic), transparency haircut (attestation < full audit), liquidity cap (depth at
tier), depeg-history penalty, and the RiskPolicy hard caps ([`06`](06_spa_core_invariants.md) §A — TVL
floor, per-protocol/T2 limits). This is **advisory input**; the deterministic RiskPolicy remains the
sole hard gate and is never overridden.

---

## 3. The 14 stablecoin yield-strategy categories

Each category below is one row of the machine. **Yield source** ties to the five honest buckets of
doc 33 §0 (borrow demand · risk-premium/tail-comp · basis/funding · incentives/subsidy · real economic
yield). The single honesty test throughout: *is this real economic return, or am I being paid to carry
tail risk?* — default **REFUSE** on the latter until red-team clears it.

### C1. Conservative overcollateralized lending
- **Yield source:** borrow demand (variable rate). · **APY category:** Preserve → Core.
- **Risk drivers:** contract exploit; oracle failure; utilization spike freezing withdrawals; governance.
- **Capacity:** cap-bounded by pool liquidity + utilization headroom; large. · **Liquidity:** high (unless utilization-frozen).
- **Data:** on-chain reserve rate, utilization, TVL (`requires verification`); adapter feeds. · **Monitoring:** daily.
- **Product line:** Preserve / Core. · **Validation:** L1→L2→L3.
- **Red-team:** exploit history? oracle design? withdrawal freeze under stress? governance capture?
- **SPA today:** read-only adapters (`spa_core/adapters/`), RiskPolicy-capped. Doc 33 **A1**.

### C2. Curated lending vaults (Morpho / curator-managed)
- **Yield source:** borrow demand, peer-matched. · **APY category:** Core → Enhanced.
- **Risk drivers:** curator misallocation; underlying-market fragility; contract risk.
- **Capacity:** vault capacity + underlying depth. · **Liquidity:** underlying-market dependent.
- **Data:** vault rate, curator/allocation config, underlying market. · **Monitoring:** daily; curator-config change = alert.
- **Product line:** Core / Enhanced. · **Validation:** protocol + **curator** card mandatory.
- **Red-team:** who is the curator? allocation limits? underlying fragility?
- **SPA today:** adapter present (read-only); curator DD not yet carded. Doc 33 **A3**.

### C3. Pendle fixed-rate (PT to maturity)
- **Yield source:** fixed implied rate locked by buying PT at discount. · **APY category:** Core → Enhanced.
- **Risk drivers:** underlying-yield source fails; thin secondary liquidity to exit early; contract risk.
- **Capacity:** **thin** — bounded by PT pool depth per maturity (binding constraint). · **Liquidity:** hold-to-maturity is safe path.
- **Data:** Pendle market data, PT/YT prices, maturity, underlying-yield feed. · **Monitoring:** daily; per-maturity.
- **Product line:** Enhanced (validated). · **Validation:** already validated (refusal-first thesis #1).
- **Red-team:** underlying-yield durability? exit liquidity? which underlying is toxic (LRT PTs)?
- **SPA today:** **FixedCarry** in `spa_core/strategy_lab/rates_desk/` (validated, live-paper, refusal-first). Doc 33 **A4**.

### C4. Basis / cash-and-carry (spot–future)
- **Yield source:** spot–future basis captured delta-neutral. · **APY category:** Enhanced → Max (regime-dependent).
- **Risk drivers:** funding/basis flips; counterparty; two-leg execution slippage.
- **Capacity:** aggregate funding depth; regime/venue-limited. · **Liquidity:** both legs must exit simultaneously.
- **Data:** multi-venue basis + funding, borrow/lend for spot leg. · **Monitoring:** continuous (intraday).
- **Product line:** Max, isolated. · **Validation:** red-team mandatory; **CEX leg is off-code**.
- **Red-team:** funding reversal survival? venue default? basis-collapse behavior?
- **SPA today:** rates_desk `BASIS_HEDGE` shape **BLOCKED-NO-HEDGE** (CEX leg not built). Doc 33 **A7**.

### C5. Funding-rate arbitrage (perp funding capture)
- **Yield source:** perp funding paid by leveraged longs. · **APY category:** Enhanced → Max (regime-dependent).
- **Risk drivers:** funding flips negative; venue/counterparty; hedge break.
- **Capacity:** funding depth across venues; compresses with size. · **Liquidity:** venue withdrawal limits.
- **Data:** 5-venue funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid median). · **Monitoring:** continuous; funding-kill trigger.
- **Product line:** Max, isolated, regime-gated. · **Validation:** funding-kill logic required.
- **Red-team:** sustained negative funding? venue default? collateral depeg?
- **SPA today:** studied in `aggressive_lab/`; funding feed `data/funding_feed.py` (`requires verification`). Doc 33 **A7**.

### C6. Delta-neutral (Ethena / sUSDe class)
- **Yield source:** staking basis + perp funding on a long-spot/short-perp book. · **APY category:** Enhanced → Max.
- **Risk drivers:** funding reversal; CEX counterparty; collateral custody; USDe/sUSDe depeg; regime shift.
- **Capacity:** funding depth + collateral capacity. · **Liquidity:** sUSDe redemption windows.
- **Data:** multi-venue funding, collateral composition, sUSDe redemption. · **Monitoring:** continuous; funding-kill.
- **Product line:** Max, isolated, regime-gated. · **Validation:** red-team mandatory.
- **Red-team:** sustained negative funding? CEX default? collateral depeg?
- **SPA today:** studied in `aggressive_lab/`; sUSDe funding-kill noted. **Conditional REFUSE** — excess is tail-comp. Doc 33 **A6/A8**.

### C7. Stablecoin LP (Curve / Convex / stable AMM)
- **Yield source:** trading fees + incentive emissions. · **APY category:** Core (fees) → Enhanced (with incentives).
- **Risk drivers:** **depeg of a pool asset → permanent loss**; incentive cliff; contract risk.
- **Capacity:** pool depth; incentive dilution as you add. · **Liquidity:** easy exit unless a pool asset depegged.
- **Data:** pool balances, fee APR, emissions APR, peg spread of pool assets. · **Monitoring:** daily; peg-spread intraday.
- **Product line:** Core / Enhanced; incentive portion flagged as subsidy. · **Validation:** base-vs-incentive split mandatory (doc 37 §3).
- **Red-team:** which pool asset depegs first? emission-cliff date? fee-vs-subsidy split?
- **SPA today:** Aerodrome LP adapter (read-only); incentive-split carding pending. Doc 33 **A9**.

### C8. RWA / tokenized T-bills (the floor)
- **Yield source:** **real T-bill coupon** (US Treasury interest). · **APY category:** Preserve — the honest floor.
- **Risk drivers:** issuer default; custody; redemption freeze; regulatory reclassification.
- **Capacity:** very large (multi-$B market `requires verification`); rarely binding. · **Liquidity:** redemption windows (T+n), not always instant.
- **Data:** live tokenized-T-bill feed, TVL-weighted (`data/rwa_feed.py`, ≈3.4% `requires verification`). · **Monitoring:** daily.
- **Product line:** **Preserve — the benchmark every other strategy must beat risk-adjusted.** · **Validation:** L1→L6.
- **Red-team:** issuer solvency? custody chain? redemption under stress? reg status?
- **SPA today:** `rwa_sleeve` + `data/rwa_feed.py` — the risk-adjusted benchmark for the whole desk. Doc 33 **A10**.

### C9. Tokenized private credit (Maple-style / institutional)
- **Yield source:** interest paid by institutional/private borrowers. · **APY category:** Enhanced → Max (credit-spread dependent).
- **Risk drivers:** **borrower default**; underwriting failure; illiquid lockups; opacity; no on-chain liquidation.
- **Capacity:** loan-book size — but capacity ≠ safety (underwriting quality is the limit). · **Liquidity:** lockups / no secondary.
- **Data:** loan-book disclosures (opaque), collateral terms, default history, issuer reporting. · **Monitoring:** per issuer-report cadence.
- **Product line:** Max / Experimental, **legal-review gated**. · **Validation:** credit review + red-team + legal (not code-only).
- **Red-team:** who underwrites? default history? recovery process? lockup under stress?
- **SPA today:** not carded; `rwa_backstop/underwriting` probes the *measurement* side (measurement-GO / book NO-GO). **Conditional REFUSE.** Doc 33 **A11**.

### C10. CeFi / OTC treasury lending
- **Yield source:** bilateral spread / short-term lending to trusted counterparties. · **APY category:** Core → Enhanced.
- **Risk drivers:** counterparty default; relationship-gated; opacity; no on-chain proof.
- **Capacity:** counterparty limits. · **Liquidity:** term-dependent; often locked.
- **Data:** counterparty financials (off-chain), terms, collateral. · **Monitoring:** per-counterparty exposure, continuous limit checks.
- **Product line:** Core → Enhanced, **off-code** (relationships + legal). · **Validation:** counterparty DD + legal.
- **Red-team:** counterparty solvency? recall terms? concentration?
- **SPA today:** not implemented; research-only (off-code relationships). Doc 33 **A12**.

### C11. Structured products (packaged options/rates payoff)
- **Yield source:** packaged options/rates payoff (often embedded short-vol). · **APY category:** Enhanced → Max.
- **Risk drivers:** path-dependent payoff; **embedded short-vol tail**; opacity of the wrapper.
- **Capacity:** issuer/venue-limited. · **Liquidity:** often locked to expiry.
- **Data:** full payoff decomposition (required), IV surface, underlying. · **Monitoring:** continuous near expiry.
- **Product line:** Max, isolated. · **Validation:** **REFUSE unless payoff fully decomposed** into known primitives.
- **Red-team:** worst-case payoff path? hidden short-vol? venue default?
- **SPA today:** not implemented. **REFUSE default.** Doc 33 **A12**.

### C12. Incentive farming (emissions / points / airdrops)
- **Yield source:** token emissions / points / airdrop speculation. · **APY category:** Experimental (mostly unrealizable).
- **Risk drivers:** emissions end; token collapses; **points never convert to cash**; airdrop-leverage trap.
- **Capacity:** not sizable as real yield. · **Liquidity:** thin, speculative.
- **Data:** emissions schedule, points program (opaque), token liquidity. · **Monitoring:** emission-cliff dates.
- **Product line:** **None** — subsidy, not yield. · **Validation:** flag as incentive; never card as sustainable.
- **Red-team:** do points convert? at what rate? is this airdrop-leverage?
- **SPA today:** **REFUSE** — points/airdrop-leverage explicitly rejected (LBTC-restaking note, invariants). Doc 33 **A5/A12**.

### C13. Looping / recursive leverage on lending
- **Yield source:** amplified supply-minus-borrow spread (levered). · **APY category:** Enhanced → Max (leverage-dependent).
- **Risk drivers:** **liquidation**; rate inversion; oracle lag; depeg of looped asset; hidden leverage.
- **Capacity:** shrinks as leverage rises; bounded by liquidation buffer + pool depth. · **Liquidity:** must unwind before liquidation price.
- **Data:** live supply/borrow rates, LTV, liquidation thresholds, oracle price. · **Monitoring:** continuous health-factor.
- **Product line:** Max / Experimental only, isolated sleeve. · **Validation:** full red-team mandatory before any paper approval.
- **Red-team:** health factor under −20% shock? borrow-rate spike? oracle manipulation?
- **SPA today:** studied and **REFUSED** in `aggressive_lab/` (dated liquidation drawdowns recorded). **REFUSE default** — largely tail-comp. Doc 33 **A2**.

### C14. Hybrid (multi-source composed sleeves)
- **Yield source:** composed — e.g. RWA floor base + a red-team-cleared basis overlay; each leg attributed separately.
- **APY category:** blended; reported as the **weakest leg's** risk category, not the average.
- **Risk drivers:** correlation between legs under stress; the composition can hide a single dominant tail.
- **Capacity:** min of the legs' capacities. · **Liquidity:** min of the legs' liquidity.
- **Data:** all constituent-leg feeds + a cross-leg correlation/stress overlay. · **Monitoring:** per-leg + composite; continuous for any funding/leverage leg.
- **Product line:** category of the riskiest leg. · **Validation:** every leg must independently clear its own row above; the composite gets its own red-team.
- **Red-team:** do the legs' tails correlate in stress? does one leg secretly dominate the risk? does hedging one leg break the other?
- **SPA today:** the desk's honest posture — a Preserve RWA floor with **narrowly** red-team-cleared Enhanced overlays, each attributed separately (`forward_analytics.py` scorecard vs the floor).

---

## 4. Category posture summary

| Posture | Categories |
|---|---|
| **Keep (real economic / real borrow-demand yield)** | C1 conservative lending, C2 curated vaults, C3 Pendle fixed (validated), C7 stable LP (base fees), C8 RWA T-bills (the floor) |
| **Isolated / regime-gated / red-team-cleared only** | C4 basis, C5 funding arb, C6 delta-neutral (sUSDe) |
| **Off-code / legal-gated (research-only until carded)** | C9 private credit, C10 CeFi/OTC |
| **REFUSE by default (tail-comp / speculation / short-vol)** | C11 structured products (unless decomposed), C12 incentive farming (subsidy), C13 looping |

**Through-line.** The engine earns from **real borrow demand and real economic yield**, refuses to be
paid for **tail risk it cannot underwrite**, and forces every category to clear the evidence funnel in
[`37`](37_apy_realism_and_evidence_standard.md) (risk-adjusted, sustainable, net, executable — beating
the RWA floor after stress) before any claim is made. The desk's audited honesty: most categories do
**not** clear that funnel at fundable scale — capital preservation outranks maximum yield
([`06`](06_spa_core_invariants.md) §E). See also [`33_yield_thesis_map.md`](33_yield_thesis_map.md)
(full taxonomy) and [`34_capital_tiers_strategy.md`](34_capital_tiers_strategy.md) (how scale changes
the category universe).
