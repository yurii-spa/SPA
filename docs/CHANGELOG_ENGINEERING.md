# SPA Engineering Changelog

> Auto-generated entries from git log; curated entries annotated manually.
> Format: [vX.Y] — YYYY-MM-DD · MP-NNN · description

---

## [v11.34] — 2026-06-20

### Added
- `docs/CHANGELOG_ENGINEERING.md` — this file (engineering changelog + full version history)
- `scripts/generate_changelog.py` — auto-generates changelog from `git log --oneline`
- `tests/test_changelog_generator.py` — 15 tests for changelog generator

---

## [v11.33] — 2026-06-20

### Added
- `docs/COMPLIANCE_POLICY.md` — AML/KYC policy for Family Fund investors
- `docs/RISK_DISCLOSURE.md` — risk warning document for investors
- `tests/test_compliance_docs.py` — 16 tests for compliance docs

---

## [v11.32] — 2026-06-20

### Added
- `docs/RUNBOOK.md` — operations manual (1,200+ words): daily ops, weekly review,
  emergency procedures (circuit breaker, data outage, gap monitor, daemon restart,
  live trading gate), monitoring reference, push-to-GitHub guide

---

## [v11.31] — 2026-06-20

### Added
- `docs/adr/ADR-037-walk-forward-validation.md` — WFV as mandatory pre-paper gate
  (train ≥ 6 months, test ≥ 1 month, ≥ 3 folds, OOS Sharpe ≥ 0.8, degradation ≥ 0.7)
- `docs/adr/ADR-038-monte-carlo-robustness.md` — MC robustness testing (1,000 sims,
  block bootstrap, P(Sharpe≥0.5)≥60%, 5th-pct Sharpe≥0.0, p95 drawdown≤15%)
- `docs/adr/ADR-039-drawdown-circuit-breaker.md` — graduated circuit breaker
  (YELLOW 2% / ORANGE 3% / RED 4% / BLACK 5%), cooldown/reset logic
- `docs/adr/ADR-040-strategy-demotion-policy.md` — extends ADR-023: PROBATION →
  DEMOTED → ARCHIVED lifecycle, quarterly WFV re-evaluation, recovery conditions
- `tests/test_adr_documents.py` — 32 tests for ADR-037/038/039/040

---

## [v11.30] — 2026-06-20

### Added
- Strategy S20 Curve/Convex optimizer
- Strategy S21 Aave V3 Loop
- Tournament runner v2 with Sharpe ranking
- Strategy demotion engine (initial scaffolding)
- ADR-036 BaseAnalytics migration policy

---

## [v10.86] — 2026-06-20

### Sprint baseline before v11.x series
- `done_count`: 1185

---

## [v10.74] — 2026-06-20

### Added
- ADR-032 Live Trading Gate
- ADR-033 Strategy Loop Activation
- ADR-034 Atomic Write Centralization
- ADR-035 SPAError Hierarchy
- Security audit report (0 CRITICAL findings)
- GoLive score: 82/100

---

## [v10.42] — 2026-06-20

### Added (MP-1425 + MP-1426)
- `capital_config.json` — capital configuration file
- `spa_core/golive/fee_structure.py` — fee structure module
- GoLive scorer: new 6-category system (`assess_financial`, `assess_gates`,
  `assess_infrastructure_v2`, `assess_data_sources`, `assess_evidence`,
  `assess_documentation_v2`), max score = 100
- `data/paper_evidence_history.json` initialized
- GoLive score jump: 50.5 → 69.0 (+18.5 pts)
- 25 tests GREEN

---

## [v10.33] — 2026-06-20

### Added (MP-1417 + MP-1418)
- `docs/RISK_MANAGEMENT_POLICY.md` — risk management policy
- `docs/DEPLOYMENT_RUNBOOK.md` — deployment runbook
- `docs/DATA_SOURCES_REGISTRY.md` — data sources registry
- `docs/FAMILY_FUND_ONBOARDING.md` — family fund onboarding guide
- `docs/INFRASTRUCTURE_CHECKLIST.md` — infrastructure checklist
- `scripts/verify_infrastructure.py` — 8-check infrastructure verifier
  (`check_git_hooks`, `check_launchd_plist`, `check_kill_switch`, `check_data_backups`,
  `check_monitoring`, `check_verify_script`, `check_infrastructure_doc`,
  `check_install_hooks_script`)
- GoLive score: 29.7 → 50.5

---

## [v10.20] — 2026-06-20

### Added (MP-1403 + MP-1404)
- `scripts/analytics_conformance.py` — AnalyticsConformanceChecker (scans 727 analytics
  files, reports BaseAnalytics conformance)
