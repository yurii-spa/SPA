# ADR-049: Maple Finance Tier Evaluation (T2 vs T1) + Centrifuge RWA Watchlist

| Field            | Value                                            |
|------------------|--------------------------------------------------|
| **Date**         | 2026-06-21                                       |
| **Status**       | PROPOSED                                          |
| **Author**       | Claude (SPA agent)                               |
| **Approved by**  | _pending_ (Yurii)                                |
| **Policy ver.**  | v1.0 (no change applied — evaluation record)     |
| **ADR number**   | ADR-049                                           |

> **Numbering note:** latest existing ADR was ADR-048; ADR-049 is the next free
> number. Criteria framework referenced throughout is **ADR-041** (Adapter Tier
> Promotion Criteria).

---

## Context

DeFiLlama research surfaced the Maple Finance USDC institutional-lending pool at
**$3.1B TVL / 4.94% APY** — larger than several protocols SPA currently tiers as
T1, and the largest single pool by TVL among our T2 adapters. This raised the
question: should Maple be promoted from **T2** to **T1**?

Current Maple state in SPA:
- Registry: `("maple", "T2", MapleAdapter)` in `spa_core/adapters/__init__.py`.
- Adapter: `spa_core/adapters/maple.py` — `tier="T2"`, `RISK_SCORE=0.50`,
  **`EXIT_LATENCY_HOURS=336.0`** (~14-day epoch-based withdrawal queue).
- Current paper allocation: **$2,231.48 / $100,000 = 2.23%** of portfolio
  (`data/current_positions.json`, 2026-06-20).

This ADR also evaluates **Centrifuge** (RWA protocol) as a candidate new adapter.

---

## TVL / APY Comparison

| Protocol | TVL | APY | SPA Tier | Exit latency | Risk type |
|---|---:|---:|---|---|---|
| Aave V3 (Ethereum) | $5.0B | 3.14% | **T1** | instant | Smart-contract |
| Morpho Blue | $4.0B | 4.65% | T2 | instant | Smart-contract (isolated) |
| **Maple USDC** | **$3.1B** | **4.94%** | **T2** | **~336h (queue)** | **Credit / borrower default** |
| Compound V3 (Comet) | $1.9B | 3.27% | **T1** | instant | Smart-contract |
| Centrifuge (RWA) | $370–868M | 4.8–5.7% | _none_ | days–weeks | Legal / issuer / off-chain |

Maple's TVL and APY are genuinely attractive — TVL ~1.6× Compound's, APY higher
than both T1 money-markets. On those two axes alone, a promotion looks justified.

---

## Maple — T1 Criteria Assessment (per ADR-041 "T2 → T1")

ADR-041 requires **all** T3→T2 criteria **plus** five additional T1 gates. Maple
passes the maturity/TVL/audit bar but fails two T1-specific gates outright:

| ADR-041 T1 criterion | Maple | Verdict |
|---|---|---|
| Extended mainnet age ≥ 2 yrs | Launched 2021 (~3+ yrs) | ✅ Pass |
| Elevated TVL floor ≥ $500M / 6 mo | $3.1B | ✅ Pass |
| ≥ 2 independent audits | Multiple audits, institutional clientele | ✅ Pass (subject to audit-report cite) |
| **Battle-tested, no loss of funds** | **2022 bear market: bad-debt / borrower defaults (Orthogonal, Auros)** | ❌ **Fail** |
| **Exit latency ≤ 1h** | **`EXIT_LATENCY_HOURS=336.0` — epoch withdrawal queue** | ❌ **Fail (hard)** |

### Decisive disqualifiers

