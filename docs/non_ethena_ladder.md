# The Non-Ethena Fundable Ladder (assembled)

> Owner-directed synthesis (autonomous engine): assemble a fundable stablecoin ladder that
> **diversifies away from Ethena** — by ASSET CLASS, not by chain (chain-hopping to Base just
> re-routes to Ethena; see docs/decision_index.md, rubric meta #7). Every figure sourced 2026-07-02
> (DeFiLlama + WebSearch); capacity = a conservative 2%-of-pool deployable estimate. Research only;
> not a live offering. Source of truth: docs/decision_index.md + docs/underwriting_rubric.md.
> Floor: live rwa_feed ~3.4%.

## The rungs (non-Ethena, by asset class)

| Rung | Asset class | Underlying (NOT Ethena) | Yield | Pool depth | ~2%-of-pool capacity | Verdict |
|---|---|---|---|---|---|---|
| **RWA floor** | Sovereign T-bill | **USYC (best realizer: T+0 USDC atomic)** / BUIDL / USTB (USDY=refuse-as-floor) | ~3.4% | ~$15B | ~$300M (effectively unlimited) | BASELINE (the base) |
| **Overcollat curated** | Overcollateralized lending | blue-chip crypto collateral on **immutable Morpho Blue** (Steakhouse/Gauntlet) | ~4.5–6.5% | ~$6.6B Blue | ~$130M | ADVANCE (Core) |
| **Institutional credit** | Credit (overcollat) | Maple syrupUSDC (160%+ avg collat, 0 defaults >$600M) | **~4.7% live** (9-12%=higher-risk tier) | ~$1.22B | ~$24M | CONDITIONAL-ADVANCE (Core), concentration-capped |
| **RWA senior credit** | Tranched RWA credit | Centrifuge DROP (TIN junior first-loss; US real-estate; TVL ~$1.64B) | ~8% (legacy) | pool-specific | ~$10M | **WATCH — opacity-held** (buffer-depth % not publicly verifiable) |
| **Solana base lending** | Organic lending (non-EVM) | Solana base USDC lending (Kamino/marginfi/Save; native-CCTP, Ethena-isolated-to-Drift) | ~3.5-5% organic | ~$1-2B | ~$20-40M | **ADVANCE (capped)** — real cross-chain non-Ethena diversifier + chain-liveness tail |
| **Fixed-rate lending** | Fixed-rate overcollat | Notional fCash (ETH/USDC/WBTC collat) | fixed (rate n/a) | **~$3.1M** | **~$60k (DEAD)** | capacity-dead venue |

*(Ethena PT-sUSDe/PT-USDe 8-11% is deliberately EXCLUDED — it is the concentration we are diversifying
away from. It remains a separate, capped Enhanced rung; ~70% of Pendle TVL is Ethena.)*

## What the ladder reveals (the honest math)

1. **The DEEP non-Ethena capacity is at the floor + overcollat end (3.4–6.5%), not 8-12%.** RWA
   floor (~$15B) and overcollat-curated (~$6.6B) can absorb real size; they pay 3.4–6.5%.
2. **Non-Ethena 8-12% is CREDIT-only, capacity-limited, AND the well-underwritten flagship is only
   ~4.7% today.** Maple's *flagship* syrupUSDC is **~4.7% live** (160%+ overcollat, 0 defaults) — a
   Core sleeve, not 8-12%. The 8-12% non-Ethena credit is Maple's **higher-risk tier** + Centrifuge
   (~8%), combined ~**$34M** at a 2%-of-pool cap — MORE concentrated / subordinated than the flagship.
   Beyond that you'd over-concentrate in one credit book (the exact mistake Goldfinch punished — it
   wound down with $50M of defaults). So true non-Ethena 8-12% = *higher-risk* credit, capped.
3. **Notional (the "clean" non-Ethena fixed-rate) is capacity-dead (~$3.1M TVL).** Right asset class,
   collapsed venue — not a usable rung today. `reason_code: capacity_dead_venue`.

