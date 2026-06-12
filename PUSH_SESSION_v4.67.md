# SPA Push Session v4.67 — 2026-06-12

**Дата:** 2026-06-12  
**Всего файлов:** 229 (227 изменённых + 2 новых: этот файл + push_all_session.sh)  
**Sprint:** v4.67  

---

## Новые и изменённые файлы (сгруппированные)

### Python modules — spa_core/ (66 файлов)

```
spa_core/adapters/__init__.py
spa_core/adapters/pendle_adapter.py
spa_core/agents/reporting_agent.py
spa_core/alerts/alert_manager.py
spa_core/alerts/bot_commands.py
spa_core/alerts/daily_report.py
spa_core/alerts/milestone_alert.py
spa_core/alerts/telegram_format_ru.py
spa_core/audit/data_integrity.py
spa_core/audit/decision_audit.py
spa_core/execution/__init__.py
spa_core/execution/rate_limiter.py
spa_core/family_fund/__init__.py
spa_core/family_fund/models.py
spa_core/family_fund/pnl_attribution.py
spa_core/family_fund/registry.py
spa_core/family_fund/telegram_blast.py
spa_core/orchestrator/adapter_orchestrator.py
spa_core/paper_trading/alpha_decay.py
spa_core/paper_trading/analytics_scorecard.py
spa_core/paper_trading/apy_dispersion_analytics.py
spa_core/paper_trading/backtest_vs_paper.py
spa_core/paper_trading/bias_ratio.py
spa_core/paper_trading/capm_decomposition.py
spa_core/paper_trading/concentration_analytics.py
spa_core/paper_trading/correlation_analyzer.py
spa_core/paper_trading/cost_drag_analytics.py
spa_core/paper_trading/cycle_gap_monitor.py
spa_core/paper_trading/cycle_runner.py
spa_core/paper_trading/daily_report.py
spa_core/paper_trading/deflated_sharpe.py
spa_core/paper_trading/drawdown_analytics.py
spa_core/paper_trading/drawdown_attribution.py
spa_core/paper_trading/exit_liquidity.py
spa_core/paper_trading/honest_metrics.py
spa_core/paper_trading/liquidity_depth_analyzer.py
spa_core/paper_trading/monthly_report.py
spa_core/paper_trading/performance_report.py
spa_core/paper_trading/position_sizing_v2.py
spa_core/paper_trading/progress_tracker.py
spa_core/paper_trading/protocol_scorecard.py
spa_core/paper_trading/rachev_ratio.py
spa_core/paper_trading/regime_conditional_performance.py
spa_core/paper_trading/regime_detector.py
spa_core/paper_trading/risk_contribution.py
spa_core/paper_trading/strategy_consolidator.py
spa_core/paper_trading/strategy_registry.py
spa_core/paper_trading/structural_break.py
spa_core/paper_trading/tail_risk.py
spa_core/paper_trading/tournament_evaluator.py
spa_core/paper_trading/turnover_analytics.py
spa_core/paper_trading/ulcer_index.py
spa_core/paper_trading/upside_potential_ratio.py
spa_core/paper_trading/vportfolio.py
spa_core/paper_trading/walk_forward_validator.py
spa_core/paper_trading/yield_attribution.py
spa_core/paper_trading/yield_decay_analytics.py
spa_core/reporting/portal_data.py
spa_core/risk/chain_limits.py
spa_core/risk/policy.py
spa_core/strategies/emode_looping.py
spa_core/strategies/strategy_registry.py
spa_core/testing/__init__.py
spa_core/testing/fork_harness.py
spa_core/utils/__init__.py
spa_core/utils/refresh_agent_summaries.py
```

### Tests — spa_core/tests/ (49 файлов)

