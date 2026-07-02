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
| **RWA floor** | Sovereign T-bill | BUIDL / USYC / USDY / OUSG | ~3.4% | ~$15B | ~$300M (effectively unlimited) | BASELINE (the base) |
| **Overcollat curated** | Overcollateralized lending | blue-chip crypto collateral on **immutable Morpho Blue** (Steakhouse/Gauntlet) | ~4.5–6.5% | ~$6.6B Blue | ~$130M | ADVANCE (Core) |
| **Institutional credit** | Credit (overcollat) | Maple syrupUSDC borrower credit (120–170% collat + custody) | ~9–12% | ~$1.22B | ~$24M | WATCH (Enhanced) |
| **RWA senior credit** | Tranched RWA credit | Centrifuge DROP (senior over TIN junior first-loss + real RWA cashflows) | ~8% | ~$500M | ~$10M | WATCH (Enhanced) |
| **Fixed-rate lending** | Fixed-rate overcollat | Notional fCash (ETH/USDC/WBTC collat) | fixed (rate n/a) | **~$3.1M** | **~$60k (DEAD)** | capacity-dead venue |

*(Ethena PT-sUSDe/PT-USDe 8-11% is deliberately EXCLUDED — it is the concentration we are diversifying
away from. It remains a separate, capped Enhanced rung; ~70% of Pendle TVL is Ethena.)*

## What the ladder reveals (the honest math)

1. **The DEEP non-Ethena capacity is at the floor + overcollat end (3.4–6.5%), not 8-12%.** RWA
   floor (~$15B) and overcollat-curated (~$6.6B) can absorb real size; they pay 3.4–6.5%.
2. **Non-Ethena 8-12% is CREDIT-only, and capacity-limited.** The only non-Ethena rungs paying
   8-12% are Maple (~9-12%) and Centrifuge (~8%) — both credit, combined **~$34M** at a conservative
   2%-of-pool cap. Beyond that you'd over-concentrate in one credit book (the exact mistake Goldfinch
   punished — it wound down with $50M of defaults).
3. **Notional (the "clean" non-Ethena fixed-rate) is capacity-dead (~$3.1M TVL).** Right asset class,
   collapsed venue — not a usable rung today. `reason_code: capacity_dead_venue`.

## The honest portfolio choice (the whole point)

You cannot have all three of {8-12% · diversified · non-Ethena · at scale}. Pick two:

- **Diversified + non-Ethena (any scale):** a blended book — e.g. 40% floor + 30% overcollat + 30%
  capped credit → **~5.5–6% blended**, bounded, no Ethena concentration. *This is the honest
  fundable non-Ethena book — but it is ~6%, not 8-12%.*
- **8-12% + non-Ethena:** concentrate in **credit** (Maple/Centrifuge) → ~9-12%, but ~$34M capacity
  cap + real (bounded) default risk. Not "diversified" — it is a credit bet.
- **8-12% + diversified + at scale:** only reachable by **including Ethena** (PT-sUSDe funding-carry,
  underwritten + stress-validated, capped) — i.e. you re-accept the concentration.

## Recommended non-Ethena ladder (blended, bounded, honest ~6%)

| Weight | Rung | Yield | Why |
|---|---|---|---|
| 40% | RWA floor | ~3.4% | deep, zero-vol base |
| 30% | Steakhouse overcollat (immutable Blue) | ~5.5% | deep, bounded, curator+oracle DD |
| 20% | Maple syrupUSDC | ~10% | credit, overcollat+custody, capped |
| 10% | Centrifuge DROP senior | ~8% | RWA credit, junior first-loss, per-pool DD |
| **100%** | **blended** | **≈ 5.8%** | **non-Ethena, diversified, bounded — ~240 bps over floor** |

**Honest bottom line:** a real, diversified, non-Ethena stablecoin book lands at **~5.5–6%**
(~200-260 bps over the floor) — a genuine, bounded, fundable edge, but **not 8-12%**. The 8-12%
headline in stablecoins is either Ethena funding-carry (concentration) or concentrated credit
(capacity + default risk). Diversifying away from Ethena is the *right* risk decision; it costs
yield. That trade-off — stated plainly — is the product.

## Advisory paper tracks
The credit rungs (Maple, Centrifuge) already accrue as advisory strategy_lab sleeves
(`maple_syrup`, `centrifuge_drop`), alongside the RWA floor (`rwa_sleeve`) — a live, separate-from-
go-live paper record of exactly this non-Ethena stack. Notional is NOT sleeved (capacity-dead).

*created_at: 2026-07-02 · sources: DeFiLlama (notional TVL ~$3.1M, morpho-blue ~$6.6B, maple ~$2.49B/syrupUSDC ~$1.22B, Centrifuge ~$500M, RWA ~$15B), decision_index.md candidates + ADR-YL-008 + underwriting_rubric.md.*
