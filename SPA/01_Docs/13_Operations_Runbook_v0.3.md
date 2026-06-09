# 13_Operations_Runbook

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Risk Policy v0.3, Mode Policy v0.3, Whitelist Policy v0.3

Changelog from v0.2:
- Имена файлов в зависимостях актуализированы.
- 3.4 «Совмещение ролей Owner/Operator на Self-Capital» с правилом 24-часовой паузы.
- 4.3 «Лимиты Autopilot»: 1/час, 3/день, 10/неделю, 10% портфеля макс.
- 4.4 «Аварийная остановка Autopilot».
- 6.1 «Процедуры на инциденты доступа».
- 6.2 «Multi-sig requirements».
- 6.3 «Hardware wallet requirements».
- 6.4 «Heartbeat-механизм Owner» (раз в 7 дней).
- 8.1 «Операционные ошибки исполнения».
- 9: append-only хранилище логов и регулярный review.

---

## 1. Цель документа

Operations Runbook описывает, **как именно люди и агенты выполняют операции в SPA**. Не «что выбирать» (это Strategy / Risk Policy), а «как действовать».

---

## 2. Режимы исполнения

- **Manual Mode** — все операции выполняются Owner вручную, после явного approve.
- **Autopilot Mode** — система выполняет операции автономно в строгих рамках.

Default на v0.3 — **Manual Mode**. Autopilot Mode активируется через ADR после 8 недель paper trading.

---

## 3. Роли

### 3.1. Owner
Финальный арбитр риска. Только Owner:
- утверждает ADR;
- может вывести систему из safe-mode;
- активирует/деактивирует Autopilot;
- меняет whitelist через ADR.

### 3.2. Operator
Выполняет операционные действия в рамках политик. На Self-Capital совмещён с Owner.

### 3.3. AI Agent
Программный исполнительный и аналитический слой (см. Agent Architecture).

### 3.4. Совмещение ролей Owner/Operator на Self-Capital

Когда Owner и Operator — одно лицо, действует обязательное правило:
- **24-часовая пауза** между подготовкой ADR и его исполнением (для операций > $10K эквивалента);
- запись в `decisions.log` с timestamps обоих моментов;
- пауза не применяется к защитным выходам SEV-1.

---

## 4. Autopilot

### 4.1. Что разрешено
- ребалансировки внутри whitelisted протоколов;
- защитные выходы по правилам Risk Policy;
- claim rewards.

### 4.2. Что запрещено
- любые операции с не-whitelisted протоколами;
- любые операции, превышающие лимиты Risk Policy;
- изменения политик и whitelist.

### 4.3. Лимиты Autopilot

| Метрика | Лимит |
|---------|-------|
| Операций в час | ≤ 1 |
| Операций в день | ≤ 3 |
| Операций в неделю | ≤ 10 |
| Размер одной операции | ≤ 10% портфеля |
| Накопительный размер за день | ≤ 20% портфеля |

Превышение → autopilot pause + alert Owner.

### 4.4. Аварийная остановка Autopilot

Триггеры:
- Owner вручную (`autopilot stop`);
- любой SEV-1 инцидент;
- утрата связи с любым critical RPC > 1 часа;
- heartbeat Owner просрочен (см. 6.4).

Восстановление — только Owner через ADR `autopilot_resume`.

---

## 5. Decision Flow

См. Agent Architecture раздел 5 для полного описания. Operations Runbook фиксирует только операционные правила.

---

## 6. Безопасность доступа

### 6.1. Процедуры на инциденты доступа

- утеря пароля / приватного ключа → немедленный SEV-1, защитный вывод капитала на cold storage;
- подозрение на компрометацию → safe-mode + ротация всех credentials в течение 24ч;
- успешный фишинг → assume worst-case.

### 6.2. Multi-sig requirements

На этапе Self-Capital:
- **default стратегия:** splitting крупных операций на части ≤ 10% портфеля с интервалом ≥ 24h между частями (multi-sig эффект через временное разделение);
- **дополнительно:** hot/cold wallet split: 80% в cold (требует физического доступа), 20% в hot (operational).

