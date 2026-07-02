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

## Verdict — UPGRADED to CONDITIONAL-ADVANCE (Core-tier) after per-pool DD (2026-07-02)
- **verdict:** **CONDITIONAL-ADVANCE (Core-tier)** (was WATCH). Per-pool DD materially clears the credit-underwriting concern — BUT reveals the honest current yield is **~4.7%, not 9-12%**, so it is a **Core-band credit sleeve now, not an Enhanced 8-12% rung.**
- **reason_code:** `credit_risk_comp_bounded_conditional` → now `bounded_credit_underwritten` (Core-tier)
- **PER-POOL DD RESULT (sourced 2026-07-02, TID Research + live):**
  - ✅ **Overcollateralization confirmed CONSERVATIVE:** loans backed by **BTC/XRP/cbBTC/HYPE at 125–333%** collateral, **averaging 160%+** across all categories (better than the 120-170% I'd assumed). The credit is genuinely secured, not v1-style unsecured.
  - ✅ **Track record clean:** **NO loan defaults across >$600M cumulative originations** (Syrup). The v1 $50M/2022 loss was the *undercollateralized* old model — this is the restructured secured model, and it has held.
  - ✅ **Exit-liquidity measured:** ~**12 bps flat exit cost, sub-minute settlement** in normal markets; the **redemption queue (up to 30d) is the binding constraint ONLY in stress** — measurable + monitorable.
  - ⚠️ **THE residual (binding condition): BORROWER CONCENTRATION** — top-3 cross-pool borrowers = **~48.8%** of the $1.27B loan book; **single largest ~19.3%**. A single (even overcollateralized) borrower default is a real shock. TID: holding syrupUSDC + syrupUSDT does NOT diversify — same borrowers → compute combined exposure.
  - ⚠️ **HONEST YIELD CORRECTION:** live syrupUSDC APY is **~4.7%** (range 3-9% across loans), net of Maple take + 3.33% delegate fee — **NOT the 9-12% "high-yield tier" figure.** So the flagship, well-underwritten pool is a ~4.7% Core sleeve; the 9-12% Maple is the higher-risk/more-concentrated tier.
- **remaining conditions (→ live):** (1) ✅ overcollat + track: CLEARED; (2) **strict BORROWER-concentration cap** (the binding one — cap single-borrower + top-3 exposure, count syrupUSDC+syrupUSDT combined); (3) stress-exit monitor (redemption-queue length as a kill signal); (4) full Red-Team.
- **product_line_fit:** `Core` at ~4.7% now (was assumed Enhanced) — a bounded, well-underwritten credit sleeve at ~130 bps over floor. Enhanced only if a higher-yield Maple tier is separately DD'd (more concentration).
- **capacity:** pool ~$1.27B loans + $347M liquidity; ~$24M at 2%-of-pool (cap concentration below that).

## Honesty note
Credit is the hardest spread to judge: the yield is real (borrowers pay it) and now largely bounded
(overcollateralized + custody), but the tail is a correlated default in a crash — exactly when it
matters. The honest verdict is **WATCH**: acceptable in principle, gated on DD the v1 $50M loss taught
the desk to demand. A THIRD verdict type (WATCH) beside clean-ADVANCE (USDY) and REFUSE (leverage_loop
tail-comp / sUSDS gov-safety) — the realistic middle.

*created_at: 2026-07-02 · sources: DeFiLlama maple-finance TVL $2.49B; Maple/Syrup docs + TID/OAK/Modular Capital research (APY ~5.2%, 120-170% overcollateralized, Anchorage/BitGo/Copper custody, v1 $50M 2022 default, Syrup ~3yr zero-loss) + ADR-YL-008.*
