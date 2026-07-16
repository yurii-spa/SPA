---
trackerStatus:
  type: owner-decision
title: "Флот: 7 агентов не переживут reboot (swarm+DR) — разрешить сделать reboot-safe"
status: ingested
source: audit
created: 2026-07-16
---

## Что случилось и почему это важно
Аудит флота нашёл: **7 агентов загружены, но НЕ переживут перезагрузку Mac** (нет plist в
`~/Library/LaunchAgents`, self_heal их не оживит): 5 swarm-органов (blend/brain/regime/guardian/health)
+ golive_freshness + resilience. Первый же reboot тихо убьёт весь swarm-слой и DR-rollup. Плюс был баг в
`install_all_agents.sh` (битый путь aggressive_lab/rates_desk_paper).

## Что от тебя нужно
Разреши сделать флот reboot-safe (это правка флота — по инварианту деплой ≤3 агентов через gate, поэтому
спрашиваю). Варианты: (а, рекомендую) я прогоню ПОЧИНЕННЫЙ `install_all_agents.sh` (баг уже исправлен + 5
swarm добавлены) через deploy-gate — он доустановит недостающие plist в `~/Library`; для
golive_freshness/resilience сначала реконструирую их plist (в репо отсутствуют). (б) оставить как есть
(риск: reboot убьёт swarm+DR).

## Как понять, что готово
`data/agent_registry.json` / дашборд `/admin/agents` показывает 0 «не переживёт reboot».

## Что будет после
При (а): реконструирую 2 недостающих plist, прогоняю installer через gate, проверяю реестром → 0 проблем.

## Ответ владельца (2026-07-16, в чате) → инжест
Да, сделано — реестр 0 проблем, все reboot-safe.
