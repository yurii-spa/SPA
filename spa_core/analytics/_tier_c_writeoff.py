"""_tier_c_writeoff.py — реестр списанных и замороженных модулей Tier-C.

**Решение владельца 2026-08-25** по карточке «Списать 180 фоновых модулей Tier-C
или честно записать, что мы про них не знаем» — ответ «все по рекомендациям»,
то есть **1А** по первому вопросу и **2А** по второму (ADR-133):

* **1А — СПИСАТЬ девять константных.** Они единственные, кто в Tier-C вообще
  отвечает, и именно из них целиком складывается публикуемое ``avg_score``.
  Замер: балл одинаков для всех протоколов аудита — модуль не читает, о каком
  протоколе его спросили. Не исполняем, из ``avg_score`` не публикуем, запись о
  каждом остаётся здесь с причиной (ничего не удаляется).
  «Константа, притворяющаяся замером, хуже пустоты» — формулировка карточки.
* **2А — 162 записать «мы не знаем» и заморозить.** Это НЕ списание: списание
  было бы утверждением о бесполезности, а его у нас нет. Мы знаем только, что
  позвать их нечем (пригодных к проводке — ноль из 180, замер
  ``audit_tier_c_wiring_feasibility.py``). Они и дальше честно считаются в
  знаменателе как неработающие (статус ``unchecked`` в ``module_status``), и
  НЕ публикуются как работающий слой.

Провенанс — воспроизводимый замер, а не список из головы:

    python3 scripts/audit_protocol_blindness.py --tier C --out <файл>
    modules=180 counts={'blind_constant': 9, 'unchecked': 162, 'dormant': 4, 'failed': 5}

Снят 2026-08-26T12:01:27.478337Z. Tier-C — советующий слой: капитал он не двигает,
RiskPolicy и стоп-кран этот файл не касается.
"""
from typing import Dict, FrozenSet

#: Когда снят замер, из которого построен этот реестр.
AUDIT_GENERATED_AT = "2026-08-26T12:01:27.478337Z"

#: 1А — СПИСАНЫ: не исполняются, в avg_score не попадают. Имя → измеренная причина.
WRITTEN_OFF: Dict[str, str] = {
    "airdrop_farming_value_estimator":
        "константа 0.0 на всех протоколах аудита",
    "defi_protocol_interest_rate_sensitivity_analyzer":
        "константа 0.0 на всех протоколах аудита",
    "defi_protocol_net_interest_margin_analyzer":
        "константа 0.0 на всех протоколах аудита",
    "defi_protocol_reserve_factor_economics_analyzer":
        "константа 0.0 на всех протоколах аудита",
    "defi_protocol_sandwich_attack_exposure_analyzer":
        "константа 45.0 на всех протоколах аудита",
    "defi_protocol_token_vesting_overhang_analyzer":
        "константа 0.0 на всех протоколах аудита",
    "defi_protocol_treasury_diversification_analyzer":
        "константа 100.0 на всех протоколах аудита",
    "protocol_partnership_network_analyzer":
        "константа 0.0 на всех протоколах аудита",
    "protocol_revenue_share_analyzer":
        "константа 40.0 на всех протоколах аудита",
}

