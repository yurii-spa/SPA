# Strategy Candidate — Options-income / structured stablecoin vaults → REFUSE (short-vol)

> Auto-sprint batch (research agent, 2026-07-02). Covered-call / put-selling "yield" vaults + structured
> notes. Rubric: **REFUSE** — the "yield" is an insurance premium for absorbing someone's crash risk
> (short volatility / negative convexity); the headline APY is GROSS premium, not net of the tail.

- **candidate_id:** `CAND-OPTVAULT-001` · **strategy_type:** `options-income / structured` · **chains:** multi
- **products:** DeFi Option Vaults (Ribbon→Aevo, Stryke, Thetanuts) ~10-20%+ advertised; stablecoin options-income vaults 8-15%; principal-"protected" autocallable notes. TradFi grounding: **QYLD covered-call ETF = 12.3% distribution yield but −5.1% total return over a quarter** (headline ≠ net).
- **yield source + tail:** selling optionality = short vol/gamma/**negative convexity**. Premiums small+steady; loss rare+**uncapped** (put-selling into a gap-down; covered-call downside uncapped). Heavy inflows suppress vol then forced unwinds AMPLIFY the next selloff → **correlated tail across all vaults at once**.
- **evidence:** **9 of 13 options-vault protocols wound down / pivoted by late 2024** (market's own verdict); Feb-2025 flash crash IV spiked to Nov-2022 levels; Feb-2026 risk-reversal −19.34 (lowest since 2022, market paying up for exactly this tail).
- **verdict:** **REFUSE** — `short_vol_unpriced_tail` (+ taxonomy: `gross_premium_not_net`, `negative_convexity`, `soft_barrier_principal_at_risk`, `correlated_short_vol_unwind`). Matches the desk's core thesis: yield = tail-compensation, not mispriced carry.
- **narrow exception:** a HARD-buffered zero-coupon-T-bill-floor + capped-option note is *bounded* — but reduces to "RWA floor + a negative-EV lottery ticket" + issuer/contract credit → **bounded but non-fundable** (doesn't beat floor risk-adjusted). DeFi vaults ship SOFT barriers → principal fully at risk → refuse.

*sources: Opium/DeFipedia (DOV consolidation 9/13), ProShares/AlphaArchitect/IBKR (covered-call downside myth), BlockScholes/FTI/CME (2025-26 vol spikes), FINRA (structured notes), QYLD data — accessed 2026-07-02. Per-vault 2026 APY/drawdown = requires verification. + underwriting_rubric.md.*
