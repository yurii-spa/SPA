# SPA Documentation v0.3 — Master Changelog

Version: v0.3 (DRAFT, готов к утверждению Owner)
Started: 2026-05-01
Completed: 2026-05-01
Author of review: Claude (Anthropic)
Owner approval: pending
Scope: ревью и обновление всей документации проекта SPA (16 документов)

---

## Принципы ревью

- Frozen-документы v0.2 не удаляются; v0.3 создаётся как преемник.
- Ни одна правка не снижает уровень контроля рисков; правки только усиливают или уточняют.
- Все изменения логируются здесь с обоснованием.
- Owner принимает финальное решение по каждому изменению.
- Этот файл — кандидат-список, а не утверждённый ADR. После утверждения Owner — основа для ADR в `06_ADR/`.

---

## Системные изменения, общие для всех документов

**S1. Версионирование.** Все документы получают мини-changelog в шапке, перечисляющий ключевые изменения.

**S2. Условия выхода в v1.0.** В каждом ключевом документе добавлено явное условие, при котором документ переходит из v0.x в v1.0.

**S3. Регуляторный контекст.** Context получает новый раздел про санкционные ограничения. Risk Policy и Whitelist Policy ссылаются на этот раздел.

**S4. Сетевая нейтральность.** В v0.2 имплицитно предполагался Ethereum L1. В v0.3 явно зафиксировано: текущая область действия — EVM-сети.

**S5. Унификация статусов.** Все документы теперь честно помечены как Draft до Owner-утверждения. В v0.2 было противоречие: метаданные «Frozen» vs внутренний статус «Review» в 9 из 16 документов.

---

## Документ-уровневые изменения

### 00_Context (v0.2 Frozen → v0.3 Draft)
- Добавлены: 1.1 Действующие лица, 1.2 Критерии успеха (6% net yield, 5% drawdown, ≤1 крит. инцидент/год, ≤10% safe-mode), 6.1 Регуляторный контекст, 7.1 Условия выхода в v1.0.
- Уточнён горизонт проекта (минимум 24 месяца).
- Иерархия документов синхронизирована с Docs_Index.

### Risk_Policy (v0.2 Review → v0.3 Draft) — КРИТИЧНЫЕ ИЗМЕНЕНИЯ
- Исправлен конфликт статуса.
- Лимиты концентрации (4.1): таблица «целевая / максимальная / жёсткая граница» вместо диапазонов.
- Добавлено 4.2 «Лимиты по типу риска» — корреляционные риски (lending 50%, эмитент 50%, сеть 70%).
- Добавлено 5 «Лимиты просадки» (daily 2% / weekly 3% / monthly 5% / annual 5%).
- Добавлено 6 «Risk Budget».
- Раздел 7.1 переписан: разделены «эксплойт активный» и «эксплойт завершённый».
- Добавлены 7.6 «Сетевой риск», 7.7 «Регуляторный риск».
- Добавлено 9.1 «Default-policy при отсутствии Owner» (heartbeat 72-168ч).
- Добавлено 10 «Tail Risk Reserve» (5% портфеля, не для yield).

### Mode_Policy (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- Терминология: «пользователь» → «Owner».
- Структура портфеля переписана: целевая/мин/макс таблица.
- 5.1 «Переключение режимов»: только начало месяца, ≥90 дней между, через ADR.
- 5.2 «Режим по умолчанию» (Режим A при первом запуске и при недоступности Owner >7 дней).
- 8 «Расширяемость» — правила добавления Режим C.

### 04_Whitelist_Policy (v0.2 Frozen → v0.3 Draft) — КРИТИЧНЫЕ ИЗМЕНЕНИЯ
- Имена файлов в зависимостях актуализированы.
- Tier 1 субъективный критерий заменён на «топ-3 в категории по DeFiLlama 90+ дней».
- 3.4 «Требования к сети», 3.5 «Требования к oracles», 3.6 «Timelock» (48ч Tier 1, 24ч Tier 2).
- 4.1 «Регуляторная проверка перед добавлением».
- 5.1 «Периодическое ре-ревью» (квартально).
- 5: расширен мониторингом governance.
- 6.1 «Exit Liquidity Test» (≤0.3% slippage Tier 1).
- 9 «Действующий whitelist»: пустой, шорт-лист кандидатов (Aave V3, Compound V3, Morpho Blue, Sky).

