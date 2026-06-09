# Reporting Weekly Template

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Accounting & PnL v0.3, Risk Policy v0.3, Mode Policy v0.3, Monitoring & Alerts v0.3, Whitelist Policy v0.3

Changelog from v0.2:
- Исправлено противоречие статуса.
- Добавлен раздел 5.3 «Drawdown за период».
- Добавлен раздел 8.1 «Heartbeat-статус Owner».
- Добавлен раздел 8.2 «Quarterly whitelist re-review».
- Добавлен раздел 14 «Дисциплина отчётности» — ≤48h после конца периода.
- Добавлен раздел 15 «Monthly и Quarterly reports».

---

## 1. Назначение

**Единый и обязательный формат** отчёта по работе SPA.

Если показатель не попал в отчёт — считается, что его **не существует**.

---

## 2. Правило структуры (обязательно)

1) **Факты** (цифры, действия, статусы)
2) **Интерпретации и выводы**

Интерпретации **не могут изменять или смягчать факты**.

---

## 3. Общая информация

- Отчётный период:
- Режим (A / B):
- Стартовый капитал (USDT):
- Конечный капитал (USDT):
- Изменение капитала (USDT / %):
- NAV максимум за период:
- NAV минимум за период:

---

## 4. Executive Summary — ФАКТЫ

- Net PnL за период (USDT):
- Были ли действия: да / нет
- Количество действий:
- Были ли алерты: да / нет (Info / Warning / Critical)
- Статус портфеля на конец периода: Active / Paused / Safe-mode
- Heartbeat Owner: соблюдён / нарушения

---

## 5. Финансовый результат — ФАКТЫ

### 5.1. Net PnL
- За период (USDT):
- С начала теста / запуска (USDT):

### 5.2. Расшифровка
- Realized Yield PnL (USDT):
- Execution Costs (USDT):
- Realized Price PnL (если Режим B):
- Reward Realization PnL (если применимо):

Проверка: Realized Yield − Execution Costs ± Price PnL ± Reward Realization PnL = Net PnL

### 5.3. Drawdown за период
- Daily DD максимум:
- Weekly DD от HWM:
- Monthly DD (rolling 30d):
- Annual DD (rolling 365d):

Если порог Risk Policy 5 превышен — указать явно + реакция.

---

## 6. Бенчмарк — ФАКТЫ

### Режим A
- Бенчмарк: кэш (0% доходности)
- Отклонение от бенчмарка (USDT / %):

### Режим B
- Бенчмарк: hold BTC/ETH в тех же долях
- Результат бенчмарка:
- Отклонение:

---

## 7. Действия за период — ФАКТЫ

Для каждого:
- дата;
- стратегия;
- действие;
- причина (alert / правило);
- ссылка на Execution Cost Model расчёт;
- ссылка на decisions.log entry.

**Если действий не было** — обязательно указать причину бездействия.

---

## 8. Состояние стратегий — ФАКТЫ

Для каждой стратегии на конец периода:
- статус (Active / Paused / Retired);
- доля в портфеле;
- фактический yield за период;
- ожидаемый yield по Strategy Passport;
- отклонение факт/ожидание;
- были ли алерты.

### 8.1. Heartbeat-статус Owner
- последний heartbeat (timestamp);
- максимальный gap heartbeat за период;
- нарушения порогов (если были);
- ADR `planned_absence` действовал: да / нет.

### 8.2. Quarterly whitelist re-review
*Заполняется только в последнюю неделю квартала.*

Для каждого whitelisted протокола:
- по-прежнему ли соответствует Tier 1/2 требованиям;
- governance review результат;
- regulatory check результат;
- решение: оставить / понизить Tier / выйти.

---

## 9. Алерты и инциденты — ФАКТЫ

| Severity | Count | Подробности |
|----------|-------|-------------|
| SEV-1 | | |
| SEV-2 | | |
| SEV-3 | | |
| SEV-4 | | |

Для SEV-1/2 — ссылка на post-mortem.

---

## 10. Состояние мониторинга и данных

- self-monitoring test проведён: да/нет;
- RPC status:
- oracle расхождения:
- DeFiLlama TVL обновлялся:

---

## 11. Owner-комментарии (Интерпретации)

Здесь — только после фактов.

---

## 12. Action items для следующего периода

- ...
- ...

---

## 13. Сравнение с ADR-009 net targets

Соответствует ли net APY текущего периода target по уровню капитала?

---

## 14. Дисциплина отчётности

Отчёт должен быть сформирован **не позднее 48 часов после конца отчётного периода**.

Просрочка > 48h:
- инцидент SEV-4 (систематические просрочки → SEV-3);
- причина фиксируется в отчёте.

---

## 15. Monthly и Quarterly reports

### 15.1. Monthly report

Расширение weekly:
- агрегаты за 4-5 недель;
- сравнение с предыдущим месяцем;
- net APY за месяц annualized vs target;
- review лимитов и порогов.

### 15.2. Quarterly report

Расширение monthly:
- полный whitelist re-review (8.2);
- progress по условиям выхода в v1.0 для всех документов;
- tabletop exercise результат (Incident Response 7);
- review всех ADR за квартал.

---

## 16. Приложения

- ссылки на decisions.log, trades.log, alerts.log за период;
- on-chain ссылки.

Приложения **не могут содержать новую информацию**, отсутствующую в основном отчёте.

---

## 17. Условия выхода в v1.0

- минимум 8 weekly reports без просрочек;
- минимум 1 monthly report;
- минимум 1 quarterly report с полным whitelist re-review;
- минимум 1 tabletop exercise с фиксацией в quarterly.

---

## 18. Статус

Статус: Draft (целевой — Frozen после правок).
