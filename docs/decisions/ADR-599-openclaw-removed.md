# ADR-599 · OpenClaw удалён: неиспользуемый агент с доступом к shell (решение владельца)

- **Статус:** Accepted
- **Дата:** 2026-10-07
- **Автор/утвердил:** владелец (явное решение о необратимом удалении); исполнила интерактивная сессия RM-TRUTH-01

## Контекст

OpenClaw — сторонний OSS-пакет `openclaw` 2026.4.15 («Multi-channel AI gateway») + `OpenClaw.app`
(`ai.openclaw.mac`), поставленный владельцем 2026-04-20, РАНЬШЕ проекта SPA. Единственный канал —
Telegram-бот, модель — локальная `ollama`. Аудит RM-TRUTH-01 (только чтение, 2026-10-06/07): реальные
сообщения через него только 21.04–02.05; ни SPA-бот, ни Bridge-бот, ни Director OS / Mission Control,
ни один LaunchAgent или скрипт от него не зависят (необязательный whisper на :8080 в
`studio_shell/voice_server.py` не поднят и имеет запасной путь). При этом у него профиль инструментов
`coding`, пустые `exec-approvals` и право Automation на Terminal — агент с доступом к shell, которым
никто не пользуется. Его Telegram-токен был засвечен в сессии 05.10 и отозван владельцем.

## Решение

Классификация **D · UNUSED / ORPHANED**. Шаг 1 (06.10): LaunchAgent `ai.openclaw.gateway` выгружен и
выключен, проверено, что SPA-бот, Bridge-бот и Mission Control не затронуты. Шаг 2 (07.10, явное
решение владельца о необратимом удалении, без архива): удалены LaunchAgent plist, `/Applications/OpenClaw.app`,
копия в `~/Downloads`, весь `~/.openclaw/` (конфиг, учётные данные, агенты, задачи, память, логи),
`~/Library` (Application Support, Caches, Preferences ×2, WebKit, HTTPStorages для `ai.openclaw.*`).
Статус компонента: **REMOVED / RETIRED**, причина — UNUSED_ORPHANED + лишняя поверхность атаки с shell.

## Последствия

- Ни одна функция SPA / Studio OS не потеряна (Telegram-управление — SPA-бот и Bridge-бот, ADR-521).
- Остаток, требующий sudo владельца: глобальный npm-пакет `/usr/local/lib/node_modules/openclaw` и CLI
  `/usr/local/bin/openclaw` (принадлежат root).
- Учётные данные вне машины: в профиле агента была OAuth-авторизация **OpenAI (Codex)** — удаление
  файла её не отзывает; отозвать в настройках аккаунта OpenAI. Telegram-токен уже отозван.
- Метаданные ОС: `tccutil` не сбрасывает разрешения удалённого приложения (bundle id не резолвится) —
  возможная пустая запись в «Конфиденциальность → Автоматизация».
- Документы владельца `~/Downloads/OpenClaw_TradingAgents_Инструкция.{pdf,docx}` — не программа, оставлены.
