> **IMPORTANT — before working on this repository, read [`PROJECT_CONTROL/00_START_HERE.md`](PROJECT_CONTROL/00_START_HERE.md)** (source-of-truth, deploy topology, two-agent separation, verification commands). Consolidates existing docs; does not replace them.

# SPA_Claude

**Smart Passive Aggregator — DeFi Yield Management System**

Версия: v12.87 | Язык: Python 3 (stdlib-only runtime) | Статус: Paper Trading — реальный трек с honest anchor **2026-06-22** (**12/30** evidenced честных дней, GoLive 27/29, target ~2026-07-21)

> ⚠️ **Источник истины — `CLAUDE.md` + `docs/SYSTEM_BRIEFING.md` + `data/golive_status.json`, не этот README.**
> Рантайм **детерминированный, только stdlib, LLM ЗАПРЕЩЁН** в risk/execution/monitoring
> (крутится на launchd-агентах + детерминированном RiskPolicy v1.0). Всё до anchor 2026-06-22 —
> backfill/демо/teardown, недействительно (honest-track reset; прежний anchor 2026-06-10 был pre-reset).

---

## Что это

SPA — автономный DeFi yield optimizer (стабильное кредитование USDC/USDT на whitelisted-протоколах),
работает только в **paper trading** до отдельного ADR на live-режим.

> **Историческая заметка:** изначально проектировался как мульти-LLM-агентная система (секция
> «Агенты» ниже). В текущем рантайме этот дизайн НЕ построен — логика детерминированная,
> stdlib-only, без LLM в risk/execution/monitoring. Секции ниже могут описывать исходный замысел,
> а не фактический рантайм; сверяйся с `CLAUDE.md`.

---

## Финансовые цели (ADR-009)

| Капитал | Целевой Net APY |
|---|---|
| $10,000 | 4.0% |
| $25,000 | 6.2% |
| $50,000 | 6.9% |
| $100,000 | 7.3% |
| $250,000 | 7.5% |

Baseline (v1_passive): стабильное кредитование, Sharpe ≥ 2.0, Max drawdown ≤ 5%.

---

## Whitelist протоколов (v0.4.5)

| ID | Протокол | Tier | Сети | Активы | Статус |
|---|---|---|---|---|---|
| T1-01 | Aave V3 | Tier 1 | Ethereum, Arbitrum, Base | USDC, USDT | Active |
| T1-02 | Compound V3 | Tier 1 | Ethereum, Arbitrum | USDC, USDT | Active |
| T1-03 | Morpho | Tier 1 | Ethereum, Base | USDC, USDT | Active |
| T2-01 | Yearn V3 | Tier 2 | Ethereum | USDC, USDT | Active |
| T2-02 | Pendle | Tier 2 | Ethereum, Arbitrum | PT-stablecoin | Active |
| T2-03 | Maple Finance | Tier 2 | Ethereum | USDC | Active |
| T2-04 | Euler V2 | Tier 2 | Ethereum | USDC, USDT | Active |
| WL-01 | Sky/sUSDS | Watch List | Ethereum | USDS | 0% (pending 48h GSM) |

---

## Агенты

| Агент | Тип | Модель | Роль |
|---|---|---|---|
| CEO Agent | LLM | Claude Sonnet 4.6 | Стратегия, оркестрация, финальное одобрение |
| Data Agent | Детерм. + LLM | Gemini 2.5 Flash-Lite | Сбор DeFi-данных, классификация аномалий |
| Risk Agent | **Детерминированный** | — | VaR, лимиты, circuit breakers (LLM запрещён) |
| Strategy Agent | LLM | Gemini 2.5 Flash | Выбор и применение стратегий |
| Execution Agent | **Детерминированный** | — | Исполнение paper trades (LLM запрещён) |
| Monitoring Agent | Детерм. + LLM | Claude Haiku 4.5 | Heartbeat, классификация инцидентов |
| Memory & Knowledge | LLM | Claude Haiku 4.5 | Retrieval, контекст решений |

**Критическое правило:** Risk Agent и Execution Agent — ТОЛЬКО детерминированный код. LLM запрещён для предотвращения prompt injection атак на капитал.

**LLM cost:** ~$6.60/мес при 10 вызовов/агент/день.

---

## Архитектура коммуникации

