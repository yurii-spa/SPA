# ADR-2026-008: Включение Yearn V3 yvUSDC в Tier 1 (v0.4.5)

Дата: 2026-05-03
Статус: Accepted
Owner: Юра

## Контекст

v0.4 успешно перебалансирована (8% net yield). Owner добавляет ОДИН Layer из v0.5 концепции — Layer 5 (auto-compound через Yearn V3 yvUSDC). Это гибрид v0.4 + Layer 5.

Auto-compound vault даёт +1-2% APY поверх прямого lending за счёт автоматического реинвестирования rewards и консолидации gas-cost.

## Решение

Добавить **Yearn V3 yvUSDC** в Tier 1 как T1-05 (10% портфеля).

### Перераспределение Tier 1 (60% сохраняется)

| # | Протокол | v0.4 | v0.4.5 |
|---|---|---|---|
| T1-01 | Aave V3 USDC | 25% | 20% |
| T1-02 | Morpho Blue Steakhouse | 15% | 12% |
| T1-03 | Compound V3 | 10% | 8% |
| T1-04 | Sky sUSDS | 10% | 10% |
| **T1-05** | **Yearn V3 yvUSDC** | — | **10%** (NEW) |

## Технические характеристики

- ERC-4626 compliant
- Аудит: ChainSecurity (yearn-v3-vaults audit)
- Multi-strategy с возможностью отзыва из проблемной стратегии
- 2026 typical APY: 4.5-6.5% + 1-2% от компаундинга = 6.5-7.5% итог
- Fees: 15% performance fee (учтено в APY)

## Что включается, что нет

✅ **Используется:** классический Yearn V3 yvUSDC (multi-strategy, без leverage)
❌ **НЕ используется:** yvUSD V3 (январь 2026, zero-fee, использует leveraged looping)

## Альтернативы

- Layer 4 (Airdrop) — отклонено: высокая волатильность
- Layer 3 (Delta-neutral) — отклонено: CEX counterparty risk
- Discovery Agent — отклонено: требует архитектурной работы

## Эффект

Net APY: 7.8% → 9.2% (+1.4 п.п.). Drawdown 5% не меняется. Архитектура агентов не меняется.

## Условия мониторинга

- Состав активных стратегий yvUSDC проверяется еженедельно
- При появлении leveraged looping в стратегиях — немедленный exit

## Подпись Owner: 2026-05-03
