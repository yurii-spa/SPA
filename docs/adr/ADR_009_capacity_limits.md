# ADR-009 — Capacity Limits Enforcement (MP-209)

**Статус:** Accepted  
**Дата:** 2026-06-11  
**Авторы:** MP-209 implementation  
**Тикет:** MP-209  

---

## Контекст

SPA управляет $100K виртуального USDC и планирует масштабирование до $10M+ при подтверждённом
track record. Институциональные инвесторы задают ключевой вопрос: «Как ваша стратегия масштабируется?
Что происходит с realised APY при AUM $10M?»

До MP-209 аллокатор мог разместить, например, $40K (40% портфеля) в пул с TVL $200K —
заняв 20% пула. При $10M AUM та же логика аллокации попытается разместить $4M в пул $200K TVL
(2000% от TVL — физически невозможно). Это:

1. **Market impact при выходе** — доминирование в пуле создаёт проскальзывание.
2. **Концентрационный риск** — один пул несёт непропорциональную часть AUM.
3. **Аудиторский риск** — track record с нереалистичными позициями не валиден.

MP-209-prep (SPA-V413, уже в `done`) создал аналитику capacity-adjusted APY.
MP-209 вводит детерминированный enforcement.

---

## Решение

### Правило

**Позиция SPA в одном протоколе не должна превышать `MAX_CAPACITY_PCT = 1%` от TVL пула.**

```
max_deployable_usd = pool_tvl_usd × 0.01
```

При $100K портфеле и типичном пуле $5M TVL (минимум RiskPolicy) — лимит $50K,
то есть для текущего размера портфеля правило практически никогда не срабатывает.
При $10M AUM лимит $50K становится реально ограничивающим и заставляет диверсифицировать.

### Исключение для крупных T1 пулов

T1 адаптеры с TVL ≥ $1B могут держать до **3%** TVL (вместо 1%). Обоснование:
крупные пулы (Aave V3 Ethereum с TVL ~$189M+) имеют достаточную глубину ликвидности
для слегка повышенного лимита без значимого market impact.

```
T1 + TVL ≥ $1B → max_pct = 0.03  (3%)
иначе          → max_pct = 0.01  (1%)
```

### Режим работы

**Фаза 1 (2 недели, warn-only):** нарушения логируются как предупреждения, аллокация
не блокируется. `RiskCheckResult.capacity_check` содержит детали. Аллокатор срезает
превышения в `target_usd` но не останавливает цикл.

**Фаза 2 (после 2 недель):** нарушения переводятся в `violations` (approved=False).
Требует отдельного ADR и code review Owner.

---

## Реализация

### Новый модуль: `spa_core/risk/capacity_limits.py`

Функции (все детерминированные, stdlib only):

| Функция | Назначение |
|---|---|
| `check_capacity(protocol_id, amount_usd, tvl_usd, max_pct)` | Проверка одной позиции |
| `check_all_capacities(allocation, tvl_map, max_pct)` | Проверка всего портфеля |
| `apply_capacity_caps(allocation, tvl_map, max_pct)` | Обрезание превышений (новый dict) |
| `build_tvl_map(adapter_status)` | Извлечение TVL из adapter_orchestrator_status |
| `effective_max_pct(protocol_id, tier, tvl_usd)` | T1-high-TVL исключение |

### Изменения в `spa_core/risk/policy.py`

- `RiskCheckResult` получил поле `capacity_check: dict`.
- `check_new_position()` получил параметр `check_capacity: bool = True`.
  Вызывает `check_capacity()` с `effective_max_pct()` — нарушения идут в warnings.
- `check_portfolio_health()` получил параметры `check_capacity: bool = True`,
  `tvl_map: dict | None = None`. Вызывает `check_all_capacities()` — нарушения в warnings.

### Изменения в `spa_core/allocator/allocator.py`

- `AllocationResult` получил поля `capacity_capped: bool`, `capacity_check: dict`.
- После финального расчёта `target_usd` аллокатор вызывает `apply_capacity_caps()`.
  Если TVL map пустой — пропускает (fail-safe). Ошибки логируются, не бросают.

---

## Отклонённые альтернативы

**A. Enforce сразу (блокировать при нарушении):** отклонено — нет данных о том,
как часто текущая аллокация нарушает лимит. 2 недели warn-only собирают статистику.

**B. Лимит 2% вместо 1%:** отклонено — 1% является индустриальным стандартом
для yield-стратегий; 2% слишком мягкий для track record с institutional appeal.

**C. Отдельный gate в cycle_runner:** отклонено — изменение в аллокаторе чище,
capacity cap — это constraint аллокации, а не execution gate.

---

## Rollback

Установить `check_capacity=False` при вызове `check_new_position` / `check_portfolio_health`.
В аллокаторе — убрать блок MP-209 из `allocate()`. Не требует отдельного ADR —
это возврат к pre-MP-209 состоянию.

---

## Governance

- **Изменение `MAX_CAPACITY_PCT`** → новый ADR + owner approval.
- **Переход к enforce mode (Фаза 2)** → новый ADR + минимум 1 неделя paper-тестирования.
- **LLM ЗАПРЕЩЁН** в `spa_core/risk/capacity_limits.py` — КОНСТИТУЦИОННЫЙ ИНВАРИАНТ.

---

*Обновлено: 2026-06-11 (MP-209)*
