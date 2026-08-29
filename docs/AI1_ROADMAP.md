# SPA: AI1 Roadmap (машиночитаемый бизнес)

**Дата:** 2026-08-29  
**Версия:** 0.1  
**Цель:** Превратить SPA из системы-с-памятью-людей в машиночитаемый yield-optimizer

---

## 📋 Текущее состояние: Что держится на памяти людей

| Процесс | Сейчас держится на | Риск | Приоритет |
|---------|-------------------|------|-----------|
| **Risk Scoring** | RiskPolicy (явно) + интуиция owner-a | Средний | 🟢 ГОТОВО |
| **Allocation Logic** | Policy + RiskConfig + эвристики desk-ов | Высокий | 🔴 КРИТИЧНО |
| **APY Truth Claim** | Evidence L0-L6 + мнение аналитиков | Высокий | 🔴 КРИТИЧНО |
| **Protocol Tier Decision** | Проверка с одобрением владельца | Высокий | 🔴 КРИТИЧНО |
| **Rebalance Trigger** | Concentration checks + yield-improvement logic | Средний | 🟡 ВАЖНО |
| **Kill-Switch Action** | Two-tier drawdown ladder (явно) | Низкий | 🟢 ГОТОВО |
| **Live Data Freshness** | Site Custodian (явно, но только мониторинг) | Средний | 🟡 ВАЖНО |

---

## 🎯 Первый Агент (Месяц 1): Allocation Auditor

### Что этот агент делает
**Диагностирует** — каждый цикл проверяет:
- Соответствие текущей аллокации RiskPolicy v1.0
- Нарушения потолков концентрации per-protocol
- Стоимость переключения vs выгода ребаланса
- История сигналов и причины отклонений

### Паспорт Агента

| Поле | Значение |
|------|----------|
| **Деловая цель** | Уменьшить риск скрытого дрейфа портфеля от политики |
| **Пользователь** | Owner (еженедельно) + оркестратор (ежедневно) |
| **Вход** | `current_allocation.json` + `risk_config.json` + `live_tvl.json` |
| **Метод** | Проверка по правилам (0 LLM) |
| **Инструменты** | Живой TVL, кэш потолков, история цен |
| **Результат** | `allocation_audit.json` |
| **Качество** | Полнота, точность, скорость |
| **Организация** | Уровень: читает + аудитирует, не меняет |
| **Эксплуатация** | Cron ежедневно 07:50, резервный сценарий вручную |

### Стандарт Результата (Контракт)

```json
{
  "audit_timestamp": "2026-08-29T08:00:00Z",
  "state": {
    "allocation_current": {...},
    "allocation_policy_compliant": {...}
  },
  "findings": [
    {
      "type": "concentration_breach",
      "protocol": "Aave",
      "current_pct": 42,
      "limit_pct": 40,
      "severity": "warning"
    }
  ],
  "rebalance_opportunity": {
    "trigger": "yield_improvement",
    "current_apy_weighted": 12.3,
    "optimal_apy_weighted": 13.8,
    "switch_cost": 45,
    "net_benefit_30d": 450,
    "recommendation": "rebalance"
  },
  "human_decision": null,
  "next_action": "await_owner_review"
}
```

### Данные и Стандарты

**Откуда берём:**
- `data/current_positions.json` (источник истины)
- `spa_core/risk/policy.py` (RiskPolicy v1.0)
- `data/adapter_status.json` (live TVL)
- `MASTER_PLAN_v1.md` (потолки, tier-ы)

**Новый контракт:**
- `data/allocation_audit_daily.json` ← создаёт этот агент
- `data/rebalance_signals.jsonl` (лог всех возможностей)

### Тесты (3+)

```python
# test_allocation_auditor.py
- test_concentration_breach_detected()      # Красная зона: 45% > 40%
- test_yield_improvement_trigger()           # Оптимум 13.8% vs текущий 12.3%
- test_no_false_alarm_on_noise()             # Шум <0.5% не генерирует сигнал
```

### Развёртывание

```bash
# День 1-5: Параллельный запуск с человеком
python3 -m spa_core.agents.allocation_auditor --dry-run
  # Человек читает результаты, проверяет логику

# День 6-30: Автоматический запуск
launchctl bootstrap \
  ~/Library/LaunchAgents/com.spa.allocation_auditor.plist
```

