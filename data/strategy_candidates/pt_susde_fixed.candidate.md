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

## Verdict
- **verdict:** **WATCH → CONDITIONAL-ADVANCE** — a **real ~11.2% (8-12% band) whose worst tail is bounded by the fixed-to-maturity structure**; the residual (USDe-solvency-to-maturity) is measurable, not unbounded. The strongest "real 8-12% with mostly-bounded risk" found so far — but explicitly conditional (USDe is not risk-free).
- **reason_code:** `fixed_carry_held_to_maturity_bounded` (NEW — the fixed wrapper bounds a floating tail; residual = underlying-solvency-to-maturity)
- **conditions to move to PAPER:** (1) **USDe/Ethena solvency DD** — reserve coverage %, funding history, peg-stress record, collateral quality (the one underwriting question), (2) **PT exit-liquidity-at-size** (SC-RDFC-001 capacity gate), (3) **held-to-maturity discipline** (no MTM panic-exit) + maturity-laddering, (4) **strict cap** (single-underlying concentration), (5) full Red-Team.
- **product_line_fit:** `Enhanced` (a genuine higher-yield sleeve if the USDe-solvency DD clears + capped).
- **relation:** extends the validated FixedCarry thesis (SC-RDFC-001) to a concrete high-carry underlying; the honest tension is that the high fixed rate exists *because* the underlying carries real (if measurable) risk — you are paid for underwriting USDe-to-maturity.

## Honest note
This is the answer to "is there real 8-12% with bounded risk?": **yes, conditionally** — a fixed-rate
PT crystallizes an 8-12% carry and BOUNDS the floating funding tail, but the yield is still
*compensation for a measurable underlying-solvency risk* (USDe surviving to maturity). It is fundable
IF that one risk is underwritten and capped — which is exactly the desk's job. Not free; earned by
underwriting a *measurable* (not unbounded) tail. Next hunt targets: tokenized private-credit SENIOR
tranches (Centrifuge/Goldfinch/Maple-cash 9-12%, bounded by seniority + first-loss + diversification).

*created_at: 2026-07-02 · sources: Pendle markets (PT-sUSDe Mar-2026 ~11.2% implied, Jun-2026 0.917 par→9.05%, PT-USDe ~13.78%); PC-PENDLE (TVL $977.5M); usde.stablecoin.md (Ethena reserve ~1.1%, Oct-2025 deleverage); ADR-YL-008 + underwriting_rubric.md.*
