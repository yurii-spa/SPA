"""
_protocol_key_coverage.py — эмпирическая разметка Tier-B модулей, которые
различают протоколы ПОБОЧНЫМИ полями.

СГЕНЕРИРОВАНО scripts/audit_tier_c_wiring_feasibility.py — НЕ редактировать
вручную; перегенерация:
    python3 scripts/audit_tier_c_wiring_feasibility.py --tier B \
        --out /tmp/feas_b.json --emit-markup
(в sandbox-чекауте, не в живом репо — модули пишут data/*-логи).

Замер 2026-08-06T18:46:04.014316Z: каждый Tier-B модуль прогнан на
`_protocol_facts.generic_profile_for` для ['aave_v3', 'maple', 'pendle', 'morpho', 'spark', 'compound_v3'];
запись подменена на `RecordingProfile`, который помнит, какие ключи у неё
спрашивали. Модуль попадает сюда, если его score РАЗЛИЧАЕТСЯ между
протоколами, но профиль не отдаёт часть ключей, которые движок читает
(покрытие < 1.0): отсутствующий ключ молча становится 0.0/False,
и всё различие приходит из побочных полей вроде `utilization_rate_pct`.

**Почему этого мало — «различается»**. Аудит слепоты
(`audit_protocol_blindness.py`) считает такой модуль `sensitive`, «работает».
Одинаковая константа видна глазом; правдоподобно различающееся число — нет.
Это класс fail-OPEN мониторов (#29/#31/#35–#38/#40), вывернутый наизнанку: не
«✅ OK о непроверенном», а РАЗЛИЧАЮЩЕЕСЯ число о неизмеренном.

`signal_aggregator.run_tier_b` исключает эти модули из composite и из
числителя confidence, статус `"unsourced"` — ровно так же, как
`PROTOCOL_BLIND_MODULES`. Advisory-слой; Tier-A разметку не потребляет,
RiskPolicy её не видит.

Снятие пометки — не правка этого файла, а одно из трёх (карточка
`inbox-tier-b-19-modulei-chislyatsya-rabotayusc`): дописать факт в
`_protocol_facts`, подключить живой фид, либо честно списать модуль. После
любого из них разметка перегенерируется и модуль уходит отсюда сам.
"""
from typing import Dict, FrozenSet, Tuple

AUDIT_GENERATED_AT = "2026-08-06T18:46:04.014316Z"
MIN_COVERAGE = 1.0