```
spa_core/tests/test_alpha_decay.py
spa_core/tests/test_analytics_scorecard.py
spa_core/tests/test_apy_dispersion_analytics.py
spa_core/tests/test_backtest_vs_paper.py
spa_core/tests/test_bias_ratio.py
spa_core/tests/test_capm_decomposition.py
spa_core/tests/test_concentration_analytics.py
spa_core/tests/test_correlation_analyzer.py
spa_core/tests/test_cost_drag_analytics.py
spa_core/tests/test_cycle_gap_monitor.py
spa_core/tests/test_dashboard_snapshot.py
spa_core/tests/test_data_integrity.py
spa_core/tests/test_decision_audit.py
spa_core/tests/test_deflated_sharpe.py
spa_core/tests/test_drawdown_analytics.py
spa_core/tests/test_drawdown_attribution.py
spa_core/tests/test_exit_liquidity.py
spa_core/tests/test_family_fund.py
spa_core/tests/test_fork_harness.py
spa_core/tests/test_honest_metrics.py
spa_core/tests/test_l2_adapters.py
spa_core/tests/test_milestone_alert.py
spa_core/tests/test_monthly_report.py
spa_core/tests/test_paper_trading_daily_report.py
spa_core/tests/test_pat_rotation.py
spa_core/tests/test_pendle_adapter.py
spa_core/tests/test_performance_report.py
spa_core/tests/test_portal_data.py
spa_core/tests/test_position_sizing_v2.py
spa_core/tests/test_progress_tracker.py
spa_core/tests/test_protocol_scorecard.py
spa_core/tests/test_rachev_ratio.py
spa_core/tests/test_rate_limiter.py
spa_core/tests/test_regime_conditional_performance.py
spa_core/tests/test_regime_detector.py
spa_core/tests/test_risk_contribution.py
spa_core/tests/test_risk_policy.py
spa_core/tests/test_strategy_consolidator.py
spa_core/tests/test_structural_break.py
spa_core/tests/test_tail_risk.py
spa_core/tests/test_telegram_alerts.py
spa_core/tests/test_tournament_evaluator.py
spa_core/tests/test_turnover_analytics.py
spa_core/tests/test_ulcer_index.py
spa_core/tests/test_upside_potential_ratio.py
spa_core/tests/test_vportfolio.py
spa_core/tests/test_walk_forward_validator.py
spa_core/tests/test_yield_attribution.py
spa_core/tests/test_yield_decay_analytics.py
```

### Tests — tests/ integration (2 файла)

```
tests/test_liquidity_depth_analyzer.py
tests/test_telegram_formatting.py
```

### Scripts (7 файлов)

```
scripts/golive_preflight.py
scripts/kill_switch_drill.py
scripts/lint_llm_forbidden.py
scripts/pat_rotation_helper.py
scripts/tests/test_golive_preflight.py
scripts/tests/test_kill_switch_drill.py
scripts/tests/test_lint_llm_forbidden.py
```

### Frontend / HTML (2 файла)

```
index.html
investor_portal.html
```

### Data — data/*.json (65 файлов)

```
data/adapter_orchestrator_status.json
data/adapter_status.json
data/agent_summaries.json
data/analytics_scorecard.json
data/analytics_summary.json
data/apy_dispersion_analytics.json
data/audit_trail.jsonl
data/backtest_vs_paper.json
data/bias_ratio.json
data/concentration_analytics.json
data/correlation_analytics.json
data/cost_drag_analytics.json
data/current_positions.json
data/daily_report_2026-06-12.json
data/dashboard_metrics_history.json
data/data_integrity_status.json
data/decisions.json
data/deflated_sharpe.json
data/drawdown_analytics.json
data/drawdown_attribution.json
data/equity_curve_daily.json
data/exit_liquidity_status.json
data/fast_loop_status.json
data/gap_monitor.json
data/golive_status.json
data/governance_proposals.json
data/honest_metrics.json
data/incidents.json
data/investor_portal_data.json
data/investors.json
data/kill_switch_status.json
data/last_approved_allocation.json
data/legal_status.json
data/llm_forbidden_lint.json
data/orchestrator_runs.json
data/orchestrator_trigger.json
data/paper_trading_status.json
data/pat_rotation_state.json
data/pnl_history.json
data/progress_tracker.json
data/rachev_ratio.json
data/rate_limiter_state.json
data/red_flags.json
data/regime_conditional_performance.json
data/reporting_status.json
data/risk_contribution.json
data/risk_scores.json
data/shadow_portfolio.json
data/slow_loop_insights.json
data/statements/2026-06_i1.json
data/statements/2026-06_i2.json
data/strategy_shadow_comparison.json
data/structural_break.json
data/tail_risk.json
data/tear_sheet.json
data/tg_update_offset.json
data/trades.json
data/turnover_analytics.json
data/ulcer_index.json
data/upside_potential_ratio.json
data/watchdog_cycle_result.json
data/watchdog_log.json
data/watchdog_state.json
data/yield_attribution.json
data/yield_decay_analytics.json
```

