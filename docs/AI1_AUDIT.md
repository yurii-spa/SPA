# 🔍 AI1 Audit: Статус Выполнения Roadmap

**Дата:** 2026-08-29  
**Статус:** 🟢 IN PROGRESS — месяц 1 доставлен, месяц 2 ждёт стандартов  
**Версия:** 0.2

---

## 📇 Карточки трекера — по одной на задачу

Единственное место, где статус задачи меняется, — её карточка. Эта таблица —
окно в них, а не второй учёт: разошлись ⇒ верна карточка.

| Задача | Карточка (`nimbalyst-local/tracker/`) | Статус | Чем заблокирована |
|---|---|---|---|
| **1.0** Явные правила аллокации | `agent-ai1-10-pravila-allokatsii-yavno` | ✅ `done` | ждёт ревью владельца (5 вопросов) |
| **1.1** Allocation Auditor | `agent-ai1-11-allocation-auditor` | ⛔ `blocked` | подключением в дневной цикл — прод-дерево трогает владелец |
| **2.1** Стандарт уровней L0–L6 | `agent-ai1-21-standart-urovnei-dokazatelnosti` | ✅ `done` | канон уже был; доставлен НАДЗОР + починена поверхность доходности |
| **2.2** APY Evidencer | `agent-ai1-22-apy-evidencer` | 📋 `backlog` | **разблокирована**; начинать с правила §2, не с текущей разметки |
| **2.3** Критерии тиров | `agent-ai1-23-kriterii-tirov` | ✅ `done` | стандарт `docs/tier_criteria.md` + сторож; найдено недоставленное решение владельца |
| **2.4** Tier Validator | `agent-ai1-24-tier-validator` | ✅ `done` | валидатор УЖЕ существует (`tier_curator`) и подключён; доставлен сторож источника тира |
| **3.1** Rebalance Engine | `agent-ai1-31-rebalance-engine-dry-run` | ⛔ `blocked` | формально 1.1 (доставлена), фактически — вопрос 2 владельцу |

**Месяц 1 доставлен, оба стандарта месяца 2 закрыты за один день.** Свободны теперь
**2.2** и **2.4** — обе реализации, обе с записанным основанием. 3.1 ждёт ответа владельца.

**Обе задачи-стандарта пришлось начать с опровержения собственной постановки.**
2.3: «критериев тиров нет нигде» — контракт есть и тестируется. 2.1: «напиши стандарт
уровней L0–L6» — канон есть и запрещает себя переопределять, а пример из плана описывал
другую ось теми же метками. Общий вывод: **прежде чем писать стандарт, надо убедиться,
что его ещё нет** — иначе задача по построению производит вторую копию правды.

### Что дала 2.4 сверх задания (2026-08-29)

Валидатор просили написать — он существует (`spa_core/analytics/tier_curator.py`),
подробнее задания и **подключён к дневному циклу**. Третья ложная посылка за день.

Замер по живому отчёту (34 протокола): обосновано **30**, расходится с каноном **2**,
тира нет нигде — **2**. По `morpho_steakhouse` куратор выносит **KEEP**, то есть
ежедневно подтверждает тир, отменённый решением владельца ADR-070 п.6.
`sky_susds` судится как **T1** без основания при инварианте 10 («Sky/sUSDS = 0 %»).

Доставлен `test_tier_curator_uses_the_canon.py` (9 проверок): логика на фикстуре
работает всегда, живой отчёт — вторым слоем, оба списка известных случаев только
сокращаются.

### Что дала 2.1 сверх задания (2026-08-29)

Канон уровней — `docs/37` (ADR-YL-009) — существует и запрещает себя переопределять.
Не хватало **надзора**. Перепись точек назначения уровня в коде:

| Заявка | Мест | Почему это неправда |
|---|---|---|
| **L6** (`reporting.py`) | 2 | канон называет наш трек эталоном **L3** и требует слова «paper» |
| **L5** (`quant.py`) | 1 | на бэктесте; канон дословно: «backtest… never L4+» |
| **L4** (семь агентов) | 9 | «исполнено реальным капиталом» — которого не было ни разу |

