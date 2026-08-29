# 🎉 AI1 Roadmap: Полная Картина

**Дата:** 2026-08-29  
**Статус:** ✅ READY FOR ACTION  
**Аудит:** Полный (все 8 компонентов исследованы)

---

## TL;DR

**Хорошая новость:** Почти всё уже существует! 

SPA уже имеет **working allocation_logic, risk-policy, kill-switch, adapters, tests, monitoring**. AI1 roadmap не о переписывании с нуля — это о том, чтобы:
1. **Документировать** то что уже работает (allocation_logic_explicit.md)
2. **Обёртывать** в явные JSON контракты (allocation_audit.json, apy_evidence.json и т.д.)
3. **Масштабировать** через агентов (Allocation Auditor, APY Evidencer, Tier Validator)

**Сроки:**
- ✅ Сейчас: документирование allocation_logic (1-2 недели)
- ✅ Месяц 1-2: три агента готовы
- ✅ Месяц 6: Go-Live $1K live
- ✅ Месяц 12: Go-Live $100K+ полностью автоматический

---

## 📊 Состояние по Компонентам

### МЕСЯЦ 1: Allocation Auditor

#### 1.0 allocation_logic_explicit.md
- **Статус:** 🟡 НУЖНА ДОКУМЕНТАЦИЯ (код существует, нужно описать)
- **Входы:** `spa_core/allocator/allocator.py` (116KB, работает)
- **Выход:** `docs/allocation_logic_explicit.md` (2K слов)
- **Сроки:** Неделя 1-2 сентября
- **Инвестиция:** 1-2 недели owner-time
- **Блокирует:** Allocation Auditor реализацию

**Что нужно делать:**
- Потолки из MASTER_PLAN_v1.md → в allocation_logic_explicit.md
- Эвристики ребаланса из allocation_models.py → явное описание
- История решений из docs/decisions/ → собрать в одно место
- Формат: JSON schema + примеры

#### 1.1 Allocation Auditor реализация
- **Статус:** ❌ НЕ НАЧИНАЛАСЬ (ждёт 1.0)
- **Компонент:** `spa_core/agents/allocation_auditor.py`
- **Входы:** allocation_logic_explicit.md + current_positions.json + RiskPolicy v1.0
- **Выходы:** `data/allocation_audit_daily.json`
- **Тесты:** 3 (concentration_breach, yield_improvement, noise_filter)
- **Сроки:** Неделя 3-4 сентября
- **Инвестиция:** 1 неделя Claude-time
- **Блокирует:** Месяц 2

**Что нужно сделать:**
1. Реализовать `spa_core/agents/allocation_auditor.py` (read-only, no LLM)
2. Напиcать 3 теста
3. Параллельный запуск 30 дней (агент + owner смотрит)
4. После валидации → встраивать в daily_cycle (step 1.0)

---

### МЕСЯЦ 2: APY Evidencer + Tier Validator

#### 2.1 Evidence-levels стандарт
- **Статус:** 🟡 НУЖНА ДОКУМЕНТАЦИЯ (структура предполагается, не полная)
- **Входы:** `docs/37` (упоминается)
- **Выход:** `docs/apy_evidence_standards.md`
- **Сроки:** Неделя 4-6
- **Инвестиция:** 3-5 дней

#### 2.2 APY Evidencer реализация
- **Статус:** ❌ НЕ НАЧИНАЛАСЬ (ждёт 2.1)
- **Компонент:** `spa_core/agents/apy_evidencer.py`
- **Входы:** adapter_orchestrator_status.json + evidence_standards
- **Выходы:** `data/apy_evidence.json`
- **Работает параллельно:** с Site Custodian (30 дней валидации)
- **Сроки:** Неделя 6-9
- **Инвестиция:** 1-2 недели

#### 2.3 Tier criteria стандарт
- **Статус:** 🟡 НУЖНА ДОКУМЕНТАЦИЯ (T1/T2/T3 критерии разбросаны)
- **Входы:** MASTER_PLAN_v1.md, policy.py, ADR-074/076 и др.
- **Выход:** `docs/tier_criteria.md`
- **Сроки:** Неделя 6-9
- **Инвестиция:** 3-5 дней

