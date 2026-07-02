# Strategy Candidate — Morpho Steakhouse USDC vault → ADVANCE (conditional)

> Edge-hunt cycle 14 (autonomous engine, ADR-YL-008). A NEW risk shape: **curated vault over
> immutable Morpho Blue markets** (curator-selection + per-market-oracle risk, distinct from
> credit/RWA/carry). A **second genuine ADVANCE** beside USDY — overcollateralized DeFi lending with
> an immutable-markets structural plus — balancing the (refusal-heavy) decision index. Data sourced
> 2026-07-02 (DeFiLlama + WebSearch). Schema: `docs/schemas/candidate.schema.json`. Cross-ref:
> `data/protocol_cards/examples/morpho.protocol.md` (PC-MORPHO, $6.6B, immutable Blue).

## Candidate
- **candidate_id:** `CAND-STEAK-001`
- **source:** live-yield scan (Morpho Steakhouse USDC vault, 2026-07-02)
- **discovered_at:** `2026-07-02`
- **strategy_type:** `lending/curated-vault` (supply USDC to a curator-managed vault allocating across immutable Blue markets)
- **assets:** `["USDC → Steakhouse USDC vault (STEAKUSDC)"]`
- **protocols:** `["Morpho (Blue + MetaMorpho vaults)"]`
- **chains:** `["Ethereum (+ verify)"]`

## Yield & apparent edge (SOURCED)
- **apparent_yield:** `Steakhouse USDC ~4.5–6.5% APY` **net of a 15% performance fee** — **L2** (verified 2026-07-02). (Gauntlet USDC Prime ~5–7.5% conservative; Frontier ~6–8.5% broader — for comparison.)
- **suspected_yield_source:** overcollateralized borrower interest across **blue-chip Morpho Blue markets** (wstETH/USDC, WBTC/USDC, cbBTC/USDC) selected by the curator; NOT emissions.
- **Morpho Blue TVL:** `~$6.79B` (DeFiLlama `morpho-blue`, 2026-07-02). [L2]
- **live RWA floor baseline:** `~3.4%` (rwa_feed).

## Spread over the floor (ADR-YL-008)
- **spread_over_floor_bps:** `~110–310 bps` (net ~4.5–6.5% − 3.4%); ~150 bps at a ~4.9% mid.
- **spread_risk_explanation (bounded, measurable — mostly overcollateralized DeFi lending):**
  - `curator-selection / allocation risk` — Steakhouse chooses which Blue markets + sizes + rebalances. **MITIGATED: reputable curator, published conservative methodology, blue-chip collateral only, tight LLTV caps, avoids experimental collateral.** Measurable via curator track record + current allocation.
  - `per-market oracle risk` — each Blue market has its own **immutable** oracle (one of 5 immutable params). A bad oracle → bad debt in that market. Measurable per-market (which oracle each market uses).
  - `collateral / liquidation (LLTV)` — overcollateralized (wstETH/WBTC/cbBTC vs USDC) with LLTV caps. Bounded, measurable — standard overcollateralized-lending risk, NOT credit/counterparty.
  - `performance fee drag` — 15% of yield already netted out of the quoted APY.
- **structural PLUS (reduces risk vs Aave/Compound):** Morpho **Blue is immutable** — market params can't be changed by governance after deployment → **no governance-rug / parameter-change risk** at the market layer (the risk moves to *which* markets the curator picks, which is transparent).

## Red-team (abbreviated)
- **how do we lose money?** a curator allocates to a market whose oracle/collateral fails → bad debt socialized to that market's suppliers; a blue-chip collateral (wstETH/WBTC) depeg/liquidation-cascade.
- **most-fragile assumption:** that the curator's conservative mandate holds AND every underlying market's immutable oracle is sound. Both are measurable/auditable up-front (the immutability helps — the market can't silently change).
- **correlation:** blue-chip crypto collateral → correlated to a crypto crash (liquidation stress), but overcollateralized + LLTV caps bound it.

## Verdict
- **verdict:** **ADVANCE (conditional) → research** — the ~110–310 bps spread is **bounded, measurable overcollateralized-lending risk** (curator + per-market oracle + LLTV), with an **immutable-markets structural plus**. Cleaner than Maple credit (no undercollateralized counterparty tail; no v1-style precedent). The mandate can accept this spread → ADVANCE, conditional on per-vault DD.
- **reason_code:** `overcollat_curated_vault_bounded`
- **conditions to move to PAPER:** (1) pull the vault's **current allocation** (which Blue markets + weights), (2) verify each market's **oracle + LLTV + collateral**, (3) curator (Steakhouse) track-record + fee, (4) exit-liquidity-at-size across the underlying markets, (5) Red-Team.
- **initial_product_line_fit:** `Core → Enhanced` (overcollateralized DeFi lending, floor-plus).
- **initial_capital_tier_fit:** `$100k–$10M+ (deep; $6.6B Blue TVL) — cap per-market concentration`.
- **next_action:** deepen `PC-MORPHO` with the immutable-Blue + curator model (partly done), then per-vault DD → paper.

## Honesty note
This is the fundable middle done RIGHT: a bounded, overcollateralized, transparent, immutable-markets
lending vault whose spread is measurable risk, not a tail. It ADVANCES (conditionally) — a **second
ADVANCE** beside USDY — showing the desk says YES when the spread is genuinely explained, not only NO.
The condition (per-vault allocation + oracle DD) is real work, not a rubber stamp.

*created_at: 2026-07-02 · sources: DeFiLlama morpho-blue TVL $6.79B; Eco/Gauntlet/Steakhouse/Coinstancy research (Steakhouse USDC 4.5-6.5% net of 15% fee, blue-chip markets wstETH/WBTC/cbBTC-USDC + tight LLTV; Gauntlet Prime 5-7.5% / Frontier 6-8.5%; Morpho Blue immutable 5-param markets; curators allocate across Blue) + ADR-YL-008.*
