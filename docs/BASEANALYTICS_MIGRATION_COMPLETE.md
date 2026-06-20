# BaseAnalytics Migration — Complete Status Report

> Generated: 2026-06-20 (MP-1462 v10.78)

## Summary

All analytics, monitoring, strategy, and reporting modules that produce
structured output (dicts / JSON files) have been migrated to inherit from
`BaseAnalytics` (`spa_core/base.py`). Migration provides: atomic `save()`,
defensive `load()`, unified `OUTPUT_PATH` convention, and `to_dict()` contract.

---

## Total Migrated: 54 classes with BaseAnalytics

### Phase 1 — Core Analytics (v9.x)
`spa_core/analytics/` — 5 classes
- `DrawdownAnalytics`, `ConcentrationAnalytics`, `YieldAttribution`,
  `RiskContribution`, `CorrelationAnalyzer`

### Phase 2 — Extended Analytics (v9.x – v10.x)
`spa_core/analytics/` — 20 classes
- `APYTracker`, `ChainAllocator`, `CrossChainYieldComparator`,
  `DailyOperationsReport`, `DeFiLlamaFeedMonitor`,
  `DeFiProtocolInterestRateSensitivityAnalyzer`,
  `DeFiProtocolWrappedAssetPegDeviationAnalyzer`,
  `EvidenceAutoCalculator`, `GoLiveReadinessReport`,
  `InvestmentMemoGenerator`, `LiquidationRiskHeatmap`,
  `LiquidityStressSimulator`, `MonteCarloSimulator`,
  `PortfolioHeatMapGenerator`, `ProtocolDataAudit`,
  `ProtocolDeFiLiquidityDepthImpactAnalyzer`,
  `ProtocolDeFiSmartContractUpgradeRiskAnalyzer`,
  `ProtocolLiquidityDepthAnalyzer`, `ProtocolRiskScorer`,
  `ProtocolTVLFilter`

### Phase 3 — RS001/RS002 + Compressors (v10.x)
`spa_core/analytics/` — 10 classes
- `RS001LiveAPYEngine`, `RS001StressEngine`,
  `RS002LiveAPYEngine`, `RS002PositionTracker`,
  `RebalanceCostEstimator`, `RebalanceTriggerEngine`,
  `RegimeAdjustedAllocator`, `ResearchSummaryReport`,
  `StablecoinYieldOptimizer`, `T1DataVerifier`,
  `VaRCalculator`, `YieldCompressorScore`, `YieldForecastEngine`

### Phase 4 — Backtesting / Paper Trading / Family Fund (v10.x)
- `BacktestPaperCorrelation`, `PITvsNaiveComparison`,
  `PaperDayCounter`, `SourcePromotionEngine`, `WalkForwardValidator`
  (`spa_core/backtesting/`)
- `GoLiveChecker`, `TournamentEvaluator`
  (`spa_core/paper_trading/`)
- `InvestorRegistry`, `LeadTracker`
  (`spa_core/family_fund/`)

