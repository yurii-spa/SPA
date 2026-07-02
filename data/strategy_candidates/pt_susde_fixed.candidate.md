# Strategy Candidate — Pendle PT-sUSDe fixed carry (11.2%) → WATCH / CONDITIONAL-ADVANCE

> Edge-hunt cycle 21 (autonomous engine, ADR-YL-008) — **first cycle of the "real 8-12% with bounded
> risk" hunt** (owner-directed). A sharp rubric result: **spot sUSDe was lean-REFUSE (unbounded
> funding-flip tail, cycle 17); PT-sUSDe FIXED to maturity REMOVES the funding-flip tail** (you lock
> the rate), converting the residual to a *measurable* USDe-solvency-to-maturity risk. The fixed-rate
> wrapper changes the risk profile — this is the desk's validated FixedCarry thesis (SC-RDFC-001) in
> action. Data sourced 2026-07-02 (Pendle markets via WebSearch). Schema: `docs/schemas/candidate.schema.json`.
> Rubric: `docs/underwriting_rubric.md`. Underlying stablecoin: `data/stablecoin_cards/examples/usde.stablecoin.md`.

## Candidate
- **candidate_id:** `CAND-PTSUSDE-001`
- **source:** live PT-market scan (Pendle, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `fixed-carry` (buy PT-sUSDe at a discount, hold to maturity, redeem at par)
- **assets:** `["PT-sUSDe (Pendle)", "underlying sUSDe/USDe"]`
- **protocols:** `["Pendle", "Ethena (underlying)"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `PT-sUSDe Mar-2026 ~11.2% implied APY` (fixed, held-to-maturity) — **L2** (Pendle markets, 2026-07-02). Corroborating: PT-sUSDe Jun-2026 at 0.917 par → **9.05% annualized** ($917→$1000); PT-USDe locked ~13.78% in one example. [verified 2026-07-02]
- **suspected_yield_source:** the **fixed discount** a PT buyer locks vs the floating sUSDe yield — i.e. the market pays for rate certainty, PLUS the embedded Ethena delta-neutral carry crystallized as a fixed rate to maturity.
- **Pendle TVL:** `~$977.5M` (PC-PENDLE, DeFiLlama 2026-07-02). Ethena USDe TVL ~$4.45B. [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008) — run through the rubric
- **spread_over_floor_bps:** `~780 bps` (11.2% − 3.4%). Large — but the rubric asks: is it bounded?
- **rubric Q2 (emissions-stripped?):** YES organic — PT carry is NOT emissions; it's a fixed discount. ✓
- **rubric Q3 (bounded vs unbounded tail?):** the fixed-to-maturity structure **BOUNDS the two worst spot-sUSDe tails**:
  - `funding-flip` (the spot-sUSDe REFUSE reason) → **REMOVED**: the rate is LOCKED at purchase; a negative funding regime after you buy does not change your redemption value. This is the key transformation.
  - `mark-to-market` → bounded if **held to maturity** (interim PT price swings don't matter if you redeem at par).
  - **residual tail = USDe/Ethena SOLVENCY-to-maturity** — if USDe de-pegs / Ethena is impaired before maturity, the PT redeems into an impaired asset. This is a **measurable** risk (reserve coverage, funding history, peg record — see usde.stablecoin.md, which notes an Oct-2025 deleveraging event), NOT the unbounded floating tail.
  - `PT exit-liquidity-at-size` — the FixedCarry capacity constraint (SC-RDFC-001: realized-at-size INSUFFICIENT_DATA). Held-to-maturity mitigates the need to exit early, but size-in matters.
- **spread_risk_explanation:** `{fixed-carry premium (rate-certainty demand): partial}`, `{USDe-solvency-to-maturity risk-comp: the main residual — measurable}`, `{PT liquidity/duration: bounded if held to maturity}`.

## Red-team
- **how do we lose?** USDe de-pegs or Ethena is impaired before maturity → PT redeems into a discounted/impaired sUSDe; or forced early exit into thin PT liquidity at a loss.
- **most-fragile assumption:** that USDe/Ethena survives intact to the maturity date. That is the ONE thing to underwrite — and it is measurable (reserve %, funding history, collateral), unlike the unbounded spot funding tail.
- **the sharp nuance:** same underlying, different wrapper, different verdict — spot sUSDe (floating) = lean-REFUSE (unbounded funding tail); PT-sUSDe (fixed, held-to-maturity) = WATCH/conditional (bounded to a measurable solvency tail). **The structure, not the asset, sets the risk.**

## Verdict — UPGRADED to CONDITIONAL-ADVANCE (to paper) after solvency DD (2026-07-02)
- **verdict:** **CONDITIONAL-ADVANCE → PAPER** (was WATCH). The one gating risk — **USDe/Ethena solvency-to-maturity — has now been UNDERWRITTEN and STRESS-VALIDATED**, materially de-risking the residual. A real ~11.2% (8-12% band) whose worst tail (funding-flip) is removed by the fixed-to-maturity wrapper and whose remaining tail (USDe survival) is measurable, monitorable, and has PASSED a live stress test.
- **reason_code:** `fixed_carry_held_to_maturity_bounded` (residual = underlying-solvency-to-maturity — now DD'd)
- **SOLVENCY DD RESULT (sourced 2026-07-02, see `usde.stablecoin.md`):**
  - ✅ **Stress-passed:** in the Oct-2025 $19B deleveraging crash, USDe stayed **overcollateralized ~$66M throughout** (attested live by Chaos Labs / Chainlink / Llama Risk / Harris & Trotter); the $0.65 Binance print was a **Binance-oracle artifact** (DEX only −0.3%); supply $9B→$6B redeemed **without unwinding basis**, short perps **profited**. Design validated under duress; rivals xUSD/deUSD collapsed, USDe did not.
  - ✅ **Solvency provable:** Anchorage (monthly attestation + weekly PoR) + Kraken (weekly PoR) since Jan-2026.
  - ✅ **Funding tail bounded/measurable:** over 3yr, negative funding = 17.5% of days but **longest stretch only 13 days**; reserve (~1.1%) covers short bursts + is bidder-of-last-resort.
  - ⚠️ **Residual (why PAPER not full-live):** reserve is thin (1.1%); reflexivity real (mcap $14.7B→$6.4B in 2mo, survived $8.3B/24h outflow); an **extended negative-funding regime (> reserve coverage)** is the true remaining tail — measurable + monitorable, so it's a *monitored* risk, not a blind one.
- **remaining conditions (paper → live):** (1) **PT exit-liquidity-at-size** (SC-RDFC-001 capacity gate — the one still-open unknown), (2) **held-to-maturity discipline** + maturity-laddering (no MTM panic-exit), (3) **strict single-underlying cap**, (4) live monitors: negative-funding-regime duration + reserve-coverage % + PoR freshness (kill if reserve coverage breaks a floor), (5) full Red-Team sign-off.
- **product_line_fit:** `Enhanced` (paper-track now; live only after PT-liquidity-at-size + cap set).
- **honest bottom line:** this is the strongest real 8-12% the hunt has produced — **~11.2% fixed, funding-tail removed by structure, solvency-tail underwritten + stress-validated + monitorable.** It ADVANCES to paper because the gating risk was measured and passed, NOT waved through. The remaining gate is capacity (can it be sized?), which the FixedCarry track (SC-RDFC-001) already flags as INSUFFICIENT_DATA — so: fundable *thesis*, capacity-limited *scale*.

## Honest note
This is the answer to "is there real 8-12% with bounded risk?": **yes, conditionally** — a fixed-rate
PT crystallizes an 8-12% carry and BOUNDS the floating funding tail, but the yield is still
*compensation for a measurable underlying-solvency risk* (USDe surviving to maturity). It is fundable
IF that one risk is underwritten and capped — which is exactly the desk's job. Not free; earned by
underwriting a *measurable* (not unbounded) tail. Next hunt targets: tokenized private-credit SENIOR
tranches (Centrifuge/Goldfinch/Maple-cash 9-12%, bounded by seniority + first-loss + diversification).

*created_at: 2026-07-02 · sources: Pendle markets (PT-sUSDe Mar-2026 ~11.2% implied, Jun-2026 0.917 par→9.05%, PT-USDe ~13.78%); PC-PENDLE (TVL $977.5M); usde.stablecoin.md (Ethena reserve ~1.1%, Oct-2025 deleverage); ADR-YL-008 + underwriting_rubric.md.*
