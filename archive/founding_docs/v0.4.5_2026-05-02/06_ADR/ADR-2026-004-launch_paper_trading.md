# ADR-2026-004: Запуск Paper Trading — Stable Lending Core

Дата: 2026-05-02
Статус: Accepted
Owner: Юра
Связанные документы: Paper Trading Plan v0.3, Strategy Passport Stable Lending Core v0.3, Whitelist Policy v0.3

---

## Контекст

Все блокеры для запуска paper trading устранены:
- ADR-2026-001: документация v0.3 принята ✅
- ADR-2026-002: whitelist заполнен (Tier 1 + Tier 2) ✅
- ADR-2026-003: provider stack определён ✅
- Strategy Passport Stable Lending Core: Draft → Paper ✅

Paper trading — обязательный этап перед любым реальным капиталом (Paper Trading Plan v0.3, раздел 9).

---

## Решение

Запустить paper trading для стратегии Stable Lending Core.

### Параметры запуска

| Параметр | Значение |
|----------|----------|
| Дата старта | 2026-05-02 |
| Минимальная длительность | 56 дней (8 недель) — до 2026-06-27 |
| Виртуальный капитал | 10 000 USDT |
| Режим | Manual (Autopilot не включается в paper trading) |
| Целевая структура | 70% Tier 1 / 30% Tier 2 / 10% Tail Risk Reserve (виртуальный) |
| Environment | MODE=paper, ключи невалидные или test-only |

### Целевое размещение виртуального капитала

**Tier 1 (70% = 7 000 USDT):**
- T1-01 Aave V3 USDC: ~3 010 USDT (43% от T1)
- T1-02/03 Morpho Blue USDC vaults: ~2 030 USDT (29% от T1)
- T1-04 Compound V3 USDC: ~1 960 USDT (28% от T1)

**Tier 2 (30% = 3 000 USDT):**
- T2-01/02 Pendle PT (≤90д): до 900 USDT совокупно
- T2-03 Maple syrupUSDC: до 750 USDT
- T2-04 Euler V2 (Conditional): до 450 USDT
- T2-R резервный буфер: ≥ 600 USDT (≥20% T2)

**Tail Risk Reserve (виртуальный, 10% = 1 000 USDT):** не размещается, отдельный учёт.

---

## Условия успеха (Paper Trading Plan v0.3, раздел 7)

Все должны быть выполнены одновременно:
- стратегия исполняется без логических ошибок
- Risk Policy не нарушена
- ≤5 действий в неделю в среднем
- net yield > 0 на горизонте теста
- нет необъяснимых сценариев
- все алерты объяснимы
- ни один drawdown-порог не превышен без объяснения

---

## Условия досрочного прекращения

- стратегия требует постоянного ручного вмешательства (>5 раз в неделю)
- возникли сценарии, не покрытые документацией
- расхождения симуляции систематически превышают Paper Trading Plan 4.1

---

## Что должно быть создано по итогам

- 8+ weekly reports (Reporting Weekly Template v0.3)
- финальный summary с выводом: **готово / не готово к live**
- ADR-2026-005: перевод Paper → Active (или закрытие стратегии)
- откалиброванные пороги через мини-ADR

---

## Последствия

- Strategy Passport Stable Lending Core: статус Draft → **Paper**
- Отчётность: еженедельно по Reporting Weekly Template
- Следующий decision point: 2026-06-27 (минимум 8 недель)

---

## Подпись Owner

Дата утверждения: 2026-05-02
Owner: Юра
