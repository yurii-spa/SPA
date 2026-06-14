# SPA — Стратегия разработки v1.0

Project: Smart Passive Aggregator
Дата: 2026-05-20
Статус: Действующий план

---

## Главный вопрос: что нам нужно?

SPA — это не AI-чатбот. Это **система управления доходностью**:
получает данные с DeFi-протоколов → применяет правила Risk Policy →
выбирает лучшую стратегию → исполняет (пока симуляцию) → отчитывается.

Из этого следует ключевой вывод:

> **LLM-агенты — это верхний слой, а не фундамент.**
> Без данных агентам нечего анализировать.
> Без Risk Policy агенты опасны.
> Без paper trading трекера агенты бесполезны.

Строим снизу вверх.

---

## Критический путь

```
Данные → Риск + Стратегия → Paper Trading → Наблюдаемость → Агенты → Go-Live
```

Каждый этап — необходимое условие для следующего.
8-недельный тест начинается как можно раньше — это самое долгое ожидание.

---

## Фазы разработки

### Фаза 0 — Прямо сейчас (параллельно, 1 неделя)

**0A. Data Pipeline** (критический путь)
- Интеграция DeFiLlama API: APY, TVL, utilization rate по 7 протоколам whitelist
- Интеграция The Graph: on-chain события (liquidations, rates)
- SQLite: схема хранения, версионирование снимков (snapshot_id)
- Scheduler: сбор данных каждые 4 часа
- Валидация: проверка аномалий, пропусков, stale data

**0B. Risk Policy (детерминированный код)** (параллельно)
- VaR калькулятор по текущим позициям
- Концентрационные лимиты (max % в один протокол)
- Circuit breakers: пороговые значения для автостопа
- Тесты: 100% покрытие юнит-тестами (это код который трогает деньги)

Выход Фазы 0: данные текут в базу, риск-правила написаны и протестированы.

---

### Фаза 1 — Paper Trading старт (1-2 недели)

**Ключевое событие: запускаем 8-недельный отсчёт.**

- Strategy v1_passive: детерминированная логика выбора протокола
  - Ранжирование по net APY (с учётом fee)
  - Проверка через Risk Policy перед каждым действием
  - Условия входа и выхода из позиции
- Paper Trading Engine:
  - Запись виртуальных сделок в SQLite
  - Расчёт PnL, net APY (annualized), Sharpe
  - Тег `strategy_id` на каждой сделке
- Простой CLI-дашборд: `python show_status.py` — текущие позиции, PnL, риски

Выход Фазы 1: система ежедневно принимает решения и записывает их в базу.
Начинается отсчёт 8 недель для v1_passive.

---

### Фаза 2 — Наблюдаемость (параллельно с Фазой 1)

Пока идёт 8-недельный тест — строим инструменты наблюдения.

**2A. Web Dashboard (простой, не React)**
- FastAPI backend: эндпоинты для данных
- Простой HTML/JS фронт (или даже Streamlit на старте)
- Страницы: Portfolio Overview, Trade Log, Risk Status, APY Chart
- Цель: видеть данные в браузере, без сложного стека

**2B. Alerting & Reporting**
- Heartbeat: проверка что data pipeline жив
- Алерты при аномалиях данных (stale APY, TVL drop > 20%)
- Автоматический еженедельный отчёт (Markdown файл по шаблону)
- Email/Telegram уведомление (опционально)

**2C. Backtest Engine**
- Прогон v1_passive на исторических данных (DeFiLlama с 2022)
- Сравнение equity curve: стратегия vs baseline
- Генерация report: Sharpe, drawdown, N сделок

Выход Фазы 2: ты видишь что происходит в реальном времени.

---

### Фаза 3 — Strategy Sandbox (параллельно с тестом v1_passive)

Пока v1_passive проходит 8-недельный тест, готовим альтернативы.

- v2_aggressive.yaml: T1 + T2 протоколы, выше риск / выше APY
- v3_pendle_focused.yaml: акцент на Pendle PT, фиксированная доходность
- Все стратегии запускаются параллельно в paper trading
- Backtest каждой стратегии на исторических данных
- Dashboard: сравнение стратегий по PnL, Sharpe, drawdown

Выход Фазы 3: к концу 8 недель у нас есть несколько стратегий с реальными результатами.

---

### Фаза 4 — LLM Агенты (после стабильного paper trading)

Только когда данные текут, риск работает, PnL считается — добавляем интеллект.

**Порядок внедрения агентов (важен):**

1. **Monitoring Agent** (Claude Haiku) — первый, самый простой
   - Классификация инцидентов из алерт-лога
   - "Это аномалия данных или проблема протокола?"

2. **Data Agent** (Gemini Flash-Lite) — второй
   - Обогащает детерминированный pipeline классификацией аномалий
   - "Это временный spike APY или реальная возможность?"

3. **CEO Agent** (Claude Sonnet 4.6) — третий
   - Анализирует недельные отчёты
   - Принимает решения об эскалации
   - Отвечает на вопросы Owner через CHAT-вкладку

4. **Strategy Agent** (Gemini Flash) — четвёртый
   - Улучшает логику выбора стратегии
   - Hybrid: детерминированная база + LLM для edge cases

5. **Message Bus + LangGraph** — финальная интеграция
   - Все агенты общаются через pub/sub
   - correlation_id для полного аудит-лога

Выход Фазы 4: система умеет объяснять свои решения и задавать уточняющие вопросы.

---

### Фаза 5 — Production Dashboard (после стабильных агентов)