---

## 🎯 Второй Агент (Месяц 2): APY Evidencer

### Что этот агент делает
**Отслеживает источники APY**:
- Какой адаптер вернул число
- Когда оно было получено (freshness)
- Какой evidence-level (L0-L6)
- Что изменилось vs прошлый цикл
- Есть ли расхождение между фидами

### Паспорт

| Поле | Значение |
|------|----------|
| **Деловая цель** | Защитить от скрытого стейла APY на публичной поверхности |
| **Пользователь** | Site Custodian (мониторит) + Owner (еженедельно) |
| **Вход** | `adapter_status.json` + live DeFiLlama + на-чейн RPC |
| **Метод** | Сравнение источников, проверка freshness |
| **Инструменты** | Стандарты freshness, tier-ы протоколов |
| **Результат** | `apy_evidence.json` |
| **Качество** | Полнота покрытия, задержка обнаружения stale |
| **Организация** | Только мониторит, не меняет данные |
| **Эксплуатация** | Каждый запуск цикла (08:00 по UTC) |

### Стандарт Результата

```json
{
  "cycle": 112,
  "timestamp": "2026-08-29T08:00:00Z",
  "protocols": {
    "Aave": {
      "apy_current": 12.3,
      "apy_previous": 12.1,
      "source": "adapter_aave_v2",
      "freshness_minutes": 2,
      "evidence_level": "L3",
      "is_stale": false,
      "last_verified_onchain": "2026-08-29T07:58:00Z"
    }
  },
  "anomalies": [
    {
      "type": "apy_spike",
      "protocol": "Curve",
      "change_pct": 45,
      "signal_strength": "moderate",
      "action": "flag_for_review"
    }
  ],
  "stale_count": 0,
  "evidenced_portfolio_valid": true
}
```

### Этапы внедрения

**Неделя 1:** Параллельный запуск, сравнение vs текущей Site Custodian  
**Неделя 2-4:** Автоматический мониторинг, алерты в лог  
**День 30:** Подключение к дневному циклу

---

## 🎯 Третий Агент (Месяц 3): Protocol Tier Validator

### Что этот агент делает
**Автоматизирует проверку тиров:**
- TVL ≥ $5M/пул?
- История стабильности ≥ 30 дней?
- Есть ли инциденты на-чейне?
- Security score from Certora/Immunefi?

### Паспорт

| Поле | Значение |
|------|----------|
| **Деловая цель** | Снять обязательное одобрение владельца для T1→T2 промоушена, оставить для T2→T1 |
| **Пользователь** | Owner (решение), Agent (assessment) |
| **Вход** | Live TVL + history + security APIs |
| **Метод** | Checklist per tier + человеческое решение owner-a |
| **Результат** | `tier_assessment.json` + owner decision card |
| **Качество** | Полнота критериев, время на проверку |
| **Организация** | Собирает данные, owner решает |
| **Эксплуатация** | По запросу + ежемесячный audit всех tier-ов |

---

## 📅 Дорожная карта 30/90/180/365

### **МЕСЯЦ 1 (0-30 дней): Диагностика + Первый Агент**

#### Неделя 0-1: Диагностика (Allocation Auditor)
- ✅ Явно описать текущую логику аллокации
- ✅ Выписать все потолки, эвристики, исключения
- ✅ Создать тесты для текущего поведения
- ✅ Написать паспорт агента
- ✅ Подготовить `allocation_audit_daily.json` (контракт)

**Выход:** `docs/allocation_logic_explicit.md` (2K слов)

#### Неделя 1-3: Реализация
- ✅ Реализовать allocation_auditor.py (0 LLM)
- ✅ Параллельный запуск: агент + человек
- ✅ Тесты: concentration, yield-opportunity, noise
- ✅ Логирование в `data/allocation_audit_daily.json`

**Выход:** 3 теста GREEN, 30 дней параллельных прогонов

#### Неделя 3-4: Hyperparameters
- ✅ Настроить пороги noise-фильтра (сейчас 0.5%?)
- ✅ Подтвердить cost_of_switch (газ, спред)
- ✅ Валидировать историю (последние 10 циклов)

**Выход:** `allocation_auditor` готов к автоматизации

