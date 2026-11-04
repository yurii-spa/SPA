# STUDIO-TRUTH-AND-OWNER-CONTROL-01 · план релиза и отката

**Ничего не влито.** Слияние в `main` — production change даже без перезапуска (агенты сами синхронизируют
прод-дерево с `origin/main` за ≤10 мин), поэтому каждая стадия ждёт отдельного разрешения владельца.
Поставка — через PR (правило `freeze-main-phase0`: PR обязателен), не прямым пушем.

## Состав

| Репозиторий | Ветка | Что меняет в проде |
|---|---|---|
| SPA (GitHub) | `truth/owner-control-01` → PR в `main` | read models пульта (`mission_control`, `company_truth`, `owner_view`, `trading_engines`, `director_report`, `mission_ui`), экраны SPA-бота (`views/home`, `views/golive`, `views/_base`), досылка кнопок (`owner_decisions`, `bot.py`), сторож сайта (`scripts/site_freshness_monitor.py`), подписи годовых (`investment_cio/sources_summary`), `read_model.signal_events`, `utils/presentation.ru_plural` |
| earn-defi (GitHub) | `truth01/alert-state-change` | `earn_defi/monitoring.py` (повтор по состоянию) |
| Studio Bridge (локальный, без remote) | `b19.7-truth-owner-control` | `cockpit_projection`, `cockpit_view`, `ru_view`, `owner_control`, `telegram_runtime` |

Не затронуто: RiskPolicy/RiskConfig, kill_switch, allocator, cycle_runner, стратегии, ставки, позиции, `landing/`,
расписания launchd, Keychain.

## Стадии

**A · Safety & Truth (SPA PR).** Состав — вся ветка SPA (стадии A и C в SPA неразделимы по файлам: одни и те же
`mission_control`/`owner_view`).
* Перезапуски: `mission_control` пересоберёт пульт сам (5 мин); `telegram_bot` — долгожитель, новый код получит
  после перезапуска сторожем `telegram_health` (сам, ADR-117) или `launchctl kickstart -k`; `mission_server` не
  меняется — перезапуск не нужен.
* Критерий успеха: на пульте «Главное сейчас» — блокировка earn-defi; «Вопросов к вам нет; ещё 2 без названной темы» (те же 2, что «Мои решения» в боте); дисковых вопросов
  нет; «Версия системы» = код флота; бот `/start` — строка «Движки ⛔ earn_defi: INCIDENT KC-1».
* Стоп: `deployment_acceptance` ≠ OK · пульт не собирается (`mission_control` код ≠ 0) · бот молчит > 5 мин.
* Откат: `git revert -m 1 <merge>` в PR-е отката; флот подтянет прежний код сам.

**B · Telegram reliability.**
* earn-defi: слить `truth01/alert-state-change` в `main` earn-defi (свой PR). Эффект — следующий прогон
  `com.earn-defi.daily` (12:10/22:10) промолчит о неизменном INCIDENT; напоминание через 72 ч после последней
  доставки. Перезапусков нет. Откат — revert.
* Bridge: перевести `~/Documents/studio_bridge` на ветку `b19.7-truth-owner-control` (в основном дереве лежат 4
  чужие незакоммиченные правки — сначала их владелец/сессия решает судьбу) и перезапустить
  `com.studiobridge.telegram` (долгожитель). Откат — `git checkout main` + перезапуск.

**C · Trading & owner visibility** — уже в SPA PR (стадия A): лента сигналов, 5 из 5, версии, OFF-функции.

## Что владелец делает
1. Разрешение на слияние SPA PR (стадия A+C).
2. Разрешение на слияние earn-defi ветки.
3. Разрешение на переключение Bridge и перезапуск его бота.
4. Отдельно (не QA): снять ли KC-1 (карточка в пакете вопросов).

## Не сделано этой программой (честно)
* Мобильная проверка 296/390/430 px — автоматического браузерного контура нет (не ставили); ручная проверка
  владельцем с iPhone остаётся ручной.
* Полная вычитка RU/EN всех экранов; форматы денег/процентов — только найденные места.
* `resolve("cycle_failed")` в `cycle_runner` — денежный путь, отдельная задача.
* Копия сторожа сайта в GitHub Actions — без памяти отпечатка (повтор раз в 6 ч из CI остаётся).
* Write-path управления с телефона — только RFC (OWNER_TRUTH_CONTRACT §7).
