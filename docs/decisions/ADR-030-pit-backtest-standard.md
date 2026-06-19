# ADR-030: Point-in-Time Backtest Standard

**Status:** Accepted  
**Date:** 2026-06-19  
**Deciders:** SPA Architecture Team  
**MP:** MP-1332 (Sprint v9.48)

---

## Context

SPA uses historical backtesting to evaluate strategy performance and establish
a track record before live capital deployment. A critical failure mode in DeFi
backtesting is **look-ahead bias**: using APY data from protocols that were not
live or verifiable at the simulated date.

The CPA pre-paper backtest handoff (2026-06-19) revealed a stark quantitative
example of this problem:

| Backtest mode | APY (2022–2026) | Cash drag |
|---|---|---|
| **Naive** (all protocols retroactive) | 8–15% | ~10% |
| **Strict PIT** (point-in-time eligible only) | ~1.3% | **86.97%** |

The 86.97% cash drag in strict PIT mode is **correct** — it reflects the genuine
scarcity of verifiable on-chain data for the 2022 period. The naive 8–15% figure
overstates historical performance through look-ahead bias.

---

## Decision

All backtests in SPA **MUST** use Point-In-Time (PIT) data filtering.

### Core rules

1. **Protocol eligibility by date**: Protocol `P` can only appear in a simulation
   on date `D` if `P` was live (deployed and verifiable) before `D`. Protocol
   launch dates are tracked in `PointInTimeWhitelist`.

2. **APY data currency**: Historical APY for protocol `P` on date `D` can only
   use data that existed on `D`. Retroactive APY fills are forbidden.

3. **Cash drag is acceptable**: If no eligible protocol exists for a slot on
   date `D`, that slot remains as cash (0% yield). Cash drag is a legitimate
   and expected output of strict PIT backtesting — it reflects real-world
   information scarcity, not a deficiency of the simulator.

4. **SourceState gating**: Only protocols with `SourceState.CLEAN_INCLUDED`
   can affect strict backtest results. All other states (`PENDING`, `RESEARCH_ONLY`,
   `MANUAL_PROXY`, `REVIEW`, `SOURCE_NEEDED`) are excluded from strict evidence.

5. **Naïve comparisons are illustrative only**: `PITvsNaiveComparison` output
   may be shown for educational purposes (to quantify look-ahead bias magnitude)
   but must never be used as a performance claim.

### Required infrastructure

| Component | File | Role |
|---|---|---|
| `PointInTimeWhitelist` | `spa_core/backtesting/point_in_time_whitelist.py` | Protocol eligibility by date |
| `PITEngine` | `spa_core/backtesting/pit_engine.py` | 100% API-compatible drop-in for BacktestEngine |
| `PITvsNaiveComparison` | `spa_core/backtesting/pit_vs_naive_comparison.py` | Quantifies look-ahead bias |
| `SourcePipeline` | `spa_core/backtesting/source_pipeline.py` | SourceState classification |
| `BacktestGate` | `spa_core/backtesting/gate.py` | Gate file: blocks strict runs if sources unclean |

### SourceState → strict eligibility mapping

| SourceState | Strict eligible | Notes |
|---|---|---|
| `CLEAN_INCLUDED` | ✅ Yes | Full historical APY series verified |
| `PENDING` | ❌ No | Under review — excluded until promoted |
| `MANUAL_PROXY` | ❌ No | Proxy exists but not clean point-in-time |
| `REVIEW` | ❌ No | Needs owner/analyst verification |
| `RESEARCH_ONLY` | ❌ No | Modeled/estimated — no verifiable history |
| `SOURCE_NEEDED` | ❌ No | No data source connected |

### LLM prohibition

**LLM_FORBIDDEN** applies to `pit_engine.py`, `point_in_time_whitelist.py`,
and `source_pipeline.py`. These modules determine what counts as "evidence" for
capital allocation decisions. LLM involvement in evidence determination is a
critical attack surface. All logic must be deterministic and auditable.

