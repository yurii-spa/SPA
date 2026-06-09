# Docs Index

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01

Changelog from v0.2:
- Все статусы приведены к реальному (Draft).
- Раздел 2: ссылка на Context v0.3 раздел 4 вместо дублирования.
- Все таблицы — на v0.3 имена файлов.
- Добавлен раздел 7 «Зависимости и blocker-цепочки».
- Добавлен раздел 8 «ADR (Architecture Decision Records)».
- Раздел 9: PDF в 00_Admin помечены как «historical reference».
- Добавлены условия выхода в v1.0.

---

## 1. Назначение документа

Docs Index — **карта всей документации SPA**. Любой документ не в индексе — не существует.

---

## 2. Иерархия документов

См. Context v0.3 раздел 4. Docs Index не определяет иерархию самостоятельно — он на неё ссылается.

---

## 3. Корневые документы

| ID | Документ | Версия | Статус | Имя файла |
|----|---------|--------|--------|-----------|
| 00 | Context | v0.3 | Draft | 00_Context_v0.3.md |

---

## 4. Политики

| ID | Документ | Версия | Статус | Имя файла |
|----|---------|--------|--------|-----------|
| 02 | Mode Policy | v0.3 | Draft | Mode_Policy_v0.3.md |
| 03 | Risk Policy | v0.3 | Draft | Risk_Policy_v0.3.md |
| 04 | Whitelist Policy | v0.3 | Draft | 04_Whitelist_Policy_v0.3.md |

---

## 5. Operations & Engineering

| ID | Документ | Версия | Статус | Имя файла |
|----|---------|--------|--------|-----------|
| 13 | Operations Runbook | v0.3 | Draft | 13_Operations_Runbook_v0.3.md |
| 14 | Incident Response | v0.3 | Draft | 14_Incident_Response_v0.3.md |
| 15 | Monitoring & Alerts | v0.3 | Draft | 15_Monitoring_and_Alerts_v0.3.md |
| 16 | Data & Signals | v0.3 | Draft | 16_Data_and_Signals_v0.3.md |
| 18 | Agent Architecture | v0.3 | Draft | 18_Agent_Architecture_v0.3.md |

---

## 6. Экономика, исполнение и отчётность

| ID | Документ | Версия | Статус | Имя файла |
|----|---------|--------|--------|-----------|
| 05 | Execution Cost Model | v0.3 | Draft | Execution_Cost_Model_v0.3.md |
| 06 | Accounting & PnL Attribution | v0.3 | Draft | Accounting_and_PnL_v0.3.md |
| 07 | Weekly Reporting Template | v0.3 | Draft | Reporting_Weekly_Template_v0.3.md |
| 08 | Paper Trading & Simulation | v0.3 | Draft | Paper_Trading_and_Simulation_Plan_v0.3.md |

---

## 7. Стратегии

| ID | Документ | Версия | Статус | Имя файла |
|----|---------|--------|--------|-----------|
| 09 | Strategy Passport Template | v0.3 | Draft | Strategy_Passport_Template_v0.3.md |
| 10 | Stable Lending Core Strategy | v0.3 | Draft | Strategy_Passport_Stable_Lending_Core_v0.3.md |

---

## 8. Зависимости и blocker-цепочки

### 8.1. Граф зависимостей

```
Context (00)
  ├── Risk Policy (03)
  │     ├── Mode Policy (02)
  │     ├── Whitelist Policy (04)
  │     └── используется всеми
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

### 8.2. Blocker-цепочки перед paper trading

1. Whitelist Policy раздел 9 заполнен → ✅ через ADR-002;
2. Strategy Passport Stable Lending Core разделы 4.3 и 4.4 заполнены → ✅;
3. Risk Policy утверждена через ADR → ✅ через ADR-001;
4. Operations Runbook утверждён (Heartbeat + Multi-sig) → ✅ через ADR-001;
5. Provider stack выбран → ✅ через ADR-003.

### 8.3. Blocker-цепочки перед live

1. Все блокеры paper (8.2);
2. Завершено 8 недель paper trading;
3. Финальный отчёт со статусом «готово»;
4. Калибровки через ADR;
5. Tail Risk Reserve размещён;
6. Multi-sig setup проверен;
7. Hardware wallet проверен;
8. Append-only log работает;
9. Self-monitoring через test-alert.

---

## 9. ADR (Architecture Decision Records)

ADR — критический класс документов.

**Расположение:** `06_ADR/`
**Именование:** `ADR-YYYY-NNN-короткое_описание.md`

**Список ADR на этапе v0.4.5:**

| ID | Тема | Статус |
|-----|------|--------|
| ADR-2026-001 | Принятие документации SPA v0.3 | Accepted 2026-05-01 |
| ADR-2026-002 | Whitelist Tier 1 протоколы | Accepted 2026-05-01 |
| ADR-2026-003 | Provider stack (Data & Signals) | Accepted 2026-05-02 |
| ADR-2026-004 | Запуск paper trading Stable Lending Core | Accepted 2026-05-02 |
| ADR-2026-005 | Принятие SPA v0.4 | Accepted 2026-05-01 |
| ADR-2026-006 | Расширенный whitelist v0.4 (60%/40% T1/T2) | Accepted 2026-05-01 |
| ADR-2026-007 | Tail Risk Reserve (sUSDS) | Accepted 2026-05-01 |
| ADR-2026-008 | Yearn V3 yvUSDC (v0.4.5) | Accepted 2026-05-03 |
| ADR-2026-009 | Financial Targets Reconciliation | Accepted 2026-05-03 |

Multi-sig setup — покрыт Operations Runbook 6.2 без отдельного ADR.

---

## 10. Документы из 00_Admin (Reference / Historical)

PDF в `00_Admin/`:
- `design_foundation.pdf`
- `docs_architecture.pdf`
- `ai_base_architecture.pdf`
- `roadmap_milestones.pdf`

Привязаны к ChatGPT 5.2 Pro как «архитектору» (февраль 2026), устарели относительно Claude Code / Codex (актуальные инструменты май 2026).

**Рекомендация:** перенести в `00_Admin_Archive/`.

---

## 11. Правила изменений

- любые изменения Frozen документов — **только через ADR**;
- изменение статусов фиксируется в Docs Index первым;
- Docs Index обновляется первым при любом изменении документации;
- при противоречии — авторитет у Context (раздел 4).

---

## 12. Условия выхода в v1.0

Docs Index переходит в v1.0 после того как:
- все нижестоящие документы переведены в Frozen;
- минимум 1 квартальный re-review проведён;
- ADR-trail непрерывный.

---

## 13. Статус

Статус: Draft (целевой — Frozen после правок и Owner-подтверждения всех нижестоящих документов).