---

### **МЕСЯЦ 2 (30-90 дней): Site Custodian + Tier Assessment**

#### Неделя 4-6: APY Evidencer
- ✅ Явно описать evidence-levels (L0-L6)
- ✅ Для каждого протокола: freshness SLA, источник истины
- ✅ Реализовать APY Evidencer (читает adapter_status + на-чейн)
- ✅ Параллельный запуск с Site Custodian (текущий)

**Выход:** `data/apy_evidence.json`, сравнение vs текущего

#### Неделя 6-9: Protocol Tier Validator
- ✅ Выписать все критерии для T1 vs T2 vs T3
- ✅ Реализовать чек-лист (TVL, history, security)
- ✅ Создать карточку `owner-decision-tier-X` на проверку
- ✅ Тесты: нарушение TVL-floor, новый протокол, демоушен

**Выход:** Проверка тира = человек читает `tier_assessment.json`

#### Неделя 9-12: Интеграция
- ✅ Подключить оба агента к daily_cycle (шаг 0a)
- ✅ Алерты в Telegram (stale APY, tier breach)
- ✅ История `data/protocol_tiers.jsonl` (кто и когда переместился)

**Выход:** Дневной цикл пишет 3 артефакта: audit, evidence, tier-decision

---

### **МЕСЯЦ 3-6 (90-180 дней): Автоматизация Ребаланса**

#### Неделя 13-16: Rebalance Engine
- ✅ Явно: что такое «оптимальная аллокация»?
  - RiskPolicy потолки (твёрдые)
  - Yield-improvement порог (гистерезис 0.5%)
  - Hold-time минимум (чтобы не делать чёрн)
- ✅ Реализовать dry-run ребаланса
- ✅ Тесты: безопасность, cost-benefit, edge cases (TVL вырос/упал)

**Выход:** `rebalance_plan.json` (что и на сколько менять)

#### Неделя 17-20: Orchestrator Integration
- ✅ Подключить Rebalance Engine в оркестратор
- ✅ Шаг 1.5: оркестратор читает `rebalance_plan`, проверяет, выполняет
- ✅ Kill-switch cuts всё (HARD ≥10% drawdown → all-cash)

**Выход:** Ребаланс автоматический, kill-switch работает

#### Неделя 21-26: Monitoring + Contracts
- ✅ Каждый агент пишет свой контракт в JSON
- ✅ Оркестратор проверяет: все ли факты собраны?
- ✅ Если какая-то проверка не прошла → HALT

**Выход:** Fail-CLOSED: система не двигает капитал на неполных данных

---

### **МЕСЯЦ 6-12 (180-365 дней): Масштабирование + Go-Live**

#### Месяц 6: Live-переход
- ✅ Переключение на реальный USDC (малый объём $1K)
- ✅ То же самое: same contracts, same agents, same checks
- ✅ Kill-switch SOFT −5% / HARD −10% работает на живых деньгах

**Выход:** Go-live на $1,000 USDC

#### Месяц 7-9: Масштабирование
- ✅ Увеличение капитала $1K → $10K → $50K
- ✅ Мониторинг: APY за деньги vs бумаги (calibration)
- ✅ Новые агенты: Liquidation Detector, Bridge Monitor

**Выход:** $50K живого капитала, стабильный трек

#### Месяц 10-12: Hardening
- ✅ Code-review all agent code (security)
- ✅ Stress-testing: drawdown simulation, feed outage
- ✅ 365-day SLA проверка: uptime ≥ 99.5%

**Выход:** Ready for $100K+ производства

---

## 📊 Метрики Успеха по Этапам

### Месяц 1 (30d)
```
✓ Allocation Auditor: 30 дней параллельного запуска
✓ 100% согласованность с ручной проверкой owner-a
✓ 0 ложных положительных сигналов
✓ Время выполнения < 5 сек
```

### Месяц 2 (90d)
```
✓ APY Evidencer работает автоматически
✓ Site Custodian обновляется за 2 минуты до цикла
✓ Tier Validator: 100% критериев покрыто
✓ 0 stale APY на публичной поверхности (SPA Stack)
```