Причина одна: слой читал L-метки как «насколько живой ИСТОЧНИК», а канон измеряет
«насколько далеко ИСПОЛНЕНО». Своей шкалы у слоя нет — `harness.py` прямо ссылается
на канон.

**Починено сразу одно место** — единственное, где метка стояла рядом с числом
доходности и бралась **из тира** (`T1 → L4`): живой `data/investment_os/stablecoin_yield.json`
носил L4 на числах из публичного API. Теперь L2. Тест, закреплявший `T1 → L4`, исправлен
с обоснованием и записью в журнал; проверка усилена.

Владельцу: `owner-decision-urovni-dokazatelnosti-2026-08-29` (три варианта, рекомендован
первый — понизить все одиннадцать).

Побочно: `docs/37` ссылается на **ADR-YL-009, которого нет ни в дереве, ни на origin**.

### Что дала 2.3 сверх задания (2026-08-29)

Постановка задачи была неверна, и проверка это опровергла: контракт «оценка → тир»
записан и **тестируется** (`TIER_BANDS`), а per-adapter тиры лежат в авторитетной
таблице с покрытием 36 из 36. Не хватало **правила каноничности** и сторожа.

Найдено при замере: **решение владельца ADR-070 п.6 от 07.08 доехало до трёх источников
из четырёх.** Класс `morpho_steakhouse` до сих пор объявляет `TIER = "T1"` — и именно
его читает снимок оркестратора, из которого аллокатор строит потолки. Отсюда TIER-01
в отчёте Allocation Auditor: это не «источники разошлись сами», а недоставленная правка.

| Что сверялось (36 адаптеров) | Расходится | Доходит до денег |
|---|---|---|
| `TIER` класса против канона | **1** | **да** |
| `RISK_SCORE` класса против канона | **31** | нет — аллокатор читает `risk_scores.json` |
| класс противоречит сам себе (оценка в одной полосе, тир от другой) | **6** | нет |

Владельцу: `owner-decision-tier-steakhouse-2026-08-29` (три варианта, рекомендован
второй — снять у классов право объявлять тир вообще).

### Что нашёл Allocation Auditor в первый же прогон (2026-08-29)

Вердикт **VIOLATION** по живой книге. Три находки, ни одной из которых не видел
ни один существующий сторож:

| Правило | Находка |
|---|---|
| **TIER-01** | `morpho_steakhouse` объявлен тиром ДВАЖДЫ и по-разному: канон `tier_map`=**T2**, снимок оркестратора=**T1**. Потолок 20 % против 40 %; совокупная доля T2 — **50 % против 35 %**. Это задача **2.3** в чистом виде, и она уже стоит денег. |
| **ECON-10 ×2** | `morpho_blue` и `morpho_steakhouse` держат по 15 % при доходности 4.04 % ниже медианы 4.40 % — больше половины тир-потолка. ADR-055 это запрещает. |
| **CAP-13/14** | у `morpho_steakhouse` не объявлена цепочка ⇒ потолки сети посчитать **нечем**. Записано «не измерено», не «в порядке». |

---

## 🎯 Цель Этого Документа

Для любого агента (Claude или человека), который берёт задачу с AI1 Roadmap:
- ✅ Что **уже готово** (можно использовать)
- ⏳ Что **в работе** (кто взял, статус, когда)
- 🔴 Что **брошено** (почему, нужно ли доделывать)
- 📋 **Что делать сейчас** (очередь задач, критичность)

Аудит по каждому пункту roadmap: МЕСЯЦ 1, МЕСЯЦ 2, МЕСЯЦ 3.

---

## МЕСЯЦ 1: Allocation Auditor

### 1.0 Явное описание allocation_logic

**Roadmap требует:** `docs/allocation_logic_explicit.md` (2K слов — явное описание + JSON schema)  
**Содержит:** потолки, эвристики, исключения, история решений