**Документ не может быть Frozen без заполнения раздела 9.**

### 13_Operations_Runbook (v0.2 Frozen → v0.3 Draft) — КРИТИЧНЫЕ ИЗМЕНЕНИЯ
- 3.4 «Совмещение ролей Owner/Operator на Self-Capital» с правилом 24-часовой паузы.
- 4.3 «Лимиты Autopilot»: 1/час, 3/день, 10/неделю, 10% портфеля макс.
- 4.4 «Аварийная остановка Autopilot».
- 6.1 «Процедуры на инциденты доступа».
- 6.2 «Multi-sig requirements».
- 6.3 «Hardware wallet requirements».
- 6.4 «Heartbeat-механизм Owner».
- 8.1 «Операционные ошибки исполнения».
- 9: append-only хранилище логов и регулярный review.

### 14_Incident_Response (v0.2 Frozen → v0.3 Draft)
- 2.0 «Severity levels» (SEV-1 1ч / SEV-2 24ч / SEV-3 7д / SEV-4 weekly).
- 3.1 «Triage» с консервативной классификацией.
- 3.2 «Запрещённые эмоциональные паттерны»: panic-sell, revenge, FOMO, anchoring, doubling down.
- 5.1 «Внешняя коммуникация».
- 6.1 «Закрытие инцидента» (подтверждённый/ложный/частично).
- 7 «Tabletop exercises» (квартальные).

### 15_Monitoring_and_Alerts (v0.2 Frozen → v0.3 Draft)
- 3.7 «Portfolio Drawdown Monitoring».
- 3.8 «Owner Heartbeat Monitoring».
- 3.9 «Governance & Protocol Updates Monitoring».
- 3.10 «DeFi-specific» (MEV, bridges, whales).
- 4.1 «Alert Deduplication and Throttling».
- 4.2 «Threshold Calibration» (после 8 недель paper).
- 4.3 «Self-monitoring».

### 16_Data_and_Signals (v0.2 Frozen → v0.3 Draft)
- 3.6 «Compliance Data» (OFAC/EU/UN).
- 4.4 «Кандидаты в provider stack» — конкретные провайдеры.
- 4.5 «Multi-chain rules».
- 4.6 «Cost considerations» ($50-150/месяц ориентир).
- 7.1 «Historical data» для paper trading.
- Различение нормальной refresh rate и аномальной задержки.

### 18_Agent_Architecture (v0.2 Frozen → v0.3 Draft) — КРИТИЧНЫЕ ИЗМЕНЕНИЯ
- 3.1 «Mapping на современные фреймворки» (LangGraph, OpenAI Agents SDK, MCP).
- **3.2 «Deterministic vs LLM-based» — Risk Agent и Execution Agent НИКОГДА не LLM.**
- Для каждого агента — явные tool boundaries.
- 4.6 «Memory & Knowledge Agent» (опциональный).
- 5.1 «Coordination failures».
- 5.2 «Anti-loop guards» (макс 3 итерации, cooldown 1ч).
- **6.1 «Защита от prompt injection»** — все внешние тексты как untrusted, structured data only.

### Execution_Cost_Model (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- Safety Multiplier разбит по типам: 1.6 плановый ребаланс / 2.0 новый вход / 1.4 плановый выход / 0 экстренный / 0.8 защитный.
- 8.1 «Cumulative cost limit» (≤30% Realized Yield за 7 дней).
- 9.1 «Газ — единицы и расчёт».

### Accounting_and_PnL (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- 3.3 «Gas wallet и его учёт».
- 4.1 «Internal transfers».
- 6.4 «Reward tokens» (OP, ARB, COMP).
- 13.1 «Точность» (6 decimals внутри / 2 в отчётах).
- 13.2 «Базис конвертации».

