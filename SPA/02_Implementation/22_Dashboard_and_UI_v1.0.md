# 22_Dashboard_and_UI

Project: Smart Passive Aggregator (SPA)
Version: v1.0
Status: Draft
Owner: Юра
Last updated: 2026-05-20
Depends on: 18_Agent_Architecture v0.3, 19_Agent_Communication v1.0, 15_Monitoring_and_Alerts v0.3

---

## 1. Назначение

Dashboard — интерфейс Owner для наблюдения за системой, постановки задач и анализа результатов. Не заменяет Operations Runbook — дополняет его визуальным слоем.

---

## 2. Технологический стек

| Компонент | Технология |
|---|---|
| Frontend | React + TypeScript |
| Agent UI protocol | AG-UI Protocol (CopilotKit) |
| Realtime обновления | WebSocket (AgentStream) |
| Голосовой интерфейс | OpenAI Realtime API |
| Computer-use (DEX) | browser-use |
| Бэкенд API | FastAPI (Python) |

---

## 3. Структура интерфейса

### 3.1. Вкладка TEAM — состояние агентов

- Карточка каждого агента: имя, модель, статус (ACTIVE / BUSY / IDLE / ERROR)
- Pixel-art аватар агента (уникальный для каждой роли)
- Текущая задача агента
- Activity Log — поток событий из Message Bus в реальном времени

Агенты: CEO, Data, Risk, Strategy, Execution, Monitoring.

### 3.2. Вкладка BOARD — Kanban

Задачи системы в трёх колонках:
- **BACKLOG** — запланированные Decision Flow
- **IN PROGRESS** — активные цепочки с correlation_id
- **DONE** — завершённые (последние 50)

Каждая карточка: ID задачи, агент-исполнитель, статус, время.

### 3.3. Вкладка METRICS — результаты

**Portfolio Dashboard:**
- Текущий Net APY (annualized)
- PnL: total, 7d, 30d
- Win rate, Sharpe ratio, Max drawdown
- График equity curve: стратегия vs baseline

**Strategy Comparison:**
- Таблица всех стратегий в Sandbox с метриками
- Прогресс-бары 8-недельного paper test
- Сортировка по PnL, Sharpe, drawdown

**Risk Dashboard:**
- Текущий Risk Score
- Концентрация по протоколам (pie chart)
- VaR текущий vs лимит
- Статус Heartbeat

### 3.4. Вкладка STRATEGY SANDBOX — управление стратегиями

- Список всех стратегий с статусами (DRAFT / PAPER_TESTING / REVIEW / PROMOTED / ELIMINATED)
- Визуальный редактор параметров стратегии:
  - Выбор протоколов (из whitelist)
  - Слайдеры: max position size, stop loss
  - Конструктор условий входа (поле + оператор + значение)
  - Rebalance frequency
- Кнопки: SAVE / ▶ START PAPER TEST / BACKTEST
- Результаты backtest: equity curve vs SPY/ETH baseline, статистика

### 3.5. Вкладка CHAT — диалог с CEO Agent

- Текстовый/голосовой диалог с CEO Agent
- CEO Agent отвечает на вопросы о статусе, метриках, решениях
- Owner может давать задачи через интерфейс

---

## 4. Голосовой интерфейс

Реализован через **OpenAI Realtime API**.

**Разрешённые голосовые команды:**
- Запрос статуса: "Какой текущий PnL?", "Что сейчас делает Data Agent?"
- Запрос метрик: "Покажи результаты за неделю"
- Постановка задачи CEO: "Проанализируй возможности на Pendle"
- Запрос на ревью стратегии

**Запрещены голосом (только через UI с подтверждением):**
- Изменение Risk Policy лимитов
- Изменение Whitelist
- Изменение параметров стратегии
- Активация live-режима
- Любые действия с реальным капиталом

Причина: голосовые команды — потенциальный вектор misissue. Изменение конфигурации должно быть осознанным действием через UI.

---

## 5. Computer-use (browser-use)

Используется для взаимодействия с DEX-интерфейсами, которые не предоставляют API.

**Ограничения:**
- Только для чтения данных (prices, liquidity) в paper trading фазе
- Исполнение через browser-use запрещено до отдельного ADR
- Любые browser-use сессии логируются полностью

---

## 6. Безопасность UI

- Dashboard доступен только локально (localhost) или через VPN
- Все изменения конфигурации требуют явного подтверждения (double-click / confirm dialog)
- Audit log всех действий Owner через UI
- Голосовые команды транскрибируются и логируются