### Месяц 3 (180d)
```
✓ Ребаланс полностью автоматический
✓ Kill-switch срабатывает < 10 сек
✓ Fail-CLOSED: нет капитала на неполных данных
✓ Uptime цикла ≥ 99%
```

### Месяц 12 (365d)
```
✓ Go-Live $100K+ реального капитала
✓ Трек 30+ дней, APY соответствует бумаге (±2%)
✓ 0 инцидентов от скрытого дрейфа политики
✓ Масштабируемость: добавление нового протокола < 1 дня
```

---

## 🔐 Контракты (что каждый агент гарантирует)

| Агент | Гарантия | Если нарушено |
|-------|----------|---------------|
| **Allocation Auditor** | Каждый день выдаст audit.json или STOP | Цикл ждёт |
| **APY Evidencer** | Покроет 100% протоколов L0-L6 или FLAG | Не включаем в аллокацию |
| **Tier Validator** | Выдаст checklist или PENDING_REVIEW | Тир не меняется |
| **Rebalance Engine** | Dry-run плана или ABORT | Kill-switch активирует |
| **Orchestrator** | Запустит шаги 0-3 или HALT_AND_ALERT | Owner в курсе |

---

## 🎓 Как это читать owner-у

| Спрашивает Owner | Где найти ответ |
|-----------------|-----------------|
| «Почему текущая аллокация именно такая?» | `allocation_audit_daily.json` |
| «Какой APY мы используем в расчётах?» | `apy_evidence.json` + источник |
| «Почему этот протокол в T2, а не T1?» | `tier_assessment.json` + история в JSONL |
| «Почему нет ребаланса на +3% APY?» | `rebalance_signals.jsonl` (gist_cost > benefit) |
| «Как работает kill-switch?» | `data/emergency_status.json` + ADR-034 |

---

## ⚠️ Риски и Как Их Снизить

### Риск: Агент отказывает в критический момент
**Снижение:** Fail-CLOSED + дублирование check-ов
```bash
Если Allocation Auditor не ответит за 10 сек → HALT
```

### Риск: Данные противоречивые (разные фиды)
**Снижение:** Quorum + tie-breaker
```json
{
  "apy_sources": [
    {"adapter": "aave_v2", "apy": 12.3, "weight": 0.6},
    {"adapter": "defillama", "apy": 12.1, "weight": 0.3},
    {"adapter": "onchain", "apy": 12.25, "weight": 0.1}
  ],
  "consensus_apy": 12.24,
  "dissent": false
}
```

### Риск: Проверка с одобрением владельца станет узким местом
**Снижение:** Асинхронный workflow
```
Агент готовит tier_assessment ночью → Owner смотрит с утра → Решение в API
```

---

## 📋 Чек-лист Запуска

- [ ] Месяц 1
  - [ ] `allocation_logic_explicit.md` написана
  - [ ] `allocation_auditor.py` на 80%
  - [ ] 3 теста (concentration, yield, noise) GREEN
  - [ ] 7 дней параллельного запуска пройдено
  
- [ ] Месяц 2
  - [ ] APY Evidencer работает параллельно Site Custodian
  - [ ] Tier Validator выдаёт checklist
  - [ ] Оба интегрированы в daily_cycle
  
- [ ] Месяц 3
  - [ ] Ребаланс dry-run готов
  - [ ] Fail-CLOSED проверка работает
  - [ ] Allocation Auditor + Tier Validator: 100% автоматизм

- [ ] Месяц 12
  - [ ] Go-Live $100K
  - [ ] Трек APY соответствует
  - [ ] Kill-switch отработал хотя бы раз (контроль)

---

## 📚 Документы по каждому этапу

- `docs/allocation_logic_explicit.md` — явное описание
- `spa_core/agents/allocation_auditor.py` — первый агент
- `data/allocation_audit_daily.json` — контракт
- `docs/apy_evidence_standards.md` — стандарт APY
- `spa_core/agents/apy_evidencer.py` — второй агент
- `docs/tier_criteria.md` — критерии тиров
- `spa_core/agents/tier_validator.py` — третий агент
- `spa_core/strategy_lab/rebalance_engine.py` — ребаланс
- `ADR-XXX-ai1-roadmap.md` — этот роадмап

---

**Статус:** Готово к обсуждению с Owner  
**Версия следующая:** После решения на allocation_logic_explicit.md
