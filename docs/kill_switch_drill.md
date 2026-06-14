# Kill-Switch Drill — MP-312

**Дата выполнения:** 2026-06-12  
**Результат:** PASS ✅  
**Время реакции:** 13ms (ограничение: <1000ms)

## Что проверялось

1. **import_risk_policy** — `RiskPolicy`, `PortfolioState`, `Position`, `RiskConfig` импортируются из `spa_core.risk.policy` без ошибок.
2. **simulate_5pct_drawdown** — симуляция портфеля с PnL = -$5,000 (drawdown = 5.0%). `RiskPolicy.check_portfolio_health()` возвращает `approved=False` с violation «KILL SWITCH TRIGGERED: portfolio drawdown 5.0% ≥ 5.0%. Close all positions.»
3. **verify_risk_gate_in_cycle_runner** — `cycle_runner.py` содержит `RiskPolicy`, вызов `_apply_risk_policy_gate` и интеграцию `kill_switch`. Risk gate активен.
4. **check_current_drawdown** — текущий equity $100,026.06 → drawdown = 0.0000% → kill-switch не тригерится (норма).
5. **verify_risk_config** — `RiskConfig.version = "v1.0"`, `max_drawdown_stop = 5%` (соответствует ADR-001).

## Как запустить повторно

```bash
cd ~/Documents/SPA_Claude
python3 scripts/kill_switch_drill.py
```

Или с указанием папки данных:

```bash
python3 scripts/kill_switch_drill.py --data-dir /path/to/data
```

## Как запустить тесты

```bash
cd ~/Documents/SPA_Claude
python3 -m unittest discover -s scripts/tests -p "test_kill_switch_drill.py" -v
```

## Известные ограничения

- Drill симулирует сценарий in-memory, не исполняет реальные транзакции и не пишет state-файлы.
- Симуляционная позиция `sim_test_protocol` вызывает также concentration breach (95% > 40%) — это ожидаемо для drill-контекста.
- Kill-switch в `spa_core.governance.kill_switch` (MP-108) использует порог **15% drawdown за 30 дней** (equity curve). Drill MP-312 проверяет **5% порог** `RiskPolicy.check_portfolio_health()` (ADR-001).
- При go-live с реальным капиталом нужен дополнительный drill с реальным broker/DEX.
- Порог drawdown: 5% (ADR-001, RiskPolicy.max_drawdown_stop).
- Версия `RiskConfig` остаётся `"v1.0"` весь paper-период; изменение → ADR.

## Структура drill

```
scripts/kill_switch_drill.py        # drill script (MP-312)
scripts/tests/test_kill_switch_drill.py  # 37 unit-тестов
docs/kill_switch_drill.md           # этот файл
```

## История drills

| Дата | Результат | Время | Equity | Кто |
|------|-----------|-------|--------|-----|
| 2026-06-12 | PASS ✅ | 13ms | $100,026.06 | automated (MP-312) |
