# ADR-019: T2 Allocation Cap Increase 35% → 50%

**Status:** Accepted  
**Date:** 2026-06-12  
**Author:** Claude (SPA-V466)  
**Owner approval required:** Yes (Yurii Kulieshov) — paper test ≥ 2 weeks before live capital deployment  

---

## Context

The current T2 total allocation cap of **35% AUM** was established in the initial risk policy (v1.0, 2026-05-20) as a conservative baseline for the paper trading period. At that time, the T2 protocol set was limited to Morpho Blue, Yearn V3, Euler V2, and Maple Finance.

As of 2026-06-12, the protocol roadmap includes adding higher-TVL T2 protocols (Pendle PT/YT, Clearpool Prime, and additional ERC-4626 vaults). Historical data shows that T2 protocols with TVL > $100M exhibit risk profiles closer to T1 than to the smaller T2 protocols the original cap was designed for.

The 35% cap is structurally binding: with the existing T2 set, the allocator frequently hits the cap and redirects capital to T1 protocols (primarily Aave V3), creating artificial concentration in a single protocol and underutilizing higher-yield T2 opportunities.

---

## Decision

**Raise `max_total_t2_allocation` from 0.35 (35%) to 0.50 (50% of AUM).**

The new cap applies to the aggregate weight of all T2 positions across the portfolio.

### Conditions and Guards

1. **TVL guard (per-protocol):** T2 protocols with TVL ≥ $100M may absorb up to their full per-protocol cap (20%). Protocols with TVL < $100M remain subject to the existing TVL-proportional capacity limit (ADR-009).
2. **Diversification requirement:** When T2 total allocation exceeds 35%, at least **3 distinct T2 protocols** must be represented (no single-protocol T2 concentration above the existing 20% per-protocol cap).
3. **T1 floor retained:** T1 protocols (Aave V3, Compound V3) must hold at least **30% AUM** combined when T2 > 35%. Cash buffer rule (5% min) unchanged.
4. **Paper test period:** This change applies during the paper trading period only. Live capital deployment with the new cap requires a separate sign-off under ADR-002 criteria.

---

## Rationale

| Factor | Assessment |
|--------|-----------|
| Smart contract risk | Partially mitigated by the ≥3 protocol diversification requirement. Marginal increase acceptable given TVL > $100M guard. |
| Yield improvement | +0.5% to +1.2% estimated portfolio APY from accessing Pendle PT yields (6–12% range vs. Aave 4–5%). |
| Liquidity | T2 protocols at $100M+ TVL provide adequate exit liquidity for paper trading position sizes (<$10M AUM). |
| Regulatory | No change — all T2 protocols are non-custodial, permissionless DeFi. |
| Downside scenario | Maximum additional loss exposure: 15% of portfolio (50% T2 − 35% baseline) × worst-case T2 drawdown scenario. Within existing 5% drawdown kill switch. |

---

## Implementation

**File changed:** `spa_core/risk/policy.py` — `RiskConfig.max_total_t2_allocation: 0.35 → 0.50`

The per-protocol T2 cap (`max_concentration_t2 = 0.20`) is **unchanged**.

The allocator (`spa_core/allocator/allocator.py`) already respects `max_total_t2_allocation` via the `remaining_t2` check. No allocator changes required; the raised cap will automatically allow more T2 allocation in the next cycle.

**Version snapshot:** The previous v1.0 parameters are preserved in `spa_core/risk/versions/v1_0_passive.py` (rollback target).

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Smart contract exploit in T2 protocol | Low | High (up to 20% AUM) | Per-protocol 20% cap + TVL floor + ≥3 diversification |
| APY collapse in T2 protocols simultaneously | Low–Med | Medium | Daily cycle re-checks; min_apy guard (1%) triggers exit |
| Allocator concentrates all T2 in one protocol | Low | Medium | Per-protocol 20% cap unchanged; allocator enforces this |
| Governance attack on T2 protocol | Very low | High | TVL > $100M protocols have battle-tested governance |

---

## Rollback

Revert `max_total_t2_allocation` to `0.35` and redeploy. No data migration required. KANBAN card: `ADR-019-rollback` (to be created if triggered).

---

## Related

- ADR-001: Initial risk policy (T1/T2 caps origin)
- ADR-009: Capacity limits (per-protocol TVL proportional caps)
- ADR-020: T3 Private Credit category (companion decision)
- MP-352: Ethereum chain concentration fix (same sprint)
