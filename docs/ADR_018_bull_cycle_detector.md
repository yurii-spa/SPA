# ADR-018: Bull Cycle Detector + Dynamic Tier Allocation (FEAT-STRAT-001)

**Status:** Accepted  
**Sprint:** v3.19  
**Date:** 2026-05-28  
**Author:** SPA Dev Agent  

---

## Context

DeFi APY markets are cyclical. During bull phases (broadly elevated yields), the risk-return profile of T2 stable LP and T3 yield-loop positions becomes more favourable — higher rates partially offset the additional risk. Keeping T1 at 80% during a bull cycle means leaving significant yield on the table.

The existing Markowitz/Kelly sizing optimises per-protocol allocation given current APYs, but is constrained by hardcoded tier caps. These caps were set conservatively for a neutral market and don't adapt to macro market conditions.

The user highlighted this explicitly: "Исторически было же и 10 и 18 процентов годовых... если мы и идем на риски то агент смотрит не раз в 4 часа а раз в 4 минуты".

---

## Decision

Implement `spa_core/strategies/bull_cycle_detector.py` with two components:

### BullCycleDetector

Reads `data/historical_apy.json` and computes a rolling market-wide median APY across all whitelisted protocols. When this median exceeds the bull threshold (default 8%) for `MIN_BULL_DAYS` (default 7) consecutive calendar days, the market is classified as BULL.

**Cycle logic:**
```
consecutive_bull_days ≥ 7  →  BULL
current_median < threshold × 0.75  →  BEAR
otherwise  →  NEUTRAL
```

**Robustness:** when no historical data is available (new deployment, file missing), defaults to NEUTRAL — never assumes BEAR from a 0% synthetic median.

### DynamicTierAllocator

Applies cycle-aware allocation caps to the output of Kelly/Markowitz sizing:

| Cycle   | T1 max | T2 max | T3 max | Cash min |
|---------|--------|--------|--------|----------|
| BEAR    | 80%    | 15%    | 5%     | 5%       |
| NEUTRAL | 60%    | 30%    | 10%    | 5%       |
| BULL    | 40%    | 40%    | 20%    | 5%       |

All caps are env-overridable (`SPA_BULL_APY_THRESHOLD`, `SPA_MIN_BULL_DAYS`, etc.). The cash buffer minimum (5%) is always enforced — if T1+T2+T3 targets would violate it, all three are scaled down proportionally.

Output: `data/market_cycle.json` — includes cycle, consecutive bull days, per-protocol APY summary, and the active allocation caps.

---

## Consequences

### Positive

- **Dynamic yield capture**: in a BULL market, T3 cap doubles from 10% to 20%, T2 from 30% to 40%. On $100K capital that's +$10K T3 exposure — potentially +$1,500-2,500/year at current rates.
- **Conservative in BEAR**: T1 rises to 80%, T3 drops to 5%. Protects capital in low-yield / high-risk environments.
- **7-day smoothing**: requires 7 consecutive bull days, not just 1. Prevents overreaction to single-day APY spikes (already detected by FEAT-MON-001 red-flag monitor as an anomaly).
- **Integration-ready**: `apply_caps()` wraps existing Kelly/Markowitz output — zero changes needed to upstream optimisers.

### Neutral

- Bull cycle detection is backward-looking (7-day window). A sudden market shift won't be detected for 7 days.
- T1+T2+T3 caps don't sum to exactly 100% by design — they represent independent per-tier maximums. The actual allocation is always further constrained by Kelly/Markowitz.

### Negative

- In a bull cycle, T3 is 20% of capital. At $100K that's $20K in yield loops — Health Factor monitoring via FEAT-MON-003 (AdaptiveMonitor) is critical at these sizes.

---

## Integration

1. `export_data.py` — add `BullCycleDetector().export(dry_run=False)` to write `data/market_cycle.json` every 4h.
2. `paper_trading/engine.py` — in `auto_allocate()`, wrap tier targets through `DynamicTierAllocator.apply_caps()` before sending to Markowitz/Kelly.
3. `AdaptiveMonitor` — T3 cap increases → more T3 positions → more monitoring load; already handled by FEAT-MON-003.

---

## Related ADRs

- ADR-016: Adaptive Monitoring (FEAT-MON-003) — must scale with larger T3 positions in BULL
- ADR-014: Risk Scoring Engine — cycle context should be fed into position-level risk score
- ADR-007: Kelly Sizing — output wrapped by DynamicTierAllocator.apply_caps()
