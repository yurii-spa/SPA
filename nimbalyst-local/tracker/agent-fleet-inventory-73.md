---
trackerStatus:
  type: agent
title: Свежая полная инвентаризация флота (73 агента) — что делает / жив ли / нужен ли / расход
status: backlog
source: owner-decision-2026-07-23 (расширение own-21, этап D)
created: 2026-07-23
priority: high
domain: ops (агентский контур; каждое действие — через gate + запись, инвариант #12)
---

## Зачем

Владелец (2026-07-23), цель «навести порядок / вылизать систему» (этап D пути D→B). Карта `own-21`
устарела (писалась при 54 агентах); на 23.07 во флоте **73** агента (`com.spa.*` + `com.studiobridge.*`)
— вырос на ~19 за 8 дней. 73 процесса на одном Mac Mini (SPOF из Решения 1) = риск + шум + расход.

## Что сделать

Полная инвентаризация ВСЕХ 73 агентов, по каждому:
- что делает (роль, подсистема) — сверить с `docs/AGENT_REGISTRY.md` / `data/agent_registry.json`;
- жив ли по СМЫСЛУ (даёт ли полезный вывод; судить по state-файлу, НЕ по mtime лога —
  memory `unflushed-print-in-daemon-is-invisible`);
- когда последний раз давал полезный результат;
- нужен ли (важен / в утиль / переподчинить);
- расход (частота, стоимость — особенно Claude-агенты вроде novel-edge-rnd).

Выход: обновлённый `docs/AGENT_REGISTRY.md` + список кандидатов на выгрузку (owner-gated) +
классификация fail-OPEN/зомби (memory `fail-open-monitor-class`).

## Как понять, что готово

Каждый из 73 агентов классифицирован (важен/утиль/переподчинить) с доказательством «жив по смыслу»;
кандидаты на выгрузку вынесены владельцу карточкой; реестр обновлён.

## Уже сделано в рамках own-21 (2026-07-23)

- ✅ `checkpoint-7day` выгружен (spent one-shot): bootout + plist в `data/retired_plists_backup/` +
  добавлен в `RETIRED_LABELS` + закомментирован в `install_all_agents.sh`.
- ✅ roadmap-loop — НЕ возобновляем (подтверждено владельцем; остаток в `docs/ROADMAP_2MONTH_EISENHOWER_v2.md`).
- ✅ 3 retired (`digest_weekly`/`tier1_digest`/`weekly_backup`) — подтверждено выгружены ранее.

## Novel-Edge R&D — разобран (2026-07-23)

- «⚡ SPA Novel-Edge R&D Daily» оказался **cloud-routine** (ID `trig_016xZei1jPzEeek3LcUvJkHV`), НЕ
  локальный агент: бежит в облаке со свежим чекаутом `yurii-spa/SPA`, дописывает `DYNAMIC_LEVERAGE_GUARDIAN.md`,
  пушит в main / PR в `novel-edge-daily`.
- ✅ **Переведён с daily на 2×/нед** (владелец 2026-07-23): cron `13 8 * * *` → `13 8 * * 2,5`
  (вт+пт 08:13 UTC), переименован в «...2x-weekly (Tue+Fri)». Следующий запуск вт 04.08.
- ⚠️ **КАНДИДАТ В УТИЛЬ:** локальный launchd `com.spa.novel_edge_rnd` (сейчас `.disabled`) — дубликат
  cloud-routine, больше не нужен. Убрать окончательно в рамках инвентаризации.
- Наблюдение: выход Novel-Edge попадает в НЕДОВЕРЯЕМЫЙ турнир (`agent-tournament-trustworthy-real-apy.md`)
  → доверять ранжированию его идей можно только после фикса турнира.

---

## Сверка 2026-08-18 — инструмент есть, критерий приёмки НЕ выполнен

Прогон мой, не отчёт.

**Что реально доставлено** (коммит `484269bfc`): `scripts/fleet_inventory.py` — инвентаризация
**по репозиторию**, stdlib, ничего не ставит и не снимает. Тесты:
`pytest spa_core/tests/test_fleet_inventory.py -q` → **17 passed in 0.55s**.

Что печатает (мой прогон `python3 scripts/fleet_inventory.py`, exit 0):

```
fleet inventory: DRIFT  (манифест 89 / plist 88 label'ов в 94 файлах / обёрток 82 / реестр 80 / retired 11)
  источник registry: stale — снимок с Mac от 2026-07-17 старше 48ч (возраст 786.8ч) — судить нельзя
  [DRIFT] manifest_without_plist (1): com.spa.morning_digest
  [DRIFT] duplicate_plist_label (6): dfb_capture · hy_cycle · lp_cycle · rules_watchdog · telegram_bot · tournament_engine
  [UNCHECKED] registry_unknown_agent / registry_record_of_retired / manifest_without_registry
```

**Почему карточка остаётся открытой (`backlog`).** Её критерий — «каждый из 73 агентов
классифицирован (важен/утиль/переподчинить) с ДОКАЗАТЕЛЬСТВОМ „жив по смыслу“». Доставленный
инструмент отвечает на другой вопрос — сходятся ли четыре ОБЪЯВЛЕНИЯ флота между собой, и сам
это говорит («инвентаризация — про объявления флота, а не про живой флот»).

**Остаток числом:** классифицировано по смыслу **0 агентов из 89 объявленных** (число 73 из
шапки карточки устарело: манифест сегодня объявляет 89, plist'ов 88 меток в 94 файлах).
Списка кандидатов на выгрузку владельцу эта работа не завела. «Жив по смыслу» измеримо только
на Маке (`launchctl list`, state-файлы, `print_stale_agent_restarts.py`) — из контейнера
недоступно.
