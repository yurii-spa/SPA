# 15_Monitoring_and_Alerts

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Risk Policy v0.3, Whitelist Policy v0.3, Operations Runbook v0.3, Incident Response v0.3, Agent Architecture v0.3

Changelog from v0.2:
- Имена файлов в зависимостях приведены к актуальным.
- Раздел 3.2 обновлён под новую структуру лимитов Risk Policy v0.3 (целевая / максимальная / жёсткая граница).
- Добавлен класс 3.7 «Portfolio Drawdown Monitoring» (синхронизирован с Risk Policy 5).
- Добавлен класс 3.8 «Owner Heartbeat Monitoring» (синхронизирован с Risk Policy 9.1 и Operations Runbook 6.4).
- Добавлен класс 3.9 «Governance & Protocol Updates Monitoring».
- Добавлен класс 3.10 «DeFi-specific Monitoring» (MEV, bridge health, whale movements).
- Добавлен раздел 4.1 «Alert Deduplication and Throttling».
- Добавлен раздел 4.2 «Threshold Calibration» — пороги стартовые, калибровка после 8 недель.
- Добавлен раздел 4.3 «Self-monitoring» — кто следит за мониторингом.
- Добавлены условия выхода в v1.0.

---

## 1. Цель документа

Этот документ определяет **систему мониторинга и алертинга SPA**: какие метрики отслеживаются, какие пороги считаются опасными и какие действия они триггерят.

Цель мониторинга:
- раннее выявление рисков;
- предотвращение необратимых потерь;
- автоматическая эскалация в safe-mode;
- снижение зависимости от ручного контроля.

Мониторинг **не оптимизирует доходность**, а защищает систему.

---

## 2. Общие принципы мониторинга

- мониторинг непрерывен;
- отсутствие сигнала **не означает** отсутствие риска;
- при сомнении выбирается более консервативное действие;
- алерты имеют приоритет над стратегиями;
- автоматические алерты могут останавливать Autopilot;
- любые пороги трактуются как **стоп-факторы**, а не рекомендации;
- пороги — стартовые значения, подлежат калибровке (см. 4.2).

---

## 3. Классы мониторинга

### 3.1. Data Integrity Monitoring

Отслеживаемые метрики:
- расхождение цен между источниками (%);
- задержка обновления данных;
- отсутствие данных;
- неконсистентность TVL / balances.

Пороги:
- price deviation > 1% → degraded;
- price deviation > 3% → broken;
- delay > 2 blocks → degraded;
- delay > 5 blocks → broken.

Действия:
- degraded → уведомление + блок стратегий, зависящих от данных;
- broken → Autopilot OFF + safe-mode.

### 3.2. Risk & Exposure Monitoring

Использует трёхуровневую структуру лимитов из Risk Policy 4.1 (целевая / максимальная / жёсткая граница).

Отслеживаемые метрики:
- доля стратегии в портфеле;
- доля одного протокола;
- доля одного актива;
- доля волатильных активов (Режим B);
- лимиты по типу риска (Risk Policy 4.2).

Пороги:
- ≥ 80% от **целевой** доли → Info (плановый ребаланс может быть актуален);
- ≥ 100% **целевой** до 100% **максимальной** → Warning;
- ≥ 100% **максимальной** до 100% **жёсткой границы** → block новых операций;
- > 100% **жёсткой границы** → инцидент + safe-mode.

### 3.3. Liquidity Monitoring

Отслеживаемые метрики:
- глубина ликвидности выхода;
- slippage при моделируемом выходе (см. Whitelist Policy 6.1);
- скорость падения TVL протокола;
- on-chain outflows;
- utilization rate в lending-протоколах.

Пороги:
- ожидаемое slippage > 1% → alert;
- ожидаемое slippage > 2% → block новых входов;
- ожидаемое slippage > 5% → safe-mode для соответствующей стратегии;
- TVL drop > 20% / 24h → safe-mode;
- utilization > 95% → block новых входов в lending.

### 3.4. Execution Monitoring

