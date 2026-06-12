# SPA — Правила совместной работы с AI агентами

> Этот файл — живой документ. Каждое важное решение, изменение рабочего процесса или правило фиксируется здесь. Читается агентами в каждой сессии.

---

## 🔴 АБСОЛЮТНЫЕ ЗАПРЕТЫ (нарушение = стоп)

1. **Никогда не просить пользователя пушить вручную.** Autopush (com.spa.autopush) работает каждые 90 минут. Агент сам диагностирует проблемы с пушем.
2. **Никогда не встраивать PAT/токены в файлы.** Инцидент 2026-06-10 — PAT утёк в 90+ файлов.
3. **Никогда не создавать push_*.html с кредами.**
4. **LLM запрещён в risk/execution/monitoring коде** — только stdlib Python.
5. **Только атомарные записи** — tmp + os.replace, никогда прямой open(..., "w").
6. **Не импортировать** execution/risk код из paper_trading/analytics модулей.

---

## 🟡 РАБОЧИЙ ПРОЦЕСС

### Пуш в GitHub
- Autopush: `com.spa.autopush` каждые 90 минут забирает всё из `~/Documents/SPA_Claude`
- **Статус (2026-06-12):** autopush НЕ установлен — plist-шаблон с заглушкой PYTHON_PATH
- **Разовый фикс:** `bash ~/Documents/SPA_Claude/mp009_fix_launchd.command`
- После фикса агенты никогда не упоминают пуш в отчётах — он происходит автоматически

### Спринты
- Каждый спринт = один MP-xxx тикет из KANBAN.json
- Отчёт по завершении: что сделано, сколько тестов, KANBAN обновлён
- Агент сам выбирает следующую задачу без одобрения пользователя (режим "я сплю")
- Стоп только при USER ACTION блокере или реальном техническом препятствии

### Язык
- **Всегда русский** в сообщениях пользователю
- Код, комментарии, коммит-сообщения — английский

### Модели
- Архитектура/дизайн/ADR: `fable` (Claude 5.0)
- Код/тесты/инфра: `opus` (Claude 4.8)
- Быстрые задачи: `sonnet`

---

## 🟢 ИНФРАСТРУКТУРА (что и где)

| Сервис | Файл | Расписание | Лог |
|--------|------|------------|-----|
| Дневной цикл | cycle_runner.py | launchd 08:00 | /tmp/spa_cycle.log |
| Autopush | auto_push.py | launchd 90 мин | /tmp/spa_autopush.log |
| HTTP сервер | — | launchd | — |
| Cloudflare туннель | — | launchd | — |
| Агент-команда (Dev) | team_loop.py | launchd 4ч | SPA_Dev/spa_agents/logs/ |

**PAT в Keychain:** `security find-generic-password -s GITHUB_PAT_SPA -w`
**Ротация PAT:** `bash setup_pat.sh`

---

## 📋 ИСТОРИЯ КЛЮЧЕВЫХ РЕШЕНИЙ

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-10 | Перезапуск трека с нуля | Все данные до этой даты — демо/недействительны |
| 2026-06-10 | PAT инцидент — токен утёк в файлы | Запрет встраивания токенов |
| 2026-06-11 | Два проекта: SPA_Claude (prod) + SPA_Dev (dev) | Разделение production и AI-команды |
| 2026-06-11 | ADR-020 — автономная команда агентов | Агенты общаются через team_chat.json каждые 4ч |
| 2026-06-12 | Go-live перенесён на ~2026-08-01 | ADR-002 — нужно 30 честных дней трека |
| 2026-06-12 | Backlog пополнен MP-126..135 | 10 новых аналитических модулей |

---

## 🤖 КОМАНДА АГЕНТОВ (SPA_Dev)

**Файлы:** `~/Documents/SPA_Dev/agents/*.md`
**KANBAN Dev:** `~/Documents/SPA_Dev/sprints/KANBAN_DEV.json`
**Переписка:** `~/Documents/SPA_Dev/spa_agents/state/team_chat.json`
**Запуск:** launchd `com.spa.agent-team` каждые 4 часа

| Агент | Модель | Роль |
|-------|--------|------|
| orchestrator | sonnet | Координация, стендапы |
| architect | fable | Архитектурные решения, ADR |
| product_manager | fable | Роадмап, спринты, приоритеты |
| business_analyst | fable | Unit economics, investor narrative |
| backend_developer | opus | Python, тесты, адаптеры |
| frontend_developer | opus | index.html, dashboard |
| qa_engineer | opus | Тесты, регрессия |
| devops | opus | launchd, CI, инфра |
| security_reviewer | fable | Аудит, ADR безопасности |
| data_engineer | opus | Data pipeline, JSON схемы |
| technical_writer | sonnet | Документация |
| ui_ux_designer | fable | UX, дизайн-решения |

**Activation Matrix:**
- `drawdown_alert` → architect + product_manager
- `apy_below_benchmark` → product_manager
- `morning_standup` → orchestrator
- `weekly_retro` → orchestrator + product_manager
- `adapter_offline` → backend_developer

---

## 📊 СОСТОЯНИЕ ПРОЕКТА (обновляется автоматически)

- **Спринт:** v4.47 (последний завершённый)
- **Done:** 91 задача
- **Backlog:** MP-017, UA-004, UA-006 (USER ACTION) + MP-126..135 (code-ready)
- **Track start:** 2026-06-10
- **Go-live:** ~2026-08-01

---

*Обновлён: 2026-06-12. Следующее обновление — при любом изменении правил или инфраструктуры.*