### Reporting_Weekly_Template (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- 5.3 «Drawdown за период».
- 8.1 «Heartbeat-статус Owner».
- 8.2 «Quarterly whitelist re-review».
- 14 «Дисциплина отчётности» (≤48h после конца периода).
- 15 «Monthly и Quarterly reports».

### Paper_Trading_Plan (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- **Минимальная продолжительность увеличена с 30 до 56 дней (8 недель).**
- 4.1 «Точность симуляции» (gas ±20%, slippage ±10%).
- 6.3 «Drawdown в paper trading».
- 9.1 «Виртуальный vs reference capital».
- 11.1 «Изоляция paper trading от live».

### Strategy_Passport_Template (v0.2 Frozen → v0.3 Draft)
- 5 «Лимиты» переписан под Risk Policy 4.1.
- 4.3 «Governance / oracle / regulatory checks».
- 4.4 «Tier классификация».
- 5.2 «Drawdown-лимиты стратегии».
- 11 «Kill Criteria» с числовыми порогами.
- 12 «Paper trading требования».
- 14 «ADR reference», 15 «Strategy Owner».

### Strategy_Passport_Stable_Lending_Core (v0.2 Review → v0.3 Draft)
- Конфликт статуса исправлен.
- Конкретные кандидаты протоколов (Aave V3, Compound V3, Morpho Blue, Sky).
- Заполнены поля 4.3, 4.4 (или помечены TBD для конкретного ADR).
- 5.2 «Drawdown-лимиты» строже общих (1%/2%/3%).
- 11 «Kill Criteria» с числовыми порогами.
- 12 «Paper trading milestones».
- ADR references.

### Docs_Index (v0.2 Frozen → v0.3 Draft)
- Все статусы приведены к реальному (Draft).
- 2: ссылка на Context v0.3 раздел 6, не дублирование.
- Все таблицы на v0.3 имена файлов.
- 7 «Зависимости и blocker-цепочки».
- 8 «ADR (Architecture Decision Records)».
- 9: PDF в 00_Admin помечены как «historical reference».

---

## Документы из 00_Admin

PDF-файлы (`design_foundation.pdf`, `docs_architecture.pdf`, `ai_base_architecture.pdf`, `roadmap_milestones.pdf`) не переписывались. Привязаны к ChatGPT 5.2 Pro (февраль 2026), устарели относительно Claude Code / Codex GPT-5.5.

**Рекомендация:** перенести в `00_Admin_Archive/` после v0.3 финализации.

---

## Открытые вопросы для Owner

См. `REVIEW_SUMMARY.md` разделы Q1–Q12.

- **Q1.** Цифры критериев успеха (Context 1.2)
- **Q2.** Юрисдикция Owner (Context 6.1)
- **Q3.** Лимиты концентрации (Risk Policy 4.1)
- **Q4.** Drawdown vs Risk Budget (Risk Policy 5/6)
- **Q5.** Размер Tail Risk Reserve (Risk Policy 10)
- **Q6.** Heartbeat-механизм (Risk Policy 9.1)
- **Q7.** Шорт-лист протоколов Tier 1 (Whitelist Policy 9.1)
- **Q8.** Квартальное re-review (Whitelist Policy 5.1)
- **Q9.** Provider stack (Data & Signals 4.4)
- **Q10.** Multi-sig setup (Operations Runbook 6.2)
- **Q11.** Реализационная платформа (Claude Code vs Codex)
- **Q12.** Обработка PDF в 00_Admin

---

## Финальное состояние

**16 документов v0.3 в `01_Docs/`** + `REVIEW_SUMMARY.md` + `CHANGELOG_v0.3.md` + `00_Admin/` (4 PDF без изменений).

**Следующий шаг:** Owner отвечает на Q1–Q12, формирует ADR-001 ÷ ADR-006, переводит документы из Draft в Frozen.
