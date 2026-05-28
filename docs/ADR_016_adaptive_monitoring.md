# ADR-016: Adaptive Monitoring Intervals (FEAT-MON-003)

**Status:** Accepted  
**Sprint:** v3.17  
**Date:** 2026-05-28  
**Author:** SPA Dev Agent  

---

## Context

SPA operates three strategy tiers with fundamentally different risk profiles:

| Tier | Strategy | Risk Window | Consequence of Missed Check |
|------|----------|-------------|----------------------------|
| T1 | Conservative lending (Aave/Compound) | Days–weeks | Low — rates drift slowly |
| T2 | Stable LP (Curve, Uniswap v3) | Hours | Medium — impermanent loss, fee APY changes |
| T3 | Yield loop (leveraged borrow/supply) | Minutes | HIGH — Health Factor can drop from 1.5 to 1.1 in 20 min |

A single fixed polling cadence wastes compute on safe T1 positions while creating dangerous blind spots on T3 loops. ADR-011 (Red Flag Monitor) introduced external signal detection but did not couple it to polling frequency.

---

## Decision

Implement `spa_core/alerts/adaptive_monitor.py` — a **pure-stdlib, deterministic, never-raises** polling-interval calculator that adjusts cadence per position based on tier, Health Factor, and active red flags.

### Interval table

| Condition | Interval | Rationale |
|-----------|----------|-----------|
| T1 (no flags) | 5 h (env: `SPA_T1_INTERVAL`) | Lending rates change on the order of days |
| T2 (no flags) | 30 min | LP IL can compound within hours |
| T3, HF > 1.8 | 5 min | Ample buffer — check less often |
| T3, 1.3 ≤ HF ≤ 1.8 | Lerp 60–180 s | Proportional to risk proximity |
| T3, HF < 1.3 | 60 s | Near critical — aggressive monitoring |
| Any tier, red flag active | `interval × 0.5` | Halve interval for flagged protocols |
| T3, HF < 1.15 | Immediate (escalate) | Liquidation imminent |

### Health Factor interpolation

For T3 positions where `1.3 ≤ HF ≤ 1.8`, the interval is linearly interpolated:

```
t = (HF - 1.3) / (1.8 - 1.3)
interval = 60 + t × (180 - 60)
```

This gives a smooth, monotone response curve rather than stepwise jumps.

---

## Consequences

### Positive

- **T3 safety**: critical HF positions polled every 60 s by default, escalated immediately at HF < 1.15. Closes the 20-minute blindspot identified in user feedback.
- **Resource efficiency**: T1 positions polled 36× less often than T3. On 100 positions this could save ~95% of RPC calls vs a flat 3-minute cadence.
- **Red-flag coupling**: `AdaptiveMonitor` reads `data/red_flags.json` (from FEAT-MON-001) and automatically halves intervals for flagged protocols without requiring caller changes.
- **Env-configurable**: `SPA_T1_INTERVAL`, `SPA_T2_INTERVAL`, `SPA_T3_INTERVAL` allow tuning without code changes.
- **Never raises**: all public methods catch exceptions internally, ensuring the scheduler loop cannot crash due to a single bad position config.

### Neutral

- The module is stateless — it does not persist "last checked at" itself. Callers must track `MonitorConfig.last_checked_at`.
- Red-flag cache TTL is 60 s. A new flag appearing in `red_flags.json` will take up to 60 s to affect intervals.

### Negative

- T3 at 60 s generates significant RPC traffic. Callers should implement rate limiting at the RPC layer (3-fallback already in price_feeds.py).

---

## Alternatives Considered

1. **Static tier intervals** — Simple but ignores real-time HF state. Rejected: T3 near-liquidation requires sub-minute response.
2. **LLM-driven interval suggestion** — Flexible but non-deterministic and violates `LLM_FORBIDDEN_AGENTS` rule for monitoring components. Rejected.
3. **Webhook-based monitoring (e.g. Tenderly Alerts)** — Would eliminate polling entirely but adds external dependency and latency for non-Tenderly protocols. Deferred to FEAT-MON-004 scope.

---

## Related ADRs

- ADR-011: Red Flag Monitor (FEAT-MON-001) — provider of `data/red_flags.json`
- ADR-012: Execution Layer (FEAT-004/005)
- ADR-014: Real Yield Classifier (FEAT-RISK-003)
- ADR-015: Red Flag Monitor Extended (v3.16)
