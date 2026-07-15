---
trackerStatus:
  type: inbox
title: Команда /status в Telegram-боте — сводка системы простым языком
status: done
source: nimbalyst
created: 2026-07-15
---

## Задание (от владельца, 2026-07-15)
Добавить в существующий Telegram-бот команду **`/status`**, которая выдаёт сводку простым
человеческим языком — чтобы можно было с телефона понять состояние системы без терминала.

## Что показывать
1. **Агенты:** сколько LaunchAgent'ов работает / всего (из `launchctl list | grep com.spa`),
   и есть ли CRITICAL в `data/agent_health.json`.
2. **Автономные сессии:** сколько живых Claude-сессий (`ps`, `claude --resume/-p`), активны ли
   roadmap-loop / novel-edge-rnd (из `AGENT_REGISTRY.md` + процессов).
3. **Очереди-карточки:** сколько карточек в каждом статусе — Owner Decisions (needs-owner / owner-done /
   ingested) и Inbox (new / in-progress / done) через `spa_core.owner_queue.list_cards`.
4. **Свежесть памяти:** когда последний раз обновлялся `docs/STATE.md` (mtime) и `docs/SYSTEM_BRIEFING.md`.

## Правила реализации
- Расширять СУЩЕСТВУЮЩИЙ бот (`spa_core/telegram/bot.py`, как сделали с `/task`) — owner-only,
  fail-safe, добавить `/status` в `register_commands`.
- Отправка — через сам бот (`send_message`, единая Telegram-власть), НЕ прямой transport.
- Формат — короткий HTML, эмодзи-статусы (✅/⚠️/⛔), без жаргона.

## Как понять, что готово (acceptance criteria)
Отправляю боту `/status` → приходит сообщение со всеми 4 блоками, числа сходятся с реальностью
(агенты, сессии, карточки, свежесть STATE). Тест на парсинг сводки зелёный.

## Что будет после
Оркестратор возьмёт задачу в работу (изолированный worktree, тесты до закрытия), закроет карточку.

## Оркестратор: выполнено (2026-07-15, сухой прогон автономного цикла)
Команда `/status` собрана: `spa_core/telegram/status_summary.py` + intercept в `bot.py` + `/status` в
setMyCommands + 3 теста (зелёные). Вывод проверен вживую (агенты/сессии/карточки/свежесть). Карточка → done.
