# 15_Monitoring_and_Alerts

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Risk Policy v0.3, Whitelist Policy v0.3, Operations Runbook v0.3, Incident Response v0.3, Agent Architecture v0.3

Changelog from v0.2:
- Имена файлов в зависимостях приведены к актуальным.
- Раздел 3.2 обновлён под новую структуру лимитов Risk Policy v0.3.
- Добавлен класс 3.7 «Portfolio Drawdown Monitoring».
- Добавлен класс 3.8 «Owner Heartbeat Monitoring».
- Добавлен класс 3.9 «Governance & Protocol Updates Monitoring».
- Добавлен класс 3.10 «DeFi-specific Monitoring» (MEV, bridge health, whale movements).
- Добавлен раздел 4.1 «Alert Deduplication and Throttling».
- Добавлен раздел 4.2 «Threshold Calibration» — после 8 недель paper.
- Добавлен раздел 4.3 «Self-monitoring».

---

## 1. Цель документа

Определяет **систему мониторинга и алертинга SPA**: какие метрики отслеживаются, какие пороги считаются опасными и какие действия они триггерят.

Мониторинг **не оптимизирует доходность**, а защищает систему.

---

## 2. Принципы

- early detection > late reaction;
- consistency > completeness;
- false positives ОК; false negatives — нет;
- thresholds откалиброваны на paper trading;
- self-monitoring — мониторинг самого мониторинга.

---

## 3. Классы мониторинга

### 3.1. Asset Health Monitoring
- стейблкоин peg deviation
- TVL changes
- protocol-specific metrics (utilization)

### 3.2. Concentration Limits
Соответствие лимитам Risk Policy 4.1 (трёхуровневая таблица).

### 3.3. Execution Monitoring
- failed transactions
- gas costs vs model
- slippage vs prediction

### 3.4. Data Quality Monitoring
- RPC latency и расхождения
- oracle расхождения
- stale data

### 3.5. Strategy Performance
- фактический vs ожидаемый yield по Strategy Passport
- drift от целевой структуры

### 3.6. Compliance Monitoring
- ежедневная сверка whitelist адресов с sanctions lists
- governance proposals на whitelisted протоколах

### 3.7. Portfolio Drawdown Monitoring
- Daily DD (синхронизировано с Risk Policy 5)
- Weekly DD
- Monthly DD (rolling 30d)
- Annual DD (rolling 365d)

Каждый порог → соответствующее действие.

### 3.8. Owner Heartbeat Monitoring
- последний heartbeat timestamp
- countdown до 7 дней
- escalation на 5-й день (warning), 6-й день (urgent), 7-й день (safe-mode)

### 3.9. Governance & Protocol Updates Monitoring
- новые governance proposals на whitelisted протоколах
- changes in protocol team / multisig signers
- forum activity на крупных obs (forum.aave, forum.skyeco)

### 3.10. DeFi-specific Monitoring
- MEV-related anomalies на наших транзакциях
- bridge health (для cross-chain)
- whale movements в наших протоколах

---

## 4. Управление алертами

### 4.1. Alert Deduplication and Throttling
- одинаковые алерты в течение 1 часа → дедуплицируются (count + first/last timestamp);
- алерты одной severity в течение 15 минут → группируются в digest;
- алерты SEV-1 — НЕ дедуплицируются, всегда индивидуально.

### 4.2. Threshold Calibration
Пороги стартовые (best guess). Калибровка — после 8 недель paper trading:
- false positive rate target: < 5% от всех алертов;
- false negative rate target: 0 (любой пропущенный реальный инцидент → review);
- калибровка фиксируется через ADR.

### 4.3. Self-monitoring
**Кто следит за мониторингом?**
- ежемесячный test-alert (Owner отправляет фиктивный signal — проверяет работу chain);
- heartbeat мониторинга (отдельный процесс проверяет, что monitoring процесс жив);
- если самомониторинг отказал → safe-mode.

---

## 5. Условия выхода в v1.0

Monitoring переходит в v1.0 после того как:
- пороги откалиброваны на 8 неделях paper trading через ADR;
- self-monitoring проверен через минимум 3 test-alert;
- false positive rate < 5%.

---

## 6. Статус и следующие шаги

Статус: Draft (целевой — Frozen после правок).
