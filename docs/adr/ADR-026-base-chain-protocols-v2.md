# ADR-026 — Base Chain Protocols v2: Moonwell Finance Suspension

**Date:** 2026-06-12  
**Status:** Accepted  
**Authors:** SPA Agent (MP-511)  
**Supersedes:** N/A (extends ADR-025 Base Chain Expansion)

---

## Context

ADR-025 added Moonwell Finance (Base chain, T2) to the SPA adapter registry in Phase 1 monitoring mode (no live allocation until 2026-08-01).

In November 2025, Moonwell Finance suffered a security incident:

- **Mechanism:** Chainlink oracle price manipulation exploit
- **Stolen:** ~$1,000,000 USD
- **Residual bad debt:** ~$3,700,000 USD (uncleared as of 2026-06-12)
- **Protocol response:** Emergency pause; partial recovery; bad debt not fully absorbed

The residual bad debt and unresolved oracle upgrade path represent an unacceptable risk level under SPA RiskPolicy v1.0 TVL-floor and risk-score criteria.

---

## Decision

1. **ADAPTER_STATUS = "suspended"** for `moonwell_base_adapter` effective immediately.
2. **RISK_SCORE elevated:** 0.36 → 0.75 (reflects oracle manipulation history + uncleared bad debt).
3. **validate() returns (False, reason)** while ADAPTER_STATUS == "suspended", preventing any allocation from StrategyAllocator.
4. **Reassessment date:** December 2026. Conditions for reinstatement:
   - Bad debt fully absorbed or insured
   - Chainlink oracle upgrade deployed and audited
   - 90+ days of clean operation post-fix
   - Manual Owner review + new ADR version

---

## Consequences

- Moonwell USDC (Base) is excluded from all portfolio allocations until suspended status is lifted.
- RISK_SCORE = 0.75 is retained in adapter metadata and `data/adapter_status.json` for dashboard/reporting purposes.
- GoLiveChecker criteria are unaffected (Moonwell was Phase 1 monitoring only, never in live allocation path).
- `adapter_status.json` entry updated: `status="suspended"`, `risk_score=0.75`, `bad_debt_usd=3700000`.

---

## References

- MP-511: Update MoonwellBaseAdapter after ADR-026 security finding
- MP-463: Original Moonwell Base adapter (ADR-025 Phase 1)
- ADR-025: Base Chain Expansion Plan
- RiskPolicy v1.0: `spa_core/risk/policy.py`
