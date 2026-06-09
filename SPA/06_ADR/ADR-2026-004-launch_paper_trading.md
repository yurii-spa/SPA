# ADR-2026-004 — Запуск Paper Trading для Stable Lending Core

**Дата:** 2026-05-02
**Статус:** Accepted
**Версия документации:** SPA v0.3
**Связанные ADR:** ADR-2026-001, ADR-2026-002, ADR-2026-003

---

## Контекст

После принятия документации v0.3 и выбора провайдерского стека (ADR-001..003) необходимо валидировать первую стратегию — **Stable Lending Core** — в режиме paper trading перед коммитом реального капитала.

Цели paper trading:

1. Проверить корректность сигналов мониторинга (TVL, utilization, oracle freshness, governance heartbeat).
2. Зафиксировать baseline-метрики whitelist-протоколов на момент запуска.
3. Прогнать процедуры Operations Runbook без реального риска.
4. Накопить 4 недели данных для оценки tracking error между ожидаемым и фактическим APY.

## Решение

**Запустить paper trading Stable Lending Core с 2026-05-02 на длительность 4 недели (Week 0 → Week 4).**

### Параметры

- **Виртуальный капитал:** $100,000 USDC
- **Аллокация (по Whitelist v0.3):**
  - Aave V3 USDC: 40% ($40,000)
  - Compound V3 USDC: 35% ($35,000)
  - Sky sUSDS: 15% ($15,000) — Watch List, мониторинг без аллокации сверх лимита
  - Tail Risk Reserve (мёртвый кэш USDC): 10% ($10,000)
- **Режим:** Conservative (yield ≥4%, drawdown ≤2%)
- **Ребалансировка:** еженедельно, threshold 5% от целевой аллокации
- **Reporting:** Weekly Report по шаблону `12_Reporting_Weekly_Template_v0.3.md`

### Baseline (Week 0, 2026-05-02)

Зафиксирован в документе `Paper_Trading_Week0_Baseline_2026-05-02.md`:

| Протокол | TVL | APY (supply) | Utilization | Health |
|---|---|---|---|---|
| Aave V3 USDC (Ethereum) | $1.85B | 4.62% | 71% | ✅ |
| Compound V3 USDC (Ethereum) | $620M | 4.28% | 68% | ✅ |
| Sky sUSDS | $2.10B | 4.25% | n/a | ✅ |

### Критерии успеха paper trading

- Tracking error (фактический vs ожидаемый APY): ≤50 bps на конец Week 4
- Все алерты Monitoring_and_Alerts корректно сработали ≥1 раз каждый
- Нет ложных срабатываний governance heartbeat
- Operations Runbook прошёл хотя бы один цикл rebalance без блокирующих ошибок

### Критерии остановки

- Drawdown симуляции > 1% (50% от лимита Conservative режима)
- Любой Tier 1 протокол триггерит kill-criteria из Risk_Policy
- Расхождение whitelist-source между Aave/Compound/Morpho/DefiLlama по TVL >15%

## Альтернативы

1. **Сразу запустить с реальным капиталом** — отклонено. Слишком много непроверенных компонентов (агенты, провайдеры, alerts).
2. **Симуляция на исторических данных без live-фида** — отклонено. Не валидирует live-инфраструктуру провайдеров и timing алертов.
3. **Расширенный набор стратегий с первого дня** — отклонено. Stable Lending Core достаточно прост, чтобы изолировать проблемы инфраструктуры от проблем стратегии.

## Последствия

**Положительные:**
- 4 недели данных для калибровки моделей и алертов до коммита капитала
- Документированный baseline для будущего сравнения
- Тренировка операционных процедур

**Отрицательные:**
- Задержка ~4 недели до первого реального коммита
- Риск, что paper trading не выявит проблемы, проявляющиеся только при реальной торговле (slippage, MEV)

**Митигация:** добавить Week 4 → Week 6 фазу "small live" с $5K реального капитала перед полным деплоем.

## Ссылки

- `11_Paper_Trading_and_Simulation_Plan_v0.3.md`
- `Paper_Trading_Week0_Baseline_2026-05-02.md`
- `Strategy_Passport_Stable_Lending_Core_v0.3.md`
- `12_Reporting_Weekly_Template_v0.3.md`
