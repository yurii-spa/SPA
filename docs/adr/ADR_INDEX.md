# ADR Index

Generated: 2026-06-20

ADR-файлы хранятся в двух местах: `docs/adr/` (основные) и `docs/` (legacy/дополнительные).

## docs/adr/

| Файл | Заголовок |
|---|---|
| [ADR-002-golive-transfer-rule.md](ADR-002-golive-transfer-rule.md) | ADR-002: Правило переноса go-live решения |
| [ADR-010-gnosis-safe-key-management.md](ADR-010-gnosis-safe-key-management.md) | ADR-010: Gnosis Safe Key Management Architecture |
| [ADR-011-go-live-security-checklist.md](ADR-011-go-live-security-checklist.md) | ADR-011: Go-Live Security Checklist |
| [ADR-019-t2-cap-increase.md](ADR-019-t2-cap-increase.md) | ADR-019: T2 Allocation Cap Increase 35% → 50% |
| [ADR-020-t3-private-credit.md](ADR-020-t3-private-credit.md) | ADR-020: T3 Private Credit / RWA Category — 15% AUM Cap |
| [ADR-021-pendle-legacy-position.md](ADR-021-pendle-legacy-position.md) | ADR-021 Legacy Exception: Pendle Position |
| [ADR-021-pendle-yt-t3-classification.md](ADR-021-pendle-yt-t3-classification.md) | ADR-021: Pendle YT Tokens — T3 Speculative Asset Classification |
| [ADR-022-gnosis-safe-multisig.md](ADR-022-gnosis-safe-multisig.md) | ADR-022: Gnosis Safe 2-of-3 Multisig для Family Fund |
| [ADR-024-gnosis-safe-multisig.md](ADR-024-gnosis-safe-multisig.md) | ADR-024: Gnosis Safe Multisig для go-live |
| [ADR-025-base-chain-expansion.md](ADR-025-base-chain-expansion.md) | ADR-025: Base Chain Expansion |
| [ADR-026-base-chain-protocols-v2.md](ADR-026-base-chain-protocols-v2.md) | ADR-026 — Base Chain Protocols v2: Moonwell Finance Suspension |
| [ADR-027-s13-multi-chain-yield-arbitrage.md](ADR-027-s13-multi-chain-yield-arbitrage.md) | ADR-027 — S13 Multi-Chain Yield Arbitrage Strategy |
| [ADR-028-oracle-price-diversification.md](ADR-028-oracle-price-diversification.md) | ADR-028: Oracle Price Diversification |
| [ADR-029-promotion-automation-policy.md](ADR-029-promotion-automation-policy.md) | ADR-029: Strategy Promotion Automation Policy |
| [ADR-030-emergency-circuit-breakers.md](ADR-030-emergency-circuit-breakers.md) | ADR-030: Emergency Circuit Breakers |
| [ADR-031-rebalancing-policy.md](ADR-031-rebalancing-policy.md) | ADR-031: Portfolio Rebalancing Policy |
| [ADR-032-live-trading-gate.md](ADR-032-live-trading-gate.md) | ADR-032: Live Trading Gate — Triple-Lock Activation Protocol |
| [ADR-033-strategy-loop-activation.md](ADR-033-strategy-loop-activation.md) | ADR-033: Strategy Loop Activation Policy |
| [ADR-034-atomic-write-centralization.md](ADR-034-atomic-write-centralization.md) | ADR-034: Centralized Atomic Write via `spa_core/utils/atomic.py` |
| [ADR-035-spaerror-hierarchy.md](ADR-035-spaerror-hierarchy.md) | ADR-035: SPAError Exception Hierarchy |
| [ADR-036-baseanalytics-migration.md](ADR-036-baseanalytics-migration.md) | ADR-036: BaseAnalytics Abstract Base Class — 43-Class Migration |
| [ADR-037-walk-forward-validation.md](ADR-037-walk-forward-validation.md) | ADR-037: Walk-Forward Validation as Mandatory Pre-Paper Gate |
| [ADR-038-monte-carlo-robustness.md](ADR-038-monte-carlo-robustness.md) | ADR-038: Monte Carlo Robustness Testing for Strategy Validation |
| [ADR-039-drawdown-circuit-breaker.md](ADR-039-drawdown-circuit-breaker.md) | ADR-039: Drawdown Circuit Breaker |
| [ADR-040-strategy-demotion-policy.md](ADR-040-strategy-demotion-policy.md) | ADR-040: Strategy Demotion Policy (extends ADR-023) |
| [ADR-041-adapter-tier-promotion.md](ADR-041-adapter-tier-promotion.md) | ADR-041: Adapter Tier Promotion Criteria |
| [ADR-042-backtest-harness-design.md](ADR-042-backtest-harness-design.md) | ADR-042: Backtest Harness Design |
| [ADR-043-new-protocol-adapters-ethena-fluid-usual.md](ADR-043-new-protocol-adapters-ethena-fluid-usual.md) | ADR-043: New Protocol Adapters — Ethena / Fluid / Usual |
| [ADR-044-bear-market-hedge-strategy.md](ADR-044-bear-market-hedge-strategy.md) | ADR-044: Bear-Market Hedge Strategy (S31) + Market-Neutral (S32) — Proposed |
| [ADR-045-kelly-criterion-allocation.md](ADR-045-kelly-criterion-allocation.md) | ADR-045: Kelly Criterion Allocation |
| [ADR-046-multi-chain-expansion-strategy.md](ADR-046-multi-chain-expansion-strategy.md) | ADR-046: Multi-Chain Expansion Strategy |
| [ADR-047-site-privacy-hardening.md](ADR-047-site-privacy-hardening.md) | ADR-047: Site Privacy Hardening (earn-defi.com) |
| [ADR_001_initial_risk_policy.md](ADR_001_initial_risk_policy.md) | ADR-001: Initial Risk Policy v1.0 — Stable Lending Core |
| [ADR_002_pendle_pt_integration.md](ADR_002_pendle_pt_integration.md) | ADR-002: Pendle PT Integration |
| [ADR_009_capacity_limits.md](ADR_009_capacity_limits.md) | ADR-009 — Capacity Limits Enforcement (MP-209) |
| [ADR_TEMPLATE.md](ADR_TEMPLATE.md) | ADR-XXX: [Short Decision Title] |

