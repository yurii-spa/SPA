# ADR-020: T3 Private Credit / RWA Category — 15% AUM Cap

**Status:** Accepted  
**Date:** 2026-06-12  
**Author:** Claude (SPA-V466)  
**Owner approval required:** Yes (Yurii Kulieshov) — paper test ≥ 2 weeks before live capital deployment  

---

## Context

The current risk policy recognises two protocol tiers: T1 (blue-chip, battle-tested) and T2 (established DeFi, audited). A growing class of on-chain credit protocols — Private Credit and Real-World Asset (RWA) vaults — does not fit neatly into either tier. These protocols offer significantly higher yields (8–18% APY on USDC) but carry structural risks absent from T1/T2: credit default risk, lock-up periods, no instant redemption, and off-chain legal counterparty exposure.

Protocols in scope:

| Protocol | Type | Est. APY (USDC) | TVL | Notes |
|----------|------|-----------------|-----|-------|
| Maple Finance | Private Credit | 8–12% | $500M+ | Accredited borrowers only (institutional) |
| Clearpool Prime | Private Credit | 9–15% | $150M+ | Permissioned vaults |
| Goldfinch | Private Credit | 8–13% | $100M+ | Emerging-market lending |
| Ondo USDY | RWA (T-bills) | 4.5–5.5% | $400M+ | US Treasuries-backed |
| Mountain USDM | RWA (T-bills) | 5–6% | $150M+ | Yield-bearing stablecoin |

Note: Maple Finance is currently classified as T2 in the adapter registry. This ADR creates the T3 category for future adapters; existing Maple positions remain classified as T2 until a separate adapter migration ADR is approved.

---

## Decision

**Create a new tier T3 (Private Credit / RWA) with a portfolio-level cap of 15% AUM.**

`RiskConfig.max_total_t3_allocation = 0.15` is added to the risk policy.

### Eligibility Criteria for T3

A protocol qualifies for T3 allocation only if **all** of the following hold:

1. **Audit:** At least one recognised security audit with no unresolved critical/high findings.
2. **TVL floor:** Protocol TVL ≥ $20M at time of allocation.
3. **Track record:** Protocol live on-chain ≥ 6 months with no principal loss events.
4. **Lock period documentation:** Lock-up / redemption delay fully documented in adapter code.
5. **Minimum hold:** SPA position must be held ≥ 30 days; early exit may incur queue delays.

### Special Operational Rules

- **No instant redemption assumption:** Cycle runner must not model T3 positions as instantly liquid. Redemption queue delays (1–30 days typical) must be tracked.
- **No re-deployment during lock:** If a T3 position is in redemption queue, the notional is still counted against the T3 cap.
- **Separate per-protocol cap for T3:** 10% AUM max per T3 protocol (vs. 20% for T2, 40% for T1).
- **T3 + T2 combined cap:** T2 + T3 combined must not exceed 55% AUM (protecting T1 floor).

---

## Rationale

| Factor | Assessment |
|--------|-----------|
| Yield uplift | +1.5% to +3.5% portfolio APY (15% × 10–23% T3 APY premium over T1). Material upside. |
| Credit risk | Real — borrower default possible. Mitigated by: max 15% total T3 exposure, ≥$20M TVL floor, track record gate. |
| Liquidity risk | Significant — no instant redemption. Mitigated by: 30-day min hold, separate cap, cycle runner lock awareness. |
| Regulatory / legal | Off-chain legal agreements involved (Maple, Clearpool). SPA operates in paper-trading mode; no legal exposure during paper period. |
| Operational complexity | Increased — redemption queue tracking required in cycle runner. Deferred to implementation MP for T3 adapter. |

---

## Implementation

**Files changed:**

1. `spa_core/risk/policy.py` — `RiskConfig.max_total_t3_allocation: float = 0.15` added.
2. `docs/adr/ADR-020-t3-private-credit.md` — this document.

**Not yet implemented (future MPs):**

- T3 adapter base class (`spa_core/adapters/t3_base.py`) — tracks lock period, redemption queue.
- Allocator T3 support (`spa_core/allocator/allocator.py`) — enforce 10% per-protocol cap, T2+T3 combined cap.
- Cycle runner awareness of T3 liquidity constraints.
- `check_new_position` in policy.py — T3-specific validation branch.

Until those MPs are implemented, the `max_total_t3_allocation` field is present in `RiskConfig` but not enforced by the allocator. No T3 positions will be opened until a T3 adapter is registered.

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Borrower default (Maple/Clearpool) | Low–Med | High (up to 10% AUM) | Per-protocol 10% T3 cap; TVL + track record gates |
| Regulatory action on RWA protocols | Low | Med–High | Paper-only initially; legal review before live deployment |
| Redemption queue > 30 days during market stress | Medium | Medium | 30-day hold requirement + liquidity reserve (5% cash buffer) |
| Smart contract exploit in T3 | Low | High | Audit gate + track record ≥ 6 months |
| T3 APY collapse making position uneconomical | Medium | Low | min_apy guard (1%) + daily cycle review |

---

## Rollback

Remove `max_total_t3_allocation` from `RiskConfig` and close any T3 positions via normal rebalance. Since no T3 adapters are registered yet, rollback before any T3 allocation is a no-op (field removal only).

---

## Related

- ADR-001: Initial risk policy (T1/T2 caps origin)
- ADR-009: Capacity limits
- ADR-019: T2 cap increase 35%→50% (companion decision, same sprint)
- MP-352: Ethereum chain concentration fix (same sprint)
- Future MP: T3 adapter base class implementation
- Future MP: Allocator T3 support (10% per-protocol cap, T2+T3 combined 55% cap)
