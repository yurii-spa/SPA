---
trackerStatus:
  type: inbox
title: Починить писателей живого data/ по карте замера — класс обнесён храповиком, но не закрыт
status: new
source: nimbalyst
created: 2026-08-23
priority: high
domain: tests · data/
---

## Что уже сделано (цикл #352) и что осталось

Класс «прогон тестов переписывает живое git-tracked состояние» ИЗМЕРЕН и обнесён
храповиком, но **поимённая починка писателей не сделана** — она и есть эта задача.

Готово и трогать не надо:

* **инструмент** — прогон с `SPA_DATA_WRITE_AUDIT=1` пишет `{nodeid, paths}` в JSONL
  (`SPA_DATA_WRITE_AUDIT_OUT`, по умолчанию `/tmp/spa_data_write_audit.jsonl`);
* **сторож** — `spa_core/tests/live_data_write_guard.py`: НОВЫЙ путь роняет прогон;
* **храповик** — `live_data_write_baseline.json` может ТОЛЬКО уменьшаться
  (`test_live_data_write_ratchet.py`, потолок числом);
* **один писатель уже починен** — `data/live_execution_log.json` (домен исполнения),
  и в базу разрешений он не внесён.

## Чего делать НЕ надо — два тупика, уже оплаченные прогонами

Пробовать закрыть класс ОДНОЙ autouse-фикстурой, переселяющей константы путей, не нужно:
это измерено дважды на `spa_core/tests/test_d*.py` (контроль — 37 555 passed за 95 с):

1. подмена любой константы, ведущей в наблюдаемый каталог, → **135 failed**. Причина:
   `_DEFAULT_LOG_FILE = "data/x_log.json"` бывает не путём, а ФРАГМЕНТОМ для склейки
   (`base / _DEFAULT_LOG_FILE`); абсолютная подмена съедает `base`;
2. подмена только АБСОЛЮТНЫХ констант → **123 failed**, причём ДРУГИХ:
   `test_build_default_cfg_override` и родня проверяют, что дефолт конфига РАВЕН этой
   константе, и имеют на это право.

Отличить «куда модуль пишет» от «чем он склеивает» и от «значения, про которое есть
утверждение» по виду константы нельзя. Починка — поимённая, по карте ниже.

## ПЕРВЫМ пунктом — `data/golive_status.json`

Он в базе храповика, и попал туда НЕ из `git status`: прогон переписывает его **тем же
содержимым**, поэтому git такую правку не покажет никогда — нашёл сторож по mtime. Это
артефакт гейта go-live: тест довёл прод-код до записи в него, и спасает сегодня только
совпадение содержимого.

Писатель СОСТОЯНИЕ-ЗАВИСИМ: `test_golive_checker.py::test_cycle_runner_writes_golive_status`
в одиночку файл НЕ трогает (проверено), а в полном прогоне — трогает. Тот же класс, что
описан в `spa_core/tests/push_state_guard.py`: срабатывание зависит от состояния, оставленного
соседями, поэтому список писателей из ОДНОГО прогона неполон по построению. Искать надо
атрибуцией на полном прогоне, а не по одному файлу.

## Как чинить один файл (образец)

`spa_core/tests/test_engine_bridge.py::test_paper_insert_when_live_fails` — там же назван
капкан: один и тот же модуль живёт в `sys.modules` ДВАЖДЫ (`execution.engine_bridge` и
`spa_core.execution.engine_bridge`), и подменять надо оба.

## Как понять, что готово

Полный прогон командой CI оставляет `git status --porcelain -- data/` ПУСТЫМ, база
храповика — пустой список, потолок в `test_live_data_write_ratchet.py` снижен до нуля.

## Карта «тест-файл → путь» (замер 23.08, `SPA_DATA_WRITE_AUDIT=1`, 69 % набора, 1236 записей)

Карта НЕПОЛНАЯ по построению: прогон атрибуции остановлен на 69 %, потому что голодал
одновременную приёмку. Полную снимает та же команда за один заход — числа тут не догма,
догма инструмент.

