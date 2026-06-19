# CPA Integration Wave Summary (v9.21–v9.70)
Generated: 2026-06-19

## Overview

The CPA (Clean-source Point-in-Time Audited) Integration Wave spanned 50 sprints
(v9.21–v9.70) and delivered the full backtesting methodology infrastructure
required before paper trading can begin.

---

## What We Built

### Core Modules (24 files)

| Module | Path | Tests | Purpose |
|--------|------|-------|---------|
| BacktestGate | `spa_core/backtesting/gate.py` | 40 | 4-state gate system (Backtest/Pre-Paper/Paper/Live) |
| GateAPI | `spa_core/backtesting/gate_api.py` | — | REST-like gate status interface |
| PITEngine | `spa_core/backtesting/pit_engine.py` | 40 | Point-in-time filtering, no look-ahead |
| OwnerAcceptance | `spa_core/backtesting/owner_acceptance.py` | 50 | Formal signing workflow |
| RunPITBacktest | `spa_core/backtesting/replay.py` | 50 | PIT backtest runner with P0/P1A/P2 periods |
| PITvsNaive | `spa_core/backtesting/pit_vs_naive_comparison.py` | 42 | Look-ahead bias quantification (~10.5 pp) |
| PrePaperChecklist | `spa_core/backtesting/pre_paper_checklist.py` | 36 | Pre-paper gate checklist (5 categories) |
| ResearchScenarioMatrix | `spa_core/backtesting/research_scenario_matrix.py` | 49 | 120 scenarios for RS-001/RS-002 |
| ResearchTournament | `spa_core/backtesting/research_tournament.py` | 40 | RS-001 vs RS-002 comparison engine |
| AdaptiveAPYTarget | `spa_core/analytics/adaptive_apy_target.py` | 40 | Regime-adjusted APY targets |
| SourcePromotionEngine | `spa_core/backtesting/cycle_runner_cpa_hook.py` | 54 | State machine for source promotion |
| PaperPeriodSimulator | `spa_core/backtesting/paper_period_simulator.py` | 42 | 4 historical period simulations |
| CPADailyCycle | `spa_core/backtesting/cpa_daily_cycle.py` | 40 | Daily automated CPA check |
| EvidenceScoringAudit | `spa_core/analytics/paper_evidence_tracker_v2.py` | 35 | Evidence accumulation tracker |
| GoLiveReadinessReport | `spa_core/analytics/golive_readiness_report.py` | 52 | Full readiness assessment (MP-1353) |
| RS001LiveAPYEngine | `spa_core/analytics/rs001_live_apy_engine.py` | — | RS-001 live APY tracking |
| RS002LiveAPYEngine | `spa_core/analytics/rs002_live_apy_engine.py` | — | RS-002 live APY tracking |
| ConcentratedLPILModel | `spa_core/analytics/conc_lp_il_model.py` | — | Concentrated LP impermanent loss model |
| GMXResearch | `spa_core/analytics/` | — | GMX v2 BTC/ETH research module |
| GoldProxyResearch | `spa_core/analytics/` | — | Gold proxy yield research |
| PointInTimeWhitelist | `spa_core/backtesting/point_in_time_whitelist.py` | — | Protocol whitelist with PIT snapshots |
| SourcePipelineJSON | `data/backtest/source_pipeline.json` | — | Live source quality state machine |
| MultiStrategyBacktest | `spa_core/backtesting/multi_strategy_backtest.py` | — | S0–S21 multi-strategy backtest |
| DataLoader | `spa_core/backtesting/data_loader.py` | — | PIT-aware historical data loader |

---

## Research Strategies

| Strategy | ID | Target APY | Gross Margin | Status |
|----------|----|-----------|--------------|--------|
| Anti-Crisis Delta-Neutral | RS-001 (S20) | 18.2% | ~18.2% net | **RESEARCH_ONLY** |
| Cashflow LP | RS-002 (S21) | 29.2% gross | ~15% net | **RESEARCH_ONLY** |

Both strategies are **excluded from paper trading** until:
1. RS-001: Ethena/sUSDe source promoted to CLEAN_INCLUDED
2. RS-002: GMX v2 BTC/ETH DeFiLlama pool IDs acquired + historical data verified

---

## Key Findings

### Look-Ahead Bias Quantified
Running the strict PIT backtest vs naive (retroactive) shows:
- **~10.5 pp APY gap** if retroactive data is used (naive overstates by ~10.5 pp)
- PIT mode produces honest historical performance
- Cash drag of **~86.97%** in strict PIT mode (2022–2026) — expected, not a bug
  (most P1B sources had no clean historical data until 2024+)

### Source Quality (as of 2026-06-19)
From `data/backtest/source_pipeline.json`:

| Status | Count | Examples |
|--------|-------|---------|
| `clean_included` | 8 | Aave V2/V3, Compound V2/V3, Morpho Blue, Sky sUSDS, sFRAX, Aave Base |
| `manual_proxy` | 2 | Pendle PT sUSDe, Ethena USDe |
| `pending` | 3 | Morpho Steakhouse, Yearn V3, Euler V2 |
| `review` | 1 | Maple syrupUSDC |
| `source_needed` | 9 | GMX BTC/ETH, BTC/ETH staking, gold proxy, conc LP pools |
| `research_only` | 1 | Delta-neutral |

### Evidence for Live Trading
- **30 evidence points** needed to unlock paper trading gate
- Current: **~0 pts** (track started 2026-06-10, 9 days old as of 2026-06-19)
- Expected achievement: **~2026-07-10** at 1.0 pt/day rate

---

## Gate Status (as of 2026-06-19)

| Gate | Status | Details |
|------|--------|---------|
| ✅ Backtest Gate | **PASS** | P0/P1A/P2 all closed; `pre_paper_backtest_gate.json` |
| ⚠️ Pre-Paper Gate | **NOT_READY** | Hardening audit incomplete; expanded universe STRICT_BLOCKED |
| ⏳ Paper Trading | **NOT_READY** | 1/30 days (29 more needed, ~2026-07-18) |
| 🔒 Live Deployment | **BLOCKED** | All above gates + owner acceptance required |

**Blockers to resolve:**

1. **Hardening audit** — complete `hardening_checklist.json` (est. 7 days)
2. **Expanded universe** — acquire DeFiLlama pool IDs for GMX v2 BTC/ETH (est. 14 days)
3. **Paper track** — accumulate 30 gap-free days (est. 29 more days → ~2026-07-18)
4. **Owner acceptance** — sign `owner_paper_acceptance.json` after paper gate is READY
5. **Source promotions** — promote Morpho Steakhouse, Yearn V3, Euler V2 to `clean_included`

---

## GoLiveReadinessReport (MP-1353)

New module added in v9.69: `spa_core/analytics/golive_readiness_report.py`

Answers the question: **"When can we go live?"**

```bash
# Check readiness (prints to stdout)
python3 -m spa_core.analytics.golive_readiness_report --check

# Check + save to data/reports/golive_readiness_YYYY-MM-DD.json
python3 -m spa_core.analytics.golive_readiness_report --run
```

**Current output (2026-06-19):**
- Overall Status: `BLOCKED`
- Total Score: ~35/100
- Estimated Days to Ready: ~30 days (~2026-07-18)

---

## Next Steps

Priority order to reach READY:

1. **[Priority 1 — 14d]** Acquire DeFiLlama pool IDs for GMX v2 BTC/ETH
   → promotes `gmx_btc`, `gmx_eth` from `source_needed` to `pending`
   → unblocks expanded universe verification

2. **[Priority 2 — 7d]** Complete hardening audit
   → fill `data/backtest/hardening_checklist.json`
   → unlocks Pre-Paper Gate

3. **[Ongoing — 29d]** Paper track continues automatically
   → `com.spa.daily_cycle` runs daily at 08:00
   → gap_monitor.py tracks continuity
   → Evidence accumulates at ~1.0 pt/day

4. **[After Pre-Paper READY]** Sign owner acceptance
   → `python3 -m spa_core.backtesting.owner_acceptance --generate-draft`
   → Review + sign draft → `data/backtest/owner_paper_acceptance.json`

5. **[For live trading]** Deploy Gnosis Safe + deposit $100K USDC
   → ADR-002 go-live transfer rule: READY 7+ days + 30d track + manual review Owner

---

## Architecture Diagram

```
CPA Methodology Flow
====================

Historical APY Data (DeFiLlama)
    │
    ▼
PITEngine (point_in_time_whitelist.py)
    │ filters: only data available at each historical date
    ▼
PIT Backtest (replay.py)
    │ P0: pre-2022 (minimal), P1A: 2022-2024 (core), P2: 2024-2026 (recent)
    ▼
pre_paper_backtest_gate.json → STATUS: PASS ✅
    │
    ▼
Hardening + Expanded Universe checks
    │                        │
    ▼                        ▼
paper_ready_gate.json      source_pipeline.json
STATUS: NOT_READY ❌       (promotion state machine)
    │
    ▼
Owner Acceptance Workflow (owner_acceptance.py)
    │ owner_paper_acceptance.json (not signed yet)
    ▼
Paper Trading (30 days, daily_cycle launchd)
    │ evidence tracked by paper_evidence_tracker_v2.py
    ▼
GoLiveChecker (golive_checker.py) — 26 criteria
    │ 20/26 PASS currently
    ▼
GoLiveReadinessReport (golive_readiness_report.py)
    │ overall_status = BLOCKED → NOT_READY → READY
    ▼
ADR-002 Go-Live Transfer → activate.py (manual "I CONFIRM LIVE TRADING")
```

---

_Generated by MP-1354 (v9.70) — CPA Wave Summary_