| Что | Статус | Где | Комментарий |
|-----|--------|-----|------------|
| **Потолки (40/20/50%)** | ✅ **В КОДЕ** | `spa_core/allocator/allocator.py` (116KB) | Реализованы в StrategyAllocator, но НЕ ДОКУМЕНТИРОВАНЫ явно |
| **Эвристики ребаланса** | ✅ **В КОДЕ** | `allocation_models.py`, `rebalance_economics.py` | Есть логика, но NЕ ОПИСАНА явно для машины |
| **Исключения (Sky/sUSDS = 0%)** | ✅ **ЧАСТИЧНО** | `.claude/rules/adapters.md`, `sky_susds_adapter.py` | Инвариант 10 исполнен в коде, но опис. неполное |
| **История решений (T1 vs T2)** | ✅ **ЧАСТИЧНО** | `docs/decisions/` (ADR-074, ADR-076 и др.) | Разбросано по ADR-ам, не в одном месте |
| **Документ `allocation_logic_explicit.md`** | 🟡 **ЧЕРНОВИК ГОТОВ, ждёт ревью владельца** | `docs/allocation_logic_explicit.md` (v0.1, 2026-08-29) | 33 правила с ID, все числа сверены с кодом автоматически; 5 пробелов вынесены владельцу (раздел 8) |
| **Храповик «документ = код»** | ✅ **ЕСТЬ** | `spa_core/tests/test_allocation_logic_explicit.py` | 38 проверок; проверен тремя мутациями (документ→код и код→документ), каждая покраснела |

**Что уже есть (ПЕРЕИСПОЛЬЗОВАТЬ):**
- `spa_core/allocator/allocator.py` — вся логика в коде, нужно только ЗАДОКУМЕНТИРОВАТЬ
- `MASTER_PLAN_v1.md` — потолки есть, нужно выписать явно
- `docs/decisions/` — история решений, нужно собрать в одно описание

**Что нужно делать:**
1. Owner + Claude: **ДОКУМЕНТИРОВАТЬ** существующую логику в `allocation_logic_explicit.md`
   - Не переписываем код, а ОПИСЫВАЕМ то что уже работает
   - Формат: JSON schema + примеры + обоснование
   - Берём числа ИЗ КОДА (не угадываем)
2. Интегрировать в Allocation Auditor как входные параметры
3. Тесты: 3 теста для проверки (нарушение потолка, оптимум, шум)

**СТАТУС (обновлено 2026-08-29):** 🟡 **ЧЕРНОВИК ДОСТАВЛЕН — ждёт владельца**
- Документ написан извлечением из кода, а не с нуля: владельцу осталось ревью + 5 ответов
  (было «выдели 1-2 недели на написание»).
- Карточка владельцу: `nimbalyst-local/tracker/owner-decision-AI1-approach-2026-08-29.md`.
- Задача 1.1 (Allocation Auditor) РАЗБЛОКИРОВАНА по числам: все потолки, окна и ручки
  имеют ID и проверяемое значение. Ждёт только подтверждения владельца, что правила — те самые.
- Код работает ✅
- Документация нужна ❌ (для auditor + clarity)

---

### 1.1 Allocation Auditor: Реализация

**Roadmap требует:** `spa_core/agents/allocation_auditor.py`

| Компонент | Статус | Код | Тесты | Комментарий |
|-----------|--------|-----|-------|------------|
| Модуль agents/ | ❓ НЕИЗВЕСТНО | ? | ? | **Агент исследует** |
| Allocation Auditor логика | ✅ **ДОСТАВЛЕН 2026-08-29** | `spa_core/agents/allocation_auditor.py` | `data/allocation_audit_daily.json` | 12 проверок по ID правил; три исхода (OK/VIOLATION/UNCHECKED), «не измерено» НЕ схлопывается в «в порядке»; 20 тестов, 5 мутаций |
| Первый прогон по живой книге | ✅ | вердикт VIOLATION | 3 нарушения + 1 «не измерено» | TIER-01 (два объявления тира у morpho_steakhouse), ECON-10 ×2, цепочка не объявлена |
| Подключение в дневной цикл | ⏸️ **ждёт владельца** | `scripts/run_daily_paper_cycle.sh` | - | правило доставки: прод-дерево трогает только владелец; патч подготовлен в карточке |
| Concentration check | ❌ НЕ НАЧИНАЛАСЬ | - | - | test_concentration_breach_detected() |
| Yield-opportunity detection | ❌ НЕ НАЧИНАЛАСЬ | - | - | test_yield_improvement_trigger() |
| Noise filter | ❌ НЕ НАЧИНАЛАСЬ | - | - | test_no_false_alarm_on_noise() |
| Контракт `allocation_audit.json` | ❌ НЕ ОПРЕДЕЛЁН | - | - | JSON schema нужно создать |