#: 2А — «не знаем», заморожены: НЕ списаны и НЕ починены, позвать их нечем.
#: Исполнение не запрещаем — они и так не отвечают и честно идут в знаменатель.
UNKNOWN_FROZEN: FrozenSet[str] = frozenset({
    "alert_threshold_manager",
    "analytics_pipeline",
    "analytics_runner",
    "auto_compounder_analyzer",
    "basis_trade_analyzer",
    "benchmark",
    "benchmark_tracker",
    "borrow_rate_optimizer",
    "borrowing_cost_optimizer",
    "calmar",
    "capital_deployment_pacer",
    "capital_efficiency_benchmarker",
    "capital_efficiency_report",
    "capital_efficiency_scorer",
    "capital_rotation_advisor",
    "chain_exposure_report",
    "compounding_strategy_selector",
    "covariance_estimator",
    "covariance_export",
    "cross_chain_opportunity",
    "daily_operations_report",
    "daily_pnl_reconciler",
    "debt_ceiling_monitor",
    "debt_ratio_analyzer",
    "defi_amm_impermanent_loss_simulator",
    "defi_borrow_cost_optimizer",
    "defi_cycle_phase_detector",
    "defi_fixed_rate_duration_analyzer",
    "defi_funding_rate_arbitrage_detector",
    "defi_impermanent_loss_breakeven_analyzer",
    "defi_impermanent_loss_hedging_analyzer",
    "defi_lending_rate_spread_analyzer",
    "defi_leverage_looping_optimizer",
    "defi_leverage_safety_monitor",
    "defi_lockup_opportunity_cost_analyzer",
    "defi_mev_exposure_estimator",
    "defi_option_strategy_payoff_analyzer",
    "defi_perpetual_funding_rate_analyzer",
    "defi_points_program_analyzer",
    "defi_points_to_token_conversion_analyzer",
    "defi_protocol_adoption_tracker",
    "defi_protocol_airdrop_farming_detector",
    "defi_protocol_auto_compounding_frequency_analyzer",
    "defi_protocol_dependency_mapper",
    "defi_protocol_funding_rate_arbitrage_analyzer",
    "defi_protocol_interest_rate_model_analyzer",
    "defi_protocol_lending_rate_spread_analyzer",
    "defi_protocol_moat_analyzer",
    "defi_protocol_sandwich_attack_vulnerability_scorer",
    "defi_protocol_slippage_impact_analyzer",
    "defi_protocol_supply_cap_proximity_analyzer",
    "defi_protocol_token_unlock_impact_analyzer",
    "defi_protocol_token_unlock_price_impact_estimator",
    "defi_protocol_token_velocity_analyzer",
    "defi_protocol_vault_strategy_diversification_scorer",
    "defi_sentiment_tracker",
    "defi_slippage_impact_estimator",
    "defi_tax_lot_tracker",
    "defi_vault_rebalancing_cost_analyzer",
    "defi_vault_strategy_comparator",
    "defi_whale_impact_analyzer",
    "drawdown",
    "drawdown_recovery_tracker",
    "drawdown_tracker",
    "exit_timing_optimizer",
    "funding_rate_arbitrage_analyzer",
    "funding_rate_arbitrage_detector",
    "funding_rate_monitor",
    "honest_metrics",
    "impermanent_loss_calculator",
    "impermanent_loss_hedger",
    "impermanent_loss_predictor",
    "impermanent_loss_tracker",
    "leverage_ratio_monitor",
    "monthly_summary_report",
    "multi_chain_monitor",
    "network_congestion_monitor",
    "performance_attribution",
    "performance_benchmark_tracker",
    "performance_regression_detector",
    "protocol_adoption_velocity_tracker",
    "protocol_airdrop_eligibility_optimizer",
    "protocol_community_sentiment_scorer",
    "protocol_cross_chain_bridge_analyzer",
    "protocol_cross_protocol_contagion_analyzer",
    "protocol_dao_treasury_analyzer",
    "protocol_defi_aave_efficiency_mode_analyzer",
    "protocol_defi_borrow_rate_mode_optimizer",
    "protocol_defi_borrow_rate_stability_analyzer",
    "protocol_defi_debt_ceiling_proximity_analyzer",
    "protocol_defi_points_program_value_estimator",
    "protocol_defi_points_system_valuation_analyzer",
    "protocol_defi_price_impact_depth_analyzer",
    "protocol_defi_protocol_revenue_sustainability_analyzer",
    "protocol_defi_real_world_asset_bridge_analyzer",
    "protocol_defi_smart_money_flow_analyzer",
    "protocol_defi_token_buyback_impact_analyzer",
    "protocol_defi_token_unlock_pressure_analyzer",
    "protocol_defi_treasury_runway_analyzer",
    "protocol_defi_ve_token_lock_optimizer",
    "protocol_developer_activity_tracker",
    "protocol_dominance_analyzer",
    "protocol_dominance_tracker",
    "protocol_economic_attack_simulator",
    "protocol_hack_recovery_tracker",
    "protocol_incentive_decay_monitor",
    "protocol_incentive_sustainability_scorer",
    "protocol_insider_activity_monitor",
    "protocol_maturity_scorer",
    "protocol_network_effect_scorer",
    "protocol_network_effect_strength_analyzer",
    "protocol_registry",
    "protocol_reputation_scorer",
    "protocol_revenue_diversification_scorer",
    "protocol_revenue_predictor",
    "protocol_revenue_quality_scorer",
    "protocol_revenue_tracker",
    "protocol_security_incident_tracker",
    "protocol_smart_contract_age_scorer",
    "protocol_smart_contract_complexity_scorer",
    "protocol_smart_money_flow_analyzer",
    "protocol_stress_tester",
    "protocol_token_buyback_tracker",
    "protocol_token_distribution_analyzer",
    "protocol_token_unlock_schedule_analyzer",
    "protocol_tokenomics_stress_tester",
    "protocol_total_value_secured_analyzer",
    "protocol_treasury_runway_analyzer",
    "protocol_upgrade_impact_analyzer",
    "protocol_upgrade_impact_assessor",
    "protocol_user_incentive_analyzer",
    "protocol_validator_economics_analyzer",
    "protocol_vetoken_bribe_efficiency_analyzer",
    "protocol_volume_analyzer",
    "protocol_whale_wallet_tracker",
    "quarterly_summary_report",
    "rate_sensitivity_analyzer",
    "scenario_simulator",
    "sharpe",
    "sharpe_ratio_calculator",
    "slippage_impact_estimator",
    "slippage_model_advisor",
    "slippage_simulator",
    "smart_money_flow_detector",
    "smart_money_flow_tracker",
    "sortino_ratio_calculator",
    "strategy_comparison_matrix",
    "strategy_drawdown_guard",
    "strategy_promoter",
    "strategy_tournament",
    "streak",
    "system_config_validator",
    "telegram_daily_digest",
    "tier_exposure_report",
    "time_weighted_return_calculator",
    "token_price_impact_estimator",
    "token_unlock_monitor",
    "token_vesting_tracker",
    "vault_migration_advisor",
    "vault_share_tracker",
    "weekly_summary_report",
    "whale_alert_detector",
})

#: Прочие исходы того же замера — для полноты картины (не списаны, не заморожены).
DORMANT: FrozenSet[str] = frozenset(['capital_efficiency_tracker', 'daily_digest', 'defi_protocol_validator_set_decentralization_analyzer', 'protocol_defi_strategy_rebalancing_cost_analyzer'])
FAILED: FrozenSet[str] = frozenset(['defi_protocol_flash_loan_attack_surface_analyzer', 'protocol_adoption_scorer', 'protocol_defi_interest_rate_kink_proximity_analyzer', 'protocol_defi_protocol_maturity_score_analyzer', 'protocol_defi_validator_slashing_exposure_analyzer'])
