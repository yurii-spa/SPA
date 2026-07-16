# analytics_lab — вынесенные измерительные метрики (Q2, owner-approved 2026-07-16)

Модули из `paper_trading/`: построены+тестированы, но НЕ подключены к продукту (0 внешних импортов —
проверено precise-грепом). Разгружают money-path вдвое. **Не удалять** — сырьё для будущего продуктового
слоя агентов (аналитики, docs/08_ai_investment_os_architecture.md). Пакет создан; массовый перенос —
следующей сессией по протоколу (не начат целиком т.к. был near-full context).

## Верифицированы как внешне-мёртвые (0 non-test import) — к переносу:
advanced_ratios · alpha_decay · apy_dispersion_analytics · bias_ratio · calendar_returns ·
capm_decomposition · conditional_drawdown · cost_drag_analytics · deflated_sharpe · distribution_normality ·
k_ratio · linearity_analytics · monte_carlo_projection · rachev_ratio · regime_conditional_performance ·
regime_segmentation · return_distribution · return_predictability · risk_contribution · rolling_performance ·
serial_dependence · sterling_burke_ratio · tail_risk · ulcer_index · upside_potential_ratio ·
walk_forward_validator · yield_decay_analytics (+ ещё ~18 из pass-1 списка — доверифицировать)

## ПРОТОКОЛ переноса (обязательно, как в чистке модулей):
1. Для каждого: precise import-check (`from spa_core.paper_trading.<mod>`) — 0 non-test.
2. Проверить intra-импорты МЕЖДУ переносимыми (если A импортит B — переписать на `spa_core.analytics_lab.B`).
3. Найти посвящённый тест → перенести ВМЕСТЕ (инвариант #16) + переписать его импорт на analytics_lab.
4. `pytest --collect-only spa_core/tests/ tests/` = 0 ошибок (ловит осиротевшие импорты за ~8с).
5. Батчами: attic-move → collect-gate green → push копий → github_delete оригиналов. Всё обратимо.