**Что нужно делать:**
1. Дождаться `allocation_logic_explicit.md`
2. Реализовать auditor.py (read-only, no LLM)
3. Написать 3 теста
4. Параллельный запуск 30 дней с owner

**СТАТУС (обновлено 2026-08-29):** ✅ **РАЗБЛОКИРОВАНА И ДОСТАВЛЕНА** — 1.0 дал числа, 1.1 их применяет

---

### 1.2 Integration в daily_cycle

**Roadmap требует:** Auditor работает в шаге 1.0 дневного цикла

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Step 1.0 в `run_daily_paper_cycle.sh` | ✅ ЕСТЬ | `scripts/run_daily_paper_cycle.sh` | Нужно проверить |
| Logging в `allocation_audit_daily.json` | ❌ НЕ НАЧИНАЛАСЬ | `data/allocation_audit_daily.json` | Контракт не определён |
| Cron scheduling | ✅ ДОЛЖНО БЫТЬ | `launchd/` или crontab | Нужно проверить |

**Что нужно делать:**
1. После реализации auditor (1.1) — интеграция в step 1.0
2. Подключить cron (07:50 перед циклом)

**СТАТУС:** ⏳ **ЖДЁТ** 1.1

---

## МЕСЯЦ 2: APY Evidencer + Tier Validator

### 2.1 APY Evidencer

**Roadmap требует:** `spa_core/agents/apy_evidencer.py`

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Evidence-levels (L0-L6) стандарт | ❓ НЕИЗВЕСТНО | `docs/37` (упоминается) | Нужно проверить, полный ли стандарт |
| APY freshness check | ❓ ЕСТЬ ЧАСТИЧНО | `spa_core/monitoring/` или `adapters/` | Site Custodian уже мониторит |
| APY Evidencer логика | ❌ НЕ НАЧИНАЛАСЬ | - | Должен собирать evidence в JSON |
| Контракт `apy_evidence.json` | ❌ НЕ ОПРЕДЕЛЁН | - | JSON schema нужно создать |
| Параллельный запуск с Site Custodian | ❌ НЕ НАЧИНАЛАСЬ | - | 30 дней валидации |

**Что нужно делать:**
1. Уточнить evidence-levels в документе
2. Реализовать apy_evidencer.py
3. Создать контракт apy_evidence.json
4. Параллельный запуск (неделя 4-6)

**СТАТУС:** ⏳ **ЖДЁТ MONTH 2**

---

### 2.2 Tier Validator

**Roadmap требует:** `spa_core/agents/tier_validator.py`

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Tier criteria (T1/T2/T3) стандарт | ✅ ЕСТЬ ЧАСТИЧНО | `MASTER_PLAN_v1.md`, `docs/decisions/` | TVL $5M, история, security — есть ли явное описание? |
| TVL-live check | ✅ ДОЛЖНО БЫТЬ | `spa_core/adapters/`, `defillama_feed.py` | Адаптеры это делают |
| Security score API | ❓ НЕИЗВЕСТНО | - | Нужно узнать: есть ли Certora/Immunefi API? |
| Tier Validator логика | ❌ НЕ НАЧИНАЛАСЬ | - | Собирает чек-лист для проверки |
| Контракт `tier_assessment.json` | ❌ НЕ ОПРЕДЕЛЁН | - | JSON schema нужно создать |
| Проверка владельцем — процесс | ⏳ ЕСТЬ ЧАСТИЧНО | `nimbalyst-local/tracker/` | Owner пишет owner-decision карточки |