Отслеживаемые метрики:
- gas price volatility;
- failed / reverted transactions;
- pending time;
- фактическое проскальзывание;
- chain reorg detection.

Пороги:
- gas spike > 2x rolling 30d median → alert;
- gas spike > 10x rolling 30d median → block всех некритичных операций (panic gas);
- > 3 failed tx подряд → Autopilot OFF;
- slippage > ожидаемого на 1% → block стратегии;
- chain reorg глубиной > 5 blocks → пауза до подтверждения.

### 3.5. Strategy Performance Monitoring

Отслеживаемые метрики:
- отклонение фактического yield от ожидаемого;
- отрицательный net yield;
- рост execution cost относительно yield.

Пороги:
- net yield < 0 → alert;
- net yield < 0 два периода подряд → freeze стратегии (status: Paused);
- execution cost > 30% yield → block ребалансов;
- фактический yield ниже ожидаемого на 50%+ за 4+ недели → mandatory review стратегии.

### 3.6. AI & Automation Monitoring

Отслеживаемые метрики:
- частота рекомендаций;
- повторяющиеся решения;
- конфликты с Risk Agent;
- ошибки логики и деградация качества решений;
- срабатывание лимитов Autopilot (Operations Runbook 4.3).

Пороги:
- повторяющиеся рекомендации без изменения входных данных → alert;
- конфликт с Risk Agent → block;
- деградация качества решений → Autopilot OFF;
- превышение лимитов Autopilot → safe-mode.

### 3.7. Portfolio Drawdown Monitoring

Синхронизировано с Risk Policy 5. Drawdown в USDT-эквиваленте от исторического максимума NAV.

| Метрика | Порог | Действие |
|---------|-------|----------|
| Daily DD | ≥ 0.5% | Warning + алерт Owner |
| Weekly DD | ≥ 1% | Critical + safe-mode |
| Monthly DD | ≥ 1.5% | Critical + global stop |
| Annual DD (rolling 12m) | > 2% | mandatory review Risk Policy через ADR |

Drawdown в Режиме B считается отдельно по yield-составляющей и price-составляющей; safe-mode триггерится только yield-просадкой (price PnL — естественная волатильность экспозиции).

### 3.8. Owner Heartbeat Monitoring

Синхронизировано с Risk Policy 9.1 и Operations Runbook 6.4.

| Время с последнего heartbeat | Действие |
|-----------------------------|----------|
| 0–7 дней | штатный режим |
| 7–10 дней | Info-алерт «Owner heartbeat overdue» |
| 10–14 дней | Warning + автоматический safe-mode |
| 14+ дней | Critical + global stop, all-cash |

Heartbeat не требуется при оформленном ADR `planned_absence` (до 14 дней).

Восстановление heartbeat **не отменяет** safe-mode автоматически — отмена только Owner вручную через ADR.

### 3.9. Governance & Protocol Updates Monitoring

Синхронизировано с Whitelist Policy 5.

Отслеживаемые метрики:
- новые governance proposals в whitelisted-протоколах;
- результаты голосований;
- концентрация voting power (top-10 holders);
- изменение admin/multisig состава;
- timelock-события (executed / canceled changes).

Пороги:
- concentration top-1 holder > 50% voting power → alert;
- malicious-flag proposal (от риск-сервисов или сообщества) → Critical, block новых входов;
- успешный malicious proposal → инцидент 2.1, safe-mode и оценка экспозиции;
- изменение admin без timelock → инцидент 2.1.

### 3.10. DeFi-specific Monitoring

Метрики, специфичные для DeFi 2026:

| Класс | Метрика | Порог | Действие |
|-------|---------|-------|----------|
| MEV exposure | sandwich-able size | размер позиции > 10% pool depth | block операции, использовать private mempool |
| Bridge health | задержки и аномалии bridge | задержка > 4x baseline | alert + проверка экспозиции |
| Whale movements | крупные выводы из whitelisted-протокола | top-10 holder вывел > 20% | alert + ускорение review |
| Stablecoin redemption | redemption rate ↑↑ | > 5x baseline за 24h | alert + проверка depeg-risk |

