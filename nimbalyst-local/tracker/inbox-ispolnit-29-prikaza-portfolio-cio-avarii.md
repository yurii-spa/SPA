---
trackerStatus:
  type: inbox
title: "Исполнить §29 приказа «Portfolio CIO»: аварийный выход капитала ВЫШЕ раннего выхода EmergencyBreakers — порядок Step 2b/2c/3 (money-path, ADR-973)"
status: new
source: nimbalyst
created: 2026-11-10
priority: high
intake_kind: task
acceptance_probe: emergency_exit_outranks_the_breaker
twin_key: "sha256:708ca7f389836401700649f545db80ff4550a8e3ec0570246fc7efc7479ef232"
---

## Что случилось и почему это важно

Замер §29 приказа владельца «Portfolio CIO» (цикл #1091, ADR-973, прибор
`spa_core/analytics/emergency_mode_census.py`) нашёл две CRITICAL-инверсии в ПОРЯДКЕ шагов
дневного цикла `spa_core/paper_trading/cycle_runner.py`:

- ранний выход EmergencyBreakers (Step 2b, `return _eb_cycle_result`) стои́т ДО all-cash
  стоп-крана (Step 2c, `apply_kill_switch_override`) и ДО сделки (Step 3). При `HALT`
  (EB-01 эксплойт APY > 100 %, EB-02 каскад оракула) книга ДЕРЖИТСЯ в поражённом протоколе,
  пока датчик горит; стоп-кран, взведённый реактором угроз по тому же событию, вывести
  капитал не может;
- газ (EB-03 `PAUSE` при > 50 Gwei) тем же ранним выходом останавливает и аварийный выход —
  газ стои́т ВЫШЕ сохранности капитала, обратно §29 («сохранность капитала имеет приоритет
  над: gas · APY · break-even · cooldown · turnover»).

Вопрос владельцу «держать или выводить» НЕ задаётся: §29 на него уже отвечает. Нужен
ИСПОЛНИТЕЛЬ правки money-path.

## Что нужно сделать

Это денежный путь и risk-логика (ADR-285 предмет №1; `.claude/rules/risk-engine.md`):
исполнитель — владелец либо сессия с его явным поручением. Решение владельца уже есть (§29),
переспрашивать нельзя.

1. Переставить порядок Step 2b / 2c / 3 так, чтобы all-cash стоп-крана и де-риск исполнялись
   ДО раннего выхода EmergencyBreakers, ЛИБО расширить словарь EB `{CLEAR, PAUSE, HALT}`
   выходом (`EXIT`), который при HALT переводит книгу в кэш, а не держит её.
2. **Цена перестановки, которую обязан назвать исполнитель:** ранний выход EB защищает и от
   торговли на ИСПОРЧЕННЫХ данных (EB-05) — all-cash ВЫШЕ него означает исполнить выход на
   данных, которым EB-05 не верит. Выход в кэш не требует цен (цель = 0 у каждой позиции),
   поэтому цена приемлема; но это надо записать в ADR, а не подразумевать.
3. Тем же пушем — устаревший докстринг `apply_rtmr_posture_gate` («cycle_runner does not
   call this yet»): это касание файла гейта, отдельным пушем не делать (заказ G962 п. 4).
4. Новый ADR; прогон `spa_core/paper_trading/pre_cutover_gate.py`; тесты в обе стороны
   (HALT при открытой позиции ⇒ книга в кэше; CLEAR ⇒ порядок прежний); пороги RiskPolicy
   не трогаются; `spa_core/tests/` целиком.

## Как понять, что готово

Проба `emergency_exit_outranks_the_breaker` (реестр `card_acceptance.PROBES`) отвечает
`satisfied`: all-cash и сделка стоя́т в `cycle_runner` ДО раннего выхода EB. Сегодня —
`not_satisfied` с номерами строк (1856 / 2043 / 2268).

## Что будет после

Прибор §29 перестаёт печатать `breaker_halt_precedes_the_exit` и
`priority_outranks_capital_preservation:gas`; проба в карточке приказа закрывает ось A §29;
`CLAUDE.md` строка «реакция на деградацию автоматическая» получает оговорку про EB снятой.
