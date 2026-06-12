# CURRENT_STATE
> Последнее обновление: 2026-06-12 (обновляй вручную в конце каждого спринта)
> **ЧИТАЙ ЭТОТ ФАЙЛ ПЕРВЫМ** перед любой работой с проектом.

## Инфраструктура (launchd)

| Демон | Статус | Последний запуск | Комментарий |
|-------|--------|-----------------|-------------|
| com.spa.daily_cycle | ✅ РАБОТАЕТ | 2026-06-12T06:00:04Z | Ежедневный paper-trading цикл 08:00 |
| com.spa.autopush | ❌ НЕ УСТАНОВЛЕН | — | PYTHON_PATH-заглушка. Фикс: `bash mp009_fix_launchd.command` |
| com.spa.httpserver | ⚠️ ПРОВЕРИТЬ | — | HTTP дашборд localhost:8765; plist есть, статус launchd неизвестен |
| com.spa.cloudflared | ⚠️ ПРОВЕРИТЬ | — | Cloudflare tunnel; plist есть, статус launchd неизвестен |

> Для проверки реального статуса в Terminal: `launchctl list | grep com.spa`

## Push-метод

```
push_method: manual          # autopush не установлен
autopush_status: not_installed   # PYTHON_PATH-заглушка, нужен bash mp009_fix_launchd.command
push_last_success: unknown   # проверить: git log --oneline -5
push_command: python3 push_to_github.py --files <files> --message "<msg>"
```

**Правило для агента:** если autopush_status=not_installed → ПЕРВЫЙ шаг сессии: `bash mp009_fix_launchd.command` (не ждать, не спрашивать).

## Спринты

- Последний завершённый: v4.62 (2026-06-12)
- Sprint log синхронизирован: ❌ (пропущены v4.31-v4.47, задача SYS-009)
- Задач в done: 115

## Paper Trading Track

- Старт: 2026-06-10
- Дней трека: 3 (из progress_tracker.json)
- Equity: $100,026.06 (из paper_trading_status.json)
- APY сегодня: 3.1969% (из paper_trading_status.json)
- Go-live решение: 2026-07-15 (переносится если трек прерывается; ADR-002 → ~2026-08-01)

## Алерты

- Telegram: ✅ НАСТРОЕН (TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA в Keychain)
- Daily report: ❌ не активирован (dry_run). Задача MP-314.
- cycle_gap_monitor: ✅ в cycle_runner (MP-144)
- milestone_alert: ✅ в cycle_runner (MP-143)

## Активные блокеры (USER ACTION)

| Блокер | Задача | Действие | Критичность |
|--------|--------|----------|-------------|
| Запустить autopush fix | MP-313 | `bash mp009_fix_launchd.command` | P0 — без этого код не пушится автоматически |
| RPC ключи Alchemy/Infura | MP-017 | Добавить в Keychain | P1 — нужно для Pendle PT (+2-3% APY) |
| GitHub Pages | UA-004 | Settings → Pages → main/root | P1 — публичный дашборд |
| Workflow token | UA-006 | PAT с workflow scope | P2 |

## Системные долги (SYS-задачи)

Все 10 SYS-задач в KANBAN backlog. Следующие в очереди:
- SYS-003: Sprint close DoD (обновить RULES.md)
- SYS-004: Infra-first правило (обновить RULES.md)
- SYS-005: Anti-HALT протокол (обновить RULES.md)
- SYS-007: Startup protocol (обновить RULES.md)
- SYS-008: Delivery_status в KANBAN
- SYS-009: Восстановить sprint log v4.31-v4.47
