# ADR-056 — rules_watchdog circuit-breaker reads the REAL kill-switch state files

- **Статус:** Accepted (owner Variant A, 2026-07-23)
- **Контекст-источник:** карта `owner-decision-storozh-pravil-ne-vidit-stop-kran-smotri.md`.
- **Домен:** monitoring над kill-switch (read-only). **Не меняет** RiskPolicy, kill-switch execution,
  пороги ADR-034/048. Расширяет honesty-линию (fail-OPEN monitor class, циклы #29/#31/#35).

## Контекст

`com.spa.rules_watchdog` (каждые 300с) проверяет стоп-кран через `check_circuit_breaker`. Замерено
(цикл, 2026): проверка читала `data/kill_switch.json` — **имя, которого нет нигде в репо** — и поле
`max_drawdown_pct` в `paper_trading_status.json`, **которое никто не пишет**. Итог: 5-минутный сторож
бодро отвечал «стоп-кран не активен, просадка в норме» про числа, которых **ни разу не видел**. Если
бы стоп-кран реально сработал — сторож промолчал бы. Настоящее состояние пишет дневной цикл в
`data/kill_switch_status.json` (`triggered`) и `data/derisk_status.json` (`active`/`tier`/`reason`).

## Решение (Variant A)

`check_circuit_breaker` читает РЕАЛЬНЫЕ файлы:
1. `kill_switch_status.json.triggered == true` → **CRITICAL** немедленно.
2. `derisk_status.json.active == true` → **CRITICAL** (с `tier`/`reason`).
3. **Свежесть:** cycle-written файл старше `CIRCUIT_FRESH_H = 26h` → **CRITICAL «missed cycle»**
   (дневной цикл, вероятно, не отработал → posture BLIND). НЕ тихий skip.
4. Unreadable/missing/без `generated_at` → **NOT CHECKED** (fail-CLOSED), никогда не «off».
   ACTIVE-состояние выигрывает над устареванием (активный де-риск с протухшим файлом = всё равно CRITICAL).

Порогов не вводит; авторитетная лестница остаётся в `spa_core/governance/kill_switch.py`.

## Последствия

- (+) Сторож наконец делает то, ради чего создан: быстрая (5-мин) резервная доставка kill-события +
  детект пропущенного цикла. Радиус: только Telegram-алерт; ни один гейт исполнения от него не зависит,
  капитал не двигает.
- (−) Порог 26h пересекается с `cycle_gap_monitor` (ADR-нет, карта storozh-propuschennogo, Variant B,
  порог 08:00 UTC) — пересечение НАМЕРЕННОЕ (два независимых быстрых пути к «цикл не отработал»).
- Тесты: `test_rules_watchdog_honesty.py::TestCircuitBreakerHonesty` переписан со старой (мёртвой)
  модели на новую (инвариант #16 — обоснование в тесте + журнал 2026-W31). 75 passed.

## Связанные

ADR-034/048 (kill-switch ladder), карта go-live intraday drawdown
(`agent-golive-intraday-drawdown-monitor.md`), memory `fail-open-monitor-class`.
