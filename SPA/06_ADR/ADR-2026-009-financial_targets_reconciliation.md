# ADR-2026-009 — Сверка финансовых целей по уровням капитала

**Дата:** 2026-05-03
**Статус:** Accepted
**Версия документации:** SPA v0.4.5
**Связанные ADR:** ADR-2026-005, ADR-2026-006, ADR-2026-007, ADR-2026-008

---

## Контекст

После принятия ADR-005..008 документация v0.4.5 содержит несколько неявно конфликтующих финансовых таргетов:

1. **v0.4 заявленный target net APY:** ≥8% (агрессивный режим)
2. **v0.4.5 фактический weighted gross APY whitelist (рассчитан в ADR-008):** ~7.4%
3. **Tail Risk Reserve (8%) на 4.25%** в общем portfolio yield: drag.
4. **Аспирационный таргет:** ≥9% при крупных капиталах (упоминался в внутренних обсуждениях).

Рецензия из соседнего чата (peer review) выделила 4 проблемы:

1. Заявленный 8% vs реально достижимый 7.4% (gross, не учитывая operational costs).
2. Operational costs (gas, провайдеры $110–125/мес, accounting) — могут съесть 100–300 bps в зависимости от capital base.
3. Yearn V3 performance fee (15%) уже включён в quoted APY, но это не очевидно из документации.
4. Tail Risk Reserve вынесен за working capital в v0.4, но в v0.3 он был внутри 100% — расчёт portfolio APY не последователен между версиями.

Цель ADR-009: явная сверка финансовых таргетов с учётом всех factors, дифференцированная по уровням капитала.

## Решение

**Принять следующую структуру финансовых таргетов SPA v0.4.5.**

### Gross APY working capital (без учёта operational costs)

Weighted average по whitelist v0.4.5:

| Tier | Доля | Component APY | Contribution |
|---|---|---|---|
| T1-01 Aave V3 USDC | 20% | 4.8% | 0.96% |
| T1-02 Morpho Steakhouse | 15% | 6.5% | 0.98% |
| T1-03 Compound V3 USDC | 10% | 4.5% | 0.45% |
| T1-04 Sky sUSDS | 10% | 4.25% | 0.43% |
| T1-05 Yearn V3 yvUSDC | 10% | 7.0% | 0.70% |
| T2-01 Pendle PT-sUSDe | 12% | 10.0% | 1.20% |
| T2-02 Pendle PT-syrupUSDC | 10% | 9.0% | 0.90% |
| T2-03 Maple syrupUSDC | 8% | 8.5% | 0.68% |
| T2-04 Euler V2 USDC | 5% | 6.0% | 0.30% |
| **Weighted average** | **100%** | | **7.60%** |

Округлённо: **Gross APY working capital target = 7.4%** (с учётом haircut на rate volatility −20 bps).

### Operational costs structure

Фиксированные:

- **Провайдеры:** ~$110–125/мес = $1,320–1,500/yr (Alchemy/QuickNode $49, DefiLlama Pro $25, Zapper $30, Tenderly $0–50, Koinly $9–15)
- **Анализ/время:** условно $0 (self-managed)

Переменные:

- **Gas:** rebalance bi-weekly + event-driven. Ethereum ~$30–80 per rebalance × 26 = $780–2,080/yr. Layer 2 rebalance ~$2–5 per × 50 = $100–250/yr.
- **Pendle PT roll:** ~$20–40 per maturity × 8/yr = $160–320/yr.
- **Bridge costs:** canonical bridges ~$10–30 per move, ожидаемо 6–12 раз/год = $60–360/yr.

**Total operational costs (estimate): $2,500–4,500/yr.**

### Net APY таргеты по уровням капитала

| Capital | Op cost / yr (est) | Op cost as % | Gross APY | Net APY target | Annual net $ |
|---|---|---|---|---|---|
| $10K | $2,500 | 25.0% | 7.4% (working 92%) → 6.8% effective | **4.0%** | $400 |
| $25K | $3,000 | 12.0% | 6.8% effective | **6.2%** | $1,545 |
| $50K | $3,500 | 7.0% | 6.8% effective | **6.9%** | $3,452 |
| $100K | $4,000 | 4.0% | 6.8% effective | **7.3%** | $7,266 |
| $250K | $4,500 | 1.8% | 6.8% effective | **7.5%** | $18,707 |

Где "Gross effective" = 7.4% × 92% working + 4.25% × 8% TRR = 6.81% ≈ 6.8%.

Net APY = Gross effective − (Op cost / Capital).

### Aspirational target

При капитале ≥$250K и оптимизированной операционной структуре:

- Concentration в L1 protocols (lower gas frequency rebalances)
- Bridge usage minimised
- Возможный uptick от Tier 2 при favorable Pendle maturity rolls

→ **aspirational net APY ≥9%** достижим в **благоприятный квартал**, но не как baseline.

### Что это означает практически

1. **Заявлять "Net APY 8%"** — НЕ корректно для капиталов <$100K. Заявлять "Gross APY 7.4%" — корректно для всех уровней.
2. **Минимальный размер capital для разумного use case:** $25K (Net APY 6.2% даёт >$1,500/yr против $3K op cost).
3. **Below $10K** SPA не имеет позитивного economic case — proven выше op cost.
4. **Выше $100K** marginal Net APY улучшение ограничено (7.3% → 7.5%); aspirational 9% — это upside, не gospel.

### Что нужно обновить в документации

- `Risk_Policy_v0.4.5.md`: добавить таблицу Net APY по уровням капитала, убрать unconditional "≥8%" claim.
- `Mode_Policy_v0.4.5.md`: явное предупреждение про minimum viable capital ($25K).
- `08_Accounting_and_PnL_v0.4.5.md`: формула Net APY = Gross effective − (Op cost / Capital).
- `12_Reporting_Weekly_Template_v0.4.5.md`: weekly включает rolling 30-day op cost в bps от capital.

## Альтернативы

1. **Не делать reconciliation, оставить v0.4 ≥8% как aspirational** — отклонено. Создаёт ожидания, которые система не выполняет на малых капиталах.
2. **Установить единый Net APY 6%** — отклонено. Не отражает экономии масштаба.
3. **Минимальный capital threshold $50K** — отклонено как требование, но 25K зафиксирован как "минимальный осмысленный".

## Последствия

**Положительные:**
- Реалистичные ожидания пользователя.
- Чёткий decision point: при каком капитале SPA имеет смысл.
- Прозрачность вокруг operational costs (часто игнорируется DeFi сообществом).

**Отрицательные:**
- "Маркетинговый" положение слабее (7.5% звучит менее впечатляюще, чем "≥8%").
- Сложнее explain пользователю — нужно несколько таблиц вместо одной цифры.

**Митигация:** в `00_Context_v0.4.5.md` добавить раздел "Когда SPA имеет смысл" с ясной таблицей по уровням капитала.

## Ссылки

- `Risk_Policy_v0.4.5.md` (обновлённая секция Financial Targets)
- `08_Accounting_and_PnL_v0.4.5.md` (Op cost tracking)
- ADR-2026-005, 006, 007, 008 (источники компонентов)
- Memory facts: подтверждённые цифры по уровням капитала
- Peer review chat: 4 проблемы → ADR-009 reconciliation
