"""
_protocol_facts.py — детерминированная структурная база фактов по протоколам
whitelisted-universe SPA (Tier-A protocol-context wiring, audit 2026-08-02).

Зачем: дифференциальный аудит показал, что все 12 Tier-A BLOCKING модулей не
дают ни одного протокол-специфичного сигнала — их entrypoint'ы ждут доменные
структуры (positions / oracles / stablecoins), а protocol-контекст агрегатора
(``ctx["protocol"]``) им нечем наполнить. Этот модуль — единый источник
структурных фактов, из которого каждый Tier-A модуль строит СВОИ доменные
входы и прогоняет их через СВОЙ собственный движок (no-fork: движки не
дублируются).

Честная рамка (важно):
* Это КУРИРОВАННЫЕ СТРУКТУРНЫЕ КОНСТАНТЫ (as_of ниже), а не live-телеметрия:
  механизм пега, m-of-n мультисига, timelock, тип выхода, sequencer-модель
  чейна, исторические депеги/инциденты, порядок величины TVL. Они меняются
  редко (governance-события), поэтому пригодны для структурного скоринга;
  live-величины (текущая цена пега, живой TVL) сюда сознательно НЕ входят —
  сеть в 3s-timeout blocking-слое запрещена, а детерминизм обязателен.
* Калибровка: структурные скоры для whitelisted-universe целятся в диапазон
  OK/WARN (<70). BLOCK-пространство (>70) зарезервировано за живыми
  событийными сигналами; постоянное структурное свойство протокола,
  разрешённого RiskPolicy, не должно вечно блокировать его аллокацию.
* Неизвестный протокол → ``facts_for() = None`` → модуль возвращает None →
  громкий статус ``dormant`` в агрегаторе (сигнал НЕ измерен, не "OK").

stdlib-only, детерминированный, LLM FORBIDDEN. Обновление фактов — обычный
code-review (изменение структуры протокола = изменение файла + тест).

AS_OF: 2026-08-02 (структурные факты сверены с публичной документацией
протоколов на дату аудита).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

FACTS_AS_OF = "2026-08-02"
FACTS_SOURCE = "protocol_facts_v1"


def is_protocol_context(obj: Any) -> bool:
    """True, если *obj* — protocol-контекст агрегатора (ADR-031), а не
    легаси-доменная структура: dict со строковым ключом ``protocol``."""
    return isinstance(obj, dict) and isinstance(obj.get("protocol"), str)


# ─── Chain facts (sequencer / canonical bridge) ──────────────────────────────
#
# sequencer: входы DeFiProtocolSequencerDowntimeRiskAnalyzer.
# bridge:    канонический мост чейна — входы TokenBridgeSecurityRiskAnalyzer
#            (None = mainnet-native, bridge-зависимости нет).

CHAIN_FACTS: Dict[str, Dict[str, Any]] = {
    "ethereum": {
        "is_l2": False,
        "sequencer": None,   # нет sequencer'а — L1
        "bridge": None,      # нет канонического моста — родной чейн
    },
    "arbitrum": {
        "is_l2": True,
        "sequencer": {
            "is_single_sequencer": True,
            "has_grace_period": True,           # Aave-style sequencer-uptime grace
            "has_force_inclusion": True,        # delayed inbox через L1
            "force_inclusion_delay_hours": 24.0,
            "uptime_feed_integrated": True,     # Chainlink L2 sequencer feed
            "decentralized_sequencer_roadmap": True,
            "historical_downtime_minutes_30d": 0.0,
            "max_single_outage_minutes": 78.0,  # худший исторический инцидент
        },
        "bridge": {
            "bridge_name": "arbitrum_canonical_rollup_bridge",
            "validation_model": "optimistic",
            "validator_count": 1,
            "days_since_last_audit": 120,
            "historical_hacks": [],
            "open_source": True,
            "bug_bounty_usd": 2_000_000.0,
            "time_to_finality_minutes": 25.0,
        },
    },
    "optimism": {
        "is_l2": True,
        "sequencer": {
            "is_single_sequencer": True,
            "has_grace_period": True,
            "has_force_inclusion": True,
            "force_inclusion_delay_hours": 12.0,
            "uptime_feed_integrated": True,
            "decentralized_sequencer_roadmap": True,
            "historical_downtime_minutes_30d": 0.0,
            "max_single_outage_minutes": 240.0,
        },
        "bridge": {
            "bridge_name": "op_canonical_rollup_bridge",
            "validation_model": "optimistic",
            "validator_count": 1,
            "days_since_last_audit": 150,
            "historical_hacks": [],
            "open_source": True,
            "bug_bounty_usd": 2_000_000.0,
            "time_to_finality_minutes": 25.0,
        },
    },
    "base": {
        "is_l2": True,
        "sequencer": {
            "is_single_sequencer": True,
            "has_grace_period": True,
            "has_force_inclusion": True,
            "force_inclusion_delay_hours": 12.0,
            "uptime_feed_integrated": True,
            "decentralized_sequencer_roadmap": True,
            "historical_downtime_minutes_30d": 0.0,
            "max_single_outage_minutes": 45.0,
        },
        "bridge": {
            "bridge_name": "base_canonical_rollup_bridge",
            "validation_model": "optimistic",
            "validator_count": 1,
            "days_since_last_audit": 150,
            "historical_hacks": [],
            "open_source": True,
            "bug_bounty_usd": 1_000_000.0,
            "time_to_finality_minutes": 25.0,
        },
    },
    "polygon": {
        "is_l2": False,  # PoS sidechain: свой консенсус, sequencer-модели нет
        "sequencer": None,
        "bridge": {
            "bridge_name": "polygon_pos_bridge",
            "validation_model": "multisig",   # PoS validator set + upgradable
            "validator_count": 100,
            "days_since_last_audit": 200,
            "historical_hacks": [],
            "open_source": True,
            "bug_bounty_usd": 1_000_000.0,
            "time_to_finality_minutes": 30.0,
        },
    },
}


# ─── Stable/asset peg profiles (DeFiStablecoinDepegRiskMonitor) ──────────────
#
# Поля — вход monitor(): peg_type, collateral_ratio, historical_max_depeg_pct,
# audit_count, tvl_usd (порядок величины), mint_burn_24h_usd (структурная
# оценка оборота). current_price = 1.0 (структурный скоринг фрагильности
# механизма, НЕ live-мониторинг пега — см. докстринг модуля).

ASSET_PEG_PROFILES: Dict[str, Dict[str, Any]] = {
    "USDC": {"collateral_usage_pct": 70.0, "peg_type": "fiat_backed", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 12.0,  # SVB, 2023-03
             "audit_count": 5, "tvl_usd": 40e9, "mint_burn_24h_usd": 2e9,
             "mint_mechanism": "fiat_reserve"},
    "USDT": {"collateral_usage_pct": 55.0, "peg_type": "fiat_backed", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 5.0,
             "audit_count": 2, "tvl_usd": 110e9, "mint_burn_24h_usd": 3e9,
             "mint_mechanism": "fiat_reserve"},
    "DAI": {"collateral_usage_pct": 40.0, "peg_type": "collateralized", "collateral_ratio": 1.6,
            "historical_max_depeg_pct": 8.0,  # через USDC-долю, 2023-03
            "audit_count": 5, "tvl_usd": 5e9, "mint_burn_24h_usd": 300e6,
            "mint_mechanism": "cdp_overcollateralized"},
    "USDS": {"collateral_usage_pct": 25.0, "peg_type": "collateralized", "collateral_ratio": 1.6,
             "historical_max_depeg_pct": 8.0,  # наследует DAI-историю (Sky)
             "audit_count": 4, "tvl_usd": 6e9, "mint_burn_24h_usd": 300e6,
             "mint_mechanism": "cdp_overcollateralized"},
    "FRAX": {"collateral_usage_pct": 10.0, "peg_type": "collateralized", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 3.0,
             "audit_count": 3, "tvl_usd": 650e6, "mint_burn_24h_usd": 40e6,
             "mint_mechanism": "amo_collateralized"},
    "USDe": {"collateral_usage_pct": 30.0, "peg_type": "crypto_backed", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 4.0,  # basis-обеспечение, funding-хвост
             "audit_count": 4, "tvl_usd": 6e9, "mint_burn_24h_usd": 400e6,
             "mint_mechanism": "delta_hedged_basis"},
    "crvUSD": {"collateral_usage_pct": 8.0, "peg_type": "crypto_backed", "collateral_ratio": 1.8,
               "historical_max_depeg_pct": 2.0,
               "audit_count": 3, "tvl_usd": 150e6, "mint_burn_24h_usd": 20e6,
               "mint_mechanism": "llamma_soft_liquidation"},
    "USDM": {"collateral_usage_pct": 3.0, "peg_type": "fiat_backed", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 1.0,  # rebase T-bill
             "audit_count": 2, "tvl_usd": 60e6, "mint_burn_24h_usd": 5e6,
             "mint_mechanism": "tbill_reserve_rebase"},
    "USD0": {"collateral_usage_pct": 10.0, "peg_type": "collateralized", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 9.0,  # USD0++ floor-repricing, 2025-01
             "audit_count": 3, "tvl_usd": 600e6, "mint_burn_24h_usd": 30e6,
             "mint_mechanism": "rwa_collateral_bond"},
    "USDA": {"collateral_usage_pct": 3.0, "peg_type": "collateralized", "collateral_ratio": 1.1,
             "historical_max_depeg_pct": 2.0,
             "audit_count": 3, "tvl_usd": 50e6, "mint_burn_24h_usd": 5e6,
             "mint_mechanism": "angle_transmuter"},
    # BTC-wrapped: пег к BTC, не к $1 — структурная фрагильность моста/кастоди.
    "tBTC": {"collateral_usage_pct": 10.0, "peg_type": "crypto_backed", "collateral_ratio": 1.0,
             "historical_max_depeg_pct": 1.5,
             "audit_count": 3, "tvl_usd": 550e6, "mint_burn_24h_usd": 10e6,
             "mint_mechanism": "threshold_ecdsa_bridge"},
    "cbBTC": {"collateral_usage_pct": 15.0, "peg_type": "fiat_backed",  # кастодиальный (Coinbase) — как fiat-модель
              "collateral_ratio": 1.0,
              "historical_max_depeg_pct": 0.5,
              "audit_count": 2, "tvl_usd": 2.5e9, "mint_burn_24h_usd": 50e6,
              "mint_mechanism": "custodial_wrap"},
}


# ─── Per-kind defaults ───────────────────────────────────────────────────────
#
# База по типу протокола; каждый протокол ниже переопределяет только своё.
# Все числа — структурные порядки величины (см. шапку модуля).

_KIND_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "lending": {
        "utilization_pct": 60.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 55.0, "market_stress_score": 20,
        "exit": {"exit_type": "instant_withdraw", "lock_remaining_days": 0.0,
                 "withdrawal_queue_usd": 0.0, "slippage_model": "linear",
                 "withdrawal_fee_pct": 0.0},
        "withdrawal": {"withdrawal_type": "instant", "queue_wait_hours": 0.0,
                       "queue_size_usd": 0.0, "daily_exit_capacity_usd": 0.0,
                       "price_impact_risk_pct": 0.1},
        # cascade = профиль ТИПИЧНОГО ЗАЁМЩИКА пула (каскадный риск для
        # депозитора приходит от заёмщиков): средний LTV пула ~0.35,
        # волатильный collateral-микс (ETH+stables) ~35%.
        "cascade": {"debt_to_collateral": 0.35,
                    "liquidation_threshold_pct": 80.0,
                    "collateral_volatility_pct": 35.0,
                    "collateral_correlation_to_debt": 0.1},
        "bad_debt": {"bad_debt_ratio_pct": 0.02, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 8.0, "failed_liq_pct": 0.0,
                     "largest_underwater_pct_of_borrowed": 0.1},
        "systemic": {"interconnection_score": 60.0, "debt_ratio": 0.6,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 45.0,
                     "insurance_pct_of_tvl": 0.5},
    },
    "vault": {  # агрегаторы/savings-обёртки (yearn, sdai, susds, scrvusd…)
        "utilization_pct": 0.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 90.0, "market_stress_score": 20,
        "exit": {"exit_type": "instant_withdraw", "lock_remaining_days": 0.0,
                 "withdrawal_queue_usd": 0.0, "slippage_model": "linear",
                 "withdrawal_fee_pct": 0.0},
        "withdrawal": {"withdrawal_type": "instant", "queue_wait_hours": 0.0,
                       "queue_size_usd": 0.0, "daily_exit_capacity_usd": 0.0,
                       "price_impact_risk_pct": 0.1},
        "cascade": {"debt_to_collateral": 0.0,
                    "liquidation_threshold_pct": 100.0,
                    "collateral_volatility_pct": 1.0,
                    "collateral_correlation_to_debt": 0.95},
        "bad_debt": {"bad_debt_ratio_pct": 0.0, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 9999.0, "failed_liq_pct": 0.0,
                     "largest_underwater_pct_of_borrowed": 0.0},
        "systemic": {"interconnection_score": 45.0, "debt_ratio": 0.0,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 55.0,
                     "insurance_pct_of_tvl": 0.0},
    },
    "rwa_credit": {  # permissioned private credit (maple)
        "utilization_pct": 85.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 30.0, "market_stress_score": 30,
        "exit": {"exit_type": "vesting_unlock", "lock_remaining_days": 14.0,
                 "withdrawal_queue_usd": 15e6, "slippage_model": "constant",
                 "withdrawal_fee_pct": 0.0},
        "withdrawal": {"withdrawal_type": "queued", "queue_wait_hours": 48.0,
                       "queue_size_usd": 8e6, "daily_exit_capacity_usd": 8e6,
                       "price_impact_risk_pct": 0.3},
        "cascade": {"debt_to_collateral": 0.0,
                    "liquidation_threshold_pct": 100.0,
                    "collateral_volatility_pct": 4.0,
                    "collateral_correlation_to_debt": 0.5},
        "bad_debt": {"bad_debt_ratio_pct": 0.3, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 2.5, "failed_liq_pct": 2.0,
                     "largest_underwater_pct_of_borrowed": 1.0},
        "systemic": {"interconnection_score": 25.0, "debt_ratio": 0.85,
                     "historical_contagion_events": 1,  # 2022 кредитные дефолты
                     "liquidity_in_crisis_pct": 80.0,
                     "insurance_pct_of_tvl": 1.0},
    },
    "fixed_yield": {  # pendle PT/YT
        "utilization_pct": 0.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 70.0, "market_stress_score": 25,
        "exit": {"exit_type": "pool_exit", "lock_remaining_days": 0.0,
                 "withdrawal_queue_usd": 0.0, "slippage_model": "sqrt",
                 "withdrawal_fee_pct": 0.1},
        "withdrawal": {"withdrawal_type": "instant", "queue_wait_hours": 0.0,
                       "queue_size_usd": 0.0, "daily_exit_capacity_usd": 0.0,
                       "price_impact_risk_pct": 1.0},
        "cascade": {"debt_to_collateral": 0.0,
                    "liquidation_threshold_pct": 100.0,
                    "collateral_volatility_pct": 5.0,
                    "collateral_correlation_to_debt": 0.8},
        "bad_debt": {"bad_debt_ratio_pct": 0.0, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 9999.0, "failed_liq_pct": 0.0,
                     "largest_underwater_pct_of_borrowed": 0.0},
        "systemic": {"interconnection_score": 50.0, "debt_ratio": 0.0,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 70.0,
                     "insurance_pct_of_tvl": 0.0},
    },
    "lp_amm": {  # стейбл-LP (aerodrome/velodrome)
        "utilization_pct": 0.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 95.0, "market_stress_score": 25,
        "exit": {"exit_type": "pool_exit", "lock_remaining_days": 0.0,
                 "withdrawal_queue_usd": 0.0, "slippage_model": "sqrt",
                 "withdrawal_fee_pct": 0.05},
        "withdrawal": {"withdrawal_type": "instant", "queue_wait_hours": 0.0,
                       "queue_size_usd": 0.0, "daily_exit_capacity_usd": 0.0,
                       "price_impact_risk_pct": 0.5},
        "cascade": {"debt_to_collateral": 0.0,
                    "liquidation_threshold_pct": 100.0,
                    "collateral_volatility_pct": 2.0,
                    "collateral_correlation_to_debt": 0.95},
        "bad_debt": {"bad_debt_ratio_pct": 0.0, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 9999.0, "failed_liq_pct": 0.0,
                     "largest_underwater_pct_of_borrowed": 0.0},
        "systemic": {"interconnection_score": 35.0, "debt_ratio": 0.0,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 60.0,
                     "insurance_pct_of_tvl": 0.0},
    },
    "synthetic_dollar": {  # ethena-стек
        "utilization_pct": 0.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 20.0, "market_stress_score": 35,
        "exit": {"exit_type": "instant_withdraw", "lock_remaining_days": 7.0,
                 "withdrawal_queue_usd": 20e6, "slippage_model": "linear",
                 "withdrawal_fee_pct": 0.0},
        "withdrawal": {"withdrawal_type": "unbonding",
                       "queue_wait_hours": 36.0, "queue_size_usd": 10e6,
                       "daily_exit_capacity_usd": 20e6,
                       "price_impact_risk_pct": 0.5},
        "cascade": {"debt_to_collateral": 0.0,
                    "liquidation_threshold_pct": 100.0,
                    "collateral_volatility_pct": 8.0,
                    "collateral_correlation_to_debt": 0.6},
        "bad_debt": {"bad_debt_ratio_pct": 0.0, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 9999.0, "failed_liq_pct": 0.0,
                     "largest_underwater_pct_of_borrowed": 0.0},
        "systemic": {"interconnection_score": 65.0, "debt_ratio": 0.0,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 65.0,
                     "insurance_pct_of_tvl": 1.0},
    },
    "leverage_farm": {  # T3 leveraged farming (extra_finance)
        "utilization_pct": 70.0, "tvl_trend_7d_pct": 0.0,
        "stablecoin_collateral_pct": 50.0, "market_stress_score": 40,
        "exit": {"exit_type": "pool_exit", "lock_remaining_days": 0.0,
                 "withdrawal_queue_usd": 0.0, "slippage_model": "sqrt",
                 "withdrawal_fee_pct": 0.1},
        "withdrawal": {"withdrawal_type": "instant", "queue_wait_hours": 0.0,
                       "queue_size_usd": 0.0, "daily_exit_capacity_usd": 0.0,
                       "price_impact_risk_pct": 1.5},
        "cascade": {"debt_to_collateral": 0.65,  # leverage — реальный долг
                    "liquidation_threshold_pct": 80.0,
                    "collateral_volatility_pct": 45.0,
                    "collateral_correlation_to_debt": 0.3},
        "bad_debt": {"bad_debt_ratio_pct": 0.2, "trend_pct_30d": 0.0,
                     "reserve_coverage_x": 1.5, "failed_liq_pct": 3.0,
                     "largest_underwater_pct_of_borrowed": 2.0},
        "systemic": {"interconnection_score": 30.0, "debt_ratio": 0.7,
                     "historical_contagion_events": 0,
                     "liquidity_in_crisis_pct": 75.0,
                     "insurance_pct_of_tvl": 0.0},
    },
}

# Oracle-профили (вход DeFiOracleManipulationRiskScorer).
_ORACLE_PROFILES: Dict[str, Dict[str, Any]] = {
    "chainlink_major": {
        "oracle_type": "chainlink", "num_price_sources": 16,
        "liquidity_of_underlying_usd": 800e6, "twap_window_seconds": 0.0,
        "heartbeat_seconds": 3600.0, "last_update_seconds_ago": 0.0,
        "manipulation_incidents_count": 0, "has_circuit_breaker": True,
        "audited": True,
    },
    "chainlink_mid": {
        "oracle_type": "chainlink", "num_price_sources": 8,
        "liquidity_of_underlying_usd": 120e6, "twap_window_seconds": 0.0,
        "heartbeat_seconds": 3600.0, "last_update_seconds_ago": 0.0,
        "manipulation_incidents_count": 0, "has_circuit_breaker": True,
        "audited": True,
    },
    "exchange_rate_internal": {  # обменный курс контракта (sDAI, sUSDS…)
        "oracle_type": "internal_rate", "num_price_sources": 1,
        "liquidity_of_underlying_usd": 400e6, "twap_window_seconds": 0.0,
        "heartbeat_seconds": 3600.0, "last_update_seconds_ago": 0.0,
        "manipulation_incidents_count": 0, "has_circuit_breaker": False,
        "audited": True,
    },
    "amm_twap": {
        "oracle_type": "uniswap_twap", "num_price_sources": 2,
        "liquidity_of_underlying_usd": 40e6, "twap_window_seconds": 1800.0,
        "heartbeat_seconds": 3600.0, "last_update_seconds_ago": 0.0,
        "manipulation_incidents_count": 0, "has_circuit_breaker": False,
        "audited": True,
    },
    "custom_small": {
        "oracle_type": "custom", "num_price_sources": 2,
        "liquidity_of_underlying_usd": 15e6, "twap_window_seconds": 0.0,
        "heartbeat_seconds": 3600.0, "last_update_seconds_ago": 0.0,
        "manipulation_incidents_count": 0, "has_circuit_breaker": False,
        "audited": True,
    },
}

# Admin-профили (вход DeFiProtocolAdminKeyControlRiskAnalyzer).
_ADMIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "dao_timelock_strong": {  # полноценный governance + длинный timelock
        "multisig_threshold": 6, "multisig_signers": 9,
        "timelock_hours": 48.0, "upgradeable": True, "pausable": True,
        "has_guardian": True, "admin_controlled_tvl_pct": 25.0,
        "signer_independence_pct": 85.0,
    },
    "dao_timelock_mid": {
        "multisig_threshold": 4, "multisig_signers": 7,
        "timelock_hours": 24.0, "upgradeable": True, "pausable": True,
        "has_guardian": True, "admin_controlled_tvl_pct": 45.0,
        "signer_independence_pct": 70.0,
    },
    "team_multisig": {
        "multisig_threshold": 3, "multisig_signers": 5,
        "timelock_hours": 12.0, "upgradeable": True, "pausable": True,
        "has_guardian": False, "admin_controlled_tvl_pct": 70.0,
        "signer_independence_pct": 50.0,
    },
    "immutable_minimal": {  # неапгрейдируемое ядро (morpho blue, llamma)
        "multisig_threshold": 5, "multisig_signers": 9,
        "timelock_hours": 24.0, "upgradeable": False, "pausable": False,
        "has_guardian": True, "admin_controlled_tvl_pct": 10.0,
        "signer_independence_pct": 80.0,
    },
    "custodial": {  # централизованный кастодиан (cbBTC-модель)
        "multisig_threshold": 2, "multisig_signers": 3,
        "timelock_hours": 0.0, "upgradeable": True, "pausable": True,
        "has_guardian": False, "admin_controlled_tvl_pct": 100.0,
        "signer_independence_pct": 20.0,
    },
}


# ─── Protocol table ──────────────────────────────────────────────────────────
#
# Каждая запись: kind, chain, tier, tvl_usd (порядок величины), assets
# (пег-профили из ASSET_PEG_PROFILES), oracle/admin (профили выше),
# liquidity (exit-глубина), overrides (точечные структурные отличия).

def _p(kind: str, chain: str, tier: str, tvl_usd: float,
       assets: List[str], oracle: str, admin: str,
       exit_liquidity_usd: float, daily_volume_usd: float,
       asset_type: str = "stablecoin",
       overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "kind": kind, "chain": chain, "tier": tier, "tvl_usd": tvl_usd,
        "assets": assets, "oracle_profile": oracle, "admin_profile": admin,
        "exit_liquidity_usd": exit_liquidity_usd,
        "daily_volume_usd": daily_volume_usd,
        "asset_type": asset_type,
        "overrides": overrides or {},
    }


PROTOCOL_TABLE: Dict[str, Dict[str, Any]] = {
    # ── Aave family ──
    "aave_v3": _p("lending", "ethereum", "T1", 25e9, ["USDC", "USDT", "DAI"],
                  "chainlink_major", "dao_timelock_strong", 2e9, 500e6,
                  overrides={"systemic": {"interconnection_score": 85.0,
                                          "insurance_pct_of_tvl": 1.5}}),
    "aave_arbitrum": _p("lending", "arbitrum", "T1", 2.5e9, ["USDC", "USDT"],
                        "chainlink_major", "dao_timelock_strong", 300e6, 80e6,
                        overrides={"systemic": {"interconnection_score": 70.0}}),
    "aave_v3_optimism": _p("lending", "optimism", "T1", 500e6, ["USDC", "USDT"],
                           "chainlink_major", "dao_timelock_strong", 80e6, 20e6),
    "aave_v3_polygon": _p("lending", "polygon", "T1", 600e6, ["USDC", "USDT"],
                          "chainlink_major", "dao_timelock_strong", 90e6, 25e6),
    "aave_v3_base": _p("lending", "base", "T2", 800e6, ["USDC"],
                       "chainlink_major", "dao_timelock_strong", 120e6, 30e6),
    # ── Blue-chip lending ──
    "compound_v3": _p("lending", "ethereum", "T1", 2.5e9, ["USDC", "USDT"],
                      "chainlink_major", "dao_timelock_strong", 400e6, 60e6,
                      overrides={"systemic": {"interconnection_score": 70.0}}),
    "morpho_blue": _p("lending", "ethereum", "T2", 4e9, ["USDC", "DAI"],
                      "chainlink_mid", "immutable_minimal", 500e6, 60e6,
                      overrides={"systemic": {"interconnection_score": 55.0}}),
    "morpho_blue_base": _p("lending", "base", "T2", 1.5e9, ["USDC"],
                           "chainlink_mid", "immutable_minimal", 200e6, 25e6),
    "euler_v2": _p("lending", "ethereum", "T2", 1e9, ["USDC", "USDT"],
                   "chainlink_mid", "dao_timelock_mid", 150e6, 20e6,
                   overrides={
                       # эксплойт 2023 (Euler v1) — исторический инцидент линии
                       "systemic": {"historical_contagion_events": 1},
                       "oracle": {"manipulation_incidents_count": 0}}),
    "fluid_usdc": _p("lending", "ethereum", "T2", 1.2e9, ["USDC"],
                     "chainlink_mid", "team_multisig", 200e6, 40e6,
                     overrides={"utilization_pct": 80.0}),
    "fluid_fusdc": _p("lending", "ethereum", "T2", 1.2e9, ["USDC"],
                      "chainlink_mid", "team_multisig", 200e6, 40e6,
                      overrides={"utilization_pct": 80.0}),
    "fluid_arbitrum": _p("lending", "arbitrum", "T2", 300e6, ["USDC"],
                         "chainlink_mid", "team_multisig", 50e6, 10e6,
                         overrides={"utilization_pct": 80.0}),
    "moonwell_base": _p("lending", "base", "T2", 250e6, ["USDC"],
                        "chainlink_mid", "dao_timelock_mid", 40e6, 8e6),
    "dolomite_arbitrum": _p("lending", "arbitrum", "T2", 120e6, ["USDC", "USDT"],
                            "chainlink_mid", "team_multisig", 20e6, 5e6),
    "silo_arbitrum": _p("lending", "arbitrum", "T2", 150e6, ["USDC"],
                        "chainlink_mid", "team_multisig", 25e6, 5e6),
    # ── Savings / vault wrappers ──
    "yearn_v3": _p("vault", "ethereum", "T2", 350e6, ["USDC", "DAI"],
                   "exchange_rate_internal", "dao_timelock_mid", 60e6, 10e6),
    "sdai": _p("vault", "ethereum", "T2", 1.5e9, ["DAI"],
               "exchange_rate_internal", "dao_timelock_strong", 400e6, 50e6),
    "spark_susds": _p("vault", "ethereum", "T1", 3e9, ["USDS"],
                      "exchange_rate_internal", "dao_timelock_strong", 500e6, 60e6),
    "scrvusd": _p("vault", "ethereum", "T2", 80e6, ["crvUSD"],
                  "exchange_rate_internal", "dao_timelock_mid", 20e6, 4e6),
    "sfrax": _p("vault", "ethereum", "T2", 60e6, ["FRAX"],
                "exchange_rate_internal", "dao_timelock_mid", 15e6, 3e6),
    "frax": _p("vault", "ethereum", "T2", 650e6, ["FRAX"],
               "chainlink_mid", "dao_timelock_mid", 60e6, 15e6),
    "wusdm": _p("vault", "ethereum", "T2", 60e6, ["USDM"],
                "exchange_rate_internal", "team_multisig", 12e6, 2e6),
    "stusd": _p("vault", "ethereum", "T2", 40e6, ["USDA"],
                "exchange_rate_internal", "dao_timelock_mid", 10e6, 2e6),
    "usual_usd0pp": _p("vault", "ethereum", "T2", 500e6, ["USD0"],
                       "amm_twap", "team_multisig", 30e6, 8e6,
                       overrides={
                           # USD0++ = 4y-бонд с floor-выкупом: выход = продажа
                           # в пул / floor-redeem ниже номинала (2025-01 event)
                           "exit": {"exit_type": "bond_redemption",
                                    "withdrawal_fee_pct": 0.5},
                           "withdrawal": {"withdrawal_type": "queued",
                                          "queue_wait_hours": 12.0,
                                          "queue_size_usd": 5e6,
                                          "daily_exit_capacity_usd": 5e6,
                                          "price_impact_risk_pct": 2.0},
                           "systemic": {"historical_contagion_events": 1}}),
    # ── RWA credit ──
    "maple": _p("rwa_credit", "ethereum", "T2", 2.5e9, ["USDC"],
                "chainlink_mid", "team_multisig", 40e6, 5e6),
    # ── Fixed yield (Pendle) ──
    "pendle": _p("fixed_yield", "ethereum", "T2", 4e9, ["USDe", "USDC"],
                 "amm_twap", "dao_timelock_mid", 150e6, 40e6,
                 overrides={"systemic": {"interconnection_score": 60.0}}),
    "pendle_pt_susde": _p("fixed_yield", "ethereum", "T2", 800e6, ["USDe"],
                          "amm_twap", "dao_timelock_mid", 60e6, 15e6,
                          overrides={
                              "cascade": {"collateral_volatility_pct": 8.0}}),
    "pendle_pt_usdc": _p("fixed_yield", "ethereum", "T2", 300e6, ["USDC"],
                         "amm_twap", "dao_timelock_mid", 30e6, 8e6),
    # ── Synthetic dollar (Ethena) ──
    "ethena_susde": _p("synthetic_dollar", "ethereum", "T2", 5e9, ["USDe"],
                       "chainlink_mid", "team_multisig", 250e6, 80e6),
    "susde": _p("synthetic_dollar", "ethereum", "T3", 5e9, ["USDe"],
                "chainlink_mid", "team_multisig", 250e6, 80e6),
    # ── LP AMM ──
    "aerodrome_base": _p("lp_amm", "base", "T2", 900e6, ["USDC"],
                         "amm_twap", "team_multisig", 80e6, 60e6),
    "velodrome_optimism": _p("lp_amm", "optimism", "T2", 150e6, ["USDC"],
                             "amm_twap", "team_multisig", 25e6, 15e6),
    # ── Leverage farming (T3) ──
    "extra_finance_base": _p("leverage_farm", "base", "T3", 40e6, ["USDC"],
                             "custom_small", "team_multisig", 6e6, 1.5e6),
    # ── BTC lending (advisory) ──
    "tbtc_lending": _p("lending", "ethereum", "T2", 550e6, ["tBTC"],
                       "chainlink_mid", "dao_timelock_mid", 40e6, 8e6,
                       asset_type="wrapped",
                       overrides={
                           "cascade": {"collateral_volatility_pct": 45.0,
                                       "collateral_correlation_to_debt": 0.2},
                           "bridge_profile": {
                               "bridge_name": "threshold_tbtc_bridge",
                               "validation_model": "multisig",
                               "validator_count": 51,
                               "days_since_last_audit": 180,
                               "historical_hacks": [],
                               "open_source": True,
                               "bug_bounty_usd": 500_000.0,
                               "time_to_finality_minutes": 60.0}}),
    "cbbtc_lending": _p("lending", "ethereum", "T2", 2.5e9, ["cbBTC"],
                        "chainlink_major", "custodial", 150e6, 30e6,
                        asset_type="wrapped",
                        overrides={
                            "cascade": {"collateral_volatility_pct": 45.0,
                                        "collateral_correlation_to_debt": 0.2},
                            "bridge_profile": {
                                "bridge_name": "coinbase_cbbtc_custody",
                                "validation_model": "custodial",
                                "validator_count": 1,
                                "days_since_last_audit": 120,
                                "historical_hacks": [],
                                "open_source": False,
                                "bug_bounty_usd": 1_000_000.0,
                                "time_to_finality_minutes": 10.0}}),
}

# Алиасы: имена, встречающиеся в аллокаторе/статусах, → каноническое имя.
PROTOCOL_ALIASES: Dict[str, str] = {
    "aave_v3_eth": "aave_v3",
    "aave_v3_arbitrum": "aave_arbitrum",
    "aave_v3_arb": "aave_arbitrum",
    "aave_optimism": "aave_v3_optimism",
    "aave_polygon": "aave_v3_polygon",
    "aave_base": "aave_v3_base",
    "spark": "spark_susds",
    "sky_susds": "spark_susds",
    "morpho": "morpho_blue",
    "morpho_steakhouse": "morpho_blue",
    "fluid": "fluid_usdc",
    "aerodrome": "aerodrome_base",
    "velodrome": "velodrome_optimism",
    "ethena": "ethena_susde",
    "ondo_usdy": "wusdm",  # ближайший структурный аналог: tokenized T-bill wrapper
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def known_protocols() -> List[str]:
    """Отсортированный список канонических имён протоколов в базе."""
    return sorted(PROTOCOL_TABLE)


def facts_for(protocol: str) -> Optional[Dict[str, Any]]:
    """Собрать полный структурный факт-профиль протокола (или None).

    Возвращаемый dict (все значения — deep-копии, мутировать безопасно):
      name, kind, chain, tier, tvl_usd, asset_type,
      utilization_pct, tvl_trend_7d_pct, stablecoin_collateral_pct,
      market_stress_score, exit{...}, withdrawal{...}, cascade{...},
      bad_debt{...}, systemic{...},
      exit_liquidity_usd, daily_volume_usd,
      assets [имена], asset_profiles [пег-профили ASSET_PEG_PROFILES],
      oracle {...}, admin {...},
      sequencer {...}|None, bridge {...}|None,
      facts_as_of, facts_source.

    None → протокол вне базы: вызывающий модуль обязан вернуть None
    (сигнал НЕ измерен → громкий ``dormant`` в агрегаторе), а не выдумывать.
    """
    if not isinstance(protocol, str) or not protocol:
        return None
    key = protocol.strip().lower()
    key = PROTOCOL_ALIASES.get(key, key)
    entry = PROTOCOL_TABLE.get(key)
    if entry is None:
        return None

    kind_defaults = copy.deepcopy(_KIND_DEFAULTS[entry["kind"]])
    overrides = entry.get("overrides", {})
    merged = _deep_merge(kind_defaults, {
        k: v for k, v in overrides.items() if k != "bridge_profile"
    })

    chain = CHAIN_FACTS.get(entry["chain"], CHAIN_FACTS["ethereum"])
    bridge = overrides.get("bridge_profile") or chain.get("bridge")

    asset_profiles = []
    for a in entry["assets"]:
        prof = ASSET_PEG_PROFILES.get(a)
        if prof is not None:
            p = copy.deepcopy(prof)
            p["name"] = a
            asset_profiles.append(p)

    oracle = copy.deepcopy(_ORACLE_PROFILES[entry["oracle_profile"]])
    oracle = _deep_merge(oracle, merged.pop("oracle", {}))
    admin = copy.deepcopy(_ADMIN_PROFILES[entry["admin_profile"]])
    admin = _deep_merge(admin, merged.pop("admin", {}))

    facts: Dict[str, Any] = {
        "name": key,
        "kind": entry["kind"],
        "chain": entry["chain"],
        "tier": entry["tier"],
        "tvl_usd": float(entry["tvl_usd"]),
        "asset_type": entry.get("asset_type", "stablecoin"),
        "exit_liquidity_usd": float(entry["exit_liquidity_usd"]),
        "daily_volume_usd": float(entry["daily_volume_usd"]),
        "assets": list(entry["assets"]),
        "asset_profiles": asset_profiles,
        "oracle": oracle,
        "admin": admin,
        "sequencer": copy.deepcopy(chain.get("sequencer")),
        "bridge": copy.deepcopy(bridge),
        "facts_as_of": FACTS_AS_OF,
        "facts_source": FACTS_SOURCE,
    }
    facts.update(merged)
    return facts


# ─── Generic per-protocol profile (Tier-B mass wiring) ───────────────────────

# Структурная базовая доходность по (kind, tier) — порядок величины, НЕ live.
_KIND_BASE_APY: Dict[str, float] = {
    "lending": 4.5, "vault": 4.0, "rwa_credit": 8.5, "fixed_yield": 7.0,
    "lp_amm": 6.0, "synthetic_dollar": 9.0, "leverage_farm": 12.0,
}
_TIER_APY_BUMP: Dict[str, float] = {"T1": 0.0, "T2": 1.0, "T3": 2.5}
_CHAIN_GAS_USD: Dict[str, float] = {
    "ethereum": 8.0, "arbitrum": 0.15, "optimism": 0.1,
    "base": 0.05, "polygon": 0.02,
}


def generic_profile_for(protocol: str) -> Optional[Dict[str, Any]]:
    """Плоский протокол-профиль: суперсет полей, которые массово читают
    Tier-B движки (`.get("tvl_usd")`, `.get("apy_pct")`, …), выведенный
    детерминированно из структурной базы — значения РАЗЛИЧАЮТСЯ между
    протоколами (kind/tier/chain/admin/exit), иначе массовая проводка
    контекста дала бы новую протокол-слепую константу.

    None → протокол вне базы (вызывающий модуль возвращает None → dormant).
    """
    facts = facts_for(protocol)
    if facts is None:
        return None
    apy = _KIND_BASE_APY.get(facts["kind"], 5.0) + _TIER_APY_BUMP.get(
        facts["tier"], 1.0)
    if facts["asset_type"] == "wrapped":  # BTC-lending: честный ~0-1% APY
        apy = 0.8
    tvl = facts["tvl_usd"]
    util = float(facts["utilization_pct"])
    cas = facts["cascade"]
    ex = facts["exit"]
    admin = facts["admin"]
    size = 25_000.0
    asset = (facts["assets"] or ["USDC"])[0]
    is_rwa = facts["kind"] == "rwa_credit"
    profile: Dict[str, Any] = {
        # идентичность
        "name": facts["name"], "protocol": facts["name"],
        "chain": facts["chain"], "asset": asset,
        "pair": f"{asset}/USDC", "token_type": "governance",
        # размер / TVL / потоки
        "tvl_usd": tvl, "total_tvl_usd": tvl, "total_supply_usd": tvl,
        "total_borrow_usd": tvl * util / 100.0,
        "utilization_rate_pct": util,
        "volume_24h_usd": facts["daily_volume_usd"],
        "min_tvl_usd": 5_000_000.0,
        # доходность (структурные порядки величины)
        "apy": apy, "apy_pct": apy, "gross_apy_pct": apy,
        "current_apy_pct": apy, "apy_current": apy,
        "initial_apy_pct": apy, "apy_7d_ago": apy,
        "basis_spread_pp": 2.0 if facts["kind"] == "synthetic_dollar" else 0.2,
        "il_change_pct": 0.0,
        # позиция (репрезентативная paper-аллокация)
        "capital_usd": size, "position_value_usd": size,
        "allocation_usd": size, "value_usd": size,
        "collateral_usd": size,
        "debt_usd": size * float(cas["debt_to_collateral"]),
        "liquidation_threshold_pct": cas["liquidation_threshold_pct"],
        "liquidation_threshold": cas["liquidation_threshold_pct"] / 100.0,
        "holding_days": 30, "holding_period_days": 30,
        "date_days_from_now": 30,
        # издержки
        "gas_cost_usd": _CHAIN_GAS_USD.get(facts["chain"], 5.0),
        "bridge_cost_usd": 0.0 if facts["chain"] == "ethereum" else 5.0,
        "fee_pct": ex["withdrawal_fee_pct"],
        "withdrawal_fee_pct": ex["withdrawal_fee_pct"],
        "performance_fee_pct": 10.0 if facts["kind"] == "vault" else 0.0,
        "management_fee_pct": 1.0 if facts["kind"] == "vault" else 0.0,
        # governance / централизация / комплаенс
        "oracle_type": facts["oracle"]["oracle_type"],
        "timelock_hours": admin["timelock_hours"],
        "multisig_required": admin["multisig_threshold"] > 1,
        "bug_bounty_usd": 1_000_000.0 if facts["tier"] == "T1" else 250_000.0,
        "centralized_components": (
            2 if admin["admin_controlled_tvl_pct"] >= 70 else 1),
        "has_kyc": is_rwa, "has_aml": is_rwa,
        "jurisdiction": "US" if is_rwa else "decentralized",
        "token_classified_security": False,
        "uses_private_mempool": False,
        # резервы / redemption (структурно)
        "issuer_reserves_audited": True,
        "redemption_suspended": False,
        "liquid_reserve_pct": 15.0 if is_rwa else 80.0,
        "stress_redemption_pct": 25.0,
        "illiquid_asset_pct": 70.0 if is_rwa else 5.0,
        "historical_bad_debt_usd":
            tvl * util / 100.0
            * float(facts["bad_debt"]["bad_debt_ratio_pct"]) / 100.0,
        # governance-участие (protocol_governance_health_scorer и родня)
        "voter_participation_pct": (
            25.0 if admin["signer_independence_pct"] >= 70 else 8.0),
        "proposals_last_90d": (
            12 if admin["signer_independence_pct"] >= 70 else 3),
        "has_timelock": admin["timelock_hours"] > 0,
        "community_forum_active": admin["signer_independence_pct"] >= 50,
        "top10_holder_pct": 100.0 - admin["signer_independence_pct"],
        "governance_token_circulating_pct": admin["signer_independence_pct"],
        # provenance
        "facts_source": facts["facts_source"],
        "facts_as_of": facts["facts_as_of"],
    }
    return profile


# Приоритетные контейнеры, в которых Tier-B движки прячут скоры своих
# агрегатов (детерминированный порядок обхода).
_SCORE_CONTAINERS = (
    "aggregates", "summary", "portfolio", "totals", "overall",
    "results", "positions", "protocols", "pools", "markets", "items",
    "details", "analyzed", "analyzed_positions", "entries", "opportunities",
)


def extract_protocol_score(result: Any,
                           profile: Optional[Dict[str, Any]] = None
                           ) -> Optional[Dict[str, Any]]:
    """Свести разнородный выход Tier-B движка к ``{"risk_score": 0-100}``.

    Используется ТОЛЬКО контекст-ветками массовой Tier-B проводки (audit
    2026-08-02): движок прогнан на одном протокол-профиле, его агрегат
    часто прячет score во вложенном контейнере (``aggregates`` /
    ``results[0]`` / …), который top-level коэрция агрегатора не видит.
    Детерминированный обход (приоритетные контейнеры, глубина ≤ 3) через
    ТУ ЖЕ ``_ModuleAdapter._coerce_score`` — семантика ключей не форкается.
    Ничего не нашли → None (dormant, не фабрикация).
    """
    from spa_core.analytics.signal_aggregator import _ModuleAdapter
    coerce = _ModuleAdapter._coerce_score

    def _find(obj: Any, depth: int) -> Optional[float]:
        # Коэрсим ТОЛЬКО dict-контейнеры: голое число произвольного ключа
        # (TVL, APY, timestamp…) score'ом не является — именно этот класс
        # ложной коэрции audit 2026-08-02 убрал из агрегатора (generic
        # "value"), не реинтродуцируем его обходом.
        if isinstance(obj, dict):
            score = coerce(obj)
            if score is not None:
                return score
            if depth <= 0:
                return None
            keys = [k for k in _SCORE_CONTAINERS if k in obj]
            keys += [k for k in sorted(obj) if k not in keys]
            for k in keys:
                v = obj[k]
                if isinstance(v, (dict, list, tuple)):
                    found = _find(v, depth - 1)
                    if found is not None:
                        return found
        elif isinstance(obj, (list, tuple)) and obj and depth > 0:
            return _find(obj[0], depth - 1)
        return None

    score = _find(result, 3)
    if score is None:
        return None
    out = {
        "risk_score": max(0.0, min(100.0, float(score))),
        "facts_source": FACTS_SOURCE,
        "facts_as_of": FACTS_AS_OF,
    }
    if profile is not None:
        out["protocol"] = profile.get("name")
    return out
