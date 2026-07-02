# Strategy Candidate — Ethena sUSDe → WATCH (funding-carry risk-comp; lean-REFUSE at current thin spread)

> Edge-hunt cycle 17 (autonomous engine, ADR-YL-008). The largest delta-neutral synthetic dollar
> evaluated as a proper candidate. A sharp contrast to the Aave floor-parity result: sUSDe is
> **near-floor spread today (~46 bps) but carries a FAT tail** (funding-flip, CEX-counterparty, ~1.1%
> reserve). The mandate's read: funding carry is **unbounded risk-comp**, and at the current thin
> spread it does NOT pay for the tail. Data sourced 2026-07-02 (DeFiLlama + WebSearch). Complements
> (does not duplicate) `data/strategy_cards/examples/susde_dn.strategy.md` + `stablecoin_cards/examples/usde.stablecoin.md`.

## Candidate
- **candidate_id:** `CAND-SUSDE-001`
- **source:** live-yield scan (Ethena sUSDe, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `delta-neutral / funding-carry` (stake USDe → sUSDe; accrues perp-funding + staking)
- **assets:** `["sUSDe / USDe (Ethena)"]`
- **protocols:** `["Ethena"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `sUSDe ~3.86% APY` — **L2** (Aavescan, Q2-2026; **compressed from late-2024 high-single/double digits** as funding cooled; **variable, can briefly flip NEGATIVE** when longs unwind). [verified 2026-07-02]
- **suspected_yield_source:** delta-neutral basis — long staked-ETH/LRT collateral + short ETH perp; **perp funding + staking yield** accrue to sUSDe stakers.
- **Ethena USDe TVL:** `~$4.45B` (DeFiLlama `ethena-usde`, 2026-07-02; ~$5.6B supply cited Mar-2026). [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** `~46 bps` (3.86% − 3.4%) at current funding — **THIN**, and can go **negative**.
- **spread_risk_explanation — funding-carry risk-comp (UNBOUNDED tail; the spread does NOT bound it):**
  - `funding-rate flip` — the yield IS the perp funding rate; in a bearish unwind it compresses to zero / **negative**. Unbounded downside, not a fixed carry.
  - `CEX-counterparty / OES` — collateral at **OES custodians (Copper, Ceffu, Cobo)**, perps on **Binance/Bybit/OKX/Deribit** — exchange solvency + settlement + OES-custodian risk. The defining non-DeFi tail.
  - `reserve-fund thinness` — the **Ethena Reserve Fund was ~$61M vs ~$5.6B supply = ~1.1%** (Mar-2026); it subsidizes negative funding but is **NOT a guarantee** and is small vs the book.
  - `collateral / peg` — staked-ETH/LRT collateral (depeg/slashing) + USDe peg mechanics (Oct-2025-style deleveraging events are on record — see usde.stablecoin.md).

## Red-team (abbreviated)
- **how do we lose money?** funding turns negative for an extended stretch and drains the 1.1% reserve; a CEX/OES-custodian failure; an LRT-collateral depeg during a hedge-rebalance.
- **most-fragile assumption:** that funding stays positive AND the CEX/OES leg holds AND the 1.1% reserve suffices. Three unbounded tails for ~46 bps.
- **the sharp contrast:** Aave (cycle 16) was **floor-parity with a THIN tail** → just hold the floor. sUSDe is **floor-parity-ish with a FAT tail** → *actively avoid at this spread* (worse than Aave).

## Verdict
- **verdict:** **WATCH (research) → lean-REFUSE at the current ~46 bps spread** — the yield is **funding-carry risk-comp**, an **unbounded** tail (funding-flip + CEX-counterparty + 1.1% reserve + LRT peg), NOT a bounded/measurable edge. At today's thin spread it does not pay for the tail → do not fund. It is not a hard REFUSE (Ethena is a real, sizeable, functioning protocol with a reserve + OES custody) — but it only becomes interesting if funding widens materially AND under a strict CEX-counterparty cap + reserve-coverage floor.
- **reason_code:** `funding_carry_riskcomp_unbounded` (thin-spread-fat-tail at current levels)
- **conditions to RE-EVALUATE (not advance):** (1) funding widens to a spread that plausibly over-covers the tail, (2) a strict CEX/OES-counterparty concentration cap, (3) reserve-fund coverage floor (%-of-supply) as a kill trigger, (4) full Red-Team (mandatory), (5) treat as `Enhanced`-only with a hard sub-cap, never Core/Preserve.
- **product_line_fit:** `Enhanced` at best (never Preserve/Core — it is not principal-stable under a funding/CEX tail).

## Honesty note
The most-hyped "delta-neutral stablecoin yield" pays **~46 bps over the floor right now** for **three
unbounded tails**. That is the mandate working: a headline reputation for high yield does not survive
spread-over-floor + tail-attribution when funding is compressed. Re-open only if the pay actually
covers the risk — and even then, capped and CEX-gated.

*created_at: 2026-07-02 · sources: DeFiLlama ethena-usde TVL $4.45B; Aavescan sUSDe ~3.86%; Eco/Earnpark/Forbes research (delta-neutral basis, OES custodians Copper/Ceffu/Cobo, Binance/Bybit/OKX/Deribit, Reserve Fund $61M vs $5.6B supply = ~1.1% Mar-2026, funding can flip negative) + ADR-YL-008.*
