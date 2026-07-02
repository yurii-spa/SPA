# Strategy Candidate — ETH delta-neutral staking (LST + short perp) → REFUSE

> Auto-sprint batch (research agent, 2026-07-02). Non-stablecoin, non-Ethena yield check: long plain-staking
> LST (stETH/rETH) + short ETH perp (β≈0), income = staking ± funding. Rubric verdict: **REFUSE** — the
> bounded component (staking) is AT the floor; the spread is unbounded funding carry (structurally identical
> to Ethena). Sourced; funding/APR flagged L3 (re-pull live before any re-eval).

- **candidate_id:** `CAND-ETHDN-001` · **strategy_type:** `delta-neutral (ETH LST + perp)` · **chains:** Ethereum
- **legs (L3, 2026):** stETH ~2.6% / rETH ~3.46% staking APR; ETH perp funding ~+3% annualized but NEAR-NEUTRAL (one venue already negative). LST leg alone ~2.6-3.5% → **spread over ~3.4% floor ≈ 0** (staking does NOT beat the floor).
- **spread attribution:** ~260-350 bps staking = bounded protocol reward but sits AT the floor (0 net edge); the only lift above floor = **funding carry = UNBOUNDED, sign-flipping** (same source Ethena harvests) + **LST/ETH depeg residual** (stETH −5% / ~7% discount 2022, NOT hedged by the ETH perp) + **CEX-counterparty** (hedge on Binance/Bybit).
- **verdict:** **REFUSE** — `no_structural_spread_unbounded_funding_tail`. Bounded staking = floor-matching; every bp of *spread* is unbounded funding/depeg/CEX tail. Relabelling collateral as an LST ≠ changing the risk source (still Ethena-style funding carry). Capacity: staking deep (Lido $15.5B) but the HEDGE leg self-limits (your short pushes funding negative) → the edge erodes exactly where you'd size.
- **re-open:** only a funding-harvest sleeve with a hard funding-flip kill + multi-venue counterparty caps, paper-proven to beat floor net-of-drag across a negative-funding regime.

*sources: DeFiLlama tvl/lido $15.5B, tvl/rocket-pool $899M (L4); staking APR spotedcrypto/dextools (L3); ETH funding TheBlock/Coinglass (L3, re-pull); stETH 2022 depeg (L5). + underwriting_rubric.md.*
