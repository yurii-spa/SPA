"""_untiered_census.py — перепись модулей аналитики ВНЕ тиров реестра.

СГЕНЕРИРОВАН ЗАМЕРОМ, руками не набран. Провенанс — одна воспроизводимая команда:

    python3 scripts/audit_untiered_analytics.py --emit-markup

Зачем файл существует. Метрика «% работающего слоя» считается от знаменателя, в
который эти модули не входили ВООБЩЕ: реестр тиров знает 671,
на диске лежат 754 публичных модулей, разница — 83.
Пока они не названы, знаменатель — не оценка, а незнание, выдающее себя за оценку.

Файл ничего не исполняет и ничего не запрещает. Он ТОЛЬКО называет каждый модуль и
измеренную причину его положения, чтобы метрику можно было посчитать от всего корпуса.

Разбивка замера: {"deprecated_tombstone": 1, "inherits_base_stub": 21, "not_a_signal_module": 60, "unchecked": 1}
"""
from typing import Dict

#: Когда снят замер, из которого построен этот файл.
AUDIT_GENERATED_AT = '2026-08-30T18:23:43.070260Z'

#: Размер реестра тиров и число публичных модулей на диске на момент замера.
REGISTRY_SIZE = 671
ON_DISK = 754

#: Надгробия: импорт намеренно бросает ImportError со словом DEPRECATED — файл
#: оставлен указателем на замену. Не модуль сигнала. Имя → дословный текст отказа.
DEPRECATED_TOMBSTONE: Dict[str, str] = {
    'cycle_health_monitor':
        'DEPRECATED: use spa_core.monitoring.cycle_health_monitor instead',
}

#: Импорт падает по иной причине. Это НЕ «модуль не работает» — это «модуль нельзя
#: даже загрузить», и причина названа дословно. Имя → причина.
IMPORT_FAILED: Dict[str, str] = {

}

#: Не модуль сигнала по контракту самого агрегатора: нет публичного класса с
#: методом-входом из `_ENTRY_METHODS`. Служебный код (отчёты, движки, трекеры).
#: Позвать его агрегатор не может, поэтому в корзину «неработающих» он не идёт —
#: он идёт ВНЕ знаменателя, с названной причиной. Имя → причина.
NOT_A_SIGNAL_MODULE: Dict[str, str] = {
    'adapter_correlation_matrix':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'adapter_health_scorecard':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'adaptive_apy_target':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'allocator_advisors':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'apy_series_accumulator':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'architecture_audit':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'chain_fee_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'conc_lp_il_model':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'correlation_matrix_builder':
        'нет публичного класса с методом-входом; классов в модуле: 4',
    'cpa_health_dashboard':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'decision_audit_trail':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_cross_protocol_yield_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_gas_optimization_advisor':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_liquid_staking_rate_comparator':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_liquidity_mining_roi_calculator':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_nft_collateral_valuation_model':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_protocol_fee_tier_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_protocol_leverage_adjusted_apy_calculator':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_protocol_market_share_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'defi_protocol_yield_harvesting_frequency_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'fee_calculator':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'fee_drag_calculator':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'fee_structure':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'gas_cost_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'gas_optimization_engine':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'governance_token_value_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'gross_of.sequencer_tip_config':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'kelly_position_sizer':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'lp_position_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'monthly_performance_report':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'portfolio_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'portfolio_snapshot_diff':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'portfolio_stats':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'portfolio_volatility_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'protocol_concentration_risk':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'protocol_defi_gas_cost_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'protocol_defi_position_size_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'protocol_defi_stable_yield_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'protocol_health_checker':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'rebalance_engine':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'rebalance_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'report_sections':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'research_risk_attribution':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'research_risk_limits':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'signal_aggregator':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'source_integration_helper':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'stablecoin_exposure_report':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'staking_reward_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'strategy_benchmark_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'strategy_correlation_matrix':
        'нет публичного класса с методом-входом; классов в модуле: 2',
    'strategy_rs001_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'strategy_rs002_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'tier_curator':
        'нет публичного класса с методом-входом; классов в модуле: 0',
    'weekly_paper_report_v2':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'yield_attribution_tracker':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'yield_curve_builder':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'yield_ladder_builder':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'yield_reinvestment_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
    'yield_route_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 3',
    'yield_timing_optimizer':
        'нет публичного класса с методом-входом; классов в модуле: 1',
}

#: Класс есть, метод-вход формально есть — но реализован он в базовом классе, а не
#: здесь: `BaseAnalytics.analyze` возвращает пустой dict. Вход НЕ НАПИСАН. Прогон даёт
#: `dormant`, и этот ярлык уводит: он зовёт чинить данные, тогда как чинить надо
#: реализацию (или признать, что она не нужна). Имя → измеренная причина.
INHERITS_BASE_STUB: Dict[str, str] = {
    'apy_history_tracker':
        'APYHistoryTracker.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'chain_allocator':
        'ChainAllocator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'cross_chain_yield':
        'CrossChainYieldComparator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'defillama_feed_monitor':
        'DeFiLlamaFeedMonitor.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'evidence_auto_calculator':
        'EvidenceAutoCalculator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'golive_readiness_report':
        'GoLiveReadinessReport.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'investment_memo_generator':
        'InvestmentMemoGenerator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'monte_carlo':
        'MonteCarloSimulator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'paper_backtest_drift_v2':
        'PaperBacktestDriftV2.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'paper_evidence_tracker_v2':
        'PaperEvidenceTrackerV2.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'protocol_data_audit':
        'ProtocolDataAudit.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'regime_adjusted_allocator':
        'RegimeAdjustedAllocator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'research_summary_report':
        'ResearchSummaryReport.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'rs001_live_apy_engine':
        'RS001LiveAPYEngine.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'rs001_stress_engine':
        'RS001StressEngine.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'rs002_live_apy_engine':
        'RS002LiveAPYEngine.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'rs002_position_tracker':
        'RS002PositionTracker.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'source_acquisition_tracker':
        'SourceAcquisitionTracker.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'stablecoin_yield_optimizer':
        'StablecoinYieldOptimizer.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    't1_data_verifier':
        'T1DataVerifier.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
    'var_calculator':
        'VaRCalculator.analyze не реализован — наследуется заглушка BaseAnalytics, возвращающая пустой dict',
}

#: Агрегатор позвать МОЖЕТ — измерен тем же дифференциальным тестом, что и тиры.
#: Это кандидаты в реестр; включение в тир — отдельное решение владельца, не этот
#: файл. Имя → измеренный класс и точка входа.
WIRABLE: Dict[str, str] = {
    'bts_exit_monitor':
        'unchecked · класс BTSExitMonitor.run',
}

#: Вне знаменателя метрики: позвать нечем, и это измерено, а не предположено.
OUT_OF_DENOMINATOR = (
    frozenset(DEPRECATED_TOMBSTONE) | frozenset(IMPORT_FAILED)
    | frozenset(NOT_A_SIGNAL_MODULE) | frozenset(INHERITS_BASE_STUB)
)

#: Все переписанные модули (объединение четырёх наборов).
ALL_UNTIERED = OUT_OF_DENOMINATOR | frozenset(WIRABLE)