**Что нужно делать:**
1. Явно описать все критерии T1/T2/T3 в документе
2. Реализовать tier_validator.py (чек-лист)
3. Подключить в процесс проверки (неделя 6-9)

**СТАТУС:** ⏳ **ЖДЁТ MONTH 2**

---

## МЕСЯЦ 3+: Rebalance Engine + Orchestrator

### 3.1 Rebalance Engine (Dry-Run)

**Roadmap требует:** `spa_core/strategy_lab/rebalance_engine.py` (or similar)

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Оптимальная аллокация логика | ❓ НЕИЗВЕСТНО | `spa_core/strategy_lab/` | Desk-ы и стратегии — что есть? |
| Cost-of-switch расчёт | ❓ НЕИЗВЕСТНО | - | Газ, спред — есть ли модель? |
| Dry-run план | ❌ НЕ НАЧИНАЛАСЬ | - | Что и на сколько менять (без выполнения) |
| Контракт `rebalance_plan.json` | ❌ НЕ ОПРЕДЕЛЁН | - | JSON schema нужно создать |

**Что нужно делать:**
1. Исследовать существующие desk-и и стратегии
2. Реализовать dry-run (неделя 13-16)
3. Тесты: безопасность, cost-benefit (неделя 17-20)

**СТАТУС:** ⏳ **ЖДЁТ MONTH 3**

---

### 3.2 Orchestrator Integration

**Roadmap требует:** Шаг 1.5 в дневном цикле (выполнение ребаланса)

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Orchestrator структура | ✅ ЕСТЬ | `spa_core/paper_trading/cycle_runner.py` (или аналог) | Нужно проверить |
| Fail-CLOSED проверка | ✅ ЕСТЬ ЧАСТИЧНО | `pre_cutover_gate.py` | Есть ли для each шага? |
| Kill-switch интеграция | ✅ ЕСТЬ | `spa_core/governance/kill_switch.py` (ADR-034/048) | Должна работать |
| Execution step | ❓ НЕИЗВЕСТНО | - | Где выполняется ребаланс? |

**Что нужно делать:**
1. Подключить Rebalance Engine в step 1.5
2. Verify fail-CLOSED для каждого шага (неделя 21-26)

**СТАТУС:** ⏳ **ЖДЁТ 3.1**

---

### 3.3 Go-Live Preparation

**Roadmap требует:** Live-переход $1-10K (день 180)

| Компонент | Статус | Где | Комментарий |
|-----------|--------|-----|------------|
| Live-адрес кошелька | ❓ НЕИЗВЕСТНО | - | Есть ли уже? |
| Kill-switch на live (−5% SOFT, −10% HARD) | ✅ ЕСТЬ | ADR-034/048 | Нужно проверить на live |
| Monitoring (эвиденс vs real APY) | ❓ НЕИЗВЕСТНО | `data/equity_curve_daily.json` | Отслеживается ли калибровка? |
| Rollback plan | ❌ НЕ НАЧИНАЛАСЬ | - | Что если что-то пойдёт не так? |

**Что нужно делать:**
1. Подготовить live-адрес и контракты (неделя 1-2 месяца 6)
2. Stress-testing (месяц 6-7)
3. Go-live $1K (день 180)

**СТАТУС:** ⏳ **ЖДЁТ 3.1+3.2**

---

## 📋 Что Уже Сделано (Конкретно, Используй)

### ✅ RiskPolicy v1.0
- **Файл:** `spa_core/risk/policy.py` (59KB)
- **Версия:** v1.0 (2026-05-20, не меняется во время paper)
- **Тесты:** `test_risk_policy.py`, `test_risk_policy_gate.py` (16 тестов в spa_core/tests/)
- **Компоненты:** policy_enforcer, emergency_breakers, scoring_engine, capacity_limits, concentration_monitor
- **Свойство:** LLM FORBIDDEN, детерминированный код
- **Используется в:** Allocation Auditor (читает для проверки)

