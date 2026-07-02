# Strategy Candidate — Pendle PT-syrupUSDC (non-Ethena fixed-carry on credit) → CONDITIONAL LEAD (market requires verification)

> Edge-hunt cycle 31 (non-Ethena ladder). Evaluated the *conceptual holy grail* of a non-Ethena
> fixed-carry rung: a Pendle PT on **syrupUSDC (Maple credit)** — it would LOCK the DD-cleared,
> bounded Maple credit rate to maturity (fixed-wrapper removes rate variability) with a NON-Ethena
> underlying. Honest blocker: **a live PT-syrupUSDC market is NOT publicly confirmed** — Pendle's
> confirmed PT stablecoin markets are Aave-USDC / sUSDe / Ethena-linked. Recorded as a structurally
> attractive LEAD requiring verification, NOT an evaluable live candidate (no fabricated rate). Data
> sourced 2026-07-02 (WebSearch). Cross-ref: pt_susde_fixed.candidate.md, maple_syrupusdc.candidate.md.

## Candidate
- **candidate_id:** `CAND-PTSYRUP-001`
- **strategy_type:** `fixed-carry on credit` (Pendle PT on syrupUSDC, held to maturity)
- **assets:** `["PT-syrupUSDC (Pendle, IF listed)", "underlying syrupUSDC (Maple credit)"]`
- **protocols:** `["Pendle", "Maple (underlying)"]`
- **chains:** `["Ethereum"]`

## Why it's structurally attractive (the thesis)
- **Non-Ethena** — underlying is Maple credit, not Ethena funding-carry → real diversification (the owner's goal).
- **Fixed-wrapper bounds variability** — PT locks the rate to maturity (like PT-sUSDe removed the funding-flip tail); here it locks the Maple credit rate.
- **Underlying credit is DD-CLEARED** — Maple syrupUSDC (CAND-SYRUP-001): 160%+ overcollat, 0 defaults >$600M, qualified collateral. The residual is the credit tail (bounded, concentration-capped), NOT an unbounded funding tail.
- **So the risk stack is measurable:** Maple credit (bounded, capped) + PT exit-liquidity + fixed-duration. This is the CLEANEST conceptual non-Ethena fixed-carry rung — IF the market exists.

## The honest blocker
- **Market NOT confirmed:** public sources (Pendle markets, 2026-07-02) show confirmed PT stablecoin markets on **Aave-USDC, sUSDe, Ethena-linked assets (5–11% fixed, 30–180d)** — **no confirmed PT-syrupUSDC pool.** A PT market requires Pendle to have listed syrupUSDC + real liquidity; neither is verified.
- **Rate = requires verification:** IF listed, the implied fixed yield would be ≈ the syrupUSDC rate ± a term premium. syrupUSDC itself is ~4.7% weighted (TID) / 6-10% loan-range (Q1-2026) → a PT-syrupUSDC would plausibly price ~5-8% fixed. **Not asserted — requires verification of the actual market.**

## Verdict
- **verdict:** **CONDITIONAL LEAD — requires market verification** (not a live evaluable candidate). Structurally the strongest non-Ethena fixed-carry idea (fixed lock on DD-cleared bounded credit), but **a live PT-syrupUSDC market + depth is unconfirmed** from public data.
- **reason_code:** `fixed_carry_on_bounded_credit` (the attractive combination) + `market_not_confirmed` (the blocker)
- **to promote:** verify on app.pendle.finance/trade/markets that a PT-syrupUSDC market exists → source its implied APY + maturity + liquidity depth → then run the full rubric (spread → Maple-credit residual [already DD'd] → PT capacity). If it exists at depth, it is a genuine non-Ethena fixed-carry rung combining the two things that worked (fixed-wrapper + bounded credit).
- **if it does NOT exist:** the honest non-Ethena fixed-carry options remain Ethena-underlying PTs (PT-sUSDe/PT-USDe, capped) — reinforcing that non-Ethena fixed-carry at depth is scarce.

## Honest note
This is the one combination that *would* give a bounded, non-Ethena, fixed-rate 5-8% — a fixed lock on
the DD-cleared Maple credit. The desk does not fabricate a rate for a market it cannot confirm exists.
Recorded as a verified-next LEAD, not a decision. The absence of a confirmed PT-syrupUSDC market is
itself informative: Pendle's PT depth is concentrated in Ethena + Aave, not credit — echoing the ladder's
finding that non-Ethena 8-12% (and even non-Ethena fixed-carry) is structurally scarce.

*created_at: 2026-07-02 · sources: WebSearch (Pendle PT stablecoin markets = Aave-USDC/sUSDe/Ethena 5-11% fixed 30-180d; no confirmed PT-syrupUSDC market; Maple syrupUSDC 6-10% range / ~4.7% weighted) + maple_syrupusdc.candidate.md (Maple credit DD) + underwriting_rubric.md.*
