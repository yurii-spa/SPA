# ADR-041: Adapter Tier Promotion Criteria

## Status

Accepted (2026-06-20)

## Context

SPA maintains three adapter tiers to categorize DeFi protocols by maturity,
security, and capital suitability:

- **T1** — Blue-chip protocols (Aave V3, Compound V3, Morpho Steakhouse, Spark).
  Eligible for full paper-trading allocation. Highest TVL, most audits,
  longest mainnet track record.

- **T2** — Established protocols (Morpho Blue, Euler V2, Maple, Fluid, etc.).
  `research_only` flag may be True (paper validation required) or False
  (allocation eligible after RiskPolicy gate). TVL ≥ $100M, at least one audit.

- **T3** — Experimental / speculative (Ethena sUSDe, Pendle YT).
  `RESEARCH_ONLY=True` always. Advisory-only — no capital is allocated
  automatically. Require explicit Board sign-off to promote.

Historically, tier assignments were made ad-hoc. This ADR formalises the
promotion criteria so the process is auditable, deterministic, and consistent
across sprints.

**Trigger:** MP-1550 (v11.66) — adding Fluid (new) and Notional V3 as T2
`research_only=True` adapters, requiring a clear path toward production status.

## Decision

### T3 → T2 Promotion

A T3 adapter may be promoted to T2 when **all** of the following hold:

1. **Mainnet age** — ≥ 6 months of continuous mainnet operation on a production
   network (Ethereum mainnet, Arbitrum, Optimism, or Base).

2. **TVL floor** — Total Value Locked ≥ $100M at the time of review, verified
   on DeFiLlama. TVL must have been above $100M for at least 90 of the
   preceding 180 days.

3. **Security audit** — At least one completed audit by a reputable firm.
   Acceptable auditors include (non-exhaustive): Sigma Prime, Trail of Bits,
   OpenZeppelin, ConsenSys Diligence, ABDK Consulting, Certik, Spearbit,
   Code4rena (community contest), Sherlock.

4. **Clean security record** — No critical or high-severity vulnerabilities
   in the 12 months preceding the promotion review. Medium findings are
   acceptable if mitigated.

5. **APY stability** — DeFiLlama pool APY variance < 20% week-over-week for
   at least 8 weeks. Spike events must be explainable (e.g., DEX activity).

6. **Board review + ADR** — Promotion documented in a new ADR, reviewed and
   accepted by the Owner. The ADR must reference the security audit report(s)
   and DeFiLlama pool ID.

### T2 → T1 Promotion

A T2 adapter may be promoted to T1 when **all T3→T2 criteria** plus:

1. **Extended mainnet age** — ≥ 2 years of continuous mainnet operation.

2. **Elevated TVL floor** — TVL ≥ $500M sustained for ≥ 6 months.

3. **Multiple independent audits** — At least 2 independent audits from
   different firms.

4. **Battle-tested** — Protocol has survived at least one significant market
   stress event (e.g., > 30% ETH price drop, liquidity crisis, stablecoin
   de-peg event) without a security incident or loss of user funds.

5. **Exit latency ≤ 1h** — Protocol supports instant or near-instant
   withdrawals (same-block or within 1 block). Epoch-based or queued exit
   protocols cannot be T1.

6. **Board review + ADR** — Separate ADR for T1 promotion, signed by Owner.

### Demotion Criteria

Tier demotion is triggered by any of the following; Owner must confirm within
24 hours:

| Condition | Action |
|---|---|
| Security incident (any loss of funds, hack, exploit) | Immediate SUSPENDED; demotion to T3 after 6-month clean record |
| TVL drops below $50M for > 30 days | Review: potential T1→T2 or T2→T3 demotion |
| APY consistently < 0.5% for > 60 days | Remove from registry (zero yield protocols waste gas) |
| Protocol abandons mainnet or enters wind-down | Remove from registry |
| Governance exploit or admin-key compromise | Immediate SUSPENDED |

### SUSPENDED Status

ADR-026 (Extra Finance, Moonwell) established the SUSPENDED sub-status for T3
adapters affected by hacks. Suspended adapters:
- Remain in the registry with `SUSPENDED = True`
- Are excluded from cycle allocation automatically
- Can only be re-activated after 6 months clean + explicit Board un-suspend

### research_only → False Graduation

Within a given tier, a `research_only=True` adapter can become
`research_only=False` (allocation-eligible) after:

1. ≥ 30 days of paper-trading data with no anomalies
2. RiskPolicy gate passes consistently (no blocks for 30 days)
3. Owner manually sets `research_only=False` in registry.py and pushes ADR
4. The GoLiveChecker `adapter_audit` criterion must re-pass after the change

### New Adapter Default

All newly added adapters start with:
- T3: `RESEARCH_ONLY=True`, speculative flag
- T2: `research_only=True` until paper-validation complete (this ADR)
- T1: Not directly add-able; must be promoted from T2

## Consequences

- **Positive:** Provides a reproducible, auditable path from experimental →
  production for any DeFi protocol adapter.
- **Positive:** Reduces ad-hoc decision-making; Owner reviews are bounded by
  explicit criteria.
- **Positive:** Fluid Protocol USDC/USDT and Notional V3 now have a defined
  graduation path (both currently T2 `research_only=True`).
- **Negative:** Promotion process requires Owner time for each ADR.
- **Neutral:** SUSPENDED status from ADR-026 is preserved and codified here.

## Affected Adapters (as of 2026-06-20)

| Adapter | Current Tier | research_only | Eligible for promotion? |
|---|---|---|---|
| Fluid USDC (fluid_usdc) | T2 | True | → research_only=False after 30d paper track |
| Fluid USDT (fluid_usdt) | T2 | True | → research_only=False after 30d paper track |
| Notional V3 (notional_v3) | T2 | True | → research_only=False after 30d paper track |
| Ethena sUSDe (susde) | T3 | False | → T2 eligible: TVL ✓, audit ✓, APY volatile |
| Pendle (pendle) | T3 | False | → T2 ineligible: speculative, T3-SPEC per ADR-021 |
| Extra Finance (extra_finance_base) | T3 SUSPENDED | — | Suspended per ADR-026 |
| Moonwell (moonwell_base) | T3 SUSPENDED | — | Suspended per ADR-026 |

## References

- ADR-002: Go-live transfer rule
- ADR-019: T2 total cap raised to 50%
- ADR-020: T3 Private Credit category
- ADR-021: Pendle YT T3-SPEC advisory only
- ADR-025: Base chain adapter monitoring
- ADR-026: Extra Finance + Moonwell SUSPENDED
- ADR-040: Strategy demotion policy (parallel for strategies)
- MP-1547: Fluid + Notional V3 T2 adapters
- MP-1550: ADR-041 tier promotion criteria