### ✅ Kill-Switch (Two-Tier)
- **Файл:** `spa_core/governance/kill_switch.py` (43KB)
- **Реализовано:** 4 триггера (drawdown ≥10%, red_flags >5, manual, sharpe <-1.0)
- **Действие:** Все позиции → Cash (allocation = {cash: 1.0})
- **Тесты:** Должны быть в governance/tests/
- **ADR:** ADR-034, ADR-048
- **Используется в:** Orchestrator (автоматическая остановка)

### ✅ Data Contracts (Уже Определены)
- **`data/adapter_status.json`** (19KB) — live APY/TVL/health по адаптерам ✅
- **`data/adapter_orchestrator_status.json`** (3.7KB) — orchestrator выход ✅
- **`data/target_allocation.json`** — целевое распределение $100K ✅
- **`data/allocation_rationale.json`** (17KB) — обоснование аллокации ✅
- **`data/risk_limits_check.json`** (1.2KB) — проверки policy ✅
- **`data/kill_switch_drill_status.json`** (505B) — kill-switch статус ✅
- **`data/agent_health.json`** (22KB) — health статус агентов ✅
- **`data/site_freshness_report.json`** — Site Custodian выход ✅

**Новые контракты для AI1:**
- ❌ **`data/allocation_audit_daily.json`** — НУЖНО ОПРЕДЕЛИТЬ (Allocation Auditor выход)
- ❌ **`data/apy_evidence.json`** — НУЖНО ОПРЕДЕЛИТЬ (APY Evidencer выход)
- ❌ **`data/tier_assessment.json`** — НУЖНО ОПРЕДЕЛИТЬ (Tier Validator выход)
- ❌ **`data/rebalance_plan.json`** — НУЖНО ОПРЕДЕЛИТЬ (Rebalance Engine выход)

### ✅ Allocation Logic (Полностью Готова)
- **Файл:** `spa_core/allocator/allocator.py` (116KB)
- **Классы:** StrategyAllocator, allocation_models
- **Модели:** equal_weight, best_apy, risk_parity, risk_adjusted, optimized_yield
- **Тесты:** `test_allocator.py`, `test_allocator_properties.py`, `test_allocator_tvl_provenance.py` (14 тестов)
- **Вспомогательные:** kelly_sizer.py, dynamic_allocator.py, rebalance_economics.py
- **Входы:** `adapter_orchestrator_status.json`, risk_policy
- **Выход:** `target_allocation.json`, `allocation_rationale.json`
- **Свойство:** RiskPolicy gate применяется после (fail-CLOSED)
- **Используется в:** Allocation Auditor (может читать target + current для сравнения)

### ✅ APY Stack (Полностью Готова)
- **33 адаптера** в `spa_core/adapters/`:
  - Aave, Compound, Morpho (Blue, Morpho), Yearn, Euler, Maple
  - Curve, Balancer, Lido, Rocket, Pendle (PT), Sky (sUSDS), Ethena (sUSDe)
  - Fluid, Hyperlend, Linea, Uniswap V3, Lendingmarkt и др.
- **DeFiLlama feed:** `defillama_feed.py` (live APY/TVL, TTL 300s)
  - Методы: `get_apy()` (decimal), `fetch_apy()` (percentage)
- **APY Aggregator:** `apy_aggregator.py` (нормализация, risk-adjusted scoring)
- **Adapter Orchestrator:** `adapter_orchestrator.py` (центральный оркестратор)
- **Выход:** `adapter_orchestrator_status.json` (health scores, APY, TVL)
- **Используется в:** APY Evidencer (читает status, добавляет evidence-levels)

