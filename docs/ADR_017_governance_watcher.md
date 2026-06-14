# ADR-017: Governance Watcher (FEAT-MON-002)

**Status:** Accepted  
**Sprint:** v3.18  
**Date:** 2026-05-28  
**Author:** SPA Dev Agent  

---

## Context

Governance proposals can dramatically change the risk profile of DeFi protocols within hours. For example: an active proposal to increase USDC LTV from 82% to 88% on Aave V3 could change collateral requirements while SPA has an active T3 yield loop position — directly affecting Health Factor projections. The Risk Scoring Engine (ADR-014) scores protocols statically against a snapshot; it cannot react to in-flight governance decisions.

FEAT-MON-001 (Red Flag Monitor) addresses TVL drops and APY spikes but has no governance coverage. This ADR fills that gap.

---

## Decision

Implement `spa_core/alerts/governance_watcher.py` — a **pure-stdlib, deterministic** governance proposal scanner that queries Snapshot GraphQL and Tally REST APIs for active proposals affecting whitelisted protocols.

### Architecture

**Data sources:**
- **Snapshot** (`hub.snapshot.org/graphql`) — covers most major DeFi governance spaces (Aave, Compound, Curve, Lido, Maker, Balancer, Yearn, Uniswap). Free, no API key.
- **Tally** (`api.tally.xyz/query`) — on-chain governors for Compound and Uniswap. Free tier available; degrades gracefully when unavailable.

**Classification** (keyword-based, deterministic):

| Category | Keywords | Severity |
|----------|----------|---------|
| emergency | pause, freeze, halt, exploit, hack | HIGH |
| upgrade | migration, proxy, implementation, deploy | HIGH |
| risk_param | LTV, liquidation threshold, borrow cap, supply cap | HIGH (active) / MEDIUM (closed) |
| parameter_change | interest rate, fee, oracle, emission | MEDIUM |
| treasury | grant, funding, budget, allocation | MEDIUM |
| general | (none of the above) | LOW |

**Risk triggers:** `{risk_param, upgrade, emergency}` — active proposals in these categories are exposed via `get_risk_triggers()` for potential risk-score recalculation.

### Output

`data/governance_proposals.json` — sorted by (active first, HIGH first, start_at), written on demand or via cron.

---

## Consequences

### Positive

- **Proactive risk signal**: SPA can surface active "LTV increase" or "emergency pause" proposals before they pass and affect positions.
- **Score recalculation hook**: `get_risk_triggers()` returns proposals that should trigger risk_scoring_engine.py re-evaluation.
- `has_active_risk_proposals(protocol_key)` is a one-liner check usable by AdaptiveMonitor (e.g., reduce T1 interval if governance risk is active).
- Bootstrap seed data ensures offline-resilient operation.

### Neutral

- Snapshot requires querying each space individually — 8 sequential GraphQL calls per scan. At ≤30s each and 8s timeout, worst case is ~64s scan. Acceptable for hourly cron.
- Tally may require a paid API key for sustained production use. Current implementation degrades gracefully to empty results.

### Negative

- Keyword classifier can produce false positives for ambiguous titles (e.g., "fee switch" might be treasury not parameter_change). Acceptable — severity is conservative (prefers false HIGH over false LOW).
- No historical proposal storage — only current active proposals are tracked.

---

## Integration points

- **AdaptiveMonitor** (ADR-016) can call `has_active_risk_proposals(protocol_key)` to further tighten T1/T2 intervals when governance risk is active.
- **Risk Scoring Engine** (ADR-014) — `get_risk_triggers()` output should feed into a future scheduled re-score.
- **Red Flag Monitor** (ADR-015) — both produce alerts that feed the same risk surface; governance proposals have their own output file to avoid namespace conflicts.

---

## Related ADRs

- ADR-014: Risk Scoring Engine (FEAT-RISK-001)
- ADR-015: Red Flag Monitor Extended (FEAT-MON-001)
- ADR-016: Adaptive Monitoring Intervals (FEAT-MON-003)
