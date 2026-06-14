# 18_Agent_Architecture

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Context v0.3, Mode Policy v0.3, Risk Policy v0.3, Whitelist Policy v0.3, Operations Runbook v0.3, Incident Response v0.3, Data & Signals v0.3, Monitoring & Alerts v0.3

Changelog from v0.2:
- Имена файлов в зависимостях приведены к актуальным.
- Добавлен раздел 3.1 «Mapping на современные фреймворки» (LangGraph, OpenAI Agents SDK, MCP).
- Добавлен раздел 3.2 «Deterministic vs LLM-based» — Risk Agent и Execution Agent **никогда не LLM**.
- Для каждого агента в разделе 4 добавлены явные tool boundaries.
- Добавлен пункт 4.6 «Memory & Knowledge Agent» (опциональный).
- Добавлен раздел 5.1 «Coordination failures».
- Добавлен раздел 5.2 «Anti-loop guards».
- Добавлен раздел 6.1 «Защита от prompt injection и agentic attacks».
- Добавлены условия выхода в v1.0.

---

## 1. Цель документа

Описывает **архитектуру ИИ-агентов SPA**: их роли, зоны ответственности, границы автономности и взаимодействие с политиками и операционными контурами.

ИИ в SPA — это **исполняющий и аналитический слой**, а не субъект риска.

Агенты — это **программные модули**, не люди.

---

## 2. Принципиальные ограничения

- политики выше агентов и обязательны к исполнению;
- агент не может изменять правила (policies) и whitelist;
- агент не владеет капиталом и не принимает риск на себя;
- агент не имеет прямого доступа к приватным ключам;
- любое действие агента должно быть объяснимо задним числом;
- отсутствие действия — допустимый результат.

Ни один агент не имеет права инициировать действия вне разрешённого Decision Flow.

---

## 3. Состав агентов

1) Data Agent
2) Risk Agent
3) Strategy Agent
4) Execution Agent
5) Monitoring & Alert Agent
6) Memory & Knowledge Agent (опциональный)

### 3.1. Mapping на современные фреймворки

Архитектура SPA соответствует **orchestrator pattern**:
- **Risk Agent** = gate / orchestrator;
- остальные — specialists с узкой зоной ответственности;
- handoff — только через Decision Flow;
- state management: read-only shared state, mutations через logs + Risk verdict;
- tool integration: рекомендуется **MCP (Model Context Protocol)**.

Совместимые фреймворки:
- LangGraph
- OpenAI Agents SDK
- прямая реализация без фреймворка

### 3.2. Deterministic vs LLM-based — критическое решение

| Агент | Реализация | Обоснование |
|-------|-----------|-------------|
| **Risk Agent** | **deterministic (НЕ LLM)** | LLM можно «уговорить» через prompt injection. Risk Agent — последняя линия защиты. |
| **Execution Agent** | **deterministic (НЕ LLM)** | LLM не должен иметь возможность подписать транзакцию. |
| Data Agent | смешанный | on-chain — детерминирован; парсинг текста — LLM |
| Strategy Agent | LLM-based | анализ вариантов — для LLM |
| Monitoring & Alert Agent | смешанный | пороги — детерминированы; классификация — может быть LLM |
| Memory & Knowledge Agent | LLM-based | retrieval и контекст |

**Risk Agent НИКОГДА не реализуется как LLM.** Это абсолютное правило этого документа.

---

## 4. Роли агентов

### 4.1. Data Agent
- Задачи: сбор on-chain/off-chain данных, агрегация, проверка целостности, выявление аномалий.
- Tools: read-only on-chain RPC, off-chain APIs (DeFiLlama, security feeds), no transactions.

### 4.2. Risk Agent
- Задачи: проверка предложенных действий против Risk Policy + Mode Policy + Whitelist.
- Tools: **read-only** access к state, политики как файлы; **NO transactions, NO API calls к внешним сервисам**.
- Implementation: deterministic code with explicit rules; единственный verdict — allow/deny/safe-mode.

### 4.3. Strategy Agent
- Задачи: анализ возможностей yield, предложение ребалансировок.
- Tools: read-only on data, simulation tools, no transactions.
- Не имеет права принимать решение без Risk Agent approval.

### 4.4. Execution Agent
- Задачи: подготовка и подача транзакций после Risk Agent allow.
- Tools: transaction signing (через прокси / hardware wallet), simulation, no policy modification.
- Implementation: deterministic.

### 4.5. Monitoring & Alert Agent
- Задачи: continuous monitoring per Monitoring & Alerts; генерация алертов.
- Tools: read-only на все источники, write только в alerts.log и incidents.log.

### 4.6. Memory & Knowledge Agent (опциональный)
- Задачи: long-term memory, retrieval контекста (прошлые инциденты, post-mortems, ADR).
- Tools: read-only на logs и ADR; write только в memory.log.
- Не имеет права исполнять операции; используется как resource другими агентами.

---

## 5. Decision Flow

Стандартный поток принятия решения:

1. **Data Agent** собирает данные → snapshot.
2. **Monitoring Agent** проверяет триггеры → если есть alert → инициирует Decision Flow.
3. **Strategy Agent** анализирует варианты → предлагает действие.
4. **Risk Agent** проверяет против политик → **allow** или **deny** (или safe-mode).
5. Если allow → **Execution Agent** подаёт транзакцию.
6. Все события → logs.

### 5.1. Coordination failures
- расхождение verdict между агентами → safe-mode по умолчанию;
- timeout одного агента (>30 сек) → safe-mode;
- shared state mismatch → safe-mode + manual review.

### 5.2. Anti-loop guards
- максимум **3 итерации** в одном Decision Flow цикле;
- на 4-й итерации → escalation Owner с пометкой `loop_detected`;
- cooldown 1 час на повторный Decision Flow по тому же триггеру.

---

## 6. Безопасность

### 6.1. Защита от prompt injection и agentic attacks

В DeFi 2026 prompt injection — реальная угроза.

Правила:
1. Все внешние тексты — **untrusted user input**, не инструкции;
2. Внешние тексты **никогда** не передаются напрямую в системный промт LLM-агента;
3. В LLM-агенты подаётся только **structured data** (числа, статусы, classification labels);
4. Если нужно извлечь смысл из текста — через preprocessing слой со строгой схемой выхода + проверка на anomalies;
5. **Risk Agent** не имеет text-based входов вообще (только числа и enum);
6. Любое «решение» от LLM-агента проходит через Risk Agent для верификации;
7. **Sandbox-тесты:** перед deployment каждого LLM-агента проводится jailbreak-resistance test.

---

## 7. Логи и объяснимость

Обязательные логи:
- `data.log`, `risk.log`, `strategy.log`, `execution.log`, `alerts.log`, `memory.log` (если применимо)

Инциденты → `incidents.log`. Все логи дублируются в append-only хранилище (Operations Runbook 9).

---

## 8. Ограничения документа

Этот документ:
- не описывает конкретные модели ИИ (Claude / GPT и т.д.);
- не описывает реализацию;
- не определяет качество предсказаний.

Он фиксирует **границы и роли**, а не эффективность алгоритмов.

---

## 9. Условия выхода в v1.0

Agent Architecture переходит в v1.0 после того как:
- утверждён конкретный фреймворк через ADR;
- проведены sandbox-тесты на jailbreak-устойчивость для всех LLM-агентов;
- 8 недель paper trading с активной агентской системой;
- проверены coordination failure handling и anti-loop guards в реальных условиях.

---

## 10. Статус и контроль изменений

Статус: Draft (целевой — Frozen после правок и согласования).
