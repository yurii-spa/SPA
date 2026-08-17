"""
_tier_c_key_coverage.py — разметка Tier-C: что известно про КАЖДЫЙ из 180
модулей тира и какие из них помечены «нечем сорсить».

СГЕНЕРИРОВАНО scripts/audit_tier_c_wiring_feasibility.py — НЕ редактировать
вручную; перегенерация (в sandbox-чекауте, не в живом репо — модули пишут
`data/*`-логи относительно корня репо):

    python3 scripts/audit_protocol_blindness.py --tier C --out /tmp/blind_c.json
    python3 scripts/audit_tier_c_wiring_feasibility.py --tier C \
        --out /tmp/feas_c.json --emit-markup --blindness /tmp/blind_c.json

Разметка сшита из ДВУХ замеров, потому что ни один из них по отдельности не
отвечает на нужный вопрос (класс #29/#31/#35–#40 — сторож честно отвечает на
свой вопрос и читается как ответ на другой):

* **аудит слепоты** (2026-08-17T19:33:53.262988Z) отвечает «даёт ли агрегатор от
  модуля число СЕГОДНЯ» — `blindness` в каждой записи;
* **аудит пригодности** (2026-08-17T19:38:18.579889Z) отвечает «можно ли НАЗВАТЬ, каких
  фактов не хватает» — `verdict` / `coverage` / `missing_keys`.

## TIER_C_DISPOSITION — запись, а не удаление

Требование родительской карточки `inbox-tier-c-171-iz-180-modulei-ne-otvechayut`
(пункт 4): списание фиксируется ЗАПИСЬЮ, реестр обязан продолжать знать, что
модуль есть и почему он не считается. `TIER_C_DISPOSITION` — эта запись: по
строке на каждый из 180 модулей тира, ничего не удалено.

Читать её как приговор нельзя: строка `unchecked` означает «мы НЕ ЗНАЕМ»
(агрегатору нечем построить вход движка), а не «измерен ноль». Решение о
списании — за владельцем, карточка
`own-tier-c-spisat-180-modulei-ili-priznat-chto-ne-znaem`.

## UNSOURCED_MODULES — потребляемый набор, численно инертный

Модуль попадает сюда, только если ОБА условия выполнены:

1. `blindness == "failed"` — агрегатор зовёт его сегодня, и он падает, то есть
   числа от него нет ⇒ не звать его численно ИНЕРТНО (ни `modules_ok`, ни
   `avg_score` не меняются; закреплено тестом в обе стороны);
2. недостающие факты можно НАЗВАТЬ поимённо (замер покрытия либо список полей
   из текста исключения).

Оба условия обязательны — fail-CLOSED. Не смогли назвать, чего не хватает ⇒
модуль остаётся громким `failed`, а не получает успокаивающий ярлык. И
наоборот: модуль, который сегодня ДАЁТ число, сюда не попадает никогда, каким
бы плохим ни было его покрытие, — иначе разметка тихо погасила бы работающий
код (урок цикла #136: аннотация не гарантия, первая версия разделения погасила
рабочий модуль Tier-A).

`signal_aggregator._tier_c_pass` не исполняет помеченный модуль и записывает
статус `"unsourced"` с поимённым списком недостающего — вместо `failed`,
который отправлял следующего исполнителя чинить код, в котором чинить нечего.

Снятие пометки — не правка этого файла (он производный), а появление источника
факта либо решение владельца о списании.

Advisory-слой: Tier-C не влияет на аллокацию, RiskPolicy эту разметку не видит.
"""
from typing import Dict, FrozenSet, Tuple

AUDIT_GENERATED_AT = "2026-08-17T19:38:18.579889Z"
BLINDNESS_GENERATED_AT = "2026-08-17T19:33:53.262988Z"
MIN_COVERAGE = 1.0
MODULE_COUNT = 180

#: Сводка по вердиктам слепоты: {'blind_constant': 9, 'unchecked': 162, 'dormant': 4, 'failed': 5}
#: Сводка по вердиктам пригодности: {'BLIND': 44, 'NO_ENTRY': 70, 'RAISES': 24, 'SHAPE_NOT_PROBED': 23, 'NO_SCORE': 16, 'UNCOVERED': 3}

