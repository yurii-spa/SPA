---
trackerStatus:
  type: inbox
title: "Находка петли: data/agent_registry.json: возраст 477.2ч > SLO 26ч (класс agent_regist"
status: done
source: nimbalyst
created: 2026-08-05
finding_key: "B2:stale:data/agent_registry.json"
claimed_by: cycle-128
claimed_at: 2026-08-06T03:55:19Z
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/agent_registry.json: возраст 477.2ч > SLO 26ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/agent_registry.json` · ADR-066_

---

## Закрыто циклом #128 (2026-08-06)

Производитель появился: `spa_core/monitoring/agent_registry_refresh.py`, вызывается из
**часового** `com.spa.agent_health` (новый агент СОЗНАТЕЛЬНО не заводился — деплой owner-gated,
а этот агент уже ходит в те же источники: `launchctl` + `~/Library/LaunchAgents`).
Корень был не в сломанном сборщике: `scripts/build_agent_registry.py` существовал,
детерминирован и покрыт тестами — но его не звал **никто** (последний запуск руками 17.07).
Отсутствовал не код, а вызов.

Приёмка: **482.16ч → 0.0ч** на проде · сторож `architecture_conformance` **WARN(3) → WARN(2)**
(находка `B2:stale:data/agent_registry.json` исчезла из отчёта источника — ровно критерий
закрытия) · `deployment_acceptance` OK · 20 тестов, главный проверяет **вызов** из часового
агента, а не работоспособность функции · три мутации красят цель · манифест:
`producer: null → com.spa.agent_health`.

Журнал: `docs/journal/2026-W32.md`, цикл #128.

**Двойник:** та же находка была заведена дважды — вручную (`agent-registry-has-no-producer`,
05.08) и мостом ADR-066 (`inbox-nahodka-petli-data-agent-registry-json-v`). Мост не
дедуплицировал её потому, что у ручной карточки нет `finding_key`. Работа сделана один раз,
обе карточки закрыты со ссылкой друг на друга.