## docs/ (legacy / дополнительные)

| Файл | Заголовок |
|---|---|
| [ADR-023-strategy-promotion-policy.md](../ADR-023-strategy-promotion-policy.md) | ADR-023: Strategy Promotion Policy — Paper → Live |
| [ADR-031-analytics-integration.md](../ADR-031-analytics-integration.md) | ADR-031: Analytics Integration Architecture |
| [ADR-032-push-strategy.md](../ADR-032-push-strategy.md) | ADR-032: Consolidation of GitHub push mechanisms |
| [ADR-strategy-shadow.md](../ADR-strategy-shadow.md) | ADR — Multi-Strategy Shadow Framework (Sprint A, v3.90) |
| [ADR_003_rate_limiting.md](../ADR_003_rate_limiting.md) | ADR-003: Rate Limiting and Circuit Breaker for External API Calls |
| [ADR_004_two_layer_agents.md](../ADR_004_two_layer_agents.md) | ADR-004: Two-Layer Agent Architecture |
| [ADR_005_postgres_migration_plan.md](../ADR_005_postgres_migration_plan.md) | ADR-005: PostgreSQL Migration Plan (BL-008) |
| [ADR_006_aave_live_sdk.md](../ADR_006_aave_live_sdk.md) | ADR-006: Aave V3 Live SDK Adapter — Migration Plan (FEAT-004) |
| [ADR_007_compound_v3_live_sdk.md](../ADR_007_compound_v3_live_sdk.md) | ADR-007: Compound V3 Live SDK Integration (Phased Rollout) |
| [ADR_008_execution_router.md](../ADR_008_execution_router.md) | ADR-008 — Execution Router (cross-protocol APY arbitration) |
| [ADR_008_risk_axes_v2.md](../ADR_008_risk_axes_v2.md) | ADR-008: Risk Policy v2 — Оси риска (credit / peg / duration / bridge) |
| [ADR_009_aave_v3_live_writes.md](../ADR_009_aave_v3_live_writes.md) | ADR-009 — Aave V3 Live Write Methods (FEAT-004 Phase 3) |
| [ADR_010_compound_v3_live_writes.md](../ADR_010_compound_v3_live_writes.md) | ADR-010 — Compound V3 Live Write Methods (FEAT-005 Phase 3) |
| [ADR_011_engine_live_cutover.md](../ADR_011_engine_live_cutover.md) | ADR-011 — Engine Live-Execution Bridge (FEAT-004/005 Phase 4) |
| [ADR_012_dynamic_kelly_sizing.md](../ADR_012_dynamic_kelly_sizing.md) | ADR-012 — Dynamic Kelly Sizing with Live APY Covariance |
| [ADR_013_incident_history.md](../ADR_013_incident_history.md) | ADR-013 — Incident History Database (FEAT-RISK-002) |
| [ADR_014_risk_scoring_engine.md](../ADR_014_risk_scoring_engine.md) | ADR-014 — Risk Scoring Engine (FEAT-RISK-001) |
| [ADR_015_red_flag_monitor.md](../ADR_015_red_flag_monitor.md) | ADR-015 — Red Flag Monitor Extended (FEAT-MON-001) |
| [ADR_016_adaptive_monitoring.md](../ADR_016_adaptive_monitoring.md) | ADR-016: Adaptive Monitoring Intervals (FEAT-MON-003) |
| [ADR_017_governance_watcher.md](../ADR_017_governance_watcher.md) | ADR-017: Governance Watcher (FEAT-MON-002) |
| [ADR_018_bull_cycle_detector.md](../ADR_018_bull_cycle_detector.md) | ADR-018: Bull Cycle Detector + Dynamic Tier Allocation (FEAT-STRAT-001) |
| [ADR_E2E_FORK_HARNESS.md](../ADR_E2E_FORK_HARNESS.md) | ADR: E2E Fork-Harness (MP-401) |
| [ADR_TOKEN_VS_EQUITY.md](../ADR_TOKEN_VS_EQUITY.md) | ADR: Token vs Equity Round — Модель монетизации SPA |