---

## 4. Каналы алертинга и эскалация

Уровни алертов:
- **Info** — логирование, без действий;
- **Warning** — уведомление Owner/Operator;
- **Critical** — немедленный safe-mode.

Правила:
- Critical алерт имеет абсолютный приоритет;
- эскалация не отменяется вручную без ADR;
- все алерты фиксируются в `alerts.log`.

### 4.1. Alert Deduplication and Throttling

Чтобы избежать alert fatigue:

- одинаковые алерты в окне **30 минут** агрегируются в один canonical алерт с counter «(replays: N)»;
- алерты Warning-уровня по одному и тому же триггеру в окне **24 часа** агрегируются в один summary;
- **Critical-алерты не агрегируются** — каждый Critical уведомляет отдельно;
- если одна и та же метрика триггерит >10 алертов в час → автоматический mandatory review порога этой метрики (она сломана или порог неверный).

### 4.2. Threshold Calibration

Все пороги в этом документе — **стартовые значения**, подлежат калибровке после периода реальной эксплуатации.

Правила калибровки:
- калибровка после 8 недель paper trading;
- следующие калибровки — каждые 12 недель live-эксплуатации;
- калибровка через ADR с обоснованием на основе данных;
- **целевая частота Warning-алертов**: 1-3 в неделю (если больше — пороги слишком чувствительны, если ноль — слишком грубые);
- Critical-алерты в идеале — 0 за квартал.

### 4.3. Self-monitoring

Кто следит за самим мониторингом:
- monitoring-система отправляет heartbeat-сигнал каждые **5 минут**;
- отсутствие heartbeat **15+ минут** → Critical алерт через резервный канал;
- двойной мониторинг: если основной мониторинг упал — резервный замечает;
- Owner раз в неделю проверяет факт работы мониторинга через test-alert (отправка специального синтетического сигнала и проверка получения).

Расхождение основного и резервного мониторинга — **критический инцидент**.

---

## 5. Связь с Incident Response

Любой Critical алерт:
- автоматически инициирует Incident Response;
- создаёт запись в `incidents.log`;
- блокирует Autopilot до ручного подтверждения Owner;
- проходит triage по Incident Response 3.1 с автоматической первичной классификацией severity.

Маппинг алертов в severity (стартовые значения, подлежат калибровке):

| Класс алерта | Базовая severity |
|--------------|-----------------|
| Critical из 3.1 (data broken) | SEV-2 |
| Critical из 3.2 (жёсткая граница лимита) | SEV-1 |
| Critical из 3.3 (TVL drop, slippage) | SEV-2 |
| Critical из 3.7 (monthly DD ≥ 5%) | SEV-1 |
| Critical из 3.8 (heartbeat 14+ дней) | SEV-1 |
| Critical из 3.9 (malicious governance) | SEV-1 |
| Critical из 3.10 (bridge issue) | SEV-2 |

---

## 6. Ограничения документа

Этот документ:
- не гарантирует отсутствие инцидентов;
- не описывает источники данных (см. Data & Signals);
- не определяет стратегии и лимиты.

Он фиксирует **что мониторить и когда останавливать систему**.

---

## 7. Условия выхода в v1.0

Monitoring & Alerts переходит в v1.0 после того как:
- завершено минимум 8 недель paper trading с активным мониторингом;
- проведена первая калибровка порогов через ADR;
- проведено минимум 4 test-alert проверки self-monitoring;
- частота Warning-алертов вышла на устойчивые 1-3 в неделю.

---

## 8. Статус и контроль изменений

Статус: Draft (целевой — Frozen после правок и согласования).

Любые изменения данного документа допускаются **только через ADR**.

Для перевода в Frozen v0.3:
- подтвердить пороги (разделы 3.1–3.10) — Owner;
- подтвердить heartbeat-интервалы (3.8) — Owner;
- зафиксировать решение через ADR.
