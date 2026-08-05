# Docs_Index

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01

Changelog from v0.2:
- Все статусы приведены в соответствие с реальным состоянием документов после v0.3 ревью.
- Раздел 2 «Иерархия приоритетов» обновлён — теперь ссылается на Context v0.3 раздел 6, не дублирует.
- Все таблицы обновлены на v0.3 имена файлов.
- Добавлен раздел 7 «Зависимости и blocker-цепочки».
- Добавлен раздел 8 «ADR (Architecture Decision Records)».
- Раздел про методологию и планирование уточнён — PDF из 00_Admin помечены как «historical reference, потенциально устаревшие».
- Добавлены условия выхода индекса в v1.0.

---

## 1. Назначение документа

Docs_Index — это **единая карта документации SPA** и **единственный источник истины** по наличию, статусам и зависимостям документов проекта.

Любой документ, не указанный в этом индексе, считается **не существующим** для SPA.

---

## 2. Принципы работы с документацией

- каждый документ имеет уникальный ID, версию и статус;
- документы со статусом `Frozen` не изменяются без ADR;
- документы со статусом `Draft` и `Review` допускают изменения;
- зависимости обязательны к указанию;
- противоречия решаются через документы более высокого уровня (см. Context v0.3 раздел 6 «Иерархия документации»);
- Docs_Index **не дублирует иерархию** — он отражает её и список фактических документов.

---

## 3. Статусы документов

- **Draft** — документ в разработке, активно меняется;
- **Review** — логика согласована, идёт финальная проверка перед заморозкой;
- **Frozen** — документ зафиксирован, изменения только через ADR;
- **Archived** — документ выведен из эксплуатации, сохраняется для истории.

После цикла v0.3 ревью **все ключевые документы находятся в статусе Draft** до утверждения Owner и формирования соответствующих ADR.

---

## 4. Ядро системы (required for live)

| ID | Документ | Версия | Статус | Актуальное имя файла |
|----|---------|--------|--------|----------------------|
| 00 | Context | v0.3 | Draft | 00_Context_v0.3_DRAFT.md |
| 02 | Mode Policy | v0.3 | Draft | Mode_Policy_v0.3_DRAFT.md |
| 03 | Risk Policy | v0.3 | Draft | Risk_Policy_v0.3_DRAFT.md |
| 04 | Whitelist Policy | v0.3 | Draft | 04_Whitelist_Policy_v0.3_DRAFT.md |
| 13 | Operations Runbook | v0.3 | Draft | 13_Operations_Runbook_v0.3_DRAFT.md |
| 14 | Incident Response | v0.3 | Draft | 14_Incident_Response_v0.3_DRAFT.md |
| 15 | Monitoring & Alerts | v0.3 | Draft | 15_Monitoring_and_Alerts_v0.3_DRAFT.md |
| 16 | Data & Signals | v0.3 | Draft | 16_Data_and_Signals_v0.3_DRAFT.md |
| 18 | Agent Architecture | v0.3 | Draft | 18_Agent_Architecture_v0.3_DRAFT.md |

---

## 5. Экономика, исполнение и отчётность

| ID | Документ | Версия | Статус | Актуальное имя файла |
|----|---------|--------|--------|----------------------|
| 05 | Execution Cost Model | v0.3 | Draft | Execution_Cost_Model_v0.3_DRAFT.md |
| 06 | Accounting & PnL Attribution | v0.3 | Draft | Accounting_and_PnL_Attribution_Model_v0.3_DRAFT.md |
| 07 | Weekly Reporting Template | v0.3 | Draft | Reporting_Weekly_Template_v0.3_DRAFT.md |
| 08 | Paper Trading & Simulation | v0.3 | Draft | Paper_Trading_and_Simulation_Plan_v0.3_DRAFT.md |

---

## 6. Стратегии

| ID | Документ | Версия | Статус | Актуальное имя файла |
|----|---------|--------|--------|----------------------|
| 09 | Strategy Passport Template | v0.3 | Draft | Strategy_Passport_Template_v0.3_DRAFT.md |
| 10 | Stable Lending Core Strategy | v0.3 | Draft | Strategy_Passport_Stable_Lending_Core_v0.3_DRAFT.md |

---

## 7. Зависимости и blocker-цепочки

### 7.1. Граф зависимостей (упрощённый)

```
Context (00)
  ├── Risk Policy (03)
  │     ├── Mode Policy (02)
  │     ├── Whitelist Policy (04)
  │     └── используется всеми остальными
  ├── Operations Runbook (13)
  │     ├── Incident Response (14)
  │     └── Agent Architecture (18)
  ├── Data & Signals (16)
  │     └── Monitoring & Alerts (15)
  ├── Accounting & PnL (06)
  │     ├── Reporting Weekly (07)
  │     └── Execution Cost Model (05)
  ├── Strategy Passport Template (09)
  │     └── Stable Lending Core (10)
  └── Paper Trading Plan (08)
        └── зависит почти от всех
```