### ✅ Site Custodian (Полностью Реализирована)
- **Файл:** `scripts/site_freshness_monitor.py` (800+ строк)
- **ADR:** ADR-YL-011
- **Проверяет:** Свежесть (<30h), доступность, honesty (no overstating)
- **8 fail-кодов:**
  - STALE_SNAPSHOT (>30h)
  - STALE_API (>30h)
  - SITE_BEHIND_SNAPSHOT (live ≠ repo)
  - SNAPSHOT_BEHIND_API (repo ≠ live)
  - OVERSTATED_METRIC (🔴 CRITICAL: APY > API)
  - MISSING_ASOF, UNAVAILABLE, VERIFIER_PIN_MISMATCH
- **Kill-rule:** OVERSTATED или stale >48h → degraded=true (fail-CLOSED)
- **Тесты:** `test_site_custodian_fresh_checkout.py`, `test_site_custodian_alert_humanized.py`
- **Выход:** `data/site_freshness_report.json`, `landing/src/data/track_snapshot.json`
- **Используется в:** APY Evidencer (может интегрироваться с freshness check)

### ✅ 22 Агента (Существуют и Работают)
- Основные: alpha_agent, strategy_agent (v1&v2), ceo_agent (v1&v2), architect_agent
- Research: protocol_research_agent, audit_reader_agent, risk_sentinel
- Поддержка: yield_classifier_agent, reporting_agent, incident_commander
- Используются в: Decision-making и research слоях (не в risk-gate)

---

## 🔴 Что КРИТИЧНО Брошено (Нужно Доделать)

### Ничего не брошено из AI1 — это НОВЫЙ roadmap!

Но есть **предсуществующее**, что можно переиспользовать:

| Что | Статус | Почему Брошено | Нужно Ли |
|-----|--------|----------------|----------|
| Aggressive_Lab panel | ⏸️ ЗАМОРОЖЕНО | Live-ветка работает на фиксстуре | ❌ Не нужно для AI1 |
| Rates Desk anchor mirror | ❓ UNKNOWN | Anchor unsound (open) | ❓ Может нужно для rebalance |
| Swarm (5 sleeves) | ⏸️ ADVISORY | Advisory-only, не гейтит | ❌ Не для AI1 |

---

## 📊 Очередь Задач (Priority Order)

### 🔴 MUST DO (Блокирует всё)

1. **`allocation_logic_explicit.md`** (неделя 1-2)
   - Owner + Claude пишут явное описание
   - Потолки, эвристики, исключения
   - ⏱️ 1-2 недели owner-time
   - 🚨 **Блокирует:** Allocation Auditor

2. **Allocation Auditor реализация** (неделя 3-4)
   - `spa_core/agents/allocation_auditor.py`
   - 3 теста (concentration, yield, noise)
   - ⏱️ 1 неделя Claude-time
   - 🚨 **Блокирует:** Месяц 2

### 🟡 SHOULD DO (Месяц 2)

3. **Evidence-levels стандарт** (неделя 4-6)
   - L0-L6 явно описаны
   - Freshness SLA для каждого
   - ⏱️ 3-5 дней

4. **APY Evidencer реализация** (неделя 6-9)
   - Параллельный запуск с Site Custodian
   - ⏱️ 1-2 недели

5. **Tier criteria стандарт** (неделя 6-9)
   - T1/T2/T3 явно описаны
   - Security score API проверить
   - ⏱️ 3-5 дней

6. **Tier Validator реализация** (неделя 9-12)
   - Чек-лист для проверки
   - ⏱️ 1 неделя

### 🟢 NICE TO HAVE (Месяц 3+)

7. **Rebalance Engine** (неделя 13-16)
8. **Go-Live preparation** (месяц 6+)

---

## 🔍 Результаты Исследования (Agent a9ffa... вернул результаты)

✅ **Все вопросы изучены. Вот реальное состояние:**

### 1. АГЕНТЫ (spa_core/agents/)
✅ **22 агента уже существуют** (alpha_agent, strategy_agent, ceo_agent, architect_agent, protocol_research_agent, yield_classifier_agent, risk_sentinel, audit_reader_agent, reporting_agent, incident_commander и др.)