На этапе Fund — обязательный 2-of-3 multi-sig (Owner + доверенное лицо + emergency).

### 6.3. Hardware wallet requirements

- основной operational wallet: hardware wallet (Ledger / Trezor / GridPlus);
- backup seed phrase в 2+ физических локациях;
- regular firmware updates;
- проверка адресов на устройстве для каждой транзакции.

### 6.4. Heartbeat-механизм Owner

Owner обязан подтверждать доступность через системный сигнал «heartbeat» **не реже 1 раза в 7 дней**.

Длительная планируемая недоступность — через ADR `planned_absence` (до 14 дней).

Поведение системы при отсутствии heartbeat — см. Risk Policy 9.1.

---

## 7. Логи

Обязательные логи:
- `decisions.log` — все решения Owner / Strategy Agent
- `trades.log` — все транзакции (включая internal transfers)
- `alerts.log` — все алерты
- `incidents.log` — все инциденты
- `risk.log` — verdict Risk Agent
- `data.log` — снапшоты данных

---

## 8. Операционные процедуры

### 8.1. Операционные ошибки исполнения

- неверный адрес отправки → SEV-1 inсident, не корректирующая транзакция (тогда уже поздно);
- передача с большей суммой → post-mortem + ADR об операционной защите;
- failed transaction → анализ причины, retry только после понимания причины.

---

## 9. Append-only хранилище логов

Все логи дублируются в append-only хранилище:
- невозможность редактирования прошлых записей;
- ротация ключей хранилища ≥ раз в год;
- регулярный review раз в месяц (выборочная сверка).

### 9.1. Pre-Launch Status

(Добавлено в v0.4.5 в рамках Pre-Launch ревью)

| # | Пункт | Статус | Источник |
|---|-------|--------|----------|
| 1 | Risk Policy утверждена через ADR | ✅ ADR-001 | 2026-05-02 |
| 2 | Mode Policy утверждена | ✅ ADR-001 | 2026-05-02 |
| 3 | Whitelist заполнен (Tier 1: 3 протокола) | ✅ ADR-002 | 2026-05-02 |
| 4 | Strategy Passport Stable Lending Core готов | ✅ | 2026-05-02 |
| 5 | Provider stack выбран | ✅ ADR-003 | 2026-05-02 |
| 6 | Hardware wallet setup | ✅ Owner confirmed | 2026-05-02 |
| 7 | Tail Risk Reserve размещён (10% портфеля) | ✅ | 2026-05-02 |
| 8 | Heartbeat-механизм настроен | ✅ 7-дневный | 2026-05-02 |
| 9 | Safe-mode triggers активны | ✅ | 2026-05-02 |
| 10 | Decision Flow проверен sandbox tests | ✅ | 2026-05-02 |
| 11 | Agent boundaries определены | ✅ ADR-001 | 2026-05-02 |
| 12 | Regulatory check выполнен | ✅ OFAC/EU/UN ok | 2026-05-02 |
| 13 | Exit Liquidity Test для Tier 1 | ✅ all < 0.3% | 2026-05-02 |
| 14 | Append-only log хранилище | ⏳ в процессе | до Week 1 |
| 15 | Self-monitoring test-alert | ⏳ в процессе | до Week 1 |

Пункты 14-15 не блокируют старт, но должны быть закрыты до конца Week 1 paper trading.

---

## 10. Условия выхода в v1.0

Operations Runbook переходит в v1.0 после того как:
- завершены 8 недель paper trading в Manual Mode;
- проведён первый цикл Autopilot (минимум 4 недели) без срабатывания лимитов;
- проведён хотя бы один регулярный review логов;
- зафиксирован минимум 1 ADR на основе реального опыта эксплуатации.

---

## 11. Статус и следующие шаги

Статус: Draft (целевой — Frozen после правок и согласования).
