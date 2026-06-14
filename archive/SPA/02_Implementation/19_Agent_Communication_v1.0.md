# 19_Agent_Communication

Project: Smart Passive Aggregator (SPA)
Version: v1.0
Status: Draft
Owner: Юра
Last updated: 2026-05-20
Depends on: 18_Agent_Architecture v0.3, Mode_Policy v0.3, Risk_Policy v0.3

---

## 1. Цель документа

Описывает протокол коммуникации между агентами SPA: транспорт, форматы сообщений, таймауты, обработку сбоев. Является имплементационным дополнением к `18_Agent_Architecture v0.3`, который описывает роли и границы, но не протокол.

---

## 2. Транспортный уровень

### 2.1. Message Bus (основной транспорт)

Все агенты подключены к единой шине сообщений через **asyncio pub/sub**.

Правила:
- Каждый агент публикует события в именованные топики
- Каждый агент подписывается только на те топики, которые нужны для его роли
- Шина не хранит историю — это не очередь задач, это поток событий
- При масштабировании на несколько нод — шина заменяется на **Redis Pub/Sub**

### 2.2. Прямые каналы (быстрый путь)

Для критичных взаимодействий с требованием низкой задержки — прямые синхронные вызовы:

| Канал | Назначение | Таймаут | Fallback |
|---|---|---|---|
| Data → Risk | Проверка аномалии в данных | 500 мс | Данные помечаются `anomaly_suspected: true` |
| Risk → Strategy | Одобрение/отклонение proposal | 500 мс | Auto-deny (fail-closed) |
| Strategy → Execution | Команда на исполнение | 500 мс | Команда отменяется |

Прямые каналы — **дополнение** к шине, не замена. При каждом прямом вызове генерируется событие в шину для логирования.

### 2.3. Топики Message Bus

```
data.snapshot.ready          — Data Agent: новый снапшот данных готов
data.anomaly.detected        — Data Agent: обнаружена аномалия в данных
risk.verdict.allow           — Risk Agent: действие разрешено
risk.verdict.deny            — Risk Agent: действие отклонено
risk.verdict.safe_mode       — Risk Agent: переход в safe-mode
strategy.proposal.created    — Strategy Agent: предложено действие
strategy.proposal.cancelled  — Strategy Agent: предложение отменено
execution.trade.submitted    — Execution Agent: paper trade отправлен
execution.trade.confirmed    — Execution Agent: paper trade подтверждён
monitoring.alert.triggered   — Monitoring Agent: сработал алерт
monitoring.heartbeat         — Monitoring Agent: периодический ping
escalation.owner.required    — любой агент: требуется внимание Owner
```

---

## 3. Формат сообщений

Каждое сообщение в шине — JSON со следующей структурой:

```json
{
  "message_id": "uuid-v4",
  "correlation_id": "uuid-v4",
  "timestamp_utc": "2026-05-20T10:00:00Z",
  "sender": "data_agent | risk_agent | strategy_agent | execution_agent | monitoring_agent",
  "topic": "data.snapshot.ready",
  "version": "1.0",
  "payload": { ... }
}
```

**correlation_id** — идентификатор всей цепочки от сигнала до исполнения. Генерируется первым агентом в цепочке (обычно Monitoring или Data), наследуется всеми последующими сообщениями в рамках одного Decision Flow. Позволяет восстановить полную историю решения в логах.

---

## 4. Жизненный цикл Decision Flow

```
[Monitoring] alert.triggered  (correlation_id: C-001)
      ↓
[Data] snapshot.ready          (correlation_id: C-001)
      ↓
[Strategy] proposal.created    (correlation_id: C-001)
      ↓
[Risk] (прямой канал ← Strategy, timeout 500ms)
      ↓
[Risk] verdict.allow           (correlation_id: C-001)
      ↓
[Execution] trade.submitted    (correlation_id: C-001)
      ↓
[Execution] trade.confirmed    (correlation_id: C-001)
```

Все шаги пишутся в `execution.log` с correlation_id. Полная цепочка восстанавливается по одному ID.

---

## 5. CEO Agent и оркестрация

CEO Agent (Claude Sonnet 4.6) — **надстройка над стандартным Decision Flow**, не замена ему.

CEO Agent используется для:
- Анализа сложных ситуаций, где детерминированные правила не дают однозначного ответа
- Ответов на голосовые/текстовые запросы Owner
- Финального одобрения действий вне стандартного Autopilot-режима (Mode B)

CEO Agent **не имеет права**:
- Обходить Risk Agent
- Изменять Risk Policy или Whitelist напрямую
- Инициировать исполнение без Risk verdict allow

Когда CEO Agent вовлечён — его решение оформляется как `strategy.proposal.created` и проходит стандартный Risk-check.

### 5.1. CEO offline / таймаут

Если CEO Agent не отвечает в течение **60 секунд** на запрос, требующий его участия:
- Для рутинных действий в Autopilot — Decision Flow продолжается без него
- Для escalation — действие автоматически переходит в `deny` (fail-closed)
- Escalation помещается в очередь с меткой `ceo_timeout`, Owner уведомляется при следующем Heartbeat

---

## 6. Обработка сбоев

| Ситуация | Поведение |
|---|---|
| Агент не отвечает >30 сек | Safe-mode + `escalation.owner.required` |
| Прямой канал timeout 500 мс | Fallback (см. 2.2) |
| Расхождение данных между агентами | Safe-mode + manual review |
| Loop detected (>3 итерации) | Safe-mode + `loop_detected` метка + cooldown 1ч |
| Risk Agent недоступен | Все действия заблокированы (fail-closed) |

---

## 7. Безопасность коммуникации

- Все входящие данные из внешних источников (on-chain, API) считаются **untrusted**
- Внешние текстовые данные не передаются напрямую в LLM-агенты
- В LLM-агенты подаётся только **structured data** (числа, enum статусы)
- Risk Agent получает только числа и enum — никакого текста
- Каждое сообщение логируется в append-only лог