## The honest portfolio choice (the whole point)

You cannot have all three of {8-12% · diversified · non-Ethena · at scale}. Pick two:

- **Diversified + non-Ethena (any scale):** a blended book — e.g. 40% floor + 30% overcollat + 30%
  capped credit → **~5.5–6% blended**, bounded, no Ethena concentration. *This is the honest
  fundable non-Ethena book — but it is ~6%, not 8-12%.*
- **8-12% + non-Ethena:** concentrate in **higher-risk credit** (Maple's high-yield tier / Centrifuge
  junior) → ~8-12%, but ~$34M capacity cap + real (bounded, more-concentrated) default risk. Not
  "diversified" — it is a credit bet. (The *well-underwritten* Maple flagship is only ~4.7%.)
- **8-12% + diversified + at scale:** only reachable by **including Ethena** (PT-sUSDe funding-carry,
  underwritten + stress-validated, capped) — i.e. you re-accept the concentration.

## Recommended non-Ethena ladder (blended, bounded, honest ~4.75%)

| Weight | Rung | Yield | Why |
|---|---|---|---|
| 40% | RWA floor | ~3.4% | deep, zero-vol base |
| 30% | Steakhouse overcollat (immutable Blue) | ~5.5% | deep, bounded, curator+oracle DD |
| 20% | Maple syrupUSDC | ~4.7% live | credit, 160%+ overcollat, 0-default, concentration-capped |
| 10% | Centrifuge DROP senior | ~8% | RWA credit, junior first-loss, per-pool DD |
| **100%** | **blended** | **≈ 4.75%** | **non-Ethena, diversified, bounded — ~135 bps over floor (corrected: Maple live ~4.7%)** |

**Honest bottom line (corrected 2026-07-02 after Maple live-DD):** a real, diversified, non-Ethena stablecoin book lands at **~4.75–5.5%**
(~135-210 bps over the floor) — even TIGHTER than first assembled, because the flagship credit (Maple syrupUSDC) is **~4.7% live**, not 9-12% (that is Maple's higher-risk tier). At CURRENT 2026 rates the non-Ethena 8-12% band is almost entirely Ethena funding-carry or concentrated higher-risk credit — a genuine, bounded, fundable edge, but **not 8-12%**. The 8-12%
headline in stablecoins is either Ethena funding-carry (concentration) or concentrated credit
(capacity + default risk). Diversifying away from Ethena is the *right* risk decision; it costs
yield. That trade-off — stated plainly — is the product.

## Credit-rung DD status (2026-07-02)
- **Maple syrupUSDC:** DD CLEARED (160%+ overcollat, 0 defaults >$600M) → CONDITIONAL-ADVANCE, but live ~4.7% (Core). Concentration-capped.
- **Centrifuge DROP:** DD ATTEMPTED, **held on off-chain opacity** — the junior-buffer depth % (the binding number) is not publicly verifiable; needs issuer-level data. Stays WATCH.
- **Implication:** the **ADVANCE-grade** (fully-underwritable-from-public-data) non-Ethena book is really **floor + overcollat + Maple-Core ≈ 4.3-4.5%**; the ~8% Centrifuge rung is real-but-unverifiable (WATCH). So the *confidently fundable* non-Ethena edge is even tighter than the blended ~4.75% — Centrifuge's 8% is aspirational-pending-transparency, not bankable today.

## Advisory paper tracks
The credit rungs (Maple, Centrifuge) already accrue as advisory strategy_lab sleeves
(`maple_syrup`, `centrifuge_drop`), alongside the RWA floor (`rwa_sleeve`) — a live, separate-from-
go-live paper record of exactly this non-Ethena stack. Notional is NOT sleeved (capacity-dead).

*created_at: 2026-07-02 · sources: DeFiLlama (notional TVL ~$3.1M, morpho-blue ~$6.6B, maple ~$2.49B/syrupUSDC ~$1.22B, Centrifuge ~$500M, RWA ~$15B), decision_index.md candidates + ADR-YL-008 + underwriting_rubric.md.*