### 2. ALLOCATION LOGIC
✅ **Полностью реализована** в `spa_core/allocator/allocator.py` (116KB)
- StrategyAllocator (canonical live-money allocator)
- Модели: equal_weight, best_apy, risk_parity, risk_adjusted, optimized_yield
- RiskPolicy gate применяется после (fail-CLOSED)

### 3. APY (spa_core/adapters/)
✅ **Полный стек существует**
- 33 адаптера (Aave, Compound, Morpho, Yearn, Euler, Maple, Pendle, Sky/sUSDS и др.)
- DeFiLlama feed (live APY/TVL, кэш 36h)
- APY aggregator (нормализация, risk-adjusted scoring)
- Adapter orchestrator (центральный оркестратор)

### 4. ТЕСТЫ
✅ **1675 файлов тестов**
- Allocator: 14 тестов (concentration, properties, evidence_gate, tvl_provenance и др.)
- Risk: 16 тестов (policy, risk_axes, risk_contribution, depeg и др.)
- Adapters: множество (sky_susds, compound_v3, pendle_pt и др.)
- Site Custodian: 4 теста (freshness, humanized alerts)

### 5. DATA CONTRACTS
✅ **650+ JSON файлов, основные:**
- adapter_status.json (live APY/TVL)
- adapter_orchestrator_status.json
- target_allocation.json (целевое распределение)
- allocation_rationale.json (обоснование)
- kill_switch_drill_status.json
- risk_limits_check.json
- agent_health.json
- site_freshness_report.json

### 6. RiskPolicy v1.0
✅ **Полностью реализована** в `spa_core/risk/policy.py` (59KB)
- Версия: v1.0 (2026-05-20)
- LLM FORBIDDEN (детерминированная логика)
- policy_enforcer, emergency_breakers, scoring_engine, capacity_limits, concentration_monitor

### 7. KILL-SWITCH
✅ **Полностью реализована** в `spa_core/governance/kill_switch.py` (43KB)
- 4 триггера: drawdown (≥10%), red_flags (>5 CRITICAL), manual, sharpe (<-1.0)
- Действие: все позиции → Cash
- LLM FORBIDDEN, atomic writes

### 8. SITE CUSTODIAN
✅ **Полностью реализована** в `scripts/site_freshness_monitor.py` (800+ строк)
- 8 fail-кодов (STALE_SNAPSHOT, STALE_API, SITE_BEHIND, OVERSTATED_METRIC и др.)
- Публикует из свежей checkout (ADR-098)
- Kill-rule: OVERSTATED или stale >48h → degraded=true (fail-CLOSED)

---

## 📝 Как Читать Этот Документ

**Ты агент, берёшь новую задачу?**
1. Найди в таблице свою задачу
2. Посмотри **Статус** (✅ готово / ⏳ ждёт / ❌ не начиналась)
3. Посмотри **Где** (путь к коду, если существует)
4. Посмотри **Что нужно делать** (пошагово)
5. Посмотри **Блокирует** (если я что-то жду)
6. Если статус ❌ — **начинай**
7. Если статус ⏳ — **подожди или помоги разблокировать предыдущее**

**Ты owner?**
1. Посмотри 🔴 **Что КРИТИЧНО** (красные пункты)
2. Посмотри **Инвестиция** (сколько твоего времени нужно)
3. Подпиши решение в `nimbalyst-local/tracker/owner-decision-AI1-approach-*.md`

---

## 🔄 История Изменений

| Дата | Что | Кто | Статус |
|------|-----|-----|--------|
| 2026-08-29 | Создан AI1 Audit (draft 0.1) | Claude | ⏳ Ждёт результатов agent |
| 2026-08-29 | Agent исследует кодовую базу | agent a9ff... | ⏳ В работе |
| [TBD] | Финальный аудит после results | Claude | 📋 Плановая |

---

**Статус:** 🟡 **DRAFT** — ждёт результатов исследования  
**Следующий шаг:** Agent a9ffa3633e33a7d81 вернёт результаты → обновлю таблицы
