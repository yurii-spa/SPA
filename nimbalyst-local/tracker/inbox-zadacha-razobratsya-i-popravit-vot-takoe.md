---
trackerStatus:
  type: inbox
title: Задача разобраться и поправить - вот такое сообщение приходит в час несколько р…
status: done
source: telegram
created: 2026-07-31
---

## Задание (из Telegram)

Задача разобраться и поправить - вот такое сообщение приходит в час несколько раз - 🚨 Не удалось проверить, был ли сегодня цикл

📅 Last cycle: NOT MEASURED — the age of the last cycle could not be computed, so this alert does NOT claim the cycle was missed.
🔎 Reason: paper_trading_status.json exists but is not readable JSON; cycle_log.json not found
🕐 Expected: daily ~08:00 local time (launchd com.spa.daily_cycle, StartCalendarInterval — local, not UTC)
❓ Treated as a gap (fail-CLOSED): an unverifiable cycle is not a verified one.

go-live 32d
⚡ Action: check data/paper_trading_status.json first (that is what could not be read), then launchd com.spa.daily_cycle status

2026-07-31T07:47:33.153808+00:00

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Разобрано (автономный цикл #55, 2026-07-31)

**Классификация: ЗАДАЧА.** Проверка истории (шаг 1а) — NEW: цикл #43 правил ТЕКСТ этого
алерта (честное «NOT MEASURED» вместо выдуманного «999.0h ago»), но источник сообщения тогда
не искали.

**Твой цикл в порядке — врал не он.** Прод-сторож здоров и молчит: в логе каждые 5 минут
`✅ No gap — 2.9h since last cycle`, `data/cycle_gap_state.json` = `measured: true`,
`data/telegram/push_state.json` → `cycle_gap: {"state": "ok"}` (в «плохое» состояние он не
переходил вообще). Значит **прод этот алерт не отправлял ни разу**.

Сообщения тебе слал **тестовый прогон**: `spa_core/tests/test_cycle_gap_monitor.py::
TestRunCycleGapMonitorBehavior::test_never_raises_corrupt_status_json` звал сторож с
`dry_run=False` и без подмены отправителя, поэтому алерт уходил в твой настоящий чат.
Перехват транспорта на чистом `origin/main` дал сообщение, совпадающее с присланным тобой
слово-в-слово, включая `go-live 32d` — эту строку живой код сегодня выдать НЕ МОЖЕТ
(дата go-live 15.07 в прошлом ⇒ отсчёт опускается), 32 дня получаются только из
инъецированного в тесте `now = 2026-06-13`. Второй такой же тест слал `Cycle Gap Resolved`.
Каденция «несколько раз в час» объясняется без остатка: автономные циклы гоняют сюиту почти
непрерывно.

**Сделано** → карточка `agent-tests-send-live-telegram-alerts`:
страж на уровне КЛАССА (`spa_core/tests/telegram_guard.py` + autouse-фикстуры в обоих
`conftest.py`) — ни один тест репозитория больше не может достучаться до боевого Telegram;
плюс оба виновных теста сделаны герметичными без единого изменённого ассерта.
