# S11 — Hybrid Yield Maximizer (MP-421)

**Tier:** T3-SPEC | **Target APY:** 15.6% | **Risk Score:** 0.70  
**Status:** research | **Файл:** `spa_core/strategies/s11_hybrid_yield_max.py`  
**Создана:** 2026-06-12

---

## Концепция

S11 превосходит S10 (14.0% target) за счёт комбинирования высокодоходного
Pendle YT с T1/T2 safety buffer. Стратегия переключается между тремя режимами
в зависимости от рыночных условий.

---

## Аллокация

### Bull mode (Pendle YT APY ≥ 12%)

| Протокол | Вес | APY (bull) | Tier | Вклад в blended |
|---|---|---|---|---|
| Pendle YT | 45% | ~28.4% | T3-SPEC | 12.78% |
| Morpho Steakhouse | 30% | 6.5% | T1 | 1.95% |
| Euler V2 | 15% | 2.78% | T2 | 0.42% |
| Maple | 10% | 4.74% | T2 | 0.47% |
| **Итого** | **100%** | | | **≈ 15.62%** |

### Fallback mode (Pendle YT APY < 12%)

| Протокол | Вес | APY | Tier |
|---|---|---|---|
| Morpho Steakhouse | 50% | 6.5% | T1 |
| Morpho Blue | 30% | 4.75% | T1 |
| Maple | 15% | 4.74% | T2 |
| Euler V2 | 5% | 2.78% | T2 |
| **Blended** | **100%** | **≈ 5.8%** | T1/T2 |

### Risk-off mode

Данные APY недоступны → нулевая аллокация, APY = 0%.

---

## Ключевые параметры

| Параметр | Значение |
|---|---|
| `MIN_PENDLE_YT_APY` | 12.0% |
| `MAX_PENDLE_EXPOSURE` | 50% |
| `REBALANCE_THRESHOLD` | ±5% drift |
| `MAX_DRAWDOWN_PCT` | 5% (kill-switch) |
| `MIN_DAYS_PAPER` | 30 (ADR-023) |
| `MIN_SHARPE` | 1.0 (ADR-023) |

---

## Архитектурные решения

**Pendle YT — advisory only (ADR-021):** позиции не открываются автоматически.
APY учитывается в расчётах (paper), live adapter отсутствует.

**Трёхрежимная логика:** bull → fallback → risk_off обеспечивает мягкую
деградацию: при ухудшении рынка S11 переходит в консервативный T1/T2 портфель
вместо полной остановки.

**Нет external dependencies:** только Python stdlib. Атомарные записи
(mkstemp + os.replace) для JSON.

---

## Тесты

`tests/test_s11_hybrid_yield_max.py` — **65 unittest** (100% pass):

- `TestInit` (6) — capital, allocation sums, tier, id
- `TestGetMode` (9) — bull / fallback / risk_off по APY значениям
- `TestGetAllocation` (6) — ключи и веса по каждому режиму
- `TestComputeExpectedAPY` (10) — weighted math, edge cases, defaults
- `TestValidateAllocation` (9) — Pendle cap, sum check, negative weights
- `TestRunDay` (8) — все режимы, накопление капитала, обязательные ключи
- `TestAllocationConstraints` (7) — константы cap / threshold / risk_score
- `TestNeedsRebalance` (5) — drift threshold, risk_off, at-threshold
- `TestGetStats` (5) — stats keys, days accumulation, vportfolio format

---

## Сравнение с существующими стратегиями

| Стратегия | APY target | Risk Score | Режимов |
|---|---|---|---|
| S7 Pendle YT+PT Aggressive | 10.1% | 0.52 | 2 (base/PT-only) |
| S10 Pendle YT Max Spec | 14.0% | 0.75 | 3 (bull/base/bear) |
| **S11 Hybrid Yield Max** | **15.6%** | **0.70** | **3 (bull/fallback/risk_off)** |

S11 достигает более высокого APY при меньшем риск-скоре чем S10 за счёт
T1 якоря (Morpho Steakhouse 30%) который стабилизирует портфель.

---

## Go-live условия (ADR-023)

- `MIN_DAYS_PAPER` = 30 дней paper trading без пробелов
- `MIN_SHARPE` ≥ 1.0
- `USER_APPROVAL` Owner перед переходом в live
- Pendle YT требует on-chain адаптера (сейчас отсутствует)

*Обновлено: 2026-06-12 (MP-421)*