#: module_name -> {"blindness": что даёт агрегатор сегодня,
#:                 "verdict": вердикт пригодности,
#:                 "coverage": доля отданных ключей (None = не измерено),
#:                 "missing_keys": поимённо, чего не хватает}
TIER_C_DISPOSITION: Dict[str, Dict[str, object]] = {
    "airdrop_farming_value_estimator": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.2222,
        "missing_keys": ("airdrop_supply_pct", "base_apy_pct", "days_farming", "estimated_fdv_usd", "points_accrued", "probability", "total_protocol_points"),
    },
    "alert_threshold_manager": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "analytics_pipeline": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "analytics_runner": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "auto_compounder_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "basis_trade_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "benchmark": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "benchmark_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "borrow_rate_optimizer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "borrowing_cost_optimizer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "calmar": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_deployment_pacer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_efficiency_benchmarker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_efficiency_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_efficiency_scorer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_efficiency_tracker": {
        "blindness": "dormant",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "capital_rotation_advisor": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "chain_exposure_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "compounding_strategy_selector": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "covariance_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "covariance_export": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "cross_chain_opportunity": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "daily_digest": {
        "blindness": "dormant",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": ("str",),
    },
    "daily_operations_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "daily_pnl_reconciler": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "debt_ceiling_monitor": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "debt_ratio_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_amm_impermanent_loss_simulator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_borrow_cost_optimizer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2222,
        "missing_keys": ("available_liquidity_usd", "borrow_apy_pct", "borrow_asset", "kink_utilization_pct", "rate_30d_avg_pct", "rate_30d_std_pct", "rate_model"),
    },
    "defi_cycle_phase_detector": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_fixed_rate_duration_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1667,
        "missing_keys": ("days_to_maturity", "face_value_usd", "price_usd", "spot_apy_pct", "symbol"),
    },
    "defi_funding_rate_arbitrage_detector": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.375,
        "missing_keys": ("execution_cost_pct", "perp_funding_rate_pct_8h", "perp_protocol", "spot_lending_apy_pct", "spot_protocol"),
    },
    "defi_impermanent_loss_breakeven_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.5,
        "missing_keys": ("expected_price_divergence_pct", "fee_apr_pct", "horizon_days", "reward_apr_pct"),
    },
    "defi_impermanent_loss_hedging_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.0909,
        "missing_keys": ("apy_with_hedge_pct", "apy_without_hedge_pct", "available_hedges", "correlation_ab", "hedge_cost_annual_pct", "hedge_coverage_pct", "il_pct", "lp_value_usd", "token_a", "token_b"),
    },
    "defi_lending_rate_spread_analyzer": {
        "blindness": "unchecked",
        "verdict": "UNCOVERED",
        "coverage": 0.5,
        "missing_keys": ("borrow_apy_pct", "reserve_factor_pct", "supply_apy_pct"),
    },
    "defi_leverage_looping_optimizer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.125,
        "missing_keys": ("borrow_apy_pct", "liquidation_ltv", "ltv", "max_loops", "reward_apy_pct", "supply_apy_pct", "symbol"),
    },
    "defi_leverage_safety_monitor": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.4444,
        "missing_keys": ("borrow_cost_pct", "collateral_apy_pct", "current_ltv_pct", "leverage_multiplier", "position_health_factor"),
    },
    "defi_lockup_opportunity_cost_analyzer": {
        "blindness": "unchecked",
        "verdict": "UNCOVERED",
        "coverage": 0.4444,
        "missing_keys": ("early_exit_available", "early_exit_penalty_pct", "expected_rate_volatility_pct", "liquid_alternative_apy_pct", "locked_apy_pct"),
    },
    "defi_mev_exposure_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_option_strategy_payoff_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_perpetual_funding_rate_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.3,
        "missing_keys": ("avg_funding_rate_30d_pct", "current_funding_rate_8h_pct", "funding_rate_volatility_pct", "liquidations_24h_usd", "long_short_ratio", "open_interest_usd", "predicted_next_rate_pct"),
    },
    "defi_points_program_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.3,
        "missing_keys": ("days_remaining", "expected_airdrop_token_supply_pct", "points_per_usd_per_day", "program_status", "qualification_difficulty", "token_fdv_estimate_usd", "total_points_issued"),
    },
    "defi_points_to_token_conversion_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.125,
        "missing_keys": ("airdrop_date_days_from_now", "eligible_users_count", "expected_token_allocation_pct", "points_earned_per_dollar_tvl", "similar_protocol_airdrop_usd", "token_fdv_usd", "total_points_issued"),
    },
    "defi_protocol_adoption_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_airdrop_farming_detector": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_auto_compounding_frequency_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_dependency_mapper": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.25,
        "missing_keys": ("bridge_dependency", "dependency_count", "is_upgradeable", "multisig_signers", "oracle_dependency", "underlying_protocols"),
    },
    "defi_protocol_flash_loan_attack_surface_analyzer": {
        "blindness": "failed",
        "verdict": "RAISES",
        "coverage": 0.1,
        "missing_keys": ("audit_count", "days_since_last_audit", "has_price_manipulation_check", "historical_flash_loan_attacks", "price_oracle_type", "protocol_name", "reentrancy_guards", "single_block_borrowable_usd", "total_value_lost_usd"),
    },
    "defi_protocol_funding_rate_arbitrage_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_interest_rate_model_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_interest_rate_sensitivity_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.1667,
        "missing_keys": ("base_rate_pct", "current_borrow_rate_pct", "current_supply_rate_pct", "duration_days", "kink_utilization_pct", "position_type", "protocol_name", "rate_model", "slope1_pct", "slope2_pct"),
    },
    "defi_protocol_lending_rate_spread_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_moat_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2727,
        "missing_keys": ("brand_recognition_score", "clone_count", "integrations_count", "market_share_pct", "network_effect_score", "protocol_owned_liquidity_pct", "switching_cost_score", "years_operating"),
    },
    "defi_protocol_net_interest_margin_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.4286,
        "missing_keys": ("borrow_apy_pct", "protocol_name", "reserve_factor_pct", "supply_apy_pct"),
    },
    "defi_protocol_reserve_factor_economics_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.375,
        "missing_keys": ("borrow_apr_pct", "current_reserves_usd", "reserve_factor_pct", "supply_apy_pct", "total_borrows_usd"),
    },
    "defi_protocol_sandwich_attack_exposure_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.0,
        "missing_keys": ("avg_block_time_seconds", "gas_priority_fee_gwei", "has_commit_reveal", "mempool_visibility", "mev_bot_activity_score", "pool_tvl_usd", "protocol_name", "slippage_tolerance_pct", "trade_size_usd", "uses_private_rpc"),
    },
    "defi_protocol_sandwich_attack_vulnerability_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1818,
        "missing_keys": ("base_fee_gwei", "flashbots_protected", "gas_price_gwei", "max_priority_fee_gwei", "mempool_visible", "mev_blocker_enabled", "private_rpc", "slippage_tolerance_pct", "trade_size_usd"),
    },
    "defi_protocol_slippage_impact_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_supply_cap_proximity_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_token_unlock_impact_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2,
        "missing_keys": ("circulating_supply_usd", "daily_volume_usd", "historical_unlock_price_impact_pct", "next_unlock_amount_usd", "next_unlock_beneficiary", "next_unlock_date_days", "unlock_cliff", "upcoming_unlocks_12mo_usd"),
    },
    "defi_protocol_token_unlock_price_impact_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_protocol_token_velocity_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1818,
        "missing_keys": ("avg_hold_duration_days", "circulating_supply", "market_cap_usd", "on_chain_tx_count_30d", "staked_pct", "trading_volume_30d_usd", "unique_wallets_30d", "utility_uses", "vesting_locked_pct"),
    },
    "defi_protocol_token_vesting_overhang_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.0,
        "missing_keys": ("avg_daily_volume_usd", "circulating_supply", "current_price_usd", "token_symbol", "total_supply", "upcoming_unlocks"),
    },
    "defi_protocol_treasury_diversification_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.0,
        "missing_keys": ("monthly_burn_usd", "protocol_name", "revenue_usd_per_month", "treasury_holdings", "vesting_unlocks_6m_usd"),
    },
    "defi_protocol_validator_set_decentralization_analyzer": {
        "blindness": "dormant",
        "verdict": "BLIND",
        "coverage": 0.0769,
        "missing_keys": ("client_diversity_score", "geographic_distribution_score", "nakamoto_coefficient", "network_type", "sequencer_centralized", "slashing_incidents_count", "time_to_finality_seconds", "top10_validator_stake_pct", "top5_validator_stake_pct", "top_validator_stake_pct", "upgrade_multisig_threshold", "validator_count"),
    },
    "defi_protocol_vault_strategy_diversification_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.5,
        "missing_keys": ("weight_pct", "yield_type"),
    },
    "defi_sentiment_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "defi_slippage_impact_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.125,
        "missing_keys": ("concentration_factor", "pool_fee_pct", "pool_liquidity_usd", "pool_type", "price_impact_observed_pct", "token_pair", "trade_size_usd"),
    },
    "defi_tax_lot_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.3333,
        "missing_keys": ("disposal", "lots"),
    },
    "defi_vault_rebalancing_cost_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2,
        "missing_keys": ("aum_usd", "current_weights", "gas_price_gwei", "last_rebalance_days_ago", "pool_depths", "rebalance_frequency_days", "slippage_model", "target_weights"),
    },
    "defi_vault_strategy_comparator": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1111,
        "missing_keys": ("gas_cost_per_month_usd", "max_capital_usd", "min_capital_usd", "net_apy_pct", "rebalance_frequency_days", "requires_active_management", "risk_multiplier", "strategy_type"),
    },
    "defi_whale_impact_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.3333,
        "missing_keys": ("daily_volume_usd", "fee_apy", "pool_id", "whale_transactions"),
    },
    "drawdown": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "drawdown_recovery_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "drawdown_tracker": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "exit_timing_optimizer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "funding_rate_arbitrage_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "funding_rate_arbitrage_detector": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.25,
        "missing_keys": ("collateral_ratio", "perp_funding_rate_8h_bps", "spot_apy_pct"),
    },
    "funding_rate_monitor": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "honest_metrics": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "impermanent_loss_calculator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "impermanent_loss_hedger": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "impermanent_loss_predictor": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.375,
        "missing_keys": ("days_in_position", "fee_apy", "pool_type", "price_ratio_current", "price_ratio_entry"),
    },
    "impermanent_loss_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "leverage_ratio_monitor": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.8,
        "missing_keys": ("maintenance_margin_pct",),
    },
    "monthly_summary_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "multi_chain_monitor": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "network_congestion_monitor": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "performance_attribution": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "performance_benchmark_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "performance_regression_detector": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_adoption_scorer": {
        "blindness": "failed",
        "verdict": "RAISES",
        "coverage": 0.5,
        "missing_keys": ("unique_users_30d",),
    },
    "protocol_adoption_velocity_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.5,
        "missing_keys": ("age_days",),
    },
    "protocol_airdrop_eligibility_optimizer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_community_sentiment_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1,
        "missing_keys": ("bug_reports_open", "community_grants_usd", "days_since_exploit", "discord_active_members_30d", "github_commits_30d", "governance_proposals_90d", "governance_voter_participation_pct", "twitter_engagement_rate_pct", "twitter_followers"),
    },
    "protocol_cross_chain_bridge_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_cross_protocol_contagion_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_dao_treasury_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_aave_efficiency_mode_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_borrow_rate_mode_optimizer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_borrow_rate_stability_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_debt_ceiling_proximity_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_interest_rate_kink_proximity_analyzer": {
        "blindness": "failed",
        "verdict": "UNCOVERED",
        "coverage": 0.3,
        "missing_keys": ("available_liquidity_usd", "base_rate_pct", "data_quality", "kink_utilization_pct", "reserve_factor_pct", "slope1_pct", "slope2_pct"),
    },
    "protocol_defi_points_program_value_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_points_system_valuation_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_price_impact_depth_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_protocol_maturity_score_analyzer": {
        "blindness": "failed",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": ("audit_count", "chain_count", "github_commits_90d", "has_dao", "launch_date_days_ago", "num_security_incidents", "protocol_name", "token_market_cap_usd", "total_loss_usd", "tvl_peak_usd", "unique_users_30d"),
    },
    "protocol_defi_protocol_revenue_sustainability_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2222,
        "missing_keys": ("market_dependent_revenue_pct", "revenue_sources", "revenue_trend_pct", "token_emissions_weekly_usd", "treasury_runway_months", "weekly_costs_usd", "weekly_revenue_usd"),
    },
    "protocol_defi_real_world_asset_bridge_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1875,
        "missing_keys": ("counterparty_default_risk_score", "custodian_name", "custodian_regulated", "kyc_required", "legal_wrapper", "min_investment_usd", "net_yield_pct", "on_chain_audit_frequency", "protocol_fee_pct", "redemption_mechanism", "rwa_category", "secondary_market_liquidity_score", "underlying_yield_pct"),
    },
    "protocol_defi_smart_money_flow_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_strategy_rebalancing_cost_analyzer": {
        "blindness": "dormant",
        "verdict": "NO_SCORE",
        "coverage": 0.0,
        "missing_keys": ("asset_values_usd", "current_weights", "gas_per_trade_usd", "portfolio_apy_pct", "protocol_name", "rebalance_frequency_days", "slippage_per_trade_pct", "target_apy_improvement_pct", "target_weights"),
    },
    "protocol_defi_token_buyback_impact_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_token_unlock_pressure_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_treasury_runway_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_defi_validator_slashing_exposure_analyzer": {
        "blindness": "failed",
        "verdict": "BLIND",
        "coverage": 0.2727,
        "missing_keys": ("annual_correlated_slash_prob", "annual_downtime_slash_prob", "correlated_penalty_pct", "data_quality", "downtime_penalty_pct", "num_validators", "operator_concentration_pct", "restaking_layers"),
    },
    "protocol_defi_ve_token_lock_optimizer": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_developer_activity_tracker": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1818,
        "missing_keys": ("active_contributors_30d", "closed_issues_30d", "commits_last_30d", "commits_last_90d", "days_since_last_commit", "days_since_last_release", "has_bug_bounty", "open_issues", "total_contributors"),
    },
    "protocol_dominance_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_dominance_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.75,
        "missing_keys": ("tvl_7d_ago_usd",),
    },
    "protocol_economic_attack_simulator": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.125,
        "missing_keys": ("avg_block_governance_votes", "circulating_supply", "governance_token_price_usd", "has_flash_loan_guard", "majority_threshold_pct", "oracle_manipulation_cost_usd", "time_lock_hours"),
    },
    "protocol_hack_recovery_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_incentive_decay_monitor": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_incentive_sustainability_scorer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.1,
        "missing_keys": ("incentive_to_revenue_ratio", "incentive_token", "incentive_tvl_usd", "monthly_incentive_budget_usd", "monthly_organic_revenue_usd", "organic_tvl_usd", "similar_protocol_post_incentive_tvl_drop_pct", "token_treasury_remaining_months", "user_retention_rate_pct"),
    },
    "protocol_insider_activity_monitor": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1111,
        "missing_keys": ("days_since_last_team_dump", "governance_token_mcap_usd", "governance_token_sales_30d_usd", "team_token_holdings_pct", "team_wallet_outflows_30d_usd", "token_price_change_30d_pct", "treasury_to_team_transfers_30d_usd", "unusual_tx_count_7d"),
    },
    "protocol_maturity_scorer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_network_effect_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1111,
        "missing_keys": ("cross_chain_deployments", "dependent_tvl_usd", "integrations_count", "monthly_active_users", "own_tvl_usd", "tx_count_30d", "unique_token_holders", "user_growth_30d_pct"),
    },
    "protocol_network_effect_strength_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.25,
        "missing_keys": ("avg_transaction_value_usd", "data_network_effect", "monthly_active_users", "monthly_active_users_3m_ago", "switching_cost_score", "total_integrations", "total_integrations_3m_ago", "transaction_count_30d", "tvl_3m_ago_usd"),
    },
    "protocol_partnership_network_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.0,
        "missing_keys": ("protocols",),
    },
    "protocol_registry": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_reputation_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.0769,
        "missing_keys": ("age_months", "audit_count", "github_stars", "has_bug_bounty", "has_code_of_conduct", "institutional_backers", "open_source", "regulatory_issues", "team_doxxed", "total_hacks_usd", "tvl_peak_usd", "twitter_followers"),
    },
    "protocol_revenue_diversification_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1429,
        "missing_keys": ("age_months", "chain_count", "revenue_sources", "token_price_dependency", "total_monthly_revenue_usd", "user_count"),
    },
    "protocol_revenue_predictor": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_revenue_quality_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.0833,
        "missing_keys": ("cyclical_dependency", "has_recurring_revenue", "incentive_revenue_pct", "liquidation_fee_revenue_pct", "protocol_fee_revenue_pct", "revenue_30d_vs_90d_avg_ratio", "revenue_concentration_top3_users_pct", "revenue_growth_mom_pct", "total_revenue_30d_usd", "trading_fee_revenue_pct", "unique_revenue_sources_count"),
    },
    "protocol_revenue_share_analyzer": {
        "blindness": "blind_constant",
        "verdict": "BLIND",
        "coverage": 0.1429,
        "missing_keys": ("buyback_pct", "revenue_to_holders_pct", "revenue_to_team_pct", "revenue_to_treasury_pct", "token_holders_count", "total_revenue_usd_annual"),
    },
    "protocol_revenue_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_security_incident_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_smart_contract_age_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1,
        "missing_keys": ("contract_age_days", "current_tvl_usd", "exploit_count", "exploit_total_loss_usd", "formal_verification", "last_upgrade_days_ago", "lines_of_code", "peak_tvl_usd", "upgrade_count"),
    },
    "protocol_smart_contract_complexity_scorer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2,
        "missing_keys": ("assembly_blocks_count", "audit_count", "critical_bugs_found", "cross_contract_calls", "days_live", "external_call_count", "function_count", "inheritance_depth", "lines_of_code", "oracle_dependencies", "proxy_pattern", "upgrade_mechanism"),
    },
    "protocol_smart_money_flow_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.2,
        "missing_keys": ("days_since_last_large_deposit", "large_wallet_count", "price_correlation_30d", "retail_inflow_30d_usd", "retail_outflow_30d_usd", "smart_money_tvl_pct", "smart_wallet_inflow_30d_usd", "smart_wallet_outflow_30d_usd"),
    },
    "protocol_stress_tester": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_token_buyback_tracker": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.1111,
        "missing_keys": ("buyback_frequency", "buyback_usd_30d", "circulating_supply", "market_cap_usd", "revenue_usd_30d", "token_price_usd", "token_symbol", "tokens_burned"),
    },
    "protocol_token_distribution_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.5,
        "missing_keys": ("allocations", "token_age_months"),
    },
    "protocol_token_unlock_schedule_analyzer": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.125,
        "missing_keys": ("circulating_supply", "current_price_usd", "daily_volume_usd", "market_cap_usd", "total_supply", "upcoming_unlocks", "vesting_cliff_days"),
    },
    "protocol_tokenomics_stress_tester": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_total_value_secured_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_treasury_runway_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.125,
        "missing_keys": ("has_dao_vote_for_spending", "monthly_burn_usd", "monthly_revenue_usd", "token_price_usd", "token_treasury_amount", "treasury_usd", "vesting_unlock_usd_per_month"),
    },
    "protocol_upgrade_impact_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_upgrade_impact_assessor": {
        "blindness": "unchecked",
        "verdict": "BLIND",
        "coverage": 0.0909,
        "missing_keys": ("affected_tvl_usd", "community_approval_pct", "has_audit", "historical_similar_upgrades_count", "last_upgrade_issues_count", "magnitude_score", "migration_period_days", "scheduled_date_days", "upgrade_type", "user_action_required"),
    },
    "protocol_user_incentive_analyzer": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_validator_economics_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.0909,
        "missing_keys": ("annual_reward_usd", "chain_inflation_rate_pct", "commission_pct", "delegated_stake_usd", "operating_cost_usd_monthly", "self_stake_pct", "slashing_events_count", "stake_usd", "uptime_pct", "validator_count_total"),
    },
    "protocol_vetoken_bribe_efficiency_analyzer": {
        "blindness": "unchecked",
        "verdict": "NO_SCORE",
        "coverage": 0.1667,
        "missing_keys": ("bribe_usd", "emissions_usd", "epochs_per_year", "vote_value_usd", "votes"),
    },
    "protocol_volume_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "protocol_whale_wallet_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "quarterly_summary_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "rate_sensitivity_analyzer": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "scenario_simulator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "sharpe": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "sharpe_ratio_calculator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "slippage_impact_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "slippage_model_advisor": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "slippage_simulator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "smart_money_flow_detector": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "smart_money_flow_tracker": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
    "sortino_ratio_calculator": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "strategy_comparison_matrix": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "strategy_drawdown_guard": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "strategy_promoter": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "strategy_tournament": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "streak": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "system_config_validator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "telegram_daily_digest": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "tier_exposure_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "time_weighted_return_calculator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "token_price_impact_estimator": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "token_unlock_monitor": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": 0.5,
        "missing_keys": ("unlock_date_ts",),
    },
    "token_vesting_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "vault_migration_advisor": {
        "blindness": "unchecked",
        "verdict": "RAISES",
        "coverage": None,
        "missing_keys": (),
    },
    "vault_share_tracker": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "weekly_summary_report": {
        "blindness": "unchecked",
        "verdict": "NO_ENTRY",
        "coverage": None,
        "missing_keys": (),
    },
    "whale_alert_detector": {
        "blindness": "unchecked",
        "verdict": "SHAPE_NOT_PROBED",
        "coverage": None,
        "missing_keys": (),
    },
}

