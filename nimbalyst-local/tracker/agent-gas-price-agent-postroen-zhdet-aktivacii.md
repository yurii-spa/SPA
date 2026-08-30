---
trackerStatus:
  type: inbox
title: "Агент цены газа построен (ADR-183) — активировать на хосте после доезда синка"
status: backlog
priority: high
created: 2026-08-30
---

## Что сделано

`spa_core/monitoring/gas_price_agent.py` + `scripts/agent_gas_price.sh` +
`launchd/com.spa.gas_price_agent.plist` + манифест (`intent: designed`) + 17 тестов.
Решение владельца — ADR-183 (вариант 3 карточки пилота: сначала агент и история газа,
целевая сеть пилота — Base).

## Что сделать (на хосте, после того как синк довезёт spa_core/ и scripts/)

1. Скопировать plist в прод (launchd/ синком НЕ возится): взять из origin
   `launchd/com.spa.gas_price_agent.plist` → `~/Library/LaunchAgents/`.
2. `bash scripts/check_agent_before_deploy.sh gas_price_agent` (гейт, инв. #12).
3. `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.gas_price_agent.plist`.
4. `python3 -m spa_core.monitoring.deployment_acceptance` — до и после (правило deployment.md).
5. Убедиться, что `data/gas_price_history.json` появился и чтения `live` (не `unchecked`).
6. ТОЛЬКО ПОСЛЕ этого: манифест `intent: designed → active`; добавить
   `com.spa.gas_price_agent: ("data/gas_price_history.json", 5400)` в AGENT_OUTPUT_FILES
   (uptime_monitor) — раньше нельзя: неустановленный агент даст ложные просрочки.
7. Через 2–4 недели live-истории — карточка владельцу «запускаем пилот на Base?»
   с измеренным распределением газа (последовательность — ADR-183).

Связано: ADR-182/183, `inbox-l2-gas-monitory-molcha-predyavlyayut-fallback`
(вывод трёх старых мониторов — после активации).