- `scripts/dead_code_scanner.py` — DeadCodeScanner v2 (5 categories: unused_import,
  no_tests, todo_stale, stub_module, orphan_module), output `data/dead_code_report.json`

---

## [v10.0] — 2026-06-19

### Milestone: First Stable Pre-Paper-Trading Release
- Full paper trading infrastructure operational
- GoLive score > 50/100 for first time
- All core adapters (Aave V3, Compound V3, Morpho Steakhouse) returning live APY
- Risk policy v1.0 enforced in daily cycle
- `launchd com.spa.daily_cycle` running without manual intervention

---

## [v9.94] — 2026-06-18

### Added (MP-1377 + MP-1378)
- `scripts/push_registry.py` — PushRegistry (scan/load/save/mark_done/sync_scan/summary),
  `scripts/push_registry.json` (71 entries DONE/PENDING)
- `scripts/scan_dead_code.py` — DeadCodeScanner (find_modules/find_tests/
  modules_without_tests/find_all_imports/orphan_modules/stub_modules/report/save)

---

## [v9.82] — 2026-06-17

### Added
- GoLiveChecker expanded to 26 criteria (from 6 baseline)
- ADR-029 Research Strategies Framework
- ADR-030 Emergency Circuit Breakers (high-level)

---

## [v9.48] — 2026-06-16

### Added (MP-1331 + MP-1332)
- `spa_core/analytics/protocol_data_audit.py` — ProtocolDataAudit (40 protocols,
  priority formula base×boost+penalty, acquisition_roadmap)
- `docs/decisions/ADR-029-research-strategies-framework.md`
- `docs/decisions/ADR-030-pit-backtest-standard.md`

---

## [v9.24] — 2026-06-15

### Added (MP-1307 + MP-1308)
- `spa_core/adapters/gmx_research.py` — GMXResearchAdapter (DeFiLlama APY feed,
  RESEARCH_ONLY=True, fallback=15.0%)
- `spa_core/analytics/conc_lp_il_model.py` — Concentrated LP Impermanent Loss model
  (Uniswap V3 math, il_pct/net_apy/scenario_analysis/rs002_net_apy)

---

## [v9.0] — 2026-06-14

### Milestone: Multi-Chain Expansion
- ADR-025 Base Chain Expansion
- ADR-026 Base Chain Protocols v2
- ADR-027 S13 Multi-Chain Yield Arbitrage
- ADR-028 Oracle Price Diversification
- Aave V3 Arbitrum adapter (T1, in development)

---

## [v8.05] — 2026-06-12

### Added (MP-1134 + MP-1135)
- `spa_core/analytics/yield_compounding_optimizer.py` — DeFiProtocolYieldCompoundingOptimizer
  (effective_apy formula, optimal frequency DAILY/WEEKLY/etc., gas_drag_at_optimal_pct,
  net_annual_yield_usd, ring-buffer log cap 100, atomic write, 129 tests)
- `spa_core/analytics/tvl_momentum_analyzer.py` — ProtocolDeFiTvlMomentumAnalyzer
  (momentum_score 0-100, yield_dilution_risk, tvl_label, 124 tests)

---

## [v7.51] — 2026-06-11

### Added (MP-1026 + MP-1027)
- DeFiProtocolGovernanceProposalImpactScorer (107 tests)
- ProtocolDeFiProtocolRevenueSustainabilityAnalyzer (109 tests)

---

## [v7.38] — 2026-06-10

### Added (MP-1000 + MP-1001)
- DeFiProtocolFeeTierOptimizer (124 tests, fee tiers 5/30/100/500 bps)
- ProtocolDeFiTokenBuybackImpactAnalyzer (120 tests)

---

## [v4.46] — 2026-06-10 *(real track start)*

### Milestone: Real Track Start (2026-06-10)
- All data before this date classified as demo/simulation
- `is_demo: false` set in paper_trading_status.json
- GoLive 30-day continuity counter started

---

## [v1.0] — 2026-06-01 *(initial architecture)*

### Foundation
- SPA concept: autonomous DeFi yield optimizer, paper trading $100,000 USDC
- Initial adapter set: Aave V3, Compound V3
- RiskPolicy v1.0 (ADR-001): TVL floor $5M, per-protocol cap 40% T1 / 20% T2
- Paper trading engine (`spa_core/paper_trading/engine.py`)
- Basic dashboard (`index.html`)
- launchd `com.spa.daily_cycle` scaffold

---

*Generated by: `scripts/generate_changelog.py`*  
*For strategic roadmap see: MASTER_PLAN_v1.md, GRAND_VISION_v1.md*  
*For infrastructure state see: CURRENT_STATE.md, SYSTEM_HEALTH.md*