1. **Exit latency (ADR-041 T1 #5).** T1 explicitly forbids epoch-based or queued
   exit: *"Epoch-based or queued exit protocols cannot be T1."* Maple
   redemptions clear through a withdrawal queue (days→weeks), declared
   conservatively at 336h in the adapter. This is a **structural, non-waivable**
   bar — TVL size cannot compensate for it.

2. **Loss-of-funds history (ADR-041 T1 #4).** T1 requires surviving a stress
   event *"without a security incident or loss of user funds."* Maple lenders
   took realized losses to borrower defaults in the 2022 cycle. Even though this
   was credit risk (not a smart-contract exploit), the criterion is about lender
   capital preservation, which was not met.

### Risk-model note

T1 in SPA implicitly denotes **smart-contract money-markets** where the dominant
risk is contract/oracle failure, collateral is on-chain and over-collateralized,
and exit is instant. Maple is a **credit protocol**: principal risk is
**borrower default**, partially under-collateralized, and intermediated by
off-chain underwriting. This is a *different risk category*, not merely a
"smaller/larger T1" — it does not belong in the same allocation bucket as Aave/
Compound regardless of headline TVL.

---

## Decision

1. **Maple stays T2.** It fails two ADR-041 T1 gates (exit latency ≤ 1h;
   battle-tested-without-loss). TVL/APY superiority does not override structural
   credit + illiquidity risk. No change to `tier="T2"` or the registry.

2. **Allocation-cap consideration: T2 per-protocol cap 20% → 25% for Maple-class
   credit exposure** is recorded here as a *proposal to be decided as part of the
   Kelly allocation discussion* (ADR-045 / ADR-048), **not** applied by this ADR.
   Rationale: Maple's depth ($3.1B) and yield make a modestly higher individual
   cap defensible — but only within the existing **illiquid-bucket ≤25%**
   constraint already enforced by the allocator (`EXIT_LATENCY_HOURS>72h` ⇒
   illiquid bucket). Any cap change requires an explicit RiskPolicy ADR; v1.0 is
   unchanged here.

3. **Centrifuge → T3 watchlist, no allocation.** Add as a watchlist entry only
   (no adapter wired into cycle allocation yet). RWA introduces legal/issuer/
   off-chain-redemption risk that SPA's deterministic RiskPolicy does not yet
   model (no on-chain enforceable liquidation, jurisdictional/SPV risk, manual
   redemption). Too exotic for the current risk model. Revisit when SPA has an
   RWA-specific risk sub-policy (analogous to the Sky/sUSDS GSM-pause gate).

---

## Centrifuge — Evaluation Summary

| Dimension | Centrifuge |
|---|---|
| TVL | $370–868M (varies by pool) |
| APY | 4.8–5.7% |
| Asset class | RWA — invoices, trade finance, treasuries |
| Dominant risk | **Legal / issuer default / off-chain redemption**, not smart-contract |
| Exit | Pool-dependent; days→weeks, manual redemption |
| ADR-041 T2 fit | Fails risk-model fit: RiskPolicy has no RWA primitives |
| **Recommendation** | **T3 watchlist, RESEARCH_ONLY, 0% allocation** |

---

## Consequences

- **Positive:** Tier decisions remain anchored to ADR-041's explicit, auditable
  gates rather than headline TVL. Exit-latency and loss-history bars are upheld.
- **Positive:** Documents a clear, principled answer ("no") to a recurring
  "but it's huge — promote it" question, reusable for future large-TVL credit
  protocols (e.g. other private-credit pools).
- **Neutral:** Maple remains allocation-eligible at T2; today's 2.23% weight is
  well within both the 20% per-protocol and ≤25% illiquid-bucket caps.
- **Open item (deferred to Kelly ADR):** whether Maple's individual T2 cap rises
  to 25%. Not decided here. RiskPolicy version stays **v1.0**.
- **Negative:** Centrifuge yield (4.8–5.7%) is left on the table until an RWA
  risk sub-policy exists.

## References

- ADR-041 — Adapter Tier Promotion Criteria (T2→T1 gates, demotion rules)
- ADR-045 — Kelly Criterion Allocation
- ADR-048 — Advisory Kelly Optimizer Parameters
- `spa_core/adapters/maple.py` (`EXIT_LATENCY_HOURS=336.0`, `tier="T2"`)
- `data/current_positions.json` (Maple = $2,231.48, 2026-06-20)
- DeFiLlama: Maple USDC pool ($3.1B / 4.94%), Centrifuge RWA pools