#### 2.4 Tier Validator реализация
- **Статус:** ❌ НЕ НАЧИНАЛАСЬ (ждёт 2.3)
- **Компонент:** `spa_core/agents/tier_validator.py`
- **Входы:** adapter_orchestrator_status.json + tier_criteria.md
- **Выходы:** `data/tier_assessment.json` (чек-лист для проверки)
- **Сроки:** Неделя 9-12
- **Инвестиция:** 1 неделя

---

### МЕСЯЦ 3+: Rebalance Engine + Go-Live

#### 3.1 Rebalance Engine (Dry-Run)
- **Статус:** ❌ НЕ НАЧИНАЛАСЬ (ждёт 1.1)
- **Компонент:** `spa_core/strategy_lab/rebalance_engine.py` (или allocator enhancement)
- **Входы:** allocation_audit + adapter_orchestrator_status + kelly_sizer
- **Выходы:** `data/rebalance_plan.json` (что менять, на сколько)
- **Сроки:** Неделя 13-16
- **Инвестиция:** 1-2 недели

#### 3.2 Orchestrator Integration
- **Статус:** ✅ СУЩЕСТВУЕТ (cycle_runner.py)
- **Что добавить:** Шаг 1.5 (выполнение dry-run плана)
- **Сроки:** Неделя 17-26

#### 3.3 Go-Live $1K-$100K
- **Статус:** ⏳ ПОДГОТОВКА (день 180)
- **Что нужно:** Stress-testing, rollback-plan, live-адрес
- **Сроки:** День 180-365

---

## ✅ Что УЖЕ Существует (НЕ Переделывать)

### Инварианты (Работают)
| Компонент | Статус | Файл | Тесты | Примечание |
|-----------|--------|------|-------|-----------|
| RiskPolicy v1.0 | ✅ | `spa_core/risk/policy.py` | ✅ 16 тестов | LLM FORBIDDEN, детерминированный |
| Kill-Switch (4 триггера) | ✅ | `spa_core/governance/kill_switch.py` | ✅ | Drawdown, red_flags, manual, sharpe |
| Allocation Logic | ✅ | `spa_core/allocator/allocator.py` | ✅ 14 тестов | 5 моделей, ready_for_live |
| APY Stack (33 адаптера) | ✅ | `spa_core/adapters/` | ✅ | DeFiLlama + on-chain feeds |
| Site Custodian | ✅ | `scripts/site_freshness_monitor.py` | ✅ 4 теста | 8 fail-кодов, fail-CLOSED |
| 22 Агента | ✅ | `spa_core/agents/` | ✅ | Research/decision слои (не risk) |

### Data Contracts (Определены)
| JSON | Размер | Статус | Используется |
|------|--------|--------|-------------|
| adapter_status.json | 19KB | ✅ | Adapter orchestrator output |
| target_allocation.json | - | ✅ | StrategyAllocator output |
| allocation_rationale.json | 17KB | ✅ | Обоснование решений |
| risk_limits_check.json | 1.2KB | ✅ | RiskPolicy проверки |
| kill_switch_drill_status.json | 505B | ✅ | Kill-switch статус |
| agent_health.json | 22KB | ✅ | Health monitor output |
| site_freshness_report.json | - | ✅ | Site Custodian output |

### Новые JSON Контракты (Нужно Определить)
| JSON | Для кого | Статус |
|------|----------|--------|
| allocation_audit_daily.json | Allocation Auditor | ❌ |
| apy_evidence.json | APY Evidencer | ❌ |
| tier_assessment.json | Tier Validator | ❌ |
| rebalance_plan.json | Rebalance Engine | ❌ |

---

## 🚀 Очередь Задач (В Приоритетном Порядке)

### 🔴 НЕДЕЛЯ 1-2 (КРИТИЧНО)
**Task 1.0:** allocation_logic_explicit.md
- Owner + Claude пишут явное описание
- Берём числа ИЗ КОДА (не угадываем)
- Формат: JSON schema + примеры
- 🏁 **Выход:** `docs/allocation_logic_explicit.md` (2K слов)
- ⏱️ **Инвестиция:** 1-2 недели owner-time

