# ADR-045: Kelly Criterion Allocation

## Status

Accepted (2026-06-21)

> Relationship to prior work: an earlier note,
> [`docs/ADR_012_dynamic_kelly_sizing.md`](../ADR_012_dynamic_kelly_sizing.md)
> (Dynamic Kelly Sizing with Live APY Covariance), sketched Kelly sizing at the
> covariance level. This ADR supersedes its sizing rationale with the concrete,
> tier-based, half-Kelly model implemented in
> [`spa_core/allocator/kelly_sizer.py`](../../spa_core/allocator/kelly_sizer.py)
> (MP-1231/MP-1232).

## Context

The allocator's default weighting is effectively **equal-weight within the
allowed caps**, which **ignores the differing risk profiles** of protocols: a T1
blue-chip and a T3 speculative venue can receive comparable weight even though
their loss probabilities differ by an order of magnitude. We want position sizes
that are explicitly a function of *both* expected edge and tail risk, while
staying deterministic, read-only, and stdlib-only.

## Decision

Adopt **half-Kelly (50% blend)** position sizing via
`spa_core/allocator/kelly_sizer.py`.

### Financial model

Treat each protocol position as a bet:

- **win** = protocol is *not* exploited → position earns its APY edge over
  risk-free.
- **loss** = protocol suffers an exploit/rug → **100% of the position is lost**.

Classical Kelly:

```
f* = (p·b − q) / b        where  b = APY edge over risk-free (fraction)
                                  p = P(win)  = 1 − hack_prob
                                  q = P(loss) = hack_prob
```

### Tier-based loss (hack) probabilities — annual

| Tier | Loss probability / year | Examples |
|---|---|---|
| **T1** | **0.5%** | Aave, Compound, Morpho Steakhouse — audits, institutional TVL |
| **T2** | **2.0%** | Morpho Blue, Yearn, Euler, Maple, Fluid, Ethena, Usual |
| **T3** | **5.0%** | Pendle YT, private credit — speculative |

### Half-Kelly safety factor

Live sizing applies a **0.5 multiplier** to full-Kelly. Full-Kelly is
over-aggressive under estimation error; half-Kelly retains ~75% of the growth
rate at materially lower variance (standard systematic-trading practice). The
"50% blend" is the half-Kelly weighting blended against the existing
cap-respecting baseline, so Kelly tilts allocation without violating
RiskPolicy/allocator caps.

### Domain constraints

`kelly_sizer.py` is **strictly read-only / advisory**: it does not execute
trades, does not touch `execution/`, uses no LLM, and depends only on stdlib.
Its weights are an input to the allocator, never an override of the RiskPolicy
gate — `approved=False` still wins.

## Consequences

- **Positive:** Sizing now reflects tier risk — T3 positions are sized down
  relative to their raw APY, T1 positions can carry more weight for the same
  edge.
- **Positive:** Deterministic and auditable; the hack-probability assumptions are
  explicit constants tied to tiers, not opaque tuning.
- **Negative:** Hack probabilities are *assumptions*; if a T2 protocol is riskier
  than 2%/yr, Kelly over-allocates. They should be revisited as the incident
  database (ADR_013) accumulates evidence.
- **Negative:** Kelly is sensitive to the APY-edge estimate `b`; a noisy/inflated
  APY feed inflates the optimal fraction — mitigated by the layered, anomaly-
  flagged feeds from ADR-043.
- **Neutral:** Kelly output is bounded by existing per-protocol and T2 caps
  (ADR-019), so it tilts within, never beyond, the risk envelope.

## References

- MP-1231 / MP-1232: Kelly sizer implementation
- [`spa_core/allocator/kelly_sizer.py`](../../spa_core/allocator/kelly_sizer.py)
- [`docs/ADR_012_dynamic_kelly_sizing.md`](../ADR_012_dynamic_kelly_sizing.md) (superseded sizing rationale)
- [ADR-019](./ADR-019-t2-cap-increase.md): T2 caps
- [ADR-041](./ADR-041-adapter-tier-promotion.md): Tier definitions used for hack-probability buckets