### Docs (20 файлов)

```
docs/ADR_E2E_FORK_HARNESS.md
docs/ADR_TOKEN_VS_EQUITY.md
docs/AUDIT_online_v2.md
docs/AUDIT_status_backlog_v2.md
docs/AUDIT_team_papertest_v2.md
docs/AUDIT_v2_dashboard.md
docs/CHECKPOINT_v2.md
docs/DECISIONS.md
docs/FAMILY_FUND_ROADMAP.md
docs/LEGAL_STRUCTURE_v1.md
docs/LEVERAGE_STRATEGIES.md
docs/OUTREACH_STRATEGY_v1.md
docs/PHASE2_ROADMAP.md
docs/REPORT_v2_dashboard.md
docs/YIELD_STRATEGY_ROADMAP.md
docs/adr/ADR-010-gnosis-safe-key-management.md
docs/adr/ADR-011-go-live-security-checklist.md
docs/adr/ADR-019-t2-cap-increase.md
docs/adr/ADR-020-t3-private-credit.md
docs/kill_switch_drill.md
```

### Root config / misc (16 файлов)

```
.github/workflows/spa-lint.yml
CLAUDE.md
CURRENT_STATE.md
KANBAN.json
RULES.md
SPA_audit_report.md
SPA_sprint_log.md
SYSTEM_HEALTH.md
_run_spa_v434.sh
_run_tests_mp071.command
auto_push.py
com.spa.autopush.plist
com.spa.httpserver.plist
push_mp129.command
push_mp130.command
push_mp135.command
```

### Session artifacts (2 новых файла)

```
PUSH_SESSION_v4.67.md
scripts/push_all_session.sh
```

---

## Push команда