### 🟡 НЕДЕЛЯ 3-4 (ВЫСОКИЙ)
**Task 1.1:** Allocation Auditor реализация
- Зависит от: 1.0 ✅
- Компонент: `spa_core/agents/allocation_auditor.py`
- 🏁 **Выход:** Готов к параллельному запуску
- ⏱️ **Инвестиция:** 1 неделя Claude-time

### 🟡 НЕДЕЛЯ 5-12 (ВЫСОКИЙ)
**Task 2.1-2.4:** APY Evidencer + Tier Validator
- 2.1: Evidence-levels стандарт
- 2.2: APY Evidencer реализация
- 2.3: Tier criteria стандарт
- 2.4: Tier Validator реализация
- 🏁 **Выход:** Site Custodian автоматизирована, проверка → 30 мин

### 🟢 НЕДЕЛЯ 13+ (СТАНДАРТНЫЙ)
**Task 3.1+:** Rebalance Engine + Go-Live подготовка

---

## 📋 Что НЕ Нужно Делать

❌ **Переписывать RiskPolicy** — работает, трогать только для новых требований  
❌ **Переписывать Kill-Switch** — работает, меняем только пороги через ADR  
❌ **Переписывать Allocation Logic** — работает, документируем и обёртываем  
❌ **Переписывать Adapters** — работают, нужна только интеграция evidence-levels  
❌ **Переписывать Site Custodian** — работает, нужна только интеграция в AI1  

---

## 🎯 Почему Этот Roadmap Хорош

✅ **Incrementally** — месяц за месяцем, не big-bang  
✅ **Safe** — fail-CLOSED гарантии на каждом шаге  
✅ **Reuses existing** — не переписывает что работает  
✅ **Documents existing** — делает явным то что неявно  
✅ **Scales** — go-live на $100K+ без перегруза owner  
✅ **Testable** — метрики и тесты на каждом этапе  

---

## 📖 Документы для Чтения

**Для Owner (30 мин):**
1. `AI1_ONE_PAGER.md` (5 мин)
2. `QUICKSTART.md` → раздел для Owner
3. `owner-decision-AI1-approach-*.md` → подпишите решение

**Для Разработчика (20 мин):**
1. `AI1_QUICKSTART.md` (10 мин)
2. `AI1_AUDIT.md` → найдите свою задачу

**Для TL/Архитектора (1 час):**
1. `AI1_ROADMAP.md` (30 мин) — полный план
2. `ADR-AI1-004.md` (20 мин) — почему это решение
3. `AI1_AUDIT.md` (10 мин) — статус каждого пункта

---

## 🎬 Следующее Действие

**СЕЙЧАС:**
1. Owner прочитай `AI1_ONE_PAGER.md` ✅
2. Owner подпиши карточку владельца ✅
3. Если **Вариант A** → начинаем неделю 1

**НЕДЕЛЯ 1-2:**
- Owner + Claude: пишут `allocation_logic_explicit.md`

**НЕДЕЛЯ 3-4:**
- Claude: реализует `allocation_auditor.py`

**МЕСЯЦ 2-3:**
- Агенты 2, 3, 4 за шагом

**ДЕНЬ 180:**
- 🚀 Go-Live $1K live

---

## 📞 Если Вопросы

| Вопрос | Ответ |
|--------|--------|
| Это займёт 12 месяцев? | Да, но incrementally. День 180 уже $1K live. |
| Мы теряем что-то существующее? | Нет, переиспользуем 95% кода. Только документируем и обёртываем. |
| Это сложно? | Нет, это **сборка** того что уже есть. Allocation logic работает, нам нужна только **её документация**. |
| Что если что-то пойдёт не так? | Fail-CLOSED гарантии на каждом шаге. Агент отказывает, не угадывает. |

---

**Версия:** 1.0  
**Статус:** ✅ READY FOR ACTION  
**Ответственный:** Owner (решение) + Claude (реализация)