| тест-файл | пути |
|---|---|
| `test_airdrop_farming_value_estimator.py` | `data/airdrop_farming_log.json` |
| `test_alert_recovery_stuck_events.py` | `data/threat_reactor_status.json` |
| `test_alerts.py` | `data/alert_log.json` |
| `test_api.py` | `spa_core/database/spa.db` |
| `test_api_honesty_meta.py` | `spa_core/database/spa.db` |
| `test_api_security_ws2.py` | `spa_core/database/spa.db` |
| `test_borrowing_cost_optimizer.py` | `data/borrowing_cost_log.json` |
| `test_cash_attribution_policy_refusals.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_chaos_resilience.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json`, `data/threat_reactor_status.json` |
| `test_cmo_router_auth.py` | `spa_core/database/spa.db` |
| `test_concurrent_fetch.py` | `data/chains_status.json` |
| `test_cycle_derisk_e2e.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_nav_determinism.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_runner.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_runner_characterization.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_runner_integration.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_runner_policy_gate.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_cycle_write_interlock.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_daily_limits_error_halts.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_daily_report.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_defenses_exercised_rtmr.py` | `data/defenses_exercised_rtmr.json` |
| `test_defi_borrow_cost_optimizer.py` | `data/borrow_cost_log.json` |
| `test_defi_fixed_rate_duration_analyzer.py` | `data/fixed_rate_duration_log.json` |
| `test_defi_funding_rate_arbitrage_detector.py` | `data/funding_rate_arb_log.json` |
| `test_defi_impermanent_loss_hedging_analyzer.py` | `data/il_hedging_log.json` |
| `test_defi_insurance_coverage_analyzer.py` | `data/insurance_coverage_log.json` |
| `test_defi_lending_rate_spread_analyzer.py` | `data/lending_rate_spread_log.json` |
| `test_defi_leverage_looping_optimizer.py` | `data/leverage_looping_log.json` |
| `test_defi_liquid_staking_rate_comparator.py` | `data/liquid_staking_comparison_log.json` |
| `test_defi_liquidation_cascade_risk_analyzer.py` | `data/liquidation_cascade_log.json` |
| `test_defi_perpetual_funding_rate_analyzer.py` | `data/perp_funding_rate_log.json` |
| `test_defi_points_to_token_conversion_analyzer.py` | `data/points_conversion_log.json` |
| `test_defi_protocol_admin_key_control_risk_analyzer.py` | `data/admin_key_control_risk_log.json` |
| `test_defi_protocol_borrow_rate_volatility_forecaster.py` | `data/borrow_rate_volatility_log.json` |
| `test_defi_protocol_borrowing_power_utilization_analyzer.py` | `data/borrowing_power_utilization_log.json` |
| `test_defi_protocol_cross_asset_correlation_risk_analyzer.py` | `data/cross_asset_correlation_log.json` |
| `test_defi_protocol_fixed_vs_floating_yield_decision_analyzer.py` | `data/fixed_vs_floating_yield_decision_log.json` |
| `test_defi_protocol_gas_cost_breakeven_analyzer.py` | `data/gas_cost_breakeven_log.json` |
| `test_defi_protocol_gauge_emission_decay_forecaster.py` | `data/gauge_emission_decay_log.json` |
| `test_defi_protocol_lending_rate_spread_analyzer.py` | `data/lending_rate_spread_log.json` |
| `test_defi_protocol_leverage_loop_risk_analyzer.py` | `data/leverage_loop_risk_log.json` |
| `test_defi_protocol_net_interest_margin_analyzer.py` | `data/net_interest_margin_log.json` |
| `test_defi_protocol_points_to_token_conversion_risk_analyzer.py` | `data/points_token_conversion_risk_log.json` |
| `test_defi_protocol_rebase_token_yield_normalizer.py` | `data/rebase_token_yield_normalizer_log.json` |
| `test_defi_protocol_rehypothecation_risk_analyzer.py` | `data/rehypothecation_risk_log.json` |
| `test_defi_protocol_reserve_factor_economics_analyzer.py` | `data/reserve_factor_economics_log.json` |
| `test_defi_protocol_reward_claim_timing_optimizer.py` | `data/reward_claim_timing_log.json` |
| `test_defi_protocol_reward_dilution_velocity_tracker.py` | `data/reward_dilution_velocity_log.json` |
| `test_defi_protocol_risk_adjusted_yield_hurdle_analyzer.py` | `data/risk_adjusted_yield_hurdle_log.json` |
| `test_defi_protocol_stablecoin_basket_composition_risk_analyzer.py` | `data/stablecoin_basket_composition_log.json` |
| `test_defi_protocol_stablecoin_peg_arbitrage_analyzer.py` | `data/stablecoin_peg_arbitrage_log.json` |
| `test_defi_protocol_stablecoin_yield_basis_spread_analyzer.py` | `data/stablecoin_yield_basis_spread_log.json` |
| `test_defi_protocol_treasury_diversification_analyzer.py` | `data/treasury_diversification_log.json` |
| `test_defi_protocol_tvl_yield_elasticity_analyzer.py` | `data/tvl_yield_elasticity_log.json` |
| `test_defi_protocol_yield_after_tax_drag_analyzer.py` | `data/yield_after_tax_drag_log.json` |
| `test_defi_protocol_yield_term_structure_analyzer.py` | `data/yield_term_structure_log.json` |
| `test_defi_volatility_surface_analyzer.py` | `data/vol_surface_log.json` |
| `test_deploy_site_snapshot.py` | `data/consumption_receipts.jsonl` |
| `test_dl_unmeasurable_halts.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_engine_bridge.py` | `data/live_execution_log.json` |
| `test_golive_checker.py` | `data/adapter_status.json`, `data/apy_milestone_log.json`, `data/gap_monitor.json`, `data/risk_alerts.json` |
| `test_integration_e2e.py` | `spa_core/database/spa.db` |
| `test_kill_switch.py` | `data/kill_switch_drill_status.json` |
| `test_protocol_airdrop_eligibility_optimizer.py` | `data/airdrop_eligibility_log.json` |
| `test_protocol_community_sentiment_scorer.py` | `data/community_sentiment_log.json` |
| `test_protocol_cross_chain_yield_arbitrage_detector.py` | `data/cross_chain_arbitrage_log.json` |
| `test_protocol_defi_collateral_health_factor_simulator.py` | `data/collateral_health_factor_log.json` |
| `test_protocol_defi_interest_rate_kink_proximity_analyzer.py` | `data/interest_rate_kink_proximity_log.json` |
| `test_protocol_defi_liquidity_mining_dilution_analyzer.py` | `data/liquidity_mining_dilution_log.json` |
| `test_protocol_defi_mercenary_capital_risk_analyzer.py` | `data/mercenary_capital_risk_log.json` |
| `test_protocol_defi_position_health_monitor.py` | `data/position_health_monitor_log.json` |
| `test_protocol_defi_protocol_maturity_score_analyzer.py` | `data/protocol_maturity_score_log.json` |
| `test_protocol_defi_reward_token_lockup_discount_analyzer.py` | `data/reward_token_lockup_discount_log.json` |
| `test_protocol_defi_strategy_rebalancing_cost_analyzer.py` | `data/strategy_rebalancing_cost_log.json` |
| `test_protocol_defi_validator_slashing_exposure_analyzer.py` | `data/validator_slashing_exposure_log.json` |
| `test_protocol_defi_vetoken_governance_power_analyzer.py` | `data/vetoken_governance_log.json` |
| `test_protocol_defi_wrapped_asset_backing_verifier.py` | `data/wrapped_asset_backing_log.json` |
| `test_protocol_defi_yield_farming_exit_timing_advisor.py` | `data/yield_farming_exit_timing_log.json` |
| `test_protocol_defi_yield_smoothing_analyzer.py` | `data/yield_smoothing_log.json` |
| `test_protocol_defi_yield_source_dependency_graph_analyzer.py` | `data/yield_source_dependency_graph_log.json` |
| `test_protocol_defi_yield_source_sustainability_ranker.py` | `data/yield_sustainability_rank_log.json` |
| `test_protocol_economic_attack_simulator.py` | `data/attack_simulation_log.json` |
| `test_protocol_ecosystem_health_scorecard.py` | `data/ecosystem_health_log.json` |
| `test_protocol_exit_liquidity_analyzer.py` | `data/exit_liquidity_log.json` |
| `test_protocol_fee_revenue_sustainability_analyzer.py` | `data/fee_revenue_sustainability_log.json` |
| `test_protocol_fee_structure_analyzer.py` | `data/fee_structure_log.json` |
| `test_protocol_insider_activity_monitor.py` | `data/insider_activity_log.json` |
| `test_protocol_ponzi_risk_screener.py` | `data/ponzi_risk_log.json` |
| `test_protocol_real_yield_vs_paper_yield_analyzer.py` | `data/real_vs_paper_yield_log.json` |
