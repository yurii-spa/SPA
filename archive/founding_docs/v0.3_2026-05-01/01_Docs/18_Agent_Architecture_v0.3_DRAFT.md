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

Этот документ описывает **архитектуру ИИ-агентов SPA**: их роли, зоны ответственности, границы автономности и взаимодействие с политиками и операционными контурами.

Цель архитектуры:
- усилить дисциплину, а не заменить мышление;
- автоматизировать рутинные и формализуемые процессы;
- исключить неконтролируемую автономию;
- обеспечить воспроизводимость решений и действий.

ИИ в SPA — это **исполняющий и аналитический слой**, а не субъект риска.

Агенты — это **программные модули**, не люди. Названия (Data Agent, Risk Agent и т.д.) обозначают функциональные роли в системе.

---

## 2. Принципиальные ограничения архитектуры

Архитектура агентов строится на принципах:

- политики выше агентов и обязательны к исполнению;
- агент не может изменять правила (policies) и whitelist;
- агент не владеет капиталом и не принимает риск на себя;
- агент не имеет прямого доступа к приватным ключам;
- любое действие агента должно быть объяснимо задним числом;
- отсутствие действия — допустимый результат.

Ни один агент не имеет права инициировать действия вне разрешённого Decision Flow.

---

## 3. Состав агентов и границы ответственности

SPA использует многоагентную модель с разделением функций.

Агенты:

1) Data Agent
2) Risk Agent
3) Strategy Agent
4) Execution Agent
5) Monitoring & Alert Agent
6) Memory & Knowledge Agent (опциональный, см. 4.6)

Каждый агент:
- решает строго ограниченный класс задач;
- не является финальным арбитром;
- работает только с разрешёнными входными данными;
- фиксирует результаты в логах.

### 3.1. Mapping на современные фреймворки

Архитектура SPA соответствует **orchestrator pattern**:

- **Risk Agent** выступает как gate / orchestrator: его verdict определяет, продолжается ли Decision Flow.
- **Strategy Agent**, **Execution Agent**, **Data Agent**, **Monitoring Agent** — specialists с узкой зоной ответственности.
- **Handoff** между агентами — только через Decision Flow (раздел 5), не peer-to-peer.
- **State management:** каждый агент видит shared state в режиме read; mutations — только через свои logs и через Risk Agent verdict.
- **Tool integration:** рекомендуется через MCP (Model Context Protocol) — стандарт Anthropic для подключения внешних tools и сервисов к LLM-агентам.

Совместимые фреймворки реализации:
- **LangGraph** (графовая модель state machines);
- **OpenAI Agents SDK** (built-in handoffs, tracing);
- **CrewAI** (для prototype);
- **прямая реализация** на любом языке без фреймворка.

Конкретный фреймворк выбирается через ADR на этапе реализации.

### 3.2. Deterministic vs LLM-based агенты

Не все агенты должны быть LLM-based. Это критическое архитектурное решение.

| Агент | Реализация | Обоснование |
|-------|-----------|-------------|
| **Risk Agent** | **deterministic (не LLM)** — код с явными rules | LLM может быть «уговорён» на исключение через prompt injection или социальную инженерию. Risk Agent — последняя линия защиты. |
| **Execution Agent** | **deterministic (не LLM)** — код с явными правилами подписи | LLM не должен иметь возможность подписать транзакцию. Execution — это конкретные операции, не интерпретация. |
| Data Agent | смешанный (deterministic для on-chain, LLM-based для интерпретации off-chain) | сбор on-chain — детерминирован; парсинг человеческого текста (governance proposals, security alerts) — задача для LLM |
| Strategy Agent | LLM-based | анализ вариантов — задача для языковой модели |
| Monitoring & Alert Agent | смешанный | пороги — детерминированы; классификация и приоритизация — может быть LLM |
| Memory & Knowledge Agent | LLM-based | retrieval и контекст — естественная задача LLM |

**Risk Agent никогда не реализуется как LLM.** Это абсолютное правило этого документа.

---

## 4. Роли агентов

### 4.1. Data Agent

Задачи:
- сбор on-chain и off-chain данных;
- агрегация метрик;
- проверка целостности данных;
- выявление аномалий и расхождений.

Выходы:
- нормализованный датасет;
- метки качества данных (ok / degraded / broken) согласно Data & Signals 5;
- список расхождений между источниками.

Ограничения:
- не интерпретирует данные как торговые сигналы;
- не принимает решений;
- не инициирует действия.

**Tools:**
- read-only on-chain RPC (whitelisted endpoints);
- off-chain APIs (DeFiLlama, The Graph, oracle endpoints — whitelisted);
- security feed parsers (см. 6.1 для безопасности);
- **запрещено:** транзакции, доступ к ключам, внешний интернет вне whitelisted endpoints.

### 4.2. Risk Agent

Задачи:
- проверка соответствия Risk Policy и Mode Policy;
- контроль лимитов и экспозиций;
- сигнализация о нарушениях и приближении к лимитам;
- рекомендации перехода в safe-mode.

