# План переселения 55 модулей из реестра риск-сигналов (own-27, решение владельца 2026-08-04)

Решение владельца: «если их создавали — они нужны, просто возможно не там, где сейчас».
Все 55 записей удалены из Tier-B реестра сигнального слоя (они не могут ответить на вопрос
«какой риск у протокола X» по своей природе). Файлы и тесты НЕ тронуты. Польза сохраняется
переселением по назначению — три рабочих потока (карточки agent-relocate-*):

## Поток 1 → советники аллокатора (Head-of-Investment, ADR-055) — 13 модулей
`defi_cross_protocol_yield_optimizer`, `defi_gas_optimization_advisor`, `gas_optimization_engine`,
`protocol_defi_gas_cost_optimizer`, `defi_liquidity_mining_roi_calculator`,
`defi_protocol_fee_tier_optimizer`, `defi_protocol_leverage_adjusted_apy_calculator`,
`defi_protocol_yield_harvesting_frequency_optimizer`, `protocol_defi_position_size_optimizer`,
`protocol_defi_stable_yield_optimizer`, `yield_reinvestment_optimizer`, `yield_timing_optimizer`,
`fee_calculator`.
**Куда:** advisory-вход в `data/allocation_rationale.json` (shadow-триггер ребаланса уже пишет его
каждый цикл) — «что можно улучшить и почём», строго advisory, капитал не двигают (инвариант:
advisory никогда не гейтит).

## Поток 2 → слой отчётности — 9 модулей
`adapter_health_scorecard`, `chain_fee_tracker`, `governance_token_value_tracker`,
`lp_position_tracker`, `portfolio_stats`, `portfolio_volatility_tracker`,
`defi_protocol_market_share_tracker`, `staking_reward_tracker`, `yield_attribution_tracker`.
**Куда:** секции пост-циклового `analytics_runner` (MP-104) / дневного дайджеста — «что произошло»,
не риск-сигнал.

## Поток 3 → линия рыночных данных (время-ряды) — 18 модулей
`apy_forecaster`, `apy_momentum`, `defi_borrow_rate_forecaster`, `cross_chain_yield_comparator`,
`defi_liquid_staking_rate_comparator`, `defi_risk_adjusted_yield_comparator`,
`protocol_defi_cross_chain_yield_normalizer`, `protocol_defi_cross_protocol_yield_arbitrage_scanner`,
`protocol_defi_depeg_contagion_modeler`, `defi_protocol_real_yield_sustainability_rater`,
`defi_yield_sustainability_rater`, `protocol_defi_yield_source_sustainability_ranker`,
`chain_concentration`, `liquidity_scorer`, `protocol_liquidity_depth_stress_tester`, `risk_budget`,
`defi_nft_collateral_valuation_model`, `defi_vault_strategy_risk_decomposer`.
**Куда:** отдельная линия с фидом живых APY-рядов из `data/historical_apy*` /
`dashboard_metrics_history.json` (ВНИМАНИЕ: оси дат файлов не совпадают — выравнивать по дате,
не по индексу). Это же разблокирует часть из 140 «честно непроводимых» Tier-B и 38
dormant-by-design (та же причина: нужны ряды).

## Не переселяются (реестровый шум) — 15 записей
14 записей указывали на @dataclass-контейнеры (`CorrelationPair`, `AdapterSeries`, `FeeSpec`,
`GasEstimate`, `KellyReport`, `AdapterChange`, `ProtocolExposure`, `HealthResult`,
`RebalanceMove`, `StablecoinExposure`, `CorrelationResult`, `CurvePoint`, `LadderRung`,
`AllocationSlot`) — их модули остаются обычными библиотеками. `cycle_health_monitor` —
DEPRECATED в пользу `spa_core.monitoring.cycle_health_monitor`, из реестра удалён.
