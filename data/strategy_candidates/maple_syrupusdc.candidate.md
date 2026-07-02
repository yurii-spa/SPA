# Strategy Candidate — Maple syrupUSDC (institutional credit) → WATCH / CONDITIONAL-ADVANCE

> Edge-hunt cycle 9 (autonomous engine, ADR-YL-008). A NEW risk shape: **onchain institutional
> credit** (counterparty/default risk, distinct from lending/RWA/carry). Introduces a **THIRD verdict
> type** — WATCH / conditional — between clean ADVANCE (USDY) and REFUSE (leverage_loop/sUSDS):
> the spread is **bounded credit-risk-comp**, acceptable in principle but gated on deeper DD given a
> material v1 default precedent. Data sourced 2026-07-02 (DeFiLlama + WebSearch). Schema:
> `docs/schemas/candidate.schema.json`.

## Candidate
- **candidate_id:** `CAND-SYRUP-001`
- **source:** live-yield scan (Maple syrupUSDC, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `credit` (supply USDC to a professionally-underwritten institutional lending pool)
- **assets:** `["syrupUSDC (Maple)"]`
- **protocols:** `["Maple Finance"]`
- **chains:** `["Ethereum"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `syrupUSDC ~5.2% APY` — **L2** (syrupUSDT 4.2%; weighted ~4.9%; individual loans 3–9%, wtd-avg ~4.7–5%). [verified 2026-07-02]
- **suspected_yield_source:** interest paid by **institutional borrowers** (trading firms, market makers, crypto funds) tapping USDC liquidity.
- **Maple TVL:** `~$2.49B` (DeFiLlama `maple-finance`); syrupUSDC pool ~$1.22B, syrupUSDT ~$436M (79% loans / 21% liquidity buffer). [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** `~180 bps` (5.2% − 3.4%).
- **spread_risk_explanation (credit-risk-comp — now largely BOUNDED, sourced):**
  - `counterparty/default risk (institutional borrowers)` — **MITIGATED: most loans overcollateralized 120–170%** with BTC/ETH/stables held at custodians **Anchorage / BitGo / Copper** (Syrup model). Bounded, measurable (collateral ratio + custody).
  - `underwriter-dependence` — professional credit underwriters set terms (a curator-like trust party). Measurable via underwriter track record.
  - `liquidity / withdrawal` — 79% in loans (term), 21% liquidity buffer; exit-at-size depends on the buffer + loan maturities. Measurable.
  - `v1-default precedent` — **Maple v1 (2021–22) was UNDERCOLLATERALIZED and lost LPs ~$50M+** (Orthogonal Trading + M11/Babel defaults, 2022). The Syrup line is the RESTRUCTURED stricter-underwriting model with **~3yr zero principal losses** — but the precedent raises the DD bar.

## Red-team (abbreviated)
- **how do we lose money?** a borrower default that exceeds its (over)collateral in a sharp crash + custody failure; a liquidity-buffer run.
- **most-fragile assumption:** that the 120–170% overcollateralization + reputable custody hold in a fast crash — v1 proved undercollateralized credit CAN lose $50M. The Syrup overcollateralized model materially de-risks this, but credit tail is never zero.
- **hidden leverage / correlation:** borrowers are crypto trading firms → correlated to a crypto drawdown (the moment collateral is most stressed).

## Verdict
- **verdict:** **WATCH / CONDITIONAL-ADVANCE** — the ~180 bps spread IS bounded credit-risk-comp (overcollateralized + reputable custody + 3yr zero-loss Syrup track), which the mandate CAN accept in principle — so NOT a refuse. But it is **NOT a clean advance** (unlike USDY's sovereign T-bill): credit tail + the v1 $50M precedent + underwriter/correlation risk demand deeper DD before paper.
- **reason_code:** `credit_risk_comp_bounded_conditional`
- **conditions to ADVANCE:** (1) per-pool verification that loans are genuinely overcollateralized 120–170% (not v1-style unsecured), (2) underwriter track-record DD + custody (Anchorage/BitGo/Copper) review, (3) a **strict issuer cap** given the v1 precedent, (4) exit-liquidity-at-size vs the 21% buffer, (5) a full Red-Team (mandatory for credit).
- **initial_product_line_fit:** `Enhanced` (a genuine higher-yield-than-floor credit sleeve — if the DD clears).
- **initial_capital_tier_fit:** `$100k–$5M+ (deep pool ~$1.22B; cap concentration)`.
- **next_action:** Maple Protocol Card (underwriting model, custody, default history, per-pool collateralization) → then ADVANCE-to-paper if conditions clear, else HOLD.

## Honesty note
Credit is the hardest spread to judge: the yield is real (borrowers pay it) and now largely bounded
(overcollateralized + custody), but the tail is a correlated default in a crash — exactly when it
matters. The honest verdict is **WATCH**: acceptable in principle, gated on DD the v1 $50M loss taught
the desk to demand. A THIRD verdict type (WATCH) beside clean-ADVANCE (USDY) and REFUSE (leverage_loop
tail-comp / sUSDS gov-safety) — the realistic middle.

*created_at: 2026-07-02 · sources: DeFiLlama maple-finance TVL $2.49B; Maple/Syrup docs + TID/OAK/Modular Capital research (APY ~5.2%, 120-170% overcollateralized, Anchorage/BitGo/Copper custody, v1 $50M 2022 default, Syrup ~3yr zero-loss) + ADR-YL-008.*