```bash
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files \
  /Users/yuriikulieshov/Documents/SPA_Claude/.github/workflows/spa-lint.yml \
  /Users/yuriikulieshov/Documents/SPA_Claude/CLAUDE.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/CURRENT_STATE.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/PUSH_SESSION_v4.67.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/RULES.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/SPA_audit_report.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/SPA_sprint_log.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/SYSTEM_HEALTH.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/_run_spa_v434.sh \
  /Users/yuriikulieshov/Documents/SPA_Claude/_run_tests_mp071.command \
  /Users/yuriikulieshov/Documents/SPA_Claude/auto_push.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/com.spa.autopush.plist \
  /Users/yuriikulieshov/Documents/SPA_Claude/com.spa.httpserver.plist \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_orchestrator_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/agent_summaries.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/analytics_scorecard.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/analytics_summary.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/apy_dispersion_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/audit_trail.jsonl \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/backtest_vs_paper.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/bias_ratio.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/concentration_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/correlation_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/cost_drag_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/current_positions.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/daily_report_2026-06-12.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/dashboard_metrics_history.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/data_integrity_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/decisions.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/deflated_sharpe.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/drawdown_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/drawdown_attribution.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/equity_curve_daily.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/exit_liquidity_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/fast_loop_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/gap_monitor.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/golive_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/governance_proposals.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/honest_metrics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/incidents.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/investor_portal_data.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/investors.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/kill_switch_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/last_approved_allocation.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/legal_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/llm_forbidden_lint.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/orchestrator_runs.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/orchestrator_trigger.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/paper_trading_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/pat_rotation_state.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/pnl_history.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/progress_tracker.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/rachev_ratio.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/rate_limiter_state.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/red_flags.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/regime_conditional_performance.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/reporting_status.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/risk_contribution.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/risk_scores.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/shadow_portfolio.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/slow_loop_insights.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/statements/2026-06_i1.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/statements/2026-06_i2.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/strategy_shadow_comparison.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/structural_break.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/tail_risk.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/tear_sheet.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/tg_update_offset.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/trades.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/turnover_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/ulcer_index.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/upside_potential_ratio.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/watchdog_cycle_result.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/watchdog_log.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/watchdog_state.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/yield_attribution.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/yield_decay_analytics.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/ADR_E2E_FORK_HARNESS.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/ADR_TOKEN_VS_EQUITY.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/AUDIT_online_v2.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/AUDIT_status_backlog_v2.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/AUDIT_team_papertest_v2.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/AUDIT_v2_dashboard.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/CHECKPOINT_v2.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/DECISIONS.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/FAMILY_FUND_ROADMAP.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/LEGAL_STRUCTURE_v1.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/LEVERAGE_STRATEGIES.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/OUTREACH_STRATEGY_v1.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/PHASE2_ROADMAP.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/REPORT_v2_dashboard.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/YIELD_STRATEGY_ROADMAP.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/adr/ADR-010-gnosis-safe-key-management.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/adr/ADR-011-go-live-security-checklist.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/adr/ADR-019-t2-cap-increase.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/adr/ADR-020-t3-private-credit.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/docs/kill_switch_drill.md \
  /Users/yuriikulieshov/Documents/SPA_Claude/index.html \
  /Users/yuriikulieshov/Documents/SPA_Claude/investor_portal.html \
  /Users/yuriikulieshov/Documents/SPA_Claude/push_mp129.command \
  /Users/yuriikulieshov/Documents/SPA_Claude/push_mp130.command \
  /Users/yuriikulieshov/Documents/SPA_Claude/push_mp135.command \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/golive_preflight.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/kill_switch_drill.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/lint_llm_forbidden.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/pat_rotation_helper.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_all_session.sh \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/tests/test_golive_preflight.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/tests/test_kill_switch_drill.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/tests/test_lint_llm_forbidden.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/__init__.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/pendle_adapter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/agents/reporting_agent.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/alert_manager.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/bot_commands.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/daily_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/milestone_alert.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/telegram_format_ru.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/audit/data_integrity.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/audit/decision_audit.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/execution/__init__.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/execution/rate_limiter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/__init__.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/models.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/pnl_attribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/registry.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/telegram_blast.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/orchestrator/adapter_orchestrator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/alpha_decay.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/analytics_scorecard.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/apy_dispersion_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/backtest_vs_paper.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/bias_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/capm_decomposition.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/concentration_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/correlation_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cost_drag_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_gap_monitor.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/daily_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/deflated_sharpe.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/drawdown_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/drawdown_attribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/exit_liquidity.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/honest_metrics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/liquidity_depth_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/monthly_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/performance_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/position_sizing_v2.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/progress_tracker.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/protocol_scorecard.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/rachev_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/regime_conditional_performance.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/regime_detector.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/risk_contribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/strategy_consolidator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/strategy_registry.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/structural_break.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/tail_risk.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/tournament_evaluator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/turnover_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/ulcer_index.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/upside_potential_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/vportfolio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/walk_forward_validator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/yield_attribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/yield_decay_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/reporting/portal_data.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/risk/chain_limits.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/risk/policy.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/emode_looping.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/strategy_registry.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/testing/__init__.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/testing/fork_harness.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_alpha_decay.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_analytics_scorecard.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_apy_dispersion_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_backtest_vs_paper.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_bias_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_capm_decomposition.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_concentration_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_correlation_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_cost_drag_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_cycle_gap_monitor.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_dashboard_snapshot.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_data_integrity.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_decision_audit.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_deflated_sharpe.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_drawdown_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_drawdown_attribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_exit_liquidity.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_family_fund.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_fork_harness.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_honest_metrics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_l2_adapters.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_milestone_alert.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_monthly_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_paper_trading_daily_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_pat_rotation.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_pendle_adapter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_performance_report.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_portal_data.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_position_sizing_v2.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_progress_tracker.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_protocol_scorecard.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_rachev_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_rate_limiter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_regime_conditional_performance.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_regime_detector.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_risk_contribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_risk_policy.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_strategy_consolidator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_structural_break.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_tail_risk.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_telegram_alerts.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_tournament_evaluator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_turnover_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_ulcer_index.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_upside_potential_ratio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_vportfolio.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_walk_forward_validator.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_yield_attribution.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_yield_decay_analytics.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/utils/__init__.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/utils/refresh_agent_summaries.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_liquidity_depth_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_telegram_formatting.py \
  --message "feat(v4.67): Batch push session — tournament, leverage, family fund, preflight, analytics [229 files]"
```

---

## Альтернатива: через скрипт

```bash
bash ~/Documents/SPA_Claude/scripts/push_all_session.sh
```

---

*Сгенерировано автономно: claude (SPA-MP159), 2026-06-12*