- **Message Bus:** asyncio pub/sub (Redis для multi-node). Все агенты публикуют события в именованные топики.
- **Direct channels:** Data↔Risk, Risk↔Strategy, Strategy↔Exec — timeout 500ms, fail-closed.
- **correlation_id:** UUID отслеживает полный Decision Flow для аудит-лога.
- **Anti-loop:** максимум 3 итерации Decision Flow, 4-я → escalation + 1h cooldown.
- **CEO offline:** очередь эскалаций с таймаутом 60s → авто-отклонение.

---

## Strategy Sandbox

- До **10 стратегий** параллельно в paper trading
- Lifecycle: `DRAFT → PAPER_TESTING → REVIEW → [PROMOTED | ELIMINATED]`
- Минимальный срок теста: **8 недель** (Paper_Trading_and_Simulation_Plan v0.3)
- Стратегии описаны в **YAML-файлах** (Strategy Passport) — hot-reload с аудит-логом
- Виртуальный капитал: **$10,000 на стратегию**
- Backtest: DeFiLlama API + The Graph, данные с 2022 года

---

## Dashboard (React + AG-UI)

| Вкладка | Содержание |
|---|---|
| TEAM | Статус агентов, pixel-art аватары, Activity Log |
| BOARD | Kanban: BACKLOG / IN PROGRESS / DONE |
| METRICS | Portfolio PnL, Sharpe, drawdown, equity curve |
| STRATEGY SANDBOX | Управление стратегиями, запуск paper test, backtest |
| CHAT | Диалог с CEO Agent (текст + голос) |

**Голосовой интерфейс** (OpenAI Realtime API): только read-only команды. Изменение конфигурации, whitelist, risk-лимитов — только через UI с подтверждением.

---

## Структура папки

```
SPA_Claude/
├── README.md                         — этот файл
├── MEMORY_FACTS.md                   — ключевые факты проекта
├── REVIEW_SUMMARY.md                 — результаты ревью v0.3
├── CHANGELOG_v0.3.md
├── CHANGELOG_v0.4_v0.4.5.md
└── SPA/
    ├── 01_Docs/                      — документация v0.3 (из архива)
    │   ├── 00_Context_v0.3.md
    │   ├── Risk_Policy_v0.3.md
    │   ├── Mode_Policy_v0.3.md
    │   ├── 04_Whitelist_Policy_v0.3.md
    │   ├── 13_Operations_Runbook_v0.3.md
    │   ├── 14_Incident_Response_v0.3.md
    │   ├── 15_Monitoring_and_Alerts_v0.3.md
    │   ├── 16_Data_and_Signals_v0.3.md
    │   ├── 18_Agent_Architecture_v0.3.md
    │   ├── Execution_Cost_Model_v0.3.md
    │   ├── Accounting_and_PnL_v0.3.md
    │   ├── Reporting_Weekly_Template_v0.3.md
    │   ├── Paper_Trading_and_Simulation_Plan_v0.3.md
    │   ├── Strategy_Passport_Template_v0.3.md
    │   ├── Strategy_Passport_Stable_Lending_Core_v0.3.md
    │   ├── Docs_Index_v0.3.md
    │   └── Paper_Trading_Week0_Baseline_2026-05-02.md
    ├── 02_Implementation/             — новые документы v1.0
    │   ├── 19_Agent_Communication_v1.0.md
    │   ├── 20_LLM_Stack_v1.0.md
    │   ├── 21_Strategy_Sandbox_v1.0.md
    │   └── 22_Dashboard_and_UI_v1.0.md
    └── 06_ADR/                        — Architecture Decision Records
        ├── ADR-2026-001.md  — LangGraph как оркестратор
        ├── ADR-2026-002.md  — Paper-first подход
        ├── ADR-2026-003.md  — Whitelist v0.4.5
        ├── ADR-2026-004.md  — Kill Switch
        ├── ADR-2026-005.md  — Execution Agent детерминированный
        ├── ADR-2026-006.md  — Hybrid LLM стек
        ├── ADR-2026-007.md  — Sky/sUSDS Watch List
        ├── ADR-2026-008.md  — browser-use для DEX
        └── ADR-2026-009.md  — Финансовые цели

```

---

## Технологический стек

| Компонент | Технология |
|---|---|
| Оркестрация | LangGraph |
| Message Bus | asyncio pub/sub → Redis |
| БД | SQLite (прототип) → PostgreSQL |
| Стратегии | YAML + hot-reload (watchdog) |
| Frontend | React + TypeScript |
| Agent UI | AG-UI Protocol (CopilotKit) |
| Realtime | WebSocket (AgentStream) |
| Голос | OpenAI Realtime API |
| Computer-use | browser-use |
| Данные | DeFiLlama API, The Graph |