#: Потребляемый набор (см. докстринг): агрегатор их НЕ исполняет и пишет
#: honest-статус "unsourced" с поимённым списком недостающих фактов.
UNSOURCED_DETAIL: Dict[str, Dict[str, object]] = {
    "defi_protocol_flash_loan_attack_surface_analyzer": {
        "coverage": 0.1,
        "missing_keys": ("audit_count", "days_since_last_audit", "has_price_manipulation_check", "historical_flash_loan_attacks", "price_oracle_type", "protocol_name", "reentrancy_guards", "single_block_borrowable_usd", "total_value_lost_usd"),
    },
    "protocol_adoption_scorer": {
        "coverage": 0.5,
        "missing_keys": ("unique_users_30d",),
    },
    "protocol_defi_interest_rate_kink_proximity_analyzer": {
        "coverage": 0.3,
        "missing_keys": ("available_liquidity_usd", "base_rate_pct", "data_quality", "kink_utilization_pct", "reserve_factor_pct", "slope1_pct", "slope2_pct"),
    },
    "protocol_defi_protocol_maturity_score_analyzer": {
        "coverage": None,
        "missing_keys": ("audit_count", "chain_count", "github_commits_90d", "has_dao", "launch_date_days_ago", "num_security_incidents", "protocol_name", "token_market_cap_usd", "total_loss_usd", "tvl_peak_usd", "unique_users_30d"),
    },
    "protocol_defi_validator_slashing_exposure_analyzer": {
        "coverage": 0.2727,
        "missing_keys": ("annual_correlated_slash_prob", "annual_downtime_slash_prob", "correlated_penalty_pct", "data_quality", "downtime_penalty_pct", "num_validators", "operator_concentration_pct", "restaking_layers"),
    },
}

UNSOURCED_MODULES: FrozenSet[str] = frozenset(UNSOURCED_DETAIL)

__all__: Tuple[str, ...] = (
    "AUDIT_GENERATED_AT", "BLINDNESS_GENERATED_AT", "MIN_COVERAGE",
    "MODULE_COUNT", "TIER_C_DISPOSITION", "UNSOURCED_DETAIL",
    "UNSOURCED_MODULES",
)
