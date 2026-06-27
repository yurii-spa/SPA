# Зачем нужен GitHub в SPA (роль по назначению)

> Зафиксировано 2026-06-24. Источник истины по рантайму — **Mac mini** (24/7) + live API
> `api.earn-defi.com`. GitHub НЕ запускает торговлю — он обслуживает код, историю и деплой.

## ✅ Для чего GitHub используется (по назначению)

| Функция | Как |
|---|---|
| **Код и история** | Версионирование `spa_core/`, `scripts/`, документов. Основное назначение. |
| **CI / проверки** | `ci.yml`, `test.yml`, `spa-lint.yml` — pytest + lint + **запрет LLM/внешних либ** в `risk/execution` + stdlib-контракт. Это страхует правила проекта. |
| **Деплой сайта** | `deploy-landing.yml` → **earn-defi.com** (Astro-сайт: лендинг + **единый** canonical дашборд `/dashboard` + `/agents` + `/tournament`, Cloudflare Pages). **Единственный** frontend-деплой. Legacy `deploy-pages.yml` → github.io удалён 2026-06-28 (root `index.html` + `spa_frontend/` сняты). |
| **Бэкап кода** | Удалённая копия репозитория. |

## 🚫 Чем GitHub НЕ должен быть (исправлено)

- **НЕ облачный торговый раннер.** `spa-run.yml` (cron каждые 4ч) дублировал дневной цикл Mac
  mini и коммитил `data/*.json` + `spa.db` в `main` каждые 4ч → мусор в истории + гонки записи.
  **Отключён 2026-06-24** (оставлен только ручной `workflow_dispatch` как аварийный fallback).
- **НЕ хранилище рантайм-состояния.** `data/*.json`, `*.db`, `*.log` теперь в `.gitignore`
  (см. чистку 2026-06-24: снято с remote .venv_test, логи, бэкап-БД, track.db/spa.db).
  Рантайм-данные отдаёт **live API** (`/api/live/*`), не git.

## Поток

```
Mac mini (24/7)  ──код/фиксы──►  GitHub (main)  ──CI──►  проверки
   │                                  │
   │ live API :8765                   └──Pages build──►  earn-defi.com (сайт+дашборд)
   └── api.earn-defi.com (туннель) ──────────────────►  дашборд берёт ЖИВЫЕ данные
```

## Открытые улучшения (low-priority, не сделано)
- Консолидировать два autopush-механизма (`auto_push.sh`+`push_v*.sh` vs root `auto_push.py`)
  в один с **батч-коммитами** (сейчас Contents API пишет по файлу → дубль-коммиты в истории).
- Перейти на ветки + PR, чтобы CI реально гейтил (сейчас почти всё в `main` с `[skip ci]`).
- `spa_alerts.yml` (email каждые 6ч) дублирует Telegram-алерты Mac — при желании отключить.
