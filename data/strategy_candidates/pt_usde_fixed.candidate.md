# Strategy Candidate — Pendle PT-USDe fixed carry (~8.8%) → CONDITIONAL-ADVANCE (same-underlying rung — CAPS with PT-sUSDe)

> Edge-hunt cycle 25 (8-12% ladder build). Evaluated PT-USDe as the next fixed-carry ladder rung — and
> found the **key ladder rule**: PT-USDe and PT-sUSDe share the **SAME underlying (Ethena/USDe
> solvency)**, so laddering them does NOT diversify — it **concentrates Ethena**. Sharpened by a
> systemic fact: **~70% of Pendle's entire TVL (~$6.1B) is Ethena-linked** — so "Pendle PT fixed-carry"
> as a class is largely an Ethena bet. Rule: **cap by UNDERLYING; ladder across underlyings, not
> maturities of the same issuer.** Data sourced 2026-07-02 (Pendle/DeFiLlama via WebSearch). Reuses the
> USDe solvency DD (`usde.stablecoin.md`, cycle 23). Cross-ref: `pt_susde_fixed.candidate.md`.

## Candidate
- **candidate_id:** `CAND-PTUSDE-001`
- **strategy_type:** `fixed-carry` (Pendle PT on USDe/sUSDe, held to maturity)
- **assets:** `["PT-USDe / PT-sUSDe (Pendle)", "underlying USDe (Ethena)"]`
- **protocols:** `["Pendle", "Ethena (underlying)"]`
- **chains:** `["Ethereum"]`

## Yield & spread (SOURCED)
- **apparent_yield:** `PT-USDe/PT-sUSDe Jun-2026 ~$0.917 par → ~8.8–9.05% fixed APY` — **L2** (2026-07-02). (The earlier ~13.78% was a distinct/earlier print; current Ethena-PT range ~8–11%.)
- **spread_over_floor_bps:** `~540 bps` (8.8% − 3.4%). Real 8-12%-band fixed carry.
- **rubric Q2/Q3:** organic (not emissions); fixed-to-maturity **removes the funding-flip tail** (same as PT-sUSDe); residual = **USDe-solvency-to-maturity** — already DD'd + STRESS-VALIDATED (cycle 23: Oct-2025 crash, USDe overcollat throughout).

## THE finding — underlying concentration (why this is NOT incremental diversification)
- **Same underlying as PT-sUSDe:** both redeem into (staked) USDe; both depend on **Ethena solvency to maturity**. Different maturity/wrapper, **identical tail**.
- **Systemic concentration:** **~70% of ALL Pendle TVL (~$6.1B) is Ethena-linked.** The entire "Pendle PT fixed-carry" asset class is dominated by one underlying. Even nominally-different Pendle markets are correlated to Ethena's health via the platform.
- **Ladder rule (the lesson):** capacity scales by adding rungs, but **risk must be capped by UNDERLYING, not by market.** PT-USDe + PT-sUSDe together count against ONE Ethena cap — they do not stack as diversified exposure. **True diversification needs different underlyings** (PT-syrupUSDC = Maple credit; fixed-rate markets = other collateral; RWA), which is where the next rungs must come from.

## Capacity
- Same thin-PT constraint as PT-sUSDe (Ethena pools ARE the deep ones, but 24h vol thin; near-expiry AMM flattening). Adds maturity capacity within the Ethena cap; does NOT raise the Ethena ceiling.

## Verdict
- **verdict:** **CONDITIONAL-ADVANCE (to paper) — as a MATURITY rung inside the Ethena cap, NOT incremental diversification.** Fundable ~8.8% fixed, solvency already underwritten + stress-validated; but its exposure is **the same Ethena tail as PT-sUSDe** and must share one combined cap.
- **reason_code:** `fixed_carry_held_to_maturity_bounded` (same as PT-sUSDe) + **`same_underlying_concentration_cap`** (NEW — different market, identical underlying → one cap, not additive diversification)
- **conditions:** combined Ethena cap across ALL Ethena-PT rungs (PT-sUSDe + PT-USDe + …); maturity-ladder for capacity; held-to-maturity; monitor Ethena solvency/reserve/PoR as ONE risk; the NEXT ladder rungs must be **non-Ethena** underlyings.
- **honest bottom line:** PT-USDe adds fundable *maturity capacity* to the Ethena sleeve, but the ladder's real diversification (and the path past the single-issuer cap toward scale) must come from **different underlyings**, not more Ethena PTs. The ~70%-Ethena-of-Pendle fact is the reason the desk must ladder across issuers, not within one.

*created_at: 2026-07-02 · sources: Pendle/DeFiLlama (PT-USDe Jun-2026 ~$0.917→~8.8%, PT-sUSDe ~9.05%; Pendle TVL ~$1.5B, Ethena ~$6.1B/~70% of Pendle TVL) + usde.stablecoin.md (solvency DD, cycle 23) + underwriting_rubric.md.*