### 7.2. Blocker-цепочки перед paper trading

Paper trading **не может быть запущен**, пока:

1. **Whitelist Policy раздел 9.1 не заполнен** — нужны утверждённые Tier 1 протоколы.
2. **Strategy Passport Stable Lending Core разделы 4.3 и 4.4 не заполнены** — governance/oracle/regulatory checks для конкретных протоколов.
3. **Risk Policy не утверждена** через ADR — лимиты должны быть финализированы.
4. **Operations Runbook не утверждён** — Heartbeat-механизм и Multi-sig procedures должны быть настроены.
5. **Provider stack для Data & Signals не выбран** — конкретные RPC, oracle, indexer.

Эти 5 блокеров — **минимально необходимый набор** перед стартом paper trading.

### 7.3. Blocker-цепочки перед live

Live **не может быть запущен**, пока:

1. Завершены все блокеры paper trading (раздел 7.2);
2. Завершено минимум **8 недель paper trading** (Paper Trading Plan 9);
3. Сформирован финальный отчёт paper trading с выводом «готово»;
4. Калибровки моделей проведены через ADR;
5. Tail Risk Reserve размещён (Risk Policy 10);
6. Multi-sig setup проверен (Operations Runbook 6.2);
7. Hardware wallet setup проверен (Operations Runbook 6.3);
8. Append-only log хранилище работает (Operations Runbook 9);
9. Self-monitoring проверен через test-alert (Monitoring & Alerts 4.3).

---

## 8. ADR (Architecture Decision Records)

ADR — критический класс документов, фиксирующий все значимые решения.

**Расположение:** `06_ADR/`
**Именование:** `ADR-YYYY-NNN-короткое_описание.md`
(пример: `ADR-2026-001-adopt_risk_policy_v0_3.md`)

**Минимальное содержимое ADR:**
- Контекст (что произошло, какая ситуация);
- Решение (что было принято);
- Альтернативы (что рассматривалось);
- Последствия (что меняется, какие риски);
- Дата и ответственный (Owner).

**Список ожидаемых ADR на этапе v0.3 → Frozen:**

| ID | Тема | Статус |
|-----|------|--------|
| TBD | Принятие Risk Policy v0.3 | Не создан |
| TBD | Принятие Mode Policy v0.3 | Не создан |
| TBD | Включение протоколов в Tier 1 whitelist | Не создан (блокер paper trading) |
| TBD | Утверждение Provider stack (Data & Signals) | Не создан |
| TBD | Утверждение Multi-sig setup | Не создан |
| TBD | Запуск Paper trading для Stable Lending Core | Не создан |

ADR создаются последовательно по мере утверждения соответствующих документов.

---

## 9. Методология и планирование (Reference / Historical)

PDF-файлы в `00_Admin/`:

| Документ | Статус | Примечание |
|---------|--------|-----------|
| `design_foundation.pdf` | Reference / Historical | привязан к ChatGPT 5.2 Pro как «архитектору», требует обновления |
| `docs_architecture.pdf` | Reference / Historical | устарел относительно v0.3 структуры |
| `ai_base_architecture.pdf` | Reference / Historical | устарел относительно Claude Code / Codex GPT-5.5 |
| `roadmap_milestones.pdf` | Reference / Historical | таймлайн февраля 2026, требует пересмотра |

Эти документы **не используются** в operational decision-making. Они сохраняются как историческая справка о принятых ранее архитектурных решениях.

**Рекомендация:** перенести в `00_Admin_Archive/` после v0.3 финализации, чтобы не путать с активными документами.

---

## 10. Правила изменений

- любые изменения Frozen-документов — **только через ADR**;
- изменение статусов фиксируется в Docs_Index первым;
- Docs_Index **обновляется первым** при любом изменении документации;
- при противоречии между Docs_Index и каким-либо документом — Docs_Index не является arbitrary; авторитет — у Context (раздел 6 «Иерархия документации»).

---

## 11. Условия выхода в v1.0

Docs_Index переходит в v1.0 после того как:
- все документы в разделах 4, 5, 6 переведены в Frozen v0.3;
- все blocker-цепочки раздела 7 разрешены;
- сформированы все ADR раздела 8;
- проведено первое quarterly re-review всех whitelisted-протоколов с фиксацией в Docs_Index.

---

## 12. Статус документа

Статус: Draft (целевой — Frozen после v0.3 финализации всех остальных документов).

Любые изменения данного документа допускаются **только через ADR**.