Только когда агенты работают — строим полный React UI.

- React + TypeScript + AG-UI Protocol (CopilotKit)
- WebSocket (AgentStream): live статус агентов
- Все 5 вкладок: TEAM / BOARD / METRICS / STRATEGY SANDBOX / CHAT
- Pixel-art аватары агентов
- Voice interface (OpenAI Realtime API)
- browser-use для DEX-данных без API

---

### Фаза 6 — Go-Live (требует отдельного ADR)

Условия для начала:
- 8+ недель успешного paper trading v1_passive
- Sharpe ≥ 2.0, drawdown ≤ 5%, N ≥ 15 сделок
- Все агенты работают стабильно ≥ 4 недели
- PostgreSQL вместо SQLite
- Security audit (VPN доступ, audit log)
- Kill Switch протестирован
- ADR принят Owner

---

## Что убираем с М1

Из текущего Бэклога убираем в "Позже" до Фазы 4-5:

| Убираем сейчас | Когда вернёмся |
|---|---|
| Message Bus (Redis) | Фаза 4 |
| LangGraph оркестратор | Фаза 4 |
| CEO / Strategy / Memory Agent | Фаза 4 |
| React Dashboard полный | Фаза 5 |
| Голосовой интерфейс | Фаза 5 |
| browser-use DEX | Фаза 5 |
| PostgreSQL миграция | Фаза 6 |

---

## Что параллельно

```
Неделя 1-2:   [0A Data Pipeline] ══ [0B Risk Policy]
Неделя 2-3:   [1. Paper Trading Engine]
Неделя 3-10:  [8-недельный тест v1_passive] ══ [2A Dashboard] ══ [2B Alerting] ══ [3. Sandbox]
Неделя 6-10:  [2C Backtest Engine]
Неделя 10+:   [4. Агенты (по очереди)]
Неделя 14+:   [5. React Dashboard]
Неделя 18+:   [6. Go-Live ADR]
```

---

## Что начинаем прямо сейчас

1. **DeFiLlama API скрипт** — первый реальный код проекта
2. **SQLite схема** — таблицы: protocols, apySnapshots, paperTrades, riskEvents
3. **Risk Policy калькулятор** — детерминированный, с тестами

Всё остальное — после того как данные текут.

---

## Revised Milestones

| Веха | Содержание | Условие старта |
|---|---|---|
| M1 | Data Pipeline + Risk Policy | Сейчас |
| M2 | Paper Trading старт (8-недельный отсчёт) | M1 готово |
| M3 | Web Dashboard + Alerting + Strategy Sandbox | После M2 |
| M4 | LLM Агенты (поэтапно) | M2 стабилен 2+ недели |
| M5 | Production React Dashboard | M4 готово |
| M6 | Go-Live | M2 8 недель + ADR |

---

*Этот документ заменяет предыдущие вехи из README.md и Канбан-доски.*
*Следующий шаг: обновить Канбан-доску под новую стратегию.*

---

## Current Status (2026-05-22)

**Paper trading is active. Day 2 of 56. Go-live decision: 2026-07-15.**

### Phase Completion

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Data Pipeline + Risk Policy | ✅ COMPLETE |
| Phase 1 | Paper Trading Engine | ✅ COMPLETE |
| Phase 2 | Observability (Dashboard, Alerts, Backtest) | ✅ COMPLETE |
| Phase 3 | Strategy Sandbox (multi-strategy, tournament) | ✅ COMPLETE |
| Phase 4 | LLM Agents | 🔶 PARTIALLY COMPLETE |
| Phase 5 | Production Dashboard | ✅ COMPLETE (v1.5) |
| Phase 6 | Go-Live | 🔄 IN PROGRESS — paper trading active |

**Phase 4 detail:** Basic agents built (CEO, Data, Strategy, Monitoring). Model config decoupled via `agents/model_config.py`. Message Bus (SQLite-backed pub/sub) operational. LangGraph orchestration and full agent memory are deferred to post-paper-trading period.

### APY Status

| Metric | Value |
|--------|-------|
| Current paper trading APY | ~4.2% |
| Target APY (at $100K) | 7.3% |
| Gap | ~3.1 pp |
| Gap closure lever | Pendle PT integration (v1.2) |

The gap exists because Sky/sUSDS allocation is 0% (pending GSM Pause Delay confirmation ≥48h) and Pendle PT pools are newly integrated and ramping up. As Pendle positions accumulate over the paper trading period the weighted APY is expected to approach the 7.3% target.

### Next 7 Weeks (2026-05-22 → 2026-07-15)

- **Accumulate P&L data** — daily Telegram digest active, risk monitor live
- **Monitor Sky/sUSDS on-chain** — GSM Pause Delay checker running (3 fallback RPCs); if 48h timelock confirmed, Sky moves to T1 at 30% weight
- **Pendle PT ramp-up** — quality-gated pools onboarding; expected to be primary APY driver
- **Agent stability** — target ≥4 weeks continuous stable operation before go-live
- **Go-live decision gate (2026-07-15):** Sharpe ≥ 2.0, drawdown ≤ 5%, N ≥ 15 trades, all agents stable, ADR accepted by Owner

### Build Stats (2026-05-22)

| Metric | Value |
|--------|-------|
| Sprint | v1.5 |
| Tests passing | 120+ |
| Files on GitHub | 67/68 (workflow file pending `workflow` scope token) |
| Dashboard version | v1.5 |
| Paper trading day | 2 / 56 |