---

## Rationale

### Why strict PIT reveals 86.97% cash drag for 2022–2026

In 2022, few DeFi protocols had on-chain APY series that meet the CPA evidence
standard:
- Aave V2 USDC and Compound V2 USDC are among the earliest `CLEAN_INCLUDED` sources
- Morpho (Blue, Steakhouse), Pendle PT, Yearn V3, and most T2 sources did not
  exist or lack verifiable point-in-time series for 2022
- This is accurate — an allocator with strict standards in 2022 would have held
  mostly cash or T1 lending, achieving ~3% APY rather than the naive 8–15%

### Look-ahead bias magnitude

The naive approach retroactively includes all current protocols in 2022 simulations.
This is equivalent to assuming an investor in 2022 could invest in protocols that
hadn't been launched yet — an obvious impossibility. Quantifying this bias:

```
look_ahead_bias = naive_APY - pit_APY ≈ 8–15% − 1.3% ≈ 7–14 percentage points
```

Any SPA performance claim citing the backtest period MUST use PIT figures.

---

## Consequences

### Positive

- Eliminates look-ahead bias from all performance claims
- `PITEngine` is a drop-in for `BacktestEngine` — minimal refactor required
- Cash drag output is honest and communicates the scarcity of clean data
- Creates pressure to expand `CLEAN_INCLUDED` sources (acquisition roadmap)
- Compliant with institutional track record standards

### Negative

- 86.97% cash drag makes 2022–2025 backtest results unimpressive-looking
- Cannot claim high historical APY for marketing until more sources are promoted
- `PointInTimeWhitelist` requires manual updates when new protocols get clean data
- Research strategies (RS-001, RS-002) are nearly invisible in strict mode (ADR-029)

---

## Alternatives Considered

### 1. Use naive backtest with disclaimer

Rejected — disclaimer is insufficient for capital allocation decisions. Users may
ignore disclaimers; strict separation of evidence standards is required.

### 2. Use MANUAL_PROXY sources in strict mode

Rejected — proxies introduce subjective assumptions that cannot be independently
verified. They may be directionally correct but are not auditable evidence.

### 3. Retroactively find historical data for all protocols

Partially accepted — the `Source Promotion Engine` is designed exactly for this.
As new `CLEAN_INCLUDED` sources are added, the PIT backtest automatically improves.
This is the correct long-term path, not a workaround.

---

## Implementation Notes

```python
# Correct: use PITEngine for all strict backtests
from spa_core.backtesting.pit_engine import PITEngine

engine = PITEngine(data_dir="data/backtest")
results = engine.run(strategy, start_date="2022-01-01", end_date="2026-06-19")
# results["cash_drag_pct"] may be high — this is correct and expected

# Wrong: use BacktestEngine with all sources (naive mode)
# from spa_core.backtesting.engine import BacktestEngine  # ← produces look-ahead bias
```

The `PITvsNaiveComparison` tool outputs a clear bias report:

```json
{
  "pit_apy_pct": 1.34,
  "naive_apy_pct": 11.8,
  "look_ahead_bias_pct": 10.46,
  "pit_cash_drag_pct": 86.97,
  "verdict": "SIGNIFICANT_LOOK_AHEAD_BIAS — use PIT figures only"
}
```

---

## References

- ADR-022 (existing backtest framework)
- ADR-029 — Research Strategies Framework (RS-001, RS-002 RESEARCH_ONLY)
- `spa_core/backtesting/point_in_time_whitelist.py`
- `spa_core/backtesting/pit_engine.py`
- `spa_core/backtesting/pit_vs_naive_comparison.py`
- `spa_core/backtesting/source_pipeline.py` — SourceState machine
- MP-1331 — Protocol Data Audit (data acquisition roadmap)
- CPA pre-paper backtest handoff package (2026-06-19)
