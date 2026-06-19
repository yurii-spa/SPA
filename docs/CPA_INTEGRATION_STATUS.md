# CPA Integration Status

Date: 2026-06-19
Sprint: v9.37–v9.38
Tests (CPA-related, tests/): 500+ tests across 13 CPA test files

## Completed MPs

| MP | Sprint | Module | Tests | Status |
|---|---|---|---|---|
| MP-1300 | v9.16 | point_in_time_whitelist.py | 66 | ✅ |
| MP-1301 | v9.17 | gate.py + gate_api.py | 40 | ✅ |
| MP-1302 | v9.18 | s20_anticrisis_research.py | 76 | ✅ |
| MP-1303 | v9.19 | s21_cashflow_research.py | 52 | ✅ |
| MP-1304 | v9.20 | source_pipeline.py | 54 | ✅ |
| MP-1305 | v9.21 | owner_acceptance.py | 50 | ✅ |
| MP-1306 | v9.22 | source_promotion_engine.py | 54 | ✅ |
| MP-1307 | v9.28 | research_scenario_matrix.py | — | ✅ |
| MP-1308 | v9.29 | gmx_research.py (adapter) | — | ✅ |
| MP-1309 | v9.30 | conc_lp_il_model.py | — | ✅ |
| MP-1310 | v9.31 | gold_proxy_research.py (adapter) | — | ✅ |
| MP-1311 | v9.32 | rs001_live_apy_engine.py | 35 | ✅ |
| MP-1312 | v9.33 | rs002_live_apy_engine.py | — | ✅ |
| MP-1321 | v9.37 | pre_paper_checklist.py | 36 | ✅ |

## Module Status

| Module | Path | Status | Notes |
|---|---|---|---|
| point_in_time_whitelist | spa_core/backtesting/point_in_time_whitelist.py | ✅ Created | Prevents look-ahead bias |
| gate | spa_core/backtesting/gate.py | ✅ Created | 4-state gate (BACKTEST/PRE_PAPER/PAPER/LIVE) |
| gate_api | spa_core/backtesting/gate_api.py | ✅ Created | HTTP API endpoint for gate status |
| s20_anticrisis_research | spa_core/backtesting/… (strategy S20) | ✅ Created | RS-001, RESEARCH_ONLY, 18.2% target |
| s21_cashflow_research | spa_core/backtesting/… (strategy S21) | ✅ Created | RS-002, RESEARCH_ONLY, 29.24% gross |
| source_pipeline | spa_core/backtesting/source_pipeline.py | ✅ Created | strict/research/pending classification |
| owner_acceptance | spa_core/backtesting/owner_acceptance.py | ✅ Created | Owner sign-off workflow |
| source_promotion_engine | spa_core/backtesting/source_promotion_engine.py | ✅ Created | Promotes sources strict→research |
| research_scenario_matrix | spa_core/backtesting/research_scenario_matrix.py | ✅ Created | Scenario matrix for research strats |
| gmx_research | spa_core/adapters/gmx_research.py | ✅ Created | GMX GLP/GM fee yield (RESEARCH_ONLY) |
| conc_lp_il_model | spa_core/analytics/conc_lp_il_model.py | ✅ Created | Concentrated LP IL modelling |
| gold_proxy_research | spa_core/adapters/gold_proxy_research.py | ✅ Created | Gold proxy yield (RESEARCH_ONLY) |
| rs001_live_apy_engine | spa_core/analytics/rs001_live_apy_engine.py | ✅ Created | RS-001 live APY estimation |
| rs002_live_apy_engine | spa_core/analytics/rs002_live_apy_engine.py | ✅ Created | RS-002 live APY estimation |
| strategy_rs001_tracker | spa_core/analytics/strategy_rs001_tracker.py | ✅ Created | RS-001 performance tracker |
| strategy_rs002_tracker | spa_core/analytics/strategy_rs002_tracker.py | ✅ Created | RS-002 performance tracker |
| pre_paper_checklist | spa_core/backtesting/pre_paper_checklist.py | ✅ Created | 5-category launch checklist |

## Research Strategy Status

| ID | Name | Mode | APY Target | Notes |
|---|---|---|---|---|
| RS-001 (S20) | Anti-Crisis Research | RESEARCH_ONLY | 18.2% | Excluded from strict backtest — proxy data only |
| RS-002 (S21) | Cashflow Research | RESEARCH_ONLY | 29.24% gross | Excluded from strict backtest — model only |

## Paper Trading Gate Status

| Gate | Status | Notes |
|---|---|---|
| Pre-paper backtest | ✅ PASS | All P0/P1A/P2 closures complete |
| Hardening audit | ❌ NOT_PASS | See paper_ready_gate.json blockers |
| Expanded universe | ❌ STRICT_BLOCKED | P1B sources excluded until evidence accepted |
| Owner acceptance | ❌ NOT_SIGNED | Pending — run `owner_acceptance --generate-draft` |
| **Paper trading allowed** | **❌ NOT_READY** | 3 blockers above must clear |

## Key Figures

- Cash drag (structural): **86.97%** (single dominant T1 — policy norm)
- Tests (RS-001 + RS-002): **128** (76 + 52)
- Tests (total CPA suite): **500+**
- Paper period target: **90 days minimum**
- Go-live target: **2026-08-01**

## Push Scripts

| Script | Sprint | Status |
|---|---|---|
| scripts/push_v916.sh | v9.16 | Pending USER ACTION |
| scripts/push_v917.sh | v9.17 | Pending USER ACTION |
| scripts/push_v918.sh | v9.18 | Pending USER ACTION |
| scripts/push_v919.sh | v9.19 | Pending USER ACTION |
| scripts/push_v920.sh | v9.20 | Pending USER ACTION |
| scripts/push_v921.sh | v9.21 | Pending USER ACTION |
| scripts/push_v922.sh | v9.22 | Pending USER ACTION |
| scripts/push_v929.sh | v9.29 | Pending USER ACTION |
| scripts/push_v937.sh | v9.37 | Pending USER ACTION |
| scripts/push_v938.sh | v9.38 | Pending USER ACTION |