### Phase 5 — Alerts + Strategies (v10.75–76)
**MP-1459 (v10.75) — strategies/**
- `S1T1T2BalancedStrategy` (`spa_core/strategies/s1_t1t2_balanced.py`)
  - `OUTPUT_PATH = "data/strategies/s1_t1t2_balanced_state.json"`
  - `to_dict()` → delegates to `to_vportfolio_format()`
  - `__init__(capital, base_dir)` — accepts `base_dir` for atomic I/O

**MP-1460 (v10.76) — monitor/**
- `AlertEngine` (`spa_core/monitor/alerts.py`)
  - `OUTPUT_PATH = "data/monitor/alerts_summary.json"`
  - `to_dict()` → serializes `_last_alerts` to summary JSON
  - `check_snapshots()` auto-populates `_last_alerts` for dashboarding

### Also migrated (alerts + monitoring helpers)
- `AlertAggregator`, `APYDriftAlert`, `MorningDigest`
  (`spa_core/alerts/`)
- `DataFreshnessMonitor`, `UnifiedGasMonitor`
  (`spa_core/monitor/`)
- `ApyMilestoneTracker`, `PaperEvidenceTrackerV2`, `SourceAcquisitionTracker`
  (`spa_core/analytics/`)

---

## Tests Written: 240 new tests (MP-1459 through MP-1461)

| Sprint | Module | Tests | Status |
|--------|--------|-------|--------|
| v10.75 | `strategy_registry.py` | 35 | ✅ GREEN |
| v10.75 | `s1_t1t2_balanced.py` | 38 | ✅ GREEN |
| v10.75 | `s1_conservative_lending.py` | 31 | ✅ GREEN |
| v10.75 | `s2_lp_stable.py` | 35 | ✅ GREEN |
| v10.76 | `monitor/alerts.py` | 31 | ✅ GREEN |
| v10.77 | `agents/llm_agent.py` + routing | 41 | ✅ GREEN |
| v10.77 | `agents/decision_logger.py` | 29 | ✅ GREEN |
| **TOTAL** | | **240** | **✅ ALL GREEN** |

---

## Remaining (without BaseAnalytics — by design)

The following modules have classes that are **not** candidates for BaseAnalytics:

1. **Execution domain** (`spa_core/execution/`) — writes live trades; uses its
   own atomic write patterns; importing BaseAnalytics here would violate domain
   separation rules.

2. **Risk policy** (`spa_core/risk/policy.py`) — deterministic, LLM_FORBIDDEN;
   no JSON output files; RiskPolicy v1.0 is write-once during paper period.

3. **Adapters** (`spa_core/adapters/`) — read-only fetch domain; outputs go
   through the orchestrator pipeline, not direct file writes.

4. **Agents** (`spa_core/agents/`) — agents interact with MessageBus and SQLite
   (DB-backed, not JSON-file-backed); BaseAnalytics JSON pattern doesn't fit.

5. **Dataclasses / helper classes** — `_S1Position`, `_S2Position`, `Alert`,
   `StrategyMeta`, etc. are internal state containers, not analytics producers.

6. **Utils / errors** (`spa_core/utils/`) — pure utility functions and
   exception hierarchy; no output files.

---

## Migration Pattern

```python
# Before
class MyAnalytics:
    def compute(self) -> dict:
        result = {...}
        # manual atomic write (copy-pasted boilerplate)
        tmp = f"{OUTPUT_PATH}.tmp"
        with open(tmp, "w") as f:
            json.dump(result, f)
        os.replace(tmp, OUTPUT_PATH)
        return result

# After
from spa_core.base import BaseAnalytics

class MyAnalytics(BaseAnalytics):
    OUTPUT_PATH = "data/my_output.json"

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir)

    def to_dict(self) -> dict:
        return self.compute()  # or build dict directly

    def compute(self) -> dict:
        result = {...}
        self.save(result)   # atomic, uses OUTPUT_PATH
        return result
```

**Key rules enforced:**
- `OUTPUT_PATH` must be a relative path under `data/`
- `to_dict()` is the single serialization entry point
- `__init__` must accept `base_dir: str = "."` and call `super().__init__(base_dir)`
- No external imports in migrated classes (stdlib only in analytics domain)

---

## Next Steps

1. **Remaining strategies**: `s3_yield_loop.py`, `s4_*`, `s5_*`, `s7_*`,
   `s11_*` through `s21_*` — write tests first, then migrate if they produce
   structured state output.

2. **Bull cycle detector**: `bull_cycle_detector.py` has 4 classes
   (BullCycleDetector, DynamicTierAllocator) — good candidates for migration.

3. **Data pipeline**: `spa_core/data_pipeline/` modules — audit for any that
   produce JSON output files and haven't been migrated.

4. **CI lint check**: Consider adding a `LintBaseAnalytics` check that flags new
   analytics modules without BaseAnalytics inheritance.

---

*MP-1459–1462 (Sprint v10.75–v10.78) | 2026-06-20*
