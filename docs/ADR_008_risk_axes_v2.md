# ADR-008: Risk Policy v2 — Оси риска (credit / peg / duration / bridge)

**Статус:** Accepted  
**Дата:** 2026-06-11  
**Автор:** SPA Team (MP-208)  
**Связанные ADR:** ADR_001_initial_risk_policy.md, ADR-002-golive-transfer-rule.md

---

## Контекст

Risk Policy v1.0 (ADR-001) ограничивает концентрацию по тирам (T1 ≤ 40%, T2 ≤ 20%/35%
суммарно) и категориям (chain, L2). Она не различает **природу** риска внутри тиров:
протокол `maple` (credit risk) и `yearn` (yield-aggregator) оба T2, но несут принципиально
разные хвостовые риски. Эпизоды LUNA (май 2022), FTX (ноябрь 2022) и USDC-depeg (март 2023)
показали, что концентрация по одной оси риска может уничтожить доходность даже при
соблюдении тировых лимитов.

## Решение

Добавить **4 ортогональные оси риска** поверх существующей политики без изменения тировых
лимитов. Оси реализованы в `spa_core/risk/risk_axes.py` и интегрированы в `RiskPolicy`
через метод `check_axis_compliance()`.

### Ось 1 — CREDIT (лимит ≤ 15%)

| Параметр | Значение |
|---|---|
| Протоколы | maple, clearpool, ipor |
| Природа риска | Uncollateralized lending, counterparty defaults |
| Лимит | Суммарный вес ≤ 15% портфеля |
| Инцидент-триггер | FTX 2022: Maple заморозил выводы, некоторые заёмщики дефолтнули |

**Rationale:** Credit-протоколы доходнее (8–12% APY против 3–5% для Aave), но при системном
стрессе могут полностью остановить вывод средств. 15% — баланс между yield-uplift и защитой
от credit-event потерь.

### Ось 2 — PEG (лимит ≤ 10%)

| Параметр | Значение |
|---|---|
| Протоколы | ethena, susde, crvusd, fraxlend, frax |
| Природа риска | Peg-риск не-USDC/USDT активов |
| Лимит | Суммарный вес ≤ 10% портфеля |
| Инцидент-триггер | LUNA 2022: UST depeg → contagion на USDT/USDC; USDC depeg март 2023 |

**Rationale:** Peg-активы могут временно потерять привязку к доллару в стрессовых условиях
даже при overcollateralized дизайне. 10% — максимальная «безопасная» экспозиция при условии,
что остальные 90% держатся в USDC/USDT blue-chip протоколах.

### Ось 3 — DURATION (лимит ≤ 30% + maturity ladder ≤ 15%)

| Параметр | Значение |
|---|---|
| Источник | `exit_latency_hours` из YieldInfo (дефолт: pendle/maple/morpho_lock → 168h) |
| Duration лимит | Доля с exit > 24h ≤ 30% портфеля |
| Maturity ladder | Доля с maturity < 30 дней ≤ 15% портфеля |
| Инцидент-триггер | FTX 2022: Pendle PT ноябрьской серии заперты до истечения |

**Rationale:** Ликвидность — асимметричный актив: не нужна когда всё хорошо, критична
при стрессе. 30% в duration-протоколах — максимум при 70%-ном буфере мгновенной ликвидности.
Maturity ladder предотвращает концентрацию коротких PT (< 30 дней до экспирации), которые
несут дополнительный market-impact при ролловере.

### Ось 4 — BRIDGE (per-cap ≤ 5%, суммарно ≤ 10%)

| Параметр | Значение |
|---|---|
| Протоколы | across, stargate, layerzero |
| Per-protocol лимит | ≤ 5% портфеля |
| Суммарный лимит | ≤ 10% портфеля |
| Природа риска | Bridge exploit, liquidity fragmentation, cross-chain messaging failure |

**Rationale:** Bridge-риск — бинарный (exploit → потеря всех bridged активов). 5% per-cap
ограничивает максимальный ущерб от одного exploit. Суммарный лимит 10% отражает, что
cross-chain оперирование на paper-trading фазе — исследовательская экспозиция.

---

## Реализация

```
spa_core/risk/risk_axes.py          # чистые функции — check_*_axis(), check_all_axes()
spa_core/risk/policy.py             # RiskPolicy.check_axis_compliance(), _state_to_allocation()
                                    # RiskCheckResult.axis_checks: dict (новое поле)
spa_core/tests/test_risk_axes.py    # ≥ 25 тестов
```

### Интеграция с RiskPolicy

```python
# Standalone — для allocator
result = policy.check_axis_compliance(allocation, exit_latency_map)
if not result.approved:
    block_rebalance(result.violations)

# Inline — portfolio health check с осями
result = policy.check_portfolio_health(state, check_axes=True, exit_latency_map=latency_map)
```

### Backward compatibility

- `RiskCheckResult.axis_checks` — новое поле с `default_factory=dict`. Существующий код,
  не передающий `axis_checks=`, продолжает работать без изменений.
- `check_portfolio_health(check_axes=False)` — дефолт False, существующие тесты не затронуты.
- Тировые лимиты и все существующие проверки v1.0 — без изменений.

---

## Paper-тест

Согласно governance policy (ADR-001 §4): новые оси применяются только в режиме **warn**
первые 2 недели (2026-06-11 … 2026-06-25). Блокировки `approved=False` вводятся с
2026-06-25 после анализа логов и подтверждения Owner.

---

## Откат

Загрузить `spa_core/risk/versions/` snapshot v1.0 и убрать вызовы `check_axis_compliance`.
Бинарная совместимость сохранена (новое поле `axis_checks` опционально).

---

## Принятые компромиссы

1. **Substring-матчинг** вместо реестра: быстрее внедряется, достаточен для текущего
   набора протоколов (≤ 15). При росте > 30 протоколов заменить на явный реестр.
2. **Дефолтные латентности** для duration-протоколов: если `exit_latency_map` не передан,
   pendle/maple/morpho_lock считаются 168h. Консервативно, но безопасно.
3. **check_axes=False по умолчанию**: избегаем внезапных блокировок существующих workflow
   до окончания paper-теста.
