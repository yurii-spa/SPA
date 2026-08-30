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

## Читатели артефакта (ответ владельца 30.08: «а кто будет с агентом общаться? CIO?»)

Общение — файлом (files-first): агент пишет `data/gas_price_history.json`, читатели забирают.
Подключать в этом порядке, ПОСЛЕ активации:

1. **CIO = com.spa.io_chief_investment (уже active в репо, такт 5 мин, ADR-104)** — газ
   становится седьмым входом рядом с liquidity/market_regime: `read_feed()` харнесса
   (fail-CLOSED, staleness ⇒ UNKNOWN), режим cheap/normal/expensive входит в вердикт
   `chief_investment.json`. Advisory читает advisory — разрешено. В манифесте — в `consumes`
   CIO, `consumer_required: true` у газ-агента.
2. **Дневной Telegram-отчёт** — строка о газе для владельца (паттерн ADR-170: строка в
   существующем отчёте, не новый канал; затяжное `unchecked` должно быть видно человеку).
3. **Конечная цель (отдельный ADR, money-path):** `rebalance_economics`/`cost_model` берёт
   ИЗМЕРЕННЫЙ газ вместо константы $12 — детерминированно, LLM запрещён; CIO туда не садится,
   гейтит по-прежнему только RiskPolicy v1.0.

Примечание: владелец параллельно проектирует «своего CIO» в соседнем чате — когда доедет до
репо, вливать в существующий `spa_core/investment_os/` контур, НЕ второй копией (источник
правды — git; по чату не действовать).

Связано: ADR-182/183, `inbox-l2-gas-monitory-molcha-predyavlyayut-fallback`
(вывод трёх старых мониторов — после активации).