#: module_name -> {"coverage": доля отданных ключей, "missing_keys": чего нет}
UNSOURCED_DETAIL: Dict[str, Dict[str, object]] = {
    "defi_gas_cost_yield_drag_analyzer": {
        "coverage": 0.9,
        "missing_keys": ("harvests_per_year",),
    },
    "defi_oracle_risk_scorer": {
        "coverage": 0.875,
        "missing_keys": ("max_price_deviation_pct",),
    },
    "defi_protocol_borrower_concentration_risk_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("avg_collateral_ratio", "protocol_reserve_usd", "top_borrower_amounts_usd"),
    },
    "defi_protocol_cdp_stability_fee_analyzer": {
        "coverage": 0.1818,
        "missing_keys": ("collateral_asset", "current_price_usd", "debt_utilization_pct", "liquidation_ratio_pct", "protocol_name", "stability_fee_pct", "surplus_buffer_usd", "target_price_usd", "total_debt_ceiling_usd"),
    },
    "defi_protocol_composability_risk_analyzer": {
        "coverage": 0.1818,
        "missing_keys": ("auto_unwind_available", "base_protocol", "base_protocol_audit_score", "dependency_depth", "dependent_protocol", "historical_issues_count", "integration_type", "time_to_unwind_hours", "tvl_at_risk_usd"),
    },
    "defi_protocol_emergency_withdrawal_pause_risk_analyzer": {
        "coverage": 0.5455,
        "missing_keys": ("annual_pause_probability_pct", "assumed_apy_pct", "emergency_exit_available", "historical_max_pause_days", "unpause_timelock_hours"),
    },
    "defi_protocol_lending_market_health_scorer": {
        "coverage": 0.4545,
        "missing_keys": ("liquidation_incentive_pct", "paused_markets", "protocol_name", "reserve_factor_pct", "top_borrower_concentration_pct", "total_markets"),
    },
    "defi_protocol_mev_protection_effectiveness_analyzer": {
        "coverage": 0.5455,
        "missing_keys": ("has_commit_reveal", "has_sandwich_guard", "historical_mev_losses_usd", "order_flow_auction", "slippage_protection_pct"),
    },
    "defi_protocol_oracle_manipulation_risk_analyzer": {
        "coverage": 0.2857,
        "missing_keys": ("historical_manipulation_incidents", "manipulation_cost_usd_estimate", "oracle_sources_count", "tvl_at_risk_usd", "twap_window_seconds"),
    },
    "defi_protocol_regulatory_risk_scorer": {
        "coverage": 0.3571,
        "missing_keys": ("dao_governance", "defi_category", "entity_incorporated", "front_end_geo_restrictions", "regulator_action_history", "sanctions_screening", "settlement_layer", "stablecoin_exposure_pct", "team_public"),
    },
    "defi_protocol_vault_apr_lookback_window_selection_bias_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_protocol_vault_apr_quote_staleness_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_protocol_vault_instant_exit_nav_discount_analyzer": {
        "coverage": 0.2222,
        "missing_keys": ("instant_exit_discount_pct", "instant_exit_price_usd", "nav_per_share_usd", "redeploy_apr_pct", "token", "vault", "vault_apr_pct"),
    },
    "defi_protocol_vault_redemption_cooldown_exposure_analyzer": {
        "coverage": 0.3333,
        "missing_keys": ("daily_volatility_pct", "earns_during_cooldown", "exit_urgency_days", "token", "vault", "vault_apr_pct"),
    },
    "defi_protocol_vault_relative_yield_outlier_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_protocol_vault_round_trip_cost_analyzer": {
        "coverage": 0.4444,
        "missing_keys": ("apr_advantage_pct", "deposit_fee_pct", "expected_holding_days", "token", "vault"),
    },
    "defi_protocol_vault_yield_realization_gap_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_protocol_vault_yield_variance_drag_realization_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("data_dir",),
    },
    "defi_token_governance_power_analyzer": {
        "coverage": 0.5714,
        "missing_keys": ("active_voters_30d", "avg_voter_turnout_pct", "team_treasury_pct"),
    },
    "defi_yield_bearing_collateral_analyzer": {
        "coverage": 0.2727,
        "missing_keys": ("asset_name", "borrow_rate_pct", "current_ltv_pct", "daily_ltv_drift_pct", "price_deviation_risk_pct", "protocol_used_as_collateral", "rebasing_type", "underlying_apy_pct"),
    },
    "lending_pool_utilization_analyzer": {
        "coverage": 0.375,
        "missing_keys": ("base_rate", "optimal_utilization", "reserve_factor", "slope1", "slope2"),
    },
    "protocol_audit_coverage_scorer": {
        "coverage": 0.2,
        "missing_keys": ("audit_count", "audit_coverage_pct", "auditor_tier", "critical_findings_unresolved", "days_since_last_audit", "formal_verification", "high_findings_unresolved", "lines_of_code"),
    },
    "protocol_defi_position_health_monitor": {
        "coverage": 0.1667,
        "missing_keys": ("apy_earned_pct", "current_value_usd", "days_held", "entry_value_usd", "exit_cost_usd", "health_factor", "il_pct", "position_type", "protocol_name", "unrealized_pnl_usd"),
    },
    "protocol_defi_stable_yield_consistency_scorer": {
        "coverage": 0.2857,
        "missing_keys": ("apy_history", "has_rate_lock", "lock_duration_days", "protocol_name", "yield_source"),
    },
    "protocol_defi_vault_fee_structure_breakeven_analyzer": {
        "coverage": 0.5556,
        "missing_keys": ("aum_usd", "hurdle_rate_pct", "peer_avg_total_fee_load_pct", "target_net_apy_pct"),
    },
    "protocol_defi_yield_bearing_stablecoin_risk_analyzer": {
        "coverage": 0.1667,
        "missing_keys": ("collateral_apy_pct", "collateral_asset", "collateral_ratio_pct", "current_price_usd", "days_since_depeg_event", "peg_asset", "protocol_tvl_usd", "redemption_delay_days", "token_name", "yield_source"),
    },
    "protocol_defi_yield_duration_mismatch_analyzer": {
        "coverage": 0.4545,
        "missing_keys": ("asset_avg_maturity_days", "asset_yield_apy_pct", "fixed_rate_assets", "floating_rate_liabilities", "funding_cost_apy_pct", "liability_avg_redemption_days"),
    },
    "protocol_ecosystem_health_scorecard": {
        "coverage": 0.1429,
        "missing_keys": ("audit_count", "chain_count", "community_score", "daily_active_users", "dau_30d_change_pct", "developer_count", "github_commits_30d", "incident_count_12m", "integrations_count", "revenue_monthly_usd", "token_price_change_30d_pct", "tvl_30d_change_pct"),
    },
    "protocol_governance_attack_resistance_scorer": {
        "coverage": 0.2727,
        "missing_keys": ("delegation_enabled", "flash_loan_protected", "governance_token_market_cap_usd", "proposal_threshold_pct", "quorum_pct", "snapshot_based", "total_unique_voters_30d", "voting_period_hours"),
    },
    "protocol_liquidation_history_analyzer": {
        "coverage": 0.5,
        "missing_keys": ("liquidation_penalty_pct", "liquidations_count_30d", "peak_single_day_usd", "total_liquidations_30d_usd"),
    },
    "protocol_oracle_risk_analyzer": {
        "coverage": 0.4,
        "missing_keys": ("deviation_threshold_pct", "has_fallback_oracle", "last_manipulation_incident_days", "protocol_tvl_usd", "staleness_threshold_minutes", "uses_spot_price"),
    },
    "protocol_regulatory_risk_assessor": {
        "coverage": 0.6,
        "missing_keys": ("has_legal_wrapper", "has_received_sec_subpoena", "has_us_user_restriction", "team_is_doxxed"),
    },
    "protocol_security_audit_tracker": {
        "coverage": 0.4,
        "missing_keys": ("audits", "days_since_major_change", "formal_verification"),
    },
    "yield_bearing_stablecoin_comparator": {
        "coverage": 0.2,
        "missing_keys": ("collateral_ratio_pct", "days_since_peg_incident", "liquidity_depth_usd", "peg_deviation_30d_max_pct", "redemption_mechanism", "symbol", "underlying", "yield_source"),
    },
}

UNSOURCED_MODULES: FrozenSet[str] = frozenset(UNSOURCED_DETAIL)

__all__: Tuple[str, ...] = (
    "AUDIT_GENERATED_AT", "MIN_COVERAGE", "UNSOURCED_DETAIL", "UNSOURCED_MODULES",
)
