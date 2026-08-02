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