Выходы:
- verdict: `allow` / `block` / `safe-mode`;
- перечень нарушений и причин;
- рекомендации по снижению экспозиции.

Ограничения:
- не исполняет транзакции;
- не изменяет лимиты;
- не даёт разрешений на действия вне Decision Flow;
- **не реализован как LLM** (см. 3.2).

**Tools:**
- read-only access к state портфеля;
- read access к политикам как файлам / structured config;
- математические вычисления;
- **запрещено:** API calls, web requests, любая запись (кроме risk.log).

### 4.3. Strategy Agent

Задачи:
- анализ доступных стратегий (Strategy Passports);
- расчёт ожидаемой net-доходности;
- учёт execution cost и ёмкости;
- формирование предложений по ребалансу.

Выходы:
- набор вариантов (вариант A/B/…);
- расчёт net yield после всех издержек;
- обоснование выбора и отказа.

Ограничения:
- не исполняет операции;
- не выбирает не-whitelisted протоколы;
- не может игнорировать verdict Risk Agent;
- результат всегда передаётся через Risk Agent перед Execution.

**Tools:**
- read-only на data;
- simulation / preflight tools (read-only on-chain calls типа `eth_call`);
- математические вычисления;
- LLM reasoning;
- **запрещено:** транзакции, доступ к ключам, изменение whitelist.

### 4.4. Execution Agent

Задачи:
- подготовка транзакций;
- симуляция исполнения (preflight);
- контроль gas и проскальзывания;
- исполнение операций **только при включённом Autopilot**.

Выходы:
- план транзакций;
- оценка издержек и проскальзывания;
- статус исполнения и фактические результаты.

Ограничения:
- не инициирует стратегии;
- не обходит safe-mode;
- не имеет прямого доступа к ключам (только через прокси/подпись по правилам Operations Runbook 6);
- **не реализован как LLM** (см. 3.2).

**Tools:**
- transaction signing через прокси (multi-sig API, Safe SDK или эквивалент);
- simulation (Tenderly, on-chain `eth_call`, fork-based simulation);
- gas estimation;
- on-chain monitoring выполняемой транзакции;
- **запрещено:** прямой доступ к private keys, изменение политик, инициация стратегий без Risk Agent allow.

### 4.5. Monitoring & Alert Agent

Задачи:
- непрерывный мониторинг метрик (см. Monitoring & Alerts);
- генерация алертов;
- фиксация инцидентов;
- эскалация событий по Incident Response.

Выходы:
- alerts.log;
- incidents.log (инициация записи);
- сигнал safe-mode (через Risk Agent).

Ограничения:
- не принимает торговых решений;
- не выполняет операций.

**Tools:**
- read-only на все источники данных;
- write только в alerts.log и incidents.log;
- алерт-каналы (email, Telegram, push) — read-only с точки зрения портфеля;
- **запрещено:** транзакции, изменение политик, прямое влияние на portfolio state.

### 4.6. Memory & Knowledge Agent (опциональный)

Этот агент **не обязателен** для запуска SPA, но рекомендуется при достижении 6+ месяцев истории.

Задачи:
- управление long-term memory (прошлые инциденты, post-mortems, ADR);
- retrieval релевантного контекста при принятии решения;
- индексация Strategy Passports и whitelist истории.

Выходы:
- релевантные snippets для Strategy Agent (например: «вот post-mortem прошлого инцидента в этом протоколе»);
- summary исторических данных по запросу.

Ограничения:
- не имеет права исполнять операции;
- не имеет права изменять политики;
- не имеет права инициировать Decision Flow.

**Tools:**
- read-only на архив документов и логов;
- vector embeddings и retrieval;
- LLM reasoning;
- **запрещено:** запись в production-логи, транзакции.

---

## 5. Decision Flow (обязательный порядок)

Decision flow является обязательным и не может быть нарушен.

1) **Data Agent** обновляет данные и выставляет качество данных
2) **Monitoring & Alert Agent** проверяет аномалии
3) **Risk Agent** выдаёт verdict (`allow` / `block` / `safe-mode`)
4) **Strategy Agent** формирует варианты — **только при verdict = allow**
5) **Execution Agent** готовит план транзакций и preflight
6) Исполнение:
   - Manual: Owner/Operator подтверждает и исполняет
   - Autopilot: Execution Agent исполняет строго по правилам

Любая аномалия качества данных или verdict Risk Agent = `block` / `safe-mode` — останавливает поток.

### 5.1. Coordination failures

Что происходит при рассинхронизации между агентами:

- **расхождение verdict** между Risk Agent и Monitoring Agent → выбирается более консервативный + safe-mode;
- **timeout** между агентами (агент не отвечает в течение N секунд) → safe-mode по умолчанию;
- **stale state** (агент работает на устаревших данных) → invalidate result, повторный Decision Flow;
- **двойной Decision Flow** (две параллельные итерации одновременно) — запрещён через mutex/lock; нарушение — инцидент 2.5 (AI / Automation).

