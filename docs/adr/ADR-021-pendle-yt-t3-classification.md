# ADR-021: Pendle YT Tokens — T3 Speculative Asset Classification

**Status:** Accepted  
**Date:** 2026-06-12  
**Authors:** SPA Architect  
**Supersedes:** —  
**Related:** ADR-020 (T3 Private Credit), ADR-019 (T2 cap increase)

---

## Context

Pendle Finance платформа классифицирована как **T2** (TVL $2B+, прошла аудиты, 3+ года на mainnet). Однако Pendle **YT (Yield Tokens)** представляют собой принципиально иной класс активов — спекулятивные деривативы с детерминированным обнулением стоимости к матюрити.

### Механика YT

Pendle разделяет доходный актив (например, weETH, sUSDe) на два токена:

- **PT (Principal Token):** фиксированная сумма к матюрити — T2-актив, классифицирован в `ADR_002_pendle_pt_integration.md`.
- **YT (Yield Token):** право на будущую доходность актива до матюрити.

Характеристики YT, критические для классификации:

| Параметр | Значение |
|----------|----------|
| Цена к матюрити | **Детерминированно → 0** (по дизайну протокола) |
| Структура выплаты | `(realized_apy − implied_yield) × notional × leverage` |
| Кредитное плечо | Типично **3–4×** (зависит от pool ratio) |
| Максимальный убыток | 100% цены YT = **~25% от notional** |
| Тета-распад | Ускоряется по мере приближения матюрити |

### Почему YT ≠ T2

Pendle-платформа T2, но YT-токены нарушают базовые предположения T2:

1. **Нет concept of "holding at par"** — цена YT не стабилизируется, она обязана упасть до нуля.
2. **Бинарный исход относительно implied yield** — если realized APY < implied → убыток всей позиции YT.
3. **Leverage** 3–4× амплифицирует и прибыль, и потери.
4. **Ликвидность деградирует** по мере приближения к матюрити.

---

## Decision

**Классифицировать Pendle YT как T3-SPECULATIVE** — отдельный подтип T3 ниже T3-GROWTH (Maple, Clearpool).

---

## Constraints

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| Max allocation | **30% vPortfolio** | Максимальный cap для высокорискового спекулятивного актива |
| Entry gate | `current_apy ≥ implied × 1.25` | 25% safety cushion против implied yield |
| Max hold | **60% от duration до матюрити** | Избежать ускорения тета-распада в последней трети |
| Kill trigger | `current_apy < implied` | Немедленный выход при инверсии yield-условий |
| Tier | **T3-SPECULATIVE** | Ниже T3-GROWTH; отдельный subtype в RiskPolicy |

---

## Consequences

**Положительные:**
- В bull-рынке (elevated DeFi APY): 20–50% годовых за счёт кредитного плеча.
- Диверсификация относительно стабильного stablecoin-yield портфеля.
- Strategy tournament (S10 PendleYTStrategy) конкурирует на risk-adjusted основе.

**Отрицательные:**
- Bear: возможна полная потеря позиции YT (25% notional, до 30% vPortfolio).
- Требует ежедневного мониторинга: current APY vs implied yield.
- Liquidity risk у матюрити: высокий bid-ask spread, возможен forced exit по нерыночной цене.

---

## Implementation Notes

- `S10 PendleYTStrategy` реализует entry gate (`current_apy ≥ implied × 1.25`) + exit logic (`current_apy < implied`).
- Максимум **30% от total capital** по всем Pendle YT позициям совокупно.
- Tournament weight: **30%** в период proof-of-concept (высокий риск требует демонстрации).
- После 30 дней paper trading — promote / kill решение на основе TournamentEvaluator.

---

## Approval Criteria (для go-live)

- [ ] Paper trading: **30+ дней**
- [ ] Средний симулированный APY > **12%** (превышает T2 threshold)
- [ ] Максимальная симулированная просадка < **35%**
- [ ] Kill switch drill: **PASS**

---

## Rollback

Выставить S10 PendleYTStrategy status = `killed` в strategy_registry; удалить T3-SPECULATIVE subtype из RiskPolicy версии. До реализации T3-SPECULATIVE enforcement в allocator — rollback без последствий (поле присутствует, но не enforced).

---

## Related Decisions

- **ADR_002_pendle_pt_integration.md** — Pendle PT как T2-актив (фиксированный yield, PT→1:1 к матюрити)
- **ADR-019** — T2 cap increase 35%→50% AUM
- **ADR-020** — T3 Private Credit / RWA Category 15% cap
- **ADR-001** — Initial risk policy (T1/T2 caps origin)
- Future MP: T3-SPECULATIVE adapter (`spa_core/adapters/pendle_yt_adapter.py`)
- Future MP: Allocator T3-SPECULATIVE enforcement (30% cap, entry gate, kill trigger)
