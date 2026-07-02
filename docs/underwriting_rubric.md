# Yield Lab — Underwriting Rubric (derived from real decisions)

> A **reusable underwriting rubric distilled from the 10 real, sourced decisions** in
> `docs/decision_index.md` (autonomous engine, cycles 1–19). Every rule below is grounded in a case
> the desk actually decided — this is not an abstract framework, it is the method that produced those
> verdicts, written down so it can be re-applied and audited. Governs research only; never a hard gate
> (RiskPolicy v1.0 is the sole hard gate). ADR: `docs/adr/ADR-YL-008`. Floor: live `data/rwa_feed.py` (~3.4%).

## 1. The one principle
**Judge the spread over the LIVE RWA floor, not the absolute APY. Every basis point of spread must be
explained by a specific, accepted, *measurable* risk — or the yield is rejected.** A high APY is a
reason to *look*, never a reason to *fund*.

## 2. The decision tree (apply in order)

```
Q1. Is there a spread over the live floor at all?
      NO  → NO-EDGE / FLOOR-PARITY. Hold the T-bill floor directly; don't add risk for the same yield.
            └─ case: Aave V3 USDC (~5 bps, trending negative) → hold the floor.
      YES → Q2.

Q2. Strip subsidies (token emissions, points). Does an ORGANIC spread remain?
      NO  → REFUSE (emissions-dependent). The spread is a token-distribution subsidy, not risk-comp.
            Value what you'd keep if rewards → 0.
            └─ case: Curve/Convex stable-LP (~30% of yield = CRV/CVX emissions; organic ≈ floor-parity).
      YES → Q3.

Q3. Is the organic spread explained by a BOUNDED, MEASURABLE risk (collateral ratio, custody,
    issuer quality, per-market oracle) — or by an UNBOUNDED tail (funding-flip, first-loss,
    recursive leverage, governance-attack window)?
      UNBOUNDED tail → REFUSE (the spread cannot bound the tail).
            └─ cases: leverage_loop (recursive-leverage tail), Resolv RLP (first-loss + realized exploit),
               sUSDS (governance-safety precondition: GSM pause-delay < the desk's bar).
      BOUNDED but the spread is THIN vs the tail → WATCH → lean-REFUSE (don't fund at this spread).
            └─ case: sUSDe (~46 bps for funding-flip + CEX-counterparty + 1.1% reserve → too thin).
      BOUNDED and the spread PLAUSIBLY covers the risk → Q4.

Q4. Is the bounded risk cleanly DD-able now, or does it need per-vault / per-issuer work first?
      Needs DD (credit underwriter, per-vault allocation, custody chain) → WATCH / CONDITIONAL-ADVANCE.
            └─ case: Maple syrupUSDC (bounded credit, overcollat + custody, but v1 $50M precedent → DD-gate).
      Clean, sourced, bounded → ADVANCE (conditional on the standard gates).
            └─ cases: Ondo USDY (issuer/custody spread, sourced), Steakhouse USDC (overcollat + immutable
               Blue markets + reputable curator).

Baseline: the RWA floor itself (rwa_sleeve) is spread ≈ 0 by construction — the yardstick, not a trade.
```

## 3. Reason-code taxonomy (verdict ← reason, each cited to a case)