Default timeout per agent step: 60 секунд (для Manual mode), 30 секунд (для Autopilot).

### 5.2. Anti-loop guards

Защита от зацикливания Decision Flow:

- максимум **3 итерации** в одном Decision Flow цикле (например, Strategy Agent предложил → Risk блокировал → Strategy переформулировал → Risk снова блокировал = на 3-й итерации stop);
- на 4-й итерации → escalation Owner с пометкой `loop_detected` в `incidents.log`;
- **cooldown timer** на повторный Decision Flow по тому же триггеру: минимум **1 час**;
- если за 24 часа сработал >5 Decision Flow по одному и тому же активу — mandatory review соответствующего Strategy Passport.

---

## 6. Autopilot и уровни автономности

Autopilot **не является «умным трейдером»**. Это ограниченный механизм исполнения.

Уровни:
- **Autopilot OFF** — все операции исполняются вручную Operator (при необходимости Owner);
- **Autopilot ON** — Execution Agent может исполнять только заранее разрешённые действия в рамках:
  - Strategy Passport;
  - Risk Policy (включая лимиты Autopilot из Operations Runbook 4.3);
  - Mode Policy;
  - Whitelist Policy;
  - Operations Runbook.

Триггеры немедленного отключения Autopilot:
- деградация качества данных (degraded / broken);
- любой инцидент по Incident Response;
- verdict Risk Agent = `block` / `safe-mode`;
- повторяющиеся ошибки исполнения;
- аномальные значения газ / проскальзывания;
- срабатывание лимитов Autopilot (rate limit из Operations Runbook 4.3);
- срабатывание anti-loop guard (5.2).

### 6.1. Защита от prompt injection и agentic attacks

В DeFi 2026 prompt injection — реальная угроза. Любой текст из внешних источников (Twitter, Discord, blog protocols, governance proposals) может содержать инструкции вида «ignore previous instructions» или попытки манипуляции.

Правила:

1) Все внешние тексты трактуются как **untrusted user input**, не как инструкции.

2) Внешние тексты **никогда** не передаются напрямую в системный промт LLM-агента. Между сырым текстом и LLM всегда стоит **preprocessing-слой** с строгой схемой выхода.

3) В LLM-агенты подаётся только **structured data** (числа, статусы, classification labels), не сырой текст.

4) Если необходимо извлечь смысл из текста — через отдельный preprocessing-слой:
   - извлечение структурированных полей (sentiment, named entities, urgency);
   - результат preprocessing проверяется на anomalies (длина выхода, неожиданные команды);
   - подача в LLM-агент только проверенного structured output.

5) **Risk Agent (deterministic)** не имеет text-based входов вообще. Его входы — числа и enum'ы.

6) Любое «решение», полученное от LLM-агента, проходит через Risk Agent для верификации соответствия политикам. LLM не может сам разрешить действие.

7) **Sandbox-тесты:** перед deployment каждого LLM-агента проводится тест на jailbreak-устойчивость с попытками prompt injection через все возможные входы.

---

## 7. Логи и объяснимость

Каждый агент обязан:
- писать собственные логи;
- фиксировать входные данные;
- фиксировать выводы и рекомендации;
- обеспечивать объяснимость задним числом.

Обязательные логи:
- `data.log`
- `risk.log`
- `strategy.log`
- `execution.log`
- `alerts.log`
- `memory.log` (если используется Memory Agent)

Инциденты фиксируются в `incidents.log` согласно Operations Runbook и Incident Response.

Логи дублируются в append-only хранилище (см. Operations Runbook 9).

---

## 8. Ограничения документа

Этот документ:
- не описывает конкретные модели ИИ (Claude / GPT-5.5 / другие);
- не описывает реализацию и инфраструктуру;
- не определяет качество предсказаний;
- не является технической спецификацией.

Он фиксирует **границы и роли**, а не эффективность алгоритмов.

---

## 9. Условия выхода в v1.0

Agent Architecture переходит в v1.0 после того как:
- утверждён конкретный фреймворк реализации через ADR;
- проведены sandbox-тесты на jailbreak-устойчивость для всех LLM-агентов;
- завершено минимум 8 недель paper trading с активной агентской системой;
- проведён минимум 1 Decision Flow с расхождением verdict (5.1) — для проверки coordination failure handling;
- проведён минимум 1 anti-loop trigger (5.2) — для проверки защиты от зацикливания.

---

## 10. Статус и контроль изменений

Статус: Draft (целевой — Frozen после правок и согласования).

Любые изменения данного документа допускаются **только через ADR**.

Для перевода в Frozen v0.3:
- подтвердить deterministic vs LLM-based разделение (раздел 3.2) — Owner;
- подтвердить tool boundaries для каждого агента (раздел 4) — Owner;
- утвердить подход к prompt injection защите (раздел 6.1) — Owner;
- зафиксировать решение через ADR.
