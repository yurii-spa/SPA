# Paper Trading & Simulation Plan

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Risk Policy v0.3, Mode Policy v0.3, Strategy Passport: Stable Lending Core v0.3, Execution Cost Model v0.3, Accounting & PnL v0.3, Monitoring & Alerts v0.3

Changelog from v0.2:
- Исправлено противоречие статуса.
- **Минимальная продолжительность увеличена с 30 до 56 дней (8 недель)** — синхронизировано с Context 6.
- Добавлен раздел 4.1 «Точность симуляции» — допустимые расхождения между модельным и реальным газом.
- Добавлен раздел 6.3 «Drawdown в paper trading».
- Добавлен раздел 9.1 «Виртуальный vs reference capital».
- Добавлен раздел 11.1 «Изоляция paper trading от live».

---

## 1. Назначение

Paper trading — обязательный этап перед live-исполнением. Цель — **проверить процедуры, не доходность**.

«Высокая доходность не является критерием успеха paper trading.»

---

## 2. Что проверяется

- работа всей agentic архитектуры;
- срабатывание Risk Agent verdict;
- корректность Execution Cost Model расчётов;
- accuracy симуляции (gas, slippage);
- надёжность мониторинга;
- работа heartbeat-механизма;
- weekly reporting дисциплина.

---

## 3. Продолжительность

**Минимум 56 дней (8 недель).** Не 30 дней — для DeFi с волатильностью APR этого мало.

Расширение возможно, сокращение — нет.

---

## 4. Симуляция

Paper trading использует:
- модельный портфель ($10K virtual capital);
- реальные APY whitelisted протоколов (из DeFiLlama / sky.money / pendle.finance);
- модельный gas (rolling median Etherscan);
- модельный slippage (на основе размера операций и текущей ликвидности).

### 4.1. Точность симуляции

Допустимые расхождения между симулированными и реальными значениями:
- gas: **± 20%**;
- slippage: **± 10%**;
- APY: используется снимок на момент решения, исторический drift учитывается через корректирующие записи.

Если расхождение превышает допустимое → review модели через ADR.

---

## 5. Метрики

- net APY за период (annualized);
- сравнение с baseline (см. Week 0 Baseline);
- количество ребалансировок vs план;
- false positive rate алертов;
- false negative rate (любой реальный инцидент, пропущенный мониторингом → SEV-3).

---

## 6. Критерии успеха paper trading

Все условия — обязательны:
- Net APY ≥ target по уровню капитала из ADR-009;
- Drawdown ≤ 5% годовых (Risk Policy 5);
- ≤ 1 критический инцидент за 8 недель;
- ≤ 10% времени в safe-mode;
- Все weekly reports сформированы без пропусков;
- **Ноль** нарушений Risk Policy и Mode Policy.

### 6.3. Drawdown в paper trading

Те же пороги, что в Risk Policy 5. Превышение в paper — повод для review, не для live запуска.

---

## 7. Точки отказа

Любое из нижеперечисленного **прерывает** paper trading и требует ADR:
- любое нарушение Risk Policy;
- расхождение симуляции > допустимого (4.1);
- coordination failure агентов (Agent Architecture 5.1);
- 2+ false negatives мониторинга.

---

## 8. Weekly cycle в paper

Каждую неделю:
- сформировать Weekly Report по шаблону;
- сверить с baseline;
- зафиксировать lessons learned;
- если необходимо — корректирующий ADR (например, recalibration thresholds).

---

## 9. Capital

### 9.1. Виртуальный vs reference capital

- **Virtual capital:** $10K USDT (модельный, не реальный);
- **Reference capital:** реальный размер портфеля при запуске live (например, $50K);
- метрики (net APY %) — переносимы между virtual и reference;
- абсолютные суммы — нет.

ADR-009 фиксирует target net APY по уровням capital — для будущего reference.

---

## 10. Финальный отчёт paper trading

В конце 8 недель — финальный отчёт с:
- всеми metric vs target;
- список действий и причин;
- список алертов и реакций;
- inсidents и post-mortems;
- финальный вывод: **готово к live** / **требуется ещё цикл** / **отказ от стратегии**.

Финальный отчёт = вход в ADR о live запуске.

---

## 11. Переход в live

Live возможен только после:
- финального отчёта paper trading со статусом «готово»;
- калибровки моделей через ADR (Safety Multiplier, thresholds);
- Tail Risk Reserve размещён;
- Multi-sig setup проверен;
- Hardware wallet setup проверен;
- Append-only log хранилище работает;
- Self-monitoring проверен через test-alert;
- финальное ADR на переход в live.

### 11.1. Изоляция paper trading от live

- paper и live используют **разные кошельки** (не один и тот же EOA);
- paper logs и live logs — в **разных файлах** (`paper.decisions.log`, `live.decisions.log`);
- паспорта стратегий помечают статус: `Paper` или `Active`;
- невозможна случайная подача live-транзакции из paper environment (technical safeguard).

---

## 12. Условия выхода в v1.0

- завершён минимум 1 полный цикл paper trading (8 недель);
- финальный отчёт зафиксирован;
- последовавший live запуск отработал минимум 4 недели;
- модель симуляции откалибрована на сравнении paper vs live.

---

## 13. Статус

Статус: Draft (целевой — Frozen после правок).