| Verdict | reason_code | What it means | Case |
|---|---|---|---|
| **ADVANCE** | `bounded_issuer_custody` | spread = issuer/custody risk, sourced & bounded | Ondo USDY (~160 bps) |
| **ADVANCE** | `overcollat_curated_vault_bounded` | overcollateralized + immutable markets + reputable curator | Steakhouse USDC (~150 bps) |
| **WATCH** | `credit_risk_comp_bounded_conditional` | bounded credit, but DD-gated (precedent) | Maple (~180 bps) |
| **WATCH→REFUSE** | `funding_carry_riskcomp_unbounded` | funding carry = unbounded tail; thin spread doesn't pay | sUSDe (~46 bps) |
| **REFUSE** | `governance_safety_precondition` | a safety precondition (e.g. GSM pause-delay) is unmet | sUSDS (~25 bps) |
| **REFUSE** | `recursive_leverage_tail` | nominal spread is an unpriced liquidation tail | leverage_loop (realized −8.95%) |
| **REFUSE** | `first_loss_leverage_tranche + realized_exploit` | yield = payment to absorb first loss; tail already fired | Resolv RLP (~2200 bps, $25M exploit) |
| **REFUSE** | `emissions_dependent_unpriced_spread` | the spread is token-emissions subsidy, not risk-comp | Curve/Convex |
| **WATCH→ADVANCE** | `fixed_carry_held_to_maturity_bounded` | a fixed-rate wrapper (PT) bounds a floating tail; residual = underlying-solvency-to-maturity (measurable) | PT-sUSDe (~11.2%, ~780 bps) |
| **REFUSE** | `uncollateralized_credit_realized_default` | uncollat credit; the default tail fired at scale | Goldfinch (wind-down, ~$50M) |
| **WATCH** | `senior_tranche_bounded_by_junior_firstloss` | senior bounded by a genuine junior first-loss + real assets | Centrifuge DROP (~8%) |
| **ADVANCE(capped)** | `same_underlying_concentration_cap` | different market, identical underlying → ONE cap, not additive diversification | PT-USDe vs PT-sUSDe (both Ethena; ~70% of Pendle TVL) |
| **NO-EDGE** | `no_edge_floor_parity` | safest lending ≈ the floor; hold the floor | Aave V3 USDC (~5 bps) |
| **BASELINE** | `is_the_floor` | the yardstick (spread ≈ 0) | rwa_sleeve |

## 4. Honest meta-findings (what the 10 cases prove)

1. **Yield ⟂ fundability.** The spread ranking is *inverse* to fundability: the biggest headline
   (Resolv ~2200 bps) drew the hardest REFUSE (tail fired); the smallest explained spread (USDY
   ~160 bps) is the cleanest ADVANCE. High APY draws scrutiny, not capital.
2. **Spread is bought with accepted risk.** Aave floor-parity proves plain blue-chip lending is
   arbitraged to the floor — so every real basis point of edge is *paid for* with bounded, measured
   incremental risk (issuer, custody, overcollateralized-curated, credit). No risk → no spread.
3. **Same spread, different tail, different verdict.** Aave (floor-parity, thin tail → hold floor)
   vs sUSDe (floor-parity-ish, fat unbounded tail → avoid): the edge is not the yield, it's asking
   *does the spread cover the tail?*
4. **Subsidies aren't edge.** Emissions (Curve) and governance rate-setting (sUSDS) are not
   risk-compensation; strip them and underwrite what remains.
5. **Structure can bound an unbounded tail.** Spot sUSDe (floating funding) = lean-REFUSE; PT-sUSDe (fixed, held-to-maturity) = WATCH/ADVANCE — the fixed-rate wrapper removes the funding-flip tail, leaving a *measurable* underlying-solvency residual. The *structure*, not the asset, sets the risk. This is where real 8-12% bounded yield lives — earned by underwriting a measurable (not unbounded) tail.
5. **Refusals dominate — by design.** 4 REFUSE + 1 lean-REFUSE + 1 NO-EDGE vs 2 ADVANCE + 1 WATCH.
   A desk whose product is *disciplined refusal* is more trustworthy than one selling the top number.

## 5. How to use
For any new candidate: run the Q1→Q4 tree, assign a reason_code from §3 (or add a new one, cited to
the case that motivated it), and append the row to `docs/decision_index.md`. The rubric is *derived
from* cases, so it grows as new cases teach new reasons — the taxonomy is a living record of the
desk's underwriting judgment, auditable against every decision that produced it.

*Research-layer artifact; moves no capital; never read by RiskPolicy/execution. Derived from
`docs/decision_index.md` (10 decisions, 2026-07-02). Updated by the value-engine.*
