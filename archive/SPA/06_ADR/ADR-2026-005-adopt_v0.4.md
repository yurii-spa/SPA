# ADR-2026-005 — Принятие SPA v0.4 (агрессивный режим)

**Дата:** 2026-05-01
**Статус:** Accepted
**Версия документации:** SPA v0.4
**Связанные ADR:** ADR-2026-001 (v0.3), ADR-2026-006, ADR-2026-007

---

## Контекст

Документация v0.3 определяла консервативные таргеты (yield ≥4%, drawdown ≤2%) для Stable Lending Core. После анализа рынка stablecoin DeFi yields на апрель–май 2026 (Pendle PT-инструменты с фиксированным yield 9–12%, syrupUSDC от Maple 8–10%, Sky sUSDS стабилизировался на 4.25%), стало очевидно, что консервативный режим оставляет значительную ожидаемую доходность на столе.

Параллельно, baseline paper trading Stable Lending Core (Week 0, см. ADR-004) показал, что инфраструктура провайдеров и агентов готова поддерживать более широкий whitelist.

Цель v0.4: расширить операционный диапазон системы без потери базовых принципов risk management (kill-criteria, oracle independence, governance heartbeat).

## Решение

**Принять документацию SPA v0.4 — "агрессивный режим" — как основной операционный конфиг с 2026-05-01.**

### Изменения относительно v0.3

#### Yield-таргеты

| Параметр | v0.3 (Conservative) | v0.4 (Aggressive) |
|---|---|---|
| Target net APY | ≥4% | ≥8% |
| Max drawdown | ≤2% | ≤5% |
| Tier 1 / Tier 2 split | 100% / 0% | 60% / 40% |

#### Расширение whitelist

См. отдельный **ADR-2026-006**: расширенный whitelist включает Pendle PT, Maple syrupUSDC, Morpho Blue (Steakhouse/Gauntlet/Block Analitica vaults), Euler V2.

#### Multi-chain

- Tier 1: добавлены Arbitrum + Base (помимо Ethereum L1) для Aave V3 и Compound V3.
- Tier 2: Pendle на Ethereum, Maple на Ethereum.
- Bridge canonical only (Arbitrum Bridge, Base Bridge). НЕТ third-party bridges (Stargate, Across) в v0.4.

#### Sky sUSDS

См. **ADR-2026-007**: повышен из Watch List в Tier 1 с долей 10%; Tail Risk Reserve переведён из мёртвого USDC в sUSDS.

#### Operations

- Ребалансировка: переход с еженедельной на bi-weekly + event-driven (threshold 7% от целевой аллокации).
- Reporting: weekly report расширен секцией Tier 2 performance.

### Что НЕ изменилось из v0.3

- Все kill-criteria из Risk_Policy остаются в силе (oracle stale >30 min, governance compromise, TVL drop >50% за 24h, smart contract exploit).
- Heartbeat protocol governance review: 7 дней.
- Agent Architecture: тот же стек (см. `18_Agent_Architecture_v0.3.md`).
- Принцип oracle independence (минимум 2 независимых источника цены/TVL).

## Альтернативы

1. **Остаться на v0.3 как стабильной базе** — отклонено. Yield 4% при доступности 7–9% на проверенных протоколах — это упущенная альфа без соответствующего снижения риска.
2. **Полностью агрессивный режим (Tier 1 / Tier 2 = 40/60)** — отклонено. Слишком резкий переход без накопленных данных по Tier 2 поведению в стрессе.
3. **Гибридный режим: оставить v0.3 как опцию, добавить v0.4 как параллельный preset** — отклонено в v0.4, но фактически реализовано через ADR-009 (Financial Targets Reconciliation): пользователь может выбрать profile в зависимости от капитала.

## Последствия

**Положительные:**
- Ожидаемый net APY: 6–8% вместо 4%.
- Диверсификация по типам yield-источников (lending + fixed-rate + tokenized RWA через Maple).
- Более полное использование инфраструктуры мониторинга.

**Отрицательные:**
- Более широкий attack surface (больше протоколов, больше цепочек).
- Tier 2 имеет более низкую TVL и меньшую историю стресс-тестов.
- Pendle PT может иметь low secondary liquidity ближе к maturity.

**Митигация:**
- Tier 2 каждая позиция: max 15% allocation, max 25% от Tier 2 TVL контракта.
- Pendle: только PT с maturity ≤90 дней.
- Maple: только syrupUSDC (overcollateralized institutional), НЕ pool USDC permissionless.

## Ссылки

- `Risk_Policy_v0.4.md` (содержит обновлённые таргеты)
- `Mode_Policy_v0.4.md`
- `04_Whitelist_Policy_v0.4.md` (см. также ADR-006)
- ADR-2026-006: Extended Whitelist v0.4
- ADR-2026-007: Tail Risk Reserve переведён в sUSDS
- CHANGELOG_v0.4_v0.4.5.md
